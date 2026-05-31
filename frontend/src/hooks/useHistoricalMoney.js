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

export function useHistoricalMoney() {
  const { currency, tcBlue } = useCurrency()
  const { getRateOrFallback } = useFxHistory(tcBlue)

  function resolveFx(opts) {
    if (currency !== 'ARS') return 1
    const stamped = opts?.stampedFx
    if (stamped && stamped > 0) return stamped
    const date = opts?.dateIso
    if (date) return getRateOrFallback(date)
    return tcBlue
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

  return {
    currency,
    fmtMoneyAt,
    fmtMoneyCompactAt,
  }
}
