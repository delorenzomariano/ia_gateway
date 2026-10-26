# IA Gateway

Backend que conecta un **chat flotante** (componente web reutilizable) con un **modelo de lenguaje
local en Ollama**, preparado para incorporar herramientas que el modelo pueda usar.

```
Navegador ⇄ (API REST + SSE) ⇄ backend IA Gateway ⇄ Ollama
   <ia-chat-widget>                 FastAPI + SQLite       (qwen3:4b por defecto)
```

- Respuestas en tiempo real (streaming), botón **Detener** y **Reintentar** ante errores.
- La conversación se conserva al recargar la página durante 24 h (configurable).
- Registro de herramientas con esquemas validados; incluye `current_time` como ejemplo.
- Imágenes adjuntas: el backend reconoce el texto (OCR con Tesseract) y el asistente responde
  sobre él. La imagen no se guarda; solo el texto reconocido.
- Logs JSON con `correlation_id`; el texto de los mensajes no se registra salvo en modo
  diagnóstico.

> **Acceso**: esta versión **no tiene autenticación**. El acceso a `/api/` se limita a las redes
> locales configuradas (`IA_GATEWAY_ALLOWED_NETWORKS`) y a los orígenes permitidos por CORS. No
> exponer el servicio a Internet sin agregar autenticación (ver
> `specs/001-chatbot-ollama-gateway/plan.md`, Complexity Tracking).

## Requisitos

- Python ≥ 3.12 y [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com) corriendo en `http://localhost:11434` con el modelo descargado:
  `ollama pull qwen3:4b`
