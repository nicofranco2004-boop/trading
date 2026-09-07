# 1A — Veredicto: Costo de adquisición, costo promedio y lotes FIFO

**Grupo:** Costo de adquisición, costo promedio y lotes FIFO · 13 divergencias (DIV-050–DIV-062)
**Commit auditado:** `b74f450f` (copia de solo lectura `/tmp/rendi-main`, `backend/main.py` = 38.029 líneas ✅)
**Citas verificadas:** 26 de 32 correctas · 6 corregidas (detalle al final)
**Método:** además de leer el código, se **ejecutaron los motores reales** contra una base temporal (`DB_PATH` en `/var/folders/...`, jamás la del usuario) para medir las diferencias. Ningún archivo del proyecto fue modificado.

---

## Resumen ejecutivo

El costo de adquisición no tiene una sola implementación en Rendi: tiene **cinco motores que consumen lotes** y **siete valuadores que arman el cost basis**, y no coinciden.

Lo más grave, medido y reproducido en esta auditoría con los motores reales:

1. **Tres motores FIFO dan tres respuestas distintas para la misma venta.** Con 5 GGAL comprados en pesos + 5 comprados en dólares y una venta de 7 en pesos: `rebuild._replay_asset` devuelve **P&L +120 USD** y deja 3 nominales abiertos; `persister._persist_sell_fifo` devuelve **+100 USD**, fabrica un lote fantasma y deja 5 abiertos; `main.sell_position_fifo` **rechaza la venta con HTTP 400**. Cuál te toca depende de por dónde entró el dato (venta manual / import / re-import), no de la operación. Es una diferencia del **20 % del resultado realizado** sobre exactamente los mismos hechos.
2. **La amortización de un bono se aplica con dos criterios incompatibles sobre el mismo bono.** `_amortize_position_fifo` (cobro manual) consume el lote más viejo; `sweep_bond_amortizations` (import) reduce todos los lotes proporcionalmente. Medido: sobre 500 nominales a 0,40 + 500 a 0,70, amortizar 500 VN deja un costo unitario remanente de **0,70 USD/VN por FIFO vs 0,57 USD/VN por proporcional** — 23 % de diferencia en el costo del bono que queda en cartera. El criterio correcto es el proporcional (lo dice el propio comentario de `maturity.py`); el FIFO es conceptualmente erróneo para una amortización.
3. **La amortización pierde comisiones.** Medido: cartera con 570 USD de costo económico, se amortiza la mitad, el sistema reporta 200 consumidos y deja 350 en cartera → **20 USD de costo desaparecen**. `realized_gain` de cada amortización queda inflado exactamente en la comisión prorrateada.
4. **El toggle "Costo en dólares" (default `'purchase'`) sólo existe en el navegador y ni siquiera en todo el navegador.** El backend no tiene el concepto: snapshots, libro del asesor, packets de IA e informes usan `'today'` implícito. Y dentro del propio frontend, `MonthlySummary`, `Goals`, `Events`, `useMonthlyData` y `fundamentals/CarteraList` llaman a `computeBrokerValue` **sin pasar `costBasis`** → caen al default `'today'` de la función. El mismo usuario ve dos "invertido" distintos entre Cartera y Mensual.
5. **El costo en pesos de un lote alojado en cuenta dólar se cuenta como dólares en el backend.** `snapshots_job.compute_broker_value_usd` no tiene la rama `costInPesos && !isAR` que sí tiene `valuation.js`. El error es de un factor MEP (≈1.400×) sobre ese lote, y contamina la curva de evolución, el libro del asesor (`GET /api/advisor/book`), el brief diario y el contexto del chat de IA.
6. **"Precio promedio" tiene cinco definiciones y ninguna cierra con "Invertido" de su propia fila.** `avgCostUsdPerUnit` excluye comisiones a propósito; `routedInvUsd`, en la misma fila de Cartera, las incluye. `precio_prom × cantidad ≠ invertido`, siempre, por el monto de las comisiones.
7. **`ai/builders/position_lots.avg_buy_price` es código muerto que le miente al LLM.** Calcula el promedio sobre `operations` con `op_type='Compra'`, y **ningún camino de producción escribe esa fila**: las compras van a `positions`, y el único escritor libre de `op_type` es un input de texto con placeholder "LONG, SHORT, Futuros…". El packet `position.lots` publica `total_qty_bought: 0`, `avg_buy_price: null` y `pattern: "single"` para todo el mundo.

---

## Tabla de veredictos

| DIV | versiones | ¿difieren de verdad? | cuál es la correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---:|---|---|---|---|---|
| DIV-050 | 4 | **SÍ, medido: +120 / +100 / rechazo** sobre la misma secuencia | ninguna entera; `rebuild` es la más correcta (pool único), pero le falta ordenar el pool por `entry_date` | Cartera (`/posiciones`), Operaciones, Dashboard "P&L realizado"; `POST /api/positions/sell-fifo` vs `POST /api/import/confirm` | 🔴 | falta de capa compartida + fix aplicado en un solo motor |
| DIV-051 | 2 | **SÍ: 0,70 vs 0,57 USD/VN remanente** | `sweep_bond_amortizations` (proporcional) | Cartera → fila de bono (costo e "invertido" del residual) | 🔴 | copiar y pegar + el fix (proporcional) nunca se llevó al camino manual |
| DIV-052 | 7 | SÍ en comisiones y en el modo; el resto es la misma cuenta reescrita | `valuation.js:543 valuePositionLot` | todas las que valúan: Cartera desktop/mobile, ficha de activo, Dashboard, Insights, Calidad de cartera, snapshots, libro del asesor | 🟠 | migración a `valuePositionLot` empezada y nunca terminada (su propio docstring lo dice) |
| DIV-053 | 2 vs 5 | SÍ: costo subestimado en el 100 % de la comisión de compra | los que SÍ suman comisiones (frontend, persister, snapshots) | packets de IA (`position`, `dashboard*`, `insights*`), Coach IA, Comportamiento | 🟡 | el `SELECT` de esos builders directamente no trae la columna |
| DIV-054 | 2 | **SÍ: factor ≈ MEP (≈1.400×) sobre ese lote** | `valuation.js` (tiene la rama) | curva de evolución (Reportes/Dashboard), `GET /api/advisor/book`, brief diario, contexto del chat IA | 🔴 | "port fiel" hecho a mano que quedó desactualizado |
| DIV-055 | 2 (+5 callers sin parámetro) | SÍ: el default es `'purchase'` y medio sistema lee `'today'` | ninguna: falta que el modo viaje al backend | Cartera vs Mensual/Metas/Eventos/Calidad; Reportes, informes del asesor, packets IA, CSV | 🟠 | feature de frontend sin contraparte de backend |
| DIV-056 | 2 en la MISMA fila | SÍ, exactamente por las comisiones | `routedInvUsd` (con comisiones) — la casa define costo = invested + commissions | Cartera desktop `/posiciones`: "Precio prom." vs "Invertido" | 🟠 | fix de un bug reportado (tc_compra) que replicó la fórmula en vez de reusarla |
| DIV-057 | 5 | SÍ (2 excluyen comisiones, 1 mezcla monedas, 1 está muerta) | `Σ(invested_i + comm_i)/Σqty_i` ruteada por lote | Cartera (desktop y mobile), ficha de activo, packet IA `position` y `position.lots` | 🟠 | copiar y pegar por superficie |
| DIV-058 | 3 (en realidad 2) | SÍ en precisión: el despeje `pnl/pct` es sensible al redondeo y muere cerca del breakeven | despejar `pnl/pct` es lo mejor DISPONIBLE hoy; lo correcto es persistir `cost_basis_consumed` en la venta | Reportes ("rendimiento por activo"), torta del asesor, `GET /api/advisor/book` | 🟠 | columna creada y nunca escrita en el camino de venta |
| DIV-059 | 1 (contra los 5 FIFO) | SÍ: promedio ponderado ≠ FIFO en cuanto hay ventas parciales | FIFO (es el modelo de la casa) — el backfill debería replayar, no promediar | curva histórica de meses cerrados (Reportes → evolución), snapshots `source='mtm_backfill'` | 🟡 | script escrito aparte, sin reusar el motor |
| DIV-060 | 3 | SÍ: riel BLUE vs riel MEP para el costo de una venta cruzada | `persister`/`rebuild` (gate `fx_version`, riel MEP) | `POST /api/positions/sell-fifo` → P&L de la venta manual en Operaciones/Dashboard | 🟠 | fix del TC histórico aplicado en 2 de 3 motores |
| DIV-061 | 2 | SÍ cuando hay lotes sin `entry_date` o multi-broker | el backend (`COALESCE(...,'9999-12-31') ASC, id ASC`) | ficha de activo `/activo/:ticker` → badge "próximo" | 🟡 | la vista reordena lo que el backend ya ordenó |
| DIV-062 | 2 | **NO entre sí** (medido: las dos devuelven 200,00) — pero **las dos ignoran comisiones** | ninguna: el costo consumido debe ser `(invested + commissions) × ratio` | Cartera → bono → "P&L con cupones"; `POST /api/bonds/cashflow` (`realized_gain`) | 🟠 | la premisa del mapa es incorrecta; el bug real es otro |

---

## Detalle por divergencia

Las divergencias se agrupan por raíz. Donde dos comparten causa, el análisis va junto y se dice.

---

### DIV-050 — Cuatro motores FIFO que escriben las mismas tablas

**Estado de las citas:** ✅ verificadas (4/4).
`backend/importing/rebuild.py:232` = `def _replay_asset` ✅ · `backend/importing/persister.py:601` = `def _persist_sell_fifo` ✅ · `backend/main.py:11149` = `def sell_position_fifo` ✅ · `backend/main.py:10587` = `def _amortize_position_fifo` ✅.

#### a. Implementaciones

**(1) `backend/importing/rebuild.py:232` — `_replay_asset` (replay en memoria, pool único).**
Ordena los eventos con `_full_events` (`rebuild.py:557-559`):
```sql
ORDER BY n.date ASC,
         CASE n.operation_type WHEN 'BUY' THEN 0 ELSE 1 END ASC,
         n.id ASC
```
y construye `lots` en ese orden. En la venta (`rebuild.py:373-379`):
```python
spill_qty = min(max(0.0, oversell_same), _other_total)
_consume_from = list(_same)
if spill_qty > _EPS:
    _consume_from = _consume_from + _other
seed_qty = max(0.0, oversell_same) - spill_qty
if seed_qty > _EPS:
    _consume_from = _consume_from + [_seed(seed_qty)]
```

