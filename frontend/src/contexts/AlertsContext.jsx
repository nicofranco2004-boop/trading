// AlertsContext — estado compartido de alertas para el badge del sidebar.
// ═══════════════════════════════════════════════════════════════════════════
// El puntito violeta del ítem "Alertas" indica que hay eventos de alerta SIN
// VER. El Sidebar lee `unseenCount` de acá; la página /alertas llama `markSeen()`
// al entrar y el badge se apaga. Un solo fetch de /alerts por sesión (useAlerts
// corre en el provider) + refresh al volver a la pestaña (throttled) para captar
// alertas que dispararon con la app abierta (el cron corre cada ~10 min).
//
// Backend ya listo: alert_events.seen + POST /api/alerts/events/seen + el flag
// `seen` en GET /api/alerts (useAlerts deriva unseenCount).
import { createContext, useCallback, useContext, useEffect, useRef } from 'react'
import { useAlerts } from '../hooks/useAlerts'
import { api } from '../utils/api'

const AlertsCtx = createContext(null)

export function AlertsProvider({ children }) {
  const alerts = useAlerts()
  const { refresh } = alerts

  // Marca todos los eventos como vistos (apaga el badge) y recarga. Idempotente:
  // el backend hace UPDATE ... WHERE seen=0 (no-op si no hay nada sin ver).
  // Silencioso: el indicador no es crítico, un error no debe romper la página.
  const markSeen = useCallback(async () => {
    try {
      await api.post('/alerts/events/seen')
      await refresh()
    } catch { /* el badge no es crítico */ }
  }, [refresh])

  // Refrescar al volver a la pestaña (throttle 60s) → capta alertas nuevas sin
  // polling constante. No afecta la vista de /alertas (AlertsManager tiene su
  // propia instancia de useAlerts); acá sólo mueve el contador del sidebar.
  const lastRefreshRef = useRef(0)
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return
      const now = Date.now()
      if (now - lastRefreshRef.current < 60000) return
      lastRefreshRef.current = now
      refresh()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [refresh])

  return <AlertsCtx.Provider value={{ ...alerts, markSeen }}>{children}</AlertsCtx.Provider>
}

// Degradación segura: fuera del provider devuelve defaults (sin dot, no-op) en
// vez de romper — el badge nunca debe tirar la app.
export function useAlertsContext() {
  return useContext(AlertsCtx) ?? { unseenCount: 0, markSeen: () => {} }
}
