import { lookupHistoricalDolar } from './fx'
import { hoyISO } from './fecha'

// ⚠️ DOS PREGUNTAS DISTINTAS, DOS PREDICADOS DISTINTOS. Colapsarlas es el error
// que hizo volver este bug once veces, y las dos direcciones del error ya se
// vivieron: separarlas POR FILA hizo polvo la curva (ronda 9), unificarlas POR
// SERIE devolvió el pico fabricado (ronda 10).
//
//   ¿se puede DIBUJAR?     → por SERIE (continuidad). Una foto intradía está
//                            valuada a mercado (posiciones × precio): sostiene
//                            la línea. Lo único que nunca entra es la fila que
//                            el import FABRICA copiando la cadena contable.
//   ¿puede ser PICO o      → por FILA (hecho de medición). Una intradía NO es un
//     DENOMINADOR?           cierre: sostiene la línea pero no fija un máximo ni
//                            sirve de base de un período.
//
// Es el mismo contrato que el backend ya escribió en twr.py (BASE_MERCADO vs
// ACEPTA_LINEA) y que /api/snapshots ya manda por fila: `clase`, `base`, `apto`.
// Acá sólo se LEE — si estos predicados y twr.py dicen cosas distintas sobre la
// misma fila, uno de los dos está mal.
const ACEPTA_LINEA = ['medicion', 'reconstruido', 'intradia']

/**
 * esApto — ¿esta fila puede ser PICO, BORDE o DENOMINADOR?
 *
 * ⚠️ NO USAR `sintetico` PARA DECIDIR SI DIBUJAR. `/api/snapshots` lo define
 * como `sintetico = not apto` (main.py:5020), o sea colapsa las dos preguntas:
 * una foto INTRADIA sale `sintetico=true` sin ser fabricada — está medida a
 * mercado. `sintetico` sólo sobrevive como fallback para un backend viejo que
 * todavía no manda `apto`.
 */
export function esApto(s) {
  if (!s) return false
  return s.apto !== undefined ? !!s.apto : !s.sintetico
}

/**
 * BORDE_MAX_LAG_DIAS / esBordeFresco — ¿este cierre puede ABRIR el período?
 *
 * Espejo exacto de `reporting/builder.py::_border_is_fresh` y de su constante
 * `_BORDER_MAX_LAG_DAYS`. **Mismo número a propósito: si se separan, uno de los
 * dos está mal**, y `tests/borde-fresco.test.js` lo verifica leyendo el archivo
 * de Python — porque durante meses el número estuvo en tres lugares del repo y
 * faltó justo en el más mirado.
 *
 * QUÉ PASABA SIN ESTO. `computeReturnDelta` tomaba como base "el cierre más
 * reciente anterior al mes", por viejo que fuera, y si no había ninguno caía al
 * MÁS ANTIGUO de la serie. Medido sobre un usuario que se ausentó en junio y
 * volvió el 10 de septiembre: el KPI "Este mes" del Dashboard publicaba
 * **+35,24 % / US$ 3.700** midiendo desde el 20 de junio —79 días— mientras
 * `/mensual` y `/reportes` no publicaban nada y el mes real era **+2,90 %**.
 * El propio helper devolvía `dayDiff: 79`: el dato para no publicarlo estaba
 * calculado y nadie lo miraba.
 *
 * Se rechazan las DOS puntas del rango a propósito, igual que el backend:
 *   · lag > 5   → cierre viejo: mete semanas de mercado ajeno adentro del mes.
 *   · lag < 0   → el "cierre" cae DENTRO del período: no lo abre, lo parte.
 */
export const BORDE_MAX_LAG_DIAS = 5

export function esBordeFresco(fechaCierre, inicioPeriodo, maxLagDias = BORDE_MAX_LAG_DIAS) {
  if (!fechaCierre || !inicioPeriodo) return false
  const a = Date.parse(`${String(inicioPeriodo).slice(0, 10)}T00:00:00Z`)
  const b = Date.parse(`${String(fechaCierre).slice(0, 10)}T00:00:00Z`)
  if (Number.isNaN(a) || Number.isNaN(b)) return false
  const lag = Math.round((a - b) / 86_400_000)
  return lag >= 0 && lag <= maxLagDias
}

/**
 * esDibujable — ¿este punto entra a la línea?
 *
 * Con `clase` (backend actual) la respuesta es la lista de continuidad. Sin
 * `clase` (backend anterior a este cambio) el único dato disponible es `apto`,
 * y ahí se degrada al lado conservador: dibuja menos, nunca de más.
 */
export function esDibujable(s) {
  if (!s) return false
  if (s.clase !== undefined && s.clase !== null) return ACEPTA_LINEA.includes(s.clase)
  return esApto(s)
}

// Cuánto de la base de un período puede venir de capital CONTABLE sin medir
// antes de que el resultado deje de ser publicable.
//
// ⚠️ NO ES UN NÚMERO NUEVO: es el mismo `_UNMEASURED_BASE_TOL` de
// `backend/reporting/builder.py`, con la misma fórmula. Se porta en vez de
// inventar un criterio nuevo justamente porque el defecto de fondo de todo esto
// fue tener la misma regla escrita distinto en cada lector. Si estos dos valores
// se separan, uno de los dos está mal.
const _TOL_BASE_SIN_MEDIR = 0.10

/**
 * baseIncomparable — ¿la resta `fin(mercado) − inicio` mide el período, o mide
 * la brecha entre dos formas de medir?
 *
 * Incomparable cuando el inicio NO salió de un cierre medido Y ADEMÁS pesa lo
 * suficiente como para torcer el resultado.
 *
 * La tolerancia existe por el ONBOARDING y sacarla sería un error: el primer
 * período de un usuario arranca en la cadena contable y su número es correcto
 * igual, porque cuando el período está dominado por dinero NUEVO los flujos son
 * hechos registrados, no estimaciones, y el error que puede meter la cadena está
 * acotado. Lo que el guard caza es el otro caso: el 452, donde la base contable
 * es el 99% de todo y la resta publica −65,82% con cero operaciones.
 */