**(2) `backend/importing/persister.py:601` — `_persist_sell_fifo` (escritura directa al confirmar el import).**
Lee de la DB (`persister.py:657-663`), ordenando por `COALESCE(entry_date,'9999-12-31') ASC, id ASC` sobre el `broker_pair`, y filtra por moneda con:
```python
def _by_ccy(rows):
    same = [p for p in rows if _nccy(dict(p)) == currency]
    return same if same else rows          # persister.py:634-636
```
**Sin spill**: si hay lotes de la moneda de la venta pero no alcanzan, no toca la otra moneda — **fabrica un lote semilla** al precio de venta (`persister.py:673-694`).

**(3) `backend/main.py:11149` — `sell_position_fifo` (venta manual, `POST /api/positions/sell-fifo`).**
Misma query y mismo orden, mismo filtro de moneda (`main.py:11201-11202`), pero:
```python
if data.quantity > total + 1e-9:
    raise HTTPException(400, f"Cantidad solicitada ({data.quantity}) excede el total disponible ({total})")
```
Sin spill y **sin semilla**: rechaza.

**(4) `backend/main.py:10587` — `_amortize_position_fifo`.**
`WHERE user_id=? AND broker=? AND asset=?` — **un solo broker, sin `broker_pair`**, y **sin filtro de moneda**.

#### b. Fórmulas

Sea la venta de $q$ unidades en moneda $c$ a precio $p$, con comisión de venta $f_v$; lotes $L_i=(q_i, I_i, f_i, c_i, d_i)$ (cantidad, invested, comisión de compra, moneda, fecha de entrada).

Costo consumido del lote $i$ por la porción $\theta_i = t_i/q_i$:

$$C_i = \theta_i \cdot (I_i + f_i) \cdot \kappa(c_i \to c)$$

con el conversor cruzado

$$\kappa(\text{USD}\to\text{ARS}) = tc_{venta},\qquad \kappa(\text{ARS}\to\text{USD}) = 1/fx(d_i),\qquad \kappa(c\to c)=1$$

Lo que cambia entre motores es **de qué conjunto sale $t_i$** y **en qué orden**:

| motor | conjunto ordenado | falta de stock |
|---|---|---|
| `_replay_asset` | `[same-ccy en orden de evento] ++ [other-ccy]`, la pata cruzada capada a `spill_qty` | semilla sólo si `_same_total + _other_total < q` |
| `_persist_sell_fifo` | `same-ccy` por `entry_date, id` (o TODOS si no hay same-ccy) | **semilla siempre** por el faltante |
| `sell_position_fifo` | idéntico al anterior | **HTTP 400** |
| `_amortize_position_fifo` | TODOS los lotes del broker por `entry_date, id`, sin distinguir moneda | amortiza lo que hay |

La semilla vale $I_{seed} = q_{falta}\cdot p$ y $f_{seed}=0$ → P&L 0 sobre ese tramo.

#### c. ¿Real o cosmética? — REAL, medida

Secuencia ejecutada con los motores reales (`tc = 1000`):

| # | fecha | broker | operación | qty | precio | moneda | invested |
|---|---|---|---|---|---|---|---|
| 1 | 2024-01-05 | IOL (ARS) | BUY GGAL | 5 | 10.000 | ARS | 50.000 ARS |
| 2 | 2024-02-05 | IOL · USD | BUY GGAL | 5 | 20 | USD | 100 USD |
| 3 | 2024-06-10 | IOL (ARS) | SELL GGAL | 7 | 30.000 | ARS | 210.000 ARS |

Resultado real de cada motor:

```
[rebuild._replay_asset]
   chunk qty=5.0  pnl_usd=100.0  pnl_pct=200.0  entry_price=10000.0
   chunk qty=2.0  pnl_usd= 20.0  pnl_pct= 50.0  entry_price=20.0
   TOTAL pnl_usd = 120.0
   lotes abiertos: 3,0 USD  (invested 60,00)

[persister._persist_sell_fifo]
   chunk qty=5.0  pnl_usd=100.0  pnl_pct=200.0  entry_price=10000.0
   chunk qty=2.0  pnl_usd=  0.0  pnl_pct=  0.0  entry_price=30000.0   ← lote SEMILLA fabricado
   TOTAL pnl_usd = 100.0
   lotes abiertos: 5,0 USD  (invested 100,00)   ← la pata dólar no se tocó

[main.sell_position_fifo]
   HTTPException 400: "Cantidad solicitada (7.0) excede el total disponible (5.0)"
```

Tres números para los mismos hechos: **+120 USD**, **+100 USD** (con un fantasma de 5 nominales) y **operación imposible**. La diferencia de P&L es del 20 %, y la de tenencia es de 2 nominales que existen o no según el camino.

Hay además una divergencia de **orden** que el propio código admite (`rebuild.py:363-372`): `_same` va antes que `_other` **sin mirar `entry_date`**, así que `_replay_asset` no es FIFO puro sobre el pool. Y `_full_events` ordena por `n.date` (SQLite pone los `NULL` **primero**) mientras el persister ordena por `COALESCE(entry_date,'9999-12-31')` (los pone **últimos**): con un lote sin fecha, los dos motores consumen lotes distintos.

#### d. Dictamen

**Ninguna es correcta entera.** El modelo conceptualmente bueno es el de `_replay_asset` (pool único: un CEDEAR es un CEDEAR, la moneda decide el costo del lote, no cuántos nominales tenés), y es además el único causal y determinístico. Pero le falta lo que sí tienen los otros dos: **ordenar el pool por `entry_date, id` en vez de por moneda-y-orden-de-llegada**.

La fórmula correcta es una sola:

$$\text{ordenar todos los lotes del par por } (\,\text{COALESCE}(d_i,\infty),\ id_i\,) \ \Rightarrow\ \text{consumir en ese orden con } \kappa(c_i\to c)$$

y una sola política de faltante (semilla history-as-truth, que es la que el producto ya eligió) aplicada en los tres caminos. Que la venta manual rechace mientras el import fabrica es una **inconsistencia de producto**, no una decisión.

**PARCHE detectado:** el `_by_ccy` del persister (`persister.py:634-636`) — su propio comentario dice "Acá NO hacemos spill para no destruir tenencias dual-currency genuinas en el estado transitorio" y confía en que el rebuild lo pise después. Pero `_is_safe_to_rebuild` (`rebuild.py:565`) **saltea todo grupo que tenga cualquier fila manual o no vinculada**. En esos grupos el estado "transitorio" del persister es el **estado final**, semilla fantasma incluida.

#### e. Qué ve mal el usuario y dónde

- **`/posiciones` (Cartera)**: cantidad de nominales abiertos y "Invertido" del activo. Un lote fantasma de 5 GGAL a 100 USD en el sub-broker "· USD" que el usuario no compró.
- **`/operaciones`**: el P&L realizado de esa venta (+100 vs +120 USD).
- **Dashboard / Reportes**: "P&L realizado del mes" hereda el número del motor que haya escrito.
- **`POST /api/positions/sell-fifo`**: el usuario no puede registrar a mano una venta que su broker sí ejecutó, porque el motor manual no cruza monedas.

#### f. Causa raíz

**Falta de capa compartida** + **fix aplicado en un solo lugar**. Los tres motores de venta son copias con evolución divergente: el "pool único" (2026-08-04) se escribió sólo en `rebuild`, y el comentario de `main.py:11198-11202` lo declara explícito ("El spill cross-currency es exclusivo de la RECONSTRUCCIÓN de IMPORT"). El de amortización (4) es una cuarta copia hecha para bonos que ni siquiera resuelve el par de brokers.

#### g. Fuente única de verdad propuesta

Un módulo `backend/fifo.py` con:

```python
def consume_fifo(lots, qty, sell_ccy, *, fx_lot, fx_sell, on_shortfall) -> (chunks, remaining_lots)
```

puro, sin DB, ordenando por `(COALESCE(entry_date, ∞), id)`, con la conversión cruzada como parámetro y la política de faltante inyectada (`seed` | `reject`). **A eliminar:** el loop de `_persist_sell_fifo` (601-870), el de `sell_position_fifo` (11216-11330) y el de `_replay_asset` (300-500) — los tres pasan a ser adaptadores que cargan lotes, llaman a `consume_fifo` y persisten.

---

### DIV-051 — Un quinto criterio que no es FIFO: la amortización proporcional

**Estado de las citas:** ✅ verificada. `backend/importing/maturity.py:386-400` es exactamente el bloque "Reducción PROPORCIONAL (no FIFO)".

#### a. Implementaciones

**`backend/importing/maturity.py:393-401` — `sweep_bond_amortizations`:**
```python
factor = target / current
if factor >= 1.0 - 1e-9:
    continue
for l in linked_lots:
    lot_qty = l["quantity"] or 0
    new_qty = lot_qty * factor
    new_inv = (l["invested"] or 0) * factor
    new_com = (l["commissions"] or 0) * factor
```
Corre en cada `import_confirm` (`main.py:15103`), en la conciliación por foto de tenencia (`main.py:30872`) y en `recompute_backfill` (`recompute_backfill.py:304`). Agrupa por **par de brokers**, sólo toca lotes import-linked y **exime los lotes sembrados por la foto**.

**`backend/main.py:10587` — `_amortize_position_fifo`:** consume el lote más viejo entero antes de tocar el siguiente. Se dispara desde `POST /api/bonds/cashflow` con `flow_type='amortization'` y `decrement_quantity=true` (`main.py:10460`).

#### b. Fórmulas

Para una amortización que devuelve $A$ de valor nominal sobre lotes $(q_i, I_i, f_i)$:

- **Proporcional** — $\phi = 1 - A/\sum q_i$; para todo $i$: $q_i' = \phi q_i$, $I_i' = \phi I_i$, $f_i' = \phi f_i$.
  Costo unitario remanente = **invariante**: $\dfrac{\sum \phi(I_i+f_i)}{\sum \phi q_i} = \dfrac{\sum (I_i+f_i)}{\sum q_i}$.
- **FIFO** — se consume $t_1=\min(A,q_1)$ del lote más viejo, luego $t_2$, etc.
  Costo unitario remanente = el de los lotes **nuevos**, que es sistemáticamente distinto.

#### c. ¿Real o cosmética? — REAL, medida

Cartera: 500 nominales a 0,40 (invested 200 USD + comisión 20) y 500 a 0,70 (invested 350). Amortización de 500 VN:

```
[FIFO — _amortize_position_fifo]
   consume el lote 1 entero: {'take': 500, 'inv': 200.0, 'com': 20.0, 'survives': False}
   remanente: 500 VN, invested 350,00, com 0,00  →  costo unitario 0,7000 USD/VN

[PROPORCIONAL — criterio de sweep_bond_amortizations]
   remanente: 250 VN inv 100,00 com 10,00  +  250 VN inv 175,00 com 0,00
   costo económico remanente 285,00        →  costo unitario 0,5700 USD/VN
```

