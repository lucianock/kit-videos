"""post6: transiciones cinematográficas y acabado final (el «look»).

    import post6 as P
    img = P.transicion(cuadro_a, cuadro_b, p, 'zoom', t=t, dur=0.5)   # p de 0 a 1 a lo largo del cruce
    img = P.acabado(img, t)                                           # grano, viñeta y color, muy sutil
    img = P.cuadro_escenas(d.escenas, t)                              # elige escena y transición (DURACION por tipo)
    P.sonidos(d, t_corte, 'zoom')                                     # efectos de sonido que acompañan el cruce

Tipos: 'fundido', 'negro', 'zoom', 'barrido', 'barrido_izq', 'destello', 'glitch', 'corte'.
Solo numpy + Pillow (no importa armar2, así se puede probar suelto). Los desenfoques se calculan a resolución reducida
y se reescalan; lo nítido se pega encima donde el movimiento es chico. ACABADO=0 en el entorno apaga el acabado.
"""
import math
import os

import numpy as np
from PIL import Image, ImageChops, ImageFilter

W, H, FPS = 1920, 1080, 30
CIAN = (0, 212, 240)
NARANJA = (255, 123, 0)
NOCHE = (3, 5, 9)                       # el «negro» del video: azul noche, como el fondo del panel

TIPOS = ('fundido', 'negro', 'zoom', 'barrido', 'barrido_izq', 'destello', 'glitch', 'corte')

# Ventana recomendada de cada cruce (segundos, centrada en el corte). transicion() también funciona con otra
# ventana: zoom, barrido y glitch concentran su movimiento en su duración propia (MOVIMIENTO) y el resto del
# tiempo muestran A o B quietos.
DURACION = {'fundido': 0.6, 'negro': 0.9, 'zoom': 0.5, 'barrido': 0.4, 'barrido_izq': 0.4, 'destello': 0.7,
            'glitch': 0.36, 'corte': 0.1}
MOVIMIENTO = {'zoom': 0.55, 'barrido': 0.42, 'barrido_izq': 0.42, 'glitch': 0.36}

# Sonidos sugeridos: (desfase respecto del corte en s, nombre, ganancia, pan). Ver sonidos().
SONIDOS = {
    'fundido': [(-0.30, 'swish', 0.22, 0.0)],
    'negro': [],
    'zoom': [(-0.30, 'whoosh', 0.65, 0.0), (0.0, 'impacto', 0.22, 0.0)],
    'barrido': [(-0.17, 'whoosh_corto', 0.80, 0.25)],
    'barrido_izq': [(-0.17, 'whoosh_corto', 0.80, -0.25)],
    'destello': [(-0.45, 'reverse', 0.32, 0.0), (0.02, 'swish', 0.22, 0.0)],
    'glitch': [(-0.07, 'glitch', 0.75, 0.0)],
    'corte': [],
}

ACABADO = os.environ.get('ACABADO', '1') != '0'


# ─── Curvas ───────────────────────────────────────────────────────────────

def _lim(v, a=0.0, b=1.0):
    return a if v < a else b if v > b else v


def _suave(p):
    p = _lim(p)
    return p * p * (3 - 2 * p)


def _eio(p):
    p = _lim(p)
    return 4 * p * p * p if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def _exp_in(u):
    """0 → 1 acelerando; sigue creciendo pasado 1 (sirve para medir la velocidad al final)."""
    return (2.0 ** (10 * u) - 1) / 1023.0


def _exp_out(u):
    """0 → 1 frenando; pasado 1 queda en 1."""
    u = min(u, 1.0)
    return (1 - 2.0 ** (-10 * u)) / (1 - 2.0 ** -10)


def _comprimir(p, dur, propia):
    """Concentra el movimiento en `propia` segundos alrededor del corte aunque la ventana sea más larga."""
    if not dur or dur <= propia:
        return p
    return _lim(0.5 + (p - 0.5) * dur / propia)


# ─── Utilidades compartidas ───────────────────────────────────────────────

_SOLIDOS = {}


def _solido(color, tam=(W, H)):
    k = (tuple(color), tuple(tam))
    im = _SOLIDOS.get(k)
    if im is None:
        im = _SOLIDOS[k] = Image.new('RGB', tam, tuple(color))
    return im


def _rgb(im):
    return im if im.mode == 'RGB' else im.convert('RGB')


def _lut_pantalla(alfa, color):
    """Tabla para «pantalla» (screen) con un color fijo: 1-(1-x)(1-c·alfa), canal por canal."""
    x = np.arange(256, dtype=np.float32) / 255
    tabla = []
    for c in color:
        k = alfa * c / 255
        tabla += np.clip(np.round((1 - (1 - x) * (1 - k)) * 255), 0, 255).astype(int).tolist()
    return tabla


