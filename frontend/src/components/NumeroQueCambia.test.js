// Un número tiene que mostrar CÓMO CAMBIÓ después de que el usuario hizo algo
// (cobró un cupón o un dividendo, vendió, depositó, borró un movimiento), y no
// moverse cuando no hizo nada. Pedido de Nico, 2026-10-10.
//
// Estas pruebas montan el componente de verdad (testing/navegadorMinimo.js) y
// el aviso de "se escribió" es el mismo evento que emite utils/api.js en cada
// escritura que sale bien: el camino de la app, no uno armado para la prueba.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from 'vitest'
import { createElement as h, act } from 'react'
import { instalarNavegadorMinimo, montar, texto } from '../testing/navegadorMinimo'

let NumeroQueCambia, textoDeDiferencia, vistos, api, sesion
beforeAll(async () => {
  ;({ sesion } = instalarNavegadorMinimo())
  api = await import('../utils/api')
  vistos = await import('../utils/valoresVistos')
  ;({ default: NumeroQueCambia, textoDeDiferencia } = await import('./NumeroQueCambia'))
})
afterAll(() => { vi.unstubAllGlobals() })

const format = (n) => `US$ ${Number(n).toFixed(2)}`
// Lo que hace la app cuando una escritura sale bien (cobrar, vender, depositar, borrar).
const elUsuarioCambioAlgo = () => act(async () => { window.dispatchEvent(new Event(api.EVENTO_ESCRITURA)) })
const pasa = (ms) => act(async () => { vi.advanceTimersByTime(ms) })
const numero = (props) => h(NumeroQueCambia, { clave: 'prueba:aportado', format, moneda: 'USD', ...props })

let montado
beforeEach(() => { vi.useFakeTimers() })
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  vi.useRealTimers()
  sesion.clear()
  delete globalThis.IntersectionObserver
})

// Ver el número una vez, como en una visita anterior a la pantalla.
async function verlo(value, props = {}) {
  const m = await montar(numero({ value, ...props }))
  await pasa(1500)
  await m.desmontar()
}

describe('lo recordado (utils/valoresVistos)', () => {
  it('sin ningún cambio del usuario no hay "antes" que mostrar', () => {
    vistos.recordarValor('a', 100, 'USD')
    expect(vistos.valorAntesDelCambio('a', 'USD')).toBeNull()
  })

  it('después de una escritura, devuelve lo que valía', async () => {
    vistos.recordarValor('a', 100, 'USD')
    await elUsuarioCambioAlgo()
    expect(vistos.valorAntesDelCambio('a', 'USD')).toBe(100)
  })

  it('el aviso del importador y del chat también cuenta', async () => {
    vistos.recordarValor('a', 100, 'USD')
    await act(async () => { window.dispatchEvent(new Event('rendi:portfolio-changed')) })
    expect(vistos.valorAntesDelCambio('a', 'USD')).toBe(100)
  })

  it('no compara un valor en pesos con el que se vio en dólares', async () => {
    vistos.recordarValor('a', 100, 'USD')
    await elUsuarioCambioAlgo()
    expect(vistos.valorAntesDelCambio('a', 'ARS')).toBeNull()
  })

  it('lo visto hace más de media hora ya no sirve de "antes"', async () => {
    vistos.recordarValor('a', 100, 'USD')
    await elUsuarioCambioAlgo()
    vi.setSystemTime(Date.now() + vistos.CADUCA_MS + 1000)
    expect(vistos.valorAntesDelCambio('a', 'USD')).toBeNull()
  })

  it('es de UNA cuenta: lo de un cliente del asesor no aparece en otro', async () => {
    api.setClientContext({ id: 11, label: 'A' })
    vistos.recordarValor('a', 500000, 'USD')
    api.setClientContext({ id: 22, label: 'B' })
    vistos.recordarValor('a', 21000, 'USD')
    await elUsuarioCambioAlgo()                                  // el cambio fue en B
    expect(vistos.valorAntesDelCambio('a', 'USD')).toBe(21000)
    api.setClientContext({ id: 11, label: 'A' })
    expect(vistos.valorAntesDelCambio('a', 'USD')).toBeNull()    // en A no cambió nada
    api.clearClientContext()
  })

  it('las claves empiezan con rendi_ (las borra el cierre de sesión)', async () => {
    vistos.recordarValor('a', 1, 'USD')
    await elUsuarioCambioAlgo()
    expect([...sesion.keys()].length).toBeGreaterThan(0)
    expect([...sesion.keys()].every(k => k.startsWith('rendi_'))).toBe(true)
  })
})

