## 11 · Facturación, suscripciones, trial y planes

Auditado sobre `origin/main` @ `b74f450f` (2026-09-05). Todas las rutas son relativas a la raíz del repo.

Módulo: `backend/billing/` — 4.968 líneas en 8 archivos.

| archivo | líneas | qué hace |
|---|---:|---|
| `backend/billing/__init__.py` | 7 | docstring del paquete (menciona 3 submódulos de 7) |
| `backend/billing/pricing.py` | 145 | constantes de precio ARS + IVA |
| `backend/billing/mercadopago.py` | 294 | cliente MP (preapproval + firma de webhook) |
| `backend/billing/rebill.py` | 571 | cliente Rebill (payment links + auth de webhook) |
| `backend/billing/subscriptions.py` | 598 | cron diario del ciclo de vida |
| `backend/billing/credits.py` | 477 | crédito tiempo-based (prorrateo Rendi-managed) |
| `backend/billing/trial.py` | 1.200 | free trial 15 días + "probar Pro" sobre Plus + embudo |
| `backend/billing/emails.py` | 1.676 | 28 emails transaccionales (Resend) |

La lógica de endpoints NO vive acá: está toda en `backend/main.py` (≈26.300–27.800 para el flujo de usuario, ≈19.000–20.000 para admin).

---

### 11.1 Procesadores de pago

Hay **dos** integraciones en el árbol. **La activa es Rebill.** [V]

| procesador | crea suscripciones nuevas | recibe webhooks | cancela | estado real |
|---|---|---|---|---|
| **Rebill** | ✅ `backend/main.py:26560` (`rebill.create_payment_link`) | ✅ `POST /api/billing/rebill-webhook` (`backend/main.py:26809`) | ✅ `backend/main.py:27357`, `backend/main.py:26727`, `backend/main.py:3825` | **ACTIVO** |
| **Mercado Pago** | ❌ nadie llama `create_preapproval` | ✅ `POST /api/billing/webhook` (`backend/main.py:27501`) sigue montado | ❌ `cancel_preapproval` sin callers | **ZOMBI** |

**Cómo se elige: NO hay flag ni env var.** [V] La elección está **hardcodeada en el código del endpoint**: `/api/billing/subscribe` importa `from billing import rebill` (`backend/main.py:26529`) y punto. El docstring lo dice explícito:

> `backend/main.py:26522-26523` — "NOTA: migramos de Mercado Pago a Rebill (commit X). MP queda muerto pero el código está en mercadopago.py por si hay que revertir."

Verificación de que MP está muerto para altas [V]: `grep create_preapproval` fuera de `mercadopago.py` solo devuelve tests (`backend/tests/test_billing.py:43,77`). Lo mismo con `cancel_preapproval`: cero callers de producción.

Lo que **sí sigue vivo del lado MP** [V]:
- `POST /api/billing/webhook` (`backend/main.py:27501`) — sigue registrado y procesa eventos.
- `POST /api/billing/sync` (`backend/main.py:27420`) — llama `mercadopago.get_preapproval` vía `_process_preapproval_event`. El frontend ya no lo usa (`frontend/src/pages/BillingReturn.jsx:18-19`: *"eso quedó muerto pero el endpoint todavía existe en el backend hasta que limpiemos"*), pero cualquier usuario logueado puede pegarle.
- `subscriptions._sync_authorized_with_mp` (`backend/billing/subscriptions.py:556`) — consulta MP, pero **nadie la llama** (ver 11.10).

#### Config por env var

`backend/billing/rebill.py` (solo nombres, sin valores):

| variable | dónde | para qué |
|---|---|---|
| `REBILL_API_KEY` | `backend/billing/rebill.py:39` | header `x-api-key`; el prefijo `sk_test_`/`sk_live_` define sandbox vs prod (`rebill.py:87-89`, `rebill.py:248-251`) |
| `REBILL_WEBHOOK_SECRET` | `backend/billing/rebill.py:46` | HMAC del webhook (preferido) |
| `REBILL_WEBHOOK_TOKEN` | `backend/billing/rebill.py:65` | token en el query string `?token=` (fallback) |
| `REBILL_PLAN_ID_{PLAN}_{PERIOD}` | `backend/billing/rebill.py:72` | 4 combinaciones: `PLUS_MONTHLY`, `PLUS_ANNUAL`, `PRO_MONTHLY`, `PRO_ANNUAL` |
| `MP_FRONTEND_BASE_URL` | `backend/billing/rebill.py:80` | base del frontend (Rebill rechaza `localhost` → cae a `https://rendi.finance`) |
| `RENDI_ENV`, `RAILWAY_ENVIRONMENT` | `backend/billing/rebill.py:105-107` | detección de producción |

`backend/billing/mercadopago.py`: `MP_ACCESS_TOKEN` (`:43`), `MP_WEBHOOK_SECRET` (`:81`), `MP_FRONTEND_BASE_URL` (`:63`), `MP_BACK_URL_BASE` (`:60`), `MP_ENV` (`:119`), `MP_TEST_PAYER_EMAIL` (`:120`).

`backend/billing/trial.py`: `TRIALS_ENABLED` (`:48`), `TRIALS_MONTHLY_CAP` (`:57`).
`backend/billing/emails.py`: `RESEND_API_KEY` (`:41`), `EMAIL_FROM` (`:47`), `EMAIL_FROM_NOREPLY` (`:53`), `EMAIL_FROM_SUPPORT` (`:63`), `ADMIN_NOTIFY_EMAIL` (`:951`, `:1012`).

#### Validación de config al arrancar [V]

`rebill.validate_config()` (`backend/billing/rebill.py:220-304`) corre al startup desde `_validate_rebill_config()` (`backend/main.py:32120-32142`). Detecta: API key ausente, mismatch `sk_live_` + plan IDs `test_pln_`, plan IDs faltantes, y ausencia de auth de webhook. **No bloquea el startup** — solo loguea (`backend/main.py:32137-32140`).

#### Detección de "estamos en producción" [V]

`rebill.is_likely_production()` (`backend/billing/rebill.py:92-112`) devuelve True si CUALQUIERA: `RENDI_ENV=prod`, `RAILWAY_ENVIRONMENT=production`, o `REBILL_API_KEY` existe y no empieza con `sk_test_`. El comentario documenta el bug que arregló (2026-05-31): antes solo miraba `RENDI_ENV`, que no estaba seteada en Railway, y en producción real se aceptaba **cualquier webhook sin firma** (`backend/billing/rebill.py:408-414`).

---

### 11.2 Catálogo de planes y precios

⚠️ **Hay TRES fuentes de precio distintas y las tres discrepan.** [V]

#### (a) `backend/billing/pricing.py` — ARS + IVA

| plan | período | base ARS | IVA ARS (21 %) | **total ARS** | USD display | línea |
|---|---|---:|---:|---:|---|---|
| Plus | mensual | 4.950 | 1.040 | **5.990** | `"4"` | `pricing.py:34-37` |
| Plus | anual | 49.580 | 10.410 | **59.990** | `"3.50"` (mensual eq.) | `pricing.py:42-45` |
| Pro | mensual | 10.000 | 2.100 | **12.100** | `"6.99"` | `pricing.py:49-51`, `:66` |
| Pro | anual | 102.000 | 21.420 | **123.420** | `"5.99"` (mensual eq.) | `pricing.py:55-57`, `:67` |

Constantes de cálculo: `IVA_PCT = 0.21`, `ANNUAL_DISCOUNT_PCT = 0.15` (`pricing.py:61-62`).

**Este archivo es código muerto en producción.** [V] Su único consumidor es `mercadopago.create_preapproval` (`backend/billing/mercadopago.py:34`, `:111`), que no tiene callers. Ningún endpoint expone `get_all_plans()` (`grep` de `get_all_plans` / `get_pricing` fuera de `pricing.py` y `mercadopago.py`: **cero resultados**).

**Contradicción interna** [V]: el docstring de `get_pricing` dice *"Plus no tiene plan anual (todavía). Pedir plus+annual cae a plus+monthly"* (`pricing.py:78`), pero el código en `pricing.py:81-93` **sí devuelve** el shape anual de Plus. El docstring de módulo repite lo mismo (`pricing.py:26`).

#### (b) `frontend/src/pages/Planes.jsx` — lo que ve el usuario

| plan | período | ARS | línea |
|---|---|---:|---|
| Plus | mensual | **5.990** | `frontend/src/pages/Planes.jsx:44` |
| Pro | mensual | **13.990** | `frontend/src/pages/Planes.jsx:45` |
| Plus | anual | **59.900** | `frontend/src/pages/Planes.jsx:47` |
| Pro | anual | **139.900** | `frontend/src/pages/Planes.jsx:48` |
| Plus anual (equiv. mensual) | | 4.992 | `frontend/src/pages/Planes.jsx:52` |
| Pro anual (equiv. mensual) | | 11.658 | `frontend/src/pages/Planes.jsx:53` |

Descuento anual real declarado: 16,7 % (`Planes.jsx:47-48`), no el 15 % de `pricing.py:62`.

**Divergencia con `pricing.py`:** Pro mensual 13.990 vs 12.100 (+15,6 %); Pro anual 139.900 vs 123.420 (+13,4 %); Plus anual 59.900 vs 59.990.

#### (c) `backend/billing/credits.py` — el precio que gobierna el prorrateo

```
PLAN_PRICES_USD = {
    ('plus', 'monthly'):  4.0,
    ('plus', 'annual'):  40.0,
    ('pro',  'monthly'):  9.0,
    ('pro',  'annual'):  90.0,
}
PERIOD_DAYS = {'monthly': 30.0, 'annual': 365.0}
```
`backend/billing/credits.py:38-48`

Pro mensual = **USD 9,00** acá, contra `USD_MONTHLY_DISPLAY = "6.99"` en `pricing.py:66`. El propio comentario admite la deuda: *"Mantener sincronizado con Planes.jsx y los plan IDs de Rebill"* (`credits.py:35`).

`daily_rate(plan, period) = price / days` (`credits.py:51-58`). Rates efectivos: Plus mensual 0,1333 USD/d; Plus anual 0,1096; Pro mensual 0,30; Pro anual 0,2466.

#### (d) El precio que se cobra de verdad

