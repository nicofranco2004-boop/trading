// Alertas — lo que Rendi te avisa, en dos pestañas.
// ═══════════════════════════════════════════════════════════════════════════
//   • Crear alerta (CrearAlerta): las dos cosas que se pueden pedir, para
//     elegir — el resumen diario del mercado y el aviso de precio.
//   • Mis alertas (MisAlertas): lo que ya armaste, con su estado y su
//     interruptor. Tocar una abre el formulario (AlertaForm) para cambiarla.
//
// La pestaña viaja en la dirección (?tab=crear | ?tab=mis): el tutorial de
// novedades abre «crear» para resaltar las dos tarjetas, y recargar no te
// cambia de pestaña. Sin ?tab, entra en «Mis alertas» si ya creaste algún
// aviso y en «Crear» si no (pestanaInicial, abajo).
//
// Prefill: /alertas?new=MSFT.BA&ccy=ARS (desde el menú de una posición) y
// /alertas?new=BTC&down=10 (desde un botón de Mervall-E AI) abren el formulario
// ya cargado.
//
// Un solo dueño de datos: esta página trae las alertas, los precios y el
// interruptor del resumen, y los baja a las dos pestañas.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import CrearAlerta from '../components/alerts/CrearAlerta'
import MisAlertas from '../components/alerts/MisAlertas'
import AlertaForm from '../components/alerts/AlertaForm'
import AdvisorAlerts from '../components/advisor/AdvisorAlerts'
import { usePlanFeatures } from '../hooks/usePlanFeatures'
import { useAlerts } from '../hooks/useAlerts'
import { useResumenMercado } from '../hooks/useResumenMercado'
import { useAlertsContext } from '../contexts/AlertsContext'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import { useToast } from '../components/Toast'
import AvisoNotificaciones from '../components/AvisoNotificaciones'
import { usePushNotifications } from '../hooks/usePushNotifications'
import { api } from '../utils/api'
import { simbolo, diaArgentina } from '../components/alerts/alertasTexto'

// La pestaña con la que se abre la página. La de la dirección manda (el
// tutorial pide «crear»; los mails y las notificaciones de un aviso que saltó,
// «mis»). Sin dirección decide si creaste algún aviso: el resumen diario del
// mercado NO cuenta. Antes contaba, y quien sólo tenía el resumen prendido
// caía en «Mis alertas» sin ninguna alerta creada (pedido de Nico,
// 2026-10-19: sin alertas, se abre en Crear). null = todavía cargando.
// Exportada para las pruebas.
export function pestanaInicial({ tabUrl, cargando, cantidadAvisos }) {
  if (tabUrl === 'crear' || tabUrl === 'mis') return tabUrl
  if (cargando) return null
  return cantidadAvisos > 0 ? 'mis' : 'crear'
}

export default function Alertas() {
  const plan = usePlanFeatures()
  const { clientCtx } = useAdvisorContext()
  const { markSeen } = useAlertsContext()
  // A su propio nivel el asesor no tiene cartera: sus alertas son del LIBRO.
  const atOwnLevel = plan.isAdvisor && !clientCtx

  // Al entrar, los avisos quedan vistos → se apaga el puntito del menú.
  useEffect(() => { markSeen() }, [markSeen])

  return (
    <div className="page-shell-wide">
      <div className="max-w-3xl">
        <PageHeader
          title="Alertas"
          subtitle={atOwnLevel
            ? 'Lo que te avisamos de tu libro: el brief diario y los movimientos de tus clientes.'
            : 'Te avisamos por mail y al celular cuando pasa algo con tus inversiones.'}
        />
        {clientCtx && (
          <div className="mb-4 text-[12.5px] text-ink-1 bg-data-violet/[0.08] border border-data-violet/30 rounded-lg px-3 py-2">
            Las alertas que crees en esta cuenta te llegan <span className="font-semibold">a vos</span> (tu
            email y tus notificaciones), con el nombre de <span className="font-semibold">{clientCtx.label}</span> adelante.
          </div>
        )}
        {atOwnLevel ? <AdvisorAlerts /> : <AlertasPropias plan={plan} />}
      </div>
    </div>
  )
}

