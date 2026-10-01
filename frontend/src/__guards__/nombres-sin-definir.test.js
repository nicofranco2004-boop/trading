// Ningún archivo usa un nombre que no existe.
//
// POR QUÉ ESTE TEST
// ─────────────────
// 2026-10-01: al borrar el formateador `pct` local de Admin.jsx quedaron dos
// renglones llamándolo, 600 líneas más abajo. El build compiló y la suite
// entera pasó; la tabla de la auditoría MTM se habría caído al dibujar su
// primera fila ("pct is not defined" → ErrorBoundary, pantalla tapada). Es la
// misma familia que el backtick que falta en un className (la página de pago
// caída) y que la variable del try que el catch no ve. Detalle en
// scripts/scan-nombres-sin-definir.mjs.
//
// TOLERANCIA CERO: medido sobre todo src/ el día del arreglo, los únicos
// hallazgos eran esos dos, ya corregidos. Cualquier caso nuevo es un bug nuevo.
//
// Para verlo suelto:  node scripts/scan-nombres-sin-definir.mjs src
import { describe, it, expect } from 'vitest'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { buscarNombresSinDefinir, nombresSinDefinir } from '../../scripts/scan-nombres-sin-definir.mjs'

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

describe('nombres sin definir', () => {
  it('ningún archivo de src/ usa un nombre que no está definido', () => {
    const hallados = buscarNombresSinDefinir(SRC)
    const detalle = hallados
      .map(h => `${h.archivo}:${h.linea}: "${h.nombre}" no está definido. El build no lo ve `
              + `y la pantalla se cae recién al ejecutar ese renglón. ¿Falta un import, o se `
              + `borró una función que todavía se usa? Si es un global del navegador legítimo, `
              + `sumalo a GLOBALES_NAVEGADOR en scripts/scan-nombres-sin-definir.mjs.`)
      .join('\n')
    expect(hallados, detalle).toEqual([])
    // Resolver el alcance de ~370 archivos tarda ~2 s solo y hasta ~12 s con la
    // suite entera en paralelo: el tope de 5 s por test lo cortaba en falso.
  }, 60_000)
})

// El escaneo tiene que VER el caso que lo originó; si no, el verde de arriba
// no dice nada. Y no puede quejarse de código válido: un falso positivo en un
// guard de tolerancia cero termina con alguien borrando el guard.
describe('el escaneo — lo que ve y lo que no', () => {
  const nombres = (codigo) => nombresSinDefinir(codigo).map(h => h.nombre)

  it('ve la función borrada que se sigue llamando (el caso de Admin)', () => {
    expect(nombres(`
      import { pctVar } from './format'
      export default function Tabla({ o }) {
        return <td>{pctVar(o.a, 2)}{pct(o.b)}</td>
      }
    `)).toEqual(['pct'])
  })

  it('ve el className al que le falta el backtick (el caso de Planes)', () => {
    expect(nombres('export const C = ({ a }) => <p className={`${a ? font-medium`x` : "y"}`} />'))
      .toContain('font')
  })

  it('ve el componente que no se importó, y el objeto de <motion.div>', () => {
    expect(nombres('export const C = () => <><Panel /><motion.div /></>')).toEqual(['Panel', 'motion'])
  })

  it('no se queja de lo que está bien', () => {
    expect(nombres(`
      import React, { useState } from 'react'
      import * as fmt from './format'
      const { a, b: [c] } = obj()
      function obj() { return { a: 1, b: [2] } }
      export function F({ d = 1, ...resto }) {
        const [x] = useState(0)
        try { JSON.parse('1') } catch (e) { console.log(e) }
        for (const k of Object.keys(resto)) if (typeof noDeclarada === 'undefined') window.k = k
        class Z { m() { return this } }
        return <div onClick={() => setTimeout(() => {}, 0)}>{fmt.nfmt(a + c + d + x)}{new Z().m() && __BUILD_ID__}</div>
      }
    `)).toEqual([])
  })
})
