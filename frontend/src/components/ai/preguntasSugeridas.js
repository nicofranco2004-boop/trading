// Las preguntas con las que arranca el chat — UNA sola lista para las dos
// pantallas.
// ═══════════════════════════════════════════════════════════════════════════
// Estaban copiadas: el chat grande tenía las doce y la isla tenía dos suyas,
// escritas a mano. El resultado fue que a un ASESOR la isla le ofrecía
// "¿cómo está mi portfolio en general?" y "¿qué riesgos detectás en mi
// cartera?" — preguntas sobre una cartera personal que él no tiene. El chat
// grande sí le ofrecía las del libro, porque allá la lista estaba bien. Dos
// copias, una actualizada y la otra no: el modo clásico de que se separen.

// Las doce de siempre. Tienen que coincidir LETRA POR LETRA con
// `_FREE_QUESTIONS_WHITELIST` del backend: Free y Plus sólo pueden mandar
// éstas, y una coma de más se las rebota con "el chat libre es sólo Pro".
export const SUGERIDAS = [
  '¿Cómo está mi portfolio en general?',
  '¿Qué riesgos detectás en mi cartera?',
  '¿Mi nivel de concentración es elevado?',
  '¿Cómo evalúo mi win rate?',
  '¿Está cara mi posición más grande?',
  '¿Detectás algún sesgo en mi forma de operar?',
  '¿Mi exposure por sector/región está equilibrado?',
  '¿Cuándo reportan earnings los activos de mi cartera?',
  'Si tuvieras que mejorar UNA cosa de mi cartera, ¿cuál sería?',
  '¿Cómo voy vs el S&P 500?',
  '¿Le estoy ganando a la inflación argentina?',
  '¿Qué activo es el que más riesgo me agrega?',
]

// Las del ASESOR en su propio nivel: preguntas sobre EL LIBRO, no sobre una
// cartera. No necesitan estar en la lista cerrada del backend — el plan asesor
// tiene chat libre, así que son sugerencias de arranque y nada más.
export const SUGERIDAS_ASESOR = [
  '¿Cómo viene mi libro en general?',
  '¿Qué cliente necesita mi atención hoy?',
  '¿Qué clientes tienen plata sin invertir?',
  '¿Quién está más concentrado en un solo activo?',
  '¿Qué activo le está haciendo perder plata a más clientes?',
  '¿Cómo está repartido el libro entre mis clientes?',
  '¿Qué cliente rindió mejor y cuál peor?',
  'Armame un resumen del libro para una reunión',
]

/** Las dos primeras, que es lo que entra en la isla. */
export const paraLaIsla = (modoLibro) =>
  (modoLibro ? SUGERIDAS_ASESOR : SUGERIDAS).slice(0, 2)
