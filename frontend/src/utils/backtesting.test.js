// Las palabras de la pestaña «Backtesting» (utils/backtesting.js).
// Lo que importa:
//   · las reglas, los períodos y el máximo para comparar son los del servidor
//     (backend/backtest.py): uno que no existe allá daría un 400;
//   · lo que se dice sale de la respuesta REAL del servidor para GGAL
//     (backend/tests/fixtures/backtest_ggal.json, que test_backtest.py compara
//     contra backtest.probar): no de un caso armado a mano. Los casos que GGAL
//     no tiene se arman cambiando lo justo de una respuesta real, con la forma
//     que el servidor manda;
//   · dice lo que pasó, en pasado y sobre ESTA prueba, al lado de comprar y
//     mantener: lo que se movió el precio (sin comisiones), cuántos días estuvo
//     afuera sin redondeos que se contradigan, la compra sin la que habría
//     terminado en pérdida, y que con pocas compras no se separa la regla de la
//     suerte;
//   · dice que prueba una forma de usar el indicador, no el indicador, y lo que
//     una regla que perdió contra mantener consiguió a cambio: caer menos (Nico,
//     05/11);
//     comparando, cuántas le ganaron (una que no compró no le ganó a nadie),
//     nunca cuál es «la mejor»;
//   · los avisos de «no se pudo probar» son oraciones enteras con el activo
//     adentro, también en el modo demo;
//   · nunca promete.
//   Los casos de la auditoría del 04/11 (A2, A3, M1–M4, M8, B1, B2, B5, B9)
//   llevan su nombre.
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import {
  DE_ENTRADA, MAX_REGLAS, PERIODOS, PERIODOS_CARTERA, POCAS_COMPRAS, REGLAS, aniosDe, colorDe, comoSeSimula, compraClave,
  contraMantener, ganaron, lectura, motivoEnPalabras, otraRegla, parteAfuera, periodoEnPalabras, porcentaje,
  precio, queSePrueba, reglaDe, reglasDe, sinEstaCompra, textoDelRecorte, tramosComprada,
} from './backtesting'
import { handleDemoRequest } from './demo'

const AQUI = dirname(fileURLToPath(import.meta.url))
const GGAL = JSON.parse(readFileSync(resolve(AQUI, '../../../backend/tests/fixtures/backtest_ggal.json'), 'utf8'))
const PY = readFileSync(resolve(AQUI, '../../../backend/backtest.py'), 'utf8')
const RSI = GGAL.rsi

// Un resultado real con lo justo cambiado, para los casos que GGAL no tiene.
const con = (cambios = {}, regla = {}, mantener = {}) => ({
  ...RSI, ...cambios,
  resultados: [{ ...RSI.resultados[0], ...regla }],
  mantener: { ...RSI.mantener, ...mantener },
})
// Una regla que no compró nunca, con la forma que manda el servidor.
const sinCompras = (x) => ({ ...x, compras: 0, ganadoras: 0, ruedas_comprada: 0, resultado: 0, peor_caida: 0,
  final: 100, sin_la_mejor: null, operaciones: [] })

