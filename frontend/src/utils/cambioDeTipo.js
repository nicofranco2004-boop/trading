// Cambiar el activo de una posición ya cargada: CEDEAR ↔ acción.
//
// El CEDEAR de IREN y la acción IREN tienen el MISMO código. Lo único que los
// separa es el tipo que se guarda (`asset_type`), y es lo que decide con qué
// precio se valúa: el CEDEAR con el de la Bolsa de Buenos Aires (.BA), la acción
// con el de Nueva York. Al editar, el buscador devolvía sólo el código: el tipo
// viejo viajaba intacto y el activo se seguía valuando como CEDEAR (reporte real,
// 2026-10-20).
//
// Una sola definición para la edición de un lote (PositionFormModal) y la de la
// posición entera (EditGroupModal), en escritorio y celular.
import { CATEGORY_ASSET_TYPE } from './tickers'
import { admiteDosMonedas, cuentaDe } from './pataDeLaMoneda'

// Lo que cotiza afuera (Nueva York): la acción y el ETF de EE.UU.
const DEL_EXTERIOR = new Set(['stocks', 'etfs'])

/** El tipo a guardar según lo que se eligió en el buscador; null si no dice uno. */
export function tipoDeLaEleccion(eleccion) {
  return CATEGORY_ASSET_TYPE[eleccion?.categoria] || null
}

/**
 * Qué decirle a la persona cuando lo elegido cambia el tipo de la posición.
 * Devuelve { tono: 'info' | 'aviso', texto } o null si no hay nada que decir.
 *
 * El aviso de la cuenta argentina existe porque ahí el tipo NO mueve el precio:
 * todo se valúa con el de BYMA (es lo que ofrece el alta en esas cuentas, donde
 * «AAPL acción» y el CEDEAR son una sola opción). Elegir la acción ahí y guardar
 * sin enterarse es exactamente el «no me cambia el precio» del reporte.
 */
export function avisoDeCambioDeTipo({ antes, eleccion, broker, brokers }) {
  const despues = tipoDeLaEleccion(eleccion)
  const previo = String(antes || '').toUpperCase()
  if (!despues || despues === previo) return null
  const delExterior = DEL_EXTERIOR.has(eleccion.categoria)
  const cual = eleccion.categoria === 'etfs' ? 'el ETF' : 'la acción'
  const pron = eleccion.categoria === 'etfs' ? 'lo' : 'la'

  if (delExterior && admiteDosMonedas(broker, brokers)) {
    return {
      tono: 'aviso',
      texto: `${cuentaDe(broker, brokers)} es una cuenta argentina: ahí lo que se compra es `
        + `el CEDEAR, y Rendi lo valúa con el precio de la Bolsa de Buenos Aires aunque `
        + `elijas ${cual}. Si ${pron} compraste en un broker del exterior, carga${pron} `
        + `en ese broker.`,
    }
  }
  if (delExterior && previo === 'CEDEAR') {
    return {
      tono: 'info',
      texto: `Pasa de CEDEAR a ${cual}: al guardar se valúa con su precio en Nueva York. `
        + `Revisá el precio de compra y la cantidad — un CEDEAR es una parte de la acción, `
        + `así que los números del CEDEAR no sirven tal cual.`,
    }
  }
  if (despues === 'CEDEAR') {
    return {
      tono: 'info',
      texto: 'Pasa a CEDEAR: al guardar se valúa con su precio en la Bolsa de Buenos Aires. '
        + 'Revisá el precio de compra y la cantidad — un CEDEAR es una parte de la acción.',
    }
  }
  return null
}

/**
 * La moneda del lote después de elegir. Una acción o un ETF de EE.UU. en un
 * broker del exterior se compra en dólares: si el lote estaba marcado en pesos
 * (un CEDEAR comprado en pesos), seguiría valuándose por su precio en pesos (.BA)
 * aunque el tipo diga acción. En una cuenta argentina no se toca: ahí la moneda
 * es la de la pata, y el aviso de arriba explica el resto.
 */
export function monedaAlCambiarDeTipo({ moneda, eleccion, broker, brokers }) {
  if (!DEL_EXTERIOR.has(eleccion?.categoria)) return moneda
  if (admiteDosMonedas(broker, brokers)) return moneda
  return String(moneda || '').toUpperCase() === 'ARS' ? 'USD' : moneda
}
