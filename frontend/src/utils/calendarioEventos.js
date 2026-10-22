// calendarioEventos.js — las cuentas del calendario de Eventos ("Ver calendario").
// ════════════════════════════════════════════════════════════════════════════
// El calendario no trae datos propios: dibuja por mes los MISMOS eventos de la
// pestaña "Para ti" — los de las empresas (`/api/events/portfolio`: balances,
// corte y pago de dividendos, sólo los que tienen fecha conocida) y los de los
// bonos (`upcomingBondEvents`, el cronograma). Acá vive lo que es del calendario:
// qué tipo de evento entra, en qué casillero cae y qué meses se pueden recorrer.

// Lo que muestra el calendario, por tipo de evento. Lo que no está acá (macro,
// splits) no entra: el pedido es "cobros y balances".
const CATEGORIA = {
  payment_date: 'cobro',
  bond_coupon: 'cobro',
  bond_coupon_amort: 'cobro',
  bond_amort: 'cobro',
  bond_maturity: 'cobro',
  ex_dividend: 'corte',
  earnings: 'balance',
}

export const FILTROS = [
  { id: 'todo', label: 'Todo' },
  { id: 'cobros', label: 'Dividendos y cupones' },
  { id: 'balances', label: 'Balances' },
]

export const DIAS_SEMANA = ['L', 'M', 'M', 'J', 'V', 'S', 'D']
const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio',
  'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

/** 'cobro' | 'corte' | 'balance' | null */
export function categoriaDe(eventType) {
  return CATEGORIA[eventType] || null
}

/** Cómo se llama cada evento en el calendario. */
export function rotuloDe(eventType) {
  switch (eventType) {
    case 'earnings': return 'Presenta balance'
    case 'ex_dividend': return 'Corte del dividendo'
    case 'payment_date': return 'Pago del dividendo'
    case 'bond_coupon': return 'Cupón'
    case 'bond_coupon_amort': return 'Cupón + amortización'
    case 'bond_amort': return 'Amortización'
    case 'bond_maturity': return 'Vencimiento'
    default: return eventType
  }
}

export function nombreDelMes(anio, mes) {
  return `${MESES[mes - 1]} ${anio}`
}

function pasaElFiltro(ev, filtro) {
  const c = categoriaDe(ev.eventType)
  if (!c) return false
  if (filtro === 'cobros') return c === 'cobro' || c === 'corte'
  if (filtro === 'balances') return c === 'balance'
  return true
}

/** Los eventos del calendario, de hoy en adelante, ordenados por fecha. */
export function eventosDelCalendario(eventos = [], { hoy, filtro = 'todo' } = {}) {
  return eventos
    .filter(e => e.eventDate && e.eventDate >= hoy && pasaElFiltro(e, filtro))
    .sort((a, b) => a.eventDate.localeCompare(b.eventDate) || a.ticker.localeCompare(b.ticker))
}

/** Map 'AAAA-MM-DD' → [eventos] */
export function porDia(eventos = []) {
  const m = new Map()
  for (const e of eventos) {
    if (!m.has(e.eventDate)) m.set(e.eventDate, [])
    m.get(e.eventDate).push(e)
  }
  return m
}

const iso = (y, m, d) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`

/** Las semanas del mes, de lunes a domingo: cada una 7 fechas o null (relleno).
 *  SIEMPRE seis semanas, aunque el mes entre en cinco (o en cuatro, un febrero
 *  que arranca lunes): con un alto distinto por mes, la ventana se volvía a
 *  centrar al pasar de mes y la flecha de "siguiente" se corría de debajo del
 *  mouse (pedido de Nico, 2026-10-22). */
export function semanasDelMes(anio, mes) {
  const dias = new Date(Date.UTC(anio, mes, 0)).getUTCDate()
  // getUTCDay: 0 = domingo. Lo corremos para que el lunes sea la columna 0.
  const blancos = (new Date(Date.UTC(anio, mes - 1, 1)).getUTCDay() + 6) % 7
  const celdas = [...Array(blancos).fill(null)]
  for (let d = 1; d <= dias; d++) celdas.push(iso(anio, mes, d))
  while (celdas.length < 42) celdas.push(null)
  const semanas = []
  for (let i = 0; i < celdas.length; i += 7) semanas.push(celdas.slice(i, i + 7))
  return semanas
}

/** Los meses que se pueden recorrer: del de hoy al del último evento, 13 como
 *  mucho (la búsqueda de eventos mira un año para adelante). */
export function mesesDelCalendario(hoy, eventos = []) {
  let y = Number(hoy.slice(0, 4)), m = Number(hoy.slice(5, 7))
  const ultimo = eventos.reduce((max, e) => (e.eventDate > max ? e.eventDate : max), hoy)
  const yf = Number(ultimo.slice(0, 4)), mf = Number(ultimo.slice(5, 7))
  const out = []
  while ((y < yf || (y === yf && m <= mf)) && out.length < 13) {
    out.push({ anio: y, mes: m })
    m += 1
    if (m > 12) { m = 1; y += 1 }
  }
  return out
}