/**
 * diagnosticoSinMedicion — POR QUÉ no hay número, con las palabras del caso.
 *
 * ⚠️ EXISTE PORQUE `null` NO ALCANZA. `computeReturnDelta` devuelve `null` por dos
 * motivos que para el usuario son opuestos: "todavía no cargaste nada" y "cargaste
 * 57 fotos pero ninguna es una medición a precio real". La UI las mostraba igual
 * —una card que desaparece, un "—" pelado, o peor: *"Cargá tus snapshots diarios"*,
 * que le pide a alguien con 57 snapshots que haga lo que ya hizo—.
 *
 * Medido en la copia de producción del 16/08: 174 usuarios se quedaban sin
 * sparkline y 168 de ellos TENÍAN ≥2 snapshots.
 *
 * Devuelve `null` cuando sí se puede medir (o cuando no hay nada y el vacío de
 * siempre es el correcto). Si no, devuelve el material para escribir la frase.
 */
export function diagnosticoSinMedicion(snapshots) {
  const filas = (snapshots || []).filter(s => s && s.date)
  if (filas.length === 0) return null          // cuenta vacía: el vacío de siempre
  const medidas = filas.filter(esApto)
  if (medidas.length >= 2) return null         // hay con qué medir
  const fechas = medidas.map(s => String(s.date).slice(0, 10)).sort()
  return {
    filas: filas.length,
    medidas: medidas.length,
    primeraMedicion: fechas[0] || null,
  }
}

/**
 * textoSinMedicion — la frase única. Un solo lugar donde se elige cómo se dice,
 * para que el Dashboard, el home mobile y Reportes no inventen tres versiones.
 */
export function textoSinMedicion(diag) {
  if (!diag) return null
  if (diag.medidas === 0) {
    return `Todavía no medimos tu cartera a precio de mercado. Las ${diag.filas} fotos que tenemos salen de tu import —son tu contabilidad, no una medición—, y compararlas contra el valor de hoy no da tu rendimiento.`
  }
  return `Tenemos una sola medición a precio de mercado (${diag.primeraMedicion}). Para calcular un rendimiento hacen falta dos cierres medidos.`
}

export function baseIncomparable(inicioEsMedido, inicioValor, depositos = 0, retiros = 0) {
  if (inicioEsMedido || !(inicioValor > 0)) return false
  const baseTotal = inicioValor + Math.max(0, (depositos || 0) - (retiros || 0))
  if (!(baseTotal > 0)) return true
  return (inicioValor / baseTotal) > _TOL_BASE_SIN_MEDIR
}

/**
 * buildPortfolioValueSeries
 * ─────────────────────────
 * Returns [{ date, label, valueUsd, netDeposited }, ...] from snapshots,
 * optionally filtered by `days`. Used by the Dashboard portfolio evolution
 * chart with the 1D / 1W / 1M / 6M / 1Y / MAX selector.
 *
 * If a `liveValue` is provided AND the latest snapshot is older than today
 * (or absent for today), we append a synthetic "today" point so the chart
 * always shows the current portfolio value as the rightmost data point.
 *
 * @param {Array}  snapshots  [{ date, total_value, total_invested, net_deposited }]
 * @param {number} days       window in days (null = all)
 * @param {number} liveValue  optional live portfolio value (USD) to append as today's point
 * @param {number} liveNet    optional live net_deposited (USD) for today's point
 *
 * @returns {Array<{ date, label, valueUsd, netDeposited }>}
 */
/**
 * convertSeriesToArs — convierte cada punto de una serie USD a ARS usando
 * FX histórico per-punto (Phase C audit fix C1).
 *
 * Prioridad de FX por punto:
 *   1. punto.fxToUsdBlue stampeado en el snapshot original (más auténtico)
 *   2. getFxForDate(punto.date) — lookup en la historia de blue
 *
 * Retorna una nueva serie con `valueUsd` y `netDeposited` convertidos a ARS
 * (los nombres de las keys se preservan por compat con el chart que ya las usa),
 * y agrega `_fxUsed` para inspección/transparencia (chart muestra el TC blue
 * usado en el tooltip).
 *
 * @param {Array} series — output de buildPortfolioValueSeries (cada item con
 *                          { date, valueUsd, netDeposited, fxToUsdBlue? })
 * @param {(dateIso: string) => number} getFxForDate — resolver del FX por fecha
 * @returns {Array} serie con valores convertidos a ARS
 */
export function convertSeriesToArs(series, getFxForDate) {
  if (!Array.isArray(series)) return []
  return series.map(p => {
    const stamped = p.fxToUsdBlue
    const fx = (stamped && stamped > 0)
      ? stamped
      : (typeof getFxForDate === 'function' ? getFxForDate(p.date) : null)
    const safeFx = (fx && fx > 0) ? fx : 1  // último fallback: no convertir
    return {
      ...p,
      valueUsd: p.valueUsd * safeFx,
      netDeposited: p.netDeposited * safeFx,
      _fxUsed: safeFx,
    }
  })
}

