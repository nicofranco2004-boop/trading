import { describe, it, expect } from 'vitest'
import { tarjetas, tarjetaFuerza, tarjetaBandas, tarjetaMovimiento, textoRendPorMovimiento, colorSqueeze, fmtAdx, textoCruceAdx, textoSqueeze, velasSemanales, ADX_CLAVE, veredictoRsi, textoCruceRsi, lineaPromedio, marcas, indiceDeFecha, recortar, tendenciasDistintas, sumarVelaDeHoy, textoVelaDeHoy } from './tecnico'

const L = {
  ruedas: 760, fecha: '2026-10-21', precio: 228.97,
  media50: 241.49, dist_media50: -5.18, media200: 250.08, dist_media200: -8.44, tendencia: 'bajista',
  pendiente_media200: -1.2, rsi: 37.8, maximo_12m: 274.63, dist_maximo_12m: -16.63,
  anio_completo: true,
}

describe('tarjetas', () => {
  it('dice bajista con la media que baja, en palabras', () => {
    const t = tarjetas(L)
    const fondo = t.find(x => x.id === 'fondo')
    expect(fondo.veredicto).toBe('Bajista')
    expect(fondo.tono).toBe('neg')
    expect(fondo.texto).toBe('El precio está 8,4% abajo de su promedio de los últimos 200 días. Ese promedio viene bajando. '
      + 'Estar abajo de ese promedio es la referencia más usada para decir que la tendencia de largo plazo es bajista.')
    expect(t.find(x => x.id === 'corto').veredicto).toBe('Bajista')
    expect(t.find(x => x.id === 'rsi').veredicto).toBe('Pierde impulso')
    expect(t.find(x => x.id === 'rsi').texto).toContain('38 de 100. Compara el tamaño de las subas con el de las bajas de las últimas 3 semanas. Arriba de 50 el precio gana impulso')
    expect(t.find(x => x.id === 'maximo').veredicto).toBe('16,6% por debajo')
  })

  it('con pocas ruedas dice que faltan datos en vez de inventar la media', () => {
    const t = tarjetas({ ruedas: 120, media200: null, dist_media200: null, tendencia: null, media50: 10, dist_media50: 2, rsi: 50, dist_maximo_12m: -3, anio_completo: false })
    const fondo = t.find(x => x.id === 'fondo')
    expect(fondo.veredicto).toBe('Faltan datos')
    expect(fondo.texto).toContain('tiene 120')
    expect(t.find(x => x.id === 'maximo').titulo).toBe('Máximo del período')
  })

  it('la tendencia de largo plazo la decide el servidor (P6: una sola regla, tecnico.tendencia_de)', () => {
    // Un cierre a una millonésima abajo del promedio: la distancia redondea a 0,
    // pero el servidor (precio ≥ promedio) dice bajista. La tarjeta no la recalcula.
    const fondo = tarjetas({ ruedas: 760, media200: 100, dist_media200: 0, tendencia: 'bajista', rsi: 50 }).find(x => x.id === 'fondo')
    expect(fondo.veredicto).toBe('Bajista')
    expect(tendenciasDistintas({ dist_media200: 0, tendencia: 'bajista' }, { dist_media200: 0, tendencia: 'alcista' })).toBe(true)
  })

  it('con un servidor de antes (sin `tendencia`, mientras se publica) no dice «Faltan datos» (re-test P6, 29/10)', () => {
    // La web (Vercel) sale antes que el servidor (Railway) con el mismo push.
    const viejo = { ruedas: 760, media200: 100, dist_media200: 4, rsi: 50 }
    expect(tarjetas(viejo).find(x => x.id === 'fondo').veredicto).toBe('Alcista')
    expect(tarjetas({ ...viejo, dist_media200: -4 }).find(x => x.id === 'fondo').veredicto).toBe('Bajista')
    expect(tendenciasDistintas({ dist_media200: -8 }, { dist_media200: 24 })).toBe(true)
    // Con el servidor nuevo, lo que diga él (aunque sea «no hay»).
    expect(tarjetas({ ...viejo, tendencia: null }).find(x => x.id === 'fondo').veredicto).toBe('Faltan datos')
  })

  it('sin lectura no hay tarjetas', () => {
    expect(tarjetas(null)).toEqual([])
    expect(tarjetas({ ruedas: 0 })).toEqual([])
  })
})

describe('veredictoRsi', () => {
  it('dice quién viene ganando, con los cortes de 30 y 70', () => {
    expect(veredictoRsi(25)).toBe('Cayó muy rápido')
    expect(veredictoRsi(30)).toBe('Pierde impulso')
    expect(veredictoRsi(50)).toBe('Sin impulso claro')
    expect(veredictoRsi(70)).toBe('Gana impulso')
    expect(veredictoRsi(71)).toBe('Subió muy rápido')
  })

  it('cuenta cuándo volvió a superar 30 o bajó de 70', () => {
    expect(textoCruceRsi({ tipo: 'salio_de_abajo', hace: 3 }))
      .toBe('Hace 3 días de mercado volvió a superar 30: dejó de caer tan rápido.')
    expect(textoCruceRsi({ tipo: 'salio_de_arriba', hace: 0 }))
      .toBe('En el último día de mercado volvió a quedar debajo de 70: dejó de subir tan rápido.')
    expect(textoCruceRsi(null)).toBeNull()
  })
})

describe('lineaPromedio', () => {
  const pts = [{ c: 100 }, { c: 120 }]
  it('la distancia al precio es exactamente tu resultado', () => {
    // Ganás 20 %: tu precio en este gráfico es 120 / 1,2 = 100.
    expect(lineaPromedio(pts, 0.2)).toBeCloseTo(100, 10)
    expect(lineaPromedio(pts, -0.25)).toBeCloseTo(160, 10)
  })
  it('sin resultado (no tenés el activo) no hay línea', () => {
    expect(lineaPromedio(pts, null)).toBeNull()
    expect(lineaPromedio([], 0.1)).toBeNull()
    expect(lineaPromedio(pts, -1)).toBeNull()
  })
})

describe('marcas', () => {
  it('compras de los lotes y de las cerradas, ventas de las cerradas, sin cobros ni conversiones', () => {
    const lotes = [{ entry_date: '2026-03-02', quantity: 5 }, { is_cash: true, entry_date: '2026-01-01' }]
    const ops = [
      { op_type: 'Venta', entry_date: '2025-11-14', date: '2026-04-28', pnl_usd: -3 },
      { op_type: 'Dividendo', date: '2026-05-10', pnl_usd: 12 },
      { op_type: 'Conversión ARS→USD', date: '2026-06-01', pnl_usd: 0 },
    ]
    expect(marcas(lotes, ops)).toEqual([
      { fecha: '2025-11-14', tipo: 'compra' },
      { fecha: '2026-03-02', tipo: 'compra' },
      { fecha: '2026-04-28', tipo: 'venta' },
    ])
  })
})

