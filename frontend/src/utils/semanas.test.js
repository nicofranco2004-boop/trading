/**
 * Las cuentas de la tira "Semana a semana".
 *
 * Los casos que tienen test acá no son decorativos: son las cuatro formas
 * conocidas en las que un gráfico de barras miente sin avisar, y las tres que ya
 * se pagaron en este repo.
 *
 *   1. LA SEMANA QUE NO SE PUDO MEDIR. El backend deja su resultado en CERO
 *      cuando no tiene con qué medirla (`basis_incomparable`). Dibujar ese cero
 *      afirma "tu cartera no se movió", que es otra cosa. Acá se exige que salga
 *      `null` —que no se dibuja— y que el pedazo que SÍ se conoce (las ventas)
 *      sobreviva.
 *   2. LA SEMANA DEL FUTURO. El motor arma todas las semanas cuyo lunes cae en
 *      el mes, incluidas las que todavía no pasaron. Sin filtro, la tira termina
 *      en barras vacías de semanas que no ocurrieron.
 *   3. LA SEGUNDA FORMA DE "NO PUDE MEDIR". El motor tiene dos: una levanta
 *      bandera y otra sólo se calla el porcentaje y publica el monto igual —
 *      que puede ser la cartera entera. Las dos tienen que terminar en hueco.
 *   4. LA FECHA QUE SE CORRE UN DÍA. `new Date('2026-09-07')` se interpreta en
 *      UTC y en Argentina devuelve el 6. El rótulo de la semana se arma partiendo
 *      el texto, y el test lo exige.
 */
import { describe, it, expect } from 'vitest'
import {
  MAX_SEMANAS, aplanarSemanas, ultimasSemanas, medirSemana, pedazosDe,
  escalaDeSerie, fraccionArriba, altoPorcentual, rangoSemana, diaCorto,
  claveSemanaISO, valorDe,
} from './semanas.js'

const HOY = '2026-09-13'

/** Una semana como la manda el backend. */
function semana(clave, inicio, fin, metrics = {}, extra = {}) {
  return {
    period_type: 'week',
    period_key: clave,
    period_label: `Semana ${clave.slice(-2)}`,
    period_start: inicio,
    period_end: fin,
    is_current: false,
    is_relevant: true,
    metrics: {
      // delta_pct con número por defecto a propósito: una semana que el motor
      // SÍ pudo medir siempre lo trae. El null es la señal de "no pude medir" y
      // los tests que la necesitan lo pasan explícito.
      delta_usd: 0, delta_pct: 0.5, realized_pnl: 0, unrealized_pnl: 0,
      trades_count: 0, basis_incomparable: false, ...metrics,
    },
    ...extra,
  }
}

const timeline = (...semanas) => [{ year: 2026, months: [{ period_type: 'month', children: semanas }] }]

describe('aplanarSemanas — qué semana entra a la tira', () => {
  it('saca las semanas de adentro de los meses y las ordena de vieja a nueva', () => {
    const datos = [
      { year: 2026, months: [
        { children: [semana('2026-W37', '2026-09-07', '2026-09-13')] },
        { children: [semana('2026-W35', '2026-08-24', '2026-08-30')] },
      ] },
    ]
    expect(aplanarSemanas(datos, HOY).map(s => s.period_key)).toEqual(['2026-W35', '2026-W37'])
  })

  it('deja afuera la semana que todavía no empezó', () => {
    const datos = timeline(
      semana('2026-W37', '2026-09-07', '2026-09-13'),
      semana('2026-W38', '2026-09-14', '2026-09-20'),   // arranca mañana
    )
    expect(aplanarSemanas(datos, HOY).map(s => s.period_key)).toEqual(['2026-W37'])
  })

  it('la semana que empieza HOY sí entra', () => {
    const datos = timeline(semana('2026-W38', HOY, '2026-09-19'))
    expect(aplanarSemanas(datos, HOY)).toHaveLength(1)
  })

  it('ignora lo que no sea una semana, lo vacío y lo roto', () => {
    const datos = [
      { year: 2026, months: [
        { children: [
          { period_type: 'month', period_key: '2026-09', period_start: '2026-09-01' },
          null,
          semana('2026-W36', '2026-08-31', '2026-09-06'),
          { period_type: 'week', period_key: '2026-W99' },   // sin fecha de inicio
        ] },
        { children: null },
        null,
      ] },
    ]
    expect(aplanarSemanas(datos, HOY).map(s => s.period_key)).toEqual(['2026-W36'])
  })

  it('no dibuja dos barras de la misma semana aunque llegue repetida', () => {
    const repetida = semana('2026-W36', '2026-08-31', '2026-09-06')
    const datos = [
      { year: 2026, months: [{ children: [repetida] }, { children: [repetida] }] },
    ]
    expect(aplanarSemanas(datos, HOY)).toHaveLength(1)
  })

  it('sin datos no explota', () => {
    expect(aplanarSemanas(undefined, HOY)).toEqual([])
    expect(aplanarSemanas([], HOY)).toEqual([])
  })
})

