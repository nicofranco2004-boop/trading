// El manejador de errores no puede reventar cuando hay un error que mostrar.
//
// POR QUÉ ESTE TEST
// ─────────────────
// Producción 2026-09-16: `VozContext.jsx` declaraba `let agregado = false`
// adentro del `try` y la usaba desde el `catch`. `let` es de bloque, así que el
// catch nunca la vio: cada vez que el chat fallaba, el manejador tiraba
// "agregado is not defined" y se llevaba puesta la pantalla entera. Por ese
// mismo catch pasan TODOS los errores del chat — el más frecuente es quedarse
// sin cuota, o sea que le pegaba sobre todo a los Free al llegar a su límite.
//
// El código "se lee" perfecto y el build no dice nada. Sólo aparece cuando hay
// un error de verdad: el peor momento posible para enterarse.
//
// TOLERANCIA CERO, a diferencia del contrato visual
// ─────────────────────────────────────────────────
// Ese guard lleva un baseline porque arrancó con deuda. Acá la deuda es CERO
// (medida sobre los 400+ archivos el día del arreglo), así que no hay nada que
// congelar: cualquier caso nuevo es un bug nuevo y el test se pone rojo.
//
// Para verlo suelto:  node scripts/scan-try-catch-scope.mjs src
import { describe, it, expect } from 'vitest'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { buscarFugasDeAlcance } from '../../scripts/scan-try-catch-scope.mjs'

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

describe('alcance try → catch/finally', () => {
  it('ninguna variable del try se usa desde el catch o el finally', () => {
    const fugas = buscarFugasDeAlcance(SRC)
    const detalle = fugas
      .map(f => `${f.archivo}: "${f.nombre}" se declara en la línea ${f.declaradaEn} `
              + `(adentro del try) y se usa en la ${f.usadaEn}, adentro del ${f.bloque}. `
              + `El catch NO la ve → ReferenceError justo cuando hay un error que mostrar. `
              + `Movela ARRIBA del try.`)
      .join('\n')
    expect(fugas, detalle).toEqual([])
  })

  // ── Los casos vienen de AUDITAR el guard el mismo día que se escribió. ──
  // La primera versión fallaba en las dos direcciones: era ciega al
  // desestructurado (justo lo que usa el catch que originó todo esto) y a las
  // funciones declaradas adentro del try, y encima reportaba como fuga un caso
  // VÁLIDO. Un falso positivo en un guard de tolerancia cero es peor que no
  // tenerlo: pone la suite en rojo sobre código correcto, y lo que se hace
  // entonces es borrar el guard.
  function escanear(archivos) {
    const fs = require('node:fs')
    const os = require('node:os')
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'guard-'))
    for (const [nombre, codigo] of Object.entries(archivos)) {
      fs.writeFileSync(path.join(dir, nombre), codigo)
    }
    try { return buscarFugasDeAlcance(dir) } finally { fs.rmSync(dir, { recursive: true, force: true }) }
  }

  it('encuentra el bug REAL, reducido', () => {
    // Un guard que no se prueba contra lo que dice cazar devolvería [] y el
    // test de arriba quedaría VERDE certificando lo contrario de lo que pasa.
    const f = escanear({ 'caso.js': `
export async function enviar() {
  let preguntaPuesta = false
  try {
    let agregado = false
    agregado = true
    await pedir()
  } catch (e) {
    setThread(t => (agregado ? t.slice(0, -1) : t))
    if (preguntaPuesta) limpiar()
  }
}` })
    expect(f).toHaveLength(1)
    expect(f[0].nombre).toBe('agregado')
    expect(f[0].bloque).toBe('catch')
  })

  it('ve el DESESTRUCTURADO — era su agujero más grave', () => {
    // `const { mensaje, usage, upgrade } = traducirErrorDeChat(e)` es la forma
    // exacta que usa el catch del chat. Si se moviera adentro del try, la
    // primera versión del escáner no decía nada.
    const f = escanear({ 'd.js': `
export function a() {
  try { const { mensaje, usage } = traducir(x); return mensaje }
  catch (e) { console.log(mensaje, usage) }
}
export function b() {
  try { const [x1, y1] = pares(); return x1 } catch (e) { console.log(x1, y1) }
}
export function c() {
  try { const { a: renombrada, ...resto } = obj } catch (e) { usar(renombrada, resto) }
}` })
    expect(f.map(x => x.nombre).sort()).toEqual(
      ['mensaje', 'renombrada', 'resto', 'usage', 'x1', 'y1'])
  })

  it('ve una función declarada adentro del try', () => {
    const f = escanear({ 'f.js': `
export function a() {
  try { function ayuda() { return 1 } return ayuda() } catch (e) { return ayuda() }
}` })
    expect(f).toHaveLength(1)
    expect(f[0].nombre).toBe('ayuda')
  })

  it('NO reporta lo que sí es válido — ninguno de los siete', () => {
    const f = escanear({ 'ok.js': `
export function sombra() {
  let dato = 'afuera'                      // el catch ve ESTA
  try { if (x) { const dato = 'adentro'; usar(dato) }; throw new Error() }
  catch (e) { return dato }
}
export function antes() {
  const previo = 1                         // declarada ANTES del try
  try { const otro = 2; return otro } catch (e) { return previo }
}
export function izada() {
  try { var v = 1 } catch (e) { return v } // var se iza a la función
}
export function propia() {
  try { const x = 1; return x } catch (e) { const x = 2; return x }
}
export function propiedad() {
  try { const dato = 1; return dato } catch (e) { return e.dato }
}
export function anidada() {
  const cb = () => { const interna = 1; return interna }   // otro alcance
  try { cb() } catch (e) { return cb() }
}
export function parametro(dato) {
  try { const dato2 = 1; return dato2 } catch (e) { return dato }
}` })
    expect(f).toEqual([])
  })
})
