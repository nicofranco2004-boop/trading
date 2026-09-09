// useCerSeries — la serie de ajuste de los bonos CER, UNA vez por sesión.
//
// POR QUÉ EXISTE
// ─────────────
// La serie la pedía sólo `Positions.jsx`, y encima PEREZOSAMENTE: recién cuando
// el usuario expandía la fila de un bono. Todo lo que necesita el ajuste dependía
// de eso — el inbox de cobranzas pendientes, el monto que pre-llena el modal que
// REGISTRA el cobro, los chips de próximo pago — y las otras pantallas que
// muestran los mismos pagos (`Events`, la card de próximos eventos) directamente
// no la pedían nunca.
//
// Con la fuente de CER caída daba lo mismo: sin serie, el factor es 1 y todos
// mostraban nominal. Repuesta la serie, esa asimetría se convierte en dos montos
// distintos para el MISMO cupón en dos pantallas de la misma app.
//
// Mismo patrón que `useFxHistory`: cache module-level, una request por sesión,
// compartida entre todos los consumidores.
import { useEffect, useState } from 'react'
import { api } from '../utils/api'

let _promise = null
let _data = null          // { series, stale, basis }
let _error = false
let _errorAt = 0
const RETRY_COOLDOWN_MS = 30_000

const VACIO = { series: {}, stale: true, basis: 'CER' }

export function fetchCerSeries() {
  if (_promise) return _promise
  if (_data) return Promise.resolve(_data)
  if (_error && Date.now() - _errorAt < RETRY_COOLDOWN_MS) {
    return Promise.resolve(_data || VACIO)
  }
  _error = false
  _promise = api.get('/bond-indices/CER')
    .then(res => {
      const series = res?.series || {}
      // `basis` dice con qué serie ajustó el backend de verdad: con el endpoint
      // de CER caído sirve UVA, que el BCRA actualiza POR CER (el ratio entre
      // dos fechas es el mismo). Un backend viejo no lo manda → 'CER'.
      _data = { series, stale: !!res?.stale, basis: res?.basis || 'CER' }
      _promise = null
      if (Object.keys(series).length === 0) { _error = true; _errorAt = Date.now() }
      return _data
    })
    .catch(() => {
      _promise = null
      _data = null
      _error = true
      _errorAt = Date.now()
      return VACIO
    })
  return _promise
}

/** Export para tests — resetea el cache module-level. */
export function _resetCerCacheForTesting() {
  _promise = null; _data = null; _error = false; _errorAt = 0
}

/**
 * @param {boolean} enabled  pedirla sólo si hace falta (el usuario tiene un CER).
 * @returns {{ series: object|null, stale: boolean, basis: string, loaded: boolean }}
 *          `series` arranca en null (= "todavía no sé"), que es distinto de {}
 *          (= "no hay serie"): la tarjeta del bono muestra "Cargando…" con uno y
 *          "Serie no disponible" con el otro.
 */
export function useCerSeries(enabled = true) {
  const [estado, setEstado] = useState(() => (_data ? { ..._data, loaded: true } : null))

  useEffect(() => {
    if (!enabled || estado) return
    let vivo = true
    fetchCerSeries().then(d => { if (vivo) setEstado({ ...d, loaded: true }) })
    return () => { vivo = false }
  }, [enabled, estado])

  return estado || { series: null, stale: false, basis: 'CER', loaded: false }
}
