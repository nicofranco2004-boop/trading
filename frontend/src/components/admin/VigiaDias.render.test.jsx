// La fila del vigía de días en /admin, dibujada con un hallazgo como el que
// arma el servidor (`billing/vigia_dias.evaluar`; las claves las fija
// backend/tests/test_vigia_dias.py). Es el caso real de octubre: Pro pagado el
// 14/10 y el 14/11, con tres avisos de Rebill contados como cobros.
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { FilaHallazgo, dia } from './VigiaDias'

const HALLAZGO = {
  id: 1322, email: 'cliente@rendi.test', name: 'Cliente', plan: 'pro',
  vence: '2027-03-14T22:05:39', deberia_vencer: '2026-12-14T22:05:39',
  dias_de_mas: 90, motivo: 'cobro_repetido',
  repetidos: [
    { fecha: '2026-10-14', dias: 30, nota: '', dias_despues_del_anterior: 0 },
    { fecha: '2026-10-15', dias: 30, nota: '', dias_despues_del_anterior: 0.9 },
  ],
}

const texto = (h) => renderToStaticMarkup(
  <FilaHallazgo h={h} motivo="Avisos de Rebill" onMotivo={() => {}}
    onCorregir={() => {}} onDejar={() => {}} ocupado={false} />)
  .replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

describe('FilaHallazgo', () => {
  it('dice cuándo vence, cuándo debería y cuántos días de más', () => {
    const t = texto(HALLAZGO)
    expect(t).toContain('vence 14/03/2027')
    expect(t).toContain('según lo que pagó, 14/12/2026')
    expect(t).toContain('90 días de más')
    expect(t).toContain('Un aviso de Rebill se contó como cobro más de una vez')
  })

  it('muestra de dónde salen los días: cada cobro repetido', () => {
    const t = texto(HALLAZGO)
    expect(t).toContain('14/10/2026 : + 30 días')
    expect(t).toContain('15/10/2026 : + 30 días')
  })

  it('ofrece corregir a la fecha que explica el historial, y dejarla como está', () => {
    const t = texto(HALLAZGO)
    expect(t).toContain('Corregir al 14/12/2026')
    expect(t).toContain('Dejar como está')
  })

  it('sin fecha que lo explique (plan sin ningún cobro) sólo deja «dejar como está»', () => {
    const t = texto({ ...HALLAZGO, motivo: 'sin_registro', deberia_vencer: null, repetidos: [] })
    expect(t).not.toContain('Corregir al')
    expect(t).toContain('Dejar como está')
    expect(t).toContain('sin ningún renglón')
  })

  it('las fechas van día/mes/año', () => {
    expect(dia('2026-12-14T22:05:39')).toBe('14/12/2026')
    expect(dia(null)).toBe('—')
  })
})
