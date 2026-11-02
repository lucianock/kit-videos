---
description: Crea un video nuevo en videos/<nombre> a partir del ejemplo
argument-hint: nombre-del-video
---
Creá el video `$ARGUMENTS` en `videos/$ARGUMENTS/`:

1. Copiá `ejemplo/armar.py` y `ejemplo/pantallas.json` (no `sitio/`, `pantallas/`, `vistas/` ni `cache/`). En el
   `armar.py` copiado, cambiá el `sys.path.insert` para que apunte a `../../motor`, y dejá las escenas del ejemplo
   como referencia hasta que haya guion.
2. Creá `guion.md` copiando `plantilla-guion.md` y `versiones.md` con una línea: la fecha y «video creado».
3. Contale al usuario, en 3 líneas, que el próximo paso es `/guion $ARGUMENTS` y qué va a necesitar contar: la
   historia real, lo más importante del sistema y qué no se puede mostrar.
