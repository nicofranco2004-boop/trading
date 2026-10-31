// MapaCartera — «Mapa de tu cartera», en el Panorama de Análisis técnico
// (lienzo «1 · Panorama», aprobado por Nico el 30/10): un cuadrito por activo,
// de tamaño proporcional a lo que pesa y pintado según su tendencia de largo
// plazo (verde alcista, rojo bajista, punteado sin lectura). Cada cuadrito
// lleva a la ficha del activo.
// ════════════════════════════════════════════════════════════════════════════
// Una sola pieza para compu y celular (R6): la caja tiene siempre la misma
// proporción (PROPORCION) y los cuadritos van en % de la caja; lo que no entra
// en un cuadrito chico (el %, después el nombre) se esconde y queda en el globo.
//
// Los cuadritos y su lugar los arma utils/mapaCartera.js con el peso y la
// tendencia de las filas de Tu lista (la misma cuenta del % alcista). Con
// «Ocultar saldos» todos del mismo tamaño, en orden alfabético y sin %: el
// tamaño y el orden también dicen cuánto pesa cada uno.
//
// Lo de la pieza 8 (Nico, 30/10: «Sí, sumarlo»), en este MISMO componente, el
// del Panorama y el del Dashboard: «Color por: Hoy · Tendencia · Contra tu
// promedio» (Tendencia de entrada), el renglón «Hoy tu cartera» y lo que más
// sumó y restó hoy. Lo del día lo pide el mapa (GET /api/cartera/mapa-del-dia,
// la misma cuenta que el chat). Con «Ocultar saldos» no dice cuánto: ni el % de
// la cartera ni el de cada activo (sí qué activo sumó o restó).

import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../utils/api'
import {
  cuadritosDelMapa, ubicarCuadritos, PROPORCION, MODOS, QUE_ES_EL_COLOR, modoGuardado, guardarModo,
  conElDia, colorDelModo, losExtremosDeHoy,
} from '../utils/mapaCartera'
import { pesoVisible, deTuCartera } from '../utils/parteDeTuPlata'
import { pctSigned } from '../utils/format'
import { polarityLegend, CORTES_DIA, CORTES_PROMEDIO } from '../utils/polarityScale'
import { OCULTO } from '../contexts/PrivacyContext'
import { useCurrency } from '../contexts/CurrencyContext'

const TONO = {
  alcista: 'bg-rendi-pos/15 border border-rendi-pos/40',
  bajista: 'bg-rendi-neg/15 border border-rendi-neg/40',
  sin: 'bg-ink-3/10 border border-dashed border-ink-3/60',
  otros: 'bg-bg-2 border border-line',
}
const PALABRA = { alcista: 'tendencia alcista', bajista: 'tendencia bajista', sin: 'sin lectura', otros: '' }

/** Lo que dice un cuadrito en «Hoy» o «Contra tu promedio» (el globo y el
 *  lector de pantalla). Con «Ocultar saldos», nada: el % también es tuyo acá. */
function valorDelModo(c, modo, hidden) {
  if (hidden || modo === 'tendencia' || c.tendencia === 'otros' || c.clave === 'efectivo') return null
  if (modo === 'hoy') return c.hoy ? `${pctSigned(c.hoy.pct)} hoy` : (c.diaTxt ? `sin movimiento de hoy (lo último es de ${c.diaTxt})` : 'sin dato de hoy')
  if (c.promedio != null) return `${pctSigned(c.promedio)} contra lo que pagaste`
  return c.promedioSinDato ? `sin dato contra lo que pagaste: ${c.promedioSinDato}` : 'sin lo que pagaste'
}

