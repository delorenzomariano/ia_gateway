# Feature Specification: Chatbot flotante con backend conectado a LLM local

**Feature Branch**: `001-chatbot-ollama-gateway`

**Created**: 2026-10-24

**Status**: Draft

**Input**: User description: "El frontend tendra  un componente flotante que va actuar de chatboot,  se comunica con el backend a traves de una api, el backend va a interactuar con ollama, y va a estar preparado para  en un futuro incorporar herramientas para proveerle al  modellm"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Conversar con el asistente desde el chat flotante (Priority: P1)

Un usuario que navega el frontend ve un botón flotante de chat en una esquina de la pantalla. Al
pulsarlo se abre una ventana de chat superpuesta al contenido, sin abandonar la página. El usuario
escribe una pregunta, la envía y recibe la respuesta generada por el modelo de lenguaje local.
Puede seguir haciendo preguntas y el asistente tiene en cuenta los mensajes anteriores de la
misma conversación.

**Why this priority**: es el valor central de la feature; sin esto no existe chatbot.

**Independent Test**: abrir el chat flotante, enviar "Hola, ¿qué podés hacer?" y verificar que
aparece una respuesta del modelo; enviar una pregunta de seguimiento que dependa de la anterior y
verificar que la respuesta la tiene en cuenta.

**Acceptance Scenarios**:

1. **Given** el usuario está en la página del frontend, **When** pulsa el botón flotante,
   **Then** se abre la ventana de chat sin recargar ni abandonar la página.
2. **Given** la ventana de chat está abierta, **When** el usuario envía un mensaje, **Then** el
   mensaje aparece en el historial y se muestra un indicador de "respondiendo" hasta que llega la
   respuesta del asistente.
3. **Given** una conversación con al menos un intercambio previo, **When** el usuario hace una
   pregunta que referencia lo anterior ("¿y eso cómo se hace?"), **Then** la respuesta es
   coherente con el contexto previo.
4. **Given** la ventana de chat está abierta, **When** el usuario la minimiza o cierra, **Then**
   vuelve a quedar solo el botón flotante y la página sigue siendo usable.

---

### User Story 2 - Ver la respuesta a medida que se genera (Priority: P2)

Las respuestas del modelo local pueden tardar varios segundos. El usuario ve el texto de la
respuesta aparecer progresivamente mientras se genera, en lugar de esperar a que esté completa.

**Why this priority**: mejora fuertemente la percepción de velocidad con un LLM local, pero el
chat es usable sin esto.

**Independent Test**: enviar una pregunta que produzca una respuesta larga y verificar que el
primer fragmento de texto aparece antes de que la respuesta completa termine de generarse.

**Acceptance Scenarios**:

1. **Given** el usuario envió un mensaje, **When** el modelo empieza a generar, **Then** el texto
   aparece en la ventana de chat de forma incremental.
2. **Given** una respuesta en curso, **When** el usuario pulsa "detener", **Then** la generación
   se interrumpe y queda visible el texto recibido hasta ese momento.

---

### User Story 3 - Recibir mensajes claros cuando algo falla (Priority: P2)

Si el modelo local no está disponible, tarda demasiado o ocurre un error, el usuario ve un mensaje
comprensible dentro del chat y puede reintentar, sin que el frontend se cuelgue.

**Why this priority**: el LLM local es una dependencia que puede estar caída o saturada; la
experiencia debe seguir siendo predecible.

**Independent Test**: detener el servidor del modelo, enviar un mensaje y verificar que aparece
un mensaje de error comprensible con opción de reintentar; levantar el servidor y reintentar con
éxito.

**Acceptance Scenarios**:

1. **Given** el modelo local no está disponible, **When** el usuario envía un mensaje, **Then**
   ve un aviso de que el asistente no está disponible y una opción de reintentar.
2. **Given** el modelo no responde dentro del tiempo máximo configurado, **When** se cumple ese
   tiempo, **Then** el usuario ve un aviso de demora y puede reintentar.
