---
description: Etapa 5 - agrega una escena del guion a armar.py
argument-hint: nombre-del-video escenas (por ejemplo: demo A1-A4)
---
Etapa 5 (escena por escena). Argumentos: `$ARGUMENTS` (nombre del video y las escenas del guion a agregar). Leé
`CLAUDE.md`, `guion.md`, `versiones.md` y el `armar.py` actual del video.

1. Agregá **solo esas escenas** a `armar.py`, con los mismos recursos y el mismo estilo que el prototipo aprobado, sin
   tocar las escenas que ya aprobó el usuario.
2. Mostrá cuadros en los momentos clave (cada palabra que mueve algo, cada transición) con `VISTAS=` y una hoja de
   contacto. Revisalos vos primero: textos que se cortan, elementos tapados por los subtítulos, cámara que no llega.
3. Esperá el OK del usuario antes de renderizar. El render va a `v<N>.mp4` (nunca pises uno anterior).

Al terminar, anotá en `versiones.md` qué escenas quedaron y cuáles faltan.
