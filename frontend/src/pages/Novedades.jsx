// Novedades — hub unificado de Eventos + Noticias.
// ════════════════════════════════════════════════════════════════════════════
// Reúne los dos bloques de "qué pasa en el mercado y en tu cartera". Reduce
// la complejidad del navbar (en lugar de 2 items, 1).
//
// Diseño: PageHeader con live-dot. Tabs outer prominentes con icono. Cada
// sección hija (Events/News) maneja su propio KPI strip + sub-tabs en URL.
//
// URL state:
//   • ?tab=eventos|noticias  → sección activa (este componente)
//   • ?sub=…                 → sub-tab dentro de la sección (componente hijo)

import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Calendar, Newspaper } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Events from './Events'
import News from './News'

const SECTIONS = [
  { value: 'eventos',  label: 'Eventos',  icon: Calendar },
  { value: 'noticias', label: 'Noticias', icon: Newspaper },
]

const DEFAULT_SECTION = 'eventos'

function readSection(searchParams) {
  const t = searchParams.get('tab')
  return SECTIONS.find(s => s.value === t) ? t : DEFAULT_SECTION
}

export default function Novedades() {
  const [searchParams, setSearchParams] = useSearchParams()
  const section = readSection(searchParams)

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
    const next = new URLSearchParams(searchParams)
    next.set('tab', value)
    next.delete('sub')  // reset sub-tab al cambiar de sección
    setSearchParams(next, { replace: true })
  }

  return (
    <div className="page-shell-wide">
      <PageHeader
        title="Novedades"
        subtitle="Eventos financieros y noticias del mercado — todo en un solo lugar."
        meta="Live · Google News + yfinance"
      />

      {/* Tabs outer — section selector con border-b prominente. Más grandes
          que los sub-tabs internos (pills) para establecer jerarquía clara. */}
      <div
        role="tablist"
        aria-label="Secciones de Novedades"
        className="flex items-center gap-1 mb-5 border-b border-line"
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
              className={`group flex items-center gap-2 px-4 py-3 text-[15px] font-semibold border-b-2 -mb-px transition-colors ${
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