**23 % de diferencia** en el costo del bono que queda en cartera, y por lo tanto en su P&L no realizado, para el mismo hecho económico.

#### d. Dictamen

**El proporcional es el correcto** y el propio comentario de `maturity.py:387-392` lo argumenta bien: "cada lámina amortiza igual". Una amortización no es una venta de lotes: es una devolución de capital que ocurre **sobre todos los nominales a la vez**. El FIFO no tiene sentido acá — no elegís qué lámina te amortizan.

Además el proporcional es **currency-aware** por construcción (escala cada moneda por sí misma) mientras que `_amortize_position_fifo` **no filtra por moneda** y consumiría un lote en pesos para amortizar un bono en dólares.

#### e. Qué ve mal el usuario y dónde

`/posiciones` → fila del bono amortizante (AL30, AL35, GD30…): el "Invertido" y el P&L del nominal residual. La divergencia sólo aparece con **más de un lote a precios distintos**, que es el caso normal de quien promedió. Además `POST /api/bonds/cashflow` devuelve `realized_gain` calculado con el costo FIFO.

#### f. Causa raíz

**Copiar y pegar + un fix que no se llevó al otro camino.** El comentario de `maturity.py:389-390` dice literalmente que el FIFO consumía una sola moneda y que eso se corrigió en el audit 2026-06-26 — pero **sólo en el sweep**. `_amortize_position_fifo` quedó con el criterio viejo.

#### g. Fuente única de verdad propuesta

Una función `amortize_pro_rata(lots, face)` en el módulo de bonos, usada por los dos caminos. **A eliminar:** `_amortize_position_fifo` y `_compute_amort_cost_basis_fifo` (que pasan a ser la misma función con y sin escritura).

---

### DIV-052 · DIV-053 · DIV-054 — Los siete valuadores de cost basis (misma raíz)

**Estado de las citas:**
- ✅ `backend/snapshots_job.py:158` = `def compute_broker_value_usd`
- ✅ `backend/behavioral.py:391` = `def _position_value_usd`
- ✅ `frontend/src/utils/valuation.js:543` = `valuePositionLot`
- ✅ `frontend/src/utils/valuation.js:360` = `valueEquityLot`
- ✅ `frontend/src/pages/AssetDetail.jsx:34` = `function valueLot`
- ⚠️ **corregida** — `PositionsMobile.jsx:775` es un comentario suelto; la matriz de valuación vive en **`frontend/src/pages/PositionsMobile.jsx:652-790`** (`const enriched`), y el costo-display del modo en **775-786**.
- ✅ `frontend/src/pages/PositionDetailMobile.jsx:124-187`
- ⚠️ **corregida** — DIV-053 cita `behavioral.py:425`; la línea real es **`behavioral.py:426`** (`invested_native = float(p.get("invested") or 0)`).
- ✅ `backend/ai/builders/insights.py:337` (el `SELECT` sin `commissions`)
- ⚠️ **corregida** — DIV-054 cita `snapshots_job.py:284-319`; la rama USD arranca en **`283`** (`else:`) y termina en **318**.
- ⚠️ **corregida** — DIV-054 cita `valuation.js:569-573`; la rama es **`valuation.js:568-586`**.

#### a. Implementaciones

Las siete, con lo único que las distingue:

| # | ubicación | ¿suma comisiones al costo? | ¿respeta `costBasis`? | ¿rama lote-ARS-en-broker-USD? | ¿rama lote-USD-en-broker-ARS? |
|---|---|---|---|---|---|
| 1 | `valuation.js:543` `valuePositionLot` | ✅ `realCost = invested + comm` | ✅ | ✅ (568) | ✅ (596) |
| 2 | `valuation.js:360` `valueEquityLot` | ✅ | ✅ | ✅ | ✅ |
| 3 | `AssetDetail.jsx:34` `valueLot` | ✅ | ✅ | ✅ | ✅ |
| 4 | `PositionsMobile.jsx:652` `enriched` | ✅ | ✅ | ✅ | ✅ |
| 5 | `PositionDetailMobile.jsx:112` | ✅ (vía `pesoLotUsd`/`usdLotValue`) | ✅ | ✅ | ✅ |
| 6 | `snapshots_job.py:158` `compute_broker_value_usd` | ✅ `real_cost = invested + comm` | ❌ **no existe el parámetro** | ❌ **FALTA** | ✅ (`_cost_in_usd`, 258) |
| 7 | `behavioral.py:391` `_position_value_usd` | ❌ `invested_native = invested` | ❌ | ✅ (vía `_native_ccy`) | ✅ |

Y el octavo, que no está en el mapa pero es el mismo caso:
`backend/ai/builders/insights.py:337` carga las posiciones con
```sql
SELECT asset, broker, quantity, invested, is_cash, currency FROM positions
```
— **sin `commissions`**, así que aunque quisiera sumarlas no las tiene.

#### b. Fórmulas

Costo en USD de un lote, con $I$ = invested, $f$ = comisiones, $r_{hoy}$ = MEP de hoy, $r_c$ = `tc_compra`:

- **Frontend canónico (1-5):**
  $$C_{USD} = \frac{I+f}{\rho},\quad \rho=\begin{cases} r_c & \text{si modo}='purchase' \wedge r_c>0 \\ r_{hoy} & \text{si no}\end{cases}\ \text{cuando el costo está en pesos};\qquad C_{USD}=I+f \text{ si ya está en USD}$$
- **`snapshots_job` (6):** idéntica, pero $\rho \equiv r_{hoy}$ **siempre**, y **le falta el caso** "costo en pesos alojado en broker USD" → para ese lote calcula $C_{USD}=I+f$ **sin dividir**.
- **`behavioral` (7) y `insights` (8):** $C_{USD} = I/\rho$ con $\rho\equiv r_{hoy}$ — **sin $f$**.

#### c. ¿Real o cosmética?

**DIV-052 (los siete valuadores en sí): mayormente COSMÉTICA entre los cinco del frontend.** Se leyeron rama por rama: 1-5 hacen la misma aritmética con distintos nombres. Se detectaron dos diferencias reales, ambas menores:
- `AssetDetail.valueLot` (líneas 51-58): sin precio confiable, el valor cae a `investedUsd` (**ruteado por el modo**), mientras `valuePositionLot` cae a `invUsdHoy`. El P&L es 0 en los dos, pero el **valor absoluto** de un activo sin cotización difiere entre `/activo/XYZ` y `/posiciones` en modo `'purchase'`.
- `PositionsMobile` y `PositionDetailMobile` usan `tcValuacion` donde el canónico usa `cedearRate`. Hoy es cosmético porque los dos valen `pickFinancialRate(dolar, valuationDollar)` (`PositionsMobile.jsx:629-630`, `Dashboard.jsx:192-193`) — la separación de rieles es **vestigial** y una divergencia futura esperando.

**DIV-053: REAL.** El costo del backend de IA/Comportamiento es menor que el de la pantalla exactamente en la comisión de compra. Con una comisión típica del 0,6 %, un lote de 10.000 USD comprado con 60 de comisión:
- pantalla: costo 10.060 → si vale 10.500, P&L +4,37 %
- IA/Comportamiento: costo 10.000 → P&L +5,00 %

Es sistemático y siempre en la misma dirección: **la IA es más optimista que la pantalla sobre la misma posición**, y el sesgo crece con la rotación.

**DIV-054: REAL Y GRANDE.** Un lote con `currency='ARS'` que vive en un broker USD (acción argentina o bono comprado en pesos y ruteado a una cuenta dólar, o cargado a mano):
- `valuation.js:568` → $C_{USD} = (I+f)/r_{hoy}$
- `snapshots_job.py:283-294` → entra al `else` de broker USD y hace `invested += real_cost * cf` → $C_{USD} = I+f$ **en pesos, contados como dólares**

Ejemplo concreto: 100 acciones de PAMP compradas por 1.500.000 ARS (currency='ARS') en un broker marcado USD, MEP 1.500.
- frontend: invertido = **1.000 USD** ✅
- `snapshots_job`: invertido = **1.500.000 USD** ❌ — **1.500× inflado**

El guard `_trust_mkt_value` no salva nada: al comparar el valor de mercado (≈1.000 USD) contra un costo de 1.500.000 rechaza el precio y **valúa la posición al costo inflado**. La curva de evolución, el AUM del asesor y el packet de IA quedan con un millón y medio de dólares fantasma.

#### d. Dictamen

- **DIV-052:** la correcta es `valuation.js:543 valuePositionLot`. Su propio docstring lo dice: *"había CINCO implementaciones … y ninguna era 'la buena a la que volver'. Esta es la que va a serlo. Todavía NO la consume nadie más"*. Es correcto: hoy sólo la consume `computeBrokerValue`.
- **DIV-053:** las correctas son las que suman comisiones. Que la comisión de compra es costo está decidido en toda la casa (`persister._persist_buy` la debita del cash, `valuePositionLot` la suma, `_persist_sell_fifo:747` la incluye en `base_invested`). `behavioral` e `insights` son los outliers.
- **DIV-054:** correcta `valuation.js`. `snapshots_job` tiene un agujero, no una convención distinta.

#### e. Qué ve mal el usuario y dónde

- **DIV-054** contamina, todos por el mismo motor `compute_broker_value_usd`:
  - `backend/snapshots_job.py:751, 897` → snapshots diarios → **Reportes → evolución del portfolio** y la variación diaria del Dashboard
  - `backend/main.py:36924` → `_advisor_positions_valued` → **`GET /api/advisor/book`** (el libro del asesor)
  - `backend/advisor_brief.py:152` → **el email diario del asesor**
  - `backend/main.py:22882` → `_valuate_positions_for_chat` → **el contexto del Coach IA**
  - `backend/ledger_replay.py:273` → replay del ledger
- **DIV-053** contamina los packets de IA que usan `_position_value_usd`: `ai/builders/position.py`, `dashboard.py`, `dashboard_brokers.py`, `dashboard_composition.py`, `dashboard_events.py`, `dashboard_top_holdings.py`, `insights.py`, `insights_attribution.py`, y `reporting/timeline.py`.

#### f. Causa raíz

**"Port fiel" hecho a mano.** El docstring de `compute_broker_value_usd` dice literalmente *"Equivalente Python de frontend `computeBrokerValue` (port fiel, incluida la rama CEDEAR)"*. El frontend después agregó la rama `costInPesos && !isAR` y el port no la recibió — no hay ningún mecanismo que lo obligue. La prueba de que el problema es estructural y no un olvido puntual: el comentario de `snapshots_job.py:245` dice *"Espejo de costInPesos (valuation.js)"* sobre una función llamada `_cost_in_usd` que implementa **`costInUsd`**, no `costInPesos`. Ni el nombre ni el comentario coinciden con lo que hace.

