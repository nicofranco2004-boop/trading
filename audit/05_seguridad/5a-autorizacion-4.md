# Autorización entre usuarios — tramo 4 de 6 (billing + IA + imports)

**Alcance:** los 43 endpoints de `/tmp/rendi-main/backend/main.py` entre las líneas 19697 y 30737
(commit congelado `b74f450f`). Desde `POST /api/admin/billing/restore-tier` hasta
`POST /api/imports/preview`. Los 43 auditados, sin muestreo.

---

## Método

**Qué ejecuté**

- `awk -F'|' '$1>=19697 && $1<=30737' audit/05_seguridad/_inventario_endpoints.txt` → 43 rutas.
  Conté 43 y entrego 43.
- Lectura de la firma + cuerpo de cada uno de los 43 sobre la copia congelada
  (`sed -n` por rango). No leí el working tree del repo.
- Lectura completa del resolver de contexto de cliente: `main.py:2721-2820`
  (`get_current_user`, `get_admin_user`, `CLIENT_CTX_EXEMPT_PREFIXES`,
  `_resolve_client_context`, `get_effective_user`).
- Barrido de escrituras del tramo:
  `awk 'NR>=19697 && NR<=30737' main.py | grep -iE '(UPDATE|INSERT INTO|DELETE FROM)'` → 24 sitios,
  revisados uno por uno.
- Barrido de SQL por f-string en el tramo → 6 hits, **todos** con nombre de tabla proveniente de una
  lista hardcodeada y valores por placeholder. **No hay inyección SQL en este tramo.**
- Seguimiento de los builders de IA (`ai/registry.py` + los 37 `ai/builders/*.py`) para descartar
  IDOR vía el `params: dict` libre de `POST /api/ai/analyze`.
- Verificación de deriva del hallazgo principal contra `origin/main`:
  `git show origin/main:backend/main.py | grep -n "from billing.mercadopago import _webhook_secret" -A 4`
  → **sigue vivo en `origin/main:27557`**.
- **MEDIDO (único):** `audit/_scripts/poc_closed_conn.py` — sqlite3 en memoria, para probar el
  mecanismo de H-5. Salida real: `RAISE: ProgrammingError: Cannot operate on a closed database.`

**Qué NO ejecuté**

- Ninguna petición contra producción ni contra ningún sistema en vivo. No levanté el backend.
- No verifiqué el valor de ninguna env var de producción (`MP_WEBHOOK_SECRET`, `MP_ACCESS_TOKEN`,
  `REBILL_WEBHOOK_SECRET`/`_TOKEN`). H-1 depende de que `MP_WEBHOOK_SECRET` esté vacía en Railway:
  eso **no lo puedo medir desde acá** y lo digo explícito en "Lo que NO pude verificar".
- No probé la ruta del asesor con un vínculo real (no hay entorno con `advisor_clients` poblada).

**Supuestos**

- `get_effective_user` sobre un prefijo exento devuelve el uid autenticado tal cual — verificado
  leyendo `_resolve_client_context` (`main.py:2789-2792`: match por límite de segmento, `return None`).
- "Valida propiedad = n/a" significa que el endpoint no recibe ningún identificador de recurso
  ajeno: opera siempre sobre el `uid` que resolvió el `Depends`.

---

## Respuesta directa a las dos preguntas del encargo

**Billing — ¿puede un usuario cambiarse el tier / restaurarlo / regalarse crédito por API?**
No. Los 5 endpoints de `/api/admin/billing/*` y `/api/admin/*` del tramo exigen `get_admin_user`
(`main.py:2721-2726`, que releé `users.is_admin` de la DB en cada request, no del JWT). Los caminos
de usuario que escriben tier o crédito están todos guardados:
`trial/start` y `trial/pro-upsell` usan `get_current_user` **a propósito** (documentado) y son
`UPDATE ... WHERE id=? AND trial_used_at IS NULL` atómicos (`billing/trial.py:343-359`, `860-865`);
`change-plan` exige crédito activo **con anchor** y convierte a la tarifa diaria del plan nuevo
(no fabrica días); `subscribe` sólo crea un payment-link; `sync` lee la sub del propio uid y delega
en MP, que es la autoridad. **El único camino no autenticado que escribe billing es H-1.**

**IA — ¿es coherente que `/api/ai` NO esté exento?**
Sí, es coherente con lo que el comentario de `main.py:2790` declara, y lo verifiqué: con contexto
activo la IA lee y escribe la cuenta del **cliente**, y las escrituras (todo lo que no es GET) exigen
`permission='read_write'` (`main.py:2807-2808`). Pero la coherencia tiene tres costuras reales:
la cuota se le cobra **al cliente** con lente forzada `pro` (H-4), la memoria que el asesor escribe
en el cliente **sobrevive a la revocación del vínculo** (H-2), y el propio camino de la lente
revienta con 500 en el caso más común (H-5).

---

## Tabla — los 43 endpoints

