// KeywordLanding — template reusable para landings keyword-específicas.
// ════════════════════════════════════════════════════════════════════════════
// Sirve para crear páginas focused en una keyword/intent específico
// (ej: "tracker Cocos", "tracker IOL", "FIFO CEDEARs") que rankean
// long-tail en Google AR. Estructura SEO-optimized:
//
//   • <PageMeta> con title/description únicos por landing
//   • H1 keyword-rich
//   • Bloque "Lo que te da Rendi" (lista bullet) — keywords AR
//   • Bloque "Cómo funciona" — pasos (refuerza el HowTo schema)
//   • CTA prominente a /login?mode=register
//   • Footer con links a otras landings + planes (internal linking)
//
// Cada landing nueva = un archivo .jsx en pages/keywords/ que usa este
// componente. El contenido (kicker, h1, intro, etc.) viene por props.
//
// Pattern de uso:
//   <KeywordLanding
//     kicker="Tracker para Cocos Capital"
//     h1="Seguí tu cartera de Cocos en USD real, con FIFO automático"
//     intro="Cargá tu CSV de Cocos Capital o agregá manualmente..."
//     features={[...]}
//     howSteps={[...]}
//     relatedLinks={[...]}
//     metaTitle="..."
//     metaDescription="..."
//     canonicalPath="/brokers/cocos"
//   />

import { Link } from 'react-router-dom'
import { ArrowRight, Check, Sparkles } from 'lucide-react'
import RendiLogo from '../RendiLogo'
import PageMeta from '../PageMeta'

