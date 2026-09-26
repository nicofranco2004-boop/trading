// ExportCsvButton — botón "Exportar CSV" gateado por plan (`export.csv`).
// ═══════════════════════════════════════════════════════════════════════════
// UX:
//   • Con acceso: descarga directa con fetch authorizado, sin redirects.
//   • Sin acceso: el botón muestra el candado y el click le pregunta al
//     backend, que responde el 403 con el cartel (`upgrade`) armado con los
//     límites reales (`billing/plan_textos`). Antes abría el modal SIN pedir
//     nada, y el modal caía en su lista de repuesto escrita a mano — la del
//     Pro, con "10× más análisis IA (60/sem vs 6/sem)" y "Distribución por
//     activo" — para un cartel que ofrece Plus. Un pedido que rebota en el
//     gate cuesta milisegundos: el gate es lo primero que corre el endpoint.
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
import { hoyISO } from '../../utils/fecha'

export default function ExportCsvButton({
  resource,
  label = 'Exportar CSV',
  variant = 'default',  // 'default' | 'compact'
  source,
}) {
  const { can, loading: planLoading } = usePlanFeatures()
  const [downloading, setDownloading] = useState(false)
  // El 403 del backend tal cual: `{ error, upgrade: { target_tier, benefits } }`.
  const [bloqueo, setBloqueo] = useState(null)
  const hasAccess = can('export.csv')

  async function onClick() {
    if (planLoading) return
    if (hasAccess) track('export_csv_downloaded', { resource })
    setDownloading(true)
    try {
      // Descargar como blob para forzar el browser a abrir el "guardar como"
      // sin perder la auth header.
      const blob = await api.getBlob(`/export/${resource}.csv`)
      // Filename amistoso en español para el user (el contenido viene del
      // backend con label en español también).
      const spanish = {
        operations: 'operaciones',
        positions: 'posiciones',
        monthly: 'mensual',
        transactions: 'movimientos',
      }[resource] || resource
      const filename = `rendi_${spanish}_${hoyISO()}.csv`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (ex) {
      // 403 = no está en su plan (o se le venció en el medio): el cartel lo
      // arma el backend, con la lista de lo que da el plan que ofrece.
      const detail = ex?.status === 403 ? ex?.payload?.detail : null
      if (detail?.upgrade) {
        track('feature_blocked_clicked', { feature: 'export.csv', source: source || `export_${resource}` })
        setBloqueo(detail)
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
        title={!hasAccess ? 'Ver qué plan lo incluye' : 'Descargar CSV'}
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

      {bloqueo && (
        <UpgradeModal
          targetTier={bloqueo.upgrade.target_tier}
          message={bloqueo.error}
          feature="export.csv"
          source={source || `export_${resource}`}
          benefits={bloqueo.upgrade.benefits}
          onClose={() => setBloqueo(null)}
        />
      )}
    </>
  )
}
