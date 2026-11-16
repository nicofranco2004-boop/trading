// Las landings de cada broker (/brokers/*), en UNA lista.
//
// La leen la portada (bloque «¿Usás un broker en particular?») y cada landing de
// broker («También te puede interesar»). Antes cada página tenía su lista a mano
// y una landing nueva quedaba sin links desde las demás hasta que alguien se
// acordaba de ir a sumarla en seis archivos.
//
// Vive en data/ y no al lado de las landings a propósito: la portada la importa,
// y no tiene que arrastrar las guías de descarga de todos los brokers.
// `pages/keywords/guiasDeBrokers.render.test.jsx` se pone rojo si una ruta
// /brokers/* de paginasPublicas.js no está acá, o al revés.

// `guia` es el id del broker en BROKER_GUIDES (components/import/BrokerInstructions.jsx),
// de donde la landing saca los pasos de descarga. Va como texto, no importado: la
// prueba de las landings lo usa para mirar que cada página muestre los pasos de SU guía.
export const GUIAS_DE_BROKERS = [
  { to: '/brokers/cocos', nombre: 'Cocos Capital', guia: 'cocos' },
  { to: '/brokers/iol', nombre: 'IOL', guia: 'iol' },
  { to: '/brokers/balanz', nombre: 'Balanz', guia: 'balanz' },
  { to: '/brokers/bull-market', nombre: 'Bull Market', guia: 'bullmarket' },
  { to: '/brokers/ppi', nombre: 'PPI', guia: 'ppi' },
  { to: '/brokers/binance', nombre: 'Binance', guia: 'binance' },
]

// Los links a las otras landings de broker, para «También te puede interesar».
export function otrasGuiasDeBrokers(desde) {
  return GUIAS_DE_BROKERS
    .filter(g => g.to !== desde)
    .map(g => ({ to: g.to, label: `Tu cartera de ${g.nombre}` }))
}
