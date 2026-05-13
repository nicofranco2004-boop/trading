// AssetQuickView — modal mini-ficha de un activo.
//
// V1: precio, variación diaria, market cap (estático del SP500_META si aplica).
// V2: mini-chart 30d via /api/prices/history, explicación AI del movimiento.
// V3: comentarios por ticker (feed social).
//
// Diseño: modal centrado, dismiss con X o click fuera. Mobile: full-width.

import { useEffect, useState } from 'react'
import { X, TrendingUp, TrendingDown, ExternalLink, Star, Check } from 'lucide-react'
import { api } from '../../utils/api'
import AssetLogo from '../AssetLogo'

function fmtPct(p) {
  if (p == null) return '—'
  const sign = p >= 0 ? '+' : ''
  return `${sign}${p.toFixed(2)}%`
}

function fmtPrice(p) {
  if (p == null) return '—'
  return `US$${p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export default function AssetQuickView({ symbol, onClose }) {
  const [quote, setQuote] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [inWatchlist, setInWatchlist] = useState(false)
  const [addingWl, setAddingWl] = useState(false)

  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    setLoading(true)
    // Fetch quote + check si ya está en watchlist (paralelo)
    Promise.all([
      api.get(`/prices?symbols=${encodeURIComponent(symbol)}`),
      api.get('/watchlist').catch(() => ({ items: [] })),
    ])
      .then(([prices, wl]) => {
        if (cancelled) return
        setQuote({ price: prices[symbol], symbol })
        setInWatchlist((wl.items || []).some(i => i.symbol === symbol))
      })
      .catch(ex => { if (!cancelled) setErr(ex.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [symbol])

  async function toggleWatchlist() {
    if (addingWl) return
    setAddingWl(true)
    try {
      if (inWatchlist) {
        await api.delete(`/watchlist/${encodeURIComponent(symbol)}`)
        setInWatchlist(false)
      } else {
        await api.post('/watchlist', { symbol })
        setInWatchlist(true)
      }
    } catch (ex) {
      console.error('Watchlist toggle:', ex)
    } finally {
      setAddingWl(false)
    }
  }

  // ESC para cerrar
  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose?.() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        onClick={e => e.stopPropagation()}
        className="bg-bg-1 border border-line rounded shadow-2xl w-full max-w-md max-h-[90vh] overflow-y-auto"
      >
        <header className="flex items-center justify-between px-4 py-3 border-b border-line/40">
          <div className="flex items-center gap-2 min-w-0">
            <AssetLogo asset={symbol} size={28} />
            <div className="min-w-0">
              <h3 className="font-semibold text-ink-0 truncate">{symbol}</h3>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-ink-3 hover:text-ink-0 p-1"
            aria-label="Cerrar"
          >
            <X size={16} strokeWidth={1.75} />
          </button>
        </header>

        <div className="p-4 space-y-4">
          {loading && (
            <div className="space-y-2">
              <div className="h-8 rounded-sm bg-bg-2 animate-pulse" />
              <div className="h-4 rounded-sm bg-bg-2 animate-pulse w-1/2" />
            </div>
          )}

          {err && !loading && (
            <div className="text-xs text-rendi-neg">{err}</div>
          )}

          {!loading && !err && quote && (
            <>
              <div>
                <div className="text-2xl font-mono tabular text-ink-0">
                  {fmtPrice(quote.price)}
                </div>
                <div className="text-[10px] text-ink-3 uppercase tracking-wider mt-0.5">
                  Último precio
                </div>
              </div>

              {/* V2: aquí va el mini-chart 30d + explicación de movimiento */}
              <div className="text-[11px] text-ink-3 leading-relaxed border-t border-line/40 pt-3">
                Historial detallado, comentarios y análisis vienen en próximas versiones.
              </div>
            </>
          )}
        </div>

        <footer className="px-4 py-3 border-t border-line/40 flex items-center justify-between gap-2 text-xs">
          <button
            onClick={toggleWatchlist}
            disabled={addingWl || loading}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-sm border transition-colors disabled:opacity-50 ${
              inWatchlist
                ? 'border-rendi-warn/30 bg-rendi-warn/10 text-rendi-warn hover:bg-rendi-warn/15'
                : 'border-line bg-bg-2 text-ink-1 hover:bg-bg-3'
            }`}
          >
            {inWatchlist
              ? <><Check size={11} strokeWidth={2} /> En watchlist</>
              : <><Star size={11} strokeWidth={1.75} /> Agregar a watchlist</>}
          </button>
          <a
            href={`https://finance.yahoo.com/quote/${symbol}`}
            target="_blank" rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-ink-2 hover:text-ink-0"
          >
            Yahoo Finance <ExternalLink size={11} strokeWidth={1.75} />
          </a>
        </footer>
      </div>
    </div>
  )
}