**Ninguno de los tres.** [V] El monto lo define el **plan configurado en el dashboard de Rebill**: `create_payment_link` manda solo `{"plan": {"id": plan_id}}` (`backend/billing/rebill.py:150`), sin `amount`. El precio real está fuera del repo, en Rebill, resuelto por `REBILL_PLAN_ID_*`. La moneda del payment method está hardcodeada en `"ARS"` (`rebill.py:158-160`) con un comentario que explica que debe matchear la del plan o Rebill devuelve 400.

Consecuencia [I, inferido de `rebill.py:148-161` + `main.py:26610`]: el backend **nunca sabe cuánto se cobró** al crear la suscripción. La fila se inserta con `amount_ars = 0` literal (`backend/main.py:26610`), y `amount_usd` solo se llena si el webhook trae un `amount` (`main.py:26988-26994`).

#### Qué incluye cada plan

Fuente: `backend/ai/plan.py:45-134` (dict `PLAN_LIMITS`); los IDs de feature canónicos en `backend/ai/plan.py:31-40`.

| | free | plus | pro | advisor | admin |
|---|---|---|---|---|---|
| `brokers_max` | (ver `plan.py`) | 3 | ∞ | ∞ | ∞ |
| `alerts_max` | — | 25 | ∞ | ∞ | ∞ |
| `insights_diagnostic_visible` | — | 6 | ∞ | ∞ | ∞ |
| `behavioral_tags_visible` | — | 6 | ∞ | ∞ | ∞ |
| `ai.followup` | ✗ | ✗ | ✓ | ✓ | ✓ |
| `ai.hub` | ✗ | ✗ | ✗ (no liberado) | ✗ | ✓ |
| `comportamiento.full` | ✗ | ✗ (parcial 6/12) | ✓ | ✓ | ✓ |
| `insights.distribucion_activo` | ✗ | ✓ | ✓ | ✓ | ✓ |
| `reportes.historicos` | ✗ | ✓ | ✓ | ✓ | ✓ |
| `export.csv` | ✗ | ✓ | ✓ | ✓ | ✓ |
| `alerts.pct_move` | ✗ | ✓ ★ | ✓ | ✓ | ✓ |
| `tax.helper` | ✗ | ✗ | ✗ (no construido) | ✗ | ✓ |

Líneas: `plan.py:66-81` (plus), `:82-97` (pro), `:102-117` (advisor), `:118-133` (admin).

---

### 11.3 Ciclo de vida de una suscripción

#### Valores reales de `subscriptions.status`

Barrido de todas las escrituras [V]:

| valor | quién lo escribe | archivo:línea |
|---|---|---|
| `pending` | alta desde `/api/billing/subscribe` | `backend/main.py:26610` |
| `authorized` | webhook `subscription.created` (update o insert) | `backend/main.py:27030`, `:27042`; MP: `main.py:27601` |
| `cancelled` | webhook cancel / defaulted / finished; `/api/billing/cancel`; cron de pendings stale | `backend/main.py:27183`, `:27193`, `:27383`; `backend/billing/subscriptions.py:546` |
| `superseded` | `/api/billing/change-plan` (la vieja al cambiar de plan) | `backend/main.py:26743` |
| `expired` | cron, cuando una `cancelled` pasó su `current_period_end` | `backend/billing/subscriptions.py:493` |
| `paused` | webhook `subscription.updated` status `paused` | `backend/main.py:27164` (parámetro) |
| `retrying` | idem, status `retrying` | `backend/main.py:27164` (parámetro) |

El comentario de la tabla menciona un `'failed'` (`backend/main.py:2020`) que **nadie escribe nunca** [V].

#### Diagrama de transiciones

```
                    POST /api/billing/subscribe
                    (rebill.create_payment_link)
                              │
                              ▼
                        ┌──────────┐
                        │ pending  │───────── >7 días sin pagar ────┐
                        └────┬─────┘   _cancel_stale_pending        │
                             │         subscriptions.py:523-553     │
        webhook subscription.created                                │
        (o subscription.updated status=active)                      │
        _rebill_activate  main.py:26965                             │
                             │                                      │
                             ▼                                      │
                      ┌────────────┐                                │
      ┌───────────────│ authorized │───────────────┐                │
      │               └──────┬─────┘               │                │
      │                      │                     │                │
      │   webhook            │  webhook            │  POST          │
      │   status=paused/     │  status=cancelled/  │  /api/billing/ │
      │   retrying           │  defaulted/finished │  change-plan   │
      │                      │  _rebill_cancel     │  main.py:26743 │
      ▼                      ▼                     ▼                │
┌───────────────┐      ┌───────────┐        ┌────────────┐          │
│ paused /      │      │ cancelled │◄───────│ superseded │          │
│ retrying      │      └─────┬─────┘        └────────────┘          │
│ (tier intacto)│            │                (terminal: _rebill_   │
└───────────────┘            │                 cancel NO la pisa,   │
                             │                 main.py:27186)       │
                             │◄───────────────────────────────────── ┘
                             │
              cron: current_period_end < now
              Y crédito vencido Y sin authorized
              _downgrade_expired_cancellations
              subscriptions.py:444-520
                             │
                             ▼
                       ┌──────────┐
                       │ expired  │   (terminal)
                       └──────────┘
```

**Clave del diseño: el `status` de la suscripción NO es lo que da acceso.** [V] Lo que gobierna el tier es `users.credit_active_until` + `users.tier`, no la fila de `subscriptions`. El comentario lo dice: *"Source of truth = users.credit_active_until (modelo de crédito tiempo-based)"* (`backend/billing/subscriptions.py:46`).

#### Máquina de estados del ACCESO (la que importa)

```
  users.tier = NULL/'free'
        │
        │  ① pago Rebill (webhook)     ② grant-comp admin      ③ free trial
        │  credits.grant_payment_credit  main.py:19925-19937   trial._start_tx
        │  credits.py:242-268                                  trial.py:343-357
        ▼
  users.tier ∈ {plus, pro, advisor}
  users.credit_active_until = <fecha futura>
  users.credit_anchor_* = plan/period/monto     ← el trial los deja en NULL a propósito
        │
        ├── ④ cambio de plan → credits.convert_plan (credits.py:301-413)
        │       reajusta credit_active_until al daily_rate del plan nuevo
        │
        ├── ⑤ renovación Rebill → grant_payment_credit EXTIENDE la ventana
        │
        ├── ⑥ trial día 8 → step_down_due_trials: tier 'pro'→'plus'
        │       NO toca credit_active_until (trial.py:481-560)
        │
        └── ⑦ credit_active_until < now
                ├─ EN TIEMPO REAL: quota.get_tier devuelve free/admin
                │    (backend/ai/quota.py:208-216, red de seguridad sin cron)
                └─ CRON 03:30 UTC: _downgrade_expired_credit pone tier=NULL
                     (subscriptions.py:161-239) + fila 'expiration' en credit_ledger
```

`quota.get_tier` (`backend/ai/quota.py:148-223`) es la red de seguridad en tiempo real: aunque el cron falle, un `tier='pro'` con `credit_active_until` vencido y sin sub `authorized` devuelve `free` (o `admin` si `is_admin`).

#### Qué dispara cada transición

| transición | disparador | código |
|---|---|---|
| free → pending | usuario aprieta "Suscribirme" | `frontend/src/pages/Planes.jsx:232` → `backend/main.py:26504` |
| pending → authorized + tier pago | webhook `subscription.created` | `backend/main.py:26913` → `:26965` |
| renovación (extiende crédito) | webhook `payment.created`/`payment.updated` con status aprobado | `backend/main.py:26917` → `:27201` |
| pago fallido | webhook `subscription.updated` status `retrying` | `backend/main.py:27156-27165` — **solo actualiza el status; no manda mail ni toca el tier** |
| cambio de plan | `POST /api/billing/change-plan` | `backend/main.py:26630` |
| cancelación voluntaria | `POST /api/billing/cancel` | `backend/main.py:27306` (frontend `frontend/src/pages/Config.jsx:1207`) |
| cancelación desde Rebill | webhook `subscription.updated` status cancelled/defaulted/finished | `backend/main.py:27154-27155` |
| baja a Free | cron diario 03:30 UTC | `backend/main.py:32551-32556` |
| baja a Free (real-time) | cualquier request | `backend/ai/quota.py:214-215` |
| baja al borrar la cuenta | `DELETE` de cuenta cancela en Rebill best-effort | `backend/main.py:3818-3827` |

#### ⚠️ El orden en change-plan no es estético

`backend/main.py:26646-26651` documenta que **primero se convierte el crédito y recién después se cancela en Rebill**, porque antes se cancelaba primero y una conversión fallida dejaba al usuario sin suscripción y sin plan nuevo. El peor caso hoy es un cobro de más, que se acredita como crédito.

---

### 11.4 ⚠️ Webhooks: firma, auth e idempotencia

#### Endpoints

| endpoint | procesador | archivo:línea |
|---|---|---|
| `POST /api/billing/rebill-webhook` | Rebill | `backend/main.py:26809` |
| `POST /api/billing/webhook` | Mercado Pago | `backend/main.py:27501` |

Ninguno de los dos tiene rate limit [V] (`_check_rate_limit` no aparece en ninguno de los dos handlers).

#### ¿Se valida la firma? — Rebill: **sí, con matices**

`rebill.verify_webhook_auth(raw_body, signature_header, url_token)` (`backend/billing/rebill.py:359-398`) devuelve `(ok, método, motivo)` con este orden:

1. **HMAC** (`REBILL_WEBHOOK_SECRET` seteado) → `verify_webhook_signature` (`rebill.py:401-504`). Si el secret está pero la firma no matchea → **rechaza, sin probar el token URL** (`rebill.py:382-384`).
2. **URL token** (`REBILL_WEBHOOK_TOKEN` seteado) → `verify_webhook_url_token` (`rebill.py:343-356`), `hmac.compare_digest` contra el query param `?token=`.
3. Sin ninguno de los dos **y `is_likely_production()` == True** → **rechaza** (`rebill.py:393-397`).
4. Sin ninguno **y dev local** → **acepta con warning** (`rebill.py:398`, método `dev_skip`).

El handler lee el token de la query (`backend/main.py:26857`) y los headers `x-rebill-signature` / `rebill-signature` (`backend/main.py:26828`). Si `sig_valid` es False devuelve **401** (`backend/main.py:26886-26892`), pero **después de haber guardado el evento en `billing_events`** para forensics/replay (`backend/main.py:26864-26883`).

