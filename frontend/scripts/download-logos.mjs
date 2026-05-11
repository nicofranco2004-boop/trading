#!/usr/bin/env node
// download-logos.mjs
// ════════════════════════════════════════════════════════════════════════════
// Baja TODOS los logos de los tickers que aparecen en el buscador de Rendi
// y los guarda en /public/logos/{TICKER}.png. Una vez ejecutado, el frontend
// queda con cero dependencia externa para los logos.
//
// Fuentes:
//   • Cripto → assets.coincap.io
//   • Stocks / ETFs / CEDEARs / Índices → financialmodelingprep.com
//
// Detección de placeholders:
//   FMP devuelve un PNG válido pero CASI VACÍO cuando no tiene el logo (ej.
//   INTC). Detectamos por dimensión + filesize y skipeamos esos casos
//   (en runtime caen al fallback de iniciales).
//
// Uso:
//   cd frontend && node scripts/download-logos.mjs
//
// Idempotente: si el archivo ya existe, no lo vuelve a bajar (excepto
// con flag --force).

import { writeFileSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  CRYPTO, STOCKS_US, ETFS, INDICES, CEDEARS_LIST, ARG_LIDER, ARG_GENERAL,
} from '../src/utils/tickers.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT_DIR = join(__dirname, '..', 'public', 'logos')
const FORCE = process.argv.includes('--force')

if (!existsSync(OUT_DIR)) mkdirSync(OUT_DIR, { recursive: true })

// ─── Tickers únicos por categoría ────────────────────────────────────────
// El TickerSearch combina varias listas; deduplicamos antes de bajar.
// Cripto va a CoinCap, el resto a FMP.
const CRYPTO_TICKERS = new Set(CRYPTO.map(x => x.s.toUpperCase()))
const STOCK_TICKERS = new Set([
  ...STOCKS_US, ...ETFS, ...INDICES, ...CEDEARS_LIST, ...ARG_LIDER, ...ARG_GENERAL,
].map(x => x.s.toUpperCase()))
// Cripto tiene prioridad si hay overlap (USDT puede estar en ambas)
for (const c of CRYPTO_TICKERS) STOCK_TICKERS.delete(c)

console.log(`Tickers a procesar:`)
console.log(`  Cripto: ${CRYPTO_TICKERS.size}`)
console.log(`  Stocks/ETFs/CEDEARs/Índices: ${STOCK_TICKERS.size}`)
console.log(`  Total: ${CRYPTO_TICKERS.size + STOCK_TICKERS.size}`)
console.log(`Output: ${OUT_DIR}`)
console.log(`Force re-download: ${FORCE ? 'sí' : 'no'}`)
console.log('')

// ─── PNG header parser (extrae width sin deps) ───────────────────────────
function getPngDimensions(buf) {
  if (buf.length < 24) return null
  // PNG signature: 89 50 4E 47 0D 0A 1A 0A — bytes 0-7
  // IHDR chunk: bytes 8-11 (length=13), 12-15 (type=IHDR), 16-19 (width), 20-23 (height)
  const width = (buf[16] << 24) | (buf[17] << 16) | (buf[18] << 8) | buf[19]
  const height = (buf[20] << 24) | (buf[21] << 16) | (buf[22] << 8) | buf[23]
  return { width, height }
}

// FMP devuelve PNGs placeholder cuando no tiene el logo. Detectamos por
// dimensión + filesize. Análisis empírico (mayo 2026):
//   Logos legítimos 250x250: NVDA 11KB, AMZN 9KB, GOOG 12KB, TSLA 9KB
//   Placeholder confirmado: INTC 6KB, MSFT <1KB (250x250)
//   Tickers que no existen: FMP devuelve 22 bytes ASCII (error text)
function isLikelyPlaceholder(buf, source) {
  if (buf.length < 100) return true   // probablemente HTML/error text
  if (source !== 'fmp') return false  // CoinCap no tiene este problema
  const dims = getPngDimensions(buf)
  if (!dims) return true
  // FMP placeholder: 250x250 y < 7000 bytes
  if (dims.width === 250 && buf.length < 7000) return true
  return false
}

// Mapping ticker → dominio oficial para usar Google Favicons como fallback
// cuando FMP devuelve placeholder. Cobertura: tickers populares conocidos.
// Si aparece un ticker placeholder nuevo, agregarlo acá.
const TICKER_TO_DOMAIN = {
  // Tech mega-caps que FMP no cubre
  MSFT: 'microsoft.com',
  AMD:  'amd.com',
  NFLX: 'netflix.com',
  INTC: 'intel.com',
  ROKU: 'roku.com',
  ADSK: 'autodesk.com',
  // Consumer / industriales
  NKE:  'nike.com',
  ABT:  'abbott.com',
  ACN:  'accenture.com',
  AMGN: 'amgen.com',
  NOC:  'northropgrumman.com',
  LOW:  'lowes.com',
  // Healthcare / biotech
  BNTX: 'biontech.com',
}

