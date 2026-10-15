// usePesosDelPeriodo — los montos de Reportes en la moneda en que se mira, cada
// uno al dólar de su fecha (ver utils/periodoEnPesos.js).
//
// `PesosDelPeriodoProvider` va UNA vez arriba de Reportes: trae /monthly y
// /brokers (los pesos que se pusieron viven ahí) sólo cuando se mira en pesos, y
// todas las tarjetas leen de él. Sin el provider (una tarjeta montada en otra
// pantalla) la regla es la misma, sin los pesos guardados: los depósitos van al
// dólar del cierre del período.
//
// `PeriodoEnVista` lo pone cada tarjeta para lo que tiene adentro (la evidencia
// de los hallazgos no sabe de qué período es).

import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { useCurrency, fmtConvertedRaw } from '../contexts/CurrencyContext'
import { useFxHistory, useDolarMensual } from './useFxHistory'
import { api } from '../utils/api'
import { crearPesosDelPeriodo } from '../utils/periodoEnPesos'

const Ctx = createContext(null)
export const PeriodoEnVista = createContext(null)

function usePesos({ monthly = null, brokers = null, broker = 'global' } = {}) {
  const { currency, tcValuacion } = useCurrency()
  const { getRateForDate, fxKey } = useFxHistory(tcValuacion)
  const { dolarMes } = useDolarMensual()
  return useMemo(() => {
    const p = crearPesosDelPeriodo({
      moneda: currency, tcHoy: tcValuacion, tcEnFecha: getRateForDate, dolarMes,
      monthly, brokers, broker,
    })
    // Formatea un monto que YA está en `p.moneda` (no reconvierte).
    const fmt = (v, opts) => fmtConvertedRaw(v, p.moneda, opts)
    return { ...p, fmt }
  }, [currency, tcValuacion, fxKey, dolarMes, monthly, brokers, broker])  // eslint-disable-line react-hooks/exhaustive-deps
}

export function PesosDelPeriodoProvider({ broker = 'global', children }) {
  const { currency } = useCurrency()
  const [datos, setDatos] = useState({ monthly: null, brokers: null })
  useEffect(() => {
    if (currency !== 'ARS') return
    let vivo = true
    Promise.all([api.get('/monthly'), api.get('/brokers')])
      .then(([monthly, brokers]) => { if (vivo) setDatos({ monthly: monthly || [], brokers: brokers || [] }) })
      .catch(() => {})
    return () => { vivo = false }
  }, [currency])
  const valor = usePesos({ ...datos, broker })
  return <Ctx.Provider value={valor}>{children}</Ctx.Provider>
}

export function usePesosDelPeriodo() {
  const deArriba = useContext(Ctx)
  const propio = usePesos()
  return deArriba || propio
}
