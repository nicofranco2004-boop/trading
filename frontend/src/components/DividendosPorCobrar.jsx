// DividendosPorCobrar — la bandeja de Cartera para confirmar dividendos cobrados.
// ════════════════════════════════════════════════════════════════════════════
// Rendi calcula cuánto te corresponde (CEDEARs al día de corte → acciones →
// dividendo de la empresa, menos el impuesto de EE.UU., los otros descuentos y
// la comisión en pesos) y lo muestra; el usuario confirma, o edita los montos y
// confirma. Lo confirmado entra al efectivo del broker, aparece en Movimientos
// como "Dividendo" y cuenta como ganancia REALIZADA — no como depósito, ni como
// ganancia no realizada de la acción. Ver backend/dividendos.py.
//
// `onCambio({ texto, monto, deshecho? })`: la página recarga la cartera y muestra
// el total recalculado con <RecalculoDeCartera>.
//
// Datos y acciones: hooks/useDividendosPorCobrar.js (una sola fuente para
// Cartera de escritorio y de celular). Detección: utils/dividendosPendientes.js.
//
// Movimiento (con "reducir movimiento", nada se mueve):
//   · mientras el pedido viaja, los chips de tus empresas barren en ola
//     (.chip-escaneando, el idioma del cargador de Novedades) y una línea recorre
//     la cabecera (.barrido-escaneo). Es el pedido REAL: sin pedido, no hay barrido.
//   · el cálculo se arma renglón por renglón (.entra + .tilde-entra), lo que te
//     llega cuenta desde cero y la barra se parte en lo que llega y lo que se
//     descuenta (.crece-ancho).
//   · al confirmar, el comprobante entra renglón por renglón y el efectivo de la
//     cuenta cuenta desde el saldo anterior hasta el nuevo.

import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, CircleDollarSign, Info, Loader2 } from 'lucide-react'
import AssetLogo from './AssetLogo'
import { useToast } from './Toast'
import { useDemora } from '../hooks/useDemora'
import { useEnVuelo } from '../hooks/useEnVuelo'
import { useDividendosPorCobrar } from '../hooks/useDividendosPorCobrar'
import { usePrivacy } from '../contexts/PrivacyContext'

const num = (n, d = 2) => Number(n || 0).toLocaleString('es-AR', { minimumFractionDigits: d, maximumFractionDigits: d })
const usd = (n) => `US$ ${num(n)}`
const ars = (n) => `$ ${num(n)}`
// Modo privacidad: los montos de la bandeja se tapan como en el resto de Cartera
// (auditoría 2026-10-09: mostraba el neto, el total y el saldo de la cuenta).
const Oculto = createContext(false)
const TAPADO = '••••••'
function useMontos() {
  const oculto = useContext(Oculto)
  return { usd: (n) => (oculto ? TAPADO : usd(n)), ars: (n) => (oculto ? TAPADO : ars(n)) }
}
const ddmm = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : '')
const parse = (s) => {
  const v = parseFloat(String(s ?? '').trim().replace(/\./g, '').replace(',', '.'))
  return Number.isFinite(v) ? v : NaN
}
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

