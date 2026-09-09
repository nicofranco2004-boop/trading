# Qué queda por hacer del audit de seguridad — verificado el 2026-09-09

> Método: no me creí ni el informe ni la memoria. Fui hallazgo por hallazgo **al código de hoy**
> (`origin/main` = `8b3956ba`) y verifiqué si el arreglo está o no está. Los números de línea del
> audit original son de `b74f450f` y **ya no sirven** (el archivo se movió ~700 líneas); acá van
> las líneas de hoy.
>
> Donde no llegué a mirar el código lo digo explícitamente: dice `(sin re-verificar)`.

---

## Lo primero: de todo el audit, se cerró UNA cosa

**Cerrado y verificado en producción:** la `SECRET_KEY` dejó de ser la API key de Anthropic, y las
credenciales de broker pasaron a cifrarse con su propia clave (`CREDENTIALS_KEY`). Commits
`56c26782`, `4d990810`, `363db686`, `3b1cf95b`. La rotación se ejecutó el 2026-09-08 y quedó
verificada en los logs de arranque. Era el hallazgo más grave de todos.

**Falso positivo que se puede tachar:** el audit decía que `schema_pg.sql` declara `users.email`
sin `UNIQUE` y que eso permitiría dos cuentas con el mismo email en Postgres. **No es cierto.** El
`UNIQUE (email)` está al final del mismo `CREATE TABLE` (`backend/schema_pg.sql:1745`); el agente
miró sólo las primeras líneas de la tabla y no llegó al constraint. Además producción sigue en
SQLite, así que ese archivo hoy ni corre.

**Todo lo demás sigue exactamente como lo dejó el audit.** Los commits que hubo desde entonces
(`f900d5bd`, `53b90dfd`, la tanda del CER, los de cripto) no tocaron ninguno de estos hallazgos.

---

## Los 7 de "antes de que entre un usuario más"

| # | qué | estado | dónde está hoy |
|---|---|---|---|
| 1 | Borrar el webhook de Mercado Pago | 🔴 abierto | `backend/main.py:28140` |
| 2 | El cambio de contraseña no echa al intruso en las cuentas viejas | 🔴 abierto | `backend/main.py:913` y `2849` |
| 3 | Los 4 endpoints de cron: comparación insegura, token por URL, aceptan GET | 🔴 abierto | `main.py:32394, 34450, 34507, 34796` |
| 4 | Borrar una alerta resetea el estado de las alertas **ajenas** | 🔴 abierto | `backend/main.py:34432` |
| 5 | Los 31 límites "por email"/"por usuario" son en realidad por IP | 🔴 abierto | `backend/main.py:396` |
| 6 | Rotar la `SECRET_KEY` | ✅ **hecho** | — |
| 7 | Sacar `/reset-password` del camino del pixel de Facebook | 🔴 abierto | `frontend/src/utils/metaPixel.js:115` y `frontend/index.html:209` |

### 1 · El webhook de Mercado Pago sigue armado
`@app.post("/api/billing/webhook")` sigue existiendo. Es la única puerta del sistema que le
contesta a cualquiera sin pedirle identificación, y sirve a un proveedor de pagos que ya no se usa.
El audit lo bajó a severidad BAJA (no hay ninguna variable `MP_` en Railway), pero **se borra
igual**: no cuesta nada y elimina la categoría entera.

### 2 · Cambiar la contraseña no invalida el token robado, en las cuentas viejas
La columna `password_changed_at` se agregó con `ALTER TABLE ... ADD COLUMN password_changed_at TEXT`
(`main.py:913`), **sin valor por defecto**. Las cuentas anteriores al 2026-05-07 la tienen vacía →
sus sesiones se firman sin la marca → y el chequeo `if pca and row["password_changed_at"]`
(`main.py:2849`) se saltea entero. Para esas cuentas, cambiar la contraseña **no echa a nadie**
durante 7 días. No hace falta que un atacante haga nada raro: el backend emite tokens que él mismo
no puede revocar.

