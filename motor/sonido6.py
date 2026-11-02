"""sonido6 · efectos de sonido, música y mezcla del video.

Todo se sintetiza con numpy a 48 kHz (sin muestras externas ni scipy): síntesis modal para los golpes chicos (clics,
teclas, sello, interruptor), ruido con espectro variable en el tiempo (STFT) para los barridos, osciladores sin
aliasing (polyBLEP) y FM para lo tonal, y reverberación por convolución con respuestas sintéticas multibanda.
No hay aplausos.

API
  SR = 48000
  ORDEN                      nombres de los efectos, en el orden del pedido
  EFECTOS6[nombre](dur=None) -> np.float32 mono (n,) o estéreo (n, 2), picos <= 0,9, sin DC, con fundidos.
                             'dur' cambia la duración en conteo (1,5), riser (1,6), reverse (tiempo hasta el
                             golpe, 1,6), whoosh/whoosh_corto/swish/cambio, desliza (0,8) y glitch; el resto lo ignora
  efecto(nombre, dur=None)   lo mismo, con caché para los efectos fijos (ALEATORIOS cambian en cada llamada:
                             tecla, tic, golpe, glitch)
  DESFASES[nombre]           segundos desde el comienzo del efecto hasta su golpe o punto fuerte (agendar en
                             t_golpe - DESFASES[nombre]); los que no figuran golpean en 0
  musica6(secciones, total, stings, n=None, llegada=None) -> (L, R) float32
  mezcla6(d, ruta)           voz + efectos + música -> WAV 48 kHz estéreo 16 bits; devuelve ruta
  semilla(s)                 reinicia el generador aleatorio de los efectos (mezcla6 lo hace solo)
  nivel_a50(x)               sonoridad (dB, ponderación A, máximo de RMS en ventanas de 50 ms)

Notas para el armador
  - d.stings los toca musica6 (la música se retira, platillo invertido y golpe 'sting'): no agendar además
    d.sfx(t, 'sting') en el mismo tiempo.
  - Si hay sección 'final' y un d.sfx(..., 'acorde') después de su comienzo, el Do final de la música cae justo en el
    tiempo del acorde (llegada); si no, cerca de total - 6,5 s.
  - La música entra con un fundido de 1 s; efectos y voz con 50 ms. En los últimos FADE_FIN = 3 s música y efectos
    caen en forma exponencial hasta total (la voz solo los últimos 0,2 s).
  - Niveles: voz -17 dBFS RMS al hablar; los efectos conservan la relación con la voz de las mezclas v3-v5
    (GANANCIA_SFX), así que las ganancias de armar5 siguen sirviendo.
"""
import math
import os
import wave
from functools import lru_cache

import numpy as np

SR = 48000
BPM = 100
NEGRA = 60.0 / BPM            # 0,6 s
COMPAS = 4 * NEGRA            # 2,4 s
SEMI = NEGRA / 4              # semicorchea, 0,15 s
CRUCE = 0.8                   # fundido entre secciones de música
COLA_EXTRA = 0.5              # segundos de audio después de d.total (el video corta con -shortest)
FADE_FIN = 3.0                # caída final de música y efectos (exponencial, hasta d.total)
VOZ_RMS_DB = -17.0            # nivel de la voz al hablar
GANANCIA_SFX = 1.13           # efectos con la misma relación con la voz que en las mezclas v3-v5
PICO_MAX = 0.9
MUSICA = os.environ.get('MUSICA', '1') == '1'

_rng = np.random.default_rng(606)


def semilla(s=606):
    global _rng
    _rng = np.random.default_rng(s)


def _rl(s):
    return np.random.default_rng(s)


# ─── Herramientas de señal ────────────────────────────────────────────────

_LARGOS = np.array(sorted(2 ** a * 3 ** b * 5 ** c for a in range(28) for b in range(6) for c in range(4)
                          if 2 ** a * 3 ** b * 5 ** c <= 2 ** 28))


def _largo_fft(n):
    return int(_LARGOS[np.searchsorted(_LARGOS, n)])


def _t(seg):
    return np.arange(int(round(seg * SR))) / SR


def _fft_filtro(x, resp, pad=4096):
    """Filtro de fase cero: multiplica el espectro por resp(frecuencias)."""
    x = np.asarray(x, np.float64)
    n = len(x)
    m = _largo_fft(n + pad)
    fr = np.fft.rfftfreq(m, 1 / SR)
    g = resp(fr)
    X = np.fft.rfft(x, m, axis=0)
    if X.ndim == 2:
        g = g[:, None]
    return np.fft.irfft(X * g, m, axis=0)[:n]


def _r(fr, fc):
    return np.maximum(fr, 1e-6) / fc


def _lp(fc, q=0.7071, orden=1):
    return lambda fr: (1 / np.sqrt((1 - _r(fr, fc) ** 2) ** 2 + (_r(fr, fc) / q) ** 2)) ** orden


def _hp(fc, q=0.7071, orden=1):
    return lambda fr: (_r(fr, fc) ** 2 / np.sqrt((1 - _r(fr, fc) ** 2) ** 2 + (_r(fr, fc) / q) ** 2)) ** orden


def _bp(fc, q=1.0):
    return lambda fr: (_r(fr, fc) / q) / np.sqrt((1 - _r(fr, fc) ** 2) ** 2 + (_r(fr, fc) / q) ** 2)


def _pico(f0, gdb, q=1.0):
    A = 10 ** (gdb / 40)

    def f(fr):
        s = 1j * _r(fr, f0)
        return np.abs((s * s + s * (A / q) + 1) / (s * s + s / (A * q) + 1))
    return f


def _estante_alto(f0, gdb, q=0.7071):
    A = 10 ** (gdb / 40)

    def f(fr):
        s = 1j * _r(fr, f0)
        return np.abs(A * (A * s * s + math.sqrt(A) / q * s + 1) / (s * s + math.sqrt(A) / q * s + A))
    return f


def _estante_bajo(f0, gdb, q=0.7071):
    A = 10 ** (gdb / 40)

    def f(fr):
        s = 1j * _r(fr, f0)
        return np.abs(A * (s * s + math.sqrt(A) / q * s + A) / (A * s * s + math.sqrt(A) / q * s + 1))
    return f


def _y(*resps):
    def f(fr):
        g = np.ones(len(fr))
        for r_ in resps:
            g = g * r_(fr)
        return g
    return f


def _banda(lo=None, hi=None, orden=2):
    rs = []
    if lo:
        rs.append(_hp(lo, 0.7071, orden))
    if hi:
        rs.append(_lp(hi, 0.7071, orden))
    return _y(*rs)


def _ruido_banda(n, lo=None, hi=None, rng=None, orden=2):
    x = (rng if rng is not None else _rng).standard_normal(n + 256)
    y = _fft_filtro(x, _banda(lo, hi, orden), pad=512)[128:128 + n]
    return y / (np.sqrt(np.mean(y ** 2)) + 1e-12)


def _env(tt, ataque, caida):
    """Envolvente percusiva sin saltos: sube con constante 'ataque' y cae con constante 'caida'. 0 antes de tt=0."""
    tt = np.maximum(tt, 0.0)
    return (1 - np.exp(-tt / ataque)) * np.exp(-tt / caida)


def _modos(tt, modos):
    """Síntesis modal: suma de senoidales amortiguadas [(frecuencia, tau, amplitud)], 0 antes de tt=0."""
    tt = np.maximum(tt, 0.0)
    s = np.zeros(len(tt))
    for f, tau, a in modos:
        if f < SR * 0.45:
            s += a * np.sin(2 * np.pi * f * tt) * np.exp(-tt / tau)
    return s


def _fase(f):
    return 2 * np.pi * np.cumsum(f) / SR


def _sierra(f, n=None, fase=0.0, sr=SR):
    """Diente de sierra con corrección polyBLEP (sin aliasing audible). f escalar o arreglo por muestra."""
    f = np.asarray(f, np.float64)
    if f.ndim == 0:
        f = np.full(n, float(f))
    dt = f / sr
    p = (fase + np.cumsum(dt) - dt[0]) % 1.0
    y = 2 * p - 1
    m = p < dt
    x = p[m] / dt[m]
    y[m] -= 2 * x - x * x - 1
    m = p > 1 - dt
    x = (p[m] - 1) / dt[m]
    y[m] -= x * x + 2 * x + 1
    return y


def _cuadrada(f, n=None, fase=0.0):
    return 0.5 * (_sierra(f, n, fase) - _sierra(f, n, fase + 0.5))


def _suave(p):
    p = np.clip(p, 0, 1)
    return p * p * (3 - 2 * p)


def _compuerta(t, t0, t1, sube=0.004, baja=0.02):
    """1 entre t0 y t1, con rampas de coseno (sin clics)."""
    a = _suave((t - t0) / sube)
    b = 1 - _suave((t - t1) / baja)
    return a * b


def _ajustar(x, n):
    """Recorta o completa con ceros hasta n muestras."""
    if len(x) >= n:
        return x[:n]
    return np.concatenate([x, np.zeros((n - len(x),) + x.shape[1:], x.dtype)])


def _env_pad(n, dur, ataque, rel):
    """Envolvente de colchón: sube en 'ataque' (curva suave), sostiene hasta 'dur' y cae exponencialmente."""
    env = np.ones(n)
    a = min(n, max(1, int(ataque * SR)))
    env[:a] = _suave(np.arange(a) / (ataque * SR))
    d = min(n, int(dur * SR))
    if d < n:
        env[d:] *= np.exp(-np.arange(n - d) / SR / (rel / 4.5))
    return env


def _cola(x, seg=None, frac=0.2):
    """Fundido de coseno al final (los últimos 'seg' segundos o la fracción 'frac'): nada termina de golpe."""
    x = np.array(x, np.float64, copy=True)
    m = int(seg * SR) if seg else int(len(x) * frac)
    m = max(2, min(len(x), m))
    r = 0.5 + 0.5 * np.cos(np.pi * (np.arange(m) + 1) / m)
    x[-m:] *= r[:, None] if x.ndim == 2 else r
    return x


def _rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)) + 1e-12)


# STFT: filtros que cambian en el tiempo (barridos, subidas, filtros que se abren)

_VENT = {}


def _stft_aplicar(x, mascara, N=1024, hop=256):
    """Filtra x (1-D) con mascara(tc, fr) -> ganancias (marcos x bandas); tc en segundos desde el comienzo de x."""
    n = len(x)
    w = _VENT.get(N)
    if w is None:
        w = _VENT[N] = np.hanning(N + 1)[:-1]
    xp = np.concatenate([np.zeros(N), np.asarray(x, np.float64), np.zeros(2 * N)])
    F = (len(xp) - N) // hop + 1
    marcos = np.lib.stride_tricks.sliding_window_view(xp, N)[::hop][:F] * w
    S = np.fft.rfft(marcos, axis=1)
    tc = (np.arange(F) * hop + N / 2 - N) / SR
    fr = np.fft.rfftfreq(N, 1 / SR)
    S *= mascara(tc[:, None], np.maximum(fr[None, :], 1.0))
    y = np.fft.irfft(S, N, axis=1) * w
    out = np.zeros(F * hop + N)
    R = N // hop
    for k in range(R):
        bloque = y[k::R]
        out[k * hop:k * hop + len(bloque) * N] += bloque.reshape(-1)
    out /= (w ** 2).sum() / hop
    return out[N:N + n]


def _ruido_formado(n, mascara, rng, N=1024):
    return _stft_aplicar(rng.standard_normal(n), mascara, N)


def _campana_log(fr, fc, octavas):
    return np.exp(-0.5 * (np.log2(fr / fc) / octavas) ** 2)


# Reverberación por convolución con respuestas sintéticas (multibanda, reflexiones tempranas, estéreo decorrelado)

