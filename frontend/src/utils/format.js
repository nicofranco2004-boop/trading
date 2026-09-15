// ═══════════════════════════════════════════════════════════════════════════
// Number formatting utilities
// ═══════════════════════════════════════════════════════════════════════════
// Audit visual mayo 2026: el formato "+USD 1,037.74" tiene el signo separado
// del número por el currency code, awkward de leer. Nueva convención:
// "+$1.037,74 USD" — signo pegado al dígito, currency code después.
//
// ⚠️ SEPARADORES — convención ARGENTINA para TODO, sin importar la moneda:
// el punto separa los miles y la coma los decimales ("US$ 1.037,74").
// Antes el locale se elegía por MONEDA (ARS→es-AR, USD→en-US), así que los
// pesos salían a la argentina y los dólares a la inglesa, muchas veces en la
// MISMA pantalla. Como casi todo Rendi se muestra en dólares, casi todos los
// números salían al revés de como se leen acá. Es el mismo criterio que ya
// aplicaba CurrencyContext (fmtMoneyRaw) y que en el backend vive en
// money_fmt.py. No volver a ramificar el locale por moneda.
//
// API:
// • fmtUsd(n)               → "USD 1.037,74"      (legacy, sin signo)
// • fmtArs(n)               → "ARS 1.037"          (legacy, sin signo)
// • fmtMoney(n, ccy, opts)  → "+$1.037,74 USD"    (nuevo, signed/no signed)
// • fmtSigned(n, ccy)       → "+$1.037,74 USD"    (shorthand de fmtMoney signed)
// • pct, pctSigned          → "+5,2%" etc.
// • parseNum(txt)           → lee lo que el usuario TIPEA (coma o punto)
// • colorClass              → tokens rendi-pos/neg/ink-2

// ── Raw number formatting (sin currency code) ────────────────────────────────

// El idioma con el que se escriben los números en TODA la app. No depende de
// la moneda ni del navegador del usuario: Rendi se lee en Argentina.
export const LOCALE = 'es-AR'

