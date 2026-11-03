// cierreDeVela — cuánto falta para que cierre la vela en curso, como el
// contador de TradingView debajo del precio (Nico, 02/11).
// ════════════════════════════════════════════════════════════════════════════
// SI la vela está en curso lo dice el servidor (`enCurso`: la rueda abierta,
// con su demora, los feriados y los cierres tempranos de Nueva York adentro;
// velas_diarias.en_rueda_de). Acá sólo se cuenta CUÁNDO cierra, con el reloj de
// la bolsa:
//   · cripto: el día entero, en UTC, como TradingView: la vela de 1 hora cierra
//     a la hora en punto; la de 4 horas a las 0, 4, 8… UTC; la diaria a las
//     00:00 UTC (21:00 en Argentina); la semanal el lunes 00:00 UTC.
//   · Nueva York: rueda de 9:30 a 16:00 (hora de allá, con su cambio de hora).
//     Las velas de horas se cortan desde la apertura (10:30, 11:30…; la última,
//     de 15:30 a 16:00); la diaria cierra a las 16:00 y la semanal el viernes.
//   · BYMA: rueda de 11:00 a 17:00 en Argentina; las velas de horas se cortan
//     desde la pre-apertura de las 10:30, como TradingView (velas_horarias.py
//     APERTURA_BYMA_GRAFICO): 11:30, 12:30… y la última de 16:30 a 17:00.
// Fuera de la rueda (por el reloj) no hay cuenta: null.

const MERCADOS = {
  cripto: { zona: 'UTC', abre: 0, corte: 0, cierra: 24 * 60, todosLosDias: true },
  us: { zona: 'America/New_York', abre: 9 * 60 + 30, corte: 9 * 60 + 30, cierra: 16 * 60 },
  byma: { zona: 'America/Argentina/Buenos_Aires', abre: 11 * 60, corte: 10 * 60 + 30, cierra: 17 * 60 },
}
const LARGO = { '1h': 60, '4h': 240 }
const DIAS = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }
const formatos = {}

/** La hora en la bolsa: minutos del día (con segundos, en fracción) y día de la semana (0 = domingo). */
function relojDe(zona, ms) {
  const f = formatos[zona] ||= new Intl.DateTimeFormat('en-US', {
    timeZone: zona, hourCycle: 'h23', weekday: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
  const p = Object.fromEntries(f.formatToParts(new Date(ms)).map(x => [x.type, x.value]))
  return { min: Number(p.hour) * 60 + Number(p.minute) + Number(p.second) / 60, dia: DIAS[p.weekday] }
}

/**
 * Cuándo cierra (ms) la vela de `cada` ('1h' | '4h' | 'dia' | 'semana') que
 * está en curso en `ahora`, en el mercado `mercado` ('us' | 'byma' | 'cripto').
 * null si por el reloj no hay rueda (o el mercado no se conoce).
 */
export function cierreDeVela(mercado, cada, ahora = Date.now()) {
  const m = MERCADOS[mercado]
  if (!m) return null
  const { min, dia } = relojDe(m.zona, ahora)
  if (!m.todosLosDias && (dia === 0 || dia === 6 || min < m.abre || min >= m.cierra)) return null
  let fin
  if (LARGO[cada]) fin = Math.min(m.corte + (Math.floor((min - m.corte) / LARGO[cada]) + 1) * LARGO[cada], m.cierra)
  else if (cada === 'dia') fin = m.cierra
  else if (cada === 'semana') fin = m.cierra + 1440 * (m.todosLosDias ? (7 - dia) % 7 : 5 - dia)
  else return null
  return ahora + Math.round((fin - min) * 60) * 1000
}

/** «12:05» (menos de una hora), «3:12:05», «2d 5h» (más de un día). */
export function textoCuenta(ms) {
  const s = Math.max(0, Math.round(ms / 1000))
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), mi = Math.floor((s % 3600) / 60), se = s % 60
  const dos = (n) => String(n).padStart(2, '0')
  if (d > 0) return `${d}d ${h}h`
  return h > 0 ? `${h}:${dos(mi)}:${dos(se)}` : `${dos(mi)}:${dos(se)}`
}