@lru_cache(maxsize=24)
def _ir(rt60=2.2, predelay=0.02, brillo=1.0, sem=7, corte_bajo=150.0, tempranas=True):
    largo = min(6.0, rt60 * 1.25 + predelay)
    n = int(largo * SR)
    t = np.arange(n) / SR
    rng = _rl(sem)
    m = _largo_fft(n)
    fr = np.maximum(np.fft.rfftfreq(m, 1 / SR), 1.0)
    cruce = lambda fc: 1 / (1 + (fr / fc) ** 4)
    bandas = [(cruce(300), 1.1), (cruce(2000) - cruce(300), 1.0), (cruce(6000) - cruce(2000), 0.72 * brillo),
              (1 - cruce(6000), 0.42 * brillo)]
    canales = []
    for c in range(2):
        X = np.fft.rfft(rng.standard_normal(n), m)
        h = np.zeros(n)
        for g, mult in bandas:
            h += np.fft.irfft(X * g, m)[:n] * np.exp(-6.91 * t / (rt60 * mult))
        h *= 1 - np.exp(-t / 0.012)
        if tempranas:
            for _ in range(7):
                i = int(rng.uniform(0.003, 0.05) * SR)
                h[i] += rng.choice([-1, 1]) * rng.uniform(1.5, 4.0) * (1 - i / (0.06 * SR))
        h = _fft_filtro(h, _hp(corte_bajo, 0.7071, 1), pad=8192)
        d = int(predelay * SR)
        h = np.concatenate([np.zeros(d), h])[:n]
        canales.append(h / np.sqrt((h ** 2).sum()))
    return canales[0], canales[1]


def _conv(x, h, n_sal=None):
    """Convolución por FFT (bloques solapados si la señal es larga)."""
    x = np.asarray(x, np.float64)
    n_sal = n_sal or len(x) + len(h) - 1
    total = len(x) + len(h) - 1
    if total <= 1 << 21:
        m = _largo_fft(total)
        y = np.fft.irfft(np.fft.rfft(x, m) * np.fft.rfft(h, m), m)[:total]
    else:
        N = 1 << 20 if len(h) < (1 << 19) else _largo_fft(4 * len(h))
        paso = N - len(h) + 1
        H = np.fft.rfft(h, N)
        y = np.zeros(total)
        for s0 in range(0, len(x), paso):
            bloque = x[s0:s0 + paso]
            yy = np.fft.irfft(np.fft.rfft(bloque, N) * H, N)[:len(bloque) + len(h) - 1]
            y[s0:s0 + len(yy)] += yy
    if len(y) < n_sal:
        y = np.concatenate([y, np.zeros(n_sal - len(y))])
    return y[:n_sal]


def _reverb(x, rt60=1.2, mezcla=0.25, predelay=0.015, brillo=1.0, sem=7, cola=True, corte_bajo=150.0, seco=1.0):
    """Devuelve estéreo: seco + mezcla * reverberación (con la cola si cola=True)."""
    hL, hR = _ir(round(rt60, 3), round(predelay, 4), round(brillo, 3), sem, round(corte_bajo, 1))
    x = _cola(x, seg=0.03)
    if x.ndim == 1:
        xl = xr = x
    else:
        xl, xr = x[:, 0], x[:, 1]
    n = len(x) + (len(hL) if cola else 0)
    out = np.zeros((n, 2))
    out[:len(x), 0] = xl * seco
    out[:len(x), 1] = xr * seco
    out[:, 0] += mezcla * _conv(xl, hL, n)
    out[:, 1] += mezcla * _conv(xr, hR, n)
    return out


# Sonoridad y terminación de cada efecto

def _aw(fr):
    f2 = np.maximum(fr, 1e-3) ** 2
    ra = (12194.0 ** 2 * f2 ** 2) / ((f2 + 20.6 ** 2) * np.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2)) *
                                     (f2 + 12194.0 ** 2))
    return ra * 1.2589


def nivel_a50(x):
    """Sonoridad de un efecto: máximo del RMS ponderado A en ventanas de 50 ms (dBFS; promedio de potencia L/R)."""
    x = np.asarray(x, np.float64)
    canales = [x[:, 0], x[:, 1]] if x.ndim == 2 else [x]
    w = int(0.05 * SR)
    pot = None
    for c in canales:
        xa = _fft_filtro(c, _aw, pad=4096)
        if len(xa) <= w:
            p = np.array([np.mean(xa ** 2)])
        else:
            cs = np.cumsum(np.concatenate([[0.0], xa ** 2]))
            p = (cs[w:] - cs[:-w]) / w
        pot = p if pot is None else pot + p
    pot = pot / len(canales)
    return float(10 * np.log10(pot.max() + 1e-20))


