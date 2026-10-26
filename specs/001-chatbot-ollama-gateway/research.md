# Research: Chatbot flotante con backend conectado a LLM local

**Feature**: `001-chatbot-ollama-gateway` | **Date**: 2026-10-24

Entorno relevado en la máquina de desarrollo: Python 3.14.3, uv 0.12.3, Node 24.14 / npm 11.9,
Git 2.56, Ollama 0.40.11 corriendo en `http://localhost:11434` con los modelos `qwen3:4b`
(4B, capacidades `completion`, `tools`, `thinking`) y `qwen3.6:latest` (36B MoE, además `vision`).

## R1. Lenguaje y framework del backend

- **Decision**: Python ≥ 3.12 (desarrollo en 3.14) con FastAPI + Uvicorn, gestionado con `uv`.
- **Rationale**: soporte async nativo para streaming y llamadas concurrentes a Ollama; validación
  de entrada/salida con Pydantic (principio III); generación automática de OpenAPI, que permite
  verificar el contrato publicado contra `contracts/openapi.yaml` (principios I y V). Python y uv
  ya están instalados.
- **Alternatives considered**: Node + Fastify/Hono (buen streaming, pero duplicaría el ecosistema
  de validación y el taller ya usa Python); Flask (sin async ni OpenAPI nativo).

## R2. Cliente para Ollama

- **Decision**: llamar a la API REST de Ollama (`POST /api/chat`, `GET /api/tags`) con `httpx`
  (AsyncClient), encapsulado en un adaptador `OllamaClient` que implementa la interfaz interna
  `LLMClient`.
- **Rationale**: control explícito de timeouts por fase (conexión, primer token, inactividad entre
  fragmentos) y de cancelación; mockeable con `respx` sin servidor real (principio V). La
  librería `ollama` para Python es una capa delgada sobre httpx y oculta parte de ese control.
- **Alternatives considered**: librería oficial `ollama` (menos control de timeouts); endpoint
  compatible con OpenAI de Ollama (`/v1/chat/completions`) — se descarta para no depender de un
  modo de compatibilidad, aunque el diseño por adaptador permitiría cambiarlo.

## R3. Modelo por defecto y "thinking"

- **Decision**: modelo por defecto `qwen3:4b`, configurable (`IA_GATEWAY_OLLAMA_MODEL`). Por
  defecto **no** se envía el campo `think` (configurable con `IA_GATEWAY_OLLAMA_THINK`); el campo
  `thinking` devuelto se descarta (no se muestra ni se guarda) y el adaptador elimina además un
  bloque `<think>…</think>` al inicio del contenido.
- **Medición (2026-10-24, Ollama 0.40.11)**: con `think: false`, `qwen3:4b` igual razona, mezcla
  el razonamiento en `content` (terminado en `</think>`) y tardó 36–46 s; omitiendo `think` o con
  `think: true` el razonamiento llega separado en `thinking` y la respuesta completa tardó ~5 s.
  Por eso se descartó la decisión inicial de enviar `think: false`.
- **Rationale**: el modelo de 4B cumple más fácilmente SC-002 (primer fragmento < 3 s) en hardware
  local y soporta `tools`, necesario para FR-017/018. El razonamiento interno aumenta la latencia y
  no es parte de la respuesta.
- **Alternatives considered**: `qwen3.6` (mejor calidad, pero 24 GB y mayor latencia; queda
  disponible por configuración).

## R4. Streaming hacia el frontend y cancelación

- **Decision**: `POST /api/v1/conversations/{id}/messages` devuelve `text/event-stream` (SSE)
  cuando el cliente envía `Accept: text/event-stream`, y JSON completo con `Accept:
  application/json`. El frontend consume el stream con `fetch` + `ReadableStream` (EventSource
  no admite POST). Cancelar = abortar la petición (`AbortController`); el backend detecta la
  desconexión, cancela la llamada a Ollama y guarda el mensaje como `incomplete`.
