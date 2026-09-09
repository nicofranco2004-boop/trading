# Autorización entre usuarios — tramo 2 de 6 (`main.py` 9103–15039, 44 endpoints)

Auditoría sobre `/tmp/rendi-main` (copia congelada del commit `b74f450f`, prod al 2026-09-05).
Alcance: los 44 endpoints entre `/api/plazos-fijos` (9103) y `/api/assets/history` (15019).

## Método

**Lo que EJECUTÉ** (sonda en proceso, nunca contra producción):
`audit/_scripts/5a_autorizacion_2_probe.py` levanta la copia congelada con `DB_PATH`
apuntando a una SQLite temporal e instancia `TestClient(main.app)`. Crea tres usuarios
(víctima, atacante, asesor) y datos reales de la víctima (plazo fijo, monthly_entry,
operation, futuro, broker). Cinco bloques:

- **A · IDOR** — el atacante dispara 12 escrituras contra los ids de la víctima
  (`PUT/DELETE /api/plazos-fijos/{pid}`, `renovar`, `cobrar`, `PUT/DELETE /api/monthly/{eid}`,
  `PUT/DELETE /api/operations/{oid}`, `PUT/DELETE /api/futures/{fid}`, `close`,
  `usd-sibling`) y después se relee la base de la víctima fila por fila. Además, 6 GET de
  listado con el token del atacante.
- **B · escrituras por GET** — asesor con `permission='read'` y header `X-Rendi-Client-Id`
  del cliente: control con `POST /api/monthly` (debe dar 403) y luego `GET /api/monthly`,
  contando filas de `monthly_entries` del cliente antes y después.
- **C · contexto de cliente** — header sin vínculo, con vínculo revocado, y 8 formas
  raras del valor (` 1 `, `+1`, `01`, `abc`, `-1`, `0`, `2^63`, `1e3`).
- **D · exports del cliente** por el asesor de solo lectura.
- **E · validación del broker** en `POST /api/operations` / `POST /api/futures`, con
  `POST /api/monthly` como control (ése sí valida).
- **F · 500 con texto crudo** de la excepción: intenté forzar 4 excepciones y **no lo
  logré**, así que ese hallazgo queda ESTRUCTURAL, no medido.

Salida completa en `audit/_scripts/5a_autorizacion_2_probe.out`.

**Lo que NO ejecuté:** nada contra la app desplegada; ningún test con Postgres (`USANDO_PG`);
ninguna prueba de concurrencia. No revisé los cálculos (tanda 1A/1B).

**Barrido estructural:** script Python sobre las líneas 9103–15039 que extrae toda línea con
`WHERE` y marca las que no tienen `user_id` en una ventana de ±4 líneas (19 hits, todos
verificados a mano: en los 19 el id ya venía de una query filtrada por `user_id`), y un
segundo script que resuelve la dependencia de auth de cada uno de los 44 endpoints.

**Deriva:** los dos hallazgos principales siguen vivos en `origin/main` (`897b0d63`):
`_rollover_all_brokers(conn, uid)` sigue en la línea 11970 y `create_operation` en la 13823.

---

## Resumen — hallazgos por severidad

| id | severidad | título | archivo:línea | evidencia |
|---|---|---|---|---|
| H-1 | **ALTO** | `GET /api/monthly` ESCRIBE: el asesor de solo lectura crea filas en la cuenta del cliente | `backend/main.py:11960-11970` | MEDIDO (1→9 filas) |
| H-2 | MEDIO | `POST/PUT /api/operations` y `POST/PUT /api/futures` no validan que el broker sea del usuario: crean efectivo bajo un broker inexistente | `backend/main.py:13865`, `13923-13926`, `12241` | MEDIDO ($5.000 fantasma) |
| H-3 | MEDIO | Dos DELETE sin chequeo de pertenencia ni de `rowcount`: devuelven `ok:true` sobre recursos ajenos | `backend/main.py:9190`, `12038` | MEDIDO (200 sin borrar nada) |
| H-4 | BAJO | 7 endpoints devuelven el texto crudo de la excepción interna en el cuerpo del 500 | `backend/main.py:10121, 10213, 10532, 10746, 11002, 11091, 11409` | ESTRUCTURAL |
| H-5 | BAJO | Ningún endpoint del tramo está en `CLIENT_CTX_EXEMPT_PREFIXES` — correcto hoy, pero el diseño es fail-open y ya hay 4 rutas del tramo que exportan la cartera completa | `backend/main.py:2749-2765` | ESTRUCTURAL |

