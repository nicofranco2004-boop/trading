/**
 * moverDeBroker — la lógica pura de «Mover a otro broker» (sin React, sin pedidos).
 *
 * QUÉ ES UN PASE. Los títulos se van de un broker tuyo (A) a otro broker tuyo (B)
 * con su costo y su fecha de compra originales. No es una venta: en A figura la
 * diferencia entre lo que valían ese día y lo que costaron (el «puente»), y en B
 * arrancan valiendo eso. El servidor arma y guarda todo (POST
 * /api/positions/traspaso y su vista previa); la pantalla sólo decide qué ofrecer
 * y cómo decirlo. Este archivo es el espejo de PANTALLA de esas reglas:
 *
 *   · `puedeMoverse`   — qué filas de la Cartera muestran la opción en el menú ⋯.
 *   · `destinosPosibles` — a qué cuentas se puede pasar (la misma familia: un
 *     CEDEAR no puede ir a un broker de afuera; la regla C.1 del servidor).
 *   · `cuerpoDeMover`  — el pedido, leído con el ÚNICO parser de números.
 *   · los textos de la vista previa (lotes, fuente del precio, el puente).
 *
 * El servidor vuelve a validar todo: si esto ofrece de más, el servidor frena con
 * su mensaje. Lo que NO puede pasar es lo contrario (esconder un pase posible).
 */
import { brokersParaElegir, cuentaDe } from './pataDeLaMoneda'
import { parseNum, fmtMoney, fmtUsd } from './format'
import { isFciSym } from './valuation'
import { isBondPosition } from './tickers'
import { OCULTO } from './ocultarSaldos'

const _ccy = (b) => String(b?.currency || '').toUpperCase()

/** Wallbit se sincroniza sola con la cuenta real: no se le pasan ni sacan títulos a mano. */
export function esWallbit(nombre) {
  return String(nombre || '').trim().toLowerCase() === 'wallbit'
}

/**
 * La familia de la CUENTA de `nombre` (su padre si es una pata en dólares), con la
 * misma regla que el servidor (`traspaso_a_mano` C.1, que lee
 * `snapshots_job._broker_name_sets` y `cripto.is_exchange_broker`):
 *   'AR'        cuenta argentina (en pesos, o un «X · USD» suelto de datos viejos)
 *   'EXCHANGE'  exchange cripto (`is_exchange`, que estampa GET /api/brokers)
 *   'EXTERIOR'  broker de afuera
 * null si el broker no está en la lista.
 */
export function familiaDeCuenta(nombre, brokers) {
  const lista = brokers || []
  const raiz = cuentaDe(nombre, lista)
  const b = lista.find((x) => x.name === raiz)
  if (!b) return null
  // El sufijo «· USD» sin distinguir mayúsculas: el servidor pasa el nombre a
  // minúsculas antes de comparar (`_is_ar_usd_subbroker`).
  if (_ccy(b) === 'ARS' || (b.parent_broker_id == null && /·\s*usd$/i.test(b.name || ''))) return 'AR'
  if (b.is_exchange) return 'EXCHANGE'
  return 'EXTERIOR'
}

const _esBono = (l) => !!l && (String(l.asset_type || '').toUpperCase() === 'BOND' || isBondPosition(l))
const _esFondo = (l) => !!l && (isFciSym(l.asset) || String(l.asset_type || '').toUpperCase() === 'FUND')

/**
 * ¿Esta fila de la Cartera ofrece «Mover a otro broker»? No en efectivo, ni en
 * bonos o letras (tampoco en la fila AGREGADA, que antes no miraba `isBond`), ni
 * en fondos comunes, ni en Wallbit. `opts.isBond` es lo que ya calculó la pantalla.
 */
