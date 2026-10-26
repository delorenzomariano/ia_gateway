# Implementation Plan: Chatbot flotante con backend conectado a LLM local

**Branch**: `001-chatbot-ollama-gateway` | **Date**: 2026-10-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-chatbot-ollama-gateway/spec.md`

## Summary

Página web mínima con un componente de chat flotante reutilizable (`<ia-chat-widget>`, Web
Component sin framework) que habla exclusivamente con un backend FastAPI mediante una API REST
versionada (`/api/v1`) con respuesta JSON o streaming SSE. El backend guarda las conversaciones en
SQLite (retención de 24 h, sobreviven reinicios), arma el contexto, consulta a Ollama
(`qwen3:4b` por defecto) a través de un adaptador con timeouts y cancelación, y expone un
registro de herramientas (vacío por defecto, con una herramienta de prueba `current_time`) que el
orquestador ofrece al modelo sin cambiar el contrato con el frontend. Acceso sin autenticación
limitado a la red local (excepción documentada abajo). Detalle de decisiones en
[research.md](research.md).

## Technical Context

**Language/Version**: Backend Python ≥ 3.12 (desarrollo en 3.14); frontend JavaScript ES2022
(módulos nativos, sin build)

**Primary Dependencies**: FastAPI, Uvicorn, httpx, pydantic-settings. Dev: pytest,
pytest-asyncio, respx, ruff; frontend dev: vitest, happy-dom

**Storage**: SQLite (`sqlite3` de la librería estándar), archivo `backend/data/ia_gateway.db`

**Testing**: pytest (unit, contract, integration con dobles de Ollama), vitest + happy-dom para
el componente; pruebas contra Ollama real opcionales (`-m ollama`)

**Target Platform**: Servidor local Windows/Linux en la misma red que Ollama; navegadores de
escritorio y móvil actuales

**Project Type**: Aplicación web (backend API + frontend estático)

**Performance Goals**: primer fragmento < 3 s en el 90% de las consultas con el modelo cargado
(SC-002); ≥ 5 conversaciones simultáneas sin errores (SC-006)

**Constraints**: timeouts configurables (conexión 5 s, primer fragmento 60 s, inactividad 30 s,
total 180 s); mensajes ≤ 4000 caracteres; sin texto de mensajes en logs por defecto; acceso solo
desde red local

**Scale/Scope**: uso de taller/equipo reducido (decenas de usuarios), 1 página, 5 endpoints,
1 componente

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Cómo se cumple | Estado |
|-----------|----------------|--------|
| I. API-First con contratos | `contracts/openapi.yaml` + `sse-events.md` definidos antes de implementar; versión en la ruta (`/api/v1`); error uniforme `{error:{code,message,correlation_id}}` | ✅ |
| II. Integraciones aisladas | Interfaz `LLMClient` con adaptador `OllamaClient`; `ToolRegistry` con lista permitida y esquemas Pydantic de entrada/salida; el orquestador no conoce formatos de Ollama | ✅ |
| III. Seguridad y secretos | Config por variables de entorno; validación de entrada con Pydantic; salida del LLM validada y renderizada solo con `textContent`; sin texto en logs por defecto. **Autenticación: excepción** (ver Complexity Tracking) | ⚠️ justificado |
| IV. Resiliencia | Timeouts por fase, un reintento solo antes del primer fragmento, errores `503/504/502` documentados, eventos `error` en SSE, streaming soportado | ✅ |
| V. Pruebas de contrato e integración | Contrato OpenAPI verificado contra la app; `respx`/`FakeLLMClient` en lugar de Ollama; integración para timeout, caída, respuesta malformada, cancelación y herramientas | ✅ |
| VI. Observabilidad | Logs JSON con `correlation_id` propagado a Ollama; latencias, tokens y herramientas; `GET /api/v1/health` con estado de base y modelo | ✅ |
| VII. Simplicidad | Un solo servicio backend; SQLite sin servidor; frontend sin framework ni build; 4 dependencias de runtime | ✅ |
| Restricciones de arquitectura | Topología Frontend ⇄ API ⇄ Backend ⇄ Ollama; JSON + SSE; configuración externa con valores seguros por defecto | ✅ |

**Resultado previo a Phase 0**: PASA con una excepción justificada.
**Re-evaluación tras Phase 1**: PASA. El diseño no agregó servicios ni dependencias; el endpoint
`retry` evita duplicar mensajes sin romper el contrato; el punto de extensión para autenticación
(dependencia común del router `/api/v1`) quedó definido.

## Project Structure

### Documentation (this feature)

```text
specs/001-chatbot-ollama-gateway/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── openapi.yaml       # API REST v1
│   ├── sse-events.md      # eventos de streaming
│   └── chat-widget.md     # contrato de integración del componente
├── checklists/
│   └── requirements.md
└── tasks.md               # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── pyproject.toml
├── .env.example
├── data/                      # SQLite (ignorado por git)
├── src/ia_gateway/
│   ├── main.py                # app factory, lifespan (limpieza periódica), estáticos
│   ├── config.py              # Settings (pydantic-settings, prefijo IA_GATEWAY_)
│   ├── api/
│   │   ├── router.py          # APIRouter /api/v1 + dependencia de acceso (punto para auth)
│   │   ├── conversations.py   # endpoints de conversaciones y mensajes
│   │   ├── health.py
│   │   ├── schemas.py         # modelos Pydantic del contrato
│   │   ├── errors.py          # ApiError, códigos, handlers uniformes
│   │   ├── sse.py             # serialización de eventos
│   │   └── access.py          # middleware de redes permitidas
│   ├── chat/
│   │   ├── orchestrator.py    # mensaje → contexto → LLM → herramientas → respuesta
│   │   ├── context.py         # armado del contexto con presupuesto
│   │   ├── validation.py      # saneamiento de la salida del modelo
│   │   └── locks.py           # una generación por conversación
│   ├── llm/
│   │   ├── base.py            # LLMClient, LLMChunk, ToolCall, errores
│   │   └── ollama.py          # OllamaClient (httpx)
│   ├── tools/
│   │   ├── registry.py        # Tool, ToolRegistry
│   │   └── current_time.py    # herramienta de prueba
│   ├── storage/
│   │   ├── repository.py      # ConversationRepository (interfaz)
│   │   └── sqlite.py          # implementación + esquema
│   └── observability/
│       ├── logging.py         # formateador JSON, modo diagnóstico
│       └── correlation.py     # contextvar + middleware X-Correlation-ID
└── tests/
    ├── conftest.py            # app con dobles, base temporal
    ├── fakes.py               # FakeLLMClient, herramienta de prueba
    ├── contract/              # OpenAPI vs contracts/openapi.yaml, esquemas de respuesta, SSE
    ├── integration/           # flujos completos con respx/fakes
    └── unit/                  # context, validation, registry, repository, ollama adapter

