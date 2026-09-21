import { describe, it, expect } from 'vitest'
import { correrTanda, estadoFinal, filaLista, faltante, ESTADO, resumen } from './tandaImport'

// Los tests atraviesan el orquestador REAL con una api falsa que registra cada
// pedido: qué ruta, en qué orden y A NOMBRE DE QUIÉN (opts.clientId). Eso último
// es la única forma de que dos clientes no se crucen, y es lo que más importa.

function apiFalsa({ previewDe = () => ({ session_id: 'sess-1', errors: [] }), confirmDe = () => ({ operations_created: 3, cash_movements: 1, conversions: 0, auto_skipped_duplicates: 0 }), crearDe = () => ({ client_uid: 900 }), ...extra } = {}) {
  const llamadas = []
  return {
    llamadas,
    async post(path, body, opts) {
      llamadas.push({ path, body, clientId: opts?.clientId ?? null })
      if (path === '/advisor/clients') return crearDe(body)
      if (path === '/imports/confirm') {
        if (extra.confirmError) throw extra.confirmError
        return extra.confirm ? extra.confirm : confirmDe(body, opts)
      }
      throw new Error('ruta inesperada ' + path)
    },
    async upload(path, fd, opts) {
      llamadas.push({ path, files: fd.getAll('files').length, file: fd.get('file')?.name || null, broker: fd.get('broker'), format: fd.get('format'), tandaId: fd.get('tanda_id'), clientId: opts?.clientId ?? null })
      if (path === '/imports/classify-tenencia') return extra.classify ? extra.classify : (extra.classifyDe || (() => ({ file_name: null, format: null })))(fd)
      if (path === '/imports/tenencia/preview') {
        if (extra.tenenciaError) throw extra.tenenciaError
        return extra.tenencia ? extra.tenencia : (extra.tenenciaDe || (() => ({})))(fd, opts)
      }
      return previewDe(fd, opts)
    },
  }
}

const archivo = (n = 'a.csv') => new File(['x'], n, { type: 'text/csv' })
const fila = (extra = {}) => {
  const f = { id: 1, clientUid: 11, esNuevo: false, nombre: '', format: 'cocos', archivos: [archivo()], soloLectura: false, ...extra }
  f.archivos = f.archivos.map(a => (a instanceof File ? a : archivo(a.name)))
  return f
}

describe('filaLista / faltante', () => {
  it('una fila completa está lista y no le falta nada', () => {
    expect(filaLista(fila())).toBe(true)
    expect(faltante(fila())).toBeNull()
  })
  it('sólo lectura nunca está lista, aunque tenga todo', () => {
    expect(filaLista(fila({ soloLectura: true }))).toBe(false)
    expect(faltante(fila({ soloLectura: true }))).toBe('Sólo lectura: no podés cargarle archivos')
  })
  it('cliente nuevo necesita nombre; existente necesita uid entero', () => {
    expect(filaLista(fila({ esNuevo: true, clientUid: null, nombre: '  ' }))).toBe(false)
    expect(filaLista(fila({ esNuevo: true, clientUid: null, nombre: 'Lucía F' }))).toBe(true)
    expect(faltante(fila({ clientUid: '11' }))).toBe('Falta el cliente')
    expect(faltante(fila({ format: '' }))).toBe('Falta el broker')
    expect(faltante(fila({ archivos: [] }))).toBe('Faltan archivos')
  })
})

describe('estadoFinal', () => {
  it('cuenta lo ESCRITO por el confirm (compras incluidas), no filas del archivo', () => {
    const r = estadoFinal({ errors: [] }, { positions_created: 2, operations_created: 5, cash_movements: 2, conversions: 1, auto_skipped_duplicates: 4 })
    expect(r.estado).toBe(ESTADO.COMPLETO)
    expect(r.cargados).toBe(10)
    expect(r.repetidos).toBe(4)
    expect(r.notas).toEqual(['4 repetidos omitidos'])
  })
  it('errores del preview se informan sin frenar', () => {
    const r = estadoFinal({ errors: [{}, {}, {}] }, { operations_created: 1 })
    expect(r.estado).toBe(ESTADO.COMPLETO)
    expect(r.errores).toBe(3)
    expect(r.notas).toEqual(['3 filas con error, omitidas'])
  })
  it('si faltan posiciones previas queda en REVISAR, no en completo', () => {
    const r = estadoFinal({ errors: [], seed_suggestions: { needed: true } }, { operations_created: 9 })
    expect(r.estado).toBe(ESTADO.REVISAR)
    expect(r.cargados).toBe(9)
    expect(r.detalle).toMatch(/posiciones previas|fondeo inicial/)
  })
})

