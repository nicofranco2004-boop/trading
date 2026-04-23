import { Routes, Route } from 'react-router-dom'
import Navbar from './components/Navbar'
import Dashboard from './pages/Dashboard'
import Positions from './pages/Positions'
import Monthly from './pages/Monthly'
import Operations from './pages/Operations'
import Config from './pages/Config'

export default function App() {
  return (
    <>
      <Navbar />
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/posiciones" element={<Positions />} />
        <Route path="/mensual" element={<Monthly />} />
        <Route path="/operaciones" element={<Operations />} />
        <Route path="/config" element={<Config />} />
      </Routes>
    </>
  )
}
