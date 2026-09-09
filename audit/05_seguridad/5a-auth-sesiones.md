# 5a — Autenticación y sesiones

> Auditoría de seguridad · Tanda A · commit auditado **`b74f450f`** (copia limpia en `/tmp/rendi-main`,
> 1.126 archivos, `backend/main.py` con 38.029 líneas — verificado).
> Toda la superficie de este informe fue re-verificada contra **`origin/main` (`897b0d63`)**: los
> 12 hallazgos siguen vivos ahí, en las mismas líneas o a ±0.
> **Este documento no contiene ningún valor de secreto.**

## Punto de partida heredado (no se repite acá)

`audit/05_seguridad/5a-paso0-secret-key.md` ya dejó auditado y **no se re-audita**:

- `SECRET_KEY` firma los JWT con **HS256** (`main.py:115, 2689, 2704`) — simétrico: quien la tiene
  **fabrica** tokens, no sólo los lee.
- En **producción esa clave es una API key de Anthropic** (confirmado por el founder, §8-9 del paso 0).
  Severidad CRÍTICA, abierta.
- El claim `pca` es **opcional** en `get_current_user` (`main.py:2713-2716`), así que un token
  forjado lo omite y pasa. No hay `jti`, ni denylist, ni tabla de sesiones.
- El hardcodeo de `start-rendi.sh:43` + `.claude/settings.local.json:74` quedó re-calificado a **BAJO**
  (repo privado, prod usa otro valor).

Este informe sigue **desde ahí**, y su aporte principal es este: **el `pca` no sólo se puede omitir
forjando un token — el propio backend emite tokens sin `pca` a una parte de sus usuarios reales,
sin que intervenga ningún atacante** (H-1). Es decir, la única revocación que tiene el sistema está
apagada para esas cuentas incluso contra un atacante que sólo robó una cookie.

---

## Método

**MEDIDO** (ejecutado, traza pegada; scripts en `audit/_scripts/`, ninguno toca producción ni la red):

| script | qué mide |
|---|---|
| `medir_bcrypt_5a.py` | coste real de `pwd_ctx`, truncación a 72 bytes, tiempo por hash |
| `medir_timing_login_5a.py` | oráculo de timing existe/no-existe en `/api/auth/login` (n=30) |
| `medir_pca_revocacion_5a.py` | si el reseteo de contraseña mata las sesiones vivas — réplica **literal** de `main.py:2681-2689` y `2704-2718` contra SQLite en memoria con el esquema de `main.py:711-722` + la migración de `main.py:781-782` |
| `medir_ratelimit_5a.py` | réplica literal de `_check_rate_limit` (`main.py:395-411`) en tres escenarios |

Las versiones del entorno de medición **coinciden con `backend/requirements.txt`**:
`passlib 1.7.4`, `bcrypt 4.0.1` (líneas 7-8 del requirements).

**DEDUCIDO**: la cadena `X-Forwarded-For` real en producción (H-4), la latencia de Resend (H-8), el
comportamiento de `fbevents.js` (H-2). Supuestos declarados en cada hallazgo.

**ESTRUCTURAL**: ausencia de 2FA, de bloqueo de cuenta, de refresh, de revocación, de purga de tokens.
Cada uno verificado con grep sobre `b74f450f` **y** sobre `origin/main`.

**NO EJECUTADO**: ninguna petición a producción ni a `trading-production-143b.up.railway.app`; no
levanté el backend; no firmé ningún JWT con la clave real; no consulté la base de producción; no
miré Railway ni Vercel; no ejecuté ningún ataque contra nada.

---

## Resumen — hallazgos por severidad

| id | sev | título | archivo:línea | evidencia |
|---|---|---|---|---|
| H-1 | **ALTO** | El reseteo de contraseña NO desloguea al atacante en las cuentas creadas antes del 2026-05-07 | `main.py:782`, `2687`, `2716` | MEDIDO |
| H-2 | **ALTO** | El token de reseteo de contraseña se le manda a Facebook en cada apertura del link | `frontend/index.html:203`, `utils/metaPixel.js:114` | DEDUCIDO |
| H-3 | **ALTO** | El "rate limit por email" del login lleva la IP en la clave: no limita nada distribuido | `main.py:396-397`, `3192` | MEDIDO |
| H-4 | **ALTO** | Detrás del proxy de Vercel, todos los usuarios caen en un solo balde: 5 requests cierran el registro para todo el mundo | `main.py:373-387` + `frontend/vercel.json:6` | DEDUCIDO |
| H-5 | **MEDIO** | No existe forma de revocar una sesión: sin `jti`, sin denylist, y `logout` no toca el servidor | `main.py:163-164`, `3231-3238` | ESTRUCTURAL |
| H-6 | **MEDIO** | El token de reseteo NO es de un solo uso: falta el guard atómico que sí tiene `/api/auth/claim` | `main.py:3438-3448` vs `35135-35147` | ESTRUCTURAL |
| H-7 | **MEDIO** | `resend-verification`: el suffix del rate limit no normaliza el email → bombardeo de la casilla ajena desde una sola IP | `main.py:3340-3342` | MEDIDO |
| H-8 | **MEDIO** | Enumeración de usuarios en 3 endpoints: mensajes distintos y un oráculo de tiempo | `main.py:3155`, `3261`, `3350-3352`, `3395` | MEDIDO + DEDUCIDO |
| H-9 | **MEDIO** | bcrypt trunca a 72 bytes en silencio y el modelo valida 128 **caracteres** | `main.py:136`, `2863` | MEDIDO |
| H-10 | **MEDIO** | Sin 2FA, sin bloqueo de cuenta, sin política de complejidad más allá de 10 caracteres | `main.py:2874-2879` | ESTRUCTURAL |
| H-11 | **BAJO** | Los tokens de reseteo se guardan en claro y no se purgan nunca | `main.py:2108-2117` | ESTRUCTURAL |
| H-12 | **BAJO** | El JWT se devuelve además en el body, deshaciendo a medias el HttpOnly; y el email del admin está en claro en un comentario | `main.py:3222-3228`, `123-126` | ESTRUCTURAL |

Nada de lo que encontré en esta área llega a **CRÍTICO** por sí solo (ningún usuario cualquiera llega
a la cuenta de otro sin un paso previo). Lo CRÍTICO del área sigue siendo el `SECRET_KEY` del paso 0.

