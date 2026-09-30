// IndicesStrip — strip horizontal de índices (clean pass 2026-07).
// Cards con gap y aire: label sans + valor grande tabular + delta con flecha.
//
// Los datos y el formato son los MISMOS que los de la cinta de arriba
// (MarketTicker): useMarketIndices es el único que pide /home/indices, y los
// números salen de pctVar / fmtIndexPrice de utils/format. Antes cada uno pedía
// y escribía por su cuenta, y la misma caída se leía "-0,85%" acá y "−0,85%"
// en la barra del celular.

import { useMarketIndices } from '../../hooks/useMarketIndices'
import { pctVar, pctVarSign, fmtIndexPrice } from '../../utils/format'

export default function IndicesStrip() {
  const { items, loading, error: err } = useMarketIndices()

  if (loading && items.length === 0) {
    return (
      <div className="rounded border border-line bg-bg-1">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 divide-x divide-y sm:divide-y-0 divide-line">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-16 p-3">
              <div className="h-2 w-12 rounded-sm bg-bg-3 esqueleto mb-2" />
              <div className="h-4 w-20 rounded-sm bg-bg-3 esqueleto" />
            </div>
          ))}
        </div>
      </div>
    )
  }
  if (err && items.length === 0) {
    return <div className="text-xs text-rendi-neg">No pudimos cargar los índices: {err}</div>
  }

  // Clean pass 2026-07: cards con gap (antes: grilla con hairlines divide-x,
  // look planilla). Label sans, número grande, variación con flecha.
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {items.map(it => {
        const dir = pctVarSign(it.change_pct)
        return (
          <div key={it.symbol} className="rounded-xl border border-line bg-bg-1 px-4 py-3.5">
            <div className="text-[12.5px] text-ink-2 font-medium leading-tight">{it.label}</div>
            <div className="mt-2 text-[19px] font-semibold text-ink-0 num tabular leading-none">
              {fmtIndexPrice(it.price, it.kind)}
            </div>
            <div className={`mt-1.5 text-[12.5px] font-semibold tabular num ${dir > 0 ? 'text-rendi-pos' : dir < 0 ? 'text-rendi-neg' : 'text-ink-2'}`}>
              {dir > 0 ? '▲ ' : dir < 0 ? '▼ ' : ''}{pctVar(it.change_pct)}
            </div>
          </div>
        )
      })}
    </div>
  )
}
