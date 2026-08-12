// FuturosGroup — grupo "Futuros" en Cartera: posiciones ABIERTAS con su no
// realizado en vivo.
//
// Por qué es una sección aparte y no una posición más: un futuro no es una
// tenencia. No tenés el activo, y un SHORT vale al revés (gana cuando el precio
// baja). En el backend viven en su propia tabla por la misma razón — `positions`
// asume exposición positiva en 116 lugares.
//
// El no realizado se calcula acá, que es donde vive la valuación de la app:
//     long :  (mercado − entrada) × cantidad
//     short:  (entrada − mercado) × cantidad
// El backend expone `dir` (+1/−1) para no re-derivar ese signo en cada lugar.
//
// Pide sus PROPIOS precios: el subyacente de un futuro (BTC) puede no estar en
// la cartera, así que no alcanza con los precios que ya trajo la página.
import { useState, useEffect } from 'react'
import { Plus, TrendingUp, TrendingDown, Trash2, X } from 'lucide-react'
import { api } from '../utils/api'
import { useToast } from './Toast'

const hoy = () => new Date().toISOString().slice(0, 10)
const usd = (n) => (n < 0 ? '−' : '') + 'US$' + Math.abs(n).toLocaleString('es-AR',
  { minimumFractionDigits: 2, maximumFractionDigits: 2 })

// El no realizado de una posición, o null si todavía no sabemos el precio.
// Devolver null y NO 0 es a propósito: un 0 se lee como "no ganaste ni
// perdiste", que es una afirmación sobre tu plata que no podemos hacer si el
// feed no contestó.
export function noRealizado(pos, precio) {
  if (precio == null || !isFinite(precio)) return null
  const dir = pos.dir ?? (pos.side === 'short' ? -1 : 1)
  const pnl = (precio - pos.entry_price) * pos.quantity * dir
  const base = Math.abs(pos.entry_price * pos.quantity)
  return { pnl, pct: base > 0 ? pnl / base : null, precio }
}

