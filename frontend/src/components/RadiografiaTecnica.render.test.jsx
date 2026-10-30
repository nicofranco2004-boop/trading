// Lo que DIBUJAN las dos tarjetas del % de tu cartera en tendencia alcista. El
// número no se calcula en la pantalla (28/10): llega armado del servidor
// (`reparto`: senales_semana.reparto, la cuenta única), así que acá se mira que
// se dibuje tal cual, con sus palabras.
//   · La Cartera, corta (recuadro 21c): el renglón con «la semana pasada» y el
//     link a Análisis técnico; sin barra y sin «Lo que cambió esta semana».
//   · La tarjeta grande del Panorama: barra, grupos y POR QUÉ cada uno va sin
//     lectura (antes decía siempre «Bonos, fondos y efectivo…», falso para una
//     acción recién agregada que todavía no tiene velas).
import { describe, it, expect, beforeEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import RadiografiaTecnica, { TarjetaPlata } from './RadiografiaTecnica'
import { PrivacyProvider } from '../contexts/PrivacyContext'
import { MOTIVOS_SIN_LECTURA } from '../utils/radiografia'
import { setBrokersRegistry } from '../utils/valuation'

beforeEach(() => setBrokersRegistry([
  { id: 1, name: 'IOL', currency: 'ARS' },
  { id: 2, name: 'Schwab', currency: 'USD' },
]))

import { hoyISO } from '../utils/fecha'
const diasAtras = (n) => new Date(Date.parse(hoyISO() + 'T00:00:00Z') - n * 86400000).toISOString().slice(0, 10)
const haceSiete = diasAtras(7)
// Como lo manda el servidor (POST /api/tecnico/cartera → reparto, GET /api/tus-senales → alcista).
const REPARTO = {
  pct: 54,
  grupos: {
    alcista: { pct: 54, fraccion: 0.54, nombres: ['NVDA', 'SPY'] },
    bajista: { pct: 29, fraccion: 0.29, nombres: ['MELI'] },
    sin: { pct: 17, fraccion: 0.17, nombres: ['AL30', 'GGAL', 'FCI:PIONERO-PESOS', 'efectivo'] },
  },
  motivos: [
    { porque: 'no_se_mide', nombres: ['AL30', 'FCI:PIONERO-PESOS', 'efectivo'] },
    { porque: 'sin_historia', nombres: ['GGAL'] },
  ],
  semana_pasada: { semana: haceSiete, pct: 61 },
}
const LOTES = [{ id: 1, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK' }]
const conRouter = (el) => renderToStaticMarkup(<MemoryRouter><PrivacyProvider>{el}</PrivacyProvider></MemoryRouter>)
const sinEtiquetas = (html) => html.replace(/<[^>]+>/g, '').replace(/&#x27;|&#39;/g, "'")

describe('la Cartera, corta (recuadro 21c)', () => {
  it('el renglón con la semana pasada y el link; sin barra ni «Lo que cambió esta semana»', () => {
    const html = conRouter(<RadiografiaTecnica lotes={LOTES} reparto={REPARTO} cargando={false} />)
    const t = sinEtiquetas(html)
    expect(t).toContain('54% de tu cartera está en activos con tendencia alcista de largo plazo (la semana pasada, 61%)')
    expect(html).toContain('href="/analisis-tecnico"')
    expect(t).toContain('Ver análisis técnico')
    expect(html).not.toContain('role="img"')                 // la barra vive en el Panorama
    expect(t).not.toContain('Lo que cambió esta semana')
  })
  it('«la semana pasada» sólo a los 7 días justos; si no, el sábado con su fecha (la regla de Señales)', () => {
    // Un sábado que NO es de hace 7 días justos (el resumen guardado siempre es de
    // un sábado). Antes era «hace 5 días», que es sábado sólo los jueves: la
    // prueba daba rojo los otros seis días (visto al juntar, 30/10; igual en 31c00ff6).
    const n = [8, 9, 10, 11, 12, 13, 14].find(k => new Date(diasAtras(k) + 'T12:00:00Z').getUTCDay() === 6)
    const sabado = diasAtras(n)
    const [, m, d] = sabado.split('-')
    const t = sinEtiquetas(conRouter(<RadiografiaTecnica lotes={LOTES} reparto={{ ...REPARTO, semana_pasada: { semana: sabado, pct: 61 } }} cargando={false} />))
    expect(t).toContain(`(el sábado ${d}/${m}, 61%)`)
  })
  it('sin la semana pasada guardada, esa parte no aparece', () => {
    const t = sinEtiquetas(conRouter(<RadiografiaTecnica lotes={LOTES} reparto={{ ...REPARTO, semana_pasada: null }} cargando={false} />))
    expect(t).toContain('54% de tu cartera está en activos con tendencia alcista de largo plazo')
    expect(t).not.toContain('semana pasada')
  })
  it('si el pedido falla lo dice, y si nada tiene lectura también (nunca inventa un %)', () => {
    expect(sinEtiquetas(conRouter(<RadiografiaTecnica lotes={LOTES} reparto={null} error cargando={false} />)))
      .toContain('no pudimos cargar el análisis técnico')
    expect(sinEtiquetas(conRouter(<RadiografiaTecnica lotes={LOTES} reparto={{ ...REPARTO, pct: null }} cargando={false} />)))
      .toContain('Ninguno de tus activos tiene todavía suficiente historia de precios')
  })
})

describe('la tarjeta grande del Panorama', () => {
  it('barra, grupos con nombres y por qué cada uno va sin lectura', () => {
    const html = conRouter(<TarjetaPlata reparto={REPARTO} titulo="Tu cartera en tendencia alcista de largo plazo" />)
    const t = sinEtiquetas(html)
    expect(t).toContain('54% de tu cartera está en activos con tendencia alcista de largo plazo.')
    expect(t).toContain('(la semana pasada, 61%)')
    expect(html).toContain('aria-label="54% alcista, 29% bajista, 17% sin lectura"')
    expect(t).toContain('29% bajista · MELI')
    expect(t).toContain(`AL30, Pionero Pesos, efectivo: ${MOTIVOS_SIN_LECTURA.no_se_mide}`)
    expect(t).toContain(`GGAL: ${MOTIVOS_SIN_LECTURA.sin_historia}`)
    expect(t).toContain('va a aparecer mañana')
  })
})
