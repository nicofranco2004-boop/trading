// Tus líneas de tendencia y canales recuerdan la escala en que los dibujaste
// (Nico, 12/11, «opción A»): rectos en SU escala, curvos mirados en la otra, y
// el precio que mira el aviso es el de su escala. Las cuentas de la pantalla
// (CapaDibujos, utils/dibujos.js, MiniLinea), sin montar el gráfico; montado,
// en EscalaLogGrafico.test.js. El servidor hace la misma cuenta
// (backend/tecnico.valor_de_linea): ver backend/tests/test_alertas_tecnicas.py.
import { describe, it, expect } from 'vitest'
import { anchoDelCanal, preciosAlBorde, puntosDeLaRecta, trazosDeDibujos } from './CapaDibujos'
import { dibujoCorrido, dibujoValido, puntasDe } from '../../utils/dibujos'
import { armarEscala, precioCorrido } from '../../utils/escalaPrecio'
import { trazosDeMiniLinea } from '../alerts/MiniLinea'
import { specDelGrafico } from '../../utils/imagenGrafico'

// Un gráfico de 101 lugares (pctX(k) = k) y precios de 10 a 1000 de alto.
const pctX = (k) => k
const enVista = (escala) => armarEscala(10, 1000, 100, escala).y
const P = (k, precio) => ({ k, precio })

describe('el precio de tu línea, el que mira el aviso', () => {
  it('es el de su escala: el ejemplo de NVDA, US$ 66 en la de siempre y US$ 89 en la logarítmica', () => {
    const t = { id: 't', tipo: 'tendencia', a: P(0, 14.8095), b: P(52, 48.9551) }
    expect(preciosAlBorde(t, 78)[0]).toBeCloseTo(66.03, 1)
    expect(preciosAlBorde({ ...t, escala: 'log' }, 78)[0]).toBeCloseTo(89.01, 1)
  })

  it('un canal logarítmico: su paralela multiplica', () => {
    const c = { id: 'c', tipo: 'canal', a: P(0, 100), b: P(10, 200), ancho: Math.log(1.5), escala: 'log' }
    const [abajo, arriba] = preciosAlBorde(c, 20)
    expect(abajo).toBeCloseTo(400)
    expect(arriba).toBeCloseTo(600)
  })
})

describe('recta en su escala, curva en la otra', () => {
  const t = { id: 't', tipo: 'tendencia', a: P(10, 20), b: P(60, 400), escala: 'log' }

  it('mirada en su escala, un solo trazo recto', () => {
    const tr = trazosDeDibujos([t], pctX, enVista('log'), [], 'log')
    expect(tr).toHaveLength(1)
    expect(tr[0].curva).toBeUndefined()
  })

  it('mirada en la de siempre, una curva de muchos tramos que pasa por sus dos puntas', () => {
    const y = enVista('lineal')
    const tr = trazosDeDibujos([t], pctX, y, [], 'lineal')
    expect(tr.length).toBeGreaterThan(10)
    expect(new Set(tr.map(x => x.curva)).size).toBe(1)
    expect(tr[0].y1).toBeCloseTo(y(20))
    expect(tr.at(-1).y2).toBeCloseTo(y(400))
    // En el medio pasa por la media geométrica (recta en log), no por el promedio.
    const medio = tr.find(x => Math.abs(x.x1 - 35) < 1e-9)
    expect(medio.y1).toBeCloseTo(y(Math.sqrt(20 * 400)), 6)
    expect(Math.abs(medio.y1 - y(210))).toBeGreaterThan(10)        // el promedio (210) queda lejos
  })

  it('una línea que multiplica mucho su precio: la curva no se aparta de la de verdad (ni medio por ciento del alto)', () => {
    // De 10 a 600 (×60) en 50 lugares, mirada en la de siempre: casi todo el
    // salto está cerca de la punta cara, y ahí la curva se empina.
    const empinada = { id: 'e', tipo: 'tendencia', a: P(10, 10), b: P(60, 600), escala: 'log' }
    const y = armarEscala(5, 700, 100, 'lineal').y
    const tr = trazosDeDibujos([empinada], pctX, y, [], 'lineal')
    for (let k = 10; k <= 60; k += 0.25) {
      const t = tr.find(s => s.x1 <= k && s.x2 >= k)
      const enLaCurva = t.y1 + ((t.y2 - t.y1) * (k - t.x1)) / (t.x2 - t.x1 || 1)
      expect(Math.abs(enLaCurva - y(preciosAlBorde(empinada, k)[0]))).toBeLessThan(0.5)
    }
  })

  it('con aviso, sigue hasta el borde por la recta de su escala', () => {
    const tr = trazosDeDibujos([t], pctX, enVista('lineal'), ['t'], 'lineal').filter(x => x.correccion)
    expect(tr.at(-1).x2).toBe(100)
    expect(tr.at(-1).y2).toBeCloseTo(enVista('lineal')(preciosAlBorde(t, 100)[0]))
  })

  it('las dos puntas en el mismo lugar (en semanales, la misma semana): una raya de una a la otra, como siempre', () => {
    const misma = { id: 's', tipo: 'tendencia', a: P(40, 100), b: P(40, 120) }
    for (const vista of ['lineal', 'log']) {
      const [tr] = trazosDeDibujos([misma], pctX, enVista(vista), [], vista)
      expect(tr.y1).toBeCloseTo(enVista(vista)(100))
      expect(tr.y2).toBeCloseTo(enVista(vista)(120))
    }
  })

  it('una línea de antes (sin escala) no cambia nada mirada en la de siempre', () => {
    const vieja = { id: 'v', tipo: 'tendencia', a: P(10, 20), b: P(60, 400) }
    const [tr] = trazosDeDibujos([vieja], pctX, enVista('lineal'))
    expect(tr).toMatchObject({ x1: 10, x2: 60 })
    expect(tr.y1).toBeCloseTo(enVista('lineal')(20))
    expect(tr.y2).toBeCloseTo(enVista('lineal')(400))
  })

  it('el canal: tres bordes curvos y la franja por los dos bordes', () => {
    const c = { id: 'c', tipo: 'canal', a: P(10, 20), b: P(60, 400), ancho: Math.log(2), escala: 'log' }
    const tr = trazosDeDibujos([c], pctX, enVista('lineal'), [], 'lineal')
    expect(new Set(tr.map(x => x.curva)).size).toBe(3)
    const franja = [...puntosDeLaRecta(c.a, c.b, 10, 60, 'log', 'lineal', pctX, enVista('lineal')),
      ...puntosDeLaRecta(c.a, c.b, 60, 10, 'log', 'lineal', pctX, enVista('lineal'), c.ancho)]
    expect(franja.at(-1)[1]).toBeCloseTo(enVista('lineal')(40))   // la paralela en a: el doble
  })
})

