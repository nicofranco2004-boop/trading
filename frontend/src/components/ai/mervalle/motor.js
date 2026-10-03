// Motor de Mervall-E — el dibujo y el movimiento del personaje de la IA.
// ═══════════════════════════════════════════════════════════════════════════
// Es JavaScript de DOM a propósito, no React: el personaje se mueve 60 veces
// por segundo (flota, parpadea, mira el cursor) y pasar eso por el estado de
// React re-renderizaría el árbol en cada cuadro. React (MervallE.jsx) lo crea,
// le cambia el estado cuando pasa algo en el chat y lo destruye al desmontar;
// el cuadro a cuadro lo hace este archivo tocando atributos del SVG.
//
// La referencia visual y de comportamiento es la propuesta aprobada el
// 2026-10-03 (artifact "Mervall-E AI"): mismo dibujo, mismos 13 estados.
//
// Reglas que este archivo hace cumplir:
//   · Sin colores escritos a mano: la pintura vive en mervalle.css y sale de
//     los tokens --mv-* de index.css (claro y oscuro). Acá sólo hay clases y,
//     para lo que cambia en vivo, rgb(var(--mv-*)).
//   · Verde, rojo y ámbar SÓLO en el monitor del pecho y sólo con `tono`
//     (cuando Mervall-E está diciendo un número con signo).
//   · "Reducir movimiento" del sistema: no flota, no sigue el cursor, cambia
//     de cara sin transición.
//   · Un solo bucle para todos los personajes, que se pausa fuera de pantalla
//     y se apaga cuando no queda ninguno montado.

const NS = 'http://www.w3.org/2000/svg'
const f = (v) => Math.round(v * 100) / 100
const clamp = (v, a, b) => Math.max(a, Math.min(b, v))
const rand = (a, b) => a + Math.random() * (b - a)
const ahora = () => (typeof performance !== 'undefined' ? performance.now() : Date.now()) / 1000

/* ── Formas: el mismo dibujo, recortado según el tamaño ──────────────────── */
export const FORMAS = {
  full:   { vb: [0, 0, 200, 262], head: 1, body: 1, shadow: 1, sparks: 1, amp: 1 },
  bust:   { vb: [10, 14, 180, 196], head: 1, body: 1, fade: 1, sparks: 1, amp: 0.8 },
  head:   { vb: [22, 6, 156, 156], head: 1, amp: 0.45 },
  visor:  { vb: [44, 52, 112, 74], visor: 1, amp: 0 },
  screen: { vb: [77, 153, 46, 31], screen: 1, amp: 0 },
}

/** La forma sale del tamaño: a 20 px hasta la cabeza es una mancha; dos luces en un vidrio, no.
 *  De 21 a 48 la cabeza (a 24-26 px, el tamaño de los accesos, se reconoce bien). */
export function formaPara(px) {
  return px <= 20 ? 'visor' : px <= 48 ? 'head' : px <= 110 ? 'bust' : 'full'
}

/** Alto / ancho de cada forma, para reservar el lugar antes de dibujar. */
export function proporcion(forma) {
  const vb = FORMAS[forma].vb
  return vb[3] / vb[2]
}

const D = {
  shell: 'M100 26C140 26 166 52 166 82C166 112 138 134 100 134C62 134 34 112 34 82C34 52 60 26 100 26Z',
  visor: 'M100 56C133 56 152 67 152 88C152 109 131 120 100 120C69 120 48 109 48 88C48 67 67 56 100 56Z',
  gloss: 'M60 74C66 64 80 60 98 60',
  circ: 'M80 47L88 39L96 45L104 35L112 43L120 38',
  body: 'M100 142C128 142 144 152 144 170C144 200 121 231 100 236C79 231 56 200 56 170C56 152 72 142 100 142Z',
  bgloss: 'M72 155C80 149 90 147 102 147',
  arm: 'M0 -2C7 -2 9 8 8.5 20C8 34 3.5 46 -.5 48C-4.5 46 -8.5 34 -8.5 20C-8.5 8 -7 -2 0 -2Z',
  spark: 'M0 -6L1.4 -1.4L6 0L1.4 1.4L0 6L-1.4 1.4L-6 0L-1.4 -1.4Z',
}
const SPARKS = [[44, 40], [160, 32], [170, 120], [28, 126]]

/* ── Monitor del pecho ───────────────────────────────────────────────────
   Zona de dibujo y los gráficos fijos de cada estado (y en unidades del
   dibujo: más chico = más arriba). */
const SX0 = 84, SX1 = 116, SN = 9, SDX = (SX1 - SX0) / (SN - 1), SMID = 168.5
const SHAPES = {
  open:   [170, 170, 169.5, 170, 169, 168, 168.5, 167, 166.5],
  up:     [174, 173, 174.5, 171, 172, 168.5, 169.5, 165, 162.5],
  down:   [163, 164.5, 163.5, 167, 166, 169.5, 168.5, 173, 175.5],
  alert:  [173, 171, 172, 169, 170, 167.5, 168.5, 166.5, 165],
  spike:  [171, 170.5, 171.5, 170.5, 171, 170, 171, 170.5, 161.5],
  record: [174, 172, 173, 169.5, 170.5, 167, 168, 167.5, 161.5],
}
const CANDLES = [[172, 169, 167, 174], [169, 170.5, 167.5, 172], [170.5, 167, 165, 171.5], [167, 168, 164.5, 170], [168, 165, 163, 169], [165, 162.5, 161, 166.5]]
const nz = (n) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x) - 0.5 }