**La verificación HMAC prueba 4 formatos distintos** porque *"la doc pública de Rebill v3 no expone el formato exacto del header"* (`rebill.py:415-425`): hex puro (`:450-452`), `sha256=<hex>` (`:454-458`), Stripe-style `t=..,v1=..` con dos manifests (`:460-482`), y base64 (`:484-492`). Todas con `hmac.compare_digest`.

**Realidad operativa** [V]: el docstring de `_webhook_url_token` (`rebill.py:49-65`) dice que Rebill v3 **no expone webhook signing**, así que el mecanismo real hoy es el token en la URL — *"Más débil que HMAC (no protege contra MITM si la URL queda loggeada), pero suficiente para evitar el bypass más obvio (POST anónimo)"*.

#### ¿Se valida la firma? — Mercado Pago: **NO, es fail-open** 🔴

`mercadopago.verify_webhook_signature` (`backend/billing/mercadopago.py:191-239`) sí implementa el manifest oficial de MP (`id:{data_id};request-id:{x_request_id};ts:{ts};`, HMAC-SHA256, `compare_digest` — `mercadopago.py:230-236`) y sin secret **en producción devuelve False** (`mercadopago.py:214-219`).

Pero el handler lo desarma:

```python
        if not sig_valid:
            # En sandbox sin secret pasamos (warning ya en mercadopago.py).
            # Sólo rechazamos si secret está configurado pero la firma falla.
            from billing.mercadopago import _webhook_secret
            if _webhook_secret():
                log.warning("MP webhook with INVALID signature, rejecting")
                return Response(status_code=401)
```
`backend/main.py:27554-27560`

**Si `MP_WEBHOOK_SECRET` no está seteada, `sig_valid` es False pero `_webhook_secret()` es vacío → no hay 401 y el evento se procesa igual.** [V] Es exactamente el patrón fail-open que `is_likely_production()` (`rebill.py:92-112`) se creó para eliminar, y que en el path de Rebill sí está cerrado (`main.py:26886-26892` rechaza siempre que `sig_valid` sea False).

Mitigación de hecho [I, inferido de `mercadopago.py:180-186` + `main.py:27567`]: el evento MP no confía en el payload — hace `GET /preapproval/{data_id}` con el `MP_ACCESS_TOKEN` propio, así que un `data_id` inventado no existe en la cuenta del merchant y el fetch falla. Y si MP quedó desmantelado, `MP_ACCESS_TOKEN` ausente hace que `_access_token()` levante (`mercadopago.py:45`), la excepción sube al `except` del handler y devuelve 200 (`main.py:27581-27583`). O sea: **el agujero es real en el código, pero la explotación requiere conocer un `preapproval_id` válido de la cuenta MP de Rendi.**

#### ¿Son idempotentes? ¿Un webhook repetido acredita dos veces?

**Protección principal — doble candado en `credit_ledger`:** [V]

1. **App-side**, antes de escribir: `grant_payment_credit` busca una fila previa con el mismo `(source_subscription_id, payment_id, kind='payment')` y si existe devuelve `{"duplicate": True}` sin extender nada (`backend/billing/credits.py:184-207`).
2. **DB-side**, índice único parcial:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_ledger_payment_dedup
    ON credit_ledger(source_subscription_id, payment_id, kind)
    WHERE payment_id IS NOT NULL AND source_subscription_id IS NOT NULL
```
`backend/main.py:2364-2368`. El `IntegrityError` de la carrera SELECT→INSERT se captura y el `with conn` revierte el UPDATE a `users` (`credits.py:269-284`).

**🔴 Pero el candado NO cierra cuando falta el `payment_id`.** [V] Ambas defensas exigen `payment_id` **y** `subscription_id` no nulos. En `_rebill_activate` el `payment_id` se extrae best-effort y puede quedar vacío — el propio comentario lo asume:

> `backend/main.py:26996-26998` — *"payment_id para idempotency del ledger — el subscription.created suele venir con un payment_id (el primer cobro). Si no está, queda None y el ledger no aplica el dedup (la sub.created solo viene una vez)."*

"La sub.created solo viene una vez" es una **suposición sobre el proveedor, no una garantía**. Si Rebill reintenta `subscription.created` (timeout, race del LB), o si llega un `subscription.updated` con `status=active` — que llama al MISMO `_rebill_activate` (`backend/main.py:27151-27153`) — sin `payment_id` en el payload, `grant_payment_credit` **extiende la ventana de crédito otra vez**: `credits.py:215-221` suma `period_days` sobre lo que ya había.

**🔴 Segunda vía de doble-acreditación**: `_rebill_activate` y `_rebill_record_payment` extraen el `payment_id` de listas de candidatos **con orden distinto**:

| función | orden de candidatos | línea |
|---|---|---|
| `_rebill_activate` | `data.payment.id` → `data.payment_id` → `payload.payment_id` | `backend/main.py:27000-27007` |
| `_rebill_record_payment` | `payload.payment_id` → `data.payment_id` → `data.payment.id` | `backend/main.py:27211-27218` |

Si un payload trae **dos** de esos campos con valores distintos, las dos funciones derivan claves de dedup distintas para el mismo cobro y el índice único no las une. [I — inferido de la asimetría de las dos listas; no encontré payload real que lo dispare.]

**Idempotencia de `billing_events`: no hay.** [V]
- El `INSERT` no tiene `ON CONFLICT` ni índice único: cada reintento crea una fila nueva (`backend/main.py:26871-26883` para Rebill, `:27540-27552` para MP).
- El marcado de procesado en Rebill es `UPDATE billing_events SET processed = 1 WHERE raw_payload = ?` — **matchea por el JSON entero como texto** (`backend/main.py:26924-26928`). Marca *todas* las filas con ese payload, y hace un full scan de texto (no hay índice sobre `raw_payload`; los índices son sobre `user_id` y `mp_data_id`, `backend/main.py:2064-2067`).
- El de MP es `WHERE mp_event_id = ?` (`backend/main.py:27577-27578`); si `mp_event_id` viene vacío (`str(payload.get("id") or "")` en `main.py:27528`), marca como procesados **todos** los eventos con id vacío.

**Otras idempotencias verificadas:**
- Cancelación (`_rebill_cancel`): el UPDATE tiene `AND status NOT IN ('superseded')` para no pisar un cambio de plan (`backend/main.py:27186`).
- Emails: `welcome_email_sent_at`, `cancellation_email_sent_at`, `expiration_reminder_sent_at` en `subscriptions` (`backend/main.py:2037-2039`).
- Aviso al admin: `send_plan_change_admin` no manda si `old_label == new_label`, lo que deduplica reintentos porque en el 2º el tier ya cambió (`backend/billing/emails.py:930-941`).
- Trial: PK `(user_id, kind)` en `trial_email_log`, marca-antes-de-mandar (`backend/billing/trial.py:596-608`).

**Otros hallazgos del webhook Rebill:**
- Sin `metadata.rendi_user_id` → 200 y descarta (`backend/main.py:26894-26896`). Si Rebill deja de propagar la metadata del payment-link, **el cobro entra y nadie recibe el plan**.
- Cualquier excepción devuelve **200** para no gatillar reintentos agresivos (`backend/main.py:26930-26932`). O sea: un bug transitorio del backend **descarta el evento definitivamente** (queda solo la fila en `billing_events` para replay manual).
- Se loguea el payload completo truncado a 1500 chars y todos los headers `x-*` (`backend/main.py:26830`, `:26842-26847`) — con un comentario que dice *"sacar después de confirmar el shape"* que sigue ahí.
- El evento `subscription.renewal_soon` se recibe y se ignora explícitamente (`backend/main.py:26919-26920`).

---

### 11.5 Créditos y prorrateo (`credits.py`)

#### Modelo

No hay reembolsos ni cobros de ajuste: el tiempo no consumido se convierte en una **ventana de crédito** sobre `users` (`backend/billing/credits.py:1-21`):

| columna de `users` | qué guarda |
|---|---|
| `credit_active_until` | ISO ts hasta el que el tier ≠ free |
| `credit_anchor_plan` | `plus` \| `pro` \| `advisor` \| NULL |
| `credit_anchor_period` | `monthly` \| `annual` \| NULL |
| `credit_anchor_amount_usd` | USD del último anchor |
| `credit_anchor_at` | ISO ts del anchor |

`get_credit_state` (`credits.py:71-126`) computa `days_remaining` y `remaining_usd = days_remaining × daily_rate(anchor)`.

#### `grant_payment_credit` — Rebill cobró (`credits.py:144-296`)

Tres ramas [V]:

| estado previo | qué hace | línea |
|---|---|---|
| crédito vigente **con** anchor | convierte lo que queda al rate nuevo y le SUMA el período comprado: `days = remaining_usd/new_rate + period_days` | `credits.py:215-221` |
| crédito vigente **sin** anchor (= free trial) | **respeta los días de prueba enteros** y el período pagado arranca cuando la prueba termina: `max(fin_prueba, now) + period_days` | `credits.py:222-234` |
| sin crédito o vencido | `now + period_days` | `credits.py:235-237` |

La rama del medio arregla un bug documentado: *"con 10 días restantes pagabas un mes y recibías 30 en vez de 40 — o sea, pagar temprano te daba menos que esperar al día 15"* (`credits.py:227-229`).

#### `convert_plan` — cambio de plan (`credits.py:301-413`)

Fórmula:
```
dias_de_prueba = min(max(0, trial_ends_at − now), days_remaining)      # credits.py:353-364
dias_pagos     = days_remaining − dias_de_prueba                        # credits.py:366
remaining_usd  = dias_pagos × daily_rate(anchor_plan, anchor_period)    # credits.py:367
new_days       = remaining_usd / daily_rate(new_plan, new_period) + dias_de_prueba
new_active_until = now + new_days                                       # credits.py:368-369
```

Los días de prueba **se arrastran como días, no se valúan** — el comentario cuantifica el bug que esto cerró: *"pagar Pro el día 1 y cambiar a Plus daba 101,25 días donde el mismo pago sin prueba da 67,5; 33,75 días fabricados, USD 4,50 de lista, por usuario"* (`credits.py:343-352`).

Escritura atómica: `UPDATE users` (tier + `quota_window_from` + ventana + anchors) e `INSERT credit_ledger kind='plan_change'` en el mismo `with conn` (`credits.py:373-399`).

**🔴 `preview_plan_change` NO aplica el descuento de días de prueba.** [V] `credits.py:448-450` hace `new_days = state["remaining_usd"] / new_rate` sobre el `remaining_usd` **completo** (que en `get_credit_state:113` valúa TODA la ventana, prueba incluida). El confirm (`convert_plan`) sí descuenta. Para quien pagó **durante** su prueba —el único que tiene anchor y días de trial simultáneamente— el modal promete más días de los que va a recibir. El frontend muestra ese preview antes de confirmar (`frontend/src/pages/Planes.jsx:278-281`).

Guardas de `preview_plan_change` (`credits.py:418-461`): `no_active_credit`, `no_anchor` (free trial — el comentario aclara que antes devolvía `eligible=True` con 0 días y el confirm reventaba en 500), `same_plan`.

#### Consumo del crédito

**No se "consume" descontando plata: se consume por paso del tiempo.** [V] No hay ninguna operación que reste `amount_usd`. Cuando `credit_active_until < now`:
- en tiempo real: `quota.get_tier` devuelve `free` (`backend/ai/quota.py:214-215`);
- en el cron: `_downgrade_expired_credit` pone `users.tier = NULL` y asienta `kind='expiration'` (`backend/billing/subscriptions.py:209-225`).

El docstring de `credits.py:17-18` anuncia una operación `expire:` que **no existe en ese archivo** — vive en `subscriptions.py` [V].

#### `credit_ledger`

Esquema en `backend/main.py:2332-2349`. Columnas: `user_id, kind, amount_usd, days_delta, from_plan, from_period, to_plan, to_period, active_until_before, active_until_after, source_subscription_id, payment_id, note, created_at`.

Valores reales de `kind` [V]:

| kind | quién lo escribe | archivo:línea |
|---|---|---|
| `payment` | `grant_payment_credit` | `backend/billing/credits.py:254-268` |
| `plan_change` | `convert_plan` | `backend/billing/credits.py:385-399` |
| `expiration` | los dos downgrades del cron | `backend/billing/subscriptions.py:214-225`, `:499-510` |
| `comp` | `/api/admin/billing/grant-comp` | `backend/main.py:19938-19950` |
| `manual_adjust` | `/api/admin/billing/restore-tier` | `backend/main.py:19782-19791` |
| `trial` | activación del free trial | `backend/billing/trial.py:372-395` |
| `trial_step` | paso Pro→Plus del día 8 | `backend/billing/trial.py:548-555` |

El comentario del esquema (`main.py:2335`) solo lista 4 de los 7.

**El ledger es append-only y sobrevive al borrado de la cuenta** [V]: `_NO_BORRAR_ANONIMIZAR = ("credit_ledger",)` (`backend/main.py:3836`) — se le saca el `user_id` en vez de borrar la fila, *"si se borran, borrar la cuenta se vuelve la forma de resetear el límite"* (`main.py:3835`). El tope mensual de trials se cuenta sobre esta tabla justamente por eso (`backend/billing/trial.py:75-82`).

---

### 11.6 Free trial (`trial.py`)

#### Duración y forma

```
día 1-7   → pro    (TRIAL_PRO_DAYS = 7)
día 8-15  → plus   (TRIAL_PLUS_DAYS = 8)
día 16    → free
```
`backend/billing/trial.py:38-40`, `:9-11`.

Los 7 días de Pro no son arbitrarios: *"la cuota de Pro se mide en ventanas de 7 días, así que el trial consume EXACTAMENTE UNA ventana. El costo queda acotado por diseño (~USD 1,50 en el peor caso absoluto)"* (`trial.py:25-27`).

#### Cómo se decide el vencimiento

**Se graba de una sola vez, a 15 días desde el arranque** (`trial.py:321`): `until = now + TRIAL_TOTAL_DAYS`. Se escribe simultáneamente en `credit_active_until` **y** en `trial_ends_at` (`trial.py:345`, `:351`). El razonamiento explícito: *"si el cron fallara, el usuario se queda en Pro de más en vez de quedarse sin acceso. El error cae siempre a favor del usuario"* (`trial.py:21-23`).

**Los anchors se limpian EXPLÍCITAMENTE a NULL** (`trial.py:352-353`) — porque ponerle precio a los 15 días gratis los convertía en plata real y "cambiar de plan" los transformaba en 41 días de Plus (`trial.py:338-342`).

De ahí sale el discriminador canónico del trial:
```python
def credit_is_trial(credit_active_until, trial_ends_at) -> bool:
    return bool(credit_active_until and trial_ends_at
                and str(credit_active_until) == str(trial_ends_at))
