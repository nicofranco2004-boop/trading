// Revisión final de «Mover a otro broker»: dos lecturas de la pantalla que no
// entendían a los pases.
//
//  · Importaciones ofrecía «Forzar revert» ante un freno de un pase, que el servidor
//    mira ANTES del modo forzado: forzar devolvía el mismo error (contrato #2). Los
//    textos de abajo son los del servidor (importing/traspaso_a_mano.py), copiados.
//  · «Aportado neto» de Movimientos sumaba sólo depósitos y retiros: con el filtro de
//    un broker, o con una pata sola (se borró el otro broker), no coincidía con el
//    aportado de /mensual y del Dashboard en el valor de los títulos (contable H1).
import { describe, it, expect } from 'vitest'
import { esFrenoDeUnPase } from './moverDeBroker'
import { computeMovementKpis } from '../pages/Operations.jsx'

describe('los frenos de un pase al revertir un archivo', () => {
  it('reconoce los tres textos del servidor', () => {
    expect(esFrenoDeUnPase('Este lote es un pase de títulos entre tus brokers: no se revierte desde ' +
      'acá. Deshacé el pase entero desde Movimientos (la fila «Pase» → Deshacer).')).toBe(true)
    expect(esFrenoDeUnPase('Hay títulos de esta importación que pasaste a Balanz el 16/06/2025. ' +
      'Deshacé ese pase (Movimientos → la fila «Pase» → Deshacer) antes de revertir el archivo.')).toBe(true)
    expect(esFrenoDeUnPase('Esto cambia la historia de NVDA en Cocos antes de tu pase del 16/06/2025 a ' +
      'Balanz, y el pase quedaría con otros lotes. Primero deshacé el pase (Movimientos → la fila ' +
      '«Pase» → Deshacer), hacé este cambio y después volvé a moverlos.')).toBe(true)
  })
  it('no confunde los frenos de siempre (ahí «Forzar revert» sí sirve)', () => {
    expect(esFrenoDeUnPase('Este import tiene ventas: revertirlo puede dejar posiciones vendidas.')).toBe(false)
    expect(esFrenoDeUnPase('')).toBe(false)
    expect(esFrenoDeUnPase(undefined)).toBe(false)
  })
})

describe('«Aportado neto» de Movimientos cuenta las patas de un pase', () => {
  const sumar = (filas, getUsd) => filas.reduce((s, f) => s + getUsd(f), 0)
  const kpi = (filas) => computeMovementKpis(filas, 'all', { sumar, fmt: String }, 0)
    .find(k => k.label === 'Aportado neto')
  // Cocos deposita 1.000 y pasa a Balanz títulos que valían 415,51; Balanz deposita 554,17.
  const cocos = [
    { type: 'DEPOSIT', broker: 'Cocos', amount_usd: 1000 },
    { type: 'TRASPASO_SALIDA', broker: 'Cocos', amount_usd: 415.51, traspaso_id: 'p1' },
  ]
  const balanz = [
    { type: 'DEPOSIT', broker: 'Balanz', amount_usd: 554.17 },
    { type: 'TRASPASO_ENTRADA', broker: 'Balanz', amount_usd: 415.51, traspaso_id: 'p1' },
  ]

  it('la cuenta entera: las dos patas se anulan y el número no cambia', () => {
    const k = kpi([...cocos, ...balanz])
    expect(k.num).toBeCloseTo(1554.17, 6)
    expect(k.sub).toBe('2 depósitos · 0 retiros')
  })

  it('filtrado por un broker: el aportado de ese broker, como /mensual', () => {
    expect(kpi(cocos).num).toBeCloseTo(1000 - 415.51, 6)
    expect(kpi(balanz).num).toBeCloseTo(554.17 + 415.51, 6)
    expect(kpi(cocos).sub).toBe('1 depósitos · 0 retiros · incluye 1 pase entre tus brokers')
  })

  it('con una pata sola (se borró el otro broker): cuenta la que queda', () => {
    expect(kpi(cocos).num).toBeCloseTo(584.49, 6)
  })
})
