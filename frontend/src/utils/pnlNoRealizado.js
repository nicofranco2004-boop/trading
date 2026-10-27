// pnlNoRealizado — el P&L no realizado de la cartera entera, en un solo lugar.
// ═══════════════════════════════════════════════════════════════════════════
// Es la cuenta del encabezado de Cartera (Positions.jsx), sacada de ahí para
// que el reporte en PDF de Análisis publique el MISMO número. Antes vivía
// inline en Positions y Análisis tenía su propia versión (`unrealizedPnl`:
// sin plazos fijos y, en pesos, convirtiendo el P&L en dólares), así que la
// misma cartera podía decir dos números distintos según la pantalla.
//
// Las reglas, tal cual estaban en Cartera:
//   • suma lo que valen y lo que costaron las tenencias de TODOS los brokers
//     (computeBrokerValue, el mismo motor de la tabla) + los plazos fijos
//     (capital + interés devengado; su P&L es el devengado);
//   • en DÓLARES, el costo sigue el modo elegido (`costBasis`): en 'purchase'
//     el invertido absorbe la devaluación;
//   • en PESOS, las cifras no dependen del modo: pesos nativos + tenencias en
//     dólares al dólar de hoy (`totalsToday`, costBasis 'today') × tcValuacion.
//
// ⚠️ Dos que todavía NO pasan por acá, anotados:
//   • PositionsMobile.jsx arma su encabezado sumando las filas (es "espejo del
//     desktop" por comentario, no por código);
//   • `unrealizedPnl` de Insights.jsx (sin plazos fijos) sigue alimentando el
//     diagnóstico: cambiarlo mueve reglas de hallazgos, que es otro cambio.

import { computeBrokerValue } from './valuation'

/** Lo que valen y lo que costaron todos los brokers, con un modo de costo. */
export function sumarBrokers({ brokers = [], positions, prices, tcValuacion, tcCedear, tcCripto, costBasis }) {
  let value = 0
  let invested = 0
  const byBroker = {}
  for (const b of brokers) {
    const r = computeBrokerValue(positions, prices, b, tcValuacion, tcCedear, tcCripto, costBasis)
    byBroker[b.name] = r
    value += r.value || 0
    invested += r.invested || 0
  }
  return { value, invested, byBroker }
}

/**
 * @param {object} a
 * @param {{value:number, invested:number}} a.totals       con el modo de costo elegido
 * @param {{value:number, invested:number}} a.totalsToday  con costBasis 'today'
 * @param {{valueUsd:number, investedUsd:number}} a.pf     pfUsd(...) de usePfRollup
 * @param {number} a.tcValuacion
 * @param {'USD'|'ARS'} a.moneda
 * @returns {{valor:number, invertido:number, pnl:number, pct:number}} en `moneda`
 */
export function pnlNoRealizado({ totals, totalsToday, pf, tcValuacion, moneda = 'USD' }) {
  const pfValor = pf?.valueUsd || 0
  const pfInvertido = pf?.investedUsd || 0
  const enPesos = moneda === 'ARS'
  const base = enPesos ? totalsToday : totals
  const tc = enPesos ? tcValuacion : 1
  const valor = ((base?.value || 0) + pfValor) * tc
  const invertido = ((base?.invested || 0) + pfInvertido) * tc
  const pnl = valor - invertido
  return { valor, invertido, pnl, pct: invertido > 0 ? pnl / invertido : 0 }
}
