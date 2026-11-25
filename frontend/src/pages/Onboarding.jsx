// Onboarding — la bienvenida obligatoria con Mervall-E (ruta /onboarding).
// ════════════════════════════════════════════════════════════════════════════
// Una cuenta nueva no ve Rendi hasta haber SUBIDO Y CONFIRMADO un archivo de su
// broker (o la planilla de Rendi, para un broker que Rendi no lee). Cargar a
// mano no destraba. Quién tiene que pasar por acá lo decide el servidor
// (`user.falta_cargar_historial`) y la regla de pantalla vive en
// utils/bienvenidaObligatoria.js; la puerta que manda acá está en App.jsx
// (Layout), igual que el muro de plan. Esta página se dibuja SIN el armazón de
// la app (sin menú, sin barras del celular, sin la barra de la prueba): sólo
// ella y el botón de WhatsApp, con links chicos al pie a lo que la puerta deja
// a la vista (Planes, Privacidad, Términos).
//
// Mervall-E guía todo hablando en un globo (GloboDeMervallE). Los pasos:
//   Configurá tu Rendi   1 hola      — saludo + la prueba gratis (días del servidor)
//                        2 broker    — la misma lista que el Paso 0 del importador,
//                                      más Wallbit (se conecta, no sube archivo)
//                        3 historial — cómo bajar el archivo + el importador
//   Últimos detalles     4 cartera   — «esto es lo que tenés hoy» (el momento wow)
//                        5 perfil    — opcional, con «Más tarde»
//                        6 celular   — opcional, sólo en el celular y sin la app
//                                      instalada; último a propósito: en iPhone
//                                      instalar saca de Safari y corta el recorrido
// Lo que deja para más tarde queda pendiente en la lista de primeros pasos de
// Inicio (components/home/OnboardingChecklist.jsx), que ya lo maneja.
//
// EL ESTADO DEL RECORRIDO VIVE ACÁ, no en el navegador. Si al montar a la
// persona no le falta nada, se va al inicio. Pero si a mitad de camino el
// servidor ya dice que cargó (pasa justo al confirmar el archivo), la página
// sigue con sus pasos hasta el final.
//
// EL PASO VA EN LA DIRECCIÓN (`/onboarding?paso=broker`), y cada paso nuevo
// AGREGA una entrada al historial: el «atrás» del celular (o deslizar para
// volver en el iPhone) vuelve al paso anterior en vez de irse de la página.
// Abrir el importador también agrega una (`&subiendo=1`), así «atrás» lo
// CIERRA. Lo que se escriba a mano en la dirección se corrige (pasoQueVa): un
// paso de después de cargar, sin haber cargado, va a «broker»; uno de antes,
// ya cargado, va a «tu cartera».
//
// QUÉ CUENTA COMO «YA CARGÓ»: lo que diga el servidor (`falta_cargar_historial`
// en false), venga de un archivo, de Wallbit o de lo que exista mañana. Al
// confirmar (o conectar Wallbit) se le pregunta enseguida; al cerrarse el
// importador sin una carga a la vista, se le pregunta igual. El cierre del
// recorrido (las marcas de «se acaba de configurar» y de «ya importó») se hace
// en el momento de la carga: si sale por «atrás» después de cargar, queda hecho.
//
// Medición: cada paso tiene su evento propio (`bienvenida_*`, utils/usoCatalogo):
// el panel de uso guarda sólo el nombre, y es la forma de ver dónde se va la gente.

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { AlertTriangle, ArrowRight, Check, ChevronLeft, Copy, Download, FileSpreadsheet, Lightbulb, LogOut, Plug, Smartphone, TrendingDown, TrendingUp, Upload } from 'lucide-react'
import RendiLogo from '../components/RendiLogo'
import PageMeta from '../components/PageMeta'
import MervallE from '../components/ai/MervallE'
import GloboDeMervallE from '../components/onboarding/GloboDeMervallE'
import ProgressBar from '../components/onboarding/ProgressBar'
import ImportWizard, { withBlockedPlatforms, brokersParaElegir } from '../components/import/ImportWizard'
import BrokerInstructions, { BROKER_GUIDES } from '../components/import/BrokerInstructions'
import InvestorProfileForm from '../components/InvestorProfileForm'
import InstalarAppModal from '../components/InstalarAppModal'
import AnimatedNumber from '../components/AnimatedNumber'
import DiagnosticText from '../components/DiagnosticText'
import { useAuth } from '../contexts/AuthContext'
import { usePrivacy, OCULTO } from '../contexts/PrivacyContext'
import { usePlanFeatures } from '../hooks/usePlanFeatures'
import { useIsMobile } from '../hooks/useIsMobile'
import { useCarteraRecienCargada } from '../hooks/useCarteraRecienCargada'
import { api, getClientContext } from '../utils/api'
import { track } from '../utils/track'
import { fmtUsd } from '../utils/format'
import { whatsappUrl } from '../utils/support'
import { faltaConfigurar, marcarRecienConfigurado } from '../utils/bienvenidaObligatoria'
import { descargarPlantilla, PLANILLA_DE_RENDI } from '../utils/descargarPlantilla'
import { hallazgosDeLaBienvenida } from '../utils/hallazgosDeLaBienvenida'
import { esCelular, plataformaDe, yaInstalada, hayInstalador, instalarAhora } from '../utils/instalarApp'
import { guardar as guardarEnAlmacen } from '../utils/almacen'
import { CATALOGO } from '../utils/catalogoDelAlmacen'

const TRAMO_1 = { titulo: 'Configurá tu Rendi', pasos: ['hola', 'broker', 'historial'], nombres: ['Hola', 'Tu broker', 'Tu historial'] }
const TRAMO_2 = { titulo: 'Últimos detalles', pasos: ['cartera', 'perfil', 'celular'], nombres: ['Tu cartera', 'Tu perfil', 'Tu celular'] }
const PASOS = [...TRAMO_1.pasos, ...TRAMO_2.pasos]
// Los pasos cortos se centran en la pantalla de la compu; los largos (la
// grilla de brokers, las instrucciones, el perfil) arrancan arriba.
const PASOS_CORTOS = ['hola', 'cartera', 'celular']

/** La dirección de un paso. «hola» es la bienvenida pelada. */
export function urlDe(paso, { subiendo = false } = {}) {
  if (paso === 'hola') return '/onboarding'
  return `/onboarding?paso=${paso}${subiendo ? '&subiendo=1' : ''}`
}

/** Qué paso se muestra, a partir del que pide la dirección (`?paso=`). La
 *  dirección la puede escribir cualquiera o traerla el «atrás»: lo que no tiene
 *  sentido se corrige acá, en un solo lugar.
 *   · sin paso (o uno que no existe)            → hola
 *   · uno de después de cargar, sin haber cargado → broker
 *   · uno de antes de cargar, ya cargado         → tu cartera (salvo el
 *     historial con el importador abierto: está mirando lo que importó)
 *   · el historial sin broker elegido (recargó)  → broker
 *   · el celular cuando ese paso no va           → perfil */
