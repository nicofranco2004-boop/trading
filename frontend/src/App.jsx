import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { ThemeProvider } from './contexts/ThemeContext'
import Sidebar from './components/Sidebar'
import Login from './pages/Login'
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

function Layout() {
  const { user } = useAuth()

  if (!user) {
    return (
      <Routes>
        <Route path="*" element={<Login />} />
      </Routes>
    )
  }

  return (
    <>
      <Sidebar />
      {/* main content shifteado dinámicamente por --sidebar-w
          (la sidebar setea esta CSS var según expandida/colapsada) */}
      <main
        className="min-h-screen transition-[margin] duration-200 ease-out"
        style={{ marginLeft: 'var(--sidebar-w, 220px)' }}
      >
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/posiciones" element={<Positions />} />
          <Route path="/insights" element={<Insights />} />
          <Route path="/mensual" element={<Monthly />} />
          <Route path="/reportes" element={<Reports />} />
          <Route path="/novedades" element={<Novedades />} />
          {/* Redirects para back-compat con bookmarks/links viejos. Antes
              estas rutas montaban las páginas standalone; ahora reenvían al
              hub para mantener una sola UI consistente. */}
          <Route path="/eventos"  element={<Navigate to="/novedades?tab=eventos"  replace />} />
          <Route path="/noticias" element={<Navigate to="/novedades?tab=noticias" replace />} />
          <Route path="/operaciones" element={<Operations />} />
          <Route path="/config" element={<Config />} />
          <Route path="/objetivos" element={<Goals />} />
          <Route path="/imports" element={<Imports />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
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
