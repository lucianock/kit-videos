# Kit de videos narrados: instrucciones para Claude Code

Este repo sirve para hacer videos de presentación de un sistema (1920×1080, 3-5 min) con voz, cámara de cine sobre
capturas, rótulos animados, subtítulos, música y efectos. Cada video vive en `videos/<nombre>/` y se arma con un
`armar.py` propio que usa el motor de `motor/`. El modelo de todo es `ejemplo/armar.py`: leelo antes de escribir una
escena.

## Cómo trabajar

- **El guion manda.** Nada se programa si no está en `videos/<nombre>/guion.md` (formato de `plantilla-guion.md`). Si
  el usuario pide algo que cambia la historia, primero se actualiza el guion.
- **Una etapa por vez** (las 7 de `METODO.md`). Al empezar cada sesión, leé `guion.md` y `versiones.md` del video; al
  terminar, anotá en `versiones.md` qué se hizo, qué decidió el usuario y qué falta. Las sesiones se
  pueden cortar: todo lo importante tiene que quedar en archivos.
- **Revisá con cuadros sueltos antes de renderizar**: `VISTAS=t1,t2,… python armar.py` deja PNG en `vistas/`.
  Miralos vos (armá una hoja de contacto) y mostráselos al usuario. Un render entero solo cuando la escena aprobó.
- **Nunca pises una versión**: cada render va a `v<N>.mp4`.
- **Si algo no sale en dos intentos, pará** y proponé otra idea o volver a la versión anterior. No insistas sobre lo
  mismo: gasta el uso del usuario.
- Respetá las **reglas de calidad** de `METODO.md`. Las más importantes: primero la historia; la cámara *llega* con la
  palabra; se despega el elemento mismo, no un recuadro dibujado; pantalla llena; pausas para leer; nada de desenfoques
  decorativos; subtítulos grandes.
- **Datos**: solo entornos de prueba con datos inventados. Si una captura muestra algo sensible (IPs reales, clientes,
  correos, tokens), avisá antes de usarla. Nunca escribas contraseñas: si hay que ingresar, `captura.py --ventana` y el
  usuario inicia sesión.
- Hablá con el usuario en castellano, simple y corto. Mostrá resultados (cuadros, duraciones), no código, salvo que
  lo pida.

## Comandos

Siempre con el Python del entorno del kit, desde la carpeta del video (`videos/<nombre>/`):

```bat
..\..\.venv\Scripts\python ..\..\motor\captura.py pantallas.json      :: capturas a ×2 + cajas (pantallas/)
..\..\.venv\Scripts\python ..\..\motor\voz.py "frase 1" "frase 2"     :: probar voces y ver sus marcas
set VISTAS=2,6.5,12 && ..\..\.venv\Scripts\python armar.py             :: cuadros sueltos en vistas/
..\..\.venv\Scripts\python armar.py                                    :: render (30 fps; FPS=60 opcional)
```

En la carpeta del video, `armar.py` busca el motor en `../../motor` (ajustá `sys.path.insert` si lo copiaste del
ejemplo: allá es `../motor`).

## El motor, en una página

Todo en px CSS de las capturas (las capturas son ×2: `C.Imagen(im, ss=2)`). Tiempos en segundos del video.

**Voz** (`motor/voz.py`): `j = voz.Linea(texto, t0)` → `j.en('palabra')` (segundo en que empieza esa palabra;
`n=2` para la segunda), `j.v0`, `j.fin`, `j.pcm`. Voz y velocidad: variables `VOZ`, `VELOCIDAD` (−3 % por omisión).
Primero se ponen las frases; todo lo demás se acomoda a sus palabras.

**Escena y cámara** (`motor/cine10.py`, `motor/mov10.py`):

