// DateField — selector de fecha con estética Rendi (reemplaza el <input type=date>
// nativo, que abre el calendario del browser y no se puede estilar). El calendario
// se despliega inline (no flota) para no chocar con el overflow del modal.
import { useState, useRef, useEffect } from 'react'
import { Calendar, ChevronLeft, ChevronRight } from 'lucide-react'

const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
const DOW = ['L', 'M', 'M', 'J', 'V', 'S', 'D']

function parse(v) {
  if (!v) return null
  const [y, m, d] = v.split('-').map(Number)
  if (!y || !m || !d) return null
  return new Date(y, m - 1, d)
}
function iso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function fmt(v) {
  const d = parse(v)
  if (!d) return ''
  return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`
}
const dayOnly = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate())
const sameDay = (a, b) => a && b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()

export default function DateField({ value, onChange, min }) {
  const [open, setOpen] = useState(false)
  const sel = parse(value)
  const [view, setView] = useState(() => sel || new Date())
  const ref = useRef(null)
  const minD = min ? dayOnly(parse(min) || new Date(0)) : null
  const today = dayOnly(new Date())

  useEffect(() => { if (open && sel) setView(sel) }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return
    function onDoc(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    function onKey(e) { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey) }
  }, [open])

  const vy = view.getFullYear(), vm = view.getMonth()
  const first = new Date(vy, vm, 1)
  const offset = (first.getDay() + 6) % 7  // Lunes = 0
  const start = new Date(vy, vm, 1 - offset)
  const cells = Array.from({ length: 42 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i))

  function pick(d) {
    if (minD && dayOnly(d) < minD) return
    onChange(iso(d))
    setOpen(false)
  }

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between bg-bg-2 border border-line-2 rounded-md px-3 py-2 text-sm hover:border-rendi-accent/50 focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 transition"
      >
        <span className={value ? 'text-ink-0' : 'text-ink-3'}>{value ? fmt(value) : 'dd/mm/aaaa'}</span>
        <Calendar size={14} className="text-ink-3 flex-shrink-0" aria-hidden="true" />
      </button>

      {open && (
        <div className="mt-1 bg-bg-1 border border-line rounded-lg shadow-lg p-3 select-none">
          <div className="flex items-center justify-between mb-2">
            <button type="button" onClick={() => setView(new Date(vy, vm - 1, 1))} className="p-1 rounded text-ink-2 hover:text-ink-0 hover:bg-bg-2 transition" aria-label="Mes anterior">
              <ChevronLeft size={16} />
            </button>
            <span className="text-sm font-semibold text-ink-0 capitalize">{MESES[vm]} {vy}</span>
            <button type="button" onClick={() => setView(new Date(vy, vm + 1, 1))} className="p-1 rounded text-ink-2 hover:text-ink-0 hover:bg-bg-2 transition" aria-label="Mes siguiente">
              <ChevronRight size={16} />
            </button>
          </div>
          <div className="grid grid-cols-7 mb-1">
            {DOW.map((d, i) => <div key={i} className="text-[12px] tracking-[0.12em] text-ink-3 text-center py-1 font-medium">{d}</div>)}
          </div>
          <div className="grid grid-cols-7 gap-0.5">
            {cells.map((d, i) => {
              const inMonth = d.getMonth() === vm
              const isSel = sameDay(d, sel)
              const isToday = sameDay(d, today)
              const disabled = minD && dayOnly(d) < minD
              return (
                <button
                  key={i}
                  type="button"
                  disabled={disabled}
                  onClick={() => pick(d)}
                  className={[
                    'h-8 rounded-md text-sm flex items-center justify-center transition tabular',
                    isSel ? 'bg-rendi-accent text-white font-semibold'
                      : disabled ? 'text-ink-3/40 cursor-not-allowed'
                        : inMonth ? 'text-ink-1 hover:bg-bg-2' : 'text-ink-3/50 hover:bg-bg-2',
                    !isSel && isToday ? 'ring-1 ring-rendi-accent/50' : '',
                  ].join(' ')}
                >
                  {d.getDate()}
                </button>
              )
            })}
          </div>
          <div className="flex justify-between items-center mt-2 pt-2 border-t border-line/40">
            <button type="button" onClick={() => pick(today)} className="text-xs text-rendi-accent hover:underline">Hoy</button>
            <button type="button" onClick={() => setOpen(false)} className="text-xs text-ink-3 hover:text-ink-1">Cerrar</button>
          </div>
        </div>
      )}
    </div>
  )
}