describe('correrTanda', () => {
  it('corre EN SERIE y cada pedido va a nombre del cliente de SU fila, nunca del contexto', async () => {
    const orden = []
    const api = apiFalsa({
      previewDe: (fd, opts) => { orden.push('p' + opts.clientId); return { session_id: 's' + opts.clientId, errors: [] } },
      confirmDe: (body, opts) => { orden.push('c' + opts.clientId); return { operations_created: 1 } },
    })
    const filas = [fila({ id: 1, clientUid: 11 }), fila({ id: 2, clientUid: 22, format: 'iol' })]
    const r = await correrTanda(filas, { api })
    expect(orden).toEqual(['p11', 'c11', 'p22', 'c22'])
    const confirms = api.llamadas.filter(l => l.path === '/imports/confirm')
    expect(confirms.map(c => c.clientId)).toEqual([11, 22])
    expect(confirms.map(c => c.body.session_id)).toEqual(['s11', 's22'])
    expect(r.total).toBe(2); expect(r.completos).toBe(2)
  })

  it('la tanda NO pregunta: sin seed_state, sin include_duplicates, aprobar_tickers vacío', async () => {
    const api = apiFalsa()
    await correrTanda([fila()], { api })
    const c = api.llamadas.find(l => l.path === '/imports/confirm')
    expect(c.body).toEqual({ session_id: 'sess-1', skip_row_indices: [], aprobar_tickers: [] })
    expect('seed_state' in c.body).toBe(false)
    expect('include_duplicates' in c.body).toBe(false)
  })

  it('si el preview falla, NO se confirma y se muestra el motivo del backend', async () => {
    const api = apiFalsa({ previewDe: () => { const e = new Error('HTTP 400'); e.payload = { detail: 'El archivo no es el formato de Bull Market.' }; throw e } })
    const updates = []
    const r = await correrTanda([fila()], { api, onUpdate: (id, p) => updates.push(p) })
    expect(api.llamadas.some(l => l.path === '/imports/confirm')).toBe(false)
    expect(r.errores).toBe(1)
    expect(updates.at(-1).estado).toBe(ESTADO.ERROR)
    expect(updates.at(-1).detalle).toBe('El archivo no es el formato de Bull Market.')
  })

  it('un cliente nuevo se crea primero y el uid creado es el que viaja en preview y confirm', async () => {
    const api = apiFalsa({ crearDe: () => ({ client_uid: 777 }) })
    const updates = []
    await correrTanda([fila({ esNuevo: true, clientUid: null, nombre: ' Lucía F ' })], { api, onUpdate: (id, p) => updates.push(p) })
    expect(api.llamadas[0]).toMatchObject({ path: '/advisor/clients', body: { label: 'Lucía F' } })
    expect(api.llamadas[1]).toMatchObject({ path: '/imports/classify-tenencia', clientId: 777 })
    expect(api.llamadas[2]).toMatchObject({ path: '/imports/preview', clientId: 777, files: 1, format: 'cocos' })
    expect(api.llamadas[3]).toMatchObject({ path: '/imports/confirm', clientId: 777 })
    expect(updates.some(u => u.creado === true && u.clientUid === 777)).toBe(true)
  })

  it('una fila que falla no frena a la siguiente', async () => {
    let n = 0
    const api = apiFalsa({ previewDe: () => { n += 1; if (n === 1) throw new Error('rompió'); return { session_id: 'ok', errors: [] } } })
    const r = await correrTanda([fila({ id: 1 }), fila({ id: 2, clientUid: 22 })], { api })
    expect(r.errores).toBe(1); expect(r.completos).toBe(1)
  })

  it('una fila incompleta o de sólo lectura no genera ningún pedido', async () => {
    const api = apiFalsa()
    const r = await correrTanda([fila({ soloLectura: true }), fila({ archivos: [] })], { api })
    expect(api.llamadas).toEqual([])
    expect(r.errores).toBe(2)
  })

  it('abortar corta ANTES de la fila siguiente, nunca a mitad de una', async () => {
    const ac = new AbortController()
    const api = apiFalsa({ confirmDe: () => { ac.abort(); return { operations_created: 1 } } })
    const r = await correrTanda([fila({ id: 1 }), fila({ id: 2, clientUid: 22 })], { api, signal: ac.signal })
    expect(api.llamadas.filter(l => l.path === '/imports/confirm')).toHaveLength(1)
    expect(r.total).toBe(1)
  })
})