export function buildPortfolioValueSeries(snapshots, days = null, liveValue = null, liveNet = null, liveFx = null) {
  // ⚠️ FILTRAR ACÁ ES LO QUE ARREGLA EL EJE Y, EL CHIP Y EL ANCLA — los tres
  // consumidores a dos saltos que no nombran `snapshots` en ninguna línea.
  // Medido sobre la serie real del 452: sin este filtro el punto más alto de la
  // curva de 30 días es una fila `source='import'` de 197.297,51 que fija el
  // techo del eje (`Dashboard.jsx:1018`), el chip pegado al gráfico publica
  // −65,93% (`Dashboard.jsx:551`) y el home mobile rotula literalmente
  // "Hace 30d · US$196.631" contra "Hoy · US$67.214". Nadie perdió ese dinero:
  // es el escalón entre medir al costo y medir a mercado.
  //
  // Y VA ANTES DEL RECORTE POR VENTANA, no después: el ancla del período
  // (más abajo) hace PREPEND del último punto anterior al corte, así que con el
  // filtro puesto después, la fila al costo se re-inyectaba igual aunque
  // quedara fuera de los 30 días. Acortar la ventana no la saca; sacarla del
  // universo, sí.
  const dibujables = (snapshots || []).filter(esDibujable)
  const sorted = [...dibujables].sort((a, b) => a.date < b.date ? -1 : 1)
  const points = sorted.map(s => ({
    date: s.date,
    label: s.date.slice(5), // MM-DD
    valueUsd: +(s.total_value || 0),
    netDeposited: +(s.net_deposited || s.total_invested || 0),
    // Phase C: fx_to_usd_blue stampeado al momento del snapshot. Cuando
    // el toggle global está en ARS, el chart usa este FX (no el actual)
    // para mostrar la realidad histórica. NULL en filas legacy → frontend
    // hace fallback al fx histórico de useFxHistory, después al tcValuacion actual.
    fxToUsdBlue: s.fx_to_usd_blue != null ? +s.fx_to_usd_blue : null,
  }))

  // Append "today" if live value supplied and last snapshot isn't already today
  const today = hoyISO()
  if (liveValue != null && (points.length === 0 || points[points.length - 1].date !== today)) {
    points.push({
      date: today,
      label: today.slice(5),
      valueUsd: +liveValue,
      netDeposited: liveNet != null ? +liveNet : (points[points.length - 1]?.netDeposited ?? +liveValue),
      fxToUsdBlue: liveFx != null ? +liveFx : null,
    })
  }

  if (days != null && days > 0 && points.length > 0) {
    const cutoff = Date.now() - days * 86400000
    const filtered = points.filter(p => new Date(p.date).getTime() >= cutoff)

    // AUDIT FOLLOW-UP (2026-05-31): siempre PREPEND el último snapshot
    // ANTES del cutoff como ancla del período. Sin este anchor, si el user
    // no entró a Rendi durante varios días al inicio del período, el chart
    // tomaba como `first.value` el primer snapshot DENTRO de la ventana
    // (ej: 22 de mayo) y mostraba un delta más chico que el KPI "Este mes"
    // (que sí ancla en el primer día calendar del mes). Resultado: 3
    // números distintos para "rendimiento del mes" en distintas pantallas.
    // Con el anchor, chart y KPI convergen al mismo número.
    const beforeCutoff = points.filter(p => new Date(p.date).getTime() < cutoff)
    const anchor = beforeCutoff.length > 0 ? beforeCutoff[beforeCutoff.length - 1] : null

    if (filtered.length >= 2) {
      return anchor ? [anchor, ...filtered] : filtered
    }
    if (filtered.length === 1 && anchor) {
      return [anchor, filtered[0]]
    }
    if (filtered.length === 1 && points.length >= 2) {
      // Sin anchor disponible (la ventana captura el primer snapshot de
      // todos los tiempos), preserve previous behavior.
      const idx = points.findIndex(p => p.date === filtered[0].date)
      if (idx > 0) return [points[idx - 1], filtered[0]]
    }
    return points.slice(-Math.max(2, filtered.length))
  }

  return points
}


/**
 * netDepositedOf — baseline para Total Return de un snapshot.
 * Phase 6+ guarda `net_deposited`; snapshots legacy lo tienen en 0 → fallback
 * a `total_invested` (cost basis) para no romper el cálculo. Misma convención
 * que buildPortfolioValueSeries / buildEvolutionFromSnapshots.
 */
function netDepositedOf(s) {
  // ⚠️ AUSENTE ≠ NEGATIVO. El `> 0` de antes leía un `net_deposited` NEGATIVO
  // —retiros netos por encima de los aportes, un dato perfectamente legítimo—
  // como si fuera un hueco, y caía a `total_invested`, que es COSTO. O sea
  // volvía a meter la base contable por la ventana, dentro del helper que
  // justamente existe para no mezclarlas.
  //
  // Medido en la copia de producción del 16/08: 4.744 filas (11,7%) en 192
  // usuarios tienen `net_deposited < 0`. En el 452 son las DOS puntas
  // (−1.789,39 y −5.726,38), así que el fallback disparaba de los dos lados.
  //
  // La columna es `NOT NULL DEFAULT 0`, así que el hueco real —las filas
  // anteriores a Phase 6— se escribe exactamente como 0. Ése es el único valor
  // que significa "no lo tengo"; cualquier otro, signo incluido, es un dato.
  const nd = s?.net_deposited
  return (nd != null && nd !== 0) ? nd : (s?.total_invested || 0)
}

