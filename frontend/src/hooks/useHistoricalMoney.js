// useHistoricalMoney — formatter que combina toggle global ARS/USD con FX
// histórico per-fecha. Pensado para listas con valores USD viejos (operaciones,
// movimientos, P&L realizado) donde el blue de cuando se generó NO es el de hoy.
//
// Prioridad de FX cuando currency==='ARS':
//   1. `stampedFx` (preferido) — fx_to_usd stampeado en el row al guardar
//   2. `lookupRate(history, dateIso)` — busca en /api/fx-rates por fecha
//   3. `tcBlue` actual — último fallback
//
// Cuando currency==='USD', no convierte (el valor canónico USD se formatea
// directo).

import {
  useCurrency,
  fmtConvertedRaw,
  fmtConvertedCompactRaw,
} from '../contexts/CurrencyContext'
import { useFxHistory } from './useFxHistory'

/**
 * resolveHistoricalFx — chain de prioridad para conseguir el FX a aplicar a
 * un valor USD. Pure function — testeable sin React.
 *
 * @param {string} currency — 'USD' | 'ARS' (toggle global)
 * @param {number} tcBlue — blue actual (fallback final)
 * @param {object} opts — { stampedFx?, dateIso? }
 * @param {(date: string) => number | null} getRateForDate — lookup histórico
 * @returns {number} FX para multiplicar. 1 si currency='USD' (no convertir).
 */
export function resolveHistoricalFx(currency, tcBlue, opts, getRateForDate) {
  if (currency !== 'ARS') return 1
  const stamped = opts?.stampedFx
  // ⚠️ El stamp SOLO sirve si el evento ocurrió en PESOS: ahí `fx_to_usd` es el TC
  // que se usó para llevarlo a USD, así que invertirlo reconstruye el nominal real.
  // En un evento en DÓLARES el backend estampa 1.0 (no hubo conversión) — tomarlo
  // como "ARS por USD" mostraría un P&L de USD 10.000 como "$10.000" (~1500× menos).
  // Para esos casos ignoramos el stamp y vamos al blue de la fecha, que es lo que
  // el usuario quiere ver: cuántos pesos representaban esos dólares ese día.
  const rowCcy = (opts?.rowCurrency || '').toUpperCase()
  const stampUsable = stamped && stamped > 0 && !(rowCcy && rowCcy !== 'ARS')
  if (stampUsable) return stamped
  const date = opts?.dateIso
  if (date && typeof getRateForDate === 'function') {
    const r = getRateForDate(date)
    if (r && r > 0) return r
  }
  return tcBlue > 0 ? tcBlue : 1
}

export function useHistoricalMoney() {
  const { currency, tcBlue } = useCurrency()
  const { getRateOrFallback, fxKey } = useFxHistory(tcBlue)

  function resolveFx(opts) {
    return resolveHistoricalFx(currency, tcBlue, opts, getRateOrFallback)
  }

  function convertedValue(usdValue, opts) {
    if (usdValue == null || !Number.isFinite(usdValue)) return null
    const fx = resolveFx(opts)
    return currency === 'ARS' ? usdValue * fx : usdValue
  }

  /**
   * Formatea un valor USD en la currency del toggle, usando FX histórico cuando
   * está disponible.
   * @param {number} usdValue — valor USD canónico del backend
   * @param {object} opts
   * @param {number} [opts.stampedFx] — FX stampeado en la fila (preferido)
   * @param {string} [opts.dateIso] — fecha del row para lookup histórico
   * @param {boolean} [opts.signed] — agregar '+'/'−' prefix
   * @param {number} [opts.decimals] — max fraction digits
   */
  function fmtMoneyAt(usdValue, opts = {}) {
    const v = convertedValue(usdValue, opts)
    if (v == null) return '—'
    return fmtConvertedRaw(v, currency, opts)
  }

  /** Mismo que fmtMoneyAt pero compacto (k/M/B abbreviation). */
  function fmtMoneyCompactAt(usdValue, opts = {}) {
    const v = convertedValue(usdValue, opts)
    if (v == null) return '—'
    return fmtConvertedCompactRaw(v, currency, opts)
  }

  /**
   * sumConvertedAt — convert-then-sum: convierte CADA fila con SU propio FX
   * histórico y recién ahí suma. Es la única forma de que un total coincida con
   * las filas que muestra (`total === Σ filas`), incluso con una sola fila.
   *
   * Sumar los USD y convertir el total al FX de hoy (convert-after-sum) re-expresa
   * ganancias viejas al dólar actual → infla un resultado que ya ocurrió. Mismo
   * criterio que MonthlySummary (valueAt por mes) y que MovementRow ("un retiro de
   * $1000 USD en 2024 no se muestra hoy como $1.466.000").
   *
   * @param {Array} rows — filas con valor USD canónico
   * @param {(row) => number|null} getUsd — extractor del valor USD de cada fila
   * @returns {number} total YA convertido a la currency del toggle
   */
  function sumConvertedAt(rows, getUsd) {
    let total = 0
    for (const r of (rows || [])) {
      const usd = getUsd(r)
      if (usd == null || !Number.isFinite(usd)) continue
      const v = convertedValue(usd, {
        stampedFx: r?.fx_to_usd, dateIso: r?.date, rowCurrency: r?.currency,
      })
      if (v != null) total += v
    }
    return total
  }

  return {
    currency,
    fmtMoneyAt,
    fmtMoneyCompactAt,
    convertedValue,
    resolveFx,
    sumConvertedAt,
    // Para memoizar agregados: cambia cuando cambia la serie FX (no por render).
    fxKey,
  }
}
