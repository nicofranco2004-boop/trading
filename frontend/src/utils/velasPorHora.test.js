// Las cuentas de las velas de 1 y 4 horas (utils/velasPorHora.js): dónde cae
// cada cosa guardada por día o por momento, el eje de horas, el refresco y la
// mezcla de lo que llega cada minuto. Lo montado (el menú, la vela en curso que
// se mueve, la pestaña oculta) está en components/asset/LecturaTecnicaHoras.test.js.
import { describe, it, expect } from 'vitest'
import {
  cadaCuantoRefrescar, esIntradia, fechaHoraCorta, fechaHoraDeLaMira, horaArt, marcasDeHoras, mezclar,
  primeraVelaDelDia, REFRESCO_HORAS_MS, textoEnCurso, textoMedicionPorHora, ubicadorPorHora, velasRecientes,
} from './velasPorHora'
import { indiceDeFecha } from './tecnico'

// Nueva York en horario de verano: 9:30 de allá = 13:30 UTC = 10:30 en Buenos Aires.
const SESION_NY = { abre: 570, cierra: 960, desfase: -240, todos_los_dias: false, velas_por_dia: 7 }
const utc = (a, m, d, hh, mm = 0) => Date.UTC(a, m - 1, d, hh, mm) / 1000

/** Velas de 1 hora de Nueva York (9:30 a 15:30 de allá) de estos días de octubre de 2026. */
function horasNY(dias) {
  const out = []
  for (const d of dias) {
    for (let k = 0; k < 7; k++) {
      const t = utc(2026, 10, d, 13 + k, 30)
      out.push({ d: `2026-10-${String(d).padStart(2, '0')}`, t, c: 100 + out.length })
    }
  }
  return out
}
// Lunes 19 a jueves 29 de octubre (sin el fin de semana del 24 y 25).
const DIAS = [19, 20, 21, 22, 23, 26, 27, 28, 29]
const SERIE = horasNY(DIAS)
const DIARIOS = DIAS.slice(0, -1).map(d => ({ d: `2026-10-${d}` }))   // el 29 todavía no está en las diarias

describe('qué es 1H y 4H', () => {
  it('1h y 4h son de horas; dia y semana no', () => {
    expect(['1h', '4h', 'dia', 'semana'].map(esIntradia)).toEqual([true, true, false, false])
  })
})

describe('la hora, en hora argentina', () => {
  it('la vela de las 9:30 de Nueva York es la de las 10:30 de acá', () => {
    const t = utc(2026, 10, 29, 13, 30)
    expect(horaArt(t)).toBe('10:30')
    expect(fechaHoraCorta(t)).toBe('29/10/26 10:30')
    expect(fechaHoraDeLaMira(t)).toBe('jue 29 oct 10:30')
  })
  it('una cripto a las 01:00 UTC del 30 es el 29 a las 22:00 en Buenos Aires', () => {
    expect(fechaHoraCorta(utc(2026, 10, 30, 1))).toBe('29/10/26 22:00')
  })
})

describe('mezclar lo que llega cada minuto', () => {
  it('lo nuevo reemplaza desde su primera vela: la en curso se actualiza y la nueva se agrega', () => {
    const antes = [{ t: 1, c: 1 }, { t: 2, c: 2 }, { t: 3, c: 3, enCurso: true }]
    expect(mezclar(antes, [{ t: 3, c: 3.5 }, { t: 4, c: 4, enCurso: true }]))
      .toEqual([{ t: 1, c: 1 }, { t: 2, c: 2 }, { t: 3, c: 3.5 }, { t: 4, c: 4, enCurso: true }])
    expect(mezclar(antes, [])).toBe(antes)
  })
})

describe('el ritmo del refresco', () => {
  it('cada minuto con la rueda en horario; con todo cerrado, a la próxima media hora', () => {
    expect(cadaCuantoRefrescar(true)).toBe(REFRESCO_HORAS_MS)
    expect(REFRESCO_HORAS_MS).toBe(60_000)
    // 10:12 → la próxima media hora es 10:30, más el margen de 90 s.
    expect(cadaCuantoRefrescar(false, new Date(Date.UTC(2026, 9, 30, 13, 12)))).toBe(18 * 60_000 + 90_000)
  })
})