frontend/
├── index.html                 # página de demo
├── package.json               # solo dev: vitest, happy-dom
├── widget/
│   ├── ia-chat-widget.js      # Custom Element (UI, estado, teclado, a11y)
│   ├── api-client.js          # llamadas REST + lectura de SSE + abort
│   ├── markdown.js            # renderer seguro (textContent)
│   └── styles.js              # CSS del Shadow DOM
└── tests/
    ├── api-client.test.js
    ├── markdown.test.js
    └── widget.test.js
```

**Structure Decision**: aplicación web con `backend/` (único servicio, paquete `ia_gateway` en
layout `src/`) y `frontend/` (archivos estáticos). El backend sirve `frontend/` en `/` cuando
`IA_GATEWAY_SERVE_FRONTEND=true`, de modo que la demo es del mismo origen; el componente en
`frontend/widget/` se puede incluir desde cualquier otra página permitida.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Endpoints de chat sin autenticación (principio III) | Decisión de la spec (FR-011, clarificación 2026-10-24): uso interno en red local para esta versión | Una clave compartida quedaría expuesta en el frontend sin aportar seguridad real; un login completo amplía el alcance. Mitigación: CORS + lista de redes permitidas, y dependencia común del router como punto único para agregar autenticación antes de exponer fuera de la red local |
