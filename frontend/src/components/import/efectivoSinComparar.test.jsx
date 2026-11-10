// La foto de una fecha pasada, con plata movida después, NO ajusta el efectivo
// (el servidor no sabe cuánto había ese día). La pantalla de revisión lo tiene
// que decir: sin el aviso, la ausencia de un ajuste se lee como «el efectivo
// coincide». Medido el 2026-11-07: antes el ajuste borraba un cobro de $1.000.000.
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { ReconcileStep } from './ImportWizard'

const base = { matched: 1, to_seed: [], over: [], not_in_snapshot: [], no_reconciliable: [],
  cash_ajustes: [], override: {} }

describe('efectivo sin comparar en la revisión de la foto', () => {
  it('con plata posterior a la foto, dice que el efectivo no se toca y por qué', () => {
    const html = renderToStaticMarkup(
      <ReconcileStep data={{ ...base, caja_sin_ajustar: {
        motivo: 'movimientos_posteriores', fecha_foto: '2026-09-05', movimientos: 1,
        hasta: '2026-10-20' } }} decisiones={new Map()} onDecidir={() => {}} />)
    expect(html).toContain('Efectivo sin comparar')
    expect(html).toContain('05/09/26')
    expect(html).toContain('20/10/26')
    expect(html).toContain('no se ajusta')
  })

  it('sin ese caso, el aviso no aparece', () => {
    const html = renderToStaticMarkup(
      <ReconcileStep data={{ ...base, caja_sin_ajustar: null }}
                     decisiones={new Map()} onDecidir={() => {}} />)
    expect(html).not.toContain('Efectivo sin comparar')
  })
})

// 2026-11-10: lo archivado salía como «no lo tenías» y la foto lo recompraba.
// Ahora el servidor lo deja sin comparar con su motivo, y la pantalla lo nombra.
describe('lo archivado en la revisión de la foto', () => {
  it('dice que lo archivaste, no un código interno', () => {
    const html = renderToStaticMarkup(
      <ReconcileStep data={{ ...base, no_reconciliable: [
        { ticker: 'AL30', motivo: 'posiciones_archivadas', rendi_qty_hoy: 0 }] }}
                     decisiones={new Map()} onDecidir={() => {}} />)
    expect(html).toContain('AL30')
    expect(html).toContain('lo archivaste')
    expect(html).not.toContain('posiciones_archivadas')
  })
})
