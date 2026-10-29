// Dibujos a mano sobre el gráfico técnico, como en TradingView: líneas de
// tendencia (de un punto a otro), líneas horizontales (un precio), un Fibonacci
// propio (el tramo que uno elige) y un conteo propio de ondas de Elliott. Pedido
// de Nico, 24/10: «que vos con eso marcás tendencias», «que se guarden por
// activo»; 28/10: Fibonacci y Elliott automáticos, pero «poder calcularlo como
// ellos estiman».
// ════════════════════════════════════════════════════════════════════════════
// Se guardan en tu CUENTA, por activo y por moneda (en pesos y en dólares los
// precios son otros), para verlos en todos tus dispositivos (Nico, 24/10):
// GET/PUT /api/tecnico/{activo}/dibujos (tabla `dibujos_grafico`). Además queda
// una copia en el navegador (`rendi_dibujos:AAPL:usd`): aparecen al instante,
// antes de que conteste el servidor, y no se pierden si el guardado falla.
//
// Un punto se guarda por DÍA y precio, no por lugar en la pantalla, así queda
// en su lugar con el zoom, con las velas semanales y cuando llegan días nuevos:
// { d: 'AAAA-MM-DD', mas: n, precio }. `mas` son los días de mercado después de
// `d`: un punto dibujado en el espacio vacío de la derecha (hacia adelante) es
// «n días de mercado después del último día que había».

import { indiceDeFecha } from './tecnico'
import { api } from './api'

const clave = (asset, moneda) => `rendi_dibujos:${String(asset || '').toUpperCase()}:${moneda === 'ars' ? 'ars' : 'usd'}`
export const DIBUJOS_MAXIMOS = 60

const numero = (x) => typeof x === 'number' && Number.isFinite(x)
// `f` (opcional, sólo el pincel): la fracción del lugar, para que un trazo a
// mano no quede en escalones de a un día cuando el gráfico está muy acercado.
const punto = (p) => !!p && typeof p.d === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(p.d)
  && Number.isInteger(p.mas) && p.mas >= 0 && numero(p.precio) && p.precio > 0
  && (p.f == null || (numero(p.f) && p.f >= 0 && p.f < 1))
// El pincel (Nico, 29/10): un trazo a mano alzada, hasta tantos puntos (se
// guardan en tu cuenta con los demás dibujos: sin tope, un garabato largo
// pesaría como cien líneas).
export const PINCEL_MAXIMO = 200
// Un conteo de Elliott a mano, en dos formas por separado (Nico, 28/10), como
// TradingView: el IMPULSO (0, 1, 2, 3, 4, 5) y la CORRECCIÓN (el arranque y
// A, B, C). Se puede terminar antes (un impulso que va por la 3). Los conteos
// guardados antes de separarlos no traen `forma`: son 0-1-2-3-4-5-A-B-C.
export const ETIQUETAS_ELLIOTT = ['0', '1', '2', '3', '4', '5', 'A', 'B', 'C']
export const ETIQUETAS_IMPULSO = ['0', '1', '2', '3', '4', '5']
export const ETIQUETAS_CORRECCION = ['', 'A', 'B', 'C']   // el arranque, sin nombre
export const etiquetasDe = (forma) => (forma === 'impulso' ? ETIQUETAS_IMPULSO
  : forma === 'correccion' ? ETIQUETAS_CORRECCION : ETIQUETAS_ELLIOTT)

/** ¿Es un dibujo que se puede dibujar? (lo guardado puede venir roto o de otra versión)
 *  horizontal: un precio · tendencia y fibonacci (retroceso): dos puntos (a, b) ·
 *  extension: tres (a, b, c) · elliott: de 2 puntos al máximo de su forma. */
export function dibujoValido(x) {
  if (!x || typeof x.id !== 'string') return false
  if (x.tipo === 'horizontal') return numero(x.precio) && x.precio > 0
  if (x.tipo === 'tendencia' || x.tipo === 'fibonacci') return punto(x.a) && punto(x.b)
  // El canal: la línea de abajo (a → b) y cuánto más arriba (o abajo) va su
  // paralela, en precio (Nico, 29/10: «el lateral»).
  if (x.tipo === 'canal') return punto(x.a) && punto(x.b) && numero(x.ancho) && x.ancho !== 0
  if (x.tipo === 'pincel') return Array.isArray(x.puntos) && x.puntos.length >= 2 && x.puntos.length <= PINCEL_MAXIMO && x.puntos.every(punto)
  if (x.tipo === 'extension') return punto(x.a) && punto(x.b) && punto(x.c)
  if (x.tipo === 'elliott') {
    if (x.forma != null && x.forma !== 'impulso' && x.forma !== 'correccion') return false
    return Array.isArray(x.puntos) && x.puntos.length >= 2 && x.puntos.length <= etiquetasDe(x.forma).length && x.puntos.every(punto)
  }
  return false
}

