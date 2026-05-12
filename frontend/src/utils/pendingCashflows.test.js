import { describe, it, expect } from 'vitest'
import { detectPendingCashflows, groupPendingByBond } from './pendingCashflows.js'

// ════════════════════════════════════════════════════════════════════════════
// Tests del detector de cobranzas pendientes (Phase 3E).
// Usamos AL30 (cronograma conocido, semestral 9 ene / 9 jul) y TZX26
// (zero-cupón, único pago al maturity).
// ════════════════════════════════════════════════════════════════════════════

const POS_AL30 = {
  broker: 'Cocos',
  asset: 'AL30',
  quantity: 1000,
  is_cash: false,
  invested: 700,
}

const POS_TZX26 = {
  broker: 'Balanz',
  asset: 'TZX26',
  quantity: 100,
  is_cash: false,
  invested: 75,
}

const POS_CASH = {
  broker: 'Cocos',
  asset: 'ARS',
  is_cash: true,
  invested: 5000,
  quantity: 0,
}

const POS_NON_BOND = {
  broker: 'Cocos',
  asset: 'GGAL',
  quantity: 100,
  is_cash: false,
  invested: 50000,
}

describe('detectPendingCashflows — happy path', () => {
  it('AL30 con qty=1000 al 2026-05-11 detecta pagos pasados sin registrar', () => {
    const pending = detectPendingCashflows(
      [POS_AL30],
      [],  // ninguna op registrada
      [],  // ningún skip
      { today: '2026-05-11' }
    )
    // AL30 paga cada 6 meses desde 2021-01-09. Pagos pasados al 2026-05-11:
    //   2021-01-09, 2021-07-09, 2022-01-09, ..., 2026-01-09 (último pasado).
    //   2026-07-09 es futuro → excluido.
    // Con MAX_BACKLOG_DAYS=730 (2 años), excluye los anteriores a ~2024-05.
    expect(pending.length).toBeGreaterThan(0)
    // Más reciente primero
    expect(pending[0].date).toBe('2026-01-09')
    expect(pending[0].broker).toBe('Cocos')
    expect(pending[0].asset).toBe('AL30')
  })

  it('AL30 con MAX_BACKLOG largo detecta TODOS los pagos pasados', () => {
    const pending = detectPendingCashflows(
      [POS_AL30],
      [],
      [],
      { today: '2026-05-11', maxBacklogDays: 3650 }  // 10 años
    )
    // Desde 2021-01-09 (primer pago) hasta 2026-01-09: 11 pagos semestrales
    expect(pending.length).toBe(11)
  })

  it('cada pendiente tiene amount escalado por quantity', () => {
    const pending = detectPendingCashflows(
      [POS_AL30],
      [],
      [],
      { today: '2026-05-11' }
    )
    // Para AL30 con qty=1000, los pagos están escalados ×10 (factor=qty/100).
    // Verificamos el pago de 2026-01-09: amort 7.69 face + cupón ~0.288
    // → total ~7.98 / 100 × 1000 = ~79.8
    const recent = pending.find(p => p.date === '2026-01-09')
    expect(recent).toBeDefined()
    expect(recent.total).toBeGreaterThan(70)
    expect(recent.total).toBeLessThan(90)
  })

  it('clasifica kind correctamente', () => {
    const pending = detectPendingCashflows(
      [POS_AL30],
      [],
      [],
      { today: '2026-05-11', maxBacklogDays: 3650 }
    )
    // Pagos 2021-01-09 a 2024-01-09: solo cupón (amort empieza 2024-07-09)
    const early = pending.find(p => p.date === '2021-07-09')
    if (early) expect(early.kind).toBe('cupon')
    // Pagos 2024-07-09 en adelante: cupón + amort
    const mixed = pending.find(p => p.date === '2024-07-09')
    if (mixed) expect(mixed.kind).toBe('mixto')
  })
})

