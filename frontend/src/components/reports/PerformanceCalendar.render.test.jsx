import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

// La vista (Pesos/Dólares) la decide el selector global: cada test arma la suya.
const vista = { currency: 'ARS' }
vi.mock('../../contexts/CurrencyContext', async (original) => ({
  ...(await original()),
  useCurrency: () => ({ currency: vista.currency, tcValuacion: 1500 }),
}))
// El dólar de cada fecha: mayo (y antes) 1.000, junio 1.200, hoy 1.500. Con el mismo dólar en todos
// lados, usar el equivocado pasaría igual.
vi.mock('../../hooks/useFxHistory', async (original) => ({
  ...(await original()),
  useFxHistory: () => ({ getRateForDate: (iso) => (String(iso) < '2024-06' ? 1000 : 1200), fxKey: 'k' }),
  useDolarMensual: () => ({ dolarMes: {} }),
}))
vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn() } }))

import PerformanceCalendar, { MetricasDelAno, BarrasDelAnio } from './PerformanceCalendar.jsx'
import { crearPesosDelPeriodo } from '../../utils/periodoEnPesos'
import { fmtConvertedRaw } from '../../contexts/CurrencyContext'

// La fila de métricas del año, en la moneda en que se mira (la misma `pesos` que arma usePesosDelPeriodo).
function pesosEn(moneda, tcEnFecha = () => 1000) {
  const p = crearPesosDelPeriodo({ moneda, tcHoy: 1500, tcEnFecha, dolarMes: {}, monthly: [], brokers: [] })
  return { ...p, fmt: (v, opts) => fmtConvertedRaw(v, p.moneda, opts) }
}
const fila = (pesos, resumen, months = []) => renderToStaticMarkup(
  <MetricasDelAno resumen={{ year: 2024, is_current: false, deposits: 0, withdrawals: 0, trades_count: 0, ...resumen }}
                  months={months} pesos={pesos} ranking={null} />,
)
// El Dato «P&L realizado» ya con su color: busca el span del valor justo después del rótulo.
const colorDelRealizado = (html) => (html.match(/P&amp;L realizado<\/span><span class="[^"]*?(text-rendi-pos|text-rendi-neg)/) || [])[1]

describe('Reportes · fila del año · P&L realizado', () => {
  // 100 u. compradas a $4.500 con el dólar a 1.500 y vendidas a $4.400 con el dólar a 1.000:
  // +US$ 140 en dólares y −$10.000 en pesos (el peso se apreció).
  const resumen = { realized_pnl: 140, realized_ars: -10000, realized_ars_cubre_usd: 140, realized_ars_valuado: false }

  it('en Pesos el color es el del número que se ve (rojo: −$10.000), no el de los dólares', () => {
    const html = fila(pesosEn('ARS'), resumen)
    expect(html).toContain('10.000')
    expect(colorDelRealizado(html)).toBe('text-rendi-neg')
  })
  it('en Dólares es el de siempre (verde: +US$ 140)', () => {
    expect(colorDelRealizado(fila(pesosEn('USD'), resumen))).toBe('text-rendi-pos')
  })
  it('lo convertido se dice en la fila del año', () => {
    // US$ 140 de la venta + US$ 40 de dividendos en dólares: US$ 40 se convierten
    const html = fila(pesosEn('ARS'), { ...resumen, realized_pnl: 180 })
    expect(html).toMatch(/incluye US\$ 40 convertidos/)
  })
  it('en Dólares no hay nada que avisar', () => {
    expect(fila(pesosEn('USD'), { ...resumen, realized_pnl: 180 })).not.toMatch(/convertidos/)
  })
  it('si el realizado en dólares da cero pero en pesos no, la fila aparece', () => {
    const marzo = { period_type: 'month', period_key: '2024-03', period_start: '2024-03-01', period_end: '2024-03-31',
      is_current: false, metrics: { realized_pnl: 0, realized_ars: 5000, realized_ars_cubre_usd: 0 } }
    const html = fila(pesosEn('ARS'), { realized_pnl: 0, realized_ars: 5000, realized_ars_cubre_usd: 0 }, [marzo])
    expect(html).toContain('P&amp;L realizado')
    expect(colorDelRealizado(html)).toBe('text-rendi-pos')
  })
})


