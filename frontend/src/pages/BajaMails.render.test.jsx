// El botón «Baja de mails» de la tabla de Usuarios de /admin. El campo
// `marketing_baja_at` y el pedido `/admin/users/{id}/mails-promocionales` los
// fija backend/tests/test_baja_promocionales.py (BajaDesdeLaTablaDeUsuariosTest):
// si el servidor cambia uno, se pone rojo allá.
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { BotonMails, MarcaSinMails, cambiarMailsPromocionales, preguntaMails } from './Admin'

const texto = (el) => renderToStaticMarkup(el).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
const ana = { id: 7, email: 'ana@ejemplo.com', is_admin: false, marketing_baja_at: null }
const anaDeBaja = { ...ana, marketing_baja_at: '2026-11-11T14:03:00' }

describe('la fila de la tabla', () => {
  it('a quien recibe le ofrece la baja, sin la marca', () => {
    expect(texto(<BotonMails u={ana} onCambiar={() => {}} />)).toBe('Baja de mails')
    expect(renderToStaticMarkup(<MarcaSinMails u={ana} />)).toBe('')
  })

  it('a quien se dio de baja lo marca con la fecha y ofrece deshacerlo', () => {
    expect(texto(<BotonMails u={anaDeBaja} onCambiar={() => {}} />)).toBe('Volver a mandarle')
    const marca = renderToStaticMarkup(<MarcaSinMails u={anaDeBaja} />)
    expect(texto(<MarcaSinMails u={anaDeBaja} />)).toBe('Sin mails')
    expect(marca).toContain('desde el 2026-11-11')
  })

  it('a una cuenta de admin no le muestra el botón', () => {
    expect(renderToStaticMarkup(<BotonMails u={{ ...ana, is_admin: true }} onCambiar={() => {}} />)).toBe('')
  })
})

describe('el pedido', () => {
  const pedidos = []
  const pedir = async (ruta, cuerpo) => { pedidos.push([ruta, cuerpo]); return { ok: true } }

  it('pregunta antes y, si dice que sí, le pide al servidor la baja de ESA cuenta', async () => {
    pedidos.length = 0
    const preguntas = []
    const res = await cambiarMailsPromocionales({
      u: ana, recibe: false, pedir,
      confirmar: async (msg, op) => { preguntas.push([msg, op.si]); return true },
    })
    expect(res).toEqual({ ok: true })
    expect(pedidos).toEqual([['/admin/users/7/mails-promocionales', { recibe: false }]])
    expect(preguntas[0][1]).toBe('Dar de baja')
    expect(preguntas[0][0]).toContain('ana@ejemplo.com')
  })

  it('si cancela, no pide nada', async () => {
    pedidos.length = 0
    const res = await cambiarMailsPromocionales({ u: ana, recibe: false, pedir, confirmar: async () => false })
    expect(res).toBeNull()
    expect(pedidos).toEqual([])
  })

  it('deshacer manda recibe: true', async () => {
    pedidos.length = 0
    await cambiarMailsPromocionales({ u: anaDeBaja, recibe: true, pedir, confirmar: async () => true })
    expect(pedidos).toEqual([['/admin/users/7/mails-promocionales', { recibe: true }]])
  })
})

describe('el cartel', () => {
  it('dice qué deja de llegar y qué sigue llegando', () => {
    const t = preguntaMails(ana, false)
    expect(t).toContain('campañas que mandás desde el panel')
    expect(t).toContain('lista para Meta')
    expect(t).toContain('los códigos para entrar, los recibos')
    expect(t).toContain('se le termina la prueba o el plan')
  })
})
