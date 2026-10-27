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

## 6. Pendiente de registrar

- Despliegue en la instancia EC2 y pruebas en la IP pública.
- Guía de estudio para la defensa y preguntas de práctica de la receta.
