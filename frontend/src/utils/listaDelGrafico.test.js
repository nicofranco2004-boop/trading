// La lista al costado del gráfico, sin pantalla (utils/listaDelGrafico.js): qué
// es cada activo, cómo se agrupa y se ordena, qué renglón es el que estás
// mirando, qué tenés y lo que dice la ficha corta.
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect, beforeEach } from 'vitest'
import { instalarNavegadorMinimo } from '../testing/navegadorMinimo'
import {
  BANDERAS, armarLista, banderaAlAgregar, colorDeBandera, enSuLugar, filaDe, filaDelActivo, guardarVista,
  lecturaCorta, loTenes, mover, nombreDeBandera, nombresDeBanderas, numerosDe, textoDeLaRueda, textoLoTenes,
  tipoDeSimbolo, tipoDelLote, vistaGuardada, VISTA_DE_ENTRADA,
} from './listaDelGrafico'

const AQUI = dirname(fileURLToPath(import.meta.url))
const MAIN_PY = readFileSync(resolve(AQUI, '../../../backend/main.py'), 'utf8')

const it_ = (symbol, extra = {}) => filaDe({ symbol, price: 100, change: 1, change_pct: 1, ...extra })

describe('las banderas son las del servidor', () => {
  it('los mismos siete ids, en el mismo orden (main.BANDERAS_DE_LA_LISTA)', () => {
    const m = MAIN_PY.match(/^BANDERAS_DE_LA_LISTA = \(([^)]*)\)/m)
    expect(m, 'no encontré BANDERAS_DE_LA_LISTA en backend/main.py').toBeTruthy()
    const delServidor = [...m[1].matchAll(/"([a-z]+)"/g)].map(x => x[1])
    expect(BANDERAS.map(b => b.id)).toEqual(delServidor)
  })
  it('cada una pinta con una variable del tema, nunca un color escrito a mano', () => {
    for (const b of BANDERAS) expect(colorDeBandera(b.id)).toMatch(/^rgb\(var\(--[a-z0-9-]+\) \/ 1\)$/)
    expect(colorDeBandera('dorada')).toBeNull()
  })
  it('sin nombre se llama por su color; los nombres vienen de la cuenta', () => {
    const nombres = nombresDeBanderas([{ id: 'azul', nombre: 'EE.UU.' }, { id: 'rosa', nombre: null }, { id: 'dorada', nombre: 'x' }])
    expect(nombres).toEqual({ azul: 'EE.UU.' })
    expect(nombreDeBandera('azul', nombres)).toEqual({ texto: 'EE.UU.', conNombre: true })
    expect(nombreDeBandera('rosa', nombres)).toEqual({ texto: 'Rosa', conNombre: false })
    expect(nombreDeBandera(null, nombres).texto).toBe('Sin bandera')
  })
})

describe('qué es cada activo (agrupar por tipo, sin banderas)', () => {
  it('la regla de la app: CEDEAR con .BA, acción argentina con o sin .BA, cripto, ETF', () => {
    expect(tipoDeSimbolo('AAPL')).toBe('eeuu')
    expect(tipoDeSimbolo('AAPL.BA')).toBe('cedear')
    expect(tipoDeSimbolo('GGAL.BA')).toBe('arg')
    expect(tipoDeSimbolo('GGAL')).toBe('arg')
    expect(tipoDeSimbolo('BTC')).toBe('cripto')
    expect(tipoDeSimbolo('BTC-USD')).toBe('cripto')
    expect(tipoDeSimbolo('SPY')).toBe('etf')
    // «AGRO» guardado como STOCK es Adecoagro de Nueva York, no Agrometal.
    expect(tipoDeSimbolo('AGRO', 'STOCK')).toBe('eeuu')
  })
  it('el renglón: ticker sin .BA, en pesos si cotiza en BYMA, bandera válida o ninguna', () => {
    const f = filaDe({ symbol: 'tsla.ba', bandera: 'naranja', orden: 3, price: 39960, change: 1460, change_pct: 3.79 })
    expect(f).toMatchObject({ simbolo: 'TSLA.BA', ticker: 'TSLA', tipo: 'cedear', pesos: true, bandera: 'naranja', orden: 3 })
    expect(filaDe({ symbol: 'AAPL', bandera: 'dorada' }).bandera).toBeNull()
  })
})

