import { Calendar, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react'
import { useRef, useState, useEffect } from 'react'

const MONTHS = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
const DAYS = ['L', 'M', 'M', 'J', 'V', 'S', 'D']

function pad(n) { return String(n).padStart(2, '0') }
function fmtISO(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` }
function fmtDisplay(iso) {
  if (!iso) return ''
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y}`
}
function parseISO(iso) {
  if (!iso) return null
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}
function isSameDay(a, b) {
  return a && b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

// Auto-máscara mientras se tipea: deja solo dígitos (DDMMAAAA) y los formatea a
// dd/mm/aaaa. Así el user escribe "15032021" y ve "15/03/2021" sin tocar barras.
function maskDate(raw) {
  const g = (raw || '').replace(/\D/g, '').slice(0, 8)
  let out = g.slice(0, 2)
  if (g.length > 2) out += '/' + g.slice(2, 4)
  if (g.length > 4) out += '/' + g.slice(4, 8)
  return out
}
// Parsea "dd/mm/aaaa" → ISO "aaaa-mm-dd", o null si no es una fecha real
// (rechaza 31/02, mes 13, etc.). Permite d/m de 1 dígito.
function parseDisplay(text) {
  const m = (text || '').match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/)
  if (!m) return null
  const d = +m[1], mo = +m[2], y = +m[3]
  const dt = new Date(y, mo - 1, d)
  if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) return null
  return fmtISO(dt)
}

