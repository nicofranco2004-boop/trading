// dividendosPendientes — qué dividendos ya pagaron las empresas y el usuario
// todavía no anotó. Es lo que llena la bandeja de Cartera.
// ════════════════════════════════════════════════════════════════════════════
// Por qué existe (2026-10-09): Rendi anunciaba los dividendos en Novedades pero
// nunca los anotaba. Sólo entraban importando el archivo del broker, y el 72 %
// de las cuentas se importó una sola vez. Ver backend/dividendos.py.
//
// Para cada tenencia de CEDEARs en un broker argentino y cada pago de la
// empresa en la ventana:
//   1. cuántos CEDEARs tenía el día de CORTE (los lotes comprados antes);
//   2. cuántas acciones de la empresa son (`underlyingShares`, la ÚNICA
//      conversión CEDEAR → acción de la app; sin ratio exacto, no hay tarjeta);
//   3. el dividendo = acciones × lo que pagó la empresa por acción;
//   4. menos el impuesto de EE.UU. y los otros descuentos, y la comisión en
//      pesos del broker. Los porcentajes NO viven acá: llegan del servidor
//      (`reglas`, en backend/dividendos.py), que los midió sobre 7.566 cobros.
//
// Y lo saca de la bandeja si:
//   · ya está anotado (`yaRegistrado`: MISMA regla que el servidor usa para
//     frenar un doble registro — si cambia una, cambia la otra);
//   · el usuario dijo "No lo cobré";
//   · no es el ÚLTIMO pago de la empresa (regla `solo_ultimo_pago`).
//
// Fuera de la primera etapa, a propósito (sin monto antes que un monto malo):
// acciones argentinas (el dato de Yahoo es el del ADR), empresas que no son de
// EE.UU. (otra retención, sin medir) y acciones en brokers del exterior.

import { underlyingShares } from './cedearRatio'
import { cedearEspecieBase, CEDEAR_EN_EEUU } from './tickers'

const DIA = 86400000

function sumarDias(iso, dias) {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d) + dias * DIA).toISOString().slice(0, 10)
}

const r2 = (n) => Math.round(n * 100) / 100

/** Los nombres de las cuentas del mismo broker (padre en pesos + "· USD"). */
export function familiaDeBroker(nombre, brokers = []) {
  const b = brokers.find(x => x.name === nombre)
  if (!b) return new Set([nombre])
  const padreId = b.parent_broker_id || b.id
  const out = new Set([nombre])
  for (const x of brokers) {
    if (x.id === padreId || x.parent_broker_id === padreId) out.add(x.name)
  }
  return out
}

/** El nombre del padre (para buscar la comisión en pesos por broker). */
function nombreBase(nombre, brokers) {
  const b = brokers.find(x => x.name === nombre)
  if (b?.parent_broker_id) {
    const p = brokers.find(x => x.id === b.parent_broker_id)
    if (p) return p.name
  }
  return nombre
}

/** Fracción de comisión en pesos para este broker (0 si no hay regla). Por
 *  PALABRA del nombre, no por pedazo: "Violeta Inversiones" contiene "iol" y se
 *  le cobraba la comisión de IOL (auditoría 2026-10-09). */
function comisionPesosPct(nombre, brokers, reglas) {
  const palabras = new Set(nombreBase(nombre, brokers).toLowerCase().split(/[^a-z0-9áéíóúñ]+/))
  for (const [clave, pct] of Object.entries(reglas?.comision_pesos || {})) {
    if (palabras.has(clave)) return pct
  }
  return 0
}

/** El símbolo de la acción en EE.UU. (lo que tiene Yahoo) para un CEDEAR:
 *  casi siempre el mismo; DISN es DIS, BRKB es BRK-B (utils/tickers). */
export function tickerEnEEUU(base) {
  return CEDEAR_EN_EEUU[base] || base
}

function metaDe(o) {
  if (!o?.undo_meta_json) return null
  if (typeof o.undo_meta_json === 'object') return o.undo_meta_json
  try { return JSON.parse(o.undo_meta_json) } catch { return null }
}

