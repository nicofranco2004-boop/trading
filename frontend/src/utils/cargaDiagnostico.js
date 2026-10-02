// cargaDiagnostico — los pedidos de Diagnóstico y Perfil de inversor
// (pages/Insights.jsx), en el orden y con la paciencia con que se hacen.
//
// Vive fuera del componente para que las pruebas atraviesen EL MISMO camino
// que producción (el tope de los precios, un pedido caído, el reintento) con un
// `get` de mentira y relojes de mentira. Antes era el cuerpo de `loadAll` y
// ningún test lo recorría: cada prueba miraba una función suelta.
//
// Qué hace:
//   1. Pide las 9 piezas a la vez. Cada una avisa al volver (`marcar`) con lo
//      que trajo, para el cargador (utils/cargaPorPasos → pasosDiagnostico).
//   2. Los precios salen apenas están tus posiciones y tus brokers, a la par
//      del resto.
//   3. Si falló algo imprescindible, termina ahí (la pantalla muestra el error;
//      esperar los precios sería demorar el aviso hasta 8 s para nada).
//   4. Si no, espera los precios hasta TOPE_PRECIOS_MS. Pasado el tope devuelve
//      sin ellos y con la promesa (`preciosTarde`) para completar cuando lleguen.
//
// La curva de Performance NO se pide acá: la pide un solo lugar (el efecto de
// Insights, con el benchmark, el modo y la moneda elegidos). Se pedía también
// acá, sin benchmark, y esta respuesta —S&P— pisaba la del efecto: un usuario en
// pesos veía el S&P con el rótulo "Inflación" (revisión del 2026-10-02). Lo que
// la carga tiene que esperar de ella entra por `esperarTambien`.

import { PIEZAS_IMPRESCINDIBLES, mesesDelHistorial } from './cargaPorPasos'

// Cuánto más espera la página a los precios cuando todo lo demás ya llegó.
// Con Yahoo colgado (yf.download con dos descargas a la vez, ver backend
// pricing/yahoo.py) los precios podían no volver nunca y la página quedaba en
// "Cargando…" para siempre.
export const TOPE_PRECIOS_MS = 8000

const SIN_RESPUESTA = Symbol('sin respuesta')
const cuantosHay = (r) => (Array.isArray(r) ? r.length : true)
const activosDistintos = (r) => new Set((r || []).filter((p) => !p.is_cash).map((p) => p.asset)).size

// Devuelve { datos, falta, precios, preciosTarde }:
//   falta         — true si no volvió algo de `imprescindibles`.
//   precios       — el objeto de precios si llegaron a tiempo ({} si no
//                   había nada que cotizar); null si el pedido falló, si falló
//                   la cartera o si todavía no llegaron (ver preciosTarde).
//   preciosTarde  — pasado el tope: la promesa de los precios (resuelve en el
//                   objeto, o null si el pedido falla). Si no, null.
export async function cargarDiagnostico({
  get,
  simbolos,
  marcar = () => {},
  esperarTambien = [],
  imprescindibles = PIEZAS_IMPRESCINDIBLES,
  tope = TOPE_PRECIOS_MS,
}) {
  const fallaron = new Set()
  // `siFalla`: con qué seguir si el pedido no vuelve, para que uno caído no
  // tire el Promise.all entero.
  const pedir = (pieza, url, siFalla, cuenta = cuantosHay) => get(url)
    .then((r) => { marcar(pieza, cuenta(r)); return r })
    .catch(() => { fallaron.add(pieza); marcar(pieza, 'error'); return siFalla })

  const pPos = pedir('positions', '/positions', null, activosDistintos)
  const pBkrs = pedir('brokers', '/brokers', null)
  const pPrecios = Promise.all([pPos, pBkrs]).then(([pos, bkrs]) => {
    // Sin cartera no hay qué cotizar (y la pantalla muestra el error).
    if (pos == null || bkrs == null) return null
    const lista = simbolos(pos, bkrs)
    if (!lista) { marcar('prices'); return {} }
    return get(`/prices?symbols=${lista}`)
      .then((r) => { marcar('prices'); return r })
      .catch(() => { marcar('prices', 'error'); return null })
  })

  const [monthly, positions, brokers, benchmarks, snapshots, dolar, operations, commissions, profile] = await Promise.all([
    pedir('monthly', '/monthly', [], mesesDelHistorial),
    pPos,
    pBkrs,
    pedir('benchmarks', '/benchmarks', null),
    // Historia completa, no 30 días: los snapshots son la serie a valor de
    // MERCADO y corrigen toda la cadena mensual (applyMtmToMonthly), no solo
    // el detalle diario del último mes.
    pedir('snapshots', '/snapshots?days=3650', []),
    pedir('dolar', '/dolar', null),
    pedir('operations', '/operations', []),
    pedir('commissions', '/insights/commissions', null),
    pedir('profile', '/auth/investor-profile', {}),
    ...esperarTambien,
  ])
  const datos = { monthly, positions, brokers, benchmarks, snapshots, dolar, operations, commissions, profile }

  if (imprescindibles.some((p) => fallaron.has(p))) {
    return { datos, falta: true, precios: null, preciosTarde: null }
  }

  let reloj
  const precios = await Promise.race([
    pPrecios,
    new Promise((r) => { reloj = setTimeout(() => r(SIN_RESPUESTA), tope) }),
  ])
  clearTimeout(reloj)
  if (precios === SIN_RESPUESTA) return { datos, falta: false, precios: null, preciosTarde: pPrecios }
  return { datos, falta: false, precios, preciosTarde: null }
}

// Un pedido GET que ya está en curso no se repite: el que llega segundo
// recibe la misma respuesta. Para el reintento: los precios del primer intento
// pueden seguir bajando, y dos descargas a la vez es justo lo que cuelga a
// Yahoo (ver memoria del proyecto: yf.download comparte un dict global).
export function getCompartido(get) {
  const enCurso = new Map()
  return (url) => {
    if (!enCurso.has(url)) {
      const p = get(url)
      enCurso.set(url, p)
      const soltar = () => { if (enCurso.get(url) === p) enCurso.delete(url) }
      p.then(soltar, soltar)
    }
    return enCurso.get(url)
  }
}
