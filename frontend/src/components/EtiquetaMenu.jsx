// EtiquetaMenu — las etiquetas «Nuevo» y «Beta» del menú (lanzamiento del
// análisis técnico, Nico 31/10/2026). Las dibujan el menú de la compu
// (Sidebar), «Más» del celular (More) y el título de Análisis técnico, así las
// tres se ven iguales. Cuándo se ven NO se decide acá: sale de
// utils/navegacion.js (FIN_DEL_NUEVO, `beta`).
//   · «Nuevo»: violeta lleno, el que llama la atención (va en el grupo).
//   · «Beta»: violeta de contorno, para que no compita con «Nuevo».
// Sans, sentence case y radio `full` (R2/R5 de frontend/CLAUDE.md).

export function EtiquetaNuevo({ className = '' }) {
  return (
    <span className={`inline-flex items-center flex-shrink-0 rounded-full bg-data-violet text-white px-2 py-px text-[11px] font-semibold leading-4 ${className}`}>
      Nuevo
    </span>
  )
}

// `compacta`: la del menú de la compu, donde «Análisis técnico» + «Beta» no
// entraban en los 248 px (se cortaba en «Análisis técn…», medido el 31/10).
// Un prop y no una clase de afuera: dos `px-` o dos `text-` en el mismo nodo
// los decide el orden de la hoja compilada, no el del atributo (R5).
export function EtiquetaBeta({ className = '', compacta = false }) {
  return (
    <span title="Todavía lo estamos ajustando"
      className={`inline-flex items-center flex-shrink-0 rounded-full border border-data-violet/60 text-data-violet font-semibold leading-4 ${
        compacta ? 'px-1 text-[10px]' : 'px-1.5 text-[11px]'} ${className}`}>
      Beta
    </span>
  )
}

// La clase del fondo resaltado de una fila mientras dure el «Nuevo»: violeta
// suave con borde, distinto del «estás acá» (gris con la rayita violeta).
export const FILA_RESALTADA = 'bg-data-violet/[0.08] ring-1 ring-inset ring-data-violet/25'
