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
const punto = (p) => !!p && typeof p.d === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(p.d)
  && Number.isInteger(p.mas) && p.mas >= 0 && numero(p.precio) && p.precio > 0
// Un conteo de Elliott a mano: el arranque (0), las cinco ondas y la corrección
// A-B-C, uno por toque. Se puede terminar antes (un conteo que va por la 3).
export const ETIQUETAS_ELLIOTT = ['0', '1', '2', '3', '4', '5', 'A', 'B', 'C']

/** ¿Es un dibujo que se puede dibujar? (lo guardado puede venir roto o de otra versión)
 *  horizontal: un precio · tendencia y fibonacci: dos puntos (a, b) ·
 *  elliott: de 2 a 9 puntos, en el orden de ETIQUETAS_ELLIOTT. */
export function dibujoValido(x) {
  if (!x || typeof x.id !== 'string') return false
  if (x.tipo === 'horizontal') return numero(x.precio) && x.precio > 0
  if (x.tipo === 'tendencia' || x.tipo === 'fibonacci') return punto(x.a) && punto(x.b)
  if (x.tipo === 'elliott') {
    return Array.isArray(x.puntos) && x.puntos.length >= 2 && x.puntos.length <= ETIQUETAS_ELLIOTT.length && x.puntos.every(punto)
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
export function puntoDelDia(puntos, i, precio) {
  const ultimo = puntos.length - 1
  if (i <= ultimo) return { d: puntos[Math.max(0, i)].d, mas: 0, precio: precioRedondo(precio) }
  return { d: puntos[ultimo].d, mas: i - ultimo, precio: precioRedondo(precio) }
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