// ─── La tarjeta «P&L Realizado · 12M», la fila del año por mes y el globo de una barra ───────────
const mes = (clave, metrics) => ({
  period_type: 'month', period_key: clave, period_label: clave, period_start: `${clave}-01`,
  period_end: `${clave}-28`, is_current: false, is_relevant: true,
  metrics: { delta_pct: 1, delta_usd: 0, unrealized_pnl: 0, trades_count: 1, basis_incomparable: false,
             realized_ars_valuado: false, ...metrics },
})
const texto = (h) => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
const calendario = (currency, months, years = []) => {
  vista.currency = currency
  return renderToStaticMarkup(
    <MemoryRouter><PerformanceCalendar yearGroups={[{ year: 2024, months }]} years={years} /></MemoryRouter>)
}
// mayo: GGAL +$240.000 (US$ 10); junio: otra venta +$30.000 (US$ 5) y un dividendo de US$ 20 en dólares
const mayo = mes('2024-05', { realized_pnl: 10, realized_ars: 240000, realized_ars_cubre_usd: 10 })
const junio = mes('2024-06', { realized_pnl: 25, realized_ars: 30000, realized_ars_cubre_usd: 5 })

describe('Reportes · «P&L Realizado · 12M»', () => {
  const celda = (h) => texto(h.slice(h.indexOf('P&amp;L Realizado'), h.indexOf('Meses positivos')))
  it('en Pesos suma los pesos de verdad de las ventas (no los dólares × el dólar de hoy)', () => {
    const t = celda(calendario('ARS', [mayo, junio]))
    // 240.000 + 30.000 + el dividendo (US$ 20) al dólar de junio (1.200) = 294.000
    expect(t).toContain('294.000')
    expect(t).not.toContain('22.500')   // US$ 15 × 1.500
    expect(t).not.toContain('37.500')   // US$ 25 × 1.500
  })
  it('lo convertido se dice, con su cantidad y a qué dólar', () => {
    const t = celda(calendario('ARS', [mayo, junio]))
    expect(t).toContain('en parte convertido')
    expect(t).toContain('incluye US$ 20 convertidos al dólar de cada mes')
  })
  it('sin resto convertido no hay aviso', () => {
    const t = celda(calendario('ARS', [mayo, mes('2024-06', { realized_pnl: 5, realized_ars: 30000, realized_ars_cubre_usd: 5 })]))
    expect(t).not.toContain('convertido')
  })
  it('el color es el del número en pesos: pérdida en dólares con ganancia en pesos va en verde', () => {
    const h = calendario('ARS', [mes('2024-06', { realized_pnl: -130, realized_ars: 30000, realized_ars_cubre_usd: -130 })])
    const tramo = h.slice(h.indexOf('P&amp;L Realizado'), h.indexOf('Meses positivos'))
    expect(tramo).toContain('text-rendi-pos')
    expect(tramo).not.toContain('text-rendi-neg')
  })
  it('en Dólares, los dólares y ningún aviso', () => {
    const t = celda(calendario('USD', [mayo, junio]))
    expect(t).toMatch(/US\$\s?35\b/)
    expect(t).not.toContain('convertido')
  })
})

