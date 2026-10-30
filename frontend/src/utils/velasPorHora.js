// velasPorHora — las velas de 1 hora y de 4 horas del gráfico técnico.
// ════════════════════════════════════════════════════════════════════════════
// Nico, 30/10: que la vela en curso se mueva en vivo también en 1 h y 4 h. El
// menú «1D ▾» de LecturaTecnica.jsx suma «1H» y «4H»; los puntos vienen de
// GET /api/tecnico/{activo}/horas (backend/velas_horarias.py): cada uno es
// { d, t, o, h, l, c, s50, s200, rsi, …, enCurso? }, donde `d` es el día de la
// rueda (el de la vela DIARIA a la que pertenece) y `t` cuándo empieza la vela,
// en segundos UTC. La última es la que está en curso (`enCurso`).
//
// Se pide entera al elegir 1H o 4H y después, cada 60 s con la pestaña a la
// vista, sólo desde la última vela (`desde`): la que se estaba moviendo y la
// nueva, si empezó otra. Con la rueda cerrada, espaciado (relojVisible.js).
//
// LA HORA. Todo se muestra en hora argentina (UTC−3 todo el año: la Argentina
// no cambia de hora), también Nueva York y las cripto: es la hora de quien mira.
//
// LOS DIBUJOS Y LAS NOTAS. Se guardan por día ({ d, mas, precio }, utils/dibujos.js)
// y, si se hicieron en 1H o 4H, también por momento (`t`, segundos UTC). En las
// velas de horas (`ubicadorPorHora`):
//   · un punto con momento va a la vela de ese momento (y a la fracción de la
//     vela que corresponde);
//   · un punto de un día va a la PRIMERA vela de ese día, como TradingView (la
//     vela diaria empieza con la rueda);
//   · hacia adelante (el espacio vacío de la derecha) se cuenta con el horario
//     de la rueda: cuántas velas tiene cada día y qué días hay rueda;
//   · antes de la primera vela de horas que hay, no se puede saber dónde cae:
//     ese dibujo no se dibuja en 1H/4H (se ve en diarias). Nunca una posición
//     inventada.

import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { relojVisible, refrescoSegunRueda } from './relojVisible'
import { indiceDeFecha } from './tecnico'
import { precioRedondo } from './dibujos'
import { pctConSigno } from './cuantoSeMueve'

export const INTERVALOS_POR_HORA = { '1h': { minutos: 60, nombre: '1 hora' }, '4h': { minutos: 240, nombre: '4 horas' } }
export const esIntradia = (intervalo) => !!INTERVALOS_POR_HORA[intervalo]

// La vela en curso se mueve cada minuto mientras la rueda está en horario.
export const REFRESCO_HORAS_MS = 60 * 1000
/** Cada cuánto volver a pedir: 60 s con la rueda en horario; con todo cerrado,
 *  a la próxima media hora (cuando abre algo), como el resto de la app. */
export function cadaCuantoRefrescar(enHorario, ahora = new Date()) {
  return enHorario ? REFRESCO_HORAS_MS : refrescoSegunRueda({ abierto: false, en_rueda: 0, en_horario: false }, ahora)
}

// ─── Pedir y refrescar ──────────────────────────────────────────────────────

/** La serie que se tenía más lo nuevo: lo nuevo reemplaza desde su primera vela. */
export function mezclar(puntos = [], nuevos = []) {
  if (!nuevos.length) return puntos
  const corte = nuevos[0].t
  return [...puntos.filter(p => p.t < corte), ...nuevos]
}

const ruta = (asset, cada, moneda, local, desde) =>
  `/tecnico/${encodeURIComponent(asset)}/horas?cada=${cada}&moneda=${moneda}${local ? '&local=1' : ''}${desde != null ? `&desde=${desde}` : ''}`

