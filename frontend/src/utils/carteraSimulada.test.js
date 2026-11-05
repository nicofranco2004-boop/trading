// Las palabras y las cuentas chicas de «Una cartera» (utils/carteraSimulada.js).
// Lo que importa:
//   · el máximo de activos y la tolerancia del 100 son los del servidor
//     (backend/cartera_simulada.py): uno distinto daría un 400;
//   · lo que se dice sale de la respuesta REAL del servidor
//     (backend/tests/fixtures/cartera_simulada.json, que test_cartera_simulada.py
//     compara contra cartera_simulada.simular), no de un caso armado a mano;
//   · cada porcentaje acepta coma, hasta 100; cuánto falta o sobra se dice;
//   · la torta va de la porción más grande a la más chica, con la rampa de las
//     tortas de composición, y lo que falta para 100 al final;
//   · cada número de una frase es el de su tarjeta (el formateador de la tarjeta,
//     no una cuenta de la prueba);
//   · habla de lo que tenemos («no tenemos los precios de AL30»), y con el asesor
//     adentro de un cliente, de la cartera de él;
//   · nunca promete ni dice cuál cartera es «mejor».
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import {
  COMO_SE_SIMULA_CARTERA, MAX_ACTIVOS, NOTA_CADA_ACTIVO, QUE_SE_SIMULA, TOLERANCIA,
  aLaDireccion, carteraDe, consultaDe, errorDeHoy, estadoDeLaCartera, filasDeHoy, lecturaCartera, limpiar, loQueFalta,
  modoDe, motivoCartera, notaDeHoy, notaDeLosQueSobran, notaHoy, notaOjito, notaSinActivos, numeroDe, origenDe,
  origenes, porcionesDeLaTorta, repartirIgual, sobranDe, textoDe, totalDe, trayendoHoy,
} from './carteraSimulada'
import { porcentaje } from './backtesting'
import { porcionColor } from './chartTheme'

const AQUI = dirname(fileURLToPath(import.meta.url))
const CASOS = JSON.parse(readFileSync(resolve(AQUI, '../../../backend/tests/fixtures/cartera_simulada.json'), 'utf8'))
const PY = readFileSync(resolve(AQUI, '../../../backend/cartera_simulada.py'), 'utf8')
const fila = (asset, txt, local = false) => ({ asset, local, txt })

describe('lo que se acepta es lo del servidor', () => {
  it('el máximo de activos y la tolerancia del 100', () => {
    expect(MAX_ACTIVOS).toBe(Number(PY.match(/^MAX_ACTIVOS = (\d+)/m)[1]))
    expect(TOLERANCIA).toBe(Number(PY.match(/^TOLERANCIA = ([\d.]+)/m)[1]))
  })

  it('el modo y con qué arranca, de la dirección', () => {
    expect([modoDe('cartera'), modoDe('otra'), modoDe(null)]).toEqual(['cartera', 'regla', 'regla'])
    expect([origenDe('cero'), origenDe('hoy'), origenDe(undefined)]).toEqual(['cero', 'hoy', 'hoy'])
    // Un link con una cartera y sin `origen` es una armada (la de hoy nunca va en
    // la dirección); con origen=hoy explícito, manda el origen.
    expect([origenDe(null, true), origenDe('hoy', true), origenDe('cero', false)]).toEqual(['cero', 'hoy', 'cero'])
  })
})

