# Broker unificado (padre ARS + sub-broker "· USD") — factibilidad y riesgo

Fecha: 2026-09-04 · Repo: `/Users/nicolaspussetto/Documents/trading` · Rama: `fix/ai-stale-position`

Todo lo que sigue está verificado contra el código y contra `backend/trading.db`. Lo que no pude
verificar está en la sección **Incertidumbres** al final.

---

## 1. Veredicto en 5 líneas

1. **Es factible**, y es 100% frontend si el alcance es la tabla de Cartera. El backend ya trata
   al par padre↔sibling como una sola cartera para el FIFO (`broker_pair`, `backend/importing/persister.py:64`),
   y `/api/brokers` ya devuelve `parent_broker_id` (`backend/main.py:2462`): no falta ningún dato.
2. **La trampa principal no es técnica, es de definición**: "una sola fila por ticker" y
   "precio promedio" son incompatibles cuando el mismo ticker se compró en pesos y por MEP.
   Cualquier promedio fusionado suma ARS con USD y sale un número sin unidad.
3. La app **ya resolvió eso** hace tiempo: agrupa por `(activo, MONEDA)`, no por activo
   (`frontend/src/pages/Positions.jsx:846`). Si se conserva esa clave cruzando las dos patas,
   se entrega "veo todo junto" sin romper nada y **sin tener que bloquear la edición**.
4. Lo caro no es el merge: es que la pantalla tiene **dos árboles de tabla duplicados**
   (ARS `Positions.jsx:1398-1607`, USD `1610-1795`, ~400 líneas con columnas distintas) y hay
   que colapsarlos en uno.
5. Antes de tocar la vista hay **6 bugs vivos** que este cambio convierte en el camino principal
   (el peor: borrar el broker padre tira `FOREIGN KEY constraint failed` en toda DB de producción).

---

## 2. Lo que el usuario tiene razón

**Premisa 1 — mantener la separación en import y almacenamiento: correcta y no negociable.**
El rebuild FIFO decide si netear una venta cross-currency (el fantasma dólar-MEP) mirando
`positions.currency` por lote (`backend/importing/rebuild.py:154-191`). Si se fusionaran los lotes
en la DB, se pierde ese dato y el rebuild ya no puede decidir el spill. Además
`monthly_entries` tiene `UNIQUE(user_id, year, month, broker)` (`backend/main.py:588`) y el
propio endpoint de rename devuelve 409 justamente por eso (`backend/main.py:2574-2576`).
La unificación **sólo puede ser de vista**. El usuario lo dijo bien.

**Premisa 2 — el dolor es real y es estructural.** Hoy el par se ve como dos cuentas
independientes: dos headers, dos tablas, dos totales. En desktop al menos quedan adyacentes
(`sortBrokersForDisplay`, `Positions.jsx:2357-2385`); en mobile se ordenan por `totalUsd`
descendente (`PositionsMobile.jsx:640`) así que "IOL" e "IOL · USD" pueden quedar separados por
otros brokers, sin ninguna marca de parentesco — `parent_broker_id` no aparece en ninguna línea
de `PositionsMobile.jsx`.

**Premisa 3 — "en unificado no se edita": la intuición es correcta, el alcance es más chico
de lo que él cree.** Tiene razón en que un promedio que fusiona lotes de dos monedas no se puede
editar. Pero eso sólo pasa si se fusiona por activo. Si se conserva la moneda en la clave de
agrupación, cada fila sigue teniendo un `p.broker` real y unívoco, y **la edición sigue viva**.

**Y el precedente ya existe en el código**: la fila agregada multi-lote (`isAgg`) ya es
read-only por diseño — `buildPositionMenu` devuelve sólo "Ver lotes / Agregar compra / Registrar
venta" (`Positions.jsx:2390-2397`), con el comentario "NO editar/eliminar (eso es por lote)".
El mecanismo que él propone ya está escrito.

---

## 3. Dónde se complica

### 3.A — BLOQUEANTES (hay que arreglarlos antes de tocar la vista)

#### B1 · Borrar la cuenta unificada revienta: la FK no tiene `ON DELETE CASCADE` en producción

`delete_broker` limpia `positions`/`operations`/`monthly_entries` de padre+sibling por nombre y
después borra **sólo la fila del padre**, confiando en un cascade que no existe:

- `backend/main.py:2869-2870` — `# DELETE del padre — el FK CASCADE elimina el row del sibling.`
  seguido de `DELETE FROM brokers WHERE id=? AND user_id=?`
- `backend/main.py:395` (CREATE TABLE) sí dice `ON DELETE CASCADE`, pero la columna llegó por
  `backend/main.py:404`: `ALTER TABLE brokers ADD COLUMN parent_broker_id INTEGER REFERENCES brokers(id)` — **sin acción**.
- Schema vivo: `sqlite3 backend/trading.db "PRAGMA foreign_key_list(brokers)"` →
  `parent_broker_id|id|NO ACTION|NO ACTION`
- `backend/main.py:255` prende `PRAGMA foreign_keys=ON`.

**Reproducido** con el schema exacto de la DB real:

```
CREATE TABLE brokers (... parent_broker_id INTEGER REFERENCES brokers(id), UNIQUE(user_id,name));
INSERT padre; INSERT hijo con parent_broker_id=1;
PRAGMA foreign_keys=ON; DELETE FROM brokers WHERE id=1;
→ Error: stepping, FOREIGN KEY constraint failed (19)
```

