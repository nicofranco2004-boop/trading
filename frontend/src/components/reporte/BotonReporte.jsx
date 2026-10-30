// BotonReporte — "Descargar reporte": el reporte de la cartera en PDF.
// ═══════════════════════════════════════════════════════════════════════════
// El recorrido: botón → PreguntaMontos (la misma pregunta que la imagen para
// compartir) → vista previa del papel a pantalla completa → "Descargar PDF".
//
// El PDF lo hace el navegador (window.print → "Guardar como PDF"), igual que
// el informe público del asesor: cero dependencias, el texto sale como texto
// (se puede copiar y buscar) y en el celular abre el menú nativo para guardar
// o mandar el archivo. Al imprimir, el CSS de abajo esconde TODA la app y deja
// sólo el papel.
//
// Los datos se arman UNA vez, al contestar la pregunta, y quedan congelados:
// los precios de Análisis se refrescan solos y el PDF tiene que ser lo que el
// usuario está viendo en la vista previa.

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { FileText, Download, X, Eye, EyeOff } from 'lucide-react'
import PreguntaMontos from '../PreguntaMontos'
import ReporteCartera from './ReporteCartera'
import { P } from '../../pages/ReportPublic'
import { track } from '../../utils/track'
import { hoyISO } from '../../utils/fecha'

const CSS_IMPRESION = `
  @media print {
    @page { margin: 12mm; }
    /* El fondo de la app (oscuro) se colaba en los márgenes de la hoja. Y con
       el tema oscuro Chromium pinta el MARGEN de la página con el color de su
       \`color-scheme\` (index.css lo pone en dark): sin forzarlo a claro, los
       12 mm salían negros (verificado con page.pdf). */
    :root { color-scheme: light !important; }
    html, body { background: ${P.paper} !important; }
    body > *:not(.reporte-portal) { display: none !important; }
    .reporte-portal { position: static !important; display: block !important; overflow: visible !important; background: ${P.paper} !important; padding: 0 !important; }
    .reporte-cuerpo { overflow: visible !important; padding: 0 !important; }
    .reporte-no-print { display: none !important; }
    .reporte-papel { box-shadow: none !important; border-radius: 0 !important; padding: 0 !important; max-width: none !important; }
    .reporte-papel, .reporte-papel * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }
`

