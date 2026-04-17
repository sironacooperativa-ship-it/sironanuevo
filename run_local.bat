@echo off
REM Fuerza SQLite local (db.sqlite3) ignorando DATABASE_URL del sistema.
cd /d "%~dp0"
set "DATABASE_URL="
set "DEBUG=1"
echo.
echo === Local: SQLite en esta carpeta (DATABASE_URL vacia en esta ventana) ===
echo.
python manage.py runserver %*