Como todo corre dentro del mismo `with conn:`, el rollback deshace también los DELETE de
positions/operations/monthly_entries. Resultado: **500 genérico y la cuenta es indeleteable**.

Ya es alcanzable hoy desde `BrokerManager.jsx:102` y `PositionsMobile.jsx:414`, pero hoy es el
camino raro (el usuario ve dos cuentas y suele borrar el sibling, que sí funciona porque no tiene
hijos). **Una tarjeta unificada con un solo botón "Eliminar" lo convierte en EL camino.**

Ningún test lo caza porque `init_db()` crea DBs frescas con el CREATE TABLE de la línea 395.

**Fix:** una línea — `DELETE FROM brokers WHERE user_id=? AND parent_broker_id=?` antes del padre.
Es exactamente el patrón que ya funciona en `_wipe_broker_data` (`backend/main.py:10967`).

---

#### B2 · El único escape hatch para editar ("Ver lotes") está roto: escribe una clave que nadie lee

El grupo se crea con `key: \`t:${asset}:${ccy}\`` (`Positions.jsx:854-855`) y `flattenGroups`
expande leyendo `expandedTickers.has(g.key)` (`Positions.jsx:870`). Pero los 4 call-sites del
toggle escriben/leen **sin la moneda**:

- `Positions.jsx:1424` — `const tickerExpanded = showAllLots || expandedTickers.has(\`t:${p.asset}\`)`
- `Positions.jsx:1495` — `onClick={() => toggleTicker(\`t:${p.asset}\`)}` (botón inline "N lotes")
- `Positions.jsx:1560` — `onToggleLots: () => toggleTicker(\`t:${p.asset}\`)` (ítem del ActionMenu)
- `Positions.jsx:1632` — mismo `tickerExpanded` en la tabla USD

El Set queda con una clave huérfana. Peor: `tickerExpanded` **sí** lee la clave sin moneda, así
que el botón pasa a "Ocultar lotes" y el chevron se da vuelta mientras abajo no aparece ninguna
fila. El único camino vivo es el botón global "Ver lotes" de la toolbar (`showAllLots`).

Es prerequisito duro: si el modo unificado le saca "Editar posición" a alguna fila, "Ver lotes"
pasa a ser la única vía descubrible al lote real (`AssetDetail.jsx` y `PositionDetailMobile.jsx`
son read-only: cero `api.put/post/delete`).

**Fix trivial:** la variable correcta ya está desestructurada — `{ key: rowKey, p, isAgg, isLot, lotCount }`
en `Positions.jsx:1423` y `:1631`. Usar `rowKey` en los 4 lugares.

---

#### B3 · Mobile aplica `lots[0].isAR` al costo de TODOS los lotes del grupo

`frontend/src/pages/PositionsMobile.jsx:560` agrupa por `` `${p.broker}:${p.asset}` `` — **sin
dimensión de moneda**, a diferencia del desktop. Después:

- `:571` — `const isAR = lots[0].isAR`
- `:575` — `investedUsd = lots.reduce((s,x) => s + (isAR ? (x.invested||0)/tcBlue : (x.invested||0)), 0)`
- `:578` — `pnlLocal = isAR ? pnlUsd * tcBlue : pnlUsd`
- `:594` — `buy_price: totalQty > 0 ? totalInv / totalQty : null`

Hoy no explota porque el nombre del broker separa las monedas (`isAR` sale de
`arsBrokerSet.has(p.broker)`, `:451`). Cualquier agrupación cross-pata lo rompe ×~1400, y **el
signo del error se invierte según el orden del array**. Mobile además no importa `trustMktValue`
(`import` en `:38`), así que nada atenúa el disparate.

---

#### B4 · El guard `isAgg` que el usuario quiere reusar deja pasar tres escrituras

`buildPositionMenu` con `isAgg` (`Positions.jsx:2390-2397`) saca Editar/Eliminar pero **deja
"Agregar compra" y "Registrar venta"**. Y hay un cuarto entrypoint que ni siquiera pasa por el
menú.

- **Vender.** `openSell` postea `broker: p.broker` = `lots[0].broker` (`_buildAgg`, `Positions.jsx:812`).
  En el backend hay dos ejes que se desalinean: `currency` sale de
  `SELECT currency FROM brokers WHERE name=?` con el nombre que mandó el cliente
  (`backend/main.py:7850-7853`), mientras `sell_ccy` sale de `data.currency` (`:7858-7861`).
  El FIFO consume bien los lotes vía `broker_pair` (`:7871`), pero la rama del P&L (`:7951`),
  la acreditación de cash (`:8005` → `_adjust_broker_cash(conn, uid, data.broker, ...)`) y el
  P&L mensual (`:8012-8020`) siguen a `currency`. Vender la pata dólar mandando el padre ARS
  **acredita dólares como pesos, en silencio, con HTTP 200**.
  Nota: `/api/positions` ordena `ORDER BY broker ASC` (`backend/main.py:5685`), así que
  `lots[0].broker` es **siempre** el padre ARS ("Balanz" ordena antes que "Balanz · USD").
