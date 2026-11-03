// PantallasModulos — las seis mini-pantallas del recorrido «Todo lo que hace
// Rendi» de la portada (las cambia RecorridoModulos).
// ════════════════════════════════════════════════════════════════════════════
// Cada una muestra un módulo real de la app con una cartera de EJEMPLO (la
// ventana que las envuelve dice «Ejemplo»). Lo que prometen tiene que existir
// adentro: el perfil «coincide en N de 8» es el de Perfil de inversor, las
// etiquetas Sólido / En precio son las de Análisis fundamental
// (components/fundamentals/axes.js), los cupos de Mervall-E salen del
// catálogo. Si un módulo cambia, se cambia acá.
//
// Las animaciones son de entrada (clases `lp-*` de index.css): cada pantalla se
// monta de nuevo al elegirla (key en RecorridoModulos) y sus barras vuelven a
// crecer. Sin animación quedan completas.

import { useEffect, useState } from 'react'
import MervallE from '../ai/MervallE'
import { PLUS_FEATURES, PRO_FEATURES, CUPO_CHAT } from '../../data/planCatalog'
import { cupoDe } from '../../data/prueba'
import { prefiereSinMovimiento } from '../../utils/movimiento'

const fmt = (n, d = 0) => n.toLocaleString('es-AR', { minimumFractionDigits: d, maximumFractionDigits: d })
const conSigno = (n, d = 1) => `${n >= 0 ? '+' : '−'}${fmt(Math.abs(n), d)} %`
const demora = (s) => ({ '--d': `${s}s` })

function Caja({ titulo, extra, children, className = '' }) {
  return (
    <div className={`border border-line rounded-xl p-3.5 min-w-0 ${className}`}>
      {titulo && (
        <div className="flex justify-between gap-2 mb-2.5 text-[13px] text-ink-2 font-medium">
          <span>{titulo}</span>{extra && <span>{extra}</span>}
        </div>
      )}
      {children}
    </div>
  )
}

function Kpi({ rotulo, children, sub, subClase = 'text-ink-3' }) {
  return (
    <div className="border border-line rounded-xl px-3.5 py-3 bg-bg-2/40 min-w-0">
      <div className="text-[12.5px] text-ink-2 mb-1">{rotulo}</div>
      <div className="font-semibold tracking-tight tabular whitespace-nowrap text-[clamp(18px,2.2vw,25px)]">{children}</div>
      <div className={`text-xs mt-0.5 truncate ${subClase}`}>{sub}</div>
    </div>
  )
}

function Pill({ tono, children }) {
  const c = tono === 'bien' ? 'text-rendi-pos bg-rendi-pos/10' : 'text-rendi-warn bg-rendi-warn/15'
  return <span className={`text-[11.5px] font-medium px-2 py-0.5 rounded-full whitespace-nowrap ${c}`}>{children}</span>
}

// ─── Tu cartera ──────────────────────────────────────────────────────────────

const APORTADO = 42510
const SERIE = [31.2, 32.0, 31.4, 33.8, 35.1, 34.2, 37.9, 39.5, 38.1, 42.6, 45.8, 50.4]
const POR_BROKER = [
  { n: 'Schwab', m: 'USD', v: 14200, p: 23.5 },
  { n: 'Cocos', m: 'ARS', v: 14982, p: 14.4 },
  { n: 'Binance', m: 'USDT', v: 10755, p: 21.7 },
  { n: 'IOL', m: 'ARS', v: 5500, p: 9.8 },
  { n: 'Balanz', m: 'ARS', v: 2235, p: -2.1 },
]