- [Tesseract 5](https://github.com/tesseract-ocr/tesseract) con los idiomas español e inglés,
  para leer imágenes (opcional: sin él, el chat de texto funciona y las imágenes dan
  `OCR_UNAVAILABLE`):
  - Windows: instalador de [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki),
    marcando *Spanish* en "Additional language data"; luego en `backend/.env`:
    `IA_GATEWAY_OCR_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`
  - Linux: `sudo apt install tesseract-ocr tesseract-ocr-spa`
  - Para no usarlo: `IA_GATEWAY_OCR_ENABLED=false`
- Node ≥ 20 (solo para las pruebas del componente)

## Puesta en marcha

```powershell
cd backend
uv sync
Copy-Item .env.example .env   # opcional: ajustar IA_GATEWAY_*
uv run uvicorn ia_gateway.main:app --host 127.0.0.1 --port 8000
```

Abrir <http://localhost:8000/>: la página de demo con el chat en la esquina inferior derecha.
Estado del servicio: <http://localhost:8000/api/v1/health>.

## Usar el chat en otra página

```html
<script type="module" src="http://localhost:8000/widget/ia-chat-widget.js"></script>
<ia-chat-widget backend-url="http://localhost:8000" title="Asistente"></ia-chat-widget>
```

El origen de esa página debe estar en `IA_GATEWAY_ALLOWED_ORIGINS`. Con `image-upload="false"`
se oculta el botón de adjuntar imagen. Atributos, eventos y estilos:
`specs/002-chat-image-ocr/contracts/chat-widget.md`.

## API del backend

Base: `http://<host>:8000/api/v1`. Todo es JSON en UTF-8. El contrato formal vigente (v1.1.0)
está en `specs/002-chat-image-ocr/contracts/openapi.yaml` (y `sse-events.md` para el
streaming); con el backend levantado, la documentación interactiva está en
<http://localhost:8000/docs>.

| Método | Ruta | Para qué | Respuesta OK |
|--------|------|----------|--------------|
| `GET` | `/health` | Estado del backend, la base, el modelo y el OCR | `200` (o `503` si algo falla) |
| `POST` | `/conversations` | Crear una conversación vacía (sin cuerpo) | `201` `Conversation` |
| `GET` | `/conversations/{id}` | Obtener la conversación con su historial | `200` `ConversationWithMessages` |
| `DELETE` | `/conversations/{id}` | Descartarla (idempotente) | `204` |
| `POST` | `/conversations/{id}/messages` | Enviar un mensaje y obtener la respuesta | `200` JSON o stream SSE |
| `POST` | `/conversations/{id}/messages/retry` | Regenerar la respuesta al último mensaje (tras un error) | `200` JSON o stream SSE |

### Objetos

```jsonc
// Conversation
{ "id": "uuid", "created_at": "…", "last_activity_at": "…", "expires_at": "…" }

// ConversationWithMessages = Conversation +
{ "generation_in_progress": false, "messages": [ /* Message */ ] }

// Message
{
  "id": "uuid",
  "role": "user" | "assistant",
  "content": "texto (Markdown en las respuestas del asistente)",
  "status": "complete" | "incomplete" | "error",
  "error_code": null,            // código de error si status = "error"
  "created_at": "2026-10-24T15:00:00Z",
  "attachment": null             // solo en mensajes user con imagen (ver abajo)
}

// Attachment: metadatos y texto reconocido de la imagen (la imagen no se guarda)
{
  "filename": "captura.png",
  "media_type": "image/png" | "image/jpeg" | "image/webp",
  "size_bytes": 183204,
  "text": "texto reconocido…",   // hasta OCR_MAX_TEXT_CHARS (8000)
  "truncated": false             // true si el texto se recortó
}

// Cuerpo de POST /messages (retry no lleva cuerpo)
{ "content": "Hola" }           // se recorta; vacío o > MAX_MESSAGE_CHARS (4000) → 422
{                               // con imagen: content es opcional
  "content": "¿Qué dice este error?",
  "image": { "filename": "captura.png", "media_type": "image/png", "data": "<base64>" }
}

// Respuesta JSON de /messages y /messages/retry
{ "user_message": Message, "assistant_message": Message }
```

Las fechas son ISO 8601 en UTC. Una conversación vence `RETENTION_HOURS` después de la última
actividad; a partir de ahí responde `404 CONVERSATION_NOT_FOUND`.

**Imágenes**: una por mensaje, PNG, JPEG o WebP de hasta 5 MB (`OCR_MAX_IMAGE_BYTES`), en base64
estándar **sin** el prefijo `data:…;base64,`. El backend verifica el formato real, reconoce el
texto (español e inglés) **antes** de empezar a responder y se lo pasa al modelo junto con la
pregunta; las preguntas siguientes de la conversación también lo tienen en cuenta. Si la imagen
falla (formato, tamaño, sin texto, OCR caído) responde el error como JSON y no guarda nada, aun
pidiendo streaming. `GET /health` incluye `checks.ocr` (`ok`, `error` o `disabled`).

### Errores

Todos los errores, incluso los de rutas inexistentes, tienen el mismo formato:

```json
{
  "error": {
    "code": "GENERATION_IN_PROGRESS",
    "message": "Texto en español apto para mostrar al usuario",
    "correlation_id": "4f1c…",
    "details": [{ "field": "content", "issue": "…" }]
  }
}
```

`details` solo aparece en `VALIDATION_ERROR`.

| HTTP | `code` | Qué hacer en el frontend |
|------|--------|--------------------------|
| 403 | `ACCESS_DENIED` | El cliente está fuera de `ALLOWED_NETWORKS` |
| 404 | `CONVERSATION_NOT_FOUND` | Venció o no existe: crear una nueva |
| 404 / 405 | `NOT_FOUND` / `METHOD_NOT_ALLOWED` | Ruta o método incorrectos |
| 409 | `GENERATION_IN_PROGRESS` | Ya se está generando una respuesta en esa conversación: esperar |
| 413 | `IMAGE_TOO_LARGE` | La imagen (o el cuerpo) supera el máximo: pedir otra más chica |
| 422 | `VALIDATION_ERROR` / `NOTHING_TO_RETRY` | Mensaje inválido / no hay nada que reintentar |
| 422 | `IMAGE_INVALID` / `IMAGE_NO_TEXT` | Formato no admitido o dañado / imagen sin texto legible |
| 502 | `LLM_INVALID_RESPONSE` | El modelo respondió vacío o mal: ofrecer **Reintentar** |
| 503 | `LLM_UNAVAILABLE` / `OCR_UNAVAILABLE` | Ollama / el OCR no responde: ofrecer **Reintentar** (con imagen, reenviar el mensaje) |
| 504 | `LLM_TIMEOUT` / `OCR_TIMEOUT` | El modelo / el OCR tardó demasiado: ofrecer **Reintentar** |
| 500 | `INTERNAL_ERROR` | Error inesperado |

Cada respuesta trae el header `X-Correlation-ID`. Podés enviar el tuyo (1–64 caracteres
`[A-Za-z0-9-]`) para rastrear una petición en los logs del backend.

### Streaming (SSE)

Si `POST /messages` o `/messages/retry` llevan `Accept: text/event-stream`, la respuesta llega
como Server-Sent Events. Si no, llega como JSON completa. Los errores previos al stream
(404, 409, 422…) llegan igual como JSON con su código HTTP.

```text
message.start → delta* → (message.end | error)
```

| Evento | `data` |
|--------|--------|
| `message.start` | `{"user_message": Message, "assistant_message_id": "uuid"}` |
| `delta` | `{"text": "fragmento"}`: concatenar todos da la respuesta final |
| `ping` | `{}` cada 15 s sin actividad; ignorarlo |
| `message.end` | `{"assistant_message": Message}` con `status` = `complete` |
| `error` | `{"error": {code, message, correlation_id}, "assistant_message": Message \| null}` |

Como es un `POST`, **no se puede usar `EventSource`**: hay que leer el cuerpo con `fetch` y un
`ReadableStream` (ver el ejemplo). Para **detener** la respuesta, abortar la petición: el
backend corta el modelo y guarda lo generado hasta ese momento con `status` = `incomplete`.

## Consumir la API desde otro frontend

Si no querés usar `<ia-chat-widget>`, cualquier frontend puede hablar directamente con la API:

1. **Permitir el origen**: agregar el origen de tu app a `IA_GATEWAY_ALLOWED_ORIGINS` (p. ej.
   `http://localhost:5173` para Vite) y reiniciar el backend. Si el navegador corre en otra
   máquina, su red tiene que estar en `IA_GATEWAY_ALLOWED_NETWORKS`. CORS acepta `GET`, `POST`,
   `DELETE` y los headers `Content-Type`, `Accept` y `X-Correlation-ID`.
2. **Crear o recuperar la conversación**: guardar solo el `id` (p. ej. en `localStorage`). Al
   cargar, pedir `GET /conversations/{id}` para mostrar el historial; si da `404`, crear otra.
3. **Enviar mensajes** en JSON o en streaming.
4. **Mostrar el texto del modelo de forma segura**: es contenido no confiable. Usar
   `textContent` (o el escape por defecto de React/Vue/etc.), nunca `innerHTML` ni
   `dangerouslySetInnerHTML` sin sanitizar.

### Ejemplo en JavaScript

```js
const API = "http://localhost:8000/api/v1";

async function request(path, options = {}) {
  const res = await fetch(API + path, options);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const err = new Error(body?.error?.message ?? `HTTP ${res.status}`);
    err.code = body?.error?.code;
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res;
}

// 1. Conversación: reutiliza la guardada o crea una nueva
async function getConversation() {
  const saved = localStorage.getItem("conversationId");
  if (saved) {
    try {
      return await (await request(`/conversations/${saved}`)).json(); // trae messages[]
    } catch (e) {
      if (e.code !== "CONVERSATION_NOT_FOUND") throw e;
    }
  }
  const conv = await (await request("/conversations", { method: "POST" })).json();
  localStorage.setItem("conversationId", conv.id);
  return { ...conv, messages: [] };
}

// 2a. Respuesta completa (JSON)
async function ask(conversationId, content) {
  const res = await request(`/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ content }),
  });
  const { assistant_message } = await res.json();
  return assistant_message.content;
}

