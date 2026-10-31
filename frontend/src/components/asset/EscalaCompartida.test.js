// La imagen de «Compartir» del gráfico técnico no lleva tu precio de compra,
// tampoco en la ESCALA (auditoría D4, 31/10). En automático la pantalla se
// estira hasta tu precio y la imagen no (`compartible`). Pero al arrastrar la
// columna de precios o el gráfico, el rango «a mano» arrancaba del de la
// pantalla y ése se compartía: la franja vacía de abajo decía más o menos a
// cuánto compraste. Ahora el precio a mano lleva dos rangos (ejesGrafico:
// empezarAMano / estirarAMano / correrAMano), y el de la imagen arranca de
// `compartible`.
//
// Se compara la salida CON y SIN cartera (la memoria «la privacidad se filtra
// por la forma»): los mismos precios y los mismos gestos; con cartera la
// pantalla va estirada hasta tu precio (80), sin cartera no. La imagen tiene
// que salir IGUAL en los dos casos.
import { describe, it, expect } from 'vitest'
import { empezarAMano, estirarAMano, correrAMano } from '../../utils/ejesGrafico'
import { specDelGrafico } from '../../utils/imagenGrafico'

// Las escalas automáticas del gráfico (LecturaTecnica, el useMemo de la
// escala): los precios van de 95 a 130; `compartible` no depende de tu precio.
const COMPARTIBLE = [92, 133]
const PANTALLA = { con: [77, 133], sin: [92, 133] } // con cartera, estirada hasta 80

// Los gestos de una persona: estira la columna 60 px, la suelta, la vuelve a
// estirar −30 y después arrastra el gráfico un 10 % para abajo.
function gestos(pantalla) {
  let mano = null
  const columna = (dy) => {
    const inicio = mano || empezarAMano(pantalla, COMPARTIBLE) // onPointerDown de la columna
    mano = estirarAMano(inicio, dy)                            // onPointerMove
  }
  columna(60)
  columna(-30)
  mano = correrAMano(mano || empezarAMano(pantalla, COMPARTIBLE), 0.1) // arrastrar el gráfico
  return mano
}

const PUNTOS = [{ d: '2026-10-28', c: 95 }, { d: '2026-10-29', c: 120 }, { d: '2026-10-30', c: 130 }]
const imagen = (mano) => JSON.stringify(specDelGrafico({ activo: 'MELI', puntos: PUNTOS, lo: mano.comp.lo, hi: mano.comp.hi }))

describe('la escala de la imagen de «Compartir», con el precio a mano', () => {
  it('la pantalla sí cambia con tu precio (si no, la prueba no prueba nada)', () => {
    const con = gestos(PANTALLA.con), sin = gestos(PANTALLA.sin)
    expect(con.lo).not.toBeCloseTo(sin.lo, 3)
  })

  it('la imagen sale igual CON y SIN cartera, y arranca de `compartible`', () => {
    const con = gestos(PANTALLA.con), sin = gestos(PANTALLA.sin)
    expect(con.comp).toEqual(sin.comp)
    expect(imagen(con)).toBe(imagen(sin))
    // Es lo mismo que haría la pantalla de alguien sin cartera.
    expect(con.comp.lo).toBeCloseTo(sin.lo, 9)
    expect(con.comp.hi).toBeCloseTo(sin.hi, 9)
  })

  it('el primer gesto también: arrastrar el gráfico desde automático', () => {
    const con = correrAMano(empezarAMano(PANTALLA.con, COMPARTIBLE), -0.2)
    const sin = correrAMano(empezarAMano(PANTALLA.sin, COMPARTIBLE), -0.2)
    expect(con.comp).toEqual(sin.comp)
    expect(con.comp.lo).toBeGreaterThan(80) // tu precio (80) no entra en la escala de la imagen
  })
})
