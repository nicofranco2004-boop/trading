# 1A — Veredicto: P&L realizado

**Grupo:** P&L realizado · 11 divergencias (DIV-081–DIV-091)
**Commit auditado:** b74f450f (`/tmp/rendi-main`, `backend/main.py` = 38.029 líneas ✅)
**Citas verificadas:** 36 de 41 correctas · 5 corregidas
**Deriva `82fad6a0`:** ningún hallazgo de este grupo toca `backend/pricing/fci.py`, `frontend/src/components/AddPositionFlow.jsx` ni `backend/tests/test_fci_uala.py`. No hay solapamiento.

---

## Resumen ejecutivo

La hipótesis del mapa se confirma y se queda corta. No hay **dos** definiciones de "P&L realizado": hay **una columna polimórfica** (`operations.pnl_usd`) que guarda cuatro cosas distintas —resultado de una venta, cash de un dividendo, cash bruto de una amortización, y ganancia cambiaria de una conversión— en **dos monedas distintas**, y encima de ella hay dos universos de filtrado (uno que suma todo, otro que excluye renta y conversiones) y cuatro tratamientos incompatibles de la amortización de bonos.

Lo que el usuario ve mal, hoy, en producción:

1. **🔴 La IA recibe el P&L realizado de por vida EXACTAMENTE DUPLICADO.** `RendiAI.jsx:170` y `AICoachDrawer.jsx:177` suman `pnl_realized` de **todas** las filas de `GET /api/monthly`, que incluye la fila sintética `broker='global'` **más** las por-broker. `Dashboard.jsx:242` hace el mismo cálculo tres líneas más arriba **con** el `.filter(m => m.broker === 'global')`. El campo se llama `realized_pnl_usd_lifetime` y viaja en el contexto de cada mensaje del chat (DIV-090).
2. **🔴 Una amortización de bono cargada a mano se contabiliza como 100% ganancia** (`main.py:10484` guarda `net_amount` entero como `pnl_usd`). La ganancia real —`net_amount − cost_basis_consumed`— se calcula tres líneas después (`main.py:10508`) y **se tira**: sólo viaja en la respuesta HTTP. Como `capital_final = capital_inicio + deposits − withdrawals + pnl_realized`, esto **infla la cadena contable mensual de forma permanente** y con ella el TWR (DIV-083).
3. **🔴 `Interés PF` se escapa de todos los filtros y de toda conversión.** No está en `_NOT_A_TRADE` ni en `_NATIVE_CCY_OPS` (`realized_pnl.py:74,78`), y nace con `fx_to_usd=NULL` cuando el plazo fijo es en pesos (`main.py:9315`). Un PF de $10M al 40% durante 30 días entra como **US$328.767** de ganancia realizada y como **una operación cerrada ganada** en los seis win rates (DIV-084).
4. **🔴 Cinco pantallas leen `pnl_usd` crudo.** `GET /api/operations` es `SELECT *` (`main.py:12384`) — devuelve la columna sin convertir. Diagnóstico, Detalle de activo y el detalle mobile de posición muestran un cupón de $125.000 como **US$125.000** (DIV-087).
5. **🟠 El card "P&L realizado" de Reportes se contradice a sí mismo**: el monto viene del universo A (con dividendos y ganancia cambiaria), el subtítulo "N ops cerradas" del universo B (DIV-082).

Orden de magnitud de la desviación: **×2** exacto en el número que consume la IA; **+cost_basis** por cada amortización manual; **×1.250** por cada plazo fijo en pesos y por cada cupón legacy leído en la pantalla equivocada.

---

## Tabla de veredictos

| DIV | versiones | ¿difieren de verdad? | cuál es la correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---:|---|---|---|---|---|
| **DIV-081** | 2 universos × 6 sitios | **REAL** — difieren en dividendos + intereses + FX de conversiones | Ninguna: falta separar `trade_pnl` / `income` / `fx_pnl` | `/analisis?tab=reportes`, `/dashboard`, chat IA | 🔴 alta | falta de capa compartida: `realized_pnl.py` unificó la CONVERSIÓN pero no el UNIVERSO |
| **DIV-082** | 1 card, 2 universos | **REAL** — monto ≠ denominador del subtítulo | `builder.py:1655` + `1659` deben salir del mismo universo | `/analisis?tab=reportes` (KPI "P&L realizado") | 🟠 media-alta | DIV-081 hecha visible en un solo componente |
| **DIV-083** | 4 tratamientos | **REAL** — 0, gross, gross−cost, y FIFO real | La 3ª (`Venta` FIFO del importador) y `Positions.jsx:544` | `/dashboard`, `/analisis?tab=reportes`, `/mensual`, chat IA | 🔴 alta | fix aplicado en un solo lugar (el frontend) + número correcto calculado y descartado |
| **DIV-084** | 3 clasificaciones de `Interés PF` | **REAL** — trade cerrado ganado + sin convertir vs. renta | Ninguna: `Interés PF` debe ser renta y estar en `_NATIVE_CCY_OPS` | todas las que leen realized + los 6 win rates | 🔴 alta | migración a medio hacer: se agregó un op_type nuevo sin tocar el módulo canónico |
| **DIV-085** | 8 copias del filtro, 2 listas | **REAL** — sólo en filas con `op_type=''` | `realized_pnl.is_closed_op` (incluye `''`) | `/analisis?tab=reportes` cuenta ops que la IA no cuenta | 🟡 media | copiar y pegar; `realized_pnl.py` existe pero 5 sitios no lo importan |
| **DIV-086** | 6 win rates, 2 denominadores | **REAL** — ~12 puntos de spread con ceros y cupones | Ninguna: hay que sacar renta del universo (decisión de producto) | `/operaciones` 71% vs `/analisis?tab=diagnostico` 83% | 🟠 media-alta | copiar y pegar + el propio módulo lo documenta como "Pendiente #1" sin cerrar |
| **DIV-087** | 5 lectores crudos vs 3 convertidos | **REAL** — ×fx (≈1.250) en cupones/amortizaciones ARS | Convertir en el endpoint, no en cada lector | `/analisis?tab=diagnostico`, `/activo/:ticker`, `/posiciones/:id` | 🔴 alta | frontend recalculando lo que el backend debería entregar ya normalizado |
| **DIV-088** | 1 pantalla infiere FX prohibido | **REAL** — 1.250× más chico en bonos USD con `currency` NULL | `realized_pnl.py:24-32` (no inferir) | `/posiciones` (zona renta fija, "Ya cobraste") | 🟠 media-alta | PARCHE local que contradice una política escrita |
| **DIV-089** | 2 fórmulas en la misma columna | **REAL** — universo A convertido vs universo B crudo | La del backend (`entry.pnl_realized`) | `/posiciones` (teaser mensual, `MonthlyTeaser`) | 🟡 media | fallback improvisado en el navegador cuando falta la fila |
| **DIV-090** | 1 sitio, doble conteo | **REAL** — ×2 exacto | `Dashboard.jsx:242-244` (con `.filter(broker==='global')`) | chat IA (`/ai` y el drawer, en toda la app) | 🔴 alta | copiar y pegar que perdió el `.filter` |
| **DIV-091** | doc ≠ impl en 3 packets | **REAL** — el `_field_docs` miente al modelo | Los docs describen el universo B; el valor es A | packets `monthly` y `reports` del chat IA | 🟠 media-alta | documentación escrita sobre la intención, no sobre el código |

---

## Detalle por divergencia

### DIV-081 — Dos universos con el mismo nombre

**Estado de las citas:** ✅ verificadas las 5.
`builder.py:842` ✅ · `main.py:25412` ✅ · `insights.py:286` ✅ · `insights_attribution.py:70` ✅ · `operations.py:53` ✅ (la línea apunta a `realized_usd_sql()` dentro del SELECT; el filtro de universo está en `:42` y `:60` — la cita es válida pero incompleta).

#### a. Implementaciones

**A-1 · `backend/reporting/builder.py:842`** (embudo de todo Reportes)
```python
842:    realized = sum(float(o.get("pnl_usd") or 0) for o in ops)
```
`ops` sale de `fetch_operations_in_range` (`builder.py:218-247`). Verificado: esa query **no tiene ningún filtro de `op_type`** —pese a que su docstring dice "Operations cerradas (Venta, Dividendo, Interés, Futuros)"— y **sí** aplica `realized_usd_sql()`. O sea: **convierte pero no filtra**.

**A-2 · `backend/main.py:9517-9538`** (`_recalc_pnl_realized_from_ops`, escritor de `monthly_entries.pnl_realized`)
```sql
SELECT COALESCE(SUM( <realized_usd_sql('o')> ), 0) AS s FROM operations o
 WHERE o.user_id=? AND strftime('%Y',o.date)=? AND strftime('%m',o.date)=? [AND o.broker=?]
```
Idem: convierte, no filtra. El comentario de la línea 9517 lo llama "ÚNICA fuente autoritativa".

**B-1 · `backend/realized_pnl.py:85-94`** (`closed_filter_sql`)
```sql
pnl_usd IS NOT NULL
AND op_type NOT IN ('Compra','Dividendo','Interés','')
AND op_type NOT LIKE 'CONVERSION%'
AND op_type NOT LIKE 'Conversión%'
```
Consumido por `main.py:25412` (tool IA `get_realized_vs_unrealized`), `insights.py:288`, `insights_attribution.py:70`, `operations.py:42`.

#### b. Fórmulas

Sea `O` el conjunto de filas de `operations` del usuario en el período, y para cada fila `o`:

- `p(o)` = `o.pnl_usd` crudo
- `c(o)` = `realized_usd(o)` = `p(o)/fx(o)` si `type(o) ∈ {Cupón, Amortización} ∧ ccy(o)='ARS' ∧ fx(o)>0`; si no, `p(o)`

**Universo A** (Reportes, `monthly_entries`, Dashboard, packets `monthly`/`reports`):

    R_A = Σ_{o ∈ O}  c(o)