// Colores en vivo. Escritos enteros a propósito: el test de tokens busca el
// literal `var(--mv-pantalla-pos` y un nombre armado por pedazos no lo ve.
const COLOR_OJO = 'rgb(var(--mv-ojo))'
const COLOR_TONO = {
  pos: 'rgb(var(--mv-pantalla-pos))',
  neg: 'rgb(var(--mv-pantalla-neg))',
  warn: 'rgb(var(--mv-pantalla-warn))',
}
const FONDO_VELA_BAJISTA = 'rgb(var(--mv-visor))'

function screenMarkup(u) {
  const velas = CANDLES.map((k, i) => {
    const x = f(86.5 + i * 5.8), top = Math.min(k[0], k[1]), h = Math.max(1, Math.abs(k[0] - k[1]))
    return `<g class="mv-cd" data-bull="${k[1] < k[0] ? 1 : 0}" opacity="0"><path d="M${x} ${k[2]}V${k[3]}" class="mv-cd-w"/><rect x="${f(x - 1.5)}" y="${top}" width="3" height="${h}" rx=".5" class="mv-cd-b"/></g>`
  }).join('')
  let barras = ''
  for (let i = 0; i < 7; i++) barras += `<rect class="mv-bar" x="${f(84.6 + i * 4.55)}" y="175" width="2.6" height="2" rx=".8" opacity="0"/>`
  return `<g class="mv-scr"><rect x="79" y="155" width="42" height="27" rx="7" fill="url(#mvvz${u})" class="mv-scr-frame"/>` +
    `<g clip-path="url(#mvsc${u})"><path class="mv-scr-grid" d="M82 164.5H118M82 172.5H118"/>` +
    `<path class="mv-scr-th" d="M82 165H118" opacity="0"/>` +
    `<g>${velas}</g><g>${barras}</g>` +
    `<g filter="url(#mvgs${u})"><path class="mv-scr-line"/><circle class="mv-scr-dot" r="1.7" cx="116" cy="168.5"/></g></g>` +
    `<path d="M84 157.6H100" class="mv-scr-gloss"/></g>`
}

function visorMarkup(u, rim) {
  return `<g class="mv-visorg"><path d="${D.visor}" fill="url(#mvvz${u})"${rim ? ' class="mv-visor-rim"' : ''}/>` +
    `<path d="${D.gloss}" class="mv-gloss"/>` +
    `<g class="mv-eyes" filter="url(#mvgl${u})"><path class="mv-eye mv-eye-l"/><path class="mv-eye mv-eye-r"/></g></g>`
}

