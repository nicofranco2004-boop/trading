// ResumenMercado — /resumen: el resumen del mercado completo, adentro de Rendi.
// ═══════════════════════════════════════════════════════════════════════════
// Es adonde lleva la notificación del resumen (market_brief.PUSH_URL). La
// notificación sólo entra el titular; acá está todo lo que lleva el mail.
//
// Muestra UNO solo, el último que se mandó (pedido de Nico, 2026-10-16: «se
// tiene que ir limpiando cada vez que llega uno nuevo»). No es un archivo: el
// de hoy reemplaza al de ayer. Si el que hay no es de hoy, se dice de qué día
// es — un resumen de mercado sin fecha se lee como si fuera de hoy.
//
// El cuerpo lo dibuja ResumenMercadoCuerpo, el mismo que el ejemplo de /alertas.
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import ResumenMercadoCuerpo from '../components/alerts/ResumenMercadoCuerpo'
import { api } from '../utils/api'

// La fecha de hoy en Argentina, como la sella el servidor (`_today_art`).
// Con el reloj del teléfono a secas, de 21:00 a medianoche el resumen de hoy
// figuraría como «de ayer» para quien esté fuera de la zona.
export function hoyArgentina(ahora = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Argentina/Buenos_Aires',
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(ahora)
}

// «viernes 16 de octubre». Al mediodía UTC para que ninguna zona horaria lo
// corra de día.
export function fechaLarga(iso) {
  if (!iso) return ''
  const d = new Date(`${iso}T12:00:00Z`)
  if (Number.isNaN(d.getTime())) return ''
  // El navegador escribe «viernes, 16 de octubre»: la coma sobra en una frase.
  return d.toLocaleDateString('es-AR', {
    weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC',
  }).replace(',', '')
}

export function subtituloDelResumen(resumen, hoy = hoyArgentina()) {
  if (!resumen) return 'Lo que pasó en el mercado desde que cerró ayer.'
  if (resumen.date === hoy) return `El de hoy, ${fechaLarga(resumen.date)}.`
  return `El último que te llegó, del ${fechaLarga(resumen.date)}. ` +
    'Cuando llegue uno nuevo, reemplaza a este.'
}

export default function ResumenMercado() {
  const [estado, setEstado] = useState({ cargando: true, error: false, resumen: null })

  function cargar() {
    setEstado(e => ({ ...e, cargando: true, error: false }))
    return api.get('/market-brief/ultimo')
      .then(d => setEstado({ cargando: false, error: false, resumen: (d && d.resumen) || null }))
      // Sin dato no se dice «no tenés ninguno»: sería mentira si el servidor
      // sólo tardó. Se avisa y se ofrece reintentar.
      .catch(() => setEstado({ cargando: false, error: true, resumen: null }))
  }

  useEffect(() => { cargar() }, [])

  const { cargando, error, resumen } = estado

  return (
    <div className="page-shell">
      <PageHeader
        title="Resumen del mercado"
        subtitle={cargando || error ? undefined : subtituloDelResumen(resumen)}
      />

      {cargando && (
        <Panel className="max-w-2xl">
          <div className="text-sm text-ink-3">Cargando el resumen…</div>
        </Panel>
      )}

      {!cargando && error && (
        <Panel className="max-w-2xl">
          <div className="text-sm text-ink-2">
            No pudimos traer el resumen.{' '}
            <button type="button" onClick={cargar} className="text-rendi-accent hover:underline">
              Reintentar
            </button>
          </div>
        </Panel>
      )}

      {!cargando && !error && !resumen && (
        <Panel className="max-w-2xl">
          <div className="text-sm text-ink-1">Todavía no te llegó ningún resumen.</div>
          <div className="text-xs text-ink-3 mt-1.5 leading-relaxed">
            Sale los días hábiles cuando abre el mercado argentino, a las 11. Se
            prende en <Link to="/alertas" className="text-rendi-accent hover:underline">Alertas</Link>.
          </div>
        </Panel>
      )}

      {!cargando && !error && resumen && (
        <Panel className="max-w-2xl" padding="lg">
          <ResumenMercadoCuerpo resumen={resumen} />
          <p className="text-xs text-ink-3 leading-relaxed mt-8 pt-4 border-t border-line/40">
            Lo escribimos a partir de las noticias del día; no es una recomendación
            de inversión. Te llega también por mail. Podés apagarlo en{' '}
            <Link to="/alertas" className="text-rendi-accent hover:underline">Alertas</Link>.
          </p>
        </Panel>
      )}
    </div>
  )
}
