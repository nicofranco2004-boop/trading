// MiniLinea — el gráfico chiquito de una línea tuya con aviso (Nico, 29/10).
// ═══════════════════════════════════════════════════════════════════════════
// Va en «Mis alertas» y en el formulario («Una línea que dibujaste»): los
// últimos cierres y tu línea —o los dos bordes de tu canal, con la franja de
// entre medio— en su color, para reconocer cuál es sin abrir la ficha. Los
// datos los arma el servidor con la misma cuenta que el aviso
// (alerts_engine.resumen_de_dibujo): `serie` (cierres) y `lineas` (una lista
// de precios por línea, en esos mismos días; null donde no se sabe).
//
// Sistema visual: generación nueva — sin texto adentro, sólo trazo; el color
// de tu dibujo es el de la ficha (CapaDibujos.colorDe), del tema.
import { colorDe } from '../asset/CapaDibujos'

/** Los trazos en un cuadro de `ancho` × `alto`: { precio, lineas: [puntos…] } o null. */
export function trazosDeMiniLinea(resumen, ancho, alto) {
  const serie = resumen?.serie || []
  const lineas = resumen?.lineas || []
  const n = serie.length
  if (n < 2) return null
  const valores = [...serie, ...lineas.flat()].filter(v => v != null && Number.isFinite(v))
  const lo = Math.min(...valores), hi = Math.max(...valores)
  const margen = (hi - lo) * 0.08 || Math.abs(hi) * 0.02 || 1
  const y = (v) => alto - ((v - (lo - margen)) / (hi - lo + 2 * margen)) * alto
  const x = (i) => (i / (n - 1)) * ancho
  const puntos = (vs) => vs.map((v, i) => (v == null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`)).filter(Boolean)
  return { precio: puntos(serie), lineas: lineas.map(puntos) }
}

export default function MiniLinea({ resumen, ancho = 96, alto = 48, className = '', etiqueta }) {
  const t = trazosDeMiniLinea(resumen, ancho, alto)
  if (!t) {
    return <span className={`block rounded border border-dashed border-line-2 ${className}`} style={{ width: ancho, height: alto }} aria-hidden="true" />
  }
  const color = colorDe(resumen)
  const canal = resumen.tipo === 'canal' && t.lineas.length === 2 && t.lineas[0].length > 1 && t.lineas[1].length > 1
  return (
    <svg width={ancho} height={alto} viewBox={`0 0 ${ancho} ${alto}`} className={`flex-shrink-0 overflow-hidden ${className}`}
      {...(etiqueta ? { role: 'img', 'aria-label': etiqueta } : { 'aria-hidden': 'true' })}>
      {canal && (
        <polygon points={[...t.lineas[0], ...[...t.lineas[1]].reverse()].join(' ')} fill={color} fillOpacity="0.12" stroke="none" />
      )}
      {t.lineas.map((ps, k) => ps.length > 1 && (
        <polyline key={k} points={ps.join(' ')} fill="none" stroke={color} strokeWidth="1.5" />
      ))}
      <polyline points={t.precio.join(' ')} fill="none" stroke="rgb(var(--ink-1))" strokeWidth="1.2" strokeLinejoin="round" />
    </svg>
  )
}
