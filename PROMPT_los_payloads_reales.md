# LOS PAYLOADS REALES — y el evento más frecuente, que nadie probó

Sos el chat IMPLEMENTADOR. La ronda anterior (`623563e4`) está **auditada por ejecución** y es
la mejor de las quince: **cero archivos de producción tocados**, y el baseline bajó de 29 a 25
por primera vez desde que existe.

Esta ronda **termina la cobertura del webhook** — y ahora con payloads de verdad.

---

## 0 · LO QUE VERIFIQUÉ, Y UNA CORRECCIÓN TUYA QUE ERA CORRECTA

| Qué | Resultado |
|---|---|
| Suite | **25 fallas / 3.731 pasan / 11 xfail** ✅ exactamente lo que reportaste |
| `fallas_conocidas.txt` | 25 ids, **coincidencia exacta** con lo que falla: 0 nuevas, 0 perdones sobrantes ✅ |
| Qué salió | los 4, y **nada entró** ✅ |
| Archivos de producción tocados | **0** ✅ |

**Tu corrección al enunciado era correcta y la mía estaba mal**: sólo **tres** de las cuatro eran
la migración. La de `lifecycle` fallaba por un fixture sin las columnas del free trial
(`trial_started_at`, `managed_by`, `quota_window_from`) — el job devolvía `errors=2` por
`no such column`, nada que ver con MercadoPago. Lo verifiqué en tu diff.

### Los seis bugs: verificados, uno reproducido de cero

| # | Verificación del auditor |
|---|---|
| ① `/subscribe` no reusa la pending | ✅ por código: `WHERE status='authorized'` (main.py:26032) y `"reused": False` fijo (:26107) |
| ② idempotencia del crédito sin `user_id` | ✅ por código: `credits.py:186-192` filtra por `(sub_id, payment_id, kind)` |
| ③ `subscription.created` repetido | ✅ **REPRODUCIDO** con mi propio script y mi propio payload |
| ④ `_sync_authorized_with_mp` muerto | ✅ sólo 3 tests lo llaman; `synced_from_mp` se inicializa en 0 y nunca se escribe |
| ⑤ el docstring promete eventos que no rutea | ✅ y es **peor**: lista 7 nombres y el router atiende **uno** de esa lista |
| ⑥ sin índice único en `mp_event_id` | ✅ sólo dos índices no-únicos (main.py:1995-1998) |

Mi reproducción de ③, independiente de tus tests:

```
webhook #1  200  tier=pro  crédito hasta 2026-09-29  1 fila authorized
webhook #2  200  tier=pro  crédito hasta 2026-10-29  2 filas authorized  ← mismo sub_id
```

**Un mes gratis y una fila duplicada.** Confirmado.

---

## 1 · 🔴 LOS PAYLOADS REALES EXISTEN — y los encontré

Dijiste, con razón, que ningún payload salió de Rebill. **Salen de acá**, en la copia de
producción que ya tenías:

```sql
-- pico.db, mode=ro
SELECT raw_payload FROM billing_events WHERE raw_payload IS NOT NULL AND raw_payload <> '';
-- 92 filas, todas con el JSON crudo
```

Corriendo las `extract_*` **reales** sobre esas 92 filas:

```
evento                        n   sin sub_id   sin rendi_user_id
payment.created              52          52 ←              2
subscription.created         27           0                5
subscription.updated         10           0                0
subscription_preapproval      2           0                2   (era MercadoPago)
payment                       1           0                1   (era MercadoPago)
```

**Primero, la buena noticia, que corrige mi §⑤ de arriba**: los nombres que el docstring promete
y el router no atiende —`subscription.activated`, `subscription.cancelled`, `payment.succeeded`,
`payment.failed`, `subscription.renewed`— **NO LLEGAN NUNCA**. Rebill manda tres nombres y el
router los cubre a los tres. ⑤ es documentación podrida, no un agujero vivo. Iba a escribir que
una cancelación podía perderse; lo medí y no es cierto.

## 2 · 🔴 EL HALLAZGO: el evento más frecuente pierde el `subscription_id`