- **Agregar compra.** `openAdd(p.broker)` (`Positions.jsx:2395`) setea `form.broker`, que se pasa
  como `initialBroker` a `AddPositionFlow` → `needsBrokerStep = !initialBroker`
  (`AddPositionFlow.jsx:53`) **saltea el paso de elegir broker**, y en modo `add` el broker se
  muestra como texto no editable (`Positions.jsx:3285-3294`). El backend infiere
  `resolved_ccy` del broker recibido (`backend/main.py:5703-5708`): una compra por MEP queda
  estampada `currency='ARS'` y el costo sale ~1450× subestimado.
- **Cupón / amortización.** Segundo entrypoint fuera del menú: los botones de `BondDetailRow`
  (`Positions.jsx:1574-1575` y `:1765-1766`) llaman `openBondCashflow(p, ...)` directo, y
  `BondDetailRow` se renderiza para la fila agregada. El backend amortiza con
  `WHERE ... AND broker=?` sin `broker_pair` (`_bond_total_qty`, `backend/main.py:7247-7253`),
  a diferencia de la venta: o dispara `cross_currency_skipped` (acredita el cash y no decrementa
  un solo VN) o clampea con `min()` y borra una pata entera.

---

### 3.B — ALTOS (rompen consistencia entre pantallas)

#### A1 · `computeBrokerValue` deja `valueArs`/`invArs` en 0 para brokers USD

`frontend/src/utils/valuation.js:174` declara `let valueArs = 0, invArs = 0`; la rama ARS
(`:183-213`) los llena; **la rama USD (`:215-247`) nunca los escribe**, y el return
(`:250-257`) los devuelve en 0. El docstring lo dice: "Meaningful only for ARS brokers"
(`:42-45`).

Consecuencia: la forma obvia de armar el subtotal del par —llamar dos veces y sumar— produce un
total en pesos que es **sólo el del padre**, sin ningún warning. La suma en USD sí es correcta,
así que el bug sólo aparece con el toggle en ARS. Y hay tests que consagran los ceros
(`valuation.test.js:41-43` y `:257-259`), o sea que "arreglarlo" cambiando el campo rompe el
contrato existente.

#### A2 · Reportes filtra por nombre exacto: la mitad de la historia, sin error

`backend/reporting/builder.py:93-97` — `_broker_clause` devuelve `" AND broker = ?"`, con
`'global'` como único agregado. Lo mismo en `_operations_clause` (`:100-103`),
`fetch_monthly_entry` (`:152`) y `backend/reporting/timeline.py:111`.

`grep broker_pair backend/reporting/` → **0 resultados**. Los 4 callers reales son
`backend/main.py:7871` (venta), `backend/main.py:16855` (tenencia),
`backend/importing/rebuild.py:527` y `backend/importing/persister.py:484`. Ninguno es de lectura.

Es el **único lugar donde el split deja números INCOMPLETOS, no repartidos**: pedir el reporte
de "IOL" hoy excluye operaciones, monthly_entries y posiciones de "IOL · USD". Capital aportado,
P&L realizado, top holdings y concentración salen sistemáticamente por debajo.
Y `brokers_count` (`backend/main.py:17777-17783`) es un `COUNT(DISTINCT broker)` que **no aplica
el `br_clause`**, así que cuenta el sibling siempre y muestra "en 2 brokers".

Hoy esa contradicción está tapada porque el usuario acepta que son dos cuentas. **Una tarjeta
unificada la vuelve visible entre dos pantallas.**

#### A3 · El tab Dashboard de la MISMA pantalla valúa la pata USD a costo (P&L exactamente 0)

`frontend/src/pages/Dashboard.jsx:134-136` pide el ticker **pelado** para todo broker no-ARS:
`.map(p => p.asset)`. Pero `computeBrokerValue` para un broker `arUsd` busca
`prices[priceSymbol(p.asset, true, p.asset_type)]` = `'<ASSET>.BA'` (`valuation.js:227-233`)
→ miss de precio → `value += realCost` → P&L 0.

`Cartera.jsx:136-138` hostea Positions + Dashboard + Goals como tabs de la misma página: a un
clic de la tarjeta unificada el usuario ve dos StatCards, una con P&L 0,0%. Peor: esas tenencias
a costo se persisten en el snapshot diario (`Dashboard.jsx:302`) → contamina la serie histórica.

Variante parcial en `HomeMobile.jsx:90` (`priceSymbol(p.asset, false, p.asset_type)`: sólo agrega
`.BA` si `asset_type === 'CEDEAR'`, así que PAMP/YPFD quedan afuera).

El fix ya existe en 6 superficies: `Positions.jsx:457-461`, `PositionsMobile.jsx:351`,
`useMonthlyData.js:193`, `Insights.jsx:237-240`, `Goals.jsx:68`, `MonthlySummary.jsx:266`.

#### A4 · La regex del nombre es el contrato de PRECIO, no el de identidad

`isArUsdBroker` es `/·\s*USD$/` sobre el nombre (`valuation.js:108-110`), espejada en
`backend/snapshots_job.py:51` y `backend/behavioral.py:42` (más una cuarta variante laxa en
`behavioral.py:145-153` que acepta `'·usd'`, `'- usd'` y `' usd'`).

De ahí sale si un CEDEAR/acción AR se cotiza por su `.BA` o por el ticker US. **Si la vista
unificada propaga el nombre del padre a un lote del sibling, vuelve el bug C1: 15-100× inflado.**
Regla dura: nunca sustituir `p.broker` por el nombre de la cuenta, ni al mostrar ni al escribir.

#### A5 · La cuota de plan cuenta el sibling