describe('lo que se ofrece es lo del servidor', () => {
  it('las mismas reglas, en el mismo orden, y el mismo máximo para comparar', () => {
    const delServidor = [...PY.match(/^REGLAS = \(([^)]*)\)/m)[1].matchAll(/"([a-z0-9_]+)"/g)].map(m => m[1])
    expect(REGLAS.map(r => r.id)).toEqual(delServidor)
    expect(MAX_REGLAS).toBe(Number(PY.match(/^MAX_REGLAS = (\d+)/m)[1]))
  })

  it('los mismos períodos, y el de entrada es uno de ellos', () => {
    const delServidor = PY.match(/^ANIOS = \(([^)]*)\)/m)[1].split(',').map(Number)
    expect(PERIODOS.map(([a]) => a)).toEqual(delServidor)
    expect(delServidor).toContain(DE_ENTRADA.anios)
    expect(REGLAS[0].id).toBe(DE_ENTRADA.regla)
  })

  it('«Una cartera» llega a todo lo que se guarda: 5 años', () => {
    // backend/cartera_simulada.py: ANIOS va de 1 a velas_diarias.ANIOS_GUARDADOS.
    const CS = readFileSync(resolve(AQUI, '../../../backend/cartera_simulada.py'), 'utf8')
    const VD = readFileSync(resolve(AQUI, '../../../backend/velas_diarias.py'), 'utf8')
    expect(CS).toMatch(/^ANIOS = tuple\(range\(1, velas_diarias\.ANIOS_GUARDADOS \+ 1\)\)$/m)
    const guardados = Number(VD.match(/^ANIOS_GUARDADOS = (\d+)/m)[1])
    expect(PERIODOS_CARTERA.map(([a]) => a)).toEqual(Array.from({ length: guardados }, (_, i) => i + 1))
    expect(PERIODOS_CARTERA.at(-1)).toEqual([5, '5 años'])
  })

  it('lo que viene en la dirección y no se ofrece abre lo de entrada; uno más largo, el más largo', () => {
    expect(aniosDe('3')).toBe(3)
    // Los dos modos comparten ?anios=: 5 años de «Una cartera» en «Una regla» son 4.
    expect(aniosDe('5')).toBe(4)
    expect(aniosDe('5', PERIODOS_CARTERA)).toBe(5)
    expect(aniosDe('9', PERIODOS_CARTERA)).toBe(5)
    for (const raro of [null, '', '0', '-3', '2.5', 'dos']) expect(aniosDe(raro), String(raro)).toBe(DE_ENTRADA.anios)
    expect(reglaDe('rsi').nombre).toBe('RSI 30 / 70')
    expect(reglaDe('otra').id).toBe(DE_ENTRADA.regla)
  })

  it('las reglas de la dirección: las que se ofrecen, sin repetir, hasta 3, en su orden', () => {
    expect(reglasDe('rsi,adx_squeeze')).toEqual(['rsi', 'adx_squeeze'])
    expect(reglasDe('rsi,otra,rsi,media50')).toEqual(['rsi', 'media50'])
    expect(reglasDe('media200,media50,rsi,adx_squeeze')).toEqual(['media200', 'media50', 'rsi'])
    expect(reglasDe('')).toEqual([DE_ENTRADA.regla])
    expect(reglasDe(null)).toEqual([DE_ENTRADA.regla])
  })

  it('«comparar con otra» suma la primera que no está', () => {
    expect(otraRegla(['media200'])).toBe('media50')
    expect(otraRegla(['media50', 'media200'])).toBe('rsi')
    expect(otraRegla(REGLAS.map(r => r.id))).toBeNull()
  })

  it('cada regla dice cuándo compra y cuándo vende', () => {
    for (const r of REGLAS) {
      expect(r.explica, r.id).toMatch(/^Compra cuando .+\. Vende cuando .+\.$/)
      expect(r.necesita, r.id).toMatch(/necesita/)
      expect(r.corto.length, r.id).toBeLessThanOrEqual(r.nombre.length)
    }
  })
})

