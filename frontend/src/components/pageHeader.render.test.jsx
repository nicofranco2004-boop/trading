import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import PageHeader from './PageHeader'
import PreciosEnVivo from './PreciosEnVivo'

// El punto que late lo decide quien sabe si el dato se mueve, nunca un texto.
describe('<PageHeader meta>', () => {
  it('un texto fijo NO late, diga lo que diga ("precios", "live")', () => {
    for (const meta of ['Precios · 14:32', 'Live · Google News', 'actualizado 14:32']) {
      expect(renderToStaticMarkup(<PageHeader title="X" meta={meta} />)).not.toContain('live-dot')
    }
  })
  it('un nodo se dibuja tal cual: late sólo si él lo decide', () => {
    const quieto = renderToStaticMarkup(<PageHeader title="X" meta={<PreciosEnVivo actualizado={new Date()} />} />)
    const vivo = renderToStaticMarkup(<PageHeader title="X" meta={<PreciosEnVivo actualizado={new Date()} seMueven />} />)
    expect(quieto).not.toContain('live-dot')
    expect(vivo).toContain('live-dot')
  })
})

// En el celular el meta va solo en su renglón: su ancho cambia («Buscando
// precios…» → «Precios de hace 0 s» → «hace 1 min») y, al lado de los botones,
// decidía si los botones entraban o bajaban 30 px (Dashboard, 16/11/2026: por
// 1 px). Sin navegador no hay anchos; la medida de verdad es
// scripts/medir-cls.mjs. Esto cuida que el meta no vuelva a compartir renglón.
describe('<PageHeader meta> en el celular', () => {
  // Las clases del <div> más cercano que envuelve al texto del meta.
  const clasesDelContenedor = (html, texto) => {
    const abre = html.lastIndexOf('<div class="', html.indexOf(texto))
    return html.slice(abre + 12, html.indexOf('"', abre + 12)).split(/\s+/)
  }
  it('el meta (nodo o texto) ocupa el renglón entero hasta sm, y al lado desde sm', () => {
    const accion = <button>Analizar</button>
    for (const meta of [<PreciosEnVivo actualizado={null} actualizando />, 'Dólar MEP del 14/11']) {
      const html = renderToStaticMarkup(<PageHeader title="X" meta={meta} action={accion} />)
      const texto = typeof meta === 'string' ? meta : 'Buscando precios…'
      // `w-full` exacto: el contenedor de las acciones tiene `max-w-full`, que no es lo mismo.
      expect(clasesDelContenedor(html, texto)).toContain('w-full')
      expect(clasesDelContenedor(html, texto)).toContain('sm:w-auto')
    }
  })
  it('sin meta no queda un renglón vacío', () => {
    const html = renderToStaticMarkup(<PageHeader title="X" action={<button>Analizar</button>} />)
    expect(html).not.toContain('w-full sm:w-auto')
  })
})