def flash(img, alfa, color=(255, 255, 255), modo='pantalla'):
    """Destello de luz. modo 'pantalla' aclara sin aplastar el contraste (como luz que entra); 'mezcla' funde hacia
    el color (como un blanco de cámara)."""
    if alfa <= 0.003:
        return img
    if modo == 'mezcla':
        return Image.blend(_rgb(img), _solido(color, img.size), _lim(alfa))
    return _rgb(img).point(_lut_pantalla(_lim(alfa), color))


def _escalar(img, s, cx=None, cy=None):
    """Acerca la imagen s veces (s ≥ 1) dejando quieto el punto (cx, cy)."""
    w, h = img.size
    cx = w / 2 if cx is None else cx
    cy = h / 2 if cy is None else cy
    if s <= 1.0002:
        return img
    caja = (cx - cx / s, cy - cy / s, cx + (w - cx) / s, cy + (h - cy) / s)
    return img.resize((w, h), Image.BILINEAR, box=caja)


# Mapa de distancias al centro: 'L' de 2W×2H con el centro en (W, H); 255 = la diagonal completa.
_RADIAL = None
RMAX = math.hypot(W, H)


def _radial():
    global _RADIAL
    if _RADIAL is None:
        y, x = np.ogrid[-H:H, -W:W]
        r = np.sqrt((x.astype(np.float32) + 0.5) ** 2 + (y.astype(np.float32) + 0.5) ** 2)
        _RADIAL = Image.fromarray(np.clip(np.round(r / RMAX * 255), 0, 255).astype(np.uint8), 'L')
    return _RADIAL


L0, LW = 1.0, 3.5      # estela (px) desde la que algo se ve corrido, y cuánto tarda en estar del todo desenfocado


def _mascara_nitida(caja, cx, cy, fm1):
    """Peso de la versión nítida (255) en cada punto de `caja`, según lo larga que es su estela en un zoom fm1."""
    x0, y0, x1, y1 = caja
    tabla = []
    for v in range(256):
        largo = v * RMAX / 255 * fm1
        tabla.append(int(round(255 * (1 - _lim((largo - L0) / LW)))))
    ox, oy = int(round(W - cx)), int(round(H - cy))
    return _radial().crop((x0 + ox, y0 + oy, x1 + ox, y1 + oy)).point(tabla)


def _zoom_bajo(im, cx, cy, f, pasos_max=6):
    """Desenfoque de zoom a baja resolución: promedia 2^n copias agrandadas entre 1 y f (duplicando en cada paso)."""
    w, h = im.size
    largo = math.hypot(max(cx, w - cx), max(cy, h - cy)) * (f - 1)
    if largo < 0.8:
        return im
    pasos = max(1, min(pasos_max, int(math.ceil(math.log2(largo / 0.9)))))
    acc = im
    for k in range(pasos):
        fk = f ** (0.5 ** (k + 1))
        caja = (cx - cx / fk, cy - cy / fk, cx + (w - cx) / fk, cy + (h - cy) / fk)
        acc = Image.blend(acc, acc.resize((w, h), Image.BILINEAR, box=caja), 0.5)
    hueco = largo / 2 ** pasos
    if hueco > 1.4:                                   # copias muy separadas: un pelo de suavizado y no se notan
        acc = acc.filter(ImageFilter.BoxBlur(hueco / 2.5))
    return acc


_LUZ_BAJO = {}


def _luz_bajo(im, alfa, color, centro=0.45):
    """Luz que llena el cuadro (pantalla), más fuerte en el centro, sobre una imagen chica."""
    w, h = im.size
    patron = _LUZ_BAJO.get((w, h, color))
    if patron is None:
        y, x = np.ogrid[0:h, 0:w]
        g = np.exp(-(((x - w / 2) / (0.55 * w)) ** 2 + ((y - h / 2) / (0.55 * w)) ** 2))
        k = ((1 - centro) + centro * g)[..., None] * np.array(color, np.float64)
        patron = _LUZ_BAJO[(w, h, color)] = Image.fromarray(np.round(k).astype(np.uint8), 'RGB')
    a = _lim(alfa)
    return ImageChops.screen(im, patron.point([int(v * a + 0.5) for v in range(256)] * 3))


def _reduccion(largo):
    """Cuánto achicar para desenfocar una estela de `largo` px sin perder calidad visible."""
    return 4 if largo < 150 else 6


# ─── Ayudas públicas de desenfoque ────────────────────────────────────────

