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

  it('el escáner encuentra el bug de verdad cuando está', () => {
    // Un guard que no se prueba contra el bug que dice cazar no vale nada: si el
    // recorrido se rompiera, devolvería [] y el test de arriba quedaría VERDE
    // certificando lo contrario de lo que pasa. Esto es el caso REAL, reducido.
    const fs = require('node:fs')
    const os = require('node:os')
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'guard-'))
    fs.writeFileSync(path.join(dir, 'caso.js'), `
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
}
`)
    const fugas = buscarFugasDeAlcance(dir)
    fs.rmSync(dir, { recursive: true, force: true })
    expect(fugas).toHaveLength(1)
    expect(fugas[0].nombre).toBe('agregado')
    expect(fugas[0].bloque).toBe('catch')
  })

  it('NO se queja de lo que sí es válido', () => {
    const fs = require('node:fs')
    const os = require('node:os')
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'guard-ok-'))
    fs.writeFileSync(path.join(dir, 'ok.js'), `
export function a() {
  let afuera = 1                 // declarada ANTES del try: el catch la ve
  try { afuera = 2 } catch (e) { console.log(afuera, e) }
}
export function b() {
  try { var izada = 1 } catch (e) { console.log(izada) }   // var se iza: válido
}
export function c() {
  try { const x = 1; return x } catch (e) { const x = 2; return x }  // otra x, propia
}
export function d() {
  try { const dato = 1; return dato } catch (e) { return e.dato }    // propiedad, no variable
}
`)
    const fugas = buscarFugasDeAlcance(dir)
    fs.rmSync(dir, { recursive: true, force: true })
    expect(fugas).toEqual([])
  })
})
