// Dos cosas del celular que la auditoría midió en un navegador de verdad (31/10):
//   · D2: en la ficha, «Ordenar por · Técnico primero · Fundamental primero»
//     medía 348 px y en un celular de 375 quedan 343: la página se corría de
//     costado. La causa era el Segmento (components/asset/Segmento.jsx), que
//     usan también Comparar (moneda y plazo) y Análisis fundamental: sus
//     botones no se podían achicar por debajo de su texto (`nowrap` y un hijo
//     de flex sin `min-w-0`). Ahora, si no entra, el texto se parte en dos
//     renglones; en la compu, todo igual.
//   · D7: el «?» (InfoTooltip, 13×13 px) era casi imposible de tocar con el
//     dedo. Ahora un `::before` invisible agranda el área (25 px con mouse, 45
//     con el dedo) sin agrandar el ícono ni mover nada.
// jsdom no mide; esto dibuja los componentes de verdad y compila sus clases con
// el Tailwind del proyecto, así una clase mal escrita (que no genera CSS) da
// rojo. Medido en Chrome a 375 px (y 320): el renglón entra justo (343 de 343),
// el ícono sigue en 13×13 y el toque cuenta hasta 22 px del centro.
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import postcss from 'postcss'
import tailwindcss from 'tailwindcss'
import config from '../../tailwind.config.js'
import Segmento from './asset/Segmento'
import InfoTooltip from './InfoTooltip'
import fuenteFicha from '../pages/AssetDetail.jsx?raw'

const clases = (html, etiqueta) => [...html.matchAll(new RegExp(`<${etiqueta}[^>]*class="([^"]*)"`, 'g'))]
  .map(m => m[1].replace(/&#x27;/g, "'").split(/\s+/))
const css = async (html) => (await postcss([tailwindcss({ ...config, content: [{ raw: html.replace(/&#x27;/g, "'") }] })])
  .process('@tailwind utilities;', { from: undefined })).css
const regla = (hoja, selector) => {
  const i = hoja.indexOf(selector)
  return i < 0 ? null : hoja.slice(i, hoja.indexOf('}', i) + 1)
}

describe('D2: el Segmento estirado se achica en el celular', () => {
  const html = renderToStaticMarkup(
    <Segmento etiqueta="Ordenar la ficha" valor="tecnico" alElegir={() => {}} estirar
      opciones={[['tecnico', 'Técnico primero'], ['fundamental', 'Fundamental primero']]} />)

  it('los botones pueden achicarse y partir el texto; en la compu, en un renglón', async () => {
    const [grupo] = clases(html, 'div')
    expect(grupo).toContain('min-w-0')
    for (const b of clases(html, 'button')) {
      expect(b).toContain('min-w-0')
      expect(b).toContain('whitespace-normal')
      expect(b, 'el «nowrap» sólo desde sm (la compu)').not.toContain('whitespace-nowrap')
      expect(b).toContain('sm:whitespace-nowrap')
    }
    const hoja = await css(html)
    expect(regla(hoja, '.min-w-0')).toContain('min-width: 0px')
    expect(regla(hoja, '.whitespace-normal')).toContain('white-space: normal')
    expect(hoja).toMatch(/@media \(min-width: 640px\)[\s\S]*\.sm\\:whitespace-nowrap/)
  })

  it('sin estirar, como antes (en un renglón)', () => {
    const solo = renderToStaticMarkup(<Segmento etiqueta="x" valor="a" alElegir={() => {}} opciones={[['a', 'Uno'], ['b', 'Dos']]} />)
    for (const b of clases(solo, 'button')) expect(b).toContain('whitespace-nowrap')
  })

  it('la ficha usa el Segmento estirado para «Ordenar por»', () => {
    expect(fuenteFicha).toMatch(/<Segmento etiqueta="Ordenar la ficha"[^>]*\bestirar\b/)
  })
})

describe('D7: el «?» se toca sin acertarle a 13 píxeles', () => {
  const html = renderToStaticMarkup(<p>Drawdown <InfoTooltip><p>Caída desde el máximo.</p></InfoTooltip></p>)

  it('el ícono no cambia de tamaño; el área que se toca, sí', async () => {
    expect(html).toMatch(/<svg[^>]*width="13"[^>]*height="13"/)
    const [boton] = clases(html, 'button')
    for (const c of ['relative', 'before:absolute', 'before:-inset-1.5', "before:content-['']", '[@media(pointer:coarse)]:before:-inset-4']) {
      expect(boton).toContain(c)
    }
    const hoja = await css(html)
    // Con mouse: 6 px de cada lado (13 + 12 = 25). Con el dedo: 16 (13 + 32 = 45).
    expect(regla(hoja, '.before\\:-inset-1\\.5::before')).toContain('inset: -0.375rem')
    const desde = hoja.search(/@media\s*\(pointer:\s*coarse\)/)
    expect(desde, 'la regla «con el dedo»').toBeGreaterThanOrEqual(0)
    const dedo = hoja.slice(desde)
    expect(regla(dedo, 'before\\:-inset-4::before')).toContain('inset: -1rem')
    expect(regla(hoja, '.before\\:absolute::before')).toContain('position: absolute')
  })
})