3. **Given** ocurrió un error, **When** el usuario reintenta y el modelo ya está disponible,
   **Then** recibe la respuesta normalmente y la conversación previa se conserva.

---

### User Story 4 - Base preparada para incorporar herramientas (Priority: P3)

Como responsable del sistema, quiero que el backend permita, en una etapa futura, registrar
herramientas que el modelo pueda usar para obtener información o ejecutar acciones, sin rediseñar
el flujo de chat ni el contrato con el frontend.

**Why this priority**: es una preparación para evolución futura; no entrega valor visible al
usuario final en esta versión.

**Independent Test**: verificar que existe un registro de herramientas (vacío en esta versión),
que el sistema funciona normalmente con cero herramientas registradas, y que registrar una
herramienta de prueba no requiere cambios en el contrato de la API con el frontend.

**Acceptance Scenarios**:

1. **Given** no hay herramientas registradas, **When** el usuario conversa, **Then** el chat
   funciona solo con el modelo, sin errores.
2. **Given** una herramienta de prueba registrada en un entorno de pruebas, **When** el modelo
   solicita usarla, **Then** el backend la ejecuta, devuelve el resultado al modelo y el frontend
   recibe la respuesta final por el mismo contrato de API.
3. **Given** el modelo solicita una herramienta no registrada, **When** el backend procesa la
   solicitud, **Then** la rechaza y la conversación continúa sin ejecutarla.

---

### Edge Cases

- El usuario vuelve después de vencida la retención: se muestra una conversación nueva vacía.
- El usuario abre el frontend en dos pestañas del mismo navegador: ambas usan la misma
  conversación.
- El navegador envía un identificador de conversación inexistente o vencido: el backend lo
  rechaza con un error controlado y el frontend inicia una conversación nueva.
- El backend se reinicia: las conversaciones no vencidas DEBEN seguir disponibles.

- El usuario envía un mensaje vacío o solo con espacios: no se envía.
- El usuario envía un mensaje que excede el largo máximo permitido: se le informa el límite y no
  se envía.
- El usuario envía un nuevo mensaje mientras otra respuesta se está generando: el envío queda
  bloqueado hasta que termina o se detiene la respuesta en curso.
- La conversación crece más allá de lo que el modelo puede considerar: se conserva el contexto
  más reciente y el chat sigue funcionando.
- El modelo devuelve una respuesta vacía o malformada: se muestra un aviso de error con opción
  de reintentar.
- Se pierde la conexión entre frontend y backend a mitad de una respuesta: se muestra el texto
  recibido y un aviso de respuesta incompleta.
- La pantalla es pequeña (móvil): la ventana de chat se adapta y no impide cerrar el chat.

## Requirements *(mandatory)*

### Functional Requirements

**Componente de chat (frontend)**

- **FR-001**: El proyecto DEBE incluir un frontend mínimo (una página web) que aloje el chat y
  muestre un botón flotante de chat visible que no tape contenido esencial.
- **FR-001a**: El componente de chat DEBE ser autocontenido y reutilizable: su incorporación a
  otra página o aplicación DEBE requerir solo incluirlo e indicarle la dirección del backend, sin
  modificar el componente.
- **FR-002**: Al activar el botón, el sistema DEBE abrir una ventana de chat superpuesta que
  pueda minimizarse y volver a abrirse sin perder la conversación en curso.
- **FR-003**: La ventana de chat DEBE mostrar el historial de la conversación diferenciando
  mensajes del usuario y del asistente.
- **FR-004**: El sistema DEBE mostrar un indicador de actividad mientras espera la respuesta.
- **FR-005**: El sistema DEBE impedir enviar mensajes vacíos o que superen el largo máximo
  configurado (por defecto 4.000 caracteres).
- **FR-006**: El componente DEBE poder usarse con teclado (abrir, escribir, enviar con Enter,
  cerrar con Escape).

