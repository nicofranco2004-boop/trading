// El texto que confirma el borrado de un broker.
//
// `DELETE /api/brokers/{id}` sin `force` contesta 409 con el resumen de lo que se
// va a ir (`detail.counts`, lo arma `_contar_datos_de_brokers` en el backend).
// Este es el ÚNICO lugar que lo traduce a palabras: antes estaba copiado en
// BrokerManager y en PositionsMobile, y cada clave nueva del resumen había que
// acordarse de sumarla en los dos.
//
// `futures` y `archived` se agregaron el 2026-10-09: el borrado no se llevaba los
// futuros abiertos ni las posiciones guardadas en "Posiciones eliminadas", así
// que tampoco los anunciaba — y cerrar ese futuro después acreditaba la ganancia
// a un broker que ya no existía.

const plural = (n, uno, muchos) => `${n} ${n === 1 ? uno : muchos}`

/** Las líneas del resumen, en el orden en que se muestran. */
export function partesDelBorrado(counts) {
  const n = (k) => Number(counts?.[k]) || 0
  const partes = []
  if (n('positions') > 0) partes.push(plural(n('positions'), 'posición', 'posiciones'))
  if (n('operations') > 0) partes.push(plural(n('operations'), 'operación', 'operaciones'))
  if (n('monthly_entries') > 0) partes.push(plural(n('monthly_entries'), 'entrada mensual', 'entradas mensuales'))
  if (n('import_batches') > 0) partes.push(plural(n('import_batches'), 'import', 'imports'))
  if (n('futures') > 0) partes.push(plural(n('futures'), 'futuro abierto', 'futuros abiertos'))
  if (n('archived') > 0) {
    partes.push(`${plural(n('archived'), 'posición guardada', 'posiciones guardadas')} en "Posiciones eliminadas" (ya no se van a poder restaurar)`)
  }
  return partes
}

/** El mensaje completo para el `confirm()`. `detail` es el `detail` del 409. */
export function avisoBorrarBroker(nombre, detail) {
  const partes = partesDelBorrado(detail?.counts)
  const siblingWarning = detail?.sibling
    ? `\n\n⚠️ ATENCIÓN: este broker es PADRE de "${detail.sibling.name}" (${detail.sibling.currency}). Al borrar el padre, el sibling también se eliminará.`
    : ''
  return `El broker "${nombre}" tiene data:\n\n  • ${partes.join('\n  • ')}${siblingWarning}\n\n¿Borrar TODO? Esta acción no se puede deshacer.`
}
