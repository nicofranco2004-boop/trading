// BuscadorRapido — ⌘K (Ctrl+K en Windows) desde cualquier pantalla de la compu:
// una caja donde escribís "NVDA" y vas a tu posición, "dólar" y vas a Mercado,
// "cargar" y se abre una operación nueva, o escribís una pregunta y se la lleva
// a Rendi AI. Qué ofrece y en qué orden: utils/buscadorRapido.js. Las
// pantallas son las MISMAS del menú lateral (utils/navegacion.js).
//
// Sólo compu: en el celular no hay teclado con ⌘ y el buscador es la pantalla
// /buscar. También se abre con el botón "Buscar" del menú (evento
// `rendi:abrir-buscador`).
//
// Una pantalla que tiene SU propio ⌘K (Calidad de cartera busca empresas) lo
// atiende en la fase de captura y marca `preventDefault`: este lo respeta.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  Search, Sparkles, Plus, Repeat, Sun, Moon, EyeOff, Eye, TrendingUp, Building2,
} from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import { useCurrency } from '../contexts/CurrencyContext'
import { useTheme } from '../contexts/ThemeContext'
import { usePrivacy } from '../contexts/PrivacyContext'
import { useCoachDrawer } from '../contexts/CoachDrawerContext'
import { usePlanFeatures } from '../hooks/usePlanFeatures'
import { puedeChatLibre } from '../utils/chatLibre'
import { muroTapaLaPantalla } from '../utils/muroDePlan'
import { api } from '../utils/api'
import { pantallasVisibles, menuVisible } from '../utils/navegacion'
import { tickerName, POPULAR_TICKERS } from '../utils/tickers'
import {
  resultadosDelBuscador, opcionesDeActivos, opcionesDeEmpresas, esAtajoBuscador, esMac, urlNuevaOperacion, claveDeActivos,
} from '../utils/buscadorRapido'

export const EVENTO_ABRIR_BUSCADOR = 'rendi:abrir-buscador'
export function abrirBuscador() {
  window.dispatchEvent(new CustomEvent(EVENTO_ABRIR_BUSCADOR))
}

// "⌘K" en Mac, "Ctrl K" en el resto: lo que hay que apretar de verdad.
export function atajoBuscador() {
  return esMac() ? '⌘K' : 'Ctrl K'
}

// ¿Está abierto? Una pantalla con su propio ⌘K (Calidad de cartera) lo atiende
// sólo con el buscador CERRADO: abierto, ⌘K lo cierra, no abre otra ventana.
let _abierto = false
export function buscadorAbierto() { return _abierto }

// Palabras con las que la gente busca una pantalla aunque no sea su nombre.
const CLAVES = {
  '/':                 ['mercado', 'dólar', 'mep', 'blue', 'ccl', 'cotizaciones', 'merval', 'S&P', 'bitcoin', 'índices'],
  '/novedades':        ['noticias'],
  '/dashboard':        ['inicio', 'patrimonio', 'resumen'],
  '/posiciones':       ['posiciones', 'tenencias', 'activos'],
  '/operaciones':      ['operaciones', 'compras', 'ventas', 'historial'],
  '/analisis':         ['rendimiento', 'performance', 'análisis'],
  '/fundamentals':     ['fundamentals', 'empresas', 'calidad'],
  '/perfil-inversor':  ['perfil', 'riesgo'],
  '/alertas':          ['avisos', 'notificaciones'],
  '/imports':          ['importar', 'csv', 'excel', 'archivo'],
  '/clientes':         ['asesor', 'clientes'],
  '/cobros':           ['cupones', 'amortizaciones'],
  '/importar-historiales': ['importar', 'clientes'],
  '/config':           ['ajustes', 'cuenta', 'plan', 'suscripción'],
  '/guia':             ['ayuda', 'manual', 'cómo'],
  '/admin':            ['administración'],
}
// Lo que se ve al abrir, antes de escribir.
const DE_ENTRADA = new Set(['/dashboard', '/posiciones', '/operaciones', '/', '/clientes', '/cobros'])

