// 🔴 CENSO DE LO QUE LA APP GUARDA EN EL NAVEGADOR.
//
// Toda escritura en localStorage / sessionStorage del frontend (cada
// `.setItem(clave, …)`) tiene que estar acá, en UNA de estas listas, con su
// porqué:
//
//   · CON_DUENO — lleva datos de una cuenta y su clave es de la persona Y de la
//     cuenta: pasa por la regla única, utils/duenoDeLaPestana. El guardián lo
//     verifica: el archivo usa la regla (o el ayudante que dice `via`, y ese
//     ayudante la usa).
//   · DUENO_PROPIO — lleva datos de una persona con un dueño propio, anterior a
//     la regla y con su prueba. Lista cerrada: no se suma nada sin unificarlo.
//   · SIN_DATOS_DE_CUENTA — preferencias de pantalla o de la máquina, ayudas, o
//     la mecánica de la sesión misma: no muestran ni suben datos de una cuenta.
//
// POR QUÉ EXISTE (re-test a ciegas, 30/10). Las copias del navegador decidían
// su dueño cada una por su cuenta: los dibujos del gráfico por activo, la foto
// del día y la tanda del asesor por nadie, los números «que cambian» por cuenta
// y no por persona, el «desde tu última visita» y las tarjetas descartadas por
// persona y no por cuenta. Con una sesión que VENCE (api.js con un 401 sólo
// borra `rendi_user`) o con el asesor cambiando de cliente, la pantalla de uno
// arrancaba de lo que había dejado otro. Se arregló con la regla única, pero
// nada obligaba a una clave NUEVA a pasar por ella: las dos últimas se
// escaparon del primer arreglo. Este censo es esa obligación: una escritura
// nueva sin clasificar, o una clasificada que ya no existe, da rojo.
//
// Cómo leerlo: la clave es `archivo|expresión` — lo que va como primer
// argumento de `.setItem(` en ese archivo, tal cual (sin espacios de más).
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC = join(__dirname, '..')

const CON_DUENO = {
  'pages/AdvisorImports.jsx|k': { via: 'duenoDeLaPestana', porque: 'la última tanda del asesor, con nombres de clientes' },
  'pages/Dashboard.jsx|key': { via: 'claveFotoDeHoy', porque: '«ya guardé la foto de hoy»: si no es de la cuenta, el cliente 3 se queda sin la suya' },
  'utils/cambioDeMovimiento.js|clave': { via: 'duenoDeLaPestana', porque: 'el último total visto y los cambios de Movimientos (montos)' },
  'utils/valoresVistos.js|k': { via: 'duenoDeLaPestana', porque: 'el «antes» de los números que cambian (montos)' },
  'hooks/useLastVisit.js|LS_PREFIX + keyRef.current': { via: 'useDuenoDeLaPestana', porque: '«desde tu última visita»: el valor de la cartera y los hallazgos' },
  'hooks/useDescartesDelDiagnostico.js|PREFIJO + dueno': { via: 'useDuenoDeLaPestana', porque: 'las tarjetas del diagnóstico que se descartaron' },
}

const DUENO_PROPIO = {
  'utils/chatSession.js|clave': 'la conversación con la IA: adoptarConversaciones anota de quién es (rendi_chat_dueno) y la borra si entra otra persona (contexts/sesionEnOtraPestana.test.js, fotoDeOtraCuenta.test.js)',
  'utils/chatSession.js|DUENO_KEY': 'el dueño de esas conversaciones (la persona, con utils/quienEs)',
  'utils/instalarApp.js|CLAVE_AVISADA': 'guarda la persona a la que ya se le avisó al servidor que instaló la app; si entra otra, no coincide y se avisa de nuevo',
}

