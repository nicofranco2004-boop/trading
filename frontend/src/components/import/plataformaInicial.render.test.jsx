import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, enActo, texto } from '../../testing/navegadorMinimo'

// `plataformaInicial` del importador: la bienvenida (pages/Onboarding.jsx) ya
// preguntó el broker, así que el asistente no lo vuelve a preguntar y arranca
// en la subida, con el export soportado de esa plataforma. Sin la prop, el
// asistente es el de siempre (Paso 0). Se monta el ImportWizard REAL; sólo se
// responden los pedidos.

const GRUPOS = [
  { platform: 'generic', platform_label: 'Genérico', exports: [{ id: 'rendi_generic', label: 'Plantilla', supported: true }] },
  { platform: 'cocos', platform_label: 'Cocos Capital', exports: [{ id: 'cocos', label: 'Movimientos', supported: true }] },
  { platform: 'binance', platform_label: 'Binance', exports: [{ id: 'binance', label: 'Spot', supported: true }] },
]
let grupos = GRUPOS
vi.mock('../../utils/api', async (o) => ({
  ...(await o()),
  api: {
    get: vi.fn(async (url) => {
      if (url.startsWith('/imports/parsers/grouped')) {
        if (grupos instanceof Error) throw grupos
        return grupos
      }
      if (url.startsWith('/plan/features')) return { tier: 'pro', trial: null }
      return []
    }),
    post: vi.fn(async () => ({})),
  },
}))
vi.mock('./WallbitConnect', () => ({ default: () => null }))

let ImportWizard
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: ImportWizard } = await import('./ImportWizard'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null; grupos = GRUPOS })

async function abrir(props = {}) {
  montado = await montar(h(ImportWizard, { onClose: () => {}, ...props }))
  for (let i = 0; i < 6; i++) await enActo(async () => { await new Promise(r => setTimeout(r, 0)) })
  return texto(montado.contenedor)
}

const PASO_0 = '¿Cómo querés traer tus operaciones?'
const SUBIDA = 'Soltá tu CSV o Excel'

describe('ImportWizard con plataformaInicial', () => {
  it('sin la prop: arranca en el Paso 0, como siempre', async () => {
    const t = await abrir()
    expect(t).toContain(PASO_0)
    expect(t).not.toContain(SUBIDA)
  })

  it('con un broker: saltea el Paso 0 y queda en la subida con ese broker elegido', async () => {
    const t = await abrir({ plataformaInicial: 'cocos' })
    expect(t).not.toContain(PASO_0)
    expect(t).toContain(SUBIDA)
    expect(t).toContain('Importando un export de Cocos Capital')
  })

  it('con la planilla («personal»): queda en el Paso 0 con la plantilla de Rendi elegida (la moneda y el broker se eligen ahí)', async () => {
    const t = await abrir({ plataformaInicial: 'personal' })
    expect(t).toContain('¿En qué moneda están las operaciones?')
    expect(t).not.toContain(SUBIDA)
  })

  it('si la lista de brokers no llega, no se queda colgado: muestra el Paso 0', async () => {
    grupos = new Error('sin red')
    const t = await abrir({ plataformaInicial: 'cocos' })
    expect(t).not.toContain('Preparando la subida')
    expect(t).toContain(PASO_0)
  })
})
