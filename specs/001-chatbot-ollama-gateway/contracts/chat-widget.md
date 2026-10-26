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