def zoom_blur(img, cx=W / 2, cy=H / 2, fuerza=0.1, nitido=True):
    """Desenfoque radial (de zoom) hacia afuera de (cx, cy): cada punto deja una estela del `fuerza` de su
    distancia al centro (0,1 = 10 %). Con nitido=True el centro, que casi no se mueve, queda nítido."""
    img = _rgb(img)
    if fuerza <= 0.0005:
        return img
    w, h = img.size
    largo = math.hypot(max(cx, w - cx), max(cy, h - cy)) * fuerza
    if largo < L0 + 0.5:
        return img
    k = _reduccion(largo)
    bajo = _zoom_bajo(img.reduce(k), cx / k, cy / k, 1 + fuerza)
    out = bajo.resize((w, h), Image.BILINEAR)
    if nitido and (w, h) == (W, H):
        r1 = (L0 + LW) / fuerza
        if r1 > 12:
            x0, y0 = max(0, int(cx - r1)), max(0, int(cy - r1))
            x1, y1 = min(w, int(math.ceil(cx + r1))), min(h, int(math.ceil(cy + r1)))
            out.paste(img.crop((x0, y0, x1, y1)), (x0, y0), _mascara_nitida((x0, y0, x1, y1), cx, cy, fuerza))
    return out


def desenfoque_movimiento(img, dx, dy=0.0):
    """Desenfoque de movimiento en línea recta: la estela mide (dx, dy) px. Horizontal o vertical sale exacto a
    resolución completa (~10 ms); en diagonal se gira a resolución reducida, se desenfoca y se vuelve (35-65 ms)."""
    img = _rgb(img)
    ax, ay = abs(dx), abs(dy)
    if ax < 1.5 and ay < 1.5:
        return img
    if ay < 1.5 or ax < 1.5:
        return img.filter(ImageFilter.BoxBlur((ax / 2 if ay < 1.5 else 0, ay / 2 if ax < 1.5 else 0)))
    w, h = img.size
    largo = math.hypot(dx, dy)
    k = 3 if largo < 40 else 4
    chico = img.reduce(k)
    cw, ch = chico.size
    m = int(math.ceil(largo / k / 2)) + 3
    grande = Image.fromarray(np.pad(np.asarray(chico), ((m, m), (m, m), (0, 0)), mode='edge'), 'RGB')
    ang = math.degrees(math.atan2(dy, dx))
    girada = grande.rotate(ang, Image.BILINEAR, expand=True)
    girada = girada.filter(ImageFilter.BoxBlur((largo / k / 2, 0)))
    vuelta = girada.rotate(-ang, Image.BILINEAR, expand=True)
    x0 = (vuelta.width - grande.width) / 2 + m
    y0 = (vuelta.height - grande.height) / 2 + m
    return vuelta.resize((w, h), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))


# ─── Transiciones ─────────────────────────────────────────────────────────

def _t_fundido(a, b, p, t, dur):
    """Fundido encadenado con un leve empuje: se acerca un 2,6 % y vuelve a su lugar mientras cambia."""
    q = _suave(p)
    img = Image.blend(a, b, q)
    return _escalar(img, 1 + 0.026 * 4 * q * (1 - q))


def _t_negro(a, b, p, t, dur):
    """Pasa por el azul noche: A se apaga y B se enciende (para cambios de capítulo)."""
    if p < 0.5:
        return Image.blend(a, _solido(NOCHE, a.size), _eio(p / 0.5))
    return Image.blend(_solido(NOCHE, b.size), b, _eio((p - 0.5) / 0.5))


Z_ZOOM, S0_ZOOM, OBTURADOR = 1.6, 0.7, 0.75
LUZ_ZOOM = (226, 248, 255)
QUIETO = 8.0           # estela máxima (px, en la esquina) por debajo de la cual el zoom se muestra nítido


def _t_zoom(a, b, p, t, dur):
    """Zoom a través: A se agranda acelerando con desenfoque radial y un leve corrimiento de color de lente; un
    destello frío tapa el corte y B llega desde más chico (el entorno, espejado y oscurecido) y frena."""
    p = _comprimir(p, dur, MOVIMIENTO['zoom'])
    dpf = 1.0 / (FPS * min(dur or MOVIMIENTO['zoom'], MOVIMIENTO['zoom']))
    du = dpf / 0.5 * OBTURADOR
    fl = 0.92 * math.exp(-((p - 0.5) / 0.09) ** 2)
    if p < 0.5:
        u = p / 0.5
        s = 1 + Z_ZOOM * _exp_in(u)
        f = (1 + Z_ZOOM * _exp_in(u + du)) / s
        return _capa_zoom(a, s, f, fl, entra=False)
    u = (p - 0.5) / 0.5
    s = S0_ZOOM + (1 - S0_ZOOM) * _exp_out(u)
    f = (S0_ZOOM + (1 - S0_ZOOM) * _exp_out(u + du)) / s
    return _capa_zoom(b, s, f, fl, entra=True)


