// CrearAlerta — la pestaña «Crear alerta» de /alertas.
// ═══════════════════════════════════════════════════════════════════════════
// Las dos cosas que Rendi te puede avisar, una al lado de la otra, para elegir:
//   • Resumen del mercado: un mail por día hábil. Se PRENDE, no se arma.
//   • Aviso de precio: abre el formulario (AlertaForm), que adentro elige entre
//     «llega a un precio» y «se mueve un %».
// Lo que ya armaste vive en la otra pestaña (MisAlertas).
//
// Las dos tarjetas llevan las marcas del tutorial de novedades
// (components/tour/pasos.js): el tutorial abre esta pestaña con ?tab=crear y
// resalta cada una. Van en las tarjetas, que están SIEMPRE en pantalla en esta
// pestaña, prendido o no el resumen.
//
// Sistema visual: generación nueva — Panel como superficie (rounded-xl),
// rótulos sans sentence-case, números con `tabular`.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Sunrise, Target, Check } from 'lucide-react'
import Panel from '../Panel'
import Pill from '../Pill'
import ResumenMercadoCuerpo from './ResumenMercadoCuerpo'

// El ejemplo es FIJO y el mismo para todos, a propósito (decisión de Nico, sep
// 2026): el mail real ya llega a la casilla, ocupaba media pantalla y gastaba una
// llamada al modelo por clic para enseñar un formato que no cambia. Escrito a
// mano sobre resúmenes reales, con datos inventados y dichos.
const EJEMPLO = {
  titular: 'El petróleo sube y presiona a las tasas',
  mercado: [
    'El crudo subió 4% por tensiones en Medio Oriente. Cuando la energía se ' +
    'encarece, presiona la inflación de todo el mundo. Por eso el mercado ' +
    'espera que los bancos centrales tarden más en bajar las tasas.',
    'En Argentina, el riesgo país cerró en 490 puntos. Es lo que el mercado ' +
    'cobra de más por prestarle al país, y subió por la caída de los bonos.',
  ],
  tu_cartera: [
    'YPFD y PAMP acompañan la suba del petróleo. GGAL cae con los bonos, ' +
    'como suele pasar con los bancos cuando sube el riesgo país.',
  ],
  agenda: [
    { ticker: 'AAPL', label: 'Reporte trimestral' },
    { ticker: 'AL30', label: 'Cupón + amortización' },
  ],
}

const BOTON = 'inline-flex items-center justify-center h-11 px-5 rounded-lg bg-data-violet text-white text-sm font-semibold hover:bg-rendi-violet-hover disabled:opacity-50 transition-colors'

export default function CrearAlerta({ resumen, onCrearAviso, alTope, alertsMax, puedeMovimiento }) {
  const [verEjemplo, setVerEjemplo] = useState(false)

  return (
    <div className="space-y-4">
      <p className="text-[15px] text-ink-1">¿Qué querés que te avisemos?</p>

      <div className="grid gap-4 sm:grid-cols-2">
        {/* Resumen del mercado */}
        <Panel padding="lg" className="flex flex-col gap-4" data-tour="resumen-mercado">
          <div className="w-12 h-12 rounded-xl bg-bg-2 flex items-center justify-center text-rendi-warn" aria-hidden="true">
            <Sunrise size={24} strokeWidth={1.75} />
          </div>
          <div className="flex-1 space-y-1.5">
            <h2 className="text-lg font-semibold text-ink-0">Resumen del mercado</h2>
            <p className="text-sm text-ink-2 leading-relaxed">
              Un mail cada día hábil a las 11:00 con lo que pasó en el mercado y lo que toca a tus activos.
            </p>
          </div>
          {resumen.error ? (
            <p className="text-sm text-ink-2">
              No pudimos leer tu configuración.{' '}
              <button type="button" onClick={resumen.cargar} className="text-data-violet hover:underline">Reintentar</button>
            </p>
          ) : (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              {resumen.prendido ? (
                <span className="inline-flex items-center gap-1.5 h-11 text-sm text-rendi-pos">
                  <Check size={16} strokeWidth={2.25} /> Ya te llega
                </span>
              ) : (
                <button type="button" className={BOTON} disabled={!resumen.cargado}
                  onClick={() => resumen.cambiar(true)}>
                  Activar
                </button>
              )}
              <button type="button" onClick={() => setVerEjemplo(v => !v)} aria-expanded={verEjemplo}
                className="text-sm text-data-violet hover:underline">
                {verEjemplo ? 'Ocultar el ejemplo' : 'Ver un ejemplo'}
              </button>
              {resumen.prendido && (
                <Link to="/resumen" className="text-sm text-data-violet hover:underline">Leer el de hoy</Link>
              )}
            </div>
          )}
          {verEjemplo && (
            <div className="border-t border-line pt-3 space-y-3">
              <p className="text-xs text-ink-2">
                Un ejemplo con datos inventados, para que veas el formato. El tuyo se arma con las noticias del día y tus activos.
              </p>
              <ResumenMercadoCuerpo resumen={EJEMPLO} compacto />
            </div>
          )}
        </Panel>

        {/* Aviso de precio */}
        <Panel padding="lg" className="flex flex-col gap-4" data-tour="nueva-alerta">
          <div className="w-12 h-12 rounded-xl bg-bg-2 flex items-center justify-center text-data-blue" aria-hidden="true">
            <Target size={24} strokeWidth={1.75} />
          </div>
          <div className="flex-1 space-y-1.5">
            <h2 className="text-lg font-semibold text-ink-0">Aviso de precio</h2>
            <p className="text-sm text-ink-2 leading-relaxed">
              Te avisamos cuando un activo llega al precio que elegís, o cuando sube o cae más de un %.
              {!puedeMovimiento && <> <Pill tone="info">El % es de Plus</Pill></>}
            </p>
          </div>
          {alTope ? (
            <p className="text-sm text-ink-1">
              Llegaste al máximo de tu plan (<span className="tabular">{alertsMax}</span>).{' '}
              <Link to="/config?tab=planes" className="text-data-violet font-medium hover:underline">Ver planes</Link>
            </p>
          ) : (
            <div>
              <button type="button" className={BOTON} onClick={onCrearAviso}>
                Crear aviso
              </button>
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}
