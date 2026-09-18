// El menú de la fila tiene que ofrecer lo MISMO en la compu y en el teléfono.
//
// POR QUÉ ESTE TEST
// ─────────────────
// Hasta este cambio el menú estaba escrito dos veces: `buildPositionMenu` en
// Positions.jsx y un array a mano adentro de PositionRow en PositionsMobile.jsx.
// Se separaron sin que nada lo avisara — en el teléfono faltaban "Agregar
// compra", "Crear alerta", "Comprar USD" y el cupón/amortización de los bonos, y
// las dos opciones que sí estaban se llamaban distinto.
//
// Ahora la lista la decide una sola función. Este test fija QUÉ ofrece para cada
// tipo de fila; el de abajo fija que las dos pantallas la usen y que nadie
// vuelva a escribir un menú a mano.

import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildPositionActions } from './positionActions'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')

// Todos los handlers presentes: es el caso de una pantalla completa.
const TODOS = {
  onBuy: () => {}, onSell: () => {}, onAlert: () => {}, onEdit: () => {},
  onEditGroup: () => {}, onDelete: () => {}, onCashFlow: () => {},
  onConvert: () => {}, onBondCashflow: () => {}, onToggleLots: () => {},
}

const etiquetas = (acciones) => acciones.filter(a => !a.divider).map(a => a.label)

describe('buildPositionActions — qué ofrece cada tipo de fila', () => {
  it('una posición normal: comprar, vender, alertar, editar, eliminar', () => {
    const a = buildPositionActions({ asset: 'NVDA', broker: 'Schwab' }, TODOS, {})
    expect(etiquetas(a)).toEqual([
      'Agregar compra', 'Registrar venta', 'Crear alerta', 'Editar posición', 'Eliminar',
    ])
  })

  it('un bono pone cupón y amortización ARRIBA', () => {
    const a = buildPositionActions({ asset: 'AL30', broker: 'Cocos' }, TODOS, { isBond: true })
    expect(etiquetas(a).slice(0, 2)).toEqual(['Registrar cupón', 'Registrar amortización'])
  })

  it('el efectivo en pesos ofrece Comprar USD', () => {
    const a = buildPositionActions({ is_cash: true, broker: 'Cocos' }, TODOS,
      { broker: { currency: 'ARS' } })
    expect(etiquetas(a)).toEqual([
      'Depositar', 'Retirar', 'Comprar USD', 'Editar posición', 'Eliminar',
    ])
  })

  it('el efectivo en dólares de un sub-broker ofrece venderlos a pesos', () => {
    const a = buildPositionActions({ is_cash: true, broker: 'Cocos · USD' }, TODOS,
      { broker: { currency: 'USDT', parent_broker_id: 7 } })
    expect(etiquetas(a)).toContain('Vender USD a ARS')
  })

  it('el efectivo de una cuenta en dólares NO ofrece conversiones', () => {
    const a = buildPositionActions({ is_cash: true, broker: 'Schwab' }, TODOS,
      { broker: { currency: 'USDT', parent_broker_id: null } })
    expect(etiquetas(a)).toEqual(['Depositar', 'Retirar', 'Editar posición', 'Eliminar'])
  })

  it('la fila agregada edita el GRUPO y despliega los lotes', () => {
    const a = buildPositionActions({ asset: 'NVDA', broker: 'Schwab' }, TODOS,
      { isAgg: true, lotCount: 4 })
    expect(etiquetas(a)).toEqual([
      'Agregar compra', 'Registrar venta', 'Crear alerta', 'Ver lotes (4)', 'Editar posición',
    ])
  })

  it('la fila que junta las dos monedas abre los lotes PRIMERO', () => {
    const a = buildPositionActions({ asset: 'NVDA', broker: null, _multiBroker: true }, TODOS,
      { isAgg: true, lotCount: 3 })
    expect(etiquetas(a)[0]).toBe('Ver lotes (3)')
  })

  it('"Analizar" aparece sólo si la pantalla lo pasa (el teléfono sí, la compu no)', () => {
    const conIA = buildPositionActions({ asset: 'NVDA' }, { ...TODOS, onAnalyze: () => {} }, {})
    expect(etiquetas(conIA)[0]).toBe('Analizar')
    expect(etiquetas(buildPositionActions({ asset: 'NVDA' }, TODOS, {}))).not.toContain('Analizar')
  })

  it('un handler que falta esconde su ítem, no rompe', () => {
    const { onDelete, ...sinBorrar } = TODOS
    expect(etiquetas(buildPositionActions({ asset: 'NVDA' }, sinBorrar, {}))).not.toContain('Eliminar')
  })

  it('nunca deja separadores sueltos: ni al principio, ni al final, ni dos seguidos', () => {
    // Una pantalla mínima (sólo vender) dejaría todos los bloques vacíos.
    const casos = [
      buildPositionActions({ asset: 'NVDA' }, { onSell: () => {} }, {}),
      buildPositionActions({ is_cash: true }, { onCashFlow: () => {} }, {}),
      buildPositionActions({ asset: 'NVDA' }, { onSell: () => {} }, { isAgg: true }),
      buildPositionActions({ asset: 'NVDA' }, TODOS, { isAgg: true, lotCount: 2 }),
    ]
    for (const a of casos) {
      expect(a[0]?.divider).toBeFalsy()
      expect(a[a.length - 1]?.divider).toBeFalsy()
      expect(a.some((x, i) => x.divider && a[i + 1]?.divider)).toBe(false)
    }
  })

  it('todo ítem tiene id, etiqueta, ícono y acción', () => {
    for (const it of buildPositionActions({ asset: 'NVDA' }, TODOS, {}).filter(a => !a.divider)) {
      expect(it.id).toBeTruthy()
      expect(it.label).toBeTruthy()
      expect(it.icon).toBeTruthy()
      expect(typeof it.onClick).toBe('function')
    }
  })
})

describe('nadie vuelve a escribir el menú a mano', () => {
  function fuentes(dir) {
    return readdirSync(dir).flatMap((n) => {
      const p = join(dir, n)
      if (statSync(p).isDirectory()) return fuentes(p)
      return /\.jsx?$/.test(n) && !/\.test\.jsx?$/.test(n) ? [p] : []
    })
  }

  it('las dos pantallas de la cartera lo importan', () => {
    for (const f of ['pages/Positions.jsx', 'pages/PositionsMobile.jsx']) {
      expect(readFileSync(join(SRC, f), 'utf8')).toMatch(/buildPositionActions/)
    }
  })

  it('"Agregar compra" se declara como ítem de menú en UN solo archivo', () => {
    // Si `label: 'Agregar compra'` aparece en otro lado, alguien armó un segundo
    // menú — que es exactamente cómo las dos copias se separaron la vez pasada.
    // Se busca la DECLARACIÓN (`label:`), no la frase: las dos pantallas la
    // nombran en comentarios que explican de dónde salió cada handler.
    const duenios = fuentes(SRC)
      .filter(f => /label:\s*['"]Agregar compra['"]/.test(readFileSync(f, 'utf8')))
      .map(f => f.slice(SRC.length + 1))
    expect(duenios).toEqual(['utils/positionActions.js'])
  })
})