**`extract_subscription_id` devuelve `''` en los 52 `payment.created`. El 100%.** Y son el 57%
de todo el tráfico.

La causa, sobre la forma real: `payment.created` trae `data.payment.id`, `data.customer.email`,
`data.card.*` — **y ningún `subscriptionId`**. La función lo busca en
`data.payment.subscriptionId` (`rebill.py:534`), que en la vida real no está.

Qué pasa entonces en `_rebill_record_payment` (`main.py:26691`), que es el que registra las
**renovaciones**:

1. El `UPDATE subscriptions SET last_payment_id, amount_usd` está adentro de `if sub_id:`
   (`:26736`) → **no se ejecuta nunca** para renovaciones.
2. El crédito **sí** se otorga: sale del `credit_anchor_plan/period` del user, que no depende
   del sub_id.
3. 🔴 **Y se otorga SIN clave de idempotencia**: pasa `subscription_id=sub_id or None`
   (`:26777`), y `credits.py:185` exige **las dos** (`if payment_id and subscription_id:`).
   Con una en None, **el chequeo de duplicados se saltea entero**.

Medido en el ledger de producción:

```
credit_ledger kind='payment' :  34 filas
   … SIN source_subscription_id :  15   (44%)   ← escritas con el dedup apagado
```

Y las redeliveries existen: **dos `payment_id` llegaron CUATRO veces cada uno**
(`test_pay_e7e1…`, `test_pay_6a8f…`).

⚠️ **Honestidad sobre el alcance**: esos dos son `test_pay_*` (sandbox), y fui a buscarlos al
ledger — **no generaron ni una fila**, así que **no hay ningún mes duplicado demostrado** en esta
copia. Lo que está demostrado es que **el mecanismo está abierto** en el 44% de los créditos por
pago, y que el mismo `payment_id` sí se re-entrega. No lo cuentes como plata perdida: contalo
como una puerta sin traba.

⚠️ Y `mp_event_id` está **vacío en las 52 filas**, así que el índice único que proponía tu ⑥
tampoco tendría de qué agarrarse tal como está hoy.

## 3 · QUÉ HACER

**3.1 · Cubrir los dos handlers que faltan, con payloads REALES sacados de `billing_events`.**

- `payment.created` → `_rebill_record_payment`. **57% del tráfico, cero tests.** Que las
  aserciones sean sobre la DB: qué pasa con `last_payment_id`, con `credit_active_until`, y
  **qué pasa cuando el mismo `payment.created` llega dos veces**.
- `subscription.updated` → `_rebill_subscription_status_change`. Son 10 eventos reales y traen
  todo: `data.id`, `data.status`, `data.lastStatus`, `data.statusDetail` y el
  `data.metadata.rendi_user_id` completo. **Es el camino por el que se cancela una suscripción**
  y no tiene un solo test.

**3.2 · Anonimizá lo que copies.** Los payloads reales traen `data.customer.email`,
`firstName`, `lastName`, `phone` y `data.card.lastFourDigits`. **Nada de eso entra a un archivo
de tests.** Reemplazá por valores obviamente falsos y **dejá dicho en el archivo que la FORMA es
real y los VALORES no**.

**3.3 · Medí la consecuencia del sub_id vacío**, no la asumas: escribí el test que manda dos
veces el mismo `payment.created` real y **contá las filas del `credit_ledger` y los días de
crédito**. Si otorga dos veces, ese test es el entregable más valioso de la ronda. Si no otorga,
también — y entonces explicá por qué, porque significa que hay otra traba que no vimos.

**3.4 · La triage.** Ya hay **siete** hallazgos sobre la ruta del dinero (tus ⑥ + éste). El dueño
necesita decidir cuáles se tocan. Entregá una lista **ordenada por daño real**, y para cada uno:
a quién le pasa, cuánta plata o cuántos usuarios, y qué tan probable es. Sin proponer el
arreglo — el orden, no la solución.

## 4 · 🔴 LA REGLA, OTRA VEZ: no arregles nada

Vale igual que la ronda pasada, y ahora más: hay siete bugs conocidos en la ruta por la que entra
la plata. **Ninguno se toca hasta que el dueño lea la triage y elija.** Un `xfail` documentado
sigue valiendo más que un arreglo apurado.