describe('indiceDeFecha', () => {
  const pts = [{ d: '2026-10-16' }, { d: '2026-10-19' }, { d: '2026-10-20' }]
  it('un fin de semana cae en el viernes', () => {
    expect(indiceDeFecha(pts, '2026-10-18')).toBe(0)
    expect(indiceDeFecha(pts, '2026-10-20')).toBe(2)
    expect(indiceDeFecha(pts, '2026-10-01')).toBeNull()
  })
})

describe('recortar y tendenciasDistintas', () => {
  it('recorta las últimas ruedas', () => {
    expect(recortar([1, 2, 3, 4], 2)).toEqual([3, 4])
    expect(recortar([1, 2], 10)).toEqual([1, 2])
  })
  it('avisa cuando en pesos parece alcista y en dólares no', () => {
    expect(tendenciasDistintas({ dist_media200: -8, tendencia: 'bajista' }, { dist_media200: 24, tendencia: 'alcista' })).toBe(true)
    expect(tendenciasDistintas({ dist_media200: 3, tendencia: 'alcista' }, { dist_media200: 24, tendencia: 'alcista' })).toBe(false)
    expect(tendenciasDistintas(null, { dist_media200: 24, tendencia: 'alcista' })).toBe(false)
  })
})

describe('velas', () => {
  it('completa una vela rota con lo que hay, sin inventar mecha', async () => {
    const { velaCompleta } = await import('./tecnico')
    expect(velaCompleta({ o: 10, h: 12, l: 9, c: 11 }, 9.5)).toEqual({ o: 10, h: 12, l: 9, c: 11 })
    // Sin apertura ni máximo/mínimo: abre en el cierre anterior y la mecha es el cuerpo.
    expect(velaCompleta({ o: null, h: null, l: null, c: 11 }, 10)).toEqual({ o: 10, h: 11, l: 10, c: 11 })
    // Un máximo menor que el cierre (dato roto) se corrige al cierre.
    expect(velaCompleta({ o: 10, h: 10.5, l: 9, c: 11 }, null).h).toBe(11)
  })

  it('agrupa por semana: apertura del lunes, máximo y mínimo de la semana, cierre del viernes', async () => {
    const { velasSemanales } = await import('./tecnico')
    const dias = [
      { d: '2026-10-12', o: 10, h: 11, l: 9.5, c: 10.5, s200: 1, rsi: 40 },   // lunes
      { d: '2026-10-14', o: 10.5, h: 13, l: 10, c: 12, s200: 2, rsi: 50 },
      { d: '2026-10-16', o: 12, h: 12.5, l: 8, c: 9, s200: 3, rsi: 45 },       // viernes
      { d: '2026-10-19', o: 9, h: 10, l: 8.5, c: 9.8, s200: 4, rsi: 47 },      // otra semana
    ]
    const s = velasSemanales(dias)
    expect(s).toHaveLength(2)
    expect(s[0]).toMatchObject({ d: '2026-10-12', o: 10, h: 13, l: 8, c: 9, s200: 3, rsi: 45, semana: true })
    expect(s[1]).toMatchObject({ d: '2026-10-19', o: 9, c: 9.8 })
  })

  it('el volumen de la semana es la suma de sus días (un día sin dato no suma)', async () => {
    const { velasSemanales } = await import('./tecnico')
    const s = velasSemanales([
      { d: '2026-10-12', c: 10, v: 100 }, { d: '2026-10-13', c: 11, v: null }, { d: '2026-10-14', c: 12, v: 50 },
      { d: '2026-10-19', c: 9 },
    ])
    expect(s[0].v).toBe(150)
    expect(s[1].v).toBeNull()
  })
})

describe('zoom y arrastre', () => {
  it('la ruedita acerca dejando quieto el día bajo el mouse', async () => {
    const { zoomVentana } = await import('./tecnico')
    // Se ven las ruedas 252..503 y el mouse está en el medio (rueda 378).
    const v = zoomVentana({ n: 252, fin: 504, total: 504 }, 0.5, 0.5)
    expect(v).toEqual({ n: 126, fin: 441 })
    expect(v.fin - v.n + 0.5 * v.n).toBe(378)
  })
  it('no se pasa de los bordes ni baja de 20 ruedas', async () => {
    const { zoomVentana } = await import('./tecnico')
    // Lo más lejos: todos los días que hay más su aire a la derecha (504 + 25).
    expect(zoomVentana({ n: 500, fin: 504, total: 504 }, 1.5, 0.5)).toEqual({ n: 529, fin: 529 })
    expect(zoomVentana({ n: 529, fin: 529, total: 504 }, 1.5, 0.5)).toBeNull()
    expect(zoomVentana({ n: 21, fin: 504, total: 504 }, 0.1, 1)).toEqual({ n: 20, fin: 504 })
  })
  it('arrastrar a la derecha va para atrás en el tiempo; a la izquierda, hasta medio ancho de futuro', async () => {
    const { moverVentana } = await import('./tecnico')
    expect(moverVentana({ n: 100, fin: 504, total: 504 }, 0.25)).toEqual({ n: 100, fin: 479 })
    // Hacia el futuro (Nico, 23/10): se puede pasar del último día, hasta la mitad de lo que se ve.
    expect(moverVentana({ n: 100, fin: 504, total: 504 }, -0.25)).toEqual({ n: 100, fin: 529 })
    expect(moverVentana({ n: 100, fin: 554, total: 504 }, -0.25)).toBeNull()
    expect(moverVentana({ n: 100, fin: 110, total: 504 }, 0.5)).toEqual({ n: 100, fin: 100 })
  })
})

describe('aire a la derecha (el futuro)', () => {
  it('la ventana de entrada deja aire a la derecha: 5 % de lo que se ve, nunca menos de 3', async () => {
    const { ventanaInicial, margenDerecho } = await import('./tecnico')
    expect(margenDerecho(252)).toBe(13)
    expect(margenDerecho(20)).toBe(3)
    expect(ventanaInicial(252, 760)).toEqual({ n: 265, fin: 773 })
    expect(ventanaInicial(900, 760)).toEqual({ n: 798, fin: 798 })   // pocos datos: todos, más su aire
  })
})

