// El vigía de `key` repetidos (testing/vigilarClaves.js) tiene que ver el aviso
// de React, y sólo ése.
import { describe, it, expect, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar } from './navegadorMinimo'
import { clavesRepetidas } from './vigilarClaves'

let montado
afterEach(async () => { await montado?.desmontar?.(); montado = null })

describe('el vigía de key repetidos', () => {
  it('ve dos hermanos con el mismo key (el renglón y la prueba de Backtesting, 05/11)', async () => {
    instalarNavegadorMinimo()
    const Renglon = () => h('p', null, 'renglón')
    const Prueba = () => h('p', null, 'prueba')
    montado = await montar(h('div', null, h(Renglon, { key: 'GGAL' }), h('span'), h(Prueba, { key: 'GGAL' })))
    const vistos = clavesRepetidas()
    expect(vistos).toHaveLength(1)
    expect(vistos[0]).toMatch(/^key «GGAL»/)
  })

  it('con un key propio cada uno no dice nada, y otros errores de la consola no cuentan', async () => {
    instalarNavegadorMinimo()
    const Renglon = () => h('p', null, 'renglón')
    const Prueba = () => h('p', null, 'prueba')
    montado = await montar(h('div', null, h(Renglon, { key: 'renglon:GGAL' }), h(Prueba, { key: 'prueba:GGAL' })))
    const antes = console.error
    console.error = () => {}
    try { console.error('Warning: otra cosa') } finally { console.error = antes }
    expect(clavesRepetidas()).toEqual([])
  })
})
