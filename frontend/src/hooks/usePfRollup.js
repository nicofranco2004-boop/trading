// usePfRollup — fetch de plazos fijos + agregación por moneda, para sumar el PF
// a los totales de cualquier pantalla (Dashboard, Home) de forma consistente.
// Devuelve { ARS: {valor, capital}, USD: {valor, capital} }. El helper pfUsd
// lo convierte a USD con el blue.
import { useState, useEffect } from 'react'
import { api } from '../utils/api'
import { computePf } from '../utils/valuation'

export function usePfRollup(reloadKey) {
  const [totals, setTotals] = useState({})
  useEffect(() => {
    let alive = true
    api.get('/plazos-fijos')
      .then(pfs => {
        if (!alive) return
        const now = new Date().toISOString().slice(0, 10)
        const t = {}
        for (const pf of (pfs || [])) {
          const m = pf.moneda || 'ARS'
          if (!t[m]) t[m] = { valor: 0, capital: 0 }
          t[m].valor += computePf(pf, now).valorHoy
          t[m].capital += (+pf.capital || 0)
        }
        setTotals(t)
      })
      .catch(() => {})
    return () => { alive = false }
  }, [reloadKey])
  return totals
}

// Convierte los totales por moneda a USD. valueUsd = capital + devengado;
// investedUsd = capital (costo); pnlUsd = devengado.
export function pfUsd(totals, tcBlue) {
  const tc = tcBlue || 1415
  const valueUsd = (totals?.USD?.valor || 0) + (totals?.ARS?.valor || 0) / tc
  const investedUsd = (totals?.USD?.capital || 0) + (totals?.ARS?.capital || 0) / tc
  return { valueUsd, investedUsd, pnlUsd: valueUsd - investedUsd }
}
