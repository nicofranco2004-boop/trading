// Lo que DIBUJA la radiografía cuando algo va «sin lectura»: el texto tiene que
// decir por qué es CADA uno. Antes decía siempre «Bonos, fondos y efectivo no
// tienen historia de precios» — falso para una acción recién agregada que todavía
// no tiene velas guardadas (GGAL, en la copia con las 4 piezas juntas, 22/10).
import { describe, it, expect, beforeEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import RadiografiaTecnica, { TendenciaChip } from './RadiografiaTecnica'
import { PrivacyProvider } from '../contexts/PrivacyContext'
import { indexarLecturas, MOTIVOS_SIN_LECTURA } from '../utils/radiografia'
import { setBrokersRegistry } from '../utils/valuation'

beforeEach(() => setBrokersRegistry([
  { id: 1, name: 'IOL', currency: 'ARS' },
  { id: 2, name: 'Schwab', currency: 'USD' },
]))

const hoy = new Date().toISOString().slice(0, 10)
const ALCISTA = { ruedas: 760, fecha: hoy, media200: 90, dist_media200: 11, pendiente_media200: 2, media50: 95, dist_media50: 5, rsi: 60 }
const dibujar = (lotes, lecturas) => renderToStaticMarkup(
  <MemoryRouter><PrivacyProvider>
    <RadiografiaTecnica lotes={lotes} valorDe={() => 100} indice={indexarLecturas(lecturas)} cargando={false} />
  </PrivacyProvider></MemoryRouter>,
)
const sinEtiquetas = (html) => html.replace(/<[^>]+>/g, '').replace(/&#x27;|&#39;/g, "'")

describe('radiografía: por qué cada uno va sin lectura', () => {
  it('una acción sin velas todavía: «aparece en un día», no «bonos, fondos y efectivo»', () => {
    const texto = sinEtiquetas(dibujar(
      [
        { id: 1, broker: 'IOL', asset: 'GGAL', asset_type: 'ACCION' },
        { id: 2, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK' },
      ],
      [{ asset: 'GGAL', local: true, disponible: false }, { asset: 'NVDA', local: false, disponible: true, lectura: ALCISTA, cambios: [] }],
    ))
    expect(texto).toContain(`GGAL: ${MOTIVOS_SIN_LECTURA.sin_historia}`)
    expect(texto).toContain('aparece en un día')
    expect(texto.toLowerCase()).not.toContain('bonos, fondos')
  })

  it('cada motivo con sus activos: bono y efectivo no se miden; la acción nueva aparece en un día', () => {
    const texto = sinEtiquetas(dibujar(
      [
        { id: 1, broker: 'IOL', asset: 'AL30', asset_type: 'BONO' },
        { id: 2, broker: 'IOL', asset: 'ARS', is_cash: true },
        { id: 3, broker: 'IOL', asset: 'FCI:PIONERO-PESOS', asset_type: 'FUND' },
        { id: 4, broker: 'IOL', asset: 'GGAL', asset_type: 'ACCION' },
      ],
      [{ asset: 'AL30', local: true, disponible: false }, { asset: 'GGAL', local: true, disponible: false }],
    ))
    expect(texto).toMatch(new RegExp(`AL30, efectivo, Pionero Pesos: ${MOTIVOS_SIN_LECTURA.no_se_mide.slice(0, 20)}`))
    expect(texto).toContain(`GGAL: ${MOTIVOS_SIN_LECTURA.sin_historia}`)
  })

  it('el globo de la fila también dice el motivo correcto', () => {
    const bono = renderToStaticMarkup(<TendenciaChip x={null} p={{ asset: 'AL30', asset_type: 'BONO' }} />)
    const accion = renderToStaticMarkup(<TendenciaChip x={{ asset: 'GGAL', disponible: false }} p={{ asset: 'GGAL', asset_type: 'ACCION' }} />)
    expect(bono).toContain('no se les mide la tendencia')
    expect(accion).toContain('aparece en un día')
    expect(accion).not.toContain('Bonos')
  })
})

describe('radiografía: «Lo que cambió esta semana» se mudó a Análisis técnico (28/10)', () => {
  it('la Cartera queda con el % y un link a Análisis técnico, sin la caja de cambios', () => {
    const html = dibujar(
      [{ id: 2, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK' }],
      [{ asset: 'NVDA', local: false, disponible: true, lectura: ALCISTA, cambios: [{ tipo: 'media200', sentido: 'arriba', fecha: hoy }] }],
    )
    const texto = sinEtiquetas(html)
    expect(texto).toContain('100% de tu plata está en activos con tendencia de fondo alcista')
    expect(html).toContain('href="/analisis-tecnico"')
    expect(texto).toContain('Ver análisis técnico')
    expect(texto).not.toContain('Lo que cambió esta semana')
    expect(texto).not.toContain('pasó arriba de su promedio')
  })
})
