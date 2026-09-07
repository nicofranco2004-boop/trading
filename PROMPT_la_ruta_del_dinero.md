# LA RUTA DEL DINERO

Sos el chat IMPLEMENTADOR. La ronda anterior (`8245b0e0`) está **auditada por ejecución** y
cerrada. Con ella se termina la familia de bugs que llevaba catorce rondas.

**Esta ronda es otra cosa: es plata.** Y empieza con una corrección.

---

## 0 · LO QUE CERRÓ LA RONDA 14 — no lo revises

| Qué | Verificado por el auditor |
|---|---|
| ARS · consejo nuevo sí / viejo no | ✅ con payload forzado, en el componente real |
| USD · consejo viejo sí / nuevo no | ✅ ídem, a 1280 px |
| Backend | 29 / 3.701 · conjunto **idéntico** ✅ |
| Frontend | 50 archivos / 1.351 · build limpio ✅ |

Y **tres de tus seis "no verifiqué"** quedan cerrados, medidos:

- **El renglón nuevo entra en mobile.** A 375 px: tooltip 256 px de ancho, 171 de alto,
  **0 px de overflow**, no se sale de la pantalla (izq 47, der 303, viewport 375). El párrafo
  nuevo ocupa 230×78. No hay nada que arreglar.
- **El consejo imposible no está en ninguna otra pantalla.** Grep sobre todo `frontend/src`: la
  única otra mención a "modo Estimado" es un **comentario de código** en
  `InsightsKpiStrip.jsx:110`, no texto de usuario.
- **"Configuración" existe y tiene el riel** — pero está **un salto más adentro**: `/config`
  muestra un menú de 5 secciones y `CurrencyRail` vive en **"Tipos de cambio"**
  (`Config.jsx:614`). El subtítulo dice "Moneda de valuación y cotizaciones", así que se
  encuentra. Si algún día lo tocás, nombrar la sección sería estrictamente mejor y no cuesta nada.

---

## 1 · 🔴 LA CORRECCIÓN: lo que el auditor viene repitiendo mal hace cinco rondas

Durante cinco rondas se dijo, en cada prompt: *"la ruta de cobro no tiene tests desde que
migraron de MercadoPago a Rebill"*. **Medido, es más preciso y peor en una mitad y mejor en la
otra.**

Mención por función pública de `billing/rebill.py` en toda la suite (`grep -c` por nombre, ver
el caveat de abajo):

```
CUBIERTO                            SIN UNA SOLA MENCIÓN
  verify_webhook_signature   12       create_payment_link        0   ← el link de pago
  is_likely_production       11       extract_event_name         0   ← qué evento llegó
  cancel_subscription        11       extract_subscription_id    0   ← de quién es
  validate_config             7       extract_metadata           0   ← qué plan le toca
  verify_webhook_auth         6       verify_webhook_url_token   0
  get_subscription            3       verify_api_key             0
```

**La suite verifica que un webhook sea AUTÉNTICO y nunca que se INTERPRETE bien.** Está probada
la puerta y no lo que entra por ella.

⚠️ **Caveat del instrumento**: contar menciones por nombre es un proxy, no cobertura. Una función
puede ejercitarse indirectamente. El paquete `coverage` **no está instalado** en este entorno
(`import coverage` → ImportError); si lo instalás, la medición de verdad reemplaza a ésta y
**decilo**.

## 2 · LOS DOS AGUJEROS, CON SUS NÚMEROS

### 2.1 · El webhook que da el plan no tiene NI UN test

```
ruta:  @app.post("/api/billing/rebill-webhook")     main.py:26299
tests que la mencionan:  0        (grep -rl "rebill-webhook" tests/ → vacío)
```

Es la ruta por la que entra *"el pago salió bien"* y que **activa el tier**
(`subscription.activated / subscription.created → activar tier`). Decide **quién pasa a pago y a
qué plan**. Cero cobertura.

### 2.2 · Los tests del cobro existen, apuntan al proveedor viejo, y están **perdonados**

`/api/billing/subscribe` (`main.py:25994`) llama a `rebill.create_payment_link` en la línea
**26050**, **sin ningún switch de proveedor**: no hay rama de MercadoPago que se pueda tomar.