**Universo B** (tool IA, packets `insights`/`operations`/`attribution`):

    R_B = Σ_{o ∈ O : type(o) ∉ {Compra, Dividendo, Interés, ''} ∧ type(o) ∤ CONVERSION*}  c(o)

    R_A − R_B = Σ dividendos + Σ intereses + Σ ganancia cambiaria de conversiones

Verificado que las conversiones **sí** llevan `pnl_usd` no nulo: `main.py:10958-10970` inserta `op_type='CONVERSION {kind} USDT→ARS'` con `pnl_usd = round(pnl_usd_realized, 2)`. Idem el importador en `persister.py:1178-1186`.

#### c. ¿Real o cosmética? — **REAL**

Mes de septiembre de un usuario tipo:

| evento | `op_type` | `pnl_usd` | ¿en A? | ¿en B? |
|---|---|---:|:-:|:-:|
| venta AAPL | `Venta` | +1.000 | ✅ | ✅ |
| 5 dividendos VOO | `Dividendo` | +300 | ✅ | ❌ |
| venta de US$ a $ con ganancia | `CONVERSION FX USDT→ARS` | +200 | ✅ | ❌ |
| cupón AL30 ($125.000, fx 1.250) | `Cupón` | 125.000 → **100** | ✅ | ✅ |
| amortización AL35 manual (cash US$5.000, costo US$4.000) | `Amortización` | +5.000 | ✅ | ✅ |

- **R_A = 6.600** → lo que muestra Reportes, lo que guarda `monthly_entries`, lo que suma el Dashboard.
- **R_B = 6.100** → lo que le contesta la IA si el usuario pregunta "¿cuánto gané realizado?".
- **Diferencia: US$500 (8,2%)** en un mes cualquiera; en una cartera de renta el gap es el número dominante: el propio código mide (`main.py:37422-37424`) **US$10.972 de dividendos + US$9.695 de intereses contra US$2.652 de ventas** — ahí A ≈ **8×** B.

#### d. Dictamen

**Ninguna de las dos es correcta.** Son dos preguntas legítimas con un solo nombre:

- `R_A` es la **identidad contable** que necesita `capital_final = capital_inicio + dep − wit + pnl_realized`. Si le sacás los dividendos, la cadena mensual deja de cerrar. Por eso `_recalc` tiene razón en sumar todo.
- `R_B` es el **resultado de tus decisiones de trading**, que es lo que el usuario lee bajo "P&L realizado".

El error es que las dos se llamen igual y se publiquen indistintamente. La fórmula correcta es una **descomposición**, no una elección:

    trade_pnl  = Σ sobre {Venta, Futuros}                      (proceeds − costo)
    income     = Σ sobre {Dividendo, Interés, Interés PF, Cupón, Renta}
    fx_pnl     = Σ sobre {CONVERSION*}
    cap_return = Σ sobre {Amortización} ∩ cost_basis_consumed   (NO es resultado)

    realized_contable = trade_pnl + income + fx_pnl        ← para capital_final
    "P&L realizado" (KPI de pantalla) = trade_pnl          ← para el usuario

#### e. Qué ve mal el usuario y dónde

| superficie | ruta / endpoint | qué publica |
|---|---|---|
| Reportes, KPI "P&L realizado" | `/analisis?tab=reportes` ← `GET /api/reports/period/{type}/{key}` (`main.py:33136`) | R_A rotulado como trades cerrados |
| Dashboard, "P&L realizado" acumulado | `/dashboard` ← `GET /api/monthly` | R_A |
| Chat IA, tool `get_realized_vs_unrealized` | `POST` del chat → `main.py:25384` | R_B |
| Chat IA, packet `insights.realized_pnl_usd` | `insights.py:323` | R_B |
| Chat IA, packet `reports.realized_pnl_year_usd` | `reports.py:97` | R_A |

**El mismo request de chat puede llevar R_A y R_B a la vez.** Con los números del ejemplo del código real: el usuario ve +US$20.000 en Reportes y el modelo, en la misma conversación, tiene un campo que dice 2.652.

#### f. Causa raíz

**Falta de una capa compartida de cálculo, a medio construir.** `backend/realized_pnl.py` se creó (docstring, líneas 1-8) exactamente por este problema, pero unificó **sólo la conversión de moneda** (`realized_usd_sql`) y dejó el **universo** (`closed_filter_sql`) opcional: los dos escritores canónicos (`builder.py:842` y `main.py:9517`) importan el primero y no el segundo. El módulo lo dice él mismo en su "Pendiente #1" (`realized_pnl.py:34-53`): decidir si los cupones son trades "es decisión de producto, no una conversión". Esa decisión nunca se tomó, y mientras tanto los dos universos siguen publicándose con el mismo rótulo.

#### g. Fuente única de verdad

`backend/realized_pnl.py` debe exponer una **clasificación** (`bucket(op_type) → trade | income | fx | capital_return | flow`) y un `decompose_sql(prefix)` que devuelva las cuatro columnas. Eliminar: el `sum()` pelado de `builder.py:842` (pasa a `trade_pnl + income + fx_pnl`, con los tres campos en `PeriodMetrics`), y el `_is_trade` local de `builder.py:845` y `1778`.

---

### DIV-082 — El card que se contradice a sí mismo

**Estado de las citas:** ✅ `Reports.jsx:560-566` verificada literal.

#### a. Implementaciones

**`frontend/src/pages/Reports.jsx:560-566`**
```jsx
560:  if (m.realized_pnl != null && (m.realized_pnl !== 0 || m.trades_count > 0)) {
561:    kpis.push({
562:      label: 'P&L realizado',
563:      value: `${m.realized_pnl >= 0 ? '+' : '−'}US$ ${fmtNum(Math.abs(m.realized_pnl))}`,
564:      sub: m.trades_count != null ? `${m.trades_count} op...cerrada...` : 'operaciones cerradas',
```
Las dos mitades del card salen de `PeriodMetrics` (`builder.py:1649-1662`), verificado:
```python
1655:        realized_pnl=round(realized, 2),      # ← línea 842: TODAS las filas
1659:        trades_count=len(trade_ops),          # ← línea 853: filtradas por _is_trade
```

#### b. Fórmulas

    valor    = R_A                                            (universo A)
    subtítulo = |{o ∈ O : type(o) ∉ {Compra,Dividendo,Interés} ∧ type(o) ∤ Conversión* ∧ p(o) ≠ NULL}|   (universo B)

#### c. ¿Real o cosmética? — **REAL**

Con el mes del ejemplo de DIV-081: `trade_ops` = {venta, cupón, amortización} = **3**; `realized` = **6.600**.
El card dice literalmente: **"+US$ 6.600 · 3 ops cerradas"**, cuando de esos 6.600 hay 500 que no vinieron de ninguna de las 3 operaciones.

Caso degenerado y frecuente en carteras de renta fija/CEDEARs: **0 ventas, 5 dividendos de US$300**. `trade_ops = 0` → `trades_count = 0`, `realized = 300`. La condición de la línea 560 pasa (`realized_pnl !== 0`), y el card publica **"+US$ 300 · 0 ops cerradas"**.

Lo mismo aparece en el subheadline autogenerado del informe, `builder.py:2018-2023`:
```python
2022:  f"Cerraste {metrics.trades_count} operación{...}"
2023:  f"{wr_str}, sumando US$ {metrics.realized_pnl:+,.0f} de P&L realizado."
```
Una frase que afirma que N operaciones "sumaron" un monto que N operaciones no sumaron.

#### d. Dictamen

Ninguna es correcta por separado; el card debe leer del **mismo universo** en las dos mitades. Aplicando la descomposición de DIV-081: valor = `trade_pnl`, subtítulo = `trades_count`, y la renta va a un card propio ("Renta cobrada · N cupones/dividendos"), que además es información que hoy el usuario no tiene en ningún lado de Reportes.

#### e. Qué ve mal el usuario y dónde

`/analisis?tab=reportes`, KPI "P&L realizado" — en las 4 pestañas (día/semana/mes/año) y en el informe público `/i/:token` (`main.py:36005`), que es el que el asesor le manda al cliente.

#### f. Causa raíz

Es **DIV-081 hecha visible**: el frontend no inventó nada, sólo pintó juntos dos campos del mismo objeto `metrics` que ya venían de universos distintos.

#### g. Fuente única de verdad

Misma que DIV-081. Sin cambiar el frontend: si `PeriodMetrics.realized_pnl` pasa a ser `trade_pnl`, el card queda consistente solo.

---

### DIV-083 — Cuatro tratamientos de la amortización de bono 🔴

**Estado de las citas:** ✅ `main.py:10484` verificada literal · ✅ `persister.py:980` verificada literal · ✅ `Positions.jsx:540-549` (el bloque real es 539-551).

#### a. Implementaciones

**T-1 · Manual — `backend/main.py:10478-10500`** (`POST /api/bonds/cashflow`)
```python
10478:            conn.execute(
10479:                """INSERT INTO operations (user_id, date, broker, asset, op_type,
10480:                   pnl_usd, commissions, notes, currency, fx_to_usd, cost_basis_consumed,
10481:                   undo_meta_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
10483:                (uid, data.date, data.broker, data.asset.upper(), op_type,
10484:                 net_amount, commissions, ...,  cost_basis_consumed, ...
```
`op_type` sale de `main.py:10372`: `'Cupón' if flow_type=='coupon' else 'Amortización'`.
Y tres líneas más abajo, el número correcto — calculado y **descartado**:
```python
10504:        # Ganancia realizada del amort (sólo para diagnóstico / response):
10506:        realized_gain = None
10507:        if data.flow_type == 'amortization' and cost_basis_consumed is not None:
10508:            realized_gain = round(net_amount - cost_basis_consumed, 6)
```
`realized_gain` sólo sale en el JSON de respuesta (`main.py:10522`). No se persiste en ningún lado.