`backend/ai/plan.py:138-140` — `SELECT COUNT(*) AS c FROM brokers WHERE user_id = ?`, contra
`brokers_max` (free = 1). `_ensure_usd_sibling` inserta directo (`backend/main.py:7505-7508`) sin
pasar por la cuota. Un Free queda bloqueado en 2 apenas importa un broker AR con una fila en
dólares — y el ruteo se auto-detecta (`backend/importing/pipeline.py:477-485`).
Si el producto va a presentar el par como UNA cuenta, el conteo y el discurso comercial dejan de
coincidir.

#### A6 · Consumidores que van a contradecir la tarjeta

- `frontend/src/utils/insightsModel.js:411-418` + `diagnostics.js:94-99`: el riesgo de
  concentración por plataforma (>70%) **nunca dispara** porque el par divide el share.
- `diagnostics.js:448-454`: el "% custodiado en brokers ARS" **excluye al sibling** (su currency
  es `'USDT'`) aunque la plata esté en el mismo custodio argentino.
- `diagnostics.js:808-833`: el sibling con dólares parados figura como **un broker entero ocioso**.
- `backend/ai/builders/dashboard_brokers.py:44-88` y `dashboard_composition.py:52-53`: la IA
  publica `broker_count` inflado y `top1_pct` diluido → le dice al usuario algo distinto de lo
  que ve en pantalla.

---

### 3.C — Descartados (los evalué y no aplican)

- ~~"La fila unificada pierde el sufijo y el CEDEAR se precia con el ticker US (2.700%)"~~ —
  no puede ocurrir si se conserva la clave `${asset}::${ccy}` (`Positions.jsx:846`), porque la
  rama de precio la elige `isARS` de la sección (`:1301`), no `p.broker`. Además la magnitud
  estaba mal calculada.
- ~~"`trustMktValue` compara valor USD contra costo mezclado y la fila cae a costo (750×)"~~ —
  el clamp hoy siempre recibe costo y valor en la misma moneda (`valuation.js:206-212` ARS-vs-ARS,
  `:241-244` USD-vs-USD). Y si se mezclaran, el daño primario sería el costo, no el clamp.
- ~~"La conversión interna ARS→USD hace que el par gane capital de la nada"~~ — el delta está
  compensado uno a uno en la valuación (`valuation.js:190-193` usa el mismo blue que
  `persister.py:885`), y `_update_monthly_flow` mueve `capital_final` en la misma dirección
  (`backend/main.py:6784`, `:6791`), así que el numerador de Modified Dietz queda invariante.
- ~~"Un alta manual apaga el rebuild FIFO del par permanentemente"~~ — es preexistente
  (`rebuild.py:527` y `:541` ya pasan el `pair`), no se persiste ninguna marca, y el neteo
  cross-currency vive en el persister (`persister.py:484-497`), no en el rebuild.

---

## 4. La decisión de diseño clave

Hay tres opciones y la diferencia se ve mejor con números. Tomemos el caso del enunciado:

> **100 GGAL comprados en pesos a ARS 1.000 c/u** (viven en "IOL", `currency='ARS'`, invested = ARS 100.000)
> **50 GGAL comprados por dólar-MEP a US$0,80 c/u** (viven en "IOL · USD", `currency='USD'`, invested = US$40)
>
> MEP de hoy: 1.450. Costo real total ≈ US$68,97 + US$40 = **US$108,97** (≈ ARS 158.000).

### Opción 1 — Fusionar LOTES (una fila por ticker) ❌

`_buildAgg` (`Positions.jsx:804-826`) haría `quantity = 150`,
`invested = 100.000 + 40 = 100.040`, `buy_price = 100.040 / 150 = **666,93**`.

Y ese número se imprime con un literal de moneda **hardcodeado por rama**: la tabla ARS escribe
`` `ARS ${ars(avgPriceArs)}` `` (`Positions.jsx:1527`), la USD escribe `USD ...` (`:1728`).

El usuario lee **"Precio prom. ARS 666,93"** e **"Invertido ARS 100.040"** para una posición cuyo
promedio real en pesos es ARS 1.053 y cuyo costo real es ARS 158.000. El 666,93 no corresponde a
ninguna compra que haya hecho: es la suma de pesos con dólares dividida por unidades.

Consecuencias en cadena: no se puede editar (no hay una moneda que mandar), no se puede vender
(`openSell` manda un solo broker), no se puede registrar amortización, y `lots[0].broker` es
arbitrario.

### Opción 2 — Agrupar JERÁRQUICAMENTE (una tarjeta, filas por moneda) ✅

Una sola tarjeta "IOL", un solo header, un solo total, y **dos filas**:

| Activo | Cant. | Precio prom. | Invertido | Broker real |
|---|---|---|---|---|
| GGAL `$` | 100 | ARS 1.000,00 | ARS 100.000 | `IOL` |
| GGAL `US$` | 50 | US$ 0,80 | US$ 40 | `IOL · USD` |

Pie de la tabla, que es literalmente lo que muestra la pantalla de tenencia de un broker AR:

```
Subtotal ARS      ARS 100.000   (valor ARS)
Subtotal USD      US$ 40        (valor USD)
TOTAL             US$ 108,97    (o ARS 158.007 según el toggle)
```

Los dos promedios tienen unidad y son verdaderos. **Las dos filas siguen editables, vendibles y
con cupón**, porque `p.broker` sigue siendo un nombre real y unívoco. Hay **una sola conversión
en toda la tabla** y está visible, en la línea TOTAL, auditable contra los dos subtotales nativos.