// ─── El cálculo (lo que Rendi propone) ───────────────────────────────────────
function Calculo({ it, animar }) {
  const m = useMontos()
  const neto = useCuenta(it.neto, { demora: 760, activo: animar })
  const renglones = [
    [`Tenías ${num(it.cedears, 0)} CEDEARs el día de corte (${ddmm(it.exDate)})`,
      `= ${num(it.acciones, it.acciones % 1 ? 2 : 0)} acciones (${num(it.ratio, 0)} CEDEARs por acción)`, null, false],
    [`La empresa pagó US$ ${num(it.porAccion, it.porAccion < 1 ? 2 : 3)} por acción`,
      'Dato de la empresa, no estimado', m.usd(it.bruto), false],
    ['Impuesto de EE.UU.', `Retención del ${num(it.impuestoPct * 100, 0)} % sobre dividendos`, `− ${m.usd(it.impuesto)}`, true],
  ]
  if (it.otros > 0) {
    renglones.push(['Otros descuentos',
      `Lo que descuentan los brokers argentinos además del impuesto (~${num(it.otrosPct * 100, 0)} %)`,
      `− ${m.usd(it.otros)}`, true])
  }
  const pct = (v) => (it.bruto > 0 ? (v / it.bruto) * 100 : 0)
  const n = renglones.length
  return (
    <div className="space-y-3">
      <ul className="divide-y divide-dashed divide-line" aria-label="Cómo lo calculó Rendi">
        {renglones.map(([que, detalle, monto, resta], i) => (
          <li key={que} style={{ '--i': i * 2 }}
            className={`grid grid-cols-[16px_minmax(0,1fr)_auto] gap-2.5 items-baseline py-2 ${animar ? 'entra' : ''}`}>
            <Check size={14} strokeWidth={2.25} aria-hidden="true"
              className={`text-rendi-pos self-center ${animar ? 'tilde-entra' : ''}`} style={{ '--i': i * 2 }} />
            <span className="text-[13px] text-ink-1 min-w-0">
              {que}<span className="block text-[12px] text-ink-3">{detalle}</span>
            </span>
            <span className={`tabular text-[13.5px] text-right whitespace-nowrap ${resta ? 'text-ink-2' : 'text-ink-0 font-medium'}`}>{monto}</span>
          </li>
        ))}
      </ul>
      <div style={{ '--i': n * 2 }}
        className={`grid grid-cols-[16px_minmax(0,1fr)_auto] gap-2.5 items-baseline pt-3 border-t border-line-2 ${animar ? 'entra' : ''}`}>
        <Check size={14} strokeWidth={2.25} aria-hidden="true" className="text-rendi-pos self-center" />
        <span className="text-[13.5px] font-semibold text-ink-0">Te llega a {it.broker} · USD</span>
        <span className="tabular text-[19px] font-semibold text-rendi-pos tracking-tight">{m.usd(neto)}</span>
      </div>
      {it.comisionPesos > 0 && (
        <div style={{ '--i': n * 2 + 1 }}
          className={`grid grid-cols-[16px_minmax(0,1fr)_auto] gap-2.5 items-baseline ${animar ? 'entra' : ''}`}>
          <Check size={14} strokeWidth={2.25} aria-hidden="true" className="text-rendi-pos self-center" />
          <span className="text-[13px] text-ink-1">Comisión de {it.broker} en pesos
            <span className="block text-[12px] text-ink-3">Sale del efectivo en pesos, el mismo día</span></span>
          <span className="tabular text-[13px] text-ink-2 whitespace-nowrap">− {m.ars(it.comisionPesos)}</span>
        </div>
      )}
      <div className="space-y-1.5">
        <div className="flex h-2.5 rounded-full overflow-hidden bg-bg-3" role="img"
          aria-label={`De ${m.usd(it.bruto)} te llegan ${m.usd(it.neto)}`}>
          <span className={`h-full bg-rendi-pos ${animar ? 'crece-ancho' : ''}`} style={{ width: `${pct(it.neto)}%`, '--i': 8 }} />
          <span className={`h-full bg-data-amber/70 ${animar ? 'crece-ancho' : ''}`} style={{ width: `${pct(it.impuesto)}%`, '--i': 8, '--fila': 2 }} />
          {it.otros > 0 && <span className={`h-full bg-ink-3/60 ${animar ? 'crece-ancho' : ''}`} style={{ width: `${pct(it.otros)}%`, '--i': 8, '--fila': 3 }} />}
        </div>
        <div className="flex flex-wrap gap-x-3.5 gap-y-1 text-[11.5px] text-ink-2 tabular">
          <span className="inline-flex items-center gap-1.5"><i className="w-2 h-2 rounded-xs bg-rendi-pos" />Te llega {num(pct(it.neto), 0)} %</span>
          <span className="inline-flex items-center gap-1.5"><i className="w-2 h-2 rounded-xs bg-data-amber/70" />Impuesto {num(pct(it.impuesto), 0)} %</span>
          {it.otros > 0 && <span className="inline-flex items-center gap-1.5"><i className="w-2 h-2 rounded-xs bg-ink-3/60" />Otros {num(pct(it.otros), 0)} %</span>}
        </div>
      </div>
    </div>
  )
}