```
`backend/billing/trial.py:91-106`. **Comparación de strings**, no de fechas [V]. Lo usan `status()` (`trial.py:459`), `step_down_due_trials` (`trial.py:515`, en SQL), `repair_stage` (`trial.py:173`), `activos` (`trial.py:945`), `_downgrade_expired_credit` (`subscriptions.py:227-228`), `pro_upsell_eligibility` (`trial.py:831`) y la campaña de regalos (`backend/main.py:19178-19179`).

#### El activar

`start()` (`trial.py:310-417`) → `_start_tx` (`trial.py:331-417`):
1. `UPDATE users SET tier='pro', credit_active_until=?, quota_window_from=date('now','localtime'), trial_started_at=?, trial_used_at=?, trial_ends_at=?, credit_anchor_*=NULL WHERE id=? AND trial_used_at IS NULL AND (credit_active_until IS NULL OR credit_active_until <= ?)` — condicional, así dos requests simultáneos activan una sola vez (`trial.py:343-357`).
2. Marca el email como consumido (`trial.py:360`).
3. `INSERT credit_ledger kind='trial'`. **Con tope mensual configurado, el INSERT es el que hace cumplir el tope**: el conteo y la escritura van en UN solo statement (`INSERT ... SELECT ... WHERE (SELECT COUNT(*)...) < cap`, `trial.py:372-383`) y si no entra levanta `_TopeDelMes` para que el `with conn` deshaga el alta (`trial.py:384-385`). El comentario mide el bug anterior: *"con tope 5 y 20 pedidos simultáneos entraron los 20"* (`trial.py:365-367`).
4. Manda el mail de bienvenida **fuera de toda transacción** — *"httpx tarda hasta 10s y no puede tener tomado el lock de escritura de SQLite"* (`trial.py:408-409`).

#### Qué pasa al vencer

Dos mecanismos, uno sin cron:
- **Real time**: `quota.get_tier` ve `tier='pro'` + `credit_active_until` vencido + sin sub `authorized` → devuelve `free` (`backend/ai/quota.py:208-216`).
- **Cron 03:30 UTC**: `_downgrade_expired_credit` pone `tier=NULL`, asienta `kind='expiration'` y **separa las pruebas vencidas de las bajas reales** vía `credit_is_trial` (`subscriptions.py:227-231`) — *"una prueba que se apaga sola NO es un cliente que se fue, y avisarla igual que una baja real tapaba la señal de churn"* (`subscriptions.py:169-171`). Las pruebas van a un solo mail agregado (`send_trials_ended_admin`), las bajas reales a uno por usuario.

El paso Pro→Plus del día 8 (`step_down_due_trials`, `trial.py:481-560`) corre **antes** de los avisos, para que el mail del día salga con el plan correcto (`subscriptions.py:54-69`). El corte va **por fecha, no por instante** (`trial.py:502`, `:508`) porque con instante la etapa Pro duraba 8 días y se comía dos ventanas de cuota (`trial.py:490-498`). El UPDATE también mueve `quota_window_from` a HOY, con fecha **local** (`trial.py:539-546`), para que los 60 análisis de la semana Pro no se le descuenten del techo de 6 de Plus.

#### `trial_consumed` y `trial_email_log`

```sql
CREATE TABLE IF NOT EXISTS trial_consumed (
    email_key   TEXT PRIMARY KEY,
    consumed_at TEXT NOT NULL
)
CREATE TABLE IF NOT EXISTS trial_email_log (
    user_id INTEGER NOT NULL,
    kind    TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (user_id, kind)
)
```
`backend/main.py:2302-2319`.

`trial_consumed` existe porque **borrar la cuenta borra `users.trial_used_at`**, y eso habilitaba trials infinitos con el mismo mail (`backend/main.py:2298-2301`, `trial.py:220-224`). Guarda `sha256(email_normalizado)` (`trial.py:213-217`) — sirve para comparar, no para reconstruir la casilla.

`trial_email_log` es la idempotencia propia de los avisos del trial, y NO se apoya en `subscriptions` porque un usuario de trial no tiene fila ahí — con el mecanismo genérico el aviso de vencimiento le llegaba **todos los días de los últimos 4** (`backend/main.py:2308-2311`, `trial.py:573-576`). `kind` ∈ `started` \| `pro_ending` \| `ending_soon` \| `ended` (`trial.py:578-581`).

#### Cómo se evita repetirlo — 8 barreras [V]

| barrera | condición | línea |
|---|---|---|
| 1 | `users.trial_used_at` no nulo | `trial.py:274` |
| 2 | `trial_consumed` tiene el hash del email (sobrevive al borrado de cuenta) | `trial.py:274`, `:220-233` |
| 3 | normalización del email: `+alias` en todos los dominios; puntos y `googlemail.com` solo en Gmail | `trial.py:190-210` |
| 4 | `is_admin` → `not_applicable` (activarlo lo DEGRADARÍA 15 días) | `trial.py:279-280` |
| 5 | `tier='advisor'` o `managed_by` no nulo → `not_applicable` | `trial.py:283-285` |
| 6 | sub `authorized` → `already_paying`, **fail-closed** si la consulta falla | `trial.py:286`, `:248-259` |
| 7 | `credit_active_until` vigente → `already_premium` (le acortaría el vencimiento) | `trial.py:290-292` |
| 8 | `email_verified = 0` → `email_not_verified` | `trial.py:295-296` |

Más el `WHERE ... AND trial_used_at IS NULL` del UPDATE (`trial.py:354`), que cierra la carrera entre `eligibility()` y `start()`.

El propio código reconoce el límite: *"No pretende frenar a un decidido con dos casillas de verdad: corta el abuso trivial, que es el que escala"* (`trial.py:200-201`).

#### Interruptores

- `TRIALS_ENABLED` (`trial.py:43-49`): default **encendido**; con `false`/`0`/`off`/`no` deja de ofrecerse, pero los trials ya activos siguen su curso.
- `TRIALS_MONTHLY_CAP` (`trial.py:52-59`): default **0 = sin tope**. `_activations_this_month` cuenta sobre `credit_ledger kind='trial'` normalizando el `T`/espacio de la fecha (`trial.py:62-88`) — el comentario documenta que sin eso *"con tope 3 entraron 8 trials el día 1 y el mes cerró con 11"*. Es **fail-closed** (devuelve `10**9` si no puede contar, `trial.py:88`), pero como el default es 0 la rama que consulta el tope **ni se ejecuta** (`trial.py:299-301`) [I].

#### "Probar Pro sin dejar el Plus que pagás" — mecanismo aparte

`PRO_UPSELL_DAYS = 7` (`trial.py:789`). Es para el suscriptor **de Plus** (`trial.py:835-836`). No escribe `users.tier`, ni `credit_active_until`, ni anchors: solo `pro_trial_until` / `pro_trial_used_at` (`trial.py:860-863`), y `quota.get_tier` devuelve `pro` mientras la fecha esté viva (`backend/ai/quota.py:199-204`). Cuando pasa, vuelve solo a Plus sin cron. Endpoint: `POST /api/billing/trial/pro-upsell` (`backend/main.py:26387`).

#### Endpoints del trial

| endpoint | auth | archivo:línea |
|---|---|---|
| `POST /api/billing/trial/start` | `get_current_user` (**no** `get_effective_user`, a propósito) | `backend/main.py:26365` |
| `POST /api/billing/trial/pro-upsell` | `get_current_user` | `backend/main.py:26387` |
| `GET /api/billing/trial` | `get_current_user` | `backend/main.py:26427` |
| `GET /api/admin/billing/trial-funnel?days=` | `get_admin_user` | `backend/main.py:26408` |
| (embebido) `GET /api/plan/features` → `out["trial"]`, `out["pro_upsell"]` | | `backend/main.py:26476-26484` |

El uso de `get_current_user` está justificado en el docstring: *"Un asesor mirando la cuenta de un cliente no puede activarle un trial 'sin querer' desde el contexto"* (`backend/main.py:26369-26371`).

#### Medición

`funnel(conn, days)` (`trial.py:1054-1200`): activados → importaron → usaron IA → convirtieron, más `cuando_pagan` (durante Pro / durante Plus / después), `activos` y `pro_upsell`. La conversión se lee de `credit_ledger kind='payment'` y **no** de `subscriptions`, porque ahí hay fila desde que se genera el link: *"3 personas que abrieron el link y nunca pagaron + 1 que pagó de verdad daban 'convirtieron 4, conversión 100%' cuando la respuesta es 1 y 25%"* (`trial.py:1108-1120`).

---

### 11.7 Emails transaccionales (`emails.py`)

**Proveedor único: Resend** (`https://api.resend.com/emails`, `backend/billing/emails.py:148-156`), API key en `RESEND_API_KEY`. Sin key configurada, `_send` **loguea y devuelve False** sin fallar (`emails.py:127-135`).