describe('agrupar, filtrar y ordenar', () => {
  const filas = [
    it_('META', { bandera: 'azul', orden: 0, change_pct: -0.04, added_at: '2026-11-01' }),
    it_('TSLA', { bandera: 'azul', orden: 1, change_pct: -0.57, added_at: '2026-11-02' }),
    it_('TSLA.BA', { bandera: 'naranja', orden: 2, change_pct: 3.79, added_at: '2026-11-03' }),
    it_('GGAL.BA', { bandera: null, orden: 3, change_pct: -2.1, added_at: '2026-11-04' }),
    it_('BTC', { bandera: 'azul', orden: 4, change_pct: 2.76, added_at: '2026-11-05' }),
  ]
  it('por bandera (de entrada): en el orden de las banderas, y al final «Sin bandera»', () => {
    const { chips, secciones } = armarLista({ filas, nombres: { azul: 'EE.UU.' } })
    expect(secciones.map(s => [s.id, s.titulo, s.filas.map(f => f.simbolo)])).toEqual([
      ['azul', 'EE.UU.', ['META', 'TSLA', 'BTC']],
      ['naranja', 'Naranja', ['TSLA.BA']],
      ['sin', 'Sin bandera', ['GGAL.BA']],
    ])
    expect(chips.map(c => [c.id, c.n])).toEqual([['todas', 5], ['azul', 3], ['naranja', 1], ['sin', 1]])
    // Una sección que mezcla tipos lleva el cartelito (BTC al lado de acciones).
    expect(secciones[0]).toMatchObject({ mixta: true, sub: 'en dólares' })
    expect(secciones[1]).toMatchObject({ mixta: false, sub: 'en pesos' })
  })
  it('filtrar por una bandera muestra sólo esa; una que ya no existe vuelve a «Todas»', () => {
    expect(armarLista({ filas, filtro: 'naranja' }).secciones.map(s => s.id)).toEqual(['naranja'])
    const r = armarLista({ filas, filtro: 'rosa' })
    expect(r.filtro).toBe('todas')
    expect(r.secciones).toHaveLength(3)
  })
  it('por tipo se arma solo: EE.UU., CEDEARs, argentinas, cripto', () => {
    const { secciones } = armarLista({ filas, agrupar: 'tipo' })
    expect(secciones.map(s => [s.titulo, s.filas.map(f => f.simbolo)])).toEqual([
      ['Acciones de EE.UU.', ['META', 'TSLA']],
      ['CEDEARs', ['TSLA.BA']],
      ['Acciones argentinas', ['GGAL.BA']],
      ['Cripto', ['BTC']],
    ])
  })
  it('sin grupos: una sola lista sin botones arriba, con el cartelito del tipo', () => {
    const { chips, secciones } = armarLista({ filas, agrupar: 'nada' })
    expect(chips).toEqual([])
    expect(secciones).toHaveLength(1)
    expect(secciones[0]).toMatchObject({ titulo: null, mixta: true })
  })
  it('ordenar: como los acomodás, por ticker, lo que más subió hoy (sin precio, al final)', () => {
    const sin = [...filas, it_('KO', { bandera: 'azul', orden: 5, change_pct: null, price: null })]
    const de = (orden) => armarLista({ filas: sin, orden }).secciones[0].filas.map(f => f.simbolo)
    expect(de('tuyo')).toEqual(['META', 'TSLA', 'BTC', 'KO'])
    expect(de('ticker')).toEqual(['BTC', 'KO', 'META', 'TSLA'])
    expect(de('hoy')).toEqual(['BTC', 'META', 'TSLA', 'KO'])
  })
  it('lo que agregás entra con la bandera que estás mirando, si estás agrupando por bandera', () => {
    expect(banderaAlAgregar({ agrupar: 'bandera', filtro: 'naranja' })).toBe('naranja')
    expect(banderaAlAgregar({ agrupar: 'bandera', filtro: 'todas' })).toBeNull()
    expect(banderaAlAgregar({ agrupar: 'bandera', filtro: 'sin' })).toBeNull()
    expect(banderaAlAgregar({ agrupar: 'tipo', filtro: 'cedear' })).toBeNull()
  })
})

