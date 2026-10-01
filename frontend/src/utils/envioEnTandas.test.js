// Los envíos masivos del panel de admin parten la lista en tandas.
//
// Lo que se protege acá: que ningún pedido lleve más de `lote` personas (el
// proxy de Vercel corta a ~30 s y el admin veía un error con los mails todavía
// saliendo), que cada persona viaje con lo que se vio en pantalla, que si un
// pedido falla el panel se entere de lo que YA salió en vez de perderlo, que
// contra el servidor de antes (unos minutos en cada deploy) no se mande nada
// de más, y que el estado del envío sobreviva a que el panel se desmonte.
import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  enviarEnTandas, textoDeProgreso, tomarEnvio, soltarEnvio, avanceEnvio, estadoEnvio,
  ultimoResultado, suscribirEnvios, LOTE_POR_DEFECTO,
} from './envioEnTandas'

const personas = n => Array.from({ length: n }, (_, i) => ({ id: i + 1, sent_at: null }))

// Lo que contesta el servidor de esta versión: siempre trae `frenado`.
const respuesta = (extra = {}) => ({
  sent_count: 0, failed_count: 0, skipped_count: 0, discarded_count: 0,
  marcas_trabadas: [], inciertos: [], pendientes: [], frenado: false, ...extra,
})

