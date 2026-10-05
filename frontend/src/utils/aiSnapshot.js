// aiSnapshot — el contexto de cartera que viaja al modelo, armado en UN lugar.
// ═══════════════════════════════════════════════════════════════════════════
// Hasta ahora este bloque estaba copiado en cada superficie de chat (la página
// /ai y el drawer viejo), y con la voz iba a ser una tercera copia: el
// acompañante flotante puede preguntar desde CUALQUIER pantalla, así que
// también necesita el snapshot.
//
// Tres copias del mismo fetch es exactamente la forma del bug que este repo ya
// pagó con `buildSummary` (ver utils/aiSummary.js): dos funciones idénticas que
// dejaron de serlo y publicaban el doble. Por eso el fetch entero vive acá y
// las pantallas sólo lo llaman.
//
// LOS NOMBRES DE LOS ACTIVOS NO SE PONEN ACÁ (y el plan decía que sí)
// -----------------------------------------------------------------------
// La voz de Rendi tiene que decir "Nvidia", no "N-V-D-A". El plan original era
// pegarle el nombre a cada posición desde el catálogo del navegador
// (utils/tickers.js) y que la IA lo leyera del dato.
//
// No funciona: el servidor NO usa las posiciones que le mandamos. Las pisa
// enteras con las que valúa él desde la base (main.py, _enrich_chat_snapshot_
// valuation) y, antes de eso, recorta cada fila a una lista cerrada de campos
// (_sanitize_chat_snapshot). Un `name` puesto acá se caía dos veces.
//
// Así que los nombres los pone el backend, desde ai/asset_names.py — generado
// desde tickers.js, o sea el MISMO catálogo, con un test que se pone rojo si
// los dos se desincronizan.

import { api } from './api'
import { buildAiSummary } from './aiSummary'

// Operaciones capeadas a las 100 más recientes: el backend corta el snapshot
// en 200 KB y una cuenta con 500+ operaciones se caía sin esto.
export const MAX_OPERATIONS = 100

/**
 * Trae el contexto de cartera que consume el chat.
 * Rechaza si falla lo esencial (posiciones/mensual/brokers); las operaciones
 * son opcionales y un fallo ahí no tira el chat abajo.
 *
 * `alLlegar({ pieza, dato, error })` se llama apenas vuelve CADA pedido, en el
 * orden en que vuelven (salen los cuatro juntos): es lo que tilda cada renglón
 * del cargador de /ai. `pieza` es 'positions' | 'monthly' | 'brokers' |
 * 'operations'.
 *
 * `signal` cancela los cuatro (utils/lecturaDeCartera, cuando la lectura quedó
 * vieja antes de volver).
 */
export async function fetchAiSnapshot({ alLlegar, signal } = {}) {
  const pedir = (pieza, path) => api.get(path, signal ? { signal } : undefined).then(
    (dato) => { alLlegar?.({ pieza, dato }); return dato },
    (e) => { alLlegar?.({ pieza, error: true }); throw e },
  )
  const [positions, monthly, brokers, operations] = await Promise.all([
    pedir('positions', '/positions'),
    pedir('monthly', '/monthly'),
    pedir('brokers', '/brokers'),
    // Sin operations el prompt declara que existen pero llegan undefined, y
    // toda la sección abierto/cerrado queda vacía (audit #3, fix B3).
    pedir('operations', '/operations').catch(() => []),
  ])
  return {
    summary: buildAiSummary(positions, monthly),
    positions: Array.isArray(positions) ? positions : [],
    operations: Array.isArray(operations) ? operations.slice(0, MAX_OPERATIONS) : [],
    monthly: monthly || [],
    brokers: brokers || [],
  }
}

/**
 * Lo que se lee en pantalla de un snapshot: "12 posiciones · 3 brokers". De acá
 * lo toman la cabecera de /ai y la isla, así las dos dicen lo mismo.
 */
export function resumenDeCartera(snap) {
  if (!snap) return null
  const posiciones = snap.summary?.open_positions_count
  return {
    posiciones: Number.isFinite(posiciones) ? posiciones : null,
    brokers: Array.isArray(snap.brokers) ? snap.brokers.length : null,
  }
}
