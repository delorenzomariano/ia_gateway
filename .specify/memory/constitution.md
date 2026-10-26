<!--
Sync Impact Report
- Version change: (template sin completar) → 1.0.0
- Principios definidos (todos nuevos):
  - I. API-First con Contratos Explícitos
  - II. Integraciones Aisladas mediante Adaptadores
  - III. Seguridad y Manejo de Secretos (NO NEGOCIABLE)
  - IV. Resiliencia ante Dependencias Externas
  - V. Pruebas de Contrato e Integración
  - VI. Observabilidad
  - VII. Simplicidad
- Secciones agregadas: Restricciones de Arquitectura, Flujo de Desarrollo y Calidad, Gobernanza
- Secciones eliminadas: ninguna
- Plantillas: no se modifican (leen la constitución en tiempo de ejecución)
- TODOs diferidos: ninguno (stack tecnológico se decide intencionalmente en /speckit-plan)
-->

# IA Gateway Constitution

IA Gateway es un backend que actúa como intermediario entre un frontend, un servidor LLM local y
herramientas expuestas por una API externa. El frontend se comunica con el backend exclusivamente
a través de una API.

## Core Principles

### I. API-First con Contratos Explícitos

- Toda funcionalidad expuesta al frontend DEBE estar definida primero como contrato de API
  (p. ej. OpenAPI) antes de implementarse.
- El frontend DEBE comunicarse con el backend únicamente a través de esa API; no hay acceso
  directo del frontend al servidor LLM ni a la API de herramientas.
- Los contratos DEBEN estar versionados; un cambio incompatible requiere nueva versión de API
  y nota de migración.
- Las respuestas de error DEBEN seguir un formato uniforme y documentado (código, mensaje,
  identificador de correlación).

**Razón**: el backend es el punto único de integración; un contrato estable permite que frontend
y backend evolucionen de forma independiente.

### II. Integraciones Aisladas mediante Adaptadores

- El acceso al servidor LLM local y a la API externa de herramientas DEBE encapsularse en
  adaptadores con una interfaz interna propia.
- La lógica de negocio y la orquestación (prompt → LLM → llamada a herramientas → respuesta)
  NO DEBEN depender de detalles específicos del proveedor (formatos, SDKs, URLs).
- Reemplazar el servidor LLM o el proveedor de herramientas DEBE requerir cambios solo en el
  adaptador correspondiente y su configuración.
- Las herramientas invocables por el LLM DEBEN declararse explícitamente (lista permitida con
  esquema de entrada/salida); el LLM no puede invocar herramientas no registradas.

**Razón**: los modelos locales y las APIs externas cambian con frecuencia; el aislamiento limita
el impacto de esos cambios y facilita las pruebas.

### III. Seguridad y Manejo de Secretos (NO NEGOCIABLE)

- Credenciales, tokens y URLs sensibles DEBEN provenir de configuración/variables de entorno;
  NUNCA se versionan en el código ni se envían al frontend.
- Los secretos y datos sensibles NO DEBEN aparecer en logs ni en mensajes de error.
- La API expuesta al frontend DEBE validar toda entrada (esquema, tamaño, tipos) antes de
  enviarla al LLM o a las herramientas.
- La salida del LLM DEBE tratarse como no confiable: se valida antes de ejecutar herramientas y
  antes de devolverla al frontend.
- El backend DEBE requerir autenticación para endpoints que consuman el LLM o herramientas,
  salvo excepción documentada.

**Razón**: el gateway concentra acceso a recursos de cómputo y servicios externos; es el punto
crítico de control de seguridad, incluyendo riesgos de prompt injection.

### IV. Resiliencia ante Dependencias Externas

- Toda llamada al servidor LLM y a la API de herramientas DEBE tener timeout configurable.
- Los reintentos DEBEN ser acotados (con backoff) y aplicarse solo a operaciones idempotentes.
- La caída o lentitud de una dependencia DEBE traducirse en un error controlado y documentado
  hacia el frontend, nunca en un cuelgue o en una excepción sin manejar.
- Las respuestas largas del LLM DEBERÍAN soportar streaming hacia el frontend cuando el caso de
  uso lo justifique.

