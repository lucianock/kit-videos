---
description: Etapa 2 - saca las capturas a x2 de las pantallas del guion
argument-hint: nombre-del-video
---
Etapa 2 (entorno y capturas) del video `videos/$ARGUMENTS/`. Leé `CLAUDE.md`, `guion.md` y `versiones.md`.

1. Armá `pantallas.json` con cada pantalla que pide el guion: `nombre`, `url` y, si hace falta, `clics` (textos de
   botones o pestañas para llegar) y `espera`. Preguntá la URL del entorno de prueba si no está en el guion.
2. Sacá las capturas desde la carpeta del video con `..\..\.venv\Scripts\python ..\..\motor\captura.py pantallas.json`.
   Si el sistema pide ingreso, usá `--ventana` y que el usuario inicie sesión: vos no escribas contraseñas.
3. Armá una hoja de contacto (todas las capturas chicas en una imagen), miralas y mostrásela al usuario. Avisá si
   alguna tiene datos sensibles (IPs reales, clientes, correos, tokens), sale cortada o le falta lo que pide el guion.
4. Verificá que cada caja que el guion va a usar exista en los JSON (`captura.caja`).

Al terminar, anotá en `versiones.md` las capturas aprobadas y que sigue `/voces`.
