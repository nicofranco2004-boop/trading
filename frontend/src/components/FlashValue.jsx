// FlashValue — highlight direccional one-shot al cambiar un valor "vivo".
// ═══════════════════════════════════════════════════════════════════════════
// Cuando un precio/valor se actualiza (refresh ~90s o llegada de /prices),
// aplica un fondo verde (subió) o rojo (bajó) que se desvanece en ~420ms.
// El primer render NO flashea (no hay "anterior" con qué comparar).
//
// API:
//   value    → number  (valor CRUDO para detectar dirección — NO el string formateado)
//   children → ReactNode (lo que se muestra: el string ya formateado, o <AnimatedNumber>)
//   as       → tag contenedor ('span' por defecto)
//   className→ clases extra del contenedor
//   epsilon  → umbral mínimo de cambio para flashear (default 0)
//
// NO remonta los children (no usa key) → así un <AnimatedNumber> adentro
// conserva su count-up. Reusa los keyframes flash-up/flash-down de index.css,
// que se anulan bajo prefers-reduced-motion.

import { useEffect, useRef, useState } from 'react'

export default function FlashValue({
  value,
  children,
  as: Tag = 'span',
  className = '',
  epsilon = 0,
}) {
  const prev = useRef(value)
  const [dir, setDir] = useState(null) // 'up' | 'down' | null

  useEffect(() => {
    const before = prev.current
    prev.current = value
    if (typeof value !== 'number' || typeof before !== 'number') return
    const delta = value - before
    if (Math.abs(delta) <= epsilon) return
    setDir(delta > 0 ? 'up' : 'down')
    const t = setTimeout(() => setDir(null), 450)
    return () => clearTimeout(t)
  }, [value, epsilon])

  const flashCls = dir === 'up' ? 'flash-up' : dir === 'down' ? 'flash-down' : ''

  return <Tag className={`${flashCls} ${className}`.trim()}>{children}</Tag>
}