def _achicada_espejada(src, s):
    """src achicada s veces en el centro; el borde que queda se completa espejando la propia imagen."""
    if s > 0.9995:
        return src
    sw, sh = round(W * s), round(H * s)
    x0, y0 = (W - sw) // 2, (H - sh) // 2
    chica = src.resize((sw, sh), Image.BILINEAR)
    out = Image.new('RGB', (W, H))
    out.paste(chica, (x0, y0))
    if x0 > 0:
        out.paste(chica.crop((0, 0, x0, sh)).transpose(Image.FLIP_LEFT_RIGHT), (0, y0))
        der = W - x0 - sw
        out.paste(chica.crop((sw - der, 0, sw, sh)).transpose(Image.FLIP_LEFT_RIGHT), (x0 + sw, y0))
    if y0 > 0:
        out.paste(out.crop((0, y0, W, 2 * y0)).transpose(Image.FLIP_TOP_BOTTOM), (0, 0))
        aba = H - y0 - sh
        out.paste(out.crop((0, y0 + sh - aba, W, y0 + sh)).transpose(Image.FLIP_TOP_BOTTOM), (0, y0 + sh))
    return out


def _aberracion(im, ca):
    """Corrimiento de color de lente (rojo un poco más grande que el azul), proporcional a la velocidad."""
    w, h = im.size
    if ca * math.hypot(w, h) / 2 < 0.75:            # menos de un píxel de corrimiento: no se nota
        return im
    r, g, b = im.split()
    return Image.merge('RGB', (_escalar(r, 1 + 2 * ca), _escalar(g, 1 + ca), b))


def _capa_zoom(src, s, f, fl, entra):
    cx, cy = W / 2, H / 2
    largo = RMAX / 2 * (f - 1)                       # estela en la esquina, en px
    if largo < QUIETO and fl < 0.01:                 # casi quieto: nítido, sin desenfoque
        return _achicada_espejada(src, s) if entra else _escalar(src, s)
    k = _reduccion(largo)
    w, h = W // k, H // k
    bajo = src.reduce(k)
    if entra:
        vw, vh = w / s, h / s
        mx, my = int(math.ceil((vw - w) / 2)) + 2, int(math.ceil((vh - h) / 2)) + 2
        arr = np.pad(np.asarray(bajo), ((my, my), (mx, mx), (0, 0)), mode='symmetric')
        oscuro = (arr.astype(np.float32) * 0.5).astype(np.uint8)      # el reflejo, más apagado que B
        oscuro[my:my + h, mx:mx + w] = arr[my:my + h, mx:mx + w]
        espejo = Image.fromarray(oscuro, 'RGB')
        ex, ey = mx + w / 2, my + h / 2
        vista = espejo.resize((w, h), Image.BILINEAR, box=(ex - vw / 2, ey - vh / 2, ex + vw / 2, ey + vh / 2))
    else:
        vista = _escalar(bajo, s)
    vista = _aberracion(vista, min(0.012, 0.18 * (f - 1)))
    bajo = _zoom_bajo(vista, w / 2, h / 2, f)
    if fl > 0.01:
        bajo = _luz_bajo(bajo, fl, LUZ_ZOOM)
    out = bajo.resize((W, H), Image.BILINEAR)
    # Centro nítido: donde la estela es corta se ve la imagen real
    r1 = (L0 + LW) / (f - 1) if f > 1.0001 else 1e9
    if r1 > 16:
        hx, hy = min(r1, W / 2), min(r1, H / 2)
        if entra:
            hx, hy = min(hx, W * s / 2), min(hy, H * s / 2)
        x0, y0 = max(0, int(cx - hx)), max(0, int(cy - hy))
        x1, y1 = min(W, int(math.ceil(cx + hx))), min(H, int(math.ceil(cy + hy)))
        caja = (cx + (x0 - cx) / s, cy + (y0 - cy) / s, cx + (x1 - cx) / s, cy + (y1 - cy) / s)
        caja = (max(0.0, caja[0]), max(0.0, caja[1]), min(float(W), caja[2]), min(float(H), caja[3]))
        nit = src.resize((x1 - x0, y1 - y0), Image.BILINEAR, box=caja)
        if fl > 0.01:
            nit = flash(nit, fl, LUZ_ZOOM)
        out.paste(nit, (x0, y0), _mascara_nitida((x0, y0, x1, y1), cx, cy, f - 1))
    return out


