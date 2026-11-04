// Backtesting — la pestaña «Backtesting» de Análisis técnico (?tab=backtesting).
// ═══════════════════════════════════════════════════════════════════════════
// Nico, 04/11/2026; bocetos aprobados: https://claude.ai/artifact/46cJx7aUeeH9CkVA7LAqX5.
// Elegís un papel, una regla y un período, y ves qué habría pasado con US$ 100
// si seguías la regla al pie de la letra, SIEMPRE al lado de comprar y no tocar
// nada: el resultado, la peor caída, cuántas compras hubo y cuántos días estuvo
// comprada; qué quiere decir, en palabras; el gráfico; y cada operación.
// Con «Comparar con otra regla» se suman hasta 3 (etapa 2): una tarjeta y una
// línea por regla, en el orden en que las sumaste (no de la que dio más a la que
// dio menos), y abajo del gráfico cuándo estuvo comprada cada una.
//
// LA CUENTA LA HACE EL SERVIDOR (GET /api/tecnico/:activo/backtest →
// backend/backtest.py) con la misma serie que el Gráfico, y todas las reglas
// sobre los mismos días. El activo es el mismo que el de esa pestaña
// (hooks/useActivoDelGrafico), se cambia con el mismo renglón (`Encabezado` de
// GraficoTecnico.jsx) y qué serie usar (la de BYMA de una acción argentina, o
// la tuya si lo tenés con otro nombre) lo decide la ficha (useFichaDelActivo),
// como en el Gráfico. Las palabras salen de utils/backtesting.js, que nunca
// promete.
//
// Las reglas y el período van en la dirección (?reglas=rsi,adx_squeeze&anios=2):
// recargar o mandar el link abre la misma prueba.
//
// Una sola pantalla para compu y celular (R6).

import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AlertCircle, Plus, X } from 'lucide-react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ReferenceArea,
} from 'recharts'
import Segmento from '../components/asset/Segmento'
import Skeleton from '../components/Skeleton'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import { useActivoDelGrafico } from '../hooks/useActivoDelGrafico'
import { useFichaDelActivo } from '../hooks/useFichaDelActivo'
import { api } from '../utils/api'
import { chartGrid, chartTickSm, chartTooltip, chartReferenceStroke } from '../utils/chartTheme'
import { fechaCorta, plata } from '../utils/cuantoSeMueve'
import { MONTHS, pctColor } from '../utils/format'
import { activoValido } from '../utils/graficoTecnico'
import { nombreDelCliente } from '../utils/navegacion'
import { track } from '../utils/track'
import {
  MAX_REGLAS, MOTIVOS, PERIODOS, REGLAS, aniosDe, comoSeSimula, compraClave, ganaron, lectura, otraRegla,
  porcentaje, precio, reglaDe, reglasDe, textoDelRecorte, tramosComprada,
} from '../utils/backtesting'
import { Encabezado } from './GraficoTecnico'

const v = (token) => `rgb(var(--${token}))`
// Una por regla, en el orden en que las sumaste: la primera en el violeta de la
// marca. Ni el verde ni el rojo (se leerían «gana» o «pierde»), ni el ámbar (es
// el de los avisos), ni el azul al lado del violeta (demasiado parecidos): las
// mismas razones que Comparar (components/fundamentals/PrecioComparado.jsx).
// Comprar y mantener es la vara: un tono quieto y punteado.
const COLOR_REGLA = [v('data-violet'), v('data-cyan'), v('cat-magenta')]
const COLOR_MANTENER = v('ink-1')
const PUNTEADO = '6 3'
// «bajando»: otra persona está bajando ese activo; se vuelve a pedir, como en Comparar.
const REINTENTOS = 3
const ESPERA_MS = 4000

const mesCorto = (iso) => {
  const [y, m] = iso.split('-')
  return `${MONTHS[Number(m) - 1]?.slice(0, 3).toLowerCase()} ${y.slice(2)}`
}