export function puedeMoverse(p, { isBond = false } = {}) {
  if (!p || p.is_cash) return false
  const asset = String(p.asset || '').toUpperCase()
  if (asset === 'USD' || asset === 'USDT' || asset === 'ARS') return false
  if (isBond || _esBono(p) || _esFondo(p) || esWallbit(p.broker)) return false
  const lotes = Array.isArray(p._lots) ? p._lots : []
  if (lotes.some((l) => l?.is_cash || _esBono(l) || _esFondo(l) || esWallbit(l?.broker))) return false
  return true
}

/**
 * Las cuentas a las que se puede pasar la opción `opcion` (una de
 * `opcionesDeVenta`: cuenta + activo + moneda): cuentas raíz (sin las patas en
 * dólares, que el servidor elige solo), sin la de origen, sin las de otra familia
 * y sin Wallbit. Vacío = no hay a dónde pasarlo (la pantalla ofrece crear uno).
 */
export function destinosPosibles(opcion, brokers) {
  const lista = brokers || []
  if (!opcion) return []
  const origen = cuentaDe(opcion.cuenta || opcion.broker, lista)
  const familia = familiaDeCuenta(origen, lista)
  if (!familia) return []
  return brokersParaElegir(lista)
    .filter((b) => cuentaDe(b.name, lista) === b.name)
    .filter((b) => b.name !== origen && !esWallbit(b.name))
    .filter((b) => familiaDeCuenta(b.name, lista) === familia)
}

/** ¿La cuenta de `nombre` tiene caja en pesos y en dólares? (una cuenta argentina) */
export function admiteGastoEnDosMonedas(nombre, brokers) {
  return familiaDeCuenta(nombre, brokers) === 'AR'
}

/**
 * El pedido del formulario, listo para el servidor, o el primer error.
 *
 * `form`: { destino, fecha, cantidad, precioManual, gastoMonto, gastoMoneda }.
 * La cantidad vacía es «todo lo que había en A ese día» (el servidor la completa).
 * Los números se leen con `parseNum` («1.000,5» = mil y medio): ningún otro parser.
 * @returns {{ body: object } | { error: string }}
 */
export function cuerpoDeMover(form = {}, opcion) {
  if (!opcion) return { error: 'Elegí qué querés mover.' }
  const destino = String(form.destino || '').trim()
  if (!destino) return { error: 'Elegí a qué broker lo pasás.' }
  const fecha = String(form.fecha || '').trim()
  if (!fecha) return { error: 'Elegí la fecha del pase.' }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(fecha)) return { error: 'Fecha inválida. Usá el formato día/mes/año.' }
  const body = {
    broker_origen: opcion.broker,
    asset: opcion.asset,
    moneda: String(opcion.moneda || '').toUpperCase() === 'ARS' ? 'ARS' : 'USD',
    broker_destino: destino,
    fecha,
  }
  const cantidad = String(form.cantidad ?? '').trim()
  if (cantidad) {
    const q = parseNum(cantidad)
    if (!(q > 0)) return { error: 'Escribí una cantidad mayor a 0.' }
    body.cantidad = q
  }
  const precio = String(form.precioManual ?? '').trim()
  if (precio) {
    const v = parseNum(precio)
    if (!(v > 0)) return { error: 'Escribí un precio mayor a 0.' }
    body.precio_manual = v
  }
  const gasto = String(form.gastoMonto ?? '').trim()
  if (gasto) {
    const g = parseNum(gasto)
    if (!(g > 0)) return { error: 'El gasto del trámite tiene que ser mayor a 0.' }
    body.gasto = { monto: g, moneda: String(form.gastoMoneda || '').toUpperCase() === 'USD' ? 'USD' : 'ARS' }
  }
  return { body }
}

// ─── Fechas y textos ────────────────────────────────────────────────────────

const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado']

/** '2026-11-20' → '20/11/2026'. */
export function fechaDelPase(iso) {
  if (!iso || String(iso).length < 10) return ''
  const s = String(iso).slice(0, 10)
  return `${s.slice(8, 10)}/${s.slice(5, 7)}/${s.slice(0, 4)}`
}

