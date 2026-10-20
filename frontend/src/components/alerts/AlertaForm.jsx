// AlertaForm — el formulario del aviso de precio, para crearlo y para editarlo.
// ═══════════════════════════════════════════════════════════════════════════
// Dos tipos, elegidos arriba con un selector:
//   • Llega a un precio  (price_target): "avisame cuando GGAL suba a $ 8.000".
//     Todos los planes.
//   • Se mueve un %      (pct_move): "avisame si algo de mi cartera cae 5 %".
//     Plus o más; el backend lo gatea igual (403 con {upgrade}).
//
// Es un formulario de CAMPOS con su nombre, uno debajo del otro y todos del
// mismo alto. La versión anterior armaba una frase con casilleros adentro y se
// cortaba en cualquier renglón según el ancho. La frase no se perdió: abajo de
// todo, `confirmacion()` cuenta en palabras lo que armaste — no se escribe ahí,
// se lee.
//
// Por dónde avisa y cuántas veces quedan plegados en una línea («Por mail y
// celular · una vez · cambiar»): casi nadie los cambia y antes eran la mitad
// de los botones del formulario.
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
import { monedaDe, simbolo, fmtPrecio, fmtPct, confirmacion, canal, monedasPosibles } from './alertasTexto'
import { cargarCedears, dolaresPorSimbolo } from '../../utils/opcionesCedear'

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
  channel: 'both',
  repeat: 'once',
}

