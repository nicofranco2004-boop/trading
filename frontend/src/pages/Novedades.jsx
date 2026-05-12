// Novedades — hub unificado de Eventos + Noticias.
// ════════════════════════════════════════════════════════════════════════════
// Reúne en una sola página los dos bloques de "qué pasa en el mercado y en
// tu cartera". Reduce la complejidad del navbar (en lugar de 2 items, 1).
//
// Implementación: usa los componentes <Events embedded /> y <News embedded />
// existentes — cada uno se renderea sin PageHeader interno y queda dentro
// de un único container con tabs de nivel superior.
//
// Las rutas /eventos y /noticias siguen funcionando, pero ahora redirigen
// a /novedades?tab=… (ver App.jsx).
//
// URL state:
//   • ?tab=eventos|noticias  → sección activa (controlada por este componente)
//   • ?sub=…                 → sub-tab dentro de cada sección (la maneja
//                              el componente hijo via prop `embedded`).

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

  // Si llegamos a /novedades sin ?tab=, normalizamos la URL una vez para que
  // los share-links y el back-button siempre tengan estado explícito.
  useEffect(() => {
    if (!searchParams.get('tab')) {
      const next = new URLSearchParams(searchParams)
      next.set('tab', DEFAULT_SECTION)
      setSearchParams(next, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function selectSection(value) {
    // Al cambiar de sección reseteamos ?sub para que no quede un sub-tab
    // de otra sección (ej: ?sub=market que sólo aplica a Noticias).
    const next = new URLSearchParams(searchParams)
    next.set('tab', value)
    next.delete('sub')
    setSearchParams(next, { replace: true })
  }

  return (
    <div className="page-shell-wide">
      <PageHeader
        title="Novedades"
        subtitle="Eventos financieros y noticias del mercado, en un solo lugar."
      />

      {/* Tabs de nivel superior: outer tabs ─ visualmente más prominentes
          (icon + texto, semibold, padding amplio). Los sub-tabs internos
          de Events/News usan pills para evitar confusión jerárquica. */}
      <div
        role="tablist"
        aria-label="Secciones de Novedades"
        className="flex items-center gap-1 mb-2 border-b border-slate-200 dark:border-line"
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
              className={`flex items-center gap-2 px-4 py-2.5 text-[15px] font-semibold border-b-2 -mb-px transition ${
                active
                  ? 'border-rendi-accent text-ink-0'
                  : 'border-transparent text-ink-2 hover:text-ink-0'
              }`}
            >
              <Icon size={15} strokeWidth={1.75} />
              {s.label}
            </button>
          )
        })}
      </div>

      {/* Contenido según sección — montamos sólo el panel activo para no
          fetchear ambas APIs al entrar. Los hijos manejan su propio sub-tab
          en URL (?sub=…) cuando embedded=true. */}
      <div
        role="tabpanel"
        id={`novedades-panel-${section}`}
        aria-labelledby={`novedades-tab-${section}`}
        className="mt-4"
      >
        {section === 'eventos'  && <Events  embedded />}
        {section === 'noticias' && <News    embedded />}
      </div>
    </div>
  )
}