**Razón**: un LLM local puede ser lento o estar saturado y una API externa puede fallar; el
usuario del frontend debe recibir siempre una respuesta predecible.

### V. Pruebas de Contrato e Integración

- Cada endpoint de la API DEBE tener pruebas de contrato que verifiquen el esquema publicado.
- Cada adaptador DEBE tener pruebas con dobles (mocks/stubs) del LLM y de la API de herramientas,
  de modo que la suite principal no dependa de servicios reales.
- Los flujos de orquestación críticos DEBEN cubrirse con pruebas de integración, incluyendo
  casos de error, timeout y respuestas malformadas del LLM.
- Para cambios de contrato o de adaptadores, las pruebas DEBEN escribirse antes o junto con la
  implementación y fallar antes de que el cambio se complete.

**Razón**: los componentes externos no son deterministas; las pruebas con dobles y de contrato
dan confianza reproducible.

### VI. Observabilidad

- El backend DEBE emitir logs estructurados con un identificador de correlación por request,
  propagado a las llamadas al LLM y a las herramientas.
- DEBEN registrarse, como mínimo: latencia por dependencia, errores, herramientas invocadas y
  consumo de tokens cuando el servidor LLM lo informe.
- DEBE existir un endpoint de salud que refleje el estado del backend y de sus dependencias.

**Razón**: diagnosticar fallas en una cadena frontend → backend → LLM → herramientas es inviable
sin trazabilidad de extremo a extremo.

### VII. Simplicidad

- Se implementa solo lo requerido por una especificación aprobada (YAGNI).
- Cada dependencia nueva o capa de abstracción adicional DEBE justificarse en el plan
  (sección de complejidad).
- Se prefiere un único servicio backend hasta que exista una necesidad demostrada de dividirlo.

**Razón**: el proyecto debe mantenerse comprensible y fácil de evolucionar.

## Restricciones de Arquitectura

- Topología fija: Frontend ⇄ (API) ⇄ Backend IA Gateway ⇄ {Servidor LLM local, API externa de
  herramientas}. Ningún otro camino de comunicación entre estos componentes está permitido.
- El stack tecnológico concreto (lenguaje, framework, servidor LLM) se define en cada
  `plan.md` y DEBE ser consistente entre features salvo justificación explícita.
- La configuración (endpoints del LLM, de la API de herramientas, modelo, timeouts, límites)
  DEBE ser externa al código y documentada con valores por defecto seguros.
- Los formatos intercambiados con el frontend DEBEN ser JSON (o eventos de streaming
  documentados, p. ej. SSE).

## Flujo de Desarrollo y Calidad

- Toda feature sigue el flujo Spec Kit: `/speckit-specify` → `/speckit-clarify` (si aplica) →
  `/speckit-plan` → `/speckit-tasks` → `/speckit-implement`.
- El `plan.md` DEBE incluir un "Constitution Check" que verifique cada principio; las
  desviaciones se registran en la tabla de complejidad con su justificación.
- Ningún cambio se considera terminado si: las pruebas fallan, el contrato de API no está
  actualizado, o se introducen secretos en el repositorio.
- Las revisiones de código DEBEN verificar explícitamente los principios III (seguridad) y
  IV (resiliencia) en cambios que toquen adaptadores o endpoints.

## Governance

- Esta constitución prevalece sobre cualquier otra práctica o convención del proyecto.
- Enmiendas: se proponen modificando este archivo mediante `/speckit-constitution`, con
  descripción del cambio, motivo e impacto sobre specs/planes existentes.
- Versionado semántico:
  - MAJOR: eliminación o redefinición incompatible de un principio o de la gobernanza.
  - MINOR: nuevo principio o sección, o ampliación material de una guía.
  - PATCH: aclaraciones, redacción o correcciones sin cambio semántico.
- Cumplimiento: cada plan y cada revisión DEBEN verificar conformidad con esta constitución;
  `/speckit-analyze` DEBERÍA ejecutarse antes de implementar para detectar desvíos.

**Version**: 1.0.0 | **Ratified**: 2026-10-24 | **Last Amended**: 2026-10-24
