import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { createElement as h, useState } from 'react'
import { instalarNavegadorMinimo, montar, enActo, clic, buscarBoton, texto, escribir } from '../testing/navegadorMinimo'
import { tipoDeLaEleccion, avisoDeCambioDeTipo, monedaAlCambiarDeTipo } from '../utils/cambioDeTipo'

// 🔴 «PASÉ DE CEDEAR A ACCIÓN Y SIGUE CON EL PRECIO DEL CEDEAR» (2026-10-20).
//
// Alguien cargó el CEDEAR de IREN cuando había comprado la acción. En «Editar»
// la buscó, la eligió y guardó: cambió el precio de compra y el precio actual
// siguió siendo el del CEDEAR. El CEDEAR y la acción tienen el MISMO código; lo
// único que los separa es el tipo guardado (asset_type), y el buscador devolvía
// sólo el código: el tipo viejo viajaba intacto. En la edición de varios lotes,
// elegir «la otra IREN» ni siquiera habilitaba el botón (no había «cambio»).
//
// Además, dentro de «Editar» la lista del buscador es más ancha que la ventana y
// la etiqueta «Acción US» / «CEDEAR» iba al borde derecho, que quedaba cortado:
// se veían dos «IREN» sin decir cuál era cuál.
//
// Acá se montan los formularios de verdad, se escribe en el buscador y se hace
// click en la fila como en el navegador.

vi.mock('../hooks/useIsMobile', () => ({ useIsMobile: () => false, useAnchoMinimo: () => true, MOBILE_BREAKPOINT_PX: 768 }))

let api, PositionFormModal, EditGroupModal
beforeAll(async () => {
  instalarNavegadorMinimo()
  api = (await import('../utils/api')).api
  vi.spyOn(api, 'get').mockResolvedValue([])
  ;({ PositionFormModal, EditGroupModal } = await import('./Positions'))
})
afterAll(() => { vi.restoreAllMocks() })

const IBKR = { id: 1, name: 'IBKR', currency: 'USD', parent_broker_id: null }
const GALICIA = { id: 2, name: 'Banco Galicia', currency: 'ARS', parent_broker_id: null }
const GALICIA_USD = { id: 3, name: 'Banco Galicia · USD', currency: 'USD', parent_broker_id: 2 }
const BROKERS = [IBKR, GALICIA, GALICIA_USD]

describe('qué tipo y qué aviso sale de lo elegido en el buscador', () => {
  it('la lista de la que salió decide el tipo', () => {
    expect(tipoDeLaEleccion({ categoria: 'stocks' })).toBe('STOCK')
    expect(tipoDeLaEleccion({ categoria: 'cedears' })).toBe('CEDEAR')
    expect(tipoDeLaEleccion({ categoria: 'etfs' })).toBe('ETF')
    // Tipeado a mano o un índice: no dice tipo, queda el que estaba.
    expect(tipoDeLaEleccion(undefined)).toBe(null)
    expect(tipoDeLaEleccion({ categoria: 'indices' })).toBe(null)
  })

  it('de CEDEAR a acción en un broker del exterior: avisa que pasa al precio de Nueva York', () => {
    const a = avisoDeCambioDeTipo({ antes: 'CEDEAR', eleccion: { categoria: 'stocks' }, broker: 'IBKR', brokers: BROKERS })
    expect(a.tono).toBe('info')
    expect(a.texto).toContain('Nueva York')
  })

  it('de acción a CEDEAR: avisa que pasa al precio de Buenos Aires', () => {
    const a = avisoDeCambioDeTipo({ antes: 'STOCK', eleccion: { categoria: 'cedears' }, broker: 'IBKR', brokers: BROKERS })
    expect(a.texto).toContain('Bolsa de Buenos Aires')
  })

  it('en una cuenta argentina (pesos o su pata en dólares) dice que el precio NO cambia', () => {
    for (const broker of ['Banco Galicia', 'Banco Galicia · USD']) {
      const a = avisoDeCambioDeTipo({ antes: 'CEDEAR', eleccion: { categoria: 'stocks' }, broker, brokers: BROKERS })
      expect(a.tono, broker).toBe('aviso')
      expect(a.texto).toContain('Banco Galicia es una cuenta argentina')
    }
  })

  it('elegir lo mismo que ya era no dice nada', () => {
    expect(avisoDeCambioDeTipo({ antes: 'CEDEAR', eleccion: { categoria: 'cedears' }, broker: 'IBKR', brokers: BROKERS })).toBe(null)
    expect(avisoDeCambioDeTipo({ antes: 'CEDEAR', eleccion: null, broker: 'IBKR', brokers: BROKERS })).toBe(null)
  })

  it('una acción de EE.UU. en un broker del exterior se compra en dólares', () => {
    const eleccion = { categoria: 'stocks' }
    expect(monedaAlCambiarDeTipo({ moneda: 'ARS', eleccion, broker: 'IBKR', brokers: BROKERS })).toBe('USD')
    expect(monedaAlCambiarDeTipo({ moneda: 'USD', eleccion, broker: 'IBKR', brokers: BROKERS })).toBe('USD')
    // En la cuenta argentina la moneda es la de la pata: no se toca.
    expect(monedaAlCambiarDeTipo({ moneda: 'ARS', eleccion, broker: 'Banco Galicia', brokers: BROKERS })).toBe('ARS')
    // Elegir un CEDEAR no cambia la moneda.
    expect(monedaAlCambiarDeTipo({ moneda: 'ARS', eleccion: { categoria: 'cedears' }, broker: 'IBKR', brokers: BROKERS })).toBe('ARS')
  })
})

