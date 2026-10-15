// tcHistorico.js
// ──────────────
// "¿A qué dólar paso a pesos unos dólares de OTRA fecha?" — una sola respuesta
// para toda la app: AL DÓLAR QUE EL USUARIO ELIGIÓ, el de esa fecha.
//
// El dólar de hoy ya es el elegido (`tcValuacion` = MEP, o CCL si lo cambió en
// Configuración; ver `pickFinancialRate`). Los montos viejos tienen que ir al
// MISMO dólar, pero de su fecha. Hasta el 2026-10-15 las pantallas usaban para
// lo viejo el BLUE (`/benchmarks` → `dolar_blue`, o `/fx-rates` → `blue`) y para
// lo de hoy el MEP: dos dólares distintos en la misma cuenta, y "lo que pusiste"
// en pesos no coincidía con los pesos que el servidor anotó al guardar el
// depósito (el servidor dolariza con el MEP del día: `fx.fx_for_date`).
//
// LA SERIE: `/api/fx-rates` (tabla `fx_rates_daily`), el punto medio de cada
// día. De ahí:
//   1. El MEP de esa fecha (o el último anterior: fines de semana y feriados).
//   2. Antes de que exista el MEP en la serie (oct-2018) el blue de esa fecha:
//      la misma red que usa el servidor (`fx.fx_for_date_detail`).
//   3. Sin serie, el dólar de hoy (último recurso, lo de antes).
//
// ⚠️ CCL: la serie no guarda el CCL histórico. Quien eligió CCL ve lo de HOY al
// CCL y lo viejo al MEP de su fecha. Es la mejor aproximación con lo guardado;
// para guardarlo hay que agregar la columna a `fx_rates_daily`.

/** Índice de la serie: fechas ordenadas + MEP y blue por fecha. */
export function indexarSerie(rows) {
  const dates = []
  const blue = new Map()
  const mep = new Map()
  for (const r of rows || []) {
    if (!r?.date || r?.blue == null) continue
    dates.push(r.date)
    blue.set(r.date, Number(r.blue))
    if (r?.mep != null && Number(r.mep) > 0) mep.set(r.date, Number(r.mep))
  }
  return { dates, blue, mep }
}

// Posición de la última fecha ≤ dateIso (búsqueda binaria), -1 si no hay.
function ultimaHasta(dates, dateIso) {
  let lo = 0, hi = dates.length - 1, best = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (dates[mid] <= dateIso) { best = mid; lo = mid + 1 } else { hi = mid - 1 }
  }
  return best
}

/**
 * El dólar elegido de una fecha, CON TRAZA: de qué serie y de qué día salió.
 * `{tc: null}` si no hay nada ≤ la fecha (el caller decide el respaldo).
 */
export function tcDeFechaDetalle(idx, dateIso) {
  const NADA = { tc: null, source: null, asOf: null }
  if (!dateIso || !idx || idx.dates.length === 0) return NADA
  const best = ultimaHasta(idx.dates, String(dateIso).slice(0, 10))
  for (let i = best; i >= 0; i--) {
    const v = idx.mep.get(idx.dates[i])
    if (v != null && v > 0) return { tc: v, source: 'mep', asOf: idx.dates[i] }
  }
  if (best >= 0) {
    const b = idx.blue.get(idx.dates[best])
    if (b != null && b > 0) return { tc: b, source: 'blue', asOf: idx.dates[best] }
  }
  return NADA
}

// La tabla POR MES (el cierre de cada mes, para los cálculos que trabajan sobre
// `monthly_entries`) es `dolarMensualDe` en utils/capitalAportado.js: la misma
// serie y la misma preferencia (MEP; blue donde no hay MEP).

/**
 * dolarDelDiaDe — de las filas de `/api/fx-rates`, `(iso) => dólar elegido de ese
 * día | null`: lo mismo que `useFxHistory().getRateForDate` (el de cada fila de
 * Movimientos), sin React. Lo usa `useDolarMensual` para los aportes en dólares
 * que tienen su día (utils/capitalAportado.js).
 */
export function dolarDelDiaDe(rows) {
  const idx = indexarSerie(rows)
  return (dateIso) => tcDeFechaDetalle(idx, dateIso).tc
}
