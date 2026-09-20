// Broker que crea la FOTO de tenencia según el formato del export de movimientos.
// Un solo lugar: lo usan el asistente individual (ImportWizard) y la tanda del
// asesor (utils/tandaImport). Si sumás un broker con foto, va acá.
export const TENENCIA_BROKER_BY_FORMAT = {
  bullmarket: 'Bull Market',
  cocos: 'Cocos',
  ppi: 'PPI',
  ieb: 'IEB',
  iol: 'IOL',
  inviu: 'inviu',
  // La plataforma Balanz tiene 3 exports (balanz=Órdenes, balanz_movimientos,
  // balanz_resultados) y el wizard arranca en el PRIMERO (balanz). Todos crean el
  // broker 'Balanz', así que mapeamos los tres → la foto se aplica bien sin importar
  // cuál export quedó seleccionado.
  balanz: 'Balanz',
  balanz_movimientos: 'Balanz',
  balanz_resultados: 'Balanz',
  // Balanz Internacional = plataforma/broker aparte (USD). Su foto de tenencia
  // (Resumen de Cuenta Internacional) es un follow-up; el mapeo queda listo.
  balanz_internacional: 'Balanz Internacional',
}
