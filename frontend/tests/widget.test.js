import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import '../widget/ia-chat-widget.js';
import {
  createFakeBackend,
  errorResponse,
  flush,
  sseResponse,
  sseText,
} from './fake-backend.js';

const STORAGE_KEY = 'ia-chat:conversation-id';
let backend;

function mount(attrs = {}) {
  const el = document.createElement('ia-chat-widget');
  el.setAttribute('backend-url', 'http://backend.test');
  el.setAttribute('streaming', 'false');
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  document.body.appendChild(el);
  return el;
}

const $ = (el, role) => el.shadowRoot.querySelector(`[data-role="${role}"]`);
const messages = (el) =>
  [...el.shadowRoot.querySelectorAll('[data-role="log"] .msg')].map((m) => ({
    sender: m.dataset.sender,
    status: m.dataset.status,
    text: m.querySelector('.body').textContent,
  }));

function key(target, k, opts = {}) {
  target.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, ...opts }));
}

async function type(el, text) {
  const input = $(el, 'input');
  input.value = text;
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

async function sendText(el, text) {
  await type(el, text);
  key($(el, 'input'), 'Enter');
  await flush();
}

beforeEach(() => {
  backend = createFakeBackend();
  globalThis.fetch = backend.fetch;
  localStorage.clear();
  document.body.innerHTML = '';
});

afterEach(() => {
  document.body.innerHTML = '';
});

describe('<ia-chat-widget>', () => {
  it('abre y cierra la ventana con el botón flotante y emite eventos', async () => {
    const el = mount();
    const events = [];
    el.addEventListener('ia-chat:open', () => events.push('open'));
    el.addEventListener('ia-chat:close', () => events.push('close'));

    const panel = $(el, 'panel');
    expect(panel.getAttribute('role')).toBe('dialog');
    expect(panel.hidden).toBe(true);

    $(el, 'launcher').click();
    expect(panel.hidden).toBe(false);
    expect($(el, 'launcher').getAttribute('aria-expanded')).toBe('true');

    $(el, 'close').click();
    expect(panel.hidden).toBe(true);
    expect(events).toEqual(['open', 'close']);
  });

  it('usa el título configurado', () => {
    const el = mount({ title: 'Ayuda' });
    expect($(el, 'panel').getAttribute('aria-label')).toBe('Ayuda');
    expect($(el, 'title').textContent).toBe('Ayuda');
  });

  it('Escape cierra y devuelve el foco al botón', async () => {
    const el = mount();
    $(el, 'launcher').click();
    key($(el, 'input'), 'Escape');
    expect($(el, 'panel').hidden).toBe(true);
    expect(el.shadowRoot.activeElement).toBe($(el, 'launcher'));
  });

  it('Enter envía y muestra la respuesta del asistente', async () => {
    const el = mount();
    $(el, 'launcher').click();
    await sendText(el, 'Hola');
    expect(messages(el)).toEqual([
      { sender: 'user', status: 'complete', text: 'Hola' },
      { sender: 'assistant', status: 'complete', text: 'Respuesta a: Hola' },
    ]);
    expect($(el, 'log').getAttribute('aria-live')).toBe('polite');
    expect(localStorage.getItem(STORAGE_KEY)).toBeTruthy();
  });

  it('Shift+Enter no envía', async () => {
    const el = mount();
    $(el, 'launcher').click();
    await type(el, 'Hola');
    key($(el, 'input'), 'Enter', { shiftKey: true });
    await flush();
    expect(backend.calls).toHaveLength(0);
  });

  it('no envía mensajes vacíos ni mayores a max-length', async () => {
    const el = mount({ 'max-length': '10' });
    $(el, 'launcher').click();
    await sendText(el, '   ');
    expect(backend.calls).toHaveLength(0);

    await sendText(el, 'x'.repeat(11));
    expect(backend.calls).toHaveLength(0);
    expect($(el, 'send').disabled).toBe(true);
    expect($(el, 'notice').textContent).toContain('10');
  });

  it('deshabilita el envío mientras espera y muestra el indicador', async () => {
    let release;
    const el = mount();
    $(el, 'launcher').click();
    const original = backend.handle.bind(backend);
    backend.handle = (method, path, init) => {
      if (path.endsWith('/messages')) {
        return new Promise((resolve) => {
          release = () => resolve(original(method, path, init));
        });
      }
      return original(method, path, init);
    };
    await type(el, 'Hola');
    key($(el, 'input'), 'Enter');
    await flush();
    expect($(el, 'send').disabled).toBe(true);
    expect($(el, 'status').hidden).toBe(false);

    release();
    await flush();
    expect($(el, 'status').hidden).toBe(true);
    await type(el, 'otra');
    expect($(el, 'send').disabled).toBe(false);
  });

  it('restaura el historial guardado al cargar', async () => {
    const api = backend;
    const created = await (await api.fetch('http://backend.test/api/v1/conversations', { method: 'POST' })).json();
    await api.fetch(`http://backend.test/api/v1/conversations/${created.id}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content: 'antes' }),
    });
    localStorage.setItem(STORAGE_KEY, created.id);
    backend.calls.length = 0;

    const el = mount();
    await flush();
    expect(messages(el).map((m) => m.text)).toEqual(['antes', 'Respuesta a: antes']);
  });

  it('descarta el id guardado si la conversación no existe', async () => {
    localStorage.setItem(STORAGE_KEY, 'vencida');
    const el = mount();
    await flush();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(messages(el)).toEqual([]);

    $(el, 'launcher').click();
    await sendText(el, 'Hola');
    expect(localStorage.getItem(STORAGE_KEY)).not.toBe('vencida');
    expect(messages(el)).toHaveLength(2);
  });

  it('crea una conversación nueva si el backend responde 404 al enviar', async () => {
    const el = mount();
    $(el, 'launcher').click();
    await sendText(el, 'uno');
    const firstId = localStorage.getItem(STORAGE_KEY);
    backend.conversations.clear(); // venció en el backend

    await sendText(el, 'dos');
    expect(localStorage.getItem(STORAGE_KEY)).not.toBe(firstId);
    expect(messages(el).at(-1).text).toBe('Respuesta a: dos');
  });

  it('"Nueva conversación" borra la actual y limpia el historial', async () => {
    const el = mount();
    $(el, 'launcher').click();
    await sendText(el, 'Hola');
    const id = localStorage.getItem(STORAGE_KEY);

    $(el, 'new').click();
    await flush();
    expect(backend.calls.at(-1)).toMatchObject({ method: 'DELETE', path: `/api/v1/conversations/${id}` });
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(messages(el)).toEqual([]);
  });

  it('usa location.origin si no se indica backend-url', async () => {
    const el = document.createElement('ia-chat-widget');
    el.setAttribute('streaming', 'false');
    document.body.appendChild(el);
    $(el, 'launcher').click();
    await sendText(el, 'Hola');
    expect(backend.calls[0].path).toBe('/api/v1/conversations');
  });

  describe('streaming (US2)', () => {
    function mountStreaming() {
      const el = mount();
      el.removeAttribute('streaming'); // por defecto: streaming activo
      return el;
    }

    function holdingStream(fragments) {
      // Responde start + fragmentos y queda abierto hasta que se aborte.
      backend.nextResponses.push((url, init) => {
        const user = { id: 'u1', role: 'user', content: 'Hola', status: 'complete' };
        const events = [['message.start', { user_message: user, assistant_message_id: 'a1' }]];
        for (const text of fragments) events.push(['delta', { text }]);
        return sseResponse([sseText(events)], { signal: init.signal, hold: true });
      });
    }

    it('muestra la respuesta de forma incremental', async () => {
      const el = mountStreaming();
      $(el, 'launcher').click();
      // Se crea la conversación antes para que la respuesta forzada sea la del mensaje.
      await el._ensureConversation();
      await type(el, 'Hola');
      holdingStream(['Primera ', 'parte']);
      key($(el, 'input'), 'Enter');
      await flush();
      const last = messages(el).at(-1);
      expect(last).toEqual({ sender: 'assistant', status: 'streaming', text: 'Primera parte' });
      expect($(el, 'stop').hidden).toBe(false);
      expect($(el, 'send').hidden).toBe(true);
    });

    it('"Detener" corta la respuesta y la marca como incompleta', async () => {
      const el = mountStreaming();
      $(el, 'launcher').click();
      await el._ensureConversation();
      holdingStream(['Texto parcial']);
      await sendText(el, 'Hola');
      $(el, 'stop').click();
      await flush();
      expect(messages(el).at(-1)).toEqual({
        sender: 'assistant',
        status: 'incomplete',
        text: 'Texto parcial',
      });
      expect($(el, 'stop').hidden).toBe(true);
      await type(el, 'otra');
      expect($(el, 'send').disabled).toBe(false);
    });

    it('completa la respuesta con message.end', async () => {
      const el = mountStreaming();
      $(el, 'launcher').click();
      await sendText(el, 'Hola');
      expect(messages(el)).toEqual([
        { sender: 'user', status: 'complete', text: 'Hola' },
        { sender: 'assistant', status: 'complete', text: 'Respuesta a: Hola' },
      ]);
      const call = backend.calls.at(-1);
      expect(call.init.headers.Accept).toBe('text/event-stream');
    });

    it('con streaming="false" usa el modo JSON', async () => {
      const el = mount(); // mount() fija streaming="false"
      $(el, 'launcher').click();
      await sendText(el, 'Hola');
      expect(backend.calls.at(-1).init.headers.Accept).toBe('application/json');
    });

    it('"Nueva conversación" durante una respuesta aborta y luego borra', async () => {
      const el = mountStreaming();
      $(el, 'launcher').click();
      const id = await el._ensureConversation();
      holdingStream(['algo']);
      await sendText(el, 'Hola');
      let deletes = 0;
      const original = backend.handle.bind(backend);
      backend.handle = (method, path, init) => {
        if (method === 'DELETE') {
          deletes += 1;
          if (deletes === 1) return errorResponse(409, 'GENERATION_IN_PROGRESS');
        }
        return original(method, path, init);
      };
      $(el, 'new').click();
      await new Promise((resolve) => setTimeout(resolve, 400));
      await flush();
      expect(deletes).toBe(2);
      expect(backend.conversations.has(id)).toBe(false);
      expect(messages(el)).toEqual([]);
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });
  });

  describe('errores y reintento (US3)', () => {
    const CODES = [
      ['LLM_UNAVAILABLE', 503, 'no está disponible'],
      ['LLM_TIMEOUT', 504, 'tardando'],
      ['LLM_INVALID_RESPONSE', 502, 'inválida'],
    ];

    for (const [code, status, text] of CODES) {
      it(`ante ${code} muestra un aviso con Reintentar que no duplica la pregunta`, async () => {
        const el = mount();
        const errors = [];
        el.addEventListener('ia-chat:error', (e) => errors.push(e.detail));
        $(el, 'launcher').click();
        await el._ensureConversation();
        backend.nextResponses.push(() => errorResponse(status, code, 'mensaje del servidor'));
        await sendText(el, 'Hola');

        expect($(el, 'notice').textContent).toContain(text);
        expect($(el, 'retry').hidden).toBe(false);
        expect(errors).toEqual([{ code, message: expect.any(String), correlationId: 'test-corr' }]);
        await type(el, 'x');
        expect($(el, 'send').disabled).toBe(false);

        // El backend guardó la pregunta; el reintento regenera la respuesta.
        const conv = backend.conversations.get(localStorage.getItem(STORAGE_KEY));
        conv.messages.push({ id: 'u9', role: 'user', content: 'Hola', status: 'complete' });
        $(el, 'retry').click();
        await flush();
        expect(backend.calls.at(-1).path).toMatch(/\/messages\/retry$/);
        expect(messages(el).map((m) => m.text)).toEqual(['Hola', 'Respuesta a: Hola']);
        expect($(el, 'notice-box').hidden).toBe(true);
      });
    }

    it('ante un error de red muestra Reintentar', async () => {
      const el = mount();
      $(el, 'launcher').click();
      await el._ensureConversation();
      backend.nextResponses.push(() => {
        throw new TypeError('Failed to fetch');
      });
      await sendText(el, 'Hola');
      expect($(el, 'notice').textContent).toContain('conectar');
      expect($(el, 'retry').hidden).toBe(false);
    });

    it('si el stream se corta con texto, lo conserva como incompleto sin Reintentar', async () => {
      const el = mount();
      el.removeAttribute('streaming');
      $(el, 'launcher').click();
      await el._ensureConversation();
      backend.nextResponses.push(() =>
        sseResponse([
          sseText([
            ['message.start', { user_message: { id: 'u', role: 'user', content: 'Hola', status: 'complete' }, assistant_message_id: 'a' }],
            ['delta', { text: 'Mitad de' }],
          ]),
        ]),
      );
      await sendText(el, 'Hola');
      expect(messages(el).at(-1)).toEqual({ sender: 'assistant', status: 'incomplete', text: 'Mitad de' });
      expect($(el, 'notice').textContent).toContain('incompleta');
      expect($(el, 'retry').hidden).toBe(true);
    });

    it('ante GENERATION_IN_PROGRESS avisa que hay otra respuesta en curso', async () => {
      const el = mount();
      $(el, 'launcher').click();
      await el._ensureConversation();
      backend.nextResponses.push(() => errorResponse(409, 'GENERATION_IN_PROGRESS'));
      await sendText(el, 'Hola');
      expect($(el, 'notice').textContent).toContain('otra pestaña');
      expect($(el, 'retry').hidden).toBe(true);
      await type(el, 'x');
      expect($(el, 'send').disabled).toBe(false);
    });

    it('muestra los mensajes con error del historial', async () => {
      const created = await (await backend.fetch('http://backend.test/api/v1/conversations', { method: 'POST' })).json();
      backend.conversations.get(created.id).messages.push(
        { id: 'u', role: 'user', content: 'Hola', status: 'complete' },
        { id: 'a', role: 'assistant', content: '', status: 'error', error_code: 'LLM_TIMEOUT' },
      );
      localStorage.setItem(STORAGE_KEY, created.id);
      const el = mount();
      await flush();
      expect(messages(el).at(-1).status).toBe('error');
      expect(messages(el).at(-1).text).toContain('No se pudo');
      expect($(el, 'retry').hidden).toBe(false);
    });
  });

  it('muestra el error de la API sin bloquear el chat', async () => {
    const el = mount();
    $(el, 'launcher').click();
    backend.nextResponses.push(() => errorResponse(500, 'INTERNAL_ERROR', 'Falló algo.'));
    await sendText(el, 'Hola');
    expect($(el, 'notice').textContent).toContain('Falló algo.');
    await type(el, 'de nuevo');
    expect($(el, 'send').disabled).toBe(false);
  });
});
