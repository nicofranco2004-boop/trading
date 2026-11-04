// Las palabras de la pestaña «Backtesting» (utils/backtesting.js).
// Lo que importa:
//   · las reglas, los períodos y el máximo para comparar son los del servidor
//     (backend/backtest.py): uno que no existe allá daría un 400;
//   · lo que se dice sale de la respuesta REAL del servidor para GGAL
//     (backend/tests/fixtures/backtest_ggal.json, que test_backtest.py compara
//     contra backtest.probar): no de un caso armado a mano;
//   · dice lo que pasó, en pasado, al lado de comprar y mantener; con pocas
//     compras, que no alcanzan para separar la regla de la suerte; si una sola
//     compra explica el resultado, cuál; comparando, cuántas le ganaron a
//     mantener, nunca cuál es «la mejor»;
//   · nunca promete.
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import {
  DE_ENTRADA, MAX_REGLAS, MOTIVOS, PERIODOS, POCAS_COMPRAS, REGLAS, aniosDe, comoSeSimula, compraClave, ganaron,
  lectura, otraRegla, periodoEnPalabras, porcentaje, precio, reglaDe, reglasDe, textoDelRecorte, tramosComprada,
} from './backtesting'

const AQUI = dirname(fileURLToPath(import.meta.url))
const GGAL = JSON.parse(readFileSync(resolve(AQUI, '../../../backend/tests/fixtures/backtest_ggal.json'), 'utf8'))
const PY = readFileSync(resolve(AQUI, '../../../backend/backtest.py'), 'utf8')
const RSI = GGAL.rsi

