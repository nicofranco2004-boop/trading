// AlertaForm — el formulario del aviso de precio, para crearlo y para editarlo.
// ═══════════════════════════════════════════════════════════════════════════
// Tres tipos, elegidos arriba con un selector:
//   • Llega a un precio  (price_target): "avisame cuando GGAL suba a $ 8.000".
//     Todos los planes.
//   • Se mueve un %      (pct_move): "avisame si algo de mi cartera cae 5 %".
//     Plus o más; el backend lo gatea igual (403 con {upgrade}).
//   • Señal técnica      (tecnica): "avisame cuando AAPL cruce su promedio de
//     200 días". Todos los planes. Se mira una vez por día con el cierre
//     (alerts_engine.evaluar_tecnicas). Desde la ficha técnica llega ya armada
//     (`prefill.fijo`: el activo y la marca de acción argentina los decidió la
//     ficha), sin el selector de tipo. También «una línea que dibujaste»
//     (Nico, 29/10): tu línea horizontal, de tendencia o tu canal, desde el
//     cartel de la línea elegida o acá, eligiéndola de tus dibujos del activo.
//
// Es un formulario de CAMPOS con su nombre, uno debajo del otro y todos del
// mismo alto. La versión anterior armaba una frase con casilleros adentro y se
// cortaba en cualquier renglón según el ancho. La frase no se perdió: abajo de
// todo, `confirmacion()` cuenta en palabras lo que armaste — no se escribe ahí,
// se lee.
//
// Por dónde avisa y cuántas veces quedan plegados en una línea («Por mail y
// celular · una vez · cambiar»): casi nadie los cambia y antes eran la mitad
// de los botones del formulario. Por eso el «cuántas veces» de arranque tiene
// que ser el que sirve: ver `repeticionPorDefecto`.
//
// Editar: el servidor deja cambiar el precio, la dirección, los %, el canal y
// la repetición. El activo y lo que se vigila, no: para eso se arma otra.
//
// Sistema visual: generación nueva — Modal (sheet en celular), campos
// rounded-lg, rótulos sans sentence-case, números con `tabular`.
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bell, TrendingUp, TrendingDown, Search, Briefcase, Mail, Smartphone } from 'lucide-react'
import Modal from '../Modal'
import Pill from '../Pill'
import AssetResultRow from '../AssetResultRow'
import { usePushNotifications } from '../../hooks/usePushNotifications'
import { POPULAR_TICKERS } from '../../utils/tickers'
import { api } from '../../utils/api'
import { parseNum, numACampo } from '../../utils/format'
import { confirmar } from '../../utils/confirmar'
import AvisoNotificaciones from '../AvisoNotificaciones'
import { monedaDe, simbolo, fmtPrecio, fmtPct, confirmacion, canal, monedasPosibles, SENALES_TECNICAS, conSentido, activoTecnico, textoDeLinea, tipoDeLinea, idDeLinea, modoDeCanal, alertaDeLinea, assetDeLinea, simboloDelAviso } from './alertasTexto'
import MiniLinea from './MiniLinea'
import { cargarCedears, dolaresPorSimbolo } from '../../utils/opcionesCedear'
import { setBrokersRegistry } from '../../utils/valuation'

const VACIO = {
  kind: 'price_target',
  scope: 'ticker',
  symbol: '',
  currency: 'USD',
  direction: 'above',
  threshold: '',       // price_target
  up_pct: '',          // pct_move: sube más de
  down_pct: '',        // pct_move: cae más de
  baseline: 'prev_close', // pct_move de un activo: 'prev_close' (en el día) | 'set_price' (desde ahora)
  senal: 'media200',   // tecnica: qué señal (alertasTexto → SENALES_TECNICAS)
  accion_local: false, // tecnica: acción argentina (la regla de la ficha)
  channel: 'both',
  repeat: 'once',      // el de precio; al cambiar de tipo lo decide repeticionPorDefecto
}

// «Cuántas veces» arranca según lo que se vigila: el % de toda la cartera en
// «Todos los días»; el de precio y el de un activo, en «Una vez». Con «Una vez»
// la de toda la cartera se apagaba con el primer activo que pasaba el % —y
// avisaba sólo de ése aunque se movieran tres juntos—: quien pedía «avisame si
// algo de mi cartera se mueve 3 %» recibía un aviso y nunca más (21/10/2026).
//
// La técnica arranca en «Cada vez que pase»: un cruce del promedio de 200 días
// pasa pocas veces por año y quien lo pide quiere enterarse de todos. Salvo
// tocar tu línea: un precio que anda alrededor de la línea la tocaría todos
// los días (y TradingView también arranca en «una vez»).
export function repeticionPorDefecto(kind, scope, senal) {
  if (kind === 'tecnica') return senal === 'linea' ? 'once' : 'always'
  return kind === 'pct_move' && scope === 'holdings' ? 'always' : 'once'
}

// Cambiar qué se vigila (el tipo o «Qué vigilar»). Si la persona ya eligió
// «Cuántas veces» a mano, se respeta; si no, sigue a lo que se vigila.
export function alCambiarVigilancia(f, cambios, repeticionElegida) {
  const n = { ...f, ...cambios }
  return repeticionElegida ? n : { ...n, repeat: repeticionPorDefecto(n.kind, n.scope, n.senal) }
}

// En «Señal técnica», qué vigilar: una señal de la lista o una línea que
// dibujaste. Cambiar suelta la línea elegida.
export function alElegirVigilanciaTecnica(f, que, repeticionElegida) {
  return alCambiarVigilancia(f, que === 'linea'
    ? { senal: 'linea', direction: 'either', dibujo: null, tipoLinea: null, modo: 'toque' }
    : { senal: 'media200', direction: 'either', dibujo: null, tipoLinea: null }, repeticionElegida)
}

