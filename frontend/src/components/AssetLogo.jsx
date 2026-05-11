// AssetLogo — logo del activo (acción / CEDEAR / cripto / fiat) con fallback.
// ════════════════════════════════════════════════════════════════════════════
// Orden de resolución (primer match gana):
//   1. Fiat reconocido (USD, ARS) → render inline con bandera SVG
//   2. Asset con archivo en /public/logos/{TICKER}.png → <img>
//   3. is_cash sin asset identificable → icono Wallet (cash genérico)
//   4. Asset sin archivo → fallback a iniciales con color hash
//
// Antes el orden tenía is_cash ANTES del archivo, lo cual causaba que la
// cash position USDT mostrara el Wallet en lugar del logo Tether real.

import { useState } from 'react'
import { Wallet } from 'lucide-react'

// ─── Banderas inline ────────────────────────────────────────────────────────
// SVGs simples y reconocibles para USD (bandera US) y ARS (bandera AR).
// Inscritas dentro de un círculo via clipPath. Sin archivos, sin fetches.

function UsFlag({ size }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      aria-label="USD"
      role="img"
      className="flex-shrink-0"
    >
      <defs>
        <clipPath id="usf-clip">
          <circle cx="32" cy="32" r="32" />
        </clipPath>
      </defs>
      <g clipPath="url(#usf-clip)">
        {/* 13 rayas rojas y blancas */}
        <rect width="64" height="64" fill="#B22234" />
        <rect y="5" width="64" height="5" fill="#fff" />
        <rect y="15" width="64" height="5" fill="#fff" />
        <rect y="25" width="64" height="5" fill="#fff" />
        <rect y="35" width="64" height="5" fill="#fff" />
        <rect y="45" width="64" height="5" fill="#fff" />
        <rect y="55" width="64" height="5" fill="#fff" />
        {/* cantón azul superior izq con estrellas estilizadas */}
        <rect width="28" height="32" fill="#3C3B6E" />
        {/* 9 puntitos representando estrellas (3×3 grilla simplificada) */}
        <g fill="#fff">
          <circle cx="7"  cy="8"  r="1.4" />
          <circle cx="14" cy="8"  r="1.4" />
          <circle cx="21" cy="8"  r="1.4" />
          <circle cx="7"  cy="16" r="1.4" />
          <circle cx="14" cy="16" r="1.4" />
          <circle cx="21" cy="16" r="1.4" />
          <circle cx="7"  cy="24" r="1.4" />
          <circle cx="14" cy="24" r="1.4" />
          <circle cx="21" cy="24" r="1.4" />
        </g>
      </g>
      <circle cx="32" cy="32" r="31" fill="none" stroke="rgba(0,0,0,0.08)" strokeWidth="1" />
    </svg>
  )
}

function ArFlag({ size }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      aria-label="ARS"
      role="img"
      className="flex-shrink-0"
    >
      <defs>
        <clipPath id="arf-clip">
          <circle cx="32" cy="32" r="32" />
        </clipPath>
      </defs>
      <g clipPath="url(#arf-clip)">
        <rect y="0"  width="64" height="22" fill="#74ACDF" />
        <rect y="22" width="64" height="20" fill="#fff" />
        <rect y="42" width="64" height="22" fill="#74ACDF" />
        {/* Sol de mayo estilizado: círculo amarillo + rayos básicos */}
        <circle cx="32" cy="32" r="6" fill="#F6B40E" />
        <g stroke="#F6B40E" strokeWidth="1.2" strokeLinecap="round">
          <line x1="32" y1="22" x2="32" y2="26" />
          <line x1="32" y1="38" x2="32" y2="42" />
          <line x1="22" y1="32" x2="26" y2="32" />
          <line x1="38" y1="32" x2="42" y2="32" />
          <line x1="25" y1="25" x2="27.5" y2="27.5" />
          <line x1="36.5" y1="36.5" x2="39" y2="39" />
          <line x1="25" y1="39" x2="27.5" y2="36.5" />
          <line x1="36.5" y1="27.5" x2="39" y2="25" />
        </g>
      </g>
      <circle cx="32" cy="32" r="31" fill="none" stroke="rgba(0,0,0,0.08)" strokeWidth="1" />
    </svg>
  )
}

const FIAT_RENDERERS = {
  USD: UsFlag,
  ARS: ArFlag,
}

function isFiat(asset) {
  return !!FIAT_RENDERERS[(asset || '').toUpperCase()]
}

// URL del logo. /logos/ se sirve desde public/ via Vite.
function logoUrlFor(asset) {
  if (!asset || typeof asset !== 'string') return null
  const clean = asset.trim().toUpperCase()
  if (!clean) return null
  return `/logos/${clean}.png`
}

// Hash determinístico para el color del fallback de iniciales.
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
  const [failed, setFailed] = useState(false)
  const px = `${size}px`
  const clean = (asset || '').trim().toUpperCase()

  // ─── 1. Fiat reconocido (USD, ARS) → bandera SVG inline ──────────────
  if (isFiat(clean)) {
    const Renderer = FIAT_RENDERERS[clean]
    return (
      <div
        className={`flex-shrink-0 ${className}`}
        style={{ width: px, height: px }}
      >
        <Renderer size={size} />
      </div>
    )
  }

  // ─── 2. Asset con archivo en /logos/ → <img> con fallback ───────────
  // OJO: este check va ANTES del isCash. Si la cash position es USDT,
  // queremos el logo real de Tether (no el Wallet icon genérico).
  const url = clean ? logoUrlFor(clean) : null
  if (url && !failed) {
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

  // ─── 3. Cash sin asset reconocible → Wallet icon ────────────────────
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

  // ─── 4. Asset sin archivo → iniciales con color hash ─────────────────
  const initials = (clean || '?').slice(0, 2)
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