export default function Backtesting() {
  const { clientCtx } = useAdvisorContext()
  const cliente = nombreDelCliente(clientCtx)
  // El activo abierto, el mismo que el del Gráfico (hooks/useActivoDelGrafico).
  const { activo, setActivo, recientes, enfocar, elegir, abierto } = useActivoDelGrafico()
  const [searchParams, setSearchParams] = useSearchParams()
  const reglas = reglasDe(searchParams.get('reglas'))
  const anios = aniosDe(searchParams.get('anios'))
  const cambiar = (clave, valor) => setSearchParams(prev => {
    const next = new URLSearchParams(prev)
    next.set(clave, String(valor))
    return next
  }, { replace: true })

  return (
    <div className="flex flex-col gap-4">
      {activo
        ? <Encabezado activo={activo} recientes={recientes} cliente={cliente} enfocar={enfocar} onElegir={elegir} pie={null} />
        : <Skeleton className="h-10 w-48" />}
      <Controles reglas={reglas} anios={anios}
        onReglas={(rs) => cambiar('reglas', rs.join(','))} onAnios={(a) => cambiar('anios', a)} />
      {activo
        ? <PruebaDe key={activo} activo={activo} reglas={reglas} anios={anios}
            onTuyo={(s) => setActivo(s)} onAbierto={abierto} />
        : <Skeleton className="h-72 w-full rounded-xl" />}
    </div>
  )
}

function Controles({ reglas, anios, onReglas, onAnios }) {
  const varias = reglas.length > 1
  const cambiarEn = (i, id) => onReglas(reglas.map((r, k) => (k === i ? id : r)))
  const sacar = (i) => onReglas(reglas.filter((_, k) => k !== i))
  const sumar = () => { const id = otraRegla(reglas); if (id) onReglas([...reglas, id]) }
  return (
    <section aria-label="Armá la prueba" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-3">
      <div>
        <h2 className="text-[15px] sm:text-[16px] font-semibold text-ink-0">
          {varias ? 'Compará reglas con el pasado' : 'Probá una regla con el pasado'}
        </h2>
        <p className="text-[13px] text-ink-2 mt-0.5">
          Qué habría pasado con US$ 100 si seguías {varias ? 'cada regla' : 'la regla'} al pie de la letra, al lado de
          comprar y no tocar nada.
        </p>
      </div>
      <div className={`grid grid-cols-1 gap-3 ${reglas.length === 2 ? 'md:grid-cols-2' : reglas.length === 3 ? 'md:grid-cols-3' : ''}`}>
        {reglas.map((id, i) => (
          <div key={`${i}-${id}`} className={`flex flex-col gap-1.5 min-w-0 ${varias ? 'bg-bg-2/40 border border-line rounded-lg p-3' : 'sm:max-w-md'}`}>
            <label htmlFor={`bt-regla-${i}`} className="flex items-center gap-1.5 text-[12px] font-medium text-ink-2">
              {varias && <Punto color={COLOR_REGLA[i]} />}
              {varias ? `Regla ${i + 1}` : 'Regla'}
            </label>
            <div className="flex items-center gap-1.5">
              <select id={`bt-regla-${i}`} value={id} onChange={e => cambiarEn(i, e.target.value)}
                className="flex-1 min-w-0 min-h-11 sm:min-h-10 rounded-lg border border-line-2 bg-bg-2 px-3 text-[14px] text-ink-0">
                {/* Las que ya están en otro lugar no se ofrecen: no hay dos iguales. */}
                {REGLAS.filter(x => x.id === id || !reglas.includes(x.id)).map(x => (
                  <option key={x.id} value={x.id}>{x.nombre}</option>
                ))}
              </select>
              {varias && (
                <button type="button" onClick={() => sacar(i)} aria-label={`Sacar ${reglaDe(id).nombre}`}
                  className="shrink-0 inline-flex items-center justify-center min-h-11 min-w-11 sm:min-h-10 sm:min-w-10 rounded-lg text-ink-2 hover:text-ink-0 hover:bg-bg-2">
                  <X size={16} aria-hidden="true" />
                </button>
              )}
            </div>
            <p className="text-[13px] text-ink-1 leading-relaxed">{reglaDe(id).explica}</p>
          </div>
        ))}
      </div>
      <div className="flex flex-col sm:flex-row sm:flex-wrap sm:items-end sm:justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={sumar} disabled={reglas.length >= MAX_REGLAS}
            className="inline-flex items-center gap-1.5 min-h-11 sm:min-h-9 px-3.5 rounded-full border border-dashed border-line-3 text-[13px] font-medium text-ink-1 hover:text-ink-0 disabled:opacity-50 disabled:cursor-not-allowed">
            <Plus size={14} aria-hidden="true" />
            Comparar con otra regla
          </button>
          {reglas.length >= MAX_REGLAS && (
            <span className="text-[12px] text-ink-2">Ya sumaste {MAX_REGLAS}, el máximo.</span>
          )}
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-[12px] font-medium text-ink-2">Período</span>
          <div className="flex">
            <Segmento etiqueta="Período" valor={anios} alElegir={onAnios} opciones={PERIODOS} estirar />
          </div>
        </div>
      </div>
    </section>
  )
}