#### g. Fuente única de verdad propuesta

**Una tabla de decisión de moneda-del-costo declarativa, compartida.** El eje no es "frontend vs backend": es que la regla *"¿en qué moneda está el costo de este lote?"* está codificada como cadena de `if` en ocho lugares. Debería ser una función de una línea, `cost_currency(lot, broker) -> 'ARS'|'USD'`, con su tabla de casos versionada y un test de paridad JS↔Python que corra sobre el mismo fixture. **A eliminar:** las ramas duplicadas de `valueEquityLot`, `AssetDetail.valueLot`, `PositionsMobile.enriched` y `PositionDetailMobile` (migrar los cinco lectores a `valuePositionLot`, que es lo que su docstring ya pide); y las tres ramas de moneda de `compute_broker_value_usd`.

---

### DIV-055 — El toggle `costBasis` sólo existe en el navegador (y ni ahí completo)

**Estado de las citas:** ⚠️ **corregida** — el mapa cita `frontend/src/contexts/CurrencyContext.js`; el archivo real es **`frontend/src/contexts/CurrencyContext.jsx`** (no existe el `.js`). Las líneas **102-109** ✅ son correctas.

#### a. Implementaciones

**`frontend/src/contexts/CurrencyContext.jsx:102-109`:**
```js
const [costBasis, setCostBasisRaw] = useState(() => {
  if (typeof window === 'undefined') return 'purchase'
  try {
    return localStorage.getItem(CB_STORAGE_KEY) === 'today' ? 'today' : 'purchase'
  } catch {
    return 'purchase'
  }
})
```
Default **`'purchase'`** — el usuario ve, por defecto, el costo al dólar de la compra.

**Backend:** `compute_broker_value_usd` (`snapshots_job.py:158-167`) **no tiene el parámetro**. `behavioral._position_value_usd` (`behavioral.py:391-393`) tampoco. Ningún endpoint de valuación acepta el modo. Todo el backend es `'today'`.

**Y dentro del frontend**, los llamadores de `computeBrokerValue` se dividen:

| pasa `costBasis` (modo del usuario) | NO lo pasa → default `'today'` |
|---|---|
| `Positions.jsx:1591` (Cartera) | `components/MonthlySummary.jsx:284` |
| `Dashboard.jsx:211` | `pages/Goals.jsx:82` (Metas) |
| `HomeMobile.jsx:111,128` | `pages/Events.jsx:155,167` (Eventos) |
| `Insights.jsx:328,411,526,974` | `hooks/useMonthlyData.js:509` (Mensual) |
| `FirstInsight.jsx:92` | `components/fundamentals/CarteraList.jsx:95` |
| | `Positions.jsx:1610` (**`'today'` explícito**) |

#### b. Fórmulas

$$C_{USD}^{purchase} = \frac{I+f}{tc\_compra},\qquad C_{USD}^{today} = \frac{I+f}{r_{hoy}}$$

$$\frac{C^{purchase}}{C^{today}} = \frac{r_{hoy}}{tc\_compra}$$

#### c. ¿Real o cosmética? — REAL, y el factor es la devaluación acumulada

El propio comentario del contexto (`CurrencyContext.jsx:88-92`) trae el caso reportado por un usuario: `tc_compra` 1.048,6 y MEP de hoy 1.517. Ratio **1,45×**. Sobre un lote de 1.500.000 ARS:
- modo `'purchase'` (default, Cartera) → invertido **1.430,64 USD**
- modo `'today'` (Mensual, Metas, Eventos, snapshots, informes, IA) → invertido **988,79 USD**

**44,7 % de diferencia en el mismo número, en la misma sesión, con dos clicks de distancia.** Con compras de 2021 (blue ≈ 180) el ratio pasa de 8×.

#### d. Dictamen

El modo `'purchase'` es el correcto conceptualmente y el comentario del contexto lo argumenta bien: *"'Cuánto me costó en dólares' son los dólares que pusiste, no los que valdría hoy esa plata"*. El problema no es cuál gana: es que **la elección del usuario no viaja**. La corrección es que `costBasis` sea un parámetro de la valuación en los dos lados, no un estado de UI.

Mientras tanto hay un problema de coherencia más urgente que el de backend: **cinco pantallas del propio frontend ignoran el toggle en silencio**, sin indicarlo. El usuario no tiene forma de saber que Mensual y Cartera están midiendo cosas distintas.

#### e. Qué ve mal el usuario y dónde

- **`/posiciones` (Cartera)** y **Dashboard**: invertido al `tc_compra` (modo del usuario).
- **Mensual** (`useMonthlyData`), **Metas** (`/metas`), **Eventos** (`/eventos`), **Calidad de cartera** (`fundamentals/CarteraList`), **`MonthlySummary`**: el mismo invertido al dólar de hoy. Sin aviso.
- **Reportes → evolución** (snapshots), **informes del asesor**, **packets de IA**, **CSV para el contador**: siempre `'today'`.

#### f. Causa raíz

**Feature de frontend sin contraparte de backend.** El toggle nació como preferencia de display en `localStorage`; nunca se propagó ni al backend ni a todos los callers del propio frontend. El default se cambió a `'purchase'` (comentario `CurrencyContext.jsx:78-101`) **agrandando la divergencia**: antes los dos lados coincidían en `'today'`.

#### g. Fuente única de verdad propuesta

`costBasis` debe ser una **preferencia persistida en `config`** del usuario (como `tc_blue` o `fx_version`), leída por el backend en cada valuación y enviada por el frontend como parámetro. Un solo lugar decide, los dos lados lo respetan. **A eliminar:** el `localStorage` como fuente, y los cinco llamados a `computeBrokerValue` sin `costBasis`.

---

### DIV-056 · DIV-057 — "Precio promedio": cinco definiciones, ninguna cierra con "Invertido" (misma raíz)

**Estado de las citas:**
- ✅ `frontend/src/utils/valuation.js:868` = `export function avgCostUsdPerUnit`
- ✅ `frontend/src/pages/Positions.jsx:1248` = `function routedInvUsd` — ⚠️ la columna "sitios" del mapa dice `frontend/src/pages/Positions.js`; el archivo real es **`.jsx`**
- ✅ `Positions.jsx:2611-2615` (`const avgPrice`) — el mapa cita 2614, dentro del bloque
- ✅ `Positions.jsx:1170` (`buy_price: totalInv / totalQty`)
- ✅ `backend/ai/builders/position.py:84` (`avg_price = (invested / qty)`)
- ✅ `backend/ai/builders/position_lots.py:69-73`

#### a. Implementaciones

**(1) `valuation.js:868` — `avgCostUsdPerUnit`** (columna "Precio prom." en vista dólares):
```js
for (const l of lots) {
  const inv = l?.invested || 0          // ← SIN comisiones, a propósito
  if (!inv) continue
  const costIsPesos = isArsBroker ? !costInUsd(l) : costInPesos(l)
  cost += costIsPesos ? inv / costBasisRate(l, rate, costBasis) : inv
}
return cost > 0 ? cost / qty : null
```
El docstring lo declara: *"SIN comisiones, igual que la columna en pesos, para que ambas vistas midan lo mismo."*

**(2) `Positions.jsx:1248` — `routedInvUsd`** (columna "Invertido", **la misma fila**):
```js
return lots.reduce((s, l) => s + ((l.invested || 0) + (l.commissions || 0)) / costBasisRate(l, rate, costBasis), 0)
```
**CON comisiones.**

**(3) `Positions.jsx:1170` / `Positions.jsx:2614`** — `p.buy_price` crudo, o `invested / quantity` como fallback. Para un agregado multi-lote `buy_price = totalInv / totalQty`, **sin comisiones y sin rutear moneda**.

**(4) `backend/ai/builders/position.py:84`** — `avg_price = invested / qty` sobre la suma cruda de `positions.invested`. Sin comisiones. Si los lotes mezclan monedas devuelve `None` (bien).

**(5) `backend/ai/builders/position_lots.py:69-73`:**
```python
if op_type == "Compra":
    total_buy_qty += qty
    total_buy_value += entry * qty
avg_buy_price = (total_buy_value / total_buy_qty) if total_buy_qty > 0 else None
```
Sobre `operations` con `op_type == 'Compra'`.

**(6) — no está en el mapa** `PositionDetailMobile.jsx:190`:
```js
const avgPriceDisp = !p.is_cash && qty > 0 ? investedDisp / qty : null
```
con `invested = p.invested || 0` (`PositionDetailMobile.jsx:101`) — **sin comisiones**, mientras el P&L de esa misma pantalla las incluye (via `pesoLotUsd`/`usdLotValue`).

#### b. Fórmulas

$$\text{(1) } \bar p_{avg} = \frac{\sum_i I_i/\rho_i}{\sum_i q_i} \qquad \text{(2) } Inv = \sum_i \frac{I_i+f_i}{\rho_i} \qquad \text{(3),(4) } \frac{\sum I_i}{\sum q_i} \qquad \text{(5) } \frac{\sum_{\text{Compra}} p_i q_i}{\sum_{\text{Compra}} q_i}$$

De (1) y (2), en la misma fila:

$$\bar p_{avg}\cdot q \;=\; Inv \;-\; \sum_i \frac{f_i}{\rho_i} \;<\; Inv \qquad \textbf{siempre}$$

#### c. ¿Real o cosmética? — REAL

**DIV-056.** Compra de 100 CEDEARs de AAPL en un broker ARS: invested 1.500.000 ARS, comisión 9.000 ARS, MEP 1.500.
- "Precio prom." = `1.500.000 / 1.500 / 100` = **10,00 USD**
- "Invertido" = `(1.500.000 + 9.000) / 1.500` = **1.006,00 USD**
- $10{,}00 \times 100 = 1.000 \ne 1.006$

El usuario que multiplica las dos columnas contiguas no llega al total, y la diferencia no está explicada en ningún lado. Es chico en porcentaje (0,6 %) pero rompe la aritmética visible de la tabla — y es exactamente el tipo de cosa que hace desconfiar de todo lo demás.

