---
description: Etapa 3 - sintetiza las voces del guion y mide la duración
argument-hint: nombre-del-video
---
Etapa 3 (voces) del video `videos/$ARGUMENTS/`. Leé `CLAUDE.md`, `guion.md` y `versiones.md`.

1. Sintetizá todas las frases del guion con `motor/voz.py` (voz y velocidad: las del guion; por omisión
   en-US-BrianMultilingualNeural a −3 %).
2. Pasale al usuario una tabla con la duración de cada frase y la duración total del video con las pausas.
3. Marcá las frases con palabras que pueden sonar mal (siglas, nombres en inglés, números, símbolos) y proponé cómo
   escribirlas para que suenen bien. Que escuche los mp3 de `cache/voces/` y apruebe.

Cambiar una frase después mueve todo lo que llega con sus palabras: cerrá las voces ahora. Al terminar, anotá en
`versiones.md` las voces aprobadas y que sigue `/prototipo`.
