// variacionDelDia — cuánto se movió hoy un lote: (precio de ahora − cierre de
// la rueda anterior) × cantidad, y el % de ese movimiento.
// ═══════════════════════════════════════════════════════════════════════════
// Es la columna «Var. día» de la Cartera de la compu. Vivía adentro de
// Positions.jsx (`dayVarOf` + `dvFor`); se mudó acá sin cambiarle una cuenta
// para que el mapa de calor del Dashboard pinte cada cuadro con el MISMO número
// que muestra la fila de la Cartera. Usa el mismo precio que la fila, así los
// números reconcilian.
//
// ⚠️ La Cartera del celular (PositionsMobile.jsx) tiene su propia copia, metida
// adentro de su valuación lote por lote, con dos casos más (la cripto en dólares
// de una cuenta en pesos y el lote en dólares de un broker en pesos con precio
// en `.BA`). No se unificó con esta: anotado para la ronda de auditorías. El
// control del precio no confiable sí está en las dos.

import { priceSymbol, isArUsdBroker, costInPesos, costInUsd, trustMktValue } from './valuation'
import { isCrypto, cryptoBrokerFactor } from './crypto'

// El cálculo de mercado puro. null cuando es efectivo, tiene precio manual (el
// precio a mano no sale de la misma fuente que el cierre anterior), falta el
// cierre anterior (un símbolo sin cobertura, como varios bonos argentinos) o
// todavía no llegó el precio de ahora. (Y, antes de llegar acá, si la valuación
// no confía en el precio: ver `precioConfiable`.) `base` = lo que valía el lote al cierre
// anterior (cierre × cantidad), en la moneda de `amount`: con él se suma el %
// de varios lotes.
function deMercado(p, prev, currentPrice) {
  if (p.is_cash || p.price_override) return null
  if (prev == null || !(prev > 0) || currentPrice == null) return null
  const perUnit = currentPrice - prev
  const qty = p.quantity || 0
  return { amount: perUnit * qty, pct: perUnit / prev, base: prev * qty }
}

// ¿La valuación confía en este precio? Es `trustMktValue`, el mismo control con
// que la Cartera y el Dashboard deciden si un lote vale su precio o su costo
// (un bono con el costo cargado por lámina de 100 y el precio por 1, por
// ejemplo). Si no confía, el lote se muestra al costo, y entonces su movimiento
// del día tampoco existe: antes la columna publicaba el movimiento de un precio
// que la fila de al lado había descartado (AL30 de la cuenta de prueba: «vale»
// USD 89 al costo y «se movió» −USD 217 en el día). La Cartera del celular ya
// lo cortaba así (`priceTrusted`). Precio y costo se comparan en la misma moneda.
function precioConfiable(p, isARS, symKey, curPrice, tcCedear) {
  const costoEnPesos = isARS ? !costInUsd(p) : costInPesos(p)
  const precioEnPesos = symKey.endsWith('.BA') || (symKey.startsWith('FCI:') && costoEnPesos)
  let costo = (p.invested || 0) + (p.commissions || 0)
  if (costoEnPesos !== precioEnPesos) costo = costoEnPesos ? costo / tcCedear : costo * tcCedear
  return trustMktValue(curPrice * (p.quantity || 0), costo, p.asset_type, false)
}

const escalar = (dv, k) => ({ amount: dv.amount * k, pct: dv.pct, base: dv.base * k })

/**
 * La variación del día de un lote, CEDEAR-aware. Para un CEDEAR (o un papel de
 * BYMA, o un lote con costo en pesos) en un broker en dólares, se mide sobre el
 * precio LOCAL (`.BA`, en pesos) — el mismo símbolo para el precio de ahora y
 * el cierre — y el monto pasa a dólares por el MEP. Para el resto, el símbolo
 * nativo del broker (en pesos → `.BA`, en dólares → el ticker de afuera).
 *
 * Moneda del resultado: en un broker en PESOS (`isARS`), `amount` va en pesos;
 * en uno en dólares, en dólares. El % no depende de la moneda.
 *
 * @param p        el lote (una fila de /positions)
 * @param isARS    ¿el broker del lote es en pesos?
 * @param ctx      { prices, prevClose, tcCedear, tcCripto, exchangeBrokers: Set }
 * @returns {{ amount, pct, base } | null}
 */
export function variacionDelDia(p, isARS, { prices, prevClose, tcCedear, tcCripto, exchangeBrokers }) {
  // costInPesos: lote en ARS en broker USD (IOL sin sibling) — se valúa por su
  // .BA (calcUSDT/pesoLotUsd), así que la Var. día usa el MISMO símbolo local.
  // Sin esto caía a priceSymbol(asset, false) → 'GGAL' (el ADR): si el ADR no
  // estaba priceado daba '—' garantizado; si SÍ estaba (otra posición lo trae),
  // computaba perUnit del ADR × nominales locales → monto ×ratio inflado.
  const local = !isARS && !isCrypto(p.asset) && (p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker) || costInPesos(p))
  const symKey = local ? priceSymbol(p.asset, true, p.asset_type) : priceSymbol(p.asset, isARS)
  const curPrice = p.price_override ?? prices[symKey]
  if (curPrice != null && !p.price_override && !p.is_cash && !precioConfiable(p, isARS, symKey, curPrice, tcCedear)) return null
  const dv = deMercado(p, prevClose[symKey], curPrice)
  if (!dv) return dv
  if (local) return escalar(dv, 1 / tcCedear)
  // Factor cripto: SÓLO en el riel en dólares, donde el precio es el spot. En el
  // riel en PESOS el '<c>.BA' ya trae el premium adentro (spot × dólar-cripto), y
  // multiplicarlo de nuevo lo duplicaba: el monto salía ~4% más grande que el de
  // mobile, que ya usaba `isAR ? 1 : …`. Hoy, en dólares, el factor vale 1 (la
  // cuenta en dólares no lleva premium); queda por si cambia la regla. El % es
  // invariante.
  const f = isARS ? 1 : cryptoBrokerFactor(p.asset, exchangeBrokers.has(p.broker), p.price_override != null, tcCripto, tcCedear, 'USD')
  if (f !== 1) return escalar(dv, f)
  return dv
}

/** La misma variación, siempre en dólares: lo de un broker en pesos pasa por el
 *  MEP, como suma la Cartera la variación de una cuenta con dos patas. */
export function variacionDelDiaUsd(p, isARS, ctx) {
  const dv = variacionDelDia(p, isARS, ctx)
  if (!dv || !isARS) return dv
  return escalar(dv, 1 / ctx.tcCedear)
}