// Al pasar a «Se mueve un %» sin activo elegido arranca en «Toda mi cartera»,
// el uso más común; con un activo ya elegido, sigue con ese.
export function alElegirTipo(f, kind, repeticionElegida) {
  return alCambiarVigilancia(f, {
    kind, direction: kind === 'tecnica' ? 'either' : 'above', threshold: '', up_pct: '', down_pct: '',
    scope: kind === 'pct_move' && !(f.symbol || '').trim() ? 'holdings' : 'ticker',
  }, repeticionElegida)
}

// El borrador inicial: una alerta que se edita, un link que trae el ticker
// (?new=GGAL.BA&down=10, desde una posición o desde Mervall-E AI) o vacío.
export function borradorInicial({ alerta, prefill, puedeMovimiento }) {
  if (alerta) {
    return {
      ...VACIO, ...alerta,
      // Tu línea: de qué tipo y, si es un canal, cuándo cuenta (lo dice su referencia).
      ...(alerta.senal === 'linea' ? { tipoLinea: tipoDeLinea(alerta), modo: modoDeCanal(alerta), assetLinea: assetDeLinea(alerta) } : {}),
      symbol: alerta.symbol || '',
      currency: alerta.currency || monedaDe(alerta.symbol),
      threshold: alerta.threshold != null ? numACampo(alerta.threshold) : '',
      up_pct: alerta.up_pct != null ? numACampo(Math.abs(alerta.up_pct)) : '',
      down_pct: alerta.down_pct != null ? numACampo(Math.abs(alerta.down_pct)) : '',
      baseline: alerta.baseline || 'prev_close',
    }
  }
  if (!prefill) return VACIO
  if (prefill.kind === 'tecnica') {
    // Desde la ficha (o la Radiografía): la señal de la tarjeta, ya armada.
    return {
      ...VACIO, kind: 'tecnica', scope: 'ticker', symbol: prefill.symbol || '',
      senal: prefill.senal || 'media200', direction: prefill.direction || 'either',
      currency: prefill.currency === 'ARS' ? 'ARS' : 'USD', accion_local: !!prefill.accionLocal,
      // Tu línea del gráfico: cuál (su id) y de qué tipo, para decirlo.
      ...(prefill.senal === 'linea' ? { dibujo: prefill.dibujo, tipoLinea: prefill.tipoLinea, modo: prefill.modo || 'toque' } : {}),
      repeat: repeticionPorDefecto('tecnica', 'ticker', prefill.senal),
    }
  }
  const base = {
    ...VACIO, symbol: prefill.symbol || '', monedaDelLink: prefill.currency,
    currency: prefill.currency || monedaDe(simboloDelAviso(prefill.symbol, prefill.currency)),
  }
  // "Crear alerta BTC −10%" desde Mervall-E AI → por %, ya cargada. Sin el
  // permiso queda el de precio (el selector de % muestra que es de Plus).
  if ((prefill.downPct || prefill.upPct) && puedeMovimiento) {
    return {
      ...base, kind: 'pct_move',
      down_pct: prefill.downPct ? numACampo(prefill.downPct) : '',
      up_pct: prefill.upPct ? numACampo(prefill.upPct) : '',
    }
  }
  return base
}

// El activo de un aviso técnico: el de la ficha tal cual (`fijo`: ya viene
// pelado y con su marca de acción argentina) o el del buscador, decidido con
// tus lotes como lo decide la ficha (`activoTecnico`).
function activoTecnicoDelBorrador(f, fijo, posiciones) {
  const sym = (f.symbol || '').trim().toUpperCase()
  return fijo ? { symbol: sym, accion_local: !!f.accion_local } : activoTecnico(sym, posiciones)
}

// Lo que se manda al crear un aviso técnico (POST /api/alerts, ver
// main._crear_alerta_tecnica). Exportada para las pruebas.
export function pedidoTecnico(f, fijo, posiciones = []) {
  const { symbol, accion_local } = activoTecnicoDelBorrador(f, fijo, posiciones)
  const canal = f.senal === 'linea' && f.tipoLinea === 'canal'
  return {
    kind: 'tecnica', scope: 'ticker', symbol, senal: f.senal,
    // Un canal también tiene lado: por qué borde (Nico, 29/10).
    direction: conSentido(f.senal) || canal ? f.direction : 'either',
    currency: f.currency === 'ARS' ? 'ARS' : 'USD', accion_local,
    channel: f.channel, repeat: f.repeat,
    // Tu línea: el activo como lo guarda la ficha (desde la ficha, con su «.BA»
    // si lo tiene; desde acá, pelado, como abre la ficha) y cuál de tus
    // dibujos (main._crear_alerta_de_linea).
    ...(f.senal === 'linea' ? { symbol: fijo ? (f.symbol || '').trim().toUpperCase() : (f.assetLinea || symbol), dibujo: f.dibujo } : {}),
    ...(canal ? { modo: f.modo === 'cierre' ? 'cierre' : 'toque' } : {}),
  }
}

// El activo que se vigila de verdad (el que se pide al servidor y del que se
// muestra el precio): una alerta que se edita no cambia de activo; una nueva
// pasa por la regla de acción argentina (alertasTexto.simboloDelAviso).
export function activoDelBorrador(f, editando) {
  const crudo = (f.symbol || '').trim().toUpperCase()
  return editando ? crudo : simboloDelAviso(crudo, f.monedaDelLink)
}

// Elegir o escribir otro activo en el buscador: la moneda del link ya no
// vale (era del activo que traía el link) y la del precio sale del activo.
export function alElegirActivo(f, valor, ccy) {
  return { ...f, symbol: valor, monedaDelLink: undefined, currency: ccy || monedaDe(simboloDelAviso(valor)) }
}

const CAMPO = 'h-12 w-full rounded-lg border border-line bg-bg-2 px-3.5 text-ink-0 outline-none focus-within:border-data-violet'
const ROTULO = 'text-[13px] text-ink-2'
const PRIMARIO = 'inline-flex items-center justify-center h-11 px-5 rounded-lg bg-data-violet text-white text-sm font-semibold hover:bg-rendi-violet-hover disabled:opacity-50 transition-colors'

