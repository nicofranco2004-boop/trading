// OpportunityBar — gauge "Oportunidad ← En precio → Flojo".
// ═══════════════════════════════════════════════════════════════════════════
// props: { opportunity } con el shape del contrato:
//   { available, kind, value_pct, label, position_pct (0..100), caption }
// Barra con gradiente verde→neutral→rojo + marcador absoluto en position_pct.
// Si opportunity es null o available:false → no renderiza nada (return null).

export default function OpportunityBar({ opportunity }) {
  if (!opportunity || !opportunity.available) return null

  const pos = Math.max(0, Math.min(100, Number(opportunity.position_pct) || 0))

  return (
    <div className="bg-bg-1 border border-line rounded p-4">
      <p className="text-[10px] font-mono uppercase tracking-caps text-ink-2 mb-3">
        Oportunidad de precio
      </p>

      <div className="relative pt-1 pb-6">
        {/* Barra de gradiente */}
        <div
          className="h-2.5 w-full rounded-full"
          style={{
            background:
              'linear-gradient(90deg, #21D07A 0%, #E8B14A 50%, #FF5360 100%)',
          }}
        />
        {/* Marcador */}
        <div
          className="absolute top-0 -translate-x-1/2 flex flex-col items-center"
          style={{ left: `${pos}%`, transition: 'left 600ms ease-out' }}
        >
          <div className="w-3.5 h-3.5 rounded-full bg-ink-0 border-2 border-bg-1 ring-1 ring-line" />
        </div>
        {/* Labels bajo la barra */}
        <div className="absolute left-0 right-0 bottom-0 flex justify-between text-[10px] font-mono uppercase tracking-caps text-ink-3">
          <span>Oportunidad</span>
          <span>En precio</span>
          <span>Flojo</span>
        </div>
      </div>

      {opportunity.caption && (
        <p className="text-xs text-ink-2 leading-snug mt-1">{opportunity.caption}</p>
      )}
    </div>
  )
}
