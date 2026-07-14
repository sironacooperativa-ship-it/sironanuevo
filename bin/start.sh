#!/usr/bin/env bash
set -euo pipefail

python manage.py migrate
python manage.py createcachetable 2>/dev/null || true
python manage.py collectstatic --noinput
python manage.py ensure_superuser

exec gunicorn coop_manager.wsgi:application --bind 0.0.0.0:${PORT:-8000}

