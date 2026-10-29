// clicNormal.js — ¿es un click común (botón izquierdo, sin ⌘/Ctrl/Shift/Alt)?
// Un link que navega adentro de la app lo intercepta SÓLO en ese caso: con el
// botón del medio o ⌘+click el navegador abre otra pestaña, como en cualquier
// link (auditoría D12, 29/10: «Ver gráfico» era un botón y no se podía).
export function clicNormal(e) {
  return (e?.button ?? 0) === 0 && !e?.metaKey && !e?.ctrlKey && !e?.shiftKey && !e?.altKey
}
