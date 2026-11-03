// espacioAbajo.js — cuánto ocupa lo que flota abajo de la pantalla del celular.
// ════════════════════════════════════════════════════════════════════════════
// La barra de pestañas (MobileTabBar) y, apoyados encima, los botones flotantes
// de Mervall-E (voz/RendiMate, a la izquierda) y de WhatsApp
// (SupportWhatsAppFab, a la derecha). Una sola cuenta para los tres y para lo
// que tiene que esquivarlos.
//
// Por qué existe (auditoría D8, 29/10): el espacio que se dejaba al final de
// cada página medía la barra (64 px) y no los botones que se sumaron después
// arriba de ella (hasta 128 px): el aviso «no es una recomendación» del final
// de Análisis técnico quedaba debajo de los botones y no se podía leer, y el
// globo de ayuda de «Beta» se abría detrás de ellos.

/** La barra de pestañas: 56 px más el «+» que sobresale. */
export const BARRA_ABAJO = 64
/** Los botones flotantes: a cuántos px del borde de abajo y cuánto miden. */
export const FLOTANTES_DESDE_ABAJO = 80
export const FLOTANTES_ALTO = 48
/** Lo que se deja libre al final de cada página: barra + botones + aire. */
export const ESPACIO_ABAJO_CELULAR = FLOTANTES_DESDE_ABAJO + FLOTANTES_ALTO + 8
