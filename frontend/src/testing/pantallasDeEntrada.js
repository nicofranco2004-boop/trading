// pantallasDeEntrada — entrar a la app por las PANTALLAS de verdad, para las
// pruebas que atraviesan el camino de producción.
// ═══════════════════════════════════════════════════════════════════════════
// 🔴 POR QUÉ (re-test a ciegas 8, 31/10). La prueba al azar llamaba a la puerta
// de la sesión (AuthContext.entrar) directo, salteándose las pantallas: probaba
// la puerta, no que las pantallas la usaran. El auditor plantó en una copia una
// pantalla de entrada que no pasaba por ella —con un `entrar()` que nunca se
// ejecutaba, invisible para un guardián que busca textos— y volvió el síntoma
// con todas las pruebas en verde. Esto llena y manda el formulario de cada
// pantalla de entrada como lo hace el navegador (pages/Login, VerifyEmail,
// ResetPassword, ClaimAccount), y contesta como el servidor de verdad cada
// ruta de entrada: pone la cookie y devuelve lo mismo que devuelve main.py
// (restablecer NO devuelve el email).
//
// Lo usan pages/puertasDeEntrada.render.test.jsx y pages/sesionAlAzar.render.test.jsx.

/** Las rutas de las pantallas de entrada (las monta la prueba en su router). */
export const RUTAS_DE_ENTRADA = ['/login', '/verify-email', '/reset-password', '/claim']

/** Las pantallas de verdad, cargadas en ESTA carga de la página. */
export async function pantallasDeEntrada() {
  const [{ default: Login }, { default: VerifyEmail }, { default: ResetPassword }, { default: ClaimAccount }] = await Promise.all([
    import('../pages/Login'), import('../pages/VerifyEmail'), import('../pages/ResetPassword'), import('../pages/ClaimAccount'),
  ])
  return { '/login': Login, '/verify-email': VerifyEmail, '/reset-password': ResetPassword, '/claim': ClaimAccount }
}

/** Las rutas como App.jsx (Layout): las pantallas de entrada existen SÓLO sin
 *  usuario (con alguien adentro, o en el demo, la app no las dibuja). `Cuenta`:
 *  lo que la prueba muestra en el resto de las direcciones. `siempre`: las que
 *  App.jsx monta con y sin usuario ({ '/acceso': AdvisorAccessRequest }). */
export function rutasComoLaApp(h, RR, useAuth, pantallas, Cuenta, siempre = {}) {
  return function Rutas() {
    const { user } = useAuth()
    return h(RR.Routes, null,
      ...(user ? [] : RUTAS_DE_ENTRADA.map(r => h(RR.Route, { key: r, path: r, element: h(pantallas[r]) }))),
      ...Object.entries(siempre).map(([r, C]) => h(RR.Route, { key: r, path: r, element: h(C) })),
      h(RR.Route, { key: '*', path: '*', element: h(Cuenta) }))
  }
}

const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { 'content-type': 'application/json' } })

/** Lo que contesta el servidor a una ruta de entrada, o null si no es una.
 *  `srv.me` es la cookie del navegador; `porEmail` busca la cuenta.
 *  `srv.resetPara` / `srv.claimPara`: de quién es el link del mail.
 *  `srv.registroDirecto`: registrarse entra sin verificar el mail (el admin). */
export function contestarEntrada(srv, method, path, body, porEmail) {
  if (method !== 'POST' && !(method === 'GET' && path === '/auth/claim/preview')) return null
  if (path === '/auth/login') {
    const u = porEmail(body?.email); if (!u) return json({ detail: 'Credenciales inválidas' }, 401)
    srv.me = u; return json({ token: 't', name: u.name, is_admin: false })
  }
  if (path === '/auth/register') {
    if (srv.registroDirecto) { const u = porEmail(body?.email); srv.me = u; return json({ token: 't', name: u.name, is_admin: true }) }
    return json({ needs_verification: true, email: body?.email, message: 'Te enviamos un código' })
  }
  if (path === '/auth/verify-email') { const u = porEmail(body?.email); srv.me = u; return json({ token: 't', name: u.name, verified: true }) }
  if (path === '/auth/reset-password') { const u = srv.resetPara; srv.me = u; return json({ token: 't', name: u.name, message: 'Contraseña restablecida.' }) }
  if (path === '/auth/claim/preview') return json({ advisor_name: 'La Asesora', label: 'Cuenta X', email: srv.claimPara.email })
  if (path === '/auth/claim') { const u = srv.claimPara; srv.me = u; return json({ token: 't', name: u.name, email: u.email }) }
  if (path === '/auth/resend-verification' || path === '/auth/forgot-password') return json({ ok: true })
  return null
}

