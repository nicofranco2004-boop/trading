// IslaSegura — la isla puede fallar, la pantalla no.
// ═══════════════════════════════════════════════════════════════════════════
// 🔴 POR QUÉ EXISTE. Nico abrió la isla en su iPhone y le apareció "Se rompió
// esta pantalla": el acompañante se llevó puesta la aplicación entera.
//
// Eso está mal más allá del bug que lo causó. La isla es un ACOMPAÑANTE: flota
// sobre la pantalla que el usuario está mirando, y esa pantalla —su cartera,
// sus números— no tiene nada que ver con ella. Que un error en una burbujita de
// chat impida ver cuánta plata tenés es una desproporción, aunque la burbujita
// esté rota.
//
// Con esto, si la isla falla se apaga sola y el resto sigue andando. El usuario
// pierde el acompañante, que es exactamente lo que se rompió, y nada más.
//
// NO ES UN PARCHE PARA NO BUSCAR LA CAUSA: el error se sigue registrando en la
// consola con todo su detalle. Lo que cambia es quién paga el costo mientras
// tanto.

import { Component } from 'react'

export default class IslaSegura extends Component {
  constructor(props) {
    super(props)
    this.state = { fallo: false }
  }

  static getDerivedStateFromError() {
    return { fallo: true }
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('[Rendi] la isla flotante falló y se apagó sola:', error, info?.componentStack)
  }

  componentDidUpdate(prevProps) {
    // Si el usuario navega a otra pantalla, se le da otra oportunidad: el fallo
    // pudo depender de esa pantalla o de un dato que ya no está.
    if (this.state.fallo && prevProps.reintentarEn !== this.props.reintentarEn) {
      this.setState({ fallo: false })
    }
  }

  render() {
    if (this.state.fallo) return null
    return this.props.children
  }
}