**Lo que está bien y conviene no romper**: `dummy_verify()` en el login cierra el oráculo de timing
(**MEDIDO**: +0,3 ms de diferencia); el OTP se compara con `hmac.compare_digest`; la cookie es
HttpOnly, `Secure` en prod, `SameSite=Lax`, sin `Domain` (host-only); CORS es una allowlist cerrada
con `allow_credentials`; el frontend ya no guarda el token en `localStorage`; borrar la cuenta sí
invalida el token de verdad; los endpoints admin listan columnas explícitas y nunca devuelven
`password_hash`; y `_ip_del_cliente` ya lee `X-Forwarded-For` **por la derecha**, que es la mitad
difícil del problema.

---

## Hallazgos

### [ALTO] H-1 · El reseteo de contraseña no desloguea al atacante en las cuentas viejas

**Evidencia:** MEDIDO
**Dónde:** `main.py:782` (la migración), `main.py:2687` (emisión), `main.py:2716` (verificación)

**Qué pasa.** La única revocación de sesión del sistema es el claim `pca`. Pero el claim **sólo se
agrega si el valor existe**:

```python
# main.py:2686-2687
if pw_changed_at:
    payload["pca"] = pw_changed_at
```

y **sólo se chequea si existe en los dos lados**:

```python
# main.py:2716
if pca and row["password_changed_at"] and pca != row["password_changed_at"]:
```

Ahora, la migración de SQLite (`main.py:781-782`):

```python
if user_cols and 'password_changed_at' not in user_cols:
    conn.execute("ALTER TABLE users ADD COLUMN password_changed_at TEXT")
```

**sin `DEFAULT`.** SQLite rellena con NULL. El `DEFAULT (datetime('now'))` está sólo en el
`CREATE TABLE` (`main.py:719`), que corre para bases nuevas, no para la que ya existía.

Resultado: **todo usuario cuya fila se creó antes de que se agregara la columna tiene
`password_changed_at = NULL`** → su login emite un JWT **sin `pca`** → cuando resetea la contraseña,
`pca` es `None`, el `if` corta en el primer término, y **el token viejo sigue valiendo hasta que
vence solo, 7 días después**.

`git log -S "password_changed_at" -- backend/main.py` fecha la introducción en **`28d080c6`,
2026-05-07**. Son las cuentas anteriores a esa fecha que nunca cambiaron la contraseña desde entonces.

**Traza (`audit/_scripts/medir_pca_revocacion_5a.py`)** — réplica literal de `create_token` y del
chequeo de `get_current_user`:

```
--- usuario NUEVO (pca poblado) ---
  password_changed_at al loguear : '2026-09-08 22:38:47'
  claim 'pca' en el JWT emitido  : '2026-09-08 22:38:47'
  antes del reseteo              : ACEPTADO
  DESPUES del reseteo            : 401 pca distinto

--- usuario LEGACY (pca NULL) ---
  password_changed_at al loguear : None
  claim 'pca' en el JWT emitido  : None
  antes del reseteo              : ACEPTADO
  DESPUES del reseteo            : ACEPTADO   <-- el token robado sigue sirviendo
```

**Cómo se explota en la práctica.** El escenario que el reseteo de contraseña existe para resolver:
la víctima nota que alguien entró a su cuenta y cambia la contraseña. En una cuenta vieja **eso no
hace nada**: el atacante que copió la cookie (o el `Authorization: Bearer`, que el backend acepta,
`main.py:2696-2699`) sigue leyendo la cartera completa hasta 7 días. La víctima cree que cerró la
puerta. Y no hay ninguna otra palanca: cambiar la contraseña otra vez tampoco sirve, porque el token
robado nunca llevó el claim.

**Qué queda expuesto.** La cartera, las operaciones, el patrimonio y las credenciales de broker
conectadas de esas cuentas, durante los 7 días posteriores a un reseteo que el usuario cree efectivo.

**Otros call sites del mismo patrón.** Los **6** sitios que emiten token pasan `password_changed_at`
tal como viene de la base, así que **todos** heredan el NULL: `main.py:3170` (register admin),
`3220` (login), `3323` (verify-email), `3454` (reset-password), `3587` (change-password),
`35162` (claim). El chequeo vive en **uno solo**, `main.py:2716`. No hay divergencia: hay un único
punto y está mal.

**Verificación asimétrica que conviene mirar:** el esquema Postgres **sí** tiene el DEFAULT en las dos
puntas (`schema_pg.sql:1725` en el `CREATE`, y `1760` en el `ALTER ... ADD COLUMN IF NOT EXISTS ...
DEFAULT`). O sea: el bug **existe sólo en SQLite**, que es lo que corre en producción. Si algún día se
migra a Postgres, se arregla por accidente y nadie va a entender por qué.

**Solución de fondo.** Dos cosas, en este orden:

1. Backfill: `UPDATE users SET password_changed_at = COALESCE(password_changed_at, created_at, datetime('now')) WHERE password_changed_at IS NULL;`
   Efecto: los tokens sin `pca` **siguen pasando** (el `if` mira el claim, no la columna), así que el
   backfill solo no arregla nada — hay que hacer el punto 2.
2. Invertir el fail-open de `main.py:2716`: **exigir** el claim. `if row["password_changed_at"] and
   payload.get("pca") != row["password_changed_at"]: 401`. Con el backfill hecho, esto invalida de
   una vez todos los tokens sin `pca` — incluidos los forjados que el paso 0 describe (§2), que hoy
   pasan por este mismo agujero. Es un deslogueo masivo puntual y es el precio correcto.
3. El fondo del fondo es H-5: mientras la revocación sea un string comparado dentro del token, no hay
   forma de matar **una** sesión.

**Medición pendiente para dimensionar el radio** (necesita la base, no la tengo):
`SELECT COUNT(*) FROM users WHERE password_changed_at IS NULL;`

---

### [ALTO] H-2 · El token de reseteo de contraseña se le manda a Facebook

**Evidencia:** DEDUCIDO (supuesto: `fbevents.js` incluye la URL completa —`dl`/`rl`— en cada evento,
que es su comportamiento documentado y el que el propio código del repo describe)
**Dónde:** `frontend/index.html:203` y `frontend/src/utils/metaPixel.js:114`

**Qué pasa.** El link del mail lleva el token en la query string:

```python
# main.py:3391
reset_url = f"{_frontend_url()}/reset-password?token={token}"
```

Una auditoría anterior ya encontró exactamente este problema y lo arregló — para otras tres rutas.
El comentario que dejó, en `metaPixel.js:111-113`, lo dice con todas las letras:

> `/i/:token` y `/claim` llevan secretos en la URL: fbevents manda la location completa a Facebook —
> el guard del index.html solo cubría la carga inicial, no la navegación SPA (audit de seguridad).

Y el guard, en los dos lugares, es:

