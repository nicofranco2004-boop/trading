// CuponesPorCobrar — la bandeja de Cartera para confirmar los cobros de bonos.
// ════════════════════════════════════════════════════════════════════════════
// Gemela de DividendosPorCobrar (mismo esqueleto, mismos movimientos). Rendi
// toma el cronograma del bono y tus nominales y arma el pago: el cupón (ganancia)
// y, si el bono amortiza, la cuota de capital que te devuelve. El usuario
// confirma, o edita los montos y confirma.
//
// Lo confirmado (POST /bonds/cashflow/pago, cupón y amortización en una sola
// transacción):
//   · entra al efectivo de la cuenta donde paga el bono: un bono en dólares de
//     la cuenta en pesos paga en la cuenta en dólares;
//   · el cupón es ganancia REALIZADA; de la amortización, sólo lo que cobraste
//     por encima de lo que te había costado esa parte (el resto es tu plata que
//     vuelve: baja tu costo en el bono);
//   · no toca el capital aportado ni la ganancia no realizada (por precio) del bono;
//   · si después se importa el archivo del broker con el mismo pago, el del
//     broker lo reemplaza (no se suma).
//
// Datos y acciones: hooks/useCuponesPorCobrar.js (una sola fuente para Cartera
// de escritorio y de celular). Detección y montos: utils/pendingCashflows.js.

import { useEffect, useRef, useState } from 'react'
import { CalendarCheck, Check, ChevronDown, FileCheck2, Info, Loader2 } from 'lucide-react'
import AssetLogo from './AssetLogo'
import { useToast } from './Toast'
import { useDemora } from '../hooks/useDemora'
import { useEnVuelo } from '../hooks/useEnVuelo'
import { useCuponesPorCobrar } from '../hooks/useCuponesPorCobrar'
import { groupBrokersIntoAccounts, accountForBrokerName } from '../utils/brokerAccounts'
import { parseNum } from '../utils/format'

const num = (n, d = 2) => Number(n || 0).toLocaleString('es-AR', { minimumFractionDigits: d, maximumFractionDigits: d })
const plata = (moneda) => (n) => `${moneda === 'ARS' ? '$' : 'US$'} ${num(n)}`
// Lo que entró a la cuenta con un pago confirmado (cupón + amortización), en la
// moneda en que entró: el texto del aviso "Recalculando tu cartera".
const monedaDe = (resultado) => ((resultado?.partes?.[0]?.currency || 'USD').toUpperCase() === 'ARS' ? 'ARS' : 'USD')
const loQueEntro = (resultado) => plata(monedaDe(resultado))(
  (resultado?.partes || []).reduce((s, p) => s + (p.amount_net || 0), 0))
const ddmm = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : '')
const ddmmaa = (iso) => (iso ? `${ddmm(iso)}/${iso.slice(2, 4)}` : '')
const pctTxt = (v) => `${num(v, Number.isInteger(+(+v).toFixed(4)) ? 0 : (String(+(+v).toFixed(4)).split('.')[1]?.length > 2 ? 3 : 2))} %`
// El lector de números del repo (acepta "827,50", "827.5" y "1.234,56"). El
// atajo de borrar todos los puntos convertía "827.5" en 8275.
const parse = (s) => parseNum(s)
const sinMovimiento = () => typeof window !== 'undefined'
  && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** Un número que cuenta de `desde` a `hasta` (o aparece directo si no hay movimiento). */
function useCuenta(hasta, { desde = 0, demora = 0, ms = 900, activo = true } = {}) {
  const [v, setV] = useState(activo && !sinMovimiento() ? desde : hasta)
  useEffect(() => {
    if (!activo || sinMovimiento()) { setV(hasta); return undefined }
    let raf
    const t0 = performance.now() + demora
    const paso = (ahora) => {
      const p = Math.min(1, Math.max(0, (ahora - t0) / ms))
      setV(desde + (hasta - desde) * (1 - Math.pow(1 - p, 3)))
      if (p < 1) raf = requestAnimationFrame(paso)
    }
    setV(desde)
    raf = requestAnimationFrame(paso)
    return () => cancelAnimationFrame(raf)
  }, [hasta, desde, demora, ms, activo])
  return v
}

// La cuenta en pesos del mismo broker, si la hay (para "me lo pagaron en pesos").
function cuentaEnPesos(broker, brokers) {
  const c = accountForBrokerName(groupBrokersIntoAccounts(brokers || []), broker)
  return c?.patas.find(b => (b.currency || '').toUpperCase() === 'ARS')?.name || null
}