| # | línea | método | ruta | qué hace | valida sesión | valida propiedad | veredicto |
|---|-------|--------|------|----------|---------------|------------------|-----------|
| 1 | 19697 | POST | `/api/admin/billing/restore-tier` | realinea `users.tier` con el crédito activo, por email | `get_admin_user` | n/a — el target lo elige un admin por email, es la función | OK (ver H-8: el email va por query string) |
| 2 | 19844 | POST | `/api/admin/billing/grant-comp` | regala plan pago N días (ledger `kind='comp'`) | `get_admin_user` | n/a — idem | OK (ver H-8) |
| 3 | 19985 | GET | `/api/admin/fci/probe` | probe HTTP saliente read-only a fuentes de precio FCI | `get_admin_user` | n/a — no toca DB | OK |
| 4 | 20074 | GET | `/api/fci/catalog` | catálogo global de FCI + último precio | `get_effective_user` | n/a — dato global, no del usuario | OK |
| 5 | 20086 | POST | `/api/admin/fci/refresh` | seed catálogo + refresh de precios FCI | `get_admin_user` | n/a — tabla global | OK |
| 6 | 20098 | GET | `/api/admin/pf/probe` | probe read-only de tasas de plazo fijo | `get_admin_user` | n/a — no toca DB | OK |
| 7 | 20146 | POST | `/api/admin/users/{user_id}/approve` | `UPDATE users SET approved=1 WHERE id=?` | `get_admin_user` | n/a — actuar sobre otro usuario ES la función | OK |
| 8 | 20273 | POST | `/api/admin/wipe-broker-data` | borrado nuclear de un broker | `get_admin_user` | **sí** — `SELECT ... FROM brokers WHERE user_id=? AND name=?` (20280) y `_wipe_broker_data(conn, uid, ...)` sólo con el uid del admin | OK — no puede tocar otra cuenta |
| 9 | 20291 | DELETE | `/api/admin/users/{user_id}` | borra usuario + cascada dinámica | `get_admin_user` | n/a — bloquea auto-borrado (20294) y borrar otro admin (20301) | OK |
| 10 | 25890 | POST | `/api/ai/analyze` | análisis IA de una pantalla (LLM + cache + cuota) | `get_effective_user` | **sí** — `build_packet(conn, uid, **params)`; los builders con id (`goal`, `operations.trade`) filtran `WHERE id=? AND user_id=?` | REVISAR: topics `book.*` sin gate de tier (H-9); cuota al cliente (H-4) |
| 11 | 26106 | GET | `/api/tickers/search` | autocomplete de tickers vía yfinance | `get_effective_user` | n/a — dato de mercado | OK |
| 12 | 26153 | GET | `/api/fundamentals/{ticker}` | scorecard de fundamentales | `get_effective_user` | n/a — dato de mercado | **MEDIO: escritura por GET en tabla global `yfinance_cache`, sin allowlist ni rate-limit (H-3)** |
| 13 | 26176 | POST | `/api/fundamentals/ai-summary` | resumen IA de fundamentales | `get_effective_user` | n/a — sólo ticker | OK (rate-limit 10/60s, cuota) |
| 14 | 26308 | GET | `/api/ai/topics` | lista los topics del registry | **NINGUNA — público** | n/a | BAJO: público a propósito, pero filtra la existencia de features del plan asesor (H-6) |
| 15 | 26334 | POST | `/api/plan/track` | inserta evento de paywall (whitelist de nombres) | `get_effective_user` (prefijo exento → uid propio) | n/a — escribe con el uid propio | OK |
| 16 | 26365 | POST | `/api/billing/trial/start` | activa el trial de 15 días | `get_current_user` (deliberado) | n/a — sólo la propia cuenta | OK — `UPDATE ... WHERE id=? AND trial_used_at IS NULL` atómico |
| 17 | 26387 | POST | `/api/billing/trial/pro-upsell` | 7 días de Pro al que paga Plus | `get_current_user` (deliberado) | n/a | OK — exige anchor de plan pago (`trial.py:828-832`), idempotente |
| 18 | 26408 | GET | `/api/admin/billing/trial-funnel` | embudo agregado del trial | `get_admin_user` | n/a — agregado cross-cuenta, es la función | OK (valida `days` 1-730) |
| 19 | 26427 | GET | `/api/billing/trial` | estado del trial propio | `get_current_user` | n/a | OK — sin escrituras en `trial.status` |
| 20 | 26439 | GET | `/api/plan/features` | flags/límites del tier | `get_effective_user` | n/a | OK — lente `pro` sólo si `uid != auth_uid`, que el resolver ya validó; el bloque `trial` se omite en contexto |
| 21 | 26504 | POST | `/api/billing/subscribe` | crea payment-link Rebill | `get_effective_user` (exento → uid propio) | **sí** — `WHERE user_id=?` en users y subscriptions | OK (rate-limit 5/600s) |
| 22 | 26630 | POST | `/api/billing/change-plan` | convierte crédito al plan nuevo, después da de baja | `get_effective_user` (exento) | **sí** — `subscriptions WHERE user_id=?` | OK (rate-limit 3/600s; orden convertir→cancelar documentado) |
| 23 | 26773 | GET | `/api/billing/preview-change-plan` | simula el cambio de plan | `get_effective_user` (exento) | n/a | OK — sin escrituras |
| 24 | 26809 | POST | `/api/billing/rebill-webhook` | webhook de Rebill: activa/cancela tier | **NINGUNA sesión — HMAC o token de URL** | n/a — matchea por `metadata.rendi_user_id` | OK — **fail-closed correcto** (`rebill.py:392-398`): en prod sin auth configurada, 401 |
| 25 | 27306 | POST | `/api/billing/cancel` | cancela la suscripción | `get_effective_user` (exento) | **sí** — `WHERE user_id=? AND status='authorized'` | OK (rate-limit 5/600s) |
| 26 | 27420 | POST | `/api/billing/sync` | pull del estado de la sub a MP | `get_effective_user` (exento) | **sí** — lee su propia sub antes de procesar | OK |
| 27 | 27476 | GET | `/api/billing/status` | estado de la suscripción propia | `get_effective_user` (exento) | **sí** — `WHERE user_id=?` | OK |
| 28 | 27501 | POST | `/api/billing/webhook` | webhook de Mercado Pago | **NINGUNA — firma MP, y la comprobación es FAIL-OPEN** | n/a | **ALTO: H-1 — sin `MP_WEBHOOK_SECRET` el rechazo no dispara y el evento se procesa sin autenticar** |
| 29 | 27787 | GET | `/api/ai/usage` | consumo IA de la semana | `get_effective_user` | n/a | OK — `get_current_usage` no escribe |
| 30 | 27800 | DELETE | `/api/ai/cache/{screen}` | invalida cache IA de una pantalla | `get_effective_user` | **sí** — `DELETE ... WHERE user_id=? AND screen IN (?)` (`ai/cache.py:158-161`) | OK — DELETE exige `read_write` en contexto |
| 31 | 28213 | POST | `/api/diagnostics/dismiss` | descuenta un "no me interesa" de la cuota | `get_effective_user` | n/a — `reserve_diag_dismiss(conn, uid)` | OK (rate-limit 30/60s) |
| 32 | 28264 | POST | `/api/ai/chat` | chat del coach IA (con tools que escriben) | `get_effective_user` | **sí** — snapshot y facts por `WHERE user_id=?`; POST exige `read_write` en contexto | **MEDIO: H-4 (cuota al cliente) + H-5 (500 por conexión cerrada en `main.py:28412`)** |
| 33 | 29199 | POST | `/api/feedback/recommendation` | manda la recomendación por mail | `get_effective_user` (exento) | n/a — lee su propio email | BAJO: rate-limit por IP sin uid en la clave (H-7) |
| 34 | 29303 | POST | `/api/ai/remember` | persiste un "hecho" en la memoria del coach | `get_effective_user` | **sí** — `_atomic_insert_fact(conn, uid, ...)` con caps por `user_id` | **MEDIO: H-2 — el asesor escribe memoria persistente en el cliente y sobrevive a la revocación** |
| 35 | 29339 | GET | `/api/ai/facts` | lista los hechos del usuario | `get_effective_user` | **sí** — `WHERE user_id=?` en ambas ramas (29351, 29358) | OK |
| 36 | 29367 | DELETE | `/api/ai/facts/{fact_id}` | soft-delete de un hecho | `get_effective_user` | **sí** — comprueba `WHERE id=? AND user_id=?` ANTES (29385) y repite el filtro en el `UPDATE` (29391) | OK — patrón correcto, es el modelo a copiar |
| 37 | 29436 | GET | `/api/imports/template` | CSV de ejemplo del parser | `get_effective_user` | n/a — dato estático | OK |
| 38 | 29452 | GET | `/api/imports/parsers` | lista de parsers | `get_effective_user` | n/a | OK |
| 39 | 29458 | GET | `/api/imports/parsers/grouped` | parsers agrupados | `get_effective_user` | n/a | OK |
| 40 | 29464 | POST | `/api/imports/inspect` | headers + mapping sugerido de un CSV | `get_effective_user` | n/a — no persiste | BAJO: sin rate-limit (H-10) |
| 41 | 29496 | POST | `/api/imports/classify-tenencia` | dice cuál archivo es la foto | `get_effective_user` | n/a — no persiste | BAJO: sin rate-limit (H-10) |
| 42 | 29661 | POST | `/api/imports/tenencia/preview` | foto de tenencia → batch `preview` | `get_effective_user` | **sí** — `SELECT 1 FROM brokers WHERE user_id=? AND name=?` (29803) | OK — POST exige `read_write` en contexto |
| 43 | 30439 | POST | `/api/imports/preview` | sube CSVs → batch `preview` | `get_effective_user` | **sí** — `run_preview(conn, uid=uid, ...)`; el broker llega como nombre, no como id ajeno | OK (cap 20 archivos / 5 MB); BAJO: sin rate-limit (H-10) |