/**
 * La copia de este navegador: { dibujos, pendiente }. `pendiente`: hay un
 * cambio hecho acá que todavía no llegó a tu cuenta (el guardado falló, o se
 * dibujó antes de que existiera el guardado en la cuenta: la copia vieja era la
 * lista sola). Sin pendiente, lo de la cuenta manda: si borraste todo desde el
 * celular, la copia de la compu no lo vuelve a subir.
 * Sin almacenamiento o con un valor roto: ninguno.
 */
export function copiaLocal(asset, moneda) {
  try {
    const g = JSON.parse(localStorage.getItem(clave(asset, moneda)) || 'null')
    const lista = Array.isArray(g) ? g : Array.isArray(g?.dibujos) ? g.dibujos : []
    return { dibujos: lista.filter(dibujoValido).slice(0, DIBUJOS_MAXIMOS), pendiente: Array.isArray(g) || !!g?.pendiente }
  } catch {
    return { dibujos: [], pendiente: false }
  }
}

/** Los dibujos de la copia de este navegador. */
export const dibujosGuardados = (asset, moneda) => copiaLocal(asset, moneda).dibujos

export function guardarDibujos(asset, moneda, lista, pendiente = true) {
  try {
    if (!pendiente && !lista.length) localStorage.removeItem(clave(asset, moneda))
    else localStorage.setItem(clave(asset, moneda), JSON.stringify({ pendiente, dibujos: lista.slice(0, DIBUJOS_MAXIMOS) }))
  } catch { /* sin almacenamiento: el dibujo vive mientras la página esté abierta */ }
}

/** Ya llegó a la cuenta: si la copia sigue siendo ESA lista, deja de estar pendiente. */
export function marcarSubidos(asset, moneda, lista) {
  if (JSON.stringify(copiaLocal(asset, moneda).dibujos) === JSON.stringify(lista)) guardarDibujos(asset, moneda, lista, false)
}

/** El precio a guardar: el del toque viene con 15 decimales. 4 decimales y,
 *  abajo de 1, 6 cifras significativas (como backend/estructura.precio_redondo). */
export const precioRedondo = (x) => (Math.abs(x) >= 1 ? Math.round(x * 1e4) / 1e4 : Number(x.toPrecision(6)))

const ruta = (asset, moneda) => `/tecnico/${encodeURIComponent(String(asset || '').toUpperCase())}/dibujos?moneda=${moneda === 'ars' ? 'ars' : 'usd'}`

/** Los de tu cuenta. null si no se pudieron traer (sin conexión): se sigue con la copia. */
export async function dibujosDelServidor(asset, moneda) {
  try {
    const r = await api.get(ruta(asset, moneda))
    return Array.isArray(r?.dibujos) ? r.dibujos.filter(dibujoValido).slice(0, DIBUJOS_MAXIMOS) : null
  } catch {
    return null
  }
}

// Los guardados van en fila, uno detrás del otro por activo y moneda: la lista
// va entera, y si dos salieran juntos el viejo podría llegar después y pisar
// al nuevo.
const enFila = {}
/** Guarda la lista entera en tu cuenta. Resuelve true si quedó guardada. */
export function subirDibujos(asset, moneda, lista) {
  const k = clave(asset, moneda)
  const sigue = (enFila[k] || Promise.resolve(true))
    .then(() => api.put(ruta(asset, moneda), { dibujos: lista.slice(0, DIBUJOS_MAXIMOS) }))
    .then(() => true, () => false)
  enFila[k] = sigue
  return sigue
}

let contador = 0
export const idNuevo = () => `d${Date.now().toString(36)}${(contador++).toString(36)}`

