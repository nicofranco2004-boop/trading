// useActivoDelGrafico — qué activo está abierto en las pestañas «Gráfico» y
// «Backtesting» de Análisis técnico. Es UNO para las dos: pasar de una a la
// otra no te cambia de activo (Nico, 04/11).
//   · El de la dirección (?activo=GGAL); si no, el último que miraste en este
//     navegador (utils/graficoTecnico.js, a nombre de la persona y la cuenta);
//     si no, el primero de tu cartera con gráfico, o el S&P 500.
//   · Se guarda y va a la dirección recién cuando la pestaña ABRIÓ ese activo
//     (`abierto`): pedido con otro nombre (GGAL.BA y tu lote es GGAL), queda el
//     tuyo y no los dos. Sin sumar un paso al «atrás» del navegador por activo.
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../utils/api'
import { activoDeEntrada, activoValido, guardado, recordar } from '../utils/graficoTecnico'
import { useDuenoDeLosDatos } from '../utils/duenoDeLaPestana'

export function useActivoDelGrafico() {
  // De quién es lo que se recuerda: la persona y la cuenta de cuando se abrió
  // la pantalla (utils/duenoDeLaPestana). Si otra pestaña cambia de cuenta, la
  // puerta ya no lo guarda a nombre de la nueva.
  const persona = useDuenoDeLosDatos()
  const [searchParams, setSearchParams] = useSearchParams()
  const deLaDireccion = activoValido(searchParams.get('activo'))
  // El activo abierto, con el nombre con que lo pediste (el de tu lista, el
  // del catálogo, el de tus lotes). null mientras se decide (sin dirección ni
  // nada guardado, hace falta saber qué tenés).
  const [activo, setActivo] = useState(() => deLaDireccion || guardado(persona).activo)
  const [recientes, setRecientes] = useState(() => guardado(persona).recientes)
  // Elegiste con el buscador o un atajo: el renglón del activo se arma de nuevo
  // y el teclado tiene que seguir en su botón, no volver al principio.
  const [enfocar, setEnfocar] = useState(false)

  // Sin nada guardado: el primero de tu cartera con gráfico, o el S&P 500.
  useEffect(() => {
    if (activo) return
    let vivo = true
    api.get('/positions').catch(() => []).then(pos => {
      if (vivo) setActivo(a => a || activoDeEntrada({ deLaDireccion: null, persona, posiciones: pos || [] }))
    })
    return () => { vivo = false }
  }, [activo, persona])

  // Un link a otro activo con la pestaña ya abierta (?activo=…): ése.
  useEffect(() => {
    if (deLaDireccion && deLaDireccion !== activo) setActivo(deLaDireccion)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deLaDireccion])

  const abierto = (a) => {
    setRecientes(recordar(persona, a).recientes)
    setSearchParams(prev => {
      if (prev.get('activo') === a) return prev
      const next = new URLSearchParams(prev)
      next.set('activo', a)
      return next
    }, { replace: true })
  }
  const elegir = (s) => { const a = activoValido(s); if (a) { setEnfocar(true); setActivo(a) } }

  return { activo, setActivo, recientes, enfocar, elegir, abierto }
}
