// tarjetaBroker.js — QUÉ ACTIVOS ENTRAN EN LA TABLA DE UN BROKER.
// ════════════════════════════════════════════════════════════════════════════
// Una sola función decide esto, y la usan TODAS las superficies que dibujan la
// cartera: la tabla de escritorio (pesos y dólares), el botón "Ver lotes" que
// pregunta si hay algo que desglosar, y la lista de celular.
//
// Existe porque el mismo filtro estaba escrito tres veces. Mientras la renta
// fija se excluía de las tarjetas, cualquier copia que se olvidara de excluirla
// mostraba el bono dos veces (una en la tabla y otra en la zona "Renta Fija"),
// y cualquier copia de más lo escondía. Ahora la regla es "todo lo de la cuenta
// entra", pero sigue viviendo en un solo lugar: si mañana vuelve a haber una
// excepción, se escribe acá y las tres superficies la heredan.
//
// REGLA (2026-09-22): la tabla del broker muestra TODOS los activos de la
// cuenta — acciones, CEDEARs, cripto Y renta fija (bonos, letras, FCI). El bono
// es un activo más: lo propio del bono (vencimiento, próximo cobro) va en la
// línea chica bajo el ticker y la ficha completa al desplegar la fila.
// Antes los bonos salían de acá y se juntaban en una zona aparte al pie de la
// pantalla: de 427 usuarios con renta fija, sólo 16 la tenían en más de una
// cuenta, así que a 411 les partía la cartera en dos sin ganar nada.
//
// CONSECUENCIA CONTABLE: el subtotal de la tarjeta se calcula sobre este mismo
// subconjunto, así que ahora INCLUYE la renta fija — y por eso sumar las
// tarjetas vuelve a dar el total de arriba (antes daba de menos).

/**
 * Filas de la tabla de una cuenta.
 * @param positions    todas las posiciones del usuario (lotes crudos)
 * @param section      la sección/tarjeta (trae `patasNames`: los brokers que la componen —
 *                     dos en una cuenta unificada ARS+USD, uno en modo separado)
 * @param matchesAsset predicado del buscador de la toolbar (sin búsqueda: () => true)
 */
export function filasDeLaTarjeta(positions, section, matchesAsset = () => true) {
  return positions.filter(p => section.patasNames.has(p.broker) && matchesAsset(p))
}