export function pasoQueVa(pedido, { yaCargo = false, conBroker = false, conPasoCelular = false, subiendo = false } = {}) {
  if (!PASOS.includes(pedido)) return 'hola'
  const antes = TRAMO_1.pasos.includes(pedido)
  if (yaCargo && antes) return pedido === 'historial' && subiendo && conBroker ? 'historial' : 'cartera'
  if (!yaCargo && !antes) return 'broker'
  if (pedido === 'historial' && !conBroker) return 'broker'
  if (pedido === 'celular' && !conPasoCelular) return 'perfil'
  return pedido
}

// El orden de la grilla de brokers: primero los argentinos más usados. Lo que
// el servidor devuelva y no esté acá va después, en el orden en que vino; la
// tarjeta «Otro / mi broker no está» siempre va al final (aparte).
export const ORDEN_DE_BROKERS = ['cocos', 'balanz', 'iol', 'bullmarket', 'ppi', 'ieb', 'inviu', 'wallbit', 'balanz_internacional', 'schwab', 'binance']

// Wallbit no es un lector de archivos (no viene en /imports/parsers/grouped):
// se conecta con una clave de solo lectura, en la rama «Integración con broker»
// del MISMO importador (WallbitConnect). Tiene tarjeta propia para que quien
// invierte ahí no tenga que adivinar que está escondido debajo de «Otro».
const WALLBIT = { platform: 'wallbit', platform_label: 'Wallbit', integracion: true }

/** La grilla de la bienvenida: la MISMA lista que el Paso 0 del importador
 *  (withBlockedPlatforms + brokersParaElegir), más Wallbit, en ORDEN_DE_BROKERS. */
export function brokersDeLaBienvenida(grupos) {
  const lista = brokersParaElegir(withBlockedPlatforms(grupos))
  if (!lista.some(g => g.platform === WALLBIT.platform)) lista.push(WALLBIT)
  const lugar = (g) => {
    const i = ORDEN_DE_BROKERS.indexOf(g.platform)
    return i === -1 ? ORDEN_DE_BROKERS.length : i
  }
  return lista
    .map((g, i) => ({ g, i }))
    .sort((a, b) => lugar(a.g) - lugar(b.g) || a.i - b.i)
    .map(x => x.g)
}

// Cuánto saluda Mervall-E al llegar antes de empezar a hablar.
const MS_SALUDO = 1300
// Cuánto festeja con la cartera a la vista (el festejo no descansa: gasta batería).
const MS_FESTEJO = 4200
// Cuánto se espera a la prueba gratis (/plan/features) antes de saludar sin ella.
const MS_ESPERA_PRUEBA = 2500

const BOTON = 'inline-flex items-center justify-center gap-2 font-medium rounded-xl transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-data-violet disabled:opacity-60'
const BOTON_1 = `${BOTON} h-12 px-6 text-[15px] bg-data-violet hover:bg-rendi-violet-hover text-white lp-sombra-boton hover:-translate-y-px`
const BOTON_2 = `${BOTON} h-12 px-5 text-[15px] bg-bg-1 text-ink-0 border border-line-2 hover:border-data-violet/60`

/** El primer nombre, o nada si lo que hay es el mail. */
export function primerNombre(nombre) {
  const n = String(nombre || '').trim()
  if (!n || n.includes('@')) return ''
  return n.split(/\s+/)[0]
}

/** Lo que dice Mervall-E en el saludo. Los días de la prueba salen del
 *  servidor (`trial` de /plan/features), nunca escritos acá. */
export function textoDelSaludo(nombre, trial) {
  const quien = primerNombre(nombre)
  const lineas = [`¡Hola${quien ? `, ${quien}` : ''}! Soy Mervall-E, y te voy a ayudar a armar tu Rendi.`]
  if (trial?.active && trial.pro_days && trial.plus_days) {
    const base = `${trial.pro_days} días de Rendi Pro y después ${trial.plus_days} de Plus, gratis y sin tarjeta`
    const left = trial.days_left
    if (left != null && trial.total_days && left < trial.total_days) {
      lineas.push(`Tu prueba son ${base}: ${left <= 1 ? 'te queda 1 día' : `te quedan ${left} días`}.`)
    } else {
      lineas.push(`Arrancás con ${base}.`)
    }
  }
  lineas.push('Para mostrarte tu plata necesito tu historial. Son un par de minutos.')
  return lineas
}

/** El nombre corto de un broker para que lo diga Mervall-E: el de su guía de
 *  descarga si la tiene («Cocos»), si no el del servidor sin lo de entre
 *  paréntesis («IOL (InvertirOnline)» → «IOL»). */
