# Data Model: Adjuntar imágenes al chat con extracción de texto

**Feature**: `002-chat-image-ocr` | **Date**: 2026-10-25

Amplía el modelo de la feature 001 (`specs/001-chatbot-ollama-gateway/data-model.md`); lo no
mencionado aquí no cambia.

## Message (cambios)

| Campo | Cambio |
|-------|--------|
| `content` | `user`: recortado, **0**–`max_message_chars` caracteres. Puede quedar vacío **solo** si el mensaje tiene un adjunto; sin adjunto sigue siendo 1–`max_message_chars`. |
| `attachment` | **nuevo** (relación 0..1 con `Attachment`). Solo en mensajes `user`. Se expone en la API como objeto o `null`. |

**Contexto enviado al modelo**: un mensaje `user` con adjunto se convierte en un único mensaje
para el modelo con la pregunta (o un texto por defecto si está vacía) seguida del bloque
delimitado con el texto reconocido (ver research.md R6). Su tamaño para el presupuesto de
contexto es `len(content) + len(attachment.text)`. El mensaje de sistema incluye la instrucción
fija sobre el texto de imágenes **solo** si alguno de los mensajes seleccionados tiene adjunto.

**Reintento**: `retry` regenera la respuesta al último mensaje `user`, con su adjunto ya
guardado; la imagen no se vuelve a procesar (FR-015).

## Attachment (nuevo)

Representa la imagen adjunta a un mensaje del usuario. **No** contiene la imagen: los bytes se
descartan al terminar el reconocimiento (FR-014).

| Campo | Tipo | Reglas |
|-------|------|--------|
| `message_id` | UUID | PK y FK → Message (`role = user`), `ON DELETE CASCADE` |
| `filename` | text | nombre original saneado: sin ruta (solo la parte final tras `/` o `\`), sin caracteres de control, 1–255 caracteres; si queda vacío → `imagen` |
| `media_type` | enum | `image/png`, `image/jpeg`, `image/webp`; debe coincidir con el formato real detectado |
| `size_bytes` | int | tamaño de la imagen decodificada, 1–`OCR_MAX_IMAGE_BYTES` |
| `width` / `height` | int | dimensiones originales en píxeles; `width × height ≤ OCR_MAX_PIXELS` |
| `text` | text | texto reconocido saneado, 1–`OCR_MAX_TEXT_CHARS` caracteres, con al menos 3 caracteres alfanuméricos |
| `truncated` | bool | `true` si el texto reconocido superaba `OCR_MAX_TEXT_CHARS` y se recortó |
| `ocr_duration_ms` | int | duración del reconocimiento (observabilidad) |
| `created_at` | datetime | igual al del mensaje |

**Ciclo de vida**: se crea en la misma transacción que su mensaje `user`; se borra en cascada
con el mensaje y la conversación (vencimiento de 24 h, `DELETE`). No hay estados: un adjunto
solo existe si el reconocimiento terminó con texto. Los fallos (`IMAGE_INVALID`,
`IMAGE_TOO_LARGE`, `IMAGE_NO_TEXT`, `OCR_UNAVAILABLE`, `OCR_TIMEOUT`) no guardan ni el mensaje
ni el adjunto.

**Esquema SQLite** (se agrega con `CREATE TABLE IF NOT EXISTS`, compatible con bases
existentes):

```text
attachments(
  message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  media_type TEXT NOT NULL CHECK (media_type IN ('image/png','image/jpeg','image/webp')),
  size_bytes INTEGER NOT NULL,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  text TEXT NOT NULL,
  truncated INTEGER NOT NULL CHECK (truncated IN (0, 1)),
  ocr_duration_ms INTEGER NOT NULL,
  created_at TEXT NOT NULL
)
```

## Entrada de imagen (solo en la solicitud, no persistida)

| Campo | Reglas |
|-------|--------|
| `filename` | 1–255 caracteres (se sanea como arriba) |
| `media_type` | `image/png`, `image/jpeg` o `image/webp` |
| `data` | base64 estándar (RFC 4648, sin prefijo `data:`), decodificado 1–`OCR_MAX_IMAGE_BYTES` bytes |

## Resultado de OCR (interno, interfaz `OcrEngine`)

| Campo | Descripción |
|-------|-------------|
| `text` | texto reconstruido con las palabras de confianza ≥ `OCR_MIN_CONFIDENCE`, antes de sanear y recortar |
| `word_count` / `dropped_words` | palabras conservadas / descartadas por baja confianza (logs) |
| `duration_ms` | duración del reconocimiento |

Errores del adaptador: `OcrUnavailableError` (ejecutable o idiomas ausentes), `OcrTimeoutError`,
`OcrFailedError` (cualquier otra falla de Tesseract → se informa como `OCR_UNAVAILABLE`).

## Configuración (nuevas claves, prefijo `IA_GATEWAY_`)

Ver la tabla de research.md R10 (`OCR_ENABLED`, `OCR_TESSERACT_CMD`, `OCR_LANGUAGES`,
`OCR_MAX_IMAGE_BYTES`, `OCR_MAX_PIXELS`, `OCR_MAX_TEXT_CHARS`, `OCR_MIN_CONFIDENCE`,
`OCR_TIMEOUT_S`, `OCR_MAX_CONCURRENCY`).
