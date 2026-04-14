# Cooperativa - Gestión (MVP)

Aplicación web multiusuario (login) para gestión básica de una cooperativa.

## Requisitos

- Windows 10/11
- Python 3.11+ instalado (recomendado 3.12)

## Instalación (PowerShell)

En la carpeta del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Abrí `http://127.0.0.1:8000/` y logueate.

## Módulos

- **Inicio**: resumen del estado (MVP).
- **Productos**:
  - Tabla con: código, descripción, tipo, costo, % ganancia (30% por defecto), precio venta (autocalculado, editable).
  - Importación desde Excel.
  - Acciones por ítem: editar, eliminar, deshabilitar, marcar para lista de precios.
  - Exportación a PDF de lista de precios (productos marcados).

## Notas de despliegue (internet)

Para acceso por internet se recomienda desplegar en un VPS o servicio PaaS (p.ej. Render/Fly/Heroku) o en tu servidor con IIS + reverse proxy.