// El borrador inicial: una alerta que se edita, un link que trae el ticker
// (?new=GGAL.BA&down=10, desde una posición o desde Mervall-E AI) o vacío.
export function borradorInicial({ alerta, prefill, puedeMovimiento }) {
  if (alerta) {
    return {
      ...VACIO, ...alerta,
      symbol: alerta.symbol || '',
      currency: alerta.currency || monedaDe(alerta.symbol),
      threshold: alerta.threshold != null ? numACampo(alerta.threshold) : '',
      up_pct: alerta.up_pct != null ? numACampo(Math.abs(alerta.up_pct)) : '',
      down_pct: alerta.down_pct != null ? numACampo(Math.abs(alerta.down_pct)) : '',
      baseline: alerta.baseline || 'prev_close',
    }
  }
  if (!prefill) return VACIO
  const base = { ...VACIO, symbol: prefill.symbol || '', currency: prefill.currency || monedaDe(prefill.symbol) }
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

const CAMPO = 'h-12 w-full rounded-lg border border-line bg-bg-2 px-3.5 text-ink-0 outline-none focus-within:border-data-violet'
const ROTULO = 'text-[13px] text-ink-2'
const PRIMARIO = 'inline-flex items-center justify-center h-11 px-5 rounded-lg bg-data-violet text-white text-sm font-semibold hover:bg-rendi-violet-hover disabled:opacity-50 transition-colors'

export default function AlertaForm({ plan, alerta, prefill, onClose, crear, actualizar, borrar, onCreada }) {
  const editando = !!alerta
  const puedeMovimiento = plan?.can ? plan.can('alerts.pct_move') : false
  const [form, setForm] = useState(() => borradorInicial({ alerta, prefill, puedeMovimiento }))
  const [opciones, setOpciones] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const [err, setErr] = useState(null)
  const [upsell, setUpsell] = useState(false)
  const [precio, setPrecio] = useState(null)
  const push = usePushNotifications()

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const esPrecio = form.kind === 'price_target'
  const cartera = !esPrecio && form.scope === 'holdings'

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

  const sym = (form.symbol || '').trim().toUpperCase()
  // La moneda del precio es una que el activo TIENE (la regla del servidor,
  // main._moneda_del_aviso): antes el selector $/US$ era libre y «AAPL baja a
  // US$ 15» se comparaba contra los pesos del CEDEAR — no avisaba nunca.
  const monedas = monedasPosibles(sym, dolares)
  const moneda = editando || monedas.includes(form.currency) ? form.currency : monedas[0]
  const enDolaresDeLaBolsa = sym.endsWith('.BA') && moneda === 'USD'

  // El precio de ahora del activo elegido: contexto para la persona y para el
  // «le falta X %» del campo de precio.
  useEffect(() => {
    if (!sym || cartera) { setPrecio(null); return }
    if (enDolaresDeLaBolsa) { setPrecio(dolares?.get(sym)?.px ?? null); return }
    let cancelado = false
    const t = setTimeout(async () => {
      try {
        const res = await api.get(`/prices?symbols=${encodeURIComponent(sym)}`)
        if (!cancelado) setPrecio(res && res[sym] != null ? res[sym] : null)
      } catch { if (!cancelado) setPrecio(null) }
    }, 400)
    return () => { cancelado = true; clearTimeout(t) }
  }, [sym, cartera, enDolaresDeLaBolsa, dolares])

  function elegirTipo(kind) {
    if (editando) return
    if (kind === 'pct_move' && !puedeMovimiento) { setUpsell(true); return }
    setUpsell(false)
    // Al pasar a «Se mueve un %» sin activo elegido arranca en «Toda mi
    // cartera», el uso más común; con un activo ya elegido, sigue con ese.
    setForm(f => ({ ...f, kind, direction: 'above', threshold: '', up_pct: '', down_pct: '',
      scope: kind === 'pct_move' && !(f.symbol || '').trim() ? 'holdings' : 'ticker' }))
  }

  // Lo que se manda es lo que se ve: el borrador con los números leídos.
  const borrador = {
    ...form,
    symbol: cartera ? null : sym,
    currency: moneda,
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
    if (esPrecio) {
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
      if (editando) {
        await actualizar(alerta.id, esPrecio
          ? { threshold: thr, direction: form.direction, channel: form.channel, repeat: form.repeat }
          // 0 = «dejalo vacío»: el servidor lo guarda sin ese lado.
          : { up_pct: up > 0 ? up : 0, down_pct: down > 0 ? down : 0, channel: form.channel, repeat: form.repeat })
        onClose()
        return
      }
      const pedido = {
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
      if (e2?.status === 403 && e2?.payload?.upgrade) setUpsell(true)
      setErr(e2?.payload?.error || e2?.message || 'No se pudo guardar.')
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

  const veces = form.repeat === 'once' ? 'una vez' : esPrecio ? 'cada vez que cruce' : 'todos los días'

  return (
    <Modal title={editando ? 'Editar aviso' : 'Nuevo aviso de precio'} onClose={onClose}>
      <form onSubmit={enviar} className="space-y-5">
        {!editando && (
          <Segmentos etiqueta="Tipo de aviso" valor={form.kind} onChange={elegirTipo} opciones={[
            { valor: 'price_target', texto: 'Llega a un precio' },
            { valor: 'pct_move', texto: <>Se mueve un %{!puedeMovimiento && <Pill tone="info" className="ml-1.5">Plus</Pill>}</> },
          ]} />
        )}

        {upsell && (
          <p className="text-sm text-ink-1 rounded-lg bg-bg-2 px-3.5 py-3">
            Los avisos por % son de Rendi Plus.{' '}
            <Link to="/config?tab=planes" className="text-data-violet font-medium hover:underline">Ver planes</Link>
          </p>
        )}

        {!esPrecio && (
          <Campo rotulo="Qué vigilar">
            {editando ? (
              <Fijo>{cartera ? 'Toda mi cartera' : simbolo(sym)}</Fijo>
            ) : (
              <Segmentos etiqueta="Qué vigilar" grande valor={form.scope} onChange={v => set('scope', v)} opciones={[
                { valor: 'holdings', texto: <><Briefcase size={15} strokeWidth={1.75} /> Toda mi cartera</> },
                { valor: 'ticker', texto: <><Search size={15} strokeWidth={1.75} /> Un activo</> },
              ]} />
            )}
          </Campo>
        )}

        {!cartera && (
          <Campo rotulo="Activo">
            {editando ? (
              <Fijo>
                <span className="font-semibold">{simbolo(sym)}</span>
                {precio != null && <span className="ml-auto tabular text-ink-1">{fmtPrecio(precio, moneda)}</span>}
              </Fijo>
            ) : (
              <BuscadorTicker valor={form.symbol} precio={precio} moneda={moneda} dolares={dolares}
                onChange={(v, ccy) => setForm(f => ({ ...f, symbol: v, currency: ccy || monedaDe(v) }))} />
            )}
          </Campo>
        )}

        {esPrecio ? (
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
              <Segmentos etiqueta="Cuántas veces" grande valor={form.repeat} onChange={v => set('repeat', v)} opciones={[
                { valor: 'once', texto: 'Una vez' },
                { valor: 'always', texto: esPrecio ? 'Cada vez que cruce' : 'Todos los días' },
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