```js
// frontend/index.html:203
if (!location.pathname.startsWith('/i/') && !location.pathname.startsWith('/claim') && !location.pathname.startsWith('/acceso')) {
  fbq('init', '1281911210681122'); fbq('track', 'PageView');
}
// frontend/src/utils/metaPixel.js:114
if (p.startsWith('/i/') || p.startsWith('/claim') || p.startsWith('/acceso')) return
```

**`/reset-password` no está en ninguna de las dos listas.** Es la ruta con token en la URL más vieja
y más usada de la app (`App.jsx:285`), y es la única que quedó afuera.

**Por qué Google sí está cubierto y Meta no.** `analytics.js:93` tiene la misma lista incompleta,
pero además una segunda defensa que la salva:

```js
// analytics.js:97-101
const u = new URL(loc)
if (u.searchParams.has('token')) { u.searchParams.delete('token'); loc = u.toString() }
```

El comentario la llama *"defensa extra si algún flujo lo agrega"*. Esa defensa extra es lo único que
impide que el token de reseteo llegue a GA4. **El Pixel de Meta no tiene equivalente**: se inicializa
en el `<head>` estático y `fbevents.js` arma el payload solo, leyendo `document.URL`. `Referrer-Policy:
strict-origin-when-cross-origin` (`vercel.json`) no ayuda: no es el Referer, es el propio parámetro
que el pixel manda.

**Cómo se explota en la práctica.** No hace falta un atacante externo: el token de reseteo **en vivo**
(TTL 30 min, `main.py:2914`) queda registrado en la cuenta de Meta Ads de Rendi y en los sistemas de
Meta. Cualquiera con acceso a esa cuenta de anuncios —hoy o después de un compromiso de la cuenta de
Meta— tiene, para cada usuario que abrió un link de reseteo en los últimos 30 minutos, la llave para
tomarle la cuenta. A eso se suma que el token queda en el historial del navegador y en cualquier log
de acceso que registre query strings (Vercel).

**Qué queda expuesto.** Toma de control de la cuenta (el reseteo, además, auto-loguea:
`main.py:3454-3459`) de cualquier usuario que haya pedido un reseteo, con una ventana de 30 minutos.

**Otros call sites del mismo patrón.** La lista de rutas sensibles está **duplicada en tres archivos**
y las tres copias están incompletas: `frontend/index.html:203`, `frontend/src/utils/metaPixel.js:114`,
`frontend/src/utils/analytics.js:93`. Una lista repetida tres veces es una lista que va a divergir —
y ya divergió: la de analytics tiene el fallback del `?token`, las otras dos no.

**Solución de fondo.**
1. Que el token no viaje en la query string: mandarlo en el fragmento (`#token=`, que el navegador
   nunca envía a un servidor ni un pixel ve como parte de `search`), o que la página lo saque de la
   URL con `history.replaceState` apenas lo lee (`ResetPassword.jsx:24` hoy lo deja ahí para siempre).
2. Unificar las tres listas en **una** constante exportada, y que el guard no sea una lista de rutas
   sino una regla sobre la URL: *si hay query string, no se reporta la location*.
3. El `?token=` también está en los tres endpoints de cron (`main.py:31567`, `33598`, `33666`:
   `request.query_params.get("token")`). Mismo problema de logging, distinto dueño — lo dejo señalado
   para el informe de configuración.

---

### [ALTO] H-3 · El "rate limit por email" del login no limita nada distribuido

**Evidencia:** MEDIDO
**Dónde:** `main.py:396-397` (la clave), `main.py:3190-3192` (el uso)

**Qué pasa.** El comentario del login promete exactamente lo contrario de lo que hace el código:

```python
# main.py:3190-3192
# Rate limit por IP y por email (mitiga brute-force distribuido sobre una cuenta puntual)
_check_rate_limit(request, max_calls=10, window_seconds=60, suffix="login_ip")
_check_rate_limit(request, max_calls=10, window_seconds=60, suffix=f"login_email:{email_norm}")
```

pero la clave del balde se arma así:

```python
# main.py:396-397
ip = _rate_limit_ip(request)
key = f"{ip}|{suffix}" if suffix else ip
```

**La IP entra en TODAS las claves**, incluida la que dice ser "por email". No existe ningún límite
por cuenta: existe un límite por *(IP, cuenta)*. Lo que el comentario dice mitigar —el ataque
distribuido contra una cuenta puntual— es justo el que no mitiga.

**Traza (`audit/_scripts/medir_ratelimit_5a.py`)**:

```
B) login — 'rate limit por email' contra un ataque distribuido
   intentos aceptados contra UNA cuenta en 60s desde 200 IPs: 200
   (max_calls=10 se aplica por (IP,email), no por email)
```

**Cómo se explota en la práctica.** Con un pool de IPs baratas (residenciales, o simplemente IPv6:
un /64 son 2⁶⁴ direcciones y el código las trata como distintas — `_es_ip_publica` usa `is_global`,
sin agrupar por prefijo), el atacante hace 10 intentos por IP y 200 IPs le dan 2.000 intentos por
minuto **contra una sola cuenta**, indefinidamente. No hay bloqueo de cuenta (H-10) ni 2FA, así que
el único freno es el coste de bcrypt (~176 ms, MEDIDO) — que además es un freno para el servidor, no
para el atacante.

**Qué queda expuesto.** Cualquier cuenta con contraseña débil o reutilizada. El mínimo son 10
caracteres (`main.py:2874-2879`), sin ninguna otra exigencia: `contraseña1` pasa.

**Otros call sites del mismo patrón.** **Todos** los limitadores "por sujeto" del archivo heredan el
mismo defecto, porque el defecto está en `_check_rate_limit`, no en los call sites. Son **31**
llamadas y las que llevan un identificador en el suffix creyendo que limitan por ese identificador
son al menos: `3192` (login_email), `3250` (verify_email), `3340-3341` (resend), `3368`
(forgot_pw_email), `25913`, `26192`, `26527`, `26665`, `27318`, `28226`, `28295`, `29318`, `29380`,
`31241`, `31281`, `31493`, `31535`, `34377`, `34696`, `35947`, `36296`. Las de `uid` importan menos
(el usuario ya está autenticado y no gana nada rotando IP contra su propia cuota… salvo la cuota de
IA, que **sí** se puede inflar rotando IP: `ai_chat:{uid}` a 12/min pasa a 12/min **por IP**).

**Solución de fondo.** Que `_check_rate_limit` acepte la clave completa en vez de anteponer la IP
siempre. Algo como `_check_rate_limit(request, ..., scope="email", key=email_norm)` donde `scope`
decide si la IP entra o no. Y que el balde por cuenta escale: 10/min, después 10/5min, después
10/hora — un techo plano por minuto es infinito en un día.

