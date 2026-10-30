// 🔴 LO QUE LA PANTALLA MANDA SOLA AL SERVIDOR SALE CON EL DUEÑO DE LOS DATOS.
//
// Censo de los envíos automáticos: todo `api.post/put/patch/delete` que corre
// dentro de un useEffect / useLayoutEffect / setInterval / setTimeout —o en una
// función del mismo archivo que esos llaman, a cualquier profundidad— tiene que
// salir por utils/enviosConDueno (`enviarDe`, o `guardarPnlNoRealizado`, que lo
// usa) o estar en LIBRES con su porqué: no lleva números de una cuenta.
// Un envío nuevo sin clasificar pone esto en rojo.
//
// POR QUÉ (re-test a ciegas 3, 30/10). La pestaña vieja del asesor mandaba cada
// 90 s la ganancia no realizada del cliente 2 a nombre del cliente 3, porque el
// pedido sale con la cuenta que la pestaña tiene AHORA (api.js) y el número era
// de la que tenía al cargar. utils/almacen había cerrado ese eslabón para el
// navegador; éste es el mismo eslabón del lado del servidor.
//
// Lo que queda abierto, dicho:
// - Un envío automático armado en OTRO archivo (un hook o un util que hace el
//   api.post y al que un efecto llama): el censo sigue llamadas sólo dentro del
//   mismo archivo. Por eso las rutas de ENVIOS que sólo salen solas
//   (/snapshots, /monthly/sync-unrealized) no pueden aparecer fuera de
//   utils/enviosConDueno.js, se llamen desde donde se llamen.
// - Los guardados que dispara un clic (un formulario) no son de este censo: los
//   cuida el servidor por número de fila; ver la nota del commit.
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { ENVIOS } from '../utils/enviosConDueno'

const SRC = join(__dirname, '..')
const SALIDA = 'utils/enviosConDueno.js'

// Envíos automáticos que NO llevan números de una cuenta.
const LIBRES = {
  'components/fundamentals/AISummaryCard.jsx|/fundamentals/ai-summary':
    'pide el resumen de una empresa: manda sólo el ticker',
  'components/plan/AvisoPrecios.jsx|/me/aviso-precios-visto':
    'marca que LA PERSONA vio el aviso de precios: cuerpo vacío, el servidor lo anota por la sesión',
  'pages/AdvisorCobros.jsx|/advisor/cashflows/positions':
    'es una lectura (POST con cuerpo vacío) de la renta fija de los clientes del asesor',
  'components/RadiografiaTecnica.jsx|/tecnico/cartera':
    'es una lectura: manda los tickers de la cartera y vuelve su lectura técnica; el servidor no guarda nada',
  'hooks/useDiario.js|/tecnico/en-fechas':
    'es una lectura: manda ticker y fecha de cada operación y vuelve la tendencia de ese día; no guarda nada',
  'pages/TuLista.jsx|/tecnico/lista':
    'es una lectura: manda los tickers de la lista de seguidos y vuelve su lectura técnica; no guarda nada',
}

function archivos(dir = SRC, out = []) {
  for (const n of readdirSync(dir)) {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) {
      if (n === '__guards__' || n === 'testing' || n === '__design__') continue
      archivos(p, out)
    } else if (/\.(js|jsx|ts|tsx)$/.test(n) && !/\.test\.|\.spec\./.test(n)) out.push(p)
  }
  return out
}

function cierre(t, i, abre, cierra) {
  let n = 0
  for (let j = i; j < t.length; j++) {
    if (t[j] === abre) n++
    else if (t[j] === cierra && --n === 0) return j + 1
  }
  return t.length
}

// El cuerpo de una función declarada en el archivo (function f / const f = … =>).
function cuerpoDe(t, nombre) {
  const re = new RegExp(`(?:function\\s+${nombre}\\s*\\(|(?:const|let)\\s+${nombre}\\s*=\\s*(?:async\\s*)?(?:\\([^)]*\\)|\\w+)\\s*=>|(?:const|let)\\s+${nombre}\\s*=\\s*(?:async\\s+)?function)`)
  const m = re.exec(t)
  if (!m) return null
  const llave = t.indexOf('{', m.index + m[0].length - 1)
  const conLlave = m[0].startsWith('function') || /=>\s*$/.test(t.slice(m.index, llave)) || /function$/.test(m[0])
  return t.slice(m.index, conLlave ? cierre(t, llave, '{', '}') : t.indexOf('\n', m.index))
}

