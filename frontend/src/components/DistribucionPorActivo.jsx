// DistribucionPorActivo — la torta "Distribución de activos": cuánto pesa cada
// activo sobre TODO el patrimonio (tenencias, efectivo y plazo fijo).
//
// Una sola tarjeta para el Dashboard y Análisis → Diagnóstico. Antes eran dos
// barras distintas —top 5 sin efectivo en el Dashboard, top 7 con efectivo en
// Análisis— y el mismo activo daba un % distinto en cada pantalla.
//
// Las porciones las arma la página con assetSlicesFromPositions
// (utils/bookComposition, el mismo corte que la torta por activo del libro del
// asesor), pasándole la MISMA lista y el MISMO plazo fijo que a sus tortas por
// tipo y por sector: así las tres suman el mismo total. Este componente sólo
// dibuja: los 12 activos más grandes, "Resto (N activos)" que se despliega, y
// al pie cuánto es efectivo — leído de la porción, para que ese número y el de
// la torta no puedan diferir; en ámbar desde el 30 %. Va al PIE y no arriba a
// la derecha: en el Dashboard la tarjeta va envuelta en AskAIAbout, cuyo botón
// ✦ ocupa esa esquina y lo tapaba (medido).

import CompositionDonut from './CompositionDonut'
import { DEFAULT_TOP_ASSETS } from '../utils/bookComposition'

export default function DistribucionPorActivo({ items = [], fmt, className = '' }) {
  if (items.length === 0) return null
  const efectivo = items.find(i => i.key === 'efectivo')?.pct ?? 0
  return (
    <CompositionDonut
      className={className}
      title="Distribución de activos"
      items={items}
      fmt={fmt}
      height={230}
      // El agregador ya cortó en 12 + "Resto": el donut no vuelve a agrupar
      // (el mismo trato que la torta por activo del asesor).
      maxSlices={items.length}
      minSlicePct={0}
      footnote={
        <>Efectivo: <span className={`font-semibold tabular ${efectivo >= 30 ? 'text-rendi-warn' : 'text-ink-1'}`}>{efectivo.toFixed(1).replace('.', ',')}%</span> de tu patrimonio{efectivo >= 30 ? ' — una parte grande sin invertir' : ''}.</>
      }
      info={
        <>
          <p className="font-semibold text-ink-0">Cómo se calcula</p>
          <p>
            Cuánto pesa cada activo sobre todo tu patrimonio, incluidos el
            efectivo y los plazos fijos. Un mismo activo en dos brokers (AAPL
            como CEDEAR y como acción) es una sola porción.
          </p>
          <p className="text-ink-3">
            Los {DEFAULT_TOP_ASSETS} más grandes van con su porción; el resto se
            junta en “Resto”, que se despliega para ver qué hay adentro.
          </p>
        </>
      }
    />
  )
}
