"""mg10: motion graphics hechos con HTML/CSS/SVG y anime.js, filmados cuadro a cuadro con Chrome
sin cabeza (por CDP), con fondo transparente.

Cada plantilla de mg10/plantillas/ arma su animación con una línea de tiempo de anime.js (MIT) en pausa; mg10 la
lleva a cada instante con seek(ms) y saca una captura PNG con alfa. Es determinista (el mismo pedido da los mismos
cuadros, no depende del reloj ni de la velocidad de la PC) y queda en caché (mg10/cache/<hash>/), así armar10.py lo
pide en cada corrida sin volver a filmar. La letra es la del panel (Geist y Geist Mono de fuentes/), con el render de
texto de Chrome: el mismo motor que dibuja el panel.

    import mg10 as G
    s = G.sprite('rotulo', dict(numero='01', kicker='RECORRIDO DEL PANEL', titulo='Inicio',
                                bajada='Todo el negocio, de un vistazo'), fps=60)
    s.dur, s.ancho, s.alto, s.ancla
    s.cuadro(t)            # RGBA premultiplicado (numpy) del instante t (segundos desde que empieza), o None
    G.preparar([...])      # filma varios en paralelo (un Chrome por sprite), antes de repartir los tramos

Plantillas: rotulo (título de sección), llamada (punto + línea + etiqueta que señala un elemento), dato (un número
grande que cuenta con su etiqueta). Todas aceptan 'dur' (segundos en pantalla, con entrada y salida).

Sin dependencias de Python fuera de numpy y opencv (el WebSocket de CDP está acá, como en capturar_mapa9.py). Usa el
Chrome instalado (o el de la variable CHROME). Con conexión no hace falta nada: anime.js está en mg10/node_modules.
"""
import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
MG = os.path.join(AQUI, 'mg10')
PLANTILLAS = os.path.join(MG, 'plantillas')
CACHE = os.path.join(MG, 'cache')
ANIME = os.path.join(MG, 'node_modules', 'animejs', 'dist', 'bundles', 'anime.umd.min.js')
CHROME = os.environ.get('CHROME', r'C:\Program Files\Google\Chrome\Application\chrome.exe')
VERSION = 'mg10-1'           # cambia la clave de la caché si cambia la forma de filmar


# ─── CDP (WebSocket mínimo) ───────────────────────────────────────────────

