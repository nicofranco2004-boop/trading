// Carga de historiales por tanda (Plan Asesor) — el orquestador.
//
// Es un módulo PURO a propósito: no sabe de React ni de pantallas. Recibe la
// lista de filas que armó el asesor y una `api`, y corre el importador que ya
// existe (/imports/preview + /imports/confirm) una fila por vez, cada pedido
// "a nombre de" el cliente de esa fila (`opts.clientId`, ver utils/api.js).
//
// Tres decisiones de producto viven acá y en ningún otro lado:
//   1. EN SERIE, nunca en paralelo. SQLite tiene UNA llave de escritura por
//      base: N confirms a la vez se pisan y traban la app para todos
//      (backend/tests/test_import_confirm_lock.py cuenta la historia).
//   2. LA TANDA NO PREGUNTA. No manda `seed_state`, no manda
//      `include_duplicates`, manda `aprobar_tickers: []`. Lo que el asistente
//      individual le preguntaría a la persona, acá termina en estado
//      'revisar' con un motivo, y se cierra desde la cuenta del cliente.
//      ⚠️ Eso obliga a LEER todo lo que el asistente muestra y la tanda no
//      puede preguntar: traspasos entre brokers (`preview.traspasos`), filas
//      que el guardado no pudo escribir (`confirm.skipped_rows`), filas que
//      exigen aprobación (`confirm.skipped_by_user`), caja negativa
//      (`confirm.cash_health`) y pasos del post-proceso que fallaron
//      (`confirm.post_proceso`). Si algo de eso pasa, la fila NO es "Completo".
//   3. SI LA VISTA PREVIA FALLA, NO SE CONFIRMA. El motivo que devuelve el
//      backend es el que se muestra; no se inventa otro.
//
// La pantalla (pages/AdvisorImports.jsx) sólo dibuja lo que este módulo le
// va contando por `onUpdate`.
import { errorMessage } from './api'

export const ESTADO = {
  PENDIENTE: 'pendiente',
  CARGANDO: 'cargando',
  COMPLETO: 'completo',
  REVISAR: 'revisar',
  ERROR: 'error',
}

// Sub-pasos que se muestran mientras una fila corre. El orden es el real.
export const PASOS = {
  CREANDO: 'Creando la cuenta del cliente',
  LEYENDO: 'Leyendo los archivos',
  GUARDANDO: 'Guardando movimientos',
}

// Extensiones que el importador de movimientos entiende. El PDF (la foto de
// tenencia) queda afuera en F1: soltarlo acá rompería la fila entera con un
// mensaje que no dice qué sacar.
export const EXTENSIONES = ['csv', 'xlsx', 'xls', 'txt']
export function archivoAceptado(nombre) {
  const ext = String(nombre || '').toLowerCase().split('.').pop()
  return EXTENSIONES.includes(ext)
}

/** ¿La fila tiene todo lo que hace falta para intentar cargarla? */
export function filaLista(fila) {
  if (!fila) return false
  const tieneCliente = fila.esNuevo ? !!(fila.nombre || '').trim() : Number.isInteger(fila.clientUid)
  return tieneCliente && !!fila.format && Array.isArray(fila.archivos) && fila.archivos.length > 0 && !fila.soloLectura
}

/** Qué le falta a la fila, en palabras de la pantalla. null = nada. */
export function faltante(fila) {
  if (fila.soloLectura) return 'Vínculo de sólo lectura'
  if (fila.esNuevo ? !(fila.nombre || '').trim() : !Number.isInteger(fila.clientUid)) return 'Falta el cliente'
  if (!fila.format) return 'Falta el broker'
  if (!fila.archivos || fila.archivos.length === 0) return 'Faltan archivos'
  return null
}

