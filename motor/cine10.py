"""cine10: la cámara virtual del panel (OpenCV), con desenfoque de movimiento real.

Reemplaza, para el recorrido del panel, el armado de armar2 (componer_ventana + dibujar_foco con Pillow), que queda
sin tocar. Las capturas son «placas» puestas en un mundo plano (unidades = px CSS de la captura) y una cámara las
filma. Lo nuevo:

  · Desenfoque de movimiento real: cada cuadro es el promedio de K muestras de la escena dentro del obturador (180°,
    1/120 s a 60 fps), en luz lineal. K se elige solo según cuánto se mueve la imagen (1 si está quieta, hasta 40 en
    un latigazo). El paneo, el zoom, el látigo entre páginas y el scroll quedan «filmados», no deslizados.
  · Encuadre a pantalla llena: zoom 1 = la captura de 1920 px ocupa los 1920 px del cuadro (en la v9 ocupaba el 84 %
    dentro de una ventana). Para el proyector, el panel se ve un 19 % más grande sin acercar nada.
  · Perspectiva 3D (inclinación de la cámara con homografía) y parallax del fondo, para entradas y planos generales.
  · Elevación: el elemento que nombra la voz (una tarjeta, una fila) se despega de la página: crece con un resorte,
    con sombra y un borde cian que respira, y el resto de la página se oscurece y se desenfoca (profundidad de campo).
    No hay un recuadro dibujado aparte que pueda quedar corrido: lo que se ilumina es el elemento mismo, recortado de
    la captura en las coordenadas del DOM (tapar.json). Se recorta supermuestreado (×2, Lanczos + nitidez) y los
    números se vuelven a escribir a ×2 con la letra del panel (Geist Mono), así se leen nítidos aunque se acerquen.
  · Contadores: el número de una tarjeta cuenta hasta su valor real con la letra del panel.
  · Scroll real: la barra de arriba y el menú quedan fijos y solo baja el contenido (como en el navegador), con el
    desenfoque de movimiento vertical que tendría una pantalla filmada.
  · Sprites de mg10 (rótulos y llamadas hechos con HTML/CSS/anime.js en Chrome) pegados con precisión subpíxel: una
    llamada anclada a un punto de la página lo sigue aunque la cámara se mueva, sin temblar un píxel.

  · Fuentes: Imagen (una captura; ss=2 con las de nitidas10), PaginaDesplazable (scroll real), Secuencia (las tomas
    del mapa en vivo, cuadro a cuadro), Recorte (supermuestreado), ConContadores, ConEsquinas; ventana() arma la
    ventana flotante (sombra, barra de título y página).

    import cine10 as C, mov10 as M
    esc = C.Escena(fps=60)
    ini = esc.placa(C.Imagen(pant.im['inicio9']), 0, 0)            # una página, en el mundo en (0, 0)
    esc.cam.ir(0, C.encuadre_completo(ini), 0)                       # pantalla llena
    esc.cam.resorte(2.0, esc.encuadre(ini, (313, 175, 1250, 310)))   # acercar a las tarjetas
    esc.elevar(2.4, 4.0, ini, (630, 175, 932, 310), contador=C.Contador(...))
    img = esc.cuadro(t)                                              # PIL RGB 1920×1080

Requiere opencv-python-headless (entorno .venv10, ver TECNOLOGIA10.md).
"""
import math
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import mov10 as M

W, H = 1920, 1080
AQUI = os.path.dirname(os.path.abspath(__file__))
FUENTES = os.path.join(AQUI, 'fuentes')

CIAN = (0, 251, 255)              # color de acento (cambialo por el de tu marca)
FONDO_PANEL = (3, 6, 11)
SUPERFICIE = (7, 14, 21)          # bg-surface de las tarjetas del panel
TEXTO = (225, 238, 242)

ZONA_UTIL = (0, 0, W, 930)        # lo que no tapan los subtítulos (la franja de abajo)
OBTURADOR = 0.5                   # fracción del cuadro con el obturador abierto (180°)
PASO_PX = 1.4                     # separación máxima entre muestras del desenfoque, en px del cuadro
K_MAX = 40
K_MEDIA = 24                      # desde tantas muestras (estela de más de ~34 px) se toman a media resolución

cv2.setNumThreads(max(1, int(os.environ.get('HILOS_CV', '2'))))


# ─── Utilidades ───────────────────────────────────────────────────────────

def lim(v, a=0.0, b=1.0):
    return a if v < a else b if v > b else v


def _rgba(im, ya_premultiplicada=False):
    """PIL o numpy → numpy RGBA uint8 premultiplicado."""
    if isinstance(im, Image.Image):
        im = np.asarray(im.convert('RGBA') if im.mode != 'RGBA' else im)
    im = np.ascontiguousarray(im)
    if im.ndim == 2:
        im = np.dstack([im, im, im])
    if im.shape[2] == 3:
        return np.dstack([im, np.full(im.shape[:2], 255, np.uint8)])
    if ya_premultiplicada:
        return im
    a = im[..., 3:4].astype(np.uint16)
    out = im.copy()
    out[..., :3] = ((im[..., :3].astype(np.uint16) * a + 127) // 255).astype(np.uint8)
    return out


_SRGB_A_LIN = ((np.arange(256) / 255.0) ** 2.2).astype(np.float32)        # aproximación de la curva sRGB
_LIN_A_SRGB = np.clip(np.round((np.arange(4096) / 4095.0) ** (1 / 2.2) * 255), 0, 255).astype(np.uint8)


def a_lineal(u8):
    return cv2.LUT(u8, _SRGB_A_LIN)


def a_srgb(lin):
    idx = np.clip(lin * 4095.0 + 0.5, 0, 4095).astype(np.uint16)
    return _LIN_A_SRGB[idx]


def componer(dst, src, x0, y0, opacidad=1.0):
    """src premultiplicado RGBA uint8 sobre dst RGB uint8 (en su lugar), en (x0, y0) enteros, recortando."""
    h, w = src.shape[:2]
    X0, Y0, X1, Y1 = max(0, x0), max(0, y0), min(dst.shape[1], x0 + w), min(dst.shape[0], y0 + h)
    if X1 <= X0 or Y1 <= Y0 or opacidad <= 0.002:
        return
    s = src[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]
    d = dst[Y0:Y1, X0:X1]
    if opacidad < 0.999:
        s = cv2.convertScaleAbs(s, alpha=opacidad)
    a = s[..., 3]
    if a.min() == 255:
        d[...] = s[..., :3]
        return
    inv = cv2.cvtColor(255 - a, cv2.COLOR_GRAY2RGB)
    d[...] = cv2.add(cv2.multiply(d, inv, scale=1 / 255.0), s[..., :3])


def caja_redonda(w, h, radio, ss=4):
    """Máscara L con esquinas redondeadas y borde suavizado (dibujada a ×ss y reducida)."""
    m = Image.new('L', (int(round(w * ss)), int(round(h * ss))), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, m.width - 1, m.height - 1], radius=max(0, radio * ss), fill=255)
    return np.asarray(m.resize((int(round(w)), int(round(h))), Image.BOX))


