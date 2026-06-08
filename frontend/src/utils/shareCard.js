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
//
// Spec shape:
//   {
//     kind: 'insight' | 'performance',
//     eyebrow: string,        // mono uppercase, accent color
//     title: string,          // headline grande (wrap automático)
//     subtitle?: string,      // gris, debajo del headline
//     stats?: [{ label, value }],  // bloques key→value, máx ~4
//     pill?: { label, tone }, // tone: red | green | amber | blue | gray
//     date?: string,          // pie derecho ("MAYO 2026")
//   }

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

// ── Render principal ──────────────────────────────────────────────────────

export async function renderShareCard(spec) {
  // Best-effort: precargar fuentes web para los tamaños que vamos a usar.
  // CRÍTICO: document.fonts.ready puede no resolver nunca en algunos browsers,
  // así que usamos Promise.race con timeout corto. Si no carga la fuente web,
  // Canvas cae al fallback del sistema (system-ui) — preferimos eso a un hang.
  await ensureFontsReady()

  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')

  const accent = TONE[spec.pill?.tone] || TONE.green

  // ── Background ────────────────────────────────────────────────────────
  const grad = ctx.createLinearGradient(0, 0, 0, H)
  grad.addColorStop(0, '#0E1218')
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

  // ── Header brand ──────────────────────────────────────────────────────
  let y = PAD
  ctx.textBaseline = 'top'

  ctx.fillStyle = '#E6EAF2'
  ctx.font = `600 28px ${FONT_SANS}`
  ctx.fillText('rendi', PAD, y)

  ctx.fillStyle = '#5A6478'
  ctx.font = `12px ${FONT_MONO}`
  ctx.textAlign = 'right'
  ctx.fillText('RENDI.APP', W - PAD, y + 8)
  ctx.textAlign = 'left'

  y += 110

  // ── Eyebrow ───────────────────────────────────────────────────────────
  if (spec.eyebrow) {
    ctx.fillStyle = accent
    ctx.font = `14px ${FONT_MONO}`
    ctx.fillText(String(spec.eyebrow).toUpperCase(), PAD, y)
    y += 40
  }

  // ── Title (headline grande, wrap) ─────────────────────────────────────
  if (spec.title) {
    ctx.fillStyle = '#E6EAF2'
    const titleSize = spec.kind === 'performance' ? 92 : 54
    ctx.font = `500 ${titleSize}px ${FONT_SANS}`
    y = wrapText(ctx, String(spec.title), PAD, y, W - 2 * PAD, titleSize * 1.05)
    y += 18
  }

  // ── Subtitle ──────────────────────────────────────────────────────────
  if (spec.subtitle) {
    ctx.fillStyle = '#9CA3B5'
    const subSize = 26
    ctx.font = `${subSize}px ${FONT_SANS}`
    y = wrapText(ctx, String(spec.subtitle), PAD, y, W - 2 * PAD, subSize * 1.35)
    y += 32
  }

  // ── Divider ───────────────────────────────────────────────────────────
  if (spec.stats?.length) {
    ctx.strokeStyle = '#1B2230'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(PAD, y)
    ctx.lineTo(W - PAD, y)
    ctx.stroke()
    y += 28

    // ── Stats rows ──────────────────────────────────────────────────────
    for (const stat of spec.stats.slice(0, 4)) {
      ctx.fillStyle = '#5A6478'
      ctx.font = `12px ${FONT_MONO}`
      ctx.fillText(String(stat.label || '').toUpperCase(), PAD, y + 6)

      ctx.fillStyle = '#E6EAF2'
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
    ctx.fillStyle = '#5A6478'
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
  const pctStr = `${sign}${Math.abs(pnlPct * 100).toFixed(2)}%`

  const label = monthRow?.month_label || monthRow?.month || ''

  const stats = []
  if (monthRow?.capital_inicio != null && !isNaN(monthRow.capital_inicio)) {
    stats.push({
      label: 'Capital inicial',
      value: `$${Math.round(monthRow.capital_inicio).toLocaleString('en-US')}`,
    })
  }
  if (monthRow?.capital_final != null && !isNaN(monthRow.capital_final)) {
    stats.push({
      label: 'Capital final',
      value: `$${Math.round(monthRow.capital_final).toLocaleString('en-US')}`,
    })
  }
  if (monthRow?.net != null && !isNaN(monthRow.net) && monthRow.net !== 0) {
    const netSign = monthRow.net >= 0 ? '+' : '−'
    stats.push({
      label: monthRow.net >= 0 ? 'Aportes netos' : 'Retiros netos',
      value: `${netSign}$${Math.abs(Math.round(monthRow.net)).toLocaleString('en-US')}`,
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
