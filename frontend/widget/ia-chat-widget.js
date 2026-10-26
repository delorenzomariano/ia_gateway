// <ia-chat-widget>: chat flotante autocontenido (contracts/chat-widget.md).

import { ApiClient } from './api-client.js';
import { renderMarkdown } from './markdown.js';
import { STYLES } from './styles.js';

const DEFAULTS = {
  title: 'Asistente',
  storageKey: 'ia-chat:conversation-id',
  maxLength: 4000,
  maxImageBytes: 5242880,
};

const IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp']);

// Mensajes para el usuario por código de error (los demás usan el texto del servidor).
const ERROR_MESSAGES = {
  LLM_UNAVAILABLE: 'El asistente no está disponible en este momento.',
  LLM_TIMEOUT: 'El asistente está tardando demasiado en responder.',
  LLM_INVALID_RESPONSE: 'El asistente devolvió una respuesta inválida.',
  NETWORK_ERROR: 'No se pudo conectar con el servidor. Revisá tu conexión.',
  STREAM_INTERRUPTED: 'La respuesta se interrumpió antes de terminar.',
  GENERATION_IN_PROGRESS:
    'Ya hay una respuesta en curso en esta conversación (quizás en otra pestaña). Esperá a que termine.',
  IMAGE_INVALID: 'La imagen no es válida. Formatos admitidos: PNG, JPEG o WebP.',
  IMAGE_TOO_LARGE: 'La imagen supera el tamaño máximo permitido.',
  IMAGE_NO_TEXT: 'No se encontró texto legible en la imagen. Probá con otra más nítida.',
  OCR_UNAVAILABLE: 'El análisis de imágenes no está disponible en este momento.',
  OCR_TIMEOUT: 'El análisis de la imagen tardó demasiado.',
};
// Errores de imagen previos a la respuesta: el backend no guardó nada.
const IMAGE_REJECTED = new Set(['IMAGE_INVALID', 'IMAGE_TOO_LARGE', 'IMAGE_NO_TEXT']);
const OCR_RESEND = new Set(['OCR_UNAVAILABLE', 'OCR_TIMEOUT']);
const INCOMPLETE_MESSAGE = 'La respuesta quedó incompleta porque se cortó la conexión.';
const RETRYABLE = new Set([
  'LLM_UNAVAILABLE',
  'LLM_TIMEOUT',
  'LLM_INVALID_RESPONSE',
  'NETWORK_ERROR',
  'STREAM_INTERRUPTED',
  'INTERNAL_ERROR',
]);

const svg = (body, attrs = 'fill="none" stroke="currentColor" stroke-width="2"') =>
  `<svg viewBox="0 0 24 24" ${attrs} stroke-linecap="round" stroke-linejoin="round" ` +
  `aria-hidden="true">${body}</svg>`;

const ICON_CHAT = svg(
  '<rect x="4" y="5" width="16" height="12" rx="4"/><path d="M12 2v3"/>' +
    '<circle cx="9" cy="11" r="1.2" fill="currentColor"/><circle cx="15" cy="11" r="1.2" fill="currentColor"/>' +
    '<path d="M9 17v3l3-3"/>',
);
const ICON_CLOSE = svg('<path d="M18 6 6 18M6 6l12 12"/>', 'fill="none" stroke="currentColor" stroke-width="2.2"');
const ICON_SPARK = svg(
  '<path d="M12 3l1.8 4.9L19 9.7l-5.2 1.8L12 16.5l-1.8-5L5 9.7l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  'fill="currentColor" stroke="none"',
);
const ICON_NEW = svg('<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>');
const ICON_MINIMIZE = svg('<path d="M5 12h14"/>');
const ICON_SEND = svg('<path d="M12 19V5M5 12l7-7 7 7"/>', 'fill="none" stroke="currentColor" stroke-width="2.4"');
const ICON_STOP = svg('<rect x="7" y="7" width="10" height="10" rx="2"/>', 'fill="currentColor" stroke="none"');
const ICON_IMAGE = svg(
  '<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="1.8"/><path d="m21 16-5-5-9 9"/>',
);
const ICON_REMOVE = svg('<path d="M17 7 7 17M7 7l10 10"/>');

