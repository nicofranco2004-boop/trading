// AssetTypeBadge — el "cartelito" de tipo de activo (Acción US / CEDEAR / Cripto
// / Bono / FCI…), idéntico en TODAS las búsquedas de la app.
// ════════════════════════════════════════════════════════════════════════════
// Vocabulario + color salen de ASSET_TYPE_META (utils/tickers.js), única fuente
// de verdad. Si el tipo es desconocido, no renderiza nada.
//
// Props:
//   type — crypto | stock_us | stock_ar | cedear | etf | bond | index | fci

import { assetTypeMeta } from '../utils/tickers'

export default function AssetTypeBadge({ type, className = '' }) {
  const meta = assetTypeMeta(type)
  if (!meta) return null
  return (
    <span className={`flex-shrink-0 text-[9px] font-mono uppercase tracking-[0.12em] px-1.5 py-0.5 rounded-sm border ${meta.cls} ${className}`}>
      {meta.label}
    </span>
  )
}