describe('ultimasSemanas — el recorte de la tira', () => {
  const fila = Array.from({ length: 20 }, (_, i) => `s${i}`)

  it('se queda con las últimas y en el mismo orden', () => {
    expect(ultimasSemanas(fila, 3)).toEqual(['s17', 's18', 's19'])
  })

  it('con menos semanas que el tope, no recorta nada', () => {
    expect(ultimasSemanas(['a', 'b'], MAX_SEMANAS)).toEqual(['a', 'b'])
  })
})

describe('medirSemana — traducir el dato del motor a lo que se dibuja', () => {
  it('una semana normal: los dos pedazos y el total', () => {
    const m = medirSemana(semana('2026-W36', '2026-08-31', '2026-09-06', {
      delta_usd: 804, realized_pnl: 180, unrealized_pnl: 624, delta_pct: 1.45, trades_count: 2,
    }))
    expect(m).toMatchObject({
      estado: 'medida', total: 804, abiertas: 624, cerradas: 180, pct: 1.45, operaciones: 2,
    })
  })

  it('los dos pedazos suman el total — es la definición del motor, no una casualidad', () => {
    const m = medirSemana(semana('2026-W35', '2026-08-24', '2026-08-30', {
      delta_usd: -1060, realized_pnl: 180, unrealized_pnl: -1240,
    }))
    expect(m.abiertas + m.cerradas).toBe(m.total)
  })

  it('sin base para medir: el total NO es cero, es nada', () => {
    const m = medirSemana(semana('2026-W29', '2026-07-13', '2026-07-19', {
      delta_usd: 0, unrealized_pnl: 0, realized_pnl: 340, basis_incomparable: true, delta_pct: null,
    }))
    expect(m.estado).toBe('sin-medicion')
    expect(m.total).toBeNull()
    expect(m.abiertas).toBeNull()
    expect(m.pct).toBeNull()
    // Lo que sí se conoce de esa semana sobrevive: las ventas se midieron.
    expect(m.cerradas).toBe(340)
  })

  it('una semana sin actividad queda marcada como quieta, no como sin medir', () => {
    const m = medirSemana(semana('2026-W33', '2026-08-10', '2026-08-16',
      { delta_usd: 38, unrealized_pnl: 38 }, { is_relevant: false }))
    expect(m.estado).toBe('quieta')
    expect(m.total).toBe(38)
  })

  it('la semana en curso viene marcada', () => {
    expect(medirSemana(semana('2026-W37', '2026-09-07', '2026-09-13', {}, { is_current: true })).enCurso).toBe(true)
  })

  it('un objeto incompleto no rompe la tira: sale como hueco, no como cero', () => {
    // Sin métricas no hay porcentaje, y sin porcentaje no hay medición. Publicar
    // un cero sería afirmar que esa semana no se movió.
    expect(medirSemana({}).estado).toBe('sin-medicion')
    expect(medirSemana({}).total).toBeNull()
    expect(medirSemana(null).cerradas).toBe(0)
  })
})

