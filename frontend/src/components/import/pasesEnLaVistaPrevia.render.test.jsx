// La vista previa del importador después de un pase entre brokers («Mover a otro
// broker»), dibujada con la forma REAL de POST /api/imports/preview (la fija
// backend/tests/test_mover_entre_brokers_contrato.py). Lo que fija la integración:
//   · `ya_traspasados`: el bloque «Ya las cargaste con «Mover a otro broker»»;
//   · el cartel «filas ya estaban importadas» cuenta SÓLO las repetidas por huella:
//     el servidor manda en `duplicate_row_indices` también la llegada del pase y su
//     depósito compensatorio (`filas_de_pases`), que ya dice el bloque de arriba y
//     no coinciden «por fecha + broker + tipo…» (antes decía «2 filas ya estaban
//     importadas» con un motivo que no era el de ellas);
//   · `avisos_de_pases`: lo que entra igual pero puede ser lo mismo que un pase (el
//     servidor lo mandaba y la pantalla no lo dibujaba);
//   · `cambian_un_pase`: el bloque rojo con el `mensaje` del servidor.
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { PreviewStep } from './ImportWizard'

const BASE = {
  summary: { total_rows: 3, valid_rows: 3, invalid_rows: 0 },
  rows_preview: [], errors: [], by_asset: [], cash_warnings: [], traspasos: [],
  session_id: 's1', route_by_currency: false, is_multi_broker: false, new_brokers_created: [],
  ya_traspasados: [], cambian_un_pase: null, avisos_de_pases: [], filas_de_pases: [], duplicate_row_indices: [],
}
const dibujar = (preview) => renderToStaticMarkup(<PreviewStep preview={{ ...BASE, ...preview }} importMode="single" singleBroker="Balanz" />)

describe('la vista previa del importador con un pase entre brokers', () => {
  it('la llegada del pase va en su bloque, no en el cartel de las repetidas por huella', () => {
    const html = dibujar({
      ya_traspasados: [{ fecha: '2025-06-18', activo: 'VIST', cantidad: 4, broker: 'Balanz', lado: 'entrada' }],
      duplicate_row_indices: [2, 3], filas_de_pases: [2, 3],
    })
    expect(html).toContain('Ya las cargaste con «Mover a otro broker» (1)')
    expect(html).toContain('18/06/2025 · llegada de 4 VIST')
    expect(html).not.toContain('ya estaban importadas')
    expect(html).not.toContain('ya estaba importada')
  })

  it('con una repetida por huella además, el cartel cuenta sólo ésa', () => {
    const html = dibujar({
      ya_traspasados: [{ fecha: '2025-06-18', activo: 'VIST', cantidad: 4, broker: 'Balanz', lado: 'entrada' }],
      duplicate_row_indices: [2, 3, 5], filas_de_pases: [2, 3],
    })
    expect(html).toContain('1 fila ya estaba importada')
    expect(html).not.toContain('3 filas ya estaban importadas')
  })

  it('los avisos de un pase se ven, uno por renglón', () => {
    const AVISO = 'Ojo: este archivo trae una llegada de 4 VIST a Balanz el 14/09, lejos de tu pase desde Bull Market ' +
      'del 16/06: la cargamos como otra llegada. Si es la misma, deshacé el pase antes de importar el archivo.'
    const html = dibujar({ avisos_de_pases: [AVISO] })
    expect(html).toContain('Revisá esto antes de confirmar')
    expect(html).toContain(AVISO)
    expect(dibujar({})).not.toContain('Revisá esto antes de confirmar')
  })

  it('un archivo que cambia la historia anterior al pase: el bloque rojo con el texto del servidor', () => {
    const mensaje = 'Este archivo trae compras de GLOB en Balanz del 05/01/2025, anteriores a tu pase del 16/06/2025 a Cocos. ' +
      'Si lo confirmamos, el pase quedaría con otros lotes. Deshacé el pase (Movimientos → la fila «Pase» → Deshacer), ' +
      'importá el archivo y volvé a moverlos.'
    const html = dibujar({ cambian_un_pase: { traspaso_id: 't1', lado: 'origen', fecha: '2025-06-16', fecha_fila: '2025-01-05',
      asset: 'GLOB', broker: 'Balanz', contraparte: 'Cocos', op: 'BUY', mensaje } })
    expect(html).toContain('Este archivo choca con un pase entre tus brokers')
    expect(html).toContain(mensaje)
  })
})
