"""Ejemplo del kit: un video de ~20 s sobre un panel de ventas inventado (sitio/), con todas las técnicas del motor.

  0,0  la ventana del panel entra inclinada en 3D y se asienta a pantalla llena; rótulo animado (HTML + anime.js);
  1,6  J1: la cámara llega a las tarjetas *con la palabra* «vistazo»; con «hoy», «mes» y «año» cada tarjeta se despega
       (sombra, borde, el resto se oscurece y se desenfoca) y una llamada señala la meta anual;
       latigazo con desenfoque de movimiento real a la página de Pedidos;
       J2: la fila del pedido más grande se despega con su llamada.
  Voz con marcas por palabra (edge-tts), subtítulos, música y efectos sintetizados (sonido6) y acabado (post6).

Antes, una vez: python ../motor/captura.py pantallas.json      (deja pantallas/inicio y pantallas/pedidos)

    python armar.py                      -> ejemplo.mp4 (30 fps; FPS=60 para la versión fluida)
    VISTAS=2,6.5,12 python armar.py      -> solo esos cuadros en vistas/ (para revisar sin renderizar todo)
"""
import multiprocessing as mp
import os
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, '..', 'motor'))
os.environ.setdefault('CACHE_VOCES', os.path.join(AQUI, 'cache', 'voces'))

from PIL import Image  # noqa: E402

import captura  # noqa: E402
import cine10 as C  # noqa: E402
import mg10 as G  # noqa: E402
import mov10 as M  # noqa: E402
import post6  # noqa: E402
import sonido6 as S6  # noqa: E402
import subtitulos  # noqa: E402
import voz  # noqa: E402

FPS = int(os.environ.get('FPS', '30'))
W, H = C.W, C.H
post6.FPS = FPS
PANT = os.path.join(AQUI, 'pantallas')
SALIDA = os.path.join(AQUI, 'ejemplo.mp4')

J1 = 'Este es el panel de ventas de la tienda: de un vistazo, lo vendido hoy, en el mes y en todo el año.'
J2 = 'En Pedidos queda cada venta del día, y el pedido más grande se destaca solo.'


def caja(pantalla, texto, tags=None):
    return captura.caja(PANT, pantalla, texto, tags)


def union(*cajas):
    return (min(c[0] for c in cajas), min(c[1] for c in cajas), max(c[2] for c in cajas), max(c[3] for c in cajas))


def construir():
    esc = C.Escena(fps=FPS)
    d = type('D', (), {})()
    d.esc, d.voces, d.sfxs, d.sprites = esc, [], [], []
    d.subs = subtitulos.Subtitulos()
    d.musica_secciones, d.stings = [(0.0, 'liviano')], []

    def sfx(t, nombre, gan=1.0, pan=0.0, dur=None):
        d.sfxs.append((t, nombre, gan, pan, dur))

    # ── El mundo: las dos páginas, cada una en su ventana, una al lado de la otra ──
    ini = C.ventana(esc, C.Imagen(Image.open(os.path.join(PANT, 'inicio.png')), ss=2), 0, 0, 'Ventas · Tienda Demo')
    XS = 1920 + 260
    ped = C.ventana(esc, C.Imagen(Image.open(os.path.join(PANT, 'pedidos.png')), ss=2), XS, 0, 'Pedidos · Tienda Demo')

    # ── La voz: primero las frases, después todo lo demás se acomoda a sus palabras ──
    j1 = voz.Linea(J1, 1.6)
    t_lat = j1.fin + 0.35
    j2 = voz.Linea(J2, t_lat + 0.95)
    for ln in (j1, j2):
        d.voces.append((ln.v0, ln.pcm))
        d.subs.agregar(ln)
    d.total = j2.fin + 1.8

    # ── 0,0 · Entrada en 3D y rótulo ──
    cam = esc.cam
    lleno = C.encuadre_completo(ini, arriba=C.BARRA_VENTANA)
    cam.pos.ir(0.0, (lleno[0] + 120, lleno[1] + 40, 0.66), 0)
    cam.incl.ir(0.0, (17.0, -24.0), 0)
    cam.giro.ir(0.0, -3.0, 0)
    cam.pos.ir(0.0, lleno, 1.75, 'cine')
    cam.incl.ir(0.0, (0.0, 0.0), 1.75, 'cine')
    cam.giro.ir(0.0, 0.0, 1.75, 'cine')
    sfx(0.05, 'whoosh', 0.35)
    for p in (ini, ped):
        p.sombra.opacidad.ir(1.2, 0.0, 0.6, 'suave')
    rot = G.sprite('rotulo', dict(numero='01', kicker='EJEMPLO DEL KIT', titulo='Panel de ventas',
                                  bajada='Todo el negocio, de un vistazo', dur=2.4), FPS)
    d.sprites.append(rot)
    esc.en_pantalla(rot, 0.35, 64, 58)
    sfx(0.35, 'titulo', 0.45)

    # ── J1 · a las tarjetas, llegando con «vistazo»; cada una se despega con su palabra ──
    k_hoy = caja('inicio', 'Ventas de hoy', ['article'])
    k_mes = caja('inicio', 'Ventas del mes', ['article'])
    k_anio = caja('inicio', 'Total del año', ['article'])
    enc = esc.encuadre(ini, union(k_hoy, k_mes, k_anio), margen=0.08)
    cam.resorte(M.aterrizar_resorte(j1.en('vistazo'), 0.95, 0.96), enc, 0.95, 0.96)
    fin_tarjetas = j1.fin + 0.2
    for k, palabra in ((k_hoy, 'hoy'), (k_mes, 'mes'), (k_anio, 'año')):
        tp = j1.en(palabra)
        el = esc.elevar(tp - 0.12, fin_tarjetas, ini, k, escala=1.07, atenuar=0.4, desenfoque=6)
        sfx(tp - 0.12, 'pop', 0.45)
    ll = G.sprite('llamada', dict(texto='<b>92 %</b> de la meta anual', detalle='Faltan dos meses para cerrar el año',
                                  dir='izq-abajo', codo=70, largo=60, dur=2.4), FPS)
    d.sprites.append(ll)
    esc.anclar(ll, j1.en('año') + 0.3, ini, ((k_anio[0] + k_anio[2]) / 2, k_anio[3] - 10), sobre=el)
    sfx(j1.en('año') + 0.3, 'ping', 0.25)

    # ── Latigazo a Pedidos ──
    cam.pos.ir(t_lat, C.encuadre_completo(ped, arriba=C.BARRA_VENTANA), 0.62, 'latigo')
    sfx(t_lat + 0.31 - S6.DESFASES['whoosh_corto'], 'whoosh_corto', 0.9, 0.3)
    sfx(t_lat + 0.6, 'impacto', 0.18)

    # ── J2 · la tabla y el pedido más grande ──
    tabla = caja('pedidos', 'Hora Pedido', ['table', 'section'])
    cam.resorte(M.aterrizar_resorte(j2.en('venta'), 1.0, 0.98), esc.encuadre(ped, tabla, margen=0.04, zmax=1.4), 1.0, 0.98)
    fila = caja('pedidos', 'Colegio San Martín', ['tr'])
    tg = j2.en('grande')
    el2 = esc.elevar(tg - 0.2, d.total - 0.6, ped, fila, escala=1.03, subir=2, atenuar=0.42, desenfoque=5)
    sfx(tg - 0.2, 'pop', 0.4)
    ll2 = G.sprite('llamada', dict(texto='<b>$ 126.800</b>, el más grande del día', detalle='Colegio San Martín · Norte',
                                   dir='izq-abajo', codo=90, largo=70, dur=2.6), FPS)
    d.sprites.append(ll2)
    esc.anclar(ll2, tg + 0.1, ped, (fila[0] + (fila[2] - fila[0]) * 0.62, fila[3] - 6), sobre=el2)
    sfx(tg + 0.1, 'ping', 0.22)
    return d


