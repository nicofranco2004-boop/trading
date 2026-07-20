// useAlerts — CRUD de alertas personalizadas (precio objetivo + % de movimiento).
// Fuente: /api/alerts (GET items+events, POST crear, PATCH editar/pausar,
// DELETE borrar). El backend gatea por cantidad (plan) y por capacidad
// (pct_move = Plus+); create() propaga el error 403 con payload {upgrade} para
// que la UI muestre el upsell.
import { useCallback, useEffect, useState } from 'react'
import { api } from '../utils/api'

export function useAlerts() {
  const [items, setItems] = useState([])
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get('/api/alerts')
      setItems(res.items || [])
      setEvents(res.events || [])
      setError(null)
    } catch (e) {
      setError(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const create = useCallback(async (payload) => {
    const res = await api.post('/api/alerts', payload)  // throws en 403 (upsell)
    await refresh()
    return res
  }, [refresh])

  const update = useCallback(async (id, patch) => {
    await api.patch(`/api/alerts/${id}`, patch)
    await refresh()
  }, [refresh])

  const remove = useCallback(async (id) => {
    await api.delete(`/api/alerts/${id}`)
    await refresh()
  }, [refresh])

  const unseenCount = events.filter(e => !e.seen).length

  return { items, events, loading, error, refresh, create, update, remove, unseenCount }
}
