@echo off
cd /d "%~dp0"
set "DATABASE_URL="
set "DEBUG=1"
echo Creando usuario en db.sqlite3 de esta carpeta...
python manage.py createsuperuser
