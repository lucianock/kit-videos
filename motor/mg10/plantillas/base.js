/* mg10 · protocolo entre mg10.py y las plantillas, y ayudas comunes.
   La plantilla define window.construir(p) → {tl, dur, ancho, alto, ancla, alTiempo(ms)} con una línea de tiempo de
   anime.js en pausa (autoplay: false). mg10.py llama window.__mg.montar(params) y después __mg.ir(ms) cuadro por
   cuadro: tl.seek(ms) más lo que la plantilla calcule a mano (contadores, anillos), siempre en función de ms. */
(function () {
  anime.engine.useDefaultMainLoop = false;     // nadie mueve el tiempo salvo seek(): determinista
  const MG = {
    tl: null, info: null,
    async montar(params) {
      await document.fonts.load('600 40px "Geist"');
      await document.fonts.load('600 40px "Geist Mono"');
      await document.fonts.ready;
      const info = window.construir(params || {});
      this.tl = info.tl;
      this.info = info;
      this.ir(0);
      const r = { dur: info.dur, ancho: Math.ceil(info.ancho), alto: Math.ceil(info.alto), ancla: info.ancla || [0, 0],
                  marcas: info.marcas || {} };
      return r;
    },
    ir(ms) {
      if (this.tl) this.tl.seek(Math.max(0, ms), true);
      if (this.info && this.info.alTiempo) this.info.alTiempo(ms);
      return new Promise((res) => requestAnimationFrame(() => res(true)));
    },
  };
  window.__mg = MG;

  // Ayudas
  window.H = {
    // Envuelve cada letra (o palabra) en <span class="mascara"><span class="letra">…</span></span>
    partir(el, modo) {
      const texto = el.textContent;
      el.textContent = '';
      const piezas = modo === 'palabras' ? texto.split(/(\s+)/) : Array.from(texto);
      const out = [];
      for (const pz of piezas) {
        if (pz === '') continue;
        if (/^\s+$/.test(pz)) { el.appendChild(document.createTextNode(pz)); continue; }
        const m = document.createElement('span');
        m.className = 'mascara';
        const s = document.createElement('span');
        s.className = modo === 'palabras' ? 'pal' : 'letra';
        s.textContent = pz;
        m.appendChild(s);
        el.appendChild(m);
        out.push(s);
      }
      return out;
    },
    miles(v) {
      return Math.round(v).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    },
    // Generador con semilla (mulberry32): el «ruido» de un efecto es el mismo en cada filmación
    azar(semilla) {
      let a = semilla >>> 0;
      return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a);
                     t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
    },
    lim(v, a = 0, b = 1) { return Math.min(b, Math.max(a, v)); },
    expoOut(p) { return p >= 1 ? 1 : 1 - Math.pow(2, -10 * p); },
    suave(p) { p = Math.min(1, Math.max(0, p)); return p * p * (3 - 2 * p); },
    // Texto que se «decodifica»: letras al azar que se van fijando de izquierda a derecha (ms → texto)
    decodificar(final, p, semilla, juego) {
      const al = H.azar(semilla + Math.floor(p * 40));
      const set = juego || 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789·/<>#';
      let s = '';
      for (let i = 0; i < final.length; i++) {
        const umbral = i / Math.max(1, final.length);
        if (final[i] === ' ' || p >= 1 || p * 1.25 > umbral + 0.25) s += final[i];
        else if (p * 1.25 > umbral) s += set[Math.floor(al() * set.length)];
        else s += ' ';
      }
      return s;
    },
  };
})();