/** El SVG completo de una forma. Puro (sin DOM): se puede probar en Node. */
export function dibujo(u, forma) {
  const F = FORMAS[forma], vb = F.vb
  let s = `<svg xmlns="${NS}" viewBox="${vb.join(' ')}" class="mv-svg" aria-hidden="true" focusable="false"><defs>`
  s += `<radialGradient id="mvsh${u}" cx=".4" cy=".3" r=".9" fx=".4" fy=".28"><stop offset="0" class="mv-s-hi"/><stop offset=".55" class="mv-s-mid"/><stop offset="1" class="mv-s-lo"/></radialGradient>`
  s += `<radialGradient id="mvbd${u}" cx=".42" cy=".2" r=".95"><stop offset="0" class="mv-s-hi"/><stop offset=".5" class="mv-s-mid"/><stop offset="1" class="mv-s-lo"/></radialGradient>`
  s += `<linearGradient id="mvvz${u}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" class="mv-v-hi"/><stop offset="1" class="mv-v-lo"/></linearGradient>`
  s += `<radialGradient id="mvsd${u}"><stop offset="0" class="mv-d-in"/><stop offset="1" class="mv-d-out"/></radialGradient>`
  s += `<filter id="mvgl${u}" x="-60%" y="-80%" width="220%" height="260%"><feGaussianBlur in="SourceAlpha" stdDeviation="2.6" result="b"/><feFlood class="mv-f-eye" result="c"/><feComposite in="c" in2="b" operator="in" result="g"/><feMerge><feMergeNode in="g"/><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge></filter>`
  if (F.body || F.screen) {
    s += `<filter id="mvgs${u}" x="-30%" y="-60%" width="160%" height="220%"><feGaussianBlur in="SourceAlpha" stdDeviation="1.1" result="b"/><feFlood class="mv-f-scr" result="c"/><feComposite in="c" in2="b" operator="in" result="g"/><feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge></filter>`
    s += `<clipPath id="mvsc${u}"><rect x="82" y="158" width="36" height="21" rx="4"/></clipPath>`
  }
  if (F.fade) {
    // Máscara de luminancia: blanco = se ve. No es un color de la interfaz.
    s += `<linearGradient id="mvfd${u}" x1="0" y1="0" x2="0" y2="1"><stop offset=".87" stop-color="white"/><stop offset="1" stop-color="white" stop-opacity="0"/></linearGradient>` +
      `<mask id="mvmk${u}" maskUnits="userSpaceOnUse" x="${vb[0] - 40}" y="${vb[1] - 40}" width="${vb[2] + 80}" height="${vb[3] + 40}">` +
      `<rect x="${vb[0] - 40}" y="${vb[1]}" width="${vb[2] + 80}" height="${vb[3]}" fill="url(#mvfd${u})"/>` +
      `<rect x="${vb[0] - 40}" y="${vb[1] - 40}" width="${vb[2] + 80}" height="40" fill="white"/></mask>`
  }
  s += `</defs><g${F.fade ? ` mask="url(#mvmk${u})"` : ''}>`
  if (F.shadow) s += `<ellipse class="mv-shadow" cx="100" cy="252" rx="34" ry="5.5" fill="url(#mvsd${u})"/>`
  s += '<g class="mv-float">'
  if (F.body) {
    s += '<g class="mv-bodyg">' +
      `<g class="mv-arm-l"><path d="${D.arm}" fill="url(#mvbd${u})" class="mv-edge"/></g>` +
      `<g class="mv-arm-r"><path d="${D.arm}" fill="url(#mvbd${u})" class="mv-edge"/></g>` +
      `<path d="${D.body}" fill="url(#mvbd${u})" class="mv-edge"/>` +
      `<path d="${D.bgloss}" class="mv-gloss-b"/>` +
      screenMarkup(u) +
      '</g>'
  }
  if (F.head) {
    s += '<g class="mv-headg">' +
      `<path d="${D.shell}" fill="url(#mvsh${u})" class="mv-edge"/>` +
      '<ellipse class="mv-disc mv-disc-l" cx="37" cy="86" rx="4.5" ry="13"/><ellipse class="mv-disc mv-disc-r" cx="163" cy="86" rx="4.5" ry="13"/>' +
      `<g filter="url(#mvgl${u})"><ellipse class="mv-disc-lit mv-dl-l" cx="37" cy="86" rx="4.5" ry="13" opacity="0"/><ellipse class="mv-disc-lit mv-dl-r" cx="163" cy="86" rx="4.5" ry="13" opacity="0"/></g>` +
      `<g><path d="${D.circ}" class="mv-circ"/><path d="${D.circ}" class="mv-circ-lit" filter="url(#mvgl${u})" opacity="0"/></g>` +
      visorMarkup(u, false) +
      '</g>'
  }
  if (F.visor) s += visorMarkup(u, true)
  if (F.screen) s += screenMarkup(u)
  if (F.sparks) s += '<g>' + SPARKS.map((p) => `<path d="${D.spark}" class="mv-spark" transform="translate(${p[0]} ${p[1]}) scale(0)"/>`).join('') + '</g>'
  s += '</g></g></svg>'
  return s
}

/* ── Ojos ────────────────────────────────────────────────────────────────
   Cada forma es un juego de números. ti/to = alto del borde de arriba del
   lado interno/externo; bi/bo = lo mismo abajo (negativo = curva hacia
   arriba, y eso da el arco de "contento"). */
const EK = ['w', 'h', 'ti', 'to', 'bi', 'bo', 'r']
const E = (w, h, ti, to, bi, bo, r = 0) => ({ w, h, ti, to, bi, bo, r })
const EX = {
  neutral:  E(17, 12, 1, 1, 1, 1),
  happy:    E(19, 10, 1, 1, -0.45, -0.45),
  wide:     E(17.5, 14, 1, 1, 1, 1),
  think:    E(18, 8, 0.5, 0.95, 0.85, 0.85, -3),
  focus:    E(19, 8.5, 0.28, 0.28, 1, 1),
  surprise: E(15, 15, 1, 1, 1, 1),
  sleep:    E(17, 6, -0.3, -0.3, 0.5, 0.5),
  dot:      E(9, 9, 1, 1, 1, 1),
  alert:    { L: E(18, 8.5, 0.4, 0.85, 0.9, 0.9), R: E(17, 13, 1.05, 0.9, 1, 1) },
  confused: { L: E(13, 13, 1, 1, 1, 1), R: E(18, 7.5, 0.7, 1, 0.6, 0.6, -8) },
}

export function eyePath(p, mirror, bk, sw, sh) {
  const hw = p.w * sw / 2, k = 1.3333 * p.h * bk * sh
  const tL = mirror ? p.ti : p.to, tR = mirror ? p.to : p.ti
  const bL = mirror ? p.bi : p.bo, bR = mirror ? p.bo : p.bi
  return `M${f(-hw)} 0C${f(-hw)} ${f(-k * tL)} ${f(hw)} ${f(-k * tR)} ${f(hw)} 0C${f(hw)} ${f(k * bR)} ${f(-hw)} ${f(k * bL)} ${f(-hw)} 0Z`
}
const copyE = (e) => { const o = {}; EK.forEach((k) => { o[k] = e[k] }); return o }

