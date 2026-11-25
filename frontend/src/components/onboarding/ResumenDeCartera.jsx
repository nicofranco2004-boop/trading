// ResumenDeCartera — lo que la bienvenida muestra al terminar de cargar el
// historial (paso «tu cartera» de pages/Onboarding.jsx). Es el momento «wow»:
// la primera vez que la persona ve su plata en Rendi.
//
// Se revela en actos, solos y en orden (cada pieza con su demora `--d`):
//   0. AnalizandoHistorial — mientras Rendi suma: tres pasos que se van tildando.
//   1. El total, contando hasta su número, con chispas y su resultado al lado.
//   2. «Cómo está repartida»: la torta se dibuja porción por porción.
//   3. «Lo que pagaste / lo que vale hoy»: dos barras que crecen, y debajo
//      cuánto ganó o perdió cada activo (los que más movieron el resultado).
//   4. «Lo que vi»: los hallazgos del motor de Diagnóstico, de a uno.
//
// Acá no se calcula nada: los números vienen de hooks/useCarteraRecienCargada
// (el mismo cálculo que /bienvenida) y de utils/hallazgosDeLaBienvenida.
// Las animaciones son `bv-*` de index.css, todas de entrada: sin ellas (o con
// «reducir movimiento») cada pieza queda completa. Los gráficos son decorativos
// para el lector de pantalla: cada dato está también escrito al lado.

import { useEffect, useState } from 'react'
import { AlertTriangle, Check, Lightbulb, Loader2, TrendingDown, TrendingUp, Trophy, Wallet } from 'lucide-react'
import AnimatedNumber from '../AnimatedNumber'
import AssetLogo from '../AssetLogo'
import DiagnosticText from '../DiagnosticText'
import { fmtUsd, pctSigned } from '../../utils/format'
import { OCULTO } from '../../utils/ocultarSaldos'
import { porcionColor, PORCION_RESTO } from '../../utils/chartTheme'
import { repartoDeLaCartera, HALLAZGOS_CON_GRAFICO } from '../../utils/hallazgosDeLaBienvenida'

// Cuándo entra cada acto, en ms desde que se muestra el resumen.
export const ACTOS = { total: 100, resultado: 1250, torta: 1500, barras: 1800, fichas: 2300, hallazgos: 2900, entreHallazgos: 380 }
/** Cuándo entra lo que va DESPUÉS del resumen (el botón «Seguir»). */
export const finDelResumen = (cuantosHallazgos) =>
  (cuantosHallazgos ? ACTOS.hallazgos + cuantosHallazgos * ACTOS.entreHallazgos : ACTOS.fichas) + 250

const entra = (ms) => ({ '--d': `${ms}ms` })
const pct = (n) => `${n.toFixed(n < 10 && n % 1 !== 0 ? 1 : 0).replace('.', ',')}%`

// ── 0. Analizando ───────────────────────────────────────────────────────────

const PASOS_DEL_ANALISIS = ['Leyendo tus operaciones', 'Buscando los precios de hoy', 'Armando tu resumen']
/** Cuánto dura cada paso del análisis a la vista (el último espera a los datos). */
export const MS_POR_PASO = 800
export const MS_DEL_ANALISIS = PASOS_DEL_ANALISIS.length * MS_POR_PASO

export function AnalizandoHistorial() {
  const [hecho, setHecho] = useState(0)
  useEffect(() => {
    if (hecho >= PASOS_DEL_ANALISIS.length - 1) return
    const t = setTimeout(() => setHecho(h => h + 1), MS_POR_PASO)
    return () => clearTimeout(t)
  }, [hecho])
  return (
    <div className="bv-entra rounded-xl border border-line bg-bg-1 px-5 py-5 sm:px-6" role="status" aria-label="Analizando tu historial">
      <ul className="space-y-3">
        {PASOS_DEL_ANALISIS.map((paso, i) => {
          const estado = i < hecho ? 'listo' : i === hecho ? 'ahora' : 'falta'
          return (
            <li key={paso} className={`flex items-center gap-3 text-[14.5px] transition-colors duration-300 ${estado === 'falta' ? 'text-ink-3' : 'text-ink-0'}`}>
              <span className="w-6 h-6 flex items-center justify-center flex-shrink-0">
                {estado === 'listo' && (
                  <span className="bv-pop w-6 h-6 rounded-full bg-rendi-pos/15 text-rendi-pos flex items-center justify-center">
                    <Check size={14} strokeWidth={2.5} aria-hidden="true" />
                  </span>
                )}
                {estado === 'ahora' && <Loader2 size={18} strokeWidth={2} className="animate-spin text-data-violet" aria-hidden="true" />}
                {estado === 'falta' && <span className="w-1.5 h-1.5 rounded-full bg-line-3" />}
              </span>
              {paso}{estado === 'ahora' ? '…' : ''}
            </li>
          )
        })}
      </ul>
      <div className="mt-4 h-1 rounded-full bg-bg-3 overflow-hidden" aria-hidden="true">
        <div className="bv-crece h-full rounded-full bg-data-violet" style={{ animationDuration: `${MS_DEL_ANALISIS}ms`, animationTimingFunction: 'linear' }} />
      </div>
    </div>
  )
}

