# Data Model: Chatbot flotante con backend conectado a LLM local

**Feature**: `001-chatbot-ollama-gateway` | **Date**: 2026-10-24

Almacenamiento: SQLite (ver [research.md](research.md) R5). Fechas en UTC, ISO 8601. Los
identificadores son UUIDv4 en texto.

## Conversation

| Campo | Tipo | Reglas |
|-------|------|--------|
| `id` | UUID | PK, generado por el backend |
| `created_at` | datetime | inmutable |
| `last_activity_at` | datetime | se actualiza al guardar cada mensaje |
| `expires_at` | datetime | `last_activity_at + retention` (por defecto 24 h); se recalcula con cada actividad |

**Reglas**:

- Una conversación con `expires_at <= ahora` se trata como inexistente en toda lectura
  (`404 CONVERSATION_NOT_FOUND`) y la tarea de limpieza la borra junto con sus mensajes e
  invocaciones (borrado en cascada).
- A lo sumo una generación en curso por conversación (control en memoria del proceso); un segundo
  envío concurrente devuelve `409 GENERATION_IN_PROGRESS`.
- "Nueva conversación" (FR-013a) = el cliente borra la actual (`DELETE`) y crea otra.

**Estados**: `active` → `expired` (derivado de `expires_at`) → eliminada (limpieza o `DELETE`).

## Message

| Campo | Tipo | Reglas |
|-------|------|--------|
| `id` | UUID | PK |
| `conversation_id` | UUID | FK → Conversation, `ON DELETE CASCADE` |
| `seq` | int | orden dentro de la conversación, único por conversación, creciente |
| `role` | enum | `user`, `assistant`, `tool` (el mensaje de sistema no se guarda: se toma de la configuración en cada solicitud) |
| `content` | text | `user`: recortado, 1–`max_message_chars` (por defecto 4000); `assistant`: texto validado (ver abajo); `tool`: JSON serializado del resultado |
| `status` | enum | `complete`, `incomplete`, `error` |
| `error_code` | text, nullable | código de error de la API cuando `status = error` |
| `tool_calls` | JSON, nullable | solo `assistant`: llamadas solicitadas por el modelo `[{name, arguments}]` |
| `tool_name` | text, nullable | solo `tool`: herramienta cuyo resultado contiene |
| `model` | text, nullable | solo `assistant`: modelo que generó la respuesta |
| `prompt_tokens` / `completion_tokens` | int, nullable | solo `assistant`, si Ollama los informa |
| `created_at` | datetime | |

**Validación de la respuesta del modelo (FR-015)**: `content` debe ser texto; se eliminan
caracteres de control salvo `\n` y `\t`; se descarta cualquier contenido de "thinking". Si el
resultado final queda vacío y no hubo llamadas a herramientas → mensaje `error` con
`LLM_INVALID_RESPONSE`.

**Visibilidad**: `GET /conversations/{id}` devuelve solo `user` y `assistant` sin `tool_calls`
pendientes; los mensajes `tool` y los `assistant` que solo contienen llamadas a herramientas son
internos.

**Contexto enviado al modelo**: sistema + mensajes `complete`/`incomplete` (se excluyen `error`)
más recientes dentro del presupuesto de caracteres, preservando pares `assistant(tool_calls)` →
`tool` completos.

**Transiciones del mensaje `assistant`**:

```text
(generando, solo en memoria)
   ├── el modelo termina con texto válido ............ → complete
   ├── el cliente aborta / se corta la conexión ...... → incomplete (se guarda el texto recibido; si está vacío no se guarda)
   └── timeout / Ollama caído / respuesta inválida ... → error (content vacío, error_code)
```

El mensaje `user` se guarda como `complete` antes de llamar al modelo, de modo que un reintento
tras un error no duplica la pregunta: el cliente reintenta con `POST
/conversations/{id}/messages/retry`, que regenera la respuesta al último mensaje `user`.

## ToolInvocation

| Campo | Tipo | Reglas |
|-------|------|--------|
| `id` | UUID | PK |
| `conversation_id` | UUID | FK → Conversation, `ON DELETE CASCADE` |
| `assistant_message_id` | UUID | FK → Message que solicitó la llamada |
| `tool_name` | text | nombre solicitado por el modelo (puede no estar registrado) |
| `arguments` | JSON | tal como los envió el modelo |
| `status` | enum | `ok`, `error`, `rejected` (herramienta no registrada o argumentos inválidos) |
| `result` | JSON, nullable | salida validada contra el esquema de salida |
| `error` | text, nullable | mensaje técnico (sin secretos) |
| `duration_ms` | int | |
| `created_at` | datetime | |

## Tool (en memoria, no persistida)

| Campo | Tipo | Reglas |
|-------|------|--------|
| `name` | text | único en el registro, patrón `^[a-z][a-z0-9_]{0,63}$` |
| `description` | text | 1–1024 caracteres, se envía al modelo |
| `input_model` | modelo Pydantic | genera el JSON Schema de parámetros enviado al modelo; valida argumentos |
| `output_model` | modelo Pydantic | valida el resultado antes de devolverlo al modelo |
| `timeout_s` | float | por defecto 10 s; excederlo → invocación `error` |
| `handler` | función async | recibe la entrada validada y devuelve la salida |

**Reglas**: solo las herramientas listadas en `IA_GATEWAY_TOOLS_ENABLED` se registran al iniciar;
con el registro vacío no se envía `tools` a Ollama. Un nombre no registrado → invocación
`rejected` y se devuelve al modelo un resultado de error para que continúe sin ella.

## Configuración (no persistida, variables de entorno con prefijo `IA_GATEWAY_`)

| Clave | Por defecto |
|-------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `OLLAMA_MODEL` | `qwen3:4b` |
| `OLLAMA_THINK` | vacío (no se envía; ver research.md R3) |
| `OLLAMA_NUM_CTX` | `8192` |
| `SYSTEM_PROMPT` | texto en español que define al asistente |
| `MAX_MESSAGE_CHARS` | `4000` |
| `CONTEXT_CHAR_BUDGET` | `24000` |
| `RETENTION_HOURS` | `24` |
| `CLEANUP_INTERVAL_MINUTES` | `10` |
| `TIMEOUT_CONNECT_S` / `TIMEOUT_FIRST_CHUNK_S` / `TIMEOUT_IDLE_S` / `TIMEOUT_TOTAL_S` | `5` / `60` / `30` / `180` |
| `MAX_TOOL_ROUNDS` | `5` |
| `TOOLS_ENABLED` | vacío |
| `ALLOWED_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` |
| `ALLOWED_NETWORKS` | `127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` |
| `DATABASE_PATH` | `data/ia_gateway.db` |
| `SERVE_FRONTEND` | `true` |
| `DIAGNOSTIC_MODE` | `false` |
| `LOG_LEVEL` | `INFO` |