describe('arreglos de la auditoría', () => {
  it('rangos por días corridos (una cripto también tiene 365 días en 1A)', async () => {
    const { puntosEnDias } = await import('./tecnico')
    const dias = Array.from({ length: 800 }, (_, i) => ({ d: new Date(Date.UTC(2024, 0, 1) + i * 86400000).toISOString().slice(0, 10) }))
    expect(puntosEnDias(dias, 365)).toBe(365)
    const habiles = dias.filter(p => ![0, 6].includes(new Date(p.d + 'T00:00:00Z').getUTCDay()))
    expect(puntosEnDias(habiles, 365)).toBeGreaterThan(255)
    expect(puntosEnDias(habiles, 365)).toBeLessThan(265)
  })
  it('sin el dato de hace un mes no dice hacia dónde va la media', () => {
    const t = tarjetas({ ruedas: 210, media200: 10, dist_media200: 5, tendencia: 'alcista', pendiente_media200: null })
    expect(t.find(x => x.id === 'fondo').texto).toBe('El precio está 5,0% arriba de su promedio de los últimos 200 días. '
      + 'Estar arriba de ese promedio es la referencia más usada para decir que la tendencia de largo plazo es alcista.')
  })
  it('en su máximo cuando cierra en el máximo de cierre', () => {
    const t = tarjetas({ ruedas: 400, dist_maximo_12m: 0, anio_completo: true })
    expect(t.find(x => x.id === 'maximo').veredicto).toBe('En su máximo')
  })
  it('la línea de tu precio se corrige por lo que se movió hoy', async () => {
    const { variacionDeHoy } = await import('./tecnico')
    // Ayer cerró 100 y hoy vale 110; ganás 10 %, así que pagaste 100. La línea
    // tiene que quedar en 100 (sin la corrección del día quedaba en 90,9).
    expect(lineaPromedio([{ c: 100 }], 0.1, variacionDeHoy(110, { cierre: 100 }))).toBeCloseTo(100, 10)
    expect(variacionDeHoy(null, { cierre: 100 })).toBe(0)
  })
  it('los cobros (cupón, renta, amortización) no son compras ni ventas', () => {
    expect(marcas([], [
      { op_type: 'Cupón', entry_date: '2026-01-01', date: '2026-02-01', pnl_usd: 3 },
      { op_type: 'Amortización', entry_date: '2026-01-01', date: '2026-03-01', pnl_usd: 0 },
    ])).toEqual([])
  })
})

