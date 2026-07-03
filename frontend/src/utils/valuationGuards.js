/**
 * valuationGuards — cinturón de consistencia de valuación.
 *
 * Detecta AUTOMÁTICAMENTE la clase de bugs que veníamos cazando a mano:
 *   • "%-del-primer-lote" (GOOGL): value y pnl$ agregados bien, pero el pnl_pct
 *     mostrado era el de un lote → NO cerraba con value/pnl (valor 2117 + P&L 466
 *     daban +28%, mostraba +157%).
 *   • "×100 / inflado" (bono per-100, CEDEAR por ticker US): el valor se dispara
 *     absurdamente lejos del costo.
 *
 * NO cambia ningún valor. `positionPct` es el ANTÍDOTO (hace el % siempre
 * derivado, así no se puede "quedar con el del primer lote"); `auditPositions`
 * es el DETECTOR (en DEV loguea las filas que no cierran — cero efecto en prod).
 */

const isDev = () => {
  try {
    // Vite: import.meta.env.DEV. En tests (vitest) también es true.
    return !!(import.meta && import.meta.env && import.meta.env.DEV)
  } catch {
    return false
  }
}

/**
 * % canónico de una posición: SIEMPRE derivado de valor y P&L. Como
 * `invested = value − pnl` (identidad válida en TODAS las ramas de valuación:
 * value = invested + pnl), el % no se puede desincronizar del valor mostrado.
 * Usalo en vez de copiar/promediar el pnl_pct de un lote al agregar.
 *
 * @returns {number|null} ratio (0.28 = 28%), o null si no hay costo con qué dividir.
 */
export function positionPct(valueUsd, pnlUsd) {
  const v = Number(valueUsd)
  const p = Number(pnlUsd)
  if (!Number.isFinite(v) || !Number.isFinite(p)) return null
  const invested = v - p
  return invested > 0 ? p / invested : null
}

/**
 * ¿Una fila mostrada cierra consigo misma? Chequea:
 *   1) reconcile — el pnl_pct reportado ≈ pnl/(value−pnl). Caza el bug GOOGL.
 *   2) magnitud — value ≫ costo (>50×, la banda no-renta-fija de trustMktValue):
 *      olor a inflado (bono ×100, CEDEAR priceado por el ticker US).
 * Acepta {value_usd|value, pnl_usd|pnl, pnl_pct|pnlPct}. `opts.pct` = convención
 * del pnl_pct reportado: 'ratio' (0.28, default) o 'percent' (28). La app mezcla
 * ambas (Dashboard usa ratio; Insights usa percent) → hay que decirle cuál.
 */
export function checkPositionRow(row, { pct = 'ratio' } = {}) {
  const issues = []
  const value = Number(row?.value_usd ?? row?.value)
  const pnl = Number(row?.pnl_usd ?? row?.pnl)
  const reported = row?.pnl_pct ?? row?.pnlPct

  if (Number.isFinite(value) && Number.isFinite(pnl)) {
    const derivedRatio = positionPct(value, pnl)
    const scale = pct === 'percent' ? 100 : 1
    const derived = derivedRatio != null ? derivedRatio * scale : null
    if (derived != null && reported != null && Number.isFinite(Number(reported))) {
      const drift = Math.abs(Number(reported) - derived)
      // Tolerancia: 1 punto porcentual absoluto o 3% relativo (value/pnl vienen
      // redondeados a 2 decimales → drift legítimo). Escalada a la convención.
      if (drift > Math.max(0.01 * scale, 0.03 * Math.abs(derived))) {
        const toPct = (x) => (pct === 'percent' ? x : x * 100).toFixed(1)
        issues.push(
          `pnl_pct ${toPct(Number(reported))}% no cierra con value/pnl (derivado ${toPct(derived)}%)`
        )
      }
    }
    const invested = value - pnl
    if (invested > 0 && value / invested > 50) {
      issues.push(`valor ${value.toFixed(0)} = ${(value / invested).toFixed(0)}× el costo — posible inflado`)
    }
  }
  return { ok: issues.length === 0, asset: row?.asset, issues }
}

/**
 * Corré el chequeo sobre un array de filas mostradas. En DEV loguea las fallas
 * (una vez, agrupadas). Devuelve las fallas (para tests). NO cambia nada.
 *
 * Uso: al armar el array por-activo que alimenta una pantalla, pasalo por acá:
 *   auditPositions(positionsForInsight, 'Dashboard.positionsForInsight')
 */
export function auditPositions(rows, label = 'positions', opts = {}) {
  const problems = (Array.isArray(rows) ? rows : []).map((r) => checkPositionRow(r, opts)).filter((r) => !r.ok)
  if (problems.length && isDev()) {
    // eslint-disable-next-line no-console
    console.warn(
      `[valuation-guard] ${label}: ${problems.length} fila(s) inconsistente(s) →`,
      problems.map((p) => `${p.asset}: ${p.issues.join('; ')}`)
    )
  }
  return problems
}