/* ── Estados ─────────────────────────────────────────────────────────────
   Qué cara pone, cuánto flota, dónde van los brazos (ángulo hacia afuera, en
   grados; una función recibe los segundos desde que entró al estado) y qué
   dibuja el monitor del pecho. */
export const ESTADOS = {
  reposo:     { eyes: 'neutral', bob: 1, arms: [8, 8], scr: 'idle' },
  saludo:     { eyes: 'happy', bob: 1, arms: [14, (a) => 128 + Math.sin(a * 9) * 20], tilt: -5, track: 0.5, scr: 'open' },
  escuchando: { eyes: 'wide', bob: 0.6, arms: [16, 16], tilt: -7, disc: 1, scr: 'idle' },
  pensando:   { eyes: 'think', bob: 0.5, arms: [8, 34], tilt: 7, look: [-0.55, -0.8], circ: 1, scr: 'think' },
  hablando:   { eyes: 'neutral', bob: 0.8, arms: [10, (a) => 22 + Math.sin(a * 3.1) * 10], track: 0.7, talk: 1, scr: 'talk' },
  contento:   { eyes: 'happy', bob: 1, arms: [24, 24], tilt: -4, track: 0.6, hop: [2, 0.4], hopH: 9, scr: 'up' },
  atento:     { eyes: 'alert', bob: 0.6, arms: [8, 72], tilt: -6, track: 0.8, scr: 'alert' },
  serio:      { eyes: 'focus', bob: 0.3, arms: [3, 3], track: 0.5, sink: 3, scr: 'down' },
  sorpresa:   { eyes: 'surprise', bob: 0.4, arms: [34, 34], track: 0.6, jolt: 1, scr: 'spike' },
  confundido: { eyes: 'confused', bob: 0.7, arms: [8, 158], tilt: 11, track: 0.3, scr: 'gap' },
  durmiendo:  { eyes: 'sleep', bob: 0.45, arms: [2, 2], tilt: 6, track: 0, sink: 9, dim: 0.55, slow: 1, blink: 0, scr: 'flat' },
  festejo:    { eyes: 'happy', bob: 1, arms: [(a) => 150 + Math.sin(a * 14) * 10, (a) => 150 + Math.sin(a * 14 + 1) * 10], track: 0.3, hop: [4, 0.5], hopH: 11, hopCycle: 3.4, sparks: 1, circ: 0.8, circFull: 1, scr: 'record' },
  cargando:   { eyes: 'dot', bob: 0.5, arms: [8, 8], track: 0, scan: 1, circ: 0.5, scr: 'load' },
}

/* ── Señales que no pasan por React ─────────────────────────────────────
   Tipear, hablar por micrófono y cada pedazo de texto que llega del stream
   son eventos de alta frecuencia: mandarlos por el estado de React
   re-renderizaría el chat entero en cada tecla. Llegan acá directo. */
const senal = { tipeoT: -9, mic: false, palabras: 0 }
/** Una tecla en el cuadro de la pregunta. Mervall-E pasa a "escuchando". */
export function avisarTipeo() { senal.tipeoT = ahora() }
/** El micrófono empezó o terminó de grabar. */
export function avisarMicrofono(grabando) { senal.mic = !!grabando }
/** Llegó un pedazo de la respuesta: las barras del pecho laten con él. */
export function avisarPalabra() { senal.palabras++ }

/* ── El bucle compartido ────────────────────────────────────────────────── */
const G = { reduced: false, track: true, ptr: { x: 0, y: 0, on: false, t: 0 } }
const INST = []
let uid = 0, corriendo = false, ultimo = 0, io = null, oyentes = false

function prepararGlobal() {
  if (oyentes || typeof window === 'undefined') return
  oyentes = true
  const mq = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null
  G.reduced = !!(mq && mq.matches)
  if (mq && mq.addEventListener) mq.addEventListener('change', (e) => { G.reduced = e.matches })
  const setPtr = (e) => { G.ptr.x = e.clientX; G.ptr.y = e.clientY; G.ptr.on = true; G.ptr.t = ahora() }
  window.addEventListener('pointermove', setPtr, { passive: true })
  window.addEventListener('pointerdown', setPtr, { passive: true })
  document.addEventListener('mouseout', (e) => { if (!e.relatedTarget) G.ptr.on = false })
  if ('IntersectionObserver' in window) {
    io = new IntersectionObserver((es) => es.forEach((e) => { const m = e.target.__mv; if (m) m.vis = e.isIntersecting }), { rootMargin: '120px' })
  }
}

