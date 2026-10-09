// useDividendosPorCobrar — los datos y las acciones de la bandeja de dividendos.
//
// Un solo dueño para Cartera de escritorio y de celular (R6: no se bifurca por
// viewport): cada página monta <DividendosPorCobrar> con sus posiciones y sus
// brokers, y el pedido de datos vive acá.
//
// Pide al servidor:
//   · /dividendos/historial — lo que pagó cada empresa + las reglas de descuento
//     (los porcentajes viven en backend/dividendos.py, no acá);
//   · /dividendos/salteados — los "No lo cobré";
//   · /operations           — para no proponer lo que ya está anotado.
// y arma la bandeja con utils/dividendosPendientes.js.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../utils/api'
import { detectarDividendos, tickersParaHistorial } from '../utils/dividendosPendientes'

export function useDividendosPorCobrar({ positions, brokers, mep }) {
  const tickers = useMemo(() => tickersParaHistorial(positions), [positions])
  const clave = tickers.join(',')
  const [historial, setHistorial] = useState(null)
  const [operaciones, setOperaciones] = useState([])
  const [salteados, setSalteados] = useState([])
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState(null)
  // Los confirmados en esta visita: la tarjeta queda mostrando "Así quedó
  // anotado" hasta que se sale de Cartera (la próxima vez ya no está).
  const [confirmados, setConfirmados] = useState([])
  const pedido = useRef(0)

  useEffect(() => {
    if (!clave) { setHistorial(null); return undefined }
    const n = ++pedido.current
    setCargando(true); setError(null)
    Promise.all([
      api.get(`/dividendos/historial?tickers=${encodeURIComponent(clave)}`),
      api.get('/dividendos/salteados').catch(() => []),
      api.get('/operations').catch(() => []),
    ]).then(([h, s, ops]) => {
      if (n !== pedido.current) return
      setHistorial(h); setSalteados(s || []); setOperaciones(ops || [])
    }).catch((e) => {
      if (n === pedido.current) setError(e)
    }).finally(() => {
      if (n === pedido.current) setCargando(false)
    })
    return undefined
  }, [clave])

  const bandeja = useMemo(() => detectarDividendos({
    positions, historial, operaciones, salteados, brokers, mep,
  }), [positions, historial, operaciones, salteados, brokers, mep])

  // Los confirmados no vuelven a la lista de pendientes (ya hay una operación),
  // pero la tarjeta sigue a la vista con su comprobante.
  const paraConfirmar = useMemo(() => {
    const yaVistos = new Set(confirmados.map(c => c.item.key))
    return bandeja.paraConfirmar.filter(it => !yaVistos.has(it.key))
  }, [bandeja, confirmados])

  /** El efectivo de una cuenta ANTES de confirmar, para mostrar "antes → después". */
  const efectivoDe = useCallback((cuenta) => {
    const c = (positions || []).find(p => p.is_cash && p.broker === cuenta)
    return c ? Number(c.invested) || 0 : 0
  }, [positions])

  const confirmar = useCallback(async (item, montos) => {
    const cuerpo = {
      broker: item.broker,
      asset: item.ticker,
      ex_date: item.exDate,
      fecha: item.pagoEstimado <= historial.hoy ? item.pagoEstimado : historial.hoy,
      bruto: montos.bruto,
      impuesto: montos.impuesto,
      otros: montos.otros,
      comision_pesos: montos.comisionPesos,
      cedears: item.cedears,
    }
    const r = await api.post('/dividendos/cobro', cuerpo)
    const antes = efectivoDe(r.cuenta)
    setConfirmados(prev => [...prev, {
      item: { ...item, ...montos, neto: r.neto },
      resultado: r,
      antes,
      editado: !!montos.editado,
    }])
    // Que la detección vea la operación nueva (la tarjeta no vuelve como pendiente).
    setOperaciones(prev => [...prev, {
      op_type: 'Dividendo', broker: r.cuenta, asset: item.ticker, date: cuerpo.fecha,
      pnl_usd: r.ganancia_usd, id: r.operation_id,
    }])
    return r
  }, [historial, efectivoDe])

  // "Deshacer" en el comprobante: borra el movimiento por la MISMA puerta que
  // Movimientos (devuelve los dólares y la comisión en pesos) y la tarjeta
  // vuelve a quedar pendiente.
  const deshacerCobro = useCallback(async (confirmado) => {
    const id = confirmado.resultado.operation_id
    await api.delete(`/movements/op-${id}-cobro`)
    setConfirmados(prev => prev.filter(c => c.item.key !== confirmado.item.key))
    setOperaciones(prev => prev.filter(o => o.id !== id))
  }, [])

  const saltar = useCallback(async (item) => {
    await api.post('/dividendos/saltear', { broker: item.broker, asset: item.ticker, ex_date: item.exDate })
    setSalteados(prev => [...prev, { broker: item.broker, asset: item.ticker, ex_date: item.exDate }])
  }, [])

  const volverASugerir = useCallback(async (item) => {
    const q = new URLSearchParams({ broker: item.broker, asset: item.ticker, ex_date: item.exDate })
    await api.delete(`/dividendos/saltear?${q}`)
    setSalteados(prev => prev.filter(s => !(s.broker === item.broker && s.asset === item.ticker && s.ex_date === item.exDate)))
  }, [])

  return {
    tickers, cargando, error, hoy: historial?.hoy,
    paraConfirmar, proximos: bandeja.proximos, confirmados,
    confirmar, deshacerCobro, saltar, volverASugerir,
  }
}
