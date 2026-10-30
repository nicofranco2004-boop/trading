// «Ocultar saldos», segunda vuelta (re-test de la auditoría A, 29/10): con el
// ojito prendido seguían a la vista
//   · Cartera › Futuros: «+US$2.000,00 no realizado» y el resultado de cada
//     contrato (FuturosGroup: Positions.jsx lo monta sin decirle del ojito);
//   · Cartera › Plazos fijos: capital, interés ganado y valor de hoy (mismo patrón);
//   · Eventos › «Ver calendario»: lo que cobrarías (la agenda de al lado ya lo tapaba);
//   · Dashboard › Próximos eventos: «cobrás ~+US$…».
// Cada pieza montada de verdad (testing/navegadorMinimo.js), con el ojito como lo
// guarda la app y el servidor simulado en la frontera. Apagado se ve la plata
// (si no, la prueba no prueba nada); prendido, no.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { instalarNavegadorMinimo, montar, texto } from '../testing/navegadorMinimo'
import { PrivacyProvider } from '../contexts/PrivacyContext'

vi.mock('../components/Toast', () => ({ useToast: () => ({ push: () => {}, success: () => {}, error: () => {} }) }))
vi.mock('../components/AssetLogo', () => ({ default: () => null }))
vi.mock('../hooks/useCerSeries', () => ({ useCerSeries: () => ({ series: null }) }))

const FUTURO = [{ id: 1, symbol: 'BTCUSDT', base_asset: 'BTC', quantity: 1, entry_price: 60000, side: 'long', broker: 'Binance' }]
const PF = [{ id: 7, banco: 'Galicia', moneda: 'ARS', capital: 4321000, tasa: 40, rate_type: 'TNA', modalidad: 'al_vencimiento',
  fecha_inicio: '2026-09-01', plazo_dias: 60, fecha_vencimiento: '2026-10-31' }]
// En el mes de hoy: el calendario abre en el mes actual.
const EVENTO = { ticker: 'AL30', event_type: 'bond_coupon', event_date: new Date(Date.now() + 86400000).toISOString().slice(0, 10), confirmed: true,
  details: { total: 777.77, currency: 'USD' } }
vi.mock('../utils/api', async (orig) => ({
  ...(await orig()),
  api: {
    get: vi.fn((ruta) => Promise.resolve(
      ruta.startsWith('/futures') ? FUTURO
        : ruta.startsWith('/prices') ? { BTC: 62000 }
          : ruta.startsWith('/plazos-fijos') ? PF
            : ruta.startsWith('/events/portfolio') ? { events: [EVENTO] } : [])),
  },
}))

let FuturosGroup, PlazosFijosGroup, UpcomingEventsCard, CalendarioEventos
beforeAll(async () => {
  instalarNavegadorMinimo()
  window.matchMedia = (q) => ({ matches: /reduce/.test(q), addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })
  ;({ default: FuturosGroup } = await import('../components/FuturosGroup'))
  ;({ default: PlazosFijosGroup } = await import('../components/PlazosFijosGroup'))
  ;({ default: UpcomingEventsCard } = await import('../components/UpcomingEventsCard'))
  ;({ default: CalendarioEventos } = await import('../components/novedades/CalendarioEventos'))
}, 120000)
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null; localStorage.clear() })

async function ver(componente, props, ojito) {
  localStorage.setItem('rendi_privacy', ojito ? '1' : '0')
  const el = () => h(PrivacyProvider, null, h(MemoryRouter, null, h(componente, props)))
  montado = await montar(el())
  for (let i = 0; i < 6; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

const CASOS = [
  ['Cartera › Futuros', () => FuturosGroup, {}, ['+US$2.000,00']],
  ['Cartera › Plazos fijos', () => PlazosFijosGroup, {}, ['4.321.000']],
  ['Dashboard › Próximos eventos', () => UpcomingEventsCard, { positions: [{ asset: 'AL30', quantity: 1000 }] }, ['777,77']],
  ['Eventos › Ver calendario', () => CalendarioEventos, { eventosDelAnio: [EVENTO], onClose: () => {} }, ['777,77']],
]

describe('«Ocultar saldos» en lo que cuelga de la Cartera, el Dashboard y Eventos', () => {
  for (const [nombre, C, props, montos] of CASOS) {
    it(`${nombre}: apagado se ve la plata, prendido no`, async () => {
      const apagado = await ver(C(), props, false)
      for (const m of montos) expect(apagado, `${nombre} apagado`).toContain(m)
      await montado.desmontar(); montado = null
      const prendido = await ver(C(), props, true)
      for (const m of montos) expect(prendido, `${nombre} prendido`).not.toContain(m)
      expect(prendido).toContain('••••••')
    }, 120000)
  }
})
