// PageMeta — wrapper sobre react-helmet-async para metadata por ruta.
// ════════════════════════════════════════════════════════════════════════════
// El index.html define el title/description GLOBAL (que cubre la landing /).
// Las demás páginas públicas (Planes, Términos, Reembolso) sobreescriben con
// PageMeta para que Google las indexe con metadata única — sin esto, todas las
// rutas de la SPA tienen el mismo title y Google las trata como duplicate
// content (canibalización de keywords).
//
// Uso:
//   <PageMeta
//     title="Planes y precios — Rendi"
//     description="..."
//     canonical="/planes"
//   />
//
// Notas:
//   - El title se usa como `<title>{title}</title>` directamente. Si querés el
//     formato "{X} | Rendi", incluilo en el prop (ya queda explícito).
//   - canonical se concatena a "https://rendi.finance" — pasá solo el path.
//   - noindex=true → agrega meta robots noindex,follow. Útil para /login,
//     páginas de admin, errors.
//   - ogImage opcional — si la página tiene un OG image distinto al default.

import { Helmet } from 'react-helmet-async'

const BASE_URL = 'https://rendi.finance'
const DEFAULT_OG_IMAGE = '/og-image.png'

export default function PageMeta({
  title,
  description,
  canonical,
  noindex = false,
  ogImage = DEFAULT_OG_IMAGE,
  ogType = 'website',
}) {
  const canonicalUrl = canonical ? `${BASE_URL}${canonical}` : BASE_URL
  const ogImageUrl = ogImage.startsWith('http') ? ogImage : `${BASE_URL}${ogImage}`

  return (
    <Helmet>
      {title && <title>{title}</title>}
      {description && <meta name="description" content={description} />}
      <link rel="canonical" href={canonicalUrl} />

      {/* robots: noindex,follow para páginas que NO queremos en SERP pero
          sí queremos que el crawler siga sus links (ej: /login).
          Default (sin Helmet): hereda el `index,follow` del index.html. */}
      {noindex && <meta name="robots" content="noindex,follow" />}

      {/* Open Graph — sobrescribe el global del index.html cuando el title
          o description son distintos. Si no se pasan, queda el global. */}
      {title && <meta property="og:title" content={title} />}
      {description && <meta property="og:description" content={description} />}
      <meta property="og:url" content={canonicalUrl} />
      <meta property="og:image" content={ogImageUrl} />
      <meta property="og:type" content={ogType} />

      {/* Twitter — mismo patrón */}
      {title && <meta name="twitter:title" content={title} />}
      {description && <meta name="twitter:description" content={description} />}
      <meta name="twitter:image" content={ogImageUrl} />
    </Helmet>
  )
}
