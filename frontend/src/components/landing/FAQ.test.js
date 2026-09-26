import { describe, it, expect } from 'vitest'
import { FAQS } from './FAQ.jsx'
import {
  TRIAL_TOTAL_DAYS, TRIAL_PRO_DAYS, TRIAL_PLUS_DAYS,
} from '../../data/planCatalog'

// La FAQ de la home se lee en la página Y se publica como JSON-LD, que es lo
// que Google muestra en los resultados. Las dos salen del mismo array `FAQS`,
// así que lo que se prueba acá es exactamente lo que se publica.
//
// Existe por un caso concreto: el 22/09/2026 se sacó el plan gratis para quien
// se registra, se arregló la home, y la FAQ —tres secciones más abajo— siguió
// diciendo "El plan Free es gratis para siempre ... El Free no caduca".
const todo = FAQS.map(f => `${f.q}\n${f.a}`).join('\n\n')
const respuestaDe = (patron) => FAQS.find(f => patron.test(f.q))

describe('la FAQ no ofrece un plan que ya no existe', () => {
  it('no promete un plan gratis', () => {
    expect(todo).not.toMatch(/plan free/i)
    expect(todo).not.toMatch(/gratis para siempre|para siempre/i)
    expect(todo).not.toMatch(/no caduca/i)
  })

  it('no le dice a quien llega por la home que su cuenta "vuelve a Free"', () => {
    // Quien se registra hoy no tiene un Free al que volver: queda en pausa.
    expect(todo).not.toMatch(/vuelve a free/i)
    const cancelar = respuestaDe(/cancelar/i)
    expect(cancelar, 'falta la pregunta de cancelar').toBeTruthy()
    expect(cancelar.a).toMatch(/en pausa/)
  })

  it('cuenta la prueba con los días de verdad', () => {
    const costo = respuestaDe(/gratis/i)
    expect(costo, 'falta la pregunta del costo').toBeTruthy()
    // Los días salen de planCatalog.js, que el backend vigila contra
    // billing/trial.py (test_promesas_vs_producto.py).
    expect(costo.a).toContain(`${TRIAL_TOTAL_DAYS} días gratis`)
    expect(costo.a).toContain(`${TRIAL_PRO_DAYS} días usás Rendi Pro`)
    expect(costo.a).toContain(`los ${TRIAL_PLUS_DAYS} siguientes, Rendi Plus`)
    expect(costo.a).toMatch(/sin tarjeta/i)
  })

  it('usa el nombre de hoy de la IA', () => {
    expect(todo).not.toMatch(/coach ia/i)
    expect(todo).toMatch(/Rendi AI/)
  })

  it('no ata la respuesta a una versión del modelo', () => {
    // Decía "Claude Haiku 4.5" cuando el chat ya usaba Sonnet 5.
    expect(todo).not.toMatch(/haiku|sonnet|opus/i)
  })

  it('no quedó ningún número sin resolver', () => {
    // Los cupos se buscan en el catálogo por su etiqueta: si alguien la
    // renombra, acá aparecería "undefined consultas por semana".
    expect(todo).not.toMatch(/undefined|NaN|null/)
  })
})