Lo que no entrega: el renglón único por ticker. Contraargumento: **ningún broker real lo entrega
tampoco** — Cocos muestra AL30 y AL30D como dos líneas, y el saldo en pesos separado del saldo en
dólares.

### Opción 3 — Fusionar sólo TOTALES (fila única con `avg_price = null`)

Una fila: `GGAL · 150 un. · Precio prom. — · Invertido US$108,97 · MIXED`, read-only.

Precedente vivo en el repo: `backend/ai/builders/position.py:72-84` marca `currency='MIXED'` y
devuelve `avg_price = None` cuando los lotes no comparten moneda. Es la forma **honesta** de
fusionar.

Pero: (a) el "Invertido US$108,97" se mueve **todos los días** con el MEP aunque el usuario no
opere, porque el costo se convierte al TC de hoy (`valuation.js:199`, decisión deliberada del
FX-phantom fix, con test en `valuation.test.js:130`); (b) la fila queda read-only y el usuario
pierde el camino descubrible para corregir un lote mal importado; (c) el único FX histórico en la
DB es `fx_rates_daily.blue_venta` (`backend/main.py:884-889`) — **no hay MEP histórico**, así que
ni siquiera se puede congelar el promedio.

### Veredicto

**Opción 2.** La 1 produce números falsos por construcción. La 3 es honesta pero entrega menos
(read-only) por un renglón que el broker real tampoco da. La 2 entrega el 90% del valor
("entro y veo todo junto") conservando el invariante que ya protege la app.

**Dato que refuerza la elección:** en `backend/trading.db` hay 2 pares reales
(`IOL`/`IOL · USD` id 159, `Balanz`/`Balanz · USD` id 183) y **cero casos** del mismo ticker en
las dos patas:

```sql
SELECT a.broker, b.broker, a.asset FROM positions a
JOIN positions b ON b.user_id=a.user_id AND b.asset=a.asset
                AND b.broker = a.broker || ' · USD'
WHERE a.is_cash=0 AND b.is_cash=0;   -- → 0 filas
```

Y cero lotes con `currency` USD viviendo en un broker padre ARS. O sea: **con la opción 2, hoy
todas las filas quedan editables**. La fila "mixta" es un caso teórico que hay que cubrir, no uno
instanciado.

---

## 5. Recomendación

Vista jerárquica (opción 2), en tres fases, con un kill switch de build.

### FASE 0 — Prerequisitos (deployables solos, sin flag, valen aunque el resto no se haga)

Son 6 bugs vivos hoy. Ninguno lo introduce este cambio; todos los convierte en camino principal.

| # | Qué | Archivo |
|---|---|---|
| 0.1 | Borrar el sibling explícito antes del padre en `delete_broker` | `backend/main.py:2869` |
| 0.2 | Usar `rowKey` (ya desestructurado) en vez de `` `t:${p.asset}` `` | `frontend/src/pages/Positions.jsx:1424, 1495, 1560, 1632` |
| 0.3 | Símbolos `.BA` para el sub-broker | `frontend/src/pages/Dashboard.jsx:134-136`, `frontend/src/pages/HomeMobile.jsx:90` |
| 0.4 | Clave `${asset}::${ccy}` + `investedUsd`/`pnlLocal` por lote (no `lots[0].isAR`) | `frontend/src/pages/PositionsMobile.jsx:449-516, 555-602` |
| 0.5 | Campos **aditivos** `valueArsDisp`/`invArsDisp` que llenen **las dos** ramas | `frontend/src/utils/valuation.js:170-258` |
| 0.6 | `AND broker IN (...)` vía `broker_pair` + `br_clause` en el `COUNT(DISTINCT)` + cuota sin sibling | `backend/reporting/builder.py:93-103, 152`, `backend/reporting/timeline.py:111`, `backend/main.py:17777`, `backend/ai/plan.py:138` |

Detalle de 0.1:
```python
# antes del DELETE del padre
conn.execute("DELETE FROM brokers WHERE user_id=? AND parent_broker_id=?", (uid, bid))
conn.execute("DELETE FROM brokers WHERE id=? AND user_id=?", (bid, uid))
```

Detalle de 0.5 (no tocar la firma ni ningún campo existente):
```js
// rama ARS: valueArsDisp = valueArs ; invArsDisp = invArs
// rama USD: valueArsDisp += (valor USD de la posición) * cedearRate
//           invArsDisp   += (costo USD de la posición) * cedearRate
```
Documentar en el docstring: **`valueArs` NO es sumable cross-broker; `valueArsDisp` sí.**

Detalle de 0.6 — cuidado con el doble conteo: una conversión ARS→USD escribe un `withdraw` en el
padre y un `deposit` en el sibling (`backend/importing/persister.py:884-889`). Sumar
`deposits`/`withdrawals` de las dos patas cuenta **dos veces** la misma plata moviéndose adentro
del mismo broker real. El capital aportado de la cuenta hay que netear las conversiones internas,
o el fix cambia un número incompleto por uno inflado.

**Listo cuando:** existe un test que borra un padre con sibling contra una DB creada por ALTER
(sin CASCADE) y pasa; "Ver lotes" expande N filas en un agregado multi-lote; el P&L de la pata USD
en Dashboard deja de ser exactamente 0; `npm test` pasa **sin editar** `valuation.test.js`;
el reporte de "IOL" incluye las operaciones de "IOL · USD".

