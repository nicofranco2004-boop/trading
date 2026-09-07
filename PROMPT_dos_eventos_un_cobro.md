# DOS EVENTOS, UN SOLO COBRO

Sos el chat IMPLEMENTADOR. La ronda anterior (`f50beefb`) está **auditada por ejecución**, y es
la primera que tocó producción en diecisiete. **Pasó todo.**

---

## 0 · LO QUE VERIFIQUÉ DEL CAMBIO DE PRODUCCIÓN

| Qué | Resultado |
|---|---|
| Suite | **25 / 3.745 / 11 xfail** ✅ conjunto idéntico, 0 nuevas |
| A/B de `extract_subscription_id` sobre los 92 payloads reales | `payment.created` **0 → 50**; `subscription.*` **sin moverse**; **0 filas regresan** ✅ |
| El `subscription.created` repetido, forma real | ✅ no duplica: clave `subcreated:sub_…`, 1 fila de ledger, 1 fila `authorized` |
| El `payment.created` repetido | ✅ no duplica |
| Archivos de producción | 2, con el cambio acotado y comentado ✅ |

Reproduje las dos con mis propios scripts, no con tus tests.

**Y fui a buscar el riesgo que un cambio así puede traer**: al poblar las dos claves se activa
por primera vez el `CREATE UNIQUE INDEX idx_credit_ledger_payment_dedup` (`main.py:2264`), que
hasta ahora era inerte. Una carrera entre el `SELECT` y el `INSERT` ahora puede reventar.
**Ya está contemplado**: `credits.py:269` captura `ERR_INTEGRIDAD` y el `with conn` revierte el
UPDATE. El arreglo encendió una red que estaba puesta y nunca se había probado sola.

## 1 · 🔴 EL OCTAVO BUG ES EL ÚNICO QUE YA COSTÓ PLATA — y sigue abierto

Lo encontraste vos y lo confirmé. Es, con diferencia, el más importante de los ocho.

**Cada alta dispara DOS eventos que acreditan por separado.** Medido sobre los 92 payloads:

```
payment.created · data.payment.paymentType
   first_subscription_payment       27   ← uno por cada subscription.created
   recurring_subscription_payment   23
```

Los 27 `subscription.created` y los 27 `first_subscription_payment` son **el mismo cobro**. El
primero entra por `_rebill_activate` y acredita un período; el segundo entra por
`_rebill_record_payment` y acredita **otro**.

Y está en el ledger de producción, con segundos de diferencia:

```
user=127  Δ=1s   +30 días
   A  pay=None                 sub=sub_b230546566   "Rebill payment (plus monthly)"
   B  pay=pay_6077a3cfe56e…    sub=None             "Rebill renewal payment pay_6077…"
```

```
pares de créditos al mismo user a ≤120s : 6
usuarios                                : 4
días acreditados dos veces              : 180
```

⚠️ **Precisión sobre el daño real**, que tu informe no separó: **3 de los 6 pares son el uid 1**,
con ids `test_sub_*` / `test_pay_*` — la cuenta del dueño, datos de sandbox. Los clientes de
verdad son **3 (127, 285, 700), 30 días cada uno: 90 días**. Sigue siendo plata regalada, pero
es la mitad de lo que dice el número grande. Decilo así.

**Y tu arreglo de la ronda 17 no lo toca, con razón**: son `payment_id` distintos (uno sintético,
uno real) y cruzarlos rompería las renovaciones legítimas.

## 2 · QUÉ HAY QUE HACER

Que **un cobro acredite una vez**. El campo que lo permite es
`data.payment.paymentType == "first_subscription_payment"`, presente en los 27.

Las dos direcciones posibles, y **la trampa de cada una**:

**A · Que la activación no acredite y lo haga el pago.**
⚠️ Si el `payment.created` no llega —o llega sin `rendi_user_id`, que ya pasa en 2 de 52— el
usuario queda con **tier pago y sin crédito**, y el cron diario lo baja a Free. Es exactamente el
daño del bug ⑤ de tu triage: le sacás lo que pagó. Es el peor error posible acá.

**B · Que el `first_subscription_payment` no acredite, porque la activación ya lo hizo.**
⚠️ Depende de un campo que descubrimos hace dos horas. Si Rebill deja de mandarlo o cambia el
valor, volvés a acreditar dos veces — silenciosamente.

**Elegí una, escribí por qué, y escribí qué pasa si el supuesto falla.** El criterio: entre
*regalar un mes* y *sacarle a alguien lo que pagó*, el segundo es peor. Que el modo de fallar sea
el que se puede corregir después.

⚠️ **Y no dependas sólo del `paymentType`**: mirá si el sub_id ya tiene un crédito de activación
—ahora la clave `subcreated:<sub_id>` te lo dice— antes de acreditar el primer pago. Una defensa
que mira el estado es más difícil de romper que una que mira una etiqueta.

## 3 · 🔴 Y UNA FRAGILIDAD QUE MEDÍ EN TU ARREGLO — no es un bug, es un supuesto

Corrí el `subscription.created` repetido en tres formas:

```
forma REAL (sin objeto `payment`, 27 de 27)   → ✅ no duplica   clave 'subcreated:sub_…'
con `payment`, MISMO id (reintento puro)      → ✅ no duplica   clave 'pay_1'
con `payment`, ids DISTINTOS                  → 🔴 acredita dos veces
```

