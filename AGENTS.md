# Sirona: continuidad en nube

Este checkout es un entorno aislado. Usar el checkout existente en `/workspace/sironanuevo`; no crear worktrees salvo pedido explícito. Base de referencia: `main` de `sironacooperativa-ship-it/sironanuevo`.

## Proteger producción

- No acceder ni modificar el servicio `https://sironanuevo-1.onrender.com/`, sus datos ni sus credenciales durante desarrollo.
- No usar `DATABASE_URL` de producción, importar backups/datos, modificar contraseñas ni crear servicios pagos.
- Usar siempre `bash devtools/manage.sh ...`: selecciona settings aislados, elimina DATABASE_URL y fuerza SQLite temporal en `/tmp/sirona-dev-<uid>/db.sqlite3`. Tests usan SQLite en memoria. Media y estáticos generados también quedan fuera del checkout.
- No ejecutar los comandos de Render, restauraciones, migraciones ni comandos administrativos con los settings originales. No crear usuarios persistentes sin un pedido explícito; los tests pueden generar fixtures sintéticos.
- No poner secretos, `.env`, bases, backups, credenciales ni datos reales en Git. No copiar claves de Render al entorno.
- Esta integración solo autoriza configuración de desarrollo y CI, sin cambios funcionales.
- Cambios futuros pedidos por Juan: ejecutar instalación/pip check, Django check y todas las pruebas con SQLite aislado antes de push a `main`. Si falla algo, no hacer push. Revisar diff y preservar cambios ajenos; nunca force push.
- El servicio existente `sironanuevo-1` seguirá conectado a `main`, con Render configurado por Juan en «After CI Checks Pass». Después del push, comprobar GitHub Actions para el SHA exacto. Render se encarga del despliegue tras CI; no crear servicios ni ejecutar despliegues manuales. Un CI correcto no prueba que Render haya desplegado correctamente.

## Comandos desde la raíz del repositorio

Python 3.12 (README admite 3.11+). Dependencias declaradas por el repo sin lockfile; no modificar requirements durante onboarding.

```bash
bash devtools/sync-main.sh
bash devtools/install.sh
bash devtools/manage.sh check
bash devtools/manage.sh test --noinput
bash devtools/manage.sh migrate --noinput
bash devtools/manage.sh runserver 127.0.0.1:8000 --noreload
```

Comprobar localmente con una petición GET a `/login/`; verificar respuesta y formulario, no solo puerto abierto. No ofrecer URLs de localhost como enlaces utilizables desde iPhone. El acceso remoto al navegador requiere el mecanismo privado de la plataforma; no abrir túneles públicos.

Al comenzar tareas nuevas, `sync-main.sh` hace `git fetch origin main` y solo permite avance rápido seguro. Si hay cambios sin commit, HEAD separado, commits propios o divergencia, se detiene sin borrarlos; integrar después de revisar. No usar reset --hard, clean, force ni stash automático. La instalación no sincroniza el código por su cuenta: el install_script del entorno ejecuta primero esta sincronización.

La base temporal puede desaparecer y no es una copia de producción. No reutilizar SQLite del checkout. Los procesos deben reiniciarse en nuevas tareas; una publicación del entorno conserva archivos, no servidores vivos. Juan verificó privacidad «Solo yo» en la interfaz. La edición y ejecución en nube no dependen de que la PC esté encendida.
