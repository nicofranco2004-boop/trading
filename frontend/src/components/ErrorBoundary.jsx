import { Component } from 'react'
import { AlertTriangle, RefreshCw, Eraser } from 'lucide-react'

// Sin esto, cualquier excepción en el render desmonta el árbol entero y deja la
// PANTALLA EN NEGRO: sin mensaje, sin pista, y sin forma de que el usuario se
// recupere solo. Pasó en producción (2026-07-30) y diagnosticarlo costó una hora
// porque desde afuera la app se veía perfecta.
//
// El segundo botón no es decorativo: la causa más probable de un crash que
// aparece en una sesión y NO en incógnito es un dato guardado en el navegador —
// el más peligroso es `rendi_client_ctx`, que hace que TODOS los pedidos de datos
// vayan por la cuenta de otro usuario (vista de asesor). Limpiar y recargar es
// exactamente la reparación de esa familia de fallas.
// Extraída para poder testearla: el riesgo real no es el render del cartel sino
// que este botón deslogue al usuario. `rendi_user` es la sesión y tiene que
// sobrevivir; todo lo demás (preferencias, contexto de cliente del asesor,
// flags de onboarding) se va.
export function limpiarEstadoLocal(ls, ss) {
  try {
    const user = ls ? ls.getItem('rendi_user') : null
    if (ls) ls.clear()
    if (ss) ss.clear()
    if (ls && user) ls.setItem('rendi_user', user)
  } catch { /* storage bloqueado: recargamos igual */ }
}


export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null, info: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    this.setState({ info })
    // eslint-disable-next-line no-console
    console.error('[Rendi] error no capturado:', error, info?.componentStack)
  }

  limpiarYRecargar = () => {
    limpiarEstadoLocal(
      typeof localStorage !== 'undefined' ? localStorage : null,
      typeof sessionStorage !== 'undefined' ? sessionStorage : null,
    )
    window.location.href = '/'
  }

  render() {
    const { error, info } = this.state
    if (!error) return this.props.children

    const detalle = [
      error?.message || String(error),
      error?.stack ? `\n${error.stack}` : '',
      info?.componentStack ? `\nComponente:${info.componentStack}` : '',
    ].join('')

    return (
      <div className="min-h-screen flex items-center justify-center p-6 bg-bg-0 text-ink-0">
        <div className="max-w-xl w-full space-y-4">
          <div className="flex items-center gap-2">
            <AlertTriangle size={20} className="text-amber-500" />
            <h1 className="text-lg font-semibold">Se rompió esta pantalla</h1>
          </div>
          <p className="text-sm text-ink-2 leading-relaxed">
            El resto de la app sigue funcionando. Probá recargar; si vuelve a pasar,
            usá <b>Limpiar datos guardados</b> — borra lo que Rendi guardó en este
            navegador (preferencias y contexto), no tus datos de la cuenta, y no te
            desloguea.
          </p>
          <div className="flex items-center gap-2 flex-wrap">
            <button onClick={() => window.location.reload()}
              className="flex items-center gap-1.5 text-sm px-3 py-2 rounded-md bg-violet-600 text-white hover:bg-violet-500">
              <RefreshCw size={14} /> Recargar
            </button>
            <button onClick={this.limpiarYRecargar}
              className="flex items-center gap-1.5 text-sm px-3 py-2 rounded-md bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0">
              <Eraser size={14} /> Limpiar datos guardados y recargar
            </button>
          </div>
          <details className="text-xs text-ink-3">
            <summary className="cursor-pointer select-none">Ver el detalle técnico</summary>
            <pre className="mt-2 p-3 rounded-md bg-bg-2 dark:bg-bg-2/40 overflow-auto max-h-64 whitespace-pre-wrap">
              {detalle}
            </pre>
          </details>
        </div>
      </div>
    )
  }
}
