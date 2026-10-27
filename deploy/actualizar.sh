#!/usr/bin/env bash
# Actualiza FitLife en la instancia después de un "git push" desde el PC.
# Uso: cd ~/apps/fitlife && bash deploy/actualizar.sh
set -euo pipefail
cd "$(dirname "$0")/.."
# respaldo de la base antes de migrar
mkdir -p ~/respaldos
PGPASSWORD=$(grep '^DB_PASSWORD=' .env | cut -d= -f2-) \
    pg_dump -h 127.0.0.1 -U fitlife_app fitlife > ~/respaldos/fitlife_$(date +%Y%m%d_%H%M).sql
echo "Respaldo de la base en ~/respaldos/"
git pull --ff-only
venv/bin/python -m pip install -q -r requirements.txt
venv/bin/python manage.py migrate --noinput
venv/bin/python manage.py collectstatic --noinput -v 0
sudo chown -R ubuntu:www-data staticfiles
sudo systemctl restart gunicorn-fitlife
sleep 2
systemctl is-active gunicorn-fitlife
echo "Actualizado a $(git log --oneline -1)"
