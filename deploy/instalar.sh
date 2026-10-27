#!/usr/bin/env bash
# Instalación de FitLife en la instancia EC2 (Ubuntu 24.04) donde ya corre
# la Farmacia de la EVA-2. Hace las ETAPAS 3 a 8 de la receta y el SSL.
#
# Antes: crear el subdominio en https://www.duckdns.org (ej. fitlife-jorge).
# Uso (conectado por ssh como ubuntu):
#   git clone <url-del-repo> ~/apps/fitlife
#   cd ~/apps/fitlife && bash deploy/instalar.sh fitlife-jorge
#
# Se puede volver a correr: no pisa el .env, la base ni la config de Nginx
# que ya tenga el certificado. Para actualizar el código: deploy/actualizar.sh
set -euo pipefail

SUB=${1:?"Indique el subdominio de DuckDNS, ej: bash deploy/instalar.sh fitlife-jorge"}
DOMINIO="$SUB.duckdns.org"
APP=$(cd "$(dirname "$0")/.." && pwd)
cd "$APP"

echo "==> 1. Paquetes (ya deberían estar por la Farmacia)"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip nginx postgresql git curl certbot python3-certbot-nginx >/dev/null

echo "==> 2. DuckDNS: $DOMINIO tiene que apuntar a esta instancia"
DUCK=~/duckdns/duck.sh
RESPALDO=""
if [ -f "$DUCK" ] && ! grep -q "$SUB" "$DUCK"; then
    if grep -q 'domains=' "$DUCK"; then
        RESPALDO="$DUCK.respaldo_$(date +%Y%m%d_%H%M)"
        cp "$DUCK" "$RESPALDO"
        # se agrega el subdominio a la lista que actualiza el cron (cada 5 min y al encender)
        sed -i -E "s/domains=([^&\"' ]+)/domains=\1,$SUB/" "$DUCK"
        echo "    agregado $SUB a $DUCK"
    else
        echo "    OJO: no encontré 'domains=' en $DUCK; agregue $SUB a mano"
    fi
fi
if [ -f "$DUCK" ]; then
    bash "$DUCK"
    if [ "$(cat ~/duckdns/duck.log 2>/dev/null)" != "OK" ]; then
        # DuckDNS rechaza TODA la lista si un subdominio no es de la cuenta: se vuelve atrás
        # para no dejar sin actualizar el dominio de la Farmacia
        echo "    OJO: DuckDNS respondió KO. ¿Creó el subdominio $SUB en duckdns.org con la misma cuenta?"
        [ -n "$RESPALDO" ] && cp "$RESPALDO" "$DUCK" && bash "$DUCK" && echo "    se restauró $DUCK"
        exit 1
    fi
    echo "    DuckDNS actualizado (OK)"