describe('cada porcentaje', () => {
  it('con coma o punto, y lo vacío es 0', () => {
    expect([numeroDe('33,3'), numeroDe('33.3'), numeroDe(''), numeroDe('x'), numeroDe('-5')]).toEqual([33.3, 33.3, 0, 0, 0])
    expect([textoDe(40), textoDe(33.3), textoDe(33.333), textoDe(0)]).toEqual(['40', '33,3', '33,33', ''])
  })

  it('mientras se escribe: dígitos y una coma, hasta 2 decimales y no más de 100', () => {
    expect(['30', '33,3', '33.3', '33,333', '3,3,3', 'a5', '150', ',5', '007', '100,5'].map(limpiar))
      .toEqual(['30', '33,3', '33,3', '33,33', '3,33', '5', '100', '0,5', '7', '100'])
  })

  it('cuánto falta, cuánto sobra, y que cada uno tenga el suyo', () => {
    expect(estadoDeLaCartera([])).toMatchObject({ listo: false, texto: 'Faltan 100%', aviso: null })
    expect(estadoDeLaCartera([fila('A', '60'), fila('B', '25')])).toMatchObject({
      listo: false, total: 85, totalTxt: '85%', texto: 'Faltan 15%',
      aviso: 'Para ver cómo le habría ido, los porcentajes tienen que sumar 100%: falta repartir 15%.',
    })
    expect(estadoDeLaCartera([fila('A', '60'), fila('B', '45,5')])).toMatchObject({ listo: false, texto: 'Sobran 5,5%' })
    expect(estadoDeLaCartera([fila('A', '33,33'), fila('B', '33,33'), fila('C', '33,34')])).toMatchObject({ listo: true, texto: 'Suma 100%' })
    // «Suma 100%» en ámbar con un porcentaje sin poner parecía una contradicción:
    // dice qué falta (auditoría 05/11, B7).
    expect(estadoDeLaCartera([fila('A', '100'), fila('B', '')])).toMatchObject({
      listo: false, texto: 'Falta un porcentaje', aviso: 'B no tiene porcentaje: poné cuánto va, o sacalo.',
    })
    expect(estadoDeLaCartera([fila('A', '100'), fila('B', ''), fila('C', '')])).toMatchObject({
      listo: false, texto: 'Faltan porcentajes', aviso: 'B y C no tienen porcentaje: poné cuánto va en cada uno, o sacalos.',
    })
    // El borde de la tolerancia, como lo cuenta el servidor (a centavos): 99,96 sí,
    // 99,9 no (auditoría de las pruebas, F2).
    expect(estadoDeLaCartera([fila('A', '50'), fila('B', '49,96')])).toMatchObject({ listo: true })
    expect(estadoDeLaCartera([fila('A', '50'), fila('B', '49,9')])).toMatchObject({ listo: false, texto: 'Faltan 0,1%' })
    expect(estadoDeLaCartera([fila('A', '50,03'), fila('B', '50,02')])).toMatchObject({ listo: true })
    expect(totalDe([fila('A', '33,3'), fila('B', '33,3'), fila('C', '33,4')])).toBe(100)
  })

  it('repartir en partes iguales suma 100, y el que se suma toma lo que falta', () => {
    expect(repartirIgual(3)).toEqual([34, 33, 33])
    for (const n of [1, 2, 6, 7, 10]) expect(repartirIgual(n).reduce((a, b) => a + b, 0)).toBe(100)
    expect(loQueFalta([fila('A', '60')])).toBe(40)
    expect(loQueFalta([fila('A', '60'), fila('B', '50')])).toBe(0)
  })
})

describe('la dirección y el pedido', () => {
  it('ida y vuelta, sin repetir y hasta el máximo', () => {
    const filas = [fila('AAPL', '60'), fila('GGAL', '33,5', true), fila('BTC', '6,5')]
    const d = aLaDireccion(filas)
    expect(d).toEqual({ activos: 'AAPL,GGAL,BTC', pesos: '60,33.5,6.5', local: 'GGAL' })
    expect(carteraDe(new URLSearchParams(d))).toEqual(filas)
    const muchos = Array.from({ length: 12 }, (_, i) => `T${i}`)
    expect(carteraDe(new URLSearchParams({ activos: [...muchos, 'T0'].join(','), pesos: '' }))).toHaveLength(MAX_ACTIVOS)
    expect(carteraDe(new URLSearchParams({ activos: 'aapl, aapl ,ko', pesos: '50,50,50' })))
      .toEqual([fila('AAPL', '50'), fila('KO', '50')])
    // Los que no entraron se dicen (un link armado a mano con 12; B10).
    const doce = new URLSearchParams({ activos: muchos.join(','), pesos: '' })
    expect(sobranDe(doce)).toEqual(['T10', 'T11'])
    expect(notaDeLosQueSobran(sobranDe(doce))).toBe('El link traía 12 activos y entran hasta 10: quedaron afuera T10 y T11.')
    expect(notaDeLosQueSobran([])).toBeNull()
  })

  it('se pide sólo cuando suma 100 y cada uno tiene el suyo', () => {
    expect(consultaDe([fila('AAPL', '60'), fila('GGAL', '40', true)], 2)).toBe('activos=AAPL,GGAL&pesos=60,40&local=GGAL&anios=2')
    expect(consultaDe([fila('AAPL', '100')], 1)).toBe('activos=AAPL&pesos=100&anios=1')
    expect(consultaDe([fila('AAPL', '60')], 2)).toBeNull()
    expect(consultaDe([], 2)).toBeNull()
  })
})