// ─── El cálculo (lo que Rendi propone) ───────────────────────────────────────
function Calculo({ it, animar }) {
  const m = plata(it.currency)
  const neto = useCuenta(it.total, { demora: 760, activo: animar })
  const amortiza = it.amort > 0
  const devueltas = amortiza ? it.cuota - 1 : 0
  const renglones = [
    [`Tenías ${num(it.nominales, 0)} nominales el día de pago (${ddmm(it.date)})`,
      it.vivoAntes < 100
        ? `El bono ya devolvió ${devueltas > 0 ? `${devueltas} de ${it.cuotas} cuotas` : 'parte del capital'}: quedaba vivo el ${pctTxt(it.vivoAntes)}`
        : amortiza
          ? 'Hasta este pago el bono no había devuelto capital: el cupón va sobre todos tus nominales'
          : 'Todavía no devuelve capital: el cupón va sobre todos tus nominales',
      null, false],
    [`Cupón: ${pctTxt(it.couponRate)} anual, por el período`,
      `Sobre ${it.vivoAntes < 100 ? 'lo que quedaba vivo' : 'tus nominales'}. Es ganancia`, m(it.coupon), false],
  ]
  if (amortiza) {
    renglones.push([`Amortización: cuota ${it.cuota} de ${it.cuotas}`,
      `${pctTxt(it.amortPct)} de tus nominales. Te devuelven capital`, m(it.amort), 'capital'])
  }
  if (it.cerFactor) {
    renglones.push(['Ajustado por inflación (CER)', `El capital se multiplica por ${num(it.cerFactor, 4)}: ya está en los montos`, null, false])
  }
  if (it.sinAjusteCer) {
    renglones.push(['Falta el ajuste por inflación (CER)',
      'No pudimos traer la serie CER: el monto de abajo es el nominal, sin ajustar. Cargá el que te acreditó el broker con «Editar montos».',
      null, false])
  }
  if (it.otraMoneda) {
    renglones.push([`Tu cuenta ${it.cuenta} está en ${it.cuentaMoneda === 'ARS' ? 'pesos' : 'dólares'}`,
      `El bono paga en ${it.currency === 'ARS' ? 'pesos' : 'dólares'}: el broker te lo acredita convertido. Cargá lo que te acreditó con «Editar montos».`,
      null, false])
  }
  const n = renglones.length
  const cambiaCuenta = it.cuenta && it.cuenta !== it.broker && !it.otraMoneda
  const tieneCosto = amortiza && it.costoAmortizado != null
  const ganAmort = tieneCosto ? Math.max(0, it.amort - it.costoAmortizado) : 0
  const costo = tieneCosto ? Math.min(it.amort, it.costoAmortizado) : 0
  const pct = (v) => (it.total > 0 ? (v / it.total) * 100 : 0)
  return (
    <div className="space-y-3">
      <ul className="divide-y divide-dashed divide-line" aria-label="Cómo lo calculó Rendi">
        {renglones.map(([que, detalle, monto, tipo], i) => (
          <li key={que} style={{ '--i': i * 2 }}
            className={`grid grid-cols-[16px_minmax(0,1fr)_auto] gap-2.5 items-baseline py-2 ${animar ? 'entra' : ''}`}>
            <Check size={14} strokeWidth={2.25} aria-hidden="true"
              className={`text-rendi-pos self-center ${animar ? 'tilde-entra' : ''}`} style={{ '--i': i * 2 }} />
            <span className="text-[13px] text-ink-1 min-w-0">
              {que}<span className="block text-[12px] text-ink-3">{detalle}</span>
            </span>
            <span className={`tabular text-[13.5px] text-right whitespace-nowrap font-medium ${tipo === 'capital' ? 'text-data-cyan' : 'text-ink-0'}`}>{monto}</span>
          </li>
        ))}
      </ul>
      <div style={{ '--i': n * 2 }}
        className={`grid grid-cols-[16px_minmax(0,1fr)_auto] gap-2.5 items-baseline pt-3 border-t border-line-2 ${animar ? 'entra' : ''}`}>
        <Check size={14} strokeWidth={2.25} aria-hidden="true" className="text-rendi-pos self-center" />
        <span className="text-[13.5px] font-semibold text-ink-0 min-w-0">Te llega a {it.cuenta}
          {cambiaCuenta && <span className="block text-[12px] font-normal text-ink-3">El bono vive en {it.broker}, pero paga en dólares: el cobro entra a tu cuenta en dólares</span>}
        </span>
        <span className="tabular text-[19px] font-semibold text-rendi-pos tracking-tight">{m(neto)}</span>
      </div>
      <div className="space-y-1.5">
        {amortiza ? (
          <p className="text-[12px] text-ink-2 tabular">
            {tieneCosto
              ? <>De {m(it.total)}, <b className="text-ink-0 font-semibold">{m(it.coupon + ganAmort)} son ganancia</b> y {m(costo)} es tu propia plata que vuelve.</>
              : <>{m(it.coupon)} son ganancia (el cupón) y {m(it.amort)} es capital que vuelve.</>}
          </p>
        ) : (
          <p className="text-[12px] text-ink-2">Todo el cupón es ganancia: este pago no devuelve capital.</p>
        )}
        <div className="flex h-2.5 rounded-full overflow-hidden bg-bg-3" role="img"
          aria-label={amortiza ? `Cupón ${m(it.coupon)}, capital que vuelve ${m(it.amort)}` : 'Todo es ganancia'}>
          <span className={`h-full bg-rendi-pos ${animar ? 'crece-ancho' : ''}`} style={{ width: `${pct(it.coupon)}%`, '--i': 8 }} />
          {amortiza && tieneCosto && <span className={`h-full bg-rendi-pos/50 ${animar ? 'crece-ancho' : ''}`} style={{ width: `${pct(ganAmort)}%`, '--i': 8, '--fila': 2 }} />}
          {amortiza && <span className={`h-full bg-data-cyan/70 ${animar ? 'crece-ancho' : ''}`} style={{ width: `${pct(tieneCosto ? costo : it.amort)}%`, '--i': 8, '--fila': 3 }} />}
        </div>
        {amortiza && (
          <div className="flex flex-wrap gap-x-3.5 gap-y-1 text-[11.5px] text-ink-2 tabular">
            <span className="inline-flex items-center gap-1.5"><i className="w-2 h-2 rounded-xs bg-rendi-pos" />Cupón {m(it.coupon)}</span>
            {tieneCosto && <span className="inline-flex items-center gap-1.5"><i className="w-2 h-2 rounded-xs bg-rendi-pos/50" />Ganaste al amortizar {m(ganAmort)}</span>}
            <span className="inline-flex items-center gap-1.5"><i className="w-2 h-2 rounded-xs bg-data-cyan/70" />{tieneCosto ? `Vuelve tu costo ${m(costo)}` : `Capital ${m(it.amort)}`}</span>
          </div>
        )}
        {tieneCosto && (
          <p className="flex gap-1.5 text-[12px] text-ink-3">
            <Info size={13} className="shrink-0 mt-0.5" aria-hidden="true" />
            Te devuelven el capital a la par; lo que pagaste por debajo de eso es ganancia. Al anotarlo, Rendi recalcula esa parte con lo que pagaste por cada compra.
          </p>
        )}
      </div>
    </div>
  )
}

