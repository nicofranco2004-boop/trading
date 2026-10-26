// shareCard — renderiza tarjetas compartibles (1080x1350 PNG) sobre Canvas.
// ═══════════════════════════════════════════════════════════════════════════
// Sprint 5 (Wrapped / viralidad). Cero dependencias: usa Canvas 2D nativo.
// Salida: 4:5 (1080x1350) — formato pensado para IG feed / Twitter / WhatsApp.
//
// Public API:
//   renderShareCard(spec)            → HTMLCanvasElement
//   shareCardToBlob(spec)            → Blob (PNG)
//   shareCardToDataURL(spec)         → data: URL (PNG)
//   downloadShareCard(spec, name?)   → trigger download
//   tryNativeShare(spec, opts?)      → Web Share API (mobile)
//   specFromInsight(card, now?)      → spec para una card de Behavioral
//   specFromMonth(monthRow, now?)    → spec para un mes de MonthlySummary
//   specDeDistribucion(args)         → spec para una torta de distribución
//   specDeRendimiento(args)          → spec para "Cartera vs benchmark"
//
// Todas las tarjetas llevan el mismo encabezado de marca: el isotipo violeta,
// "Rendi" y "rendi.finance" (el dominio real; antes decía RENDI.APP).
//
// Spec shape (insight / performance):
//   {
//     kind: 'insight' | 'performance',
//     eyebrow: string,        // mono uppercase, accent color
//     title: string,          // headline grande (wrap automático)
//     subtitle?: string,      // gris, debajo del headline
//     stats?: [{ label, value }],  // bloques key→value, máx ~4
//     pill?: { label, tone }, // tone: red | green | amber | blue | gray
//     date?: string,          // pie derecho ("MAYO 2026")
//   }
//
// Las de métricas ('distribucion' y 'rendimiento') tienen su propio armado, en
// violeta de marca y todo en Geist (nada de mono: ver R4 en frontend/CLAUDE.md).
// Sus shapes están en specDeDistribucion y specDeRendimiento. Los montos van
// sólo si el usuario dijo que sí en el modal (`mostrarMontos`): por defecto la
// imagen dice porcentajes, no cuánta plata tiene.

// ── Constantes de diseño ──────────────────────────────────────────────────

const W = 1080
const H = 1350
const PAD = 72

const TONE = {
  red:   '#FF5360',
  green: '#21D07A',
  amber: '#E8B14A',
  blue:  '#4E83FF',
  gray:  '#9CA3B5',
}

const FONT_SANS = "Geist, -apple-system, BlinkMacSystemFont, system-ui, sans-serif"
const FONT_MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, monospace"

// Violeta de marca (el del brand kit = --data-violet en oscuro) y las tintas
// del canvas, UNA vez cada una: las tarjetas viejas también las leen de acá.
// Hex a mano a propósito: el canvas no resuelve var() y la imagen es oscura
// siempre (R8, excepción 3).
const VIOLETA = '#8B7DFF'
const INK_0 = '#E6EAF2'
const INK_2 = TONE.gray
const INK_3 = '#5A6478'
const LINEA = '#1B2230'
// El texto oscuro sobre una porción clara: el mismo tono del fondo.
const FONDO_TINTA = '#0E1218'

const LOGO_SRC = '/brand/rendi-mark-violet.png'
const DOMINIO = 'rendi.finance'

// Lo que no es una porción "de verdad": va al final y no puede ser el titular.
const PORCION_RESIDUAL = new Set(['__otros__', '__resto__', 'otro', 'sin_dato'])

// Más filas que estas no entran debajo de la torta en 1350 px de alto (la
// lista va en dos columnas de 5).
const MAX_FILAS_LEYENDA = 10

// ── Render principal ──────────────────────────────────────────────────────

