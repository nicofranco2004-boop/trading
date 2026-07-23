// BondDetail — detalle expandible de un bono (v2, mockup bonos-v2 aprobado).
// ════════════════════════════════════════════════════════════════════════════
// Antes vivía inline en Positions.jsx como <BondDetailRow> (grilla mono 10px).
// v2: tres columnas legibles (Ficha / Tu inversión / Rendimiento) + el
// cronograma como TIMELINE (verde = cobrado, ámbar = venció sin confirmar,
// gris = futuro estimado) + historial colapsable.
//
// Dos exports:
//   • BondDetailBody — div-based, reusable (tablas de broker Y zona Renta Fija).
//   • BondDetailRow  — wrapper <tr colSpan> para las tablas por broker.
//
// Misma data de siempre: bondMeta + bondSchedule + summary (bondCashflowsByKey).
// `pendingDates` (Set de fechas ISO) viene del detector de pendientes — marca
// los puntos ámbar del timeline.

import { useState } from 'react'
import { Coins, Layers as LayersIcon, ChevronDown, ChevronUp } from 'lucide-react'
import { usd, ars, pctSigned } from '../utils/format'
import { getBondMeta, formatBondType, formatCouponLabel, formatCouponTooltip } from '../utils/bondMeta'
import {
  generateSchedule, getRemainingPayments, estimateYieldDetailed, nextPaymentForPosition,
} from '../utils/bondSchedule'

const DATE_TOLERANCE_DAYS = 14  // mismo criterio que pendingCashflows.js

function diffDaysAbs(a, b) {
  const pa = a.slice(0, 10).split('-').map(Number)
  const pb = b.slice(0, 10).split('-').map(Number)
  return Math.abs(Math.round((Date.UTC(pb[0], pb[1] - 1, pb[2]) - Date.UTC(pa[0], pa[1] - 1, pa[2])) / 86400000))
}