**DIV-057, versión (5): no es una divergencia, es código muerto que le miente al LLM.** Se verificó que **ningún camino de producción escribe `op_type='Compra'` en `operations`**:
- Los `INSERT INTO operations` de producción escriben `'Venta'` (`main.py:11316`, `persister.py:818`, `rebuild.py:763`), `'Interés PF'` (`main.py:9319`), `'Futuros'` (`main.py:12354`), `'Cupón'`/`'Amortización'` (`main.py:10483`) y conversiones (`main.py:10964`).
- Las compras van a `positions`, no a `operations`.
- El único escritor libre es `POST /api/operations` (`main.py:13851`), alimentado por un **input de texto con placeholder "LONG, SHORT, Futuros…"** (`Operations.jsx:843`).
- La única aparición de `'Compra'` en el código de producción es en **listas de exclusión**: `realized_pnl.py:74`, `behavioral.py:66`, `reporting/timeline.py:70,87`, `reporting/builder.py:847,1780`, `ai/builders/profile_card.py:94`.

Consecuencia: el packet `position.lots` publica para **todos** los activos de **todos** los usuarios:
```
total_qty_bought: 0
avg_buy_price: null
pattern: "single"        ← buys siempre vacío → nunca detecta averaging_up/down
```
El bloque de detección de patrón (`position_lots.py:76-89`) es inalcanzable. El LLM recibe "compraste 0 unidades" para una posición viva.

#### d. Dictamen

Ninguna es correcta. La fórmula correcta, coherente con la definición de costo de la casa (`invested + commissions`) y con el ruteo por lote:

$$\bar p_{avg} = \frac{\sum_i (I_i+f_i)/\rho_i}{\sum_i q_i} = \frac{Inv}{q}$$

Es decir: **el precio promedio debe ser el invertido dividido la cantidad, punto.** Cualquier otra definición garantiza que dos columnas contiguas no cierren. El argumento del docstring ("SIN comisiones, igual que la columna en pesos") resuelve una coherencia (USD↔ARS) creando otra incoherencia peor (promedio↔invertido) — y la correcta es sumar las comisiones **en las dos vistas**.

Para (5): `avg_buy_price` y `pattern` deben derivarse de `positions` (los lotes abiertos) o eliminarse. Publicar `0` y `"single"` es peor que no publicar el campo.

#### e. Qué ve mal el usuario y dónde

- **`/posiciones` desktop**: "Precio prom." vs "Invertido" no cierran (DIV-056).
- **`/posiciones` mobile** (`PositionsMobile.jsx:2812`, `avgPriceUsdDe`): mismo problema.
- **`/activo/:ticker`**: `avgCostUsd = investedUsd / qty` con `investedUsd` **con** comisiones (`AssetDetail.jsx:168`) → un tercer promedio, distinto de los dos de Cartera.
- **Detalle de lote mobile** (`PositionDetailMobile.jsx:190`): un cuarto.
- **Coach IA**: `position.avg_price` sin comisiones y sin rutear moneda; `position.lots.avg_buy_price` = `null` siempre.

#### f. Causa raíz

**Copiar y pegar por superficie**, agravado por un fix parcial. El docstring de `avgCostUsdPerUnit` (`valuation.js:846-852`) cuenta que la función nació para arreglar un bug reportado (la celda ignoraba `tc_compra`): se **reimplementó** la fórmula en vez de derivarla del invertido que ya calculaba `routedInvUsd` dos funciones más abajo. La (5) es una implementación construida sobre una suposición nunca verificada sobre el esquema de datos.

#### g. Fuente única de verdad propuesta

`avgCostUsdPerUnit(p, ...)` debe ser **literalmente** `routedInvUsd(p, rate) / p.quantity`. Una función, dos consumidores. **A eliminar:** el loop propio de `avgCostUsdPerUnit`, el fallback `p.buy_price ?? invested/quantity` de `Positions.jsx:2614` y `PositionsMobile.jsx:2815`, el `avgPriceDisp` de `PositionDetailMobile.jsx:190`, y el bloque `total_buy_*` / `pattern` de `position_lots.py:69-89`.

---

### DIV-058 · DIV-059 — El costo de una venta cerrada: despejado, no guardado (misma raíz)

**Estado de las citas:**
- ✅ `backend/main.py:37511` = `cost = (pnl / (float(pct) / 100)) if (pct is not None and float(pct) != 0) else None`
- ✅ `frontend/src/utils/assetPnl.js:222-223`
- ✅ `backend/scripts/backfill_historical_mtm.py:252` (`usd = _a_usd(q * pe, ...)`) — el mapa cita 251-256, el bloque es correcto
- ✅ `backend/scripts/backfill_historical_mtm.py:294` (`avg_cost = (r["buy_amt"] / buy_qty)`) — el mapa cita 293-303
- ⚠️ **matiz sobre el enunciado del mapa:** el mapa dice *"`cost_usd` explícito solo en el libro del asesor"* como si fuera una **tercera fuente**. No lo es: `_advisor_realized_raw` (`main.py:37511`) **despeja `pnl/pct` igual que el frontend** y después lo publica como `cost_usd` (`bookComposition.js:232-235`). Son **dos** fuentes, no tres: el despeje `pnl/pct` (frontend y backend) y `entry_price × quantity` (el backfill).

#### a. Implementaciones

**(1) Despeje `pnl/pct`** — `frontend/src/utils/assetPnl.js:220-227` y `backend/main.py:37510-37515`. Ambas con el mismo guard de cordura `MAX_PNL_TO_COST = 10` (`assetPnl.js:124`, `main.py:37389`).

**(2) `entry_price × quantity`** — `backfill_historical_mtm.py:252`, para las posiciones que a una fecha pasada estaban abiertas y sólo se ven desde `operations`.

**(3) Promedio ponderado sobre `import_normalized_tx`** — `backfill_historical_mtm.py:270-295`:
```sql
SUM(CASE n.operation_type WHEN 'BUY'
      THEN COALESCE(n.gross_amount, quantity*unit_price) ELSE 0 END) AS buy_amt,
SUM(CASE n.operation_type WHEN 'BUY' THEN COALESCE(n.quantity,0) ELSE 0 END) AS buy_qty
```
```python
avg_cost = (r["buy_amt"] / buy_qty) if buy_qty > 0 else 0
... "invested": avg_cost * qty          # qty = ΣBUY − ΣSELL
```

**(4) La columna que nadie escribe** — `operations.cost_basis_consumed` existe (`main.py:1202-1203`) y **sólo se escribe en `POST /api/bonds/cashflow`** (`main.py:10483`). Los tres `INSERT` de venta (`main.py:11312`, `persister.py:818`, `rebuild.py:759`) **no la incluyen**.

#### b. Fórmulas

Del motor FIFO: $pnl = P - C - f_v$ y $pct = 100\cdot pnl/C$, donde $C$ es el costo consumido **con comisiones de compra**. Entonces:

$$\hat C = \frac{pnl}{pct/100} \equiv C \quad\text{(exacto en aritmética real)}$$

Pero lo persistido es $\widetilde{pnl}=\text{round}(pnl,2)$ y $\widetilde{pct}=\text{round}(pct,4)$, de donde el error relativo del costo recuperado es

$$\left|\frac{\Delta \hat C}{C}\right| \lesssim \frac{0{,}005}{|pnl|} + \frac{5\times10^{-5}}{|pct|}$$

Backfill: $C_{avg} = \dfrac{\sum_{BUY} \text{gross}}{\sum_{BUY} q}\cdot\left(\sum_{BUY} q - \sum_{SELL} q\right)$ — **promedio ponderado**, sin comisiones (`gross_amount` no las incluye) y sin conversión cruzada de moneda por lote.

#### c. ¿Real o cosmética? — REAL

**DIV-058.** El despeje es exacto salvo redondeo, pero **se rompe justo donde más importa**:
- Venta cerca del breakeven: costo 10.000, P&L +0,50 USD → $pct = 0{,}005$ → `round(pct,4)` = 0,0050 (ok) pero `round(pnl,2)` = 0,50 → $\hat C = 10.000$. Bien.
- P&L +0,004 USD → $\widetilde{pnl} = 0{,}00$ → la fila se descarta entera (`assetPnl.js:178`: `if (pnl === 0 && !hasExplicitCost) continue`) → **ese capital desaparece del denominador** y el "rendimiento por activo" se calcula sobre una base incompleta, sin ninguna señal.
- $pct = 0$ o `NULL` (cuando `invested_usd = 0`: `pnl_pct = (pnl_usd/invested_usd*100) if invested_usd else None`) → `costIncomplete = true` → el **porcentaje de toda la porción se oculta**.
- Y el guard `MAX_PNL_TO_COST = 10` descarta el % de cualquier posición que haya hecho más de 10× — es decir, **borra el rendimiento de las mejores operaciones**.

**DIV-059: REAL.** Promedio ponderado ≠ FIFO en cuanto hay una venta parcial. Compra 100 a 10 y 100 a 30; venta de 100:
- FIFO: consume el lote de 10 → remanente 100 unidades a costo **30/u** (total 3.000)
- Promedio ponderado del backfill: $\text{avg} = 4.000/200 = 20$; qty = 100 → costo **2.000**

**33 % de diferencia** en el costo del mes cerrado. Y como esos snapshots (`source='mtm_backfill'`) alimentan la curva histórica, el rendimiento de los meses viejos se calcula sobre un capital distinto del que el motor real dejaría.

#### d. Dictamen

**Ninguna es la correcta.** Lo correcto es que los tres `INSERT` de venta persistan `cost_basis_consumed` — el motor **ya lo tiene calculado** en la variable `invested_usd` (`main.py:11279`, `persister.py:793`, `rebuild.py:466`) y lo tira. Es un campo por operación que ya existe en el esquema.

Con eso:
- el despeje `pnl/pct` desaparece de dos lugares,
- el guard `MAX_PNL_TO_COST` se vuelve innecesario para el costo (sigue sirviendo como sanity del %),
- `costIncomplete` deja de aparecer, y
- DIV-059 se resuelve solo: el backfill puede replayar `consume_fifo` (DIV-050.g) en vez de promediar.

#### e. Qué ve mal el usuario y dónde

- **Reportes → "Rendimiento por activo"** y el pie de rendimiento por porción: porcentajes ocultos (`costIncomplete`) o calculados sobre un capital incompleto.
- **`GET /api/advisor/book`** → torta de composición del libro y `_advisor_return_spread` (el rango de retorno entre clientes): mismo despeje, mismos huecos.
- **Reportes → evolución del portfolio**, meses cerrados con `source='mtm_backfill'`: capital sobre promedio ponderado.

#### f. Causa raíz

**Migración a medio hacer.** La columna `cost_basis_consumed` se creó (`main.py:1199-1203`) con el comentario *"Ganancia del amort = pnl_usd − cost_basis_consumed"*, se cableó **sólo para amortizaciones**, y los tres motores de venta nunca se enteraron. Después tres lectores independientes documentaron que la columna está "100 % NULL" (`assetPnl.js:18`, `bookComposition.js:210`, `main.py:37436`) y cada uno se construyó su propio workaround. **El comentario que dice "está 100% NULL" es la evidencia de la migración inconclusa, y se lo tomó como una propiedad del sistema.**

