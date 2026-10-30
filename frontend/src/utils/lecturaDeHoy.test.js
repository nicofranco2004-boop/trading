import { describe, it, expect } from 'vitest'
import {
  TEMAS, fraseDeHoy, ladoDelRsi, lugarEnElAnio, miniPromedio, temaDe, tonoDelTema, ultimoCruce,
} from './lecturaDeHoy'
import { tarjetas, tarjetaBandas } from './tecnico'
import { tarjetasMovimiento } from './cuantoSeMueve'

const dia = (i) => new Date(Date.UTC(2026, 0, 1) + i * 86400000).toISOString().slice(0, 10)
// Abajo del promedio hasta el día 30, arriba desde el 30.
const serie = Array.from({ length: 60 }, (_, i) => ({ d: dia(i), c: i < 30 ? 90 : 110, s200: 100, s50: i < 50 ? 120 : 100 }))

const LECTURA = {
  ruedas: 760, fecha: '2026-10-29', precio: 110, media50: 105, dist_media50: 4.8, media200: 100, dist_media200: 10,
  pendiente_media200: 1, rsi: 62, dist_maximo_12m: -3, anio_completo: true, maximo_12m: 113, minimo_12m: 80,
  adx: 27, adx_pendiente: 1, squeeze: 1, squeeze_color: 'verde_fuerte', mov_dia: 2, mov_mes: 9, bb_arriba: 115, bb_abajo: 100, bb_posicion: 0.6,
}

describe('ultimoCruce', () => {
  it('el primer día del tramo de hoy, y para qué lado lo cruzó', () => {
    expect(ultimoCruce(serie, 's200')).toEqual({ i: 30, fecha: dia(30), arriba: true })
    expect(ultimoCruce(serie, 's50')).toEqual({ i: 50, fecha: dia(50), arriba: true })
  })
  it('sin cruce en la serie, o sin promedio, no inventa una fecha', () => {
    expect(ultimoCruce(serie.slice(30), 's200')).toBeNull()
    expect(ultimoCruce(serie.map(p => ({ ...p, s200: null })), 's200')).toBeNull()
    // Los días del principio sin promedio cortan la búsqueda: no se sabe de antes.
    expect(ultimoCruce([{ d: dia(0), c: 90, s200: null }, ...serie.slice(30)], 's200')).toBeNull()
  })
})

describe('la frase de hoy', () => {
  it('con los veredictos de las tarjetas: dos plazos iguales y el impulso', () => {
    expect(fraseDeHoy(tarjetas(LECTURA))).toEqual({ texto: 'tendencia alcista en los dos plazos, con impulso al alza.', tono: 'pos' })
    const bajista = { ...LECTURA, dist_media200: -5, dist_media50: -2, rsi: 50 }
    expect(fraseDeHoy(tarjetas(bajista))).toEqual({ texto: 'tendencia bajista en los dos plazos, sin impulso claro.', tono: 'neg' })
  })
  it('plazos distintos: cada uno con su nombre, y el punto gris', () => {
    const f = fraseDeHoy(tarjetas({ ...LECTURA, dist_media50: -2, rsi: 35 }))
    expect(f).toEqual({ texto: 'largo plazo alcista y mediano plazo bajista, con impulso a la baja.', tono: 'neutro' })
  })
  it('poca historia: lo que hay, y lo dice', () => {
    const corta = { ruedas: 60, fecha: '2026-10-29', media50: 10, dist_media50: 3, rsi: 58 }
    expect(fraseDeHoy(tarjetas(corta)).texto).toBe('mediano plazo alcista, con impulso al alza.')
    expect(fraseDeHoy(tarjetas({ ruedas: 20, rsi: 40 })).texto).toBe('Con impulso a la baja; todavía no hay historia para leer la tendencia.')
    expect(fraseDeHoy([])).toBeNull()
  })
  it('el impulso usa los cortes de la tarjeta del RSI', () => {
    expect([20, 44, 46, 54, 56, 80].map(ladoDelRsi)).toEqual([-1, -1, 0, 0, 1, 1])
    expect(ladoDelRsi(null)).toBe(0)
  })
  it('nunca promete', () => {
    const casos = [LECTURA, { ...LECTURA, dist_media200: -5, rsi: 25 }, { ...LECTURA, dist_media50: -1, rsi: 75 }]
    const textos = casos.map(l => fraseDeHoy(tarjetas(l)).texto).join(' ')
    expect(textos).not.toMatch(/suele|se viene|comprá|vendé|va a subir|va a bajar|rebota|frena|anticipa\b/i)
  })
})

describe('las pestañas', () => {
  it('toda tarjeta que hoy puede aparecer tiene su pestaña (ninguna cae por descarte)', () => {
    const conMov = { disponible: true, peor_caida: null, desde_el_maximo: { pct: -3, anio_completo: true, maximo: 10 }, dia_normal: { desvio_pct: 2, dias: 500, dias_malos: 70 } }
    const ids = [
      ...tarjetas(LECTURA), tarjetaBandas(LECTURA),
      ...tarjetasMovimiento(conMov, { tenencia: { valor: 1000 }, peso: 0.1 }),
    ].map(t => t.id).concat(['fibonacci', 'elliott', 'tuyo'])
    expect(ids).toEqual(expect.arrayContaining(['fondo', 'corto', 'rsi', 'fuerza', 'maximo', 'movimiento', 'bandas', 'caida', 'desde_maximo', 'dia', 'cartera']))
    const conLugar = TEMAS.flatMap(t => t.ids)
    for (const id of ids) expect(conLugar, id).toContain(id)
    expect(temaDe('fondo')).toBe('tendencia')
    expect(temaDe('fuerza')).toBe('impulso')
    expect(temaDe('cartera')).toBe('movimiento')
    expect(temaDe('una-nueva')).toBe('tendencia')
  })
  it('el puntito: verde o rojo si todas dicen lo mismo; el RSI por su impulso', () => {
    const l = tarjetas(LECTURA)
    expect(tonoDelTema('tendencia', l.filter(t => temaDe(t.id) === 'tendencia'))).toBe('pos')
    expect(tonoDelTema('impulso', l.filter(t => temaDe(t.id) === 'impulso'))).toBe('pos')
    expect(tonoDelTema('impulso', [{ id: 'rsi', rsi: 35, tono: 'neutro' }, { id: 'fuerza', tono: 'pos' }])).toBe('neutro')
    expect(tonoDelTema('niveles', [{ tono: 'pos' }])).toBe('neutro')
    expect(tonoDelTema('movimiento', [])).toBe('aviso')
    expect(tonoDelTema('tuyo', [{ id: 'tuyo', tono: 'neg' }])).toBe('neg')
  })
})

describe('los dibujitos', () => {
  it('precio y promedio en el lienzo, con el cruce si cae adentro', () => {
    const m = miniPromedio(serie, 's200', { n: 40 })
    expect(m.precio).toHaveLength(40)
    expect(m.cruce[0]).toBeCloseTo((10 / 39) * 300)   // el día 30 es el 10.º de los últimos 40
    expect(miniPromedio(serie, 's200', { n: 20 }).cruce).toBeNull()
    expect(miniPromedio(serie.slice(0, 1), 's200')).toBeNull()
  })
  it('la regla del año: dónde está hoy entre el mínimo y el máximo', () => {
    expect(lugarEnElAnio(LECTURA)).toBeCloseTo(30 / 33)
    expect(lugarEnElAnio({ ...LECTURA, maximo_12m: 80 })).toBeNull()
    expect(lugarEnElAnio({})).toBeNull()
  })
})