/** '2026-11-20' → 'viernes 20/11' (el día de la semana en UTC: no corre por el huso). */
export function diaDeLaSemana(iso) {
  if (!iso || String(iso).length < 10) return ''
  const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number)
  const dia = DIAS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]
  return `${dia} ${String(iso).slice(8, 10)}/${String(iso).slice(5, 7)}`
}

/**
 * De dónde salió el precio con que se valuó el pase (B.1 `fuente`), dicho para el
 * renglón «Valían … el dd/mm/aaaa · {esto}». Si la vela es de otro día que el del
 * pase (un feriado, un fin de semana), se dice cuál: «cierre del viernes 20/11».
 */
export function textoDeFuente(fuente, fechaPrecio, fechaPase) {
  const otroDia = !!fechaPrecio && !!fechaPase && String(fechaPrecio).slice(0, 10) !== String(fechaPase).slice(0, 10)
  switch (fuente) {
    case 'cierre_del_dia':
      return otroDia ? `cierre del ${diaDeLaSemana(fechaPrecio)}` : 'cierre de ese día'
    case 'ultimo_precio':
      return otroDia ? `cierre del ${diaDeLaSemana(fechaPrecio)}` : 'último precio que tenemos'
    case 'precio_a_mano':
      return 'precio que escribiste'
    case 'precio_cargado':
      return 'precio que cargaste a mano'
    default:
      return ''
  }
}

/** Una cantidad de títulos como se lee en es-AR, con hasta 6 decimales. */
export function cantidadDeTitulos(q) {
  const n = Number(q)
  if (!Number.isFinite(n)) return '—'
  return n.toLocaleString('es-AR', { maximumFractionDigits: 6 })
}

/** El formateador de montos de la vista previa: tapa todo con el ojito prendido. */
export function formateadorDeMontos(hidden) {
  return {
    dinero: (n, moneda) => (hidden ? OCULTO : fmtMoney(n, moneda || 'USD')),
    usd: (n) => (hidden ? OCULTO : fmtUsd(n)),
  }
}

/**
 * El renglón de un lote de la vista previa:
 * «4 NVDA · comprados el 10/03/2024 · costo $120.000 ARS · parte de un lote de 6».
 * `fmt` = `formateadorDeMontos(hidden)`: la cantidad y la fecha quedan siempre a la vista.
 */
export function lineaDeLote(l, asset, fmt = formateadorDeMontos(false)) {
  if (!l) return ''
  const partes = [
    `${cantidadDeTitulos(l.cantidad)} ${asset || ''}`.trim(),
    `comprados el ${fechaDelPase(l.fecha_compra) || 'sin fecha'}`,
    `costo ${fmt.dinero(l.costo, l.moneda)}`,
  ]
  const deUnLote = Number(l.de_un_lote_de)
  if (Number.isFinite(deUnLote) && deUnLote > Number(l.cantidad) + 1e-9) {
    partes.push(`parte de un lote de ${cantidadDeTitulos(deUnLote)}`)
  }
  if (l.a_mano) partes.push('cargado a mano')
  return partes.join(' · ')
}

/**
 * Los tres renglones del puente (E.2): cuánto costaron, qué va a figurar en cada
 * broker y la aclaración de que no es una venta. `A` y `B`, los nombres que se
 * muestran de cada cuenta.
 */
export function lineaDelPuente(plan, A, B, fmt = formateadorDeMontos(false)) {
  if (!plan) return []
  const puente = Number(plan.puente_usd) || 0
  const queda = puente >= 0
    ? `En ${A} va a figurar una ganancia de ${fmt.usd(puente)} hasta el pase, y en ${B} arrancan valiendo ${fmt.usd(plan.valor_usd)}.`
    : `En ${A} va a figurar una pérdida de ${fmt.usd(-puente)} hasta el pase, y en ${B} arrancan valiendo ${fmt.usd(plan.valor_usd)}.`
  return [
    `Te costaron ${fmt.usd(plan.costo_usd)}.`,
    queda,
    'No es una venta: no cuenta en tus operaciones cerradas ni en los impuestos.',
  ]
}