describe('fuerza de la tendencia (ADX + Squeeze)', () => {
  const F = { ...L, adx: 31.4, di_mas: 30, di_menos: 12, adx_pendiente: 2.1, adx_cruce: null,
    squeeze: 4.2, squeeze_color: 'verde_fuerte', squeeze_activo: false }

  it('arriba de 23 con el Squeeze en verde: tendencia con fuerza, al alza', () => {
    const t = tarjetaFuerza(F)
    expect(t.veredicto).toBe('Tendencia firme')
    expect(t.tono).toBe('pos')
    expect(t.texto).toBe('El ADX está en 31, arriba de la línea de 23, y subiendo. '
      + 'El ADX mide cuánta fuerza tiene la tendencia, no para dónde va: arriba de 23 hay una tendencia con fuerza; abajo, se mueve sin una dirección clara (de forma lateral). '
      + 'La dirección la muestra el Squeeze (indica si el precio empuja al alza o a la baja), que está en verde: empuja al alza.')
    expect(t.cruce).toBeNull()
    expect(tarjetas(F).map(x => x.id)).toContain('fuerza')
  })

  it('el color lo pone el Squeeze; abajo de 23 no hay tendencia clara', () => {
    expect(tarjetaFuerza({ ...F, squeeze: -3, squeeze_color: 'rojo_apagado' }).tono).toBe('neg')
    expect(tarjetaFuerza({ ...F, squeeze: -3, squeeze_color: 'rojo_apagado' }).texto)
      .toContain('está en rojo: empuja a la baja, pero menos que el día anterior.')
    const sin = tarjetaFuerza({ ...F, adx: 17.2, adx_pendiente: -0.2 })
    expect(sin.veredicto).toBe('Sin tendencia clara')
    expect(sin.tono).toBe('neutro')
    expect(sin.texto).toMatch(/^El ADX está en 17, abajo de la línea de 23\. /)
    expect(tarjetaFuerza({ ...F, adx_pendiente: -1.5 }).veredicto).toBe('La tendencia se debilita')
    // «Apretado» sólo sin tendencia, y dicho como lectura, no como pronóstico.
    expect(tarjetaFuerza({ ...F, adx: 17, squeeze_activo: true }).texto)
      .toContain('en estas semanas se mueve en un rango más chico que de costumbre.')
    expect(tarjetaFuerza({ ...F, squeeze_activo: true }).texto).not.toContain('rango más chico')
  })

  it('cuando el ADX pasa 23 con el Squeeze del mismo lado, la frase destacada dice para dónde', () => {
    const t = tarjetaFuerza({ ...F, adx: 24.4, adx_cruce: { tipo: 'paso_arriba', hace: 1, squeeze: 1 } })
    expect(t.veredicto).toBe('La tendencia se fortalece')
    expect(t.cruce).toBe('Hace 1 día de mercado la fuerza de la tendencia (ADX) superó 23 con el Squeeze (indica si el precio empuja al alza o a la baja) en verde: '
      + 'el precio viene subiendo con fuerza.')
    expect(textoCruceAdx({ tipo: 'paso_arriba', hace: 0, squeeze: -1 }, -2))
      .toBe('En el último día de mercado la fuerza de la tendencia (ADX) superó 23 con el Squeeze (indica si el precio empuja al alza o a la baja) en rojo: el precio viene bajando con fuerza.')
    // El Squeeze cambió de lado desde el cruce: no se dice para dónde.
    expect(textoCruceAdx({ tipo: 'paso_arriba', hace: 4, squeeze: -1 }, 2))
      .toBe('Hace 4 días de mercado la fuerza de la tendencia (ADX) superó 23: la tendencia ganó fuerza.')
    expect(textoCruceAdx({ tipo: 'paso_abajo', hace: 2, squeeze: 1 }, 1)).toContain('bajó de 23')
    expect(textoCruceAdx(null, 1)).toBeNull()
  })

  it('con pocos datos lo dice en vez de inventar', () => {
    const t = tarjetaFuerza({ ruedas: 25, adx: null, squeeze: null })
    expect(t.veredicto).toBe('Faltan datos')
    expect(t.texto).toBe('Para calcularla hacen falta unos 28 días de mercado y este activo tiene 25.')
    expect(tarjetaFuerza(null)).toBeNull()
    expect(ADX_CLAVE).toBe(23)
  })

  it('nunca promete: ni «suele», ni «se viene», ni «comprá»', () => {
    // Medido (backtest 28/10, y «Tus señales»: 70 activos, 2 años): ni el RSI ni
    // el ADX anticiparon el precio mejor que el azar. Los textos describen lo que
    // ya pasó; ninguno dice qué «suele» venir.
    const rsi = tarjetas({ ruedas: 300, rsi: 75 }).find(c => c.id === 'rsi')
    const textos = [textoSqueeze('verde_fuerte'), textoSqueeze('rojo_fuerte'),
      ...['paso_arriba', 'paso_abajo'].flatMap(tipo => [-1, 1].map(sq => textoCruceAdx({ tipo, hace: 1, squeeze: sq }, sq))),
      tarjetaFuerza(F).texto, tarjetaFuerza({ ...F, adx: 17, squeeze_activo: true }).texto,
      rsi.texto, textoCruceRsi({ tipo: 'salio_de_abajo', hace: 1 }), textoCruceRsi({ tipo: 'salio_de_arriba', hace: 1 }),
      // Las Bollinger en todas sus posiciones y anchos: tocar una banda no anticipa nada.
      ...[-0.2, 0.1, 0.5, 0.9, 1.2, null].flatMap(bb_posicion => [0.5, 1, 2].map(bb_ancho_relativo =>
        tarjetaBandas({ ruedas: 300, bb_arriba: 110, bb_abajo: 90, bb_posicion, bb_ancho_relativo }).texto)),
      tarjetaBandas({ ruedas: 10, bb_arriba: null }).texto,
      textoRendPorMovimiento({ rend_12m: 32, mov_anual: 24, rend_por_movimiento: 1.33 }), textoRendPorMovimiento({ rend_12m: -22, mov_anual: 41, rend_por_movimiento: -0.54 }),
      ...[0.8, 2, 4].flatMap(mov_dia => [null, 1, 3].map(mov_dia_anio => tarjetaMovimiento({ ruedas: 300, mov_dia, mov_dia_anio, mov_mes: mov_dia * 4.6 }).texto))].join(' ')
    expect(textos).not.toMatch(/suele|se viene|comprá|vendé|va a subir|va a bajar|rebota|frena|antesala|arranque|esperad|potencial|oportunidad|anticipa\b/i)
  })

  it('las Bandas de Bollinger dicen dónde está el precio y cuánto se movió', () => {
    const B = { ruedas: 300, bb_arriba: 110, bb_abajo: 90, bb_ancho_relativo: 1 }
    const arriba = tarjetaBandas({ ...B, bb_posicion: 0.9 })
    expect(arriba.veredicto).toBe('Cerca de la banda superior')
    expect(arriba.texto).toContain('El precio está muy cerca de la banda superior: en la parte alta de su recorrido de esos 20 días.')
    expect(arriba.texto).not.toContain('angostas')
    expect(tarjetaBandas({ ...B, bb_posicion: 1.3 }).texto).toContain('Cerró por encima de la banda superior: más alto que casi todos los precios de esos 20 días.')
    expect(tarjetaBandas({ ...B, bb_posicion: -0.1 }).veredicto).toBe('Por debajo de las bandas')
    expect(tarjetaBandas({ ...B, bb_posicion: 0.15 }).veredicto).toBe('Cerca de la banda inferior')
    expect(tarjetaBandas({ ...B, bb_posicion: 0.5 }).veredicto).toBe('Entre las bandas')
    expect(tarjetaBandas({ ...B, bb_posicion: 0.5, bb_ancho_relativo: 0.5 }).texto).toContain('más angostas que lo habitual')
    expect(tarjetaBandas({ ...B, bb_posicion: 0.5, bb_ancho_relativo: 1.8 }).texto).toContain('más anchas que lo habitual')
    expect(arriba.tono).toBe('neutro')
    // Pocos días o un precio quieto: lo dice, no inventa.
    expect(tarjetaBandas({ ruedas: 12, bb_arriba: null }).texto).toContain('hacen falta 20 días de mercado y este activo tiene 12')
    expect(tarjetaBandas({ ...B, bb_posicion: null }).veredicto).toBe('Sin movimiento')
    expect(tarjetaBandas(null)).toBeNull()
  })

  it('cuánto se mueve: el tamaño del día normal, contra su último año', () => {
    const t = tarjetaMovimiento({ ruedas: 300, mov_dia: 3.49, mov_dia_anio: 2.1, mov_mes: 16.0 })
    expect(t.veredicto).toBe('Volatilidad alta')
    expect(t.texto).toBe('En los últimos 20 días de mercado, en un día típico subió o bajó alrededor de 3,5%. '
      + 'En un mes, eso equivale a unos 16%, para arriba o para abajo. Es más que en un día típico de su último año (2,1%). '
      + 'Mide cuánto se mueve el precio, no hacia dónde.')
    expect(t.tono).toBe('neutro')
    expect(tarjetaMovimiento({ ruedas: 300, mov_dia: 1.2, mov_dia_anio: 2 }).veredicto).toBe('Volatilidad baja')
    expect(tarjetaMovimiento({ ruedas: 300, mov_dia: 1.2, mov_dia_anio: 2 }).texto).toContain('Es menos que en un día típico')
    expect(tarjetaMovimiento({ ruedas: 300, mov_dia: 2, mov_dia_anio: 2.1 }).veredicto).toBe('Volatilidad media')
    expect(tarjetaMovimiento({ ruedas: 300, mov_dia: 2, mov_dia_anio: 2.1 }).texto).toContain('Es parecido')
    // Sin año medido no compara; con pocos días o precio quieto lo dice.
    expect(tarjetaMovimiento({ ruedas: 60, mov_dia: 2, mov_dia_anio: null }).texto).not.toContain('último año')
    expect(tarjetaMovimiento({ ruedas: 15, mov_dia: null }).texto).toContain('hacen falta 21 días de mercado y este activo tiene 15')
    expect(tarjetaMovimiento({ ruedas: 60, mov_dia: 0 }).veredicto).toBe('Sin movimiento')
    expect(tarjetas({ ruedas: 300, mov_dia: 2 }).map(x => x.id)).toContain('movimiento')
    // Ganancia por punto de movimiento, en pasado y con la aclaración.
    const con = tarjetaMovimiento({ ruedas: 760, mov_dia: 0.84, rend_12m: 32.07, mov_anual: 24.13, rend_por_movimiento: 1.329 })
    expect(con.cruce).toBe('En los últimos 12 meses subió 32,1%. Su volatilidad anual (cuánto oscila el precio en un año, para arriba o para abajo) es de unos 24%: 1,3 puntos de ganancia por cada punto de volatilidad. '
      + 'Es un dato del pasado: medido en 15 acciones, no anticipó cuál iba a rendir más después.')
    expect(textoRendPorMovimiento({ rend_12m: -22.2, mov_anual: 41.2, rend_por_movimiento: -0.539 }))
      .toContain('bajó 22,2%. Su volatilidad anual (cuánto oscila el precio en un año, para arriba o para abajo) es de unos 41%: 0,5 puntos de pérdida por cada punto de volatilidad')
    // Lo que redondea a cero va en palabras (auditoría 28/10).
    expect(textoRendPorMovimiento({ rend_12m: 0.9, mov_anual: 40, rend_por_movimiento: 0.0225 })).toContain('subió 0,9%')
    expect(textoRendPorMovimiento({ rend_12m: 0.9, mov_anual: 40, rend_por_movimiento: 0.0225 })).toContain('casi nada de ganancia para toda esa volatilidad')
    expect(textoRendPorMovimiento({ rend_12m: -0.03, mov_anual: 40, rend_por_movimiento: -0.00075 })).toContain('quedó casi en el mismo precio')
    expect(textoRendPorMovimiento({ rend_12m: -0.03, mov_anual: 40, rend_por_movimiento: -0.00075 })).not.toMatch(/0,0/)
    expect(tarjetaMovimiento({ ruedas: 300, mov_dia: 0.04, mov_mes: 0.2 }).veredicto).toBe('Sin movimiento')
    expect(tarjetaMovimiento({ ruedas: 300, mov_dia: 0.9, mov_mes: 4.2 }).texto).toContain('unos 4,2%, para arriba o para abajo')
    // Un servidor de antes (sin las claves nuevas): sin tarjeta, no «faltan datos».
    expect(tarjetaMovimiento({ ruedas: 760, rsi: 50 })).toBeNull()
    expect(tarjetaBandas({ ruedas: 760, rsi: 50 })).toBeNull()
    expect(textoRendPorMovimiento({ rend_12m: 5, mov_anual: 20, rend_por_movimiento: null })).toBeNull()
    expect(tarjetaMovimiento({ ruedas: 300, mov_dia: 2 }).cruce).toBeNull()
  })

  it('las velas semanales llevan las bandas del último día', () => {
    const pts = ['2026-10-12', '2026-10-13'].map((d, i) => ({ d, c: 10 + i, bb_arriba: 12 + i, bb_abajo: 8 + i }))
    const [semana] = velasSemanales(pts)
    expect([semana.bb_arriba, semana.bb_abajo]).toEqual([13, 9])
  })

  it('las velas semanales llevan el ADX y el Squeeze del último día', () => {
    const pts = ['2026-10-12', '2026-10-13', '2026-10-14'].map((d, i) => ({ d, c: 10 + i, adx: 20 + i, squeeze: i - 1, squeeze_color: `c${i}` }))
    const [semana] = velasSemanales(pts)
    expect([semana.adx, semana.squeeze]).toEqual([22, 1])
  })

  it('el color de cada semana se compara con la semana anterior, no con el día anterior', () => {
    // Semana 1 termina en 5; semana 2 termina en 3 (el viernes subió contra el
    // jueves, pero la semana quedó abajo de la anterior): verde apagado.
    const pts = [['2026-10-09', 5], ['2026-10-15', 1], ['2026-10-16', 3]].map(([d, sq]) => ({ d, c: 10, squeeze: sq, squeeze_color: 'verde_fuerte' }))
    expect(velasSemanales(pts).map(s => s.squeeze_color)).toEqual(['verde_fuerte', 'verde_apagado'])
    expect([colorSqueeze(-2, -1), colorSqueeze(-1, -2), colorSqueeze(0, 0), colorSqueeze(null, 1)])
      .toEqual(['rojo_fuerte', 'rojo_apagado', 'rojo_apagado', null])
  })

  it('arreglos de la auditoría: cruce con el ADX cayendo, Squeeze en cero o todavía sin datos, precio quieto', () => {
    // Pasó 23 hace 8 días pero ya viene cayendo: afloja, no «toma fuerza».
    const cae = tarjetaFuerza({ ...F, adx: 28.9, adx_pendiente: -1.75, adx_cruce: { tipo: 'paso_arriba', hace: 8, squeeze: 1 } })
    expect(cae.veredicto).toBe('La tendencia se debilita')
    // …y la frase destacada no le lleva la contraria («arranque de una suba con fuerza»).
    expect(cae.cruce).toBe('Hace 8 días de mercado la fuerza de la tendencia (ADX) superó 23; en los últimos 3 días de mercado viene bajando.')
    expect(cae.tono).toBe('neutro')
    // Squeeze exactamente en 0: no dice «a la baja».
    const cero = tarjetaFuerza({ ...F, squeeze: 0, squeeze_color: 'rojo_apagado' })
    expect(cero.tono).toBe('neutro')
    expect(cero.texto).toContain('El Squeeze (indica si el precio empuja al alza o a la baja) está en cero: no empuja ni al alza ni a la baja.')
    expect(cero.texto).not.toContain('empuja a la baja')
    // 33 días: ya hay ADX (el panel lo dibuja) pero no Squeeze. La tarjeta lee el ADX.
    const sinSq = tarjetaFuerza({ ruedas: 33, adx: 26, adx_pendiente: 1, adx_cruce: null, squeeze: null, squeeze_activo: true })
    expect(sinSq.veredicto).toBe('Tendencia firme')
    expect(sinSq.tono).toBe('neutro')
    expect(sinSq.texto).toContain('hacen falta unos 39 días de mercado y este activo tiene 33.')
    expect(sinSq.texto).not.toContain('rango más chico')
    // 300 días con el precio quieto: el servidor no da ADX. No «faltan datos».
    const quieto = tarjetaFuerza({ ruedas: 300, adx: null, squeeze: 0 })
    expect(quieto.veredicto).toBe('Sin tendencia clara')
    expect(quieto.texto).not.toContain('hacen falta')
    // Ningún veredicto de esta tarjeta repite uno del RSI.
    const delRsi = [10, 40, 50, 60, 80].map(veredictoRsi)
    for (const v of [cae, cero, sinSq, quieto, tarjetaFuerza({ ...F, adx_cruce: { tipo: 'paso_arriba', hace: 1, squeeze: 1 } })].map(t => t.veredicto)) {
      expect(delRsi).not.toContain(v)
    }
  })

  it('segunda auditoría: el redondeo no contradice la línea de 23, y los cortes exactos', () => {
    // 22,8 se mostraba «23» al lado de «abajo de la línea de 23».
    expect(fmtAdx(22.8)).toBe('22,8')
    expect(fmtAdx(22.97)).toBe('22,9')
    expect(fmtAdx(22.4)).toBe('22')
    expect(fmtAdx(23)).toBe('23,0')
    expect(fmtAdx(23.4)).toBe('23,4')
    expect(fmtAdx(23.6)).toBe('24')
    expect(fmtAdx(null)).toBe('—')
    expect(tarjetaFuerza({ ...F, adx: 22.8 }).texto).toMatch(/^El ADX está en 22,8, abajo de la línea de 23/)
    // 23 justo ya cuenta como arriba (la misma regla que el cruce del servidor).
    const justo = tarjetaFuerza({ ...F, adx: 23, adx_pendiente: 0 })
    expect(justo.veredicto).toBe('Tendencia firme')
    expect(justo.texto).toMatch(/^El ADX está en 23,0, justo en la línea de 23\. /)
    expect(tarjetaFuerza({ ...F, adx: 23.2, adx_pendiente: 0 }).texto).toMatch(/^El ADX está en 23,2, arriba de la línea de 23\. /)
    // Un cambio chico (menos de medio punto en 3 días) no es «subiendo» ni «bajando».
    expect(tarjetaFuerza({ ...F, adx_pendiente: 0.3 }).texto).toMatch(/^El ADX está en 31, arriba de la línea de 23\. /)
    expect(tarjetaFuerza({ ...F, adx_pendiente: -0.3 }).veredicto).toBe('Tendencia firme')
  })

  it('la primera semana del zoom compara su Squeeze con la semana anterior, no con 0', () => {
    const previos = [{ d: '2026-10-02', squeeze: 9 }, { d: '2026-10-05', squeeze: 7 }]
    const pts = [{ d: '2026-10-08', c: 10, squeeze: 5 }, { d: '2026-10-09', c: 10, squeeze: 6 }]
    // Semana del 5/10: el 8 y el 9 (visibles) y el 5 (fuera del zoom). La de
    // antes es la del 2/10 (squeeze 9): 6 < 9 → verde apagado.
    expect(velasSemanales(pts, previos)[0].squeeze_color).toBe('verde_apagado')
    expect(velasSemanales(pts)[0].squeeze_color).toBe('verde_fuerte')
  })

  it('tercera auditoría: el cruce de hoy no «afloja», sin tendencia no hay «dirección», y textos más cortos', () => {
    // Cruzó hoy: el ADX subió hoy aunque esté más bajo que hace 3 días (26 → 23,1).
    const hoy = tarjetaFuerza({ ...F, adx: 23.1, adx_pendiente: -1.6, adx_cruce: { tipo: 'paso_arriba', hace: 0, squeeze: 1 } })
    expect(hoy.veredicto).toBe('La tendencia se fortalece')
    expect(hoy.texto).toMatch(/^El ADX está en 23,1, arriba de la línea de 23\. /)
    expect(hoy.cruce).not.toContain('bajando')
    // Hace 3 días o más, los 3 días que mira son posteriores al cruce: ahí sí afloja.
    expect(tarjetaFuerza({ ...F, adx_pendiente: -1.6, adx_cruce: { tipo: 'paso_arriba', hace: 3, squeeze: 1 } }).veredicto).toBe('La tendencia se debilita')
    // Sin tendencia, el Squeeze es el empuje de estos días, no «la dirección».
    const sin = tarjetaFuerza({ ...F, adx: 15 })
    expect(sin.texto).toContain('Por ahora el Squeeze (indica si el precio empuja al alza o a la baja) está en verde: empuja al alza, pero sin fuerza suficiente para hablar de una tendencia.')
    // Bajó de 23 hoy: «y subiendo» (por los 3 días de antes del cruce) no va.
    expect(tarjetaFuerza({ ...F, adx: 22.1, adx_pendiente: 1, adx_cruce: { tipo: 'paso_abajo', hace: 0, squeeze: 1 } }).texto)
      .toMatch(/^El ADX está en 22, abajo de la línea de 23\. /)
    expect(sin.texto).not.toContain('La dirección la muestra')
    // Ningún veredicto dice «fuerza» (el RSI la usa para otra cosa).
    for (const t of [hoy, sin, tarjetaFuerza(F), tarjetaFuerza({ ...F, adx_pendiente: -2 })]) expect(t.veredicto).not.toMatch(/fuerza/i)
    // La más larga posible (cruce para abajo + apretado) no repite «lateral».
    const larga = tarjetaFuerza({ ...F, adx: 21, adx_pendiente: -2, squeeze_activo: true, adx_cruce: { tipo: 'paso_abajo', hace: 2, squeeze: -1 } })
    expect((larga.texto + larga.cruce).match(/lateral/g)).toHaveLength(1)
    expect((larga.texto + larga.cruce).length).toBeLessThan(560)
  })
})