def _final(x, la=None, pico=None, ini=0.0005, fin=0.006):
    """Sin DC (pasa-altos de fase cero a 18 Hz), bordes con fundido, nivel pedido y pico máximo 0,9."""
    x = np.asarray(x, np.float64)
    x = _fft_filtro(x, _hp(18.0, 0.7071, 1), pad=16384)
    n = len(x)
    a = max(2, min(n // 4, int(ini * SR)))
    b = max(2, min(n // 4, int(fin * SR)))
    ra = 0.5 - 0.5 * np.cos(np.pi * np.arange(a) / a)
    rb = 0.5 + 0.5 * np.cos(np.pi * (np.arange(b) + 1) / b)
    if x.ndim == 2:
        ra, rb = ra[:, None], rb[:, None]
    x[:a] *= ra
    x[-b:] *= rb
    if pico is not None:
        x *= pico / (np.abs(x).max() + 1e-12)
    elif la is not None:
        x *= 10 ** ((la - nivel_a50(x)) / 20)
    p = np.abs(x).max()
    if p > PICO_MAX:
        x *= PICO_MAX / p
    return x.astype(np.float32)


def _estereo(x, pan):
    """Mono -> estéreo con ley de potencia constante (centro = 1 en cada canal)."""
    return np.stack([x * math.sqrt(1 - pan), x * math.sqrt(1 + pan)], axis=1)


# ─── Efectos ──────────────────────────────────────────────────────────────

def e_clic(dur=None):
    """Clic de mouse: el botón baja (plástico, chasquido brillante) y suelta 62 ms después, más suave."""
    r = _rl(101)
    n = int(0.14 * SR)
    t = np.arange(n) / SR
    x = np.zeros(n)
    for t0, esc, amp in ((0.0, 1.0, 1.0), (0.062, 1.08, 0.4)):
        tt = t - t0
        x += amp * _modos(tt, [(3300 * esc, 0.0022, 1.0), (5600 * esc, 0.0012, 0.45), (1500 * esc, 0.005, 0.5),
                               (720 * esc, 0.009, 0.28)])
        x += amp * 0.28 * _ruido_banda(n, 2500, 11000, r) * _env(tt, 0.0001, 0.0006)
    return _final(x, la=-25)


def e_tecla(dur=None):
    """Tecla de teclado mecánico: tope del fondo (plástico + 'thock' grave + caja) y retorno. Varía en cada llamada."""
    r = _rng
    n = int(0.2 * SR)
    t = np.arange(n) / SR
    esc = r.uniform(0.93, 1.07)
    f_tapa = r.uniform(1800, 2500) * esc
    f_thock = r.uniform(360, 500) * esc
    x = _modos(t, [(f_tapa, 0.0035, 0.7), (f_tapa * r.uniform(1.65, 2.1), 0.0018, 0.4),
                   (f_thock, r.uniform(0.009, 0.014), 0.8), (r.uniform(170, 240), 0.02, 0.16),
                   (r.uniform(5200, 6800), 0.03, 0.018)])
    x += 0.3 * _ruido_banda(n, 1500, 10000, r) * _env(t, 0.0001, 0.0005)
    tu = r.uniform(0.075, 0.12)
    au = r.uniform(0.22, 0.38)
    x += au * (_modos(t - tu, [(f_tapa * 1.17, 0.0025, 0.7), (f_thock * 1.25, 0.006, 0.4)]) +
               0.3 * _ruido_banda(n, 2000, 10000, r) * _env(t - tu, 0.0001, 0.0004))
    return _final(x, la=-31 + r.uniform(-2.0, 2.0))


def e_enter(dur=None):
    """Tecla grande (Enter / barra): más grave y con el estabilizador que traquetea."""
    r = _rl(103)
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    x = _modos(t, [(245, 0.02, 0.9), (520, 0.012, 0.55), (1480, 0.005, 0.5), (2650, 0.003, 0.45),
                   (180, 0.03, 0.2)])
    x += 0.32 * _ruido_banda(n, 1200, 9000, r) * _env(t, 0.0001, 0.0007)
    x += _modos(t - 0.005, [(3400, 0.012, 0.08), (7200, 0.006, 0.05)])
    tu = 0.155
    x += 0.33 * (_modos(t - tu, [(2900, 0.0025, 0.7), (640, 0.006, 0.4)]) +
                 0.3 * _ruido_banda(n, 2000, 10000, r) * _env(t - tu, 0.0001, 0.0005))
    return _final(x, la=-27)


def e_pop(dur=None):
    """Pop suave de interfaz: burbuja que sube de 360 a 880 Hz y se apaga en ~0,1 s."""
    r = _rl(104)
    t = _t(0.18)
    f = 360 + 520 * (1 - np.exp(-t / 0.012))
    ph = _fase(f)
    x = (np.sin(ph) + 0.12 * np.sin(2 * ph)) * _env(t, 0.0015, 0.04)
    x += 0.08 * _ruido_banda(len(t), 3000, 9000, r) * _env(t, 0.0001, 0.0006)
    x = _fft_filtro(x, _lp(3500, 0.7071, 1))
    return _final(x, la=-25)


def _soplo(D, pk, f_lo, f_hi, ancho, cuerpo, tono, pan0, pan1, sem, la, tono_amp=0.1):
    """Barrido de aire estéreo: banda de ruido que sube y baja con la intensidad (efecto Doppler), paneo que cruza,
    capa grave de cuerpo y un tono tenue que acompaña el barrido."""
    r = _rl(sem)
    n = int(D * SR)

    def forma(tc):
        p = np.clip(tc / D, 0, 1)
        return np.where(p < pk, (p / pk) ** 2.2, np.clip((1 - p) / (1 - pk), 0, 1) ** 1.6)

    def masc(tc, fr):
        e = forma(tc)
        fc = f_lo * (f_hi / f_lo) ** e
        g = _campana_log(fr, fc, ancho) + cuerpo * _campana_log(fr, 200.0, 0.9)
        return e * g * _lp(11000, 0.7071, 1)(fr)

    m = _ruido_formado(n, masc, r)
    d1 = _ruido_formado(n, masc, r)
    d2 = _ruido_formado(n, masc, r)
    t = np.arange(n) / SR
    pan = pan0 + (pan1 - pan0) * _suave(t / D)
    L = m * np.sqrt(1 - pan) + 0.45 * d1
    R = m * np.sqrt(1 + pan) + 0.45 * d2
    if tono:
        e = forma(t)
        s = _sierra(tono * 2 ** (1.1 * e), n) + _sierra(tono * 1.006 * 2 ** (1.1 * e), n, 0.3)
        s = _fft_filtro(s, _lp(1300, 0.7071, 2)) * e ** 1.5
        s *= tono_amp * _rms(m) / (_rms(s) + 1e-9) * 2.0
        L += s
        R += s
    return _final(np.stack([L, R], 1), la=la, ini=0.002, fin=0.01)


def e_whoosh(dur=None):
    """Barrido de transición (0,65 s, punto fuerte a 0,22 s), de izquierda a derecha."""
    D = dur or 0.65
    return _soplo(D, 0.34, 260, 2600, 0.9, 0.35, 150, -0.6, 0.6, 105, la=-25)


def e_whoosh_corto(dur=None):
    """Barrido corto y más brillante (0,34 s, punto fuerte a 0,11 s), de derecha a izquierda."""
    D = dur or 0.34
    return _soplo(D, 0.33, 500, 4200, 0.8, 0.15, 260, 0.5, -0.5, 106, la=-26, tono_amp=0.06)


def e_swish(dur=None):
    """Latigazo de aire, agudo y muy rápido (0,24 s)."""
    D = dur or 0.24
    return _soplo(D, 0.28, 2000, 7000, 0.7, 0.0, 0, 0.4, -0.4, 107, la=-27)


def e_cambio(dur=None):
    """Cambio de pantalla de la interfaz: barrido de aire corto y suave con un golpecito grave."""
    D = dur or 0.36
    x = _soplo(D, 0.35, 900, 3800, 0.8, 0.25, 0, -0.3, 0.3, 108, la=None).astype(np.float64)
    t = np.arange(len(x)) / SR
    th = np.sin(_fase(95 + 60 * np.exp(-t / 0.02))) * _env(t - 0.1, 0.002, 0.05)
    x += 0.15 * np.abs(x).max() * th[:, None]
    return _final(x, la=-29, ini=0.002, fin=0.01)


def _bombo_golpe(t, f0=52, salto=150, caida_f=0.022, caida=0.13, ataque=0.0008):
    return np.sin(_fase(f0 + salto * np.exp(-t / caida_f))) * _env(t, ataque, caida)


def e_impacto(dur=None):
    """Golpe cinematográfico: sub-grave que cae, pegada, cuerpo, chasquido y una cola amplia."""
    r = _rl(109)
    n = int(3.6 * SR)
    t = np.arange(n) / SR
    sub = np.sin(_fase(36 + 55 * np.exp(-t / 0.08))) * _env(t, 0.002, 0.6)
    pat = _bombo_golpe(t, 52, 150, 0.022, 0.13)
    cuerpo = _ruido_banda(n, 120, 900, r) * _env(t, 0.0005, 0.09)
    chas = _ruido_banda(n, 2500, 12000, r) * _env(t, 0.0001, 0.006)
    x = 0.7 * sub + 0.8 * pat + 0.5 * cuerpo + 0.4 * chas
    x = np.tanh(1.8 * x / np.abs(x).max()) / np.tanh(1.8)
    escombros = [_ruido_banda(n, 200, 3500, r) * _env(t, 0.01, 0.5) * 0.08 for _ in range(2)]
    st = np.stack([x + escombros[0], x + escombros[1]], 1)
    st = _reverb(st, rt60=2.6, mezcla=0.3, predelay=0.015, sem=3, cola=False)
    return _final(st, la=-17, fin=0.3)


def e_boom(dur=None):
    """Grave profundo (cae de 56 a 30 Hz) con armónicos para que se oiga también en parlantes chicos."""
    r = _rl(110)
    n = int(4.6 * SR)
    t = np.arange(n) / SR
    ph = _fase(30 + 26 * np.exp(-t / 0.3))
    x = np.sin(ph) * _env(t, 0.006, 0.9) + 0.45 * np.sin(2 * ph) * _env(t, 0.006, 0.5)
    x += 0.25 * _ruido_banda(n, 25, 140, r) * _env(t, 0.02, 0.9)
    x += 0.35 * _ruido_banda(n, 60, 600, r) * _env(t, 0.001, 0.035)
    x = np.tanh(1.5 * x / np.abs(x).max())
    st = _reverb(x, rt60=2.0, mezcla=0.15, brillo=0.6, sem=4, cola=False)
    return _final(st, pico=0.8, fin=0.4)


def e_riser(dur=None):
    """Subida de tensión (1,6 s): ruido que se abre hacia los agudos, sierras que suben dos octavas (La2 → La4),
    trémolo que se acelera e imagen estéreo que se ensancha. Termina en su punto más alto (para el golpe)."""
    D = dur or 1.6
    r = _rl(111)
    n = int(D * SR)
    t = np.arange(n) / SR
    p = t / D

    def masc(tc, fr):
        q = np.clip(tc / D, 0, 1)
        fc = 350 * (9000 / 350) ** (q ** 1.35)
        return (0.04 + 0.96 * q ** 2) * _campana_log(fr, fc, 1.1)

    centro = _ruido_formado(n, masc, r)
    lados = [_ruido_formado(n, masc, r) for _ in range(2)]
    trem = 1 - 0.35 * p * (0.5 + 0.5 * np.cos(_fase(5 + 17 * p ** 2)))
    f = 110 * 2 ** (2 * p ** 1.7)
    ton = sum(_sierra(f * 2 ** (d / 12), n, ph) for d, ph in ((-0.12, 0.1), (0.0, 0.5), (0.12, 0.8)))
    ton = _stft_aplicar(ton, lambda tc, fr: _lp(250 * 20 ** np.clip(tc / D, 0, 1), 0.9, 2)(fr), N=2048)
    ton *= p ** 1.4 * 0.5 * _rms(centro) / (_rms(ton) + 1e-9)
    ancho = 0.2 + 0.6 * p
    L = (centro + ancho * lados[0]) * trem + ton
    R = (centro + ancho * lados[1]) * trem + ton
    return _final(np.stack([L, R], 1), la=-19, ini=0.01, fin=0.015)


def _platillo(largo, tau, sem, brillo=1.0):
    """Platillo: seis osciladores cuadrados inarmónicos filtrados (metal) + ruido agudo, estéreo."""
    r = _rl(sem)
    n = int(largo * SR)
    t = np.arange(n) / SR
    metal = sum(_cuadrada(f * 1.7, n, r.random()) for f in (205.3, 304.4, 369.6, 522.7, 540.0, 800.0))
    metal = _fft_filtro(metal, _y(_hp(6000 * brillo, 0.7071, 2), _lp(12500, 0.7071, 1)))
    metal /= _rms(metal)
    env = (1 - np.exp(-t / 0.0015)) * np.exp(-t / tau)
    canales = []
    for _ in range(2):
        ruido = _ruido_banda(n, 4500 * brillo, 15000, r)
        canales.append((0.5 * metal + 0.6 * ruido) * env)
    return _cola(np.stack(canales, 1), frac=0.25)


def e_reverse(dur=None):
    """Platillo invertido que crece durante 'dur' (1,6 s) y termina en un golpe (bombo, caja, platillo, sub)."""
    lead = dur or 1.6
    r = _rl(112)
    n = int((lead + 1.4) * SR)
    t = np.arange(n) / SR
    i = int(lead * SR)
    x = np.zeros((n, 2))
    inv = _platillo(lead, 0.5 * lead, 113)[::-1]
    s0 = i - len(inv)
    x[max(0, s0):i] += inv[max(0, -s0):]
    succ = _ruido_banda(n, 80, 1200, r) * np.where(t < lead, np.exp(-(lead - t) / 0.35), 0) * 0.3
    x += succ[:, None]
    tt = t - lead
    golpe = 0.9 * _bombo_golpe(tt, 50, 130, 0.03, 0.22)
    golpe += 0.5 * _ruido_banda(n, 900, 5000, r) * _env(tt, 0.0005, 0.09)
    golpe += 0.3 * np.sin(2 * np.pi * 190 * np.maximum(tt, 0)) * _env(tt, 0.0008, 0.05)
    golpe += 0.6 * np.sin(2 * np.pi * 42 * np.maximum(tt, 0)) * _env(tt, 0.003, 0.35)
    crash = np.zeros((n, 2))
    pc = _platillo(1.3, 0.4, 114) * 0.45
    crash[i:i + len(pc)] = pc[:n - i]
    hit = _reverb(golpe[:, None] * np.ones((1, 2)) + crash, rt60=2.2, mezcla=0.25, sem=5, cola=False)
    return _final(x + hit, la=-19, ini=0.01, fin=0.05)


def e_glitch(dur=None):
    """Falla digital: trozos de tono con reducción de bits, tartamudeos de ruido y chirridos, cada uno en un lugar
    distinto del estéreo. Varía en cada llamada."""
    r = _rng
    D = dur or 0.5
    n = int(D * SR)
    x = np.zeros((n, 2))
    i = 0
    while i < n * 0.85:
        largo = int(r.uniform(0.012, 0.055) * SR)
        tt = np.arange(largo) / SR
        tipo = int(r.integers(0, 4))
        if tipo == 0:
            s = np.sin(2 * np.pi * r.uniform(150, 1800) * tt)
            q = int(r.integers(2, 5))
            s = np.round(s * q) / q
            h = int(r.integers(4, 24))
            s = np.repeat(s[::h], h)[:largo]
        elif tipo == 1:
            trozo = r.standard_normal(int(r.uniform(0.002, 0.008) * SR))
            s = np.tile(trozo, largo // len(trozo) + 1)[:largo] * 0.6
            h = int(r.integers(2, 10))
            s = np.repeat(s[::h], h)[:largo]
        elif tipo == 2:
            f0, f1 = r.uniform(300, 4000, 2)
            s = np.sign(np.sin(_fase(f0 * (f1 / f0) ** (tt / tt[-1])))) * 0.5
        else:
            s = np.sin(2 * np.pi * 70 * tt) * np.exp(-tt / 0.02)
        s = s * _compuerta(tt, 0.0, tt[-1] - 0.0015, 0.0015, 0.0015) * r.uniform(0.4, 1.0)
        pan = r.uniform(-0.7, 0.7)
        m = min(largo, n - i)
        x[i:i + m, 0] += s[:m] * math.sqrt(1 - pan)
        x[i:i + m, 1] += s[:m] * math.sqrt(1 + pan)
        i += largo + int(r.uniform(0, 0.012) * SR)
    t = np.arange(n) / SR
    x *= _env(t, 0.001, 0.4)[:, None]
    x = _fft_filtro(x, _lp(9000, 0.7071, 1))
    return _final(x, la=-23)


def e_buzz(dur=None):
    """Vibración de celular sobre la mesa: dos pulsos del motor (168 Hz) con el traqueteo de la carcasa."""
    r = _rl(115)
    n = int(1.15 * SR)
    t = np.arange(n) / SR
    on = _compuerta(t, 0.0, 0.40, 0.025, 0.03) + _compuerta(t, 0.58, 0.98, 0.025, 0.03)
    f = 168 * (1 + 0.018 * np.sin(2 * np.pi * 6 * t)) * (0.82 + 0.18 * np.minimum(1, on * 1.2))
    ph = _fase(f)
    motor = np.sin(ph) + 0.5 * np.sin(2 * ph + 0.3) + 0.25 * np.sin(3 * ph + 1.1)
    traq = ((0.5 + 0.5 * np.cos(ph)) ** 8) * _ruido_banda(n, 1200, 4000, r)
    x = (0.6 * motor + 0.7 * traq) * on
    return _final(x, la=-26)


def e_ping(dur=None):
    """Notificación tipo Discord: dos notas redondas que suben (La5 → Mi6), con un poco de sala."""
    t = _t(1.9)
    x = np.zeros(len(t))
    for f, t0, tau, a in ((880.0, 0.0, 0.17, 0.8), (1318.51, 0.085, 0.3, 1.0)):
        tt = t - t0
        fi = f * (1 + 0.012 * np.exp(-np.maximum(tt, 0) / 0.012)) * (tt >= 0)
        ph = _fase(fi)
        x += a * (np.sin(ph) + 0.16 * np.sin(2 * ph) + 0.04 * np.sin(3 * ph)) * _env(tt, 0.0025, tau)
    st = _reverb(x, rt60=0.9, mezcla=0.2, predelay=0.012, sem=6)
    return _final(st, la=-18, fin=0.05)


def _marimba_nota(tt, f, amp=1.0):
    caida = 0.35 * (1046.5 / f) ** 0.5
    x = _modos(tt, [(f, caida, 1.0), (3.93 * f, 0.05, 0.22), (9.2 * f, 0.012, 0.06)])
    return amp * x


def e_notif(dur=None):
    """Notificación de celular: arpegio rápido de marimba (Do6, Mi6, Sol6)."""
    r = _rl(116)
    t = _t(2.4)
    x = np.zeros(len(t))
    for i, f in enumerate((1046.5, 1318.51, 1567.98)):
        tt = t - i * 0.075
        x += _marimba_nota(tt, f, 0.85 + 0.1 * i)
        x += 0.12 * _ruido_banda(len(t), None, 4000, r) * _env(tt, 0.0002, 0.0015)
    st = _reverb(x, rt60=0.8, mezcla=0.18, sem=7)
    return _final(st, la=-20, fin=0.05)


def e_sello(dur=None):
    """Sello de goma contra el escritorio: golpe sordo, goma, madera que resuena, papel y una sala chica."""
    r = _rl(117)
    n = int(1.1 * SR)
    t = np.arange(n) / SR
    x = np.sin(_fase(70 + 120 * np.exp(-t / 0.012))) * _env(t, 0.0006, 0.075)
    x += 0.35 * np.sin(2 * np.pi * 52 * t) * _env(t, 0.003, 0.16)
    x += _modos(t, [(205, 0.05, 0.45), (437, 0.032, 0.35), (980, 0.016, 0.22), (1760, 0.008, 0.14),
                    (2900, 0.004, 0.08)])
    x += 0.6 * _ruido_banda(n, 500, 3200, r) * _env(t, 0.0002, 0.008)
    x += 0.3 * _ruido_banda(n, 150, 900, r) * _env(t, 0.001, 0.03)
    x += 0.05 * _ruido_banda(n, 3000, 10000, r) * _env(t, 0.002, 0.03)
    st = _reverb(x, rt60=0.45, mezcla=0.22, predelay=0.004, brillo=0.8, sem=8)
    return _final(st, la=-23, fin=0.05)


def _fm(tt, f, ratio, indice, caida_i, caida, ataque=0.0015):
    t0 = np.maximum(tt, 0)
    I = indice * np.exp(-t0 / caida_i)
    return np.sin(2 * np.pi * f * t0 + I * np.sin(2 * np.pi * f * ratio * t0)) * _env(tt, ataque, caida)


def e_ding(dur=None):
    """Éxito: campana de cristal que sube de Sol6 a Do7."""
    t = _t(3.6)
    x = np.zeros(len(t))
    for f, t0, a in ((1567.98, 0.0, 0.75), (2093.0, 0.07, 1.0)):
        tt = t - t0
        x += a * (_fm(tt, f, 2.0, 1.1, 0.05, 0.55) + 0.2 * _modos(tt, [(3 * f, 0.12, 1.0)]))
    st = _reverb(x, rt60=1.2, mezcla=0.25, sem=9)
    return _final(st, la=-19, fin=0.06)


def e_error(dur=None):
    """Error: dos pitidos graves que bajan (La3 → Fa#3), cuadrados y redondeados."""
    t = _t(0.55)
    n = len(t)
    x = np.zeros(n)
    for f, t0 in ((220.0, 0.0), (185.0, 0.17)):
        osc = _fft_filtro(_cuadrada(f, n) + 0.5 * np.sin(2 * np.pi * f * t), _lp(1800, 0.7071, 2))
        x += osc * _compuerta(t, t0, t0 + 0.13, 0.004, 0.025)
    st = _reverb(x, rt60=0.4, mezcla=0.1, sem=10)
    return _final(st, la=-22, fin=0.03)


def e_interruptor(dur=None):
    """Interruptor de luz: resorte que salta y el contacto 6 ms después, con un golpe grave de la pared."""
    r = _rl(118)
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    x = np.zeros(n)
    for t0, esc, a in ((0.0, 1.0, 1.0), (0.006, 1.06, 0.8)):
        tt = t - t0
        x += a * _modos(tt, [(2350 * esc, 0.003, 1.0), (4100 * esc, 0.0018, 0.6), (1150 * esc, 0.006, 0.5),
                             (6600 * esc, 0.0009, 0.3)])
        x += a * 0.4 * _ruido_banda(n, 3000, 12000, r) * _env(tt, 0.0001, 0.0005)
    x += 0.35 * np.sin(2 * np.pi * 140 * t) * _env(t, 0.0008, 0.012)
    st = _reverb(x, rt60=0.4, mezcla=0.12, sem=11)
    return _final(st, la=-23, fin=0.03)


def e_tic(dur=None):
    """Tic de reloj: madera chica y aguda. Varía apenas en cada llamada."""
    r = _rng
    n = int(0.05 * SR)
    t = np.arange(n) / SR
    esc = r.uniform(0.96, 1.04)
    x = _modos(t, [(2900 * esc, 0.0018, 1.0), (4700 * esc, 0.001, 0.5), (1250 * esc, 0.003, 0.4)])
    x += 0.2 * _ruido_banda(n, 3000, 12000, r) * _env(t, 0.0001, 0.0004)
    return _final(x, la=-30 + r.uniform(-1, 1))


def e_conteo(dur=None):
    """Contador que corre durante 'dur' (1,5 s): blips que suben de tono y se espacian al final, sobre un tono que
    sube suave."""
    D = dur or 1.5
    r = _rl(119)
    n = int((D + 0.12) * SR)
    t = np.arange(n) / SR
    x = np.zeros(n)
    m = int(0.03 * SR)
    tb = np.arange(m) / SR
    clic = _ruido_banda(m, 3000, 12000, r)
    tk = 0.0
    while tk < D:
        p = tk / D
        f = 1100 * 2 ** p
        blip = np.sin(2 * np.pi * f * tb) * _env(tb, 0.0003, 0.006) + 0.3 * clic * _env(tb, 0.0001, 0.0006)
        i = int(tk * SR)
        k = min(m, n - i)
        x[i:i + k] += blip[:k] * (0.65 + 0.35 * p)
        tk += 0.032 + 0.078 * p ** 2.2
    p = np.clip(t / D, 0, 1)
    sub = _fft_filtro(_sierra(220 * 2 ** p, n), _lp(900, 0.7071, 2)) * np.sin(np.pi * p) ** 0.8
    x += 0.08 * sub
    return _final(x, la=-29, fin=0.03)


def e_llega(dur=None):
    """Llegada del contador: golpe grave suave y un acorde de cristal (La5, Mi6, La6) que queda sonando."""
    r = _rl(120)
    t = _t(3.2)
    n = len(t)
    x = 0.9 * _bombo_golpe(t, 55, 100, 0.025, 0.2, 0.001)
    for f, tau, a in ((880.0, 0.5, 0.35), (1318.51, 0.42, 0.3), (1760.0, 0.36, 0.22)):
        x += a * _fm(t, f, 2.0, 0.6, 0.04, tau, 0.002)
    x += 0.2 * _ruido_banda(n, 3000, 12000, r) * _env(t, 0.0001, 0.001)
    st = _reverb(x, rt60=1.3, mezcla=0.22, sem=12)
    return _final(st, la=-21, fin=0.06)


def e_golpe(dur=None):
    """Un ataque que choca contra el escudo: golpe sordo + zumbido de campo de fuerza que cae. Varía en cada
    llamada."""
    r = _rng
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    esc = r.uniform(0.9, 1.1)
    x = 0.8 * np.sin(_fase(60 * esc + 70 * np.exp(-t / 0.02))) * _env(t, 0.0008, 0.06)
    for f, a in ((1150, 0.3), (1730, 0.22), (2470, 0.15)):
        ph = _fase(f * esc * (1 + 0.35 * np.exp(-t / 0.012)))
        x += a * np.sin(ph) * _env(t, 0.0005, r.uniform(0.04, 0.09))
    x += 0.35 * _ruido_banda(n, 1500, 6000, r) * _env(t, 0.0002, 0.012)
    x += 0.06 * _ruido_banda(n, 4000, 14000, r) * _env(t, 0.002, 0.06)
    return _final(x, la=-28 + r.uniform(-1.5, 1.5), fin=0.02)


def e_escudo(dur=None):
    """El escudo se activa: barrido que sube una octava, acorde brillante abierto (La-Mi), zumbido eléctrico y
    chispas."""
    r = _rl(121)
    n = int(4.6 * SR)
    t = np.arange(n) / SR
    f = 110 * 2 ** (np.minimum(1, t / 0.35) ** 0.7)
    bar = _sierra(f * 2 ** (-0.08 / 12), n, 0.2) + _sierra(f * 2 ** (0.08 / 12), n, 0.7)
    bar = _stft_aplicar(bar, lambda tc, fr: _lp(np.where(tc < 0.35, 400 + 3100 * np.clip(tc, 0, 1) / 0.35,
                                                         1500 + 2000 * np.exp(-(tc - 0.35) / 0.3)), 0.9, 2)(fr), N=2048)
    bar *= _env(t, 0.01, 0.6) * 0.35 / (_rms(bar[:int(0.4 * SR)]) * 2.5 + 1e-9)
    brillo = np.zeros(n)
    for fn, a in ((440.0, 0.3), (659.26, 0.25), (880.0, 0.22), (1318.51, 0.15)):
        for d in (-0.03, 0.03):
            brillo += a * np.sin(2 * np.pi * fn * 2 ** (d / 12) * t + r.random() * 6.28)
    brillo *= (1 - np.exp(-t / 0.06)) * np.exp(-t / 0.9) * 0.5
    zum = _fft_filtro(_sierra(110, n), _lp(1800, 0.7071, 2)) * (0.75 + 0.25 * np.sin(2 * np.pi * 11 * t))
    zum *= _env(t, 0.02, 0.7) * 0.12
    gr = (r.random(n) < 40 / SR).astype(float)
    k = np.arange(400)
    chispas = _fft_filtro(np.convolve(gr, (1 - np.exp(-k / 30.0)) * np.exp(-k / 70.0))[:n] * r.standard_normal(n),
                          _hp(6000, 0.7071, 2)) * _env(t, 0.01, 0.5) * 0.08
    x = bar + brillo + zum + chispas
    st = _reverb(x, rt60=1.4, mezcla=0.3, sem=13)
    return _final(st, la=-22, fin=0.08)


def e_desliza(dur=None):
    """Scroll: la rueda del mouse traquetea (rápido y después más lento) con un soplo de aire tenue."""
    D = dur or 0.8
    r = _rl(122)
    n = int((D + 0.05) * SR)
    t = np.arange(n) / SR
    x = np.zeros(n)
    m = int(0.012 * SR)
    tb = np.arange(m) / SR
    tk = 0.0
    while tk < D:
        v = math.sin(math.pi * tk / D) ** 0.7
        clic = _modos(tb, [(3600, 0.0009, 1.0), (1500, 0.0018, 0.5)]) * (0.5 + 0.5 * v)
        i = int(tk * SR)
        k = min(m, n - i)
        x[i:i + k] += clic[:k]
        tk += 1 / (6 + 24 * v) * r.uniform(0.85, 1.15)
    aire = _ruido_formado(n, lambda tc, fr: np.sin(np.pi * np.clip(tc / D, 0, 1)) * _campana_log(fr, 1800, 0.8), r)
    x += 0.15 * aire / (_rms(aire) + 1e-9) * _rms(x)
    return _final(x, la=-35, fin=0.02)


# instrumentos tonales compartidos por los efectos y la música

def _nota(nombre):
    base = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}[nombre[0]]
    i, alt = 1, 0
    while nombre[i] in '#b':
        alt += 1 if nombre[i] == '#' else -1
        i += 1
    midi = 12 * (int(nombre[i:]) + 1) + base + alt
    return 440.0 * 2 ** ((midi - 69) / 12)


@lru_cache(maxsize=256)
def _epiano(f, dur=1.6):
    """Piano eléctrico FM (relación 1:1 con índice que cae + 'tine'), con trémolo estéreo suave."""
    t = _t(dur + 0.6)
    I = 1.5 * np.exp(-t / 0.22) + 0.22
    x = np.sin(2 * np.pi * f * t + I * np.sin(2 * np.pi * f * t))
    x += 0.2 * np.sin(2 * np.pi * f * 4 * t) * np.exp(-t / 0.05) if f * 4 < 16000 else 0
    caida = 1.3 * (440 / f) ** 0.3
    env = (1 - np.exp(-t / 0.002)) * np.exp(-t / caida) * (1 - _suave((t - dur) / 0.5))
    x *= env
    trem = 0.22 * np.sin(2 * np.pi * 3.2 * t)
    return np.stack([x * (1 - trem), x * (1 + trem)], 1).astype(np.float32)


@lru_cache(maxsize=256)
def _pluck(f, brillo=1.0, caida=0.5):
    """Cuerda pulsada aditiva: los armónicos agudos se apagan antes (como un pluck de sintetizador cálido)."""
    t = _t(caida * 3.2)
    x = np.zeros(len(t))
    K = int(min(28, 9000 / f))
    for k in range(1, K + 1):
        fk = k * f * (1 + 0.00015 * k * k)
        a = k ** -1.25 * math.exp(-(k * f) / (2600 * brillo))
        tau = caida / (1 + (k * f) / 1500)
        x += a * np.sin(2 * np.pi * fk * t) * np.exp(-t / tau)
    x *= 1 - np.exp(-t / 0.0015)
    x = _cola(x, frac=0.3)
    return (x / (np.abs(x).max() + 1e-9)).astype(np.float32)


@lru_cache(maxsize=128)
def _marimba(f):
    t = _t(1.3)
    x = _marimba_nota(t, f) + 0.06 * _ruido_banda(len(t), None, 3500, _rl(int(f))) * _env(t, 0.0002, 0.002)
    x *= 1 - _suave((t - 1.1) / 0.2)
    return (x / (np.abs(x).max() + 1e-9)).astype(np.float32)


@lru_cache(maxsize=64)
def _glock(f, caida=1.2):
    t = _t(caida * 3)
    x = _modos(t, [(f, caida, 1.0), (2.76 * f, caida * 0.35, 0.3), (5.4 * f, caida * 0.12, 0.12),
                   (8.93 * f, caida * 0.06, 0.05)])
    x *= 1 - np.exp(-t / 0.001)
    x *= 1 - _suave((t - caida * 2.6) / (caida * 0.4))
    return (x / (np.abs(x).max() + 1e-9)).astype(np.float32)


@lru_cache(maxsize=1024)
def _pad_nota(f, dur, corte, voces=3, det=0.08, ataque=0.6, rel=1.4, sem=0):
    """Nota de colchón: sierras desafinadas abiertas en estéreo + senoidal, filtro pasa-bajos y envolvente lenta.
    Los osciladores se generan a 24 kHz y se pasan a 48 kHz en la misma FFT que aplica el filtro (el filtro deja
    poco por encima de 8 kHz, así que no se pierde nada y cuesta la mitad)."""
    n = int((dur + rel) * SR)
    sr2 = SR // 2
    n2 = (n + 1) // 2
    t2 = np.arange(n2) / sr2
    r = _rl(sem + int(f * 100))
    L, R = np.zeros(n2), np.zeros(n2)
    for k in range(voces):
        c = (k - (voces - 1) / 2) / max(1, (voces - 1) / 2)
        ff = f * 2 ** (c * det / 12) * (1 + 0.0012 * np.sin(2 * np.pi * (0.3 + 0.13 * k) * t2 + r.random() * 6.28))
        s_ = _sierra(ff, n2, r.random(), sr2)
        pan = c * 0.8
        L += s_ * math.sqrt(1 - pan)
        R += s_ * math.sqrt(1 + pan)
    sub = (0.3 if f >= 120 else 0.15) * np.sin(2 * np.pi * f * t2 + r.random() * 6.28)
    L, R = L / voces + sub, R / voces + sub
    m2 = _largo_fft(n2 + 1024)
    m = 2 * m2
    g = _resp_pad(m2, corte)
    st = np.empty((n, 2))
    for c, x in enumerate((L, R)):
        X = np.zeros(m // 2 + 1, np.complex128)
        X[:m2 // 2 + 1] = np.fft.rfft(x, m2) * g
        st[:, c] = np.fft.irfft(X, m)[:n]
    st *= _env_pad(n, dur, ataque, rel)[:, None]
    m = min(n, int(min(0.3, rel * 0.3) * SR))
    st[-m:] *= (0.5 + 0.5 * np.cos(np.pi * (np.arange(m) + 1) / m))[:, None]
    return st.astype(np.float32)


@lru_cache(maxsize=64)
def _resp_pad(m2, corte):
    fr = np.fft.rfftfreq(m2, 2 / SR)
    return _lp(corte, 0.75, 1)(fr) * _lp(9000, 0.7071, 2)(fr) * 2.0


@lru_cache(maxsize=128)
def _coro_nota(f, dur, ataque=0.6, rel=1.5):
    """Coro 'aah': sierras con vibrato por un filtro de formantes de la vocal A."""
    n = int((dur + rel) * SR)
    t = np.arange(n) / SR
    r = _rl(int(f * 10) + 5)
    canales = []
    for c in range(2):
        s = np.zeros(n)
        for d in (-0.1, 0.1):
            vib = 1 + 0.004 * np.sin(2 * np.pi * (5.1 + 0.3 * c + d) * t + r.random() * 6)
            s += _sierra(f * 2 ** (d / 12) * vib, n, r.random())
        canales.append(s)
    form = lambda fr: (0.12 * _lp(3000)(fr) + _bp(800, 6)(fr) + 0.6 * _bp(1150, 7)(fr) + 0.25 * _bp(2900, 9)(fr))
    st = _fft_filtro(np.stack(canales, 1), form, pad=2048)
    env = _env_pad(n, dur, ataque, rel)
    st = _cola(st * env[:, None], seg=min(0.3, rel * 0.3))
    return (st / (np.abs(st).max() + 1e-9)).astype(np.float32)


@lru_cache(maxsize=256)
def _bajo(f, dur, tipo='sub'):
    """Bajo: 'sub' (senoidal con armónicos suaves y saturación) o 'pluck' (sierra con filtro que se cierra)."""
    n = int((dur + 0.25) * SR)
    t = np.arange(n) / SR
    if tipo == 'sub':
        ph = 2 * np.pi * f * t
        x = np.sin(ph) + 0.28 * np.sin(2 * ph) + 0.1 * np.sin(3 * ph)
        x = np.tanh(1.3 * x) / np.tanh(1.3)
        env = (1 - np.exp(-t / 0.01)) * np.where(t > dur, np.exp(-(t - dur) / 0.05), 1.0)
    else:
        s = _sierra(f, n)
        brillante = _fft_filtro(s, _lp(1600, 1.2, 2))
        oscuro = _fft_filtro(s, _lp(320, 0.8, 2))
        e = np.exp(-t / 0.07)
        x = brillante * e + oscuro * (1 - e) + 0.8 * np.sin(2 * np.pi * f * t)
        env = (1 - np.exp(-t / 0.003)) * np.exp(-t / max(0.12, dur * 0.9)) * np.where(t > dur, np.exp(-(t - dur) / 0.04), 1.0)
    x = _cola(x * env, seg=0.05)
    return (x / (np.abs(x).max() + 1e-9)).astype(np.float32)


# batería y percusión

@lru_cache(maxsize=16)
def _bombo(var=0):
    r = _rl(200 + var)
    t = _t(0.5)
    x = _bombo_golpe(t, 48, 95 + 6 * var, 0.035, 0.28, 0.0008)
    x += 0.25 * _ruido_banda(len(t), 2000, 9000, r) * _env(t, 0.0001, 0.0015)
    x = np.tanh(1.4 * x) / np.tanh(1.4)
    return _cola(x, frac=0.35).astype(np.float32)


@lru_cache(maxsize=16)
def _caja(var=0):
    r = _rl(210 + var)
    t = _t(0.45)
    n = len(t)
    x = 0.45 * _modos(t, [(185, 0.06, 1.0), (330, 0.04, 0.6)])
    x += 0.7 * _ruido_banda(n, 1500, 7000, r) * _env(t, 0.0005, 0.13)
    for k, d in enumerate((0.0, 0.009, 0.018)):
        x += 0.25 * _ruido_banda(n, 900, 3500, r) * _env(t - d, 0.0003, 0.006 if k < 2 else 0.05)
    x = _cola(x, frac=0.3)
    return (x / np.abs(x).max()).astype(np.float32)


@lru_cache(maxsize=16)
def _hat(var=0, abierto=False):
    r = _rl(220 + var)
    t = _t(0.5 if abierto else 0.1)
    n = len(t)
    metal = sum(_cuadrada(f * 2.4, n, r.random()) for f in (205.3, 304.4, 369.6, 522.7, 540.0, 800.0))
    x = 0.5 * _fft_filtro(metal, _hp(7500, 0.7071, 2)) / 3 + 0.6 * _ruido_banda(n, 7000, 16000, r)
    x = _cola(x * _env(t, 0.0003, 0.16 if abierto else 0.022), frac=0.3)
    return (x / np.abs(x).max()).astype(np.float32)


@lru_cache(maxsize=16)
def _shaker(var=0):
    r = _rl(230 + var)
    t = _t(0.12)
    x = _ruido_banda(len(t), 4500, 11000, r) * (1 - np.exp(-t / 0.008)) * np.exp(-t / 0.035)
    return (x / np.abs(x).max()).astype(np.float32)


@lru_cache(maxsize=4)
def _chasquido(var=0):
    r = _rl(240 + var)
    t = _t(0.15)
    x = _ruido_banda(len(t), 1500, 3800, r) * _env(t, 0.0003, 0.015) + 0.4 * _modos(t, [(2200, 0.004, 1.0)])
    return (x / np.abs(x).max()).astype(np.float32)


@lru_cache(maxsize=4)
def _latido():
    t = _t(0.45)
    x = _bombo_golpe(t, 45, 40, 0.03, 0.12, 0.004)
    x = _cola(_fft_filtro(x, _lp(180, 0.7071, 2)), frac=0.3)
    return (x / np.abs(x).max()).astype(np.float32)


@lru_cache(maxsize=8)
def _tom(f):
    r = _rl(int(f))
    t = _t(0.6)
    x = np.sin(_fase(f * (1 + 0.5 * np.exp(-t / 0.03)))) * _env(t, 0.001, 0.25)
    x += 0.2 * _ruido_banda(len(t), 200, 3000, r) * _env(t, 0.0005, 0.04)
    x = _cola(x, frac=0.3)
    return (x / np.abs(x).max()).astype(np.float32)


@lru_cache(maxsize=4)
def _crash(var=0):
    return (_platillo(2.6, 0.9, 250 + var, 0.8) * 0.5).astype(np.float32)


@lru_cache(maxsize=8)
def _tic_reloj(var=0):
    r = _rl(260 + var)
    t = _t(0.04)
    esc = 1.0 + 0.05 * var
    x = _modos(t, [(2900 * esc, 0.0016, 1.0), (4700 * esc, 0.0009, 0.5), (1250 * esc, 0.003, 0.4)])
    x += 0.15 * _ruido_banda(len(t), 3000, 12000, r) * _env(t, 0.0001, 0.0004)
    return (x / np.abs(x).max()).astype(np.float32)


# efectos musicales

def e_acorde(dur=None):
    """Acorde final: Do mayor con novena (colchón que se cierra, piano eléctrico arpegiado y una campanita), que se
    apaga despacio en ~5 s con reverberación larga."""
    n = int(6.8 * SR)
    t = np.arange(n) / SR
    L, R = np.zeros(n), np.zeros(n)
    for f, a in ((65.41, 0.35), (130.81, 0.55), (196.0, 0.5), (329.63, 0.45), (392.0, 0.35), (587.33, 0.25)):
        r = _rl(int(f))
        for k, d in enumerate((-0.06, 0.0, 0.06)):
            s = _sierra(f * 2 ** (d / 12), n, r.random())
            pan = (k - 1) * 0.6
            L += a * s * math.sqrt(1 - pan) / 3
            R += a * s * math.sqrt(1 + pan) / 3
    masc = lambda tc, fr: _lp(400 + 1000 * np.exp(-np.maximum(tc, 0) / 2.5), 0.8, 2)(fr)
    L, R = _stft_aplicar(L, masc, 2048), _stft_aplicar(R, masc, 2048)
    env = (1 - np.exp(-t / 0.08)) * np.exp(-t / 2.1)
    L, R = L * env, R * env
    for i, nom in enumerate(('E4', 'G4', 'C5', 'D5')):
        ep = _epiano(_nota(nom), 4.0)
        i0 = int((0.03 + 0.06 * i) * SR)
        m = min(len(ep), n - i0)
        L[i0:i0 + m] += 0.3 * ep[:m, 0]
        R[i0:i0 + m] += 0.3 * ep[:m, 1]
    gl = _glock(_nota('E6'), 1.4)
    i0 = int(0.3 * SR)
    m = min(len(gl), n - i0)
    L[i0:i0 + m] += 0.1 * gl[:m]
    R[i0:i0 + m] += 0.1 * gl[:m]
    st = _reverb(np.stack([L, R], 1), rt60=3.5, mezcla=0.4, predelay=0.03, sem=14, cola=False)
    st *= (1 - _suave((t - 5.6) / 1.2))[:, None]
    return _final(st, la=-27, ini=0.002, fin=0.1)


def e_sting(dur=None):
    """Golpe musical de revelación: acorde de La en quinta (sin tercera, encaja en La menor y en Do mayor) con
    filtro que se cierra, sub-grave, platillo y un brillo de campana."""
    n = int(4.8 * SR)
    t = np.arange(n) / SR
    L, R = np.zeros(n), np.zeros(n)
    for f, a in ((55.0, 0.5), (110.0, 0.6), (164.81, 0.5), (220.0, 0.45), (329.63, 0.35), (440.0, 0.25)):
        r = _rl(int(f) + 3)
        for d, pan in ((-0.1, -0.5), (0.1, 0.5)):
            s = a * _sierra(f * 2 ** (d / 12), n, r.random())
            L += s * math.sqrt(1 - pan)
            R += s * math.sqrt(1 + pan)
    masc = lambda tc, fr: _lp(600 + 3400 * np.exp(-np.maximum(tc, 0) / 0.25), 0.9, 2)(fr)
    env = (1 - np.exp(-t / 0.004)) * np.exp(-t / 0.9)
    L, R = _stft_aplicar(L, masc, 2048) * env, _stft_aplicar(R, masc, 2048) * env
    sub = 0.8 * np.sin(_fase(45 + 60 * np.exp(-t / 0.05))) * _env(t, 0.002, 0.7)
    cr = _ajustar(_platillo(4.8, 0.9, 15), n) * 0.25
    gl = 0.08 * _ajustar(_glock(1760.0, 1.0), n)
    st = np.stack([L + sub + gl, R + sub + gl], 1) + cr
    st = _reverb(st, rt60=2.8, mezcla=0.32, sem=15, cola=False)
    return _final(st, la=-19, fin=0.5)


def e_titulo(dur=None):
    """Golpe de la portada: aire que crece 0,55 s y golpe (grave, sub y un acorde brillante de Do con novena)."""
    r = _rl(123)
    T = 0.55
    n = int(5.2 * SR)
    t = np.arange(n) / SR

    def masc(tc, fr):
        q = np.clip(tc / T, 0, 1)
        return np.where(tc < T, q ** 3, 0) * _campana_log(fr, 600 * (5000 / 600) ** q, 1.0)

    pre = _ruido_formado(n, masc, r)
    pre = pre / (np.abs(pre).max() + 1e-9) * 0.35
    tt = t - T
    x = pre + 0.9 * _bombo_golpe(tt, 52, 140, 0.025, 0.28)
    x += 0.6 * np.sin(2 * np.pi * 40 * np.maximum(tt, 0)) * _env(tt, 0.003, 0.7)
    x += 0.3 * _ruido_banda(n, 150, 1000, r) * _env(tt, 0.0005, 0.06)
    x += 0.25 * _ruido_banda(n, 3000, 12000, r) * _env(tt, 0.0001, 0.004)
    for i, f in enumerate((783.99, 1046.5, 1174.66, 1318.51)):
        x += 0.18 * _fm(tt - 0.015 * i, f, 2.0, 0.9, 0.06, 1.1, 0.002)
    st = _reverb(x, rt60=2.6, mezcla=0.32, sem=16, cola=False)
    return _final(st, la=-20, ini=0.01, fin=0.5)


ORDEN = ['clic', 'tecla', 'enter', 'pop', 'whoosh', 'whoosh_corto', 'swish', 'impacto', 'boom', 'riser', 'reverse',
         'glitch', 'buzz', 'ping', 'notif', 'sello', 'ding', 'error', 'interruptor', 'tic', 'conteo', 'llega', 'golpe',
         'escudo', 'cambio', 'desliza', 'acorde', 'sting', 'titulo']

EFECTOS6 = {'clic': e_clic, 'tecla': e_tecla, 'enter': e_enter, 'pop': e_pop, 'whoosh': e_whoosh,
            'whoosh_corto': e_whoosh_corto, 'swish': e_swish, 'impacto': e_impacto, 'boom': e_boom, 'riser': e_riser,
            'reverse': e_reverse, 'glitch': e_glitch, 'buzz': e_buzz, 'ping': e_ping, 'notif': e_notif,
            'sello': e_sello, 'ding': e_ding, 'error': e_error, 'interruptor': e_interruptor, 'tic': e_tic,
            'conteo': e_conteo, 'llega': e_llega, 'golpe': e_golpe, 'escudo': e_escudo, 'cambio': e_cambio,
            'desliza': e_desliza, 'acorde': e_acorde, 'sting': e_sting, 'titulo': e_titulo}

# Golpe o punto fuerte de cada efecto, en segundos desde su comienzo (agendar en t_golpe - DESFASES[nombre]).
# riser y reverse: con dur, el punto fuerte es dur. Los que no figuran golpean en 0.
DESFASES = {'whoosh': 0.22, 'whoosh_corto': 0.11, 'swish': 0.067, 'cambio': 0.12, 'riser': 1.6, 'reverse': 1.6,
            'titulo': 0.55, 'enter': 0.0}

ALEATORIOS = {'tecla', 'tic', 'golpe', 'glitch'}
_CACHE_FX = {}


def efecto(nombre, dur=None):
    """Efecto listo para mezclar (mono o estéreo). Los fijos se calculan una vez por (nombre, dur)."""
    if nombre in ALEATORIOS:
        return EFECTOS6[nombre](dur)
    clave = (nombre, None if dur is None else round(float(dur), 3))
    if clave not in _CACHE_FX:
        _CACHE_FX[clave] = EFECTOS6[nombre](dur)
    return _CACHE_FX[clave]


# ─── Música ───────────────────────────────────────────────────────────────
# Todo en La menor / Do mayor a 100 bpm, sobre una grilla de compases global (desde t=0), así las secciones que se
# cruzan quedan a tiempo. Cada sección se arma en una ventana [t0 - 0,4, t1 + 0,4] con buses (colchón, teclas,
# arpegio, bajo, batería...), compresión tipo sidechain desde el bombo, eco en el arpegio, nivel propio y un envío
# a una reverberación de sala grande común.

ACORDES6 = {
    'C': dict(bajo='C2', pad=['E3', 'G3', 'C4', 'E4'], arp=['C4', 'E4', 'G4', 'C5', 'E5']),
    'Cadd9': dict(bajo='C2', pad=['C3', 'G3', 'D4', 'E4'], arp=['C4', 'G4', 'D5', 'E5', 'G5']),
    'G': dict(bajo='G1', pad=['D3', 'G3', 'B3', 'D4'], arp=['B3', 'D4', 'G4', 'B4', 'D5']),
    'Am': dict(bajo='A1', pad=['E3', 'A3', 'C4', 'E4'], arp=['A3', 'C4', 'E4', 'A4', 'C5']),
    'Am7': dict(bajo='A1', pad=['E3', 'G3', 'C4', 'E4'], arp=['A3', 'C4', 'E4', 'G4', 'C5']),
    'F': dict(bajo='F1', pad=['F3', 'A3', 'C4', 'F4'], arp=['A3', 'C4', 'F4', 'A4', 'C5']),
    'Fmaj7': dict(bajo='F1', pad=['F3', 'A3', 'C4', 'E4'], arp=['A3', 'C4', 'E4', 'F4', 'C5']),
    'E': dict(bajo='E1', pad=['E3', 'G#3', 'B3', 'E4'], arp=['G#3', 'B3', 'E4', 'G#4', 'B4']),
    'Em': dict(bajo='E1', pad=['E3', 'G3', 'B3', 'E4'], arp=['G3', 'B3', 'E4', 'G4', 'B4']),
    'Dm': dict(bajo='D2', pad=['D3', 'F3', 'A3', 'D4'], arp=['A3', 'D4', 'F4', 'A4', 'D5']),
}

# nivel de cada sección (RMS por canal, dBFS, antes del ducking de la mezcla)
NIVEL_SECCION = {'calido': -26.0, 'tension': -25.0, 'pulso': -23.0, 'liviano': -26.0, 'epico': -22.0,
                 'final': -26.0}
ENVIO = {'aire': 0.6, 'pad': 0.42, 'keys': 0.38, 'arp': 0.32, 'bajo': 0.0, 'bat': 0.1, 'perc': 0.2, 'coro': 0.55,
         'cuerdas': 0.45, 'drone': 0.25, 'alto': 0.5, 'campana': 0.55}
CON_SIDECHAIN = {'pad', 'keys', 'arp', 'bajo', 'coro', 'cuerdas', 'drone', 'aire'}


class _Seccion:
    def __init__(self, tipo, t0, t1, total, a, b):
        self.tipo, self.t0, self.t1, self.total = tipo, t0, t1, total
        self.a, self.b = a, b
        self.ta, self.tb = a / SR, b / SR
        self.buses = {}
        self.bombos = []
        self.medir = (t0, t1)

    def poner(self, bus, t, x, g=1.0, pan=0.0):
        B = self.buses.get(bus)
        if B is None:
            B = self.buses[bus] = np.zeros((self.b - self.a, 2), np.float32)
        i = int(round(t * SR)) - self.a
        j0, j1 = max(0, -i), min(len(x), len(B) - i)
        if j1 <= j0:
            return
        seg = x[j0:j1]
        gl, gr = g * math.sqrt(1 - pan), g * math.sqrt(1 + pan)
        if seg.ndim == 1:
            B[i + j0:i + j1, 0] += seg * gl
            B[i + j0:i + j1, 1] += seg * gr
        else:
            B[i + j0:i + j1, 0] += seg[:, 0] * gl
            B[i + j0:i + j1, 1] += seg[:, 1] * gr

    def compases(self, prog):
        k0 = int(round(self.t0 / COMPAS))
        for k in range(int(math.floor(self.ta / COMPAS)) - 1, int(math.ceil(self.tb / COMPAS)) + 1):
            tk = k * COMPAS
            if tk >= self.tb:
                break
            yield k - k0, tk, prog[(k - k0) % len(prog)]

    def pad(self, t, acorde, dur, corte, g, voces=3, det=0.08, ataque=0.6, rel=1.4, notas=None):
        notas = notas or ACORDES6[acorde]['pad']
        for i, nom in enumerate(notas):
            x = _pad_nota(round(_nota(nom), 2), round(dur, 2), round(corte, -1), voces, det, ataque, rel)
            self.poner('pad', t, x, g * (1.0 - 0.08 * i))

    def bombo(self, t, g=1.0, var=0):
        self.poner('bat', t, _bombo(var), g)
        self.bombos.append(t)

    def sidechain(self, prof=0.35, rel=0.16):
        n = self.b - self.a
        if not self.bombos:
            return np.ones(n, np.float32)
        imp = np.zeros(n)
        for tb in self.bombos:
            i = int(round(tb * SR)) - self.a
            if 0 <= i < n:
                imp[i] += 1
        k = np.arange(int(0.6 * SR)) / SR
        ker = (1 - np.exp(-k / 0.004)) * np.exp(-k / rel)
        c = _conv(imp, ker, n)
        return (1 - prof * np.clip(c, 0, 1)).astype(np.float32)


def _eco(x, retardo, fb=0.32, taps=4, corte=3500):
    """Eco ping-pong (alterna canales), cada repetición un poco más oscura."""
    n = len(x)
    mono = x.mean(axis=1)
    eco = np.zeros((n, 2))
    for k in range(1, taps + 1):
        d = int(round(k * retardo * SR))
        if d >= n:
            break
        eco[d:, k % 2] += mono[:n - d] * fb ** k
    eco = _fft_filtro(eco, _lp(corte, 0.7071, 1))
    return x + eco


def _sec_calido(S):
    for i, tk, ch in S.compases(['Cadd9', 'G', 'Am7', 'Fmaj7']):
        A = ACORDES6[ch]
        S.pad(tk, ch, COMPAS, 3200, 0.55)
        S.poner('bajo', tk, _bajo(round(_nota(A['bajo']), 2), round(COMPAS * 0.96, 2), 'sub'), 0.3)
        for nom in A['arp'][-2:]:
            S.poner('aire', tk, _pad_nota(round(_nota(nom) * 2, 2), round(COMPAS, 2), 6000.0, 2, 0.1, 0.9, 1.4), 0.11)
        arp = A['arp']
        for j, ix in ((0, 0), (2, 2), (3, 1), (4, 3), (6, 2), (7, 4)):
            vel = 1.0 if j % 2 == 0 else 0.7
            S.poner('keys', tk + j * NEGRA / 2, _epiano(round(_nota(arp[ix]), 2), 1.0), 0.2 * vel,
                    pan=(-0.25 if ix % 2 else 0.25))
        if i % 2 == 0:
            S.poner('campana', tk, _glock(round(_nota(arp[-1]) * 2, 2), 1.2), 0.035, pan=0.3)


def _sec_tension(S):
    n = S.b - S.a
    t = np.arange(n) / SR + S.ta
    drone = 0.5 * np.sin(2 * np.pi * 55 * t) + 0.25 * np.sin(2 * np.pi * 110 * t + 1.0)
    drone *= 0.75 + 0.25 * np.sin(2 * np.pi * 0.21 * t)
    S.poner('drone', S.ta, np.ascontiguousarray(drone.astype(np.float32)), 0.32)
    patron = [0, 0, 12, 0, 0, 12, 0, 12]
    for i, tk, ch in S.compases(['Am', 'Am', 'F', 'E']):
        A = ACORDES6[ch]
        S.pad(tk, ch, COMPAS, 1600, 0.5, ataque=0.9)
        raiz = _nota(A['bajo']) * 2
        for j, st in enumerate(patron):
            vel = 1.0 if j in (0, 3, 6) else 0.65
            S.poner('bajo', tk + j * NEGRA / 2, _bajo(round(raiz * 2 ** (st / 12), 2), 0.22, 'pluck'), 0.34 * vel)
        for b in (0, 2):
            S.poner('bat', tk + b * NEGRA, _latido(), 0.75)
            S.poner('bat', tk + b * NEGRA + 0.22, _latido(), 0.45)
        for j in range(8):
            S.poner('perc', tk + j * NEGRA / 2, _tic_reloj(j % 2), 0.06 if j % 2 else 0.09,
                    pan=(-0.35 if j % 2 else 0.35))
        if i >= 1 and i % 2 == 1:
            nota = 'E5' if ch != 'F' else 'C5'
            S.poner('alto', tk, _pad_nota(round(_nota(nota), 2), round(COMPAS * 2, 2), 2200.0, 2, 0.05, 1.5, 1.5),
                    0.09)


def _sec_pulso(S):
    pasos = [0, 1, 2, 1, 3, 1, 2, 1, 0, 1, 2, 1, 3, 2, 4, 2]
    for i, tk, ch in S.compases(['Am', 'F', 'C', 'G']):
        A = ACORDES6[ch]
        S.pad(tk, ch, COMPAS, 2800, 0.42)
        for s16 in (0, 6, 8):
            S.bombo(tk + s16 * SEMI, 0.8 if s16 != 6 else 0.55)
        if i % 2 == 1:
            S.bombo(tk + 14 * SEMI, 0.5, 1)
        for s16 in (4, 12):
            S.poner('bat', tk + s16 * SEMI, _caja(i % 2), 0.4)
        for s16 in range(0, 16, 2):
            abierto = (s16 == 14 and i % 2 == 1)
            vel = 1.0 if s16 % 4 == 2 else 0.6
            S.poner('perc', tk + s16 * SEMI, _hat(s16 % 3, abierto), (0.22 if abierto else 0.3) * vel, pan=0.25)
        raiz = _nota(A['bajo'])
        for j in range(8):
            st = 12 if j in (3, 7) else 0
            S.poner('bajo', tk + j * NEGRA / 2, _bajo(round(raiz * 2 ** (st / 12), 2), 0.26, 'pluck'),
                    0.38 * (1.0 if j % 2 == 0 else 0.8))
        arp = A['arp']
        for s16, ix in enumerate(pasos):
            vel = 1.0 if s16 % 4 == 0 else (0.8 if s16 % 2 == 0 else 0.6)
            S.poner('arp', tk + s16 * SEMI, _pluck(round(_nota(arp[ix]) * 2, 2), 2.6, 0.28), 0.12 * vel,
                    pan=0.3 * math.sin(s16 * 0.9))


def _sec_liviano(S):
    salto = [0, 2, 3, 5, 6]
    for i, tk, ch in S.compases(['C', 'Am', 'F', 'G']):
        A = ACORDES6[ch]
        S.pad(tk, ch, COMPAS, 3200, 0.32, ataque=0.4)
        arp = A['arp']
        for k, j in enumerate(salto):
            ix = (k * 2 + i) % len(arp)
            S.poner('arp', tk + j * NEGRA / 2, _marimba(round(_nota(arp[ix]) * 2, 2)), 0.2 * (1.0 if j % 2 == 0 else 0.75),
                    pan=(-0.3 if k % 2 else 0.3))
        raiz = _nota(A['bajo']) * 2
        for b, st in ((0, 0), (2, 7)):
            S.poner('bajo', tk + b * NEGRA, _bajo(round(raiz * 2 ** (st / 12), 2), 0.4, 'pluck'), 0.36)
        for j in range(8):
            sw = 0.03 if j % 2 else 0.0
            S.poner('perc', tk + j * NEGRA / 2 + sw, _shaker(j % 3), 0.18 if j % 2 else 0.1, pan=0.35)
        for b in (1, 3):
            S.poner('perc', tk + b * NEGRA, _chasquido(b // 2), 0.16, pan=-0.2)


def _sec_epico(S):
    dur = max(0.1, S.t1 - S.t0)
    T = float(np.clip(0.7 * dur, 6.0, 18.0))
    S.medir = (S.t0 + 0.7 * T if dur > T else S.t0 + 0.6 * dur, S.t1)
    pasos = [0, 2, 1, 3, 2, 4, 3, 2]
    for i, tk, ch in S.compases(['F', 'G', 'Am', 'C']):
        I = float(np.clip((tk - S.t0) / T, 0, 1))
        A = ACORDES6[ch]
        corte = 1600 + 3400 * round(I * 4) / 4
        S.pad(tk, ch, COMPAS, round(corte, -2), 0.26 + 0.12 * I, voces=5, det=0.14, ataque=0.35)
        raiz = _nota(A['bajo'])
        S.poner('bajo', tk, _bajo(round(raiz, 2), round(COMPAS * 0.96, 2), 'sub'), 0.12 + 0.16 * I)
        if I > 0.35:
            for k, nom in enumerate(A['pad'][1:]):
                S.poner('coro', tk, _coro_nota(round(_nota(nom), 2), round(COMPAS, 2)), 0.06 * min(1, (I - 0.35) * 3))
        arp = A['arp']
        div = 4 if I > 0.55 else 2
        for s in range(8 * (div // 2)):
            paso = NEGRA / div
            ix = pasos[s % 8]
            vel = 1.0 if s % div == 0 else 0.7
            S.poner('arp', tk + s * paso, _pluck(round(_nota(arp[ix]) * 2, 2), 2.6, 0.3), (0.07 + 0.08 * I) * vel,
                    pan=0.35 * math.sin(s * 1.3))
        if I > 0.2:
            pulsos = (0, 1, 2, 3) if I > 0.5 else (0, 2)
            for b in pulsos:
                S.bombo(tk + b * NEGRA, 0.42 + 0.25 * I)
        if I > 0.5:
            for b in (1, 3):
                S.poner('bat', tk + b * NEGRA, _caja(b // 2), 0.32 + 0.12 * I)
            if i % 4 == 0:
                S.poner('perc', tk, _crash(0), 0.35 * I)
        if I > 0.7:
            for s8 in range(8):
                S.poner('perc', tk + s8 * NEGRA / 2, _hat(s8 % 3), 0.26 if s8 % 2 else 0.15, pan=0.25)
        if I > 0.45 and i % 4 == 3:
            for k, (f, s16) in enumerate(((196.0, 12), (164.81, 13), (130.81, 14), (110.0, 15))):
                S.poner('bat', tk + s16 * SEMI, _tom(f), 0.3 + 0.05 * k, pan=0.4 - 0.25 * k)


def _sec_final(S, llegada):
    """Cadencia final Fa – Sol – Do: el Do cae justo en 'llegada' y se apaga despacio (cola natural, sin corte)."""
    kg = int(math.floor((llegada - 0.6 * COMPAS) / COMPAS))
    Q = ['G', 'C', 'Am', 'F']
    S.medir = (S.t0, llegada + 1.0)
    for k in range(int(math.floor(S.ta / COMPAS)) - 1, kg + 1):
        tk = k * COMPAS
        ch = Q[(k - kg) % 4]
        dur = (llegada - tk) if k == kg else COMPAS
        A = ACORDES6[ch]
        S.pad(tk, ch, dur, 2800, 0.5)
        S.poner('bajo', tk, _bajo(round(_nota(A['bajo']), 2), round(dur * 0.96, 2), 'sub'), 0.3)
        for nom in A['arp'][-2:]:
            S.poner('aire', tk, _pad_nota(round(_nota(nom) * 2, 2), round(dur, 2), 6000.0, 2, 0.1, 0.9, 1.4), 0.1)
        arp = A['arp']
        for j, ix in enumerate((4, 3, 2, 1)):
            tj = tk + j * NEGRA
            if tj < llegada - 0.3:
                S.poner('keys', tj, _epiano(round(_nota(arp[ix]), 2), 1.2), 0.2 * (1.0 if j == 0 else 0.75),
                        pan=(0.2 if j % 2 else -0.2))
    # el Do final
    notas = ['C3', 'G3', 'D4', 'E4']
    for i, nom in enumerate(notas):
        S.poner('pad', llegada, _pad_nota(round(_nota(nom), 2), 1.4, 1600.0, 3, 0.08, 0.25, 6.0), 0.5 * (1 - 0.08 * i))
    bajo = _bajo(round(_nota('C2'), 2), 1.2, 'sub')
    S.poner('bajo', llegada, bajo * np.exp(-np.arange(len(bajo)) / SR / 0.9).astype(np.float32), 0.34)
    S.poner('drone', llegada, _pad_nota(round(_nota('C2'), 2), 1.0, 300.0, 2, 0.04, 0.2, 5.0), 0.3)
    for i, nom in enumerate(('C4', 'G4', 'C5', 'D5', 'E5')):
        S.poner('keys', llegada + 0.07 * i, _epiano(round(_nota(nom), 2), 4.5), 0.2, pan=-0.3 + 0.15 * i)
    S.poner('campana', llegada + 0.45, _glock(round(_nota('G6'), 2), 1.6), 0.045, pan=0.25)


_SECCIONES = {'calido': _sec_calido, 'tension': _sec_tension, 'pulso': _sec_pulso, 'liviano': _sec_liviano,
              'epico': _sec_epico}


def _render_seccion(tipo, t0, t1, total, n, llegada=None):
    """Devuelve (a, seco, envio): estéreo de la ventana que empieza en la muestra a."""
    ta = max(0.0, t0 - CRUCE / 2)
    tb = min(n / SR, t1 + CRUCE / 2) if t1 < total else n / SR
    a, b = int(round(ta * SR)), int(round(tb * SR))
    S = _Seccion(tipo, t0, t1, total, a, b)
    if tipo == 'final':
        _sec_final(S, llegada)
    else:
        _SECCIONES.get(tipo, _sec_calido)(S)
    m = b - a
    if tipo == 'pulso':
        sc = S.sidechain(0.38, 0.15)
    elif tipo == 'epico':
        sc = S.sidechain(0.28, 0.16)
    else:
        sc = None
    seco = np.zeros((m, 2), np.float32)
    envio = np.zeros((m, 2), np.float32)
    for nombre, B in S.buses.items():
        if nombre == 'arp' and tipo in ('pulso', 'epico'):
            B = _eco(B, 0.45, 0.3, 4).astype(np.float32)
        elif nombre == 'arp' and tipo == 'liviano':
            B = _eco(B, 0.3, 0.22, 3).astype(np.float32)
        if sc is not None and nombre in CON_SIDECHAIN:
            B = B * sc[:, None]
        seco += B
        envio += B * ENVIO.get(nombre, 0.3)
    # nivel de la sección (la reverberación aporta más o menos la potencia del envío)
    i0 = max(0, int((S.medir[0] - ta) * SR))
    i1 = min(m, max(i0 + SR // 2, int((S.medir[1] - ta) * SR)))
    pot = np.mean(seco[i0:i1].astype(np.float64) ** 2) + np.mean(envio[i0:i1].astype(np.float64) ** 2)
    g = 10 ** (NIVEL_SECCION.get(tipo, -25.0) / 20) / math.sqrt(pot + 1e-20)
    # fundidos de potencia constante con las secciones vecinas
    tt = np.arange(m) / SR + ta
    env = np.ones(m)
    if t0 > 0:
        env *= np.sin(np.pi / 2 * np.clip((tt - ta) / CRUCE, 0, 1))
    if t1 < total:
        env *= np.cos(np.pi / 2 * np.clip((tt - (tb - CRUCE)) / CRUCE, 0, 1))
    env = (env * g).astype(np.float32)[:, None]
    return a, seco * env, envio * env


def musica6(secciones, total, stings=(), n=None, llegada=None):
    """Música del video. secciones = [(t0, tipo)] con tipo en calido, tension, pulso, liviano, epico, final;
    total = duración del video; stings = tiempos de golpes musicales (antes de cada uno la música se retira medio
    segundo con un platillo invertido y en el tiempo exacto entra el golpe); llegada = segundo en que cae el Do
    final (por omisión, un compás cerca de total - 6,5 s). Devuelve (L, R) float32 de n muestras
    (por omisión (total + COLA_EXTRA) * SR)."""
    n = n or int(round((total + COLA_EXTRA) * SR))
    L = np.zeros(n, np.float32)
    R = np.zeros(n, np.float32)
    eL = np.zeros(n, np.float32)
    eR = np.zeros(n, np.float32)
    secs = sorted((float(t0), tipo) for t0, tipo in secciones)
    if not secs:
        return L, R
    limites = secs[1:] + [(total, None)]
    for (t0, tipo), (t1, _) in zip(secs, limites):
        if t1 <= t0:
            continue
        ll = None
        if tipo == 'final':
            if llegada is not None and t0 < llegada < total:
                ll = float(llegada)
            else:
                base = max(t0 + 1.5 * COMPAS, total - 6.5)
                ll = round(base / COMPAS) * COMPAS
                ll = float(min(max(ll, t0 + 0.3), max(t0 + 0.3, total - 3.0)))
        a, seco, envio = _render_seccion(tipo, t0, t1, total, n, ll)
        m = min(len(seco), n - a)
        L[a:a + m] += seco[:m, 0]
        R[a:a + m] += seco[:m, 1]
        eL[a:a + m] += envio[:m, 0]
        eR[a:a + m] += envio[:m, 1]
    hL, hR = _ir(2.3, 0.022, 0.8, 21, 200.0)
    L = L + _conv(eL, hL, n).astype(np.float32)
    R = R + _conv(eR, hR, n).astype(np.float32)
    # ecualización general: menos sub (no aporta en parlantes chicos y le quita aire a la voz), algo de brillo
    eq = _y(_hp(30, 0.7071, 1), _estante_bajo(90, -3.0), _estante_alto(3500, 3.5, 0.6))
    L = _fft_filtro(L, eq, pad=SR).astype(np.float32)
    R = _fft_filtro(R, eq, pad=SR).astype(np.float32)
    # golpes musicales
    t = np.arange(n) / SR
    for ts in sorted(stings or []):
        w = np.clip((t - (ts - 0.9)) / 0.75, 0, 1)
        vuelta = np.clip((t - ts) / 0.8, 0, 1)
        dip = 1 - 0.6 * _suave(w) * (1 - _suave(vuelta))
        L *= dip.astype(np.float32)
        R *= dip.astype(np.float32)
        golpe = efecto('sting')
        inv = efecto('reverse', 1.2)
        inv = inv[:int(1.2 * SR)]
        for x, ini, g in ((inv, ts - 1.2, 0.4), (golpe, ts, 0.7)):
            i = int(round(ini * SR))
            j0, j1 = max(0, -i), min(len(x), n - i)
            if j1 > j0:
                L[i + j0:i + j1] += x[j0:j1, 0] * g
                R[i + j0:i + j1] += x[j0:j1, 1] * g
    return L, R


# ─── Mezcla ───────────────────────────────────────────────────────────────

def _bloques_rms(x, bloque):
    nb = int(math.ceil(len(x) / bloque))
    xp = np.zeros(nb * bloque)
    xp[:len(x)] = x
    return np.sqrt(np.mean(xp.reshape(nb, bloque) ** 2, axis=1) + 1e-20)


def _rms_hablando(v):
    """RMS de la voz en los tramos en que habla (bloques de 50 ms a menos de 20 dB del nivel típico)."""
    r = _bloques_rms(v, int(0.05 * SR))
    vivos = r[r > 1e-5]
    if not len(vivos):
        return 1e-4
    ref = np.percentile(vivos, 90)
    act = r[r > ref * 0.1]
    return float(np.sqrt(np.mean(act ** 2)))


def _suavizar(c, sube, baja, paso):
    """Seguidor de envolvente por bloques (ataque y relajación en segundos)."""
    a1 = math.exp(-paso / max(sube, 1e-4))
    a2 = math.exp(-paso / max(baja, 1e-4))
    out = np.empty(len(c))
    v = float(c[0]) if len(c) else 0.0
    for i, x in enumerate(c.tolist()):
        v = (a1 * v + (1 - a1) * x) if x > v else (a2 * v + (1 - a2) * x)
        out[i] = v
    return out


def _a_muestras(g, bloque, n):
    centros = (np.arange(len(g)) + 0.5) * bloque
    return np.interp(np.arange(n), centros, g)


def _compresor(x, umbral=-21.0, razon=2.5, ataque=0.01, rel=0.16, rodilla=6.0):
    bloque = 240
    nivel = 20 * np.log10(_bloques_rms(x, bloque) * math.sqrt(2) + 1e-9)
    sobre = nivel - umbral
    k = 1 - 1 / razon
    red = np.where(sobre <= -rodilla / 2, 0.0,
                   np.where(sobre >= rodilla / 2, sobre * k, k * (sobre + rodilla / 2) ** 2 / (2 * rodilla)))
    red = _suavizar(red, ataque, rel, bloque / SR)
    return x * _a_muestras(10 ** (-red / 20), bloque, len(x))


def _procesar_voz(v):
    """Pasa-altos suave a 75 Hz, menos 'caja' en 220 Hz, presencia en 3,2 kHz y aire; compresión leve; -17 dBFS."""
    resp = _y(_hp(75, 0.7071, 2), _pico(220, -1.5, 1.0), _pico(3200, 2.0, 0.9), _estante_alto(9000, 1.0))
    v = _fft_filtro(v, resp, pad=SR)
    v *= 10 ** (VOZ_RMS_DB / 20) / _rms_hablando(v)
    v = _compresor(v, VOZ_RMS_DB - 4.0, 2.5, 0.008, 0.15, 6.0)
    v *= 10 ** (VOZ_RMS_DB / 20) / _rms_hablando(v)
    return v


def _actividad(v):
    """0..1: dónde habla la voz, con anticipación de 80 ms, sostén de 0,6 s (no 'bombea' entre palabras),
    ataque de 60 ms y relajación de 0,5 s."""
    bloque = 240
    r = _bloques_rms(v, bloque)
    vivos = r[r > 1e-5]
    if not len(vivos):
        return np.zeros(len(v))
    on = (r > np.percentile(vivos, 90) * 0.1).astype(float)
    H, Lk = int(0.6 * SR / bloque), int(0.08 * SR / bloque)
    c = np.convolve(on, np.ones(H + Lk + 1))
    on = (c[Lk:Lk + len(on)] > 0.5).astype(float)
    sm = _suavizar(on, 0.06, 0.5, bloque / SR)
    return _a_muestras(sm, bloque, len(v))


def _limitador(st, techo=0.89, rel=0.08):
    """Limitador con anticipación de 2 ms: la ganancia baja antes del pico y vuelve suave."""
    bloque = 48
    n = len(st)
    nb = int(math.ceil(n / bloque))
    a = np.zeros(nb * bloque)
    a[:n] = np.abs(st).max(axis=1)
    pico = a.reshape(nb, bloque).max(axis=1)
    g = np.minimum(1.0, techo / np.maximum(pico, 1e-9))
    g = np.minimum.reduce([np.roll(g, k) for k in (-2, -1, 0, 1)])
    a2 = math.exp(-bloque / SR / rel)
    out = np.empty(nb)
    v = 1.0
    for i, x in enumerate(g.tolist()):
        v = x if x < v else a2 * v + (1 - a2) * x
        out[i] = v
    gm = _a_muestras(out, bloque, n)
    st = st * gm[:, None]
    return np.clip(st, -PICO_MAX, PICO_MAX)


def mezcla6(d, ruta):
    """Mezcla final: voz centrada y procesada (-17 dBFS al hablar), efectos panoramizados con un toque de sala,
    música con ducking suave y recorte de medios mientras habla la voz, fundido de entrada de 1 s, caída final
    natural y limitador. Escribe WAV 48 kHz estéreo 16 bits con dither."""
    semilla(606)
    total = float(d.total)
    n = int(round((total + COLA_EXTRA) * SR))
    t = np.arange(n) / SR
    # voz
    voz = np.zeros(n)
    for tv, pcm in d.voces:
        i = int(round(tv * SR))
        pcm = np.asarray(pcm, np.float64)
        j0, j1 = max(0, -i), min(len(pcm), n - i)
        if j1 > j0:
            voz[i + j0:i + j1] += pcm[j0:j1]
    hay_voz = np.abs(voz).max() > 1e-6
    act = _actividad(voz) if hay_voz else np.zeros(n)
    if hay_voz:
        voz = _procesar_voz(voz)
    # efectos
    fx = np.zeros((n, 2))
    for item in d.sfxs:
        ts, nombre, gan = item[0], item[1], item[2]
        pan = item[3] if len(item) > 3 and item[3] is not None else 0.0
        dur = item[4] if len(item) > 4 else None
        if nombre not in EFECTOS6:
            print('sonido6: efecto desconocido %r (se omite)' % nombre)
            continue
        x = efecto(nombre, dur).astype(np.float64) * gan
        pan = float(np.clip(pan, -1, 1))
        if x.ndim == 1:
            x = _estereo(x, pan)
        else:
            x = x * np.array([math.sqrt(1 - pan), math.sqrt(1 + pan)])
        i = int(round(ts * SR))
        j0, j1 = max(0, -i), min(len(x), n - i)
        if j1 > j0:
            fx[i + j0:i + j1] += x[j0:j1]
    fx = _reverb(fx, rt60=0.6, mezcla=0.1, predelay=0.008, brillo=0.9, sem=31, cola=False) * GANANCIA_SFX
    # música
    mus = np.zeros((n, 2))
    if MUSICA and getattr(d, 'musica_secciones', None):
        llegada = None
        finales = [t0 for t0, tipo in d.musica_secciones if tipo == 'final']
        acordes = [s[0] for s in d.sfxs if s[1] == 'acorde']
        if finales and acordes and max(acordes) > max(finales):
            llegada = max(acordes)
        mL, mR = musica6(d.musica_secciones, total, getattr(d, 'stings', []), n, llegada)
        # ducking: todo baja ~6 dB mientras habla la voz y los medios (300 Hz - 4 kHz, donde está la voz)
        # bajan otros ~6 dB; la separación en bandas es complementaria (resto + medios = original)
        m = _largo_fft(n + SR)
        fr = np.fft.rfftfreq(m, 1 / SR)
        h_lim = _hp(28, 0.7071, 1)(fr)
        h_med = h_lim * _bp(1100, 0.45)(fr)
        g_total = 1 - 0.5 * act
        g_medios = 1 - 0.5 * act
        for c, canal in enumerate((mL, mR)):
            X = np.fft.rfft(canal.astype(np.float64), m)
            completa = np.fft.irfft(X * h_lim, m)[:n]
            medios = np.fft.irfft(X * h_med, m)[:n]
            del X
            mus[:, c] = (completa - medios + medios * g_medios) * g_total
        del mL, mR
    # fundidos: la música entra en 1 s (efectos y voz 50 ms, para no tapar un golpe de portada al comienzo);
    # al final, música y efectos caen en forma exponencial durante FADE_FIN hasta total
    caida = np.where(t < total - FADE_FIN, 1.0, 10 ** (-27 * np.clip((t - (total - FADE_FIN)) / FADE_FIN, 0, 1) / 20))
    caida *= 1 - _suave((t - (total - 0.35)) / 0.35)
    fondo = (mus * _suave(t / 1.0)[:, None] + fx * _suave(t / 0.05)[:, None]) * caida[:, None]
    voz *= _suave(t / 0.05) * (1 - _suave((t - (total - 0.2)) / 0.2))
    st = fondo + voz[:, None]
    st = _limitador(st, 0.89)
    ruido = (np.random.default_rng(9).random((n, 2)) - np.random.default_rng(10).random((n, 2))) / 32768.0
    pcm = np.clip(np.round((st + ruido) * 32767), -32767, 32767).astype(np.int16)
    with wave.open(ruta, 'wb') as wv:
        wv.setnchannels(2)
        wv.setsampwidth(2)
        wv.setframerate(SR)
        wv.writeframes(pcm.tobytes())
    return ruta
