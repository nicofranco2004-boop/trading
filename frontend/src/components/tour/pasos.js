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
    // EL GESTO QUE SE PROMETE TIENE QUE SER EL QUE EL BOTÓN HACE. Acá decía
    // «mantené el micrófono» y el botón nunca fue de mantener apretado: es un
    // toque para empezar y el botón «Listo» del panel para terminar (ver
    // BotonMicrofono.jsx — `onClick={d.grabar}`, no `onPointerDown`). Quien le
    // hacía caso al tutorial soltaba el dedo y el micrófono seguía tomando.
    texto: 'Tocá el micrófono y contale la pregunta; cuando termines, tocá «Listo». '
      + 'Lo que dijiste aparece en el cuadro para que lo revises: nunca se manda solo.',
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
  // Cierra el tutorial y no es del asistente: es de la app entera. Va último a
  // propósito — los cinco anteriores cuentan una historia (Rendi te acompaña →
  // le hablás → te contesta → le registrás → te avisa) y meter el tema en el
  // medio la corta.
  //
  // Va a `/mas` y NO con `ruta: null`, que era lo primero que parecía bien. El
  // interruptor vive en dos lugares según el tamaño de pantalla: el menú
  // lateral en la computadora y «Más» en el celular. Con `null` el paso se
  // muestra donde el usuario esté — y como los dos pasos anteriores lo dejan en
  // /alertas, en CELULAR ahí no hay ningún interruptor y el paso se saltearía
  // solo: justo el usuario que no tiene menú lateral se quedaría sin enterarse.
  // `/mas` es la única ruta donde existe en los dos tamaños. En escritorio el
  // del menú lateral va antes en el DOM, así que es el que se resalta.
  {
    id: 'tema',
    marca: 'tema',
    ruta: '/mas',
    titulo: 'Y ahora, Rendi en claro',
    texto: 'Con este botón cambiás entre fondo oscuro y fondo blanco. Elegís una vez y '
      + 'Rendi se acuerda. Probá el que te resulte más cómodo para leer: de día suele '
      + 'ganar el claro.',
  },
]

/** La marca que se le pone al elemento que hay que resaltar. */
export const ATRIBUTO = 'data-tour'

// ⚠️ SUBIR ESTO ES LA ÚNICA FORMA DE QUE UNA NOVEDAD LLEGUE A QUIEN YA VIO EL
// TUTORIAL. El almacenamiento guarda un sí/no, no qué pasos vio, así que con la
// clave vieja un paso nuevo sólo lo verían los usuarios nuevos — o sea,
// exactamente los que no lo necesitan. El costo es que todos vuelven a ver el
// tutorial entero una vez. Se sube SÓLO cuando se agrega algo que vale ese
// costo; v2 = el modo claro.
export const CLAVE_VISTO = 'rendi:tour:novedades:v2'

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
