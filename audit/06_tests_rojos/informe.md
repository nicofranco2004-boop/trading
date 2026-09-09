# Los 27 tests en rojo de main

**Fecha:** 2026-09-08 · **Baseline:** `origin/main` = `56c26782` · **Rama de trabajo:** `fix/tests-en-rojo`
**Comando:** `cd backend && python3 -m pytest tests/ -q`

| | antes | después |
|---|---|---|
| fallan | **27** | **0** |
| pasan | 3.986 | **4.017** |
| skipped / xfailed | 93 / 10 | 93 / 10 |
| tiempo | 61 s | 57 s |

Reproduje la línea de base en un worktree limpio desde `origin/main` antes de tocar nada: **27 failed,
3986 passed**, y la lista de los 27 salió idéntica, nombre por nombre, a `audit/_scripts/_tests_en_rojo.txt`.

---

## 🔴 Lo primero: hay un bug real del producto, y es de plata

**Un test de los 27 no estaba podrido. Estaba avisando de una regresión en producción desde
hace 40 días: después de revertir un import y volver a importar, el gráfico de evolución y el
`net_deposited` de esos meses quedan en CERO para siempre.**

`net_deposited` es la línea de "aportado" y el denominador del rendimiento. Un mes que queda en
cero no se corrige nunca más: ni re-importando, ni con otro revert.

### Cómo se llega

`_backfill_snapshots_from_monthly` proyecta un snapshot al último día de cada mes a partir de
`monthly_entries`. Escribía con `ON CONFLICT DO NOTHING`, o sea: si ya hay una fila para esa
fecha, no la toca.