**T-2 · Importador sin cantidad — `backend/importing/persister.py:975-997`**
```python
975:    if is_amort:
976:        op_label = "Amortización"
979:    amount_usd = (amount / tc_blue) if currency == "ARS" else amount
980:    pnl_usd = 0.0 if is_amort else round(amount_usd, 2)
...
993:    #    La amortización NO suma: es capital que vuelve, no ganancia.
994:    if not is_amort:
996:        helpers._update_monthly_pnl_realized(conn, uid, tx.broker, y, m, amount_usd)
```
La detección es `_is_amort_capital_return` (`persister.py:904-935`): `op_type ∈ {DIVIDEND, INTEREST}` **y** `"amortiz" ∈ notes.lower()` **y** el activo es bono.

**T-3 · Importador con cantidad — `persister.py:787-824`**
La fila llega como SELL con `quantity`, cae en el persister de venta y produce `op_type='Venta'` con `pnl_usd = (exit_price × take) − cost − commission` (`persister.py:799`). **Es el único de los cuatro que da la ganancia real.**

**T-4 · Frontend — `frontend/src/pages/Positions.jsx:539-551`**
```jsx
539:      // Aporte al P&L: cupones = 100%; amorts = sólo la ganancia realizada.
540:      let pnlContrib = amt
541:      if (op.op_type === 'Amortización') {
542:        const cbConsumed = op.cost_basis_consumed
543:        if (cbConsumed != null && cbConsumed >= 0) {
544:          pnlContrib = amt - cbConsumed
545:        } else {
549:          pnlContrib = 0
```

#### b. Fórmulas

Amortización de face `F` con cash neto `C` y costo FIFO consumido `K`:

    T-1 (manual):              pnl = C
    T-2 (import sin qty):      pnl = 0
    T-3 (import con qty):      pnl = C − K            ✅
    T-4 (Positions.jsx):       pnl = C − K  si K≠NULL;  0  si K=NULL

#### c. ¿Real o cosmética? — **REAL, y contamina la cadena contable**

Ejemplo del propio comentario del código (`Positions.jsx:491-493`): AL30 comprado a 70, amortización de **US$76,92** con `cost_basis_consumed = US$53,84`.

| | pnl registrado | error vs. real (23,08) |
|---|---:|---:|
| T-1 manual | **76,92** | **+233 %** |
| T-2 import sin qty | 0,00 | −100 % |
| T-3 import con qty | 23,08 | ✅ |
| T-4 Positions.jsx | 23,08 | ✅ |

Pero el daño de T-1 no termina en el card. La amortización **también decrementa la posición** (`_amortize_position_fifo`, `main.py:10460`), o sea baja `invested` en 53,84. Y `_recalc_pnl_realized_from_ops` (`main.py:9667`) reconstruye:

    capital_final = capital_inicio + deposits − withdrawals + pnl_realized

Con T-1, `pnl_realized` sube 76,92 mientras el valor real de la cuenta sólo subió 23,08 (el cash entró 76,92 pero la tenencia bajó 53,84). **`capital_final` queda inflado en exactamente `K` = 53,84, y ese error se hereda como `capital_inicio` del mes siguiente y de todos los que sigan.** Es el mismo mecanismo que la "Diferencia sin explicar" que `Dashboard.jsx:278-280` ya describe como síntoma sin nombrarle esta causa.

Un usuario con un AL30 de US$10.000 nominal que amortiza durante 3 años acumula ~US$7.000 de `capital_final` fantasma y un TWR anual proporcionalmente inflado.

**Nota temporal adicional:** `POST /api/bonds/cashflow` **no llama** a `_recalc_pnl_realized_from_ops`. Verificado: los 12 call sites (`main.py:4495, 12370, 12925, 13879, 13946, 15705, 20252, 30930, 31089, 31732, 32326`) son de import/revert/delete/backfill. Consecuencia: Reportes (que lee `operations` directo vía `builder.py:842`) muestra el monto **en el acto**, y el Dashboard (que lee `monthly_entries`) recién **después del próximo import o borrado**. El mismo usuario ve dos números durante días.

#### d. Dictamen

**T-3 es la correcta** (y T-4 la refleja bien). Una amortización es una venta parcial a la par: `resultado = cash − costo consumido`, y el resto es devolución de capital que ya está contada en `invested`.

T-1 debe persistir `realized_gain` (que **ya calcula**, línea 10508) en `pnl_usd`, y `net_amount` pasar a una columna de cash bruto (`quantity` ya está libre en esa fila) — o marcarse con un `op_type` que la clasificación de DIV-081 mande a `cap_return`.

T-2 es un **PARCHE**: `0.0` no es la ganancia, es "no sé calcularla". Debería llamar a `_compute_amort_cost_basis_fifo` como hace el flujo manual, en vez de renunciar. Y deja un efecto colateral: la fila queda con `pnl_usd = 0.0` (**no NULL**), que pasa `closed_filter_sql` y entra al denominador de los seis win rates como "trade ni ganado ni perdido".

#### e. Qué ve mal el usuario y dónde

| superficie | qué ve |
|---|---|
| `/dashboard` — "P&L realizado" y "Diferencia sin explicar" | ganancia inflada en `K` por amortización manual |
| `/analisis?tab=reportes` — KPI + informe público `/i/:token` | idem, y en el mes equivocado hasta el próximo recalc |
| `/mensual` — `capital_final` de cada mes | cadena inflada acumulativa |
| chat IA (`get_realized_vs_unrealized`, packets) | idem, `Amortización` pasa el filtro |
| `/posiciones` — "P&L con cupones" | **correcto** (T-4) → contradice a las cuatro de arriba en la misma sesión |

#### f. Causa raíz

**Fix aplicado en un solo lugar.** El diagnóstico correcto existe, está escrito en prosa en `Positions.jsx:481-493`, e implementado sólo ahí. El backend calculó el número correcto (`realized_gain`) y no lo guardó — quedó como "sólo para diagnóstico / response" (comentario de la línea 10504). Es el patrón exacto que `realized_pnl.py:2-4` describe para el bug anterior: *"se arregló en uno solo y los otros tres siguieron mintiendo"*.

#### g. Fuente única de verdad

La escritura, en `POST /api/bonds/cashflow` y en `_persist_dividend_or_interest`: ambas deben guardar `pnl_usd = net_amount − cost_basis_fifo` y `cost_basis_consumed` siempre. Con eso, `Positions.jsx:539-551` se puede borrar entero (queda `pnlContrib = amt`) y los 4 lectores del backend quedan bien sin tocarlos.

⚠️ **Un backfill de las filas ya escritas es obligatorio**, o el fix sólo detiene la sangría sin reparar `capital_final`.

---

### DIV-084 — `Interés PF` se escapa de todo 🔴

**Estado de las citas:** ✅ `realized_pnl.py:74` · ✅ `main.py:9315` · ⚠️ **`main.py:37504` corregida → `main.py:37503`** (37504 es el comentario; el `if` con `"INTER"` está en 37503) · ✅ `assetPnl.js:202`.

#### a. Implementaciones

**Escritor · `backend/main.py:9312-9322`**
```python
9312:        if interes > 0:
9314:            moneda = (row["moneda"] or "ARS").upper()
9315:            fx = 1.0 if moneda in ("USD", "USDT") else None
9316:            conn.execute(
9317:                """INSERT INTO operations
9318:                       (user_id, date, broker, asset, op_type, pnl_usd, currency, fx_to_usd, notes)
9319:                   VALUES (?, ?, ?, ?, 'Interés PF', ?, ?, ?, ?)""",
9321:                 row["banco"], interes, moneda, fx, ...)
```
Verificado: para un PF en pesos, `moneda='ARS'` y **`fx_to_usd = None`**. `interes` viene de `_pf_value(row)["interes_hoy"]` — **en pesos**.

**Clasificador canónico · `backend/realized_pnl.py:74,78`**
```python
74: _NOT_A_TRADE = ('Compra', 'Dividendo', 'Interés', '')
78: _NATIVE_CCY_OPS = ('Cupón', 'Amortización')
```
`'Interés PF' ∉ _NOT_A_TRADE` (es distinto de `'Interés'`, no hay `startswith`) y `'Interés PF' ∉ _NATIVE_CCY_OPS`.

**Clasificadores por substring (los únicos que aciertan)**
- `frontend/src/utils/assetPnl.js:200-202`: `tipo.includes('INTER')` → renta ✅
- `backend/main.py:37503`: `if "DIVIDENDO" in tipo or "INTER" in tipo or "CUPON" in tipo:` → `income_usd` ✅

#### b. Fórmulas

Para una fila `Interés PF` de un PF en pesos con interés `I` (pesos) y MEP del día `m`:

    valor real                        = I / m
    closed_filter_sql                 → la fila PASA  (cuenta como trade cerrado)
    realized_usd_sql                  → CASE ... ELSE pnl_usd  →  I     (sin convertir)
    monthly_entries.pnl_realized      += I                      (pesos leídos como USD)
    is_closed_op('Interés PF')        → True
    win rate: pnl > 0 siempre         → +1 ganada, +1 al denominador
    assetPnl.js / main.py:37503       → income_usd += I   (bien clasificado, mal convertido)

#### c. ¿Real o cosmética? — **REAL, ×1.250 y contagia el win rate**

PF de **$10.000.000** al 40% TNA durante 30 días → `interes ≈ $328.767`. MEP ≈ 1.250 → valor real **US$263**.

| lector | qué publica |
|---|---|
| `monthly_entries.pnl_realized` / Dashboard | **+US$328.767** |
| Reportes (`builder.py:842`) | **+US$328.767** |
| tool IA `get_realized_vs_unrealized` | **+US$328.767** (pasa el filtro) |
| win rate `builder.py:856` / `timeline.py:77` / `behavioral.py:898` | **+1 operación ganada** |
| `Insights.jsx` profit factor | `grossWin += 328.767` → profit factor ≈ ∞ |
| `capital_final` del mes | inflado en US$328.504 |

Un solo plazo fijo en pesos, de tamaño perfectamente normal para Argentina, **borra el P&L real de la cuenta entera** en cinco pantallas y en el chat.

**Doble falla, no una:** aunque alguien agregue `'Interés PF'` a `_NATIVE_CCY_OPS`, la conversión **igual no ocurriría**, porque `realized_usd_sql` exige `fx_to_usd > 0` y la línea 9315 lo deja en `NULL`. Hay que arreglar las dos puntas.

