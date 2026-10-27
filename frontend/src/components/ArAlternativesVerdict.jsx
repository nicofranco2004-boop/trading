// ArAlternativesVerdict — "¿Le ganás a las alternativas argentinas?"
// ═══════════════════════════════════════════════════════════════════════════
// De-bury de un dato que Insights YA computa pero solo usaba para bullets
// sueltos del diagnóstico: la comparación flow-matched del patrimonio del user
// contra plazo fijo UVA, dólar (blue) e inflación. Cada fila dice si le gana o
// le pierde a esa alternativa y por cuánto. Solo se muestran las que tienen
// data (pct != null); si ninguna aplica, el bloque no renderiza.
//
// Semántica del pct (viene de Insights), LA MISMA en las tres celdas:
//   spread flow-matched: (tu patrimonio de hoy − lo que valdría hoy si la misma
//   plata, con los mismos aportes/retiros, hubiera ido a esa alternativa).
//   • Plazo fijo UVA → capitaliza con el coeficiente UVA. Se compara EN PESOS
//     (`compararEnPesos`): antes cambiaba con el selector MEP/CCL.
//   • Dólar → la plata quieta en dólares.
//   • Inflación → ajustada por IPC del INDEC (`veredictoInflacion`). Es el mismo
//     número que el hallazgo beat/lose_inflation_ars y la tarjeta de expectativa.
//     Hasta 2026-10-14 era un retorno time-weighted en pesos sobre la cadena al
//     costo, y contradecía a la celda del UVA.
//   pct ≥ 0 = "le ganás".
//
// El PERÍODO va escrito arriba (`desde`): las tres miden toda la historia, no el
// año. Y la celda de Inflación trae su `contexto` —cuánto subieron los precios y
// cuánto el dólar en ese período—, que es lo que explica cómo algo en dólares
// (el S&P incluido) puede perderle a la inflación argentina. Sin las dos cosas,
// "le gano al S&P y le pierdo a la inflación" se leía como un error (reportado).
//
// No depende de Certero/Estimado: no usa un rendimiento encadenado sino los
// aportes y retiros y lo que vale la cartera hoy, que son los mismos en los dos.
//
// Al verse (useAlVerse): en cada celda se pone "Le ganás"/"Le perdés", el
// porcentaje cuenta y una barra crece desde el centro hacia la derecha (ganás)
// o la izquierda (perdés), en la misma escala para las tres (la más grande
// llega al borde). Con "reducir movimiento", todo armado.

import { TrendingUp, TrendingDown } from 'lucide-react'
import AnimatedNumber from './AnimatedNumber'
import { useAlVerse } from '../hooks/useAlVerse'
import { pctVar, decimalesFinos } from '../utils/format'

export default function ArAlternativesVerdict({ items, desde = null }) {
  const [ref, visto] = useAlVerse()
  const rows = (items || []).filter(it => it.pct != null && isFinite(it.pct))
  if (rows.length === 0) return null
  const escala = Math.max(...rows.map(it => Math.abs(it.pct)))

  return (
    <div ref={ref} className="border border-line rounded-2xl bg-bg-1 p-5">
      <p className="text-[14.5px] font-semibold text-ink-0">
        ¿Le ganás a las alternativas?
      </p>
      <p className="text-[12px] text-ink-3 mt-1 mb-4">
        {desde ? `Toda tu historia: desde ${desde} hasta hoy` : 'Toda tu historia, hasta hoy'}
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {rows.map((it, i) => {
          const win = it.pct >= 0
          const Icon = win ? TrendingUp : TrendingDown
          const color = win ? 'text-rendi-pos' : 'text-rendi-neg'
          // Media barra = la alternativa con la diferencia más grande.
          const ancho = escala > 0 ? Math.max(2, (Math.abs(it.pct) / escala) * 50) : 0
          return (
            <div
              key={it.key}
              className="border border-line/60 rounded-xl bg-bg-2/40 p-4"
            >
              <span className="text-[13px] text-ink-2 font-medium">{it.label}</span>
              <div className={`flex items-center gap-2 mt-3 ${color} ${visto ? 'tilde-entra' : 'por-entrar'}`} style={{ '--i': i }}>
                <Icon size={16} strokeWidth={2.25} />
                <span className="text-[14.5px] font-semibold">{win ? 'Le ganás' : 'Le perdés'}</span>
              </div>
              <span className={`block font-semibold text-[24px] leading-none tabular num mt-2 ${color}`}>
                {/* decimalesFinos: −0,04 se lee "−0,04%" al lado de "Le perdés", no
                    "0,0%". Los mismos decimales mientras cuenta. */}
                <AnimatedNumber value={it.pct} visto={visto} format={n => pctVar(n, decimalesFinos(it.pct, 1))} />
              </span>
              <div className="relative h-1.5 mt-3 rounded-full bg-bg-2" aria-hidden="true">
                <div className="absolute left-1/2 -top-1 h-3.5 w-px bg-line" />
                {ancho > 0 && (
                  <div
                    className={`absolute top-0 h-full rounded-full ${win ? 'left-1/2 bg-rendi-pos/80' : 'right-1/2 bg-rendi-neg/80'} ${visto ? 'crece-ancho' : 'scale-x-0'}`}
                    style={{ width: `${ancho}%`, '--i': i, transformOrigin: win ? 'left' : 'right' }}
                  />
                )}
              </div>
              {/* La base de CADA celda, en la celda. Las tres se calculan
                  distinto y sin esto no hay forma de saberlo mirando. */}
              {it.nota && (
                <span className="block text-[11px] text-ink-3 leading-snug mt-2">{it.nota}</span>
              )}
              {it.contexto && (
                <span className="block text-[11px] text-ink-2 leading-snug mt-2">{it.contexto}</span>
              )}
            </div>
          )
        })}
      </div>

      <p className="text-[12px] text-ink-3 mt-4 leading-relaxed">
        Las tres comparan tu patrimonio de hoy contra lo que valdría si la misma
        plata —con los mismos aportes y retiros— hubiera ido ahí. El plazo fijo UVA y la
        inflación se simulan y se comparan <b>en pesos</b> (con el coeficiente UVA y con
        el IPC del INDEC); el dólar, <b>en dólares</b>. Así cada lado se mide en la misma
        moneda que su alternativa, y el resultado no cambia según qué dólar elijas para
        valuar. <b>Los tres porcentajes no se restan entre sí</b> — cada uno mide contra
        una alternativa distinta. Es igual en Certero y en Estimado: no usa tu
        rendimiento, sino lo que pusiste y lo que vale tu cartera hoy.
      </p>
    </div>
  )
}