**Guarda dura anti-envío** (`emails.py:113-118`): nunca envía si `PYTEST_CURRENT_TEST`/`pytest` en `sys.modules`, ni a dominios `.test/.example/.invalid/.localhost/.local`.

Tres remitentes (`emails.py:44-65`): `_from_address()` (default), `_from_noreply()` (transaccionales que no esperan respuesta), `_from_support()` (donde el usuario puede responder). Footer con WhatsApp `+54 9 2914 37-3695` en todos salvo los que pasan `append_footer=False` (`emails.py:120-126`, `:186-191`).

El docstring del módulo dice **"6 emails"** (`emails.py:6`). Hay **28** [V].

#### Inventario completo

| # | función | asunto | cuándo se dispara | disparador (archivo:línea) | definición | from |
|---:|---|---|---|---|---|---|
| 1 | `send_welcome_pro` | `¡Bienvenido a Rendi {Plus\|Pro\|Asesor}!` | preapproval MP pasa a `authorized`, una sola vez (`welcome_email_sent_at`) | `backend/main.py:27665` ← `_maybe_send_welcome_email` ← `_process_preapproval_event` (`main.py:27643`) | `emails.py:325` | noreply |
| 2 | `send_receipt` | `Recibo · Rendi {plan}` | pago MP aprobado **posterior** al welcome | `backend/main.py:27728` ← `_process_payment_event` | `emails.py:367` | noreply |
| 3 | `send_payment_failed` | `⚠️ No pudimos cobrar tu suscripción Rendi {plan}` | pago MP `rejected`/`cancelled`/`refunded` | `backend/main.py:27741` | `emails.py:404` | support |
| 4 | `send_cancellation` | `Cancelación confirmada · Rendi {plan}` | `POST /api/billing/cancel`, idempotente por `cancellation_email_sent_at` | `backend/main.py:27772` ← `_maybe_send_cancellation_email` ← `main.py:27407` | `emails.py:445` | noreply |
| 5 | `send_expiration_reminder` | `⏰ Tu Rendi {plan} vence en N días` | cron: crédito vence en ≤3 días (`subscriptions.py:311`) **o** sub `cancelled` con `current_period_end` en ≤3 días (`subscriptions.py:424`) | `backend/billing/subscriptions.py:311`, `:424` | `emails.py:480` | noreply |
| 6 | `send_verification_code` | `Tu código de Rendi: {code}` | signup / reenvío de OTP | `backend/main.py:3066`, `:3084` | `emails.py:513` | noreply |
| 7 | `send_welcome_free` | `Completaste tu registro en Rendi` | transición no-verificado → verificado | `backend/main.py:3301` | `emails.py:547` | noreply |
| 8 | `send_alert_email` | el `heading` de la alerta | motor de alertas de precio / variación; alertas del asesor | `backend/alerts_engine.py:292`, `backend/advisor_alerts.py:150` | `emails.py:587` | noreply |
| 9 | `send_reengagement` | `Tu historial en Rendi, cuando quieras` | campaña admin `POST /api/admin/email/re-engagement` (dry-run por default) | `backend/main.py:19092` (ruta `main.py:19011`) | `emails.py:615` | support |
| 10 | `send_custom` | libre (admin) | broadcast admin `POST /api/admin/email/broadcast` | `backend/main.py:19441` (test a sí mismo), `:19524` (masivo); ruta `main.py:19413` | `emails.py:684` | support |
| 11 | `send_gift_plan_history` | `Te regalamos un mes de Rendi {plan}` | campaña admin `POST /api/admin/email/gift-plan` | `backend/main.py:19261` (ruta `main.py:19123`) | `emails.py:707` | support |
| 12 | `send_trial_invite` | `¿Qué te diría Rendi si viera toda tu cartera?` (variante `cartera`) / `Ahora podés probar Rendi Pro gratis` (variante `directo`) | campaña admin `POST /api/admin/email/trial-invite` | `backend/main.py:19376` (ruta `main.py:19296`) | `emails.py:782` | support |
| 13 | `send_new_signup_admin` | `Rendi · nuevo usuario #N: {email}` | signup verificado, mientras `count ≤ ADMIN_SIGNUP_ALERT_LIMIT` | `backend/main.py:3315` | `emails.py:853` | noreply |
| 14 | `send_plan_change_admin` | `Rendi · cambio de plan: {old} → {new} ({email})` | todo cambio de tier: pago, cambio de plan, vencimiento, grant/restore admin | `backend/main.py:26953` (`_notify_plan_change`), `backend/billing/subscriptions.py:112` | `emails.py:918` | noreply |
| 15 | `send_trials_ended_admin` | `Rendi · N pruebas gratis terminaron` | UNO por corrida del cron, agregando las pruebas que vencieron | `backend/billing/subscriptions.py:155` | `emails.py:999` | noreply |
| 16 | `send_gifted_plan` | `Te activamos Rendi {plan} de regalo` | `POST /api/admin/billing/grant-comp` exitoso | `backend/main.py:19959` | `emails.py:1038` | (default) |
| 17 | `send_password_reset` | `Restablecé tu contraseña · Rendi` | `POST` de "olvidé mi contraseña" | `backend/main.py:3395` | `emails.py:1085` | support |
| 18 | `send_advisor_claim` | `{asesor} te invitó a ver tu cartera en Rendi` | el asesor invita a reclamar una ficha shadow | `backend/main.py:34766` | `emails.py:1130` | (default) |
| 19 | `send_advisor_access_request` | `{asesor} te pide acceso a tu cartera en Rendi` | el asesor pide acceso a una cuenta que YA existe | `backend/main.py:34873` | `emails.py:1193` | (default) |
| 20 | `send_new_login_alert` | `Nuevo inicio de sesión · Rendi` | login desde un `ua_hash` nunca visto | `backend/main.py:3021` | `emails.py:1260` | support |
| 21 | `send_user_recommendation` | `[Recomendación] {asunto}` | el usuario manda feedback | `backend/main.py:29236` | `emails.py:1314` | noreply + `reply_to` del usuario |
| 22 | `send_recommendation_acknowledgment` | `Recibimos tu recomendación — Rendi` | acuse al usuario tras el anterior | `backend/main.py:29261` | `emails.py:1394` | (default) |
| 23 | `send_advisor_brief` | `{title} · {headline}` (≤120 chars) | brief del asesor (apertura ~11:00 / cierre ~17:15 ART) | `backend/advisor_brief.py:396` | `emails.py:1447` | noreply |
| 24 | **`send_trial_started`** | `Ya tenés Rendi Pro por 7 días` | día 1 — al activar el trial, **en el momento**, no por cron | `backend/billing/trial.py:411` | `emails.py:1522` | noreply |
| 25 | **`send_trial_pro_ending`** | `Mañana termina tu semana de Pro` | día 7 — cron | `backend/billing/trial.py:705` | `emails.py:1560` | noreply |
| 26 | **`send_trial_ending_soon`** | `Te quedan N días de prueba en Rendi` | día 14 — cron | `backend/billing/trial.py:733` | `emails.py:1590` | noreply |
| 27 | **`send_trial_ended`** | `Terminó tu prueba de Rendi` | día 16 — cron, con estadísticas propias del usuario | `backend/billing/trial.py:766` | `emails.py:1618` | noreply |
| 28 | `send_iol_lab_report_admin` | `Rendi · IOL Lab run #N ({status}) — {email}` | fin de una corrida del IOL Lab | `backend/main.py:31414` | `emails.py:1660` | noreply |

