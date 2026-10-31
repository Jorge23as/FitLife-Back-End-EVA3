# FitLife — Control de Asistencia y Reserva de Clases (EVA-3 Backend)

**Alumno:** Jorge Conejeros Suazo · **Sección:** TI3041 · **Año:** 2026
**Caso asignado:** Proyecto 2 — Plataforma de Control de Asistencia y Reserva de Clases (FitLife)

| | |
|---|---|
| **Sitio en AWS EC2** | **https://fitlife-jorge.duckdns.org** |
| **IP pública de la instancia** | **`<IP_PUBLICA>`** · `http://<IP_PUBLICA>` redirige al sitio |
| **Admin de Django** | https://fitlife-jorge.duckdns.org/admin/ |
| **Documentación de la API** | https://fitlife-jorge.duckdns.org/api/docs/ (Swagger, con sesión de recepción o administración) |

> La IP pública de AWS Academy cambia cuando se reinicia el laboratorio. El dominio de DuckDNS se actualiza solo
> (cron en la instancia), así que el enlace del dominio es el que no cambia.

Aplicación web fullstack con **Django REST Framework + PostgreSQL**, desplegada en una instancia **EC2** con
**Gunicorn + Nginx** y SSL de Let's Encrypt. Las páginas son plantillas de Django que **enmascaran la API**: la
vista solo entrega el HTML con `render()` y el JavaScript consume `/api/...` con `fetch()`, enviando el token CSRF.

---

## 1. El problema y cómo lo resuelve

FitLife sufre **congestión en el acceso**, **sobrecupo en clases grupales** e **ingreso de socios con la
membresía vencida**.

| Requerimiento del caso | Cómo se resolvió |
|---|---|
| **1. CRUD de Planes, Pagos y Estados de Membresía** (Activa, Vencida, Congelada) | El **pago crea la membresía** ACTIVA (o la renueva a continuación de la vigente, sin perder días). Pasa a **VENCIDA** sola cuando termina. Se **congela** por N días (tope por plan): esos días se suman al término y se liberan sus cupos en clases. Un pago no se borra: se **anula** y la membresía queda CANCELADA. |
| **2. Acceso con código QR** (lectura o simulación) | Cada socio tiene un **QR dinámico firmado** (cambia cada 30 s y vale 60 s): una captura compartida no sirve. Recepción lo lee con la **cámara** (`BarcodeDetector` o `jsQR`), lo **simula** o lo ingresa a mano. El servidor revisa firma, vigencia, **membresía activa**, **horario**, **aforo** y **anti-passback** (no se entra dos veces sin salir). Todo intento queda registrado. |
| **3. Reserva de clases con cupos y lista de espera** | Reserva **CONFIRMADA** si hay cupo; si no, **EN ESPERA** con su lugar. Al cancelar, **sube solo** el primero de la lista. Sin sobrecupo aunque dos socios reserven al mismo tiempo: `select_for_update()` sobre la clase (probado con 2 hilos). Reglas: membresía que cubra el día de la clase, plan con clases, tope de reservas del plan, sin choque de horario. |
| **4. Aforo en tiempo real** | Dashboard que se actualiza cada 5 s: personas dentro / aforo máximo (medidor), entradas por hora, quién está dentro, clases en curso con su ocupación, rechazos por causa y últimos eventos. El socio ve una versión pública (solo el porcentaje). |

## 2. Tecnologías

| Paquete | Uso |
|---|---|
| Django 6.1 + DRF 3.18 | Framework, API REST, admin, sesiones |
| PostgreSQL 16 + psycopg 3 | Base de datos relacional (`django.db.backends.postgresql`). psycopg usa la `libpq` del sistema (no `psycopg-binary`), así OpenSSL se actualiza con `apt` |
| django-filter | Filtros de la API (`?estado=`, `?desde=`, `?por_vencer=7`...) |
| drf-spectacular | Swagger UI en `/api/docs/` |
| qrcode | QR de acceso en SVG |
| python-dotenv | Credenciales en `.env` (fuera del repositorio) |
| Gunicorn + Nginx | Servidor WSGI y proxy inverso en la EC2 |
| Bootstrap 5 + jsQR (CDN con SRI) | Interfaz responsiva y lector de QR con la cámara |

## 3. Usuarios de prueba

Los crea `python manage.py cargar_demo`.