---

### FASE 1 — Tarjeta de cuenta en desktop

**1.1 · Helper de agrupación** — nuevo `frontend/src/utils/brokerAccounts.js`:
`groupBrokersIntoAccounts(brokers)` → `[{ key, label, parent, patas: [broker...], isPair }]`.
Agrupa **exclusivamente por `parent_broker_id`**, nunca por el sufijo del nombre. Conservar el
caso del hijo huérfano que `sortBrokersForDisplay` ya contempla (`Positions.jsx:2378-2383`) → sale
como cuenta propia. Hacer que `sortBrokersForDisplay` consuma este helper, para no tener dos
constructores de árbol.
Comentario obligatorio en el módulo: *el `label` es sólo para mostrar; nunca se escribe en
`p.broker` ni se manda a ningún endpoint.*

**1.2 · Colapsar las dos tablas en una** (`Positions.jsx:1398-1607` y `:1610-1795`). Es el grueso:
~400 líneas duplicadas, la ARS con 11 + 3 columnas de "Detalle" y `colSpan` hasta 14
(`:1449`), la USD con 11 fijas. Un `<AccountTable>` con un set de columnas: Activo (sticky,
+ chip `$` / `US$`) · 30D · Cantidad · Precio prom. · Precio actual · Invertido · Valor · P&L ·
P&L % · Var. día · [Detalle] TC Compra · [Detalle] Valor USD · menú. Cada celda de plata imprime
el prefijo de la moneda **de la fila**.

**1.3 · `calcRow(p, ccy)`** reemplaza `calcARS`/`calcUSDT` (`Positions.jsx:879-931`), separando los
dos ejes igual que hace el backend (`behavioral._native_ccy` vs `_price_is_ars`):
(a) moneda del **costo** = `ccy` de la fila; (b) mercado del **precio** =
`wantsBA = ccy === 'ARS' || p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker)`, usando
**siempre `p.broker` real**. Ojo: `_rowSortKeys` (`:777-797`) tiene que ordenar por valor en USD,
o en una tabla mixta ARS 1.500.000 queda arriba de US$50.000.

**1.4 · Pool de lotes cross-pata, clave intacta.** `bposRaw` pasa de `p.broker === broker.name`
(`Positions.jsx:1307`) a `patasNames.has(p.broker)`. La clave del grupo **no cambia**: sigue
siendo `${p.asset}::${ccy}` (`:846`). En `_buildAgg`, agregar
`const mixed = new Set(lots.map(l => l.broker)).size > 1` y, si es true, devolver
`broker: null` (nunca `lots[0].broker`) + `_multiBroker: true`.

**1.5 · Header + pie de 3 líneas.** Llamar `computeBrokerValue` **una vez por pata** (firma
intacta → los otros 11 call-sites no se tocan) y sumar. Header con `Σ value` (USD) o
`Σ valueArsDisp` (ARS) según el toggle global — **prohibido sumar `valueArs`**. Pie:
`Subtotal ARS` (de la pata ARS: `valueArs`/`invArs`/`pnlArs`, correctos para un broker ARS) ·
`Subtotal USD` (de la pata USD: `value`/`invested`/`pnlUsd`) · `TOTAL` en la moneda de display.
Var. día: acumular por fila convertida a USD (hoy `Positions.jsx:1321-1327` suma deltas en moneda
nativa cruda).

**1.6 · Guard por FILA, no por modo.** Sólo la fila con `_multiBroker` pierde escritura. Ítems:
"Ver lotes (N)" + "Editar en la pata" (expande los lotes). Se sacan: Editar, Eliminar, Registrar
venta, Agregar compra, cupón, amortización, InlineAIButton. **Cubrir los dos entrypoints de bono**
(`Positions.jsx:1574-1575` y `:1765-1766`, que no pasan por `buildPositionMenu`).
Guard estructural además del flag: que `openSell`, `openAdd` y `openBondCashflow` **tiren** si
reciben `broker == null` — el precedente es que el guard `isAgg` ya existe y los botones de bono
ya lo esquivan.

**1.7 · Estado y filtros por cuenta.** El dropdown "Broker" (`Positions.jsx:1226-1231`, `:1299`)
lista una opción por cuenta (hoy filtrar por el padre **esconde** al sibling). `detailBrokers`
(`:133-134`, `:1314`, `:1365`) pasa a ser un Set de `account.key`. **Crítico**: el botón "Agregar"
del header (`:1372`) hoy hace `openAdd(broker.name)` → en una cuenta de 2 patas hay que llamar
`openAdd()` **sin argumento** para que `AddPositionFlow` pida la pata (`AddPositionFlow.jsx:53`).

**1.8 · Lápiz y tacho.** Apuntan siempre al **padre** (`account.parent.id`): el backend ya prohíbe
renombrar el sibling (`backend/main.py:2594-2601`) y ya deriva `f"{new_name} · USD"` (`:2641`).
Agregar `try/catch` a `saveEditBroker` (`PositionsMobile.jsx:382-388` y
`BrokerManager.jsx:64-70`, hoy sin catch: el 400 falla en silencio con el modal abierto).

**1.9 · Kill switch de build** (injertado): `VITE_UNIFIED_ACCOUNTS !== '0'`. **Sin** toggle por
usuario — no queremos dos modos permanentes que puedan divergir; queremos poder apagar desde
Railway sin revertir 600 líneas.

