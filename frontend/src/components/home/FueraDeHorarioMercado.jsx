// FueraDeHorarioMercado — la sección de Mercado que aparece SÓLO cuando Wall
// Street opera fuera de la rueda (pre-mercado o post-mercado).
//
//   · Los índices (vía SPY, QQQ y DIA) y cuánto se mueve tu cartera.
//   · Lo que más sube y lo que más baja, en tres pestañas: tus activos (con la
//     plata que te mueve cada uno), los ADRs argentinos y los populares.
//
// Los % salen de GET /fuera-de-horario (backend/fuera_de_horario.py) y la plata
// de utils/fueraDeHorario — la misma cuenta que Cartera y el Dashboard. Fuera
// de esas franjas la sección no existe: no deja un hueco ni un cartel.
//
// `cartera` = { positions, brokers, prices, tcValuacion, tcCedear, tcCripto }.
// El inicio del celular ya la tiene cargada y la pasa; el de la compu no carga
// la cartera, así que la sección la pide ella misma, y SÓLO cuando hay sesión
// (de 11 a 17, o de noche, no se pide nada de más).

import { useEffect, useMemo, useState } from 'react'
import { useFueraDeHorario } from '../../hooks/useFueraDeHorario'
import { simbolosFueraDeHorario, impactoFueraDeHorario, nombreDeSesion, estadoDeSesion } from '../../utils/fueraDeHorario'
import { IconoSesion, tonoDeSesion, montoFdh } from '../FueraDeHorario'
import { pctVar, pctColor, colorClass } from '../../utils/format'
import { api } from '../../utils/api'
import { buildPriceSymbols } from '../../utils/valuation'
import { useCurrency, pickFinancialRate } from '../../contexts/CurrencyContext'

const TOPE_LISTA = 5

// La cartera, para cuando la pantalla no la tiene a mano (el inicio de la compu).
function useCarteraPropia(activo) {
  const { valuationDollar } = useCurrency()
  const [c, setC] = useState(null)
  useEffect(() => {
    if (!activo || c) return
    let vivo = true
    ;(async () => {
      try {
        const [positions, brokers, dolar] = await Promise.all([
          api.get('/positions'), api.get('/brokers'), api.get('/dolar').catch(() => null),
        ])
        const syms = buildPriceSymbols(positions || [], brokers || []).join(',')
        const prices = syms ? await api.get(`/prices?symbols=${syms}`).catch(() => ({})) : {}
        const tc = pickFinancialRate(dolar, valuationDollar) || 1415
        if (vivo) setC({ positions: positions || [], brokers: brokers || [], prices, tcValuacion: tc, tcCedear: tc, tcCripto: dolar?.cripto?.venta })
      } catch {
        // sin cartera la sección sigue: índices, ADRs y populares
      }
    })()
    return () => { vivo = false }
  }, [activo, c, valuationDollar])
  return c
}

function ordenar(items) {
  const conDato = items.filter(x => x.pct != null)
  return {
    suben: conDato.filter(x => x.pct > 0).sort((a, b) => b.pct - a.pct).slice(0, TOPE_LISTA),
    bajan: conDato.filter(x => x.pct < 0).sort((a, b) => a.pct - b.pct).slice(0, TOPE_LISTA),
  }
}

function Lista({ titulo, tono, items, moneda, oculto, vacio }) {
  return (
    <div className="flex flex-col gap-1.5 min-w-0">
      <div className={`text-[13px] font-semibold ${tono}`}>{titulo}</div>
      {items.length === 0 ? (
        <div className="px-3 py-2.5 rounded-lg border border-dashed border-line text-[12.5px] text-ink-3">{vacio}</div>
      ) : items.map(x => (
        <div key={x.s} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-bg-2/60">
          <span className="text-[13px] font-semibold text-ink-0 w-14 flex-shrink-0">{x.s}</span>
          <span className="flex-1 min-w-0 text-[12.5px] text-ink-2 truncate">{x.n}</span>
          {x.monto != null && (
            <span className={`text-[12.5px] tabular ${colorClass(x.monto)}`}>{oculto ? '••••' : montoFdh(x.monto, moneda)}</span>
          )}
          <span className={`w-16 text-right text-[13.5px] font-semibold tabular ${pctColor(x.pct)}`}>{pctVar(x.pct)}</span>
        </div>
      ))}
    </div>
  )
}

