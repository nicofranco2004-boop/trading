// bondCashflowFx.js — sugerir el monto de una cobranza de bono en la moneda del broker.
// ════════════════════════════════════════════════════════════════════════════
// EL PROBLEMA
// El cronograma de un bono da el pago en la moneda del BONO (un AL30 paga USD).
// El modal pide el monto en la moneda del BROKER. Cuando no coinciden — un bono en
// dólares en una cuenta que acredita pesos, el caso argentino típico — el usuario
// tenía que ir a buscar a mano el tipo de cambio del día de la liquidación.
//
// Este helper hace esa cuenta con el dólar de la FECHA DEL PAGO (no el de hoy).
//
// POR QUÉ ES UN HELPER PURO
// El modal no se puede testear: `vite.config.js` fija `environment: 'node'` y el
// proyecto no tiene jsdom ni testing-library. Toda la lógica vive acá, con el TC
// inyectado, así que se testea sin React.
//
// LO QUE ESTE NÚMERO NO ES
// Es el BRUTO teórico convertido a un dólar de referencia. El broker liquida al SUYO
// y además retiene. Por eso el resultado se ofrece como sugerencia editable y nunca
// como valor por defecto del campo.

// Dos monedas son "la misma plata" a efectos de conversión: USD y USDT valen 1 USD,
// la diferencia es semántica. Mismo criterio que `sameCurrency` del banner de
// cobranzas pendientes — si divergen, el modal sugeriría en casos que el banner
// manda al atajo de 1 click, y viceversa.
export function sameCurrency(a, b) {
  if (!a || !b) return false
  const norm = c => (c === 'USDT' ? 'USD' : c)
  return norm(a) === norm(b)
}

// Sugiere el monto en la moneda del broker.
//
// Params:
//   theoreticalAmount — pago teórico del cronograma, ya escalado a los nominales
//                       del lote, en la moneda del BONO.
//   bondCurrency      — 'USD' | 'ARS' (de bondMeta; null si el ticker no está en el catálogo)
//   brokerCurrency    — 'ARS' | 'USD' | 'USDT'
//   paymentDate       — fecha ISO del pago (la del cronograma, no la de hoy)
//   fx                — { tc, source, asOf } de useFxHistory.getMepDetail(paymentDate).
//                       `tc` en NATIVA POR USD (ej: 1250 ARS/USD).
//
// Devuelve:
//   applies  — si hay conversión que hacer (monedas distintas y datos suficientes)
//   amount   — el monto convertido, o null si no se puede saber
//   tc/asOf/source — la traza de con qué se convirtió
//   stale    — el TC es de un día ANTERIOR al del pago (fin de semana, feriado, o
//              una fila sin MEP). El usuario tiene que poder verlo.
//   operacion — 'multiplicar' | 'dividir', para que la UI explique la cuenta real
//   fxToUsdForRow — el `fx_to_usd` que le corresponde a la FILA que se va a guardar,
//              que NO siempre es `tc`. La fila se guarda en la moneda del BROKER:
//                • broker ARS → el monto queda en pesos → fx_to_usd = tc (ARS/USD)
//                • broker USD → el monto queda en dólares → fx_to_usd = 1
//              Sellar `tc` en una fila que ya está en dólares la deja diciendo que
//              esos 100 dólares son 100/1250 = US$0,08.
//   faltaTc  — hay conversión pendiente pero no tenemos dólar para esa fecha. Se
//              distingue de "no hay monto teórico" para que la UI no le eche la
//              culpa al dólar cuando lo que falta es el cronograma.
export function suggestBrokerAmount({
  theoreticalAmount,
  bondCurrency,
  brokerCurrency,
  paymentDate,
  fx,
} = {}) {
  const nada = {
    applies: false, amount: null, tc: null, asOf: null, source: null,
    stale: false, operacion: null, fxToUsdForRow: null, faltaTc: false,
  }

  // Sin catálogo del bono no sabemos en qué moneda paga: no inventamos.
  if (!bondCurrency || !brokerCurrency) return nada
  if (sameCurrency(bondCurrency, brokerCurrency)) return nada

  // Par que no manejamos (dos monedas distintas y ninguna es ARS).
  const haciaPesos = !isArsLike(bondCurrency) && isArsLike(brokerCurrency)
  const haciaDolares = isArsLike(bondCurrency) && !isArsLike(brokerCurrency)
  if (!haciaPesos && !haciaDolares) return nada

  // Hay conversión pendiente. Lo que sigue puede faltar, pero `applies` ya es true:
  // el modal tiene que saber que este campo NO se pre-llena con el teórico.
  if (!(theoreticalAmount > 0)) return { ...nada, applies: true }

  const tc = fx?.tc
  // Sin TC no se sugiere. Deliberado: caer al dólar de hoy daría un número
  // plausible y equivocado, que es peor que un campo vacío.
  if (!(tc > 0)) return { ...nada, applies: true, faltaTc: true }

  const asOf = fx?.asOf || null
  const traza = { tc, asOf, source: fx?.source || null, stale: !!(asOf && paymentDate && asOf !== paymentDate), faltaTc: false }

  // Bono en dólares, broker en pesos → multiplico. Es el caso argentino típico.
  // La fila queda EN PESOS, así que su fx_to_usd es el TC.
  if (haciaPesos) {
    return {
      applies: true, amount: round2(theoreticalAmount * tc),
      operacion: 'multiplicar', fxToUsdForRow: tc, ...traza,
    }
  }
  // Bono en pesos, broker en dólares (un TZX26 en una cuenta USD) → divido.
  // La fila queda EN DÓLARES: su fx_to_usd es 1, NO el TC — sellar el TC acá haría
  // que todo lector que divida muestre el cupón ~1250 veces más chico.
  return {
    applies: true, amount: round2(theoreticalAmount / tc),
    operacion: 'dividir', fxToUsdForRow: 1, ...traza,
  }
}

function isArsLike(c) {
  return c === 'ARS'
}

function round2(n) {
  return Math.round(n * 100) / 100
}
