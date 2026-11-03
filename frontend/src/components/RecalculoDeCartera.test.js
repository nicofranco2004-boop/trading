// El aviso "Recalculando tu cartera" tiene que terminar en el total NUEVO.
//
// Visto en la app el 2026-10-09: después de borrar un dividendo desde
// Movimientos, el aviso decía "US$ 7.997,25 → US$ 7.997,25" mientras el total
// de arriba ya había bajado a US$ 7.987. El cambio de fase cancelaba la cuenta
// recién empezada. Estas pruebas montan el componente de verdad (ver
// testing/navegadorMinimo.js) y miran el número con el que termina.
import { describe, it, expect, vi, beforeAll, afterAll, beforeEach, afterEach } from 'vitest'
import { createElement as h, act } from 'react'
import { instalarNavegadorMinimo, montar, texto } from '../testing/navegadorMinimo'

let RecalculoDeCartera, useRecalculoDeCartera, cambio, sesion, api
beforeAll(async () => {
  dueno = await import('../utils/duenoDeLaPestana')
  ;({ sesion } = instalarNavegadorMinimo())
  RecalculoDeCartera = (await import('./RecalculoDeCartera')).default
  ;({ useRecalculoDeCartera } = await import('../hooks/useRecalculoDeCartera'))
  cambio = await import('../utils/cambioDeMovimiento')
  api = await import('../utils/api')
})
afterAll(() => { vi.unstubAllGlobals() })

const formato = (n) => `US$ ${Number(n).toFixed(2)}`
const KO = { texto: 'dividendo de KO', monto: '+US$ 10,33' }

let montado
// El dueño de los datos: el de la pestaña en este momento, como una pantalla
// recién abierta (utils/duenoDeLaPestana.useDuenoDeLosDatos).
const D = () => dueno.duenoDeLaPestana()
let dueno
// Ana logueada: lo anotado es de la persona y de la cuenta (utils/duenoDeLaPestana).
beforeEach(() => { localStorage.setItem('rendi_user', JSON.stringify({ email: 'ana@prueba.test' })) })
afterEach(async () => {
  vi.useRealTimers()
  if (montado) await montado.desmontar()
  montado = null
  sesion.clear()
  localStorage.clear()
})
const aviso = (props) => h(RecalculoDeCartera, { formato, ...props })
// Deja pasar la cuenta (900 ms + el arranque) con el reloj falso.
const pasaLaCuenta = () => act(async () => { vi.advanceTimersByTime(1500) })

describe('cobro anotado en Cartera', () => {
  it('mientras recarga dice "Recalculando"; después cuenta hasta el total nuevo', async () => {
    montado = await montar(aviso({ cobro: null, recalculando: false, total: 7997.25 }))
    vi.useFakeTimers()
    await montado.redibujar(aviso({ cobro: { ...KO, id: 1 }, recalculando: true, total: 7997.25 }))
    expect(texto(montado.contenedor)).toContain('Recalculando tu cartera')
    await montado.redibujar(aviso({ cobro: { ...KO, id: 1 }, recalculando: false, total: 8007.58 }))
    await pasaLaCuenta()
    const t = texto(montado.contenedor)
    expect(t).toContain('US$ 7997.25 → ')
    expect(t).toContain('US$ 8007.58')
    expect(t).toContain('+US$ 10,33 anotado')
  })

  it('si el total vuelve a cambiar mientras se ve, sigue hasta el último', async () => {
    montado = await montar(aviso({ cobro: null, recalculando: false, total: 100 }))
    vi.useFakeTimers()
    await montado.redibujar(aviso({ cobro: { ...KO, id: 2 }, recalculando: true, total: 100 }))
    await montado.redibujar(aviso({ cobro: { ...KO, id: 2 }, recalculando: false, total: 100 }))
    await montado.redibujar(aviso({ cobro: { ...KO, id: 2 }, recalculando: false, total: 110 }))
    await pasaLaCuenta()
    expect(texto(montado.contenedor)).toContain('US$ 110.00')
  })
})