**Y no muevas nada de lo anterior**: las 25 fallas conocidas, los 26 tests del webhook, el
frontend de las cuatro rondas de Insights.

## 5 · REGLAS

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama:     fix/reportes-guard-benchmark   (HEAD 623563e4, árbol limpio)
origin/main sigue en e3ab0b0f — nada está deployado.
```

- ❌ **NO pushees.** ✅ Podés commitear encima.
- ❌ NO uses `git stash`. NO abras ninguna `.db` en escritura (`file:…?mode=ro`).
- ❌ **NO toques `pytest.ini`** — `scripts/test_emails.py` manda 3 mails reales y su import hace
  `load_dotenv(override=True)`. Corré **siempre** `python3 -m pytest tests/`.
- ✅ Mockeá el envío de mails en cualquier test que toque `billing/` (como hiciste con
  `send_plan_change_admin` — estuvo bien).

### Instrumento — quince trampas

1. `| tail` esconde por qué murió pytest. Escribí a archivo.
2. **`timeout` NO existe en macOS** — exit 0 sin correr nada.
3. `git diff --stat` mide contra HEAD, no contra el estado previo a tu ronda.
4. Compará **CONJUNTOS de nombres**, nunca conteos.
5. Extraé con **`^FAILED ` anclado**: el log tiene líneas propias que empiezan con `ERROR `.
6. **Nunca copies archivos de un sandbox al worktree para "aplicar" un merge.**
7. **Verificá ANTES de commitear.**
8. El panel del browser no sirve para capturas. Y si está oculto, `getBoundingClientRect`
   devuelve **ceros**: `window.innerWidth === 0` es la señal. `resize_window` fuerza un viewport.
9. Midiendo el gráfico por DOM los dos chats se equivocaron siete veces. Leé `chartData`.
10. Fast Refresh devuelve geometría vieja con props nuevas.
11. **Un número sin su consulta no es reproducible.**
12. `which` no es el inventario (`pgserver` sí está, `coverage` no).
13. Una A/B vale más que un "antes" recordado.
14. **Contar menciones no es medir cobertura.**
15. 🆕 **"El mecanismo está abierto" ≠ "ya pasó".** El auditor midió 44% de créditos sin clave de
    dedup y dos `payment_id` re-entregados 4 veces, y estuvo a punto de escribir "meses
    regalados". Fue al ledger: **cero filas**. La diferencia entre una puerta sin traba y un robo
    es ir a mirar si entró alguien.

**Datos**: `pico.db` (copia de producción, `mode=ro`) — ahí están los 92 payloads.

## 6 · CRITERIO DE SALIDA

1. `payment.created` y `subscription.updated` tienen tests, con **forma real** y valores falsos.
2. Está **medido** qué pasa cuando el mismo `payment.created` llega dos veces.
3. Ningún dato personal real en el repo.
4. Sin fallas nuevas; `fallas_conocidas.txt` no crece.
5. **Cero cambios en producción.**
6. La triage de los siete, ordenada por daño.

## 7 · QUÉ ENTREGAR

1. Los tests, con `file:line`.
2. La medición del `payment.created` duplicado — el número, no la expectativa.
3. 🔴 **La triage ordenada**: a quién le pasa, cuánto, y qué tan probable.
4. Los conjuntos de tests, antes y después.
5. 🔴 **"QUÉ NO VERIFIQUÉ"**. Las cuatro últimas fueron buenas; de tus seis puntos de la ronda
   pasada, **tres** se cerraron porque quedaron escritos — y uno de ellos, el de los payloads,
   fue el que abrió este hallazgo.

## 8 · FUERA DE ALCANCE

- **Arreglar los siete bugs.** §4.
- Las tres ramas de `_rebill_activate` con el ledger caído (tu punto 5) — cuando esté la triage.
- `test_bond_conduit.py` — 640 donde se espera 720.
- **Snapshots por broker**, Postgres, Fases 3 y 4.
- **Deployar.** Cinco rondas sin pushear; lo decide el dueño aparte.
