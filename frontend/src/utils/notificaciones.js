// notificaciones — por qué una persona NO puede activar las notificaciones en
// este dispositivo, y qué decirle. Un solo lugar para todas las pantallas que
// ofrecen «Activar» (la lista de primeros pasos, Más, Alertas y la alerta de
// clientes del asesor): antes cada una tenía su propia frase, y dos de ellas
// fallaban en silencio.
//
// Dónde funcionan las notificaciones de Rendi:
//   · Compu (Chrome, Edge, Firefox, Safari de Mac) y Android: desde el
//     navegador, sin instalar nada.
//   · iPhone / iPad: SÓLO con Rendi agregada a la pantalla de inicio (iOS 16.4
//     o más nuevo). Abierta en Safari, el navegador ni siquiera ofrece el
//     permiso: Apple lo reserva para las apps del inicio.
//
// Por eso «agregá Rendi a tu inicio» es la respuesta para el iPhone, y no para
// la compu: ahí el mensaje correcto es otro.

/**
 * 'iphone-sin-instalar' | 'iphone-viejo' | 'navegador' | 'bloqueadas' | null
 * (null = se pueden activar desde acá).
 */
export function motivoSinPush({ supported, permission, plataforma, instalada }) {
  if (supported && permission === 'denied') return 'bloqueadas'
  if (supported) return null
  if (plataforma === 'iphone') return instalada ? 'iphone-viejo' : 'iphone-sin-instalar'
  return 'navegador'
}

// Pasos para destrabar un permiso que la persona negó. El navegador no deja
// volver a preguntar: lo tiene que cambiar ella, y para eso necesita saber
// dónde tocar en SU teléfono o SU compu.
const DESBLOQUEAR = {
  iphone: 'Abrí los Ajustes del iPhone → Notificaciones → Rendi → prendé «Permitir notificaciones».',
  android: 'En Chrome, tocá los tres puntitos → Configuración → Configuración de sitios → Notificaciones → rendi.finance → Permitir. Si Rendi está en tu inicio: mantené apretado el ícono → Información de la app → Notificaciones.',
  otro: 'Tocá el ícono que está a la izquierda de la dirección rendi.finance (un candado o unas rayitas) → Notificaciones → Permitir, y recargá la página.',
}

/**
 * Qué mostrar para cada motivo. `boton` = abre el paso a paso para agregar
 * Rendi al celular (null si no aplica).
 */
export function textoSinPush(motivo, plataforma) {
  switch (motivo) {
    case 'iphone-sin-instalar':
      return {
        titulo: 'Primero, agregá Rendi a tu inicio',
        cuerpo: 'En iPhone, Apple sólo deja mandar notificaciones a las apps que están en la pantalla de inicio. Son 4 toques y no hay que descargar nada. Después abrí Rendi desde el ícono y tocá «Activar» de nuevo.',
        boton: 'Ver cómo agregarla',
      }
    case 'iphone-viejo':
      return {
        titulo: 'Tu iPhone necesita actualizarse',
        cuerpo: 'Las notificaciones llegan a iPhone desde iOS 16.4. Se actualiza en Ajustes → General → Actualización de software. Mientras tanto, tus alertas te llegan por mail.',
        boton: null,
      }
    case 'navegador':
      return plataforma === 'android'
        ? {
            titulo: 'Este navegador no deja recibir notificaciones',
            cuerpo: 'Abrí Rendi en Chrome y activalas desde ahí. Mientras tanto, tus alertas te llegan por mail.',
            boton: null,
          }
        : {
            titulo: 'Este navegador no deja recibir notificaciones',
            cuerpo: 'Probá desde Chrome, Edge o Safari, o agregá Rendi a tu celular y activalas ahí. Mientras tanto, tus alertas te llegan por mail.',
            boton: 'Ver cómo agregarla',
          }
    case 'bloqueadas':
      return {
        titulo: 'Las notificaciones están bloqueadas',
        cuerpo: `En algún momento le dijiste que no a Rendi, y el navegador no nos deja volver a preguntarte. Para cambiarlo: ${DESBLOQUEAR[plataforma] || DESBLOQUEAR.otro}`,
        boton: null,
      }
    default:
      return null
  }
}

// Lo que se le dice cuando el intento de activar no salió y no es ninguno de
// los motivos de arriba (esos se muestran como cartel, no como mensaje suelto).
export const MENSAJE_CERRO_EL_PEDIDO = 'No se activaron. Cuando quieras, tocá «Activar» de nuevo.'
export const MENSAJE_FALLA = 'No pudimos activarlas ahora. Probá de nuevo en un rato.'
