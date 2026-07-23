// RentaFijaSections — zona "Renta Fija" en Cartera (v2, mockup bonos-v2).
// ════════════════════════════════════════════════════════════════════════════
// Agrupa los bonos / letras / FCI de TODOS los brokers en secciones por
// (categoría, moneda). v2: cada bono es una CARD con lo importante a la vista
// (vencimiento, TIR, próximo cobro, P&L con cupones, % de capital recuperado)
// y se expande al detalle completo (BondDetailBody: ficha + timeline).
// Letras/FCI sin cronograma quedan como card simple.
//
// El borrado/restore reversible por sección se mantiene tal cual (v1).
// Las posiciones siguen viviendo en su broker — esto es presentación.
import { useState, useEffect } from 'react'
import { Layers, Trash2, RotateCcw, ChevronDown, ChevronUp, Pencil } from 'lucide-react'
import { api } from '../utils/api'
import { useToast } from './Toast'
import AssetLogo from './AssetLogo'
import { positionSection, sectionKey, sectionLabel, sortSectionKeys } from '../utils/sections'
import { getBondMeta } from '../utils/bondMeta'
import { nextPaymentForPosition, estimateYieldDetailed } from '../utils/bondSchedule'
import { usd, ars, pctSigned } from '../utils/format'
import { BondDetailBody } from './BondDetail'

const todayIso = () => new Date().toISOString().slice(0, 10)

// "2027-01-09" → "09 ene 27" (el slice MM-DD era ambiguo en es-AR).
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
const shortDate = (iso) => {
  if (!iso || iso.length < 10) return iso || ''
  return `${iso.slice(8, 10)} ${MESES[+iso.slice(5, 7) - 1] || ''} ${iso.slice(2, 4)}`
}

