/* global __BUILD_ID__ */
// ─── Auto-update proactivo ───────────────────────────────────────────────────
// Detecta cuando el server publicó un bundle MÁS NUEVO que el que ESTA pestaña
// booteó, y recarga en un momento SEGURO. Complementa el handler REACTIVO de
// "chunk viejo" de main.jsx (ese dispara cuando el user PISA un chunk borrado;
// este es PROACTIVO — agarra al user pegado en una página YA cargada, típico:
// la PWA en la pantalla de inicio del celular que quedó vieja).
//
// Mecánica: en el build inyectamos __BUILD_ID__ (SHA del commit) y escribimos
// dist/version.json con el MISMO id. El cliente pollea /version.json (no-store)
// y, si difiere, recarga cuando no molesta. En dev __BUILD_ID__ es 'dev' → no-op.
//
// SEGURIDAD (post-audit): (1) el guard anti-loop es POR-VERSIÓN con máximo de
// intentos → converge en vez de loopear si el HTML queda stale; (2) si
// sessionStorage no está (iOS privado) hacemos FAIL-CLOSED: no recargamos
// (mejor quedar viejo que loopear; el handler de chunks queda de red); (3) NO
// recargamos si el user está escribiendo, ni en flujos críticos (auth/billing),
// ni en los primeros segundos de vida de la página (evita pisar el post-login).
import { useEffect, useRef } from 'react'

// Vite reemplaza __BUILD_ID__ via `define`. El typeof + fallback evita un
// ReferenceError si el define no se aplicó (ej. el test runner de vitest).
const BUILD_ID = (typeof __BUILD_ID__ !== 'undefined' && __BUILD_ID__) || 'dev'

const CHECK_THROTTLE_MS = 60_000        // no pollear más de 1×/min
const RELOAD_GUARD_MS = 60_000          // no recargar 2× por versión en <60s
const MAX_RELOAD_ATTEMPTS = 2           // intentos de reload por versión → converge
const REOPEN_AWAY_MS = 10 * 60_000      // "reapertura" = la pestaña estuvo oculta >10 min
const POLL_INTERVAL_MS = 15 * 60_000    // backup: pollear cada 15 min
const START_GRACE_MS = 20_000           // no recargar por navegación en los 1ros 20s de vida

// Prefijos de ruta donde NUNCA recargamos (flujos sensibles con estado en vuelo).
const CRITICAL_PREFIXES = ['/login', '/verify-email', '/reset-password', '/onboarding', '/billing']

const APP_START = Date.now()

let updatePending = false
let pendingVersion = null
let inFlight = null   // Promise del fetch en vuelo (para coalescer), o null
let lastCheckAt = 0

async function fetchLatestVersion() {
  const res = await fetch(`/version.json?t=${Date.now()}`, {
    cache: 'no-store',
    credentials: 'omit',
  })
  if (!res.ok) return null
  // Si el SPA-fallback devolvió index.html (rewrite / 404), NO es JSON → ignorar
  // para no gatillar un "update" fantasma.
  const ct = res.headers.get('content-type') || ''
  if (!ct.includes('json') && !ct.includes('text/plain')) return null
  let data
  try {
    data = await res.json()
  } catch {
    return null
  }
  return data && typeof data.version === 'string' ? data.version : null
}

// Chequea si hay versión nueva. Devuelve (Promise de) true si quedó pendiente.
// `force` saltea el throttle. Coalesce: si ya hay un fetch en vuelo, se espera
// ESE (así una reapertura forzada no se pierde por un poll de fondo en curso).
export async function checkForUpdate({ force = false } = {}) {
  if (BUILD_ID === 'dev') return false
  // Si ya hay update pendiente y NO es forzado, no re-fetcheamos (ya sabemos que
  // hay que recargar). Pero un check FORZADO (reapertura/bfcache) SÍ re-consulta:
  // así aprende una versión aún más nueva y refresca el budget contra el target
  // correcto (si no, quedaría latcheado en la primera versión detectada).
  if (updatePending && !force) return true
  if (inFlight) return inFlight
  const now = Date.now()
  if (!force && now - lastCheckAt < CHECK_THROTTLE_MS) return false
  lastCheckAt = now
  inFlight = (async () => {
    try {
      const latest = await fetchLatestVersion()
      if (latest && latest !== BUILD_ID) {
        updatePending = true
        pendingVersion = latest
      }
    } catch {
      // offline / transitorio → reintenta en el próximo trigger
    } finally {
      inFlight = null
    }
    return updatePending
  })()
  return inFlight
}

// ¿El user está escribiendo? No pisamos un formulario a medio llenar.
function isUserBusy() {
  try {
    const el = document.activeElement
    if (!el) return false
    const tag = (el.tagName || '').toLowerCase()
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return true
    if (el.isContentEditable) return true
  } catch {
    // noop
  }
  return false
}

// ¿Estamos en un flujo crítico (auth/billing/onboarding)? No recargamos ahí.
function onCriticalPath() {
  try {
    const p = window.location.pathname || ''
    return CRITICAL_PREFIXES.some((pre) => p === pre || p.startsWith(pre + '/'))
  } catch {
    return false
  }
}

