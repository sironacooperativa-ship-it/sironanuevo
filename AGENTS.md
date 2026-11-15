# Sirona: continuidad en nube

Este checkout es un entorno aislado. Usar el checkout existente en `/workspace/sironanuevo`; no crear worktrees salvo pedido explícito. Base de referencia: `main` de `sironacooperativa-ship-it/sironanuevo`.

## Proteger producción

- No acceder ni modificar el servicio `https://sironanuevo-1.onrender.com/`, sus datos ni sus credenciales durante desarrollo.
- No usar `DATABASE_URL` de producción, importar backups/datos, modificar contraseñas ni crear servicios pagos.
- Usar siempre `bash devtools/manage.sh ...`: selecciona settings aislados, elimina DATABASE_URL y fuerza SQLite temporal en `/tmp/sirona-dev-<uid>/db.sqlite3`. Tests usan SQLite en memoria. Media y estáticos generados también quedan fuera del checkout.
- No ejecutar los comandos de Render, restauraciones, migraciones ni comandos administrativos con los settings originales. No crear usuarios persistentes sin un pedido explícito; los tests pueden generar fixtures sintéticos.
- No poner secretos, `.env`, bases, backups, credenciales ni datos reales en Git. El despliegue desde nube se resolverá aparte.
- No publicar cambios funcionales. Guardar configuración de desarrollo en una rama separada; no subir a `main` porque podría disparar un despliegue.

## Comandos desde la raíz del repositorio

Python 3.12 (README admite 3.11+). Dependencias declaradas por el repo sin lockfile; no modificar requirements durante onboarding.

```bash
bash devtools/install.sh
bash devtools/manage.sh check
bash devtools/manage.sh test --noinput
bash devtools/manage.sh migrate --noinput
bash devtools/manage.sh runserver 127.0.0.1:8000 --noreload
```

Comprobar localmente con una petición GET a `/login/`; verificar respuesta y formulario, no solo puerto abierto. No ofrecer URLs de localhost como enlaces utilizables desde iPhone. El acceso remoto al navegador requiere el mecanismo privado de la plataforma; no abrir túneles públicos.

La base temporal puede desaparecer y no es una copia de producción. No reutilizar SQLite del checkout. Los procesos deben reiniciarse en nuevas tareas; una publicación del entorno conserva archivos, no servidores vivos. Revisar privacidad «Solo yo» en la interfaz antes de publicar el entorno. La edición y ejecución en nube no dependen de que la PC esté encendida.
