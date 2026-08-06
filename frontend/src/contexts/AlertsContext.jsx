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
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { useAlerts } from '../hooks/useAlerts'
import { api } from '../utils/api'

const AlertsCtx = createContext(null)

export function AlertsProvider({ children }) {
  const alerts = useAlerts()
  const { refresh } = alerts

  // Los avisos del LIBRO viven en otra tabla (advisor_alert_events) y no salen
  // de /alerts. Sin esto el puntito no se prendía nunca para un asesor: su
  // cuenta no tiene alertas de precio propias, así que el contador daba 0
  // aunque le hubieran avisado de cinco clientes.
  const [advisorUnseen, setAdvisorUnseen] = useState(0)
  const loadAdvisor = useCallback(async () => {
    try {
      const d = await api.get('/advisor/alerts')
      setAdvisorUnseen((d.history || []).filter(e => !e.seen).length)
    } catch { setAdvisorUnseen(0) }   // 401/403 = no es asesor: sin badge
  }, [])
  useEffect(() => { loadAdvisor() }, [loadAdvisor])

  // Marca todos los eventos como vistos (apaga el badge) y recarga. Idempotente:
  // el backend hace UPDATE ... WHERE seen=0 (no-op si no hay nada sin ver).
  // Silencioso: el indicador no es crítico, un error no debe romper la página.
  const markSeen = useCallback(async () => {
    try {
      await api.post('/alerts/events/seen')
      await refresh()
    } catch { /* el badge no es crítico */ }
    // Los del libro se apagan aparte (endpoint propio); si la cuenta no es
    // asesora tira 403 y no pasa nada.
    try {
      await api.post('/advisor/alerts/events/seen')
      setAdvisorUnseen(0)
    } catch { /* no es asesor */ }
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
      loadAdvisor()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [refresh, loadAdvisor])

  // El sidebar lee UN solo número: los propios + los del libro.
  const unseenCount = (alerts.unseenCount || 0) + advisorUnseen

  return (
    <AlertsCtx.Provider value={{ ...alerts, unseenCount, markSeen }}>
      {children}
    </AlertsCtx.Provider>
  )
}

// Degradación segura: fuera del provider devuelve defaults (sin dot, no-op) en
// vez de romper — el badge nunca debe tirar la app.
export function useAlertsContext() {
  return useContext(AlertsCtx) ?? { unseenCount: 0, markSeen: () => {} }
}
