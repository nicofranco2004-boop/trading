// filaFusionada.js — ¿esta fila tiene UNA cuenta a la que mandar una escritura?
// ════════════════════════════════════════════════════════════════════════════
// En una cuenta con dos patas (el broker en pesos y su cuenta en dólares) la
// cartera puede mostrar las dos juntas. Cuando lo hace, una fila puede estar
// fusionando compras de las DOS patas — o de una sola pata pero en dos monedas,
// que es lo que arma el importador de Balanz. Esa fila NO tiene una cuenta: el
// nombre del broker es a dónde iría a parar la venta, la edición o el cobro, y
// elegir el primer lote la metería en el ledger FIFO equivocado.
//
// La regla estaba escrita SIETE veces, y ya había divergido: las tres del
// celular (vender, agregar compra, eliminar) miraban `_multiBroker` y el broker
// nulo pero NO `_multiCcy`, así que la fila de una sola pata con lotes en dos
// monedas se les colaba — justo el caso que el comentario de esas tres líneas
// decía estar cubriendo. Y una octava, la de las cobranzas del bono, nunca
// existió: ahí el registro moría con el error crudo del backend en pantalla
// ("broker: Input should be a valid string", input null).
//
// Quien devuelve true no bloquea al usuario: lo manda a elegir la pata (abrir
// los lotes, o separar las monedas), que es donde cada lote SÍ es una posición
// real con su broker.
export function filaSinUnaPata(p) {
  if (!p || p.is_cash) return false
  return !!(p._multiBroker || p._multiCcy || p.broker == null)
}