export async function renderShareCard(spec) {
  // Best-effort: precargar fuentes web para los tamaños que vamos a usar.
  // CRÍTICO: document.fonts.ready puede no resolver nunca en algunos browsers,
  // así que usamos Promise.race con timeout corto. Si no carga la fuente web,
  // Canvas cae al fallback del sistema (system-ui) — preferimos eso a un hang.
  const [, logo] = await Promise.all([ensureFontsReady(), cargarLogo()])

  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')

  if (spec.kind === 'distribucion') {
    pintarFondo(ctx, VIOLETA)
    pintarEncabezado(ctx, logo)
    pintarDistribucion(ctx, spec, logo)
    return canvas
  }
  if (spec.kind === 'rendimiento') {
    pintarFondo(ctx, VIOLETA)
    pintarEncabezado(ctx, logo)
    pintarRendimiento(ctx, spec)
    return canvas
  }

  const accent = TONE[spec.pill?.tone] || TONE.green

  pintarFondo(ctx, accent)
  pintarEncabezado(ctx, logo)

  let y = PAD + 110
  ctx.textBaseline = 'top'

  // ── Eyebrow ───────────────────────────────────────────────────────────
  if (spec.eyebrow) {
    ctx.fillStyle = accent
    ctx.font = `14px ${FONT_MONO}`
    ctx.fillText(String(spec.eyebrow).toUpperCase(), PAD, y)
    y += 40
  }

  // ── Title (headline grande, wrap) ─────────────────────────────────────
  if (spec.title) {
    ctx.fillStyle = INK_0
    const titleSize = spec.kind === 'performance' ? 92 : 54
    ctx.font = `500 ${titleSize}px ${FONT_SANS}`
    y = wrapText(ctx, String(spec.title), PAD, y, W - 2 * PAD, titleSize * 1.05)
    y += 18
  }

  // ── Subtitle ──────────────────────────────────────────────────────────
  if (spec.subtitle) {
    ctx.fillStyle = INK_2
    const subSize = 26
    ctx.font = `${subSize}px ${FONT_SANS}`
    y = wrapText(ctx, String(spec.subtitle), PAD, y, W - 2 * PAD, subSize * 1.35)
    y += 32
  }

  // ── Divider ───────────────────────────────────────────────────────────
  if (spec.stats?.length) {
    ctx.strokeStyle = LINEA
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(PAD, y)
    ctx.lineTo(W - PAD, y)
    ctx.stroke()
    y += 28

    // ── Stats rows ──────────────────────────────────────────────────────
    for (const stat of spec.stats.slice(0, 4)) {
      ctx.fillStyle = INK_3
      ctx.font = `12px ${FONT_MONO}`
      ctx.fillText(String(stat.label || '').toUpperCase(), PAD, y + 6)

      ctx.fillStyle = INK_0
      ctx.font = `500 24px ${FONT_SANS}`
      ctx.textAlign = 'right'
      ctx.fillText(String(stat.value || ''), W - PAD, y)
      ctx.textAlign = 'left'

      y += 44
    }
  }

  // ── Footer (pill izquierda + fecha derecha) ──────────────────────────
  const footerY = H - PAD - 38

  if (spec.pill?.label) {
    const label = String(spec.pill.label).toUpperCase()
    ctx.font = `12px ${FONT_MONO}`
    const padX = 16
    const pillH = 36
    const textW = ctx.measureText(label).width
    const pillW = textW + padX * 2

    ctx.fillStyle = hexToRgba(accent, 0.12)
    roundRect(ctx, PAD, footerY, pillW, pillH, 4)
    ctx.fill()

    ctx.strokeStyle = hexToRgba(accent, 0.30)
    ctx.lineWidth = 1
    roundRect(ctx, PAD, footerY, pillW, pillH, 4)
    ctx.stroke()

    ctx.fillStyle = accent
    ctx.textBaseline = 'middle'
    ctx.fillText(label, PAD + padX, footerY + pillH / 2 + 1)
    ctx.textBaseline = 'top'
  }

  if (spec.date) {
    ctx.fillStyle = INK_3
    ctx.font = `13px ${FONT_MONO}`
    ctx.textAlign = 'right'
    ctx.textBaseline = 'middle'
    ctx.fillText(String(spec.date).toUpperCase(), W - PAD, footerY + 18)
    ctx.textAlign = 'left'
    ctx.textBaseline = 'top'
  }

  return canvas
}

// ── API de salida ─────────────────────────────────────────────────────────

export async function shareCardToBlob(spec) {
  const canvas = await renderShareCard(spec)
  return new Promise((resolve) => {
    if (canvas.toBlob) {
      canvas.toBlob((b) => resolve(b), 'image/png', 0.95)
    } else {
      // Fallback teórico: convertir dataURL → Blob
      const url = canvas.toDataURL('image/png')
      resolve(dataURLToBlob(url))
    }
  })
}

export async function shareCardToDataURL(spec) {
  const canvas = await renderShareCard(spec)
  return canvas.toDataURL('image/png')
}

export async function downloadShareCard(spec, filename = 'rendi-card.png') {
  const blob = await shareCardToBlob(spec)
  if (!blob) throw new Error('No se pudo generar el PNG')
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1500)
}

// Devuelve true si compartió con el sistema, false si no hay soporte o canceló.
export async function tryNativeShare(spec, { title = 'Rendi', text = '' } = {}) {
  if (typeof navigator === 'undefined' || !navigator.canShare || !navigator.share) {
    return false
  }
  const blob = await shareCardToBlob(spec)
  if (!blob) return false
  const file = new File([blob], 'rendi-card.png', { type: 'image/png' })
  if (!navigator.canShare({ files: [file] })) return false
  try {
    await navigator.share({ title, text, files: [file] })
    return true
  } catch {
    return false
  }
}

// ── Spec builders ─────────────────────────────────────────────────────────

const SEVERITY_TONE = {
  high:     'red',
  medium:   'amber',
  low:      'blue',
  positive: 'green',
  neutral:  'gray',
}

const SEVERITY_LABEL = {
  high:     'Severidad alta',
  medium:   'Severidad media',
  low:      'Severidad baja',
  positive: 'Patrón saludable',
  neutral:  'Sin datos',
}