function Cartera({ activa }) {
  // El total «respira» como en vivo: se mueve unos dólares cada 1,8 s.
  const [total, setTotal] = useState(50417)
  const [subio, setSubio] = useState(null)
  useEffect(() => {
    if (!activa || prefiereSinMovimiento()) return undefined
    const t = setInterval(() => {
      const delta = Math.round((Math.random() - 0.35) * 60)
      setTotal(prev => prev + delta)
      setSubio(delta >= 0)
    }, 1800)
    return () => clearInterval(t)
  }, [activa])
  const destello = subio ? 'flash-up' : ''
  const X = (i) => 8 + i * (384 / 11), Y = (v) => 150 - (v - 28) / 24 * 135
  const linea = SERIE.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(' ')
  const max = Math.max(...POR_BROKER.map(b => b.v))
  return (
    <div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 mb-3.5">
        <div className="col-span-2 sm:col-span-1 min-w-0">
          <Kpi rotulo="Tu cartera hoy" sub="todos tus brokers, en dólares">
            <span key={total} className={destello}>US$ {fmt(total)}</span>
          </Kpi>
        </div>
        <Kpi rotulo="Lo que pusiste" sub="depósitos menos retiros">US$ {fmt(APORTADO)}</Kpi>
        <Kpi rotulo="Ganancia en dólares" sub={`${conSigno((total - APORTADO) / APORTADO * 100)} en total`} subClase="text-rendi-pos">
          <span key={total} className={`text-rendi-pos ${destello}`}>+US$ {fmt(total - APORTADO)}</span>
        </Kpi>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-[1.25fr_1fr] gap-3.5">
        <Caja titulo="Valor de tu cartera, en dólares" extra="12 meses">
          <svg viewBox="0 0 400 170" className="block w-full h-auto">
            {[30, 40, 50].map(v => (
              <g key={v}>
                <line x1="0" x2="400" y1={Y(v)} y2={Y(v)} className="stroke-line" />
                <text x="398" y={Y(v) - 4} textAnchor="end" className="fill-ink-3 text-[10.5px] tabular">{v}k</text>
              </g>
            ))}
            <path d={`${linea} L${X(11)} 150 L${X(0)} 150 Z`} className="fill-rendi-pos-fill/10 lp-entra" style={demora(0.6)} />
            <path d={linea} fill="none" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
                  className="stroke-rendi-pos-fill lp-traza" style={{ '--L': 1000 }} />
            <circle cx={X(11)} cy={Y(SERIE[11])} r="4" className="fill-rendi-pos-fill lp-entra" style={demora(1.2)} />
            {['nov', 'ene', 'mar', 'may', 'jul', 'sep'].map((m, k) => (
              <text key={m} x={X(k * 2)} y="166" textAnchor="middle" className="fill-ink-3 text-[10.5px]">{m}</text>
            ))}
          </svg>
        </Caja>
        <Caja titulo="Por broker" extra="ganancia en USD">
          {POR_BROKER.map((b, i) => (
            <div key={b.n} className="grid grid-cols-[78px_minmax(0,1fr)_auto] gap-2.5 items-center py-1.5 border-b border-line/70 last:border-0 text-[13.5px]">
              <span className="font-semibold">{b.n}<small className="block font-mono text-[10.5px] font-medium text-ink-3">{b.m}</small></span>
              <span className="h-1.5 rounded-full bg-bg-3 overflow-hidden">
                <i className="block h-full rounded-full bg-data-blue lp-crece" style={{ width: `${Math.round(b.v / max * 100)}%`, ...demora(i * 0.1) }} />
              </span>
              <span className="text-right whitespace-nowrap tabular">
                US$ {fmt(b.v)}
                <small className={`block text-xs ${b.p >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{conSigno(b.p)}</small>
              </span>
            </div>
          ))}
        </Caja>
      </div>
    </div>
  )
}

// ─── Salud de cartera ────────────────────────────────────────────────────────

const POR_TIPO = [
  { n: 'Acciones y CEDEARs', pct: 48, c: 'stroke-data-blue', p: 'bg-data-blue' },
  { n: 'Bonos', pct: 22, c: 'stroke-data-cyan', p: 'bg-data-cyan' },
  { n: 'Cripto', pct: 21, c: 'stroke-data-amber', p: 'bg-data-amber' },
  { n: 'Efectivo', pct: 9, c: 'stroke-ink-2', p: 'bg-ink-2' },
]
const INDICADORES = [
  { n: 'Concentración', s: 'NVDA, BTC y AL30 suman', v: '41 %', t: 'mirar', e: 'Mirar' },
  { n: 'Retorno por riesgo (Sharpe)', s: 'cuánto ganás por cada susto', v: '1,34', t: 'bien', e: 'Bien' },
  { n: 'Peor caída', s: 'de máximo a mínimo', v: '−14,2 %', cv: 'text-rendi-neg', t: 'bien', e: 'Normal' },
  { n: 'Contra el S&P 500 (alfa)', s: 'lo que le ganás al mercado', v: '+3,1 %', cv: 'text-rendi-pos', t: 'bien', e: 'Bien' },
  { n: 'Volatilidad', s: 'cuánto se mueve por año', v: '18 %', t: 'bien', e: 'Normal' },
  { n: 'Operar de más', s: 'vendiste y recompraste 6 veces', v: '6', t: 'mirar', e: 'Mirar' },
]

function Salud() {
  const R = 34, C = 2 * Math.PI * R
  let acum = 0
  return (
    <div className="grid grid-cols-1 md:grid-cols-[0.9fr_1.1fr] gap-3.5">
      <div className="flex flex-col gap-3.5 min-w-0">
        <Caja titulo="Tu perfil contra tu cartera">
          <p className="text-[14px] text-ink-1 leading-relaxed">
            Dijiste que sos <b className="font-semibold text-ink-0">moderado</b>. Tu cartera hoy se comporta como la de
            alguien <b className="font-semibold text-ink-0">agresivo</b>.
          </p>
          <div className="flex items-center gap-1.5 mt-3" aria-label="Coincide con tu perfil en 5 de 8">
            {Array.from({ length: 8 }, (_, i) => (
              <span key={i} className={`h-2 flex-1 rounded-full lp-entra ${i < 5 ? 'bg-rendi-pos-fill' : 'bg-bg-3'}`} style={demora(0.2 + i * 0.08)} />
            ))}
          </div>
          <p className="text-xs text-ink-2 mt-1.5 tabular">Coincide con tu perfil en 5 de 8</p>
        </Caja>
        <Caja titulo="Por tipo de activo">
          <div className="flex items-center gap-4">
            <svg viewBox="0 0 90 90" className="w-[88px] h-[88px] shrink-0 -rotate-90 lp-entra">
              <circle cx="45" cy="45" r={R} fill="none" strokeWidth="12" className="stroke-bg-3" />
              {POR_TIPO.map(t => {
                const off = acum; acum += t.pct / 100
                return <circle key={t.n} cx="45" cy="45" r={R} fill="none" strokeWidth="12" className={t.c}
                               strokeDasharray={`${t.pct / 100 * C - 2} ${C}`} strokeDashoffset={-off * C} />
              })}
            </svg>
            <ul className="grid gap-1 text-[12.5px] min-w-0 flex-1">
              {POR_TIPO.map(t => (
                <li key={t.n} className="flex items-center gap-2 min-w-0">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${t.p}`} />
                  <span className="text-ink-1 truncate">{t.n}</span>
                  <span className="ml-auto text-ink-2 tabular">{t.pct} %</span>
                </li>
              ))}
            </ul>
          </div>
        </Caja>
      </div>
      <Caja titulo="Lo que mira Rendi" extra="estado">
        {INDICADORES.map((x, i) => (
          <div key={x.n} className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-2.5 items-center py-2.5 border-b border-line/70 last:border-0 text-[14px] lp-entra" style={demora(0.3 + i * 0.14)}>
            <div className="min-w-0">{x.n}<small className="block text-xs text-ink-3">{x.s}</small></div>
            <span className={`font-semibold tabular ${x.cv || ''}`}>{x.v}</span>
            <Pill tono={x.t}>{x.e}</Pill>
          </div>
        ))}
      </Caja>
    </div>
  )
}