def _t_barrido(a, b, p, t, dur, sentido=1):
    """Paneo látigo: A sale de costado y B entra, con desenfoque de movimiento fuerte en el medio.
    sentido 1: el contenido se va a la izquierda (B entra por la derecha); -1: al revés."""
    p = _comprimir(p, dur, MOVIMIENTO['barrido'])
    k = 9.0
    th = math.tanh(k / 2)
    q = 0.5 + 0.5 * math.tanh(k * (p - 0.5)) / th
    v = 0.5 * k / math.cosh(k * (p - 0.5)) ** 2 / th          # velocidad en anchos de cuadro por unidad de p
    x = int(round(q * W))
    if x <= 0:
        base = a.copy()
    elif x >= W:
        base = b.copy()
    else:
        base = Image.new('RGB', (W, H))
        if sentido > 0:
            base.paste(a.crop((x, 0, W, H)), (0, 0))
            base.paste(b.crop((0, 0, x, H)), (W - x, 0))
        else:
            base.paste(b.crop((W - x, 0, W, H)), (0, 0))
            base.paste(a.crop((0, 0, W - x, H)), (x, 0))
    real = min(dur or MOVIMIENTO['barrido'], MOVIMIENTO['barrido'])
    largo = min(0.33 * W, v * W / (FPS * real) * 0.55)          # obturador de 200°
    if largo >= 2:
        base = base.filter(ImageFilter.BoxBlur((largo / 2, 0)))
        if largo > 60:                                          # al barrer, las luces se estiran y brillan un poco
            base = base.point(_lut_pantalla(0.07 * _lim((largo - 60) / 300), (205, 235, 255)))
    return base


_FUGA = {}


def _malla_fuga(w=320, h=180):
    m = _FUGA.get((w, h))
    if m is None:
        y, x = np.mgrid[0:h, 0:w].astype(np.float32)
        m = _FUGA[(w, h)] = (x / h, y / h)          # coordenadas con la proporción real (x de 0 a 1,78)
    return m


def _fuga_luz(p, t, env):
    """Fuga de luz cálida (light leak) a 320×180: dos manchas (naranja y ámbar) que se cruzan, un borde rojizo
    quemado, un núcleo blanco cálido que crece hasta el corte, un rayo diagonal suave y una raya anamórfica.
    Devuelve un arreglo 0..1 (180, 320, 3)."""
    X, Y = _malla_fuga()
    x, y = X[0], Y[:, 0]
    ar = 16 / 9
    barre = env ** 0.7
    nucleo = env ** 2.2
    titila = 1 + 0.05 * math.sin(41 * t + 2 * p) + 0.03 * math.sin(73 * t + 1)
    # manchas gaussianas separables: (cx, cy, sx, sy, color, intensidad)
    manchas = [
        (-0.5 + 2.8 * p, 0.30 + 0.06 * math.sin(3.1 * p), 0.58, 0.52, (255, 104, 14), 1.25 * barre),
        (ar + 0.5 - 2.7 * p, 0.84, 0.62, 0.36, (255, 168, 58), 1.0 * barre),
        (-0.08, 1.0 - 0.4 * p, 0.32, 0.5, (255, 56, 36), 0.6 * barre),
        (ar / 2 + 0.3 * (p - 0.5), 0.48, 0.66, 0.52, (255, 238, 212), 1.9 * nucleo),
        (ar / 2 + 0.35 * (p - 0.5), 0.47 + 0.01 * math.sin(5 * t), 1.3, 0.02, (255, 214, 168), 0.8 * nucleo),
    ]
    gy = np.stack([np.exp(-((y - m[1]) / m[3]) ** 2) for m in manchas], axis=1)            # (180, n)
    gx = np.stack([np.exp(-((x - m[0]) / m[2]) ** 2) * m[5] for m in manchas], axis=0)     # (n, 320)
    cols = np.array([m[4] for m in manchas], np.float32) / 255                            # (n, 3)
    acc = np.stack([(gy * cols[:, c]) @ gx for c in range(3)], axis=2)
    # rayo diagonal que cruza con la luz
    d = (X - (0.2 + 1.4 * p)) * 0.8 + (Y - 0.5) * 0.6
    rayo = np.exp(-(d / 0.09) ** 2 - ((Y - 0.45) / 0.7) ** 2) * (0.55 * env)
    acc += rayo[..., None] * (np.array((255, 196, 130), np.float32) / 255)
    return 1 - np.exp(-acc * (1.25 * titila))


