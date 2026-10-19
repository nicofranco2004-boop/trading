// useResumenMercado — el interruptor del resumen del mercado por mail.
// ═══════════════════════════════════════════════════════════════════════════
// Lo leen dos lugares de /alertas: la tarjeta de «Crear alerta» (para prenderlo)
// y la fila de «Mis alertas» (para apagarlo). Con un hook por pantalla, prender
// en una pestaña no se enteraba la otra; por eso vive una vez en la página y
// baja a las dos.
//
// Decisión de producto (Nico, sep 2026): UNO por día hábil, a las 11:00 de
// Argentina, el mismo para todos. Arranca APAGADO: va a toda la base, y un mail
// diario que nadie pidió es cómo se llega a la pestaña «Actualizaciones» de Gmail.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../utils/api'
import { useToast } from '../components/Toast'

export function useResumenMercado() {
  const toast = useToast()
  const [prefs, setPrefs] = useState(null)        // {enabled} | null mientras carga
  const [error, setError] = useState(false)

  const cargar = useCallback(() => api.get('/market-brief/prefs')
    .then(d => { setPrefs(d); setError(false) })
    // Sin dato NO se inventa el estado: creería que apagó algo que sigue
    // mandando, o al revés. Se avisa y se ofrece reintentar.
    .catch(() => setError(true)), [])

  useEffect(() => { cargar() }, [cargar])

  const cambiar = useCallback(async (enabled) => {
    setPrefs({ enabled })                           // optimista
    try {
      await api.patch('/market-brief/prefs', { enabled })
      toast.push(enabled ? 'Listo — te llega el próximo día hábil a las 11:00' : 'Resumen apagado')
    } catch {
      setPrefs({ enabled: !enabled })               // revertir
      toast.push('No se pudo guardar', { type: 'error' })
    }
  }, [toast])

  return { cargado: prefs != null, prendido: !!(prefs && prefs.enabled), error, cargar, cambiar }
}