function nodos(raiz, pred) {
  const out = [], pila = [raiz]
  while (pila.length) { const n = pila.shift(); if (pred(n)) out.push(n); pila.push(...(n.childNodes || [])) }
  return out
}

/** Las puertas: ruta con que se abre la pantalla y cómo se llena. */
export const PUERTAS = {
  'iniciar sesión': { ruta: () => '/login', async llenar(t, u) {
    // Como lo tipea la persona: con mayúscula y un espacio de más.
    await t.escribir(t.input('email'), u.email.replace(/^./, c => c.toUpperCase()) + ' ')
    await t.escribir(t.input('password'), 'Password123$')
    await t.enviar()
  } },
  'registrarse y verificar el mail': { ruta: () => '/login?mode=register', async llenar(t, u) {
    await t.escribir(t.input('text'), u.name)
    await t.escribir(t.input('email'), u.email)
    await t.escribir(t.input('password'), 'Password123$xx')
    await t.enviar()
    if (!(await t.esperarQue(() => t.ruta() === '/verify-email'))) throw new Error('no llegó a verificar el mail: ' + t.texto().slice(0, 200))
    await t.quieta(100)
    const cajitas = t.inputs()
    for (let i = 0; i < 6; i++) await t.escribir(cajitas[i], String(i + 1))
    await t.quieta(50)
    await t.tocar('Confirmar')
  } },
  'registro directo (admin)': { ruta: () => '/login?mode=register', antes: (srv) => { srv.registroDirecto = true }, async llenar(t, u) {
    await t.escribir(t.input('text'), u.name)
    await t.escribir(t.input('email'), u.email)
    await t.escribir(t.input('password'), 'Password123$xx')
    await t.enviar()
  } },
  'reclamar una cuenta': { ruta: () => '/claim?token=c1', antes: (srv, u) => { srv.claimPara = u }, async llenar(t) {
    await t.esperarQue(() => t.formulario())
    const [p1, p2] = t.inputs().filter(n => ['password', 'text'].includes(n.atributos?.type))
    await t.escribir(p1, 'NuevaClave123$')
    await t.escribir(p2, 'NuevaClave123$')
    await t.enviar()
  } },
  'restablecer la contraseña': { ruta: () => '/reset-password?token=r1', antes: (srv, u) => { srv.resetPara = u }, async llenar(t) {
    const [p1, p2] = t.inputs().filter(n => ['password', 'text'].includes(n.atributos?.type))
    await t.escribir(p1, 'NuevaClave123$')
    await t.escribir(p2, 'NuevaClave123$')
    await t.enviar()
  } },
}

/** Entra como `u` por `puerta`: abre la pantalla (una carga nueva de la página),
 *  llena el formulario, lo manda y espera a que la app salga de las pantallas
 *  de entrada. Devuelve si salió.
 *  `ctx`: { cargar(ruta), cur() → { m, nav, ruta() }, srv, esperar(ms), quieta(ms) }. */
export async function entrarPorLaPantalla(puerta, u, ctx) {
  const p = PUERTAS[puerta]
  ctx.srv.registroDirecto = false
  p.antes?.(ctx.srv, u)
  await ctx.cargar(p.ruta())
  await ctx.quieta(150)
  const c = () => ctx.cur()
  const t = {
    inputs: () => nodos(c().m.contenedor, n => n.nodeName === 'INPUT'),
    input: (tipo) => t.inputs().find(n => n.atributos?.type === tipo),
    formulario: () => nodos(c().m.contenedor, n => n.nodeName === 'FORM')[0] || null,
    texto: () => c().nav.texto(c().m.contenedor),
    ruta: () => c().ruta(),
    escribir: (n, v) => c().nav.escribir(n, v),
    quieta: ctx.quieta,
    async esperarQue(fn, ms = 6000) {
      const t0 = Date.now()
      while (Date.now() - t0 < ms) { await ctx.quieta(25); if (fn()) return true }
      return false
    },
    async enviar() {
      const f = t.formulario()
      if (!f) throw new Error('no hay formulario en ' + t.ruta() + ': ' + t.texto().slice(0, 200))
      await c().nav.enActo(async () => {
        const ev = { type: 'submit', target: f, bubbles: true, cancelable: true, defaultPrevented: false, timeStamp: Date.now(),
          preventDefault() { this.defaultPrevented = true }, stopPropagation() {} }
        for (const fn of c().m.contenedor.escuchas.submit || []) fn(ev)
      })
    },
    async tocar(texto) {
      const b = c().nav.buscarBoton(c().m.contenedor, texto)
      if (b) await c().nav.enActo(() => c().nav.clic(c().m.contenedor, b))
    },
  }
  await p.llenar(t, u)
  return t.esperarQue(() => !RUTAS_DE_ENTRADA.includes(t.ruta()))
}
