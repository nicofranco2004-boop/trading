// Lo que DIBUJA el termómetro del mercado (pieza 7) con una respuesta de GET
// /api/termometro tal cual la armó el servidor (backend/termometro.py) con las
// velas reales del 28/10/2026 de las 503 empresas del S&P 500 y las 25 del
// panel (el panel, con un MEP fijo de prueba). La pantalla no recalcula: sólo
// pone palabras, y lo que dice tiene que salir de esos números.
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { TermometroVista, TuPlata } from './Termometro'
import {
  zona, partes, semanaPasadaTxt, cuando, tramo, puntoDelArco, LEYENDA, frasesTuPlata, filasTuPlata,
} from '../../utils/termometro'

const REAL = {
  "universo": 528,
  "medidas": 524,
  "disponible": true,
  "fecha": "2026-10-28",
  "puntaje": 64,
  "amplitud": {
    "pct": 55.7,
    "alcistas": 292,
    "medidas": 524,
    "puntos": 28,
    "sp500": {
      "alcistas": 289,
      "medidas": 499,
      "pct": 57.9
    },
    "panel": {
      "alcistas": 3,
      "medidas": 25,
      "pct": 12.0
    }
  },
  "indice": {
    "disponible": true,
    "fecha": "2026-10-28",
    "arriba200": true,
    "arriba50": true,
    "dist200": 6.04,
    "dist50": 0.6,
    "puntos": 25
  },
  "maximos": {
    "maximos": 19,
    "minimos": 22,
    "puntos": 11
  },
  "sectores": {
    "comunicacion": {
      "alcistas": 7,
      "medidas": 24,
      "pct": 29.2
    },
    "consumo_bas": {
      "alcistas": 22,
      "medidas": 34,
      "pct": 64.7
    },
    "consumo_disc": {
      "alcistas": 20,
      "medidas": 48,
      "pct": 41.7
    },
    "energia": {
      "alcistas": 18,
      "medidas": 24,
      "pct": 75.0
    },
    "financiero": {
      "alcistas": 49,
      "medidas": 82,
      "pct": 59.8
    },
    "industria": {
      "alcistas": 38,
      "medidas": 83,
      "pct": 45.8
    },
    "inmobiliario": {
      "alcistas": 8,
      "medidas": 30,
      "pct": 26.7
    },
    "materiales": {
      "alcistas": 17,
      "medidas": 28,
      "pct": 60.7
    },
    "salud": {
      "alcistas": 52,
      "medidas": 60,
      "pct": 86.7
    },
    "tecnologia": {
      "alcistas": 53,
      "medidas": 74,
      "pct": 71.6
    },
    "utilities": {
      "alcistas": 8,
      "medidas": 37,
      "pct": 21.6
    }
  },
  "semana_pasada": null,
  "viejo": false,
  "fuente": {
    "sp500_bajada": "2026-10-29",
    "pesos": {
      "amplitud": 50,
      "indice": 25,
      "maximos": 25
    }
  },
  "leyenda": "Describe cómo se mueve el mercado. No dice cuánto tener invertido ni es una recomendación."
}

describe('termómetro: las palabras', () => {
  it('los tres tramos del número', () => {
    expect(zona(39).texto).toBe('Mercado débil')
    expect(zona(40).texto).toBe('Mercado mixto')
    expect(zona(60).texto).toBe('Mercado mixto')
    expect(zona(61).texto).toBe('Mercado firme')
    expect(zona(REAL.puntaje)).toEqual({ texto: 'Mercado firme', tono: 'pos' })
  })

  it('cada parte dice cuánto suma, y las tres suman el número', () => {
    const ps = partes(REAL)
    expect(ps.map(p => p.id)).toEqual(['amplitud', 'indice', 'maximos'])
    expect(ps.map(p => p.de)).toEqual([50, 25, 25])
    expect(ps.reduce((s, p) => s + p.suma, 0)).toBe(REAL.puntaje)
    expect(ps[0].valor).toBe('56 %')
    expect(ps[0].detalle).toBe('292 de 524 están arriba de su promedio de 200 días. S&P 500: 58 % · panel argentino: 12 %.')
    expect(ps[1].valor).toBe('Arriba de sus promedios de 50 y de 200 días')
    expect(ps[1].detalle).toBe('Está 6 % arriba del de 200 días y 0,6 % arriba del de 50.')
    expect(ps[2].valor).toBe('19 contra 22')
    expect(ps[2].barra).toBeCloseTo(19 / 41 * 100)
  })

  it('la semana pasada: sólo lo guardado', () => {
    expect(semanaPasadaTxt(REAL)).toMatch(/todavía no hay dato/)
    expect(semanaPasadaTxt({ ...REAL, semana_pasada: { fecha: '2026-10-21', puntaje: 58 } }))
      .toBe('Hace una semana (21/10): 58')
  })

  it('de qué día es', () => {
    expect(cuando(REAL)).toBe('Al cierre del 28/10')
    expect(cuando({ ...REAL, viejo: true })).toBe('Último dato: cierre del 28/10')
  })

  it('el arco: 0 a la izquierda, 50 arriba, 100 a la derecha', () => {
    const r = v => puntoDelArco(v, 130, 130, 110).map(n => Math.round(n))
    expect(r(0)).toEqual([20, 130])
    expect(r(50)).toEqual([130, 20])
    expect(r(100)).toEqual([240, 130])
    expect(tramo(0, 100, 130, 130, 110)).toBe('M20,130 A110,110 0 0 1 240,130')
  })
})

