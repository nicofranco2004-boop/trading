import { Calendar, ChevronLeft, ChevronRight } from 'lucide-react'
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

export default function DateInput({ value, onChange, min, max, className = '', placeholder = 'dd/mm/aaaa' }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef(null)
  const initial = parseISO(value) || new Date()
  const [viewMonth, setViewMonth] = useState(initial.getMonth())
  const [viewYear, setViewYear] = useState(initial.getFullYear())

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

  function pickDay(d) {
    if (minDate && d < minDate) return
    if (maxDate && d > maxDate) return
    onChange(fmtISO(d))
    setOpen(false)
  }

  function isDisabled(d) {
    if (minDate && d < minDate) return true
    if (maxDate && d > maxDate) return true
    return false
  }

  return (
    <div ref={wrapRef} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full bg-slate-50 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-md pl-9 pr-3 py-2 text-sm text-left text-slate-900 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-rendi-green/40 focus:border-rendi-green/60 transition cursor-pointer relative hover:border-slate-400 dark:hover:border-slate-500"
      >
        <Calendar
          size={14}
          className={`absolute left-3 top-1/2 -translate-y-1/2 transition ${
            open ? 'text-rendi-green' : 'text-slate-400 dark:text-slate-500'
          }`}
        />
        {value ? (
          <span className="font-mono">{fmtDisplay(value)}</span>
        ) : (
          <span className="text-slate-400 dark:text-slate-500">{placeholder}</span>
        )}
      </button>

      {open && (
        <div className="absolute z-50 mt-1 left-0 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-2xl p-3 w-[280px]">
          {/* Header */}
          <div className="flex items-center justify-between mb-3">
            <button
              type="button"
              onClick={() => navMonth(-1)}
              className="p-1.5 rounded-md text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 hover:text-rendi-green transition"
            >
              <ChevronLeft size={16} />
            </button>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm text-slate-900 dark:text-white">
                {MONTHS[viewMonth]}
              </span>
              <span className="text-sm text-slate-500 dark:text-slate-400 font-mono">
                {viewYear}
              </span>
            </div>
            <button
              type="button"
              onClick={() => navMonth(1)}
              className="p-1.5 rounded-md text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 hover:text-rendi-green transition"
            >
              <ChevronRight size={16} />
            </button>
          </div>

          {/* Días de la semana */}
          <div className="grid grid-cols-7 gap-1 mb-1">
            {DAYS.map((d, i) => (
              <div key={i} className="text-[10px] font-bold text-slate-400 dark:text-slate-500 text-center py-1 uppercase tracking-wider">
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
                    ${c.otherMonth ? 'text-slate-300 dark:text-slate-600' : 'text-slate-700 dark:text-slate-300'}
                    ${isSelected
                      ? 'bg-rendi-green text-rendi-bg font-bold shadow-md shadow-rendi-green/40'
                      : !disabled && !isSelected
                        ? 'hover:bg-rendi-green/15 hover:text-rendi-green-dark dark:hover:text-rendi-green'
                        : ''
                    }
                    ${isToday && !isSelected ? 'ring-1 ring-rendi-green/40 text-rendi-green-dark dark:text-rendi-green' : ''}
                  `}
                >
                  {c.day}
                </button>
              )
            })}
          </div>

          {/* Footer con accesos rápidos */}
          <div className="flex items-center justify-between gap-2 mt-3 pt-3 border-t border-slate-200 dark:border-slate-700">
            <button
              type="button"
              onClick={() => pickDay(new Date())}
              className="text-xs px-2 py-1 rounded-md text-rendi-green-dark dark:text-rendi-green hover:bg-rendi-green/10 font-medium transition"
            >
              Hoy
            </button>
            {value && (
              <button
                type="button"
                onClick={() => { onChange(''); setOpen(false) }}
                className="text-xs px-2 py-1 rounded-md text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition"
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
