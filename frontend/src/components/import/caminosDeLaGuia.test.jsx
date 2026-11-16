// Los caminos del menú de cada broker que se ven ADENTRO de la app salen de la
// guía (BROKER_GUIDES, en BrokerInstructions.jsx). Nada más los escribe.
//
// Por qué existe: había copias a mano y se separaron de la guía sin que nada
// avisara. Al 16/11/2026, en el asistente, el aviso azul «Traé también el
// resumen de Balanz… Dónde bajarla: Mi cuenta → Resumen de cuenta» quedaba
// justo arriba de la guía que decía «Actividad → Reportes → Posición
// consolidada»; a Cocos lo mandaba a «Inversiones → Estado de cuenta». Los
// cuatro modales de la foto sola (Importaciones) tenían sus pasos copiados, y
// la demo, caminos viejos y el export de «Resultados» de Balanz, que el
// servidor rechaza. Del lado del servidor vigila backend/tests/test_caminos.py.
//
// Recorre también las páginas públicas. Las landings de broker (/brokers/*)
// tienen además su propia prueba, que mira que muestren los pasos de su guía
// (pages/keywords/guiasDeBrokers.render.test.jsx).
import { describe, it, expect, vi } from 'vitest'
import fs from 'node:fs'
import { renderToStaticMarkup } from 'react-dom/server'
import { archivosConTexto, sinComentarios, relativa } from '../../../scripts/texto-visible.mjs'
import { BROKER_GUIDES, pasosDeLaFoto } from './BrokerInstructions'
import { resolverFaltaTenencia } from './ImportWizard.jsx'
import { handleDemoRequest } from '../../utils/demo'

vi.mock('../../utils/api', () => ({ api: { get: () => Promise.resolve([]) } }))
import TenenciaUpload from './TenenciaUpload'

const guia = (id) => BROKER_GUIDES.find(g => g.id === id)
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#x27;')

describe('pasosDeLaFoto', () => {
  it('trae el paso de la foto y el de entrar desde la web, en orden', () => {
    const iol = guia('iol')
    expect(pasosDeLaFoto(iol)).toEqual([iol.steps[0], iol.steps[2]])
  })

  it('sin pasos comunes, sólo el de la foto', () => {
    const cocos = guia('cocos')
    expect(pasosDeLaFoto(cocos)).toEqual([cocos.steps[1]])
  })

  it('un broker sin foto no devuelve nada (ni el paso de entrar)', () => {
    expect(pasosDeLaFoto(guia('binance'))).toEqual([])
    expect(pasosDeLaFoto(guia('balanz_internacional'))).toEqual([])
    expect(pasosDeLaFoto(undefined)).toEqual([])
  })

  it('cada guía declara las tres listas, con índices que existen', () => {
    for (const g of BROKER_GUIDES) {
      for (const campo of ['pasosFoto', 'pasosComunes', 'pasosSoloAsistente']) {
        expect(Array.isArray(g[campo]), `${g.id}.${campo}`).toBe(true)
        for (const i of g[campo]) expect(g.steps[i], `${g.id}.${campo}[${i}]`).toBeTruthy()
      }
    }
  })
})

describe('el aviso «falta la foto» del asistente', () => {
  const grupos = [{ platform: 'balanz', platform_label: 'Balanz', tenencia_format: 'balanz_tenencia' }]

  it('dice dónde bajarla con el paso de la guía, no con un texto propio', () => {
    const r = resolverFaltaTenencia(grupos, 'balanz', { isSpecificParser: true, tenenciaFile: null })
    expect(r.pasos).toEqual(pasosDeLaFoto(guia('balanz')))
    expect(r.pasos.join(' ')).toContain('Actividad → Reportes → Posición consolidada')
    // Y señala el número del paso, para cuando la guía está en pantalla.
    expect(guia('balanz').steps[r.pasoEnLaGuia - 1]).toContain('Posición consolidada')
  })
})

describe('el modal de la foto sola (Importaciones)', () => {
  // Los cuatro que abre pages/Imports.jsx.
  for (const id of ['ppi', 'cocos', 'ieb', 'iol']) {
    it(`${id}: muestra los pasos de su guía`, () => {
      const html = renderToStaticMarkup(<TenenciaUpload guiaId={id} onClose={() => {}} />)
      const pasos = pasosDeLaFoto(guia(id))
      expect(pasos.length).toBeGreaterThan(0)
      for (const p of pasos) expect(html).toContain(esc(p))
    })
  }

  it('Importaciones le pasa a cada modal su guía', () => {
    const src = fs.readFileSync(new URL('../../pages/Imports.jsx', import.meta.url), 'utf8')
    const usos = [...src.matchAll(/<TenenciaUpload\b[\s\S]*?\/>/g)].map(m => m[0])
    expect(usos.length).toBe(4)
    for (const u of usos) {
      const id = u.match(/guiaId="([^"]+)"/)?.[1]
      expect(id && guia(id), u.slice(0, 120)).toBeTruthy()
      expect(u).not.toMatch(/fileHint/)
    }
  })
})

// ── Nada fuera de la guía escribe un camino ───────────────────────────────────

