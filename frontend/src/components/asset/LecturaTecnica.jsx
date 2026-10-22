// LecturaTecnica — el gráfico técnico y su lectura en la ficha del activo.
// ════════════════════════════════════════════════════════════════════════════
// Gráfico de precio con las medias de 50 y 200 días, tu precio promedio y tus
// compras y ventas; la fuerza del movimiento (RSI) abajo; y cuatro tarjetas en
// castellano. Se mide en DÓLARES por defecto: un CEDEAR en pesos sube con el
// dólar aunque la empresa no se mueva (ver backend/tecnico.py).
//
// Los números vienen de GET /api/tecnico (las velas que se guardan de noche).
// Si el activo todavía no tiene velas (recién agregado, o un bono/fondo), se
// muestra el gráfico de 30 días de siempre (`AssetMiniChart`).
//
// Una sola vista para compu y celular (R6): el gráfico es `width: 100%` y las
// tarjetas se acomodan en la grilla.

import { useEffect, useMemo, useRef, useState } from 'react'
import AssetMiniChart from '../home/AssetMiniChart'
import { api } from '../../utils/api'
import {
  RANGOS, RSI_CASTIGADO, RSI_ESTIRADO, recortar, tarjetas, lineaPromedio, marcas,
  indiceDeFecha, tendenciasDistintas,
} from '../../utils/tecnico'

const v = (t) => `rgb(var(--${t}))`
const COLOR = {
  precio: v('ink-0'),
  media200: v('rendi-accent'),
  media50: v('data-cyan'),
  promedio: v('ink-2'),
}
const W = 1000
const H = 260
const H_RSI = 64

function fmtPrecio(x, moneda) {
  if (x == null) return '—'
  const dec = x >= 1000 ? 0 : 2
  const n = x.toLocaleString('es-AR', { minimumFractionDigits: dec, maximumFractionDigits: dec })
  return moneda === 'ars' ? `$ ${n}` : `US$ ${n}`
}

