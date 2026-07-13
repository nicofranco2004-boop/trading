// B-6 (audit IA #2): un stream SSE cortado sin frame terminal (Vercel 30s, red
// móvil) se devolvía como respuesta COMPLETA. Ahora chatStream lanza
// err.truncated=true si el reader termina sin `done`/`error`.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api } from './api'

function sseResponse(frames) {
  // Fake Response con body.getReader() que emite los frames y cierra.
  const chunks = frames.map(f => new TextEncoder().encode(f))
  let i = 0
  return {
    status: 200,
    ok: true,
    body: {
      getReader: () => ({
        read: async () => (i < chunks.length
          ? { value: chunks[i++], done: false }
          : { value: undefined, done: true }),
        cancel: async () => {},
      }),
    },
  }
}

describe('chatStream', () => {
  beforeEach(() => {
    // node env: sin localStorage — stub mínimo para isDemoMode/api internals.
    globalThis.localStorage = {
      getItem: () => null, setItem: () => {}, removeItem: () => {},
    }
    globalThis.window = { location: { href: '' } }
  })
  afterEach(() => {
    vi.restoreAllMocks()
    delete globalThis.localStorage
    delete globalThis.window
  })

  it('stream completo (delta + done) devuelve tier y emite deltas', async () => {
    globalThis.fetch = vi.fn(async () => sseResponse([
      'data: {"t":"delta","d":"hola "}\n\n',
      'data: {"t":"delta","d":"mundo"}\n\n',
      'data: {"t":"done","tier":"pro"}\n\n',
    ]))
    let acc = ''
    const r = await api.chatStream({ messages: [] }, { onDelta: d => { acc += d } })
    expect(acc).toBe('hola mundo')
    expect(r.tier).toBe('pro')
    expect(r.portfolioChanged).toBe(false)   // turno sin write → no refresh
  })

  it('done con portfolio_changed (registro/undo por chat) → portfolioChanged', async () => {
    globalThis.fetch = vi.fn(async () => sseResponse([
      'data: {"t":"delta","d":"✅ Listo, registré: COMPRA 0,01 BTC"}\n\n',
      'data: {"t":"done","tier":"pro","portfolio_changed":true}\n\n',
    ]))
    const r = await api.chatStream({ messages: [] }, { onDelta: () => {} })
    expect(r.portfolioChanged).toBe(true)
  })

  it('stream TRUNCADO (sin frame terminal) lanza err.truncated', async () => {
    globalThis.fetch = vi.fn(async () => sseResponse([
      'data: {"t":"delta","d":"respuesta a med"}\n\n',
      // el reader cierra acá sin done/error — corte de conexión
    ]))
    let caught = null
    try {
      await api.chatStream({ messages: [] }, { onDelta: () => {} })
    } catch (e) {
      caught = e
    }
    expect(caught).not.toBeNull()
    expect(caught.truncated).toBe(true)
  })

  it('frame done PARTIDO entre dos reads NO es truncación', async () => {
    // El frame terminal puede llegar cortado en 2 chunks TCP: el parser lo
    // re-ensambla vía buf. Sin este test, una mutación en `buf +=` deja la
    // suite verde con B-6 roto.
    globalThis.fetch = vi.fn(async () => sseResponse([
      'data: {"t":"delta","d":"hola"}\n\n',
      'data: {"t":"done","ti',
      'er":"pro"}\n\n',
    ]))
    const r = await api.chatStream({ messages: [] }, { onDelta: () => {} })
    expect(r.tier).toBe('pro')
  })

  it('frame done SIN el \\n\\n final (stream cortado en el último frame) = truncado', async () => {
    globalThis.fetch = vi.fn(async () => sseResponse([
      'data: {"t":"delta","d":"hola"}\n\n',
      'data: {"t":"done","tier":"pro"}',  // sin \n\n → frame nunca se completa
    ]))
    let caught = null
    try {
      await api.chatStream({ messages: [] }, { onDelta: () => {} })
    } catch (e) { caught = e }
    expect(caught?.truncated).toBe(true)
  })

  it('frame reset (turno tool_use) dispara onReset y el stream sigue', async () => {
    // B-13: el preámbulo pre-tools se descarta client-side vía onReset; la
    // síntesis final llega después y el done cierra normal.
    globalThis.fetch = vi.fn(async () => sseResponse([
      'data: {"t":"delta","d":"déjame consultar los precios…"}\n\n',
      'data: {"t":"reset"}\n\n',
      'data: {"t":"delta","d":"NVDA está a US$ 215."}\n\n',
      'data: {"t":"done","tier":"pro"}\n\n',
    ]))
    let acc = ''
    let resets = 0
    const r = await api.chatStream({ messages: [] }, {
      onDelta: d => { acc += d },
      onReset: () => { acc = ''; resets += 1 },
    })
    expect(resets).toBe(1)
    expect(acc).toBe('NVDA está a US$ 215.')   // el preámbulo se descartó
    expect(r.tier).toBe('pro')
  })

  it('frame error del LLM lanza con status 503 (no truncated)', async () => {
    globalThis.fetch = vi.fn(async () => sseResponse([
      'data: {"t":"delta","d":"algo"}\n\n',
      'data: {"t":"error","code":"llm_error","message":"se rompió"}\n\n',
    ]))
    let caught = null
    try {
      await api.chatStream({ messages: [] }, { onDelta: () => {} })
    } catch (e) {
      caught = e
    }
    expect(caught.status).toBe(503)
    expect(caught.truncated).toBeUndefined()
  })
})