const SIN_DATOS_DE_CUENTA = {
  // La sesión misma: de acá sale el dueño, no es un dato de una cuenta.
  'contexts/AuthContext.jsx|\'rendi_user\'': 'quién está logueado (el nombre y el email de la propia persona)',
  'components/ErrorBoundary.jsx|\'rendi_user\'': 'restaura la sesión de la misma persona al reintentar',
  'utils/api.js|CLIENT_CTX_KEY': 'qué cliente tiene abierto el asesor: es la cuenta del dueño; la borran login() y logout()',
  'hooks/usePlanFeatures.js|LS_KEY': 'el plan, sólo para no parpadear al cargar; se vuelve a pedir en cada login, /auth/me y cambio de cliente',
  // Preferencias de pantalla o de la máquina.
  'contexts/ThemeContext.jsx|\'rendi_theme\'': 'tema claro u oscuro',
  'contexts/CurrencyContext.jsx|STORAGE_KEY': 'moneda en que se mira',
  'contexts/CurrencyContext.jsx|VAL_STORAGE_KEY': 'qué dólar se usa para mirar',
  'contexts/CurrencyContext.jsx|CB_STORAGE_KEY': 'costo a hoy o a la compra',
  'contexts/PrivacyContext.jsx|STORAGE_KEY': '«Ocultar saldos» prendido o apagado',
  'contexts/ModoRendimientoContext.jsx|STORAGE_KEY': 'cómo se mide el rendimiento (además se guarda en la cuenta)',
  'contexts/VozContext.jsx|k': 'la velocidad y las banderas de la voz',
  'components/Sidebar.jsx|LS_KEY': 'barra lateral plegada',
  'components/Sidebar.jsx|LS_PIE': 'pie de la barra lateral plegado',
  'components/operations/CobrosView.jsx|\'rendi_cobros_vista\'': 'cómo se ve la lista de cobros',
  'pages/Operations.jsx|\'rendi_operations_tab\'': 'la pestaña elegida en Movimientos',
  'pages/Operations.jsx|\'rendi_trades_group\'': 'cómo se agrupan las operaciones',
  'pages/Operations.jsx|\'rendi_movements_group\'': 'cómo se agrupan los movimientos',
  'pages/Positions.jsx|\'rendi_pos_density\'': 'densidad de la tabla de la cartera',
  'pages/Positions.jsx|\'rendi_cuentas_separadas\'': 'qué brokers se ven separados: sólo filtra los brokers de quien mira, no muestra los de otro',
  'pages/PositionsMobile.jsx|\'rendi_cuentas_separadas\'': 'ídem, en el celular',
  'pages/Insights.jsx|\'rendi_insights_bench_usd\'': 'contra qué índice se compara en dólares',
  'pages/Insights.jsx|\'rendi_insights_bench_ars\'': 'contra qué índice se compara en pesos',
  'hooks/useArrastrable.js|clave': 'dónde quedó una ventana arrastrable, mientras dure la pestaña',
  // Ayudas y primeros pasos: a lo sumo una ayuda de más o de menos; no muestran datos.
  'components/ai/AIDiscoveryBanner.jsx|AI_DISCOVERY_KEY': 'ya conoció la IA',
  'components/ai/mervalle/estadoDelChat.js|CLAVE_SALUDO': 'el saludo del día de Mervall-E ya se dio',
  'components/tour/pasos.js|CLAVE_VISTO': 'ya vio el recorrido de novedades',
  'components/home/OnboardingChecklist.jsx|OMITIDOS_KEY': 'pasos de la lista de inicio que se omitieron',
  'components/home/OnboardingChecklist.jsx|CHECKLIST_DISMISSED_KEY': 'la lista de inicio se cerró',
  'components/onboarding/PositionStep.jsx|\'rendi_onboarding_pending\'': 'volver a la bienvenida después de cargar',
  'pages/Onboarding.jsx|ONBOARDING_SKIPPED_KEY': 'se salteó la bienvenida',
  'pages/Onboarding.jsx|ONBOARDING_COMPLETED_KEY': 'se completó la bienvenida',
  'pages/Config.jsx|FIRST_IMPORT_FLAG': 'ya importó alguna vez (para la primera lectura)',
  'pages/Imports.jsx|FIRST_IMPORT_FLAG': 'ídem, al importar',
  'utils/positionsDiscovered.js|POSITIONS_DISCOVERED_KEY': 'ya conoció la cartera',
  'pages/PositionsMobile.jsx|PISTA_SCROLL_KEY': 'ya vio la pista de deslizar la cartera',
  // Mecánica de la página y del navegador.
  'main.jsx|KEY': 'cuándo se recargó por una versión nueva (para no recargar en bucle)',
  'utils/autoUpdate.js|\'rendi_update_guard\'': 'ídem, la guarda de la actualización automática',
  'utils/origen.js|ORIGEN_KEY': 'de dónde llegó este navegador (atribución del registro)',
  'utils/demo.js|DEMO_FLAG_KEY': 'el modo demo está prendido',
  'utils/demo.js|DEMO_OVERLAY_KEY': 'el cartel del demo se cerró',
  'pages/AdvisorAccessRequest.jsx|TOKEN_KEY': 'el link de pedido de vínculo abierto en esta pestaña; lo responde quien esté logueado y lo valida el servidor',
}

