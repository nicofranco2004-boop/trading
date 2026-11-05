// Piezas de la pestaña «Backtesting» que usan sus dos modos: «Una regla»
// (pages/Backtesting.jsx) y «Una cartera» (pages/SimularCartera.jsx). Un solo
// gráfico de «Cómo habrían ido US$ 100», un solo aviso y los mismos trazos:
// los dos modos se ven iguales porque son lo mismo, no dos copias.
import { AlertCircle } from 'lucide-react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ReferenceArea,
} from 'recharts'
import { chartGrid, chartTickSm, chartTooltip, chartReferenceStroke } from '../../utils/chartTheme'
import { fechaCorta, plata } from '../../utils/cuantoSeMueve'
import { MONTHS } from '../../utils/format'

export const v = (token) => `rgb(var(--${token}))`
// La vara (comprar y mantener, los índices): un tono quieto y punteado.
export const PUNTEADO = '6 3'
// «bajando»: otra persona está bajando ese activo; se vuelve a pedir, como en Comparar.
export const REINTENTOS = 3
export const ESPERA_MS = 4000

export const mesCorto = (iso) => {
  const [y, m] = iso.split('-')
  return `${MONTHS[Number(m) - 1]?.slice(0, 3).toLowerCase()} ${y.slice(2)}`
}

export function Aviso({ children, error = false, detalle = null, onReintentar = null }) {
  return (
    <div role="status" className={`flex items-start gap-2 rounded-xl border px-4 py-4 text-[14px] ${
      error ? 'border-rendi-neg/30 bg-rendi-neg/5 text-ink-0' : 'border-line bg-bg-1 text-ink-1'}`}>
      {error && <AlertCircle size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-rendi-neg" />}
      <div>
        <p>
          {children}
          {onReintentar && (
            <button type="button" onClick={onReintentar}
              className="ml-1.5 inline-flex items-center min-h-11 sm:min-h-0 font-medium text-data-violet hover:underline">
              Reintentar
            </button>
          )}
        </p>
        {detalle && <p className="mt-0.5 text-[12px] text-ink-2">Detalle: {detalle}</p>}
      </div>
    </div>
  )
}

export function Dato({ etiqueta, children }) {
  return (
    <div className="min-w-0">
      <dt className="text-[12px] text-ink-2">{etiqueta}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  )
}

export function Trazo({ color, dash }) {
  return (
    <svg width="16" height="4" aria-hidden="true" className="shrink-0">
      <line x1="0" y1="2" x2="16" y2="2" stroke={color} strokeWidth="2.5" strokeDasharray={dash} />
    </svg>
  )
}

export function Punto({ color }) {
  return <span aria-hidden="true" className="inline-block w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
}

/** «Cómo habrían ido US$ 100»: una línea por cada cosa que se compara, todas en
 *  100 el primer día. `curva`: [{d, <clave>: valor}]; `lineas`: [{clave, nombre,
 *  color, dash, final}], la de adelante primero; `franjas`: [{compra, venta}]
 *  pintadas detrás (los días en que una regla estaba comprada). */
export function GraficoDeCien({ curva, lineas, desde, hasta, nota = '', franjas = [], colorFranjas, children }) {
  return (
    <section aria-label="Cómo habrían ido US$ 100" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-3 min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold text-ink-0">Cómo habrían ido US$ 100</h3>
          <p className="text-[12px] text-ink-2 mt-0.5">
            Del {fechaCorta(desde)} al {fechaCorta(hasta)}, en dólares.{nota ? ` ${nota}` : ''}
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
          <LineChart data={curva} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid {...chartGrid} />
            <XAxis dataKey="d" tick={chartTickSm} axisLine={false} tickLine={false} tickFormatter={mesCorto} minTickGap={40} />
            <YAxis tick={chartTickSm} axisLine={false} tickLine={false} width={36}
              domain={['auto', 'auto']} tickFormatter={x => Math.round(x)} />
            {franjas.map(o => (
              <ReferenceArea key={o.compra} x1={o.compra} x2={o.venta} fill={colorFranjas} fillOpacity={0.12}
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
      {children}
    </section>
  )
}
