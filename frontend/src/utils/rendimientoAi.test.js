/**
 * El ✦ Analizar tiene que llevarle a la IA el MISMO número que muestra la pantalla.
 *
 * EL BUG (2026-09-25). El ✦ de la tarjeta de evolución le daba al modelo una resta
 * a secas de la curva. Con un depósito de US$ 8.000 en el medio del mes: chip
 * "+1,4 %", IA "+83 %". El del Home restaba los dos últimos cierres.
 *
 * Desde ahora el navegador manda el número que calculó y el servidor lo pasa tal
 * cual (backend/ai/builders/rendimiento_pantalla.py). Este test fija la mitad de
 * ese contrato que vive acá: que lo que viaja es EXACTAMENTE lo que calculó el
 * motor de la pantalla (`rendimientoDelRango`, `computeDailyPnl`), con la forma
 * que el servidor espera.
 *
 * Los casos salen de backend/tests/fixtures/rendimiento_pantalla.json, el mismo
 * archivo que lee backend/tests/test_ia_mismo_numero_que_la_pantalla.py — que
 * además verifica que el gemelo del servidor (`_snapshot_delta`) dé el mismo
 * número. Si un lado cambia la regla o la forma, se pone rojo el otro.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { computeDailyPnl, rendimientoDelRango } from './evolution.js'
import { fechaISO } from './fecha.js'
import { rendimientoParaIa } from './rendimientoAi.js'

const AQUI = dirname(fileURLToPath(import.meta.url))
const CONTRATO = JSON.parse(readFileSync(
  resolve(AQUI, '../../../backend/tests/fixtures/rendimiento_pantalla.json'), 'utf8'))
const DEPOSITO = CONTRATO.deposito_en_el_medio
const HUECO = CONTRATO.sin_cierre_cerca_del_arranque

// Mediodía local: lejos de la medianoche, así "hoy" no depende de la hora a la
// que corra la suite.
const HOY = new Date(2026, 8, 25, 12, 0, 0)

const hace = (dias) => {
  const d = new Date(HOY)
  d.setDate(d.getDate() - dias)
  return fechaISO(d)
}

// Filas como las devuelve /api/snapshots: medidas (`apto`) y con su aportado.
const cierres = (caso, apto = 1) => caso.cierres.map(c => ({
  date: hace(c.dias_atras),
  total_value: c.total_value,
  total_invested: c.total_value,
  net_deposited: c.net_deposited,
  apto,
}))

// Lo que el servidor tiene que recibir: los params del contrato, con la fecha
// resuelta al día del test.
const esperado = ({ desde_dias_atras, ...resto }) => ({ ...resto, desde: hace(desde_dias_atras) })

const vivo = (caso) => ({ liveValue: caso.vivo.valor, liveNetDeposited: caso.vivo.aportado })

describe('rendimientoParaIa — lo que viaja es lo que muestra la pantalla', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(HOY)
  })
  afterEach(() => vi.useRealTimers())

  it('el chip de la curva con un depósito en el medio del mes: +1,43 %, no +83 %', () => {
    const chip = rendimientoDelRango(cierres(DEPOSITO), { dias: DEPOSITO.dias, ...vivo(DEPOSITO) })
    const p = rendimientoParaIa(chip)
    expect(p).toEqual(esperado(DEPOSITO.chip.params))
    expect(p.usd).not.toBe(DEPOSITO.resta_a_secas.usd)
    expect(p.pct).not.toBe(DEPOSITO.resta_a_secas.pct)
  })

  it('sin cierre cerca del arranque: mide desde el más cercano y viaja con su rótulo', () => {
    const chip = rendimientoDelRango(cierres(HUECO), { dias: HUECO.dias, ...vivo(HUECO) })
    expect(chip.desde).toBe(hace(20))            // la pantalla dice "desde el DD/MM"
    expect(rendimientoParaIa(chip)).toEqual(esperado(HUECO.chip.params))
  })

  it('la card "Hoy" / "P&L Día"', () => {
    expect(rendimientoParaIa(computeDailyPnl(cierres(DEPOSITO), vivo(DEPOSITO))))
      .toEqual(esperado(DEPOSITO.hoy.params))
  })

  it('sin número en pantalla viaja null, no una cuenta propia', () => {
    // Sin ninguna medición a mercado, el chip no tiene con qué medir.
    const chip = rendimientoDelRango(cierres(DEPOSITO, 0), { dias: DEPOSITO.dias, ...vivo(DEPOSITO) })
    expect(chip).toBeNull()
    expect(rendimientoParaIa(chip)).toBeNull()
  })

  it('sólo números, una fecha y un sí/no: nada de texto libre entra al contexto del modelo', () => {
    const p = rendimientoParaIa(rendimientoDelRango(cierres(HUECO), { dias: HUECO.dias, ...vivo(HUECO) }))
    for (const [k, v] of Object.entries(p)) {
      if (k === 'desde') expect(v).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      else if (k === 'rotulo_con_fecha') expect(v).toBe(true)
      else expect(typeof v).toBe('number')
    }
  })

  it('un objeto roto no viaja', () => {
    expect(rendimientoParaIa(null)).toBeNull()
    expect(rendimientoParaIa({ usd: NaN, pct: 0.1 })).toBeNull()
    expect(rendimientoParaIa({ usd: 10 })).toBeNull()
    expect(rendimientoParaIa({ usd: 10, pct: 'x' })).toBeNull()
  })
})
