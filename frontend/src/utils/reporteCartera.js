// reporteCartera — los datos del reporte en PDF de la cartera (Análisis).
// ═══════════════════════════════════════════════════════════════════════════
// No calcula NADA nuevo: recibe lo que la pantalla de Análisis ya calculó
// (el KPI "Acumulado", las mismas porciones de las tortas, los mismos
// contribuyentes de "Qué explica tu resultado") y lo pasa a un objeto plano
// que dibuja components/reporte/ReporteCartera. Si el reporte recalculara algo
// por su lado, el PDF podría decir otro número que la pantalla.
//
// `mostrarMontos` es la respuesta del usuario a la pregunta de PreguntaMontos:
// en false, el objeto que sale no tiene NINGUNA cifra de plata (ni montos por
// porción, ni total, ni resultado por activo), sólo porcentajes.

import { agruparPorciones } from '../components/CompositionDonut'
import { pctConSigno, fechaDeHoy } from './shareCard'

const ticker = (t) => String(t || '').replace(/^FCI:/, '')

/**
 * @param {object}   a
 * @param {Function} a.fmt            USD → texto en la moneda de la vista (el `amt` de Análisis)
 * @param {boolean}  a.mostrarMontos
 * @param {'USD'|'ARS'} a.moneda
 * @param {string}   a.periodo        "Último año"
 * @param {number}   a.patrimonio     total en USD (el de la torta por activo)
 * @param {{carteraPct:number, benchPct:number|null, benchLabel:string, serie:Array}|null} a.rendimiento
 * @param {{currentPct:number, maxPct:number}|null} a.drawdown
 * @param {Array<{titulo:string, items:Array, maxSlices?:number, minSlicePct?:number}>} a.distribuciones
 * @param {Array<{asset:string, pnl:number}>} a.ganadores
 * @param {Array<{asset:string, pnl:number}>} a.perdedores
 * @param {Function} a.fmtEnVista     formatea un monto que YA está en la moneda de
 *                                    la vista (el `amtEnVista` de Análisis)
 * @param {{aportado:number, mercado:number, valorHoy:number}|null} a.capital
 *        lo de "Atribución del crecimiento", en la moneda de la vista
 * @param {{pnl:number, pct:number}|null} a.noRealizado
 *        el de pnlNoRealizado (encabezado de Cartera), en la moneda de la vista;
 *        `pct` es fracción (0,12 = 12%)
 */
export function armarReporte({
  fmt = (v) => String(v), mostrarMontos = false, moneda = 'USD', periodo = '',
  patrimonio = null, rendimiento = null, drawdown = null,
  distribuciones = [], ganadores = [], perdedores = [], now = new Date(),
  fmtEnVista = fmt, capital = null, noRealizado = null,
}) {
  const monto = (v) => (mostrarMontos && Number.isFinite(v) ? fmt(v) : null)
  const montoConSigno = (v) => {
    if (!mostrarMontos || !Number.isFinite(v)) return null
    return `${v >= 0 ? '+' : '−'}${fmt(Math.abs(v))}`
  }

  let rend = null
  if (rendimiento && Number.isFinite(rendimiento.carteraPct)) {
    const { carteraPct, benchPct, benchLabel } = rendimiento
    const hayBench = Number.isFinite(benchPct)
    const dif = hayBench ? carteraPct - benchPct : null
    rend = {
      cartera: pctConSigno(carteraPct),
      carteraPositiva: carteraPct >= 0,
      bench: hayBench ? pctConSigno(benchPct) : null,
      benchLabel,
      diferencia: hayBench ? `${dif >= 0 ? '+' : '−'}${Math.abs(dif).toFixed(1).replace('.', ',')} puntos` : null,
      ganaAlBench: hayBench ? dif >= 0 : null,
      serie: (rendimiento.serie || []).filter(p => p && Number.isFinite(p.ts)),
    }
  }

  // Aportado / mercado: son montos y nada más (el "% del cambio" de la
  // pantalla no se lee solo). Sin montos, la sección no va.
  const plata = mostrarMontos && capital && Number.isFinite(capital.aportado) && Number.isFinite(capital.mercado) ? {
    aportado: fmtEnVista(capital.aportado),
    mercado: fmtEnVista(capital.mercado, { signed: true }),
    mercadoPositivo: capital.mercado >= 0,
    valorHoy: Number.isFinite(capital.valorHoy) ? fmtEnVista(capital.valorHoy) : null,
  } : null

  // El no realizado SÍ va sin montos: su % es el de Cartera.
  const nr = noRealizado && Number.isFinite(noRealizado.pnl) ? {
    monto: mostrarMontos ? fmtEnVista(noRealizado.pnl, { signed: true }) : null,
    pct: pctConSigno((noRealizado.pct || 0) * 100),
    positivo: noRealizado.pnl >= 0,
  } : null

  return {
    fecha: fechaDeHoy(now),
    plata,
    noRealizado: nr,
    moneda,
    enMoneda: moneda === 'ARS' ? 'en pesos' : 'en dólares',
    periodo,
    mostrarMontos,
    patrimonio: monto(patrimonio),
    rendimiento: rend,
    drawdown: drawdown && Number.isFinite(drawdown.currentPct) ? {
      actual: pctConSigno(drawdown.currentPct),
      maximo: Number.isFinite(drawdown.maxPct) ? pctConSigno(drawdown.maxPct) : null,
    } : null,
    distribuciones: distribuciones
      .map(d => ({
        titulo: d.titulo,
        porciones: agruparPorciones(d.items || [], {
          ...(d.maxSlices != null ? { maxSlices: d.maxSlices } : {}),
          ...(d.minSlicePct != null ? { minSlicePct: d.minSlicePct } : {}),
        }).map(p => ({ label: p.label, color: p.color, pct: p.pct, monto: monto(p.value) })),
      }))
      .filter(d => d.porciones.length > 0),
    ganadores: ganadores.map(x => ({ label: ticker(x.asset), resultado: montoConSigno(x.pnl) })),
    perdedores: perdedores.map(x => ({ label: ticker(x.asset), resultado: montoConSigno(x.pnl) })),
  }
}
