// MoverDeBrokerModal — el formulario de «Mover a otro broker» (contenedor).
// ═══════════════════════════════════════════════════════════════════════════
// Los títulos pasan de un broker tuyo a otro con su costo y su fecha de compra
// originales. No es una venta. El servidor arma todo:
//   1. POST /api/positions/traspaso/vista-previa — LEE y no escribe: qué lotes se
//      mueven (primero los más viejos), cuánto valían ese día y cuánto costaron.
//      Se pide 400 ms después del último cambio válido y cancela el anterior.
//   2. POST /api/positions/traspaso — confirma con lo MISMO que se vio: el mismo
//      cuerpo, más la `firma` y la `valuacion` de la vista previa. Si la cartera
//      cambió en el medio, el servidor contesta 409 y se vuelve a pedir la vista.
//
// Una sola pieza para la compu y el celular (Modal ya es un sheet en el
// teléfono). Lo que se dibuja vive en VistaPreviaDelPase / SelectorDeDestino,
// que son puros; acá sólo hay formulario y pedidos.
//
// La fecha NO viene puesta: la elige la persona (botón «Hoy» al lado). Con la
// fecha del broker, si después importa su archivo, el servidor reconoce el pase
// y no cuenta los títulos dos veces.

import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import Modal from '../Modal'
import DateInput from '../DateInput'
import VistaPreviaDelPase, { SelectorDeDestino, CREAR_BROKER } from './VistaPreviaDelPase'
import { api, errorMessage } from '../../utils/api'
import { useEnVuelo } from '../../hooks/useEnVuelo'
import { usePrivacy } from '../../contexts/PrivacyContext'
import { hoyISO } from '../../utils/fecha'
import { numACampo } from '../../utils/format'
import { fciLabel } from '../../utils/valuation'
import { etiquetaDeVenta } from '../../utils/opcionesDeVenta'
import {
  destinosPosibles, cuerpoDeMover, admiteGastoEnDosMonedas, faltaPrecio, fechaDelPase,
  nombreDeMoneda, cantidadDeTitulos,
} from '../../utils/moverDeBroker'

const CAMPO = 'w-full bg-bg-2 border border-line rounded-lg px-3 py-2 text-base sm:text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2'
const BOTON_CHICO = 'flex-shrink-0 px-3 py-2 text-xs font-medium rounded-lg border border-line bg-bg-2 text-ink-1 hover:bg-bg-3 transition-colors'

