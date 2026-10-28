// LiquidezByma — cuánto se opera un CEDEAR o una acción argentina en BYMA, en
// la ficha del activo, debajo del análisis técnico.
// ════════════════════════════════════════════════════════════════════════════
// El gráfico de un CEDEAR mira la acción en Nueva York, que se opera muchísimo;
// el usuario compra y vende el CEDEAR en BYMA, donde puede casi no operarse.
// Esto dice cuánto se opera ahí y cuánto cuesta entrar y salir. Los números y
// el veredicto (mucha / media / poca) los arma el servidor (backend/liquidez.py).
//
// Tres formas, según el veredicto:
//   · mucha: UNA línea, sin tarjeta (no alarga la ficha cuando no hay riesgo);
//   · media: una tarjeta tranquila;
//   · poca:  una tarjeta con el aviso.
// Cada una dice QUÉ TE CAMBIA esa liquidez al operar (si podés comprar y vender
// enseguida, a qué precio, qué pasa con una orden grande), no sólo el número
// (Nico, 24/10). Describe un riesgo; nunca dice qué hacer.

import { useEffect, useState } from 'react'
import { ArrowLeftRight } from 'lucide-react'
import { api } from '../../utils/api'

// Abajo de un millón, "$ 0 millones" no dice nada: se dice que es menos.
const millones = (p) => p < 1e6 ? 'menos de $ 1 millón' : `$ ${Math.round(p / 1e6).toLocaleString('es-AR')} millones`
const pct = (x) => `${x.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} %`

export default function LiquidezByma({ papel }) {
  const [liq, setLiq] = useState(null)

  useEffect(() => {
    if (!papel) return
    let vivo = true
    setLiq(null)
    api.get(`/liquidez/${encodeURIComponent(papel)}`)
      .then(r => { if (vivo) setLiq(r) })
      .catch(() => { if (vivo) setLiq(null) })   // sin el dato, no se muestra nada
    return () => { vivo = false }
  }, [papel])

  // Sin dato: si la fuente no contestó, se dice (callar haría pensar que no
  // hay riesgo); si el papel no cotiza en BYMA (un bono, un fondo), nada.
  if (liq?.motivo === 'sin_fuente') {
    return (
      <p className="mb-5 text-[13px] text-ink-2">
        Ahora no pudimos medir cuánto se opera en BYMA. Probá de nuevo en un rato.
      </p>
    )
  }
  if (!liq?.disponible) return null
  const { nivel, pesos_por_dia: pesos, dias_sin_operar: sinOperar, ruedas, spread_pct: spread } = liq
  const ultimaRueda = liq.periodo === 'ultima_rueda'
  const enDolares = liq.en_dolares ? ' Es la especie en dólares: el monto está pasado a pesos.' : ''

  if (nivel === 'mucha') {
    return (
      <p className="flex items-start gap-2 mb-5 text-[13px] text-ink-2">
        <ArrowLeftRight size={15} strokeWidth={1.75} className="text-rendi-pos mt-0.5 flex-shrink-0" aria-hidden="true" />
        <span>
          Se opera mucho en BYMA{pesos != null && <>: <span className="text-ink-0 font-medium tabular">{millones(pesos)} {ultimaRueda ? 'en la última rueda' : 'por día'}</span></>}.{enDolares}
          {' '}Podés comprar o vender enseguida, a un precio cerca del último.
          {spread != null && <> Hacerlo al toque cuesta <span className="tabular">{pct(spread)}</span>.</>}
        </span>
      </p>
    )
  }

  const poca = nivel === 'poca'
  const tono = poca ? 'text-rendi-neg' : 'text-rendi-warn'
  // Lo que se midió, y sólo eso: sin las ruedas de BYMA no se dice "se operó
  // todos los días"; sin historia, se dice que es la última rueda.
  const operaciones = (pesos == null
    ? 'No hay historia de cuánto se opera por día.'
    : ultimaRueda
      ? (sinOperar
        ? 'En la última rueda no tuvo ninguna operación. No hay historia de los días anteriores.'
        : `En la última rueda se operaron unos ${millones(pesos)}. No hay historia de los días anteriores.`)
      : `Se operan unos ${millones(pesos)} por día${sinOperar == null ? ''
        : sinOperar
          ? ` y no tuvo ninguna operación en ${sinOperar} de las últimas ${ruedas} ruedas`
          : ` y se operó todos los días de las últimas ${ruedas} ruedas`}.`) + enDolares
  const puntas = spread == null ? null
    : poca && spread > 1
      ? `Ahora, entre el precio de compra y el de venta hay ${pct(spread)}.`
      : `Comprar y vender al toque cuesta ${pct(spread)}.`
  // Qué te cambia al operar. Sin "comprá", "vendé" ni "evitá": sólo qué pasa.
  const efectos = poca ? [
    'Puede no haber quién te compre o te venda enseguida al precio que ves: a veces hay que esperar o aceptar un precio peor.',
    spread != null && spread > 1
      ? `Si comprás y vendés enseguida, perdés ese ${pct(spread)} aunque el precio no se mueva.`
      : 'Entrar y salir seguido cuesta más que en un papel que se opera mucho.',
    'Una orden grande puede mover el precio en contra mientras se completa.',
    // Sin nombrar "el gráfico de arriba": a veces no hay gráfico (IRENC), y
    // en pesos el gráfico es el del propio CEDEAR.
    liq.es_cedear && 'El precio del CEDEAR en BYMA puede alejarse del de la acción en Nueva York, que se opera mucho más.',
  ].filter(Boolean) : [
    'En montos chicos se compra y se vende sin problema.',
    'En montos grandes, tu propia orden puede mover el precio en contra mientras se completa.',
  ]

  return (
    <section aria-label="Liquidez en BYMA"
      className={`mb-5 rounded-lg border px-3.5 py-3 sm:max-w-md ${poca ? 'border-rendi-neg/40 bg-rendi-neg/10' : 'border-rendi-warn/40 bg-rendi-warn/10'}`}>
      <div className={`text-[12px] font-medium ${tono}`}>Liquidez en BYMA</div>
      <div className={`text-[15px] font-semibold mt-0.5 ${tono}`}>{poca ? 'Poca' : 'Media'}</div>
      <p className="text-[13px] text-ink-1 leading-relaxed mt-1.5 tabular">
        {operaciones}{puntas && <> {puntas}</>}
      </p>
      <div className="text-[12.5px] text-ink-1 font-medium mt-2.5">Qué te cambia al operar</div>
      <ul className="mt-1 space-y-1">
        {efectos.map(e => (
          <li key={e} className="flex gap-2 text-[12.5px] text-ink-2 leading-relaxed">
            <span aria-hidden="true" className={tono}>·</span><span>{e}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