#### g. Fuente única de verdad propuesta

`operations.cost_basis_consumed`, escrita por `consume_fifo` (DIV-050.g) en los tres caminos, en **USD normalizado** (mismo eje que `pnl_usd`). **A eliminar:** el despeje de `assetPnl.js:220-227`, el de `main.py:37510-37515`, el campo derivado `cost_usd` de `bookComposition.js:232`, la bandera `costIncomplete`, y `_holdings_asof` de `backfill_historical_mtm.py:265-303`.

---

### DIV-060 — La venta manual usa el riel BLUE para el costo cruzado; el import usa MEP

**Estado de las citas:** ✅ verificadas (3/3).
`backend/main.py:11249` = `purchase_blue = _import_persister.blue_for_date(conn, entry_dt, cur_blue)` ✅ (exacta) · `backend/importing/rebuild.py:436-441` ✅ · `backend/importing/persister.py:769-771` ✅.

#### a. Implementaciones

**`backend/importing/persister.py:769-772`:**
```python
entry_dt = p["entry_date"] if "entry_date" in p.keys() else None
purchase_fx = (fx_for_date(conn, entry_dt, fallback=tc_blue) if _hist
               else blue_for_date(conn, entry_dt, tc_blue))
base_invested = base_invested / (purchase_fx or tc_blue)
```
con `_hist = fx_version(conn, uid) == FX_V2` (`persister.py:735`).

**`backend/importing/rebuild.py:436-442`:** mismo patrón, `use_hist` viene del `fx_version` de la cuenta.

**`backend/main.py:11247-11250`:**
```python
elif lot_currency == "ARS" and sell_ccy == "USD":
    entry_dt = p["entry_date"] if "entry_date" in p.keys() else None
    purchase_blue = _import_persister.blue_for_date(conn, entry_dt, cur_blue)
    base_invested = base_invested / (purchase_blue or cur_blue)
```
**Sin gate de `fx_version`, y siempre `blue_for_date`.**

La diferencia entre los dos rieles (`fx.py:76-97`, `persister.py:45-65`):

| función | consulta | riel |
|---|---|---|
| `blue_for_date` | `SELECT blue_venta FROM fx_rates_daily WHERE date <= ?` | **BLUE** |
| `fx_for_date` | MEP de la fecha → si no hay, blue de la fecha → fallback | **MEP** (con red de blue) |

#### b. Fórmulas

Costo USD de un lote comprado en pesos y vendido en dólares (dólar-MEP):

$$C_{USD} = \frac{I+f}{\rho_{compra}},\qquad
\rho_{compra}=\begin{cases}
\text{MEP}(d) & \text{persister/rebuild, cuenta v2}\\
\text{blue}(d) & \text{persister/rebuild, cuenta v1}\\
\text{blue}(d) & \textbf{sell\_position\_fifo, siempre}
\end{cases}$$

#### c. ¿Real o cosmética? — REAL para toda cuenta migrada a `fx_v2`

En cuentas v1 los tres coinciden (blue). En cuentas v2 el manual queda en blue y los otros dos en MEP. El spread blue−MEP en Argentina se mueve típicamente entre 0 % y 30 %, y en episodios de cepo cambió de signo. Ejemplo con brecha del 15 %:

Lote de 1.500.000 ARS comprado en 2023-05, MEP de esa fecha 450, blue 520. Vendido a 3.500 USD.
- persister/rebuild (v2): costo = 1.500.000/450 = **3.333,33 USD** → P&L **+166,67 USD** (+5,0 %)
- `sell_position_fifo`: costo = 1.500.000/520 = **2.884,62 USD** → P&L **+615,38 USD** (+21,3 %)

**El mismo hecho, registrado a mano o importado, difiere 3,7× en la ganancia.**

#### d. Dictamen

La correcta es la de `persister`/`rebuild`: riel MEP con red de blue y **gate por `fx_version`**. El gate no es un detalle: `fx.py:110-124` documenta que migrar una sola pata lleva el error del Total Return de 1,23× a 9,1×. `sell_position_fifo` está fuera de ese contrato — escribe con criterio v1 en cuentas v2.

#### e. Qué ve mal el usuario y dónde

`POST /api/positions/sell-fifo` (botón "Vender" de `/posiciones` desktop y mobile) sobre un lote en pesos vendido en dólares (dólar-MEP), en cuentas ya migradas a v2. El P&L de esa venta aparece en **Operaciones**, en el **P&L realizado del Dashboard** y en **Reportes**.

#### f. Causa raíz

**Fix aplicado en dos de tres motores.** La migración FX v2 tocó `persister` y `rebuild` (que son los caminos de import) y dejó afuera el camino manual.

#### g. Fuente única de verdad propuesta

Un helper único `purchase_fx(conn, uid, entry_date, fallback)` que encapsule el gate `fx_version` y el riel, usado por los tres motores.

---

#### URGENTE — dos bugs adyacentes en el mismo bloque, encontrados al verificar DIV-060

Al leer `sell_position_fifo` para DIV-060 aparecieron dos problemas más severos en las líneas contiguas. **No los arreglé** (regla de la auditoría); van acá porque los tres comparten la variable `data.tc_venta` y se arreglan juntos.

El frontend prellena `tc_venta` con el dólar de hoy en ventas ARS (`Positions.jsx:866`, `PositionsMobile.jsx:325`) pero **sólo lo envía si el campo no quedó vacío** (`Positions.jsx:883`, `PositionsMobile.jsx:340`), y el campo **es editable** (`Positions.jsx:3917-3918`). Si el usuario lo borra, `data.tc_venta is None` y:

**(U1) `main.py:11310` — `fx_to_usd` se sella en `1.0` mientras el P&L se dividió por otro número.**
```python
tc_venta = data.tc_venta or _fx.fx_for_date(conn, op_date, fallback=_user_tc_blue(conn, uid)) or 1   # línea 11283
...
fx_stamp = (data.tc_venta or 1) if sell_ccy == "ARS" else None                                        # línea 11310
```
El P&L se calcula con `fx_for_date(op_date)` (p. ej. 1.400) y la fila queda estampada con `fx_to_usd = 1.0`. Todo lector que use ese campo para reconstruir el nominal en pesos (`Positions.jsx:520-535`, `useHistoricalMoney`) va a mostrar el P&L **~1.400× mal**. Es exactamente el error que el comentario de `persister.py:806-812` explica que hay que evitar, y acá está.

**(U2) `main.py:11389-11390` — el asiento mensual del broker recibe el nominal en pesos como si fueran dólares.**
```python
tc_v = data.tc_venta or 1
pnl_for_broker = total_pnl_ars_native / tc_v
```
Con `data.tc_venta` vacío, `tc_v = 1` y un P&L de 1.400.000 ARS entra a `monthly_entries` como **1.400.000 USD**. Ese cache alimenta el P&L realizado por broker de Reportes y Dashboard.

**(U3) `main.py:11246` — la cancelación del TC se rompe en el mismo caso.**
```python
base_invested = base_invested * (data.tc_venta or cur_blue)   # ← dólar de HOY
...
pnl_usd = pnl_ars_chunk / tc_venta                             # ← fx_for_date(op_date)
```
El diseño depende de que el TC que lleva el costo USD a pesos sea **el mismo** que después divide (el comentario de `rebuild.py:426-434` lo explica en detalle: *"TIENE que ser el MISMO número que `tc_venta`, no `tc_blue` … los hace divergir ~5× y mete una pérdida fantasma"*). Acá divergen: `cur_blue` (hoy) contra `fx_for_date(op_date)` (la fecha de la venta). En una venta vieja de una cuenta v2, el costo USD del lote queda multiplicado por `cur_blue/fx(op_date)` — para una venta de 2021, un factor de ~8×.

Los tres se resuelven con una línea de disciplina: **resolver `tc_venta` UNA vez, arriba del loop, y usar esa variable en los cuatro lugares** (conversión del costo, división del P&L, `fx_stamp` y `pnl_for_broker`). El persister y el rebuild ya lo hacen así y por eso no tienen ninguno de los tres.

---

### DIV-061 — El orden de lotes de la ficha de activo no es el del motor

**Estado de las citas:** ✅ verificada. `frontend/src/pages/AssetDetail.jsx:163`:
```js
}).sort((a, b) => (a.entry_date || '').localeCompare(b.entry_date || '')) // FIFO: viejo primero
```
El badge está en `AssetDetail.jsx:308`: `{i === 0 && <span ...>próximo</span>}`.

#### a. Implementaciones

**Frontend** (`AssetDetail.jsx:163`): `localeCompare` sobre `entry_date || ''`. La cadena vacía es **menor que todo** → los lotes sin fecha van **primeros**. Sin desempate por `id`.

**Backend**, los tres motores: `ORDER BY COALESCE(entry_date, '9999-12-31') ASC, id ASC` (`persister.py:662`, `main.py:11184`, `main.py:10562`, `main.py:10586`, `maturity.py:352`). Los sin fecha van **últimos**, y el empate lo rompe `id`.

**Y un tercer orden:** `rebuild._full_events` (`rebuild.py:557`) usa `ORDER BY n.date ASC` — SQLite ordena `NULL` **primero**, así que el rebuild coincide con la vista y difiere del persister.

#### b. Fórmulas

$$\text{frontend: } \text{key}_i = (\,d_i \lor \text{''}\,) \qquad \text{backend: } \text{key}_i = (\,d_i \lor \text{'9999-12-31'},\ id_i\,)$$

#### c. ¿Real o cosmética? — REAL, pero acotada

Sólo diverge si algún lote del activo tiene `entry_date` nulo o vacío. Cuando ocurre, el badge "próximo" señala **el lote que el motor consumirá último**.

Hay un segundo error, más frecuente, que el mapa no menciona: **`AssetDetail` agrega lotes de TODOS los brokers** (`AssetDetail.jsx:135`: `pos.filter(p => p.asset === asset)`), pero el FIFO real sólo recorre el **`broker_pair`** de la venta (`persister.py:658`, `main.py:11182`). Con AL30 en IOL y en Balanz, el "próximo" que muestra la ficha puede ser un lote de Balanz mientras una venta en IOL consume el de IOL. Esto pasa **siempre** que el activo esté en más de un broker no emparejado, no sólo con fechas nulas.

#### d. Dictamen

Correcto el backend. La vista debe replicar **exactamente** `(COALESCE(entry_date,'9999-12-31'), id)` **y** el badge debe ser por par de brokers, no global. Como el endpoint `GET /api/positions` (`main.py:8190-8192`) **ya devuelve las filas en ese orden**, lo correcto es simplemente **no reordenar**.

