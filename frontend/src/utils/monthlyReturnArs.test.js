// El retorno EN PESOS tiene que capturar la devaluación. Antes no lo hacía: la
// serie ARS convertía ci/cf/net con el FX del MISMO mes y el FX se cancelaba
// algebraicamente, así que "retorno en pesos" era el retorno en dólares con otra
// etiqueta. De ahí salía el veredicto invertido contra la inflación.
//
// El test que faltaba y que habría cazado esto: dos meses con el MISMO retorno en
// dólares y un FX que cambia entre ellos. Antes daban idéntico; ahora no.
import { describe, it, expect } from 'vitest'
import { monthlyReturnArs } from './insightsModel'

// Retorno USD de referencia (Modified Dietz clásico), para contrastar.
const rUsd = (ci, cf, net) => (cf - ci - net) / (ci + 0.5 * net)

describe('monthlyReturnArs — la devaluación entra como retorno', () => {
  it('EL BUG: con FX constante coincide con el retorno USD', () => {
    // Si el peso no se mueve, rendir en pesos y en dólares es lo mismo. Este es
    // el ÚNICO caso donde los dos números deben coincidir.
    const r = monthlyReturnArs({ ci: 1000, cf: 1100, net: 0, fxPrev: 1000, fx: 1000 })
    expect(r).toBeCloseTo(rUsd(1000, 1100, 0), 12)
  })

  it('EL BUG, al revés: con FX que sube ya NO coincide con el retorno USD', () => {
    // Este es el test que no existía. Antes del fix, esta expectativa fallaba:
    // el FX se cancelaba y daba exactamente rUsd para cualquier fx.
    const r = monthlyReturnArs({ ci: 1000, cf: 1100, net: 0, fxPrev: 1000, fx: 1050 })
    expect(r).not.toBeCloseTo(rUsd(1000, 1100, 0), 6)
    // +10% en dólares con el peso devaluándose 5% = 1,10 × 1,05 − 1 = +15,5%
    expect(r).toBeCloseTo(1.10 * 1.05 - 1, 12)
  })

  it('cartera quieta en dólares y peso que se devalúa 5% ⇒ +5% en pesos', () => {
    const r = monthlyReturnArs({ ci: 1000, cf: 1000, net: 0, fxPrev: 1000, fx: 1050 })
    expect(r).toBeCloseTo(0.05, 12)
  })

  it('cartera quieta en dólares y peso que se APRECIA ⇒ retorno NEGATIVO en pesos', () => {
    // El caso 2024-2026 (carry trade): el peso se apreció en términos reales y
    // una cartera dolarizada quieta PIERDE medida en pesos. Tiene que poder dar
    // negativo — si no, el fix estaría sesgando al alza en vez de a la baja.
    const r = monthlyReturnArs({ ci: 1000, cf: 1000, net: 0, fxPrev: 1050, fx: 1000 })
    expect(r).toBeLessThan(0)
    expect(r).toBeCloseTo(1000 / 1050 - 1, 12)
  })

  it('el retorno en pesos compone: USD × devaluación', () => {
    // La identidad que define la corrección: (1+r_ars) = (1+r_usd)·(fx_k/fx_{k-1})
    const ci = 5000, cf = 5400, fxPrev = 900, fx = 1080
    const r = monthlyReturnArs({ ci, cf, net: 0, fxPrev, fx })
    expect(1 + r).toBeCloseTo((1 + rUsd(ci, cf, 0)) * (fx / fxPrev), 12)
  })
})

