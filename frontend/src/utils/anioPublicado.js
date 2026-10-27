// anioPublicado — qué número y qué veredictos muestra la tarjeta de UN año.
// ═══════════════════════════════════════════════════════════════════════════
// `/api/reports/years` manda, por año, el número del año entero (`pct`, con
// `vs_sp500_pct` y `vs_inflation_pct`) y, cuando el año entero no se puede medir,
// el TRAMO que sí (`parcial_pct`, "desde el 31 de enero", con `parcial_*`).
//
// ⚠️ LA ELECCIÓN SE HACE ACÁ, UNA VEZ, PARA LAS DOS PANTALLAS. El inicio
// (`YearReturnLine`) y Reportes (`PerformanceCalendar`) elegían cada uno por su
// cuenta, y los dos escribieron `vsInfl = parcial ? null : …`: en el tramo
// parcial mostraban "vs el S&P 500 +1,5 pp" y callaban la inflación. El usuario
// la buscó en "¿Le ganás a las alternativas?", que mide toda su historia, y leyó
// "le gano al S&P pero le pierdo a la inflación" como un error. Ahora el backend
// mide los dos veredictos del tramo (`builder.tramo_parcial_del_anio`) y esta
// función los entrega juntos: el número y sus dos veredictos salen siempre del
// mismo tramo.
//
// El modo (certero / estimado) no se decide acá: el pedido ya lo lleva
// (`useReportYears`) y el backend mide el número y los veredictos con él.

import { pctTxt } from './format'

/**
 * @param {object|null} resumen  una fila de `/api/reports/years`
 * @returns {{ parcial, pct, desde, vsSp, vsInfl, retornoArs, inflacion, motivoInfl } | null}
 *   `desde` sólo en el tramo parcial (la fecha desde la que corre el número).
 *   `motivoInfl`: por qué no hay veredicto contra la inflación, cuando hay número
 *   y no se pudo comparar (lo redacta el servidor).
 */
export function anioPublicado(resumen) {
  if (!resumen) return null
  const parcial = resumen.pct == null && resumen.parcial_pct != null
  if (parcial) {
    return {
      parcial: true,
      pct: resumen.parcial_pct,
      desde: resumen.parcial_desde ?? null,
      vsSp: resumen.parcial_vs_sp500_pct ?? null,
      vsInfl: resumen.parcial_vs_inflation_pct ?? null,
      retornoArs: resumen.parcial_retorno_ars_pct ?? null,
      inflacion: resumen.parcial_inflation_pct ?? null,
      motivoInfl: resumen.parcial_vs_inflation_motivo ?? null,
    }
  }
  return {
    parcial: false,
    pct: resumen.pct ?? null,
    desde: null,
    vsSp: resumen.vs_sp500_pct ?? null,
    vsInfl: resumen.vs_inflation_pct ?? null,
    retornoArs: resumen.retorno_ars_pct ?? null,
    inflacion: resumen.inflation_pct ?? null,
    motivoInfl: resumen.vs_inflation_motivo ?? null,
  }
}

// La aclaración del veredicto contra la inflación cuando se mira en DÓLARES: la
// resta se hace en pesos (`twr.vs_inflacion_ar`), con un retorno que no está en
// pantalla, así que el globo dice cuál. Sin esto, la cuenta que el usuario puede
// hacer con lo que ve no le da. En pesos no hace falta: el número de la tarjeta
// ya es el que se restó. Una sola redacción para las dos pantallas (el inicio
// escribía "12,34 %" con su propio formato y Reportes "12,34%").
export function detalleVsInflacion(anio, enPesos) {
  if (enPesos || !anio || anio.retornoArs == null || anio.inflacion == null) return null
  return `Se compara en pesos: tu cartera hizo ${pctTxt(anio.retornoArs, 2)} en pesos `
    + `y la inflación ${pctTxt(anio.inflacion, 1)}`
}