describe('pedazosDe — qué se dibuja en cada modo', () => {
  const m = medirSemana(semana('2026-W36', '2026-08-31', '2026-09-06', {
    delta_usd: 804, realized_pnl: 180, unrealized_pnl: 624,
  }))

  it('en "Todo" van los dos pedazos', () => {
    expect(pedazosDe(m, 'todo').map(p => p.valor)).toEqual([624, 180])
  })

  it('en "Sólo abiertas" desaparece lo realizado — que es el pedido original', () => {
    expect(pedazosDe(m, 'abiertas').map(p => p.valor)).toEqual([624])
  })

  it('una semana sin medición no aporta ningún pedazo', () => {
    const sinBase = medirSemana(semana('2026-W29', '2026-07-13', '2026-07-19',
      { realized_pnl: 340, basis_incomparable: true }))
    expect(pedazosDe(sinBase, 'todo')).toEqual([])
  })
})

describe('escalaDeSerie — una sola escala para todas las barras', () => {
  it('separa lo que va para arriba de lo que va para abajo', () => {
    const medidas = [
      medirSemana(semana('a', '2026-08-03', '2026-08-09', { delta_usd: 952, unrealized_pnl: 742, realized_pnl: 210 })),
      medirSemana(semana('b', '2026-08-10', '2026-08-16', { delta_usd: -382, unrealized_pnl: -318, realized_pnl: -64 })),
    ]
    expect(escalaDeSerie(medidas, 'todo')).toEqual({ arriba: 952, abajo: 382 })
  })

  it('cuando los dos pedazos apuntan a lados distintos, cada uno cuenta de su lado', () => {
    // La semana del 24 de agosto: las posiciones cayeron 1.240 y una venta dejó 180.
    const medidas = [medirSemana(semana('c', '2026-08-24', '2026-08-30',
      { delta_usd: -1060, unrealized_pnl: -1240, realized_pnl: 180 }))]
    expect(escalaDeSerie(medidas, 'todo')).toEqual({ arriba: 180, abajo: 1240 })
  })

  it('en "Sólo abiertas" la escala ignora lo realizado', () => {
    const medidas = [medirSemana(semana('d', '2026-08-03', '2026-08-09',
      { delta_usd: 952, unrealized_pnl: 200, realized_pnl: 752 }))]
    expect(escalaDeSerie(medidas, 'abiertas')).toEqual({ arriba: 200, abajo: 0 })
  })

  it('las semanas sin medición no estiran la escala', () => {
    const medidas = [
      medirSemana(semana('e', '2026-07-13', '2026-07-19', { realized_pnl: 9999, basis_incomparable: true })),
      medirSemana(semana('f', '2026-07-20', '2026-07-26', { delta_usd: 100, unrealized_pnl: 100 })),
    ]
    expect(escalaDeSerie(medidas, 'todo')).toEqual({ arriba: 100, abajo: 0 })
  })

  it('sin datos devuelve escala vacía en vez de romper', () => {
    expect(escalaDeSerie([], 'todo')).toEqual({ arriba: 0, abajo: 0 })
    expect(escalaDeSerie(undefined, 'todo')).toEqual({ arriba: 0, abajo: 0 })
  })
})

describe('fraccionArriba — dónde cae la línea del cero', () => {
  it('una serie toda positiva usa toda la caja para arriba', () => {
    expect(fraccionArriba({ arriba: 900, abajo: 0 })).toBe(1)
  })

  it('una serie toda negativa, al revés', () => {
    expect(fraccionArriba({ arriba: 0, abajo: 900 })).toBe(0)
  })

  it('serie equilibrada: el cero al medio', () => {
    expect(fraccionArriba({ arriba: 500, abajo: 500 })).toBe(0.5)
  })

  it('serie plana o vacía: el cero al medio, sin dividir por cero', () => {
    expect(fraccionArriba({ arriba: 0, abajo: 0 })).toBe(0.5)
    expect(fraccionArriba()).toBe(0.5)
  })

  // LA PROPIEDAD QUE HACE COMPARABLE AL GRÁFICO, y la que un tope de 0,88/0,12
  // rompía: un dólar tiene que medir lo mismo arriba que abajo de la línea.
  // Sin esto, con una serie de +US$2.000 y una sola semana de −US$20, la
  // perdedora se dibujaba MÁS ALTA que una ganadora de +US$200.
  it('un dólar mide lo mismo de los dos lados de la línea', () => {
    const H = 224
    const escala = { arriba: 2000, abajo: 20 }
    const frac = fraccionArriba(escala)
    const altoArribaPx = (v) => (altoPorcentual(v, escala.arriba) / 100) * (frac * H)
    const altoAbajoPx = (v) => (altoPorcentual(v, escala.abajo) / 100) * ((1 - frac) * H)

    // El mismo monto, de los dos lados, tiene que dar el mismo alto.
    expect(altoAbajoPx(-20)).toBeCloseTo(altoArribaPx(20), 6)

    // Y el orden tiene que respetarse: 200 dólares se ven más que 20.
    expect(altoArribaPx(200)).toBeGreaterThan(altoAbajoPx(-20))
  })
})