describe('«en curso · hace X s»', () => {
  it('cuenta desde que se bajó el dato, no desde que llegó a la pantalla', () => {
    const ahora = Date.parse('2026-10-30T15:00:20Z')
    expect(textoEnCurso('2026-10-30T15:00:00Z', ahora)).toBe('en curso · hace 20 s')
    expect(textoEnCurso('2026-10-30T14:57:00Z', ahora)).toBe('en curso · hace 3 min')
    expect(textoEnCurso(null, ahora)).toBe('en curso')
  })
})

describe('lo que se ve al abrir', () => {
  it('las velas que entran a 6 px cada una; null si ya entran todas', () => {
    expect(velasRecientes(900, 1000)).toBe(150)
    expect(velasRecientes(900, 100)).toBeNull()
    expect(velasRecientes(null, 1000)).toBeNull()
  })
})

describe('primeraVelaDelDia: tus compras, los balances y los dividendos', () => {
  it('en 1H, la primera hora de esa rueda', () => {
    expect(primeraVelaDelDia(SERIE, '2026-10-21')).toBe(14)
    expect(indiceDeFecha(SERIE, '2026-10-21')).toBe(20)    // (la última hora: su cierre es el del día)
  })
  it('un sábado va a la rueda de antes, como en las diarias', () => {
    expect(primeraVelaDelDia(SERIE, '2026-10-24')).toBe(28)   // el viernes 23, su primera hora
  })
  it('antes de la serie, nada', () => {
    expect(primeraVelaDelDia(SERIE, '2026-10-01')).toBeNull()
  })
  it('con una vela por día (diarias) da lo mismo que indiceDeFecha', () => {
    const diarias = DIAS.map(d => ({ d: `2026-10-${d}` }))
    for (const f of ['2026-10-18', '2026-10-19', '2026-10-24', '2026-10-29', '2026-11-02']) {
      expect(primeraVelaDelDia(diarias, f)).toBe(indiceDeFecha(diarias, f))
    }
  })
})

describe('el eje de horas', () => {
  it('diez ruedas de 1 hora en un gráfico angosto dicen el comienzo de cada semana (antes no decía nada)', () => {
    const m = marcasDeHoras(SERIE, 300)
    expect(m.map(x => x.texto)).toEqual(['26 oct'])
    expect(SERIE[m[0].i].d).toBe('2026-10-26')
  })
  it('con más lugar, cada día; acercado, las horas', () => {
    expect(marcasDeHoras(SERIE, 1400).map(x => x.texto)).toContain('20 oct')
    const unDia = SERIE.slice(-7)
    expect(marcasDeHoras(unDia, 700).map(x => x.texto)).toEqual(['11:30', '12:30', '13:30', '14:30', '15:30', '16:30'])
  })
})

