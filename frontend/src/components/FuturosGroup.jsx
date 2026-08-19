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
import { Plus, TrendingUp, TrendingDown, Trash2, X, ArrowLeft, Wallet } from 'lucide-react'
import { api } from '../utils/api'
import { useToast } from './Toast'

const hoy = () => new Date().toISOString().slice(0, 10)
const usd = (n) => (n < 0 ? '−' : '') + 'US$' + Math.abs(n).toLocaleString('es-AR',
  { minimumFractionDigits: 2, maximumFractionDigits: 2 })

// El no realizado de una posición, o null si todavía no sabemos el precio.
// Devolver null y NO 0 es a propósito: un 0 se lee como "no ganaste ni
// perdiste", que es una afirmación sobre tu plata que no podemos hacer si el
// feed no contestó.
// BTCUSDT → BTC, para el texto "en unidades de X". Espejo de `_base_asset_de`
// del backend; si no matchea, devolvemos vacío y el label queda genérico.
export function baseDe(symbol) {
  const s = (symbol || '').trim().toUpperCase()
  for (const q of ['USDT', 'USDC', 'BUSD', 'USD']) {
    if (s.endsWith(q) && s.length > q.length) return s.slice(0, -q.length)
  }
  return s
}

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
          <FuturoFlow brokers={brokers} onClose={() => setFormAbierto(false)}
            onSaved={() => { setFormAbierto(false); cargar(); onChange?.() }} />
        )}
      </div>
    )
  }

  const totalNoRealizado = futuros.reduce((acc, f) => {
    const r = noRealizado(f, precios[f.base_asset])
    return r ? acc + r.pnl : acc
  }, 0)
  const conPrecio = futuros.filter(f => precios[f.base_asset] != null).length
  const hayPrecios = conPrecio > 0
  // Si a alguna le falta el precio, el total NO la incluye. Decirlo: un total
  // que parece completo y no lo es es peor que no mostrarlo.
  const totalParcial = hayPrecios && conPrecio < futuros.length

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
              <span className="text-[11px] text-ink-3 font-medium ml-1">
                {totalParcial ? `no realizado · ${conPrecio} de ${futuros.length}` : 'no realizado'}
              </span>
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
        <FuturoFlow brokers={brokers} onClose={() => setFormAbierto(false)}
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

// ════════════════════════════════════════════════════════════════════════════
// ALTA — flujo por pasos, mismo lenguaje que "Registrar compra"
// ════════════════════════════════════════════════════════════════════════════
// Por qué pasos y no un formulario de una: la decisión que define un futuro es
// LONG vs SHORT, y en un form plano es un `select` más entre siete campos. Acá
// es un paso propio con dos tarjetas que explican qué significa cada una en
// castellano — es la que, si se elige mal, invierte el resultado.

