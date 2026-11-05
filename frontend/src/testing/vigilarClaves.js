// vigilarClaves — corre antes de CADA archivo de prueba (vite.config.js,
// test.setupFiles): si React avisa que dos hermanos tienen el mismo `key`, la
// prueba que lo dibujó da rojo.
// ═══════════════════════════════════════════════════════════════════════════
// 🔴 POR QUÉ (Backtesting, 05/11). El renglón del activo y la prueba eran
// hermanos con el mismo `key` (el activo). React lo avisaba en cada corrida
// —«Encountered two children with the same key»— y las pruebas daban verde
// igual. En la página, cada cambio de activo dejaba el renglón viejo pegado y
// muerto: diez renglones apilados, y la cruz de su buscador no cerraba nada.
// El aviso existe sólo mientras se prueba (la web publicada no lo dice): éste
// es el único lugar donde alguien lo puede ver.
//
// Lo que no ve: un `key` repetido en algo que ninguna prueba dibuja, o que
// sólo se repite con datos que ninguna prueba arma.
import { afterAll, afterEach } from 'vitest'

const AVISO = 'Encountered two children with the same key'
let vistos = []

const original = console.error
console.error = function (...args) {
  if (typeof args[0] === 'string' && args[0].includes(AVISO)) {
    // React manda el `key` repetido y, al final, dónde está (la pila de componentes).
    const donde = String(args[2] ?? '').split('\n').map(s => s.trim()).filter(Boolean).slice(0, 3).join(' ← ')
    vistos.push(`key «${args[1]}»${donde ? ` (${donde})` : ''}`)
  }
  return original.apply(this, args)
}

/** Los `key` repetidos que avisó React desde la última vez (y los olvida). Para
 *  la prueba de este vigía. */
export function clavesRepetidas() {
  const out = vistos
  vistos = []
  return out
}

function rojoSiHubo() {
  const lista = [...new Set(clavesRepetidas())]
  if (!lista.length) return
  throw new Error('Dos hermanos con el mismo `key`: React pierde el rastro de uno y lo deja en la '
    + 'página, muerto (o lo borra), cada vez que cambian. Dale a cada uno su propio key.\n  '
    + lista.join('\n  '))
}

afterEach(rojoSiHubo)
afterAll(rojoSiHubo)
