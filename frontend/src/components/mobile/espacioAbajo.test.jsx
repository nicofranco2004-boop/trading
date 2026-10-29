// D8 (auditoría D, 29/10): en el celular, el final de las páginas nuevas (el
// aviso «no es una recomendación» de Análisis técnico) quedaba debajo de los
// botones flotantes de Mervall-E y WhatsApp, y la ayuda «?» de «Beta» de la
// ficha se abría detrás de ellos. El espacio de abajo medía la barra (64 px)
// y no los botones apoyados encima (hasta 128 px). Ahora una sola cuenta
// (espacioAbajo.js) para la barra, los dos botones y lo que los esquiva.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, clic, medidas } from '../../testing/navegadorMinimo'
import { ESPACIO_ABAJO_CELULAR, FLOTANTES_DESDE_ABAJO, FLOTANTES_ALTO, BARRA_ABAJO } from './espacioAbajo'
import fuenteBarra from './MobileTabBar.jsx?raw'
import fuenteMervalle from '../voz/RendiMate.jsx?raw'
import fuenteWhatsapp from '../SupportWhatsAppFab.jsx?raw'

describe('D8 · lo de abajo no tapa el final de la página', () => {
  it('el espacio del final alcanza para la barra y los botones flotantes', () => {
    expect(ESPACIO_ABAJO_CELULAR).toBeGreaterThanOrEqual(FLOTANTES_DESDE_ABAJO + FLOTANTES_ALTO)
    expect(FLOTANTES_DESDE_ABAJO).toBeGreaterThanOrEqual(BARRA_ABAJO)
    // Los dos espacios de la barra (asesor y persona) usan esa cuenta, no 64 px.
    expect(fuenteBarra).not.toMatch(/h-\[64px\]/)
    expect(fuenteBarra.match(/style=\{ESPACIO_STYLE\}/g)).toHaveLength(2)
  })

  it('los dos botones flotantes están donde dice la cuenta', () => {
    expect(fuenteWhatsapp).toMatch(/bottom: FLOTANTES_DESDE_ABAJO/)
    // Mervall-E arranca a 80 px (clase de Tailwind: tiene que ser un literal).
    expect(fuenteMervalle).toContain(`bottom-[calc(${FLOTANTES_DESDE_ABAJO}px_+_env(safe-area-inset-bottom))]`)
    expect(fuenteMervalle).toMatch(/w-12|h-12|py-1/)   // ≤ 48 px de alto
  })
})

describe('D8 · el globo de ayuda se da vuelta si abajo lo taparían', () => {
  let InfoTooltip, montado
  beforeAll(async () => {
    instalarNavegadorMinimo()
    ;({ default: InfoTooltip } = await import('../InfoTooltip'))
  })
  afterAll(() => { vi.unstubAllGlobals() })
  afterEach(async () => { medidas(null); if (montado) await montado.desmontar(); montado = null })

  async function abrir({ ancho, botonTop }) {
    window.innerWidth = ancho
    document.documentElement.clientWidth = ancho
    window.innerHeight = 812
    // El «?» en `botonTop`; el globo, de 120 px, abajo de él.
    medidas(n => (n.getAttribute?.('role') === 'tooltip'
      ? { left: 20, top: botonTop + 18, width: 256, height: 120 }
      : n.nodeName === 'SPAN' && n.getAttribute?.('class')?.includes('relative inline-block')
        ? { left: 20, top: botonTop, width: 14, height: 14 } : null))
    const el = h(InfoTooltip, { label: 'Qué es Beta' }, h('p', null, 'Cuánto se mueve contra el S&P 500.'))
    montado = await montar(el)
    const boton = montado.contenedor.childNodes[0].childNodes[0]
    await clic(montado.contenedor, boton)
    for (let i = 0; i < 3; i++) await montado.redibujar(el)
    const globo = montado.contenedor.childNodes[0].childNodes[1]
    return globo.getAttribute('class')
  }

  it('celular, el «?» cerca de abajo: se abre hacia arriba', async () => {
    const c = await abrir({ ancho: 375, botonTop: 640 })   // 640 + 18 + 120 = 778 > 812 − 136
    expect(c).toContain('bottom-full')
  })

  it('celular, con lugar abajo: se abre abajo, como siempre', async () => {
    const c = await abrir({ ancho: 375, botonTop: 200 })
    expect(c).toContain('top-full')
  })

  it('compu: no hay barra ni botones abajo que esquivar', async () => {
    const c = await abrir({ ancho: 1440, botonTop: 640 })
    expect(c).toContain('top-full')
  })
})
