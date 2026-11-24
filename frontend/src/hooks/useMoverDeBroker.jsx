// useMoverDeBroker — «Mover a otro broker» desde la Cartera, para las DOS anchuras.
// ═══════════════════════════════════════════════════════════════════════════
// Lo usan Positions.jsx (compu) y PositionsMobile.jsx (celular): el flujo es UNO
// solo y cada pantalla nada más lo enchufa. Escrito dos veces se separaría como
// se separaron los menús de la fila (ver utils/positionActions.js).
//
//   const mover = useMoverDeBroker({ brokers, source: 'desktop', onHecho: loadAll, onCrearBroker })
//   buildPositionActions(p, { …, onMove: mover.abrir })    ← null = la opción no se muestra
//   {mover.host}                                             ← el selector y el formulario
//
// Qué hace `abrir(p)`, espejo de `openSell`:
//   1. Las opciones son las de `opcionesDeVenta` sobre los LOTES DE LA FILA tocada
//      (`p._lots || [p]`), no todos los del activo: una por (cuenta, activo, moneda).
//   2. Varias (la fila junta pesos y dólares) → «¿Cuáles querés mover?».
//   3. Una → si no hay a dónde pasarla (otro broker de la misma familia), un aviso
//      con «Crear broker» en vez de un formulario vacío; si hay, el formulario.
//
// `habilitado` sale de GET /api/positions/traspasos: el servidor tiene un
// interruptor para frenar pases nuevos. Si dice que no —o si el pedido falla—
// la opción no aparece en el menú.

import { useEffect, useState } from 'react'
import { ArrowRight } from 'lucide-react'
import Modal from '../components/Modal'
import MoverDeBrokerModal from '../components/cartera/MoverDeBrokerModal'
import { useToast } from '../components/Toast'
import { EtiquetaMoneda } from '../components/EtiquetaFila'
import { api, errorMessage } from '../utils/api'
import { usePrivacy } from '../contexts/PrivacyContext'
import { taparMontos } from '../utils/ocultarSaldos'
import { track } from '../utils/track'
import { fciLabel } from '../utils/valuation'
import { opcionesDeVenta, etiquetaDeVenta } from '../utils/opcionesDeVenta'
import { destinosPosibles, cantidadDeTitulos } from '../utils/moverDeBroker'

export function useMoverDeBroker({ brokers, source = 'desktop', onHecho, onCrearBroker } = {}) {
  const toast = useToast()
  // Los textos del servidor del deshacer (el «Listo» y los errores de C.8, que
  // pueden decir «({n} a {costo})») se tapan con el ojito prendido.
  const { hidden } = usePrivacy()
  const delServidor = (t) => (hidden ? taparMontos(t) : t)
  const [habilitado, setHabilitado] = useState(false)
  const [eleccion, setEleccion] = useState(null)
  const [opcion, setOpcion] = useState(null)

  useEffect(() => {
    let vivo = true
    api.get('/positions/traspasos')
      .then((r) => { if (vivo) setHabilitado(r?.habilitado === true) })
      .catch(() => { if (vivo) setHabilitado(false) })
    return () => { vivo = false }
  }, [])

  function crearBroker() {
    setEleccion(null)
    setOpcion(null)
    onCrearBroker?.()
    toast.push('Creá el broker y volvé a «Mover a otro broker».', { type: 'info', duration: 8000 })
  }

  function abrirOpcion(o) {
    if (!destinosPosibles(o, brokers).length) {
      toast.push(`No tenés otro broker donde pasar estos ${fciLabel(o.asset)}. Creá uno en Brokers y volvé a intentar.`, {
        type: 'info',
        duration: 10000,
        ...(onCrearBroker ? { actionLabel: 'Crear broker', onAction: crearBroker } : {}),
      })
      return
    }
    setOpcion(o)
  }

  function abrir(p) {
    if (!p || p.is_cash) return
    track('position_move_started', { source })
    const opciones = opcionesDeVenta(p._lots || [p], brokers)
    if (opciones.length > 1) {
      setEleccion(opciones)
      return
    }
    if (opciones.length) abrirOpcion(opciones[0])
  }

  async function deshacer(traspasoId) {
    try {
      const res = await api.post(`/positions/traspaso/${encodeURIComponent(traspasoId)}/deshacer`)
      track('position_move_undone', { source })
      await onHecho?.()
      toast.push(delServidor(res?.mensaje) || 'Listo: deshicimos el pase.', { type: 'success' })
    } catch (e) {
      toast.push(delServidor(errorMessage(e)) || 'No se pudo deshacer el pase.', { type: 'error', duration: 8000 })
    }
  }

  function hecho(res, vista) {
    setOpcion(null)
    track('position_moved', { source })
    onHecho?.()
    const plan = vista?.plan || {}
    const mensaje = delServidor(res?.mensaje)
      || `Listo: pasaste ${cantidadDeTitulos(plan.cantidad)} ${plan.asset || ''} de ${plan.origen?.cuenta || ''} a ${plan.destino?.cuenta || ''}.`
    toast.push(mensaje, {
      type: 'success',
      duration: 12000,
      ...(res?.traspaso_id ? { actionLabel: 'Deshacer', onAction: () => deshacer(res.traspaso_id) } : {}),
    })
  }

  const host = (
    <>
      {eleccion && (
        <Modal title="¿Cuáles querés mover?" onClose={() => setEleccion(null)}>
          <div className="space-y-2">
            <p className="text-xs text-ink-3 leading-relaxed">
              Tenés este activo comprado en pesos y en dólares. Elegí cuál pasás: se mueven primero las compras más viejas de esa moneda.
            </p>
            <ul className="space-y-1.5">
              {eleccion.map((o) => (
                <li key={o.key}>
                  <button
                    type="button"
                    onClick={() => { setEleccion(null); abrirOpcion(o) }}
                    className="w-full flex items-center gap-3 p-3 border border-line rounded-lg text-left hover:bg-bg-2 active:bg-bg-2 transition-colors"
                  >
                    <span className="flex-1 min-w-0">
                      <span className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-semibold text-ink-0">{fciLabel(o.asset)}</span>
                        <span className="text-xs text-ink-3">{etiquetaDeVenta(o)}</span>
                        <EtiquetaMoneda moneda={o.moneda} className="text-[11.5px]" />
                      </span>
                      <span className="block text-xs text-ink-3 tabular mt-0.5">
                        {cantidadDeTitulos(o.qty)} unidades{o.lots.length > 1 ? ` · ${o.lots.length} compras` : ''}
                      </span>
                    </span>
                    <ArrowRight size={15} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </Modal>
      )}
      {opcion && (
        <MoverDeBrokerModal
          opcion={opcion}
          brokers={brokers}
          onClose={() => setOpcion(null)}
          onHecho={hecho}
          onCrearBroker={crearBroker}
        />
      )}
    </>
  )

  return { habilitado, abrir: habilitado ? abrir : null, host }
}