describe('borrado en Movimientos, visto en la próxima pantalla con total', () => {
  function Cartera({ total, listo, pantalla = 'cartera' }) {
    const r = useRecalculoDeCartera({ total, moneda: 'USD', listo, pantalla })
    return h(RecalculoDeCartera, { cobro: r.cobro, recalculando: r.recalculando, total, formato })
  }

  it('cuenta del último total visto al nuevo, que es MENOR', async () => {
    cambio.recordarTotalVisto(7997.25, 'USD', 'cartera', D())
    cambio.anotarCambioDeMovimiento({ texto: 'dividendo de KO', monto: 'US$10,33', deshecho: true }, D())
    // Al entrar todavía no llegaron posiciones ni precios.
    montado = await montar(h(Cartera, { total: 0, listo: false }))
    vi.useFakeTimers()
    expect(texto(montado.contenedor)).toContain('Recalculando tu cartera')
    expect(texto(montado.contenedor)).toContain('Sacando el dividendo de KO')
    await montado.redibujar(h(Cartera, { total: 7986.92, listo: true }))
    await pasaLaCuenta()
    const t = texto(montado.contenedor)
    expect(t).toContain('sin el dividendo de KO')
    expect(t).toContain('US$ 7997.25 → ')
    expect(t).toContain('US$ 7986.92')
    expect(t).toContain('Borrado: US$10,33')
    // Y queda anotado el total nuevo para la próxima.
    expect(JSON.parse(sesion.get('rendi_ultimo_total:ana@prueba.test|propia:cartera')).total).toBeCloseTo(7986.92, 2)
  })

  it('lo anotado se muestra una sola vez', async () => {
    cambio.anotarCambioDeMovimiento({ texto: 'dividendo de KO', monto: 'US$10,33', deshecho: true }, D())
    expect(cambio.tomarCambioPendiente('USD', 'cartera', D())).not.toBeNull()
    expect(cambio.tomarCambioPendiente('USD', 'dashboard', D())).toBeNull()
  })

  it('sin un total visto antes, no inventa de dónde partió', async () => {
    cambio.anotarCambioDeMovimiento({ texto: 'dividendo de KO', monto: 'US$10,33', deshecho: true }, D())
    montado = await montar(h(Cartera, { total: 0, listo: false }))
    vi.useFakeTimers()
    await montado.redibujar(h(Cartera, { total: 500, listo: true }))
    await pasaLaCuenta()
    const t = texto(montado.contenedor)
    expect(t).toContain('US$ 500.00')
    expect(t).not.toContain('→')
  })

  it('un depósito borrado se ve en el Dashboard desde el total que se vio AHÍ', async () => {
    cambio.recordarTotalVisto(9000, 'USD', 'cartera', D())
    cambio.recordarTotalVisto(8000, 'USD', 'dashboard', D())
    cambio.anotarCambioDeMovimiento({ texto: 'depósito', monto: 'US$1.000,00', deshecho: true }, D())
    montado = await montar(h(Cartera, { total: 0, listo: false, pantalla: 'dashboard' }))
    vi.useFakeTimers()
    await montado.redibujar(h(Cartera, { total: 7000, listo: true, pantalla: 'dashboard' }))
    await pasaLaCuenta()
    const t = texto(montado.contenedor)
    expect(t).toContain('sin el depósito')
    expect(t).toContain('US$ 8000.00 → ')
    expect(t).toContain('US$ 7000.00')
    expect(t).toContain('Borrado: US$1.000,00')
  })

  it('"la venta": el artículo viene con el cambio', async () => {
    cambio.recordarTotalVisto(500, 'USD', 'cartera', D())
    cambio.anotarCambioDeMovimiento({ texto: 'venta de AAPL', articulo: 'la', deshecho: true }, D())
    montado = await montar(h(Cartera, { total: 0, listo: false }))
    expect(texto(montado.contenedor)).toContain('Sacando la venta de AAPL')
  })

  it('es de UNA cuenta: lo de un cliente del asesor no aparece en otro', async () => {
    api.setClientContext({ id: 11, label: 'A' })
    cambio.recordarTotalVisto(500000, 'USD', 'cartera', D())
    api.setClientContext({ id: 22, label: 'B' })
    cambio.recordarTotalVisto(21000, 'USD', 'cartera', D())
    cambio.anotarCambioDeMovimiento({ texto: 'depósito', monto: 'US$1.000,00', deshecho: true }, D())
    api.setClientContext({ id: 11, label: 'A' })
    expect(cambio.tomarCambioPendiente('USD', 'cartera', D())).toBeNull()   // en A no se borró nada
    api.setClientContext({ id: 22, label: 'B' })
    const p = cambio.tomarCambioPendiente('USD', 'cartera', D())
    expect(p.antes).toBe(21000)                                          // el de B, no los 500.000 de A
    api.clearClientContext()
  })

  it('es de UNA persona: si a Ana se le vence la sesión y entra Bruno, no ve el total de Ana (30/10)', () => {
    cambio.recordarTotalVisto(500000, 'USD', 'cartera', D())
    cambio.anotarCambioDeMovimiento({ texto: 'depósito', monto: 'US$1.000,00', deshecho: true }, D())
    localStorage.removeItem('rendi_user')                                // lo que hace api.js con un 401
    localStorage.setItem('rendi_user', JSON.stringify({ email: 'bruno@prueba.test' }))
    expect(cambio.tomarCambioPendiente('USD', 'cartera', D())).toBeNull()      // ni el cambio ni el total de Ana
  })

  it('las claves empiezan con rendi_ (las borra el cierre de sesión)', () => {
    cambio.recordarTotalVisto(1, 'USD', 'cartera', D())
    cambio.anotarCambioDeMovimiento({ texto: 'depósito' }, D())
    expect([...sesion.keys()].every(k => k.startsWith('rendi_'))).toBe(true)
  })

  it('varios cambios antes de volver: un resumen, sin el monto del último', () => {
    cambio.anotarCambioDeMovimiento({ texto: 'depósito', monto: 'US$1.000,00', deshecho: true }, D())
    cambio.anotarCambioDeMovimiento({ texto: 'depósito', monto: 'US$500,00', deshecho: true }, D())
    const p = cambio.tomarCambioPendiente('USD', 'cartera', D())
    expect(p.varios).toBe(true)
    expect(p.texto).toBe('2 cambios en Movimientos')
    expect(p.monto).toBeNull()
  })

  it('borrar y deshacer lo mismo se cancela: no hay aviso', () => {
    cambio.anotarCambioDeMovimiento({ texto: 'venta de AAPL', articulo: 'la', deshecho: true }, D())
    cambio.anotarCambioDeMovimiento({ texto: 'venta de AAPL', articulo: 'la', deshecho: false }, D())
    expect(cambio.tomarCambioPendiente('USD', 'cartera', D())).toBeNull()
  })

  it('el aviso no se queda en "Recalculando…" para siempre', async () => {
    cambio.anotarCambioDeMovimiento({ texto: 'depósito', monto: 'US$1.000,00', deshecho: true }, D())
    // El reloj simulado ANTES de montar: el tope se arma al entrar en "Recalculando".
    vi.useFakeTimers()
    montado = await montar(h(Cartera, { total: 0, listo: false }))
    expect(texto(montado.contenedor)).toContain('Recalculando')
    await act(async () => { vi.advanceTimersByTime(25000) })
    expect(texto(montado.contenedor)).not.toContain('Recalculando')
  })
})