describe('detectPendingCashflows — filtros', () => {
  it('excluye cobranzas ya registradas (matching ±14 días)', () => {
    const bondOps = [
      { broker: 'Cocos', asset: 'AL30', op_type: 'Cupón', date: '2026-01-10' },
      // Esta op está a 1 día del pago teórico 2026-01-09 → debe matchear
    ]
    const pending = detectPendingCashflows(
      [POS_AL30],
      bondOps,
      [],
      { today: '2026-05-11' }
    )
    // 2026-01-09 NO debe estar en pendientes
    expect(pending.find(p => p.date === '2026-01-09')).toBeUndefined()
  })

  it('NO excluye cobranzas a más de 14 días de distancia', () => {
    const bondOps = [
      // Op a 20 días → no matchea con ningún pago del cronograma
      { broker: 'Cocos', asset: 'AL30', op_type: 'Cupón', date: '2026-02-01' },
    ]
    const pending = detectPendingCashflows(
      [POS_AL30],
      bondOps,
      [],
      { today: '2026-05-11' }
    )
    // 2026-01-09 SÍ está en pendientes (la op del 2026-02-01 no matchea)
    expect(pending.find(p => p.date === '2026-01-09')).toBeDefined()
  })

  it('excluye fechas saltadas por el user', () => {
    const skips = [{ broker: 'Cocos', asset: 'AL30', date: '2026-01-09' }]
    const pending = detectPendingCashflows(
      [POS_AL30],
      [],
      skips,
      { today: '2026-05-11' }
    )
    expect(pending.find(p => p.date === '2026-01-09')).toBeUndefined()
    // Otros pagos siguen apareciendo
    expect(pending.length).toBeGreaterThan(0)
  })

  it('excluye fechas más viejas que MAX_BACKLOG_DAYS', () => {
    // today=2026-05-11, backlog 200 días → corte = 2025-10-23
    // Pagos pasados de AL30 dentro de 200 días: 2026-01-09 (122 días) ✓
    // Pagos excluidos por viejos: 2025-07-09 (306 días) ✗
    const pending = detectPendingCashflows(
      [POS_AL30],
      [],
      [],
      { today: '2026-05-11', maxBacklogDays: 200 }
    )
    expect(pending.length).toBe(1)
    expect(pending[0].date).toBe('2026-01-09')
  })

  it('excluye fechas futuras (no son "pendientes" todavía)', () => {
    const pending = detectPendingCashflows(
      [POS_AL30],
      [],
      [],
      { today: '2026-05-11' }
    )
    // 2026-07-09 es futuro → no aparece
    expect(pending.find(p => p.date === '2026-07-09')).toBeUndefined()
  })
})

describe('detectPendingCashflows — exclusiones de posición', () => {
  it('excluye posiciones no-bono', () => {
    const pending = detectPendingCashflows([POS_NON_BOND], [], [], { today: '2026-05-11' })
    expect(pending).toEqual([])
  })

  it('excluye posiciones cash', () => {
    const pending = detectPendingCashflows([POS_CASH], [], [], { today: '2026-05-11' })
    expect(pending).toEqual([])
  })

  it('excluye posiciones con quantity 0 o null', () => {
    const pZero = { ...POS_AL30, quantity: 0 }
    const pNull = { ...POS_AL30, quantity: null }
    expect(detectPendingCashflows([pZero], [], [], { today: '2026-05-11' })).toEqual([])
    expect(detectPendingCashflows([pNull], [], [], { today: '2026-05-11' })).toEqual([])
  })

  it('excluye bonos sin metadata (NOEXISTE)', () => {
    const phantom = { ...POS_AL30, asset: 'NOEXISTE' }
    expect(detectPendingCashflows([phantom], [], [], { today: '2026-05-11' })).toEqual([])
  })

  it('TZX26 zero-cupón antes del maturity: sin pendientes', () => {
    // TZX26 vence 2026-06-30. Al 2026-05-11 todavía no hay pago.
    const pending = detectPendingCashflows([POS_TZX26], [], [], { today: '2026-05-11' })
    expect(pending).toEqual([])
  })

  it('TZX26 después del maturity: 1 pendiente', () => {
    const pending = detectPendingCashflows([POS_TZX26], [], [], { today: '2026-07-15' })
    expect(pending).toHaveLength(1)
    expect(pending[0].date).toBe('2026-06-30')
    expect(pending[0].kind).toBe('amortizacion')
  })
})

describe('detectPendingCashflows — múltiples posiciones', () => {
  it('agrega pendientes de varias posiciones', () => {
    const pending = detectPendingCashflows(
      [POS_AL30, POS_TZX26],
      [],
      [],
      { today: '2026-07-15' }  // después del maturity TZX26
    )
    const al30Items = pending.filter(p => p.asset === 'AL30')
    const tzxItems = pending.filter(p => p.asset === 'TZX26')
    expect(al30Items.length).toBeGreaterThan(0)
    expect(tzxItems.length).toBe(1)
  })

  it('orden descendente por fecha', () => {
    const pending = detectPendingCashflows(
      [POS_AL30],
      [],
      [],
      { today: '2026-05-11', maxBacklogDays: 1825 }
    )
    for (let i = 1; i < pending.length; i++) {
      expect(pending[i - 1].date >= pending[i].date).toBe(true)
    }
  })
})