Y sus tests mockean `billing.mercadopago.create_preapproval` (`tests/test_billing.py:43, 77`).
Por eso fallan. Y por eso están **en `fallas_conocidas.txt`**:

```
tests/test_billing.py::BillingSubscribeTest::test_subscribe_creates_preapproval_and_saves_to_db
tests/test_billing.py::BillingSubscribeTest::test_subscribe_reuses_pending_subscription
tests/test_billing.py::BillingCancelTest::test_cancel_marks_subscription_cancelled
tests/test_billing_lifecycle.py::FullLifecycleJobTest::test_runs_all_three_steps_and_returns_counts
```

**Cuatro de las 29 fallas conocidas son la ruta del dinero.** No son ruido viejo: son la
migración sin terminar, archivada como "conocida".

Y el propio archivo, en su encabezado, dice:

> *"⚠️ ESTO NO ES UNA LISTA DE PERDÓN. Es la línea de base: lo que ya estaba roto antes de esta
> ronda."*

Éstas están perdonadas hace rato. **Son las primeras que hay que sacar de ahí.**

## 3 · QUÉ HACER

**3.1 · Migrar los cuatro.** Que prueben lo que el endpoint hace de verdad: `create_payment_link`
de Rebill, no `create_preapproval` de MercadoPago. Y **sacalos de `fallas_conocidas.txt`** — el
baseline tiene que bajar de 29. Es la primera vez en catorce rondas que ese número baja; que se
note.

**3.2 · Cubrir el webhook.** Como mínimo, y cada uno con su aserción sobre el **estado de la DB**,
no sobre el status code:
- un `subscription.activated` legítimo **activa el tier correcto** para el usuario correcto;
- un webhook **con firma inválida no toca nada** (hoy `verify_webhook_auth` está probada sola,
  no a través de la ruta);
- un evento **repetido no cobra ni acredita dos veces** (mirá cómo se usa `mp_event_id`);
- metadata rota o de otro usuario **no activa a nadie**.

**3.3 · Las tres `extract_*`.** Son funciones puras sobre un dict: son los tests más baratos del
repo y deciden a quién se le da el plan. No hay excusa para que estén en 0.

⚠️ **Usá payloads REALES de Rebill**, no inventados. Si no tenés uno, buscá en el repo (logs,
fixtures, el propio `rebill.py`) y **decí de dónde lo sacaste**. Un test que pasa contra un
payload imaginario prueba tu imaginación.

## 4 · 🔴 LA REGLA QUE MÁS IMPORTA EN ESTA RONDA

**Vas a encontrar bugs. NO los arregles acá.**

Escribir tests sobre código de plata que nunca los tuvo destapa cosas. Cuando pase:
**anotalo con su reproducción y seguí.** Un arreglo de facturación metido de contrabando en una
ronda de cobertura es exactamente cómo se rompe el cobro — y el dueño decide qué se toca en la
ruta que le entra la plata, no vos ni yo.

Si un test que escribís no puede pasar sin cambiar producción, **dejalo como `xfail` con el
motivo escrito** y reportalo. Un `xfail` documentado vale más que un arreglo apurado.

**Y no toques nada de lo anterior**: certero bit-idéntico · estimado ⊇ certero · el clamp ·
el eje temporal · una frase por pantalla en las dos monedas · el toggle de USD byte-idéntico.

