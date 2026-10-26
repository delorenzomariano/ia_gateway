// Cliente de la API del backend IA Gateway (contracts/openapi.yaml).

export class ApiClientError extends Error {
  constructor({ code, message, correlationId = null, status = 0 }) {
    super(message);
    this.name = 'ApiClientError';
    this.code = code;
    this.correlationId = correlationId;
    this.status = status;
  }
}

const NETWORK_MESSAGE = 'No se pudo conectar con el servidor. Revisá tu conexión y reintentá.';

export class ApiClient {
  constructor(baseUrl, { fetch } = {}) {
    this.baseUrl = String(baseUrl).replace(/\/+$/, '');
    this._fetch = fetch || ((...args) => globalThis.fetch(...args));
  }

  _url(path) {
    return `${this.baseUrl}/api/v1${path}`;
  }

  async _request(method, path, { body, accept = 'application/json', signal } = {}) {
    const headers = { Accept: accept };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    let response;
    try {
      response = await this._fetch(this._url(path), {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal,
      });
    } catch (error) {
      if (error?.name === 'AbortError') throw error;
      throw new ApiClientError({ code: 'NETWORK_ERROR', message: NETWORK_MESSAGE });
    }
    if (!response.ok) throw await toApiError(response);
    return response;
  }

  async _json(method, path, options) {
    const response = await this._request(method, path, options);
    return response.status === 204 ? null : response.json();
  }

  createConversation() {
    return this._json('POST', '/conversations');
  }

  getConversation(id) {
    return this._json('GET', `/conversations/${encodeURIComponent(id)}`);
  }

  async deleteConversation(id) {
    await this._json('DELETE', `/conversations/${encodeURIComponent(id)}`);
  }

  // `image` opcional: {filename, media_type, data} con `data` en base64 sin prefijo `data:`.
  sendMessage(id, content, { signal, image } = {}) {
    return this._json('POST', `/conversations/${encodeURIComponent(id)}/messages`, {
      body: messageBody(content, image),
      signal,
    });
  }

  // Envía un mensaje y consume la respuesta SSE (contracts/sse-events.md).
  // Resuelve con {user_message, assistant_message} al recibir message.end.
  async sendMessageStream(id, content, handlers = {}) {
    const response = await this._request('POST', `/conversations/${encodeURIComponent(id)}/messages`, {
      body: messageBody(content, handlers.image),
      accept: 'text/event-stream',
      signal: handlers.signal,
    });
    return consumeStream(response, handlers);
  }

  // Regenera la respuesta al último mensaje del usuario (tras un error).
  retryLastMessage(id, { signal } = {}) {
    return this._json('POST', `/conversations/${encodeURIComponent(id)}/messages/retry`, { signal });
  }

  async retryLastMessageStream(id, handlers = {}) {
    const response = await this._request('POST', `/conversations/${encodeURIComponent(id)}/messages/retry`, {
      accept: 'text/event-stream',
      signal: handlers.signal,
    });
    return consumeStream(response, handlers);
  }
}

function messageBody(content, image) {
  return image ? { content, image } : { content };
}

const INTERRUPTED_MESSAGE = 'La respuesta se interrumpió antes de terminar. Podés reintentar.';

export function parseEventBlock(block) {
  let event = 'message';
  const data = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
  }
  return { event, data: data.length ? JSON.parse(data.join('\n')) : {} };
}

async function consumeStream(response, { onStart, onDelta, onEnd } = {}) {
  const correlationId = response.headers.get('X-Correlation-ID');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let start = null;

  const interrupted = () =>
    new ApiClientError({ code: 'STREAM_INTERRUPTED', message: INTERRUPTED_MESSAGE, correlationId });

  for (;;) {
    let chunk;
    try {
      chunk = await reader.read();
    } catch (error) {
      if (error?.name === 'AbortError') throw error;
      throw interrupted();
    }
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true }).replace(/\r\n/g, '\n');

    let index;
    while ((index = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      if (!block.trim()) continue;
      const { event, data } = parseEventBlock(block);
      if (event === 'message.start') {
        start = data;
        onStart?.(data);
      } else if (event === 'delta') {
        onDelta?.(data.text ?? '');
      } else if (event === 'message.end') {
        onEnd?.(data);
        reader.cancel().catch(() => {});
        return { user_message: start?.user_message, assistant_message: data.assistant_message };
      } else if (event === 'error') {
        const error = new ApiClientError({
          code: data.error?.code || 'INTERNAL_ERROR',
          message: data.error?.message || INTERRUPTED_MESSAGE,
          correlationId: data.error?.correlation_id || correlationId,
          status: response.status,
        });
        error.assistantMessage = data.assistant_message ?? null;
        throw error;
      }
      // "ping" y eventos desconocidos se ignoran.
    }
  }
  throw interrupted();
}

export async function toApiError(response) {
  const correlationId = response.headers.get('X-Correlation-ID');
  try {
    const { error } = await response.json();
    return new ApiClientError({
      code: error.code,
      message: error.message,
      correlationId: error.correlation_id || correlationId,
      status: response.status,
    });
  } catch {
    return new ApiClientError({
      code: 'INTERNAL_ERROR',
      message: 'Ocurrió un error inesperado. Reintentá en unos segundos.',
      correlationId,
      status: response.status,
    });
  }
}
