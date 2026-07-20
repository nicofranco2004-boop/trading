// PlazosFijosGroup — grupo "Plazos fijos" en Cartera. Display + borrado. El alta
// la dispara el flujo de "Agregar posición" (o el botón contextual del header),
// que abre el PfFormModal a nivel de la página. Controlado por props:
//   • reloadKey: cambia → refetch (cuando se agrega un PF desde afuera)
//   • onAdd: abre el form de alta
// Cada PF se valúa con computePf (devengado a hoy + valor + cuenta regresiva).
import { useState, useEffect, Fragment } from 'react'
import { Plus, Landmark, Trash2, Clock, RotateCcw } from 'lucide-react'
import { api } from '../utils/api'
import { computePf } from '../utils/valuation'
import { useToast } from './Toast'

const pct = (x) => (x * 100).toFixed(2) + '%'
const todayStr = () => new Date().toISOString().slice(0, 10)
const moneyOf = (m) => (n) => (m === 'USD' ? 'US$' : '$') + Math.round(n).toLocaleString('es-AR')

export default function PlazosFijosGroup({ reloadKey, onAdd, onTotals, brokers = [], onChange }) {
  const toast = useToast()
  const [pfs, setPfs] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [cobrando, setCobrando] = useState(null)   // id del PF en proceso de cobro

  async function load() {
    try {
      const data = await api.get('/plazos-fijos')
      setPfs(data || [])
    } catch { /* noop */ }
    finally { setLoaded(true) }
  }
  useEffect(() => { load() }, [reloadKey])

  // Reporta {valor, capital} por moneda hacia el padre. El padre arma el P&L
  // coherente (valor = capital + devengado) y lo suma al patrimonio.
  useEffect(() => {
    if (!onTotals) return
    const now = todayStr()
    const t = {}
    for (const pf of pfs) {
      const m = pf.moneda || 'ARS'
      if (!t[m]) t[m] = { valor: 0, capital: 0 }
      t[m].valor += computePf(pf, now).valorHoy
      t[m].capital += (+pf.capital || 0)
    }
    onTotals(t)
    // onTotals es un setter estable; dependemos solo de pfs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pfs])

  async function del(pf) {
    if (!confirm(`¿Eliminar el plazo fijo en ${pf.banco}? Esta acción no se puede deshacer.`)) return
    try { await api.delete(`/plazos-fijos/${pf.id}`); load() }
    catch (e) { toast.push('Ocurrió un error: ' + e.message, { type: 'error' }) }
  }

  async function renovar(pf) {
    if (!confirm(`¿Renovar el plazo fijo en ${pf.banco}? Arranca un período nuevo con capital + interés, mismo plazo y tasa.`)) return
    try { await api.post(`/plazos-fijos/${pf.id}/renovar`); load() }
    catch (e) { toast.push('Ocurrió un error: ' + e.message, { type: 'error' }) }
  }

  async function cobrar(pf, broker) {
    if (!broker) {
      const monto = computePf(pf, todayStr()).valorHoy
      if (!confirm(`¿Retirar ${moneyOf(pf.moneda)(monto)}? La plata sale de tu cartera (no se trackea). El interés igual queda contabilizado como ganancia.`)) return
    }
    try {
      const res = await api.post(`/plazos-fijos/${pf.id}/cobrar`, { broker: broker || null })
      setCobrando(null)
      toast.push(
        broker ? `Cobrado: ${moneyOf(pf.moneda)(res.monto)} acreditado en ${broker}.` : 'Plazo fijo cobrado y retirado.',
        { type: 'success' },
      )
      load()
      if (broker) onChange && onChange()   // el cash del broker cambió → refrescar posiciones
    } catch (e) { toast.push('Ocurrió un error: ' + e.message, { type: 'error' }) }
  }

  // Brokers cuya moneda matchea la del PF (para acreditar el cobro).
  const matchingBrokers = (pf) => (brokers || []).filter(b => {
    const c = (b.currency || '').toUpperCase()
    return (pf.moneda === 'ARS') ? c === 'ARS' : (c === 'USD' || c === 'USDT')
  })

  if (!loaded) return null

  const Header = (
    <div className="flex items-center justify-between mb-2">
      <h2 className="text-sm text-ink-2 flex items-center gap-2 font-medium">
        <Landmark size={14} aria-hidden="true" /> Plazos fijos{pfs.length > 0 ? ` (${pfs.length})` : ''}
      </h2>
      <button
        onClick={onAdd}
        className="flex items-center gap-1 text-xs bg-bg-2 hover:bg-bg-3 border border-line text-ink-1 px-2.5 py-1.5 rounded-sm transition"
      >
        <Plus size={13} /> Plazo fijo
      </button>
    </div>
  )

  if (pfs.length === 0) {
    return (
      <div className="mt-6">
        {Header}
        <p className="text-xs text-ink-3">Todavía no cargaste ningún plazo fijo.</p>
      </div>
    )
  }

  const now = todayStr()
  const totals = {}
  for (const pf of pfs) {
    const v = computePf(pf, now)
    totals[pf.moneda] = (totals[pf.moneda] || 0) + v.valorHoy
  }

  return (
    <div className="mt-6">
      {Header}
      <div className="bg-white dark:bg-bg-2/40 border border-line rounded-md overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line/50">
                {['Banco', 'Capital', 'Tasa', 'Vence', 'Devengado', 'Valor hoy', ''].map(h => (
                  <th key={h} className="px-3 py-2 text-left text-xs text-ink-3 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pfs.map(pf => {
                const v = computePf(pf, now)
                const money = moneyOf(pf.moneda)
                return (
                  <Fragment key={pf.id}>
                    <tr className="border-b border-line/40 dark:border-line/30 hover:bg-bg-2 dark:hover:bg-bg-2/20">
                      <td className="px-3 py-2">
                        <div className="font-medium text-ink-0">{pf.banco}</div>
                        <div className="text-[11px] text-ink-3">
                          {pf.rate_type} {pct(pf.tasa)} · {pf.plazo_dias}d · {pf.moneda}
                          {pf.modalidad === 'periodico' && pf.pago_frecuencia_meses ? ` · capitaliza c/${pf.pago_frecuencia_meses}m` : ''}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-ink-1 tabular">{money(pf.capital)}</td>
                      <td className="px-3 py-2 text-ink-2 text-[11px] leading-tight">
                        <div>TNA {pct(v.tnaEquiv)}</div>
                        <div>TEA {pct(v.teaEquiv)}</div>
                      </td>
                      <td className="px-3 py-2 text-[11px] leading-tight">
                        <div className="text-ink-1">{pf.fecha_vencimiento}</div>
                        <div className={`flex items-center gap-1 ${v.vencido ? 'text-rendi-pos' : 'text-ink-3'}`}>
                          <Clock size={10} /> {v.vencido ? 'Vencido' : `faltan ${v.diasRestantes}d`}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-rendi-pos tabular">+{money(v.devengadoHoy)}</td>
                      <td className="px-3 py-2 text-ink-0 font-semibold tabular">{money(v.valorHoy)}</td>
                      <td className="px-3 py-2">
                        {v.vencido ? (
                          <div className="flex items-center gap-1 justify-end">
                            <button onClick={() => renovar(pf)} title="Renovar"
                              className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-bg-2 hover:bg-bg-3 border border-line text-ink-1 transition">
                              <RotateCcw size={11} /> Renovar
                            </button>
                            <button onClick={() => setCobrando(cobrando === pf.id ? null : pf.id)}
                              className="text-[11px] px-2 py-1 rounded bg-rendi-pos/15 text-rendi-pos hover:bg-rendi-pos/25 transition">
                              Cobrar
                            </button>
                          </div>
                        ) : (
                          <button onClick={() => del(pf)} className="text-ink-3 hover:text-red-500 transition" title="Eliminar plazo fijo">
                            <Trash2 size={13} />
                          </button>
                        )}
                      </td>
                    </tr>
                    {cobrando === pf.id && (
                      <tr className="bg-bg-2/40">
                        <td colSpan={7} className="px-3 py-2.5">
                          <div className="flex items-center gap-2 flex-wrap text-xs">
                            <span className="text-ink-2">Cobrás <span className="font-semibold text-ink-0">{money(v.valorHoy)}</span>.</span>
                            {matchingBrokers(pf).length > 0 && (
                              <>
                                <span className="text-ink-3">Dejala como cash en:</span>
                                {matchingBrokers(pf).map(b => (
                                  <button key={b.id ?? b.name} onClick={() => cobrar(pf, b.name)}
                                    className="px-2.5 py-1 rounded-md border border-line bg-bg-1 hover:border-rendi-accent/50 hover:bg-rendi-accent/5 text-ink-1 transition">
                                    {b.name}
                                  </button>
                                ))}
                                <span className="text-ink-3">o</span>
                              </>
                            )}
                            <button onClick={() => cobrar(pf, null)} title="La plata sale de tu cartera (la retirás a tu banco)"
                              className="px-2.5 py-1 rounded-md border border-dashed border-line text-ink-2 hover:text-ink-0 transition">
                              Retirar
                            </button>
                            <button onClick={() => setCobrando(null)} className="ml-auto text-ink-3 hover:text-ink-1">Cancelar</button>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="px-3 py-2 border-t border-line/50 text-xs text-ink-2 flex flex-wrap gap-x-4 gap-y-1 justify-end">
          {Object.entries(totals).map(([m, v]) => (
            <span key={m}>
              Subtotal {m}: <span className="text-ink-0 font-semibold tabular">{moneyOf(m)(v)}</span>
            </span>
          ))}
        </div>
      </div>
      <p className="text-[11px] text-ink-3 mt-1.5">
        Los plazos fijos no cotizan: el valor se calcula con tu tasa y el plazo (interés devengado).
      </p>
    </div>
  )
}