_FU = {}


def fuente(tam, peso=400, mono=False):
    """Geist / Geist Mono (las del panel) con el peso como número (100-900)."""
    clave = (round(tam * 4) / 4, int(peso), mono)
    if clave not in _FU:
        f = ImageFont.truetype(os.path.join(FUENTES, 'GeistMono-Variable.woff2' if mono else 'Geist-Variable.woff2'),
                               clave[0])
        f.set_variation_by_axes([clave[1]])
        _FU[clave] = f
    return _FU[clave]


def miles(v):
    return '{:,}'.format(int(round(v))).replace(',', '.')


# ─── Fondo con parallax ───────────────────────────────────────────────────

class Fondo:
    """El fondo azul noche de la v2-v9 (armar2.hacer_fondo), 25 % más grande que el cuadro: se mueve una fracción de
    lo que se mueve la cámara (parallax) y así el panel parece flotar delante."""

    MARGEN = 1.25

    def __init__(self, parallax=0.12, semilla=3):
        self.parallax = parallax
        w, h = int(W * self.MARGEN), int(H * self.MARGEN)
        y, x = np.mgrid[0:h, 0:w].astype(np.float32)
        x = x - (w - W) / 2
        y = y - (h - H) / 2
        base = np.zeros((h, w, 3), np.float32)
        base += np.array([7, 12, 20], np.float32) * (1 - lim_np(y / H))[..., None] + \
            np.array([3, 5, 9], np.float32) * lim_np(y / H)[..., None]

        def brillo(cx, cy, r, col, a):
            d = ((x - cx) ** 2 + (y - cy) ** 2) / (r * r)
            return (np.exp(-d) * a)[..., None] * np.array(col, np.float32)

        base += brillo(960, 430, 780, (0, 110, 140), 0.30)
        base += brillo(1750, 1080, 620, (30, 50, 130), 0.20)
        base += brillo(120, 60, 520, (0, 80, 110), 0.14)
        punto = (((x + 3600) % 36 < 1.6) & ((y + 3600) % 36 < 1.6)).astype(np.float32)
        caida = np.exp(-(((x - 960) / 1100) ** 2 + ((y - 480) / 720) ** 2))
        base += (punto * caida)[..., None] * np.array([20, 32, 46], np.float32) * 0.6
        vin = 1 - 0.32 * (((x - 960) / 1100) ** 2 + ((y - 540) / 820) ** 2)
        base *= np.clip(vin, 0.55, 1)[..., None]
        base += np.random.default_rng(semilla).uniform(-0.7, 0.7, base.shape)
        self.im = np.clip(base, 0, 255).astype(np.uint8)

    def cuadro(self, cam_xy, z, origen=(W / 2, H / 2)):
        """El fondo para la cámara en (cx, cy) con zoom z: se corre parallax × lo que se corrió la cámara desde
        `origen` (fijo: así cada tramo, en su proceso, da el mismo fondo). Más allá del margen, se refleja."""
        dx = (cam_xy[0] - origen[0]) * self.parallax * min(z, 2.0)
        dy = (cam_xy[1] - origen[1]) * self.parallax * min(z, 2.0)
        mx, my = (self.im.shape[1] - W) / 2, (self.im.shape[0] - H) / 2
        m = np.float32([[1, 0, -(mx + dx)], [0, 1, -(my + dy)]])
        return cv2.warpAffine(self.im, m, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def lim_np(a):
    return np.clip(a, 0, 1)


# ─── Fuentes de imagen (lo que se pega en una placa) ──────────────────────

class Fuente:
    """Algo que da una imagen RGBA premultiplicada para un tiempo t. ancho/alto en unidades del mundo; ss = px de la
    imagen por unidad del mundo (1 en las capturas, 2 en los recortes supermuestreados)."""
    ancho = alto = 0
    ss = 1.0

    def imagen(self, t):
        raise NotImplementedError

    def movimiento(self, t0, t1):
        """Cuánto se mueve el contenido por dentro (unidades del mundo) entre t0 y t1: el scroll."""
        return 0.0

    def clave(self, t):
        return id(self)


class Imagen(Fuente):
    """Una imagen fija (PIL o numpy RGB/RGBA). radio: esquinas redondeadas (unidades del mundo)."""

    def __init__(self, im, ss=1.0, radio=0.0, premultiplicada=False):
        a = _rgba(im, premultiplicada)
        if radio > 0:
            m = caja_redonda(a.shape[1], a.shape[0], radio * ss).astype(np.uint16)
            a = (a.astype(np.uint16) * m[..., None] // 255).astype(np.uint8)
        self.im = a
        self.ss = float(ss)
        self.ancho, self.alto = a.shape[1] / ss, a.shape[0] / ss
        self.opaca = bool(a[..., 3].min() == 255)

    def imagen(self, t):
        return self.im


class Ventana(Fuente):
    """La captura dentro de una ventana (barra de título con los tres puntos, esquinas redondeadas, borde), como
    armar2.componer_ventana pero como una imagen sola, para moverla en 3D. La barra se dibuja a ×4 y se reduce."""

    BARRA = 34

    def __init__(self, im, titulo='', radio=12):
        page = _rgba(im)
        w, h = page.shape[1], page.shape[0] + self.BARRA
        S = 4
        barra = Image.new('RGBA', (w * S, self.BARRA * S), (13, 19, 27, 255))
        d = ImageDraw.Draw(barra)
        for i in range(3):
            px, py, r = (20 + i * 20) * S, self.BARRA * S / 2, 5.5 * S
            d.ellipse([px - r, py - r, px + r, py + r], fill=(58, 68, 82, 255))
        d.text((w * S / 2, self.BARRA * S / 2), titulo, font=fuente(14.5 * S, 500), fill=(146, 160, 178, 255),
               anchor='mm')
        d.line([(0, self.BARRA * S - 2), (w * S, self.BARRA * S - 2)], fill=(28, 38, 50, 255), width=S)
        barra = np.asarray(barra.resize((w, self.BARRA), Image.LANCZOS))
        out = np.zeros((h, w, 4), np.uint8)
        out[:self.BARRA] = _rgba(barra)
        out[self.BARRA:] = page
        m = caja_redonda(w, h, radio).astype(np.uint16)
        borde = (caja_redonda(w, h, radio).astype(np.int16) - cv2.erode(caja_redonda(w, h, radio), np.ones((3, 3),
                 np.uint8)).astype(np.int16)).clip(0, 255).astype(np.uint16)
        out = (out.astype(np.uint16) * m[..., None] // 255)
        col = np.array([40, 54, 72], np.uint16)
        out[..., :3] = (out[..., :3] * (255 - borde[..., None]) // 255 + col * borde[..., None] // 255)
        self.im = out.astype(np.uint8)
        self.ss = 1.0
        self.ancho, self.alto = w, h
        self.desde_y = self.BARRA          # la página empieza 34 unidades más abajo que el borde de la ventana

    def imagen(self, t):
        return self.im


class Secuencia(Fuente):
    """Cuadros PNG numerados (f-00000.png, …) filmados a `fps`: las tomas del mapa en vivo de mapa8/ y mapa9/ (30 fps,
    1920×1080; la principal de mapa8/ es el mapa en pantalla completa). imagen(t) da el cuadro de (t - t0) × fps +
    desde, y se queda en el primero o el último fuera de rango. Un video de 60 fps repite cada cuadro dos veces, pero
    la cámara se mueve a 60 sobre él."""

    def __init__(self, carpeta, t0=0.0, fps=30, desde=0, ss=1.0):
        self.carpeta, self.t0, self.fps, self.desde, self.ss = carpeta, float(t0), fps, int(desde), float(ss)
        self.n = len([f for f in os.listdir(carpeta) if f.startswith('f-') and f.endswith('.png')])
        if not self.n:
            raise FileNotFoundError('No hay cuadros f-*.png en %s' % carpeta)
        prim = cv2.imread(os.path.join(carpeta, 'f-00000.png'), cv2.IMREAD_COLOR)
        self.ancho, self.alto = prim.shape[1] / ss, prim.shape[0] / ss
        self.opaca = True
        self._cache = {}

    def cuadro_en(self, t):
        return int(lim(round((t - self.t0) * self.fps) + self.desde, 0, self.n - 1))

    def clave(self, t):
        return (id(self), self.cuadro_en(t))

    def imagen(self, t):
        k = self.cuadro_en(t)
        if k not in self._cache:
            if len(self._cache) > 6:
                self._cache.clear()
            bgr = cv2.imread(os.path.join(self.carpeta, 'f-%05d.png' % k), cv2.IMREAD_COLOR)
            self._cache[k] = _rgba(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        return self._cache[k]


class PaginaDesplazable(Fuente):
    """Una página que baja de verdad: la barra de arriba (alto `arriba`) y el menú (ancho `menu`) quedan fijos y el
    contenido sale de la tira (Pantallas.tiras: el contenido de la captura de arriba y de las bajadas, pegado; o la
    columna de contenido de una captura completa de nitidas10). scroll: una Pista10 con los px bajados (0 = la
    captura de arriba). ss: px de la imagen por px CSS (2 con las capturas de nitidas10). Todo en px CSS."""

    def __init__(self, base, tira, scroll, arriba=64, menu=276, ss=1.0):
        self.base = np.asarray(base.convert('RGB') if isinstance(base, Image.Image) else base)
        self.tira = np.asarray(tira.convert('RGB') if isinstance(tira, Image.Image) else tira)
        self.scroll = scroll
        self.ss = float(ss)
        self.arriba, self.menu = arriba, menu
        self.alto_vista = self.base.shape[0] / self.ss - arriba
        self.smax = self.tira.shape[0] / self.ss - self.alto_vista
        self.ancho, self.alto = self.base.shape[1] / self.ss, self.base.shape[0] / self.ss
        self.opaca = True
        self._cache = {}

    def _s(self, t):
        return lim(float(self.scroll(t)), 0, self.smax)

    def clave(self, t):
        return (id(self), round(self._s(t) * self.ss * 8) / 8)

    def imagen(self, t):
        sp = self._s(t) * self.ss                    # en px de la imagen
        k = round(sp * 8) / 8
        if k in self._cache:
            return self._cache[k]
        im = self.base.copy()
        a0, m0 = int(round(self.arriba * self.ss)), int(round(self.menu * self.ss))
        alto = self.base.shape[0] - a0
        i = int(math.floor(k))
        f = k - i
        a = self.tira[i:i + alto]
        if f > 1e-3 and i + 1 + alto <= self.tira.shape[0]:
            b = self.tira[i + 1:i + 1 + alto]
            a = cv2.addWeighted(a, 1 - f, b, f, 0)
        im[a0:a0 + a.shape[0], m0:m0 + a.shape[1]] = a
        out = _rgba(im)
        if len(self._cache) > 24:
            self._cache.clear()
        self._cache[k] = out
        return out

    def movimiento(self, t0, t1):
        return abs(self._s(t1) - self._s(t0))

    def caja_a(self, caja, medida_en, s):
        """Una caja medida en la captura bajada `medida_en` px, en coordenadas de pantalla con el scroll en s (solo
        para lo que está en el contenido: debajo de la barra y a la derecha del menú)."""
        x0, y0, x1, y1 = caja
        d = medida_en - s
        return (x0, y0 + d, x1, y1 + d)


class Recorte(Fuente):
    """Un pedazo de otra fuente (caja en unidades de esa fuente), supermuestreado ×ss: Lanczos + nitidez suave, y
    encima lo que haya que volver a escribir nítido (contadores) a ×ss. Es la tarjeta que se despega en elevar()."""

    def __init__(self, origen, caja, ss=2.0, radio=0.0, redibujos=(), nitidez=0.45):
        self.origen, self.caja, self.ss = origen, tuple(float(v) for v in caja), float(ss)
        self.radio, self.redibujos, self.nitidez = radio, list(redibujos), nitidez
        x0, y0, x1, y1 = self.caja
        self.ancho, self.alto = x1 - x0, y1 - y0
        self._cache = {}
        self._mascara = None

    def clave(self, t):
        return (id(self), self.origen.clave(t)) + tuple(r.clave(t) for r in self.redibujos)

    def imagen(self, t):
        k = self.clave(t)
        if k in self._cache:
            return self._cache[k]
        src = self.origen.imagen(t)
        s0 = self.origen.ss
        x0, y0, x1, y1 = self.caja
        w, h = int(round(self.ancho * self.ss)), int(round(self.alto * self.ss))
        k_ = self.ss / s0
        m = np.float32([[k_, 0, -x0 * self.ss], [0, k_, -y0 * self.ss]])
        rgba = cv2.warpAffine(src, m, (w, h), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
        if self.nitidez > 0 and k_ > 1.01:
            bl = cv2.GaussianBlur(rgba, (0, 0), 0.6 * k_)
            rgba = cv2.addWeighted(rgba, 1 + self.nitidez, bl, -self.nitidez, 0)
        if self.redibujos:
            pil = Image.fromarray(rgba[..., :3].copy(), 'RGB')
            for r in self.redibujos:
                r.dibujar(pil, t, self.ss, (x0, y0))
            rgba = np.dstack([np.asarray(pil), rgba[..., 3]])
        if self.radio > 0:
            if self._mascara is None:
                self._mascara = caja_redonda(w, h, self.radio * self.ss).astype(np.uint16)
            rgba = (rgba.astype(np.uint16) * self._mascara[..., None] // 255).astype(np.uint8)
        if len(self._cache) > 32:
            self._cache.clear()
        self._cache[k] = rgba
        return rgba


class ConContadores(Fuente):
    """Otra fuente con contadores escritos encima a su misma escala (para contar sobre la página, sin elevar)."""

    def __init__(self, origen, contadores):
        self.origen, self.contadores = origen, list(contadores)
        self.ancho, self.alto, self.ss = origen.ancho, origen.alto, origen.ss
        self._k, self._im = None, None

    def clave(self, t):
        return (id(self), self.origen.clave(t)) + tuple(c.clave(t) for c in self.contadores)

    def imagen(self, t):
        k = self.clave(t)
        if k != self._k:
            src = self.origen.imagen(t)
            pil = Image.fromarray(src[..., :3].copy(), 'RGB')
            for c in self.contadores:
                c.dibujar(pil, t, self.ss, (0.0, 0.0))
            self._im = np.dstack([np.asarray(pil), src[..., 3]])
            self._k = k
        return self._im

    def movimiento(self, t0, t1):
        return self.origen.movimiento(t0, t1)


class Contador:
    """Un número del panel que cuenta hasta su valor: tapa el número de la captura con el fondo de la tarjeta y lo
    escribe con Geist Mono (la letra del panel) al tamaño y peso medidos. x, y: comienzo y línea de base, en px de
    la captura. Por omisión, el de las tarjetas del Inicio (font-mono text-title font-semibold: 27,75 px, peso 680,
    medido contra inicio9). Antes de t0 deja la captura como está; en t0 el número de la captura se funde en
    `aparecer` s con el que cuenta (desde `desde`, curva expo-out, `dur` s): sin el salto de 353 a 0."""

    def __init__(self, valor, x, y, t0, dur=1.2, desde=0, tapa=None, tam=27.75, peso=680, color=TEXTO,
                 fondo=SUPERFICIE, formato=miles, curva='expo', mono=True, aparecer=0.12):
        self.valor, self.x, self.y, self.t0, self.dur, self.desde = valor, x, y, t0, dur, desde
        self.tapa, self.tam, self.peso, self.color, self.fondo = tapa, tam, peso, color, fondo
        self.formato, self.curva, self.mono, self.aparecer = formato, M.curva(curva), mono, aparecer

    def valor_en(self, t):
        p = lim((t - self.t0) / self.dur) if self.dur > 0 else float(t >= self.t0)
        return self.desde + (self.valor - self.desde) * self.curva(p)

    def _mezcla(self, t):
        return lim((t - self.t0) / self.aparecer) if self.aparecer > 0 else float(t >= self.t0)

    def clave(self, t):
        if t < self.t0:
            return ('c', None)
        return ('c', self.formato(self.valor_en(t)), round(self._mezcla(t), 2))

    def dibujar(self, pil, t, ss, origen):
        if t < self.t0:
            return
        ox, oy = origen
        a = self._mezcla(t)
        caja = None
        if self.tapa:
            x0, y0, x1, y1 = self.tapa
            caja = tuple(int(round(v)) for v in ((x0 - ox) * ss, (y0 - oy) * ss, (x1 - ox) * ss, (y1 - oy) * ss))
            antes = pil.crop(caja) if a < 1 else None
        d = ImageDraw.Draw(pil)
        if caja:
            d.rectangle([caja[0], caja[1], caja[2] - 1, caja[3] - 1], fill=self.fondo)
        d.text(((self.x - ox) * ss, (self.y - oy) * ss), self.formato(self.valor_en(t)),
               font=fuente(self.tam * ss, self.peso, self.mono), fill=self.color, anchor='ls')
        if caja and a < 1:
            pil.paste(Image.blend(antes, pil.crop(caja), a), caja[:2])


class ConEsquinas(Fuente):
    """Otra fuente con las esquinas de abajo (o todas) redondeadas: la página dentro de una ventana."""

    def __init__(self, origen, radio=12, solo_abajo=True):
        self.origen, self.radio, self.solo_abajo = origen, radio, solo_abajo
        self.ancho, self.alto, self.ss = origen.ancho, origen.alto, origen.ss
        w, h = int(round(self.ancho * self.ss)), int(round(self.alto * self.ss))
        r = radio * self.ss
        S = 4
        m = Image.new('L', (w * S, h * S), 0)
        y0 = -2 * r * S if solo_abajo else 0
        ImageDraw.Draw(m).rounded_rectangle([0, y0, w * S - 1, h * S - 1], radius=r * S, fill=255)
        self.mascara = np.asarray(m.resize((w, h), Image.BOX)).astype(np.uint16)
        self._k, self._im = None, None
        self.opaca = getattr(origen, 'opaca', False)
        self.inset = radio                      # lo transparente está en las esquinas: a esta distancia del borde

    def clave(self, t):
        return ('esq', self.origen.clave(t))

    def imagen(self, t):
        k = self.origen.clave(t)
        if k != self._k:
            self._im = (self.origen.imagen(t).astype(np.uint16) * self.mascara[..., None] // 255).astype(np.uint8)
            self._k = k
        return self._im

    def movimiento(self, t0, t1):
        return self.origen.movimiento(t0, t1)


BARRA_VENTANA = 34


def barra_ventana(ancho, titulo, radio=12, alto=BARRA_VENTANA):
    """La barra de título de la ventana (la de armar2.componer_ventana), con las esquinas de arriba redondeadas y el
    texto y los bordes suavizados (dibujada a ×4)."""
    S = 4
    im = Image.new('RGBA', (int(ancho * S), alto * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, ancho * S - 1, (alto + radio * 2) * S], radius=radio * S, fill=(13, 19, 27, 255),
                        outline=(40, 54, 72, 255), width=S)
    for i in range(3):
        px, py, r = (20 + i * 20) * S, alto * S / 2, 5.5 * S
        d.ellipse([px - r, py - r, px + r, py + r], fill=(58, 68, 82, 255))
    d.text((ancho * S / 2, alto * S / 2), titulo, font=fuente(14.5 * S, 500), fill=(146, 160, 178, 255), anchor='mm')
    d.line([(0, alto * S - S), (ancho * S, alto * S - S)], fill=(28, 38, 50, 255), width=S)
    return im.resize((int(ancho), alto), Image.LANCZOS)


def sombra_ventana(ancho, alto, desv=46, alfa=0.8, radio=12):
    """Sombra grande y suave para la ventana flotando (se pone debajo, un poco corrida hacia abajo)."""
    pad = int(desv * 2.6)
    m = np.zeros((alto + 2 * pad, ancho + 2 * pad), np.uint8)
    m[pad:pad + alto, pad:pad + ancho] = caja_redonda(ancho, alto, radio)
    peq = cv2.resize(m, (m.shape[1] // 4, m.shape[0] // 4), interpolation=cv2.INTER_AREA)
    peq = cv2.GaussianBlur(peq, (0, 0), desv / 4)
    m = cv2.resize(peq, (m.shape[1], m.shape[0]), interpolation=cv2.INTER_LINEAR)
    out = np.zeros(m.shape + (4,), np.uint8)
    out[..., 3] = (m.astype(np.float32) * alfa).astype(np.uint8)
    return out, pad


# ─── Placas y cámara ──────────────────────────────────────────────────────

class Placa:
    """Una fuente puesta en el mundo en (x, y). escala: Pista10 (alrededor del centro de la placa); desp: Pista10
    (dx, dy) en unidades del mundo; opacidad: Pista10. capa 'fondo' (la página) o 'frente' (lo que se eleva)."""

    def __init__(self, fuente_, x=0.0, y=0.0, capa='fondo'):
        self.fuente = fuente_
        self.x, self.y = float(x), float(y)
        self.escala = M.Pista10(1.0)
        self.desp = M.Pista10((0.0, 0.0))
        self.opacidad = M.Pista10(1.0)
        self.capa = capa
        self.visible = (-1e9, 1e9)
        self._mips = {}

    @property
    def caja_mundo(self):
        return (self.x, self.y, self.x + self.fuente.ancho, self.y + self.fuente.alto)

    def mundo(self, px, py):
        """Un punto de la captura (px de la fuente / ss) → mundo, sin la escala animada."""
        return self.x + px, self.y + py

    def matriz(self, t):
        """Fuente (px de su imagen) → mundo, con la escala alrededor del centro y el desplazamiento."""
        f = self.fuente
        s = self.escala(t)
        dx, dy = self.desp(t)
        cx, cy = self.x + f.ancho / 2, self.y + f.alto / 2
        k = s / f.ss
        return np.array([[k, 0, cx - s * f.ancho / 2 + dx], [0, k, cy - s * f.alto / 2 + dy], [0, 0, 1]], np.float64)

    def mip(self, img, nivel, clave):
        if nivel == 0:
            return img
        k = (clave, nivel)
        if k not in self._mips:
            if len(self._mips) > 8:
                self._mips.clear()
            a = img
            for _ in range(nivel):
                a = cv2.resize(a, ((a.shape[1] + 1) // 2, (a.shape[0] + 1) // 2), interpolation=cv2.INTER_AREA)
            self._mips[k] = a
        return self._mips[k]


class Camara:
    """Cámara sobre el mundo: (cx, cy) es el punto del mundo en el centro del cuadro y z los px del cuadro por unidad.
    giro (grados, alrededor del eje de la vista), rx / ry: inclinación en grados (perspectiva con foco `focal`)."""

    def __init__(self, cx=W / 2, cy=H / 2, z=1.0, focal=2400.0):
        self.pos = M.Pista10((float(cx), float(cy), float(z)))
        self.giro = M.Pista10(0.0)
        self.incl = M.Pista10((0.0, 0.0))
        self.focal = focal

    def ir(self, t, enc, dur=0.9, curva='cine'):
        self.pos.ir(t, enc, dur, curva)

    def resorte(self, t, enc, respuesta=0.75, amortiguacion=0.92):
        self.pos.resorte(t, enc, respuesta, amortiguacion)

    def matriz(self, t):
        cx, cy, z = self.pos(t)
        g = math.radians(self.giro(t))
        rx, ry = (math.radians(a) for a in self.incl(t))
        if abs(rx) < 1e-5 and abs(ry) < 1e-5:
            c, s = math.cos(g) * z, math.sin(g) * z
            return np.array([[c, -s, W / 2 - c * cx + s * cy], [s, c, H / 2 - s * cx - c * cy], [0, 0, 1]], np.float64)
        f = self.focal
        D = f / z
        Rx = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]])
        Ry = np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]])
        Rz = np.array([[math.cos(g), -math.sin(g), 0], [math.sin(g), math.cos(g), 0], [0, 0, 1]])
        R = Rz @ Ry @ Rx
        Mx = np.column_stack([R[:, 0], R[:, 1], -cx * R[:, 0] - cy * R[:, 1] + np.array([0, 0, D])])
        K = np.array([[f, 0, W / 2], [0, f, H / 2], [0, 0, 1]])
        return K @ Mx

    def a_cuadro(self, t, x, y):
        m = self.matriz(t)
        p = m @ np.array([x, y, 1.0])
        return p[0] / p[2], p[1] / p[2]


def encuadre_caja(caja, zona=ZONA_UTIL, margen=0.06, zmin=0.3, zmax=2.2):
    """(cx, cy, z) para que la caja del mundo entre en la zona del cuadro con `margen` (fracción) alrededor."""
    x0, y0, x1, y1 = caja
    zx0, zy0, zx1, zy1 = zona
    zw, zh = (zx1 - zx0) * (1 - 2 * margen), (zy1 - zy0) * (1 - 2 * margen)
    z = lim(min(zw / max(1e-6, x1 - x0), zh / max(1e-6, y1 - y0)), zmin, zmax)
    # el centro de la caja va al centro de la zona
    fx, fy = (zx0 + zx1) / 2, (zy0 + zy1) / 2
    cx = (x0 + x1) / 2 - (fx - W / 2) / z
    cy = (y0 + y1) / 2 - (fy - H / 2) / z
    return (cx, cy, z)


def limitar(enc, caja_mundo, zona=(0, 0, W, H)):
    """Corre la cámara para no mostrar fuera de la página (si la página es más grande que el cuadro)."""
    cx, cy, z = enc
    x0, y0, x1, y1 = caja_mundo
    hw, hh = W / 2 / z, H / 2 / z
    if x1 - x0 >= 2 * hw:
        cx = lim(cx, x0 + hw, x1 - hw)
    if y1 - y0 >= 2 * hh:
        cy = lim(cy, y0 + hh, y1 - hh)
    return (cx, cy, z)


def encuadre_completo(placa, arriba=0.0):
    """Pantalla llena: el ancho de la placa = el ancho del cuadro, pegada arriba (deja la franja de subtítulos)."""
    x0, y0, x1, y1 = placa.caja_mundo
    z = W / (x1 - x0)
    return ((x0 + x1) / 2, y0 + (H / 2 - arriba) / z, z)


# ─── Ajuste de cajas a los bordes reales ──────────────────────────────────

def ajustar_caja(im, caja, radio=10, umbral=6.0):
    """Corre cada lado de la caja (px de la captura) hasta el borde visible más cercano (dentro de ±radio): el foco o
    el recorte quedan exactamente sobre la tarjeta aunque la medición venga corrida un par de px."""
    a = np.asarray(im.convert('L') if isinstance(im, Image.Image) else cv2.cvtColor(im[..., :3], cv2.COLOR_RGB2GRAY),
                   np.float32)
    x0, y0, x1, y1 = (int(round(v)) for v in caja)
    h, w = a.shape

    def mejor(perfil, centro):
        idx = np.arange(len(perfil))
        g = perfil * np.exp(-((idx - centro) / (radio * 0.9)) ** 2)
        k = int(np.argmax(g))
        return k if perfil[k] > umbral else None

    out = [x0, y0, x1, y1]
    ys0, ys1 = max(0, y0 + 4), min(h, y1 - 4)
    xs0, xs1 = max(0, x0 + 4), min(w, x1 - 4)
    for lado, (lo, hi) in enumerate(((x0 - radio, x0 + radio), (y0 - radio, y0 + radio),
                                     (x1 - radio, x1 + radio), (y1 - radio, y1 + radio))):
        lo, hi = max(1, lo), min((w if lado in (0, 2) else h) - 1, hi)
        if hi <= lo:
            continue
        if lado in (0, 2):
            banda = a[ys0:ys1, lo - 1:hi + 1]
            perfil = np.abs(np.diff(banda, axis=1)).mean(axis=0)
        else:
            banda = a[lo - 1:hi + 1, xs0:xs1]
            perfil = np.abs(np.diff(banda, axis=0)).mean(axis=1)
        k = mejor(perfil, (out[lado] - lo))
        if k is not None:
            out[lado] = lo + k
    return tuple(out)


# ─── Sprites (los de mg10 o cualquier secuencia RGBA) ─────────────────────

class _Pegado:
    def __init__(self, sprite, t0, t1, x, y, placa, ancla, capa, opacidad, sobre=None):
        self.sprite, self.t0, self.t1 = sprite, t0, t1
        self.x, self.y, self.placa, self.ancla, self.capa = x, y, placa, ancla, capa
        self.opacidad = opacidad
        self.sobre = sobre


def pegar_subpixel(dst, rgba, fx, fy, opacidad=1.0):
    """Pega rgba (premultiplicado) con su (0, 0) en (fx, fy) reales del cuadro, sin redondear a px enteros."""
    ix, iy = int(math.floor(fx)), int(math.floor(fy))
    dx, dy = fx - ix, fy - iy
    if abs(dx) < 1e-3 and abs(dy) < 1e-3:
        componer(dst, rgba, ix, iy, opacidad)
        return
    h, w = rgba.shape[:2]
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    s = cv2.warpAffine(rgba, m, (w + 1, h + 1), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    componer(dst, s, ix, iy, opacidad)


# ─── Elevación ────────────────────────────────────────────────────────────

class Elevacion:
    def __init__(self, nivel, placa, sombra, brillo, atenuar, desenfoque):
        self.nivel, self.placa, self.sombra, self.brillo = nivel, placa, sombra, brillo
        self.atenuar, self.desenfoque = atenuar, desenfoque


def _sombra_img(w, h, radio, desv, ss=1.0, alfa=0.62):
    pad = int(desv * 3)
    m = np.zeros((h + 2 * pad, w + 2 * pad), np.uint8)
    m[pad:pad + h, pad:pad + w] = caja_redonda(w, h, radio)
    m = cv2.GaussianBlur(m, (0, 0), desv)
    a = (m.astype(np.float32) * alfa).astype(np.uint8)
    out = np.zeros(m.shape + (4,), np.uint8)
    out[..., 3] = a
    return out, pad


def _brillo_img(w, h, radio, ss, color=CIAN):
    """Borde cian de 1,5 px con un halo, en una imagen con margen (premultiplicada)."""
    pad = int(26 * ss)
    W_, H_ = w + 2 * pad, h + 2 * pad
    S = 2
    m = Image.new('L', (W_ * S, H_ * S), 0)
    ImageDraw.Draw(m).rounded_rectangle([pad * S, pad * S, (pad + w) * S - 1, (pad + h) * S - 1],
                                        radius=radio * ss * S + 1, outline=255, width=max(2, int(round(1.6 * ss * S))))
    linea = np.asarray(m.resize((W_, H_), Image.BOX), np.float32) / 255
    halo = cv2.GaussianBlur(linea, (0, 0), 9 * ss) * 3.2 + cv2.GaussianBlur(linea, (0, 0), 3 * ss) * 1.1
    a = np.clip(linea * 0.95 + halo * 0.55, 0, 1)
    # nada adentro de la tarjeta (el halo interior taparía el contenido)
    adentro = np.zeros((H_, W_), np.float32)
    adentro[pad + 3:pad + h - 3, pad + 3:pad + w - 3] = 1
    a = a * (1 - adentro * 0.85)
    col = np.array(color, np.float32)
    rgb = np.clip(a[..., None] * col[None, None, :], 0, 255)
    return np.dstack([rgb, a * 255]).astype(np.uint8), pad


# ─── Escena ───────────────────────────────────────────────────────────────

class Escena:
    """Placas en el mundo + cámara + fondo con parallax + elevaciones + sprites. cuadro(t) → PIL RGB W×H."""

    def __init__(self, fps=60, fondo=None, obturador=OBTURADOR, desenfoque=True):
        self.fps = fps
        self.cam = Camara()
        self.placas = []
        self.elevaciones = []
        self.pegados = []
        self.fondo = fondo if fondo is not None else Fondo()
        self.obturador = obturador
        self.desenfoque = desenfoque
        self.atenuar_extra = M.Pista10(0.0)       # oscurecer la escena entera (detrás de un rótulo grande)
        self.ultimo_k = 1

    # -- armado --
    def placa(self, fuente_, x=0.0, y=0.0, capa='fondo'):
        p = Placa(fuente_, x, y, capa)
        self.placas.append(p)
        return p

    def encuadre(self, placa, caja, margen=0.06, zona=ZONA_UTIL, zmax=2.2, limitar_a=None):
        """Encuadre de una caja en px de la captura de esa placa (convierte al mundo y limita a la página)."""
        x0, y0, x1, y1 = caja
        X0, Y0 = placa.mundo(x0, y0)
        X1, Y1 = placa.mundo(x1, y1)
        enc = encuadre_caja((X0, Y0, X1, Y1), zona, margen, zmax=zmax)
        return limitar(enc, limitar_a or placa.caja_mundo)

    def elevar(self, t0, t1, placa, caja, escala=1.08, subir=4.0, ss=2.0, contadores=(), radio=0.0,
               respuesta=0.55, amortiguacion=0.72, salida=0.45, atenuar=0.5, desenfoque=5.0, brillo=1.0,
               ajustar=True):
        """Despega de la página la caja (px de la captura) entre t0 y t1: crece `escala`, sube `subir` unidades, con
        sombra y borde cian; el resto se oscurece (`atenuar`) y se desenfoca (`desenfoque` px). Con contadores, sus
        números se escriben a ×ss sobre el recorte."""
        if ajustar:
            k = placa.fuente.ss
            c2 = ajustar_caja(placa.fuente.imagen(t0)[..., :3], [v * k for v in caja], radio=int(round(3 * k)))
            caja = tuple(v / k for v in c2)
        rec = Recorte(placa.fuente, caja, ss=ss, radio=radio, redibujos=contadores)
        X0, Y0 = placa.mundo(caja[0], caja[1])
        nivel = M.Pista10(0.0)
        nivel.resorte(t0, 1.0, respuesta, amortiguacion)
        nivel.ir(t1, 0.0, salida, 'suave')
        w, h = rec.ancho, rec.alto
        sombra, pad_s = _sombra_img(int(round(w * ss)), int(round(h * ss)), radio * ss, 14 * ss, alfa=0.7)
        brillo_im, pad_b = _brillo_img(int(round(w * ss)), int(round(h * ss)), radio, ss)
        frente = Placa(rec, X0, Y0, capa='frente')
        som = Placa(Imagen(sombra, ss=ss, premultiplicada=True), X0 - pad_s / ss, Y0 - pad_s / ss, capa='frente')
        bri = Placa(Imagen(brillo_im, ss=ss, premultiplicada=True), X0 - pad_b / ss, Y0 - pad_b / ss, capa='frente')
        # las tres crecen alrededor del mismo centro; la tarjeta y el borde suben, la sombra baja (se despega)
        crece = _Segun(nivel, lambda n, t: 1.0 + (escala - 1.0) * n)
        for p_ in (frente, som, bri):
            p_.visible = (t0 - 0.01, t1 + salida + 0.05)
            p_.escala = crece
        frente.desp = bri.desp = _Segun(nivel, lambda n, t: (0.0, -subir * n))
        som.desp = _Segun(nivel, lambda n, t: (0.0, (10.0 - subir) * n))
        som.opacidad = _Segun(nivel, lambda n, t: lim(n))
        bri.opacidad = _Segun(nivel, lambda n, t: lim(n) * brillo * (0.82 + 0.18 * (0.5 + 0.5 * math.sin(t * 3.4))))
        el = Elevacion(nivel, frente, som, bri, atenuar, desenfoque)
        self.elevaciones.append(el)
        return el

    def anclar(self, sprite, t0, placa, punto, ancla=None, capa='arriba', opacidad=1.0, sobre=None):
        """Un sprite (mg10.Sprite) cuyo punto `ancla` (px del sprite) queda pegado al punto de la captura `punto`
        de la placa, siga la cámara lo que siga. sobre: la Elevacion de ese elemento, si está despegado (la llamada
        sigue al elemento elevado: su escala y su subida)."""
        p = _Pegado(sprite, t0, t0 + sprite.dur, punto[0], punto[1], placa, ancla or sprite.ancla, capa, opacidad,
                    sobre)
        self.pegados.append(p)
        return p

    def en_pantalla(self, sprite, t0, x, y, capa='arriba', opacidad=1.0):
        """Un sprite fijo en el cuadro: su ancla (la esquina de la tarjeta, en los rótulos) en (x, y) px del cuadro."""
        ax, ay = sprite.ancla
        p = _Pegado(sprite, t0, t0 + sprite.dur, x - ax, y - ay, None, (0, 0), capa, opacidad)
        self.pegados.append(p)
        return p

    # -- dibujo --
    def _visibles(self, t, capa, cam_m=None, Wd=W, Hd=H):
        ps = [p for p in self.placas if p.capa == capa and p.visible[0] <= t <= p.visible[1]]
        if cam_m is None or abs(cam_m[2, 0]) > 1e-12 or abs(cam_m[2, 1]) > 1e-12:
            return ps
        # una placa opaca (sin alfa) que cubre todo el cuadro tapa a las anteriores: no se dibujan
        for i in range(len(ps) - 1, 0, -1):
            p = ps[i]
            if not getattr(p.fuente, 'opaca', False) or p.opacidad(t) < 0.999:
                continue
            m = cam_m @ p.matriz(t)
            if abs(m[0, 1]) > 1e-9 or abs(m[1, 0]) > 1e-9:
                continue
            f = p.fuente
            r = getattr(f, 'inset', 0) * f.ss
            x0, y0 = m[0, 2] + m[0, 0] * r, m[1, 2] + m[1, 1] * r
            x1, y1 = m[0, 2] + m[0, 0] * (f.ancho * f.ss - r), m[1, 2] + m[1, 1] * (f.alto * f.ss - r)
            if x0 <= 0 and y0 <= 0 and x1 >= Wd and y1 >= Hd:
                return ps[i:]
        return ps

    def _dibujar_placa(self, acc, p, cam_m, t, rapido):
        Wd, Hd = acc.shape[1], acc.shape[0]
        f = p.fuente
        op = p.opacidad(t)
        if op <= 0.002:
            return
        img = f.imagen(t)
        m = cam_m @ p.matriz(t)
        afin = abs(m[2, 0]) < 1e-12 and abs(m[2, 1]) < 1e-12
        h, w = img.shape[:2]
        esq = np.array([[0, 0, 1], [w, 0, 1], [w, h, 1], [0, h, 1]], np.float64).T
        q = m @ esq
        if np.any(q[2] <= 1e-6):
            return
        qx, qy = q[0] / q[2], q[1] / q[2]
        x0, y0 = max(0, int(math.floor(qx.min())) - 1), max(0, int(math.floor(qy.min())) - 1)
        x1, y1 = min(Wd, int(math.ceil(qx.max())) + 1), min(Hd, int(math.ceil(qy.max())) + 1)
        if x1 <= x0 or y1 <= y0:
            return
        # escala efectiva (px del cuadro por px de la imagen) para elegir el nivel de detalle
        if afin:
            esc = math.sqrt(abs(np.linalg.det(m[:2, :2])))
        else:
            area = 0.5 * abs(np.dot(qx, np.roll(qy, 1)) - np.dot(qy, np.roll(qx, 1)))
            esc = math.sqrt(area / (w * h))
        nivel = 0
        while esc * (2 ** nivel) < 0.62 and nivel < 4:
            nivel += 1
        if nivel:
            img = p.mip(img, nivel, f.clave(t))
            k = 2 ** nivel
            m = m @ np.array([[k, 0, 0], [0, k, 0], [0, 0, 1]], np.float64)
            esc *= k
        mt = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], np.float64) @ m
        if rapido:
            interp = cv2.INTER_LINEAR
        else:
            interp = cv2.INTER_CUBIC if esc > 1.02 else cv2.INTER_LINEAR
        # quieto, a escala 1 y sin giro: alinear a px enteros (texto nítido)
        if afin and not rapido and abs(esc - 1) < 1e-3 and abs(mt[0, 1]) < 1e-6:
            mt[0, 2], mt[1, 2] = round(mt[0, 2]), round(mt[1, 2])
            interp = cv2.INTER_NEAREST
        if afin:
            sal = cv2.warpAffine(img, mt[:2].astype(np.float32), (x1 - x0, y1 - y0), flags=interp,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        else:
            sal = cv2.warpPerspective(img, mt, (x1 - x0, y1 - y0), flags=interp, borderMode=cv2.BORDER_CONSTANT,
                                      borderValue=0)
        componer(acc, sal, x0, y0, op)

    def nivel_elevacion(self, t):
        return max((e.nivel(t) for e in self.elevaciones), default=0.0)

    def _muestra(self, t, rapido, escala=1.0):
        """Una muestra de la escena en t. escala < 1: a menor resolución (las muestras de un desenfoque grande)."""
        cam_m = self.cam.matriz(t)
        cx, cy, z = self.cam.pos(t)
        acc = self.fondo.cuadro((cx, cy), z)
        if escala != 1.0:
            S = np.array([[escala, 0, 0], [0, escala, 0], [0, 0, 1]], np.float64)
            cam_m = S @ cam_m
            acc = cv2.resize(acc, (int(W * escala), int(H * escala)), interpolation=cv2.INTER_AREA)
        Wd, Hd = acc.shape[1], acc.shape[0]
        for p in self._visibles(t, 'fondo', cam_m, Wd, Hd):
            self._dibujar_placa(acc, p, cam_m, t, rapido)
        activas = [e for e in self.elevaciones if e.placa.visible[0] <= t <= e.placa.visible[1]]
        L = max((e.nivel(t) for e in activas), default=0.0)
        L = lim(L)
        if L > 0.004:
            bmax = max(e.desenfoque for e in activas)
            amax = max(e.atenuar for e in activas)
            if bmax > 0:
                peq = cv2.resize(acc, (Wd // 4, Hd // 4), interpolation=cv2.INTER_AREA)
                peq = cv2.GaussianBlur(peq, (0, 0), bmax * escala / 4)
                bl = cv2.resize(peq, (Wd, Hd), interpolation=cv2.INTER_LINEAR)
                acc = cv2.addWeighted(acc, 1 - L, bl, L, 0)
            acc = cv2.convertScaleAbs(acc, alpha=1 - amax * L)
        ext = self.atenuar_extra(t)
        if ext > 0.004:
            acc = cv2.convertScaleAbs(acc, alpha=1 - ext)
        for e in sorted(activas, key=lambda e: e.nivel(t)):
            if lim(e.nivel(t)) <= 0.004:
                continue
            for p_ in (e.sombra, e.placa, e.brillo):
                self._dibujar_placa(acc, p_, cam_m, t, rapido)
        for p in self._visibles(t, 'frente'):
            if not any(p is e.placa or p is e.sombra or p is e.brillo for e in self.elevaciones):
                self._dibujar_placa(acc, p, cam_m, t, rapido)
        return acc

    def _desplazamiento(self, ta, tb):
        """Cuánto se mueve la imagen (px del cuadro) entre ta y tb: esquinas de las placas visibles y scroll."""
        ma, mb = self.cam.matriz(ta), self.cam.matriz(tb)
        za = self.cam.pos(ta)[2]
        d = 0.0
        for p in self.placas:
            if not (p.visible[0] <= tb and ta <= p.visible[1]):
                continue
            f = p.fuente
            pa, pb = ma @ p.matriz(ta), mb @ p.matriz(tb)
            w, h = f.ancho * f.ss, f.alto * f.ss
            esq = np.array([[0, 0, 1], [w, 0, 1], [w, h, 1], [0, h, 1], [w / 2, h / 2, 1]], np.float64).T
            qa, qb = pa @ esq, pb @ esq
            qa, qb = qa[:2] / qa[2], qb[:2] / qb[2]
            # solo cuenta lo que está cerca del cuadro
            dd = np.hypot(*(qa - qb))
            d = max(d, float(dd.max()))
            d = max(d, f.movimiento(ta, tb) * za)
        return d

    def cuadro(self, t, rgb=True):
        sh = self.obturador / self.fps
        ta, tb = t - sh / 2, t + sh / 2
        K = 1
        if self.desenfoque and sh > 0:
            d = self._desplazamiento(ta, tb)
            K = int(min(K_MAX, max(1, math.ceil(d / PASO_PX))))
        if K == 1:
            out = self._muestra(t, rapido=False)
        else:
            acc = None
            pesos = [math.sin(math.pi * (i + 0.5) / K) ** 0.5 for i in range(K)]
            tot = sum(pesos)
            esc_m = 0.5 if K >= K_MEDIA else 1.0
            for i in range(K):
                ti = ta + sh * (i + 0.5) / K
                lin = a_lineal(self._muestra(ti, rapido=True, escala=esc_m))
                if acc is None:
                    acc = lin * (pesos[i] / tot)
                else:
                    cv2.scaleAdd(lin, pesos[i] / tot, acc, acc)
            if esc_m != 1.0:
                acc = cv2.resize(acc, (W, H), interpolation=cv2.INTER_LINEAR)
            out = a_srgb(acc)
        self._dibujar_pegados(out, t)
        self.ultimo_k = K
        return Image.fromarray(out, 'RGB') if rgb else out

    def _dibujar_pegados(self, out, t):
        cam_m = None
        for p in self.pegados:
            if not (p.t0 <= t < p.t1):
                continue
            fr = p.sprite.cuadro(t - p.t0)
            if fr is None:
                continue
            if p.placa is None:
                componer(out, fr, int(round(p.x)), int(round(p.y)), p.opacidad)
                continue
            if cam_m is None:
                cam_m = self.cam.matriz(t)
            if p.sobre is not None and p.sobre.placa.visible[0] <= t <= p.sobre.placa.visible[1]:
                rec = p.sobre.placa.fuente
                m = cam_m @ p.sobre.placa.matriz(t)
                q = m @ np.array([(p.x - rec.caja[0]) * rec.ss, (p.y - rec.caja[1]) * rec.ss, 1.0])
            else:
                wx, wy = p.placa.mundo(p.x, p.y)
                q = cam_m @ np.array([wx, wy, 1.0])
            fx, fy = q[0] / q[2], q[1] / q[2]
            ax, ay = p.ancla
            pegar_subpixel(out, fr, fx - ax, fy - ay, p.opacidad)


def ventana(esc, fuente_, x, y, titulo, radio=12, sombra=True):
    """La página dentro de una ventana flotante: sombra, barra de título (encima de la página, de y - 34 a y) y la
    página con las esquinas de abajo redondeadas. Devuelve la placa de la página (sus coordenadas = las de la
    captura) y guarda las otras en .barra y .sombra (para moverlas o apagarlas juntas)."""
    w, h = int(round(fuente_.ancho)), int(round(fuente_.alto))
    ps = None
    if sombra:
        im, pad = sombra_ventana(w, h + BARRA_VENTANA, radio=radio)
        ps = esc.placa(Imagen(im, premultiplicada=True), x - pad, y - BARRA_VENTANA - pad + 26)
    pb = esc.placa(Imagen(barra_ventana(w, titulo, radio)), x, y - BARRA_VENTANA)
    pp = esc.placa(ConEsquinas(fuente_, radio), x, y)
    pp.barra, pp.sombra = pb, ps
    return pp


class _Segun:
    """Una pista que se deriva de otra: fn(valor de la otra en t, t)."""

    def __init__(self, pista, fn):
        self.pista, self.fn = pista, fn

    def __call__(self, t):
        return self.fn(self.pista(t), t)