describe('volver a una pantalla después de un cambio', () => {
  it('arranca en el valor VIEJO, cuenta hasta el nuevo y dice la diferencia', async () => {
    await verlo(5000)
    await elUsuarioCambioAlgo()                                  // p. ej. cobró un dividendo en otra pantalla
    montado = await montar(numero({ value: 5010.33 }))
    expect(texto(montado.contenedor)).toContain('US$ 5000.00')   // no salta al nuevo de entrada
    await pasa(1500)
    const t = texto(montado.contenedor)
    expect(t).toContain('US$ 5010.33')
    expect(t).toContain('+US$ 10.33')
  })

  it('si bajó (se borró un depósito), la diferencia va en negativo', async () => {
    await verlo(5000)
    await elUsuarioCambioAlgo()
    montado = await montar(numero({ value: 4000 }))
    await pasa(1500)
    const t = texto(montado.contenedor)
    expect(t).toContain('US$ 4000.00')
    expect(t).toContain('−US$ 1000.00')
  })

  it('la diferencia se va sola a los pocos segundos; el número queda', async () => {
    await verlo(5000)
    await elUsuarioCambioAlgo()
    montado = await montar(numero({ value: 5010.33 }))
    await pasa(8000)
    const t = texto(montado.contenedor)
    expect(t).toContain('US$ 5010.33')
    expect(t).not.toContain('+US$ 10.33')
  })

  it('se muestra UNA vez: a la vuelta siguiente ya no hay nada que anunciar', async () => {
    await verlo(5000)
    await elUsuarioCambioAlgo()
    await verlo(5010.33)
    montado = await montar(numero({ value: 5010.33 }))
    expect(texto(montado.contenedor)).toBe('US$ 5010.33')
  })

  it('sin cambio del usuario no agrega nada: aparece escrito en su valor', async () => {
    await verlo(5000)
    montado = await montar(numero({ value: 5003 }))              // se movieron los precios, nada más
    expect(texto(montado.contenedor)).toBe('US$ 5003.00')
    await pasa(1500)
    expect(texto(montado.contenedor)).toBe('US$ 5003.00')
  })

  it('la cartera cambió pero ESTE número no: no anuncia nada', async () => {
    await verlo(5000)
    await elUsuarioCambioAlgo()
    montado = await montar(numero({ value: 5000 }))
    await pasa(1500)
    expect(texto(montado.contenedor)).toBe('US$ 5000.00')
  })

  it('mientras los datos no están listos espera en el valor viejo, y no recuerda un total a medias', async () => {
    await verlo(5000)
    await elUsuarioCambioAlgo()
    montado = await montar(numero({ value: 0, listo: false }))   // todavía no llegaron los precios
    await pasa(1500)
    expect(texto(montado.contenedor)).toBe('US$ 5000.00')
    expect(JSON.parse(sesion.get('rendi_valor_visto:propia:prueba:aportado')).valor).toBe(5000)
    await montado.redibujar(numero({ value: 5010.33, listo: true }))
    await pasa(1500)
    const t = texto(montado.contenedor)
    expect(t).toContain('US$ 5010.33')
    expect(t).toContain('+US$ 10.33')
    expect(JSON.parse(sesion.get('rendi_valor_visto:propia:prueba:aportado')).valor).toBeCloseTo(5010.33, 2)
  })

  it('si los datos no llegan nunca, no se queda mostrando lo de antes', async () => {
    await verlo(5000)
    await elUsuarioCambioAlgo()
    montado = await montar(numero({ value: 4200, listo: false }))
    await pasa(13000)     // vence la espera…
    await pasa(1500)      // …y cuenta hasta lo que hay
    expect(texto(montado.contenedor)).toBe('US$ 4200.00')
  })

  it('fuera de la pantalla espera: cuenta recién cuando se lo ve', async () => {
    let avisar
    globalThis.IntersectionObserver = class {
      constructor(fn) { avisar = fn }
      observe() {} disconnect() {}
    }
    // Se vio una vez (entra en pantalla) con 5000.
    const m = await montar(numero({ value: 5000 }))
    await act(async () => { avisar([{ isIntersecting: true, intersectionRatio: 1, intersectionRect: { height: 20 }, rootBounds: { height: 800 } }]) })
    await pasa(1500)
    await m.desmontar()
    await elUsuarioCambioAlgo()
    // Vuelve, pero el número está más abajo del primer pantallazo.
    montado = await montar(numero({ value: 5010.33 }))
    await pasa(3000)
    expect(texto(montado.contenedor)).toBe('US$ 5000.00')
    await act(async () => { avisar([{ isIntersecting: true, intersectionRatio: 1, intersectionRect: { height: 20 }, rootBounds: { height: 800 } }]) })
    await pasa(1500)
    expect(texto(montado.contenedor)).toContain('US$ 5010.33')
    expect(texto(montado.contenedor)).toContain('+US$ 10.33')
  })
})