// D9 (auditoría D, 29/10): «Por ahora el Squeeze está en verde…» y un panel
// titulado «Squeeze»: nunca decía qué es. Regla: cada término técnico con su
// explicación en la misma oración. Se recorren todos los estados de la tarjeta.
describe('D9 · el Squeeze dice qué es en la misma oración', () => {
  const oraciones = (t) => (t || '').split(/(?<=[.:])\s+(?=[A-ZÁÉÍÓÚ])/)
  it('en la tarjeta «Fuerza de la tendencia» y en el cruce del ADX', () => {
    const textos = []
    for (const adx of [12, 30]) {
      for (const squeeze of [null, -2, 0, 2]) {
        for (const squeeze_color of ['verde_fuerte', 'verde_apagado', 'rojo_fuerte', 'rojo_apagado']) {
          for (const adx_cruce of [null, { tipo: 'paso_arriba', hace: 1, squeeze: squeeze > 0 ? 1 : -1 }]) {
            const t = tarjetaFuerza({ ruedas: 300, adx, squeeze, squeeze_color, adx_pendiente: 0, adx_cruce })
            textos.push(t.texto, t.cruce)
          }
        }
      }
    }
    const conSqueeze = textos.flatMap(oraciones).filter(o => /Squeeze/.test(o))
    expect(conSqueeze.length).toBeGreaterThan(5)
    for (const o of conSqueeze) expect(o, o).toMatch(/si (el precio )?(viene )?empuja(ndo)? al alza o a la baja/)
  })
})

