// La pestaña Cobros montada de verdad (testing/navegadorMinimo.js), con los
// pedidos al servidor simulados en la frontera (utils/api). Lo que se prueba es
// el ARMADO, que las cuentas (utils/cobros.test.js) no ven:
//   · si no llegan tus posiciones, el estimado dice que no se pudo calcular en
//     vez de mostrar US$ 0 como si fuera un dato;
//   · con el almacenamiento del navegador bloqueado, la pestaña igual se dibuja.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto } from '../../testing/navegadorMinimo'

const hoy = '2026-10-22'
const DATOS = {
  hoy, dias_hasta_el_pago: 21,
  cobros: [{ fecha: '2026-05-20', activo: 'GGAL', tipo: 'DIVIDEND', usd: 127.12 }],
  pagos_mixtos: [], anios_previos: [],
}

let respuestas
vi.mock('../../utils/api', () => ({
  api: {
    get: vi.fn((ruta) => {
      const clave = Object.keys(respuestas).find(k => ruta.startsWith(k))
      const r = clave ? respuestas[clave] : []
      return r instanceof Error ? Promise.reject(r) : Promise.resolve(r)
    }),
  },
}))

let CobrosView
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: CobrosView } = await import('./CobrosView'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
})

async function dibujar() {
  montado = await montar(h(CobrosView))
  // Que vuelvan todas las promesas de los pedidos.
  for (let i = 0; i < 5; i++) await montado.redibujar(h(CobrosView))
  return texto(montado.contenedor)
}

function base() {
  return {
    '/cobros': DATOS,
    '/positions': [{ asset: 'GGAL', broker: 'Cocos', quantity: 100, entry_date: '2025-01-10' }],
    '/brokers': [{ id: 1, name: 'Cocos', currency: 'ARS' }],
    '/operations': [],
    '/events/portfolio': { events: [] },
    '/dolar': { mep: { medio: 1500 } },
    '/snapshots': [],
  }
}

describe('la pestaña Cobros', () => {
  it('con todo lo que necesita, muestra lo cobrado y el estimado', async () => {
    respuestas = base()
    const t = await dibujar()
    expect(t).toContain('$127,12 USD')
    expect(t).toContain('Próximos 12 meses (estimado)')
    expect(t).not.toContain('No se pudo calcular')
  })

  it('si no llegan tus posiciones, dice que no pudo calcular el estimado', async () => {
    respuestas = { ...base(), '/positions': new Error('caído') }
    const t = await dibujar()
    expect(t).toContain('$127,12 USD')                       // lo cobrado se ve igual
    expect(t).toContain('No se pudo calcular')
    expect(t).not.toContain('$0,00 USD')                     // nada de un cero como dato
  })

  it('con el almacenamiento bloqueado, la pestaña se dibuja igual', async () => {
    respuestas = base()
    const bloqueado = () => { throw new Error('SecurityError') }
    const getItem = vi.spyOn(localStorage, 'getItem').mockImplementation(bloqueado)
    const setItem = vi.spyOn(localStorage, 'setItem').mockImplementation(bloqueado)
    try {
      const t = await dibujar()
      expect(t).toContain('Por mes')
      expect(t).toContain('$127,12 USD')
    } finally {
      getItem.mockRestore()
      setItem.mockRestore()
    }
  })
})

// «Ocultar saldos» en Cobros: el demo no muestra esta pestaña («no disponible
// en modo demo»), así que la prueba de las pantallas enteras no la ve
// (auditoría a ciegas, 30/10). Acá, montada con el ojito prendido.
describe('la pestaña Cobros con «Ocultar saldos»', () => {
  it('prendido no muestra lo cobrado; apagado sí', async () => {
    const { PrivacyProvider } = await import('../../contexts/PrivacyContext')
    respuestas = base()
    for (const [ojito, ve] of [['0', true], ['1', false]]) {
      localStorage.setItem('rendi_privacy', ojito)
      montado = await montar(h(PrivacyProvider, null, h(CobrosView)))
      for (let i = 0; i < 5; i++) await montado.redibujar(h(PrivacyProvider, null, h(CobrosView)))
      const t = texto(montado.contenedor)
      expect(t.includes('127,12'), `ojito=${ojito}`).toBe(ve)
      await montado.desmontar()
      montado = null
    }
    localStorage.removeItem('rendi_privacy')
  })
})
