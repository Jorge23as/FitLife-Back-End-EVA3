# Registro de apoyo de Inteligencia Artificial — EVA-3 (FitLife)

**Alumno:** Jorge Conejeros Suazo · **Sección:** TI3041 · **Año:** 2026
**Herramienta:** Claude Code (asistente de programación de Anthropic, modelo Claude Opus 5.5) dentro de VS Code.
Trabaja sobre la carpeta del proyecto: lee archivos, propone y escribe código, ejecuta comandos y pruebas.
**Base de la pauta:** sección IV, "Apoyo de Inteligencia Artificial": se acepta el uso de IA para optimizar la
codificación, generar estructuras HTML/CSS o scripts de despliegue, dejando registro de las consultas.

## Resumen

| # | Fecha | Etapa | Consulta | Apoyo de la IA | Verificación |
|---|---|---|---|---|---|
| 1 | 26-10-2026 | Análisis | Leer la pauta de la EVA-3 (me tocó el proyecto 2) | Resumen de la pauta, la rúbrica y lo que pide el caso FitLife | Comparado con el `.docx` de la pauta |
| 2 | 26-10-2026 | Decisión | ¿Puedo presentar el software de la EVA-2? | Análisis: la rúbrica evalúa las 4 funcionalidades de FitLife; recomendación de hacer FitLife reutilizando la base y la instancia | Decisión mía: hacer FitLife |
| 3 | 26-10-2026 | Apoyo | Transcribir los audios de la clase | Transcripción local con Whisper; datos de la entrega (lunes 2, 70/30, prueba de 20 preguntas) | Escuchado en los audios |
| 4 | 26/27-10-2026 | Construcción | Construir FitLife | Modelo de datos, reglas de negocio, API, admin, páginas, pruebas y scripts de despliegue | 84 pruebas automáticas y recorrido en el navegador |
| 5 | 27-10-2026 | Revisión | (dentro de la construcción) | Las pruebas y el recorrido encontraron 5 errores, que se corrigieron | Pruebas en verde después de cada corrección |

## 1. Análisis de la pauta

**Consulta (textual):**
> te dejo las instrucciones de la eva 3 está en "/home/Jorgito/Inacap/back-end/eva3" a mi me tocó la 2 por cierto.

**Apoyo de la IA:** leyó la pauta (`EVA_3_Backend.docx`), la lista de proyectos por alumno y las recetas del curso
(Receta AWS EC2 con Gunicorn y Nginx, Receta DRF y la guía de enmascaramiento de endpoints). Resumió:

- Proyecto 2, FitLife: CRUD de planes, pagos y estados de membresía; acceso con QR; reserva de clases con cupos
  y lista de espera; aforo en tiempo real.
- Requisitos técnicos: DRF, admin de Django personalizado, sesiones y permisos por rol, PostgreSQL con
  migraciones, plantillas que consumen la API, una sola EC2 accesible por IP pública, `README.md` y este archivo.
- Rúbrica de 5 criterios de 20 puntos.

## 2. ¿Reutilizar el software de la EVA-2?

**Consultas (textuales):**
> es que no viste que en el audio 2 le pregunté al profe que podria usar el mismo software?

> antes siguas, entonces hay que usar otro software?

> entonces debo hacer otro software ? no habria problema si hacemos otro?

**Apoyo de la IA:** comparó la Farmacia B2B (EVA-2) con la rúbrica: no tiene ninguna de las 4 funcionalidades
de FitLife ni usa el admin de Django, que ahora vale 20 puntos. Recomendó hacer FitLife reutilizando lo que sirve
de la EVA-2 (login con bloqueo, seguridad, scripts de despliegue) y la misma instancia de AWS, con su propia
base, servicio y dominio, sin tocar la Farmacia.

**Decisión mía:** construir FitLife en una carpeta y repositorio nuevos.

## 3. Transcripción de los audios de la clase

**Consulta (textual):**
> te paso el audio para que lo transcribas?

**Apoyo de la IA:** transcribió los dos audios de WhatsApp en mi PC con Whisper (`faster-whisper`, sin subirlos
a internet) y limpió el audio en las partes que no se entendían. De ahí salieron los datos de la entrega: lunes
2 de noviembre a la hora de clase, presentación de 3 o 4 voluntarios, revisión "está / no está" de la rúbrica,
prueba de 20 preguntas generadas desde la receta y ponderación acordada 70/30.

## 4. Construcción de FitLife

**Consulta (textual):**
> continua construyendo el software de la conversacion que estabamos, aqui está la ruta de las instrucciones de la prueba 3: "/home/Jorgito/Inacap/back-end/eva3"

