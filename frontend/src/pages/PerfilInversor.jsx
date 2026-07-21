// PerfilInversor — página del CRUCE "tu perfil declarado vs. tu cartera real".
// ═══════════════════════════════════════════════════════════════════════════
// Antes era un tab dentro de /analisis; ahora es un ítem propio del sidebar
// ("Perfil de inversor", grupo Análisis). Reusa Insights con
// _embeddedTab='perfil' (misma vista que tenía el tab). El TEST/cuestionario
// vive en Configuración › Test de inversor; si no está completo, la vista
// muestra el CTA para completarlo (lo maneja ProfileInvestorBlock adentro).

import { lazy, Suspense } from 'react'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'

const Insights = lazy(() => import('./Insights'))

export default function PerfilInversor() {
  return (
    <div className="page-shell-wide">
      <PageHeader
        eyebrow="Tu análisis"
        title="Perfil de inversor"
        subtitle="Tu perfil declarado vs. tu cartera real. Completá el test en Configuración › Test de inversor para afinar el cruce."
      />
      <Suspense fallback={<Skeleton className="h-64 rounded-lg" />}>
        <Insights _embeddedTab="perfil" />
      </Suspense>
    </div>
  )
}