function FuturoFlow({ brokers, onClose, onSaved }) {
  const toast = useToast()
  // Sólo brokers que pueden tener futuros. Si hay uno solo, salteamos el paso.
  const cuentas = brokers.filter(b => (b.currency || '').toUpperCase() === 'USDT')
  const elegibles = cuentas.length ? cuentas : brokers
  const SEQ = elegibles.length > 1 ? ['broker', 'lado', 'datos'] : ['lado', 'datos']
  const [idx, setIdx] = useState(0)
  const paso = SEQ[idx]

  const [f, setF] = useState({
    broker: elegibles.length === 1 ? elegibles[0].name : '',
    symbol: '', side: null, quantity: '', entry_price: '',
    leverage: '', margin_usd: '', opened_at: hoy(),
  })
  const [guardando, setGuardando] = useState(false)

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const avanzar = () => setIdx(i => Math.min(i + 1, SEQ.length - 1))
  const volver = () => setIdx(i => Math.max(i - 1, 0))

  async function guardar() {
    if (!f.symbol.trim() || !f.quantity || !f.entry_price) {
      toast.push('Completá el par, la cantidad y el precio de entrada', { type: 'error' })
      return
    }
    setGuardando(true)
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
    } finally {
      setGuardando(false)
    }
  }

  const TITULOS = {
    broker: 'Elegí la cuenta',
    lado: '¿Para qué lado abriste?',
    datos: 'Cargá la posición',
  }
  const BAJADAS = {
    broker: '¿En qué cuenta está esta posición de futuros?',
    lado: 'Es lo que define si ganás cuando el precio sube o cuando baja.',
    datos: f.side === 'short'
      ? 'SHORT: ganás si el precio baja. Cargá el par, el tamaño y a qué precio entraste.'
      : 'LONG: ganás si el precio sube. Cargá el par, el tamaño y a qué precio entraste.',
  }

  return (
    <FlowShell
      paso={idx + 1} total={SEQ.length}
      titulo={TITULOS[paso]} bajada={BAJADAS[paso]}
      onBack={idx > 0 ? volver : null} onClose={onClose}
    >
      {paso === 'broker' && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {elegibles.map(b => (
            <button key={b.id ?? b.name}
              onClick={() => { setF(x => ({ ...x, broker: b.name })); avanzar() }}
              className="text-left bg-bg-2/40 border border-line rounded p-4 hover:border-rendi-accent/40 transition-colors focus:outline-none focus:ring-2 focus:ring-rendi-accent/40">
              <div className="flex items-center gap-3">
                <div className="flex-shrink-0 w-9 h-9 rounded-sm bg-bg-3 border border-line flex items-center justify-center text-rendi-accent">
                  <Wallet size={18} strokeWidth={1.5} />
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="font-semibold text-ink-0 text-sm leading-tight truncate">{b.name}</h3>
                  <p className="text-[12px] text-ink-3 mt-1 tracking-[0.12em] font-medium">{b.currency}</p>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {paso === 'lado' && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {[
            // Clases LITERALES a propósito. Tailwind sólo genera las que puede
            // leer en el código: una armada en runtime (interpolando el color
            // dentro del string) se purga del CSS y el color no se ve nunca.
            { id: 'long', label: 'LONG', icono: TrendingUp,
              icono_cls: 'text-rendi-pos', label_cls: 'text-rendi-pos',
              sel_cls: 'border-rendi-pos/50 ring-1 ring-rendi-pos/30',
              titulo: 'Invertí al alza',
              detalle: 'Ganás si el precio sube por encima de tu entrada. Perdés si baja.' },
            { id: 'short', label: 'SHORT', icono: TrendingDown,
              icono_cls: 'text-rendi-neg', label_cls: 'text-rendi-neg',
              sel_cls: 'border-rendi-neg/50 ring-1 ring-rendi-neg/30',
              titulo: 'Invertí a la baja',
              detalle: 'Ganás si el precio baja por debajo de tu entrada. Perdés si sube.' },
          ].map(o => (
            <button key={o.id}
              onClick={() => { setF(x => ({ ...x, side: o.id })); avanzar() }}
              className={`text-left bg-bg-2/40 border rounded p-4 transition-colors focus:outline-none focus:ring-2 ${
                f.side === o.id ? o.sel_cls : 'border-line hover:border-rendi-accent/40'
              } focus:ring-rendi-accent/40`}>
              <div className="flex items-start gap-3">
                <div className={`flex-shrink-0 w-9 h-9 rounded-sm bg-bg-3 border border-line flex items-center justify-center ${o.icono_cls}`}>
                  <o.icono size={18} strokeWidth={1.75} />
                </div>
                <div className="min-w-0 flex-1">
                  {/* LONG/SHORT manda: es el nombre que el usuario ve en su
                      broker. La frase en castellano va debajo, como traducción. */}
                  <h3 className={`font-bold text-sm leading-tight tracking-wide ${o.label_cls}`}>
                    {o.label}
                  </h3>
                  <p className="text-[12.5px] text-ink-0 font-medium mt-0.5 leading-tight">{o.titulo}</p>
                  <p className="text-[12px] text-ink-2 mt-1 leading-snug">{o.detalle}</p>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {paso === 'datos' && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Campo label="Par" ayuda="Como figura en tu broker">
              <input value={f.symbol} autoFocus
                onChange={e => setF(x => ({ ...x, symbol: e.target.value.toUpperCase() }))}
                className={INPUT} placeholder="BTCUSDT" />
            </Campo>
            <Campo label="Fecha de apertura">
              <input type="date" value={f.opened_at}
                onChange={e => setF(x => ({ ...x, opened_at: e.target.value }))} className={INPUT} />
            </Campo>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Campo label="Tamaño" ayuda={baseDe(f.symbol) ? `En unidades de ${baseDe(f.symbol)}` : 'En unidades del activo'}>
              <input type="number" step="any" value={f.quantity}
                onChange={e => setF(x => ({ ...x, quantity: e.target.value }))}
                className={INPUT} placeholder="0.5" />
            </Campo>
            <Campo label="Precio de entrada">
              <input type="number" step="any" value={f.entry_price}
                onChange={e => setF(x => ({ ...x, entry_price: e.target.value }))}
                className={INPUT} placeholder="60000" />
            </Campo>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Campo label="Apalancamiento" ayuda="Opcional — no entra en ningún cálculo">
              <input type="number" step="any" value={f.leverage}
                onChange={e => setF(x => ({ ...x, leverage: e.target.value }))}
                className={INPUT} placeholder="10" />
            </Campo>
            <Campo label="Margen" ayuda="Opcional — no se descuenta de tu efectivo">
              <input type="number" step="any" value={f.margin_usd}
                onChange={e => setF(x => ({ ...x, margin_usd: e.target.value }))}
                className={INPUT} placeholder="3000" />
            </Campo>
          </div>

          <div className="rounded-sm border border-line bg-bg-2/40 px-3.5 py-3 text-[12px] text-ink-2 leading-snug">
            El margen queda como dato: <strong className="text-ink-1">no se descuenta de tu
            saldo</strong>, porque pasarlo al wallet de futuros es un movimiento interno del
            broker — la plata sigue en tu cuenta. Y el resultado recién entra al efectivo y
            al P&L cuando cerrás la posición.
          </div>

          <div className="flex justify-end gap-2 pt-1">
            <button onClick={onClose} className="text-sm text-ink-3 hover:text-ink-0 px-3 py-2 transition-colors font-medium">
              Cancelar
            </button>
            <button onClick={guardar} disabled={guardando}
              className="inline-flex items-center gap-2 bg-data-violet hover:bg-data-violet/90 disabled:opacity-50 text-white text-sm font-medium rounded-sm px-4 py-2 transition-colors">
              {guardando ? 'Guardando…' : 'Agregar posición'}
            </button>
          </div>
        </div>
      )}
    </FlowShell>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// CIERRE — un paso, misma piel
// ════════════════════════════════════════════════════════════════════════════

function CerrarFuturo({ pos, precio, onClose, onDone }) {
  const toast = useToast()
  // El precio del feed viene con toda la cola del float (82.44999694824219).
  // Precargarlo así es ilegible y encima invita a "corregirlo" a mano. Se
  // redondea a una precisión razonable según la magnitud: los pares caros no
  // necesitan decimales finos y los baratos sí.
  const redondear = (x) => {
    if (x == null || !isFinite(x)) return ''
    const d = Math.abs(x) >= 1000 ? 2 : Math.abs(x) >= 1 ? 4 : 8
    return String(Number(x.toFixed(d)))
  }
  const [salida, setSalida] = useState(redondear(precio))
  const [comis, setComis] = useState('')
  const [fecha, setFecha] = useState(hoy())
  const [cerrandoYa, setCerrandoYa] = useState(false)

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const dir = pos.dir ?? (pos.side === 'short' ? -1 : 1)
  const previa = salida !== '' && isFinite(+salida)
    ? (+salida - pos.entry_price) * pos.quantity * dir - (+comis || 0)
    : null

  async function cerrar() {
    if (salida === '' || !isFinite(+salida) || +salida <= 0) {
      toast.push('Poné el precio al que cerraste', { type: 'error' }); return
    }
    setCerrandoYa(true)
    try {
      const r = await api.post(`/futures/${pos.id}/close`, {
        exit_price: +salida, closed_at: fecha, commissions: +comis || 0,
      })
      toast.push(`Cerrada · ${r.pnl_usd >= 0 ? '+' : ''}${usd(r.pnl_usd)} al efectivo`)
      onDone()
    } catch (ex) {
      toast.push(ex.message || 'No se pudo cerrar', { type: 'error' })
    } finally {
      setCerrandoYa(false)
    }
  }

  return (
    <FlowShell
      titulo={`Cerrar ${pos.symbol}`}
      bajada={`${dir > 0 ? 'LONG' : 'SHORT'} de ${pos.quantity} · entraste a ${usd(pos.entry_price)}`}
      onClose={onClose} ancho="max-w-lg"
    >
      <div className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Campo label="Precio de salida" ayuda="A cuánto cerraste">
            <input type="number" step="any" value={salida} autoFocus
              onChange={e => setSalida(e.target.value)} className={INPUT} />
          </Campo>
          <Campo label="Fecha">
            <input type="date" value={fecha} onChange={e => setFecha(e.target.value)} className={INPUT} />
          </Campo>
        </div>
        <Campo label="Comisiones" ayuda="Opcional — restan del resultado">
          <input type="number" step="any" value={comis}
            onChange={e => setComis(e.target.value)} className={INPUT} placeholder="0" />
        </Campo>

        {previa != null && (
          <div className={`rounded border px-4 py-3.5 ${
            previa >= 0 ? 'border-rendi-pos/30 bg-rendi-pos/5' : 'border-rendi-neg/30 bg-rendi-neg/5'}`}>
            <p className="eyebrow mb-1">Resultado que se acredita</p>
            <div className={`text-2xl font-semibold ${previa >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
              {previa >= 0 ? '+' : ''}{usd(previa)}
            </div>
            <p className="text-[12px] text-ink-2 mt-1.5 leading-snug">
              Entra a tu efectivo en <strong className="text-ink-1">{pos.broker}</strong> y
              cuenta como ganancia realizada. No suma al capital aportado.
            </p>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="text-sm text-ink-3 hover:text-ink-0 px-3 py-2 transition-colors font-medium">
            Cancelar
          </button>
          <button onClick={cerrar} disabled={cerrandoYa}
            className="inline-flex items-center gap-2 bg-data-violet hover:bg-data-violet/90 disabled:opacity-50 text-white text-sm font-medium rounded-sm px-4 py-2 transition-colors">
            {cerrandoYa ? 'Cerrando…' : 'Cerrar posición'}
          </button>
        </div>
      </div>
    </FlowShell>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// Piel compartida — mismo shell y header que AddPositionFlow
// ════════════════════════════════════════════════════════════════════════════

const INPUT = 'w-full bg-bg-2 border border-line rounded-sm px-3 py-2 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-rendi-accent/60 focus:ring-1 focus:ring-rendi-accent/30 transition-colors'

function Campo({ label, ayuda, children }) {
  return (
    <div>
      <label className="block text-[12.5px] text-ink-1 mb-1 font-medium">{label}</label>
      {children}
      {ayuda && <p className="text-[11.5px] text-ink-3 mt-1 leading-tight">{ayuda}</p>}
    </div>
  )
}

function FlowShell({ paso, total, titulo, bajada, onBack, onClose, ancho = 'max-w-2xl', children }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm sm:p-4 overflow-y-auto"
      onClick={onClose}>
      <div className={`bg-white dark:bg-bg-1 border border-line rounded-t-2xl sm:rounded w-full ${ancho} shadow-2xl max-h-[95vh] sm:max-h-[85vh] flex flex-col`}
        onClick={e => e.stopPropagation()}>
        <div className="flex items-start gap-3 px-5 py-4 border-b border-line flex-shrink-0">
          {onBack && (
            <button onClick={onBack} aria-label="Volver al paso anterior"
              className="flex-shrink-0 -ml-2 p-2 rounded-sm text-ink-2 hover:text-ink-0 hover:bg-bg-2 transition-colors">
              <ArrowLeft size={16} strokeWidth={1.75} />
            </button>
          )}
          <div className="min-w-0 flex-1">
            {paso ? <p className="eyebrow mb-1">Paso {paso} de {total}</p> : null}
            <h2 className="text-lg font-semibold text-ink-0 leading-tight">{titulo}</h2>
            <p className="text-xs text-ink-2 mt-0.5">{bajada}</p>
          </div>
          <button onClick={onClose} aria-label="Cerrar"
            className="flex-shrink-0 -mr-2 p-2 rounded-sm text-ink-2 hover:text-ink-0 hover:bg-bg-2 transition-colors">
            <X size={16} strokeWidth={1.75} />
          </button>
        </div>
        <div className="overflow-y-auto flex-1 p-5">{children}</div>
      </div>
    </div>
  )
}
