// Buscar / ordenar / filtrar el panel de migración FX.
//
// Con 497 cuentas ordenadas por cantidad de ventas, las que hay que mirar —las
// que más le mueven el rendimiento al usuario— quedan desparramadas entre las
// que no cambian nada. Esto vive fuera del componente para poder testearlo.

/** Cuánto le cambia el rendimiento al usuario, en PUNTOS porcentuales.
 *  Pasar de +11% a −90% son 101 puntos: eso es lo que esa persona abre. */
export function deltaRendimiento(sim) {
  const v = sim?.verificacion
  if (!v || v.rendimiento_antes_pct == null || v.rendimiento_despues_pct == null) return null
  return v.rendimiento_despues_pct - v.rendimiento_antes_pct
}

export function filtrarFilas(cuentas, sims, { buscar = '', orden = 'default', filtro = 'todas' } = {}) {
  let out = cuentas || []
  const q = String(buscar || '').trim().replace(/^#/, '')
  if (q) out = out.filter(c => String(c.user_id).includes(q))

  if (filtro === 'caen') {
    out = out.filter(c => {
      const d = deltaRendimiento(sims?.[c.user_id])
      return d != null && Math.abs(d) >= 50
    })
  } else if (filtro === 'frenadas') {
    out = out.filter(c => sims?.[c.user_id] && !sims[c.user_id].ok)
  } else if (filtro === 'sinsim') {
    out = out.filter(c => !sims?.[c.user_id] && c.fx_version === 'v1' && !c.bloqueada_por_escala)
  }

  if (orden === 'caida') {
    // La caída más fuerte primero. Las que no tienen simulación van al final:
    // no se sabe cuánto cambian, así que no pueden encabezar la lista.
    out = [...out].sort((a, b) => {
      const da = deltaRendimiento(sims?.[a.user_id])
      const db = deltaRendimiento(sims?.[b.user_id])
      if (da == null && db == null) return 0
      if (da == null) return 1
      if (db == null) return -1
      return da - db
    })
  }
  return out
}

export function contarCaen(cuentas, sims) {
  return (cuentas || []).filter(c => {
    const d = deltaRendimiento(sims?.[c.user_id])
    return d != null && Math.abs(d) >= 50
  }).length
}

export function contarFrenadas(cuentas, sims) {
  return (cuentas || []).filter(c => sims?.[c.user_id] && !sims[c.user_id].ok).length
}
