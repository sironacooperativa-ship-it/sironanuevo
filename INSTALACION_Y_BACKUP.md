# Instalación del sistema SIRONA y copias de seguridad

Este documento explica cómo instalar el programa desde cero (por ejemplo desde un `.zip` del código) y cómo usar los backups que genera el **Administrador**.

## 1. Requisitos

- Windows 10/11 (o Linux/macOS con los mismos pasos adaptados al shell).
- Python **3.11 o superior** (recomendado 3.12).
- Conexión a internet la primera vez, para instalar dependencias con `pip`.

## 2. Instalación desde el paquete `.zip` del código

1. Descomprimí el archivo `SIRONA-sistema_....zip` en una carpeta, por ejemplo `C:\SIRONA`.
2. Abrí **PowerShell** en esa carpeta (clic derecho en el fondo de la carpeta → “Abrir en Terminal” o similar).
3. Creá un entorno virtual e instalá dependencias:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

4. Creá la base de datos y un usuario administrador:

```powershell
python manage.py migrate
python manage.py createsuperuser
```

5. Iniciá el servidor local:

```powershell
python manage.py runserver
```

6. En el navegador entrá a `http://127.0.0.1:8000/` e iniciá sesión con el usuario que creaste.

**Nota:** El archivo `db.sqlite3` se crea al hacer `migrate`. Si copiás una base desde otro equipo, reemplazá ese archivo con el servidor detenido.

## 3. Backup que genera el administrador (desde la aplicación)

Un usuario con rol de **staff** (Administrador) puede ir a **Administrador** en el menú y usar **Descargar backup**.

Se descarga un archivo **ZIP** que suele incluir:

| Archivo | Qué es |
|--------|--------|
| `datos.json` | Exportación de los datos (productos, ventas, compras, usuarios, etc.). Sirve en cualquier base (SQLite o PostgreSQL en la nube). |
| `sqlite/sirona.sqlite3` | Solo aparece si el sistema está usando **SQLite** (típico en la PC local). Es una copia exacta del archivo de base. |
| `LEEME_BACKUP.txt` | Texto corto con el mismo resumen. |

No se incluyen sesiones de navegación ni el historial interno del panel admin de Django (tabla `LogEntry`), para aligerar el archivo.

### 3.1 Restaurar en local usando solo SQLite

1. Detené el servidor (`Ctrl+C` en la consola).
2. Hacé una copia de seguridad de tu `db.sqlite3` actual por las dudas.
3. Copiá el archivo `sqlite/sirona.sqlite3` del ZIP y renombralo/reemplazalo como `db.sqlite3` en la carpeta del proyecto (donde está `manage.py`).
4. Volvé a ejecutar `python manage.py runserver`.

También podés usar **Restaurar desde archivo** en Administrador y subir el `.sqlite3` (el del ZIP o uno renombrado).

### 3.2 Restaurar usando `datos.json` (avanzado)

Sirve para importar datos en una base **nueva** o para pasar de un entorno a otro. Requiere consola.

1. Entorno virtual activado y `migrate` ya ejecutado sobre una base vacía o una que quieras **reemplazar por completo** (esto borra datos actuales).

2. Si necesitás vaciar la base manteniendo las tablas:

```powershell
python manage.py flush --no-input
```

(Ojo: `flush` borra **todos** los datos, incluidos usuarios.)

3. Cargá el fixture:

```powershell
python manage.py loaddata datos.json
```

Si aparecen errores de claves duplicadas, la base no estaba vacía: en ese caso conviene una base nueva (`migrate` sobre `db.sqlite3` recién borrado) o revisar el mensaje de error.

En **producción con PostgreSQL**, el backup desde la web suele traer sobre todo `datos.json`; la restauración completa la coordiná con quien mantenga el servidor (a veces implica `loaddata` o herramientas del proveedor de base de datos).

## 4. Hacer tu propio `.zip` del código (para guardar o compartir)

En la carpeta del proyecto hay un script `empaquetar.ps1`. En PowerShell:

```powershell
cd C:\ruta\al\proyecto
.\empaquetar.ps1
```

Se crea un archivo `SIRONA-sistema_fecha_hora.zip` **un nivel arriba** de la carpeta del proyecto (junto a la carpeta que contiene el código). Ese ZIP incluye el código fuente y este tutorial, pero **no** incluye:

- la carpeta `.venv` (hay que volver a crear el entorno),
- `db.sqlite3` (para no mezclar datos personales sin querer),
- `staticfiles` generados,
- cachés `__pycache__`.

Si querés guardar también los datos, usá el backup desde **Administrador** además del ZIP del código.

## 5. Resumen rápido

- **Copia del programa:** `empaquetar.ps1` → ZIP del código + volver a `pip install` y `migrate` en el destino.
- **Copia de lo cargado en el sistema:** Administrador → **Descargar backup** → ZIP con `datos.json` (+ SQLite si aplica).