// Los archivos de la app (sin pruebas ni ayudas de prueba).
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

// El primer argumento de cada `.setItem(`: lo que hay hasta la primera coma de
// su mismo nivel (respeta paréntesis, corchetes, llaves y textos entre comillas).
function escrituras(texto) {
  const out = []
  let i = texto.indexOf('.setItem(')
  while (i !== -1) {
    let j = i + '.setItem('.length, nivel = 0, comilla = null, arg = ''
    for (; j < texto.length; j++) {
      const c = texto[j]
      if (comilla) {
        arg += c
        if (c === '\\') { arg += texto[++j]; continue }
        if (c === comilla) comilla = null
        continue
      }
      if (c === '\'' || c === '"' || c === '`') { comilla = c; arg += c; continue }
      if ('([{'.includes(c)) nivel++
      if (')]}'.includes(c)) { if (nivel === 0) break; nivel-- }
      if (c === ',' && nivel === 0) break
      arg += c
    }
    out.push(arg.replace(/\s+/g, ' ').trim())
    i = texto.indexOf('.setItem(', j)
  }
  return out
}

function censo() {
  const vistas = new Map()   // id → texto del archivo
  for (const p of archivos()) {
    const texto = readFileSync(p, 'utf8')
    const rel = relative(SRC, p).split('\\').join('/')
    for (const arg of escrituras(texto)) vistas.set(`${rel}|${arg}`, texto)
  }
  return vistas
}

const LISTAS = { ...CON_DUENO, ...DUENO_PROPIO, ...SIN_DATOS_DE_CUENTA }

describe('censo de lo que la app guarda en el navegador', () => {
  const vistas = censo()

  it('toda escritura nueva está clasificada, con su porqué', () => {
    const sinClasificar = [...vistas.keys()].filter(id => !(id in LISTAS)).sort()
    expect(sinClasificar, 'Estas escrituras en el navegador no están en el censo. Si guardan '
      + 'algo de UNA cuenta (montos, nombres, lo que la persona hizo), la clave tiene que salir '
      + 'de utils/duenoDeLaPestana y van en CON_DUENO; si son una preferencia de pantalla o de la '
      + 'máquina, en SIN_DATOS_DE_CUENTA, con su porqué.').toEqual([])
  })

  it('no hay entradas de escrituras que ya no existen', () => {
    expect(Object.keys(LISTAS).filter(id => !vistas.has(id)).sort()).toEqual([])
  })

  it('ninguna está en dos listas', () => {
    const repetidas = Object.keys(CON_DUENO).filter(id => id in DUENO_PROPIO || id in SIN_DATOS_DE_CUENTA)
      .concat(Object.keys(DUENO_PROPIO).filter(id => id in SIN_DATOS_DE_CUENTA))
    expect(repetidas).toEqual([])
  })

  it('las que dicen tener dueño usan la regla de verdad', () => {
    const fuentes = archivos().map(p => readFileSync(p, 'utf8'))
    for (const [id, { via }] of Object.entries(CON_DUENO)) {
      const texto = vistas.get(id)
      if (texto == null) continue          // lo informa la prueba de arriba
      expect(texto, `${id} no usa ${via}`).toContain(via)
      if (!/duenoDeLaPestana/i.test(via)) {
        // Un ayudante (p. ej. claveFotoDeHoy): el archivo que lo define usa la regla.
        const def = fuentes.find(f => new RegExp(`export (function|const) ${via}\\b`).test(f))
        expect(def, `no encontré dónde se define ${via}`).toBeTruthy()
        expect(def, `${via} no usa duenoDeLaPestana`).toContain('duenoDeLaPestana')
      }
    }
  })

  it('cada entrada dice por qué', () => {
    for (const [id, v] of Object.entries(LISTAS)) {
      const porque = typeof v === 'string' ? v : v.porque
      expect((porque || '').trim(), `${id}: falta el porqué`).not.toBe('')
    }
  })
})