function lookFor(m) {
  const r = m.svg.getBoundingClientRect()
  if (!r.width) return null
  const vb = m.vb
  const hx = r.left + (100 - vb[0]) / vb[2] * r.width
  const hy = r.top + ((m.forma === 'visor' ? 88 : 82) - vb[1]) / vb[3] * r.height
  let tx, ty
  const foco = m.escuchandoAhora && typeof document !== 'undefined' ? document.activeElement : null
  const el = m.lookEl || (foco && /^(INPUT|TEXTAREA)$/.test(foco.tagName) ? foco : null)
  if (el) { const b = el.getBoundingClientRect(); tx = b.left + b.width * 0.3; ty = b.top + b.height / 2 }
  else if (G.ptr.on && ahora() - G.ptr.t < 6) { tx = G.ptr.x; ty = G.ptr.y }
  else return null
  const dx = tx - hx, dy = ty - hy
  if (!el && Math.sqrt(dx * dx + dy * dy) > m.opt.trackRadius) return null
  return { x: Math.tanh(dx / 200), y: Math.tanh(dy / 200) * 0.85 }
}

function cuadro(ms) {
  const t = ms / 1000
  let dt = (ms - ultimo) / 1000
  ultimo = ms
  if (!(dt > 0) || dt > 0.1) dt = 0.016
  const act = INST.filter((m) => m.vis && !m.opt.frozen && m.host.isConnected)
  const looks = act.map(lookFor)                     // primero se lee todo…
  act.forEach((m, i) => m.update(t, dt, looks[i], false)) // …después se escribe
  // Los congelados no necesitan cuadros: si sólo quedan ellos, el bucle se apaga.
  if (INST.some((m) => !m.opt.frozen)) requestAnimationFrame(cuadro)
  else corriendo = false
}
function arrancar() {
  if (corriendo || typeof requestAnimationFrame === 'undefined') return
  corriendo = true
  ultimo = performance.now()
  requestAnimationFrame(cuadro)
}

/* ── Un personaje ───────────────────────────────────────────────────────── */
class Personaje {
  constructor(host, opt = {}) {
    prepararGlobal()
    this.host = host
    this.u = ++uid
    this.forma = opt.forma || formaPara(opt.size || 160)
    this.opt = {
      track: opt.track !== false,
      trackRadius: opt.trackRadius || Infinity,
      still: !!opt.still,
      blink: opt.blink !== false,
      frozen: !!opt.frozen,
      escucha: !!opt.escucha,
    }
    host.innerHTML = dibujo(this.u, this.forma)
    this.svg = host.firstElementChild
    this.vb = FORMAS[this.forma].vb
    const q = (s) => this.svg.querySelector(s)
    const qa = (s) => Array.prototype.slice.call(this.svg.querySelectorAll(s))
    this.el = {
      float: q('.mv-float'), body: q('.mv-bodyg'), armL: q('.mv-arm-l'), armR: q('.mv-arm-r'),
      head: q('.mv-headg'), visor: q('.mv-visorg'), eyes: q('.mv-eyes'), eyeL: q('.mv-eye-l'), eyeR: q('.mv-eye-r'),
      circ: q('.mv-circ-lit'), discL: q('.mv-disc-l'), discR: q('.mv-disc-r'), dlL: q('.mv-dl-l'), dlR: q('.mv-dl-r'),
      shadow: q('.mv-shadow'), sh: q(`#mvsh${this.u}`),
      scr: q('.mv-scr'), sLine: q('.mv-scr-line'), sDot: q('.mv-scr-dot'), sTh: q('.mv-scr-th'), sFlood: q('.mv-f-scr'),
      bars: qa('.mv-bar'), cds: qa('.mv-cd'), sparks: qa('.mv-spark'),
    }
    this.circLen = 60
    try { if (this.el.circ) this.circLen = this.el.circ.getTotalLength() || 60 } catch { /* sin layout todavía */ }
    this.P = { lx: 0, ly: 0, tilt: 0, sink: 0, dim: 1, circ: 0, disc: 0, al: 8, ar: 8, talk: 0, eL: copyE(EX.neutral), eR: copyE(EX.neutral) }
    this.ph = rand(0, 6.28)
    this.bAt = ahora() + rand(0.8, 3.5)
    this.bT = -9
    this.wd = { x: 0, y: 0, next: 0 }
    this.tAmp = 0
    this.vistas = senal.palabras
    this.ultimaPalabra = -9
    this.tone = opt.tone || null
    this.flashT = -9
    this.seed = rand(0, 60)
    this.lookEl = null
    this.vis = true
    this._col = ''
    host.__mv = this
    this.setState(opt.state || 'reposo')
    INST.push(this)
    if (io) io.observe(host)
    this.update(ahora(), 0.016, null, true)
    if (!this.opt.frozen) arrancar()
  }

  setState(nombre) {
    if (!ESTADOS[nombre] || nombre === this.state) return
    this.state = nombre
    this.S = ESTADOS[nombre]
    this.stateT = ahora()
    this.host.setAttribute('data-estado', nombre)
    if (this.opt.frozen && this.svg) this.update(ahora() + 0.3, 0.016, null, true)
  }
  /** Vuelve a arrancar el estado actual desde cero (un saludo que se repite). */
  repetir() { this.stateT = ahora() }
  setTone(tono) { this.tone = COLOR_TONO[tono] ? tono : null; if (this.opt.frozen) this.update(ahora() + 0.3, 0.016, null, true) }
  /** Enciende los anillos una vez: "tengo algo nuevo". No insiste. */
  flash() { this.flashT = ahora() }

