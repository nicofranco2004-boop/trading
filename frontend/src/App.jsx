import { useEffect, useRef, lazy, Suspense } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { ThemeProvider } from './contexts/ThemeContext'
import { CurrencyProvider } from './contexts/CurrencyContext'
import { PrivacyProvider } from './contexts/PrivacyContext'
import { CoachDrawerProvider } from './contexts/CoachDrawerContext'
import Sidebar from './components/Sidebar'
import { PageSkeleton } from './components/Skeleton'
import MobileTabBar from './components/mobile/MobileTabBar'
import MobileTopBar from './components/mobile/MobileTopBar'
import DemoBanner from './components/DemoBanner'
import SupportWhatsAppFab from './components/SupportWhatsAppFab'
import AICoachDrawer from './components/ai/AICoachDrawer'
import { useIsMobile } from './hooks/useIsMobile'
import { trackRoute } from './utils/track'
import { trackPageView } from './utils/analytics'
import { trackMetaPageView } from './utils/metaPixel'

// ─── Eager imports: páginas del flujo no-autenticado ──────────────────────────
// Estas son las primeras que ve un user sin login (Landing → Login →
// VerifyEmail/ResetPassword). Mantenerlas eager elimina un lazy load del
// path crítico de adquisición.
import Login from './pages/Login'
import Landing from './pages/Landing'
import VerifyEmail from './pages/VerifyEmail'
import ResetPassword from './pages/ResetPassword'

