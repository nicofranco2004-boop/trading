# 1B — Decimales y precisión

Auditoría transversal (backend + frontend) del commit `b74f450f2badf1a2b84e657551115a0595110e45`,
leído en la copia de sólo lectura `/tmp/rendi-main` (verificada: `backend/main.py` = 38.029 líneas).

---

## Método

**Qué ejecuté.** Diez bloques de medición. Ninguno tocó el repo del usuario ni `/tmp/rendi-main`:
copié `backend/` y `frontend/src/utils/` a un scratchpad propio y corrí ahí.

| id | qué corrí | con qué | código real o transplante |
|---|---|---|---|
| M2 / M2b | `main._valuate_positions_for_chat(conn, uid)` — el payload de valuación que se le manda a la IA | python 3.9.6, sqlite temporal creada por el `init_db()` de la app, `fetch_prices_for_symbols` stubbeada (no hay red) | **código real**, función sin modificar |
| M3 | `main._csv_response(...)` — el CSV que se descarga para el contador | ídem | **código real**, función pura sin modificar |
| M4a-b | `new_qty = pos_qty − take` y cadenas de ventas parciales | python | aritmética de las líneas literales `persister.py:837` / `main.py:11367` |
| M4c | ida y vuelta `(x/tc)·tc` sobre 200.000 pares al azar | python | aritmética |
| M4d | `round()` de Python vs `ROUND()` de SQLite vs `numeric` de Postgres | python + sqlite3 en memoria + `decimal.ROUND_HALF_UP` | python y sqlite **reales**; Postgres **emulado** con `Decimal(repr(x)).quantize(ROUND_HALF_UP)` — no tengo un Postgres para correr |
| M5 | `computeBrokerValue` y `fmtUsd`/`fmtArs`/`pct` | node v24.13.1, con un hook de resolución ESM que agrega `.js` a los imports sin extensión | **código real** (`frontend/src/utils/valuation.js`, `format.js`, `crypto.js`, `tickers.js`), sin modificar |
| M6 | distribución del desvío "Σ filas impresas − TOTAL impreso" sobre 3.000 carteras sintéticas por tamaño | node + `format.js` real | **código real** |
| M7 / M11 | `fmtConvertedRaw` y `fmtConvertedCompactRaw` | node | ⚠️ **transplante literal**: node no parsea JSX, así que extraje con `awk` el cuerpo exacto de esas dos funciones desde `CurrencyContext.jsx:234` y `:253` a un módulo aparte. El cuerpo es byte-idéntico; no cambié una línea |
| M8 | `tolerancia_qty` (real, importada de `importing/tenencia.py`) contra los otros 5 umbrales del sistema, y el `ulp` de float64 por tamaño de tenencia | python | **código real** para `tolerancia_qty`; los otros umbrales son las expresiones literales citadas |
| M9 | `main.SyncUnrealizedIn.model_validate_json(...)` con `Infinity`/`NaN`, y `json.dumps(..., allow_nan=False)` como lo hace `starlette.responses.JSONResponse.render` (verificado por `inspect.getsource`, starlette 0.38.6) | python + pydantic reales | **código real** |
| M10 | `_FINITE_BOUND` contra el epsilon del FIFO | python | aritmética |

**Qué NO pude ejecutar y por qué.**

- **No corrí Postgres.** El hallazgo D-02 (los tres modos de redondeo) tiene la mitad medida
  (Python y SQLite, ejecutados) y la mitad **deducida** (Postgres, emulado con `decimal`). La
  semántica que emulo es la documentada de `round(numeric, n)` (half-away-from-zero sobre el
  valor decimal exacto), pero no la verifiqué contra un servidor.
- **No corrí el motor FIFO completo** (`_persist_sell` / `rebuild._replay_asset`) contra una base
  con historia. Los hallazgos D-09 y D-12 son aritmética ejecutada sobre las líneas literales, no
  una corrida del motor. Los marco DEDUCIDO.
- **No tengo datos de producción.** Ninguna magnitud de este informe dice "N usuarios afectados".
  Cuando doy una frecuencia (ej. "75% de las tablas no cierran") es sobre carteras sintéticas
  generadas por mí, y lo digo en el hallazgo.
- **No pude renderizar React.** Todo lo de frontend se midió a nivel de las funciones de formato
  y valuación, no del DOM.

**Deriva.** Dos hallazgos caen en archivos de la lista de deriva:
- D-15 toca `backend/snapshots_job.py` → **⚠️ zona de trabajo activa** (rama `fix/snapshots-valuacion`).
- D-19 toca `backend/pricing/fci.py` → verificado contra `82fad6a0`: la línea `price = round(vcp / 1000.0, 6)`
  es **idéntica** (se movió de `:287` a `:311`). No está corregido ahí.

**Lo que 1A ya dictaminó y no re-audito.** El guard `_trust_mkt_value` y su banda `0,002…50`
(`snapshots_job.py:42-55`), el costo en pesos contado como dólares (A-1), y `position_price_key`
sin mirar `currency` (A-2). Los cito donde tocan mi tema y sigo.

---

## Preguntas que necesito que contestes

Sólo las que bloquean una conclusión. No contesto las 16 del filtro automático.

1. **¿Producción corre SQLite o Postgres hoy?** De esto depende la severidad de **D-02**. Si ya
   migró (o cuando migre), `round(x, n)` dentro de SQL devuelve un número **distinto** al de hoy
   para valores en la mitad exacta, y las columnas afectadas (`gross_amount`, `pnl_usd`,
   `deposits`) son las que alimentan el capital aportado. Si sigue en SQLite, D-02 es una bomba
   con mecha, no una fuga activa.

2. **El CSV de operaciones que baja el usuario para su contador (`/api/export/operations.csv`):
   ¿ya se usó alguno para una declaración?** Hoy imprime `86.20689655172414` en la columna
   rotulada "P&L USD" (**D-07**, MEDIDO). Es el mismo riesgo irreversible que el comentario de
   `main.py:13345-13355` describe para la moneda. Si nadie lo usó todavía, es un fix cosmético; si
   ya salió, hay que avisar.

3. **¿Cuál es la política de decimales que querés?** Hoy no hay ninguna: 638 `round(x, N)` en el
   backend repartidos en **7 escalas distintas** (0, 1, 2, 3, 4, 6, 8) y 468 `toFixed(N)` en el
   frontend en las **mismas 7**. No puedo decir si un `round(..., 4)` es correcto o es un typo
   porque no hay contra qué compararlo. Necesito una regla: *plata = 2, cantidad = 8, FX = 4,
   porcentaje = 2* (o la que sea), y a partir de ahí todo lo que no cumpla es un hallazgo.

4. **¿El feed mobile de Operaciones debe mostrar el número compacto?** `TradesFeed.jsx:106`
   imprime cada trade con `fmtMoneyCompactAt` → un P&L de US$10.499 se lee **"US$10k"** y en el
   93% de los días el subtotal impreso no es la suma de las filas impresas (**D-03**, MEDIDO).
   La tabla desktop del mismo dato usa `decimals: 2`. ¿Es una decisión de diseño mobile o se
   coló?

---

## Resumen ejecutivo

**Lo primero, porque cambia la lectura de todo el resto: el `double precision` del esquema NO es
el problema.** Las 142 columnas de plata son `double precision` y no hay una sola `numeric` en
todo `schema_pg.sql`. Medí la ida y vuelta de moneda sobre 200.000 pares al azar: el peor error
relativo es **2,2e-16** — cero centavos por cada diez mil dólares. Medí el acumulador de caja
(`_adjust_broker_cash`, un `+=` sin redondeo sobre miles de movimientos): el ruido de float queda
seis órdenes de magnitud abajo del centavo. En este dominio (montos ≤ 1e12, cantidades ≤ 1e12)
float64 tiene 15-16 dígitos significativos y le sobran.

**Lo que sí rompe es el CRITERIO, no el tipo.** Hay tres familias de defectos reales:

**1) Hay tres modos de redondeo distintos conviviendo, y uno de ellos entra con la migración.**
Medido: `round(0.125, 2)` da **0,12** en Python (banquero, empata al par), **0,13** en SQLite
(medio hacia afuera sobre el binario) y **0,13** en Postgres; `round(2.675, 2)` da **2,67** en
Python y SQLite pero **2,68** en Postgres, porque `pgshim.py:384` traduce `round(x, n)` a
`round(x::numeric, n)` y el casteo a `numeric` *deshace* el error binario que hacía que 2,675
fuera en realidad 2,67499999…. El docstring de `pgshim` justifica el casteo por otra razón (que
un `Decimal` no explote lejos) y **no menciona que cambia el resultado**. `round(x, 0)` es peor:
0,5 → **0** en Python y **1** en SQLite.

**2) La app tiene un zoológico de tolerancias y ya sabe cuál es la buena, pero sólo la usa en un
lugar.** `importing/tenencia.py:271-329` implementa `tolerancia_qty` — relativa (1e-4) con piso
absoluto (1e-6) — y su docstring documenta, con medición sobre la copia de prod del 2026-08-16,
que el epsilon **absoluto** anterior fabricó **77 filas sintéticas sobre 52 usuarios**. Ese mismo
epsilon absoluto sigue vivo en el motor FIFO (`1e-9` en 8 sitios), en el editor de posiciones
(`1e-6`, `1e-9`), en el chequeo de cantidades del alta (`1e-8`) y en el cruce de traspasos
(`1e-3` relativo, otra constante). Medí los cuatro criterios sobre los mismos cuatro pares de
cantidades: **dan veredictos opuestos**. En particular, el caso que `tenencia.py` documenta como
*señal real* (ADBAICA, 30.066 contra 30.060,46) lo declara "iguales" el criterio de `flujos.py`.