const CARD_LABEL = {
  disposition_effect:   'Disposition effect',
  overtrade:            'Frecuencia de trades',
  loss_aversion:        'Loss aversion',
  averaging_down:       'Promedio a la baja',
  concentration:        'Concentración',
  inflation_loss:       'Pérdida por inflación',
  counterfactual:       'Tu yo de hace meses',
  winrate_payoff:       'Win rate · Payoff',
  home_bias:            'Home bias',
  cash_drag:            'Cash drag',
  recency_bias:         'Chase the pump',
  sector_concentration: 'Concentración sectorial',
}

export function specFromInsight(card, now = new Date()) {
  const code = card?.code || ''
  const sev = card?.severity || 'neutral'
  const tone = SEVERITY_TONE[sev] || 'gray'
  const eyebrow = CARD_LABEL[code] || code

  const stats = []
  if (card?.value_label) {
    stats.push({ label: 'Indicador', value: String(card.value_label) })
  }

  const dateLabel = now.toLocaleDateString('es-AR', { month: 'long', year: 'numeric' })

  return {
    kind: 'insight',
    eyebrow,
    title: card?.title || '',
    subtitle: card?.one_liner || '',
    stats,
    pill: { label: SEVERITY_LABEL[sev] || '', tone },
    date: dateLabel,
  }
}

export function specFromMonth(monthRow) {
  const pnlPct = Number(monthRow?.pnl_pct ?? 0)
  const positive = pnlPct >= 0
  const tone = positive ? 'green' : 'red'
  const sign = positive ? '+' : '−'
  const pctStr = `${sign}${Math.abs(pnlPct * 100).toFixed(2).replace('.', ',')}%`

  const label = monthRow?.month_label || monthRow?.month || ''

  const stats = []
  if (monthRow?.capital_inicio != null && !isNaN(monthRow.capital_inicio)) {
    stats.push({
      label: 'Capital inicial',
      value: `$${Math.round(monthRow.capital_inicio).toLocaleString('es-AR')}`,
    })
  }
  if (monthRow?.capital_final != null && !isNaN(monthRow.capital_final)) {
    stats.push({
      label: 'Capital final',
      value: `$${Math.round(monthRow.capital_final).toLocaleString('es-AR')}`,
    })
  }
  if (monthRow?.net != null && !isNaN(monthRow.net) && monthRow.net !== 0) {
    const netSign = monthRow.net >= 0 ? '+' : '−'
    stats.push({
      label: monthRow.net >= 0 ? 'Aportes netos' : 'Retiros netos',
      value: `${netSign}$${Math.abs(Math.round(monthRow.net)).toLocaleString('es-AR')}`,
    })
  }
  if (monthRow?.best_trade) {
    stats.push({ label: 'Mejor trade', value: String(monthRow.best_trade) })
  }

  return {
    kind: 'performance',
    eyebrow: label ? `Mi ${label} en Rendi` : 'Mi mes en Rendi',
    title: pctStr,
    subtitle: positive
      ? 'Rendimiento mensual de la cartera'
      : 'Mes negativo — cierre del período',
    stats,
    pill: { label: positive ? 'Mes positivo' : 'Mes negativo', tone },
    date: label,
  }
}

// ── Tarjetas de métricas ──────────────────────────────────────────────────

// 38.24 → "38,2%". Mismo formato que la leyenda de CompositionDonut.
export const pctTxt = (v) => `${Number(v).toFixed(1).replace('.', ',')}%`
// Con signo explícito y el menos tipográfico (U+2212), como el resto de la app.
export const pctConSigno = (v) => `${v >= 0 ? '+' : '−'}${pctTxt(Math.abs(v))}`

// "Distribución por sector" → "distribucion-por-sector" (para el .png).
export const nombreDeArchivo = (texto) => String(texto || 'tarjeta')
  .normalize('NFD').replace(/[̀-ͯ]/g, '')
  .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'tarjeta'

export const fechaDeHoy = (now = new Date()) =>
  now.toLocaleDateString('es-AR', { day: 'numeric', month: 'long', year: 'numeric' })

/**
 * La tarjeta de una torta de distribución (por activo, por tipo, por sector).
 *
 * Recibe las MISMAS porciones que dibuja la leyenda de CompositionDonut —ya
 * ordenadas, con "Otros" agrupado y los residuales al final—, así que la
 * imagen no puede decir un % distinto del de la pantalla. Si hay más filas de
 * las que entran, las últimas se juntan en "Otros" (sumando sus %).
 *
 * @param {object}   a
 * @param {string}   a.titulo        "Distribución por sector"
 * @param {Array<{key,label,color,value,pct}>} a.porciones
 * @param {Function} a.fmt           formatea un monto (el mismo `fmt` de la torta)
 * @param {boolean}  a.mostrarMontos si van los montos; si no, sólo %
 */