## 5 · REGLAS

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama:     fix/reportes-guard-benchmark   (HEAD 8245b0e0, árbol limpio)
origin/main sigue en e3ab0b0f — nada de las cuatro rondas está deployado.
```

- ❌ **NO pushees.** ✅ Podés commitear encima.
- ❌ NO uses `git stash`. NO abras ninguna `.db` en escritura (`file:…?mode=ro`).
- ❌ **NO toques `pytest.ini`.** Leé su encabezado antes de pensarlo.

### 🔴 El peligro específico de ESTA ronda: mandar mails de verdad

`backend/scripts/test_emails.py` **manda 3 mails reales por Resend**, y su import hace
`load_dotenv(override=True)`: con **sólo colectarlo**, las credenciales de producción pisan el
entorno de toda la corrida. `pytest.ini` lo bloquea con `testpaths` + `norecursedirs`, y hacen
falta **las dos** líneas.

Vas a estar tocando `billing/`, que es de donde salen los mails de cobro (`billing/emails.py`,
81 KB). **Corré siempre `python3 -m pytest tests/`**, nunca `pytest .` ni `pytest -k algo` desde
otra carpeta, y si un test tuyo toca el envío, **mockealo explícitamente**.

### Instrumento — catorce trampas que ya cobraron

1. `| tail` esconde por qué murió pytest. Escribí a archivo.
2. **`timeout` NO existe en macOS** — falla y devuelve exit 0 sin correr nada.
3. `git diff --stat` mide contra HEAD, no contra el estado previo a tu ronda.
4. Compará **CONJUNTOS de nombres**, nunca conteos.
5. Extraé el conjunto con **`^FAILED ` anclado**: el log tiene líneas propias que empiezan con
   `ERROR ` y el auditor contó 43 donde había 29.
6. **Nunca copies archivos de un sandbox al worktree para "aplicar" un merge.**
7. **Verificá ANTES de commitear**, no después.
8. **El panel del browser no sirve para capturas** (cuatro rondas confirmándolo). Pero 🆕 **si
   está oculto, `getBoundingClientRect` devuelve CEROS**: `window.innerWidth === 0` es la señal
   de que tu medición de layout no vale nada. `resize_window` fuerza un viewport medible aunque
   el panel esté escondido — el auditor midió los 375 px así.
9. Midiendo el gráfico por DOM los dos chats se equivocaron **siete** veces. Leé `chartData` del
   fiber, no el dibujo.
10. El Fast Refresh devuelve geometría vieja con props nuevas. Recargá duro entre builds.
11. **Un número sin su consulta no es reproducible.**
12. `which` no es el inventario: hay PostgreSQL real vía el paquete pip `pgserver`. Y al revés:
    **`coverage` NO está**, aunque suene a que tiene que estar. Verificá antes de prometer.
13. Una A/B vale más que un "antes" recordado. Antes de reconstruir un estado previo, fijate si
    ya lo tenés al lado en la misma pantalla.
14. 🆕 **Contar menciones no es medir cobertura**, y afirmar "no tiene tests" sin abrir los tests
    es cómo el auditor sostuvo cinco rondas una frase a medias. Abrí los archivos.

**Datos**: `pico.db` en el scratchpad (copia de producción estampada, `mode=ro`). App local:
`http://localhost:5199`, `demo.metricas@rendi.test` / `demo1234`.

## 6 · CRITERIO DE SALIDA

1. **`fallas_conocidas.txt` BAJA**: los cuatro del cobro salen, migrados a Rebill.
2. `/api/billing/rebill-webhook` tiene tests, y **asertan sobre el estado de la DB**.
3. Las tres `extract_*` tienen tests, con payloads **reales** y su procedencia dicha.
4. **Ninguna falla nueva**, y ninguna del resto de la lista desaparece por accidente.
5. **Cero cambios en producción** salvo que el dueño lo autorice después de leer el reporte.

## 7 · QUÉ ENTREGAR

1. Los tests nuevos, con `file:line`.
2. El conjunto de fallas **antes y después**, y el `fallas_conocidas.txt` nuevo.
3. 🔴 **La lista de bugs que encontraste y NO arreglaste**, cada uno con su reproducción. Esto es
   el entregable más valioso de la ronda: es lo que el dueño no sabe todavía.
4. De dónde salieron los payloads.
5. 🔴 **"QUÉ NO VERIFIQUÉ"**. Las tres últimas rondas fueron buenas: de sus puntos, **seis** se
   pudieron cerrar porque quedaron escritos. Seguí.

## 8 · FUERA DE ALCANCE

- **Arreglar los bugs que encuentres.** §4. Reportalos.
- `test_bond_conduit.py` — 640 donde se espera 720; el mejor candidato a bug real de las 29
  restantes, pero no es plata.
- El POST del browser sin guarda de cobertura (el cron sí la tiene).
- **Snapshots por broker** — lo que habilitaría el estimado en ARS de verdad. Proyecto.
- Postgres, Fases 3 y 4.
- **Deployar.** Las cuatro rondas de Insights siguen sin pushear; eso lo decide el dueño aparte.
