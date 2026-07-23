// AlertsManager — gestor de alertas personalizadas (vive en Config › Notificaciones).
// Dos tipos:
//   • Precio objetivo: "avisame cuando AAPL llegue a US$200" (todos los planes).
//   • Variación %: "avisame cuando alguna de mis acciones caiga 10%" (Plus+).
// El backend gatea por cantidad y por capacidad; acá reflejamos el gate en la UI
// (el tipo % aparece bloqueado con badge Plus para Free) y mostramos el upsell si
// el POST devuelve 403.
import { useState, useRef, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import {
  Bell, Plus, Trash2, TrendingUp, TrendingDown, Target, Mail, Smartphone,
  X, Check, Zap, Sparkles, Search,
} from 'lucide-react'
import Panel from '../Panel'
import Pill from '../Pill'
import AssetResultRow from '../AssetResultRow'
import { usePushNotifications } from '../../hooks/usePushNotifications'
import { useAlerts } from '../../hooks/useAlerts'
import { POPULAR_TICKERS } from '../../utils/tickers'
import { api } from '../../utils/api'

const EMPTY_FORM = {
  kind: 'price_target',
  scope: 'ticker',
  symbol: '',
  currency: 'USD',
  direction: 'above',
  threshold: '',      // price_target
  up_pct: '',         // pct_move: sube ≥ up_pct%
  down_pct: '',       // pct_move: cae ≥ down_pct%
  baseline: 'set_price', // pct_move un-activo: 'set_price' (desde ahora) | 'prev_close' (en el día)
  channel: 'both',
  repeat: 'once',
}

// Parseo tolerante al formato argentino: coma decimal + punto de miles, y también
// formato US. '0,01'→0.01 · '10,5'→10.5 · '9.000'→9000 · '380.5'→380.5 · '1.234,56'→1234.56
function parseNum(v) {
  let s = String(v == null ? '' : v).trim().replace(/\s/g, '')
  if (!s) return NaN
  if (s.includes(',')) {
    s = s.replace(/\./g, '').replace(',', '.')     // coma = decimal (puntos = miles)
  } else if (/^\d{1,3}(\.\d{3})+$/.test(s)) {
    s = s.replace(/\./g, '')                        // solo puntos en grupos de 3 = miles
  }
  return parseFloat(s)
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
  const who = a.scope === 'holdings' ? 'Alguna de mis acciones' : sym
  const parts = []
  if (a.up_pct != null) parts.push(`sube ≥ ${Math.abs(a.up_pct)}%`)
  if (a.down_pct != null) parts.push(`cae ≥ ${Math.abs(a.down_pct)}%`)
  return `${who}: ${parts.join(' o ') || 'se mueve'}`
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
  const [warnSym, setWarnSym] = useState(null)   // ticker que no resolvió precio
  const [currentPrice, setCurrentPrice] = useState(null)  // precio actual del ticker elegido

  const push = usePushNotifications()

  // Trae el precio actual al elegir/tipear un ticker (debounce) — contexto para
  // el usuario y ancla del modo "Desde ahora".
  const priceSym = (form.symbol || '').trim().toUpperCase()
  const priceCcy = priceSym.endsWith('.BA') ? 'ARS' : 'USD'
  useEffect(() => {
    if (!priceSym || (form.kind === 'pct_move' && form.scope === 'holdings')) {
      setCurrentPrice(null); return
    }
    let cancelled = false
    const t = setTimeout(async () => {
      try {
        const res = await api.get(`/prices?symbols=${encodeURIComponent(priceSym)}`)
        if (!cancelled) setCurrentPrice(res && res[priceSym] != null ? res[priceSym] : null)
      } catch { if (!cancelled) setCurrentPrice(null) }
    }, 450)
    return () => { cancelled = true; clearTimeout(t) }
  }, [priceSym, form.kind, form.scope])

  function setField(k, v) { setForm(f => ({ ...f, [k]: v })) }

  function pickKind(kind) {
    if (kind === 'pct_move' && !canPct) { setUpsell(true); return }
    setUpsell(false)
    setForm(f => ({ ...f, kind, direction: 'above', threshold: '', up_pct: '', down_pct: '' }))
  }

  async function submit(e) {
    e.preventDefault()
    setErr(null)
    const isPct = form.kind === 'pct_move'
    const up = parseNum(form.up_pct), down = parseNum(form.down_pct)
    const thr = parseNum(form.threshold)

    if (isPct) {
      if (!(up > 0) && !(down > 0)) { setErr('Poné al menos un umbral: sube y/o baja X%.'); return }
      if (form.scope === 'ticker' && !form.symbol.trim()) { setErr('Elegí un ticker o "toda mi cartera".'); return }
    } else {
      if (!(thr > 0)) { setErr('Ingresá el precio objetivo.'); return }
      if (!form.symbol.trim()) { setErr('Elegí un ticker.'); return }
    }

    const payload = {
      kind: form.kind,
      scope: isPct ? form.scope : 'ticker',
      symbol: (isPct && form.scope === 'holdings') ? null : form.symbol.trim().toUpperCase(),
      channel: form.channel,
      repeat: form.repeat,
      ...(isPct
        ? { up_pct: up > 0 ? up : undefined, down_pct: down > 0 ? down : undefined,
            baseline: form.scope === 'ticker' ? form.baseline : 'prev_close' }
        : { direction: form.direction, threshold: thr, currency: form.currency }),
    }
    setBusy(true)
    try {
      const res = await create(payload)
      setShowForm(false)
      // Ticker que no resolvió precio (typo / símbolo inexistente) → avisamos.
      setWarnSym(res && res.resolved === false && payload.symbol ? payload.symbol : null)
      setForm(EMPTY_FORM)
      // Si eligió push/ambos y no dio permiso todavía, lo invitamos.
      if ((form.channel === 'push' || form.channel === 'both') && push && !push.subscribed && push.supported) {
        push.subscribe?.()
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

      {/* Aviso: el ticker no resolvió precio (posible typo) */}
      {warnSym && (
        <div className="mx-4 mt-3 rounded-sm border border-rendi-warn/30 bg-rendi-warn/5 px-3 py-2.5 flex items-start gap-2.5">
          <div className="flex-1 min-w-0 text-xs text-ink-1">
            No encontramos el precio de <span className="font-medium">{displaySym(warnSym)}</span> ahora.
            Si el símbolo es correcto, la alerta va a funcionar igual; si fue un error, borrala y creala de nuevo.
          </div>
          <button onClick={() => setWarnSym(null)} className="text-ink-3 hover:text-ink-1"><X size={14} /></button>
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
              <TickerCombobox
                value={form.symbol}
                onChange={v => setField('symbol', v)}
                placeholder="Ticker (ej. AAPL, MSFT.BA, GGAL)"
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

          {/* Precio actual del ticker elegido */}
          {currentPrice != null && priceSym && !(form.kind === 'pct_move' && form.scope === 'holdings') && (
            <p className="text-[11px] text-ink-2">
              {displaySym(priceSym)} · <span className="font-medium text-ink-1">{fmtPrice(currentPrice, priceCcy)}</span> ahora
              {form.kind === 'pct_move' && form.scope === 'ticker' && form.baseline === 'set_price' && parseNum(form.up_pct) > 0 &&
                ` → objetivo ${fmtPrice(currentPrice * (1 + parseNum(form.up_pct) / 100), priceCcy)} (+${parseNum(form.up_pct)}%)`}
            </p>
          )}

          {/* pct_move un-activo: ¿desde dónde medimos el %? */}
          {form.kind === 'pct_move' && form.scope === 'ticker' && (
            <div>
              <div className="flex gap-2">
                <SegBtn active={form.baseline === 'set_price'} onClick={() => setField('baseline', 'set_price')} label="Desde ahora" />
                <SegBtn active={form.baseline === 'prev_close'} onClick={() => setField('baseline', 'prev_close')} label="En el día" />
              </div>
              <p className="text-[11px] text-ink-3 mt-1">
                {form.baseline === 'set_price'
                  ? 'Mide el % desde el precio de ahora. Al reactivar, se re-ancla (te avisa del próximo tramo).'
                  : 'Mide el movimiento del día (vs el cierre de ayer). Se resetea cada jornada.'}
              </p>
            </div>
          )}

          {/* Umbral */}
          {form.kind === 'price_target' ? (
            <>
              <div className="flex gap-2 items-center">
                <SegBtn active={form.direction === 'above'} onClick={() => setField('direction', 'above')} label="Sube a" icon={TrendingUp} />
                <SegBtn active={form.direction === 'below'} onClick={() => setField('direction', 'below')} label="Baja a" icon={TrendingDown} />
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="text" inputMode="decimal" value={form.threshold}
                  onChange={e => setField('threshold', e.target.value)}
                  placeholder="Precio"
                  className="flex-1 text-sm bg-bg-2 border border-line rounded-sm px-3 py-2 text-ink-0 placeholder:text-ink-3 focus:border-rendi-accent/50 outline-none"
                />
                <span className="text-xs text-ink-3 w-8">{form.currency === 'ARS' ? '$' : 'US$'}</span>
              </div>
            </>
          ) : (
            // pct_move: umbrales asimétricos en una sola alerta. Completá uno o ambos.
            <div className="space-y-2">
              <p className="text-[11px] text-ink-3">Completá uno o los dos (podés poner valores distintos)</p>
              <PctInput icon={TrendingUp} label="Sube más de" value={form.up_pct} onChange={v => setField('up_pct', v)} />
              <PctInput icon={TrendingDown} label="Baja más de" value={form.down_pct} onChange={v => setField('down_pct', v)} />
            </div>
          )}

          {/* Canal + repetición */}
          <div className="flex gap-2 flex-wrap">
            <SegBtn active={form.channel === 'both'} onClick={() => setField('channel', 'both')} label="Push + Email" />
            <SegBtn active={form.channel === 'push'} onClick={() => setField('channel', 'push')} label="Push" icon={Smartphone} />
            <SegBtn active={form.channel === 'email'} onClick={() => setField('channel', 'email')} label="Email" icon={Mail} />
          </div>
          <p className="text-[11px] text-ink-3 -mt-1">
            El email siempre llega. El push es un extra para desktop y Android
            {push && push.supported === false ? ' — en iPhone, agregá Rendi a tu inicio' : ''}.
          </p>
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
          <div className="px-4 py-2 text-[12.5px] text-ink-3 flex items-center gap-2 font-medium">
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

// Combobox de ticker con las mismas tarjetas (logo + ticker + nombre + badge de
// tipo) que el resto de los buscadores de la app. Sigue permitiendo tipear un
// ticker manual que no esté en la lista (las alertas aceptan cualquier símbolo).
function TickerCombobox({ value, onChange, placeholder }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef(null)

  const results = useMemo(() => {
    const q = (value || '').trim().toUpperCase()
    if (!q) return POPULAR_TICKERS.slice(0, 8)
    const starts = [], contains = []
    for (const t of POPULAR_TICKERS) {
      const s = t.symbol.toUpperCase()
      if (s.startsWith(q)) starts.push(t)
      else if (s.includes(q) || (t.name || '').toUpperCase().includes(q)) contains.push(t)
    }
    return [...starts, ...contains].slice(0, 8)
  }, [value])

  useEffect(() => {
    function onDoc(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  function choose(sym) {
    onChange(sym)
    setOpen(false)
  }

  return (
    <div ref={wrapRef} className="relative flex-1">
      <div className="relative">
        <Search size={14} strokeWidth={1.75} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3 pointer-events-none" />
        <input
          value={value}
          onChange={e => { onChange(e.target.value.toUpperCase()); setOpen(true) }}
          onFocus={() => setOpen(true)}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck="false"
          className="w-full text-sm bg-bg-2 border border-line rounded-sm pl-8 pr-3 py-2 text-ink-0 placeholder:text-ink-3 focus:border-rendi-accent/50 outline-none"
        />
      </div>
      {open && results.length > 0 && (
        <div className="absolute z-30 left-0 right-0 mt-1 bg-white dark:bg-bg-2 border border-line rounded-lg shadow-2xl overflow-hidden max-h-72 overflow-y-auto">
          {results.map(t => (
            <AssetResultRow
              key={t.symbol}
              symbol={t.symbol}
              name={t.name}
              type={t.type}
              onClick={() => choose(t.symbol)}
            />
          ))}
        </div>
      )}
    </div>
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

function PctInput({ icon: Icon, label, value, onChange }) {
  return (
    <div className="flex items-center gap-2">
      <span className="inline-flex items-center gap-1.5 text-xs text-ink-2 w-28 flex-shrink-0">
        <Icon size={13} /> {label}
      </span>
      <input
        type="text" inputMode="decimal" value={value}
        onChange={e => onChange(e.target.value)}
        placeholder="—"
        className="flex-1 text-sm bg-bg-2 border border-line rounded-sm px-3 py-2 text-ink-0 placeholder:text-ink-3 focus:border-rendi-accent/50 outline-none"
      />
      <span className="text-xs text-ink-3 w-6">%</span>
    </div>
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