export function specDeDistribucion({ titulo, porciones = [], fmt = (v) => String(v), mostrarMontos = false, now = new Date() }) {
  const validas = porciones.filter(p => p && p.value > 0)
  const total = validas.reduce((s, p) => s + p.value, 0)

  let filas = validas
  if (validas.length > MAX_FILAS_LEYENDA) {
    const quedan = validas.slice(0, MAX_FILAS_LEYENDA - 1)
    const resto = validas.slice(MAX_FILAS_LEYENDA - 1)
    filas = [...quedan, {
      key: '__otros__',
      label: 'Otros',
      color: resto.find(p => PORCION_RESIDUAL.has(p.key))?.color || INK_3,
      value: resto.reduce((s, p) => s + p.value, 0),
      pct: resto.reduce((s, p) => s + p.pct, 0),
    }]
  }

  // El titular es la porción más grande que sea algo concreto: "Otros" o
  // "Sin clasificar" no dicen nada como titular aunque pesen más.
  const mayor = filas.find(p => !PORCION_RESIDUAL.has(p.key)) || filas[0] || null

  return {
    kind: 'distribucion',
    eyebrow: titulo,
    title: mayor ? `${pctTxt(mayor.pct)} en ${mayor.label}` : '',
    porciones: filas.map(p => ({
      label: p.label,
      color: p.color,
      pct: p.pct,
      monto: mostrarMontos ? fmt(p.value) : null,
    })),
    total: mostrarMontos && total > 0 ? fmt(total) : null,
    date: fechaDeHoy(now),
  }
}

/**
 * La tarjeta "Mi cartera vs benchmark".
 *
 * `carteraPct` y `benchPct` son los del KPI "Acumulado" de la pantalla
 * (kpiRendimiento en Insights), no la punta de la curva: son los números que la
 * app publica, y la imagen no puede decir otro. La serie es sólo la FORMA.
 *
 * @param {object} a
 * @param {number} a.carteraPct   % acumulado de la cartera en el período
 * @param {number|null} a.benchPct % del benchmark entre las mismas fechas
 * @param {string} a.benchLabel   "S&P 500", "Inflación AR"…
 * @param {Array<{ts:number, cartera:number|null, bench:number|null}>} a.serie
 * @param {string} a.periodo      "Último año"
 * @param {'USD'|'ARS'} a.moneda
 * @param {string|null} a.patrimonio  valor de la cartera ya formateado
 * @param {boolean} a.mostrarMontos
 */
export function specDeRendimiento({
  carteraPct, benchPct = null, benchLabel = 'Benchmark', serie = [],
  periodo = '', moneda = 'USD', patrimonio = null, mostrarMontos = false, now = new Date(),
}) {
  const hayBench = benchPct != null && Number.isFinite(benchPct)
  const stats = [{ label: 'Mi cartera', value: pctConSigno(carteraPct), tono: carteraPct >= 0 ? 'green' : 'red' }]
  if (hayBench) {
    stats.push({ label: benchLabel, value: pctConSigno(benchPct), tono: 'gray' })
    const dif = carteraPct - benchPct
    stats.push({
      label: 'Diferencia',
      value: `${dif >= 0 ? '+' : '−'}${Math.abs(dif).toFixed(1).replace('.', ',')} puntos`,
      tono: dif >= 0 ? 'green' : 'red',
    })
  }

  const enMoneda = moneda === 'ARS' ? 'en pesos' : 'en dólares'
  const veredicto = !hayBench ? null
    // Sin artículo a propósito: "Mejor que Inflación AR" se lee bien; "Le gané
    // al Inflación AR", no.
    : carteraPct >= benchPct ? `Mejor que ${benchLabel}` : `Por debajo de ${benchLabel}`

  // Más de ~240 puntos no se distinguen en 936 px de ancho: se raleán (la
  // última fila se queda siempre, es el "hoy").
  const limpia = serie.filter(p => p && Number.isFinite(p.ts))
  const paso = Math.max(1, Math.ceil(limpia.length / 240))
  const rala = limpia.filter((_, i) => i % paso === 0 || i === limpia.length - 1)

  return {
    kind: 'rendimiento',
    eyebrow: `Mi cartera vs ${benchLabel}`,
    title: pctConSigno(carteraPct),
    tono: carteraPct >= 0 ? 'green' : 'red',
    subtitle: [periodo, enMoneda].filter(Boolean).join(' · '),
    veredicto,
    patrimonio: mostrarMontos && patrimonio ? patrimonio : null,
    stats,
    benchLabel,
    serie: rala,
    date: fechaDeHoy(now),
  }
}

// ── Pintores ──────────────────────────────────────────────────────────────

function pintarFondo(ctx, accent) {
  const grad = ctx.createLinearGradient(0, 0, 0, H)
  grad.addColorStop(0, FONDO_TINTA)
  grad.addColorStop(1, '#07090C')
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, W, H)

  // Tira de acento arriba (4px)
  ctx.fillStyle = accent
  ctx.fillRect(0, 0, W, 4)

  // Glow sutil del accent en la diagonal (radial)
  const glow = ctx.createRadialGradient(W * 0.85, H * 0.18, 0, W * 0.85, H * 0.18, 480)
  glow.addColorStop(0, hexToRgba(accent, 0.10))
  glow.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = glow
  ctx.fillRect(0, 0, W, H)
}

