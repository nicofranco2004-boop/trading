// El botón «Fibonacci» de la lectura técnica, montado de verdad
// (testing/navegadorMinimo.js) con /api/tecnico simulado en la frontera:
//   · prendido de entrada: las rayas con su precio y la tarjeta en castellano;
//   · el botón lo apaga (ni rayas ni tarjeta) y lo vuelve a prender;
//   · sin tramo para medir: la tarjeta lo dice y no hay rayas de niveles.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from 'vitest'
import { CAPAS_TODAS } from './BarraGrafico'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscar, buscarBoton, clic } from '../../testing/navegadorMinimo'

const puntos = Array.from({ length: 252 }, (_, i) => {
  const d = new Date(Date.UTC(2025, 9, 1) + i * 86400000).toISOString().slice(0, 10)
  const c = i < 150 ? 100 + i * 0.5 : 175 - (i - 150) * 0.3
  return { d, o: c, h: c * 1.01, l: c * 0.99, c, s50: null, s200: null, rsi: 50 }
})
const FIB = {
  disponible: true, n_pivote: 3, dir: 'suba',
  desde: { fecha: puntos[20].d, precio: 108.9 }, hasta: { fecha: puntos[150].d, precio: 176.75 },
  ruptura: { fecha: puntos[170].d, cierre: 169, nivel: 170, nivel_fecha: puntos[140].d },
  niveles: [0.236, 0.382, 0.5, 0.618, 0.786].map(n => ({ nivel: n, precio: 176.75 - n * 67.85 })),
  retroceso_hoy: 0.45, retroceso_maximo: { valor: 0.46, fecha: puntos[251].d }, entre: [0.382, 0.5],
}
const DATOS = (fibonacci) => ({
  disponible: true, moneda: 'usd', ticker: 'ZZFB', convertida: null, puntos, fibonacci,
  lectura: { ruedas: 252, fecha: puntos[251].d, precio: puntos[251].c, rsi: 50 },
})

let respuesta
vi.mock('../../utils/api', () => ({
  // La copia de los dibujos es de la persona y la cuenta (utils/duenoDeLaPestana).
  getClientContext: () => null,
  EVENTO_CUENTA_CAMBIADA: 'rendi:cuenta-cambiada',
  api: { get: vi.fn(() => Promise.resolve(respuesta)) },
}))

let LecturaTecnica
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
// De fábrica el gráfico viene limpio (precio, promedio de 200 y volumen). Estas
// pruebas miran las demás capas: arrancan con todas prendidas, como quien las
// prende desde «Indicadores» (lo que se prende queda guardado así).
beforeEach(() => { try { localStorage.setItem('rendi_grafico_capas', JSON.stringify(CAPAS_TODAS)) } catch { /* sin almacenamiento */ } })
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  localStorage.clear()   // lo que apaga una prueba no pasa a la siguiente
})