**Apoyo de la IA, por partes:**

| Parte | Qué se hizo | Por qué así |
|---|---|---|
| Modelo de datos | Apps `cuentas`, `membresias`, `clases`, `accesos`. Estados con `TextChoices`; restricciones en PostgreSQL (`CheckConstraint`, `UniqueConstraint` condicional, `PROTECT`). | Que la base misma impida datos inválidos (dos reservas vigentes en la misma clase, fechas al revés, borrar historial). |
| Reglas de negocio | `services.py` en cada app: el pago crea o renueva la membresía, vencimiento por fecha, congelamiento con tope por plan, reservas con lista de espera que avanza sola, validación del QR, aforo. | La API y el admin llaman a las mismas funciones, así la regla es una sola. |
| Sobrecupo | `select_for_update()` sobre la clase dentro de una transacción. Prueba con 2 hilos que reservan el último cupo al mismo tiempo. | Es justo el problema del caso: sin el bloqueo, dos reservas simultáneas podían quedar confirmadas. |
| QR | QR firmado con la `SECRET_KEY` (`TimestampSigner`) que vale 60 segundos. | Una captura de pantalla compartida deja de servir: ataca el "ingreso de usuarios con membresías vencidas". |
| Seguridad | Sesiones de Django (cookie HttpOnly), CSRF en todo lo que modifica datos (también en el login), permisos por rol, grupos de Django para el admin, bloqueo del login por fuerza bruta, CSP con nonce. | Criterio 4 de la rúbrica (sesiones y restricciones). |
| Admin de Django | Sitio propio con indicadores, plantillas propias, filtros, búsquedas, etiquetas de estado, inlines y acciones (congelar con página intermedia, anular pagos, cancelar clases). | Criterio 2 de la rúbrica (admin personalizado con templates). |
| Páginas (enmascaramiento) | Vistas con `render()` que solo entregan la plantilla; el JavaScript consume la API con `fetch()` y `X-CSRFToken`, igual que la guía del curso. | Requisito de "frontend y enmascaramiento". |
| Datos de prueba | Comando `cargar_demo` que arma un escenario relativo a la hora actual (gente dentro, clase llena, socio vencido y congelado). | Para mostrar todos los casos en la demostración. |
| Pruebas | 84 pruebas automáticas (`python manage.py test`). | Comprobar cada regla del caso y la seguridad. |
| Despliegue | `deploy/instalar.sh`, `actualizar.sh`, servicio de Gunicorn y sitio de Nginx propios, guía por etapas de la receta. | Misma instancia de la EVA-2 sin afectar a la Farmacia. |

## 5. Errores que encontró la verificación

La IA corrió las pruebas y recorrió todas las páginas con un navegador automatizado (Chromium) con cada rol.
Eso encontró 5 errores, que se corrigieron:

1. **Portada del admin con error 500:** en un `aggregate()`, el alias `reservas` tapaba la relación `reservas`
   que usaba el filtro. Se renombró a `n_reservas`.
2. **Editar una clase por la API fallaba:** el conteo anotado `ocupados` tapaba el método `Clase.ocupados()` que
   usan las reglas. Se renombró a `n_ocupados` (lo detectó una prueba automática).
3. **Simulación de QR en recepción:** si se elegía un socio y se apretaba "Simular" antes de que cargara su QR,
   se validaba el QR del socio anterior. Ahora el botón queda desactivado mientras carga.
4. **Datos de prueba poco realistas:** un socio quedaba con unas 30 clases reservadas en la semana. Ahora cada
   socio elige de 2 a 5 clases de los próximos 4 días, una por día como máximo.
5. **Horario desordenado:** las clases salían agrupadas por actividad y no por hora. Al contar las reservas con
   `Count()` la consulta usa `GROUP BY`, y en ese caso Django no aplica el `ordering` del modelo. Se agregó
   `order_by('inicio')` explícito.
6. **"Generar QR nuevo" no hacía nada (lo encontró el alumno probando):** al escribir en el buscador de socios se
   rearmaba la lista y se perdía el socio elegido, entonces el botón no tenía a quién generarle el QR. Ahora se
   recuerda el socio que se está mostrando.
7. **La cámara se veía al revés (lo encontró el alumno):** la cámara del notebook no se mostraba como espejo, como
   en una videollamada. Ahora la imagen se voltea con CSS (`transform: scaleX(-1)`) y hay un botón para voltearla
   a mano. La lectura del QR no cambia, porque se hace sobre el cuadro original de la cámara.

## 6. Rediseño visual "de centro deportivo"

