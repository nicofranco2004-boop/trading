// Novedades — hub unificado de Eventos + Noticias.
// ════════════════════════════════════════════════════════════════════════════
// Reúne los dos bloques de "qué pasa en el mercado y en tu cartera". Reduce
// la complejidad del navbar (en lugar de 2 items, 1).
//
// Diseño: PageHeader con live-dot. Tabs outer prominentes con icono. Cada
// sección hija (Events/News) maneja su propio KPI strip + sub-tabs en URL.
//
// «Tus señales» (pieza 15) se mudó a Análisis técnico → «Señales de la
// semana» (recuadro 21c, 28/10). La pestaña queda como link (así nadie que la
// buscaba acá se pierde) y /novedades?tab=senales —la dirección de los mails y
// notificaciones viejos— redirige allá.
//
// URL state:
//   • ?tab=eventos|noticias  → sección activa (este componente)
//   • ?sub=…                 → sub-tab dentro de la sección (componente hijo)

import { useEffect } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { Activity, ArrowUpRight, Calendar, Newspaper } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Events from './Events'
import News from './News'
import AdvisorNovedades from './AdvisorNovedades'
import { useAuth } from '../contexts/AuthContext'
import { useAdvisorContext } from '../contexts/AdvisorContext'

const SECTIONS = [
  { value: 'eventos',  label: 'Eventos',  icon: Calendar },
  { value: 'noticias', label: 'Noticias', icon: Newspaper },
  // Se mudó: tocarla lleva a la pestaña de Análisis técnico.
  { value: 'senales',  label: 'Tus señales', icon: Activity, fuera: '/analisis-tecnico?tab=senales' },
]

const DEFAULT_SECTION = 'eventos'

function readSection(searchParams) {
  const t = searchParams.get('tab')
  return SECTIONS.find(s => s.value === t && !s.fuera) ? t : DEFAULT_SECTION
}

// El asesor, en su propio nivel (sin haber entrado a un cliente), no tiene
// cartera propia — "Novedades" ahí es el radar cross-cliente (los activos de
// TODOS sus clientes). Adentro de un cliente, el radar normal de ESA cartera.
// Mismo patrón wrapper que Dashboard.jsx → AdvisorDashboard.
export default function Novedades() {
  const { user } = useAuth()
  const { clientCtx } = useAdvisorContext()
  if (user?.tier === 'advisor' && !clientCtx) return <AdvisorNovedades />
  return <PersonalNovedades />
}

function PersonalNovedades() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const section = readSection(searchParams)
  const mudada = SECTIONS.find(s => s.fuera && s.value === searchParams.get('tab'))

  // Normalizamos URL una vez si llegamos sin ?tab=
  useEffect(() => {
    if (!searchParams.get('tab')) {
      const next = new URLSearchParams(searchParams)
      next.set('tab', DEFAULT_SECTION)
      setSearchParams(next, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function selectSection(value) {
    const fuera = SECTIONS.find(s => s.value === value)?.fuera
    if (fuera) { navigate(fuera); return }
    const next = new URLSearchParams(searchParams)
    next.set('tab', value)
    next.delete('sub')  // reset sub-tab al cambiar de sección
    setSearchParams(next, { replace: true })
  }

  // La dirección vieja de «Tus señales» (mails y notificaciones de antes).
  if (mudada) return <Navigate to={mudada.fuera} replace />

  return (
    <div className="page-shell-wide">
      <PageHeader
        title="Novedades"
        subtitle="Eventos y noticias del mercado, todo en un solo lugar."
        meta="Google News + yfinance"
      />

      {/* Tabs outer — section selector con border-b prominente. Más grandes
          que los sub-tabs internos (pills) para establecer jerarquía clara. */}
      <div
        role="tablist"
        aria-label="Secciones de Novedades"
        className="flex items-center gap-0.5 sm:gap-1 mb-5 border-b border-line overflow-x-auto scrollbar-none"
      >
        {SECTIONS.map(s => {
          const Icon = s.icon
          const active = section === s.value
          return (
            <button
              key={s.value}
              role="tab"
              aria-selected={active}
              aria-controls={`novedades-panel-${s.value}`}
              id={`novedades-tab-${s.value}`}
              onClick={() => selectSection(s.value)}
              className={`group flex items-center gap-1.5 sm:gap-2 px-2.5 sm:px-4 py-3 text-[14px] sm:text-[15px] font-semibold whitespace-nowrap border-b-2 -mb-px transition-colors ${
                active
                  ? 'border-rendi-accent text-ink-0'
                  : 'border-transparent text-ink-2 hover:text-ink-0'
              }`}
            >
              <Icon
                size={15}
                strokeWidth={1.75}
                className={active ? 'text-rendi-accent' : 'text-ink-3 group-hover:text-ink-1 transition-colors'}
              />
              {s.label}
              {s.fuera && <ArrowUpRight size={13} strokeWidth={2} aria-hidden="true" className="text-data-violet" />}
            </button>
          )
        })}
      </div>

      {/* Panel activo — montamos sólo uno para no fetchear ambas APIs al entrar. */}
      <div
        role="tabpanel"
        id={`novedades-panel-${section}`}
        aria-labelledby={`novedades-tab-${section}`}
      >
        {section === 'eventos'  && <Events  embedded />}
        {section === 'noticias' && <News    embedded />}
      </div>
    </div>
  )
}