**Resumen de la tabla:** 0 CRÍTICOS, 1 ALTO, 4 MEDIOS, 5 BAJOS/REVISAR, 33 OK.
**No encontré un solo IDOR en el tramo**: los 4 endpoints que reciben un id de recurso
(`/api/ai/facts/{fact_id}`, `/api/admin/users/{user_id}`, y por `params` los builders `goal` y
`operations.trade`) filtran todos por `user_id` además del id. Digo esto explícito porque es el
resultado más importante del tramo y es un resultado *positivo*.

---

## Resumen — hallazgos por severidad

| id | severidad | título | archivo:línea | evidencia |
|----|-----------|--------|---------------|-----------|
| H-1 | **ALTO** | El webhook de MP es fail-open: el fix de 2026-05-31 se aplicó en `mercadopago.py` y no se propagó al caller | `main.py:27555-27560` | ESTRUCTURAL + DEDUCIDO |
| H-2 | MEDIO | La memoria de IA que el asesor escribe en el cliente sobrevive a la revocación del vínculo | `main.py:29303`, `main.py:34609-34622` | ESTRUCTURAL |
| H-3 | MEDIO | `GET /api/fundamentals/{ticker}` escribe una tabla global sin allowlist ni rate-limit (y lo alcanza un asesor de sólo lectura) | `main.py:26153` → `main.py:21080-21095` | ESTRUCTURAL |
| H-4 | MEDIO | La cuota de IA del asesor se le cobra al cliente, con lente `pro` forzada | `main.py:28313-28325`, `main.py:25936-25941` | DEDUCIDO |
| H-5 | MEDIO | `/api/ai/chat` usa una conexión ya cerrada → 500 para el asesor dentro de un cliente pago, y el prompt de guardarraíl nunca se aplica | `main.py:28342` vs `main.py:28412` | **MEDIDO** (mecanismo) + DEDUCIDO (alcance) |
| H-6 | BAJO | `GET /api/ai/topics` sin autenticación | `main.py:26308-26313` | ESTRUCTURAL |
| H-7 | BAJO | Rate-limit de recomendaciones compartido entre todos los usuarios de una IP | `main.py:29218` | ESTRUCTURAL |
| H-8 | BAJO | Mutaciones de admin con el email del usuario en el query string | `main.py:19698`, `19845` | ESTRUCTURAL |
| H-9 | BAJO | Los topics `book.*` (plan asesor) no exigen tier advisor en `/api/ai/analyze` | `main.py:25923-25929` | DEDUCIDO |
| H-10 | BAJO | Los 4 endpoints de subida de archivos del tramo no tienen rate-limit | `main.py:29464`, `29496`, `29661`, `30439` | ESTRUCTURAL |

---

## Hallazgos

