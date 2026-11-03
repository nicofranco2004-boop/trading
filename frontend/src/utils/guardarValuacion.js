// guardarValuacion — la regla de lo que se GUARDA calculado con precios: la
// foto diaria (POST /snapshots, Dashboard) y el P&L no realizado del mes
// (/monthly/sync-unrealized, que escriben el Dashboard y el resumen mensual).
//
// La regla: con precios — coberturaDePrecios ≥ COBERTURA_MINIMA (utils/valuation,
// el umbral del cron). El resumen mensual guardaba P&L 0 con /prices caído
// mientras el Dashboard lo chequeaba (revisión 2026-10-02).
//
// Y lo guardado vive al dólar MEP, mires el que mires: el P&L se CALCULA al MEP
// en los dos escritores (no se saltea en CCL: ningún proceso del servidor
// escribe este campo, y quien mira siempre en CCL quedaba con el mes al costo).
// La foto diaria sí se saltea en CCL (Dashboard): el cron del backend la saca
// igual al MEP cada noche.
//
// El P&L se escribe SOLO por guardarPnlNoRealizado, que aplica la regla adentro:
// un escritor nuevo no puede olvidársela (lo vigila coberturaEscritores.test.js).
// Y los dos salen por utils/enviosConDueno, con el dueño de los datos.

import { COBERTURA_MINIMA } from './valuation'
import { leerDe, guardarDe } from './almacen'
import { sigueSiendoDe } from './duenoDeLaPestana'
import { ENVIOS, enviarDe } from './enviosConDueno'
import { CATALOGO } from './catalogoDelAlmacen'

export function sePuedeGuardar({ cobertura }) {
  return cobertura >= COBERTURA_MINIMA
}

// La marca de «ya guardé la foto de hoy» (una por día): de la persona Y de la
// cuenta DE LOS DATOS (utils/duenoDeLaPestana). Era una sola para todo el
// navegador: el asesor que abría el inicio del cliente 2 dejaba al 3 sin su foto
// ese día, y tras una sesión que vence, el siguiente se quedaba sin la suya.
// `dueno` es el de los datos del inicio (useDuenoDeLosDatos); la puerta
// (utils/almacen.guardarDe) no marca para un dueño que ya no es el de la
// pestaña, ni sin nadie logueado.
export function yaSeGuardoLaFotoDeHoy(dueno, hoy) {
  return !dueno || leerDe(CATALOGO.fotoDelDia, dueno) === hoy
}

export function marcarFotoDeHoy(dueno, hoy) {
  return guardarDe(CATALOGO.fotoDelDia, dueno, hoy)
}

// filas: [{ broker, pnl }] (incluida la fila 'global'), calculadas AL MEP con
// los datos de `dueno` (useDuenoDeLosDatos de la pantalla). Una fila sin número
// (NaN, null) no se guarda: antes `Number(pnl || 0)` la convertía en un 0
// guardado. Sale por utils/enviosConDueno: si la pestaña ya está en otra cuenta,
// no se manda (la ganancia del cliente 2 pisaba el mes del 3, re-test a ciegas
// 3). Devuelve si se pudo mandar. `enviar` es para las pruebas.
export async function guardarPnlNoRealizado(dueno, filas, condiciones, enviar = enviarDe) {
  if (!sePuedeGuardar(condiciones) || !sigueSiendoDe(dueno)) return false
  const validas = filas.filter(({ pnl }) => typeof pnl === 'number' && Number.isFinite(pnl))
  await Promise.all(validas.map(({ broker, pnl }) =>
    enviar(ENVIOS.pnlNoRealizado, dueno, { broker, pnl_unrealized_usd: +pnl.toFixed(4) }).catch(() => {})))
  return true
}