| Rol | Usuario | Contraseña | Para probar |
|---|---|---|---|
| Administrador | `admin` | `FitLife2026!` | Admin de Django, CRUD de planes y clases, anular pagos |
| Recepción | `recepcion` | `Recepcion2026!` | Control de acceso con QR, aforo, socios, pagos, membresías |
| Instructor | `fmunoz`, `ilagos`, `fvargas`, `raguilera` | `Instructor2026!` | Lista de sus clases y asistencia |
| Socio (membresía activa) | `maria.gonzalez` | `Socio2026!` | Mi cuenta, Mi QR, reservar y cancelar |
| Socio (vencida) | `pedro.rojas` | `Socio2026!` | El QR lo rechaza: "Membresía vencida" |
| Socio (congelada) | `camila.soto` | `Socio2026!` | El QR lo rechaza: "Membresía congelada hasta..." |
| Socio (plan sin clases) | `juan.perez` | `Socio2026!` | No puede reservar clases grupales |
| Socio (Estudiante) | `sofia.morales` | `Socio2026!` | Ya tiene sus 3 reservas permitidas |
| Socio (sin membresía) | `diego.fuentes` | `Socio2026!` | Registrar su primer pago en Gestión → Socios |

Además: una clase **HIIT llena** (6/6) con 3 en lista de espera, donde `maria.gonzalez` tiene cupo; si cancela,
sube `isidora.castillo`.

## 4. Ejecutar en local

```bash
git clone <url-del-repo> fitlife && cd fitlife
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Base de datos (una sola vez)
sudo -u postgres psql -c "CREATE USER fitlife_app WITH PASSWORD 'clave_segura' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE fitlife OWNER fitlife_app;"

cp .env.example .env            # completar DB_PASSWORD (y DB_PORT si no es 5432)
python manage.py migrate        # crea las tablas y los grupos de permisos por rol
python manage.py cargar_demo    # datos de prueba (con --reset vuelve a cargarlos desde cero)
python manage.py runserver
```

Abrir <http://127.0.0.1:8000>. Para crear otro administrador: `python manage.py createsuperuser`.

**Pruebas automatizadas** (84 pruebas: reglas de membresías, QR, reservas y lista de espera, carrera por el
último cupo con 2 hilos, sesiones, CSRF, bloqueo del login, permisos por rol y todas las páginas del admin):

```bash
python manage.py test
```

## 5. Despliegue en AWS EC2

Ubuntu 24.04 + PostgreSQL + Gunicorn (systemd, socket Unix) + Nginx (proxy inverso) + certbot, en la misma
instancia de la EVA-2. Guía paso a paso, relacionada con cada etapa de la receta: [`deploy/DESPLIEGUE_AWS.md`](deploy/DESPLIEGUE_AWS.md).

```bash
git clone <url-del-repo> ~/apps/fitlife
cd ~/apps/fitlife && bash deploy/instalar.sh fitlife-jorge     # primera vez
bash deploy/actualizar.sh                                       # después de cada git push
```

## 6. Estructura

```
fitlife/      settings.py (PostgreSQL, sesiones, CSP, DRF, Swagger), urls.py, formatos/ (fechas y $ de Chile)
cuentas/      Usuario (rol), Socio, Instructor, BloqueoLogin · roles.py (grupos y permisos) · permisos.py · login/logout
membresias/   Plan, Membresia (estado), Congelamiento, Pago · services.py (reglas) · comando actualizar_membresias
clases/       Actividad, Sala, Clase, Reserva (estado) · services.py (cupos, lista de espera, select_for_update)
accesos/      Sede, Visita, RegistroAcceso · qr.py (QR firmado) · services.py (validar acceso, aforo)
core/         vistas que enmascaran la API, admin personalizado, middleware de errores, comando cargar_demo
templates/    base.html, páginas del sitio (web/), páginas de error y plantillas propias del admin (admin/)
static/       js/api.js (fetch + CSRF), css/fitlife.css, css/admin_fitlife.css
deploy/       instalar.sh, actualizar.sh, gunicorn-fitlife.service, nginx_fitlife.conf, DESPLIEGUE_AWS.md
```

Las **reglas de negocio** están en los `services.py`: las usan la API y el admin de Django, así una regla se
cumple igual desde cualquier lado.

## 7. Modelo de datos

```
Usuario(rol) 1─1 Socio      1─N Membresia N─1 Plan
             1─1 Instructor     Membresia 1─N Congelamiento
                                Membresia 1─1 Pago N─1 Socio
Sede 1─N Sala 1─N Clase N─1 Actividad
                  Clase N─1 Instructor
                  Clase 1─N Reserva(estado) N─1 Socio
Sede 1─N Visita N─1 Socio                       (visita abierta = persona dentro -> aforo)
Sede 1─N RegistroAcceso N─1 Socio (null si el QR no sirve)
```

- **Estados con `TextChoices`:** Membresía (ACTIVA, VENCIDA, CONGELADA, CANCELADA), Pago (PAGADO, ANULADO),
  Reserva (CONFIRMADA, ESPERA, CANCELADA, ASISTIO, AUSENTE), Clase (PROGRAMADA, CANCELADA).