// Un resultado armado sobre uno real, para los casos que GGAL no tiene.
const con = (cambios = {}, regla = {}, mantener = {}) => ({
  ...RSI, ...cambios,
  resultados: [{ ...RSI.resultados[0], ...regla }],
  mantener: { ...RSI.mantener, ...mantener },
})

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

  it('lo que viene en la dirección y no se ofrece abre lo de entrada', () => {
    expect(aniosDe('3')).toBe(3)
    expect(aniosDe('5')).toBe(DE_ENTRADA.anios)
    expect(aniosDe(null)).toBe(DE_ENTRADA.anios)
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
  it('RSI en GGAL: le fue mejor porque el papel cayó, una compra explica casi todo y fueron muy pocas', () => {
    expect(lectura(RSI)).toEqual({
      titulo: 'Le fue mejor que comprar y mantener',
      frases: [
        'GGAL bajó 35% en los últimos 2 años y la regla estuvo afuera el 55% de los días: cuando el precio cae, estar afuera ayuda.',
        'La compra del 05/05/26 (+33,6%) explica casi todo: sin ella, la regla habría dado −6,1%.',
        'En el camino llegó a caer 59% desde su mejor momento.',
        'Fueron 3 compras en los últimos 2 años: con tan pocas, no alcanza para saber si el resultado es de la regla o de la suerte.',
      ],
    })
  })

  it('media de 200 en GGAL: perdió menos, desde el día en que la media existe', () => {
    const l = lectura(GGAL.media200)
    expect(l.titulo).toBe('Perdió menos que comprar y mantener')
    expect(l.frases[0]).toBe('GGAL bajó 42% desde el 17/04/25 y la regla estuvo afuera el 66% de los días: '
      + 'cuando el precio cae, estar afuera ayuda.')
    expect(l.frases.join(' ')).not.toMatch(/explica casi todo/)
    expect(GGAL.media200.resultados[0].compras).toBeGreaterThanOrEqual(POCAS_COMPRAS)
    expect(l.frases.join(' ')).not.toMatch(/con tan pocas/)
  })

  it('el ADX + Squeeze en GGAL: la mejor compra explica casi todo', () => {
    expect(compraClave(GGAL.adx_squeeze.resultados[0])).toBe('2026-03-03')
    expect(lectura(GGAL.adx_squeeze).frases).toContain(
      'La compra del 03/03/26 (+14,2%) explica casi todo: sin ella, la regla habría dado +3,0%.')
  })

  it('comprar y mantener le ganó: no se dice que estar afuera ayudó', () => {
    const l = lectura(con({ asset: 'KO', anios: 1 }, { resultado: 4, compras: 12, sin_la_mejor: null },
      { resultado: 20 }))
    expect(l.titulo).toBe('Comprar y mantener le ganó')
    expect(l.frases[0]).toBe('KO subió 20% en el último año y la regla estuvo afuera el 55% de los días.')
    expect(l.frases.join(' ')).not.toMatch(/ayuda|en el camino|con tan pocas/)
  })

  it('una regla que no compró nunca', () => {
    expect(lectura(con({ anios: 1 }, { compras: 0, ganadoras: 0, ruedas_comprada: 0, resultado: 0 }, { resultado: 20 })))
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

  it('casi lo mismo, y los demás títulos', () => {
    expect(lectura(con({}, { resultado: 10 }, { resultado: 10.02 })).titulo).toBe('Dio casi lo mismo que comprar y mantener')
    expect(lectura(con({}, { resultado: 30, sin_la_mejor: null }, { resultado: 10 })).titulo).toBe('Le ganó a comprar y mantener')
    expect(lectura({ disponible: false, motivo: 'sin_datos' })).toBeNull()
  })

  it('la compra que explica casi todo: sólo si la regla ganó y sin ella da menos de la mitad', () => {
    const s = (sin_ella, resultado = 10) => ({ resultado, sin_la_mejor: { compra: '2026-01-05', resultado: 8, sin_ella } })
    expect(compraClave(s(4.9))).toBe('2026-01-05')
    expect(compraClave(s(5.1))).toBeNull()
    expect(compraClave(s(-3, -2))).toBeNull()
    expect(compraClave({ resultado: 10, sin_la_mejor: null })).toBeNull()
  })
})

describe('varias reglas: lo que dicen los números, sin elegir «la mejor»', () => {
  it('RSI y ADX + Squeeze en GGAL', () => {
    expect(lectura(GGAL['rsi,adx_squeeze'])).toEqual({
      titulo: 'Las dos le ganaron a comprar y mantener',
      frases: [
        'GGAL bajó 35% en los últimos 2 años y las reglas estuvieron afuera entre el 55% y el 78% de los días: cuando el precio cae, estar afuera ayuda.',
        'RSI 30 / 70: la compra del 05/05/26 (+33,6%) explica casi todo; sin ella habría dado −6,1%.',
        'ADX + Squeeze: la compra del 03/03/26 (+14,2%) explica casi todo; sin ella habría dado +3,0%.',
        'Con 3 y 7 compras en los últimos 2 años, no alcanza para saber si una regla es mejor que otra o si tuvo suerte.',
        'Probá las mismas reglas en otro activo: la que sale mejor en uno muchas veces no es la que sale mejor en otro.',
      ],
    })
  })

  it('las tres en GGAL: cuenta cuántas le ganaron y las compras de cada una, en su orden', () => {
    const l = lectura(GGAL['media50,rsi,adx_squeeze'])
    expect(l.titulo).toBe('Las tres le ganaron a comprar y mantener')
    expect(l.frases).toContain('Con 10, 3 y 7 compras en los últimos 2 años, no alcanza para saber si una regla '
      + 'es mejor que otra o si tuvo suerte.')
  })

  it('los títulos dicen cuántas, nunca cuál', () => {
    const tres = GGAL['media50,rsi,adx_squeeze']
    const contra = (mantener) => lectura({ ...tres, mantener: { ...tres.mantener, resultado: mantener } }).titulo
    expect(contra(200)).toBe('Ninguna le ganó a comprar y mantener')
    expect(contra(10)).toBe('Dos de las tres le ganaron a comprar y mantener')
    expect(contra(20)).toBe('Una de las tres le ganó a comprar y mantener')
    for (const t of [contra(200), contra(10), contra(20), contra(-50)]) {
      expect(t).not.toMatch(/RSI|ADX|media|mejor/i)
    }
  })

  it('las franjas de cuándo estuvo comprada caen donde están sus compras', () => {
    const r = { ...GGAL.rsi, curva: Array.from({ length: 5 }, (_, k) => ({ d: `2026-01-0${k + 1}` })) }
    const x = { operaciones: [{ compra: '2026-01-02', venta: '2026-01-04' }, { compra: '2026-01-05', venta: '2026-01-05' }] }
    expect(tramosComprada(r, x)).toEqual([{ desde: 25, ancho: 50 }, { desde: 100, ancho: 25 }])
  })
})

describe('cuando la prueba arranca después de lo pedido', () => {
  it('la media de 200 necesita sus 200 días antes', () => {
    expect(textoDelRecorte(GGAL.media200)).toBe('Hay precios de GGAL desde el 01/07/24 y la media de 200 días necesita '
      + '200 días de precios antes: la prueba arranca el 17/04/25.')
    expect(textoDelRecorte(RSI)).toBeNull()
  })

  it('un papel que cotiza hace poco', () => {
    const joven = con({ recortado: true, recorte_por: null, primera_vela: '2025-03-28', desde: '2025-03-28',
      pedido_desde: '2024-11-05', asset: 'CRWV' })
    expect(textoDelRecorte(joven)).toBe('Hay precios de CRWV desde el 28/03/25: la prueba arranca ese día.')
    expect(lectura(joven).frases[0]).toMatch(/ desde el 28\/03\/25 y la regla/)
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

  it('la aclaración dice la comisión que usó el servidor', () => {
    expect(comoSeSimula(RSI)).toContain('con 0,1% de comisión al comprar y al vender')
    expect(comoSeSimula(RSI)).toContain('Cuando la regla está afuera')
    expect(comoSeSimula(GGAL['rsi,adx_squeeze'])).toContain('Cuando una regla está afuera')
    expect(comoSeSimula(RSI)).toContain('No incluye dividendos')
  })
})

describe('nunca promete', () => {
  it('ni «suele», ni «se viene», ni «comprá», ni «la mejor regla»', () => {
    // Medido el 04/11 (14 papeles, 2 años): la regla que sale «mejor» cambia de
    // papel en papel. Lo que habría pasado no dice nada de lo que va a pasar.
    const textos = [
      ...Object.values(GGAL).flatMap(r => { const l = lectura(r); return [l.titulo, ...l.frases, textoDelRecorte(r) || ''] }),
      ...REGLAS.flatMap(r => [r.nombre, r.corto, r.explica, r.necesita]),
      ...Object.values(MOTIVOS), comoSeSimula(RSI), comoSeSimula(GGAL['rsi,adx_squeeze']),
    ].join(' ')
    expect(textos).not.toMatch(/suele|se viene|comprá|vendé|va a subir|va a bajar|rebota|frena|antesala|arranque|esperad|potencial|oportunidad|anticipa\b|conviene|deber[íi]as|mejor regla|la mejor\b|te recomend/i)
  })
})
