# El método

Las etapas y las reglas para que el video salga bien.

## Las etapas

| # | Etapa | Qué sale | Cuándo se pasa a la siguiente |
|---|---|---|---|
| 1 | **Historia y guion** | `guion.md` (ver `plantilla-guion.md`): frase por frase, qué se ve y cuánto dura | Cuando lo leés en voz alta y te gusta. Recién ahí se toca código |
| 2 | **Entorno y capturas** | `pantallas/` con capturas a ×2 de un entorno de prueba con datos inventados | Cuando cada pantalla del guion tiene su captura y se ve bien a pantalla completa |
| 3 | **Voces** | Todas las frases sintetizadas y escuchadas | Cuando ninguna palabra suena rara. Cambiar una frase después mueve todo lo que llega con sus palabras |
| 4 | **Prototipo de 15-20 s** | Una sola escena terminada, con todo: cámara, rótulo, elevación, voz, música | Cuando el *look* te convence. Es la prueba barata de que el video va a estar bien |
| 5 | **Escena por escena** | `armar.py` crece de a una escena; cada una se revisa con `VISTAS=` antes de seguir | Cuando la escena aprueba. **Una escena por sesión** |
| 6 | **Rondas de revisión** | Una versión nueva por ronda (`v1.mp4`, `v2.mp4`… nunca se pisa una vieja) | Cuando una ronda ya no tiene pedidos importantes |
| 7 | **Entrega** | El archivo final a 30 fps, probado en la computadora de la presentación | — |

## Reglas de calidad

**Historia**

- **Primero la historia, después el producto.** Un caso real, contado en 60-90 segundos, y recién ahí el recorrido.
  Las versiones que empezaban por las funciones aburrían.
- **No vender lo mundano como gran función.** Elegí 6-10 cosas que de verdad importan; el resto se nombra de pasada.
- **Dejá respirar.** Unos segundos sin voz para mirar y leer la pantalla. Voz al −3 % (≈ 155 palabras por minuto).
- **Cerrá con algo humano**, no con una lista de funciones.

**Imagen**

- **Capturas a ×2** (3840 px de ancho). Los acercamientos con capturas de 1920 se ven borrosos.
- **La cámara llega con la palabra**, no arranca en la palabra (`mov10.aterrizar`). Esto solo ya hace que se vea
  profesional.
- **Se despega el elemento mismo**, recortado de la captura, no un recuadro dibujado encima: un recuadro aparte queda
  corrido y se nota.
- **Pantalla llena.** El sistema ocupa los 1920 px de ancho; nada de ventanas chiquitas en el medio.
- **Movimientos con resorte y desenfoque de movimiento real**: la cámara nunca frena en seco.
- **Nada de desenfoques decorativos** sobre todo el cuadro. Desenfoque solo en lo que se tapa y en lo que queda detrás de
  un elemento despegado.
- **Rótulos y llamadas con la letra y los colores del sistema** que se presenta (`mg10/plantillas/base.css`).
- **Subtítulos grandes** (46 px): en un proyector, lo chico no se lee.

**Sonido**

- Voz al frente (−17 dBFS), música que baja sola cuando habla la voz, efectos chicos en cada clic, golpe y transición.
  `sonido6.mezcla6` ya lo hace: no hace falta un editor de audio.

**Trabajo con Claude**

- **El guion manda.** Todo lo que se ve se escribe primero en `guion.md`. Si cambia el guion, cambia el código, no al
  revés.
- **Pedidos de revisión con tiempo exacto y qué querés**: «en el 1:12 la cámara llega tarde a la tabla; que llegue con
  "pedidos"». «Mejoralo» no sirve.
- **Una versión por archivo y un registro de cambios** (`versiones.md`), para poder volver atrás.
- **Revisá cuadros sueltos antes de renderizar** (`VISTAS=`): es mucho más barato que un render entero.
- **Si una idea no sale en dos intentos, volvé atrás** y probá otra cosa. Insistir sobre lo mismo gasta uso y no mejora.

**Entrega**

- Para proyectar: **30 fps**, H.264, unos 100 MB para 5 minutos. El de 60 fps solo si se probó entero en esa
  computadora.
- **Reproducilo desde el disco de la computadora de la presentación**, nunca desde un pendrive, la red o la nube.
- Probalo **entero** en esa computadora, con el proyector, antes del día.
- Armá la versión final recién cuando las funciones que mostrás estén terminadas: si cambian, hay que volver a filmar.
