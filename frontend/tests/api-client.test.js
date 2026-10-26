import { describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiClientError } from '../widget/api-client.js';
import { createFakeBackend, errorResponse, sseResponse, sseText } from './fake-backend.js';

const BASE = 'http://backend.test';

describe('ApiClient (modo JSON)', () => {
  it('crea, obtiene y borra conversaciones', async () => {
    const backend = createFakeBackend();
    const api = new ApiClient(BASE, { fetch: backend.fetch });

    const conv = await api.createConversation();
    expect(conv.id).toBeTruthy();
    expect(backend.calls[0]).toMatchObject({ method: 'POST', path: '/api/v1/conversations' });

    const loaded = await api.getConversation(conv.id);
    expect(loaded.messages).toEqual([]);

    await api.deleteConversation(conv.id);
    expect(backend.calls.at(-1)).toMatchObject({ method: 'DELETE' });
  });

  it('envía un mensaje y devuelve ambos mensajes', async () => {
    const backend = createFakeBackend();
    const api = new ApiClient(`${BASE}/`, { fetch: backend.fetch });
    const conv = await api.createConversation();

    const result = await api.sendMessage(conv.id, 'Hola');
    expect(result.user_message.content).toBe('Hola');
    expect(result.assistant_message.content).toBe('Respuesta a: Hola');

    const call = backend.calls.at(-1);
    expect(call.path).toBe(`/api/v1/conversations/${conv.id}/messages`);
    expect(call.init.headers.Accept).toBe('application/json');
    expect(JSON.parse(call.init.body)).toEqual({ content: 'Hola' });
  });

  it('envía la imagen opcional en el cuerpo (JSON y streaming)', async () => {
    const backend = createFakeBackend();
    const api = new ApiClient(BASE, { fetch: backend.fetch });
    const conv = await api.createConversation();
    const image = { filename: 'captura.png', media_type: 'image/png', data: 'iVBORw0KGgo=' };

    await api.sendMessage(conv.id, '¿Qué dice?', { image });
    expect(JSON.parse(backend.calls.at(-1).init.body)).toEqual({ content: '¿Qué dice?', image });

    await api.sendMessageStream(conv.id, '', { image });
    expect(JSON.parse(backend.calls.at(-1).init.body)).toEqual({ content: '', image });

    await api.sendMessage(conv.id, 'Sin imagen');
    expect(JSON.parse(backend.calls.at(-1).init.body)).toEqual({ content: 'Sin imagen' });
  });

  it('convierte errores de la API en ApiClientError', async () => {
    const fetch = vi.fn(async () => errorResponse(404, 'CONVERSATION_NOT_FOUND', 'No existe'));
    const api = new ApiClient(BASE, { fetch });
    const error = await api.getConversation('x').catch((e) => e);
    expect(error).toBeInstanceOf(ApiClientError);
    expect(error).toMatchObject({
      code: 'CONVERSATION_NOT_FOUND',
      message: 'No existe',
      status: 404,
      correlationId: 'test-corr',
    });
  });

  it('lee el stream SSE aunque los eventos lleguen partidos entre fragmentos', async () => {
    const user = { id: 'u1', role: 'user', content: 'Hola', status: 'complete' };
    const assistant = { id: 'a1', role: 'assistant', content: 'Hola mundo', status: 'complete' };
    const text = sseText([
      ['message.start', { user_message: user, assistant_message_id: 'a1' }],
      ['ping', {}],
      ['delta', { text: 'Hola' }],
      ['delta', { text: ' mundo' }],
      ['message.end', { assistant_message: assistant }],
    ]);
    // Cortes arbitrarios, incluso en medio de "event:" y de un carácter multibyte no aplica (ASCII)
    const chunks = [text.slice(0, 7), text.slice(7, 60), text.slice(60, 61), text.slice(61)];
    const fetch = vi.fn(async (url, init) => {
      expect(init.headers.Accept).toBe('text/event-stream');
      return sseResponse(chunks);
    });
    const api = new ApiClient(BASE, { fetch });
    const seen = [];
    const result = await api.sendMessageStream('c1', 'Hola', {
      onStart: (data) => seen.push(['start', data.assistant_message_id]),
      onDelta: (t) => seen.push(['delta', t]),
      onEnd: (data) => seen.push(['end', data.assistant_message.content]),
    });
    expect(seen).toEqual([
      ['start', 'a1'],
      ['delta', 'Hola'],
      ['delta', ' mundo'],
      ['end', 'Hola mundo'],
    ]);
    expect(result.assistant_message).toEqual(assistant);
  });

  it('convierte el evento error del stream en ApiClientError', async () => {
    const text = sseText([
      ['message.start', { user_message: { id: 'u' }, assistant_message_id: 'a' }],
      ['error', { error: { code: 'LLM_TIMEOUT', message: 'Tarda', correlation_id: 'x' }, assistant_message: null }],
    ]);
    const api = new ApiClient(BASE, { fetch: async () => sseResponse([text]) });
    const error = await api.sendMessageStream('c1', 'Hola').catch((e) => e);
    expect(error).toBeInstanceOf(ApiClientError);
    expect(error).toMatchObject({ code: 'LLM_TIMEOUT', message: 'Tarda', correlationId: 'x' });
  });

  it('informa como STREAM_INTERRUPTED un stream que se corta sin message.end', async () => {
    const text = sseText([
      ['message.start', { user_message: { id: 'u' }, assistant_message_id: 'a' }],
      ['delta', { text: 'parcial' }],
    ]);
    const api = new ApiClient(BASE, { fetch: async () => sseResponse([text]) });
    const error = await api.sendMessageStream('c1', 'Hola').catch((e) => e);
    expect(error.code).toBe('STREAM_INTERRUPTED');
  });

  it('propaga AbortError al cancelar', async () => {
    const controller = new AbortController();
    const text = sseText([['message.start', { user_message: { id: 'u' }, assistant_message_id: 'a' }]]);
    const api = new ApiClient(BASE, {
      fetch: async (url, init) => sseResponse([text], { signal: init.signal, hold: true }),
    });
    const pending = api.sendMessageStream('c1', 'Hola', {
      signal: controller.signal,
      onStart: () => controller.abort(),
    });
    const error = await pending.catch((e) => e);
    expect(error.name).toBe('AbortError');
  });

  it('reintenta la última respuesta', async () => {
    const backend = createFakeBackend();
    const api = new ApiClient(BASE, { fetch: backend.fetch });
    const conv = await api.createConversation();
    backend.conversations.get(conv.id).messages.push({ id: 'u', role: 'user', content: 'Hola' });
    const result = await api.retryLastMessage(conv.id);
    expect(backend.calls.at(-1)).toMatchObject({
      method: 'POST',
      path: `/api/v1/conversations/${conv.id}/messages/retry`,
    });
    expect(result.assistant_message.content).toBe('Respuesta a: Hola');
  });

  it('informa errores de red con código NETWORK_ERROR', async () => {
    const fetch = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    const api = new ApiClient(BASE, { fetch });
    const error = await api.createConversation().catch((e) => e);
    expect(error).toBeInstanceOf(ApiClientError);
    expect(error.code).toBe('NETWORK_ERROR');
  });
});