describe('termómetro: la pantalla', () => {
  it('dibuja el número, sus partes y la frase fija', () => {
    const html = renderToStaticMarkup(<TermometroVista datos={REAL} />)
    expect(html).toContain('¿Cómo está el mercado?')
    expect(html).toContain('>64<')
    expect(html).toContain('Mercado firme')
    expect(html).toContain('Cuántas acciones suben de fondo')
    expect(html).toContain('Suma 28 de 50')
    expect(html).toContain('Suma 25 de 25')
    expect(html).toContain('Suma 11 de 25')
    expect(html).toContain(LEYENDA)
    expect(html).toContain('Termómetro en 64 de 100: mercado firme')
  })

  it('nunca dice qué hacer', () => {
    const html = renderToStaticMarkup(<TermometroVista datos={REAL} />).toLowerCase()
    for (const p of ['tené', 'comprá', 'vendé', 'invertí', 'te conviene', 'recomendamos']) {
      expect(html).not.toContain(p)
    }
  })

  it('sin número guardado lo dice, sin inventar', () => {
    const html = renderToStaticMarkup(<TermometroVista datos={{ disponible: false }} />)
    expect(html).toContain('Todavía no hay un número guardado')
    expect(html).not.toMatch(/Suma \d/)
  })
})

// `tu_plata` tal como la arma el servidor (backend/tests/test_termometro.py,
// test_tu_plata_por_sector): AAPL, GGAL argentina, KO y SPY.
const TP = {
  suben: { pct: 54, sectores: [
    { sector: 'tecnologia', mercado_pct: 50.0, pct: 35, papeles: ['AAPL'] },
    { sector: 'financiero', mercado_pct: 100.0, pct: 19, papeles: ['GGAL'] },
  ] },
  bajan: { pct: 23, sectores: [{ sector: 'consumo_bas', mercado_pct: 0.0, pct: 23, papeles: ['KO'] }] },
  sin_sector: { pct: 23, papeles: ['SPY'] },
}
const nombre = k => ({ tecnologia: 'Tecnología', financiero: 'Financiero', consumo_bas: 'Consumo básico' }[k])

describe('termómetro: tu plata por sector', () => {
  it('las tres frases, con la cifra aparte', () => {
    expect(frasesTuPlata(TP, nombre).map(f => `${f.cifra} ${f.texto}`)).toEqual([
      '54 % de tu plata está en sectores donde la mayoría de las acciones sube de fondo (Tecnología y Financiero).',
      '23 % está en sectores donde la mayoría baja (Consumo básico).',
      '23 % no tiene sector en esta cuenta.',
    ])
    expect(frasesTuPlata(TP, nombre, true).map(f => f.cifra)).toEqual(['—', '—', '—'])
    expect(frasesTuPlata(null, nombre)).toEqual([])
  })

  it('el detalle nombra tus papeles en cada sector, y los que no tienen sector', () => {
    const filas = filasTuPlata(TP, nombre)
    expect(filas.map(f => [f.nombre, f.pct, f.papeles.join(',')])).toEqual([
      ['Tecnología', 35, 'AAPL'], ['Financiero', 19, 'GGAL'], ['Consumo básico', 23, 'KO'], ['Sin sector', 23, 'SPY'],
    ])
    expect(filas[0].mercado).toBe('50 % de sus acciones sube de fondo')
  })

  it('en pantalla: al tocar se ve qué papel cayó en cada sector; con «Ocultar saldos», sin %', () => {
    const cerrado = renderToStaticMarkup(<TuPlata tp={TP} />)
    expect(cerrado).toContain('Qué papeles tuyos hay en cada sector')
    expect(cerrado).not.toContain('SPY')
    const abierto = renderToStaticMarkup(<TuPlata tp={TP} abierto />)
    expect(abierto).toContain('Sin sector')
    expect(abierto).toContain('SPY')
    expect(abierto).toContain('Alphabet y Meta van en Comunicación')
    const oculto = renderToStaticMarkup(<TuPlata tp={TP} abierto oculto />)
    expect(oculto).not.toMatch(/\b(54|35|19|23) %/)
    expect(oculto).toContain('AAPL')
  })

  it('sin cartera no se dibuja', () => {
    expect(renderToStaticMarkup(<TuPlata tp={null} />)).toBe('')
    expect(renderToStaticMarkup(<TermometroVista datos={{ ...REAL, tu_plata: null }} />)).not.toContain('Tu plata por sector')
    expect(renderToStaticMarkup(<TermometroVista datos={{ ...REAL, tu_plata: TP }} />)).toContain('Tu plata por sector')
  })
})