// Guard anti-loop POR-VERSIÓN, persistido en sessionStorage (sobrevive el reload
// same-tab). Converge: máximo MAX_RELOAD_ATTEMPTS intentos por versión-objetivo;
// si tras esos intentos seguimos en el build viejo (HTML stale que no cede), se
// DESISTE en vez de loopear. FAIL-CLOSED: si sessionStorage no está disponible
// (iOS privado / webview), devolvemos false (no recargar) — nunca sin freno.
function reloadBudgetOk(target) {
  try {
    const store = window.sessionStorage
    const now = Date.now()
    let g = null
    try {
      const raw = store.getItem('rendi_update_guard')
      g = raw ? JSON.parse(raw) : null
    } catch {
      g = null
    }
    if (!g || g.v !== target) g = { v: target, n: 0, at: 0 }
    if (now - (g.at || 0) < RELOAD_GUARD_MS) return false  // demasiado pronto
    if ((g.n || 0) >= MAX_RELOAD_ATTEMPTS) return false     // no converge → desistir
    g.n = (g.n || 0) + 1
    g.at = now
    store.setItem('rendi_update_guard', JSON.stringify(g))
    return true
  } catch {
    return false  // storage roto → fail-closed
  }
}

// Aplica el update recargando, SI es un momento seguro. No-op si: no hay update,
// el user escribe, estamos en un flujo crítico, no está la gracia de arranque
// (salvo `immediate`), o el budget por-versión está agotado.
export function applyUpdateIfPending({ immediate = false } = {}) {
  if (!updatePending || !pendingVersion) return false
  if (isUserBusy()) return false
  if (onCriticalPath()) return false
  if (!immediate && Date.now() - APP_START < START_GRACE_MS) return false
  if (!reloadBudgetOk(pendingVersion)) return false
  try {
    // Cache-buster (?_v): la URL nueva fuerza a re-pedir el HTML (best-effort
    // anti-cache de Safari), complementado por el no-store del header.
    const url = new URL(window.location.href)
    url.searchParams.set('_v', String(Date.now()))
    window.location.replace(url.toString())
  } catch {
    window.location.reload()
  }
  return true
}

// Hook: se monta UNA vez dentro del router y recibe el pathname actual.
// - Segundo plano: chequea al montar, al volver a la pestaña, y cada 15 min.
// - Reapertura larga (PWA/celular): recarga en el acto (immediate) si hay nueva.
// - Navegación: recarga al cambiar de pantalla si quedó update pendiente.
export function useAutoUpdate(pathname) {
  const prevPath = useRef(pathname)

  useEffect(() => {
    if (BUILD_ID === 'dev') return undefined
    checkForUpdate()
    let hiddenAt = 0
    const onVisibility = () => {
      if (document.visibilityState !== 'visible') {
        hiddenAt = Date.now()
        return
      }
      const awayMs = hiddenAt ? Date.now() - hiddenAt : 0
      hiddenAt = 0
      const reopened = awayMs > REOPEN_AWAY_MS
      checkForUpdate({ force: reopened }).then((pending) => {
        // En reapertura larga recargamos en el acto (immediate); isUserBusy /
        // onCriticalPath dentro de applyUpdateIfPending igual protegen.
        if (pending && reopened) applyUpdateIfPending({ immediate: true })
      })
    }
    // bfcache (Safari/iOS/PWA): al restaurar la página congelada NO siempre
    // corre visibilitychange(hidden), pero SÍ pageshow(persisted). Lo tratamos
    // como reapertura → check forzado + reload inmediato si hay versión nueva.
    // Es el path real del resume de la PWA en la pantalla de inicio del celular.
    const onPageShow = (e) => {
      if (e && e.persisted) {
        checkForUpdate({ force: true }).then((pending) => {
          if (pending) applyUpdateIfPending({ immediate: true })
        })
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('focus', onVisibility)
    window.addEventListener('pageshow', onPageShow)
    // Poll de fondo: además de chequear, INTENTA aplicar (gateado igual por
    // isUserBusy/onCriticalPath/budget/gracia). Cubre la pestaña/PWA quieta y
    // enfocada que no navega ni se backgroundea — si no, quedaría vieja para
    // siempre (justo el caso que este módulo dice querer resolver).
    const id = setInterval(() => {
      checkForUpdate().then((pending) => { if (pending) applyUpdateIfPending() })
    }, POLL_INTERVAL_MS)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('focus', onVisibility)
      window.removeEventListener('pageshow', onPageShow)
      clearInterval(id)
    }
  }, [])

  // En cada navegación REAL (path distinto del anterior): si hay update pendiente
  // y es un momento seguro, recargamos. prevPath se reasigna en cada cambio.
  useEffect(() => {
    if (pathname !== prevPath.current) {
      prevPath.current = pathname
      applyUpdateIfPending()
    }
  }, [pathname])
}