- **Rationale**: SSE es texto, unidireccional y lo permite la constitución ("eventos de streaming
  documentados, p. ej. SSE"). El modo JSON permite entregar la historia P1 sin depender de la P2.
  Cancelar por desconexión evita un endpoint extra y cubre también la pérdida de conexión.
- **Alternatives considered**: WebSocket (bidireccional innecesario, más complejidad); endpoint
  explícito de cancelación (redundante con la desconexión en una red local sin proxies).

## R5. Almacenamiento de conversaciones

- **Decision**: SQLite (módulo estándar `sqlite3`, archivo `backend/data/ia_gateway.db`), accedido
  mediante una interfaz `ConversationRepository`; las operaciones bloqueantes se ejecutan en un
  thread pool. Limpieza de vencidas al iniciar y cada 10 min (configurable); además toda lectura
  trata como inexistente una conversación vencida.
- **Rationale**: la spec exige que las conversaciones sobrevivan a un reinicio del backend y se
  borren a las 24 h; SQLite no requiere servidor y no agrega dependencias.
- **Alternatives considered**: memoria (no sobrevive reinicios); archivos JSON (concurrencia
  frágil); PostgreSQL/Redis (servicio extra injustificado para carga baja, principio VII).

## R6. Identidad de la conversación en el navegador

- **Decision**: el backend genera un UUIDv4 al crear la conversación; el componente lo guarda en
  `localStorage` (clave configurable, por defecto `ia-chat:conversation-id`). Todas las pestañas
  del mismo origen comparten la conversación.
- **Rationale**: cumple FR-013/013b sin usuarios identificados; un UUIDv4 no es adivinable en la
  práctica dentro de la red local.
- **Alternatives considered**: cookie de sesión (requiere configurar SameSite/credenciales en
  CORS si frontend y backend están en orígenes distintos); `sessionStorage` (no compartido entre
  pestañas ni persistente).

## R7. Restricción de acceso sin autenticación (excepción documentada)

- **Decision**: dos controles configurables: (1) CORS con lista de orígenes permitidos (por
  defecto `http://localhost:8000`, `http://127.0.0.1:8000`); (2) middleware de lista de redes
  permitidas por IP de cliente (por defecto `127.0.0.0/8`, `::1/128`, `10.0.0.0/8`,
  `172.16.0.0/12`, `192.168.0.0/16`), que responde `403 ACCESS_DENIED`. Las rutas se agrupan bajo
  un `APIRouter` con una dependencia de acceso, punto único donde se agregará autenticación.
- **Rationale**: FR-011 exige limitar a la red local y permitir agregar autenticación sin
  rediseño.
- **Alternatives considered**: clave compartida estática (se expondría en el frontend, no aporta
  seguridad real); sin restricción (viola FR-011).

## R8. Registro y ejecución de herramientas

- **Decision**: `ToolRegistry` en memoria. Cada herramienta declara `name`, `description`, modelo
  Pydantic de entrada y de salida, `timeout_s` y un handler async. El orquestador envía al modelo
  la lista de herramientas (formato `tools` de Ollama, esquema JSON generado desde Pydantic),
  ejecuta solo las registradas, valida argumentos y resultados, y repite hasta que el modelo
  produce texto final o se alcanza `max_tool_rounds` (por defecto 5). Herramientas habilitadas por
  configuración (`IA_GATEWAY_TOOLS_ENABLED`, vacía por defecto). Se incluye una herramienta de
  prueba `current_time` (devuelve fecha/hora del servidor) para validar el flujo.
- **Rationale**: FR-017/018/019; el contrato con el frontend no cambia porque las herramientas se
  resuelven íntegramente en el backend.
- **Alternatives considered**: plugins cargados dinámicamente (complejidad prematura); MCP
  (posible evolución futura detrás del mismo registro).

## R9. Timeouts, reintentos y errores

- **Decision**: timeouts configurables: conexión 5 s, primer fragmento 60 s (incluye carga del
  modelo), inactividad entre fragmentos 30 s, total 180 s. Un único reintento con backoff de
  0,5 s solo si falla la conexión antes de recibir cualquier fragmento (la operación aún no tuvo
  efectos). Mapeo: no se puede conectar → `503 LLM_UNAVAILABLE`; timeout → `504 LLM_TIMEOUT`;
  respuesta vacía/malformada → `502 LLM_INVALID_RESPONSE`. En modo SSE, los errores posteriores al
  inicio del stream se emiten como evento `error`.
- **Rationale**: principio IV y SC-003.

## R10. Contexto enviado al modelo

- **Decision**: mensaje de sistema configurable + los mensajes más recientes de la conversación
  (estado `complete` o `incomplete`; se excluyen los `error`) hasta un presupuesto de caracteres
  configurable (por defecto 24.000) y siempre incluyendo el mensaje actual. `num_ctx` de Ollama
  configurable (por defecto 8192).
- **Rationale**: caso borde "la conversación crece más allá de lo que el modelo puede
  considerar"; contar caracteres evita depender de un tokenizador.

## R11. Observabilidad

- **Decision**: logging estándar de Python con un formateador JSON propio; `correlation_id` en
  un `contextvar`, tomado del header `X-Correlation-ID` si es válido o generado, devuelto en la
  respuesta e incluido en todo log, en el cuerpo de error y propagado a Ollama como header.
  Campos por solicitud: método, ruta, estado, duración, latencia del modelo (primer fragmento y
  total), tokens (`prompt_eval_count`, `eval_count`), herramientas invocadas. Texto de mensajes
  solo con `IA_GATEWAY_DIAGNOSTIC_MODE=true`, con advertencia al iniciar (FR-022).
  `GET /api/v1/health` informa estado del backend, de la base y de Ollama (incluido si el modelo
  configurado está descargado).
- **Alternatives considered**: structlog / OpenTelemetry (dependencias extra; se puede migrar
  más adelante sin cambiar contratos).

## R12. Frontend

- **Decision**: Web Component `<ia-chat-widget>` en JavaScript (ES modules, sin framework ni build),
  con Shadow DOM para aislar estilos. Atributos: `backend-url` (obligatorio), `title`,
  `storage-key`, `max-length`. La página `frontend/index.html` lo incluye con un `<script
  type="module">`. Renderizado de respuestas con un mini-renderer propio (párrafos, listas,
  bloques y código en línea) que crea nodos DOM con `textContent`, nunca `innerHTML` (FR-015).
  El backend sirve `frontend/` como archivos estáticos en `/` (configurable) para que la demo sea
  del mismo origen.
- **Rationale**: FR-001a (incorporarlo en otra página = incluir el script y poner la etiqueta con
  `backend-url`); principio VII (sin toolchain de build).
- **Alternatives considered**: React/Vue (requiere build e integración más pesada en terceros);
  iframe (aislamiento total, pero complica tamaño y accesibilidad).

## R13. Pruebas

- **Decision**: backend con `pytest` + `pytest-asyncio`, `httpx.AsyncClient`/`ASGITransport`
  para la API y `respx` para simular Ollama; un `FakeLLMClient` para pruebas de orquestación.
  Pruebas de contrato que comparan el OpenAPI generado por FastAPI con
  `contracts/openapi.yaml` (rutas, métodos, códigos y esquemas) y validan respuestas reales
  contra los esquemas. Frontend con `vitest` + `happy-dom`. Prueba opcional contra Ollama real
  marcada `@pytest.mark.ollama`, excluida por defecto. Lint con `ruff`.
- **Rationale**: principio V (la suite principal no depende de servicios reales).