fi
IP_PUBLICA=$(curl -s https://checkip.amazonaws.com || true)
echo "    IP pública: $IP_PUBLICA · $DOMINIO resuelve a: $(getent hosts "$DOMINIO" | awk '{print $1}')"

echo "==> 3. Archivo .env"
PRIMERA_VEZ=no
if [ ! -f .env ]; then
    PRIMERA_VEZ=si
    DB_PASS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
    umask 077
    cat > .env <<FIN
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')
DEBUG=False
ALLOWED_HOSTS=${DOMINIO},localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://${DOMINIO}
DB_NAME=fitlife
DB_USER=fitlife_app
DB_PASSWORD=${DB_PASS}
DB_HOST=127.0.0.1
DB_PORT=5432
# pasa a True cuando certbot entrega el certificado (paso 9)
HTTPS=False
FIN
    umask 022
    echo "    .env creado"

    echo "==> 4. Base de datos PostgreSQL (rol y base propios, la de la Farmacia no se toca)"
    sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<FIN
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fitlife_app') THEN
    CREATE ROLE fitlife_app LOGIN PASSWORD '${DB_PASS}';
  ELSE
    ALTER ROLE fitlife_app PASSWORD '${DB_PASS}';
  END IF;
END \$\$;
FIN
    sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='fitlife'" | grep -q 1 \
        || sudo -u postgres createdb -O fitlife_app fitlife
else
    echo "    .env ya existe, no se toca"
fi

echo "==> 5. Entorno virtual y dependencias"
[ -d venv ] || python3 -m venv venv
venv/bin/python -m pip install -q --upgrade pip
venv/bin/python -m pip install -q -r requirements.txt

echo "==> 6. Migraciones, estáticos y datos de prueba"
venv/bin/python manage.py migrate --noinput
venv/bin/python manage.py collectstatic --noinput -v 0
if [ "$PRIMERA_VEZ" = si ]; then
    venv/bin/python manage.py cargar_demo
fi

echo "==> 7. Gunicorn (servicio gunicorn-fitlife)"
sudo cp deploy/gunicorn-fitlife.service /etc/systemd/system/gunicorn-fitlife.service
sudo systemctl daemon-reload
sudo systemctl enable -q gunicorn-fitlife
sudo systemctl restart gunicorn-fitlife
# Nginx (www-data) tiene que llegar al socket y a /static/ (solución A de la receta)
sudo usermod -aG ubuntu www-data
sudo chmod 750 /home/ubuntu
sudo chown -R ubuntu:www-data staticfiles
sudo chmod -R 750 staticfiles

echo "==> 8. Nginx"
SITIO=/etc/nginx/sites-available/fitlife
if [ ! -f "$SITIO" ]; then
    sed "s/DOMINIO/$DOMINIO/g" deploy/nginx_fitlife.conf | sudo tee "$SITIO" >/dev/null
    # si otro sitio ya es el "default_server" del puerto 80, este no lo reclama
    if sudo grep -lq 'listen 80 default_server' /etc/nginx/sites-enabled/* 2>/dev/null; then
        sudo sed -i 's/listen 80 default_server;/listen 80;/' "$SITIO"
        echo "    otro sitio ya atiende la IP; FitLife queda solo en $DOMINIO"
    fi
fi
sudo ln -sf "$SITIO" /etc/nginx/sites-enabled/fitlife
sudo nginx -t
sudo systemctl reload nginx

echo "==> 9. Certificado SSL (Let's Encrypt)"
if sudo certbot certificates 2>/dev/null | grep -q "Domains: $DOMINIO"; then
    echo "    ya existe el certificado de $DOMINIO"
elif sudo certbot --nginx -d "$DOMINIO" --non-interactive --agree-tos --redirect \
        --register-unsafely-without-email --keep-until-expiring; then
    echo "    certificado instalado"
else
    echo "    OJO: certbot falló (¿$DOMINIO apunta a $IP_PUBLICA? ¿puerto 80 y 443 abiertos?). El sitio sigue en http."
fi
if sudo certbot certificates 2>/dev/null | grep -q "Domains: $DOMINIO"; then
    sed -i 's/^HTTPS=False/HTTPS=True/' .env
    sudo systemctl restart gunicorn-fitlife
fi

echo "==> 10. Cron: estados de membresía al día (cada hora)"
( crontab -l 2>/dev/null | grep -v 'actualizar_membresias' ;
  echo "5 * * * * cd $APP && venv/bin/python manage.py actualizar_membresias >> $APP/cron.log 2>&1" ) | crontab -

echo "==> Verificación"
sleep 2
systemctl is-active gunicorn-fitlife nginx postgresql
curl -s -o /dev/null -w "    Gunicorn por el socket: HTTP %{http_code}\n" -H "Host: localhost" -H "X-Forwarded-Proto: https" \
    --unix-socket "$APP/fitlife.sock" http://localhost/api/aforo/publico/
curl -s -o /dev/null -w "    $DOMINIO por Nginx: HTTP %{http_code}\n" "https://$DOMINIO/" || true
echo
echo "Listo: https://$DOMINIO   (admin: https://$DOMINIO/admin/)"
