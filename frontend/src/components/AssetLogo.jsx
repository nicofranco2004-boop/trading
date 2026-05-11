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

// ════════════════════════════════════════════════════════════════════════════
// Logos self-hosted. Todos los assets viven en /public/logos/{TICKER}.png
// generados con scripts/download-logos.mjs (cero dependencia externa en
// runtime). Si el archivo no existe (ticker raro / nuevo), el onError
// dispara el fallback de iniciales.
//
// Fiat (USD, ARS) se renderiza INLINE como un círculo de color con '$' —
// no requiere archivo PNG. USDT sí tiene archivo (vino de CoinCap, es el
// logo de Tether). Eso da consistencia: USDT con su logo de marca real,
// USD/ARS con render uniforme estilo "fiat icon".
// ════════════════════════════════════════════════════════════════════════════

// Configs para monedas fiat — render inline en lugar de fetchear archivo.
const FIAT = {
  USD: { bg: '#2E7D5F', sym: '$' },  // verde dollar bill, sobrio
  ARS: { bg: '#74ACDF', sym: '$' },  // celeste argentino (color bandera)
}

function isFiat(asset) {
  return !!FIAT[(asset || '').toUpperCase()]
}

// URL del logo. /logos/ se sirve desde public/ via Vite.
// Devolvemos null para ticker vacío (cae al fallback directo).
function logoUrlFor(asset) {
  if (!asset || typeof asset !== 'string') return null
  const clean = asset.trim().toUpperCase()
  if (!clean) return null
  return `/logos/${clean}.png`
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

  // Fiat (USD, ARS): render inline con $ sobre fondo de color — sin file fetch.
  // Aplicamos esto incluso cuando isCash=true porque el cash de un broker
  // USD se llama 'USD' y queremos el icono fiat (más claro que el Wallet
  // genérico). Lo mismo con cash ARS y USDT (el ticker USDT tiene archivo).
  const clean = (asset || '').trim().toUpperCase()
  if (isFiat(clean)) {
    const cfg = FIAT[clean]
    return (
      <div
        className={`rounded-full flex items-center justify-center flex-shrink-0 font-bold ${className}`}
        style={{ width: px, height: px, background: cfg.bg, color: 'white', fontSize: `${Math.round(size * 0.5)}px` }}
        aria-label={clean}
        role="img"
      >
        {cfg.sym}
      </div>
    )
  }

  // is_cash sin ticker fiat reconocido: icono Wallet (cash genérico)
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

  // Wrapper circular + img inscrita al ~78%. Sin esto los logos rectangulares
  // (Amazon, Intel, etc.) quedan recortados al circular y se ven zoomeados.
  // El padding interno los inscribe con respiración alrededor.
  return (
    <div
      className={`rounded-full bg-white border border-line flex items-center justify-center overflow-hidden flex-shrink-0 ${className}`}
      style={{ width: px, height: px }}
    >
      <img
        src={url}
        alt={asset}
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
        className="object-contain"
        style={{ width: '78%', height: '78%' }}
      />
    </div>
  )
}