#### e. Qué ve mal el usuario y dónde

`/activo/:ticker` → tabla "Lotes abiertos · orden FIFO" (`AssetDetail.jsx:285-310`) → el badge naranja **"próximo"**. Es información sobre la que el usuario decide qué vender.

#### f. Causa raíz

**El frontend recalcula lo que el backend ya calculó.** La API ya entrega el orden canónico y la vista lo re-derivó con una regla aproximada.

#### g. Fuente única de verdad propuesta

`ORDER BY` del backend, consumido tal cual. **A eliminar:** el `.sort()` de `AssetDetail.jsx:163`. Si hace falta reordenar en cliente, exportar un `fifoComparator(a,b)` desde `valuation.js` que replique el `COALESCE` y el desempate por `id`, y usarlo en las dos vistas.

---

### DIV-062 — El costo consumido por una amortización ignora las comisiones (la premisa del mapa es incorrecta)

**Estado de las citas:** ⚠️ **corregida**.
- El mapa cita `backend/main.py:10584` para `_compute_amort_cost_basis_fifo`. La línea real es **`backend/main.py:10549`** (`10584` cae dentro del docstring de `_amortize_position_fifo`, que arranca en `10587`). **Cita del mapa incorrecta.**
- El mapa cita `backend/main.py:10643`; las líneas reales del manejo de comisiones son **`10640-10642`**.

#### a. Implementaciones

**`backend/main.py:10549` — `_compute_amort_cost_basis_fifo` (read-only):**
```python
ratio = take / lot_qty
total_consumed += (lot['invested'] or 0) * ratio      # main.py:10581
```

**`backend/main.py:10587` — `_amortize_position_fifo` (escribe):**
```python
new_invested   = (lot['invested'] or 0) * (1 - ratio)
new_commissions = (lot['commissions'] or 0) * (1 - ratio)    # main.py:10640
invested_taken  = (lot['invested'] or 0) * ratio
com_taken       = (lot['commissions'] or 0) * ratio           # main.py:10642
total_invested_dec += invested_taken                          # ← com_taken NO se suma
...
return qty_to_take, round(total_invested_dec, 6)
```

`com_taken` se guarda en el `detail_out` (para poder deshacer el cobro) pero **no entra en el valor devuelto**.

#### b. Fórmulas

$$\text{(1) read-only: } C = \sum_i \theta_i I_i \qquad \text{(2) mutate: } C = \sum_i \theta_i I_i \quad\textbf{(idéntica)}$$
$$\text{correcta: } C = \sum_i \theta_i (I_i + f_i)$$

#### c. ¿Real o cosmética? — La divergencia del mapa NO existe; el bug SÍ

Ejecutado con las funciones reales sobre 500 nominales a 0,40 (invested 200 + comisión 20) + 500 a 0,70 (invested 350), amortizando 500 VN:

```
_compute_amort_cost_basis_fifo(500 VN) -> 200.0
_amortize_position_fifo(500 VN)        -> qty 500, cost_basis_consumed 200.0
   detalle: [{'id': 1, 'take': 500, 'inv': 200.0, 'com': 20.0, 'survives': False}]
post-FIFO: lote2 qty=500  inv=350,00  com=0,00
   costo económico remanente 350,00 + consumido reportado 200,00 = 550,00  (debería ser 570,00)
```

**Las dos devuelven exactamente 200,00.** La afirmación del mapa (*"`_compute` ignora las comisiones mientras `_amortize` sí las reduce, así que `cost_basis_consumed` queda sistemáticamente bajo"*) parte de una lectura equivocada: `_amortize` **reduce** `positions.commissions` pero **no las devuelve**.

El bug real, medido, es otro y es peor: **20 USD de costo económico desaparecen del sistema**. No están en el lote remanente (se borró con el lote 1) ni en el `cost_basis_consumed` reportado. `realized_gain = net_amount − cost_basis_consumed` (`main.py:10508`) queda inflado exactamente en esa comisión prorrateada.

Y hay una **asimetría según `decrement_quantity`** que sí es una divergencia genuina:
- `decrement_quantity=true` → el lote pierde su comisión (350 + 0) y el costo total del sistema baja de 570 a 550.
- `decrement_quantity=false` → el lote conserva las 20 (`200+20 + 350` = 570) **y además** se estampa `cost_basis_consumed = 200`, que Positions.jsx resta del cash. El mismo cobro deja el sistema en dos estados distintos.

#### PARCHE — `cross_currency_skipped` (`main.py:10446-10457`)

En el mismo bloque hay un parche explícito:
```python
face_to_decrement = (data.face_amortized
    if data.face_amortized is not None and data.face_amortized > 0 else net_amount)
...
total_qty = _bond_total_qty(conn, uid, data.broker, data.asset.upper())
if total_qty > 0 and face_to_decrement > total_qty * 1.5:
    cross_currency_skipped = True
    plausible_face = min(face_to_decrement, total_qty)
    cost_basis_consumed = _compute_amort_cost_basis_fifo(conn, uid, ..., plausible_face)
```
**Síntoma que tapa:** un cobro registrado en pesos usa el **monto en ARS como cantidad de nominales** (`face_to_decrement = net_amount`), lo que destruiría la posición.
**Causa real:** `net_amount` está en la moneda del broker y `quantity` en valor nominal del bono; el endpoint mezcla los dos ejes.
**Qué hace el parche:** aborta el decremento pero **igual calcula un costo**: `plausible_face = min(face_ARS, total_qty)` = **la posición entera** → `cost_basis_consumed` = **todo el cost basis del bono**, para un cobro que amortizó una fracción.
**Dónde más sigue rompiendo la misma causa:** `cost_basis_consumed` se guarda **en la moneda del lote** mientras `pnl_usd` de la fila se guarda **en la moneda del broker** (`main.py:10483`, `net_amount` crudo). `Positions.jsx:539-543` los resta directo:
```js
pnlContrib = amt - cbConsumed
```
Un bono con `positions.currency='USD'` (invested 53,84 USD) en un broker ARS que cobra la amortización en pesos (96.000 ARS) da `pnlContrib = 96.000 − 53,84 = 95.946 ARS`, cuando el costo real en pesos es `53,84 × 1.250 = 67.300` y la ganancia verdadera son ~28.700 ARS. **La ganancia de la amortización aparece 3,3× inflada**, y después se divide por `fx` (`Positions.jsx:551`) arrastrando el error a los dólares.

#### d. Dictamen

Ninguna es correcta. El costo consumido debe ser:

$$C = \sum_i \theta_i\,(I_i + f_i)\ \text{, prorrateado } \textbf{proporcionalmente} \text{ (DIV-051), y expresado en el mismo eje de moneda que } \texttt{pnl\_usd}$$

Y `_compute_amort_cost_basis_fifo` no debería existir: es la misma función que `_amortize_position_fifo` con un flag de escritura.

#### e. Qué ve mal el usuario y dónde

- **`/posiciones` → fila de bono expandida → "P&L con cupones"** y el tooltip `pnlTooltip` (`Positions.jsx:2618-2620`): la ganancia realizada de cada amortización, inflada por las comisiones y —en cobros cross-currency— por un factor MEP.
- **`POST /api/bonds/cashflow`** → campo `realized_gain` de la respuesta y el toast.
- El **costo remanente del bono en cartera**, que queda 20 USD (en el ejemplo) por debajo de lo que se pagó.

#### f. Causa raíz

**Copiar y pegar** (dos funciones que son la misma) sobre un **modelo de moneda incompleto** (un solo campo `cost_basis_consumed` sin eje de moneda declarado). El parche `cross_currency_skipped` es la señal: en vez de resolver el eje, se agregó un heurístico (`> total_qty * 1.5`) que decide si un número es "plausible".

#### g. Fuente única de verdad propuesta

`amortize_pro_rata(lots, face, *, dry_run: bool)` (la misma de DIV-051.g), devolviendo `(qty, cost_consumed_usd, detail)` con el costo **normalizado a USD** por la moneda de cada lote. **A eliminar:** `_compute_amort_cost_basis_fifo` completa, `_amortize_position_fifo`, y el heurístico `cross_currency_skipped` (que deja de tener sentido cuando `face` y `amount` viajan en ejes declarados).

---

## Parches detectados

| ubicación | qué síntoma tapa | causa real | dónde más sigue rompiendo |
|---|---|---|---|
| `persister.py:634-636` — `_by_ccy` con fallback "a todos si no hay same-ccy", **sin spill**, apoyado en que "el rebuild lo pisa después" | tenencias dual-currency destruidas en el estado transitorio del import | dos motores FIFO con políticas de moneda distintas y ningún contrato entre ellos | `rebuild._is_safe_to_rebuild` (`rebuild.py:565`) saltea todo grupo con data manual → en esos grupos el "transitorio" es el estado FINAL, con lote semilla fantasma incluido |
| `main.py:10446-10457` — `cross_currency_skipped` (`face_to_decrement > total_qty * 1.5` → abortar y usar `min(face, total_qty)` como base de costo) | una amortización en pesos destruía la posición porque el monto en ARS se usa como cantidad de nominales | `amount` está en moneda del broker y `quantity` en valor nominal; el endpoint mezcla los dos ejes | `cost_basis_consumed` se guarda en moneda del LOTE y `pnl_usd` en moneda del BROKER; `Positions.jsx:542` los resta directo → ganancia de amortización inflada ~MEP× en cobros cross-currency |
| `assetPnl.js:122-125` y `main.py:37402-37406` — `MAX_PNL_TO_COST = 10`: si `\|pnl\| > 10 × costo`, devolver `null` | costos absurdos salidos del despeje `pnl/pct` (el comentario cita GD35: +9.804 %) | el costo de una venta **no se persiste**: se despeja de dos números redondeados | borra el % de rendimiento de **cualquier operación real que haya hecho más de 10×** — el parche descarta ganancias legítimas junto con los artefactos |
| `rebuild.py:363-372` — `_same` antes que `_other` sin mirar `entry_date`, documentado como "LIMITACIÓN CONOCIDA" | el pool único no es FIFO puro | `positions.date` no tiene hora (`schema.py:205`) → las operaciones del mismo día empatan y el desempate lo fija el orden de llegada de la fila | el mismo empate decide **qué moneda paga** y con ella un costo convertido por FX; y `_full_events` (`ORDER BY n.date`) pone los `NULL` primero mientras el persister los pone últimos |
| `snapshots_job.py:243-248` — `_cost_in_usd` documentada como *"Espejo de costInPesos (valuation.js)"* cuando implementa `costInUsd` | — | el "port fiel" del frontend se mantiene a mano | es el mismo mecanismo que dejó **fuera** la rama `costInPesos && !isAR` (DIV-054): nada obliga a que el port siga al original |