**Prompt:** "le pasé este software a uno de mis amigos de ciberseguridad y me dijeron que en la parte visual no
parece un centro deportivo o un gym. así que vamos a ponerle imágenes de fondo y que se vea como una página de
centro deportivo. aquí unas páginas de ejemplo (FitFit Temuco, Elysium, Smart Fit). ¿qué te parece mi idea? ¿no
afecta la pauta?"

**Respuesta / decisiones de la IA:**

| Tema | Decisión | Por qué |
|---|---|---|
| Pauta | No la afecta: el frontend solo pide "interfaz web responsiva" con plantillas que consuman la API. Solo se cambiaron plantillas y CSS; la API, las reglas y el admin quedaron igual (84 pruebas OK). | Mejora la presentación en la defensa sin riesgo. |
| Fotos | Fotos de Unsplash (licencia libre, uso comercial permitido) descargadas en `static/img/fotos/` en formato WebP (1,4 MB en total). No se copiaron imágenes de los sitios de ejemplo. | Derechos de autor; y servirlas desde `/static` no obliga a abrir el CSP (`img-src 'self'`). |
| Letra | Oswald (licencia OFL) guardada en `static/fonts/` para títulos. | Mismo motivo: sin Google Fonts no hay que agregar dominios al CSP. |
| Portada | Cabecera grande con foto, tarjetas con foto por actividad (cargadas desde `GET /api/actividades/`), instalaciones y franja final con foto. | Que se vea como la página de un gimnasio, igual que los ejemplos. |
| Resto | Franja con foto bajo el menú en todas las páginas, ingreso con foto al lado, pie de página nuevo. Se revisó en escritorio y celular (390 px) con Chromium sin scroll horizontal. | Requisito "responsiva". |

## 7. Comprobante de pago profesional y consulta sobre Webpay

**Prompts:** "el comprobante no me convence, ¿podríamos poner uno más empresarial? y una pregunta: ¿la pauta pide
Webpay Transbank?" y luego "sí, un comprobante más profesional".

**Respuesta / decisiones de la IA:**

| Tema | Decisión | Por qué |
|---|---|---|
| Webpay | No se agrega: la pauta pide "CRUD y administración de Planes, Pagos y Estados de Membresía", no pago en línea. | El ambiente de pruebas de Transbank es lento y podría fallar en la demo en vivo. |
| Comprobante | Antes era una línea de texto en una ventana. Ahora es la página `/comprobantes/<id>/` con formato de documento: datos de la empresa, recuadro con RUT y N° de folio, datos del cliente, detalle, neto + IVA 19 % + total, monto en palabras, estado (pagado o anulado con marca de agua) y botón "Imprimir / Guardar PDF" (sale en una hoja A4). | Se ve como un documento comercial real y se puede entregar al socio. |
| Seguridad | El socio puede abrir `GET /api/pagos/{id}/` solo de sus pagos: `get_queryset()` filtra por el usuario de la sesión, así que el de otro da 404 (no 403, para no revelar que existe). La lista de pagos sigue siendo solo para el personal. | Criterio 4 (permisos por rol). 2 pruebas nuevas (86 en total). |
| Accesos | Botón en Gestión → Pagos, pregunta al registrar un pago en Socios, enlace en "Mi cuenta" del socio y columna "Ver / imprimir" en el admin de Django. | Que se use en los flujos de la demo. |
| Datos de la empresa | Ficticios, en `settings.EMPRESA`. El pie aclara que es un documento interno y no reemplaza la boleta electrónica del SII. | No hacerlo pasar por un documento tributario. |

## 8. Revisión de CVE del stack antes del despliegue

**Prompts:** "dame todo el stack para que yo busque los CVE de sus versiones" y luego un reporte con 5 CVE
(3 de Django 6.1.2 y 2 de Python 3.13/3.14) marcados como prioridad alta.

**Verificación de la IA (2026-10-31):** cada CVE se buscó en cve.org, OSV, NVD y en los rastreadores de Debian y
Ubuntu. Además se consultaron en OSV las 24 dependencias con su versión exacta (20 de PyPI y 4 librerías de CDN):
ninguna tiene vulnerabilidades conocidas.