/**
 * El renglón del gasto del trámite, tal como lo entendió el servidor (`plan.gasto`):
 * «Gasto del trámite: $5.000 ARS de la caja de Cocos.». '' si no hay gasto. Sin
 * esto, un gasto escrito en el bloque plegable viajaba aunque el bloque estuviera
 * cerrado y no se viera en ningún lado antes de confirmar (revisión E12).
 */
export function lineaDelGasto(plan, A, fmt = formateadorDeMontos(false)) {
  const g = plan?.gasto
  if (!g || !(Number(g.monto) > 0)) return ''
  return `Gasto del trámite: ${fmt.dinero(g.monto, g.moneda)} de la caja de ${g.broker || A || 'tu broker'}.`
}

/** El renglón del valor: «Valían $250.000 ARS (USD 178,57) el 20/11/2026 · cierre de ese día». */
export function lineaDelValor(plan, fmt = formateadorDeMontos(false)) {
  if (!plan) return ''
  const v = plan.valuacion || {}
  const fuente = textoDeFuente(v.fuente, v.fecha_precio, plan.fecha)
  return `Valían ${fmt.dinero(plan.valor_nativo, v.moneda_precio)} (${fmt.usd(plan.valor_usd)}) el ${fechaDelPase(plan.fecha)}${fuente ? ` · ${fuente}` : ''}`
}

/** «pesos» | «dólares», para los textos que dicen en qué moneda escribir un precio. */
export function nombreDeMoneda(moneda) {
  return String(moneda || '').toUpperCase() === 'ARS' ? 'pesos' : 'dólares'
}

/**
 * El 409 «sin precio» de la vista previa viene como objeto en `detail`
 * ({codigo:'sin_precio', mensaje, moneda_precio}). Devuelve ese objeto o null.
 */
export function faltaPrecio(e) {
  const d = e?.payload?.detail
  return d && typeof d === 'object' && !Array.isArray(d) && d.codigo === 'sin_precio' ? d : null
}

// ─── Movimientos e Importaciones ────────────────────────────────────────────

/** ¿La fila de Movimientos es una pata de un pase (no se borra: se deshace)? */
export function esFilaDePase(m) {
  return m?.type === 'TRASPASO_SALIDA' || m?.type === 'TRASPASO_ENTRADA'
}

/** «10 NVDA → Balanz» (salió) o «10 NVDA ← Cocos» (entró). */
export function lineaDeFilaDePase(m) {
  if (!esFilaDePase(m)) return ''
  const flecha = m.type === 'TRASPASO_SALIDA' ? '→' : '←'
  const cant = m.quantity != null ? `${cantidadDeTitulos(Math.abs(Number(m.quantity)))} ` : ''
  return `${cant}${m.asset || ''} ${flecha} ${m.contraparte || 'otro broker tuyo'}`.trim()
}

/**
 * El aviso debajo de una fila de pase según su `estado`. La fila que se ve es de un
 * lado que sigue vivo, así que en un pase «incompleto» el que no existe es la
 * contraparte.
 *
 * «Desfasado»: el texto es el del SERVIDOR (`m.aviso`, el mismo de GET
 * /api/positions/traspasos), que nombra la cuenta cuya historia cambió —la de
 * destino si el detector lo marcó por ese lado—. Armado acá nombraba siempre la de
 * origen. Si la fila no lo trae (una respuesta vieja), se arma con la de origen.
 */
export function avisoDeFilaDePase(m) {
  if (!esFilaDePase(m)) return null
  if (m.estado === 'desfasado') {
    if (typeof m.aviso === 'string' && m.aviso.trim()) return m.aviso
    const A = m.type === 'TRASPASO_SALIDA' ? (m.broker || '') : (m.contraparte || '')
    return `Cambió la historia de ${A} y este pase quedó desactualizado: deshacelo y hacelo de nuevo.`
  }
  if (m.estado === 'incompleto') return `${m.contraparte || 'El otro broker'} ya no existe.`
  return null
}

