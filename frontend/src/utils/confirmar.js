// confirmar — el "¿Seguro?" de Rendi. Reemplaza al cartel del navegador
// (`window.confirm`) en toda la app. Pedido de Nico, 2026-10-10.
//
// Por qué. El cartel del navegador no es de Rendi: lo dibuja (o no) quien
// muestra la página. Un navegador embebido que no lo muestra contesta "no" solo
// y en silencio — medido el 2026-10-10: respondió "no" en 0 ms, el tachito de
// Movimientos no hacía nada y no salía ningún pedido al servidor. Con un cartel
// propio, borrar funciona igual en cualquier navegador.
//
//   if (!await confirmar('¿Borrar el depósito?\n\nSale la plata de la cuenta.')) return
//
// Devuelve una promesa: true si la persona acepta, false si cancela (botón,
// Escape o tocar afuera). Lo de antes del primer renglón en blanco va como
// título; el resto, como explicación.
//
//   opciones.si / opciones.no   el texto de los botones ("Confirmar" / "Cancelar")
//   opciones.peligro            pinta el botón de aceptar en rojo
//
// El cartel lo dibuja <ConfirmarHost/> (montado una vez, en main.jsx). Sin él
// —una prueba que monta una pantalla suelta— se usa el del navegador, como
// antes: la pregunta nunca se saltea.

let abrir = null

/** Lo llama <ConfirmarHost/> al montarse. Devuelve cómo darse de baja. */
export function registrarConfirmar(fn) {
  abrir = fn
  return () => { if (abrir === fn) abrir = null }
}

export function confirmar(mensaje, opciones = {}) {
  const texto = String(mensaje ?? '')
  if (abrir) return abrir(texto, opciones)
  const nativo = typeof window !== 'undefined' && typeof window.confirm === 'function'
    ? window.confirm
    : (typeof globalThis.confirm === 'function' ? globalThis.confirm : null)
  return Promise.resolve(nativo ? !!nativo(texto) : false)
}
