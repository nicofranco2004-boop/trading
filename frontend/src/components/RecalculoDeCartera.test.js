// El aviso "Recalculando tu cartera" tiene que terminar en el total NUEVO.
//
// Visto en la app el 2026-10-09: después de borrar un dividendo desde
// Movimientos, el aviso decía "US$ 7.997,25 → US$ 7.997,25" mientras el total
// de arriba ya había bajado a US$ 7.987. El cambio de fase cancelaba la cuenta
// recién empezada. Estas pruebas montan el componente de verdad (ver
// testing/navegadorMinimo.js) y miran el número con el que termina.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h, act } from 'react'
import { instalarNavegadorMinimo, montar, texto } from '../testing/navegadorMinimo'

let RecalculoDeCartera, useRecalculoDeCartera, cambio, sesion
beforeAll(async () => {
  ;({ sesion } = instalarNavegadorMinimo())
  RecalculoDeCartera = (await import('./RecalculoDeCartera')).default
  ;({ useRecalculoDeCartera } = await import('../hooks/useRecalculoDeCartera'))
  cambio = await import('../utils/cambioDeCobro')
})
afterAll(() => { vi.unstubAllGlobals() })

const formato = (n) => `US$ ${Number(n).toFixed(2)}`
const KO = { texto: 'dividendo de KO', monto: '+US$ 10,33' }

let montado
afterEach(async () => {
  vi.useRealTimers()
  if (montado) await montado.desmontar()
  montado = null
  sesion.clear()
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

describe('cobro borrado en Movimientos, visto al volver a Cartera', () => {
  function Cartera({ total, listo }) {
    const r = useRecalculoDeCartera({ total, moneda: 'USD', listo })
    return h(RecalculoDeCartera, { cobro: r.cobro, recalculando: r.recalculando, total, formato })
  }

  it('cuenta del último total visto al nuevo, que es MENOR', async () => {
    cambio.recordarTotalVisto(7997.25, 'USD')
    cambio.anotarCambioDeCobro({ texto: 'dividendo de KO', monto: '−US$10,33', deshecho: true })
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
    expect(t).toContain('−US$10,33 sacado')
    // Y queda anotado el total nuevo para la próxima.
    expect(JSON.parse(sesion.get('rendi:ultimo-total-cartera')).total).toBeCloseTo(7986.92, 2)
  })

  it('lo anotado se muestra una sola vez', async () => {
    cambio.anotarCambioDeCobro({ texto: 'dividendo de KO', monto: '−US$10,33', deshecho: true })
    expect(cambio.tomarCambioPendiente('USD')).not.toBeNull()
    expect(cambio.tomarCambioPendiente('USD')).toBeNull()
  })

  it('sin un total visto antes, no inventa de dónde partió', async () => {
    cambio.anotarCambioDeCobro({ texto: 'dividendo de KO', monto: '−US$10,33', deshecho: true })
    montado = await montar(h(Cartera, { total: 0, listo: false }))
    vi.useFakeTimers()
    await montado.redibujar(h(Cartera, { total: 500, listo: true }))
    await pasaLaCuenta()
    const t = texto(montado.contenedor)
    expect(t).toContain('US$ 500.00')
    expect(t).not.toContain('→')
  })
})