/** El campo del buscador de activos (no el del precio, que está más arriba en el árbol). */
function campoDelBuscador(contenedor) {
  const pila = [contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'INPUT' && String(n.getAttribute('placeholder') || '').startsWith('Buscar')) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}

/** Escribe en el buscador y devuelve la fila de la lista que dice `codigo` y `tipo`. */
async function abrirYBuscar(contenedor, codigo, tipo) {
  const input = campoDelBuscador(contenedor)
  // El campo ya trae el código del lote: como una persona, se borra una letra y
  // se vuelve a escribir (escribir lo mismo que ya dice no es un cambio).
  await escribir(input, codigo.slice(0, -1))
  await escribir(input, codigo)
  const pila = [contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'BUTTON' && texto(n).includes(codigo) && texto(n).includes(tipo)) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}

describe('Editar un lote (PositionFormModal, compu y celular)', () => {
  function montarEdicion(lote, brokers = BROKERS) {
    const guardados = []
    function Pantalla() {
      const [form, setForm] = useState(lote)
      return h(PositionFormModal, {
        mode: 'edit', form, setForm, brokers, selectedBrokerCurrency: 'USD', tcValuacion: 1400,
        onClose: () => {}, onSave: async () => { guardados.push(form) },
      })
    }
    return { montado: montar(h(Pantalla)), guardados }
  }
  const LOTE = {
    id: 7, broker: 'IBKR', asset: 'IREN', is_cash: false, buy_price: '9,5', quantity: '10',
    invested: '95', tc_compra: '', commissions: '', notes: '', price_override: '',
    entry_date: '2026-10-01', asset_type: 'CEDEAR', currency: 'USD',
  }

  it('elegir «IREN · Acción US» guarda el tipo de la acción', async () => {
    const { montado, guardados } = montarEdicion(LOTE)
    const { contenedor } = await montado
    const fila = await abrirYBuscar(contenedor, 'IREN', 'Acción US')
    expect(fila, 'no está la fila de la acción con su etiqueta').toBeTruthy()
    await enActo(async () => clic(contenedor, fila))
    expect(texto(contenedor)).toContain('Pasa de CEDEAR a la acción')
    await enActo(async () => clic(contenedor, buscarBoton(contenedor, 'Guardar')))
    expect(guardados).toHaveLength(1)
    expect(guardados[0].asset).toBe('IREN')
    expect(guardados[0].asset_type).toBe('STOCK')
  })

  it('al revés: de la acción al CEDEAR', async () => {
    const { montado, guardados } = montarEdicion({ ...LOTE, asset_type: 'STOCK' })
    const { contenedor } = await montado
    await enActo(async () => clic(contenedor, await abrirYBuscar(contenedor, 'IREN', 'CEDEAR')))
    await enActo(async () => clic(contenedor, buscarBoton(contenedor, 'Guardar')))
    expect(guardados[0].asset_type).toBe('CEDEAR')
  })

  it('tipear el código sin elegir de la lista no le cambia el tipo', async () => {
    const { montado, guardados } = montarEdicion(LOTE)
    const { contenedor } = await montado
    await escribir(campoDelBuscador(contenedor), 'IRE')
    await escribir(campoDelBuscador(contenedor), 'IREN')
    await enActo(async () => clic(contenedor, buscarBoton(contenedor, 'Guardar')))
    expect(guardados[0].asset_type).toBe('CEDEAR')
  })

  it('un CEDEAR marcado en pesos en un broker del exterior pasa a dólares al elegir la acción', async () => {
    const { montado, guardados } = montarEdicion({ ...LOTE, currency: 'ARS' })
    const { contenedor } = await montado
    await enActo(async () => clic(contenedor, await abrirYBuscar(contenedor, 'IREN', 'Acción US')))
    await enActo(async () => clic(contenedor, buscarBoton(contenedor, 'Guardar')))
    expect(guardados[0].currency).toBe('USD')
  })

  it('en una cuenta argentina avisa que ahí se valúa con el precio de Buenos Aires', async () => {
    const { montado } = montarEdicion({ ...LOTE, broker: 'Banco Galicia', currency: 'ARS' })
    const { contenedor } = await montado
    await enActo(async () => clic(contenedor, await abrirYBuscar(contenedor, 'IREN', 'Acción US')))
    expect(texto(contenedor)).toContain('Banco Galicia es una cuenta argentina')
  })
})