  destroy() {
    const i = INST.indexOf(this)
    if (i !== -1) INST.splice(i, 1)
    if (io) io.unobserve(this.host)
    delete this.host.__mv
    this.host.innerHTML = ''
  }

  update(t, dt, look, instant) {
    const o = this.opt, E2 = this.el, P = this.P
    const red = G.reduced, age = t - this.stateT
    // "Escuchando" se superpone al reposo mientras tipeás o hablás por el
    // micrófono: no cambia el estado de fondo, sólo la cara de este momento.
    this.escuchandoAhora = o.escucha && this.state === 'reposo' && (t - senal.tipeoT < 1.2 || senal.mic)
    const S = this.escuchandoAhora ? ESTADOS.escuchando : this.S
    const snap = instant || red
    const calm = red || o.still
    const k = snap ? 1 : 1 - Math.exp(-dt * 10)
    const kl = snap ? 1 : 1 - Math.exp(-dt * 5.5)
    const ka = snap ? 1 : 1 - Math.exp(-dt * 11)
    const A = FORMAS[this.forma].amp

    /* 1. Mirada: el estado manda; si no, el cursor; si no, mira alrededor */
    let gx = 0, gy = 0
    const trk = (S.track == null ? 1 : S.track) * (o.track && G.track && !red ? 1 : 0)
    if (S.look) {
      gx = S.look[0]; gy = S.look[1]
      if (!red) { gx += Math.sin(t * 0.9) * 0.08; gy += Math.sin(t * 1.3) * 0.05 }
    } else if (look && trk > 0) {
      gx = look.x * trk; gy = look.y * trk
    } else if (!calm && !S.scan) {
      if (t > this.wd.next) {
        const big = Math.random() < 0.3
        this.wd.x = big ? rand(-0.6, 0.6) : rand(-0.25, 0.25)
        this.wd.y = rand(-0.2, 0.25)
        this.wd.next = t + rand(1.6, 4.2)
      }
      gx = this.wd.x; gy = this.wd.y
    }
    P.lx += (gx - P.lx) * kl; P.ly += (gy - P.ly) * kl
    P.tilt += ((S.tilt || 0) - P.tilt) * k * 0.8
    P.sink += ((S.sink || 0) - P.sink) * k * 0.6
    P.dim += ((S.dim == null ? 1 : S.dim) - P.dim) * k
    P.circ += ((S.circ || 0) - P.circ) * (snap ? 1 : k * 0.6)
    let dT = S.disc || 0
    const fp = (t - this.flashT) / 1.6
    if (fp >= 0 && fp < 1) dT = Math.max(dT, Math.sin(fp * Math.PI))
    P.disc += (dT - P.disc) * (snap ? 1 : k)

    /* 2. Brazos */
    const ev = (v) => (typeof v === 'function' ? v(red ? 0.17 : age) : v)
    P.al += (ev(S.arms[0]) - P.al) * ka; P.ar += (ev(S.arms[1]) - P.ar) * ka

    /* 3. Flotar, saltar, respingo */
    const amp = calm ? 0 : 3.2 * (S.bob == null ? 1 : S.bob) * A
    this.ph += dt * (S.slow ? 1.05 : 1.9)
    const bob = Math.sin(this.ph) * amp
    let hop = 0, jolt = 0
    if (!calm && S.hop) {
      const cyc = S.hopCycle ? age % S.hopCycle : age, n = S.hop[0], per = S.hop[1]
      if (cyc < n * per) hop = -Math.abs(Math.sin(cyc / per * Math.PI)) * (S.hopH || 9) * A
    }
    if (!calm && S.jolt) jolt = -9 * Math.exp(-age * 3.2) * Math.sin(Math.min(age * 9, Math.PI))
    const y = bob + hop + (jolt + P.sink) * A
    const lag = calm ? 0 : Math.sin(this.ph - 0.8) * amp * 0.4

    /* 4. Habla: no tiene boca; laten los ojos y las barras del pecho. Si el
          texto está llegando, laten con cada pedazo; si no (la voz leyendo),
          con un ritmo de habla inventado. */
    if (this.vistas !== senal.palabras) { this.vistas = senal.palabras; this.tAmp = 1; this.ultimaPalabra = t }
    let talk = 0
    if (S.talk && !red) {
      if (t - this.ultimaPalabra < 0.6) { this.tAmp *= Math.exp(-dt * 7); talk = this.tAmp }
      else { const w = Math.sin(t * 2.1) + Math.sin(t * 3.4 + 1); talk = w > -1.1 ? 0.55 + 0.45 * Math.sin(t * 15) : 0.1 }
    }
    P.talk += (talk - P.talk) * (snap ? 1 : 1 - Math.exp(-dt * 18))

    /* 5. Ojos y parpadeo */
    const ex = EX[S.eyes], tL = ex.L || ex, tR = ex.R || ex
    for (const key of EK) { P.eL[key] += (tL[key] - P.eL[key]) * k; P.eR[key] += (tR[key] - P.eR[key]) * k }
    let bk = 1
    if (o.blink && S.blink !== 0 && !red) {
      if (t >= this.bAt) { this.bT = t; this.bAt = t + (Math.random() < 0.18 ? 0.32 : rand(2.6, 5.8)) }
      const bp = (t - this.bT) / 0.17
      if (bp >= 0 && bp < 1) bk = 1 - Math.sin(bp * Math.PI) * 0.9
    }
    const scan = (S.scan && !red) ? Math.sin(t * 4.2) * 9 : 0

    /* 6. Escribir en el dibujo */
    const lx = P.lx, ly = P.ly
    if (E2.float) E2.float.setAttribute('transform', `translate(0 ${f(y)})`)
    if (E2.shadow) {
      E2.shadow.setAttribute('rx', f(34 * clamp(1 + y / 45, 0.6, 1.25)))
      E2.shadow.setAttribute('opacity', f(clamp(0.85 + y / 40, 0.35, 1)))
    }
    if (E2.body) {
      E2.body.setAttribute('transform', `rotate(${f(lx * 3)} 100 190) translate(${f(lx * 1.5)} 0)`)
      E2.armL.setAttribute('transform', `translate(50 152) rotate(${f(P.al)})`)
      E2.armR.setAttribute('transform', `translate(150 152) scale(-1 1) rotate(${f(P.ar)})`)
    }
    if (E2.head) E2.head.setAttribute('transform', `translate(${f(lx * 3.5)} ${f(ly * 2.5 + lag)}) rotate(${f(P.tilt + lx * 3)} 100 84)`)
    const vs = this.forma === 'visor' ? 1.5 : 4.5
    if (E2.visor) E2.visor.setAttribute('transform', `translate(${f(lx * vs)} ${f(ly * vs * 0.7)})`)
    if (E2.eyeL) {
      const es = this.forma === 'visor' ? 0.8 : 1
      const fL = 1 + (lx > 0 ? 0.05 : 0.12) * lx, fR = 1 - (lx > 0 ? 0.12 : 0.05) * lx
      const tw = 1 - 0.04 * P.talk, th = 1 + 0.16 * P.talk
      E2.eyeL.setAttribute('d', eyePath(P.eL, false, bk, fL * tw, th))
      E2.eyeR.setAttribute('d', eyePath(P.eR, true, bk, fR * tw, th))
      E2.eyeL.setAttribute('transform', `translate(${f(79 + lx * 6 * es + scan)} ${f(89 + ly * 4.5 * es)}) rotate(${f(P.eL.r)})`)
      E2.eyeR.setAttribute('transform', `translate(${f(121 + lx * 6 * es + scan)} ${f(89 + ly * 4.5 * es)}) rotate(${f(-P.eR.r)})`)
      E2.eyes.setAttribute('opacity', f(P.dim))
    }
    if (E2.circ) {
      E2.circ.setAttribute('opacity', f(P.circ))
      if (S.circFull || red) E2.circ.style.strokeDasharray = 'none'
      else {
        E2.circ.style.strokeDasharray = `16 ${f(this.circLen)}`
        E2.circ.style.strokeDashoffset = f(16 - ((age * 34) % (this.circLen + 16)))
      }
    }
    if (E2.discL) {
      const rl = clamp(4.5 + lx * 3, 1.2, 7.5), rr = clamp(4.5 - lx * 3, 1.2, 7.5)
      E2.discL.setAttribute('rx', f(rl)); E2.discR.setAttribute('rx', f(rr))
      E2.dlL.setAttribute('rx', f(rl)); E2.dlR.setAttribute('rx', f(rr))
      const dop = f(P.disc * (red ? 1 : 0.65 + 0.35 * Math.sin(t * 6)))
      E2.dlL.setAttribute('opacity', dop); E2.dlR.setAttribute('opacity', dop)
    }
    if (E2.sh) {
      E2.sh.setAttribute('cx', f(0.4 - lx * 0.1)); E2.sh.setAttribute('fx', f(0.4 - lx * 0.1))
      E2.sh.setAttribute('cy', f(0.3 - ly * 0.06))
    }
    if (E2.scr) this.monitor(t, age, S, red)
    for (let s = 0; s < E2.sparks.length; s++) {
      const sp = SPARKS[s]
      let sc = 0, rot = 0
      if (S.sparks) { const pp = (age * 1.2 + s * 0.29) % 1; sc = red ? 0.8 : Math.sin(pp * Math.PI) * 1.15; rot = pp * 120 }
      E2.sparks[s].setAttribute('transform', `translate(${sp[0]} ${sp[1]}) rotate(${f(rot)}) scale(${f(sc)})`)
    }
  }

