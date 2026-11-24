// /mensual con un pase entre brokers, la pantalla MONTADA (testing/navegadorMinimo.js)
// con el servidor simulado en la frontera (utils/api).
//
// Revisión E12, problema 2: en el mes en curso el % suma el no realizado, y los
// títulos llegan al broker de destino (B) con su costo ORIGINAL. Ese no realizado
// ya trae la ganancia vieja (V − C), y el puente de entrada −(V − C) es lo que la
// compensa. La primera versión sacaba el puente también en el mes en curso: el
// monto de la fila decía +US$ 10 y el % decía +21 %. Lo correcto (y lo que fija
// esto): en el mes en curso el % cuenta lo mismo que el monto (+1 %); en un mes
// cerrado el puente se saca (no se vendió nada), como pide la spec (E.7).
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { instalarNavegadorMinimo, montar, texto } from '../testing/navegadorMinimo'
import { PrivacyProvider } from '../contexts/PrivacyContext'
import { pctSigned } from '../utils/format'
import { hoyISO } from '../utils/fecha'

vi.mock('../contexts/CurrencyContext', async (orig) => ({
  ...(await orig()),
  useCurrency: () => ({ currency: 'USD', valuationDollar: 'mep', costBasis: 'purchase', tcValuacion: 1400 }),
  pickFinancialRate: (d) => d?.mep?.venta ?? null,
}))
vi.mock('../hooks/useFxHistory', () => ({ useDolarMensual: () => ({ dolarMes: {}, tcEnFecha: () => 1400 }) }))
vi.mock('./Toast', () => ({ useToast: () => ({ push: () => {}, success: () => {}, error: () => {}, info: () => {} }) }))

// El mes en curso es el del reloj (el cierre automático del mes de la pantalla
// usa `new Date()`), y el reloj está FIJO (vite.config: miércoles 18/11/2026 al
// mediodía): con el de la compu, la prueba cambiaba de mes a medianoche. Con
// todas las cuentas ya en noviembre no se cierra ni se abre ningún mes.
const fila = (id, broker, ym, campos) => ({ id, broker, ...ym, deposits: 0, withdrawals: 0, pnl_realized: 0, pnl_unrealized: 0,
  capital_inicio: 1000, capital_final: 1000, ...campos })
const NOV = { year: 2026, month: 11 }
const OCT = { year: 2026, month: 10 }
const ENTRADAS = [
  fila(1, 'global', OCT, {}),
  fila(2, 'global', NOV, {}),
  fila(3, 'IBKR', NOV, {}),
  // Schwab (B), mes CERRADO: vendió algo por +50 y le llegaron títulos con
  // C = 100 que valían 300 → el realizado trae 50 − 200. El % del mes: +5 %.
  fila(4, 'Schwab', OCT, { pnl_realized: 50 - 200, puente_entrada_usd: 200, capital_final: 1000 + 200 - 150, deposits: 200 }),
  // Schwab (B), mes EN CURSO: arranca con 1.000, le llegan títulos con C = 100
  // que valían 300, hoy valen 310. Realizado −200; no realizado 310 − 100 = 210.
  fila(5, 'Schwab', NOV, { pnl_realized: -200, puente_entrada_usd: 200, pnl_unrealized: 210, deposits: 300 }),
]
vi.mock('../utils/api', async (orig) => ({
  ...(await orig()),
  api: {
    get: vi.fn((ruta) => Promise.resolve(
      ruta.startsWith('/monthly') ? ENTRADAS
        : ruta.startsWith('/brokers') ? [{ id: 1, name: 'IBKR', currency: 'USD' }, { id: 2, name: 'Schwab', currency: 'USD' }]
          : ruta.startsWith('/dolar') ? { mep: { venta: 1400, compra: 1390 } }
            : ruta.startsWith('/config') ? { tc_blue: 1400 }
              : ruta.startsWith('/prices') ? {} : [])),
    post: vi.fn(() => Promise.resolve({})),
    put: vi.fn(() => Promise.resolve({})),
  },
}))

let MonthlySummary
beforeAll(async () => {
  // Sólo la fecha simulada: los tiempos de espera siguen siendo los de verdad.
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-11-18T15:00:00Z'))
  instalarNavegadorMinimo()
  window.matchMedia = (q) => ({ matches: /reduce/.test(q), addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })
  ;({ default: MonthlySummary } = await import('./MonthlySummary'))
}, 60000)
afterAll(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null; localStorage.clear() })

// Las celdas en negrita de cada fila: el resultado en plata y el % (`pctSigned(retPct)`).
function celdasDelResultado(raiz) {
  const out = []
  const pila = [raiz]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'TD' && /font-bold tabular/.test(n.atributos?.class || '')) out.push(texto(n))
    pila.push(...(n.childNodes || []))
  }
  return out
}

describe('/mensual · el % de la fila de un broker con un pase', () => {
  it('mes en curso: el % cuenta lo mismo que el monto (+1 %, no +21 %); mes cerrado: sin el puente (+5 %)', async () => {
    expect(hoyISO(), 'el reloj fijo no se aplicó').toBe('2026-11-18')
    const el = () => h(PrivacyProvider, null, h(MemoryRouter, { initialEntries: ['/mensual?broker=Schwab'] }, h(MonthlySummary)))
    montado = await montar(el())
    for (let i = 0; i < 8; i++) await montado.redibujar(el())
    const t = texto(montado.contenedor)
    // El renglón que explica el puente, debajo del realizado de cada fila.
    expect(t).toContain('Descuenta USD 200,00: los títulos que llegaron desde otro broker ya traían esa ganancia (no es una pérdida).')
    // Las filas en orden: el mes cerrado y después el mes en curso, cada una con
    // su resultado en plata (que SÍ trae el puente) y su %.
    const celdas = celdasDelResultado(montado.contenedor)
    expect(celdas).toEqual(['$(150,00)', pctSigned(0.05), '$10,00', pctSigned(0.01)])
    expect(celdas).not.toContain(pctSigned(0.21))
  }, 60000)
})