// ─── El cronograma chico: lo que ya entró, este pago, lo que viene ───────────
function Cronograma({ puntos }) {
  if (!puntos?.length) return null
  return (
    <div className="space-y-1.5">
      <span className="text-[12px] text-ink-2">Cronograma del bono</span>
      <div className="relative grid grid-flow-col auto-cols-fr" role="list">
        <span aria-hidden="true" className="absolute left-[10%] right-[10%] top-2 h-0.5 bg-line-2" />
        {puntos.map(pt => (
          <span key={pt.date} role="listitem" className="relative flex flex-col items-center gap-1 text-center min-w-0">
            <i className={`not-italic w-[18px] h-[18px] rounded-full grid place-items-center text-[10px] font-bold border-2 ${
              pt.estado === 'ok' ? 'bg-rendi-pos border-rendi-pos text-bg-1'
                : pt.estado === 'ahora' ? 'border-data-amber bg-data-amber/15 text-data-amber'
                  : 'border-line-3 bg-bg-1 text-ink-3'}`}>
              {pt.estado === 'ok' ? '✓' : pt.estado === 'ahora' ? '!' : ''}
            </i>
            <b className="text-[11px] font-medium text-ink-1 tabular">{ddmmaa(pt.date)}</b>
            <small className={`text-[10.5px] leading-tight ${pt.estado === 'ok' ? 'text-rendi-pos' : pt.estado === 'ahora' ? 'text-data-amber' : 'text-ink-3'}`}>{pt.rotulo}</small>
          </span>
        ))}
      </div>
    </div>
  )
}