**Riesgo hermano no citado por el mapa:** `'Renta'` aparece como `op_type` de renta fija en tres filtros de lectura (`main.py:14528`, `14666`, `14889`) y en `_CASHLIKE` (`main.py:35793`), pero **tampoco** está en `_NOT_A_TRADE` ni en `_NATIVE_CCY_OPS`. Lo mismo para las variantes sin acento `'Cupon'` y `'Amortizacion'`, que esos mismos cuatro filtros contemplan explícitamente (o sea: alguien creyó que existen en datos legacy) y que `_NATIVE_CCY_OPS` **no** matchea. Cada una de esas filas es un cupón sin convertir.

#### d. Dictamen

Ninguna implementación es correcta. La fórmula correcta:

1. `'Interés PF'` es **renta** → debe ir a `_NOT_A_TRADE` (o al bucket `income` de DIV-081).
2. Debe estar en `_NATIVE_CCY_OPS`, porque guarda moneda nativa igual que un cupón.
3. `main.py:9315` debe sellar el MEP de la fecha con `_fx.fx_for_date_detail(conn, fecha)` — exactamente lo que ya hace `bond_cashflow` en `main.py:10419`, doce mil líneas más abajo, para el mismo problema.
4. La clasificación debe ser por **prefijo/pertenencia a un conjunto**, no por igualdad exacta ni por substring: la igualdad exacta pierde `Interés PF`, y el substring `'INTER'` es frágil (matchearía `INTERNACIONAL`).

El propio módulo lo tiene anotado como "Pendiente #3" (`realized_pnl.py:61-68`) con la nota *"Hoy no muerde (0 filas en producción)"* — fechada 2026-08-18. El endpoint que las crea (`main.py:9280`) está vivo.

#### e. Qué ve mal el usuario y dónde

`/dashboard` (P&L realizado, Diferencia sin explicar) · `/analisis?tab=reportes` (KPI + win rate + informe público) · `/analisis?tab=diagnostico` (win rate, profit factor, activo estrella) · `/analisis?tab=comportamiento` (card "win rate vs payoff") · `/mensual` (capital_final) · chat IA. **Correcto sólo** en las tortas de composición (`assetPnl.js:202` y `main.py:37503`), que lo llaman renta — aunque con el monto en pesos igual.

#### f. Causa raíz

**Migración a medio hacer.** Se agregó un `op_type` nuevo (`Interés PF`) sin registrarlo en el módulo que centraliza la clasificación. El módulo canónico lo detectó, lo documentó como pendiente, y siguió. El diseño que lo permite es que `_NOT_A_TRADE` sea una **lista de exclusión** (default = "es un trade"): cualquier `op_type` nuevo entra a P&L realizado por omisión.

#### g. Fuente única de verdad

`realized_pnl.py` debe pasar de lista de exclusión a **mapa exhaustivo de clasificación** con `default = raise` (o `unknown`, loggeado): un `op_type` que nadie clasificó nunca debe caer en "trade cerrado ganado" por descuido. Y `main.py:9315` debe reusar `_fx.fx_for_date_detail`.

---

### DIV-085 — Ocho copias del filtro de trades, dos listas distintas

**Estado de las citas:** ✅ `realized_pnl.py:74` · ✅ `behavioral.py:66` · ⚠️ **`reports.py:101` corregida → `reports.py:105`** · ✅ `builder.py:847` · ✅ `builder.py:1780` · ⚠️ **`timeline.py:69` corregida → `timeline.py:70`** · ✅ `tradeStats.js:31`.

#### a. Implementaciones — inventario completo verificado

| # | ubicación | `''` excluido | conversión aplicada | consumidor |
|---|---|:-:|:-:|---|
| 1 | `backend/realized_pnl.py:74` (`_NOT_A_TRADE`) | ✅ | ✅ | tool IA, `insights`, `attribution`, `operations` |
| 2 | `backend/behavioral.py:66` (`_is_trade`) | ✅ | ✅ (`behavioral.py:1841`) | Comportamiento, 12 detectores |
| 3 | `backend/ai/builders/reports.py:105` (SQL `trades_year`) | ✅ | n/a (sólo `COUNT`) | packet `reports` |
| 4 | `backend/reporting/builder.py:847` | ❌ | ✅ (en el `fetch`) | Reportes: realized, win rate, drivers |
| 5 | `backend/reporting/builder.py:1780` | ❌ | ✅ | `compute_highlights` (mejor/peor op) |
| 6 | `backend/reporting/timeline.py:70` | ❌ | **❌ crudo** | win rate lifetime |
| 7 | `backend/reporting/timeline.py:87` (SQL) | ❌ | n/a | trades/mes promedio |
| 8 | `backend/ai/builders/profile_card.py:94` | ✅ (vía `if not t: return False`) | n/a | card perfil de inversor |
| 9 | `frontend/src/utils/tradeStats.js:31` | ❌ | ❌ (crudo) | `/operaciones` |
| 10 | `frontend/src/pages/Insights.jsx:1881-1887` | ✅ | ❌ | `/analisis?tab=diagnostico` |
| 11 | `frontend/src/hooks/useMonthlyData.js:48-54` | ✅ | ❌ | `MonthlyTeaser` |
| 12 | `frontend/src/utils/profileMatch.js:446-452` | ✅ | n/a | perfil de inversor |

**Doce**, no seis. Sólo 4 de las 12 importan el módulo canónico.

#### b. Fórmulas

    Lista L1 (canónica):  {Compra, Dividendo, Interés, ''}
    Lista L2 (copias):    {Compra, Dividendo, Interés}

    diff(L1, L2) = filas con op_type = ''  →  L2 las cuenta como TRADE CERRADO

#### c. ¿Real o cosmética? — **REAL pero acotada**

Una fila con `op_type=''` y `pnl_usd = 500`:
- `realized_pnl.is_closed_op('')` → `False` → la IA la ignora.
- `builder._is_trade({'op_type':''})` → `''` no está en la tupla, no arranca con `Conversión` → **`True`** → Reportes la cuenta como operación cerrada, la incluye en `trades_count`, en `wins`, y la puede elegir como "Mejor operación" del período (`builder.py:1786-1795`).

La divergencia se mide en **cantidad de filas con `op_type` vacío**, que no puedo contar sin acceso a datos. Su existencia está reconocida por el propio `realized_pnl.py:73` (*"`''` cubre las filas con op_type vacío"*) — la lista canónica se escribió con el `''` a propósito, o sea alguien las vio.

Aparte del universo, hay una divergencia de **conversión** más seria en las copias 6 y 9: leen `pnl_usd` crudo. Para el **signo** (win/loss) da igual (dividir por un `fx>0` no cambia el signo), pero `timeline.py` y `tradeStats.js` quedan como la única puerta por donde un valor nativo podría filtrarse a una magnitud — hoy no lo hacen porque sólo cuentan.

#### d. Dictamen

**`realized_pnl.is_closed_op` (copia 1) es la correcta**: incluye `''` explícitamente y es la única testeada (`backend/tests/test_realized_pnl_cupon.py:74` prueba `("Compra","Dividendo","Interés","",None,...)`).

#### e. Qué ve mal el usuario y dónde

`/analisis?tab=reportes`: `trades_count`, `win_rate`, "Mejor/Peor operación" y `realized_pnl` cuentan filas que la IA, en el mismo momento, no cuenta. `/operaciones` (tradeStats) las cuenta también.

#### f. Causa raíz

**Copiar y pegar.** `tradeStats.js:3-5` lo confiesa: *"Espejo literal de backend/reporting/builder.py:352-363"*, y `tradeStats.js:13-22` enumera las otras copias vivas y termina con *"Antes de agregar un cuarto, migrá esos"*. Se agregaron más. El módulo canónico existe desde 2026-08 pero **`reporting/` nunca lo importó para el filtro** (sólo para la conversión).

⚠️ **Cita del mapa a corregir dentro del propio código:** `tradeStats.js:3` dice "espejo de `builder.py:352-363`". En este commit el `_is_trade` de `builder.py` está en **845-851** y el win rate en **853-856**. La línea 352 no tiene nada de eso.

#### g. Fuente única de verdad

`realized_pnl.is_closed_op` / `closed_filter_sql`. Eliminar: `builder.py:845-851`, `builder.py:1778-1784`, `timeline.py:68-73`, `timeline.py:87-89`, `behavioral.py:63-71`, `profile_card.py:91-98`, y del lado del frontend dejar sólo `tradeStats.esTradeCerrado` (borrando los predicados de `Insights.jsx:1881`, `useMonthlyData.js:48` y `profileMatch.js:446`).

---

### DIV-086 — Seis win rates sobre las mismas filas

**Estado de las citas:** ✅ `builder.py:853` · ⚠️ **`timeline.py:75` corregida → `timeline.py:76-77`** · ✅ `behavioral.py:898` · ✅ `tradeStats.js:64` · ✅ `Insights.jsx:1896-1910` · ✅ `AssetDetail.jsx:171` (bloque 169-175).

#### a. Implementaciones

**W1 · `reporting/builder.py:853-856`** — Reportes, por período
```python
853:    trade_ops = [o for o in ops if _is_trade(o) and o.get("pnl_usd") is not None]
854:    wins = [o for o in trade_ops if o["pnl_usd"] > 0]
855:    losses = [o for o in trade_ops if o["pnl_usd"] < 0]
856:    win_rate = (len(wins) / len(trade_ops) * 100) if trade_ops else None
```

**W2 · `reporting/timeline.py:68-77`** — lifetime
```python
76:    wins = sum(1 for r in trades if r["pnl_usd"] > 0)
77:    return wins / len(trades) * 100
```

**W3 · `behavioral.py:890-898`** — card "win rate vs payoff"
```python
890:    trades = [o for o in ops if _is_trade(o)]
891:    winners = [o for o in trades if (o.get("pnl_usd") or 0) > 0]
892:    losers  = [o for o in trades if (o.get("pnl_usd") or 0) < 0]
897:    total = len(winners) + len(losers)
898:    win_rate = len(winners) / total * 100
```