export default function AlertaForm({ plan, alerta, prefill, onClose, crear, actualizar, borrar, onCreada }) {
  const editando = !!alerta
  const puedeMovimiento = plan?.can ? plan.can('alerts.pct_move') : false
  const [form, setForm] = useState(() => borradorInicial({ alerta, prefill, puedeMovimiento }))
  const [opciones, setOpciones] = useState(false)
  const [repeticionElegida, setRepeticionElegida] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const [err, setErr] = useState(null)
  const [upsell, setUpsell] = useState(false)
  const [precio, setPrecio] = useState(null)
  const push = usePushNotifications()

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const esPrecio = form.kind === 'price_target'
  const esTecnica = form.kind === 'tecnica'
  const fijo = !!prefill?.fijo
  const cartera = !esPrecio && !esTecnica && form.scope === 'holdings'

  // Los CEDEARs que cotizan en dólares (AAPLD): el buscador los ofrece en las
  // dos monedas y de acá sale su precio en dólares — la misma lista que el
  // buscador de "Registrar compra" y que el servidor usa para vigilarlos.
  const [cedears, setCedears] = useState(undefined)
  useEffect(() => {
    let vivo = true
    cargarCedears().then(items => { if (vivo) setCedears(items) })
    return () => { vivo = false }
  }, [])
  const dolares = useMemo(() => (cedears === undefined ? undefined : dolaresPorSimbolo(cedears)), [cedears])

  // Tus tenencias, para decidir como la ficha si un activo del buscador es una
  // acción argentina (`activoTecnico`). Sólo para el aviso técnico armado acá:
  // desde la ficha la marca ya viene, y editando no se cambia.
  const [posiciones, setPosiciones] = useState([])
  const buscaTecnica = form.kind === 'tecnica' && !prefill?.fijo && !alerta
  useEffect(() => {
    if (!buscaTecnica) return
    let vivo = true
    Promise.all([api.get('/positions').catch(() => []), api.get('/brokers').catch(() => [])])
      .then(([pos, bkrs]) => {
        if (!vivo) return
        // `isBymaHolding` mira la moneda del broker en el registro, como la ficha.
        setBrokersRegistry(bkrs || [])
        setPosiciones(pos || [])
      })
    return () => { vivo = false }
  }, [buscaTecnica])

  // El de un aviso de precio o % pasa por la regla de acción argentina
  // (`activoDelBorrador`); el técnico decide su mercado aparte (`tec`, abajo).
  const sym = form.kind === 'tecnica' ? (form.symbol || '').trim().toUpperCase() : activoDelBorrador(form, editando)
  // La moneda del precio es una que el activo TIENE (la regla del servidor,
  // main._moneda_del_aviso): antes el selector $/US$ era libre y «AAPL baja a
  // US$ 15» se comparaba contra los pesos del CEDEAR — no avisaba nunca.
  const monedas = monedasPosibles(sym, dolares)
  const moneda = editando || monedas.includes(form.currency) ? form.currency : monedas[0]
  const enDolaresDeLaBolsa = sym.endsWith('.BA') && moneda === 'USD'

  // El precio de ahora del activo elegido: contexto para la persona y para el
  // «le falta X %» del campo de precio.
  useEffect(() => {
    // La técnica no muestra precio (se mira con el cierre del día).
    if (!sym || cartera || esTecnica) { setPrecio(null); return }
    if (enDolaresDeLaBolsa) { setPrecio(dolares?.get(sym)?.px ?? null); return }
    let cancelado = false
    const t = setTimeout(async () => {
      try {
        const res = await api.get(`/prices?symbols=${encodeURIComponent(sym)}`)
        if (!cancelado) setPrecio(res && res[sym] != null ? res[sym] : null)
      } catch { if (!cancelado) setPrecio(null) }
    }, 400)
    return () => { cancelado = true; clearTimeout(t) }
  }, [sym, cartera, esTecnica, enDolaresDeLaBolsa, dolares])

  function elegirTipo(kind) {
    if (editando) return
    if (kind === 'pct_move' && !puedeMovimiento) { setUpsell('pct'); return }
    setUpsell(false)
    setForm(f => alElegirTipo(f, kind, repeticionElegida))
  }

  // Lo que se manda es lo que se ve: el borrador con los números leídos.
  // La técnica: el activo como lo pide la ficha (pelado + marca de acción
  // argentina). Desde la ficha ya viene así; del buscador se deduce.
  const tec = esTecnica ? activoTecnicoDelBorrador(form, fijo || editando, posiciones) : null
  const borrador = {
    ...form,
    ...(tec || {}),
    symbol: cartera ? null : (tec ? tec.symbol : sym),
    currency: esTecnica ? form.currency : moneda,
    threshold: parseNum(form.threshold),
    up_pct: parseNum(form.up_pct),
    down_pct: parseNum(form.down_pct),
  }
  const texto = confirmacion(borrador)
  const thr = borrador.threshold
  const falta = esPrecio && precio != null && thr > 0 ? (thr / precio - 1) * 100 : null

  async function enviar(e) {
    e.preventDefault()
    setErr(null)
    const up = borrador.up_pct, down = borrador.down_pct
    if (esTecnica) {
      if (!sym) { setErr('Elegí un activo.'); return }
      if (form.senal === 'linea' && !form.dibujo) { setErr('Elegí una de tus líneas.'); return }
    } else if (esPrecio) {
      if (!sym) { setErr('Elegí un activo.'); return }
      if (!(thr > 0)) { setErr('Poné el precio.'); return }
    } else {
      if (!cartera && !sym) { setErr('Elegí un activo o «Toda mi cartera».'); return }
      if (!(up > 0) && !(down > 0)) { setErr('Poné al menos uno de los dos %.'); return }
    }
    // Si eligió celular y este dispositivo no tiene las notificaciones, el
    // permiso se pide YA, en el mismo toque: Safari del iPhone (y Firefox) no
    // muestran el pedido si sale después de esperar al servidor. La respuesta
    // se mira cuando el aviso quedó creado (la página la muestra en «Mis
    // alertas»). Viene del arreglo de AlertsManager en claude/habito-instalar-push.
    const quierePush = !editando && form.channel !== 'email' && push && !push.subscribed && !push.motivo
    const pedidoPush = quierePush ? push.subscribe() : null
    pedidoPush?.catch(() => {})   // se atiende en la página; esto evita el «rechazo sin atender» si falla el alta
    setOcupado(true)
    try {
      if (editando && esTecnica) {
        const canalEditado = form.senal === 'linea' && form.tipoLinea === 'canal'
        await actualizar(alerta.id, {
          ...(conSentido(form.senal) || canalEditado ? { direction: form.direction } : {}),
          ...(canalEditado ? { modo: form.modo === 'cierre' ? 'cierre' : 'toque' } : {}),
          channel: form.channel, repeat: form.repeat,
        })
        onClose()
        return
      }
      if (editando) {
        await actualizar(alerta.id, esPrecio
          ? { threshold: thr, direction: form.direction, channel: form.channel, repeat: form.repeat }
          // 0 = «dejalo vacío»: el servidor lo guarda sin ese lado.
          : { up_pct: up > 0 ? up : 0, down_pct: down > 0 ? down : 0, channel: form.channel, repeat: form.repeat })
        onClose()
        return
      }
      const pedido = esTecnica ? pedidoTecnico(form, fijo, posiciones) : {
        kind: form.kind,
        scope: esPrecio ? 'ticker' : form.scope,
        symbol: cartera ? null : sym,
        channel: form.channel,
        repeat: form.repeat,
        ...(esPrecio
          ? { direction: form.direction, threshold: thr, currency: moneda }
          : { up_pct: up > 0 ? up : undefined, down_pct: down > 0 ? down : undefined,
              baseline: cartera ? 'prev_close' : form.baseline }),
      }
      const res = await crear(pedido)
      onCreada?.(res, pedido, pedidoPush)
      onClose()
    } catch (e2) {
      // El 403 del servidor trae {error, upgrade, quota | feature} en `detail`
      // (api.js deja la respuesta entera en `payload`). Antes se leía
      // `payload.upgrade`, que no existe: el cartel de planes no salía nunca.
      const det = e2?.payload?.detail
      if (e2?.status === 403 && det?.upgrade) {
        setUpsell(det.feature ? 'pct' : 'tope')
        if (!det.feature) return     // el cartel ya lo dice, con el link
      }
      setErr(e2?.message || 'No se pudo guardar.')
    } finally {
      setOcupado(false)
    }
  }

  async function quitar() {
    if (!await confirmar('¿Borrar este aviso?\n\nDeja de vigilar y se borra su historial.', { si: 'Borrar', peligro: true })) return
    setOcupado(true)
    try { await borrar(alerta.id); onClose() }
    catch (e2) { setErr(e2?.payload?.error || 'No se pudo borrar.') }
    finally { setOcupado(false) }
  }

  const veces = form.repeat === 'once' ? 'una vez' : esPrecio ? 'cada vez que cruce' : esTecnica ? 'cada vez que pase' : 'todos los días'

  return (
    <Modal title={editando ? 'Editar aviso' : esTecnica ? 'Nuevo aviso técnico' : 'Nuevo aviso de precio'} onClose={onClose}>
      <form onSubmit={enviar} className="space-y-5">
        {!editando && !fijo && (
          <Segmentos etiqueta="Tipo de aviso" valor={form.kind} onChange={elegirTipo} opciones={[
            { valor: 'price_target', texto: 'Llega a un precio' },
            { valor: 'pct_move', texto: <>Se mueve un %{!puedeMovimiento && <Pill tone="info" className="ml-1.5">Plus</Pill>}</> },
            { valor: 'tecnica', texto: 'Señal técnica' },
          ]} />
        )}

        {upsell === 'pct' && <Upsell texto="Los avisos por % son de Rendi Plus." />}

        {!esPrecio && !esTecnica && (
          <Campo rotulo="Qué vigilar">
            {editando ? (
              <Fijo>{cartera ? 'Toda mi cartera' : simbolo(sym)}</Fijo>
            ) : (
              <Segmentos etiqueta="Qué vigilar" grande valor={form.scope}
                onChange={v => setForm(f => alCambiarVigilancia(f, { scope: v }, repeticionElegida))} opciones={[
                { valor: 'holdings', texto: <><Briefcase size={15} strokeWidth={1.75} /> Toda mi cartera</> },
                { valor: 'ticker', texto: <><Search size={15} strokeWidth={1.75} /> Un activo</> },
              ]} />
            )}
          </Campo>
        )}

        {!cartera && (
          <Campo rotulo="Activo">
            {editando || fijo ? (
              <Fijo>
                <span className="font-semibold">{simbolo(sym)}</span>
                {precio != null && !esTecnica && <span className="ml-auto tabular text-ink-1">{fmtPrecio(precio, moneda)}</span>}
              </Fijo>
            ) : (
              <BuscadorTicker valor={form.symbol} precio={precio} moneda={moneda} dolares={dolares}
                // En la técnica la moneda es «en qué se mira» (Dólares por
                // defecto), no la del precio del activo: el buscador no la toca.
                // Otro activo suelta la línea elegida: era de tus dibujos del anterior.
                onChange={(v, ccy) => setForm(f => (f.kind === 'tecnica'
                  ? { ...f, symbol: v, ...(f.senal === 'linea' && v !== f.symbol ? { dibujo: null, tipoLinea: null, assetLinea: null } : {}) }
                  : alElegirActivo(f, v, ccy)))} />
            )}
          </Campo>
        )}

        {esTecnica ? (
          <CamposTecnica form={form} set={set} setForm={setForm} editando={editando} fijo={fijo}
            repeticionElegida={repeticionElegida} posiciones={posiciones} />
        ) : esPrecio ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <Campo rotulo="Avisame cuando">
              <Segmentos etiqueta="Dirección" grande valor={form.direction} onChange={v => set('direction', v)} opciones={[
                { valor: 'above', texto: <><TrendingUp size={15} /> Sube a</> },
                { valor: 'below', texto: <><TrendingDown size={15} /> Baja a</> },
              ]} />
            </Campo>
            <Campo rotulo="Precio">
              <div className={`${CAMPO} flex items-center gap-2`}>
                {editando || monedas.length < 2 ? (
                  <span className="text-ink-2">{moneda === 'ARS' ? '$' : 'US$'}</span>
                ) : (
                  <select aria-label="Moneda" value={moneda} onChange={e => set('currency', e.target.value)}
                    className="bg-transparent text-ink-2 outline-none -ml-1">
                    <option value="ARS">$</option>
                    <option value="USD">US$</option>
                  </select>
                )}
                <input type="text" inputMode="decimal" value={form.threshold} aria-label="Precio"
                  onChange={e => set('threshold', e.target.value)} placeholder="0"
                  className="flex-1 min-w-0 bg-transparent outline-none text-[17px] font-semibold tabular placeholder:text-ink-3" />
                {falta != null && (
                  <span className="text-[13px] text-ink-2 tabular">{falta < 0 ? '−' : '+'}{fmtPct(falta)} %</span>
                )}
              </div>
            </Campo>
          </div>
        ) : (
          <>
            {!cartera && (
              <Campo rotulo="Medido" ayuda={form.baseline === 'set_price'
                ? 'Desde el precio de ahora. Si la reactivás, vuelve a medir desde ese momento.'
                : 'Contra el cierre de ayer: cada día arranca de cero.'}>
                {editando ? (
                  <Fijo>{form.baseline === 'set_price' ? 'Desde el precio de ahora' : 'En el día'}</Fijo>
                ) : (
                  <Segmentos etiqueta="Medido" grande valor={form.baseline} onChange={v => set('baseline', v)} opciones={[
                    { valor: 'prev_close', texto: 'En el día' },
                    { valor: 'set_price', texto: 'Desde ahora' },
                  ]} />
                )}
              </Campo>
            )}
            <div className="grid grid-cols-2 gap-4">
              <Campo rotulo={<><TrendingUp size={14} className="text-rendi-pos" /> Si sube más de</>}>
                <Porcentaje valor={form.up_pct} onChange={v => set('up_pct', v)} etiqueta="Porcentaje de suba" />
              </Campo>
              <Campo rotulo={<><TrendingDown size={14} className="text-rendi-neg" /> Si cae más de</>}>
                <Porcentaje valor={form.down_pct} onChange={v => set('down_pct', v)} etiqueta="Porcentaje de caída" />
              </Campo>
            </div>
            <p className="text-xs text-ink-2 -mt-2">Podés dejar uno vacío.</p>
          </>
        )}

        {/* Confirmación: lo armado, en palabras */}
        <div className="flex items-start gap-2.5 rounded-lg bg-bg-2 px-4 py-3.5">
          <Bell size={18} strokeWidth={1.75} className="text-ink-1 flex-shrink-0 mt-0.5" aria-hidden="true" />
          <p className={`text-[14.5px] tabular ${texto ? 'text-ink-0' : 'text-ink-2'}`}>
            {texto || 'Completá los datos y acá vas a ver cómo queda.'}
          </p>
        </div>

        {/* Por dónde y cuántas veces, plegado */}
        {opciones ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <Campo rotulo="Avisarme por" ayuda="El mail siempre llega. La notificación te avisa al momento en este dispositivo.">
              <div className="grid grid-cols-2 gap-2">
                <Llave activa={form.channel !== 'push'} icono={Mail} texto="Mail"
                  onClick={() => set('channel', form.channel === 'both' ? 'push' : form.channel === 'push' ? 'both' : 'email')} />
                <Llave activa={form.channel !== 'email'} icono={Smartphone} texto="Celular"
                  onClick={() => set('channel', form.channel === 'both' ? 'email' : form.channel === 'email' ? 'both' : 'push')} />
              </div>
            </Campo>
            <Campo rotulo="Cuántas veces">
              <Segmentos etiqueta="Cuántas veces" grande valor={form.repeat}
                onChange={v => { setRepeticionElegida(true); set('repeat', v) }} opciones={[
                { valor: 'once', texto: 'Una vez' },
                { valor: 'always', texto: esPrecio ? 'Cada vez que cruce' : esTecnica ? 'Cada vez que pase' : 'Todos los días' },
              ]} />
            </Campo>
          </div>
        ) : null}

        {/* Las notificaciones no se pueden activar en este dispositivo (iPhone
            sin Rendi en el inicio, permiso bloqueado…) y el aviso las pide. */}
        {push?.motivo && form.channel !== 'email' && (
          <AvisoNotificaciones motivo={push.motivo} plataforma={push.plataforma} origen="alertas" />
        )}

        {err && <p className="text-sm text-rendi-neg">{err}</p>}
        {/* El tope del plan sale al lado del botón que se acaba de tocar: arriba
            del formulario quedaba fuera de la vista. */}
        {upsell === 'tope' && <Upsell texto="Llegaste al máximo de alertas de tu plan." />}

        {!opciones && editando && <Resumen canal={form.channel} veces={veces} onCambiar={() => setOpciones(true)} />}

        <div className="flex flex-wrap items-center justify-end gap-3 pt-4 border-t border-line">
          {editando ? (
            <button type="button" onClick={quitar} disabled={ocupado} className="text-sm text-rendi-neg hover:underline mr-auto">
              Borrar aviso
            </button>
          ) : !opciones && (
            <div className="mr-auto"><Resumen canal={form.channel} veces={veces} onCambiar={() => setOpciones(true)} /></div>
          )}
          <button type="submit" disabled={ocupado} className={PRIMARIO}>
            {ocupado ? 'Guardando…' : editando ? 'Guardar cambios' : 'Crear aviso'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

// Lo que se elige en un aviso técnico: qué señal, para qué lado (sólo los
// cruces de un promedio) y en qué moneda se mira. Editando, la señal y la
// moneda quedan fijas (para otra, se arma otra alerta); el lado se cambia.
//
// O una línea que dibujaste (Nico, 29/10): desde la ficha ya viene elegida;
// acá se elige de tus dibujos del activo (GET /api/tecnico/…/lineas), cada uno
// con su gráfico chiquito. Un canal pregunta además por qué borde y cuándo
// cuenta salir.
function CamposTecnica({ form, set, setForm, editando, fijo, repeticionElegida, posiciones }) {
  const actual = SENALES_TECNICAS.find(s => s.id === form.senal)
  const linea = form.senal === 'linea'
  const canal = linea && form.tipoLinea === 'canal'
  // La línea ya decidida (desde la ficha, o editando): no se elige otra.
  const lineaFija = linea && (fijo || editando)
  return (
    <>
      {!editando && !fijo && (
        <Campo rotulo="Qué vigilar">
          <Segmentos etiqueta="Qué vigilar" grande valor={linea ? 'linea' : 'senal'}
            onChange={v => setForm(f => alElegirVigilanciaTecnica(f, v, repeticionElegida))} opciones={[
              { valor: 'senal', texto: 'Una señal' },
              { valor: 'linea', texto: 'Una línea que dibujaste' },
            ]} />
        </Campo>
      )}
      {linea ? (
        <TusLineas form={form} setForm={setForm} fija={lineaFija} posiciones={posiciones} />
      ) : (
        <Campo rotulo="Avisame cuando">
          {editando ? (
            <Fijo>{actual?.texto}</Fijo>
          ) : (
            <div role="radiogroup" aria-label="Avisame cuando" className="grid gap-1.5 sm:grid-cols-2">
              {SENALES_TECNICAS.map(o => {
                const activo = o.id === form.senal
                return (
                  <button key={o.id} type="button" role="radio" aria-checked={activo}
                    onClick={() => set('senal', o.id)}
                    className={`min-h-11 px-3.5 py-2 rounded-lg border text-left text-sm transition-colors ${activo ? 'border-data-violet bg-data-violet/10 text-ink-0' : 'border-line text-ink-1 hover:text-ink-0'}`}>
                    {o.texto}
                  </button>
                )
              })}
            </div>
          )}
        </Campo>
      )}
      {conSentido(form.senal) && (
        <Campo rotulo="Para qué lado">
          <Segmentos etiqueta="Para qué lado" grande valor={form.direction} onChange={v => set('direction', v)} opciones={[
            { valor: 'above', texto: <><TrendingUp size={15} /> Para arriba</> },
            { valor: 'below', texto: <><TrendingDown size={15} /> Para abajo</> },
            { valor: 'either', texto: 'Los dos' },
          ]} />
        </Campo>
      )}
      {canal && (
        <>
          <Campo rotulo="Por qué borde">
            <Segmentos etiqueta="Por qué borde" grande valor={form.direction} onChange={v => set('direction', v)} opciones={[
              { valor: 'above', texto: <><TrendingUp size={15} /> Por arriba</> },
              { valor: 'below', texto: <><TrendingDown size={15} /> Por abajo</> },
              { valor: 'either', texto: 'Por cualquiera' },
            ]} />
          </Campo>
          <Campo rotulo="Cuándo cuenta" ayuda={form.modo === 'cierre'
            ? 'Sólo si cierra afuera: menos avisos, pero llega más tarde.'
            : 'Si lo toca o lo pasa en el día: avisa antes, aunque a veces vuelve adentro.'}>
            <Segmentos etiqueta="Cuándo cuenta" grande valor={form.modo === 'cierre' ? 'cierre' : 'toque'} onChange={v => set('modo', v)} opciones={[
              { valor: 'toque', texto: 'Si lo toca en el día' },
              { valor: 'cierre', texto: 'Si cierra afuera' },
            ]} />
          </Campo>
        </>
      )}
      {/* Siempre a la vista, también en cripto (la ficha también la muestra en
          pesos): escondido, se mandaba igual lo último que se había elegido. */}
      <Campo rotulo="Medido en" ayuda={form.currency === 'ARS'
        ? 'En pesos, el precio también sube cuando sube el dólar, aunque a la empresa no le cambie nada.'
        : 'Igual que en la ficha: en dólares se ve la tendencia del activo sin el efecto de la suba del dólar.'}>
        {editando || lineaFija ? (
          <Fijo>{form.currency === 'ARS' ? 'Pesos' : 'Dólares'}</Fijo>
        ) : (
          <Segmentos etiqueta="Medido en" grande valor={form.currency === 'ARS' ? 'ARS' : 'USD'}
            // Tus dibujos en pesos y en dólares son otros: cambiar suelta la línea elegida.
            onChange={v => setForm(f => ({ ...f, currency: v, ...(linea ? { dibujo: null, tipoLinea: null } : {}) }))} opciones={[
              { valor: 'USD', texto: 'Dólares' },
              { valor: 'ARS', texto: 'Pesos' },
            ]} />
        )}
      </Campo>
    </>
  )
}

const NOMBRE_DIBUJO = { horizontal: 'Línea horizontal', tendencia: 'Línea de tendencia', canal: 'Canal' }

/** Dónde está hoy una línea tuya, para la lista: «US$ 196,00», «Hoy pasa por…», «Hoy va de … a …». */
export function dondeEstaHoy(r, ccy) {
  const hoy = r?.hoy
  if (!Array.isArray(hoy) || hoy.some(x => x == null)) return ''
  if (r.tipo === 'canal') return `Hoy va de ${fmtPrecio(hoy[0], ccy)} a ${fmtPrecio(hoy[1], ccy)}`
  if (r.tipo === 'tendencia') return `Hoy pasa por ${fmtPrecio(hoy[0], ccy)}`
  return fmtPrecio(hoy[0], ccy)
}

// Tus líneas del activo, para elegir una (o, ya elegida, para reconocerla).
function TusLineas({ form, setForm, fija, posiciones }) {
  // Ya elegida: el activo como lo guarda la ficha (editando, el de la referencia al dibujo).
  const { symbol, accion_local } = fija ? { symbol: (form.assetLinea || form.symbol || '').trim().toUpperCase(), accion_local: !!form.accion_local }
    : activoTecnico(form.symbol, posiciones)
  const moneda = form.currency === 'ARS' ? 'ars' : 'usd'
  const ccy = moneda === 'ars' ? 'ARS' : 'USD'
  const [lineas, setLineas] = useState(undefined)
  const [avisos, setAvisos] = useState([])
  useEffect(() => {
    if (!symbol) { setLineas(undefined); return }
    let vivo = true
    setLineas(undefined)
    const t = setTimeout(() => {
      api.get(`/tecnico/${encodeURIComponent(symbol)}/lineas?moneda=${moneda}&accion_local=${accion_local ? 'true' : 'false'}`)
        .then(r => { if (vivo) setLineas(r?.lineas || []) })
        .catch(() => { if (vivo) setLineas([]) })
    }, fija ? 0 : 400)
    return () => { vivo = false; clearTimeout(t) }
  }, [symbol, moneda, accion_local, fija])
  useEffect(() => {
    if (fija) return
    api.get('/alerts').then(r => setAvisos(r?.items || [])).catch(() => setAvisos([]))
  }, [fija])
  const elegida = idDeLinea(form)

  if (fija) {
    const r = (lineas || []).find(x => x.id === elegida)
    return (
      <Campo rotulo="Avisame cuando" ayuda={form.tipoLinea === 'canal'
        ? 'Si movés o ensanchás el canal, el aviso lo sigue; si lo borrás, se apaga.'
        : 'Lo miramos con el precio más alto y el más bajo de cada día: si la tocó, te llega a la mañana siguiente. Si movés la línea, el aviso la sigue; si la borrás, se apaga.'}>
        <div className="flex items-center gap-3.5 rounded-lg bg-bg-2 px-3.5 py-2.5">
          {r && <MiniLinea resumen={r} etiqueta={`${NOMBRE_DIBUJO[r.tipo]} de ${simbolo(symbol)}`} />}
          <span className="min-w-0">
            <span className="block text-[15px] font-semibold text-ink-0">{simbolo(symbol)} {textoDeLinea(form).replace(/^./, c => c.toLowerCase())}</span>
            {r && <span className="block text-[13px] text-ink-2 tabular">{dondeEstaHoy(r, ccy)}</span>}
          </span>
        </div>
      </Campo>
    )
  }

  if (!symbol) return <p className="text-sm text-ink-2">Elegí el activo y te mostramos las líneas que dibujaste en su gráfico.</p>
  return (
    <Campo rotulo={`Tus dibujos en ${simbolo(symbol)} (en ${moneda === 'ars' ? 'pesos' : 'dólares'})`}>
      {lineas === undefined ? (
        <p className="text-sm text-ink-2 py-2">Buscando tus líneas…</p>
      ) : lineas.length === 0 ? (
        <p className="text-sm text-ink-1 rounded-lg bg-bg-2 px-3.5 py-3">
          Todavía no dibujaste líneas en {simbolo(symbol)} {moneda === 'ars' ? 'en pesos' : 'en dólares'}.{' '}
          <Link to={`/activo/${encodeURIComponent(symbol)}`} className="text-data-violet font-medium hover:underline">Dibujá una en su gráfico</Link>
        </p>
      ) : (
        <div className="space-y-1.5">
          <div role="radiogroup" aria-label="Elegí tu línea" className="space-y-1.5">
            {lineas.map(r => {
              const ya = alertaDeLinea(avisos, { asset: r.asset || symbol, moneda, dibujo: r.id })
              const activa = r.id === elegida && (!form.assetLinea || form.assetLinea === (r.asset || symbol))
              return (
                <button key={`${r.asset || ''}:${r.id}`} type="button" role="radio" aria-checked={activa} disabled={!!ya}
                  // `assetLinea`: bajo qué activo la guardó la ficha («GGAL» o «GGAL.BA»).
                  onClick={() => setForm(f => ({ ...f, dibujo: r.id, tipoLinea: r.tipo, assetLinea: r.asset || symbol, direction: 'either', modo: 'toque' }))}
                  className={`w-full flex items-center gap-3.5 rounded-lg border px-3 py-2 text-left transition-colors disabled:opacity-60 ${activa ? 'border-data-violet bg-data-violet/10' : 'border-line hover:border-line-2'}`}>
                  <MiniLinea resumen={r} />
                  <span className="flex-1 min-w-0">
                    <span className="block text-[15px] font-medium text-ink-0">{NOMBRE_DIBUJO[r.tipo]}</span>
                    <span className={`block text-[13px] tabular ${ya ? 'text-rendi-pos' : 'text-ink-2'}`}>{ya ? 'Ya te avisamos' : dondeEstaHoy(r, ccy)}</span>
                  </span>
                </button>
              )
            })}
          </div>
          <p className="text-[13px] text-ink-2">
            ¿No está la que querés? <Link to={`/activo/${encodeURIComponent(symbol)}`} className="text-data-violet hover:underline">Dibujala en el gráfico de {simbolo(symbol)}</Link>. Fibonacci, Elliott y los trazos a mano no tienen aviso.
          </p>
        </div>
      )}
    </Campo>
  )
}

function Upsell({ texto }) {
  return (
    <p className="text-sm text-ink-1 rounded-lg bg-bg-2 px-3.5 py-3">
      {texto}{' '}
      <Link to="/config?tab=planes" className="text-data-violet font-medium hover:underline">Ver planes</Link>
    </p>
  )
}

function Resumen({ canal: ch, veces, onCambiar }) {
  return (
    <p className="text-[13.5px] text-ink-2">
      {canal(ch)} · {veces} ·{' '}
      <button type="button" onClick={onCambiar} className="text-data-violet hover:underline">cambiar</button>
    </p>
  )
}

function Campo({ rotulo, ayuda, children }) {
  return (
    <div className="space-y-1.5">
      <div className={`${ROTULO} inline-flex items-center gap-1.5`}>{rotulo}</div>
      {children}
      {ayuda && <p className="text-xs text-ink-2">{ayuda}</p>}
    </div>
  )
}

function Fijo({ children }) {
  return <div className={`${CAMPO} flex items-center gap-2 text-ink-1`}>{children}</div>
}

function Segmentos({ etiqueta, valor, onChange, opciones, grande = false }) {
  return (
    <div role="radiogroup" aria-label={etiqueta}
      className={`grid gap-0.5 p-[3px] rounded-lg bg-bg-2 ${grande ? 'h-12 border border-line' : 'h-11'}`}
      style={{ gridTemplateColumns: `repeat(${opciones.length}, minmax(0, 1fr))` }}>
      {opciones.map(o => {
        const activo = o.valor === valor
        return (
          <button key={o.valor} type="button" role="radio" aria-checked={activo} onClick={() => onChange(o.valor)}
            className={`inline-flex items-center justify-center gap-1.5 rounded text-sm transition-colors ${activo ? 'bg-bg-3 text-ink-0 font-medium' : 'text-ink-2 hover:text-ink-1'}`}>
            {o.texto}
          </button>
        )
      })}
    </div>
  )
}

function Porcentaje({ valor, onChange, etiqueta }) {
  return (
    <div className={`${CAMPO} flex items-center gap-2`}>
      <input type="text" inputMode="decimal" value={valor} aria-label={etiqueta} placeholder="—"
        onChange={e => onChange(e.target.value)}
        className="flex-1 min-w-0 bg-transparent outline-none text-[17px] font-semibold tabular placeholder:text-ink-3" />
      <span className="text-ink-2">%</span>
    </div>
  )
}

function Llave({ activa, icono: Icono, texto, onClick }) {
  return (
    <button type="button" aria-pressed={activa} onClick={onClick}
      className={`h-12 inline-flex items-center justify-center gap-2 rounded-lg border text-sm transition-colors ${activa ? 'border-data-violet bg-data-violet/10 text-ink-0' : 'border-line text-ink-2 hover:text-ink-1'}`}>
      <Icono size={16} strokeWidth={1.75} /> {texto}
    </button>
  )
}

// Buscador de ticker con las mismas filas (logo + ticker + nombre + tipo) que el
// resto de la app. Acepta un ticker que no esté en la lista: las alertas
// aceptan cualquier símbolo.
//
// Un CEDEAR que cotiza en dólares aparece dos veces, como en "Registrar
// compra": «CEDEAR en pesos» y «CEDEAR en dólares · AAPLD». Elegir una fila
// elige el activo Y la moneda (`onChange(símbolo, moneda)`); también se lo
// encuentra escribiendo el código en dólares (AAPLD).
export function filasDelBuscador(valor, dolares) {
  const q = (valor || '').trim().toUpperCase()
  const filas = []
  for (const t of POPULAR_TICKERS) {
    const s = t.symbol.toUpperCase()
    const d = s.endsWith('.BA') ? dolares?.get(s) : null
    const base = { symbol: t.symbol, name: t.name, type: t.type }
    if (d) {
      filas.push({ ...base, ccy: 'ARS', sub: 'CEDEAR en pesos', codigos: [s] })
      filas.push({ ...base, ccy: 'USD', sub: `CEDEAR en dólares · ${d.codigo}`, codigos: [s, d.codigo] })
    } else {
      filas.push({ ...base, ccy: null, sub: undefined, codigos: [s] })
    }
  }
  if (!q) return filas.filter(f => f.ccy !== 'USD').slice(0, 8)
  const empieza = [], contiene = []
  for (const f of filas) {
    if (f.codigos.some(c => c.startsWith(q))) empieza.push(f)
    else if (f.codigos.some(c => c.includes(q)) || (f.name || '').toUpperCase().includes(q)) contiene.push(f)
  }
  // Quien escribió el código en dólares (AAPLD) busca esa fila: va primero.
  const exacta = empieza.filter(f => f.ccy === 'USD' && f.codigos[1] === q)
  return [...exacta, ...empieza.filter(f => !exacta.includes(f)), ...contiene].slice(0, 8)
}

function BuscadorTicker({ valor, onChange, precio, moneda, dolares }) {
  const [abierto, setAbierto] = useState(false)
  const caja = useRef(null)

  const resultados = useMemo(() => filasDelBuscador(valor, dolares), [valor, dolares])

  useEffect(() => {
    function afuera(e) { if (caja.current && !caja.current.contains(e.target)) setAbierto(false) }
    document.addEventListener('mousedown', afuera)
    return () => document.removeEventListener('mousedown', afuera)
  }, [])

  const sym = (valor || '').trim().toUpperCase()
  return (
    <div ref={caja} className="relative">
      <div className={`${CAMPO} flex items-center gap-2.5`}>
        <Search size={16} strokeWidth={1.75} className="text-ink-2 flex-shrink-0" aria-hidden="true" />
        <input value={valor} placeholder="Buscá un ticker: GGAL, AAPL, AL30…" aria-label="Activo"
          autoComplete="off" spellCheck="false"
          onChange={e => { onChange(e.target.value.toUpperCase()); setAbierto(true) }}
          onFocus={() => setAbierto(true)}
          className="flex-1 min-w-0 bg-transparent outline-none text-[15px] font-semibold placeholder:font-normal placeholder:text-ink-3" />
        {precio != null && sym && (
          <span className="text-sm text-ink-1 tabular flex-shrink-0">{fmtPrecio(precio, moneda)}</span>
        )}
      </div>
      {abierto && resultados.length > 0 && (
        <div className="absolute z-30 left-0 right-0 mt-1 bg-bg-raised border border-line rounded-lg shadow-2xl overflow-hidden max-h-72 overflow-y-auto">
          {resultados.map(t => (
            <AssetResultRow key={`${t.symbol}:${t.ccy || ''}`} symbol={t.symbol} name={t.name} type={t.type} sub={t.sub}
              onClick={() => { onChange(t.symbol, t.ccy); setAbierto(false) }} />
          ))}
        </div>
      )}
    </div>
  )
}