// ─── Editar los montos ───────────────────────────────────────────────────────
function Edicion({ it, brokers, mep, onGuardar, onCancelar, guardando }) {
  // Las cuentas donde pudo entrar: la del bono (por defecto) y, si el bono es en
  // dólares y el broker tiene cuenta en pesos, ésa.
  const pesos = (it.currency === 'USD' && !it.otraMoneda) ? cuentaEnPesos(it.broker, brokers) : null
  const [enPesos, setEnPesos] = useState(false)
  // La moneda en que se cargan los montos = la de la cuenta donde entran.
  const monedaCarga = enPesos ? 'ARS' : (it.otraMoneda ? it.cuentaMoneda : it.currency)
  // Con la cuenta en otra moneda que el bono, se propone el monto convertido con
  // el dólar de HOY (estimado: el broker usó el del día del pago). Con un bono
  // ajustado por inflación sin la serie CER no se propone nada: el nominal sin
  // ajustar es muchas veces más chico que lo cobrado.
  const conv = (v) => (!it.otraMoneda || !(mep > 0)) ? v
    : (it.cuentaMoneda === 'ARS' ? v * mep : v / mep)
  const inicial = (v) => (it.sinAjusteCer ? '' : num(conv(v)))
  const [v, setV] = useState({ cupon: inicial(it.coupon), amort: inicial(it.amort), comision: num(0) })
  const primero = useRef(null)
  useEffect(() => { primero.current?.focus() }, [])
  // Al cambiar de cuenta cambia la MONEDA de los montos: se convierten con el
  // dólar de hoy (o se vacían si no hay). Antes quedaban los dólares bajo el
  // signo "$": 27 y 800 se anotaban como pesos, con el costo entero como pérdida.
  const cambiarCuenta = (aPesos) => {
    if (aPesos === enPesos) return
    setEnPesos(aPesos)
    setV(s => {
      const f = (x) => {
        const val = parse(x)
        if (!Number.isFinite(val) || !(mep > 0)) return ''
        return num(aPesos ? val * mep : val / mep)
      }
      return { cupon: f(s.cupon), amort: f(s.amort), comision: f(s.comision) }
    })
  }
  const n = { cupon: parse(v.cupon), amort: it.amort > 0 ? parse(v.amort) : 0, comision: parse(v.comision) }
  const malo = Object.values(n).some(x => !Number.isFinite(x) || x < 0)
  const neto = Math.round(n.cupon * 100 + n.amort * 100 - n.comision * 100) / 100
  const error = malo ? 'Cargá los montos: tienen que ser números de 0 para arriba.'
    : neto <= 0 ? 'Lo que te llega tiene que ser mayor a cero. Revisá la comisión.' : null
  const moneda = monedaCarga === 'ARS' ? '$' : 'US$'
  const destino = enPesos ? `${pesos} (pesos)` : it.cuenta
  const campo = (k, rotulo, ayuda, ref) => (
    <label className="flex flex-col gap-1 min-w-0" htmlFor={`cup-${it.key}-${k}`}>
      <span className="text-[12px] text-ink-2">{rotulo}</span>
      <span className="flex items-center rounded border border-line-2 bg-bg-1 px-2.5 focus-within:border-data-violet focus-within:ring-2 focus-within:ring-data-violet/15">
        <span className="text-[13px] text-ink-3">{moneda}</span>
        <input id={`cup-${it.key}-${k}`} ref={ref} inputMode="decimal" value={v[k]}
          onChange={e => setV(s => ({ ...s, [k]: e.target.value }))}
          className="w-full min-w-0 bg-transparent py-2 pl-1.5 text-[14px] text-ink-0 tabular outline-none" />
      </span>
      <span className="text-[11.5px] text-ink-3">{ayuda}</span>
    </label>
  )
  return (
    <form className="grid grid-cols-1 sm:grid-cols-2 gap-x-3.5 gap-y-2.5"
      onSubmit={e => { e.preventDefault(); if (!error) onGuardar({ ...n, cuenta: enPesos ? pesos : it.cuenta, editado: true }) }} noValidate>
      {pesos && (
        <label className="sm:col-span-2 flex flex-col gap-1" htmlFor={`cup-${it.key}-dest`}>
          <span className="text-[12px] text-ink-2">¿En qué cuenta entró?</span>
          <select id={`cup-${it.key}-dest`} value={enPesos ? 'ars' : 'usd'} onChange={e => cambiarCuenta(e.target.value === 'ars')}
            className="rounded border border-line-2 bg-bg-1 px-2.5 py-2 text-[14px] text-ink-0 focus:border-data-violet focus:outline-none">
            <option value="usd">{it.cuenta} (dólares)</option>
            <option value="ars">{pesos} (pesos)</option>
          </select>
          <span className="text-[11.5px] text-ink-3">{enPesos
            ? 'Los montos de abajo quedaron convertidos con el dólar de hoy: reemplazalos por los pesos que te acreditaron. Para la ganancia, Rendi los pasa a dólares con el dólar del día del pago.'
            : 'Así lo paga casi siempre el broker.'}</span>
        </label>
      )}
      {it.otraMoneda && (
        <p className="sm:col-span-2 flex gap-1.5 text-[12px] text-ink-3">
          <Info size={13} className="shrink-0 mt-0.5" aria-hidden="true" />
          Tu cuenta {it.cuenta} está en {it.cuentaMoneda === 'ARS' ? 'pesos' : 'dólares'}. Los montos de abajo están convertidos con el dólar de hoy: reemplazalos por lo que te acreditó el broker.
        </p>
      )}
      {it.sinAjusteCer && (
        <p className="sm:col-span-2 flex gap-1.5 text-[12px] text-ink-3">
          <Info size={13} className="shrink-0 mt-0.5" aria-hidden="true" />
          No pudimos calcular el ajuste por inflación de este pago. Cargá los montos que te acreditó el broker.
        </p>
      )}
      {campo('cupon', 'Cupón', 'Es ganancia', primero)}
      {it.amort > 0 && campo('amort', 'Amortización', 'Devolución de capital')}
      {campo('comision', 'Comisión del broker', 'Si te cobró algo por el pago')}
      <div className={`sm:col-span-2 flex items-baseline justify-between gap-3 rounded-lg bg-bg-2 px-3 py-2.5 ${error ? 'text-rendi-neg' : ''}`}>
        <span className="text-[13px] text-ink-1">Te llega a {destino}</span>
        <span className={`tabular text-[18px] font-semibold ${error ? 'text-rendi-neg' : 'text-rendi-pos'}`}>{malo ? '—' : `${moneda} ${num(neto)}`}</span>
      </div>
      {error && <p className="sm:col-span-2 text-[12px] text-rendi-neg" role="alert">{error}</p>}
      <div className="sm:col-span-2 flex flex-wrap items-center gap-2">
        <button type="submit" disabled={guardando || !!error}
          className="inline-flex items-center gap-1.5 rounded bg-data-violet px-3.5 py-2 text-[13px] font-medium text-white hover:bg-rendi-violet-hover disabled:opacity-60 transition">
          {guardando ? <Loader2 size={14} className="animate-spin motion-reduce:animate-none" /> : <Check size={14} />}
          {guardando ? 'Registrando…' : 'Guardar y confirmar'}
        </button>
        <button type="button" onClick={onCancelar} className="px-2 py-2 text-[13px] text-ink-2 hover:text-ink-0">Cancelar</button>
      </div>
    </form>
  )
}

