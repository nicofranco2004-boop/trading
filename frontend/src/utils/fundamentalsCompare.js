// fundamentalsCompare — lógica PURA para la vista "Comparar" de Fundamentals.
// ═══════════════════════════════════════════════════════════════════════════
// Toda la decisión de "quién gana cada métrica" vive acá, sin React ni DOM, así
// es testeable de forma aislada (ver fundamentalsCompare.test.js).
//
// Input: un array de "entries" { ticker, data } donde data es la respuesta de
// GET /fundamentals/{ticker} (available:true), que incluye `metrics_detail`:
//   [{ key, label, category, value (num|null), value_label (str), direction }]
//
// Reglas:
//   • Una métrica es "comparable" en una fila si ≥2 tickers tienen value !== null.
//   • El ganador de una métrica es el ticker con el mejor value según `direction`
//     ("lower" → menor gana, "higher" → mayor gana). Empates → sin ganador único
//     (no se cuenta win para nadie, no se pinta trofeo).
//   • "gana N métricas" de un ticker = cantidad de filas comparables que gana.
//   • Ganador de categoría = ticker con más wins dentro de esa categoría; los
//     empates se rompen por overall score más alto.

export const CATEGORY_ORDER = ['valuation', 'growth', 'profitability', 'health']

export const CATEGORY_LABELS = {
  valuation: 'Valuación',
  growth: 'Crecimiento',
  profitability: 'Rentabilidad',
  health: 'Salud Financiera',
}

// El orden canónico (y completo) de las 20 keys del contrato, agrupadas por
// categoría. Lo usamos para ordenar filas de forma estable aunque metrics_detail
// venga en otro orden o falten keys.
export const METRIC_ORDER = [
  'pe', 'pe_fwd', 'pb', 'ev_ebitda', 'peg',
  'rev_growth_3y', 'rev_growth_5y', 'eps_growth_3y', 'rev_growth_yoy', 'earnings_yoy',
  'roe', 'roa', 'net_margin', 'oper_margin', 'gross_margin',
  'debt_equity', 'current_ratio', 'quick_ratio', 'payout', 'fcf_margin',
]

function isNum(v) {
  return typeof v === 'number' && !Number.isNaN(v)
}

// Devuelve el índice (en `entries`) del ganador de una fila de métricas, o -1 si
// no hay ganador único (menos de 2 valores comparables o empate en el mejor).
// `cells` = array alineado con entries: { value, direction } | null
function pickWinnerIndex(cells) {
  const valued = []
  for (let i = 0; i < cells.length; i++) {
    const c = cells[i]
    if (c && isNum(c.value)) valued.push({ i, value: c.value, direction: c.direction })
  }
  if (valued.length < 2) return -1 // no comparable
  const direction = valued[0].direction || 'higher'
  let best = valued[0]
  let tie = false
  for (let k = 1; k < valued.length; k++) {
    const cur = valued[k]
    const better = direction === 'lower' ? cur.value < best.value : cur.value > best.value
    if (better) { best = cur; tie = false }
    else if (cur.value === best.value) tie = true
  }
  return tie ? -1 : best.i
}

// Normaliza un valor a 0..1 dentro del rango [min,max] de la fila respetando la
// dirección (1 = mejor). Usado para la barra relativa de cada celda.
export function relativeFill(value, min, max, direction) {
  if (!isNum(value) || !isNum(min) || !isNum(max)) return 0
  if (max === min) return 1
  const t = (value - min) / (max - min)
  return direction === 'lower' ? 1 - t : t
}

