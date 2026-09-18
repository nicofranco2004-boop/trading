// El depósito/retiro tiene que llevar FECHA desde todas las pantallas.
//
// POR QUÉ ESTE TEST
// ─────────────────
// `POST /api/cash/flow` acepta `date` opcional y, cuando no viene, bookea el
// movimiento en `monthly_entries` con el mes de HOY (backend/main.py: `now =
// datetime.utcnow()` … `if data.date:`). O sea: el campo que decide EN QUÉ MES
// se asienta el aporte es opcional en el contrato y silencioso cuando falta.
//
// Escritorio lo mandaba desde siempre. El celular NO: su modal de depósito
// nunca tuvo el campo de fecha y el POST salía sin `date`. Un depósito de marzo
// cargado desde el teléfono entraba como aporte de HOY, y el capital aportado
// —que es el DENOMINADOR del rendimiento— quedaba corrido de mes. Nada en
// pantalla lo delataba: el mismo movimiento daba un número distinto según el
// aparato desde el que se hubiera cargado.
//
// Es la forma exacta del hallazgo del `fxHist` que guarda sellModalProps.test.js
// y la razón de la regla de propagación de CLAUDE.md: el fix estaba bien escrito
// en 1 de 2 call sites.
//
// CÓMO FUNCIONA
// ─────────────
// No hay jsdom en este proyecto, así que se verifica sobre el CÓDIGO FUENTE:
//   1. cada `api.post('/cash/flow'` del árbol manda `date`;
//   2. cada `<CashFlowModal` recibe `fxHist` y `tcValuacion` (sin ellas la línea
//      "equivalente en USD" cae al dólar de hoy para una fecha pasada);
//   3. el modal sigue siendo UNO solo — si mañana alguien vuelve a escribir el
//      formulario inline en una página, este test lo caza.
// Una pantalla nueva que se olvide falla acá aunque nadie recuerde este archivo,
// que es exactamente el caso a cazar.

import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { finDeEtiqueta } from '../../pages/sellModalProps.test.js'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', '..')

function archivosFuente(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) return archivosFuente(p)
    return /\.jsx?$/.test(n) && !/\.test\.jsx?$/.test(n) ? [p] : []
  })
}

const rel = (f) => f.slice(SRC.length + 1)

/** Cada `api.post('/cash/flow', { … })` del árbol, con su objeto de payload. */
function llamadas() {
  const out = []
  for (const f of archivosFuente(SRC)) {
    const src = readFileSync(f, 'utf8')
    let i = src.indexOf("api.post('/cash/flow'")
    while (i !== -1) {
      // El payload arranca en la `{` que sigue a la coma y termina en su cierre.
      const abre = src.indexOf('{', i)
      let depth = 0
      let fin = abre
      for (let j = abre; j < src.length; j++) {
        if (src[j] === '{') depth++
        else if (src[j] === '}') { depth--; if (depth === 0) { fin = j + 1; break } }
      }
      out.push({ archivo: rel(f), payload: src.slice(abre, fin) })
      i = src.indexOf("api.post('/cash/flow'", i + 1)
    }
  }
  return out
}

/** Cada `<CashFlowModal ... >` del árbol, con su bloque de props. */
function renders() {
  const out = []
  for (const f of archivosFuente(SRC)) {
    const src = readFileSync(f, 'utf8')
    let i = src.indexOf('<CashFlowModal')
    while (i !== -1) {
      out.push({ archivo: rel(f), props: src.slice(i, finDeEtiqueta(src, i)) })
      i = src.indexOf('<CashFlowModal', i + 1)
    }
  }
  return out
}

describe('POST /cash/flow — contrato del payload', () => {
  it('lo llama más de una pantalla (si no, este test sobra)', () => {
    expect(llamadas().length).toBeGreaterThan(1)
  })

  it('TODAS las llamadas mandan `date`', () => {
    const sinFecha = llamadas().filter(l => !/\bdate\s*:/.test(l.payload))
    expect(sinFecha.map(l => l.archivo)).toEqual([])
  })

  it('TODAS las llamadas mandan `tc_blue` (el fallback para dolarizar pesos)', () => {
    const sinTc = llamadas().filter(l => !/\btc_blue\s*:/.test(l.payload))
    expect(sinTc.map(l => l.archivo)).toEqual([])
  })
})

describe('CashFlowModal — contrato de props', () => {
  it('lo renderiza más de una pantalla', () => {
    expect(renders().length).toBeGreaterThan(1)
  })

  it('TODOS los renderers pasan fxHist', () => {
    const sin = renders().filter(r => !/\bfxHist\s*=/.test(r.props))
    expect(sin.map(r => r.archivo)).toEqual([])
  })

  it('TODOS los renderers pasan tcValuacion', () => {
    const sin = renders().filter(r => !/\btcValuacion\s*=/.test(r.props))
    expect(sin.map(r => r.archivo)).toEqual([])
  })

  it('el formulario vive en UN solo archivo — nadie lo reescribe inline', () => {
    // La marca del formulario es su etiqueta de monto. Si aparece fuera del
    // componente compartido, alguien volvió a duplicarlo y las dos copias van a
    // separarse otra vez.
    const duenios = archivosFuente(SRC)
      .filter(f => /Monto \(\{?\s*(form|cashFlowForm)\./.test(readFileSync(f, 'utf8')))
      .map(rel)
    expect(duenios).toEqual(['components/cash/CashFlowModal.jsx'])
  })
})