def _t_destello(a, b, p, t, dur):
    """Destello cálido (light leak): una fuga de luz naranja cruza el cuadro, lo quema casi entero en el medio y
    debajo de esa luz A pasa a B."""
    env = math.sin(math.pi * _lim(p)) ** 2
    w = _suave((p - 0.42) / 0.16)
    base = a if w <= 0 else b if w >= 1 else Image.blend(a, b, w)
    if env < 0.004:
        return base
    fuga = _fuga_luz(p, t, env)
    luz = Image.fromarray((np.clip(fuga, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGB')
    # la luz es muy suave: bilineal hasta media resolución y después ×2 directo (6 ms en vez de 12)
    luz = luz.resize((W // 2, H // 2), Image.BILINEAR).resize((W, H), Image.NEAREST)
    return ImageChops.add(base, luz)                 # suma (linear dodge): la luz quema las altas luces


_RUIDO_FILAS = None


def _ruido_filas():
    global _RUIDO_FILAS
    if _RUIDO_FILAS is None:
        rng = np.random.default_rng(77)
        _RUIDO_FILAS = rng.integers(0, 256, (24, W * 2, 1), dtype=np.uint8)
    return _RUIDO_FILAS


def _t_glitch(a, b, p, t, dur):
    """Corte digital: franjas corridas (algunas de la otra escena), bloques pixelados, separación RGB y líneas de
    ruido; el corte de A a B cae justo en el medio."""
    medio = MOVIMIENTO['glitch'] / 2
    real = dur or MOVIMIENTO['glitch']
    d = abs(p - 0.5) * real                                   # segundos al corte
    e = 1 - d / medio
    if e <= 0:
        return a if p < 0.5 else b
    e = e ** 0.75
    n = int(round(t * FPS)) if t else int(round(p * 997))
    rng = np.random.default_rng((n * 7919 + int(p * 1000) * 31 + 17) % (2 ** 32))
    base, otra = (a, b) if p < 0.5 else (b, a)
    arr = np.array(base)
    # 1) franjas corridas
    altos = np.array([2, 4, 6, 10, 16, 26, 40, 64, 96])
    pesos = np.array([5, 7, 8, 8, 7, 5, 4, 3, 2], np.float64)
    for _ in range(int(round(2 + 12 * e))):
        hb = int(rng.choice(altos, p=pesos / pesos.sum()))
        y0 = int(rng.integers(0, H - hb))
        dx = int(rng.normal(0, 150 * e))
        if rng.random() < 0.55 * e:
            banda = np.asarray(otra.crop((0, y0, W, y0 + hb)))
        else:
            banda = arr[y0:y0 + hb].copy()
        arr[y0:y0 + hb] = np.roll(banda, dx, axis=1)
    # 2) bloques de compresión rotos (alineados a 16 px), algunos teñidos de cian o naranja
    for _ in range(int(rng.integers(0, 2 + int(6 * e)))):
        bw, bh = 16 * int(rng.integers(3, 26)), 16 * int(rng.integers(1, 6))
        x0, y0 = 16 * int(rng.integers(0, (W - bw) // 16)), 16 * int(rng.integers(0, (H - bh) // 16))
        blk = arr[y0:y0 + bh, x0:x0 + bw]
        c = int(rng.choice([8, 16]))
        peq = blk[c // 2::c, c // 2::c]
        blk[:] = np.repeat(np.repeat(peq, c, 0), c, 1)[:bh, :bw]
        r = rng.random()
        if r < 0.45:
            color = np.array(CIAN if r < 0.3 else NARANJA, np.float32)
            blk[:] = (blk.astype(np.float32) * 0.5 + color * 0.5).astype(np.uint8)
    # 3) separación de canales (rojo a la derecha, azul a la izquierda)
    s = int(round(2 + 16 * e * rng.uniform(0.55, 1.0)))
    arr[:, s:, 0] = arr[:, :-s, 0]
    arr[:, :-s, 2] = arr[:, s:, 2]
    if e > 0.5:
        sv = int(round(4 * e * rng.uniform(-1, 1)))
        if sv:
            arr[:, :, 1] = np.roll(arr[:, :, 1], sv, axis=0)
    # 4) líneas de ruido de señal
    ruido = _ruido_filas()
    for _ in range(int(rng.integers(0, 1 + int(5 * e)))):
        y0 = int(rng.integers(0, H - 3))
        hb = int(rng.integers(1, 4))
        x0 = int(rng.integers(0, W))
        fila = ruido[int(rng.integers(0, 22)):][:hb, x0:x0 + W]
        if rng.random() < 0.5:
            arr[y0:y0 + hb] = np.maximum(arr[y0:y0 + hb], fila)
        else:
            arr[y0:y0 + hb] = fila
    # 5) un salto de imagen (como el «tracking» de una señal) en los cuadros más fuertes
    if e > 0.7 and rng.random() < 0.3:
        arr = np.roll(arr, int(rng.integers(-70, 70)), axis=0)
    return Image.fromarray(arr, 'RGB')


def _t_corte(a, b, p, t, dur, con_flash=False):
    """Corte seco; con con_flash=True el primer cuadro de B sale aclarado (un «flash» de un cuadro)."""
    if p < 0.5:
        return a
    if con_flash and (p - 0.5) * (dur or DURACION['corte']) < 1.0 / FPS:
        return flash(b, 0.55, (255, 248, 236))
    return b


_TRANS = {
    'fundido': _t_fundido,
    'negro': _t_negro,
    'zoom': _t_zoom,
    'barrido': lambda a, b, p, t, dur: _t_barrido(a, b, p, t, dur, 1),
    'barrido_izq': lambda a, b, p, t, dur: _t_barrido(a, b, p, t, dur, -1),
    'destello': _t_destello,
    'glitch': _t_glitch,
    'corte': _t_corte,
}


def transicion(a, b, p, tipo, t=0.0, dur=None, **op):
    """Mezcla dos cuadros RGB (1920×1080) con progreso p (0 = todo A, 1 = todo B).

    tipo: 'fundido' | 'negro' | 'zoom' | 'barrido' | 'barrido_izq' | 'destello' | 'glitch' | 'corte'
          (cualquier otro nombre cae en 'fundido').
    t:    segundo absoluto del cuadro (varía el ruido del glitch y el titilar del destello).
    dur:  duración real de la ventana del cruce en segundos (si no se pasa, DURACION[tipo]); con ella se calculan
          la velocidad y el desenfoque de movimiento.
    op:   con_flash=True (o flash=True) para 'corte': el primer cuadro de B sale aclarado.
    """
    if p <= 0:
        return a
    if p >= 1:
        return b
    a, b = _rgb(a), _rgb(b)
    fn = _TRANS.get(tipo, _t_fundido)
    dur = DURACION.get(tipo, 0.5) if dur is None else dur
    if tipo == 'corte':
        return _t_corte(a, b, p, t, dur, con_flash=bool(op.get('con_flash', op.get('flash', False))))
    return fn(a, b, p, t, dur)


def necesita(tipo, p, dur=None):
    """Qué cuadros hacen falta para la transición en p: 'a', 'b' o 'ab' (para no dibujar escenas de más)."""
    if p <= 0:
        return 'a'
    if p >= 1:
        return 'b'
    dur = DURACION.get(tipo, 0.5) if dur is None else dur
    if tipo == 'corte':
        return 'a' if p < 0.5 else 'b'
    if tipo == 'negro':
        return 'a' if p < 0.5 else 'b'
    if tipo == 'zoom':
        return 'a' if _comprimir(p, dur, MOVIMIENTO['zoom']) < 0.5 else 'b'
    if tipo == 'glitch':
        if abs(p - 0.5) * dur >= MOVIMIENTO['glitch'] / 2:
            return 'a' if p < 0.5 else 'b'
        return 'ab'
    if tipo in ('barrido', 'barrido_izq'):
        q = _comprimir(p, dur, MOVIMIENTO['barrido'])
        x = 0.5 + 0.5 * math.tanh(9.0 * (q - 0.5)) / math.tanh(4.5)
        return 'a' if x * W < 0.5 else 'b' if x * W > W - 0.5 else 'ab'
    return 'ab'


def cuadro_escenas(escenas, t, duraciones=None, **op):
    """Cuadro base en t: la escena que corresponde o el cruce entre dos, con la ventana de DURACION de cada tipo.

    escenas: lista de [tipo, t0, t1, obj, entrada] (el formato de Director3/5/6: `entrada` es cómo entra esa
    escena; obj.cuadro(t) devuelve la imagen). Solo dibuja las escenas que la transición necesita."""
    dur = DURACION if duraciones is None else duraciones
    i = next((k for k, e in enumerate(escenas) if e[1] <= t < e[2]), len(escenas) - 1)
    _, t0, t1, obj, entrada = escenas[i]
    par = None
    if i > 0:
        x = dur.get(entrada, 0.5)
        if x > 0 and t < t0 + x / 2:
            par = (escenas[i - 1][3], obj, (t - (t0 - x / 2)) / x, entrada, x)
    if par is None and i + 1 < len(escenas):
        sig = escenas[i + 1]
        x = dur.get(sig[4], 0.5)
        if x > 0 and t >= t1 - x / 2:
            par = (obj, sig[3], (t - (t1 - x / 2)) / x, sig[4], x)
    if par is None:
        return obj.cuadro(t)
    oa, ob, p, tipo, x = par
    falta = necesita(tipo, p, x)
    if falta == 'a':
        return oa.cuadro(t)
    if falta == 'b':
        img = ob.cuadro(t)
        return transicion(img, img, p, tipo, t, x, **op) if tipo == 'corte' else img
    return transicion(oa.cuadro(t), ob.cuadro(t), p, tipo, t, x, **op)


def sonidos(d, t_corte, tipo, ganancia=1.0):
    """Agenda en el director d los efectos que acompañan la transición (t_corte = el instante del cambio de
    escena). Si el director ya pone un whoosh en cada escena, conviene no sumar los dos."""
    for dt, nombre, g, pan in SONIDOS.get(tipo, []):
        d.sfx(t_corte + dt, nombre, g * ganancia, pan)


# ─── Acabado ──────────────────────────────────────────────────────────────

NG = 8                       # texturas de grano que se alternan
_ORDEN = [0, 5, 2, 7, 3, 6, 1, 4]
_AC = {}


class _Estado:
    pass


def _estado_acabado(grano, vineta, color):
    clave = (round(grano, 3), round(vineta, 3), round(color, 3))
    st = _AC.get(clave)
    if st is not None:
        return st
    st = _Estado()
    amp = int(math.ceil(2 * grano)) if grano > 0 else 0
    # Color: sombras apenas frías, altas luces apenas cálidas. El rango se comprime `amp` niveles en cada punta
    # para que el grano (suma módulo 256, la operación más rápida de Pillow) nunca dé la vuelta.
    x = np.arange(256, dtype=np.float64)
    n = x / 255
    sh, hi = (1 - n) ** 2.2, n ** 2.2
    canales = (x + color * (-1.0 * sh + 2.6 * hi), x + color * (0.7 * sh + 0.8 * hi), x + color * (3.4 * sh - 3.0 * hi))
    st.lut = []
    for c in canales:
        st.lut += np.clip(np.round(amp + np.clip(c, 0, 255) * (255 - 2 * amp) / 255), 0, 255).astype(int).tolist()
    st.identidad = amp == 0 and color == 0
    # Grano: gaussiano a media resolución (grano de 2 px, que el x264 no borra del todo), monocromo
    st.texturas = []
    if amp:
        rng = np.random.default_rng(606)
        for _ in range(NG):
            z = rng.standard_normal((H // 2, W // 2)).astype(np.float32)
            z = np.asarray(Image.fromarray(z, 'F').resize((W, H), Image.BICUBIC), np.float32)
            z = z / (z.std() + 1e-6) * 0.7 * grano
            z = np.clip(np.round(z), -amp, amp).astype(np.int8).view(np.uint8)
            st.texturas.append(Image.fromarray(np.repeat(z[..., None], 3, axis=2), 'RGB'))
    # Viñeta: solo en las esquinas (el centro queda intacto), pegando negro con una máscara por esquina
    st.vineta = []
    if vineta > 0:
        y, x2 = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((x2 + 0.5 - W / 2) / (W / 2)) ** 2 + ((y + 0.5 - H / 2) / (H / 2)) ** 2)
        u = np.clip((r - 1.08) / (1.415 - 1.08), 0, 1)
        a = np.round(255 * 0.22 * vineta * u ** 2.2).clip(0, 255).astype(np.uint8)
        a[a < 4] = 0                     # lo casi imperceptible no se pinta (cajas más chicas, más rápido)
        for xs, ys in ((slice(0, W // 2), slice(0, H // 2)), (slice(W // 2, W), slice(0, H // 2)),
                       (slice(0, W // 2), slice(H // 2, H)), (slice(W // 2, W), slice(H // 2, H))):
            q = a[ys, xs]
            filas, cols = np.nonzero(q.any(axis=1))[0], np.nonzero(q.any(axis=0))[0]
            if not len(filas):
                continue
            x0, x1 = xs.start + cols[0], xs.start + cols[-1] + 1
            y0, y1 = ys.start + filas[0], ys.start + filas[-1] + 1
            st.vineta.append(((int(x0), int(y0), int(x1), int(y1)), Image.fromarray(a[y0:y1, x0:x1].copy(), 'L')))
    _AC[clave] = st
    return st


def acabado(img, t=0.0, activo=None, grano=1.0, vineta=1.0, color=1.0):
    """Look final, muy sutil (~11 ms): color (sombras apenas frías, luces apenas cálidas), grano de película fino
    (desvío de 0,7 niveles, tope ±2) que cambia en cada cuadro y viñeta suave solo en las esquinas.

    activo: False lo apaga (None = variable de entorno ACABADO, prendido por defecto).
    grano, vineta, color: intensidades (1 = la recomendada, 0 = sin ese efecto).
    Ojo con el grano y el tamaño del archivo: con CRF 17, una toma quieta pasa de ~0,5 Mbps a ~2,8 Mbps con grano=1
    y a ~7,5 Mbps con grano=1,6 (el x264 conserva el ruido). grano=0 lo saca sin tocar el resto."""
    if activo is None:
        activo = ACABADO
    if not activo:
        return img
    img = _rgb(img)
    st = _estado_acabado(grano, vineta, color)
    out = img.copy() if st.identidad else img.point(st.lut)
    if st.texturas:
        k = int(round(t * FPS))
        out = ImageChops.add_modulo(out, st.texturas[_ORDEN[k % NG]])
    for caja, m in st.vineta:
        out.paste((0, 0, 0), caja, m)
    return out
