// AlertsManager — gestor de alertas personalizadas (vive en Config › Notificaciones).
// Dos tipos:
//   • Precio objetivo: "avisame cuando AAPL llegue a US$200" (todos los planes).
//   • Variación %: "avisame cuando alguna de mis acciones caiga 10%" (Plus+).
// El backend gatea por cantidad y por capacidad; acá reflejamos el gate en la UI
// (el tipo % aparece bloqueado con badge Plus para Free) y mostramos el upsell si
// el POST devuelve 403.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Bell, Plus, Trash2, TrendingUp, TrendingDown, Target, Mail, Smartphone,
  X, Check, Zap, Sparkles,
} from 'lucide-react'
import Panel from '../Panel'
import Pill from '../Pill'
import { usePushNotifications } from '../../hooks/usePushNotifications'
import { useAlerts } from '../../hooks/useAlerts'

const EMPTY_FORM = {
  kind: 'price_target',
  scope: 'ticker',
  symbol: '',
  currency: 'USD',
  direction: 'above',
  threshold: '',
  channel: 'both',
  repeat: 'once',
}

function fmtPrice(v, ccy) {
  if (v == null) return '—'
  if ((ccy || '').toUpperCase() === 'ARS') return '$' + Number(v).toLocaleString('es-AR', { maximumFractionDigits: 0 })
  return 'US$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function displaySym(s) {
  if (!s) return 'Toda mi cartera'
  return s.replace(/^FCI:/, '').replace(/\.BA$/, '')
}

// Descripción humana de una alerta (para las filas de la lista).
function describeAlert(a) {
  const sym = displaySym(a.symbol)
  if (a.kind === 'price_target') {
    const arrow = a.direction === 'above' ? '≥' : '≤'
    return `${sym} ${arrow} ${fmtPrice(a.threshold, a.currency)}`
  }
  const mag = Math.abs(a.threshold)
  const verb = a.direction === 'above' ? 'sube' : a.direction === 'below' ? 'cae' : 'se mueve'
  const who = a.scope === 'holdings' ? 'Alguna de mis acciones' : sym
  return `${who} ${verb} ≥ ${mag}%`
}

