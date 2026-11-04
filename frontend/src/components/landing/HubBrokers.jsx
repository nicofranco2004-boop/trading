// HubBrokers — la animación del héroe de la portada: cada broker le manda su
// información a Rendi y Rendi la junta en una sola cartera.
// ════════════════════════════════════════════════════════════════════════════
// De cada chip (Cocos, IOL, Schwab…) salen puntitos, uno por tenencia, del
// color de su tipo de activo. Al llegar a la tarjeta del centro suman al total,
// la torta se acomoda y el chip queda en verde. Cuando llegaron todos, espera
// y vuelve a empezar.
//
// El JSX dibuja el ESTADO FINAL (todo sumado): es lo que sale en el HTML ya
// escrito para Google y las IA, lo que ve quien pidió «reducir movimiento» y lo
// que queda si el navegador no tiene IntersectionObserver. La animación corre
// en un efecto, tocando el SVG directo (60 cuadros por segundo por estado de
// React redibujaría todo el SVG), y sólo mientras se ve.
//
// Los números son de una cartera de ejemplo y lo dice el pie.

import { useEffect, useRef } from 'react'
import { prefiereSinMovimiento } from '../../utils/movimiento'

// El mismo archivo chico que usa RendiLogo para los tamaños de hasta 32 px.
const LOGO = '/brand/rendi-mark-64.png'

const TIPOS = [
  { k: 'acc', nombre: 'Acciones', clase: 'fill-data-blue stroke-data-blue' },
  { k: 'bon', nombre: 'Bonos', clase: 'fill-data-cyan stroke-data-cyan' },
  { k: 'cri', nombre: 'Cripto', clase: 'fill-data-amber stroke-data-amber' },
  { k: 'efe', nombre: 'Efectivo', clase: 'fill-ink-2 stroke-ink-2' },
]
const CLASE = Object.fromEntries(TIPOS.map(t => [t.k, t.clase]))

// x, y = centro del chip en el lienzo de 560×470. h = lo que manda: [tipo, US$].
const BROKERS = [
  { n: 'Cocos',       m: 'ARS',  x: 96,  y: 46,  h: [['acc', 6200], ['bon', 6120], ['efe', 2662]] },
  { n: 'Bull Market', m: 'ARS',  x: 280, y: 46,  h: [['acc', 1500], ['bon', 900]] },
  { n: 'Schwab',      m: 'USD',  x: 464, y: 46,  h: [['acc', 9200], ['acc', 5000]] },
  { n: 'IOL',         m: 'ARS',  x: 58,  y: 238, h: [['bon', 3100], ['acc', 2400]] },
  { n: 'Binance',     m: 'USDT', x: 502, y: 238, h: [['cri', 8220], ['cri', 2535]] },
  { n: 'Balanz',      m: 'ARS',  x: 96,  y: 430, h: [['efe', 1200], ['bon', 1035]] },
  { n: 'Wise',        m: 'USD',  x: 464, y: 430, h: [['efe', 345]] },
]
const TOTAL = BROKERS.reduce((s, b) => s + b.h.reduce((t, [, v]) => t + v, 0), 0)
const GANANCIA_PCT = 18.6
const POR_TIPO = TIPOS.map(t => BROKERS.reduce((s, b) => s + b.h.filter(([k]) => k === t.k).reduce((u, [, v]) => u + v, 0), 0))
const MONEDAS = new Set(BROKERS.map(b => b.m)).size

const CHIP_W = 116, CHIP_H = 40
const TARJ = { x: 150, y: 138, w: 260, h: 200 }
const TORTA = { cx: 350, cy: 290, r: 30 }
const CIRC = 2 * Math.PI * TORTA.r

// El camino de cada chip hasta el borde de la tarjeta que le queda enfrente.
function ruta(b) {
  const cx = TARJ.x + TARJ.w / 2, cy = TARJ.y + TARJ.h / 2
  const dentro = (x) => Math.max(TARJ.x + 24, Math.min(TARJ.x + TARJ.w - 24, x))
  if (b.y < TARJ.y || b.y > TARJ.y + TARJ.h) {
    const arriba = b.y < TARJ.y
    const sy = arriba ? b.y + CHIP_H / 2 : b.y - CHIP_H / 2
    const ex = dentro(b.x), ey = arriba ? TARJ.y : TARJ.y + TARJ.h
    const my = (sy + ey) / 2
    return `M${b.x} ${sy} C${b.x} ${my} ${ex} ${my} ${ex} ${ey}`
  }
  const izq = b.x < cx
  const sx = izq ? b.x + CHIP_W / 2 : b.x - CHIP_W / 2
  const ex = izq ? TARJ.x : TARJ.x + TARJ.w
  const mx = (sx + ex) / 2
  return `M${sx} ${b.y} C${mx} ${b.y} ${mx} ${cy} ${ex} ${cy}`
}
const RUTAS = BROKERS.map(ruta)