function servidorQueManda() {
  return vi.fn(async (_url, body) => respuesta({ sent_count: body.vistos.length }))
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
    expect(post).toHaveBeenCalledWith('/admin/email/x',
                                      { resend: true, confirm: true, vistos, inciertos_seguidos: 0 })
  })

  it('le devuelve al servidor los "no sabemos" seguidos del pedido anterior', async () => {
    const respuestas = [respuesta({ sent_count: 19, inciertos: [{ id: 20 }], inciertos_seguidos: 1 }),
                        respuesta({ sent_count: 5, inciertos_seguidos: 0 })]
    const post = vi.fn(async () => respuestas.shift())
    await enviarEnTandas({ post, url: '/x', vistos: personas(25), lote: 20 })
    expect(post.mock.calls.map(c => c[1].inciertos_seguidos)).toEqual([0, 1])
  })

  it('con el servidor de antes del cambio no pide ni una tanda más', async () => {
    // Durante un deploy la web nueva habla con el servidor viejo, que ignora
    // `vistos` y manda a toda su lista en cada pedido (la invitación sorteaba
    // 50 nuevos por tanda).
    const viejo = vi.fn(async () => ({ dry_run: false, sent_count: 50, failed_count: 0 }))
    const r = await enviarEnTandas({ post: viejo, url: '/x', vistos: personas(50), lote: 20 })
    expect(viejo).toHaveBeenCalledTimes(1)
    expect(r).toMatchObject({ cortado: true, contesto: true })
  })

  it('suma lo que devuelve cada tanda, incluidas las marcas trabadas', async () => {
    const respuestas = [
      respuesta({ sent_count: 18, failed_count: 1, skipped_count: 1 }),
      respuesta({ sent_count: 3, discarded_count: 2,
                  marcas_trabadas: [{ id: 30, email: 'a@b.c' }], inciertos: [{ id: 31, email: 'd@e.f' }] }),
    ]
    const post = vi.fn(async () => respuestas.shift())
    const r = await enviarEnTandas({ post, url: '/x', vistos: personas(25), lote: 20 })
    expect(r).toMatchObject({ sent_count: 21, failed_count: 1, skipped_count: 1, discarded_count: 2 })
    expect(r.marcas_trabadas).toEqual([{ id: 30, email: 'a@b.c' }])
    expect(r.inciertos).toEqual([{ id: 31, email: 'd@e.f' }])
  })

  it('si una tanda falla, corta ahí y devuelve lo que ya salió', async () => {
    let llamada = 0
    const post = vi.fn(async (_u, body) => {
      llamada += 1
      if (llamada === 2) throw new Error('Gateway Timeout')
      return respuesta({ sent_count: body.vistos.length })
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

  it('los que el servidor no llegó a intentar vuelven en el pedido siguiente', async () => {
    // Resend lento: al primer pedido se le acaba el tiempo después de 12.
    const respuestas = [
      respuesta({ sent_count: 12, pendientes: Array.from({ length: 8 }, (_, i) => ({ id: 13 + i })) }),
    ]
    const post = vi.fn(async (_u, body) =>
      respuestas.shift() || respuesta({ sent_count: body.vistos.length }))
    const pasos = []
    const r = await enviarEnTandas({ post, url: '/x', vistos: personas(25), lote: 20,
                                     alAvanzar: p => pasos.push(textoDeProgreso(p)) })
    const ids = post.mock.calls.map(c => c[1].vistos.map(v => v.id))
    expect(ids[0]).toEqual(personas(20).map(p => p.id))
    expect(ids[1]).toEqual([13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25])  // 8 devueltos + 5
    expect(post).toHaveBeenCalledTimes(2)
    expect(r.sent_count).toBe(25)
    expect(r.cortado).toBeUndefined()
    expect(pasos).toEqual(['Enviando 1–20 de 25…', 'Enviando 13–25 de 25…'])
  })

  it('si el servidor devuelve la tanda entera sin intentar, corta en vez de girar para siempre', async () => {
    const post = vi.fn(async (_u, body) => respuesta({ pendientes: body.vistos }))
    const r = await enviarEnTandas({ post, url: '/x', vistos: personas(5), lote: 20 })
    expect(post).toHaveBeenCalledTimes(1)
    expect(r.cortado).toBe(true)
  })

  it('si Resend no confirma (frenado), corta y no manda la tanda siguiente', async () => {
    const post = vi.fn(async () => respuesta({ sent_count: 3, inciertos: [{ id: 4 }, { id: 5 }],
                                               frenado: true }))
    const r = await enviarEnTandas({ post, url: '/x', vistos: personas(45), lote: 20 })
    expect(post).toHaveBeenCalledTimes(1)
    expect(r).toMatchObject({ cortado: true, frenado: true, contesto: true, sent_count: 3 })
    expect(r.inciertos).toHaveLength(2)
  })

  it('distingue si el servidor contestó el error o se cortó en el camino', async () => {
    const conCodigo = status => vi.fn(async () => {
      const e = new Error('x'); if (status) e.status = status; throw e
    })
    for (const [status, contesto] of [[401, true], [422, true], [500, true], [504, false],
                                      [502, false], [null, false]]) {
      const r = await enviarEnTandas({ post: conCodigo(status), url: '/x', vistos: personas(3), lote: 20 })
      expect(r.cortado).toBe(true)
      expect(r.contesto).toBe(contesto)
    }
  })

  it('dice qué está haciendo después de la última tanda', () => {
    expect(textoDeProgreso({ fase: 'esperando' })).toBe('Esperando que termine la tanda cortada…')
    expect(textoDeProgreso({ fase: 'recargando' })).toBe('Actualizando la lista…')
  })

  it('con la lista vacía no pide nada', async () => {
    const post = servidorQueManda()
    const r = await enviarEnTandas({ post, url: '/x', vistos: [], lote: 20 })
    expect(post).not.toHaveBeenCalled()
    expect(r.sent_count).toBe(0)
  })
})

describe('el estado del envío vive fuera del panel', () => {
  afterEach(() => { soltarEnvio('/admin/email/x'); soltarEnvio('/admin/email/y') })

  it('no deja lanzar dos envíos del mismo mail a la vez', () => {
    expect(tomarEnvio('/admin/email/x')).toBe(true)
    expect(tomarEnvio('/admin/email/x')).toBe(false)
    expect(tomarEnvio('/admin/email/y')).toBe(true)     // otro mail, sí
    soltarEnvio('/admin/email/x')
    expect(tomarEnvio('/admin/email/x')).toBe(true)
  })

  it('un panel que se vuelve a montar ve el avance y, al final, el resultado', () => {
    const oyente = vi.fn()
    const dejar = suscribirEnvios(oyente)
    tomarEnvio('/admin/email/x', 'nuevos')
    avanceEnvio('/admin/email/x', { desde: 21, hasta: 40, total: 45 })
    expect(estadoEnvio('/admin/email/x')).toEqual(
      { clave: 'nuevos', progreso: { desde: 21, hasta: 40, total: 45 } })
    const antes = estadoEnvio('/admin/email/x')
    avanceEnvio('/admin/email/x', { fase: 'recargando' })
    expect(estadoEnvio('/admin/email/x')).not.toBe(antes)   // objeto nuevo: React lo ve
    soltarEnvio('/admin/email/x', { sent_count: 45 })
    expect(estadoEnvio('/admin/email/x')).toBeNull()
    expect(ultimoResultado('/admin/email/x')).toEqual({ sent_count: 45 })
    expect(oyente).toHaveBeenCalledTimes(4)
    dejar()
    tomarEnvio('/admin/email/x')
    expect(oyente).toHaveBeenCalledTimes(4)                  // ya no escucha
    expect(ultimoResultado('/admin/email/x')).toBeNull()    // un envío nuevo borra el anterior
  })

  it('pregunta antes de cerrar la pestaña sólo mientras hay un envío en curso', () => {
    // Los tests corren sin navegador: una ventana que sólo anota.
    const agregar = vi.fn()
    const sacar = vi.fn()
    vi.stubGlobal('window', { addEventListener: agregar, removeEventListener: sacar })
    try {
      tomarEnvio('/admin/email/x')
      tomarEnvio('/admin/email/y')
      expect(agregar.mock.calls.filter(c => c[0] === 'beforeunload')).toHaveLength(1)
      soltarEnvio('/admin/email/x')
      expect(sacar.mock.calls.filter(c => c[0] === 'beforeunload')).toHaveLength(0)
      soltarEnvio('/admin/email/y')
      expect(sacar.mock.calls.filter(c => c[0] === 'beforeunload')).toHaveLength(1)
      // Lo que se registra es una función que hace preguntar al navegador.
      const e = { preventDefault: vi.fn(), returnValue: undefined }
      agregar.mock.calls[0][1](e)
      expect(e.preventDefault).toHaveBeenCalled()
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