export default function RentaFijaSections({
  positions = [], valuePos, brokers = [], displayCurrency = 'USD', tcBlue = 1,
  onChanged, onEdit, onDelete,
  // v2 — plumbing del detalle (opcionales: sin ellos la card degrada con gracia)
  bondCashflowsByKey = null, pendingDatesByKey = null, openBondCashflow = null,
  tcMep = null, cerSeries = null, cerStale = false, isArsFor = null, priceFor = null,
}) {
  const toast = useToast()
  const [archived, setArchived] = useState([])
  const [busy, setBusy] = useState(null)
  const [open, setOpen] = useState({})       // colapsado por sección
  const [expanded, setExpanded] = useState({}) // detalle por posición

  async function loadArchived() {
    try { setArchived((await api.get('/sections/archived'))?.archived || []) }
    catch { /* noop */ }
  }
  useEffect(() => { loadArchived() }, [positions])

  // Agrupar las posiciones de renta fija por sección.
  const groups = {}
  for (const p of positions) {
    if (p.is_cash) continue
    if (!p.quantity) continue
    const sec = positionSection(p.asset_type, p.asset, p.currency)
    if (!sec) continue
    const key = sectionKey(sec.category, sec.currency)
    if (!groups[key]) groups[key] = { category: sec.category, currency: sec.currency, rows: [] }
    groups[key].rows.push(p)
  }
  const keys = sortSectionKeys(Object.keys(groups))

  if (keys.length === 0 && archived.length === 0) return null

  const fmtMoney = (usdVal) => {
    const n = displayCurrency === 'ARS' ? usdVal * tcBlue : usdVal
    const sym = displayCurrency === 'ARS' ? '$' : 'US$'
    return sym + Math.round(n).toLocaleString('es-AR')
  }

  // ── Chips de zona: cobrado este año + próximos 30 días (≈USD, informativo) ──
  const year = todayIso().slice(0, 4)
  const today = todayIso()
  const in30 = (() => { const d = new Date(); d.setDate(d.getDate() + 30); return d.toISOString().slice(0, 10) })()
  let cobradoYearUsd = 0
  let proximos30Usd = 0
  let proximos30Count = 0
  for (const key of keys) {
    for (const p of groups[key].rows) {
      const ccyArs = isArsFor ? isArsFor(p) : false
      const summary = bondCashflowsByKey?.get(`${p.broker}:${p.asset}`)
      if (summary?.ops) {
        for (const o of summary.ops) {
          if ((o.date || '').startsWith(year)) {
            const amt = +o.pnl_usd || 0   // monto en moneda del broker
            cobradoYearUsd += ccyArs ? amt / (tcBlue || 1) : amt
          }
        }
      }
      const next = p.quantity ? nextPaymentForPosition(p.asset, p.quantity, today) : null
      if (next && next.date <= in30) {
        proximos30Count += 1
        const meta = getBondMeta(p.asset)
        proximos30Usd += (meta?.currency === 'ARS') ? next.total / (tcBlue || 1) : next.total
      }
    }
  }

  async function wipeSection(key, label, count) {
    if (!confirm(`¿Eliminar la sección "${label}" (${count} ${count === 1 ? 'posición' : 'posiciones'})?\n\nSe puede restaurar después. No toca el broker ni el resto de tus tenencias.`)) return
    setBusy(key)
    try {
      await api.post('/sections/archive', { section: key })
      toast.push(`"${label}" eliminada. Podés restaurarla.`, { type: 'success' })
      onChanged && onChanged()
      loadArchived()
    } catch (e) {
      toast.push('No se pudo eliminar: ' + e.message, { type: 'error' })
    } finally { setBusy(null) }
  }

  async function restore(a) {
    setBusy('r' + a.id)
    try {
      await api.post('/sections/restore', { archive_id: a.id })
      toast.push(`"${a.label}" restaurada.`, { type: 'success' })
      onChanged && onChanged()
      loadArchived()
    } catch (e) {
      toast.push('No se pudo restaurar: ' + e.message, { type: 'error' })
    } finally { setBusy(null) }
  }

  return (
    <div className="mt-8">
      {/* Header de zona con chips */}
      <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
        <div className="flex items-center gap-2">
          <Layers size={15} className="text-ink-2" strokeWidth={1.5} />
          <h3 className="text-[15px] font-semibold leading-tight text-ink-0">Renta Fija</h3>
          <span className="text-ink-3 text-xs">· {keys.length} {keys.length === 1 ? 'sección' : 'secciones'}</span>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {cobradoYearUsd > 0.01 && (
            <span className="text-[12px] text-ink-2 bg-bg-1 border border-line rounded-full px-2.5 py-1 tabular">
              Cobrado {year} <b className="text-rendi-pos font-semibold">~US$ {usd(cobradoYearUsd)}</b>
            </span>
          )}
          {proximos30Count > 0 && (
            <span className="text-[12px] font-medium text-data-cyan bg-data-cyan/10 rounded-full px-2.5 py-1 tabular">
              Próximos 30 días · {proximos30Count} {proximos30Count === 1 ? 'cobro' : 'cobros'} ~US$ {usd(proximos30Usd)}
            </span>
          )}
        </div>
      </div>

      {keys.map(key => {
        const g = groups[key]
        const label = sectionLabel(g.category, g.currency)
        const isOpen = open[key] !== false   // default abierto
        let secValue = 0, secInv = 0
        const valued = g.rows.map(p => {
          const v = valuePos ? valuePos(p) : { valueUsd: 0, investedUsd: 0, pnlUsd: 0, pnlPct: 0 }
          secValue += v.valueUsd || 0
          secInv += v.investedUsd || 0
          return { p, v }
        })
        const secPnl = secValue - secInv
        const secPct = secInv > 0 ? secPnl / secInv : 0
        return (
          <div key={key} className="mb-4">
            <div className="flex items-center justify-between gap-3 px-1 py-1.5">
              <button onClick={() => setOpen(o => ({ ...o, [key]: !isOpen }))}
                className="flex items-center gap-1.5 text-[13px] font-semibold text-ink-1 hover:text-ink-0 transition">
                {isOpen ? <ChevronDown size={13} /> : <ChevronUp size={13} className="rotate-90" />}
                {label} <span className="text-ink-3 text-xs font-normal">· {g.rows.length}</span>
              </button>
              <div className="flex items-center gap-3">
                <span className="text-[12px] tabular text-ink-0 font-semibold">{fmtMoney(secValue)}</span>
                <span className={`text-[11px] font-medium px-1.5 py-0.5 rounded-full tabular ${secPnl >= 0 ? 'bg-rendi-pos/10 text-rendi-pos' : 'bg-rendi-neg/10 text-rendi-neg'}`}>{pctSigned(secPct)}</span>
                <button onClick={() => wipeSection(key, label, g.rows.length)} disabled={busy === key}
                  className="text-ink-3 hover:text-rendi-neg transition disabled:opacity-40"
                  title={`Eliminar la sección ${label} (reversible)`}>
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
            {isOpen && valued.map(({ p, v }) => (
              <BondCardRow
                key={p.id}
                p={p} v={v}
                fmtMoney={fmtMoney}
                summary={bondCashflowsByKey?.get(`${p.broker}:${p.asset}`)}
                pendingDates={pendingDatesByKey?.get(`${p.broker}:${p.asset}`)}
                isArs={isArsFor ? isArsFor(p) : false}
                isArsDisp={displayCurrency === 'ARS'}
                tcBlue={tcBlue}
                price={priceFor ? priceFor(p) : null}
                tcMep={tcMep} cerSeries={cerSeries} cerStale={cerStale}
                expanded={!!expanded[p.id]}
                onToggle={() => setExpanded(e => ({ ...e, [p.id]: !e[p.id] }))}
                onEdit={onEdit} onDelete={onDelete}
                openBondCashflow={openBondCashflow}
              />
            ))}
          </div>
        )
      })}

      {archived.length > 0 && (
        <div className="mt-3 text-xs text-ink-3">
          <div className="mb-1.5 label-mono">Secciones eliminadas</div>
          <div className="flex flex-col gap-1.5">
            {archived.map(a => (
              <div key={a.id} className="flex items-center justify-between bg-bg-2/30 border border-line/60 rounded-lg px-3 py-1.5">
                <span className="text-ink-2">{a.label} <span className="text-ink-3">· {a.count} {a.count === 1 ? 'posición' : 'posiciones'}</span></span>
                <button onClick={() => restore(a)} disabled={busy === 'r' + a.id}
                  className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md bg-bg-2 hover:bg-bg-3 border border-line text-ink-1 transition disabled:opacity-40">
                  <RotateCcw size={11} /> Restaurar
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── BondCardRow ─────────────────────────────────────────────────────────────
// Card de un bono/letra/FCI: identidad + métricas clave + próximo cobro +
// barra de capital recuperado + expansión al detalle completo.
function BondCardRow({
  p, v, fmtMoney, summary, pendingDates, isArs, isArsDisp, tcBlue, price, tcMep, cerSeries, cerStale,
  expanded, onToggle, onEdit, onDelete, openBondCashflow,
}) {
  const meta = getBondMeta(p.asset)
  const moneyLabel = isArs ? 'ARS' : 'USD'
  const fmt = isArs ? ars : usd
  const hasDetail = !!(meta || (summary?.ops?.length > 0))

  // Próximo cobro (chip cyan) — solo bonos con cronograma.
  const next = (meta?.maturity && p.quantity) ? nextPaymentForPosition(p.asset, p.quantity, todayIso()) : null

  // TIR a precio de hoy (misma convención que el detalle; cross-ccy vía MEP).
  let tir = null
  if (meta?.maturity && price != null && price > 0) {
    const bondCcy = meta.currency || 'USD'
    const brokerCcy = isArs ? 'ARS' : 'USD'
    let pBond = price
    if (bondCcy !== brokerCcy && tcMep) pBond = bondCcy === 'USD' ? price / tcMep : price * tcMep
    else if (bondCcy !== brokerCcy) pBond = null
    if (pBond != null) {
      const cerOpts = (meta.type === 'cer' && cerSeries && Object.keys(cerSeries).length > 0) ? { cerSeries } : {}
      tir = estimateYieldDetailed(p.asset, pBond * 100, todayIso(), cerOpts)?.ytm ?? null
    }
  }

  // P&L "con cupones": MtM (USD, de valuePos) + aporte realizado de cobranzas.
  const pnlAdjUsd = (v.pnlUsd || 0) + (summary?.pnlContributionUsd || 0)
  const investedUsd = v.investedUsd || 0
  const pnlAdjPct = investedUsd > 0 ? pnlAdjUsd / investedUsd : (v.pnlPct || 0)
  const hasCobros = (summary?.total || 0) > 0

  // Capital recuperado (moneda del broker, mismo criterio que el detalle).
  const recovery = (p.invested || 0) > 0 ? (summary?.total || 0) / p.invested : 0

  const tags = []
  if (meta?.currency) tags.push({ t: meta.currency, cls: meta.currency === 'ARS' ? 'bg-rendi-warn/10 text-rendi-warn' : 'bg-rendi-pos/10 text-rendi-pos' })
  if (meta?.type === 'cer') tags.push({ t: 'CER', cls: 'bg-data-cyan/10 text-data-cyan' })
  if (meta?.governingLaw) tags.push({ t: meta.governingLaw === 'Argentina' ? 'Ley AR' : 'Ley NY', cls: 'bg-bg-2 text-ink-2 border border-line/60' })

  return (
    <div className="bg-bg-1 border border-line rounded-xl px-4 py-3.5 mb-2.5">
      <div className="flex items-center gap-3 flex-wrap">
        <AssetLogo asset={p.asset} size={32} />
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[14px] font-bold text-ink-0 tabular">{p.asset}</span>
            {tags.map((tg, i) => (
              <span key={i} className={`text-[10px] font-bold rounded-full px-2 py-0.5 ${tg.cls}`}>{tg.t}</span>
            ))}
          </div>
          <div className="text-[11px] text-ink-3">
            {meta?.issuer ? `${meta.issuer} · ` : ''}{meta?.maturity ? `vence ${meta.maturity} · ` : ''}{p.broker}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-4 flex-wrap justify-end">
          <div className="text-right">
            <div className="text-[10.5px] text-ink-3 font-medium">Nominales</div>
            <div className="text-[13px] font-semibold text-ink-0 tabular">{(p.quantity || 0).toLocaleString('es-AR')}</div>
          </div>
          <div className="text-right">
            <div className="text-[10.5px] text-ink-3 font-medium">Valor</div>
            <div className="text-[13px] font-semibold text-ink-0 tabular">{v.valueUsd != null ? fmtMoney(v.valueUsd) : '—'}</div>
          </div>
          {tir != null && (
            <div className="text-right">
              <div className="text-[10.5px] text-ink-3 font-medium">{meta?.type === 'cer' ? 'TIR real' : 'TIR'}</div>
              <div className="text-[13px] font-bold text-data-violet tabular">{pctSigned(tir)}</div>
            </div>
          )}
          {next && (() => {
            // El cronograma paga en la moneda del BONO; el chip lo muestra en el
            // riel del toggle global (igual que el detalle y el resto de Cartera).
            const bondIsArs = (meta?.currency || 'USD') === 'ARS'
            const amt = bondIsArs === isArsDisp
              ? next.total
              : bondIsArs ? (tcBlue ? next.total / tcBlue : next.total) : next.total * (tcBlue || 1)
            return (
              <span className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-data-cyan bg-data-cyan/10 rounded-full px-2.5 py-1 tabular">
                Cobrás {shortDate(next.date)} ~{isArsDisp ? 'ARS' : 'USD'} {(isArsDisp ? ars : usd)(amt)}
              </span>
            )
          })()}
          <div className="text-right">
            <div className={`text-[13px] font-bold tabular ${pnlAdjUsd >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
              {pnlAdjUsd >= 0 ? '+' : '−'}{fmtMoney(Math.abs(pnlAdjUsd)).replace('-', '')}
            </div>
            <span className={`inline-block text-[10px] font-bold rounded-full px-1.5 py-0.5 tabular ${pnlAdjUsd >= 0 ? 'bg-rendi-pos/10 text-rendi-pos' : 'bg-rendi-neg/10 text-rendi-neg'}`}>
              {pctSigned(pnlAdjPct)}{hasCobros ? ' con cupones' : ''}
            </span>
          </div>
          <div className="flex items-center gap-1">
            {onEdit && (
              <button onClick={() => onEdit(p)} title="Editar posición"
                className="p-1.5 rounded-md text-ink-3 hover:text-ink-0 hover:bg-bg-2 transition">
                <Pencil size={13} />
              </button>
            )}
            {onDelete && (
              <button onClick={() => onDelete(p.id)} title="Eliminar posición"
                className="p-1.5 rounded-md text-ink-3 hover:text-rendi-neg hover:bg-bg-2 transition">
                <Trash2 size={13} />
              </button>
            )}
            {hasDetail && (
              <button onClick={onToggle} title={expanded ? 'Ocultar detalle' : 'Ver ficha, cronograma y cobranzas'}
                className="p-1.5 rounded-md text-ink-3 hover:text-ink-0 hover:bg-bg-2 transition">
                {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
              </button>
            )}
          </div>
        </div>
      </div>

      {recovery > 0.001 && (
        <div className="flex items-center gap-2.5 mt-3">
          <div className="flex-1 h-1.5 rounded-full bg-bg-2 overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${Math.min(100, recovery * 100)}%`, background: 'linear-gradient(90deg, #9d8cff, #4bd0e8)' }} />
          </div>
          <span className="text-[10.5px] text-ink-3 tabular whitespace-nowrap">
            <b className="text-ink-1">{Math.round(recovery * 100)}%</b> del capital recuperado · {moneyLabel} {fmt(summary.total)}
          </span>
        </div>
      )}

      {expanded && hasDetail && (
        <div className="mt-4 pt-4 border-t border-dashed border-line">
          <BondDetailBody
            p={p}
            summary={summary}
            isARS={isArs}
            isArsDisp={isArsDisp}
            tcBlue={tcBlue}
            currentPrice={price}
            tcMep={tcMep}
            cerSeries={cerSeries}
            cerStale={cerStale}
            pendingDates={pendingDates}
            onAddCoupon={() => openBondCashflow && openBondCashflow(p, 'coupon')}
            onAddAmortization={() => openBondCashflow && openBondCashflow(p, 'amortization')}
          />
        </div>
      )}
    </div>
  )
}
