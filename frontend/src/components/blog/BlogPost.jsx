// BlogPost — layout reusable para artículos del blog.
// ════════════════════════════════════════════════════════════════════════════
// Cada post .jsx en pages/blog/articles/ usa este wrapper para mantener
// estructura consistente: header con fecha + categoría, content, CTA final,
// posts relacionados.
//
// SEO:
//   - PageMeta con title/description únicos
//   - JSON-LD Article schema (mejora rich snippets en Google)
//   - Canonical URL específica del post
//   - Open Graph article tags

import { Link } from 'react-router-dom'
import { ArrowLeft, Calendar, Sparkles } from 'lucide-react'
import { Helmet } from 'react-helmet-async'
import RendiLogo from '../RendiLogo'
import PageMeta from '../PageMeta'

const BASE_URL = 'https://rendi.finance'

export default function BlogPost({
  slug,           // 'fifo-cedears-argentina'
  title,          // "Cómo funciona el FIFO en CEDEARs (criterio fiscal AR)"
  description,    // meta description
  publishedAt,    // 'YYYY-MM-DD'
  category,       // 'FIFO y AFIP', 'Coaching IA', 'Análisis técnico', etc.
  readTime,       // '7 min'
  children,       // contenido del artículo
  related,        // [{ to, label, desc }] otros posts del blog
}) {
  const canonicalPath = `/blog/${slug}`
  const canonicalUrl = `${BASE_URL}${canonicalPath}`

  // JSON-LD Article — mejora SEO + habilita rich snippets (fecha,
  // lectura estimada, autor) en SERP de Google.
  const articleSchema = {
    '@context': 'https://schema.org',
    '@type': 'Article',
    headline: title,
    description,
    datePublished: publishedAt,
    dateModified: publishedAt,
    inLanguage: 'es-AR',
    author: { '@type': 'Organization', name: 'Rendi' },
    publisher: {
      '@type': 'Organization',
      name: 'Rendi',
      logo: { '@type': 'ImageObject', url: `${BASE_URL}/favicon.svg` },
    },
    mainEntityOfPage: { '@type': 'WebPage', '@id': canonicalUrl },
  }

  // BreadcrumbList JSON-LD — muestra "Inicio › Blog › <title>" en SERP.
  // Mejora CTR ~5-10% al dar contexto visual de jerarquía.
  const breadcrumbSchema = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    'itemListElement': [
      {
        '@type': 'ListItem',
        'position': 1,
        'name': 'Inicio',
        'item': `${BASE_URL}/`,
      },
      {
        '@type': 'ListItem',
        'position': 2,
        'name': 'Blog',
        'item': `${BASE_URL}/blog`,
      },
      {
        '@type': 'ListItem',
        'position': 3,
        'name': title,
        'item': canonicalUrl,
      },
    ],
  }

  // Formato fecha humanizado (es-AR)
  const dateLabel = (() => {
    try {
      const d = new Date(publishedAt + 'T00:00:00')
      return d.toLocaleDateString('es-AR', { day: 'numeric', month: 'long', year: 'numeric' })
    } catch { return publishedAt }
  })()

  return (
    <div className="min-h-screen bg-bg-0 text-ink-0">
      <PageMeta
        title={`${title} — Blog de Rendi`}
        description={description}
        canonical={canonicalPath}
        ogType="article"
      />
      <Helmet>
        <script type="application/ld+json">{JSON.stringify(articleSchema)}</script>
        <script type="application/ld+json">{JSON.stringify(breadcrumbSchema)}</script>
      </Helmet>

      {/* Header minimal */}
      <header className="border-b border-line">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 hover:opacity-90">
            <RendiLogo size={28} />
            <span className="font-semibold text-base tracking-tight">rendi</span>
          </Link>
          <nav className="flex items-center gap-5 text-sm">
            <Link to="/blog" className="text-ink-2 hover:text-ink-0">Blog</Link>
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
        <Link to="/blog" className="inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink-1 mb-6">
          <ArrowLeft size={14} strokeWidth={1.75} />
          Volver al blog
        </Link>

        {/* Hero del post */}
        <header className="mb-10 pb-8 border-b border-line/40">
          <div className="flex items-center gap-3 text-xs text-ink-3 font-mono uppercase tracking-caps mb-4">
            <span className="text-data-violet">{category}</span>
            <span>·</span>
            <span className="inline-flex items-center gap-1">
              <Calendar size={11} strokeWidth={1.75} />
              {dateLabel}
            </span>
            <span>·</span>
            <span>{readTime}</span>
          </div>
          <h1 className="text-3xl md:text-4xl font-semibold tracking-tight leading-[1.15] text-ink-0">
            {title}
          </h1>
          <p className="text-base md:text-lg text-ink-2 mt-4 leading-relaxed">
            {description}
          </p>
        </header>

        {/* Content — el contenido va via children. Aplica prose-like styling
            para que h2, h3, p, ul, etc. queden bien sin que cada post tenga
            que tipear las clases. */}
        <div className="blog-prose text-ink-1">
          {children}
        </div>

        {/* CTA al final del post */}
        <section className="mt-16 border border-data-violet/30 bg-data-violet/[0.04] rounded-lg p-6 text-center">
          <h2 className="text-xl font-semibold text-ink-0 mb-2">Probá Rendi gratis</h2>
          <p className="text-sm text-ink-2 mb-5 max-w-md mx-auto">
            El tracker multi-broker para Argentina con Coach IA. Sin tarjeta.
          </p>
          <Link
            to="/login?mode=register"
            className="inline-flex items-center gap-2 bg-data-violet hover:bg-data-violet/90 text-white font-medium rounded-sm px-5 py-2.5 transition-colors"
          >
            <Sparkles size={14} strokeWidth={2} />
            Crear cuenta gratis
          </Link>
        </section>

        {/* Posts relacionados */}
        {related && related.length > 0 && (
          <section className="mt-12 pt-8 border-t border-line/40">
            <h2 className="text-sm font-mono uppercase tracking-caps text-ink-3 mb-4">
              Seguí leyendo
            </h2>
            <ul className="space-y-3">
              {related.map((r, i) => (
                <li key={i}>
                  <Link to={r.to} className="block border border-line/60 hover:border-line-3 rounded-sm px-4 py-3 transition-colors">
                    <h3 className="text-base font-medium text-ink-0 mb-1">{r.label}</h3>
                    <p className="text-xs text-ink-3 leading-relaxed">{r.desc}</p>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
      </article>

      <footer className="border-t border-line mt-16">
        <div className="max-w-3xl mx-auto px-6 py-6 flex items-center justify-between text-xs text-ink-3">
          <Link to="/" className="hover:text-ink-1">← Inicio</Link>
          <div className="flex items-center gap-4">
            <Link to="/blog" className="hover:text-ink-1">Blog</Link>
            <Link to="/planes" className="hover:text-ink-1">Planes</Link>
            <Link to="/terminos" className="hover:text-ink-1">Términos</Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