**W4 · `frontend/src/utils/tradeStats.js:64-75`** — `/operaciones`
```js
75:  return { trades, wins, losses, winRate: trades > 0 ? wins / trades : null }
```

**W5 · `frontend/src/pages/Insights.jsx:1896-1922`** — `/analisis?tab=diagnostico`
```js
1896:  const MICRO_TRADE_PNL_THRESHOLD = 1.5
1897:  const significantTradeOps = tradeOps.filter(o => Math.abs(o.pnl_usd || 0) >= MICRO_TRADE_PNL_THRESHOLD)
1911:      const total = wins + losses
1916:        pct: (wins / total) * 100,
```

**W6 · `frontend/src/pages/AssetDetail.jsx:169-173`** — `/activo/:ticker`
```js
169:    const closed = operations.filter(o => o.pnl_usd != null)     // ← SIN filtro de tipo
173:    const winRate = (wins + losses) > 0 ? Math.round((wins / (wins + losses)) * 100) : null
```

#### b. Fórmulas

Sea `T` el universo de trades, `W = |{p>0}|`, `L = |{p<0}|`, `Z = |{p=0}|`, con `|T| = W+L+Z`:

    W1 = W / (W+L+Z)              universo L2, sin micro-filtro
    W2 = W / (W+L+Z)              universo L2, lifetime, pnl CRUDO
    W3 = W / (W+L)                universo L1, mínimo 5 ops
    W4 = W / (W+L+Z)              universo L2, pnl CRUDO
    W5 = W / (W+L)                universo L1 ∩ {|p| ≥ 1,50}
    W6 = W / (W+L)                SIN universo (todas las filas con pnl ≠ NULL)

Dos ejes de divergencia: **el cero en el denominador** (W1/W2/W4 lo cuentan, W3/W5/W6 no) y **el universo** (W6 no filtra nada).

#### c. ¿Real o cosmética? — **REAL, ~12 puntos**

Cuenta con: 6 ventas ganadoras, 2 ventas perdedoras, **2 ventas a resultado exactamente 0**, 4 cupones cobrados, 1 amortización importada sin cantidad (`pnl_usd = 0.0`, ver DIV-083 T-2) y 20 dividendos.

| | universo | W | L | Z | win rate |
|---|---|---:|---:|---:|---:|
| W1 Reportes | 12 (+4 cupones, +1 amort) | 10 | 2 | 3 | **66,7 %** |
| W2 lifetime | idem | 10 | 2 | 3 | **66,7 %** |
| W3 Comportamiento | idem, sin ceros | 10 | 2 | — | **83,3 %** |
| W4 `/operaciones` | idem | 10 | 2 | 3 | **66,7 %** |
| W5 Diagnóstico | idem, sin ceros ni micro | 10 | 2 | — | **83,3 %** |
| W6 `/activo/:t` | + 20 dividendos | 30 | 2 | 3 | **93,8 %** |

**Spread real: 66,7 % → 93,8 %.** Es el mismo bug histórico que `tradeStats.js:7-11` dice haber arreglado (*"93% (desktop), 100% (mobile) y 85% (backend)"*) — se arregló en `/operaciones` y sobrevivió en las otras cinco.

Y **ninguno de los seis es el número que el usuario cree estar leyendo**: los 4 cupones son ganadores automáticos. `realized_pnl.py:39-41` lo dice textual: *"un cupón nunca es negativo: no existe 'cobrar mal un cupón'... infla un número que el usuario lee como 'cuántas de mis decisiones salieron bien' — decisiones que no tomó."*

#### d. Dictamen

**Ninguna es correcta.** La fórmula correcta:

    win_rate = |{o : bucket(o) = trade ∧ pnl(o) > 0}| / |{o : bucket(o) = trade}|

con `bucket = trade` sólo para `Venta` y `Futuros` (DIV-081), y **el cero en el denominador** (`tradeStats.js:24-27` argumenta bien por qué: `pnl_usd` es `REAL DEFAULT 0`, una venta a resultado cero es un trade cerrado que no ganaste).

W6 es la peor de las seis y no tiene defensa: sin filtro de tipo, un activo que sólo pagó dividendos muestra "100 % win rate".
El umbral de micro-trade de W5 (1,50) es un **PARCHE** hardcodeado contra ruido de bots — la causa real es que no hay agrupación de fills en trades.

#### e. Qué ve mal el usuario y dónde

| pantalla | número |
|---|---|
| `/analisis?tab=reportes` (KPI "Win rate", subheadline, informe público `/i/:token`) | 66,7 % |
| `/operaciones` | 66,7 % |
| `/analisis?tab=diagnostico` (card "Win rate + profit factor") | 83,3 % |
| `/analisis?tab=comportamiento` (card "Tu estrategia pierde plata en agregado") | 83,3 % |
| `/activo/:ticker` | 93,8 % |

En `/analisis` las tres primeras conviven en **la misma pantalla, en pestañas contiguas**.

#### f. Causa raíz

**Copiar y pegar, y "Pendiente #1" nunca cerrado.** `realized_pnl.py:34-53` diagnostica el problema, lista los 4 sitios afectados y concluye que arreglarlo *"es decisión de producto, no una conversión. Sin decidir a propósito (2026-08-18)"*. La decisión sigue sin tomarse y el número sigue publicándose en cinco pantallas con cinco valores.

#### g. Fuente única de verdad

Un único `compute_trade_stats(ops)` en el backend, expuesto en `PeriodMetrics` y consumido por el frontend sin recalcular. Eliminar: W1, W2, W3, W5, W6 y dejar W4 como *renderer* de lo que llega. `AssetDetail.jsx:169` debe usar `esTradeCerrado` como mínimo inmediato.

---

### DIV-087 — Cinco pantallas leen `pnl_usd` crudo 🔴

**Estado de las citas:** ✅ `AssetDetail.jsx:169-175` · ✅ `PositionDetailMobile.jsx:356-358` · ✅ `Insights.jsx:1860-1864` · ✅ `Insights.jsx:1888-1897` · ✅ `insightsModel.js:511` · ✅ `Positions.jsx:524-535` · ✅ `Operations.jsx:140` · ✅ `assetPnl.js:170` · ⚠️ **`bookComposition.js:233` — matiz**: ese archivo **no llama** a `opPnlUsd` (verificado: `opPnlUsd` sólo se importa en `Operations.jsx:37` y en el test); las filas ya vienen convertidas del backend (`main.py:37472`). El efecto es correcto, la descripción del mapa no.

#### a. Implementaciones

**El origen del problema — `backend/main.py:12380-12386`**
```python
12380: @app.get("/api/operations")
12381: def get_operations(uid: int = Depends(get_effective_user)):
12383:         rows = conn.execute(
12384:             "SELECT * FROM operations WHERE user_id=? ORDER BY date DESC", (uid,)
12386:     return [dict(r) for r in rows]
```
**`SELECT *` sin conversión.** Es la única fuente de operaciones del frontend retail. Compará con los tres endpoints hermanos que **sí** convierten: `/api/export/operations.csv` (`main.py:13357`), `/api/movements` (`main.py:12486`) y el `last_op` de Reportes (`main.py:32767`).

**Convierten (3):** `Operations.jsx:140` (`pnl_usd: opPnlUsd(o)`), `assetPnl.js:170`, y el libro del asesor vía backend.

**No convierten (5):**
- `AssetDetail.jsx:169-175` — `realizedTotal`, `wins/losses`, `best`, `worst`
- `PositionDetailMobile.jsx:356-358` — la lista de movimientos de la posición
- `Insights.jsx:1860-1864` — `topAsset` ("Activo estrella", y **va al snapshot del Coach IA**, comentario línea 1852)
- `Insights.jsx:1897,1909-1919` + `insightsModel.js:504-516` — win rate, `avgWin/avgLoss`, profit factor
- `Positions.jsx:512` — `entry.total` (zona renta fija; ver DIV-088 para la otra mitad)

#### b. Fórmulas

Para un cupón AL30 de **$125.000 ARS** con `fx_to_usd = 1.250` sellado:

    convertido (opPnlUsd)  = 125.000 / 1.250 = US$100
    crudo (pnl_usd)        = 125.000          → "US$125.000"

#### c. ¿Real o cosmética? — **REAL, ×1.250**

Un usuario con un solo AL30 que cobró un cupón, en la misma sesión:

| pantalla | "P&L realizado" del cupón |
|---|---|
| `/operaciones` | **US$100** ✅ |
| `/posiciones` → "Ya cobraste" | **US$100** ✅ (por su propio camino, ver DIV-088) |
| `/activo/AL30` → "P&L realizado" | **US$125.000** 🔴 |
| `/posiciones/:id` (mobile) → historial | **+$125.000** 🔴 |
| `/analisis?tab=diagnostico` → "Activo estrella" | **AL30 +US$125.000** 🔴 |
| `/analisis?tab=diagnostico` → profit factor | `grossWin += 125.000` → PF ≈ ∞ 🔴 |

Y el `topAsset` inflado **viaja al modelo**: `Insights.jsx:1852` dice explícitamente *"Solo consumimos topAsset.asset y topAsset.pnl (snapshot del Coach IA)"*.

#### d. Dictamen

**Ninguna de las 8 debería tener que decidirlo.** La conversión no es una preocupación de pantalla: es la definición de la columna. La correcta es hacer que `GET /api/operations` devuelva `pnl_usd` ya convertido, igual que sus tres endpoints hermanos.

⚠️ **Si se hace eso hay que quitar `opPnlUsd` de `Operations.jsx:140`**, o esa pantalla dividiría dos veces (la fila seguiría trayendo `currency='ARS'` y `fx_to_usd=1250`, y `opPnlUsd` volvería a dividir → US$0,08).

#### e. Qué ve mal el usuario y dónde

`/activo/:ticker`, `/posiciones/:id` (mobile), `/analisis?tab=diagnostico` (activo estrella, win rate, profit factor, hold time, mejor/peor operación) — y por arrastre, el snapshot que el Coach IA recibe desde esa pantalla.

#### f. Causa raíz