---

### [ALTO] H-4 · Detrás del proxy de Vercel, todos los usuarios comparten un solo balde

**Evidencia:** DEDUCIDO
**Supuestos:** (a) Vercel proxea server-side y su IP de salida es pública; (b) el borde de Railway
agrega esa IP al final de `X-Forwarded-For`; (c) `RENDI_TRUSTED_PROXY_HOPS` no está seteada (el paso 0
no la encontró en Railway y el default del código es el modo automático).
**Dónde:** `main.py:373-387` + `frontend/vercel.json:6`

**Qué pasa.** El frontend **no le pega al backend desde el navegador**: pega a rutas relativas y
Vercel reescribe server-side.

```json
// frontend/vercel.json:6
{ "source": "/api/(.*)", "destination": "https://trading-production-143b.up.railway.app/api/$1" }
```

Lo confirma el propio comentario del backend (`main.py:239-241`): *"el frontend web pega a rutas
relativas (/api/...) y Vercel proxea a Railway server-side, así que en prod el browser NUNCA cruza
origin"*.

Y `_ip_del_cliente` elige, en modo automático, **la entrada más a la derecha que sea pública**:

```python
# main.py:381-384
for p in reversed(parts):
    if _es_ip_publica(p):
        return p
```

Si el borde de Railway agrega la IP de salida de Vercel (pública) al final de la cadena, **la última
pública es Vercel**, no el usuario. El comentario de la función ya anticipa este fracaso —
*"Con hops mal puesto todos los usuarios caerían en el mismo balde y se rate-limitearían entre
ellos —peor que el agujero—"*— pero el modo automático puede caer en él sin que nadie ponga nada mal.

**Cómo se explota en la práctica.** Tres consecuencias, de peor a menos peor:

1. **Cierre del registro para todo el mundo, con 1 request por minuto.** `register` limita 5/5min por
   IP (`main.py:3102`). Si todos los usuarios web comparten la IP de Vercel, el atacante gasta el
   balde entrando por `https://rendi.finance/api/auth/register` y **ningún visitante puede
   registrarse**. Traza del script:
   ```
   C) si _ip_del_cliente devuelve la IP del proxy (mismo balde para todos)
      tras 5 registros del atacante, un usuario legitimo: 429 (registro cerrado para todos)
   ```
   Lo mismo con `forgot_pw_ip` (5/5min, `main.py:3366`): nadie puede recuperar su contraseña.
   Y con `login_ip` (10/60s, `main.py:3191`): el login de toda la base se cae con 10 requests por minuto.
2. **El aviso de "nuevo inicio de sesión" miente.** `_client_ip` usa la misma función
   (`main.py:2980`) y el mail le muestra al usuario la IP de Vercel. Un login desde otro país se ve
   igual que uno propio: la alerta de seguridad queda sin contenido.
3. **El atacante se saca el rate limit de encima gratis**: pegándole directo al dominio de Railway
   (público, y listado en el `connect-src` del CSP de `vercel.json`), su IP sí es la última pública y
   tiene su propio balde, sin competir con nadie.

**Qué queda expuesto.** No hay filtración de datos: es disponibilidad (denegación de servicio del
funnel completo — registro, login y recuperación — al coste de un request por minuto) más la
inutilidad del aviso de dispositivo nuevo.

**Otros call sites del mismo patrón.** Uno solo, y es el correcto: las **31** llamadas a
`_check_rate_limit`, `_rate_limit_ip` (`main.py:391`) y `_client_ip` (`main.py:2975-2981`) pasan
todas por `_ip_del_cliente`. La consolidación previa está bien hecha; lo que falta es confirmar el
valor.

**Cómo confirmarlo en 10 segundos, sin tocar nada.** El código ya trae el diagnóstico:
`GET /api/admin/diag/client-ip` (`main.py:15980-16003`), logueado como admin, devuelve la cadena
cruda y la IP elegida. **Si `ip_elegida` no es la IP pública de quien abre el endpoint, el hallazgo
está confirmado** y la corrección es setear `RENDI_TRUSTED_PROXY_HOPS` al número que indique el campo
`pos_desde_la_derecha` de la fila correcta.

**Solución de fondo.** El modo automático apuesta a que el último salto público es el cliente. Detrás
de dos proxies encadenados (Vercel → Railway) esa apuesta es falsa y el default no puede saberlo.
Lo correcto es medir una vez con el endpoint de diagnóstico y **fijar los hops**, y —para que no
vuelva a quedar en modo adivinanza— que el backend loguee al bootear qué modo está usando y qué IP
dedujo del primer request real.

---

### [MEDIO] H-5 · No hay forma de revocar una sesión, y `logout` no toca el servidor

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:163-164`, `3231-3238`, `2681-2689`

**Qué pasa.**

```python
# main.py:163-164
def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")

# main.py:3231-3238
@app.post("/api/auth/logout")
def logout(response: Response):
    """Borra la cookie de auth. Para clientes que usan Bearer header, esto es
    no-op server-side (el token sigue vigente hasta exp) — ..."""
    clear_auth_cookie(response)
    return {"ok": True}
