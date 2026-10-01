// Dónde va un aviso de arriba de todo (cliente abierto, demo, prueba gratis).
//
// En el celular va ADENTRO de la barra de arriba: App.jsx se los pasa a
// MobileTopBar. Así su alto entra en lo que la barra mide y anota en
// --alto-barra-celular, y lo que se pega debajo al bajar (el total de Cartera,
// el resultado de Movimientos, la burbuja de Rendi) se acomoda solo. Cuando
// cada aviso se pegaba por su cuenta, uno tapaba al otro: la franja del cliente
// quedaba detrás de la barra, la barra de la prueba se montaba sobre el logo y,
// pegada debajo, tapaba el total de Cartera.
//
// En la compu no hay barra de arriba: se pegan arriba del contenido.
export function ubicacionDeAviso(enLaBarra, { delante = true } = {}) {
  if (enLaBarra) return 'border-t'
  return delante ? 'sticky top-0 z-40 border-b' : 'sticky top-0 z-20 border-b'
}
