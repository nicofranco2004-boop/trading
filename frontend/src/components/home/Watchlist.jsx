// Watchlist — tickers seguidos sin holding (V2).
// Panel denso + DataRow por ticker.
//
// Movimiento (2026-09-29), el mismo que Movers del día: filas que aparecen de a
// una y porcentajes que cuentan al entrar en pantalla, barra de intensidad
// detrás de cada fila, estado de la rueda arriba (EnVivo) y refresco solo cada
// 5 min con destello en el número que cambió. Acá el destello se ve más
// seguido que en los movers: cada cotización vive 1 min en el servidor.

import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Star, X, TrendingUp, TrendingDown, Eye, Table2 } from 'lucide-react'
import { api } from '../../utils/api'
import { pctVar, pctVarSign } from '../../utils/format'
import { urlDeActivo } from '../../utils/buscadorRapido'
import Panel from '../Panel'
import Eyebrow from '../Eyebrow'
import DataRow from '../DataRow'
import { subscribeWatchlistChanged, notifyWatchlistChanged } from '../../utils/watchlistEvents'
import { refrescoSegunRueda } from '../../utils/relojVisible'
import { useUltimoPedido } from '../../hooks/useUltimoPedido'
import { useRelojVisible } from '../../hooks/useRelojVisible'
import { useAlVerse, entrada } from '../../hooks/useAlVerse'
import EnVivo from '../EnVivo'
import BarraIntensidad from '../BarraIntensidad'
import FlashValue from '../FlashValue'
import AnimatedNumber from '../AnimatedNumber'

