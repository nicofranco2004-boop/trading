// El renglón de contexto del bono en la tabla de la cartera.
//
// POR QUÉ ESTE TEST
// ─────────────────
// Este renglón es lo único que quedó, a la vista, de la card grande que el bono
// tenía en la zona "Renta Fija". Si devuelve null donde antes había una card, el
// bono queda indistinguible de una acción y se perdió información en la mudanza.
//
// Y el caso al revés: un monto calculado acá saldría MAL para los bonos CER,
// porque el ajuste depende de una serie que esta función no recibe y el cálculo
// caería a factor 1,00 (el mismo defecto que [[project_cer_via_uva]]). Por eso
// sólo se afirman FECHAS, y este test lo fija: si alguien agrega un número, cae.
import { describe, it, expect } from 'vitest'
import { lineaDelBono, fechaCorta } from './lineaDelBono.js'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
const SRC2 = join(dirname(fileURLToPath(import.meta.url)), '..')

describe('lineaDelBono', () => {
  it('un bono dice cuándo vence', () => {
    const linea = lineaDelBono({ asset: 'AL30', quantity: 100 }, '2026-01-01')
    expect(linea).toMatch(/^vence /)
  })

  it('si le queda algún pago, también dice cuándo cobra', () => {
    const linea = lineaDelBono({ asset: 'AL30', quantity: 100 }, '2026-01-01')
    expect(linea).toMatch(/ · cobrás /)
  })

  it('si el único pago que queda ES el vencimiento, no repite la fecha dos veces', () => {
    // TX26 vence el 09/11/26 y ese día paga todo: "vence 09 nov 26 · cobrás 09
    // nov 26" se lee como un error de la pantalla, no como información.
    // Desde septiembre de 2026 ya no le queda ningún pago intermedio.
    const linea = lineaDelBono({ asset: 'TX26', quantity: 1000 }, '2026-09-22')
    expect(linea).toBe('vence 09 nov 26')
  })

  it('pasado el vencimiento queda sólo el vencimiento, sin inventar un cobro', () => {
    const linea = lineaDelBono({ asset: 'AL30', quantity: 100 }, '2099-01-01')
    expect(linea).toMatch(/^vence /)
    expect(linea).not.toMatch(/cobrás/)
  })

  it('no afirma ningún MONTO: el ajuste CER no llega hasta acá', () => {
    // Sin la serie de CER, cualquier monto saldría con ajuste 1,00 — correcto
    // de forma y equivocado de número. Sólo fechas.
    const linea = lineaDelBono({ asset: 'TX26', quantity: 1000 }, '2026-01-01') || ''
    expect(linea).not.toMatch(/US\$|\$|ARS|USD/)
  })

  it('una acción, un CEDEAR o el efectivo no tienen renglón de bono', () => {
    expect(lineaDelBono({ asset: 'AAPL', quantity: 5 }, '2026-01-01')).toBeNull()
    expect(lineaDelBono({ asset: 'AL30', quantity: 5, is_cash: true }, '2026-01-01')).toBeNull()
    expect(lineaDelBono(null)).toBeNull()
  })

  it('la fecha se escribe como se lee en Argentina, no como MM-DD', () => {
    expect(fechaCorta('2027-01-09')).toBe('09 ene 27')
  })
})

describe('en la lista de celular entra un solo dato', () => {
  it('el renglón compacto dice cuándo cobrás, que es lo accionable', () => {
    expect(lineaDelBono({ asset: 'AL30', quantity: 100 }, '2026-09-22', { compacta: true }))
      .toMatch(/^cobrás /)
  })

  it('y entra en el ancla de la fila, que recorta a los ~18 caracteres', () => {
    const linea = lineaDelBono({ asset: 'AL30', quantity: 100 }, '2026-09-22', { compacta: true })
    expect(linea.length).toBeLessThanOrEqual(18)
  })

  it('sin pagos por delante, el compacto cae al vencimiento', () => {
    expect(lineaDelBono({ asset: 'AL30', quantity: 100 }, '2099-01-01', { compacta: true }))
      .toMatch(/^vence /)
  })
})

describe('el renglón del bono no tapa lo que la fila ya decía', () => {
  it('en celular, una fila agrupada conserva su "N lotes"', () => {
    // El "N lotes" es el ÚNICO aviso, en celular, de que esa fila junta varias
    // compras: escritorio tiene un botón aparte, la lista no. Si el renglón del
    // bono lo pisa, un AL30 comprado dos veces se lee como una compra sola.
    const src = readFileSync(join(SRC2, 'pages/PositionsMobile.jsx'), 'utf8')
    const m = src.match(/const delBono = [^\n]*\n?[^\n]*\n?[^\n]*/)
    expect(m, 'no se encontró el cálculo del renglón del bono').toBeTruthy()
    expect(m[0]).toMatch(/_isAgg/)
    expect(m[0]).toMatch(/_multiBroker/)
    expect(m[0]).toMatch(/_isLot/)
  })
})
