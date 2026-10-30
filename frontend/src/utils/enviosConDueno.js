// enviosConDueno — LA ÚNICA SALIDA de lo que la pantalla manda SOLA al servidor
// con números calculados a partir de los datos de una cuenta: la foto del día,
// la ganancia no realizada del mes, el cierre automático del mes anterior y el
// mes nuevo. No son clics de la persona: salen solos, al cargar o cada 90 s.
//
// 🔴 POR QUÉ (re-test a ciegas 3, 30/10). El asesor con el inicio del cliente 2
// abierto en una pestaña entraba al cliente 3 en otra, y la pestaña vieja
// mandaba cada 90 s la ganancia no realizada del 2 a nombre del 3
// (/monthly/sync-unrealized): el servidor pisaba el mes en curso y el capital
// final del 3 (5.010 donde el real era 20.043). Lo mismo entre Ana y Bruno con
// dos pestañas. Es el eslabón que utils/almacen cerró para el navegador —el
// número es de una cuenta y el pedido sale con la cuenta que tenga la pestaña
// AHORA— del lado del servidor: api.js pone el cliente de la pestaña en cada
// pedido, y la cookie es de quien esté logueado.
//
// Por eso `enviarDe` recibe el dueño DE LOS DATOS (useDuenoDeLosDatos, el de
// cuando la pantalla se montó y pidió sus datos) y NO manda si ya no es el de la
// pestaña: rechaza con `CuentaCambiada`, sin pedido. Sólo acepta los envíos de
// la lista ENVIOS, cada uno con su porqué; el guardián
// (__guards__/envios-con-dueno.test.js) se pone rojo si alguien manda esas
// rutas por otro lado.
//
// api.js arma el encabezado del cliente en el mismo instante en que se lo
// llama, sin esperas en el medio: lo que se mira acá es lo que sale.

import { api } from './api'
import { sigueSiendoDe } from './duenoDeLaPestana'

const e = (o) => Object.freeze(o)

export const ENVIOS = Object.freeze({
  fotoDelDia: e({ metodo: 'post', ruta: '/snapshots',
    porque: 'el inicio guarda una vez por día el valor de la cartera a precios de hoy' }),
  pnlNoRealizado: e({ metodo: 'post', ruta: '/monthly/sync-unrealized',
    porque: 'el inicio (cada 90 s) y el resumen mensual guardan la ganancia no realizada del mes en curso, por broker y el total' }),
  cierreDelMes: e({ metodo: 'put', ruta: '/monthly/',
    porque: 'al cambiar de mes, el resumen mensual cierra solo el mes anterior (capital final sin la ganancia no realizada)' }),
  mesNuevo: e({ metodo: 'post', ruta: '/monthly',
    porque: 'y abre el mes nuevo con el capital de cierre del anterior' }),
})

/** El envío no salió: los datos son de una cuenta y la pestaña ya está en otra. */
export class CuentaCambiada extends Error {
  constructor(envio) {
    super(`No se mandó ${envio?.ruta}: la pestaña ya no está en la cuenta de esos datos.`)
    this.name = 'CuentaCambiada'
    this.cuentaCambiada = true
  }
}

const estaEnLaLista = (envio) => Object.values(ENVIOS).includes(envio)

/**
 * Manda `cuerpo` por `envio` (una entrada de ENVIOS) SÓLO si `dueno` —el dueño
 * de los datos con que se calculó— sigue siendo el de la pestaña. Si no,
 * rechaza con CuentaCambiada y no sale ningún pedido. `resto` sigue a la ruta
 * (el número del mes en el cierre).
 */
export function enviarDe(envio, dueno, cuerpo, resto = '') {
  if (!estaEnLaLista(envio)) throw new Error('enviosConDueno: ese envío no está en ENVIOS')
  if (!sigueSiendoDe(dueno)) return Promise.reject(new CuentaCambiada(envio))
  return api[envio.metodo](envio.ruta + resto, cuerpo)
}
