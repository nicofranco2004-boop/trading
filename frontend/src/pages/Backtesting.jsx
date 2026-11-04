// Backtesting — la pestaña «Backtesting» de Análisis técnico (?tab=backtesting).
// ═══════════════════════════════════════════════════════════════════════════
// Nico, 04/11/2026; boceto aprobado: https://claude.ai/artifact/46cJx7aUeeH9CkVA7LAqX5.
// Elegís un papel, una regla y un período, y ves qué habría pasado con US$ 100
// si seguías la regla al pie de la letra, SIEMPRE al lado de comprar y no tocar
// nada: el resultado, la peor caída, cuántas compras hubo y cuántos días estuvo
// comprada; qué quiere decir, en palabras; el gráfico de las dos; y cada
// operación.
//
// LA CUENTA LA HACE EL SERVIDOR (GET /api/tecnico/:activo/backtest →
// backend/backtest.py) con la misma serie que el Gráfico. El activo es el mismo
// que el de esa pestaña (hooks/useActivoDelGrafico), se cambia con el mismo
// renglón (`Encabezado` de GraficoTecnico.jsx) y qué serie usar (la de BYMA de
// una acción argentina, o la tuya si lo tenés con otro nombre) lo decide la
// ficha (useFichaDelActivo), como en el Gráfico. Las palabras salen de
// utils/backtesting.js, que nunca promete.
//
// La regla y el período van en la dirección (?regla=rsi&anios=2): recargar o
// mandar el link abre la misma prueba.
//
// Una sola pantalla para compu y celular (R6).

import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AlertCircle } from 'lucide-react'
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
  MOTIVOS, PERIODOS, REGLAS, aniosDe, comoSeSimula, compraClave, filasDelGrafico, ganaron, lectura, porcentaje,
  precio, reglaDe, textoDelRecorte,
} from '../utils/backtesting'
import { Encabezado } from './GraficoTecnico'

const v = (token) => `rgb(var(--${token}))`
// La regla, en el violeta de la marca; comprar y mantener es la vara: un tono
// quieto y punteado, como las varas de Comparar (PrecioComparado.jsx).
const COLOR = { regla: v('data-violet'), mantener: v('ink-1') }
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
  const regla = reglaDe(searchParams.get('regla')).id
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
      <Controles regla={regla} anios={anios} onRegla={(r) => cambiar('regla', r)} onAnios={(a) => cambiar('anios', a)} />
      {activo
        ? <PruebaDe key={activo} activo={activo} regla={regla} anios={anios}
            onTuyo={(s) => setActivo(s)} onAbierto={abierto} />
        : <Skeleton className="h-72 w-full rounded-xl" />}
    </div>
  )
}

function Controles({ regla, anios, onRegla, onAnios }) {
  return (
    <section aria-label="Armá la prueba" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-3">
      <div>
        <h2 className="text-[15px] sm:text-[16px] font-semibold text-ink-0">Probá una regla con el pasado</h2>
        <p className="text-[13px] text-ink-2 mt-0.5">
          Qué habría pasado con US$ 100 si seguías la regla al pie de la letra, al lado de comprar y no tocar nada.
        </p>
      </div>
      <div className="flex flex-col sm:flex-row sm:flex-wrap sm:items-end gap-3">
        <label className="flex flex-col gap-1.5 min-w-0 sm:flex-1 sm:max-w-md">
          <span className="text-[12px] font-medium text-ink-2">Regla</span>
          <select value={regla} onChange={e => onRegla(e.target.value)}
            className="min-h-11 sm:min-h-10 rounded-lg border border-line-2 bg-bg-2 px-3 text-[14px] text-ink-0">
            {REGLAS.map(x => <option key={x.id} value={x.id}>{x.nombre}</option>)}
          </select>
        </label>
        <div className="flex flex-col gap-1.5">
          <span className="text-[12px] font-medium text-ink-2">Período</span>
          <div className="flex">
            <Segmento etiqueta="Período" valor={anios} alElegir={onAnios} opciones={PERIODOS} estirar />
          </div>
        </div>
      </div>
      <p className="text-[13px] text-ink-1 leading-relaxed">{reglaDe(regla).explica}</p>
    </section>
  )
}

