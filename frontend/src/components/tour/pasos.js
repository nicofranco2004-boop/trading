// Los pasos del tutorial de novedades — qué se resalta y qué se dice.
// ═══════════════════════════════════════════════════════════════════════════
// Separado del componente a propósito: así se puede leer la lista sin leer el
// mecanismo, y se puede probar que lo que el tutorial promete existe de verdad
// en la pantalla (ver pasos.test.js — cruza cada `marca` contra el código).
//
// A QUIÉN SE LE MUESTRA: a todos, una vez. La gente que YA usa Rendi es la que
// no tiene forma de enterarse de que esto existe; un usuario nuevo al menos
// encuentra los botones explorando.
//
// CÓMO SE ELIGIERON LOS BLANCOS A RESALTAR: cada paso apunta a algo que está
// SIEMPRE en pantalla. La tentación era resaltar el botón "Escuchar" de una
// respuesta, que es lo que de verdad hace sonar a Rendi — pero ese botón sólo
// existe si ya hay una respuesta, y el tutorial corre con el chat vacío. Se
// resalta el interruptor de arriba, que decide lo mismo y siempre está.

/** Dónde vive cada paso. `null` = donde esté el usuario, sin moverlo.
 *
 *  `libro` es la variante para el ASESOR en su propio nivel, donde el producto
 *  de verdad es otro. Es el MISMO tutorial —mismos pasos, mismo aspecto— y sólo
 *  cambia donde cambia lo que puede hacer. */
export const PASOS = [
  {
    id: 'isla',
    marca: 'isla',
    ruta: null,
    titulo: 'Rendi te acompaña',
    texto: 'Esta burbuja te sigue por toda la app. Tocala para preguntarle algo sin '
      + 'perder de vista lo que estabas mirando — y si te tapa algo, arrastrala a '
      + 'donde quieras.',
  },
  {
    id: 'microfono',
    marca: 'microfono',
    ruta: '/ai',
    titulo: 'Hablale en vez de escribir',
    texto: 'Mantené el micrófono y contale la pregunta. Lo que dijiste aparece en el '
      + 'cuadro para que lo revises: nunca se manda solo.',
  },
  {
    id: 'parlante',
    marca: 'parlante',
    ruta: '/ai',
    titulo: 'Y Rendi te contesta hablando',
    texto: 'Con esto prendido te lee la respuesta en voz alta, y sigue hablando aunque '
      + 'cambies de pantalla. Si preferís leer nomás, apagalo y listo.',
  },
  {
    id: 'registrar',
    marca: 'cuadro',
    ruta: '/ai',
    titulo: 'Contale lo que compraste',
    texto: 'Escribí o dictá «compré 100 dólares a 1.450» y Rendi lo carga en tu cartera. '
      + 'Te muestra qué entendió antes de guardar nada.',
    // 🔴 EL ASESOR NO PUEDE REGISTRAR OPERACIONES PROPIAS y no es un olvido:
    // la herramienta está excluida a propósito de su juego (ver
    // _AI_TOOLS_ADVISOR). Lo que SÍ tiene es la compra GRUPAL, que es la misma
    // idea a escala de su libro. Prometerle el botón que no tiene sería peor
    // que no mostrarle el paso.
    libro: {
      titulo: 'Contale una compra de varios clientes',
      texto: 'Dictá «registrale a Juan 300.000 pesos y a Ana 400.000 del CEDEAR de Tesla '
        + 'a 58.900» y Rendi lo anota para los dos. Te muestra qué entendió antes de '
        + 'guardar nada, y no toca los brokers: sólo lo registra en Rendi.',
    },
  },
  // Los dos últimos llevan a Alertas. El ORDEN importa: primero el resumen,
  // que es la novedad, y después los avisos de precio, que ya existían. Al
  // revés, el tutorial presentaría como noticia algo que el usuario ya tenía.
  {
    id: 'resumen-mercado',
    marca: 'resumen-mercado',
    ruta: '/alertas',
    titulo: 'Enterate sin entrar',
    texto: 'Prendé esto y cada mañana te llega un mail con lo que pasó desde que cerró '
      + 'el mercado: las tasas, el dólar, la inflación, el petróleo — y qué de todo eso '
      + 'toca a tus activos. Un mail por día hábil, y lo apagás cuando quieras.',
  },
  {
    id: 'alertas-precio',
    marca: 'nueva-alerta',
    ruta: '/alertas',
    titulo: 'Y avisos cuando algo se mueve',
    texto: 'Acá pedís que te avisemos si un activo llega a cierto precio, o si alguno de '
      + 'los tuyos sube o baja más de lo que vos digas. Te llega por mail y al teléfono.',
  },
]

/** La marca que se le pone al elemento que hay que resaltar. */
export const ATRIBUTO = 'data-tour'

export const CLAVE_VISTO = 'rendi:tour:novedades:v1'

/** ¿Ya lo vio? Si el almacenamiento no se puede leer, se asume que SÍ: mejor
 *  no mostrarlo que mostrarlo en loop a alguien que no lo puede apagar. */
export function yaLoVio(almacen) {
  try {
    return almacen.getItem(CLAVE_VISTO) === '1'
  } catch {
    return true
  }
}

export function marcarVisto(almacen) {
  try {
    almacen.setItem(CLAVE_VISTO, '1')
  } catch { /* sin almacenamiento: se va a volver a ver, y es lo menos malo */ }
}
