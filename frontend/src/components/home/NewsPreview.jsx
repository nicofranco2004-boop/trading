// NewsPreview — "Noticias del mercado" como cable de noticias (2026-09-29).
// Link a /novedades para deep dive.
//
// Una línea de tiempo: la hora a la izquierda, un punto por noticia sobre una
// línea vertical, el titular, la fuente, cuánto hace y el tema (NewsTagBadge,
// el MISMO distintivo de la página de Noticias — los temas los pone el
// servidor por palabras clave: Tasas, Inflación, Earnings…).
//
// Se refresca sola cada 5 min con la pestaña a la vista (relojVisible). Una
// noticia que no estaba entra arriba marcada "Nueva", con el punto violeta y
// un destello que se apaga solo. La primera carga no marca nada: "nueva"
// quiere decir "llegó mientras mirabas". El servidor renueva el feed cada 60
// min (NEWS_MARKET_TTL), así que la marca aparece sólo cuando hay algo nuevo
// de verdad, no como adorno.
//
// A propósito NO se usa el `sentiment` que manda el servidor: es un conteo de
// palabras ("caída" resta aunque sea la caída de la inflación), y pintar una
// noticia de verde o rojo con eso sería afirmar algo que no sabemos.

import { forwardRef, useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Newspaper, ExternalLink } from 'lucide-react'
import { api } from '../../utils/api'
import { safeExternalUrl } from '../../utils/safeUrl'
import { haceCuanto, fechaISO, diaMes } from '../../utils/fecha'
import { REFRESCO_MERCADO_MS } from '../../utils/relojVisible'
import { useRelojVisible } from '../../hooks/useRelojVisible'
import { useAlVerse } from '../../hooks/useAlVerse'
import { useUltimoPedido } from '../../hooks/useUltimoPedido'
import Panel from '../Panel'
import Eyebrow from '../Eyebrow'
import NewsTagBadge from '../NewsTagBadge'

const CUANTAS = 4

// La marca de la columna de la izquierda: la hora si es de hoy, "ayer", o la
// fecha. Siempre en el día del usuario (fecha.js), no en UTC.
export function horaDelCable(iso, ahora = new Date()) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const dia = fechaISO(d)
  if (dia === fechaISO(ahora)) {
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  const ayer = new Date(ahora)
  ayer.setDate(ayer.getDate() - 1)
  if (dia === fechaISO(ayer)) return 'ayer'
  return diaMes(dia)
}

// Las URLs de `news` que no estaban en `vistas`. Con `vistas` vacío (primera
// carga) no hay nuevas: nada "llegó" todavía.
export function urlsNuevas(vistas, news) {
  if (!vistas || vistas.size === 0) return new Set()
  return new Set((news || []).map(n => n.url).filter(u => u && !vistas.has(u)))
}

// El cable en sí, separado del que pide los datos para poder dibujarlo en los
// tests con noticias "nuevas" (en el demo nunca llega ninguna).
export const Cable = forwardRef(function Cable({ news, nuevas = new Set(), visto = true }, listaRef) {
  return (
    <ul ref={listaRef} className="py-1">
      {news.map((n, i) => {
        const nueva = nuevas.has(n.url)
        const ultima = i === news.length - 1
        return (
          <li
            key={n.url || i}
            className={visto ? 'entra' : 'por-entrar'}
            style={{ '--i': i }}
          >
            {/* El destello va en el renglón y no en el <li>: el <li> ya
                tiene la animación de entrada, y dos animaciones en el mismo
                elemento se pisan — la segunda regla borra la primera. */}
            <a
              href={safeExternalUrl(n.url)}
              target="_blank" rel="noopener noreferrer"
              className={`group flex gap-3 px-3 hover:bg-bg-2/60 transition-colors ${nueva ? 'destello-nueva' : ''}`}
            >
              <time
                dateTime={n.published_at || undefined}
                className="w-10 shrink-0 pt-2.5 text-right text-[11.5px] text-ink-3 tabular"
              >
                {horaDelCable(n.published_at)}
              </time>
              {/* La línea de tiempo: un tramo de línea por noticia y su punto. */}
              <span aria-hidden="true" className="relative w-2 shrink-0">
                {news.length > 1 && (
                  <span className={`absolute left-1/2 -translate-x-1/2 w-px bg-line ${i === 0 ? 'top-4' : 'top-0'} ${ultima ? 'h-4' : 'bottom-0'}`} />
                )}
                <span className={`absolute left-1/2 -translate-x-1/2 top-3 w-2 h-2 rounded-full border ${nueva ? 'bg-data-violet border-data-violet' : 'bg-bg-1 border-line-3'}`} />
              </span>
              <div className="flex-1 min-w-0 py-2">
                <p className="text-sm text-ink-1 leading-snug line-clamp-2 group-hover:text-ink-0">{n.title}</p>
                <div className="flex items-center gap-1.5 mt-1 text-[12px] text-ink-3 flex-wrap">
                  {(n.tags || []).slice(0, 1).map(t => <NewsTagBadge key={t} tag={t} />)}
                  <span className="font-medium">{n.source || '—'}</span>
                  <span>·</span>
                  <span>{haceCuanto(n.published_at)}</span>
                  {nueva && <span className="text-data-violet font-medium">· Nueva</span>}
                </div>
              </div>
              <ExternalLink size={10} className="flex-shrink-0 mt-3 text-ink-3" strokeWidth={1.75} aria-hidden="true" />
            </a>
          </li>
        )
      })}
    </ul>
  )
})

export default function NewsPreview() {
  const [news, setNews] = useState([])
  const [loading, setLoading] = useState(true)
  const [nuevas, setNuevas] = useState(() => new Set())
  const vistas = useRef(new Set())
  const [ref, visto] = useAlVerse()
  const nuevoPedido = useUltimoPedido()

  const cargar = useCallback(() => {
    // Una respuesta que llega tarde no pisa a una más nueva.
    const vigente = nuevoPedido()
    return api.get(`/news/market?limit=${CUANTAS}`)
      .then(d => {
        if (!vigente()) return
        const lista = d.news || []
        setNuevas(urlsNuevas(vistas.current, lista))
        lista.forEach(n => n.url && vistas.current.add(n.url))
        setNews(lista)
      })
      // Un refresco que falla no vacía el cable que ya se ve.
      .catch(() => {})
      .finally(() => { if (vigente()) setLoading(false) })
  }, [nuevoPedido])

  useEffect(() => { cargar() }, [cargar])
  useRelojVisible(cargar, REFRESCO_MERCADO_MS)

  return (
    <Panel padding="none" className="overflow-hidden">
      <header className="px-3 py-2 border-b border-line flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Newspaper size={12} strokeWidth={1.75} className="text-ink-3" aria-hidden="true" />
          <Eyebrow>Noticias del mercado</Eyebrow>
        </div>
        <Link
          to="/novedades?tab=noticias"
          className="text-[12.5px] font-medium text-ink-2 hover:text-ink-0 inline-flex items-center gap-1"
        >
          Ver todas <ArrowRight size={11} strokeWidth={1.75} aria-hidden="true" />
        </Link>
      </header>

      {loading ? (
        <div className="p-3 space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-12 rounded-sm bg-bg-2 animate-pulse" />
          ))}
        </div>
      ) : news.length === 0 ? (
        <div className="p-4 text-xs text-ink-3">Sin noticias disponibles ahora.</div>
      ) : (
        <Cable ref={ref} news={news} nuevas={nuevas} visto={visto} />
      )}
    </Panel>
  )
}
