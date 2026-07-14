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
    <div className="border border-line rounded-lg bg-bg-1 p-4">
      <span className="text-xs font-mono uppercase tracking-caps text-ink-2">
        ¿Le ganás a las alternativas?
      </span>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 mt-3">
        {rows.map(it => {
          const win = it.pct >= 0
          const Icon = win ? TrendingUp : TrendingDown
          const color = win ? 'text-rendi-pos' : 'text-rendi-neg'
          return (
            <div
              key={it.key}
              className="flex flex-col gap-1.5 border border-line/50 rounded bg-bg-2/40 p-3"
            >
              <span className="text-[11px] font-mono uppercase tracking-label text-ink-3">
                {it.label}
              </span>
              <div className={`flex items-center gap-1.5 ${color}`}>
                <Icon size={15} strokeWidth={2} />
                <span className="text-sm font-medium">{win ? 'Le ganás' : 'Le perdés'}</span>
              </div>
              <span className={`font-mono text-lg font-semibold leading-none tabular ${color}`}>
                {win ? '+' : ''}{it.pct.toFixed(1)}%
              </span>
            </div>
          )
        })}
      </div>

      <p className="text-[11px] text-ink-3 mt-3 leading-relaxed">
        Compara tu patrimonio actual contra lo que valdría hoy si la misma plata —
        con los mismos aportes y retiros— hubiera ido a cada alternativa.
        La inflación se mide como retorno real (ya descontada).
      </p>
    </div>
  )
}