const FLECHA = /(\S+)\s*→\s*(?=(\S+))/g
const BORDES = /^[“”«»"'()[\],.;:¿?¡!]+|[“”«»"'()[\],.;:¿?¡!]+$/g
const BROKER = /\b(PPI|Cocos|Balanz|IOL|InvertirOnline|Bull ?Market|bullmarket|Schwab|Binance|IEB|inviu)/i
const limpiar = (t) => t.replace(BORDES, '')

// Los pares «A → B» de la guía, y las palabras de menú (las que empiezan en
// mayúscula al lado de una flecha).
function vocabulario() {
  const pares = new Set()
  const palabras = new Set()
  for (const t of BROKER_GUIDES.flatMap(g => g.steps)) {
    for (const m of t.matchAll(FLECHA)) {
      const [a, b] = [limpiar(m[1]), limpiar(m[2])]
      pares.add(`${a.toLowerCase()}→${b.toLowerCase()}`)
      for (const x of [a, b]) if (/^\p{Lu}/u.test(x)) palabras.add(x.toLowerCase())
    }
  }
  return { pares, palabras }
}

// Dos reglas: un par que está tal cual en la guía, en cualquier renglón; o una
// flecha pegada a una palabra de menú en un renglón que habla de un broker (el
// importador, o un renglón que lo nombra). Sin esa condición confundiría los
// menús de la propia Rendi («Configuración → Brokers»), que repiten palabras.
function copiasAMano(renglones) {
  const { pares, palabras } = vocabulario()
  const out = []
  for (const { ruta, n, texto } of renglones) {
    const deBroker = ruta.startsWith('src/components/import/') || BROKER.test(texto)
    for (const m of texto.matchAll(FLECHA)) {
      const [a, b] = [limpiar(m[1]).toLowerCase(), limpiar(m[2]).toLowerCase()]
      if (pares.has(`${a}→${b}`) || (deBroker && (palabras.has(a) || palabras.has(b)))) {
        out.push(`${ruta}:${n} «${m[1]} → ${m[2]}»`)
      }
    }
  }
  return out
}

function renglonesDeLaApp() {
  return archivosConTexto()
    .filter(f => relativa(f).startsWith('src/')
      && relativa(f) !== 'src/components/import/BrokerInstructions.jsx')
    .flatMap(f => sinComentarios(f, fs.readFileSync(f, 'utf8')).split('\n')
      .map((texto, i) => ({ ruta: relativa(f), n: i + 1, texto })))
    .filter(r => r.texto.includes('→'))
}

describe('ningún texto de la app escribe a mano un camino del menú de un broker', () => {
  it('la regla atrapa las copias que había (contra el falso verde)', () => {
    const viejas = [
      { ruta: 'src/components/import/TenenciaUpload.jsx', n: 26, texto: "fileHint = 'Bull Market WEB → Mi Cuenta → Otras consultas → Tenencia Valorizada a una Fecha → Acceder.'" },
      { ruta: 'src/pages/Imports.jsx', n: 520, texto: "'Andá a Mi Cuenta → Estado de Cuenta.'," },
      { ruta: 'src/utils/demo.js', n: 3062, texto: "{ platform: 'balanz', platform_label: 'Balanz', tenencia_label: 'Mi cuenta → Resumen de cuenta (PDF)', exports: [" },
      { ruta: 'src/utils/demo.js', n: 3065, texto: "{ id: 'balanz_resultados', label: 'Actividad → Resultados', supported: true }," },
      { ruta: 'src/utils/demo.js', n: 3067, texto: "{ platform: 'cocos', tenencia_label: 'Inversiones → Estado de cuenta → Exportar', exports: [" },
      { ruta: 'src/pages/keywords/Cocos.jsx', n: 14, texto: "desc: 'Descargá desde Cocos los Movimientos (Actividad → Descargar Movimientos) y el Estado de Cuenta (Portfolio → Descargar portfolio)'," },
    ]
    for (const v of viejas) expect(copiasAMano([v]), v.texto).not.toEqual([])
  })

  it('y deja pasar los menús de Rendi y otras flechas', () => {
    expect(copiasAMano([
      { ruta: 'src/pages/Config.jsx', n: 1, texto: "'Creálo en Configuración → Brokers.'" },
      { ruta: 'src/components/CuponesPorCobrar.jsx', n: 1, texto: '`${num(a)} → ${num(b)}`' },
    ])).toEqual([])
  })

  // Lee todos los archivos de la app: medio segundo sola, pero con la suite
  // entera y otras sesiones corriendo pasó los 5 s por defecto (16/11). Mismo
  // margen que los otros guardianes que recorren src/ (nombres-sin-definir).
  it('en todo el código de la app (fuera de la guía), páginas públicas incluidas', () => {
    const renglones = renglonesDeLaApp()
    expect(renglones.length).toBeGreaterThan(20)   // contra el falso verde
    expect(copiasAMano(renglones)).toEqual([])
  }, 60_000)
})

describe('la demo', () => {
  // Por la misma puerta que usa la app en modo demo.
  const grupos = handleDemoRequest('GET', '/imports/parsers/grouped')

  it('no ofrece el export de «Resultados» de Balanz (el servidor lo rechaza)', () => {
    const ids = grupos.find(g => g.platform === 'balanz').exports.map(e => e.id)
    expect(ids).toContain('balanz_movimientos')
    expect(ids).not.toContain('balanz_resultados')
  })

  it('no trae su propio «dónde bajar la foto»: lo dice la guía', () => {
    for (const g of grupos) expect(g, g.platform).not.toHaveProperty('tenencia_label')
  })

  it('cada broker con foto tiene en la guía el paso para bajarla', () => {
    for (const g of grupos.filter(x => x.tenencia_format)) {
      expect(pasosDeLaFoto(guia(g.platform)).length, g.platform).toBeGreaterThan(0)
    }
  })
})
