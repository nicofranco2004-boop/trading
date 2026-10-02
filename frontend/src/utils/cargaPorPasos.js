// cargaPorPasos — qué dice el cargador de Novedades mientras trae los datos y
// cuándo aparece. Sin React: lo dibuja components/novedades/CargaPorPasos.jsx.
//
// Un cargador HONESTO: cada renglón es un pedido real a la API y se tilda
// cuando ESE pedido vuelve, con lo que trajo ("12 activos", "33 eventos").
// Nada gira de adorno. Los chips son tus empresas: barren mientras se buscan
// sus eventos y, cuando llega la respuesta, cada uno muestra cuántos encontró.
//
// Aparece sólo si la carga TARDA (DEMORA_CARGADOR_MS). Con lo guardado en el
// servidor la pantalla responde en milisegundos (medido el 2026-10-02: 4-9 ms
// después de una publicación), y un cargador que se prende y se apaga en un
// parpadeo es ruido, no información. Cuando tarda —la primera vez, una
// ventana nueva, los precios, Google News— se ve qué se está esperando.

import { isCrypto } from './crypto'
import { isBondTicker, inferType } from './tickers'
import { getBondMeta } from './bondMeta'
import { isFciSym } from './valuation'

export const DEMORA_CARGADOR_MS = 250

// "1 evento" / "12 eventos".
export function cuantos(n, singular, plural) {
  return `${n} ${n === 1 ? singular : plural}`
}

// Un renglón del cargador. `dato` null = el pedido no volvió todavía.
//   { id, etiqueta, estado: 'cargando' | 'listo' | 'error', detalle }
export function paso(id, etiqueta, dato, detalleListo, { error = false } = {}) {
  if (error) return { id, etiqueta, estado: 'error', detalle: 'no respondió' }
  if (dato == null) return { id, etiqueta, estado: 'cargando', detalle: null }
  const detalle = typeof detalleListo === 'function' ? detalleListo(dato) : (detalleListo ?? null)
  return { id, etiqueta, estado: 'listo', detalle }
}

const NO_ES_EMPRESA = new Set(['USDT', 'USD', 'ARS'])
const TIPOS_SIN_EVENTOS = new Set(['bond', 'bono', 'on', 'letra', 'fci', 'fund', 'crypto', 'cash'])

// Las empresas de tu cartera: lo que tiene earnings y dividendos. El mismo
// recorte que hace el servidor en /events/portfolio (sin efectivo, bonos ni
// cripto), con lo que la pantalla sabe de cada activo. Un chip no puede decir
// "busqué los earnings de AL30": el servidor no los busca, un bono no tiene.
export function empresasDeLaCartera(positions) {
  const vistas = new Set()
  const out = []
  for (const p of positions || []) {
    const a = (p?.asset || '').toUpperCase()
    if (!a || p.is_cash || NO_ES_EMPRESA.has(a) || vistas.has(a)) continue
    if (isCrypto(a) || isBondTicker(a) || getBondMeta(a) || inferType(a) === 'bond') continue
    // Un fondo del catálogo ("FCI:COCOS-RENDIMIENTO-A") no es una empresa: salía
    // como chip con "–" en producción (2026-10-02). El servidor tampoco lo busca.
    if (isFciSym(a) || a.includes(' ')) continue
    if (TIPOS_SIN_EVENTOS.has(String(p.asset_type || '').toLowerCase())) continue
    vistas.add(a)
    out.push(a)
  }
  return out
}

export const MAXIMO_CHIPS = 16

// Los chips: mientras `items` es null se están buscando; cuando llegan, cada
// empresa con cuántos trajo (los eventos con su ticker).
export function chipsDeEmpresas(empresas, items, maximo = MAXIMO_CHIPS) {
  const cuenta = new Map()
  for (const it of items || []) {
    const t = String(it?.ticker || '').toUpperCase()
    if (t) cuenta.set(t, (cuenta.get(t) || 0) + 1)
  }
  return (empresas || []).slice(0, maximo).map(simbolo => items == null
    ? { simbolo, estado: 'buscando', cuenta: null }
    : { simbolo, estado: 'listo', cuenta: cuenta.get(simbolo) || 0 })
}

function activosDe(positions) {
  return new Set((positions || []).filter(p => p && !p.is_cash && p.asset).map(p => p.asset.toUpperCase())).size
}