function Cuadrito({ c, r, rutaOtros, hidden, modo }) {
  const peso = c.peso == null ? null : pesoVisible(c.peso, hidden)
  // Lo que entra según el tamaño (en % de la caja): el nombre en casi todos,
  // el % sólo en los que tienen alto para dos renglones.
  const conNombre = r.w >= 7 && r.h >= 13
  const conPct = peso != null && r.w >= 10 && r.h >= 26
  const grande = r.w >= 22 && r.h >= 40
  const globo = [c.nombre, c.peso == null ? null : deTuCartera(c.peso, hidden), PALABRA[c.tendencia] || null,
    valorDelModo(c, modo, hidden)].filter(Boolean).join(' · ')
  // «Hoy» y «Contra tu promedio»: la rampa verde/roja (utils/polarityScale);
  // «Tendencia», los tonos del lienzo. «y N más» va siempre sin color.
  const pinta = c.tendencia === 'otros' ? null : colorDelModo(c, modo)
  const cuerpo = (
    <span className={`h-full w-full rounded-lg ${pinta ? 'border border-line/40' : TONO[c.tendencia]} px-2 py-1.5 sm:px-2.5 sm:py-2 flex flex-col justify-between overflow-hidden ${pinta ? '' : 'text-ink-0'} transition-colors`}
      style={pinta ? { background: pinta.bg, color: pinta.ink } : undefined}>
      {conNombre && (
        <b className={`font-semibold leading-tight truncate ${grande ? 'text-[14px] sm:text-[16px]' : 'text-[11.5px] sm:text-[13px]'}`}>{c.nombre}</b>
      )}
      {conPct && <span className={`text-[11px] sm:text-[12px] tabular ${pinta ? '' : 'text-ink-1'}`}>{peso}</span>}
    </span>
  )
  const lugar = { left: `${r.x}%`, top: `${r.y}%`, width: `${r.w}%`, height: `${r.h}%` }
  const ruta = c.ruta ? `/activo/${encodeURIComponent(c.ruta)}` : c.tendencia === 'otros' ? rutaOtros : null
  if (!ruta) {
    return <li className="absolute p-0.5" style={lugar} title={globo} aria-label={globo}>{cuerpo}</li>
  }
  return (
    <li className="absolute p-0.5" style={lugar}>
      <Link to={ruta} title={globo} aria-label={globo} className="block h-full w-full rounded-lg hover:brightness-125 focus-visible:outline focus-visible:outline-2 focus-visible:outline-rendi-accent">
        {cuerpo}
      </Link>
    </li>
  )
}

/** `filas`: las de Tu lista; `sinLectura`: los nombres del grupo «sin lectura»
 *  del % (senales_semana.reparto); `rutaOtros`: a dónde lleva «y N más». */
const NINGUNO = []

/** El renglón de arriba: «Hoy tu cartera: +0,8 %» y lo que más sumó y restó.
 *  Con «Ocultar saldos», el % se tapa y de los extremos va sólo el nombre. */
