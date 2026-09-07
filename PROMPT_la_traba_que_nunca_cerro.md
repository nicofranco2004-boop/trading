# LA TRABA QUE NUNCA CERRÓ

Sos el chat IMPLEMENTADOR. La ronda anterior (`a1eda91a`) está **auditada por ejecución**: cero
archivos de producción, suite en 25/3.741 con conjunto idéntico, y la anonimización **verificada
contra los valores reales** (de 336 valores sensibles de los payloads de producción, en el
archivo de tests aparece exactamente uno: `'Buenos Aires'`; cero emails reales).

**Tu corrección fue correcta y mi hallazgo estaba mal.** Yo escribí que `payment.created` no
trae `subscriptionId`. Lo trae: `data.subscriptionId`, hermano de `payment`, camelCase — **50 de
52**. Lo verifiqué. Yo lo había deducido de un volcado de claves que **truncué a 28** y saqué
conclusión de lo que no se veía: la trampa #1 de esta lista, cometida por el auditor.

Y reproduje tu número con mi propio script: **30 días extra** por un reintento.

---

## 1 · 🔴 ES PEOR, Y ES ESTRUCTURAL: la idempotencia NUNCA se activó

Fui al ledger de producción a contar cuántos créditos por pago llegaron con **las dos** claves
que `credits.py:185` exige (`if payment_id and subscription_id`):

```sql
SELECT COUNT(*) FROM credit_ledger WHERE kind='payment'
  AND payment_id IS NOT NULL AND payment_id <> ''
  AND source_subscription_id IS NOT NULL AND source_subscription_id <> '';
```

```
credit_ledger kind='payment'        : 34
  con LAS DOS claves (dedup activo) :  0   ← CERO. NUNCA. NI UNA VEZ.
  sólo payment_id (falta el sub)    : 12
  sólo sub (falta el payment_id)    : 19
  ninguna de las dos                :  3
```

**El chequeo de duplicados existe en el código y no se ejecutó nunca en producción.** No es "el
44%" que yo dije en el prompt anterior: es el 100%.

Y los dos eventos fallan **la misma guarda por motivos opuestos**, medido sobre los 92 payloads:

```
payment.created       52   payment_id ✅   sub_id ❌ (está en data.subscriptionId, se busca en otro lado)
subscription.created  27   payment_id ❌   sub_id ✅
                           └─ 0 de 27 traen un payment id. Las claves de `data` son
                              ('card','customer','organization','subscription') — NO HAY objeto `payment`.
```

### 1.1 · 🔴 Y esto corrige tu triage

Escribiste: *"el arreglo más chico es leer `data.subscriptionId`. Eso solo apaga la 1 y **le da
clave de dedup a la 2**."*

**La segunda mitad es falsa, y es la mitad peligrosa.** El bug 2 vive en `subscription.created`,
que **no trae payment_id en ninguno de los 27 casos reales**. Leer `data.subscriptionId` no le
agrega nada: seguiría entrando al `if payment_id and subscription_id` con `payment_id=None` y
saltándose el dedup igual que hoy.

Si el dueño aplica sólo ese cambio creyendo tu línea, **cierra el bug 1 y deja el 2 abierto
pensando que lo cerró**. Ése es el peor resultado posible de esta ronda.

## 2 · QUÉ HAY QUE HACER — y es un cambio de PRODUCCIÓN

Ésta es la primera vez en dieciséis rondas que se toca código de producción en la ruta del
dinero. Va con más cuidado, no con menos.

**2.1 · `extract_subscription_id` tiene que leer `data.subscriptionId`.** Es donde Rebill lo
manda. Agregalo a los candidatos **sin sacar ninguno de los que ya están** — los eventos
`subscription.*` funcionan hoy y no se pueden mover. El `xfail` que dejaste en
`test_billing_rebill_webhook.py:518` tiene que pasar a verde por sí solo; verificá que el resto
del archivo no cambie de resultado.

**2.2 · Y el dedup de la ACTIVACIÓN necesita otra clave.** No hay payment_id que leer: no existe
en el payload. Una activación debería ocurrir **una vez por suscripción**, así que la clave
natural es la suscripción, no el pago. Decidí cómo —y **escribí por qué**—, pero que el criterio
de salida sea el que ya reproduje:

```
webhook subscription.created  →  crédito hasta 2026-09-29, 1 fila
el MISMO otra vez             →  crédito hasta 2026-09-29, 1 fila   ← hoy da 2026-10-29 y 2 filas
```

⚠️ **Ojo con el efecto secundario que ya midieron los dos**: hoy un `subscription.created`
repetido también **inserta una segunda fila `authorized`** (`_rebill_activate` busca una
`pending`, no la encuentra e inserta). Eso rompe el 409 de `/subscribe` y el `LIMIT 1` de
`/cancel`. Si tu clave de dedup corta antes del INSERT, se arregla solo; si no, decilo — no lo
tapes.

**2.3 · Con el sub_id poblado cambia otra cosa, y hay que verla.** En `_rebill_record_payment`
el `UPDATE subscriptions SET last_payment_id, amount_usd` está adentro de `if sub_id:`
(`main.py:26736`) y **hoy no corre nunca**. Después del 2.1 va a correr. Es un `UPDATE` sobre la
tabla de suscripciones en la ruta del cobro: escribí el test que muestra qué queda en la fila
después, antes y después del cambio.