export function BondDetailBody({
  p, summary, isARS, currentPrice, tcMep, cerSeries, cerStale,
  onAddCoupon, onAddAmortization, pendingDates = null,
  isArsDisp = null, tcBlue = null,
}) {
  const meta = getBondMeta(p.asset)
  // La moneda de DISPLAY sigue el toggle global (isArsDisp) cuando viene —
  // igual que el resto de Cartera (toggle `932bebf`). Sin la prop, cae a la
  // moneda nativa del broker (isARS). Los montos del summary son NATIVOS del
  // broker → `toDisp` los lleva al riel elegido, prefiriendo la pata USD
  // exacta del summary sobre re-dividir por tcBlue cuando está disponible.
  const dispArs = isArsDisp == null ? isARS : isArsDisp
  const moneyLabel = dispArs ? 'ARS' : 'USD'
  const fmt = dispArs ? ars : usd
  const toDisp = (nativeAmt, usdAmt = null) => {
    if (nativeAmt == null) return nativeAmt
    if (isARS === dispArs) return nativeAmt
    if (isARS && !dispArs) return usdAmt != null ? usdAmt : (tcBlue ? nativeAmt / tcBlue : nativeAmt)
    return nativeAmt * (tcBlue || 1)  // broker USD, vista ARS
  }
  const invested = p.invested || 0
  const coupons = summary?.coupons || 0
  const amortizations = summary?.amortizations || 0
  const total = summary?.total || 0
  const totalUsd = summary?.totalUsd || 0
  const pnlContribution = summary?.pnlContribution || 0
  const hasLegacyOps = summary?.hasLegacyOps || false
  const ops = summary?.ops || []
  const recoveryPct = invested > 0 ? (total / invested) : 0
  const amortRealizedGain = pnlContribution - coupons
  // Versiones en el riel de display (las nativas quedan para gates de signo).
  const couponsUsd = summary?.couponsUsd || 0
  const amortizationsUsd = summary?.amortizationsUsd || 0
  const pnlContributionUsd = summary?.pnlContributionUsd || 0
  const totalDisp = toDisp(total, totalUsd)
  const couponsDisp = toDisp(coupons, couponsUsd)
  const amortizationsDisp = toDisp(amortizations, amortizationsUsd)
  const pnlContributionDisp = toDisp(pnlContribution, pnlContributionUsd)
  const amortRealizedGainDisp = pnlContributionDisp - couponsDisp

  // ── Schedule + TIR + próximo pago (misma lógica que la v1) ────────────────
  const today = new Date().toISOString().slice(0, 10)
  const cerOpts = (meta?.type === 'cer' && cerSeries && Object.keys(cerSeries).length > 0)
    ? { cerSeries }
    : {}
  const fullSchedule = generateSchedule(p.asset, cerOpts)
  const remaining = fullSchedule ? getRemainingPayments(p.asset, today, cerOpts) : null

  const bondCurrency = meta?.currency || 'USD'
  const brokerCurrency = isARS ? 'ARS' : 'USD'
  const isCrossCurrency = bondCurrency !== brokerCurrency
  // Los flujos del CRONOGRAMA (próximo pago, timeline futuro) están en la
  // moneda del BONO — los llevamos al riel de display igual que el resto.
  const bondIsArs = bondCurrency === 'ARS'
  const schedToDisp = (amt) => {
    if (amt == null) return amt
    if (bondIsArs === dispArs) return amt
    if (bondIsArs && !dispArs) return tcBlue ? amt / tcBlue : amt
    return amt * (tcBlue || 1)
  }
  let priceInBondCurrency = currentPrice
  let priceConversion = null
  if (isCrossCurrency && currentPrice != null && currentPrice > 0) {
    if (bondCurrency === 'USD' && brokerCurrency === 'ARS' && tcMep) {
      priceInBondCurrency = currentPrice / tcMep
      priceConversion = { from: 'ARS', to: 'USD', rate: tcMep, type: 'MEP' }
    } else if (bondCurrency === 'ARS' && brokerCurrency === 'USD' && tcMep) {
      priceInBondCurrency = currentPrice * tcMep
      priceConversion = { from: 'USD', to: 'ARS', rate: tcMep, type: 'MEP' }
    }
  }
  const pricePer100Clean = priceInBondCurrency != null && priceInBondCurrency > 0
    ? priceInBondCurrency * 100
    : null
  const yieldDetail = pricePer100Clean != null
    ? estimateYieldDetailed(p.asset, pricePer100Clean, today, cerOpts)
    : null
  const yieldEstimate = yieldDetail?.ytm ?? null
  const nextPay = p.quantity ? nextPaymentForPosition(p.asset, p.quantity, today) : null

  // CER: factor actual (contexto del ajuste por inflación).
  function cerLocfLookup(date) {
    if (!cerSeries || !date) return null
    if (cerSeries[date] != null) return cerSeries[date]
    const dates = Object.keys(cerSeries).sort()
    let best = null
    for (const d of dates) {
      if (d <= date) best = d
      else break
    }
    return best ? cerSeries[best] : null
  }
  const cerToday = meta?.type === 'cer' ? cerLocfLookup(today) : null
  const cerBase = meta?.type === 'cer' && meta.cerEmissionDate ? cerLocfLookup(meta.cerEmissionDate) : null
  const cerFactorToday = (cerToday != null && cerBase != null && cerBase > 0) ? cerToday / cerBase : null

  // ── Timeline: pasado (cobrado ✓ / pendiente ! / sin registro) + futuro ────
  // Mostramos los últimos 3 vencimientos + los próximos 4 + "+N más".
  const qty = p.quantity || 0
  const timeline = []
  if (fullSchedule) {
    const past = fullSchedule.filter(pmt => pmt.date <= today && (pmt.total || 0) > 0).slice(-3)
    for (const pmt of past) {
      const op = ops.find(o => diffDaysAbs(o.date, pmt.date) <= DATE_TOLERANCE_DAYS)
      const status = op ? 'done' : (pendingDates?.has(pmt.date) ? 'pend' : 'off')
      timeline.push({
        date: pmt.date,
        amount: op ? (+op.pnl_usd || 0) : (qty > 0 ? pmt.total * qty / 100 : null),
        approx: !op,
        status,
        kind: pmt.amort > 0 && pmt.coupon > 0 ? 'cupón + amort' : pmt.amort > 0 ? 'amortización' : 'cupón',
      })
    }
    const future = (remaining || []).filter(pmt => pmt.date > today).slice(0, 4)
    for (const pmt of future) {
      timeline.push({
        date: pmt.date,
        amount: qty > 0 ? pmt.total * qty / 100 : null,
        approx: true,
        status: 'fut',
        kind: pmt.amort > 0 && pmt.coupon > 0 ? 'cupón + amort' : pmt.amort > 0 ? 'amortización' : 'cupón',
      })
    }
  }
  const futureShown = timeline.filter(t => t.status === 'fut').length
  const futureRest = Math.max(0, (remaining?.filter(pmt => pmt.date > today).length || 0) - futureShown)

  const [showOps, setShowOps] = useState(false)

  const TL_DOT = {
    done: 'bg-rendi-pos text-[#04120a]',
    pend: 'bg-rendi-warn text-[#191002]',
    off:  'bg-bg-2 border border-line text-ink-3',
    fut:  'bg-bg-1 border-2 border-line text-ink-3',
  }
  const TL_AMT = { done: 'text-rendi-pos', pend: 'text-rendi-warn', off: 'text-ink-3', fut: 'text-ink-1' }
  const TL_LABEL = { done: 'cobrado', pend: 'sin confirmar', off: 'sin registro', fut: 'estimado' }

  return (
    <div>
      {/* ── Tres columnas: Ficha / Tu inversión / Rendimiento ─────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Ficha */}
        <div>
          <p className="flex items-center gap-2 text-[11px] font-bold tracking-[0.07em] uppercase text-ink-3 mb-2.5">
            <span className="w-1.5 h-1.5 rounded-full bg-data-violet inline-block" aria-hidden /> Ficha
          </p>
          {meta ? (
            <div className="space-y-1 text-[12.5px]">
              <div className="flex justify-between gap-3"><span className="text-ink-3">Tipo</span><span className="font-semibold text-ink-1 text-right">{formatBondType(meta.type)}</span></div>
              <div className="flex justify-between gap-3"><span className="text-ink-3">Emisor</span><span className="font-semibold text-ink-1 text-right">{meta.issuer}</span></div>
              {meta.governingLaw && (
                <div className="flex justify-between gap-3"><span className="text-ink-3">Ley</span><span className="font-semibold text-ink-1">{meta.governingLaw === 'Argentina' ? 'Argentina' : 'Nueva York'}</span></div>
              )}
              <div className="flex justify-between gap-3"><span className="text-ink-3">Vencimiento</span><span className="font-semibold text-ink-1 tabular">{meta.maturity || 'ETF · sin vto.'}</span></div>
              {meta.couponFreq && (
                <div className="flex justify-between gap-3">
                  <span className="text-ink-3">Cupón</span>
                  <span className="font-semibold text-ink-1 tabular border-b border-dotted border-ink-3/40 cursor-help" title={formatCouponTooltip(meta)}>{formatCouponLabel(meta)}</span>
                </div>
              )}
              <div className="flex justify-between gap-3"><span className="text-ink-3">Moneda</span><span className="font-semibold text-ink-1">{meta.currency}</span></div>
              {meta._verificationLevel === 'approx' && (
                <p className="text-[10.5px] text-rendi-warn pt-1">Cronograma aproximado — verificar contra prospecto.</p>
              )}
              {meta.type === 'cer' && (
                cerFactorToday != null ? (
                  <p className="text-[10.5px] text-data-cyan pt-1">
                    Capital ajustado por CER · factor hoy ≈ {cerFactorToday.toFixed(3)}×
                    {cerStale && <span className="text-rendi-warn"> (serie posiblemente desactualizada)</span>}
                  </p>
                ) : cerSeries === null ? (
                  <p className="text-[10.5px] text-ink-3 pt-1">Cargando coeficiente CER…</p>
                ) : (
                  <p className="text-[10.5px] text-rendi-warn pt-1">Serie CER no disponible — flujos en nominal sin ajuste.</p>
                )
              )}
            </div>
          ) : (
            <p className="text-xs text-ink-2">Sin metadata configurada para este ticker.</p>
          )}
        </div>

        {/* Tu inversión */}
        <div>
          <p className="flex items-center gap-2 text-[11px] font-bold tracking-[0.07em] uppercase text-ink-3 mb-2.5">
            <span className="w-1.5 h-1.5 rounded-full bg-data-violet inline-block" aria-hidden /> Tu inversión
          </p>
          {total > 0 ? (
            <>
              <p className="text-[21px] font-bold text-rendi-pos tabular leading-none">+{moneyLabel} {fmt(totalDisp)}</p>
              <p className="text-[11px] text-ink-3 mt-1">
                cobrado en total{invested > 0 && <> · <span className="text-ink-2 font-medium">{pctSigned(recoveryPct)} del capital recuperado</span></>}
              </p>
              <div className="mt-2.5 rounded-xl bg-bg-2/70 px-3 py-2.5 text-[11.5px] text-ink-2 space-y-1">
                {coupons > 0 && <div className="flex justify-between"><span>Cupones</span><b className="text-ink-1 tabular">{moneyLabel} {fmt(couponsDisp)}</b></div>}
                {amortizations > 0 && <div className="flex justify-between"><span>Amortizaciones</span><b className="text-ink-1 tabular">{moneyLabel} {fmt(amortizationsDisp)}</b></div>}
                <div className="flex justify-between border-t border-line/60 pt-1 mt-1"><span>De eso es ganancia real</span><b className={`tabular ${pnlContribution >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{pnlContribution >= 0 ? '+' : '−'}{moneyLabel} {fmt(Math.abs(pnlContributionDisp))}</b></div>
                {amortizations > 0 && (
                  <div className="flex justify-between"><span>Devolución de tu capital</span><b className="text-ink-1 tabular">{moneyLabel} {fmt(Math.max(0, amortizationsDisp - Math.max(0, amortRealizedGainDisp)))}</b></div>
                )}
              </div>
              {isARS && dispArs && totalUsd > 0 && (
                <p className="text-[10.5px] text-ink-3 mt-1.5">≈ USD {usd(totalUsd)} en cash{hasLegacyOps && <span className="text-rendi-warn"> (aprox)</span>}</p>
              )}
            </>
          ) : (
            <p className="text-xs text-ink-2 leading-relaxed">
              Aún no registraste cobranzas. Cuando el cronograma venza, te lo proponemos
              para confirmar acá y en el inbox de Cartera.
            </p>
          )}
          <div className="flex flex-wrap gap-2 mt-3">
            <button
              onClick={onAddCoupon}
              className="inline-flex items-center gap-1.5 text-xs font-semibold whitespace-nowrap bg-rendi-pos/10 hover:bg-rendi-pos/20 text-rendi-pos border border-rendi-pos/30 rounded-lg px-3 py-1.5 transition"
            >
              <Coins size={12} strokeWidth={1.75} /> Cupón cobrado
            </button>
            <button
              onClick={onAddAmortization}
              className="inline-flex items-center gap-1.5 text-xs font-semibold whitespace-nowrap bg-data-violet/10 hover:bg-data-violet/20 text-data-violet border border-data-violet/30 rounded-lg px-3 py-1.5 transition"
            >
              <LayersIcon size={12} strokeWidth={1.75} /> Amortización
            </button>
          </div>
        </div>

        {/* Rendimiento */}
        <div>
          <p className="flex items-center gap-2 text-[11px] font-bold tracking-[0.07em] uppercase text-ink-3 mb-2.5">
            <span className="w-1.5 h-1.5 rounded-full bg-data-violet inline-block" aria-hidden /> Rendimiento
          </p>
          {yieldEstimate != null ? (
            <>
              <p className="text-[21px] font-bold tabular leading-none text-data-violet">{pctSigned(yieldEstimate)}</p>
              <p className="text-[11px] text-ink-3 mt-1">
                {meta?.type === 'cer'
                  ? <span className="border-b border-dotted border-ink-3/40 cursor-help" title="TIR REAL sobre la inflación: los flujos se descuentan al CER actual — es lo que ganás POR ENCIMA de la inflación.">TIR real (sobre CER) a precio de hoy</span>
                  : 'TIR efectiva anual a precio de hoy'}
                {!yieldDetail.converged && <span className="text-rendi-warn"> · aproximada</span>}
              </p>
              {priceConversion && (
                <p className="text-[10.5px] text-ink-3 mt-1">Precio convertido {priceConversion.from}→{priceConversion.to} al {priceConversion.type} {priceConversion.rate.toFixed(0)}</p>
              )}
              {isCrossCurrency && !priceConversion && (
                <p className="text-[10.5px] text-rendi-warn mt-1">Bono {bondCurrency} en broker {brokerCurrency} sin MEP — TIR puede estar distorsionada.</p>
              )}
            </>
          ) : (
            <p className="text-xs text-ink-2 leading-relaxed">
              {currentPrice == null
                ? 'Sin precio de mercado para estimar la TIR — cargá un precio override en la posición.'
                : 'No se pudo estimar la TIR — verificá que el precio esté en la moneda del bono.'}
            </p>
          )}
          {nextPay && (
            <div className="mt-3 rounded-xl bg-data-cyan/10 px-3.5 py-2.5">
              <p className="text-[10.5px] font-bold tracking-[0.06em] text-data-cyan uppercase">Próximo pago · {nextPay.date}</p>
              {/* El cronograma está en la moneda del BONO — se convierte al
                  riel de display (toggle global), igual que el resto. */}
              <p className="text-[16px] font-bold text-ink-0 tabular mt-0.5">~{moneyLabel} {fmt(schedToDisp(nextPay.total))}</p>
              <p className="text-[10.5px] text-ink-3">
                {nextPay.isPureAmort ? 'amortización' : nextPay.isPureCoupon ? 'cupón' : 'cupón + amortización'} · por tus {qty} nominales
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ── Timeline del cronograma ───────────────────────────────────────── */}
      {timeline.length > 0 && (
        <div className="mt-5 pt-4 border-t border-line/60">
          <p className="text-[11px] font-bold tracking-[0.07em] uppercase text-ink-3 mb-3">Cronograma de cobros</p>
          <div className="flex overflow-x-auto pb-1.5 -mx-1 px-1">
            {timeline.map((t, i) => (
              <div key={t.date} className="min-w-[112px] relative px-1.5">
                <div className={`absolute top-[7px] h-[2px] bg-line ${i === 0 ? 'left-1/2 right-0' : i === timeline.length - 1 && futureRest === 0 ? 'left-0 right-1/2' : 'left-0 right-0'}`} aria-hidden />
                <div className={`relative z-[1] w-4 h-4 rounded-full mx-auto grid place-items-center text-[9px] font-bold ${TL_DOT[t.status]}`}>
                  {t.status === 'done' ? '✓' : t.status === 'pend' ? '!' : ''}
                </div>
                <div className="text-center mt-2">
                  <div className="text-[10.5px] text-ink-3 tabular">{t.date}</div>
                  <div className={`text-[12px] font-bold tabular mt-0.5 ${TL_AMT[t.status]}`}>
                    {/* Estimados vienen del cronograma (moneda del bono);
                        cobrados de la op (moneda del broker) — ambos al riel. */}
                    {t.amount != null
                      ? (t.approx
                        ? `~${fmt(schedToDisp(t.amount))}`
                        : `+${fmt(toDisp(t.amount))}`)
                      : '—'}
                  </div>
                  <div className="text-[9.5px] text-ink-3">{TL_LABEL[t.status]} · {t.kind}</div>
                </div>
              </div>
            ))}
            {futureRest > 0 && (
              <div className="min-w-[90px] relative px-1.5">
                <div className="absolute top-[7px] left-0 right-1/2 h-[2px] bg-line" aria-hidden />
                <div className="relative z-[1] w-4 h-4 rounded-full mx-auto grid place-items-center bg-bg-1 border-2 border-line text-ink-3 text-[8px]">···</div>
                <div className="text-center mt-2">
                  <div className="text-[12px] font-bold text-ink-1">+{futureRest} más</div>
                  <div className="text-[9.5px] text-ink-3">hasta {meta?.maturity || 'vencimiento'}</div>
                </div>
              </div>
            )}
          </div>
          <p className="text-[10px] text-ink-3 mt-1">Montos por tus {qty} nominales, en {moneyLabel}. Futuro estimado según cronograma del prospecto{meta?.type === 'cer' ? ' (ajustado por CER)' : ''}.</p>
        </div>
      )}

      {/* ── Historial (colapsable) ────────────────────────────────────────── */}
      {ops.length > 0 && (
        <div className="mt-3">
          <button
            onClick={() => setShowOps(v => !v)}
            className="inline-flex items-center gap-1 text-[11.5px] font-medium text-ink-2 hover:text-ink-0 transition"
          >
            {showOps ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {showOps ? 'Ocultar historial' : `Ver historial de cobranzas (${ops.length})`}
          </button>
          {showOps && (
            <div className="mt-2 border border-line rounded-xl overflow-hidden divide-y divide-line/50 max-h-48 overflow-y-auto">
              {ops.map(o => (
                <div key={o.id} className="px-3.5 py-2 flex items-center justify-between text-xs bg-bg-1">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-ink-3 tabular shrink-0">{o.date}</span>
                    <span className={`text-[10px] font-bold rounded-full px-2 py-0.5 shrink-0 ${o.op_type === 'Cupón' ? 'bg-rendi-pos/10 text-rendi-pos' : 'bg-data-violet/10 text-data-violet'}`}>{o.op_type}</span>
                    {o.notes && <span className="text-ink-3 truncate">{o.notes}</span>}
                  </div>
                  <span className="font-semibold text-rendi-pos tabular shrink-0">+{moneyLabel} {fmt(toDisp(+o.pnl_usd || 0))}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Wrapper <tr> para las tablas por broker (mismo contrato que la v1 inline).
export default function BondDetailRow({ colSpan, ...bodyProps }) {
  return (
    <tr className="bg-data-violet/[0.03] border-b border-line">
      <td colSpan={colSpan} className="px-5 py-4">
        <BondDetailBody {...bodyProps} />
      </td>
    </tr>
  )
}
