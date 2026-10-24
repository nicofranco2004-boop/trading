// Dibujos a mano sobre el gráfico técnico, como en TradingView: líneas de
// tendencia (de un punto a otro) y líneas horizontales (un precio). Pedido de
// Nico, 24/10: «que vos con eso marcás tendencias», «que se guarden por activo».
// ════════════════════════════════════════════════════════════════════════════
// Se guardan en ESTE navegador, por activo y por moneda (en pesos y en dólares
// los precios son otros): `rendi_dibujos:AAPL:usd`. Todo el guardado está acá,
// para poder pasarlo al servidor sin tocar la pantalla.
//
// Un punto se guarda por DÍA y precio, no por lugar en la pantalla, así queda
// en su lugar con el zoom, con las velas semanales y cuando llegan días nuevos:
// { d: 'AAAA-MM-DD', mas: n, precio }. `mas` son los días de mercado después de
// `d`: un punto dibujado en el espacio vacío de la derecha (hacia adelante) es
// «n días de mercado después del último día que había».

import { indiceDeFecha } from './tecnico'

const clave = (asset, moneda) => `rendi_dibujos:${String(asset || '').toUpperCase()}:${moneda === 'ars' ? 'ars' : 'usd'}`
export const DIBUJOS_MAXIMOS = 60

const numero = (x) => typeof x === 'number' && Number.isFinite(x)
const punto = (p) => p && typeof p.d === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(p.d)
  && Number.isInteger(p.mas) && p.mas >= 0 && numero(p.precio) && p.precio > 0
/** ¿Es un dibujo que se puede dibujar? (lo guardado puede venir roto o de otra versión) */
export function dibujoValido(x) {
  if (!x || typeof x.id !== 'string') return false
  if (x.tipo === 'horizontal') return numero(x.precio) && x.precio > 0
  if (x.tipo === 'tendencia') return punto(x.a) && punto(x.b)
  return false
}

/** Los dibujos guardados de un activo en una moneda. Sin almacenamiento o con un valor roto: ninguno. */
export function dibujosGuardados(asset, moneda) {
  try {
    const g = JSON.parse(localStorage.getItem(clave(asset, moneda)) || '[]')
    return Array.isArray(g) ? g.filter(dibujoValido).slice(0, DIBUJOS_MAXIMOS) : []
  } catch {
    return []
  }
}

export function guardarDibujos(asset, moneda, lista) {
  try {
    if (lista.length) localStorage.setItem(clave(asset, moneda), JSON.stringify(lista.slice(0, DIBUJOS_MAXIMOS)))
    else localStorage.removeItem(clave(asset, moneda))
  } catch { /* sin almacenamiento: el dibujo vive mientras la página esté abierta */ }
}

/** El precio a guardar: el del toque viene con 15 decimales. 4 decimales y,
 *  abajo de 1, 6 cifras significativas (como backend/estructura.precio_redondo). */
export const precioRedondo = (x) => (Math.abs(x) >= 1 ? Math.round(x * 1e4) / 1e4 : Number(x.toPrecision(6)))

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