const el = () => h(LecturaTecnica, { asset: 'ZZFB' })
async function dibujar() {
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

// Un botón por su `data-capa` (la barra, su menú o el ojito de la lista).
function porCapa(id) {
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === id) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}
// Fibonacci y Elliott: el automático y el «a mano» viven en el menú de su botón.
async function enElMenu(menu, opcion) {
  await clic(montado.contenedor, porCapa(menu))
  for (let i = 0; i < 2; i++) await montado.redibujar(el())
  const b = porCapa(opcion)
  return b
}
async function tocarFibonacci() {
  await clic(montado.contenedor, await enElMenu('menu-fibonacci', 'fib'))
  for (let i = 0; i < 2; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

describe('Fibonacci en la ficha', () => {
  it('prendido de entrada: rayas con precio y la tarjeta; el botón lo apaga', async () => {
    respuesta = DATOS(FIB)
    const t = await dibujar()
    expect(t).toContain('Fibonacci de la última suba')
    expect(t).toContain('Devolvió el 45 % de la suba')
    expect(t).toContain('está entre el 38,2 % y el 50 % de la suba')
    expect(t).toContain('Pico · US$ 176,75')         // el final del tramo, siempre con rótulo
    expect(t).toContain('Arranque · US$ 108,90')
    expect(t).toContain('no es una recomendación')
    // Apagarlo lo saca, y prenderlo lo vuelve a poner.
    const apagado = await tocarFibonacci()
    expect(apagado).toContain('Fibonacci')            // el botón sigue
    expect(apagado).not.toContain('Fibonacci de la última suba')
    expect(apagado).not.toContain('61,8 % ·')
    expect(await tocarFibonacci()).toContain('Fibonacci de la última suba')
  })

  it('el impulso de 5 ondas de Elliott (sin ruptura): rayas, tarjeta del impulso y sin rombo', async () => {
    // backend/estructura.py `de: 'impulso'` (INTC, 02/11/26): lo terminó el
    // conteo, no un cierre; antes la capa leía `ruptura.fecha` y se rompía.
    respuesta = DATOS({ ...FIB, de: 'impulso', ruptura: null, extension: null, tramo: { disponible: false, motivo: 'superado' } })
    const t = await dibujar()
    expect(t).toContain('Fibonacci del impulso de suba')
    expect(t).toContain('Devolvió el 45 % del impulso')
    expect(t).toContain('Pico · US$ 176,75')
    expect(t).toContain('Arranque · US$ 108,90')
    expect(montado.contenedor.querySelector('[title^="Ruptura"]')).toBeNull()
  })

  it('un impulso que arrancó antes de lo que se ve: no aplasta las velas y no dibuja rayas fuera del gráfico', async () => {
    // INTC en el celular con «Lo reciente» (auditoría 02/11): el impulso de
    // 32,89 a 142,35 arranca 8 meses antes de la vista, con el precio entre 63 y
    // 127. Antes la escala iba hasta 32,89 y las velas quedaban aplastadas.
    const { default: Capa, preciosDeLaCapa, trazosDelFibonacci } = await import('./CapaFibonacci')
    const vista = puntos.slice(200).map((p, i) => ({ ...p, c: 127 - i, h: 128 - i, l: 126 - i - 13 }))   // de 127 a 63
    const imp = {
      ...FIB, de: 'impulso', ruptura: null, desde: { fecha: puntos[0].d, precio: 32.89 }, hasta: { fecha: puntos[100].d, precio: 142.35 },
      niveles: [0.236, 0.382, 0.5, 0.618, 0.786].map(n => ({ nivel: n, precio: 142.35 - n * 109.46 })), entre: [0.618, 0.786],
    }
    const escala = preciosDeLaCapa(imp, vista)
    expect(Math.min(...escala)).toBeCloseTo(142.35 - 0.786 * 109.46, 2)   // 56,31: la raya debajo de 63
    expect(escala).not.toContain(32.89)
    const lo = Math.min(...escala, ...vista.map(p => p.l)), hi = Math.max(...escala, ...vista.map(p => p.h))
    const pctY = (v) => ((hi - v) / (hi - lo)) * 100
    const pctX = (i) => (i / (vista.length - 1)) * 100
    for (const t of trazosDelFibonacci(imp, vista, pctX, pctY)) expect(t.y1 >= 0 && t.y1 <= 100).toBe(true)
    montado = await montar(h(Capa, { fib: imp, puntos: vista, pctX, pctY, precio: (x) => `US$ ${x.toFixed(2)}` }))
    const t = texto(montado.contenedor)
    expect(t).toContain('61,8 % · US$ 74.70')
    expect(t).not.toContain('Arranque')                 // 32,89 queda fuera del gráfico: no se dibuja
    for (const d of montado.contenedor.querySelectorAll('div.absolute.h-0')) {
      const top = parseFloat(d.style.top)
      expect(top >= 0 && top <= 100).toBe(true)
    }
  })

  it('sin tramo claro: lo dice y no dibuja niveles', async () => {
    respuesta = DATOS({ disponible: false, motivo: 'tramos_chicos', n_pivote: 3, ruedas: 252, en_curso: null })
    const t = await dibujar()
    expect(t).toContain('Sin tramo claro')
    expect(t).not.toContain('61,8 % ·')
  })

  it('al prenderlo con un tramo corto, el gráfico se acerca al tramo', async () => {
    const { ventanaDelTramo } = await import('./CapaFibonacci')
    // Tramo de las últimas 30 ruedas en un gráfico de 252: se ven 63 (el mínimo).
    const corto = {
      ...FIB, desde: { fecha: puntos[222].d, precio: 100 }, hasta: { fecha: puntos[240].d, precio: 200 },
      ruptura: { fecha: puntos[245].d, cierre: 180, nivel: 185, nivel_fecha: puntos[236].d },
      niveles: [0.236, 0.382, 0.5, 0.618, 0.786].map(n => ({ nivel: n, precio: 200 - n * 100 })),
    }
    expect(ventanaDelTramo(puntos, corto, 252)).toEqual({ n: 63, fin: 252 })
    // Tramo de 100 ruedas: 160, con aire antes del arranque.
    expect(ventanaDelTramo(puntos, { ...FIB, desde: { fecha: puntos[152].d, precio: 150 } }, 252)).toEqual({ n: 160, fin: 252 })
    // Ya se ve entero: no toca nada. Sin tramo, o arranca antes del gráfico: tampoco.
    expect(ventanaDelTramo(puntos, FIB, 252)).toBeNull()
    expect(ventanaDelTramo(puntos, corto, 63)).toBeNull()
    expect(ventanaDelTramo(puntos, { disponible: false }, 252)).toBeNull()
    expect(ventanaDelTramo(puntos, { ...FIB, desde: { fecha: '2020-01-01', precio: 1 } }, 252)).toBeNull()
    // Montado: con el tramo corto, al apagarlo y volver a prenderlo el gráfico
    // se acerca y aparecen las 7 rayas con rótulo.
    respuesta = DATOS(corto)
    await dibujar()
    await tocarFibonacci()
    const t = await tocarFibonacci()
    for (const n of ['Pico ·', '23,6 % ·', '38,2 % ·', '50 % ·', '61,8 % ·', '78,6 % ·', 'Arranque ·']) expect(t).toContain(n)
  })

  it('con zoom o arrastre, lo que queda fuera de la vista no se dibuja en otro lugar', async () => {
    const { default: Capa, posicion, preciosDeLaCapa } = await import('./CapaFibonacci')
    const capa = (vista) => h(Capa, {
      fib: FIB, puntos: vista, pctX: (i) => (i / (vista.length - 1)) * 100, pctY: (v) => 100 - (v - 100), precio: (x) => `US$ ${x}`,
    })
    // Ventana corrida al pasado (antes del arranque del tramo): nada, y la escala no se estira.
    const pasado = puntos.slice(0, 15)
    expect(posicion(pasado, FIB.desde.fecha).donde).toBe('despues')
    expect(preciosDeLaCapa(FIB, pasado)).toEqual([])
    montado = await montar(capa(pasado))
    expect(texto(montado.contenedor)).toBe('')
    await montado.desmontar()
    // Ventana que empieza a mitad del tramo: las rayas desde el borde, pero no
    // la raya del tramo ni su arranque (quedarían en una fecha que no es la suya).
    const medio = puntos.slice(60)
    expect(posicion(medio, FIB.desde.fecha).donde).toBe('antes')
    // La escala se estira hasta la raya más cercana debajo de lo que se ve
    // (78,6 %, 123,42), no hasta el arranque (108,90): auditoría 02/11.
    const escala = preciosDeLaCapa(FIB, medio)
    expect(Math.min(...escala)).toBeCloseTo(176.75 - 0.786 * 67.85, 2)
    expect(escala).not.toContain(108.9)
    expect(Math.max(...escala)).toBe(176.75)
    montado = await montar(capa(medio))
    expect(texto(montado.contenedor)).toContain('50 % ·')
    expect(buscar(montado.contenedor, 'svg')).toBeNull()
    await montado.desmontar()
    // Con todo a la vista, sí.
    montado = await montar(capa(puntos))
    expect(buscar(montado.contenedor, 'svg')).not.toBeNull()
    // Una vela semanal cubre su semana: el miércoles cae adentro, el lunes siguiente no.
    const semanal = [{ d: '2026-10-05', semana: true }, { d: '2026-10-12', semana: true }]
    expect(posicion(semanal, '2026-10-14').donde).toBe('adentro')
    expect(posicion(semanal, '2026-10-19').donde).toBe('despues')
  })

  it('una respuesta vieja sin el campo: el botón deshabilitado, con el porqué, y nada dibujado', async () => {
    respuesta = DATOS(undefined)
    const t = await dibujar()
    expect(t).not.toContain('Fibonacci de la')
    expect(t).not.toContain('61,8 % ·')
    expect((await enElMenu('menu-fibonacci', 'fib')).getAttribute('aria-disabled')).toBe('true')
    await clic(montado.contenedor, porCapa('menu-fibonacci'))   // lo cierra
    expect(await tocarFibonacci()).toContain('Fibonacci (automático): Este activo todavía no tiene el cálculo del Fibonacci.')
  })
})