```python
esc = C.Escena(fps=FPS)
pag = C.ventana(esc, C.Imagen(Image.open('pantallas/inicio.png'), ss=2), x, y, 'Título de la ventana')
lleno = C.encuadre_completo(pag, arriba=C.BARRA_VENTANA)            # la página a pantalla llena
esc.cam.pos.ir(t, lleno, dur, 'cine')                               # curvas: suave, cine, sale, entra, latigo, scroll
esc.cam.incl.ir(t, (rx, ry), dur, 'cine'); esc.cam.giro.ir(t, grados, dur)   # inclinación 3D y giro
enc = esc.encuadre(pag, (x0, y0, x1, y1), margen=0.08, zmax=2.2)    # encuadre de una caja de la captura
esc.cam.resorte(M.aterrizar_resorte(j.en('palabra'), 0.95, 0.96), enc, 0.95, 0.96)   # llega CON la palabra
el = esc.elevar(t0, t1, pag, caja, escala=1.07, atenuar=0.4, desenfoque=6)          # el elemento se despega
pag.sombra.opacidad.ir(t, 0.0, 0.6, 'suave')                        # apagar la sombra de la ventana flotante
```

Varias páginas: cada una en su `C.ventana` en otra `x` del mundo (por ejemplo `1920 + 260`) y un latigazo
`esc.cam.pos.ir(t, C.encuadre_completo(otra, arriba=C.BARRA_VENTANA), 0.62, 'latigo')`. Scroll real:
`C.PaginaDesplazable`. Números que cuentan: `C.Contador`. Una toma de video (cuadros PNG): `C.Secuencia`.

**Cajas** (`motor/captura.py`): `captura.caja('pantallas', 'inicio', 'Texto visible', ['article'])` → `(x0, y0, x1, y1)`
del elemento más chico que contiene ese texto (tags opcionales: `tr`, `section`, `article`, `button`, `h2`…).

**Rótulos y llamadas** (`motor/mg10.py`, plantillas en `motor/mg10/plantillas/`):

```python
rot = G.sprite('rotulo', dict(numero='01', kicker='ANTETÍTULO', titulo='Título', bajada='Bajada', dur=2.4), FPS)
esc.en_pantalla(rot, t, 64, 58)                                     # fijo en pantalla
ll = G.sprite('llamada', dict(texto='<b>92 %</b> de la meta', detalle='…', dir='izq-abajo', codo=70, largo=60,
                              dur=2.4), FPS)
esc.anclar(ll, t, pag, (x, y), sobre=el)                            # pegado a un punto de la captura (sigue a la elevación)
d.sprites += [rot, ll]; G.preparar(d.sprites)                       # se filman en Chrome una vez y quedan en caché
```

Plantillas: `rotulo` (numero, kicker, titulo, bajada, dur), `llamada` (texto, detalle, dir, codo, largo, dur),
`dato` (valor, etiqueta, detalle, formato, sufijo, dur: un número grande que cuenta), `capitulo` (numero, titulo, dur).
Una plantilla nueva: copiá una de `mg10/plantillas/` (HTML + anime.js con `window.__mg`).

**Sonido** (`motor/sonido6.py`): `d.sfxs.append((t, nombre, ganancia, pan, dur))` con nombres de `S6.ORDEN` (clic,
tecla, enter, pop, whoosh, whoosh_corto, swish, impacto, ping, notif, sello, conteo, llega, titulo, acorde…); para que
el golpe caiga en `t`: `t - S6.DESFASES[nombre]`. Música: `d.musica_secciones = [(t0, 'liviano'), (t1, 'epico'), …]`
(calido, tension, pulso, liviano, epico, final). Mezcla: `S6.mezcla6(d, 'mezcla.wav')` con `d.total`, `d.voces`,
`d.sfxs`, `d.musica_secciones`, `d.stings`.

**Cuadro final**: `img = esc.cuadro(t)`, `img = subs.dibujar(img, t)` (`motor/subtitulos.py`),
`img = post6.acabado(img, t, grano=0.6)` y fundidos al principio y al final. El render en paralelo y el armado del mp4
están en `ejemplo/armar.py` (`main()`).