/**
 * capitalMaximoAportado — el denominador estable del retorno total.
 *
 * EL PROBLEMA. El "+X %" del hero se calcula sobre `netDeposited`, que es
 * "lo que pusiste MENOS lo que sacaste" AL DÍA DE HOY. Ese número se achica
 * con cada retiro, y el porcentaje se infla solo:
 *
 *   pusiste 50k, sacaste 45k, hoy tenés 35k  →  30k / 5k  = +600 %
 *   pusiste 50k, sacaste 60k, hoy tenés  5k  →  denominador NEGATIVO, y el
 *                                                call site publicaba 0 %
 *
 * Ese 0 % es peor que el +600 %: no dice "no sé", dice "no ganaste nada",
 * sobre alguien que ganó.
 *
 * EL GUARD DE `realized%` DE MÁS ABAJO USABA EL PICO DE LA CARTERA
 * (`peakValueUsd * 0.8`) y copiarlo acá le rompía el número al que nunca
 * retiró: con 10k puestos y 30k de cartera el pico es 30k, y el +200 % real
 * pasaba a +25 %. Al mirarlo de cerca resultó que el equivocado era ÉL — metía
 * la ganancia no realizada en el denominador de un porcentaje sobre capital
 * aportado — así que ese guard también pasó a `denominadorAportado` y hoy el
 * pico de la cartera no lo usa nadie.
 *
 * LO QUE SÍ SIRVE es el pico del CAPITAL APORTADO, no el de la cartera: la
 * mayor cantidad de plata que el usuario llegó a tener puesta. Para el que
 * nunca retiró es exactamente `netDeposited` de hoy —el número no se mueve un
 * decimal— y para el que retiró da la base real sobre la que trabajó.
 *
 * ⚠️ NO USA `netDepositedOf`, Y ESO ES EL PUNTO. Ese helper cae a
 * `total_invested` —o sea COSTO— cuando `net_deposited` viene en 0, que es lo
 * correcto para dibujar una serie pero veneno para ESTE denominador: los
 * snapshots legacy de este repo tienen costos corruptos conocidos (el CEDEAR
 * ×1486, la comisión fantasma), y un solo `total_invested` inflado se
 * convertiría en el máximo y aplastaría el número más visible de la app.
 * Medido: con un snapshot legacy de total_invested 14.860.000, un +200 % real
 * pasaba a +0,13 %.
 *
 * Acá un `net_deposited === 0` significa "no lo tengo" (la columna es NOT NULL
 * DEFAULT 0, así es como se escribe el hueco pre-Phase 6) y se SALTEA. Si
 * todos los puntos son huecos, el máximo es el aportado de hoy — o sea, una
 * cuenta legacy se comporta exactamente como antes.
 *
 * @param snapshots        la serie histórica; sólo se miran los puntos con un
 *                         `net_deposited` medido (≠ 0)
 * @param netDepositedHoy  el aportado neto actual: es el PISO, nunca se
 *                         devuelve menos que esto
 * @param ajuste           lo que está en `netDepositedHoy` pero NO en los
 *                         snapshots (el capital de plazos fijos, que el cron
 *                         no fotografía). Se suma a cada punto histórico para
 *                         que las dos escalas sean comparables.
 */
export function capitalMaximoAportado(snapshots, netDepositedHoy = 0, ajuste = 0) {
  let max = Number.isFinite(netDepositedHoy) ? netDepositedHoy : 0
  const aj = Number.isFinite(ajuste) ? ajuste : 0
  for (const s of (snapshots || [])) {
    const medido = s?.net_deposited
    if (medido == null || medido === 0) continue   // hueco, no un aportado de 0
    const nd = medido + aj
    if (Number.isFinite(nd) && nd > max) max = nd
  }
  return max
}

/**
 * PISO_DENOMINADOR_USD — abajo de esto no se publica ningún porcentaje.
 *
 * Un aportado residual de centavos hace explotar cualquier cociente: US$3 de
 * capital con US$30 de resultado publica +1000 % y se lleva puesto el
 * "mejor/peor" de cualquier ranking. El número sale del libro del asesor
 * (`_retorno_vs_aportado` en main.py), que ya lo aplicaba.
 *
 * ⚠️ ESPEJADO en backend/twr.py. Hay un test que verifica que no diverjan.
 */
export const PISO_DENOMINADOR_USD = 100

/**
 * denominadorAportado — LA regla, una sola vez.
 *
 * El capital contra el que se mide un porcentaje: el mayor entre lo que hay
 * aportado hoy y lo máximo que se llegó a aportar. Devuelve null cuando no
 * llega al piso — null es "no lo puedo calcular", que no es lo mismo que 0.
 *
 * ── POR QUÉ ESTA Y NO LAS OTRAS TRES QUE HABÍA ──────────────────────────
 * Esta regla estaba escrita CUATRO veces en el repo con TRES criterios
 * distintos, y el mismo usuario veía números diferentes según la pantalla:
 *
 *   · el libro del asesor:  max(nd, nd_máx) con piso 100   ← ésta
 *   · la curva de acá:      max(nd, pico_de_CARTERA × 0,8)
 *   · Análisis (×2):        nd si nd ≥ 60 % del pico, si no el pico
 *
 * El pico de la CARTERA estaba mal y no es opinable: mete la ganancia NO
 * realizada adentro del denominador de un porcentaje sobre capital aportado.
 * Medido — quien aportó 10k, nunca retiró, tiene 30k y realizó 5k: publicaba
 * 20,8 % donde el número es 50 %. Con la cartera multiplicada por diez, 62,5 %
 * donde son 500 %.
 *
 * El umbral del 60 % también se va, por otro motivo: es discontinuo. Retirar
 * un dólar de más cruzaba el 60 % y el denominador saltaba de golpe, con el
 * porcentaje pegando un escalón que no corresponde a nada que haya pasado.
 * `max()` es continua y monótona.
 */
export function denominadorAportado(ndActual = 0, ndMaximo = 0, fxDelPiso = 1) {
  const a = Number.isFinite(ndActual) ? ndActual : 0
  const b = Number.isFinite(ndMaximo) ? ndMaximo : 0
  const d = Math.max(a, b)
  // ⚠️ EL PISO ESTÁ EN DÓLARES. Si los montos vienen en PESOS hay que pasar el
  // tipo de cambio: comparar 140.000 pesos contra un piso de 100 deja pasar
  // todo, y entonces el mismo usuario con US$50 aportados no ve porcentaje en
  // dólares y sí lo ve en pesos. Las dos monedas tienen que dar el mismo
  // veredicto.
  const fx = Number.isFinite(fxDelPiso) && fxDelPiso > 0 ? fxDelPiso : 1
  return d >= PISO_DENOMINADOR_USD * fx ? d : null
}

