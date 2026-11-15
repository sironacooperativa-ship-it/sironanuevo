#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
unset DATABASE_URL
export DJANGO_SETTINGS_MODULE=devtools.settings
exec .venv/bin/python manage.py "$@" --settings=devtools.settings
