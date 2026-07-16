// LiquidityBar — barra partida: qué % de la cartera es líquido/estable.
// ═══════════════════════════════════════════════════════════════════════════
// Body de la card de liquidez en Análisis › Perfil. Verde = cash + renta fija
// (disponible/estable), ámbar = renta variable + cripto (puede tardar o bajar
// justo cuando la precisás). La nota cruza contra lo que el usuario declaró
// sobre cuándo necesita la plata (comparison viene del backend).

export default function LiquidityBar({ safePct, volatilePct, needsLiquidity, comparison }) {
  if (safePct == null) return null

  const mismatch = comparison === 'mismatch_severe' || comparison === 'mismatch_risky'

  return (
    <div>
      <div
        className="flex h-[26px] rounded-md overflow-hidden"
        role="img"
        aria-label={`${safePct}% en cash y renta fija, ${volatilePct}% en renta variable y cripto`}
      >
        <div
          className="bg-rendi-pos/80 flex items-center justify-center"
          style={{ width: `${safePct}%` }}
        >
          {safePct >= 8 && (
            <span className="text-[11px] font-semibold text-bg-0 tabular-nums">{safePct}%</span>
          )}
        </div>
        <div
          className="bg-rendi-warn/80 flex items-center justify-center"
          style={{ width: `${volatilePct}%` }}
        >
          {volatilePct >= 8 && (
            <span className="text-[11px] font-semibold text-bg-0 tabular-nums">{volatilePct}%</span>
          )}
        </div>
      </div>

      {/* Leyenda */}
      <div className="flex items-center gap-4 mt-2 text-[11px] text-ink-2">
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-rendi-pos/80" />
          Cash + renta fija
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-rendi-warn/80" />
          Renta variable + cripto
        </span>
      </div>

      <p className="text-xs text-ink-2 mt-3 leading-relaxed">
        {mismatch ? (
          <>
            Necesitás la plata pronto, pero{' '}
            <span className="text-rendi-warn tabular-nums">{volatilePct}%</span> está en activos
            que pueden tardar o bajar justo cuando la precises.
          </>
        ) : (
          <>
            Tenés <span className="text-rendi-pos tabular-nums">{safePct}%</span>{' '}
            disponible/estable — cómodo para tu horizonte.
          </>
        )}
      </p>
    </div>
  )
}
