import { describe, it, expect, beforeEach, vi } from 'vitest'

// isDemoMode toca localStorage del browser — acá solo importa que devuelva
// false para que el storageKey sea el real.
vi.mock('./demo', () => ({ isDemoMode: () => false }))

import { loadChatSession, saveChatSession, clearChatSession, sendWindow, MAX_SENT, MAX_STORED } from './chatSession'

// sessionStorage no existe en node — stub mínimo compartido por los tests.
function stubStorage() {
  const store = new Map()
  globalThis.sessionStorage = {
    getItem: k => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: k => store.delete(k),
  }
  return store
}

const msg = (role, content) => ({ role, content })

describe('chatSession', () => {
  beforeEach(() => stubStorage())

  it('roundtrip: save → load conserva role/content y descarta extras', () => {
    saveChatSession([{ role: 'user', content: 'hola', extra: 'x' }, msg('assistant', 'buenas')])
    expect(loadChatSession()).toEqual([msg('user', 'hola'), msg('assistant', 'buenas')])
  })

  it('cap MAX_STORED: guarda solo los últimos', () => {
    const many = Array.from({ length: MAX_STORED + 10 }, (_, i) => msg(i % 2 ? 'assistant' : 'user', `m${i}`))
    saveChatSession(many)
    const loaded = loadChatSession()
    expect(loaded).toHaveLength(MAX_STORED)
    expect(loaded[loaded.length - 1].content).toBe(`m${MAX_STORED + 9}`)
  })

  it('clear borra; lista vacía también limpia; storage roto → []', () => {
    saveChatSession([msg('user', 'hola')])
    clearChatSession()
    expect(loadChatSession()).toEqual([])
    saveChatSession([msg('user', 'hola')])
    saveChatSession([])
    expect(loadChatSession()).toEqual([])
    sessionStorage.setItem('rendi_chat_v1', '{no es json')
    expect(loadChatSession()).toEqual([])
  })

  it('sendWindow: cap MAX_SENT y arranca en mensaje user', () => {
    const many = Array.from({ length: 30 }, (_, i) => msg(i % 2 ? 'assistant' : 'user', `m${i}`))
    const w = sendWindow(many)
    expect(w.length).toBeLessThanOrEqual(MAX_SENT)
    expect(w[0].role).toBe('user')
    expect(w[w.length - 1].content).toBe('m29')
  })

  it('sendWindow: conversación corta pasa entera; ventana degenerada → último mensaje', () => {
    const short = [msg('user', 'a'), msg('assistant', 'b'), msg('user', 'c')]
    expect(sendWindow(short)).toEqual(short)
    const onlyAssistant = Array.from({ length: MAX_SENT }, (_, i) => msg('assistant', `a${i}`))
    const w = sendWindow(onlyAssistant)
    expect(w).toHaveLength(1)
    expect(w[0].content).toBe(`a${MAX_SENT - 1}`)
  })
})