// ─── Análisis técnico ────────────────────────────────────────────────────────

// 60 velas de ejemplo, siempre las mismas (generador con semilla): bajan, se
// acomodan y arrancan para arriba, cruzando su media.
const VELAS = (() => {
  let s = 7
  const azar = () => (s = (s * 16807) % 2147483647) / 2147483647
  const out = []
  let p = 150
  for (let i = 0; i < 60; i++) {
    const tendencia = i < 22 ? -0.35 : i < 34 ? 0.15 : 0.95
    const o = p, c = o + tendencia + (azar() - 0.5) * 5.2
    out.push({ o, c, h: Math.max(o, c) + azar() * 2.6, l: Math.min(o, c) - azar() * 2.6 })
    p = c
  }
  return out
})()
const MEDIA = VELAS.map((_, i) => {
  const tramo = VELAS.slice(Math.max(0, i - 9), i + 1)
  return tramo.reduce((s, v) => s + v.c, 0) / tramo.length
})
const PISO = Math.min(...VELAS.map(v => v.l)) - 3
const TECHO = Math.max(...VELAS.map(v => v.h)) + 6
const ALERTA = Math.ceil(TECHO - 4)
const ULTIMA = VELAS[VELAS.length - 1]
const VAR_DIA = (ULTIMA.c / VELAS[VELAS.length - 2].c - 1) * 100
const FIN_VELAS = 0.3 + VELAS.length * 0.028

