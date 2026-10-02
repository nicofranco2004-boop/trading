// guardarValuacion — la regla de lo que se GUARDA calculado con precios: la
// foto diaria (POST /snapshots, Dashboard) y el P&L no realizado del mes
// (/monthly/sync-unrealized, que escriben el Dashboard y el resumen mensual).
//
// Dos condiciones, las dos del cron del backend:
//   · al dólar MEP: la historia guardada vive al MEP. Mirando en CCL, guardar
//     mezclaba los dos dólares en la misma serie (el Dashboard lo chequeaba en la
//     foto pero no en el P&L; el resumen mensual, sí).
//   · con precios: coberturaDePrecios ≥ COBERTURA_MINIMA (utils/valuation). El
//     resumen mensual guardaba P&L 0 con /prices caído (revisión 2026-10-02).
//
// El P&L se escribe SOLO por guardarPnlNoRealizado, que aplica la regla adentro:
// un escritor nuevo no puede olvidársela (lo vigila coberturaEscritores.test.js).

import { COBERTURA_MINIMA } from './valuation'

export function sePuedeGuardar({ cobertura, valuationDollar }) {
  return valuationDollar === 'mep' && cobertura >= COBERTURA_MINIMA
}

// filas: [{ broker, pnl }] (incluida la fila 'global'). Devuelve si guardó.
export async function guardarPnlNoRealizado(post, filas, condiciones) {
  if (!sePuedeGuardar(condiciones)) return false
  await Promise.all(filas.map(({ broker, pnl }) =>
    post('/monthly/sync-unrealized', { broker, pnl_unrealized_usd: +Number(pnl || 0).toFixed(4) }).catch(() => {})))
  return true
}