```

El docstring es honesto. El JWT no lleva `jti` (`main.py:2682-2686`: sólo `sub`, `iat`, `exp`), no
existe tabla de sesiones (grep de `sessions`, `jti`, `denylist`, `revoked_token`: **0** resultados) y
`get_current_user` no consulta nada más que `users` (`main.py:2709-2712`).

**Sobre el refresh: no existe.** Verificado con grep: los **6** sitios que llaman `create_token`
(`3170, 3220, 3323, 3454, 3587, 35162`) son registro, login, verificación de email, reseteo, cambio
de contraseña y claim. **No hay endpoint de refresh, ni renovación deslizante, ni re-emisión por
actividad.** El token vive exactamente `TOKEN_DAYS = 7` (`main.py:116`) y la cookie caduca junto con
él (`max_age=TOKEN_DAYS * 86400`, `main.py:155`). A los 7 días el usuario se cae de la sesión sin
aviso, en medio de lo que esté haciendo.

**Cómo se explota en la práctica.** Un token filtrado una sola vez —de un log de proxy, del body de
la respuesta de login (H-12), de una máquina compartida— vale 7 días completos y **no hay ninguna
acción que el usuario o el admin puedan tomar para matarlo**, salvo cambiar la contraseña, que no
funciona en las cuentas viejas (H-1). El botón "Cerrar sesión" no cierra nada del lado del servidor:
si el atacante ya se copió la cookie, apretarlo no le quita nada.

**Qué queda expuesto.** El control del alcance temporal de cualquier compromiso de sesión.

**Cosas que SÍ invalidan, para no exagerar el hallazgo:** cerrar la cuenta invalida de verdad
(`DELETE FROM users` en `main.py:3876` hace que `get_current_user` no encuentre la fila y devuelva
401 — el comentario de `main.py:3932` dice *"invalida la sesión server-side"* atribuyéndoselo a
`clear_auth_cookie`, que no es lo que lo hace, pero el efecto final es correcto). Y `approved` **ya
no bloquea nada**: el gate se removió del login (`main.py:3202-3204`) y la columna quedó en 1 para
todos por compatibilidad — así que "desaprobar" a un usuario **no le corta el acceso**, ni con token
viejo ni con login nuevo. Los `UPDATE users SET approved=...` que quedan (`main.py:788, 916, 20154,
35156`) sólo mueven un flag que nadie consulta para autorizar.

**Solución de fondo.** `jti` aleatorio en el payload + una tabla `revoked_tokens(jti, exp)` que
`get_current_user` consulte (la consulta a `users` ya se hace en cada request: el coste marginal es
un índice más). Con eso, `logout` revoca de verdad, el reseteo revoca todas las sesiones menos la
nueva, y el admin puede echar a alguien sin rotar `SECRET_KEY` — que hoy es la única revocación
global que existe, y desloguea a los 1.084 usuarios de una.

---

### [MEDIO] H-6 · El token de reseteo no es de un solo uso — y el guard correcto ya existe, 31.700 líneas más abajo

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:3421-3448` (roto) vs `main.py:35135-35147` (correcto)

**Qué pasa.** `reset_password` hace SELECT, decide, y después escribe:

```python
# main.py:3421-3428
row = conn.execute("""SELECT id, user_id, expires_at, used_at FROM password_reset_tokens
                      WHERE token = ?""", (data.token,)).fetchone()
if not row or row["used_at"]:
    raise HTTPException(400, "Link inválido o ya usado. Pedí uno nuevo.")
...
# main.py:3438-3448
new_hash = pwd_ctx.hash(data.new_password)          # ← ~176 ms de bcrypt ENTRE el chequeo y la escritura
with conn:
    conn.execute("UPDATE users SET password_hash = ?, password_changed_at = datetime('now') WHERE id = ?", ...)
    conn.execute("UPDATE password_reset_tokens SET used_at = datetime('now') WHERE id = ?", (row["id"],))
```

Entre el `if row["used_at"]` y el `UPDATE ... SET used_at` hay una ventana, y el hash de bcrypt la
ensancha a ~176 ms **medidos**. Dos requests con el mismo token que entren en esa ventana pasan los
dos: el `UPDATE` no lleva `AND used_at IS NULL` y nadie mira el `rowcount`.

**Y el arreglo ya está escrito en este mismo archivo.** `/api/auth/claim` —cuyo docstring dice
literalmente *"Mismo patrón que reset-password"* (`main.py:35108-35109`)— hace lo correcto:

```python
# main.py:35135-35147
# Cerramos el token PRIMERO y sólo seguimos si nosotros lo cerramos
# (rowcount==1). Dos claims concurrentes del mismo link (ej. alguien
# interceptó el email) corren esta transacción en paralelo — sin el
# WHERE used_at IS NULL + chequeo de rowcount, ambas pasarían el
# SELECT de arriba antes de que cualquiera lo marcara usado, y la
# segunda pisaría la contraseña que puso la primera.
cur = conn.execute(
    "UPDATE advisor_claim_tokens SET used_at=datetime('now') WHERE id=? AND used_at IS NULL",
    (row["id"],))
if cur.rowcount != 1:
    raise HTTPException(400, "Link inválido o ya usado. ...")
```

El comentario describe **el bug de reset-password**, palabra por palabra, incluido el desenlace
("la segunda pisaría la contraseña que puso la primera"). Se arregló en el call site nuevo (F4a,
julio 2026) y **nunca se propagó hacia atrás al original**, que es el que usan todos los usuarios.
Es el patrón de causa raíz que este proyecto ya tiene documentado 28 veces.

**Cómo se explota en la práctica.** Requiere tener el token, así que no es una entrada por sí sola.
Vale como capa: si el atacante lo obtuvo (H-2, un mail reenviado, una regla de forwarding en el
buzón de la víctima), la carrera le permite quedarse con la contraseña final aunque la víctima use
el link "primero" — y la víctima ve el reseteo exitoso y se queda tranquila.

**Otros call sites del mismo patrón.** Cuatro tablas de token de un solo uso; **una** tiene el guard:

| tabla | endpoint | `WHERE used_at IS NULL` + rowcount |
|---|---|---|
| `advisor_claim_tokens` | `main.py:35135-35147` | **sí** |
| `password_reset_tokens` | `main.py:3438-3448` | **no** |
| `email_verification_codes` | `main.py:3283-3292` | **no** |
| `advisor_link_requests` | `main.py:35034-35058` | pendiente de revisar (es del área de autorización) |

**Solución de fondo.** Copiar el guard de `claim` a los otros dos, y —el fondo real— extraer un
`_consumir_token_de_un_uso(conn, tabla, token) -> row | None` que haga el `UPDATE ... RETURNING`
condicional en un solo lugar. Cuatro tablas con la misma semántica y cuatro implementaciones es la
garantía de que la quinta también nazca rota.

---

### [MEDIO] H-7 · Bombardeo de la casilla de un tercero desde una sola IP

**Evidencia:** MEDIDO
**Dónde:** `main.py:3340-3342`

**Qué pasa.** El limitador se arma con el email **sin normalizar**, y el lookup con el email
**normalizado**:

```python
# main.py:3340-3342
_check_rate_limit(request, max_calls=1, window_seconds=60, suffix=f"resend:{data.email.lower()}")
_check_rate_limit(request, max_calls=5, window_seconds=3600, suffix=f"resend_hourly:{data.email.lower()}")
email_norm = data.email.strip().lower()          # ← el .strip() está acá, no en el suffix
```

`ResendVerificationIn` (`main.py:2897-2898`) sólo valida `max_length=254`: **no hay validador de
email, no hay strip**. Así que `" victima@gmail.com"`, `"  victima@gmail.com"`, `"victima@gmail.com "`
son tres claves de rate limit distintas y **el mismo usuario** para el `SELECT ... WHERE email=?`.

**Traza (`audit/_scripts/medir_ratelimit_5a.py`)**:

```
A) resend-verification — 1 IP, limite 1/60s por email
   emails enviados a la MISMA casilla en el mismo minuto: 9/10
```

