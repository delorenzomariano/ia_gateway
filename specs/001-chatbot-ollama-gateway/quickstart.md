# Quickstart: validar el chatbot de punta a punta

Guía para comprobar que la feature funciona. Contratos: [openapi.yaml](contracts/openapi.yaml),
[sse-events.md](contracts/sse-events.md), [chat-widget.md](contracts/chat-widget.md).
Configuración: [data-model.md § Configuración](data-model.md#configuración-no-persistida-variables-de-entorno-con-prefijo-ia_gateway_).

## Requisitos previos

- Python ≥ 3.12 y `uv`; Node ≥ 20 y npm (solo para las pruebas del frontend).
- Ollama corriendo en `http://localhost:11434` con el modelo configurado descargado:
  `ollama pull qwen3:4b` (verificar con `ollama list`).

## Puesta en marcha (PowerShell, desde la raíz del repo)

```powershell
cd backend
uv sync
Copy-Item .env.example .env        # ajustar IA_GATEWAY_* si hace falta
uv run uvicorn ia_gateway.main:app --host 127.0.0.1 --port 8000
```

Abrir `http://localhost:8000/` (página de demo servida por el backend).

## Pruebas automáticas

```powershell
cd backend
uv run pytest                              # suite completa, sin Ollama real
uv run pytest tests/contract               # solo contrato de la API
uv run pytest tests/unit/test_context.py::test_budget_keeps_latest   # una prueba
uv run pytest -m ollama                    # opcional: contra Ollama real
uv run ruff check .

cd ../frontend
npm install
npx vitest run                             # pruebas del componente
npx vitest run tests/markdown.test.js      # un archivo
```

Resultado esperado: todas las pruebas pasan; la suite por defecto no requiere Ollama.

## Escenarios de validación manual

| # | Historia | Pasos | Resultado esperado |
|---|----------|-------|--------------------|
| 1 | US1 | `GET /api/v1/health` | `200`, `status: ok`, `llm.model_available: true` |
| 2 | US1 | En la página: clic en el botón flotante, escribir "Hola, ¿qué podés hacer?" y Enter | Se abre la ventana, aparece el mensaje y un indicador de "respondiendo", luego la respuesta |
| 3 | US1 | Preguntar "¿Cuál es la capital de Francia?" y luego "¿Y cuántos habitantes tiene?" | La segunda respuesta se refiere a París |
| 4 | US1 / FR-013 | Recargar la página y abrir el chat | El historial anterior sigue visible |
| 5 | US1 / FR-013a | Pulsar "Nueva conversación" | Historial vacío; `GET` con el id anterior devuelve `404` |
| 6 | US1 / FR-006 | Usar solo teclado: Tab hasta el botón, Enter, escribir, Enter, Escape | Todo funciona; Escape devuelve el foco al botón |
| 7 | US2 | Pedir "Explicá en detalle qué es una API REST" | El texto aparece de forma progresiva; primer fragmento en < 3 s con el modelo ya cargado |
| 8 | US2 | Durante la respuesta, pulsar "Detener" | Se corta; queda el texto parcial marcado como incompleto; tras recargar sigue igual |
| 9 | US3 | Cerrar Ollama (`ollama` desde la bandeja → Quit) y enviar un mensaje | Aviso "el asistente no está disponible" con botón Reintentar; `health` responde `503` |
| 10 | US3 | Volver a iniciar Ollama y pulsar Reintentar | Llega la respuesta; la pregunta no aparece duplicada |
| 11 | US3 | Configurar `IA_GATEWAY_TIMEOUT_FIRST_CHUNK_S=0.5`, reiniciar y enviar | Aviso de demora con Reintentar (`LLM_TIMEOUT`) |
| 12 | US4 | Con `IA_GATEWAY_TOOLS_ENABLED=` (vacío) conversar normalmente | Funciona igual que en 2–3 |
| 13 | US4 | Con `IA_GATEWAY_TOOLS_ENABLED=current_time`, reiniciar y preguntar "¿Qué hora es en el servidor?" | Respuesta con la hora del servidor; en el log aparece la herramienta invocada; el frontend no cambió |
| 14 | FR-011 | Llamar a la API desde un origen no listado (p. ej. página servida en otro puerto) | El navegador bloquea por CORS; desde una IP fuera de las redes permitidas → `403 ACCESS_DENIED` |
| 15 | FR-021/022 | Revisar logs tras los escenarios anteriores | JSON con `correlation_id`, latencias y tokens; sin texto de mensajes. Con `IA_GATEWAY_DIAGNOSTIC_MODE=true` aparece una advertencia al iniciar y el texto en los logs |
| 16 | Edge | Reiniciar el backend y recargar la página | La conversación sigue disponible |
| 17 | SC-004 | En una conversación nueva, seguir el guion de abajo (10 preguntas encadenadas) | Al menos 9 de 10 respuestas coherentes con el contexto previo |

### Guion del escenario 17 (coherencia de contexto)

| # | Pregunta | Respuesta coherente si… |
|---|----------|-------------------------|
| 1 | Me llamo Lucía y vivo en Rosario. ¿Qué río pasa por mi ciudad? | Menciona el Paraná |
| 2 | ¿Cómo me llamo? | Responde Lucía |
| 3 | ¿Qué puente importante cruza ese río cerca de mi ciudad? | Habla de un puente sobre el Paraná en la zona de Rosario (p. ej. Rosario–Victoria) |
| 4 | ¿A qué ciudad conecta ese puente? | Victoria (Entre Ríos) o la ciudad que haya mencionado en 3 |
| 5 | ¿En qué provincia está esa ciudad? | Entre Ríos (o la provincia correcta de la ciudad mencionada) |
| 6 | Recomendame una comida típica de mi provincia. | Comida asociada a Santa Fe (provincia de Rosario), no a la del punto 5 |
| 7 | ¿Con qué bebida la acompañarías? | Se refiere a la comida recomendada en 6 |
| 8 | Resumí en una frase lo que hablamos. | Menciona a Lucía/Rosario y al menos dos temas anteriores |
| 9 | ¿Cuál fue la primera pregunta que te hice? | Se refiere al río de su ciudad |
| 10 | Si me mudara a la ciudad del otro lado del puente, ¿en qué provincia viviría? | Entre Ríos (coherente con 4–5) |

## Prueba rápida de la API sin navegador

```powershell
$c = Invoke-RestMethod -Method Post http://localhost:8000/api/v1/conversations
Invoke-RestMethod -Method Post "http://localhost:8000/api/v1/conversations/$($c.id)/messages" `
  -ContentType 'application/json' -Body '{"content":"Hola"}'
curl.exe -N -X POST -H "Accept: text/event-stream" -H "Content-Type: application/json" `
  -d '{\"content\":\"Contame un chiste\"}' "http://localhost:8000/api/v1/conversations/$($c.id)/messages"
```

Esperado: la primera llamada devuelve `user_message` y `assistant_message`; la segunda imprime
eventos `message.start`, `delta`… y `message.end`.