### [ALTO] H-1 · El webhook de Mercado Pago es fail-open: el fix vive en el módulo, el caller lo anula

**Evidencia:** ESTRUCTURAL (el `if` está citado abajo) + DEDUCIDO (el impacto depende de una env var
de producción que no puedo leer desde acá).

**Dónde:** `main.py:27555-27560` (endpoint), `billing/mercadopago.py:207-221` (el fix que se anula),
`billing/rebill.py:392-398` (el mismo problema, resuelto bien).

**Qué pasa**

En mayo de 2026 se arregló exactamente este bug: el chequeo era `if RENDI_ENV == 'prod'`, esa env var
no estaba en Railway, y en producción real con API key live el código aceptaba cualquier webhook sin
firma. El fix agregó `is_likely_production()` y dejó `verify_webhook_signature` **fail-closed**:

```python
# billing/mercadopago.py:207-221
    secret = _webhook_secret()
    if not secret:
        from billing import rebill as _rebill
        if _rebill.is_likely_production():
            log.error("MP_WEBHOOK_SECRET no configurada en producción — webhook rechazado. ...")
            return False          # ← el fix: en prod sin secret, NO valida
        log.warning("MP_WEBHOOK_SECRET no configurada — saltando validación (dev local only)")
        return True
```

Pero **el caller decide el rechazo por su cuenta**, y su condición no es "la firma no validó" sino
"hay secret configurado":

```python
# main.py:27553-27560
        if not sig_valid:
            # En sandbox sin secret pasamos (warning ya en mercadopago.py).
            # Sólo rechazamos si secret está configurado pero la firma falla.
            from billing.mercadopago import _webhook_secret
            if _webhook_secret():
                log.warning("MP webhook with INVALID signature, rejecting")
                return Response(status_code=401)
        # ← si el secret está vacío, NO hay return: sigue procesando el evento
```

Con `MP_WEBHOOK_SECRET` vacía en producción, el módulo devuelve `sig_valid=False` (fail-closed
correcto) y el endpoint **no lo rechaza igual**, porque `_webhook_secret()` es `""`. El resultado es
exactamente el estado anterior al fix: el evento se procesa sin ninguna autenticación. El comentario
que justifica el `if` ("en sandbox sin secret pasamos") describe el mundo previo al fix, cuando el
módulo devolvía `True` en ese caso; hoy devuelve `False` y el comentario quedó obsoleto sobre la
línea que causa el agujero.

El contraste está en el mismo archivo y a 700 líneas: el webhook de Rebill (endpoint #24, la vía
**viva** de cobro) sí es fail-closed, porque el caller respeta el veredicto del módulo:

```python
# main.py:26886-26893
        if not sig_valid:
            log.warning("Rebill webhook auth failed (%s) — rechazado. ...", auth_reason)
            return Response(status_code=401)
```

**Cómo se explota en la práctica**

`POST https://<host>/api/billing/webhook` sin cabecera `x-signature`, con
`{"type":"payment","data":{"id":"<cualquiera>","preapproval_id":"<id de sub>","status":"rejected"}}`.
El flujo entra a `_process_payment_event` (`main.py:27686-27746`), donde:

1. `UPDATE subscriptions SET last_payment_id=?, updated_at=... WHERE mp_subscription_id=?` — **los dos
   valores los pone el atacante**, sobre la fila de suscripción de otra persona, sin sesión.
2. Se hace `JOIN users` sobre esa fila y **se manda un mail al usuario real**: `send_receipt`
   ("te cobramos $X") si el status parece aprobado, o `send_payment_failed` ("tu pago falló") si es
   `rejected`/`cancelled`. Correo saliente desde el dominio de Rendi, con datos de facturación
   reales, disparado por un anónimo: es material de phishing de primera calidad, firmado por la marca.
3. Se quema la idempotencia (`last_payment_id`, y por la vía `preapproval` también
   `welcome_email_sent_at` / `cancellation_email_sent_at`), de modo que el mail legítimo posterior
   ya no sale.

La vía `type:"preapproval"` (`_process_preapproval_event` → `UPDATE users SET tier=...`) exige que
`get_preapproval` responda; sin `MP_ACCESS_TOKEN` levanta `RuntimeError` y el `except Exception` de
`main.py:27580` la traga devolviendo 200. Con el token puesto, el `external_reference` viene de MP y
ata el tier al usuario correcto, así que **no** veo por ahí una escalada de tier cruzada — el daño
concreto y no condicionado es el de los puntos 1 y 2.

Lo que hace falta saber es un `mp_subscription_id` válido. No son enumerables por fuerza bruta
razonable, pero tampoco son secretos: son ids de preapproval de MP, aparecen en URLs de checkout y
en el `/api/billing/status` de cada dueño. **El bypass de autenticación, en cambio, no está
condicionado a nada.**

**Qué queda expuesto**

Escritura no autenticada sobre `subscriptions` de terceros y envío no autenticado de correo
transaccional de facturación a usuarios reales desde el dominio de Rendi. No hay lectura de cartera
por esta vía.

**Otros call sites del mismo patrón** (grep de los dos webhooks del repo):

- `main.py:27501` `/api/billing/webhook` (MP) — **roto**, es este hallazgo.
- `main.py:26809` `/api/billing/rebill-webhook` — **correcto**, fail-closed. Es 1 de 2 call sites
  arreglado: la regla de propagación del proyecto, otra vez.
- `billing/mercadopago.py:207` y `billing/rebill.py:379-398` — los dos módulos están bien; el
  problema es del caller, no del verificador.
- Deriva: verificado con `git show origin/main:backend/main.py` → **sigue igual en `origin/main`,
  línea 27557**. No lo arregló la tanda F1.

**Solución de fondo**

Borrar la condición y respetar el veredicto del módulo, igual que hace el endpoint de Rebill:

```python
if not sig_valid:
    return Response(status_code=401)
```