**No encontré ni un solo IDOR clásico en el tramo.** Es el resultado más importante y está
medido: las 12 sondas de escritura contra los ids de la víctima terminaron en 404 o en un
no-op, y las 4 tablas de la víctima quedaron byte a byte iguales.

---

## Tabla — los 44 endpoints

`gef` = `Depends(get_effective_user)`. Los 44 usan `gef`: **no hay ni un endpoint público
en el tramo** (verificado con script, no a ojo).

| # | línea | método | ruta | qué hace | valida sesión | valida propiedad | veredicto |
|---|---|---|---|---|---|---|---|
| 1 | 9103 | GET | `/api/plazos-fijos` | lista PF abiertos | gef | n/a — no recibe id; `WHERE user_id=?` | OK |
| 2 | 9119 | POST | `/api/plazos-fijos` | alta de PF; debita cash del broker origen | gef | sí — `brokers WHERE user_id=? AND name=?`, 400 si no | OK |
| 3 | 9164 | PUT | `/api/plazos-fijos/{pid}` | edita el PF | gef | sí — SELECT con `AND user_id=?` → 404, y el UPDATE lo repite | OK |
| 4 | 9190 | DELETE | `/api/plazos-fijos/{pid}` | borra el PF | gef | parcial — sólo el `AND user_id=?` del DELETE; sin pre-check ni `rowcount` | **MEDIO: H-3** |
| 5 | 9242 | POST | `/api/plazos-fijos/{pid}/renovar` | reinicia el período reinvirtiendo el interés | gef | sí — SELECT `AND user_id=? AND closed_at IS NULL` → 404 | OK |
| 6 | 9275 | POST | `/api/plazos-fijos/{pid}/cobrar` | cierra el PF, acredita cash y registra el interés | gef | sí — SELECT con `user_id`; el broker destino también se valida | OK |
| 7 | 9341 | GET | `/api/pf/banks` | proxy cacheado 6 h a argentinadatos (tasas por banco) | gef | n/a — no toca datos del usuario; el `uid` ni se usa. URL fija, no hay SSRF | OK |
| 8 | 10028 | POST | `/api/brokers/reconcile-cash` | fija el cash del broker al valor real y anota la diferencia | gef | sí — `brokers WHERE user_id=? AND name=?` → 404; todas las escrituras llevan `user_id` | OK ⚠️ posible cruce con F1 |
| 9 | 10126 | POST | `/api/cash/flow` | depósito/retiro de cash del broker | gef | sí — mismo patrón; `UPDATE positions ... WHERE id=? AND user_id=?` | OK ⚠️ posible cruce con F1 (`CashFlowIn`) |
| 10 | 10346 | POST | `/api/bonds/cashflow` | registra cupón/amortización, acredita cash, amortiza FIFO | gef | sí — broker validado; `_amortize_position_fifo` y `_bond_total_qty` filtran por `user_id` | OK |
| 11 | 10696 | GET | `/api/bonds/cashflow/skips` | lista los pagos marcados como saltados | gef | n/a — `WHERE user_id=?` | OK |
| 12 | 10714 | POST | `/api/bonds/cashflow/skip` | marca un pago teórico como saltado (idempotente) | gef | sí — broker validado; `ON CONFLICT(user_id, broker, asset, date)` | OK |
| 13 | 10751 | DELETE | `/api/bonds/cashflow/skip` | saca el skip (broker/asset/date por query) | gef | sí — el DELETE filtra por `user_id` además de los 3 campos del usuario | OK |
| 14 | 10870 | POST | `/api/conversions` | convierte ARS↔USD dentro del broker, con P&L cambiario | gef | sí — broker por `user_id`+nombre; el padre por `id=? AND user_id=?` | OK |
| 15 | 11007 | POST | `/api/brokers/{bid}/usd-sibling` | crea el sub-broker USD del broker ARS | gef | sí — `brokers WHERE id=? AND user_id=?` → 404 (medido) | OK |
| 16 | 11038 | POST | `/api/monthly/sync-unrealized` | escribe `pnl_unrealized` del mes en curso y cerea el resto | gef | el broker del body NO se valida, pero las 3 escrituras filtran por `user_id` → sólo toca lo propio | OK |
| 17 | 11147 | POST | `/api/positions/sell` | venta FIFO sobre el par de brokers | gef | sí — broker, lotes, operations y positions, todo con `user_id` | OK |
| 18 | 11561 | GET | `/api/insights/gap-month` | descompone la "diferencia sin explicar" del mes | gef | n/a — `mes` validado por regex; las 3 queries filtran por `user_id`. No escribe | OK |
| 19 | 11788 | GET | `/api/insights/performance` | curva del usuario + benchmark recortado | gef | n/a — delega en `performance.performance(conn, uid, …)`; `performance.py` no tiene ni un `execute` | OK |
| 20 | 11838 | GET | `/api/insights/mtm-audit` | reconcilia cadena a costo vs cadena a mercado | gef | n/a — `WHERE user_id=?`; read-only declarado y verificado | OK |
| 21 | 11960 | GET | `/api/monthly` | lista las filas mensuales **y corre el rollover (escribe)** | gef | n/a para lectura — pero el `read_write` del contexto de asesor no se aplica a GET | **ALTO: H-1** |
| 22 | 11979 | POST | `/api/monthly` | crea la fila mensual | gef | sí — **valida que el broker exista** (`SELECT 1 FROM brokers WHERE user_id=? AND name=?`) → es el control de H-2 | OK |
| 23 | 12011 | PUT | `/api/monthly/{eid}` | edita la fila mensual | gef | sí — UPDATE `WHERE id=? AND user_id=?` y el SELECT posterior repite el filtro → 404 (medido) | OK |
| 24 | 12038 | DELETE | `/api/monthly/{eid}` | borra la fila mensual + repara la cadena | gef | parcial — sólo el `AND user_id=?`; devuelve `ok:true` sin mirar `rowcount` | **MEDIO: H-3** |
| 25 | 12227 | GET | `/api/futures` | lista futuros (abiertos por defecto) | gef | n/a — `WHERE user_id=?` | OK |
| 26 | 12241 | POST | `/api/futures` | alta de posición de futuros | gef | el broker del body NO se valida (medido: 200 con broker inexistente) | **MEDIO: H-2** |
| 27 | 12263 | PUT | `/api/futures/{fid}` | edita la posición abierta | gef | sí sobre el `fid` (`WHERE id=? AND user_id=? AND closed_at IS NULL` → 404); el broker nuevo no se valida | **MEDIO: H-2** |
| 28 | 12288 | DELETE | `/api/futures/{fid}` | borra la posición abierta | gef | sí — SELECT con `user_id` → 404 antes de borrar | OK |
| 29 | 12311 | POST | `/api/futures/{fid}/close` | cierra, acredita el resultado y crea la operación | gef | sí — SELECT con `user_id` + claim atómico `UPDATE … WHERE id=? AND user_id=? AND closed_at IS NULL` | OK |
| 30 | 12380 | GET | `/api/operations` | lista operaciones | gef | n/a — `WHERE user_id=?` | OK |
| 31 | 12389 | GET | `/api/movements` | historial unificado (4 fuentes) | gef | n/a — las 4 fuentes filtran: `operations`/`positions`/`monthly_entries` por `user_id`, `import_normalized_tx` por `JOIN import_batches b … b.user_id=?`. No escribe | OK |
| 32 | 13130 | DELETE | `/api/movements/{movement_id}` | borra un movimiento con cascada (id compuesto `tx-`/`me-`/`op-`/`pos-`) | gef | sí en las 4 ramas — `_delete_one_movement`, `_route_tx_delete`, `_delete_operation_cascade` y `_delete_position_cascade` abren todas con un SELECT filtrado por `user_id` (o por el JOIN al batch) y tiran 404 | OK |
| 33 | 13177 | GET | `/api/insights/commissions` | total de comisiones sobre las filas de `_build_movements` | gef | n/a — hereda el filtrado de `_build_movements` | OK |
| 34 | 13333 | GET | `/api/export/operations.csv` | CSV de operaciones cerradas | gef | n/a — `WHERE user_id = ?`; `_gate_export` es gate de PLAN, no de propiedad | OK (ver H-5) |
| 35 | 13384 | GET | `/api/export/positions.csv` | CSV de posiciones abiertas | gef | n/a — `WHERE user_id = ?` | OK (ver H-5) |
| 36 | 13419 | GET | `/api/export/transactions.csv` | CSV consolidado de TODO el historial | gef | n/a — las 4 fuentes filtran por `user_id` / `b.user_id` | OK (ver H-5) |
| 37 | 13644 | GET | `/api/export/monthly.csv` | CSV del resumen mensual | gef | n/a — `WHERE user_id = ?` | OK (ver H-5) |
| 38 | 13682 | GET | `/api/wrapped/{year}` | resumen anual tipo Wrapped | gef | n/a — `year` acotado 2000–2200; las 3 queries filtran por `user_id`; `analysis_prep` no escribe | OK |
| 39 | 13760 | GET | `/api/behavioral/insights` | 10 detectores de sesgos | gef | n/a — `WHERE user_id=?` en ops y positions | OK |
| 40 | 13821 | POST | `/api/operations` | crea una operación manual; si `kind=futures`, mueve efectivo | gef | el broker del body NO se valida (medido: crea cash de US$5.000 bajo un broker inexistente) | **MEDIO: H-2** |
| 41 | 13890 | PUT | `/api/operations/{oid}` | edita la operación; si es de futuros, mueve el efectivo por la diferencia | gef | sí sobre el `oid` (SELECT + UPDATE con `user_id`, 404 medido); el broker destino no se valida | **MEDIO: H-2** |
| 42 | 14721 | DELETE | `/api/operations/{oid}` | borra con cascada total y deja token de deshacer | gef | sí — `_delete_operation_cascade` abre con `SELECT * FROM operations WHERE id=? AND user_id=?` → 404 (medido) | OK |
| 43 | 14743 | POST | `/api/operations/undo/{token}` | deshace el borrado | gef | sí — `deleted_ops_journal WHERE user_id=? AND token=? AND undone_at IS NULL`; el token es de 64 bits y además está scopeado al usuario | OK |
| 44 | 15019 | DELETE | `/api/assets/history` | borra todo el historial importado de un activo | gef | n/a de id — el `asset` es un string; `_delete_asset_history_cascade` filtra `b.user_id=?` y `o.user_id=?` en todas las lecturas | OK |