describe('valorDe — el número que representa la barra', () => {
  const m = medirSemana(semana('2026-W36', '2026-08-31', '2026-09-06', {
    delta_usd: 804, realized_pnl: 180, unrealized_pnl: 624,
  }))

  it('en "Todo" es el resultado de la semana', () => {
    expect(valorDe(m, 'todo')).toBe(804)
  })

  it('en "Sólo abiertas" es la parte de las abiertas, no el total', () => {
    expect(valorDe(m, 'abiertas')).toBe(624)
  })

  it('una semana sin medición no tiene número que anunciar', () => {
    const sinBase = medirSemana(semana('x', '2026-07-13', '2026-07-19', { basis_incomparable: true }))
    expect(valorDe(sinBase, 'todo')).toBeNull()
    expect(valorDe(null, 'todo')).toBeNull()
  })
})

describe('altoPorcentual — el alto de cada pedazo', () => {
  it('proporcional al máximo de su lado', () => {
    expect(altoPorcentual(500, 1000)).toBe(50)
  })

  it('es proporción pura: un resultado chico da un alto chico', () => {
    // Sin piso en porcentaje a propósito — un piso sobre el ÁREA vale distinto
    // de cada lado de la línea y deforma la escala. Que el pedazo diminuto se
    // vea es trabajo del alto mínimo en píxeles del componente.
    expect(altoPorcentual(1, 1000)).toBe(0.1)
  })

  it('nunca se derrama sobre las barras de al lado', () => {
    expect(altoPorcentual(2000, 1000)).toBe(100)
  })

  it('cero, nulo y escala vacía no dibujan nada', () => {
    expect(altoPorcentual(0, 1000)).toBe(0)
    expect(altoPorcentual(null, 1000)).toBe(0)
    expect(altoPorcentual(NaN, 1000)).toBe(0)
    expect(altoPorcentual(100, 0)).toBe(0)
  })
})

describe('medirSemana — las DOS formas en que el motor dice "no pude medir"', () => {
  // La ruidosa (basis_incomparable) ya está cubierta arriba. Esta es la callada:
  // el motor publica el monto y se NIEGA a publicar el porcentaje. Pasa cuando
  // no hay foto que abra la semana —y entonces el monto es la cartera entera— o
  // cuando las dos fotos están a más de 10 días. Dibujar esa barra como normal
  // publica un número inventado Y se lleva la escala de las otras once.
  it('sin porcentaje publicado, la semana no se dibuja aunque traiga monto', () => {
    const m = medirSemana(semana('2026-W31', '2026-07-27', '2026-08-02', {
      delta_usd: 41800,        // la cartera entera, no el resultado de la semana
      unrealized_pnl: 41800,
      realized_pnl: 0,
      delta_pct: null,         // el motor se negó: dw_incomplete
      basis_incomparable: false,
    }))
    expect(m.estado).toBe('sin-medicion')
    expect(m.total).toBeNull()
    expect(m.abiertas).toBeNull()
  })

  it('y entonces tampoco estira la escala de las demás', () => {
    const medidas = [
      medirSemana(semana('a', '2026-07-27', '2026-08-02', { delta_usd: 41800, unrealized_pnl: 41800, delta_pct: null })),
      medirSemana(semana('b', '2026-08-03', '2026-08-09', { delta_usd: 300, unrealized_pnl: 300, delta_pct: 0.7 })),
    ]
    expect(escalaDeSerie(medidas, 'todo')).toEqual({ arriba: 300, abajo: 0 })
  })

  it('CON UN BROKER ELEGIDO es al revés: el porcentaje nulo es de diseño y el monto sirve', () => {
    // builder.py:1780-1786 — sin foto por broker, delta = realizado y % = None.
    // Tratarlo como "sin medición" escondería el único número honesto que hay.
    const cruda = semana('2026-W33', '2026-08-10', '2026-08-16', {
      delta_usd: 180, realized_pnl: 180, unrealized_pnl: 0, delta_pct: null,
    })
    expect(medirSemana(cruda, { porBroker: true }).estado).toBe('medida')
    expect(medirSemana(cruda, { porBroker: true }).total).toBe(180)
    // La misma semana en la cartera global sí es un hueco.
    expect(medirSemana(cruda).estado).toBe('sin-medicion')
  })

  it('una semana normal, con su porcentaje, sigue siendo normal', () => {
    const m = medirSemana(semana('2026-W36', '2026-08-31', '2026-09-06', {
      delta_usd: 804, realized_pnl: 180, unrealized_pnl: 624, delta_pct: 1.45,
    }))
    expect(m.estado).toBe('medida')
  })
})