/**
 * yaRegistrado — ¿hay un 'Dividendo' que ya cuenta como el cobro de este corte?
 * Espejo de `dividendos.ya_registrado` en el servidor: mismo activo en la familia
 * del broker entre el corte y `ventana_ya_registrado` días después; o uno SIN
 * activo (Cocos no lo dice) con un monto parecido.
 */
export function yaRegistrado(operaciones, { familia, ticker, exDate, neto }, reglas) {
  const hasta = sumarDias(exDate, reglas?.ventana_ya_registrado ?? 45)
  const tol = reglas?.tolerancia_monto_sin_activo ?? 0.05
  let parecidos = 0
  for (const o of operaciones || []) {
    if (o.op_type !== 'Dividendo') continue
    if (!familia.has(o.broker)) continue
    // Un confirmado desde la bandeja trae su corte: cuenta por eso, sin mirar la fecha.
    const meta = metaDe(o)
    if (meta?.src === 'dividendo_bandeja' && meta.ex_date === exDate
        && (o.asset || '').trim().toUpperCase() === ticker) return true
    const d = (o.date || '').slice(0, 10)
    if (d < exDate || d > hasta) continue
    const a = (o.asset || '').trim().toUpperCase()
    if (a === ticker) return true
    if ((a === '' || a === '—') && neto > 0 && o.pnl_usd != null
        && Math.abs(Number(o.pnl_usd) - neto) <= tol * neto) parecidos += 1
  }
  // Sin activo: sólo si es el ÚNICO parecido (con dos no se sabe cuál es).
  return parecidos === 1
}

/**
 * detectarDividendos — la bandeja.
 *
 * @param {Object} p
 * @param {Array}  p.positions    lotes de /positions
 * @param {Object} p.historial    respuesta de /dividendos/historial ({hoy, reglas, tickers})
 * @param {Array}  p.operaciones  filas de /operations
 * @param {Array}  p.salteados    filas de /dividendos/salteados
 * @param {Array}  p.brokers      filas de /brokers
 * @param {number} p.mep          dólar para pasar la comisión a pesos
 * @returns {{paraConfirmar: Array, proximos: Array}}
 */