function fechaCorta(iso) {
  if (!iso) return ''
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y.slice(2)}`
}

export default function LecturaTecnica({ asset, symbolMiniChart, lotes = [], operaciones = [], pnlPctUsd = null }) {
  const [moneda, setMoneda] = useState('usd')
  const [rango, setRango] = useState('1a')
  const [datos, setDatos] = useState({ usd: undefined, ars: undefined })

  useEffect(() => {
    let vivo = true
    setDatos({ usd: undefined, ars: undefined })
    for (const m of ['usd', 'ars']) {
      api.get(`/tecnico/${encodeURIComponent(asset)}?moneda=${m}`)
        .then(r => { if (vivo) setDatos(d => ({ ...d, [m]: r })) })
        .catch(() => { if (vivo) setDatos(d => ({ ...d, [m]: null })) })
    }
    return () => { vivo = false }
  }, [asset])

  const actual = datos[moneda]
  const otra = datos[moneda === 'usd' ? 'ars' : 'usd']

  // Tu resultado en la moneda que se mira, para dibujar tu precio promedio.
  //   · dólares: el mismo % que la ficha muestra arriba (pnlPctUsd);
  //   · pesos: sólo si todo lo compraste en pesos y el gráfico es el de BYMA
  //     (misma unidad que tus lotes). Si no, no se dibuja: no hay un "precio en
  //     pesos" tuyo que sea verdad.
  const pnlPct = useMemo(() => {
    if (moneda === 'usd') return pnlPctUsd
    if (!actual?.disponible || actual.convertida) return null
    const abiertos = lotes.filter(l => !l.is_cash && Number(l.quantity) > 0)
    if (!abiertos.length || abiertos.some(l => String(l.currency || '').toUpperCase() !== 'ARS')) return null
    const invertido = abiertos.reduce((s, l) => s + (Number(l.invested) || 0), 0)
    const cantidad = abiertos.reduce((s, l) => s + Number(l.quantity), 0)
    const ultimo = actual.puntos[actual.puntos.length - 1]?.c
    return invertido > 0 && ultimo > 0 ? (cantidad * ultimo) / invertido - 1 : null
  }, [moneda, pnlPctUsd, actual, lotes])

  if (actual === undefined) {
    return <div className="h-72 mb-5 rounded-lg bg-bg-2/40 border border-line esqueleto" aria-label="Cargando gráfico" />
  }
  if (!actual?.disponible) {
    if (moneda === 'ars' && datos.usd?.disponible) {
      return (
        <Marco moneda={moneda} setMoneda={setMoneda} rango={rango} setRango={setRango} conPesos={false}>
          <p className="text-sm text-ink-2">No hay serie en pesos para este activo.</p>
        </Marco>
      )
    }
    // Sin velas todavía: el gráfico de siempre.
    return symbolMiniChart ? (
      <section className="mb-5">
        <div className="text-[12.5px] text-ink-2 mb-2 font-medium">Precio · últimos 30 días</div>
        <div className="bg-bg-1 border border-line/60 rounded-lg p-3">
          <AssetMiniChart symbol={symbolMiniChart} />
        </div>
      </section>
    ) : null
  }

  const ruedas = RANGOS.find(r => r.id === rango)?.ruedas || 252
  const puntos = recortar(actual.puntos, ruedas)
  const promedio = lineaPromedio(actual.puntos, pnlPct)
  const lista = tarjetas(actual.lectura)
  const distintas = tendenciasDistintas(datos.usd?.lectura, datos.ars?.lectura)

  return (
    <Marco moneda={moneda} setMoneda={setMoneda} rango={rango} setRango={setRango}
      conPesos={datos.ars?.disponible !== false}>
      {moneda === 'ars' && distintas && (
        <div className="rounded-lg border border-rendi-warn/40 bg-rendi-warn/10 px-3.5 py-3 mb-3">
          <div className="text-sm font-semibold text-rendi-warn">En pesos se ve distinto que en dólares.</div>
          <p className="text-[13px] text-ink-1 leading-relaxed mt-1">
            Parte del movimiento en pesos es el dólar, no la empresa. Por eso Rendi lee la tendencia en dólares.
          </p>
        </div>
      )}

      <Grafico puntos={puntos} moneda={moneda} promedio={promedio}
        marcas={marcas(lotes, operaciones)} />

      <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-[12px] text-ink-2 mt-2.5">
        <Leyenda color={COLOR.precio}>Precio</Leyenda>
        <Leyenda color={COLOR.media200} grueso>Media 200 días</Leyenda>
        <Leyenda color={COLOR.media50}>Media 50 días</Leyenda>
        {promedio != null && <Leyenda color={COLOR.promedio} punteado>Tu precio promedio</Leyenda>}
        <span className="inline-flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-rendi-pos-fill" />Compras</span>
        <span className="inline-flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-rendi-neg-fill" />Ventas</span>
      </div>

      <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-2">
        {lista.map(t => <Tarjeta key={t.id} t={t} />)}
        {promedio != null && pnlPct != null && (
          <Tarjeta t={{
            id: 'tuyo', titulo: 'Contra tu precio', tono: pnlPct >= 0 ? 'pos' : 'neg',
            veredicto: `${Math.abs(pnlPct * 100).toLocaleString('es-AR', { maximumFractionDigits: 1, minimumFractionDigits: 1 })}% ${pnlPct >= 0 ? 'arriba' : 'abajo'}`,
            texto: moneda === 'usd'
              ? 'Lo que vale hoy contra lo que pagaste: el mismo resultado de arriba. La línea punteada es tu precio llevado a este gráfico.'
              : 'Lo que vale hoy contra lo que pagaste, todo en pesos.',
          }} />
        )}
      </div>

      <p className="text-[12px] text-ink-3 mt-3 leading-relaxed">
        {actual.convertida === 'mep' && (moneda === 'usd'
          ? 'En dólares: el precio en pesos de cada día dividido por el dólar MEP de ese día. '
          : 'En pesos: el precio en dólares de cada día por el dólar MEP de ese día. ')}
        Al cierre del {fechaCorta(actual.lectura?.fecha)}. Describe cómo se movió el precio; no es una recomendación de compra o venta.
      </p>
    </Marco>
  )
}

function Marco({ moneda, setMoneda, rango, setRango, conPesos = true, children }) {
  return (
    <section className="mb-5" aria-label="Lectura técnica">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <div className="text-[12.5px] text-ink-2 font-medium">Lectura técnica</div>
        <div className="flex items-center gap-2">
          <div className="inline-flex gap-0.5 bg-bg-2 border border-line rounded p-0.5" role="group" aria-label="Moneda">
            {[['usd', 'Dólares'], ...(conPesos ? [['ars', 'Pesos']] : [])].map(([id, label]) => (
              <button key={id} type="button" onClick={() => setMoneda(id)} aria-pressed={moneda === id}
                className={`px-2.5 py-1 text-xs rounded-sm transition-colors ${moneda === id ? 'bg-bg-1 text-ink-0 font-medium shadow-sm' : 'text-ink-2 hover:text-ink-0'}`}>
                {label}
              </button>
            ))}
          </div>
          <div className="inline-flex gap-0.5 bg-bg-2 border border-line rounded p-0.5" role="group" aria-label="Rango">
            {RANGOS.map(r => (
              <button key={r.id} type="button" onClick={() => setRango(r.id)} aria-pressed={rango === r.id}
                className={`px-2 py-1 text-xs rounded-sm tabular transition-colors ${rango === r.id ? 'bg-bg-1 text-ink-0 font-medium shadow-sm' : 'text-ink-2 hover:text-ink-0'}`}>
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="bg-bg-1 border border-line/60 rounded-lg p-3">{children}</div>
    </section>
  )
}

function Leyenda({ color, grueso, punteado, children }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <svg width="16" height="6" aria-hidden="true">
        <line x1="0" y1="3" x2="16" y2="3" stroke={color} strokeWidth={grueso ? 3 : 2}
          strokeDasharray={punteado ? '4 3' : undefined} />
      </svg>
      {children}
    </span>
  )
}

function Tarjeta({ t }) {
  const tono = t.tono === 'pos' ? 'text-rendi-pos' : t.tono === 'neg' ? 'text-rendi-neg' : 'text-ink-0'
  return (
    <div className="rounded-lg border border-line/60 bg-bg-2/40 px-3.5 py-3">
      <div className="text-[12px] text-ink-2 font-medium">{t.titulo}</div>
      <div className={`text-[15px] font-semibold mt-0.5 ${tono}`}>{t.veredicto}</div>
      <div className="text-[12.5px] text-ink-1 leading-relaxed mt-1">{t.texto}</div>
      {t.rsi != null && (
        <div className="mt-2" aria-hidden="true">
          <div className="relative h-1.5 rounded-full overflow-hidden bg-bg-3">
            <div className="absolute inset-y-0 left-0 bg-rendi-pos-fill/30" style={{ width: `${RSI_CASTIGADO}%` }} />
            <div className="absolute inset-y-0 right-0 bg-rendi-neg-fill/30" style={{ width: `${100 - RSI_ESTIRADO}%` }} />
          </div>
          <div className="relative h-0">
            <div className="absolute -top-2.5 w-1 h-3.5 rounded-full bg-ink-0" style={{ left: `calc(${Math.min(100, Math.max(0, t.rsi))}% - 2px)` }} />
          </div>
          <div className="flex justify-between text-[11px] text-ink-3 mt-1.5"><span>castigado</span><span>estirado</span></div>
        </div>
      )}
    </div>
  )
}

function Grafico({ puntos, moneda, promedio, marcas: lista }) {
  const ref = useRef(null)
  const [hover, setHover] = useState(null)

  const { escalaY, path, min, max } = useMemo(() => {
    const valores = []
    for (const p of puntos) {
      valores.push(p.c)
      if (p.s50 != null) valores.push(p.s50)
      if (p.s200 != null) valores.push(p.s200)
    }
    if (promedio != null) valores.push(promedio)
    let lo = Math.min(...valores), hi = Math.max(...valores)
    const margen = (hi - lo) * 0.06 || hi * 0.02 || 1
    lo -= margen; hi += margen
    const y = (val) => H - ((val - lo) / (hi - lo)) * H
    const x = (i) => (puntos.length > 1 ? (i / (puntos.length - 1)) * W : W / 2)
    const linea = (k) => {
      let d = '', abierto = false
      puntos.forEach((p, i) => {
        if (p[k] == null) { abierto = false; return }
        d += `${abierto ? 'L' : 'M'}${x(i).toFixed(1)},${y(p[k]).toFixed(1)}`
        abierto = true
      })
      return d
    }
    return { escalaY: y, path: { c: linea('c'), s50: linea('s50'), s200: linea('s200') }, min: lo, max: hi }
  }, [puntos, promedio])

  const rsiPath = useMemo(() => {
    let d = '', abierto = false
    puntos.forEach((p, i) => {
      if (p.rsi == null) { abierto = false; return }
      const xx = puntos.length > 1 ? (i / (puntos.length - 1)) * W : W / 2
      d += `${abierto ? 'L' : 'M'}${xx.toFixed(1)},${(H_RSI - (p.rsi / 100) * H_RSI).toFixed(1)}`
      abierto = true
    })
    return d
  }, [puntos])

  const pctX = (i) => (puntos.length > 1 ? (i / (puntos.length - 1)) * 100 : 50)
  const pctY = (val) => (escalaY(val) / H) * 100
  const desde = puntos[0]?.d
  const visibles = lista
    .filter(m => m.fecha >= desde)
    .map(m => ({ ...m, i: indiceDeFecha(puntos, m.fecha) }))
    .filter(m => m.i != null)

  function mover(e) {
    const r = ref.current?.getBoundingClientRect()
    if (!r || !puntos.length) return
    const i = Math.round(((e.clientX - r.left) / r.width) * (puntos.length - 1))
    setHover(Math.max(0, Math.min(puntos.length - 1, i)))
  }
  const ph = hover != null ? puntos[hover] : null
  const ticks = [max - (max - min) * 0.15, (max + min) / 2, min + (max - min) * 0.15]
  const ultimo = puntos[puntos.length - 1]

  return (
    <div>
      <div ref={ref} className="relative select-none" onMouseMove={mover} onMouseLeave={() => setHover(null)}
        role="img" aria-label={`Precio con media de 200 y de 50 días. Último cierre ${fmtPrecio(ultimo?.c, moneda)}.`}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full h-56 sm:h-64 block" aria-hidden="true">
          {ticks.map((t, k) => (
            <line key={k} x1="0" x2={W} y1={escalaY(t)} y2={escalaY(t)} stroke={v('chart-grid')} strokeWidth="1" vectorEffect="non-scaling-stroke" />
          ))}
          <path d={path.s200} fill="none" stroke={COLOR.media200} strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
          <path d={path.s50} fill="none" stroke={COLOR.media50} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
          {promedio != null && (
            <line x1="0" x2={W} y1={escalaY(promedio)} y2={escalaY(promedio)} stroke={COLOR.promedio}
              strokeWidth="1.2" strokeDasharray="6 5" vectorEffect="non-scaling-stroke" />
          )}
          <path d={path.c} fill="none" stroke={COLOR.precio} strokeWidth="1.6" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        </svg>

        {/* Los rótulos del eje y las marcas van en HTML: un círculo dentro de un
            SVG estirado (preserveAspectRatio=none) se deformaría en óvalo. */}
        {ticks.map((t, k) => (
          <span key={k} className="absolute right-0 -translate-y-1/2 text-[11px] text-ink-3 tabular bg-bg-1/80 px-1 rounded-xs pointer-events-none"
            style={{ top: `${pctY(t)}%` }}>{fmtPrecio(t, moneda)}</span>
        ))}
        {visibles.map((m, k) => (
          <span key={k} title={`${m.tipo === 'compra' ? 'Compra' : 'Venta'} · ${fechaCorta(m.fecha)}`}
            className={`absolute w-2.5 h-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg-1 ${m.tipo === 'compra' ? 'bg-rendi-pos-fill' : 'bg-rendi-neg-fill'}`}
            style={{ left: `${pctX(m.i)}%`, top: `${pctY(puntos[m.i].c)}%` }} />
        ))}
        {ph && (
          <>
            <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 w-px bg-ink-2/40" style={{ left: `${pctX(hover)}%` }} />
            <div className="pointer-events-none absolute top-1 left-1 rounded border border-line-2 bg-bg-raised px-2 py-1 text-[11px] leading-tight whitespace-nowrap shadow-sm tabular">
              <span className="text-ink-3">{fechaCorta(ph.d)}</span>
              <span className="mx-1.5 text-ink-0 font-medium">{fmtPrecio(ph.c, moneda)}</span>
              {ph.s200 != null && <span className="text-ink-2">· media 200 {fmtPrecio(ph.s200, moneda)}</span>}
              {ph.rsi != null && <span className="text-ink-2"> · RSI {Math.round(ph.rsi)}</span>}
            </div>
          </>
        )}
      </div>

      <div className="mt-3 border-t border-line/40 pt-2">
        <div className="flex justify-between text-[11px] text-ink-2">
          <span>Fuerza del movimiento (RSI 14 días)</span>
          <span className="tabular text-ink-0">{ultimo?.rsi != null ? Math.round(ultimo.rsi) : '—'}</span>
        </div>
        <svg viewBox={`0 0 ${W} ${H_RSI}`} preserveAspectRatio="none" className="w-full h-14 block mt-1" aria-hidden="true">
          <rect x="0" y="0" width={W} height={H_RSI * (1 - RSI_ESTIRADO / 100)} fill={v('rendi-neg-fill')} fillOpacity="0.08" />
          <rect x="0" y={H_RSI * (1 - RSI_CASTIGADO / 100)} width={W} height={H_RSI * (RSI_CASTIGADO / 100)} fill={v('rendi-pos-fill')} fillOpacity="0.08" />
          <path d={rsiPath} fill="none" stroke={v('ink-1')} strokeWidth="1.3" vectorEffect="non-scaling-stroke" />
        </svg>
      </div>
    </div>
  )
}