function ElDia({ cartera, extremos, hidden }) {
  const { sumo, resto } = extremos
  if (!cartera && !sumo && !resto) return null
  const pct = (x) => (hidden ? null : ` (${pctSigned(x)})`)
  return (
    <div className="text-[13px] text-ink-1 leading-relaxed">
      {cartera && (
        <p className="text-[14px] text-ink-0 font-semibold">
          Hoy tu cartera:{' '}
          <span className={`tabular ${hidden ? 'text-ink-2' : cartera.pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
            {hidden ? OCULTO : pctSigned(cartera.pct / 100)}
          </span>
        </p>
      )}
      {(sumo || resto) && (
        <p>
          {sumo && <>Lo que más sumó hoy: <strong className="font-semibold text-ink-0">{sumo.nombre}</strong>{pct(sumo.pct)}.</>}
          {sumo && resto && ' '}
          {resto && <>Lo que más restó: <strong className="font-semibold text-ink-0">{resto.nombre}</strong>{pct(resto.pct)}.</>}
        </p>
      )}
    </div>
  )
}

function Leyenda({ modo }) {
  if (modo === 'tendencia') {
    return (
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-2">
        <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className={`w-2.5 h-2.5 rounded-xs ${TONO.alcista}`} />Alcista</span>
        <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className={`w-2.5 h-2.5 rounded-xs ${TONO.bajista}`} />Bajista</span>
        <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className={`w-2.5 h-2.5 rounded-xs ${TONO.sin}`} />Sin lectura (bonos, fondos, efectivo)</span>
      </div>
    )
  }
  const cortes = modo === 'promedio' ? CORTES_PROMEDIO : CORTES_DIA
  const tope = cortes.pasos[cortes.pasos.length - 1]
  return (
    <div className="flex flex-wrap items-center gap-2 text-[12px] text-ink-2 tabular">
      <span>−{tope} %</span>
      <span className="inline-flex rounded-xs overflow-hidden" aria-hidden="true">
        {polarityLegend().map(p => <span key={p.key} className="inline-block w-5 h-2" style={{ background: p.bg }} />)}
      </span>
      <span>+{tope} %</span>
      <span className="inline-flex items-center gap-1.5 ml-2">
        <span aria-hidden="true" className="inline-block w-2.5 h-2.5 rounded-xs" style={{ background: 'rgb(var(--bg-3))' }} />sin dato
      </span>
    </div>
  )
}

export default function MapaCartera({ filas, cargando, error, hidden, sinLectura = NINGUNO, rutaOtros }) {
  const [modo, setModoEstado] = useState(modoGuardado)
  const elegir = (m) => { setModoEstado(m); guardarModo(m) }
  // Lo del día (hoy y contra lo que pagaste): lo pide el mapa, en las dos
  // pantallas igual. Si no llega, el mapa sigue con la tendencia.
  const [delDia, setDelDia] = useState(null)
  useEffect(() => {
    let vivo = true
    Promise.resolve(api.get('/cartera/mapa-del-dia'))
      .then(r => { if (vivo && r && Array.isArray(r.activos)) setDelDia(r) })
      .catch(() => {})
    return () => { vivo = false }
  }, [])
  // «Contra tu promedio» en la moneda de la app y con su «costo en dólares».
  const { currency, costBasis } = useCurrency()
  const cuadritos = useMemo(
    () => conElDia(cuadritosDelMapa(filas, { hidden, sinLectura }), delDia, { currency, costBasis }),
    [filas, hidden, sinLectura, delDia, currency, costBasis])
  const lugares = useMemo(() => ubicarCuadritos(cuadritos.map(c => c.peso)), [cuadritos])
  const nombres = useMemo(() => new Map((filas || []).map(f => [f.clave, f.detalle ? `${f.nombre} ${f.detalle}` : f.nombre])), [filas])
  const extremos = useMemo(() => losExtremosDeHoy(delDia, nombres), [delDia, nombres])

  return (
    <section aria-label="Mapa de tu cartera" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-3 min-w-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <h2 className="text-[15px] font-semibold text-ink-0">Mapa de tu cartera</h2>
        <span className="text-[12px] text-ink-2 font-medium">
          {hidden ? QUE_ES_EL_COLOR[modo] : <><span className="sm:hidden">tamaño = cuánto pesa</span><span className="hidden sm:inline">tamaño = cuánto pesa · {QUE_ES_EL_COLOR[modo]}</span></>}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-ink-2 font-medium" id="mapa-color-por">Color por</span>
        <div role="radiogroup" aria-labelledby="mapa-color-por" className="inline-flex gap-0.5 bg-bg-0 border border-line rounded-lg p-0.5">
          {MODOS.map(m => (
            <button key={m.id} type="button" role="radio" aria-checked={modo === m.id} onClick={() => elegir(m.id)}
              className={`px-2.5 sm:px-3 py-1.5 min-h-[32px] text-[12.5px] sm:text-[13px] rounded transition-colors ${modo === m.id ? 'bg-bg-3 text-ink-0 font-semibold' : 'text-ink-2 hover:text-ink-0'}`}>
              {m.label}
            </button>
          ))}
        </div>
      </div>
      {!error && !cargando && cuadritos.length > 0 && <ElDia cartera={delDia?.cartera} extremos={extremos} hidden={hidden} />}
      {error ? (
        <p className="text-[13.5px] text-ink-1">En este momento no pudimos cargar tus activos. Probá recargar la página en unos minutos.</p>
      ) : cargando ? (
        <div className="w-full rounded-lg bg-bg-2/40 esqueleto" style={{ aspectRatio: PROPORCION }} aria-label="Cargando el mapa de tu cartera" />
      ) : !cuadritos.length ? (
        <p className="text-[13.5px] text-ink-1">Cuando cargues tus activos, acá vas a ver cuánto pesa cada uno y hacia dónde va su precio.</p>
      ) : (
        <>
          {hidden && <p className="text-[12px] text-ink-2">Con los saldos ocultos, todos van del mismo tamaño.</p>}
          <ul className="relative w-full" style={{ aspectRatio: PROPORCION }} aria-label="Tus activos">
            {cuadritos.map((c, i) => <Cuadrito key={c.clave} c={c} r={lugares[i]} rutaOtros={rutaOtros} hidden={hidden} modo={modo} />)}
          </ul>
          <Leyenda modo={modo} />
        </>
      )}
    </section>
  )
}
