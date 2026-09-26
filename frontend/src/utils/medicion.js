// medicion — en qué direcciones se le cuenta a Google Analytics y a Meta.
// ════════════════════════════════════════════════════════════════════════════
// Sólo en el sitio de verdad. Cualquier otra copia de la app — el servidor
// local (localhost, 127.0.0.1, la IP de la red de casa), un `vite preview`, un
// preview de Vercel — es alguien probando, no un visitante. Antes cada una de
// esas cargas sumaba una visita, un PageView para los anuncios y, si se probaba
// el registro, una "conversión" que Meta usaba para optimizar las campañas.
//
// La lista está DOS veces: acá y en el snippet del píxel en `index.html`, que
// corre antes que la app y no puede importar nada. Se cambian juntas;
// `medicion.test.js` corre ese snippet con cada dirección y falla si difieren.
export const SITIOS_MEDIDOS = ['rendi.finance', 'www.rendi.finance']

export function seMideEn(hostname) {
  return SITIOS_MEDIDOS.includes(String(hostname || '').toLowerCase())
}

export function seMideAca() {
  return typeof window !== 'undefined' && seMideEn(window.location?.hostname)
}
