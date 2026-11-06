import { writeFileSync } from 'node:fs'
import { abrirPestana, leerEnvios, marcasEn, contar, arrancar, navegar, cambiarParametros, cerrarPestana, volverConAtras, espera, intentosDeSalir, SALIDA_JSON, SIN_HISTORIAL, CON_CSP } from './banco.mjs'

// ── 5. Las situaciones ──────────────────────────────────────────────────────
// Cada una abre una pestaña nueva y repite lo que hace la app en producción.
// ❌ = el envío lleva algo que no tenía que salir (las «marcas» de banco.mjs: un
// ticker inventado, unos porcentajes, un token, un email, el nombre de un cliente).
const resultados = {}
async function situacion(clave, titulo, fn) {
  const pestanas = []
  await fn((p) => pestanas.push(p))
  const envios = leerEnvios(pestanas.flatMap((p) => p.anotados))
  resultados[clave] = { titulo, envios: envios.map((e) => ({ ...e, marcas: marcasEn(e) })) }
  contar(titulo, envios)
}

const SITIO = 'https://rendi.finance'
const CON_DATOS = '/analisis-tecnico?tab=backtesting&modo=cartera&origen=cero&activos=ZZPRIVADO,GGAL&pesos=73,27&anios=2'

console.log(CON_CSP ? '# Con la política de seguridad de la página (vercel.json) aplicada como el navegador' : '# Sin aplicar la política de seguridad de la página')
console.log(SIN_HISTORIAL
  ? '# Propiedad de Google con «cambios de página por el historial del navegador» APAGADO'
  : '# Propiedad de Google como está hoy (con «cambios de página por el historial del navegador» PRENDIDO)')

await situacion('A', 'A · Abrir (o recargar) una dirección con datos de la persona en los parámetros', async (usar) => {
  const p = await abrirPestana({ url: SITIO + CON_DATOS }); usar(p)
  await arrancar(p)
  await cerrarPestana(p)
})

await situacion('B', 'B · Entrar limpio, ir dentro de la app a esa dirección, cambiar un porcentaje, mandar un evento', async (usar) => {
  const p = await abrirPestana({ url: SITIO + '/analisis-tecnico?tab=grafico' }); usar(p)
  await arrancar(p)
  p.anotados.length = 0 // sólo lo que sale DESPUÉS de entrar limpio
  await navegar(p, '/analisis?tab=resumen')
  await navegar(p, CON_DATOS)
  await cambiarParametros(p, CON_DATOS.replace('73,27', '74,26'))
  p.w.__rendi.trackEvent('ai_chat_sent', { source: 'chat' })
  await espera(1500)
  await navegar(p, '/cartera?tab=resumen')
  await cerrarPestana(p)
})

await situacion('C', 'C · Recarga entera hacia una página limpia desde /login?email=… (la página anterior como la manda HOY el navegador)', async (usar) => {
  const p = await abrirPestana({ url: SITIO + '/', referrer: SITIO + '/login?email=ana.secreta%40example.com&next=%2Fcartera' }); usar(p)
  await arrancar(p, { conSesion: false })
  await cerrarPestana(p)
})

await situacion('C2', 'C2 · Lo mismo, con Referrer-Policy: strict-origin (el navegador dice sólo https://rendi.finance/)', async (usar) => {
  const p = await abrirPestana({ url: SITIO + '/', referrer: SITIO + '/' }); usar(p)
  await arrancar(p, { conSesion: false })
  await cerrarPestana(p)
})

await situacion('D', 'D · El informe público de un cliente (/i/<token>; el título nombra al cliente)', async (usar) => {
  const p = await abrirPestana({ url: SITIO + '/i/TOKENSECRETO123', titulo: 'Informe de cartera — Cliente Secreta' }); usar(p)
  await arrancar(p, { conSesion: false })
  await cerrarPestana(p)
})

await situacion('F', 'F · Registro: /login?mode=register → /verify-email?email=… → código → /onboarding', async (usar) => {
  const p = await abrirPestana({ url: SITIO + '/login?mode=register' }); usar(p)
  await arrancar(p, { conSesion: false })
  p.w.__rendi.trackMetaEvent('Lead', { content_name: 'signup_submitted' }) // Login.jsx al mandar el formulario
  await espera(300)
  await navegar(p, '/verify-email?email=ana.secreta%40example.com')
  await cambiarParametros(p, '/verify-email') // VerifyEmail saca el email de la dirección al montar
  p.w.__rendi.trackEvent('sign_up', { method: 'email' }) // AuthContext.login(…, 'sign_up')
  p.w.__rendi.trackMetaEvent('CompleteRegistration', { content_name: 'signup', status: true })
  await espera(800)
  await navegar(p, '/onboarding')
  await cerrarPestana(p)
})

await situacion('G', 'G · Entrar por una dirección con datos (?activo=…) y pasar a una limpia', async (usar) => {
  const p = await abrirPestana({ url: SITIO + '/analisis-tecnico?tab=grafico&activo=ZZPRIVADO' }); usar(p)
  await arrancar(p)
  await navegar(p, '/cartera?tab=resumen')
  await cerrarPestana(p)
})

await situacion('H', 'H · Llegar desde un anuncio (utm + fbclid + gclid): la atribución tiene que seguir llegando', async (usar) => {
  const p = await abrirPestana({ url: SITIO + '/?utm_source=instagram&utm_medium=paid&utm_campaign=lanzamiento&fbclid=IwAR0prueba&gclid=Cj0prueba' }); usar(p)
  await arrancar(p, { conSesion: false })
  await cerrarPestana(p)
  const fbc = /(?:^|; )_fbc=([^;]+)/.exec(p.w.document.cookie)
  console.log(`       cookie _fbc (el clic del anuncio de Meta, para atribuir la conversión): ${fbc ? fbc[1] : 'NO'}`)
})

await situacion('I', 'I · Ir a una dirección con datos, salir a otro sitio y volver con «Atrás» (página restaurada)', async (usar) => {
  const p = await abrirPestana({ url: SITIO + '/analisis?tab=resumen' }); usar(p)
  await arrancar(p)
  p.anotados.length = 0
  await navegar(p, CON_DATOS)
  await volverConAtras(p)
  await navegar(p, '/cartera?tab=resumen')
  await cerrarPestana(p)
})

await situacion('J', 'J · Llegar desde la app de Gmail en Android: Google tiene que seguir viendo de qué app vino', async (usar) => {
  const p = await abrirPestana({ url: SITIO + '/?utm_source=mail&utm_campaign=bienvenida', referrer: 'android-app://com.google.android.gm/' }); usar(p)
  await arrancar(p, { conSesion: false })
  await cerrarPestana(p)
})

const malos = Object.entries(resultados).map(([k, r]) => [k, r.envios.filter((e) => e.marcas.length).length])
console.log(`\nEnvíos con algo que no tenía que salir, por situación: ${malos.map(([k, n]) => `${k}=${n}`).join(' · ')}`)
console.log(`Intentos de salir a internet: ${intentosDeSalir.length}${intentosDeSalir.length ? ' → ' + [...new Set(intentosDeSalir)].join(', ') : ''}`)
if (SALIDA_JSON) writeFileSync(SALIDA_JSON, JSON.stringify({ sinHistorial: SIN_HISTORIAL, conCsp: CON_CSP, resultados, intentosDeSalir }, null, 2))
process.exit(0)
