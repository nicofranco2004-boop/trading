// HorizonStat — % en activos de plazo largo vs horizonte declarado.
// ═══════════════════════════════════════════════════════════════════════════
// Body de la card de horizonte en Análisis › Perfil. Stat grande con el % de
// la cartera en renta variable + alternativos (activos que piden años), y la
// nota lo cruza contra el horizonte que el usuario declaró en el test.

export default function HorizonStat({ longTermPct, horizonLabel, clashes }) {
  if (longTermPct == null) return null

  return (
    <div>
      <div className="flex items-baseline gap-3">
        <span className="text-3xl font-semibold text-ink-0 tabular-nums">{longTermPct}%</span>
        <span className="text-xs text-ink-2 max-w-[220px] leading-snug">
          en activos de plazo largo (renta variable + alternativos)
        </span>
      </div>

      <p className="text-xs text-ink-2 mt-3 leading-relaxed">
        Horizonte declarado: <b className="text-ink-1">{horizonLabel}</b>.{' '}
        {clashes ? (
          <>
            <span className="text-rendi-warn">Choca</span> con tener{' '}
            <span className="tabular-nums">{longTermPct}%</span> en activos de años.
          </>
        ) : (
          'Coherente con tu composición.'
        )}
      </p>
    </div>
  )
}