**Comunicación frontend ↔ backend**

- **FR-007**: El frontend DEBE comunicarse con el backend exclusivamente mediante una API
  documentada; el frontend no DEBE acceder directamente al modelo de lenguaje.
- **FR-008**: La API DEBE permitir enviar un mensaje junto con el identificador de la
  conversación y recibir la respuesta del asistente.
- **FR-009**: La API DEBE permitir recibir la respuesta de forma incremental mientras se genera,
  y cancelar una respuesta en curso.
- **FR-010**: Las respuestas de error de la API DEBEN tener un formato uniforme con un código,
  un mensaje apto para mostrar al usuario y un identificador de correlación.
- **FR-011**: En esta versión la API de chat NO requiere autenticación de usuarios: su uso es
  interno y el acceso DEBE limitarse a la red local (orígenes y direcciones permitidos
  configurables). Esta excepción al principio de autenticación de la constitución DEBE quedar
  documentada, y el diseño DEBE permitir agregar autenticación más adelante sin rediseñar el
  flujo de chat.

**Conversación e interacción con el modelo (backend)**

- **FR-012**: El backend DEBE enviar al modelo de lenguaje local el mensaje del usuario junto con
  el contexto reciente de la conversación y un mensaje de sistema configurable que define el
  comportamiento del asistente.
- **FR-013**: El sistema DEBE conservar cada conversación (contexto e historial visible) cuando
  el usuario recarga la página o vuelve más tarde desde el
  mismo navegador, durante un tiempo de retención configurable (por defecto 24 horas desde la
  última actividad). Pasado ese tiempo la conversación se elimina y el usuario empieza una nueva.
- **FR-013c**: El backend DEBE ser el único responsable de almacenar los mensajes de cada
  conversación y de construir el contexto enviado al modelo; el navegador solo conserva el
  identificador de la conversación y DEBE poder recuperar el historial desde el backend al
  recargar. El backend NO DEBE aceptar historial enviado por el cliente.
- **FR-013a**: El usuario DEBE poder iniciar una conversación nueva en cualquier momento,
  descartando la actual.
- **FR-013b**: No se ofrece historial permanente ni listado de conversaciones anteriores; cada
  navegador tiene una única conversación activa.
- **FR-014**: El backend DEBE aplicar un tiempo máximo de espera configurable a cada consulta al
  modelo y devolver un error controlado si se excede.
- **FR-015**: El backend DEBE validar la respuesta del modelo antes de devolverla al frontend y
  tratarla como contenido no confiable (el frontend la muestra como texto, sin ejecutar código).
- **FR-016**: El modelo a utilizar, la dirección del servidor del modelo, los tiempos máximos y
  los límites DEBEN ser configurables sin modificar el código.

**Preparación para herramientas**

- **FR-017**: El backend DEBE contar con un registro de herramientas donde cada herramienta se
  declara con nombre, descripción y esquema de entrada y salida; en esta versión el registro
  puede estar vacío.
- **FR-018**: Cuando haya herramientas registradas, el backend DEBE ofrecerlas al modelo,
  ejecutar solo las solicitadas que estén registradas, validar sus argumentos y devolver el
  resultado al modelo antes de generar la respuesta final.
- **FR-019**: Incorporar herramientas NO DEBE requerir cambios en el contrato de la API con el
  frontend.

**Operación**

- **FR-020**: El backend DEBE exponer un chequeo de salud que indique su estado y la
  disponibilidad del modelo local.
- **FR-021**: El backend DEBE registrar para cada solicitud: identificador de correlación,
  latencia del modelo, errores, herramientas invocadas y consumo de tokens cuando esté disponible,
  sin registrar secretos.
- **FR-022**: Por defecto los logs NO DEBEN incluir el texto de los mensajes del usuario ni de
  las respuestas del modelo. Un modo de diagnóstico, desactivado por defecto y habilitable solo
  por configuración, PUEDE agregar ese texto; al iniciar con el modo activo el backend DEBE
  emitir una advertencia visible en los logs.

