// Segmento — botones pegados para elegir UNA opción (Línea | Velas, Técnico
// primero | Fundamental primero). El elegido queda marcado con aria-pressed.
// LecturaTecnica.jsx tenía su propia copia para la moneda y el rango; desde el
// 29/10 esos dos van en un menú desplegable (`ElegirVista`) y la copia se borró.
//
// `estirar`: en el celular los botones se reparten todo el ancho (en la compu,
// cada uno mide lo que su texto). Y si no entran, el texto de cada botón se
// parte en dos renglones en vez de empujar la página de costado: «Ordenar por
// · Técnico primero · Fundamental primero» medía 348 px y en un celular de
// 375 quedan 343 (auditoría D2, 31/10). Para eso `min-w-0` (sin él, un hijo de
// un flex no se achica por debajo de su texto) y el renglón sin `nowrap`.

const GRUPO = (estirar) =>
  `${estirar ? 'flex flex-1 min-w-0 sm:flex-none sm:inline-flex' : 'inline-flex'} gap-0.5 bg-bg-2 border border-line rounded-lg p-0.5`
const BOTON = (estirar) =>
  `${estirar ? 'flex-1 min-w-0 whitespace-normal leading-tight sm:flex-none sm:whitespace-nowrap' : 'whitespace-nowrap'} min-h-10 sm:min-h-8 px-3 sm:px-2.5 text-xs rounded tabular transition-colors`

export default function Segmento({ etiqueta, valor, alElegir, opciones, estirar = false }) {
  return (
    <div className={GRUPO(estirar)}
      role="group" aria-label={etiqueta}>
      {opciones.map(([id, label]) => (
        <button key={id} type="button" onClick={() => alElegir(id)} aria-pressed={valor === id}
          className={`${BOTON(estirar)} ${valor === id ? 'bg-bg-1 text-ink-0 font-medium shadow-sm' : 'text-ink-2 hover:text-ink-0'}`}>
          {label}
        </button>
      ))}
    </div>
  )
}