describe('la torta', () => {
  it('de la más grande a la más chica, con la rampa de composición, y lo que falta al final', () => {
    const p = porcionesDeLaTorta([fila('KO', '10'), fila('AAPL', '50'), fila('GGAL', '25'), fila('X', '')])
    expect(p.map(x => [x.key, x.value, x.pct, x.color])).toEqual([
      ['AAPL', 50, 50, porcionColor(0)], ['GGAL', 25, 25, porcionColor(1)], ['KO', 10, 10, porcionColor(2)],
      ['sin_dato', 15, 15, 'rgb(var(--bg-3))'],
    ])
    expect(p.at(-1).label).toBe('Falta repartir')
  })

  it('pasada de 100, la leyenda dice lo escrito y no hay hueco', () => {
    // El dibujo reparte la vuelta entre todos (por `value`); la leyenda, los mismos
    // números que la izquierda: con 80 y 40 decía 66,7 % y 33,3 % (M9).
    const p = porcionesDeLaTorta([fila('A', '80'), fila('B', '40')])
    expect(p.map(x => [x.key, x.value, x.pct])).toEqual([['A', 80, 80], ['B', 40, 40]])
  })
})

describe('mi cartera de hoy', () => {
  it('como filas para editar, y qué quedó afuera', () => {
    const r = { activos: [{ asset: 'AAPL', local: false, peso: 66.7, tipo: 'STOCK' }, { asset: 'GGAL', local: true, peso: 33.3, tipo: 'ACCION' }],
      afuera: [{ asset: 'AL30', tipo: 'BOND', motivo: 'sin_serie' }, { asset: 'FCI:AHORRO', tipo: 'FCI', motivo: 'sin_serie' },
        { asset: 'T11', tipo: 'STOCK', motivo: 'tope' }] }
    expect(filasDeHoy(r)).toEqual([fila('AAPL', '66,7'), fila('GGAL', '33,3', true)])
    // Lo que no TENEMOS (el AL30 cotiza todos los días), y los que no entraron, con nombre.
    expect(notaDeHoy(r)).toBe('Quedaron afuera AL30 y AHORRO: no tenemos sus precios de cada día. Entran hasta 10 '
      + 'activos: quedó afuera T11, el que menos pesa. El resto se repartió sobre 100%.')
    expect(notaDeHoy({ activos: [], afuera: [{ asset: 'AL30', motivo: 'sin_serie' }] }))
      .toBe('Quedó afuera AL30: no tenemos sus precios de cada día. El resto se repartió sobre 100%.')
    expect(notaDeHoy({ activos: [], afuera: [] })).toBeNull()
  })

  it('con el asesor adentro de un cliente, la cartera es la de él', () => {
    expect(origenes('Ana')[0][1]).toBe('Su cartera de hoy')
    expect(origenes()[0][1]).toBe('Mi cartera de hoy')
    expect(notaHoy('Ana')).toMatch(/^Con los activos de Ana y lo que pesa cada uno hoy/)
    expect(notaHoy()).toMatch(/^Con tus activos y lo que pesa cada uno hoy/)
    expect(notaOjito('Ana')).toBe('Con «Ocultar saldos» prendido no traemos la cartera de hoy de Ana: los porcentajes '
      + 'dicen qué tiene. Apagalo, o armala de cero.')
    expect(notaSinActivos('Ana')).toBe('Todavía no tiene activos con precio de todos los días: armala de cero.')
    expect([trayendoHoy('Ana'), errorDeHoy()]).toEqual(['Trayendo la cartera de hoy de Ana…', 'No pudimos traer tu cartera de hoy.'])
  })

  it('la de hoy no va en el link, y cambiada lo dice', () => {
    expect(notaHoy()).toMatch(/El link no la lleva: quien lo abra ve la suya\.$/)
    expect(notaHoy(null, true)).toBe('Partiste de tu cartera de hoy y la cambiaste. Los cambios no quedan en el link: '
      + 'al recargar vuelve la de hoy.')
  })
})

