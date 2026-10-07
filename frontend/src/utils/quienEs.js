// quienEs — LA regla de "quién es la persona logueada", para todo lo que la
// pestaña guarda o compara por persona: la lectura de la cartera y la
// conversación de Mervall-E (VozContext), tus activos del buscador ⌘K y el
// aviso de "otra pestaña cambió de cuenta" (AuthContext). null = sin sesión.
//
// Es el EMAIL, y no `user.id`, porque el usuario de la app no trae `id`:
// AuthContext.mapMeToUser arma el usuario con lo que manda /auth/me y ése no
// lo copia. Dos veces se armó una clave con `user.id` y las dos quedó vacía
// —o igual para todos— en las cuentas de verdad: la lectura de la cartera
// (auditoría 2026-10-05: el siguiente en la pestaña veía la del anterior) y
// el buscador (2026-10-07: nunca pedía tus activos). En el demo andaba porque
// su usuario estaba escrito a mano con `id: 0`.
//
// Y el email está SIEMPRE, también antes de que conteste /auth/me: al abrir la
// app se usa la sesión guardada en el navegador, que tiene el email, y si
// /auth/me no contesta (un corte de red) se sigue con ésa.
//
// En minúsculas y sin espacios: al iniciar sesión el email provisorio es el
// que se tipeó ("Ana@X.com ") y después llega el de /auth/me ("ana@x.com").
// El servidor lo guarda así y no deja dos cuentas con el mismo.
export const quienEs = (user) => String(user?.email ?? '').trim().toLowerCase() || null
