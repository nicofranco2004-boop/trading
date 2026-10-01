// CursorEscribiendo — el cursor que parpadea al final de la respuesta de Rendi
// AI MIENTRAS se está escribiendo (escribiendoEn, contexts/VozContext.jsx). Se
// apaga cuando llega el final: un cursor que sigue parpadeando en una respuesta
// terminada diría que falta algo. Con "reducir movimiento" queda quieto.
export default function CursorEscribiendo() {
  return (
    <span
      className="terminal-cursor inline-block w-[2px] h-[1.05em] ml-0.5 -mb-[0.15em] rounded-full bg-data-violet"
      aria-hidden="true"
    />
  )
}