const TEMPLATE = `
  <style>${STYLES}</style>
  <button type="button" class="launcher" data-role="launcher" aria-haspopup="dialog"
    aria-expanded="false" aria-label="Abrir chat"><span class="icon-chat">${ICON_CHAT}</span><span
    class="icon-close">${ICON_CLOSE}</span></button>
  <section class="panel" data-role="panel" role="dialog" hidden>
    <header>
      <span class="avatar">${ICON_SPARK}</span>
      <div class="heading">
        <h2 data-role="title"></h2>
        <p class="subtitle">Asistente de IA local</p>
      </div>
      <button type="button" data-role="new" aria-label="Nueva conversación"
        title="Nueva conversación">${ICON_NEW}</button>
      <button type="button" data-role="close" aria-label="Cerrar chat"
        title="Minimizar">${ICON_MINIMIZE}</button>
    </header>
    <div class="log" data-role="log" role="log" aria-live="polite">
      <p class="empty" data-role="empty">¡Hola! ¿En qué te puedo ayudar?</p>
    </div>
    <div class="status" data-role="status" hidden>Respondiendo…</div>
    <div class="notice" data-role="notice-box" hidden>
      <span data-role="notice"></span>
      <button type="button" data-role="retry" hidden>Reintentar</button>
    </div>
    <form data-role="form">
      <div class="attachment-preview" data-role="attachment-preview" hidden>
        <img class="preview-thumb" data-role="attachment-thumb" alt="">
        <span class="preview-name" data-role="attachment-name"></span>
        <button type="button" data-role="attachment-remove" aria-label="Quitar imagen"
          title="Quitar imagen">${ICON_REMOVE}</button>
      </div>
      <div class="field">
        <button type="button" class="attach" data-role="attach" aria-label="Adjuntar imagen"
          title="Adjuntar imagen">${ICON_IMAGE}</button>
        <input type="file" data-role="file" accept="image/png,image/jpeg,image/webp" hidden>
        <textarea data-role="input" rows="1" aria-label="Escribí tu mensaje"
          placeholder="Escribí tu mensaje…"></textarea>
        <button type="submit" data-role="send" aria-label="Enviar" title="Enviar" disabled>${ICON_SEND}</button>
        <button type="button" data-role="stop" aria-label="Detener" title="Detener" hidden>${ICON_STOP}</button>
      </div>
      <div class="hint"><span><kbd>Enter</kbd> envía · <kbd>Shift</kbd>+<kbd>Enter</kbd> nueva línea</span></div>
    </form>
  </section>
`;

async function fileToBase64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

function formatMegabytes(bytes) {
  const mb = bytes / (1024 * 1024);
  return `${Number.isInteger(mb) ? mb : mb.toFixed(1)} MB`;
}