| CVE | Qué es | ¿Nos afecta? |
|---|---|---|
| CVE-2026-87975 (Django) | Formsets con PK editable permiten borrar filas fuera del queryset | **No.** Afecta a 6.1 *antes de* 6.1.2; usamos 6.1.2, que es la versión que lo corrige. |
| CVE-2026-84429 (Django) | DoS por cabeceras `Accept`/`Content-Type` con muchos separadores | **No.** Mismo rango: corregido en 6.1.2. |
| CVE-2026-77050 (Django) | DoS por memoria en `get_supported_language_variant()` | **No.** Mismo rango: corregido en 6.1.2. |
| CVE-2026-115557 (Python `ssl`) | Python no rechazaba certificados intermedios comprometidos (eMudhra): MitM | **Riesgo bajo.** Sin parche aún en Debian 13 ni Ubuntu (corregido arriba en 3.13.18 / 3.14.10). La app nunca usa Python como cliente TLS: no llama APIs externas, la base es por socket local y el HTTPS lo atiende Nginx (OpenSSL). Solo `pip install` usa TLS durante el despliegue. |
| CVE-2026-114583 (Python `tarfile`) | `extractall(filter="tar")` puede escribir fuera de la carpeta destino | **No aplica.** El código no usa `tarfile` y es un ataque local (AV:L) que necesita un .tar malicioso. |

**Estatus del resto del inventario** (OSV, que incluye GitHub Advisories y PyPA, consultado el 2026-10-31 17:19 con
la versión exacta de cada paquete). La consulta sí encuentra avisos: por ejemplo djangorestframework tiene 11 en su
historial, gunicorn 6, PyYAML 8, sqlparse 17 y pip 26, todos en versiones anteriores a las instaladas.

| Paquete | Versión | Uso | Estatus |
|---|---|---|---|
| djangorestframework | 3.18.3 | API REST | Aprobado (sin CVE conocidos en la versión instalada) |
| drf-spectacular | 0.30.0 | Esquema OpenAPI | Aprobado |
| django-filter | 26.2 | Filtros de la API | Aprobado |
| gunicorn | 26.2.0 | Servidor WSGI | Aprobado |
| qrcode | 8.2 | QR en SVG | Aprobado |
| python-dotenv | 1.2.4 | Lee el `.env` | Aprobado |
| PyYAML | 6.0.3 | Esquema OpenAPI | Aprobado |
| sqlparse | 0.6.0 | Dependencia de Django | Aprobado |
| asgiref | 3.13.0 | Dependencia de Django | Aprobado |
| jsonschema / jsonschema-specifications / referencing / rpds-py / attrs | 4.26.0 / 2025.9.1 / 0.37.0 / 2026.9.1 / 26.1.0 | Dependencias de drf-spectacular | Aprobado |
| inflection / uritemplate | 0.5.1 / 4.2.0 | Dependencias de drf-spectacular | Aprobado |
| packaging | 26.3 | Dependencia de gunicorn | Aprobado |
| psycopg / psycopg-binary | 3.3.6 | Driver de PostgreSQL | Aprobado el paquete, **pero** la wheel trae OpenSSL 3.5.8 embebido; OpenSSL 3.5.9 (29-09-2026) corrige 14 CVE (1 alto de DTLS, 13 bajos). Riesgo bajo: la conexión es solo a PostgreSQL local. |
| pip | 26.2.2 | Instalador (solo en el despliegue) | Aprobado |
| bootstrap / bootstrap-icons / jsqr / swagger-ui-dist (npm, CDN con SRI) | 5.3.3 / 1.11.3 / 1.4.0 / 5.34.0 | Frontend | Aprobado (jsqr no tiene mantenimiento desde 2019) |

**Decisión:** no hay que cambiar versiones. Antes de la demo se corre `sudo apt update && sudo apt upgrade` en la EC2
para tomar los parches de Ubuntu cuando salgan.

**Mitigación aplicada para psycopg-binary (opción elegida por el alumno):** se sacó `psycopg-binary` de
`requirements.txt`. Ahora psycopg usa la `libpq` del sistema (paquete `libpq5`, agregado a `deploy/instalar.sh`), que va
enlazada al OpenSSL de Ubuntu y se actualiza con `apt upgrade`. `deploy/actualizar.sh` desinstala psycopg-binary si
quedó de antes, y una prueba nueva (`test_psycopg_usa_la_libpq_del_sistema`) falla si se vuelve a instalar.
La conexión a PostgreSQL y las migraciones no cambian (87 pruebas OK contra PostgreSQL).

Aclaración de la IA: la libpq del sistema se carga en el mismo proceso de Gunicorn, así que no aísla la memoria ni
evita por sí sola un buffer overflow. Lo que gana es que los parches de OpenSSL llegan por apt, en vez de quedar
congelados en la versión embebida de la wheel.

## 9. Pendiente de registrar

- Despliegue en la instancia EC2 y pruebas en la IP pública.
- Guía de estudio para la defensa y preguntas de práctica de la receta.