export default function AlertsManager({ plan, prefill }) {
  const { items, events, loading, create, update, remove } = useAlerts()
  const canPct = plan?.can ? plan.can('alerts.pct_move') : false
  const alertsMax = plan?.limit ? plan.limit('alerts_max') : null
  const atLimit = alertsMax != null && items.length >= alertsMax

  const [showForm, setShowForm] = useState(!!prefill)
  const [form, setForm] = useState(() =>
    prefill
      ? { ...EMPTY_FORM, symbol: prefill.symbol || '', currency: prefill.currency || (String(prefill.symbol || '').endsWith('.BA') ? 'ARS' : 'USD') }
      : EMPTY_FORM
  )
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [upsell, setUpsell] = useState(false)

  const push = usePushNotifications()

  function setField(k, v) { setForm(f => ({ ...f, [k]: v })) }

  function pickKind(kind) {
    if (kind === 'pct_move' && !canPct) { setUpsell(true); return }
    setUpsell(false)
    setForm(f => ({
      ...f,
      kind,
      // defaults sensatos por tipo
      direction: kind === 'pct_move' ? 'below' : 'above',
      threshold: '',
    }))
  }

  async function submit(e) {
    e.preventDefault()
    setErr(null)
    const thr = parseFloat(form.threshold)
    if (!(thr > 0)) { setErr('Ingresá un valor mayor a 0.'); return }
    if (form.kind === 'price_target' && !form.symbol.trim()) { setErr('Elegí un ticker.'); return }
    if (form.kind === 'pct_move' && form.scope === 'ticker' && !form.symbol.trim()) { setErr('Elegí un ticker o "toda mi cartera".'); return }

    const payload = {
      kind: form.kind,
      scope: form.kind === 'pct_move' ? form.scope : 'ticker',
      symbol: (form.kind === 'pct_move' && form.scope === 'holdings') ? null : form.symbol.trim().toUpperCase(),
      direction: form.direction,
      threshold: thr,
      currency: form.currency,
      channel: form.channel,
      repeat: form.repeat,
    }
    setBusy(true)
    try {
      const res = await create(payload)
      setShowForm(false)
      setForm(EMPTY_FORM)
      // Si eligió push/ambos y no dio permiso todavía, lo invitamos.
      if ((form.channel === 'push' || form.channel === 'both') && push && !push.subscribed && push.supported) {
        push.subscribe?.()
      }
      if (res?.current_price != null && form.kind === 'price_target') {
        setErr(null)
      }
    } catch (e2) {
      if (e2?.status === 403 && e2?.payload?.upgrade) {
        setUpsell(true)
        setErr(e2.payload.error || 'Función de un plan superior.')
      } else {
        setErr(e2?.payload?.error || e2?.message || 'No se pudo crear la alerta.')
      }
    } finally {
      setBusy(false)
    }
  }

  const unseen = events.filter(e => !e.seen)

  return (
    <Panel padding="none">
      <header className="px-4 py-3 border-b border-line flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium text-ink-0">Alertas</h2>
          <p className="text-xs text-ink-3 mt-0.5">Te avisamos por push y/o email cuando algo pasa</p>
        </div>
        {!showForm && (
          <button
            onClick={() => { if (atLimit) { setUpsell(true) } else { setErr(null); setShowForm(true) } }}
            className="inline-flex items-center gap-1.5 text-xs bg-rendi-accent/10 hover:bg-rendi-accent/15 text-rendi-accent border border-rendi-accent/30 px-3 py-1.5 rounded-sm transition-colors"
          >
            <Plus size={14} /> Nueva alerta
          </button>
        )}
      </header>

      {/* Upsell Plus */}
      {upsell && (
        <div className="mx-4 mt-3 rounded-sm border border-rendi-accent/30 bg-rendi-accent/5 px-3 py-2.5 flex items-start gap-2.5">
          <Sparkles size={16} className="text-rendi-accent flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <div className="text-xs text-ink-1">
              {atLimit
                ? `Llegaste al máximo de alertas de tu plan (${alertsMax}).`
                : 'Las alertas de variación (%) sobre tu cartera son de Rendi Plus.'}
            </div>
            <Link to="/config?tab=planes" className="text-xs text-rendi-accent font-medium hover:underline mt-0.5 inline-block">
              Ver planes →
            </Link>
          </div>
          <button onClick={() => setUpsell(false)} className="text-ink-3 hover:text-ink-1"><X size={14} /></button>
        </div>
      )}

      {/* Formulario */}
      {showForm && (
        <form onSubmit={submit} className="px-4 py-3.5 border-b border-line/40 space-y-3">
          {/* Tipo */}
          <div className="flex gap-2">
            <TypeBtn active={form.kind === 'price_target'} onClick={() => pickKind('price_target')} icon={Target} label="Precio objetivo" />
            <TypeBtn active={form.kind === 'pct_move'} onClick={() => pickKind('pct_move')} icon={Zap} label="Variación %" locked={!canPct} />
          </div>

          {/* pct_move: scope */}
          {form.kind === 'pct_move' && (
            <div className="flex gap-2">
              <SegBtn active={form.scope === 'holdings'} onClick={() => setField('scope', 'holdings')} label="Toda mi cartera" />
              <SegBtn active={form.scope === 'ticker'} onClick={() => setField('scope', 'ticker')} label="Un activo" />
            </div>
          )}

          {/* Ticker (salvo pct_move + holdings) */}
          {!(form.kind === 'pct_move' && form.scope === 'holdings') && (
            <div className="flex gap-2">
              <input
                value={form.symbol}
                onChange={e => setField('symbol', e.target.value.toUpperCase())}
                placeholder="Ticker (ej. AAPL, MSFT.BA, GGAL)"
                className="flex-1 text-sm bg-bg-2 border border-line rounded-sm px-3 py-2 text-ink-0 placeholder:text-ink-3 focus:border-rendi-accent/50 outline-none"
              />
              {form.kind === 'price_target' && (
                <select value={form.currency} onChange={e => setField('currency', e.target.value)}
                  className="text-sm bg-bg-2 border border-line rounded-sm px-2 py-2 text-ink-1 outline-none">
                  <option value="USD">US$</option>
                  <option value="ARS">$ ARS</option>
                </select>
              )}
            </div>
          )}

          {/* Dirección + umbral */}
          <div className="flex gap-2 items-center">
            {form.kind === 'price_target' ? (
              <>
                <SegBtn active={form.direction === 'above'} onClick={() => setField('direction', 'above')} label="Sube a" icon={TrendingUp} />
                <SegBtn active={form.direction === 'below'} onClick={() => setField('direction', 'below')} label="Baja a" icon={TrendingDown} />
              </>
            ) : (
              <>
                <SegBtn active={form.direction === 'below'} onClick={() => setField('direction', 'below')} label="Cae" icon={TrendingDown} />
                <SegBtn active={form.direction === 'above'} onClick={() => setField('direction', 'above')} label="Sube" icon={TrendingUp} />
                <SegBtn active={form.direction === 'either'} onClick={() => setField('direction', 'either')} label="Cualquiera" />
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            <input
              type="number" step="any" min="0" value={form.threshold}
              onChange={e => setField('threshold', e.target.value)}
              placeholder={form.kind === 'price_target' ? 'Precio' : '% (ej. 10)'}
              className="flex-1 text-sm bg-bg-2 border border-line rounded-sm px-3 py-2 text-ink-0 placeholder:text-ink-3 focus:border-rendi-accent/50 outline-none"
            />
            <span className="text-xs text-ink-3 w-8">{form.kind === 'price_target' ? (form.currency === 'ARS' ? '$' : 'US$') : '%'}</span>
          </div>

          {/* Canal + repetición */}
          <div className="flex gap-2 flex-wrap">
            <SegBtn active={form.channel === 'both'} onClick={() => setField('channel', 'both')} label="Push + Email" />
            <SegBtn active={form.channel === 'push'} onClick={() => setField('channel', 'push')} label="Push" icon={Smartphone} />
            <SegBtn active={form.channel === 'email'} onClick={() => setField('channel', 'email')} label="Email" icon={Mail} />
          </div>
          <div className="flex gap-2">
            <SegBtn active={form.repeat === 'once'} onClick={() => setField('repeat', 'once')} label="Una vez" />
            <SegBtn active={form.repeat === 'always'} onClick={() => setField('repeat', 'always')} label="Siempre" />
          </div>

          {err && <div className="text-xs text-rendi-neg">{err}</div>}

          <div className="flex gap-2 pt-1">
            <button type="submit" disabled={busy}
              className="text-xs bg-rendi-accent text-white px-4 py-2 rounded-sm font-medium disabled:opacity-50">
              {busy ? 'Creando…' : 'Crear alerta'}
            </button>
            <button type="button" onClick={() => { setShowForm(false); setErr(null) }}
              className="text-xs text-ink-3 hover:text-ink-1 px-3 py-2">Cancelar</button>
          </div>
        </form>
      )}

      {/* Lista de alertas */}
      {loading ? (
        <div className="px-4 py-8 text-center text-xs text-ink-3">Cargando…</div>
      ) : items.length === 0 && !showForm ? (
        <div className="px-4 py-8 text-center">
          <Bell size={22} className="text-ink-3 mx-auto mb-2" strokeWidth={1.5} />
          <p className="text-xs text-ink-3">Todavía no tenés alertas. Creá la primera.</p>
        </div>
      ) : (
        <div>
          {items.map((a, i) => (
            <div key={a.id} className={`flex items-center gap-3 px-4 py-3 ${i > 0 ? 'border-t border-line/30' : ''}`}>
              <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${a.active ? 'bg-rendi-accent/10 text-rendi-accent' : 'bg-ink-3/10 text-ink-3'}`}>
                {a.kind === 'price_target' ? <Target size={15} /> : <Zap size={15} />}
              </div>
              <div className="flex-1 min-w-0">
                <div className={`text-sm ${a.active ? 'text-ink-0' : 'text-ink-3 line-through'}`}>{describeAlert(a)}</div>
                <div className="text-[11px] text-ink-3 mt-0.5">
                  {a.channel === 'both' ? 'Push + Email' : a.channel === 'push' ? 'Push' : 'Email'}
                  {' · '}{a.repeat === 'once' ? 'Una vez' : 'Siempre'}
                  {a.last_fired_at ? ' · disparada' : ''}
                </div>
              </div>
              <button
                onClick={() => update(a.id, { active: !a.active })}
                className={`text-[11px] px-2 py-1 rounded-sm border transition-colors ${a.active ? 'border-line text-ink-3 hover:text-ink-1' : 'border-rendi-accent/30 text-rendi-accent hover:bg-rendi-accent/10'}`}>
                {a.active ? 'Pausar' : 'Activar'}
              </button>
              <button onClick={() => remove(a.id)} className="text-ink-3 hover:text-rendi-neg p-1"><Trash2 size={15} /></button>
            </div>
          ))}
        </div>
      )}

      {/* Feed de disparos recientes */}
      {events.length > 0 && (
        <div className="border-t border-line/40">
          <div className="px-4 py-2 text-[11px] uppercase tracking-wider text-ink-3 flex items-center gap-2">
            Últimos avisos {unseen.length > 0 && <Pill tone="info">{unseen.length} nuevos</Pill>}
          </div>
          {events.slice(0, 6).map(ev => (
            <div key={ev.id} className="px-4 py-2 flex items-center gap-2.5 border-t border-line/20">
              <Check size={13} className="text-rendi-pos flex-shrink-0" />
              <div className="text-xs text-ink-2 flex-1 min-w-0 truncate">{ev.message}</div>
              <div className="text-[10px] text-ink-3 flex-shrink-0">{(ev.fired_at || '').slice(5, 10)}</div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

function TypeBtn({ active, onClick, icon: Icon, label, locked }) {
  return (
    <button type="button" onClick={onClick}
      className={`flex-1 flex items-center justify-center gap-1.5 text-xs px-3 py-2 rounded-sm border transition-colors ${active ? 'border-rendi-accent bg-rendi-accent/10 text-rendi-accent' : 'border-line text-ink-2 hover:border-line/80'}`}>
      <Icon size={14} /> {label}
      {locked && <Pill tone="info">Plus</Pill>}
    </button>
  )
}

function SegBtn({ active, onClick, label, icon: Icon }) {
  return (
    <button type="button" onClick={onClick}
      className={`inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-sm border transition-colors ${active ? 'border-rendi-accent bg-rendi-accent/10 text-rendi-accent' : 'border-line text-ink-2 hover:border-line/80'}`}>
      {Icon && <Icon size={13} />} {label}
    </button>
  )
}
// tokens: rendi-rendi-accent (acción), rendi-pos (ok), rendi-neg (error), bg-bg-2 (input)
