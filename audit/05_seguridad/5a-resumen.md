# 5a · Tanda A — resumen

> Auditoría de seguridad externa de Rendi. Commit auditado `b74f450f`, verificado contra
> `origin/main` (`897b0d63`). 8 agentes + 2 informes propios. **Ningún valor de secreto acá.**

## Método del ensamblado

Los 8 informes son de agentes; **este resumen no los da por buenos**. Verifiqué personalmente,
con grep sobre el código, los seis hallazgos que mueven una decisión: el `DELETE` cruzado de
`alert_symbol_state`, la clave del rate limit, la comparación de los tokens de cron, el
fail-open del webhook de MP, la revocación que no alcanza a los informes, y la contradicción
entre dos agentes sobre si algún `GET` escribe. Donde el ensamblado corrige a un agente, se dice.

**Dos correcciones que salieron de esa verificación:**

1. **Un agente reportó `GET /api/ai/topics` sin auth como hallazgo. Es falso**: es público a
   propósito, documentado en su docstring, y devuelve una lista estática de nombres de topics.
2. **Dos agentes se contradijeron sobre si algún `GET` escribe.** El del rol asesor barrió 131
   handlers y dijo que ninguno; el del tramo 2 lo midió y mostró 8 filas insertadas. **Gana el
   tramo 2**: la escritura de `GET /api/monthly` está dentro de un helper
   (`_rollover_all_brokers`), no en el cuerpo del handler, y un barrido textual no la ve.
   Lo medí yo con análisis transitivo del AST (`audit/_scripts/5a_gets_que_escriben.py`), y de
   paso encontré un falso positivo **en mi propio script**: marcaba `db_abierta` como escritora
   porque su docstring menciona `conn.commit()`, lo que inflaba el resultado de 6 a 15. Corregido.

---

## Lo que hay que arreglar antes de que entre un usuario más

Sin suavizarlo, en orden:

1. **Borrar `POST /api/billing/webhook` (Mercado Pago).** Es una puerta abierta sin llave hacia
   un sistema de pagos que ya no se usa. **Ver la corrección de severidad en §Corrección 3**: el
   agente lo calificó ALTO y **la verificación lo baja a MEDIO**. Se borra igual porque no cuesta
   nada y es superficie muerta que sigue armada.
2. **`ALTER TABLE users ADD COLUMN password_changed_at` sin `DEFAULT`.** Las cuentas anteriores al
   2026-05-07 emiten JWT sin el claim `pca`. Para esas cuentas, **cambiar la contraseña no
   invalida el token robado** durante 7 días. No hace falta forjar nada: el backend emite tokens
   irrevocables él solo.
3. **Los 4 endpoints de cron a `hmac.compare_digest`, header obligatorio y sólo POST.** Escriben
   datos de todos los usuarios y hoy comparan con `!=`, aceptan el token por query string y
   responden a GET.
4. **`DELETE FROM alert_symbol_state WHERE alert_id=?` (`main.py:33572`).** Cualquier usuario
   itera ids y resetea el edge-trigger de las alertas ajenas: la víctima recibe push y mails
   repetidos desde la infra de Rendi.
5. **`key = f"{ip}|{suffix}"` (`main.py:397`).** Una línea que convierte los 31 límites "por
   email" y "por uid" en límites por IP. Rotando IP se evade todo, incluidas las cuotas de IA.
6. **Rotar `SECRET_KEY`** con el runbook de `fix-credentials-key/` (el fix ya está hecho y probado).
7. **Sacar `/reset-password` del camino del Meta Pixel.** El token de reseteo viaja en la query
   string y hoy se le manda a Facebook.

### Corrección 3 · El webhook de Mercado Pago: ALTO → MEDIO

El founder confirmó (2026-09-08) que **`MP_WEBHOOK_SECRET` no existe en las variables de Railway**.
Eso deja el fail-open **armado**: `main.py:27554` sólo rechaza `if _webhook_secret()`, con la
variable vacía no rechaza, y el evento se procesa sin firma. Hasta ahí, el agente tenía razón.

