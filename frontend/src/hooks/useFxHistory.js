// useFxHistory — Phase C (2026-05-31).
//
// Fetcha /api/fx-rates una vez por sesión y expone helpers de lookup por
// fecha. Cuando el toggle global está en ARS y el caller necesita convertir
// un valor histórico (snapshot, monthly entry, operación vieja), debe usar
// el TC que existía en ESA fecha — no el actual.
//
// Fallbacks:
//   • Si la API falla → devuelve un map vacío + fallbackTcValuacion (el actual).
//   • Si una fecha no está en el map → busca el día anterior más cercano.
//   • Si nada existe → fallbackTcValuacion.
//
// El hook es global-cache friendly: una sola instancia mantiene el map.
// Re-renderizados no disparan nuevos fetches.

import { useEffect, useState, useMemo, useRef } from 'react'
import { api } from '../utils/api'
import { indexarSerie, tcDeFechaDetalle, dolarDelDiaDe } from '../utils/tcHistorico'
import { dolarMensualDe } from '../utils/capitalAportado'

// Los helpers puros (indexar la serie, buscar el dólar de una fecha) viven en
// utils/tcHistorico.js, testeables sin React.

// Cache módulo-level: una sola request por sesión / página. Compartido
// entre todos los consumers (Dashboard chart, Reports cards, etc).
//
// Audit fix C3 (2026-05-31): trackeamos failure state aparte, con retry
// cooldown. Antes: si el primer fetch fallaba (network blip), _fxCacheData
// quedaba `[]` permanente y nunca reintentábamos en la sesión. Ahora: tras
// fallo esperamos RETRY_COOLDOWN_MS y permitimos un nuevo intento (típico
// next mount o cuando otro consumer llama).
let _fxCachePromise = null
let _fxCacheData = null
let _fxCacheError = false
let _fxCacheErrorAt = 0
const RETRY_COOLDOWN_MS = 30_000

export function fetchFxHistory() {
  // Request en vuelo → comparte la misma promesa
  if (_fxCachePromise) return _fxCachePromise
  // Data válida cacheada → resolve directo
  if (_fxCacheData && _fxCacheData.length > 0) return Promise.resolve(_fxCacheData)
  // Error reciente → no reintentar hasta cooldown (devuelve cache vacío sin
  // disparar más network calls; el caller usa fallback tcValuacion automáticamente)
  if (_fxCacheError && Date.now() - _fxCacheErrorAt < RETRY_COOLDOWN_MS) {
    return Promise.resolve(_fxCacheData || [])
  }
  // Reintento permitido
  _fxCacheError = false
  // Sin `days`: la serie ENTERA. Pedía `days=3650` creyendo pedir diez años, y
  // el backend cortaba por CANTIDAD DE FILAS — 3.650 ruedas, que con una serie
  // que arranca en 2011 dejaba 1.984 días de cotización afuera. Toda fecha
  // anterior a 2016-06-09 caía al fallback (el dólar de HOY) sin avisar.
  // Acá no hay ventana que elegir: hay que poder convertir cualquier fecha en la
  // que el usuario tenga una operación, y esa fecha la elige él, no nosotros.
  _fxCachePromise = api.get('/fx-rates')
    .then(rows => {
      _fxCacheData = Array.isArray(rows) ? rows : []
      _fxCachePromise = null
      // Empty response cuenta como soft-failure (backend nunca devolvió data)
      if (_fxCacheData.length === 0) {
        _fxCacheError = true
        _fxCacheErrorAt = Date.now()
      }
      return _fxCacheData
    })
    .catch(() => {
      _fxCachePromise = null
      _fxCacheData = []
      _fxCacheError = true
      _fxCacheErrorAt = Date.now()
      return _fxCacheData
    })
  return _fxCachePromise
}

// Export para tests — permite resetear el module-level cache entre tests.
export function _resetFxCacheForTesting() {
  _fxCachePromise = null
  _fxCacheData = null
  _fxCacheError = false
  _fxCacheErrorAt = 0
}

/**
 * Hook que devuelve el dólar elegido de cada fecha (MEP; blue antes de 2018).
 * La tabla por mes (el cierre de cada mes) la da `useDolarMensual`, abajo.
 *
 * @param {number} fallbackTcValuacion — el dólar de hoy (último recurso)
 * @returns {{
 *   loaded: boolean,
 *   getRateForDate: (dateIso: string) => number | null,
 *   getRateOrFallback: (dateIso: string) => number,
 * }}
 */
