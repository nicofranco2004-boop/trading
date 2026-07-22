// AdvisorContext — estado React del "contexto de cliente" del Plan Asesor.
// ═══════════════════════════════════════════════════════════════════════════
// Espeja el estado módulo-level de api.js (getClientContext/setClientContext,
// que es quien inyecta el header X-Rendi-Client-Id en cada request) y agrega
// lo que React necesita: re-render del shell (barra de contexto, sidebar) y
// el refetch de plan features al entrar/salir — el tier que ve el frontend
// CAMBIA con el contexto (lente Pro sobre el cliente vs tier real del asesor).
//
// Uso:
//   const { clientCtx, enterClient, exitClient } = useAdvisorContext()
//   enterClient({ id, label })  → header activo + features refetch
//   exitClient()                → limpia + features refetch
//
// Fallback seguro: fuera del provider devuelve ctx null y no-ops (mismo
// patrón que AlertsContext) — ningún componente explota si se monta suelto.

import { createContext, useCallback, useContext, useState } from 'react'
import { getClientContext, setClientContext, clearClientContext } from '../utils/api'
import { refreshPlanFeatures } from '../hooks/usePlanFeatures'

const AdvisorContext = createContext(null)

export function AdvisorProvider({ children }) {
  // Hidrata del estado persistido (localStorage vía api.js) — el contexto
  // sobrevive reloads: si el asesor refresca mirando un cliente, sigue ahí.
  const [clientCtx, setCtx] = useState(() => getClientContext())

  const enterClient = useCallback((client) => {
    if (!client || typeof client.id !== 'number') return
    setClientContext({ id: client.id, label: client.label || '' })
    setCtx(getClientContext())
    // El tier efectivo cambió (asesor → lente Pro sobre el cliente):
    // invalidar el cache de plan features para que los gates se re-resuelvan.
    refreshPlanFeatures()
  }, [])

  const exitClient = useCallback(() => {
    clearClientContext()
    setCtx(null)
    refreshPlanFeatures()
  }, [])

  return (
    <AdvisorContext.Provider value={{ clientCtx, enterClient, exitClient }}>
      {children}
    </AdvisorContext.Provider>
  )
}

const FALLBACK = { clientCtx: null, enterClient: () => {}, exitClient: () => {} }

export function useAdvisorContext() {
  return useContext(AdvisorContext) || FALLBACK
}
