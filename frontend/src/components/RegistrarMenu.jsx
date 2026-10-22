// RegistrarMenu — el botón violeta «Registrar» del menú lateral.
// ═══════════════════════════════════════════════════════════════════════════
// Una sola puerta para anotar a mano, visible desde cualquier pantalla: antes
// los botones (Registrar compra · Registrar venta · Cash) vivían en el
// encabezado de la Cartera y había que ir hasta ahí para encontrarlos. Es el
// gemelo del "+" del celular (MobileTabBar): al tocarlo ofrece qué registrar y
// cada opción va a la Cartera con el formulario ya abierto.
//
// QUÉ se ofrece, en qué orden y a dónde lleva cada cosa sale de
// utils/registrar.js — la misma lista que leen las dos Carteras.
//
// El menú se dibuja en un PORTAL con position:fixed (igual que ActionMenu): el
// menú lateral y la franja fija de arriba del contenido comparten z-index, y
// adentro del <aside> quedaría a merced de cuál se pinta después.
//
// Dos anchos, como el menú lateral: desplegado dice «Registrar»; plegado
// (56 px) es el cuadrado violeta con el "+".
//
// Abajo de todo, en una franja propia (otro fondo, su título, ícono violeta de
// borde punteado), «Importar historial»: no es una carga a mano sino subir el
// archivo del broker, y antes era una fila suelta del menú lateral (pedido de
// Nico, 2026-10-19). Llega por `importar` desde la lista compartida del menú
// (utils/navegacion.js): quien no tiene Importar no lo ve acá tampoco. El "+"
// del celular (MobileTabBar) tiene la misma franja, con el mismo texto
// (IMPORTAR_HISTORIAL de utils/registrar.js).

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { ACCIONES_REGISTRAR, IMPORTAR_HISTORIAL, direccionDeRegistrar } from '../utils/registrar'
import { track } from '../utils/track'

const MENU_W = 272
// Alto aproximado del menú abierto: sólo para que no se salga por abajo en una
// ventana muy baja.
const MENU_H = 400

// El color del ícono es la intención de cada renglón, con los mismos tonos que
// ya usan el selector de efectivo (CashMenuModal) y el "+" del celular.
const TONO = {
  pos:    'bg-rendi-pos/10 text-rendi-pos',
  accent: 'bg-data-violet/10 text-data-violet',
  warn:   'bg-data-amber/10 text-data-amber',
  info:   'bg-data-cyan/10 text-data-cyan',
}