/**
 * El punto a guardar para el día `i` (contado sobre los puntos DIARIOS del
 * gráfico; puede pasar del último, hacia adelante) y un precio.
 */
export function puntoDelDia(puntos, i, precio, f = 0) {
  const ultimo = puntos.length - 1
  const fr = f > 0 && f < 1 ? { f: Math.min(0.99, Math.round(f * 100) / 100) } : {}
  if (i <= ultimo) return { d: puntos[Math.max(0, i)].d, mas: 0, precio: precioRedondo(precio), ...(fr.f ? fr : {}) }
  return { d: puntos[ultimo].d, mas: i - ultimo, precio: precioRedondo(precio), ...(fr.f ? fr : {}) }
}

/**
 * Y al revés: en qué día (índice de los puntos diarios) cae un punto guardado.
 * Si su fecha no está (un feriado, o datos que cambiaron) va al último día de
 * antes; si es anterior a todo el gráfico, -1 (queda afuera, a la izquierda).
 */
export function diaDelPunto(puntos, p) {
  if (!puntos.length) return null
  const i = indiceDeFecha(puntos, p.d)
  return i == null ? -1 : i + p.mas
}

/**
 * Las puntas de un dibujo, con su nombre: ['a', p], ['b', p], ['c', p] o, en
 * un conteo de Elliott, [n, p] por onda. Una horizontal no tiene: se agarra entera.
 */
export function puntasDe(d) {
  if (d.tipo === 'horizontal' || d.tipo === 'pincel') return []
  if (d.tipo === 'elliott') return d.puntos.map((p, n) => [n, p])
  // El canal se ensancha agarrando la paralela de su mitad (como TradingView).
  if (d.tipo === 'canal') {
    return [['a', d.a], ['b', d.b], ['ancho', { k: (d.a.k + d.b.k) / 2, precio: (d.a.precio + d.b.precio) / 2 + d.ancho }]]
  }
  return ['a', 'b', 'c'].filter(c => d[c]).map(c => [c, d[c]])
}

/**
 * El dibujo arrastrado (Nico, 28/10: «mover y corregir un dibujo ya hecho»):
 * `que` es la punta agarrada (su nombre en `puntasDe`) o 'todo', para moverlo
 * entero; en un canal, 'ancho' corre su paralela `dp` de precio. `correr(p)` da el punto nuevo de una punta; `correrPrecio(x)`, el
 * precio nuevo de una horizontal. La MISMA cuenta para lo que se ve mientras
 * se arrastra (puntos en lugares de la pantalla) y para lo que se guarda
 * (puntos por día).
 */
export function dibujoCorrido(d, que, correr, correrPrecio, dp = 0) {
  if (d.tipo === 'horizontal') return { ...d, precio: correrPrecio(d.precio) }
  if (d.tipo === 'canal' && que === 'ancho') return { ...d, ancho: d.ancho + dp || d.ancho }
  const mueve = (nombre) => que === 'todo' || que === nombre
  if (d.tipo === 'elliott' || d.tipo === 'pincel') return { ...d, puntos: d.puntos.map((p, n) => (mueve(n) ? correr(p) : p)) }
  const out = { ...d }
  for (const c of ['a', 'b', 'c']) if (d[c] && mueve(c)) out[c] = correr(d[c])
  return out
}

/** Un precio corrido `dp`, que nunca llega a 0 (arrastrar una línea muy abajo la deja en el piso). */
export const precioCorrido = (precio, dp) => Math.max(precio + dp, precio * 0.02)

/** La distancia de (x, y) al segmento de (ax, ay) a (bx, by), todo en píxeles. */
export function distanciaASegmento(x, y, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay
  const largo = dx * dx + dy * dy
  const t = largo ? Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / largo)) : 0
  return Math.hypot(x - (ax + t * dx), y - (ay + t * dy))
}

/**
 * Qué dibujo se tocó: el más cercano a (x, y) a menos de `radio` píxeles, o
 * null. `trazos`: [{ id, ax, ay, bx, by }] ya en píxeles (una horizontal va de
 * borde a borde).
 */
export function dibujoTocado(trazos, x, y, radio = 8) {
  let mejor = null, dist = radio
  for (const t of trazos) {
    const d = distanciaASegmento(x, y, t.ax, t.ay, t.bx, t.by)
    if (d <= dist) { mejor = t.id; dist = d }
  }
  return mejor
}