describe('una regla: lo que dicen los números', () => {
  it('RSI en GGAL: le fue mejor, cayó mucho (menos que mantener), sin una compra habría perdido y fueron muy pocas', () => {
    expect(lectura(RSI)).toEqual({
      titulo: 'Le habría ido mejor que comprar y mantener',
      frases: [
        'GGAL bajó 35% en los últimos 2 años y la regla estuvo afuera el 55% de los días.',
        // 59 % contra 63 %: no es bastante más chica, no se pone al lado (05/11, M2).
        'En el camino llegó a caer 59% desde su mejor momento.',
        'Sin la compra del 05/05/26 (+32,6%), la regla habría terminado en pérdida: −7,6%.',
        'Fueron 3 compras en los últimos 2 años: con tan pocas, no alcanza para saber si el resultado es de la regla o de la suerte.',
      ],
    })
  })

  // Nico, 05/11, mirando AAPL con ADX + Squeeze: «me da miedo que digan "lo que me
  // muestra Rendi no me sirve de nada"». La regla perdió contra mantener porque
  // estuvo afuera casi todo el tiempo; a cambio, cayó mucho menos. Los números
  // son los que dio la prueba en la vista previa.
  it('AAPL: mantener le ganó; se dice que se perdió la suba y lo que consiguió a cambio', () => {
    const aapl = con({ asset: 'AAPL', variacion_precio: 58.2 },
      { resultado: 4.9, peor_caida: -14.2, compras: 5, ganadoras: 3, ruedas_comprada: 67,
        sin_la_mejor: { compra: '2026-07-01', resultado: 8.6, sin_ella: -3.4 } },
      { resultado: 56.0, peor_caida: -33.1 })
    expect(lectura(aapl)).toEqual({
      titulo: 'Comprar y mantener le habría ganado',
      frases: [
        'AAPL subió 58% en los últimos 2 años y la regla estuvo afuera el 87% de los días: se perdió la mayor parte de la suba.',
        'A cambio, su peor caída fue de 14%, contra 33% de comprar y mantener.',
        'Sin la compra del 01/07/26 (+8,6%), la regla habría terminado en pérdida: −3,4%.',
        'Fueron 5 compras en los últimos 2 años: con tan pocas, no alcanza para saber si el resultado es de la regla o de la suerte.',
      ],
    })
  })

  it('«se perdió… la suba» sólo si subió, mantener le ganó y estuvo afuera la mitad o más', () => {
    const primera = (precio, regla, mantener = 60, comprada = 67) => lectura(con({ variacion_precio: precio },
      { resultado: regla, ruedas_comprada: comprada, compras: 12, sin_la_mejor: null }, { resultado: mantener })).frases[0]
    expect(primera(64, -18.5)).toMatch(/de los días: se perdió toda la suba\.$/)
    expect(primera(64, 20)).toMatch(/de los días: se perdió la mayor parte de la suba\.$/)
    expect(primera(64, 40)).toMatch(/de los días: se perdió parte de la suba\.$/)
    expect(primera(64, 20, 60, 300), 'adentro el 60 % de los días').toMatch(/de los días\.$/)
    expect(primera(-30, -40, -35), 'el precio bajó').toMatch(/de los días\.$/)
    expect(primera(64, 70), 'le ganó a mantener').toMatch(/de los días\.$/)
    // Con los números como se ven: «subió 3 %» y la tarjeta en +1,5 % es la mitad
    // justa, no «la mayor parte»; y si comprar y mantener también la perdió (las
    // comisiones), no es por haber estado afuera (auditoría de regresiones 05/11, B1).
    expect(primera(3.1, 1.5, 2.9, 200)).toMatch(/de los días: se perdió parte de la suba\.$/)
    expect(primera(1.0, -0.5, -0.1, 110), 'mantener tampoco se quedó con la suba').toMatch(/de los días\.$/)
  })

  it('la peor caída al lado de la de mantener, sólo si fue más chica, como se ve en las tarjetas', () => {
    const caida = (regla, mantener, dd, ddm) => lectura(con({ variacion_precio: -40 },
      { resultado: regla, peor_caida: dd, compras: 12, sin_la_mejor: null }, { resultado: mantener, peor_caida: ddm }))
      .frases.filter(f => /caída|caer/.test(f))
    expect(caida(-2.1, -41, -22, -63)).toEqual(['Su peor caída fue de 22%, contra 63% de comprar y mantener.'])
    expect(caida(-15, -34.8, -30, -63)).toEqual(['En el camino llegó a caer 30% desde su mejor momento; comprar y mantener, 63%.'])
    // «Bastante» más chica: 13 % contra 14 % es ruido al lado de una regla que dejó
    // 29 puntos; no se subraya (auditoría de regresiones 05/11, M2).
    const ruido = lectura(con({ variacion_precio: 30 },
      { resultado: -0.2, peor_caida: -13, compras: 12, sin_la_mejor: null }, { resultado: 28.8, peor_caida: -14 }))
    expect(ruido.frases.filter(f => /caída|caer/.test(f))).toEqual([])
    expect(caida(-2.1, -41, -58, -63), 'cinco puntos no alcanzan si es casi toda la otra')
      .toEqual(['En el camino llegó a caer 58% desde su mejor momento.'])
    expect(caida(-15, -34.8, -70, -63)).toEqual(['En el camino llegó a caer 70% desde su mejor momento.'])
    expect(caida(-50, -41, -70, -63), 'cayó más que mantener').toEqual([])
    expect(caida(-41.04, -41, -22, -63), 'empate').toEqual(['Su peor caída fue de 22%, contra 63% de comprar y mantener.'])
    expect(caida(-50, -41, -0.4, -63), 'casi no cayó: no se dice «0 %»').toEqual([])
    // Lo que se ve: −13,5 % se muestra «−14%» en la tarjeta, y así se dice.
    expect(porcentaje(-13.5, 0)).toBe('−14%')
    expect(caida(-2.1, -41, -13.5, -63)).toEqual(['Su peor caída fue de 14%, contra 63% de comprar y mantener.'])
  })

  it('arriba: prueba una forma de usar el indicador, no el indicador', () => {
    expect(queSePrueba(false)).toBe('Esto prueba una forma de usar el indicador: comprar todo cuando da la señal y '
      + 'vender todo cuando se da vuelta. El indicador es el mismo de la ficha.')
    expect(queSePrueba(true)).toMatch(/^Esto prueba una forma de usar cada indicador: .+ Los indicadores son los mismos de la ficha\.$/)
  })

  it('«bajó X %» es lo que se movió el precio, sin comisiones (H2), y nunca «subió 0 %» (B1)', () => {
    // El precio bajó 35,3 %; comprar y mantener, con sus dos comisiones, −35,9 %.
    expect(RSI.variacion_precio).toBeGreaterThan(RSI.mantener.resultado)
    expect(lectura(RSI).frases[0]).toMatch(/^GGAL bajó 35% /)
    expect(lectura(con({ variacion_precio: 0.26 })).frases[0]).toMatch(/^GGAL terminó casi igual en los últimos 2 años y /)
    expect(lectura(con({ variacion_precio: -0.4 })).frases[0]).toMatch(/^GGAL terminó casi igual /)
    expect(lectura(con({ variacion_precio: 0.6 })).frases[0]).toMatch(/^GGAL subió 1% /)
  })

  it('media de 200 en GGAL: perdió menos, desde el día en que la media existe', () => {
    const l = lectura(GGAL.media200)
    expect(l.titulo).toBe('Habría perdido menos que comprar y mantener')
    expect(l.frases[0]).toBe('GGAL bajó 41% desde el 17/04/25 y la regla estuvo afuera el 66% de los días.')
    expect(l.frases.join(' ')).not.toMatch(/sin la compra/i)
    expect(GGAL.media200.resultados[0].compras).toBeGreaterThanOrEqual(POCAS_COMPRAS)
    expect(l.frases.join(' ')).not.toMatch(/con tan pocas/)
  })

  it('el ADX + Squeeze en GGAL: sin su mejor compra habría terminado en pérdida', () => {
    expect(compraClave(GGAL.adx_squeeze.resultados[0])).toBe('2026-03-03')
    expect(lectura(GGAL.adx_squeeze).frases).toContain(
      'Sin la compra del 03/03/26 (+13,3%), la regla habría terminado en pérdida: −1,9%.')
  })

  it('comprar y mantener le ganó (y la regla cayó más: no hay «a cambio»)', () => {
    const l = lectura(con({ asset: 'KO', anios: 1, variacion_precio: 20 },
      { resultado: 4, peor_caida: -12, compras: 12, sin_la_mejor: null }, { resultado: 19.6, peor_caida: -9 }))
    expect(l.titulo).toBe('Comprar y mantener le habría ganado')
    expect(l.frases).toEqual(['KO subió 20% en el último año y la regla estuvo afuera el 55% de los días: '
      + 'se perdió la mayor parte de la suba.'])
  })

  it('A3: ninguna regla general en presente («estar afuera ayuda»)', () => {
    for (const r of Object.values(GGAL)) {
      expect(lectura(r).frases.join(' '), r.reglas.join(',')).not.toMatch(/ayuda|cuando el precio/i)
    }
  })

  it('una regla que no compró nunca', () => {
    expect(lectura(con({ anios: 1 }, sinCompras(RSI.resultados[0]), { resultado: 20 })))
      .toEqual({
        titulo: 'No dio ninguna señal',
        frases: ['En el último año, la regla no marcó ninguna compra: la plata habría quedado quieta. '
          + 'Comprar y mantener dio +20,0%.'],
      })
  })

  it('una sola compra se dice en singular', () => {
    const l = lectura(con({}, { compras: 1, ganadoras: 1, sin_la_mejor: null }))
    expect(l.frases.at(-1)).toMatch(/^Fue una sola compra en los últimos 2 años: /)
  })

  it('M2: «le ganó» se decide con los números tal como se ven, en un solo lugar', () => {
    expect(contraMantener({ compras: 3, resultado: -1.41 }, { resultado: -1.38 })).toBe('empate')
    expect(lectura(con({}, { resultado: -1.41 }, { resultado: -1.38 })).titulo).toBe('Habría dado casi lo mismo que comprar y mantener')
    expect(lectura(con({}, { resultado: 30, sin_la_mejor: null }, { resultado: 10 })).titulo).toBe('Le habría ganado a comprar y mantener')
    expect(contraMantener({ compras: 0, resultado: 0 }, { resultado: -30 })).toBe('sin_compras')
    expect(lectura({ disponible: false, motivo: 'sin_datos' })).toBeNull()
  })

  it('A2: «sin esta compra habría terminado en pérdida» sólo si es verdad', () => {
    const s = (sin_ella, resultado = 10, mejor = 8) => ({ resultado, sin_la_mejor: { compra: '2026-01-05', resultado: mejor, sin_ella } })
    expect(compraClave(s(-0.1))).toBe('2026-01-05')
    expect(sinEstaCompra(s(-0.1))).toBe('Sin esta compra, la regla habría terminado en pérdida.')
    expect(compraClave(s(0))).toBe('2026-01-05')
    expect(sinEstaCompra(s(0))).toBe('Sin esta compra, la regla habría terminado en 0%.')
    expect(lectura(con({}, { ...s(0), compras: 12 })).frases).toContain(
      'Sin la compra del 05/01/26 (+8,0%), la regla habría terminado en 0%.')
    expect(compraClave(s(0.5))).toBeNull()
    expect(compraClave(s(75.8, 175.1, 56.5)), 'una de +56 % cuando las demás dieron +76 %').toBeNull()
    expect(compraClave(s(-3, -2))).toBeNull()
    expect(compraClave({ resultado: 10, sin_la_mejor: null })).toBeNull()
  })

  it('B1: cuántos días estuvo afuera, sin «el 100 %» con una compra ni «el 0 %» si estuvo afuera alguno', () => {
    const r = { ruedas: 501 }
    expect(parteAfuera(r, { ruedas_comprada: 223 })).toBe('el 55%')
    expect(parteAfuera(r, { ruedas_comprada: 1 })).toBe('más del 99%')
    expect(parteAfuera(r, { ruedas_comprada: 500 })).toBe('menos del 1%')
    expect(parteAfuera(r, { ruedas_comprada: 501 })).toBe('el 0%')
  })
})