// La vela de HOY (useVelaDeHoy): va sólo al dibujo, en el primer lugar vacío
// de la derecha; las cuentas de la pantalla siguen con las guardadas.
describe('sumarVelaDeHoy', () => {
  // Lunes 26/10 a jueves 29/10 guardados; hoy es el viernes 30.
  const dias = ['2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29']
    .map((d, i) => ({ d, o: 100 + i, h: 102 + i, l: 99 + i, c: 101 + i, v: 10, s50: 95, s200: 90, rsi: 55 }))
  // La forma que arma useVelaDeHoy.
  const hoy = { d: '2026-10-30', o: 104, h: 110, l: 103, c: 108, v: 4, vivo: true, hoy: true, enCurso: true,
    actualizada: '2026-10-30T17:32:05Z', demora: 20 }
  const vivas = (...velas) => ({ velas, base: '2026-10-29', enRueda: true })
  const base = { puntos: dias, huecos: 3, vivas: vivas(hoy), ultimaGuardada: '2026-10-29', diarios: dias, alBorde: true }

  it('diarias: la agrega al final y le saca un lugar al aire (el ancho no cambia)', () => {
    const r = sumarVelaDeHoy(base)
    expect(r.puntos).toHaveLength(5)
    expect(r.puntos[4]).toBe(hoy)
    expect(r.huecos).toBe(2)
    expect(r.puntos.length + r.huecos).toBe(dias.length + 3)
    expect(dias).toHaveLength(4)                       // lo guardado no se toca
  })

  it('un día cerrado sin guardar va antes que el de hoy, cada uno en su lugar', () => {
    // La cripto entre las 21 y la noche: el 30 (UTC) cerró y todavía no se guardó.
    const viernes = { ...hoy, d: '2026-10-30', hoy: false, enCurso: false }
    const sabado = { ...hoy, d: '2026-10-31' }
    const r = sumarVelaDeHoy({ ...base, vivas: vivas(viernes, sabado) })
    expect(r.puntos.map(p => p.d).slice(-3)).toEqual(['2026-10-29', '2026-10-30', '2026-10-31'])
    expect(r.huecos).toBe(1)
  })

  it('si no siguen a lo guardado que tiene la pantalla (abierta de un día para el otro), no se dibujan', () => {
    expect(sumarVelaDeHoy({ ...base, vivas: { ...vivas(hoy), base: '2026-10-30' } }).puntos).toBe(dias)
  })

  it('si vienen en otra cuenta que la serie (otro dólar u otra escala), no se dibujan', () => {
    // La ficha abierta mientras se publicaba el cambio del dólar: la serie de la
    // pantalla con el MEP, la vela de hoy con el contado con liqui. Pegada,
    // «subía» 4 % un día en que el papel bajó (auditoría 06/11, H3 de la pantalla).
    const serie = { convertida: 'mep', escala: 20 }
    const con = (cuenta) => sumarVelaDeHoy({ ...base, vivas: { ...vivas(hoy), cuenta }, cuenta: serie }).puntos
    expect(con({ convertida: 'ccl', escala: 20 })).toBe(dias)          // otro dólar
    expect(con({ convertida: 'mep', escala: 120 })).toBe(dias)         // otra escala (la noche borró la serie vieja)
    expect(con({ convertida: null, escala: null })).toBe(dias)         // la de BYMA sobre un estimado
    expect(con({ convertida: 'mep', escala: 20 })).toHaveLength(5)     // la misma: se dibuja
    expect(con(undefined)).toHaveLength(5)                             // un servidor de antes no dice la suya
  })

  it('sin lugar para todas a la vista (mirando el pasado), no se dibujan', () => {
    expect(sumarVelaDeHoy({ ...base, huecos: 0 })).toEqual({ puntos: dias, huecos: 0 })
    const viernes = { ...hoy, hoy: false }
    expect(sumarVelaDeHoy({ ...base, huecos: 1, vivas: vivas(viernes, { ...hoy, d: '2026-10-31' }) }).puntos).toBe(dias)
  })

  it('sin velas, sin precio o con una fecha ya guardada: igual que antes', () => {
    expect(sumarVelaDeHoy({ ...base, vivas: null }).puntos).toBe(dias)
    expect(sumarVelaDeHoy({ ...base, vivas: vivas({ ...hoy, c: 0 }) }).puntos).toBe(dias)
    expect(sumarVelaDeHoy({ ...base, vivas: vivas({ ...hoy, d: '2026-10-29' }) }).puntos).toBe(dias)
  })

  it('semanales: se suma a la semana en curso con las medias del último día guardado y lo de la de hoy', () => {
    const semanas = velasSemanales(dias)
    const r = sumarVelaDeHoy({ ...base, puntos: semanas, huecos: 1, semanales: true })
    expect(r.puntos).toHaveLength(1)
    expect(r.huecos).toBe(1)
    const s = r.puntos[0]
    expect([s.o, s.h, s.l, s.c, s.v]).toEqual([100, 110, 99, 108, 44])
    expect([s.s50, s.s200, s.rsi]).toEqual([95, 90, 55])
    // Lo de la vela de hoy pasa a la semana: sin esto, en BYMA el pie perdía la demora.
    expect(s).toMatchObject({ hoy: true, enCurso: true, demora: 20, actualizada: hoy.actualizada, hasta: '2026-10-30' })
    expect(s.vivo).toBeUndefined()                     // la semana tiene sus indicadores
    expect(textoVelaDeHoy(s, true)).toMatch(/20 minutos de demora/)
  })

  it('semanales: un lunes abre una semana nueva si hay lugar; si no, no se suma', () => {
    const lunes = { ...hoy, d: '2026-11-02' }
    const semanas = velasSemanales(dias)
    const r = sumarVelaDeHoy({ ...base, vivas: vivas(lunes), puntos: semanas, huecos: 1, semanales: true })
    expect(r.puntos).toHaveLength(2)
    expect(r.puntos[1]).toMatchObject({ d: '2026-11-02', c: 108, hoy: true, semana: true, vivo: true })
    expect(r.huecos).toBe(0)
    // Sin aire a la derecha, abrir una semana angostaría todas las velas.
    expect(sumarVelaDeHoy({ ...base, vivas: vivas(lunes), puntos: semanas, huecos: 0, semanales: true }).puntos).toBe(semanas)
  })

  it('semanales: si el último día guardado no se ve, no se suma', () => {
    const semanas = velasSemanales(dias)
    expect(sumarVelaDeHoy({ ...base, puntos: semanas, semanales: true, alBorde: false }).puntos).toBe(semanas)
  })

  it('cada semana sabe su último día (`hasta`): el de su cierre, no su lunes', () => {
    expect(velasSemanales(dias)[0]).toMatchObject({ d: '2026-10-26', hasta: '2026-10-29' })
  })
})

