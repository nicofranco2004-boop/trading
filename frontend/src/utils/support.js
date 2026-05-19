// Contacto de soporte. Cambiá acá el número cuando migres a un business
// number — todos los lugares de la app que muestran "consultar" lo usan.
// Formato: solo dígitos, código de país incluido, sin "+" ni espacios.

export const SUPPORT_WHATSAPP = '542914373695'
export const SUPPORT_MESSAGE = 'Hola, quería hacer una consulta acerca de Rendi.'

/** Devuelve el href para abrir WhatsApp Web/app con mensaje pre-llenado. */
export function whatsappUrl(message = SUPPORT_MESSAGE) {
  return `https://wa.me/${SUPPORT_WHATSAPP}?text=${encodeURIComponent(message)}`
}

/** Display friendly del número (con espacios) — para mostrar en UI. */
export const SUPPORT_WHATSAPP_DISPLAY = '+54 9 2914 37-3695'
