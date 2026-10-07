import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, otraPestanaEscribe, montar, enActo } from '../testing/navegadorMinimo'

// 🔴 LA PANTALLA /ai TAMBIÉN ARMA SU FOTO (2026-10-05).
//
// La página de la IA pide su propia foto de la cartera y se la pasa al chat.
// Sólo la volvía a pedir al pasar del libro a un cliente: de Ana a Bruno —por
// ejemplo desde otra pestaña— se quedaba con la de Ana, en el subtítulo y en
// lo que se manda. Acá se monta la página DE VERDAD con el contexto de asesor
// real; lo que se reemplaza es lo que no hace a esto: el chat (por un espía
// que anota qué foto recibe), el personaje y quién está logueado.

const recibido = vi.hoisted(() => ({ fotos: [], montajes: 0 }))
vi.mock('../components/AICoach', async () => {
  const { useEffect } = await import('react')
  const { getClientContext } = await import('../utils/api')
  return {
    default: function Espia({ snapshot }) {
      useEffect(() => { recibido.montajes += 1 }, [])
      recibido.fotos.push({
        clienteAbierto: getClientContext()?.id ?? null,
        brokers: (snapshot?.brokers || []).map(b => b.name),
      })
      return null
    },
  }
})
vi.mock('../components/ai/MervallE', () => ({ default: () => null }))
vi.mock('../components/ai/mervalle/estadoDelChat', () => ({
  useEstadoMervallE: () => ({ estado: 'reposo' }),
  enEscena: () => 'portada',
  sinPensando: (e) => e,
  usePortadaConPersonaje: () => false,
  ANCHO_COMPANERO: 1024,
}))
vi.mock('../hooks/useIsMobile', () => ({ useAnchoMinimo: () => true, useIsMobile: () => false }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { email: 'asesor@prueba.test', tier: 'advisor' } }) }))
vi.mock('../contexts/CoachDrawerContext', () => ({ useCoachDrawer: () => ({ initialQuestion: null, consumeInitialQuestion: () => {} }) }))
// El proveedor del chat va DE VERDAD: desde que la página dejó de armar su
// propia foto, la toma de la lectura que comparte con la isla (VozContext →
// utils/lecturaDeCartera). Antes acá se lo reemplazaba por uno vacío, porque
// la página pedía la foto por su cuenta.

let api, advisor, voz, RendiAI
beforeAll(async () => {
  instalarNavegadorMinimo()
  api = await import('../utils/api')
  advisor = await import('../contexts/AdvisorContext')
  voz = await import('../contexts/VozContext')
  RendiAI = (await import('./RendiAI')).default
})
afterAll(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

const BROKERS = { null: [{ name: 'IOL' }], 2: [{ name: 'Balanz' }], 3: [{ name: 'IBKR' }] }
const esperar = () => enActo(() => new Promise(r => setTimeout(r, 0)))

describe('/ai con un cliente abierto', () => {
  it('si el cliente cambia (otra pestaña), la página pide la foto del nuevo y nunca le pasa al chat la del anterior', async () => {
    vi.spyOn(api.api, 'get').mockImplementation(async (path) =>
      (path === '/brokers' ? BROKERS[api.getClientContext()?.id ?? null] : []))
    api.setClientContext({ id: 2, label: 'Ana' })
    // Como en la app: el proveedor del chat arriba de todo, el de asesor adentro.
    const m = await montar(h(voz.VozProvider, null, h(advisor.AdvisorProvider, null, h(RendiAI))))
    await esperar()
    expect(recibido.fotos.at(-1)).toEqual({ clienteAbierto: 2, brokers: ['Balanz'] })
    const montajesConAna = recibido.montajes

    const desde = recibido.fotos.length
    await enActo(() => otraPestanaEscribe('rendi_client_ctx', JSON.stringify({ id: 3, label: 'Bruno' })))
    await esperar()
    const despues = recibido.fotos.slice(desde)
    expect(despues.at(-1)).toEqual({ clienteAbierto: 3, brokers: ['IBKR'] })
    // Con Bruno abierto, el chat no recibió NUNCA la foto de Ana.
    expect(despues.filter(f => f.clienteAbierto === 3 && f.brokers.includes('Balanz'))).toEqual([])
    // Y el chat se volvió a montar: pide el cupo de la cuenta nueva.
    expect(recibido.montajes).toBeGreaterThan(montajesConAna)
    await m.desmontar()
  })
})
