import { lotMissingPurchaseRate } from '../utils/valuation'

/**
 * TcMissingBadge — pill "TC?" que se muestra junto a la columna INV. USD cuando el
 * modo "Costo en dólares" está en 'purchase' pero ESTE lote no tiene tc_compra
 * registrado (compras previas al fix del importador, o cargadas sin tipo de cambio)
 * → cae silenciosamente al dólar de hoy. Sin el badge, esos lotes parecerían "sin
 * devaluación" sin explicación. En modo 'today' nunca aparece.
 *
 * Uso: <TcMissingBadge p={posicion} costBasis={costBasis} />
 */
export default function TcMissingBadge({ p, costBasis }) {
  if (!lotMissingPurchaseRate(p, costBasis)) return null
  return (
    <span
      className="ml-1 text-[9px] font-mono uppercase tracking-[0.1em] px-1 py-0.5 rounded-sm bg-rendi-warn/15 text-rendi-warn border border-rendi-warn/30 align-middle select-none"
      title="Sin tipo de cambio de compra registrado — este lote usa el dólar de hoy para el costo en USD"
    >
      TC?
    </span>
  )
}