**El día 8 ("ya pasaste a Plus") NO tiene mail** — a propósito: *"se avisó el día anterior y dos mails seguidos por lo mismo hacen que dejen de abrirlos justo antes del aviso que importa"* (`trial.py:569-571`).

#### 🔴 Hallazgos del inventario

1. **Los emails de pago #1, #2 y #3 cuelgan EXCLUSIVAMENTE del path Mercado Pago.** [V] `send_welcome_pro` solo se llama desde `_maybe_send_welcome_email` (`main.py:27650`), que solo se llama desde `_process_preapproval_event` (`main.py:27643`). `send_receipt` y `send_payment_failed` solo desde `_process_payment_event` (`main.py:27728`, `:27741`), que solo se invoca desde el webhook MP (`main.py:27573`). **Ninguno de los tres tiene caller en el path Rebill** — verificado por grep completo. Consecuencia: quien paga hoy por Rebill **no recibe bienvenida, no recibe recibo, y no se entera si el cobro recurrente falla.** El único email de billing que sí funciona en Rebill es la cancelación (#4, vía `main.py:27407`) y los del cron (#5, #14, #15).

2. **`_tier_label` mapea `advisor` → `"Free"`.** [V] `emails.py:904`: `{"plus": "Plus", "pro": "Pro"}.get(t, "Free")`. Cuando el admin regala el Plan Asesor con `grant-comp`, `send_plan_change_admin` computa `old_label="Free"`, `new_label="Free"` → `old == new` → `return False` (`emails.py:940-941`) y **el aviso al admin nunca sale**. `_plan_label` (`emails.py:235-246`) sí maneja `advisor` → `"Asesor"` — el propio comentario de `_tier_label` (`emails.py:901-902`) reconoce que son dos funciones con criterios distintos, pero no cubre el caso.

3. **El asunto de `send_trial_started` hardcodea "7 días"** aunque `pro_days` es parámetro (`emails.py:1556` vs `:1522`). Si se cambia `TRIAL_PRO_DAYS`, el cuerpo se adapta y el asunto miente.

4. **`send_receipt` recibe `amount_ars` desde `subscriptions.amount_ars`** (`main.py:27731`), columna que en el alta Rebill se escribe **literalmente 0** (`main.py:26610`). En el path MP el welcome tiene el mismo problema (`main.py:27669`).

---

### 11.8 Herramientas de admin

| acción | endpoint | auth | archivo:línea |
|---|---|---|---|
| **Regalar plan / cambiar tier** | `POST /api/admin/billing/grant-comp?email=&plan=&days=&force=&note=` | `get_admin_user` | `backend/main.py:19844` |
| **Diagnóstico read-only** | `GET /api/admin/billing/inspect?email=` | `get_admin_user` | `backend/main.py:19551` |
| **Realinear tier con el crédito** | `POST /api/admin/billing/restore-tier?email=` | `get_admin_user` | `backend/main.py:19697` |
| **Embudo del trial** | `GET /api/admin/billing/trial-funnel?days=` | `get_admin_user` | `backend/main.py:26408` |
| **Conversión del paywall** | `GET /api/admin/plan/conversion` | `get_admin_user` | `backend/main.py:18775` |
| Campaña re-engagement | `POST /api/admin/email/re-engagement` | `get_admin_user` | `backend/main.py:19011` |
| Campaña "te regalamos un mes" | `POST /api/admin/email/gift-plan` | `get_admin_user` | `backend/main.py:19123` |
| Campaña invitación al trial | `POST /api/admin/email/trial-invite` | `get_admin_user` | `backend/main.py:19296` |
| Broadcast libre | `POST /api/admin/email/broadcast` | `get_admin_user` | `backend/main.py:19413` |

#### `grant-comp` — regalar un plan

Es **la única vía de alta del Plan Asesor** [V]. Acepta `plan ∈ {plus, pro, advisor}` (`main.py:19879-19880`) y `days ∈ [1, 366]` (`main.py:19881`). No crea suscripción en Rebill (`main.py:19856`).

Escribe (`main.py:19925-19950`): `users.tier`, `quota_window_from`, `credit_active_until`, `credit_anchor_plan = plan`, `credit_anchor_period = 'monthly'` (fijo), `credit_anchor_amount_usd = 0`, `credit_anchor_at`; más una fila `kind='comp'` en `credit_ledger`.

Salvaguardas:
- Si el usuario **ya tiene crédito activo** y no pasás `force=true`, devuelve `ok:false` con `reason="credit_already_active"` **y un preview `would_be_active_until`** que el panel muestra en el confirm (`main.py:19899-19919`).
- La fecha base la decide `_grant_base` (`main.py:19810-19841`): **mismo plan → extiende desde el vencimiento vigente** (nunca acorta); **otro plan o ninguno → arranca HOY** (así "30 días de Asesor" son 30, no 60). El propio docstring advierte que la segunda regla puede **acortarle** el acceso a alguien con un plan pago más largo, y que por eso se devuelve `would_be_active_until` (`main.py:19826-19829`).
- Dispara `_notify_plan_change(source="admin_grant")` (`main.py:19955`) y `send_gifted_plan` al usuario (`main.py:19959-19965`).

**🔴 Con `plan='advisor'` el resultado es un estado que `credits.py` no sabe manejar.** [V] `credit_anchor_plan='advisor'` no existe en `PLAN_PRICES_USD` (`credits.py:38-43`), así que `daily_rate('advisor','monthly')` levanta `ValueError` (`credits.py:57`). Consecuencias encadenadas:
- `get_credit_state` lo captura y deja `remaining_usd = 0.0` (`credits.py:113-115`).
- `preview_plan_change` **pasa todos los guards** (hay crédito activo y hay anchor) y devuelve `eligible: True` con `new_days: 0.0` (`credits.py:442-461`).
- `POST /api/billing/change-plan` sobre un asesor pasa las 3 validaciones (`main.py:26674-26693`) y revienta dentro de `convert_plan` en `credits.py:367` → `HTTPException(500, "Error al convertir crédito: ValueError")` (`main.py:26718-26720`).
- Y como se vio en 11.7, el aviso al admin del grant nunca sale.

El frontend tapa el caso mostrando otra pantalla al asesor (`frontend/src/pages/Planes.jsx:318`), pero la API no lo bloquea.

#### `restore-tier` — realinear `users.tier`

Repara la columna `tier` cuando el crédito sigue vivo pero el tier se perdió. Solo escribe si (a) hay crédito activo y (b) hay un plan objetivo (`main.py:19738-19762`). El plan objetivo sale del anchor pago si existe; si no —**caso del free trial, que nace sin anchor a propósito**— sale del **calendario** vía `billing_trial.repair_stage` (`main.py:19750-19754`, `trial.py:154-179`), que no consulta `users.tier` justamente porque esa es la columna rota. Idempotente (`main.py:19763-19771`). Asienta `kind='manual_adjust'` (`main.py:19782-19791`).

#### `inspect` — el diagnóstico

Devuelve `user` (columnas de tier y crédito, sin `password_hash`), `computed` (tier efectivo de `quota.get_tier` + `credit_state`), `diagnosis` (**replica la lógica de los dos downgrades del cron** para mostrar si el usuario está en zona de baja, `main.py:19652-19667`), todas las `subscriptions`, el `credit_ledger` completo y hasta 50 `billing_events` con `signature_valid` y payload truncado a 1500 chars (`main.py:19620-19650`).

**Otorgar crédito "suelto" (días sin plan): no existe.** El único camino es `grant-comp`, que siempre setea también el tier.

---

### 11.9 Plan Asesor

**No tiene flujo de cobro en el código.** [V]

| pregunta | respuesta |
|---|---|
| ¿por cliente o flat? | **no encontrado** — no hay ninguna constante, tabla ni cálculo de precio del Plan Asesor en el repo |
| ¿precio? | **no encontrado** |
| ¿checkout self-serve? | **no**. `SubscribeIn.plan` tiene `pattern="^(plus\|pro)$"` (`backend/main.py:26500`); `advisor` no es un valor aceptado |
| ¿plan ID en Rebill? | **no**. `validate_config` solo espera 4 combos: plus/pro × monthly/annual (`backend/billing/rebill.py:275-280`) |
| ¿cómo se da de alta? | **manual**: `POST /api/admin/billing/grant-comp?plan=advisor` (`backend/main.py:19879-19880`) |
| ¿cómo se renueva? | manualmente, repitiendo el grant. `_grant_base` extiende desde el vencimiento si el plan es el mismo (`backend/main.py:19832-19840`) |
| ¿cómo se da de baja? | vence solo: el cron `_downgrade_expired_credit` incluye `'advisor'` en su `WHERE u.tier IN ('pro','plus','advisor')` (`backend/billing/subscriptions.py:178`), igual que `quota.get_tier` (`backend/ai/quota.py:208`) |
| ¿límite de clientes? | `alerts_max`/`brokers_max` = ∞ (`backend/ai/plan.py:102-117`); **no encontrado** un `clients_max` |

Lo que dice la UI al asesor (`frontend/src/pages/Planes.jsx:318-341`):

> *"Para cambios en tu Plan Asesor (límite de clientes, facturación o baja), escribinos directo y lo resolvemos en el día"* → botón a WhatsApp.

O sea: **la facturación del Plan Asesor es 100 % fuera de la app** [I, inferido de la ausencia total de código + el CTA de WhatsApp + que la única alta es `grant-comp`].

Lo que sí está codificado del plan:
- El asesor tiene features nivel Pro para su propia cuenta (`backend/ai/plan.py:98-117`), con el comentario *"paga 4-8× un Pro"* (`plan.py:99`) — el único número de precio del Asesor en todo el repo, y es un comentario.
- El "lente Pro" sobre las cuentas de clientes no sale de la tabla de tiers: lo fuerza `/api/plan/features` con `tier_override='pro'` cuando hay contexto de cliente (`backend/main.py:26469-26471`).
- Una cuenta shadow sin reclamar (`managed_by` no nulo + `approved=0`) resuelve `pro` directamente (`backend/ai/quota.py:186-188`).
- El gate `_require_advisor` exige tier `advisor` **de verdad**: `is_admin` no alcanza (`backend/main.py:2823-2832`).
- El trial normal excluye asesores y cuentas administradas (`backend/billing/trial.py:283-285`).
- El cron nunca borra shadows: `_delete_unverified_accounts` filtra `managed_by IS NULL` (`backend/billing/subscriptions.py:356`).
- Borrar la cuenta de un asesor borra también sus clientes shadow (`backend/main.py:3829-3832`).