// Isotipo + "Rendi" a la izquierda, el dominio a la derecha. Si el logo no
// cargó (offline, timeout), queda la palabra sola: peor sin imagen que colgado.
function pintarEncabezado(ctx, logo) {
  const alto = 44
  ctx.textBaseline = 'middle'
  let x = PAD
  if (logo) {
    const ancho = alto * (logo.naturalWidth / logo.naturalHeight || 0.83)
    ctx.drawImage(logo, PAD, PAD, ancho, alto)
    x += ancho + 16
  }
  ctx.fillStyle = INK_0
  ctx.font = `600 34px ${FONT_SANS}`
  ctx.fillText('Rendi', x, PAD + alto / 2 + 1)

  ctx.fillStyle = INK_2
  ctx.font = `500 22px ${FONT_SANS}`
  ctx.textAlign = 'right'
  ctx.fillText(DOMINIO, W - PAD, PAD + alto / 2 + 1)
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'
}

// Eyebrow violeta + titular. Devuelve el `y` donde sigue el contenido.
function pintarTitular(ctx, spec, { tamano = 64, color = INK_0 } = {}) {
  let y = PAD + 44 + 64
  ctx.textBaseline = 'top'
  if (spec.eyebrow) {
    ctx.fillStyle = VIOLETA
    ctx.font = `500 28px ${FONT_SANS}`
    y = wrapText(ctx, String(spec.eyebrow), PAD, y, W - 2 * PAD, 34, 2)
    y += 14
  }
  if (spec.title) {
    ctx.fillStyle = color
    ctx.font = `600 ${tamano}px ${FONT_SANS}`
    y = wrapText(ctx, String(spec.title), PAD, y, W - 2 * PAD, tamano * 1.08, 2)
  }
  return y
}

function pintarPie(ctx, spec) {
  if (!spec.date) return
  ctx.fillStyle = INK_3
  ctx.font = `22px ${FONT_SANS}`
  ctx.textBaseline = 'alphabetic'
  ctx.fillText(String(spec.date), PAD, H - PAD + 8)
  ctx.textBaseline = 'top'
}

function pintarDistribucion(ctx, spec, logo) {
  const yTitulo = pintarTitular(ctx, spec)

  // ── La torta: grande, con el nombre y el % adentro de cada porción ────
  const porciones = spec.porciones || []
  const colores = resolverColores(porciones.map(p => p.color))
  const cx = W / 2
  const R = 310
  const r = 150
  const cy = yTitulo + 30 + R
  const sumaPct = porciones.reduce((s, p) => s + p.pct, 0) || 1
  const hueco = porciones.length > 1 ? 0.012 : 0
  const arcos = []
  let a0 = -Math.PI / 2
  porciones.forEach((p, i) => {
    const barrido = (p.pct / sumaPct) * Math.PI * 2
    const desde = a0 + hueco / 2
    const hasta = a0 + barrido - hueco / 2
    if (hasta > desde) {
      ctx.beginPath()
      ctx.arc(cx, cy, R, desde, hasta)
      ctx.arc(cx, cy, r, hasta, desde, true)
      ctx.closePath()
      ctx.fillStyle = colores[i]
      ctx.fill()
    }
    arcos.push({ desde, hasta })
    a0 += barrido
  })

  // Rótulos adentro. Se prueba "nombre + %", si no entra sólo el %, y si
  // tampoco, nada: esa porción queda leída en la lista de abajo. Nunca se
  // dibuja un rótulo que se salga de su porción.
  // El texto es horizontal y el anillo no: según el ángulo, la caja entra
  // más cerca del borde de afuera o del de adentro. Se prueban varios radios.
  const rm = (r + R) / 2
  const radios = [rm, rm + 14, rm - 14, rm + 28, rm - 28]
  porciones.forEach((p, i) => {
    const { desde, hasta } = arcos[i]
    if (!(hasta > desde)) return
    const medio = (desde + hasta) / 2
    const tinta = tintaSobre(colores[i])
    const pct = pctTxt(p.pct)
    const opciones = [
      { nombre: String(p.label), fNombre: 22, fPct: 32 },
      { nombre: null, fPct: 30 },
      { nombre: null, fPct: 22 },
    ]
    for (const op of opciones) {
      ctx.font = `700 ${op.fPct}px ${FONT_SANS}`
      let ancho = ctx.measureText(pct).width
      let alto = op.fPct
      if (op.nombre) {
        ctx.font = `600 ${op.fNombre}px ${FONT_SANS}`
        ancho = Math.max(ancho, ctx.measureText(op.nombre).width)
        alto += op.fNombre + 4
      }
      const rad = radios.find(rr => cajaDentroDePorcion(
        cx + Math.cos(medio) * rr, cy + Math.sin(medio) * rr, ancho + 12, alto + 8,
        { cx, cy, r, R, desde, hasta }))
      if (rad == null) continue
      const x = cx + Math.cos(medio) * rad
      const y = cy + Math.sin(medio) * rad
      ctx.fillStyle = tinta
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      if (op.nombre) {
        ctx.font = `600 ${op.fNombre}px ${FONT_SANS}`
        ctx.fillText(op.nombre, x, y - alto / 2 + op.fNombre / 2)
        ctx.font = `700 ${op.fPct}px ${FONT_SANS}`
        ctx.fillText(pct, x, y + alto / 2 - op.fPct / 2)
      } else {
        ctx.font = `700 ${op.fPct}px ${FONT_SANS}`
        ctx.fillText(pct, x, y)
      }
      break
    }
  })

  // El centro: el total si el usuario eligió mostrar montos; si no, el isotipo.
  ctx.textAlign = 'center'
  if (spec.total) {
    ctx.fillStyle = INK_2
    ctx.font = `24px ${FONT_SANS}`
    ctx.textBaseline = 'alphabetic'
    ctx.fillText('Total', cx, cy - 24)
    ctx.fillStyle = INK_0
    ctx.font = `600 ${spec.total.length > 14 ? 34 : 42}px ${FONT_SANS}`
    ctx.fillText(spec.total, cx, cy + 28)
  } else if (logo) {
    const alto = 96
    const ancho = alto * (logo.naturalWidth / logo.naturalHeight || 0.83)
    ctx.globalAlpha = 0.9
    ctx.drawImage(logo, cx - ancho / 2, cy - alto / 2, ancho, alto)
    ctx.globalAlpha = 1
  }
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'

  // ── La lista, en dos columnas (se lee por columna, de arriba abajo) ───
  const fila = 40
  const sep = 40
  const anchoCol = (W - 2 * PAD - sep) / 2
  const porColumna = Math.ceil(porciones.length / 2)
  const yLista = cy + R + 32
  porciones.forEach((p, i) => {
    const colIdx = i < porColumna ? 0 : 1
    const x0 = PAD + colIdx * (anchoCol + sep)
    const x1 = x0 + anchoCol
    const yc = yLista + (i % porColumna) * fila + fila / 2

    ctx.fillStyle = colores[i]
    roundRect(ctx, x0, yc - 8, 16, 16, 4)
    ctx.fill()

    ctx.textBaseline = 'middle'
    ctx.textAlign = 'right'
    ctx.fillStyle = INK_0
    ctx.font = `600 24px ${FONT_SANS}`
    const pct = pctTxt(p.pct)
    ctx.fillText(pct, x1, yc)
    let limite = x1 - ctx.measureText(pct).width - 16
    if (p.monto) {
      ctx.fillStyle = INK_2
      ctx.font = `20px ${FONT_SANS}`
      ctx.fillText(p.monto, limite, yc)
      limite -= ctx.measureText(p.monto).width + 16
    }
    ctx.textAlign = 'left'
    ctx.fillStyle = INK_0
    ctx.font = `24px ${FONT_SANS}`
    const xLabel = x0 + 28
    ctx.fillText(truncateToWidth(ctx, String(p.label), limite - xLabel), xLabel, yc)
    ctx.textBaseline = 'top'
  })

  pintarPie(ctx, spec)
}