**Frontend recalculando lo que el backend ya sabe.** `opPnlUsd` (`assetPnl.js:76-84`) es una **re-implementación en JS** de `realized_usd()` (`realized_pnl.py:118-141`) — dos motores para la misma regla, y aplicarla quedó como responsabilidad opcional de cada consumidor. Tres de ocho se acordaron.

#### g. Fuente única de verdad

`realized_usd_sql()` en `GET /api/operations`. Con eso `opPnlUsd` se puede borrar del frontend entero (junto con su copia de `NATIVE_CCY_OPS`), y las 5 pantallas se arreglan sin tocarlas.

---

### DIV-088 — La pantalla que infiere un FX prohibido

**Estado de las citas:** ✅ `realized_pnl.py:26` (la política está en el docstring, líneas 24-32) · ✅ `Positions.jsx:524-532` verificada literal.

#### a. Implementaciones

**La política — `backend/realized_pnl.py:24-32`**
> *"Las filas VIEJAS (fx NULL) caen al ELSE y quedan como estaban. **NO se convierten con un FX inferido a posteriori**, y esto es deliberado: ... de los 276 cupones marcados ARS sin FX sellado, ~125 tienen montos < 1 (son bonos en dólares tipo AL30/AL29/AE38, ya en USD)... convertirlos a todos haría 1250× más chicas a las que ya estaban bien — un bug peor que el que arregla. Quedan como están, **en TODOS los lectores** (incluido el dashboard)."*

**La violación — `frontend/src/pages/Positions.jsx:524-532`**
```jsx
524:      let fx = op.fx_to_usd
525:      if (fx == null || fx <= 0) {
526:        entry.hasLegacyOps = true
527:        if (op.currency === 'ARS' || (op.currency == null && amt > 1000)) {
528:          fx = tcValuacion || 1
529:        } else {
530:          fx = 1.0
531:        }
532:      }
533:      const amtUsd = amt / fx
```
Es exactamente la heurística que el módulo canónico prohíbe, **y con el umbral de 1.000 que el docstring usa para explicar por qué no funciona**.

#### b. Fórmulas

Fila legacy con `fx_to_usd = NULL`, monto nativo `A`, dólar de hoy `t`:

    Backend (todos los lectores):   valor = A
    Positions.jsx:                  valor = A / t   si  ccy='ARS' ∨ (ccy=NULL ∧ A>1.000)
                                            A       en otro caso

#### c. ¿Real o cosmética? — **REAL, ×1.250, en las dos direcciones**

**Caso 1 — el que el mapa señala.** Amortización legacy de un AL30 (bono **en dólares**), `currency = NULL`, monto **US$1.500**:
- `1500 > 1000` → `fx = tcValuacion ≈ 1.250` → **US$1,20** en `/posiciones`.
- Dashboard / Reportes / IA: **US$1.500**.
- **Divergencia: 1.250×** sobre el mismo hecho, entre dos pantallas de la misma app.

**Caso 2 — el inverso, más frecuente.** Cupón legacy de un AL35 en pesos, `currency = 'ARS'`, monto **$125.000**:
- `/posiciones` → **US$100** ✅ (por accidente: la heurística acierta acá).
- Dashboard / Reportes / IA → **US$125.000** 🔴.

O sea: la heurística **acierta** en las ~29 filas grandes y **destruye** las ~125 chicas, que es literalmente lo que el docstring predijo. Y como el backend no la aplica, cada fila legacy da un número distinto en `/posiciones` que en el resto de la app **sin excepción**: cuando la heurística acierta, difiere porque el backend está mal; cuando falla, difiere porque ella está mal.

#### d. Dictamen

**`realized_pnl.py:24-32` es la correcta** — no por ser mejor numéricamente, sino porque es la única **decidida** y **uniforme**. Un número consistentemente mal es reparable con un backfill; dos números distintos para el mismo hecho no son reparables sin decidir cuál era.

La solución de fondo no es ninguna de las dos: es **clasificar las 398 filas legacy** (`realized_pnl.py:55-59`, "Pendiente #2"). La señal existe y es barata: `positions.currency` / `brokers.currency` del `(broker, asset)` de la fila, o la moneda del bono en el catálogo (`ai/ar_bonds_metadata`) — un AL30 es en dólares, un TX26 en pesos, y eso no depende del monto.

#### e. Qué ve mal el usuario y dónde

`/posiciones` (Cartera), zona de renta fija: los totales **"Ya cobraste"**, `totalUsd`, `couponsUsd`, `amortizationsUsd` y la pata USD de cada fila del historial (`usdByOpId`, línea 537). Es la pantalla donde el usuario va específicamente a verificar cuánta renta cobró.

#### f. Causa raíz

**PARCHE local que contradice una política escrita.** El comentario de `Positions.jsx:515-523` muestra que el autor conocía el problema del FX (explica el bug del recíproco: *"multiplicar por 1250 convierte un cupón de $95.000 en US$118 millones"*) pero resolvió el caso `fx=NULL` inventando un fallback en vez de consultar la regla del backend. `hasLegacyOps` (línea 526) sugiere que hay un aviso de UI — pero el número igual se publica.

#### g. Fuente única de verdad

`realized_usd_sql()` en el endpoint (misma solución que DIV-087). Eliminar el bloque `Positions.jsx:524-532` entero. Y abrir el trabajo de clasificación de las 398 legacy, que es lo único que resuelve el fondo.

---

### DIV-089 — Dos fórmulas en la misma columna de la misma tabla

**Estado de las citas:** ✅ `useMonthlyData.js:329-361` verificada literal · ✅ `:265` verificada literal.

#### a. Implementaciones

**Rama con fila — `frontend/src/hooks/useMonthlyData.js:341-351`**
```js
341:    if (entry) {
346:      pnlRealized = entry.pnl_realized || 0
```
`entry` viene de `GET /api/monthly` → `monthly_entries.pnl_realized` = **universo A, convertido** (`main.py:9534`).

**Rama sin fila — `useMonthlyData.js:259-265, 352-362`**
```js
259:  const tradeOps = opsForBroker.filter(isTradeOp)     // ← isTradeOp local, línea 48
261:  for (const op of tradeOps) {
262:    if (!op.date || op.pnl_usd == null) continue
265:    realizedByPeriod.set(period, prev + (op.pnl_usd || 0))    // ← CRUDO
...
352:    } else {
360:      pnlRealized = realizedFromOps
362:      source = 'derived'
```
`operations` viene de `GET /api/operations` = `SELECT *` = **crudo** (ver DIV-087).

#### b. Fórmulas

Para el mes `M`:

    con fila:  pnlRealized = Σ_{o ∈ O_M}                    c(o)      ← universo A, convertido
    sin fila:  pnlRealized = Σ_{o ∈ O_M : isTradeOp(o)}     p(o)      ← universo B, CRUDO

Dos ejes de diferencia a la vez: universo **y** moneda.

#### c. ¿Real o cosmética? — **REAL, y el signo puede invertirse**

Mes con: venta perdedora −US$400, 3 dividendos +US$150, 1 cupón AL35 de $125.000 (fx sellado 1.250 = US$100).

- **Con fila** (`entry.pnl_realized`): `−400 + 150 + 100 = −US$150` → mes en rojo.
- **Sin fila** (`realizedFromOps`): dividendos fuera; cupón **crudo** → `−400 + 125.000 = +US$124.600` → mes en verde brillante.

El mismo mes, la misma columna del mismo hook, con **US$124.750 de diferencia y el signo invertido**, según exista o no una fila en `monthly_entries` — cosa que el usuario no controla ni ve.

Y `source: 'derived'` alimenta el `delta` del mes (`useMonthlyData.js:365-367`: *"derived → solo pnl_realized"*), o sea el **porcentaje del mes** también.

#### d. Dictamen

**La rama con fila es la correcta** (es la que el backend calcula y la que respeta la conversión). La rama derivada es un fallback improvisado que reimplementa mal dos reglas a la vez. Debería, como mínimo, aplicar `opPnlUsd` y `esTradeCerrado`; idealmente el backend debería sembrar la fila (que es exactamente lo que `_recalc_pnl_realized_from_ops` hace con `_seed` en `main.py:9450-9466`, descubriendo los meses desde `operations`) y la rama no debería existir.

#### e. Qué ve mal el usuario y dónde

`MonthlyTeaser` (`components/MonthlyTeaser.jsx:37`), que se renderiza en `/posiciones`. Es el único consumidor de `useMonthlyData` en producción (verificado: la otra referencia, `PositionsMobile.jsx:528`, es un comentario que dice que ese camino está muerto).

#### f. Causa raíz

**Fallback improvisado en el navegador** — la rama `else` se escribió para cubrir "mes sin entry" sin volver al backend, y reimplementó el cálculo con las herramientas que había a mano (`isTradeOp` copiado de `Insights.jsx`, `pnl_usd` crudo del endpoint).

#### g. Fuente única de verdad

`monthly_entries.pnl_realized`, sembrado por el backend. Eliminar `useMonthlyData.js:253-266` (el bloque `realizedByPeriod`) y `:48-54` (`isTradeOp`); la rama `else` queda con `pnlRealized = 0` y `source='derived'`.

---

### DIV-090 — El P&L de por vida que la IA recibe DUPLICADO 🔴

**Estado de las citas:** ✅ `AICoachDrawer.jsx:177` · ✅ `RendiAI.jsx:170`. Ruta real del drawer: `frontend/src/components/ai/AICoachDrawer.jsx` (no `components/`).

#### a. Implementaciones

**El endpoint — `backend/main.py:11960-11974`**
```python
11971:        rows = conn.execute(
11972:            "SELECT * FROM monthly_entries WHERE user_id=? ORDER BY year, month, broker", (uid,)
11974:        return [dict(r) for r in rows]
```
Sin filtro de broker: devuelve **las filas por-broker y la sintética `broker='global'`**.

**El sumador roto — `RendiAI.jsx:169-179` y `AICoachDrawer.jsx:176-186`** (código idéntico)
```js
170:  const sumPnlRealized = (monthly || []).reduce((acc, m) => acc + (m.pnl_realized || 0), 0)
...
179:    realized_pnl_usd_lifetime: +sumPnlRealized.toFixed(2),
```

