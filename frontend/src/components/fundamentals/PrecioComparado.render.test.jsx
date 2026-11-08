// Comparar → Precio, dibujado: lo que dice arriba del gráfico con lo que contesta el
// servidor (backend/tests/fixtures/comparar_precio.json, que test_comparar_precio.py
// compara con su salida). La frase de por qué todos arrancan en 100 ese día estaba
// escrita adentro del componente y ninguna prueba la miraba: volverla atrás quedaba en
// verde (auditoría 08/11 de las pruebas del hueco, F04).
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, enActo } from '../../testing/navegadorMinimo'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() }))
vi.mock('../../utils/api', () => ({ api, getClientContext: () => null, EVENTO_CUENTA_CAMBIADA: 'rendi:cuenta-cambiada' }))
vi.mock('../../utils/track', () => ({ track: () => {} }))
// Sin tenencias: el plazo es «1 año», el de las respuestas guardadas. El MISMO objeto en
// cada dibujo, como el hook de verdad: uno nuevo cada vez volvía a pedir sin fin.
const sinLotes = vi.hoisted(() => ({ posiciones: [], operaciones: [] }))
vi.mock('../../hooks/useLotesDeLaCuenta', () => ({ useLotesDeLaCuenta: () => sinLotes }))
vi.mock('recharts', () => {
  const nada = () => null
  return {
    ResponsiveContainer: ({ children }) => children,
    LineChart: ({ children }) => children ?? null,
    XAxis: nada, YAxis: nada, CartesianGrid: nada, Tooltip: nada, ReferenceLine: nada, Line: nada,
  }
})

const COMPARAR = JSON.parse(readFileSync(resolve(dirname(fileURLToPath(import.meta.url)),
  '../../../../backend/tests/fixtures/comparar_precio.json'), 'utf8'))

const esperar = async () => { for (let i = 0; i < 8; i++) await enActo(async () => { await new Promise(r => setTimeout(r, 0)) }) }
let montado = null

beforeAll(() => { instalarNavegadorMinimo() })
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
})

async function abrir(res, tickers) {
  api.get.mockImplementation(async () => res)
  const { default: PrecioComparado } = await import('./PrecioComparado')
  montado = await montar(h(PrecioComparado, { tickers }))
  await esperar()
  return texto(montado.contenedor)
}

describe('Comparar → Precio: por qué todos arrancan en 100 ese día', () => {
  it('con un hueco de precios justo antes, dice qué días faltan (Nico, 08/11)', async () => {
    expect(await abrir(COMPARAR.hueco, ['MU']))
      .toContain('Todos arrancan en 100 el 18/11/25 (faltan los precios de MU del 15/10/25 al 17/11/25)')
  })

  it('con uno que cotiza hace menos, lo nombra', async () => {
    expect(await abrir(COMPARAR.corrida_por, ['MU', 'NUEV']))
      .toContain('Todos arrancan en 100 el 05/01/26 (de NUEV tenemos precios desde ese día)')
  })

  it('sin nada raro, sólo el día', async () => {
    const t = await abrir(COMPARAR.normal, ['MU'])
    expect(t).toContain('Todos arrancan en 100 el 04/11/25')
    expect(t).not.toMatch(/Todos arrancan en 100 el 04\/11\/25 \(/)
  })
})