**3) El número que ve el usuario y el número de al lado no son el mismo número, y en un lugar la
diferencia es grande.** Lo peor que encontré está en el **feed mobile de Operaciones**
(`TradesFeed.jsx:55` y `:106`): tanto cada trade como el subtotal del día se imprimen en formato
compacto, que arriba de 9,95 de cada bucket **tira todos los decimales**. Medido: el número
impreso esconde hasta **4,76%** del valor (US$10.499 se lee "US$10k", US$1.049.999 se lee
"US$1.0M") y sobre 2.000 días sintéticos de 4 trades **el 92,9% no cierra**. En modo PESOS es
peor por construcción: todo se multiplica por ~1.487, así que cada monto salta tres buckets y el
compacto se come dos dígitos significativos más. La tabla desktop del mismo trade usa
`decimals: 2` — el mismo dato, dos números, según el dispositivo.

**Lo que ya está bien y conviene no romper.** El equipo ya cazó esta clase de bug tres veces y las
tres veces lo arregló bien, dejando el razonamiento escrito: `MovementsTable.jsx:115-119` ("el
header del grupo muestra centavos, así que las filas tienen que mostrarlos también — si no, el
total *no cierra* con la suma visible de sus filas"), `Positions.jsx:1376-1379` (las filas
agregadas se suman por lote, no se re-valúan) y `tolerancia_qty`. El problema no es que no sepan;
es que el arreglo se aplicó donde apareció el síntoma y no se propagó.

**Un hallazgo de robustez que no es de redondeo pero salió de mirar precisión:** `POST
/api/monthly/sync-unrealized` es el único modelo de su tramo sin el validador `_finite` (que
existe, en `main.py:11099`, definido **67 líneas después** del modelo). Medido: acepta
`Infinity` y `NaN`, los persiste en `monthly_entries.pnl_unrealized` y `capital_final`, y
`starlette.responses.JSONResponse.render` serializa con `allow_nan=False` → **cualquier endpoint
que después devuelva esa fila tira 500**, para siempre, sin forma de arreglarlo desde la UI. El
frontend no puede disparlarlo (`JSON.stringify` convierte NaN a `null` y Pydantic lo rechaza),
pero un cliente cualquiera sí.

---

## Tabla de hallazgos

| # | hallazgo | evidencia | severidad | dónde muerde | causa raíz |
|---|---|---|---|---|---|
| D-01 | `SyncUnrealizedIn` sin `_finite`: acepta `Infinity`/`NaN`, se persisten en `capital_final`, y starlette serializa con `allow_nan=False` → 500 permanente | **MEDIDO** (M9) | 🟠 | Dashboard y Reportes del usuario afectado dejan de cargar | el modelo se declara 67 líneas antes de que exista el validador que todos sus vecinos usan |
| D-02 | Tres modos de redondeo conviven: Python (banquero), `ROUND()` de SQLite (medio afuera sobre el binario), `round(numeric)` de Postgres (medio afuera sobre el decimal exacto). `pgshim.py:384` mete el tercero en la migración | **MEDIDO** (Python+SQLite) · **DEDUCIDO** (Postgres, emulado con `decimal`) | 🟠 | montos persistidos cambian de valor al migrar; `gross_amount`, `pnl_usd`, `deposits` | no hay una función de redondeo única; se usa la del lenguaje que toque |
| D-03 | Feed mobile de Operaciones: filas y subtotal en formato compacto. Esconde hasta 4,76% del valor; el 92,9% de los días no cierra | **MEDIDO** (M11) | 🟠 | `/operaciones` en mobile; el mismo trade se lee distinto que en desktop | `fmtMoneyCompactAt` sin `decimals` en un contexto donde el número ES el dato |
| D-07 | CSV para el contador: montos sin redondear (`86.20689655172414` bajo "P&L USD"), cantidades como `0.30000000000000004` | **MEDIDO** (M3) | 🟠 | `/api/export/operations.csv` y `positions.csv` — el único número que sale hacia un tercero | `_csv_response` pasa los floats crudos (`_csv_safe` no toca los números, a propósito) y la query no redondea |
| D-08 | Al menos 6 criterios distintos de tolerancia de cantidad; dan veredictos opuestos sobre el mismo par. `tolerancia_qty` documenta que el absoluto fabricó 77 filas sintéticas en 52 usuarios y es el único que se arregló | **MEDIDO** (M8c) | 🟡 | FIFO, edición de posiciones, cruce de traspasos, conciliación de fotos | el fix se aplicó en el sitio del síntoma, no como regla |
| D-09 | El epsilon absoluto `1e-9` del FIFO es ciego arriba de ~4,5e6 unidades (el `ulp` del float lo supera). El validador acepta hasta `1e12`, donde el ruido es 122.000× el umbral. SHIB/PEPE/BONK/FLOKI están en la lista de activos | **MEDIDO** (M8a, M10) · magnitud del lote fantasma **DEDUCIDA** | 🟡 | cripto de precio bajo: lote fantasma con `quantity ≈ 2e-6` que nunca se borra | umbral absoluto sobre una cantidad de escala desconocida |
| D-04 | `fmtMoneyRaw` / `fmtConvertedRaw` tienen `decimals = 0` por default **también en USD**: un P&L de US$0,42 imprime `US$0`, y `−US$0` es imprimible | **MEDIDO** (M7) | 🟡 | KPIs de Movimientos, MonthCard, WeekCard, PerformanceCalendar, InsightEvidence | el default se eligió para pesos (donde 0 decimales es correcto) y se hereda en dólares |
| D-05 | El payload de valuación que va a la IA no cierra consigo mismo: Σ de las filas ≠ los `totals` del mismo JSON, y Σ `weight_pct` = 99,98 | **MEDIDO** (M2b, código real) | 🟡 | respuestas del chat / Rendi AI que suman las posiciones | las filas se redondean a 2 y el total se acumula sin redondear; `unrealized_pnl_usd` se calcula **sobre los ya redondeados** |
| D-06 | Builders de IA: `int(round(x))` por broker/holding y el total por separado → la lista no suma el total; `profile_card` manda porcentajes **enteros** de 4 buckets | ESTRUCTURAL + DEDUCIDO | 🟡 | lo mismo: la IA suma lo que le dan | truncar para ahorrar tokens sin re-derivar el total desde lo truncado |
| D-10 | `monthly_entries.pnl_realized` es un acumulador incremental redondeado a 4 en cada escritura, mientras `operations.pnl_usd` guarda `round(...,2)`: el mes nunca es exactamente la suma de sus operaciones | ESTRUCTURAL + DEDUCIDO | 🟡 | Dashboard (mes) vs Operaciones (lista) | dos escalas de redondeo sobre el mismo hecho, y un acumulador en vez de un recálculo |
| D-11 | Escalas incoherentes **en la misma fila persistida**: `pnl_usd`@2, `commissions`@4, `positions.invested`@6, `unit_price`/`tc_compra`@8, `snapshots.total_value` **sin redondear** | ESTRUCTURAL | ⚪ | cualquier lector que re-sume columnas | falta de política (pregunta 3) |
| D-12 | `new_qty = pos_qty − take` se persiste **sin redondear**, y `TradesTable.jsx:150` imprime `op.quantity` crudo | **MEDIDO** (M4a) | ⚪ | columna Cantidad de Operaciones y del CSV: `0.09999999999999998` | la cantidad es el único campo del UPDATE que no pasa por `round()` |
| D-13 | Cupón de bono: `coupon`, `amort` y `total` se redondean **por separado** a 2 → `total ≠ coupon + amort` | ESTRUCTURAL | ⚪ | modal de cupones, inbox de pagos pendientes | tres `toFixed(2)` independientes en vez de derivar el tercero |
| D-14 | Porcentajes de composición redondeados por separado (1 decimal, o entero) → no suman 100 | ESTRUCTURAL + DEDUCIDO | ⚪ | dona de Composición, cards de Insights, packet de IA | falta reparto del resto (largest-remainder) |
| D-15 | `holdings_json` guarda cada activo `round(v, 2)` y **excluye el cash**; `total_value` va sin redondear e **incluye** el cash | ESTRUCTURAL | ⚪ ⚠️ zona de trabajo activa | quien lea `holdings_json` como descomposición del total | dos criterios en el mismo INSERT |
| D-16 | Ida y vuelta de moneda en float: **NO es un problema** (2,2e-16 relativo). El que sí muerde es el de dos *rates* distintos | **MEDIDO** (M4c) | ⚪ | — | (hallazgo negativo, ver detalle) |
| D-17 | `_adjust_cash` rechaza `< −1e-6` y después clampea a `0` — inventa hasta 1e-6 de moneda; `_adjust_broker_cash` permite negativos a propósito | ESTRUCTURAL | ⚪ | saldo de caja | dos escritores del mismo campo con políticas opuestas |
| D-18 | La serie de snapshots se filtra con `total_value > 0` (`twr.py:1313`): un día legítimo en 0 o en negativo (overdraft) desaparece | ESTRUCTURAL | ⚪ | gráfico de evolución, TWR | comparación de float contra 0 usada como filtro de calidad |
| D-19 | FCI: `price = round(vcp / 1000.0, 6)` — error ≤ 5e-7 × cuotapartes | DEDUCIDO | ⚪ | valuación de FCI con muchas cuotapartes | 6 decimales fijos sobre un precio de escala variable |
| D-20 | `medio = round((compra + venta) / 2, 2)` — el TC de valuación se redondea a centavos y multiplica **toda** la cartera | DEDUCIDO | ⚪ | nada visible (3,4e-6 relativo), pero es el único redondeo global | — |