describe('resumen', () => {
  it('suma movimientos, repetidos y filas con error de todas las filas', () => {
    const r = resumen([
      { estado: ESTADO.COMPLETO, cargados: 10, repetidos: 2, errores: 0 },
      { estado: ESTADO.REVISAR, cargados: 5, repetidos: 0, errores: 3 },
      { estado: ESTADO.ERROR },
    ])
    expect(r).toMatchObject({ total: 3, completos: 1, revisar: 1, fotos: 0, errores: 1, movimientos: 15, repetidos: 2, filasConError: 3 })
  })
})

// ── Lo que la auditoría de F1 encontró que la tanda "perdía en silencio" ──────
import { archivoAceptado } from './tandaImport'

describe('estadoFinal — lo que el asistente pregunta y la tanda no puede', () => {
  const okConfirm = { positions_created: 1, cash_movements: 1 }
  it('traspaso entre brokers del mismo cliente → REVISAR (si no, el título se cuenta dos veces)', () => {
    const r = estadoFinal({ errors: [], traspasos: [{ activo: 'GGAL', broker_origen: 'Bull Market', cantidad: 100 }] }, okConfirm)
    expect(r.estado).toBe(ESTADO.REVISAR)
    expect(r.detalle).toMatch(/GGAL.*Bull Market/)
  })
  it('filas que el guardado no pudo escribir (skipped_rows) → REVISAR con el motivo', () => {
    const r = estadoFinal({ errors: [] }, { ...okConfirm, skipped_rows: [{ row_index: 3, message: 'Broker no encontrado' }] })
    expect(r.estado).toBe(ESTADO.REVISAR)
    expect(r.detalle).toContain('Broker no encontrado')
  })
  it('filas que exigen aprobación (skipped_pending_approval) → REVISAR', () => {
    expect(estadoFinal({ errors: [] }, { ...okConfirm, skipped_pending_approval: 2 }).estado).toBe(ESTADO.REVISAR)
  })
  it('caja negativa al terminar → REVISAR nombrando el broker', () => {
    const r = estadoFinal({ errors: [] }, { ...okConfirm, cash_health: [{ broker: 'Balanz', currency: 'ARS', balance: -1500 }] })
    expect(r.estado).toBe(ESTADO.REVISAR)
    expect(r.detalle).toContain('Balanz ARS')
  })
  it('post-proceso con error → REVISAR (antes fallaba en silencio)', () => {
    const r = estadoFinal({ errors: [] }, { ...okConfirm, post_proceso: { rebuild: 'error' } })
    expect(r.estado).toBe(ESTADO.REVISAR)
    expect(r.detalle).toMatch(/recálculo/)
  })
  it('estado inicial por caja (sin ventas) explica el fondeo, no ventas fantasma', () => {
    const r = estadoFinal({ errors: [], seed_suggestions: { needed: true, totals: { sell_errors: 0 } } }, okConfirm)
    expect(r.detalle).toMatch(/fondeo inicial/)
    const v = estadoFinal({ errors: [], seed_suggestions: { needed: true, totals: { sell_errors: 2 } } }, okConfirm)
    expect(v.detalle).toMatch(/ventas de activos/)
  })
  it('cuenta FILAS con error (summary.invalid_rows), no entradas de error', () => {
    const r = estadoFinal({ errors: [{}, {}], summary: { invalid_rows: 1 } }, okConfirm)
    expect(r.errores).toBe(1)
    expect(r.notas).toEqual(['1 fila con error, omitida'])
  })
})