---

### 11.10 El cron del ciclo de vida

`run_lifecycle_job(conn)` (`backend/billing/subscriptions.py:31-95`), invocado por `_run_subscription_lifecycle_job` (`backend/main.py:32075-32091`), agendado con APScheduler a las **03:30 UTC** diarias (`backend/main.py:32551-32556`).

Orden de los pasos y qué hace cada uno:

| # | paso | función | línea |
|---|---|---|---|
| 1 | baja a Free por crédito vencido (acá caen las pruebas) | `_downgrade_expired_credit` | `subscriptions.py:161` |
| 2 | trials que cumplieron su semana Pro → Plus | `trial.step_down_due_trials` | `trial.py:481` |
| 3 | avisos del trial (días 7, 14, 16) | `trial.send_due_trial_emails` | `trial.py:668` |
| 4 | aviso "tu crédito se acaba en 3 días" | `_send_credit_expiring_reminders` | `subscriptions.py:242` |
| 5 | baja a Free por cancelación vencida (+ `status='expired'`) | `_downgrade_expired_cancellations` | `subscriptions.py:444` |
| 6 | `pending` > 7 días → `cancelled` | `_cancel_stale_pending` | `subscriptions.py:523` |
| 7 | aviso de vencimiento para subs `cancelled` | `_send_expiration_reminders` | `subscriptions.py:386` |
| 8 | borra usuarios `email_verified=0` de > 7 días | `_delete_unverified_accounts` | `subscriptions.py:337` |

Cada paso va en su propio `try/except` que incrementa `result["errors"]` sin abortar el resto (`subscriptions.py:49-94`).

#### 🔴 `synced_from_mp` es un contador que nunca sube

`result` declara `"synced_from_mp": 0` (`subscriptions.py:38`), el docstring del módulo lista el sync como paso 3 de 3 (`subscriptions.py:15-18`) y el del cron en `main.py` dice *"sync con MP para detectar webhooks perdidos"* (`backend/main.py:32079`). Pero **`_sync_authorized_with_mp` (`subscriptions.py:556`) no se llama desde `run_lifecycle_job`** — sus únicos callers son tests (`backend/tests/test_billing_lifecycle.py:213,225,237`) [V]. El log diario reporta `synced_from_mp: 0` para siempre y no es un dato: es una constante.

(Con Rebill como procesador activo esto es coherente —no existe un `_sync_authorized_with_rebill`—, pero entonces la red de seguridad contra webhooks perdidos **no existe en ningún procesador**.)

#### 🔴 El aviso "tu crédito se acaba" es de una sola vez por usuario, para siempre

`_send_credit_expiring_reminders` chequea idempotencia así:

```sql
SELECT id FROM subscriptions
 WHERE user_id = ? AND expiration_reminder_sent_at IS NOT NULL
 ORDER BY updated_at DESC LIMIT 1
```
`backend/billing/subscriptions.py:284-291` — y si hay **cualquier** fila con la marca puesta, hace `continue` (`:290-291`).

Como la marca no se limpia nunca, un usuario que recibió el aviso una vez (por ejemplo al cancelar en 2026) **no vuelve a recibirlo jamás**, aunque después pague, cancele y su crédito venza de nuevo. El propio docstring reconoce la deuda: *"Si en el futuro queremos un canal separado por crédito vs cancel, se puede agregar una col `credit_reminder_sent_at` en users"* (`subscriptions.py:249-250`).

Además, quien **no tiene ninguna fila en `subscriptions`** no recibe el aviso nunca (`subscriptions.py:292-301`) — *"Preferimos no mandarlo antes que mandarlo cuatro veces"*. Ese es exactamente el perfil de quien recibió un `grant-comp`.

#### Detalles finos verificados

- **Guardas contra el downgrade equivocado**: ambos downgrades exigen `NOT EXISTS (sub authorized)` (`subscriptions.py:181-184`, `:473-476`), y el de cancelaciones exige además que el crédito ya haya vencido (`:472`). El comentario explica el bug que cerró: un usuario que se suscribe → cancela → vuelve a suscribirse tenía una cancelada vieja actuando de mina, y el primer cron le borraba el tier recién pagado (`subscriptions.py:457-461`).
- **Fechas con `T` vs espacio**: `_cancel_stale_pending` (`subscriptions.py:528-538`) y `_delete_unverified_accounts` (`subscriptions.py:346-355`) normalizan las dos puntas con `substr(replace(created_at,'T',' '),1,19)` porque `' ' < 'T'` invertía el orden y barría un día antes de la política.
- **Degradación sin `trial_ends_at`**: `_downgrade_expired_credit` reintenta la consulta sin esa columna si el esquema no la tiene, en vez de tirar el job entero — *"si un esquema no tuviera la columna, el job entero dejaría de correr y NADIE bajaría a Free"* (`subscriptions.py:185-201`).
- **Corte de cuota fuera de la transacción**: `_marcar_corte_de_cuota` (`subscriptions.py:122-142`) va aparte del UPDATE que baja el tier a propósito, para que una columna faltante no voltee el cumplimiento del vencimiento.
- **`_sync_authorized_with_mp` mapea todo lo desconocido a `authorized`**: `status_map.get(mp_status, "authorized")` (`subscriptions.py:587`). Un status nuevo de MP se interpretaría como plan vigente. (Inocuo hoy porque la función no corre.)
- **`_delete_unverified_accounts` borra usuarios de verdad** (`subscriptions.py:377-379`), con una defensa que salta si el usuario tiene `positions`/`operations`/`monthly_entries` (`:366-373`) y excluyendo shadows (`:356`).
- El cron corre **in-process con APScheduler** (`backend/main.py:32095`, `:32575`). La memoria del proyecto registra que APScheduler in-process no es confiable en Railway (múltiples réplicas / reinicios); no encontré un endpoint `/api/billing/run-cron` de respaldo — los `run-cron` externos que existen son solo para snapshots, IOL Lab y el brief del asesor (`backend/main.py:33647`, `:31559`, `:33936`) [V].

---

### 11.11 Endpoints de billing (mapa completo)

| método | ruta | auth | qué hace | línea |
|---|---|---|---|---|
| POST | `/api/billing/subscribe` | `get_effective_user` (exento de ctx) | crea payment link Rebill; rate limit 5/600s | `backend/main.py:26504` |
| POST | `/api/billing/change-plan` | `get_effective_user` | convierte crédito y cancela la sub vieja; rate limit 3/600s | `backend/main.py:26630` |
| GET | `/api/billing/preview-change-plan?plan=&period=` | `get_effective_user` | simulación sin ejecutar | `backend/main.py:26773` |
| POST | `/api/billing/rebill-webhook` | firma/token | webhook Rebill | `backend/main.py:26809` |
| POST | `/api/billing/cancel` | `get_effective_user` | cancela en Rebill + persiste; rate limit 5/600s | `backend/main.py:27306` |
| POST | `/api/billing/sync` | `get_effective_user` | **legacy MP**, sigue vivo | `backend/main.py:27420` |
| GET | `/api/billing/status` | `get_effective_user` | última fila de `subscriptions` del usuario | `backend/main.py:27476` |
| POST | `/api/billing/webhook` | firma MP (**fail-open**) | webhook MP | `backend/main.py:27501` |
| POST | `/api/billing/trial/start` | `get_current_user` | activa el trial | `backend/main.py:26365` |
| POST | `/api/billing/trial/pro-upsell` | `get_current_user` | 7 días de Pro sobre Plus | `backend/main.py:26387` |
| GET | `/api/billing/trial` | `get_current_user` | estado del trial | `backend/main.py:26427` |
| GET | `/api/plan/features` | `get_effective_user` | flags + límites + `trial` + `pro_upsell` | `backend/main.py:26439` |
| POST | `/api/plan/track` | `get_effective_user` | telemetría del paywall (204) | `backend/main.py:26334` |

**El prefijo `/api/billing` está en `CLIENT_CTX_EXEMPT_PREFIXES`** (`backend/main.py:2751`), así que el header `X-Rendi-Client-Id` se **ignora** en todos ellos y `get_effective_user` devuelve siempre el uid autenticado [V]. Un asesor no puede suscribir ni cancelar en nombre de un cliente. El comentario marca la superficie como fail-open para endpoints nuevos: *"todo endpoint futuro FUERA de estos prefijos hereda el contexto de cliente"* (`backend/main.py:2763-2764`).

#### Defensa anti-open-redirect en el checkout [V]

Doble validación de que la URL de pago es de Rebill:
- **Backend** (`backend/main.py:26594-26603`): allowlist explícita `app.rebill.com`, `checkout.rebill.com`, `pay.rebill.com`, `app.rebill.dev`, `checkout.rebill.dev`; si no matchea → 502 `payment_url_invalid`.
- **Frontend** (`frontend/src/pages/Planes.jsx:233-245`): `isSafePaymentUrl` antes del `window.location.href`.

#### Cancelación: nunca miente al usuario [V]

`/api/billing/cancel` (`main.py:27306-27417`) es idempotente a propósito: si Rebill rechaza el cancel, **relee el estado real** y si ya está cancelada sigue (`main.py:27356-27369`) — *"la persona quedaba trabada para siempre viendo 'No pudimos cancelar' sobre una suscripción que YA estaba cancelada"*. Y si la escritura local falla, devuelve igual `status: "cancelled"` con `local_sync_pending: true` y loguea `CANCELACIÓN HUÉRFANA` (`main.py:27390-27414`).

---

### 11.12 Esquema de datos del subsistema

