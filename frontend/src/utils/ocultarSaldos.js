// ocultarSaldos.js — cómo se ve un monto con «Ocultar saldos» prendido (el
// ojito de la Cartera, contexts/PrivacyContext.jsx). Vive en utils para que lo
// usen también las funciones que arman textos sin depender de React.

// Lo que va en lugar del monto. Uno solo para toda la app.
export const OCULTO = '••••••'
// La frase que lo explica, cuando un texto se queda sin su número. Una sola
// manera de decirlo (auditoría D, 29/10: había tres).
export const AVISO_OCULTO = 'Oculto porque tenés prendido «Ocultar saldos».'