(10 variantes de padding, una repetida — 9 distintas, 9 emails.)

**Cómo se explota en la práctica.** El endpoint es **público, sin autenticación**, y los dos límites
que tiene son por email: **no hay ninguno por IP sola**. Con espacios, tabs y saltos de línea el
espacio de claves es ilimitado, y cada acierto dispara un `httpx.post` a Resend
(`billing/emails.py:148-155`). Un atacante con una IP y un bucle manda miles de mails a la casilla de
la víctima. El daño no es sólo a la víctima: el que se quema es **el dominio remitente de Rendi**.
Cuando Resend suspende la cuenta por abuso, se caen a la vez la verificación de email, el reseteo de
contraseña, los avisos de login nuevo y todo el mail transaccional.

**Qué queda expuesto.** La entregabilidad de todo el correo del producto, y con ella el registro y la
recuperación de contraseña.

**Otros call sites del mismo patrón.** Es una asimetría de **1 entre 4**, lo que la hace un descuido
y no una decisión: `login_email` (`3192`), `verify_email` (`3250`) y `forgot_pw_email` (`3368`) usan
todos `email_norm` (ya `.strip().lower()`). Sólo `resend` usa `data.email.lower()` crudo, **dos veces**.

**Solución de fondo.** Normalizar en el **modelo**, no en el endpoint: `ResendVerificationIn`,
`LoginIn` y `ForgotPasswordIn` no tienen `field_validator` de email; `RegisterIn` sí
(`main.py:2866-2872`). Un validador compartido en un `EmailIn(BaseModel)` base hace que ningún
endpoint futuro pueda volver a equivocarse. Y agregar un límite por IP sola a `resend-verification`,
que hoy no tiene ninguno.

---

### [MEDIO] H-8 · Enumeración de usuarios: tres oráculos, y el cuidado del cuarto no sirve de nada

**Evidencia:** MEDIDO (login) + ESTRUCTURAL (mensajes) + DEDUCIDO (timing de forgot-password)

**Lo que está BIEN — el login no filtra.** `main.py:3194-3199` llama `pwd_ctx.dummy_verify()` cuando
el email no existe, para igualar el tiempo. Funciona:

```
n=30
email NO existe (dummy_verify): mediana 176.0 ms  min 175.1  max 352.7
email SI existe (verify real) : mediana 176.2 ms  min 175.4  max 180.7
delta mediana: +0.3 ms
```

Y devuelve el mismo `401 "Credenciales inválidas"` en los dos casos. El `403 EMAIL_NOT_VERIFIED`
(`main.py:3200-3206`) sólo se alcanza **después** de verificar la contraseña, así que tampoco filtra.
Correcto, y conviene no tocarlo.

**Lo que está mal — cuatro sitios que sí filtran:**

1. **`register` lo dice explícitamente** (`main.py:3151-3157`):
   ```python
   raise HTTPException(409, {"code": "EMAIL_ALREADY_REGISTERED",
                             "error": "Este email ya está registrado.", "email": data.email})
   ```
   Es un oráculo perfecto, sin autenticación, limitado a 5/5min por IP. **Es deliberado** (el
   comentario lo justifica: *"para que el frontend pueda ofrecer un botón 'Ir al login'"*), así que
   va como decisión de producto — pero hay que sacar la conclusión: **mientras esto exista, el
   mensaje genérico de `forgot-password` no protege nada**. Se está pagando el coste de UX de un
   mensaje ambiguo ("Si la cuenta existe…") sin obtener el beneficio.

2. **`resend-verification` devuelve dos textos distintos** (`main.py:3350-3352`):
   ```python
   if not user or user["email_verified"]:
       return {"sent": True, "message": "Si la cuenta existe, te enviamos un código nuevo."}
   _send_verification_email(...)
   return {"sent": True, "message": "Te enviamos un código nuevo."}
   ```
   El comentario dice *"Respuesta genérica para no leakear si el email existe"* y la respuesta de al
   lado no es genérica. Distingue tres estados: no existe / existe verificado / **existe sin verificar**.

3. **`verify-email` confirma cuentas verificadas** (`main.py:3260-3261`): con cualquier código de 6
   dígitos, un email registrado y verificado devuelve `400 "Tu cuenta ya está verificada. Iniciá
   sesión."`, contra `400 "Código inválido o expirado"` para los demás.

4. **`forgot-password` filtra por tiempo** (DEDUCIDO). El texto es genérico, pero el camino no:

   ```python
   # main.py:3374-3402
   if user:
       ... 2 escrituras en password_reset_tokens ...
       emails.send_password_reset(...)     # billing/emails.py:148-155 → httpx.post(..., timeout=10.0) SÍNCRONO
   return {"sent": True, "message": "Si la cuenta existe, ..."}
   ```

   Si el email existe, el request **bloquea** en un POST a `api.resend.com` (cientos de ms, hasta 10 s
   de timeout). Si no existe, vuelve de inmediato. La diferencia no es un side-channel de microsegundos:
   es visible con un cronómetro.

   **Y el arreglo también existe ya en el archivo.** `register` mueve exactamente ese envío a un
   `BackgroundTask` (`main.py:3159-3164`), con el comentario *"el envío del email (httpx a Resend,
   hasta 10s) va a un BackgroundTask para que register() responda al instante"*. Se hizo por
   velocidad de funnel, cierra el oráculo de paso, y **no se propagó** a `forgot-password` ni a
   `resend-verification`, que son los dos endpoints donde el oráculo importa.

**Cómo se explota en la práctica.** Un atacante confirma qué direcciones de una lista tienen cuenta
en Rendi. Eso solo ya es un dato sensible (identifica a alguien como inversor con cartera declarada,
insumo para phishing dirigido: *"tu cartera de Rendi tuvo un movimiento"*), y es la lista de entrada
para H-3.

**Solución de fondo.** Decidir de una: o el registro también responde genérico y se acepta el coste
de UX, o se asume que el padrón de emails es público y se deja de pagar por ocultarlo. Y con
independencia de eso, mover los tres envíos de mail a `BackgroundTask` — está bien por latencia
aunque la enumeración se decida ignorar.

---

### [MEDIO] H-9 · bcrypt trunca a 72 bytes en silencio y el modelo valida 128 *caracteres*

**Evidencia:** MEDIDO
**Dónde:** `main.py:136`, `main.py:2863` / `2874-2879`

**Qué pasa.** El contexto es el de siempre y no configura nada:

```python
# main.py:136
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
```

Medido con las versiones exactas de `requirements.txt` (`passlib 1.7.4`, `bcrypt 4.0.1`):

