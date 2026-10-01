// Los envíos masivos del panel de admin parten la lista en tandas.
//
// Lo que se protege acá: que ningún pedido lleve más de `lote` personas (el
// proxy de Vercel corta a ~30 s y el admin veía un error con los mails todavía
// saliendo), que cada persona viaje con lo que se vio en pantalla, y que si un
// pedido falla el panel se entere de lo que YA salió en vez de perderlo.
import { describe, it, expect, vi } from 'vitest'
import { enviarEnTandas, textoDeProgreso, LOTE_POR_DEFECTO } from './envioEnTandas'

const personas = n => Array.from({ length: n }, (_, i) => ({ id: i + 1, sent_at: null }))

function servidorQueManda() {
  return vi.fn(async (_url, body) => ({
    sent_count: body.vistos.length, failed_count: 0, skipped_count: 0, discarded_count: 0,
    marcas_trabadas: [],
  }))
}

describe('enviarEnTandas', () => {
  it('nunca manda más de un lote por pedido, y manda a todos', async () => {
    const post = servidorQueManda()
    const r = await enviarEnTandas({ post, url: '/admin/email/x', vistos: personas(45), lote: 20 })
    expect(post.mock.calls.map(c => c[1].vistos.length)).toEqual([20, 20, 5])
    expect(post.mock.calls.flatMap(c => c[1].vistos.map(v => v.id)))
      .toEqual(personas(45).map(p => p.id))
    expect(r.sent_count).toBe(45)
    expect(r.cortado).toBeUndefined()
  })

  it('cada pedido confirma, lleva el resto del cuerpo y lo que se vio', async () => {
    const post = servidorQueManda()
    const vistos = [{ id: 7, sent_at: '2026-09-28T10:00:00' }]
    await enviarEnTandas({ post, url: '/admin/email/x', cuerpo: { resend: true }, vistos, lote: 20 })
    expect(post).toHaveBeenCalledWith('/admin/email/x', { resend: true, confirm: true, vistos })
  })

  it('sin lote del servidor usa el de siempre', async () => {
    const post = servidorQueManda()
    await enviarEnTandas({ post, url: '/x', vistos: personas(LOTE_POR_DEFECTO + 1) })
    expect(post.mock.calls.map(c => c[1].vistos.length)).toEqual([LOTE_POR_DEFECTO, 1])
  })

  it('suma lo que devuelve cada tanda, incluidas las marcas trabadas', async () => {
    const respuestas = [
      { sent_count: 18, failed_count: 1, skipped_count: 1, discarded_count: 0, marcas_trabadas: [] },
      { sent_count: 3, failed_count: 0, skipped_count: 0, discarded_count: 2,
        marcas_trabadas: [{ id: 30, email: 'a@b.c' }] },
    ]
    const post = vi.fn(async () => respuestas.shift())
    const r = await enviarEnTandas({ post, url: '/x', vistos: personas(25), lote: 20 })
    expect(r).toMatchObject({ sent_count: 21, failed_count: 1, skipped_count: 1, discarded_count: 2 })
    expect(r.marcas_trabadas).toEqual([{ id: 30, email: 'a@b.c' }])
  })

  it('si una tanda falla, corta ahí y devuelve lo que ya salió', async () => {
    let llamada = 0
    const post = vi.fn(async (_u, body) => {
      llamada += 1
      if (llamada === 2) throw new Error('Gateway Timeout')
      return { sent_count: body.vistos.length, failed_count: 0, skipped_count: 0, discarded_count: 0 }
    })
    const r = await enviarEnTandas({ post, url: '/x', vistos: personas(60), lote: 20 })
    expect(post).toHaveBeenCalledTimes(2)          // la tercera no sale
    expect(r.sent_count).toBe(20)
    expect(r.cortado).toBe(true)
    expect(r.error).toBe('Gateway Timeout')
  })

  it('avisa el avance de cada tanda', async () => {
    const pasos = []
    await enviarEnTandas({ post: servidorQueManda(), url: '/x', vistos: personas(25), lote: 20,
                           alAvanzar: p => pasos.push(textoDeProgreso(p)) })
    expect(pasos).toEqual(['Enviando 1–20 de 25…', 'Enviando 21–25 de 25…'])
    expect(textoDeProgreso(null)).toBe('Enviando…')
  })

  it('con la lista vacía no pide nada', async () => {
    const post = servidorQueManda()
    const r = await enviarEnTandas({ post, url: '/x', vistos: [], lote: 20 })
    expect(post).not.toHaveBeenCalled()
    expect(r.sent_count).toBe(0)
  })
})
