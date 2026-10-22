/**
 * pataDeLaMoneda — el usuario elige "Cocos" y una moneda; los dólares de Cocos
 * viven en su sub-broker "Cocos · USD".
 *
 * Cada broker tiene UNA caja de efectivo con UNA moneda. Los dólares de una
 * cuenta argentina viven en el sub-broker `parent_broker_id → padre ARS` (lo
 * crea el importador o la primera compra en dólares). Antes el usuario tenía que
 * elegir ese sub-broker a mano en cada lista; ahora elige la cuenta y la moneda,
 * y el backend (`_pata_de_la_moneda` en main.py) decide dónde va. Este archivo
 * es el espejo de PANTALLA: qué brokers se ofrecen y de qué caja sale el saldo
 * que se muestra. NO crea nada: si el sub-broker todavía no existe, se manda el
 * padre con la moneda y el backend lo crea.
 *
 * Igual que brokerAccounts.js: el par se arma por `parent_broker_id`, nunca por
 * el sufijo " · USD" del nombre.
 */

const _ccy = b => (b?.currency || '').toUpperCase()

/** ¿Es la pata en dólares de una cuenta argentina? */
export function esPataDolar(b, brokers) {
  if (!b || b.parent_broker_id == null || _ccy(b) === 'ARS') return false
  const padre = (brokers || []).find(x => x.id === b.parent_broker_id)
  return !!padre && _ccy(padre) === 'ARS'
}

/** Los brokers que se le ofrecen al usuario: sin las patas en dólares. */
export function brokersParaElegir(brokers) {
  return (brokers || []).filter(b => !esPataDolar(b, brokers))
}

/** ¿En este broker se puede elegir pesos o dólares? (cuenta argentina) */
export function admiteDosMonedas(brokerName, brokers) {
  const b = (brokers || []).find(x => x.name === brokerName)
  return !!b && (_ccy(b) === 'ARS' || esPataDolar(b, brokers))
}

/**
 * La cuenta (el padre) de un broker: el mismo broker si no tiene padre. Mira SÓLO
 * `parent_broker_id`, igual que `broker_pair` del servidor (que decide qué lotes
 * entran en una venta): si se exigiera además que el hijo sea en dólares, un hijo
 * raro (en pesos, o de un padre que no es en pesos) quedaba fuera de la cuenta acá
 * y adentro allá, y la vista previa de la venta no mostraba lo que cerraba.
 */
export function cuentaDe(brokerName, brokers) {
  const b = (brokers || []).find(x => x.name === brokerName)
  if (!b || b.parent_broker_id == null) return brokerName
  return (brokers || []).find(x => x.id === b.parent_broker_id)?.name || brokerName
}

/**
 * El broker real donde vive `moneda` en la cuenta de `brokerName`, si ya existe.
 * Si la pata en dólares todavía no existe devuelve el padre: el backend la crea
 * al recibir el pedido con la moneda.
 */
export function pataDeLaMoneda(brokers, brokerName, moneda) {
  const lista = brokers || []
  const cuenta = cuentaDe(brokerName, lista)
  if (!moneda) return brokerName
  // Si lo pedido YA es una pata en dólares y se piden dólares, es ésa: desde la
  // fila de efectivo de una pata, el depósito va a ESA caja (si una cuenta
  // tuviera dos patas en dólares, buscar "la" pata elegía la primera).
  if (String(moneda).toUpperCase() !== 'ARS'
      && esPataDolar(lista.find(x => x.name === brokerName), lista)) return brokerName
  const padre = lista.find(x => x.name === cuenta)
  if (!padre || _ccy(padre) !== 'ARS') return brokerName
  if (String(moneda).toUpperCase() === 'ARS') return padre.name
  return lista.find(x => x.parent_broker_id === padre.id && esPataDolar(x, lista))?.name || padre.name
}

/**
 * El formulario del depósito/retiro, ya resuelto: a qué broker real va, en qué
 * moneda se muestra y cuánto hay disponible en ESA caja (el tope del retiro).
 * Lo usan escritorio y celular, así las dos pantallas mandan lo mismo.
 */
export function formularioDeCaja({ brokers, positions, brokerName, moneda, direction, date }) {
  const lista = brokers || []
  const dos = admiteDosMonedas(brokerName, lista)
  const pata = dos ? pataDeLaMoneda(lista, brokerName, moneda || 'ARS') : brokerName
  const b = lista.find(x => x.name === brokerName)
  const enDolares = dos ? String(moneda || 'ARS').toUpperCase() !== 'ARS' : _ccy(b) !== 'ARS'
  // Si la pata pedida todavía no existe (dólares en una cuenta sin sub-broker),
  // `pata` es el padre: el disponible en dólares es 0, no el de la caja de pesos.
  const existe = !enDolares || !dos || esPataDolar(lista.find(x => x.name === pata), lista)
  const caja = existe ? (positions || []).find(p => p.broker === pata && p.is_cash) : null
  return {
    broker: pata,
    cuenta: cuentaDe(brokerName, lista),
    // La moneda que viaja al backend (sólo si la cuenta tiene dos).
    moneda: dos ? (enDolares ? 'USD' : 'ARS') : null,
    // La que se MUESTRA: 'USD' para dólares reales, aunque el broker guarde 'USDT'.
    currency: enDolares ? (dos ? 'USD' : (b?.currency || 'USDT')) : 'ARS',
    direction,
    amount: '',
    available: caja?.invested || 0,
    date,
  }
}