describe('Editar la posición entera (EditGroupModal, compu y celular)', () => {
  const lote = (id, extra = {}) => ({ id, broker: 'IBKR', asset: 'IREN', quantity: 10, invested: 95,
    buy_price: 9.5, entry_date: `2026-10-0${id}`, asset_type: 'CEDEAR', currency: 'USD', ...extra })
  const grupo = (lots) => ({ broker: lots[0].broker, asset: 'IREN', currency: 'USD',
    asset_type: lots[0].asset_type, _lots: lots })

  it('elegir sólo la acción alcanza para aplicar, y viaja el tipo nuevo', async () => {
    const enviados = []
    const { contenedor } = await montar(h(EditGroupModal, {
      group: grupo([lote(1), lote(2)]), ctx: null, brokers: BROKERS,
      onClose: () => {}, onSave: async (c) => { enviados.push(c) } }))
    const aplicar = () => buscarBoton(contenedor, 'Aplicar a 2 lotes')
    expect(aplicar().hasAttribute('disabled')).toBe(true)
    await enActo(async () => clic(contenedor, await abrirYBuscar(contenedor, 'IREN', 'Acción US')))
    expect(aplicar().hasAttribute('disabled')).toBe(false)
    expect(texto(contenedor)).toContain('Pasa de CEDEAR a la acción')
    await enActo(async () => clic(contenedor, aplicar()))
    expect(enviados).toEqual([expect.objectContaining({ new_asset_type: 'STOCK', new_asset: undefined })])
  })

  it('elegir el mismo CEDEAR que ya son no manda ningún cambio de tipo', async () => {
    const { contenedor } = await montar(h(EditGroupModal, {
      group: grupo([lote(1), lote(2)]), ctx: null, brokers: BROKERS,
      onClose: () => {}, onSave: async () => {} }))
    await enActo(async () => clic(contenedor, await abrirYBuscar(contenedor, 'IREN', 'CEDEAR')))
    expect(buscarBoton(contenedor, 'Aplicar a 2 lotes').hasAttribute('disabled')).toBe(true)
  })

  it('si un lote quedó con otro tipo, elegir el del primero también lo iguala', async () => {
    const enviados = []
    const { contenedor } = await montar(h(EditGroupModal, {
      group: grupo([lote(1), lote(2, { asset_type: null })]), ctx: null, brokers: BROKERS,
      onClose: () => {}, onSave: async (c) => { enviados.push(c) } }))
    await enActo(async () => clic(contenedor, await abrirYBuscar(contenedor, 'IREN', 'CEDEAR')))
    await enActo(async () => clic(contenedor, buscarBoton(contenedor, 'Aplicar a 2 lotes')))
    expect(enviados[0].new_asset_type).toBe('CEDEAR')
  })
})
