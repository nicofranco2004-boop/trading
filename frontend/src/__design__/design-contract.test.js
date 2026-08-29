// El contrato del sistema visual no se puede violar en silencio.
//
// POR QUÉ ESTE TEST
// ─────────────────
// Rendi tuvo dos generaciones de sistema visual y el clean pass de julio 2026
// migró la mayor parte del producto — pero no llegó parejo. Las pantallas que
// están bifurcadas por viewport (Cartera y Home tienen un archivo *Mobile.jsx
// aparte) se quedaron con la generación vieja: el commit que rediseñó Posiciones
// lo dice en su propio mensaje, "Mobile (PositionsMobile) no se toca".
// Movimientos era la tercera: su fork murió en la Fase 3.
//
// Eso no pasó por falta de sistema — el sistema estaba escrito. Pasó porque
// nada lo verificaba. Este test es lo que faltaba: congela la deuda actual y
// falla ante cualquier violación NUEVA. No migra nada; impide que crezca.
//
// El contrato completo (las 7 reglas, la lista cerrada de usos legítimos del
// mono, y qué hacer antes de un barrido de migración) está en frontend/CLAUDE.md.
//
// CÓMO FUNCIONA
// ─────────────
// El baseline es un mapa ruta→conteo por categoría. El test ITERA EL ÁRBOL y
// consulta el mapa, nunca al revés: una ruta ausente vale 0, así que un archivo
// nuevo con 40 font-mono falla aunque nadie lo haya agregado al JSON — que es
// exactamente el caso que hay que cazar.
//
// Falla cuando un conteo SUBE (violación nueva) y también cuando BAJA. Bajar es
// bienvenido: significa que alguien migró deuda. Pero tiene que quedar
// registrado en el mismo commit (`node scripts/gen-design-baseline.mjs --write`)
// para que la mejora no se gaste como presupuesto silencioso para violaciones
// futuras.
//
// UNIDAD: ocurrencias. No líneas. AddPositionFlow.jsx:817 tiene 12 font-mono en
// una sola línea (los códigos de mes); contando líneas, migrar 11 de esos 12 no
// movería el número y el que hizo el trabajo vería el mismo total que antes.
// Dos excepciones declaradas: mono_uppercase es coocurrencia por línea (es un
// par, no una ocurrencia) y paginas_mobile cuenta archivos.
//
// LOS DOS HUECOS, DECLARADOS
// ──────────────────────────
// 1. Compensación intra-archivo: borrar un font-mono y agregar otro en el MISMO
//    archivo pasa. Es el precio de no romperse cada vez que se mueven líneas.
//    Este guard frena la expansión a archivos nuevos, no audita cada línea.
// 2. Los átomos propagan mono por prop sin que la string aparezca en el
//    llamador: DataRow tiene `const fontClass = mono ? 'font-mono' : ''` y 6
//    call-sites lo activan. Esos archivos puntúan 0 y renderizan mono. No es
//    resoluble por grep — está documentado para que nadie concluya que el guard
//    no sirve.

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {
  CATEGORIAS,
  CATEGORIAS_ESPECIALES,
  listarFuentes,
  leer,
  medir,
  total,
} from '../../scripts/design-patterns.mjs'

const AQUI = dirname(fileURLToPath(import.meta.url))
const BASELINE = JSON.parse(readFileSync(join(AQUI, 'design-baseline.json'), 'utf8'))

const REGENERAR = 'node scripts/gen-design-baseline.mjs --write'

const medicion = medir()