def cuadro(d, t):
    img = d.esc.cuadro(t)
    img = d.subs.dibujar(img, t)
    img = post6.acabado(img, t, grano=0.6)
    nivel = min(1.0, t / 0.35, (d.total - t) / 0.6)
    if nivel < 1:
        img = Image.blend(Image.new('RGB', (W, H), (0, 0, 0)), img, max(nivel, 0.0))
    return img


def _tramo(args):
    a, b, ruta = args
    d = construir()
    ff = subprocess.Popen([voz.FF, '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H),
                           '-r', str(FPS), '-i', '-', '-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p',
                           '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-threads', '2',
                           '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
                           '-color_range', 'tv', ruta], stdin=subprocess.PIPE)
    for k in range(a, b):
        ff.stdin.write(cuadro(d, k / FPS).tobytes())
    ff.stdin.close()
    ff.wait()
    return ruta


def main():
    d = construir()
    G.preparar(d.sprites)                      # filma los rótulos y llamadas que falten (quedan en caché)
    vistas = os.environ.get('VISTAS')
    if vistas:
        carpeta = os.path.join(AQUI, 'vistas')
        os.makedirs(carpeta, exist_ok=True)
        for x in vistas.split(','):
            cuadro(d, float(x)).save(os.path.join(carpeta, 'v-%06.2f.png' % float(x)))
        print('vistas en %s' % carpeta)
        return
    mezcla = os.path.join(AQUI, 'cache', 'mezcla.wav')
    os.makedirs(os.path.dirname(mezcla), exist_ok=True)
    S6.mezcla6(d, mezcla)
    n = int(round(d.total * FPS))
    partes = int(os.environ.get('PARTES', str(max(1, min(6, (os.cpu_count() or 2) - 1)))))
    carpeta = os.path.join(AQUI, 'cache', 'tramos')
    os.makedirs(carpeta, exist_ok=True)
    trabajos = [(i * n // partes, (i + 1) * n // partes, os.path.join(carpeta, 'tramo-%02d.mp4' % i))
                for i in range(partes)]
    t0 = time.time()
    with mp.Pool(partes) as pool:
        rutas = pool.map(_tramo, trabajos)
    lista = os.path.join(carpeta, 'lista.txt')
    with open(lista, 'w', encoding='utf-8') as f:
        for r in rutas:
            f.write("file '%s'\n" % r.replace('\\', '/'))
    subprocess.run([voz.FF, '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lista, '-i', mezcla,
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', SALIDA],
                   check=True)
    print('listo: %s (%.1f s, %d fps, %.0f s de render)' % (SALIDA, d.total, FPS, time.time() - t0))


if __name__ == '__main__':
    main()