describe('el ancho de un canal', () => {
  it('al dibujarlo, en la escala que se mira: plata o cuánto multiplica', () => {
    const a = P(0, 100), b = P(10, 100), c = P(5, 150)
    expect(anchoDelCanal(a, b, c, 'lineal')).toBeCloseTo(50)
    expect(anchoDelCanal(a, b, c, 'log')).toBeCloseTo(Math.log(1.5))
  })

  it('ensancharlo arrastrando su punta, con el canal y la vista en escalas distintas', () => {
    const c = { id: 'c', tipo: 'canal', a: P(0, 100), b: P(10, 100), ancho: Math.log(1.5), escala: 'log' }
    const [, , [, punta]] = puntasDe(c)
    expect(punta).toEqual({ k: 5, precio: expect.closeTo(150, 6) })
    // Mirando en la de siempre, la punta sube 30 de plata: la paralela queda en 180.
    const vista = 'lineal'
    const ancho = dibujoCorrido(c, 'ancho', (p) => p, (x) => precioCorrido(x, 30, vista)).ancho
    expect(ancho).toBeCloseTo(Math.log(1.8))
    // Mirando en logarítmica, la punta sube «el doble»: la paralela queda en 300.
    expect(dibujoCorrido(c, 'ancho', (p) => p, (x) => precioCorrido(x, Math.log(2), 'log')).ancho).toBeCloseTo(Math.log(3))
    // Un canal de siempre, como antes: la plata que se corrió.
    const viejo = { ...c, ancho: 50, escala: undefined }
    expect(dibujoCorrido(viejo, 'ancho', (p) => p, (x) => precioCorrido(x, 30, 'lineal')).ancho).toBeCloseTo(80)
  })

  it('un canal logarítmico con un ancho que no es un canal no se dibuja (como el servidor)', () => {
    const c = { id: 'c', tipo: 'canal', a: { d: '2026-01-02', mas: 0, precio: 10 }, b: { d: '2026-02-02', mas: 0, precio: 12 }, escala: 'log' }
    expect(dibujoValido({ ...c, ancho: 0.4 })).toBe(true)
    expect(dibujoValido({ ...c, ancho: 25 })).toBe(false)
    expect(dibujoValido({ ...c, ancho: 25, escala: undefined })).toBe(true)
  })
})

describe('el gráfico chico de «Mis alertas»', () => {
  it('una línea logarítmica se dibuja en su escala: recta, como en la ficha', () => {
    const serie = Array.from({ length: 11 }, () => 100)
    const linea = Array.from({ length: 11 }, (_, i) => 100 * Math.pow(2, i / 10))
    const recta = (ps) => {
      const xy = ps.map(p => p.split(',').map(Number))
      const m = (xy.at(-1)[1] - xy[0][1]) / (xy.at(-1)[0] - xy[0][0])
      return xy.every(([x, y]) => Math.abs(y - (xy[0][1] + m * (x - xy[0][0]))) < 0.15)
    }
    expect(recta(trazosDeMiniLinea({ serie, lineas: [linea], escala: 'log' }, 100, 50).lineas[0])).toBe(true)
    expect(recta(trazosDeMiniLinea({ serie, lineas: [linea] }, 100, 50).lineas[0])).toBe(false)
  })
})

describe('la imagen de «Compartir» en logarítmica', () => {
  it('una banda de Bollinger bajo cero se corta, como en la pantalla (no raya la imagen)', () => {
    const puntos = Array.from({ length: 40 }, (_, i) => ({
      d: new Date(Date.UTC(2026, 0, 1) + i * 86400000).toISOString().slice(0, 10), c: 30 + i,
      bb_arriba: 40 + i, bb_abajo: i >= 22 && i < 30 ? -3 : 20 + i,
    }))
    const spec = specDelGrafico({ activo: 'ZZ', puntos, lo: 5, hi: 90, escalaDePrecio: 'log', ver: { bb: true } })
    const ys = [...spec.grafico.lineas.flatMap(l => l.puntos), ...spec.grafico.poligonos.flatMap(p => p.puntos)].map(([, y]) => y)
    expect(ys.every(y => Number.isFinite(y) && y >= 0 && y <= 100)).toBe(true)
    expect(spec.pie.some(t => t.startsWith('Escala logarítmica'))).toBe(true)
  })
})