describe('textoVelaDeHoy', () => {
  it('con la rueda abierta dice de qué hora es el precio (hora argentina)', () => {
    expect(textoVelaDeHoy({ hoy: true, enCurso: true, actualizada: '2026-10-30T17:32:05Z' }))
      .toBe('La última vela es la de hoy, en curso (precio de las 14:32): se actualiza sola cada minuto.')
    expect(textoVelaDeHoy({ hoy: true, enCurso: true, actualizada: '2026-10-30T17:32:05Z' }, true))
      .toMatch(/^La última vela incluye hoy, en curso/)
  })
  it('en BYMA no dice una hora: dice la demora de sus precios', () => {
    expect(textoVelaDeHoy({ hoy: true, enCurso: true, actualizada: '2026-10-30T15:07:28Z', demora: 20 }))
      .toBe('La última vela es la de hoy, en curso: se actualiza sola cada minuto, pero los precios de esta bolsa llegan con unos 20 minutos de demora.')
  })
  it('cerrada la rueda, dice que se guarda a la noche; sin vela de hoy, nada', () => {
    expect(textoVelaDeHoy({ hoy: true, enCurso: false })).toBe('La última vela es la de hoy: la rueda cerró y se guarda esta noche.')
    expect(textoVelaDeHoy({ d: '2026-10-29', c: 1 })).toBe('')
  })
})