// ¿Entra una caja de texto centrada en (x, y) adentro de la porción? Se miran
// las esquinas y los puntos medios de los bordes: cada uno tiene que caer en
// el anillo (con margen) y entre los dos ángulos de la porción.
function cajaDentroDePorcion(x, y, ancho, alto, { cx, cy, r, R, desde, hasta }) {
  const pts = []
  for (const dx of [-0.5, 0, 0.5]) for (const dy of [-0.5, 0, 0.5]) pts.push([x + dx * ancho, y + dy * alto])
  return pts.every(([px, py]) => {
    const d = Math.hypot(px - cx, py - cy)
    if (d < r + 6 || d > R - 6) return false
    let ang = Math.atan2(py - cy, px - cx)
    while (ang < desde) ang += Math.PI * 2
    while (ang > desde + Math.PI * 2) ang -= Math.PI * 2
    return ang <= hasta - 0.01 && ang >= desde + 0.01
  })
}

// Texto oscuro sobre porciones claras, blanco sobre las oscuras.
function tintaSobre(color) {
  const m = String(color).match(/\d+(\.\d+)?/g)
  let rgb = null
  if (/^#([0-9a-f]{6})$/i.test(color)) {
    const n = parseInt(color.slice(1), 16)
    rgb = [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  } else if (m && m.length >= 3) {
    rgb = m.slice(0, 3).map(Number)
  }
  if (!rgb) return INK_0
  const [rr, gg, bb] = rgb.map(v => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  const lum = 0.2126 * rr + 0.7152 * gg + 0.0722 * bb
  return lum > 0.3 ? FONDO_TINTA : INK_0
}

function pintarRendimiento(ctx, spec) {
  const colorTitulo = TONE[spec.tono] || INK_0
  let y = pintarTitular(ctx, spec, { tamano: 120, color: colorTitulo })

  // ── Subtítulo: período, moneda y (si eligió) el valor de la cartera ──
  ctx.textBaseline = 'top'
  ctx.fillStyle = INK_2
  ctx.font = `26px ${FONT_SANS}`
  const sub = [spec.subtitle, spec.patrimonio ? `Valor de la cartera ${spec.patrimonio}` : null]
    .filter(Boolean).join(' · ')
  y = wrapText(ctx, sub, PAD, y + 8, W - 2 * PAD, 34, 2)

  // ── Los números: cartera, benchmark, diferencia ───────────────────────
  y += 36
  const stats = spec.stats || []
  const col = (W - 2 * PAD) / Math.max(stats.length, 1)
  stats.forEach((s, i) => {
    const x = PAD + i * col
    ctx.fillStyle = INK_2
    ctx.font = `22px ${FONT_SANS}`
    ctx.fillText(truncateToWidth(ctx, String(s.label), col - 20), x, y)
    ctx.fillStyle = TONE[s.tono] && s.tono !== 'gray' ? TONE[s.tono] : INK_0
    ctx.font = `600 ${stats.length > 2 ? 34 : 40}px ${FONT_SANS}`
    ctx.fillText(truncateToWidth(ctx, String(s.value), col - 20), x, y + 34)
  })
  y += 120

  // ── El gráfico ───────────────────────────────────────────────────────
  const gx0 = PAD
  const gx1 = W - PAD
  const gy0 = y
  const gy1 = H - PAD - 120
  const serie = spec.serie || []
  const valores = serie.flatMap(p => [p.cartera, p.bench]).filter(Number.isFinite)
  if (serie.length > 1 && valores.length > 1) {
    const t0 = serie[0].ts
    const t1 = serie[serie.length - 1].ts
    let vMin = Math.min(0, ...valores)
    let vMax = Math.max(0, ...valores)
    const margen = (vMax - vMin) * 0.08 || 1
    vMin -= margen
    vMax += margen
    const X = (t) => gx0 + ((t - t0) / ((t1 - t0) || 1)) * (gx1 - gx0)
    const Y = (v) => gy1 - ((v - vMin) / (vMax - vMin)) * (gy1 - gy0)

    // El cero: punteado, la referencia de "ni gané ni perdí".
    ctx.strokeStyle = LINEA
    ctx.lineWidth = 2
    ctx.setLineDash([4, 8])
    ctx.beginPath()
    ctx.moveTo(gx0, Y(0))
    ctx.lineTo(gx1, Y(0))
    ctx.stroke()
    ctx.setLineDash([])

    // Tramos sin cortes: un null parte la línea (serie partida), como en la app.
    const tramos = (clave) => {
      const out = []
      let actual = []
      for (const p of serie) {
        if (Number.isFinite(p[clave])) actual.push(p)
        else if (actual.length) { out.push(actual); actual = [] }
      }
      if (actual.length) out.push(actual)
      return out
    }
    const trazar = (tramo, clave) => {
      ctx.beginPath()
      tramo.forEach((p, i) => (i ? ctx.lineTo(X(p.ts), Y(p[clave])) : ctx.moveTo(X(p.ts), Y(p[clave]))))
    }

    // El benchmark primero, debajo: gris punteado.
    ctx.strokeStyle = INK_2
    ctx.lineWidth = 3
    ctx.setLineDash([10, 10])
    for (const tramo of tramos('bench')) { trazar(tramo, 'bench'); ctx.stroke() }
    ctx.setLineDash([])

    // La cartera: violeta de marca, con el área debajo.
    for (const tramo of tramos('cartera')) {
      if (tramo.length > 1) {
        trazar(tramo, 'cartera')
        ctx.lineTo(X(tramo[tramo.length - 1].ts), gy1)
        ctx.lineTo(X(tramo[0].ts), gy1)
        ctx.closePath()
        const area = ctx.createLinearGradient(0, gy0, 0, gy1)
        area.addColorStop(0, hexToRgba(VIOLETA, 0.28))
        area.addColorStop(1, hexToRgba(VIOLETA, 0))
        ctx.fillStyle = area
        ctx.fill()
      }
      ctx.strokeStyle = VIOLETA
      ctx.lineWidth = 5
      ctx.lineJoin = 'round'
      trazar(tramo, 'cartera')
      ctx.stroke()
    }
  }

  // ── Leyenda + veredicto ───────────────────────────────────────────────
  const yLeyenda = gy1 + 34
  ctx.textBaseline = 'middle'
  ctx.lineWidth = 5
  ctx.strokeStyle = VIOLETA
  ctx.beginPath(); ctx.moveTo(PAD, yLeyenda); ctx.lineTo(PAD + 34, yLeyenda); ctx.stroke()
  ctx.fillStyle = INK_0
  ctx.font = `22px ${FONT_SANS}`
  ctx.fillText('Mi cartera', PAD + 46, yLeyenda)
  const xBench = PAD + 46 + ctx.measureText('Mi cartera').width + 40
  ctx.lineWidth = 3
  ctx.strokeStyle = INK_2
  ctx.setLineDash([8, 7])
  ctx.beginPath(); ctx.moveTo(xBench, yLeyenda); ctx.lineTo(xBench + 34, yLeyenda); ctx.stroke()
  ctx.setLineDash([])
  ctx.fillText(String(spec.benchLabel || ''), xBench + 46, yLeyenda)

  if (spec.veredicto) {
    ctx.fillStyle = VIOLETA
    ctx.font = `600 22px ${FONT_SANS}`
    ctx.textAlign = 'right'
    ctx.fillText(spec.veredicto, W - PAD, yLeyenda)
    ctx.textAlign = 'left'
  }
  ctx.textBaseline = 'top'

  pintarPie(ctx, spec)
}

// Los colores de las porciones vienen como `rgb(var(--x))` (siguen al tema en
// la app). El canvas no resuelve var(), así que se leen del navegador DENTRO de
// un contenedor `.dark`: la imagen es oscura siempre, y una porción tiene que
// verse con su color de modo oscuro aunque el usuario esté en claro.
function resolverColores(colores) {
  if (typeof document === 'undefined' || !document.body) {
    return colores.map(c => (c && !c.includes('var(') ? c : INK_3))
  }
  const caja = document.createElement('div')
  caja.className = 'dark'
  caja.style.display = 'none'
  const muestra = document.createElement('span')
  caja.appendChild(muestra)
  document.body.appendChild(caja)
  try {
    return colores.map((c) => {
      if (!c) return INK_3
      if (!c.includes('var(')) return c
      muestra.style.color = ''
      muestra.style.color = c
      return getComputedStyle(muestra).color || INK_3
    })
  } finally {
    caja.remove()
  }
}

// El isotipo se carga una vez por sesión. Con timeout, como las fuentes: sin
// logo la tarjeta sale igual (con la palabra "Rendi" sola).
let logoPromesa = null
function cargarLogo() {
  if (typeof Image === 'undefined') return Promise.resolve(null)
  if (!logoPromesa) {
    logoPromesa = new Promise((resolve) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = () => { logoPromesa = null; resolve(null) }
      img.src = LOGO_SRC
    })
  }
  const timeout = new Promise((resolve) => setTimeout(() => resolve(null), 1500))
  return Promise.race([logoPromesa, timeout])
}

// ── Helpers internos ──────────────────────────────────────────────────────

export function wrapText(ctx, text, x, y, maxWidth, lineHeight, maxLines = 6) {
  if (!text) return y
  const words = String(text).split(/\s+/).filter(Boolean)
  let line = ''
  let drawn = 0
  for (let i = 0; i < words.length; i++) {
    const test = line ? line + ' ' + words[i] : words[i]
    const w = ctx.measureText(test).width
    if (w > maxWidth && line) {
      ctx.fillText(line, x, y)
      y += lineHeight
      drawn++
      if (drawn >= maxLines - 1 && i < words.length - 1) {
        // Última línea: ellipsis con lo que queda
        const rest = words.slice(i).join(' ')
        const ell = truncateToWidth(ctx, rest, maxWidth, '…')
        ctx.fillText(ell, x, y)
        return y + lineHeight
      }
      line = words[i]
    } else {
      line = test
    }
  }
  if (line) {
    ctx.fillText(line, x, y)
    y += lineHeight
  }
  return y
}

function truncateToWidth(ctx, str, maxWidth, suffix = '…') {
  if (ctx.measureText(str).width <= maxWidth) return str
  let out = str
  while (out.length > 1 && ctx.measureText(out + suffix).width > maxWidth) {
    out = out.slice(0, -1)
  }
  return out + suffix
}

export function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

export function hexToRgba(hex, alpha) {
  const c = String(hex).replace('#', '')
  if (c.length !== 6) return `rgba(0,0,0,${alpha})`
  const n = parseInt(c, 16)
  const r = (n >> 16) & 255
  const g = (n >> 8) & 255
  const b = n & 255
  return `rgba(${r},${g},${b},${alpha})`
}

// Precarga de fuentes para Canvas con timeout. Si en 700ms no resuelve,
// seguimos con fallback de sistema — peor un PNG con system-ui que un hang.
async function ensureFontsReady() {
  if (typeof document === 'undefined' || !document.fonts) return
  try {
    const SIZES = [
      `28px Geist`, `54px Geist`, `92px Geist`, `26px Geist`, `24px Geist`,
      // Las de métricas (distribución / rendimiento) usan también estos pesos.
      `22px Geist`, `500 22px Geist`, `500 28px Geist`, `600 26px Geist`,
      `600 34px Geist`, `600 64px Geist`, `600 120px Geist`,
      `12px "JetBrains Mono"`, `13px "JetBrains Mono"`, `14px "JetBrains Mono"`,
    ]
    const loads = SIZES.map((spec) => {
      try { return document.fonts.load(spec) } catch { return Promise.resolve() }
    })
    const all = Promise.all(loads)
    const timeout = new Promise((resolve) => setTimeout(resolve, 700))
    await Promise.race([all, timeout])
  } catch { /* ignore */ }
}

function dataURLToBlob(dataURL) {
  const parts = dataURL.split(',')
  const mime = (parts[0].match(/:(.*?);/) || [])[1] || 'image/png'
  const bstr = atob(parts[1])
  const len = bstr.length
  const u8 = new Uint8Array(len)
  for (let i = 0; i < len; i++) u8[i] = bstr.charCodeAt(i)
  return new Blob([u8], { type: mime })
}
