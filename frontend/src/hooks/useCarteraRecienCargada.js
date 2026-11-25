// useCarteraRecienCargada — «esto es lo que tenés hoy», justo después del
// primer archivo: el valor de la cartera a precios de mercado, lo invertido, la
// ganancia, cuántas posiciones en cuántas cuentas de broker y el mejor y el
// peor activo.
// ═══════════════════════════════════════════════════════════════════════════
// UN cálculo, dos pantallas: /bienvenida (pages/FirstInsight.jsx, el primer
// import de una cuenta vieja) y el paso «tu cartera» de la bienvenida
// obligatoria (pages/Onboarding.jsx). Antes vivía adentro de FirstInsight; si
// cada pantalla tuviera su copia, el mismo día dirían dos números distintos.
// La valuación es la de toda la app: `computeBrokerValue` por broker.
//
// Pide /positions, /brokers, /dolar y los precios. Devuelve `{ loading, stats }`:
// `stats` es null si no hay posiciones o brokers. NO dibuja nada: lo muestra
// quien lo llama, y quien lo muestra mira «Ocultar saldos» (usePrivacy).

import { useEffect, useMemo, useState } from 'react'
import { api } from '../utils/api'
import { computeBrokerValue, priceSymbol, costInPesos, costInUsd, cryptoCostInUsd, cryptoUsdLotValue, pesoLotUsd, usdLotValue, isFciSym, trustMktValue, isArUsdBroker, buildPriceSymbols } from '../utils/valuation'
import { isCrypto, cryptoBrokerFactor } from '../utils/crypto'
import { useCurrency, pickFinancialRate } from '../contexts/CurrencyContext'
import { groupBrokersIntoAccounts } from '../utils/brokerAccounts'
import { cedearEspecieBase } from '../utils/tickers'