  /* 7. Monitor del pecho: cada estado dibuja un gráfico. Verde/rojo/ámbar
        sólo con tono — cuando dice un número con signo. */
  monitor(t, age, S, red) {
    const E2 = this.el, P = this.P
    const col = this.tone ? COLOR_TONO[this.tone] : COLOR_OJO
    if (col !== this._col) {
      this._col = col
      E2.sLine.style.stroke = col; E2.sDot.style.fill = col; E2.sTh.style.stroke = col
      if (E2.sFlood) E2.sFlood.style.floodColor = col
      E2.bars.forEach((b) => { b.style.fill = col })
      E2.cds.forEach((g) => {
        const alcista = g.getAttribute('data-bull') === '1'
        g.firstChild.style.stroke = col
        g.lastChild.style.stroke = col
        g.lastChild.style.fill = alcista ? col : FONDO_VELA_BAJISTA
      })
    }
    E2.scr.setAttribute('opacity', f(0.4 + 0.6 * P.dim))
    const mode = S.scr || 'idle'
    let ld = '', sdx = SX1, sdy = SMID, dop = 1, dr = 1.7, thO = 0, thY = 165
    if (mode === 'idle' || mode === 'gap') {
      const sv = (red ? 0 : t * 1.5) + this.seed, base = Math.floor(sv), fr = sv - base
      let brk = true
      for (let j = 0; j <= SN; j++) {
        const kk = base + j
        if (mode === 'gap' && (kk % 6 === 3 || kk % 6 === 4)) { brk = true; continue }
        ld += (brk ? 'M' : 'L') + f(SX0 + (j - fr) * SDX) + ' ' + f(SMID + nz(kk) * 7)
        brk = false
      }
      const ya = SMID + nz(base + SN - 1) * 7, yb = SMID + nz(base + SN) * 7
      sdy = ya + (yb - ya) * fr
      if (mode === 'gap') {
        const ke = (base + SN - 1) % 6, kn = (base + SN) % 6
        if (ke === 3 || ke === 4 || kn === 3 || kn === 4) dop = 0
      }
    } else if (mode === 'flat') {
      ld = `M${SX0} ${SMID}H${SX1}`
      dop = red ? 0.6 : 0.35 + 0.35 * Math.sin(t * 1.2)
    } else if (SHAPES[mode]) {
      const arr = SHAPES[mode], cyc = red ? 9 : age % 3.4, pr = clamp(cyc / 0.9, 0, 1)
      const sg = pr * (SN - 1), fl = Math.floor(sg), pa = sg - fl
      for (let m = 0; m <= fl && m < SN; m++) ld += (m ? 'L' : 'M') + f(SX0 + m * SDX) + ' ' + f(arr[m])
      if (fl < SN - 1) {
        sdx = SX0 + (fl + pa) * SDX
        sdy = arr[fl] + (arr[fl + 1] - arr[fl]) * pa
        ld += 'L' + f(sdx) + ' ' + f(sdy)
      } else {
        sdx = SX1; sdy = arr[SN - 1]
        if (!red) dr = 1.7 + 0.6 * Math.sin(t * 6)
      }
      if (mode === 'alert') { thO = 0.85; thY = 165 }
      if (mode === 'record') { thO = 0.7; thY = 166.5 }
    } else {
      dop = 0
    }
    E2.sLine.setAttribute('d', ld)
    E2.sDot.setAttribute('cx', f(sdx)); E2.sDot.setAttribute('cy', f(sdy))
    E2.sDot.setAttribute('r', f(dr)); E2.sDot.setAttribute('opacity', f(dop))
    E2.sTh.setAttribute('d', `M82 ${thY}H118`); E2.sTh.setAttribute('opacity', thO)
    for (let bi = 0; bi < E2.bars.length; bi++) {
      let bh = 0, bo = 0
      if (mode === 'talk') {
        const av = clamp(0.14 + P.talk * (0.4 + 0.9 * Math.abs(nz(bi * 3.1 + Math.floor(t * 11)))), 0.14, 1)
        bh = red ? 4 + (bi % 3) * 2 : 1.5 + av * 14
        bo = 1
      } else if (mode === 'load') {
        const lit = red ? -9 : Math.floor(t * 9) % 10
        bh = 3 + bi * 1.7
        bo = (bi === lit || bi === lit - 1) ? 1 : 0.28
      }
      E2.bars[bi].setAttribute('y', f(177 - bh))
      E2.bars[bi].setAttribute('height', f(Math.max(bh, 0.1)))
      E2.bars[bi].setAttribute('opacity', bo)
    }
    const nc = mode === 'think' ? (red ? 6 : Math.min(6, Math.floor((age % 3.2) * 2.4))) : 0
    for (let c = 0; c < E2.cds.length; c++) E2.cds[c].setAttribute('opacity', c < nc ? 1 : 0)
  }
}

/**
 * Crea un Mervall-E dentro de `host` (un elemento vacío).
 * @param {object} opt
 *   forma        'full' | 'bust' | 'head' | 'visor' | 'screen' (si no, sale de size)
 *   size         ancho en px, para elegir la forma
 *   state        uno de ESTADOS
 *   tone         'pos' | 'warn' | 'neg' | null — color del monitor del pecho
 *   still        no flota (al lado de un número)
 *   track        sigue el cursor (default true)
 *   trackRadius  sólo mira si el cursor está a menos de N px
 *   frozen       se dibuja una vez y no se mueve más (avatares viejos del chat)
 *   escucha      pasa a "escuchando" cuando alguien tipea o usa el micrófono
 */
export function crearMervallE(host, opt) {
  return new Personaje(host, opt)
}
