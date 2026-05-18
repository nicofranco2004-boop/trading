import { useEffect, useRef } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { ThemeProvider } from './contexts/ThemeContext'
import Sidebar from './components/Sidebar'
import MobileTabBar from './components/mobile/MobileTabBar'
import MobileTopBar from './components/mobile/MobileTopBar'
import DemoBanner from './components/DemoBanner'
import { useIsMobile } from './hooks/useIsMobile'
import { trackRoute } from './utils/track'
import Login from './pages/Login'
import VerifyEmail from './pages/VerifyEmail'
import Dashboard from './pages/Dashboard'
import Positions from './pages/Positions'
import Monthly from './pages/Monthly'
import Operations from './pages/Operations'
import Config from './pages/Config'
import Insights from './pages/Insights'
import Admin from './pages/Admin'
import Goals from './pages/Goals'
import Imports from './pages/Imports'
import Reports from './pages/Reports'
import Novedades from './pages/Novedades'
import Home from './pages/Home'
import FirstInsight from './pages/FirstInsight'
import Behavioral from './pages/Behavioral'
import Wrapped from './pages/Wrapped'
import More from './pages/More'
import Planes from './pages/Planes'
import { BillingSuccess, BillingPending, BillingFailure } from './pages/BillingReturn'
import MobileSearch from './pages/MobileSearch'
import PositionDetailMobile from './pages/PositionDetailMobile'

function RouteTracker() {
  // Trackea cambios de ruta automáticamente. Vive adentro del <BrowserRouter>
  // implícito de App.jsx (asume que react-router-dom está montado por encima).
  const location = useLocation()
  const prev = useRef(location.pathname)
  useEffect(() => {
    if (prev.current !== location.pathname) {
      trackRoute(prev.current, location.pathname)
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
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/posiciones" element={<Positions />} />
      <Route path="/insights" element={<Insights />} />
      <Route path="/comportamiento" element={<Behavioral />} />
      <Route path="/mensual" element={<Monthly />} />
      <Route path="/reportes" element={<Reports />} />
      <Route path="/novedades" element={<Novedades />} />
      {/* Redirects back-compat */}
      <Route path="/eventos"  element={<Navigate to="/novedades?tab=eventos"  replace />} />
      <Route path="/noticias" element={<Navigate to="/novedades?tab=noticias" replace />} />
      <Route path="/operaciones" element={<Operations />} />
      <Route path="/config" element={<Config />} />
      <Route path="/objetivos" element={<Goals />} />
      <Route path="/wrapped" element={<Wrapped />} />
      <Route path="/imports" element={<Imports />} />
      <Route path="/bienvenida" element={<FirstInsight />} />
      <Route path="/admin" element={<Admin />} />
      <Route path="/planes" element={<Planes />} />
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
      <Routes>
        {/* /verify-email es accesible sin login — el user pasa por acá tras
            registrarse, antes de tener token. */}
        <Route path="/verify-email" element={<VerifyEmail />} />
        <Route path="*" element={<Login />} />
      </Routes>
    )
  }

  // ─── Mobile shell ──────────────────────────────────────────────────────
  if (isMobile) {
    return (
      <>
        <RouteTracker />
        <MobileTopBar />
        <main className="min-h-screen">
          <DemoBanner />
          <AppRoutes />
        </main>
        <MobileTabBar />
      </>
    )
  }

  // ─── Desktop shell ─────────────────────────────────────────────────────
  return (
    <>
      <RouteTracker />
      <Sidebar />
      {/* main content shifteado dinámicamente por --sidebar-w
          (la sidebar setea esta CSS var según expandida/colapsada) */}
      <main
        className="min-h-screen transition-[margin] duration-200 ease-out"
        style={{ marginLeft: 'var(--sidebar-w, 220px)' }}
      >
        <DemoBanner />
        <AppRoutes />
      </main>
    </>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <div className="min-h-screen bg-bg-0 text-ink-0">
          <Layout />
        </div>
      </AuthProvider>
    </ThemeProvider>
  )
}
