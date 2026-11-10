// El recuadro «Regalar días a todos» de /admin. Las claves de la vista previa
// son las que arma `admin_billing_regalo_masivo` en backend/main.py, y las fija
// backend/tests/test_regalo_masivo.py: si el servidor cambia una, se pone rojo
// allá.
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { regalarEnTandas, VistaPreviaRegalo } from './Admin'

const cuentas = (n) => Array.from({ length: n }, (_, i) => ({ id: i + 1 }))

describe('regalar de a tandas', () => {
  it('manda todas las cuentas que se ven, de a `lote`, y suma lo que contesta el servidor', async () => {
    const pedidos = []
    const total = await regalarEnTandas({
      cuentas: cuentas(120), dias: 5, lote: 50,
      pedir: async (cuerpo) => {
        pedidos.push(cuerpo)
        return { regaladas: cuerpo.ids.slice(1), salteadas: cuerpo.ids.slice(0, 1), errores: 0 }
      },
    })
    expect(pedidos.map(p => p.ids.length)).toEqual([50, 50, 20])
    expect(pedidos.flatMap(p => p.ids)).toEqual(cuentas(120).map(c => c.id))
    expect(pedidos.every(p => p.confirm === true && p.days === 5)).toBe(true)
    expect(total).toEqual({ regaladas: 117, salteadas: 3, errores: 0, corte: null })
  })

  it('si se corta a mitad, para ahí y devuelve lo hecho con el motivo', async () => {
    let n = 0
    const total = await regalarEnTandas({
      cuentas: cuentas(120), dias: 5, lote: 50,
      pedir: async (cuerpo) => {
        if (++n === 2) throw new Error('se cayó la red')
        return { regaladas: cuerpo.ids, salteadas: [], errores: 0 }
      },
    })
    expect(n).toBe(2)   // la tercera tanda no salió
    expect(total).toEqual({ regaladas: 50, salteadas: 0, errores: 0, corte: 'se cayó la red' })
  })
})

describe('la vista previa', () => {
  const texto = (preview) => renderToStaticMarkup(<VistaPreviaRegalo preview={preview} />)
    .replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

  it('dice cuántas cuentas reciben, por grupo, también los que dan 0, y quiénes quedan afuera', () => {
    const t = texto({
      por_grupo: { prueba: 3, sin_plan: 40 },
      por_motivo: { paga: 2, prueba_sin_usar: 1 },
      excluidas: [
        { id: 7, email: 'paga1@ejemplo.com', motivo: 'paga' },
        { id: 8, email: 'paga2@ejemplo.com', motivo: 'paga' },
        { id: 9, email: 'nueva@ejemplo.com', motivo: 'prueba_sin_usar' },
      ],
    })
    expect(t).toContain('En su prueba gratis 3 la prueba se alarga')
    expect(t).toContain('Con un regalo vigente 0 suma en el mismo plan')
    expect(t).toContain('Sin plan vigente 40 días de Pro desde hoy')
    expect(t).toContain('Quedan afuera: 3')
    expect(t).toContain('Pagan : 2 · paga1@ejemplo.com, paga2@ejemplo.com')
    expect(t).toContain('Tienen la prueba gratis sin usar : 1 · nueva@ejemplo.com')
  })
})