export function nombreCorto(grupo) {
  const guia = BROKER_GUIDES.find(b => b.id === grupo?.platform)
  if (guia?.label) return guia.label
  return String(grupo?.platform_label || '').split(/\s*[(·]/)[0].trim()
}

export default function Onboarding() {
  const { user, isDemo, bootstrapped } = useAuth()
  // ¿Le toca la bienvenida? Se decide UNA vez, con la sesión ya confirmada por
  // el servidor (antes de `bootstrapped` el usuario sale de lo guardado en el
  // navegador). Después, aunque el servidor diga que ya cargó, el recorrido
  // sigue hasta el final.
  const decidir = () => faltaConfigurar(user, { isDemo, clientCtx: getClientContext() })
  const [enCurso, setEnCurso] = useState(() => (bootstrapped ? decidir() : null))
  useEffect(() => {
    if (enCurso === null && bootstrapped) setEnCurso(decidir())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bootstrapped, enCurso])

  if (!user) return null
  if (enCurso === null) return <div className="min-h-[100dvh] bg-bg-0 bv-fondo" />
  if (!enCurso) return <Navigate to="/" replace />
  return <Recorrido />
}

function Recorrido() {
  const { user, refreshUser, updateUser, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const isMobile = useIsMobile()
  // En el teléfono (no por el ancho de la ventana): el paso de agregar Rendi al
  // inicio y el aviso de «bajalo desde la compu» son del aparato.
  const [enCelular] = useState(() => esCelular(typeof navigator === 'undefined' ? 'otro' : plataformaDe(navigator)))
  const [conPasoCelular] = useState(() => enCelular && !yaInstalada())

  const [cara, setCara] = useState('saludo')
  const [broker, setBroker] = useState(null)        // { platform, nombre, guia, integracion } · platform 'personal' = la planilla
  const [cargo, setCargo] = useState(false)
  const cargoRef = useRef(false)
  const refrescado = useRef(false)

  // ¿Ya cargó? Lo que vio esta página (confirmó un archivo, conectó Wallbit) o
  // lo que dice el servidor, venga de donde venga.
  const yaCargo = cargo || user?.falta_cargar_historial === false
  const pedido = params.get('paso')
  const subiendo = params.get('subiendo') === '1'
  const paso = pasoQueVa(pedido, { yaCargo, conBroker: !!broker, conPasoCelular, subiendo })
  const abierto = paso === 'historial' && subiendo

  useEffect(() => { track('bienvenida_hola') }, [])

  // Si la dirección pedía otra cosa (escrita a mano, un «atrás» a un paso que
  // ya no va), se corrige SIN agregar entrada: lo que se ve ya es el paso bueno.
  useEffect(() => {
    if (pedido !== (paso === 'hola' ? null : paso) || (subiendo && !abierto)) {
      navigate(urlDe(paso), { replace: true })
    }
  }, [pedido, paso, subiendo, abierto, navigate])

  const tramo = TRAMO_1.pasos.includes(paso) ? TRAMO_1 : TRAMO_2
  const pasosDelTramo = tramo.pasos.filter(p => p !== 'celular' || conPasoCelular)
  const nombres = pasosDelTramo.map(p => tramo.nombres[tramo.pasos.indexOf(p)])
  const nombreDelPaso = tramo.nombres[tramo.pasos.indexOf(paso)]

  // El foco del teclado y del lector de pantalla: al cambiar de paso, o al
  // cerrarse el importador, el botón que tenía el foco ya no existe y el foco
  // caía en la página entera (el lector volvía a leer desde arriba). Va al
  // título del paso, que dice dónde está. El globo se anuncia aparte.
  const tituloRef = useRef(null)
  const vista = `${paso}|${abierto}`
  const vistaAnterior = useRef(vista)
  const pasoAnterior = useRef(paso)
  useEffect(() => {
    if (vistaAnterior.current === vista) return
    vistaAnterior.current = vista
    if (pasoAnterior.current !== paso) {
      pasoAnterior.current = paso
      if (typeof window !== 'undefined') window.scrollTo?.(0, 0)
    }
    if (!abierto) tituloRef.current?.focus?.({ preventScroll: true })
  }, [vista, paso, abierto])

  /** Un paso nuevo: AGREGA una entrada al historial («atrás» vuelve acá). */
  function ir(siguiente) {
    navigate(urlDe(siguiente))
  }

  async function asegurarUsuarioAlDia() {
    if (refrescado.current) return true
    try { await refreshUser(); refrescado.current = true; return true } catch { return false }
  }

  // El cierre del recorrido, en UN lugar: que el tutorial de novedades no
  // arranque en esta misma visita, y que el próximo import (desde Importar o
  // Configuración) no lo mande a la primera lectura otra vez (esa pantalla ya
  // la vio acá, en «tu cartera»).
  function cerrarElRecorrido() {
    marcarRecienConfigurado()
    try { guardarEnAlmacen(CATALOGO.primeraImportacion, '1') } catch { /* sin almacenamiento: a lo sumo la ve una vez */ }
  }

  // Ya cargó. Se cierra el recorrido ACÁ y no recién al final: si sale por
  // «atrás» después de cargar, el cierre igual queda hecho.
  function registrarCarga() {
    if (cargoRef.current) return
    cargoRef.current = true
    setCargo(true)
    track('bienvenida_historial_cargado')
    cerrarElRecorrido()
  }

  // Confirmó un archivo o conectó Wallbit.
  async function onCargado() {
    registrarCarga()
    // Si el pedido falla (corte de señal, un reinicio del servidor), se marca
    // acá: la confirmación ya probó lo que mira el servidor. Sin esto, la
    // puerta lo devolvía al «¡Hola!» con el usuario viejo. El próximo
    // /auth/me pone el valor real.
    if (!(await asegurarUsuarioAlDia())) updateUser?.({ falta_cargar_historial: false })
  }

  // Lo que diga el servidor, venga de donde venga (otra pestaña, un refresco).
  useEffect(() => {
    if (user && user.falta_cargar_historial === false) registrarCarga()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.falta_cargar_historial])

  // Abrir el importador AGREGA una entrada: «atrás» lo cierra.
  function abrirSubida() {
    navigate(urlDe('historial', { subiendo: true }), { state: { subida: true } })
  }
  // Cerrarlo con su botón: con la carga hecha, a «tu cartera» (en lugar de la
  // entrada del importador); sin carga, se saca esa entrada.
  function cerrarSubida() {
    if (cargoRef.current || user?.falta_cargar_historial === false) {
      navigate(urlDe('cartera'), { replace: true })
    } else if (location.state?.subida) {
      navigate(-1)
    } else {
      navigate(urlDe('historial'), { replace: true })
    }
  }

  // Se cerró el importador (con su botón o con «atrás») sin una carga a la
  // vista: se le pregunta al servidor. Quien conectó Wallbit, o cargó por un
  // camino que esta página no escucha, pasa a «tu cartera» igual.
  const estabaAbierto = useRef(false)
  useEffect(() => {
    const antes = estabaAbierto.current
    estabaAbierto.current = abierto
    if (!antes || abierto || cargoRef.current) return
    refreshUser()
      .then(u => { if (u && u.falta_cargar_historial === false) { refrescado.current = true; registrarCarga() } })
      .catch(() => { /* sin respuesta: se queda acá, esperando */ })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [abierto])

  async function terminar() {
    track('bienvenida_terminada')
    cerrarElRecorrido()
    await asegurarUsuarioAlDia()
    navigate('/', { replace: true })
  }

  const props = { setCara, ir, broker }
  let contenido = null
  if (paso === 'hola') contenido = <PasoHola {...props} nombre={user?.name} />
  else if (paso === 'broker') contenido = <PasoBroker {...props} onElegir={(b) => { setBroker(b); ir('historial') }} />
  else if (paso === 'historial') {
    contenido = (
      <PasoHistorial {...props} enCelular={enCelular} abierto={abierto}
        onAbrir={abrirSubida} onCerrar={cerrarSubida} onCargado={onCargado} />
    )
  } else if (paso === 'cartera') contenido = <PasoCartera {...props} onSeguir={() => ir('perfil')} />
  else if (paso === 'perfil') {
    contenido = <PasoPerfil {...props} onSeguir={() => (conPasoCelular ? ir('celular') : terminar())} />
  } else if (paso === 'celular') contenido = <PasoCelular {...props} onSeguir={terminar} />

  const centrado = PASOS_CORTOS.includes(paso)
  const LINK_PIE = 'hover:text-ink-1 transition-colors underline-offset-2 hover:underline'

  return (
    <div className="min-h-[100dvh] bg-bg-0 bv-fondo text-ink-0 flex flex-col">
      <PageMeta
        title="Armá tu Rendi"
        description="Mervall-E te ayuda a cargar tu historial y armar tu cartera en Rendi."
        canonical="/onboarding"
        noindex={true}
      />

      <header className="max-w-4xl w-full mx-auto px-4 sm:px-6 pt-4 sm:pt-6 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2 flex-shrink-0">
          <RendiLogo size={26} />
          <span className="font-semibold text-[17px] tracking-tight">rendi</span>
        </div>
        <div className="w-48 sm:w-60">
          <ProgressBar steps={nombres} currentIndex={Math.max(0, pasosDelTramo.indexOf(paso))} titulo={tramo.titulo} />
        </div>
      </header>

      {/* En la compu la escena va centrada, con un ancho cómodo, y los pasos
          cortos bajan hasta el medio de la pantalla (`my-auto` en una columna
          flexible: si el contenido es largo, el margen se hace cero y arranca
          arriba, como debe). En el celular, una columna. */}
      <main className="flex-1 w-full max-w-4xl mx-auto px-4 sm:px-6 pt-5 sm:pt-10 md:pt-12 pb-24 md:pb-16 flex flex-col">
        <h1 ref={tituloRef} tabIndex={-1} className="sr-only">{`${tramo.titulo}: ${nombreDelPaso}`}</h1>
        <div className={`w-full grid grid-cols-1 md:grid-cols-[232px_minmax(0,1fr)] gap-3 md:gap-10 ${centrado ? 'items-start md:items-center md:my-auto' : 'items-start'}`}>
          {/* Mervall-E: un solo personaje en movimiento en toda la pantalla. No se
              vuelve a crear entre pasos (cambia de cara), así no «reaparece». */}
          <div className="flex justify-center">
            <div className="relative bv-aparece">
              <MervallE size={isMobile ? 96 : 232} estado={cara} />
              <span aria-hidden="true" className="hidden md:block absolute left-1/2 -translate-x-1/2 -bottom-2 w-40 h-5 rounded-full bv-piso" />
            </div>
          </div>
          <div className="min-w-0">
            {contenido}
          </div>
        </div>
      </main>

      {/* A la derecha queda lugar para el botón flotante de WhatsApp. Lo que
          la puerta deja a la vista (planes, lo legal) tiene su link acá: sin
          menú, era la única forma de llegar sin escribir la dirección. Lo legal
          abre aparte, para no perder el paso en que está. */}
      <footer className="max-w-4xl w-full mx-auto pl-4 pr-20 sm:pl-6 sm:pr-24 pb-6 flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px] text-ink-3">
        <a href={whatsappUrl('Hola, estoy armando mi Rendi y tengo una consulta: ')} target="_blank" rel="noopener noreferrer"
          className={LINK_PIE}>
          ¿Dudas? Escribinos por WhatsApp
        </a>
        <Link to="/planes" className={LINK_PIE}>Planes</Link>
        <Link to="/privacidad" target="_blank" rel="noopener noreferrer" className={LINK_PIE}>Privacidad</Link>
        <Link to="/terminos" target="_blank" rel="noopener noreferrer" className={LINK_PIE}>Términos</Link>
        <button type="button" onClick={logout} className="inline-flex items-center gap-1.5 hover:text-ink-1 transition-colors">
          <LogOut size={13} strokeWidth={1.75} aria-hidden="true" /> Cerrar sesión
        </button>
      </footer>
    </div>
  )
}

// ── 1. Hola ─────────────────────────────────────────────────────────────────

function PasoHola({ setCara, ir, nombre }) {
  const { trial, loading } = usePlanFeatures()
  // La frase de la prueba necesita los días del servidor: se espera un poco a
  // /plan/features (casi siempre ya está, se pidió al entrar). El texto se fija
  // la primera vez que se muestra: si cambiara a mitad de escribirse, saltaría.
  const [esperaVencida, setEsperaVencida] = useState(false)
  useEffect(() => { const t = setTimeout(() => setEsperaVencida(true), MS_ESPERA_PRUEBA); return () => clearTimeout(t) }, [])
  const llego = useRef(Date.now())
  const [saludo, setSaludo] = useState(null)       // { texto, demora }
  useEffect(() => {
    if (saludo || (loading && !esperaVencida)) return
    // Saluda con la mano al llegar y empieza a hablar cuando terminó de
    // saludar (o enseguida, si el plan tardó más que el saludo).
    setSaludo({ texto: textoDelSaludo(nombre, trial), demora: Math.max(0, MS_SALUDO - (Date.now() - llego.current)) })
  }, [saludo, loading, esperaVencida, nombre, trial])

  useEffect(() => { setCara('saludo') }, [setCara])
  useEffect(() => {
    if (!saludo) return
    const t = setTimeout(() => setCara(c => (c === 'saludo' ? 'hablando' : c)), saludo.demora)
    return () => clearTimeout(t)
  }, [saludo, setCara])

  return (
    <div className="space-y-5">
      {saludo && <GloboDeMervallE key="hola" texto={saludo.texto} demora={saludo.demora} onTermino={() => setCara('contento')} />}
      <div className="bv-entra" style={{ '--d': '600ms' }}>
        <button type="button" onClick={() => ir('broker')} className={`${BOTON_1} w-full sm:w-auto`}>
          Empecemos <ArrowRight size={17} strokeWidth={2} aria-hidden="true" />
        </button>
      </div>
    </div>
  )
}

// ── 2. Broker ───────────────────────────────────────────────────────────────

function PasoBroker({ setCara, onElegir }) {
  // La MISMA lista que el Paso 0 del importador (ImportWizard): los lectores
  // del servidor + las plataformas bloqueadas, que se muestran pero van a la
  // planilla. Más Wallbit, que se conecta en vez de subir un archivo
  // (brokersDeLaBienvenida). NO se crea el broker acá (POST /brokers): el
  // importador lo crea solo con el nombre que reconoce ('Cocos', 'Bull
  // Market'…), y crear «Cocos Capital» antes dejaba dos.
  const [grupos, setGrupos] = useState(null)
  const [fallo, setFallo] = useState(false)
  const [vuelta, setVuelta] = useState(0)
  useEffect(() => {
    let vivo = true
    setFallo(false)
    api.get('/imports/parsers/grouped')
      .then(g => { if (vivo) setGrupos(brokersDeLaBienvenida(g)) })
      // Sin la lista del servidor queda lo que no depende de ella (Wallbit y
      // «Otro»), y la opción de probar de nuevo.
      .catch(() => { if (vivo) { setGrupos(brokersDeLaBienvenida([])); setFallo(true) } })
    return () => { vivo = false }
  }, [vuelta])

  useEffect(() => { setCara('hablando') }, [setCara])

  function elegir(grupo) {
    track('bienvenida_broker_elegido')
    setCara('contento')
    if (!grupo) { onElegir({ platform: 'personal', nombre: null }); return }
    const nombre = nombreCorto(grupo)
    // Wallbit: el importador abre en la integración, donde se pega la clave.
    if (grupo.integracion) { onElegir({ platform: grupo.platform, nombre, integracion: true }); return }
    // Una plataforma bloqueada se encuentra por nombre pero todavía no se lee:
    // va a la planilla, diciendo cuál era.
    if (grupo.bloqueada) { onElegir({ platform: 'personal', nombre, bloqueada: true }); return }
    onElegir({ platform: grupo.platform, nombre, guia: BROKER_GUIDES.some(b => b.id === grupo.platform) })
  }

  return (
    <div className="space-y-5">
      <GloboDeMervallE key="broker"
        texto={['¿Con qué broker invertís?', 'Si tenés más de uno, empezá por el principal: los otros los sumás después.']}
        onTermino={() => setCara(c => (c === 'hablando' ? 'reposo' : c))} />
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-2.5">
        {grupos === null && Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="h-[60px] rounded-xl border border-line bg-bg-1/60 esqueleto" aria-hidden="true" />
        ))}
        {(grupos || []).map((g, i) => <TarjetaBroker key={g.platform} grupo={g} i={i} onClick={() => elegir(g)} />)}
        {grupos !== null && (
          <button type="button" onClick={() => elegir(null)}
            className="col-span-2 lg:col-span-3 bv-entra flex items-center gap-3 text-left px-4 py-3.5 rounded-xl border border-dashed border-line-3 bg-bg-1/50 hover:border-data-violet/60 hover:bg-data-violet/[0.04] transition-colors"
            style={{ '--d': `${Math.min(12, (grupos || []).length) * 40}ms` }}>
            <span className="w-9 h-9 rounded-xl bg-data-violet/10 text-data-violet grid place-items-center flex-shrink-0">
              <FileSpreadsheet size={18} strokeWidth={1.75} aria-hidden="true" />
            </span>
            <span className="min-w-0">
              <span className="block text-[14.5px] font-medium text-ink-0">Otro / mi broker no está</span>
              <span className="block text-[12.5px] text-ink-2 leading-snug">Interactive Brokers, Lemon, Mercado Pago… Lo cargamos con la planilla de Rendi.</span>
            </span>
          </button>
        )}
      </div>
      {fallo && (
        <p className="text-[13px] text-ink-2">
          No pude traer la lista de brokers.{' '}
          <button type="button" onClick={() => { setGrupos(null); setVuelta(v => v + 1) }} className="text-data-violet hover:underline underline-offset-2">
            Probar de nuevo
          </button>
        </p>
      )}
    </div>
  )
}

function TarjetaBroker({ grupo, i, onClick }) {
  const Logo = BROKER_GUIDES.find(b => b.id === grupo.platform)?.Logo
  return (
    <button type="button" onClick={onClick}
      className="bv-entra group flex items-center gap-2.5 sm:gap-3 min-w-0 min-h-[60px] text-left px-3 sm:px-3.5 py-3 rounded-xl border border-line bg-bg-1 hover:border-data-violet/60 hover:bg-data-violet/[0.04] hover:-translate-y-px transition-all"
      style={{ '--d': `${Math.min(i, 12) * 40}ms` }}>
      <span className="flex-shrink-0 w-7 h-7 grid place-items-center" aria-hidden="true">
        {Logo
          ? <Logo size={26} />
          : <span className="w-7 h-7 rounded-lg bg-data-violet/15 text-data-violet text-[13px] font-semibold grid place-items-center">{nombreCorto(grupo).slice(0, 1)}</span>}
      </span>
      {/* A 320 px «(InvertirOnline)» o «Internacional» no entran en media
          pantalla: se cortan (con guion, si el navegador sabe castellano)
          adentro de la tarjeta en vez de salirse por el borde. */}
      <span className="min-w-0 text-[14px] font-medium text-ink-0 leading-tight hyphens-auto [overflow-wrap:anywhere]">{grupo.platform_label}</span>
    </button>
  )
}

// ── 3. Historial ────────────────────────────────────────────────────────────

function PasoHistorial({ setCara, ir, broker, enCelular, abierto, onAbrir, onCerrar, onCargado }) {
  const [volvio, setVolvio] = useState(false)       // cerró el importador sin cargar
  const planilla = broker?.platform === 'personal'
  const integracion = !!broker?.integracion        // Wallbit: se conecta, no hay archivo

  // Recién eligió: festeja un instante y después explica.
  useEffect(() => {
    setCara('contento')
    const t = setTimeout(() => setCara(c => (c === 'contento' ? 'hablando' : c)), 900)
    return () => clearTimeout(t)
  }, [setCara])

  // El importador se cerró (con su botón o con «atrás») y la página sigue acá:
  // no hubo carga. Mervall-E espera. (Si hubo, la página ya pasó a «tu cartera».)
  const estabaAbierto = useRef(abierto)
  useEffect(() => {
    if (estabaAbierto.current && !abierto) { setVolvio(true); setCara('atento') }
    estabaAbierto.current = abierto
  }, [abierto, setCara])

  const texto = volvio
    ? [integracion ? 'Cuando tengas la clave, acá estoy.'
      : planilla ? 'Cuando tengas la planilla completa, acá estoy.'
        : 'Cuando tengas el archivo, acá estoy.']
    : integracion
      ? [`¡${broker?.nombre}, buenísimo!`,
        'Con Wallbit no hace falta ningún archivo: pegás una clave de solo lectura de tu cuenta y yo traigo tus operaciones.']
      : planilla
        ? [broker?.bloqueada
            ? `${broker.nombre} todavía no lo leo directo, pero no pasa nada: te doy la planilla de Rendi.`
            : '¡Dale! Para un broker que todavía no leo directo, te doy la planilla de Rendi.',
          'Bajala, anotá tus operaciones y subila acá. Abajo te dejo cómo completarla.']
        : [`¡${broker?.nombre}, buenísimo!`,
          `Necesito el archivo con tus movimientos. Abajo te dejo cómo bajarlo de ${broker?.nombre}; cuando lo tengas, subilo acá.`]

  function abrir() {
    track('bienvenida_subir_abierto')
    setCara('reposo')
    onAbrir()
  }

  // La planilla se da ACÁ, no dos pantallas más adelante adentro del
  // importador: quien eligió «Otro» la necesita antes de tener nada que subir.
  const [bajada, setBajada] = useState(false)
  const [errorBajada, setErrorBajada] = useState(false)
  async function bajarPlanilla() {
    setErrorBajada(false)
    try {
      await descargarPlantilla(PLANILLA_DE_RENDI)
      setBajada(true)
      setCara('contento')
      track('bienvenida_planilla_bajada')
    } catch {
      setErrorBajada(true)
    }
  }

  return (
    <div className="space-y-5">
      <GloboDeMervallE key={volvio ? 'volvio' : 'historial'} texto={texto} demora={volvio ? 0 : 900}
        onTermino={() => setCara(c => (c === 'hablando' || c === 'contento' ? 'atento' : c))} />

      {planilla ? (
        <TarjetaPlanilla bajada={bajada} error={errorBajada} enCelular={enCelular} nombreBroker={broker?.nombre}
          onBajar={bajarPlanilla} onSubir={abrir} onCambiar={() => ir('broker')} />
      ) : (
      <div className="bv-entra rounded-xl border border-line bg-bg-1 p-4 sm:p-5 space-y-3" style={{ '--d': '300ms' }}>
        <button type="button" onClick={abrir} className={`${BOTON_1} w-full sm:w-auto`}>
          {integracion
            ? <><Plug size={17} strokeWidth={2} aria-hidden="true" /> Conectar {broker?.nombre}</>
            : <><Upload size={17} strokeWidth={2} aria-hidden="true" /> Subir el archivo</>}
        </button>
        {enCelular && !integracion && (
          <p className="flex items-start gap-2 text-[13px] text-ink-2 leading-snug">
            <Smartphone size={15} strokeWidth={1.75} className="flex-shrink-0 mt-0.5 text-data-violet" aria-hidden="true" />
            <span>La mayoría de los brokers deja bajar este archivo sólo desde su página web. Si estás en el celular, entrá a rendi.finance desde la compu: te espero acá.</span>
          </p>
        )}
        <button type="button" onClick={() => ir('broker')}
          className="inline-flex items-center gap-1 text-[13px] text-ink-3 hover:text-ink-1 transition-colors">
          <ChevronLeft size={14} strokeWidth={1.75} aria-hidden="true" /> Cambiar de broker
        </button>
      </div>
      )}

      {!planilla && !integracion && broker?.guia && (
        <div className="bv-entra" style={{ '--d': '450ms' }}>
          <BrokerInstructions lockBrokerId={broker.platform} />
        </div>
      )}

      {/* Abierto o cerrado lo dice la dirección (`&subiendo=1`): así el «atrás»
          del celular cierra el importador en vez de irse de la página.
          Confirmar un archivo y conectar Wallbit cuentan igual: ya cargó. */}
      {abierto && (
        <ImportWizard
          plataformaInicial={broker?.platform}
          onConfirmed={() => onCargado()}
          onWallbitConnected={() => onCargado()}
          onClose={onCerrar}
        />
      )}
    </div>
  )
}

// La planilla de Rendi, para quien eligió «Otro / mi broker no está»: bajarla,
// completarla y subirla, en el orden en que se hace. El botón fuerte es el del
// paso que toca: antes de bajarla, «Descargar»; después, «Subir». Las columnas
// son las de la planilla (backend/importing/parsers/generic.py).
function TarjetaPlanilla({ bajada, error, enCelular, nombreBroker, onBajar, onSubir, onCambiar }) {
  return (
    <div className="bv-entra rounded-xl border border-line bg-bg-1 p-4 sm:p-5" style={{ '--d': '300ms' }}>
      <div className="flex items-center gap-3 mb-4">
        <span className="w-9 h-9 rounded-lg bg-data-violet/10 text-data-violet flex items-center justify-center flex-shrink-0">
          <FileSpreadsheet size={18} strokeWidth={1.75} aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <p className="text-[15px] font-medium text-ink-0">La planilla de Rendi</p>
          <p className="text-[12.5px] text-ink-3">Se abre con Excel o con Google Sheets.</p>
        </div>
      </div>

      <ol className="space-y-5">
        <PasoPlanilla n={1} titulo="Bajala">
          <button type="button" onClick={onBajar} className={`${bajada ? BOTON_2 : BOTON_1} w-full sm:w-auto mt-2.5`}>
            {bajada
              ? <><Check size={17} strokeWidth={2} aria-hidden="true" /> Ya la bajaste · bajarla de nuevo</>
              : <><Download size={17} strokeWidth={2} aria-hidden="true" /> Descargar la planilla</>}
          </button>
          {error && (
            <p role="alert" className="mt-2 text-[13px] text-rendi-neg">
              No pude bajar la planilla. Probá de nuevo, o escribinos por WhatsApp y te la mandamos.
            </p>
          )}
        </PasoPlanilla>

        <PasoPlanilla n={2} titulo="Completala con tus operaciones">
          <p className="mt-1">Una fila por cada compra, venta, depósito o retiro:</p>
          <ul className="mt-2 space-y-1">
            <li><span className="text-ink-0 font-medium">fecha</span>: año-mes-día, como 2024-03-15</li>
            <li><span className="text-ink-0 font-medium">tipo</span>: COMPRA, VENTA, DEPOSITO o RETIRO</li>
            <li><span className="text-ink-0 font-medium">broker</span>: el nombre de tu broker</li>
            <li><span className="text-ink-0 font-medium">activo</span>: el código, como GGAL o AAPL</li>
            <li><span className="text-ink-0 font-medium">cantidad</span>, <span className="text-ink-0 font-medium">precio</span> y <span className="text-ink-0 font-medium">moneda</span> (ARS o USD). En depósitos y retiros va el <span className="text-ink-0 font-medium">monto</span>.</li>
          </ul>
          {/* «1.500» la planilla lo lee como 1,5 (un punto solo es decimal:
              importing/normalizer.parse_number). Se avisa acá y en el pedido. */}
          <p className="mt-2">Los números, sin puntos de miles: 1500 o 1500.50.</p>
          <p className="mt-2 text-ink-3">Trae unas filas de ejemplo: borralas y dejá sólo las tuyas.</p>
          <AyudaConIA nombreBroker={nombreBroker} />
        </PasoPlanilla>

        <PasoPlanilla n={3} titulo="Subila acá">
          <button type="button" onClick={onSubir} className={`${bajada ? BOTON_1 : BOTON_2} w-full sm:w-auto mt-2.5`}>
            <Upload size={17} strokeWidth={2} aria-hidden="true" /> Subir la planilla completa
          </button>
        </PasoPlanilla>
      </ol>

      {enCelular && (
        <p className="mt-5 flex items-start gap-2 text-[13px] text-ink-2 leading-snug">
          <Smartphone size={15} strokeWidth={1.75} className="flex-shrink-0 mt-0.5 text-data-violet" aria-hidden="true" />
          <span>La planilla es más cómoda de completar en la compu. Si estás en el celular, entrá a rendi.finance desde la compu: te espero acá.</span>
        </p>
      )}
      <button type="button" onClick={onCambiar}
        className="mt-4 inline-flex items-center gap-1 text-[13px] text-ink-3 hover:text-ink-1 transition-colors">
        <ChevronLeft size={14} strokeWidth={1.75} aria-hidden="true" /> Cambiar de broker
      </button>
    </div>
  )
}

// El pedido para que una IA (ChatGPT, Gemini, Claude…) pase el archivo del
// broker a la planilla de Rendi. Las reglas son las que la planilla acepta de
// verdad: las columnas de importing/parsers/generic.GENERIC_HEADERS, los tipos de
// importing/schema (OP_TYPE_ALIASES) y los números de normalizer.parse_number,
// que lee «1.500» como 1,5: por eso se piden sin separador de miles.
export function pedidoParaLaIA(nombreBroker) {
  const broker = nombreBroker
    ? `siempre "${nombreBroker}"`
    : 'el nombre de mi broker, igual en todas las filas'
  return [
    `Te paso dos archivos: el de mi broker${nombreBroker ? ` (${nombreBroker})` : ''}, con mis operaciones, y la planilla de Rendi (planilla-de-rendi.csv).`,
    '',
    'Convertí mis operaciones al formato de la planilla de Rendi y devolveme un archivo CSV listo para descargar.',
    '',
    'Reglas:',
    '1. Usá exactamente estas columnas, en este orden: fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas',
    '2. Una fila por operación. Borrá las filas de ejemplo que trae la planilla.',
    '3. fecha: año-mes-día, por ejemplo 2024-03-15.',
    '4. tipo: COMPRA, VENTA, DEPOSITO, RETIRO, DIVIDENDO, INTERES, COMISION, CONVERSION_ARS_USD (pasé pesos a dólares) o CONVERSION_USD_ARS (pasé dólares a pesos).',
    `5. broker: ${broker}.`,
    '6. activo: el código del activo (por ejemplo GGAL, AAPL o AL30). Vacío en depósitos, retiros y conversiones.',
    '7. En compras y ventas: cantidad (siempre positiva) y precio por unidad. En depósitos, retiros, dividendos, intereses y comisiones: el monto (positivo). En conversiones: monto en pesos, monto_usd en dólares y tc con el tipo de cambio.',
    '8. comisiones: lo que cobró el broker en esa compra o venta (comisión más impuestos), si figura.',
    '9. moneda: ARS o USD.',
    '10. Números sin separador de miles y con punto decimal: 1500.50, nunca 1.500,50.',
    '11. Si no entendés alguna operación, no la inventes: dejala afuera y listala al final de tu respuesta para que la revise yo.',
  ].join('\n')
}

// Atajo para quien ya tiene el archivo de su broker aunque Rendi no lo lea: se
// lo pasa a una IA junto con la planilla y le pega este pedido. Lo hace la
// persona, en la IA que elija; Rendi recibe sólo la planilla que suba.
function AyudaConIA({ nombreBroker }) {
  const [abierto, setAbierto] = useState(false)
  const [copia, setCopia] = useState(null)          // null | 'ok' | 'fallo'
  const pedido = pedidoParaLaIA(nombreBroker)

  async function copiar() {
    setAbierto(true)
    try {
      await navigator.clipboard.writeText(pedido)
      setCopia('ok')
      track('bienvenida_pedido_ia_copiado')
    } catch {
      // Sin permiso para el portapapeles (http, navegador viejo): el texto ya
      // está a la vista para copiarlo a mano.
      setCopia('fallo')
    }
  }

  return (
    <div className="mt-4 rounded-xl border border-data-violet/30 bg-data-violet/[0.05] p-3.5 sm:p-4">
      <p className="text-[14px] font-medium text-ink-0">¿Tenés el archivo de tu broker? Que lo pase una IA.</p>
      <p className="mt-1">
        Subile a ChatGPT, Gemini o Claude el archivo de tu broker y la planilla de Rendi, y pegale este pedido:
        te devuelve la planilla completa.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={() => setAbierto(a => !a)} aria-expanded={abierto}
          className={`${BOTON} h-10 px-4 text-[14px] bg-bg-1 text-ink-0 border border-line-2 hover:border-data-violet/60`}>
          {abierto ? 'Ocultar el pedido' : 'Acá tenés el pedido para la IA'}
        </button>
        <button type="button" onClick={copiar}
          className={`${BOTON} h-10 px-4 text-[14px] bg-data-violet hover:bg-rendi-violet-hover text-white`}>
          {copia === 'ok'
            ? <><Check size={16} strokeWidth={2} aria-hidden="true" /> ¡Copiado!</>
            : <><Copy size={16} strokeWidth={2} aria-hidden="true" /> Copiar el pedido</>}
        </button>
      </div>
      <p role="status" className="mt-2 text-[13px] empty:hidden">
        {copia === 'ok' && <span className="text-rendi-pos">Listo: pegalo en la IA junto con los dos archivos.</span>}
        {copia === 'fallo' && <span className="text-ink-2">No pude copiarlo solo: seleccioná el texto de abajo y copialo.</span>}
      </p>
      {abierto && (
        <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-line bg-bg-0 p-3 text-[12.5px] leading-relaxed text-ink-1 font-sans select-all">
          {pedido}
        </pre>
      )}
      <p className="mt-2 text-[12px] text-ink-3">
        Lo hacés vos, en la IA que elijas: tus operaciones las ve esa IA. Rendi recibe sólo la planilla que subas, y la revisás antes de confirmar.
      </p>
    </div>
  )
}

function PasoPlanilla({ n, titulo, children }) {
  return (
    <li className="flex gap-3">
      <span className="w-6 h-6 rounded-full border border-data-violet/40 text-data-violet text-[12px] font-medium tabular flex items-center justify-center flex-shrink-0 mt-0.5">
        {n}
      </span>
      <div className="min-w-0 flex-1 text-[13.5px] text-ink-2 leading-relaxed">
        <p className="text-[14.5px] font-medium text-ink-0">{titulo}</p>
        {children}
      </div>
    </li>
  )
}

// ── 4. Tu cartera ───────────────────────────────────────────────────────────

function PasoCartera({ setCara, onSeguir }) {
  // El MISMO cálculo que /bienvenida (pages/FirstInsight.jsx).
  const { loading, stats, positions, brokers, tcValuacion } = useCarteraRecienCargada()
  const { hidden: oculto } = usePrivacy()
  const conValor = !!stats && stats.value > 0
  // Lo que Mervall-E encontró: 3 o 4 cosas, no sólo el total (utils/hallazgosDeLaBienvenida).
  const hallazgos = useMemo(
    () => (conValor ? hallazgosDeLaBienvenida({ stats, positions, brokers, tcValuacion, oculto }) : []),
    [conValor, stats, positions, brokers, tcValuacion, oculto])

  // «Vio "tu cartera vale…"» recién cuando el valor está a la vista: mientras
  // dice «estoy sumando todo…» todavía no lo vio, y sin precios no lo ve.
  const contada = useRef(false)
  useEffect(() => {
    if (loading || !conValor || contada.current) return
    contada.current = true
    track('bienvenida_cartera_vista')
    if (hallazgos.length) track('bienvenida_hallazgos_vistos')
  }, [loading, conValor, hallazgos.length])

  useEffect(() => {
    if (loading) { setCara('cargando'); return }
    if (!conValor) { setCara('contento'); return }
    setCara('festejo')
    const t = setTimeout(() => setCara('contento'), MS_FESTEJO)
    return () => clearTimeout(t)
  }, [loading, conValor, setCara])

  const texto = loading
    ? ['Dame un segundo, estoy sumando todo…']
    : conValor
      ? (hallazgos.length
          ? ['¡Listo! Leí todo tu historial.', 'Esto es lo que encontré en tu cartera:']
          : ['¡Listo! Esto es lo que tenés hoy.'])
      : ['¡Listo, ya tengo tu historial!', 'Todavía no tengo los precios para ponerle un valor a tu cartera: seguimos y lo ves en Inicio.']

  return (
    <div className="space-y-5">
      <GloboDeMervallE key={loading ? 'sumando' : 'listo'} texto={texto} />

      {!loading && conValor && (
        <div className="bv-entra relative overflow-hidden rounded-xl border border-line bg-bg-1 px-5 py-6 sm:px-7 sm:py-8" style={{ '--d': '150ms' }}>
          <span aria-hidden="true" className="absolute inset-0 bv-brillo" />
          <div className="relative">
            <div className="text-[13px] text-ink-2 mb-1">Tu cartera hoy</div>
            <div className="text-[clamp(26px,8vw,56px)] leading-none font-semibold tracking-tight tabular text-ink-0">
              <AnimatedNumber value={stats.value} format={(v) => (oculto ? OCULTO : fmtUsd(v))} />
            </div>
            <div className="mt-3 text-[14px] text-ink-1 tabular">
              {stats.positionCount} {stats.positionCount === 1 ? 'posición' : 'posiciones'} en {stats.brokerCount} {stats.brokerCount === 1 ? 'broker' : 'brokers'}
            </div>
          </div>
        </div>
      )}
      {loading && (
        <div className="h-[150px] rounded-xl border border-line bg-bg-1/60 esqueleto" aria-hidden="true" />
      )}

      {!loading && hallazgos.length > 0 && (
        <ul className="space-y-2.5" aria-label="Lo que encontré en tu cartera">
          {hallazgos.map((h, i) => (
            <Hallazgo key={h.id} hallazgo={h} demora={ENTRADA_HALLAZGOS_MS + i * ENTRE_HALLAZGOS_MS} />
          ))}
        </ul>
      )}

      {!loading && (
        <div className="bv-entra" style={{ '--d': `${hallazgos.length ? ENTRADA_HALLAZGOS_MS + hallazgos.length * ENTRE_HALLAZGOS_MS : 500}ms` }}>
          <button type="button" onClick={onSeguir} className={`${BOTON_1} w-full sm:w-auto`}>
            Seguir <ArrowRight size={17} strokeWidth={2} aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  )
}

// Los hallazgos entran de a uno, después de que el total terminó de contar: es
// Mervall-E contando lo que vio, no una tabla que aparece de golpe. Con
// «reducir movimiento», `bv-entra` no anima y aparecen todos juntos.
const ENTRADA_HALLAZGOS_MS = 900
const ENTRE_HALLAZGOS_MS = 450
const CARA_DEL_HALLAZGO = {
  pos: { Icono: TrendingUp, color: 'text-rendi-pos', fondo: 'bg-rendi-pos/10' },
  neg: { Icono: TrendingDown, color: 'text-rendi-neg', fondo: 'bg-rendi-neg/10' },
  atencion: { Icono: AlertTriangle, color: 'text-rendi-warn', fondo: 'bg-rendi-warn/10' },
  info: { Icono: Lightbulb, color: 'text-data-violet', fondo: 'bg-data-violet/10' },
}

function Hallazgo({ hallazgo, demora }) {
  const { Icono, color, fondo } = CARA_DEL_HALLAZGO[hallazgo.tono] || CARA_DEL_HALLAZGO.info
  return (
    <li className="bv-entra flex items-start gap-3 rounded-xl border border-line bg-bg-1 px-4 py-3.5" style={{ '--d': `${demora}ms` }}>
      <span className={`w-8 h-8 rounded-lg ${fondo} ${color} flex items-center justify-center flex-shrink-0`}>
        <Icono size={16} strokeWidth={2} aria-hidden="true" />
      </span>
      <p className="min-w-0 flex-1 text-[14px] sm:text-[15px] text-ink-1 leading-snug pt-1">
        <DiagnosticText text={hallazgo.texto} />
      </p>
    </li>
  )
}

// ── 5. Perfil de inversor (opcional) ────────────────────────────────────────

function PasoPerfil({ setCara, onSeguir }) {
  useEffect(() => { setCara('hablando') }, [setCara])
  // «Listo» sin ninguna respuesta no es un perfil hecho: cuenta como «más
  // tarde» (y la lista de Inicio lo sigue mostrando pendiente, como debe).
  const [respondidas, setRespondidas] = useState(0)
  function listo() { track(respondidas > 0 ? 'bienvenida_perfil_hecho' : 'bienvenida_perfil_despues'); onSeguir() }
  function despues() { track('bienvenida_perfil_despues'); onSeguir() }
  return (
    <div className="space-y-5">
      <GloboDeMervallE key="perfil"
        texto={['Contame un poco cómo invertís, así lo que te diga es para vos.', 'Son unos toques. Si preferís, lo dejamos para más tarde.']}
        onTermino={() => setCara(c => (c === 'hablando' ? 'reposo' : c))} />
      <div className="bv-entra rounded-xl border border-line bg-bg-1" style={{ '--d': '250ms' }}>
        <InvestorProfileForm onCambio={setRespondidas} />
      </div>
      {/* Pegados abajo: el formulario es largo y «Más tarde» no puede quedar
          escondido al final. A la derecha queda lugar para WhatsApp, que
          flota en esa esquina. */}
      <div className="sticky bottom-0 -mx-4 sm:mx-0 pl-4 pr-20 sm:px-0 py-3 bg-bg-0/90 backdrop-blur-sm flex gap-2.5">
        <button type="button" onClick={listo} className={`${BOTON_1} flex-1 sm:flex-none`}>Listo</button>
        <button type="button" onClick={despues} className={`${BOTON_2} flex-1 sm:flex-none`}>Más tarde</button>
      </div>
    </div>
  )
}

// ── 6. Rendi en el celular (opcional, sólo en el teléfono) ──────────────────

function PasoCelular({ setCara, onSeguir }) {
  const [modal, setModal] = useState(false)
  const [instalando, setInstalando] = useState(false)
  useEffect(() => { setCara('hablando') }, [setCara])

  async function mostrame() {
    track('bienvenida_celular_hecho')
    // En Android, si el navegador deja, se instala en un toque.
    if (hayInstalador()) {
      setInstalando(true)
      const r = await instalarAhora()
      track('instalar_app_un_toque', { resultado: r, origen: 'bienvenida' })
      setInstalando(false)
      if (r === 'accepted') { onSeguir(); return }
    }
    setModal(true)
  }
  function despues() { track('bienvenida_celular_despues'); onSeguir() }

  return (
    <div className="space-y-5">
      <GloboDeMervallE key="celular"
        texto={['¿Me ponés en la pantalla de inicio? Así entrás de un toque.', 'Sin App Store ni Play Store: queda con su ícono, como una app.']}
        onTermino={() => setCara(c => (c === 'hablando' ? 'atento' : c))} />
      <div className="bv-entra flex flex-col sm:flex-row gap-2.5" style={{ '--d': '300ms' }}>
        <button type="button" onClick={mostrame} disabled={instalando} className={`${BOTON_1} w-full sm:w-auto whitespace-nowrap`}>
          <Smartphone size={17} strokeWidth={2} aria-hidden="true" /> Mostrame cómo
        </button>
        <button type="button" onClick={despues} className={`${BOTON_2} w-full sm:w-auto`}>Más tarde</button>
      </div>
      <InstalarAppModal open={modal} origen="bienvenida" onClose={() => { setModal(false); onSeguir() }} />
    </div>
  )
}