function PruebaDe({ activo, regla, anios, onTuyo, onAbierto }) {
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
  // «Probó una regla» se cuenta una vez por activo, regla y período, no en cada reintento.
  const contado = useRef(null)
  // Un fondo común no tiene precio de todos los días (la ficha no le arma gráfico).
  const sinPrecios = !ficha.loading && !ficha.grafico

  useEffect(() => {
    if (ficha.loading || ficha.otroNombre || sinPrecios) return undefined
    const id = ++pedido.current
    let intento = 0
    let espera = null
    const pedir = () => {
      setCargando(true)
      setError(null)
      api.get(`/tecnico/${encodeURIComponent(activo)}/backtest?regla=${regla}&anios=${anios}${ficha.accionLocal ? '&local=1' : ''}`)
        .then(r => {
          if (id !== pedido.current) return
          if (r?.motivo === 'bajando' && intento < REINTENTOS) {
            intento += 1
            espera = setTimeout(pedir, ESPERA_MS)
            return
          }
          setRes(r)
          setCargando(false)
          const clave = `${activo}|${regla}|${anios}`
          if (r?.disponible && contado.current !== clave) {
            contado.current = clave
            track('backtesting', { regla, anios })
          }
        })
        .catch(e => {
          if (id !== pedido.current) return
          // Sin respuesta nueva no queda la prueba vieja con otra regla elegida.
          setRes(null)
          setError(e?.message || 'No se pudo armar la prueba.')
          setCargando(false)
        })
    }
    pedir()
    return () => { if (espera) clearTimeout(espera) }
  }, [activo, regla, anios, ficha.loading, ficha.otroNombre, ficha.accionLocal, sinPrecios, vuelta])

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
  const r = res.con_regla
  return (
    <div className={`flex flex-col gap-4 ${cargando ? 'opacity-60' : ''} transition-opacity`}>
      {recorte && <p className="text-[12.5px] text-ink-2">{recorte}</p>}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Tarjeta titulo="Siguiendo la regla" trazo={<Trazo color={COLOR.regla} />} resaltada
          resumen={r} operaciones={r.operaciones} detalle={ganaron(r.ganadoras)}
          comprada={r.ruedas_comprada} ruedas={res.ruedas} />
        <Tarjeta titulo="Comprar y mantener" trazo={<Trazo color={COLOR.mantener} dash={PUNTEADO} />}
          resumen={res.mantener} operaciones={1} detalle="el primer día"
          comprada={res.ruedas} ruedas={res.ruedas} />
      </div>
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

function Grafico({ res }) {
  const filas = useMemo(() => filasDelGrafico(res), [res])
  const regla = Math.round(res.con_regla.final)
  const mantener = Math.round(res.mantener.final)
  return (
    <section aria-label="Cómo habrían ido US$ 100" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-3 min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold text-ink-0">Cómo habrían ido US$ 100</h3>
          <p className="text-[12px] text-ink-2 mt-0.5">
            Del {fechaCorta(res.desde)} al {fechaCorta(res.hasta)}, en dólares. Las franjas violetas son los días en
            que la regla estaba comprada.
          </p>
        </div>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
          <li className="inline-flex items-center gap-1.5">
            <Trazo color={COLOR.regla} /><span className="text-ink-1">La regla</span>
            <span className="font-semibold text-ink-0 tabular">{plata(regla, 'usd')}</span>
          </li>
          <li className="inline-flex items-center gap-1.5">
            <Trazo color={COLOR.mantener} dash={PUNTEADO} /><span className="text-ink-1">Mantener</span>
            <span className="font-semibold text-ink-0 tabular">{plata(mantener, 'usd')}</span>
          </li>
        </ul>
      </div>
      <div className="h-64 sm:h-80 -mx-1" role="img"
        aria-label={`Siguiendo la regla, US$ 100 terminaron en ${plata(regla, 'usd')}; comprando y manteniendo, en ${plata(mantener, 'usd')}.`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={filas} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid {...chartGrid} />
            <XAxis dataKey="d" tick={chartTickSm} axisLine={false} tickLine={false} tickFormatter={mesCorto} minTickGap={40} />
            <YAxis tick={chartTickSm} axisLine={false} tickLine={false} width={36}
              domain={['auto', 'auto']} tickFormatter={x => Math.round(x)} />
            {res.operaciones.map(o => (
              <ReferenceArea key={o.compra} x1={o.compra} x2={o.venta} fill={COLOR.regla} fillOpacity={0.12}
                stroke="none" ifOverflow="hidden" />
            ))}
            <ReferenceLine y={100} stroke={chartReferenceStroke} />
            <Tooltip {...chartTooltip} labelFormatter={fechaCorta}
              formatter={(val, key) => [plata(val, 'usd'), key === 'regla' ? 'La regla' : 'Mantener']} />
            <Line dataKey="mantener" name="Mantener" type="linear" dot={false} stroke={COLOR.mantener}
              strokeWidth={1.5} strokeDasharray={PUNTEADO} isAnimationActive={false} />
            <Line dataKey="regla" name="La regla" type="linear" dot={false} stroke={COLOR.regla}
              strokeWidth={2} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}

function Operaciones({ res }) {
  const ops = res.operaciones
  if (!ops.length) return null
  const clave = compraClave(res)
  return (
    <section aria-label="Cada operación" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-3 min-w-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 pb-2">
        <h3 className="text-[15px] font-semibold text-ink-0">Cada operación</h3>
        <span className="text-[12px] text-ink-2 tabular">
          {ops.length} {ops.length === 1 ? 'compra' : 'compras'} · {ganaron(res.con_regla.ganadoras)}
        </span>
      </div>
      <ul>
        {ops.map(o => (
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
