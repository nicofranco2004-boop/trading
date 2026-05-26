// Home — landing principal de Rendi (V2).
// ════════════════════════════════════════════════════════════════════════════
// Composición v2 (más densa, menos editorial):
//   1. Header compacto + SearchBar
//   2. IndicesStrip (6 índices en grid horizontal)
//   3. Heatmap (S&P / Merval / Cripto)
//   4. PersonalLayer (si hay holdings)
//   5. MoversRail (top gainers + losers)
//   6. Watchlist
//   7. News + Events (grid 2 col)

import IndicesStrip from '../components/home/IndicesStrip'
import Heatmap from '../components/home/Heatmap'
import MoversRail from '../components/home/MoversRail'
import PersonalLayer from '../components/home/PersonalLayer'
import NewsPreview from '../components/home/NewsPreview'
import EventsPreview from '../components/home/EventsPreview'
import SearchBar from '../components/home/SearchBar'
import Watchlist from '../components/home/Watchlist'
import OnboardingChecklist from '../components/home/OnboardingChecklist'
import Eyebrow from '../components/Eyebrow'
import HomeMobile from './HomeMobile'
import { useIsMobile } from '../hooks/useIsMobile'
import AnalyzeButton from '../components/ai/AnalyzeButton'
import AskAIAbout from '../components/ai/AskAIAbout'

export default function Home() {
  const isMobile = useIsMobile()
  if (isMobile) return <HomeMobile />

  return (
    <div className="page-shell">
      {/* Header compacto — sin el PageHeader editorial gigante */}
      <header className="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <div>
          <Eyebrow>Inicio</Eyebrow>
          <h1 className="display-heading mt-1">El mercado hoy</h1>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <AnalyzeButton screen="home" subtitle="El mercado y tu portfolio hoy" />
          <SearchBar />
        </div>
      </header>

      <div className="space-y-6">
        {/* 0. Onboarding checklist — solo visible si el user no completó
            todos los items (broker, posición, perfil, IA). Se silencia
            automáticamente cuando está todo done o el user lo cierra. */}
        <OnboardingChecklist />

        {/* 1. Strip de índices */}
        <IndicesStrip />

        {/* 2. Heatmap — visual hero */}
        <section>
          <Heatmap defaultMarket="sp500" />
        </section>

        {/* 3. Lo que te afecta — condicional */}
        <PersonalLayer />

        {/* 4. Movers del día */}
        <section>
          <Eyebrow>Movers del día</Eyebrow>
          <div className="mt-2">
            <MoversRail market="sp500" />
          </div>
        </section>

        {/* 5. Watchlist */}
        <Watchlist />

        {/* 6. Noticias + eventos — cada uno con su ✦ */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <AskAIAbout topic="news" subtitle="Tus noticias del período">
            <NewsPreview />
          </AskAIAbout>
          <AskAIAbout topic="events" subtitle="Tus eventos próximos">
            <EventsPreview />
          </AskAIAbout>
        </div>
      </div>
    </div>
  )
}
