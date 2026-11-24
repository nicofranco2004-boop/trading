// Movimientos con un pase entre brokers («Mover a otro broker»), la pantalla
// ENTERA montada (testing/navegadorMinimo.js) con el servidor simulado en la
// frontera (utils/api). Lo que fija, de la revisión E12:
//   1. el botón «Pases» aparece, con su número, y filtra (antes contaba por
//      `m.type === 'PASE'`, daba 0 y la pantalla lo escondía: el filtro de la
//      sección 0 punto 5 de la spec no se podía usar);
//   3. la compra original de un lote cargado a mano que se pasó (`trp-…`, que el
//      servidor manda `borrable: false` y sin `traspaso_id`) no ofrece el tacho:
//      el DELETE iba a una fila que el servidor no reconoce;
//   6. con el ojito prendido, el porqué de «no se puede deshacer» que manda el
//      servidor no muestra montos (el texto de C.8 #4 dice «({n} a {costo})»).
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { instalarNavegadorMinimo, montar, texto, clic, buscarBoton } from '../../testing/navegadorMinimo'
import { PrivacyProvider } from '../../contexts/PrivacyContext'

vi.mock('../../contexts/CurrencyContext', async (orig) => ({
  ...(await orig()),
  useCurrency: () => ({ currency: 'USD', valuationDollar: 'mep', costBasis: 'purchase', tcValuacion: 1555 }),
  pickFinancialRate: (d) => d?.mep?.venta ?? null,
}))
vi.mock('../../hooks/useFxHistory', () => ({ useFxHistory: () => ({ getRateOrFallback: () => 1555, fxKey: 'k' }) }))
vi.mock('../../components/ai/AskAIAbout', () => ({ default: ({ children }) => children }))
vi.mock('../../components/ai/AnalyzeButton', () => ({ default: () => null }))
vi.mock('../../components/plan/ExportCsvButton', () => ({ default: () => null }))
vi.mock('../../components/FueraDeHorario', () => ({ ChipDelActivo: () => null }))
vi.mock('../../components/AssetLogo', () => ({ default: () => null }))
const avisos = []
vi.mock('../../components/Toast', () => ({
  useToast: () => ({ push: (t, o) => avisos.push({ t, o }), success: () => {}, error: () => {}, info: () => {} }),
}))

// Un pase de 10 NVDA de Cocos a Balanz (las dos patas y el gasto del trámite),
// la compra original de un lote cargado a mano que salió con el pase, y un
// depósito común. Montos raros a propósito, para reconocerlos.
const MOVS = [
  { id: 'trx-s', type: 'TRASPASO_SALIDA', asset: 'NVDA', broker: 'Cocos', date: '2026-11-20', amount_usd: 178.57, fx_to_usd: 1400,
    currency: 'ARS', quantity: 10, traspaso_id: 'abc', borrable: false, contraparte: 'Balanz', estado: 'vivo' },
  { id: 'trx-e', type: 'TRASPASO_ENTRADA', asset: 'NVDA', broker: 'Balanz', date: '2026-11-20', amount_usd: 178.57, fx_to_usd: 1400,
    currency: 'ARS', quantity: 10, traspaso_id: 'abc', borrable: false, contraparte: 'Cocos', estado: 'vivo' },
  { id: 'imp-9', type: 'FEE', asset: 'NVDA', broker: 'Cocos', date: '2026-11-20', amount_usd: 3.57, fx_to_usd: 1400,
    currency: 'ARS', traspaso_id: 'abc', borrable: false },
  { id: 'trp-abc-0', type: 'BUY', asset: 'NVDA', broker: 'Cocos', date: '2024-03-10', amount_usd: 911.11, fees_usd: 2,
    currency: 'USD', fx_to_usd: 1, quantity: 6, source: 'traspaso', borrable: false },
  { id: 1, type: 'DEPOSIT', asset: null, broker: 'Schwab', date: '2025-01-05', amount_usd: 4321, amount: 4321, currency: 'USD', fx_to_usd: 1 },
]
const MOTIVO = 'Los NVDA que llegaron a Balanz ya no están como llegaron: los editaste. ' +
  'Volvé a dejarlos como llegaron (10 a US$ 1.234,56) para poder deshacer el pase.'