// Construye el modelo de comparación completo.
// entries: [{ ticker, data }]  (solo available:true)
// Devuelve:
//   {
//     tickers: [ticker,...]   (en el orden recibido)
//     rows: [{ key, label, category, direction, cells:[{value,value_label}], winnerIndex, min, max }]
//     rowsByCategory: { [category]: row[] }
//     winsByTicker: { [ticker]: number }       // total filas comparables ganadas
//     comparableCount: number                   // filas con ≥2 valores
//     categoryWinner: { [category]: { ticker, metricKey, metricLabel, metricValueLabel } | null }
//     ranking: [{ ticker, overall, label, wins, data }] ordenado por overall desc
//     leader: { ticker, overall, wins } | null
//   }
export function buildComparison(entries) {
  const list = (entries || []).filter(e => e && e.data && e.data.available)
  const tickers = list.map(e => (e.ticker || e.data.ticker || '').toUpperCase())

  // Index metrics_detail por key para cada ticker.
  const detailByTicker = list.map(e => {
    const map = {}
    for (const m of (e.data.metrics_detail || [])) {
      if (m && m.key) map[m.key] = m
    }
    return map
  })

  // Reunir todas las keys presentes, ordenadas por METRIC_ORDER (luego extras).
  const presentKeys = new Set()
  for (const map of detailByTicker) {
    for (const k of Object.keys(map)) presentKeys.add(k)
  }
  const orderedKeys = [
    ...METRIC_ORDER.filter(k => presentKeys.has(k)),
    ...[...presentKeys].filter(k => !METRIC_ORDER.includes(k)),
  ]

  const winsByTicker = {}
  for (const t of tickers) winsByTicker[t] = 0

  const rows = []
  let comparableCount = 0

  for (const key of orderedKeys) {
    // Tomar metadata de la primera ocurrencia (label/category/direction estables).
    let meta = null
    for (const map of detailByTicker) {
      if (map[key]) { meta = map[key]; break }
    }
    if (!meta) continue

    const cells = detailByTicker.map(map => {
      const m = map[key]
      return {
        value: m && isNum(m.value) ? m.value : null,
        value_label: m ? (m.value_label ?? '—') : '—',
      }
    })

    const winnerIndex = pickWinnerIndex(
      cells.map(c => ({ value: c.value, direction: meta.direction }))
    )

    const nums = cells.map(c => c.value).filter(isNum)
    const min = nums.length ? Math.min(...nums) : null
    const max = nums.length ? Math.max(...nums) : null
    const comparable = nums.length >= 2
    if (comparable) comparableCount++
    if (winnerIndex >= 0) {
      const wt = tickers[winnerIndex]
      winsByTicker[wt] = (winsByTicker[wt] || 0) + 1
    }

    rows.push({
      key,
      label: meta.label || key,
      category: meta.category || 'valuation',
      direction: meta.direction || 'higher',
      cells,
      winnerIndex,
      min,
      max,
      comparable,
    })
  }

  // Agrupar filas por categoría (en CATEGORY_ORDER).
  const rowsByCategory = {}
  for (const cat of CATEGORY_ORDER) rowsByCategory[cat] = []
  for (const row of rows) {
    if (!rowsByCategory[row.category]) rowsByCategory[row.category] = []
    rowsByCategory[row.category].push(row)
  }

  // Overall por ticker (para tie-break y ranking).
  const overallByTicker = {}
  list.forEach((e, i) => {
    overallByTicker[tickers[i]] = e.data.score?.overall ?? -1
  })

  // Ganador por categoría = más wins en esa categoría; empate → mayor overall.
  const categoryWinner = {}
  for (const cat of CATEGORY_ORDER) {
    const catRows = rowsByCategory[cat] || []
    const winsHere = {}
    for (const t of tickers) winsHere[t] = 0
    for (const row of catRows) {
      if (row.winnerIndex >= 0) winsHere[tickers[row.winnerIndex]]++
    }
    let best = null
    for (const t of tickers) {
      const w = winsHere[t]
      if (w <= 0) continue
      if (
        !best ||
        w > best.wins ||
        (w === best.wins && (overallByTicker[t] ?? -1) > (overallByTicker[best.ticker] ?? -1))
      ) {
        best = { ticker: t, wins: w }
      }
    }
    if (!best) { categoryWinner[cat] = null; continue }
    // Métrica representativa = la primera fila de la categoría que ese ticker gana.
    const tIdx = tickers.indexOf(best.ticker)
    let repRow = null
    for (const row of catRows) {
      if (row.winnerIndex === tIdx) { repRow = row; break }
    }
    categoryWinner[cat] = {
      ticker: best.ticker,
      wins: best.wins,
      metricKey: repRow ? repRow.key : null,
      metricLabel: repRow ? repRow.label : null,
      metricValueLabel: repRow ? repRow.cells[tIdx].value_label : null,
    }
  }

  // Ranking por overall desc (empate → más wins).
  const ranking = list
    .map((e, i) => ({
      ticker: tickers[i],
      overall: e.data.score?.overall ?? null,
      label: e.data.score?.label ?? 'Sin datos',
      wins: winsByTicker[tickers[i]] || 0,
      data: e.data,
    }))
    .sort((a, b) => {
      const ao = a.overall ?? -1
      const bo = b.overall ?? -1
      if (bo !== ao) return bo - ao
      return (b.wins || 0) - (a.wins || 0)
    })

  const leader = ranking.length
    ? { ticker: ranking[0].ticker, overall: ranking[0].overall, wins: ranking[0].wins }
    : null

  return {
    tickers,
    rows,
    rowsByCategory,
    winsByTicker,
    comparableCount,
    categoryWinner,
    ranking,
    leader,
  }
}

// Top-N métricas de un ticker (por su propio metrics_detail), para la card del
// ranking. Devuelve las primeras N con value !== null, en METRIC_ORDER.
export function topMetricsFor(data, n = 3) {
  const detail = data?.metrics_detail || []
  const byKey = {}
  for (const m of detail) if (m && m.key) byKey[m.key] = m
  const out = []
  for (const key of METRIC_ORDER) {
    const m = byKey[key]
    if (m && typeof m.value === 'number' && !Number.isNaN(m.value)) {
      out.push({ key, label: m.label, value_label: m.value_label })
      if (out.length >= n) break
    }
  }
  return out
}
