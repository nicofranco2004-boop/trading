// ¿El muro "elegí un plan" (cuenta en pausa) tapa esta pantalla? UNA regla para
// el muro (MuroDePlanGate, App.jsx) y para lo que se abre encima de la app (el
// buscador ⌘K): si el buscador se abriera con el muro puesto, quedaría DEBAJO
// —invisible— con el teclado atrapado adentro.
//
// ⚠️ El muro NO puede taparle las páginas por las que sale de la pausa. Sus
// propios botones llevan a /planes: si se tapara ahí, el muro sería una puerta
// cerrada con la llave adentro (el mismo agujero que tuvo el backend con
// /api/billing/subscribe). Tampoco lo que /planes dice que aceptás al
// suscribirte: los Términos y la Política de Reembolso (y la de Privacidad).
// Antes el muro los tapaba: te pedía aceptar algo que no te dejaba leer.
const SIEMPRE_A_LA_VISTA = ['/planes', '/billing', '/terminos', '/reembolso', '/privacidad']
export function muroTapaLaPantalla(user, pathname = '') {
  if (!user?.cuenta_en_pausa) return false
  return !SIEMPRE_A_LA_VISTA.some(r => pathname.startsWith(r))
}