export default function RegistrarMenu({ collapsed = false, importar = null }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState(null)   // coords fixed {top, left} del menú
  const btnRef = useRef(null)
  const menuRef = useRef(null)
  const navigate = useNavigate()

  // A la derecha del menú lateral, alineado con el borde de arriba del botón.
  // El costado sale del ancho FINAL del menú lateral (--sidebar-w, que publica
  // Sidebar) y no de dónde está el botón ahora: al plegar o desplegar, el ancho
  // se anima 200 ms y el botón viaja; medido ahí, el menú quedaba encima.
  const ubicar = () => {
    const b = btnRef.current?.getBoundingClientRect()
    if (!b) return
    const top = Math.max(8, Math.min(b.top, window.innerHeight - MENU_H - 8))
    const anchoLateral = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-w'))
    const left = Number.isFinite(anchoLateral) ? anchoLateral + 8 : b.right + 12
    setPos({ top: Math.round(top), left: Math.round(left) })
  }

  useLayoutEffect(() => { if (open) ubicar() }, [open, collapsed])

  // Al abrir, el foco va a la primera opción (teclado).
  useEffect(() => {
    if (open && pos) menuRef.current?.querySelector('[role="menuitem"]')?.focus()
  }, [open, pos])

  // Cerrar con click afuera, Escape, scroll o al cambiar el tamaño de la ventana.
  useEffect(() => {
    if (!open) return
    function onDown(e) {
      if (btnRef.current?.contains(e.target)) return
      if (menuRef.current?.contains(e.target)) return
      setOpen(false)
    }
    function onKey(e) {
      if (e.key !== 'Escape') return
      setOpen(false)
      btnRef.current?.focus()
    }
    function cerrar() { setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', cerrar, true)
    window.addEventListener('resize', cerrar)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', cerrar, true)
      window.removeEventListener('resize', cerrar)
    }
  }, [open])

  function alternar() {
    if (!open) track('registrar_abierto')
    setOpen(o => !o)
  }

  function elegir(accion) {
    track('registrar_elegido', { code: accion.id })
    setOpen(false)
    navigate(direccionDeRegistrar(accion.id))
  }

  function irAImportar() {
    track('registrar_elegido', { code: 'importar' })
    setOpen(false)
    navigate(importar.to)
  }

  // Flechas arriba/abajo entre opciones.
  function moverFoco(e) {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
    e.preventDefault()
    const items = [...(menuRef.current?.querySelectorAll('[role="menuitem"]') || [])]
    const i = items.indexOf(document.activeElement)
    const sig = e.key === 'ArrowDown' ? (i + 1) % items.length : (i - 1 + items.length) % items.length
    items[sig]?.focus()
  }

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={alternar}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={collapsed ? 'Registrar' : undefined}
        title={collapsed ? 'Registrar' : undefined}
        className={`inline-flex items-center justify-center gap-2 bg-data-violet hover:bg-data-violet/90 text-white font-medium rounded-lg transition-colors press ${
          collapsed ? 'w-9 h-9' : 'w-full h-10 text-[14px]'
        }`}
      >
        <Plus size={collapsed ? 17 : 16} strokeWidth={2.25} aria-hidden="true" />
        {!collapsed && <span>Registrar</span>}
      </button>

      {open && pos && createPortal(
        <div
          ref={menuRef}
          role="menu"
          aria-label="¿Qué querés registrar?"
          onKeyDown={moverFoco}
          className="fixed z-[200] p-1.5 bg-bg-raised border border-line rounded-xl"
          style={{ top: pos.top, left: pos.left, width: MENU_W, boxShadow: 'var(--shadow-raised)' }}
        >
          <p className="px-2.5 pt-1.5 pb-1 text-[12px] text-ink-3">¿Qué querés registrar?</p>
          {ACCIONES_REGISTRAR.map((a, i) => {
            const Icon = a.icon
            const cambiaDeGrupo = i > 0 && ACCIONES_REGISTRAR[i - 1].grupo !== a.grupo
            return (
              <div key={a.id}>
                {cambiaDeGrupo && <div className="my-1 mx-2 border-t border-line/60" aria-hidden="true" />}
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => elegir(a)}
                  className="w-full flex items-center gap-3 px-2.5 py-2 rounded-lg text-left transition-colors hover:bg-bg-2 focus:bg-bg-2 focus:outline-none"
                >
                  <span className={`flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${TONO[a.tone] || TONO.accent}`}>
                    <Icon size={16} strokeWidth={2} aria-hidden="true" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[13.5px] font-medium text-ink-0">{a.label}</span>
                    <span className="block text-[12px] text-ink-3 leading-snug">{a.sub}</span>
                  </span>
                </button>
              </div>
            )
          })}
          {importar && (() => {
            const ImportIcon = importar.icon
            return (
              <div className="mt-1.5 -mx-1.5 -mb-1.5 px-1.5 pt-1.5 pb-1.5 border-t border-line bg-bg-1 rounded-b-xl">
                <p className="px-2.5 pt-1 pb-1 text-[12px] text-ink-3">{IMPORTAR_HISTORIAL.pregunta}</p>
                <button
                  type="button"
                  role="menuitem"
                  onClick={irAImportar}
                  className="w-full flex items-center gap-3 px-2.5 py-2 rounded-lg text-left transition-colors hover:bg-bg-2 focus:bg-bg-2 focus:outline-none"
                >
                  <span className="flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center border border-dashed border-data-violet/60 text-data-violet">
                    <ImportIcon size={16} strokeWidth={2} aria-hidden="true" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[13.5px] font-medium text-ink-0">{IMPORTAR_HISTORIAL.label}</span>
                    <span className="block text-[12px] text-ink-3 leading-snug">{IMPORTAR_HISTORIAL.sub}</span>
                  </span>
                </button>
              </div>
            )
          })()}
        </div>,
        document.body,
      )}
    </>
  )
}
