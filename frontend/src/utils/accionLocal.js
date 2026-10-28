// accionLocal — ¿es una acción argentina (no un CEDEAR)?
// ═══════════════════════════════════════════════════════════════════════════
// Entonces su lectura técnica en dólares es su precio de BYMA ÷ el MEP, no el
// ADR de Nueva York (GGAL "de afuera" son 10 acciones). Lo decide lo que TENÉS:
// si todos tus lotes de ese activo son de BYMA (y no es CEDEAR ni cripto). Sin
// lotes, no: la ficha muestra el ADR.
//
// Una sola regla para la ficha (AssetDetail → GET /api/tecnico?local=1), la
// radiografía de la Cartera (utils/radiografia.js, lote por lote) y
// las alertas técnicas que se arman desde el buscador de Alertas: si cada una
// decidiera por su lado, el aviso miraba la acción de BYMA y el botón del mail
// abría la ficha con el ADR (auditoría 22/10).
import { isBymaHolding } from './valuation'
import { isCrypto } from './crypto'
import { cedearRatio } from './cedearRatio'

/** Lote por lote: ¿este lote es una acción argentina? (la Cartera separa GGAL
 *  de IOL del ADR de Schwab en dos lecturas, una por marca). */
export function esLoteLocal(p) {
  if (!p || p.is_cash || cedearRatio(p.asset) || isCrypto(p.asset)) return false
  return p.asset_type !== 'CEDEAR' && isBymaHolding(p)
}

export function esAccionLocal(asset, lots) {
  if (!lots.length || cedearRatio(asset) || isCrypto(asset)) return false
  return lots.every(esLoteLocal)
}
