import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'

const fuente = readFileSync(new URL('./AICoach.jsx', import.meta.url), 'utf8')

// ─── Las tarjetas vienen en el mensaje, no adentro del texto ─────────────────
// Rendi manda su respuesta en dos partes: la PROSA y un bloque de datos con el
// veredicto, las cifras, los gráficos, las fuentes y los botones de "seguí por
// acá". Quien arma el mensaje (VozContext) ya los separa: `content` queda con
// la prosa sola y el resto va en `meta`.
//
// Acá se re-parseaba `content` buscando ese bloque — que ya no está — así que
// devolvía vacío y NO SE DIBUJABA NADA. MEDIDO en pantalla: Rendi mandó
// veredicto "Concentración alta", titular, 2 cifras, 1 gráfico y 3
// seguimientos; en pantalla, cero. Todo el nivel visual de las respuestas,
// muerto, desde que la conversación se mudó al contexto.
describe('el chat dibuja las tarjetas que Rendi manda', () => {
  it('usa el `meta` del mensaje y no re-parsea el texto', () => {
    expect(fuente).toMatch(/const meta = m\.meta \|\| parseado\?\.meta/)
  })

  it('el parseo queda sólo de respaldo, para mensajes viejos', () => {
    // Una conversación guardada de antes de este cambio sí trae el bloque
    // adentro del texto; ésa se tiene que seguir viendo.
    expect(fuente).toMatch(/const parseado = m\.meta \? null : parseStructured\(m\.content\)/)
  })

  it('y la prosa sale del lado correcto según de dónde vino', () => {
    expect(fuente).toMatch(/const prose = m\.meta \? m\.content : parseado\?\.prose/)
  })

  it('sigue dibujando las cinco piezas del bloque', () => {
    // Si alguien saca una, desaparece de la pantalla sin ningún error.
    for (const pieza of ['meta?.verdict', 'meta?.stats', 'meta?.blocks',
                         'meta?.sources', 'meta?.followups']) {
      expect(fuente).toContain(pieza)
    }
  })
})