---

## Detalle por hallazgo

### D-01 🟠 · `sync-unrealized` acepta `Infinity` y `NaN`, y eso rompe el usuario para siempre

**Cita verificada** — `backend/main.py:11032-11035`:

```python
class SyncUnrealizedIn(BaseModel):
    broker: str
    pnl_unrealized_usd: float
```

Y el validador que sus vecinos sí usan, **67 líneas más abajo** (`backend/main.py:11099-11106`):

```python
def _finite(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    if not math.isfinite(v):
        raise ValueError('Valor numérico inválido (NaN/Inf)')
    if abs(v) > _FINITE_BOUND:
        raise ValueError('Valor numérico fuera de rango')
    return v
```

`SellIn` (`:11109`), `BuyIn`, etc. declaran `@field_validator(... ) → _finite`. `SyncUnrealizedIn`
no puede: está declarado **antes** de que `_finite` exista. Eso es la causa raíz — no es un olvido
de criterio, es un orden de definición.

El handler (`main.py:11072-11081`) hace:

```python
pnl = round(data.pnl_unrealized_usd, 4)
new_cap_final = round(
    (current['capital_inicio'] or 0) + (current['deposits'] or 0)
    - (current['withdrawals'] or 0) + (current['pnl_realized'] or 0) + pnl, 4)
```

**MEDIDO** (M9, modelo Pydantic real + starlette real):

```
=== M9 · SyncUnrealizedIn sin cotas: ¿entra inf/nan? (modelo REAL) ===
   payload Infinity   → aceptado. round(...,4) = inf   capital_final = inf
   payload NaN        → aceptado. round(...,4) = nan   capital_final = nan
   payload 1e308      → aceptado. round(...,4) = 1e+308   capital_final = 1e+308
   payload -1e308     → aceptado. round(...,4) = -1e+308   capital_final = -1e+308

=== M9b · qué guarda sqlite si el valor es inf/nan ===
   filas guardadas: [(inf,), (None,)]
   SUM() sobre la tabla: (inf,)

=== M9c · starlette JSONResponse.render usa allow_nan=False ===
   json.dumps(inf, allow_nan=False) -> ValueError: Out of range float values are not JSON compliant
   json.dumps(nan, allow_nan=False) -> ValueError: Out of range float values are not JSON compliant
```

`starlette.responses.JSONResponse.render` (verificado con `inspect.getsource`, starlette 0.38.6):

```python
def render(self, content):
    return json.dumps(content, ensure_ascii=False, allow_nan=False, ...)
```

**Consecuencia.** Un solo POST con `Infinity` deja `monthly_entries.capital_final = inf` para ese
`(user, broker, año, mes)`. A partir de ahí, todo endpoint que devuelva esa fila —el resumen
mensual, el dashboard, el informe— **levanta `ValueError` en la serialización y responde 500**. No
hay forma de arreglarlo desde la app: la pantalla que lo arreglaría es la que no carga.

Detalle asimétrico entre bases: SQLite guarda `NaN` como **NULL** (medido arriba: la segunda fila
volvió `None`), así que en SQLite el NaN se auto-cura y sólo el `inf` es tóxico. Postgres
`double precision` **sí** acepta `'NaN'`. Otro caso donde la migración cambia el comportamiento.

**Quién puede dispararlo.** El frontend no: medido, `JSON.stringify({v: NaN})` da `{"v":null}` y
Pydantic rechaza `null` para un `float` no-opcional (y el `.catch(()=>{})` de
`MonthlySummary.jsx:298` se lo come). Hace falta un cliente que mande JSON con el literal
`Infinity` — cURL, un script, un test. Es autenticado (`Depends(get_effective_user)`), o sea
autoinfligido o de un tercero con sesión.

**Qué debería hacer.** Mover `_finite` arriba de los modelos (o declarar
`pnl_unrealized_usd: float = Field(..., ge=-_FINITE_BOUND, le=_FINITE_BOUND)`), y agregar un guard
`math.isfinite` antes de cualquier `round()` que escriba a la base.

---

### D-02 🟠 · Tres modos de redondeo, y el tercero entra con Postgres

**Cita verificada** — `backend/pgshim.py:384`:

```python
salida.append(f"(round(({args[0]})::numeric, {args[1]})::double precision)")
```

y el docstring del módulo (`pgshim.py:39-44`):

> `round(x, n)` → `round(x::numeric, n)::double precision` (la de dos argumentos en Postgres es
> sólo para numeric; el casteo de VUELTA a double no es cosmético: si no, vuelve un Decimal y
> `Decimal + float` es un TypeError lejos de donde se originó)

La justificación es correcta y necesaria. Lo que el docstring **no dice** es que el ida y vuelta
`double → numeric → double` **cambia el resultado**, porque el casteo a `numeric` usa la
representación decimal corta del double y con eso *deshace* el error binario que hacía que el
valor cayera de un lado del empate.

**MEDIDO** (M4d — Python y SQLite ejecutados; Postgres emulado con `Decimal(repr(x)).quantize(..., ROUND_HALF_UP)`):

```
=== M4d · round() de Python vs ROUND() de SQL vs numeric de Postgres ===
         valor |   py round |     sqlite |  PG numeric
         0.125 |       0.12 |       0.13 |        0.13   <-- DIFIEREN
         2.675 |       2.67 |       2.67 |        2.68   <-- DIFIEREN
         1.005 |        1.0 |        1.0 |        1.01   <-- DIFIEREN
           0.5 |        0.5 |        0.5 |         0.5
           2.5 |        2.5 |        2.5 |         2.5
         1.115 |       1.11 |       1.11 |        1.12   <-- DIFIEREN
         8.835 |       8.84 |       8.84 |        8.84
         0.615 |       0.61 |       0.61 |        0.62   <-- DIFIEREN
```

Y con `round(x, 0)`, que es el caso de los enteros:

```
  0.5: python=0  sqlite=1.0
  1.5: python=2  sqlite=2.0
  2.5: python=2  sqlite=3.0
  3.5: python=4  sqlite=4.0
 -0.5: python=0  sqlite=-1.0
```

Python usa **half-to-even** (redondeo del banquero). SQL usa **half-away-from-zero**. Son dos
convenciones contables distintas y el sistema usa las dos según quién haga la cuenta.

**Dónde importa.** Los `ROUND()` de SQL sobre plata están en:

- `main.py:16521` — `ROUND(gross_amount/gross_amount_usd, 0)` (deriva el TC de un import: el
  redondeo a entero es el caso más divergente entre motores)
- `main.py:17132` — `ROUND(COALESCE(SUM(n2.gross_amount),0),2)`
- `main.py:18173-18175` — `ROUND(f.mayor,2)`, `ROUND(p.pico,2)`, `ROUND(f.mayor/NULLIF(p.pico,0),1)`
- `importing/fx_migrate.py:56-60` — `ROUND(SUM(pnl_usd),2)`, `ROUND(SUM(deposits),2)`,
  `ROUND(SUM(withdrawals),2)` — el **antes/después del migrador de FX**, o sea el número con el
  que se decide si una migración se aplica o se frena

Ese último es el que más me preocupa: `fx_migrate.py` compara agregados redondeados en SQL contra
umbrales calculados en Python. Si la base cambia de motor, el mismo insumo puede caer del otro
lado de un freno.

**Qué debería hacer.** Una función única (`money_round(x, n=2)`) en Python con la convención
elegida —para contabilidad, `ROUND_HALF_UP` de `decimal` es la que la gente espera— y prohibir
`ROUND()` en SQL sobre columnas de plata. Los `ROUND()` de SQL que quedan son todos de reportes
de diagnóstico y se pueden mover a Python sin costo.

---

### D-03 🟠 · El feed mobile de Operaciones esconde hasta el 4,76% del número

**Citas verificadas** — `frontend/src/components/operations/TradesFeed.jsx:41` y `:55` (subtotal
del día) y `:106` (cada trade):

```jsx
const subtotalDisp = histMoney.sumConvertedAt(ops, o => (o.pnl_usd || 0))
...
{fmtConvertedCompactRaw(subtotalDisp, histMoney.currency, { signed: true })}
...
{histMoney.fmtMoneyCompactAt(op.pnl_usd, {
  stampedFx: op.fx_to_usd, rowCurrency: op.currency, dateIso: op.date, signed: true,
})}
```

Ninguna de las dos pasa `decimals`. El formateador (`CurrencyContext.jsx:253-273`) hace:

```js
} else if (abs >= 1e3) {
  const k = abs / 1e3
  body = (k < 9.95 ? k.toFixed(1) : String(Math.round(k))) + 'k'
}
```

O sea: entre 1k y 9,95k queda **un** decimal; arriba de 9,95k **ninguno**. El comentario explica
el porqué del corte en 9,95 (evitar el flicker `10.0k → 10k`) y es una buena razón para el corte,
pero el efecto colateral es que arriba de ese punto quedan dos dígitos significativos.

