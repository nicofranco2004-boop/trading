// safeUrl — sanitiza URLs externas antes de pasarlas a href/window.location.
// ════════════════════════════════════════════════════════════════════════════
// React NO escapa el `scheme://` de un href. Si una URL viene del backend o
// de un feed externo (news RSS, ticker links, etc.) con `javascript:alert(...)`
// o `data:text/html,...`, el click ejecuta XSS / abre páginas raras.
//
// safeExternalUrl(url) devuelve la URL si pasa los checks; si no, devuelve
// "#" (link inerte). Usar para todo `<a href={x}>` donde `x` no esté hardcoded.
//
// Uso:
//   <a href={safeExternalUrl(news.url)} target="_blank" rel="noopener noreferrer">
//   if (isSafePaymentUrl(initPoint)) window.location.href = initPoint
//
// Reglas:
//   - Solo `http:` y `https:` se permiten en safeExternalUrl
//   - isSafePaymentUrl exige `https:` + host en allowlist (Rebill)

const _PAYMENT_ALLOWED_HOSTS = new Set([
  'app.rebill.com',
  'checkout.rebill.com',
  'pay.rebill.com',
  'app.rebill.dev',       // sandbox
  'checkout.rebill.dev',  // sandbox
])

export function safeExternalUrl(url) {
  if (!url || typeof url !== 'string') return '#'
  try {
    const parsed = new URL(url)
    // Solo http/https. Bloquea javascript:, data:, file:, vbscript:, etc.
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return '#'
    }
    return url
  } catch {
    // URL inválida → bloqueamos
    return '#'
  }
}

export function isSafePaymentUrl(url) {
  if (!url || typeof url !== 'string') return false
  try {
    const parsed = new URL(url)
    return (
      parsed.protocol === 'https:' &&
      _PAYMENT_ALLOWED_HOSTS.has(parsed.hostname)
    )
  } catch {
    return false
  }
}