describe('correrTanda — reintentos, duplicados y tope de altas', () => {
  it('al crear un cliente nuevo la fila pasa a esNuevo:false (reintentar no lo crea de nuevo)', async () => {
    const api = apiFalsa({ crearDe: () => ({ client_uid: 55 }) })
    const updates = []
    await correrTanda([fila({ esNuevo: true, clientUid: null, nombre: 'Lucía F' })], { api, onUpdate: (id, p) => updates.push(p) })
    expect(updates.some(u => u.esNuevo === false && u.clientUid === 55 && u.label === 'Lucía F')).toBe(true)
  })
  it('el mismo cliente nuevo en dos filas se crea UNA vez', async () => {
    const api = apiFalsa({ crearDe: () => ({ client_uid: 66 }) })
    await correrTanda([
      fila({ id: 1, esNuevo: true, clientUid: null, nombre: 'Ana G' }),
      fila({ id: 2, esNuevo: true, clientUid: null, nombre: ' ana g ', format: 'balanz_movimientos' }),
    ], { api })
    expect(api.llamadas.filter(l => l.path === '/advisor/clients')).toHaveLength(1)
    expect(api.llamadas.filter(l => l.path === '/imports/confirm').map(c => c.clientId)).toEqual([66, 66])
  })
  it('429 al crear: espera y reintenta una vez', async () => {
    let n = 0
    const api = apiFalsa({ crearDe: () => { n += 1; if (n === 1) { const e = new Error('HTTP 429'); e.status = 429; throw e } return { client_uid: 77 } } })
    const esperas = []
    const r = await correrTanda([fila({ esNuevo: true, clientUid: null, nombre: 'Diego S' })], { api, dormir: async (ms) => { esperas.push(ms) } })
    expect(esperas).toEqual([61_000])
    expect(r.completos).toBe(1)
  })
  it('archivo idéntico a uno ya cargado: no se confirma y queda Completo con nota', async () => {
    const api = apiFalsa({ previewDe: () => ({ session_id: 's', errors: [], duplicate_of_batch_id: 'viejo' }) })
    const updates = []
    const r = await correrTanda([fila()], { api, onUpdate: (id, p) => updates.push(p) })
    expect(api.llamadas.some(l => l.path === '/imports/confirm')).toBe(false)
    expect(r.completos).toBe(1)
    expect(updates.at(-1).notas[0]).toMatch(/idéntico/)
  })
  it('si el confirm cae con 502, la fila queda "incierta" (no "no se tocó nada")', async () => {
    const api = apiFalsa({ confirmDe: () => { const e = new Error('gateway'); e.status = 502; throw e } })
    const updates = []
    await correrTanda([fila()], { api, onUpdate: (id, p) => updates.push(p) })
    expect(updates.at(-1)).toMatchObject({ estado: ESTADO.ERROR, incierto: true, status: 502 })
    const api4 = apiFalsa({ previewDe: () => { const e = new Error('x'); e.status = 400; e.payload = { detail: 'formato' }; throw e } })
    const u4 = []
    await correrTanda([fila()], { api: api4, onUpdate: (id, p) => u4.push(p) })
    expect(u4.at(-1)).toMatchObject({ incierto: false, detalle: 'formato' })
  })
  it('nunca manda un pedido sin cliente identificado', async () => {
    const api = apiFalsa({ crearDe: () => ({}) })
    const r = await correrTanda([fila({ esNuevo: true, clientUid: null, nombre: 'X' })], { api })
    expect(api.llamadas.some(l => l.path === '/imports/preview')).toBe(false)
    expect(r.errores).toBe(1)
  })
})

describe('archivoAceptado', () => {
  it('acepta csv/xlsx/xls/txt y, desde F3, el pdf de la foto; rechaza el resto', () => {
    expect(archivoAceptado('a.CSV')).toBe(true)
    expect(archivoAceptado('b.xlsx')).toBe(true)
    expect(archivoAceptado('resumen.pdf')).toBe(true)
    expect(archivoAceptado('foto.png')).toBe(false)
  })
})