export default function DateInput({ value, onChange, min, max, className = '', placeholder = 'dd/mm/aaaa' }) {
  const [open, setOpen] = useState(false)
  // Texto del input (display dd/mm/aaaa). Estado propio para poder tipear libre
  // sin que cada tecla reformatee/valide de golpe; se commitea cuando es válido.
  const [text, setText] = useState(fmtDisplay(value))
  const wrapRef = useRef(null)
  const initial = parseISO(value) || new Date()
  const [viewMonth, setViewMonth] = useState(initial.getMonth())
  const [viewYear, setViewYear] = useState(initial.getFullYear())

  // Sincronizar el texto cuando el value cambia desde afuera (elegir en el
  // calendario, reset del form, edición de otra posición).
  useEffect(() => { setText(fmtDisplay(value)) }, [value])

  useEffect(() => {
    function handleClick(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  // Cuando se abre, mover la vista al mes del valor actual
  useEffect(() => {
    if (open) {
      const d = parseISO(value) || new Date()
      setViewMonth(d.getMonth())
      setViewYear(d.getFullYear())
    }
  }, [open, value])

  const today = new Date()
  const selected = parseISO(value)
  const minDate = parseISO(min)
  const maxDate = parseISO(max)

  function inRange(d) {
    if (minDate && d < minDate) return false
    if (maxDate && d > maxDate) return false
    return true
  }

  // Tipeo: enmascara, y si quedó una fecha válida y en rango, la commitea ya.
  function handleType(raw) {
    const masked = maskDate(raw)
    setText(masked)
    const iso = parseDisplay(masked)
    if (iso && inRange(parseISO(iso))) onChange(iso)
  }
  // Al salir del input: vacío → limpia; válido en rango → normaliza; si quedó
  // inválido/fuera de rango → revierte al último value bueno.
  function handleBlur() {
    if (text.trim() === '') { onChange(''); return }
    const iso = parseDisplay(text)
    if (iso && inRange(parseISO(iso))) setText(fmtDisplay(iso))
    else setText(fmtDisplay(value))
  }

  // Calcular grid del mes
  const firstDay = new Date(viewYear, viewMonth, 1)
  const lastDay = new Date(viewYear, viewMonth + 1, 0)
  // Lunes = 0 (en JS getDay: domingo=0, así que ajustamos)
  const startOffset = (firstDay.getDay() + 6) % 7
  const daysInMonth = lastDay.getDate()
  // Días del mes anterior visibles
  const prevMonthLastDay = new Date(viewYear, viewMonth, 0).getDate()

  const cells = []
  // mes anterior
  for (let i = startOffset - 1; i >= 0; i--) {
    cells.push({ day: prevMonthLastDay - i, otherMonth: true, date: new Date(viewYear, viewMonth - 1, prevMonthLastDay - i) })
  }
  // mes actual
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push({ day: d, otherMonth: false, date: new Date(viewYear, viewMonth, d) })
  }
  // mes siguiente — completar a 42 (6 filas)
  let nextDay = 1
  while (cells.length < 42) {
    cells.push({ day: nextDay, otherMonth: true, date: new Date(viewYear, viewMonth + 1, nextDay) })
    nextDay++
  }

  function navMonth(delta) {
    let m = viewMonth + delta
    let y = viewYear
    if (m < 0) { m = 11; y-- }
    if (m > 11) { m = 0; y++ }
    setViewMonth(m)
    setViewYear(y)
  }
  function navYear(delta) { setViewYear(y => y + delta) }

  function pickDay(d) {
    if (!inRange(d)) return
    onChange(fmtISO(d))
    setOpen(false)
  }

  function isDisabled(d) { return !inRange(d) }

  return (
    <div ref={wrapRef} className={`relative ${className}`}>
      <div className="relative">
        <button
          type="button"
          tabIndex={-1}
          onClick={() => setOpen(o => !o)}
          aria-label="Abrir calendario"
          className="absolute left-0 top-0 h-full px-3 flex items-center"
        >
          <Calendar size={14} className={`transition ${open ? 'text-rendi-accent' : 'text-ink-3'}`} />
        </button>
        <input
          type="text"
          inputMode="numeric"
          value={text}
          onChange={e => handleType(e.target.value)}
          onBlur={handleBlur}
          placeholder={placeholder}
          className="w-full bg-bg-2 dark:bg-bg-2 border border-line rounded-md pl-9 pr-3 py-2 text-sm text-ink-0 font-mono focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60 transition placeholder:text-ink-3 placeholder:font-sans hover:border-ink-3"
        />
      </div>

      {open && (
        <div className="absolute z-50 mt-1 left-0 bg-white dark:bg-bg-2 border border-line rounded-lg shadow-2xl p-3 w-[280px]">
          {/* Header — saltos de mes (‹ ›) y de año (« »), para llegar rápido a fechas viejas */}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center">
              <button
                type="button"
                onClick={() => navYear(-1)}
                aria-label="Año anterior"
                className="p-1.5 rounded-md text-ink-3 hover:bg-bg-2 dark:hover:bg-bg-3 hover:text-ink-0 dark:hover:text-ink-0 transition"
              >
                <ChevronsLeft size={16} />
              </button>
              <button
                type="button"
                onClick={() => navMonth(-1)}
                aria-label="Mes anterior"
                className="p-1.5 rounded-md text-ink-3 hover:bg-bg-2 dark:hover:bg-bg-3 hover:text-ink-0 dark:hover:text-ink-0 transition"
              >
                <ChevronLeft size={16} />
              </button>
            </div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm text-ink-0 dark:text-white">
                {MONTHS[viewMonth]}
              </span>
              <span className="text-sm text-ink-3 font-mono">
                {viewYear}
              </span>
            </div>
            <div className="flex items-center">
              <button
                type="button"
                onClick={() => navMonth(1)}
                aria-label="Mes siguiente"
                className="p-1.5 rounded-md text-ink-3 hover:bg-bg-2 dark:hover:bg-bg-3 hover:text-ink-0 dark:hover:text-ink-0 transition"
              >
                <ChevronRight size={16} />
              </button>
              <button
                type="button"
                onClick={() => navYear(1)}
                aria-label="Año siguiente"
                className="p-1.5 rounded-md text-ink-3 hover:bg-bg-2 dark:hover:bg-bg-3 hover:text-ink-0 dark:hover:text-ink-0 transition"
              >
                <ChevronsRight size={16} />
              </button>
            </div>
          </div>

          {/* Días de la semana */}
          <div className="grid grid-cols-7 gap-1 mb-1">
            {DAYS.map((d, i) => (
              <div key={i} className="text-[12px] font-bold text-ink-3 text-center py-1">
                {d}
              </div>
            ))}
          </div>

          {/* Grid de días */}
          <div className="grid grid-cols-7 gap-1">
            {cells.map((c, i) => {
              const isToday = isSameDay(c.date, today)
              const isSelected = isSameDay(c.date, selected)
              const disabled = isDisabled(c.date)
              return (
                <button
                  key={i}
                  type="button"
                  onClick={() => pickDay(c.date)}
                  disabled={disabled}
                  className={`
                    h-8 w-8 rounded-md text-xs font-medium transition relative
                    ${disabled ? 'opacity-30 cursor-not-allowed' : 'cursor-pointer'}
                    ${c.otherMonth ? 'text-ink-1' : 'text-ink-1'}
                    ${isSelected
                      ? 'bg-rendi-accent text-white font-bold shadow-md shadow-rendi-accent/40'
                      : !disabled && !isSelected
                        ? 'hover:bg-bg-2 dark:hover:bg-bg-3 hover:text-ink-0 dark:hover:text-ink-0'
                        : ''
                    }
                    ${isToday && !isSelected ? 'ring-1 ring-rendi-accent/40 text-rendi-accent' : ''}
                  `}
                >
                  {c.day}
                </button>
              )
            })}
          </div>

          {/* Footer con accesos rápidos */}
          <div className="flex items-center justify-between gap-2 mt-3 pt-3 border-t border-line">
            <button
              type="button"
              onClick={() => pickDay(new Date())}
              className="text-xs px-2 py-1 rounded-md text-rendi-accent hover:bg-rendi-accent/10 font-medium transition"
            >
              Hoy
            </button>
            {value && (
              <button
                type="button"
                onClick={() => { onChange(''); setOpen(false) }}
                className="text-xs px-2 py-1 rounded-md text-ink-3 hover:bg-bg-2 dark:hover:bg-bg-2 transition"
              >
                Limpiar
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