describe('ubicar por fecha y hora (tus dibujos y notas en 1H/4H)', () => {
  const u = ubicadorPorHora(SERIE, { sesion: SESION_NY, cada: '1h', diarios: DIARIOS })
  const ultima = SERIE.length - 1   // la de las 15:30 de allá del 29

  it('un punto con momento va a su vela, con la parte de la vela que corresponde', () => {
    expect(u.lugarDelPunto({ d: '2026-10-21', mas: 0, t: utc(2026, 10, 21, 15, 30), precio: 1 })).toBe(16)
    // 12:00 de allá: la mitad de la vela de las 11:30.
    expect(u.lugarDelPunto({ d: '2026-10-21', mas: 0, t: utc(2026, 10, 21, 16, 0), precio: 1 })).toBeCloseTo(16.5)
  })
  it('un punto dibujado en diarias (sólo el día) va a la PRIMERA vela de ese día, como TradingView', () => {
    expect(u.lugarDelPunto({ d: '2026-10-21', mas: 0, precio: 1 })).toBe(14)
    // Un sábado: la rueda de antes.
    expect(u.lugarDelPunto({ d: '2026-10-24', mas: 0, precio: 1 })).toBe(28)
    // El pincel, con la parte del día: la mitad del día son 3,5 velas de 7.
    expect(u.lugarDelPunto({ d: '2026-10-21', mas: 0, f: 0.5, precio: 1 })).toBeCloseTo(17.5)
  })
  it('antes de las velas de horas que hay no se sabe dónde va: null (no se dibuja)', () => {
    expect(u.lugarDelPunto({ d: '2026-10-16', mas: 0, precio: 1 })).toBeNull()
    expect(u.lugarDelPunto({ d: '2026-10-16', mas: 0, t: utc(2026, 10, 16, 14), precio: 1 })).toBeNull()
  })
  it('hacia adelante, con el horario de la rueda: «2 días de mercado después» del jueves es el lunes', () => {
    // El jueves 29 en las diarias todavía no está: «el 28 y 1 día después» es el 29.
    expect(u.lugarDelPunto({ d: '2026-10-28', mas: 1, precio: 1 })).toBe(56)
    // 3 días de mercado después del 28: el viernes 30 (63) y el lunes 2 (70).
    expect(u.lugarDelPunto({ d: '2026-10-28', mas: 3, precio: 1 })).toBe(70)
    // Un momento del lunes 2/11 a las 11:30 de Nueva York (ya en invierno, pero se
    // proyecta con la hora de la última vela): la 3ra vela de esa rueda.
    expect(u.lugarDelPunto({ d: '2026-10-28', mas: 3, t: utc(2026, 11, 2, 15, 30), precio: 1 })).toBe(72)
  })
  it('lo que se guarda de un toque: el momento y, para las diarias, el día', () => {
    const p = u.puntoDelLugar(16, 123.456789)
    expect(p).toEqual({ d: '2026-10-21', mas: 0, t: utc(2026, 10, 21, 15, 30), precio: 123.4568 })
    expect(u.lugarDelPunto(p)).toBe(16)
    // El 29 todavía no está en las diarias: se guarda «1 día de mercado después del 28».
    expect(u.puntoDelLugar(ultima, 1)).toEqual({ d: '2026-10-28', mas: 1, t: utc(2026, 10, 29, 19, 30), precio: 1 })
  })
  it('un toque hacia adelante: el lunes siguiente a las 10:30 de allá, y vuelve al mismo lugar', () => {
    const p = u.puntoDelLugar(56 + 7 * 2 + 1, 1)    // dos ruedas después del 29, la 2da vela
    expect(p.t).toBe(utc(2026, 11, 2, 14, 30))
    expect(p).toMatchObject({ d: '2026-10-28', mas: 3 })
    expect(u.lugarDelPunto(p)).toBe(71)
  })
  it('el pincel guarda la parte del día, así en diarias no queda en escalones', () => {
    // La mitad de la vela de las 12:30 de allá (la 4ta de 7 del día).
    const p = u.puntoDelLugar(17.5, 1, { fraccion: true })
    expect(p.f).toBe(0.5)
    expect(p.t).toBe(utc(2026, 10, 21, 17, 0))
  })
})

describe('4 horas y cripto', () => {
  it('cripto: cada día UTC, 6 bloques; hacia adelante se cuentan todos los días', () => {
    const sesion = { abre: 0, cierra: 1440, desfase: 0, todos_los_dias: true, velas_por_dia: 6 }
    const serie = []
    for (let k = 0; k < 6 * 3; k++) {
      const t = utc(2026, 10, 23, 0) + k * 4 * 3600
      serie.push({ d: new Date(t * 1000).toISOString().slice(0, 10), t, c: 1 })
    }
    const u = ubicadorPorHora(serie, { sesion, cada: '4h', diarios: [{ d: '2026-10-25' }] })
    // Sábado y domingo también son ruedas: un día después del domingo 25 es el lunes 26.
    expect(u.lugarDelPunto({ d: '2026-10-25', mas: 1, precio: 1 })).toBe(18)
    expect(u.lugarDelPunto({ d: '2026-10-24', mas: 0, t: utc(2026, 10, 24, 14), precio: 1 })).toBeCloseTo(9.5)
  })
})

describe('medir en 1H/4H', () => {
  it('dice cuántas velas, no días de mercado', () => {
    expect(textoMedicionPorHora({ pct: 2.34, dias: 14, diferencia: 1 }, '1h')).toBe('+2,3% en 14 velas de 1 hora')
    expect(textoMedicionPorHora({ pct: -1, dias: 1, diferencia: -1 }, '4h')).toBe('−1,0% en 1 vela de 4 horas')
  })
})