// ─── El comprobante (después de confirmar) ───────────────────────────────────
function Comprobante({ c, onDeshacer, deshaciendo }) {
  const partes = c.resultado.partes || []
  const cupon = partes.find(p => p.op_type === 'Cupón')
  const amort = partes.find(p => p.op_type === 'Amortización')
  const moneda = monedaDe(c.resultado)
  const m = plata(moneda)
  const entro = partes.reduce((s, p) => s + (p.amount_net || 0), 0)
  const ganancia = partes.reduce((s, p) => s + (p.ganancia || 0), 0)
  const efectivo = useCuenta(c.antes + entro, { desde: c.antes, demora: 250, ms: 800 })
  const filas = [
    [`Efectivo · ${c.cuenta}`, 'Entra lo que te llegó',
      <><span className="text-ink-3">{m(c.antes)} → </span>{m(efectivo)}</>, ''],
    ['Ganancia realizada del mes',
      amort ? `Cupón ${m(cupon?.ganancia || 0)} + lo que ganaste al amortizar ${m(amort.ganancia || 0)}` : 'Un cupón es ganancia de tu inversión',
      `+${m(ganancia)}`, 'text-rendi-pos font-semibold'],
    ['Capital aportado', 'Sin cambios: no es plata que pusiste vos', 'sin cambios', 'text-ink-3'],
  ]
  if (amort) {
    filas.push([`Tu costo en ${c.item.asset}`, 'Baja lo que el bono te devolvió de tu plata',
      amort.cost_basis_consumed != null ? `− ${m(amort.cost_basis_consumed)}` : 'sin dato', 'text-data-cyan'])
    filas.push([`Lo que queda vivo de ${c.item.asset}`, `Te devolvió la cuota ${c.item.cuota} de ${c.item.cuotas}`,
      `${pctTxt(c.item.vivoAntes)} → ${pctTxt(c.item.vivoDespues)}`, ''])
  }
  filas.push([`Ganancia no realizada de ${c.item.asset}`, 'Sin cambios: el cobro ya es plata cobrada, no una suba de precio', 'sin cambios', 'text-ink-3'])
  filas.push(['Movimientos', amort ? 'Dos renglones: el cupón (ganancia) y la amortización (capital)' : 'Queda como Cupón, con el bono',
    amort ? `${c.item.asset} · Cupón y Amortización` : `${c.item.asset} · Cupón`, ''])
  return (
    <div className="space-y-2.5">
      <div className="rounded-lg border border-line overflow-hidden">
        <div className="flex items-center gap-1.5 bg-bg-2 px-3 py-2 text-[12px] font-semibold text-ink-0">
          <Check size={14} className="text-rendi-pos" aria-hidden="true" /> Así quedó anotado
        </div>
        {filas.map(([k, sub, v, cls], i) => (
          <div key={k} style={{ '--i': i }} className="entra grid grid-cols-[minmax(0,1fr)_auto] gap-2.5 items-baseline border-t border-line px-3 py-2">
            <span className="text-[13px] text-ink-1 min-w-0">{k}<span className="block text-[11.5px] text-ink-3">{sub}</span></span>
            <span className={`tabular text-[13px] text-right whitespace-nowrap text-ink-0 ${cls}`}>{v}</span>
          </div>
        ))}
        <div className="flex gap-1.5 items-start border-t border-line px-3 py-2 text-[12px] text-ink-3">
          <Info size={13} className="shrink-0 mt-0.5" aria-hidden="true" />
          <span>Si después importás el archivo del broker con este mismo pago, Rendi lo reconoce y no lo suma dos veces. Esta tarjeta se va de la bandeja la próxima vez que entres a Cartera.</span>
        </div>
      </div>
      <button type="button" onClick={onDeshacer} disabled={deshaciendo}
        className="px-2 py-1.5 text-[13px] text-ink-2 hover:text-ink-0 disabled:opacity-60">
        {deshaciendo ? 'Deshaciendo…' : 'Deshacer'}
      </button>
    </div>
  )
}

