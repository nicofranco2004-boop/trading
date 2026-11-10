// El demo y la lista al costado del gráfico: el visitante puede poner banderas,
// nombrarlas y ordenar su lista, y queda en SU navegador (el overlay del demo),
// con la misma forma que contesta el servidor (main.watchlist_list).
import { describe, it, expect, beforeEach } from 'vitest'
import { instalarNavegadorMinimo } from '../testing/navegadorMinimo'
import { handleDemoRequest } from './demo.js'
import { BANDERAS } from './listaDelGrafico'

beforeEach(() => { instalarNavegadorMinimo() })

const lista = () => handleDemoRequest('GET', '/watchlist')

describe('el demo guarda las banderas del visitante', () => {
  it('GET /watchlist trae las siete banderas, en el orden de la pantalla, sin nombre', () => {
    const r = lista()
    expect(r.banderas.map(b => b.id)).toEqual(BANDERAS.map(b => b.id))
    expect(r.banderas.every(b => b.nombre === null)).toBe(true)
    expect(r.items.length).toBeGreaterThan(0)
  })

  it('agregar con bandera, cambiarla, nombrarla y ordenar: todo vuelve en el GET', () => {
    handleDemoRequest('POST', '/watchlist', { symbol: 'AAPL.BA', bandera: 'naranja' })
    let aapl = lista().items.find(i => i.symbol === 'AAPL.BA')
    expect(aapl.bandera).toBe('naranja')
    // Va al final de «como los acomodás».
    expect(aapl.orden).toBe(Math.max(...lista().items.map(i => i.orden ?? -1)))

    handleDemoRequest('PATCH', '/watchlist/AAPL.BA', { bandera: 'azul' })
    aapl = lista().items.find(i => i.symbol === 'AAPL.BA')
    expect(aapl.bandera).toBe('azul')
    handleDemoRequest('PATCH', '/watchlist/AAPL.BA', { bandera: 'dorada' })
    expect(lista().items.find(i => i.symbol === 'AAPL.BA').bandera).toBeNull()

    handleDemoRequest('PUT', '/watchlist/banderas/azul', { nombre: '  Para   comprar ' })
    expect(lista().banderas.find(b => b.id === 'azul').nombre).toBe('Para comprar')
    handleDemoRequest('PUT', '/watchlist/banderas/azul', { nombre: '' })
    expect(lista().banderas.find(b => b.id === 'azul').nombre).toBeNull()

    const simbolos = lista().items.map(i => i.symbol).reverse()
    handleDemoRequest('PUT', '/watchlist/orden', { simbolos })
    const lugar = Object.fromEntries(lista().items.map(i => [i.symbol, i.orden]))
    expect(simbolos.map(s => lugar[s])).toEqual(simbolos.map((_, i) => i))
  })

  it('una bandera que no existe no se nombra', () => {
    const r = handleDemoRequest('PUT', '/watchlist/banderas/dorada', { nombre: 'x' })
    expect(r.__demoBlocked).toBe(true)
  })
})