/**
 * Las velas de `cada` ('1h' | '4h'; null = no hace falta) de este activo y
 * moneda. Devuelve { datos, reintentar }: `datos` undefined mientras carga, la
 * respuesta del servidor ({ disponible, puntos, en_horario, actualizada, … })
 * o { error: true }. Lo ya pedido queda mientras la ficha esté abierta (volver
 * de diarias a 1H no lo pide de nuevo entero).
 */
export function useVelasPorHora({ asset, moneda, local = false, cada }) {
  const [series, setSeries] = useState({})
  const ultimas = useRef({})
  ultimas.current = series
  // Cuándo se pidió por última vez cada serie (Date.now()).
  const pedidas = useRef({})
  const clave = cada ? `${moneda}|${cada}` : null
  const datos = clave ? series[clave] : undefined
  const falta = clave != null && datos === undefined
  useEffect(() => {
    if (!falta) return
    let vivo = true
    api.get(ruta(asset, cada, moneda, local))
      .then(r => { if (vivo) { pedidas.current[clave] = Date.now(); setSeries(s => ({ ...s, [clave]: r || { disponible: false } })) } })
      .catch(() => { if (vivo) setSeries(s => ({ ...s, [clave]: { error: true } })) })
    return () => { vivo = false }
  }, [asset, cada, moneda, local, clave, falta])
  const disponible = !!datos?.disponible
  // El ritmo se calcula una vez por respuesta, como MoversRail: con la rueda
  // cerrada, «hasta la próxima media hora» depende de la hora en que llegó.
  // Calculado una sola vez, el sábado se repetía ese mismo plazo (p. ej. cada
  // 170 s) todo el fin de semana.
  const plazo = useMemo(() => (datos?.disponible ? cadaCuantoRefrescar(!!datos.en_horario) : null), [datos])
  useEffect(() => {
    if (!disponible || !plazo) return
    let vivo = true
    const traer = () => {
      const ult = ultimas.current[clave]?.puntos?.at?.(-1)
      pedidas.current[clave] = Date.now()
      api.get(ruta(asset, cada, moneda, local, ult?.t))
        .then(r => {
          // Un refresco que no trajo nada (Yahoo no contestó) deja lo que había:
          // el cartel sigue diciendo de cuándo es.
          if (!vivo || !r?.disponible || !Array.isArray(r.puntos)) return
          setSeries(s => {
            const antes = s[clave]
            if (!antes?.disponible) return s
            return { ...s, [clave]: { ...antes, ...r, puntos: mezclar(antes.puntos, r.puntos) } }
          })
        })
        .catch(() => { /* el próximo tic vuelve a probar */ })
    }
    // Al volver a 1H/4H con lo de hace más de un minuto (se pasó a diarias y
    // se volvió), se pide ya: el reloj recién tocaría dentro de un plazo
    // entero, que con la rueda cerrada al pedirlo podía ser media hora.
    if (document.visibilityState !== 'hidden' && Date.now() - (pedidas.current[clave] || 0) >= REFRESCO_HORAS_MS) traer()
    const apagar = relojVisible(traer, plazo)
    return () => { vivo = false; apagar() }
  }, [asset, cada, moneda, local, clave, disponible, plazo])
  const reintentar = () => { if (clave) setSeries(s => { const n = { ...s }; delete n[clave]; return n }) }
  return { datos, reintentar }
}

// ─── La hora, en hora argentina ─────────────────────────────────────────────

const ART = -3 * 3600
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
const SEMANA = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb']
const dos = (n) => String(n).padStart(2, '0')
const enArt = (t) => new Date((t + ART) * 1000)

/** '14:30', en hora argentina, de un momento en segundos UTC. */
export function horaArt(t) {
  const x = enArt(t)
  return `${dos(x.getUTCHours())}:${dos(x.getUTCMinutes())}`
}
/** '29/10/26 14:30': para el globo de los datos. */
export function fechaHoraCorta(t) {
  const x = enArt(t)
  return `${dos(x.getUTCDate())}/${dos(x.getUTCMonth() + 1)}/${String(x.getUTCFullYear()).slice(2)} ${horaArt(t)}`
}
/** 'jue 29 oct 14:30': lo que dice la fila de fechas bajo el mouse. */
export function fechaHoraDeLaMira(t) {
  const x = enArt(t)
  return `${SEMANA[x.getUTCDay()]} ${x.getUTCDate()} ${MESES[x.getUTCMonth()]} ${horaArt(t)}`
}

