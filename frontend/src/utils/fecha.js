/**
 * El calendario del frontend: UNA sola definición de "hoy".
 *
 * EL BUG (auditoría 1B, H-10). Veintisiete lugares del frontend calculaban el
 * día de hoy con `new Date().toISOString().slice(0, 10)`, que es el día **UTC**.
 * De 21:00 a 23:59 hora argentina eso devuelve **mañana**.
 *
 * No era cosmético: esos 27 sitios fijan la fecha POR DEFECTO de todo lo que se
 * carga a mano. Una compra, una venta, un movimiento de caja, un cupón, un plazo
 * fijo o un futuro cargados a las 22:00 nacían fechados al día siguiente — y el
 * backend los aceptaba, porque su guard de fecha futura compara contra el reloj
 * del proceso, que en Railway también es UTC. Es la misma clase de fila que dejó
 * 25 cupones de AL35 fechados en 2027 y US$ 3,9M fantasma en la cartera.
 *
 * EL ARREGLO YA EXISTÍA, EN UNO SOLO DE LOS 28. `AdvisorDashboard.jsx` lo tenía,
 * con su comentario: *"Fecha LOCAL (audit: toISOString es UTC — de noche en
 * Argentina devolvía la fecha de mañana en un documento con matrícula CNV)"*. El
 * bug estaba diagnosticado y arreglado en 1 de 28 lugares. El resto de este
 * archivo es ese mismo arreglo, propagado.
 *
 * POR QUÉ HORA LOCAL Y NO ART EXPLÍCITA. Es la decisión que el repo ya había
 * tomado en el sitio arreglado, y para un usuario en Argentina —que son todos—
 * local ES la hora argentina. Límite declarado, no arreglado: alguien que abra
 * la app desde otro huso horario va a ver un default de fecha que puede diferir
 * en un día del "hoy" que usa el backend (`backend/fechas.py`, ART fija).
 *
 * ⚠️ NO USES ESTO PARA UNA MARCA DE TIEMPO. `created_at`, `ts` de analytics y
 * demás instantes van en `new Date().toISOString()` completo y en UTC, que es lo
 * correcto para un instante. Lo que este archivo resuelve es el DÍA CALENDARIO.
 */

/** Hoy como `'YYYY-MM-DD'`, en el día calendario del usuario. */
export function hoyISO() {
  return fechaISO(new Date())
}

/** Cualquier `Date` como `'YYYY-MM-DD'`, sin el corrimiento de huso de `toISOString`. */
export function fechaISO(d) {
  if (!(d instanceof Date) || Number.isNaN(d.getTime())) return null
  const mes = String(d.getMonth() + 1).padStart(2, '0')
  const dia = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mes}-${dia}`
}

/** Hoy desplazado `n` días (negativo hacia atrás), como `'YYYY-MM-DD'`. */
export function hoyMasDias(n) {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return fechaISO(d)
}
