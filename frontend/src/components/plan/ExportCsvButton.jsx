// ExportCsvButton — botón "Exportar CSV" gateado por plan Pro.
// ═══════════════════════════════════════════════════════════════════════════
// UX:
//   • Pro/Admin: descarga directa con fetch authorizado, sin redirects.
//   • Free: el click abre UpgradeModal (no descarga, no llamada de red).
//
// Uso:
//   <ExportCsvButton resource="operations" label="Exportar a CSV" />
//
// resource: 'operations' | 'positions' | 'monthly'

import { useState } from 'react'
import { Download, Lock, Loader2 } from 'lucide-react'
import { api } from '../../utils/api'
import { track } from '../../utils/track'
import { usePlanFeatures } from '../../hooks/usePlanFeatures'
import UpgradeModal from './UpgradeModal'

export default function ExportCsvButton({
  resource,
  label = 'Exportar CSV',
  variant = 'default',  // 'default' | 'compact'
  source,
}) {
  const { can, loading: planLoading } = usePlanFeatures()
  const [downloading, setDownloading] = useState(false)
  const [showUpgrade, setShowUpgrade] = useState(false)
  const hasAccess = can('export.csv')

  async function onClick() {
    if (planLoading) return
    if (!hasAccess) {
      track('feature_blocked_clicked', { feature: 'export.csv', source: source || `export_${resource}` })
      setShowUpgrade(true)
      return
    }
    track('export_csv_downloaded', { resource })
    setDownloading(true)
    try {
      // Descargar como blob para forzar el browser a abrir el "guardar como"
      // sin perder la auth header.
      const blob = await api.getBlob(`/export/${resource}.csv`)
      const filename = `rendi_${resource}_${new Date().toISOString().slice(0, 10)}.csv`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (ex) {
      // Si el server cambió y devolvió 403 (race con downgrade), abrimos el modal
      if (ex?.status === 403 && ex?.payload?.detail?.upgrade) {
        setShowUpgrade(true)
      } else {
        console.error('Export CSV failed:', ex)
        alert('No pudimos generar el CSV. Probá de nuevo.')
      }
    } finally {
      setDownloading(false)
    }
  }

  const isCompact = variant === 'compact'
  const Icon = !hasAccess && !planLoading ? Lock : (downloading ? Loader2 : Download)

  return (
    <>
      <button
        type="button"
        onClick={onClick}
        disabled={downloading || planLoading}
        title={!hasAccess ? 'Disponible en Rendi Pro' : 'Descargar CSV'}
        className={`
          inline-flex items-center gap-1.5
          ${isCompact ? 'text-xs px-2.5 py-1.5' : 'text-sm px-3 py-1.5'}
          rounded-sm transition-colors border
          ${hasAccess
            ? 'bg-bg-2/60 hover:bg-bg-2 text-ink-1 hover:text-ink-0 border-line/60'
            : 'bg-data-violet/[0.04] hover:bg-data-violet/[0.08] text-data-violet border-data-violet/30'
          }
          disabled:opacity-50 disabled:cursor-not-allowed
        `}
      >
        <Icon size={12} strokeWidth={1.75} className={downloading ? 'animate-spin' : ''} />
        <span>{label}</span>
      </button>

      {showUpgrade && (
        <UpgradeModal
          title="Export CSV es exclusivo de Pro"
          message="Descargá tus operaciones, posiciones y resumen mensual en CSV — listo para mandárselo a tu contador."
          feature="export.csv"
          source={source || `export_${resource}`}
          onClose={() => setShowUpgrade(false)}
        />
      )}
    </>
  )
}