export default function KeywordLanding({
  kicker,
  h1,
  intro,
  features,        // [{title, desc}]
  howSteps,        // [{n, title, desc}]
  relatedLinks,    // [{to, label}]
  metaTitle,
  metaDescription,
  canonicalPath,
}) {
  return (
    <div className="min-h-screen bg-bg-0 text-ink-0 overflow-x-hidden">
      <PageMeta
        title={metaTitle}
        description={metaDescription}
        canonical={canonicalPath}
      />

      {/* Header simple — logo + nav a planes/login */}
      <header className="border-b border-line">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 hover:opacity-90">
            <RendiLogo size={28} />
            <span className="font-semibold text-base tracking-tight">rendi</span>
          </Link>
          <nav className="flex items-center gap-5 text-sm">
            <Link to="/planes" className="text-ink-2 hover:text-ink-0 transition-colors">Planes</Link>
            <Link to="/login" className="text-ink-2 hover:text-ink-0 transition-colors">Iniciar sesión</Link>
            <Link
              to="/login?mode=register"
              className="inline-flex items-center gap-1.5 bg-data-violet hover:bg-data-violet/90 text-white rounded-sm px-3 py-1.5 transition-colors text-xs font-medium"
            >
              <Sparkles size={12} strokeWidth={2} />
              Empezar gratis
            </Link>
          </nav>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-16 md:py-24">
        {/* Hero — kicker + H1 + intro + CTAs */}
        <section className="mb-16">
          <p className="font-mono text-[11px] uppercase tracking-caps text-data-violet mb-4">
            {kicker}
          </p>
          <h1 className="text-4xl md:text-5xl font-semibold tracking-tight leading-[1.1] mb-6 text-ink-0">
            {h1}
          </h1>
          <p className="text-base md:text-lg text-ink-2 leading-relaxed mb-8 max-w-2xl">
            {intro}
          </p>
          <div className="flex items-center gap-3 flex-wrap">
            <Link
              to="/login?mode=register"
              className="group inline-flex items-center gap-2 bg-data-violet hover:bg-data-violet/90 text-white font-medium rounded-sm px-5 py-2.5 transition-all"
            >
              <Sparkles size={14} strokeWidth={2} />
              Crear cuenta gratis
              <ArrowRight size={14} strokeWidth={2} className="group-hover:translate-x-0.5 transition-transform" />
            </Link>
            <Link
              to="/planes"
              className="inline-flex items-center gap-2 border border-line-3 hover:border-ink-2 hover:bg-bg-2/50 text-ink-0 font-medium rounded-sm px-5 py-2.5 transition-colors"
            >
              Ver planes y precios
            </Link>
          </div>
        </section>

        {/* Features — bullet list con check verde */}
        {features && features.length > 0 && (
          <section className="mb-16">
            <h2 className="text-2xl md:text-3xl font-semibold tracking-tight mb-8 text-ink-0">
              Lo que te da Rendi
            </h2>
            <ul className="space-y-4">
              {features.map((f, i) => (
                <li key={i} className="flex items-start gap-3">
                  <Check
                    size={18}
                    strokeWidth={2}
                    className="text-rendi-pos flex-shrink-0 mt-0.5"
                  />
                  <div>
                    <h3 className="text-base font-medium text-ink-0 mb-0.5">{f.title}</h3>
                    <p className="text-sm text-ink-2 leading-relaxed">{f.desc}</p>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* How it works — numbered steps */}
        {howSteps && howSteps.length > 0 && (
          <section className="mb-16">
            <h2 className="text-2xl md:text-3xl font-semibold tracking-tight mb-8 text-ink-0">
              Cómo funciona
            </h2>
            <ol className="space-y-6">
              {howSteps.map((s) => (
                <li key={s.n} className="flex items-start gap-4">
                  <span className="font-mono text-[12px] flex-shrink-0 w-7 h-7 inline-flex items-center justify-center rounded-full bg-data-violet/15 text-data-violet font-semibold">
                    {s.n}
                  </span>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-base font-medium text-ink-0 mb-1">{s.title}</h3>
                    <p className="text-sm text-ink-2 leading-relaxed">{s.desc}</p>
                  </div>
                </li>
              ))}
            </ol>
          </section>
        )}

        {/* CTA final */}
        <section className="mb-16 border border-data-violet/30 bg-data-violet/[0.04] rounded-lg p-6 text-center">
          <h2 className="text-xl md:text-2xl font-semibold mb-2 text-ink-0">
            Probalo gratis ahora
          </h2>
          <p className="text-sm text-ink-2 mb-5 max-w-md mx-auto">
            Sin tarjeta, sin compromiso. Cargá tu primera operación en 2 minutos.
          </p>
          <Link
            to="/login?mode=register"
            className="inline-flex items-center gap-2 bg-data-violet hover:bg-data-violet/90 text-white font-medium rounded-sm px-5 py-2.5 transition-colors"
          >
            <Sparkles size={14} strokeWidth={2} />
            Crear cuenta gratis
            <ArrowRight size={14} strokeWidth={2} />
          </Link>
        </section>

        {/* Internal links — relacionados (SEO: distribuir authority entre landings) */}
        {relatedLinks && relatedLinks.length > 0 && (
          <section className="border-t border-line/40 pt-8">
            <h2 className="text-sm font-mono uppercase tracking-caps text-ink-3 mb-4">
              También te puede interesar
            </h2>
            <ul className="flex flex-wrap gap-3">
              {relatedLinks.map((r, i) => (
                <li key={i}>
                  <Link
                    to={r.to}
                    className="inline-flex items-center gap-1.5 text-sm text-ink-1 hover:text-ink-0 border border-line/60 hover:border-line-3 rounded-sm px-3 py-1.5 transition-colors"
                  >
                    {r.label}
                    <ArrowRight size={12} strokeWidth={1.75} className="text-ink-3" />
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
      </main>

      {/* Footer minimal — mismo patrón que Términos/Reembolso */}
      <footer className="border-t border-line">
        <div className="max-w-5xl mx-auto px-6 py-6 flex items-center justify-between text-xs text-ink-3">
          <Link to="/" className="hover:text-ink-1">← Volver al inicio</Link>
          <div className="flex items-center gap-4">
            <Link to="/terminos" className="hover:text-ink-1">Términos</Link>
            <Link to="/reembolso" className="hover:text-ink-1">Reembolso</Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
