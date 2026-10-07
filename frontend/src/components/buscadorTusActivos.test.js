import { describe, it, expect, vi, beforeAll, beforeEach, afterEach, afterAll } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, enActo, buscar, texto, escribir, tecla } from '../testing/navegadorMinimo'

// 🔴 EL BUSCADOR ⌘K NUNCA MOSTRABA "TUS ACTIVOS" EN UNA CUENTA DE VERDAD (2026-10-07).
//
// Guardaba tus activos bajo una clave armada con `user.id`, y el usuario de la
// app no trae `id`: AuthContext.mapMeToUser arma el usuario con lo que manda
// /auth/me y ese dato no lo copia. Sin clave, el buscador no pedía tus
// posiciones NUNCA —ni de antemano ni al abrirlo—: "nvda" + Enter llevaba a la
// empresa en vez de a tu posición. Sólo andaba en el modo demo, que es un
// usuario escrito a mano CON `id: 0`; ahí se probó y ahí pasaba.
//
// Las pruebas de antes armaban el usuario a mano (`{ id: 1 }`), que es
// justamente lo que tapó el bug. Acá el usuario sale del AuthProvider DE
// VERDAD: el guardado en el navegador al abrir y después /auth/me pasado por
// mapMeToUser, como en producción. Lo único simulado es el servidor.

// Lo que no está en el camino del bug: tema, moneda, privacidad, el chat y el
// plan (sólo deciden si hay "pregúntale a Mervall-E" al final de la lista).
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: null }) }))
vi.mock('../contexts/CurrencyContext', () => ({ useCurrency: () => ({ currency: 'USD', setCurrency: () => {} }) }))
vi.mock('../contexts/ThemeContext', () => ({ useTheme: () => ({ dark: true, toggle: () => {} }) }))
vi.mock('../contexts/PrivacyContext', () => ({ usePrivacy: () => ({ hidden: false, toggle: () => {} }) }))
vi.mock('../contexts/CoachDrawerContext', () => ({ useCoachDrawer: () => ({ open: () => {} }) }))
vi.mock('../hooks/usePlanFeatures', () => ({
  usePlanFeatures: () => ({ isPro: true, isAdmin: false }),
  refreshPlanFeatures: () => Promise.resolve(),
}))
vi.mock('./ai/MervallE', () => ({ default: () => null }))

