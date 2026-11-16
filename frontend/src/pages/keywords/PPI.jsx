// /brokers/ppi — "cómo descargar mis movimientos de PPI"
// ════════════════════════════════════════════════════════════════════════════
// Intent: alguien con cuenta en PPI (Portfolio Personal Inversiones) que quiere
// bajar su historial. Búsqueda con intención clara y, al 16/11/2026, sin nadie
// que la conteste — y es el primer paso de un usuario de Rendi.
//
// Los pasos salen de la guía de la app (landingDeBroker.js). Lo que esta página
// escribe es lo propio de PPI: los errores típicos y qué hace Rendi con esos
// archivos. Cada afirmación sale del lector del servidor
// (backend/importing/parsers/ppi.py): si cambia lo que el lector hace, cambiá
// esto.

import KeywordLanding from '../../components/landing/KeywordLanding'
import { guiaDeBroker, descargaDe, comoFuncionaDe, IMPUESTOS_PROVISORIO } from '../../components/landing/landingDeBroker'
import { otrasGuiasDeBrokers } from '../../data/guiasDeBrokers'

const GUIA = guiaDeBroker('ppi')

const ERRORES = [
  {
    // ppi.py: cada fila se rutea por la hoja de la que vino (`_hoja`).
    title: 'Borrar o separar las hojas del Excel',
    desc: 'El export de Movimientos trae una hoja por cada sub-cuenta de moneda (pesos, dólar MEP, dólar cable) y otra de instrumentos. Subilo como lo bajaste: si sacás una hoja, se pierden los movimientos de esa moneda.',
  },
  {
    title: 'Filtrar sólo el último año',
    desc: 'Si el historial no arranca cuando abriste la cuenta, falta la plata con la que la fondeaste. El Estado de Cuenta lo compensa: completa tus posiciones con su costo real y cierra tu efectivo a la foto de hoy.',
  },
  {
    // ppi.py: PPI_SPOT_REVIEW y PPI_INSTRUMENTO_NO_SOPORTADO (Ingreso de Títulos).
    title: 'Esperar que el dólar SPOT y las transferencias entren solos',
    desc: 'Las compras y ventas de dólar SPOT y los títulos que te transfirieron desde otro broker no entran solos desde los Movimientos: Rendi te los muestra como avisos para que los revises. Si subiste también el Estado de Cuenta, esos títulos igual aparecen en tu cartera, con su costo.',
  },
  {
    title: 'Volver a subir todo para actualizar',
    desc: 'Si ya importaste antes, alcanza con subir el Estado de Cuenta nuevo: en Rendi tiene su propio botón, «Estado de Cuenta PPI».',
  },
]

const FEATURES = [
  {
    title: 'Tus dólares MEP y cable, en una sola cuenta',
    desc: 'PPI separa tus dólares según cómo se liquidaron. Rendi los junta en una sola cuenta en dólares, porque lo que importa es cuántos tenés, no por dónde entraron.',
  },
  {
    title: 'Tus fondos comunes, con su ganancia',
    desc: 'Cada suscripción y cada rescate de FCI entra como una compra y una venta, así ves cuánto te rindió cada fondo.',
  },
  {
    title: 'Cauciones, cupones y dividendos',
    desc: 'El interés de tus cauciones, la renta y la amortización de tus bonos y cada dividendo entran como lo que son, con su fecha.',
  },
  {
    title: 'Comisiones y retenciones a la vista',
    desc: 'Lo que te cobraron de comisión y lo que te retuvieron queda registrado aparte, con su fecha, así sabés cuánto te costó operar.',
  },
  {
    title: 'Lo que tenés hoy, igual que en PPI',
    desc: 'El Estado de Cuenta es la foto de hoy y manda: completa tus posiciones con su costo real y cierra tu saldo en pesos y en dólares a lo que dice PPI, sin inventar ganancias.',
  },
  {
    title: 'Tu ganancia medida en dólares',
    desc: 'Cada operación en pesos se pasa al dólar MEP de su fecha: ves si tu cartera de PPI creció de verdad o sólo acompañó la inflación.',
  },
  IMPUESTOS_PROVISORIO,
]

const HOW_STEPS = comoFuncionaDe(GUIA, {
  title: 'Ves tu cartera de PPI en dólares',
  desc: 'Cuánto pusiste, cuánto vale hoy y cuánto ganaste, en pesos y en dólares, con tus fondos y tus bonos. Si después sumás otro broker, queda todo junto.',
})

const RELATED = [
  ...otrasGuiasDeBrokers('/brokers/ppi'),
  { to: '/bonos-argentinos', label: 'Bonos AR' },
  { to: '/planes', label: 'Ver planes' },
]

export default function PPI() {
  return (
    <KeywordLanding
      kicker="Guía · PPI (Portfolio Personal Inversiones)"
      h1="Cómo descargar tus movimientos de PPI (y ver tu ganancia en dólares)"
      intro="PPI te da tus movimientos en un Excel con una hoja por moneda —pesos, dólar MEP, dólar cable— y tu cartera en otro. Acá tenés cómo bajar los dos desde la web, qué conviene no tocar y qué hace Rendi con ellos."
      descarga={descargaDe(GUIA, 'Son dos Excel y los dos se bajan desde la web de PPI: Movimientos (tu historial) y el Estado de Cuenta (lo que tenés hoy).')}
      errores={ERRORES}
      features={FEATURES}
      featuresTitle="Qué calcula Rendi con tus archivos de PPI"
      howSteps={HOW_STEPS}
      relatedLinks={RELATED}
      metaTitle="Cómo descargar tus movimientos de PPI — Rendi"
      metaDescription="Cómo exportar Movimientos y Estado de Cuenta de PPI (Portfolio Personal Inversiones) desde la web y ver tu ganancia real en dólares, con FCI y cauciones."
      canonicalPath="/brokers/ppi"
    />
  )
}