export default function FuturosGroup({ reloadKey, brokers = [], onChange }) {
  const toast = useToast()
  const [futuros, setFuturos] = useState([])
  const [precios, setPrecios] = useState({})
  const [cargado, setCargado] = useState(false)
  const [formAbierto, setFormAbierto] = useState(false)
  const [cerrando, setCerrando] = useState(null)

  async function cargar() {
    try {
      const data = await api.get('/futures')
      setFuturos(data || [])
      const bases = [...new Set((data || []).map(f => f.base_asset).filter(Boolean))]
      if (bases.length) {
        try {
          setPrecios(await api.get(`/prices?symbols=${bases.join(',')}`) || {})
        } catch { /* sin precio → el no realizado queda en "—", no en 0 */ }
      }
    } catch { /* noop */ }
    finally { setCargado(true) }
  }
  useEffect(() => { cargar() }, [reloadKey])

  async function borrar(f) {
    if (!confirm(`¿Borrar la posición ${f.symbol}? No mueve plata: una posición abierta nunca tocó tu efectivo.`)) return
    try {
      await api.delete(`/futures/${f.id}`)
      toast.push('Posición borrada')
      cargar(); onChange?.()
    } catch (ex) {
      toast.push(ex.message || 'No se pudo borrar', { type: 'error' })
    }
  }

  // Sin futuros abiertos, la sección sólo aparece para quien PUEDE tenerlos (un
  // broker en USDT). Para el resto sería ruido en una pantalla que ya está
  // cargada. Pero tiene que aparecer igual: si devolviéramos null siempre que la
  // lista está vacía, no habría forma de cargar el primero.
  const puedeTenerFuturos = brokers.some(b => (b.currency || '').toUpperCase() === 'USDT')
  if (!cargado) return null
  if (!futuros.length && !puedeTenerFuturos && !formAbierto) return null

  if (!futuros.length) {
    return (
      <div className="mt-6 rounded-md border border-line bg-bg-1 px-4 py-3 flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-ink-0">Futuros abiertos</div>
          <div className="text-[11.5px] text-ink-3 font-medium">
            Seguí tus posiciones abiertas y su resultado no realizado.
          </div>
        </div>
        <button onClick={() => setFormAbierto(true)}
          className="inline-flex items-center gap-1 text-[12.5px] text-ink-2 hover:text-ink-0 transition-colors font-medium">
          <Plus size={13} /> Agregar
        </button>
        {formAbierto && (
          <FuturoForm brokers={brokers} onClose={() => setFormAbierto(false)}
            onSaved={() => { setFormAbierto(false); cargar(); onChange?.() }} />
        )}
      </div>
    )
  }

  const totalNoRealizado = futuros.reduce((acc, f) => {
    const r = noRealizado(f, precios[f.base_asset])
    return r ? acc + r.pnl : acc
  }, 0)
  const hayPrecios = futuros.some(f => precios[f.base_asset] != null)

  return (
    <div className="mt-6 rounded-md border border-line bg-bg-1 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-line">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-ink-0">Futuros abiertos</span>
          <span className="text-[12px] text-ink-3">{futuros.length}</span>
        </div>
        <div className="flex items-center gap-3">
          {hayPrecios && (
            <span className={`text-sm font-semibold ${totalNoRealizado >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
              {totalNoRealizado >= 0 ? '+' : ''}{usd(totalNoRealizado)}
              <span className="text-[11px] text-ink-3 font-medium ml-1">no realizado</span>
            </span>
          )}
          <button onClick={() => setFormAbierto(true)}
            className="inline-flex items-center gap-1 text-[12.5px] text-ink-2 hover:text-ink-0 transition-colors font-medium">
            <Plus size={13} /> Agregar
          </button>
        </div>
      </div>

      <div className="divide-y divide-line">
        {futuros.map(f => {
          const r = noRealizado(f, precios[f.base_asset])
          const esLong = (f.dir ?? 1) > 0
          return (
            <div key={f.id} className="flex items-center gap-3 px-4 py-3">
              <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm text-[10.5px] font-bold tracking-wide ${
                esLong ? 'bg-rendi-pos/10 text-rendi-pos' : 'bg-rendi-neg/10 text-rendi-neg'}`}>
                {esLong ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                {esLong ? 'LONG' : 'SHORT'}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-ink-0 truncate">
                  {f.symbol}
                  {f.leverage ? <span className="ml-1.5 text-[11px] text-ink-3 font-medium">{f.leverage}x</span> : null}
                </div>
                <div className="text-[11.5px] text-ink-3 font-medium">
                  {f.quantity} @ {usd(f.entry_price)} · {f.broker}
                </div>
              </div>
              <div className="text-right">
                {r ? (
                  <>
                    <div className={`text-sm font-semibold ${r.pnl >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                      {r.pnl >= 0 ? '+' : ''}{usd(r.pnl)}
                    </div>
                    <div className="text-[11.5px] text-ink-3 font-medium">
                      {usd(r.precio)}{r.pct != null ? ` · ${(r.pct * 100).toFixed(1)}%` : ''}
                    </div>
                  </>
                ) : (
                  <div className="text-[12px] text-ink-3 font-medium" title="No pudimos traer el precio del subyacente">—</div>
                )}
              </div>
              <button onClick={() => setCerrando(f)}
                className="text-[12px] px-2 py-1 rounded-sm border border-line text-ink-2 hover:text-ink-0 hover:border-line-2 transition-colors font-medium">
                Cerrar
              </button>
              <button onClick={() => borrar(f)} title="Borrar"
                className="text-ink-3 hover:text-rendi-neg transition-colors">
                <Trash2 size={14} />
              </button>
            </div>
          )
        })}
      </div>

      <p className="px-4 py-2.5 text-[11.5px] text-ink-3 leading-tight border-t border-line font-medium">
        El no realizado todavía no es plata tuya: recién entra al efectivo y al P&L
        cuando cerrás. El margen no se descuenta del saldo porque no salió de tu
        cuenta — es interno del broker.
      </p>

      {formAbierto && (
        <FuturoForm brokers={brokers} onClose={() => setFormAbierto(false)}
          onSaved={() => { setFormAbierto(false); cargar(); onChange?.() }} />
      )}
      {cerrando && (
        <CerrarFuturo pos={cerrando} precio={precios[cerrando.base_asset]}
          onClose={() => setCerrando(null)}
          onDone={() => { setCerrando(null); cargar(); onChange?.() }} />
      )}
    </div>
  )
}

// ─── Alta ────────────────────────────────────────────────────────────────────

function FuturoForm({ brokers, onClose, onSaved }) {
  const toast = useToast()
  const cripto = brokers.filter(b => (b.currency || '').toUpperCase() === 'USDT')
  const [f, setF] = useState({
    broker: (cripto[0] || brokers[0] || {}).name || '', symbol: '', side: 'long',
    quantity: '', entry_price: '', leverage: '', margin_usd: '', opened_at: hoy(),
  })
  const inp = 'w-full bg-bg-2 border border-line rounded-sm px-2.5 py-1.5 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2'
  const lbl = 'block text-[12.5px] text-ink-2 mb-1 font-medium'

  async function guardar() {
    if (!f.symbol.trim() || !f.quantity || !f.entry_price) {
      toast.push('Completá par, cantidad y precio de entrada', { type: 'error' }); return
    }
    try {
      await api.post('/futures', {
        broker: f.broker, symbol: f.symbol.trim().toUpperCase(), side: f.side,
        quantity: +f.quantity, entry_price: +f.entry_price,
        leverage: f.leverage ? +f.leverage : null,
        margin_usd: f.margin_usd ? +f.margin_usd : null,
        opened_at: f.opened_at,
      })
      toast.push('Posición agregada')
      onSaved()
    } catch (ex) {
      toast.push(ex.message || 'No se pudo guardar', { type: 'error' })
    }
  }

  return (
    <Overlay title="Nueva posición de futuros" onClose={onClose}>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={lbl}>Broker</label>
          <select value={f.broker} onChange={e => setF(x => ({ ...x, broker: e.target.value }))} className={inp}>
            {brokers.map(b => <option key={b.id} value={b.name}>{b.name}</option>)}
          </select>
        </div>
        <div>
          <label className={lbl}>Par</label>
          <input value={f.symbol} onChange={e => setF(x => ({ ...x, symbol: e.target.value }))}
            className={inp} placeholder="BTCUSDT" />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={lbl}>Dirección</label>
          <select value={f.side} onChange={e => setF(x => ({ ...x, side: e.target.value }))} className={inp}>
            <option value="long">LONG — gano si sube</option>
            <option value="short">SHORT — gano si baja</option>
          </select>
        </div>
        <div>
          <label className={lbl}>Fecha de apertura</label>
          <input type="date" value={f.opened_at} onChange={e => setF(x => ({ ...x, opened_at: e.target.value }))} className={inp} />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={lbl}>Cantidad (en {f.symbol ? f.symbol.replace(/USDT|USDC|BUSD|USD$/, '') || 'unidades' : 'unidades'})</label>
          <input type="number" step="any" value={f.quantity} onChange={e => setF(x => ({ ...x, quantity: e.target.value }))} className={inp} placeholder="0.5" />
        </div>
        <div>
          <label className={lbl}>Precio de entrada</label>
          <input type="number" step="any" value={f.entry_price} onChange={e => setF(x => ({ ...x, entry_price: e.target.value }))} className={inp} placeholder="60000" />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={lbl}>Apalancamiento <span className="text-ink-3">(opcional)</span></label>
          <input type="number" step="any" value={f.leverage} onChange={e => setF(x => ({ ...x, leverage: e.target.value }))} className={inp} placeholder="10" />
        </div>
        <div>
          <label className={lbl}>Margen <span className="text-ink-3">(opcional)</span></label>
          <input type="number" step="any" value={f.margin_usd} onChange={e => setF(x => ({ ...x, margin_usd: e.target.value }))} className={inp} placeholder="3000" />
        </div>
      </div>
      <p className="text-[12px] text-ink-3 leading-tight font-medium">
        El margen es sólo informativo: no se descuenta de tu efectivo, porque esa
        plata no salió de tu cuenta.
      </p>
      <Acciones onClose={onClose} onSave={guardar} texto="Guardar" />
    </Overlay>
  )
}

// ─── Cierre ──────────────────────────────────────────────────────────────────

function CerrarFuturo({ pos, precio, onClose, onDone }) {
  const toast = useToast()
  const [salida, setSalida] = useState(precio != null ? String(precio) : '')
  const [comis, setComis] = useState('')
  const [fecha, setFecha] = useState(hoy())
  const inp = 'w-full bg-bg-2 border border-line rounded-sm px-2.5 py-1.5 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2'
  const lbl = 'block text-[12.5px] text-ink-2 mb-1 font-medium'

  const dir = pos.dir ?? (pos.side === 'short' ? -1 : 1)
  const previa = salida !== '' && isFinite(+salida)
    ? (+salida - pos.entry_price) * pos.quantity * dir - (+comis || 0)
    : null

  async function cerrar() {
    if (salida === '' || !isFinite(+salida) || +salida <= 0) {
      toast.push('Poné el precio al que cerraste', { type: 'error' }); return
    }
    try {
      const r = await api.post(`/futures/${pos.id}/close`, {
        exit_price: +salida, closed_at: fecha, commissions: +comis || 0,
      })
      toast.push(`Cerrada · ${r.pnl_usd >= 0 ? '+' : ''}${usd(r.pnl_usd)} al efectivo`)
      onDone()
    } catch (ex) {
      toast.push(ex.message || 'No se pudo cerrar', { type: 'error' })
    }
  }

  return (
    <Overlay title={`Cerrar ${pos.symbol}`} onClose={onClose}>
      <div className="text-[12.5px] text-ink-2 font-medium">
        {dir > 0 ? 'LONG' : 'SHORT'} de {pos.quantity} · entrada {usd(pos.entry_price)}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={lbl}>Precio de salida</label>
          <input type="number" step="any" value={salida} onChange={e => setSalida(e.target.value)} className={inp} autoFocus />
        </div>
        <div>
          <label className={lbl}>Fecha</label>
          <input type="date" value={fecha} onChange={e => setFecha(e.target.value)} className={inp} />
        </div>
      </div>
      <div>
        <label className={lbl}>Comisiones <span className="text-ink-3">(opcional)</span></label>
        <input type="number" step="any" value={comis} onChange={e => setComis(e.target.value)} className={inp} placeholder="0" />
      </div>
      {previa != null && (
        <div className="rounded-sm border border-line bg-bg-1 px-3 py-2.5">
          <div className="text-[12.5px] text-ink-2 font-medium">Resultado que se acredita</div>
          <div className={`text-lg font-semibold ${previa >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
            {previa >= 0 ? '+' : ''}{usd(previa)}
          </div>
          <div className="text-[11.5px] text-ink-3 font-medium leading-tight mt-0.5">
            Entra a tu efectivo en {pos.broker} y cuenta como ganancia realizada.
            No suma al capital aportado.
          </div>
        </div>
      )}
      <Acciones onClose={onClose} onSave={cerrar} texto="Cerrar posición" />
    </Overlay>
  )
}

// ─── Chrome compartido ───────────────────────────────────────────────────────

function Overlay({ title, children, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 p-0 sm:p-4"
      onClick={onClose}>
      <div className="w-full sm:max-w-md bg-bg-0 border border-line rounded-t-lg sm:rounded-lg shadow-xl max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 sm:px-5 py-3 border-b border-line">
          <h2 className="text-base font-semibold text-ink-0">{title}</h2>
          <button onClick={onClose} className="text-ink-3 hover:text-ink-0 transition-colors"><X size={18} /></button>
        </div>
        <div className="p-4 sm:p-5 overflow-y-auto space-y-3">{children}</div>
      </div>
    </div>
  )
}

function Acciones({ onClose, onSave, texto }) {
  return (
    <div className="flex justify-end gap-2 pt-1">
      <button onClick={onClose} className="text-[12.5px] text-ink-3 hover:text-ink-0 px-3 py-1.5 transition-colors font-medium">
        Cancelar
      </button>
      <button onClick={onSave}
        className="text-[12.5px] bg-rendi-pos/10 text-rendi-pos hover:bg-rendi-pos/15 border border-rendi-pos/30 px-3 py-1.5 rounded-sm transition-colors font-medium">
        {texto}
      </button>
    </div>
  )
}