// Tus activos: se muestran al instante los de la última vez y SIEMPRE se
// vuelven a pedir al abrir (una posición recién cargada tiene que aparecer).
// Se guardan por USUARIO y por cuenta: cerrar sesión no recarga la página, y
// en una compu compartida el que entra después no puede ver los tickers del
// anterior (mismo motivo por el que AuthContext.logout limpia el registro de
// brokers). Un asesor adentro de un cliente ve los del cliente.
const _activos = new Map()   // `${usuario}:${cuenta}` → lista

export default function BuscadorRapido() {
  const [abierto, setAbierto] = useState(false)
  const [consulta, setConsulta] = useState('')
  const [sel, setSel] = useState(0)
  const [posiciones, setPosiciones] = useState([])
  const inputRef = useRef(null)
  const navigate = useNavigate()
  const { pathname, search } = useLocation()
  const { user } = useAuth()
  const { clientCtx } = useAdvisorContext()
  const { currency, setCurrency } = useCurrency()
  const { dark, toggle: cambiarTema } = useTheme()
  const { hidden, toggle: cambiarPrivacidad } = usePrivacy()
  const coach = useCoachDrawer()
  const { isPro, isAdmin } = usePlanFeatures()
  const chatLibre = puedeChatLibre({ isPro, isAdmin, user, clientCtx })
  const { atOwnLevel } = menuVisible({ user, clientCtx })

  const cerrar = useCallback(() => { setAbierto(false); setConsulta(''); setSel(0) }, [])

  // Con el muro de "elegí un plan" puesto no se abre: quedaría debajo del muro,
  // invisible y con el teclado atrapado adentro.
  const tapadoRef = useRef(false)
  tapadoRef.current = muroTapaLaPantalla(user, pathname)

  // ⌘K / Ctrl+K y el botón del menú.
  useEffect(() => {
    const mac = esMac()
    const onKey = (e) => {
      if (!esAtajoBuscador(e, mac)) return
      if (e.repeat) return                  // dejarlo apretado no abre y cierra en ráfaga
      if (e.defaultPrevented) return        // la pantalla tiene su propio ⌘K
      if (tapadoRef.current) return
      e.preventDefault()
      setAbierto(a => !a)
    }
    const onAbrir = () => { if (!tapadoRef.current) setAbierto(true) }
    window.addEventListener('keydown', onKey)
    window.addEventListener(EVENTO_ABRIR_BUSCADOR, onAbrir)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener(EVENTO_ABRIR_BUSCADOR, onAbrir)
    }
  }, [])

  // Al cambiar de pantalla, se cierra.
  useEffect(() => { cerrar() }, [pathname, cerrar])

  // Si se desarma abierto (achicar la ventana a celular, cerrar sesión), no
  // puede quedar marcado como abierto: la pantalla con su propio ⌘K dejaría de
  // andar para siempre.
  useEffect(() => {
    _abierto = abierto
    return () => { _abierto = false }
  }, [abierto])

  // Al cerrar, el foco vuelve a donde estaba (el botón "Buscar…", el campo en
  // el que escribías): con teclado no quedás perdido arriba de la página.
  const focoAntes = useRef(null)
  useEffect(() => {
    if (abierto) { focoAntes.current = document.activeElement; return }
    const el = focoAntes.current
    focoAntes.current = null
    if (el && el !== document.body && document.contains(el) && typeof el.focus === 'function') el.focus()
  }, [abierto])

  // Tus activos se piden de antemano (2 s después de cargar, una vez por
  // cuenta): la primera vez que abrías el buscador todavía no habían llegado,
  // y "nvda" + Enter rápido te llevaba a la empresa en vez de a tu posición.
  const claveActivos = atOwnLevel ? null : claveDeActivos(user, clientCtx)
  useEffect(() => {
    if (!claveActivos || _activos.has(claveActivos)) return
    let vigente = true
    const id = setTimeout(() => {
      api.get('/positions')
        .then(lista => { if (vigente && Array.isArray(lista)) _activos.set(claveActivos, lista) })
        .catch(() => {})
    }, 2000)
    return () => { vigente = false; clearTimeout(id) }
  }, [claveActivos])

  // Al abrir: foco en la caja; tus activos de la última vez al instante, y
  // pedidos de nuevo.
  useEffect(() => {
    if (!abierto) return
    inputRef.current?.focus()
    const clave = claveActivos
    if (!clave) { setPosiciones([]); return }
    setPosiciones(_activos.get(clave) || [])
    let vigente = true
    api.get('/positions')
      .then(lista => {
        const l = Array.isArray(lista) ? lista : []
        _activos.set(clave, l)
        if (vigente) setPosiciones(l)
      })
      .catch(() => {})
    return () => { vigente = false }
  }, [abierto, claveActivos])

  // Las empresas que no tenés: la MISMA lista que ofrece el buscador propio de
  // Calidad de cartera (components/fundamentals/TickerSearch), que es la
  // pantalla que las abre. Otra lista ofrecería tickers que esa pantalla no.
  const universo = useMemo(() => opcionesDeEmpresas(POPULAR_TICKERS), [])

  const opciones = useMemo(() => {
    const pantallas = pantallasVisibles({ user, clientCtx }).map(p => ({
      clase: 'pantalla', id: `pantalla:${p.to}`, titulo: p.label,
      detalle: p.grupo || 'Pantalla', claves: CLAVES[p.to] || [], ir: p.to, icon: p.icon,
      deEntrada: DE_ENTRADA.has(p.to),
    }))
    // Rendi AI no es una ruta del menú (el botón abre la página con
    // useCoachDrawer, que además marca la función como descubierta).
    const extra = [
      { clase: 'pantalla', id: 'pantalla:/ai', titulo: 'Rendi AI', detalle: 'Asistente', claves: ['ia', 'asistente', 'preguntar', 'coach'], icon: Sparkles, deEntrada: true, hacer: () => coach.open() },
    ]
    const acciones = [
      ...(atOwnLevel ? [] : [{
        clase: 'accion', id: 'accion:cargar', titulo: 'Cargar una operación', detalle: 'Acción',
        claves: ['compra', 'venta', 'nueva', 'agregar', 'operación'], icon: Plus, deEntrada: true,
        hacer: () => navigate(urlNuevaOperacion(pathname, search)),
      }]),
      {
        clase: 'accion', id: 'accion:moneda',
        titulo: currency === 'ARS' ? 'Ver todo en dólares' : 'Ver todo en pesos', detalle: 'Acción',
        claves: ['moneda', 'pesos', 'dólares', 'usd', 'ars'], icon: Repeat,
        hacer: () => setCurrency(currency === 'ARS' ? 'USD' : 'ARS'),
      },
      {
        clase: 'accion', id: 'accion:tema', titulo: dark ? 'Modo claro' : 'Modo oscuro', detalle: 'Acción',
        claves: ['tema', 'oscuro', 'claro', 'dark'], icon: dark ? Sun : Moon, hacer: cambiarTema,
      },
      {
        clase: 'accion', id: 'accion:privacidad', titulo: hidden ? 'Mostrar los montos' : 'Ocultar los montos', detalle: 'Acción',
        claves: ['privacidad', 'ocultar', 'mostrar', 'montos'], icon: hidden ? Eye : EyeOff, hacer: cambiarPrivacidad,
      },
    ]
    const activos = opcionesDeActivos(posiciones, tickerName).map(o => ({ ...o, icon: TrendingUp }))
    const empresas = universo.map(o => ({ ...o, icon: Building2 }))
    return [...activos, ...acciones.filter(a => a.deEntrada), ...pantallas, ...extra, ...acciones.filter(a => !a.deEntrada), ...empresas]
  }, [user, clientCtx, atOwnLevel, posiciones, universo, currency, dark, hidden, setCurrency, cambiarTema, cambiarPrivacidad, coach, navigate, pathname, search])

  const resultados = useMemo(() => resultadosDelBuscador(opciones, consulta, { chatLibre }), [opciones, consulta, chatLibre])
  const actual = Math.min(sel, Math.max(0, resultados.length - 1))

  function elegir(o) {
    if (!o) return
    cerrar()
    if (o.clase === 'ia') coach.open(o.pregunta || null)
    else if (o.hacer) o.hacer()
    else if (o.ir) navigate(o.ir)
  }

  const mac = useMemo(() => esMac(), [])
  function onKeyDown(e) {
    // Lo que se teclea acá no sale del buscador (salvo ⌘K, que lo cierra). Las
    // ventanas de abajo escuchan Esc en toda la página (AddPositionFlow,
    // PfFormModal, BottomSheet…): sin esto, cerrar el buscador con Esc cerraba
    // también el formulario a medio llenar de "Registrar compra" y se perdía.
    if (!esAtajoBuscador(e, mac)) e.stopPropagation()
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel(i => Math.min(resultados.length - 1, i + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel(i => Math.max(0, i - 1)) }
    else if (e.key === 'Enter') { e.preventDefault(); elegir(resultados[actual]) }
    else if (e.key === 'Escape') { e.preventDefault(); cerrar() }
    // La caja es lo único enfocable: Tab no se escapa a la página de atrás
    // (la ventana es modal).
    else if (e.key === 'Tab') { e.preventDefault() }
  }

  if (!abierto) return null
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 backdrop-blur-sm px-4 pt-[14vh]"
      onMouseDown={(e) => { if (e.target === e.currentTarget) cerrar() }}
    >
      <div role="dialog" aria-modal="true" aria-label="Buscar en Rendi"
        className="entra w-full max-w-xl bg-bg-1 border border-line rounded-xl shadow-2xl overflow-hidden">
        <div className="flex items-center gap-2.5 px-4 border-b border-line">
          <Search size={16} strokeWidth={1.75} className="text-ink-3 flex-none" aria-hidden="true" />
          <input
            ref={inputRef}
            value={consulta}
            onChange={(e) => { setConsulta(e.target.value); setSel(0) }}
            onKeyDown={onKeyDown}
            placeholder="NVDA, dólar, cargar… o una pregunta"
            role="combobox"
            aria-autocomplete="list"
            aria-expanded="true"
            aria-controls="buscador-rapido-lista"
            aria-activedescendant={resultados[actual] ? `buscador-${actual}` : undefined}
            className="flex-1 min-w-0 bg-transparent py-3.5 text-[15px] text-ink-0 placeholder:text-ink-3 focus:outline-none"
          />
          <kbd className="text-[11px] text-ink-3 border border-line rounded px-1.5 py-0.5">esc</kbd>
        </div>
        <ul id="buscador-rapido-lista" role="listbox" className="max-h-[50vh] overflow-y-auto p-1.5">
          {resultados.map((o, i) => {
            const Icono = o.clase === 'ia' ? Sparkles : (o.icon || Search)
            return (
              <li key={o.id} id={`buscador-${i}`} role="option" aria-selected={i === actual}
                onMouseMove={() => setSel(i)}
                onClick={() => elegir(o)}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer text-[14px] ${i === actual ? 'bg-bg-2 text-ink-0' : 'text-ink-1'}`}>
                <Icono size={16} strokeWidth={1.75} aria-hidden="true"
                  className={`flex-none ${o.clase === 'ia' ? 'text-data-violet' : 'text-ink-3'}`} />
                <span className="flex-1 min-w-0 truncate">{o.titulo}</span>
                <span className="text-[12px] text-ink-3 flex-none">{o.detalle}</span>
              </li>
            )
          })}
        </ul>
        <div className="flex items-center gap-4 px-4 py-2 border-t border-line text-[11.5px] text-ink-3">
          <span>↑↓ para moverte</span><span>Enter para ir</span><span className="ml-auto">{atajoBuscador()} abre y cierra</span>
        </div>
      </div>
    </div>
  )
}
