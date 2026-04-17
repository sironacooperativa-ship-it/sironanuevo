@echo off
cd /d "%~dp0"
set "DATABASE_URL="
python listar_usuarios_local.py
pause