export function useCarteraRecienCargada() {
  const { valuationDollar, costBasis } = useCurrency()
  const [positions, setPositions] = useState([])
  const [brokers, setBrokers] = useState([])
  const [prices, setPrices] = useState({})
  const [dolar, setDolar] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let vivo = true
    Promise.all([
      api.get('/positions'),
      api.get('/brokers'),
      api.get('/dolar').catch(() => null),
    ]).then(async ([pos, bkrs, dol]) => {
      if (!vivo) return
      setPositions(pos || [])
      setBrokers(bkrs || [])
      setDolar(dol)
      // Fetch precios de los assets
      const arsBrokers = new Set((bkrs || []).filter(b => b.currency === 'ARS').map(b => b.name))
      // .BA por el PADRE: lote en pesos (currency='ARS') o sub-broker AR·USD → .BA;
      // acción AR en broker USD extranjero (Schwab) → ADR NYSE (ticker pelado).
      const usdSyms = [...new Set((pos || []).filter(p => !arsBrokers.has(p.broker) && !p.is_cash).map(p => (isArUsdBroker(p.broker) || costInPesos(p)) ? priceSymbol(p.asset, true, p.asset_type) : priceSymbol(p.asset, false, p.asset_type)))]
      const arsSyms = [...new Set((pos || []).filter(p => arsBrokers.has(p.broker) && !p.is_cash).map(p => priceSymbol(p.asset, true)))]
      // + las keys que lee el motor (buildPriceSymbols): esta lista pedía BTC.BA
      // para la cripto de un "· USD" y el motor lee BTC (quedaba al costo).
      const all = [...new Set([...buildPriceSymbols(pos || [], bkrs || []), ...usdSyms, ...arsSyms])].join(',')
      if (all) {
        try {
          const data = await api.get(`/prices?symbols=${all}`)
          if (vivo) setPrices(data || {})
        } catch {}
      }
    }).catch(() => {}).finally(() => { if (vivo) setLoading(false) })
    return () => { vivo = false }
  }, [])

  const tcValuacion = pickFinancialRate(dolar, valuationDollar) || 1415
  const tcCedear = pickFinancialRate(dolar, valuationDollar) || tcValuacion  // dólar financiero p/ CEDEARs
  const tcCripto = dolar?.cripto?.venta

  const stats = useMemo(() => {
    if (!brokers.length || !positions.length) return null
    let value = 0, invested = 0
    for (const b of brokers) {
      const r = computeBrokerValue(positions, prices, b, tcValuacion, tcCedear, tcCripto, costBasis)
      value += r.value || 0
      invested += r.invested || 0
    }
    const pnl = value - invested
    const pnlPct = invested > 0 ? pnl / invested : 0

    // Mejor y peor activo por P&L USD individual
    const arsBrokers = new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name))
    const exchangeBrokers = new Set((brokers || []).filter(b => b.is_exchange).map(b => b.name))
    const byAsset = new Map()
    const porEspecie = new Map()
    for (const p of positions) {
      if (p.is_cash) continue
      const isARS = arsBrokers.has(p.broker)
      const cost = (p.invested || 0) + (p.commissions || 0)
      let valueUsd = null, pnlUsd = null
      if (isARS && costInUsd(p)) {
        // Espejo de costInPesos: lote de COSTO EN DÓLARES (bono/ON/FCI-USD, o CEDEAR
        // comprado en dólar-MEP → currency='USD') que vive en un broker ARS (Balanz).
        // El costo YA está en USD (sin ÷blue); el valor va por el tipo de instrumento
        // (usdLotValue, que ya clampea). Sin esto, la rama isARS de abajo dividía el
        // costo USD por el blue → colapsaba (~1/MEP) y el ranking best/worst se rompía.
        // Gateado a broker ARS: una acción US genuina (currency='USD' en Schwab/IBKR)
        // NO entra acá (usdLotValue le armaría 'AAPL.BA', inexistente) → va al else US.
        const u = usdLotValue(p, prices, tcCedear)
        valueUsd = u.valueUsd
        pnlUsd = valueUsd - u.investedUsd
      } else if (isARS && cryptoCostInUsd(p)) {
        // Lo mismo para la CRIPTO comprada en dólares (costInUsd la excluye): sin
        // esto caía abajo, su costo USD se dividía por el dólar y quedaba en ~0.
        const c = cryptoUsdLotValue(p, prices, { cedearRate: tcCedear, tcCripto, isExchange: exchangeBrokers.has(p.broker) })
        valueUsd = c.valueUsd
        pnlUsd = valueUsd - c.investedUsd
      } else if (isARS) {
        const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true)]
        if (priceArs != null) {
          // Guard anti-distorsión: mkt y costo comparados en ARS (mismas unidades).
          // Un ×100 (bono per-100 leído per-1) → cae a costo, P&L 0.
          const mktArs = priceArs * (p.quantity || 0)
          const trust = trustMktValue(mktArs, cost, p.asset_type, p.price_override != null)
          valueUsd = (trust ? mktArs : cost) / tcValuacion
          pnlUsd = valueUsd - cost / tcValuacion
        }
      } else if (costInPesos(p)) {
        // Lote en PESOS en cuenta USD → costo Y valor por el MEP (no peso como dólar).
        const u = pesoLotUsd(p, prices, tcCedear)
        const trust = trustMktValue(u.valueUsd, u.investedUsd, p.asset_type, p.price_override != null)
        valueUsd = trust ? u.valueUsd : u.investedUsd
        pnlUsd = valueUsd - u.investedUsd
      } else if ((p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker)) && !isCrypto(p.asset) && !isFciSym(p.asset) && p.price_override == null) {
        // Instrumento de BYMA en cuenta USD (CEDEAR o acción AR de un sub-broker
        // "· USD"): se valúa por su precio LOCAL .BA (ARS) ÷ MEP, NO por el ticker
        // US (un CEDEAR vale 15-100× menos que la acción → antes se inflaba 3-29×).
        // Espeja computeBrokerValue (rama USD). Broker USD → cost YA está en USD.
        // El FCI-USD NO entra: su precio es el NAV en USD (va al else, sin ÷MEP).
        const priceArs = prices[priceSymbol(p.asset, true, p.asset_type)]
        const mktUsd = priceArs != null ? (priceArs * (p.quantity || 0)) / tcCedear : null
        valueUsd = (mktUsd != null && trustMktValue(mktUsd, cost, p.asset_type)) ? mktUsd : cost
        pnlUsd = valueUsd - cost
      } else {
        // Key normalizada primero (la que pide el fetch: 'BRK.B' se pide como
        // 'BRK-B'), con fallback a la cruda para el last-known del cron y los
        // payloads legacy. Leer sólo la cruda dejaba el lote al costo, P&L 0.
        const price = p.price_override ?? prices[priceSymbol(p.asset, false, p.asset_type)] ?? prices[p.asset]
        if (price != null) {
          // Premium dólar-cripto (broker no-exchange) a valor Y costo → ranking
          // best/worst consistente con el resto de la app. f=1 para todo lo demás.
          const f = cryptoBrokerFactor(p.asset, exchangeBrokers.has(p.broker), p.price_override != null, tcCripto, tcCedear, isARS ? 'ARS' : 'USD')
          // Guard anti-distorsión: mkt vs costo en USD sin factor (mismas unidades),
          // luego escala por f (igual que computeBrokerValue). Un ×100/colisión → costo.
          const mkt = price * (p.quantity || 0)
          const trust = trustMktValue(mkt, cost, p.asset_type, p.price_override != null)
          valueUsd = (trust ? mkt : cost) * f
          pnlUsd = valueUsd - cost * f
        }
      }
      if (pnlUsd == null) continue
      const cur = byAsset.get(p.asset) || { asset: p.asset, pnl_usd: 0, value_usd: 0 }
      cur.pnl_usd += pnlUsd
      cur.value_usd += (valueUsd || 0)
      byAsset.set(p.asset, cur)
      // Cuánto vale cada ACTIVO (no cada lote): la entrada que piden los
      // hallazgos de concentración de utils/diagnostics.js (`pieData`). En
      // Argentina la pata en pesos y la en dólares del mismo CEDEAR son UN activo:
      // se juntan por su especie, como hace Diagnóstico (pages/Insights.jsx).
      const enBolsaAr = isARS || isArUsdBroker(p.broker) || costInPesos(p)
      const especie = enBolsaAr ? cedearEspecieBase(p.asset) : (p.asset || '').toUpperCase()
      porEspecie.set(especie, (porEspecie.get(especie) || 0) + (valueUsd || 0))
    }
    const pieData = [...porEspecie.entries()]
      .map(([name, v]) => ({ name, value: +v.toFixed(2) }))
      .filter(x => x.value > 0)
      .sort((a, b) => b.value - a.value)
    const arr = Array.from(byAsset.values())
    arr.sort((a, b) => b.pnl_usd - a.pnl_usd)
    const best = arr[0] || null
    const worst = arr[arr.length - 1] || null
    const positionCount = positions.filter(p => !p.is_cash).length
    // CUENTAS, no filas de `brokers`: al subir el archivo de Cocos el importador
    // crea solo la pata «Cocos · USD» (compras de MEP, depósitos en dólares) y
    // contar filas decía «en 2 brokers» después de subir UNO. El mismo criterio
    // que Cartera (utils/brokerAccounts.js).
    const brokerCount = groupBrokersIntoAccounts(brokers).length

    return { value, invested, pnl, pnlPct, best, worst, positionCount, brokerCount, pieData }
  }, [positions, brokers, prices, tcValuacion, tcCedear, tcCripto, costBasis])

  // positions, brokers y tcValuacion van afuera para los hallazgos que los miran
  // (el efectivo de utils/diagnostics.js): los mismos con los que se valuó.
  return { loading, stats, positions, brokers, tcValuacion }
}