// 2b. Respuesta en streaming (SSE sobre fetch)
async function askStream(conversationId, content, { onDelta, signal, retry = false }) {
  const path = `/conversations/${conversationId}/messages${retry ? "/retry" : ""}`;
  const res = await request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: retry ? undefined : JSON.stringify({ content }),
    signal, // AbortController.signal para el botón "Detener"
  });

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      const payload = data ? JSON.parse(data) : {};
      if (event === "delta") onDelta(payload.text);
      else if (event === "message.end") return payload.assistant_message;
      else if (event === "error") {
        const err = new Error(payload.error.message);
        err.code = payload.error.code; // LLM_* → ofrecer reintentar (retry: true)
        throw err;
      }
      // message.start y ping: nada que hacer en este ejemplo
    }
  }
  throw new Error("El stream se cortó antes de terminar");
}

// Uso
const conv = await getConversation();
const controller = new AbortController(); // controller.abort() detiene la respuesta
let text = "";
await askStream(conv.id, "¿Qué es Ollama?", {
  signal: controller.signal,
  onDelta: (chunk) => {
    text += chunk;
    document.querySelector("#respuesta").textContent = text; // nunca innerHTML
  },
});

// "Nueva conversación": si hay una respuesta en curso, abortarla antes
// (el DELETE responde 409 mientras se está generando)
await request(`/conversations/${conv.id}`, { method: "DELETE" });
localStorage.removeItem("conversationId");
```

### Enviar una imagen

```js
// <input type="file" accept="image/png,image/jpeg,image/webp">
async function toImagePayload(file) {
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) throw new Error("Formato no admitido");
  if (file.size > 5 * 1024 * 1024) throw new Error("La imagen supera 5 MB");
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
  // Se envía solo el base64, sin el prefijo "data:image/png;base64,"
  return { filename: file.name, media_type: file.type, data: dataUrl.split(",")[1] };
}