// Eventos · "Para ti": tu cartera, los eventos de tus acciones y los precios.
// La lista aparece con los dos primeros; lo que sale de los precios (cuánto te
// toca, el peso de cada evento) se suma cuando llegan — si el cargador sigue a
// la vista, su renglón se tilda ahí.
export function pasosEventosParaTi({ positions = null, eventos = null, precios = null, fallo = {} } = {}) {
  return [
    paso('cartera', 'Tu cartera', positions, ps => cuantos(activosDe(ps), 'activo', 'activos')),
    paso('acciones', 'Earnings y dividendos de tus acciones', eventos,
      evs => cuantos(evs.length, 'evento', 'eventos'), { error: fallo.cartera }),
    paso('precios', 'Precios para calcular cuánto te toca', precios, 'al día'),
  ]
}

// Eventos · "Populares": el calendario del mercado y tu cartera (para marcar
// "en tu cartera" lo que tenés).
export function pasosEventosPopulares({ eventos = null, positions = null, fallo = {} } = {}) {
  return [
    paso('mercado', 'Earnings de las empresas más seguidas, la Fed y el INDEC', eventos,
      evs => cuantos(evs.length, 'evento', 'eventos'), { error: fallo.mercado }),
    paso('cartera', 'Tu cartera, para marcar lo que tenés', positions,
      ps => cuantos(activosDe(ps), 'activo', 'activos')),
  ]
}

// Noticias: los dos pedidos, cada uno con su tilde. El de la pestaña que
// estás mirando va primero.
export function pasosNoticias({ cartera = null, mercado = null, fallo = {}, primero = 'portfolio' } = {}) {
  const deTuCartera = paso('cartera', 'Noticias de tus activos en Google News', cartera,
    ns => cuantos(ns.length, 'noticia', 'noticias'), { error: fallo.cartera })
  const delMercado = paso('mercado', 'Noticias del mercado: la Fed, Wall Street, el Merval y el BCRA', mercado,
    ns => cuantos(ns.length, 'noticia', 'noticias'), { error: fallo.mercado })
  return primero === 'market' ? [delMercado, deTuCartera] : [deTuCartera, delMercado]
}

// Diagnóstico y Perfil de inversor (pages/Insights.jsx): los 10 pedidos más los
// precios, agrupados en lo que la persona reconoce. `llego[pieza]` es la cuenta
// de lo que trajo (número), `true` si volvió sin cuenta, o 'error'. Un grupo se
// tilda cuando volvieron TODAS sus piezas.
const GRUPOS_DIAGNOSTICO = [
  { id: 'historial', etiqueta: 'Tu historial mes a mes', piezas: ['monthly'], cuenta: ['mes', 'meses'] },
  { id: 'cartera', etiqueta: 'Tus posiciones', piezas: ['positions', 'brokers'], cuenta: ['activo', 'activos'] },
  { id: 'operaciones', etiqueta: 'Tus operaciones', piezas: ['operations', 'commissions'], cuenta: ['operación', 'operaciones'] },
  { id: 'fotos', etiqueta: 'La foto diaria de tu cartera', piezas: ['snapshots'], cuenta: ['día', 'días'] },
  { id: 'comparacion', etiqueta: 'Comparación con el S&P, el dólar y la inflación', piezas: ['benchmarks', 'performance', 'dolar'] },
  { id: 'perfil', etiqueta: 'Tu test de inversor', piezas: ['profile'] },
  { id: 'precios', etiqueta: 'Precios de hoy', piezas: ['prices'] },
]

export function pasosDiagnostico(llego = {}, { perfilPrimero = false } = {}) {
  const grupos = perfilPrimero
    ? [GRUPOS_DIAGNOSTICO.find((g) => g.id === 'perfil'), ...GRUPOS_DIAGNOSTICO.filter((g) => g.id !== 'perfil')]
    : GRUPOS_DIAGNOSTICO
  return grupos.map((g) => {
    const estados = g.piezas.map((p) => llego[p])
    if (estados.some((e) => e === 'error')) return paso(g.id, g.etiqueta, null, null, { error: true })
    if (estados.some((e) => e == null)) return paso(g.id, g.etiqueta, null)
    const n = llego[g.piezas[0]]
    const detalle = g.cuenta && typeof n === 'number' ? cuantos(n, ...g.cuenta) : (g.id === 'precios' ? 'al día' : null)
    return paso(g.id, g.etiqueta, true, detalle)
  })
}
