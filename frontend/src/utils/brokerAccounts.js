/**
 * brokerAccounts — agrupa las filas de `brokers` en CUENTAS.
 *
 * El modelo: cuando un broker argentino opera en las dos monedas, el importador
 * crea un sub-broker "<Padre> · USD" (`_ensure_usd_sibling` en el backend) con
 * `currency='USDT'` y `parent_broker_id` apuntando al padre. Son dos filas en la
 * tabla `brokers`, pero para el usuario es UNA cuenta: la que le muestra el
 * broker real, con su saldo en pesos y su saldo en dólares.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * DOS REGLAS QUE NO SE NEGOCIAN
 *
 * 1. El par se arma SIEMPRE por `parent_broker_id`, NUNCA parseando el sufijo
 *    " · USD" del nombre. El nombre es el contrato de PRECIO, no el de
 *    identidad: `isArUsdBroker` decide con él si un CEDEAR se cotiza por su
 *    `.BA` o por el ticker US, y ahí la diferencia es de 15-100×. Un renombre
 *    degrada el parseo en silencio; la FK no.
 *
 * 2. El `label` de la cuenta es SÓLO para mostrar. Nunca se escribe en
 *    `p.broker`, nunca se manda a un endpoint, nunca reemplaza el nombre real
 *    de una pata. Cada posición conserva su `p.broker` unívoco — que es
 *    justamente lo que deja las filas editables, vendibles y con cupón.
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * Soporta N patas por cuenta: `POST /api/brokers` acepta un `parent_broker_id`
 * arbitrario y sólo valida que el padre exista, así que un padre puede tener
 * más de un hijo. No asumas dos.
 */

/**
 * @param {Array} brokers filas de /api/brokers (con id, name, currency, parent_broker_id)
 * @returns {Array<{key: string, label: string, parent: object, patas: object[],
 *                  patasNames: Set<string>, isPair: boolean, isOrphan: boolean}>}
 *   Una entrada por CUENTA, en el mismo orden en que venían los padres.
 *   · key        — identidad estable de la cuenta (el id del padre). Sirve de
 *                  React key, de valor de filtro y de scope de agrupación.
 *   · label      — cómo se muestra: el nombre del padre, sin el sufijo de ninguna pata.
 *   · parent     — la fila del broker padre (a la que apuntan renombrar y eliminar:
 *                  el backend rechaza renombrar un sibling y cascadea el nombre solo).
 *   · patas      — [padre, ...hijos]. Siempre incluye al padre y siempre es no vacío.
 *   · patasNames — Set con los NOMBRES reales, para filtrar posiciones por `p.broker`.
 *   · isPair     — true si tiene más de una pata (o sea, si hay algo que unificar).
 *   · isOrphan   — true si es un hijo cuyo padre ya no existe. Se emite como cuenta
 *                  propia, igual que hacía `sortBrokersForDisplay`.
 */
export function groupBrokersIntoAccounts(brokers) {
  const list = Array.isArray(brokers) ? brokers : []
  const byId = new Map(list.map(b => [b.id, b]))

  const childrenByParent = new Map()
  const roots = []
  const orphans = []

  for (const b of list) {
    if (b.parent_broker_id == null) {
      roots.push(b)
    } else if (byId.has(b.parent_broker_id)) {
      const arr = childrenByParent.get(b.parent_broker_id) || []
      arr.push(b)
      childrenByParent.set(b.parent_broker_id, arr)
    } else {
      // Padre eliminado: el hijo quedó suelto. Es una cuenta más — se ve en
      // pantalla, así que también ocupa cupo de plan (ver count_broker_accounts
      // en el backend, que usa la misma definición a propósito).
      orphans.push(b)
    }
  }

  const cuenta = (parent, patas, isOrphan) => ({
    key: String(parent.id),
    label: parent.name,
    parent,
    patas,
    patasNames: new Set(patas.map(p => p.name)),
    isPair: patas.length > 1,
    isOrphan,
  })

  const out = roots.map(p => cuenta(p, [p, ...(childrenByParent.get(p.id) || [])], false))
  // Los huérfanos al final, como venía haciendo sortBrokersForDisplay.
  for (const o of orphans) out.push(cuenta(o, [o], true))
  return out
}

/**
 * Cómo nombrar la PATA de una cuenta cuando se la lista al lado de sus hermanas.
 *
 * El sub-broker se llama "<Padre> · USD", pero el padre se llama sólo "<Padre>",
 * así que en una lista quedaban "Cocos" y "Cocos · USD": el de dólares dice su
 * moneda y el de pesos no, y hay que deducirla por descarte. Acá el padre de un
 * par pasa a mostrarse como "Cocos · ARS" — simétrico y legible de un vistazo.
 *
 * Sólo aplica cuando el broker TIENE hermanas: un broker suelto se sigue
 * llamando por su nombre, sin sufijo que no aporta nada.
 *
 * ⚠️ Es un nombre PARA MOSTRAR. Nunca se escribe en `p.broker` ni se manda a un
 * endpoint: el nombre real es el contrato de precio y de identidad.
 *
 * @param {string} brokerName nombre real del broker
 * @param {Array} brokers lista completa (para saber si tiene hermanas)
 */
export function brokerLegLabel(brokerName, brokers) {
  const list = Array.isArray(brokers) ? brokers : []
  const b = list.find(x => x.name === brokerName)
  if (!b) return brokerName
  // ¿Es el padre de al menos un sub-broker?
  const tieneHijos = list.some(x => x.parent_broker_id === b.id)
  if (!tieneHijos) return brokerName
  const ccy = (b.currency || '').toUpperCase()
  const etiqueta = ccy === 'ARS' ? 'ARS' : (ccy === 'USDT' ? 'USD' : ccy)
  // Si el nombre ya termina con esa moneda no se repite ("Cocos · USD · USD").
  return etiqueta && !new RegExp(`·\\s*${etiqueta}$`).test(brokerName)
    ? `${brokerName} · ${etiqueta}`
    : brokerName
}

/**
 * La cuenta a la que pertenece un broker, por nombre. Devuelve undefined si el
 * nombre no está en ninguna (posición de un broker que ya no existe).
 */
export function accountForBrokerName(accounts, brokerName) {
  return (accounts || []).find(a => a.patasNames.has(brokerName))
}

/**
 * Compat: la forma plana [{broker, indent, parentName}] que consumía el render
 * viejo. Se deriva del agrupado para que haya UN solo constructor del árbol
 * padre→hijo y no dos que puedan divergir.
 */
export function flattenAccounts(accounts) {
  const out = []
  for (const a of accounts) {
    out.push({ broker: a.parent, indent: false, parentName: null })
    for (const pata of a.patas) {
      if (pata.id === a.parent.id) continue
      out.push({ broker: pata, indent: true, parentName: a.parent.name })
    }
  }
  return out
}