**Cuando se arregle, los usuarios lo notan: van a tener que iniciar sesión de nuevo, una vez.**

### 3 · Los 4 crons
Los cuatro (`/api/iol/lab/run-cron`, `/api/alerts/evaluate`, `/api/snapshots/run-cron`,
`/api/advisor/brief/run-cron`) siguen con los tres problemas juntos:
- comparan el token con `!=` en vez de `hmac.compare_digest` (el `!=` corta apenas encuentra la
  primera letra distinta, y ese tiempo de más se puede medir para adivinar el token letra por letra);
- lo aceptan por `?token=` en la URL (que queda escrito en los logs de todos los proxies del camino);
- contestan a GET, así que cualquiera que consiga el link lo dispara con el navegador.
Y escriben datos **de todos los usuarios**. En el mismo repo hay 9 usos de `compare_digest` bien
hechos y un archivo (`mantenimiento.py:56-112`) que documenta **por qué** hay que usarlo.

**Consecuencia ya real:** el `ALERTS_CRON_TOKEN` se filtró en claro al pegar logs en un chat,
justamente porque viaja en la URL. **Hay que rotarlo.**

### 4 · Borrar una alerta toca las de los demás
```
DELETE FROM alerts               WHERE id=? AND user_id=?   ← bien
DELETE FROM alert_events         WHERE alert_id=? AND user_id=?   ← bien
DELETE FROM alert_symbol_state   WHERE alert_id=?   ← sin dueño
```
Las dos primeras filtran por usuario; la tercera no. Cualquiera que pruebe números de alerta al
azar resetea el "ya te avisé de esto" de las alertas de otros: la víctima recibe mails y
notificaciones repetidas, mandadas desde la infraestructura de Rendi. Es el mismo arreglo escrito
2 de 3 veces (`backend/main.py:34430-34432`).

### 5 · Una línea convierte todos los límites en límites por IP
`backend/main.py:396`: `key = f"{ip}|{suffix}" if suffix else ip`. El sufijo dice "por email" o
"por usuario", pero la clave **arranca con la IP**, así que basta cambiar de IP para empezar de
cero. Lo que eso rompe:
- el anti-fuerza-bruta del login (200 IPs = 200 intentos por minuto contra una cuenta);
- el código de verificación por email es de 6 dígitos, no tiene contador de intentos propio, y
  acertarlo **entrega la sesión**;
- las cuotas de IA y de facturación (17 lugares) se esquivan rotando IP.

**Y el mismo error al revés, que es el que puede tirar el registro para todos:** si Vercel hace de
intermediario, la IP que ve el backend es la de Vercel y **todos los usuarios caen en el mismo
balde** → 5 registros en 5 minutos cerrarían el alta para todo el mundo. Esto se confirma en
10 segundos y **no lo puedo hacer yo**: ver §"Lo que necesito de vos".

### 7 · El token de reseteo se le manda a Facebook
El guard que evita mandarle la URL al pixel cubre `/i/`, `/claim` y `/acceso` — en los dos lugares
donde está escrito (`frontend/src/utils/metaPixel.js:115` y `frontend/index.html:209`) — pero **no
cubre `/reset-password`**, y ahí el token de reseteo viaja en la URL. El pixel manda la dirección
completa. **`/verify-email` está en la misma situación** y el audit no lo menciona: también lleva
token en la URL y tampoco está en la lista.

---

## Lo demás, por informe

Todos verificados en el código de hoy salvo donde diga lo contrario.

### El rol asesor (`5a-asesor.md` + `5a-autorizacion-6.md`)