const ESCRITURA = /\b(?:api\.(post|put|patch|delete)\(\s*([^,)\n]*)|(enviarDe|guardarPnlNoRealizado)\()/g
const NO_SON_FUNCIONES = /^(if|for|while|switch|catch|function|return|useEffect|useLayoutEffect|setInterval|setTimeout)$/

/** Los envíos que corren solos en `texto`: [{ via, ruta, desde }]. */
function enviosAutomaticos(texto) {
  const out = [], vistos = new Set(), cola = []
  for (const m of texto.matchAll(/\buse(?:Layout)?Effect\(|\bset(?:Interval|Timeout)\(/g)) {
    const i = m.index + m[0].length - 1
    cola.push(['efecto', texto.slice(i, cierre(texto, i, '(', ')'))])
  }
  while (cola.length) {
    const [desde, b] = cola.shift()
    for (const w of b.matchAll(ESCRITURA)) {
      out.push(w[3] ? { via: w[3], desde } : { via: 'api', ruta: w[2].trim().replace(/^['"`]|['"`]$/g, ''), desde })
    }
    for (const c of b.matchAll(/\b([A-Za-z_]\w*)\s*\(/g)) {
      const n = c[1]
      if (vistos.has(n) || NO_SON_FUNCIONES.test(n)) continue
      vistos.add(n)
      const cu = cuerpoDe(texto, n)
      if (cu) cola.push([n, cu])
    }
  }
  return out
}

const rel = (p) => relative(SRC, p).split('\\').join('/')

// Lo que sale con `fetch` directo, sin pasar por utils/api: ahí no llega el
// freno de la pestaña desfasada (otra pestaña cambió la cuenta) ni el
// encabezado del cliente. Lista cerrada: ninguno guarda datos de una cuenta.
const FETCH_DIRECTO = {
  'contexts/AuthContext.jsx': 'despierta al servidor (/api/health) cada 4 minutos: no manda nada',
  'utils/uso.js': 'el uso de la app (qué pantallas abre la persona): es de la persona, no de una cuenta',
  'utils/autoUpdate.js': '/version.json, para saber si hay una versión nueva de la app',
  'pages/Admin.jsx': '/version.json, la versión publicada',
  'components/import/ImportWizard.jsx': 'baja la planilla modelo del importador, vacía: igual para todos',
  'hooks/useDictado.js': 'manda el audio para pasarlo a texto; vuelve el texto, no guarda nada en la cuenta',
  'pages/ResetPassword.jsx': 'cambiar la contraseña con el link del mail: antes de tener sesión',
  'pages/Login.jsx': 'entrar, crear la cuenta, «olvidé mi contraseña»: antes de tener sesión',
  'pages/VerifyEmail.jsx': 'verificar el mail: antes de tener sesión',
  'pages/ClaimAccount.jsx': 'reclamar una cuenta creada por un asesor: antes de tener sesión',
  'pages/AdvisorAccessRequest.jsx': 'responder el pedido de acceso de un asesor, con el link del mail',
  'pages/ReportPublic.jsx': 'el informe público por link: sin sesión',
  'pages/Landing.jsx': 'los números públicos de la portada: sin sesión',
}

describe('lo que sale sin pasar por utils/api', () => {
  it('el fetch directo es una lista cerrada, cada uno con su porqué', () => {
    const usan = new Set()
    for (const p of archivos()) {
      const r = rel(p)
      if (r === 'utils/api.js') continue
      const t = readFileSync(p, 'utf8').replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '')
      if (/\bfetch\s*\(|navigator\.sendBeacon|new\s+(XMLHttpRequest|EventSource|WebSocket)\b/.test(t)) usan.add(r)
    }
    expect([...usan].sort(), 'Esto habla con el servidor sin pasar por utils/api: no lo frena la pestaña '
      + 'desfasada ni lleva el cliente. Usá api.get/post/… (o, si de verdad no toca una cuenta, '
      + 'sumalo a FETCH_DIRECTO con su porqué).').toEqual(Object.keys(FETCH_DIRECTO).sort())
  })

  it('cada salida de utils/api pasa por el freno de la pestaña desfasada antes del fetch', () => {
    const t = readFileSync(join(SRC, 'utils/api.js'), 'utf8').replace(/\/\/.*$/gm, '')
    // Las funciones de arriba del archivo (async function x(…) { … }) que llaman a fetch.
    const sinFreno = []
    for (const m of t.matchAll(/^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(/gm)) {
      const cuerpo = t.slice(m.index, cierre(t, t.indexOf('{', m.index + m[0].length), '{', '}'))
      const iFetch = cuerpo.search(/\bfetch\s*\(/)
      if (iFetch < 0 || m[1] === 'withGatewayRetry') continue
      const iFreno = cuerpo.indexOf('await frenoDeLaPestana()')
      if (iFreno < 0 || iFreno > iFetch) sinFreno.push(m[1])
    }
    expect(sinFreno).toEqual([])
  })
})

describe('lo que la pantalla manda sola al servidor', () => {
  it('cada envío de la lista dice qué manda y por qué', () => {
    for (const [nombre, e] of Object.entries(ENVIOS)) {
      expect(['post', 'put', 'patch', 'delete'], `${nombre}: método`).toContain(e.metodo)
      expect(e.ruta, `${nombre}: ruta`).toMatch(/^\//)
      expect((e.porque || '').trim(), `${nombre}: falta el porqué`).not.toBe('')
    }
  })

  it('todo envío automático pasa por el freno del dueño, o dice por qué no lleva números de una cuenta', () => {
    const sinFreno = []
    for (const p of archivos()) {
      const r = rel(p)
      if (r === SALIDA || r === 'utils/api.js') continue
      for (const e of enviosAutomaticos(readFileSync(p, 'utf8'))) {
        if (e.via !== 'api') continue
        if (!LIBRES[`${r}|${e.ruta}`]) sinFreno.push(`${r} (${e.desde}): api.post/put… ${e.ruta}`)
      }
    }
    expect(sinFreno, 'Esto se manda solo al servidor sin el freno del dueño. Si lleva números '
      + 'calculados con los datos de una cuenta, sumalo a ENVIOS en utils/enviosConDueno.js y '
      + 'mandalo con enviarDe(envio, duenoDeLosDatos, …). Si no, agregalo a LIBRES con su porqué.')
      .toEqual([])
  })

  it('la lista LIBRES no guarda envíos que ya no existen', () => {
    const vivos = new Set()
    for (const p of archivos()) {
      for (const e of enviosAutomaticos(readFileSync(p, 'utf8'))) if (e.via === 'api') vivos.add(`${rel(p)}|${e.ruta}`)
    }
    expect(Object.keys(LIBRES).filter((k) => !vivos.has(k))).toEqual([])
  })

  // Nombran esas rutas sin mandarlas.
  const NO_MANDAN = {
    'utils/api.js': 'las lista entre las que no llevan el cliente de la pestaña',
    'utils/demo.js': 'es el servidor de mentira del modo demo: las CONTESTA',
  }

  it('las rutas que sólo salen solas no aparecen fuera de la salida con dueño', () => {
    const SOLO_SOLAS = [ENVIOS.fotoDelDia.ruta, ENVIOS.pnlNoRealizado.ruta]
    const afuera = []
    for (const p of archivos()) {
      const r = rel(p)
      if (r === SALIDA) continue
      const t = readFileSync(p, 'utf8')
      for (const ruta of SOLO_SOLAS) {
        const re = new RegExp(`['"\`]${ruta.replace(/\//g, '\\/')}['"\`]`)
        if (re.test(t) && !NO_MANDAN[r]) afuera.push(`${r}: ${ruta}`)
      }
    }
    expect(afuera).toEqual([])
  })

  it('el censo muerde: un envío nuevo en un efecto, o en lo que el efecto llama', () => {
    const directo = `useEffect(() => { api.post('/monthly/sync-unrealized', { pnl }) }, [])`
    expect(enviosAutomaticos(directo)).toEqual([{ via: 'api', ruta: '/monthly/sync-unrealized', desde: 'efecto' }])
    const indirecto = `
      async function cerrar(x) { await api.put(\`/monthly/\${x.id}\`, x) }
      const init = async () => { await cerrar(ultimo) }
      useEffect(() => { init() }, [])`
    expect(enviosAutomaticos(indirecto).map((e) => e.desde)).toEqual(['cerrar'])
    const conFreno = `setInterval(() => { enviarDe(ENVIOS.pnlNoRealizado, dueno, {}) }, 90000)`
    expect(enviosAutomaticos(conFreno)).toEqual([{ via: 'enviarDe', desde: 'efecto' }])
    const unClic = `const guardar = () => api.post('/monthly', form)`
    expect(enviosAutomaticos(unClic)).toEqual([])
  })
})