---

## Hallazgos

### [ALTO] H-1 · `GET /api/monthly` escribe en la base: el asesor de SOLO LECTURA crea filas en la cuenta del cliente

**Evidencia:** MEDIDO
**Dónde:** `backend/main.py:11960-11976` (el endpoint), `11523-11556` (`_rollover_all_brokers`),
`11433` (`_rollover_to_current_month`), y la regla que se saltea en `main.py:2789-2790`.

**Qué pasa.** `get_effective_user` exige `permission='read_write'` **sólo** cuando el método
no es GET/HEAD/OPTIONS:

```python
if request.method not in ("GET", "HEAD", "OPTIONS") and row["permission"] != "read_write":
    raise HTTPException(403, "Acceso de solo lectura a ese cliente")
```

Ese diseño asume que un GET no escribe. `GET /api/monthly` sí escribe: antes de devolver
corre `_rollover_all_brokers` dentro de un `with conn:`, que **INSERTA** una fila de
`monthly_entries` por cada mes faltante y por cada broker, y después corre
`_repair_monthly_chain`, que hace `UPDATE monthly_entries SET capital_inicio=…,
capital_final=…, pnl_unrealized=0`. El propio docstring lo dice ("Lazy trigger del
rollover"); lo que nadie miró es que el gate de escritura del Plan Asesor no lo cubre.

**Cómo se explota en la práctica.** Un asesor con vínculo `permission='read'` sobre un
cliente manda `GET /api/monthly` con `X-Rendi-Client-Id: <cliente>`. Traza real de la sonda
(bloque B):

```
POST /api/monthly (control, debe dar 403) -> 403 {"detail":"Acceso de solo lectura a ese cliente"}
GET  /api/monthly  -> 200
monthly_entries del CLIENTE: antes=1  despues=9  (ESCRIBIO)
filas del cliente ahora: [{'year': 2026, 'month': 1, …, 'capital_final': 500.0},
                          {'year': 2026, 'month': 2, 'capital_inicio': 500.0, …}, … hasta 2026-09]
```

El POST de control es rechazado con el mensaje correcto. El GET, un renglón después, escribe
ocho filas nuevas en la cuenta del cliente. No hace falta ningún truco: es abrir la pantalla
Mensual del cliente.

**Qué queda expuesto.** No es una fuga de datos: es una **escritura no autorizada**. El
permiso de solo lectura del Plan Asesor deja de significar lo que dice. `monthly_entries` es
la cadena contable de la que salen capital aportado, P&L mensual, la Evolución y —vía
`_backfill_snapshots_from_monthly`— los snapshots que alimentan el TWR y el AUM del libro.
Un `_repair_monthly_chain` disparado desde afuera reescribe `capital_inicio`/`capital_final`
de meses cerrados del cliente. Y el registro de quién lo hizo no existe: la fila se escribe
con el `uid` del cliente, no con el del asesor.

**Otros call sites del mismo patrón.** `_rollover_all_brokers` tiene **un solo** call site en
todo el repo (`grep -n "_rollover_all_brokers\|_rollover_to_current_month" main.py *.py` →
sólo la definición y `main.py:11970`), así que este endpoint es el único de MI tramo que
escribe desde un GET. Lo verifiqué endpoint por endpoint: los otros 17 GET del tramo no
escriben — `performance.py` y `analysis_prep.py` no tienen ni un `execute`, `_build_movements`
(12430–12800) no tiene ningún INSERT/UPDATE/DELETE, y `twr.py` sólo escribe en `sellar()` y
en el backfill de `base/apto`, ninguno de los dos alcanzable desde `curva_indexada`.
**No barrí los otros 5 tramos**: la pregunta "¿qué otros GET escriben?" es de toda la app y
hay que hacerla completa (ver "Lo que NO pude verificar").

**Solución de fondo.** El problema no es el rollover: es que el gate de escritura del contexto
de cliente se apoya en el **verbo HTTP** como proxy de "esto escribe". Dos capas:

1. Mover el rollover fuera del GET (a un job, o al login del cliente, o a un
   `POST /api/monthly/rollover` explícito). Es lo que ya anota el docstring de
   `sync_unrealized`: "Phase 8 moverá ese rollover al backend".
2. Y —lo que de verdad cierra la clase entera— que la marca de "escribe" sea del endpoint,
   no del método: una lista explícita de rutas mutantes (o un `Depends(require_write_ctx)`
   en las que escriben), de modo que un GET que escriba tenga que declararlo. Mientras el
   criterio sea `request.method`, el próximo GET que escriba vuelve a saltearse el permiso
   sin que nadie se entere.

---

### [MEDIO] H-2 · Cuatro endpoints no validan que el broker sea del usuario: crean efectivo bajo un broker que no existe

**Evidencia:** MEDIDO
**Dónde:** `backend/main.py:13821-13867` (`POST /api/operations`), `13890-13927`
(`PUT /api/operations/{oid}`, rama futuros), `12241` (`POST /api/futures`), `12263`
(`PUT /api/futures/{fid}`). El helper que materializa el daño está en `9750-9791`
(`_adjust_broker_cash`).

**Qué pasa.** Casi todo el tramo valida el broker antes de tocarlo
(`POST /api/monthly:11984`, `POST /api/cash/flow:10132`, `POST /api/bonds/cashflow:10366`,
`POST /api/conversions:10898`, `POST /api/plazos-fijos:10052`, todos con
`SELECT … FROM brokers WHERE user_id=? AND name=?` y un 400/404 si no está). Estos cuatro no.
`create_operation` toma `op.broker` del body y lo mete directo en el INSERT, y si
`kind='futures'` llama a `_adjust_broker_cash(conn, uid, op.broker, …)`, que —cuando no
encuentra posición cash— **crea una**:

```python
conn.execute(
    """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
       VALUES (?,?,?,1,?)""",
    (uid, broker, asset_name, delta),
)
```

**Cómo se explota en la práctica.** Traza real (bloque E de la sonda), con un usuario que
tiene **cero** brokers:

```
POST /api/operations broker inexistente -> 200
POST /api/futures    broker inexistente -> 200
POST /api/monthly    broker inexistente -> 400 (control: SI valida)
brokers reales del atacante: []
positions creadas: [{'broker': 'BrokerQueNoExiste', 'asset': 'USDT', 'is_cash': 1, 'invested': 5000.0}]
monthly_entries creadas: [{'broker': 'BrokerQueNoExiste', 'pnl_realized': 5000.0},
                          {'broker': 'global', 'pnl_realized': 5000.0}]
```

**Qué queda expuesto.** No cruza la frontera entre usuarios: todo se escribe con el `uid` del
que llama. Lo que rompe es otra cosa, y el propio código ya la tiene diagnosticada en el guard
del undo (`main.py:14776-14781`): *"`_adjust_broker_cash` CREABA la posición cash → plata
inventada bajo un broker inexistente, invisible e imborrable desde la UI"*. Ese guard se puso
en el camino del undo y **no se propagó al camino del alta**, que es por donde entra. Dos
consecuencias concretas:

- **Datos huérfanos e imborrables**: `positions` y `monthly_entries` cuelgan de brokers
  linkeados **por nombre**, no por FK (ver `project_broker_data_model`). Una fila bajo un
  nombre que no está en `brokers` no aparece en ninguna pantalla de gestión y no hay forma de
  sacarla desde la app. Y sí entra en `capital_final`, en el aportado y en el AUM del libro
  del asesor.
- **Cupo de plan esquivado de facto**: `ai/plan.py:151` cuenta cuentas de broker con
  `SELECT COUNT(*) … FROM brokers`. Un usuario Free (`brokers_max=1`) puede llevar el
  seguimiento de N brokers en `positions`/`operations` sin crear ni una fila en `brokers`.
  No es un bypass total (falta el resto de la UI), pero el contador miente.

**Otros call sites del mismo patrón.** Busqué todos los `_adjust_broker_cash(conn, uid, …)` /
`_adjust_cash(conn, uid, …)` de `main.py` (27 sitios). Se dividen así:

- **Validan antes** (OK): 9144 (`POST /api/plazos-fijos`), 9306 (`cobrar`), 10231
  (`cash/flow`), 10502 (`bonds/cashflow`), 10910/10911/10946/10947 (`conversions`),
  11379 (`positions/sell` — el broker sale de lotes ya filtrados por `user_id`).
- **NO validan, en MI tramo**: 13865 (`POST /api/operations`), 13923-13926
  (`PUT /api/operations/{oid}`) — más `POST/PUT /api/futures`, que no mueven cash pero sí
  escriben el nombre libre.
- **NO valida, FUERA de mi tramo (tramo 1)**: `main.py:8257`, dentro de
  `_insert_manual_position` → `POST /api/positions` (`main.py:8282`). Ahí `p.broker` sólo se
  usa para *inferir la moneda* (`_br` puede ser `None` y cae a `"USD"`), nunca para rechazar.
  **No lo arreglo ni lo cierro: es de otro tramo, lo dejo listado.**
- **Caminos de reverso/undo** (14065, 14072, 14150, 14249, 14377, 14428, 14569, 14694, 14803,
  14953, 15095, 24687): el broker sale de una foto que escribió el propio sistema, y desde el
  fix de 14776 el undo ya exige que el broker exista.

**Solución de fondo.** No sumar un quinto `if` en cada endpoint: hoy la validación está
copiada a mano en seis lugares y falta en cinco — es exactamente la deuda que describe la
regla de propagación. Lo correcto es **subirla al helper**: que `_adjust_broker_cash` /
`_adjust_cash` exijan que `(user_id, broker)` exista en `brokers` y levanten 404 si no, y que
`_resolve_op_currency` deje de tener un fallback silencioso a `"USD"` para un broker que no
existe. Con eso los 27 call sites quedan cubiertos de una y el guard del undo (14776) se
vuelve redundante en vez de ser el único que mira.

---

### [MEDIO] H-3 · Dos DELETE sin chequeo de pertenencia: responden `ok:true` sobre recursos ajenos

**Evidencia:** MEDIDO
**Dónde:** `backend/main.py:9190-9200` (`DELETE /api/plazos-fijos/{pid}`) y
`backend/main.py:12038-12053` (`DELETE /api/monthly/{eid}`).

**Qué pasa.** Los dos borran con `WHERE id=? AND user_id=?` — hoy es correcto — pero **no
hacen un SELECT previo de pertenencia ni miran `rowcount`**, y devuelven `{"ok": True}` pase
lo que pase. Contrastan con sus vecinos inmediatos: `PUT /api/plazos-fijos/{pid}` (9169),
`DELETE /api/futures/{fid}` (12292) y `DELETE /api/operations/{oid}` (vía 14462) sí hacen el
SELECT y devuelven 404.

**Cómo se explota en la práctica.** Hoy **no se explota**, y eso está medido:

```
DELETE /api/plazos-fijos/{pid}  -> 200  {"ok":true}
DELETE /api/monthly/{eid}       -> 200  {"ok":true}
  Estado de la VICTIMA despues de las 12 sondas:
    plazos_fijos     [{'banco': 'BancoV', 'capital': 1000000.0, 'closed_at': None}]
    monthly_entries  [{'deposits': 500.0, 'capital_final': 500.0}]
```

El 200 es una mentira cortés, no un borrado. Lo reporto igual porque es **defensa en
profundidad ausente en el peor lugar posible**: toda la protección de estos dos endpoints es
un `AND user_id=?` dentro de un string SQL. Si un refactor lo pierde —y el repo tiene 28+
hallazgos de exactamente eso, un fix que no se propaga— el endpoint pasa a borrar plazos
fijos y filas contables de cualquier usuario **y sigue devolviendo `ok:true`**, así que ni el
frontend ni un test de humo se enteran. En los vecinos que sí hacen el SELECT, el mismo
refactor se cae con un 404 ruidoso.

**Qué queda expuesto.** Hoy nada. Mañana, con un solo renglón de menos: borrado cruzado
silencioso de `plazos_fijos` y `monthly_entries`.

**Otros call sites del mismo patrón.** Dentro del tramo son estos dos; los otros 6 DELETE
(`/api/bonds/cashflow/skip`, `/api/futures/{fid}`, `/api/movements/{id}`,
`/api/operations/{oid}`, `/api/assets/history`) sí validan antes. No barrí los DELETE de los
otros 5 tramos.

**Solución de fondo.** Un helper único —`_owned_or_404(conn, uid, tabla, id)`— usado por todo
DELETE/PUT con id de recurso, en vez de que cada endpoint decida si chequea. Y que el
resultado del borrado refleje `rowcount`, para que "no era tuyo" y "lo borré" dejen de ser la
misma respuesta.

---

### [BAJO] H-4 · Siete endpoints devuelven el texto crudo de la excepción interna

**Evidencia:** ESTRUCTURAL (intenté forzar 4 excepciones y **no lo conseguí**: los cuatro
casos devolvieron 200. No tengo una traza de fuga; tengo el código que la haría posible.)
**Dónde:** `backend/main.py:10121, 10213, 10532, 10746, 11002, 11091, 11409`.

**Qué pasa.** Los siete cierran con `except Exception as ex: raise HTTPException(500,
f"…: {ex}")`. El `str()` de una excepción de sqlite3/psycopg lleva nombres de tabla y de
columna (`UNIQUE constraint failed: monthly_entries.user_id, monthly_entries.year, …`) y, en
un `OperationalError`, fragmentos del SQL. Eso va al cuerpo de la respuesta HTTP del usuario.
Es reconocimiento de esquema gratis para quien esté buscando por dónde entrar; no filtra
datos de otro usuario por sí solo.

**Otros call sites del mismo patrón.** Los siete de mi tramo, más al menos
`POST /api/positions` (`main.py:8291`, tramo 1) con la misma forma. Un
`grep -n 'HTTPException(500, f"'` sobre el archivo entero da la lista completa para los
otros tramos; no la corrí fuera de mi rango.

**Solución de fondo.** Loguear `ex` con el `uid` y devolver un mensaje fijo, como ya hace
`delete_operation` (`main.py:14736-14738`: `log.error(...)` y después
`HTTPException(500, "No se pudo borrar la operación")`). El patrón correcto ya existe en el
mismo archivo; falta propagarlo.

---

### [BAJO] H-5 · El contexto de cliente es fail-open y ninguno de mis 44 endpoints está exento

**Evidencia:** ESTRUCTURAL + MEDIDO (el control de acceso en sí funciona; lo que anoto es el
diseño).
**Dónde:** `backend/main.py:2749-2765` (`CLIENT_CTX_EXEMPT_PREFIXES` y la nota
"⚠️ FAIL-OPEN").

**Qué pasa.** Ninguna de mis 44 rutas cae en un prefijo exento, y **está bien**: son todos
endpoints de datos, que es justo lo que el contexto de cliente tiene que seguir. Lo verifiqué
además por el lado del ataque, y el gate aguanta (bloque C):

```
atacante sin vinculo  GET /api/operations                 -> 403 {"detail":"Sin acceso a ese cliente"}
atacante sin vinculo  GET /api/export/transactions.csv    -> 403 {"detail":"Sin acceso a ese cliente"}
asesor REVOCADO       GET /api/operations                 -> 403 {"detail":"Sin acceso a ese cliente"}
header='abc' / '-1' / '0' / '9223372036854775808' / '1e3' -> 400 {"detail":"X-Rendi-Client-Id inválido"}
```

(` 1 `, `+1` y `01` sí resuelven al mismo id — `int()` los normaliza —, lo cual es inocuo:
igual hay que tener el vínculo activo. Y el 403 nunca degrada en silencio al uid propio,
que era el riesgo grande.)

Lo que anoto es la asimetría que queda: cuatro rutas de mi tramo
(`/api/export/{operations,positions,transactions,monthly}.csv`) **exportan la cartera entera
del cliente en un archivo**, y llegan por GET, o sea que un vínculo `permission='read'`
alcanza. Es coherente con "solo lectura", pero es la superficie más sensible del tramo y
`_gate_export` (13300-13312) tiene una excepción explícita para que el asesor no reciba el
403 de plan del cliente. En mi corrida los cuatro dieron 403 porque el usuario de prueba no
tenía tier `advisor`; el camino permisivo existe y no lo pude ejercitar.

**Solución de fondo.** Nada que arreglar hoy. Dos higienes: (a) que la lista de exentos deje
de ser fail-open —default denegar y una marca explícita `follows_client_ctx=True` por
endpoint—, y (b) que una descarga completa de la cartera del cliente quede registrada con el
uid del ASESOR (que `get_effective_user` ya guarda en `request.state.rendi_auth_uid`), no
sólo con el del cliente.

---

## Lo que NO pude verificar (dicho explícitamente)

1. **No pude forzar ningún 500** en los 7 endpoints de H-4: los 4 intentos devolvieron 200.
   El hallazgo es estructural, no medido. No sé qué texto real sale por ahí.
2. **Sólo probé SQLite.** Con `USANDO_PG` cambian el driver, el texto de las excepciones y el
   manejo de transacciones (`psycopg` abre transacción hasta para un SELECT, según el propio
   `conftest.py`). No sé si H-1 se comporta igual en Postgres.
3. **No probé concurrencia.** Varios endpoints del tramo dependen de un "claim atómico" por
   `rowcount` (`futures/{fid}/close:12354`, el tombstone de `tx-`:12991, los dos undo). Los leí
   y el patrón es correcto, pero no corrí dos requests en paralelo contra ninguno.
4. **La pregunta "¿qué otros GET escriben?" queda abierta para los otros 5 tramos.** Yo cubrí
   los 18 GET de 9103–15039 y encontré uno. `_rollover_all_brokers` tiene un solo call site,
   pero hay otros escritores (`_repair_monthly_chain`, `_recalc_pnl_realized_from_ops`,
   `_backfill_snapshots_from_monthly`, `twr.sellar`) que podrían estar colgando de un GET en
   otro rango. **Es la verificación que más recomiendo hacer a nivel global**, porque el gate
   de escritura del Plan Asesor depende entera y exclusivamente de que ningún GET escriba.
5. **No verifiqué el frontend.** Si `GET /api/monthly` se llama al abrir la ficha de un
   cliente, H-1 se dispara solo, sin intención del asesor. No lo comprobé.
6. **No auditué los cálculos** (tanda 1A/1B). Al pasar vi que `POST /api/bonds/cashflow`
   aceptó `date="2020-13-45"` con 200 —`_DATE_RE` valida la FORMA, no que la fecha exista, y
   la guarda de fecha futura es una comparación de strings—, pero eso es de otra tanda y no
   tiene consecuencia de autorización.