// ─── Editar los montos ───────────────────────────────────────────────────────
function Edicion({ it, onGuardar, onCancelar, guardando }) {
  const [v, setV] = useState({
    bruto: num(it.bruto), impuesto: num(it.impuesto), otros: num(it.otros), comisionPesos: num(it.comisionPesos),
  })
  const primero = useRef(null)
  useEffect(() => { primero.current?.focus() }, [])
  const n = { bruto: parse(v.bruto), impuesto: parse(v.impuesto), otros: parse(v.otros), comisionPesos: parse(v.comisionPesos) }
  const malo = Object.values(n).some(x => !Number.isFinite(x) || x < 0)
  const neto = Math.round(n.bruto * 100 - n.impuesto * 100 - n.otros * 100) / 100
  const error = malo ? 'Revisá los montos: tienen que ser números de 0 para arriba.'
    : neto <= 0 ? 'Lo que te llega tiene que ser mayor a cero. Revisá el impuesto y los descuentos.' : null
  const campo = (k, rotulo, moneda, ayuda, ref) => (
    <label className="flex flex-col gap-1 min-w-0" htmlFor={`div-${it.key}-${k}`}>
      <span className="text-[12px] text-ink-2">{rotulo}</span>
      <span className="flex items-center rounded border border-line-2 bg-bg-1 px-2.5 focus-within:border-data-violet focus-within:ring-2 focus-within:ring-data-violet/15">
        <span className="text-[13px] text-ink-3">{moneda}</span>
        <input id={`div-${it.key}-${k}`} ref={ref} inputMode="decimal" value={v[k]}
          onChange={e => setV(s => ({ ...s, [k]: e.target.value }))}
          className="w-full min-w-0 bg-transparent py-2 pl-1.5 text-[14px] text-ink-0 tabular outline-none" />
      </span>
      <span className="text-[11.5px] text-ink-3">{ayuda}</span>
    </label>
  )
  return (
    <form className="grid grid-cols-1 sm:grid-cols-2 gap-x-3.5 gap-y-2.5"
      onSubmit={e => { e.preventDefault(); if (!error) onGuardar({ ...n, editado: true }) }} noValidate>
      {campo('bruto', 'Dividendo de la empresa', 'US$', 'Antes de impuestos', primero)}
      {campo('impuesto', 'Impuesto de EE.UU.', 'US$', 'Retención')}
      {campo('otros', 'Otros descuentos', 'US$', 'Comisiones en dólares')}
      {campo('comisionPesos', `Comisión de ${it.broker} en pesos`, '$', 'Sale del efectivo en pesos')}
      <div className={`sm:col-span-2 flex items-baseline justify-between rounded-lg bg-bg-2 px-3 py-2.5 ${error ? 'text-rendi-neg' : ''}`}>
        <span className="text-[13px] text-ink-1">Te llega a {it.broker} · USD</span>
        <span className={`tabular text-[18px] font-semibold ${error ? 'text-rendi-neg' : 'text-rendi-pos'}`}>{malo ? '—' : usd(neto)}</span>
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
  const m = useMontos()
  const r = c.resultado
  const efectivo = useCuenta(c.antes + r.efectivo, { desde: c.antes, demora: 250, ms: 800 })
  const moneda = r.moneda === 'ARS' ? m.ars : m.usd
  const filas = [
    [`Efectivo · ${r.cuenta}`, 'Entra lo que te llegó',
      <><span className="text-ink-3">{moneda(c.antes)} → </span>{moneda(efectivo)}</>, ''],
    ['Ganancia realizada del mes', 'Un dividendo es ganancia de tu inversión', `+${m.usd(r.ganancia_usd)}`, 'text-rendi-pos font-semibold'],
    ['Capital aportado', 'Sin cambios: no es plata que pusiste vos', 'sin cambios', 'text-ink-3'],
    [`Ganancia no realizada de ${c.item.ticker}`, 'Sin cambios: el dividendo ya es plata cobrada, no una suba de precio', 'sin cambios', 'text-ink-3'],
  ]
  if (r.comision_pesos > 0) filas.push([`Efectivo · ${r.cuenta_pesos}`, 'Comisión del broker', `− ${m.ars(r.comision_pesos)}`, ''])
  filas.push(['Movimientos', 'Queda como Dividendo, con la empresa', `${c.item.ticker} · Dividendo`, ''])
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
          <span>Esta tarjeta se va de la bandeja la próxima vez que entres a Cartera, porque ya no hay nada que confirmar. El cobro queda en el efectivo, en la ganancia realizada y en Movimientos.</span>
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
  const m = useMontos()
  const montoRotulo = confirmado ? `en ${confirmado.resultado.cuenta}` : (it.editado ? 'tu monto' : 'estimado')
  return (
    <div className="border-t border-line first:border-t-0 entra" style={{ '--i': i }}>
      <button type="button" onClick={onAbrir} aria-expanded={abierta} aria-controls={`div-cuerpo-${it.key}`}
        className="w-full grid grid-cols-[36px_minmax(0,1fr)_auto] sm:grid-cols-[36px_minmax(0,1fr)_auto_16px] gap-3 items-center px-4 py-3 text-left hover:bg-bg-2/60 transition">
        <AssetLogo asset={it.ticker} size={36} />
        <span className="min-w-0">
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="text-[13px] font-semibold text-ink-0">{it.ticker}</span>
            <span className="rounded-sm border border-line bg-bg-2 px-1.5 text-[11px] text-ink-2">{it.broker}</span>
            {it.tipo === 'ETF' && <span className="rounded-sm border border-line bg-bg-2 px-1.5 text-[11px] text-ink-2">ETF</span>}
            {confirmado?.editado && <span className="rounded-sm border border-data-violet/30 bg-data-violet/10 px-1.5 text-[11px] text-data-violet">Editado</span>}
            {confirmado && <span className="rounded-sm border border-rendi-pos/30 bg-rendi-pos/10 px-1.5 text-[11px] text-rendi-pos">Cobrado</span>}
          </span>
          <span className="block text-[12px] text-ink-3 tabular mt-0.5">Corte {ddmm(it.exDate)} · el broker acredita ~{ddmm(it.pagoEstimado)}</span>
        </span>
        <span className="text-right">
          <span className={`block tabular text-[15px] font-semibold ${confirmado ? 'text-rendi-pos' : 'text-ink-0'}`}>{confirmado ? '+' : ''}{m.usd(confirmado ? confirmado.resultado.neto : it.neto)}</span>
          <span className="block text-[11.5px] text-ink-3">{montoRotulo}</span>
        </span>
        <ChevronDown size={16} aria-hidden="true"
          className={`hidden sm:block text-ink-3 transition-transform duration-300 ${abierta ? 'rotate-180' : ''}`} />
      </button>
      {abierta && (
        <div id={`div-cuerpo-${it.key}`} className="despliega">
          <div><div className="px-4 pb-4 sm:pl-16">{children}</div></div>
        </div>
      )}
    </div>
  )
}

// ─── La bandeja ──────────────────────────────────────────────────────────────
export default function DividendosPorCobrar({ positions, brokers, mep, onCambio, className = '' }) {
  const toast = useToast()
  const { hidden } = usePrivacy()
  const mm = { usd: (n) => (hidden ? TAPADO : usd(n)) }
  const b = useDividendosPorCobrar({ positions, brokers, mep })
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

  if (!b.tickers.length) return null
  const hay = b.paraConfirmar.length + b.confirmados.length
  if (!b.cargando && !hay) return null
  if (b.cargando && !mostrarEscaneo) return null

  const total = b.paraConfirmar.reduce((s, it) => s + it.neto, 0)
  const n = b.paraConfirmar.length
  const titulo = b.cargando ? 'Buscando dividendos en tus activos…'
    : n === 0 ? 'Todo al día'
      : n === 1 ? 'Tenés 1 dividendo para confirmar' : `Tenés ${n} dividendos para confirmar`
  const sub = b.cargando ? 'Rendi cruza lo que tenías el día de corte con lo que pagó cada empresa.'
    : n === 0 ? 'Los cobros confirmados ya están en el efectivo de cada broker y en Movimientos.'
      : 'Las empresas ya pagaron. Revisá el cálculo y confirmá: entra al efectivo de cada broker como ganancia.'

  const abrir = (key) => { setEditando(null); setAbierta(a => (a === key ? null : key)); setAnimada(key) }

  const confirmar = (it, montos) => enVuelo.correr(async () => {
    try {
      const r = await b.confirmar(it, montos)
      setEditando(null)
      // La página recarga la cartera y muestra el total recalculado (RecalculoDeCartera).
      onCambio?.({ texto: `dividendo de ${it.ticker}`, monto: `+${usd(r.neto)}` })
    } catch (e) {
      toast.push(`No se pudo anotar el dividendo de ${it.ticker}: ${e.message}`, { type: 'error' })
    }
  }, it.key)

  const saltar = (it) => enVuelo.correr(async () => {
    try {
      await b.saltar(it)
      if (abierta === it.key) setAbierta(null)
      toast.push(`${it.ticker}: no lo vamos a volver a mostrar.`, {
        // 8 s y no los 4 de siempre: es la única salida de un click equivocado.
        type: 'success', actionLabel: 'Deshacer', duration: 8000,
        onAction: () => b.volverASugerir(it).catch(e => toast.push(e.message, { type: 'error' })),
      })
    } catch (e) {
      toast.push(`No se pudo guardar: ${e.message}`, { type: 'error' })
    }
  }, it.key)

  const deshacer = (c) => enVuelo.correr(async () => {
    try {
      await b.deshacerCobro(c)
      setAbierta(c.item.key); setAnimada(null)
      onCambio?.({ texto: `dividendo de ${c.item.ticker}`, monto: usd(c.resultado.neto), deshecho: true })
    } catch (e) {
      toast.push(`No se pudo deshacer: ${e.message}`, { type: 'error' })
    }
  }, c.item.key)

  // Un solo orden (el más reciente primero): la tarjeta confirmada no salta de lugar.
  const tarjetas = [
    ...b.confirmados.map(c => ({ it: c.item, c })),
    ...b.paraConfirmar.map(it => ({ it, c: null })),
  ].sort((x, y) => y.it.exDate.localeCompare(x.it.exDate) || x.it.key.localeCompare(y.it.key))

  return (
    <Oculto.Provider value={!!hidden}>
    <section aria-labelledby="dividendos-titulo"
      className={`bg-bg-1 border border-line rounded-xl overflow-hidden ${className}`}>
      <div className="flex items-start gap-3 px-4 py-3.5">
        <div className="w-8 h-8 rounded-lg bg-data-cyan/10 text-data-cyan grid place-items-center shrink-0" aria-hidden="true">
          <CircleDollarSign size={16} strokeWidth={1.75} />
        </div>
        <div className="min-w-0 flex-1" role="status" aria-live="polite">
          <h2 id="dividendos-titulo" className="text-sm font-semibold text-ink-0">{titulo}</h2>
          <p className="text-[12.5px] text-ink-3 leading-snug mt-0.5">{sub}</p>
        </div>
        {!b.cargando && n > 0 && (
          <div className="hidden sm:block text-right shrink-0">
            <div className="tabular text-[17px] font-semibold text-rendi-pos">~{mm.usd(total)}</div>
            <div className="text-[11.5px] text-ink-3">a confirmar</div>
          </div>
        )}
      </div>

      {b.cargando && (
        <>
          <div className="flex flex-wrap gap-1.5 px-4 pb-3.5 sm:pl-[60px]" aria-hidden="true">
            {b.tickers.map((t, i) => (
              <span key={t} style={{ '--i': i }}
                className="chip-escaneando inline-flex items-center rounded-full border border-line bg-bg-2 px-2 py-0.5 text-[11.5px] font-semibold text-ink-2">
                {t}
              </span>
            ))}
          </div>
          <div className="barrido-escaneo" aria-hidden="true" />
        </>
      )}

      {!b.cargando && (
        <div className="border-t border-line">
          {tarjetas.map(({ it, c }, i) => (
            <Fila key={it.key} it={it} i={i} confirmado={c}
              abierta={abierta === it.key} onAbrir={() => abrir(it.key)}>
              {c ? (
                <Comprobante c={c} onDeshacer={() => deshacer(c)} deshaciendo={enVuelo.activo(it.key)} />
              ) : editando === it.key ? (
                <Edicion it={it} guardando={enVuelo.activo(it.key)}
                  onCancelar={() => setEditando(null)}
                  onGuardar={(montos) => confirmar(it, montos)} />
              ) : (
                <div className="space-y-3.5">
                  <Calculo it={it} animar={animada === it.key} />
                  <p className="flex gap-1.5 text-[12px] text-ink-3">
                    <Info size={13} className="shrink-0 mt-0.5" aria-hidden="true" />
                    Compará con lo que te muestra {it.broker}. Si no coincide, editalo: se anota tu número.
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    <button type="button" disabled={enVuelo.activo(it.key)}
                      onClick={() => confirmar(it, { bruto: it.bruto, impuesto: it.impuesto, otros: it.otros, comisionPesos: it.comisionPesos })}
                      className="inline-flex items-center gap-1.5 rounded bg-data-violet px-3.5 py-2 text-[13px] font-medium text-white hover:bg-rendi-violet-hover disabled:opacity-60 transition">
                      {enVuelo.activo(it.key) ? <Loader2 size={14} className="animate-spin motion-reduce:animate-none" /> : <Check size={14} />}
                      {enVuelo.activo(it.key) ? 'Registrando…' : 'Confirmar cobro'}
                    </button>
                    <button type="button" onClick={() => setEditando(it.key)}
                      className="rounded border border-line-2 bg-bg-1 px-3.5 py-2 text-[13px] font-medium text-ink-0 hover:bg-bg-2 transition">
                      Editar montos
                    </button>
                    <button type="button" onClick={() => saltar(it)} disabled={enVuelo.activo(it.key)}
                      className="px-2 py-2 text-[13px] text-ink-2 hover:text-ink-0">
                      No lo cobré
                    </button>
                  </div>
                </div>
              )}
            </Fila>
          ))}
          {b.proximos.map((it) => (
            <div key={it.key} className="grid grid-cols-[36px_minmax(0,1fr)_auto] gap-3 items-center px-4 py-3 border-t border-line bg-bg-2/40">
              <span className="opacity-60"><AssetLogo asset={it.ticker} size={36} /></span>
              <span className="min-w-0">
                <span className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-[13px] font-semibold text-ink-1">{it.ticker}</span>
                  <span className="rounded-sm border border-line bg-bg-2 px-1.5 text-[11px] text-ink-2">{it.broker}</span>
                </span>
                <span className="block text-[12px] text-ink-3 tabular mt-0.5">Corte {ddmm(it.exDate)} · todavía no llegó, aparece acá alrededor del {ddmm(it.pagoEstimado)}</span>
              </span>
              <span className="text-right">
                <span className="block tabular text-[15px] text-ink-2">~{mm.usd(it.neto)}</span>
                <span className="block text-[11.5px] text-ink-3">próximo</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
    </Oculto.Provider>
  )
}
