import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { PASOS_TECNICO } from './pasosTecnico'
import { ATRIBUTO } from './recorrido'
import { PESTANAS, pestanaDe } from '../../pages/AnalisisTecnico'
import { FILTROS as FILTROS_DEL_BUSCADOR } from '../../utils/graficoTecnico'
import { MAX_ACTIVOS } from '../../utils/comparadorPrecio'

const leer = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')
const paso = (id) => PASOS_TECNICO.find(p => p.id === id)
const PAGINA = leer('../../pages/AnalisisTecnico.jsx')

// ─── Que lo que el tutorial promete resaltar EXISTA ─────────────────────────
// Igual que en el de novedades (pasos.test.js): un paso que apunta a algo que
// no está se saltea solo y la pestaña queda sin explicar.
describe('cada paso del técnico resalta algo que está de verdad', () => {
  const FUENTES = [
    '../../pages/AnalisisTecnico.jsx', '../../pages/GraficoTecnico.jsx',
    '../asset/LecturaTecnica.jsx', '../asset/BarraGrafico.jsx',
  ].map(leer).join('\n')

  it('las pestañas llevan su marca, y cada paso de pestaña nombra una que existe', () => {
    // Las marcas de las pestañas se arman con su id: se prueba el armado y el id.
    expect(PAGINA).toContain('data-tour={`tab-${p.id}`}')
    const tabs = PASOS_TECNICO.filter(p => p.marca.startsWith('tab-'))
    expect(tabs.length).toBeGreaterThan(0)
    const visibles = PESTANAS.filter(p => !p.pronto).map(p => p.id)
    for (const p of tabs) expect(visibles, p.id).toContain(p.marca.slice(4))
  })

  it('las demás marcas existen en la pantalla', () => {
    const sinMarcar = PASOS_TECNICO.filter(p => !p.marca.startsWith('tab-'))
      .filter(p => !FUENTES.includes(`${ATRIBUTO}="${p.marca}"`))
    expect(sinMarcar.map(p => p.id)).toEqual([])
  })

  it('hay un paso por cada pestaña, más el «Pronto»', () => {
    const conPaso = PASOS_TECNICO.map(p => p.marca)
    for (const p of PESTANAS.filter(x => !x.pronto)) expect(conPaso, p.id).toContain(`tab-${p.id}`)
    expect(conPaso).toContain('pronto')
  })

  it('cada paso abre la pestaña donde vive lo que ilumina', () => {
    // Lo del gráfico vive en el Gráfico; una pestaña de acá se explica con la
    // pestaña abierta; Comparar lleva AFUERA, así que no se abre (se describe).
    const DEL_GRAFICO = ['grafico-activo', 'grafico-vista', 'grafico-herramientas']
    for (const p of PASOS_TECNICO) {
      expect(p.ruta, p.id).toBe('/analisis-tecnico')
      const abierta = pestanaDe(new URLSearchParams(p.busqueda))
      const tab = p.marca.startsWith('tab-') ? PESTANAS.find(x => x.id === p.marca.slice(4)) : null
      if (DEL_GRAFICO.includes(p.marca)) expect(abierta, p.id).toBe('grafico')
      else if (tab && !tab.afuera) expect(abierta, p.id).toBe(tab.id)
      else expect(abierta, p.id).toBe('grafico')
    }
  })

  it('empieza por el Gráfico y termina de vuelta en él', () => {
    // El Gráfico es la de entrada: el tutorial arranca ahí y termina ahí, donde
    // la persona va a empezar a usar la pantalla (no en Señales).
    expect(PASOS_TECNICO[0].marca).toBe('tab-grafico')
    expect(pestanaDe(new URLSearchParams(PASOS_TECNICO.at(-1).busqueda))).toBe('grafico')
  })

  it('cada paso dice qué cuenta, corto', () => {
    for (const p of PASOS_TECNICO) {
      expect(p.titulo.length, p.id).toBeGreaterThan(8)
      expect(p.texto.length, p.id).toBeGreaterThan(40)
      // El cartel se acomoda a su alto (Tour.jsx, `altoCartel`), pero un texto
      // largo en un celular acostado igual no entra: corto.
      expect(p.texto.length, p.id).toBeLessThanOrEqual(240)
    }
  })
})

// ─── Lo que promete cada paso tiene que ser lo que la pantalla hace ─────────
// (el gesto que se promete: ver el comentario del micrófono en pasos.js).
describe('el texto promete lo que la pantalla hace', () => {
  it('el botón de cada cuánto es una vela se llama «1D», y sólo está con velas', () => {
    const lt = leer('../asset/LecturaTecnica.jsx')
    expect(lt).toMatch(/\['dia', '1D', 'Diarias'\]/)
    expect(lt).toMatch(/\{tipo === 'velas' && setIntervalo && \(\s*<ElegirIntervalo/)
    expect(paso('vista').texto).toContain('Con velas aparece «1D»')
    for (const nombre of ["'1 hora'", "'4 horas'"]) expect(lt).toContain(nombre)
  })

  it('el buscador del gráfico ofrece tu cartera y tu lista', () => {
    const nombres = FILTROS_DEL_BUSCADOR.map(f => f.label)
    expect(nombres).toContain('Tu cartera')
    expect(nombres).toContain('Tu lista')
    expect(paso('activo').texto).toMatch(/de tu cartera o de tu lista/)
  })

  it('las tarjetas de Tu lista tienen los medidores que se nombran', () => {
    const tl = leer('../../pages/TuLista.jsx')
    for (const m of ['Tendencia', 'Impulso', 'Fuerza']) {
      expect(tl, m).toContain(`text-ink-2">${m}</span>`)
      expect(paso('lista').texto.toLowerCase(), m).toContain(m.toLowerCase())
    }
  })

  it('Tu lista tiene el buscador que el paso nombra', () => {
    // Pedido de Nico (02/11): sumar a la watchlist desde «Tu lista».
    const tl = leer('../../pages/TuLista.jsx')
    expect(tl).toMatch(/<BuscarParaTuLista filas=\{filas\}/)
    expect(paso('lista').texto).toContain('Con el buscador de arriba sumás activos a tu watchlist')
  })

  it('Comparar admite los activos que dice', () => {
    expect(paso('comparar').texto).toContain(`hasta ${MAX_ACTIVOS} activos`)
  })

  it('el «Pronto» nombra lo que la pantalla anuncia', () => {
    for (const p of PESTANAS.filter(x => x.pronto)) expect(paso('pronto').texto, p.id).toContain(p.label)
  })
})

// ─── Lo que no puede decir ──────────────────────────────────────────────────
describe('ni consejos ni montos', () => {
  const textos = PASOS_TECNICO.map(p => `${p.titulo} ${p.texto}`)

  it('no dice qué hacer con un activo (CNV)', () => {
    // Lo central de backend/ai/certezas_y_consejos.py, lo que un texto fijo
    // podría tener: una opinión de qué conviene, el verbo de operar en
    // imperativo o una predicción. Describir qué muestra, nunca qué hacer.
    const MAL = /\b(conviene|deber[íi]as|recomend\w*|suger\w*|oportunidad|buen momento|comprá\w*|vendé\w*|acumulá\w*|invertí\w*|tomá ganancias|va a (subir|bajar|seguir)|probablemente)\b/i
    for (const t of textos) expect(t).not.toMatch(MAL)
  })

  it('no nombra montos: con «Ocultar saldos» el tutorial se ve igual', () => {
    for (const t of textos) { expect(t).not.toMatch(/\$|\bpesos\b|\bd[óo]lares\b/i); expect(t).not.toMatch(/\bUS\b/) }
  })
})
