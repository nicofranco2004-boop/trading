// PesoEnCartera — cuánto pesa una fila DENTRO DE SU BROKER: una barrita violeta
// debajo del valor, llena en proporción, con el porcentaje escrito al lado
// ("28,9 %") y la frase entera en el globo del mouse ("Pesa 28,9 % de Schwab").
// La usan las filas de Cartera en la compu (Positions.jsx, las dos tablas) y en
// el celular (PositionsMobile.jsx). El efectivo también la lleva: es parte del
// broker, y así las filas de cada tarjeta suman 100 %.
//
// Por qué del broker y no del total (decisión de Nico, 2026-09-30): el peso
// sobre toda la cartera ya está en el Dashboard y lo dice Mervall-E AI; el peso
// dentro de cada broker no estaba en ningún lado. Y se puede comprobar mirando:
// el total está escrito en el encabezado de la misma tarjeta.
//
// ⚠️ EL TOTAL ES EL DE LA TARJETA COMPLETA, en la MISMA moneda que la fila. Con
// la cuenta unificada (pesos + dólares en una tarjeta) es el total unificado;
// separada, el de cada tarjeta. Y SIN EL BUSCADOR: buscando "NVDA" la tarjeta
// queda con esa sola fila, y con el total de lo visible decía "100 %". Quien la
// usa pasa ese número: compu `totalPesoDisp` (misma cuenta que el encabezado,
// sobre la tarjeta entera), celular `totalPesoUsd` / `totalPesoFiltro`.
//
// El porcentaje va ESCRITO, no sólo en el globo: la barrita mide 3 px, el panel
// del navegador de la app no muestra esos globos y en el celular no existe
// "pasar el mouse".
//
// Violeta y no verde/rojo: el peso no es ganancia ni pérdida. Crece desde la
// derecha al aparecer (`.peso-crece`) porque el valor está alineado a la
// derecha; si cambia con un refresco de precios, se acomoda (`.barra-intensidad`).
//
// Con "Ocultar saldos" no se muestra: la proporción también es información de
// la cartera.

import { usePrivacy } from '../contexts/PrivacyContext'
import { nfmt } from '../utils/format'

// La fracción 0..1, o null si no hay con qué calcularla (sin valor, un saldo
// negativo o en cero, total en cero).
export function pesoEnCartera(valor, total) {
  const v = Number(valor)
  const t = Number(total)
  if (valor == null || !Number.isFinite(v) || !(v > 0)) return null
  if (!Number.isFinite(t) || !(t > 0)) return null
  return Math.min(1, v / t)
}

export default function PesoEnCartera({ valor, total, nombre }) {
  const { hidden } = usePrivacy()
  const peso = pesoEnCartera(valor, total)
  if (hidden || peso == null) return null
  const pct = nfmt(peso * 100, 1)
  const deQue = nombre ? `de ${nombre}` : 'de este broker'
  return (
    <span className="mt-1 flex w-full items-center justify-end gap-1.5" title={`Pesa ${pct} % ${deQue}`}>
      <span aria-hidden="true" className="flex flex-1 min-w-[20px] h-[3px] justify-end rounded-full bg-line/70 overflow-hidden">
        <span className="peso-crece barra-intensidad block h-full rounded-full bg-data-violet/70" style={{ width: `${peso * 100}%` }} />
      </span>
      <span className="shrink-0 text-[10.5px] leading-none font-medium text-data-violet tabular">
        <span className="sr-only">Pesa </span>{pct} %<span className="sr-only"> {deQue}</span>
      </span>
    </span>
  )
}
