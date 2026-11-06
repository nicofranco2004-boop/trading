// Las palabras y las cuentas chicas de «Una cartera» (utils/carteraSimulada.js).
// Lo que importa:
//   · el máximo de activos y la tolerancia del 100 son los del servidor
//     (backend/cartera_simulada.py): uno distinto daría un 400;
//   · lo que se dice sale de la respuesta REAL del servidor
//     (backend/tests/fixtures/cartera_simulada.json, que test_cartera_simulada.py
//     compara contra cartera_simulada.simular), no de un caso armado a mano;
//   · cada porcentaje acepta coma, hasta 100; cuánto falta o sobra se dice;
//   · la barra del 100 % va en el orden de la tabla, con lo que falta al final, y
//     dice lo escrito aunque pase de 100;
//   · cada número de una frase es el que se ve (el formateador de la pantalla, no
//     una cuenta de la prueba);
//   · habla de lo que tenemos («no tenemos los precios de AL30»), y con el asesor
//     adentro de un cliente, de la cartera de él;
//   · nunca promete ni dice cuál cartera es «mejor».
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import {
  COMO_SE_SIMULA_CARTERA, MAX_ACTIVOS, NOTA_CADA_ACTIVO, QUE_SE_SIMULA, TOLERANCIA,
  aLaDireccion, aclaracionDeLaCartera, carteraDe, consultaDe, errorDeHoy, estadoDeLaCartera, filasDeHoy, lecturaCartera,
  limpiar, loQueFalta, motivoCartera, notaDeHoy, notaDeLosQueSobran, notaDelResumen, notaHoy, notaOjito, notaSinActivos,
  numeroDe, origenDe, origenes, repartirIgual, rotuloDelAnterior, sobranDe, textoDe, totalDe, tramosDeLaBarra,
  trayendoHoy,
} from './carteraSimulada'
import { modoDe, porcentaje } from './backtesting'

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

  it('mientras se escribe: dígitos y una coma, hasta 2 decimales; más de 100 no se acepta', () => {
    expect(['30', '33,3', '33.3', '33,333', '3,3,3', 'a5', ',5', '007', '100', '100,0'].map(limpiar))
      .toEqual(['30', '33,3', '33,3', '33,33', '3,33', '5', '0,5', '7', '100', '100,0'])
    // Más de 100: null, y la pantalla deja lo que estaba. Antes se volvía 100: con «10»
    // y el cursor al final, un «5» dejaba 100 sin avisar (auditoría de pantalla 06/11).
    expect(['150', '105', '100,5', '1000'].map(limpiar)).toEqual([null, null, null, null])
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

describe('la barra del 100 %', () => {
  it('en el orden de la tabla (no de mayor a menor), sin los que no tienen porcentaje, y lo que falta al final', () => {
    // Era una torta de mayor a menor: la leyenda iba en otro orden que la tabla y los
    // colores cambiaban de activo mientras escribías (diseño 05/11, M3).
    const b = tramosDeLaBarra([fila('KO', '10'), fila('AAPL', '50'), fila('GGAL', '25'), fila('X', '')])
    expect(b).toEqual({ tramos: [{ asset: 'KO', peso: 10 }, { asset: 'AAPL', peso: 50 }, { asset: 'GGAL', peso: 25 }],
      falta: 15, ambar: false })
    expect(tramosDeLaBarra([fila('A', '33,33'), fila('B', '33,33'), fila('C', '33,33')]).falta).toBe(0)   // V6
    expect(tramosDeLaBarra([]).tramos).toEqual([])
  })

  it('pasada de 100, cada tramo dice lo escrito y la barra lo marca', () => {
    // Con 80 y 40 la torta decía 66,7 % y 33,3 %: números que nadie escribió (M9).
    expect(tramosDeLaBarra([fila('A', '80'), fila('B', '40')]))
      .toEqual({ tramos: [{ asset: 'A', peso: 80 }, { asset: 'B', peso: 40 }], falta: 0, ambar: true })
  })

  it('llena pero con un activo sin porcentaje también la marca: no está lista', () => {
    // Con 50 / 50 / 0 se veía violeta y completa, y abajo decía «Falta un porcentaje»
    // (auditoría de pantalla 06/11, B3).
    expect(tramosDeLaBarra([fila('A', '50'), fila('B', '50'), fila('C', '')]))
      .toEqual({ tramos: [{ asset: 'A', peso: 50 }, { asset: 'B', peso: 50 }], falta: 0, ambar: true })
    expect(tramosDeLaBarra([fila('A', '50'), fila('B', '50')]).ambar).toBe(false)
  })

  it('el resultado anterior dice que es el anterior, en un renglón y sin el número que cambia', () => {
    // B4 y H6: tenue al lado de los porcentajes nuevos, se leía como el de lo escrito.
    expect(rotuloDelAnterior(estadoDeLaCartera([fila('A', '50'), fila('B', '40')])))
      .toBe('Es el resultado anterior: no suman 100%')
    expect(rotuloDelAnterior(estadoDeLaCartera([fila('A', '80'), fila('B', '40')])))
      .toBe('Es el resultado anterior: no suman 100%')
    expect(rotuloDelAnterior(estadoDeLaCartera([fila('A', '50'), fila('B', '50'), fila('C', '')])))
      .toBe('Es el resultado anterior: falta un porcentaje')
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

  it('dice qué parte de tu plata se simula (un porcentaje, nunca plata)', () => {
    // Mitad fondo y mitad CEDEARs se veía como «tu cartera», toda en CEDEARs (producto 05/11, A4).
    expect(notaDeHoy({ activos: [], afuera: [], parte: 62 })).toBe('Lo que se simula es el 62% de tu plata: lo demás '
      + '(efectivo, plazos fijos, bonos o fondos) no lo podemos simular.')
    expect(notaDeHoy({ activos: [], afuera: [], parte: 62 }, 'Ana')).toMatch(/^Lo que se simula es el 62% de su plata/)
    expect(notaDeHoy({ activos: [], afuera: [], parte: 100 })).toBeNull()
  })

  it('con el asesor adentro de un cliente, la cartera es la de él', () => {
    expect(origenes('Ana')[0][1]).toBe('Su cartera de hoy')
    expect(origenes()[0][1]).toBe('Mi cartera de hoy')
    expect(notaHoy('Ana')).toMatch(/^Con los activos de Ana y lo que pesa cada uno hoy/)
    expect(notaHoy()).toMatch(/^Con tus activos y lo que pesa cada uno hoy/)
    expect(notaOjito('Ana')).toBe('Con «Ocultar saldos» prendido no traemos la cartera de hoy de Ana: los porcentajes '
      + 'dicen qué tiene. Apagalo con el ojito del Inicio o de Tu Cartera, o armala de cero.')
    expect(notaSinActivos('Ana')).toBe('Todavía no tiene acciones, CEDEARs ni cripto para simular: armala de cero.')
    expect([trayendoHoy('Ana'), errorDeHoy()]).toEqual(['Trayendo la cartera de hoy de Ana…', 'No pudimos traer tu cartera de hoy.'])
    expect(aclaracionDeLaCartera('hoy', 'Ana')).toMatch(/^Es la cartera de hoy de Ana puesta en el pasado: .+ No es lo que ganó/)
  })

  it('lo que queda afuera es lo que no TENEMOS, y cambiada dice que no queda en el link', () => {
    // «(no tienen precio de todos los días)» hablaba del bono, que cotiza todos los días (V4, M8).
    expect(notaHoy()).toBe('Con tus activos y lo que pesa cada uno hoy. Quedan afuera los bonos y los fondos, porque no '
      + 'tenemos sus precios de cada día, y el efectivo. Cambiá lo que quieras.')
    expect(notaHoy(null, true)).toBe('Partiste de tu cartera de hoy y la cambiaste. Los cambios no quedan en el link: '
      + 'al recargar vuelve la de hoy.')
  })
})

describe('lo que dicen los números', () => {
  it('la cartera de las pruebas, al lado del S&P 500 y del Nasdaq, en condicional', () => {
    const l = lecturaCartera(CASOS.tres, { origen: 'hoy' })
    // En condicional: es lo que habría pasado, no tu resultado (producto y método 05/11).
    // +21,4 % contra +20,8 %: menos de un punto es «casi lo mismo» (método C9).
    expect(l.titulo).toBe('Habría dado casi lo mismo que el S&P 500, y el Nasdaq le habría ganado')
    // Con «Mi cartera de hoy», que es tu cartera de hoy puesta en el pasado y no lo que ganaste.
    // Y para qué lado se equivoca: da de más (método 06/11, H2; Nico, 06/11: «Sí, agregala»).
    expect(l.aclaracion).toBe('Es tu cartera de hoy puesta en el pasado: con los pesos de hoy desde el primer día, con '
      + 'lo que compraste después y sin lo que vendiste. Por cómo se arma, da de más: lo que hoy pesa más, en buena '
      + 'parte pesa más porque subió. No es lo que ganaste: eso está en Métricas.')
    // Los aportes en dólares de cada US$ 100 (diseño M7) van con «Cada activo»; los «habrían
    // quedado en» no se repiten: están en el gráfico (diseño M10). La peor caída de la
    // cartera y la de los índices se ven juntas en la tabla de la respuesta: no van
    // también en una frase.
    expect(l.deLosActivos).toEqual([
      'De cada US$ 100, AAPL habría sumado US$ 17,8 y GGAL habría restado US$ 6,0: entre todos, la cartera habría dado +21,4%.',
      'Sin tocarla, GGAL habría pasado de 30% a 19,7% de la cartera.',
    ])
    expect(l.avisos).toEqual([])
    expect([l.titulo, l.aclaracion, ...l.deLosActivos].join(' ')).not.toMatch(/peor caída/i)
    // Debajo de la tabla: de cuándo a cuándo, y los índices sin dividendos como la cartera.
    expect(notaDelResumen(CASOS.tres)).toBe('Del 31/10/24 al 30/10/26, en dólares. Los índices, sin dividendos, como la cartera.')
    // Sin ningún índice, lo de la cartera sola (método 06/11, H7).
    expect(notaDelResumen({ ...CASOS.tres, indices: [] })).toBe('Del 31/10/24 al 30/10/26, en dólares y sin dividendos.')
    // Armada de cero: el diario del lunes.
    expect(lecturaCartera(CASOS.tres, { origen: 'cero' }).aclaracion)
      .toBe('Elegir los porcentajes mirando este resultado es elegir con el diario del lunes.')
  })

  it('sin el Nasdaq lo dice, y compara con el que hay', () => {
    const l = lecturaCartera(CASOS.sin_nasdaq)
    expect(l.titulo).toBe('Habría dado casi lo mismo que el S&P 500')
    expect(l.avisos).toEqual(['Todavía no tenemos la historia del Nasdaq para compararla.'])
  })

  it('si un activo cotiza desde después, dice desde cuándo', () => {
    const l = lecturaCartera(CASOS.recortada)
    expect(l.avisos).toEqual(['Tenemos precios de NUEVA desde el 26/01/26: la simulación arranca ese día.'])
  })

  it('si todos restaron, nombra al que MÁS restó', () => {
    const l = lecturaCartera(CASOS.todos_restan)
    const [baja1, baja2] = CASOS.todos_restan.activos
    expect(baja2.aporte).toBeLessThan(baja1.aporte)
    expect(l.deLosActivos).toContain(`De cada US$ 100, el que más habría restado es BAJA2: ${dolares(baja2.aporte)} de los `
      + `${dolares(CASOS.todos_restan.cartera.resultado)} que habría perdido la cartera.`)
  })

  it('la nota de «Cada activo» dice la regla que cumplen los números del servidor', () => {
    // Gana peso el que rinde más que el conjunto, aunque baje; lo pierde el que rinde
    // menos, aunque suba. «El que sube pesa cada vez más» y «el que baja lo pierde» los
    // contradecía la tabla (auditoría A4 y verificación V1, 05/11). Contra TODOS los
    // casos que contesta el servidor, no contra uno armado a mano.
    let gananBajando = 0
    for (const r of Object.values(CASOS).filter(x => x.disponible)) {
      for (const a of r.activos) {
        if (Math.abs(a.resultado - r.cartera.resultado) < 1e-9) continue
        expect(a.peso_final > a.peso, `${a.asset}`).toBe(a.resultado > r.cartera.resultado)
        if (a.resultado < 0 && a.peso_final > a.peso) gananBajando += 1
      }
    }
    expect(gananBajando, 'el caso que la nota vieja contradecía está en los datos').toBeGreaterThan(0)
    expect(NOTA_CADA_ACTIVO).toMatch(/gana peso el que rinde más que el conjunto, aunque baje, y lo pierde el que rinde menos, aunque suba/)
  })

  it('los títulos dicen contra qué índice, con los números como se ven, y menos de un punto es casi lo mismo', () => {
    const t = (c, s, n) => lecturaCartera({ ...CASOS.tres, cartera: { ...CASOS.tres.cartera, resultado: c },
      indices: [{ ...CASOS.tres.indices[0], resultado: s }, { ...CASOS.tres.indices[1], resultado: n }] }).titulo
    expect(t(30, 20, 25)).toBe('Le habría ido mejor que el S&P 500 y que el Nasdaq')
    expect(t(10, 20, 25)).toBe('El S&P 500 y el Nasdaq le habrían ganado')
    expect(t(21.41, 21.38, 25)).toBe('Habría dado casi lo mismo que el S&P 500, y el Nasdaq le habría ganado')
    expect(t(30, 30.04, 10)).toBe('Le habría ido mejor que el Nasdaq y habría dado casi lo mismo que el S&P 500')
    expect(t(20, 20, 20)).toBe('Habría dado casi lo mismo que el S&P 500 y el Nasdaq')
    // Un ETF del S&P 500 contra el S&P 500: 0,2 puntos de diferencia no es «le ganó» (método C9).
    expect(t(33.2, 33.0, 39.6)).toBe('Habría dado casi lo mismo que el S&P 500, y el Nasdaq le habría ganado')
    // Con el redondeo de la TARJETA (−10,25 se ve −10,3), y a un punto o más, ya no es «casi».
    expect(porcentaje(-10.25)).toBe('−10,3%')
    expect(t(-10.25, -9.2, 25)).toBe('El S&P 500 y el Nasdaq le habrían ganado')
    const solo = lecturaCartera({ ...CASOS.tres, indices: [], faltan: [] })
    expect(solo.titulo).toBe('Así habría ido esta cartera')
    expect(lecturaCartera(CASOS.vieja)).toBeNull()
  })
})

describe('por qué no se pudo simular', () => {
  it('cada motivo, en una oración entera', () => {
    // Sobre lo que tenemos: PARADA cotiza; la que está vieja es nuestra copia (M10).
    expect(motivoCartera(CASOS.vieja)).toBe('No tenemos precios de PARADA desde el 30/09/26: sacalo para simular el resto.')
    // Vieja contra hoy (H9): un activo solo, o todos, ya no tienen «resto» que simular,
    // y cambiarlo no sirve si la falla es nuestra (H4, 06/11).
    const parado = (asset, hasta = '2026-09-04') => ({ asset, motivo: 'vieja', hasta })
    expect(motivoCartera({ motivo: 'vieja', faltan: [parado('MU')] }, 1))
      .toBe('No tenemos precios de MU desde el 04/09/26: para simular hacen falta los de la última semana.')
    expect(motivoCartera({ motivo: 'vieja', faltan: [parado('MU'), parado('AAPL')] }, 2))
      .toBe('No tenemos precios de MU y AAPL desde el 04/09/26: para simular hacen falta los de la última semana.')
    // Cada uno con su fecha (H5, 06/11): la noche caída y uno que ya estaba parado.
    expect(motivoCartera({ motivo: 'vieja', faltan: [parado('AAPL', '2026-10-05'), parado('MU', '2026-08-14')] }, 2))
      .toBe('No tenemos precios de MU desde el 14/08/26 ni de AAPL desde el 05/10/26: '
        + 'para simular hacen falta los de la última semana.')
    expect(motivoCartera({ motivo: 'vieja', faltan: [parado('MU', '2026-08-14'), parado('NOK', '2026-08-14')] }, 3))
      .toBe('No tenemos precios de MU y NOK desde el 14/08/26: sacalos para simular el resto.')
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
      ...Object.values(CASOS).flatMap(r => {
        const l = lecturaCartera(r)
        return l ? [l.titulo, l.aclaracion, ...l.avisos, ...l.deLosActivos, notaDelResumen(r)] : [motivoCartera(r)]
      }),
      QUE_SE_SIMULA, notaHoy(), notaHoy('Ana', true), notaOjito(), notaSinActivos('Ana'), NOTA_CADA_ACTIVO,
      COMO_SE_SIMULA_CARTERA, ...['sin_serie', 'vieja', 'poca_historia', 'tope', 'bajando', 'demo', 'otro']
        .map(m => motivoCartera({ motivo: m, faltan: [{ asset: 'X', hasta: '2026-01-02' }] }, 1)),
    ].join(' ')
    expect(textos).not.toMatch(/suele|se viene|comprá|vendé|va a subir|va a bajar|conviene|deber[íi]as|mejor cartera|la mejor\b|te recomend|ayuda|muchas veces|garantiz/i)
  })
})

// Dólares de cada US$ 100 como los escribe la frase (sin signo, un decimal).
function dolares(x) {
  return `US$ ${Math.abs(x).toLocaleString('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`
}
