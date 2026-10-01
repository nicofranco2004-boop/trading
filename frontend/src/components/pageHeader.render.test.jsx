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
