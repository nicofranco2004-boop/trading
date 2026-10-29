// Rótulos del gráfico técnico que se pisarían con todas las capas prendidas.
// ════════════════════════════════════════════════════════════════════════════
// Con todo prendido (Nico, 24/10) el rótulo de una capa puede caer encima del
// de otra: en AAPL el «Cierre debajo: termina la suba» del Fibonacci pisaba el
// «Dejaría de valer» de Elliott y el número de la onda 4. Cada capa ya ordena
// sus propios rótulos (fibonacci.rotulosQueEntran); esto ordena los de capas
// DISTINTAS, midiendo lo que quedó dibujado: donde dos se pisan, se esconde el
// de menos prioridad. La raya o el punto quedan; sólo se va el texto (y su
// precio sigue en la tarjeta de esa capa).
//
// La prioridad va en el atributo `data-rotulo` de cada rótulo (más alto, más
// importante; ver PRIORIDAD). Un rótulo escondido queda con `data-tapado`.
// El rótulo de una raya horizontal (`data-rotulo-voltear`) antes de esconderse
// prueba la otra punta de su raya, el otro lado (arriba en vez de abajo) y las
// dos cosas: en AAPL el «Cierre debajo» chocaba con la onda 4 en las dos puntas
// de su raya (corta: el rótulo es más ancho que ella) y arriba entraba.

export const PRIORIDAD = {
  medicion: 6,          // lo que la persona acaba de medir
  onda: 5,              // los números de las ondas: sin ellos el conteo no se lee
  nivelFib: 4,          // los niveles del Fibonacci, lo primero que se mira
  corteFib: 3,          // «Cierre debajo: termina la suba»
  invalidaElliott: 2,   // «Dejaría de valer»
}

/**
 * Dónde va cada rótulo. `cajas`: [{ prioridad, x0, x1, y0, y1, otras?, limite? }]
 * en píxeles de la pantalla; `otras` son las cajas del rótulo en sus otros
 * lugares posibles (si se puede voltear), en orden de preferencia, y `limite`
 * ({ x0, x1 }) el ancho del gráfico: un rótulo de raya que se sale por un
 * costado cuenta como chocado (en el celular el «Cierre debajo» del Fibonacci
 * se salía y quedaba sobre el último precio, GGAL 24/10). Las que no ocupan
 * lugar (ancho o alto 0) no cuentan. De mayor a menor prioridad (a igual
 * prioridad, el que vino primero), cada uno va donde está si no pisa a ninguno
 * ya puesto; si no, en el primero de sus otros lugares que esté libre; si no
 * hay, se esconde. Devuelve { tapados: Set de índices, movidos: Map índice →
 * cuál de sus `otras` }.
 */
export function ubicarRotulos(cajas, tolerancia = 1) {
  const ocupa = (c) => c && c.x1 - c.x0 > 0 && c.y1 - c.y0 > 0
  const orden = cajas.map((c, k) => k).filter(k => ocupa(cajas[k]))
    .sort((a, b) => cajas[b].prioridad - cajas[a].prioridad || a - b)
  const puestas = []
  const sale = (c, lim) => lim && (c.x0 < lim.x0 - tolerancia || c.x1 > lim.x1 + tolerancia)
  const pisa = (c, lim) => sale(c, lim) || puestas.some(o => Math.min(c.x1, o.x1) - Math.max(c.x0, o.x0) > tolerancia
    && Math.min(c.y1, o.y1) - Math.max(c.y0, o.y0) > tolerancia)
  const tapados = new Set()
  const movidos = new Map()
  for (const k of orden) {
    const c = cajas[k]
    if (!pisa(c, c.limite)) { puestas.push(c); continue }
    const j = (c.otras || []).findIndex(o => ocupa(o) && !pisa(o, c.limite))
    if (j >= 0) { puestas.push(c.otras[j]); movidos.set(k, j) } else tapados.add(k)
  }
  return { tapados, movidos }
}

/** Sólo cuáles esconder (sin mover ninguno). */
export const rotulosTapados = (cajas, tolerancia = 1) => ubicarRotulos(cajas, tolerancia).tapados

// Los otros lugares de un rótulo de raya, en orden: la otra punta, el otro
// lado, las dos cosas. Su lugar normal es su clase (`left-1`/`right-1` y
// `top-0.5` = abajo de la raya / `-translate-y-full` = arriba).
const VARIANTES = [{ punta: true }, { lado: true }, { punta: true, lado: true }]
const ESTILOS = ['left', 'right', 'top', 'bottom', 'transform']
function mover(n, { punta, lado }) {
  const clase = ' ' + (n.getAttribute('class') || '') + ' '
  if (punta) {
    if (clase.includes(' right-1 ')) { n.style.right = 'auto'; n.style.left = '4px' } else { n.style.left = 'auto'; n.style.right = '4px' }
  }
  if (lado) {
    if (clase.includes(' top-0.5 ')) { n.style.top = 'auto'; n.style.bottom = '2px' } else { n.style.transform = 'none'; n.style.top = '2px' }
  }
}
const enSuLugar = (n) => { for (const k of ESTILOS) n.style[k] = '' }

/**
 * Mide los rótulos con `data-rotulo` adentro de `raiz` (lo que ya está
 * dibujado), los ubica (ubicarRotulos) y mueve o esconde los que se pisan. Se
 * llama después de cada dibujo: lo primero que hace es devolver todos a su
 * lugar (al cambiar el zoom o apagar una capa, el que estaba tapado puede
 * volver a entrar).
 */
export function taparRotulos(raiz) {
  if (!raiz) return
  const nodos = []
  const recorrer = (n) => {
    if (n.getAttribute?.('data-rotulo') != null) nodos.push(n)
    for (const h of n.childNodes || []) if (h.nodeType === 1) recorrer(h)
  }
  recorrer(raiz)
  // Sólo se mueven los rótulos de raya (no traen posición de React: su lugar
  // es su clase); a los demás —los números de las ondas, que React pone con
  // `left`/`top`— no se les toca la posición.
  const volteable = (n) => n.getAttribute('data-rotulo-voltear') != null
  for (const n of nodos) {
    n.style.visibility = ''
    if (volteable(n)) enSuLugar(n)
    n.removeAttribute('data-tapado')
  }
  const caja = (n) => { const r = n.getBoundingClientRect(); return { x0: r.left, x1: r.right, y0: r.top, y1: r.bottom } }
  const area = raiz.getBoundingClientRect?.()
  const limite = area && area.right > area.left ? { x0: area.left, x1: area.right } : null
  const cajas = nodos.map(n => {
    const c = { prioridad: Number(n.getAttribute('data-rotulo')) || 0, ...caja(n) }
    if (volteable(n)) {
      c.otras = VARIANTES.map(vr => { mover(n, vr); const o = caja(n); enSuLugar(n); return o })
      c.limite = limite
    }
    return c
  })
  const { tapados, movidos } = ubicarRotulos(cajas)
  for (const [k, j] of movidos) mover(nodos[k], VARIANTES[j])
  for (const k of tapados) {
    nodos[k].style.visibility = 'hidden'
    nodos[k].setAttribute('data-tapado', '')
  }
}
