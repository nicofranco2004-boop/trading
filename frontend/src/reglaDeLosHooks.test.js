// Ningún `useAlgo()` DESPUÉS de un `return` temprano.
//
// POR QUÉ ESTE TEST
// ─────────────────
// Un componente que arranca con `if (cargando) return <Skeleton/>` y más abajo
// llama a un hook, llama 6 hooks en un render y 7 en el siguiente. React lo
// avisa por consola ("change in the order of Hooks") y, en cuanto el hook de
// más ocupa lugar en la lista (useState / useMemo / useEffect / useRef — todos
// menos useContext), el render siguiente explota con "Rendered more hooks than
// during the previous render": pantalla en blanco.
//
// Encontrado el 2026-09-22 probando el selector de clientes del libro:
//   • `BookEvolution` (AdvisorDashboard.jsx) tenía un `useMoneyFormat()` después
//     de los dos returns de "cargando" y "sin historia". Como abajo de todo es
//     un useContext, sólo avisaba por consola — la bomba con la mecha puesta.
//   • `CurrentPeriodView` (Reports.jsx) tenía un `useState` después de
//     `if (loading)`, y el padre lo monta JUSTO con loading=true. Ese sí rompe
//     la pantalla de Reportes cuando la llamada tarda.
//
// El repo no tiene eslint (ni el plugin react-hooks), así que la regla se vigila
// acá. No reemplaza leer el código: es la red para que no vuelva a pasar.

import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = dirname(fileURLToPath(import.meta.url))

function archivosDeFuente(dir = SRC, acc = []) {
  for (const nombre of readdirSync(dir)) {
    if (nombre === 'node_modules' || nombre === '__design__') continue
    const f = join(dir, nombre)
    if (statSync(f).isDirectory()) { archivosDeFuente(f, acc); continue }
    if (!/\.(jsx?|tsx?)$/.test(nombre)) continue
    if (/\.(test|spec)\./.test(nombre)) continue
    acc.push(f)
  }
  return acc
}

// Definición de nivel superior: `function Algo(`, `export function useAlgo(`,
// `const Algo = (...) =>`. Sirve para cortar el archivo en bloques; lo que
// importa es que un hook de OTRO componente no se le cuelgue al anterior.
const DEFINICION =
  /^(?:export\s+)?(?:default\s+)?(?:function\s+([A-Za-z]\w*)\s*\(|const\s+([A-Za-z]\w*)\s*=\s*(?:React\.)?(?:memo\()?\s*(?:\([^)]*\)|\w+)\s*=>)/

// Llamada a hook en el cuerpo del componente (2 espacios de indentación). Más
// adentro ya es un callback, y ahí la regla no aplica.
const HOOK_DE_CUERPO = /^ {2}(?:(?:const|let|var) .*\buse[A-Z]\w*\(|use[A-Z]\w*\()/

function returnTempranoEn(bloque) {
  for (let j = 0; j < bloque.length; j++) {
    const l = bloque[j]
    if (/^ {2}if \(.*\)\s*return\b/.test(l)) return j            // if (x) return null
    if (/^ {2}if \(/.test(l)) {                                   // if (x) {
      const sig = bloque.slice(j + 1, j + 3).find(x => x.trim()) || ''
      if (/^ {4}return\b/.test(sig)) return j                     //   return (…)
    }
  }
  return null
}

function infracciones(ruta) {
  const lineas = readFileSync(ruta, 'utf8').split('\n')
  const defs = []
  lineas.forEach((l, i) => {
    const m = DEFINICION.exec(l)
    if (m) defs.push({ i, nombre: m[1] || m[2] })
  })
  const malas = []
  defs.forEach(({ i, nombre }, k) => {
    // Sólo componentes (Mayúscula) y hooks propios (useAlgo).
    if (!/^(use[A-Z]|[A-Z])/.test(nombre)) return
    const fin = k + 1 < defs.length ? defs[k + 1].i : lineas.length
    const bloque = lineas.slice(i, fin)
    const ret = returnTempranoEn(bloque)
    if (ret === null) return
    for (let j = ret; j < bloque.length; j++) {
      if (HOOK_DE_CUERPO.test(bloque[j])) {
        malas.push(`${relative(SRC, ruta)}:${i + j + 1} — ${nombre}() llama ${bloque[j].trim()} después del return temprano de la línea ${i + ret + 1}`)
        break
      }
    }
  })
  return malas
}

describe('Regla de los hooks: todos ANTES del primer return', () => {
  it('ningún componente llama un hook después de un return temprano', () => {
    const malas = archivosDeFuente().flatMap(infracciones)
    expect(malas, [
      'Hay hooks después de un `return` temprano. Ese componente llama distinta',
      'cantidad de hooks según el render y React termina rompiendo la pantalla',
      '("Rendered more hooks than during the previous render").',
      'Se arregla moviendo la llamada al hook ARRIBA del primer return:',
      '',
      ...malas,
      '',
    ].join('\n')).toEqual([])
  })

  it('el detector encuentra el caso que motivó el test', () => {
    // Control negativo: si mañana el detector deja de ver esta forma, el test
    // pasaría en verde sin vigilar nada.
    const caso = [
      'function Roto({ cargando }) {',
      '  if (cargando) {',
      '    return (<div />)',
      '  }',
      '  const [x, setX] = useState(0)',
      '  return <div>{x}</div>',
      '}',
    ]
    expect(returnTempranoEn(caso)).toBe(1)
    expect(HOOK_DE_CUERPO.test(caso[4])).toBe(true)
  })
})