export default function BotonReporte({ armarDatos, source = 'analisis' }) {
  // null → cerrado · 'pregunta' → eligiendo montos · 'vista' → vista previa
  const [paso, setPaso] = useState(null)
  const [mostrarMontos, setMostrarMontos] = useState(false)
  const [datos, setDatos] = useState(null)
  // El título de la pestaña mientras se imprime (ver `descargar`) y cómo
  // volverlo atrás: al terminar la impresión o al cerrar, lo que pase primero.
  const tituloRef = useRef(null)

  const restaurarTitulo = () => {
    const t = tituloRef.current
    if (!t) return
    document.title = t.antes
    window.removeEventListener('afterprint', t.volver)
    tituloRef.current = null
  }

  // Cambiar montos en la vista previa vuelve a armar el papel, pero no es otro
  // reporte: "generado" se cuenta sólo al contestar la pregunta.
  const armar = (conMontos) => {
    setMostrarMontos(conMontos)
    setDatos(armarDatos({ mostrarMontos: conMontos }))
  }
  const elegir = (conMontos) => {
    armar(conMontos)
    setPaso('vista')
    track('reporte_generado', { source, montos: conMontos ? 'visibles' : 'ocultos' })
  }
  const cerrar = () => { restaurarTitulo(); setPaso(null); setDatos(null) }

  useEffect(() => {
    if (!paso) return
    const onKey = (e) => { if (e.key === 'Escape') cerrar() }
    document.addEventListener('keydown', onKey)
    // Con la pregunta o la vista previa abiertas la página de atrás no scrollea.
    const overflowAntes = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflowAntes
    }
  }, [paso])

  // Si el componente se va con el título cambiado (navegar en medio), se vuelve.
  useEffect(() => () => restaurarTitulo(), [])

  function descargar() {
    // El título de la pestaña es el nombre que el navegador le propone al PDF.
    // Dos toques seguidos (en el celular print() no bloquea) no pisan el
    // título original con el del reporte: se guarda una sola vez.
    if (!tituloRef.current) {
      const volver = () => restaurarTitulo()
      tituloRef.current = { antes: document.title, volver }
      window.addEventListener('afterprint', volver)
    }
    document.title = `Reporte de cartera Rendi ${hoyISO()}`
    track('reporte_descargado', { source, montos: mostrarMontos ? 'visibles' : 'ocultos' })
    window.print()
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setPaso('pregunta')}
        className="inline-flex items-center gap-1.5 text-xs bg-bg-2/60 hover:bg-bg-2 text-ink-1 border border-line/60 px-2.5 py-1.5 rounded-sm transition-colors"
      >
        <FileText size={12} strokeWidth={1.75} />
        Descargar reporte
      </button>

      {paso === 'pregunta' && typeof document !== 'undefined' && createPortal(
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center p-3 bg-black/70 backdrop-blur-sm"
          onClick={cerrar}
          role="dialog"
          aria-modal="true"
          aria-label="Reporte de cartera"
        >
          <div onClick={(e) => e.stopPropagation()} className="bg-bg-1 border border-line-2 rounded-lg shadow-2xl w-full max-w-md">
            <header className="flex items-center justify-between gap-2 px-4 py-3 border-b border-line/40">
              <div className="min-w-0">
                <div className="text-[12.5px] text-ink-2 leading-none font-medium">Reporte de cartera</div>
                <h2 className="text-sm font-medium text-ink-0 mt-1.5 leading-none">¿Mostramos los montos?</h2>
              </div>
              <button onClick={cerrar} className="text-ink-3 hover:text-ink-0 transition-colors p-1" aria-label="Cerrar">
                <X size={16} strokeWidth={1.75} />
              </button>
            </header>
            <div className="p-4">
              <PreguntaMontos
                onElegir={elegir}
                texto="El reporte puede mostrar cuánta plata tenés en cada parte, o solo los porcentajes. Si lo vas a mandar a alguien, elegí qué querés que vea."
              />
            </div>
          </div>
        </div>,
        document.body,
      )}

      {paso === 'vista' && datos && typeof document !== 'undefined' && createPortal(
        // La barra no es `sticky`: el portal es una columna (barra fija arriba y
        // el papel scrollea abajo), así no hay nada pegado con un alto a mano.
        <div className="reporte-portal fixed inset-0 z-[60] flex flex-col bg-black/80" role="dialog" aria-modal="true" aria-label="Vista previa del reporte">
          <style>{CSS_IMPRESION}</style>
          <div className="reporte-no-print shrink-0 bg-bg-1 border-b border-line">
            <div className="max-w-[800px] mx-auto flex items-center justify-between gap-2 px-3 py-2.5">
              <button
                type="button"
                onClick={() => armar(!mostrarMontos)}
                className="inline-flex items-center gap-1 text-[12px] text-data-violet hover:text-data-violet/80 transition-colors"
              >
                {mostrarMontos ? <EyeOff size={12} strokeWidth={1.75} /> : <Eye size={12} strokeWidth={1.75} />}
                {mostrarMontos ? 'Ocultar montos' : 'Mostrar montos'}
              </button>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={descargar}
                  className="inline-flex items-center gap-1.5 text-xs bg-data-violet/10 hover:bg-data-violet/15 text-data-violet border border-data-violet/30 px-3 py-1.5 rounded-sm transition-colors"
                >
                  <Download size={12} strokeWidth={1.75} />
                  Descargar PDF
                </button>
                <button onClick={cerrar} className="text-ink-3 hover:text-ink-0 transition-colors p-1" aria-label="Cerrar">
                  <X size={16} strokeWidth={1.75} />
                </button>
              </div>
            </div>
          </div>
          <div className="reporte-cuerpo flex-1 overflow-y-auto p-3 sm:p-6">
            <ReporteCartera datos={datos} />
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}
