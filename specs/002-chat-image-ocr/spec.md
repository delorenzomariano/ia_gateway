# Feature Specification: Adjuntar imágenes al chat con extracción de texto

**Feature Branch**: `002-chat-image-ocr`

**Created**: 2026-10-25

**Status**: Draft

**Input**: User description: "Agregar la opcion de subir una imagen al chat, agregar el paquete  pytesseract"

## Clarifications

### Session 2026-10-25

- Q: ¿Qué debe poder hacer el asistente con la imagen: solo leer el texto o también describir lo que se ve? → A: Solo leer el texto (OCR); la descripción visual queda fuera de alcance.
- Q: ¿El usuario revisa/corrige el texto reconocido antes de enviarlo al asistente? → A: No; envío directo en un solo paso. El texto reconocido se consulta después, desplegándolo en el mensaje enviado, y no es editable.
- Q: ¿Qué se conserva de la imagen tras enviarla? → A: Solo nombre, tipo, tamaño y texto reconocido; la imagen (ni miniatura) no se guarda. La vista previa existe solo durante la sesión del navegador en que se adjuntó.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Preguntar sobre el texto de una imagen (Priority: P1)

Un usuario tiene una imagen que contiene texto (una captura de pantalla, la foto de un documento,
un ticket, un cartel) y quiere que el asistente lo ayude con ese contenido. Desde la ventana de
chat adjunta la imagen, escribe opcionalmente una pregunta ("¿qué dice este error?", "resumí
este documento") y la envía. El sistema reconoce el texto de la imagen y el asistente responde
teniendo en cuenta ese texto y la pregunta del usuario.

**Why this priority**: es el valor central de la feature; sin esto no hay soporte de imágenes.

**Independent Test**: adjuntar una captura que contenga una frase conocida, preguntar "¿qué dice
la imagen?" y verificar que la respuesta del asistente reproduce o resume esa frase.

**Acceptance Scenarios**:

1. **Given** la ventana de chat está abierta, **When** el usuario pulsa el botón de adjuntar y
   elige una imagen válida, **Then** se muestra una vista previa de la imagen junto al campo de
   mensaje, con la opción de quitarla antes de enviar.
2. **Given** hay una imagen adjunta y el usuario escribió una pregunta, **When** envía el
   mensaje, **Then** el mensaje aparece en el historial con la imagen y la pregunta, y el
   asistente responde usando el texto reconocido en la imagen.
3. **Given** hay una imagen adjunta y el campo de texto está vacío, **When** el usuario envía,
   **Then** el mensaje se acepta y el asistente responde con un resumen o explicación del texto
   reconocido.
4. **Given** una conversación en la que ya se envió una imagen, **When** el usuario hace una
   pregunta de seguimiento sin adjuntar nada ("¿y qué fecha figura?"), **Then** la respuesta
   sigue teniendo en cuenta el texto de esa imagen.

---

### User Story 2 - Ver qué texto se reconoció (Priority: P2)

El reconocimiento de texto puede equivocarse (imagen borrosa, letra manuscrita, tipografía
inusual). El usuario puede ver el texto que el sistema extrajo de la imagen para entender en qué
se basó el asistente y detectar errores de lectura.

**Why this priority**: da transparencia y ayuda a interpretar respuestas incorrectas, pero la
feature es usable sin esto.

**Independent Test**: enviar una imagen con texto y verificar que el mensaje enviado ofrece
desplegar el texto reconocido, y que este coincide con el contenido de la imagen.

**Acceptance Scenarios**:

1. **Given** el usuario envió un mensaje con imagen, **When** el mensaje aparece en el historial,
   **Then** ofrece una opción para ver el texto reconocido (oculto por defecto).
2. **Given** el usuario recarga la página dentro del período de conservación de la conversación,
   **When** se recupera el historial, **Then** el mensaje con imagen se muestra con una
   indicación de imagen adjunta (nombre del archivo) y su texto reconocido sigue disponible.

---

### User Story 3 - Aviso claro cuando la imagen no sirve (Priority: P3)

Si la imagen no tiene texto legible, tiene un formato no admitido o es demasiado grande, el
usuario recibe un aviso comprensible en lugar de una respuesta inventada o un error genérico.

**Why this priority**: evita frustración y respuestas engañosas, pero solo cubre casos de borde.

**Independent Test**: intentar adjuntar un archivo que no es imagen, una imagen que supera el
tamaño máximo y una foto sin texto, y verificar el aviso correspondiente en cada caso.

**Acceptance Scenarios**:

1. **Given** el usuario elige un archivo con formato no admitido o que supera el tamaño máximo,
   **When** intenta adjuntarlo, **Then** el chat lo rechaza antes de enviar e indica los formatos
   y el tamaño permitidos.
2. **Given** el usuario envía una imagen sin texto legible, **When** el sistema no reconoce
   texto, **Then** el usuario recibe un aviso de que no se encontró texto en la imagen y la
   conversación puede continuar normalmente.
3. **Given** el reconocimiento de texto no está disponible en el servidor, **When** el usuario
   intenta enviar una imagen, **Then** recibe un aviso de que el análisis de imágenes no está
   disponible por el momento, y puede seguir enviando mensajes de texto.

---

### Edge Cases

- ¿Qué pasa si la imagen tiene muchísimo texto (p. ej. una página completa)? Se usa el texto
  reconocido hasta un máximo configurable; si se recorta, el asistente y el usuario son
  informados de que se analizó solo una parte.
- ¿Qué pasa si la imagen contiene texto con instrucciones dirigidas al asistente ("ignorá tus
  instrucciones y …")? El texto reconocido se trata como contenido aportado por el usuario, nunca
  como instrucciones del sistema.
- ¿Qué pasa si la imagen está rotada o en otro idioma? Se reconocen al menos español e inglés; la
  calidad del reconocimiento en otros casos no está garantizada y el usuario puede ver el texto
  extraído (US2).
- ¿Qué pasa si el usuario adjunta una imagen y pulsa "detener" mientras el asistente responde?
  Mismo comportamiento que un mensaje de texto: la respuesta parcial queda como incompleta; el
  mensaje del usuario con su texto reconocido se conserva.
- ¿Qué pasa si el usuario intenta adjuntar más de una imagen? Solo se admite una imagen por
  mensaje; elegir otra reemplaza la anterior.
- ¿Qué pasa si el reconocimiento tarda demasiado? Se aplica un tiempo máximo; si se excede, el
  usuario recibe un aviso y puede reintentar.
- ¿Qué pasa si se reintenta la respuesta tras un error del modelo? Se reutiliza el texto ya
  reconocido; la imagen no se vuelve a procesar.
- ¿Qué pasa con un archivo que dice ser imagen pero no lo es (extensión cambiada o archivo
  dañado)? Se rechaza con el mismo aviso de formato no admitido.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El chat DEBE permitir adjuntar una imagen a un mensaje mediante un botón de
  adjuntar, con vista previa y opción de quitarla antes de enviar.
- **FR-002**: El sistema DEBE aceptar imágenes en formato PNG, JPEG y WebP de hasta 5 MB
  (límite configurable), y rechazar cualquier otro archivo indicando formatos y tamaño
  permitidos.
- **FR-003**: El chat DEBE validar formato y tamaño antes de enviar; el servidor DEBE volver a
  validarlos, incluido verificar que el contenido sea realmente una imagen del formato declarado.
- **FR-004**: Se admite como máximo una imagen por mensaje; el texto del mensaje es opcional
  cuando hay una imagen adjunta.
- **FR-005**: El sistema DEBE reconocer el texto contenido en la imagen (reconocimiento óptico de
  caracteres) en el servidor, sin enviar la imagen a servicios externos. El envío es en un solo
  paso: el texto reconocido llega al asistente sin revisión previa del usuario y no es editable.
- **FR-006**: El reconocimiento DEBE admitir al menos español e inglés.
- **FR-007**: El texto reconocido DEBE entregarse al asistente junto con la pregunta del usuario,
  identificado como contenido extraído de una imagen y tratado como contenido del usuario (no
  como instrucciones del sistema).
- **FR-008**: El texto reconocido DEBE formar parte del contexto de la conversación, de modo que
  las preguntas de seguimiento lo tengan en cuenta, sujeto a los mismos límites de contexto que
  los demás mensajes.
- **FR-009**: El texto reconocido que se usa DEBE limitarse a un máximo configurable (por
  defecto 8000 caracteres); si se recorta, el asistente y el usuario DEBEN ser informados.
- **FR-010**: Si no se reconoce texto legible, el sistema DEBE informar al usuario que la imagen
  no contiene texto reconocible, sin generar una respuesta del asistente basada en contenido
  inexistente.
- **FR-011**: El reconocimiento DEBE tener un tiempo máximo configurable; al excederse o fallar,
  el usuario DEBE recibir un aviso específico y poder reintentar.
- **FR-012**: Si el reconocimiento de texto no está disponible en el servidor, el envío de
  imágenes DEBE fallar con un aviso específico y el chat de texto DEBE seguir funcionando; el
  estado de salud del servicio DEBE reflejar esa indisponibilidad.
- **FR-013**: El historial DEBE mostrar los mensajes con imagen indicando que llevan una imagen
  adjunta (vista previa durante la sesión; nombre del archivo tras recargar) y permitir ver el
  texto reconocido.
- **FR-014**: El sistema NO DEBE conservar el archivo de imagen ni miniaturas después de
  procesarlo; solo se
  conservan el nombre del archivo, su tipo, su tamaño y el texto reconocido, con la misma
  política de vencimiento que el resto de la conversación.
- **FR-015**: El reintento de una respuesta fallida DEBE reutilizar el texto ya reconocido sin
  volver a procesar la imagen.
- **FR-016**: Los registros (logs) NO DEBEN incluir la imagen ni el texto reconocido, salvo en el
  modo diagnóstico ya existente; sí DEBEN registrar tamaño, tipo, duración del reconocimiento y
  cantidad de caracteres reconocidos.
- **FR-017**: Los clientes que no adjunten imágenes DEBEN seguir funcionando sin cambios (el
  envío de mensajes de solo texto se mantiene compatible).
- **FR-018**: El botón de adjuntar DEBE ser accesible por teclado y tener una etiqueta
  descriptiva; la vista previa DEBE poder quitarse también con teclado.

### Key Entities

- **Mensaje** (existente): se amplía para poder llevar, como máximo, un adjunto de imagen.
- **Adjunto de imagen**: representa la imagen enviada con un mensaje del usuario. Atributos:
  nombre original del archivo, tipo, tamaño, texto reconocido, si el texto fue recortado, y el
  resultado del reconocimiento (con texto / sin texto). No incluye la imagen en sí, que se
  descarta tras el procesamiento.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: En un conjunto de 10 capturas de pantalla nítidas con texto impreso en español o
  inglés, al menos 9 producen un texto reconocido en el que el usuario identifica el contenido
  principal y el asistente responde correctamente a "¿qué dice la imagen?".
- **SC-002**: Para una imagen de hasta 2 MB, el reconocimiento de texto tarda menos de 10
  segundos en el 90 % de los casos con el servidor sin otras cargas.
- **SC-003**: El 100 % de los archivos no admitidos (formato, tamaño o contenido falso) se
  rechazan con un aviso que indica qué está permitido, sin llegar al asistente.
- **SC-004**: Un usuario nuevo logra adjuntar una imagen y obtener una respuesta sobre su
  contenido en menos de 1 minuto sin instrucciones.
- **SC-005**: Ninguna imagen queda almacenada en el servidor después de procesar el mensaje, y
  ningún registro contiene el texto reconocido fuera del modo diagnóstico.
- **SC-006**: Con el reconocimiento de texto deshabilitado o no disponible, el 100 % de los
  mensajes de solo texto siguen funcionando igual que antes de esta feature.

## Assumptions

- El objetivo es **leer el texto** de las imágenes (confirmado en Clarifications); la
  descripción visual de la imagen (objetos, personas, escenas, gráficos) queda fuera de alcance,
  ya que el modelo actual solo procesa texto. Podría abordarse en una feature futura con un
  modelo multimodal.
- Por pedido del usuario, el reconocimiento de texto se hará con **pytesseract** (motor
  Tesseract), lo que requiere instalar Tesseract y los paquetes de idioma español e inglés en el
  servidor. La decisión concreta y su justificación como nueva dependencia se documentan en el
  plan.
- No se admiten PDF, documentos de oficina ni varias imágenes por mensaje en esta versión.
- No se admite pegar imágenes desde el portapapeles ni arrastrarlas en esta versión; solo el
  botón de adjuntar. (Puede agregarse si es simple en el plan.)
- Se mantienen las condiciones de la feature 001: uso interno en red local, sin autenticación,
  conversaciones conservadas 24 h desde la última actividad.
- El componente de chat reutilizable y la API expuesta al frontend se amplían de forma
  compatible: las páginas y clientes existentes que no usen imágenes no requieren cambios.
