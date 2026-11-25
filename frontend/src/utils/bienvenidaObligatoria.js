// bienvenidaObligatoria — ¿a esta persona le falta configurar Rendi? UNA regla
// para todos los que la preguntan: la puerta (App.jsx → Layout manda a
// /onboarding), la isla de Mervall-E y los tutoriales (VozGate no se muestran),
// el buscador ⌘K (no se abre) y la propia página de la bienvenida (si no le
// falta nada, la manda al inicio).
//
// QUIÉN DECIDE: el servidor. `user.falta_cargar_historial` sale de /auth/me
// (backend/bienvenida.py): cuenta nueva (creada desde el corte), que no es
// asesor, ni cliente de un asesor, ni admin, y que todavía no confirmó ningún
// archivo de su broker. Acá sólo se suman las excepciones que son de ESTA
// pantalla y que el servidor no ve:
//   · la cuenta en pausa → gana el muro de elegir plan (con la cuenta en pausa
//     no se puede importar: el servidor contesta 402);
//   · el demo → es una cartera de ejemplo, no una cuenta;
//   · un asesor adentro de un cliente → la bienvenida es de quien se loguea.
//
// ⚠️ NO DECIDIR ANTES DE `bootstrapped` (AuthContext). Al abrir la pestaña el
// usuario sale primero de lo guardado en el navegador y después lo confirma
// /auth/me. Decidir con lo guardado puede encerrar a quien ya cargó (en otra
// compu) o soltar a quien todavía no, y parpadear. La puerta pregunta
// `bootstrapped` antes de mandar a nadie a ningún lado.
//
// Lo que siempre queda a la vista aunque falte configurar:
//   · la lista del muro de plan (utils/muroDePlan.js, una sola, importada acá):
//     los planes y el pago (por donde se sale de una pausa) y lo que /planes
//     dice que aceptás (términos, reembolso, privacidad);
//   · la propia bienvenida;
//   · las pantallas sueltas que llegan por un link de mail y no muestran la
//     cartera de la persona: el pedido de acceso de un asesor (/acceso?token=…)
//     y el informe que le mandó (/i/:token). Si la puerta las tapara, el token
//     se perdía y no había forma de contestarle al asesor;
//   · la guía pública (/guia), que también se lee antes de registrarse.

import { guardar, leer } from './almacen'
import { CATALOGO } from './catalogoDelAlmacen'
import { SIEMPRE_A_LA_VISTA as LO_QUE_EL_MURO_DEJA_VER } from './muroDePlan'

export const SIEMPRE_A_LA_VISTA = ['/onboarding', '/acceso', '/i/', '/guia', ...LO_QUE_EL_MURO_DEJA_VER]

/** ¿Le falta cargar su historial para ver Rendi? */
export function faltaConfigurar(user, { isDemo = false, clientCtx = null } = {}) {
  return !!user?.falta_cargar_historial && !user?.cuenta_en_pausa && !isDemo && !clientCtx
}

/** ¿La bienvenida tapa esta pantalla? (= la puerta manda a /onboarding) */
export function bienvenidaTapaLaPantalla(user, pathname = '', ctx = {}) {
  if (!faltaConfigurar(user, ctx)) return false
  return !SIEMPRE_A_LA_VISTA.some(r => String(pathname || '').startsWith(r))
}

// ── «Se acaba de configurar» (dura lo que la pestaña) ────────────────────────
// Al terminar la bienvenida la persona aterriza en el inicio. El tutorial de
// novedades arrancaría solo a los 900 ms, encima de la lista de primeros pasos
// y de todo lo que recién vio: en esta visita ya tuvo bastante. Le toca la
// próxima vez que entre (otra pestaña, otro día).

/** Marca que en esta pestaña se acaba de terminar la bienvenida. */
export function marcarRecienConfigurado() {
  try { guardar(CATALOGO.recienConfigurado, '1') } catch { /* sin almacenamiento: el tutorial puede salir, no es grave */ }
}

/** ¿En esta pestaña se acaba de terminar la bienvenida? */
export function recienConfigurado() {
  try { return leer(CATALOGO.recienConfigurado) === '1' } catch { return false }
}