describe('«como los acomodás»', () => {
  it('lo que nunca se movió va primero, en el orden en que se agregó; después los que tienen lugar', () => {
    const f = enSuLugar([
      it_('B', { orden: 0, added_at: '2026-11-09' }),
      it_('VIEJO2', { orden: null, added_at: '2026-10-02' }),
      it_('VIEJO1', { orden: null, added_at: '2026-10-01' }),
      it_('A', { orden: 1, added_at: '2026-11-10' }),
    ])
    expect(f.map(x => x.simbolo)).toEqual(['VIEJO1', 'VIEJO2', 'B', 'A'])
  })
  it('mover antes o después de otro; con algo que no está, nada', () => {
    const l = ['A', 'B', 'C', 'D']
    expect(mover(l, 'D', 'B')).toEqual(['A', 'D', 'B', 'C'])
    expect(mover(l, 'A', 'C', { despues: true })).toEqual(['B', 'C', 'A', 'D'])
    expect(mover(l, 'A', 'A')).toBe(l)
    expect(mover(l, 'Z', 'A')).toBe(l)
  })
})

describe('el renglón que estás mirando y lo que tenés', () => {
  const filas = [it_('GGAL.BA'), it_('AAPL'), it_('AAPL.BA'), it_('BTC-USD')]
  it('el mismo nombre, o el que abre el mismo gráfico (tocaste GGAL.BA y se abrió tu GGAL)', () => {
    expect(filaDelActivo(filas, 'AAPL.BA').simbolo).toBe('AAPL.BA')
    expect(filaDelActivo(filas, 'GGAL').simbolo).toBe('GGAL.BA')
    expect(filaDelActivo(filas, 'BTC').simbolo).toBe('BTC-USD')
    expect(filaDelActivo(filas, 'NVDA')).toBeNull()
  })
  it('lo que tenés se abre con TU lote: con TSLA cargado como CEDEAR, el renglón es el del CEDEAR', () => {
    const conTsla = [it_('TSLA'), it_('TSLA.BA'), it_('GGAL.BA')]
    // Medido en la copia local: abrir TSLA.BA pasa a «TSLA» (tu lote) y se
    // marcaba la TSLA de Nueva York, con «15 acciones» y el precio en dólares.
    const tuLote = { broker: 'IOL', asset: 'TSLA', asset_type: 'CEDEAR', currency: 'ARS', quantity: 15 }
    expect(tipoDelLote(tuLote)).toBe('cedear')
    expect(filaDelActivo(conTsla, 'TSLA', 'cedear').simbolo).toBe('TSLA.BA')
    expect(filaDelActivo(conTsla, 'TSLA', 'eeuu').simbolo).toBe('TSLA')
    // Sin el CEDEAR en la lista, el renglón que abre ese gráfico (el mismo nombre).
    expect(filaDelActivo([it_('TSLA')], 'TSLA', 'cedear').simbolo).toBe('TSLA')
    // Tu GGAL de Schwab es la de Nueva York: la de BYMA de la lista no es la que mirás.
    expect(tipoDelLote({ broker: 'Schwab', asset: 'GGAL', asset_type: 'STOCK', quantity: 3 })).toBe('eeuu')
    expect(filaDelActivo(conTsla, 'GGAL', 'eeuu')).toBeNull()
    expect(tipoDelLote({ broker: 'Binance', asset: 'BTC', quantity: 1 })).toBe('cripto')
  })
  it('el CEDEAR y la acción de EE.UU.: el tipo del lote dice cuál tenés', () => {
    const tenencias = [{ asset: 'AAPL', local: false, tipo: 'CEDEAR' }, { asset: 'GGAL', local: true, tipo: 'ACCION' }]
    expect(loTenes(filas[2], tenencias)).toBe(true)    // AAPL.BA
    expect(loTenes(filas[1], tenencias)).toBe(false)   // AAPL de Nueva York
    expect(loTenes(filas[0], tenencias)).toBe(true)    // GGAL.BA
    expect(loTenes(filas[1], [{ asset: 'AAPL', local: false, tipo: 'STOCK' }])).toBe(true)
  })
})