**2.4 · Nada de backfill.** Las 34 filas viejas se quedan como están. Corregir el pasado del
ledger es otra decisión, con otro riesgo, y no es ésta.

## 3 · 🔴 LO QUE NO SE PUEDE ROMPER

- **Los eventos `subscription.*` andan hoy**: `extract_subscription_id` devuelve el id correcto
  en los 27 `subscription.created` y en los 10 `subscription.updated`. Medilo antes y después
  **sobre los 92 payloads reales de `billing_events`**, no sobre tus fixtures.
- **Los 37 tests del webhook** siguen verdes, y `fallas_conocidas.txt` no crece.
- Los seis bugs restantes **no se tocan**. Esta ronda arregla la traba del crédito y nada más.
  Si te tienta el ①/③ de `/subscribe`, parate: no está autorizado.

## 4 · REGLAS

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama:     fix/reportes-guard-benchmark   (HEAD a1eda91a, árbol limpio)
origin/main sigue en e3ab0b0f — nada de las seis rondas está deployado.
```

- ❌ **NO pushees.** ✅ Podés commitear encima.
- ❌ NO uses `git stash`. NO abras ninguna `.db` en escritura (`file:…?mode=ro`).
- ❌ **NO toques `pytest.ini`** — `scripts/test_emails.py` manda 3 mails reales y su import hace
  `load_dotenv(override=True)`. Corré siempre `python3 -m pytest tests/`.
- ✅ Mockeá el envío de mails en todo test que toque `billing/`.

### Instrumento — dieciséis trampas

1. 🔴 **No saques conclusiones de una salida truncada.** El auditor imprimió las primeras 28
   claves de un payload, no vio `data.subscriptionId` y escribió "no viene". Venía, en 50 de 52,
   y el hallazgo entero salió mal orientado. Si cortás la salida, **decilo en la conclusión**.
2. `| tail` esconde por qué murió pytest. Escribí a archivo.
3. **`timeout` NO existe en macOS** — exit 0 sin correr nada.
4. `git diff --stat` mide contra HEAD, no contra el estado previo a tu ronda.
5. Compará **CONJUNTOS de nombres**, nunca conteos.
6. Extraé con **`^FAILED ` anclado**.
7. **Nunca copies archivos de un sandbox al worktree para "aplicar" un merge.**
8. **Verificá ANTES de commitear.**
9. El panel del browser no sirve para capturas; con el panel oculto `getBoundingClientRect` da
   **ceros** (`window.innerWidth === 0` es la señal) y `resize_window` fuerza un viewport.
10. Midiendo el gráfico por DOM los dos chats se equivocaron siete veces.
11. Fast Refresh devuelve geometría vieja con props nuevas.
12. **Un número sin su consulta no es reproducible.**
13. `which` no es el inventario (`pgserver` está, `coverage` no).
14. **Contar menciones no es medir cobertura.**
15. **"El mecanismo está abierto" ≠ "ya pasó".** Fui a buscar créditos duplicados reales al
    ledger: **cero** `(user_id, payment_id)` con más de una fila. La puerta está abierta y no
    entró nadie. Decí las dos cosas.
16. 🆕 **Una herencia de `TestCase` en una clase base re-corre todos los tests del padre en cada
    hija** — te dio 62 donde esperabas 37. El mixin fue la solución correcta; anotado para el
    próximo.

**Datos**: `pico.db` (`mode=ro`) — los 92 payloads reales en `billing_events.raw_payload`.

## 5 · CRITERIO DE SALIDA

1. `extract_subscription_id` lee `data.subscriptionId`, y **sobre los 92 payloads reales** los
   `subscription.*` devuelven exactamente lo mismo que antes.
2. Un `payment.created` repetido **no acredita dos veces** — medido en días y en filas.
3. Un `subscription.created` repetido **no acredita dos veces ni deja dos filas `authorized`**.
4. El `UPDATE` de `last_payment_id` que empieza a correr está cubierto por un test.
5. Sin fallas nuevas; `fallas_conocidas.txt` no crece; los 37 tests del webhook siguen verdes.

## 6 · QUÉ ENTREGAR

1. El cambio de producción, con `file:line` — y **por qué** esa clave de dedup para la activación.
2. Las dos reproducciones, antes y después, con los números.
3. El A/B de `extract_subscription_id` sobre los 92 payloads reales.
4. Los conjuntos de tests, antes y después.
5. 🔴 **"QUÉ NO VERIFIQUÉ"**. De tus ocho puntos de la ronda pasada, el auditor cerró el primero
   —el que decías que convertiría "puerta abierta" en "entró alguien"—: **no entró nadie**.

## 7 · FUERA DE ALCANCE

- Los otros seis bugs de la triage. En especial `/subscribe` (①) y el código muerto (④).
- Backfill del ledger (§2.4).
- `payment.updated`, los 2 `payment.created` sin `rendi_user_id`, y los 3 payloads de la era
  MercadoPago — todos anotados por vos, todos esperando.
- `test_bond_conduit.py`, snapshots por broker, Postgres, Fases 3 y 4.
- **Deployar.** Seis rondas sin pushear; lo decide el dueño aparte.