function fmtPrice(p) {
  if (p == null) return '—'
  return p.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// La moneda sale del símbolo: `.BA` cotiza en BYMA, en pesos. Decía "US$" a
// todo — GGAL.BA a 5.850 pesos salía "US$5.850,00".
export function monedaDe(symbol) {
  return String(symbol || '').toUpperCase().endsWith('.BA') ? '$' : 'US$'
}

export default function Watchlist() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()
  const [removingSym, setRemovingSym] = useState(null)
  const [estado, setEstado] = useState(null)
  const [ref, visto] = useAlVerse()
  const nuevoPedido = useUltimoPedido()

  function load({ silent = false } = {}) {
    if (!silent) setLoading(true)
    // Una respuesta que llega tarde (ya salió otro pedido) no pisa a la nueva.
    const vigente = nuevoPedido()
    api.get('/watchlist')
      .then(d => {
        if (!vigente()) return
        setItems(d.items || [])
        const { items: _items, ...est } = d
        setEstado(est)
      })
      // Un refresco silencioso que falla no vacía la lista que ya se ve.
      .catch(() => { if (vigente() && !silent) setItems([]) })
      .finally(() => { if (vigente()) setLoading(false) })
  }

  // Cada 5 min con alguna rueda de la lista viva; con todas cerradas, a la
  // próxima media hora en punto (cuando puede abrir alguna).
  // Cada pedido de acá puede bajar cotizaciones de Yahoo para ESTE usuario.
  // Una vez por respuesta: calculado en cada render, un plazo que depende de
  // la hora reiniciaba el reloj con cualquier cambio de estado.
  const plazo = useMemo(() => refrescoSegunRueda(estado), [estado])
  useRelojVisible(() => load({ silent: true }), plazo)

  useEffect(() => {
    load()
    // Escuchar cambios disparados desde MobileSearch / SearchBar / la ficha
    // del activo para refrescar la lista sin requerir reload.
    const unsubscribe = subscribeWatchlistChanged(({ detail }) => {
      // Si llega { symbol, added: true } podemos hacer optimistic update
      // — agregamos el row con price/change_pct null mientras el fetch
      // completa con precios reales.
      if (detail?.added && detail?.symbol) {
        setItems(prev => {
          if (prev.some(i => i.symbol === detail.symbol)) return prev
          return [{ symbol: detail.symbol, price: null, change_pct: null, _pending: true }, ...prev]
        })
      }
      if (detail?.removed && detail?.symbol) {
        setItems(prev => prev.filter(i => i.symbol !== detail.symbol))
      }
      // Re-fetch en background para traer precios + sync con backend
      load({ silent: true })
    })
    return unsubscribe
  }, [])

  async function remove(symbol) {
    setRemovingSym(symbol)
    try {
      await api.delete(`/watchlist/${encodeURIComponent(symbol)}`)
      setItems(prev => prev.filter(i => i.symbol !== symbol))
      notifyWatchlistChanged({ symbol, removed: true })
    } catch {
      load()
    } finally {
      setRemovingSym(null)
    }
  }

  return (
    <section ref={ref}>
      {/* En el celular no entra todo en un renglón: lo de la derecha baja
          entero (el botón no se parte en tres). */}
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 mb-2">
        <h2><Eyebrow>Watchlist</Eyebrow></h2>
        <span className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1.5">
          {!loading && items.length > 0 && (
            <>
              {estado && <EnVivo estado={estado} />}
              <span className="text-[12px] text-ink-3 whitespace-nowrap">{items.length} tickers</span>
            </>
          )}
          {/* Lo que tenés y lo que seguís en una tabla, con su lectura técnica
              (pages/TuLista.jsx). Va aunque la watchlist esté vacía: también
              muestra tu cartera. */}
          <Link to="/tu-lista"
            className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-line-2 px-2.5 py-1 text-[12.5px] text-ink-1 hover:text-ink-0 hover:border-data-violet/50 transition-colors">
            <Table2 size={13} strokeWidth={1.75} aria-hidden="true" />
            Ver como tablero
          </Link>
        </span>
      </div>

      {loading ? (
        <div className="rounded border border-line bg-bg-1 p-3 space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-8 rounded-sm bg-bg-2 esqueleto" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Panel padding="lg" className="text-center">
          <Eye size={18} className="mx-auto mb-2 text-ink-3" strokeWidth={1.5} aria-hidden="true" />
          <p className="text-xs text-ink-2">
            Tu watchlist está vacía. Buscá un ticker arriba y agregalo desde su ficha.
          </p>
        </Panel>
      ) : (
        <Panel padding="none" className="overflow-hidden">
          <div className="divide-y divide-line/30">
            {items.map((it, i) => {
              // Del número redondeado; sin cotización, gris y sin flecha.
              const dir = pctVarSign(it.change_pct)
              const pending = it._pending && it.price == null
              return (
                <div
                  key={it.symbol}
                  {...entrada(visto, i, 'flex items-center group')}
                >
                  <DataRow
                    density="default"
                    hoverable
                    onClick={() => navigate(urlDeActivo(it.symbol))}
                    className="flex-1 relative isolate"
                  >
                    {!pending && <BarraIntensidad pct={it.change_pct} visto={visto} />}
                    <Star size={11} className="text-rendi-warn flex-shrink-0" fill="currentColor" strokeWidth={1.5} aria-hidden="true" />
                    <DataRow.Cell width={80} mono>
                      <span className="text-ink-0 text-[13px]">{it.symbol}</span>
                    </DataRow.Cell>
                    <DataRow.Cell align="right" tabular className="flex-1">
                      {pending
                        ? <span className="inline-block w-12 h-3 rounded-sm bg-bg-2 esqueleto" aria-label="Cargando precio" />
                        : `${monedaDe(it.symbol)}${fmtPrice(it.price)}`}
                    </DataRow.Cell>
                    <DataRow.Cell align="right" width={80} tabular>
                      {pending
                        ? <span className="inline-block w-10 h-3 rounded-sm bg-bg-2 esqueleto" />
                        : (
                          <FlashValue value={it.change_pct} className={`flex items-center justify-end gap-1 font-medium ${dir > 0 ? 'text-rendi-pos' : dir < 0 ? 'text-rendi-neg' : 'text-ink-3'}`}>
                            {dir > 0 && <TrendingUp size={9} strokeWidth={1.75} aria-hidden="true" />}
                            {dir < 0 && <TrendingDown size={9} strokeWidth={1.75} aria-hidden="true" />}
                            <AnimatedNumber value={it.change_pct} visto={visto} format={pctVar} />
                          </FlashValue>
                        )}
                    </DataRow.Cell>
                  </DataRow>
                  <button
                    onClick={(e) => { e.stopPropagation(); remove(it.symbol) }}
                    disabled={removingSym === it.symbol}
                    className="text-ink-3 hover:text-rendi-neg p-2 flex-shrink-0 disabled:opacity-40 opacity-0 group-hover:opacity-100 transition-opacity"
                    title="Quitar de watchlist"
                    aria-label="Quitar"
                  >
                    <X size={11} strokeWidth={1.75} />
                  </button>
                </div>
              )
            })}
          </div>
        </Panel>
      )}
    </section>
  )
}
