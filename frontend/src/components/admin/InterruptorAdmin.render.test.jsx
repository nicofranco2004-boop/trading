// Los interruptores de /admin dibujados con la respuesta del servidor
// (GET /api/admin/mover-entre-brokers → { interruptor, cuentas_con_pases }; las claves
// las fija backend/tests/test_mover_entre_brokers.py::ElAdminPuedeVolverAtras).
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { VistaInterruptor, TEXTOS_MOVER, lineaPasesVivos } from './InterruptorAdmin'

const texto = (e, extra) => renderToStaticMarkup(
  <VistaInterruptor titulo="Mover a otro broker" e={e} busy={false} textos={TEXTOS_MOVER} onCambiar={() => {}}>
    {extra}
  </VistaInterruptor>).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

describe('el interruptor de «Mover a otro broker» en /admin', () => {
  it('apagado: ofrece prenderlo y dice qué pasa mientras tanto', () => {
    const t = texto({ interruptor: { encendido: false }, cuentas_con_pases: [] })
    expect(t).toContain('Prender «Mover a otro broker»')
    expect(t).toContain('nadie puede armar un pase nuevo')
  })

  it('prendido: ofrece apagarlo y muestra cuándo se cambió', () => {
    const t = texto({ interruptor: { encendido: true, cambiado_at: '2026-11-24 13:00:00' } })
    expect(t).toContain('Apagar «Mover a otro broker»')
    expect(t).toContain('PRENDIDO')
    expect(t).toContain('cambiado 2026-11-24 13:00:00 (UTC)')
  })

  it('mientras carga no deja tocar el botón', () => {
    const html = renderToStaticMarkup(
      <VistaInterruptor titulo="x" e={null} busy={false} textos={TEXTOS_MOVER} onCambiar={() => {}} />)
    expect(html).toContain('disabled')
    expect(html).toContain('Cargando…')
  })

  it('lo propio de cada panel va abajo del estado', () => {
    const t = texto({ interruptor: { encendido: false }, cuentas_con_pases: [] }, (e) => `hay ${e.cuentas_con_pases.length}`)
    expect(t).toContain('hay 0')
  })

  it('cuenta los pases sin deshacer, que hay que deshacer antes de volver atrás', () => {
    expect(lineaPasesVivos([])).toBe('Nadie tiene pases sin deshacer.')
    expect(lineaPasesVivos([{ user_id: 7, pases: 1 }])).toBe(
      '1 pase sin deshacer (cuenta 7: 1). Antes de volver atrás una publicación, hay que deshacerlos.')
    expect(lineaPasesVivos([{ user_id: 7, pases: 2 }, { user_id: 9, pases: 1 }])).toContain('3 pases sin deshacer')
  })
})