function AlertasPropias({ plan }) {
  const toast = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const { items, events, loading, create, update, remove } = useAlerts()
  const resumen = useResumenMercado()
  const push = usePushNotifications()
  // El aviso quedó creado pero las notificaciones no se activaron.
  const [notaPush, setNotaPush] = useState(null)
  const hoy = diaArgentina(new Date().toISOString())

  // El link que trae un ticker (?new=) abre el formulario ya cargado.
  const newSym = searchParams.get('new')
  const prefill = useMemo(() => {
    if (!newSym) return null
    const pct = (k) => {
      const n = Number(searchParams.get(k))
      return Number.isFinite(n) && n > 0 && n <= 90 ? n : undefined
    }
    return { symbol: newSym, currency: searchParams.get('ccy') || undefined, downPct: pct('down'), upPct: pct('up') }
  }, [newSym, searchParams])

  const [formulario, setFormulario] = useState(() => (prefill ? { prefill } : null))

  const alertsMax = plan?.limit ? plan.limit('alerts_max') : null
  const alTope = alertsMax != null && items.length >= alertsMax
  const puedeMovimiento = plan?.can ? plan.can('alerts.pct_move') : false

  // La pestaña: la de la dirección, o la que corresponde a lo que tenés.
  const tab = pestanaInicial({ tabUrl: searchParams.get('tab'), cargando: loading, cantidadAvisos: items.length })
  const irA = useCallback((t) => {
    setSearchParams(p => { const n = new URLSearchParams(p); n.set('tab', t); n.delete('new'); n.delete('ccy'); n.delete('down'); n.delete('up'); return n }, { replace: true })
  }, [setSearchParams])

  // Los precios de ahora de los activos con aviso, en un solo pedido.
  const simbolos = useMemo(
    () => [...new Set(items.filter(a => a.symbol).map(a => a.symbol.toUpperCase()))].sort().join(','),
    [items])
  const [precios, setPrecios] = useState({})
  useEffect(() => {
    if (!simbolos) { setPrecios({}); return }
    let cancelado = false
    api.get(`/prices?symbols=${encodeURIComponent(simbolos)}`)
      .then(res => { if (!cancelado) setPrecios(res || {}) })
      .catch(() => { if (!cancelado) setPrecios({}) })
    return () => { cancelado = true }
  }, [simbolos])

  const cuantas = items.length + (resumen.prendido ? 1 : 0)

  async function pausar(a) {
    try { await update(a.id, { active: !a.active }) }
    catch { toast.push('No se pudo guardar', { type: 'error' }) }
  }

  function creada(res, payload, pedidoPush) {
    toast.push('Aviso creado')
    if (pedidoPush) {
      setNotaPush(null)
      pedidoPush.catch((ex) => {
        // 'bloqueadas' ya lo explica el cartel de AvisoNotificaciones de abajo.
        if (ex?.motivo === 'bloqueadas') return
        setNotaPush(payload.channel === 'both'
          ? 'El aviso quedó creado, pero las notificaciones no se activaron: por ahora te llega por mail. Las podés activar cuando quieras desde Más → Notificaciones.'
          : 'El aviso quedó creado, pero las notificaciones no se activaron, así que todavía no te va a llegar. Activalas desde Más → Notificaciones, o cambialo para que también te llegue por mail.')
      })
    }
    // Un ticker que no resolvió precio (typo o símbolo que no existe): se avisa.
    if (res && res.resolved === false && payload.symbol) {
      toast.push(`No encontramos el precio de ${simbolo(payload.symbol)} ahora. Si el ticker está bien va a funcionar igual; si no, borralo y armalo de nuevo.`, { type: 'error' })
    }
    irA('mis')
  }

  return (
    <div className="space-y-6">
      <div role="tablist" aria-label="Secciones de Alertas" className="flex gap-7 border-b border-line">
        <Pestana activa={tab === 'crear'} onClick={() => irA('crear')}>Crear alerta</Pestana>
        <Pestana activa={tab === 'mis'} onClick={() => irA('mis')}>
          Mis alertas
          {cuantas > 0 && (
            <span className="ml-2 inline-flex items-center justify-center min-w-[22px] h-[22px] px-1.5 rounded-full bg-bg-3 text-xs text-ink-1 tabular">{cuantas}</span>
          )}
        </Pestana>
      </div>

      {tab === 'crear' && (
        <CrearAlerta resumen={resumen} alTope={alTope} alertsMax={alertsMax} puedeMovimiento={puedeMovimiento}
          onCrearAviso={() => setFormulario({})} />
      )}
      {tab === 'mis' && notaPush && (
        <div role="status" className="flex items-start gap-3 rounded-xl border border-rendi-warn/30 bg-rendi-warn/5 px-4 py-3">
          <p className="flex-1 text-sm text-ink-1">{notaPush}</p>
          <button type="button" onClick={() => setNotaPush(null)} className="text-sm text-ink-2 hover:text-ink-1">Cerrar</button>
        </div>
      )}
      {/* Las notificaciones no se pueden activar en este dispositivo y alguno
          de tus avisos llega por ahí: se explica por qué y qué hacer. */}
      {tab === 'mis' && push.motivo && items.some(a => a.active && a.channel !== 'email') && (
        <AvisoNotificaciones motivo={push.motivo} plataforma={push.plataforma} origen="alertas" />
      )}
      {tab === 'mis' && (
        <MisAlertas items={items} events={events} precios={precios} resumen={resumen} hoy={hoy}
          cargando={loading} onEditar={a => setFormulario({ alerta: a })} onPausar={pausar}
          onIrACrear={() => irA('crear')} />
      )}
      {tab == null && <p className="py-10 text-center text-sm text-ink-2">Cargando…</p>}

      {formulario && (
        <AlertaForm plan={plan} alerta={formulario.alerta} prefill={formulario.prefill}
          onClose={() => setFormulario(null)}
          crear={create} actualizar={update} borrar={remove} onCreada={creada} />
      )}
    </div>
  )
}

function Pestana({ activa, onClick, children }) {
  return (
    <button type="button" role="tab" aria-selected={activa} onClick={onClick}
      className={`h-11 -mb-px inline-flex items-center border-b-2 text-[15px] transition-colors ${activa ? 'border-ink-0 text-ink-0 font-medium' : 'border-transparent text-ink-2 hover:text-ink-1'}`}>
      {children}
    </button>
  )
}