export function useFxHistory(fallbackTcValuacion = 1415) {
  const [data, setData] = useState(_fxCacheData)
  const fallbackRef = useRef(fallbackTcValuacion)
  fallbackRef.current = fallbackTcValuacion

  useEffect(() => {
    let cancelled = false
    if (_fxCacheData) {
      setData(_fxCacheData)
      return () => { cancelled = true }
    }
    fetchFxHistory().then(rows => {
      if (!cancelled) setData(rows)
    })
    return () => { cancelled = true }
  }, [])

  // Asume que el backend devuelve rows ya ordenadas ascendentemente (la
  // búsqueda binaria de tcHistorico lo necesita).
  const sortedRows = useMemo(() => {
    if (!data || !Array.isArray(data)) return []
    return data
  }, [data])

  // Índice de la serie (fechas ordenadas + MEP y blue por fecha) para resolver
  // por búsqueda BINARIA en vez del scan lineal. Los agregados (convert-then-sum
  // en headers de grupo y KPIs) llaman esto una vez POR OPERACIÓN en cada
  // render: con ~15 años de serie y cientos de ops, el scan lineal era
  // O(ops × filas) por render. Se construye una sola vez por cambio de `data`.
  const fxIndex = useMemo(() => indexarSerie(sortedRows), [sortedRows])

  // EL DÓLAR ELEGIDO DE ESA FECHA (ver utils/tcHistorico.js): el MEP del día, o
  // el blue antes de que existiera el MEP en la serie. Hasta el 2026-10-15 esto
  // devolvía el BLUE mientras el dólar de hoy era el MEP: lo viejo y lo de hoy
  // se pasaban a pesos con dos dólares distintos.
  function getRateForDate(dateIso) {
    return tcDeFechaDetalle(fxIndex, dateIso).tc
  }

  function getRateOrFallback(dateIso) {
    const r = getRateForDate(dateIso)
    return r != null && r > 0 ? r : fallbackRef.current
  }

  // El mismo dólar con TRAZA: además del TC, de dónde salió y de QUÉ FECHA.
  //
  // La fecha importa: `mep_venta` es nullable y el cron nocturno puede no
  // escribirlo, así que el MEP "del 15/08" puede ser en realidad el del 13/08.
  // Quien le muestra el número a un usuario tiene que poder decirle qué día está
  // usando. Devuelve `{tc: null}` en vez de caer al fallback: sugerir un monto
  // con el dólar de HOY para un cupón de hace dos años es peor que no sugerir nada.
  function getMepDetail(dateIso) {
    return tcDeFechaDetalle(fxIndex, dateIso)
  }

  // Espeja `fx_for_date` del backend (MEP, red al blue): lo usan las vistas
  // previas de depósitos y ventas con fecha, para no mostrar un dólar distinto
  // del que se va a guardar. Hoy es el mismo dólar que `getRateOrFallback`.
  function getMepOrFallback(dateIso) {
    return getRateOrFallback(dateIso)
  }

  return {
    loaded: !!data,
    getRateForDate,
    getRateOrFallback,
    getMepOrFallback,
    getMepDetail,
    // Clave estable para memoizar cálculos que dependen de la serie: cambia
    // cuando la serie termina de cargar (o se recarga), no en cada render.
    fxKey: fxIndex.dates.length,
  }
}

/**
 * useDolarMensual — el dólar del cierre de cada mes ({'AAAA-MM': dólar}, ver
 * `dolarMensualDe`) de la misma serie de /api/fx-rates (cacheada por sesión),
 * para llevar a pesos lo aportado en dólares (utils/capitalAportado.js) y todo
 * cálculo que trabaja por mes (Reportes, el resumen mensual, Análisis). Es el
 * mismo dólar que `getRateForDate`, al cierre de cada mes.
 *
 * `listo` = la serie ya respondió (o falló: entonces el mapa viene vacío y la
 * cuenta cae al dólar de hoy). Las pantallas en pesos esperan a `listo` antes de
 * mostrar "Capital aportado" como número firme: sin esto, durante la carga se
 * veía el número calculado con el dólar de hoy y la animación anunciaba una
 * diferencia que no existía.
 */
export function useDolarMensual() {
  const [filas, setFilas] = useState(_fxCacheData)
  useEffect(() => {
    let cancelled = false
    if (_fxCacheData) {
      setFilas(_fxCacheData)
      return () => { cancelled = true }
    }
    fetchFxHistory().then(rows => {
      if (!cancelled) setFilas(rows)
    })
    return () => { cancelled = true }
  }, [])
  const dolarMes = useMemo(() => dolarMensualDe(filas), [filas])
  // El dólar de UN DÍA, de la misma serie y con la misma regla que
  // `useFxHistory().getRateForDate` (el de cada fila de Movimientos): para los
  // aportes en dólares que tienen su día (utils/capitalAportado.js).
  const tcEnFecha = useMemo(() => dolarDelDiaDe(filas), [filas])
  return { dolarMes, tcEnFecha, listo: filas != null }
}