// ─── Descarga con timeout + retry ────────────────────────────────────────
async function downloadOne(url, timeoutMs = 5000) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(url, { signal: controller.signal })
    if (!res.ok) return { ok: false, reason: `HTTP ${res.status}` }
    const buf = Buffer.from(await res.arrayBuffer())
    return { ok: true, buf }
  } catch (e) {
    return { ok: false, reason: e.name === 'AbortError' ? 'timeout' : e.message }
  } finally {
    clearTimeout(timer)
  }
}

async function downloadLogo(ticker, source) {
  const url = source === 'crypto'
    ? `https://assets.coincap.io/assets/icons/${ticker.toLowerCase()}@2x.png`
    : `https://financialmodelingprep.com/image-stock/${ticker}.png`

  const outPath = join(OUT_DIR, `${ticker}.png`)
  if (!FORCE && existsSync(outPath)) {
    return { ticker, status: 'skipped' }
  }

  const r = await downloadOne(url)
  if (!r.ok) {
    // Si FMP falla con 404, probamos Google Favicons como fallback
    if (source !== 'crypto' && TICKER_TO_DOMAIN[ticker]) {
      return await tryFavicon(ticker, outPath)
    }
    return { ticker, status: 'failed', reason: r.reason }
  }

  if (isLikelyPlaceholder(r.buf, source === 'crypto' ? 'coincap' : 'fmp')) {
    // FMP devolvió placeholder — intentamos favicon si tenemos el domain mapeado
    if (TICKER_TO_DOMAIN[ticker]) {
      return await tryFavicon(ticker, outPath)
    }
    return { ticker, status: 'placeholder' }
  }

  writeFileSync(outPath, r.buf)
  return { ticker, status: 'ok', bytes: r.buf.length }
}

// Google Favicons como fallback. Cobertura ~100% para empresas con web,
// calidad decente con sz=128. Solo lo usamos cuando FMP devuelve placeholder
// o 404 y tenemos el dominio mapeado en TICKER_TO_DOMAIN.
async function tryFavicon(ticker, outPath) {
  const domain = TICKER_TO_DOMAIN[ticker]
  const url = `https://www.google.com/s2/favicons?domain=${domain}&sz=128`
  const r = await downloadOne(url)
  if (!r.ok) return { ticker, status: 'failed', reason: `favicon: ${r.reason}` }
  // Favicons muy chicos (<300 bytes) suelen ser placeholders de Google
  if (r.buf.length < 300) return { ticker, status: 'placeholder' }
  writeFileSync(outPath, r.buf)
  return { ticker, status: 'ok-favicon', bytes: r.buf.length }
}

// ─── Run con throttle suave (no abusar de FMP/CoinCap) ──────────────────
const CONCURRENCY = 6  // 6 descargas en paralelo — gentil con los CDNs

async function processList(tickers, source) {
  const arr = [...tickers]
  const results = []
  let idx = 0
  async function worker() {
    while (idx < arr.length) {
      const i = idx++
      const t = arr[i]
      const r = await downloadLogo(t, source)
      results.push(r)
      const tag = r.status === 'ok' ? '✓' : r.status === 'ok-favicon' ? '★' : r.status === 'skipped' ? '·' : '✗'
      process.stdout.write(`\r[${source}] ${i + 1}/${arr.length} ${tag} ${t.padEnd(8)}      `)
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCY }, worker))
  process.stdout.write('\n')
  return results
}

console.log('Descargando cripto…')
const cryptoResults = await processList(CRYPTO_TICKERS, 'crypto')

console.log('Descargando stocks/etfs/cedears/índices…')
const stockResults = await processList(STOCK_TICKERS, 'stock')

// ─── Summary ──────────────────────────────────────────────────────────────
const all = [...cryptoResults, ...stockResults]
const ok = all.filter(r => r.status === 'ok').length
const okFavicon = all.filter(r => r.status === 'ok-favicon').length
const skipped = all.filter(r => r.status === 'skipped').length
const placeholder = all.filter(r => r.status === 'placeholder')
const failed = all.filter(r => r.status === 'failed')

console.log('')
console.log('═════════════════════════════════════════════')
console.log(`Resultado: ${all.length} tickers procesados`)
console.log(`  ✓ Descargados de FMP/CoinCap: ${ok}`)
console.log(`  ★ Descargados de Google Favicons (fallback): ${okFavicon}`)
console.log(`  · Skipped (ya existían): ${skipped}`)
console.log(`  · Placeholders detectados: ${placeholder.length}`)
console.log(`  ✗ Fallaron: ${failed.length}`)

if (placeholder.length > 0) {
  console.log('')
  console.log('Placeholders (sin logo en CDN — caen a iniciales en runtime):')
  console.log('  ' + placeholder.map(r => r.ticker).join(', '))
}
if (failed.length > 0) {
  console.log('')
  console.log('Fallos:')
  for (const r of failed.slice(0, 20)) {
    console.log(`  ${r.ticker}: ${r.reason}`)
  }
  if (failed.length > 20) console.log(`  ... y ${failed.length - 20} más`)
}