describe('correrTanda — tanda del servidor (F2)', () => {
  it('manda tanda_id en cada preview cuando la tanda existe en el servidor', async () => {
    const api = apiFalsa()
    await correrTanda([fila({ id: 1 }), fila({ id: 2, clientUid: 22 })], { api, tandaId: 'abc123' })
    const previews = api.llamadas.filter(l => l.path === '/imports/preview')
    expect(previews.map(p => p.tandaId)).toEqual(['abc123', 'abc123'])
  })
  it('sin tanda no manda el campo (compatibilidad con el importador de siempre)', async () => {
    const api = apiFalsa()
    await correrTanda([fila()], { api })
    expect(api.llamadas.find(l => l.path === '/imports/preview').tandaId).toBeNull()
  })
})

import { filaAlServidor, filaDelServidor, fechaServidor, marcarInterrumpidas } from './tandaImport'

describe('contrato con el servidor (F2)', () => {
  it('ida y vuelta sin perder lo que la pantalla necesita', () => {
    const f = { id: 7, clientUid: 44, esNuevo: false, nombre: '', label: 'Ana G', platform: 'cocos', platformLabel: 'Cocos Capital',
      format: 'cocos', archivos: [{ name: 'C:\\Users\\x\\cocos-2024.csv', size: 10 }], estado: ESTADO.ERROR, batchId: 'b1',
      cargados: 3, repetidos: 1, errores: 2, detalle: 'gateway', notas: ['ya estaba cargado'], creado: true, incierto: true }
    const vuelta = filaDelServidor(filaAlServidor(f))
    expect(vuelta).toMatchObject({ id: 7, clientUid: 44, label: 'Ana G', platform: 'cocos', platformLabel: 'Cocos Capital',
      estado: ESTADO.ERROR, batchId: 'b1', cargados: 3, repetidos: 1, errores: 2, detalle: 'gateway', notas: ['ya estaba cargado'], creado: true, incierto: true })
    expect(vuelta.archivos).toEqual([{ name: 'cocos-2024.csv', size: 0 }])
  })
  it('un cliente nuevo todavía sin cuenta viaja con client_uid null y vuelve sin uid', () => {
    const v = filaDelServidor(filaAlServidor({ id: 1, esNuevo: true, nombre: 'Lucía F', archivos: [], estado: ESTADO.PENDIENTE }))
    expect(v.clientUid).toBeNull(); expect(v.label).toBe('Lucía F')
  })
  it('fechaServidor entiende el formato de SQLite (espacio, UTC)', () => {
    expect(fechaServidor('2026-09-20 14:01:02')).toBe(Date.parse('2026-09-20T14:01:02Z'))
    expect(fechaServidor(null)).toBeNull(); expect(fechaServidor('nada')).toBeNull()
  })
  it('marcarInterrumpidas convierte cargando/pendiente en error explicado', () => {
    const r = marcarInterrumpidas([{ estado: ESTADO.CARGANDO }, { estado: ESTADO.PENDIENTE }, { estado: ESTADO.COMPLETO }])
    expect(r.map(x => x.estado)).toEqual([ESTADO.ERROR, ESTADO.ERROR, ESTADO.COMPLETO])
    expect(r[0].incierto).toBe(true); expect(r[1].incierto).toBe(false)
  })
})

import { aplicarFoto, omitirFoto, fusionarFotosLocales } from './tandaImport'

