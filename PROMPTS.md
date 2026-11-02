# Prompts para Claude Code, etapa por etapa

Pegalos en Claude Code abierto en la carpeta de tu video (una copia de `ejemplo/` dentro del kit). Cambiá lo que está
entre `< >`. **Una etapa por sesión**: todo queda en archivos y la sesión siguiente arranca leyéndolos.

---

## 0. Arranque (al principio de cada sesión)

```
Estoy haciendo un video narrado con el kit de esta carpeta (motor en ../motor). Antes de hacer nada, leé
../README.md, ../METODO.md, guion.md (si existe), versiones.md (si existe) y armar.py. Respetá las reglas de calidad
de METODO.md. Trabajá solo en la etapa que te pido, mostrame cuadros sueltos (VISTAS=) antes de renderizar todo, y
al terminar anotá en versiones.md qué hiciste y qué falta.
```

## 1. Historia y guion

```
Quiero un video de <3-4> minutos para <la presentación / el público> que muestre <el sistema>. La historia real que
quiero contar es: <qué pasó, quién, qué hizo el sistema, cuál fue el giro>. Lo más importante del sistema es:
<6 a 10 cosas>. No se puede mostrar: <datos sensibles, funciones sin terminar>.

Primero haceme las preguntas que necesites (de a una). Después escribí guion.md con el formato de
../plantilla-guion.md: primero la historia (60-90 s), después el recorrido y un cierre humano. Calculá la duración
con 155 palabras por minuto más las pausas. No escribas código todavía.
```

Leelo en voz alta. Pedí cambios hasta que te guste («la frase P4 es muy técnica», «sacá la parte de usuarios»).

## 2. Entorno y capturas

```
Según guion.md, armá pantallas.json con cada pantalla que hace falta (nombre, url, y los clics para llegar si hay
pestañas) y sacá las capturas con ../motor/captura.py. El entorno de prueba está en <URL> con datos inventados
<si hace falta ingresar: usá --ventana y yo inicio sesión>. Después mostrame una hoja de contacto con todas las
capturas y decime si alguna tiene algo sensible, sale cortada o le falta un dato que pide el guion.
```

## 3. Voces

```
Sintetizá todas las frases de guion.md con motor/voz.py (voz <en-US-BrianMultilingualNeural>, velocidad -3 %) y
pasame una tabla con la duración de cada una y la duración total del video con las pausas. Si alguna frase tiene
una palabra que puede sonar mal (siglas, nombres en inglés, números), proponé cómo escribirla para que suene bien.
```

Escuchá los mp3 de `cache/voces/`. Cambiá ahora lo que suene raro: después mueve todo.

## 4. Prototipo de 15-20 segundos

```
Armá un prototipo de 15-20 s con la escena <P2> del guion, siguiendo ejemplo/armar.py: entrada en 3D de la ventana,
rótulo animado, la cámara que llega con la palabra <"…">, el elemento <…> que se despega con <"…"> y una llamada.
Música y efectos con sonido6. Mostrame 6 cuadros con VISTAS= y después renderizá el prototipo.
```

Si el prototipo no te convence, corregilo acá: es la parte barata.

## 5. Escena por escena

```
Agregá a armar.py la escena <A1-A4> del guion (todavía no las demás). Mismos recursos que el prototipo. Mostrame
cuadros en <los segundos clave> y esperá mi OK antes de renderizar.
```

## 6. Revisión

Mirá el video entero y anotá con el minuto exacto. Después:

```
Versión <3>, cambios:
- <0:42>: la cámara llega tarde a la tabla; que llegue con "pedidos".
- <1:15-1:30>: va muy rápido; 1,5 s de pausa después de P6 para leer la tabla.
- <2:05>: la llamada tapa el número; ponela arriba.
Hacé solo eso, sin tocar lo demás, guardá como v<4>.mp4 y anotá los cambios en versiones.md.
```

## 7. Entrega

```
Renderizá la versión final a 1920×1080 y 30 fps (H.264, CRF 17-19, unos 100 MB para 5 minutos) y comprobá la
duración, el peso y el audio (que la voz no sature). Escribí en versiones.md cuál es la final.
```

Después: copiala al disco de la computadora de la presentación y miralo entero en el proyector.

---

## Si algo sale mal

- **«Quedó genérico, no se parece a lo que quiero»**: volvé al guion. Casi siempre falta la historia o hay demasiadas
  funciones.
- **La sesión se cortó**: abrí otra y pegá el prompt 0. Por eso se trabaja de a una etapa.
- **Un efecto no sale en dos intentos**: pedí volver a la versión anterior y probar otra idea.
- **Algo del motor no anda** (una plantilla, Chrome, ffmpeg): pegá el error completo y pedí que lo arregle sin
  cambiar el resto.
