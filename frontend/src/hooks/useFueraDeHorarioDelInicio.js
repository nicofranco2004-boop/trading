// useFueraDeHorarioDelInicio — lo que la sección de pre/post mercado del inicio
// de la COMPU (components/home/FueraDeHorarioMercado) necesita, pedido por la
// pantalla desde que se abre: el fuera de horario, con las listas y con tus
// símbolos, y tu cartera. `listo` dice que la sección ya sabe si va y con qué
// forma; el inicio la espera antes de mostrarse (useEsperaDeLaLista, `ademas`).
// ═══════════════════════════════════════════════════════════════════════════
// Por qué (CLS 0,35 en el inicio de la compu con la lista cerrada, a las 18:30
// del 17/11/2026): la sección armaba la cartera ella sola en cuatro pasos, uno
// detrás del otro —¿hay sesión? → posiciones, brokers y dólar → precios → el
// fuera de horario con tus símbolos—, y el inicio no la esperaba. Aparecía
// después, arriba de todo (+700 px), y un rato más tarde cambiaba a la pestaña
// «Tus activos», con listas de otro largo. Como la lista de primeros pasos el
// 16/11 y el anticipo del celular el 17: una pieza de arriba que carga y decide
// sola cuánto ocupa, sin que la pantalla lo sepa.
//
// Ahora son dos pasos y la pantalla los espera (con tope):
//   1. al abrir, juntos: el fuera de horario con las listas (dice si hay
//      sesión) y posiciones, brokers y dólar;
//   2. si hay sesión, juntos: el fuera de horario con tus símbolos y los precios.
// En la rueda (de 11:30 a 18) el paso 1 contesta «no hay sesión» y listo: ni
// tus símbolos ni los precios se piden. Lo que se pide de más en la rueda son
// posiciones, brokers y dólar, a cambio de un paso menos el resto del día.
// La FORMA de la sección (qué pestañas, cuántas filas) no depende de los
// precios, sólo de la respuesta y de qué tenés; los precios ponen los montos, y
// también se esperan para que no se vean montos sin precio.
//
// El celular no usa esto: su inicio ya tiene la cartera y le pasa a la sección
// la misma respuesta que usa para el anticipo (HomeMobile).

import { useEffect, useMemo, useState } from 'react'
import { api } from '../utils/api'
import { buildPriceSymbols } from '../utils/valuation'
import { useCurrency, pickFinancialRate } from '../contexts/CurrencyContext'
import { useFueraDeHorarioDeConEstado } from './useFueraDeHorario'
import { useRelojVisible } from './useRelojVisible'

// La cartera se vuelve a pedir cada 10 minutos con la pestaña a la vista (la de
// Cartera se refresca cada 90 s): no congelarla (auditoría 2026-10-15).
const REFRESCO_CARTERA_MS = 10 * 60 * 1000

/**
 * @param {boolean} activo  false en el celular: no pide nada y `listo` es true
 * @returns {{ cartera: object|null, datos: object|null, listo: boolean }}
 *   `cartera` = { positions, brokers, prices, tcValuacion, tcCedear, tcCripto }
 *   (o null si todavía no llegó); `datos` = la respuesta de GET /fuera-de-horario.
 */
export function useFueraDeHorarioDelInicio({ activo = true } = {}) {
  const { valuationDollar } = useCurrency()
  const [base, setBase] = useState(null)        // { positions, brokers, dolar }
  const [prices, setPrices] = useState(null)    // null = todavía no contestó
  const [vuelta, setVuelta] = useState(0)
  useRelojVisible(() => { if (activo) setVuelta(v => v + 1) }, REFRESCO_CARTERA_MS)

  // Paso 1 (y cada refresco): la cartera. Mientras viaja un refresco queda la
  // que había: si se vaciaba, «Tus activos» desaparecía y volvía, y la sección
  // saltaba cada 10 minutos.
  useEffect(() => {
    if (!activo) return undefined
    let vivo = true
    Promise.all([api.get('/positions'), api.get('/brokers'), api.get('/dolar').catch(() => null)])
      .then(([positions, brokers, dolar]) => {
        if (vivo) setBase({ positions: positions || [], brokers: brokers || [], dolar })
      })
      // Sin cartera la sección sigue: índices, ADRs y populares.
      .catch(() => { if (vivo) setBase(b => b || { positions: [], brokers: [], dolar: null }) })
    return () => { vivo = false }
  }, [activo, vuelta])

  // Hasta saber que hay sesión se piden sólo las listas; con sesión y cartera,
  // también tus símbolos (paso 2). Una vez que hubo sesión se siguen pidiendo:
  // si termina con la pantalla abierta, la respuesta lo dice y la sección se va.
  const [huboSesion, setHuboSesion] = useState(false)
  const conTuyos = activo && huboSesion && base
  const { datos, respondio } = useFueraDeHorarioDeConEstado(
    conTuyos ? base.positions : null, conTuyos ? base.brokers : null, { listas: activo })
  useEffect(() => { if (datos?.sesion) setHuboSesion(true) }, [datos?.sesion])

  // Paso 2: los precios, sólo si hay sesión (para los montos de la sección).
  useEffect(() => {
    if (!conTuyos) return undefined
    const syms = buildPriceSymbols(base.positions, base.brokers).join(',')
    if (!syms) { setPrices({}); return undefined }
    let vivo = true
    api.get(`/prices?symbols=${syms}`).catch(() => ({}))
      .then(p => { if (vivo) setPrices(p || {}) })
    return () => { vivo = false }
  }, [conTuyos, base])

  const cartera = useMemo(() => {
    if (!base) return null
    const tc = pickFinancialRate(base.dolar, valuationDollar) || 1415
    return { positions: base.positions, brokers: base.brokers, prices: prices || {},
      tcValuacion: tc, tcCedear: tc, tcCripto: base.dolar?.cripto?.venta }
  }, [base, prices, valuationDollar])

  // Lista: contestó la dirección de AHORA y, si hay sesión, ya se pidió con tus
  // símbolos (`conTuyos`: en el dibujo en que llega la cartera la dirección
  // cambia, y `respondio` vuelve a false hasta la respuesta nueva) y llegaron
  // los precios. En la rueda alcanza con la primera respuesta.
  const listo = !activo || (respondio && (!datos?.sesion || (!!conTuyos && prices !== null)))
  return { cartera, datos, listo }
}
