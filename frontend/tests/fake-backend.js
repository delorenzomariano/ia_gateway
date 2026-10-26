// Backend simulado para las pruebas del componente: implementa el contrato en memoria.

export function jsonResponse(status, body, headers = {}) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'X-Correlation-ID': 'test-corr', ...headers },
  });
}

export function errorResponse(status, code, message = `error ${code}`) {
  return jsonResponse(status, { error: { code, message, correlation_id: 'test-corr' } });
}

let seq = 0;
const now = () => new Date().toISOString();

function message(role, content, status = 'complete', errorCode = null) {
  seq += 1;
  return { id: `m${seq}`, role, content, status, error_code: errorCode, created_at: now() };
}

function attachmentOf(image, backend) {
  if (!image) return null;
  const size = Math.floor((image.data.length * 3) / 4);
  return {
    filename: image.filename,
    media_type: image.media_type,
    size_bytes: size,
    text: backend.ocrText[image.filename] ?? `Texto de ${image.filename}`,
    truncated: Boolean(backend.ocrTruncated[image.filename]),
  };
}

export function createFakeBackend({ reply = (text) => `Respuesta a: ${text}` } = {}) {
  const conversations = new Map();
  const calls = [];
  const backend = {
    conversations,
    calls,
    reply,
    // Texto "reconocido" por nombre de archivo y archivos cuyo texto se marca como recortado.
    ocrText: {},
    ocrTruncated: {},
    // Permite forzar la próxima respuesta de sendMessage/retry: función (url, init) => Response.
    nextResponses: [],
    fetch: async (input, init = {}) => {
      const url = new URL(typeof input === 'string' ? input : input.url);
      const method = (init.method || 'GET').toUpperCase();
      calls.push({ method, path: url.pathname, init });
      if (init.signal?.aborted) throw new DOMException('aborted', 'AbortError');
      const forced = backend.nextResponses.shift();
      if (forced) return forced(url, init);
      const response = await backend.handle(method, url.pathname, init);
      const wantsStream = init.headers?.Accept === 'text/event-stream';
      if (wantsStream && response.ok && url.pathname.includes('/messages')) {
        return sseResponse([sseText(streamFromJson(await response.json()))]);
      }
      return response;
    },
    handle(method, path, init) {
      if (method === 'POST' && path === '/api/v1/conversations') {
        const id = `c${conversations.size + 1}-${Math.random().toString(16).slice(2, 8)}`;
        const conv = { id, created_at: now(), last_activity_at: now(), expires_at: now(), messages: [] };
        conversations.set(id, conv);
        const { messages, ...rest } = conv;
        return jsonResponse(201, rest);
      }
      const match = path.match(/^\/api\/v1\/conversations\/([^/]+)(\/messages(\/retry)?)?$/);
      if (!match) return errorResponse(404, 'NOT_FOUND');
      const [, id, messagesPart, retryPart] = match;
      const conv = conversations.get(id);
      if (method === 'DELETE' && !messagesPart) {
        conversations.delete(id);
        return new Response(null, { status: 204 });
      }
      if (!conv) return errorResponse(404, 'CONVERSATION_NOT_FOUND');
      if (method === 'GET' && !messagesPart) {
        return jsonResponse(200, { ...conv, generation_in_progress: false });
      }
      if (method === 'POST' && messagesPart && !retryPart) {
        const { content, image } = JSON.parse(init.body);
        const user = { ...message('user', content), attachment: attachmentOf(image, backend) };
        const assistant = message('assistant', backend.reply(content || user.attachment?.text));
        conv.messages.push(user, assistant);
        return jsonResponse(200, { user_message: user, assistant_message: assistant });
      }
      if (method === 'POST' && retryPart) {
        const user = [...conv.messages].reverse().find((m) => m.role === 'user');
        const assistant = message('assistant', backend.reply(user.content));
        conv.messages = conv.messages.filter((m) => m.status !== 'error');
        conv.messages.push(assistant);
        return jsonResponse(200, { user_message: user, assistant_message: assistant });
      }
      return errorResponse(405, 'METHOD_NOT_ALLOWED');
    },
  };
  return backend;
}

export function sseText(events) {
  return events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('');
}

// Respuesta SSE que entrega `chunks` (strings) y, si `hold` es true, queda abierta hasta que
// se aborte la petición con `signal`.
export function sseResponse(chunks, { signal, hold = false } = {}) {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      if (!hold) {
        controller.close();
        return;
      }
      signal?.addEventListener('abort', () => {
        controller.error(new DOMException('aborted', 'AbortError'));
      });
    },
  });
  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream', 'X-Correlation-ID': 'test-corr' },
  });
}

// Convierte una respuesta JSON del backend simulado en el stream SSE equivalente.
export function streamFromJson(result, fragments) {
  const deltas = fragments ?? [result.assistant_message.content];
  return [
    ['message.start', { user_message: result.user_message, assistant_message_id: result.assistant_message.id }],
    ...deltas.map((text) => ['delta', { text }]),
    ['message.end', { assistant_message: result.assistant_message }],
  ];
}

export async function flush(times = 5) {
  for (let i = 0; i < times; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}