describe('lo que dicen los números', () => {
  it('la cartera de las pruebas, al lado del S&P 500 y del Nasdaq', () => {
    const l = lecturaCartera(CASOS.tres)
    expect(l.titulo).toBe('Le fue mejor que el S&P 500, pero no que el Nasdaq')
    // La plata con un decimal, como el resultado: con US$ 121 y US$ 121 el título
    // decía «le fue mejor» (M1).
    expect(l.frases).toEqual([
      'En los últimos 2 años, US$ 100 en esta cartera habrían quedado en US$ 121,4; en el S&P 500, en US$ 120,8, y en el Nasdaq, en US$ 128,6.',
      'El que más sumó fue AAPL, +17,8 puntos, y el que más restó, GGAL, −6,0: entre todos, la cartera dio +21,4%.',
      'Sin tocarla, GGAL pasó de 30% a 19,7% de la cartera.',
      `La peor caída de la cartera —lo más que llegó a bajar desde su mejor momento— fue de ${CAIDA(CASOS.tres.cartera)}, `
        + `contra ${CAIDA(CASOS.tres.indices[0])} del S&P 500 y ${CAIDA(CASOS.tres.indices[1])} del Nasdaq.`,
    ])
    expect(CAIDA(CASOS.tres.cartera)).toBe('20%')
  })

  it('sin el Nasdaq lo dice, y compara con el que hay', () => {
    const l = lecturaCartera(CASOS.sin_nasdaq)
    expect(l.titulo).toBe('Le fue mejor que el S&P 500')
    expect(l.frases[0]).toMatch(/habrían quedado en US\$ 121,4, y en el S&P 500, en US\$ 120,8\.$/)
    expect(l.frases.at(-1)).toBe('Todavía no tenemos la historia del Nasdaq para compararla.')
  })

  it('si un activo cotiza desde después, dice desde cuándo', () => {
    const l = lecturaCartera(CASOS.recortada)
    expect(l.frases[0]).toMatch(/^Desde el 26\/01\/26, US\$ 100 en esta cartera/)
    expect(l.frases).toContain('Tenemos precios de NUEVA desde el 26/01/26: la simulación arranca ese día.')
    // Las caídas de la frase son las de las tarjetas, también las que redondean a 0
    // («0,3 %», no «0 %»; auditoría de las pruebas, F8).
    const deLaFrase = l.frases.find(f => f.startsWith('La peor caída'))
    for (const x of [CASOS.recortada.cartera, ...CASOS.recortada.indices]) expect(deLaFrase).toContain(CAIDA(x))
  })

  it('si todos restaron, nombra al que MÁS restó', () => {
    const l = lecturaCartera(CASOS.todos_restan)
    const [baja1, baja2] = CASOS.todos_restan.activos
    expect(baja2.aporte).toBeLessThan(baja1.aporte)
    expect(l.frases).toContain(`El que más restó fue BAJA2: ${porcentaje(baja2.aporte).replace('%', '')} de los `
      + `${porcentaje(CASOS.todos_restan.cartera.resultado).replace('%', '')} puntos de la cartera.`)
  })

  it('una cartera que no llegó a bajar no dice «su peor caída fue de 0 %»', () => {
    const l = lecturaCartera({ ...CASOS.tres, cartera: { ...CASOS.tres.cartera, peor_caida: 0 } })
    expect(l.frases).toContain(`La cartera no llegó a bajar desde su mejor momento. En el mismo período, el S&P 500 `
      + `llegó a caer ${CAIDA(CASOS.tres.indices[0])} y el Nasdaq llegó a caer ${CAIDA(CASOS.tres.indices[1])}.`)
  })

  it('los títulos dicen contra qué índice, con los números como se ven', () => {
    const t = (c, s, n) => lecturaCartera({ ...CASOS.tres, cartera: { ...CASOS.tres.cartera, resultado: c },
      indices: [{ ...CASOS.tres.indices[0], resultado: s }, { ...CASOS.tres.indices[1], resultado: n }] }).titulo
    expect(t(30, 20, 25)).toBe('Le fue mejor que el S&P 500 y que el Nasdaq')
    expect(t(10, 20, 25)).toBe('El S&P 500 y el Nasdaq le ganaron')
    expect(t(21.41, 21.38, 25)).toBe('Dio casi lo mismo que el S&P 500, y el Nasdaq le ganó')
    expect(t(30, 30.04, 10)).toBe('Le fue mejor que el Nasdaq y dio casi lo mismo que el S&P 500')
    expect(t(20, 20, 20)).toBe('Dio casi lo mismo que el S&P 500 y el Nasdaq')
    // Con el redondeo de la TARJETA (−10,25 se ve −10,3): antes daba «casi lo mismo»
    // con las tarjetas en −10,3 % y −10,2 % (B5).
    expect(porcentaje(-10.25)).toBe('−10,3%')
    expect(t(-10.25, -10.2, 25)).toBe('El S&P 500 y el Nasdaq le ganaron')
    const solo = lecturaCartera({ ...CASOS.tres, indices: [], faltan: [] })
    expect(solo.titulo).toBe('Así habría ido esta cartera')
    expect(lecturaCartera(CASOS.vieja)).toBeNull()
  })
})