/**
 * Los rótulos de la fila de fechas en 1H/4H: [{ i, texto }]. Como en las
 * diarias (utils/ejesGrafico.marcasDeFechas), el detalle más fino que entra
 * sin pisarse: el año, el mes, la semana (su primer día), el día o la hora
 * (hora argentina). Sin la semana, diez ruedas de 1 hora no tenían ningún
 * rótulo: los días no entraban y no había cambio de mes.
 */
export function marcasDeHoras(puntos, anchoPx, cadaPx = 80) {
  if (!puntos?.length || !(anchoPx > 0)) return []
  const pxPorPunto = anchoPx / Math.max(1, puntos.length)
  const partes = puntos.map(p => {
    const x = enArt(p.t)
    // La semana: cuántas van desde un lunes (el 5/1/1970 lo fue).
    return [x.getUTCFullYear(), x.getUTCMonth(), x.getUTCDate(), Math.floor((Math.floor((p.t + ART) / 86400) - 4) / 7)]
  })
  const nivelDe = puntos.map((p, i) => {
    if (i === 0) return null
    const [a, m, d, s] = partes[i - 1], [a2, m2, d2, s2] = partes[i]
    return a !== a2 ? 0 : m !== m2 ? 1 : s !== s2 ? 2 : d !== d2 ? 3 : 4
  })
  let elegido = 0
  for (let n = 0; n <= 4; n++) {
    const idx = nivelDe.map((v, i) => (v != null && v <= n ? i : null)).filter(i => i != null)
    const minimo = idx.slice(1).reduce((m, i, k) => Math.min(m, (i - idx[k]) * pxPorPunto), Infinity)
    if (idx.length && minimo < cadaPx * 0.55) break
    elegido = n
    if (idx.length * cadaPx > anchoPx * 1.15) break
  }
  const out = []
  let ultimo = -Infinity
  for (let i = 1; i < puntos.length; i++) {
    const v = nivelDe[i]
    if (v == null || v > elegido) continue
    if ((i - ultimo) * pxPorPunto < cadaPx * 0.75) continue
    const [a, m, d] = partes[i]
    out.push({ i, texto: v === 0 ? String(a) : v === 1 ? MESES[m] : v <= 3 ? `${d} ${MESES[m]}` : horaArt(puntos[i].t) })
    ultimo = i
  }
  return out
}

