// enfocarCambios — al cambiar de moneda (o de dólar MEP/CCL), los números que
// cambiaron hacen foco: un fundido corto de borroso a nítido.
//
// SÓLO los que cambiaron. La primera versión animaba todos los `.tabular` de la
// pantalla, y eso incluía la cinta de cotizaciones y el "Dólar MEP · $1.424" del
// menú, que no dependen de la moneda: un número que parpadea sin haber cambiado
// dice algo que no pasó (la misma regla que el punto de "en vivo").
//
// Cómo sabe qué cambió: durante `ms` después del click escucha las
// reescrituras de texto del documento (MutationObserver) y anima el número que
// contiene cada texto reescrito. React reescribe un texto de dos maneras: le
// cambia el valor al nodo (`characterData`) o reemplaza el nodo de texto
// (`childList` con un Text agregado). Los bloques enteros que aparecen o
// desaparecen (elementos agregados) no se animan: eso no es "el número cambió".
//
// Con Web Animations (`el.animate`) y no con una clase: no pisa las animaciones
// CSS que el elemento ya tenga (`.entra`, el destello de FlashValue) y no hay
// clase que limpiar después.

import { prefiereSinMovimiento } from './movimiento'

const TEXTO = 3   // Node.TEXT_NODE

// Los elementos a animar según una tanda de mutaciones. Pura: se prueba con
// objetos de mentira, sin navegador. Un texto reescrito anima su número
// (`.tabular` / `.num`, que por contrato son los números) y, si no está adentro
// de uno, el elemento que lo contiene directamente.
export function elementosQueCambiaron(mutaciones) {
  const out = new Set()
  for (const m of mutaciones || []) {
    let el = null
    if (m.type === 'characterData') el = m.target?.parentElement
    else if (m.type === 'childList' && [...(m.addedNodes || [])].some(n => n.nodeType === TEXTO)) el = m.target
    if (!el) continue
    out.add(el.closest?.('.tabular, .num') || el)
  }
  return out
}

const FOCO = [
  { opacity: 0.2, filter: 'blur(3px)' },
  { opacity: 1, filter: 'blur(0)' },
]

// Escucha `ms` milisegundos y anima una sola vez cada número que cambie en ese
// lapso (un AnimatedNumber que cuenta reescribe su texto en cada cuadro: sin el
// "una sola vez" se reiniciaría el borroso todo el tiempo). Devuelve la
// función que corta antes de tiempo.
export function enfocarCambios(ms = 900) {
  if (typeof window === 'undefined' || typeof MutationObserver === 'undefined') return () => {}
  if (prefiereSinMovimiento()) return () => {}
  const yaAnimados = new WeakSet()
  const obs = new MutationObserver(lista => {
    for (const el of elementosQueCambiaron(lista)) {
      if (yaAnimados.has(el) || typeof el.animate !== 'function') continue
      yaAnimados.add(el)
      el.animate(FOCO, { duration: 450, easing: 'ease-out' })
    }
  })
  obs.observe(document.body, { subtree: true, characterData: true, childList: true })
  const t = setTimeout(() => obs.disconnect(), ms)
  return () => { clearTimeout(t); obs.disconnect() }
}