---

## Citas del mapa incorrectas

| DIV | cita del mapa | ubicación real | qué decía mal |
|---|---|---|---|
| DIV-062 | `backend/main.py:10584` (`_compute_amort_cost_basis_fifo`) | **`backend/main.py:10549`** | 10584 cae dentro del docstring de `_amortize_position_fifo`; la función citada arranca 35 líneas antes |
| DIV-062 | *"`_compute` ignora las comisiones mientras `_amortize` sí las reduce, así que `cost_basis_consumed` queda sistemáticamente bajo"* | ambas devuelven **el mismo valor** (medido: 200,00) | `_amortize` **reduce** `positions.commissions` pero **no las suma** a `total_invested_dec`. El bug real es que **las dos** excluyen comisiones, y que el `com_taken` desaparece del sistema |
| DIV-052 | `PositionsMobile.jsx:775` | **`PositionsMobile.jsx:652-790`** (`const enriched`); costo-display del modo en **775-786** | 775 es una línea de comentario, no el sitio de cálculo |
| DIV-053 | `backend/behavioral.py:425` | **`backend/behavioral.py:426`** | off-by-one sobre `invested_native = float(p.get("invested") or 0)` |
| DIV-054 | `backend/snapshots_job.py:284-319` / `valuation.js:569-573` | **`snapshots_job.py:283-318`** / **`valuation.js:568-586`** | off-by-one; el rango del frontend se queda corto (la rama completa llega hasta 586) |
| DIV-055 / DIV-056 | `frontend/src/contexts/CurrencyContext.js` / `frontend/src/pages/Positions.js` | **`CurrencyContext.jsx`** / **`Positions.jsx`** | extensión equivocada en la columna "sitios" (la prosa del mapa sí trae `.jsx`) |
| DIV-058 | *"`cost_usd` explícito solo en el libro del asesor"* presentado como una **tercera** fuente | `_advisor_realized_raw` (`main.py:37511`) **despeja `pnl/pct`** y lo publica como `cost_usd` | son **dos** fuentes, no tres: el despeje (front y back) y `entry_price × quantity` del backfill |

**Verificación adicional contra la deriva conocida (`82fad6a0`):** ninguno de los 13 hallazgos toca `backend/pricing/fci.py`, `frontend/src/components/AddPositionFlow.jsx` ni `backend/tests/test_fci_uala.py`. **Nada de este informe está corregido por ese commit.**

---

## URGENTE

Tres cosas ameritan mirarse antes que el resto del grupo. **No toqué una línea de código; esto es diagnóstico.**

**1. `main.py:11310` — `fx_to_usd` sellado en `1.0` con un P&L dividido por otro número.**
En `POST /api/positions/sell-fifo`, si el usuario borra el campo "TC de venta" (es editable y opcional), el P&L se calcula con `fx_for_date(op_date)` pero la fila se estampa con `fx_to_usd = 1.0`. Todo lector que use ese campo para reconstruir el nominal en pesos muestra el número **~1.400× mal**. Es literalmente el bug que `persister.py:806-812` documenta como el que hay que evitar, presente en el tercer motor.

**2. `main.py:11389-11390` — `pnl_for_broker = total_pnl_ars_native / (data.tc_venta or 1)`.**
Mismo disparador: sin `tc_venta`, un P&L de 1.400.000 ARS entra a `monthly_entries` como **1.400.000 USD**. Ese cache alimenta el P&L realizado por broker de Reportes y del Dashboard, y `_repair_monthly_chain` lo propaga hacia adelante.

**3. `snapshots_job.py:283-318` (DIV-054) — costo en pesos contado como dólares en el snapshot.**
Un lote `currency='ARS'` en un broker USD entra al cost basis **sin dividir por el MEP** (≈1.400× inflado), y el guard `_trust_mkt_value` entonces rechaza el precio real y valúa la posición **al costo inflado**. Contamina la curva de evolución, el AUM del libro del asesor, el email diario del asesor y el contexto del Coach IA. Es el hallazgo de mayor impacto por dólar del grupo, y no requiere ninguna acción rara del usuario para dispararse.

Los tres son de una a tres líneas y no dependen de la refactorización grande.

---

## BLOQUE-RESUMEN

| concepto | DIV | versiones | difieren | correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---|---:|---|---|---|---|---|
| Costo de adquisición, costo promedio y lotes FIFO | DIV-050 | 4 | SÍ — medido +120 / +100 / HTTP 400 sobre la misma secuencia (20 % de P&L y 2 nominales fantasma) | ninguna entera; `rebuild._replay_asset` es la base, le falta ordenar el pool por `entry_date, id` | `/posiciones`, `/operaciones`, Dashboard "P&L realizado"; `POST /api/positions/sell-fifo` vs `POST /api/import/confirm` | 🔴 alta | falta de capa compartida + pool único aplicado en un solo motor |
| Costo de adquisición, costo promedio y lotes FIFO | DIV-051 | 2 | SÍ — costo unitario remanente 0,70 vs 0,57 USD/VN (23 %) | `sweep_bond_amortizations` (proporcional) | `/posiciones` → fila de bono amortizante (invertido y P&L del residual) | 🔴 alta | copiar y pegar; el fix currency-aware sólo llegó al sweep |
| Costo de adquisición, costo promedio y lotes FIFO | DIV-052 | 7 | Parcial — cosmética entre los 5 del frontend; real en comisiones y en el modo | `valuation.js:543 valuePositionLot` | Cartera desktop/mobile, `/activo/:ticker`, Dashboard, Insights, Calidad de cartera, snapshots, libro del asesor | 🟠 media-alta | migración a `valuePositionLot` empezada y nunca terminada |
| Costo de adquisición, costo promedio y lotes FIFO | DIV-053 | 2 vs 5 | SÍ — costo subestimado en el 100 % de la comisión de compra (≈0,6 % del costo) | las que suman comisiones (frontend, persister, snapshots) | packets de IA (`position`, `dashboard*`, `insights*`), Coach IA, `/comportamiento` | 🟡 media | el `SELECT` de esos builders no trae la columna `commissions` |
| Costo de adquisición, costo promedio y lotes FIFO | DIV-054 | 2 | SÍ — factor ≈ MEP (1.500× en el ejemplo) sobre ese lote | `valuation.js` (tiene la rama `costInPesos && !isAR`) | Reportes → evolución, `GET /api/advisor/book`, email diario del asesor, contexto del Coach IA | 🔴 alta | "port fiel" mantenido a mano que quedó atrás del original |
| Costo de adquisición, costo promedio y lotes FIFO | DIV-055 | 2 (+5 callers sin el parámetro) | SÍ — 44,7 % con `tc_compra` 1.048 vs MEP 1.517; 8× con compras de 2021 | ninguna: falta que `costBasis` viaje al backend (y a los 5 callers) | Cartera/Dashboard vs Mensual, Metas, Eventos, Calidad de cartera; Reportes, informes del asesor, packets IA, CSV | 🟠 media-alta | feature de frontend (localStorage) sin contraparte de backend |
| Costo de adquisición, costo promedio y lotes FIFO | DIV-056 | 2 en la MISMA fila | SÍ — exactamente por las comisiones: `precio_prom × qty ≠ invertido` siempre | `routedInvUsd` (con comisiones); el promedio debe ser `invertido / cantidad` | `/posiciones` desktop: "Precio prom." vs "Invertido" | 🟠 media-alta | fix de un bug reportado que replicó la fórmula en vez de reusarla |
| Costo de adquisición, costo promedio y lotes FIFO | DIV-057 | 5 | SÍ — 2 excluyen comisiones, 1 no rutea moneda, 1 (`position_lots`) es **código muerto**: `op_type='Compra'` no lo escribe ningún camino de producción | `Σ(invested_i + comm_i)/Σqty_i` ruteada por lote | Cartera desktop/mobile, `/activo/:ticker`, detalle de lote mobile, packets IA `position` y `position.lots` | 🟠 media-alta | copiar y pegar por superficie + suposición nunca verificada sobre el esquema |
| Costo de adquisición, costo promedio y lotes FIFO | DIV-058 | 3 (en realidad 2) | SÍ — el despeje muere cerca del breakeven, con `pct` nulo, y el guard ×10 borra el % de las mejores operaciones | ninguna: hay que persistir `operations.cost_basis_consumed` en las ventas (el motor ya lo calcula y lo tira) | Reportes → "Rendimiento por activo", torta del libro del asesor, `GET /api/advisor/book` | 🟠 media-alta | migración a medio hacer: columna creada, cableada sólo para amortizaciones |
| Costo de adquisición, costo promedio y lotes FIFO | DIV-059 | 1 (contra los 5 FIFO) | SÍ — 33 % en el ejemplo (promedio ponderado 2.000 vs FIFO 3.000) | FIFO (el modelo de la casa): el backfill debería replayar, no promediar | Reportes → evolución, meses cerrados con `source='mtm_backfill'` | 🟡 media | script escrito aparte sin reusar el motor |
| Costo de adquisición, costo promedio y lotes FIFO | DIV-060 | 3 | SÍ — riel BLUE vs MEP: con brecha del 15 %, P&L +166,67 vs +615,38 USD (3,7×) | `persister`/`rebuild` (riel MEP con gate `fx_version`) | `POST /api/positions/sell-fifo` → P&L de la venta manual en `/operaciones`, Dashboard, Reportes | 🟠 media-alta | fix del TC histórico aplicado en 2 de 3 motores |
| Costo de adquisición, costo promedio y lotes FIFO | DIV-061 | 2 (3 con `_full_events`) | SÍ con lotes sin `entry_date`; y **siempre** con el activo en más de un broker (la ficha agrega global, el motor va por `broker_pair`) | el backend (`COALESCE(entry_date,'9999-12-31') ASC, id ASC`), que `GET /api/positions` ya devuelve | `/activo/:ticker` → badge "próximo" de la tabla "Lotes abiertos · orden FIFO" | 🟡 media | el frontend reordena lo que el backend ya ordenó |
| Costo de adquisición, costo promedio y lotes FIFO | DIV-062 | 2 | Entre sí **NO** (medido: las dos devuelven 200,00 — premisa del mapa incorrecta). Pero las dos ignoran comisiones: 20 USD de costo desaparecen de 570 | ninguna: `C = Σ θᵢ(Iᵢ+fᵢ)` proporcional y normalizado a USD | `/posiciones` → bono → "P&L con cupones" y tooltip; `POST /api/bonds/cashflow` → `realized_gain` | 🟠 media-alta | copiar y pegar (dos funciones que son una) sobre un modelo de moneda incompleto; parche `cross_currency_skipped` |