describe('contrato de diseño — el walker mide lo que dice medir', () => {
  it('escanea el árbol de fuentes y excluye los tests', () => {
    const fuentes = listarFuentes()
    // NO se asertea `fuentes.length === BASELINE._archivosEscaneados`. Era una
    // igualdad exacta sobre el conteo de archivos: CUALQUIER .js nuevo bajo src/
    // rompía la suite y obligaba a regenerar el baseline, con un diff pelado
    // ("287 !== 286") y sin el mensaje de "QUÉ HACER" que sí traen las
    // categorías. Fricción sin señal: un archivo nuevo CON violaciones ya lo
    // cazan los mapas por categoría, que iteran el ÁRBOL y no el mapa (ruta
    // ausente = 0). `_archivosEscaneados` sigue en el JSON como dato
    // informativo — el generador lo escribe, nadie lo verifica.
    expect(fuentes.some((f) => f.includes('.test.'))).toBe(false)
    expect(fuentes.some((f) => f.includes('node_modules'))).toBe(false)
    expect(fuentes.every((f) => f.startsWith('src/'))).toBe(true)
  })

  it('no se cuenta a sí mismo: los patrones viven fuera de src/', () => {
    // Si design-patterns.mjs se mudara adentro de src/, el walker levantaría
    // sus literales ('font-mono', 'rounded-md') y el baseline subiría solo.
    const fuentes = listarFuentes()
    expect(fuentes.some((f) => f.includes('design-patterns'))).toBe(false)
    // El baseline es .json a propósito: en .js el walker lo leería y contaría
    // los tokens de sus propias claves.
    expect(fuentes.some((f) => f.includes('design-baseline'))).toBe(false)
  })
})

describe('contrato de diseño — la deuda no crece', () => {
  for (const [nombre, cat] of Object.entries(CATEGORIAS)) {
    const esperado = BASELINE.totales[nombre]
    const actual = total(medicion.porCategoria[nombre])

    it(`${nombre} (${cat.regla}) sigue en ${esperado}`, () => {
      if (actual === esperado) {
        expect(actual).toBe(esperado)
        return
      }

      // El mensaje de error ES el producto. Un guard que falla sin explicar
      // qué hacer se termina borrando.
      const previo = BASELINE.porArchivo[nombre] || {}
      const ahora = medicion.porCategoria[nombre]
      const rutas = [...new Set([...Object.keys(previo), ...Object.keys(ahora)])].sort()
      const deltas = rutas
        .map((r) => ({ r, antes: previo[r] || 0, ahora: ahora[r] || 0 }))
        .filter((d) => d.antes !== d.ahora)
        .map((d) => `    ${d.r}: ${d.antes} → ${d.ahora}  (${d.ahora > d.antes ? '+' : ''}${d.ahora - d.antes})`)

      const subio = actual > esperado
      const cabecera = subio
        ? `SUBIÓ: ${esperado} → ${actual}. Hay ${actual - esperado} violación(es) nueva(s) de ${cat.regla}.`
        : `BAJÓ: ${esperado} → ${actual}. Migraste ${esperado - actual} — bien, pero falta registrarlo.`

      const quehacer = subio
        ? `  QUÉ HACER\n` +
          `    Revisá las líneas nuevas contra ${cat.regla} en frontend/CLAUDE.md.\n` +
          `    Si de verdad son legítimas (la lista de R3 es cerrada), la conversación es\n` +
          `    sobre la regla, no sobre el número: no corras el generador para "arreglar" esto.`
        : `  QUÉ HACER\n` +
          `    Correr \`${REGENERAR}\` y commitear el JSON junto con tu cambio.\n` +
          `    Bajar el número exige registrarlo para que la mejora no quede como\n` +
          `    presupuesto silencioso para violaciones futuras.`

      throw new Error(
        `\n  ${cabecera}\n\n` +
          `  ${cat.nota}\n\n` +
          `  POR ARCHIVO\n${deltas.join('\n')}\n\n` +
          `${quehacer}\n`,
      )
    })
  }

  for (const [nombre, cat] of Object.entries(CATEGORIAS_ESPECIALES)) {
    it(`${nombre} (${cat.regla}) sigue en ${BASELINE.totales[nombre]}`, () => {
      const actual = medicion.especiales[nombre]
      if (actual !== BASELINE.totales[nombre]) {
        throw new Error(
          `\n  ${nombre}: ${BASELINE.totales[nombre]} → ${actual}\n\n  ${cat.nota}\n\n` +
            `  Si el cambio es intencional, correr \`${REGENERAR}\`.\n`,
        )
      }
      expect(actual).toBe(BASELINE.totales[nombre])
    })
  }
})

