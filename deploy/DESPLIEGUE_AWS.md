# Despliegue de FitLife en AWS EC2

FitLife corre en la **misma instancia EC2** de la Farmacia B2B (EVA-2), con su propia base de datos, su propio
servicio de Gunicorn y su propio subdominio. La Farmacia no se toca.

```
Navegador ──https──> Nginx (80/443) ──socket Unix──> Gunicorn (3 workers) ──> Django ──> PostgreSQL (5432, local)
                       │
                       └── /static/ lo entrega Nginx directo (collectstatic)
```

| Pieza | FitLife | Farmacia (EVA-2, sin cambios) |
|---|---|---|
| Carpeta | `/home/ubuntu/apps/fitlife` | `/home/ubuntu/apps/farmacia` |
| Servicio | `gunicorn-fitlife.service` | `gunicorn.service` |
| Socket | `/home/ubuntu/apps/fitlife/fitlife.sock` | `/home/ubuntu/apps/farmacia/farmacia.sock` |
| Sitio Nginx | `/etc/nginx/sites-available/fitlife` | `/etc/nginx/sites-available/farmacia` |
| Base PostgreSQL | `fitlife` (rol `fitlife_app`) | `farmacia_b2b` (rol `farmacia_app`) |
| Dominio | `<subdominio>.duckdns.org` | `farmaciab2b-jorge.duckdns.org` |

## Etapas de la receta y cómo se hicieron

| Etapa de la receta | En FitLife |
|---|---|
| 1. Infraestructura (EC2, VPC, grupo de seguridad, IP) | Instancia Ubuntu 24.04 de la EVA-2. Grupo de seguridad: 22 (SSH), 80 (HTTP), 443 (HTTPS). |
| 2. Conexión por SSH | `ssh -i Farmacia.pem ubuntu@<IP>` (la llave con `chmod 400`). |
| 3. Configurar Ubuntu | `apt install python3-venv nginx postgresql git certbot` (paso 1 del script). |
| 4. Proyecto Django + DRF | `git clone` del repositorio, `python3 -m venv venv`, `pip install -r requirements.txt`, `migrate`. |
| 5. Gunicorn con systemd | `deploy/gunicorn-fitlife.service`: 3 workers, socket Unix, `Group=www-data`, `UMask=007`. |
| 6. Nginx como proxy inverso | `deploy/nginx_fitlife.conf`: `proxy_pass` al socket, `include proxy_params`, `/static/` con `alias`. |
| Permisos (solución A) | `www-data` en el grupo `ubuntu`, `chmod 750 /home/ubuntu`, estáticos `ubuntu:www-data`. |
| STATIC_ROOT + collectstatic | `STATIC_ROOT = BASE_DIR / 'staticfiles'` y `collectstatic` (paso 6 del script). |
| 8. Probar y finalizar | `systemctl status gunicorn-fitlife nginx` y `curl` por el socket y por el dominio. |
| Extra: SSL | `certbot --nginx -d <subdominio>.duckdns.org --redirect` (Let's Encrypt, renovación automática). |

## Pasos

1. **DuckDNS:** en <https://www.duckdns.org> (misma cuenta de la Farmacia) crear el subdominio, por ejemplo
   `fitlife-jorge`. No hace falta poner la IP a mano: el script la actualiza.
2. **GitHub:** el repositorio de FitLife tiene que estar subido (`git push`).
3. **Encender el laboratorio de AWS Academy** y conectarse:

   ```bash
   ssh -i Farmacia.pem ubuntu@<IP_PUBLICA>
   git clone <url-del-repositorio> ~/apps/fitlife
   cd ~/apps/fitlife && bash deploy/instalar.sh fitlife-jorge
   ```

   El script hace todo y se puede volver a correr sin romper nada:
   1. Instala los paquetes que falten.
   2. Agrega el subdominio al actualizador de DuckDNS de la instancia (`~/duckdns/duck.sh`, que corre al
      encender y cada 5 minutos). Así el dominio sigue a la IP aunque el laboratorio la cambie.
   3. Crea el `.env` con `DEBUG=False`, una `SECRET_KEY` nueva y una contraseña aleatoria para la base.
   4. Crea el rol `fitlife_app` y la base `fitlife` en el PostgreSQL de la instancia.
   5. Crea el `venv` e instala `requirements.txt`.
   6. `migrate`, `collectstatic` y `cargar_demo` (solo la primera vez).
   7. Instala y arranca `gunicorn-fitlife` y ajusta los permisos para Nginx.
   8. Instala el sitio de Nginx (`nginx -t` antes de recargar).
   9. Saca el certificado con certbot y deja `HTTPS=True` en el `.env`.
   10. Programa `actualizar_membresias` cada hora en el cron (vence las membresías por fecha).
4. **Probar:** `https://fitlife-jorge.duckdns.org` y `http://<IP_PUBLICA>`, que redirige al dominio.

## Actualizar después de un cambio

En el PC: `git push`. En la instancia:

```bash
cd ~/apps/fitlife && bash deploy/actualizar.sh
```

Hace un respaldo de la base en `~/respaldos/`, `git pull`, `pip install`, `migrate`, `collectstatic` y reinicia
`gunicorn-fitlife`.

## Antes de la demostración

```bash
cd ~/apps/fitlife && venv/bin/python manage.py cargar_demo --reset
```

Recarga los datos de prueba relativos a la hora actual: gente dentro del gimnasio, clases de hoy, una clase
llena con lista de espera y socios con membresía vencida y congelada.

## Problemas comunes (tabla de la receta)

| Error | Causa probable | Solución |
|---|---|---|
| 502 Bad Gateway | Gunicorn no creó el socket | `sudo systemctl status gunicorn-fitlife` y `journalctl -u gunicorn-fitlife -n 50` |
| (13) Permission denied | Nginx no llega al socket | `namei -l /home/ubuntu/apps/fitlife/fitlife.sock` (ver solución A) |
| 400 Bad Request | El dominio no está en `ALLOWED_HOSTS` | Revisar `.env` y `sudo systemctl restart gunicorn-fitlife` |
| 403 CSRF en el login | Falta `CSRF_TRUSTED_ORIGINS=https://<dominio>` | Revisar `.env` |
| Sin estilos | Falta `collectstatic` o permisos de `staticfiles` | `bash deploy/actualizar.sh` |
| El dominio no carga | Cambió la IP del laboratorio | `bash ~/duckdns/duck.sh` y `cat ~/duckdns/duck.log` (debe decir OK) |
| Logs | | `sudo tail -n 30 /var/log/nginx/fitlife_error.log` |