describe('varias reglas: lo que dicen los números, sin elegir «la mejor»', () => {
  it('RSI y ADX + Squeeze en GGAL', () => {
    expect(lectura(GGAL['rsi,adx_squeeze'])).toEqual({
      titulo: 'Las dos habrían terminado mejor que comprar y mantener',
      frases: [
        'GGAL bajó 35% en los últimos 2 años y las reglas estuvieron afuera entre el 55% y el 78% de los días.',
        'RSI 30 / 70: sin la compra del 05/05/26 (+32,6%), la regla habría terminado en pérdida: −7,6%.',
        'ADX + Squeeze: sin la compra del 03/03/26 (+13,3%), la regla habría terminado en pérdida: −1,9%.',
        'Con tan pocas compras (3 y 7) en los últimos 2 años, no alcanza para saber si una regla es mejor que otra o si tuvo suerte.',
        'Probá las mismas reglas en otro activo: cuando lo medimos en 14 papeles, la regla que dio más cambió de un papel a otro.',
      ],
    })
  })

  it('las tres en GGAL: cuenta cuántas le ganaron y las compras de cada una, en su orden', () => {
    const l = lectura(GGAL['media50,rsi,adx_squeeze'])
    expect(l.titulo).toBe('Las tres habrían terminado mejor que comprar y mantener')
    expect(l.frases).toContain('Con tan pocas compras (10, 3 y 7) en los últimos 2 años, no alcanza para saber si una regla '
      + 'es mejor que otra o si tuvo suerte.')
  })

  it('los títulos dicen cuántas, nunca cuál', () => {
    const tres = GGAL['media50,rsi,adx_squeeze']
    const contra = (mantener) => lectura({ ...tres, mantener: { ...tres.mantener, resultado: mantener } }).titulo
    expect(contra(200)).toBe('Ninguna habría terminado mejor que comprar y mantener')
    expect(contra(10)).toBe('Dos de las tres habrían terminado mejor que comprar y mantener')
    expect(contra(20)).toBe('Una de las tres habría terminado mejor que comprar y mantener')
    for (const t of [contra(200), contra(10), contra(20), contra(-50)]) {
      // Contra comprar y mantener sí («terminado mejor que…»); entre ellas, nunca «la mejor».
      expect(t).not.toMatch(/RSI|ADX|media|\b(la|el|es) mejor\b/i)
    }
  })

  it('M1: una regla que no compró no le ganó a nadie, y se dice aparte', () => {
    const dos = GGAL['rsi,adx_squeeze']
    const r = { ...dos, resultados: [dos.resultados[0], sinCompras(dos.resultados[1])] }
    const l = lectura(r)
    expect(l.titulo).toBe('Una de las dos habría terminado mejor que comprar y mantener')
    expect(l.frases[0]).toBe('GGAL bajó 35% en los últimos 2 años y RSI 30 / 70 estuvo afuera el 55% de los días.')
    expect(l.frases).toContain('ADX + Squeeze no marcó ninguna compra en los últimos 2 años.')
    const ninguna = { ...dos, resultados: dos.resultados.map(sinCompras) }
    expect(lectura(ninguna).titulo).toBe('Ninguna marcó compras en el período')
  })

  it('M8: la advertencia final es un dato en pasado, no una regla', () => {
    const fin = lectura(GGAL['rsi,adx_squeeze']).frases.at(-1)
    expect(fin).toMatch(/cuando lo medimos en 14 papeles/)
    expect(fin).not.toMatch(/muchas veces|suele|la mejor/i)
  })

  it('las franjas de cuándo estuvo comprada caen donde están sus compras', () => {
    const r = { ...GGAL.rsi, curva: Array.from({ length: 5 }, (_, k) => ({ d: `2026-01-0${k + 1}` })) }
    const x = { operaciones: [{ compra: '2026-01-02', venta: '2026-01-04' }, { compra: '2026-01-05', venta: '2026-01-05' }] }
    expect(tramosComprada(r, x)).toEqual([{ desde: 25, ancho: 50 }, { desde: 100, ancho: 25 }])
  })
})