| tabla | definición | notas |
|---|---|---|
| `subscriptions` | `backend/main.py:2021-2048` | `mp_subscription_id` **reusado** para guardar el ID de Rebill (payment-link primero, subscription después) — `main.py:26583-26585`, `:27345-27346`. `amount_ars` se inserta en 0. Índices: `user_id`, `mp_subscription_id`, `status` |
| `billing_events` | `backend/main.py:2053-2067` | guarda **todos** los webhooks, válidos e inválidos. Sin unique. Índices: `user_id`, `mp_data_id` (no sobre `raw_payload`, que es por lo que se hace el UPDATE de `processed` en Rebill) |
| `credit_ledger` | `backend/main.py:2332-2349` + índice único `main.py:2364-2368` | append-only; se anonimiza, no se borra (`main.py:3836`) |
| `trial_consumed` | `backend/main.py:2302-2307` | PK = `sha256(email normalizado)` |
| `trial_email_log` | `backend/main.py:2312-2319` | PK `(user_id, kind)` |
| `plan_events` | `backend/main.py:2073-2088` | telemetría del paywall |
| columnas en `users` | | `tier`, `credit_active_until`, `credit_anchor_plan/period/amount_usd/at`, `trial_started_at`, `trial_used_at`, `trial_ends_at`, `pro_trial_until`, `pro_trial_used_at`, `quota_window_from`, `gift_plan_email_sent_at`, `managed_by` |

Hay un **backfill al arrancar** (`backend/main.py:2371-2400+`) que rellena `credit_active_until` para usuarios `plus`/`pro` con sub `authorized` y crédito NULL —los que pagaron antes de que `_rebill_activate` llamara a `grant_payment_credit`—, infiriendo la ventana de `current_period_end` o de `created_at + period_days`. Duplica el diccionario de precios en línea (`main.py:2392-2394`), o sea **una cuarta copia** de `PLAN_PRICES_USD`.

---

### 11.13 Reembolsos

La política publicada promete el derecho de arrepentimiento de 10 días corridos con reembolso total (Ley 24.240 art. 34) — `frontend/src/pages/Reembolso.jsx:8`, `:53`.

**No existe ningún código de reembolso en el backend.** [V] Grep de `refund`/`reembols`/`arrepentimiento` en `backend/**.py` solo devuelve el refund de **cuota de chat de la IA** (`backend/main.py:28116-28138`) y el string `"refunded"` como status de pago MP entrante (`main.py:27739`). No hay llamada a ninguna API de reembolso de Rebill ni de MP.

[I, inferido de la ausencia de código + el CTA de WhatsApp de la página] el reembolso se procesa a mano desde el panel de Rebill.

Lo que sí está codificado: al cancelar **no se devuelve plata y el acceso sigue hasta fin de período** (`backend/billing/rebill.py:321-323`, `backend/main.py:27310-27314`), y cambiar de plan **no cobra ni devuelve**, convierte crédito (`frontend/src/pages/Reembolso.jsx:57`, `backend/billing/credits.py:3-8`).

---

### 11.14 Resumen de hallazgos, por severidad

#### 🔴 Alto

1. **El webhook de Mercado Pago es fail-open sin secret.** Si `MP_WEBHOOK_SECRET` no está seteada, `verify_webhook_signature` devuelve False en producción pero el handler solo rechaza cuando el secret **sí** está configurado → procesa igual. `backend/main.py:27554-27560` vs `backend/billing/mercadopago.py:214-219`. Mitigado de hecho porque el evento se resuelve pegándole a MP con el token propio, pero el código contradice su propio diseño fail-closed.

2. **Quien paga por Rebill no recibe bienvenida, ni recibo, ni aviso de cobro fallido.** Los tres emails cuelgan exclusivamente del path MP (muerto): `send_welcome_pro` ← `main.py:27643`, `send_receipt` ← `main.py:27728`, `send_payment_failed` ← `main.py:27741`. Ningún caller en el path Rebill.

3. **La idempotencia del crédito depende de que el webhook traiga `payment_id`.** Sin él, ni el check app-side (`credits.py:184-193`) ni el índice único (`main.py:2364-2368`) aplican, y `grant_payment_credit` extiende la ventana otra vez. `_rebill_activate` acepta explícitamente ese caso (`main.py:26996-26998`) apoyándose en que "sub.created solo viene una vez" — pero `subscription.updated` con `status=active` llama al mismo handler (`main.py:27151-27153`).

4. **Tres (cuatro) catálogos de precios que no coinciden.** `pricing.py` (Pro mensual 12.100 ARS / USD 6,99), `Planes.jsx` (13.990 ARS), `credits.py` (USD 9,00), y una copia inline en el backfill (`main.py:2392-2394`). El precio que se cobra de verdad no está en ninguno: vive en el dashboard de Rebill (`rebill.py:150`). `credits.py` es el que gobierna el prorrateo, así que un cambio de plan se calcula con números que no son los que el usuario pagó.

5. **`grant-comp` con `plan='advisor'` deja un estado que `credits.py` no puede procesar.** `'advisor'` no está en `PLAN_PRICES_USD`; `preview_plan_change` devuelve `eligible: True` con 0 días y el confirm revienta en 500 (`credits.py:367` → `main.py:26718-26720`). Además el aviso al admin del grant nunca sale, porque `_tier_label('advisor')` devuelve `"Free"` (`emails.py:904`) y `old == new` corta el envío (`emails.py:940-941`).

#### 🟡 Medio

6. **`preview_plan_change` y `convert_plan` no calculan lo mismo.** El preview no descuenta los días de prueba; el confirm sí (`credits.py:448-450` vs `credits.py:353-368`). El usuario que pagó durante su trial ve prometido más de lo que recibe.

7. **El aviso "tu crédito se acaba" se manda una sola vez en la vida del usuario.** La idempotencia mira si existe *cualquier* fila de `subscriptions` con `expiration_reminder_sent_at` no nulo, y esa marca nunca se limpia (`subscriptions.py:284-291`). Quien nunca tuvo suscripción (regalados) no lo recibe nunca (`subscriptions.py:292-301`).

8. **`synced_from_mp` es una métrica muerta.** `_sync_authorized_with_mp` no tiene callers de producción (`subscriptions.py:556`), pero el contador (`:38`), el docstring del módulo (`:15-18`) y el del cron (`main.py:32079`) siguen anunciándolo. No hay red de seguridad equivalente para Rebill.

9. **`billing_events` no tiene idempotencia ni índice adecuado.** Cada reintento inserta fila; el marcado de procesado se hace por igualdad del JSON completo (`main.py:26926-26928`) sobre una columna sin índice, y en el path MP por un `mp_event_id` que puede venir vacío (`main.py:27577-27578`).

10. **El webhook devuelve 200 ante cualquier excepción** (`main.py:26930-26932`, `:27581-27583`). Un fallo transitorio descarta el evento sin retry del proveedor; solo queda el replay manual desde `billing_events`.

11. **`amount_ars` se inserta siempre en 0** (`main.py:26610`) y alimenta el recibo (`main.py:27731`) y el welcome (`main.py:27669`).

12. **`pricing.py` es código muerto** cuyo único consumidor (`mercadopago.create_preapproval`) no tiene callers, y su docstring se contradice a sí mismo sobre el plan anual de Plus (`pricing.py:26`, `:78` vs `:81-93`).

#### 🟢 Bajo / cosmético

13. `POST /api/billing/sync` (MP) sigue montado y accesible para cualquier usuario logueado, aunque el frontend ya no lo use (`main.py:27420`, `BillingReturn.jsx:18-19`).
14. El handler de Rebill loguea el payload completo (1500 chars) y todos los headers `x-*` con un comentario "sacar después de confirmar el shape" que quedó (`main.py:26829-26830`).
15. Asunto de `send_trial_started` con "7 días" hardcodeado mientras el cuerpo usa el parámetro (`emails.py:1556`).
16. El docstring de `emails.py` dice "6 emails"; hay 28 (`emails.py:6`).
17. `subscriptions.status = 'failed'` está documentado en el esquema (`main.py:2020`) y nadie lo escribe.
18. `credit_ledger.kind` documenta 4 valores (`main.py:2335`); en producción hay 7.
19. `_sync_authorized_with_mp` mapea cualquier status desconocido de MP a `authorized` (`subscriptions.py:587`).
20. `TRIALS_MONTHLY_CAP` tiene un fail-closed cuidado (`trial.py:84-88`) que con el default 0 nunca se ejecuta (`trial.py:299-301`).
21. `credits.py` anuncia una operación `expire:` en su docstring (`credits.py:17-18`) que vive en otro módulo.
22. `__init__.py` de `billing` lista 3 submódulos de 7 (`backend/billing/__init__.py:4-6`).
23. `frontend/src/pages/Planes.jsx:12` sigue diciendo que el CTA "pega a /api/billing/subscribe → MP devuelve init_point".
24. `Reembolso.jsx` promete reembolso por arrepentimiento sin ningún camino automatizado en el backend.

---

### 11.15 Lo que el código hace muy bien (para no perderlo)

- **El acceso no depende del cron.** `quota.get_tier` corta en tiempo real cuando el crédito vence (`backend/ai/quota.py:208-216`). El cron es la limpieza, no el enforcement.
- **El trial vence a favor del usuario.** Los 15 días se graban de una sola vez: si el cron muere, sobra Pro, no falta acceso (`trial.py:21-23`).
- **Un solo discriminador de "esto es el trial".** `credit_is_trial` (`trial.py:91-106`) tiene 6 lectores y todos preguntan lo mismo — el comentario documenta los tres bugs distintos que aparecían cuando cada uno decidía por su cuenta.
- **El tope mensual de trials se hace cumplir en el INSERT, no en un check-then-act** (`trial.py:372-385`), y se cuenta sobre el ledger append-only para que borrar la cuenta no devuelva cupo.
- **El orden convertir→cancelar en change-plan** garantiza que ninguna falla deje al usuario pagando por nada (`main.py:26646-26651`).
- **La cancelación nunca le miente al usuario**: relee el estado real ante error y devuelve `local_sync_pending` en vez de un 502 (`main.py:27356-27414`).
- **Doble candado de idempotencia del crédito** (app + índice único parcial), con la carrera SELECT→INSERT capturada y revertida (`credits.py:184-207`, `:269-284`).
- **Los webhooks se guardan ANTES de rechazarse**, para forensics y replay manual (`main.py:26864-26892`).
- **Allowlist de dominios de la URL de pago en las dos puntas** (`main.py:26594-26603`, `Planes.jsx:236`).
- **Cada bug de fechas `T`-vs-espacio está arreglado con `substr(replace(...))` y explicado con el síntoma medido** (`trial.py:65-72`, `subscriptions.py:346-351`, `:528-532`).