**MEDIDO** (M11, con el cuerpo literal de `fmtConvertedCompactRaw`):

```
   peor error relativo del número impreso: 4.76%  (en US$1,050,002 → US$1.1M)

   ejemplos:
     P&L real US$     1249  →  el feed imprime US$1.2k   (esconde hasta US$49)
     P&L real US$     9949  →  el feed imprime US$9.9k   (esconde hasta US$49)
     P&L real US$    10499  →  el feed imprime US$10k    (esconde hasta US$499)
     P&L real US$    99499  →  el feed imprime US$99k    (esconde hasta US$499)
     P&L real US$  1049999  →  el feed imprime US$1.0M   (esconde hasta US$49999)

=== M11b · un día del feed: ¿el subtotal impreso es la suma de las filas impresas? ===
   sobre 2.000 días de 4 trades cada uno: 92.9% de los días el subtotal NO es la suma de sus filas impresas
```

**Por qué en pesos es peor.** El toggle global multiplica todo por ~1.487. Un trade de US$1.000
—que en dólares cae en el bucket "1.0k" con un decimal— en pesos vale $1.487.000 y cae en el
bucket **M sin decimales**: se imprime `$1.5M`, escondiendo hasta $49.000. La misma pantalla, el
mismo trade, dos dígitos significativos menos por cambiar el toggle.

**Y el mismo dato en desktop se ve completo.** `TradesTable.jsx:154-160` sí pasa `decimals: 2`
(verificado línea por línea; mi primer grep lo dio como faltante porque la opción está en la
línea 159 de una llamada multilínea — corregido). Así que el usuario que abre la misma operación
en la notebook y en el teléfono ve dos números distintos.

**Qué debería hacer.** El compacto sirve para ejes de gráfico y para un hero donde el orden de
magnitud es el mensaje. Para el P&L de una operación individual, el número **es** el dato:
`decimals: 2` (o `decimals: 0` en pesos, que ahí sí corresponde), no compacto.

---

### D-07 🟠 · El CSV que va al contador lleva 14 decimales

**Cita verificada** — `backend/main.py:13353-13362` (la query de `/api/export/operations.csv`):

```python
rows = [dict(r) for r in conn.execute(
    f"""SELECT date AS fecha_cierre, entry_date, asset, broker,
              op_type AS tipo, quantity, entry_price, exit_price,
              {realized_pnl.realized_usd_sql()} AS pnl_usd,
              pnl_pct, commissions
       FROM operations WHERE user_id = ? ORDER BY date DESC""", (uid,))]
```

`realized_usd_sql()` (`backend/realized_pnl.py:101-107`) es:

```sql
CASE WHEN op_type IN (...) AND currency = 'ARS' AND fx_to_usd > 0
     THEN pnl_usd / fx_to_usd ELSE pnl_usd END
```

Una división de floats, **sin `round()`**. Y `_csv_safe` (`main.py:13265-13266`) deja los números
intactos a propósito:

```python
if isinstance(value, (int, float)):
    return value
```

`csv.writer` entonces escribe `str(float)` — la representación corta de Python, que para un
cociente son 15-17 dígitos.

**MEDIDO** (M3, ejecutando el `_csv_response` real):

```
Fecha cierre,Fecha apertura,Activo,Broker,Tipo,Cantidad,Precio entrada,Precio salida,P&L USD,P&L %,Comisiones
2026-03-11,2025-08-02,AL30,Cocos,Cupón,1000.0,,,86.20689655172414,,0.0
2026-04-02,2024-11-19,GGAL,Cocos,Venta,131.0,5583.03,7412.5,161.0672749154525,32.7411,0.30000000000000004
```

Y `positions.csv`, cuyo `quantity` no pasa por ningún `round()` (ver D-12):

```
Activo,Broker,Es cash,Cantidad,Costo invertido,Comisiones,Fecha compra,TC compra (ARS),Precio override
BTC,Binance,0,0.30000000000000004,11223.531,0.0,2025-02-03,,
```

El comentario del propio endpoint (`main.py:13345-13350`) dice, sobre otro bug de esa misma
columna:

> es el único lector cuyo número sale de la app hacia un tercero: una vez que alguien lo usó para
> una declaración, Rendi ya no lo puede corregir.

Se aplica igual acá.

**Riesgo adyacente que no puedo confirmar.** El CSV usa `,` como separador de campo y `.` como
separador decimal. Excel en configuración regional argentina espera `;` y `,`. No pude verificar
qué hace Excel es-AR con este archivo; lo dejo señalado, no lo afirmo.

**Qué debería hacer.** Redondear en la query (`ROUND(..., 2)` para plata, `8` para cantidad) o
formatear la celda en `_csv_response` cuando el valor es float. Lo primero es más barato pero
arrastra D-02; lo segundo es lo correcto.

---

### D-08 🟡 · Seis criterios de tolerancia sobre lo mismo, y el bueno ya está escrito

La app **ya tiene** la implementación correcta y su justificación medida sobre producción.
`backend/importing/tenencia.py:267-329`:

```python
EPS_QTY_ABS = 1e-6     # piso: ruido de float
REL_QTY = 1e-4         # 0,01% de la tenencia comparada

def tolerancia_qty(rendi_qty, foto_qty, *, rel=REL_QTY, abs_min=EPS_QTY_ABS):
    return max(abs_min, rel * min(abs(rendi_qty or 0.0), abs(foto_qty or 0.0)))
```

Su docstring dice, textual:

> `compute_reconcile` comparaba con un epsilon ABSOLUTO de 1e-6. […] Medido sobre la copia de
> prod del 2026-08-16, 152 fotos confirmadas […] 77 filas sintéticas que ya no se crean, sobre 52
> usuarios. […] POR QUÉ RELATIVA Y NO UN ABSOLUTO MÁS GRANDE. Un umbral absoluto no significa lo
> mismo en un FCI de 500.000 cuotapartes que en 0,05 BTC.

**El resto del sistema no aplicó esa lección.** Los criterios que conviven hoy:

| ubicación | expresión | tipo |
|---|---|---|
| `importing/tenencia.py:329` | `max(1e-6, 1e-4 · min(a,b))` | **relativo con piso** ✅ |
| `flujos.py:23,106` | `max(abs(cantidad)·0.001, 1e-6)` | relativo (otro rel: 1e-3) con piso |
| `importing/parsers/iol.py:502` | `abs(q-rq) <= 1e-6 · max(1.0, rq)` | relativo (otro rel: 1e-6) con piso raro |
| `importing/persister.py:834` · `main.py:11362` | `take >= pos_qty - 1e-9` | **absoluto** |
| `main.py:10575, 10631, 10644, 11205, 11220, 14323, 14391, 24145, 24682` | `1e-9` | **absoluto** |
| `main.py:14336, 14325, 14651` | `1e-6` | **absoluto** |
| `main.py:24024` | `if quantity < 1e-8` | **absoluto** |
| `ledger_replay.py:82` | `v > 1e-9` | **absoluto** |

**MEDIDO** (M8c — `tolerancia_qty` importada real, los otros como las expresiones literales, sobre
los cuatro pares que el docstring de `tenencia.py` usa como referencia):

```
   caso                                         gap  tenencia(1e-4 rel)  flujos(1e-3 rel)  FIFO(1e-9 abs)  iol(1e-6 rel)
   FCI 90,1037 vs foto 90,10                 0.0037             iguales           iguales       DISTINTAS      DISTINTAS
   FCI 500.000,0037 vs 500.000,00            0.0037             iguales           iguales       DISTINTAS        iguales
   ADBAICA 30.066 vs 30.060,46               5.5400           DISTINTAS           iguales       DISTINTAS      DISTINTAS
   TRAN 401 vs 400 (1 lámina)                1.0000           DISTINTAS         DISTINTAS       DISTINTAS      DISTINTAS
```

La fila que importa es la tercera: el caso que `tenencia.py` documenta como **señal real** (5,54
unidades sobre 30.066, la primera señal después del hueco medido) lo declara **"iguales"** el
criterio de `flujos.py`. O sea: `cruce_entre_brokers` casaría las dos patas de un traspaso cuyas
cantidades difieren en 5,54 unidades y lo resolvería como "no es aporte ni retiro", cuando
tenencia lo trataría como una diferencia que hay que decidir.

**Qué debería hacer.** Exportar `tolerancia_qty` a un módulo común y hacer que los otros cinco la
llamen, con el `rel` explícito en cada caso si de verdad tienen que diferir. No hace falta
inventar nada: la función y su justificación ya existen.

---

### D-09 🟡 · El `1e-9` del FIFO es ciego arriba de 4,5 millones de unidades

**Cita verificada** — `backend/importing/persister.py:834-845` (idéntico en `main.py:11362-11372`):

```python
if take >= pos_qty - 1e-9:
    conn.execute("DELETE FROM positions WHERE id=? AND user_id=?", (p["id"], uid))
else:
    new_qty = pos_qty - take
    remaining_ratio = 1 - ratio
    new_invested = round((p["invested"] or 0) * remaining_ratio, 6) if p["invested"] is not None else None
    new_commissions = round(pos_buy_commissions * remaining_ratio, 6)
```

**MEDIDO** (M8a, M4b, M10) — el `ulp` (la distancia al siguiente float representable) por tamaño
de tenencia:

```
   cantidad          100   ulp = 1.421e-14   ¿ulp > 1e-9? no
   cantidad      500,000   ulp = 5.821e-11   ¿ulp > 1e-9? no
   cantidad    4,500,000   ulp = 9.313e-10   ¿ulp > 1e-9? no
   cantidad   10,000,000   ulp = 1.863e-09   ¿ulp > 1e-9? SÍ  <-- el umbral es ciego
   cantidad 1,000,000,000   ulp = 1.192e-07   ¿ulp > 1e-9? SÍ
   cantidad 5,000,000,000   ulp = 9.537e-07   ¿ulp > 1e-9? SÍ
```

Y el residuo real de una cadena de 40 ventas parciales:

```
   tenencia         500,000.00: |diferencia| = 4.366e-11   ¿supera 1e-9? False
   tenencia   5,000,000,000.00: |diferencia| = 2.384e-06   ¿supera 1e-9? True
```

**¿Es realista tener miles de millones de unidades?** Sí. `frontend/src/utils/crypto.js:22`
incluye `'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'DEGEN'`. US$1.000 de SHIB son ~60 millones de
unidades; de PEPE, ~100 millones. Y `main.py:11096` define `_FINITE_BOUND = 1e12`, con
`quantity: float = Field(..., gt=0, le=_FINITE_BOUND)` — a 1e12 el ruido del propio float es
`1,2e-4`, **122.000 veces** el umbral que decide si el lote se borra.

**Consecuencia (DEDUCIDA — no corrí el motor).** Un lote grande vendido en varias tandas parciales
que en teoría lo cierran deja `quantity ≈ 2e-6`, que no dispara el `DELETE`. Como
`new_invested = round(invested · (1-ratio), 6)` con `ratio ≈ 1` da `0.0`, queda una fila con
cantidad microscópica y costo cero. Con `real_cost = 0`, `_trust_mkt_value` devuelve `True` sin
comparar nada (`snapshots_job.py:48`), así que el lote fantasma entra a la valuación con valor
`precio × 2e-6 ≈ 0` — numéricamente inofensivo, pero es una fila visible en Cartera con
`quantity` en notación científica.

**Qué debería hacer.** El mismo patrón que `tolerancia_qty`: `take >= pos_qty - max(1e-9, 1e-10 * pos_qty)`.
O redondear `new_qty` a 8-10 decimales antes de persistir (ver D-12), que resuelve las dos cosas.

---

### D-04 🟡 · El formateador de plata de la app tiene 0 decimales por default, también en dólares

**Cita verificada** — `frontend/src/contexts/CurrencyContext.jsx:222` (`fmtMoneyRaw`) y `:236`
(`fmtConvertedRaw`):

```js
const { signed = false, decimals = 0 } = opts
```

`useMoneyFormat().fmtMoney` (`:313-315`) delega en `fmtMoneyRaw`. De las 27 llamadas a `fmtMoney(`
en el frontend, **2** pasan `decimals`. El default se eligió pensando en pesos —donde 0 decimales
es lo correcto, un centavo de peso no existe— y se hereda tal cual en dólares.

**MEDIDO** (M7, con el cuerpo literal de `fmtConvertedRaw`):

```
  P&L real    0.42 USD  →  la tabla imprime  US$0     (con decimals:2 sería US$0,42)
  P&L real   -0.49 USD  →  la tabla imprime  −US$0     (con decimals:2 sería −US$0,49)
  P&L real   12.49 USD  →  la tabla imprime  US$12     (con decimals:2 sería US$12,49)
  P&L real     3.5 USD  →  la tabla imprime  US$4      (con decimals:2 sería US$3,50)
  P&L real    -3.5 USD  →  la tabla imprime  −US$4     (con decimals:2 sería −US$3,50)
```

Dos cosas ahí:

1. **`−US$0`.** Un valor negativo pequeño imprime el signo menos con un cero. `toLocaleString` no
   colapsa el signo. El único lugar del código que lo maneja es el informe de WhatsApp
   (`main.py:35885`, ver *Parches*). En pantalla sigue pasando.
2. **`toLocaleString('es-AR')` también para dólares.** `decimals: 2` sobre un dólar imprime
   `US$12,49` (coma decimal). Es coherente para el público argentino, pero significa que el
   mismo componente produce `US$1.234,56` — que un lector en-US lee como mil doscientos.

**Dónde cae.** `Operations.jsx:85` y `:980` (`const fmtUsd = (v) => money.fmtMoney(v, {signed:false})`),
que alimenta las KPI cards de Movimientos (`computeMovementKpis`, `main` de `Operations.jsx:1358-1410`):
"Aportado neto", "Cobrado", "Comisiones", "Total comisiones", "Promedio". Todas a dólares enteros.
Las **filas** de esa misma tabla usan `decimals: 2` (`MovementsTable.jsx:120-126`) con un
comentario que dice exactamente por qué:

```js
// decimals:2 para que la columna sea coherente: el header del grupo muestra
// centavos, así que las filas que despliega tienen que mostrarlos también
// (si no, el total "no cierra" con la suma visible de sus filas).
```

O sea: se corrigió el header de grupo y se dejaron las KPI cards. El desvío acá es acotado (≤
US$0,50, porque el que se redondea grueso es el total y no las filas), pero "Total comisiones:
US$3" para US$3,47 es un número que el usuario puede chequear contra su resumen del broker.

**Qué debería hacer.** Invertir el default: `decimals` derivado de la moneda (`ARS → 0`, `USD → 2`),
igual que hace `fmtMoney` de `utils/format.js:68` (`const dec = decimals != null ? decimals : isArs ? 0 : 2`).
Ya existe la implementación correcta, en el otro módulo de formato.

---

### D-05 🟡 · El payload que se le manda a la IA no cierra consigo mismo

**Cita verificada** — `backend/main.py:22919-22938`, dentro de `_valuate_positions_for_chat`:

```python
for key in order:
    h = holdings[key]
    total_value += h["value_usd"]            # acumula el valor SIN redondear
    total_invested += h["invested_usd"]
    if not h["is_cash"]:
        total_holdings_value += h["value_usd"]
    h["value_usd"] = round(h["value_usd"], 2)
    h["invested_usd"] = round(h["invested_usd"], 2)
    h["unrealized_pnl_usd"] = round(h["value_usd"] - h["invested_usd"], 2)   # ← sobre los YA redondeados
...
    h["weight_pct"] = (round((h["value_usd"] / total_holdings_value) * 100, 2) ...)
...
totals = {
    "total_value_usd": round(total_value, 2),
    "total_invested_usd": round(total_invested, 2),
    "total_unrealized_pnl_usd": round(total_value - total_invested, 2),
```

Tres criterios en 15 líneas: las filas se redondean a 2; el P&L de cada fila se deriva **de los
valores redondeados** (redondeo intermedio alimentando el cálculo siguiente); los totales se
derivan de los acumuladores **sin redondear**; y `weight_pct` mezcla numerador redondeado con
denominador sin redondear.

**MEDIDO** (M2b — `_valuate_positions_for_chat` real, base sqlite temporal, 12 lotes en un broker
ARS, precios stubbeados, MEP 1487,33):

```
activo      value_usd     invested   unreal_pnl   weight
GGAL           652.87       491.81       161.06     7.96
YPFD           212.78       135.22        77.56     2.59
PAMP           880.39       684.37       196.02    10.73
ALUA           663.71       479.46       184.25     8.09
BMA            373.09       253.55       119.54     4.55
TXAR         1,061.63       814.80       246.83    12.94
CEPU           955.82       694.54       261.28    11.65
LOMA           685.32       522.80       162.52     8.35
SUPV           471.77       330.27       141.50     5.75
COME           924.61       679.95       244.66    11.27
EDN            881.17       657.16       224.01    10.74
TGSU2          439.57       344.09        95.48     5.36
----------------------------------------------------------
Σ filas   value=8,202.73  inv=6,088.02  pnl=2,114.71  Σpeso=99.9800
totals    value=8,202.73  inv=6,088.01  pnl=2,114.72

DESVÍO value : +0.0000 USD
DESVÍO inv   : +0.0100 USD
DESVÍO pnl   : -0.0100 USD
Σ weight_pct : 99.9800  (desvío -0.0200 pp)
```

Un centavo y dos centésimas de punto porcentual. En plata no es nada. **Lo que importa es que
quien consume esto es un LLM**, y un LLM que suma las 12 filas y las compara con el total del
mismo JSON tiene dos números y ninguna forma de saber cuál es el bueno. El docstring de la
función dice, con razón, que se hizo server-side para que la IA no razone sobre números del
cliente; falta el paso siguiente, que el payload sea internamente consistente.

**Qué debería hacer.** Derivar los totales **de las filas ya redondeadas**
(`total_value = sum(h["value_usd"] for h in valued)`), y repartir el resto de los porcentajes con
largest-remainder para que sumen 100,00 exacto.

---

### D-06 🟡 · Los builders de IA truncan a entero y no re-derivan el total

**Citas verificadas:**

`backend/ai/builders/dashboard_brokers.py:67-82`:

```python
grand = max(grand, 1)
...
"value_usd": int(round(data["value"])),
"invested_usd": int(round(data["invested"])),
...
"total_value_usd": int(round(grand)),
```

`backend/ai/builders/profile_card.py:304-308`:

```python
bucket_pcts = (
    {k: round(v / total * 100) for k, v in bucket_totals.items()}
    if total > 0 else {k: 0 for k in bucket_totals})
```

