# El mail de bienvenida no salía por Rebill

**Rama:** `fix/mail-bienvenida-rebill` (sobre `fix/tests-en-rojo`) · **2026-09-08** · sin deployar
**Suite:** 4023 passed, 93 skipped, 10 xfailed, **0 failed**

---

## Qué pasaba

`send_welcome_pro` tenía **un** caller en producción, y colgaba del webhook de Mercado Pago:

```
send_welcome_pro           ← main.py:27959
  _maybe_send_welcome_email  ← único caller: main.py:27937
    _process_preapproval_event = webhook de MERCADO PAGO
```

Las altas de hoy entran por Rebill. Sus tres handlers —`_rebill_activate` (169 líneas),
`_rebill_subscription_status_change` (36) y `_rebill_record_payment` (105)— **no mandan un solo
mail**: verificado buscando `emails.` / `send_*` en las tres funciones completas.

Nadie lo vio porque los únicos tests del mail (`tests/test_billing_emails.py`) mockean
`billing.mercadopago` y están **en verde**: prueban el camino que ya no corre.

## Qué se arregló

**1. El disparador, en el router y no adentro de los handlers.** `_notificar_alta_rebill` se llama
desde la rama `subscription.created` de `rebill_webhook`, después de `_rebill_activate` (que es
quien deja el `sub_id` real en `mp_subscription_id`, por donde la bienvenida busca la fila).

Va ahí por dos razones: notificar no es activar —el que otorga crédito no tiene por qué saber de
mails— y así el diff no se mete en las funciones que están bajo auditoría de la ruta del dinero.
Reusa `_maybe_send_welcome_email` tal cual: ya era idempotente por `welcome_email_sent_at`, que es
la traba que importa porque **`subscription.created` se re-entrega** (medido sobre payloads reales
en una ronda anterior).

**2. El mail ya no puede decir "ARS 0".** Por Rebill, `amount_ars` se escribe en exactamente dos
INSERT (`main.py:26903` y `:27335`), los dos con literal `0`, y **nada lo actualiza después**.
Cablear el mail sin tocar esto le decía "ARS 0 mensual" a alguien que acababa de pagar. Ahora: si
no hay importe, el bloque muestra sólo la renovación; si tampoco hay fecha, no se muestra. El
camino de MP —donde el importe sí viene— queda igual. (De paso, `_fmt_ars(None)` reventaba en
`int(None)`.)

**3. A un suscriptor de Plus ya no le dice "Bienvenido a Pro".** `send_welcome_pro(plan=…)`
defaultea a `"pro"` y `_maybe_send_welcome_email` nunca lo pasaba — se escribió cuando había un
solo plan. El metadata de Rebill trae `rendi_plan`, así que ahora se pasa.

**4. La fecha de renovación aparece.** El helper lee `next_payment_date` (nombre de MP); Rebill
manda `nextChargeDate`. Se traduce en el disparador nuevo, sin tocar el camino de MP.

## Los tests

`tests/test_mail_bienvenida_rebill.py`, 6 casos, **entrando por el webhook** (`POST
/api/billing/rebill-webhook`) y no por el helper: el arreglo vive en el router, así que un test que
llamara a `_maybe_send_welcome_email` —o incluso a `_rebill_activate`— pasaría en verde sin ejercer
una línea de lo nuevo.

Verificado en las dos direcciones: **con el arreglo 6/6 pasan; sin él, 6/6 fallan.** Los dos guards
(sub_id vacío, mail caído) se reforzaron para que también fallen sin el arreglo — como estaban,
pasaban en vacío sobre el código roto y no probaban nada.

La forma de los payloads es real (sale de lo que `extract_event_name` / `extract_subscription_id` /
`extract_metadata` leen de verdad); **los valores son falsos**, ningún dato personal entra al
archivo.

## Antes de deployar

Todo suscriptor Rebill actual tiene `welcome_email_sent_at` en NULL. El disparador cuelga sólo de
`subscription.created`, que para ellos ya pasó — **pero ese evento se re-entrega**, y una
re-entrega vieja les mandaría un "bienvenido" meses tarde. Correr antes del deploy:

```sql
UPDATE subscriptions
   SET welcome_email_sent_at = COALESCE(welcome_email_sent_at, created_at)
 WHERE status = 'authorized' AND welcome_email_sent_at IS NULL;
```

Es idempotente y sólo toca filas ya activas. **No lo corrí**: es producción.

Decisión aparte, tuya: **los que ya pagaron y nunca recibieron nada, ¿reciben algo?** Si la
respuesta es sí, no es este mail (un "bienvenido" con fecha vieja se lee raro) sino uno distinto y
en una corrida controlada.

## Lo que NO hice, y por qué — para tu triage de la ruta del dinero

Propuse tres mails; la Fase 0 mostró que dos se apoyan en piso que está en reparación.

**① Receipt de cada renovación — no implementable hoy.** Sale de `payment.created`, que es el 57%
del tráfico y **no trae `subscription_id` en el 100% de los casos reales**. Sin eso no hay fila de
suscripción que mirar: ni para sacar el mail, ni para estampar "ya lo mandé". Depende del arreglo
de `extract_subscription_id` que está en tu triage.
*Daño:* nadie recibe comprobante de un cobro recurrente. Le pasa a todo el que renueva.

**② Aviso de pago rechazado — sin evidencia de que el evento llegue.** Misma dependencia del
`subscription_id`, y además no está verificado que un pago rechazado llegue como `payment.updated`
ni con qué status. Sobre los 92 payloads reales no hay ninguno.
*Daño:* a alguien se le vence la tarjeta, la suscripción se cae y no se entera. Probable, pero
frecuencia sin medir.

**③ Baja iniciada por Rebill — decisión de producto, no técnica.** `_maybe_send_cancellation_email`
sí sale cuando la persona cancela desde la app (cuelga de `billing_cancel`, que es
proveedor-agnóstico). El hueco es la baja involuntaria (tarjeta rechazada N veces →
`subscription.updated`), y ahí el mail correcto probablemente no sea "cancelaste" sino uno de
"se te venció el pago". Eso lo decidís vos.

**Y una que quedó sin resolver:** la moneda. `_rebill_activate` guarda `payment.amount` en
`amount_usd` (`main.py:27282`) **sin mirar la moneda**, y el payment link se crea con
`"currency": "ARS"` (`billing/rebill.py:161`). O ese campo tiene pesos con nombre de dólares, o
Rebill convierte. No lo pude verificar: `pico.db` —la copia de producción con los 92 payloads
reales— **ya no está en disco**. Es la única pregunta de la Fase 0 que quedó abierta, y es de la
familia de errores que más caro salió en este repo.