/**
 * retornoTotal — el "Ganancia total · +X %" del hero, en UN solo lugar.
 *
 * Estaba calculado a mano en dos: el chip del hero (Dashboard.jsx) y la frase
 * "Tu cartera rinde X % desde el inicio" (insights.js). Los dos con el mismo
 * `netDeposited`, así que al cambiarle el denominador a uno solo la misma
 * pantalla habría mostrado dos porcentajes distintos.
 *
 * `pct` viene en null —no en 0— cuando no hay denominador que lo sostenga.
 * Null es "no lo puedo calcular"; 0 es "no ganaste nada", que es otra
 * afirmación y era falsa. Quien lo muestre tiene que decidir qué hacer con el
 * null; el MONTO (`usd`) es siempre correcto y se publica siempre.
 */
export function retornoTotal({ totalValue = 0, netDeposited = 0, capitalMaximo = null } = {}) {
  const usd = totalValue - netDeposited
  const denom = denominadorAportado(netDeposited, capitalMaximo ?? 0)
  return { usd, pct: denom ? usd / denom : null }
}

/**
 * computeReturnDelta
 * ──────────────────
 * Δ(Total Return) entre "hoy" y un punto de referencia, EXCLUYENDO cashflows
 * (depósitos / retiros). Es la base de `computeDailyPnl` (referencia = cierre
 * anterior) y de la variación mensual (referencia = cierre del mes pasado).
 *
 * EL BUG QUE CORRIGE: el cálculo viejo era `Δtotal_value` (valor de hoy − valor
 * de referencia). Pero total_value mezcla aportes con ganancias: si retirás
 * US$110, total_value baja US$110 y se mostraba "−$110" aunque no hayas perdido
 * un centavo. Lo mismo al revés con un depósito (variación inflada).
 *
 * FÓRMULA CORRECTA = Δ(Total Return), donde Total Return = value − net_deposited:
 *
 *   variación = (value − net_deposited)_hoy − (value − net_deposited)_referencia
 *
 * Esto equivale exactamente a "(realizado + no realizado) hoy − (realizado +
 * no realizado) en la referencia": value − net_deposited ES la ganancia
 * acumulada sobre el capital aportado (= realizado + no realizado).
 *
 * Usa el valor LIVE de hoy (si se pasa, refleja precios actuales) contra el
 * snapshot de referencia. Sin liveValue, usa el snapshot más reciente como "hoy".
 *
 * @param {Array}  snapshots               [{ date, total_value, total_invested, net_deposited }]
 * @param {Object} [opts]
 * @param {number} [opts.liveValue]         valor total USD actual (mark-to-market en vivo)
 * @param {number} [opts.liveNetDeposited]  net_deposited actual USD (baseline + flujos)
 * @param {string} [opts.sinceDate]         ISO (YYYY-MM-DD). Referencia = snapshot más
 *   reciente ANTERIOR a esta fecha (ej: cierre del mes pasado para month-to-date).
 *   Si empezaste DENTRO del período (no hay snapshot previo) cae al más antiguo.
 *   Sin sinceDate → modo diario: referencia = cierre más reciente anterior a hoy.
 * @returns {null | { usd:number, pct:number, prevDate:string, dayDiff:number }}
 */
export function computeReturnDelta(snapshots, { liveValue = null, liveNetDeposited = null, sinceDate = null } = {}) {
  if (!snapshots?.length) return null
  const today = hoyISO()
  // ⚠️ LAS DOS PUNTAS, NO UNA. Éste es EL hallazgo estructural: los guards de las
  // rondas anteriores filtran el borde de APERTURA y ninguno filtra el de CIERRE.
  // Cuando la punta es la foto del import, el número sale INVERTIDO —un +96%
  // fantasma en vez de un −65% fantasma—, mismo crimen y signo opuesto, y por eso
  // nadie lo fue a buscar. Medido en producción: 180 usuarios (22%) tienen la
  // última fila al costo.
  //
  // Acá se filtra por `esApto` y NO por `esDibujable`: este helper no dibuja
  // nada, produce un DELTA y un PORCENTAJE. Sus dos extremos son bordes de
  // período, y una foto intradía no cierra un período.
  const aptos = [...snapshots].filter(esApto).sort((a, b) => (a.date < b.date ? 1 : -1))
  if (!aptos.length) return null
  const desc = aptos

  // "Hoy": preferimos el valor live (refleja la cartera ahora). Fallback al snap más reciente.
  // El live NO necesita filtro: es la cartera valuada a precio de mercado ahora
  // mismo, que es justamente la regla que queremos en las dos puntas. Lo que sí
  // se filtra es el `net_deposited` de respaldo, que sale de una fila.
  let todayValue, todayNetDep
  if (liveValue != null) {
    todayValue = +liveValue
    todayNetDep = liveNetDeposited != null ? +liveNetDeposited : netDepositedOf(desc[0])
  } else {
    todayValue = +(desc[0].total_value || 0)
    todayNetDep = netDepositedOf(desc[0])
  }

  // Referencia (cierre del período anterior).
  let prev
  if (sinceDate != null) {
    // Cierre más reciente ANTES del inicio del período (ej: último día del mes pasado).
    const cierrePrevio = desc.find(s => s.date < sinceDate)
    if (cierrePrevio) {
      // ⚠️ Y TIENE QUE ESTAR PEGADO AL ARRANQUE. Ver `esBordeFresco`: sin esto,
      // el KPI "Este mes" publicaba +35,24 % / US$ 3.700 midiendo desde 79 días
      // antes —un usuario que se ausentó en junio y volvió en septiembre—
      // mientras `/mensual` y `/reportes` no publicaban nada para ese mismo mes
      // y el mes real era +2,90 %. Sin borde no hay número, y eso es una
      // respuesta.
      //
      // Y si el cierre previo es viejo, NO se cae al fallback de abajo: el más
      // antiguo de la serie es todavía más viejo. Cortar acá o el guard se
      // pisa a sí mismo.
      prev = esBordeFresco(cierrePrevio.date, sinceDate) ? cierrePrevio : null
    } else {
      // ⚠️ ASIMETRÍA DELIBERADA CON EL BACKEND, no un descuido.
      //
      // No hay NINGÚN cierre anterior al período: la serie entera cae adentro,
      // o sea que esta persona empezó este mes. `_border_is_fresh` rechazaría
      // ese borde (`lag < 0`), pero acá se conserva: no mete mercado ajeno
      // —mide una ventana más corta, no una ajena— y es el único que tiene. El
      // backend puede rechazarlo porque le queda la cadena contable de
      // `monthly_entries`; acá no hay segunda vía, así que rechazarlo apaga el
      // KPI a todo usuario nuevo durante su primer mes. Eso no es arreglarlo.
      //
      // `evolution.test.js` fija los dos casos por separado para que quien
      // toque esto tenga que decidirlo, y no romperlo de refilón.
      prev = desc[desc.length - 1]
    }
  } else if (liveValue != null) {
    // Modo diario con live: cierre más reciente con fecha < hoy (saltea el snap de hoy).
    prev = desc.find(s => s.date < today)
  } else {
    prev = desc[1]  // modo diario sin live: penúltimo snapshot
  }
  // ⚠️ `!prev.total_value` NO ALCANZA: deja pasar un `total_value` NEGATIVO
  // (truthy). Con base negativa, el `prevValue > 0 ? ... : 0` de más abajo cae al
  // CERO, y el resultado es lo peor de los dos mundos: un monto en dólares que se
  // publica junto a un "0,00%" que parece medido. Un cero falso es peor que un
  // vacío — el vacío se lee como "no lo sabemos" y el cero como "no se movió".
  // Medido en la copia del 16/08: 7 usuarios publicaban un monto contra 0,00%
  // (uid 1: +US$2.026,35 · 0,00% sobre una base de −11,92).
  // No hay porcentaje contra una base ≤ 0: no es 0, es indefinido.
  if (!prev || !(prev.total_value > 0)) return null
  // Sin `liveValue`, las dos puntas salen de filas y tienen que ser DISTINTAS:
  // con una sola fila apta, `desc[0]` y el fallback `desc[desc.length-1]` son la
  // misma, y el helper publicaba un 0,00% que se lee como "el mes estuvo plano"
  // cuando lo cierto es que no hay con qué medirlo.
  if (liveValue == null && prev === desc[0]) return null

  const usd = (todayValue - todayNetDep) - ((prev.total_value || 0) - netDepositedOf(prev))
  const prevValue = prev.total_value || 0
  const pct = prevValue > 0 ? usd / prevValue : 0
  const dayDiff = Math.max(1, Math.round((new Date(today) - new Date(prev.date)) / 86_400_000))
  return { usd, pct, prevDate: prev.date, dayDiff }
}

