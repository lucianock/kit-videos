# Kit de videos narrados

Motor y método para hacer videos de presentación de un sistema (un panel, una app, un sitio) con Claude Code: voz
narrada, cámara sobre las pantallas reales, rótulos animados, subtítulos, música y efectos. 1920×1080, 3-5 minutos.

```
Tu sistema (entorno de prueba)                         Video de 3-5 min, 1920×1080
        │                                                        ▲
        ▼                                                        │
  captura.py ── capturas a ×2 + cajas de cada elemento           │
  voz.py ────── voz narrada con la marca de cada palabra         │
  guion.md ──── qué se ve, qué se dice y con qué palabra llega   │
        │                                                        │
        ▼                                                        │
  armar.py ──── cine10 (cámara 3D, resortes, desenfoque de movimiento, elevaciones)
                mg10   (rótulos y llamadas en HTML + anime.js)   │
                sonido6 (música y efectos sintetizados) ─────────┘
```

## Qué esperar

El kit trae el motor y el método; el video lo hacés vos. Lo que más pesa en el resultado no viene incluido:

- **La historia.** Un caso real que enganche vale más que cualquier efecto.
- **La coreografía.** Qué se muestra, en qué palabra llega la cámara, qué se despega, cuánto se deja leer.
- **Las rondas de revisión.** Un buen video lleva entre 5 y 20, con pedidos concretos («en el 2:55 la transición queda
  fea»).

Contá con varios días para un video de 3 a 5 minutos. Un video hecho de una sola pasada, sin prototipo ni revisiones,
sale mal: para eso está `METODO.md`.

## Instalar (Windows, una vez)

Necesitás [Python 3.11+](https://www.python.org/downloads/), [Node.js](https://nodejs.org/), Google Chrome y conexión
la primera vez (para las voces).

```bat
git clone https://github.com/lucianock/kit-videos.git
cd kit-videos
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd motor\mg10 && npm install && cd ..\..
```

Si Chrome no está en `C:\Program Files\Google\Chrome\Application\chrome.exe`, poné su ruta en la variable `CHROME`.

## Probar el ejemplo

```bat
cd ejemplo
..\.venv\Scripts\python ..\motor\captura.py pantallas.json
..\.venv\Scripts\python armar.py
```

Sale `ejemplo\ejemplo.mp4`: 18 segundos sobre un panel de ventas inventado. Tarda unos 3 minutos.

## Hacer un video con Claude Code

Abrí Claude Code en la carpeta del kit. Lee solo el `CLAUDE.md` y tiene estos comandos:

| Comando | Qué hace |
|---|---|
| `/nuevo-video nombre` | Crea `videos/nombre/` a partir del ejemplo |
| `/guion nombre` | Te entrevista y escribe el guion |
| `/capturas nombre` | Saca las capturas a ×2 y te muestra una hoja de contacto |
| `/voces nombre` | Sintetiza las frases y te pasa las duraciones |
| `/prototipo nombre` | Una escena terminada de 15-20 s para validar el *look* |
| `/escena nombre A1-A4` | Agrega una escena a `armar.py` |
| `/revision nombre` | Aplica una lista de cambios en una versión nueva |
| `/entrega nombre` | Render final a 30 fps |

Un comando por sesión: cada uno arranca leyendo `guion.md` y `versiones.md`, así que cerrar la sesión no pierde nada.
Los mismos pasos, como prompts para copiar, están en `PROMPTS.md`.

## Qué hay adentro

| Ruta | Qué es |
|---|---|
| `CLAUDE.md`, `.claude/commands/` | Instrucciones y comandos para Claude Code |
| `METODO.md` | Las 7 etapas y las reglas de calidad |
| `PROMPTS.md` | Los pasos como prompts para copiar |
| `plantilla-guion.md` | Formato de guion: frase, qué se ve y con qué palabra llega |
| `motor/cine10.py` | Cámara virtual 3D: resortes, desenfoque de movimiento, latigazos, scroll y elevación de elementos |
| `motor/mov10.py` | Curvas y resortes; `aterrizar()` hace que un movimiento llegue con una palabra |
| `motor/mg10.py` | Rótulos, llamadas y datos animados (HTML + anime.js, filmados en Chrome) |
| `motor/voz.py` | Voz narrada (edge-tts) con la marca de tiempo de cada palabra |
| `motor/subtitulos.py` | Subtítulos |
| `motor/sonido6.py` | Música y efectos sintetizados y la mezcla con la voz |
| `motor/post6.py` | Acabado final: color, grano y viñeta |
| `motor/captura.py` | Capturas a ×2 y cajas de cada elemento |
| `ejemplo/` | Sitio inventado y su `armar.py`: el punto de partida |
| `videos/` | Tus videos (capturas, caché y mp4 no se suben) |

**Marca:** color de acento en `--cian` (`motor/mg10/plantillas/base.css`) y `CIAN` (`motor/cine10.py`); letra Geist en
`motor/fuentes/`.

**Voz:** `set VOZ=es-AR-TomasNeural` (lista: `edge-tts --list-voices`). Por omisión, `en-US-BrianMultilingualNeural`,
que habla castellano neutro.

**Sistemas con usuario y contraseña:** `captura.py --ventana` abre Chrome para que ingreses a mano.

## Datos

Filmá un entorno de prueba con datos inventados. Si no queda otra que producción, tapá todo lo sensible. No subas
capturas reales a herramientas de IA externas.

## Licencias de terceros

OpenCV (Apache 2.0), anime.js (MIT), numpy, Pillow e imageio-ffmpeg (BSD/MIT), edge-tts (LGPL-3) y las fuentes Geist
(SIL OFL 1.1).