export const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`

/**
 * Traduce lo que devolvieron preview + confirm al estado final de la fila.
 * Exportada para testearla sola: es donde una mala lectura del backend haría
 * que la pantalla diga "Completo" sobre algo que no lo está.
 */
export function estadoFinal(preview, confirm) {
  // `errors` del preview es UNA entrada por (fila, error): una fila con dos
  // problemas cuenta dos. El número de FILAS está en summary.invalid_rows.
  const errores = Number(preview?.summary?.invalid_rows ?? (Array.isArray(preview?.errors) ? preview.errors.length : 0))
  const repetidos = Number(confirm?.auto_skipped_duplicates || 0)
  // Lo que el confirm dice haber ESCRITO (persist_batch). Una COMPRA crea una
  // posición (positions_created); una venta/cierre, una operación
  // (operations_created); depósitos y retiros, movimientos de caja; el dólar
  // MEP, conversiones. Verificado contra la respuesta real: un archivo con un
  // depósito y una compra vuelve como positions_created=1, cash_movements=1,
  // operations_created=0 — sin `positions_created` la pantalla decía "1".
  const cargados = ['positions_created', 'operations_created', 'cash_movements', 'conversions']
    .reduce((a, k) => a + Number(confirm?.[k] || 0), 0)

  const notas = []
  const motivos = []   // cada uno vuelve la fila "Revisar"
  if (repetidos > 0) notas.push(plural(repetidos, 'repetido omitido', 'repetidos omitidos'))
  if (errores > 0) notas.push(plural(errores, 'fila con error, omitida', 'filas con error, omitidas'))

  // Traspasos entre brokers del MISMO cliente: el asistente individual pide
  // aprobar el cierre en el broker de origen; la tanda no puede → si no se
  // avisa, el mismo título queda contado dos veces.
  const traspasos = Array.isArray(preview?.traspasos) ? preview.traspasos : []
  if (traspasos.length > 0) {
    const t = traspasos[0]
    motivos.push(`${plural(traspasos.length, 'título vino', 'títulos vinieron')} de otro broker suyo (${t.activo || ''} desde ${t.broker_origen || 'otro broker'}): falta aprobar el cierre allá para no contarlo dos veces.`)
  }
  // Filas que el guardado no pudo escribir (el preview las dio por buenas).
  const skipped = Array.isArray(confirm?.skipped_rows) ? confirm.skipped_rows : []
  if (skipped.length > 0) {
    const m = skipped[0]?.message || skipped[0]?.error || skipped[0]?.reason || ''
    motivos.push(`${plural(skipped.length, 'fila no se pudo guardar', 'filas no se pudieron guardar')}${m ? `: ${m}` : '.'}`)
  }
  // Filas que exigen aprobación explícita (fail-closed): no entraron.
  if (Number(confirm?.skipped_by_user || 0) > 0) {
    motivos.push(`${plural(Number(confirm.skipped_by_user), 'fila requiere', 'filas requieren')} tu aprobación y no entró.`)
  }
  // Estado inicial: el archivo arranca a mitad de la historia.
  if (preview?.seed_suggestions?.needed) {
    const tot = preview.seed_suggestions.totals || {}
    const porVentas = Number(tot.sell_errors || tot.ventas_sin_compra || 0) > 0
    motivos.push(porVentas
      ? 'El archivo arranca con ventas de activos que no aparecen comprados: faltan las posiciones previas. Se cargó lo que había; completalo con "Editar y rehacer" desde su cuenta.'
      : 'El archivo arranca sin el fondeo inicial: la caja queda en negativo. Se cargó lo que había; completalo con "Editar y rehacer" desde su cuenta.')
  }
  // Caja negativa al terminar (aunque el estado inicial no lo haya pedido).
  const cajas = Array.isArray(confirm?.cash_health) ? confirm.cash_health : []
  const negativas = cajas.filter(c => Number(c?.balance) < -0.01)
  if (negativas.length > 0 && !preview?.seed_suggestions?.needed) {
    motivos.push(`La caja quedó en negativo en ${negativas.map(c => `${c.broker} ${c.currency || c.asset || ''}`.trim()).join(', ')}: revisá si falta un depósito.`)
  }
  // Post-proceso (rebuild / recalc / fotos): antes fallaba en silencio.
  const pp = confirm?.post_proceso && typeof confirm.post_proceso === 'object' ? confirm.post_proceso : {}
  const fallidos = Object.keys(pp).filter(k => pp[k] === 'error')
  if (fallidos.length > 0) {
    motivos.push('Se guardaron los movimientos pero falló el recálculo posterior de la cartera: entrá a su cuenta y usá "Recalcular".')
  }
  if (confirm?.fx_migracion && confirm.fx_migracion.migrada === false && confirm.fx_migracion.motivo) {
    notas.push(`tipo de cambio: ${confirm.fx_migracion.motivo}`)
  }

  const base = { cargados, repetidos, errores, notas }
  if (motivos.length > 0) return { ...base, estado: ESTADO.REVISAR, detalle: motivos.join(' '), motivos }
  return { ...base, estado: ESTADO.COMPLETO, detalle: null, motivos }
}

function mensajeDe(err) {
  return errorMessage(err) || 'No se pudo cargar.'
}

const espera = (ms) => new Promise(r => setTimeout(r, ms))

/**
 * Corre la tanda. `filas` = [{ id, clientUid, esNuevo, nombre, format, archivos:[File], soloLectura }].
 * `api` necesita `post(path, body, opts)` y `upload(path, formData, opts)`.
 * `onUpdate(id, patch)` recibe cada cambio de estado de una fila.
 * `signal` (AbortSignal) corta ANTES de la fila siguiente — nunca a mitad de
 * un confirm, que es atómico del lado del servidor.
 * `dormir` se inyecta en tests para no esperar de verdad.
 * Devuelve el resumen final.
 * `tandaId` (Fase 2): el id de la tanda en el servidor; viaja como `tanda_id`
 * en cada preview para que el lote quede colgado de ella.
 */
export async function correrTanda(filas, { api, onUpdate = () => {}, signal, dormir = espera, tandaId = null } = {}) {
  const resultados = []
  // Un cliente NUEVO nombrado en dos filas (tiene dos brokers) se crea UNA vez.
  const creados = new Map()
  for (const fila of filas) {
    if (signal?.aborted) break
    if (!filaLista(fila)) {
      const r = { id: fila.id, estado: ESTADO.ERROR, detalle: faltante(fila) || 'La fila está incompleta.' }
      onUpdate(fila.id, r); resultados.push(r)
      continue
    }
    let clientUid = fila.clientUid
    let creado = false
    try {
      if (fila.esNuevo) {
        const nombre = fila.nombre.trim()
        const clave = nombre.toLowerCase()
        onUpdate(fila.id, { estado: ESTADO.CARGANDO, paso: PASOS.CREANDO })
        if (creados.has(clave)) {
          clientUid = creados.get(clave)
        } else {
          clientUid = await crearCliente(api, nombre, dormir)
          creados.set(clave, clientUid)
          creado = true
        }
        // A partir de acá la fila ES un cliente existente: si falla y se
        // reintenta, no se vuelve a crear.
        onUpdate(fila.id, { clientUid, esNuevo: false, label: nombre, creado })
      }
      if (!Number.isInteger(clientUid)) {
        // Nunca mandar un pedido sin cliente: sin header caería en la cuenta
        // propia del asesor (el bug que el header existe para evitar).
        throw new Error('No se pudo identificar la cuenta del cliente.')
      }
      onUpdate(fila.id, { estado: ESTADO.CARGANDO, paso: PASOS.LEYENDO })
      const fd = new FormData()
      fila.archivos.forEach(f => fd.append('files', f))
      fd.append('format', fila.format)
      if (tandaId) fd.append('tanda_id', String(tandaId))
      const preview = await api.upload('/imports/preview', fd, { clientId: clientUid })

      // Archivo IDÉNTICO a uno ya confirmado: no hay nada que confirmar (dejaría
      // un lote vacío y correría todo el post-proceso por nada).
      if (preview?.duplicate_of_batch_id) {
        const r = { id: fila.id, clientUid, batchId: null, paso: null, estado: ESTADO.COMPLETO, cargados: 0, repetidos: 0, errores: 0,
          detalle: null, notas: ['ya estaba cargado: el archivo es idéntico a uno anterior'], creado }
        onUpdate(fila.id, r); resultados.push(r)
        continue
      }

      onUpdate(fila.id, { estado: ESTADO.CARGANDO, paso: PASOS.GUARDANDO })
      const confirm = await api.post('/imports/confirm', {
        session_id: preview.session_id,
        skip_row_indices: [],
        aprobar_tickers: [],
      }, { clientId: clientUid })

      const r = { id: fila.id, clientUid, batchId: preview.session_id, paso: null, creado, ...estadoFinal(preview, confirm) }
      onUpdate(fila.id, r); resultados.push(r)
    } catch (err) {
      const status = Number(err?.status) || null
      const r = {
        id: fila.id, clientUid, estado: ESTADO.ERROR, paso: null, creado,
        detalle: mensajeDe(err), status,
        // 502/503/504 en el confirm: no sabemos si llegó a guardarse. Un 4xx
        // del preview/confirm sí es "no se tocó nada".
        incierto: status == null || status >= 500,
      }
      onUpdate(fila.id, r); resultados.push(r)
    }
  }
  return resumen(resultados)
}

// El alta de clientes tiene tope de 30 por minuto en el servidor; una tanda de
// 50 clientes nuevos lo pisa. Ante 429 se espera y se reintenta UNA vez.
async function crearCliente(api, nombre, dormir) {
  const body = { label: nombre, name: nombre }
  try {
    const c = await api.post('/advisor/clients', body)
    return c?.client_uid
  } catch (err) {
    if (Number(err?.status) !== 429) throw err
    await dormir(61_000)
    const c = await api.post('/advisor/clients', body)
    return c?.client_uid
  }
}

// ── Contrato con el servidor (Fase 2): ida y vuelta sin pérdida ─────────────
// `platform` viaja como ID (cocos, balanz…) para poder rearmar la fila;
// `platform_label` para mostrarla. `incierto`, `notas` y `status` también van:
// sin ellos, una tanda reabierta decía "No se cargó ningún movimiento" sobre un
// 5xx que quizás guardó, y perdía "ya estaba cargado: archivo idéntico".
export function filaAlServidor(f) {
  return {
    id: f.id,
    client_uid: Number.isInteger(f.clientUid) ? f.clientUid : null,
    label: f.label || f.nombre || '',
    platform: f.platform || '',
    platform_label: f.platformLabel || '',
    archivos: (f.archivos || []).map(a => String(a.name || '').split(/[\\/]/).pop()),
    estado: f.estado || ESTADO.PENDIENTE,
    batch_id: f.batchId || null,
    cargados: f.cargados || 0,
    repetidos: f.repetidos || 0,
    errores: f.errores || 0,
    detalle: f.detalle || null,
    notas: (f.notas || []).slice(0, 6),
    creado: !!f.creado,
    incierto: !!f.incierto,
  }
}
export function filaDelServidor(r) {
  return {
    id: r.id, clientUid: Number.isInteger(r.client_uid) ? r.client_uid : null, esNuevo: false, nombre: '',
    label: r.label || '', platform: r.platform || '', platformLabel: r.platform_label || r.platform || '',
    format: '', archivos: (r.archivos || []).map(n => ({ name: n, size: 0 })),
    estado: r.estado, batchId: r.batch_id || null, cargados: r.cargados || 0,
    repetidos: r.repetidos || 0, errores: r.errores || 0, detalle: r.detalle || null,
    notas: Array.isArray(r.notas) ? r.notas : [], creado: !!r.creado, incierto: !!r.incierto,
    batchStatus: r.batch_status || null,
  }
}
// SQLite guarda "2026-09-20 14:01:02" (con espacio, en UTC). Safari no parsea
// el espacio: se normaliza a ISO con 'T' y 'Z'. Devuelve ms o null.
export function fechaServidor(v) {
  if (!v) return null
  const iso = String(v).replace(' ', 'T') + (/Z$|[+-]\d\d:\d\d$/.test(String(v)) ? '' : 'Z')
  const t = Date.parse(iso)
  return Number.isNaN(t) ? null : t
}
// Al reabrir una tanda que no terminó, lo que quedó 'cargando'/'pendiente' no
// corrió o no sabemos cómo terminó: se marca como interrumpido.
export function marcarInterrumpidas(filas) {
  return filas.map(f => {
    if (f.estado === ESTADO.CARGANDO) return { ...f, estado: ESTADO.ERROR, incierto: true, detalle: 'La carga se cortó mientras corría esta fila: no sabemos si llegó a guardarse.' }
    if (f.estado === ESTADO.PENDIENTE) return { ...f, estado: ESTADO.ERROR, incierto: false, detalle: 'No llegó a arrancar: la tanda se cortó antes.' }
    return f
  })
}

export function resumen(resultados) {
  const por = (e) => resultados.filter(r => r.estado === e).length
  return {
    total: resultados.length,
    completos: por(ESTADO.COMPLETO),
    revisar: por(ESTADO.REVISAR),
    errores: por(ESTADO.ERROR),
    // Sólo lo que sigue cargado: una fila revertida no suma movimientos.
    movimientos: resultados.reduce((a, r) => a + ([ESTADO.COMPLETO, ESTADO.REVISAR].includes(r.estado) ? (r.cargados || 0) : 0), 0),
    repetidos: resultados.reduce((a, r) => a + (r.repetidos || 0), 0),
    filasConError: resultados.reduce((a, r) => a + (r.errores || 0), 0),
  }
}