describe('por qué no se pudo simular', () => {
  it('cada motivo, en una oración entera', () => {
    // Sobre lo que tenemos: PARADA cotiza; la que está vieja es nuestra copia (M10).
    expect(motivoCartera(CASOS.vieja)).toBe('No tenemos precios de PARADA desde el 30/09/26: sacalo para simular el resto.')
    expect(motivoCartera({ motivo: 'sin_serie', faltan: [{ asset: 'AL30' }, { asset: 'ZZZ' }] }))
      .toBe('No tenemos los precios de cada día de AL30 y ZZZ: sacalos o cambialos por otros.')
    expect(motivoCartera({ motivo: 'poca_historia', recorte_por: 'NUEVITO', faltan: [] }))
      .toBe('Tenemos muy pocos días de precios de NUEVITO: no alcanzan para simular. Sacalo para probar el resto.')
    // Con uno solo no hay «resto» (B2); sin recorte no hay a quién culpar (H10).
    expect(motivoCartera({ motivo: 'poca_historia', recorte_por: 'NUEVITO', faltan: [] }, 1))
      .toBe('Tenemos muy pocos días de precios de NUEVITO: no alcanzan para simular. Cambialo por otro con más historia.')
    expect(motivoCartera({ motivo: 'poca_historia', recorte_por: null, faltan: [] }, 3))
      .toBe('Con estos activos tenemos muy pocos días de precios: no alcanzan para simular.')
    expect(motivoCartera({ motivo: 'demo' })).toBe('En el modo demo no hay precios de todos los días para simular carteras.')
    expect(motivoCartera({ motivo: 'tope' })).toMatch(/probá de nuevo en un rato/)
  })
})

describe('en el modo demo', () => {
  it('la cartera de hoy se arma sin el bono, y simular dice que no hay precios', async () => {
    const { handleDemoRequest } = await import('./demo')
    const hoy = handleDemoRequest('GET', '/backtest/cartera/hoy')
    expect(hoy.activos.reduce((s, a) => s + a.peso, 0)).toBe(100)
    expect(hoy.activos.length).toBeLessThanOrEqual(MAX_ACTIVOS)
    expect(hoy.afuera).toEqual([{ asset: 'AL30', tipo: 'BOND', motivo: 'sin_serie' }])
    const r = handleDemoRequest('GET', '/backtest/cartera?activos=NVDA&pesos=100&anios=2')
    expect(r).toEqual({ disponible: false, motivo: 'demo' })
    expect(motivoCartera(r)).toBe('En el modo demo no hay precios de todos los días para simular carteras.')
  })
})

describe('nunca promete', () => {
  it('ni «suele», ni «conviene», ni «la mejor cartera», ni consejos', () => {
    const textos = [
      ...Object.values(CASOS).flatMap(r => { const l = lecturaCartera(r); return l ? [l.titulo, ...l.frases] : [motivoCartera(r)] }),
      QUE_SE_SIMULA, notaHoy(), notaHoy('Ana', true), notaOjito(), notaSinActivos('Ana'), NOTA_CADA_ACTIVO,
      COMO_SE_SIMULA_CARTERA, ...['sin_serie', 'vieja', 'poca_historia', 'tope', 'bajando', 'demo', 'otro']
        .map(m => motivoCartera({ motivo: m, faltan: [{ asset: 'X', hasta: '2026-01-02' }] }, 1)),
    ].join(' ')
    expect(textos).not.toMatch(/suele|se viene|comprá|vendé|va a subir|va a bajar|conviene|deber[íi]as|mejor cartera|la mejor\b|te recomend|ayuda|muchas veces|garantiz/i)
  })
})

// La caída como la escribe la TARJETA (`porcentaje(x, 0)`, sin el signo), no con
// una cuenta propia: con `Math.round` daba «0 %» donde la tarjeta dice «−0,3 %», y
// la prueba no lo veía (auditoría de las pruebas 05/11, F8).
function CAIDA(x) {
  return porcentaje(x.peor_caida, 0).replace(/^[−+-]/, '')
}