function PruebaDe({ activo, reglas, anios, onTuyo, onAbierto }) {
  // Qué serie se prueba lo decide la ficha, como en el Gráfico: tu GGAL de IOL
  // es la acción de BYMA; el de Schwab, el ADR. Si lo tenés con otro nombre
  // (pediste GGAL.BA y tu lote es GGAL), se abre el tuyo.
  const ficha = useFichaDelActivo(activo, {
    conCotizacion: false,
    aceptaOtroNombre: (s) => { const a = activoValido(s); return !!a && a !== activo },
  })
  useEffect(() => {
    if (ficha.otroNombre) onTuyo(activoValido(ficha.otroNombre))
    else if (!ficha.loading) onAbierto(activo)
  }, [ficha.otroNombre, ficha.loading]) // eslint-disable-line react-hooks/exhaustive-deps

  const [res, setRes] = useState(null)
  const [error, setError] = useState(null)
  const [cargando, setCargando] = useState(false)
  const [vuelta, setVuelta] = useState(0)
  const pedido = useRef(0)
  // «Probó reglas» se cuenta una vez por activo, reglas y período, no en cada reintento.
  const contado = useRef(null)
  // Un fondo común no tiene precio de todos los días (la ficha no le arma gráfico).
  const sinPrecios = !ficha.loading && !ficha.grafico
  const clave = reglas.join(',')

  useEffect(() => {
    if (ficha.loading || ficha.otroNombre || sinPrecios) return undefined
    const id = ++pedido.current
    let intento = 0
    let espera = null
    const pedir = () => {
      setCargando(true)
      setError(null)
      api.get(`/tecnico/${encodeURIComponent(activo)}/backtest?reglas=${clave}&anios=${anios}${ficha.accionLocal ? '&local=1' : ''}`)
        .then(r => {
          if (id !== pedido.current) return
          if (r?.motivo === 'bajando' && intento < REINTENTOS) {
            intento += 1
            espera = setTimeout(pedir, ESPERA_MS)
            return
          }
          setRes(r)
          setCargando(false)
          const contar = `${activo}|${clave}|${anios}`
          if (r?.disponible && contado.current !== contar) {
            contado.current = contar
            track('backtesting', { reglas: clave, anios })
          }
        })
        .catch(e => {
          if (id !== pedido.current) return
          // Sin respuesta nueva no queda la prueba vieja con otras reglas elegidas.
          setRes(null)
          setError(e?.message || 'No se pudo armar la prueba.')
          setCargando(false)
        })
    }
    pedir()
    return () => { if (espera) clearTimeout(espera) }
  }, [activo, clave, anios, ficha.loading, ficha.otroNombre, ficha.accionLocal, sinPrecios, vuelta])

  if (sinPrecios) {
    return (
      <Aviso>
        Los fondos comunes no tienen un precio de todos los días para probar una regla: se valúan una vez por día,
        por el valor de la cuotaparte. Elegí otro activo arriba a la izquierda.
      </Aviso>
    )
  }
  if (error) {
    return (
      <Aviso error onReintentar={() => setVuelta(x => x + 1)}>No se pudo armar la prueba. {error}</Aviso>
    )
  }
  if (!res || (cargando && !res.disponible)) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Skeleton className="h-40 w-full rounded-xl" />
          <Skeleton className="h-40 w-full rounded-xl" />
        </div>
        <Skeleton className="h-72 w-full rounded-xl" />
      </div>
    )
  }
  if (!res.disponible) {
    return (
      <Aviso onReintentar={res.motivo === 'bajando' ? () => setVuelta(x => x + 1) : null}>
        {activo} {MOTIVOS[res.motivo] || MOTIVOS.sin_datos}
      </Aviso>
    )
  }
  return <Resultado res={res} cargando={cargando} />
}