**Listo cuando:** una cuenta de UNA sola pata (Schwab, Binance, un broker ARS sin sibling)
renderiza **exactamente lo mismo** que hoy (diff visual de los tres casos); el total de la tarjeta
en USD == la suma de los dos totales de hoy; un CEDEAR/bono del sibling sigue pidiendo `.BA`;
vender desde una fila normal de la pata USD manda el nombre **real** del sibling y `currency:'USD'`.

---

### FASE 2 — Mobile

Consumir el mismo `groupBrokersIntoAccounts`: `grouped` (`PositionsMobile.jsx:619-642`) mapea por
`account.key`; un chip de filtro por cuenta (`:757-765`); `ColumnHeader` (`:1252`, `:1332`) gana
un valor `MIXED` que rotula en la moneda de display; la moneda de la fila
(`:1374 const cur = p.isAR ? 'ARS' : 'USD'`) sale del lote (ya resuelto en 0.4).

**Cuidado**: el layout está clavado a offsets calculados a mano sobre la altura actual del header
(`sticky top-[88px]` en `:687`, `sticky top-[252px]` en `:1289`). No agregar filas al header.

**Listo cuando:** el mismo usuario cruzando 768px ve la misma estructura y el mismo total.

---

### FASE 3 — Que el resto deje de contradecir la tarjeta

Por orden de daño: StatCards del Dashboard por cuenta (`Dashboard.jsx:957-982`);
`BrokerSelector.jsx:31-35` emite la cuenta; packets de IA con `account`
(`backend/ai/builders/dashboard_brokers.py:44-88`, `dashboard_composition.py:52-53`,
`Insights.jsx:1705`); `home.py:196` e `insights.py:396` usando `_price_is_ars` en vez de la lista
hardcodeada / el substring; los tres diagnósticos de `diagnostics.js` (`:94-99`, `:448-454`,
`:808-833`).

**Listo cuando:** la IA dice "1 cuenta" cuando la pantalla dice 1 cuenta, y la alerta de
concentración por plataforma dispara con la cartera del par.

---

## 6. Lo que NO haría

1. **Fusionar lotes de distinta moneda en una fila.** Es la opción 1 del §4 y produce un
   `buy_price` sin unidad por construcción (`Positions.jsx:822`). La clave `${asset}::${ccy}`
   (`:846`) existe desde hace tiempo, con un comentario que explica exactamente por qué. No la
   saquen.
2. **Un toggle unificado/separado.** Dos caminos de agregación que tienen que dar el mismo número
   para siempre, más un default que decide quién ve la feature. En un repo cuyo historial es una
   sucesión de "dos copias de la misma lógica divergieron" (desktop vs mobile con claves distintas,
   4 copias de la matriz de valuación, 9 copias de la cascada de `tcCedear`), un modo permanente es
   la fábrica del próximo incidente. Kill switch de build sí; toggle de usuario no.
3. **Agregar una TERCERA rama de tabla** al lado de las dos existentes. Es más barato hoy
   (~3 días menos) y es exactamente cómo se llegó al problema actual.
4. **Reescribir `computeBrokerValue`** (extraer un `valuePositionUsd` y montar la función encima).
   Toca 12 call-sites en 9 archivos (`Positions.jsx:984` y `:1315`, `Dashboard.jsx:165`,
   `Insights.jsx:267/363/730`, `HomeMobile.jsx:108`, `Goals.jsx:75`, `Events.jsx:148/160`,
   `FirstInsight.jsx:88`, `useMonthlyData.js:437`, `MonthlySummary.jsx:274`) para una feature que
   se resuelve con dos campos aditivos (0.5). Los 110 tests cubren el **motor**, no el render.
5. **Reconstruir la capa de lectura del backend** (`/api/portfolio/view` con SSoT de
   cuenta/FX/valuación). Es el destino correcto a 12 meses y arregla de raíz A2, A3 y A6. Pero son
   17-20 días, ~28 archivos, tres motores de valuación conviviendo durante la migración, la Cartera
   pasando a depender de un endpoint que pega precios live (hoy `/api/positions` es un SELECT puro,
   `backend/main.py:5685`) sobre el cold start de Railway, y —lo peor— **mover números que hoy el
   usuario ya vio**: `behavioral._position_value_usd` y `snapshots_job.compute_broker_value_usd`
   difieren en cómo aplican el factor cripto y en la base de comparación de `trustMktValue`.
   Para un pedido de layout, es desproporcionado.
6. **Fusionar `monthly_entries` a nivel dato.** `UNIQUE(user_id, year, month, broker)`
   (`backend/main.py:588`) y el rename ya devuelve 409 por eso (`:2574-2576`). La suma de las dos
   cadenas es **en lectura**.
7. **Renombrar o normalizar el nombre del sibling.** Es el contrato de PRECIO
   (`valuation.js:108-110` + `snapshots_job.py:51` + `behavioral.py:42`). Romperlo trae de vuelta
   el bug C1.

---

## 7. Estimación