describe('notaDeLaMoneda: de dónde sale el precio del gráfico', () => {
  it('un CEDEAR estimado en pesos dice que es un estimado y cómo se hizo (Nico, 06/11)', async () => {
    const { notaDeLaMoneda } = await import('./tecnico')
    // Sin su serie en pesos, el servidor manda la acción de Nueva York × el
    // contado con liqui de cada día ÷ `escala`. Antes no dividía y la nota decía
    // sólo «pasado a pesos»: Apple ×20.
    const nota = notaDeLaMoneda('ccl', 'ars', 20)
    expect(nota).toBe('Precio estimado del CEDEAR: la acción de Nueva York pasada a pesos con el dólar contado con '
      + 'liqui (CCL) de cada día y dividida por los CEDEARs que hacen una acción. '
      + 'Puede quedar alrededor de 1 % arriba o abajo de su precio en la Bolsa.')
  })
  it('con el MEP (una base que todavía no tiene el contado con liqui) lo dice y avisa que queda más lejos', async () => {
    const { notaDeLaMoneda } = await import('./tecnico')
    const nota = notaDeLaMoneda('mep', 'ars', 20)
    expect(nota).toContain('pasada a pesos con el MEP de cada día')
    expect(nota).toContain('unos pocos % lejos de su precio en la Bolsa')
    expect(nota).not.toContain('contado con liqui')
  })
  it('con un CEDEAR que vale varias acciones (ABEV: tres) dice «multiplicada», no «dividida»', async () => {
    const { notaDeLaMoneda } = await import('./tecnico')
    expect(notaDeLaMoneda('ccl', 'ars', 1 / 3)).toContain('multiplicada por las acciones que hay en un CEDEAR')
    expect(notaDeLaMoneda('ccl', 'ars', 1 / 3)).not.toContain('dividida')
    // Y con un CEDEAR que vale una acción (PBR, ITUB…) también es un estimado.
    for (const escala of [1 / 3, 1, 20]) expect(notaDeLaMoneda('ccl', 'ars', escala)).toMatch(/^Precio estimado del CEDEAR/)
  })
  it('sin escala conocida, la ficha dice qué falta (no que «no tiene precio en pesos»)', async () => {
    const { sinPrecioEnPesos } = await import('./tecnico')
    expect(sinPrecioEnPesos('sin_escala')).toMatch(/^En pesos no podemos estimar el precio de este CEDEAR/)
    expect(sinPrecioEnPesos(undefined)).toBe('Este activo no tiene precio en pesos.')
  })
  it('lo demás, como antes: una acción de afuera o una cripto en pesos, una argentina en dólares', async () => {
    const { notaDeLaMoneda } = await import('./tecnico')
    expect(notaDeLaMoneda('mep', 'ars')).toBe('El precio en dólares de cada día está pasado a pesos con el MEP de ese día.')
    expect(notaDeLaMoneda('mep', 'usd')).toBe('El precio en pesos de cada día está pasado a dólares con el MEP de ese día.')
    // Un CEDEAR sin escala conocida (Comparar, alertas): la acción de afuera con
    // el dólar de los CEDEARs, sin decir «estimado».
    expect(notaDeLaMoneda('ccl', 'ars')).toBe('El precio en dólares de cada día está pasado a pesos con el dólar contado con liqui (CCL) de ese día.')
    expect(notaDeLaMoneda(null, 'ars', 20)).toBe('')
    expect(notaDeLaMoneda(null, 'usd')).toBe('')
    expect(notaDeLaMoneda('otro', 'ars', 20)).toBe('')
  })
})

describe('haciaDondeVa: el color del cartel del último precio (Nico, 02/11)', () => {
  it('con velas, contra la apertura de la vela actual (vela verde, cartel verde)', async () => {
    const { haciaDondeVa } = await import('./tecnico')
    // Abrió en 100 y va en 98, pero el cierre anterior fue 95: la vela es roja → rojo.
    expect(haciaDondeVa([{ c: 95 }, { o: 100, c: 98 }], true)).toBe(-1)
    expect(haciaDondeVa([{ c: 105 }, { o: 100, c: 102 }], true)).toBe(1)
    expect(haciaDondeVa([{ c: 99 }, { o: 100, c: 100 }], true)).toBe(0)
    // Sin apertura (una vela sin datos sanos), contra el cierre anterior.
    expect(haciaDondeVa([{ c: 95 }, { c: 98 }], true)).toBe(1)
  })
  it('en la línea, contra el cierre anterior', async () => {
    const { haciaDondeVa } = await import('./tecnico')
    expect(haciaDondeVa([{ c: 95 }, { o: 100, c: 98 }], false)).toBe(1)
    expect(haciaDondeVa([], false)).toBe(0)
  })
})