function storage() {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export class IaChatWidget extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._busy = false;
    this._conversationId = null;
    this._built = false;
    this._attachment = null; // {file, url} de la imagen elegida y aún no enviada
  }

  connectedCallback() {
    if (!this._built) this._build();
    this._els.title.textContent = this.title;
    this._els.panel.setAttribute('aria-label', this.title);
    this._els.attach.hidden = !this.imageUpload;
    this._api = new ApiClient(this.backendUrl);
    this._restore();
  }

  // --- atributos -------------------------------------------------------------------

  get title() {
    return this.getAttribute('title') || DEFAULTS.title;
  }

  get backendUrl() {
    return this.getAttribute('backend-url') || globalThis.location.origin;
  }

  get storageKey() {
    return this.getAttribute('storage-key') || DEFAULTS.storageKey;
  }

  get maxLength() {
    const value = Number.parseInt(this.getAttribute('max-length'), 10);
    return Number.isFinite(value) && value > 0 ? value : DEFAULTS.maxLength;
  }

  get streaming() {
    return this.getAttribute('streaming') !== 'false';
  }

  get imageUpload() {
    return this.getAttribute('image-upload') !== 'false';
  }

  get maxImageBytes() {
    const value = Number.parseInt(this.getAttribute('max-image-bytes'), 10);
    return Number.isFinite(value) && value > 0 ? value : DEFAULTS.maxImageBytes;
  }

  // --- construcción ----------------------------------------------------------------

  _build() {
    this.shadowRoot.innerHTML = TEMPLATE; // plantilla estática propia, sin datos externos
    this._els = {};
    for (const el of this.shadowRoot.querySelectorAll('[data-role]')) {
      this._els[el.dataset.role] = el;
    }
    const { launcher, close, panel, input, form, retry } = this._els;

    launcher.addEventListener('click', () => (panel.hidden ? this.open() : this.close()));
    close.addEventListener('click', () => this.close());
    this._els.new.addEventListener('click', () => this.newConversation());
    this._els.stop.addEventListener('click', () => this.stop());
    retry.addEventListener('click', () => this._onRetry?.());
    panel.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        this.close();
      }
    });
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        this._submit();
      }
    });
    input.addEventListener('input', () => this._validateInput());
    this._els.attach.addEventListener('click', () => this._els.file.click());
    this._els.file.addEventListener('change', () => {
      const [file] = this._els.file.files || [];
      this._els.file.value = '';
      this._chooseFile(file);
    });
    this._els['attachment-remove'].addEventListener('click', () => {
      this._clearAttachment();
      input.focus();
    });
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this._submit();
    });
    this._built = true;
  }

  // --- apertura / cierre -----------------------------------------------------------

  open() {
    const { panel, launcher, input } = this._els;
    if (!panel.hidden) return;
    panel.hidden = false;
    launcher.setAttribute('aria-expanded', 'true');
    launcher.setAttribute('aria-label', 'Cerrar chat');
    input.focus();
    this._scrollToEnd();
    this._emit('ia-chat:open', {});
  }

  close() {
    const { panel, launcher } = this._els;
    if (panel.hidden) return;
    panel.hidden = true;
    launcher.setAttribute('aria-expanded', 'false');
    launcher.setAttribute('aria-label', 'Abrir chat');
    launcher.focus();
    this._emit('ia-chat:close', {});
  }

  // --- conversación ----------------------------------------------------------------

  async _restore() {
    const id = storage()?.getItem(this.storageKey);
    if (!id) return;
    try {
      const conversation = await this._api.getConversation(id);
      this._conversationId = id;
      this._clearLog();
      for (const message of conversation.messages) this._appendMessage(message);
      const last = conversation.messages.at(-1);
      if (last?.role === 'assistant' && last.status === 'error') {
        this._showError({ code: last.error_code || 'INTERNAL_ERROR', message: '' });
      }
    } catch (error) {
      if (error.code === 'CONVERSATION_NOT_FOUND') {
        this._forgetConversation();
      } else {
        this._showError(error);
      }
    }
  }

  async _ensureConversation() {
    if (this._conversationId) return this._conversationId;
    const conversation = await this._api.createConversation();
    this._conversationId = conversation.id;
    storage()?.setItem(this.storageKey, conversation.id);
    return conversation.id;
  }

  _forgetConversation() {
    this._conversationId = null;
    storage()?.removeItem(this.storageKey);
  }

  async newConversation() {
    const id = this._conversationId;
    // Si hay una respuesta en curso se aborta primero y se espera a que termine (FR-013a).
    this.stop();
    await this._currentRun;
    this._forgetConversation();
    this._clearLog();
    this._hideNotice();
    if (!id) return;
    for (let attempt = 0; ; attempt += 1) {
      try {
        await this._api.deleteConversation(id);
        return;
      } catch (error) {
        // El backend puede tardar un instante en registrar la cancelación.
        if (error.code === 'GENERATION_IN_PROGRESS' && attempt < 3) {
          await new Promise((resolve) => setTimeout(resolve, 300));
          continue;
        }
        this._showError(error);
        return;
      }
    }
  }

  stop() {
    this._abort?.abort();
  }

  // --- envío -----------------------------------------------------------------------

  _validateInput() {
    const { input, send } = this._els;
    const length = input.value.trim().length;
    const tooLong = input.value.length > this.maxLength;
    if (tooLong) {
      this._showNotice(`El mensaje supera el máximo de ${this.maxLength} caracteres.`, {
        kind: 'validation',
      });
    } else if (this._noticeKind === 'validation') {
      this._hideNotice();
    }
    send.disabled = this._busy || (length === 0 && !this._attachment) || tooLong;
    return !send.disabled;
  }

  // --- imagen adjunta --------------------------------------------------------------

  _chooseFile(file) {
    if (!file) return;
    if (!IMAGE_TYPES.has(file.type) || file.size > this.maxImageBytes) {
      this._showNotice(
        `Solo se admiten imágenes PNG, JPEG o WebP de hasta ${formatMegabytes(this.maxImageBytes)}.`,
        { kind: 'attachment' },
      );
      return;
    }
    if (this._noticeKind === 'attachment') this._hideNotice();
    this._setAttachment({ file, url: URL.createObjectURL(file) });
  }

  _setAttachment(attachment) {
    this._clearAttachment();
    this._attachment = attachment;
    const { 'attachment-preview': preview, 'attachment-thumb': thumb, 'attachment-name': name } =
      this._els;
    thumb.src = attachment.url;
    name.textContent = attachment.file.name;
    preview.hidden = false;
    this._validateInput();
  }

  // `revoke=false` cuando la imagen pasa a la burbuja enviada, que sigue usando su URL.
  _clearAttachment({ revoke = true } = {}) {
    if (this._attachment && revoke) URL.revokeObjectURL(this._attachment.url);
    this._attachment = null;
    this._els['attachment-preview'].hidden = true;
    this._els['attachment-thumb'].removeAttribute('src');
    this._els['attachment-name'].textContent = '';
    this._validateInput();
  }

  async _imagePayload(attachment) {
    if (!attachment) return undefined;
    attachment.payload ??= {
      filename: attachment.file.name,
      media_type: attachment.file.type,
      data: await fileToBase64(attachment.file),
    };
    return attachment.payload;
  }

  // --- envío -----------------------------------------------------------------------

  async _submit() {
    if (!this._validateInput()) return;
    const content = this._els.input.value.trim();
    const attachment = this._attachment;
    this._els.input.value = '';
    this._clearAttachment({ revoke: false });
    this._hideNotice();
    const userBubble = this._appendMessage(
      {
        role: 'user',
        content,
        status: 'complete',
        attachment: attachment ? { filename: attachment.file.name } : null,
      },
      { imageUrl: attachment?.url },
    );
    this._pending = { content, userBubble, attachment };
    await this._run(() => this._reply({ content, userBubble, attachment, retry: false }));
  }

  // Reintento tras un error: regenera la respuesta en el backend sin duplicar la pregunta.
  // Si el backend nunca recibió el mensaje (NOTHING_TO_RETRY, sin conversación o un error de
  // OCR, que no guarda nada), lo reenvía completo, con su imagen.
  async _retry({ resend = false } = {}) {
    const pending = this._pending;
    this._hideNotice();
    this._removeErrorBubbles();
    await this._run(async () => {
      if ((resend || !this._conversationId) && pending) {
        await this._reply({ ...pending, retry: false });
        return;
      }
      try {
        await this._reply({ userBubble: pending?.userBubble ?? null, retry: true });
      } catch (error) {
        if (error.code !== 'NOTHING_TO_RETRY' || !pending) throw error;
        await this._reply({ ...pending, retry: false });
      }
    });
  }

  async _reply({ content, userBubble, attachment = null, retry }) {
    const id = this._conversationId;
    const image = retry ? undefined : await this._imagePayload(attachment);
    this._setStatus(image ? 'Leyendo la imagen…' : 'Respondiendo…');
    if (this.streaming) {
      return this._streamReply(userBubble, (handlers) =>
        retry
          ? this._api.retryLastMessageStream(id, handlers)
          : this._withRecovery((cid) => this._api.sendMessageStream(cid, content, { ...handlers, image })),
      );
    }
    return this._jsonReply(userBubble, () =>
      retry
        ? this._api.retryLastMessage(id)
        : this._withRecovery((cid) => this._api.sendMessage(cid, content, { image })),
    );
  }

  async _jsonReply(userBubble, request) {
    const result = await request();
    if (userBubble && result.user_message) this._updateBubble(userBubble, result.user_message);
    this._appendMessage(result.assistant_message);
    this._pending = null;
  }

  async _streamReply(userBubble, request) {
    const controller = new AbortController();
    this._abort = controller;
    this._setStreaming(true);
    let bubble = null;
    let text = '';
    try {
      await request({
        signal: controller.signal,
        onStart: ({ user_message: user, assistant_message_id: assistantId }) => {
          this._setStatus('Respondiendo…');
          if (user && userBubble) this._updateBubble(userBubble, user);
          bubble = this._appendMessage({ id: assistantId, role: 'assistant', content: '', status: 'streaming' });
        },
        onDelta: (delta) => {
          text += delta;
          this._updateBubble(bubble, { role: 'assistant', content: text, status: 'streaming' });
          this._scrollToEnd();
        },
        onEnd: ({ assistant_message: assistant }) => this._updateBubble(bubble, assistant),
      });
      this._pending = null;
    } catch (error) {
      if (error?.name === 'AbortError' || (error?.code === 'STREAM_INTERRUPTED' && text)) {
        // Detenido por el usuario o conexión cortada a mitad: se conserva el texto recibido.
        if (bubble && text) {
          this._updateBubble(bubble, { role: 'assistant', content: text, status: 'incomplete' });
        } else {
          bubble?.remove();
        }
        this._pending = null;
        if (error?.name === 'AbortError') return;
        error.incomplete = true;
      } else if (bubble) {
        // Falla del modelo informada por el backend: el mensaje quedó con estado error.
        if (text) this._updateBubble(bubble, { role: 'assistant', content: text, status: 'error' });
        else bubble.remove();
      }
      throw error;
    } finally {
      this._abort = null;
      this._setStreaming(false);
    }
  }

  async _withRecovery(send) {
    const id = await this._ensureConversation();
    try {
      return await send(id);
    } catch (error) {
      if (error.code !== 'CONVERSATION_NOT_FOUND') throw error;
      // La conversación venció en el backend: se empieza una nueva y se reenvía una vez.
      this._forgetConversation();
      return send(await this._ensureConversation());
    }
  }

  async _run(task) {
    this._setBusy(true);
    const run = (async () => {
      try {
        await task();
      } catch (error) {
        this._showError(error);
      } finally {
        this._setBusy(false);
      }
    })();
    this._currentRun = run;
    await run;
  }

  _setBusy(busy) {
    this._busy = busy;
    this._els.status.hidden = !busy;
    if (!busy) this._setStatus('Respondiendo…');
    this._validateInput();
  }

  _setStatus(text) {
    this._els.status.textContent = text;
  }

  _setStreaming(streaming) {
    this._els.stop.hidden = !streaming;
    this._els.send.hidden = streaming;
  }

  // --- mensajes en pantalla --------------------------------------------------------

  _clearLog() {
    const { log, empty } = this._els;
    for (const bubble of log.querySelectorAll('.msg')) {
      if (bubble._imageUrl) URL.revokeObjectURL(bubble._imageUrl);
    }
    log.replaceChildren(empty);
    empty.hidden = false;
  }

  // `imageUrl`: URL blob: local de la imagen enviada en esta sesión (para la miniatura).
  _appendMessage(message, { imageUrl = null } = {}) {
    const bubble = document.createElement('div');
    bubble.className = 'msg';
    bubble._imageUrl = imageUrl;
    const body = document.createElement('div');
    body.className = 'body';
    bubble.appendChild(body);
    this._updateBubble(bubble, message);
    this._els.empty.hidden = true;
    this._els.log.appendChild(bubble);
    this._scrollToEnd();
    return bubble;
  }

  _updateBubble(bubble, message) {
    bubble.dataset.sender = message.role;
    bubble.dataset.status = message.status;
    if (message.id) bubble.dataset.id = message.id;
    const body = bubble.querySelector('.body');
    if (message.role === 'assistant' && message.status === 'error' && !message.content) {
      body.textContent = 'No se pudo obtener la respuesta.';
    } else if (message.role === 'assistant') {
      body.replaceChildren(renderMarkdown(message.content));
    } else {
      body.textContent = message.content;
    }
    this._renderAttachment(bubble, message.attachment);
  }

  // Miniatura (solo en la sesión en que se adjuntó) o "📎 nombre", y el texto reconocido.
  _renderAttachment(bubble, attachment) {
    let box = bubble.querySelector('.attachment');
    if (!attachment) {
      box?.remove();
      return;
    }
    if (!box) {
      box = document.createElement('div');
      box.className = 'attachment';
      bubble.insertBefore(box, bubble.querySelector('.body'));
    }
    const parts = [];
    if (bubble._imageUrl) {
      const img = document.createElement('img');
      img.className = 'attachment-thumb';
      img.src = bubble._imageUrl;
      img.alt = `Imagen adjunta: ${attachment.filename}`;
      parts.push(img);
    } else {
      const chip = document.createElement('span');
      chip.className = 'attachment-chip';
      chip.textContent = `📎 ${attachment.filename}`;
      parts.push(chip);
    }
    if (attachment.text) {
      const details = document.createElement('details');
      details.className = 'ocr';
      const summary = document.createElement('summary');
      summary.textContent = attachment.truncated
        ? 'Ver texto reconocido (texto recortado)'
        : 'Ver texto reconocido';
      const text = document.createElement('div');
      text.className = 'ocr-text';
      text.textContent = attachment.text;
      details.append(summary, text);
      parts.push(details);
    }
    box.replaceChildren(...parts);
  }

  _removeErrorBubbles() {
    for (const bubble of this._els.log.querySelectorAll('.msg[data-status="error"]')) bubble.remove();
  }

  _scrollToEnd() {
    const { log } = this._els;
    log.scrollTop = log.scrollHeight;
  }

  // --- avisos ----------------------------------------------------------------------

  _showNotice(text, { kind = 'error', onRetry = null } = {}) {
    this._noticeKind = kind;
    this._els.notice.textContent = text;
    this._els['notice-box'].hidden = false;
    this._els.retry.hidden = !onRetry;
    this._onRetry = onRetry;
  }

  _hideNotice() {
    this._noticeKind = null;
    this._els['notice-box'].hidden = true;
    this._els.retry.hidden = true;
    this._onRetry = null;
  }

  _showError(error) {
    const code = error?.code || 'INTERNAL_ERROR';
    const message = error?.incomplete
      ? INCOMPLETE_MESSAGE
      : ERROR_MESSAGES[code] || error?.message || 'Ocurrió un error inesperado.';
    let onRetry = RETRYABLE.has(code) && !error?.incomplete ? () => this._retry() : null;
    if (IMAGE_REJECTED.has(code) && this._pending?.attachment) {
      this._restorePending();
    } else if (OCR_RESEND.has(code) && this._pending) {
      onRetry = () => this._retry({ resend: true });
    }
    this._showNotice(message, { onRetry });
    this._emit('ia-chat:error', { code, message, correlationId: error?.correlationId || null });
  }

  // Devuelve texto e imagen al campo de escritura para que el usuario los cambie.
  _restorePending() {
    const { content, userBubble, attachment } = this._pending;
    this._pending = null;
    userBubble?.remove();
    if (!this._els.log.querySelector('.msg')) this._els.empty.hidden = false;
    this._els.input.value = content;
    this._setAttachment(attachment);
  }

  _emit(name, detail) {
    this.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true }));
  }
}

if (!customElements.get('ia-chat-widget')) {
  customElements.define('ia-chat-widget', IaChatWidget);
}