// ─── Lazy imports: páginas del flujo autenticado ──────────────────────────────
// Cada página queda en su propio chunk JS, descargado on-demand al navegar.
// Beneficio: bundle main pasa de ~600KB → ~150KB gzip (Insights 2869L,
// Positions 2481L, Reports, Wrapped, Recharts ~150KB ya no entran al main).
// TTI inicial mejora ~1.5-2.5s en mobile 4G.
const Home = lazy(() => import('./pages/Home'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Positions = lazy(() => import('./pages/Positions'))
const Monthly = lazy(() => import('./pages/Monthly'))
const Operations = lazy(() => import('./pages/Operations'))
const Config = lazy(() => import('./pages/Config'))
const Insights = lazy(() => import('./pages/Insights'))
const Admin = lazy(() => import('./pages/Admin'))
const Goals = lazy(() => import('./pages/Goals'))
const PerfilInversor = lazy(() => import('./pages/PerfilInversor'))
const Imports = lazy(() => import('./pages/Imports'))
const Reports = lazy(() => import('./pages/Reports'))
const Novedades = lazy(() => import('./pages/Novedades'))
const FirstInsight = lazy(() => import('./pages/FirstInsight'))
const Behavioral = lazy(() => import('./pages/Behavioral'))
const Wrapped = lazy(() => import('./pages/Wrapped'))
// Restructure 2026-05-27: páginas wrapper que consolidan secciones del nav.
// Analisis = Insights + Comportamiento + Reportes en 4 tabs.
// Cartera = Posiciones + Dashboard + Objetivos en 4 tabs.
// Las páginas internas siguen existiendo como rutas (alias) — ver redirects.
const Analisis = lazy(() => import('./pages/Analisis'))
const Fundamentals = lazy(() => import('./pages/Fundamentals'))
const AssetDetail = lazy(() => import('./pages/AssetDetail'))
const Cartera = lazy(() => import('./pages/Cartera'))
const More = lazy(() => import('./pages/More'))
const Planes = lazy(() => import('./pages/Planes'))
// BillingReturn exporta 3 componentes — Vite los dedupea en un solo chunk
// porque comparten el import path. El user solo entra a UNO de los 3 según
// el resultado de Mercado Pago, pero los 3 quedan en el mismo bundle.
const BillingSuccess = lazy(() => import('./pages/BillingReturn').then(m => ({ default: m.BillingSuccess })))
const BillingPending = lazy(() => import('./pages/BillingReturn').then(m => ({ default: m.BillingPending })))
const BillingFailure = lazy(() => import('./pages/BillingReturn').then(m => ({ default: m.BillingFailure })))
const MobileSearch = lazy(() => import('./pages/MobileSearch'))
const PositionDetailMobile = lazy(() => import('./pages/PositionDetailMobile'))
// Páginas legales — accesibles SIN login (compliance: el user puede leer
// los T&C antes de pagar / sin tener una cuenta). Lazy igual porque la
// mayoría de los visitantes no las necesitan ver.
const Terminos = lazy(() => import('./pages/Terminos'))
const Reembolso = lazy(() => import('./pages/Reembolso'))
const Privacidad = lazy(() => import('./pages/Privacidad'))

// SEO landings — páginas keyword-específicas que rankean long-tail
// (cocos, iol, binance, cedears, bonos AR, AFIP cripto). Accesibles
// sin login. Lazy porque solo se cargan cuando alguien viene de Google.
const LandingCocos = lazy(() => import('./pages/keywords/Cocos'))
const LandingIOL = lazy(() => import('./pages/keywords/IOL'))
const LandingBinance = lazy(() => import('./pages/keywords/Binance'))
const LandingCedears = lazy(() => import('./pages/keywords/Cedears'))
const LandingBonosAR = lazy(() => import('./pages/keywords/BonosAR'))
const LandingAfipCripto = lazy(() => import('./pages/keywords/AfipCripto'))

// Blog — accesible sin login. Cada artículo es un componente JSX por
// simplicidad (no markdown). Para agregar uno: crear el archivo + entry
// en pages/Blog.jsx POSTS + ruta acá + sitemap.
const Blog = lazy(() => import('./pages/Blog'))
const BlogFifoCedears = lazy(() => import('./pages/blog/articles/FifoCedearsArgentina'))
const BlogPnlRealUsdBlue = lazy(() => import('./pages/blog/articles/PnlRealUsdBlue'))
const BlogComparativaBrokers = lazy(() => import('./pages/blog/articles/ComparativaBrokersArgentina'))

// Onboarding wizard — flow guiado de primer uso post-signup.
// Auto-trigger desde VerifyEmail.jsx si el user no tiene brokers.
// Skip flag en localStorage para users que prefieran explorar solos.
const Onboarding = lazy(() => import('./pages/Onboarding'))

// Guía / Manual completo — accesible sin login. Index + 6 sub-secciones.
// Linkeado desde la Landing (botón "Ver guía completa" en HowItWorks) y
// desde el Sidebar (footer) para usuarios logueados. SEO friendly: cada
// sub-página tiene su propio canonical + metadescription.
const Guia = lazy(() => import('./pages/Guia'))
const GuiaEmpezar = lazy(() => import('./pages/guia/Empezar'))
const GuiaCarteraYOperaciones = lazy(() => import('./pages/guia/CarteraYOperaciones'))
const GuiaInsightsYReportes = lazy(() => import('./pages/guia/InsightsYReportes'))
const GuiaCoachIA = lazy(() => import('./pages/guia/CoachIA'))
const GuiaNovedades = lazy(() => import('./pages/guia/Novedades'))
const GuiaCuentaYPlanes = lazy(() => import('./pages/guia/CuentaYPlanes'))

// Fallback mínimo mientras carga el chunk. El shell (Sidebar / MobileTopBar)
// queda montado, así que la nav no parpadea — solo el content area se reemplaza.
function PageFallback() {
  return <PageSkeleton />
}

function RouteTracker() {
  // Trackea cambios de ruta automáticamente. Vive adentro del <BrowserRouter>
  // implícito de App.jsx (asume que react-router-dom está montado por encima).
  // Manda el route change a 2 destinos:
  //   - trackRoute(): nuestro backend telemetry interno (api.post /track)
  //   - trackPageView(): Google Analytics 4 (page_view event)
  const location = useLocation()
  const prev = useRef(location.pathname)
  // Page view inicial — el primer render no dispara el useEffect con prev≠new,
  // así que lo trackeamos explícito.
  useEffect(() => {
    trackPageView(location.pathname)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    if (prev.current !== location.pathname) {
      trackRoute(prev.current, location.pathname)
      trackPageView(location.pathname)
      trackMetaPageView()  // Meta Pixel — PageView en navegación SPA (retargeting)
      prev.current = location.pathname
    }
  }, [location.pathname])
  return null
}

function AppRoutes() {
  // Las rutas son las mismas en desktop y mobile — el layout cambia, el
  // árbol de rutas no. Algunas páginas detectan useIsMobile() internamente
  // para variar el render.
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      {/* Restructure 2026-05-27: rutas wrapper consolidadas. Las URLs viejas
          (/dashboard, /insights, etc.) mantienen redirects para no romper
          bookmarks ni links externos. */}
      <Route path="/posiciones" element={<Cartera />} />
      <Route path="/analisis" element={<Analisis />} />
      <Route path="/fundamentals" element={<Fundamentals />} />
      <Route path="/activo/:ticker" element={<AssetDetail />} />
      {/* Redirects de rutas viejas al wrapper consolidado, preservando query */}
      <Route path="/dashboard"       element={<Navigate to="/posiciones?tab=evolucion"   replace />} />
      <Route path="/objetivos"       element={<Navigate to="/posiciones?tab=objetivos"   replace />} />
      <Route path="/insights"        element={<Navigate to="/analisis?tab=diagnostico"   replace />} />
      <Route path="/comportamiento"  element={<Navigate to="/analisis?tab=comportamiento" replace />} />
      <Route path="/reportes"        element={<Navigate to="/analisis?tab=reportes"      replace />} />
      <Route path="/mensual" element={<Monthly />} />
      <Route path="/novedades" element={<Novedades />} />
      {/* Redirects back-compat */}
      <Route path="/eventos"  element={<Navigate to="/novedades?tab=eventos"  replace />} />
      <Route path="/noticias" element={<Navigate to="/novedades?tab=noticias" replace />} />
      <Route path="/operaciones" element={<Operations />} />
      <Route path="/config" element={<Config />} />
      {/* /perfil-inversor ahora es tab dentro de Análisis. PerfilInversor sigue
          como componente embebido en Analisis.jsx — el URL viejo redirige al
          tab para que bookmarks externos no se rompan. */}
      <Route path="/perfil-inversor" element={<Navigate to="/analisis?tab=perfil" replace />} />
      {/* /objetivos sigue siendo redirect a /posiciones?tab=objetivos arriba */}
      <Route path="/wrapped" element={<Wrapped />} />
      <Route path="/imports" element={<Imports />} />
      <Route path="/bienvenida" element={<FirstInsight />} />
      <Route path="/onboarding" element={<Onboarding />} />
      <Route path="/admin" element={<Admin />} />
      <Route path="/planes" element={<Planes />} />
      {/* Páginas legales — duplicadas en flow no-auth abajo para que sean
          accesibles sin login (linkeadas desde Planes.jsx antes del CTA de pago). */}
      <Route path="/terminos" element={<Terminos />} />
      <Route path="/reembolso" element={<Reembolso />} />
      <Route path="/privacidad" element={<Privacidad />} />
      {/* SEO landings + blog — también duplicadas abajo para flow no-auth */}
      <Route path="/brokers/cocos" element={<LandingCocos />} />
      <Route path="/brokers/iol" element={<LandingIOL />} />
      <Route path="/brokers/binance" element={<LandingBinance />} />
      <Route path="/cedears" element={<LandingCedears />} />
      <Route path="/bonos-argentinos" element={<LandingBonosAR />} />
      <Route path="/afip-cripto" element={<LandingAfipCripto />} />
      <Route path="/blog" element={<Blog />} />
      <Route path="/blog/fifo-cedears-argentina" element={<BlogFifoCedears />} />
      <Route path="/blog/pnl-real-usd-blue-argentina" element={<BlogPnlRealUsdBlue />} />
      <Route path="/blog/comparativa-brokers-argentina" element={<BlogComparativaBrokers />} />
      {/* Guía / manual de uso — index + 6 secciones */}
      <Route path="/guia" element={<Guia />} />
      <Route path="/guia/empezar" element={<GuiaEmpezar />} />
      <Route path="/guia/cartera-y-operaciones" element={<GuiaCarteraYOperaciones />} />
      <Route path="/guia/insights-y-reportes" element={<GuiaInsightsYReportes />} />
      <Route path="/guia/coach-ia" element={<GuiaCoachIA />} />
      <Route path="/guia/novedades" element={<GuiaNovedades />} />
      <Route path="/guia/cuenta-y-planes" element={<GuiaCuentaYPlanes />} />
      <Route path="/billing/success" element={<BillingSuccess />} />
      <Route path="/billing/pending" element={<BillingPending />} />
      <Route path="/billing/failure" element={<BillingFailure />} />
      {/* Mobile-only: "Más" drawer page + buscador full-screen + detail */}
      <Route path="/mas" element={<More />} />
      <Route path="/buscar" element={<MobileSearch />} />
      <Route path="/posiciones/:id" element={<PositionDetailMobile />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

function Layout() {
  const { user } = useAuth()
  const isMobile = useIsMobile()

  if (!user) {
    return (
      <Suspense fallback={<PageFallback />}>
        <Routes>
          {/* Landing pública — primer punto de contacto sin login */}
          <Route path="/" element={<Landing />} />
          {/* Rutas accesibles SIN login — el user pasa por acá tras registrarse
              o tras clickear un magic link de password reset. */}
          <Route path="/verify-email" element={<VerifyEmail />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          {/* Planes — accesible sin login (el visitante decide comprar ANTES
              de crear cuenta; el flow de subscribe en sí requiere login pero
              la página de pricing es 100% pública e indexable por Google). */}
          <Route path="/planes" element={<Planes />} />
          {/* Legal — accesibles sin login (compliance + el user puede leer
              T&C antes de crear cuenta). Lazy igual que las del flow auth. */}
          <Route path="/terminos" element={<Terminos />} />
          <Route path="/reembolso" element={<Reembolso />} />
          <Route path="/privacidad" element={<Privacidad />} />
          {/* SEO landings públicas — visitantes desde Google sin sesión.
              Cada una rankea para una keyword AR-específica. */}
          <Route path="/brokers/cocos" element={<LandingCocos />} />
          <Route path="/brokers/iol" element={<LandingIOL />} />
          <Route path="/brokers/binance" element={<LandingBinance />} />
          <Route path="/cedears" element={<LandingCedears />} />
          <Route path="/bonos-argentinos" element={<LandingBonosAR />} />
          <Route path="/afip-cripto" element={<LandingAfipCripto />} />
          {/* Blog público */}
          <Route path="/blog" element={<Blog />} />
          <Route path="/blog/fifo-cedears-argentina" element={<BlogFifoCedears />} />
          <Route path="/blog/pnl-real-usd-blue-argentina" element={<BlogPnlRealUsdBlue />} />
          <Route path="/blog/comparativa-brokers-argentina" element={<BlogComparativaBrokers />} />
          {/* Guía / manual público — index + 6 secciones, indexables */}
          <Route path="/guia" element={<Guia />} />
          <Route path="/guia/empezar" element={<GuiaEmpezar />} />
          <Route path="/guia/cartera-y-operaciones" element={<GuiaCarteraYOperaciones />} />
          <Route path="/guia/insights-y-reportes" element={<GuiaInsightsYReportes />} />
          <Route path="/guia/coach-ia" element={<GuiaCoachIA />} />
          <Route path="/guia/novedades" element={<GuiaNovedades />} />
          <Route path="/guia/cuenta-y-planes" element={<GuiaCuentaYPlanes />} />
          <Route path="*" element={<Login />} />
        </Routes>
      </Suspense>
    )
  }

  // ─── Mobile shell ──────────────────────────────────────────────────────
  // Suspense envuelve SOLO el content area — el shell (TopBar/TabBar) sigue
  // montado mientras carga el chunk de la nueva ruta. Sin parpadeo en la nav.
  if (isMobile) {
    return (
      <>
        <MobileTopBar />
        <main className="min-h-screen">
          <DemoBanner />
          <Suspense fallback={<PageFallback />}>
            <AppRoutes />
          </Suspense>
        </main>
        <MobileTabBar />
        <SupportWhatsAppFab />
      </>
    )
  }

  // ─── Desktop shell ─────────────────────────────────────────────────────
  return (
    <>
      <Sidebar />
      {/* main content shifteado dinámicamente por --sidebar-w
          (la sidebar setea esta CSS var según expandida/colapsada) */}
      <main
        className="min-h-screen transition-[margin] duration-200 ease-out"
        style={{ marginLeft: 'var(--sidebar-w, 220px)' }}
      >
        <DemoBanner />
        <Suspense fallback={<PageFallback />}>
          <AppRoutes />
        </Suspense>
      </main>
      <SupportWhatsAppFab />
    </>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <CurrencyProvider>
          <PrivacyProvider>
          <CoachDrawerProvider>
            <div className="min-h-screen bg-bg-0 text-ink-0">
              {/* RouteTracker vive ACÁ (no dentro de los shells autenticados)
                  para que GA4 + Meta también midan al visitante SIN login:
                  Landing, /login, /verify-email. Antes solo se montaba tras el
                  gate `if (!user)`, así que el embudo de adquisición (el que
                  importa para los ads) era invisible en analytics. */}
              <RouteTracker />
              <Layout />
              {/* Drawer global del Coach IA — mounted una vez al nivel de App,
                  cualquier componente lo abre via useCoachDrawer().open() */}
              <AICoachDrawer />
            </div>
          </CoachDrawerProvider>
          </PrivacyProvider>
        </CurrencyProvider>
      </AuthProvider>
    </ThemeProvider>
  )
}