**El sumador correcto, en el mismo repo — `Dashboard.jsx:242-244`**
```js
242:  const realizedPnl = monthly
243:    .filter(m => m.broker === 'global')
244:    .reduce((s, m) => s + (m.pnl_realized || 0), 0)
```

**El invariante que hace que sea exactamente ×2** — verificado en tres lugares:
- `_recalc_pnl_realized_from_ops` recalcula `broker='global'` como la suma cross-broker (`main.py:9518-9530`, `broker_filter_sql = "" if broker == 'global'`).
- Cada escritura incremental toca las dos filas: `main.py:10977-10980`, `11394-11395`, `12365-12366`, `persister.py:857-858`, `1194-1195`.
- El propio código lo dice al modelo en otro packet (`insights.py:280-281`): *"NO sumes 'global' con las por-broker — duplicarías."*

#### b. Fórmulas

Con `B` brokers y `R_b` el realizado del broker `b`:

    correcto  = R_global = Σ_b R_b
    publicado = R_global + Σ_b R_b = 2 · Σ_b R_b

    error = +100 % exacto

#### c. ¿Real o cosmética? — **REAL, ×2 exacto**

Usuario con Cocos (+US$4.000) y Balanz (−US$1.400):
- `monthly_entries` tiene filas de Cocos, de Balanz y de `global` (=+2.600).
- `Dashboard.jsx` → **+US$2.600** ✅
- `realized_pnl_usd_lifetime` → `4.000 − 1.400 + 2.600` = **+US$5.200** 🔴

El campo viaja en el `summary` del contexto de **cada mensaje** del chat (`RendiAI.jsx:71`, `AICoachDrawer.jsx:60`), así que el modelo responde "ganaste US$5.200 realizados desde que empezaste" mientras el Dashboard, en la misma pantalla, dice US$2.600. Y como `deposits_lifetime` y `withdrawals_lifetime` (líneas 171-172 / 178-179) tienen **el mismo bug**, cualquier ratio que el modelo derive (rendimiento sobre aportado) sale mal por partida doble.

#### d. Dictamen

**`Dashboard.jsx:242-244` es la correcta.** El fix es una línea, y ya está escrita 70 líneas más arriba en el mismo repo.

#### e. Qué ve mal el usuario y dónde

Chat IA en **toda la app**: el drawer del Coach (`components/ai/AICoachDrawer.jsx`, disponible desde cualquier pantalla) y la página `/ai` (`RendiAI.jsx`). Afecta `realized_pnl_usd_lifetime`, `deposits_lifetime` y `withdrawals_lifetime`.

#### f. Causa raíz

**Copiar y pegar que perdió el `.filter`.** `buildSummary` está duplicado carácter por carácter en dos archivos (comentario de `RendiAI.jsx:160`: *"Mismo resumen mínimo que armaba el drawer"*). El backend defiende contra este mismo error en sus propios packets (`insights.py:280`), pero el frontend arma este `summary` por su cuenta.

#### g. Fuente única de verdad

Un builder de backend (`ai/builders/dashboard.py` ya existe) que arme el `summary` server-side; o, como mínimo, extraer `buildSummary` a `utils/` con el `.filter(m => m.broker === 'global')`, y borrar las dos copias.

---

### DIV-091 — Los `_field_docs` le mienten al modelo

**Estado de las citas:** ✅ `monthly.py:154` verificada literal · ✅ `builder.py:842` · ✅ `reports.py:160` verificada literal.

#### a. Implementaciones

**Packet `monthly` — `backend/ai/builders/monthly.py:154` vs `:185`**
```python
154:  "metrics.realized_pnl": "USD de trades CERRADOS en el mes. Solo realized.",
...
185:  "realized_pnl": round(float(m.get("realized_pnl") or 0), 2),
```
`m` es `full["metrics"]` de `build_period_report` → `PeriodMetrics.realized_pnl` → `builder.py:1655` → `builder.py:842` = **universo A** (con dividendos, intereses y FX de conversiones). Idem el header del módulo, `monthly.py:28`: *"P&L USD de trades CERRADOS en el mes"*.

Y en la línea siguiente:
```python
156:  "metrics.trades_count": "Cantidad de operaciones CERRADAS en el mes (no incluye Compra/Dividendo/Interés)."
```
Éste **sí** es cierto (universo B) — o sea el packet le entrega al modelo dos campos con descripciones que se contradicen entre sí, igual que el card de DIV-082.

**Packet `reports` — `backend/ai/builders/reports.py:160` vs `:97-99`**
```python
97:  pnl_year_usd = round(sum(
98:      float(e.get("pnl_realized") or 0) for e in entries
99:  ), 2)
...
160:  "realized_pnl_year_usd": "USD ABSOLUTO de P&L REALIZADO del año (suma pnl_realized de monthly_entries). Solo trades cerrados.",
```
`monthly_entries.pnl_realized` = universo A. La descripción admite la fuente y **niega su contenido en la misma frase**.

**Contrapunto — `insights_attribution.py:173`**
```python
173: "total_realized_usd": "USD de P&L de trades CERRADOS, sumado all-time. SOLO realized.",
```
Ésta **sí** es verdadera (usa `is_closed_op`, línea 70). O sea: el modelo recibe tres campos con la misma descripción y **dos universos distintos detrás**.

#### b. Fórmulas

    monthly.metrics.realized_pnl      = R_A     ·  doc dice: universo B
    reports.realized_pnl_year_usd     = R_A     ·  doc dice: universo B
    reports.pnl_year_usd              = R_A     ·  doc dice: "alias, mismo valor" ✅
    insights.realized_pnl_usd         = R_B     ·  doc dice: universo B ✅
    attribution.total_realized_usd    = R_B     ·  doc dice: universo B ✅

#### c. ¿Real o cosmética? — **REAL, y peor que un número mal**

Los `_field_docs` existen para que el LLM interprete: son la **instrucción de lectura**. Con el mes de DIV-081, si el usuario pregunta *"¿cuánto gané en trades cerrados en septiembre?"*:

- El packet `monthly` dice **6.600** con la etiqueta "solo trades cerrados" → el modelo lo afirma sin margen de duda.
- El packet `insights` dice **6.100** con la misma etiqueta.
- El modelo no tiene forma de detectar la discrepancia (son campos de packets distintos) y responderá con el que tenga a mano, con confianza total.

Es cualitativamente peor que un número inflado: un campo mal documentado **desactiva el escepticismo del modelo** sobre ese campo. `reports.py:161` incluso convierte un alias en un compromiso: *"pnl_year_usd: Alias back-compat de realized_pnl_year_usd. Mismo valor."* — cierto, pero los dos son A.

#### d. Dictamen

Los **docs** describen lo correcto (universo B es lo que el usuario entiende por "trades cerrados"); el **valor** es el que está mal. Ver dictamen de DIV-081: hasta que exista la descomposición, los docs deben decir la verdad literal — *"USD realizado del mes: ventas + renta cobrada + resultado cambiario"*.

#### e. Qué ve mal el usuario y dónde

Chat IA, packets `monthly` (`/analisis?tab=reportes` con el Coach abierto) y `reports`. El usuario no ve el campo: ve una **afirmación del modelo** construida sobre él.

#### f. Causa raíz

**Documentación escrita sobre la intención, no sobre el código.** Los `_field_docs` se agregaron en la "Ola 2-E del audit" (comentario `monthly.py:146`) describiendo lo que el campo *debería* significar. Nadie siguió `m.get("realized_pnl")` hasta `builder.py:842`. Es el mismo síntoma que este informe encontró en `fetch_operations_in_range` (`builder.py:220`), cuyo docstring dice *"Operations cerradas (Venta, Dividendo, Interés, Futuros)"* sobre una query que **no filtra por `op_type`**.

#### g. Fuente única de verdad

Los `_field_docs` deben generarse desde la misma capa que produce el valor (p. ej. la descomposición de DIV-081 exponiendo `{value, definition}` por campo), no escribirse a mano en cada builder.

---

## Parches detectados

| ubicación | qué síntoma tapa | causa real | dónde más sigue rompiendo |
|---|---|---|---|
| `realized_pnl.py:101-107` (`realized_usd_sql`) — `CASE WHEN op_type IN ('Cupón','Amortización') AND currency='ARS' AND fx>0` | cupones en pesos leídos como dólares | `operations.pnl_usd` es una columna polimórfica: guarda resultado, cash bruto y ganancia cambiaria, en 2 monedas | `Interés PF` (DIV-084); `'Renta'`; `'Cupon'`/`'Amortizacion'` sin acento (contemplados en `main.py:14528,14666,14889,35793` pero no en `_NATIVE_CCY_OPS`); las 398 filas legacy con `fx=NULL` |
| `main.py:10508` — `realized_gain` calculado y **descartado** (sólo en la respuesta HTTP) | ninguno: el número correcto existe y no se persiste | falta separar "cash cobrado" de "resultado" en el modelo de datos | `capital_final` de todos los meses posteriores; TWR; Dashboard; Reportes; chat IA |
| `persister.py:980` — `pnl_usd = 0.0 if is_amort` | amortización importada contada como ingreso | ese camino no tiene lookup del cost basis FIFO (el manual sí lo tiene: `_compute_amort_cost_basis_fifo`) | subestima el resultado real; y deja un `pnl_usd = 0.0` (no NULL) que entra al denominador de los 6 win rates |
| `persister.py:927` — `if "amortiz" not in (notes or "").lower()` | clasificar amortizaciones que el broker exporta como cash | no hay un campo de tipo de evento en `NormalizedTx`; se clasifica por substring de texto libre | cualquier broker que escriba "Amort." o "Devol. capital" cae en `Dividendo` → capital devuelto contado como ganancia (el propio comentario de `persister.py:908-910` dice que ya pasó con TX26) |
| `Positions.jsx:524-532` — FX inferido con el dólar de hoy | cupones legacy sin `fx` sellado | las 398 filas legacy sin clasificar (`realized_pnl.py` "Pendiente #2") | rompe las ~125 filas de bonos en dólares (1.250× más chicas) y diverge del backend en las 276 |
| `Positions.jsx:549` — `pnlContrib = 0` cuando `cost_basis_consumed` es NULL | amortizaciones legacy sin cost basis | idem: el dato no se estampó en su momento | subestima el P&L de renta fija en la única pantalla que lo calcula bien |
| `Insights.jsx:1896` — `MICRO_TRADE_PNL_THRESHOLD = 1.5` | bots de DCA/grid que destruyen el win rate | no hay agrupación de fills en trades | hace que Diagnóstico dé un win rate distinto de Reportes y Operaciones sobre las mismas filas (DIV-086) |
| `builder.py:1531` — `unrealized = delta_usd - realized` | falta de un `unrealized` medido para ese camino | `realized` (universo A) se usa como residual, así que todo error de A se transfiere de signo contrario a `unrealized` | los dividendos que inflan A **deflactan** el `unrealized_pnl` publicado en Reportes por el mismo monto |
| `main.py:9315` — `fx = 1.0 if moneda in ("USD","USDT") else None` | evita inventar un FX para USD | no reusa `_fx.fx_for_date_detail`, que es justo lo que `bond_cashflow` sí hace (`main.py:10419`) para el mismo problema | todo PF en pesos nace irreparable (DIV-084) |

