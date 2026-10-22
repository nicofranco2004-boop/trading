import { lotMissingPurchaseRate } from '../utils/valuation'
import { EtiquetaFaltaTc } from './EtiquetaFila'

/**
 * TcMissingBadge — pastilla "Falta TC" que va en el renglón de la fecha de la fila cuando el
 * modo "Costo en dólares" está en 'purchase' pero ESTE lote no tiene tc_compra
 * registrado (compras previas al fix del importador, o cargadas sin tipo de cambio)
 * → cae silenciosamente al dólar de hoy. Sin el badge, esos lotes parecerían "sin
 * devaluación" sin explicación. En modo 'today' nunca aparece.
 *
 * Uso: <TcMissingBadge p={posicion} costBasis={costBasis} isArsBroker={isARS} />
 */
export default function TcMissingBadge({ p, costBasis, isArsBroker = false, className = 'ml-1 text-[12.5px] align-middle' }) {
  if (!lotMissingPurchaseRate(p, costBasis, isArsBroker)) return null
  // La misma pastilla "Falta TC" que la fila de Cartera (EtiquetaFila).
  return <EtiquetaFaltaTc className={className} />
}