const fmt = (n, d = 0) => n.toLocaleString('es-AR', { minimumFractionDigits: d, maximumFractionDigits: d })
const textoGanancia = (total) =>
  `+US$ ${fmt(Math.round(total * GANANCIA_PCT / (100 + GANANCIA_PCT)))} · +${fmt(GANANCIA_PCT * total / TOTAL, 1)} % en dólares`
const PIE_FINAL = `${BROKERS.length} brokers · ${MONEDAS} monedas · una sola cartera (ejemplo)`

// Los segmentos de la torta para unos montos por tipo.
function segmentos(montos) {
  const tot = montos.reduce((a, b) => a + b, 0) || 1
  let off = 0
  return montos.map(v => {
    const frac = v / tot
    const s = { largo: Math.max(0, frac * CIRC - (frac > 0 ? 2 : 0)), off: -off * CIRC, pct: Math.round(frac * 100) }
    off += frac
    return s
  })
}
const SEG_FINAL = segmentos(POR_TIPO)

export default function HubBrokers() {
  const svg = useRef(null)

  useEffect(() => {
    const raiz = svg.current
    if (!raiz || prefiereSinMovimiento() || typeof IntersectionObserver === 'undefined') return undefined
    const $ = (sel) => raiz.querySelector(sel)
    const $$ = (sel) => [...raiz.querySelectorAll(sel)]
    const tot = $('[data-total]'), gan = $('[data-ganancia]'), pie = $('[data-pie]'), anillo = $('[data-anillo]')
    const capaDatos = $('[data-datos]')
    const chips = $$('[data-chip]'), rutas = $$('[data-ruta]'), segs = $$('[data-seg]'), pcts = $$('[data-pct]')
    const largos = rutas.map(r => r.getTotalLength())

    const relojes = new Set(), cuadros = new Set()
    const despues = (fn, ms) => { const t = setTimeout(() => { relojes.delete(t); fn() }, ms); relojes.add(t) }
    const cuadro = (fn) => { const c = requestAnimationFrame((t) => { cuadros.delete(c); fn(t) }); cuadros.add(c) }

    let visible = false, esperando = true, acum = [0, 0, 0, 0], mostrado = 0, objetivo = 0

    const pintaTorta = () => {
      segmentos(acum).forEach((s, i) => {
        segs[i].setAttribute('stroke-dasharray', `${s.largo} ${CIRC}`)
        segs[i].setAttribute('stroke-dashoffset', s.off)
        pcts[i].textContent = `${s.pct} %`
      })
    }
    const pintaTotal = () => {
      tot.textContent = `US$ ${fmt(Math.round(mostrado))}`
      gan.textContent = mostrado > 0 ? textoGanancia(mostrado) : 'esperando a tus brokers…'
    }
    const cuenta = () => {
      if (mostrado < objetivo) {
        mostrado = Math.min(objetivo, mostrado + Math.max(40, (objetivo - mostrado) * 0.12))
        pintaTotal()
      }
      if (mostrado < objetivo) cuadro(cuenta)
    }
    const pulso = () => anillo.animate?.(
      [{ opacity: 0.9, transform: 'scale(1)' }, { opacity: 0, transform: 'scale(1.06)' }],
      { duration: 650, easing: 'ease-out' })

    const ciclo = () => {
      esperando = false
      acum = [0, 0, 0, 0]; mostrado = objetivo = 0
      pintaTotal(); pintaTorta(); pie.textContent = ''
      chips.forEach(c => { c.dataset.estado = '' })
      let pendientes = BROKERS.reduce((s, b) => s + b.h.length, 0)
      BROKERS.forEach((b, i) => b.h.forEach(([k, v], j) => {
        despues(() => {
          chips[i].dataset.estado = 'manda'
          const punto = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
          punto.setAttribute('r', 5); punto.setAttribute('class', CLASE[k])
          const halo = punto.cloneNode(); halo.setAttribute('r', 10); halo.setAttribute('opacity', 0.18)
          capaDatos.append(halo, punto)
          const ini = performance.now()
          const paso = (ahora) => {
            const f = Math.min(1, (ahora - ini) / 1250)
            const e = f < 0.5 ? 2 * f * f : 1 - (-2 * f + 2) ** 2 / 2
            const p = rutas[i].getPointAtLength(e * largos[i])
            for (const n of [punto, halo]) { n.setAttribute('cx', p.x); n.setAttribute('cy', p.y) }
            if (f < 1) return cuadro(paso)
            punto.remove(); halo.remove()
            acum[TIPOS.findIndex(t => t.k === k)] += v
            objetivo += v; pintaTorta(); pulso(); cuadro(cuenta)
            if (j === b.h.length - 1) chips[i].dataset.estado = 'listo'
            if (--pendientes === 0) {
              pie.textContent = PIE_FINAL
              despues(() => { if (visible) ciclo(); else esperando = true }, 4200)
            }
            return undefined
          }
          cuadro(paso)
        }, 400 + i * 380 + j * 260)
      }))
    }

    const ojo = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting
      if (visible && esperando) ciclo()
    }, { threshold: 0.3 })
    ojo.observe(raiz)
    return () => {
      ojo.disconnect()
      relojes.forEach(clearTimeout); cuadros.forEach(cancelAnimationFrame)
      capaDatos.replaceChildren()
    }
  }, [])

  return (
    <div className="relative w-full max-w-[600px] justify-self-center">
      <svg ref={svg} viewBox="0 0 560 470" className="block w-full h-auto overflow-visible" role="img"
           aria-label="Cada broker le manda su información a Rendi, que la junta en una sola cartera">
        <g>
          {RUTAS.map((d, i) => (
            <path key={i} data-ruta="" d={d} fill="none" strokeWidth="1.5" strokeDasharray="3 5"
                  className="stroke-line-3 transition-colors" />
          ))}
        </g>
        <g data-datos="" />
        <rect x={TARJ.x} y={TARJ.y} width={TARJ.w} height={TARJ.h} rx="16" className="fill-bg-1 stroke-line-2" />
        <rect data-anillo="" x={TARJ.x} y={TARJ.y} width={TARJ.w} height={TARJ.h} rx="16" fill="none" strokeWidth="2"
              className="stroke-data-violet opacity-0" style={{ transformOrigin: '280px 238px', transformBox: 'view-box' }} />
        <image href={LOGO} x="168" y="154" width="22" height="22" />
        <text x="198" y="170" className="fill-ink-2 text-[12px] font-medium">Tu cartera, todo junto</text>
        <text data-total="" x="168" y="214" className="fill-ink-0 text-[31px] font-semibold tabular" letterSpacing="-0.9">
          US$ {fmt(TOTAL)}
        </text>
        <text data-ganancia="" x="168" y="236" className="fill-rendi-pos text-[12.5px] font-medium tabular">
          {textoGanancia(TOTAL)}
        </text>
        {TIPOS.map((t, i) => (
          <g key={t.k}>
            <circle cx="172" cy={264 + i * 19} r="4" className={t.clase} />
            <text x="182" y={268 + i * 19} className="fill-ink-1 text-[12px] font-medium">{t.nombre}</text>
            <text data-pct="" x="300" y={268 + i * 19} textAnchor="end" className="fill-ink-2 text-[12px] tabular">
              {SEG_FINAL[i].pct} %
            </text>
          </g>
        ))}
        <circle cx={TORTA.cx} cy={TORTA.cy} r={TORTA.r} fill="none" strokeWidth="11" className="stroke-bg-3" />
        <g transform={`rotate(-90 ${TORTA.cx} ${TORTA.cy})`}>
          {TIPOS.map((t, i) => (
            <circle key={t.k} data-seg="" cx={TORTA.cx} cy={TORTA.cy} r={TORTA.r} fill="none" strokeWidth="11"
                    className={t.clase.split(' ')[1]}
                    strokeDasharray={`${SEG_FINAL[i].largo} ${CIRC}`} strokeDashoffset={SEG_FINAL[i].off}
                    style={{ transition: 'stroke-dasharray .5s ease, stroke-dashoffset .5s ease' }} />
          ))}
        </g>
        <text data-pie="" x="280" y="362" textAnchor="middle" className="fill-ink-3 text-[11px] font-medium">{PIE_FINAL}</text>
        {BROKERS.map((b) => (
          <g key={b.n} data-chip="" data-estado="listo" transform={`translate(${b.x - CHIP_W / 2} ${b.y - CHIP_H / 2})`}
             className="group/chip">
            <rect width={CHIP_W} height={CHIP_H} rx="10"
                  className="fill-bg-1 stroke-line-2 transition-colors group-data-[estado=manda]/chip:stroke-data-violet" />
            <text x="12" y="18" className="fill-ink-0 text-[14px] font-semibold">{b.n}</text>
            <text x="12" y="31" className="fill-ink-3 text-[10px] font-medium">{b.m}</text>
            <circle cx={CHIP_W - 14} cy={CHIP_H / 2} r="5"
                    className="fill-rendi-pos opacity-0 transition-opacity group-data-[estado=listo]/chip:opacity-100" />
          </g>
        ))}
      </svg>
    </div>
  )
}
