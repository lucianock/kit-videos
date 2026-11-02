"""Voz narrada con la marca de tiempo de cada palabra (edge-tts, gratis, sin cuenta).

Las marcas por palabra son lo que permite que la cámara, los resaltados y los rótulos lleguen *con la palabra* que dice
la voz (mov10.aterrizar). Cada frase se sintetiza una sola vez y queda en caché (carpeta cache/voces del proyecto).

    import voz
    j1 = voz.Linea('El inicio muestra las ventas de hoy.', t0=1.3)
    j1.en('ventas')      -> segundo exacto en que empieza esa palabra (en la línea de tiempo del video)
    j1.v0, j1.fin, j1.pcm  -> comienzo, fin de la voz y el audio (float32, 48 kHz)

Voz por omisión: en-US-BrianMultilingualNeural (habla castellano neutro con muy
buena entonación). Para probar otras: `edge-tts --list-voices`; castellanas: es-AR-TomasNeural, es-AR-ElenaNeural,
es-MX-JorgeNeural, es-ES-AlvaroNeural... VOZ y VELOCIDAD también se cambian con variables de entorno.
"""
import asyncio
import hashlib
import json
import os
import re
import subprocess
import unicodedata

import edge_tts
import imageio_ffmpeg
import numpy as np

SR = 48000
FF = imageio_ffmpeg.get_ffmpeg_exe()
VOZ = os.environ.get('VOZ', 'en-US-BrianMultilingualNeural')
VELOCIDAD = os.environ.get('VELOCIDAD', '-3%')       # -3 %: ≈ 155 palabras por minuto, se entiende sin apuro
CACHE = os.environ.get('CACHE_VOCES', os.path.join(os.getcwd(), 'cache', 'voces'))


def norm(s):
    s = unicodedata.normalize('NFC', s.lower())
    return re.sub(r'[^0-9a-záéíóúüñ]', '', s)


async def _sintetizar(texto, mp3):
    palabras = []
    com = edge_tts.Communicate(texto, VOZ, rate=VELOCIDAD, boundary='WordBoundary')
    with open(mp3, 'wb') as f:
        async for parte in com.stream():
            if parte['type'] == 'audio':
                f.write(parte['data'])
            elif parte['type'] == 'WordBoundary':
                palabras.append({'ini': parte['offset'] / 1e7, 'dur': parte['duration'] / 1e7, 'texto': parte['text']})
    return palabras


def sintetizar(texto):
    """(pcm float32 mono 48 kHz, [{'ini', 'dur', 'texto'}]) de la frase; con caché."""
    os.makedirs(CACHE, exist_ok=True)
    base = os.path.join(CACHE, hashlib.sha1((VOZ + VELOCIDAD + texto).encode()).hexdigest()[:12])
    if not os.path.exists(base + '.json'):
        palabras = asyncio.run(_sintetizar(texto, base + '.mp3'))
        subprocess.run([FF, '-y', '-loglevel', 'error', '-i', base + '.mp3', '-ac', '1', '-ar', str(SR), '-f', 'f32le',
                        base + '.pcm'], check=True)
        with open(base + '.json', 'w', encoding='utf-8') as f:
            json.dump({'texto': texto, 'voz': VOZ, 'velocidad': VELOCIDAD, 'palabras': palabras}, f,
                      ensure_ascii=False)
    pcm = np.fromfile(base + '.pcm', dtype=np.float32)
    with open(base + '.json', encoding='utf-8') as f:
        return pcm, json.load(f)['palabras']


class Linea:
    """Una frase de voz puesta en la línea de tiempo: empieza a sonar en t0 (+ pre)."""

    def __init__(self, texto, t0, pre=0.0):
        self.texto = texto
        self.pcm, self.palabras = sintetizar(texto)
        self.v0 = t0 + pre
        self.dur = len(self.pcm) / SR
        self.fin = self.v0 + self.dur

    def en(self, palabra, n=1):
        """Segundo (en el video) en que empieza la n-ésima palabra que arranca con `palabra`."""
        objetivo, k = norm(palabra), 0
        for p in self.palabras:
            if norm(p['texto']).startswith(objetivo):
                k += 1
                if k == n:
                    return self.v0 + p['ini']
        raise KeyError('«%s» no está en: %s' % (palabra, self.texto))

    def trozos(self, max_chars=84):
        """Subtítulos: [(t0, t1, texto)] partidos en frases cortas, con el tiempo de sus palabras."""
        toks = self.texto.split()
        tiempos = []
        j = 0
        for tk in toks:
            t = None
            for k in range(j, min(j + 4, len(self.palabras))):
                if norm(self.palabras[k]['texto']) == norm(tk) and norm(tk):
                    t = self.v0 + self.palabras[k]['ini']
                    j = k + 1
                    break
            tiempos.append(t)
        for i, t in enumerate(tiempos):                       # lo que no se alineó, se reparte entre los vecinos
            if t is None:
                tiempos[i] = tiempos[i - 1] + 0.25 if i else self.v0
        out, cur, ini = [], [], None
        for tk, t in zip(toks, tiempos):
            if ini is None:
                ini = t
            cur.append(tk)
            if len(' '.join(cur)) >= max_chars or tk[-1] in '.:;?!':
                out.append([ini, ' '.join(cur)])
                cur, ini = [], None
        if cur:
            out.append([ini, ' '.join(cur)])
        res = []
        for i, (t, tx) in enumerate(out):
            t1 = out[i + 1][0] if i + 1 < len(out) else self.fin + 0.3
            res.append((t, t1, tx))
        return res


if __name__ == '__main__':
    import sys
    for texto in sys.argv[1:] or ['Hola: esta es la voz del video, con la marca de cada palabra.']:
        pcm, palabras = sintetizar(texto)
        print('%.2f s  %s' % (len(pcm) / SR, ' '.join('%s@%.2f' % (p['texto'], p['ini']) for p in palabras)))
