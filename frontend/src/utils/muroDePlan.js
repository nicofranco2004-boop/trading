// ¿El muro "elegí un plan" (cuenta en pausa) tapa esta pantalla? UNA regla para
// el muro (MuroDePlanGate, App.jsx) y para lo que se abre encima de la app (el
// buscador ⌘K): si el buscador se abriera con el muro puesto, quedaría DEBAJO
// —invisible— con el teclado atrapado adentro.
//
// ⚠️ El muro NO puede taparle las páginas por las que sale de la pausa. Sus
// propios botones llevan a /planes: si se tapara ahí, el muro sería una puerta
// cerrada con la llave adentro (el mismo agujero que tuvo el backend con
// /api/billing/subscribe).
export function muroTapaLaPantalla(user, pathname = '') {
  if (!user?.cuenta_en_pausa) return false
  return !(pathname.startsWith('/planes') || pathname.startsWith('/billing'))
}
