/**
 * Las cuentas puras del gráfico "Semana a semana" de Reportes.
 * ═══════════════════════════════════════════════════════════════════════════
 * Por qué vive acá y no dentro del componente: el entorno de tests del frontend
 * es node, sin DOM — no se renderiza nada. Lo único que se puede poner en rojo
 * es lo puro. Así que TODO lo que decide qué semana entra, cuánto mide cada
 * pedazo y dónde cae la línea del cero está en este archivo; el `.jsx` sólo
 * dibuja lo que acá se decidió.
 *
 * LO QUE ESTE ARCHIVO LEE DEL MOTOR Y NO RECALCULA (si alguna de estas tres
 * cambia en el backend, el gráfico miente y este comentario es el lugar donde
 * hay que enterarse):
 *
 *   1. LOS MONTOS VIENEN EN DÓLARES, SIEMPRE. Aunque el selector global esté en
 *      Pesos. `reporting/builder.py:772-776` lo declara: sólo el PORCENTAJE se
 *      convierte en el backend, los montos los convierte `useMoneyFormat` en el
 *      navegador. Multiplicar acá por el tipo de cambio sería multiplicar dos
 *      veces (~1.400×).
 *
 *   2. LOS DOS PEDAZOS SUMAN EXACTO. Para una semana el motor DEFINE
 *      `unrealized = delta_usd − realized` (`builder.py:1919`), así que
 *      "posiciones abiertas" + "ventas y dividendos" da el resultado de la
 *      semana sin residuo. No hace falta un tercer segmento.
 *      El costado flojo de esa resta —que el pedazo de abiertas se come también
 *      cualquier otra cosa que se mueva, como pesos quietos contra el dólar— se
 *      le cuenta al usuario en el panel de detalle, no se tapa.
 *
 *   3. CON UN BROKER ELEGIDO, "ABIERTAS" ES CERO POR DISEÑO. Las fotos diarias
 *      de la cartera son globales, no por broker, así que el motor pone
 *      `delta_usd = realized` y `unrealized = 0` (`builder.py:1780-1786` y `:1914-1917`). Cero
 *      ahí NO significa "no se movieron": significa "no se puede medir". El
 *      componente lo dice en pantalla.
 *
 * Y una que es del calendario: la semana en curso llega marcada `is_current`, y
 * las semanas que TODAVÍA NO EMPEZARON también llegan (el backend arma todas las
 * del mes, `timeline.py:57-60`). Se filtran por fecha contra el día calendario
 * del usuario — `hoyISO()`, nunca `toISOString()`, que de 21:00 a medianoche ya
 * es mañana y metería una barra vacía del futuro.
 */

import { hoyISO } from './fecha'

/** Cuántas semanas dibuja la tira. 12 ≈ un trimestre: entra en 375px de ancho. */
export const MAX_SEMANAS = 12

const MES_CORTO = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
                   'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

