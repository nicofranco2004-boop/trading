// realizadoEnPesos.js
// ───────────────────
// El P&L REALIZADO de un mes, un año o un período, en pesos.
//
// El servidor lo manda en dólares (`realized_pnl` / `pnl_realized`) y, aparte, la parte que
// SÍ tiene pesos de verdad (`realized_ars`, con `realized_ars_cubre_usd` = el realizado en
// dólares de esas mismas operaciones y `realized_ars_valuado` = si alguna fue una venta en
// dólares). La cuenta de esos tres números vive en backend/resultado_dual.py
// (`resultado_en_pesos` / `realizado_en_pesos`), la MISMA de Movimientos y de «Última op
// cerrada»: Reportes, el Resumen mensual y el Dashboard no la repiten, la usan.
//
// POR QUÉ NO ALCANZA CON `dólares × el dólar del cierre`. GGAL comprada a $4.500 con el
// dólar a 1.000 y vendida a $6.900 con el dólar a 1.500 dejó +$240.000 (y el broker dice
// eso), pero en dólares son +US$10, y US$10 × 1.500 son $15.000.
//
// LA CUENTA: lo exacto que mandó el servidor + sólo lo que NO tiene pesos (dividendos en
// dólares, lo cargado a mano en /mensual, ventas viejas en dólares) convertido al dólar `fx`
// del período, como siempre. Lo convertido se DICE (`notaDelRealizado`), no se disfraza de
// exacto.

const num = (v) => (v == null || v === '' || !Number.isFinite(+v) ? null : +v)

const UMBRAL_RESTO_USD = 1   // menos de un dólar convertido no vale un cartel

/**
 * @param {object} a
 * @param {number|null} a.usd        el realizado en dólares (todo el período)
 * @param {number|null} a.ars        los pesos exactos que mandó el servidor (null = no mandó)
 * @param {number|null} a.cubreUsd   los dólares de las operaciones que tienen esos pesos
 * @param {number|null} a.fx         el dólar con que se convierte lo que no tiene pesos
 * @returns {{ monto: number|null, restoUsd: number }}
 *   `restoUsd` = los dólares que se convirtieron con `fx` (no son pesos de verdad).
 */
export function realizadoEnPesos({ usd, ars, cubreUsd, fx } = {}) {
  const u = num(usd) ?? 0
  const f = num(fx)
  const a = num(ars)
  // Sin la cuenta del servidor (respuesta de una versión anterior): todo convertido, como antes.
  if (a == null) return { monto: f > 0 ? u * f : null, restoUsd: u }
  const resto = u - (num(cubreUsd) ?? 0)
  // Sin dólar con el que convertir el resto no se inventa un número.
  if (!(f > 0)) return { monto: Math.abs(resto) < 0.005 ? a : null, restoUsd: resto }
  return { monto: a + resto * f, restoUsd: resto }
}

/**
 * El realizado en pesos de UNA FILA de /api/monthly (un mes de un broker), con el dólar `fx` de
 * ese mes. Una sola traducción de los nombres del servidor: el Dashboard y el Resumen mensual
 * no la escriben cada uno.
 */
export function realizadoDeLaFilaMensual(m, fx) {
  return realizadoEnPesos({
    usd: m?.pnl_realized, ars: m?.realized_ars, cubreUsd: m?.realized_ars_cubre_usd, fx,
  })
}

/**
 * Junta el realizado en pesos de varios meses, cada uno con SU dólar (convertir y después sumar).
 * `restoUsd` es la suma de los valores ABSOLUTOS de los restos (lo que se convirtió, para el
 * cartel): con signo, +US$ 500 y −US$ 500 en meses distintos se cancelan y el cartel desaparece.
 * @param {Array} filas  filas de /api/monthly
 * @param {(fila:object)=>number} fxDelMes  el dólar con que se convierte el resto de esa fila
 * @returns {{ monto:number, restoUsd:number, valuado:boolean }}
 */
export function sumarRealizadoMeses(filas, fxDelMes) {
  let monto = 0, restoUsd = 0, valuado = false
  for (const m of filas || []) {
    const r = realizadoDeLaFilaMensual(m, fxDelMes(m))
    monto += r.monto || 0
    restoUsd += Math.abs(r.restoUsd)
    valuado = valuado || !!m.realized_ars_valuado
  }
  return { monto, restoUsd, valuado }
}

/**
 * La aclaración para la pantalla, o null si todo es exacto.
 * @param {object} a
 * @param {number} a.restoUsd  lo que devolvió `realizadoEnPesos`. Si se junta de varios meses,
 *                             sumar los VALORES ABSOLUTOS (`Math.abs(r.restoUsd)`): con signo,
 *                             un mes de +US$ 500 y otro de −US$ 500 se cancelan y el cartel
 *                             desaparece aunque todo el monto sea convertido.
 * @param {boolean} [a.valuado] el servidor avisó que hubo ventas en dólares o lotes pagados en
 *                              dólares (sus pesos son los dólares a cada dólar de su fecha, no
 *                              pesos de verdad)
 * @param {string} [a.dolar]    cuál dólar se usó para el resto ('del cierre', 'del mes'…)
 */
export function notaDelRealizado({ restoUsd, valuado = false, dolar = 'del cierre' } = {}) {
  const partes = []
  // Misma frase que el tooltip de Movimientos (TradesTable): vale para una venta en dólares y para
  // una compra en dólares vendida en pesos.
  if (valuado) partes.push('ventas o compras en dólares valuadas al dólar de cada fecha')
  const r = num(restoUsd)
  if (r != null && Math.abs(r) >= UMBRAL_RESTO_USD) {
    partes.push(`incluye US$ ${Math.round(Math.abs(r)).toLocaleString('es-AR')} convertidos al dólar ${dolar}`)
  }
  return partes.length ? partes.join(' · ') : null
}