describe('claveSemanaISO — 400 días contra una implementación independiente', () => {
  // Este cambio reemplazó la cuenta de semana que Reports.jsx tenía escrita a
  // mano. De ella depende QUÉ SEMANA pide la tarjeta grande del período, así que
  // una diferencia de un día en un borde de año haría que la pantalla muestre
  // otra semana sin que nada falle. Acá la referencia se escribe aparte, con el
  // algoritmo ISO clásico, y se comparan 400 días seguidos: si alguien toca
  // `claveSemanaISO`, este test lo agarra.
  function referencia(y, m, d) {
    const fecha = new Date(Date.UTC(y, m - 1, d))
    const dia = fecha.getUTCDay() || 7
    fecha.setUTCDate(fecha.getUTCDate() + 4 - dia)
    const arranque = new Date(Date.UTC(fecha.getUTCFullYear(), 0, 1))
    const n = Math.ceil(((fecha - arranque) / 86400000 + 1) / 7)
    return `${fecha.getUTCFullYear()}-W${String(n).padStart(2, '0')}`
  }

  it('coincide en los 400 días alrededor de hoy', () => {
    const diferencias = []
    for (let i = -200; i <= 200; i++) {
      const d = new Date(Date.UTC(2026, 8, 14))
      d.setUTCDate(d.getUTCDate() + i)
      const iso = d.toISOString().slice(0, 10)
      const [y, m, dd] = iso.split('-').map(Number)
      if (claveSemanaISO(iso) !== referencia(y, m, dd)) diferencias.push(iso)
    }
    expect(diferencias).toEqual([])
  })

  it('y en los bordes de año, que es donde ISO se pone raro', () => {
    for (const iso of ['2024-12-30', '2025-12-28', '2025-12-29', '2026-01-01',
                       '2026-01-04', '2026-01-05', '2027-01-03']) {
      const [y, m, d] = iso.split('-').map(Number)
      expect(`${iso} → ${claveSemanaISO(iso)}`).toBe(`${iso} → ${referencia(y, m, d)}`)
    }
  })
})

describe('rangoSemana / diaCorto — el rótulo, sin el corrimiento de huso', () => {
  it('una semana dentro del mismo mes', () => {
    expect(rangoSemana('2026-09-07', '2026-09-13')).toBe('7 – 13 sep')
  })

  it('una semana que cruza de mes', () => {
    expect(rangoSemana('2026-08-31', '2026-09-06')).toBe('31 ago – 6 sep')
  })

  it('una semana que cruza de año', () => {
    expect(rangoSemana('2025-12-29', '2026-01-04')).toBe('29 dic – 4 ene')
  })

  it('el día es el que dice el texto, no el que devolvería un Date en UTC', () => {
    // new Date('2026-09-07') en Argentina cae el 6 a las 21:00.
    expect(diaCorto('2026-09-07')).toBe('7 sep')
  })

  it('una fecha rota devuelve vacío en vez de "NaN undefined"', () => {
    expect(diaCorto('')).toBe('')
    expect(diaCorto(null)).toBe('')
    expect(rangoSemana(null, null)).toBe('')
    expect(diaCorto('2026-13-45')).toBe('')
  })
})