export default function FueraDeHorarioMercado({ cartera = null, moneda = 'USD', oculto = false, className = '' }) {
  // Primero sin la cartera: con eso alcanza para saber si hay sesión.
  const [hayCartera, setHayCartera] = useState(false)
  const propia = useCarteraPropia(!cartera && hayCartera)
  const c = cartera || propia
  const simbolos = useMemo(() => (c ? simbolosFueraDeHorario(c.positions, c.brokers) : []), [c])
  const datos = useFueraDeHorario(simbolos, { listas: true })
  useEffect(() => { if (datos?.sesion) setHayCartera(true) }, [datos?.sesion])

  const impacto = useMemo(
    () => (c ? impactoFueraDeHorario(c.positions, c.brokers, c, datos) : null),
    [c, datos])

  // «Tus activos»: una fila por acción de EE.UU., con la plata de todas las
  // tenencias que la siguen (el CEDEAR de AAPL y AAPL en Schwab suman juntas).
  const mios = useMemo(() => {
    if (!impacto?.aplica) return []
    const porSimbolo = {}
    for (const r of Object.values(impacto.porPosicion)) {
      const x = porSimbolo[r.s] || (porSimbolo[r.s] = { s: r.s, pct: r.pct, monto: 0, vias: new Set(), propia: false })
      x.monto += moneda === 'ARS' ? r.ars : r.usd
      if (r.via === 'propio') x.propia = true
      else x.vias.add(r.via === 'eeuu' ? 'CEDEAR' : 'vía ADR')
    }
    // Cómo la tenés, corto para que entre en el celular: «EE.UU.» (la acción
    // misma, en un broker del exterior), «CEDEAR», «vía ADR» (acción argentina),
    // o «EE.UU. y CEDEAR» si la tenés de las dos formas.
    return Object.values(porSimbolo).map(x => ({
      s: x.s, pct: x.pct, monto: x.monto,
      n: [x.propia ? 'EE.UU.' : null, ...x.vias].filter(Boolean).join(' y '),
    }))
  }, [impacto, moneda])

  const listas = datos?.listas
  const conPct = (grupo) => (grupo || []).map(x => ({ ...x, pct: datos?.cotizaciones?.[x.s]?.pct ?? null }))
  const pestanas = [
    mios.length > 0 && { id: 'mios', label: 'Tus activos', items: mios,
      pie: 'Al lado del %, la plata que te mueve cada una. Los CEDEARs y las acciones argentinas siguen a su acción en Nueva York: es un anticipo, sin lo que haga el dólar CCL.' },
    { id: 'adrs', label: 'ADRs argentinos', items: conPct(listas?.adrs),
      pie: 'Las acciones argentinas que cotizan en Nueva York. Anticipan cómo puede abrir el Merval.' },
    { id: 'populares', label: 'Populares', items: conPct(listas?.populares),
      pie: 'Acciones y ETFs de EE.UU. muy operados en Argentina como CEDEAR.' },
  ].filter(Boolean)
  const [elegida, setElegida] = useState(null)
  const pestana = pestanas.find(p => p.id === elegida) || pestanas[0]

  if (!datos?.sesion) return null
  const sesion = datos.sesion
  const t = tonoDeSesion(sesion)
  const { suben, bajan } = ordenar(pestana.items)
  const titulo = sesion === 'pre' ? 'Pre-mercado en Wall Street' : 'Post-mercado en Wall Street'
  const sub = [
    estadoDeSesion(datos),
    sesion === 'pre' && !datos.byma_abierto ? 'BYMA abre a las 11:00' : null,
  ].filter(Boolean).join(' · ')
  const indices = conPct(listas?.indices)

  return (
    <section className={`bg-bg-1 border border-dashed ${t.borde} rounded-xl p-4 sm:p-5 flex flex-col gap-4 ${className}`}
      aria-label={nombreDeSesion(sesion)}>
      <div className="flex items-center gap-3">
        <span className={`w-9 h-9 rounded-full inline-flex items-center justify-center flex-shrink-0 ${t.fondo} ${t.texto}`}>
          <IconoSesion sesion={sesion} size={17} />
        </span>
        <div className="min-w-0">
          <h2 className="text-[16px] font-semibold text-ink-0 leading-tight">{titulo}</h2>
          <p className="text-[12.5px] text-ink-2 mt-0.5">{sub}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        {indices.map(x => (
          <div key={x.s} className="bg-bg-2/60 rounded-lg px-3 py-2.5">
            <div className="text-[12px] text-ink-2">{x.n} <span className="text-ink-3">· vía {x.s}</span></div>
            <div className={`text-[19px] font-semibold tabular mt-0.5 ${x.pct == null ? 'text-ink-3' : pctColor(x.pct)}`}>
              {x.pct == null ? '—' : pctVar(x.pct)}
            </div>
          </div>
        ))}
        {impacto?.aplica && (
          <div className="bg-bg-2/60 rounded-lg px-3 py-2.5">
            <div className="text-[12px] text-ink-2">Tu cartera</div>
            <div className={`text-[19px] font-semibold tabular mt-0.5 ${colorClass(impacto.total.usd)}`}>
              {oculto ? '••••' : montoFdh(moneda === 'ARS' ? impacto.total.ars : impacto.total.usd, moneda)}
            </div>
          </div>
        )}
      </div>

      <div role="tablist" aria-label="Qué activos mirar" className="flex flex-wrap gap-1 bg-bg-0/60 rounded-lg p-1 self-start">
        {pestanas.map(p => (
          <button key={p.id} type="button" role="tab" aria-selected={p.id === pestana.id}
            onClick={() => setElegida(p.id)}
            className={`h-8 px-3 rounded text-[13px] font-medium transition-colors ${p.id === pestana.id
              ? 'bg-data-violet/15 text-data-violet' : 'text-ink-2 hover:text-ink-0'}`}>
            {p.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Lista titulo="▲ Más suben" tono="text-rendi-pos" items={suben} moneda={moneda} oculto={oculto}
          vacio={pestana.id === 'mios' ? 'Ninguno de tus activos sube.' : 'Ninguno sube por ahora.'} />
        <Lista titulo="▼ Más bajan" tono="text-rendi-neg" items={bajan} moneda={moneda} oculto={oculto}
          vacio={pestana.id === 'mios' ? 'Ninguno de tus activos baja.' : 'Ninguno baja por ahora.'} />
      </div>
      <p className="text-[12px] text-ink-3 -mt-1">
        {pestana.pie} Las que todavía no operaron fuera de la rueda no aparecen.
      </p>
    </section>
  )
}