// ─── Una tarjeta ─────────────────────────────────────────────────────────────
function Fila({ it, abierta, onAbrir, confirmado, children, i }) {
  // Confirmado: la moneda en la que ENTRÓ (editado "en pesos" entra en pesos).
  const monedaCobro = confirmado
    ? (((confirmado.resultado.partes || [])[0]?.currency || '').toUpperCase() === 'ARS' ? 'ARS' : 'USD')
    : it.currency
  const m = plata(monedaCobro)
  const tipo = it.kind === 'mixto' ? 'Cupón + amortización' : it.kind === 'amortizacion' ? 'Amortización' : 'Cupón'
  const entro = confirmado ? (confirmado.resultado.partes || []).reduce((s, p) => s + (p.amount_net || 0), 0) : it.total
  const montoRotulo = confirmado ? `en ${confirmado.cuenta}` : 'según el cronograma'
  return (
    <div className="border-t border-line first:border-t-0 entra" style={{ '--i': i }}>
      <button type="button" onClick={onAbrir} aria-expanded={abierta} aria-controls={`cup-cuerpo-${it.key}`}
        className="w-full grid grid-cols-[36px_minmax(0,1fr)_auto] sm:grid-cols-[36px_minmax(0,1fr)_auto_16px] gap-3 items-center px-4 py-3 text-left hover:bg-bg-2/60 transition">
        <AssetLogo asset={it.asset} size={36} />
        <span className="min-w-0">
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="text-[13px] font-semibold text-ink-0">{it.asset}</span>
            <span className="rounded-sm border border-line bg-bg-2 px-1.5 text-[11px] text-ink-2">{it.broker}</span>
            {it.amort > 0 && <span className="rounded-sm border border-data-cyan/30 bg-data-cyan/10 px-1.5 text-[11px] text-data-cyan">Devuelve capital</span>}
            {confirmado?.editado && <span className="rounded-sm border border-data-violet/30 bg-data-violet/10 px-1.5 text-[11px] text-data-violet">Editado</span>}
            {confirmado && <span className="rounded-sm border border-rendi-pos/30 bg-rendi-pos/10 px-1.5 text-[11px] text-rendi-pos">Cobrado</span>}
          </span>
          <span className="block text-[12px] text-ink-3 tabular mt-0.5">{tipo} del {ddmmaa(it.date)} · venció hace {it.daysAgo} {it.daysAgo === 1 ? 'día' : 'días'}</span>
        </span>
        <span className="text-right">
          <span className={`block tabular text-[15px] font-semibold ${confirmado ? 'text-rendi-pos' : 'text-ink-0'}`}>{confirmado ? '+' : ''}{m(entro)}</span>
          <span className="block text-[11.5px] text-ink-3">{montoRotulo}</span>
        </span>
        <ChevronDown size={16} aria-hidden="true"
          className={`hidden sm:block text-ink-3 transition-transform duration-300 ${abierta ? 'rotate-180' : ''}`} />
      </button>
      {abierta && (
        <div id={`cup-cuerpo-${it.key}`} className="despliega">
          <div><div className="px-4 pb-4 sm:pl-16">{children}</div></div>
        </div>
      )}
    </div>
  )
}