También `dashboard_top_holdings.py:137`, `distribution.py:102,107,145`, `dashboard.py:251`,
`dashboard_evolution.py:126-127`.

**DEDUCIDO.** Con N brokers, `Σ int(round(vᵢ)) − int(round(Σvᵢ))` puede llegar a N/2 dólares; con
4 brokers, hasta 2 dólares, y en el caso peor de `profile_card` los 4 porcentajes enteros suman 98
o 102. La IA reproduce esos números tal cual y a veces los suma.

Truncar a entero para ahorrar tokens es una decisión razonable; el error es no re-derivar el total
desde los truncados.

---

### D-10 🟡 · `pnl_realized` del mes nunca es exactamente la suma de sus operaciones

**Citas verificadas.** El persister guarda la operación redondeada a 2
(`importing/persister.py:824`) pero acumula la **sin redondear** al mes
(`persister.py:803` → `:856-857`):

```python
total_pnl_usd += pnl_usd                 # sin redondear
...
     round(pnl_usd, 2),                  # lo que se guarda en operations
...
helpers._update_monthly_pnl_realized(conn, uid, 'global', op_year, op_month, total_pnl_usd)
```

Y el acumulador mensual (`main.py:9885-9893`) vuelve a redondear, a **4**, en cada escritura:

```python
new_pnl_realized = round((row['pnl_realized'] or 0) + pnl_amount, 4)
new_cap_final = round(... + new_pnl_realized + (row['pnl_unrealized'] or 0), 4)
```

**DEDUCIDO.** Tres desalineaciones sobre el mismo hecho:
- `operations.pnl_usd` = round(x, 2); `monthly_entries.pnl_realized` acumula x sin redondear →
  desvío ≤ 0,005 por chunk de venta.
- El acumulador es **incremental**: cada escritura lee el valor persistido y le suma, redondeando
  a 4. Con N operaciones la deriva acumulada es ≤ N·5e-5.
- El **recálculo** (`main.py:9530-9542`) sí lo hace bien: recompone desde `operations` con un solo
  `round(..., 4)` al final. O sea que el valor del mes **cambia** después de correr un recalc, sin
  que haya cambiado ningún dato.

Lo escribo como 🟡 y no ⚪ no por la magnitud (que es despreciable) sino porque es la definición
de un número que tiene dos caminos de cálculo: eso es lo que produce los tickets de "el dashboard
me dice X y operaciones me dice Y".

**Qué debería hacer.** Que `_update_monthly_pnl_realized` recompute desde `operations` en vez de
incrementar, o que el persister le pase el mismo valor redondeado que escribió en la fila.

---

### D-11 ⚪ · Cinco escalas de redondeo en la misma fila persistida

Del mismo `INSERT`/`UPDATE` del persister (`importing/persister.py:820-840`):

| campo | escala | cita |
|---|---|---|
| `operations.pnl_usd` | **2** | `persister.py:824` |
| `operations.pnl_pct` | **4** | `:825` |
| `operations.commissions` | **4** | `:827` |
| `positions.invested` | **6** | `:839` |
| `positions.commissions` | **6** | `:840` |
| `positions.quantity` | **sin redondear** | `:837` |
| `NormalizedTx.unit_price`, `tc_compra`, `gross_amount` | **8** | `normalizer.py:529-584` |
| `snapshots.total_value` / `total_invested` / `net_deposited` | **sin redondear** al INSERT, redondeados a **2** sólo en el dict que devuelve la función | `snapshots_job.py:791` vs `:795-797` |

Ese último es el más raro: la fila que se guarda y el número que se reporta al caller son distintos.

Tally completo (sin tests ni scripts): backend **638** `round(x, N)` en 7 escalas
(0:2, 1:69, 2:405, 3:8, 4:78, 6:59, 8:17); frontend **468** `toFixed(N)` en las mismas 7
(0:57, 1:143, 2:234, 3:2, 4:22, 6:9, 8:1).

---

### D-12 ⚪ · La cantidad es el único campo que se persiste sin redondear, y se imprime cruda

`persister.py:837` / `main.py:11367`: `new_qty = pos_qty - take`, directo al `UPDATE`.

**MEDIDO** (M4a):

```
  lote 0.5 − venta 0.2 = 0.3
  lote 1.0 − venta 0.9 = 0.09999999999999998
  lote 0.3 − venta 0.1 = 0.19999999999999998
  lote 2.1 − venta 0.7 = 1.4000000000000001
```

Y `frontend/src/components/operations/TradesTable.jsx:150` lo imprime **sin formatear**:

```jsx
<td className="...">{op.quantity ?? '—'}</td>
```

Así que una venta parcial de 0,9 sobre un lote de 1,0 BTC deja una fila que dice
`0.09999999999999998` en la columna Cantidad, en pantalla y en el CSV (D-07). Existe un
formateador para esto —`_fmt_qty` en `main.py:23331`, "entero pelado o hasta 8 decimales sin
ceros"— pero no se usa acá.

---

### D-13 ⚪ · Cupón + amortización ≠ total

`frontend/src/utils/bondSchedule.js:374-376`:

```js
coupon: +(next.coupon * quantity / 100).toFixed(2),
amort:  +(next.amort  * quantity / 100).toFixed(2),
total:  +(next.total  * quantity / 100).toFixed(2),
```

y el mismo patrón en `frontend/src/utils/pendingCashflows.js:145-147`. Los tres se redondean
**independientemente**, así que `coupon + amort` puede diferir de `total` en 0,01. Notar que en el
schedule interno sí está bien hecho (`bondSchedule.js:254`: `total: +(couponAmount + amortOnThisDate).toFixed(6)`,
derivado); el error aparece al re-escalar por `quantity/100`.

Como el `total` es el monto que se pre-carga en el modal y termina en `operations`, la fila
registrada puede no ser la suma de sus dos partes declaradas.

**Qué debería hacer.** Redondear dos y derivar el tercero: `total = +(coupon + amort).toFixed(2)`.

---

### D-14 ⚪ · Los porcentajes no suman 100

- `backend/behavioral.py:1047` y `:1775`: `{"asset": a, "value_usd": round(v,2), "pct": round(v/total*100, 1)}`
- `backend/ai/builders/insights.py:487-490`: `cash_pct`, `ar_pct`, `us_pct`, `crypto_pct`, cada uno
  `round(..., 1)` — una partición de 4 que debe sumar 100
- `backend/ai/builders/profile_card.py:306`: enteros (ver D-06)
- `frontend/src/components/CompositionDonut.jsx:246,319,381,409`: `slice.pct.toFixed(1)`
- `backend/main.py:22932`: `weight_pct` con numerador redondeado y denominador sin redondear (ver D-05)

Todos redondean cada porción por separado. Medido en M2b: `Σ weight_pct = 99,98`. Con 1 decimal y
N porciones el desvío típico es ±0,05·√N puntos.

**Qué debería hacer.** Largest-remainder: repartir el resto entre las porciones con mayor parte
fraccionaria hasta que sumen exacto.

---

### D-15 ⚪ ⚠️ · `holdings_json` y `total_value` no describen lo mismo — *zona de trabajo activa*

`backend/snapshots_job.py:754-791`:

```python
for b in brokers:
    r = compute_broker_value_usd(bpos, ...)
    total_value += r['value']            # INCLUYE el cash del broker
    ...
    for p in bpos:
        if p.get('is_cash'):
            continue                     # el desglose EXCLUYE el cash
        rp = compute_broker_value_usd([p], ...)
        by_asset[p['asset']] += rp['value']
holdings = [{'asset': a, 'value_usd': round(v, 2)} for a, v in by_asset.items()]
...
""", (uid, target_date, total_value, total_invested, ...))   # total_value SIN redondear
```

Dos criterios distintos en el mismo INSERT: el desglose va redondeado a 2 y sin cash; el total va
sin redondear y con cash. `Σ holdings ≠ total_value` por el monto del cash **más** el redondeo.

Verifiqué que la descomposición en sí es exacta: **MEDIDO** (M5a, `computeBrokerValue` real de
`frontend/src/utils/valuation.js`, que es el port espejo):

```
=== M5a · computeBrokerValue: broker entero vs suma por lote (código real) ===
  entero  value= 8202.729219473822  invested= 6088.010784425783
  Σ lotes value= 8202.729219473822  invested= 6088.010784425783
  desvío  value= 0.000e+0  invested= 0.000e+0
```

O sea que el docstring de `_valuate_positions_for_chat` tiene razón: la función suma
contribuciones independientes y el valor por-posición es exacto. El problema no es la valuación,
es qué se guarda de ella.

**⚠️ Este archivo está en la rama `fix/snapshots-valuacion`.** Verificado al momento de escribir:
esa rama no tiene commits ni cambios sin commitear sobre `snapshots_job.py`, así que este hallazgo
está contra la versión vigente. Confirmar antes de tocarlo.

---

### D-16 ⚪ · Ida y vuelta de moneda en float: hallazgo NEGATIVO

El punto 6 del encargo era `x / tc * tc`. **Lo medí y no es un problema.**

**MEDIDO** (M4c, 200.000 pares al azar con `x ∈ [1.000, 50.000.000]` y `tc ∈ [900, 1.600]`):

```
  peor error RELATIVO en 200.000 sorteos: 2.206e-16  (= 0.0000 centavos por cada 10.000 USD)
```

