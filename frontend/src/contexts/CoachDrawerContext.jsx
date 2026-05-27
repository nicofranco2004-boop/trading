// Estado global del drawer del Coach IA — abre/cierra desde cualquier
// componente (sidebar, página, atajo de teclado, etc.) sin prop-drilling.
import { createContext, useContext, useState } from 'react'
import { markAIDiscovered } from '../components/ai/AIDiscoveryBanner'

const CoachDrawerContext = createContext({
  isOpen: false,
  open: () => {},
  close: () => {},
  toggle: () => {},
})

export function CoachDrawerProvider({ children }) {
  const [isOpen, setIsOpen] = useState(false)

  // Marcar la feature como descubierta cada vez que el user abre el coach.
  // Bug fix 2026-05-26: antes markAIDiscovered() SOLO se llamaba al cerrar el
  // AIDiscoveryBanner. Si el user abría el coach desde el checklist (o desde
  // el sidebar, AnalyzeButton, etc.) sin haber cerrado nunca el banner, el
  // checklist nunca detectaba que "ya probó el coach" y el item quedaba
  // pendiente eternamente. Fix: marcar como discovered en cada open() — es
  // la semántica correcta del flag ("descubrió la feature").
  const open = () => {
    setIsOpen(true)
    markAIDiscovered()
  }
  const toggle = () => setIsOpen(o => {
    if (!o) markAIDiscovered()  // solo marcar al abrir, no al cerrar
    return !o
  })

  const value = {
    isOpen,
    open,
    close: () => setIsOpen(false),
    toggle,
  }
  return (
    <CoachDrawerContext.Provider value={value}>
      {children}
    </CoachDrawerContext.Provider>
  )
}

export const useCoachDrawer = () => useContext(CoachDrawerContext)