| Fase | Días | Archivos | Riesgo |
|---|---|---|---|
| 0 — Prerequisitos | 2,5 | 9 (`main.py`, `plan.py`, `builder.py`, `timeline.py`, `Positions.jsx`, `PositionsMobile.jsx`, `Dashboard.jsx`, `HomeMobile.jsx`, `valuation.js`) | Bajo — bugfixes aislados, mergeables de a uno |
| 1 — Tarjeta desktop | 5-7 | 3 (`Positions.jsx`, `brokerAccounts.js` nuevo, `flags.js` nuevo) | **Alto** — colapsar 2 árboles de JSX es donde salen los bugs (colSpan, sticky, modo compacto) |
| 2 — Mobile | 2-3 | 2 (`PositionsMobile.jsx`, `PositionDetailMobile.jsx`) | Medio |
| 3 — Consistencia | 3-4 | 8 (`Dashboard.jsx`, `BrokerSelector.jsx`, `Insights.jsx`, `diagnostics.js`, `insightsModel.js`, 3 builders de IA) | Bajo |
| **Total** | **13-16** | **~20** | |

El entregable de escritorio (Fase 0 + 1) sale en **7-9 días**. Las fases 2 y 3 son separables y
valen por sí solas.

No incluido y conviene presupuestar aparte: el bug de `/api/positions/sell` que sigue la moneda
del **broker** en vez de la de la venta (`backend/main.py:7853` vs `:7951` vs `:8005`). Es
preexistente, alcanzable hoy, y son **0,5-1 día** con test.

### Cómo se apaga si sale mal

1. **Fase 1-2**: `VITE_UNIFIED_ACCOUNTS=0` en Railway + redeploy. Vuelve a las dos tarjetas sin
   revertir código. Nada de esto escribe en la DB, así que no hay estado que deshacer.
2. **Fase 0**: no tiene apagador porque son bugfixes, pero cada uno es un commit chiquito y
   revertible por separado. Mergearlos de a uno, con unos días entre medio, para que el ruido de
   diagnóstico no se mezcle con el de la tabla.
3. **Gate de merge para 0.5**: `npm test` pasa con **cero** ediciones a `valuation.test.js`. Si hay
   que tocar un test, el cambio movió comportamiento y hay que volver atrás.
4. **Gate de merge para 1.3**: correr `calcARS`/`calcUSDT` viejos y `calcRow` nuevo sobre todas las
   posiciones de la DB y listar las que se mueven >1%. Si la lista no está vacía y no se explica
   fila por fila, no se mergea. (Es la práctica que ya se usó en el audit de benchmark.)

---

## 8. Incertidumbres

Cosas que **no** pude verificar y que hay que chequear antes de empezar:

1. **Los datos de producción.** Todo lo que verifiqué es contra `backend/trading.db`, que es la DB
   de desarrollo local. Prod corre Postgres/Supabase o SQLite en Railway según la memoria del
   proyecto. **Antes de tocar 0.1, confirmar que el schema de prod también tiene el FK sin
   `ON DELETE CASCADE`** (`PRAGMA foreign_key_list(brokers)` en SQLite, o
   `information_schema.referential_constraints` en PG). Si prod es PG, el DDL puede diferir del
   ALTER de `main.py:404`.
2. **Cuántos usuarios tienen realmente un par.** En dev hay 2 (`IOL`/`IOL · USD` id 159,
   `Balanz`/`Balanz · USD` id 183). No sé el número en prod, y eso decide si la feature vale 13-16
   días. Query: `SELECT COUNT(DISTINCT user_id) FROM brokers WHERE parent_broker_id IS NOT NULL`.
3. **Cuántos usuarios tienen el mismo ticker en las dos patas.** En dev: cero. Si en prod también
   es cero o casi, la fila `_multiBroker` es un caso teórico y el guard de 1.6 se puede simplificar
   mucho. Si es común, hay que diseñar la UI de esa fila con más cuidado.
4. **No corrí la suite de tests.** Según la memoria del proyecto el comando es `pytest tests/`
   (~52 s) desde `backend/`, y `pytest` pelado colecta `scripts/test_*.py` y falla. No verifiqué
   que la suite esté verde hoy en esta rama (`fix/ai-stale-position` tiene ~40 archivos
   modificados sin commitear).
5. **No verifiqué el render.** Todo el análisis del frontend es lectura de código. No monté la app
   ni comparé screenshots, así que la afirmación "una cuenta de una sola pata renderiza igual" es
   un **criterio de aceptación**, no algo que haya comprobado.
6. **El comportamiento de `calcRow` sobre lotes legacy.** En dev hay cero lotes con `currency`
   USD/USDT en un broker padre ARS, así que no pude observar el caso que 1.3 cambia. En prod puede
   haber lotes con `currency` NULL que el backfill del boot (`backend/main.py:512-526`) etiquetó
   por la moneda del broker; ahí la unificación de `calcARS`/`calcUSDT` puede mover números.
   Por eso el gate del §7.4.
7. **`bond_cashflow_skips` y `import_normalized_tx` en el delete.** El propio código documenta que
   `delete_broker` no las limpia (`backend/main.py:2546-2549`, "orphan gap conocido"). El fix de
   0.1 no lo toca — sigue siendo deuda, y no la evalué.
8. **Múltiples siblings.** `POST /api/brokers` acepta un `parent_broker_id` arbitrario y sólo
   valida que el padre exista (`backend/main.py:2502-2510`), mientras `rename`/`delete`/
   `_wipe_broker_data` resuelven el sibling con `.fetchone()` (`:2637`, `:2797`, `:10931`) y
   `broker_pair` usa `.fetchall()` (`persister.py:85-89`). No verifiqué si existe algún usuario con
   2 hijos; el helper de 1.1 debería soportar N patas de todas formas.
