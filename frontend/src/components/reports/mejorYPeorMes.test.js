import { describe, it, expect } from 'vitest'
import { mejorYPeorMes } from './PerformanceCalendar'

// La fila de cada año de Reportes ya no rankea: muestra `ranking_por_anio` de
// `/api/reports/timeline`. Los payloads de abajo son los que devuelve el servidor
// para la cuenta de `backend/tests/test_reportes_mejor_peor_mes.py` (SPY −5 %,
// −20 %, −2 % y el mes de alta en 0 % contable).
const meses = [
  { period_key: '2025-01', period_label: 'Enero 2025' },
  { period_key: '2025-02', period_label: 'Febrero 2025' },
  { period_key: '2025-03', period_label: 'Marzo 2025' },
  { period_key: '2025-04', period_label: 'Abril 2025' },
]

describe('mejorYPeorMes — lo que eligió el servidor, sin mezclar bases', () => {
  it('a mercado: el 0 % contable de enero no es el "mejor mes", y se dice entre cuáles se eligió', () => {
    const ranking = {
      base: 'mercado',
      mejor: { mes: '2025-04', pct: -2.0, base: 'mercado' },
      peor: { mes: '2025-03', pct: -20.0, base: 'mercado' },
      positivos: 0, total: 3, sin_medir_a_mercado: 1,
    }
    const [mejor, peor] = mejorYPeorMes(ranking, meses)
    expect(mejor).toMatchObject({ label: 'Mejor mes', valor: '−2,0%', tono: 'neg',
                                  nota: 'abril, a precio de mercado' })
    expect(peor).toMatchObject({ label: 'Peor mes', valor: '−20,0%', tono: 'neg',
                                 nota: 'marzo, a precio de mercado' })
  })

  it('todo a mercado: sin aclaración, sólo el mes', () => {
    const ranking = {
      base: 'mercado',
      mejor: { mes: '2025-02', pct: 20, base: 'mercado' },
      peor: { mes: '2025-03', pct: -25, base: 'mercado' },
      positivos: 1, total: 2, sin_medir_a_mercado: 0,
    }
    const [mejor] = mejorYPeorMes(ranking, meses)
    expect(mejor).toMatchObject({ valor: '+20,0%', tono: 'pos', nota: 'febrero' })
  })

  it('contable: lo dice y va sin color; un solo mes no se repite como peor', () => {
    const ranking = {
      base: 'contable',
      mejor: { mes: '2025-01', pct: 0, base: 'contable' },
      peor: { mes: '2025-01', pct: 0, base: 'contable' },
      positivos: 0, total: 1, sin_medir_a_mercado: 1,
    }
    const out = mejorYPeorMes(ranking, meses)
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({ label: 'Mejor mes', tono: undefined,
                                   nota: 'enero, de tu historia importada' })
  })

  it('sin ranking del servidor no inventa uno', () => {
    expect(mejorYPeorMes(undefined, meses)).toEqual([])
    expect(mejorYPeorMes({ base: null, mejor: null, peor: null }, meses)).toEqual([])
  })
})