- **Integridad en PostgreSQL:** `CheckConstraint` de fechas (término ≥ inicio), `UniqueConstraint` condicional
  (un socio no puede tener dos reservas vigentes en la misma clase, ni dos visitas abiertas), `PROTECT` para no
  borrar planes, socios o membresías con historial.
- **3FN:** los datos del socio y del instructor van en sus perfiles 1:1, no en todos los usuarios. El monto del
  pago se copia del plan al pagar (si el plan cambia de precio, el pago no cambia).

## 8. API (resumen; detalle en `/api/docs/`)

| Rol | Endpoint | Qué hace |
|---|---|---|
| Público | `POST /api/auth/login/` · `POST /api/auth/logout/` | Sesión de Django (login exige token CSRF; 5 fallos = 10 min de bloqueo) |
| Público | `GET /api/planes/` · `GET /api/clases/` · `GET /api/aforo/publico/` | Planes, horario y aforo (sin nombres) |
| Socio | `GET /api/mi-cuenta/` · `GET /api/mi-qr/` | Membresía, reservas, pagos, accesos y QR dinámico |
| Socio / personal | `POST /api/reservas/` · `POST /api/reservas/{id}/cancelar/` | Reservar (cupo o lista de espera) y cancelar |
| Socio / personal | `GET /api/pagos/{id}/` | Datos del comprobante de pago (el socio solo los suyos: el de otro da 404). Página imprimible: `/comprobantes/{id}/` |
| Personal | `/api/socios/` · `/api/pagos/` · `/api/membresias/` (+ `congelar`, `descongelar`) | Gestión diaria de recepción |
| Personal | `POST /api/accesos/validar/` · `GET /api/accesos/` · `/api/visitas/` · `GET /api/aforo/` | Control de acceso y dashboard |
| Instructor / personal | `GET /api/clases/{id}/asistentes/` · `POST /api/reservas/{id}/asistencia/` | Lista de la clase y asistencia |
| Administrador | CRUD `/api/planes/`, `/api/clases/`, `/api/actividades/`, `/api/salas/`, `/api/sedes/`, `POST /api/pagos/{id}/anular/` | Configuración |

## 9. Seguridad

- **Sesiones de Django:** cookie `fitlife_sesion` HttpOnly (el JavaScript no la puede leer), `SameSite=Lax`,
  `Secure` con https. La sesión vive en la tabla `django_session` y vence tras 1 hora sin actividad. El login
  cambia el id de sesión (evita la fijación de sesión) y el logout la borra.
- **CSRF:** toda petición que modifica datos lleva `X-CSRFToken` (también el login).
- **Permisos por rol** en la API (`cuentas/permisos.py`) y en las páginas (el servidor redirige al login o
  muestra la 403). En el admin, cada rol tiene un **grupo de Django** con permisos por modelo: recepción ve
  todo pero no borra ni toca usuarios ni planes; un administrador que no es superusuario no se puede dar el
  superusuario.
- **Fuerza bruta:** 5 intentos fallidos por IP = 10 minutos de bloqueo (en la base, para los 3 workers) y
  límite de Nginx de 10 peticiones por minuto en `/api/auth/`.
- **Contraseñas:** hash PBKDF2 de Django + validador propio de fortaleza (nivel media o superior).
- **QR firmado** con la `SECRET_KEY` y con vencimiento; se puede regenerar si el socio pierde el celular.
- **Content-Security-Policy** con nonce (sin `unsafe-inline` en scripts; botones con `data-accion`), SRI en
  los CDN, HSTS, `X-Frame-Options` y RUT con dígito verificador.
- **Auditoría:** el historial de accesos es de solo lectura; los pagos se anulan, no se borran.

## 10. Admin de Django personalizado

- Portada propia con **indicadores del día** (aforo, membresías activas / por vencer / congeladas, pagos y
  clases de hoy) y colores de FitLife (`templates/admin/`, `static/css/admin_fitlife.css`).
- Todos los modelos registrados con `list_display` (etiquetas de estado de colores, barras de ocupación,
  montos en pesos), `list_filter` (también filtros propios: "vencen en 7 días", "dentro ahora", "membresía
  hoy"), `search_fields`, `date_hierarchy`, `inlines` y `autocomplete_fields`.
- **Acciones** que aplican las reglas: congelar (con página intermedia para los días), descongelar, anular
  pagos, cancelar clases, repetir la semana siguiente, cancelar reservas (sube la lista de espera), registrar
  salidas, regenerar QR.
- Registrar un pago desde el admin crea la membresía (misma regla que la API).

## 11. Uso de inteligencia artificial

Ver [`prompts_ia.md`](prompts_ia.md): consultas hechas a la IA, qué entregó y cómo lo revisé.
