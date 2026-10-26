# Contrato del componente `<ia-chat-widget>`

Contrato de integración del componente de chat en cualquier página (FR-001a). Cambios
incompatibles en atributos o eventos requieren nueva versión mayor del componente.

## Inclusión

```html
<script type="module" src="<origen-del-backend>/widget/ia-chat-widget.js"></script>
<ia-chat-widget backend-url="http://localhost:8000"></ia-chat-widget>
```

El origen de la página que lo incluye debe figurar en `IA_GATEWAY_ALLOWED_ORIGINS`.

## Atributos

| Atributo | Obligatorio | Por defecto | Descripción |
|----------|-------------|-------------|-------------|
| `backend-url` | no | `location.origin` | URL base del backend (sin `/api/v1`); omitirlo solo si la página la sirve el mismo backend |
| `title` | no | `Asistente` | Título de la ventana de chat |
| `storage-key` | no | `ia-chat:conversation-id` | Clave de `localStorage` para el id de conversación |
| `max-length` | no | `4000` | Largo máximo del mensaje; debe coincidir con `IA_GATEWAY_MAX_MESSAGE_CHARS` |
| `position` | no | `bottom-right` | `bottom-right` o `bottom-left` |
| `streaming` | no | `true` | `false` usa el modo JSON (sin respuesta incremental) |
| `image-upload` | no | `true` | `false` oculta el botón de adjuntar imagen (v1.1, feature 002) |
| `max-image-bytes` | no | `5242880` | Tamaño máximo de la imagen; debe coincidir con `IA_GATEWAY_OCR_MAX_IMAGE_BYTES` |

## Eventos DOM emitidos (`CustomEvent`, `bubbles: true`, `composed: true`)

| Evento | `detail` | Cuándo |
|--------|----------|--------|
| `ia-chat:open` | `{}` | Se abre la ventana |
| `ia-chat:close` | `{}` | Se minimiza/cierra |
| `ia-chat:error` | `{code, message, correlationId}` | Se muestra un error al usuario |

## Comportamiento garantizado

- Shadow DOM: los estilos de la página no afectan al componente ni viceversa. Personalizable vía
  propiedades CSS `--ia-chat-accent`, `--ia-chat-font`, `--ia-chat-z-index`.
- Apariencia: tema oscuro propio (azul noche con acento celeste), independiente del tema de la
  página. Los botones de encabezado, enviar y detener son íconos con `aria-label` ("Nueva
  conversación", "Cerrar chat", "Enviar", "Detener"). Usa la fuente Inter si la página la carga.
- Teclado: el botón flotante es enfocable; `Enter` envía, `Shift+Enter` inserta salto de línea,
  `Escape` cierra la ventana y devuelve el foco al botón.
- Accesibilidad: la ventana tiene `role="dialog"` con etiqueta; el historial usa
  `aria-live="polite"`.
- El contenido del asistente se representa con nodos DOM creados vía `textContent` (párrafos,
  listas, bloques y código en línea); nunca se interpreta como HTML.
- En pantallas de menos de 480 px de ancho la ventana ocupa toda la pantalla y mantiene visible
  el botón de cerrar.
- Al cargar, si hay un id guardado, recupera el historial (`GET`); si la respuesta es `404`,
  descarta el id y crea una conversación nueva al enviar el primer mensaje.
- "Nueva conversación": si hay una respuesta generándose, primero la aborta; luego `DELETE` de la
  actual (reintenta hasta 3 veces con 300 ms de espera ante `409`), borra el id guardado y limpia
  el historial.
- Ante `409 GENERATION_IN_PROGRESS` al enviar (p. ej. otra pestaña está generando), muestra un
  aviso y vuelve a habilitar el envío.

## Imágenes (v1.1, feature 002)

- Botón "Adjuntar imagen" (`data-role="attach"`, `aria-label="Adjuntar imagen"`) que abre un
  selector de archivos limitado a PNG, JPEG y WebP. Una imagen por mensaje; elegir otra reemplaza
  la anterior.
- Antes de leer el archivo valida tipo y tamaño (`max-image-bytes`); si no cumple, muestra un
  aviso con los formatos y el tamaño permitidos y no adjunta nada.
- Vista previa (`data-role="attachment-preview"`) con el nombre y botón "Quitar imagen"
  (`data-role="attachment-remove"`), accesible por teclado. La vista previa usa una URL `blob:`
  local; nunca `innerHTML`.
- Con imagen adjunta, el envío se habilita aunque el texto esté vacío. Mientras el backend lee
  la imagen, el estado muestra "Leyendo la imagen…".
- En el historial, el mensaje del usuario con imagen muestra la miniatura (solo en la sesión en
  que se adjuntó) o "📎 nombre" al recuperar el historial, y un desplegable "Ver texto
  reconocido" con el texto vía `textContent` (e indica si fue recortado).
- Avisos por código: `IMAGE_INVALID`, `IMAGE_TOO_LARGE`, `IMAGE_NO_TEXT` (sin Reintentar: el
  backend no guardó el mensaje, así que el componente quita la burbuja provisional y devuelve el
  texto y la imagen al campo de escritura para que el usuario los cambie), `OCR_UNAVAILABLE` y
  `OCR_TIMEOUT` (con Reintentar, que reenvía el mensaje completo con la imagen).