---

## Citas del mapa incorrectas

| DIV | cita del mapa | ubicación real | qué decía mal |
|---|---|---|---|
| DIV-084 | `main.py:37504` | **`main.py:37503`** | 37504 es el comentario; el `if "DIVIDENDO" in tipo or "INTER" in tipo or "CUPON" in tipo:` está en 37503 |
| DIV-085 | `ai/builders/reports.py:101` | **`ai/builders/reports.py:105`** | 101 es `trades_year_row = conn.execute(`; la lista `('Compra','Dividendo','Interés','')` está en 105. Además `reports.py` **no tiene** un `_is_trade` en Python: su único filtro es ese SQL |
| DIV-085 | `reporting/timeline.py:69` | **`reporting/timeline.py:70`** | 69 es `r for r in rows`; la tupla está en 70. Y falta una **segunda** copia en el mismo archivo: el SQL de `timeline.py:87` |
| DIV-086 | `reporting/timeline.py:75` | **`reporting/timeline.py:76-77`** | 75 es `return None` del guard; `wins` está en 76 y el cociente en 77 |
| DIV-087 | "`bookComposition.js:233` sí la aplican" | `bookComposition.js:233` **no llama a `opPnlUsd`** | `opPnlUsd` sólo se importa en `Operations.jsx:37` (y en el test). Las filas del libro llegan ya convertidas del backend (`main.py:37472`): el efecto es correcto, la explicación no |
| DIV-085 | (interno al código, no del mapa) `tradeStats.js:3` dice "espejo de `builder.py:352-363`" | `builder.py:845-856` | en este commit la línea 352 no contiene `_is_trade` ni el win rate |
| DIV-081 | (interno) `fetch_operations_in_range` docstring, `builder.py:220`: *"Operations cerradas (Venta, Dividendo, Interés, Futuros)"* | la query (`builder.py:238-245`) **no filtra por `op_type`** | el docstring afirma un filtro que no existe — es el origen de que `builder.py:842` se lea como si estuviera filtrado |

---

## URGENTE

Tres cosas de este grupo ameritan arreglo inmediato. **No toqué una sola línea de código.**

**1. `realized_pnl_usd_lifetime` duplicado en el chat IA (DIV-090).**
`RendiAI.jsx:170` y `AICoachDrawer.jsx:177` publican **exactamente el doble** del P&L realizado de por vida (y lo mismo con `deposits_lifetime` y `withdrawals_lifetime`), porque suman las filas por-broker **más** la fila sintética `broker='global'` de `GET /api/monthly`. El fix es agregar `.filter(m => m.broker === 'global')`, que ya está escrito en `Dashboard.jsx:243`. Es la peor combinación posible: error grande, determinista, en un canal donde el modelo lo afirma con autoridad, y con la corrección disponible a 70 líneas de distancia.

**2. La amortización manual corrompe la cadena contable de forma permanente (DIV-083).**
`main.py:10484` guarda el cash bruto entero como `pnl_usd`, y `capital_final = capital_inicio + deposits − withdrawals + pnl_realized` hereda ese error hacia adelante mes a mes. La ganancia correcta se calcula en `main.py:10508` y se descarta. Esto no sólo muestra un P&L mal: **infla el TWR** de toda cuenta con bonos amortizantes, que en Argentina es casi cualquier cartera con AL30/GD30. Requiere fix **y** backfill de las filas ya escritas.

**3. `Interés PF` entra como ganancia realizada 1.250× inflada y como operación ganada (DIV-084).**
Un plazo fijo en pesos de tamaño normal ($10M a 30 días) inyecta **US$328.767** falsos en el P&L realizado de cinco pantallas, en `capital_final` y en el chat, y suma una "operación ganada" a los seis win rates. `realized_pnl.py:61-68` lo tiene documentado como "Pendiente #3" con la nota *"Hoy no muerde (0 filas en producción)"* fechada 2026-08-18 — pero el endpoint que las crea (`POST` de cierre de plazo fijo, `main.py:9280`) está vivo y publicado. Es una mina que se arma sola con el primer usuario que cierre un PF en pesos.

Riesgo estructural asociado, no urgente pero sí de diseño: `_NOT_A_TRADE` es una **lista de exclusión**, así que todo `op_type` nuevo entra a "P&L realizado / trade cerrado ganado" **por omisión**. Ya pasó con `Interés PF`, y `'Renta'`, `'Cupon'` y `'Amortizacion'` (contemplados en cuatro filtros de lectura del propio `main.py`) están en la misma situación.

---

## BLOQUE-RESUMEN

| concepto | DIV | versiones | difieren | correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---|---:|---|---|---|---|---|
| P&L realizado | DIV-081 | 6 | REAL — dividendos + intereses + FX de conversiones (hasta 8× en carteras de renta) | ninguna: falta descomponer trade/income/fx/capital_return | `/analisis?tab=reportes`, `/dashboard`, chat IA | 🔴 | falta de capa compartida: `realized_pnl.py` unificó la conversión pero no el universo |
| P&L realizado | DIV-082 | 2 | REAL — monto universo A con subtítulo universo B ("+US$300 · 0 ops cerradas") | ninguna: las dos mitades deben salir del mismo universo | `/analisis?tab=reportes` (KPI "P&L realizado") e informe público `/i/:token` | 🟠 | DIV-081 hecha visible en un solo componente |
| P&L realizado | DIV-083 | 4 | REAL — 0 / bruto / bruto−costo / FIFO; e infla `capital_final` de forma permanente | `Venta` FIFO del importador (= `Positions.jsx:544`) | `/dashboard`, `/analisis?tab=reportes`, `/mensual`, chat IA | 🔴 | fix aplicado en un solo lugar; el número correcto se calcula (`main.py:10508`) y se descarta |
| P&L realizado | DIV-084 | 3 | REAL — ×1.250 y +1 operación ganada por cada plazo fijo en pesos | ninguna: `Interés PF` es renta y debe estar en `_NATIVE_CCY_OPS` con FX sellado | `/dashboard`, `/analisis` (3 tabs), `/mensual`, chat IA | 🔴 | migración a medio hacer: op_type nuevo sin registrar en el módulo canónico |
| P&L realizado | DIV-085 | 12 | REAL — sólo en filas con `op_type=''`, que Reportes cuenta y la IA no | `realized_pnl.is_closed_op` (incluye `''`, y es la única testeada) | `/analisis?tab=reportes` (trades_count, win rate, mejor/peor op), `/operaciones` | 🟡 | copiar y pegar: sólo 4 de 12 importan el módulo canónico |
| P&L realizado | DIV-086 | 6 | REAL — 66,7 % / 83,3 % / 93,8 % sobre las mismas filas | ninguna: hay que sacar renta del universo (Pendiente #1 sin cerrar) | `/operaciones` vs `/analisis?tab=diagnostico` vs `?tab=comportamiento` vs `/activo/:ticker` | 🟠 | copiar y pegar + decisión de producto postergada |
| P&L realizado | DIV-087 | 8 | REAL — ×fx (≈1.250): un cupón de $125.000 se muestra como US$125.000 | convertir en `GET /api/operations`, no en cada lector | `/analisis?tab=diagnostico`, `/activo/:ticker`, `/posiciones/:id` (mobile) | 🔴 | frontend recalculando: `GET /api/operations` es `SELECT *` mientras 3 endpoints hermanos sí convierten |
| P&L realizado | DIV-088 | 2 | REAL — 1.250× entre `/posiciones` y el resto de la app, en ambas direcciones | `realized_pnl.py:24-32` (no inferir FX), por uniformidad | `/posiciones` (zona renta fija: "Ya cobraste", totales USD) | 🟠 | PARCHE local que contradice una política escrita en el módulo canónico |
| P&L realizado | DIV-089 | 2 | REAL — universo A convertido vs universo B crudo; el signo del mes se puede invertir | la rama con fila (`entry.pnl_realized`) | `/posiciones` (`MonthlyTeaser`: monto y % del mes) | 🟡 | fallback improvisado en el navegador cuando falta la fila |
| P&L realizado | DIV-090 | 2 | REAL — ×2 exacto (también `deposits_lifetime` y `withdrawals_lifetime`) | `Dashboard.jsx:242-244` (con `.filter(broker==='global')`) | chat IA en toda la app (drawer del Coach y `/ai`) | 🔴 | copiar y pegar que perdió el `.filter`; `buildSummary` duplicado en 2 archivos |
| P&L realizado | DIV-091 | 5 | REAL — 3 campos con la misma descripción y 2 universos detrás | los docs describen bien; el valor es el que está mal | chat IA (packets `monthly` y `reports`) | 🟠 | documentación escrita sobre la intención, no verificada contra el código |
