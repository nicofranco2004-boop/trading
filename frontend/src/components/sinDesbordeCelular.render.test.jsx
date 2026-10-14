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
    // Desde 2026-10-14 va en clases (56 px en el celular, 72 desde sm).
    expect(src).toContain('grid-cols-[56px_minmax(0,1fr)] sm:grid-cols-[72px_minmax(0,1fr)]')
    expect(src).not.toMatch(/grid-cols-\[\d+px_1fr\]|gridTemplateColumns: '\d+px 1fr'/)
  })

  // 2026-10-13, 390 px: «Analizar» + «en N días» (~170 px fijos) en la misma
  // fila que el título lo dejaban en 0 px — se veía el logo y los botones, sin
  // decir de qué era el evento. Debajo de lg van en un segundo renglón.
  // La prueba de verdad es de comportamiento (mide en un navegador):
  // scripts/medir-textos-cortados.mjs. Esto sólo frena que se deshaga sin querer.
  it('la fila del evento: el título en minmax(0,1fr) y los botones abajo hasta lg', () => {
    expect(src).toContain("'grid-cols-[auto_minmax(0,1fr)_auto] lg:grid-cols-[auto_minmax(0,1fr)_auto_auto]'")
    expect(src).toContain('col-start-2 row-start-2 lg:col-start-3 lg:row-start-1')
    expect(src).not.toContain('className="px-4 py-3 flex items-center gap-3"')
  })
})