describe('cuando la prueba arranca después de lo pedido', () => {
  it('la media de 200 necesita sus 200 días antes, sola o comparada', () => {
    const t = 'Hay precios de GGAL desde el 01/07/24 y la media de 200 días necesita 200 días de precios antes: '
      + 'la prueba arranca el 17/04/25.'
    expect(textoDelRecorte(GGAL.media200)).toBe(t)
    expect(textoDelRecorte(GGAL['rsi,media200'])).toBe(t)
    expect(textoDelRecorte(RSI)).toBeNull()
  })

  it('B5: un papel que cotiza hace poco, con la forma que manda el servidor (recorte_por siempre lleno)', () => {
    const joven = con({ recortado: true, recorte_por: 'rsi', primera_vela: '2025-03-28', desde: '2025-04-21',
      pedido_desde: '2024-11-05', asset: 'CRWV' })
    expect(textoDelRecorte(joven)).toBe('Hay precios de CRWV desde el 28/03/25 y el RSI necesita 15 días de precios '
      + 'antes: la prueba arranca el 21/04/25.')
    expect(lectura(joven).frases[0]).toMatch(/ desde el 21\/04\/25 y la regla/)
  })
})

describe('M3/M4: por qué no se pudo probar, en oraciones enteras', () => {
  it('cada motivo con el activo adentro', () => {
    expect(motivoEnPalabras({ motivo: 'sin_datos' }, 'NVDA')).toBe('No encontramos los precios de NVDA.')
    expect(motivoEnPalabras({ motivo: 'bajando' }, 'NVDA')).toBe('Estamos trayendo los precios de NVDA: probá de nuevo en unos segundos.')
    expect(motivoEnPalabras({ motivo: 'tope' }, 'NVDA')).toBe('Pediste muchos activos nuevos en poco tiempo: probá de nuevo en un rato.')
    expect(motivoEnPalabras({ motivo: 'sin_serie' }, 'AL30')).toBe('Para probar una regla hacen falta los precios de cada día '
      + '(apertura, máximo, mínimo y cierre), y de AL30 no los tenemos.')
    expect(motivoEnPalabras({ motivo: 'algo_nuevo' }, 'NVDA')).toBe('No encontramos los precios de NVDA.')
    // Sin precios de la última semana, contada desde hoy (auditoría 05/11, H9).
    expect(motivoEnPalabras({ motivo: 'vieja', hasta: '2026-09-04' }, 'MU'))
      .toBe('Los precios de MU llegan hasta el 04/09/26: para probar una regla hacen falta los de la última semana.')
  })

  it('poca historia: dice qué regla necesita más días y, comparando, que se puede sacar', () => {
    expect(motivoEnPalabras({ motivo: 'poca_historia', recorte_por: 'media200', reglas: ['rsi', 'media200'] }, 'JOVEN'))
      .toBe('JOVEN tiene muy pocos días de precios para probar «Precio y media de 200 días»: la media de 200 días '
        + 'necesita 200 días de precios antes. Sacá esa regla para probar las otras.')
    expect(motivoEnPalabras({ motivo: 'poca_historia', recorte_por: 'rsi', reglas: ['rsi'] }, 'JOVEN'))
      .toBe('JOVEN tiene muy pocos días de precios para probar «RSI 30 / 70»: el RSI necesita 15 días de precios antes.')
  })

  it('A1: en el modo demo lo dice, y no que NVDA es un bono o un fondo', () => {
    const r = handleDemoRequest('GET', '/tecnico/NVDA/backtest?reglas=rsi&anios=2')
    expect(r).toEqual({ asset: 'NVDA', disponible: false, motivo: 'demo' })
    expect(motivoEnPalabras(r, 'NVDA')).toBe('En el modo demo no hay precios de todos los días para probar reglas.')
    // La ficha del demo sigue como estaba: «sin serie» la manda al gráfico de 30 días.
    expect(handleDemoRequest('GET', '/tecnico/NVDA?moneda=usd')).toMatchObject({ disponible: false, motivo: 'sin_serie' })
  })
})