```
hash prefix/coste : $2b$12$ | len: 60          ← bcrypt, coste 12, salt de 22 chars por hash
hash de 88 bytes  : OK (no lanza)
verify(72 bytes  , hash de 88 bytes) -> True   ← contraseña DISTINTA, verifica igual
verify(otro >72  , hash de 88 bytes) -> True   ← cualquier cosa que comparta los primeros 72 bytes
40 x 'n-tilde' =  40 chars / 80 bytes
tiempo medio hash : 176 ms
```

Lo bueno: bcrypt `$2b$`, coste **12** (el default de passlib, razonable para 2026), salt aleatorio
por hash, comparación en tiempo constante dentro de `bcrypt.checkpw`. No se loguea ni se devuelve
nunca el hash: los **6** usos de `password_hash` (`main.py:3114, 3198, 3441, 3573-3574, 3579, 34396,
35156`) son INSERT, verify o UPDATE, y los endpoints admin listan columnas explícitas —
`admin_billing_inspect` incluso lo comenta (`main.py:19557`: *"columnas de tier + crédito (sin
password_hash)"*). El único `SELECT * FROM users` (`main.py:3194`) es el del login y no devuelve la
fila.

Lo malo: **passlib trunca a 72 bytes sin avisar** (`truncate_error` no está seteado, o sea `False`).
Y el límite del modelo está en **caracteres**, no en bytes:

```python
# main.py:2863
password: str = Field(..., min_length=10, max_length=128)
```

Una contraseña de 40 caracteres acentuados son 80 bytes en UTF-8 — pasa el `max_length=128` y bcrypt
le corta los últimos 8. En español eso no es un caso de laboratorio.

**Cómo se explota en la práctica.** No es una entrada directa: hay que probar contraseñas igual. El
daño es que **la entropía que el usuario cree tener por encima de los 72 bytes no existe**. Alguien
que usa una passphrase larga generada por un gestor de contraseñas cree tener 100 caracteres de
seguridad y tiene 72 bytes. En combinación con H-3 (fuerza bruta distribuida sin techo por cuenta),
lo que se pierde es justamente el margen del que dependen los usuarios más cuidadosos.

**Otros call sites del mismo patrón.** Los **5** sitios que hashean usan el mismo `pwd_ctx` y ninguno
mide bytes: `main.py:3106` (register), `3438` (reset), `3577` (change-password), `34393` (shadow del
asesor — `token_urlsafe(24)` = 32 bytes, dentro del límite), `35134` (claim). El límite en caracteres
se repite en **4** modelos: `RegisterIn:2863`, `ChangePasswordIn:2889`, `ResetPasswordIn:2907`,
`ClaimAccountIn:35103`.

**Nota aparte, misma línea 136:** `deprecated="auto"` con un solo esquema no hace nada, y
`pwd_ctx.needs_update()` **no se llama en ningún lado** (grep: 0 resultados). Si algún día se agrega
argon2 al principio de la lista, los hashes existentes no se van a migrar nunca al loguear, que es el
único momento en que se puede.

**Solución de fondo.** Validar `len(v.encode('utf-8')) <= 72` en un validador compartido y decírselo
al usuario, o pasar a **argon2id** (que no tiene el límite) con `deprecated=["bcrypt"]` y un
`needs_update` en el login para migrar los hashes a medida que la gente entra.

---

### [MEDIO] H-10 · Sin 2FA, sin bloqueo de cuenta, y la política de contraseñas es "10 caracteres"

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:2874-2879`

```python
@field_validator('password')
def password_strength(cls, v):
    if len(v) < 10:
        raise ValueError('La contraseña debe tener al menos 10 caracteres')
    return v
```

Eso es toda la política. `contraseña1`, `1234567890` y `rendi12345` pasan. No hay chequeo contra una
lista de contraseñas comunes ni contra el email del usuario, y no hay medidor de fuerza que obligue.

Greps que vuelven **vacíos** en `b74f450f` y en `origin/main`:

| busqué | resultados |
|---|---|
| `totp`, `two.factor`, `2fa`, `mfa`, `authenticator` | **0** |
| `failed_attempts`, `lockout`, `locked_until`, `intentos_fallidos` | **0** |
| `jti`, `denylist`, `revoked_token`, tabla `sessions` | **0** |

**No hay segundo factor de ningún tipo** —ni TOTP, ni código por mail en el login, ni WebAuthn— y
**no hay bloqueo de cuenta tras N intentos fallidos**. La única contención de fuerza bruta es el rate
limit, que H-3 muestra que no limita por cuenta y H-4 que probablemente ni siquiera limita por IP
correctamente.

**Qué queda expuesto.** La única barrera entre un atacante y la cartera completa de un usuario es una
contraseña que puede tener 10 caracteres, contra un atacante sin techo de intentos por cuenta. Para
un producto que muestra el patrimonio declarado de sus usuarios, eso es poco.

**Contrapeso, para ser justos.** Sí existe **detección de dispositivo nuevo con aviso por mail**
(`_record_login_and_maybe_alert`, `main.py:2984-3029`): guarda `login_history` con el hash del
User-Agent y manda un mail si el `ua_hash` no se vio antes. Es la pieza correcta y está bien pensada
(hashea el UA para no exponerlo si se filtra la base, y no avisa en el primer login para no ensuciar
el signup). Sus dos límites: el `ua_hash` es un fingerprint trivialmente clonable —el atacante que
copia el User-Agent de la víctima no dispara nada— y la IP que le muestra al usuario es la que H-4
pone en duda. **El mail de aviso es hoy la única señal que el usuario tiene de una intrusión, y no
viene con ninguna acción posible: no hay "cerrar todas las sesiones" (H-5).**

**Solución de fondo.** En orden de retorno por esfuerzo: (1) bloqueo progresivo por cuenta —el mismo
cambio de clave que pide H-3—, (2) rechazo de las 10.000 contraseñas más comunes, que es una lista
estática y 5 líneas, (3) TOTP opcional. La (1) y la (2) son de esta semana; la (3) puede esperar.

---

### [BAJO] H-11 · Tokens de reseteo en claro, y nadie los borra nunca

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:2108-2117`