export function detectarDividendos({ positions, historial, operaciones, salteados, brokers, mep }) {
  const reglas = historial?.reglas
  const hoy = historial?.hoy
  const vacio = { paraConfirmar: [], proximos: [] }
  if (!reglas || !hoy) return vacio

  const desde = sumarDias(hoy, -(reglas.dias_hacia_atras ?? 120))
  const paises = new Set(reglas.paises_con_regla || [])

  // Lotes agrupados por (BROKER, empresa) — el broker es el par entero: la
  // cuenta en pesos y su "· USD". Agrupados por cuenta salían dos tarjetas del
  // MISMO cobro (150 CEDEARs en IOL y 50 en IOL · USD) y, como "ya anotado"
  // mira el par, confirmar una borraba la otra: se anotaba una parte
  // (auditoría 2026-10-09). La tarjeta lleva el nombre del padre, que es con
  // el que el servidor encuentra el par. Sólo lotes con el ratio EXACTO.
  const grupos = new Map()
  for (const p of positions || []) {
    if (p.is_cash || !(Number(p.quantity) > 0)) continue
    const eq = underlyingShares(p)
    if (!eq || eq.scale !== 'cedear' || eq.source !== 'table') continue
    const ticker = cedearEspecieBase(p.asset)
    if (!ticker) continue
    const broker = nombreBase(p.broker, brokers)
    const k = `${broker}|${ticker}`
    if (!grupos.has(k)) grupos.set(k, { broker, ticker, lotes: [] })
    grupos.get(k).lotes.push({ p, eq })
  }

  const out = { paraConfirmar: [], proximos: [] }
  for (const g of grupos.values()) {
    const emisor = historial.tickers?.[tickerEnEEUU(g.ticker)]
    if (!emisor) continue
    const esEtf = emisor.tipo === 'ETF'
    if (!esEtf && !paises.has(emisor.pais)) continue   // sin regla medida → sin monto
    const otrosPct = esEtf ? 0 : (reglas.otros_accion ?? 0)
    const familia = familiaDeBroker(g.broker, brokers)

    // Con `solo_ultimo_pago` (regla del servidor): de los cortes cuyo pago ya
    // tuvo que llegar, sólo el más reciente; los posteriores (todavía no
    // acreditados) siguen apareciendo como "próximos".
    const diasPago = reglas.dias_hasta_el_pago ?? 21
    const enVentana = (emisor.pagos || []).filter(p => p.ex_date >= desde && p.ex_date <= hoy)
    const yaPagados = enVentana.filter(p => sumarDias(p.ex_date, diasPago) <= hoy)
    const ultimoPagado = yaPagados.reduce((m, p) => (!m || p.ex_date > m.ex_date ? p : m), null)
    const aMirar = reglas.solo_ultimo_pago
      ? enVentana.filter(p => p === ultimoPagado || sumarDias(p.ex_date, diasPago) > hoy)
      : enVentana

    for (const pago of aMirar) {
      const exDate = pago.ex_date
      // Lo que tenía el día de corte: los lotes comprados ANTES. Un lote sin
      // fecha cuenta como tenido (los cargados sin fecha son viejos).
      const lotes = g.lotes.filter(({ p }) => !p.entry_date || p.entry_date.slice(0, 10) < exDate)
      const cedears = lotes.reduce((s, { p }) => s + Number(p.quantity), 0)
      const acciones = lotes.reduce((s, { eq }) => s + eq.shares, 0)
      if (!(acciones > 0)) continue

      const bruto = r2(acciones * pago.por_accion)
      const impuesto = r2(bruto * (reglas.impuesto_eeuu ?? 0))
      const otros = r2(bruto * otrosPct)
      const neto = r2(bruto - impuesto - otros)
      if (!(neto > 0)) continue
      if (yaRegistrado(operaciones, { familia, ticker: g.ticker, exDate, neto }, reglas)) continue
      if ((salteados || []).some(s => s.broker === g.broker && s.asset === g.ticker && s.ex_date === exDate)) continue

      const pct = comisionPesosPct(g.broker, brokers, reglas)
      const comisionPesos = mep > 0 ? r2(neto * pct * mep) : 0
      const pagoEstimado = sumarDias(exDate, reglas.dias_hasta_el_pago ?? 21)
      const item = {
        key: `${g.broker}|${g.ticker}|${exDate}`,
        broker: g.broker,
        ticker: g.ticker,
        tipo: esEtf ? 'ETF' : 'Acción',
        exDate,
        pagoEstimado,
        cedears,
        ratio: lotes[0]?.eq.ratio,
        acciones,
        porAccion: pago.por_accion,
        bruto, impuesto, otros, neto, comisionPesos,
        impuestoPct: reglas.impuesto_eeuu ?? 0,
        otrosPct,
      }
      ;(pagoEstimado <= hoy ? out.paraConfirmar : out.proximos).push(item)
    }
  }
  out.paraConfirmar.sort((a, b) => b.exDate.localeCompare(a.exDate))
  out.proximos.sort((a, b) => a.pagoEstimado.localeCompare(b.pagoEstimado))
  return out
}

/** Los tickers (acción en EE.UU.) que hay que pedirle al servidor. */
export function tickersParaHistorial(positions) {
  const out = new Set()
  for (const p of positions || []) {
    if (p.is_cash || !(Number(p.quantity) > 0)) continue
    const eq = underlyingShares(p)
    if (!eq || eq.scale !== 'cedear' || eq.source !== 'table') continue
    const t = cedearEspecieBase(p.asset)
    if (t) out.add(tickerEnEEUU(t))
  }
  return [...out].sort()
}