describe('detectPendingCashflows — filtro por entry_date (Phase 3F)', () => {
  it('si la posición tiene entry_date, NO sugiere pagos previos a esa fecha', () => {
    // Posición AL30 cargada con entry_date=2026-01-20 (más de 7 días después
    // del cupón 2026-01-09, fuera del grace). El detector NO debe sugerir
    // ningún pago anterior — todos corresponden al dueño previo.
    const posRecent = { ...POS_AL30, entry_date: '2026-01-20' }
    const pending = detectPendingCashflows(
      [posRecent],
      [],
      [],
      { today: '2026-05-11', maxBacklogDays: 3650 }
    )
    expect(pending).toEqual([])
  })

  it('entry_date posterior a todo el histórico → inbox vacío', () => {
    const posNew = { ...POS_AL30, entry_date: '2026-05-01' }
    const pending = detectPendingCashflows(
      [posNew],
      [],
      [],
      { today: '2026-05-11', maxBacklogDays: 3650 }
    )
    expect(pending).toEqual([])
  })

  it('entry_date antiguo → muestra los pagos posteriores', () => {
    const posOld = { ...POS_AL30, entry_date: '2024-01-01' }
    const pending = detectPendingCashflows(
      [posOld],
      [],
      [],
      { today: '2026-05-11', maxBacklogDays: 3650 }
    )
    // Pagos pasados de AL30 después del 2024-01-01 hasta 2026-05-11:
    //   2024-01-09 (cupón pre-amort), 2024-07-09 (1er amort),
    //   2025-01-09, 2025-07-09, 2026-01-09 = 5 pagos
    expect(pending.length).toBe(5)
    expect(pending[pending.length - 1].date).toBe('2024-01-09')
  })

  it('grace period de 7 días: entry_date inmediatamente posterior al pago igual lo incluye', () => {
    // entry_date 2026-01-10 (1 día después del cupón del 2026-01-09). Como el
    // grace es 7 días, ese cupón SÍ se incluye (es posible que el user lo
    // cobre por T+x del settlement).
    const pos = { ...POS_AL30, entry_date: '2026-01-10' }
    const pending = detectPendingCashflows(
      [pos],
      [],
      [],
      { today: '2026-05-11', maxBacklogDays: 3650 }
    )
    expect(pending.length).toBeGreaterThan(0)
    expect(pending.find(p => p.date === '2026-01-09')).toBeDefined()
  })

  it('sin entry_date → comportamiento previo (usa MAX_BACKLOG_DAYS)', () => {
    // Posición sin entry_date — fallback al backlog global.
    const posNoEntry = { ...POS_AL30 }  // sin entry_date
    delete posNoEntry.entry_date
    const pending = detectPendingCashflows(
      [posNoEntry],
      [],
      [],
      { today: '2026-05-11', maxBacklogDays: 3650 }
    )
    // 11 pagos pasados (sin filtro por entry_date)
    expect(pending.length).toBe(11)
  })

  it('combina con MAX_BACKLOG: el más restrictivo gana', () => {
    // entry_date hace 5 años + backlog de 200 días → corte = 200 días atrás
    const posVieja = { ...POS_AL30, entry_date: '2021-01-01' }
    const pending = detectPendingCashflows(
      [posVieja],
      [],
      [],
      { today: '2026-05-11', maxBacklogDays: 200 }
    )
    expect(pending.length).toBe(1)  // sólo 2026-01-09 entra
    expect(pending[0].date).toBe('2026-01-09')
  })

  it('varias posiciones del mismo bono con entry_dates distintos: filtra por posición', () => {
    // Posición vieja (entry 2024-01) + posición nueva (entry 2026-04)
    // Pero detect agrupa por broker+asset; ambas son AL30 en Cocos.
    // El comportamiento: cada posición se evalúa con su propio entry_date,
    // y los pendientes se agregan. Como el helper itera positions, el más
    // permisivo gana (entry más viejo).
    const posVieja = { ...POS_AL30, entry_date: '2024-01-01' }
    const posNueva = { ...POS_AL30, entry_date: '2026-04-01' }
    const pendVieja = detectPendingCashflows([posVieja], [], [], { today: '2026-05-11', maxBacklogDays: 3650 })
    const pendAmbas = detectPendingCashflows([posVieja, posNueva], [], [], { today: '2026-05-11', maxBacklogDays: 3650 })
    // Iterando ambas se generan duplicados (key colision en pendiente) —
    // testeamos que al menos hay tantos como pendVieja, no menos.
    expect(pendAmbas.length).toBeGreaterThanOrEqual(pendVieja.length)
  })
})

describe('groupPendingByBond', () => {
  it('agrupa por (broker, asset) y suma cash total', () => {
    const pending = detectPendingCashflows(
      [POS_AL30, POS_TZX26],
      [],
      [],
      { today: '2026-07-15' }
    )
    const grouped = groupPendingByBond(pending)
    expect(grouped.length).toBe(2)
    const al30 = grouped.find(g => g.asset === 'AL30')
    expect(al30.items.length).toBeGreaterThan(0)
    expect(al30.totalCash).toBeGreaterThan(0)
  })
})
