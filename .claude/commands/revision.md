---
description: Etapa 6 - aplica una ronda de cambios en una versión nueva
argument-hint: nombre-del-video [cambios]
---
Etapa 6 (revisión) del video. Argumentos: `$ARGUMENTS` (nombre del video y, si vienen, los cambios). Leé `CLAUDE.md`,
`guion.md`, `versiones.md` y `armar.py`.

1. Si el usuario no pasó la lista de cambios, pedísela así: «minuto exacto: qué pasa y qué querés». Ejemplo:
   «0:42: la cámara llega tarde a la tabla; que llegue con "pedidos"».
2. Hacé **solo esos cambios**, sin tocar lo demás. Si uno cambia el guion, actualizá `guion.md` primero.
3. Mostrá cuadros de cada cambio con `VISTAS=` antes de renderizar.
4. Renderizá a la versión siguiente (`v<N+1>.mp4`) y anotá en `versiones.md` la lista de cambios de esta ronda.

Si un cambio no sale en dos intentos, decilo y proponé otra forma: no insistas.
