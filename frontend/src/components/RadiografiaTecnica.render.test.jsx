// Lo que DIBUJAN las dos tarjetas del % de tu plata en tendencia alcista. El
// número no se calcula en la pantalla (28/10): llega armado del servidor
// (`reparto`: senales_semana.reparto, la cuenta única), así que acá se mira que
// se dibuje tal cual, con sus palabras.
//   · La Cartera, corta (recuadro 21c): el renglón con «la semana pasada» y el
//     link a Análisis técnico; sin barra y sin «Lo que cambió esta semana».
//   · La tarjeta grande del Panorama: barra, grupos y POR QUÉ cada uno va sin
//     lectura (antes decía siempre «Bonos, fondos y efectivo…», falso para una
//     acción recién agregada que todavía no tiene velas).
import { describe, it, expect, beforeEach, vi } from 'vitest'
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
    expect(t).toContain('54% de tu plata está en tendencia de fondo alcista (la semana pasada, 61%)')
    // A Panorama (la barra y los grupos de este número), no a la entrada (el gráfico).
    expect(html).toContain('href="/analisis-tecnico?tab=panorama"')
    expect(t).toContain('Ver análisis técnico')
    expect(html).not.toContain('role="img"')                 // la barra vive en el Panorama
    expect(t).not.toContain('Lo que cambió esta semana')
  })
  it('«la semana pasada» sólo a los 7 días justos; si no, el sábado con su fecha (la regla de Señales)', () => {
    // El servidor guarda el % SÓLO los sábados (senales_semana.correr_si_toca) y
    // manda el último de antes de hoy: «semana» es siempre el sábado anterior, a
    // 1–7 días. Antes la prueba usaba «hoy − 5», que es sábado sólo los jueves.
    // Se recorre una semana entera con el reloj fijo: el sábado (a 7 días justos)
    // dice «la semana pasada»; los otros seis días, «el sábado DD/MM».
    vi.useFakeTimers()
    try {
      for (let dia = 24; dia <= 30; dia++) {               // sáb 24/10 … vie 30/10/2026
        vi.setSystemTime(new Date(2026, 9, dia, 12))
        const atras = (new Date().getDay() + 1) % 7 || 7   // días hasta el sábado anterior
        const sabado = diasAtras(atras)
        const [, m, d] = sabado.split('-')
        const t = sinEtiquetas(conRouter(<RadiografiaTecnica lotes={LOTES} reparto={{ ...REPARTO, semana_pasada: { semana: sabado, pct: 61 } }} cargando={false} />))
        expect(t).toContain(atras === 7 ? '(la semana pasada, 61%)' : `(el sábado ${d}/${m}, 61%)`)
      }
    } finally {
      vi.useRealTimers()
    }
  })
  it('sin la semana pasada guardada, esa parte no aparece', () => {
    const t = sinEtiquetas(conRouter(<RadiografiaTecnica lotes={LOTES} reparto={{ ...REPARTO, semana_pasada: null }} cargando={false} />))
    expect(t).toContain('54% de tu plata está en tendencia de fondo alcista')
    expect(t).not.toContain('semana pasada')
  })
  it('si el pedido falla lo dice, y si nada tiene lectura también (nunca inventa un %)', () => {
    expect(sinEtiquetas(conRouter(<RadiografiaTecnica lotes={LOTES} reparto={null} error cargando={false} />)))
      .toContain('No pudimos traer el análisis técnico')
    expect(sinEtiquetas(conRouter(<RadiografiaTecnica lotes={LOTES} reparto={{ ...REPARTO, pct: null }} cargando={false} />)))
      .toContain('Ninguno de tus activos tiene todavía una tendencia de fondo')
  })
})

describe('la tarjeta grande del Panorama', () => {
  it('barra, grupos con nombres y por qué cada uno va sin lectura', () => {
    const html = conRouter(<TarjetaPlata reparto={REPARTO} titulo="Tu plata en tendencia de fondo alcista" />)
    const t = sinEtiquetas(html)
    expect(t).toContain('54% de tu plata está en tendencia de fondo alcista.')
    expect(t).toContain('(la semana pasada, 61%)')
    expect(html).toContain('aria-label="54% alcista, 29% bajista, 17% sin lectura"')
    expect(t).toContain('29% bajista · MELI')
    expect(t).toContain(`AL30, Pionero Pesos, efectivo: ${MOTIVOS_SIN_LECTURA.no_se_mide}`)
    expect(t).toContain(`GGAL: ${MOTIVOS_SIN_LECTURA.sin_historia}`)
    expect(t).toContain('aparece en un día')
  })
})