/** «en curso · hace 20 s»: la vela que todavía se mueve. */
export function textoEnCurso(actualizada, ahora = Date.now()) {
  const t = Date.parse(actualizada || '')
  if (!Number.isFinite(t)) return 'en curso'
  const s = Math.max(0, Math.floor((ahora - t) / 1000))
  return `en curso · hace ${s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h`}`
}

// ─── Cuánto se ve al abrir ──────────────────────────────────────────────────

// Al abrir 1H o 4H se ven las velas más nuevas que entran a 6 px cada una (en
// la compu, ~150: un mes de 1 hora en Nueva York), como TradingView. «Todo»
// sigue en el menú.
export const PX_POR_VELA_HORA = 6
export function velasRecientes(ancho, total) {
  if (!(ancho > 0)) return null
  const n = Math.max(20, Math.floor(ancho / PX_POR_VELA_HORA))
  return n < total ? n : null
}

// ─── Ubicar por fecha y hora ────────────────────────────────────────────────

/**
 * La primera vela del día `fecha` (o, si ese día no hubo rueda, del último
 * día de antes, como en las diarias): ahí van tus compras y ventas, los
 * balances y los dividendos. En diarias y semanales es `indiceDeFecha`.
 */
export function primeraVelaDelDia(puntos, fecha) {
  const j = indiceDeFecha(puntos, fecha)
  if (j == null) return null
  const d = puntos[j].d
  let lo = 0, hi = j
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (puntos[mid].d < d) lo = mid + 1
    else hi = mid
  }
  return lo
}

// Cuántos minutos está corrida la hora de `zona` respecto de UTC en el
// momento `t`: para las velas que todavía no existen (Nueva York cambia de
// hora a fin de octubre y a mediados de marzo). Sin zona, `porDefecto`.
const formatos = {}
export function desfaseEn(t, zona, porDefecto = 0) {
  if (!zona) return porDefecto
  try {
    const f = formatos[zona] || (formatos[zona] = new Intl.DateTimeFormat('en-US', {
      timeZone: zona, hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric',
    }))
    const p = Object.fromEntries(f.formatToParts(new Date(t * 1000)).map(x => [x.type, x.value]))
    const local = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute) / 60000
    return Math.round(local - Math.floor(t / 60))
  } catch {
    return porDefecto
  }
}

const diaNumero = (iso) => Math.floor(Date.parse(`${iso}T00:00:00Z`) / 86400000)
const isoDeNumero = (n) => new Date(n * 86400000).toISOString().slice(0, 10)
const habil = (n) => { const w = new Date(n * 86400000).getUTCDay(); return w !== 0 && w !== 6 }

/**
 * Dónde caen, en la serie de horas que se ve, los puntos guardados de tus
 * dibujos, y al revés: qué guardar de un toque. `serie`: los puntos de horas;
 * `sesion` (del servidor): { abre, cierra, desfase, zona, todos_los_dias,
 * velas_por_dia } — apertura y cierre en minutos del día local, corrimiento
 * con UTC en minutos (el de la última vela) y la zona horaria, con la que se
 * calcula el corrimiento de los días que vienen; `cada`: '1h' | '4h';
 * `diarios`: los puntos DIARIOS de la ficha (para guardar el día de modo que
 * también se vea bien en diarias).
 */
export function ubicadorPorHora(serie, { sesion, cada, diarios = [] }) {
  const dur = (INTERVALOS_POR_HORA[cada]?.minutos || 60) * 60
  const vpd = Math.max(1, sesion?.velas_por_dia || 1)
  const abre = sesion?.abre || 0
  const desfaseFijo = sesion?.desfase || 0
  const desfase = (t) => desfaseEn(t, sesion?.zona, desfaseFijo)
  const todos = !!sesion?.todos_los_dias
  const ultima = serie.length - 1
  const dias = []
  serie.forEach((p, i) => { if (!i || serie[i - 1].d !== p.d) dias.push({ d: p.d, i }) })
  const ultimoDia = dias.length - 1
  const diaLocal = (t) => Math.floor((t / 60 + desfase(t)) / 1440)
  // Días de rueda después de `desde` hasta `hasta` (números de día), inclusive.
  const ruedasEntre = (desde, hasta) => {
    let n = 0
    for (let x = desde + 1; x <= hasta; x++) if (todos || habil(x)) n++
    return n
  }
  const ruedaDespues = (desde, n) => {
    let x = desde
    while (n > 0) { x++; if (todos || habil(x)) n-- }
    return x
  }

  /** El lugar (con decimales) de un momento `t`, o null si es antes de la serie. */
  function lugarDelMomento(t) {
    if (!serie.length || !(t >= serie[0].t)) return null
    if (t < serie[ultima].t + dur) {
      let lo = 0, hi = ultima
      while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (serie[mid].t <= t) lo = mid; else hi = mid - 1 }
      // Un momento en un hueco (de noche, el fin de semana, o las 10:30 de un
      // día de BYMA de los que Yahoo da desde las 11) va a la vela siguiente,
      // no a la última del día anterior.
      if (t >= serie[lo].t + dur && lo < ultima) return lo + 1
      return lo + Math.min(0.99, (t - serie[lo].t) / dur)
    }
    // Hacia adelante: las velas que faltan según el horario de la rueda.
    const minuto = (t / 60 + desfase(t)) - diaLocal(t) * 1440
    const slot = Math.min(vpd - 0.01, Math.max(0, (minuto - abre) / (dur / 60)))
    const n = ruedasEntre(diaLocal(serie[ultima].t), diaLocal(t))
    return dias[ultimoDia].i + n * vpd + slot
  }
  /** El momento (segundos UTC) del lugar `k` (puede pasar de la última vela). */
  function momentoDelLugar(k) {
    if (k <= ultima + 0.99) {
      const j = Math.max(0, Math.min(ultima, Math.floor(k)))
      return Math.round(serie[j].t + Math.max(0, k - j) * dur)
    }
    const n = k - dias[ultimoDia].i
    const masDias = Math.floor(n / vpd)
    const slot = n - masDias * vpd
    const dia = ruedaDespues(diaLocal(serie[ultima].t), masDias)
    // La hora local de ese día a UTC, con el corrimiento de ESE día.
    const local = dia * 1440 + abre + slot * (dur / 60)
    const aprox = (local - desfase(serie[ultima].t)) * 60
    return Math.round((local - desfase(aprox)) * 60)
  }
  /** El lugar de un punto guardado sólo por día ({ d, mas, f }), o null. */
  function lugarDelDia(p) {
    let k = -1
    for (let lo = 0, hi = ultimoDia; lo <= hi;) {
      const mid = (lo + hi) >> 1
      if (dias[mid].d <= p.d) { k = mid; lo = mid + 1 } else hi = mid - 1
    }
    if (k < 0) return null
    const pos = k + (p.mas || 0)
    const f = (p.f || 0) * vpd
    return pos <= ultimoDia ? dias[pos].i + f : dias[ultimoDia].i + (pos - ultimoDia) * vpd + f
  }

  return {
    /** El lugar (índice de la serie, con decimales) de un punto guardado, o null si no se puede saber. */
    lugarDelPunto(p) {
      if (!p || !serie.length) return null
      if (Number.isInteger(p.t)) return lugarDelMomento(p.t)
      return lugarDelDia(p)
    },
    lugarDelMomento,
    /**
     * Lo que se guarda de un toque en el lugar `k` (índice de la serie, con
     * decimales) y un precio: el momento y, para que también se vea en
     * diarias (y lo lean los avisos), el día y los días de mercado después.
     * `fraccion`: la del pincel, que en diarias ubica el trazo dentro del día.
     */
    puntoDelLugar(k, precio, { fraccion = false } = {}) {
      const t = momentoDelLugar(Math.max(0, k))
      const dia = k <= ultima + 0.99 ? serie[Math.max(0, Math.min(ultima, Math.floor(k)))].d : isoDeNumero(diaLocal(t))
      const ultDiario = diarios[diarios.length - 1]?.d
      const enDiarias = !ultDiario || dia <= ultDiario
        ? { d: dia, mas: 0 }
        : { d: ultDiario, mas: ruedasEntre(diaNumero(ultDiario), diaNumero(dia)) }
      const pos = lugarDelDia({ d: dia, mas: 0 })
      const f = fraccion && pos != null && k <= ultima + 0.99 ? Math.min(0.99, Math.max(0, (k - pos) / vpd)) : 0
      return { ...enDiarias, t, precio: precioRedondo(precio), ...(f > 0 ? { f: Math.round(f * 100) / 100 } : {}) }
    },
  }
}

// ─── Medir ──────────────────────────────────────────────────────────────────

/** «+2,3 % en 14 velas de 1 hora»: lo que dice la medición en 1H/4H. */
export function textoMedicionPorHora(m, cada) {
  if (!m) return ''
  const pct = pctConSigno(m.pct)
  if (m.dias === 0) return m.diferencia === 0 ? 'Es el mismo punto: tocá otro.' : `${pct} en la misma vela`
  return `${pct} en ${m.dias} vela${m.dias === 1 ? '' : 's'} de ${INTERVALOS_POR_HORA[cada]?.nombre || '1 hora'}`
}
