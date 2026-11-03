/**
 * opcionesDeVenta — qué se le ofrece vender, y qué lotes cierra cada venta.
 *
 * LA LISTA. Una opción por (cuenta, activo, moneda): "NFLX · Cocos · en pesos" y
 * "NFLX · Cocos · en dólares", no "NFLX · Cocos · ARS" y "NFLX · Cocos · USD" como
 * si fueran dos brokers. Y una sola fila aunque haya varias compras: antes la
 * lista de escritorio mostraba un renglón por LOTE (NFLX dos veces, INTC dos
 * veces) y el usuario tenía que adivinar cuál vender — cuando la venta igual
 * consume por orden de compra, elija el renglón que elija.
 *
 * LOS LOTES (FIFO). `lotesDeLaVenta` es el espejo de lo que hace el servidor en
 * `POST /api/positions/sell` (main.py, sell_position_fifo):
 *   1. los lotes del activo en TODA la cuenta (`broker_pair`: Cocos y Cocos · USD),
 *   2. sólo los de la moneda de la venta (`behavioral._native_ccy` ↔ `sellCurrency`),
 *   3. del más viejo al más nuevo (`entry_date`, sin fecha al final; empate: id).
 * Antes la ventana de venta miraba sólo el broker elegido y SIN filtrar moneda:
 * con AAPL en pesos y en dólares en la misma cuenta, mostraba la suma de los dos
 * como disponible y cerraba en la vista previa el lote de la otra moneda — el
 * servidor después hacía otra cosa. Lo que se ve tiene que ser lo que pasa.
 */
import { sellCurrency } from './valuation'
import { cuentaDe, admiteDosMonedas, pataDeLaMoneda } from './pataDeLaMoneda'

const _broker = (brokers, name) => (brokers || []).find(b => b.name === name)

/** La moneda de un lote para vender: la misma regla que el servidor. */
export function monedaDelLote(p, brokers) {
  return sellCurrency(p, _broker(brokers, p?.broker))
}

/** Los lotes que consume una venta de `asset` en `currency` hecha en `broker`, en orden FIFO. */
export function lotesDeLaVenta(positions, brokers, { broker, asset, currency }) {
  const cuenta = cuentaDe(broker, brokers)
  const ccy = String(currency || '').toUpperCase() === 'ARS' ? 'ARS' : 'USD'
  return (positions || [])
    .filter(p => !p.is_cash && p.asset === asset && (p.quantity || 0) > 0
      && cuentaDe(p.broker, brokers) === cuenta
      && monedaDelLote(p, brokers) === ccy)
    .sort((a, b) => (a.entry_date || '9999-12-31').localeCompare(b.entry_date || '9999-12-31')
      || (a.id || 0) - (b.id || 0))
}

/**
 * Una opción por (cuenta, activo, moneda).
 * @returns {Array<{key, asset, cuenta, moneda, dosMonedas, broker, lots, qty, invested, valueUsd}>}
 *   `broker`: a dónde se manda la venta — la pata de esa moneda (la caja donde
 *   entra lo cobrado). El servidor busca los lotes en toda la cuenta igual.
 */
export function opcionesDeVenta(positions, brokers) {
  const porClave = new Map()
  for (const p of positions || []) {
    if (!p || p.is_cash || !((p.quantity || 0) > 0)) continue
    const moneda = monedaDelLote(p, brokers)
    const cuenta = cuentaDe(p.broker, brokers)
    const key = `${cuenta}\u0000${p.asset}\u0000${moneda}`
    let o = porClave.get(key)
    if (!o) {
      const dos = admiteDosMonedas(p.broker, brokers)
      o = {
        key, asset: p.asset, cuenta, moneda, dosMonedas: dos,
        broker: dos ? pataDeLaMoneda(brokers, cuenta, moneda) : p.broker,
        lots: [], qty: 0, invested: 0, valueUsd: 0,
      }
      porClave.set(key, o)
    }
    o.lots.push(p)
    o.qty += p.quantity || 0
    o.invested += p.invested || 0
    o.valueUsd += p.valueUsd || 0
  }
  return [...porClave.values()]
}

