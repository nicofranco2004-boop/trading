// useWatchlist — hook compartido que reusa la watchlist EXISTENTE del app.
// ═══════════════════════════════════════════════════════════════════════════
// No inventa store: lee GET /watchlist, escribe POST/DELETE /watchlist, y se
// sincroniza vía el bus de eventos window-level de utils/watchlistEvents
// (mismo que usan SearchBar / AssetQuickView / Watchlist).
//
// Devuelve:
//   { symbols: string[] (upper), has(sym), toggle(sym), loading }
// `toggle` hace optimistic update + emite track('fundamentals_favorite_toggled').

import { useEffect, useState, useCallback, useRef } from 'react'
import { api } from '../../utils/api'
import { notifyWatchlistChanged, subscribeWatchlistChanged } from '../../utils/watchlistEvents'
import { track } from '../../utils/track'

export default function useWatchlist() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const busyRef = useRef(new Set())

  const load = useCallback(({ silent = false } = {}) => {
    if (!silent) setLoading(true)
    api.get('/watchlist')
      .then(d => setItems(Array.isArray(d?.items) ? d.items : []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
    const unsub = subscribeWatchlistChanged(() => load({ silent: true }))
    return unsub
  }, [load])

  const symbols = items.map(i => (i.symbol || '').toUpperCase())

  const has = useCallback(
    sym => symbols.includes((sym || '').toUpperCase()),
    [symbols],
  )

  const toggle = useCallback(async (rawSym) => {
    const sym = (rawSym || '').toUpperCase()
    if (!sym || busyRef.current.has(sym)) return
    busyRef.current.add(sym)
    const wasIn = symbols.includes(sym)
    // Optimistic
    setItems(prev => wasIn
      ? prev.filter(i => (i.symbol || '').toUpperCase() !== sym)
      : [{ symbol: sym, price: null, change_pct: null, _pending: true }, ...prev])
    try {
      if (wasIn) {
        await api.delete(`/watchlist/${encodeURIComponent(sym)}`)
        notifyWatchlistChanged({ symbol: sym, removed: true })
      } else {
        await api.post('/watchlist', { symbol: sym })
        notifyWatchlistChanged({ symbol: sym, added: true })
      }
      track('fundamentals_favorite_toggled', { ticker: sym, on: !wasIn })
    } catch {
      // Revertir ante error
      load({ silent: true })
    } finally {
      busyRef.current.delete(sym)
    }
  }, [symbols, load])

  return { symbols, items, has, toggle, loading }
}