// ── El resumen ──────────────────────────────────────────────────────────────

export default function ResumenDeCartera({ stats, hallazgos = [], oculto = false }) {
  const plata = (v, dec = 0) => (oculto ? OCULTO : fmtUsd(v, dec))
  const porciones = repartoDeLaCartera(stats)
  const textuales = hallazgos.filter(h => !HALLAZGOS_CON_GRAFICO.includes(h.id)).slice(0, 3)
  const conResultado = stats.invested > 0 && Math.abs(stats.pnl) >= 1
  const arriba = stats.pnl >= 0
  // Los activos que más movieron el resultado, del que más ganó al que más perdió.
  const ranking = [...(stats.pieData || [])]
    .filter(a => Math.abs(a.pnl || 0) >= 1)
    .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl))
    .slice(0, MAX_EN_EL_RANKING)
    .sort((a, b) => b.pnl - a.pnl)
  const topeDelRanking = Math.max(...ranking.map(a => Math.abs(a.pnl)), 1)

  return (
    <div className="space-y-4">
      {/* 1. El total */}
      <div className="bv-entra relative overflow-hidden rounded-xl border border-line bg-bg-1 px-5 py-6 sm:px-7 sm:py-7" style={entra(ACTOS.total)}>
        <span aria-hidden="true" className={`absolute inset-0 ${conResultado && !arriba ? 'bv-brillo-neutro' : 'bv-brillo'}`} />
        <Chispas />
        <div className="relative">
          <div className="text-[13px] text-ink-2 mb-1.5">Tu cartera hoy</div>
          <div className="text-[clamp(28px,8.5vw,58px)] leading-none font-semibold tracking-tight tabular text-ink-0">
            <AnimatedNumber value={stats.value} duration={1300} format={(v) => plata(v, 2)} />
          </div>
          <div className="mt-3.5 flex flex-wrap items-center gap-x-3 gap-y-2">
            {conResultado && (
              <span className={`bv-pop inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[13.5px] font-medium tabular ${arriba ? 'bg-rendi-pos/10 text-rendi-pos' : 'bg-rendi-neg/10 text-rendi-neg'}`} style={entra(ACTOS.resultado)}>
                {arriba ? <TrendingUp size={15} strokeWidth={2} aria-hidden="true" /> : <TrendingDown size={15} strokeWidth={2} aria-hidden="true" />}
                {arriba ? '+' : '−'}{plata(Math.abs(stats.pnl))} · {pctSigned(stats.pnlPct)}
              </span>
            )}
            <span className="text-[13.5px] text-ink-2 tabular">
              {stats.positionCount} {stats.positionCount === 1 ? 'posición' : 'posiciones'} en {stats.brokerCount} {stats.brokerCount === 1 ? 'broker' : 'brokers'}
            </span>
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 2. Cómo está repartida */}
        {porciones.length > 0 && <Reparto porciones={porciones} />}

        {/* 3. Lo que pagaste / lo que vale hoy */}
        {conResultado && (
          <div className="bv-entra rounded-xl border border-line bg-bg-1 p-5" style={entra(ACTOS.barras)}>
            <h3 className="text-[13px] text-ink-2 mb-4">Lo que pagaste y lo que vale hoy</h3>
            <Barra rotulo="Pagaste" valor={stats.invested} tope={Math.max(stats.invested, stats.value)} texto={plata(stats.invested)} color="bg-line-3" demora={ACTOS.barras + 250} />
            <Barra rotulo="Vale hoy" valor={stats.value} tope={Math.max(stats.invested, stats.value)} texto={plata(stats.value)} color={arriba ? 'bg-rendi-pos' : 'bg-rendi-neg'} demora={ACTOS.barras + 450} fuerte />
            <p className={`mt-3 text-[13.5px] font-medium tabular ${arriba ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
              {arriba ? `${plata(Math.abs(stats.pnl))} más de lo que pagaste` : `${plata(Math.abs(stats.pnl))} menos de lo que pagaste`}
            </p>
            {ranking.length > 0 && (
              <div className="mt-5 pt-4 border-t border-line">
                <h3 className="text-[13px] text-ink-2 mb-3">Cuánto ganó o perdió cada activo</h3>
                <ul className="space-y-2.5">
                  {ranking.map((a, i) => (
                    <FilaDelRanking key={a.name} activo={a} tope={topeDelRanking} texto={plata(Math.abs(a.pnl))} primero={i === 0 && a.pnl > 0} demora={ACTOS.fichas + i * 140} />
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 4. Lo que vi */}
      {textuales.length > 0 && (
        <div>
          <h3 className="bv-entra text-[13px] text-ink-2 mb-2.5" style={entra(ACTOS.hallazgos - 150)}>Lo que vi en tu cartera</h3>
          <ul className="space-y-2.5">
            {textuales.map((h, i) => (
              <Hallazgo key={h.id} hallazgo={h} demora={ACTOS.hallazgos + i * ACTOS.entreHallazgos} />
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

/** Cuántos hallazgos escribe el resumen (los demás van en gráficos). */
export const hallazgosEscritos = (hallazgos = []) =>
  hallazgos.filter(h => !HALLAZGOS_CON_GRAFICO.includes(h.id)).slice(0, 3).length

// ── La torta ────────────────────────────────────────────────────────────────

const R = 40
const C = 2 * Math.PI * R
const HUECO = 1.6          // separación entre porciones, en unidades del círculo

function Reparto({ porciones }) {
  const [foco, setFoco] = useState(null)
  const color = (p, i) => (p.otros ? PORCION_RESTO : porcionColor(i))
  const varias = porciones.length > 1
  let corrido = 0
  const arcos = porciones.map((p, i) => {
    const largo = (p.pct / 100) * C
    const visible = Math.max(largo - (varias ? HUECO : 0), 0.6)
    const arco = { p, i, desde: corrido, visible }
    corrido += largo
    return arco
  })
  const mirada = foco != null ? porciones[foco] : porciones[0]

  return (
    <div className="bv-entra rounded-xl border border-line bg-bg-1 p-5" style={entra(ACTOS.torta)}>
      <h3 className="text-[13px] text-ink-2 mb-4">Cómo está repartida</h3>
      {/* En el celular (una columna) la torta va al lado de su leyenda; en la
          compu las dos tarjetas van lado a lado y son angostas: la leyenda baja. */}
      <div className="flex items-center gap-5 lg:flex-col lg:items-stretch lg:gap-4">
        <div className="relative w-[116px] h-[116px] sm:w-[132px] sm:h-[132px] flex-shrink-0 lg:mx-auto">
          <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90" aria-hidden="true">
            <circle cx="50" cy="50" r={R} fill="none" strokeWidth="11" className="stroke-bg-3" />
            {arcos.map(({ p, i, desde, visible }) => (
              <circle key={p.nombre} cx="50" cy="50" r={R} fill="none" strokeWidth="11" strokeLinecap="butt"
                stroke={color(p, i)}
                className="bv-porcion transition-opacity duration-200"
                style={{
                  strokeDasharray: `${visible} ${C - visible}`,
                  strokeDashoffset: -desde,
                  opacity: foco == null || foco === i ? 1 : 0.28,
                  '--c': C,
                  '--d': `${ACTOS.torta + 300 + i * 170}ms`,
                }} />
            ))}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none">
            <span className="text-[20px] sm:text-[22px] leading-none font-semibold tabular text-ink-0">{pct(mirada.pct)}</span>
            <span className="mt-1 max-w-[70px] truncate text-[11px] text-ink-2">{mirada.nombre}</span>
          </div>
        </div>
        <ul className="min-w-0 flex-1 space-y-1.5">
          {porciones.map((p, i) => (
            <li key={p.nombre}
              onMouseEnter={() => setFoco(i)} onMouseLeave={() => setFoco(null)}
              className="bv-entra flex items-center gap-2 rounded-lg px-1.5 py-1 -mx-1.5 transition-colors hover:bg-bg-2"
              style={entra(ACTOS.torta + 350 + i * 170)}>
              <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: color(p, i) }} aria-hidden="true" />
              {p.otros || p.efectivo
                ? <span className="w-5 h-5 rounded-full bg-bg-3 text-ink-2 flex items-center justify-center flex-shrink-0"><Wallet size={11} strokeWidth={2} aria-hidden="true" /></span>
                : <AssetLogo asset={p.nombre} size={20} />}
              <span className="min-w-0 flex-1 truncate text-[13.5px] text-ink-0">
                {p.otros ? `Otros (${p.cuantos})` : p.nombre}
              </span>
              <span className="text-[13.5px] font-medium tabular text-ink-1">{pct(p.pct)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

// ── Las barras y las fichas ─────────────────────────────────────────────────

function Barra({ rotulo, valor, tope, texto, color, demora, fuerte = false }) {
  const ancho = tope > 0 ? Math.max((valor / tope) * 100, 2) : 0
  return (
    <div className="mb-3 last:mb-0">
      <div className="flex items-baseline justify-between gap-3 mb-1.5">
        <span className="text-[13px] text-ink-2">{rotulo}</span>
        <span className={`text-[14px] tabular ${fuerte ? 'font-semibold text-ink-0' : 'text-ink-1'}`}>{texto}</span>
      </div>
      <div className="h-2.5 rounded-full bg-bg-3 overflow-hidden" aria-hidden="true">
        <div className={`bv-crece h-full rounded-full ${color}`} style={{ width: `${ancho}%`, '--d': `${demora}ms` }} />
      </div>
    </div>
  )
}

const MAX_EN_EL_RANKING = 4

function FilaDelRanking({ activo, tope, texto, primero, demora }) {
  const gano = activo.pnl >= 0
  const ancho = Math.max((Math.abs(activo.pnl) / tope) * 100, 4)
  return (
    <li className="bv-entra flex items-center gap-2.5" style={entra(demora)}>
      <AssetLogo asset={activo.name} size={22} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2 mb-1">
          <span className="min-w-0 truncate text-[13.5px] font-medium text-ink-0 inline-flex items-center gap-1.5">
            {activo.name}
            {primero && <Trophy size={12} strokeWidth={2} className="text-data-amber flex-shrink-0" aria-label="El que más ganó" />}
          </span>
          <span className={`text-[13.5px] font-medium tabular ${gano ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{gano ? '+' : '−'}{texto}</span>
        </div>
        <div className="h-1.5 rounded-full bg-bg-3 overflow-hidden" aria-hidden="true">
          <div className={`bv-crece h-full rounded-full ${gano ? 'bg-rendi-pos' : 'bg-rendi-neg'}`} style={{ width: `${ancho}%`, '--d': `${demora + 120}ms` }} />
        </div>
      </div>
    </li>
  )
}

// ── Los hallazgos ───────────────────────────────────────────────────────────

const CARA_DEL_HALLAZGO = {
  pos: { Icono: TrendingUp, color: 'text-rendi-pos', fondo: 'bg-rendi-pos/10', borde: 'border-l-rendi-pos' },
  neg: { Icono: TrendingDown, color: 'text-rendi-neg', fondo: 'bg-rendi-neg/10', borde: 'border-l-rendi-neg' },
  atencion: { Icono: AlertTriangle, color: 'text-rendi-warn', fondo: 'bg-rendi-warn/10', borde: 'border-l-rendi-warn' },
  info: { Icono: Lightbulb, color: 'text-data-violet', fondo: 'bg-data-violet/10', borde: 'border-l-data-violet' },
}

function Hallazgo({ hallazgo, demora }) {
  const { Icono, color, fondo, borde } = CARA_DEL_HALLAZGO[hallazgo.tono] || CARA_DEL_HALLAZGO.info
  return (
    <li className={`bv-entra flex items-start gap-3 rounded-xl border border-line border-l-2 ${borde} bg-bg-1 px-4 py-3.5`} style={entra(demora)}>
      <span className={`bv-pop w-8 h-8 rounded-lg ${fondo} ${color} flex items-center justify-center flex-shrink-0`} style={entra(demora + 120)}>
        <Icono size={16} strokeWidth={2} aria-hidden="true" />
      </span>
      <p className="min-w-0 flex-1 text-[14px] sm:text-[15px] text-ink-1 leading-snug pt-1">
        <DiagnosticText text={hallazgo.texto} />
      </p>
    </li>
  )
}

// ── Las chispas ─────────────────────────────────────────────────────────────

// Un estallido chico al aparecer el total. Posiciones fijas (no al azar): la
// misma pantalla se ve igual cada vez, y las pruebas también.
const CHISPAS = [
  [-120, -70, 'bg-data-violet'], [-80, -110, 'bg-rendi-pos'], [-30, -130, 'bg-data-cyan'], [30, -125, 'bg-data-amber'],
  [85, -105, 'bg-data-violet'], [130, -65, 'bg-rendi-pos'], [150, -10, 'bg-data-cyan'], [120, 50, 'bg-data-amber'],
  [-150, -15, 'bg-data-amber'], [-125, 45, 'bg-data-cyan'], [-60, 70, 'bg-rendi-pos'], [55, 75, 'bg-data-violet'],
]
function Chispas() {
  return (
    <span aria-hidden="true" className="pointer-events-none absolute left-[28%] top-[52%]">
      {CHISPAS.map(([x, y, color], i) => (
        <span key={i} className={`bv-chispa absolute w-1.5 h-1.5 rounded-full ${color}`}
          style={{ '--x': `${x}px`, '--y': `${y}px`, '--d': `${ACTOS.total + 250 + (i % 4) * 60}ms` }} />
      ))}
    </span>
  )
}