describe('contrato de diseño — R6, no se bifurca por viewport', () => {
  // Tres aserciones y no una: el patrón literal caza los forks que existen,
  // el ternario caza la variante que todavía no existe, y el glob caza el fork
  // que alguien escriba SIN la línea canónica.
  //
  // Eran 3. Operations murió en la Fase 3: un dueño de datos y dos ramas
  // `{isMobile && …}` / `{!isMobile && …}` sobre renderers compartidos en
  // components/operations/.
  it('los 2 forks siguen siendo exactamente Home y Positions', () => {
    const conFork = Object.keys(medicion.porCategoria.fork_viewport).sort()
    expect(conFork).toEqual([
      'src/pages/Home.jsx',
      'src/pages/Positions.jsx',
    ])
  })

  it('no hay páginas *Mobile.jsx nuevas', () => {
    const mobiles = listarFuentes().filter((f) => /^src\/pages\/[^/]+Mobile\.jsx$/.test(f)).sort()
    expect(mobiles).toEqual([
      'src/pages/HomeMobile.jsx',
      'src/pages/PositionDetailMobile.jsx',
      'src/pages/PositionsMobile.jsx',
    ])
  })

  it('el breakpoint sigue teniendo un solo dueño', () => {
    // Si aparece un segundo mecanismo de ancho, R6 se puede evadir sin tocar
    // ninguno de los dos patrones de arriba.
    //
    // El predicado mira ANCHO, no matchMedia a secas: `useCountUp.js` consulta
    // `prefers-reduced-motion`, que es accesibilidad y no tiene nada que ver
    // con el viewport. Y la lista se congela con su contenido REAL en vez de
    // afirmar que está vacía: `ActionMenu.jsx` usa innerWidth para que un popup
    // no se salga de la pantalla — es posicionamiento, no un breakpoint.
    // Congelar el valor de verdad es lo que hace que un tercer archivo falle;
    // afirmar cero habría hecho que la suite naciera en rojo y que el arreglo
    // obvio fuera bajar la aserción.
    const CONOCIDOS = [
      'src/components/ActionMenu.jsx',  // clamp de posición de popup, no breakpoint
      'src/hooks/useIsMobile.js',       // el dueño legítimo del breakpoint
    ]
    const conAncho = listarFuentes().filter((f) => {
      const t = leer(f)
      return /window\.matchMedia\([^)]*width/i.test(t) || /window\.innerWidth/.test(t)
    })
    expect(conAncho.sort()).toEqual(CONOCIDOS)
  })
})

describe('contrato de diseño — la referencia sigue siendo la referencia', () => {
  // El Plan Asesor es el material que se usa como norte cuando hay que decidir
  // cómo se ve algo nuevo. Se congela con su valor REAL, nunca con un 0
  // aspiracional: escribir "advisor está en cero" es la forma natural de
  // afirmar "esta es la generación nueva", y haría que la suite arranque en
  // rojo el día uno. El arreglo obvio para el que la vea sería bajar la
  // aserción — y el guard nacería desarmado.
  const PAGINAS = [
    'src/pages/AdvisorDashboard.jsx',
    'src/pages/AdvisorClients.jsx',
    'src/pages/AdvisorNovedades.jsx',
  ]

  it('las 3 páginas del asesor siguen sin un solo font-mono', () => {
    const conMono = PAGINAS.filter((f) => medicion.porCategoria.mono_clase[f])
    expect(conMono).toEqual([])
  })

  it('components/advisor tiene exactamente 1 font-mono (un ticker, legítimo por R3)', () => {
    const enAdvisor = Object.entries(medicion.porCategoria.mono_clase)
      .filter(([f]) => f.startsWith('src/components/advisor/'))
    expect(Object.fromEntries(enAdvisor)).toEqual({
      'src/components/advisor/BookComposition.jsx': 1,
    })
  })
})