| id | qué | estado |
|---|---|---|
| H-1 | El `claim` da permiso de **escritura permanente** y la pantalla no lo dice | 🔴 abierto — `ClaimAccount.jsx` no menciona permiso, escritura ni revocación; su pantalla hermana `/acceso` sí |
| H-2 | El header abre **131 endpoints**, no los 3 que promete la interfaz | 🔴 abierto — el diseño sigue declarándose fail-open (`main.py:2951`); `/api/wallbit/*` sigue sin eximir |
| H-3 | Revocar **no mata los informes ya emitidos** | 🔴 abierto — `/i/<token>` sólo mira `revoked_at` del informe, nunca el estado del vínculo (`main.py:36876`) |
| H-4 | El informe público vive 180 días sin contraseña y el cliente ni sabe que existe | 🔴 abierto |
| H-5 | El ex-asesor sigue viendo nombre y teléfono de sus ex-clientes | 🔴 abierto — el `LEFT JOIN advisor_clients` de `main.py:35291` no filtra `status='active'` |
| H-5b | `_advisor_own_link` lo usan **3 de 14** lugares; el resto lo reescribe a mano | 🔴 abierto — 4 apariciones en todo el repo (1 definición + 3 usos) |
| — | **La revocación del cliente no cierra nada** | 🔴 abierto — el revoke del asesor (`main.py:35469`) cierra invitaciones y pedidos pendientes; el del cliente (`main.py:36101`) sólo cambia el estado |
| H-4 (t6) | `/api/advisor/alerts` borra eventos de **todos** los asesores | 🔴 abierto — `advisor_alerts.py:94`, `DELETE ... WHERE fired_at < ?` sin dueño |
| H-6, H-7 (t6) | Rechazar sin login; el preview entrega datos del asesor para tokens vencidos | 🟡 el rechazo sin login **está decidido a propósito** y documentado ("cortar nunca puede ser peor que no cortar"); el preview, sin re-verificar |
| H-8 (t6) | `/api/health` publica el commit desplegado | 🔴 abierto (menor) |

### Autenticación y sesiones (`5a-auth-sesiones.md`)

| id | qué | estado |
|---|---|---|
| H-1, H-2, H-3, H-4 | Los cuatro ALTOS = los puntos 2, 7 y 5 de arriba | 🔴 abiertos |
| H-5 | No hay forma de cerrar una sesión: `logout` sólo borra la cookie, el token sigue válido | 🔴 abierto — el propio docstring lo dice (`main.py:3395`) |
| H-6 | El link de reseteo **no es de un solo uso de verdad**: lee y después escribe, en dos pasos | 🔴 abierto — `main.py:3573` mira `used_at`, `main.py:3596` lo marca. Dos pedidos simultáneos pasan los dos. El arreglo correcto ya existe en `/api/auth/claim` |
| H-7 | Bombardear la casilla de un tercero desde una sola IP | 🔴 abierto |
| H-8 | Enumeración de usuarios: se puede averiguar qué emails están registrados | 🔴 abierto — `main.py:3330` devuelve un 409 con estructura, `main.py:3411` contesta "Tu cuenta ya está verificada" |
| H-9 | bcrypt corta la contraseña a 72 bytes en silencio y el modelo acepta 128 caracteres | 🔴 abierto — `max_length=128` sigue en los tres modelos |
| H-10 | Sin 2FA, sin bloqueo de cuenta, contraseña mínima de 10 caracteres | 🔴 abierto (decisión de producto) |
| H-11 | Los tokens de reseteo se guardan en claro y nadie los borra nunca | 🔴 abierto |
| H-12 | El token de sesión también viaja en el cuerpo de la respuesta (7 lugares) | 🔴 abierto |
| H-7 (forgot) | El mail de reseteo se manda **bloqueando la respuesta** → el tiempo de respuesta delata si el email existe. El arreglo ya está escrito en `register` | 🔴 abierto — `main.py:3543` manda el mail dentro del handler |

### Autorización, tramos 1 a 5