/** "Cocos Capital · en dólares" (o sólo "IBKR" si la cuenta tiene una moneda). */
export function etiquetaDeVenta(o) {
  if (!o) return ''
  return o.dosMonedas ? `${o.cuenta} · en ${o.moneda === 'ARS' ? 'pesos' : 'dólares'}` : o.cuenta
}

/**
 * El resultado en DÓLARES de un pedazo de venta (un lote), para la vista previa
 * del formulario «Vender». Espejo de lo que anota el servidor: los tres motores
 * de venta llaman a `resultado_dual.resultado_en_dolares` (backend).
 *
 *   · venta en dólares: cobrado − costo.
 *   · venta en pesos, cuenta con `cadaPuntaASuDolar` (v2): lo cobrado al dólar
 *     de la venta menos el costo al dólar de compra del lote — el mismo con que
 *     Cartera muestra su costo en dólares. GGAL de $450.000 (dólar 1.000) a
 *     $690.000 (dólar 1.500) = US$ 460 − US$ 450 = +US$ 10.
 *   · venta en pesos sin dólar de compra, o cuenta v1: la ganancia en pesos ÷
 *     el dólar de la venta (+US$ 160 en el mismo ejemplo), como el servidor.
 *
 * `cadaPuntaASuDolar` lo dice el servidor (GET /api/positions/regla-de-venta):
 * depende de la versión de dólar de la cuenta, que la pantalla no conoce.
 */
export function resultadoUsdDelPedazo({ cobrado, costo, enPesos, tcVenta, tcCompra, cadaPuntaASuDolar }) {
  if (!enPesos) return cobrado - costo
  if (cadaPuntaASuDolar && tcCompra > 0 && tcVenta > 0) return cobrado / tcVenta - costo / tcCompra
  return (cobrado - costo) / tcVenta
}

/**
 * vistaPreviaDeLaVenta — la vista previa FIFO del formulario «Vender», con las mismas
 * cuentas que el servidor (`main.sell_position_fifo`): una fila por lote que la venta
 * toca, con su resultado en dólares. Es una función pura para poder probarla contra los
 * mismos casos que el servidor.
 *
 *   · costo del lote = `invested` si lo tiene (si no, precio × cantidad: `fx.costo_del_lote`)
 *     + su comisión de compra, prorrateado por lo que se consume.
 *   · lo cobrado = precio × cantidad − la comisión de venta prorrateada entre los lotes.
 *   · dólar de compra = el `tc_compra` del lote o, si no lo tiene, el de su fecha
 *     (`tcCompraDe(fecha)`); dólar de venta = el que escribió el usuario o, si lo dejó
 *     vacío, el de la fecha de la venta (el que usa el servidor).
 *
 * `cadaPuntaASuDolar` es lo que dice el servidor de ESTA cuenta (GET /positions/regla-de-venta).
 */
export function vistaPreviaDeLaVenta({ lots, quantity, price, commission = 0, enPesos, tcVenta,
  tcCompraDe, cadaPuntaASuDolar }) {
  let restante = quantity
  const filas = []
  for (const p of (lots || [])) {
    if (restante <= 1e-9) break
    const posQty = p.quantity || 0
    const take = Math.min(restante, posQty)
    if (take <= 0) continue
    const ratio = take / posQty
    const costoDelLote = p.invested != null ? Number(p.invested) : ((p.buy_price || 0) * posQty)
    const costo = (costoDelLote + (p.commissions || 0)) * ratio
    const cobrado = price * take - (quantity > 0 ? commission * (take / quantity) : 0)
    const tcCompra = p.tc_compra > 0 ? p.tc_compra
      : (p.entry_date && tcCompraDe ? tcCompraDe(p.entry_date) : null)
    filas.push({
      lot_id: p.id,
      entry_date: p.entry_date,
      take,
      pos_qty: p.quantity,
      buy_price: p.buy_price,
      pnl_usd: resultadoUsdDelPedazo({ cobrado, costo, enPesos, tcVenta, tcCompra, cadaPuntaASuDolar }),
      partial: take < p.quantity,
    })
    restante -= take
  }
  return { filas, total: filas.reduce((a, f) => a + f.pnl_usd, 0) }
}