const RESPUESTAS = {
  '/brokers': () => [{ id: 1, name: 'Cocos', currency: 'ARS' }, { id: 2, name: 'Balanz', currency: 'ARS' }, { id: 3, name: 'Schwab', currency: 'USD' }],
  '/dolar': () => ({ mep: { venta: 1555, compra: 1550 } }),
  '/operations': () => [],
  '/movements': () => MOVS,
  '/positions/traspasos': () => ({ habilitado: true, traspasos: [{ id: 'abc', fecha: '2026-11-20', asset: 'NVDA', cantidad: 10,
    broker_origen: 'Cocos', broker_destino: 'Balanz', estado: 'vivo', puede_deshacer: false, motivo: MOTIVO }] }),
}
vi.mock('../../utils/api', async (orig) => ({
  ...(await orig()),
  api: {
    get: vi.fn((ruta) => {
      const k = Object.keys(RESPUESTAS).sort((a, b) => b.length - a.length).find(c => ruta.startsWith(c))
      return Promise.resolve(k ? RESPUESTAS[k]() : [])
    }),
    post: vi.fn(() => Promise.resolve({ items: [] })),
    delete: vi.fn(() => Promise.resolve({})),
  },
}))

let Operations
beforeAll(async () => {
  instalarNavegadorMinimo()
  window.matchMedia = (q) => ({ matches: /reduce/.test(q), addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })
  ;({ default: Operations } = await import('../../pages/Operations'))
}, 60000)
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null; localStorage.clear(); avisos.length = 0 })

async function movimientos(ojito) {
  localStorage.setItem('rendi_privacy', ojito ? '1' : '0')
  // Sin agrupar: cada fila con su tacho (o sin él) a la vista.
  localStorage.setItem('rendi_movements_group', 'none')
  const el = () => h(PrivacyProvider, null, h(MemoryRouter, { initialEntries: ['/operaciones'] },
    h(Routes, null, h(Route, { path: '/operaciones', element: h(Operations) }))))
  montado = await montar(el())
  for (let i = 0; i < 8; i++) await montado.redibujar(el())
  return { el, leer: () => texto(montado.contenedor) }
}

// Los botones con ese `aria-label` (el tacho de cada fila dice «Borrar movimiento»).
function contarConEtiqueta(raiz, etiqueta) {
  let n = 0
  const pila = [raiz]
  while (pila.length) {
    const x = pila.shift()
    if (x.nodeName === 'BUTTON' && x.atributos?.['aria-label'] === etiqueta) n++
    pila.push(...(x.childNodes || []))
  }
  return n
}

describe('Movimientos con un pase entre brokers', () => {
  it('el botón «Pases» aparece con su número y deja sólo las filas del pase', async () => {
    const p = await movimientos(false)
    const boton = buscarBoton(montado.contenedor, 'Pases')
    expect(boton, 'el filtro «Pases» no aparece').not.toBeNull()
    expect(texto(boton)).toBe('Pases3')            // las dos patas y el gasto del trámite
    expect(p.leer()).toContain('4.321')
    await clic(montado.contenedor, boton)
    for (let i = 0; i < 4; i++) await montado.redibujar(p.el())
    const t = p.leer()
    expect(t).toContain('Pase (salió)')
    expect(t).toContain('Pase (entró)')
    expect(t).toContain('10 NVDA → Balanz')
    expect(t).not.toContain('4.321')               // el depósito queda afuera
    expect(t).not.toContain('911,11')              // la compra original, también
  })

  it('sólo el depósito tiene tacho: ni las patas, ni el gasto, ni la compra `trp-…`', async () => {
    const p = await movimientos(false)
    expect(p.leer()).toContain('911,11')          // la compra `trp-…` está en la lista…
    expect(contarConEtiqueta(montado.contenedor, 'Borrar movimiento')).toBe(1)   // …pero sin tacho
    expect(buscarBoton(montado.contenedor, 'Deshacer pase')).not.toBeNull()
  })

  it('«Deshacer pase» que no se puede: el porqué del servidor, con el monto tapado si el ojito está prendido', async () => {
    const p0 = await movimientos(false)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Deshacer pase'))
    for (let i = 0; i < 4; i++) await montado.redibujar(p0.el())
    expect(avisos.map(a => a.t)).toContain(MOTIVO)   // apagado se ve (si no, la prueba no prueba nada)
    await montado.desmontar(); montado = null; avisos.length = 0

    const p = await movimientos(true)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Deshacer pase'))
    for (let i = 0; i < 4; i++) await montado.redibujar(p.el())
    const dicho = avisos.map(a => a.t).join(' | ')
    expect(dicho).toContain('Volvé a dejarlos como llegaron (10 a ••••••)')
    expect(dicho).not.toContain('1.234,56')
  })
})