/**
 * El «¿Deshacer…?» del botón de Movimientos, con el texto según el estado (C.8).
 * `t` = el pase de GET /api/positions/traspasos; `fila` = la fila tocada (dice
 * qué lado sobrevive cuando el pase está incompleto).
 */
export function preguntaDeDeshacer(t, fila) {
  const q = cantidadDeTitulos(t?.cantidad)
  const A = t?.broker_origen || ''
  const B = t?.broker_destino || ''
  const titulo = `¿Deshacer el pase de ${q} ${t?.asset || ''} de ${A} a ${B}?`
  let texto
  if (t?.estado === 'incompleto') {
    texto = fila?.type === 'TRASPASO_ENTRADA'
      ? `${A} ya no existe: al deshacer el pase, los ${q} ${t?.asset || ''} salen de ${B} y no vuelven a ningún lado.`
      : `${B} ya no existe: al deshacer el pase, los ${q} ${t?.asset || ''} vuelven a ${A} con su costo original, y si cargaste el gasto del trámite, vuelve a la caja.`
  } else {
    texto = `Los títulos vuelven a ${A} con su costo original, y si cargaste el gasto del trámite, vuelve a la caja.`
  }
  return `${titulo}\n\n${texto}`
}

/** El título de un lote de Importaciones que es un pase: «Pase de 10 NVDA a Balanz». */
export function tituloDeLotePase(traspaso) {
  if (!traspaso) return ''
  const hacia = traspaso.lado === 'entrada' ? 'desde' : 'a'
  return `Pase de ${cantidadDeTitulos(traspaso.cantidad)} ${traspaso.asset || ''} ${hacia} ${traspaso.contraparte || 'otro broker tuyo'}`
}

/**
 * Las filas que el cartel «filas ya estaban importadas» del importador cuenta: las
 * repetidas por HUELLA (misma fecha + broker + tipo + activo + cantidad + precio),
 * que es lo que ese cartel explica. El servidor manda en `duplicate_row_indices`
 * también las que omite POR UN PASE (`filas_de_pases`: la llegada o la salida y su
 * depósito compensatorio, D.2.3); ésas ya las dice el bloque «Ya las cargaste con
 * «Mover a otro broker»», y con otro motivo.
 */
export function repetidasPorHuella(preview) {
  const dePases = new Set(Array.isArray(preview?.filas_de_pases) ? preview.filas_de_pases : [])
  const todas = Array.isArray(preview?.duplicate_row_indices) ? preview.duplicate_row_indices : []
  return todas.filter((i) => !dePases.has(i))
}

/**
 * El bloque rojo del importador cuando el archivo cambiaría la historia anterior a
 * un pase (`preview.cambian_un_pase`). Si el servidor manda el texto armado
 * (`mensaje`), es ése; si manda los datos, se arma el `MSG_IMPORT_CAMBIA_UN_PASE`.
 */
export function textoDeImportCambiaUnPase(c) {
  if (!c) return ''
  if (typeof c === 'string') return c
  if (typeof c.mensaje === 'string' && c.mensaje.trim()) return c.mensaje
  const que = String(c.op || '').toUpperCase() === 'SELL' ? 'ventas' : 'compras'
  const hacia = c.lado === 'destino' || c.lado === 'entrada' || c.lado === 'B' ? 'desde' : 'a'
  const delArchivo = c.fecha_fila ? ` del ${fechaDelPase(c.fecha_fila)}` : ''
  return `Este archivo trae ${que} de ${c.asset || 'un activo'} en ${c.broker || 'tu broker'}${delArchivo}, ` +
    `anteriores a tu pase del ${fechaDelPase(c.fecha)} ${hacia} ${c.contraparte || 'otro broker tuyo'}. ` +
    'Si lo confirmamos, el pase quedaría con otros lotes. Deshacé el pase (Movimientos → la fila «Pase» → Deshacer), ' +
    'importá el archivo y volvé a moverlos.'
}
