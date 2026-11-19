// 🔴 TODA LECTURA DE LA PANTALLA TIENE RESPUESTA EN EL DEMO (o un porqué escrito).
//
// POR QUÉ (19/11/2026). El análisis técnico creció en octubre —Panorama, Tu
// lista, Señales de la semana, la radiografía de la Cartera— y nadie le escribió
// al demo su respuesta: en el demo cada una decía «No pudimos cargar…», que es
// lo que ve quien llega de un anuncio. No lo vio ninguna prueba: la del demo
// (utils/demoPlomeria.test.js) revisa una lista de rutas escrita a mano en
// septiembre, y lo que se agregó después no estaba en la lista. Ésta no tiene
// lista de rutas: recorre el código de la pantalla.
//
// La regla: cada `api.get('/…')` —y cada lectura que va por POST
// (utils/api `esLecturaPorPost`)— la contesta el demo: su simulador
// (utils/demo `handleDemoRequest`) o el servidor por la puerta del demo
// (`rutaDelDemoEnElServidor`, backend/main.py «La puerta del demo»). Si no la
// contesta, en el demo esa pantalla muestra un error. Lo que hoy no tiene
// respuesta está abajo con su porqué: una lectura NUEVA sin respuesta pone esto
// en rojo, y una de la lista que empieza a tenerla también (se saca de la lista
// en el mismo cambio, para que la lista diga siempre la verdad).
//
// Lo que no ve, dicho:
//   · una ruta guardada en una variable (`api.get(url)`): mira las escritas en
//     el llamado;
//   · cada `${…}` se prueba con 'X': una regla del demo que mire ese valor puede
//     dar «sin respuesta» de más (hoy no pasa con ninguna de la lista);
//   · que la respuesta tenga la FORMA que lee la pantalla: eso lo miran las
//     pruebas de cada pantalla y utils/demoPlomeria.test.js.
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { handleDemoRequest, rutaDelDemoEnElServidor } from '../utils/demo'
import { esLecturaPorPost } from '../utils/api'

const SRC = join(__dirname, '..')

