// Home — la nueva landing de Rendi (V1).
// ════════════════════════════════════════════════════════════════════════════
// Composición:
//   1. SearchBar — buscar cualquier ticker (acciones US, CEDEARs, cripto)
//   2. IndicesStrip — S&P, Nasdaq, Merval, BTC, dólar blue, oro
//   3. Heatmap S&P 500 top 50 (snapshot mid-day + cierre)
//   4. PersonalLayer — "Lo que te afecta" (holdings que se mueven, earnings próximos)
//   5. MoversRail — top 5 ↑ / top 5 ↓ del día
//   6. NewsPreview — 3 noticias destacadas + link a /novedades
//   7. EventsPreview — 5 eventos económicos próximos + link a /novedades
//
// V1.5 agrega: Watchlist + Heatmap Merval/Cripto.
// V2 agrega: real-time prices + explicación AI de movimientos.
// V3 agrega: feed social / comentarios por ticker.

import PageHeader from '../components/PageHeader'
import IndicesStrip from '../components/home/IndicesStrip'
import Heatmap from '../components/home/Heatmap'
import MoversRail from '../components/home/MoversRail'
import PersonalLayer from '../components/home/PersonalLayer'
import NewsPreview from '../components/home/NewsPreview'
import EventsPreview from '../components/home/EventsPreview'
import SearchBar from '../components/home/SearchBar'

export default function Home() {
  return (
    <div className="page-shell">
      <PageHeader
        title="Home"
        subtitle="Lo que está pasando en el mercado, con un guiño a tu portfolio."
        action={<SearchBar />}
      />

      <div className="space-y-6">
        {/* 1. Strip de índices (S&P, Nasdaq, Merval, BTC, blue, oro) */}
        <IndicesStrip />

        {/* 2. Heatmap S&P 500 — el visual hero */}
        <section>
          <h2 className="font-display text-sm uppercase tracking-wider text-ink-3 mb-2">
            S&P 500 — heatmap
          </h2>
          <Heatmap market="sp500" />
        </section>

        {/* 3. Capa personalizada — solo si el user tiene portfolio */}
        <PersonalLayer />

        {/* 4. Movers del día */}
        <section>
          <h2 className="font-display text-sm uppercase tracking-wider text-ink-3 mb-2">
            Movers del día
          </h2>
          <MoversRail market="sp500" />
        </section>

        {/* 5. Noticias + eventos — preview, deep dive en /novedades */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <NewsPreview />
          <EventsPreview />
        </div>
      </div>
    </div>
  )
}
