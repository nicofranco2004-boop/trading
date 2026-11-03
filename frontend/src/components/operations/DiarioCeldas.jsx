// DiarioCeldas — las celdas nuevas del diario de operaciones (pieza 11), las
// MISMAS para la tabla de la compu (TradesTable) y las tarjetas del celular
// (TradesFeed): Tiempo, Por año, Tendencia al comprar y Tu tesis.

import { pctSigned } from '../../utils/format'
import {
  esDelDiario, diasTenida, rendimientoPorAnio, textoTiempo, tendenciaDe,
  MOTIVO_SIN_TENDENCIA, DIAS_MIN_POR_ANIO, tesisDeLaOperacion,
} from '../../utils/diarioOperaciones'

/** Lo que muestra cada celda nueva de una operación. null si la operación no
 *  entra en el diario (una compra, un cobro, una conversión): ahí va «—». */
export function celdasDelDiario(op, diario, currency = 'USD') {
  if (!esDelDiario(op)) return null
  const dias = diasTenida(op)
  // En la moneda de la app: el MISMO % de la columna «P&L %» (pctEnMoneda).
  const anual = rendimientoPorAnio(op, currency)
  const t = tendenciaDe(op, diario?.tendencias)
  return {
    tiempo: textoTiempo(dias),
    porAnio: anual == null ? '—' : pctSigned(anual),
    porAnioValor: anual,
    porAnioPorQue: anual != null ? null
      : dias == null ? 'Falta la fecha de compra.'
      : dias < DIAS_MIN_POR_ANIO ? `La tuviste ${textoTiempo(dias)}: con menos de 3 meses, pasarlo a un año infla el número.`
      : 'Falta el % de la operación.',
    tendencia: t?.tendencia || null,
    tendenciaPorQue: t?.tendencia ? tituloTendencia(t)
      : t?.motivo ? MOTIVO_SIN_TENDENCIA[t.motivo] || null
      : diario?.estadoTendencias === 'error' ? MOTIVO_SIN_TENDENCIA.sin_respuesta
      : diario?.estadoTendencias === 'cargando' ? null : MOTIVO_SIN_TENDENCIA.sin_velas,
    cargandoTendencia: !t && diario?.estadoTendencias === 'cargando',
    tesis: tesisDeLaOperacion(diario?.tesis, op),
  }
}

function tituloTendencia(t) {
  const d = t.dist != null ? `${Math.abs(t.dist).toLocaleString('es-AR', { maximumFractionDigits: 1 })} % ` : ''
  return `El ${fechaCorta(t.fecha)} el precio estaba ${d}${t.tendencia === 'alcista' ? 'arriba' : 'abajo'} de su promedio de 200 días.`
}

export function fechaCorta(iso) {
  const [a, m, d] = String(iso || '').slice(0, 10).split('-')
  return a && m && d ? `${d}/${m}/${a.slice(2)}` : ''
}

/** Alcista / Bajista / sin dato. El porqué va en el globo nativo (title). */
export function ChipTendencia({ celdas, chico = false }) {
  const tam = chico ? 'text-[11px] px-1.5 py-0.5' : 'text-[12px] px-2 py-0.5'
  if (celdas?.cargandoTendencia) return <span className="text-ink-3 text-xs">…</span>
  if (!celdas?.tendencia) {
    return (
      <span title={celdas?.tendenciaPorQue || undefined} className={`inline-flex items-center rounded-full border border-line text-ink-3 font-medium ${tam}`}>
        sin dato
      </span>
    )
  }
  const alcista = celdas.tendencia === 'alcista'
  return (
    <span title={celdas.tendenciaPorQue || undefined}
      className={`inline-flex items-center rounded-full font-medium ${tam} ${alcista ? 'bg-rendi-pos/10 text-rendi-pos' : 'bg-rendi-neg/10 text-rendi-neg'}`}>
      {alcista ? 'Alcista' : 'Bajista'}
    </span>
  )
}
