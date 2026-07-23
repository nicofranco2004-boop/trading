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
import { TrendingUp, TrendingDown } from 'lucide-react'

export default function ArAlternativesVerdict({ items }) {
  const rows = (items || []).filter(it => it.pct != null && isFinite(it.pct))
  if (rows.length === 0) return null

  return (
    <div className="border border-line rounded-2xl bg-bg-1 p-5">
      <p className="text-[14.5px] font-semibold text-ink-0 mb-4">
        ¿Le ganás a las alternativas?
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {rows.map(it => {
          const win = it.pct >= 0
          const Icon = win ? TrendingUp : TrendingDown
          const color = win ? 'text-rendi-pos' : 'text-rendi-neg'
          return (
            <div
              key={it.key}
              className="border border-line/60 rounded-xl bg-bg-2/40 p-4"
            >
              <span className="text-[13px] text-ink-2 font-medium">{it.label}</span>
              <div className={`flex items-center gap-2 mt-3 ${color}`}>
                <Icon size={16} strokeWidth={2.25} />
                <span className="text-[14.5px] font-semibold">{win ? 'Le ganás' : 'Le perdés'}</span>
              </div>
              <span className={`block font-semibold text-[24px] leading-none tabular num mt-2 ${color}`}>
                {win ? '+' : ''}{it.pct.toFixed(1)}%
              </span>
            </div>
          )
        })}
      </div>

      <p className="text-[12px] text-ink-3 mt-4 leading-relaxed">
        Compara tu patrimonio actual contra lo que valdría hoy si la misma plata —
        con los mismos aportes y retiros— hubiera ido a cada alternativa.
        La inflación se mide como retorno real (ya descontada).
      </p>
    </div>
  )
}
