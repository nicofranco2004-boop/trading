// DiarioResumen — las tarjetas y «Lo que dicen tus números» arriba de las
// operaciones cerradas (pieza 11). Un solo componente para la compu y el
// celular (R6): la grilla pasa de 3 columnas a 1.
//
// La cantidad de cerradas y en cuántas ganaste NO se repite acá: ya está en la
// franja de arriba (el Win rate, utils/tradeStats). Estas tres son las nuevas.

import Panel from '../Panel'
import InfoTooltip from '../InfoTooltip'
import { pctSigned, colorClass } from '../../utils/format'
import { mesesDe, fraseDeTusNumeros, ACLARACION_DIARIO } from '../../utils/diarioOperaciones'

function Tarjeta({ titulo, ayuda, children, sub }) {
  return (
    <Panel padding="sm" className="flex flex-col gap-0.5 sm:gap-1 min-w-0 sm:p-4">
      <div className="flex items-center gap-1 text-[12.5px] text-ink-2 font-medium">
        {titulo}
        {ayuda && <InfoTooltip label={`Qué es ${titulo}`}>{ayuda}</InfoTooltip>}
      </div>
      <div className="text-xl sm:text-2xl font-semibold tabular text-ink-0 leading-tight">{children}</div>
      {sub && <div className="text-[12.5px] text-ink-2">{sub}</div>}
    </Panel>
  )
}

const Chico = ({ children }) => <span className="text-[15px] text-ink-3 font-medium">{children}</span>

// `aparte`: lo que va al costado de la frase en pantallas anchas (la tesis de
// una posición abierta, TesisPosiciones). Sin cerradas, va solo.
export default function DiarioResumen({ resumen, estadoTendencias = 'listo', aparte = null, className = '' }) {
  if (!resumen || resumen.cerradas === 0) return aparte ? <div className={className}>{aparte}</div> : null
  const r = resumen
  const frase = fraseDeTusNumeros(r)
  const mg = mesesDe(r.diasGanadoras), mp = mesesDe(r.diasPerdedoras)
  const faltanT = r.ganadas - r.ganadorasConTendencia
  return (
    <div className={className}>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 sm:gap-3">
        <Tarjeta
          titulo="Tiempo que las tuviste"
          ayuda={<p>El promedio de días entre la compra y la venta, pasado a meses. Una venta que cerró dos compras cuenta dos veces, cada una con su fecha.</p>}
          sub={mg && mp ? 'ganadoras contra perdedoras'
            : mg ? 'tus ganadoras (todavía no cerraste una perdiendo)'
            : mp ? 'tus perdedoras (todavía no cerraste una ganando)'
            : 'faltan las fechas de compra'}
        >
          {mg && mp ? <>{mg} <Chico>contra</Chico> {mp} <Chico>meses</Chico></>
            : (mg || mp) ? <>{mg || mp} <Chico>meses</Chico></> : '—'}
        </Tarjeta>
        <Tarjeta
          titulo="Rendimiento por año"
          ayuda={<>
            <p>Todo lo que ganaste y perdiste, en dólares, dividido por la plata que pusiste multiplicada por el tiempo que estuvo puesta. Una venta grande y larga pesa más que una chica y corta.</p>
            <p className="mt-1 text-ink-3">Por eso puede no coincidir con el promedio de la columna «Por año», que mira cada venta sola.</p>
          </>}
          sub={r.nPorAnio ? `por cada dólar y cada año que estuvo invertido, en ${r.nPorAnio === 1 ? 'tu venta' : `tus ${r.nPorAnio} ventas`}` : 'faltan las fechas o el precio de compra'}
        >
          <span className={r.porAnio != null ? colorClass(r.porAnio) : ''}>{r.porAnio != null ? pctSigned(r.porAnio) : '—'}</span>
        </Tarjeta>
        <Tarjeta
          titulo="Compraste con tendencia a favor"
          ayuda={<>
            <p>«A favor»: el día que compraste, el precio estaba arriba de su promedio de los últimos 200 días de mercado (la señal más usada de que la tendencia de fondo es alcista).</p>
            <p className="mt-1 text-ink-3">Muestra cómo estaba el papel ese día, no que eso te haya hecho ganar.</p>
          </>}
          sub={estadoTendencias === 'cargando' ? 'buscando los precios de cada día…'
            : estadoTendencias === 'error' ? 'no pudimos traer los precios de cada día'
            : r.ganadas === 0 ? 'todavía no cerraste una ganando'
            : faltanT > 0 ? `de tus ganadoras (de ${faltanT} no hay precios de ese día)`
            : 'de tus ganadoras'}
        >
          {estadoTendencias !== 'listo' || r.ganadorasConTendencia === 0
            ? '—'
            : <>{r.ganadorasAFavor} <Chico>de {r.ganadorasConTendencia}</Chico></>}
        </Tarjeta>
      </div>
      <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,1fr)_380px] items-start">
        {frase.length > 0 && (
          <Panel padding="md">
            <p className="text-[14px] leading-relaxed text-ink-1">
              <strong className="font-semibold text-ink-0">Lo que dicen tus números:</strong>{' '}
              {frase.join(' ')}
            </p>
            <p className="mt-1.5 text-[12.5px] text-ink-2">{ACLARACION_DIARIO}</p>
          </Panel>
        )}
        {aparte}
      </div>
    </div>
  )
}
