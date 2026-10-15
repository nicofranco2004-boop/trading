import { parseNum } from './format'

// ── Lo que se MANDA sale de la misma lectura que lo que se VE ────────────────
//
// Los modales de venta y de conversión son de texto libre desde 2026-09-15
// (56910e7f): se puede escribir "10.820,00". La pantalla los leía con parseNum
// y los `confirm*` de escritorio y de celular con `+campo`, que no entiende la
// coma ni el punto de miles:
//   "10.820,00" → NaN → viaja como null → el servidor rechaza la venta
//   "10.820"    → 10.82 → se guarda una venta a la milésima del precio, sin error
//   "1.000"     → 1     → se vende una unidad en vez de mil
// En la conversión era peor: el campo espejo lo escribe el sistema con
// separadores ("1.000"), así que bastaba con no tocarlo para mandar US$ 1.
//
// Estas funciones son la ÚNICA lectura de esos formularios: el modal las usa
// para dibujar y los dos `confirm*` para armar lo que se manda.

const finito = (v) => {
  const n = parseNum(v)
  return Number.isFinite(n) ? n : null
}

/** Los números del formulario de venta tal como los entiende la pantalla (null = vacío o ilegible). */
export function leerVenta(form) {
  return {
    quantity: finito(form.quantity),
    exit_price: finito(form.exit_price),
    commissions: finito(form.commissions),
    tc_venta: finito(form.tc_venta),
  }
}

/** Cuerpo de POST /positions/sell, o `{ error }` con el texto para el usuario. */
export function cuerpoDeVenta(form) {
  const n = leerVenta(form)
  if (n.quantity == null || n.quantity <= 0) return { error: 'La cantidad ingresada no es válida.' }
  if (n.exit_price == null || n.exit_price < 0) return { error: 'El precio ingresado no es válido.' }
  const comisionEscrita = String(form.commissions ?? '').trim() !== ''
  if (comisionEscrita && (n.commissions == null || n.commissions < 0)) {
    return { error: 'La comisión ingresada no es válida.' }
  }
  const enPesos = form.currency === 'ARS'
  const tcEscrito = enPesos && String(form.tc_venta ?? '').trim() !== ''
  if (tcEscrito && (n.tc_venta == null || n.tc_venta <= 0)) {
    return { error: 'El tipo de cambio ingresado no es válido.' }
  }
  return {
    body: {
      broker: form.broker,
      asset: form.asset,
      quantity: n.quantity,
      exit_price: n.exit_price,
      date: form.date,
      commissions: n.commissions ?? 0,
      // Moneda de la venta → el FIFO consume sólo lotes de esa moneda.
      currency: enPesos ? 'ARS' : 'USD',
      ...(tcEscrito ? { tc_venta: n.tc_venta } : {}),
    },
  }
}

/** Los números del formulario de conversión ARS ↔ USD (null = vacío o ilegible). */
export function leerConversion(form) {
  return {
    ars_amount: finito(form.ars_amount),
    usd_amount: finito(form.usd_amount),
    tc: finito(form.tc),
  }
}

/** Cuerpo de POST /conversions, o `{ error }`. El saldo lo valida quien llama. */
export function cuerpoDeConversion(form) {
  const n = leerConversion(form)
  if (!(n.ars_amount > 0)) return { error: 'Ingresá un monto ARS válido.' }
  if (!(n.usd_amount > 0)) return { error: 'Ingresá un monto USD válido.' }
  if (!(n.tc > 0)) return { error: 'Ingresá un tipo de cambio válido.' }
  return {
    body: {
      from_broker: form.from_broker,
      direction: form.direction,
      ars_amount: n.ars_amount,
      usd_amount: n.usd_amount,
      tc: n.tc,
      kind: form.kind,
      date: form.date || null,
    },
  }
}