describe('el cambio pasa en la misma pantalla', () => {
  it('después de una escritura, el valor nuevo se anuncia con su diferencia', async () => {
    montado = await montar(numero({ value: 5000 }))
    await pasa(1500)
    await elUsuarioCambioAlgo()                                  // confirmó un cobro acá mismo
    await montado.redibujar(numero({ value: 5010.33 }))          // la pantalla recargó
    await pasa(1500)
    const t = texto(montado.contenedor)
    expect(t).toContain('US$ 5010.33')
    expect(t).toContain('+US$ 10.33')
  })

  it('si lo que cambió fueron los precios, cuenta pero NO dice que fue tu cambio', async () => {
    montado = await montar(numero({ value: 5000 }))
    await pasa(1500)
    await montado.redibujar(numero({ value: 5003 }))
    await pasa(1500)
    expect(texto(montado.contenedor)).toBe('US$ 5003.00')
  })

  it('cambiar de filtro justo después de borrar no se lee como un cambio de la cartera', async () => {
    montado = await montar(numero({ value: 5000, clave: 'movimientos:Aportado:all|all|all' }))
    await pasa(1500)
    await elUsuarioCambioAlgo()
    await montado.redibujar(numero({ value: 1200, clave: 'movimientos:Aportado:all|Balanz|all' }))
    await pasa(1500)
    expect(texto(montado.contenedor)).toBe('US$ 1200.00')
  })

  it('pasar a pesos no es un cambio de la cartera', async () => {
    montado = await montar(numero({ value: 5000, moneda: 'USD' }))
    await pasa(1500)
    await elUsuarioCambioAlgo()
    await montado.redibujar(numero({ value: 7000000, moneda: 'ARS' }))
    await pasa(1500)
    expect(texto(montado.contenedor)).toBe('US$ 7000000.00')
  })
})

describe('lo que no cambia', () => {
  it('con `desdeCero`, la primera vez cuenta desde 0 (como el total de siempre)', async () => {
    montado = await montar(numero({ value: 5000, desdeCero: true }))
    expect(texto(montado.contenedor)).toBe('US$ 0.00')
    await pasa(1500)
    expect(texto(montado.contenedor)).toBe('US$ 5000.00')
  })

  it('en modo privacidad no se escribe ningún monto, ni el viejo ni la diferencia', async () => {
    await verlo(5000)
    await elUsuarioCambioAlgo()
    montado = await montar(numero({ value: 5010.33, oculto: true }))
    await pasa(1500)
    expect(texto(montado.contenedor)).toBe('••••••')
  })

  it('un dato que no llegó se escribe "—", no un 0 inventado', async () => {
    montado = await montar(numero({ value: null }))
    expect(texto(montado.contenedor)).toBe('—')
  })

  it('un cambio que escrito no se nota (centavos en un número sin centavos) no se anuncia', async () => {
    const sinCentavos = (n) => `US$${Math.round(n)}`
    montado = await montar(numero({ value: 0.01, format: sinCentavos }))
    await pasa(1500)
    await elUsuarioCambioAlgo()
    await montado.redibujar(numero({ value: 0, format: sinCentavos }))
    await pasa(1500)
    expect(texto(montado.contenedor)).toBe('US$0')               // sin "−US$0"
  })

  it('la diferencia no duplica el signo de un formato que ya lo trae', () => {
    const conSigno = (n) => `${n >= 0 ? '+' : '−'}USD ${Math.abs(n).toFixed(2)}`
    expect(textoDeDiferencia(-12.5, conSigno)).toBe('−USD 12.50')
    expect(textoDeDiferencia(12.5, conSigno)).toBe('+USD 12.50')
  })
})
