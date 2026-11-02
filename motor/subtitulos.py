"""Subtítulos grandes y legibles en un proyector: una franja oscura abajo y el texto de la voz, por frases cortas.

    subs = Subtitulos()
    subs.agregar(linea)          # una voz.Linea
    img = subs.dibujar(img, t)   # PIL RGB 1920×1080
"""
import os

from PIL import Image, ImageDraw, ImageFont

AQUI = os.path.dirname(os.path.abspath(__file__))
W, H = 1920, 1080
_FU = {}


def fuente(tam, peso=500):
    if (tam, peso) not in _FU:
        f = ImageFont.truetype(os.path.join(AQUI, 'fuentes', 'Geist-Variable.woff2'), tam)
        f.set_variation_by_axes([peso])
        _FU[(tam, peso)] = f
    return _FU[(tam, peso)]


class Subtitulos:
    def __init__(self, tam=46, ancho_max=1560, abajo=64, fundido=0.18):
        self.trozos = []
        self.tam, self.ancho_max, self.abajo, self.fundido = tam, ancho_max, abajo, fundido

    def agregar(self, linea, max_chars=84):
        self.trozos.extend(linea.trozos(max_chars))

    def _lineas(self, texto, f):
        lineas, cur = [], ''
        for p in texto.split():
            prueba = (cur + ' ' + p).strip()
            if f.getlength(prueba) > self.ancho_max and cur:
                lineas.append(cur)
                cur = p
            else:
                cur = prueba
        return lineas + [cur]

    def dibujar(self, img, t):
        for t0, t1, texto in self.trozos:
            if t0 - self.fundido <= t < t1:
                a = min(1.0, (t - t0 + self.fundido) / self.fundido, (t1 - t) / self.fundido)
                break
        else:
            return img
        f = fuente(self.tam, 560)
        lineas = self._lineas(texto, f)
        alto_l = int(self.tam * 1.36)
        caja_h = alto_l * len(lineas) + 30
        caja_w = max(f.getlength(li) for li in lineas) + 72
        capa = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(capa)
        y0 = H - self.abajo - caja_h
        d.rounded_rectangle(((W - caja_w) / 2, y0, (W + caja_w) / 2, y0 + caja_h), 16, fill=(0, 0, 0, int(170 * a)))
        for i, li in enumerate(lineas):
            d.text((W / 2, y0 + 15 + alto_l * i + alto_l / 2), li, font=f, fill=(255, 255, 255, int(255 * a)),
                   anchor='mm')
        base = img.convert('RGBA')
        base.alpha_composite(capa)
        return base.convert('RGB')
