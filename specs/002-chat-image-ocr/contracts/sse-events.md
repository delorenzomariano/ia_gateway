# Contrato de streaming (SSE)

Aplica a `POST /api/v1/conversations/{id}/messages` y `.../messages/retry` cuando la petición
lleva `Accept: text/event-stream`. Respuesta: `200`, `Content-Type: text/event-stream`,
`Cache-Control: no-cache`, header `X-Correlation-ID`.

Formato de cada evento (UTF-8, `data` es JSON en una sola línea):

```text
event: <tipo>
data: <json>

```

**Cambios en v1.1.0 (feature 002)**: ningún evento nuevo. Cuando el mensaje lleva imagen, el
reconocimiento de texto ocurre **antes** de `message.start`; sus errores (`IMAGE_INVALID`,
`IMAGE_TOO_LARGE`, `IMAGE_NO_TEXT`, `OCR_UNAVAILABLE`, `OCR_TIMEOUT`) llegan como respuesta JSON
con su código HTTP, nunca como evento `error`. El `user_message` de `message.start` incluye
`attachment` (esquema `Attachment` de `openapi.yaml`) cuando corresponde.

## Secuencia

```text
message.start → delta* → (message.end | error)
```

Nunca se emiten eventos después de `message.end` o `error`; el backend cierra el stream.
Mientras el modelo ejecuta herramientas no se emiten `delta`; puede emitirse `ping`.

## Eventos

| Evento | `data` | Cuándo |
|--------|--------|--------|
| `message.start` | `{"user_message": Message, "assistant_message_id": "<uuid>"}` | Primer evento. `user_message` según el esquema `Message` de `openapi.yaml` (en `retry` es el mensaje existente). |
| `delta` | `{"text": "<fragmento>"}` | Cada fragmento de texto del asistente, en orden. Concatenar todos da el `content` final. |
| `ping` | `{}` | Mantenimiento de conexión cada 15 s sin actividad. El cliente lo ignora. |
| `message.end` | `{"assistant_message": Message}` | Fin correcto; `status` = `complete`. |
| `error` | `{"error": {"code", "message", "correlation_id"}, "assistant_message": Message \| null}` | Falla después de iniciado el stream. Códigos posibles: `LLM_UNAVAILABLE`, `LLM_TIMEOUT`, `LLM_INVALID_RESPONSE`, `INTERNAL_ERROR`. `assistant_message` tiene `status` = `error`. |

## Cancelación

El cliente cancela abortando la petición HTTP. El backend detecta la desconexión, cancela la
llamada al modelo y guarda el texto ya generado como mensaje `assistant` con `status` =
`incomplete` (si no se generó texto, no se guarda nada). No se envía evento final porque la
conexión ya está cerrada; el cliente marca localmente el mensaje como incompleto y puede
confirmarlo con `GET /api/v1/conversations/{id}`.

## Ejemplo

```text
event: message.start
data: {"user_message":{"id":"7b1…","role":"user","content":"Hola","status":"complete","error_code":null,"created_at":"2026-10-24T15:00:00Z"},"assistant_message_id":"c42…"}

event: delta
data: {"text":"¡Hola! "}

event: delta
data: {"text":"¿En qué puedo ayudarte?"}

event: message.end
data: {"assistant_message":{"id":"c42…","role":"assistant","content":"¡Hola! ¿En qué puedo ayudarte?","status":"complete","error_code":null,"created_at":"2026-10-24T15:00:01Z"}}

```