describe('Reportes · fila del año · el realizado se arma mes por mes', () => {
  const p = (moneda) => {
    const x = crearPesosDelPeriodo({ moneda, tcHoy: 1500, tcEnFecha: (iso) => (String(iso) < '2024-06' ? 1000 : 1200),
      dolarMes: {}, monthly: [], brokers: [] })
    return { ...x, fmt: (v, opts) => fmtConvertedRaw(v, x.moneda, opts) }
  }
  // mayo: US$ 30 de los cuales US$ 10 son la venta (240.000) y US$ 20 un dividendo en dólares;
  // junio: US$ 10 de una venta en dólares (valuada). La suma de los meses coincide con la del año.
  const maySuma = mes('2024-05', { realized_pnl: 30, realized_ars: 240000, realized_ars_cubre_usd: 10 })
  const junValuada = mes('2024-06', { realized_pnl: 10, realized_ars: 100000, realized_ars_cubre_usd: 10, realized_ars_valuado: true })
  const resumen = { realized_pnl: 40, realized_ars: 340000, realized_ars_cubre_usd: 20, realized_ars_valuado: true }

  it('cada resto a SU dólar: 340.000 + los US$ 20 × 1.000 de mayo', () => {
    const t = texto(fila(p('ARS'), resumen, [maySuma, junValuada]))
    expect(t).toContain('360.000')
  })
  it('dice cuánto se convirtió, a qué dólar, y que hubo ventas valuadas', () => {
    const t = texto(fila(p('ARS'), resumen, [maySuma, junValuada]))
    expect(t).toContain('incluye US$ 20 convertidos al dólar de cada mes')
    expect(t).toContain('ventas o compras en dólares valuadas')
  })
  it('si los meses no suman lo que dice el resumen del año, vale el año entero', () => {
    const t = texto(fila(p('ARS'), { ...resumen, realized_pnl: 99 }, [maySuma, junValuada]))
    expect(t).not.toContain('incluye US$ 20 convertidos al dólar de cada mes')
  })
})