describe('F3 — la foto de tenencia adentro de la fila', () => {
  const mov = archivo('cocos-mov.csv'); const pdf = archivo('tenencia.pdf')
  it('clasifica, importa primero los movimientos y después compara la foto; con algo que decidir queda foto_pendiente', async () => {
    const api = apiFalsa({ classifyDe: () => ({ file_name: 'tenencia.pdf', format: 'bullmarket' }), tenenciaDe: () => ({ session_id: 'foto-1', to_seed: [{ ticker: 'GGAL' }] }) })
    const updates = []
    const r = await correrTanda([fila({ archivos: [mov, pdf], format: 'bullmarket' })], { api, onUpdate: (id, p) => updates.push(p) })
    const paths = api.llamadas.map(l => l.path)
    expect(paths).toEqual(['/imports/classify-tenencia', '/imports/preview', '/imports/confirm', '/imports/tenencia/preview'])
    expect(api.llamadas[1].files).toBe(1)                       // sólo movimientos al preview
    expect(api.llamadas[3]).toMatchObject({ file: 'tenencia.pdf', broker: 'Bull Market', format: 'bullmarket', clientId: 11 })
    const fin = updates.at(-1)
    expect(fin.estado).toBe(ESTADO.FOTO_PENDIENTE)
    expect(fin.estadoMovimientos).toBe(ESTADO.COMPLETO)
    expect(fin.foto.session_id).toBe('foto-1')
    expect(r.fotos).toBe(1); expect(r.revisar).toBe(1)
  })
  it('si la foto coincide con todo, la fila sigue Completo con la nota', async () => {
    const api = apiFalsa({ classifyDe: () => ({ file_name: 'tenencia.pdf', format: 'bullmarket' }), tenenciaDe: () => ({ ok: true }) })
    const updates = []
    await correrTanda([fila({ archivos: [mov, pdf], format: 'bullmarket' })], { api, onUpdate: (id, p) => updates.push(p) })
    expect(updates.at(-1).estado).toBe(ESTADO.COMPLETO)
    expect(updates.at(-1).notas.join(' ')).toMatch(/todo coincide/)
  })
  it('si el servidor no pudo comparar la foto (sin fecha), la fila queda Revisar con su motivo, no "todo coincide"', async () => {
    const api = apiFalsa({ classifyDe: () => ({ file_name: 'tenencia.pdf', format: 'bullmarket' }), tenenciaDe: () => ({ session_id: null, nothing_to_do: true, motivo: 'fecha_desconocida', message: 'No pudimos leer la fecha de este resumen.' }) })
    const updates = []
    await correrTanda([fila({ archivos: [mov, pdf], format: 'bullmarket' })], { api, onUpdate: (id, p) => updates.push(p) })
    expect(updates.at(-1).estado).toBe(ESTADO.REVISAR)
    expect(updates.at(-1).detalle).toMatch(/No pudimos leer la fecha/)
  })
  it('sólo la foto, sin movimientos: la fila no se carga y lo dice', async () => {
    const api = apiFalsa({ classifyDe: () => ({ file_name: 'tenencia.pdf', format: 'bullmarket' }) })
    const r = await correrTanda([fila({ archivos: [pdf], format: 'bullmarket' })], { api })
    expect(api.llamadas.some(l => l.path === '/imports/preview')).toBe(false)
    expect(r.errores).toBe(1)
  })
  it('un solo archivo también pasa por el clasificador (el Estado de Cuenta solo es foto, no movimientos)', async () => {
    const api = apiFalsa()
    await correrTanda([fila()], { api })
    expect(api.llamadas.map(l => l.path)).toEqual(['/imports/classify-tenencia', '/imports/preview', '/imports/confirm'])
  })
  it('dos fotos en la fila: no se carga nada y lo dice', async () => {
    const api = apiFalsa({ classify: { file_name: 'a.pdf', format: 'bullmarket', files: [{ file_name: 'a.pdf', format: 'bullmarket' }, { file_name: 'b.pdf', format: 'bullmarket' }] } })
    const cambios = []
    await correrTanda([fila({ archivos: [{ name: 'mov.csv' }, { name: 'a.pdf' }, { name: 'b.pdf' }] })], { api, onUpdate: (id, p) => cambios.push(p) })
    const fin = cambios.at(-1)
    expect(fin.estado).toBe(ESTADO.ERROR)
    expect(fin.detalle).toMatch(/2 fotos/)
    expect(api.llamadas.map(l => l.path)).toEqual(['/imports/classify-tenencia'])
  })
  it('si el servidor no pudo ni comparar la foto (400), la fila queda Revisar, no Completo con nota', async () => {
    const api = apiFalsa({ classify: { file_name: 'foto.pdf', format: 'bullmarket' }, tenenciaError: Object.assign(new Error('x'), { status: 400, payload: { detail: "No encontramos el broker 'PPI'." } }) })
    const cambios = []
    await correrTanda([fila({ archivos: [{ name: 'mov.csv' }, { name: 'foto.pdf' }] })], { api, onUpdate: (id, p) => cambios.push(p) })
    const fin = cambios.at(-1)
    expect(fin.estado).toBe(ESTADO.REVISAR)
    expect(fin.detalle).toMatch(/No encontramos el broker/)
  })
  it('la foto viaja con el tanda_id (su lote también es de la tanda)', async () => {
    const api = apiFalsa({ classify: { file_name: 'foto.pdf', format: 'bullmarket' }, tenencia: { session_id: 'sf', to_seed: [{ ticker: 'GGAL', qty: 1 }] } })
    await correrTanda([fila({ archivos: [{ name: 'mov.csv' }, { name: 'foto.pdf' }] })], { api, tandaId: 'T1' })
    const tp = api.llamadas.find(l => l.path === '/imports/tenencia/preview')
    expect(tp.tandaId).toBe('T1')
  })
  it('aplicarFoto lee la respuesta: lo que la foto escribió suma, y un recálculo fallido vuelve la fila a Revisar', async () => {
    const api = apiFalsa({ confirm: { ok: true, positions_created: 2, post_proceso: { rebuild: 'error' } } })
    const r = await aplicarFoto(api, { id: 1, clientUid: 7, cargados: 10, foto: { session_id: 'sf' }, estadoMovimientos: ESTADO.COMPLETO, notas: [] }, ['GGAL'])
    expect(r.cargados).toBe(12)
    expect(r.estado).toBe(ESTADO.REVISAR)
    expect(r.fotoBatchId).toBe('sf')
  })
  it('aplicarFoto con el borrador vencido: la fila queda Revisar y lo explica (no "omitida")', async () => {
    const api = apiFalsa({ confirmError: Object.assign(new Error('x'), { status: 400, payload: { detail: 'Sesión de import no encontrada o expirada.' } }) })
    const r = await aplicarFoto(api, { id: 1, clientUid: 7, foto: { session_id: 'sf' }, estadoMovimientos: ESTADO.COMPLETO, notas: [] }, [])
    expect(r.estado).toBe(ESTADO.REVISAR)
    expect(r.detalle).toMatch(/venció/)
    expect(r.foto).toBeNull()
  })
  it('contrato ida/vuelta guarda la foto (session, lote, estado de los movimientos)', () => {
    const f = { id: 3, clientUid: 7, label: 'Ana', platform: 'cocos', platformLabel: 'Cocos', archivos: [], estado: ESTADO.FOTO_PENDIENTE, batchId: 'b1', fotoBatchId: null, estadoMovimientos: ESTADO.COMPLETO, foto: { session_id: 'sf', nombre: 'p.csv', to_seed: [] } }
    const v = filaDelServidor(filaAlServidor(f))
    expect(v.foto).toEqual({ session_id: 'sf', nombre: 'p.csv', sinDetalle: true })
    expect(v.estadoMovimientos).toBe(ESTADO.COMPLETO)
    const fus = fusionarFotosLocales([v], [f])
    expect(fus[0].foto.to_seed).toEqual([])
  })
  it('aplicarFoto confirma con los tickers aprobados a nombre del cliente y devuelve la fila a su estado', async () => {
    const api = apiFalsa()
    const f = { clientUid: 11, estado: ESTADO.FOTO_PENDIENTE, estadoMovimientos: ESTADO.REVISAR, foto: { session_id: 'foto-1' }, notas: ['x'] }
    const patch = await aplicarFoto(api, f, new Set(['GGAL']))
    expect(api.llamadas.at(-1)).toMatchObject({ path: '/imports/confirm', clientId: 11, body: { session_id: 'foto-1', aprobar_tickers: ['GGAL'] } })
    expect(patch.estado).toBe(ESTADO.REVISAR); expect(patch.foto).toBeNull()
    expect(omitirFoto(f).estado).toBe(ESTADO.REVISAR)
    expect(omitirFoto(f).notas.at(-1)).toMatch(/omitida/)
  })
})

describe('resumen después de un Deshacer que falló', () => {
  it('lo que no se pudo revertir SIGUE cargado: suma movimientos y no cuenta como revertido', () => {
    const r = resumen([
      { id: 1, clientUid: 7, estado: 'revert_fallo', cargados: 13 },
      { id: 2, clientUid: 8, estado: 'revert_fallo', cargados: 13 },
      { id: 3, clientUid: 9, estado: 'revertido', cargados: 5 },
    ])
    expect(r.movimientos).toBe(26)
    expect(r.clientesCargados).toBe(2)
    expect(r.noRevertidos).toBe(2)
    expect(r.revertidos).toBe(1)
  })
})