/**
 * computeDailyPnl — P&L del día (variación vs el cierre anterior).
 * Wrapper de computeReturnDelta sin `sinceDate` (modo diario).
 * Ver computeReturnDelta para la explicación del cálculo cashflow-adjusted.
 */
export function computeDailyPnl(snapshots, opts = {}) {
  return computeReturnDelta(snapshots, { ...opts, sinceDate: null })
}


/**
 * buildEvolutionFromSnapshots
 * ───────────────────────────
 * Phase 7 — daily-granularity portfolio evolution from snapshots.
 *
 * Each snapshot point produces:
 *   total %     = (value − baseline) / baseline × 100
 *   realized %  = (cumulative realized at snapshot's month) / baseline × 100
 *
 * `baseline` is the snapshot's `net_deposited` (Phase 6+) or, for legacy
 * snapshots predating Phase 6 (`net_deposited === 0`), falls back to
 * `total_invested` (cost basis) so the chart doesn't go to infinity.
 *
 * Cumulative `pnl_realized` is sourced from `monthly_entries` (the "global"
 * broker, sorted ascending), step-matched onto each snapshot by its YYYY-MM.
 *
 * ARS series: value & baseline are converted using the historical blue rate
 * for the snapshot's (year, month) via `lookupHistoricalDolar`.
 *
 * @param {Array}  snapshots     [{ date, total_value, total_invested, net_deposited }, ...]
 * @param {Array}  globalMonthly monthly_entries for broker='global', SORTED ASC by year/month
 * @param {Object} bench         bench.dolar_blue map (or null)
 * @param {number} tcValuacion        live blue rate (used as fallback in lookupHistoricalDolar)
 *
 * @returns {{ seriesUsd: Array, seriesArs: Array } | null}
 *   null if there are <2 snapshots (caller should fall back to monthly logic).
 */
