// Punto de entrada global a Rendi AI — desde cualquier componente (sidebar,
// checklist, ✦ botones, mobile) sin prop-drilling.
//
// Clean pass 2026-07: Rendi AI dejó de ser un drawer lateral y pasó a ser una
// PÁGINA (/ai). `open(question?)` ahora NAVEGA ahí; si viene una pregunta
// inicial queda en el contexto y la página la consume una sola vez (autoAsk).
// La API pública (useCoachDrawer().open) se mantiene para no tocar callers.

import { createContext, useContext, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { markAIDiscovered } from '../components/ai/AIDiscoveryBanner'

const CoachDrawerContext = createContext({
  open: () => {},
  close: () => {},
  toggle: () => {},
  initialQuestion: null,
  consumeInitialQuestion: () => {},
})

export function CoachDrawerProvider({ children }) {
  const navigate = useNavigate()
  // Pregunta opcional pre-cargada — la página /ai la consume una vez y AICoach
  // la auto-envía al montar. Debe estar whitelisted (main.py) o Free/Plus 403.
  const [initialQuestion, setInitialQuestion] = useState(null)

  // markAIDiscovered en cada open(): el checklist de onboarding detecta que el
  // user "ya probó" Rendi AI sin importar desde dónde entró.
  const open = (question = null) => {
    setInitialQuestion(question || null)
    markAIDiscovered()
    navigate('/ai')
  }

  const value = {
    open,
    toggle: open,                    // back-compat: toggle ≈ ir a la página
    close: () => setInitialQuestion(null),
    initialQuestion,
    consumeInitialQuestion: () => setInitialQuestion(null),
  }
  return (
    <CoachDrawerContext.Provider value={value}>
      {children}
    </CoachDrawerContext.Provider>
  )
}

export const useCoachDrawer = () => useContext(CoachDrawerContext)