describe('los números', () => {
  it('con el menos tipográfico y la coma', () => {
    expect(porcentaje(-29.98)).toBe('−30,0%')
    expect(porcentaje(25.5)).toBe('+25,5%')
    expect(porcentaje(-58.92, 0)).toBe('−59%')
    expect(precio(59.85)).toBe('59,85')
    expect(precio(0.000412345)).toBe('0,0004123')
    expect(periodoEnPalabras(1)).toBe('el último año')
    expect([ganaron(0), ganaron(1), ganaron(4)]).toEqual(['ninguna ganó', '1 ganó', '4 ganaron'])
  })

  it('B9: una operación que ganó poco no se ve en «0,0 %» ni en gris', () => {
    expect(porcentaje(0.03)).toBe('+0,03%')
    expect(colorDe(0.03)).toBe(colorDe(5))
    expect(colorDe(-0.03)).toBe(colorDe(-5))
  })

  it('la aclaración dice la comisión que usó el servidor (B2: sin decimales de máquina)', () => {
    expect(comoSeSimula(RSI)).toContain('con 0,5% de comisión al comprar y al vender')
    expect(comoSeSimula({ ...RSI, comision: 0.007 * 100 })).toContain('con 0,7% de comisión')
    expect(comoSeSimula(RSI)).toContain('Cuando la regla está afuera')
    expect(comoSeSimula(GGAL['rsi,adx_squeeze'])).toContain('Cuando una regla está afuera')
    expect(comoSeSimula(RSI)).toContain('No incluye dividendos')
  })
})