describe('Reportes · el globo de una barra del año', () => {
  const pesosDe = (moneda) => {
    const x = crearPesosDelPeriodo({ moneda, tcHoy: 1500, tcEnFecha: (iso) => (String(iso) < '2024-06' ? 1000 : 1200),
      dolarMes: {}, monthly: [], brokers: [] })
    return { ...x, fmt: (v, opts) => fmtConvertedRaw(v, x.moneda, opts) }
  }
  // Junio: la GGAL que ya estaba (240.000 exactos, −US$ 440 en dólares) + un dividendo de US$ 20;
  // la cartera vale US$ 450 al arrancar (dólar de mayo 1.000) y US$ 480 al cerrar (dólar 1.200).
  const junioCompleto = mes('2024-06', { delta_pct: 2, delta_usd: 30, start_value: 450, end_value: 480,
    realized_pnl: -420, realized_ars: 240000, realized_ars_cubre_usd: -440, unrealized_pnl: 450,
    medicion: 'mercado', puntas_desde: '2024-05-31', puntas_hasta: '2024-06-30' })
  const celdas = Array.from({ length: 12 }, (_, idx) => ({ idx, month: idx === 5 ? junioCompleto : undefined }))
  const globo = (moneda) => texto(renderToStaticMarkup(
    <BarrasDelAnio cells={celdas} pesos={pesosDe(moneda)} enPesos={moneda === 'ARS'} tipAbajo encimaInicial={5} />))

  it('el monto es la resta de pesos del mes (480 × 1.200 − 450 × 1.000), no los dólares como pesos', () => {
    const t = globo('ARS')
    expect(t).toContain('+$126.000')
    expect(t).not.toContain('+$30')   // US$ 30 sin convertir
  })
  it('la leyenda dice cómo se arma', () => {
    expect(globo('ARS')).toContain('en pesos, cada punta a su dólar')
  })
  it('un mes medido AL COSTO no dice "cada punta a su dólar": su monto es lo vendido, exacto', () => {
    // La cadena contable: start/end_value son costo en dólares, no hay puntas a mercado.
    const costo = mes('2024-06', { delta_pct: 2, delta_usd: 10, start_value: 450, end_value: 460,
      realized_pnl: 10, realized_ars: 240000, realized_ars_cubre_usd: 10, unrealized_pnl: 0,
      medicion: 'costo', puntas_desde: null, puntas_hasta: null })
    const c = Array.from({ length: 12 }, (_, idx) => ({ idx, month: idx === 5 ? costo : undefined }))
    const t = texto(renderToStaticMarkup(
      <BarrasDelAnio cells={c} pesos={pesosDe('ARS')} enPesos tipAbajo encimaInicial={5} />))
    expect(t).not.toContain('cada punta a su dólar')
    expect(t).toContain('lo vendido, exacto')
    expect(t).toContain('+$240.000')   // y no 460 × 1.200 − 450 × 1.000 = +$102.000
  })
  it('si parte de lo vendido está convertido, la leyenda no dice «exacto» (el aviso de abajo lo contradice)', () => {
    // [auditoría 4] «lo vendido, exacto» y, dos renglones después, «incluye US$ 20 convertidos».
    const costo = mes('2024-06', { delta_pct: 2, delta_usd: 30, start_value: 450, end_value: 480,
      realized_pnl: -420, realized_ars: 240000, realized_ars_cubre_usd: -440, unrealized_pnl: 0,
      medicion: 'costo', puntas_desde: null, puntas_hasta: null })
    const c = Array.from({ length: 12 }, (_, idx) => ({ idx, month: idx === 5 ? costo : undefined }))
    const t = texto(renderToStaticMarkup(
      <BarrasDelAnio cells={c} pesos={pesosDe('ARS')} enPesos tipAbajo encimaInicial={5} />))
    expect(t).toContain('incluye US$ 20 convertidos')
    expect(t).toContain('en pesos: lo vendido')
    expect(t).not.toContain('lo vendido, exacto')
  })
  it('un mes del motor sí: su monto también es de dos puntas, cada una a su dólar', () => {
    const motor = mes('2024-06', { delta_pct: 2, delta_usd: 10, start_value: 450, end_value: 460,
      realized_pnl: 10, realized_ars: 240000, realized_ars_cubre_usd: 10, unrealized_pnl: 0,
      medicion: 'motor', delta_ars: 31000, puntas_desde: null, puntas_hasta: null })
    const c = Array.from({ length: 12 }, (_, idx) => ({ idx, month: idx === 5 ? motor : undefined }))
    const t = texto(renderToStaticMarkup(
      <BarrasDelAnio cells={c} pesos={pesosDe('ARS')} enPesos tipAbajo encimaInicial={5} />))
    expect(t).toContain('cada punta a su dólar')
    expect(t).toContain('+$31.000')
  })
  it('lo cerrado va aparte, con los pesos de verdad de las ventas, y avisa lo convertido', () => {
    const t = globo('ARS')
    expect(t).toContain('de operaciones cerradas: +$264.000')   // 240.000 + US$ 20 × 1.200
    expect(t).toContain('incluye US$ 20 convertidos al dólar del cierre')
  })
  it('el aviso de lo convertido baja de renglón y tiene ancho propio (si no, el globo se estira)', () => {
    const h = renderToStaticMarkup(
      <BarrasDelAnio cells={celdas} pesos={pesosDe('ARS')} enPesos tipAbajo encimaInicial={5} />)
    const aviso = h.slice(h.indexOf('incluye US$ 20'))
    // Antes del texto del aviso, el contenedor que lo envuelve:
    const caja = h.slice(h.lastIndexOf('<div', h.indexOf('incluye US$ 20')), h.indexOf('incluye US$ 20'))
    expect(aviso).toBeTruthy()
    expect(caja).toContain('whitespace-normal')
    expect(caja).toContain('max-w-[240px]')
    expect(caja).toContain('mt-1')
  })
  it('la leyenda del globo va en su propio renglón, debajo del monto', () => {
    const h = renderToStaticMarkup(
      <BarrasDelAnio cells={celdas} pesos={pesosDe('ARS')} enPesos tipAbajo encimaInicial={5} />)
    const i = h.indexOf('en pesos, cada punta a su dólar')
    expect(i).toBeGreaterThan(0)
    expect(h.slice(h.lastIndexOf('<div', i), i)).toContain('mt-1')
  })
  it('en Dólares: dólares y sin leyenda ni aviso de conversión', () => {
    const t = globo('USD')
    expect(t).not.toContain('cada punta a su dólar')
    expect(t).not.toContain('convertidos')
    expect(t).toMatch(/US\$\s?30\b/)
  })
})