| id | qué | estado |
|---|---|---|
| t1 H-1/H-2 | El código de verificación y el login no tienen límite por cuenta | 🔴 abierto (es el punto 5) |
| t1 H-4 | **El email del admin está en claro en un comentario** (`main.py:124`), al lado del hash que supuestamente lo oculta | 🔴 abierto |
| t1 H-7 | `/api/auth/investor-profile` cae en prefijo exento: el asesor cree editar el perfil del cliente y edita el suyo | 🔴 abierto — sigue bajo `/api/auth` (`main.py:4121`) |
| t1 H-10 | CORS no permite `PATCH` ni el header del contexto de cliente | 🔴 abierto — `main.py:262-263` |
| t1 H-12 | Los símbolos `FCI:` esquivan el tope de 60 por pedido | 🔴 abierto (sin re-verificar el detalle) |
| t1 H-5, H-8, H-9, H-11 | Guard hardcodeado, oráculo 400-vs-404, 6 GET que escriben caches, `POST /api/positions` con broker inexistente | (sin re-verificar) |
| **t2 H-1** | **`GET /api/monthly` ESCRIBE**: un asesor de sólo lectura le crea filas en el libro mayor del cliente | 🔴 abierto — `main.py:12433` llama a `_rollover_all_brokers`. Es el agujero real del "ningún GET escribe" |
| **t2 H-2** | Dar de alta una operación **no valida que el broker exista** → plata inventada bajo un broker fantasma, invisible e imborrable | 🔴 abierto — `create_operation` (`main.py:14286`) no tiene ni un `SELECT ... FROM brokers`. Y el guard correcto ya está escrito en el camino del *deshacer* |
| t2 H-3, H-4 | Dos DELETE que contestan `ok:true` sin borrar nada; 7 endpoints que devuelven el texto crudo del error | (sin re-verificar) |
| t3 H-1 | El deshacer escribe con `WHERE id=?` pelado, sin dueño | 🔴 abierto — `main.py:15555` |
| t3 H-2 | `POST /api/goals` sin tope ni límite: filas ilimitadas por usuario | 🔴 abierto — `main.py` |
| t3 H-3 | Copia completa de la base en `/tmp`: 2 de 3 lugares no borran los archivos laterales | 🔴 abierto — sólo `main.py:16186` los limpia; `17364` y `17693` no |
| t3 H-4 | SQL armado pegando texto con el parámetro `days` | 🔴 abierto — `main.py:19352, 19362, 19376` |
| t3 H-5 | 4 endpoints de admin devuelven el error interno crudo | (sin re-verificar) |
| t4 H-2 | La memoria de IA que el asesor le escribe al cliente sobrevive a la revocación | 🔴 abierto |
| t4 H-3 | `GET /api/fundamentals/{ticker}` escribe una tabla global sin lista blanca ni límite | 🔴 abierto — `main.py:26770` |
| **t4 H-5** | **`/api/ai/chat` usa una conexión ya cerrada** → 500 para el asesor dentro de un cliente pro/advisor, y el guardarraíl del prompt nunca se aplica | 🔴 abierto y confirmado — cierre en `main.py:29032`, uso en `main.py:29102`. **Esto es un bug funcional, no sólo de seguridad** |
| t4 H-4, H-7..H-10 | Cuota de IA cobrada al cliente; límite compartido por IP; email en la URL en mutaciones de admin; topics `book.*` sin exigir plan asesor; 4 subidas de archivo sin límite | (sin re-verificar) |
| t5 H-5 | Más GET que escriben: `/api/iol/lab/status` y `/api/advisor/twr` | (sin re-verificar) |
| t5 H-6 | `PATCH /api/alerts/{id}` hace el UPDATE final con `WHERE id=?` sin dueño (hoy tapado por una consulta previa) | 🔴 abierto — `main.py:34417` |
| t5 H-8 | `POST /api/sections/restore` arma el INSERT pegando nombres de columna leídos de un JSON | 🔴 abierto |
| t5 H-9 | `POST /api/imports/wipe-broker` recibe el broker por la URL (queda en logs) | 🔴 abierto — `main.py:32576` |

### Secretos (`5a-secretos.md`)