`verify_webhook_signature` ya devuelve `True` en dev local sin secret, así que el caso de desarrollo
sigue funcionando sin el `if`. Y como MP está muerto (migrado a Rebill), la opción más honesta es
**borrar la ruta entera**: un endpoint no autenticado que nadie usa es superficie de ataque pura.
Si se quiere conservar por reversibilidad, que quede detrás de una env var `MP_ENABLED`.

---

### [MEDIO] H-2 · La memoria de IA que el asesor escribe en el cliente sobrevive a la revocación

**Evidencia:** ESTRUCTURAL.

**Dónde:** `main.py:29303` (`POST /api/ai/remember`), `main.py:34609-34622` y `main.py:35241-35256`
(las dos vías de revocación), `main.py:28336-28340` (dónde se consumen los hechos).

**Qué pasa**

`/api/ai/remember` no está en `CLIENT_CTX_EXEMPT_PREFIXES` — a propósito, según el comentario de
`main.py:2790`. Con contexto de cliente activo y `permission='read_write'`, el `uid` que llega a
`_atomic_insert_fact(conn, uid, ...)` es el **del cliente**, así que el hecho se graba en
`ai_user_facts` del cliente. Ese es el diseño buscado, y la escritura está bien acotada por
`user_id`. El problema es el ciclo de vida.

Cuando el vínculo se corta —por el asesor (`main.py:34621`) o por el propio cliente
(`main.py:35256`)— lo único que pasa es `UPDATE advisor_clients SET status='revoked', revoked_at=...`.
Grep de `ai_user_facts` en `main.py` (12 hits): **ninguna vía de revocación lo toca**. El comentario
del propio endpoint de revoke lo dice: "NO borra la data del cliente".

Los hechos siguen ahí y se siguen inyectando: `main.py:28336-28340` levanta los 25 activos más
recientes en cada chat del cliente, y el prompt los presenta como verdad declarada por el usuario.
Es decir: texto que escribió un tercero, que el cliente nunca tipeó, que su propio coach de IA va a
tratar como afirmación propia — indefinidamente, mucho después de que el tercero perdiera el acceso.

**Cómo se explota en la práctica**

Un asesor con `read_write` (o cualquiera que consiga ese token) llama `/api/ai/remember` con el
header del cliente hasta 50 veces (`MAX_ACTIVE_FACTS`). El cliente revoca. Los 50 hechos siguen
alimentando su chat. `_validate_fact_content` aplica un bloqueador de prompt-injection, pero eso
filtra la forma del texto, no la **autoría**: una afirmación falsa y bien redactada
("acordamos concentrar todo en X") pasa el filtro perfectamente y va a sesgar cada respuesta.

**Qué queda expuesto**

Integridad de la memoria de IA del cliente, con persistencia más allá de la relación que la
autorizaba. El cliente puede verlos y borrarlos (`GET /api/ai/facts`, `DELETE /api/ai/facts/{id}`),
pero tiene que saber que existen y que no los escribió él: `ai_user_facts` guarda `source`
(`user_correction` / `ai_inferred` / `manual`) y **no guarda quién los escribió**, así que ni la UI
ni el propio cliente pueden distinguir los suyos de los del asesor.

**Otros call sites del mismo patrón**

