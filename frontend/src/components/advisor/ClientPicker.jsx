// ClientPicker — elegir clientes con casillas: "Todos" + uno por uno.
// ═══════════════════════════════════════════════════════════════════════════
// Sacado del modal "Informe del período" (AdvisorDashboard), donde vivía como
// markup suelto; acá es un componente para que Cobros y cualquier pantalla
// cross-cliente usen la MISMA selección. Sin grupos a propósito (Nico,
// 2026-09-21: "es muy complejo, ¿por qué no sólo se seleccionan los usuarios?").
//
//   clients   → [{client_uid, label, ...}] (null = cargando)
//   selected  → Set de client_uid
//   onChange  → (Set) => void
//   compact   → chips horizontales (toolbar) en vez de lista vertical (modal)
//   hint      → función opcional (client) => string chico a la derecha del nombre

export default function ClientPicker({ clients, selected, onChange, compact = false, hint }) {
  const all = clients || []
  const allChecked = all.length > 0 && selected && selected.size === all.length
  const toggleAll = () => onChange(allChecked ? new Set() : new Set(all.map(c => c.client_uid)))
  const toggleOne = (uid) => {
    const next = new Set(selected)
    next.has(uid) ? next.delete(uid) : next.add(uid)
    onChange(next)
  }

  if (compact) {
    return (
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Clientes">
        <button type="button" onClick={toggleAll} aria-pressed={!!allChecked}
          className={`inline-flex items-center gap-1.5 text-[12.5px] rounded-full border px-2.5 py-1 transition-colors ${
            allChecked ? 'border-data-violet/50 bg-data-violet/10 text-ink-0 font-semibold' : 'border-line bg-bg-2 text-ink-1 hover:text-ink-0'}`}>
          <Box on={!!allChecked} />
          Todos{clients ? ` · ${all.length}` : ''}
        </button>
        {all.map(c => {
          const on = !!selected?.has(c.client_uid)
          return (
            <button key={c.client_uid} type="button" onClick={() => toggleOne(c.client_uid)} aria-pressed={on}
              className={`inline-flex items-center gap-1.5 text-[12.5px] rounded-full border px-2.5 py-1 transition-colors max-w-[14rem] ${
                on ? 'border-data-violet/50 bg-data-violet/10 text-ink-0' : 'border-line bg-bg-2 text-ink-2 hover:text-ink-0'}`}>
              <Box on={on} />
              <span className="truncate">{c.label}</span>
              {hint && <span className="text-[11px] text-ink-3">{hint(c)}</span>}
            </button>
          )
        })}
      </div>
    )
  }

  return (
    <div className="border border-line rounded max-h-44 overflow-y-auto divide-y divide-line/40">
      <label className="flex items-center gap-2.5 px-3 py-2 text-[12.5px] font-semibold text-ink-0 cursor-pointer hover:bg-bg-2/50">
        <input type="checkbox" className="accent-data-violet" checked={!!allChecked} onChange={toggleAll} />
        Todos {clients ? `(${all.length})` : ''}
      </label>
      {all.map(c => (
        <label key={c.client_uid} className="flex items-center gap-2.5 px-3 py-2 text-[12.5px] text-ink-1 cursor-pointer hover:bg-bg-2/50">
          <input type="checkbox" className="accent-data-violet"
                 checked={!!selected?.has(c.client_uid)} onChange={() => toggleOne(c.client_uid)} />
          <span className="truncate">{c.label}</span>
          {hint && <span className="ml-auto text-[11px] text-ink-3">{hint(c)}</span>}
        </label>
      ))}
    </div>
  )
}

function Box({ on }) {
  return (
    <span aria-hidden="true" className={`inline-block w-3 h-3 rounded-xs border ${
      on ? 'bg-data-violet border-data-violet' : 'border-ink-3'}`} />
  )
}
