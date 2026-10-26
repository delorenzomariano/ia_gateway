---

description: "Task list for 001-chatbot-ollama-gateway"
---

# Tasks: Chatbot flotante con backend conectado a LLM local

**Input**: Design documents from `/specs/001-chatbot-ollama-gateway/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (openapi.yaml,
sse-events.md, chat-widget.md), quickstart.md

**Tests**: INCLUIDOS. La constitución (principio V) exige pruebas de contrato por endpoint,
pruebas de adaptadores con dobles y pruebas de integración de los flujos críticos, escritas antes
o junto con la implementación. Ninguna prueba de la suite por defecto usa Ollama real.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4 de spec.md)
- Include exact file paths in descriptions

## Path Conventions

- Backend: `backend/src/ia_gateway/`, pruebas en `backend/tests/`
- Frontend: `frontend/widget/`, pruebas en `frontend/tests/`
- Contratos de referencia: `specs/001-chatbot-ollama-gateway/contracts/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [X] T001 Inicializar git en la raíz del repo y crear `.gitignore` con `backend/.venv/`, `backend/data/`, `backend/.env`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `frontend/node_modules/`
- [X] T002 Crear `backend/pyproject.toml` (proyecto `ia-gateway`, layout `src/`, `requires-python = ">=3.12"`; dependencias `fastapi`, `uvicorn[standard]`, `httpx`, `pydantic-settings`; grupo dev `pytest`, `pytest-asyncio`, `respx`, `ruff`, `pyyaml`, `jsonschema`, `referencing`; `[tool.pytest.ini_options]` con `asyncio_mode = "auto"`, `testpaths = ["tests"]`, marker `ollama` excluido por defecto con `addopts = "-m 'not ollama'"`; `[tool.ruff]` line-length 100) y ejecutar `uv sync` en `backend/`
- [X] T003 Crear el árbol de paquetes vacío según plan.md: `backend/src/ia_gateway/__init__.py` y `__init__.py` en `api/`, `chat/`, `llm/`, `tools/`, `storage/`, `observability/`; directorios `backend/tests/{contract,integration,unit}/` con `__init__.py`
- [X] T004 [P] Crear `frontend/package.json` (`"type": "module"`, devDependencies `vitest` y `happy-dom`, script `"test": "vitest run"`) y `frontend/vitest.config.js` con `environment: 'happy-dom'`; ejecutar `npm install` en `frontend/`
- [X] T005 [P] Crear `backend/.env.example` con todas las variables `IA_GATEWAY_*` y sus valores por defecto de la tabla "Configuración" de `data-model.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Interfaces y pruebas de la base (escribir primero; deben FALLAR hasta completar la implementación)

- [X] T006 [P] Definir la interfaz de almacenamiento en `backend/src/ia_gateway/storage/repository.py`: dataclasses de dominio `ConversationRecord`, `MessageRecord` (campos de `data-model.md`: `id`, `conversation_id`, `seq`, `role` ∈ `user|assistant|tool`, `content`, `status` ∈ `complete|incomplete|error`, `error_code`, `tool_calls`, `tool_name`, `model`, `prompt_tokens`, `completion_tokens`, `created_at`), `ToolInvocationRecord` (`status` ∈ `ok|error|rejected`) y `Protocol` `ConversationRepository` con `create_conversation`, `get_conversation` (devuelve `None` si `expires_at <= ahora`), `delete_conversation`, `add_message` (asigna `seq` creciente y actualiza `last_activity_at` y `expires_at = last_activity_at + retention`), `list_messages`, `add_tool_invocation`, `delete_expired`
- [X] T007 [P] Definir la interfaz del modelo en `backend/src/ia_gateway/llm/base.py`: `ChatMessage` (role `system|user|assistant|tool`, content, tool_calls, tool_name), `ToolSpec` (name, description, parameters JSON Schema), `LLMChunk` (`text`, `tool_calls`, `done`, `prompt_tokens`, `completion_tokens`), `Protocol` `LLMClient` con `chat_stream(messages, tools) -> AsyncIterator[LLMChunk]` y `health() -> (ok, model_available, detail)`; excepciones `LLMUnavailableError`, `LLMTimeoutError`, `LLMInvalidResponseError`
- [X] T008 [P] Pruebas unitarias del repositorio en `backend/tests/unit/test_sqlite_repository.py` contra la interfaz de T006 (importando `SqliteConversationRepository` de `storage/sqlite.py`, aún inexistente): `seq` creciente, actualización de `expires_at`, conversación vencida devuelve `None`, `delete_expired` borra en cascada mensajes e invocaciones, los datos persisten al reabrir el archivo (caso borde de reinicio) (depends on T006)
- [X] T009 [P] Pruebas de infraestructura en `backend/tests/integration/test_infrastructure.py` (usan los fixtures `client`/`settings` de T019): header `X-Correlation-ID` generado y reutilizado; formato de error uniforme en ruta inexistente de `/api/v1`; IP fuera de `ALLOWED_NETWORKS` → `403 ACCESS_DENIED`; preflight CORS rechaza origen no listado
- [X] T010 [P] Prueba de contrato estructural en `backend/tests/contract/test_openapi_contract.py`: cargar `specs/001-chatbot-ollama-gateway/contracts/openapi.yaml` con pyyaml y verificar que, para cada `operationId` de la constante `IMPLEMENTED_OPERATIONS` (vacía en esta fase; cada historia agrega las suyas), el OpenAPI generado por la app tiene la misma ruta, método y códigos de respuesta; crear también `backend/tests/contract/schema_utils.py` con `assert_matches_schema(body, schema_name)` que valida un cuerpo contra `components.schemas` de `openapi.yaml` resolviendo `$ref` con `jsonschema` + `referencing`

### Implementación de la base

- [X] T011 Implementar `Settings` en `backend/src/ia_gateway/config.py` con pydantic-settings (prefijo `IA_GATEWAY_`, lectura de `.env`) con exactamente las claves y defaults de `data-model.md` § Configuración (`OLLAMA_BASE_URL=http://localhost:11434`, `OLLAMA_MODEL=qwen3:4b`, `OLLAMA_THINK=false`, `OLLAMA_NUM_CTX=8192`, `SYSTEM_PROMPT`, `MAX_MESSAGE_CHARS=4000`, `CONTEXT_CHAR_BUDGET=24000`, `RETENTION_HOURS=24`, `CLEANUP_INTERVAL_MINUTES=10`, `TIMEOUT_CONNECT_S=5`, `TIMEOUT_FIRST_CHUNK_S=60`, `TIMEOUT_IDLE_S=30`, `TIMEOUT_TOTAL_S=180`, `MAX_TOOL_ROUNDS=5`, `TOOLS_ENABLED` lista vacía, `ALLOWED_ORIGINS`, `ALLOWED_NETWORKS` como listas separadas por coma, `DATABASE_PATH=data/ia_gateway.db`, `SERVE_FRONTEND=true`, `DIAGNOSTIC_MODE=false`, `LOG_LEVEL=INFO`); `SYSTEM_PROMPT` por defecto en español describiendo un asistente útil y conciso
- [X] T012 [P] Implementar correlación en `backend/src/ia_gateway/observability/correlation.py`: `contextvar` `correlation_id`, middleware ASGI que reutiliza `X-Correlation-ID` entrante si cumple `^[A-Za-z0-9-]{1,64}$` o genera un UUID4, y lo agrega como header `X-Correlation-ID` a toda respuesta (incluidas SSE y errores)
- [X] T013 [P] Implementar logging JSON en `backend/src/ia_gateway/observability/logging.py`: formateador que emite una línea JSON por registro con `timestamp`, `level`, `logger`, `message`, `correlation_id` (desde el contextvar) y campos extra; función `configure_logging(settings)`; helper `log_content(field, text)` que solo incluye texto de mensajes si `DIAGNOSTIC_MODE` es true; advertencia `WARNING` al iniciar con modo diagnóstico activo (FR-022)
- [X] T014 [P] Implementar errores uniformes en `backend/src/ia_gateway/api/errors.py`: enum de códigos (`VALIDATION_ERROR`, `NOTHING_TO_RETRY`, `ACCESS_DENIED`, `CONVERSATION_NOT_FOUND`, `GENERATION_IN_PROGRESS`, `LLM_UNAVAILABLE`, `LLM_TIMEOUT`, `LLM_INVALID_RESPONSE`, `INTERNAL_ERROR`) con su estado HTTP (422, 422, 403, 404, 409, 503, 504, 502, 500) y mensaje en español para el usuario; excepción `ApiError`; handlers que devuelven `{"error": {"code", "message", "correlation_id", "details?"}}` para `ApiError`, `RequestValidationError` (con `details` `[{field, issue}]`) y excepciones no manejadas (`INTERNAL_ERROR`, sin filtrar detalles internos)
- [X] T015 [P] Definir los modelos Pydantic del contrato en `backend/src/ia_gateway/api/schemas.py` según `contracts/openapi.yaml`: `Conversation`, `ConversationWithMessages` (con `generation_in_progress`), `Message` (`role` ∈ `user|assistant`, `status` ∈ `complete|incomplete|error`, `error_code` nullable), `SendMessageRequest` (`content` string, `extra="forbid"`; recortar espacios y rechazar si queda vacío o supera `MAX_MESSAGE_CHARS`), `SendMessageResponse`, `Health`, `HealthCheck`, `ErrorResponse`
- [X] T016 Implementar `SqliteConversationRepository` en `backend/src/ia_gateway/storage/sqlite.py`: creación de esquema al iniciar (tablas `conversations`, `messages` con `UNIQUE(conversation_id, seq)`, `tool_invocations`, FKs `ON DELETE CASCADE`, `PRAGMA foreign_keys=ON`, `journal_mode=WAL`), creación del directorio de `DATABASE_PATH`, fechas UTC ISO 8601, JSON para `tool_calls`/`arguments`/`result`; operaciones bloqueantes ejecutadas con `anyio.to_thread.run_sync`; método `ping()` para health (depends on T006)
- [X] T017 Implementar control de acceso en `backend/src/ia_gateway/api/access.py` y `backend/src/ia_gateway/api/router.py`: middleware `NetworkAccessMiddleware` que responde `403 ACCESS_DENIED` a toda ruta bajo `/api/` si la IP del cliente no pertenece a `ALLOWED_NETWORKS` (usar `ipaddress`; cubre también rutas inexistentes); `build_api_router()` con prefijo `/api/v1` y comentario indicando que es el punto único para agregar autenticación (excepción documentada en plan.md) (depends on T011, T014)
- [X] T018 Implementar la app factory en `backend/src/ia_gateway/main.py`: `create_app(settings=None, llm_client=None, repository=None)` que configura logging, middleware de correlación, `CORSMiddleware` con `ALLOWED_ORIGINS` (exponer header `X-Correlation-ID`), handlers de error, `api_router`, montaje estático de `frontend/` en `/` si `SERVE_FRONTEND`; `lifespan` que inicializa el repositorio, ejecuta `delete_expired()` al iniciar y cada `CLEANUP_INTERVAL_MINUTES`, y cierra el cliente LLM; log por solicitud con método, ruta, estado y duración; `app = create_app()` a nivel de módulo (depends on T011–T017)
- [X] T019 Crear dobles y fixtures en `backend/tests/fakes.py` y `backend/tests/conftest.py`: `FakeLLMClient` programable (lista de chunks por llamada, latencia simulada, excepción a lanzar, registro de mensajes y tools recibidos, soporte de cancelación), fixture `settings` con base SQLite en `tmp_path`, fixture `app` vía `create_app` con dobles, fixture `client` `httpx.AsyncClient(transport=ASGITransport(app), base_url="http://127.0.0.1")` (depends on T018); al terminar, T008–T010 DEBEN pasar

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Conversar con el asistente desde el chat flotante (Priority: P1) 🎯 MVP

