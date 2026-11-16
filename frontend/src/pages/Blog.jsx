// Blog — índice del blog público de Rendi.
// ════════════════════════════════════════════════════════════════════════════
// Página /blog que lista todos los artículos publicados con metadata. Cada
// post vive en pages/blog/articles/{slug}.jsx — para agregar uno nuevo,
// crear el archivo + agregar su entrada en data/blogPosts.js + ruta en
// App.jsx + sumar al sitemap.
//
// Estrategia editorial: contenido pillar que rankea long-tail AR. Cada
// artículo target una keyword específica que un inversor argentino
// googlearía: "FIFO CEDEARs", "P&L USD blue", "comparativa brokers AR", etc.

import { Link } from 'react-router-dom'
import { ArrowRight, Calendar } from 'lucide-react'
import CabeceraPublica from '../components/CabeceraPublica'
import PageMeta from '../components/PageMeta'
import { POSTS } from '../data/blogPosts'

// Los posts publicados salen de data/blogPosts.js, la misma lista que usa cada
// artículo: así el título y la descripción del índice no se separan de los suyos.

export default function Blog() {
  return (
    <div className="min-h-screen bg-bg-0 text-ink-0">
      <PageMeta
        title="Blog de Rendi — Tracker de inversiones Argentina"
        description="Artículos sobre impuestos y FIFO en CEDEARs, tu ganancia real en dólares, cripto y comparativas de brokers argentinos. Para inversores con varios brokers."
        canonical="/blog"
      />

      <CabeceraPublica>
        <Link to="/planes" className="text-ink-2 hover:text-ink-0">Planes</Link>
        <Link to="/login" className="text-ink-2 hover:text-ink-0">Iniciar sesión</Link>
      </CabeceraPublica>

      <main className="max-w-3xl mx-auto px-6 py-12 md:py-16">
        <section className="mb-12">
          <p className="text-[12.5px] text-data-violet mb-3 font-medium">Blog de Rendi</p>
          <h1 className="text-3xl md:text-4xl font-semibold tracking-tight mb-4 text-ink-0">
            Aprende a invertir mejor desde Argentina
          </h1>
          <p className="text-base text-ink-2 leading-relaxed max-w-2xl">
            Artículos sobre FIFO en CEDEARs, P&L real en dólares, cripto e impuestos (ARCA),
            comparativas de brokers. Para inversores argentinos que quieren entender
            qué pasa con su plata.
          </p>
        </section>

        <section>
          <ul className="space-y-4">
            {POSTS.map((p) => (
              <li key={p.slug}>
                <Link
                  to={`/blog/${p.slug}`}
                  className="block border border-line/60 hover:border-line-3 hover:bg-bg-1/40 rounded-lg p-6 transition-colors group"
                >
                  <div className="flex items-center gap-3 text-xs text-ink-3 mb-3 font-medium">
                    <span className="text-data-violet">{p.category}</span>
                    <span>·</span>
                    <span className="inline-flex items-center gap-1">
                      <Calendar size={11} strokeWidth={1.75} />
                      {(() => { try { const d = new Date(p.publishedAt + 'T00:00:00'); return d.toLocaleDateString('es-AR', { day: 'numeric', month: 'short', year: 'numeric' }) } catch { return p.publishedAt } })()}
                    </span>
                    <span>·</span>
                    <span>{p.readTime}</span>
                  </div>
                  <h2 className="text-xl font-semibold text-ink-0 mb-2 group-hover:text-data-violet transition-colors">
                    {p.title}
                  </h2>
                  <p className="text-sm text-ink-2 leading-relaxed mb-3">
                    {p.description}
                  </p>
                  <div className="inline-flex items-center gap-1.5 text-xs text-data-violet font-medium">
                    Leer artículo
                    <ArrowRight size={12} strokeWidth={1.75} className="group-hover:translate-x-0.5 transition-transform" />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </main>

      <footer className="border-t border-line mt-16">
        <div className="max-w-3xl mx-auto px-6 py-6 flex items-center justify-between text-xs text-ink-3">
          <Link to="/" className="hover:text-ink-1">← Volver al inicio</Link>
          <div className="flex items-center gap-4">
            <Link to="/planes" className="hover:text-ink-1">Planes</Link>
            <Link to="/terminos" className="hover:text-ink-1">Términos</Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