// Número crudo, sin símbolo ni signo, con separadores argentinos.
// minimumFractionDigits va junto con maximumFractionDigits a propósito: sin él
// un valor redondo con decimals=2 imprime "1.037" y se lee como mil treinta y
// siete en vez de como 1037,00.
export const nfmt = (n, decimals = 2) => {
  if (n == null || isNaN(n)) return '—'
  return Number(n).toLocaleString(LOCALE, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export const usd = (n, decimals = 2) => {
  if (n == null || isNaN(n)) return '—'
  const abs = Math.abs(n)
  const formatted = abs.toLocaleString(LOCALE, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
  return n < 0 ? `(${formatted})` : formatted
}

export const ars = (n) => {
  if (n == null || isNaN(n)) return '—'
  const abs = Math.abs(n)
  const formatted = abs.toLocaleString(LOCALE, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })
  return n < 0 ? `(${formatted})` : formatted
}

// ── Currency labelled (legacy: prefix "USD" o "ARS") ─────────────────────────
// Mantenidos por compat. La API es estable. Nuevos llamados deben usar
// fmtMoney/fmtSigned.

export const fmtUsd = (n, decimals = 2) => {
  if (n == null || isNaN(n)) return '—'
  return `USD ${usd(n, decimals)}`
}

export const fmtArs = (n) => {
  if (n == null || isNaN(n)) return '—'
  return `ARS ${ars(n)}`
}

export const fmtCurrency = (n, currency) => {
  const c = String(currency || 'USD').toUpperCase()
  if (c === 'ARS') return fmtArs(n)
  return fmtUsd(n)
}

// ── Currency con formato del audit: "+$1,037.74 USD" ─────────────────────────
// signed=true incluye + cuando positivo, − cuando negativo (sin paréntesis).
// signed=false omite signo en positivo (igual al formato bancario clásico).

export function fmtMoney(n, currency = 'USD', { signed = false, decimals } = {}) {
  if (n == null || isNaN(n)) return '—'

  const c = String(currency).toUpperCase()
  const isArs = c === 'ARS'
  const dec = decimals != null ? decimals : isArs ? 0 : 2
  const symbol = '$'
  const code = isArs ? 'ARS' : 'USD'

  const abs = Math.abs(n)
  const formatted = abs.toLocaleString(LOCALE, {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  })

  let sign = ''
  if (signed) {
    if (n > 0) sign = '+'
    else if (n < 0) sign = '−'  // signo unicode minus, no hyphen
  } else if (n < 0) {
    sign = '−'
  }

  return `${sign}${symbol}${formatted} ${code}`
}

export const fmtSigned = (n, currency = 'USD') =>
  fmtMoney(n, currency, { signed: true })

// ── Compact para axes de charts ──────────────────────────────────────────────

// El decimal del compacto también es coma: "$1,5M", no "$1.5M" — con punto se
// lee como separador de miles y "$1.5M" parece mil quinientos millones.
export const usdCompact = (n) => {
  if (n == null || isNaN(n)) return '—'
  const abs = Math.abs(n)
  const sign = n < 0 ? '−' : ''
  if (abs >= 1e6) return `${sign}$${nfmt(abs / 1e6, 1)}M`
  if (abs >= 1e3) return `${sign}$${nfmt(abs / 1e3, 1)}k`
  return `${sign}$${nfmt(abs, 0)}`
}

// ── Percent ──────────────────────────────────────────────────────────────────
// pct: con paréntesis para negativos (legacy)
// pctSigned: con + o − explícito (formato chart axis)

export const pct = (n, decimals = 2) => {
  if (n == null || isNaN(n)) return '—'
  const v = n * 100
  return n < 0 ? `(${nfmt(Math.abs(v), decimals)}%)` : `${nfmt(v, decimals)}%`
}

export const pctSigned = (n, decimals = 1) => {
  if (n == null || isNaN(n)) return '—'
  const v = n * 100
  const sign = v >= 0 ? '+' : '−'
  return `${sign}${nfmt(Math.abs(v), decimals)}%`
}

// ── Entrada: leer lo que el usuario TIPEA ────────────────────────────────────
//
// La contracara de nfmt. Si Rendi MUESTRA "1.037,74", tiene que ACEPTAR que la
// gente escriba "1.037,74" — y también "1037.74", que es lo que pega quien copia
// de un resumen del broker. Reglas, en orden:
//   hay coma   → la coma es el decimal y los puntos son miles ("1.037,74")
//   sólo puntos en grupos de 3 → son miles ("9.000" = nueve mil, no 9)
//   si no      → punto decimal normal ("380.5")
//
// Antes esto vivía copiado en 4 lugares con 3 criterios distintos: el más pobre
// (`String(v).replace(',', '.')`) convertía "1.234,56" en "1.234.56" → parseFloat
// leía 1,234 y se cargaba una compra de mil pesos como una de un peso.
// Cualquier campo donde se escriba un número usa ESTE parser. No escribir otro.
export function parseNum(v) {
  if (v == null || v === '') return NaN
  if (typeof v === 'number') return Number.isFinite(v) ? v : NaN

  // Se sacan los espacios (incluido el fino que algunos exports usan de separador
  // de miles) y sólo los símbolos que el propio Rendi imprime alrededor del
  // número. NO se borra "todo lo que no sea un dígito": ese atajo convertía
  // "1e5" en "15" — cien mil guardado como quince, sin un solo aviso.
  const s0 = String(v).trim()
    .replace(/[\s\u00a0\u202f]/g, '')
    .replace(/^(US\$|U\$S|\$|ARS|USDT|USD)/i, '')
    .replace(/(ARS|USDT|USD|%)$/i, '')
  if (!s0) return NaN

  // Lo que no tiene forma de número se RECHAZA. Devolver un número plausible para
  // algo mal escrito es peor que no devolver nada: el formulario puede avisar de
  // un campo vacío, pero no de un importe que quedó mal.
  const sci = s0.match(/^([+-]?[\d.,]+)[eE]([+-]?\d+)$/)
  const cuerpo = sci ? sci[1] : s0
  const exp = sci ? Number(sci[2]) : 0
  if (!/^[+-]?[\d.,]*\d[\d.,]*$/.test(cuerpo)) return NaN

  const signo = cuerpo.startsWith('-') ? -1 : 1
  const cifras = cuerpo.replace(/^[+-]/, '')
  let limpio

  if (cifras.includes(',')) {
    // Coma = decimal. Con más de una, no hay forma de saber qué quiso escribir.
    if ((cifras.match(/,/g) || []).length > 1) return NaN
    const [ent, dec] = cifras.split(',')
    // Los puntos que acompañan a una coma sólo pueden ser miles bien formados.
    if (ent.includes('.') && !/^\d{1,3}(\.\d{3})+$/.test(ent)) return NaN
    limpio = ent.replace(/\./g, '') + (dec ? '.' + dec : '')
  } else {
    const puntos = (cifras.match(/\./g) || []).length
    if (puntos > 1) {
      // Varios puntos: o son miles bien formados, o está mal escrito.
      if (!/^\d{1,3}(\.\d{3})+$/.test(cifras)) return NaN
      limpio = cifras.replace(/\./g, '')
    } else if (/^\d{1,3}\.\d{3}$/.test(cifras)) {
      limpio = cifras.replace('.', '')   // "9.000" = nueve mil
    } else {
      limpio = cifras                     // "380.5" = punto decimal
    }
  }

  const n = parseFloat(limpio) * signo * Math.pow(10, exp)
  return Number.isFinite(n) ? n : NaN
}

// Número → texto para un campo EDITABLE, con los mismos separadores que el
// resto: "7.230.825", "4.820,55", "0,00000123".
//
// Sólo se usa para lo que ESCRIBE el sistema (un campo autocalculado, un valor
// sugerido), nunca en cada tecla: lo que el usuario tipea se guarda crudo y se
// interpreta con parseNum al leerlo. Reformatear mientras alguien escribe le
// mueve el cursor y le traba el decimal.
export const numToInput = (n) => {
  if (n == null || !Number.isFinite(Number(n))) return ''
  return Number(n).toLocaleString(LOCALE, { maximumFractionDigits: 8 })
}

// Variante para formularios: devuelve null (no NaN) cuando no hay número, que es
// lo que los `save()` mandan al backend para "no tocar este campo".
export const parseNumOrNull = (v) => {
  const n = parseNum(v)
  return Number.isFinite(n) ? n : null
}

// Porcentaje que YA viene en escala de porcentaje (23.4 → "23,4%"), no en
// fracción — para eso están pct/pctSigned, que multiplican por 100.
//
// Existe porque decenas de pantallas interpolaban el número crudo pegado al
// signo: `{a.pct}%`. El backend manda `round(v, 1)`, así que un 23,4 llegaba
// como 23.4 y se leía "23.4%". No redondea ni cambia la escala: lo único que
// hace es escribir el separador como corresponde.
export const pctTxt = (n) => {
  if (n == null || n === '') return '—'
  if (typeof n === 'string') {
    // Algunos call sites ya traen el texto armado ("18,0"). `isNaN("18,0")` es
    // true, así que un chequeo numérico a secas los convertía en un guión — un
    // número que desaparece de la pantalla y no rompe ningún test.
    if (!/\d/.test(n)) return '—'
    return n.replace('.', ',') + '%'
  }
  if (isNaN(n)) return '—'
  return String(n).replace('.', ',') + '%'
}

// ── Color helper para values ─────────────────────────────────────────────────
// Usa tokens semánticos del audit: rendi-pos / rendi-neg / ink-2 (neutro).
// Reemplaza los emerald-400/red-400 que se usaban legacy.

export const colorClass = (n) =>
  n == null || isNaN(n) || n === 0
    ? 'text-ink-2'
    : n > 0
    ? 'text-rendi-pos'
    : 'text-rendi-neg'

// ── Misc ─────────────────────────────────────────────────────────────────────

export const MONTHS = [
  'ENERO','FEBRERO','MARZO','ABRIL','MAYO','JUNIO',
  'JULIO','AGOSTO','SEPTIEMBRE','OCTUBRE','NOVIEMBRE','DICIEMBRE'
]

// Rótulo de la ventana de tiempo de una métrica acumulada ("1A", "6m", "histórico").
// Existe porque la card "Acumulado" no decía sobre qué período medía: por defecto
// son los últimos 12 meses y cambia en silencio con los tabs 1A/2A/5A/MAX. Sin el
// rótulo, ese número se compara mentalmente contra el "Rendimiento anual" del
// Dashboard —que es toda la historia Y anualizado— y parecen contradecirse cuando
// en realidad miden cosas distintas.
export function labelVentanaMeses(meses) {
  if (!meses || !(meses > 0)) return 'histórico'
  return meses % 12 === 0 ? `${meses / 12}A` : `${meses}m`
}
