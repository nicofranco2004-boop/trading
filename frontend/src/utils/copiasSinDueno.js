// copiasSinDueno — al abrir la app, ordena las copias del navegador que dejó la
// versión ANTERIOR a la regla de dueño (utils/duenoDeLaPestana).
//
// Desde la regla, cada copia con datos de una cuenta va a nombre de
// `persona|cuenta` y las viejas, sin dueño, ya no se leen: no le aparecen a
// nadie. Pero seguían ahí. En localStorage, para siempre: el valor de la
// cartera de «desde tu última visita». En sessionStorage, mientras dure la
// pestaña: la tanda del asesor con nombres de clientes y los totales vistos.
//
// Dos destinos (re-test a ciegas 2, 30/10):
//   · SE PASAN A SU DUEÑO las que lo dicen en la clave: «desde tu última
//     visita» y las tarjetas descartadas iban a nombre del EMAIL de la persona
//     (`…diagnostico:ana@x.com`). Pasan a `ana@x.com|propia`: borrarlas hacía
//     que, una vez, volvieran a aparecer las tarjetas descartadas y
//     desapareciera «desde tu última visita».
//   · SE BORRAN las que no dicen de quién son (la foto del día, la tanda, los
//     totales vistos, los dibujos de antes del guardado por persona): no hay
//     forma de saber a quién darlas, y se rehacen solas. ⚠️ Los dibujos
//     pendientes de las ramas del gráfico que todavía no usan la regla
//     (`rendi_dibujos:AAPL:usd`) se borran acá: al juntar el técnico se parte
//     de claude/dibujos-por-persona, que ya guarda a nombre de su dueño.
//
// Cómo distingue una vieja de una nueva: las familias de abajo son las que
// pasaron por la regla, y una clave suya sin `|` no tiene dueño (el dueño es
// siempre `email|propia` o `email|cliente-N`). El demo (`demo`) no se toca.

import { claves, quitarClaves, mudarCopiaVieja } from './almacen'
import { CATALOGO, LOCAL, SESION } from './catalogoDelAlmacen'

const FAMILIAS = [
  'rendi_snapshot_date',
  'rendi_tanda_ultima',
  'rendi_valor_visto:',
  'rendi_version_cartera:',
  'rendi_cambios_movimientos:',
  'rendi_ultimo_total:',
  'rendi_lastvisit_',
  'rendi_diag_dismissed_',
  'rendi_dibujos:',
]

// Las que iban a nombre del email: la entrada del catálogo y cómo era la clave.
const CON_EMAIL = [
  { entrada: CATALOGO.ultimaVisitaDiagnostico, vieja: /^rendi_lastvisit_diagnostico:(.+)$/ },
  { entrada: CATALOGO.descartesDiagnostico, vieja: /^rendi_diag_dismissed_diag:(.+)$/ },
]

export function esCopiaSinDueno(clave) {
  if (!clave || !FAMILIAS.some(f => clave.startsWith(f))) return false
  return !clave.includes('|') && !/(^|:)demo(:|$)/.test(clave)
}

/** El dueño que dice una copia vieja, o null. El email como lo compara quienEs. */
function duenoDeLaCopiaVieja(clave) {
  for (const { entrada, vieja } of CON_EMAIL) {
    const m = vieja.exec(clave)
    const email = m && m[1].trim().toLowerCase()
    if (email && email.includes('@')) return { entrada, dueno: `${email}|propia` }
  }
  return null
}

function ordenar(donde) {
  try {
    let pasadas = 0
    const sinDueno = []
    for (const k of claves(donde).filter(esCopiaSinDueno)) {
      const suyo = duenoDeLaCopiaVieja(k)
      if (suyo && mudarCopiaVieja(suyo.entrada, k, suyo.dueno)) pasadas++
      else sinDueno.push(k)
    }
    quitarClaves(donde, sinDueno)
    return { pasadas, borradas: sinDueno.length }
  } catch { return { pasadas: 0, borradas: 0 } }   // sin almacenamiento: no hay nada
}

/** Ordena las copias sin dueño de los dos almacenes: pasa a su dueño las que lo
 *  dicen y borra las demás. Devuelve cuántas pasó y cuántas borró. */
export function ordenarCopiasSinDueno() {
  if (typeof window === 'undefined') return { pasadas: 0, borradas: 0 }
  const a = ordenar(LOCAL), b = ordenar(SESION)
  return { pasadas: a.pasadas + b.pasadas, borradas: a.borradas + b.borradas }
}
