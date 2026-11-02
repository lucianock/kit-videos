"""Capturas nítidas de páginas web para el video: 1920 px CSS de ancho a ×2 (3840 px), la página entera.

Con ×2 los acercamientos de la cámara quedan nítidos (la letra no se pixela). Además de la imagen deja un JSON con la
caja de cada elemento visible (en px CSS) y su texto: así el guion enfoca «la fila que dice X» sin medir a mano.

    python motor/captura.py pantallas.json             # [{"nombre": "inicio", "url": "http://localhost:3000/"}, ...]
    python motor/captura.py --url https://ejemplo.com --nombre ejemplo

Cada entrada puede llevar "clics": ["Texto del botón", ...] y "espera": segundos. Para páginas con ingreso, abrí la
sesión una vez con --perfil y --ventana (Chrome con ventana): las siguientes corridas usan ese perfil.
Nunca captures datos reales de clientes: usá un entorno de prueba con datos inventados.
"""
import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

CHROME = os.environ.get('CHROME', r'C:\Program Files\Google\Chrome\Application\chrome.exe')
ANCHO, ALTO, DSF = 1920, 1080, 2

CAJAS_JS = r"""
(() => {
  const sel = 'a,button,h1,h2,h3,h4,th,tr,td,label,input,[role=tab],section,article,header,aside,nav,p,li,img,svg,canvas';
  const out = [];
  for (const e of document.querySelectorAll(sel)) {
    const r = e.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    const s = getComputedStyle(e);
    if (s.visibility === 'hidden' || s.display === 'none' || Number(s.opacity) === 0) continue;
    const t = (e.innerText || e.value || e.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 160);
    out.push({tag: e.tagName.toLowerCase(), texto: t,
              caja: [r.left, r.top + scrollY, r.right, r.bottom + scrollY].map(v => Math.round(v * 10) / 10)});
  }
  return out;
})()
"""

CLIC_JS = r"""
((txt) => {
  const els = [...document.querySelectorAll('button,a,[role=tab],summary,label')];
  const e = els.find(x => (x.innerText || '').replace(/\s+/g, ' ').trim() === txt)
         || els.find(x => (x.innerText || '').includes(txt));
  if (!e) return false;
  e.click();
  return true;
})(%s)
"""