describe('monthlyReturnArs — flujos', () => {
  it('los flujos entran al FX de mitad de período (media geométrica)', () => {
    const fxPrev = 1000, fx = 1210, net = 500
    const r = monthlyReturnArs({ ci: 1000, cf: 1600, net, fxPrev, fx })
    const fxMid = Math.sqrt(fxPrev * fx)   // 1100
    const esperado = (1600 * fx - 1000 * fxPrev - net * fxMid) /
                     (1000 * fxPrev + 0.5 * net * fxMid)
    expect(r).toBeCloseTo(esperado, 12)
  })

  it('un depósito puro no genera retorno', () => {
    // Meter plata no es rendir. Con FX quieto, depositar 500 sobre 1000 que
    // terminan en 1500 tiene que dar exactamente 0%.
    const r = monthlyReturnArs({ ci: 1000, cf: 1500, net: 500, fxPrev: 1000, fx: 1000 })
    expect(r).toBeCloseTo(0, 12)
  })

  it('primer mes de un import (ci=0) usa el flujo como denominador', () => {
    const r = monthlyReturnArs({ ci: 0, cf: 1100, net: 1000, fxPrev: 1000, fx: 1000, isImportInitial: true })
    expect(r).toBeCloseTo(0.1, 12)
  })

  it('un retiro grande no rompe el signo', () => {
    const r = monthlyReturnArs({ ci: 1000, cf: 520, net: -500, fxPrev: 1000, fx: 1000 })
    expect(r).toBeCloseTo((520 - 1000 + 500) / (1000 - 250), 12)
  })
})

describe('monthlyReturnArs — bordes', () => {
  it('sin FX devuelve null (no cae al retorno USD)', () => {
    // Caer al retorno USD sería reintroducir el bug en silencio.
    expect(monthlyReturnArs({ ci: 1000, cf: 1100, net: 0, fxPrev: 0, fx: 1000 })).toBeNull()
    expect(monthlyReturnArs({ ci: 1000, cf: 1100, net: 0, fxPrev: 1000, fx: null })).toBeNull()
    expect(monthlyReturnArs({ ci: 1000, cf: 1100, net: 0 })).toBeNull()
  })

  it('denominador no positivo devuelve 0, no NaN ni Infinity', () => {
    const r = monthlyReturnArs({ ci: 0, cf: 100, net: 0, fxPrev: 1000, fx: 1000 })
    expect(r).toBe(0)
  })

  it('pierde como mucho el 100%: piso en −99%', () => {
    const r = monthlyReturnArs({ ci: 1000, cf: 0, net: 0, fxPrev: 1000, fx: 1 })
    expect(r).toBe(-0.99)
  })

  it('NO tiene techo: un mes de +300% pasa entero', () => {
    // El techo de +50% que había inline truncaba el retorno en una pantalla y no
    // en otra — parte de la desalineación que este trabajo viene a cerrar.
    const r = monthlyReturnArs({ ci: 1000, cf: 4000, net: 0, fxPrev: 1000, fx: 1000 })
    expect(r).toBeCloseTo(3, 12)
  })
})

describe('la cadena completa — el escenario que se midió en producción', () => {
  it('4 meses al +1% USD con el blue subiendo 5%/mes ya NO da el retorno USD', () => {
    // Reproduce la simulación del audit: antes daba TWR_ARS == TWR_USD == −1,8277%
    // (diferencia 7e-18). El TWR en pesos correcto es muy distinto.
    const meses = [0, 1, 2, 3]
    let cumUsd = 1, cumArs = 1
    let valor = 1000
    let fxPrev = 1000
    for (const _ of meses) {
      const ci = valor
      const cf = valor * 1.01
      const fx = fxPrev * 1.05
      cumUsd *= 1 + rUsd(ci, cf, 0)
      cumArs *= 1 + monthlyReturnArs({ ci, cf, net: 0, fxPrev, fx })
      valor = cf
      fxPrev = fx
    }
    expect(cumUsd - 1).toBeCloseTo(Math.pow(1.01, 4) - 1, 10)
    // En pesos: (1,01 × 1,05)^4 − 1 ≈ +27,7%. Antes daba +4,06% (el de dólares).
    expect(cumArs - 1).toBeCloseTo(Math.pow(1.01 * 1.05, 4) - 1, 10)
    expect(cumArs).toBeGreaterThan(cumUsd)
  })
})