El tercero **no ocurre hoy** (0 de 27 traen objeto `payment`), y podría argumentarse que dos
pagos distintos *deberían* acreditar dos veces. Pero deja claro qué garantiza tu arreglo: la
regla "una activación por suscripción" **no está escrita en el código — está heredada de la forma
actual del payload**. El día que Rebill agregue un `payment` ahí, la identidad del dedup cambia
sola de "por suscripción" a "por pago" y nadie se entera.

**No lo arregles en esta ronda.** Dejalo escrito como comentario donde está la clave sintética,
con el número: *"vale mientras 0 de 27 traigan payment"*. Si en el 2 elegís una defensa que mira
el estado y no la etiqueta, esto se cubre solo.

## 4 · LO QUE NO SE PUEDE ROMPER

- **Lo de la ronda 17**: los 50 `payment.created` que recuperaron su sub_id, los `subscription.*`
  sin moverse, y las dos no-duplicaciones ya medidas. Reproducí las tres.
- **Los 40 tests del webhook**, verdes. `fallas_conocidas.txt` en 25, sin crecer.
- **Los otros seis bugs de la triage no se tocan.** En especial `/subscribe` (①).
- **Ningún backfill del ledger.** Los 90 días ya regalados son una decisión del dueño, aparte:
  anotá qué haría falta para corregirlos y **no lo hagas**.

## 5 · REGLAS

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama:     fix/reportes-guard-benchmark   (HEAD f50beefb, árbol limpio)
origin/main sigue en e3ab0b0f — SIETE rondas sin deployar.
```

- ❌ **NO pushees.** ✅ Podés commitear encima.
- ❌ NO uses `git stash`. NO abras ninguna `.db` en escritura (`file:…?mode=ro`).
- ❌ **NO toques `pytest.ini`** — `scripts/test_emails.py` manda 3 mails reales.
- ✅ Mockeá el envío de mails en todo test que toque `billing/`.

### Instrumento — diecisiete trampas

1. 🔴 **No saques conclusiones de una salida truncada.** El auditor imprimió 28 claves de un
   payload, no vio `data.subscriptionId` y escribió "no viene". Venía, en 50 de 52.
2. 🆕 **Un repro viejo prueba el mundo viejo.** El auditor volvió a correr su script de la ronda
   15 contra el código arreglado y le dio 🔴 duplica — pero su payload llevaba un objeto
   `payment` que **no existe en ninguno de los 27 reales**. El arreglo estaba bien; el que había
   envejecido era el instrumento. Cuando un repro contradiga un arreglo, **revisá primero si el
   repro sigue describiendo la realidad**.
3. `| tail` esconde por qué murió pytest. Escribí a archivo.
4. **`timeout` NO existe en macOS.**
5. `git diff --stat` mide contra HEAD.
6. Compará **CONJUNTOS de nombres**, nunca conteos, y extraé con **`^FAILED ` anclado**.
7. **Nunca copies archivos de un sandbox al worktree para "aplicar" un merge.**
8. **Verificá ANTES de commitear.**
9. El panel del browser no sirve para capturas; con el panel oculto `getBoundingClientRect` da
   ceros (`window.innerWidth === 0`) y `resize_window` fuerza un viewport.
10. Midiendo el gráfico por DOM los dos chats se equivocaron siete veces.
11. Fast Refresh devuelve geometría vieja con props nuevas.
12. **Un número sin su consulta no es reproducible.**
13. `which` no es el inventario (`pgserver` está, `coverage` no).
14. **Contar menciones no es medir cobertura.**
15. **"El mecanismo está abierto" ≠ "ya pasó"** — pero acá **sí pasó**: 6 pares en el ledger. Y
    al revés, **separá el sandbox del cliente real**: 3 de esos 6 son la cuenta del dueño.
16. Heredar de `TestCase` en una clase base re-corre los tests del padre en cada hija.
17. Una A/B vale más que un "antes" recordado.

**Datos**: `pico.db` (`mode=ro`) — los 92 payloads en `billing_events.raw_payload`.

## 6 · CRITERIO DE SALIDA

1. Un alta completa —`subscription.created` **+** su `first_subscription_payment`— acredita
   **un** período. Medido en días y en filas de ledger.
2. Una renovación (`recurring_subscription_payment`) **sí** acredita. No rompas el caso bueno.
3. Un alta a la que **no** le llega el pago **conserva el crédito** (o se declara explícitamente
   por qué no).
4. Las tres reproducciones de la ronda 17, sin moverse.
5. Sin fallas nuevas; los 40 tests del webhook verdes.
6. La fragilidad del §3, comentada en el código con su número.

## 7 · QUÉ ENTREGAR

1. El cambio, con `file:line`, y **por qué esa dirección y no la otra**.
2. Las mediciones del §6.1 a §6.4, con números.
3. Qué haría falta para corregir los 90 días ya regalados — **descrito, no ejecutado**.
4. Los conjuntos de tests, antes y después.
5. 🔴 **"QUÉ NO VERIFIQUÉ"**. El punto 1 de tu lista anterior —la transición si Rebill manda un
   payment_id— lo medí yo y está en el §3: tenías razón en marcarlo.

## 8 · FUERA DE ALCANCE

- Los otros seis bugs. `/subscribe` (①), el código muerto (④), el resto de la triage.
- Backfill del ledger (§4).
- `payment.updated`, los 2 `payment.created` sin `rendi_user_id`, los 3 payloads de la era
  MercadoPago, el fallback de `_rebill_activate` con el ledger caído.
- `test_bond_conduit.py`, snapshots por broker, Postgres, Fases 3 y 4.
- **Deployar.** Siete rondas sin pushear; lo decide el dueño.