Grep de escrituras del tramo que persisten contenido en la cuenta del cliente y sobreviven a la
revocación: `ai_user_facts` (este), y las de import (`/api/imports/preview` y
`/api/imports/tenencia/preview`, endpoints #42 y #43) que crean batches y operaciones en la cuenta
del cliente. La diferencia es que un import queda visible como batch en el historial, con su origen;
un "hecho" de IA queda indistinguible de lo que el cliente escribió. Fuera de mi tramo, hay que
revisar el resto de `/api/ai/*` y la cascada de revoke completa — no es mi rango.

**Solución de fondo**

Añadir `written_by_uid` a `ai_user_facts` y estampar el `request.state.rendi_auth_uid` cuando difiere
del `uid` efectivo. Con eso: la UI del cliente puede etiquetar "lo anotó tu asesor", y la revocación
puede desactivar (`is_active=0`, no borrar — se mantiene el historial de auditoría) los hechos
escritos por el asesor que se va. La columna es la que falta; sin ella el problema no tiene fix
posible, sólo mitigaciones.

---

### [MEDIO] H-3 · `GET /api/fundamentals/{ticker}` escribe una tabla global, sin allowlist, sin rate-limit

**Evidencia:** ESTRUCTURAL.

**Dónde:** `main.py:26153` (endpoint) → `main.py:22063-22090` (`_build_fundamentals_response`) →
`main.py:21080-21095` (`_yf_cache_write`).

**Qué pasa**

Es una **escritura por GET**, que es justo el punto 5 del encargo. El path param `ticker` no tiene
allowlist, ni validación de formato, ni tope de longitud (`ticker: str` pelado). Se normaliza con
`.strip().upper()` y se pasa a cinco fetchers cacheados; cada uno que devuelve algo hace un UPSERT
sobre `yfinance_cache`, una tabla **global** (clave `(ticker, kind)`, sin `user_id`):

```python
# main.py:21086-21093
        conn.execute(
            """INSERT INTO yfinance_cache(ticker, kind, fetched_at, payload_json)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(ticker, kind) DO UPDATE SET ...""",
            (ticker, kind, str(_time.time()), json.dumps(payload, default=str)),
        )
        conn.commit()
```

Tres consecuencias, en orden de importancia:

1. **Salta el control de `read_write`.** `_resolve_client_context` exige `read_write` sólo para
   métodos que no son GET/HEAD/OPTIONS (`main.py:2807`). Como esto es un GET que escribe, un asesor
   con vínculo **de sólo lectura** (`permission='linked'`, la v1) escribe en la tabla global desde
   el contexto de un cliente. El permiso de sólo lectura no es de sólo lectura acá.
2. **Amplificación de tráfico saliente.** Cada string nuevo dispara hasta 5 requests HTTP del server
   de Rendi a Yahoo. Sin rate-limit — nótese que el endpoint hermano
   `POST /api/fundamentals/ai-summary` (#13) **sí** tiene `_check_rate_limit(..., 10, 60, ...)`, y
   este no. Es el mismo par "fix aplicado en un call site y no en el otro".
3. **Crecimiento no acotado** de `yfinance_cache`: una fila por string arbitrario que algún fetcher
   haya respondido.

**Cómo se explota en la práctica**

Un usuario autenticado cualquiera itera `GET /api/fundamentals/<string>` con strings generados.
No hay 429 que lo pare. No hace falta ni contexto de cliente; el contexto sólo agrega que también
lo puede hacer un asesor de sólo lectura.

**Qué queda expuesto**

Ninguna cartera. Es defensa en profundidad: el control de escritura del plan asesor tiene una fuga
por diseño (GET que escribe), y falta un límite de recursos. Lo reporto en MEDIO y no más arriba
porque no cruza datos entre usuarios.

**Otros call sites del mismo patrón**

Barrí las 16 rutas GET de mi tramo buscando escrituras en el camino:

- `#12 /api/fundamentals/{ticker}` → **escribe** `yfinance_cache`. Único caso real.
- `#11 /api/tickers/search` → escribe sólo `_symsearch_cache`, en memoria del proceso. Aceptable.
- `#19 /api/billing/trial`, `#20 /api/plan/features`, `#23 /api/billing/preview-change-plan`,
  `#27 /api/billing/status`, `#29 /api/ai/usage` → grep de `UPDATE|INSERT|DELETE|commit` sobre
  `trial.status`, `plan.get_plan_features`, `credits.preview_plan_change`, `quota.get_current_usage`
  y `quota.get_tier`: **cero hits**. Limpios.
- `#3` y `#6` (probes de admin) → documentados como read-only; confirmado, no tocan DB.

**Solución de fondo**

El fix del ticket es validar el ticker contra un patrón (`^[A-Z0-9.\-]{1,12}$`) y ponerle el mismo
`_check_rate_limit` que su hermano `ai-summary`. El fix de fondo es que la regla "las escrituras
exigen `read_write`" no puede depender del verbo HTTP: si el criterio es el método, cualquier GET
que escriba la burla. El control debería estar donde se escribe, no en el resolver de contexto.

---

### [MEDIO] H-4 · La cuota de IA del asesor se le cobra al cliente, con lente `pro` forzada

**Evidencia:** DEDUCIDO — leí el código y el comentario que lo justifica; no lo ejecuté.

**Dónde:** `main.py:28313-28325` (chat), `main.py:25936-25941` (analyze), `main.py:2790-2794`
(la nota de diseño).

**Qué pasa**

Es una **decisión deliberada y documentada**, no un parche, y la trato como tal: el comentario de
`main.py:2790` dice que `/api/ai` no está exento a propósito y que "la cuota corre en los contadores
del cliente… F5 centraliza la cuota en el asesor". Lo reporto igual porque el efecto de recursos es
real y F5 no está.

Con contexto activo, `quota.can_chat(conn, uid, ...)` recibe el uid del **cliente**. Además, si el
cliente es free/plus y quien mira es advisor, el tier se fuerza a `pro`:

```python
# main.py:28320-28325
        if uid != _lens_auth and tier in ("free", "plus") \
                and quota.get_tier(conn, _lens_auth) == "advisor":
            tier = "pro"
            _lens_override = "pro"
```

Con lo cual el asesor no consume 6 chats semanales del cliente sino hasta 60, sobre los contadores
del cliente. Lo mismo en `/api/ai/analyze` (`main.py:25936-25941`), con el comentario que lo declara
consistente con el chat.

**Cómo se explota en la práctica**

No hace falta mala fe: un asesor con 20 clientes que trabaja normalmente les vacía la cuota semanal.
Con mala fe (o con un token de asesor comprometido), agotar la cuota de IA de toda la cartera de
clientes es un bucle de 60 requests por cliente. El cliente entra a su cuenta y su coach le dice que
no le quedan consultas, sin ninguna explicación de por qué.

**Qué queda expuesto**

Disponibilidad de una feature de pago, cliente por cliente. Sin fuga de datos.

**Otros call sites del mismo patrón**

Los dos endpoints de mi tramo que cobran cuota bajo contexto de cliente: `#32 /api/ai/chat` y
`#10 /api/ai/analyze`. `#13 /api/fundamentals/ai-summary` reusa `ai.quota` con el mismo `uid`
efectivo, así que es el tercero. `#31 /api/diagnostics/dismiss` también descuenta contra el cliente
(`reserve_diag_dismiss(conn, uid)`), aunque el cupo es sólo para Free y el impacto es menor.
Son 4 sitios con la misma decisión; F5 tiene que cubrirlos a los 4, no a los 2 que están comentados.

**Solución de fondo**

La que ya está planificada (F5): cobrar la cuota al `request.state.rendi_auth_uid` cuando hay
contexto, no al `uid` efectivo. Hasta entonces, lo mínimo honesto es que la respuesta 429 del cliente
distinga "la gastaste vos" de "la gastó tu asesor" — hoy son el mismo mensaje.

---

### [MEDIO] H-5 · `/api/ai/chat` usa una conexión ya cerrada: 500 en el camino del asesor, y el guardarraíl no se aplica

**Evidencia:** **MEDIDO** el mecanismo; DEDUCIDO el alcance (no pude construir un vínculo asesor real).

**Dónde:** `main.py:28342` (`conn.close()`) vs `main.py:28412` (uso de `conn`).

**Qué pasa**

El bloque que resuelve tier, cuota, perfil y hechos cierra su conexión en un `finally`:

```python
# main.py:28340-28342
        ).fetchall()
    finally:
        conn.close()
```

Setenta líneas más abajo, ya fuera del `try`, se vuelve a usar esa misma variable:

```python
# main.py:28412
    elif _lens_override == "pro" or (uid != _lens_auth and quota.get_tier(conn, _lens_auth) == "advisor"):
        base_system = base_system + _AI_CHAT_SYSTEM_ADVISOR_IN_CLIENT
```

`quota.get_tier(conn, ...)` hace `conn.execute` (verificado en `ai/quota.py:148`). El
cortocircuito del `or` salva el caso en que `_lens_override == "pro"` — que es exactamente el caso
del cliente free/plus. Pero cuando el cliente es **pro / advisor / admin**, `_lens_override` queda en
`None`, la segunda rama se evalúa, `uid != _lens_auth` es verdadero, y se ejecuta contra una
conexión cerrada.

MEDIDO — `audit/_scripts/poc_closed_conn.py`, sqlite3 en memoria, reproduce el mecanismo:

```
$ python3 audit/_scripts/poc_closed_conn.py
RAISE: ProgrammingError: Cannot operate on a closed database.
```

La excepción no está dentro de ningún `try` del endpoint → 500 al cliente.

**Cómo se explota en la práctica**

No es un ataque: es el camino normal. Un asesor abre el chat dentro de un cliente que tiene plan Pro
—el cliente que más paga— y recibe un 500. Lo reporto en la auditoría de seguridad y no como bug de
producto por la segunda mitad: **la línea que revienta es la que agrega
`_AI_CHAT_SYSTEM_ADVISOR_IN_CLIENT`**, el bloque de sistema que le dice al modelo que está mirando la
cuenta de otra persona. En la rama que sí funciona (cliente free/plus, `_lens_override == "pro"`) el
guardarraíl se aplica; en la que revienta no llega a aplicarse nunca. Si alguna vez alguien "arregla"
esto envolviéndolo en un `try/except` en vez de reabrir la conexión, el resultado va a ser un chat de
asesor sobre la cuenta de un cliente Pro **sin** el bloque de contexto: el modelo hablándole al
asesor como si la cartera fuera suya. Ese es el desenlace que hay que evitar.

**Qué queda expuesto**

Hoy: disponibilidad del chat del asesor sobre clientes de tier pago. Mañana, si se parchea mal: el
prompt de guardarraíl del contexto de cliente.

**Otros call sites del mismo patrón**

Comprobé el gemelo: `/api/ai/analyze` (`main.py:25936-25941`) hace la misma resolución de lente
**dentro** del `try` con la conexión viva, y no tiene el bug. Es 1 de 2. Vale la pena un barrido de
`conn` usada después de su `finally: conn.close()` en todo `main.py` — fuera de mi tramo, no lo hice.

**Solución de fondo**

Calcular el flag de la lente **antes** de cerrar la conexión (junto a `_lens_override`, que ya se
calcula ahí adentro) y usar el booleano después. La condición de `main.py:28412` recalcula algo que
el bloque de arriba ya sabía: no debería consultar la base una segunda vez.

---

### [BAJO] H-6 · `GET /api/ai/topics` sin autenticación

**Evidencia:** ESTRUCTURAL. **Dónde:** `main.py:26308-26313`.

Es el único endpoint del tramo sin ningún `Depends` de auth, y está declarado como tal
("Endpoint público sin auth — útil para que el frontend descubra topics sin hardcodear"). Devuelve
`list_topics()`, es decir las claves de `REGISTRY` (`ai/registry.py:63-114`): nombres de topics, sin
datos de nadie. Lo dejo en BAJO y no en OK por un detalle: la lista incluye `book.composition_type` y
`book.composition_sector`, los topics del libro del asesor, así que un anónimo puede inventariar
features de un plan que todavía no está anunciado. Es divulgación de roadmap, no de datos.
**Solución:** ponerle `get_current_user`; el frontend ya está autenticado cuando lo llama.

### [BAJO] H-7 · Rate-limit de recomendaciones compartido entre todos los usuarios de una IP

**Evidencia:** ESTRUCTURAL. **Dónde:** `main.py:29218`.

`_check_rate_limit` arma la clave como `f"{ip}|{suffix}"` (`main.py:396-397`). Casi todos los
llamadores del tramo meten el uid en el sufijo (`f"ai_chat:{uid}"`, `f"subscribe:{uid}"`,
`f"cancel:{uid}"`, `f"ai_remember:{uid}"`, `f"diag_dismiss:{uid}"`…). Este no:
`_check_rate_limit(request, max_calls=5, window_seconds=3600, suffix="recommendation")`. Resultado:
5 recomendaciones por hora **por IP, entre todos**. Detrás de un NAT corporativo o de un CGNAT móvil,
un usuario le consume la cuota a los demás — una denegación de servicio menor, involuntaria y
difícil de diagnosticar. Nota positiva: `_ip_del_cliente` (`main.py:335-360`) lee `X-Forwarded-For`
**por la derecha**, tomando la entrada pública más a la derecha, así que el rate-limit no es
falsificable inyectando XFF; ese agujero ya está cerrado y bien documentado.
**Solución:** `suffix=f"recommendation:{uid}"`, como los otros doce llamadores.

### [BAJO] H-8 · Mutaciones de admin con el email del usuario en el query string

**Evidencia:** ESTRUCTURAL. **Dónde:** `main.py:19698` (`email: str`), `main.py:19845` (idem
`grant-comp`), `main.py:20274` (`broker: str` en `wipe-broker-data`).

Los tres son `POST` con los parámetros como query string (FastAPI trata un `str` sin `Body`/`Form`
como query param). El email del usuario objetivo termina en la URL: logs de acceso de Railway,
historial del navegador, `Referer` si la página enlaza afuera. Son datos personales de clientes de
una app financiera viajando por el canal que más se loguea y menos se rota.
**Solución:** pasarlos por body (`BaseModel`). Sin cambio funcional para el panel de admin.

### [BAJO/REVISAR] H-9 · Los topics `book.*` no exigen tier advisor en `/api/ai/analyze`

**Evidencia:** DEDUCIDO. **Dónde:** `main.py:25923-25929`.

`get_topic(screen)` resuelve contra `REGISTRY` sin mirar el tier: cualquier usuario autenticado puede
pedir `screen="book.composition_type"`. **Verifiqué que no hay fuga de datos**:
`ai/builders/book_composition.py:127-132` ignora `conn` y `user_id` por completo y arma el packet
sólo con `**params`, es decir con lo que mande el propio cliente. Lo mismo `distribution.py:164-169`.
Así que el peor caso es un usuario Free gastando su propia cuota para que el LLM le aplique el prompt
del libro del asesor a datos que él mismo inventó. Es un bypass cosmético de paywall, no un cruce de
cuentas. Lo dejo en REVISAR porque es una asimetría sin explicación — el resto del producto sí gatea
por tier— y las asimetrías sin explicación, en este repo, suelen ser el bug.
**Solución:** rechazar `screen.startswith("book.")` si `quota.get_tier(...) != "advisor"`.

### [BAJO] H-10 · Los cuatro endpoints de subida de archivos del tramo no tienen rate-limit

**Evidencia:** ESTRUCTURAL. **Dónde:** `main.py:29464`, `29496`, `29661`, `30439`.

Los caps por request existen y están bien puestos: máximo 20 archivos (`main.py:30465`), 5 MB
totales (`importing/pipeline.py:35-36`) y lectura **chunked** que aborta al pasarse, en vez de
bufferear primero — está claramente pensado contra el OOM. Lo que no hay es un límite de
**frecuencia**: ninguno de los cuatro llama a `_check_rate_limit`. Un usuario autenticado puede
encadenar subidas de 5 MB con parsing de xlsx/PDF, que es CPU cara, indefinidamente. Contrasta con
`/api/ai/chat` (12/60s) y `/api/ai/remember` (20/h), que sí lo tienen para proteger un recurso caro.
**Solución:** el mismo `_check_rate_limit(request, ..., suffix=f"import:{uid}")` en los cuatro.
Ojo con `#40` y `#41`, que hoy no reciben `request` en la firma y habría que agregárselo.

---

## Lo que NO pude verificar (dicho explícitamente)

1. **Si `MP_WEBHOOK_SECRET` está vacía en producción.** Es la condición que convierte H-1 de bug
   latente en agujero abierto. No leo env vars de Railway y no hago peticiones a la app desplegada.
   Lo que sí es seguro: el `if` está mal escrito, contradice el fix de su propio módulo, y sigue así
   en `origin/main`. Si la variable está puesta, H-1 es una bomba desarmada esperando el día que
   alguien rote el secret y lo borre; si está vacía, está armada. **Verificalo primero.** Lo mismo
   para `MP_ACCESS_TOKEN`, que decide si la vía `preapproval` del webhook hace algo o se traga la
   `RuntimeError`.
2. **La ruta del asesor, en ejecución.** H-2, H-4 y el alcance de H-5 son lectura de código: no armé
   un entorno con `advisor_clients` poblada ni un vínculo `read_write`, así que no ejecuté un solo
   request con `X-Rendi-Client-Id`. El mecanismo de H-5 sí está medido; lo que no medí es que la rama
   del `elif` se alcance en producción.
3. **Los 33 "OK" son OK *para las cinco preguntas del encargo*** (sesión, propiedad del recurso,
   filtro por dueño en cada query, prefijos exentos, escrituras por GET). No auditė de esos endpoints
   la validación de entrada, la lógica de negocio ni los cálculos —los cálculos son de la tanda 1A y
   quedan explícitamente fuera.
4. **El interior de los parsers de import.** `#40`-`#43` reciben xlsx, CSV y PDF de terceros y los
   entregan a `importing/pipeline.py`. Verifiqué la autorización y los caps de tamaño del endpoint;
   **no** audité los parsers por XXE, zip-bomb ni deserialización. Es superficie real y merece su
   propio pase.
5. **Barrido global de `conn` usada después de `close()`.** Encontré el de `main.py:28412` siguiendo
   H-5. No corrí la búsqueda sobre las 38.029 líneas del archivo; puede haber más.
6. **Cruce con F1:** ninguno de mis 10 hallazgos cae en los archivos de la tanda de fixes
   (`snapshots_job.py`, persister de FX, `reconcile-cash`, `CashFlowIn`, recalc de P&L, amortización
   manual, `SellModal`/`PositionsMobile`). **Sin cruce que marcar.**

---

## CORRECCIÓN DEL ENSAMBLADO (2026-09-08) — H-1 baja de ALTO a MEDIO

El founder confirmó que `MP_WEBHOOK_SECRET` no existe en Railway: **el fail-open está armado**,
eso se sostiene. Pero la frase *"UPDATE subscriptions de terceros con valores propios"* es
**incorrecta** y se corrige acá.

`_process_preapproval_event` **no confía en el payload**: llama a `mercadopago.get_preapproval()`
y usa la respuesta de Mercado Pago. Con un id inventado, `pa` viene vacío y la función retorna sin
hacer nada. Y `_access_token()` lanza excepción sin `MP_ACCESS_TOKEN`, que el `except Exception`
de `main.py:27587` traga devolviendo 200 — o sea que esa rama probablemente ni corre.

La superficie real es la otra rama, `_process_payment_event`, que **sí** lee `pa_id` y
`data_status` del JSON posteado. Requiere conocer o adivinar un `mp_subscription_id` válido, y
permite escribir `last_payment_id` y disparar mails de "recibo" o "pago fallido" a usuarios reales
desde el dominio de Rendi. No otorga tier pago.

**Severidad corregida: MEDIO.** La recomendación (borrar la ruta) no cambia.
Detalle completo en `5a-resumen.md`, §Corrección 3.