**Goal**: el usuario abre el chat flotante en la página de demo, envía mensajes y recibe respuestas de Ollama (modo JSON) con contexto de la conversación, que se conserva al recargar y puede reiniciar.

**Independent Test**: quickstart.md escenarios 1–6 y 16; `uv run pytest tests/contract/test_conversations_contract.py tests/contract/test_openapi_contract.py tests/integration/test_conversation_flow.py` y `npx vitest run` pasan.

### Tests for User Story 1 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T020 [P] [US1] Pruebas de contrato en `backend/tests/contract/test_conversations_contract.py`: `POST /api/v1/conversations` → 201 con esquema `Conversation`; `GET /api/v1/conversations/{id}` → 200 `ConversationWithMessages` y 404 `CONVERSATION_NOT_FOUND`; `DELETE` → 204 idempotente; `POST .../messages` con `Accept: application/json` → 200 `SendMessageResponse`, 422 `VALIDATION_ERROR` para contenido vacío/solo espacios, para más de 4000 caracteres y para campos extra; `GET /api/v1/health` → esquema `Health`. Validar cuerpos con `assert_matches_schema` de `backend/tests/contract/schema_utils.py`; agregar `getHealth`, `createConversation`, `getConversation`, `deleteConversation` y `sendMessage` a `IMPLEMENTED_OPERATIONS` en `backend/tests/contract/test_openapi_contract.py`
- [X] T021 [P] [US1] Pruebas unitarias del contexto en `backend/tests/unit/test_context.py`: incluye el mensaje de sistema primero; excluye mensajes `error`; incluye `incomplete`; respeta `CONTEXT_CHAR_BUDGET` conservando los más recientes (`test_budget_keeps_latest`); siempre incluye el mensaje actual aunque exceda el presupuesto
- [X] T022 [P] [US1] Pruebas unitarias de validación de salida en `backend/tests/unit/test_validation.py`: elimina caracteres de control salvo `\n` y `\t`; texto vacío tras sanear se marca inválido
- [X] T023 [P] [US1] Pruebas del adaptador en `backend/tests/unit/test_ollama_client.py` con `respx`: `POST /api/chat` recibe `model`, `messages`, `stream: true`, `think` según config, `options.num_ctx`, y header `X-Correlation-ID`; parseo de NDJSON a `LLMChunk` (texto, `done`, `prompt_eval_count` → `prompt_tokens`, `eval_count` → `completion_tokens`); el campo `thinking` se descarta; `health()` usa `GET /api/tags` e informa si el modelo configurado está en la lista
- [X] T024 [P] [US1] Prueba de integración en `backend/tests/integration/test_conversation_flow.py` con `FakeLLMClient`: crear conversación, enviar 2 mensajes, verificar que la segunda llamada al LLM recibe el primer intercambio como contexto, que `GET` devuelve 4 mensajes visibles en orden, que tras recrear la app sobre la misma base la conversación sigue disponible, que una conversación vencida devuelve 404, y que un segundo envío mientras hay una generación en curso devuelve `409 GENERATION_IN_PROGRESS`
- [X] T025 [P] [US1] Pruebas del renderer en `frontend/tests/markdown.test.js`: párrafos, listas con `-` y `1.`, bloques ```` ``` ```` y código en línea; un texto con `<script>` o `<img onerror>` se muestra literal y no crea elementos HTML de esos tipos
- [X] T026 [P] [US1] Pruebas del cliente API en `frontend/tests/api-client.test.js` con `fetch` simulado: crear, obtener, borrar conversación y enviar mensaje en modo JSON; un 404 lanza un error con `code` `CONVERSATION_NOT_FOUND`
- [X] T027 [P] [US1] Pruebas del componente en `frontend/tests/widget.test.js`: el botón flotante abre/cierra la ventana (`role="dialog"`); `Enter` envía y `Shift+Enter` agrega salto de línea; `Escape` cierra y devuelve el foco al botón; no envía mensajes vacíos ni mayores a `max-length`; deshabilita el envío mientras espera; restaura el historial con el id de `localStorage` y descarta el id ante 404; "Nueva conversación" llama a `DELETE` y limpia el historial; emite `ia-chat:open` / `ia-chat:close`

### Implementation for User Story 1

- [X] T028 [P] [US1] Implementar `build_context(system_prompt, messages, current, budget)` en `backend/src/ia_gateway/chat/context.py` según `data-model.md` (sistema + mensajes `complete`/`incomplete` más recientes dentro de `CONTEXT_CHAR_BUDGET`, sin cortar pares `assistant(tool_calls)` → `tool`, siempre incluye el mensaje actual)
- [X] T029 [P] [US1] Implementar `sanitize_llm_text(text) -> str` en `backend/src/ia_gateway/chat/validation.py` (eliminar caracteres de control salvo `\n` y `\t`; si el resultado queda vacío y no hubo tool calls → `LLMInvalidResponseError`)
- [X] T030 [P] [US1] Implementar `GenerationLocks` en `backend/src/ia_gateway/chat/locks.py`: a lo sumo una generación en curso por conversación; `acquire(conversation_id)` lanza `ApiError(GENERATION_IN_PROGRESS)` si ya está tomada; `is_busy(conversation_id)` para `generation_in_progress`
- [X] T031 [P] [US1] Implementar `OllamaClient` en `backend/src/ia_gateway/llm/ollama.py` con `httpx.AsyncClient`: `chat_stream` hace `POST {OLLAMA_BASE_URL}/api/chat` con `stream: true`, `think: OLLAMA_THINK`, `options.num_ctx`, propaga `X-Correlation-ID`, parsea NDJSON a `LLMChunk` descartando `thinking`; `health` consulta `GET /api/tags`; `aclose()`
- [X] T032 [US1] Implementar `ChatOrchestrator` en `backend/src/ia_gateway/chat/orchestrator.py` (sin herramientas aún): `send(conversation_id, content)` adquiere el lock, guarda el mensaje `user` como `complete`, arma el contexto, consume `chat_stream` y emite fragmentos como async generator de eventos internos (`start`, `delta`, `end`), sanea el texto final, guarda el mensaje `assistant` (`model`, tokens) y registra en log latencia del primer fragmento y total, tokens y `correlation_id` (texto solo vía `log_content`) (depends on T028–T031)
- [X] T033 [US1] Implementar endpoints en `backend/src/ia_gateway/api/conversations.py`: `POST /conversations` (201), `GET /conversations/{id}` (solo mensajes `user` y `assistant` sin `tool_calls`, más `generation_in_progress`), `DELETE /conversations/{id}` (204 idempotente, 409 si hay generación en curso), `POST /conversations/{id}/messages` en modo `application/json` que consume el orquestador y devuelve `SendMessageResponse`; registrar en `api_router` (depends on T032)
- [X] T034 [US1] Implementar `GET /api/v1/health` en `backend/src/ia_gateway/api/health.py`: `checks.database` vía `repository.ping()`, `checks.llm` vía `llm_client.health()` con `model` y `model_available`; `200 status=ok` si todo está bien, si no `503 status=degraded`
- [X] T035 [US1] Conectar `OllamaClient`, repositorio, `GenerationLocks` y `ChatOrchestrator` como dependencias en `backend/src/ia_gateway/main.py` (inyectables desde `create_app` para pruebas)
- [X] T036 [P] [US1] Implementar el renderer seguro en `frontend/widget/markdown.js`: `renderMarkdown(text) -> DocumentFragment` que crea nodos con `document.createElement` y `textContent` (párrafos, listas, bloques de código, código en línea); prohibido usar `innerHTML`
- [X] T037 [P] [US1] Implementar el cliente API en `frontend/widget/api-client.js`: clase `ApiClient(baseUrl)` con `createConversation`, `getConversation`, `deleteConversation`, `sendMessage(id, content)` en modo JSON; los errores de API se convierten en `ApiClientError {code, message, correlationId, status}`
- [X] T038 [P] [US1] Implementar estilos del Shadow DOM en `frontend/widget/styles.js`: botón flotante en esquina (`position` `bottom-right`/`bottom-left`), ventana superpuesta, diferenciación visual de mensajes de usuario/asistente, indicador "respondiendo", propiedades CSS `--ia-chat-accent`, `--ia-chat-font`, `--ia-chat-z-index`, y ventana a pantalla completa con botón de cerrar visible bajo 480 px de ancho
- [X] T039 [US1] Implementar el Custom Element en `frontend/widget/ia-chat-widget.js` según `contracts/chat-widget.md`: atributos `backend-url` (opcional; si se omite o está vacío usa `location.origin`), `title` (`Asistente`), `storage-key` (`ia-chat:conversation-id`), `max-length` (`4000`), `position`; botón flotante enfocable; ventana `role="dialog"` con `aria-label`; historial con `aria-live="polite"`; envío con Enter, salto con Shift+Enter, Escape cierra y devuelve foco; validación de vacío y largo; indicador "respondiendo"; restauración del historial desde `localStorage` y descarte del id ante 404; botón "Nueva conversación"; eventos `ia-chat:open`, `ia-chat:close` (`bubbles`, `composed`) (depends on T036–T038)
- [X] T040 [US1] Crear la página de demo `frontend/index.html` con contenido de ejemplo en español y `<script type="module" src="/widget/ia-chat-widget.js">` + `<ia-chat-widget>` sin `backend-url` (mismo origen)

**Checkpoint**: User Story 1 completamente funcional y verificable de forma independiente (MVP)

---

## Phase 4: User Story 2 - Ver la respuesta a medida que se genera (Priority: P2)

**Goal**: la respuesta aparece de forma incremental vía SSE y el usuario puede detenerla, conservando el texto parcial como `incomplete`.

**Independent Test**: quickstart.md escenarios 7–8; `uv run pytest tests/contract/test_sse_contract.py tests/integration/test_streaming.py` pasa.

### Tests for User Story 2 ⚠️

- [X] T041 [P] [US2] Prueba de contrato SSE en `backend/tests/contract/test_sse_contract.py`: con `Accept: text/event-stream` la respuesta es `200 text/event-stream` con `Cache-Control: no-cache` y `X-Correlation-ID`; secuencia `message.start` → `delta`* → `message.end` con los `data` de `contracts/sse-events.md`; la concatenación de `delta.text` es igual a `assistant_message.content`; nada después de `message.end`
- [X] T042 [P] [US2] Prueba de integración en `backend/tests/integration/test_streaming.py`: cancelar el cliente a mitad del stream guarda el mensaje `assistant` con `status = incomplete` y el texto recibido; si no se generó texto no se guarda mensaje; el lock se libera; se emite `ping` tras 15 s sin actividad (usar intervalo configurable reducido en la prueba)
- [X] T043 [P] [US2] Pruebas frontend en `frontend/tests/api-client.test.js` y `frontend/tests/widget.test.js`: el lector SSE parsea eventos partidos entre chunks; el texto se agrega incrementalmente; el botón "Detener" aborta la petición y marca el mensaje como incompleto; con `streaming="false"` usa modo JSON; "Nueva conversación" durante una generación aborta primero y luego llama a `DELETE`, reintentando ante `409`

### Implementation for User Story 2

- [X] T044 [P] [US2] Implementar serialización SSE en `backend/src/ia_gateway/api/sse.py`: `format_event(event, data) -> str` (`event: <tipo>\ndata: <json en una línea>\n\n`) y generador de `ping` cada 15 s sin actividad (intervalo configurable para pruebas)
- [X] T045 [US2] Agregar al `ChatOrchestrator` en `backend/src/ia_gateway/chat/orchestrator.py` el manejo de cancelación: ante `asyncio.CancelledError`/desconexión, cancelar la iteración de `chat_stream`, guardar el texto acumulado como `assistant` `incomplete` (omitir si está vacío), liberar el lock y registrar en log la cancelación
- [X] T046 [US2] Agregar a `POST /api/v1/conversations/{id}/messages` en `backend/src/ia_gateway/api/conversations.py` la negociación por `Accept`: con `text/event-stream` devolver `StreamingResponse` con eventos `message.start` (`user_message`, `assistant_message_id`), `delta` (`text`), `ping`, `message.end` (`assistant_message`), header `Cache-Control: no-cache`; detectar desconexión con `request.is_disconnected()` para cancelar; errores previos al stream (404, 409, 422) siguen como JSON (depends on T044, T045)
- [X] T047 [US2] Agregar a `frontend/widget/api-client.js` `sendMessageStream(id, content, {onStart, onDelta, onEnd, onError, signal})` con `fetch` + `ReadableStream` + `TextDecoder`, parser SSE tolerante a eventos partidos entre chunks, que ignora `ping` y usa `AbortController` para cancelar
- [X] T048 [US2] Actualizar `frontend/widget/ia-chat-widget.js`: atributo `streaming` (por defecto `true`); render incremental de `delta` re-renderizando el mensaje con `renderMarkdown`; botón "Detener" visible durante la generación que aborta y marca el mensaje como incompleto; bloquear nuevos envíos hasta terminar o detener; "Nueva conversación" durante una generación primero aborta la petición y luego llama a `DELETE`, reintentando hasta 3 veces con 300 ms de espera si recibe `409 GENERATION_IN_PROGRESS` (FR-013a) (depends on T047)

**Checkpoint**: User Stories 1 y 2 funcionan de forma independiente

---

## Phase 5: User Story 3 - Recibir mensajes claros cuando algo falla (Priority: P2)

**Goal**: caídas, demoras y respuestas inválidas del modelo se informan con mensajes comprensibles y opción de reintentar sin duplicar la pregunta.

**Independent Test**: quickstart.md escenarios 9–11; `uv run pytest tests/integration/test_llm_failures.py tests/contract/test_retry_contract.py` pasa.

### Tests for User Story 3 ⚠️

- [X] T049 [P] [US3] Pruebas del adaptador en `backend/tests/unit/test_ollama_failures.py` con `respx`: conexión rechazada → `LLMUnavailableError` tras exactamente 1 reintento con backoff de 0,5 s; sin reintento si ya se recibió algún fragmento; exceder `TIMEOUT_FIRST_CHUNK_S`, `TIMEOUT_IDLE_S` o `TIMEOUT_TOTAL_S` → `LLMTimeoutError`; NDJSON malformado o respuesta HTTP de error de Ollama → `LLMInvalidResponseError`
- [X] T050 [P] [US3] Pruebas de integración en `backend/tests/integration/test_llm_failures.py`: en modo JSON, LLM caído → `503 LLM_UNAVAILABLE`, timeout → `504 LLM_TIMEOUT`, respuesta vacía → `502 LLM_INVALID_RESPONSE`, todos con `correlation_id` y mensaje en español; el mensaje `user` queda guardado y el `assistant` se guarda con `status = error` y `error_code`; en modo SSE un fallo tras `message.start` emite evento `error` y cierra el stream; el lock se libera en todos los casos; `health` → 503 `degraded` con LLM caído
- [X] T051 [P] [US3] Prueba de contrato en `backend/tests/contract/test_retry_contract.py`: `POST .../messages/retry` regenera la respuesta al último `user` tras un error (sin duplicar el mensaje `user`), funciona en JSON y SSE, y devuelve `422 NOTHING_TO_RETRY` si el último mensaje visible es un `assistant` `complete` o `incomplete`; agregar `retryLastMessage` a `IMPLEMENTED_OPERATIONS` en `backend/tests/contract/test_openapi_contract.py`
- [X] T052 [P] [US3] Pruebas frontend en `frontend/tests/widget.test.js`: ante `LLM_UNAVAILABLE`, `LLM_TIMEOUT`, `LLM_INVALID_RESPONSE`, error de red o corte del stream se muestra un aviso en español con botón "Reintentar" que llama a `retry`; se emite `ia-chat:error` con `{code, message, correlationId}`; ante `409 GENERATION_IN_PROGRESS` (otra pestaña generando) se muestra el aviso correspondiente y el envío vuelve a habilitarse; el chat nunca queda bloqueado

### Implementation for User Story 3

- [X] T053 [US3] Agregar a `OllamaClient` en `backend/src/ia_gateway/llm/ollama.py` los timeouts por fase (`httpx.Timeout(connect=TIMEOUT_CONNECT_S)`, espera del primer fragmento, inactividad entre fragmentos y total con `asyncio.timeout`), un único reintento con backoff de 0,5 s solo si falla la conexión antes de recibir fragmentos, y la conversión de errores a `LLMUnavailableError`/`LLMTimeoutError`/`LLMInvalidResponseError`
- [X] T054 [US3] Agregar al `ChatOrchestrator` en `backend/src/ia_gateway/chat/orchestrator.py`: captura de errores del LLM → guardar `assistant` con `status = error`, `content` vacío y `error_code`; emitir evento interno `error`; liberar lock; log con código y `correlation_id`; método `retry(conversation_id)` que regenera la respuesta al último `user` si el último mensaje visible es `user` o `assistant` `error`, si no `ApiError(NOTHING_TO_RETRY)`
- [X] T055 [US3] En `backend/src/ia_gateway/api/conversations.py`: mapear errores del LLM a `ApiError` (`LLM_UNAVAILABLE` 503, `LLM_TIMEOUT` 504, `LLM_INVALID_RESPONSE` 502) en modo JSON; en modo SSE emitir `event: error` con `{error, assistant_message}` y cerrar; agregar `POST /conversations/{id}/messages/retry` con ambos modos (depends on T054)
- [X] T056 [US3] Agregar `retryLastMessage(id)` y su variante stream a `frontend/widget/api-client.js`, y en `frontend/widget/ia-chat-widget.js` el aviso de error en el historial con mensaje en español por código (para `GENERATION_IN_PROGRESS`: "Ya hay una respuesta en curso en esta conversación (quizás en otra pestaña). Esperá a que termine."), botón "Reintentar", aviso de respuesta incompleta ante corte de conexión, y evento `ia-chat:error`

**Checkpoint**: User Stories 1, 2 y 3 funcionan de forma independiente

---

## Phase 6: User Story 4 - Base preparada para incorporar herramientas (Priority: P3)

**Goal**: registro de herramientas con esquemas, ejecución controlada desde el orquestador y herramienta de prueba `current_time`, sin cambios en el contrato con el frontend.

**Independent Test**: quickstart.md escenarios 12–13; `uv run pytest tests/unit/test_tool_registry.py tests/integration/test_tools_flow.py` pasa y `tests/contract` sigue pasando sin cambios.

### Tests for User Story 4 ⚠️

- [X] T057 [P] [US4] Pruebas unitarias en `backend/tests/unit/test_tool_registry.py`: el nombre debe cumplir `^[a-z][a-z0-9_]{0,63}$` y ser único; `description` de 1–1024 caracteres; `to_tool_specs()` genera JSON Schema desde el modelo de entrada; argumentos inválidos → invocación `rejected`; salida que no cumple el modelo de salida → `error`; exceder `timeout_s` (por defecto 10 s) → `error`; solo se registran las herramientas de `TOOLS_ENABLED`
- [X] T058 [P] [US4] Pruebas de integración en `backend/tests/integration/test_tools_flow.py` con `FakeLLMClient`: con registro vacío no se envía `tools` al LLM; con `current_time` registrada, el LLM pide la herramienta, el backend la ejecuta, guarda `ToolInvocation` (`ok`) y mensajes internos `assistant(tool_calls)` y `tool`, y el cliente recibe solo la respuesta final por el mismo contrato (JSON y SSE); herramienta no registrada → invocación `rejected`, se devuelve error al modelo y la conversación continúa; se corta tras `MAX_TOOL_ROUNDS` (5); `GET` de la conversación no muestra mensajes `tool`

### Implementation for User Story 4

- [X] T059 [P] [US4] Implementar `Tool` y `ToolRegistry` en `backend/src/ia_gateway/tools/registry.py`: `Tool(name, description, input_model, output_model, handler, timeout_s=10)` con validación de nombre `^[a-z][a-z0-9_]{0,63}$` y descripción de 1–1024 caracteres; `register`, `get`, `to_tool_specs()`; `execute(name, arguments) -> ToolResult` que valida argumentos con `input_model`, aplica `timeout_s`, valida la salida con `output_model` y devuelve estado `ok|error|rejected` con duración; `build_registry(settings)` registra solo las de `TOOLS_ENABLED`
- [X] T060 [P] [US4] Implementar la herramienta de prueba en `backend/src/ia_gateway/tools/current_time.py`: `current_time` sin parámetros que devuelve `{iso, timezone}` con la fecha/hora del servidor
- [X] T061 [US4] Agregar al `OllamaClient` en `backend/src/ia_gateway/llm/ollama.py` el envío de `tools` (formato `{"type": "function", "function": {name, description, parameters}}`) solo si la lista no está vacía, el parseo de `message.tool_calls` a `LLMChunk.tool_calls` y el envío de mensajes `tool` con `tool_name`; ampliar `backend/tests/unit/test_ollama_client.py` con estos casos
- [X] T062 [US4] Agregar el bucle de herramientas al `ChatOrchestrator` en `backend/src/ia_gateway/chat/orchestrator.py`: si el LLM devuelve `tool_calls`, guardar `assistant` con `tool_calls`, ejecutar cada llamada vía `ToolRegistry.execute`, guardar `ToolInvocationRecord` y mensaje `tool` con el resultado (o error para `rejected`), volver a consultar al LLM; máximo `MAX_TOOL_ROUNDS`; no emitir `delta` durante la ejecución; registrar herramientas invocadas en el log (depends on T059, T061)
- [X] T063 [US4] Conectar `build_registry(settings)` en `backend/src/ia_gateway/main.py` y pasarlo al orquestador (inyectable desde `create_app` para pruebas)

**Checkpoint**: todas las historias funcionan de forma independiente

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [X] T064 [P] Prueba de punta a punta opcional contra Ollama real en `backend/tests/integration/test_ollama_live.py` marcada `@pytest.mark.ollama` (health, mensaje JSON y stream SSE con el modelo configurado); medición de SC-002: tras 1 consulta de calentamiento, enviar 10 mensajes por SSE, medir el tiempo hasta el primer `delta`, imprimir los tiempos y verificar que el percentil 90 sea < 3 s
- [X] T065 [P] Prueba de concurrencia en `backend/tests/integration/test_concurrency.py`: 5 conversaciones simultáneas con `FakeLLMClient` con latencia completan sin errores (SC-006)
- [X] T066 [P] Prueba de logs en `backend/tests/integration/test_logging.py`: los registros son JSON con `correlation_id`, latencias y tokens; no contienen texto de mensajes con `DIAGNOSTIC_MODE=false`; sí lo contienen y se emite advertencia al iniciar con `DIAGNOSTIC_MODE=true` (FR-021/022)
- [X] T067 [P] Crear `README.md` en la raíz con descripción, requisitos, puesta en marcha y comandos de prueba tomados de `specs/001-chatbot-ollama-gateway/quickstart.md`, y la nota de la excepción de autenticación (solo red local)
- [X] T068 [P] Actualizar `CLAUDE.md` con los comandos reales de build, ejecución y pruebas (`uv sync`, `uv run uvicorn ia_gateway.main:app`, `uv run pytest`, prueba individual, `uv run ruff check .`, `npx vitest run`) y la estructura `backend/` + `frontend/widget/`
- [X] T069 Ejecutar `uv run ruff check .` y `uv run pytest` en `backend/` y `npx vitest run` en `frontend/`; corregir hasta que todo pase
- [ ] T070 Ejecutar los escenarios manuales 1–17 de `specs/001-chatbot-ollama-gateway/quickstart.md` contra Ollama local y registrar resultados, incluido el puntaje del escenario 17 (SC-004: ≥ 9/10 respuestas coherentes)
- [X] T071 Completar `IMPLEMENTED_OPERATIONS` en `backend/tests/contract/test_openapi_contract.py` con todas las operaciones de `contracts/openapi.yaml` y agregar una aserción que falle si alguna operación documentada no está implementada

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias
- **Foundational (Phase 2)**: depende de Setup; BLOQUEA todas las historias
- **US1 (Phase 3)**: depende de Foundational
- **US2 (Phase 4)** y **US3 (Phase 5)**: dependen de US1 (extienden `orchestrator.py`, `conversations.py`, `ollama.py` y el componente); entre sí son independientes, pero tocan los mismos archivos, así que conviene hacerlas en secuencia
- **US4 (Phase 6)**: depende de US1; independiente de US2/US3
- **Polish (Phase 7)**: depende de las historias que se quieran entregar

### User Story Dependencies

- **US1 (P1)**: solo Foundational
- **US2 (P2)**: US1
- **US3 (P2)**: US1 (si US2 ya está hecha, T055 también cubre el evento `error` en SSE; si no, esa parte se agrega al completar US2)
- **US4 (P3)**: US1

### Within Each User Story

- Las pruebas se escriben primero y deben FALLAR antes de implementar
- `context`/`validation`/`locks`/adaptador → orquestador → endpoints → wiring en `main.py`
- Frontend: `markdown.js`/`api-client.js`/`styles.js` → `ia-chat-widget.js` → `index.html`

### Parallel Opportunities

- Setup: T004, T005
- Foundational: T006–T010 (interfaces y pruebas) en paralelo; luego T012–T015 en paralelo
- US1: todas las pruebas T020–T027 en paralelo; T028–T031 y T036–T038 en paralelo (backend y frontend son independientes hasta la integración manual)
- US2: T041–T043 en paralelo; T044 en paralelo con T047
- US3: T049–T052 en paralelo
- US4: T057, T058, T059, T060 en paralelo
- Polish: T064–T068 en paralelo; T071 después de todas las historias

---

## Parallel Example: User Story 1

```text
# Pruebas de US1 en paralelo:
Task: "Pruebas de contrato en backend/tests/contract/test_conversations_contract.py"
Task: "Pruebas unitarias del contexto en backend/tests/unit/test_context.py"
Task: "Pruebas del adaptador en backend/tests/unit/test_ollama_client.py"
Task: "Pruebas del componente en frontend/tests/widget.test.js"

# Piezas independientes de US1 en paralelo:
Task: "build_context en backend/src/ia_gateway/chat/context.py"
Task: "OllamaClient en backend/src/ia_gateway/llm/ollama.py"
Task: "Renderer seguro en frontend/widget/markdown.js"
Task: "Cliente API en frontend/widget/api-client.js"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Setup
2. Phase 2: Foundational
3. Phase 3: US1
4. **STOP and VALIDATE**: quickstart escenarios 1–6 y 16
5. Demo del chat funcionando con Ollama

### Incremental Delivery

1. Setup + Foundational → base lista
2. US1 → validar → demo (MVP)
3. US2 → streaming y detener → validar
4. US3 → errores y reintento → validar
5. US4 → herramientas → validar que el contrato no cambió
6. Polish → README, CLAUDE.md, validación completa

---

## Notes

- [P] = archivos distintos, sin dependencias pendientes
- La etiqueta [Story] vincula cada tarea con su historia de spec.md
- Verificar que las pruebas fallen antes de implementar
- Commit después de cada tarea o grupo lógico
- No modificar `contracts/` durante la implementación sin actualizar primero el contrato (principio I)
