// Alertas — página dedicada a las alertas de precio y variación.
// ═══════════════════════════════════════════════════════════════════════════
// Movida desde Config › Notificaciones (2026-07): las alertas merecen su propio
// lugar en el nav (ítem "Alertas" del sidebar) en vez de estar enterradas en
// Configuración. El componente (AlertsManager) es el mismo — solo cambia dónde
// vive. Prefill vía ?new=&ccy= (desde el menú de una posición).
import { useSearchParams } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import AlertsManager from '../components/alerts/AlertsManager'
import { usePlanFeatures } from '../hooks/usePlanFeatures'

export default function Alertas() {
  const plan = usePlanFeatures()
  const [searchParams] = useSearchParams()
  // Prefill desde el menú de una posición: /alertas?new=MSFT.BA&ccy=ARS
  const newSym = searchParams.get('new')
  const prefill = newSym
    ? { symbol: newSym, currency: searchParams.get('ccy') || undefined }
    : undefined

  return (
    <div className="page-shell-wide">
      <PageHeader
        title="Alertas"
        subtitle="Avisos de precio objetivo y variación sobre tus activos."
      />
      <AlertsManager plan={plan} prefill={prefill} />
    </div>
  )
}