**Pero su impacto estaba sobredimensionado.** El agente escribió *"UPDATE subscriptions de
terceros con valores propios"*. Es falso, y las dos ramas del handler explican por qué:

| rama | qué hace | qué controla el atacante |
|---|---|---|
| `preapproval` → `_process_preapproval_event` | **Le vuelve a preguntar a Mercado Pago** (`get_preapproval`, `mercadopago.py`) y usa ESA respuesta | sólo el id. Los valores salen de MP, no del atacante. Con un id inventado, `pa` viene vacío y sale por el `return` |
| `payment` → `_process_payment_event` | **Sí confía en el payload**: `pa_id` y `data_status` salen del JSON posteado | acá sí hay superficie, ver abajo |

Además `_access_token()` (`mercadopago.py`) **lanza excepción si `MP_ACCESS_TOKEN` no está**, y el
`except Exception` de `main.py:27587` la traga devolviendo 200. Si esa variable tampoco está en
Railway —probable, porque MP está deprecado— la primera rama **no hace absolutamente nada**.

**Lo que queda realmente explotable, y es la rama `payment`:** un atacante que **conozca o adivine
un `mp_subscription_id` válido** (un id de preapproval de Mercado Pago, largo y no secuencial)
puede (a) escribirle `last_payment_id` a esa suscripción y (b) **disparar un mail de "recibo de
pago" o de "tu pago falló" a un usuario real, desde el dominio de Rendi**. No cambia el tier de
nadie: eso vive en la otra rama, la que sí consulta a MP.

**Severidad honesta: BAJO** (bajada por segunda vez, ver abajo). Requiere adivinar un
identificador no público, no otorga plan pago, y sólo alcanza a las suscripciones legacy de MP que
queden en la base. El daño posible es suplantación de correo de facturación, que igual es serio
para la confianza en el producto.

**Segunda bajada, 2026-09-08:** el founder confirmó que **no existe NINGUNA variable `MP_` en
Railway**. Sin `MP_ACCESS_TOKEN`, `_access_token()` lanza excepción y el `except Exception` de
`main.py:27587` la traga → **la rama `preapproval` no llega a hacer nada, ni siquiera consultar a
MP**. Queda sólo la rama `payment`, que necesita un `mp_subscription_id` histórico válido y
además que exista la fila en `subscriptions`. Es una cadena de tres condiciones improbables.
**Se borra la ruta por higiene, no por riesgo.**

**Sigue en pie borrar la ruta**, y por una razón más simple que su severidad: es la única puerta
del sistema que acepta pedidos de cualquiera sin identificarse, y sirve a un proveedor de pagos
que ya no se usa. Borrarla no cuesta nada y elimina la categoría entera.

**Lo que falta confirmar:** si existe alguna variable `MP_ACCESS_TOKEN` en Railway. Sin ella, ni
siquiera la primera rama corre.

---

## Los hallazgos agrupados por causa raíz

### RC-1 · El fix que se aplicó en 1 de N call sites — explica 8 hallazgos

Es la causa raíz que ya documenta tu `CLAUDE.md`, y en seguridad aparece ocho veces. En **todos**
los casos el arreglo correcto ya está escrito en el repo; simplemente no llegó a todos lados.

| dónde | los que están bien | los que quedaron afuera |
|---|---|---|
| Tokens de servicio | 9 usos con `compare_digest`; `mantenimiento.py:56-112` documenta **por qué** | los 4 crons: `main.py:31568, 33602, 33670, 33952` |
| Webhooks de pago | Rebill valida bien | MP es fail-open en el caller (`main.py:27557`) |
| Borrado de alertas | 2 de 3 `DELETE` filtran por `user_id` | el tercero, `main.py:33572` |
| Validación de broker | 9 de 27 call sites de `_adjust_broker_cash` | 5 no validan, incl. el alta de operaciones |
| Scoping del undo | 3 grados distintos en el repo | `main.py:15092` sin ninguno |
| Guard de rutas sensibles del pixel | `/i/`, `/claim`, `/acceso` | `/reset-password` |
| Revocación del vínculo | el revoke del **asesor** cierra claims y link-requests | el revoke del **cliente** no cierra nada |
| Predicado de autorización del asesor | `_advisor_own_link` existe | lo usan 3 de 14 sitios; el resto está inline 23 veces en 5 archivos |
| Un-solo-uso atómico | `/api/auth/claim` (`main.py:35135`) lo tiene | `reset-password` no |
| Mail en BackgroundTask (cierra el oráculo de timing) | `register` (`main.py:3159`) | `forgot-password` no |

