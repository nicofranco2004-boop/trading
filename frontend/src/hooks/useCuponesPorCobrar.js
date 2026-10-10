// useCuponesPorCobrar — los datos y las acciones de la bandeja de cobros de bonos.
//
// Gemelo de hooks/useDividendosPorCobrar.js. Un solo dueño para Cartera de
// escritorio y de celular (R6: no se bifurca por viewport): cada página monta
// <CuponesPorCobrar> con sus posiciones y sus brokers, y el pedido vive acá.
//
// Pide al servidor:
//   · /operations              — para no proponer lo que ya está anotado (a mano
//                                o importado: ver pendingCashflows.cobroRegistrado);
//   · /bonds/cashflow/skips    — los "No lo cobré".
// y arma la bandeja con utils/pendingCashflows.js. Confirmar va por
// POST /bonds/cashflow/pago: cupón y amortización en la misma transacción.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../utils/api'
import { detectPendingCashflows, detectCobrosImportados, cobroRegistrado, esCobroAMano } from '../utils/pendingCashflows'
import { generateSchedule, cerOptsFor } from '../utils/bondSchedule'
import { isBondTicker } from '../utils/tickers'
import { hoyISO } from '../utils/fecha'

export function useCuponesPorCobrar({ positions, brokers, cerSeries, mep }) {
  const bonos = useMemo(() => [...new Set((positions || [])
    .filter(p => !p.is_cash && p.quantity > 0 && isBondTicker(p.asset))
    .map(p => p.asset))].sort(), [positions])
  const clave = bonos.join(',')
  const [operaciones, setOperaciones] = useState(null)
  const [salteados, setSalteados] = useState([])
  const [cargando, setCargando] = useState(false)
  // Los confirmados en esta visita: la tarjeta queda mostrando "Así quedó
  // anotado" hasta que se sale de Cartera (la próxima vez ya no está).
  const [confirmados, setConfirmados] = useState([])
  const pedido = useRef(0)

  // Se vuelve a pedir lo anotado cada vez que Cartera recarga sus posiciones (la
  // lista cambia de identidad en cada recarga): después de confirmar acá, de un
  // "+ Cupón" en la ficha del bono, de un borrado en Movimientos. Antes sólo se
  // pedía al cambiar la LISTA de bonos, y un cobro cargado desde la ficha seguía
  // apareciendo como pendiente (confirmarlo daba "ya está anotado").
  const primeraVez = useRef(true)
  useEffect(() => {
    if (!clave) { setOperaciones(null); return undefined }
    const n = ++pedido.current
    // El escaneo se muestra sólo la primera vez; después se actualiza en silencio
    // (si no, el comprobante de lo recién confirmado parpadeaba).
    if (primeraVez.current) setCargando(true)
    Promise.all([
      api.get('/operations').catch(() => null),
      api.get('/bonds/cashflow/skips').catch(() => null),
    ]).then(([ops, sk]) => {
      if (n !== pedido.current) return
      // Si el pedido falla, se queda con lo que había (o sin bandeja la primera
      // vez): con una lista vacía TODO parecería pendiente, dos años de pagos.
      if (ops) setOperaciones(ops)
      if (sk) setSalteados(sk)
    }).finally(() => {
      if (n === pedido.current) { setCargando(false); primeraVez.current = false }
    })
    return undefined
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clave, positions])

  const opciones = useMemo(() => ({ brokers, cerSeries, tcRef: mep }), [brokers, cerSeries, mep])

  const pendientes = useMemo(() => (operaciones
    ? detectPendingCashflows(positions || [], operaciones, salteados, opciones) : []),
  [positions, operaciones, salteados, opciones])

  const importados = useMemo(() => (operaciones
    ? detectCobrosImportados(positions || [], operaciones, opciones) : []),
  [positions, operaciones, opciones])

  // Los confirmados no vuelven a la lista de pendientes (ya hay una operación),
  // pero la tarjeta sigue a la vista con su comprobante.
  const paraConfirmar = useMemo(() => {
    const yaVistos = new Set(confirmados.map(c => c.item.key))
    return pendientes.filter(it => !yaVistos.has(it.key))
  }, [pendientes, confirmados])

  /** El efectivo de una cuenta ANTES de confirmar, para mostrar "antes → después". */
  const efectivoDe = useCallback((cuenta) => {
    const c = (positions || []).find(p => p.is_cash && p.broker === cuenta)
    return c ? Number(c.invested) || 0 : 0
  }, [positions])

  /**
   * montos: { cupon, amort, comision, cuenta? }. Los montos están en la moneda de
   * la cuenta donde entran: `montos.cuenta` si el usuario eligió otra (la de
   * pesos), o `item.cuenta`. El nominal amortizado (a la par, en nominales del
   * bono) viaja aparte para que el servidor no lo confunda con los pesos.
   */
  const confirmar = useCallback(async (item, montos) => {
    const cuerpo = {
      broker: item.broker,
      asset: item.asset,
      date: item.date,
      coupon_amount: montos.cupon,
      amort_amount: montos.amort,
      commissions: montos.comision || 0,
      cash_broker: montos.cuenta || item.cuenta,
      notes: montos.editado ? 'Confirmado desde la bandeja (montos editados)' : 'Confirmado desde la bandeja',
    }
    if (montos.amort > 0) {
      // Con los nominales SIN redondear: redondeados, 111,12 contra una amortización de 111,11.
      cuerpo.face_amortized = +((item.nominalesExactos ?? item.nominales) * (item.amortPct || 0) / 100).toFixed(6) || undefined
    }
    const r = await api.post('/bonds/cashflow/pago', cuerpo)
    const cuenta = r.partes?.[0]?.cash_broker || cuerpo.cash_broker
    const antes = efectivoDe(cuenta)
    setConfirmados(prev => [...prev, { item, montos, resultado: r, cuenta, antes,
                                       editado: !!montos.editado }])
    // Que la detección vea las operaciones nuevas (la tarjeta no vuelve como pendiente).
    setOperaciones(prev => [...(prev || []), ...(r.partes || []).map(pt => ({
      id: pt.operation_id, op_type: pt.op_type, broker: pt.cash_broker, asset: pt.asset,
      date: item.date, quantity: pt.amount_net, pnl_usd: pt.ganancia,
    }))])
    return r
  }, [efectivoDe])

  // "Deshacer" en el comprobante: borra las operaciones por la MISMA puerta que
  // Movimientos (devuelve el efectivo y, si amortizó, el nominal) y la tarjeta
  // vuelve a quedar pendiente.
  // Cada parte se borra por separado: si una falla, las ya borradas se
  // descuentan igual (un reintento no vuelve a pedir lo que ya no existe).
  const deshacerCobro = useCallback(async (confirmado) => {
    const ids = (confirmado.resultado.partes || []).map(pt => pt.operation_id).filter(Boolean)
    const borradas = []
    try {
      for (const id of ids) {
        if (confirmado.borradas?.includes(id)) { borradas.push(id); continue }
        try {
          await api.delete(`/movements/op-${id}-cobro`)
        } catch (e) {
          if (!/404|no encontrad|not found/i.test(String(e?.message || ''))) throw e
        }
        borradas.push(id)
      }
    } finally {
      confirmado.borradas = borradas
      setOperaciones(prev => (prev || []).filter(o => !borradas.includes(o.id)))
    }
    setConfirmados(prev => prev.filter(c => c.item.key !== confirmado.item.key))
  }, [])

  const saltar = useCallback(async (item) => {
    await api.post('/bonds/cashflow/skip', { broker: item.broker, asset: item.asset, date: item.date, reason: null })
    setSalteados(prev => [...prev, { broker: item.broker, asset: item.asset, date: item.date }])
  }, [])

  const volverASugerir = useCallback(async (item) => {
    const q = new URLSearchParams({ broker: item.broker, asset: item.asset, date: item.date })
    await api.delete(`/bonds/cashflow/skip?${q}`)
    setSalteados(prev => prev.filter(s => !(s.broker === item.broker && s.asset === item.asset && s.date === item.date)))
  }, [])

  /**
   * El cronograma chico de la tarjeta: los dos pagos anteriores, este y los dos
   * siguientes. Cada punto dice si ya está anotado (importado o confirmado), si
   * espera confirmación, o cuánto se estima que va a pagar.
   */
  const cronogramaDe = useCallback((item, confirmado) => {
    const sched = generateSchedule(item.asset, cerOptsFor(item.position, cerSeries)) || []
    const i = sched.findIndex(x => x.date === item.date)
    if (i < 0) return []
    const pendientesDelBono = new Set(pendientes.filter(x => x.asset === item.asset && x.broker === item.broker).map(x => x.date))
    const m = item.currency === 'ARS' ? '$' : 'US$'
    return sched.slice(Math.max(0, i - 2), i + 3).filter(x => (x.total || 0) > 0).map(x => {
      if (x.date === item.date) return confirmado
        ? { date: x.date, estado: 'ok', rotulo: 'confirmado' }
        : { date: x.date, estado: 'ahora', rotulo: 'a confirmar' }
      if (x.date > item.date && x.date > hoyISO()) {
        return { date: x.date, estado: 'futuro',
                 rotulo: `~${m} ${Math.round(x.total * item.nominales / 100).toLocaleString('es-AR')}` }
      }
      const op = cobroRegistrado(operaciones || [], item.position, x.date, brokers)
      if (op) return { date: x.date, estado: 'ok', rotulo: esCobroAMano(op) ? 'confirmado' : 'importado' }
      if (pendientesDelBono.has(x.date)) return { date: x.date, estado: 'ahora', rotulo: 'a confirmar' }
      return { date: x.date, estado: 'nada', rotulo: 'sin registro' }
    })
  }, [cerSeries, pendientes, operaciones, brokers])

  return {
    bonos, cronogramaDe, cargando,
    paraConfirmar, importados, confirmados,
    confirmar, deshacerCobro, saltar, volverASugerir,
  }
}