// ─── La bandeja ──────────────────────────────────────────────────────────────
export default function CuponesPorCobrar({ positions, brokers, cerSeries, mep, onCambio, className = '' }) {
  const toast = useToast()
  const b = useCuponesPorCobrar({ positions, brokers, cerSeries, mep })
  const [abierta, setAbierta] = useState(null)
  const [editando, setEditando] = useState(null)
  const [animada, setAnimada] = useState(null)
  const abrioSola = useRef(false)
  const enVuelo = useEnVuelo()
  const mostrarEscaneo = useDemora(b.cargando, 250)

  // Al llegar los datos, se abre sola la primera y su cálculo se arma.
  useEffect(() => {
    if (!b.cargando && !abrioSola.current && b.paraConfirmar.length) {
      abrioSola.current = true
      setAbierta(b.paraConfirmar[0].key); setAnimada(b.paraConfirmar[0].key)
    }
  }, [b.cargando, b.paraConfirmar])

  if (!b.bonos.length) return null
  const hay = b.paraConfirmar.length + b.confirmados.length
  if (!b.cargando && !hay) return null
  if (b.cargando && !mostrarEscaneo) return null

  const n = b.paraConfirmar.length
  const monedas = new Set(b.paraConfirmar.map(it => it.currency))
  const total = b.paraConfirmar.reduce((s, it) => s + it.total, 0)
  const titulo = b.cargando ? 'Revisando el cronograma de tus bonos…'
    : n === 0 ? 'Todo al día'
      : n === 1 ? 'Tenés 1 cobro de bonos para confirmar' : `Tenés ${n} cobros de bonos para confirmar`
  const sub = b.cargando ? 'Rendi cruza las fechas de pago de cada bono con lo que ya está anotado.'
    : n === 0 ? 'Los cobros confirmados ya están en el efectivo de cada broker, en Movimientos y en el cronograma de cada bono.'
      : 'Estos bonos ya pagaron y no encontramos el cobro anotado. Revisá la cuenta y confirmá: entra al efectivo del broker.'

  const abrir = (key) => { setEditando(null); setAbierta(a => (a === key ? null : key)); setAnimada(key) }

  const confirmar = (it, montos) => enVuelo.correr(async () => {
    try {
      const r = await b.confirmar(it, montos)
      setEditando(null)
      // La página recarga la cartera y muestra el total recalculado
      // (RecalculoDeCartera), igual que al confirmar un dividendo.
      onCambio?.({ texto: `cobro de ${it.asset}`, monto: `+${loQueEntro(r)}` })
    } catch (e) {
      toast.push(`No se pudo anotar el cobro de ${it.asset}: ${e.message}`, { type: 'error' })
    }
  }, it.key)

  const saltar = (it) => enVuelo.correr(async () => {
    try {
      await b.saltar(it)
      if (abierta === it.key) setAbierta(null)
      onCambio?.()
      toast.push(`${it.asset} ${ddmm(it.date)}: no lo vamos a volver a mostrar.`, {
        // 8 s y no los 4 de siempre: es la única salida de un click equivocado.
        type: 'success', actionLabel: 'Deshacer', duration: 8000,
        onAction: () => b.volverASugerir(it).then(() => onCambio?.()).catch(e => toast.push(e.message, { type: 'error' })),
      })
    } catch (e) {
      toast.push(`No se pudo guardar: ${e.message}`, { type: 'error' })
    }
  }, it.key)

  const deshacer = (c) => enVuelo.correr(async () => {
    try {
      await b.deshacerCobro(c)
      setAbierta(c.item.key); setAnimada(null)
      onCambio?.({ texto: `cobro de ${c.item.asset}`, monto: loQueEntro(c.resultado), deshecho: true })
    } catch (e) {
      toast.push(`No se pudo deshacer: ${e.message}`, { type: 'error' })
    }
  }, c.item.key)

  // Un solo orden (el más reciente primero): la tarjeta confirmada no salta de lugar.
  const tarjetas = [
    ...b.confirmados.map(c => ({ it: c.item, c })),
    ...b.paraConfirmar.map(it => ({ it, c: null })),
  ].sort((x, y) => y.it.date.localeCompare(x.it.date) || x.it.key.localeCompare(y.it.key))

  return (
    <section aria-labelledby="cupones-titulo"
      className={`bg-bg-1 border border-line rounded-xl overflow-hidden ${className}`}>
      <div className="flex items-start gap-3 px-4 py-3.5">
        <div className="w-8 h-8 rounded-lg bg-data-cyan/10 text-data-cyan grid place-items-center shrink-0" aria-hidden="true">
          <CalendarCheck size={16} strokeWidth={1.75} />
        </div>
        <div className="min-w-0 flex-1" role="status" aria-live="polite">
          <h2 id="cupones-titulo" className="text-sm font-semibold text-ink-0">{titulo}</h2>
          <p className="text-[12.5px] text-ink-3 leading-snug mt-0.5">{sub}</p>
        </div>
        {!b.cargando && n > 0 && monedas.size === 1 && (
          <div className="hidden sm:block text-right shrink-0">
            <div className="tabular text-[17px] font-semibold text-rendi-pos">~{plata([...monedas][0])(total)}</div>
            <div className="text-[11.5px] text-ink-3">a confirmar</div>
          </div>
        )}
      </div>

      {b.cargando && (
        <div className="flex flex-wrap gap-1.5 px-4 pb-3.5 sm:pl-[60px]" aria-hidden="true">
          {b.bonos.map((t, i) => (
            <span key={t} style={{ '--i': i }}
              className="chip-escaneando inline-flex items-center rounded-full border border-line bg-bg-2 px-2 py-0.5 text-[11.5px] font-semibold text-ink-2">
              {t}
            </span>
          ))}
        </div>
      )}

      {!b.cargando && (
        <div className="border-t border-line">
          {tarjetas.map(({ it, c }, i) => (
            <Fila key={it.key} it={it} i={i} confirmado={c}
              abierta={abierta === it.key} onAbrir={() => abrir(it.key)}>
              <div className="space-y-3.5">
                <Cronograma puntos={b.cronogramaDe(it, !!c)} />
                {c ? (
                  <Comprobante c={c} onDeshacer={() => deshacer(c)} deshaciendo={enVuelo.activo(it.key)} />
                ) : editando === it.key ? (
                  <Edicion it={it} brokers={brokers} mep={mep} guardando={enVuelo.activo(it.key)}
                    onCancelar={() => setEditando(null)}
                    onGuardar={(montos) => confirmar(it, montos)} />
                ) : (
                  <>
                    <Calculo it={it} animar={animada === it.key} />
                    <p className="flex gap-1.5 text-[12px] text-ink-3">
                      <Info size={13} className="shrink-0 mt-0.5" aria-hidden="true" />
                      Compará con lo que te muestra {it.broker}. Si no coincide (otra comisión, o te lo pagó en pesos), editalo: se anota tu número.
                    </p>
                    <div className="flex flex-wrap items-center gap-2">
                      {!it.sinAjusteCer && !it.otraMoneda && <button type="button" disabled={enVuelo.activo(it.key)}
                        onClick={() => confirmar(it, { cupon: it.coupon, amort: it.amort, comision: 0 })}
                        className="inline-flex items-center gap-1.5 rounded bg-data-violet px-3.5 py-2 text-[13px] font-medium text-white hover:bg-rendi-violet-hover disabled:opacity-60 transition">
                        {enVuelo.activo(it.key) ? <Loader2 size={14} className="animate-spin motion-reduce:animate-none" /> : <Check size={14} />}
                        {enVuelo.activo(it.key) ? 'Registrando…' : 'Confirmar cobro'}
                      </button>}
                      <button type="button" onClick={() => setEditando(it.key)}
                        className={(it.sinAjusteCer || it.otraMoneda)
                          ? 'inline-flex items-center gap-1.5 rounded bg-data-violet px-3.5 py-2 text-[13px] font-medium text-white hover:bg-rendi-violet-hover transition'
                          : 'rounded border border-line-2 bg-bg-1 px-3.5 py-2 text-[13px] font-medium text-ink-0 hover:bg-bg-2 transition'}>
                        {(it.sinAjusteCer || it.otraMoneda) ? 'Cargar lo que cobré' : 'Editar montos'}
                      </button>
                      <button type="button" onClick={() => saltar(it)} disabled={enVuelo.activo(it.key)}
                        className="px-2 py-2 text-[13px] text-ink-2 hover:text-ink-0">
                        No lo cobré
                      </button>
                    </div>
                  </>
                )}
              </div>
            </Fila>
          ))}
          {b.importados.length > 0 && (
            <div className="grid grid-cols-[36px_minmax(0,1fr)] gap-3 items-start px-4 py-3 border-t border-line">
              <span className="w-9 h-9 rounded-full grid place-items-center bg-rendi-pos/10 text-rendi-pos" aria-hidden="true">
                <FileCheck2 size={16} strokeWidth={1.75} />
              </span>
              <div className="min-w-0">
                <p className="text-[13px] font-medium text-ink-0">
                  {b.importados.length === 1 ? '1 cobro ya entró con tu importación' : `${b.importados.length} cobros ya entraron con tu importación`}
                </p>
                <p className="text-[12px] text-ink-3 mt-0.5">El archivo del broker los llama «renta», «dividendo» o «interés». Rendi igual los reconoce como el pago del bono y no te los pide de nuevo.</p>
                <ul className="mt-2 space-y-1">
                  {b.importados.slice(0, 4).map(y => (
                    <li key={y.key} className="grid grid-cols-[minmax(0,1fr)_auto] gap-2.5 text-[12.5px] text-ink-1 items-baseline">
                      <span className="tabular min-w-0">{y.asset} · {ddmmaa(y.date)} · {y.broker}{' '}
                        <span className="rounded-sm border border-line bg-bg-2 px-1.5 text-[11px] text-ink-2">{y.comoLoLlama}</span></span>
                      {y.monto != null && <span className="tabular text-rendi-pos whitespace-nowrap">+{num(y.monto)}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
