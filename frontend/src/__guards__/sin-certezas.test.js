// Lo que habla del futuro del precio se dice como posibilidad («podría»), nunca
// como certeza. Pedido de Nico el 23/10: «ahí se termina la suba» sonaba a que
// iba a pasar seguro.
//
// POR QUÉ ESTE TEST
// ─────────────────
// El 23/10 se corrigió la frase en la tarjeta de Fibonacci (0431739d), en el
// resumen de la IA (1e297ff1) y en la de Elliott (fdfb0f90), cada una con SU
// prueba, que miraba SU texto. El rótulo del gráfico decía lo mismo en otro
// archivo (CapaFibonacci.jsx: «Cierre encima: termina la bajada») y siguió así
// seis días, hasta la auditoría D del 29/10. Causa de proceso: la regla vivía
// texto por texto; ninguna prueba recorría la app entera.
//
// Recorre el ÁRBOL (scripts/texto-visible.mjs), no una lista: un componente
// nuevo entra solo. Los comentarios pueden contar la historia; lo que se
// muestra, no. Falta el mismo guardián para los textos del servidor (mail y
// avisos de los sábados): hoy el grep no encuentra ninguna certeza ahí.
import { describe, it, expect } from 'vitest'
import { ENTRE, archivosConTexto, hallazgos, relativa, sinComentarios } from '../../scripts/texto-visible.mjs'

// Frases que afirman lo que va a hacer el precio. «terminó» (pasado) no entra:
// lo que ya pasó se cuenta como pasó.
export const CERTEZAS = [
  new RegExp(String.raw`\btermin(?:a|ar[aá]|ar[ií]a)${ENTRE}(?:la|el)${ENTRE}(?:suba|bajada|tendencia|ca[ií]da|rebote)\b`, 'gi'), // «termina la suba»
  new RegExp(String.raw`\bse${ENTRE}(?:da|dar[ií]a)${ENTRE}por${ENTRE}terminad`, 'gi'),     // «se da por terminada»
  new RegExp(String.raw`\bse${ENTRE}terminar[ií]a\b`, 'gi'),                               // «se terminaría»
  new RegExp(String.raw`\bse${ENTRE}invalida\b`, 'gi'),                                     // «el conteo se invalida»
  new RegExp(String.raw`\bva${ENTRE}a${ENTRE}(?:subir|bajar|caer|rebotar|terminar|romper)\b`, 'gi'), // «va a subir»
  new RegExp(String.raw`\bseguramente\b`, 'gi'),
  new RegExp(String.raw`\bconfirmar[ií]a\b`, 'gi'),
  new RegExp(String.raw`\bsuele${ENTRE}(?:frenar|rebotar|terminar|subir|bajar|caer)\b`, 'gi'), // «suele rebotar» (no se cumplió en la medición)
  new RegExp(String.raw`\bsuele${ENTRE}anticipar${ENTRE}una${ENTRE}(?:baja|suba|ca[ií]da)`, 'gi'),
  new RegExp(String.raw`\bantesala\b`, 'gi'),
  // Sin sujeto, «Dejaría de valer · US$ 47,84» se lee como que la ACCIÓN dejaría
  // de valer eso. Lo que deja de valer es el conteo de Elliott: que lo diga.
  new RegExp(String.raw`(?<!conteo${ENTRE})\bdejar[ií]a${ENTRE}de${ENTRE}valer\b`, 'gi'),
]

const TODOS = archivosConTexto()

describe('lo que habla del futuro, como posibilidad', () => {
  it('el recorrido lee la app entera, incluido el gráfico técnico', () => {
    const leidos = TODOS.map(relativa)
    expect(leidos.length).toBeGreaterThan(300)
    for (const r of ['src/components/asset/CapaFibonacci.jsx', 'src/components/asset/CapaElliott.jsx',
      'src/utils/fibonacci.js', 'src/utils/elliott.js', 'src/utils/tecnico.js']) {
      expect(leidos, r).toContain(r)
    }
  })

  it('el patrón caza la certeza y deja pasar la posibilidad y el pasado', () => {
    const ve = (src) => CERTEZAS.flatMap((p) => [...sinComentarios('a.jsx', src).matchAll(p)].map((m) => m[0]))
    for (const mal of ["'Cierre encima: termina la bajada'", "<span>Cierre debajo: termina{' '}la suba</span>",
      "'Esa suba se da por terminada si…'", "'ahí se terminaría la suba'", "'el conteo se invalida'",
      "'el precio va a subir'", "'seguramente rebota'", "'suele rebotar ahí'", "'Dejaría de valer · US$ 47'",
      "'la antesala de una baja'"]) {
      expect(ve(mal), mal).not.toEqual([])
    }
    for (const bien of ["'podría ser una señal de que esa suba está perdiendo fuerza'",
      "'ahí terminó la suba, el 6/10'", "'Ahora tocá donde termina la línea'", "'el conteo dejaría de valer'",
      "// termina la bajada (comentario)", "'que en la teoría suele ser la más larga'"]) {
      expect(ve(bien), bien).toEqual([])
    }
  })

  it('ningún texto de la app afirma lo que va a hacer el precio', () => {
    const encontrados = TODOS.flatMap((r) => hallazgos(r, CERTEZAS))
    expect(encontrados, 'decilo como posibilidad («podría»)').toEqual([])
  })
})
