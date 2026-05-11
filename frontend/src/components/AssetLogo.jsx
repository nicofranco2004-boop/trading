// AssetLogo — logo real del activo (acción / CEDEAR / cripto) con fallback.
// ════════════════════════════════════════════════════════════════════════════
// Estrategia:
//   • is_cash         → icono Wallet (sin logo, es cash de broker)
//   • Cripto conocido → CoinCap CDN (assets.coincap.io)
//   • Stock / CEDEAR  → Financial Modeling Prep CDN (images.financialmodelingprep.com)
//   • Onerror (404)   → fallback a iniciales del ticker con color hash
//                       (mismo patrón que el AssetAvatar previo)
//
// Cero deps nuevas. Logos cacheados por el browser tras el primer load.
// No hay rate limit relevante para use case web personal.
//
// Tamaños:
//   • 32  → Positions table (default)
//   • 24  → listas densas (atribución en /insights, drivers en /reportes)
//   • >32 → cards destacadas

import { useState } from 'react'
import { Wallet } from 'lucide-react'

// Lista de tickers cripto que CoinCap soporta. La derivamos del backend
// (CRYPTO_SYMBOLS en main.py). Mantenemos solo los que efectivamente tienen
// asset en CoinCap — los muy nicho caen al fallback igual.
const CRYPTO_TICKERS = new Set([
  'BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'AVAX', 'DOGE', 'TRX', 'DOT',
  'MATIC', 'POL', 'LINK', 'LTC', 'BCH', 'NEAR', 'UNI', 'ATOM', 'XLM', 'ETC',
  'APT', 'ARB', 'OP', 'AAVE', 'MKR', 'SNX', 'CRV', 'COMP', 'SUSHI', 'YFI',
  '1INCH', 'BAL', 'DYDX', 'GMX', 'BLUR', 'GRT', 'LRC', 'ZRX', 'BAT', 'REN',
  'ALGO', 'VET', 'EGLD', 'FTM', 'FLOW', 'HBAR', 'THETA', 'XTZ', 'EOS', 'WAVES',
  'ZIL', 'NEO', 'QTUM', 'ICX', 'ONT', 'IOTA', 'ZEC', 'DASH', 'XMR', 'KAVA',
  'SAND', 'MANA', 'AXS', 'ENJ', 'IMX', 'CHZ', 'GALA',
  'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF',
  'SUI', 'SEI', 'TIA', 'INJ', 'PYTH', 'STRK', 'WLD',
  'FIL', 'STX', 'APE', 'LDO', 'PENDLE',
  'USDT', 'USDC', 'DAI',
])

// Detecta si un ticker es cripto. Mayúsculas para match con el set.
function isCryptoTicker(asset) {
  if (!asset) return false
  return CRYPTO_TICKERS.has(asset.toUpperCase())
}

// URL del logo según categoría. Devuelve null si no podemos inferir
// (caso raro — ticker vacío o no-string).
function logoUrlFor(asset) {
  if (!asset || typeof asset !== 'string') return null
  const clean = asset.trim().toUpperCase()
  if (!clean) return null
  if (isCryptoTicker(clean)) {
    // CoinCap usa lowercase en sus URLs
    return `https://assets.coincap.io/assets/icons/${clean.toLowerCase()}@2x.png`
  }
  // Stock / CEDEAR / ADR — FMP cubre US tickers (los CEDEARs argentinos usan
  // el mismo símbolo que su ADR, así que MELI/GGAL/etc. funcionan).
  return `https://financialmodelingprep.com/image-stock/${clean}.png`
}

// Hash determinístico para el color del fallback (mismo que el AssetAvatar
// previo, así si el logo falla el ticker mantiene su color estable).
function colorClassesForTicker(asset) {
  const hash = (asset || '').split('').reduce((h, c) => ((h << 5) - h + c.charCodeAt(0)) | 0, 0)
  const palette = [
    'bg-rendi-accent/15 text-rendi-accent border-rendi-accent/30',
    'bg-blue-500/15 text-blue-500 border-blue-500/30',
    'bg-violet-500/15 text-violet-500 border-violet-500/30',
    'bg-cyan-500/15 text-cyan-500 border-cyan-500/30',
    'bg-amber-500/15 text-amber-500 border-amber-500/30',
    'bg-pink-500/15 text-pink-500 border-pink-500/30',
  ]
  return palette[Math.abs(hash) % palette.length]
}

export default function AssetLogo({ asset, isCash, size = 32, className = '' }) {
  // El estado `failed` se setea cuando el browser dispara onError sobre el
  // <img>. Ahí pintamos las iniciales con el color hash en su lugar.
  const [failed, setFailed] = useState(false)

  const px = `${size}px`

  // is_cash: icono Wallet — no es activo de mercado, no tiene logo
  if (isCash) {
    return (
      <div
        className={`rounded-full bg-bg-3 border border-line flex items-center justify-center flex-shrink-0 ${className}`}
        style={{ width: px, height: px }}
        aria-hidden="true"
      >
        <Wallet
          size={Math.round(size * 0.45)}
          strokeWidth={1.5}
          className="text-ink-2"
        />
      </div>
    )
  }

  // Logo real con fallback a iniciales
  const url = logoUrlFor(asset)
  const initials = (asset || '?').slice(0, 2).toUpperCase()

  if (!url || failed) {
    // Fallback: iniciales con color hash (idéntico al AssetAvatar legacy)
    const colors = colorClassesForTicker(asset)
    return (
      <div
        className={`rounded-full border flex items-center justify-center flex-shrink-0 font-mono font-semibold tracking-tighter ${colors} ${className}`}
        style={{
          width: px,
          height: px,
          fontSize: `${Math.round(size * 0.32)}px`,
        }}
        aria-label={asset || 'Activo'}
        role="img"
      >
        {initials}
      </div>
    )
  }

  return (
    <img
      src={url}
      alt={asset}
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
      className={`rounded-full bg-white object-contain flex-shrink-0 ${className}`}
      style={{ width: px, height: px }}
    />
  )
}
