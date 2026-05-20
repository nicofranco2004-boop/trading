// Estado global del drawer del Coach IA — abre/cierra desde cualquier
// componente (sidebar, página, atajo de teclado, etc.) sin prop-drilling.
import { createContext, useContext, useState } from 'react'

const CoachDrawerContext = createContext({
  isOpen: false,
  open: () => {},
  close: () => {},
  toggle: () => {},
})

export function CoachDrawerProvider({ children }) {
  const [isOpen, setIsOpen] = useState(false)
  const value = {
    isOpen,
    open: () => setIsOpen(true),
    close: () => setIsOpen(false),
    toggle: () => setIsOpen(o => !o),
  }
  return (
    <CoachDrawerContext.Provider value={value}>
      {children}
    </CoachDrawerContext.Provider>
  )
}

export const useCoachDrawer = () => useContext(CoachDrawerContext)
