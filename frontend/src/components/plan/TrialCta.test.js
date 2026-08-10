// Cuándo se ofrece el trial y qué se le avisa al usuario.
//
// La regla que no se puede romper: el botón sale SOLO si el backend dice
// can_start. Nada de recalcular elegibilidad en el front — así es como se
// terminan mostrando botones que fallan al apretarlos.
import { describe, it, expect } from 'vitest'
import { canOfferTrial, trialNotice, trialDaysLabel } from './TrialCta'

describe('canOfferTrial — cuándo se muestra el botón', () => {
  it('se ofrece a quien nunca lo usó', () => {
    expect(canOfferTrial({ can_start: true, used: false, active: false })).toBe(true)
  })

  it('NO se ofrece mientras el trial corre', () => {
    expect(canOfferTrial({ can_start: false, used: true, active: true, stage: 'pro' })).toBe(false)
  })

  it('NO vuelve a ofrecerse cuando terminó', () => {
    expect(canOfferTrial({ can_start: false, used: true, active: false })).toBe(false)
  })

  it('NO se ofrece a quien ya paga', () => {
    expect(canOfferTrial({ can_start: false, reason: 'already_paying' })).toBe(false)
  })

  it('no explota si el backend no mandó nada (asesor mirando a un cliente)', () => {
    expect(canOfferTrial(undefined)).toBe(false)
    expect(canOfferTrial(null)).toBe(false)
    expect(canOfferTrial({})).toBe(false)
  })
})

describe('trialNotice — el aviso del banner', () => {
  it('avisa la víspera del cambio a Plus, que es el aviso que convierte', () => {
    const t = { active: true, stage: 'pro', days_left: 9, days_to_switch: 1 }
    expect(trialNotice(t)).toMatch(/Mañana pasás a Plus/)
  })

  it('el aviso de la víspera gana sobre el de "quedan pocos días"', () => {
    // Caso raro pero posible si alguien cambia los parámetros: primero se
    // avisa lo inminente, no lo lejano.
    const t = { active: true, stage: 'pro', days_left: 2, days_to_switch: 1 }
    expect(trialNotice(t)).toMatch(/Mañana pasás a Plus/)
  })

  it('avisa cuando se está por terminar todo', () => {
    const t = { active: true, stage: 'plus', days_left: 2, days_to_switch: null }
    expect(trialNotice(t)).toMatch(/quedan 2 días de prueba/)
  })

  it('el último día se dice en singular', () => {
    expect(trialNotice({ active: true, stage: 'plus', days_left: 1 }))
      .toMatch(/queda 1 día de prueba/)
  })

  it('a mitad del trial NO mete un aviso de urgencia', () => {
    expect(trialNotice({ active: true, stage: 'plus', days_left: 6 })).toBeNull()
    expect(trialNotice({ active: true, stage: 'pro', days_left: 12, days_to_switch: 4 })).toBeNull()
  })

  it('sin trial activo no hay aviso', () => {
    expect(trialNotice({ active: false, can_start: true })).toBeNull()
    expect(trialNotice(null)).toBeNull()
  })
})

describe('trialDaysLabel', () => {
  it('plural, singular y ausente', () => {
    expect(trialDaysLabel(12)).toBe('12 días restantes')
    expect(trialDaysLabel(1)).toBe('último día')
    expect(trialDaysLabel(null)).toBeNull()
    expect(trialDaysLabel(undefined)).toBeNull()
  })

  it('el día 0 no dice "0 días restantes"', () => {
    // El trial todavía está activo pero le queda menos de un día.
    expect(trialDaysLabel(0)).toBe('0 días restantes')
  })
})
