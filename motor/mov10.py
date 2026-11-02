"""mov10: el movimiento (curvas, resortes, pistas y tiempos atados a la voz).

Lo que cambia respecto de armar2.Pista (que queda sin tocar):

  · Resortes físicos con velocidad continua. Un movimiento nuevo que arranca mientras el anterior todavía se mueve
    hereda su velocidad (posición y velocidad continuas), así la cámara nunca «frena en seco y arranca»: es lo que
    hace que un paneo de cámara se sienta filmado y no animado. Solución analítica (sin integrar), exacta en
    cualquier t: los cuadros de cada tramo y los del desenfoque de movimiento dan siempre lo mismo.
  · Curvas cubic-bezier como las de CSS (las mismas que usan las plantillas de mg10 con anime.js) y curvas con nombre.
  · aterrizar(): el movimiento LLEGA con la palabra (empieza antes), en lugar de arrancar cuando la voz ya la dijo.
    En la v9 la cámara arrancaba en la palabra y llegaba 0,9 s tarde: el foco parecía ir «desfasado» de la voz.

    import mov10 as M
    p = M.Pista10((960.0, 540.0, 1.0))
    p.resorte(2.0, (400.0, 300.0, 1.6), respuesta=0.7, amortiguacion=0.9)    # cámara con resorte
    p.ir(4.0, (960.0, 540.0, 1.0), 0.8, 'cine')                             # o con una curva
    p(3.1), p.velocidad(3.1)

    t0 = M.aterrizar(b.en('hoy'), 0.8)        # empieza 0,8 s × LLEGADA antes de «hoy»: llega con la palabra

Sin dependencias fuera de numpy.
"""
import math

import numpy as np


def lim(v, a=0.0, b=1.0):
    return a if v < a else b if v > b else v


# ─── Curvas ───────────────────────────────────────────────────────────────

class Bezier:
    """cubic-bezier(x1, y1, x2, y2) de CSS: x es el tiempo (0-1) e y el avance. Newton con respaldo de bisección."""

    def __init__(self, x1, y1, x2, y2):
        self.p = (x1, y1, x2, y2)
        self.cx, self.bx, self.ax = 3 * x1, 3 * (x2 - x1) - 3 * x1, 1 - 3 * x2 + 3 * x1
        self.cy, self.by, self.ay = 3 * y1, 3 * (y2 - y1) - 3 * y1, 1 - 3 * y2 + 3 * y1

    def _x(self, s):
        return ((self.ax * s + self.bx) * s + self.cx) * s

    def _y(self, s):
        return ((self.ay * s + self.by) * s + self.cy) * s

    def _dx(self, s):
        return (3 * self.ax * s + 2 * self.bx) * s + self.cx

    def __call__(self, x):
        if x <= 0:
            return 0.0
        if x >= 1:
            return 1.0
        s = x
        for _ in range(8):
            e = self._x(s) - x
            if abs(e) < 1e-7:
                return self._y(s)
            d = self._dx(s)
            if abs(d) < 1e-6:
                break
            s -= e / d
        a, b = 0.0, 1.0
        s = x
        for _ in range(40):
            v = self._x(s)
            if abs(v - x) < 1e-7:
                break
            if v < x:
                a = s
            else:
                b = s
            s = (a + b) / 2
        return self._y(s)


def _expo_out(p):
    return 1.0 if p >= 1 else 1 - 2 ** (-10 * p)


CURVAS = {
    'lineal': lambda p: p,
    'suave': Bezier(0.45, 0.0, 0.55, 1.0),          # entra y sale parejo
    'cine': Bezier(0.65, 0.0, 0.2, 1.0),            # arranque decidido, llegada larga y suave (cámara)
    'sale': Bezier(0.16, 1.0, 0.3, 1.0),            # expo-out de CSS: llega rápido y se asienta (ui)
    'entra': Bezier(0.7, 0.0, 0.84, 0.0),           # acelera (para salir de cuadro)
    'latigo': Bezier(0.8, 0.0, 0.2, 1.0),           # paneo látigo: casi quieto, disparo, casi quieto
    'scroll': Bezier(0.25, 0.1, 0.0, 1.0),          # rueda/trackpad: arranque firme y frenado largo (inercia)
    'expo': _expo_out,
}


def curva(nombre_o_fn):
    if callable(nombre_o_fn):
        return nombre_o_fn
    return CURVAS[nombre_o_fn]


# ─── Resorte ──────────────────────────────────────────────────────────────

class Resorte:
    """Oscilador amortiguado y'' = -w0² y - 2ζw0 y' con y = x - destino.

    respuesta: período del resorte sin amortiguar, en segundos (como el «response» de SwiftUI): 0,5 ágil, 0,9 lento.
    amortiguacion: ζ. 1 = crítico (llega sin pasarse), 0,8 = se pasa un pelo y vuelve (vivo), 0,6 = rebota."""

    def __init__(self, respuesta=0.6, amortiguacion=0.9):
        self.respuesta, self.z = float(respuesta), float(amortiguacion)
        self.w0 = 2 * math.pi / self.respuesta

    def estado(self, y0, v0, t):
        """(y, v) a t segundos de (y0, v0). y0 y v0 pueden ser arrays de numpy."""
        w0, z = self.w0, self.z
        if t <= 0:
            return y0, v0
        if abs(z - 1) < 1e-4:
            e = math.exp(-w0 * t)
            c2 = v0 + w0 * y0
            y = e * (y0 + c2 * t)
            v = e * (c2 - w0 * (y0 + c2 * t))
            return y, v
        if z < 1:
            wd = w0 * math.sqrt(1 - z * z)
            e = math.exp(-z * w0 * t)
            c, s = math.cos(wd * t), math.sin(wd * t)
            b = (v0 + z * w0 * y0) / wd
            y = e * (y0 * c + b * s)
            v = e * ((-z * w0) * (y0 * c + b * s) + (-y0 * wd * s + b * wd * c))
            return y, v
        r = w0 * math.sqrt(z * z - 1)
        l1, l2 = -z * w0 + r, -z * w0 - r
        c1 = (v0 - l2 * y0) / (l1 - l2)
        c2 = y0 - c1
        e1, e2 = math.exp(l1 * t), math.exp(l2 * t)
        return c1 * e1 + c2 * e2, c1 * l1 * e1 + c2 * l2 * e2

    def asentado(self, tol=0.02):
        """Segundos hasta quedar dentro de tol (fracción del salto) partiendo del reposo: la «llegada» perceptible."""
        t, paso = 0.0, self.respuesta / 60
        ultimo_fuera = 0.0
        while t < self.respuesta * 6:
            y, _ = self.estado(1.0, 0.0, t)
            if abs(y) > tol:
                ultimo_fuera = t
            t += paso
        return ultimo_fuera