const image = await toImagePayload(input.files[0]);
const res = await request(`/conversations/${conv.id}/messages`, {
  method: "POST",
  headers: { "Content-Type": "application/json", Accept: "application/json" },
  body: JSON.stringify({ content: "¿Qué dice este error?", image }),
});
const { user_message, assistant_message } = await res.json();
console.log(user_message.attachment.text); // texto reconocido en la imagen
// Mostrar una vista previa local: img.src = URL.createObjectURL(file)  (nunca innerHTML)
```

El streaming funciona igual: el mismo cuerpo con `Accept: text/event-stream`. Mientras el
backend lee la imagen todavía no llega `message.start`, así que conviene mostrar algo como
"Leyendo la imagen…".

### Desde la línea de comandos

```powershell
$api = "http://localhost:8000/api/v1"
$conv = Invoke-RestMethod -Method Post "$api/conversations"
Invoke-RestMethod -Method Post "$api/conversations/$($conv.id)/messages" `
  -ContentType "application/json" -Body '{"content":"Hola"}'

# Streaming (curl.exe, -N para no bufferizar)
curl.exe -N -X POST "$api/conversations/$($conv.id)/messages" `
  -H "Content-Type: application/json" -H "Accept: text/event-stream" `
  -d '{\"content\":\"Contame un chiste\"}'
```

> Las llamadas desde otro **backend** (no navegador) no pasan por CORS, pero sí por el control de
> red: la IP de origen tiene que estar en `IA_GATEWAY_ALLOWED_NETWORKS`.

## Configuración

Todas las opciones son variables de entorno con prefijo `IA_GATEWAY_` (o `backend/.env`); la
lista completa con valores por defecto está en `backend/.env.example`. Las más usadas:

| Variable | Por defecto | Para qué |
|----------|-------------|----------|
| `OLLAMA_MODEL` | `qwen3:4b` | Modelo de Ollama |
| `SYSTEM_PROMPT` | asistente en español | Comportamiento del asistente |
| `TOOLS_ENABLED` | vacío | Herramientas habilitadas, p. ej. `current_time` |
| `RETENTION_HOURS` | `24` | Vida de una conversación sin actividad |
| `ALLOWED_ORIGINS` / `ALLOWED_NETWORKS` | localhost / redes privadas | Restricción de acceso |
| `DIAGNOSTIC_MODE` | `false` | Incluir el texto de los mensajes en los logs |
| `OCR_ENABLED` | `true` | Permitir imágenes en el chat |
| `OCR_TESSERACT_CMD` | vacío (`PATH`) | Ruta de `tesseract.exe` |
| `OCR_LANGUAGES` | `spa+eng` | Idiomas de reconocimiento |
| `OCR_MAX_IMAGE_BYTES` | `5242880` | Tamaño máximo de la imagen (debe coincidir con `max-image-bytes` del componente) |
| `OCR_MAX_TEXT_CHARS` / `OCR_TIMEOUT_S` | `8000` / `30` | Texto reconocido máximo / tiempo máximo del OCR |

## Pruebas

```powershell
cd backend
uv run pytest                      # suite completa, sin Ollama real
uv run pytest -m ollama -s         # contra Ollama real (incluye la medición de SC-002)
uv run pytest -m tesseract -s      # contra Tesseract real (tiempo de reconocimiento, 002 SC-002)
uv run ruff check .

cd ../frontend
npm install
npx vitest run
```

Escenarios de validación manual: `specs/001-chatbot-ollama-gateway/quickstart.md` y
`specs/002-chat-image-ocr/quickstart.md`.

## Documentación del diseño

- `specs/001-chatbot-ollama-gateway/`: chat flotante con Ollama.
- `specs/002-chat-image-ocr/`: imágenes con reconocimiento de texto (contratos vigentes).

Cada carpeta tiene especificación, plan, decisiones (`research.md`), modelo de datos, contratos
y lista de tareas. Principios del proyecto: `.specify/memory/constitution.md`.
