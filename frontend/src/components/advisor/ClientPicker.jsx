// ClientPicker — elegir DE QUÉ CLIENTES se está mirando algo.
// ═══════════════════════════════════════════════════════════════════════════
// Un botón que dice a quiénes se está viendo ("Todos · 12", "3 de 12 clientes")
// y abre una lista con buscador. UNA sola forma para 2 clientes y para 200:
// las fichas horizontales de la primera versión ocupaban toda la barra con 6 y
// eran inusables con 40 (Nico, 2026-09-22: "en el caso de que tenga muchos
// usuarios va a ser un quilombo, una lista infinita").
//
// Sin grupos guardados a propósito (Nico, 2026-09-21): acá se eligen personas.
//
//   clients   → [{client_uid, label, ...}] (null = cargando)
//   selected  → Set de client_uid
//   onChange  → (Set) => void
//   hint      → función opcional (client) => string chico a la derecha del nombre
//   label     → rótulo del botón cuando están todos ("Clientes" por defecto)
//   inline    → lista sin botón (para un modal, donde el panel ya es la pantalla)
import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, Search, Users } from 'lucide-react'

export default function ClientPicker({ clients, selected, onChange, hint,
                                       label = 'Clientes', inline = false }) {
  const all = clients || []
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const btnRef = useRef(null)
  const panelRef = useRef(null)

  const allChecked = all.length > 0 && selected && selected.size === all.length
  const setAll = () => onChange(new Set(all.map(c => c.client_uid)))
  const setNone = () => onChange(new Set())
  const toggleOne = (uid) => {
    const next = new Set(selected)
    next.has(uid) ? next.delete(uid) : next.add(uid)
    onChange(next)
  }

  const filtrados = useMemo(() => {
    const t = q.trim().toLowerCase()
    if (!t) return all
    return all.filter(c => (c.label || '').toLowerCase().includes(t))
  }, [all, q])

  // Cerrar al tocar afuera / Escape — mismo patrón que ActionMenu.
  useEffect(() => {
    if (!open || inline) return
    function onDown(e) {
      if (btnRef.current?.contains(e.target)) return
      if (panelRef.current?.contains(e.target)) return
      setOpen(false)
    }
    function onKey(e) { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('touchstart', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('touchstart', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, inline])

  const lista = (
    <>
      {all.length > 8 && (
        <div className="relative p-2 border-b border-line">
          <Search size={13} strokeWidth={1.75} aria-hidden="true"
                  className="absolute left-4 top-1/2 -translate-y-1/2 text-ink-3" />
          <input
            type="text" value={q} onChange={e => setQ(e.target.value)}
            placeholder="Buscar cliente"
            aria-label="Buscar cliente"
            className="w-full bg-bg-2 border border-line rounded text-[12.5px] text-ink-0 placeholder:text-ink-3 pl-7 pr-2 py-1.5 outline-none focus:border-line-3"
          />
        </div>
      )}
      <div className="flex items-center gap-3 px-3 py-1.5 border-b border-line text-[11.5px]">
        <button type="button" onClick={setAll} disabled={!!allChecked}
                className="text-data-violet hover:underline disabled:text-ink-3 disabled:no-underline">
          Todos
        </button>
        <button type="button" onClick={setNone} disabled={!selected?.size}
                className="text-ink-2 hover:text-ink-0 disabled:text-ink-3">
          Ninguno
        </button>
        <span className="ml-auto text-ink-3 tabular">
          {selected?.size ?? 0} de {all.length}
        </span>
      </div>
      <div className="max-h-56 overflow-y-auto divide-y divide-line/40">
        {filtrados.length === 0 && (
          <p className="px-3 py-3 text-[12px] text-ink-3">Ningún cliente con ese nombre.</p>
        )}
        {filtrados.map(c => (
          <label key={c.client_uid}
                 className="flex items-center gap-2.5 px-3 py-2 text-[12.5px] text-ink-1 cursor-pointer hover:bg-bg-2/50">
            <input type="checkbox" className="accent-data-violet"
                   checked={!!selected?.has(c.client_uid)}
                   onChange={() => toggleOne(c.client_uid)} />
            <span className="truncate">{c.label}</span>
            {hint && hint(c) && <span className="ml-auto text-[11px] text-ink-3 flex-shrink-0">{hint(c)}</span>}
          </label>
        ))}
      </div>
    </>
  )

  if (inline) {
    return <div className="border border-line rounded overflow-hidden">{lista}</div>
  }

  // El botón DICE a quiénes se está viendo: con 40 clientes, "3 de 40" es la
  // única forma de saberlo sin abrir nada.
  const resumen = allChecked
    ? `Todos · ${all.length}`
    : selected?.size === 1
      ? (all.find(c => selected.has(c.client_uid))?.label || '1 cliente')
      : `${selected?.size ?? 0} de ${all.length} clientes`

  return (
    <div className="relative inline-block">
      <button
        ref={btnRef} type="button" onClick={() => setOpen(o => !o)}
        aria-expanded={open} aria-haspopup="true"
        className={`inline-flex items-center gap-1.5 text-[12.5px] rounded-lg border px-2.5 py-1.5 transition-colors max-w-[16rem] ${
          allChecked
            ? 'border-line bg-bg-2 text-ink-1 hover:text-ink-0'
            : 'border-data-violet/50 bg-data-violet/10 text-ink-0 font-medium'}`}
      >
        <Users size={13} strokeWidth={1.75} aria-hidden="true" className="text-ink-2 flex-shrink-0" />
        <span className="text-ink-3">{label}</span>
        <span className="truncate">{resumen}</span>
        <ChevronDown size={13} strokeWidth={2} aria-hidden="true"
                     className={`text-ink-3 flex-shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div ref={panelRef} role="group" aria-label="Elegir clientes"
             className="absolute z-30 mt-1 w-72 max-w-[calc(100vw-2rem)] bg-bg-raised border border-line-2 rounded-lg shadow-lg overflow-hidden">
          {lista}
        </div>
      )}
    </div>
  )
}