describe('los números y la ficha corta', () => {
  it('último, variación en plata y en %: decimales según el precio, el menos tipográfico', () => {
    expect(numerosDe(it_('NVDA', { price: 167.51, change: -11.16, change_pct: -6.25 }))).toEqual({ precio: '167,51', cambio: '−11,16', pct: '−6,25%', tono: -1 })
    expect(numerosDe(it_('TSLA.BA', { price: 39960, change: 1460, change_pct: 3.79 }))).toMatchObject({ precio: '39.960', cambio: '+1.460', tono: 1 })
    expect(numerosDe(it_('PEPE', { price: 0.00001234, change: 0, change_pct: 0 }))).toMatchObject({ cambio: '0,0000', tono: 0 })
    expect(numerosDe(filaDe({ symbol: 'KO' }))).toEqual({ precio: '—', cambio: '—', pct: '—', tono: 0 })
  })
  it('la rueda: abierta con la hora de cierre, cerrada con la fecha del precio, cripto todo el día', () => {
    expect(textoDeLaRueda(filaDe({ symbol: 'AAPL', en_horario: true, cierra: '18:00' }))).toEqual({ abierto: true, texto: 'Mercado abierto · cierra a las 18:00 (hora argentina)' })
    expect(textoDeLaRueda(filaDe({ symbol: 'GGAL.BA', en_horario: false, as_of: '2026-11-07' }))).toEqual({ abierto: false, texto: 'Mercado cerrado · precio del cierre del 07/11' })
    expect(textoDeLaRueda(filaDe({ symbol: 'BTC', mercado: 'cripto' })).texto).toBe('Se opera todo el día')
  })
  it('la lectura, con las palabras de la ficha; sin lectura, nada', () => {
    const lectura = { precio: 100, media200: 120, dist_media200: -16.7, tendencia: 'bajista', rsi: 27, ruedas: 400, fecha: '2026-11-10' }
    const l = lecturaCorta({ disponible: true, lectura })
    expect(l.largo).toEqual({ id: 'bajista', texto: 'Largo plazo: bajista' })
    expect(l.impulso.texto).toMatch(/^Impulso \(RSI\): .+ · 27$/)
    expect(lecturaCorta(null)).toBeNull()
    expect(lecturaCorta({ disponible: false })).toBeNull()
  })
  it('«Lo tenés»: cantidad y lo que ganás desde que compraste; con «Ocultar saldos», sin la cantidad', () => {
    expect(textoLoTenes({ qty: 8, pnlPct: 0.224, tipo: 'eeuu', ticker: 'NVDA' })).toBe('8 acciones · +22,4% desde que compraste')
    expect(textoLoTenes({ qty: 1, pnlPct: null, tipo: 'cedear', ticker: 'TSLA' })).toBe('1 CEDEAR')
    expect(textoLoTenes({ qty: 0.05, pnlPct: -0.1, tipo: 'cripto', ticker: 'BTC' })).toBe('0,05 BTC · −10,0% desde que compraste')
    expect(textoLoTenes({ qty: 8, pnlPct: 0.224, tipo: 'eeuu', ticker: 'NVDA', oculto: true })).toBe('+22,4% desde que compraste')
    expect(textoLoTenes({ qty: 0 })).toBeNull()
  })
})

describe('«Cómo se ve» queda en este navegador', () => {
  beforeEach(() => { instalarNavegadorMinimo() })
  it('sin nada guardado: por bandera, como los acomodás, con Var. y la ficha; abierta sin decidir', () => {
    expect(vistaGuardada()).toEqual({ ...VISTA_DE_ENTRADA })
    expect(vistaGuardada().abierta).toBeNull()
  })
  it('lo que se guarda vuelve; lo que no se entiende, no', () => {
    guardarVista({ ...VISTA_DE_ENTRADA, abierta: false, agrupar: 'tipo', orden: 'hoy', verVar: false, plegadas: ['azul'] })
    expect(vistaGuardada()).toMatchObject({ abierta: false, agrupar: 'tipo', orden: 'hoy', verVar: false, verFicha: true, plegadas: ['azul'] })
    localStorage.setItem('rendi_grafico_lista', JSON.stringify({ agrupar: 'cualquiera', orden: 3, abierta: 'si' }))
    expect(vistaGuardada()).toMatchObject({ agrupar: 'bandera', orden: 'tuyo', abierta: null })
    localStorage.setItem('rendi_grafico_lista', '{roto')
    expect(vistaGuardada()).toEqual({ ...VISTA_DE_ENTRADA })
  })
})