export function buildEvolutionFromSnapshots(snapshots, globalMonthly, bench, tcValuacion) {
  if (!snapshots || snapshots.length < 2) return null
  // ⚠️ Sólo puntos en BASE DE MERCADO. `snapshots` mezcla mediciones del cron con
  // fotos que el import FABRICA copiando la cadena contable
  // (backend/importing/persister.py:1289-1292): no bajan con el mercado y dan más
  // alto que el valor real, así que encadenarlas contra una medición de verdad
  // fabrica un desplome que el usuario nunca vivió. La clase la decide el backend
  // con `twr.clasificar_fila` y viaja en `apto` (/api/snapshots); `sintetico` es
  // el mismo dato con el nombre viejo, para snapshots servidos por un backend
  // anterior a este cambio.
  // ⚠️ `esApto`, Y NO `esDibujable` — AUNQUE EL RESULTADO SE DIBUJE.
  //
  // ESTE ES EL LUGAR DONDE EL PRÓXIMO LECTOR VA A QUERER "CORREGIRLO". Yo mismo lo
  // hice: el nombre dice `buildEvolution...`, el consumidor es un gráfico
  // (`Insights.jsx:481`), y de ahí saqué que era una serie dibujada y le puse el
  // predicado flojo. **El nombre y el consumidor mienten: el CUERPO mide.**
  //
  // Mirá 40 líneas más abajo antes de tocar esto. Cada punto que entra acá es:
  //   · DENOMINADOR de un período  → `period_return = pnl_t / (value_t-1 + 0.5·flows_t)`
  //   · candidato a PICO del aportado → `if (netDep > peakNetDepUsd) …`
  // Son exactamente las dos cosas que `esApto` protege, y son las dos que el
  // contrato de `twr.py` le prohíbe a una foto INTRADIA.
  //
  // Y ésta NO es `curva_indexada`. El contrato de `ACEPTA_LINEA` dice que INTRADIA
  // entra a la línea "y `curva_indexada` se encarga de que nunca sea pico ni
  // denominador". Acá NO HAY QUIEN SE ENCARGUE: el punto entra derecho al
  // encadenado. Aflojar el filtro sin construir ese mecanismo no es dibujar mejor,
  // es contaminar el cálculo.
  //
  // Medido con las 822 series reales de la copia del 16/08: de los 99 usuarios con
  // filas INTRADIA, a 84 les cambiaba el rendimiento acumulado. Con UNA sola fila
  // intradía, el uid 93 pasaba de +7,82% a −33,44%; el 519 de +5,82% a −39,53%;
  // el 427 de −4,32% a +42,43%.
  //
  // Si algún día se quiere la continuidad visual de los puntos INTRADIA, hace falta
  // el equivalente de `curva_indexada` —dibujar el punto SIN que participe del
  // encadenado ni del pico—. No se resuelve metiéndolo al chain-link.
  snapshots = snapshots.filter(esApto)
  if (snapshots.length < 2) return null

  // Pre-compute cumulative pnl_realized by YYYY-MM
  const cumRealizedByMonth = new Map()
  let cum = 0
  for (const m of globalMonthly || []) {
    cum += (m.pnl_realized || 0)
    const key = `${m.year}-${String(m.month).padStart(2, '0')}`
    cumRealizedByMonth.set(key, cum)
  }
  const sortedKeys = [...cumRealizedByMonth.keys()].sort()
  const realizedAt = (dateStr) => {
    const k = dateStr.slice(0, 7)
    if (cumRealizedByMonth.has(k)) return cumRealizedByMonth.get(k)
    let found = null
    for (const kk of sortedKeys) { if (kk <= k) found = kk; else break }
    return found ? cumRealizedByMonth.get(found) : 0
  }

  const sorted = [...snapshots].sort((a, b) => a.date < b.date ? -1 : 1)
  const seriesUsd = []
  const seriesArs = []

  // TWRR chain-linked vía Modified Dietz entre snapshots consecutivos.
  // La fórmula simple (value - net_deposited) / net_deposited es MWR — se
  // distorsiona cuando hay retiros/depósitos grandes (e.g. tras un withdrawal
  // de $177k, net_deposited baja y el ratio se infla a +90% sin que hubiera
  // ganancia real). TWRR usa el rendimiento por período (ajustado por flujos)
  // y los encadena multiplicativamente — neutraliza el timing de flujos.
  //
  //   flows_t       = net_deposited_t − net_deposited_t-1
  //   pnl_t         = (value_t − value_t-1) − flows_t
  //   period_return = pnl_t / (value_t-1 + 0.5 × flows_t)
  //   cum_t         = cum_t-1 × (1 + period_return)
  //
  // Clampeamos period_return ≥ −0.99 para que un período con value=0 (data
  // corrupta) no colapse el multiplicador. -99% es "perdiste casi todo".
  let cumUsd = 1
  let cumArs = 1
  let prevValueUsd = null
  let prevNetDep = null
  let prevValueArs = null
  let prevBaselineArs = null
  // Pico del capital APORTADO — no el de la cartera. Sirve como denominador
  // estable de realized% cuando hay retiros grandes: si aportaste \$100k y
  // después retirás \$70k para impuestos, `net_deposited` queda chico o
  // negativo y el ratio (cumRealized / denom) explota.
  //
  // ⚠️ ACÁ VIVÍA `peakValueUsd`, el pico del VALOR DE LA CARTERA × 0,8, y
  // estaba mal: metía la ganancia NO realizada adentro del denominador de un
  // porcentaje sobre capital aportado. Medido — quien aportó 10k, nunca
  // retiró, tiene 30k y realizó 5k: publicaba 20,8 % donde el número es 50 %.
  // Con la cartera multiplicada por diez, 62,5 % donde son 500 %. Ver
  // `denominadorAportado`, que es la regla única.
  let peakNetDepUsd = 0

  for (const s of sorted) {
    // ⚠️ LA MISMA REGLA, NO UNA COPIA. Acá vivía un segundo
    // `(s.net_deposited > 0) ? ... : s.total_invested` — el mismo `> 0` de §4.4 que
    // se arregló en `netDepositedOf` y que quedó vivo en esta línea, adentro de la
    // función que encadena. Leía un `net_deposited` NEGATIVO (retiros netos por
    // encima de los aportes, un dato legítimo) como si fuera un hueco y caía a
    // `total_invested`, que es COSTO: la base contable volvía a entrar por la
    // ventana, y de ahí salen los `flows` del chain-link de abajo.
    // Son 4.744 filas (11,7%) en 192 usuarios con `net_deposited < 0`.
    //
    // Dos copias de la misma regla en un archivo es el defecto de fondo de este
    // proyecto, así que ahora hay UNA sola y es la de arriba.
    const baselineUsd = netDepositedOf(s)
    const value = s.total_value || 0
    const netDep = baselineUsd || 0
    // ⚠️ EL PICO NO SE ALIMENTA DE `baselineUsd`. Ese sale de `netDepositedOf`,
    // que cae a `total_invested` —COSTO— cuando el dato falta: correcto para
    // dibujar la línea (no querés un hueco), veneno para un DENOMINADOR. Los
    // snapshots legacy de este repo tienen costos corruptos conocidos, y uno
    // solo se volvía el pico. Medido: con un legacy de total_invested
    // 14.860.000, un realized% de 50 % publicaba 0,03 %.
    // Mismo criterio que `capitalMaximoAportado`: un `net_deposited` en 0 es el
    // hueco (la columna es NOT NULL DEFAULT 0), y un hueco se saltea.
    const ndMedido = s?.net_deposited
    if (ndMedido != null && ndMedido !== 0 && ndMedido > peakNetDepUsd) {
      peakNetDepUsd = ndMedido
    }

    // First snapshot → baseline = 0% TWRR
    if (prevValueUsd === null) {
      cumUsd = 1
      // Initialize ARS baselines too (snapshot por snapshot tiene su propio fx)
      const y0 = +s.date.slice(0, 4)
      const mo0 = +s.date.slice(5, 7)
      const fx0 = lookupHistoricalDolar(bench, y0, mo0, tcValuacion)
      prevBaselineArs = netDep * fx0
      prevValueArs = value * fx0
    } else {
      // USD TWRR period return — Modified Dietz con heurística big-withdrawal.
      //
      // Cuando |flow| > 30% del capital inicial Y flow < 0, Modified Dietz
      // (avgCap = ci + 0.5×flow) achica demasiado el denominador y crea
      // spikes artificiales. Caso real: papá retira \$70k de \$100k de capital
      // y cierra una posición con +\$20k. Con MD clásico: 20/65 = +30.7%
      // que compunde a +91% acumulado. La verdad operativa: ganó \$20 sobre
      // \$100 ≈ +20%. Usamos prevValueUsd directo como denom en esos casos
      // (asumimos withdraw al final del período).
      const flows = netDep - prevNetDep
      const pnl = (value - prevValueUsd) - flows
      const flowRatio = prevValueUsd > 0 ? Math.abs(flows) / prevValueUsd : 0
      const isBigWithdraw = flows < 0 && flowRatio > 0.3
      const avgCap = isBigWithdraw ? prevValueUsd : (prevValueUsd + 0.5 * flows)
      const rRaw = avgCap > 0 ? pnl / avgCap : 0
      // SIN TECHO. El `Math.min(..., 0.5)` que estaba acá limitaba las subidas de la
      // CARTERA a +50% por mes y NO le aplicaba nada al BENCHMARK: el sesgo iba
      // sistematicamente en contra del usuario y se componia mes a mes. Un +80% en
      // cripto o post-devaluacion es perfectamente posible. El piso de -99% si
      // queda: no se puede perder mas que todo. Mismo criterio que `twr.dietz`
      // (backend/twr.py:215), cuyo docstring explica por que.
      const r = Math.max(rRaw, -0.99)
      cumUsd *= (1 + r)
    }

    // Denominador estable para realized%: LA regla, la misma que el hero y que
    // el libro del asesor. Ver `denominadorAportado`.
    const denomRealizedUsd = denominadorAportado(baselineUsd, peakNetDepUsd)
    const realPctUsd = denomRealizedUsd ? (realizedAt(s.date) / denomRealizedUsd) * 100 : 0
    seriesUsd.push({
      key: s.date,
      label: s.date.slice(5),       // MM-DD
      total: +((cumUsd - 1) * 100).toFixed(2),
      realized: +realPctUsd.toFixed(2),
    })

    // ARS: convertir value e invested al fx del snapshot — la conversión
    // afecta tanto numerador como denominador del period_return, así que
    // técnicamente el % se mantiene; sin embargo lo replicamos por simetría.
    const y = +s.date.slice(0, 4)
    const mo = +s.date.slice(5, 7)
    const fx = lookupHistoricalDolar(bench, y, mo, tcValuacion)
    const valueArs    = value * fx
    const baselineArs = netDep * fx

    if (prevValueArs !== null && prevBaselineArs !== null) {
      const flowsArs = baselineArs - prevBaselineArs
      const pnlArs = (valueArs - prevValueArs) - flowsArs
      const flowRatioArs = prevValueArs > 0 ? Math.abs(flowsArs) / prevValueArs : 0
      const isBigWithdrawArs = flowsArs < 0 && flowRatioArs > 0.3
      const avgArs = isBigWithdrawArs ? prevValueArs : (prevValueArs + 0.5 * flowsArs)
      const rRawArs = avgArs > 0 ? pnlArs / avgArs : 0
      // SIN TECHO. El `Math.min(..., 0.5)` que estaba acá limitaba las subidas de la
      // CARTERA a +50% por mes y NO le aplicaba nada al BENCHMARK: el sesgo iba
      // sistematicamente en contra del usuario y se componia mes a mes. Un +80% en
      // cripto o post-devaluacion es perfectamente posible. El piso de -99% si
      // queda: no se puede perder mas que todo. Mismo criterio que `twr.dietz`
      // (backend/twr.py:215), cuyo docstring explica por que.
      const rArs = Math.max(rRawArs, -0.99)
      cumArs *= (1 + rArs)
    }
    // El denominador en pesos es el MISMO que en dólares, convertido — y no uno
    // calculado aparte. Si se calculan por separado, el piso (que está en USD)
    // se compara contra pesos: con el dólar a 1400, US$100 de piso son 140.000
    // pesos, así que el mismo usuario con US$50 aportados NO veía porcentaje en
    // dólares y SÍ lo veía en pesos. Las dos monedas tienen que dar el mismo
    // veredicto — este repo ya se quemó con eso en los benchmarks.
    const denomRealizedArs = denomRealizedUsd ? denomRealizedUsd * fx : 0
    const realPctArs = denomRealizedArs > 0 ? ((realizedAt(s.date) * fx) / denomRealizedArs) * 100 : 0
    seriesArs.push({
      key: s.date,
      label: s.date.slice(5),
      total: +((cumArs - 1) * 100).toFixed(2),
      realized: +realPctArs.toFixed(2),
    })

    prevValueUsd = value
    prevNetDep = netDep
    prevValueArs = valueArs
    prevBaselineArs = baselineArs
  }

  return { seriesUsd, seriesArs }
}