### Key Entities

- **Conversación**: secuencia de mensajes entre un usuario y el asistente; tiene un identificador
  (asociado al navegador que la inició), fecha de inicio, última actividad y vencimiento según la
  retención configurada.
- **Mensaje**: unidad de la conversación; tiene rol (usuario, asistente, sistema, herramienta),
  contenido, fecha y estado (completo, incompleto, error).
- **Herramienta**: capacidad registrada que el modelo puede solicitar; tiene nombre, descripción,
  esquema de entrada y de salida.
- **Invocación de herramienta**: registro de una ejecución solicitada por el modelo dentro de una
  conversación: herramienta, argumentos, resultado o error, duración.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un usuario nuevo puede abrir el chat, enviar una pregunta y recibir respuesta sin
  instrucciones previas en menos de 30 segundos.
- **SC-002**: En el 90% de las consultas, el primer fragmento de la respuesta aparece en menos de
  3 segundos con el modelo disponible y sin carga concurrente.
- **SC-003**: El 100% de las fallas del modelo (caído, demora excesiva, respuesta inválida) se
  muestran al usuario como un mensaje comprensible con opción de reintentar; ninguna deja el chat
  bloqueado.
- **SC-004**: En pruebas de conversación de 10 intercambios, el asistente responde de forma
  coherente con el contexto previo en al menos el 90% de las preguntas de seguimiento.
- **SC-005**: Registrar una herramienta de prueba no requiere ningún cambio en el frontend ni en
  el contrato de la API.
- **SC-006**: El sistema atiende al menos 5 conversaciones simultáneas sin errores (las respuestas
  pueden demorar más, pero no fallar).

## Assumptions

- El modelo de lenguaje corre localmente mediante Ollama, en la misma red que el backend, con al
  menos un modelo descargado; la elección del modelo concreto es configuración.
- No existe un frontend previo: el proyecto crea una página web mínima que aloja el chat. No se
  requiere en esta versión navegación entre varias páginas ni integración en sitios de terceros,
  aunque el componente queda aislado para permitirlo a futuro.
- El idioma principal de uso es español; el comportamiento del asistente se define con el mensaje
  de sistema configurable.
- No se incorporan herramientas concretas en esta versión; solo la estructura para registrarlas
  y una herramienta de prueba para validar el flujo en entorno de pruebas.
- Las respuestas se muestran como texto con formato básico (párrafos, listas, bloques de código);
  no se soportan archivos adjuntos, imágenes ni voz en esta versión.
- La carga esperada es baja (uso de taller/equipo reducido); no se requiere escalado horizontal.
- El sistema se usa solo dentro de la red local; exponerlo a Internet requerirá agregar
  autenticación (feature futura).
- Como no hay usuarios identificados, la conversación se asocia al navegador; borrar los datos
  del navegador o cambiar de dispositivo inicia una conversación nueva.

## Clarifications

### Session 2026-10-24

- Q: ¿Quién puede usar el chatbot? → A: Uso interno sin autenticación en esta versión, limitado a
  la red local (excepción documentada a la constitución).
- Q: ¿Cuánto dura una conversación? → A: Se conserva al recargar o volver, con retención
  configurable (por defecto 24 h desde la última actividad).
- Q: ¿El chat se agrega a un frontend existente o el proyecto crea el frontend? → A: El proyecto
  crea un frontend mínimo (una página) que aloja el chat; el componente es aislado y reutilizable.
- Q: ¿Dónde se guarda la conversación? → A: En el backend; el navegador solo guarda el
  identificador y el backend elimina las conversaciones vencidas.
- Q: ¿Los logs pueden incluir el texto de los mensajes? → A: No por defecto; solo con un modo
  de diagnóstico habilitado por configuración.