function Aviso({ children, error = false, onReintentar = null }) {
  return (
    <div role="status" className={`flex items-start gap-2 rounded-xl border px-4 py-4 text-[14px] ${
      error ? 'border-rendi-neg/30 bg-rendi-neg/5 text-ink-0' : 'border-line bg-bg-1 text-ink-1'}`}>
      {error && <AlertCircle size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-rendi-neg" />}
      <p>
        {children}
        {onReintentar && (
          <button type="button" onClick={onReintentar}
            className="ml-1.5 inline-flex items-center min-h-10 sm:min-h-0 font-medium text-data-violet hover:underline">
            Reintentar
          </button>
        )}
      </p>
    </div>
  )
}

function Resultado({ res, cargando }) {
  const lec = lectura(res)
  const recorte = textoDelRecorte(res)
  const varias = res.resultados.length > 1
  const columnas = res.resultados.length === 1 ? '' : res.resultados.length === 2 ? 'lg:grid-cols-3' : 'lg:grid-cols-4'
  return (
    <div className={`flex flex-col gap-4 ${cargando ? 'opacity-60' : ''} transition-opacity`}>
      {recorte && <p className="text-[12.5px] text-ink-2">{recorte}</p>}
      <div className={`grid grid-cols-1 sm:grid-cols-2 ${columnas} gap-4`}>
        {res.resultados.map((x, i) => (
          <Tarjeta key={x.regla} titulo={varias ? reglaDe(x.regla).corto : 'Siguiendo la regla'}
            trazo={<Trazo color={COLOR_REGLA[i]} />} resaltada={!varias}
            resumen={x} operaciones={x.compras} detalle={ganaron(x.ganadoras)}
            comprada={x.ruedas_comprada} ruedas={res.ruedas} />
        ))}
        <Tarjeta titulo="Comprar y mantener" trazo={<Trazo color={COLOR_MANTENER} dash={PUNTEADO} />}
          resumen={res.mantener} operaciones={1} detalle="el primer día"
          comprada={res.ruedas} ruedas={res.ruedas} />
      </div>
      {varias && (
        <p className="text-[12px] text-ink-2 -mt-1">
          Las reglas van en el orden en que las sumaste. No las ordenamos de la que dio más a la que dio menos.
        </p>
      )}
      {lec && (
        <section aria-label="Qué quiere decir" className="bg-bg-2/60 rounded-lg px-4 py-3 flex flex-col gap-1.5">
          <h3 className="text-[14px] font-semibold text-ink-0">{lec.titulo}</h3>
          {lec.frases.map(f => <p key={f} className="text-[13.5px] text-ink-1 leading-relaxed">{f}</p>)}
        </section>
      )}
      <Grafico res={res} />
      <Operaciones res={res} />
      <p className="text-[12px] text-ink-2 leading-relaxed">{comoSeSimula(res)}</p>
    </div>
  )
}

function Tarjeta({ titulo, trazo, resumen, operaciones, detalle, comprada, ruedas, resaltada = false }) {
  return (
    <section aria-label={titulo} className={`bg-bg-1 border rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-3 min-w-0 ${
      resaltada ? 'border-data-violet/40' : 'border-line'}`}>
      <h3 className="flex items-center gap-2 text-[14px] font-semibold text-ink-0">{trazo}{titulo}</h3>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-3">
        <Dato etiqueta="Resultado">
          <span className={`text-[26px] leading-tight font-semibold tabular ${pctColor(resumen.resultado, 1)}`}>
            {porcentaje(resumen.resultado)}
          </span>
        </Dato>
        <Dato etiqueta="Peor caída">
          <span className="text-[18px] font-semibold tabular text-ink-0">{porcentaje(resumen.peor_caida, 0)}</span>
        </Dato>
        <Dato etiqueta="Operaciones">
          <span className="text-[16px] font-semibold tabular text-ink-0">{operaciones}</span>
          <span className="text-[12.5px] text-ink-2"> · {detalle}</span>
        </Dato>
        <Dato etiqueta="Días comprado">
          <span className="text-[16px] font-semibold tabular text-ink-0">{comprada}</span>
          <span className="text-[12.5px] text-ink-2 tabular"> de {ruedas}</span>
        </Dato>
      </dl>
    </section>
  )
}

function Dato({ etiqueta, children }) {
  return (
    <div className="min-w-0">
      <dt className="text-[12px] text-ink-2">{etiqueta}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  )
}

function Trazo({ color, dash }) {
  return (
    <svg width="16" height="4" aria-hidden="true" className="shrink-0">
      <line x1="0" y1="2" x2="16" y2="2" stroke={color} strokeWidth="2.5" strokeDasharray={dash} />
    </svg>
  )
}

function Punto({ color }) {
  return <span aria-hidden="true" className="inline-block w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
}

function Grafico({ res }) {
  const varias = res.resultados.length > 1
  const lineas = [
    ...res.resultados.map((x, i) => ({ clave: x.regla, nombre: varias ? reglaDe(x.regla).corto : 'La regla', color: COLOR_REGLA[i], final: x.final })),
    { clave: 'mantener', nombre: 'Mantener', color: COLOR_MANTENER, dash: PUNTEADO, final: res.mantener.final },
  ]
  // Una regla: sus días comprada son franjas violetas detrás de la línea. Con
  // varias, las franjas se taparían entre sí: van abajo, una fila por regla.
  const franjas = varias ? [] : res.resultados[0].operaciones
  return (
    <section aria-label="Cómo habrían ido US$ 100" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-3 min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold text-ink-0">Cómo habrían ido US$ 100</h3>
          <p className="text-[12px] text-ink-2 mt-0.5">
            Del {fechaCorta(res.desde)} al {fechaCorta(res.hasta)}, en dólares.
            {varias ? '' : ' Las franjas violetas son los días en que la regla estaba comprada.'}
          </p>
        </div>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
          {lineas.map(l => (
            <li key={l.clave} className="inline-flex items-center gap-1.5">
              <Trazo color={l.color} dash={l.dash} /><span className="text-ink-1">{l.nombre}</span>
              <span className="font-semibold text-ink-0 tabular">{plata(Math.round(l.final), 'usd')}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="h-64 sm:h-80 -mx-1" role="img"
        aria-label={lineas.map(l => `${l.nombre}: US$ 100 terminaron en ${plata(Math.round(l.final), 'usd')}`).join('; ')}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={res.curva} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid {...chartGrid} />
            <XAxis dataKey="d" tick={chartTickSm} axisLine={false} tickLine={false} tickFormatter={mesCorto} minTickGap={40} />
            <YAxis tick={chartTickSm} axisLine={false} tickLine={false} width={36}
              domain={['auto', 'auto']} tickFormatter={x => Math.round(x)} />
            {franjas.map(o => (
              <ReferenceArea key={o.compra} x1={o.compra} x2={o.venta} fill={COLOR_REGLA[0]} fillOpacity={0.12}
                stroke="none" ifOverflow="hidden" />
            ))}
            <ReferenceLine y={100} stroke={chartReferenceStroke} />
            <Tooltip {...chartTooltip} labelFormatter={fechaCorta}
              formatter={(val, key) => [plata(val, 'usd'), lineas.find(l => l.clave === key)?.nombre || key]} />
            {[...lineas].reverse().map(l => (
              <Line key={l.clave} dataKey={l.clave} name={l.nombre} type="linear" dot={false} stroke={l.color}
                strokeWidth={l.dash ? 1.5 : 2} strokeDasharray={l.dash} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {varias && <CuandoComprada res={res} />}
    </section>
  )
}

/** Con varias reglas: una fila por regla con los días que estuvo comprada,
 *  alineada con el período del gráfico (el ancho del eje de números a la
 *  izquierda y el margen de la derecha). */
function CuandoComprada({ res }) {
  return (
    <div className="flex flex-col gap-2 pt-1" style={{ marginLeft: 36, marginRight: 8 }}>
      <h4 className="text-[12.5px] font-semibold text-ink-1">Cuándo estuvo comprada cada una</h4>
      {res.resultados.map((x, i) => (
        <div key={x.regla} className="flex flex-col gap-1">
          <span className="text-[12px] text-ink-2 tabular">
            <span className="font-medium" style={{ color: COLOR_REGLA[i] }}>{reglaDe(x.regla).corto}</span>
            {' · '}{x.ruedas_comprada}{' '}de {res.ruedas} días
          </span>
          <div className="relative h-2 rounded-xs bg-bg-2 overflow-hidden" aria-hidden="true">
            {tramosComprada(res, x).map(t => (
              <span key={t.desde} className="absolute inset-y-0" style={{ left: `${t.desde}%`, width: `${t.ancho}%`, background: COLOR_REGLA[i] }} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function Operaciones({ res }) {
  const [ver, setVer] = useState(0)
  const i = Math.min(ver, res.resultados.length - 1)
  const x = res.resultados[i]
  const varias = res.resultados.length > 1
  if (!varias && !x.operaciones.length) return null
  const clave = compraClave(x)
  return (
    <section aria-label="Cada operación" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-3 min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 pb-2">
        <h3 className="text-[15px] font-semibold text-ink-0">Cada operación</h3>
        {varias ? (
          <div role="group" aria-label="Ver las operaciones de" className="flex flex-wrap gap-1.5">
            {res.resultados.map((y, k) => (
              <button key={y.regla} type="button" onClick={() => setVer(k)} aria-pressed={k === i}
                className={`inline-flex items-center gap-1.5 min-h-11 sm:min-h-8 px-3 rounded-full border text-[13px] font-medium transition-colors ${
                  k === i ? 'border-line-3 bg-bg-2 text-ink-0' : 'border-line text-ink-1 hover:text-ink-0'}`}>
                <Punto color={COLOR_REGLA[k]} />
                {reglaDe(y.regla).corto}
                <span className="text-ink-2 tabular">· {y.compras}</span>
              </button>
            ))}
          </div>
        ) : (
          <span className="text-[12px] text-ink-2 tabular">
            {x.compras} {x.compras === 1 ? 'compra' : 'compras'} · {ganaron(x.ganadoras)}
          </span>
        )}
      </div>
      {!x.operaciones.length && (
        <p className="py-3 border-t border-line/60 text-[13.5px] text-ink-1">Esta regla no marcó ninguna compra en el período.</p>
      )}
      <ul>
        {x.operaciones.map(o => (
          <li key={o.compra} className="flex items-center justify-between gap-3 py-2.5 border-t border-line/60">
            <div className="min-w-0 flex flex-col gap-0.5">
              <span className="text-[14px] font-medium text-ink-0 tabular">
                {fechaCorta(o.compra)} → {o.abierta ? 'seguía comprada' : fechaCorta(o.venta)}
              </span>
              <span className="text-[12px] text-ink-2 tabular">
                US$ {precio(o.precio_compra)} → US$ {precio(o.precio_venta)}{o.abierta ? ' (último cierre)' : ''}
                {/* Espacio que no corta: «46 días» no se parte en dos renglones. */}
                {' · '}{o.ruedas}{' '}{o.ruedas === 1 ? 'día' : 'días'}
              </span>
              {clave === o.compra && (
                <span className="text-[12px] text-ink-1">Esta compra explica casi todo el resultado.</span>
              )}
            </div>
            <span className={`shrink-0 text-[15px] font-semibold tabular ${pctColor(o.resultado, 1)}`}>
              {porcentaje(o.resultado)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
