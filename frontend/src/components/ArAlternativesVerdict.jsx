// ArAlternativesVerdict — "¿Le ganás a las alternativas argentinas?"
// ═══════════════════════════════════════════════════════════════════════════
// De-bury de un dato que Insights YA computa pero solo usaba para bullets
// sueltos del diagnóstico: la comparación flow-matched del patrimonio del user
// contra plazo fijo UVA, dólar (blue) e inflación. Cada fila dice si le gana o
// le pierde a esa alternativa y por cuánto. Solo se muestran las que tienen
// data (pct != null); si ninguna aplica, el bloque no renderiza.
//
// Semántica del pct (viene de Insights):
//   • Plazo fijo / Dólar → spread flow-matched: (tu patrimonio − lo que valdría
//     hoy si la misma plata, con los mismos aportes/retiros, hubiera ido ahí).
//   • Inflación → retorno REAL geométrico ((1+r)/(1+infl)−1), mismo cálculo que
//     el diagnóstico beat/lose_inflation_ars (así el veredicto no lo contradice).
//   pct ≥ 0 = "le ganás".
//
// Al verse (useAlVerse): en cada celda se pone "Le ganás"/"Le perdés", el
// porcentaje cuenta y una barra crece desde el centro hacia la derecha (ganás)
// o la izquierda (perdés), en la misma escala para las tres (la más grande
// llega al borde). Con "reducir movimiento", todo armado.

import { TrendingUp, TrendingDown } from 'lucide-react'
import AnimatedNumber from './AnimatedNumber'
import { useAlVerse } from '../hooks/useAlVerse'
import { pctVar } from '../utils/format'

export default function ArAlternativesVerdict({ items }) {
  const [ref, visto] = useAlVerse()
  const rows = (items || []).filter(it => it.pct != null && isFinite(it.pct))
  if (rows.length === 0) return null
  const escala = Math.max(...rows.map(it => Math.abs(it.pct)))

  return (
    <div ref={ref} className="border border-line rounded-2xl bg-bg-1 p-5">
      <p className="text-[14.5px] font-semibold text-ink-0 mb-4">
        ¿Le ganás a las alternativas?
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
                <AnimatedNumber value={it.pct} visto={visto} format={n => pctVar(n, 1)} />
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
            </div>
          )
        })}
      </div>

      <p className="text-[12px] text-ink-3 mt-4 leading-relaxed">
        <b>Plazo fijo UVA</b> y <b>Dólar</b> comparan tu patrimonio de hoy contra lo que
        valdría si la misma plata —con los mismos aportes y retiros— hubiera ido ahí.
        El plazo fijo UVA se simula <b>en pesos</b> (capitaliza con el coeficiente UVA) y
        recién después se pasa a <b>dólares</b> al tipo de cambio de cada mes, así los dos
        lados se miden en la misma moneda y la comparación es válida.
        <b> Inflación</b> es otra cosa: el retorno real de tu plata en pesos, ya descontado
        el IPC. <b>Los tres porcentajes no se restan entre sí</b> — cada uno responde una
        pregunta distinta.
      </p>
    </div>
  )
}