describe('nunca promete', () => {
  it('ni «suele», ni «ayuda», ni «muchas veces», ni «comprá», ni «la mejor regla»', () => {
    // Medido el 04/11 (14 papeles, 2 años): la regla que dio más cambió de papel
    // en papel. Lo que habría pasado no dice nada de lo que va a pasar.
    const motivos = ['sin_serie', 'sin_datos', 'tope', 'bajando', 'demo', 'poca_historia']
      .map(motivo => motivoEnPalabras({ motivo, recorte_por: 'media200', reglas: ['rsi', 'media200'] }, 'GGAL'))
    const textos = [
      ...Object.values(GGAL).flatMap(r => { const l = lectura(r); return [l.titulo, ...l.frases, textoDelRecorte(r) || ''] }),
      ...REGLAS.flatMap(r => [r.nombre, r.corto, r.explica, r.necesita]),
      ...motivos, comoSeSimula(RSI), comoSeSimula(GGAL['rsi,adx_squeeze']), queSePrueba(false), queSePrueba(true),
    ].join(' ')
    expect(textos).not.toMatch(/suele|se viene|comprá|vendé|va a subir|va a bajar|rebota|frena|antesala|arranque|esperad|potencial|oportunidad|anticipa\b|conviene|deber[íi]as|mejor regla|la mejor\b|te recomend|ayuda|muchas veces/i)
  })
})