class CDP:
    """Cliente mínimo del protocolo de depuración de Chrome (WebSocket a mano, sin dependencias)."""

    def __init__(self, ws_url):
        u = urllib.parse.urlparse(ws_url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=120)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(('GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                           'Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n'
                           % (u.path, u.hostname, u.port, key)).encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            buf += self.sock.recv(4096)
        self.buf = bytearray(buf.split(b'\r\n\r\n', 1)[1])
        self.n = 0
        self.eventos = {}

    def _send(self, data):
        n = len(data)
        head = bytearray([0x81])
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head += bytes([0x80 | 126]) + n.to_bytes(2, 'big')
        else:
            head += bytes([0x80 | 127]) + n.to_bytes(8, 'big')
        mask = os.urandom(4)
        self.sock.sendall(bytes(head) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _leer(self, n):
        while len(self.buf) < n:
            parte = self.sock.recv(1 << 20)
            if not parte:
                raise ConnectionError('Chrome cerró la conexión')
            self.buf += parte
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def _mensaje(self):
        datos = b''
        while True:
            b0, b1 = self._leer(2)
            n = b1 & 0x7F
            if n == 126:
                n = int.from_bytes(self._leer(2), 'big')
            elif n == 127:
                n = int.from_bytes(self._leer(8), 'big')
            datos += self._leer(n)
            if b0 & 0x80:
                return json.loads(datos.decode('utf-8'))

    def call(self, metodo, **params):
        self.n += 1
        mid = self.n
        self._send(json.dumps({'id': mid, 'method': metodo, 'params': params}).encode())
        while True:
            m = self._mensaje()
            if m.get('id') == mid:
                if 'error' in m:
                    raise RuntimeError('CDP %s: %s' % (metodo, m['error']))
                return m.get('result', {})
            if 'method' in m:
                self.eventos[m['method']] = self.eventos.get(m['method'], 0) + 1

    def js(self, expr, esperar=False):
        r = self.call('Runtime.evaluate', expression=expr, awaitPromise=esperar, returnByValue=True)
        return r.get('result', {}).get('value')


class Navegador:
    def __init__(self, perfil, ventana=False):
        os.makedirs(perfil, exist_ok=True)
        args = [CHROME, '--remote-debugging-port=0', '--user-data-dir=%s' % perfil, '--window-size=%d,%d' % (ANCHO, ALTO),
                '--hide-scrollbars', '--mute-audio', '--no-first-run', '--no-default-browser-check',
                '--force-color-profile=srgb', '--lang=es-AR', 'about:blank']
        if not ventana:
            args.insert(1, '--headless=new')
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        archivo = os.path.join(perfil, 'DevToolsActivePort')
        for _ in range(400):
            if os.path.exists(archivo) and os.path.getsize(archivo) > 0:
                break
            time.sleep(0.05)
        puerto = int(open(archivo).read().split()[0])
        for _ in range(100):
            try:
                lista = json.loads(urllib.request.urlopen('http://127.0.0.1:%d/json/list' % puerto, timeout=5).read())
                break
            except OSError:
                time.sleep(0.1)
        pagina = next(t for t in lista if t.get('type') == 'page')
        self.cdp = CDP(pagina['webSocketDebuggerUrl'])
        self.cdp.call('Page.enable')
        self.cdp.call('Emulation.setEmulatedMedia', media='screen',
                      features=[{'name': 'prefers-reduced-motion', 'value': 'reduce'}])

    def metricas(self, alto=ALTO):
        self.cdp.call('Emulation.setDeviceMetricsOverride', width=ANCHO, height=alto, deviceScaleFactor=DSF,
                      mobile=False, screenWidth=ANCHO, screenHeight=alto)

    def ir(self, url, espera=2.0):
        antes = self.cdp.eventos.get('Page.loadEventFired', 0)
        self.cdp.call('Page.navigate', url=url)
        fin = time.time() + 60
        while self.cdp.eventos.get('Page.loadEventFired', 0) <= antes and time.time() < fin:
            self.cdp.js('1')
            time.sleep(0.1)
        time.sleep(espera)

    def cerrar(self):
        try:
            self.cdp.sock.close()
        finally:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(self.proc.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            else:
                self.proc.kill()


def capturar(nav, salida, nombre, url, clics=(), espera=2.0):
    c = nav.cdp
    nav.metricas()
    nav.ir(url, espera)
    for txt in clics:
        if not c.js(CLIC_JS % json.dumps(txt)):
            print('  [aviso] %s: no encontré «%s»' % (nombre, txt))
        time.sleep(1.2)
    alto = int(c.js('Math.max(document.scrollingElement.scrollHeight, %d)' % ALTO))
    nav.metricas(alto)
    time.sleep(0.8)
    alto = int(c.js('Math.max(document.scrollingElement.scrollHeight, %d)' % ALTO))
    shot = c.call('Page.captureScreenshot', format='png',
                  clip={'x': 0, 'y': 0, 'width': ANCHO, 'height': alto, 'scale': 1})
    with open(os.path.join(salida, nombre + '.png'), 'wb') as f:
        f.write(base64.b64decode(shot['data']))
    info = {'imagen': nombre + '.png', 'url': url, 'ancho_css': ANCHO, 'alto_css': alto, 'escala': DSF,
            'cajas': c.js(CAJAS_JS)}
    with open(os.path.join(salida, nombre + '.json'), 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False)
    print('  %-24s %d x %d px  (%d cajas)' % (nombre, ANCHO * DSF, alto * DSF, len(info['cajas'])))


def caja(salida, nombre, texto, tags=None, exacto=False):
    """Caja (x0, y0, x1, y1) en px CSS del elemento más chico que contiene ese texto en la captura."""
    with open(os.path.join(salida, nombre + '.json'), encoding='utf-8') as f:
        cajas = json.load(f)['cajas']
    t = texto.lower()
    r = [c for c in cajas if (c['texto'].lower() == t if exacto else t in c['texto'].lower())
         and (not tags or c['tag'] in tags)]
    if not r:
        raise KeyError('%s: no hay ningún elemento con «%s»' % (nombre, texto))
    r.sort(key=lambda c: (c['caja'][2] - c['caja'][0]) * (c['caja'][3] - c['caja'][1]))
    return tuple(r[0]['caja'])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('lista', nargs='?', help='JSON con [{"nombre", "url", "clics", "espera"}]')
    ap.add_argument('--url')
    ap.add_argument('--nombre', default='captura')
    ap.add_argument('--salida', default='pantallas')
    ap.add_argument('--perfil', default=os.path.join('cache', 'chrome-perfil'))
    ap.add_argument('--ventana', action='store_true', help='Chrome con ventana (para iniciar sesión a mano)')
    a = ap.parse_args(argv)
    if a.lista:
        with open(a.lista, encoding='utf-8') as f:
            items = json.load(f)
    elif a.url:
        items = [{'nombre': a.nombre, 'url': a.url}]
    else:
        ap.error('pasá un JSON con la lista o --url')
    for it in items:                       # rutas locales (un sitio de ejemplo) -> file:///
        if '://' not in it['url']:
            it['url'] = 'file:///' + os.path.abspath(it['url']).replace(os.sep, '/')
    os.makedirs(a.salida, exist_ok=True)
    nav = Navegador(os.path.abspath(a.perfil), ventana=a.ventana)
    try:
        if a.ventana:
            input('Iniciá sesión en la ventana de Chrome y apretá Enter acá para seguir... ')
        for it in items:
            capturar(nav, a.salida, it['nombre'], it['url'], it.get('clics', ()), it.get('espera', 2.0))
    finally:
        nav.cerrar()


if __name__ == '__main__':
    sys.exit(main())