Un error relativo de 2,2e-16 sobre una cartera de US$1.000.000 son 2 diezmilésimas de centavo.

**Lo que sí muerde con esa forma no es el float, son los dos rates.** Cuando el valor se calcula
dividiendo por un TC y se muestra multiplicando por **otro**, la diferencia es del orden del
spread, no del épsilon. Eso ya está diagnosticado y arreglado en Cartera —el comentario de
`Positions.jsx:231-238` cuenta el caso exacto: "filas al 1.341,71 (viejo) y pie al 1.521,10 (el
MEP), 13,4% de diferencia en la misma tabla"— y verifiqué que ahí hoy hay **un solo** dólar de
valuación (`tcCedear = tcMep = tcValuacion`, `Positions.jsx:241-253`).

El caso que queda vivo con esta forma está en **Operaciones**, y es de moneda, no de decimales:
las KPI cards (`computeMovementKpis`, `Operations.jsx:1358-1410`) suman los `amount_usd` crudos y
formatean con `money` (**el dólar de hoy**), mientras las filas usan `histMoney` (**el dólar de la
fecha de cada movimiento**). En modo pesos, "Aportado neto" y la suma de las filas que muestra
abajo son dos números genuinamente distintos, por la devaluación acumulada. El comentario de
`Operations.jsx:976-977` declara la decisión ("Los KPIs de montos siguen con `money`") pero el
comentario hermano de `MovementsTable.jsx:117-119` dice que eso es exactamente lo que no debe
pasar. **Lo dejo señalado y lo derivo al audit de monedas** — no es mi tema y P-114 ya lo tiene
planteado.

---

### D-17 ⚪ · Dos escritores del saldo de caja con políticas opuestas

`backend/main.py:10838-10843` (`_adjust_cash`, camino manual):

```python
new_invested = existing + delta
if new_invested < -1e-6:
    raise HTTPException(400, f"Saldo insuficiente en {broker_name}. Disponible: {existing:.2f}")
new_invested = max(0.0, new_invested)
```

`backend/main.py:9762` (`_adjust_broker_cash`, camino de import), en su docstring:

> Se permiten balances negativos — señal visible de overdraft / margen.

El primero rechaza a partir de −1e-6 y **clampea a cero** lo que queda entre −1e-6 y 0: un saldo
de −0,0000005 se convierte en 0 en silencio (la observación es del mapa, `00-mapa-sistema.md:5246-5248`,
y la verifiqué línea por línea). El segundo deja el negativo a propósito, como señal.

No es una fuga de plata (1e-6 de una moneda), pero sí dos definiciones distintas de "el saldo
puede ser negativo" sobre la misma columna. El `-1e-6` además es absoluto: sobre un saldo de
ARS 500.000.000 el ruido de float ya es del orden de 6e-8, así que el margen real es de menos de
20 ulps.

---

### D-18 ⚪ · `total_value > 0` borra días legítimos de la serie

`backend/twr.py:1310-1313`:

```python
q = [f"""SELECT date, total_value, total_invested, net_deposited, ...
           FROM snapshots WHERE user_id=? AND total_value > 0"""]
```

Es una comparación de float contra 0 usada como filtro de calidad. Un día en que la cartera valió
exactamente 0 (todo vendido, cash retirado) o negativo (overdraft, que `_adjust_broker_cash`
permite explícitamente) **desaparece de la serie**. El módulo tiene una regla escrita justo arriba
—"LOS HUECOS NO SE RELLENAN. Un hueco visible es información"— y este filtro fabrica un hueco que
no lo es: no es que falte la medición, es que la medición dio cero.

---

### D-19 ⚪ · FCI: precio a 6 decimales fijos

`backend/pricing/fci.py:287`: `price = round(vcp / 1000.0, 6)`.

**Verificado contra la deriva:** en `origin/main` `82fad6a0` la línea es idéntica (movida a `:311`).
No está corregida ahí.

**DEDUCIDO.** Con 6 decimales fijos, el error de valuación de una tenencia es ≤ 5e-7 × cuotapartes.
`tenencia.py` documenta tenencias reales de 500.000 cuotapartes → ±0,25 unidades de moneda. En
pesos es invisible; en un FCI en dólares son 25 centavos. Lo que hace ruido es que 6 decimales
sobre un `vcp` chico (un money market con vcp ≈ 1,5 → price 0,0015) deja **3 cifras
significativas**. No verifiqué si existen FCIs con vcp de ese orden en el catálogo.

---

### D-20 ⚪ · El TC de valuación se redondea a centavos

`backend/main.py:4623`: `medio = round((compra + venta) / 2, 2) if compra else venta`.

**DEDUCIDO.** Error relativo ≤ 0,005/1.450 = 3,4e-6. Sobre una cartera de US$100.000 son 34
centavos. Lo listo porque es el único redondeo del sistema que multiplica (o divide) **todos** los
montos a la vez, así que conviene saber que existe y que su cota es esa.

---

## Parches detectados

| ubicación | síntoma que tapa | causa real | dónde más sigue rompiendo |
|---|---|---|---|
| `main.py:35885,35887,35889` — `mu = round(p["market_usd"], 2) + 0.0   # -0.004 → -0.0 → 0.0 (sin "ganó -0")` | el cero negativo en el informe de WhatsApp | redondear un valor a menos decimales de los que tiene su magnitud produce `-0.0`, y ningún formateador lo colapsa | en pantalla: **MEDIDO** que `fmtConvertedRaw(-0.49, 'USD', {})` imprime `−US$0` (D-04). El `+ 0.0` sólo se aplicó en el único lugar donde el síntoma se reportó |
| `ai/builders/dashboard_brokers.py:67` — `grand = max(grand, 1)` | división por cero al calcular `weight_pct` | falta un guard `if total > 0` como el que sí tienen `profile_card.py:305` y `behavioral.py` | una cartera de valor < US$1 reporta pesos calculados sobre un denominador inventado (un broker de US$0,40 sale con `weight_pct = 0.4` en vez de 1.0) |
| `main.py:10843` — `new_invested = max(0.0, new_invested)` después de rechazar `< -1e-6` | un saldo residual negativo de fracción de centavo | el saldo se recalcula por acumulación en vez de derivarse del ledger | D-17: el otro escritor del mismo campo (`_adjust_broker_cash`) permite negativos a propósito. Las dos políticas conviven sobre `positions.invested` de la fila cash |
| `normalizer.py:534-557` — reconciliación de escala per-100 / VCP-por-1000 cuando cantidad × precio ≠ monto | filas donde los tres campos se contradicen | convención de escala del broker, no un problema de precisión | **NO es un parche.** El comentario de 20 líneas explica por qué está gateado por tipo de instrumento y por qué los `k` arbitrarios se dejan intactos a propósito ("un número que no entendemos conserva su firma absurda, que es lo que permite detectarlo"). Es una decisión de diseño bien argumentada — lo listo para que nadie lo confunda con un parche |
| `importing/tenencia.py:669-695` — `build_cash_trueup_txs` (ajusta el efectivo al valor de la foto emitiendo un depósito/retiro sintético) | que el cash de Rendi no coincida con el del broker | — | **NO es un parche.** Es un ajuste explícito, auditable, revertible y documentado, con la foto declarada como fuente de verdad. Lo listo por la misma razón que el anterior |

---

## Citas del mapa incorrectas

| cita | ubicación real | qué decía mal |
|---|---|---|
| **Del encargo, no del mapa:** *"hay comparaciones de igualdad exacta entre `total_value` y `total_invested` en snapshots"* | **no existe en `b74f450f`** | Busqué con seis greps distintos (`total_value.*==`, `total_invested.*==`, `value === invested`, `abs(tv - ti)`, `value - invested` en backend y frontend). La única comparación de `total_value` en todo el backend es `main.py:32677`, que es una asignación, no una igualdad. La única igualdad relacionada es `evolution.js:269` (`nd !== 0`), sobre `net_deposited`. **Si el dato viene de otra versión o de una lectura del mapa, hay que corregirlo: hoy esa comparación no está.** Lo que sí encontré en su lugar es `twr.py:1313` (`WHERE total_value > 0`, D-18) y `main.py:9615-9620` (`DELETE ... WHERE COALESCE(pnl_realized,0) = 0`), que sí son floats comparados contra 0 |
| `00-mapa-sistema.md:410` — «`round(x, n)` → `round(x::numeric, n)::double precision` (el casteo de vuelta evita que un `Decimal` explote lejos con `Decimal + float`)» | `backend/pgshim.py:384` — la cita del **código** es correcta (verificada) | Lo que falta es la consecuencia: el casteo a `numeric` **cambia el resultado del redondeo**, no sólo el tipo. MEDIDO: `round(2.675, 2)` da 2,67 en SQLite y 2,68 en Postgres. El mapa reproduce fielmente el docstring, y el docstring es el que omite el efecto (D-02) |
| `00-mapa-sistema.md:5359` y `:5745` — `SyncUnrealizedIn` «sin validadores… un `inf` o un número absurdo entra tal cual (se redondea a 4 decimales y se guarda)» | `backend/main.py:11032-11035` | **Correcta y verificada.** La amplío: además de guardarse, rompe la serialización de starlette (`allow_nan=False`) y deja al usuario con 500 permanentes. Y agrego la causa raíz que el mapa no da: `_finite` se define en `:11099`, **67 líneas después** del modelo |
| `00-mapa-sistema.md:5246-5248` — `_adjust_cash` «hace `max(0.0, new_invested)` DESPUÉS de haber rechazado los negativos con tolerancia `-1e-6`… un saldo de −0,0000005 se convierte silenciosamente en 0» | `backend/main.py:10838` (rechazo) y `:10843` (clamp) | **Correcta y verificada**, líneas incluidas. Le falta el contraste: el otro escritor del mismo campo (`_adjust_broker_cash`, `main.py:9762`) permite negativos a propósito (D-17) |
| `00-mapa-sistema.md:9735` — «`share_pct` se redondea a 1 decimal mientras `delta_7d_pct` va a 2» | `backend/main.py:37988` | **Correcta.** Es una instancia más de D-11 (falta de política de escalas) |
| `00-mapa-sistema.md:9479` — el truco `round(x, 2) + 0.0` | `backend/main.py:35885,35887,35889` | **Correcta y verificada**, con el comentario literal. Lo reclasifico como PARCHE: el cero negativo sigue imprimiéndose en pantalla (MEDIDO) |