// Lo que el demo no pide nunca: pantallas a las que el visitante no entra, o
// lecturas que la pantalla saltea en el demo. No hace falta contestarlas.
const FUERA_DEL_DEMO = [
  [/^\/admin\//, 'el panel del administrador: el usuario del demo no es administrador'],
  [/^\/advisor\//, 'el Plan Asesor: el usuario del demo no es asesor'],
  [/^\/iol\/lab\//, 'el laboratorio de IOL (/lab/iol, escondido): sólo para las cuentas habilitadas '
    + '(backend `_iol_lab_gate`), y el usuario del demo no lo está'],
  [/^\/auth\/me$/, 'AuthContext no la pide en el demo: arma el usuario del demo sin preguntar'],
  [/^\/preferencias\/modo-rendimiento$/, 'ModoRendimientoContext no la pide en el demo: sin persona '
    + 'logueada ni la lee ni la guarda (la elección queda en el navegador)'],
  [/^\/billing\/preview-change-plan$/, 'Planes no la pide en el demo: cambiar de plan lleva a crear la '
    + 'cuenta (`desdeElDemoACrearCuenta`), como «Suscribirme»'],
]

// Lecturas que el demo todavía no contesta: la pantalla muestra su error o se
// queda sin esa parte. Vacía desde el 19/11/2026: las 18 que encontró esta
// prueba al escribirse tienen respuesta (utils/demo.js) o están arriba, en
// FUERA_DEL_DEMO, con su porqué. Una que se anote acá lleva qué ve el visitante.
const SIN_RESPUESTA = {}

function archivos(dir = SRC, out = []) {
  for (const n of readdirSync(dir)) {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) {
      if (n === '__guards__' || n === 'testing' || n === '__design__') continue
      archivos(p, out)
    } else if (/\.(js|jsx)$/.test(n) && !/\.test\.|\.spec\./.test(n)) out.push(p)
  }
  return out
}

/** Las lecturas que hace la pantalla: [{ metodo, ruta (con 'X' en cada ${…}), donde }]. */
function lecturas() {
  const out = []
  for (const p of archivos()) {
    const t = readFileSync(p, 'utf8')
    for (const m of t.matchAll(/\bapi\.(get|post)\(\s*(['"`])((?:(?!\2).)*)\2/g)) {
      const metodo = m[1].toUpperCase()
      const ruta = m[3].replace(/\$\{[^}]*\}/g, 'X')
      if (!ruta.startsWith('/')) continue
      if (metodo === 'POST' && !esLecturaPorPost('POST', ruta)) continue
      out.push({ metodo, ruta, donde: relative(SRC, p) })
    }
  }
  return out
}

function laContesta(metodo, ruta) {
  if (rutaDelDemoEnElServidor(metodo, ruta)) return true
  try {
    return handleDemoRequest(metodo, ruta, {}) != null
  } catch {
    return true   // contesta con un error propio (una acción que el demo no deja)
  }
}

describe('el demo contesta todo lo que lee la pantalla', () => {
  const todas = lecturas()

  it('el instrumento ve las lecturas (si no ve ninguna, no prueba nada)', () => {
    expect(todas.length).toBeGreaterThan(200)
    // Las del análisis técnico, que fueron las que se escaparon.
    for (const r of ['GET /tus-senales', 'POST /tecnico/lista', 'POST /tecnico/cartera', 'GET /termometro']) {
      expect(todas.some(x => `${x.metodo} ${x.ruta}` === r), r).toBe(true)
    }
  })

  it('cada una tiene respuesta, o está en la lista con su porqué', () => {
    const sin = new Set()
    for (const { metodo, ruta } of todas) {
      if (FUERA_DEL_DEMO.some(([re]) => re.test(ruta.split('?')[0]))) continue
      if (!laContesta(metodo, ruta)) sin.add(`${metodo} ${ruta}`)
    }
    const nuevas = [...sin].filter(k => !(k in SIN_RESPUESTA))
    expect(nuevas, 'lecturas nuevas sin respuesta en el demo: contestalas en utils/demo.js '
      + '(o mandalas a la puerta del demo del servidor), o anotalas en SIN_RESPUESTA con su porqué').toEqual([])
    const yaContestadas = Object.keys(SIN_RESPUESTA).filter(k => !sin.has(k))
    expect(yaContestadas, 'ya tienen respuesta: sacalas de SIN_RESPUESTA').toEqual([])
  })

  it('el análisis técnico lo arma el servidor, con el mismo motor que una cuenta', () => {
    for (const [metodo, ruta] of [['GET', '/tecnico/NVDA?moneda=usd'], ['GET', '/tecnico/NVDA/horas?cada=1h'],
      ['GET', '/tecnico/NVDA/hoy'], ['GET', '/tecnico/NVDA/peso'], ['GET', '/tecnico/NVDA/eventos'],
      ['GET', '/tecnico/NVDA/backtest?reglas=rsi'], ['POST', '/tecnico/lista'], ['POST', '/tecnico/cartera'],
      ['POST', '/tecnico/en-fechas'], ['GET', '/tus-senales'], ['GET', '/backtest/cartera/hoy'],
      ['GET', '/comparar/precio?activos=NVDA'], ['GET', '/termometro'], ['GET', '/liquidez/GGAL']]) {
      expect(rutaDelDemoEnElServidor(metodo, ruta), ruta).toBe(`/demo${ruta}`)
    }
    // Lo que es de cada persona, no: los dibujos, las líneas, el resumen de
    // Mervall-E y cómo te llega el de los sábados.
    for (const [metodo, ruta] of [['GET', '/tecnico/NVDA/dibujos?moneda=usd'], ['PUT', '/tecnico/NVDA/dibujos'],
      ['GET', '/tecnico/NVDA/lineas'], ['POST', '/tecnico/NVDA/resumen'], ['PUT', '/tus-senales/canal']]) {
      expect(rutaDelDemoEnElServidor(metodo, ruta), ruta).toBeNull()
    }
  })

  it('lo del mercado lo contesta el servidor; lo de la persona, el demo', () => {
    for (const ruta of ['/fci/catalog', '/cedears', '/pf/banks', '/bond-indices/CER',
      '/dividendos/historial?tickers=AAPL%2CMSFT', '/tickers/search?q=intel']) {
      expect(rutaDelDemoEnElServidor('GET', ruta), ruta).toBe(`/demo${ruta}`)
    }
    // Los «No lo cobré», las tesis, los cobros: son de cada persona.
    for (const ruta of ['/dividendos/salteados', '/tesis', '/cobros', '/primeros-pasos', '/alerts/lineas',
      '/positions/regla-de-venta', '/positions/group/context?broker=Schwab&asset=NVDA']) {
      expect(rutaDelDemoEnElServidor('GET', ruta), ruta).toBeNull()
    }
  })
})
