// accionLocal — ¿es una acción ARGENTINA (no un CEDEAR)?
// ═══════════════════════════════════════════════════════════════════════════
// Entonces su lectura técnica en dólares es su precio de BYMA ÷ el MEP, no el
// ADR de Nueva York (GGAL "de afuera" son 10 acciones, y su precio no es el de
// tu acción). Es la marca `local` que el servidor recibe en /api/tecnico y en
// /api/tecnico/en-fechas.
//
// Vivía adentro de pages/AssetDetail.jsx; se mudó acá cuando Movimientos (el
// diario de operaciones y la tesis) necesitó la MISMA regla para una operación
// cerrada: `esAccionLocal(op.asset, [op])` (una operación trae broker, asset y
// currency, que es lo que mira `isBymaHolding`).

import { isBymaHolding } from './valuation'
import { isCrypto } from './crypto'
import { cedearRatio } from './cedearRatio'

export function esAccionLocal(asset, lots) {
  if (!lots.length || cedearRatio(asset) || isCrypto(asset)) return false
  return lots.every(p => p.asset_type !== 'CEDEAR' && isBymaHolding(p))
}
