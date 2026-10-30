// menuGrafico — tocar el menú «Moneda y período» del gráfico técnico
// (LecturaTecnica.jsx) en las pruebas montadas, como lo hace una persona:
// abrir el menú y tocar la opción. Sólo lo importan pruebas.

import { clic, texto } from './navegadorMinimo'

function buscar(nodo, ok) {
  const pila = [nodo]
  while (pila.length) {
    const n = pila.shift()
    if (ok(n)) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}

/** El botón que abre el menú (dice lo elegido: «US$ · Todo»). */
export const botonDeLaVista = (c) => buscar(c, n => n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === 'vista')

const opciones = (c) => {
  const out = [], pila = [c]
  while (pila.length) {
    const n = pila.shift()
    if (n.getAttribute?.('role') === 'menuitemradio' && n.getAttribute('data-intervalo') == null) out.push(n)
    pila.push(...(n.childNodes || []))
  }
  return out
}

/** Abre el menú y toca la opción que empieza con `nombre` («Pesos», «Todo», «Desde que lo tenés»…). */
export async function elegirEnLaVista(c, nombre) {
  if (botonDeLaVista(c).getAttribute('aria-expanded') !== 'true') await clic(c, botonDeLaVista(c))
  const op = opciones(c).find(n => texto(n).startsWith(nombre))
  if (!op) throw new Error(`El menú «Moneda y período» no tiene «${nombre}»: ${opciones(c).map(texto).join(' | ')}`)
  await clic(c, op)
}

/** Lo que ofrece el menú (abre y cierra): los nombres de cada opción. */
export async function opcionesDeLaVista(c) {
  await clic(c, botonDeLaVista(c))
  const lista = opciones(c).map(n => texto(n))
  await clic(c, botonDeLaVista(c))
  return lista
}

/** El período que dice el botón («Todo», «Reciente», «Desde tu compra»), o null si se acercó a mano. */
export function periodoElegido(c) {
  const t = texto(botonDeLaVista(c)).replace(/^Moneda y período: /, '')
  return t.includes(' · ') ? t.split(' · ')[1] : null
}