function numero(v) {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

/**
 * Saca las semanas de adentro de los meses del timeline y las deja en una sola
 * fila, de la más vieja a la más nueva.
 *
 * `hoy` se pasa a propósito en vez de leerlo adentro: un test con una fecha
 * escrita a mano tiene que poder decidir qué es futuro y qué no.
 */
export function aplanarSemanas(yearGroups, hoy = hoyISO()) {
  const vistas = new Set()
  const salida = []

  for (const grupo of yearGroups || []) {
    for (const mes of (grupo && grupo.months) || []) {
      for (const semana of (mes && mes.children) || []) {
        if (!semana || semana.period_type !== 'week') continue
        if (!semana.period_start) continue
        // Semana que todavía no empezó: el mes en curso trae las que faltan.
        if (hoy && semana.period_start > hoy) continue
        // Una semana pertenece al mes donde cae su lunes, así que hoy no hay
        // repetidas. El guard igual queda: si esa regla cambia, el gráfico
        // dibujaría dos barras de la misma semana y nadie lo vería.
        if (vistas.has(semana.period_key)) continue
        vistas.add(semana.period_key)
        salida.push(semana)
      }
    }
  }

  salida.sort((a, b) => (a.period_start < b.period_start ? -1 : a.period_start > b.period_start ? 1 : 0))
  return salida
}

/** Las últimas `n` de la fila (la más nueva queda al final, contra el eje). */
export function ultimasSemanas(semanas, n = MAX_SEMANAS) {
  const fila = semanas || []
  return n > 0 && fila.length > n ? fila.slice(-n) : fila
}

/**
 * Traduce una semana del backend a lo que el gráfico necesita dibujar.
 *
 * Estados:
 *   'medida'       → barra normal, se puede partir en dos pedazos.
 *   'quieta'       → el motor la marcó sin actividad (`is_relevant` false, que
 *                    es trades > 0 || |delta| >= 100 || flujos). Se dibuja una
 *                    rayita apoyada en el cero: pasó poco, pero pasó.
 *   'sin-medicion' → el motor no pudo medirla, por CUALQUIERA de sus dos vías
 *                    (ver el bloque de abajo). `total` y `abiertas` salen en
 *                    null a propósito: un cero se dibuja, un null no, y el cero
 *                    que publica el backend en ese caso significa "no se pudo
 *                    medir", no "no se movió".
 *
 * `cerradas` sobrevive incluso sin medición, porque las ventas de esa semana SÍ
 * se conocen; es lo único publicable de una semana que no se pudo medir.
 */
export function medirSemana(semana, { porBroker = false } = {}) {
  const m = (semana && semana.metrics) || {}
  const sinBase = m.basis_incomparable === true
  const quieta = semana && semana.is_relevant === false

  // ⚠️ EL MOTOR TIENE DOS FORMAS DE DECIR "NO PUDE MEDIR ESTA SEMANA", Y LA
  // SEGUNDA NO SE VE. `basis_incomparable` es la ruidosa: pone el resultado en
  // cero y levanta la bandera. La otra es `dw_incomplete`
  // (reporting/builder.py:1835-1842 y :1906), que se limita a NO PUBLICAR EL
  // PORCENTAJE y deja el monto intacto. Dispara en dos casos, los dos feos:
  //   · no hay foto que abra la semana → `delta_usd = valor final − 0 − flujos`,
  //     o sea la CARTERA ENTERA contada como resultado de esa semana;
  //   · las dos fotos están a más de 10 días → la barra se come semanas de
  //     mercado que no son las suyas.
  // Dibujar eso como una barra normal no sólo publica un número inventado:
  // siendo el más grande de la serie, se lleva la escala y aplasta a las otras
  // once contra la línea del cero.
  // Por eso "el motor no publicó el porcentaje" cuenta como no medida.
  //
  // LA EXCEPCIÓN, y es importante: con un broker elegido el porcentaje viene
  // nulo POR DISEÑO (builder.py:1780-1786) y el monto —que es sólo lo
  // realizado— sí es confiable. Ahí el hueco sería el número inventado.
  const sinPorcentaje = !porBroker && typeof m.delta_pct !== 'number'
  const noMedible = sinBase || sinPorcentaje

  return {
    clave: (semana && semana.period_key) || '',
    rotulo: (semana && semana.period_label) || '',
    inicio: (semana && semana.period_start) || '',
    fin: (semana && semana.period_end) || '',
    enCurso: !!(semana && semana.is_current),
    estado: noMedible ? 'sin-medicion' : quieta ? 'quieta' : 'medida',
    total: noMedible ? null : numero(m.delta_usd),
    abiertas: noMedible ? null : numero(m.unrealized_pnl),
    // Lo realizado sobrevive a las dos formas de "no medible": las ventas de esa
    // semana se conocen igual. Es lo único publicable de una semana sin medir.
    cerradas: numero(m.realized_pnl),
    pct: noMedible || typeof m.delta_pct !== 'number' ? null : m.delta_pct,
    // Por qué no se pudo medir, para que el panel de detalle no diga siempre lo
    // mismo: el motor a veces manda su propio motivo en texto.
    motivo: noMedible ? (m.motor_motivo_texto || null) : null,
    operaciones: numero(m.trades_count),
  }
}

/** Los pedazos que se dibujan de una semana, según el interruptor. */
export function pedazosDe(medida, modo = 'todo') {
  if (!medida || medida.estado === 'sin-medicion') return []
  const abiertas = { tipo: 'abiertas', valor: numero(medida.abiertas) }
  if (modo === 'abiertas') return [abiertas]
  return [abiertas, { tipo: 'cerradas', valor: numero(medida.cerradas) }]
}

/**
 * Cuánto mide la barra más alta para cada lado. Es la escala del gráfico: un
 * solo número por lado para todas las barras, si no, dos semanas con el mismo
 * resultado se dibujarían distinto.
 */
export function escalaDeSerie(medidas, modo = 'todo') {
  let arriba = 0
  let abajo = 0

  for (const medida of medidas || []) {
    let positivo = 0
    let negativo = 0
    for (const pedazo of pedazosDe(medida, modo)) {
      if (pedazo.valor > 0) positivo += pedazo.valor
      else negativo += -pedazo.valor
    }
    if (positivo > arriba) arriba = positivo
    if (negativo > abajo) abajo = negativo
  }

  return { arriba, abajo }
}

/**
 * Qué proporción del alto queda ARRIBA de la línea del cero.
 *
 * Es exactamente la proporción entre los dos máximos, SIN topes, y de eso
 * depende que el gráfico no mienta: como cada pedazo se mide contra el máximo
 * de su lado, repartir el alto en esa misma proporción hace que un dólar mida
 * lo mismo arriba que abajo. La cuenta se cancela sola —
 *
 *     alto = (valor / máximo del lado) × (máximo del lado / total) × H
 *          =  valor / total × H          ← el mismo píxel-por-dólar de los dos lados
 *
 * ⚠️ ACÁ HUBO UN TOPE DE 0,88/0,12 Y ERA UNA MENTIRA. Lo puse para que el lado
 * chico no quedara invisible, y lo que hacía era romper esa cancelación: con un
 * trimestre de +US$2.000 y una sola semana de −US$20, la caja de abajo se
 * quedaba con 27 px para 20 dólares mientras la de arriba tenía 197 px para
 * 2.000. Dibujado: la semana de −US$20 salía MÁS ALTA que una de +US$200. El
 * que mira concluía exactamente lo contrario de lo que pasó.
 * El problema que el tope quería resolver se resuelve donde corresponde: con un
 * alto mínimo en píxeles de la barra (`min-h` en el componente), que es un piso
 * de visibilidad y no le cambia el valor al píxel de un lado.
 *
 * Serie plana o vacía: el cero al medio, que es lo honesto cuando no hay nada
 * que repartir (y evita dividir por cero).
 */
export function fraccionArriba({ arriba = 0, abajo = 0 } = {}) {
  const total = arriba + abajo
  if (!(total > 0)) return 0.5
  return arriba / total
}

/**
 * El número que representa una barra según el interruptor: el resultado de la
 * semana, o sólo la parte de las posiciones abiertas.
 *
 * Existe para que el rótulo accesible, el globito del mouse y el panel de
 * detalle digan los tres LO MISMO que se dibuja. Cuando el ternario estaba
 * escrito dos veces, el globito anunciaba el total incluso en "Sólo abiertas",
 * que es justo el número que ese modo existe para sacar de la vista.
 */
export function valorDe(medida, modo = 'todo') {
  if (!medida || medida.estado === 'sin-medicion') return null
  return modo === 'abiertas' ? medida.abiertas : medida.total
}

/**
 * Alto de un pedazo, en porcentaje del área de su lado. Proporción pura.
 *
 * ⚠️ ACÁ TAMBIÉN HUBO UN PISO (1,5 %) Y TAMBIÉN DEFORMABA. Un piso en PORCENTAJE
 * DEL ÁREA vale distinto de cada lado de la línea, porque las dos áreas no
 * miden lo mismo: con la escala {arriba: 2.000, abajo: 20}, el piso inflaba los
 * US$20 del lado de arriba a 3,3 px mientras los mismos US$20 de abajo median
 * 2,2 px. El mismo monto, dos alturas. La visibilidad del pedazo chiquito se
 * garantiza ahora con un alto mínimo en PÍXELES en el componente (`min-h`), que
 * es un piso igual para los dos lados y no toca la proporción.
 *
 * El techo de 100 % es defensivo: si la escala llegara mal, la barra se recorta
 * en su caja en vez de derramarse sobre las de al lado.
 */
export function altoPorcentual(valor, maximoDelLado) {
  const v = Number(valor)
  if (!Number.isFinite(v) || v === 0) return 0
  if (!(maximoDelLado > 0)) return 0
  return Math.min(100, (Math.abs(v) / maximoDelLado) * 100)
}

/**
 * Rótulo de una semana: '7 – 13 sep', o '31 ago – 6 sep' si cruza de mes.
 * Se parte el texto de la fecha en vez de construir un Date: `new Date('2026-09-07')`
 * se interpreta en UTC y en Argentina devuelve el día anterior.
 */
export function rangoSemana(inicio, fin) {
  const a = partesISO(inicio)
  const b = partesISO(fin)
  if (!a && !b) return ''
  if (!a) return diaCorto(fin)
  if (!b) return diaCorto(inicio)
  if (a.mes === b.mes && a.anio === b.anio) return `${a.dia} – ${b.dia} ${MES_CORTO[b.mes - 1]}`
  return `${a.dia} ${MES_CORTO[a.mes - 1]} – ${b.dia} ${MES_CORTO[b.mes - 1]}`
}

/** Un día suelto: '7 sep'. Mismo criterio de parseo que `rangoSemana`. */
export function diaCorto(iso) {
  const p = partesISO(iso)
  return p ? `${p.dia} ${MES_CORTO[p.mes - 1]}` : ''
}

/**
 * La clave ISO de la semana de una fecha: '2026-W37'.
 *
 * Es LA definición de semana del producto — la misma que usa el backend
 * (`date.isocalendar()` de Python) y la que arma la URL del reporte semanal.
 * Vive acá para que haya una sola: cuando estaba escrita adentro de la pantalla,
 * cualquier otro lugar que necesitara una semana tenía que copiarla.
 *
 * La semana 1 del año es la que contiene el primer jueves. Por eso el 29 de
 * diciembre de 2025 pertenece a la semana 1 de 2026: el año de la clave no es
 * necesariamente el de la fecha.
 */
export function claveSemanaISO(iso) {
  const p = partesISO(iso)
  if (!p) return ''
  // Se opera en UTC con las partes ya separadas: construir el Date desde el
  // texto lo interpretaría en UTC y en Argentina devolvería el día anterior.
  const fecha = new Date(Date.UTC(p.anio, p.mes - 1, p.dia))
  const diaSemana = fecha.getUTCDay() || 7          // domingo = 7, no 0
  fecha.setUTCDate(fecha.getUTCDate() + 4 - diaSemana)  // al jueves de su semana
  const inicioAnio = new Date(Date.UTC(fecha.getUTCFullYear(), 0, 1))
  const numero = Math.ceil(((fecha - inicioAnio) / 86400000 + 1) / 7)
  return `${fecha.getUTCFullYear()}-W${String(numero).padStart(2, '0')}`
}

function partesISO(iso) {
  if (typeof iso !== 'string') return null
  const partes = iso.slice(0, 10).split('-')
  if (partes.length !== 3) return null
  const anio = Number(partes[0])
  const mes = Number(partes[1])
  const dia = Number(partes[2])
  if (!Number.isInteger(anio) || !Number.isInteger(mes) || !Number.isInteger(dia)) return null
  if (mes < 1 || mes > 12 || dia < 1 || dia > 31) return null
  return { anio, mes, dia }
}
