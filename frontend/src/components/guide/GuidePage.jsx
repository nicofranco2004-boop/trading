// GuidePage — layout reusable para las sub-páginas del manual /guia.
// ════════════════════════════════════════════════════════════════════════════
// Cada sub-página usa este wrapper para mantener consistencia visual y
// navegación (volver al índice + página anterior/siguiente).
//
// Diferencia vs BlogPost: no muestra fecha/categoría/readTime (eso queda
// para el blog editorial). Acá el foco es funcional: TOC visible arriba +
// link al índice + paginación al final.
//
// Estilos de tipografía: usa `.blog-prose` (definida en index.css) para
// que los h2/h3/p/ul/ol queden formateados sin tener que tipear classes.

import { Link } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Sparkles } from 'lucide-react'
import RendiLogo from '../RendiLogo'
import PageMeta from '../PageMeta'

export default function GuidePage({
  title,            // "Cartera y operaciones"
  section,          // "2 de 6"
  intro,            // descripción corta del tema
  children,         // contenido del manual (h2/p/ul/etc)
  prev,             // { to, label } — página anterior (opcional)
  next,             // { to, label } — página siguiente (opcional)
  metaTitle,
  metaDescription,
  canonicalPath,
}) {
  // BreadcrumbList JSON-LD para SERP de Google.
  // Muestra "Inicio › Guía › <title>" mejorando el CTR de los resultados.
  const breadcrumbSchema = canonicalPath ? {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    'itemListElement': [
      {
        '@type': 'ListItem',
        'position': 1,
        'name': 'Inicio',
        'item': 'https://rendi.finance/',
      },
      {
        '@type': 'ListItem',
        'position': 2,
        'name': 'Guía',
        'item': 'https://rendi.finance/guia',
      },
      {
        '@type': 'ListItem',
        'position': 3,
        'name': title,
        'item': `https://rendi.finance${canonicalPath}`,
      },
    ],
  } : null

  return (
    <div className="min-h-screen bg-bg-0 text-ink-0">
      <PageMeta
        title={metaTitle}
        description={metaDescription}
        canonical={canonicalPath}
      />
      {breadcrumbSchema && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbSchema) }}
        />
      )}

      {/* Header minimal: logo + nav a planes/login */}
      <header className="border-b border-line">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 hover:opacity-90">
            <RendiLogo size={28} />
            <span className="font-semibold text-base tracking-tight">rendi</span>
          </Link>
          <nav className="flex items-center gap-5 text-sm">
            <Link to="/guia" className="text-ink-2 hover:text-ink-0">Guía</Link>
            <Link to="/planes" className="text-ink-2 hover:text-ink-0">Planes</Link>
            <Link
              to="/login?mode=register"
              className="inline-flex items-center gap-1.5 bg-data-violet hover:bg-data-violet/90 text-white rounded-sm px-3 py-1.5 text-xs font-medium"
            >
              <Sparkles size={12} strokeWidth={2} />
              Empezar gratis
            </Link>
          </nav>
        </div>
      </header>

      <article className="max-w-3xl mx-auto px-6 py-12 md:py-16">
        <Link to="/guia" className="inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink-1 mb-6">
          <ArrowLeft size={14} strokeWidth={1.75} />
          Volver al índice
        </Link>

        {/* Hero */}
        <header className="mb-10 pb-8 border-b border-line/40">
          <p className="text-[12px] text-data-violet mb-3 font-medium">
            Guía · {section}
          </p>
          <h1 className="text-3xl md:text-4xl font-semibold tracking-tight leading-[1.15] text-ink-0">
            {title}
          </h1>
          <p className="text-base md:text-lg text-ink-2 mt-4 leading-relaxed">
            {intro}
          </p>
        </header>

        {/* Content (children) — usa .blog-prose definido en index.css */}
        <div className="blog-prose text-ink-1">
          {children}
        </div>

        {/* Paginación prev/next */}
        {(prev || next) && (
          <nav className="mt-16 pt-8 border-t border-line/40 grid grid-cols-2 gap-4">
            {prev ? (
              <Link
                to={prev.to}
                className="block border border-line/60 hover:border-line-3 rounded-sm px-4 py-3 transition-colors text-left group"
              >
                <div className="inline-flex items-center gap-1.5 text-[12.5px] text-ink-2 mb-1 font-medium">
                  <ArrowLeft size={11} strokeWidth={1.75} />
                  Anterior
                </div>
                <div className="text-sm font-medium text-ink-1 group-hover:text-ink-0">{prev.label}</div>
              </Link>
            ) : <div />}

            {next ? (
              <Link
                to={next.to}
                className="block border border-line/60 hover:border-line-3 rounded-sm px-4 py-3 transition-colors text-right group"
              >
                <div className="inline-flex items-center gap-1.5 text-[12.5px] text-ink-2 mb-1 justify-end w-full font-medium">
                  Siguiente
                  <ArrowRight size={11} strokeWidth={1.75} />
                </div>
                <div className="text-sm font-medium text-ink-1 group-hover:text-ink-0">{next.label}</div>
              </Link>
            ) : <div />}
          </nav>
        )}
      </article>

      <footer className="border-t border-line mt-16">
        <div className="max-w-3xl mx-auto px-6 py-6 flex items-center justify-between text-xs text-ink-3">
          <Link to="/" className="hover:text-ink-1">← Inicio</Link>
          <div className="flex items-center gap-4">
            <Link to="/guia" className="hover:text-ink-1">Índice</Link>
            <Link to="/planes" className="hover:text-ink-1">Planes</Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