Nota: mi primer grep dio `TradesTable.jsx:154` como una llamada sin `decimals`. **Es falso** — la
opción está en la línea 159, dentro de la misma llamada multilínea. Corregido en D-03. Lo dejo
escrito porque es el modo exacto en que un grep sobre llamadas multilínea produce un falso
positivo, y este informe usó greps en todos lados.

---

## URGENTE

**D-01 — `POST /api/monthly/sync-unrealized` acepta `Infinity` y deja al usuario con 500
permanentes.**

No es urgente por probabilidad —el frontend no puede dispararlo, `JSON.stringify` convierte NaN a
`null`— sino porque **el daño no se puede deshacer desde la app**: la fila envenenada rompe la
serialización de todo endpoint que la devuelva, incluida la pantalla desde la que se arreglaría. Y
el arreglo es de dos líneas: mover `_finite` (`main.py:11099`) arriba de `SyncUnrealizedIn`
(`main.py:11032`), o poner `Field(..., ge=-_FINITE_BOUND, le=_FINITE_BOUND)`.

Recomiendo además un `SELECT` de barrido antes de tocar nada, para saber si ya hay filas así:

```sql
SELECT user_id, broker, year, month, pnl_unrealized, capital_final
  FROM monthly_entries
 WHERE pnl_unrealized IS NOT NULL
   AND (pnl_unrealized != pnl_unrealized OR abs(pnl_unrealized) > 1e12
        OR capital_final != capital_final OR abs(capital_final) > 1e12);
```

(`x != x` es verdadero sólo para NaN. En SQLite el NaN ya se guardó como NULL, así que ahí sólo
va a aparecer el `inf`; en Postgres aparecen los dos.)

Nada más. Los otros 19 hallazgos no requieren acción inmediata.

---

## BLOQUE-RESUMEN

| tema | # | hallazgo | evidencia | severidad | dónde muerde | causa raíz |
|---|---|---|---|---|---|---|
| decimales | D-01 | `SyncUnrealizedIn` sin `_finite`: `Infinity`/`NaN` se persisten en `capital_final` y starlette (`allow_nan=False`) tira 500 para siempre | MEDIDO | 🟠 | Dashboard/Reportes del usuario dejan de cargar; no se arregla desde la UI | el modelo (`main.py:11032`) se declara 67 líneas antes de que exista `_finite` (`:11099`) |
| decimales | D-02 | Tres modos de redondeo: Python (banquero), `ROUND()` de SQLite, `round(numeric)` de Postgres vía `pgshim.py:384`. `round(0.125,2)`=0,12 vs 0,13; `round(2.675,2)`=2,67 vs 2,68 | MEDIDO (py+sqlite) · DEDUCIDO (PG emulado) | 🟠 | `gross_amount`, `pnl_usd`, `deposits`; los frenos de `fx_migrate.py` | no hay función de redondeo única |
| decimales | D-03 | Feed mobile de Operaciones: filas y subtotal en compacto. Esconde hasta 4,76%; 92,9% de los días no cierra; el mismo trade se ve distinto en desktop | MEDIDO | 🟠 | `/operaciones` mobile, peor en modo pesos | `fmtMoneyCompactAt` sin `decimals` donde el número ES el dato |
| decimales | D-07 | CSV para el contador: `86.20689655172414` bajo "P&L USD", `0.30000000000000004` en Cantidad | MEDIDO | 🟠 | `/api/export/operations.csv` y `positions.csv` — sale hacia un tercero | `realized_usd_sql` divide sin redondear y `_csv_safe` no toca números |
| decimales | D-08 | Seis criterios de tolerancia de cantidad con veredictos opuestos; `tolerancia_qty` documenta que el absoluto fabricó 77 filas sintéticas en 52 usuarios y es el único arreglado | MEDIDO | 🟡 | FIFO, edición de posiciones, cruce de traspasos | el fix se aplicó en el sitio del síntoma, no como regla |
| decimales | D-09 | El `1e-9` del FIFO es ciego arriba de 4,5e6 unidades; el validador acepta hasta 1e12 (ruido 122.000× el umbral); SHIB/PEPE/BONK están en la lista | MEDIDO (umbral) · DEDUCIDO (lote fantasma) | 🟡 | cripto de precio bajo: lote fantasma que nunca se borra | umbral absoluto sobre cantidad de escala desconocida |
| decimales | D-04 | `fmtMoneyRaw`/`fmtConvertedRaw` con `decimals = 0` por default también en USD: `US$0,42` → `US$0`; `−US$0` imprimible | MEDIDO | 🟡 | KPIs de Movimientos, MonthCard, WeekCard, PerformanceCalendar | default pensado para pesos, heredado en dólares |
| decimales | D-05 | El payload de valuación de la IA no cierra consigo mismo: Σ filas ≠ totals (0,01 USD), Σ weight_pct = 99,98; `unrealized_pnl` se deriva de los ya redondeados | MEDIDO | 🟡 | respuestas del chat que suman posiciones | filas redondeadas a 2, totales acumulados sin redondear |
| decimales | D-06 | Builders de IA: `int(round(x))` por ítem y total aparte; `profile_card` manda 4 porcentajes enteros | ESTRUCTURAL + DEDUCIDO | 🟡 | lo mismo | truncar sin re-derivar el total desde lo truncado |
| decimales | D-10 | `monthly_entries.pnl_realized` es acumulador incremental a 4 decimales; `operations.pnl_usd` a 2; el recalc da otro número sin que cambien los datos | ESTRUCTURAL + DEDUCIDO | 🟡 | Dashboard (mes) vs Operaciones (lista) | acumulador incremental en vez de recálculo |
| decimales | D-11 | Cinco escalas en la misma fila persistida (2/4/6/8/sin redondear); 638 `round(x,N)` en 7 escalas y 468 `toFixed(N)` en las mismas 7 | ESTRUCTURAL | ⚪ | cualquier lector que re-sume columnas | no hay política de decimales |
| decimales | D-12 | `new_qty = pos_qty − take` sin redondear y `TradesTable.jsx:150` lo imprime crudo: `0.09999999999999998` | MEDIDO | ⚪ | columna Cantidad en pantalla y en el CSV | único campo del UPDATE sin `round()`; `_fmt_qty` existe y no se usa |
| decimales | D-13 | Cupón de bono: `coupon`/`amort`/`total` redondeados por separado → `total ≠ coupon + amort` | ESTRUCTURAL | ⚪ | modal de cupones, inbox de pendientes | tres `toFixed(2)` independientes |
| decimales | D-14 | Porcentajes de composición redondeados por separado → no suman 100 | ESTRUCTURAL + DEDUCIDO | ⚪ | dona de Composición, cards de Insights, packet IA | falta largest-remainder |
| decimales | D-15 | `holdings_json` a 2 decimales y sin cash; `total_value` sin redondear y con cash, en el mismo INSERT | ESTRUCTURAL | ⚪ ⚠️ zona activa | quien lea el desglose como descomposición del total | dos criterios en la misma escritura |
| decimales | D-16 | Ida y vuelta `(x/tc)·tc` en float: **NO es un problema** (2,2e-16 relativo). El que muerde es el de dos rates, ya arreglado en Cartera y vivo en las KPI de Movimientos | MEDIDO | ⚪ | — (se deriva al audit de monedas / P-114) | — |
| decimales | D-17 | `_adjust_cash` rechaza `< −1e-6` y clampea a 0; `_adjust_broker_cash` permite negativos a propósito | ESTRUCTURAL | ⚪ | saldo de caja | dos escritores del mismo campo con políticas opuestas |
| decimales | D-18 | `WHERE total_value > 0` (`twr.py:1313`) borra de la serie un día legítimo en 0 o negativo | ESTRUCTURAL | ⚪ | gráfico de evolución, TWR | float comparado contra 0 como filtro de calidad |
| decimales | D-19 | FCI: `price = round(vcp/1000, 6)` — error ≤ 5e-7 × cuotapartes (verificado idéntico en `82fad6a0`) | DEDUCIDO | ⚪ | valuación de FCI con muchas cuotapartes | 6 decimales fijos sobre precio de escala variable |
| decimales | D-20 | `medio = round((compra+venta)/2, 2)` — el TC que multiplica toda la cartera, redondeado a centavos (3,4e-6 relativo) | DEDUCIDO | ⚪ | nada visible | — |