function Tecnico() {
  const X = (i) => 10 + i * 9.6, Y = (v) => 262 - (v - PISO) / (TECHO - PISO) * 250
  const media = MEDIA.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(' ')
  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-3.5 gap-y-2 mb-3">
        <span className="font-mono font-semibold text-lg">NVDA</span>
        <span className="text-lg font-semibold tabular">US$ {fmt(ULTIMA.c, 2)}</span>
        <span className={`text-sm tabular ${VAR_DIA >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{conSigno(VAR_DIA)} hoy</span>
        <span className="ml-auto inline-flex border border-line-2 rounded-lg overflow-hidden text-[12.5px]">
          {['1H', '4H', '1D', '1S'].map(t => (
            <span key={t} className={`px-2.5 py-1 ${t === '1D' ? 'bg-bg-3 text-ink-0' : 'text-ink-2'}`}>{t}</span>
          ))}
        </span>
      </div>
      <div className="relative border border-line rounded-xl px-2 pt-2 pb-1">
        <svg viewBox="0 0 640 280" className="block w-full h-auto">
          {[0, 1, 2, 3, 4].map(k => {
            const v = PISO + (TECHO - PISO) * k / 4
            return (
              <g key={k}>
                <line x1="0" x2="590" y1={Y(v)} y2={Y(v)} className="stroke-line" />
                <text x="636" y={Y(v) + 4} textAnchor="end" className="fill-ink-3 text-[10.5px] tabular">{fmt(v)}</text>
              </g>
            )
          })}
          {VELAS.map((v, i) => {
            const sube = v.c >= v.o
            return (
              <g key={i} className={`lp-entra ${sube ? 'fill-rendi-pos-fill stroke-rendi-pos-fill' : 'fill-rendi-neg-fill stroke-rendi-neg-fill'}`}
                 style={demora(0.3 + i * 0.028)}>
                <line x1={X(i)} x2={X(i)} y1={Y(v.h)} y2={Y(v.l)} strokeWidth="1.2" />
                <rect x={X(i) - 3.3} y={Y(Math.max(v.o, v.c))} width="6.6" height={Math.max(1.2, Math.abs(Y(v.o) - Y(v.c)))} rx="1" />
              </g>
            )
          })}
          <path d={media} fill="none" strokeWidth="1.8" className="stroke-rendi-accent lp-traza" style={{ '--L': 2000, ...demora(FIN_VELAS) }} />
          <line x1="0" x2="590" y1={Y(ALERTA)} y2={Y(ALERTA)} strokeDasharray="5 4" strokeWidth="1.2"
                className="stroke-rendi-warn lp-entra" style={demora(FIN_VELAS + 0.9)} />
        </svg>
        <div className="absolute left-3.5 top-3.5 flex items-center gap-2 text-[12.5px] px-3 py-1.5 rounded-lg bg-bg-1 border border-line-2 lp-sombra-cartel lp-entra" style={demora(FIN_VELAS + 1.5)}>
          <span className="w-2 h-2 rounded-full bg-rendi-pos shrink-0" />Señal: cruzó arriba de su media
        </div>
        <div className="hidden sm:flex absolute right-14 top-[38%] items-center gap-2 text-[12.5px] px-3 py-1.5 rounded-lg bg-bg-1 border border-line-2 lp-sombra-cartel lp-entra tabular" style={demora(FIN_VELAS + 0.9)}>
          <span className="w-2 h-2 rounded-full bg-rendi-warn shrink-0" />Tu alerta en US$ {fmt(ALERTA)}
        </div>
      </div>
      <div className="flex flex-wrap gap-2 mt-3">
        {['Tendencia de largo plazo: alcista', 'Impulso (RSI): 64', 'Ondas de Elliott y Fibonacci', 'Señales de la semana', 'Alertas cuando toca tu línea'].map(t => (
          <span key={t} className="text-[12.5px] border border-line rounded-full px-2.5 py-1 text-ink-1">{t}</span>
        ))}
      </div>
    </div>
  )
}

// ─── Análisis fundamental ────────────────────────────────────────────────────

// [métrica, aclaración, KO, PEP, quién gana, tope de la barra, ¿en %?]
const FUNDAMENTOS = [
  ['Precio / ganancias', '¿cara o barata?', 24.1, 21.3, 'b', 30, false],
  ['Margen neto', 'de cada US$ 100 que vende', 22.9, 10.2, 'a', 25, true],
  ['Crecimiento de ventas', 'último año', 3.1, 1.8, 'a', 5, true],
  ['Deuda / patrimonio', 'cuánto debe', 1.6, 2.5, 'a', 3, false],
  ['Dividendo', 'por año', 2.9, 3.6, 'b', 4, true],
]

function Fundamental() {
  const num = (v, pct, gana) => (
    <span className={`font-semibold whitespace-nowrap tabular ${gana ? 'text-ink-0' : 'text-ink-2'}`}>
      {fmt(v, 1)}{pct ? ' %' : ''}{gana && <span className="text-rendi-pos text-[9px] align-[2px]"> ●</span>}
    </span>
  )
  return (
    <div>
      <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] gap-2.5 items-center mb-3.5">
        <div className="border border-line rounded-xl px-3 py-2.5 min-w-0">
          <span className="font-mono font-semibold text-data-blue">KO</span>
          <small className="block text-xs text-ink-3 truncate">Coca-Cola · Sólido</small>
        </div>
        <span className="text-xs text-ink-3">contra</span>
        <div className="border border-line rounded-xl px-3 py-2.5 min-w-0 text-right">
          <span className="font-mono font-semibold text-data-cyan">PEP</span>
          <small className="block text-xs text-ink-3 truncate">PepsiCo · En precio</small>
        </div>
      </div>
      {FUNDAMENTOS.map(([n, s, a, b, gana, tope, pct], i) => (
        <div key={n} className="grid grid-cols-[minmax(0,1fr)_92px_minmax(0,1fr)] sm:grid-cols-[minmax(0,1fr)_140px_minmax(0,1fr)] gap-2.5 items-center py-2 border-b border-line/70 last:border-0 text-[13px] sm:text-[13.5px]">
          <div className="flex flex-row-reverse items-center gap-2 min-w-0">
            <span className="h-2 rounded-full bg-data-blue lp-crece-der" style={{ width: `${a / tope * 100}%`, ...demora(0.2 + i * 0.12) }} />
            {num(a, pct, gana === 'a')}
          </div>
          <div className="text-center text-ink-2 text-[12.5px] leading-tight">{n}<br /><span className="text-ink-3 text-[11.5px]">{s}</span></div>
          <div className="flex items-center gap-2 min-w-0">
            {num(b, pct, gana === 'b')}
            <span className="h-2 rounded-full bg-data-cyan lp-crece" style={{ width: `${b / tope * 100}%`, ...demora(0.2 + i * 0.12) }} />
          </div>
        </div>
      ))}
      <div className="flex flex-wrap gap-2 mt-3.5">
        {['Más barata hoy: PEP', 'Más rentable: KO', 'Menos deuda: KO', 'Las dos en el mismo gráfico'].map(t => (
          <span key={t} className="text-[12.5px] rounded-full px-2.5 py-1 bg-bg-2 border border-line text-ink-1">{t}</span>
        ))}
      </div>
    </div>
  )
}

// ─── Mervall-E AI ────────────────────────────────────────────────────────────

// La respuesta en tramos, para pintar de rojo y verde los números mientras se
// escribe.
const RESPUESTA = [
  ['Tu cartera bajó '], ['−2,1 %', 'text-rendi-neg'], [' esta semana ('], ['−US$ 1.012', 'text-rendi-neg'],
  ['). Casi todo lo explica NVDA: cayó 8 % después del balance y es tu posición más grande. Los bonos AL30 compensaron una parte. Sin NVDA, tu semana habría dado '],
  ['+0,4 %', 'text-rendi-pos'], ['.'],
]
const LARGO = RESPUESTA.reduce((s, [t]) => s + t.length, 0)
const APORTES = [
  { tk: 'NVDA', v: -710, desde: 8, hasta: 50 },
  { tk: 'MELI', v: -302, desde: 36, hasta: 50 },
  { tk: 'AL30', v: 288, desde: 50, hasta: 70 },
]

function Mervalle({ activa }) {
  // Escondida (o en el HTML ya escrito) la respuesta está entera: sólo se
  // escribe en vivo la que se está mirando.
  const escribe = activa && !prefiereSinMovimiento()
  const [letras, setLetras] = useState(escribe ? -1 : LARGO)
  // Piensa 1,1 s (los tres puntitos) y escribe de a dos letras.
  useEffect(() => {
    if (!escribe) return undefined
    let cada
    const piensa = setTimeout(() => {
      cada = setInterval(() => setLetras(n => Math.min(LARGO, Math.max(0, n) + 2)), 22)
    }, 1100)
    const termina = setTimeout(() => clearInterval(cada), 1100 + Math.ceil(LARGO / 2) * 22 + 200)
    return () => { clearTimeout(piensa); clearTimeout(termina); clearInterval(cada) }
  }, [escribe])
  const plus = cupoDe(PLUS_FEATURES, CUPO_CHAT)
  const pro = cupoDe(PRO_FEATURES, CUPO_CHAT)

  let resto = Math.max(0, letras)
  const tramos = RESPUESTA.map(([t, c], i) => {
    const visible = t.slice(0, resto); resto -= visible.length
    return visible && <span key={i} className={c}>{visible}</span>
  })
  const listo = letras >= LARGO
  return (
    <div className="flex flex-col gap-3 max-w-2xl mx-auto">
      <div className="self-end max-w-[86%] rounded-xl px-3.5 py-2.5 text-[14.5px] bg-data-violet/15 border border-data-violet/30 lp-entra" style={demora(0.2)}>
        ¿Por qué bajó mi cartera esta semana?
      </div>
      <div className="self-start max-w-[92%] rounded-xl px-3.5 py-2.5 text-[14.5px] leading-normal bg-bg-2/70 border border-line min-h-[52px]">
        <div className="flex items-center gap-2 text-[12.5px] text-ink-2 mb-1.5">
          <MervallE size={20} forma="visor" congelado />Mervall-E AI · mira tu cartera
        </div>
        {letras < 0
          ? <span className="inline-flex gap-1" aria-label="Escribiendo">{[0, 1, 2].map(i => <span key={i} className="w-1.5 h-1.5 rounded-full bg-ink-3 lp-salta" style={{ animationDelay: `${i * 0.15}s` }} />)}</span>
          : <p>{tramos}{!listo && <span className="terminal-cursor inline-block w-[7px] h-[15px] bg-ink-1 align-[-2px] ml-0.5" />}</p>}
        {listo && (
          <div className="grid gap-1.5 mt-2.5">
            {APORTES.map((a, i) => (
              <div key={a.tk} className="grid grid-cols-[52px_minmax(0,1fr)_62px] gap-2 items-center text-[12.5px] lp-entra" style={demora(i * 0.1)}>
                <span className="font-mono text-xs">{a.tk}</span>
                <span className="relative h-1.5 rounded-full bg-bg-3 overflow-hidden">
                  <i className={`absolute inset-y-0 rounded-full ${a.v < 0 ? 'bg-rendi-neg-fill lp-crece-der' : 'bg-rendi-pos-fill lp-crece'}`}
                     style={{ left: `${a.desde}%`, right: `${100 - a.hasta}%`, ...demora(0.15 + i * 0.1) }} />
                </span>
                <span className={`text-right font-semibold tabular ${a.v < 0 ? 'text-rendi-neg' : 'text-rendi-pos'}`}>
                  {a.v < 0 ? '−' : '+'}US$ {fmt(Math.abs(a.v))}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
      <p className="text-[12.5px] text-ink-2 text-center leading-relaxed">
        En todos los planes, Mervall-E AI responde 12 preguntas guiadas ({plus} consultas por semana en Plus).
        Con Pro, le preguntás lo que quieras.
      </p>
      <div className="flex flex-wrap gap-1.5 justify-center">
        {[`12 guiadas · ${plus}/sem (Plus)`, `Chat libre · ${pro}/sem (Pro)`, 'Memoria persistente'].map(t => (
          <span key={t} className="text-[12.5px] border border-line-2 rounded-full px-2.5 py-1 text-ink-1 tabular">{t}</span>
        ))}
      </div>
    </div>
  )
}

// ─── Reportes ────────────────────────────────────────────────────────────────

const CONTRA = [
  { n: 'Tu cartera', v: 3.8, w: 59, tuya: true },
  { n: 'Merval (USD)', v: 5.2, w: 81, ref: true },
  { n: 'S&P 500', v: 2.1, w: 33, ref: true },
  { n: 'Inflación', v: 2.3, w: 36 },
  { n: 'Plazo fijo', v: 1.9, w: 30 },
]
const ANIO = [2.1, -1.4, 3.3, 0.8, -2.6, 4.1, 1.2, -0.7, 2.9, 3.8, null, null]
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

function Reportes() {
  return (
    <div>
      <div className="flex flex-wrap items-end gap-x-5 gap-y-1.5 mb-5">
        <div>
          <div className="text-[13px] text-ink-2">Tu octubre, en dólares</div>
          <div className="font-semibold tracking-tight leading-none text-rendi-pos tabular text-[clamp(34px,4.6vw,50px)]">
            +3,8 %<small className="text-sm font-medium text-ink-2 tracking-normal ml-1.5">+US$ 1.842</small>
          </div>
        </div>
        <p className="text-[14px] text-ink-1 max-w-[30em]">
          Le ganaste al S&amp;P 500, a la inflación y al plazo fijo. El Merval en dólares hizo más: tu parte argentina es chica.
        </p>
      </div>
      <div className="grid gap-2.5">
        {CONTRA.map((c, i) => (
          <div key={c.n} className="grid grid-cols-[92px_minmax(0,1fr)_54px] sm:grid-cols-[120px_minmax(0,1fr)_62px] gap-3 items-center text-[13px] sm:text-[14px]">
            <span className={c.tuya ? 'font-semibold text-ink-0' : 'text-ink-1'}>{c.n}</span>
            <span className="h-3.5 rounded bg-bg-2 overflow-hidden">
              <i className={`block h-full rounded lp-crece ${c.tuya ? 'bg-rendi-pos-fill' : c.ref ? 'bg-rendi-accent/70' : 'bg-ink-3'}`}
                 style={{ width: `${c.w}%`, ...demora(0.2 + i * 0.15) }} />
            </span>
            <span className={`text-right font-semibold tabular ${c.tuya ? 'text-rendi-pos' : ''}`}>{conSigno(c.v)}</span>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-6 sm:grid-cols-12 gap-1 mt-5">
        {ANIO.map((v, i) => (
          <div key={MESES[i]} title={MESES[i]}
               className={`aspect-[1.5] rounded flex items-center justify-center text-[10.5px] tabular lp-entra ${
                 v == null ? 'bg-bg-2 text-ink-3' : v >= 0 ? 'bg-rendi-pos-fill text-ink-0' : 'bg-rendi-neg-fill text-ink-0'}`}
               style={{ ...demora(0.6 + i * 0.05), ...(v == null ? {} : { '--tw-bg-opacity': Math.min(0.85, 0.2 + Math.abs(v) / 5).toFixed(2) }) }}>
            {v == null ? MESES[i] : `${v >= 0 ? '+' : '−'}${fmt(Math.abs(v), 1)}`}
          </div>
        ))}
      </div>
    </div>
  )
}

export const PANTALLAS = { cartera: Cartera, salud: Salud, tecnico: Tecnico, fundamental: Fundamental, ia: Mervalle, reportes: Reportes }
