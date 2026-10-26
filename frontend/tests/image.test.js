import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '../widget/ia-chat-widget.js';
import { createFakeBackend, errorResponse, flush, jsonResponse } from './fake-backend.js';

let backend;
let objectUrls;

function mount(attrs = {}) {
  const el = document.createElement('ia-chat-widget');
  el.setAttribute('backend-url', 'http://backend.test');
  el.setAttribute('streaming', 'false');
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  document.body.appendChild(el);
  return el;
}

const $ = (el, role) => el.shadowRoot.querySelector(`[data-role="${role}"]`);
const bubbles = (el) => [...el.shadowRoot.querySelectorAll('[data-role="log"] .msg')];

function pngFile(name = 'captura.png', bytes = 64, type = 'image/png') {
  return new File([new Uint8Array(bytes).fill(7)], name, { type });
}

async function pick(el, file) {
  const input = $(el, 'file');
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  input.dispatchEvent(new Event('change'));
  await flush();
}

async function typeText(el, text) {
  const input = $(el, 'input');
  input.value = text;
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

async function submit(el) {
  $(el, 'form').dispatchEvent(new Event('submit', { cancelable: true }));
  await flush(10);
}

// Hace fallar solo el próximo envío de mensaje (no la creación de la conversación).
function failNextMessage(status, code) {
  const original = backend.handle.bind(backend);
  let failed = false;
  backend.handle = (method, path, init) => {
    if (!failed && method === 'POST' && path.endsWith('/messages')) {
      failed = true;
      return errorResponse(status, code);
    }
    return original(method, path, init);
  };
}

const lastBody = () => JSON.parse(backend.calls.filter((c) => c.path.endsWith('/messages')).at(-1).init.body);

beforeEach(() => {
  backend = createFakeBackend();
  globalThis.fetch = backend.fetch;
  localStorage.clear();
  document.body.innerHTML = '';
  objectUrls = { created: [], revoked: [] };
  let n = 0;
  URL.createObjectURL = vi.fn(() => {
    n += 1;
    const url = `blob:http://test/${n}`;
    objectUrls.created.push(url);
    return url;
  });
  URL.revokeObjectURL = vi.fn((url) => objectUrls.revoked.push(url));
});

afterEach(() => {
  document.body.innerHTML = '';
});

describe('<ia-chat-widget> imágenes (US1)', () => {
  it('muestra el botón de adjuntar con etiqueta accesible', () => {
    const el = mount();
    const attach = $(el, 'attach');
    expect(attach).toBeTruthy();
    expect(attach.hidden).toBe(false);
    expect(attach.getAttribute('aria-label')).toBe('Adjuntar imagen');
    expect($(el, 'file').getAttribute('accept')).toBe('image/png,image/jpeg,image/webp');
  });

  it('image-upload="false" oculta el botón', () => {
    const el = mount({ 'image-upload': 'false' });
    expect($(el, 'attach').hidden).toBe(true);
  });

  it('el botón de adjuntar abre el selector de archivos', () => {
    const el = mount();
    const click = vi.fn();
    $(el, 'file').click = click;
    $(el, 'attach').click();
    expect(click).toHaveBeenCalled();
  });

  it('elegir una imagen muestra la vista previa y se puede quitar', async () => {
    const el = mount();
    await pick(el, pngFile('captura.png'));
    const preview = $(el, 'attachment-preview');
    expect(preview.hidden).toBe(false);
    expect($(el, 'attachment-name').textContent).toBe('captura.png');
    expect($(el, 'attachment-thumb').getAttribute('src')).toBe('blob:http://test/1');

    const remove = $(el, 'attachment-remove');
    expect(remove.getAttribute('aria-label')).toBe('Quitar imagen');
    remove.click();
    expect(preview.hidden).toBe(true);
    expect(objectUrls.revoked).toEqual(['blob:http://test/1']);
    expect($(el, 'send').disabled).toBe(true);
  });

  it('elegir otra imagen reemplaza la anterior', async () => {
    const el = mount();
    await pick(el, pngFile('a.png'));
    await pick(el, pngFile('b.png'));
    expect($(el, 'attachment-name').textContent).toBe('b.png');
    expect(objectUrls.revoked).toEqual(['blob:http://test/1']);
  });

  it('con imagen se puede enviar sin texto y el cuerpo lleva base64 sin prefijo', async () => {
    const el = mount();
    await pick(el, pngFile('captura.png', 10));
    expect($(el, 'send').disabled).toBe(false);
    await submit(el);

    const body = lastBody();
    expect(body.content).toBe('');
    expect(body.image.filename).toBe('captura.png');
    expect(body.image.media_type).toBe('image/png');
    expect(body.image.data.startsWith('data:')).toBe(false);
    expect(atob(body.image.data)).toBe('\x07'.repeat(10));
  });

  it('envía texto e imagen juntos y limpia el adjunto tras el envío', async () => {
    const el = mount();
    await pick(el, pngFile('captura.png'));
    await typeText(el, '¿Qué dice?');
    await submit(el);

    expect(lastBody().content).toBe('¿Qué dice?');
    expect($(el, 'attachment-preview').hidden).toBe(true);
    expect($(el, 'input').value).toBe('');
    const [user, assistant] = bubbles(el);
    expect(user.dataset.sender).toBe('user');
    expect(user.querySelector('.body').textContent).toBe('¿Qué dice?');
    expect(user.querySelector('img.attachment-thumb').getAttribute('src')).toBe('blob:http://test/1');
    expect(assistant.dataset.sender).toBe('assistant');
  });

  it('muestra "Leyendo la imagen…" mientras espera la respuesta', async () => {
    let release;
    backend.nextResponses.push(
      (url, init) =>
        new Promise((resolve) => {
          release = () => resolve(backend.handle('POST', url.pathname, init));
        }),
    );
    const el = mount();
    await pick(el, pngFile());
    await submit(el);
    expect($(el, 'status').hidden).toBe(false);
    expect($(el, 'status').textContent).toBe('Leyendo la imagen…');
    release();
    await flush(10);
    expect($(el, 'status').hidden).toBe(true);
  });

  it('respeta max-image-bytes', async () => {
    const el = mount({ 'max-image-bytes': '100' });
    await pick(el, pngFile('grande.png', 101));
    expect($(el, 'attachment-preview').hidden).toBe(true);
    await pick(el, pngFile('justa.png', 100));
    expect($(el, 'attachment-preview').hidden).toBe(false);
  });

  it('funciona también en modo streaming', async () => {
    const el = mount({ streaming: 'true' });
    await pick(el, pngFile('captura.png'));
    await submit(el);
    const call = backend.calls.filter((c) => c.path.endsWith('/messages')).at(-1);
    expect(call.init.headers.Accept).toBe('text/event-stream');
    expect(JSON.parse(call.init.body).image.filename).toBe('captura.png');
    expect(bubbles(el).map((b) => b.dataset.status)).toEqual(['complete', 'complete']);
  });
});

describe('<ia-chat-widget> texto reconocido (US2)', () => {
  it('ofrece desplegar el texto reconocido, cerrado por defecto y sin interpretar HTML', async () => {
    backend.ocrText['captura.png'] = 'Error <b>404</b>\nsegunda línea';
    const el = mount();
    await pick(el, pngFile('captura.png'));
    await submit(el);

    const [user] = bubbles(el);
    const details = user.querySelector('details.ocr');
    expect(details).toBeTruthy();
    expect(details.open).toBe(false);
    expect(details.querySelector('summary').textContent).toBe('Ver texto reconocido');
    const text = details.querySelector('.ocr-text');
    expect(text.textContent).toBe('Error <b>404</b>\nsegunda línea');
    expect(text.querySelector('b')).toBeNull();
  });

  it('marca el texto recortado de forma visible', async () => {
    backend.ocrTruncated['larga.png'] = true;
    const el = mount();
    await pick(el, pngFile('larga.png'));
    await submit(el);
    const summary = bubbles(el)[0].querySelector('summary');
    expect(summary.textContent).toContain('(texto recortado)');
  });

  it('al recuperar el historial muestra "📎 nombre" en lugar de la miniatura', async () => {
    const first = mount();
    await pick(first, pngFile('captura.png'));
    await submit(first);
    const conversationId = localStorage.getItem('ia-chat:conversation-id');
    expect(conversationId).toBeTruthy();
    document.body.innerHTML = '';

    const restored = mount();
    await flush(10);
    const [user] = bubbles(restored);
    expect(user.querySelector('img')).toBeNull();
    expect(user.querySelector('.attachment-chip').textContent).toBe('📎 captura.png');
    expect(user.querySelector('.ocr-text').textContent).toBe('Texto de captura.png');
  });
});

describe('<ia-chat-widget> errores de imagen (US3)', () => {
  it('rechaza localmente formatos no admitidos y archivos grandes', async () => {
    const el = mount({ 'max-image-bytes': '1048576' });
    await pick(el, new File(['hola'], 'nota.txt', { type: 'text/plain' }));
    expect($(el, 'attachment-preview').hidden).toBe(true);
    expect($(el, 'notice').textContent).toContain('PNG, JPEG o WebP de hasta 1 MB');

    await pick(el, pngFile('anim.gif', 10, 'image/gif'));
    expect($(el, 'attachment-preview').hidden).toBe(true);

    await pick(el, pngFile('grande.png', 1048577));
    expect($(el, 'attachment-preview').hidden).toBe(true);
    expect(URL.createObjectURL).not.toHaveBeenCalled();

    await pick(el, pngFile('ok.png'));
    expect($(el, 'attachment-preview').hidden).toBe(false);
    expect($(el, 'notice-box').hidden).toBe(true);
  });

  for (const [status, code, text] of [
    [422, 'IMAGE_NO_TEXT', 'No se encontró texto legible'],
    [422, 'IMAGE_INVALID', 'no es válida'],
    [413, 'IMAGE_TOO_LARGE', 'tamaño máximo'],
  ]) {
    it(`${code}: quita la burbuja y devuelve texto e imagen al campo, sin Reintentar`, async () => {
      const el = mount();
      await pick(el, pngFile('foto.png'));
      await typeText(el, '¿Qué dice?');
      failNextMessage(status, code);
      await submit(el);

      expect(bubbles(el)).toHaveLength(0);
      expect($(el, 'empty').hidden).toBe(false);
      expect($(el, 'notice').textContent).toContain(text);
      expect($(el, 'retry').hidden).toBe(true);
      expect($(el, 'input').value).toBe('¿Qué dice?');
      expect($(el, 'attachment-preview').hidden).toBe(false);
      expect($(el, 'attachment-name').textContent).toBe('foto.png');
      expect($(el, 'send').disabled).toBe(false);
    });
  }

  for (const [status, code] of [
    [503, 'OCR_UNAVAILABLE'],
    [504, 'OCR_TIMEOUT'],
  ]) {
    it(`${code}: Reintentar reenvía el mensaje completo con la misma imagen`, async () => {
      const el = mount();
      await pick(el, pngFile('captura.png', 20));
      await typeText(el, 'hola');
      failNextMessage(status, code);
      await submit(el);

      expect($(el, 'retry').hidden).toBe(false);
      expect(bubbles(el)).toHaveLength(1);
      const failedBody = lastBody();

      $(el, 'retry').click();
      await flush(10);
      const sent = backend.calls.filter((c) => c.path.endsWith('/messages'));
      expect(sent).toHaveLength(2);
      expect(lastBody()).toEqual(failedBody);
      expect(backend.calls.some((c) => c.path.endsWith('/retry'))).toBe(false);
      expect(bubbles(el).map((b) => b.dataset.sender)).toEqual(['user', 'assistant']);
      expect($(el, 'notice-box').hidden).toBe(true);
    });
  }

  it('después de un error de imagen se puede seguir enviando texto', async () => {
    const el = mount();
    await pick(el, pngFile());
    failNextMessage(422, 'IMAGE_NO_TEXT');
    await submit(el);
    $(el, 'attachment-remove').click();
    await typeText(el, 'solo texto');
    await submit(el);
    expect(lastBody()).toEqual({ content: 'solo texto' });
    expect(bubbles(el).map((b) => b.dataset.sender)).toEqual(['user', 'assistant']);
  });
});