class CDP:
    def __init__(self, ws_url):
        u = urllib.parse.urlparse(ws_url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=60)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(('GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                           'Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n'
                           % (u.path, u.hostname, u.port, key)).encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            buf += self.sock.recv(4096)
        head, rest = buf.split(b'\r\n\r\n', 1)
        if b' 101 ' not in head.split(b'\r\n')[0]:
            raise RuntimeError('CDP: el WebSocket no abrió: %r' % head[:200])
        self.buf = bytearray(rest)
        self.n = 0
        self.errores = []

    def _send(self, data):
        n = len(data)
        head = bytearray([0x81])
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack('>H', n)
        else:
            head.append(0x80 | 127)
            head += struct.pack('>Q', n)
        mask = os.urandom(4)
        head += mask
        m = (mask * (n // 4 + 1))[:n]
        body = (int.from_bytes(data, 'big') ^ int.from_bytes(m, 'big')).to_bytes(n, 'big') if n else b''
        self.sock.sendall(bytes(head) + body)

    def _frame(self):
        b = self.buf
        if len(b) < 2:
            return None
        n = b[1] & 0x7f
        pos = 2
        if n == 126:
            if len(b) < 4:
                return None
            n = struct.unpack('>H', bytes(b[2:4]))[0]
            pos = 4
        elif n == 127:
            if len(b) < 10:
                return None
            n = struct.unpack('>Q', bytes(b[2:10]))[0]
            pos = 10
        if b[1] & 0x80:
            pos += 4
        if len(b) < pos + n:
            return None
        fin, op = b[0] & 0x80, b[0] & 0x0f
        payload = bytes(b[pos:pos + n])
        del b[:pos + n]
        return fin, op, payload

    def _mensaje(self):
        partes = []
        while True:
            fr = self._frame()
            if fr is None:
                self.sock.settimeout(120)
                chunk = self.sock.recv(1 << 20)
                if not chunk:
                    raise ConnectionError('CDP: conexión cerrada')
                self.buf += chunk
                continue
            fin, op, payload = fr
            if op == 8:
                raise ConnectionError('CDP: cerrado por Chrome')
            if op in (9, 10):
                continue
            partes.append(payload)
            if fin:
                return json.loads(b''.join(partes))

    def call(self, method, **params):
        self.n += 1
        mid = self.n
        self._send(json.dumps({'id': mid, 'method': method, 'params': params}).encode())
        while True:
            msg = self._mensaje()
            if msg.get('id') == mid:
                if 'error' in msg:
                    raise RuntimeError('CDP %s: %s' % (method, msg['error']))
                return msg.get('result', {})
            m = msg.get('method')
            if m == 'Runtime.exceptionThrown':
                d = msg['params'].get('exceptionDetails', {})
                self.errores.append(d.get('text', '') + ' ' + str(d.get('exception', {}).get('description', ''))[:400])
            elif m == 'Runtime.consoleAPICalled' and msg['params'].get('type') in ('error', 'assert'):
                self.errores.append(' '.join(str(a.get('value', a.get('description', '')))
                                             for a in msg['params'].get('args', []))[:400])

    def js(self, expr, esperar=True):
        r = self.call('Runtime.evaluate', expression=expr, awaitPromise=esperar, returnByValue=True)
        if 'exceptionDetails' in r:
            d = r['exceptionDetails']
            raise RuntimeError('JS: %s %s' % (d.get('text'), d.get('exception', {}).get('description', '')[:600]))
        return r.get('result', {}).get('value')


class Chrome:
    """Un Chrome sin cabeza, con su propio perfil temporal y fondo transparente."""

    def __init__(self):
        if not os.path.exists(CHROME):
            raise SystemExit('No encuentro Chrome en %s (variable CHROME).' % CHROME)
        self.perfil = tempfile.mkdtemp(prefix='mg10-')
        args = [CHROME, '--headless=new', '--remote-debugging-port=0', '--user-data-dir=%s' % self.perfil,
                '--allow-file-access-from-files', '--hide-scrollbars', '--mute-audio', '--no-first-run',
                '--no-default-browser-check', '--disable-extensions', '--disable-sync', '--disable-default-apps',
                '--disable-background-networking', '--disable-component-update', '--disable-domain-reliability',
                '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
                '--disable-backgrounding-occluded-windows', '--force-color-profile=srgb', '--no-pings',
                '--run-all-compositor-stages-before-draw', '--disable-gpu', '--lang=es-AR',
                '--disable-features=Translate,OptimizationHints,MediaRouter,AutofillServerCommunication',
                '--window-size=1920,1080', 'about:blank']
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        archivo = os.path.join(self.perfil, 'DevToolsActivePort')
        for _ in range(400):
            if os.path.exists(archivo) and os.path.getsize(archivo) > 0:
                break
            time.sleep(0.05)
        else:
            self.cerrar()
            raise SystemExit('Chrome no abrió el puerto de depuración.')
        puerto = int(open(archivo).read().split()[0])
        lista = json.loads(urllib.request.urlopen('http://127.0.0.1:%d/json/list' % puerto, timeout=10).read())
        pagina = next(t for t in lista if t.get('type') == 'page')
        self.cdp = CDP(pagina['webSocketDebuggerUrl'])
        c = self.cdp
        c.call('Page.enable')
        c.call('Runtime.enable')
        c.call('Emulation.setDefaultBackgroundColorOverride', color={'r': 0, 'g': 0, 'b': 0, 'a': 0})
        c.call('Emulation.setEmulatedMedia', media='screen',
               features=[{'name': 'prefers-reduced-motion', 'value': 'no-preference'},
                         {'name': 'prefers-color-scheme', 'value': 'dark'}])

    def tamano(self, w, h, dsf=1):
        self.cdp.call('Emulation.setDeviceMetricsOverride', width=int(w), height=int(h), deviceScaleFactor=dsf,
                      mobile=False)

    def ir(self, url):
        self.cdp.call('Page.navigate', url=url)
        for _ in range(400):
            if self.cdp.js("document.readyState === 'complete' && !!window.__mg", esperar=False):
                return
            time.sleep(0.025)
        raise RuntimeError('No cargó %s' % url)

    def captura(self, w, h):
        r = self.cdp.call('Page.captureScreenshot', format='png', fromSurface=True, captureBeyondViewport=False,
                          optimizeForSpeed=True, clip={'x': 0, 'y': 0, 'width': w, 'height': h, 'scale': 1})
        return base64.b64decode(r['data'])

    def cerrar(self):
        try:
            self.cdp.sock.close()
        except Exception:
            pass
        if self.proc.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(self.proc.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            else:
                self.proc.kill()
        try:
            self.proc.wait(10)
        except Exception:
            pass
        shutil.rmtree(self.perfil, ignore_errors=True)


# ─── Sprites ─────────────────────────────────────────────────────────────

def _huella(plantilla, params, fps):
    h = hashlib.sha1()
    h.update(VERSION.encode())
    for nombre in (plantilla + '.html', 'base.js', 'base.css'):
        with open(os.path.join(PLANTILLAS, nombre), 'rb') as f:
            h.update(f.read())
    with open(ANIME, 'rb') as f:
        h.update(hashlib.sha1(f.read()).digest())
    h.update(json.dumps(params, sort_keys=True, ensure_ascii=False).encode())
    h.update(str(fps).encode())
    return h.hexdigest()[:16]


def _premul_rgba(bgra):
    rgba = cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA)
    a = rgba[..., 3:4].astype(np.uint16)
    rgba[..., :3] = ((rgba[..., :3].astype(np.uint16) * a + 127) // 255).astype(np.uint8)
    return rgba


class Sprite:
    """Una animación filmada: cuadros PNG con alfa en su carpeta de caché y meta.json (dur, ancho, alto, ancla)."""

    def __init__(self, plantilla, params, fps=60):
        self.plantilla, self.params, self.fps = plantilla, dict(params), fps
        self.huella = _huella(plantilla, self.params, fps)
        self.dir = os.path.join(CACHE, '%s-%s' % (plantilla, self.huella))
        self._meta = None
        self._ultimo = (None, None)

    @property
    def listo(self):
        return os.path.exists(os.path.join(self.dir, 'meta.json'))

    @property
    def meta(self):
        if self._meta is None:
            if not self.listo:
                filmar(self)
            with open(os.path.join(self.dir, 'meta.json'), encoding='utf-8') as f:
                self._meta = json.load(f)
        return self._meta

    dur = property(lambda s: s.meta['dur'])
    ancho = property(lambda s: s.meta['ancho'])
    alto = property(lambda s: s.meta['alto'])
    ancla = property(lambda s: tuple(s.meta['ancla']))
    n = property(lambda s: s.meta['cuadros'])
    marcas = property(lambda s: s.meta.get('marcas', {}))

    def cuadro(self, t):
        """El cuadro en t segundos desde el comienzo (RGBA premultiplicado) o None fuera de la animación."""
        k = int(round(t * self.fps))
        if k < 0 or k >= self.n:
            return None
        if self._ultimo[0] == k:
            return self._ultimo[1]
        im = cv2.imread(os.path.join(self.dir, 'f-%05d.png' % k), cv2.IMREAD_UNCHANGED)
        if im is None:
            raise FileNotFoundError(os.path.join(self.dir, 'f-%05d.png' % k))
        im = _premul_rgba(im)
        self._ultimo = (k, im)
        return im


def sprite(plantilla, params, fps=60):
    return Sprite(plantilla, params, fps)


def _url(plantilla):
    return 'file:///' + os.path.join(PLANTILLAS, plantilla + '.html').replace('\\', '/')


def filmar(sp, chrome=None, avisar=True):
    """Filma el sprite (si no está en caché) y deja meta.json al final (si se corta a la mitad, se vuelve a filmar)."""
    if sp.listo:
        return sp
    propio = chrome is None
    ch = chrome or Chrome()
    tmp = sp.dir + '.tmp'
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    t0 = time.time()
    try:
        ch.tamano(1920, 1080)
        ch.ir(_url(sp.plantilla))
        info = ch.cdp.js('window.__mg.montar(%s)' % json.dumps(sp.params, ensure_ascii=False))
        w, h = int(info['ancho']), int(info['alto'])
        ch.tamano(w, h)
        ch.cdp.js('window.__mg.relayout && window.__mg.relayout()')
        n = int(round(info['dur'] / 1000.0 * sp.fps)) + 1
        for k in range(n):
            ch.cdp.js('window.__mg.ir(%r)' % (k * 1000.0 / sp.fps), esperar=True)
            png = ch.captura(w, h)
            with open(os.path.join(tmp, 'f-%05d.png' % k), 'wb') as f:
                f.write(png)
        if ch.cdp.errores:
            raise RuntimeError('Errores en la plantilla %s: %s' % (sp.plantilla, ch.cdp.errores[:3]))
        meta = dict(plantilla=sp.plantilla, params=sp.params, fps=sp.fps, dur=info['dur'] / 1000.0, ancho=w,
                    alto=h, ancla=info.get('ancla', [0, 0]), cuadros=n, marcas=info.get('marcas', {}),
                    filmado=time.strftime('%Y-%m-%d %H:%M:%S'))
        with open(os.path.join(tmp, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        shutil.rmtree(sp.dir, ignore_errors=True)
        os.replace(tmp, sp.dir)
    finally:
        if propio:
            ch.cerrar()
    if avisar:
        print('  mg10: %s %s · %d cuadros %dx%d en %.1f s' % (sp.plantilla, sp.huella, n, w, h, time.time() - t0),
              flush=True)
    return sp


def preparar(sprites, hilos=3):
    """Filma en paralelo los que falten (un Chrome por hilo). Llamarlo antes de repartir los tramos en procesos."""
    faltan = [s for s in sprites if not s.listo]
    if not faltan:
        return
    os.makedirs(CACHE, exist_ok=True)
    lock = threading.Lock()
    pendientes = list(faltan)

    def trabajador():
        ch = Chrome()
        try:
            while True:
                with lock:
                    if not pendientes:
                        return
                    s = pendientes.pop(0)
                filmar(s, ch)
        finally:
            ch.cerrar()

    with ThreadPoolExecutor(max_workers=max(1, min(hilos, len(faltan)))) as ex:
        for f in [ex.submit(trabajador) for _ in range(max(1, min(hilos, len(faltan))))]:
            f.result()


def limpiar(usados):
    """Borra de la caché los sprites que ya no se usan (los que no están en `usados`)."""
    quedan = {os.path.basename(s.dir) for s in usados}
    if not os.path.isdir(CACHE):
        return
    for x in os.listdir(CACHE):
        if x not in quedan:
            shutil.rmtree(os.path.join(CACHE, x), ignore_errors=True)


if __name__ == '__main__':
    # python mg10.py rotulo '{"titulo": "Inicio"}'  → filma y muestra dónde quedó
    s = sprite(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else {})
    filmar(s)
    print(s.dir, s.meta)