1. `revert_batch` ([persister.py:1695-1707](../../backend/importing/persister.py#L1695)) purga los
   snapshots del rango, deja `monthly_entries` en cero y llama al backfill → **se escribe un fin de
   mes con `total_value = 0` y `net_deposited = 0`**, estampado `source='import'`.
2. El re-import vuelve a poner `monthly_entries` en 5.000 y llama al backfill otra vez
   ([persister.py:443](../../backend/importing/persister.py#L443)) — pero la fila ya existe, el
   `DO NOTHING` la protege, **y el cero queda clavado**.

Medido con una sonda sobre el mismo camino que corre el importador:

```
tras import #1 : 2024-01-31  tv=5000.0  nd=5000.0   monthly=5000.0
tras revert    : 2024-01-31  tv=   0.0  nd=   0.0   monthly=   0.0
tras re-import : 2024-01-31  tv=   0.0  nd=   0.0   monthly=5000.0   ← la contabilidad se arregló, el gráfico no
```

### Qué eslabón lo rompió (bisecado, no deducido)

El `DO NOTHING` lo puso `a813abc4` (2026-07-30, *"fix(fx-migrate): … deja de pisar los snapshots
reales"*), y para lo suyo **estaba bien**: el backfill venía pisando la medición a MERCADO del cron
nocturno con el capital AL COSTO de la cadena contable, en cada fin de mes, sin vuelta atrás.

Lo que no se vio es que un caller **dependía** de ese pisado para repararse. Corrí el test en los
dos commits:

```
53e61d02 (a813abc4^)  → 1 passed
a813abc4              → 1 failed
```

Es el patrón del CLAUDE.md dado vuelta: un fix que frena una sobreescritura, sin mirar quién
necesitaba esa sobreescritura para corregirse.

### El arreglo

El backfill puede reescribir **las filas que fabricó él mismo**, y ninguna otra. Quién es medición
y quién es fabricación **no se decide en el persister**: se le pregunta a `twr.clasificar_fila`
([twr.py:181](../../backend/twr.py#L181)), que es la regla canónica — y que `scripts/backfill_historical_mtm.py`
**ya venía usando por exactamente este motivo**, con el agujero descrito en su propio docstring:

> `usaba ON CONFLICT DO NOTHING (persister.py:1291) → no pisaba ni siquiera la fila sintética que el
> propio import había dejado antes, así que reconstruir no cambiaba nada de lo que el gráfico ya mostraba.`

O sea: el diagnóstico ya estaba escrito en el repo, en el módulo de al lado, y el persister seguía
sin enterarse. Ahora los dos preguntan lo mismo (regla de propagación: no dos implementaciones, una).

Conservador a propósito: **una fila sin `source` no se toca** (las columnas `source`/`holdings_json`
son de 2026; lo anterior no se puede afirmar quién lo escribió). Sólo se corrigen las estampadas
`source='import'` → `SINTETICO_COSTO`. Las mediciones del cron siguen intocables, que es lo que
`a813abc4` fue a proteger.

### El guard que no guardaba

`test_fx_migrate_gate.py::SnapshotsNoSePisanTest::test_el_upsert_es_do_nothing` vigilaba esto así:

```python
src = inspect.getsource(ps._backfill_snapshots_from_monthly)
self.assertIn("DO NOTHING", src)
self.assertNotIn("total_value = excluded.total_value", src)
```

Un guard de **texto**. Se conforma con la ortografía: mi cambio pasó su verificación en verde sin
que el guard se enterara de nada, porque dejé el `DO NOTHING` en el INSERT y agregué un UPDATE
aparte. Lo reemplacé por tres tests que ejercen las tres filas contra una base de verdad
(medición del cron → intocable; fila del import desactualizada → se corrige; fila legacy sin firma →
no se toca).

---

## 🔴 Segundo bug real, este salió del barrido de propagación

**Quien se suscribe hoy no recibe el mail de bienvenida.** El `send_welcome_pro` tiene UN caller en
producción, y cuelga del webhook de Mercado Pago:

```
send_welcome_pro          ← main.py:27959
  _maybe_send_welcome_email  ← main.py:27944  (único caller: main.py:27937)
    _process_preapproval_event ← main.py:27882  = webhook de MERCADO PAGO
```

El alta de hoy entra por Rebill: `/api/billing/rebill-webhook` → `_rebill_activate`
([main.py:27259](../../backend/main.py#L27259)), que activa el tier y otorga el crédito y **nunca
llama al welcome**. Verificado con `grep` de los dos nombres sobre todo el backend: cero callers
desde el camino Rebill.

Por qué nadie lo vio: los únicos tests del mail (`tests/test_billing_emails.py`) mockean
`billing.mercadopago.get_preapproval` y están **en verde** — prueban el camino muerto.

**NO lo arreglé.** Mandar (o no) un mail a cada nuevo suscriptor es una decisión de producto y toca
un flujo de plata; no entra en "poner la suite en verde". Queda señalado con el call graph exacto.

---

## Los 27, uno por uno

Grupos: **PODRIDO** = el test caducó o congeló un contrato viejo · **BUG** = el código está mal ·
**NO-HERMÉTICO** = depende de algo externo.

| # | archivo · test | motivo real | grupo |
|---|---|---|---|
| 1 | `test_importer` · `test_reimport_after_revert_does_not_duplicate` | `net_deposited` queda en 0 tras revert+re-import (arriba) | **BUG** |
| 2-10 | `test_events` · 9 tests | siembran fechas fijas may-jul 2026 y consultan "los próximos N días" | PODRIDO (calendario) |
| 11-13 | `test_bond_conduit` · 3 tests | esperan 720 = 1000 × 0,72; el AL30 pagó otra cuota y hoy R = 0,64 | PODRIDO (calendario) |
| 14 | `test_backfill_recompute` · `test_clean_amortization_is_safe` | mismo factor 0,72 congelado → 1000→720 dejó de ser "amortización limpia" | PODRIDO (calendario) |
| 15-17 | `test_news` · `MarketRelevanceFilterTest` × 3 | el filtro se endureció el 2026-05-26 y los fixtures son del 2026-05-12 | PODRIDO + **BUG chico** |
| 18-19 | `test_news` · `MarketNewsEndpointTest` × 2 | mismo filtro, re-aplicado al LEER (`main.py:25896`) → la lista vuelve vacía | PODRIDO + **BUG chico** |
| 20 | `test_news` · `test_macro_category_also_filters` | idem, en el camino de ingesta | PODRIDO + **BUG chico** |
| 21 | `test_news` · `test_respects_max_workers_cap` | **`max_workers` se aceptaba y se ignoraba**: el test tenía razón | **BUG (código muerto)** |
| 22-24 | `test_billing` · 3 tests | mockean `billing.mercadopago`; producción llama a `billing.rebill` → 502 | PODRIDO (migración) |
| 25 | `test_billing_lifecycle` · `test_runs_all_three_steps…` | fixture con schema escrito a mano, atrasado 4 columnas | PODRIDO (fixture) |
| 26 | `test_importer` · `test_new_aliases_…_whtax_…` | `WHTAX` pasó de `FEE` a `IMPUESTO` a propósito | PODRIDO (contrato) |
| 27 | `test_cedear_usd_price` · `test_snapshot_converts_bac` | **el test salía a internet** y comparaba contra el precio del día | NO-HERMÉTICO |

### Causa raíz por grupo

**A. El calendario (13 tests).** Dos sabores distintos, y el arreglo NO es el mismo:

- *Ventana de eventos* (9): el endpoint filtra `event_date >= hoy AND event_date <= hoy + days`
  ([main.py:6201](../../backend/main.py#L6201)). El comentario del test lo decía solo:
  `# 30 días: sólo el cercano (de 2026-06-01, asumiendo today ~2026-05-12)`
  ([test_events.py:136](../../backend/tests/test_events.py)). **Elegí semillas relativas**, no
  congelar el reloj: lo que estos tests verifican es la ventana, no una fecha del almanaque, y una
  semilla "dentro de 15 días" prueba lo mismo sin caducar ni sumar una dependencia nueva
  (no hay `freezegun` en el repo y nada parchea `date.today`).
- *Amortización de bonos* (4): acá **no** sirven semillas relativas — el factor residual sale de
  cuotas reales (`pricing/bond_amortization.py`: 4 % el 9-jul-2024 + 12 × 8 %). Lo que hay que fijar
  es la **fecha de valuación**, tal como planteabas. Y el seam ya existía:
  `sweep_bond_amortizations(conn, uid, ref_date=…)` — `tests/test_bond_amortization.py` **ya lo
  usaba** (`ref_date="2026-06-25"`) y por eso nunca se puso en rojo. Faltaba pasarlo por
  `recompute_user`, que es el camino que corre producción.

**B. Contrato viejo congelado (12 tests).** Tres migraciones que no arrastraron sus tests:
el filtro de noticias (`efecab9f`, 2026-05-26), el procesador de pagos (MP → Rebill), y la
separación impuesto/comisión (`WHTAX` → `OP_TAX`, con `importing/schema.py:143` diciendo
explícitamente *"NO son comisiones; van a métrica aparte"*). En los tres casos **el código está más
correcto que el test**.

**C. Fixture divergente (1).** `test_billing_lifecycle._make_db()` declaraba las tablas a mano.
Le faltaban `trial_ends_at`, `trial_started_at`, `quota_window_from` y `managed_by` — cuatro columnas
de tres features distintas. Y no explotaba: el job atrapa sus errores y los **cuenta**, así que el
`no such column` salía por el log y el test moría comparando `errors == 0` contra un 2 que no tenía
nada que ver con el cron. Estaba probando el fixture, no el job.

**D. Red (1).** `fetch_prices_for_symbols` mockeaba yfinance… y después data912/BYMA **pisa** todo lo
`.BA` ([snapshots_job.py:617-644](../../backend/snapshots_job.py#L617)). Medido:

```
_resolve_ar_equity_price('AAPL.BA')   con red → 25160.0 (2,6 s)      ← exactamente lo que recibía el test
                                      sin red → None    (0,0 s)
```

El escritor POSTERIOR se comía el fixture — el mismo patrón que el bug #1.

---

## Qué toqué

**Producción (3 archivos):**

| archivo | cambio | por qué |
|---|---|---|
| `importing/persister.py` | el backfill corrige sus propias filas vía `twr.clasificar_fila` | bug real #1 |
| `importing/recompute_backfill.py` | `ref_date` opcional en `recompute_user` y `_classify_safe` (default = hoy) | seam de fecha; producción no cambia |
| `main.py` | `_STRONG_MACRO_REGEX` (word boundary) + se saca el `max_workers` muerto | ver abajo |

Sobre el filtro de noticias: **no aflojé el criterio del 2026-05-26**. Medí los 9 titulares que el
test exige y **8 ya pasaban**. Los que caían eran dos formas cortas del titular más importante para
un inversor argentino:

```
CAE   Inflación de mayo: el IPC fue de 4.2%
CAE   FED holds rates steady
PASA  El Merval subió 4% en la jornada / El dólar blue cerró a $1.500 / BCRA bajó la tasa…
```

La lista ya tenía `'inflación argentina'`, `'ipc indec'`, `'fed minutes'`, `'fed pivot'`: la
intención de cubrir esos temas estaba escrita, faltaban las formas cortas. Van por regex con word
boundary y no por substring porque `'fed'` como substring se lleva puestas *Fedex* y
*confederación*. Un `stocks rally` pelado **sigue afuera**, que es lo que se decidió en mayo — y ahora
hay un test que lo fija en las tres capitalizaciones.

Sobre `max_workers`: el parámetro quedó de cuando la función creaba su propio executor; desde que usa
el pool global se aceptaba y se ignoraba. **Ningún caller de producción lo pasaba** (verificado en los
8 call sites), así que lo saqué en vez de implementarlo. El test de wall time (`elapsed > 0.25`) lo
reemplacé por uno que cuenta ejecuciones simultáneas contra el tope real del pool: un umbral de
tiempo convierte una máquina cargada en un rojo falso, y así fue como este test se ganó su lugar en
la lista de perdón.

**Tests (9 archivos):** `test_events` (semillas relativas), `test_bond_conduit` + `test_backfill_recompute`
(`REF_DATE` fijada), `test_news` (fixtures al contrato de hoy + test de concurrencia reescrito),
`test_billing` (reescrito contra Rebill), `test_billing_lifecycle` (schema copiado del real),
`test_importer` (`WHTAX → OP_TAX`), `test_cedear_usd_price` (mockea los escritores posteriores),
`test_fx_migrate_gate` (guard de texto → guard de comportamiento).

**No actualicé ningún número esperado.** El `720.0` sigue diciendo 720; lo que cambió es que ahora
hay una fecha de valuación al lado que lo hace verificable.

### Efecto lateral: tests verdes que no probaban nada

Los que asertaban lista **vacía** pasaban por el motivo equivocado — el filtro de fecha ya se comía
todo. Con las semillas relativas vuelven a ejercer su lógica (y siguen en verde, o sea que el código
estaba bien): `test_excludes_ar_bonds`, `test_cross_user_isolation`, `test_events_sorted_by_date`.
Un test podrido molesta; uno vacuo miente.

---

## Lo que dejé sin arreglar (y por qué)

1. **El mail de bienvenida por Rebill** — decisión de producto sobre un flujo de plata (arriba).
2. **`subscribe` ya no reusa la pending.** Con MP, un segundo POST devolvía el mismo `init_point` con
   `reused: True`. El endpoint de Rebill no tiene esa rama: cada llamada crea otro payment link. Y la
   `x-idempotency-key` no compensa, porque lleva un `uuid4()` adentro
   ([rebill.py:165](../../backend/billing/rebill.py#L165)) → nunca hay dos llamadas con la misma
   clave. Lo único que frena la acumulación es el rate limit de 5/600 s. Cambiarlo es tocar el flujo
   de cobro: dejé un test que **fija el comportamiento de hoy** y falla si alguien lo cambia sin querer.
3. **`tests/test_billing_emails.py` prueba el camino de MP.** Está en verde y no es vacuo (el mock se
   usa de verdad), pero cubre código que ya no corre para altas nuevas. Es el mismo síntoma que el
   punto 1.
4. **Los otros 11 guards de texto** (`inspect.getsource`) siguen ahí:
   `test_advisor_composition`, `test_audit_ronda4`, `test_audit_ronda5`, `test_billing_trial`,
   `test_clamp_pico`, `test_conducto_no_bonos`, `test_endpoints_no_bloquean`, `test_fx_for_date`,
   `test_reconstruccion_e2e`, `test_seed_fx_hoy`, `test_tickers_cd`. Convertí el que estorbaba;
   los demás no están en rojo y revisarlos uno por uno es otro trabajo.

---

## Barrido de propagación — dónde MÁS vive cada patrón

Lo pedías explícitamente, así que lo verifiqué en vez de suponerlo:

- **Semillas fijas contra ventana de hoy:** sólo `test_events.py`. Barrí los 15 archivos con fechas
  futuras hardcodeadas; el resto **ya fija la fecha** (`NOW` en `test_goals_diagnostic`, `ref_date` en
  `test_bond_amortization`/`test_letra_maturity`, año explícito en `test_wrapped`) o usa centinelas
  lejanos (2029, 2030, 2099). El único sospechoso con `?days=` (`test_audit_ronda11`) lo **medí**: esa
  ventana está anclada a los datos, no a hoy — devuelve 30 filas e intersección 30. No caduca.
- **`recompute_user` sin fecha fijada:** quedan 3 llamadas en `test_backfill_recompute`, y están bien:
  `test_reduces_amortizing_bond` asserta un **rango** (`< 1000` y `> 0`), que es la otra forma correcta
  de no depender del calendario.
- **Mocks del proveedor viejo:** eran 4 archivos. Arreglé 2 (`test_billing`, `test_billing_lifecycle`);
  `test_billing_emails` queda (punto 3 de arriba) y `test_dependencias_declaradas` sólo lo nombra en un
  comentario.
- **Tests que salen a la red:** los 5 archivos que llaman a `fetch_prices_for_symbols` los corrí con un
  proxy muerto (control verificado: el resolver devuelve `None` en 0,0 s en vez de 25160,0 en 2,6 s).
  **84 passed** — después del arreglo ninguno *necesita* la red. Sí sigue costando: cada llamada que
  igual sale y falla son ~2,6 s.

---

## Una corrección al planteo

`tests/fallas_conocidas.txt` **ya existía** (generado el 2026-08-28) con estos mismos 27 nombres, y
`tests/conftest.py` tiene un hook (`pytest_sessionfinish`) que grita
`🔴 N FALLA(S) NUEVA(S) — no están en fallas_conocidas.txt` cuando aparece un rojo que no está en la
lista. O sea: la suite no estaba del todo desdentada — una regresión nueva sí se habría señalado.

Lo que sí era cierto es lo otro: con 27 nombres en la lista de perdón, el mecanismo dependía de que
alguien la drenara, y nadie lo hizo en 11 días. Y el rojo #1 —una regresión real, de plata, de hacía
40 días— entró en esa lista el 2026-08-28 **como línea de base**, sin que nadie mirara qué decía.

Dejé el archivo **vacío**, con la nota de que una entrada nueva va con motivo y fecha. El hook
también avisa al revés (`✅ N falla(s) conocida(s) ya no fallan`), y en la corrida final marcó 24 de
las 27 (las otras 3 cambiaron de nombre).

---

## Verificación final

```
$ cd backend && python3 -m pytest tests/ -q
4017 passed, 93 skipped, 10 xfailed, 21 warnings in 56.51s
```

Cero rojos, cero entradas en la lista de perdón, y ninguna falla nueva reportada por el hook. La
cuenta cierra: 3.986 + 27 arreglados + 4 tests nuevos = 4.017.
