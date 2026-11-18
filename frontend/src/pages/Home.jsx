// Home — landing principal de Rendi (V2).
// ════════════════════════════════════════════════════════════════════════════
// Composición v2 (más densa, menos editorial):
//   1. Header compacto + SearchBar
//   2. IndicesStrip (6 índices en grid horizontal)
//   3. Termómetro del mercado (0 a 100) y, abajo, el Heatmap (S&P / Merval / Cripto)
//   4. PersonalLayer (si hay holdings)
//   5. MoversRail (top gainers + losers)
//   6. Watchlist
//   7. News + Events (grid 2 col)

import IndicesStrip from '../components/home/IndicesStrip'
import Heatmap from '../components/home/Heatmap'
import Termometro from '../components/home/Termometro'
import MoversRail from '../components/home/MoversRail'
import PersonalLayer from '../components/home/PersonalLayer'
import NewsPreview from '../components/home/NewsPreview'
import EventsPreview from '../components/home/EventsPreview'
import SearchBar from '../components/home/SearchBar'
import Watchlist from '../components/home/Watchlist'
import OnboardingChecklist from '../components/home/OnboardingChecklist'
import FueraDeHorarioMercado from '../components/home/FueraDeHorarioMercado'
import { useCurrency } from '../contexts/CurrencyContext'
import { usePrivacy } from '../contexts/PrivacyContext'
import Eyebrow from '../components/Eyebrow'
import HomeMobile from './HomeMobile'
import { useIsMobile } from '../hooks/useIsMobile'
import { useEsperaDeLaLista } from '../hooks/useEsperaDeLaLista'
import { useFueraDeHorarioDelInicio } from '../hooks/useFueraDeHorarioDelInicio'
import AnalyzeButton from '../components/ai/AnalyzeButton'
import AskAIAbout from '../components/ai/AskAIAbout'

export default function Home() {
  const isMobile = useIsMobile()
  const { currency } = useCurrency()
  const { hidden } = usePrivacy()
  // En el celular la espera es de HomeMobile (con su esqueleto): acá no corre.
  // La sección de pre/post mercado se pide desde que se abre la pantalla, y la
  // pantalla la espera junto con la lista (ver hooks/useFueraDeHorarioDelInicio).
  const fdh = useFueraDeHorarioDelInicio({ activo: !isMobile })
  const espera = useEsperaDeLaLista({ desde: !isMobile, ademas: fdh.listo })
  if (isMobile) return <HomeMobile />

  return (
    <div className="page-shell">
      {/* Header compacto — sin el PageHeader editorial gigante */}
      <header className="flex items-center justify-between mb-6 gap-4 flex-wrap">
        <div>
          <Eyebrow>Mercado</Eyebrow>
          <h1 className="display-heading mt-1">El mercado hoy</h1>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <AnalyzeButton screen="home" subtitle="El mercado y tu cartera hoy" />
          <SearchBar />
        </div>
      </header>

      {/* ⚠️ INVISIBLE HASTA QUE LA LISTA DE PRIMEROS PASOS SE DECIDE. La lista
          aparecía una vuelta de red después que el resto y empujaba todo 686 px
          hacia abajo (CLS 0,31 en 4 de 4 cargas, 16/11/2026). `invisible` y no
          `hidden`: todo queda montado y midiendo su ancho, y los pedidos de cada
          sección salen ya. Con tope: ver useEsperaDeLaLista. Y hasta que la
          sección de pre/post mercado sabe si va y con qué forma (`fdh.listo`):
          aparecía después, arriba, y cambiaba a «Tus activos» (CLS 0,35 con la
          lista cerrada, a las 18:30 del 17/11/2026). */}
      <div className={`space-y-6 ${espera.lista ? '' : 'invisible'}`} aria-busy={!espera.lista}>
        {/* 0. Onboarding checklist — solo visible si el user no completó
            todos los items (broker, posición, perfil, IA). Se silencia
            automáticamente cuando está todo done o el user lo cierra. */}
        <OnboardingChecklist onDecidida={espera.alDecidirse} aLaVista={espera.lista} />

        {/* 0.5 Pre y post mercado — sólo existe en esas franjas */}
        <FueraDeHorarioMercado cartera={fdh.cartera} datos={fdh.datos} moneda={currency} oculto={hidden} />

        {/* 1. Strip de índices */}
        <IndicesStrip />

        {/* 2. Termómetro del mercado (pieza 7) y el Heatmap — visual hero */}
        <Termometro />
        <section>
          <Heatmap defaultMarket="sp500" />
        </section>

        {/* 3. Lo que te afecta — condicional */}
        <PersonalLayer />

        {/* 4. Movers del día — el título lo pone MoversRail, al lado de su
            indicador en vivo */}
        <MoversRail market="sp500" />

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
