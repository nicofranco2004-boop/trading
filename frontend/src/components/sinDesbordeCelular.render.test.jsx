import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import PageHeader from './PageHeader'

// En el celular (375 px), medido en Chrome el 2026-10-02: Reportes medía 555 px
// (las acciones del encabezado no se partían) y Novedades 823 (la columna de la
// agenda medía lo que su título más largo). La página se corría de costado.

describe('PageHeader — las acciones pueden partirse en el celular', () => {
  it('max-w-full + flex-wrap; el no-achicarse sólo desde sm', () => {
    const html = renderToStaticMarkup(<PageHeader title="Reportes" action={<button>Exportar</button>} />)
    expect(html).toMatch(/class="flex flex-wrap items-center gap-3 max-w-full sm:flex-shrink-0"/)
    expect(html).not.toMatch(/class="flex items-center gap-3 flex-shrink-0"/)
  })
})

describe('Novedades — la agenda y los filtros entran en la pantalla', () => {
  const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../pages/Events.jsx'), 'utf8')
  it('la columna de la agenda es minmax(0, 1fr) (con `1fr` crecía con el texto)', () => {
    expect(src).toContain("gridTemplateColumns: '72px minmax(0, 1fr)'")
    expect(src).not.toContain("gridTemplateColumns: '72px 1fr'")
  })
})