| id | qué | estado |
|---|---|---|
| S-1 | `SECRET_KEY` era la API key de Anthropic | ✅ **cerrado** |
| S-2 | `ANTHROPIC_API_KEY` compartía valor con la clave de firma | ✅ **cerrado por el mismo cambio** |
| S-3 | La `SECRET_KEY` sigue escrita a mano en **dos archivos que están en git** | 🔴 abierto — `start-rendi.sh:43` y `.claude/settings.local.json:74`, los dos versionados. Ese valor **ya no es el de producción**, pero hay que sacarlo igual y agregar `.claude/settings.local.json` al `.gitignore` |
| H-1 | El email del admin en claro en un comentario | 🔴 abierto (mismo que t1 H-4) |

### Pendientes que dejó el cierre del Paso 0

1. 🔴 **Sacar el diagnóstico temporal de arranque** `_log_config_arranque()` — sigue vivo
   (`backend/main.py:31832` y `31860`). No filtra valores, sólo largos y forma, pero ya cumplió
   su función.
2. 🔴 **Rotar `ALERTS_CRON_TOKEN`** — se filtró en claro al pegar logs en un chat.
3. 🟡 **`REBILL_API_KEY` en los logs** — verificado: sólo escribe los primeros 8 caracteres
   **cuando la clave está mal formada** (`billing/rebill.py:251`). Si la clave es correcta no
   loguea nada. Menos grave de lo que decía la nota, pero conviene sacarlo.
4. 🔴 Sacar la `SECRET_KEY` de los dos archivos (= S-3).

---

## Lo que necesito de vos (yo no lo puedo mirar)

Son las cuatro preguntas que el audit dejó abiertas y siguen abiertas. **Ninguna te pide que
pegues una clave.**

1. **La más importante y la más rápida.** Entrá como admin a `/api/admin/diag/client-ip` y mirá el
   campo `ip_elegida`. La pregunta es una sola: **¿ese número es tu IP de casa, o es siempre el
   mismo para todos?** Si es siempre el mismo, todos los usuarios comparten un solo balde de
   límites y 5 registros en 5 minutos cierran el alta para todo el mundo. (Tu IP la ves en
   cualquier buscador poniendo "cuál es mi ip".)
2. **¿El bucket de backups de S3 es privado?** Panel de AWS → S3 → el bucket → pestaña
   *Permissions* → tiene que decir *Block all public access: On*.
3. **¿Existe la variable `REPORTS_TTL_DAYS` en Railway, y cuánto dice?** (Railway → proyecto →
   servicio `trading` → pestaña *Variables*.) Si no existe, los informes públicos duran **180 días**.
4. Confirmá que **no hay ninguna variable `MP_`** en Railway (ya lo dijiste el 08/09; lo repito
   porque de eso depende que el webhook sea BAJO y no ALTO).

---

## Si me preguntás por dónde empezar

Por orden de "daño posible ÷ trabajo":

1. **Los 4 crons** (`compare_digest` + header obligatorio + sólo POST) y **rotar el
   `ALERTS_CRON_TOKEN`**. Es el único de la lista donde ya hay un secreto filtrado.
2. **El `DELETE` de `alert_symbol_state`** — una palabra: `AND user_id=?`. Cinco minutos.
3. **`/reset-password` y `/verify-email` fuera del pixel** — dos líneas, en dos archivos. Diez minutos.
4. **Borrar el webhook de Mercado Pago** — un bloque menos.
5. **La clave del rate limit** — es una línea, pero antes hay que contestar la pregunta 1 de arriba,
   porque la respuesta cambia el arreglo.
6. **`password_changed_at` con valor por defecto** — el más grande de los siete, y el único que
   los usuarios notan (se deslogean una vez).
7. **`GET /api/monthly` que escribe** y **el alta de operaciones que no valida el broker**: no son
   de seguridad pura, son plata que se inventa sola.

Y una cosa que no está en ninguna lista pero conviene: **`/api/ai/chat` está tirando 500** cuando
un asesor entra a un cliente pro. Eso no es un riesgo, es una función rota.
