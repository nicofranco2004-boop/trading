// AssetResultRow — fila/tarjeta unificada para CUALQUIER resultado de búsqueda
// de activos en la app (Registrar compra, Mercado, Alertas, Fundamentals…).
// ════════════════════════════════════════════════════════════════════════════
// Formato: [logo]  TICKER  ·  Nombre del activo            [BADGE DE TIPO]
//                  (subtítulo opcional en muted)                     (right)
//
// El badge de tipo sale de ASSET_TYPE_META en utils/tickers.js (fuente única de
// vocabulario/color), así un CEDEAR se ve igual en las 5 superficies.
//
// Props:
//   symbol    — ticker (ej. 'AAPL'). Se usa para el logo y el texto grande.
//   name      — nombre del activo (ej. 'Apple Inc.').
//   type      — crypto | stock_us | stock_ar | cedear | etf | bond | index | fci
//   sub       — texto secundario opcional (ej. subgrupo de bono, emisor FCI).
//   right     — nodo opcional alineado a la derecha (ej. "3 clases ▾").
//   onClick   — handler al elegir la fila.
//   title     — texto grande alternativo (para FCI mostramos el nombre del
//               fondo en vez del símbolo).

import AssetLogo from './AssetLogo'
import AssetTypeBadge from './AssetTypeBadge'

export default function AssetResultRow({ symbol, name, type, sub, right, onClick, title }) {
  const primary = title || symbol
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-3 px-5 py-3 hover:bg-bg-2 dark:hover:bg-bg-2/40 transition-colors text-left focus:outline-none focus:bg-bg-2 dark:focus:bg-bg-2/40"
    >
      <AssetLogo asset={symbol} size={32} />
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-ink-0 text-sm tabular truncate">{primary}</p>
        {(name && name !== primary) && (
          <p className="text-xs text-ink-2 truncate">{name}</p>
        )}
        {sub && <p className="text-[11px] text-ink-3 truncate">{sub}</p>}
      </div>
      <AssetTypeBadge type={type} />
      {right && <span className="flex-shrink-0">{right}</span>}
    </button>
  )
}
