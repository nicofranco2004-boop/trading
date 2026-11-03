// recorrido — lo que comparten los tutoriales guiados (Tour.jsx): la marca que
// ilumina, el «ya lo vio», a dónde hay que ir para cada paso y el TURNO.
// ═══════════════════════════════════════════════════════════════════════════
// Hay más de un tutorial (el de novedades, el de Análisis técnico) y son el
// MISMO mecanismo con otra lista de pasos: una sola copia de cada cosa.
//
// EL TURNO, y por qué existe. Los dos tutoriales oscurecen la pantalla entera.
// Alguien que todavía no vio el de novedades y entra a Análisis técnico
// cumple las condiciones de los dos a la vez: sin turno, se dibujaban uno
// encima del otro y «Omitir» cerraba uno solo. Ahora el que arranca toma el
// turno, el otro espera, y cuando se suelta los que esperaban vuelven a mirar.

// Con «.js»: scripts/medir-textos-cortados.mjs la importa desde Node, que no
// completa la terminación como el empaquetador.
import { CATALOGO } from '../../utils/catalogoDelAlmacen.js'

/** La marca que se le pone al elemento que hay que resaltar. */
export const ATRIBUTO = 'data-tour'

/** ¿Ya lo vio? Si el almacenamiento no se puede leer, se asume que SÍ: mejor
 *  no mostrarlo que mostrarlo en loop a alguien que no lo puede apagar. */
export function yaLoVio(almacen, clave) {
  try {
    return almacen.getItem(clave) === '1'
  } catch {
    return true
  }
}

export function marcarVisto(almacen, clave) {
  try {
    almacen.setItem(clave, '1')
  } catch { /* sin almacenamiento: se va a volver a ver, y es lo menos malo */ }
}

/**
 * Las claves de «ya lo vio» de TODOS los tutoriales, salidas del catálogo.
 * Las pruebas y los scripts que miran pantallas las marcan para que ningún
 * tutorial les tape lo que miran. Antes cada uno escribía la suya a mano y
 * dos usaban un nombre que ya no existía (el de antes del catálogo): el
 * tutorial corría en el medio de la prueba sin que nadie lo notara.
 */
export const CLAVES_DE_LOS_TOURS = Object.freeze(
  Object.values(CATALOGO).filter(e => /^rendi:tour:/.test(e.clave || '')).map(e => e.clave))

/**
 * A dónde hay que ir para mostrar `paso`, o null si ya está ahí.
 *
 * `busqueda` dice SÓLO lo que el paso necesita de la dirección y respeta el
 * resto: en Análisis técnico la dirección lleva además el activo del gráfico
 * (?activo=GGAL), y compararla entera hacía que el tutorial nunca se diera por
 * llegado. Un valor vacío pide que NO esté (`?tab=` = la pestaña de entrada).
 */
export function destino(paso, pathname, search) {
  if (!paso?.ruta) return null
  const aca = pathname === paso.ruta
  const params = new URLSearchParams(aca ? search : '')
  let falta = !aca
  for (const [k, v] of new URLSearchParams(paso.busqueda || '')) {
    const ahora = params.get(k)
    if (v === '') {
      if (ahora != null) { params.delete(k); falta = true }
    } else if (ahora !== v) {
      params.set(k, v); falta = true
    }
  }
  if (!falta) return null
  const q = params.toString()
  return paso.ruta + (q ? `?${q}` : '')
}

// ── El turno ────────────────────────────────────────────────────────────────
let enCurso = null
let pedido = null
const oyentes = new Set()
// Los tutoriales montados ahora. Un pedido a mano sólo se guarda si el suyo
// está: si no (la red que lo envuelve lo apagó), quedaba guardado y, al
// volver a montarse en otra pantalla, arrancaba sin que nadie lo tocara.
const presentes = new Map()

/** Lo llama cada tutorial al montarse; devuelve con qué irse. */
export function presentarse(id) {
  presentes.set(id, (presentes.get(id) || 0) + 1)
  return () => {
    const n = (presentes.get(id) || 1) - 1
    if (n > 0) presentes.set(id, n)
    else { presentes.delete(id); if (pedido === id) pedido = null }
  }
}
const avisar = () => { for (const f of [...oyentes]) f() }

/** ¿Puede arrancar `id`? (nadie más está mostrando el suyo) */
export const turnoLibre = (id) => enCurso == null || enCurso === id

/** Lo toma si está libre. Devuelve si lo consiguió. */
export function tomarTurno(id) {
  if (!turnoLibre(id)) return false
  enCurso = id
  return true
}

/** Lo suelta (si era suyo) y avisa a los que esperaban. */
export function soltarTurno(id) {
  if (enCurso !== id) return
  enCurso = null
  avisar()
}

/** Abrir un tutorial a mano (el botón «¿Cómo se lee esto?»). */
export function pedirTour(id) {
  if (!presentes.has(id)) return false
  pedido = id
  avisar()
  return true
}

/** ¿Hay un pedido a mano para `id`? (sin consumirlo) */
export const hayPedido = (id) => pedido === id

/** Si alguien pidió abrir `id`, lo consume y devuelve true. */
export function tomarPedido(id) {
  if (pedido !== id) return false
  pedido = null
  return true
}

/** Llama a `f` cada vez que el turno se suelta o alguien pide un tutorial. */
export function escucharTurno(f) {
  oyentes.add(f)
  return () => { oyentes.delete(f) }
}
