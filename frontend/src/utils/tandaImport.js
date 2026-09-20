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
//   3. SI LA VISTA PREVIA FALLA, NO SE CONFIRMA. El motivo que devuelve el
//      backend es el que se muestra; no se inventa otro.
//
// La pantalla (pages/AdvisorImports.jsx) sólo dibuja lo que este módulo le
// va contando por `onUpdate`.

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

/**
 * Traduce lo que devolvieron preview + confirm al estado final de la fila.
 * Exportada para testearla sola: es donde una mala lectura del backend haría
 * que la pantalla diga "Completo" sobre algo que no lo está.
 */
export function estadoFinal(preview, confirm) {
  const errores = Array.isArray(preview?.errors) ? preview.errors.length : 0
  const repetidos = Number(confirm?.auto_skipped_duplicates || 0)
  // Lo que el confirm dice haber ESCRITO (persist_batch): operaciones +
  // movimientos de caja + conversiones. No se cuentan filas del archivo.
  const cargados = ['operations_created', 'cash_movements', 'conversions']
    .reduce((a, k) => a + Number(confirm?.[k] || 0), 0)
  const notas = []
  if (repetidos > 0) notas.push(`${repetidos} repetidos omitidos`)
  if (errores > 0) notas.push(`${errores} filas con error, omitidas`)

  if (preview?.seed_suggestions?.needed) {
    return {
      estado: ESTADO.REVISAR,
      cargados, repetidos, errores,
      detalle: 'El archivo arranca con ventas de activos que no aparecen comprados: faltan las posiciones previas. Se cargó lo que había; completalo desde su cuenta.',
      notas,
    }
  }
  return { estado: ESTADO.COMPLETO, cargados, repetidos, errores, detalle: null, notas }
}

function mensajeDe(err) {
  if (!err) return 'No se pudo cargar.'
  const p = err.payload
  if (p && typeof p.detail === 'string') return p.detail
  return err.message || 'No se pudo cargar.'
}

/**
 * Corre la tanda. `filas` = [{ id, clientUid, esNuevo, nombre, format, archivos:[File], soloLectura }].
 * `api` necesita `post(path, body, opts)` y `upload(path, formData, opts)`.
 * `onUpdate(id, patch)` recibe cada cambio de estado de una fila.
 * `signal` (AbortSignal) corta ANTES de la fila siguiente — nunca a mitad de
 * un confirm, que es atómico del lado del servidor.
 * Devuelve el resumen final.
 */
export async function correrTanda(filas, { api, onUpdate = () => {}, signal } = {}) {
  const resultados = []
  for (const fila of filas) {
    if (signal?.aborted) break
    if (!filaLista(fila)) {
      const r = { id: fila.id, estado: ESTADO.ERROR, detalle: faltante(fila) || 'La fila está incompleta.' }
      onUpdate(fila.id, r); resultados.push(r)
      continue
    }
    let clientUid = fila.clientUid
    try {
      if (fila.esNuevo) {
        onUpdate(fila.id, { estado: ESTADO.CARGANDO, paso: PASOS.CREANDO })
        const creado = await api.post('/advisor/clients', { label: fila.nombre.trim(), name: fila.nombre.trim() })
        clientUid = creado.client_uid
        onUpdate(fila.id, { clientUid, creado: true })
      }
      onUpdate(fila.id, { estado: ESTADO.CARGANDO, paso: PASOS.LEYENDO })
      const fd = new FormData()
      fila.archivos.forEach(f => fd.append('files', f))
      fd.append('format', fila.format)
      const preview = await api.upload('/imports/preview', fd, { clientId: clientUid })

      onUpdate(fila.id, { estado: ESTADO.CARGANDO, paso: PASOS.GUARDANDO })
      const confirm = await api.post('/imports/confirm', {
        session_id: preview.session_id,
        skip_row_indices: [],
        aprobar_tickers: [],
      }, { clientId: clientUid })

      const r = { id: fila.id, clientUid, batchId: preview.session_id, paso: null, ...estadoFinal(preview, confirm) }
      onUpdate(fila.id, r); resultados.push(r)
    } catch (err) {
      const r = { id: fila.id, clientUid, estado: ESTADO.ERROR, paso: null, detalle: mensajeDe(err) }
      onUpdate(fila.id, r); resultados.push(r)
    }
  }
  return resumen(resultados)
}

export function resumen(resultados) {
  const por = (e) => resultados.filter(r => r.estado === e).length
  return {
    total: resultados.length,
    completos: por(ESTADO.COMPLETO),
    revisar: por(ESTADO.REVISAR),
    errores: por(ESTADO.ERROR),
    movimientos: resultados.reduce((a, r) => a + (r.cargados || 0), 0),
    repetidos: resultados.reduce((a, r) => a + (r.repetidos || 0), 0),
    filasConError: resultados.reduce((a, r) => a + (r.errores || 0), 0),
  }
}
