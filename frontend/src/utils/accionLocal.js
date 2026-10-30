// accionLocal — ¿es una acción argentina (no un CEDEAR)?
// ═══════════════════════════════════════════════════════════════════════════
// Entonces su lectura técnica en dólares es su precio de BYMA ÷ el MEP, no el
// ADR de Nueva York (GGAL "de afuera" son 10 acciones, y su precio no es el de
// tu acción). Lo decide lo que TENÉS: si todos tus lotes de ese activo son de
// BYMA (y no es CEDEAR ni cripto). Sin lotes, no: la ficha muestra el ADR. Es la
// marca `local` que el servidor recibe en /api/tecnico y en /api/tecnico/en-fechas.
//
// Una sola regla para la ficha (AssetDetail → GET /api/tecnico?local=1), la
// radiografía de la Cartera (utils/radiografia.js, lote por lote), las alertas
// técnicas que se arman desde el buscador de Alertas y Movimientos (el diario de
// operaciones y la tesis: `esAccionLocal(op.asset, [op])`; una operación trae
// broker, asset y currency, que es lo que mira `isBymaHolding`). Si cada una
// decidiera por su lado, el aviso miraba la acción de BYMA y el botón del mail
// abría la ficha con el ADR (auditoría 22/10).
//
// «Es CEDEAR» = la lista de CEDEARs de la app (`CEDEAR_TICKERS`, con el código
// de especie: SI = SID), la MISMA que usa el servidor (accion_local.py, que no
// depende de data912). Antes se preguntaba a la tabla de RATIOS: BLK, NET, DDOG,
// TTWO, GME y AMC son CEDEARs sin ratio conocido y salían «acción argentina»
// (auditoría A 29/10, P1). Los casos viven en fixtures/accionLocal.json y los
// leen las pruebas de los dos lados.
import { isBymaHolding } from './valuation'
import { isCrypto } from './crypto'
import { CEDEAR_TICKERS, cedearEspecieBase, inferType } from './tickers'

/** ¿Este código es un CEDEAR de la lista de la app? */
export function esCedear(asset) {
  return CEDEAR_TICKERS.has(cedearEspecieBase(asset))
}

/** Lote por lote: ¿este lote es una acción argentina? (la Cartera separa GGAL
 *  de IOL del ADR de Schwab en dos lecturas, una por marca). */
export function esLoteLocal(p) {
  if (!p || p.is_cash || esCedear(p.asset) || isCrypto(p.asset)) return false
  return p.asset_type !== 'CEDEAR' && isBymaHolding(p)
}

export function esAccionLocal(asset, lots) {
  if (!lots.length || esCedear(asset) || isCrypto(asset)) return false
  return lots.every(esLoteLocal)
}

/** Los `asset_type` que dicen «acción argentina» (los demás dicen otra cosa). */
export const TIPOS_ACCION_AR = new Set(['ACCION', 'STOCK_AR'])

/**
 * Lo que NO tenés (un símbolo de la watchlist, el de una ficha sin lotes, el de
 * una alerta técnica creada desde el buscador): ¿es una acción argentina? Del
 * panel argentino (con o sin «.BA»: «GGAL» lo guarda el buscador del inicio,
 * «GGAL.BA» la estrella de la ficha). `tipo`: el `asset_type` de la fila, si lo
 * trae; uno que no es de acción argentina manda («AGRO» de tipo STOCK es
 * Adecoagro de Nueva York). LA regla de lo que seguís: la usan Tu lista
 * (`lecturaDeSeguido`), la ficha (`miradaSinTenencia`) y las alertas técnicas
 * (`activoTecnico`). Espejo de backend/accion_local.seguido.
 */
export function esLocalSinTenencia(simbolo, tipo = null) {
  const s = String(simbolo || '').trim().toUpperCase()
  const t = String(tipo || '').trim().toUpperCase()
  return inferType(s) === 'stock_ar' && (!t || TIPOS_ACCION_AR.has(t))
}
