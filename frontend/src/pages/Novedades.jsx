// Novedades — hub unificado de Eventos + Noticias.
// ════════════════════════════════════════════════════════════════════════════
// Reúne en una sola página los dos bloques de "qué pasa en el mercado y en
// tu cartera". Reduce la complejidad del navbar (en lugar de 2 items, 1).
//
// Implementación: usa los componentes <Events embedded /> y <News embedded />
// existentes — cada uno se renderea sin PageHeader interno y queda dentro
// de un único container con tabs de nivel superior.
//
// Las rutas /eventos y /noticias siguen funcionando (backwards compat) pero
// el navbar apunta sólo a /novedades.

import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Calendar, Newspaper } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Events from './Events'
import News from './News'

const SECTIONS = [
  { value: 'eventos',  label: 'Eventos',  icon: Calendar,  desc: 'Cupones, earnings, dividendos y macro' },
  { value: 'noticias', label: 'Noticias', icon: Newspaper, desc: 'Mercado y tu portfolio en vivo' },
]

export default function Novedades() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialTab = searchParams.get('tab')
  const [section, setSection] = useState(
    SECTIONS.find(s => s.value === initialTab) ? initialTab : 'eventos'
  )

  function selectSection(value) {
    setSection(value)
    setSearchParams({ tab: value }, { replace: true })
  }

  return (
    <div className="page-shell-wide">
      <PageHeader
        title="Novedades"
        subtitle="Eventos financieros y noticias del mercado, en un solo lugar."
      />

      {/* Tabs de nivel superior: Eventos / Noticias */}
      <div className="flex items-center gap-1 mb-2 border-b border-slate-200 dark:border-line">
        {SECTIONS.map(s => {
          const Icon = s.icon
          const active = section === s.value
          return (
            <button
              key={s.value}
              onClick={() => selectSection(s.value)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition ${
                active
                  ? 'border-rendi-accent text-ink-0'
                  : 'border-transparent text-ink-2 hover:text-ink-0'
              }`}
            >
              <Icon size={14} strokeWidth={1.75} />
              {s.label}
            </button>
          )
        })}
      </div>
      <p className="text-xs text-ink-2 mb-4">
        {SECTIONS.find(s => s.value === section)?.desc}
      </p>

      {/* Contenido según sección */}
      {section === 'eventos' && <Events embedded />}
      {section === 'noticias' && <News embedded />}
    </div>
  )
}
