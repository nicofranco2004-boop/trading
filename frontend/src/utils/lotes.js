// ¿Hay algo que desglosar? El botón "Ver lotes" de Cartera sólo tiene sentido
// si algún activo está comprado en más de un lote. Con un lote por activo no
// cambia nada visible y el tester lo leyó como "no funciona" — por eso el
// botón se oculta cuando esto da false. Un solo lugar para escritorio y
// celular (la regla del contrato: nada bifurcado por viewport).
//
// Se agrupa por (cuenta, activo) donde la cuenta es el broker SIN el sufijo
// del sub-broker en dólares (" · USD"): en la cuenta unificada el mismo
// ticker comprado en pesos y por dólar-MEP es UN activo con dos lotes.
const SUFIJO_USD = / · USD$/

export function cuentaDe(broker) {
  return String(broker || '').replace(SUFIJO_USD, '')
}

export function hayMultiLote(positions) {
  const vistos = new Set()
  for (const p of positions || []) {
    if (!p || p.is_cash) continue
    if (!(Number(p.quantity) > 0)) continue
    const k = `${cuentaDe(p.broker)}|${p.asset}`
    if (vistos.has(k)) return true
    vistos.add(k)
  }
  return false
}