**El fix de fondo no es arreglar los 10.** Es que cada uno de estos predicados viva en un solo
lugar: un helper de token de servicio, un helper de validación de broker, un `FOREIGN KEY …
ON DELETE CASCADE` en vez de un `DELETE` a mano.

### RC-2 · El modelo de permisos del asesor asume tres cosas que no son ciertas

`get_effective_user` (`main.py:2731-2820`) resuelve bien: **cero IDOR**, 403 con vínculo
inexistente, ajeno o revocado, y `read` bloquea escrituras. El agujero no está en el resolver
sino en sus supuestos.

1. **"Ningún GET escribe."** `get_effective_user` exige `read_write` sólo para métodos ≠ GET.
   **MEDIDO por mí:** 12 handlers GET escriben; 6 son alcanzables con contexto de cliente. De
   esos 6, **cinco escriben caches globales** sin `user_id` (`bond_indices_daily`,
   `financial_events`, `yfinance_cache`) y son inofensivos para el modelo de permisos.
   **Uno escribe el libro mayor del cliente**: `GET /api/monthly` → `_rollover_all_brokers` →
   `monthly_entries`. Un asesor con permiso de sólo lectura le insertó 8 filas a un cliente.
   El fix es chico y puntual, no arquitectónico.
2. **"El header abre lo que la interfaz promete."** La promesa es cartera, movimientos y
   registrar operaciones. El header abre **131 endpoints**, incluidos `GET/POST/DELETE
   /api/ai/facts` (la memoria personal que el cliente le declaró a la IA), `imports/wipe-broker`
   y `wallbit/disconnect`. El propio código se declara fail-open en `main.py:2763`.
   Caso concreto: `/api/wallbit/*` no está exento y `/api/iol/lab/*` se salvó por accidente
   (usa `get_current_user`) — una asimetría sin explicación es la señal de que nadie lo decidió.
3. **"Revocar corta el acceso."** No corta los informes ya emitidos. `/i/<token>` sirve
   patrimonio, tenencias y movimientos **sin auth** por 180 días, el único que puede revocarlos
   es el asesor —la persona de la que el cliente se está separando— y el cliente no tiene ningún
   endpoint para siquiera enterarse de qué informes existen sobre su cartera. Se suma que el
   `LEFT JOIN advisor_clients` de `main.py:34428` no filtra `status='active'`: el ex-asesor sigue
   viendo nombre actual y teléfono de sus ex-clientes.

Aparte, de consentimiento: el `claim` deja `read_write` permanente sobre una cuenta que ya tiene
dueño y contraseña, y la pantalla `/claim` **no lo dice** — su pantalla hermana `/acceso` sí
divulga permiso, escritura y revocación.

### RC-3 · Una línea de rate limiting rompe los 31 límites

`main.py:397`: `key = f"{ip}|{suffix}"`. Todo límite "por email" o "por uid" es en realidad por
*(IP, sufijo)*. Consecuencias medidas y deducidas:

- 200 IPs = 200 intentos por minuto contra una cuenta. El comentario del login promete
  explícitamente mitigar el brute-force distribuido y hace lo contrario.
- El OTP de verificación son 6 dígitos (900 k) sin contador de intentos en la fila, y
  `verify-email` **emite el token de sesión**: adivinar el código es tomarse la cuenta.
- Las cuotas de IA y de billing (17 call sites con `:{uid}`) se evaden rotando IP.
- **Y el mismo error al revés (DEDUCIDO):** si Vercel proxea `/api/*` server-side, la última IP
  pública del `X-Forwarded-For` es Vercel y **todos los usuarios caen en el mismo balde** —
  5 requests en 5 minutos cerrarían el registro para todo el mundo. Se confirma en 10 segundos
  entrando como admin a `/api/admin/diag/client-ip` y mirando si `ip_elegida` es tu IP.