let api, auth, demo, Buscador, router, local
beforeAll(async () => {
  ;({ local } = instalarNavegadorMinimo())
  api = (await import('../utils/api')).api
  auth = await import('../contexts/AuthContext')
  demo = await import('../utils/demo')
  Buscador = await import('./BuscadorRapido')
  router = await import('react-router-dom')
})
afterAll(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

// Lo que contesta /api/auth/me (backend/main.py → `me`), con todos sus campos.
const servidorDe = (id, email, name) => ({
  id, email, name, is_admin: false, created_at: '2025-03-01 12:00:00', last_login_at: '2026-10-06 09:00:00',
  tier: 'pro', subscription_status: 'authorized', subscription_period_end: null, subscription_cancelled_at: null,
  subscription_period: 'monthly', credit_active_until: null, credit_days_remaining: 0, credit_remaining_usd: 0,
  credit_anchor_plan: null, credit_anchor_period: null, requires_plan: false, cuenta_en_pausa: false,
  pausa_motivo: null, pausa_resumen: null, access_mode: 'authorized',
})
// Una persona por prueba: el buscador guarda tus activos mientras la página
// está abierta (como en la app), y lo que guardó una prueba taparía a la otra.
const ANA = servidorDe(41, 'ana@prueba.test', 'Ana')
const BETO = servidorDe(42, 'beto@prueba.test', 'Beto')
const CARLA = servidorDe(43, 'carla@prueba.test', 'Carla')
const DANI = servidorDe(44, 'dani@prueba.test', 'Dani')
const NVDA = [{ asset: 'NVDA', broker: 'Schwab', quantity: 10, is_cash: false }]

let montado, donde, quien, pedidosDePosiciones
// Dónde quedó la pantalla y quién cree la app que está.
const Donde = () => { donde = router.useLocation().pathname; quien = auth.useAuth().user; return null }

/**
 * Abre la app con la sesión de `persona` guardada en el navegador (lo que dejó
 * la visita anterior: el usuario armado por mapMeToUser) y el servidor
 * contestando /auth/me y /positions.
 */
async function abrirLaAppComo(persona, { meContesta = () => persona, posiciones = () => NVDA } = {}) {
  local.set('rendi_user', JSON.stringify(auth.mapMeToUser(persona)))
  pedidosDePosiciones = 0
  vi.spyOn(api, 'get').mockImplementation(async (path) => {
    if (path === '/auth/me') return meContesta()
    if (path === '/positions') { pedidosDePosiciones += 1; return posiciones() }
    return {}
  })
  montado = await montar(h(auth.AuthProvider, null,
    h(router.MemoryRouter, { initialEntries: ['/dashboard'] }, h(Buscador.default), h(Donde))))
}

const campo = () => buscar(montado.contenedor, 'input')
const filas = () => {
  const lista = buscar(montado.contenedor, 'ul')
  return lista ? lista.childNodes.map(texto) : []
}
async function abrirYEscribir(consulta) {
  await enActo(async () => { Buscador.abrirBuscador() })
  await escribir(campo(), consulta)
}
// Que terminen los pedidos simulados (resuelven en la próxima vuelta).
const queContesten = () => enActo(async () => { await new Promise(r => setTimeout(r, 0)) })

beforeEach(() => {
  vi.restoreAllMocks()
  local.clear()
  donde = quien = null
})
afterEach(async () => {
  vi.useRealTimers()
  if (montado) await montado.desmontar()
  montado = null
})

describe('⌘K en una cuenta de verdad: "nvda" + Enter lleva a TU posición', () => {
  it('abrís, escribís "nvda": lo primero es tu posición, y Enter te lleva ahí', async () => {
    await abrirLaAppComo(ANA)
    await abrirYEscribir('nvda')
    await queContesten()
    expect(filas()[0]).toContain('Tu posición')
    expect(filas().join(' | ')).not.toContain('Ver la empresa')

    await tecla(campo(), 'Enter')
    expect(donde).toBe('/activo/NVDA')
  })

  it('tus activos se piden ANTES de abrir: el primer "nvda" rápido ya los tiene', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await abrirLaAppComo(CARLA)
    expect(pedidosDePosiciones).toBe(0)
    await enActo(async () => { vi.advanceTimersByTime(2000); await Promise.resolve() })
    expect(pedidosDePosiciones).toBe(1)

    // Al abrir se vuelven a pedir; ese pedido no vuelve nunca, y aun así ya
    // están: son los de antes.
    api.get.mockImplementation(async (path) => (path === '/positions' ? new Promise(() => {}) : {}))
    await abrirYEscribir('nvda')
    expect(filas()[0]).toContain('Tu posición')
  })

  it('si /auth/me no contesta (corte de red), la sesión guardada alcanza: igual están', async () => {
    await abrirLaAppComo(DANI, { meContesta: () => { throw new TypeError('Failed to fetch') } })
    await abrirYEscribir('nvda')
    await queContesten()
    expect(filas()[0]).toContain('Tu posición')
  })

  it('el que entra después en la misma pestaña NO ve los del anterior', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await abrirLaAppComo(ANA)
    await enActo(async () => { vi.advanceTimersByTime(2000); await Promise.resolve() })
    await montado.desmontar()

    // Entra Beto: sus posiciones todavía no llegaron. Lo guardado de Ana no
    // se le puede mostrar ni un instante.
    vi.useRealTimers()
    await abrirLaAppComo(BETO, { posiciones: () => new Promise(() => {}) })
    await abrirYEscribir('nvda')
    expect(filas().join(' | ')).not.toContain('Tu posición')
  })

  it('el modo demo sigue andando', async () => {
    demo.enableDemoMode()
    await abrirLaAppComo(ANA)
    expect(quien?.demo).toBe(true)
    await abrirYEscribir('nvda')
    await queContesten()
    expect(filas()[0]).toContain('Tu posición')
    demo.disableDemoMode()
  })
})