# ─── Pista ────────────────────────────────────────────────────────────────

class Pista10:
    """Valor (número o tupla) que se anima con tramos de curva o de resorte, con posición y velocidad continuas.

    p.ir(t, valor, dur, curva)              tramo con curva (dur=0: salto)
    p.resorte(t, valor, respuesta, amort.)  tramo con resorte que hereda la velocidad del momento
    p(t) → valor; p.velocidad(t) → derivada (unidades por segundo)
    Los tramos se pueden agregar en cualquier orden: se ordenan por tiempo."""

    def __init__(self, valor):
        self.escalar = not isinstance(valor, (tuple, list, np.ndarray))
        self.v0 = np.atleast_1d(np.asarray(valor, np.float64)).copy()
        self.tramos = []          # dicts: t, tipo, destino, dur, curva/resorte
        self._listo = True
        self._estados = []        # (x, v) al comienzo de cada tramo

    def _agregar(self, tr):
        self.tramos.append(tr)
        self.tramos.sort(key=lambda x: x['t'])
        self._listo = False
        return self

    def ir(self, t, valor, dur=0.8, curva_='cine'):
        return self._agregar(dict(t=float(t), tipo='curva', destino=np.atleast_1d(np.asarray(valor, np.float64)),
                                  dur=max(0.0, float(dur)), curva=curva(curva_)))

    def resorte(self, t, valor, respuesta=0.6, amortiguacion=0.9):
        return self._agregar(dict(t=float(t), tipo='resorte', destino=np.atleast_1d(np.asarray(valor, np.float64)),
                                  resorte=Resorte(respuesta, amortiguacion)))

    def _preparar(self):
        if self._listo:
            return
        self._estados = []
        x, v = self.v0.copy(), np.zeros_like(self.v0)
        for i, tr in enumerate(self.tramos):
            if i > 0:
                x, v = self._en_tramo(i - 1, tr['t'], self._estados[i - 1])
            self._estados.append((x.copy(), v.copy()))
        self._listo = True

    def _en_tramo(self, i, t, inicio):
        tr = self.tramos[i]
        x0, v0 = inicio
        dt = t - tr['t']
        if tr['tipo'] == 'resorte':
            y, v = tr['resorte'].estado(x0 - tr['destino'], v0, dt)
            return tr['destino'] + y, v
        if tr['dur'] <= 0:
            return tr['destino'].copy(), np.zeros_like(x0)
        p = dt / tr['dur']
        if p >= 1:
            return tr['destino'].copy(), np.zeros_like(x0)
        c = tr['curva']
        e = 1e-4
        q = c(p)
        dq = (c(min(1.0, p + e)) - c(max(0.0, p - e))) / (min(1.0, p + e) - max(0.0, p - e))
        return x0 + (tr['destino'] - x0) * q, (tr['destino'] - x0) * dq / tr['dur']

    def _vector(self, t):
        self._preparar()
        i = -1
        for k, tr in enumerate(self.tramos):
            if tr['t'] <= t:
                i = k
            else:
                break
        if i < 0:
            return self.v0.copy(), np.zeros_like(self.v0)
        return self._en_tramo(i, t, self._estados[i])

    def __call__(self, t):
        x, _ = self._vector(t)
        return float(x[0]) if self.escalar else tuple(float(a) for a in x)

    def velocidad(self, t):
        _, v = self._vector(t)
        return float(v[0]) if self.escalar else tuple(float(a) for a in v)

    def quieta(self, t0, t1, tol=1e-3):
        """True si entre t0 y t1 no se mueve (para no gastar muestras de desenfoque)."""
        a, b = np.asarray(self._vector(t0)[0]), np.asarray(self._vector(t1)[0])
        return bool(np.all(np.abs(a - b) < tol))


# ─── Tiempos atados a la voz ──────────────────────────────────────────────

LLEGADA = 0.82      # fracción de un movimiento con curva 'cine' en la que el ojo ya lo ve «llegado»


def aterrizar(t_palabra, dur, llegada=LLEGADA, anticipo=0.06):
    """Comienzo de un movimiento de `dur` s para que llegue (fracción `llegada`) `anticipo` s antes de la palabra:
    la imagen confirma lo que la voz dice en el mismo instante, no después."""
    return t_palabra - anticipo - dur * llegada


def aterrizar_resorte(t_palabra, respuesta=0.6, amortiguacion=0.9, anticipo=0.06, tol=0.08):
    """Lo mismo para un resorte: empieza para quedar a menos del 8 % del destino justo con la palabra."""
    r = Resorte(respuesta, amortiguacion)
    return t_palabra - anticipo - r.asentado(tol)
