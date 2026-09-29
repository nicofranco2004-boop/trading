// useMarketIndices — las cotizaciones de referencia (S&P, Nasdaq, Merval,
// Bitcoin, Ethereum, Oro) que muestran la cinta de arriba y las tarjetas del
// inicio. Salen de GET /home/indices → home/market.py `get_indices_strip()`.
//
// UN dueño para todos los que las muestran. Antes la barra del celular y las
// tarjetas del inicio pedían el endpoint cada una por su cuenta, y lo pedían
// UNA vez: la barra quedaba con el dato de cuando se abrió la app hasta que
// alguien tiraba hacia abajo para refrescar. Ahora hay una sola copia en
// memoria, un solo pedido aunque la miren dos componentes a la vez, y se
// refresca sola cada REFRESH_MS mientras alguien la esté mostrando.
//
// Cada cuánto: el servidor las guarda 15 minutos (el `_cached` de
// home/market.py, que devuelve la guardada y la renueva por detrás). Pedirlas
// más seguido que eso no trae datos más nuevos, sólo carga; cada 5 minutos el
// dato que se ve tiene como mucho ~20 minutos. Con la pestaña oculta no se
// pide nada: al volver, si pasó el plazo, se pide en el momento.
//
// Si un refresco falla se QUEDAN los datos que había: un corte de red de un
// segundo no puede vaciar la cinta.
//
// El modo demo (utils/demo.js) sirve su propio juego de cotizaciones. Si la
// pestaña entra o sale del demo sin recargar, lo guardado es del otro mundo:
// se descarta y se vuelve a pedir.

import { useSyncExternalStore } from 'react'
import { api } from '../utils/api'
import { isDemoMode } from '../utils/demo'

export const REFRESH_MS = 5 * 60 * 1000

const INICIAL = { items: [], loading: true, error: null, fetchedAt: 0, demo: null }

let _state = INICIAL
let _inflight = null
let _timer = null
const _subs = new Set()

function _set(patch) {
  _state = { ..._state, ...patch }
  _subs.forEach(fn => fn())
}

// Pide las cotizaciones YA (el gesto de tirar hacia abajo en el celular, y el
// refresco periódico). Si hay un pedido en vuelo, devuelve ése.
export function refreshMarketIndices() {
  if (_inflight) return _inflight
  const demo = isDemoMode()
  _inflight = api.get('/home/indices')
    .then(d => {
      _set({ items: Array.isArray(d?.items) ? d.items : [], loading: false, error: null, fetchedAt: Date.now(), demo })
    })
    .catch(ex => {
      _set({ loading: false, error: ex?.message || 'No pudimos cargar las cotizaciones', fetchedAt: Date.now(), demo })
    })
    .finally(() => { _inflight = null })
  return _inflight
}

function _ensureFresh() {
  const demo = isDemoMode()
  if (_state.fetchedAt && _state.demo !== demo) {
    _set({ ...INICIAL })
  }
  if (Date.now() - _state.fetchedAt >= REFRESH_MS) refreshMarketIndices()
}

function _onVisibility() {
  if (document.visibilityState === 'visible') _ensureFresh()
}

// Exportado para los tests; los componentes usan el hook.
export function subscribeMarketIndices(fn) {
  _subs.add(fn)
  if (_subs.size === 1) {
    // El reloj pide sin mirar la edad del dato: si mirara, un pedido que tardó
    // 300 ms quedaría "300 ms más joven" que el plazo y se salteaba una vuelta.
    _timer = setInterval(() => {
      if (document.visibilityState !== 'hidden') refreshMarketIndices()
    }, REFRESH_MS)
    document.addEventListener('visibilitychange', _onVisibility)
  }
  _ensureFresh()
  return () => {
    _subs.delete(fn)
    if (_subs.size === 0) {
      clearInterval(_timer)
      _timer = null
      document.removeEventListener('visibilitychange', _onVisibility)
    }
  }
}

const _snapshot = () => _state

// { items, loading, error } — items con la forma del backend:
// { symbol, label, kind, price, change_pct }.
export function useMarketIndices() {
  return useSyncExternalStore(subscribeMarketIndices, _snapshot, _snapshot)
}

// Las que tienen algo para mostrar. Una cotización que yfinance no devolvió
// llega con price y change_pct en null: en una tarjeta fija un "—" se lee bien,
// pero una cinta que pasa guiones es ruido.
export function conDato(items) {
  return (items || []).filter(it => it && (it.price != null || it.change_pct != null))
}

// Sólo para tests: vuelve el módulo a cero.
export function _resetMarketIndices() {
  clearInterval(_timer)
  _timer = null
  _inflight = null
  _subs.clear()
  _state = INICIAL
}

export function _getMarketIndicesState() {
  return _state
}
