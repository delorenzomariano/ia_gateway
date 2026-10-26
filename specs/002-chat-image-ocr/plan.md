# Implementation Plan: Adjuntar imágenes al chat con extracción de texto

**Branch**: `002-chat-image-ocr` | **Date**: 2026-10-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-chat-image-ocr/spec.md`

## Summary

El componente `<ia-chat-widget>` agrega un botón para adjuntar **una imagen** (PNG, JPEG o WebP,
hasta 5 MB) por mensaje. La imagen viaja en base64 dentro del mismo `POST .../messages` (API
v1.1.0, cambio compatible). El backend valida el contenido real con **Pillow**, la preprocesa y
reconoce su texto con **Tesseract vía pytesseract** (`spa+eng`) a través de un adaptador
`OcrEngine`, con timeout, concurrencia acotada y filtro por confianza para detectar imágenes sin
texto. La imagen se descarta; se guardan solo metadatos y el texto reconocido (tabla
`attachments`), que se incorpora al contexto del modelo como contenido del usuario delimitado,
nunca como instrucción. Los errores de imagen/OCR son respuestas JSON antes de iniciar la
respuesta, y el estado de salud agrega el chequeo `ocr`. Detalle en [research.md](research.md).

## Technical Context

**Language/Version**: Backend Python ≥ 3.12 (desarrollo en 3.14); frontend JavaScript ES2022
(sin cambios)

**Primary Dependencies**: las de la feature 001 (FastAPI, Uvicorn, httpx, pydantic-settings) +
**pytesseract ≥ 0.3.13** y **Pillow ≥ 11.3** (runtime). Dependencia de sistema: **Tesseract 5**
con datos de idioma `spa` y `eng` (no es un paquete de Python; ver quickstart)

**Storage**: SQLite existente; nueva tabla `attachments` (sin migración destructiva:
`CREATE TABLE IF NOT EXISTS`)

**Testing**: pytest con `FakeOcrEngine` e imágenes generadas con Pillow (suite por defecto sin
Tesseract); pruebas opt-in `-m tesseract` contra Tesseract real; vitest + happy-dom para el
componente

**Target Platform**: mismo servidor local Windows/Linux de la feature 001; navegadores actuales

**Project Type**: Aplicación web (backend API + frontend estático), sin cambios de estructura

**Performance Goals**: reconocimiento < 10 s (p90) para imágenes de hasta 2 MB (SC-002); el
chat de texto mantiene sus tiempos (SC-006)

**Constraints**: imagen ≤ 5 MiB y ≤ 25 MP; texto reconocido ≤ 8000 caracteres; OCR con timeout
de 30 s y como máximo 2 en paralelo (equipo con poca memoria); sin imágenes en disco ni en
logs; sin servicios externos

**Scale/Scope**: mismo uso de taller (decenas de usuarios); 1 endpoint ampliado, 1 tabla, 1
adaptador, 1 componente ampliado

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Cómo se cumple | Estado |
|-----------|----------------|--------|
| I. API-First con contratos | `contracts/openapi.yaml` v1.1.0 (campos nuevos y opcionales: `image`, `attachment`, `checks.ocr`, códigos `IMAGE_*`/`OCR_*`), `sse-events.md` y `chat-widget.md` actualizados antes de implementar; la prueba de contrato pasa a apuntar a `specs/002-chat-image-ocr/contracts/`; el error mantiene el formato uniforme. Cambio compatible: no requiere `/api/v2` | ✅ |
| II. Integraciones aisladas | Interfaz `OcrEngine` + adaptador `TesseractOcrEngine`, único código que conoce pytesseract; el orquestador recibe el texto ya extraído. Reemplazar el motor de OCR solo toca el adaptador | ✅ |
| III. Seguridad y secretos | Validación del contenido real de la imagen (formato, tamaño, píxeles, base64) antes de procesarla; límite del cuerpo antes de leerlo; nombre de archivo saneado; texto reconocido tratado como contenido no confiable y delimitado (anti prompt-injection); nada de imagen ni texto reconocido en logs salvo modo diagnóstico; render en el frontend solo con `textContent` y URLs `blob:`. Autenticación: misma excepción de la feature 001 | ⚠️ justificado (heredado) |
| IV. Resiliencia | Timeout configurable del OCR (pytesseract + `fail_after`), semáforo de concurrencia, errores controlados `503 OCR_UNAVAILABLE` / `504 OCR_TIMEOUT`; sin reintentos automáticos (operación local determinista, el usuario reintenta). El chat de texto no depende del OCR | ✅ |
| V. Pruebas de contrato e integración | Contrato OpenAPI v1.1.0 verificado contra la app; esquemas de `Attachment`/errores en pruebas de contrato; `FakeOcrEngine` en la suite por defecto; integración para imagen válida, inválida, grande, sin texto, OCR caído, timeout, reintento sin reprocesar y límite del cuerpo; pruebas escritas antes de implementar | ✅ |
| VI. Observabilidad | Log `ocr_completed` / `ocr_failed` con `correlation_id`, tipo, tamaño, dimensiones, duración, caracteres y palabras descartadas; `checks.ocr` en `/health` | ✅ |
| VII. Simplicidad | Sin servicios nuevos; un endpoint existente ampliado en lugar de un flujo de subida en dos pasos; sin OpenCV ni modelos de visión. Dos dependencias nuevas justificadas abajo | ⚠️ justificado |
| Restricciones de arquitectura | La imagen llega por la API del backend en JSON; Tesseract corre en el mismo servidor como dependencia local del backend (no hay nuevo camino de comunicación); configuración externa con valores seguros por defecto | ✅ |

**Resultado previo a Phase 0**: PASA con dos justificaciones (autenticación heredada,
dependencias nuevas).

**Re-evaluación tras Phase 1**: PASA. El diseño mantiene un único endpoint de envío, agrega una
tabla sin romper las existentes y no introduce eventos SSE nuevos. Punto de atención para
`/speckit-tasks`: el límite de tamaño del cuerpo debe ser un middleware (FastAPI lee el JSON
completo antes de ejecutar dependencias) y el OCR debe ejecutarse después de verificar la
conversación y el lock, para no gastar CPU en solicitudes que igual fallarían con 404/409.

## Project Structure

### Documentation (this feature)

```text
specs/002-chat-image-ocr/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── openapi.yaml       # API REST v1.1.0 (reemplaza a la de 001 como contrato vigente)
│   ├── sse-events.md      # sin eventos nuevos; aclara errores de OCR previos al stream
│   └── chat-widget.md     # atributos image-upload / max-image-bytes y comportamiento de imágenes
├── checklists/
│   └── requirements.md
└── tasks.md               # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── pyproject.toml                 # + pytesseract, pillow; marcador pytest `tesseract`
├── .env.example                   # + IA_GATEWAY_OCR_*
├── src/ia_gateway/
│   ├── config.py                  # + ocr_* (research R10)
│   ├── main.py                    # crea el OcrEngine, registra BodySizeLimitMiddleware
│   ├── main_deps.py               # Services + image_reader
│   ├── api/
│   │   ├── limits.py              # NUEVO: BodySizeLimitMiddleware (413 antes de leer el cuerpo)
│   │   ├── schemas.py             # + ImageInput, Attachment; content opcional con imagen
│   │   ├── conversations.py       # pre-chequeo conversación/lock → OCR → start_send
│   │   ├── errors.py              # + IMAGE_INVALID, IMAGE_TOO_LARGE, IMAGE_NO_TEXT, OCR_UNAVAILABLE, OCR_TIMEOUT
│   │   └── health.py              # + checks.ocr
│   ├── ocr/                       # NUEVO
│   │   ├── base.py                # OcrEngine, OcrResult, OcrHealth, errores
│   │   └── tesseract.py           # TesseractOcrEngine (pytesseract, image_to_data, confianza, timeout)
│   ├── chat/
│   │   ├── images.py              # NUEVO: decodificar/validar/preprocesar (Pillow) e ImageReader
│   │   │                          #        (semáforo, timeout, saneo y recorte del texto)
│   │   ├── context.py             # compone pregunta + bloque de texto de la imagen; tamaño del adjunto
│   │   └── orchestrator.py        # start_send(..., attachment); instrucción de sistema para imágenes
│   ├── storage/
│   │   ├── repository.py          # + AttachmentRecord / NewAttachment; MessageRecord.attachment
│   │   └── sqlite.py              # + tabla attachments; lectura con JOIN
│   └── observability/logging.py   # sin cambios de estructura (nuevos eventos de log)
└── tests/
    ├── fakes.py                   # + FakeOcrEngine
    ├── images.py                  # NUEVO: generadores de imágenes de prueba con Pillow
    ├── contract/                  # apunta a specs/002-…/contracts; casos de image/attachment/errores
    ├── integration/
    │   ├── test_image_flow.py     # NUEVO: US1–US3 con FakeOcrEngine
    │   ├── test_body_limit.py     # NUEVO: 413 antes de leer el cuerpo
    │   └── test_tesseract_live.py # NUEVO, opt-in `-m tesseract` (SC-002)
    └── unit/
        ├── test_images.py         # NUEVO: validación y preprocesamiento
        ├── test_tesseract_engine.py # NUEVO: adaptador con pytesseract simulado
        ├── test_context.py        # + adjuntos
        └── test_sqlite_repository.py # + attachments