export default function MoverDeBrokerModal({ opcion, brokers, onClose, onHecho, onCrearBroker }) {
  const { hidden } = usePrivacy()
  const enVuelo = useEnVuelo()
  const destinos = useMemo(() => destinosPosibles(opcion, brokers), [opcion, brokers])
  const dosMonedas = admiteGastoEnDosMonedas(opcion?.cuenta || opcion?.broker, brokers)
  const [form, setForm] = useState(() => ({
    destino: destinos.length === 1 ? destinos[0].name : '',
    fecha: '',
    cantidad: '',
    precioManual: '',
    gastoMonto: '',
    gastoMoneda: dosMonedas ? 'ARS' : 'USD',
  }))
  const [gastoAbierto, setGastoAbierto] = useState(false)
  // La última vista previa que llegó, con el cuerpo que la pidió: sólo vale
  // mientras el formulario siga diciendo lo mismo (`clave`).
  const [vista, setVista] = useState(null)
  const [pidiendo, setPidiendo] = useState(false)
  // El error de la vista previa y el «sin precio» también dicen de QUÉ pedido
  // son: el error, de esa combinación (`clave`); el «sin precio», de esa fecha.
  // Antes el error de la combinación anterior quedaba en rojo durante la espera
  // de 400 ms, o para siempre si se borraba la fecha (revisión E12).
  const [errorVista, setErrorVista] = useState(null)   // { clave, texto }
  const [errorGuardar, setErrorGuardar] = useState(null)
  const [sinPrecio, setSinPrecio] = useState(null)     // { ...detail, fecha }
  const [disponible, setDisponible] = useState(null)
  const [refresco, setRefresco] = useState(0)

  const cambiar = (campo, valor) => {
    setErrorGuardar(null)
    setForm((f) => {
      const nuevo = { ...f, [campo]: valor }
      // Un precio escrito es el de ESA fecha: con otra fecha no se reusa (el
      // rótulo ya decía la fecha nueva y el pedido viajaba con el precio viejo).
      if (campo === 'fecha' && valor !== f.fecha) nuevo.precioManual = ''
      return nuevo
    })
  }

  const cuerpo = useMemo(() => cuerpoDeMover(form, opcion), [form, opcion])
  const clave = cuerpo.body ? JSON.stringify(cuerpo.body) : null
  const vigente = vista && vista.clave === clave ? vista : null

  useEffect(() => {
    if (!clave) { setPidiendo(false); return undefined }
    const control = new AbortController()
    const espera = setTimeout(() => pedirVistaPrevia(JSON.parse(clave), control.signal), 400)
    return () => { clearTimeout(espera); control.abort() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clave, refresco])

  async function pedirVistaPrevia(body, signal) {
    setPidiendo(true)
    setErrorVista(null)
    try {
      const plan = await api.post('/positions/traspaso/vista-previa', body, { signal })
      if (signal.aborted) return
      setVista({ clave: JSON.stringify(body), body, plan })
      setSinPrecio(null)
      if (plan?.cantidad_disponible != null) setDisponible({ fecha: body.fecha, valor: plan.cantidad_disponible })
    } catch (e) {
      if (signal.aborted || e?.name === 'AbortError') return
      setVista(null)
      const falta = faltaPrecio(e)
      if (falta) {
        setSinPrecio({ ...falta, fecha: body.fecha })
        return
      }
      setErrorVista({
        clave: JSON.stringify(body),
        texto: errorMessage(e) || 'No pudimos armar la vista previa. Probá de nuevo en un rato.',
      })
    } finally {
      if (!signal.aborted) setPidiendo(false)
    }
  }

  async function confirmarPase() {
    if (!vigente?.plan) return
    setErrorGuardar(null)
    try {
      const res = await api.post('/positions/traspaso', {
        ...vigente.body, firma: vigente.plan.firma, valuacion: vigente.plan.valuacion,
      })
      onHecho?.(res, vigente)
    } catch (e) {
      setErrorGuardar(errorMessage(e) || 'No pudimos guardar el pase. No se cambió nada en tu cartera.')
      // «Tu cartera cambió» / «el dólar de ese día cambió»: se vuelve a pedir la
      // vista previa para que la persona revise los números nuevos.
      if (e?.status === 409) {
        setVista(null)
        setRefresco((n) => n + 1)
      }
    }
  }

  function elegirDestino(valor) {
    if (valor === CREAR_BROKER) {
      onClose?.()
      onCrearBroker?.()
      return
    }
    cambiar('destino', valor)
  }

  function todo() {
    const d = disponible && disponible.fecha === form.fecha ? disponible.valor : null
    cambiar('cantidad', d != null ? numACampo(d) : '')
  }

  if (!opcion) return null
  const asset = opcion.asset
  const nombre = fciLabel(asset)
  const A = opcion.cuenta || opcion.broker
  const B = form.destino || ''
  const plan = vigente?.plan || null
  const disp = disponible && disponible.fecha === form.fecha ? disponible.valor : null
  const faltaElPrecio = sinPrecio && sinPrecio.fecha === form.fecha ? sinPrecio : null
  const conPrecioAMano = !!faltaElPrecio || !!String(form.precioManual || '').trim()
  const monedaPrecio = faltaElPrecio?.moneda_precio || plan?.valuacion?.moneda_precio || (opcion.moneda === 'ARS' ? 'ARS' : 'USD')
  // El error del formulario (una cantidad mal escrita) sólo cuando ya hay destino
  // y fecha: antes, la ayuda de cada campo alcanza.
  const errorForm = cuerpo.error && form.destino && form.fecha ? cuerpo.error : null
  const errorDeEsteForm = errorVista && errorVista.clave === clave ? errorVista.texto : null
  const error = errorGuardar || errorForm || (vigente ? null : errorDeEsteForm)
  const cantidadBoton = plan?.cantidad != null ? `${cantidadDeTitulos(plan.cantidad)} ` : ''

  return (
    <Modal title={`Mover ${nombre} a otro broker`} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-[13px] text-ink-3 -mt-1">Desde {etiquetaDeVenta(opcion)}</p>

        <div>
          <label className="block text-xs text-ink-3 mb-1">¿A qué broker?</label>
          <SelectorDeDestino destinos={destinos} valor={form.destino} onCambio={elegirDestino} />
        </div>

        <div>
          <label className="block text-xs text-ink-3 mb-1">¿Qué día llegaron a {B || 'ese broker'}?</label>
          <div className="flex items-center gap-2">
            <div className="flex-1 min-w-0">
              <DateInput value={form.fecha} max={hoyISO()} onChange={(v) => cambiar('fecha', v || '')} />
            </div>
            <button type="button" onClick={() => cambiar('fecha', hoyISO())} className={BOTON_CHICO}>Hoy</button>
          </div>
          <p className="text-[12px] text-ink-3 mt-1 leading-relaxed">
            Usá la fecha que figura en tu broker. Si después importás su archivo, Rendi la usa para no contar los títulos dos veces.
          </p>
        </div>

        <div>
          <label className="block text-xs text-ink-3 mb-1">Cantidad</label>
          <div className="flex items-center gap-2">
            <input
              type="text"
              inputMode="decimal"
              value={form.cantidad}
              onChange={(e) => cambiar('cantidad', e.target.value)}
              placeholder={disp != null ? `Todo (${cantidadDeTitulos(disp)})` : 'Todo'}
              className={`${CAMPO} tabular`}
            />
            <button type="button" onClick={todo} className={BOTON_CHICO}>Todo</button>
          </div>
          {disp != null && (
            <p className="text-[12px] text-ink-3 mt-1 tabular">Tenés {cantidadDeTitulos(disp)} que ya estaban en {A} ese día</p>
          )}
        </div>

        {conPrecioAMano && (
          <div>
            <label className="block text-xs text-ink-3 mb-1">
              Precio de {nombre} el {fechaDelPase(form.fecha) || 'ese día'} (en {nombreDeMoneda(monedaPrecio)})
            </label>
            <input
              type="text"
              inputMode="decimal"
              value={form.precioManual}
              onChange={(e) => cambiar('precioManual', e.target.value)}
              className={`${CAMPO} tabular`}
            />
            {faltaElPrecio?.mensaje && (
              <p className="text-[12px] text-rendi-warn mt-1 leading-relaxed">{faltaElPrecio.mensaje}</p>
            )}
          </div>
        )}

        <div>
          <button
            type="button"
            onClick={() => setGastoAbierto((v) => !v)}
            aria-expanded={gastoAbierto}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-2 hover:text-ink-0 transition-colors"
          >
            {gastoAbierto ? <ChevronUp size={13} aria-hidden="true" /> : <ChevronDown size={13} aria-hidden="true" />}
            Gasto del trámite (opcional)
          </button>
          {gastoAbierto && (
            <div className="mt-2">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.gastoMonto}
                  onChange={(e) => cambiar('gastoMonto', e.target.value)}
                  placeholder="Monto"
                  aria-label="Monto del gasto del trámite"
                  className={`${CAMPO} tabular`}
                />
                {dosMonedas && (
                  <select
                    value={form.gastoMoneda}
                    onChange={(e) => cambiar('gastoMoneda', e.target.value)}
                    aria-label="Moneda del gasto"
                    className="flex-shrink-0 bg-bg-2 border border-line rounded-lg px-2 py-2 text-base sm:text-sm text-ink-0 focus:outline-none focus:border-ink-2"
                  >
                    <option value="ARS">Pesos</option>
                    <option value="USD">Dólares</option>
                  </select>
                )}
              </div>
              <p className="text-[12px] text-ink-3 mt-1">Sale de la caja de {A}.</p>
            </div>
          )}
        </div>

        <VistaPreviaDelPase plan={plan} hidden={hidden} error={error} opcion={opcion} />
        {pidiendo && !plan && !error && (
          <p className="text-[12px] text-ink-3">Calculando cuánto valían…</p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-ink-3 hover:text-ink-0 px-3 py-2 transition-colors"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={() => enVuelo.correr(confirmarPase)}
            disabled={!plan || enVuelo.activo()}
            className="inline-flex items-center gap-1.5 text-xs font-semibold bg-rendi-accent text-white hover:bg-rendi-accent/90 px-4 py-2 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {enVuelo.activo() ? 'Moviendo…' : `Mover ${cantidadBoton}${nombre}`}
          </button>
        </div>
      </div>
    </Modal>
  )
}