```sql
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token TEXT NOT NULL UNIQUE,       -- ← el token EN CLARO
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

**La entropía está bien**: `secrets.token_urlsafe(32)` (`main.py:2943-2945`) son 256 bits de un CSPRNG,
imposibles de adivinar. El TTL son 30 minutos (`PASSWORD_RESET_TTL_MINUTES = 30`, `main.py:2914`) y
**sí se invalidan los tokens anteriores al pedir uno nuevo** (`main.py:3382-3386`: `UPDATE ... SET
used_at WHERE user_id = ? AND used_at IS NULL`) — un solo link vivo por usuario, correcto.

Lo que falta: el token se guarda tal cual, no un hash. Quien lea la base (un backup en S3, el volumen
de Railway, un `read_db` de más) puede usar cualquier token de los últimos 30 minutos para tomar una
cuenta. Y **no hay ninguna purga**: grep de `DELETE FROM password_reset_tokens` y de
`DELETE FROM email_verification_codes` devuelve **0**. Las filas se acumulan para siempre; sólo
`DELETE /api/me` las limpia, y sólo las del usuario que se va.

**Solución de fondo.** Guardar `sha256(token)` y buscar por el hash — el token en claro sólo existe en
el mail, que es donde tiene que estar. Es el mismo cambio de 4 líneas en las cuatro tablas de token
del H-6. Y un borrado de lo vencido en el cron que ya corre a diario.

---

### [BAJO] H-12 · El JWT también viaja en el body, y el email del admin está en un comentario

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:3222-3228`, `main.py:123-126`, `912-916`

**(a) El token en el body.** La cookie es HttpOnly precisamente para que un XSS no la lea
(`main.py:141-144`), pero los **4** endpoints que la setean devuelven **además** el token en el JSON:
login (`main.py:3222`), verify-email (`3325`), reset-password (`3456`), claim (`35164`). El comentario
lo justifica por compatibilidad (*"clientes legacy / mobile"*) y el frontend ya no lo usa
(`utils/api.js:15` borra el `rendi_token` de `localStorage` como legacy). Mientras siga ahí, el token
pasa por cualquier cosa que registre cuerpos de respuesta y queda al alcance de un XSS que ocurra
durante el login. Con H-5 (sin revocación) y H-1, cada copia extra dura 7 días.

Relacionado: `bearer = HTTPBearer(auto_error=False)` (`main.py:139`) y el fallback de
`main.py:2696-2699` hacen que **el header `Authorization` valga tanto como la cookie**. Eso es lo que
convierte "robé una cookie" en "tengo una sesión desde `curl`, sin navegador" — y es también lo que
hace que `SameSite=Lax` no sea una defensa contra un token ya filtrado, sólo contra CSRF.

**(b) El email del admin, en claro, al lado del hash que lo esconde.**

```python
# main.py:123-126
# Admin gating ─ el email del admin no se guarda en plano. Comparamos hash SHA-256 + HMAC.
# El email real es nicofranco2004@gmail.com pero solo se sabe por el hash. ...
_ADMIN_EMAIL_HASH = "3dace40c..."
```

El comentario que explica que el email no está en claro escribe el email en claro. El mecanismo en sí
está bien hecho (`_is_admin_email` usa `hmac.compare_digest`, `main.py:132-134`), pero no protege nada.

Lo que importa de verdad no es el email: es **qué hace el sistema con él**. En cada boot,
`init_db()` recorre la tabla entera y promueve:

```python
# main.py:912-916
rows = conn.execute("SELECT id, email FROM users").fetchall()
for r in rows:
    if _is_admin_email(r["email"]):
        conn.execute("UPDATE users SET is_admin=1, approved=1 WHERE id=?", (r["id"],))
```

O sea: **el admin es quien tenga esa dirección de email en la tabla `users`**, evaluado en cada
arranque. Hoy no es explotable porque la cuenta existe y `users.email` es UNIQUE. Pero si esa cuenta
se cerrara alguna vez (`DELETE /api/me`, `main.py:3807`), la dirección queda libre y **el siguiente
que la registre se convierte en admin en el próximo deploy** — sobre 47 endpoints `/api/admin`. Con
el email publicado en un comentario del código, el único obstáculo es controlar el buzón para el OTP.

**Solución de fondo.** (a) Dejar de devolver el token en el body, o dejar de aceptar el header Bearer:
las dos cosas juntas anulan buena parte del beneficio del HttpOnly. (b) Que `is_admin` deje de
derivarse del email en cada boot: es un flag de la base, y un email no debería poder cambiar un rol.
Sacar el email del comentario es cosmético al lado de eso.

---

## Lo que NO pude verificar (dicho explícitamente)

1. **Cuántos usuarios tienen `password_changed_at IS NULL`** — decide el radio de H-1. Necesita la
   base: `SELECT COUNT(*) FROM users WHERE password_changed_at IS NULL;`. No consulté producción.
2. **Qué `X-Forwarded-For` llega realmente a la app en Railway** — decide H-4 entero. No hice ninguna
   petición a producción. Se resuelve en 10 segundos con `GET /api/admin/diag/client-ip`
   (`main.py:15980`), logueado como admin, mirando si `ip_elegida` es la IP pública de quien lo abre.
3. **Si `RENDI_TRUSTED_PROXY_HOPS` está seteada en Railway** — el paso 0 dejó pendiente la revisión de
   variables. Asumí que no (el default del código es el modo automático).
4. **Qué manda exactamente `fbevents.js` en cada evento** (H-2). No cargué el pixel ni intercepté una
   petición a Facebook. El supuesto es su comportamiento documentado, y coincide con lo que afirma el
   comentario del propio repo (`metaPixel.js:111-113`), escrito por una auditoría anterior que sí lo
   verificó para las otras rutas.
5. **La latencia real de Resend** (H-8, punto 4). Medí que la llamada es síncrona y bloqueante
   (`billing/emails.py:148-155`, `timeout=10.0`); no medí cuánto tarda, porque eso implicaba mandar
   un mail de verdad.
6. **Que el aviso de dispositivo nuevo llegue** (H-10). Leí el código; no disparé ningún envío.
7. **Autorización** — quién puede ver los datos de quién una vez autenticado (`get_effective_user`,
   `X-Rendi-Client-Id`, los 47 endpoints `/api/admin`, `advisor_link_requests`) **no es de este
   informe**. Sólo dejé señalado lo que toca sesiones: que `approved` ya no bloquea nada (H-5) y que
   el rol de admin se re-deriva del email en cada boot (H-12b).
8. **Las 173 cláusulas `except Exception as e`** que el paso 0 dejó abiertas (§8) — si alguna filtra
   un `str(e)` con datos de sesión al usuario. Es el punto 10 de la Tanda B.

## Cruce con la tanda de fixes F1

Ninguno. Los archivos de F1 (`snapshots_job.py`, persister de FX, `reconcile-cash`, `CashFlowIn`,
recalc de P&L, amortización manual, `SellModal`/`PositionsMobile`) no aparecen en ningún hallazgo de
este informe.