frontend/
├── widget/
│   ├── ia-chat-widget.js          # botón adjuntar, vista previa, chip/desplegable en el historial, errores
│   ├── api-client.js              # sendMessage / sendMessageStream con `image` opcional
│   └── styles.js                  # estilos de adjunto y vista previa
└── tests/
    ├── fake-backend.js            # acepta `image`, simula OCR y errores IMAGE_*/OCR_*
    ├── api-client.test.js         # + imagen
    └── image.test.js              # NUEVO: flujo de imágenes del componente
```

**Structure Decision**: se mantiene la estructura de la feature 001 (`backend/` + `frontend/`).
El OCR es un adaptador nuevo (`ocr/`, como `llm/`); la validación y el preprocesamiento de la
imagen y la coordinación del reconocimiento viven en `chat/images.py`, junto al resto de la
lógica del turno. El contrato vigente pasa a ser `specs/002-chat-image-ocr/contracts/`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Endpoints de chat sin autenticación (principio III) | Heredado de la feature 001 (uso interno en red local) | Igual que en 001; el punto único para agregarla sigue siendo `api/router.py` |
| Dependencia nueva `pytesseract` + binario de sistema Tesseract (principio VII) | Pedido explícito del usuario; OCR local sin servicios externos (FR-005) | EasyOCR/PaddleOCR traen PyTorch/Paddle (GB y mucha memoria); un modelo de visión en Ollama queda fuera de alcance por la clarificación "solo texto" |
| Dependencia nueva `Pillow` (principio VII) | Requerida por pytesseract; además valida el formato real, limita píxeles y preprocesa | Validar solo por extensión/`Content-Type` no detecta archivos falsos (FR-003); `python-magic` sería otra dependencia y no preprocesa |