### RC-4 · `SECRET_KEY` hace dos trabajos

Paso 0 completo en `5a-paso0-secret-key.md`. En producción es una API key de Anthropic, y además
de firmar los JWT deriva la Fernet que cifra las credenciales de broker — por eso rotar dolía y
no se hacía. **Fix construido, probado y aplicado en la rama `fix/credentials-key`** (33/33 tests),
con runbook en `fix-credentials-key/README.md`. Falta ejecutarlo.

### RC-5 · Higiene que está bien y conviene no romper

No todo es hallazgo, y esto vale decirlo: **cero IDOR en los 264 endpoints**. Los que reciben un
id filtran por dueño *en la sentencia que produce el efecto*, no sólo en un chequeo previo.
47/47 rutas `/api/admin` exigen `get_admin_user`. bcrypt cost 12 con salt. `dummy_verify()` cierra
el timing del login (+0,3 ms medidos). Cookie HttpOnly/Secure/Lax host-only, sin token en
localStorage. CORS cerrado. Borrar la cuenta sí invalida la sesión. El gate `IOL_LAB_EMAILS` falla
cerrado. De los 19 secretos que usa el backend, 16 están limpios y ninguno aparece en los 24.579
objetos del historial.

---

## Inventario de entregables

| archivo | qué cubre |
|---|---|
| `5a-paso0-secret-key.md` | la `SECRET_KEY`: qué protege, historial, precedencia, rotación |
| `5a-autorizacion-1.md` … `-6.md` | los **264** endpoints, uno por uno, con tabla |
| `5a-asesor.md` | el modelo del rol asesor: vínculo, consentimiento, revocación |
| `5a-auth-sesiones.md` | hash, tokens, reset, enumeración, rate limiting |
| `5a-secretos.md` | los 19 secretos: dónde viven, qué protegen, qué rotar |
| `fix-credentials-key/` | el fix de `CREDENTIALS_KEY` + runbook (aplicado en su rama) |
| `_inventario_endpoints.txt` | los 264 endpoints con línea y método |
| `../_scripts/` | 17 scripts de medición, reproducibles |

**Corrección al inventario:** contaba `@app.get/post/...` pero no `@app.api_route`, y los 4 que
usan ese decorador son justo los crons. El total real es **264**, no los 260 que medí primero ni
los 276 que decía el mapa. El agente del tramo 5 lo detectó solo y los auditó igual.

**Corrección al mapa:** `get_effective_user` está en `main.py:2731-2820`, no en 2729-2800.

---

## Lo que la Tanda A NO auditó

Por diseño, va a la Tanda B: pagos e idempotencia de webhooks, los límites de plan (backend vs
frontend), el reinicio del período de prueba, rate limiting de los crons, la IA (qué viaja en el
prompt, inyección vía nombre de broker o CSV), la importación de archivos (tamaño, tipo, XXE,
zip-bombs, XSS al renderizar), las vulnerabilidades clásicas y la configuración (CORS,
`ALLOWED_ORIGINS`, cabeceras, stack traces, bucket S3), y qué devuelven las APIs de más.

Y lo que **no se pudo** verificar desde el código, que necesita al founder:

1. ~~Qué valor tiene `SECRET_KEY` en Railway~~ **CONFIRMADO 2026-09-08**: el founder lo verificó
   en el dashboard de Railway — **empieza con `sk-ant-`**. Es una API key de Anthropic. Deja de
   ser "de memoria" y pasa a estar confirmado visualmente por el dueño de la cuenta.
2. ~~Si `MP_WEBHOOK_SECRET` está vacía~~ **CERRADO 2026-09-08: no existe NINGUNA variable `MP_`
   en Railway.** El fail-open está armado pero sin consecuencia práctica: re-calificado a BAJO
   (§Corrección 3).
3. Si el bucket de backups de S3 es privado.
4. Si `ip_elegida` en `/api/admin/diag/client-ip` es la IP real del cliente o la de Vercel.
5. El `REPORTS_TTL_DAYS` real en producción (el default del código son 180 días).
