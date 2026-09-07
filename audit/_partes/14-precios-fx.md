## 14. Capa de precios y tipos de cambio

Auditado sobre `origin/main` @ `b74f450f` (2026-09-05). Todo lo marcado `[V]` está leído en el
código con su cita; lo marcado `[I]` es inferencia y digo de qué me agarré.

> **Nota sobre la base de desarrollo.** `backend/trading.db` viene de una rama vieja: su
> `fx_rates_daily` **no tiene la columna `mep_venta`** y **no existen** las tablas
> `asset_price_history` ni `price_backfill_log` (`sqlite3 backend/trading.db ".schema"`).
> Sirve para confirmar la existencia y forma de `fx_rates_daily` (5.634 filas, 2011-01-03 →
> 2026-08-26), `fci_prices` (117 filas), `fci_catalog` y `asset_last_price`, pero **el código
> manda** para todo lo demás. `[V]`

---

### 14.1 Mapa de una mirada

```
                 ┌──────────────── dolarapi.com/v1/dolares/{casa} ────────────────┐
                 │  blue · bolsa(=MEP) · contadoconliqui(=CCL) · cripto           │
                 └───────────────────────────┬───────────────────────────────────┘
                                             │ _fetch_dolar (timeout 5s)
                                   _dolar_cache (in-memory, TTL 300s)
                                             │
     ┌───────────────────────┬────────────────┼─────────────────────┬──────────────────┐
 _display_blue          _display_ccl    _current_ccl        _current_cedear_rate  _current_cripto_rate
 (blue.venta)           (ccl→mep→cripto) (ccl→mep→cripto)    (mep→ccl→cripto)      (cripto.venta)
     │                       │                │                     │                    │
     └── cripto en broker ARS│                │                     │                    │
                             └─ CEDEAR USD-cotizado (BAC)           └─ TODO el path ARS ─┘

  PRECIOS
  data912.com/live/{arg_bonds,arg_corp}  → bonos/ONs AR    (cache 300s)
  data912.com/live/{arg_cedears,arg_stocks} → CEDEARs/.BA  (cache 300s)   ← PRIMARIO para .BA
  yfinance (yf.download period="1mo")    → US, cripto, y fallback de .BA
  fci_prices (ArgentinaDatos/CAFCI)      → FCI, refresco 1×/día
  asset_last_price                       → último conocido, SIN TTL
```

---

### 14.2 Tabla maestra de precios

Todas las funciones son de `backend/main.py` salvo aclaración. La resolución del **símbolo**
(qué se pide) vive en `backend/snapshots_job.py:105` (`position_price_key`) del lado backend y
en `frontend/src/utils/valuation.js:81` (`priceSymbol`) del lado frontend.

| Tipo de activo | Fuente primaria | función:línea | Fallback 1 | Fallback 2 | Cache / TTL | Unidad | Moneda del precio |
|---|---|---|---|---|---|---|---|
| **Acción US** (AAPL, BRK-B) | yfinance batch `yf.download(period="1mo")` | `backend/main.py:7746` | `_fetch_one` per-símbolo (`backend/main.py:7142`) | `_fetch_one(f"{sym}-USD")` si no es `.BA` ni cripto (`backend/main.py:7809-7810`) | `_PRICE_CACHE` 60 s (`backend/main.py:7400`) | per-1 | USD |
| **CEDEAR / acción AR** (`XXX.BA`) | data912 `arg_cedears`+`arg_stocks` — **PRIMARIO** | `_resolve_ar_equity_price` `backend/main.py:7300`, prefetch en `backend/main.py:7683-7687` | yfinance batch | `_resolve_ar_equity_price` de nuevo (post-yfinance, `backend/main.py:7804`) y después `_fetch_one` | `_data912_eq_cache` 300 s (`backend/main.py:7212` `DATA912_TTL`) | per-1 | **ARS** |
| **CEDEAR cotizado en USD** (solo `BAC`) | ticker US de yfinance × CCL ÷ ratio | `CEDEAR_USD_RATIOS` `backend/main.py:7125`; conversión `backend/main.py:7830-7833` | — (si no hay CCL, queda sin convertir: el `if` no entra y el precio queda **en USD**) | `_fill_last_known_prices` | igual que acción US | per-1 | **ARS** (tras × CCL ÷ ratio) |
| **Bono AR / ON / BOPREAL / CER** | data912 `arg_bonds`+`arg_corp` | `_resolve_ar_bond_price` `backend/main.py:7329` | yfinance (`.BA`) — sin ÷100 | `_fill_last_known_prices` | `_data912_cache` 300 s (`backend/main.py:7211-7212`) | **per-1** (÷100 solo si clasifica como per-100, `backend/main.py:7355-7357`) | ARS si `.BA`; USD si ticker + `D` |
| **Cripto en exchange / broker USD** | yfinance `<COIN>-USD` (`CRYPTO_YF`, `backend/main.py:7115`) | `backend/main.py:7746` | `_fetch_one` | last-known | 60 s | per-1 | USD (spot) |
| **Cripto en broker ARS** (`BTC.BA`) | yfinance `<COIN>-USD` **× dólar cripto** | `backend/main.py:7704-7714`, conversión `backend/main.py:7823-7825` | rate: `_current_cripto_rate()` → `_current_cedear_rate()` → `_display_blue()` | last-known | 60 s | per-1 | **ARS** |
| **FCI** (`FCI:<slug>`) | `fci_prices` (ArgentinaDatos/CAFCI) | `pricing/fci.get_prices_detail_for` `backend/pricing/fci.py:321`; consumo `backend/main.py:7620-7631` | ninguno (si no hay fila, no aparece en el dict) | **no pasa por `_fill_last_known_prices`** (se mergea después del cache) | fila en DB, refresh cron 12:10 UTC (`backend/main.py:32570-32574`) | **per-1** (`vcp/1000`, `backend/pricing/fci.py:287`) | ARS o USD según `fci_catalog.moneda` |
| **Plazo fijo** | **no cotiza** — devengado determinístico | `computePf` `frontend/src/utils/valuation.js:797`; espejo backend `_pf_value` | — | — | — | — | ARS o USD (`plazos_fijos.moneda`) |
| **Futuro** | precio spot del `base_asset` vía `/api/prices` | `frontend/src/components/FuturosGroup.jsx:63` | — | — | 60 s | per-1 | USD |
| **Efectivo (cash)** | no se precia: `invested` **es** el saldo | `backend/snapshots_job.py:214-224` | — | — | — | — | moneda del broker |

**Cosas que la tabla no dice y hay que saber:**

- `[V]` **data912 va PRIMERO para todo `.BA`, no solo bonos.** El prefetch de
  `backend/main.py:7679-7690` intenta bono y después equity; lo que resuelve nunca llega a
  yfinance. El motivo está documentado en `backend/main.py:7261-7276`: yfinance devuelve
  ruedas `.BA` con volumen pero **OHLC en NaN**, y tickers congelados (el comentario cita
  `DISN.BA` clavado en 10.416 durante 15 días).
- `[V]` `_resolve_ar_equity_price` (`backend/main.py:7307-7308`) **excluye a propósito** cripto
  (`BTC.BA` no cotiza en BYMA) y los `CEDEAR_USD_RATIOS`, que tienen camino propio.
- `[V]` La clasificación **per-100 vs per-1** de bonos no usa la allowlist: usa la magnitud en
  USD-equivalente, con umbral 3 USD (`backend/main.py:7355-7357`). Para el path ARS el
  USD-equivalente se saca del **MEP implícito de data912** (`_data912_peso_per_usd`,
  `backend/main.py:7245`), que si no encuentra un par soberano usable devuelve **1450.0
  hardcodeado** (`backend/main.py:7256`).
- `[V]` `AR_BONDS_DATA912` (`backend/main.py:7194`) **ya no se usa para preciar**. Sus dos
  únicos usos vivos son excluir bonos del fetch de noticias/eventos
  (`backend/main.py:6080` y `backend/main.py:35321`). El nombre engaña.
- `[V]` **Cap duro de 60 símbolos con truncado silencioso**: `MAX_SYMBOLS = 60`
  (`backend/main.py:7139`), aplicado en `backend/main.py:7637` (`/api/prices`) y
  `backend/main.py:7881` (`/api/prices/prev-close`). El propio código lo documenta como
  problema en `backend/main.py:37265-37266`. El frontend **no chunkea**: manda todos los
  símbolos en una URL (`frontend/src/pages/Positions.jsx:577-580`).

---

### 14.3 Cachés y TTLs (todos in-memory por proceso)

| Cache | Constante | TTL | Qué guarda |
|---|---|---|---|
| `_dolar_cache` | `DOLAR_TTL` `backend/main.py:4603` | 300 s | las 4 casas de dolarapi |
| `_PRICE_CACHE` | `_PRICE_CACHE_TTL_S` `backend/main.py:7400` | 60 s | precio por símbolo, **incluye los `None`** (`backend/main.py:7443-7444`) |
| `_PRICE_META` | mismo TTL | 60 s | `{src, as_of, stale}` por símbolo |
| `_PREVCLOSE_CACHE` | `backend/main.py:7580` | 600 s | cierre anterior |
| `_data912_cache` / `_data912_eq_cache` | `DATA912_TTL` `backend/main.py:7212` | 300 s | quotes de data912 |
| `_history_cache` | `_HISTORY_TTL_S` `backend/main.py:8040` | 3600 s | serie del mini-chart |
| `_QUOTE_CACHE` (`backend/home/market.py:264`) | `_QUOTE_TTL_S` | 60 s | quotes del watchlist / behavioral |
| `_last_price_buf` | `_LAST_PRICE_FLUSH_S` `backend/main.py:7501` | flush ≤ 1×/min | buffer de escritura a `asset_last_price` |
| `_LIVE_VALUE_CACHE` (`backend/snapshots_job.py:808-809`) | 60 s | valor vivo del portfolio por `(uid, tc_blue)` |

`[V]` El buffer de último-precio existe porque `/api/prices` **escribía en cada request** y en
SQLite eso era una cola que no drenaba (`backend/main.py:7484-7500`, cita literal del log:
`persist_last_prices falló: database is locked`). Se baja a disco en el shutdown hook con
`forzar=True` (`backend/main.py:32598-32601`).

`[V]` **`_fetch_batch_quotes` es una segunda vía de precios que NO pasa por data912.** Vive en
`backend/home/market.py:267`, usa `yf.download(period="5d")` y su fallback per-símbolo es
`yf.Ticker().history()`. La consume `analysis_prep.fetch_ba_aware_prices`
(`backend/analysis_prep.py:53-77`), que sí pide `.BA`. `[I]` Con eso, Análisis / behavioral /
goals / wrapped se valúan con el yfinance que el resto del sistema declaró no confiable para
`.BA` — la barra NaN y el ticker congelado que motivaron el cambio en `/api/prices` siguen
mordiendo por acá. Me agarro de que en `backend/home/market.py` no hay ninguna mención a
data912 (`grep data912 backend/home/market.py` → sin resultados).

---

### 14.4 Procedencia del precio (`__meta`) — cómo el sistema dice "esto es viejo"

`[V]` `/api/prices` devuelve, además de `{símbolo: número}`, una clave `__meta` con
`{src, as_of, stale}` por símbolo (`backend/main.py:7841-7853`). Valores de `src`:

- `'byma'` → data912 (`backend/main.py:7686`, `backend/main.py:7805`)
- `'yf'` → yfinance (`backend/main.py:7786`, `backend/main.py:7813`)
- `'last_known'` → completado desde `asset_last_price` (`backend/main.py:7840`)
- `'fci'` → `fci_prices`, con `as_of` = `as_of_date` de la fila (`backend/main.py:7625-7626`)

`stale = (src == 'last_known') or (src == 'yf' and as_of < newest_bar)`
(`backend/main.py:7848-7849`), donde `newest_bar` es la rueda más nueva **del lote**
(`backend/main.py:7758`). Lo muestra `frontend/src/components/StalePricesNotice.jsx:21`, un
único aviso arriba de Cartera (`frontend/src/pages/Positions.jsx:2002`).

`[V]` Un precio que viene de **data912** nunca se marca stale (no se le llena `as_of`) — el
`stale` solo mira `yf` y `last_known`. `[I]` O sea: si data912 devuelve un cierre viejo, el
aviso no aparece. Me agarro de que `px_as_of` solo se puebla en el bloque de yfinance
(`backend/main.py:7763-7772`).

---

### 14.5 Qué pasa cuando NO hay precio

Hay **cuatro** capas de degradación, en este orden:

**1. Último conocido (`asset_last_price`) — SIN límite de edad.**
`[V]` `_fill_last_known_prices` (`backend/main.py:7538`) completa los `None` primero desde el
buffer en memoria y después desde la tabla (`read_last_prices`, `backend/snapshots_job.py:589`).
`read_last_prices` **no filtra por `updated_at`**: un precio de hace un año se sirve igual. El
propio `backend/price_history.py:18-22` lo señala como bug conocido:

> «Es la misma clase de bug que `apply_last_known_prices`, que completa desde una tabla global
> sin TTL y deja la serie PLANA (peor que un hueco: el hueco se ve).»

La única excepción que sí chequea edad es el flujo de registro por chat, que rechaza un
last-known de más de 48 h (`backend/main.py:23451`).

**2. Guard anti-distorsión (`trustMktValue` / `_trust_mkt_value`).**
`[V]` Si el valor de mercado se aleja demasiado del costo, se **descarta el precio** y se usa el
costo: renta fija banda `[0.02×, 4×]`, resto `[0.002×, 50×]`
(`backend/snapshots_job.py:52`, espejo en `frontend/src/utils/valuation.js:448-453`). Un
`price_override` manual se respeta salvo en renta fija.

**3. Valor = costo (P&L 0 para esa fila).**
`[V]` En los cuatro caminos de `compute_broker_value_usd` el `else` sin precio hace
`value += inv_usd` / `value += real_cost` (`backend/snapshots_job.py:279`, `:264`, `:255`,
`:311`, `:315`). El frontend hace lo mismo (`frontend/src/utils/valuation.js:665`).
**Consecuencia sobre el total de la cartera:** la posición **no se excluye** — entra al total
con su costo. El total no queda "corto": queda **anclado al costo**, y la variación diaria de
esa fila es 0.

**4. La celda de precio muestra `—`.**
`[V]` En la tabla, cuando `avgPriceUsdDisp`/`invUsd`/`pnlUsd` son `null` se imprime `'—'`
(`frontend/src/pages/Positions.jsx:2453-2454`, `:2463`, `:2480`).

**Excepciones donde SÍ se excluye en vez de caer a costo:**

- `[V]` **Snapshot nocturno**: si la cobertura ponderada por costo cae por debajo del 95 %,
  **no se escribe la fila del día** (`backend/snapshots_job.py:729-742`, `MIN_COVERAGE = 0.95`).
  Fail-closed a propósito: prefiere un hueco a un dato subvaluado.
- `[V]` **Libro del asesor**: una posición sin precio conocido se **excluye** del agregado y se
  cuenta en `star.skipped_no_price` (`backend/main.py:36917-36921`).
- `[V]` **`ledger_replay.valor_en`**: devuelve `valor: None` con `motivo:
  "cobertura_insuficiente"` si no llega al 98 % (`backend/ledger_replay.py:33`,
  `backend/ledger_replay.py:310-313`).
- `[V]` **CEDEAR USD-cotizado en el snapshot**: si no hay CCL se deja en `None` explícitamente
  en vez de persistir el valor en USD roto (`backend/snapshots_job.py:504`).

⚠️ `[V]` **Agujero verificado: FCI en broker ARS con lote en pesos se valúa AL COSTO en el
snapshot.** `position_price_key` tiene un early-return que devuelve el símbolo tal cual para
`FCI:` (`backend/snapshots_job.py:116`), así que `prices` trae la clave `FCI:X`. Pero la rama
genérica ARS de `compute_broker_value_usd` busca `prices.get(f"{p['asset']}.BA")`
(`backend/snapshots_job.py:276`) → busca `FCI:X.BA`, que **no existe**. Y el guard de cobertura
usa `position_price_key` (`backend/snapshots_job.py:727`), o sea **cuenta esa posición como
"con precio"**: la foto pasa el 95 % y se escribe con el FCI al costo. El frontend NO tiene el
bug (`priceSymbol` chequea `FCI:` primero, `frontend/src/utils/valuation.js:82`), y el motor del
asesor lo parchea con un alias explícito (`backend/main.py:36893-36897`, comentario literal:
«el engine busca 'FCI:x.BA' pero el NAV vive como 'FCI:x'»). Sobrevive solo el lote con
`currency='USD'`, que entra por la rama `_cost_in_usd` (`backend/snapshots_job.py:254`).

---

### 14.6 ⚠️ Los dólares: inventario completo

`[V]` La app consume **cuatro** casas de `dolarapi.com` (`backend/main.py:4847-4850`) y ninguna
más. **No hay oficial, ni tarjeta, ni mayorista** (`grep oficial|tarjeta|mayorista` sobre
`backend/main.py` y los utils del frontend no devuelve ningún uso de cotización).

| Dólar | De dónde sale | Cada cuánto | Dónde se persiste | Para qué se usa |
|---|---|---|---|---|
| **Blue** | `dolarapi.com/v1/dolares/blue` (`backend/main.py:4608`) + histórico `api.argentinadatos.com/v1/cotizaciones/dolares/blue` (`backend/main.py:4722`) | live: TTL 300 s; histórico: backfill 1× al boot con la tabla vacía | `fx_rates_daily.blue_venta` (PK `date`) | red histórica de `fx_for_date` (pre-2018); stamp `snapshots.fx_to_usd_blue`; benchmark `dolar_blue` mensual; último recurso de `pickFinancialRate` |
| **MEP** (casa `bolsa`) | `dolarapi.com/v1/dolares/bolsa` + histórico `.../dolares/bolsa` (`backend/main.py:4811`) | live TTL 300 s; histórico solo cuando hay filas con `mep_venta IS NULL`, **al boot** | `fx_rates_daily.mep_venta` (NULLABLE) | **el riel canónico**: valuación de TODO el path ARS (holdings `.BA` + cash + costos), `fx_for_date`, TWR en pesos, libro del asesor, autodepósitos |
| **CCL** (casa `contadoconliqui`) | `dolarapi.com/v1/dolares/contadoconliqui` | TTL 300 s | **no se persiste** | (a) opción del usuario como dólar de valuación (`pickFinancialRate(d,'ccl')`); (b) obligatorio para el CEDEAR cotizado en USD: `ARS = precioUS × CCL ÷ ratio` |
| **Cripto** | `dolarapi.com/v1/dolares/cripto` | TTL 300 s | **no se persiste** | premium de cripto en broker AR (`crypto_broker_factor` = cripto/MEP) y conversión de `<COIN>.BA` a pesos |
| **`config.tc_blue`** (por usuario) | fila en `config`, sembrada en 1415 al signup (`backend/main.py:3146`) | **nunca se refresca sola** | tabla `config` | fallback frío de `_display_blue`/`_display_ccl`; denominador de varios caminos legacy |
| **`config.tc_mep`** (por usuario) | fila en `config`, sembrada en 1415 (`backend/main.py:3145`) | **nunca se refresca sola** | tabla `config` | fallback frío de `user_fx`/`_user_tc_cedear` |

#### Punta: `medio` vs `venta`

`[V]` `_fetch_dolar` estampa `medio = (compra+venta)/2` y lo devuelve junto a las puntas
(`backend/main.py:4622-4625`). `_val_rate` (`backend/main.py:4630`) es "medio con fallback a
venta" y lo usan `_display_ccl`, `_current_ccl`, `_current_cedear_rate`. El frontend hace lo
mismo (`frontend/src/contexts/CurrencyContext.jsx:50-53`).

**Dos excepciones deliberadas y una que parece accidental:**

- `[V]` **Cripto se queda en `venta`** a propósito: el comentario dice que su premium es el
  *ratio* cripto/MEP y el frontend lee `dolar.cripto.venta` crudo en ~8 lugares
  (`backend/main.py:4964-4969`).
- `[V]` **`_get_blue_for_scheduler` usa `venta`** (`backend/main.py:32011-32012`) → el
  `fx_to_usd_blue` que estampa el snapshot es la punta, no el medio.
- ⚠️ `[V]` **`_display_blue` usa `venta`** (`backend/main.py:4894-4897`) y su docstring dice
  «el MISMO que usa el frontend como tcBlue». Eso **ya no es cierto**: el frontend usa
  `pickFinancialRate`, que arranca por el **MEP al medio**
  (`frontend/src/contexts/CurrencyContext.jsx:52-53`). `[I]` El docstring quedó desfasado
  respecto de la unificación FX; el impacto real es acotado porque `_display_blue` es el
  **tercer** fallback de la conversión de cripto-ARS (`backend/main.py:7713`).

---

### 14.7 ⚠️ Tabla de decisión: qué dólar se usa en cada contexto

| Contexto | Qué dólar | Dónde está la decisión |
|---|---|---|
| Valuar un CEDEAR / acción AR / bono `.BA` (backend) | **MEP** (`cedear_rate`) | `backend/snapshots_job.py:266-279` |
| Valuar un CEDEAR (frontend) | **MEP o CCL, según preferencia** (`cedearRate = pickFinancialRate`) | `frontend/src/utils/valuation.js:699`; `frontend/src/contexts/CurrencyContext.jsx:46` |
| Precio en pesos de un CEDEAR cotizado en USD (BAC) | **CCL** (cascada ccl→mep→cripto) | `backend/main.py:7726` (`_display_ccl`), conversión `backend/main.py:7830-7833` |
| Cash en pesos dentro de un broker ARS | **MEP** (mismo `cedear_rate` que los holdings) | `backend/snapshots_job.py:222`; frontend `frontend/src/utils/valuation.js:634` |
| Costo (invested) de un lote en pesos, modo `today` | **MEP de hoy** | `frontend/src/utils/valuation.js:266` (`costBasisRate`) |
| Costo de un lote en pesos, modo `purchase` (**default**) | **`positions.tc_compra` del lote** | `frontend/src/utils/valuation.js:266-268`; default en `frontend/src/contexts/CurrencyContext.jsx:104-108` |
| Cripto en un **exchange** (Binance, Ripio…) | **spot USD**, factor 1.0 | `crypto_broker_factor` `backend/main.py:7104-7105` |
| Cripto en un **broker AR** (Cocos, Balanz…) | **cripto/MEP** aplicado a valor **y** costo | `backend/main.py:7113`; espejo `frontend/src/utils/crypto.js:47-52` |
| Precio de `<COIN>.BA` devuelto por `/api/prices` | **cripto** → mep → blue | `backend/main.py:7713` |
| Convertir un **aporte/depósito en pesos** con fecha | **MEP de esa fecha** (`fx_for_date`), fallback blue de esa fecha, y recién después el rate del cliente | `backend/main.py:10196` |
| Autodepósito (alta manual sin saldo) | **MEP de la fecha de la compra** | `_autodeposit_rate` `backend/main.py:9794-9805` |
| Ventas / flujos del importador (cuentas `fx_version=v2`) | **MEP de la fecha** → blue de la fecha → fallback del caller | `backend/fx.py:76-97` |
| Cupón / amortización de bono cross-currency | **MEP de la fecha del pago**, con traza y sin caer a hoy | `frontend/src/utils/bondCashflowFx.js:83-89`; `frontend/src/hooks/useFxHistory.js:177` |
| Mostrar el total de la cartera en pesos (toggle ARS) | **`tcValuacion`** = MEP (o CCL si el usuario lo eligió) → el otro → blue | `frontend/src/contexts/CurrencyContext.jsx:46-54`, `frontend/src/contexts/CurrencyContext.jsx:338-341` |
| Curva histórica en pesos (chart) | **TC del día de cada punto** (mep→blue) | `backend/twr.py:1242-1264` (`serie_fx`) |
| Curva de evolución mensual en pesos | **blue mensual del benchmark**, mes a mes | `frontend/src/utils/fx.js:26`, `frontend/src/utils/evolution.js:519` y `:565` |
| `end_value` del período en Reportes | **MEP live** (`_get_mep_for_scheduler`) | `_live_valuation_rate` `backend/main.py:33051-33063` |
| Snapshot nocturno: valuación | **MEP resuelto por el job** (fetch directo, fail-closed si no resuelve) | `backend/snapshots_job.py:715`, `backend/snapshots_job.py:955-964` |
| Snapshot nocturno: stamp de display | **blue.venta** en `snapshots.fx_to_usd_blue` | `backend/snapshots_job.py:791`; `backend/main.py:32011` |
| Libro del asesor (AUM, cash, plazos fijos) | **MEP de la última fila con `mep_venta` no nulo** | `_advisor_book_fx` `backend/main.py:36820-36842`; `_advisor_pf_usd` `backend/main.py:37333` |
| Reconciliar cash (`/api/cash/reconcile`) | **`data.tc_blue` del navegador** | `backend/main.py:10100` |
| Revertir la pata de un transfer fallido | **`tc_blue` recibido** (¡no `fx_for_date`!) | `backend/main.py:10240` |

⚠️ **Asimetría verificada** entre las dos últimas filas y `cash_flow`: el alta de un flujo con
fecha usa `fx_for_date` (`backend/main.py:10196`) pero `_revert_cash_flow` usa el `tc_blue` que
le pasan (`backend/main.py:10240`). `[I]` En una transferencia retroactiva cuya pata de depósito
falla, el retiro se aplicó al MEP de la fecha y se revierte al dólar de hoy → queda un residuo
en `monthly_entries` (capital aportado fantasma). Único caller:
`backend/main.py:24338`, con `_tc` del contexto del chat.

---

### 14.8 Override manual del usuario (`/config`)

`[V]` **El endpoint existe; la pantalla no lo usa.**

- `PUT /api/config` acepta `tc_mep` y `tc_blue` (`backend/main.py:4537-4539`, handler
  `backend/main.py:4565-4597`). Upsert por `(key, user_id)`.
- `GET /api/config` los devuelve con `setdefault(..., 1415)` (`backend/main.py:4561-4562`).
- **Ningún componente del frontend hace `PUT /config`**: el único `api.put` sobre `/config` no
  existe (`grep "put('/config'" frontend/src` → sin resultados). `frontend/src/pages/Config.jsx`
  solo expone el toggle de moneda (USD MEP / USD CCL / Pesos, `frontend/src/pages/Config.jsx:679-680`)
  y el modo "Costo en dólares" (`frontend/src/pages/Config.jsx:693-699`), **ambos guardados en
  `localStorage`, no en la base** (`frontend/src/contexts/CurrencyContext.jsx:25-27`).

O sea: `[I]` hoy `config.tc_blue` / `config.tc_mep` son **1415 fijo para toda cuenta creada
después del signup**, salvo que alguien pegue el `PUT` a mano. Me agarro de que el único
escritor en el flujo normal es `INSERT OR IGNORE ... '1415'` en el registro
(`backend/main.py:3145-3146`); el otro está en `backend/seed.py:29-30`, un script pre-multi-tenancy
que su propio comentario declara roto.

**Dónde SÍ se aplica el override (si existiera):**

| Consumidor | Cita | Condición |
|---|---|---|
| `_user_tc_blue` / `_config_tc_blue` | `backend/main.py:33040`, `backend/main.py:13957` | siempre (dos implementaciones idénticas y duplicadas) |
| `_display_blue`, `_display_ccl` | `backend/main.py:4901`, `backend/main.py:4920` | **solo con el caché de dólar frío** |
| `analysis_prep.user_fx` → `tc_cedear` | `backend/analysis_prep.py:46-48` | **solo si `_current_cedear_rate()` devuelve None** |
| `snapshots_job._user_tc_cedear` | `backend/snapshots_job.py:146-155` | solo si el job no pasó `tc_mep` |
| Frontend `Positions` / `Dashboard` / `Events` | `frontend/src/pages/Positions.jsx:241`, `frontend/src/pages/Dashboard.jsx:192`, `frontend/src/pages/Events.jsx:149` | **solo si `/api/dolar` falló entero** |

**Dónde se IGNORA:**

- `[V]` Snapshot nocturno: el job resuelve el MEP por fetch directo y **aborta** si no lo
  consigue (`backend/snapshots_job.py:956-964`) — nunca llega al config.
- `[V]` Libro del asesor: lee `fx_rates_daily`, no el config (`backend/main.py:36826-36842`).
- `[V]` Reportes: `_live_valuation_rate` va a `_get_mep_for_scheduler` y solo cae al config si
  eso levanta (`backend/main.py:33060-33063`).
- `[V]` Motor de import v2: `fx_for_date` no conoce el config; su `fallback` lo decide el caller
  (`backend/fx.py:100-107`).
- `[V]` `_RESET_CONFIG_KEYS = ("fx_version", "tc_blue", "tc_mep")` — el reset de cuenta los borra
  (`backend/main.py:3616`).

---

### 14.9 `fx_rates_daily`

**Esquema** (`backend/main.py:1477-1483`, Postgres en `backend/schema_pg.sql:910-927`):

```sql
CREATE TABLE fx_rates_daily (
  date       TEXT PRIMARY KEY,   -- YYYY-MM-DD
  blue_venta REAL NOT NULL,
  mep_venta  REAL,               -- NULLABLE
  source     TEXT DEFAULT 'unknown',
  fetched_at TEXT DEFAULT (datetime('now'))
);
```

**Los cuatro escritores** (`grep "INSERT INTO fx_rates_daily"`):

| # | Quién | Cuándo | Qué escribe | Cita |
|---|---|---|---|---|
| 1 | `_backfill_fx_rates_if_empty` | al boot, **solo si `COUNT(*) == 0`** | ~5 años de blue de argentinadatos, `source='argentinadatos'` | `backend/main.py:4709`, SQL en `backend/main.py:4701-4707` |
| 2 | `_backfill_mep_rates_if_missing` | al boot, **solo si hay filas con `mep_venta IS NULL`** | `UPDATE ... SET mep_venta` sobre filas existentes; **no inserta fechas nuevas** | `backend/main.py:4791`, `backend/main.py:4824-4827` |
| 3 | Cron nocturno (02:59 UTC) | 1×/día | **solo `blue_venta`**, `source='snapshot_cron'` | `backend/snapshots_job.py:980-987` |
| 4 | `POST /api/snapshots` (Dashboard) | cada carga del Dashboard | `blue_venta` + `mep_venta` desde el caché, `source='dolarapi'` | `backend/main.py:5040` → `_persist_blue_for_date` `backend/main.py:4658` |

⚠️ `[V]` **El cron NO escribe `mep_venta`.** La fila del día nace con MEP NULL salvo que alguien
abra el Dashboard con el caché caliente. Y `_backfill_mep_rates_if_missing` **solo corre al
boot** (`backend/main.py:32098-32110`). `[I]` En un server que no se reinicia y con poco
tráfico, la serie MEP puede quedarse varios días atrás mientras el blue está al día. Esto no lo
infiero solo yo: `_advisor_book_fx` tiene un fallback explícito «la fila MÁS NUEVA puede venir
solo-blue (el cron nocturno no trae mep) … si no, el libro entero se valuaba al blue ~5 %
abajo un fin de semana cualquiera» (`backend/main.py:36838-36842`).

**Días faltantes: se arrastra el anterior, nunca se interpola.** `[V]`

- `backend/fx.py:60-64`: `WHERE date <= ? AND {col} IS NOT NULL ORDER BY date DESC LIMIT 1`.
  El `IS NOT NULL` está **dentro** del WHERE a propósito — el docstring
  (`backend/fx.py:50-58`) explica que ponerlo afuera hacía que un solo día sin MEP tirara al
  caller al fallback aunque el dato existiera dos días antes.
- `backend/twr.py:1276-1281` (`serie_fx._en`): `bisect_right` sobre las fechas → último ≤ la
  fecha pedida.
- `frontend/src/hooks/useFxHistory.js:156-161` (`getRateForDate`) y `:184-192`
  (`getMepDetail`): búsqueda binaria del anterior más cercano, con la traza `asOf` para poder
  decirle al usuario **de qué día** es el dólar.
- `backend/ledger_replay.py:187-192`: idem, `mep_venta` únicamente — «sin FX no se valúa una
  pata en pesos, no se inventa una tasa».

**No hay interpolación en ningún lado** (`grep interpol` sobre `backend/` → sin resultados). `[V]`

**Fecha futura:** `[V]` **no está protegida en la capa de FX**. `date <= ?` con una fecha de 2027
devuelve la fila **más nueva que exista** (el dólar de hoy), silenciosamente:
`backend/fx.py:60-64`, `frontend/src/hooks/useFxHistory.js:157-161`. `backend/twr.py:1277` es el
único que lo hace explícito: `if fecha == "hoy" or f > _hoy: return vals[-1]`.
La defensa está **río arriba, y solo en un endpoint**: `POST /api/bonds/cashflow` rechaza fechas
futuras con 400 (`backend/main.py:10384-10387`), con el incidente documentado en el comentario
(25 cupones de AL35 fechados 09/01/2027 → +US$ 3,9 M de P&L fantasma). `[I]` Un depósito o un
alta manual con fecha futura **no** tiene ese guard: `cash_flow` (`backend/main.py:10196`) llama
a `fx_for_date` sin validar, y devolvería el dólar de hoy.

**Versionado por cuenta (`fx_version`).** `[V]` `backend/fx.py:126-168`: cada usuario tiene
`config.fx_version ∈ {v1, v2}`. `v1` = el motor escribe con el dólar vivo del import (legacy,
"grandfathered"); `v2` = escribe con `fx_for_date`. Una cuenta virgen nace `v2` y se **persiste
en el momento**, porque si no la segunda llamada la vería "con historia" y la degradaría a `v1`
para siempre (`backend/fx.py:136-140`). El migrador es `/api/admin/fx-migrate-user`
(`backend/main.py:16889`) y tiene que mover **las dos patas juntas** (ventas y flujos) o el error
salta de 1,23× a 9,1× (`backend/fx.py:110-124`).

---

### 14.10 Bonos: escala per-100, paridad y amortización

#### a) La escala per-100 → per-1

`[V]` **data912 no es uniforme** y el código lo documenta con números medidos
(`backend/main.py:7184-7192`):

- Soberanos / BOPREAL / ONs → **per-100** (`AL30 = 96.300 ARS`, `AL30D = 64,23 USD`)
- Bonos CER (`TX*`, `TZX*`) → **per-1** (`TX26 = 702,9 ARS`, `TX26D = 0,465 USD`)

La clasificación es por **USD-equivalente con umbral 3 USD** (`backend/main.py:7355-7357`):
per-1 ≈ paridad/100 (< ~2 USD), per-100 ≈ paridad (5-150 USD). El umbral está en USD y no en
pesos para que la devaluación no lo erosione. El USD-equivalente del quote en pesos sale del
MEP implícito del par `AL30/AL30D` (`_data912_peso_per_usd`, `backend/main.py:7245-7256`),
con **fallback duro 1450.0**.

`[V]` Hay **tres** normalizadores de escala más, en el pipeline de import, y no comparten código
con el de pricing:

1. `reconciled_unit_price` (`backend/importing/persister.py:490`): si `precio×cantidad / monto`
   ≈ 100 (renta fija) o ≈ 1000 (VCP de FCI), reescribe el precio a `monto/cantidad`. Fuera de
   esas dos ventanas devuelve el valor **intacto a propósito** — el docstring
   (`backend/importing/persister.py:499-524`) explica que un `k` de 1e13 es basura y
   "arreglarlo" lo volvería invisible.
2. `bond_per100_factor` (`backend/importing/recompute_backfill.py:157`): decide por el ratio
   costo-unitario / precio-de-mercado (umbral 10, ventana `(10, 1000)`).
3. `tenencia.py` (`backend/importing/tenencia.py:785-793`): detecta per-100 comparando
   `qty×precio` contra el importe de la foto.

⚠️ `[V]` El propio comentario de `persister.py:509-511` señala que `tenencia._num` usa la
**convención opuesta** a `normalizer` para el separador decimal: «una de las dos está mal por
construcción».

`[V]` En el snapshot, los bonos se resuelven **pisando lo de yfinance**: primero se hace el
batch de yfinance y después `_resolve_ar_bond_price` sobrescribe
(`backend/snapshots_job.py:503-513`), porque yfinance devuelve el `.BA` per-100 sin dividir → el
snapshot inflaba los bonos ×100 (el comentario cita: «chart "Hoy" 3× la cartera real»).

#### b) Paridad

`[V]` **La paridad como número no se calcula en la capa de precios.** Aparece solo como
concepto: en la clasificación per-100 vs per-1 (`backend/main.py:7185`, `:7353-7354`) y en el
prompt de la IA (`backend/main.py:20481`). La matemática de renta fija (yield, duration,
day-count ICMA/ISDA) vive en `frontend/src/utils/bondPricing.js`, cuyo contrato de unidad es
explícito: **precio "por 100 VN"; si el broker reporta per-1, el caller multiplica × 100 ANTES**
(`frontend/src/utils/bondPricing.js:9-11`). O sea: la capa de precios sirve **per-1** y la capa
de matemática de bonos espera **per-100** — la conversión es responsabilidad del caller.

#### c) `pricing/bond_amortization.py` — amortización = devolución de capital

`[V]` El módulo (`backend/pricing/bond_amortization.py`) es corto y explícito. Su premisa
(`backend/pricing/bond_amortization.py:7-13`):

> el mercado cotiza **por nominal RESIDUAL**, pero Rendi reconstruye la tenencia desde la compra
> del nominal ORIGINAL y **nunca lo baja** cuando entra una amortización (la importa como
> dividendo = solo cash) → tenencia y valuación sobrevaluadas.

- `residual_factor(ticker, fecha)` = `1 − Σ(cuotas con fecha ≤ ref)`
  (`backend/pricing/bond_amortization.py:136-142`), con clamp a `[0, 1]`.
- **Solo 4 tickers tienen cronograma**: `AL29`, `GD29`, `AL30`, `GD30`
  (`backend/pricing/bond_amortization.py:88-93`). Todo lo demás devuelve `1.0` = no-op
  (`backend/pricing/bond_amortization.py:134`).
- ⚠️ `[V]` El propio archivo lista lo que **falta y por qué duele**
  (`backend/pricing/bond_amortization.py:95-102`): **`GD46` AMORTIZA HOY** (~44 cuotas de
  ~2,27 % desde 2025) y sin su schedule **queda sobrevaluado**. `AL41/GD41`, `AE38/GD38` y
  `AL35/GD35` arrancan en 2027/2028/2031 → hoy `R=1`, inocuo.
- `_strip_bond_suffix` (importado de `ai.ar_bonds_metadata`, con fallback local en
  `backend/pricing/bond_amortization.py:39-48`) normaliza `AL30D`/`AL30C`/`AL30.BA` → `AL30`.
  El lookup además cae a buscar el ticker **dentro del nombre** para brokers como Cocos
  (`backend/pricing/bond_amortization.py:117-121`).

**Quién lo aplica:** `sweep_bond_amortizations` (`backend/importing/maturity.py:296`), que corre
en cada confirm de import (`backend/main.py:15103`, `backend/main.py:30872`). Detalles no
obvios `[V]`:

- Reducción **proporcional, no FIFO** (`backend/importing/maturity.py:390-395`): cada lámina
  amortiza igual, y así es currency-aware (un bono con tenencia en ARS y en USD escala cada
  moneda por sí misma; el FIFO consumía una sola).
- **No toca cash ni `monthly_entries`** — la plata ya entró como cupón/dividendo
  (`backend/importing/maturity.py:307`).
- Los lotes sembrados por la **foto de tenencia** están eximidos: su cantidad ya es el residual
  real (`backend/importing/maturity.py:317-327`, `:378-383`). Sin eso, doble conteo.

**El otro lado (el cobro):** `POST /api/bonds/cashflow` con `flow_type='amortization'` y
`decrement_quantity=True` reduce FIFO cantidad + invested + comisiones proporcionalmente
(`_amortize_position_fifo`, `backend/main.py:10587-10640`). La distinción
**capital vs renta** está estampada en la columna `operations.cost_basis_consumed`
(`backend/main.py:1194-1203`): «Ganancia del amort = pnl_usd − cost_basis_consumed». Es NULL
para cupones y para amortizaciones legacy pre-Phase-3D.
⚠️ `[V]` `_amortize_position_fifo` asume **1 VN = 1 USD face** y lo dice
(`backend/main.py:10604-10607`), argumentando que los CER (que tendrían face ajustado) son bullet
y nunca llegan acá.

---

### 14.11 FCIs — `backend/pricing/fci.py`

`[V]` **Fuente:** `https://api.argentinadatos.com/v1/finanzas/fci/{categoria}/ultimo`, capa JSON
pública sobre CAFCI, sobre 5 categorías (`backend/pricing/fci.py:35-36`).

**El `vcp/1000`:** el campo `vcp` de la API es el valor **por 1000 cuotapartes**, no el precio
unitario. Se divide **al guardar**, para que el resto de la app lo trate como cualquier precio:
`price = round(vcp / 1000.0, 6)` (`backend/pricing/fci.py:287`). La verificación citada es la
identidad `vcp*ccp == patrimonio*1000` (`backend/pricing/fci.py:6-9`).

**Dos tablas, creadas por el propio módulo** (no viven en el esquema — `ensure_tables`,
`backend/pricing/fci.py:175-201`):

- `fci_catalog(symbol PK, ad_name, display_name, emisor, clase, moneda, categoria, activo)` —
  subset **curado**. El match contra la fuente es por `ad_name` **exacto**
  (`backend/pricing/fci.py:282`), y ese nombre vive en una columna precisamente para que un
  rename de CAFCI se arregle en datos y no en código (`backend/pricing/fci.py:13-15`).
- `fci_prices(symbol PK, price DOUBLE PRECISION, moneda, as_of_date, fetched_at)`. El
  `DOUBLE PRECISION` es deliberado: como la tabla se crea acá y no pasa por el traductor de
  tipos, un `REAL` en Postgres son 4 bytes (~7 dígitos) y esto es una columna de precios
  (`backend/pricing/fci.py:190-195`).

**El catálogo son tres allowlists hardcodeadas** `[V]`: `FIMA_CLASSES` (clases retail A/B/C/P,
`backend/pricing/fci.py:41`), `MM_ALLOWLIST` (13 money-market, `backend/pricing/fci.py:46-60`) y
`BROKER_FCI_ALLOWLIST` (~18 fondos propietarios de brokers, `backend/pricing/fci.py:70-92`).
El match es por **nombre-base exacto** para que `Allaria Ahorro` no arrastre
`Allaria Ahorro Dinámico` (`backend/pricing/fci.py:162-171`). Cada entrada de
`BROKER_FCI_ALLOWLIST` viene con su VCP verificado y su fecha en el comentario.
**Un fondo que no esté en la allowlist no tiene precio y se valúa al costo** — el comentario lo
dice de frente para "Cocos Pesos Plus" (`backend/pricing/fci.py:68-69`).

**Freshness — el bug que ya mordió:** `[V]` el corte de fondos stale es **por categoría**, no
global (`backend/pricing/fci.py:218-227`). El comentario documenta la medición del 2026-08-13:
`otros` venía al día y las otras cuatro traían 2026-07-21 → el corte global tiraba 4.067 fondos
y **el seed quedaba en cero, en silencio**.

**Degradación:** si el fetch falla, **no se borran los precios viejos** — se sirve el último
bueno con su `as_of_date` (`backend/pricing/fci.py:19-21`, `:263-268`). Y por eso
`get_prices_detail_for` devuelve `{price, as_of}` y no un número pelado: la fuente **dejó de
publicar tres semanas** (21/07 → 13/08 de 2026) y el precio viejo se mostraba como si fuera de
hoy (`backend/pricing/fci.py:321-328`). Ese `as_of` viaja al frontend por `__meta`
(`backend/main.py:7625-7626`).

**Refresco:** cron diario 12:10 UTC (~09:10 ART, porque CAFCI publica T+1) —
`backend/main.py:32570-32574` — más un `bootstrap` en un thread daemon al arrancar
(`backend/main.py:32506-32521`) y un endpoint admin `POST /api/admin/fci/refresh`
(`backend/main.py:20086`).

---

### 14.12 `price_history.py` y `asset_price_history`

**Qué es.** `[V]` Un histórico **por símbolo y fecha**, pensado como prerrequisito de la
reconstrucción de bordes: «con el ledger sabemos QUÉ tenía cada persona en cada fecha, y con
esta tabla sabemos CUÁNTO VALÍA» (`backend/price_history.py:1-12`).

**Esquema** (`backend/main.py:1788-1807`):

```sql
CREATE TABLE asset_price_history (
  symbol TEXT NOT NULL, date TEXT NOT NULL, price REAL NOT NULL,
  source TEXT, fetched_at TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (symbol, date));
CREATE INDEX idx_price_hist_symbol ON asset_price_history(symbol, date DESC);

CREATE TABLE price_backfill_log (
  symbol TEXT PRIMARY KEY, desde TEXT NOT NULL,
  ok INTEGER NOT NULL DEFAULT 1, fetched_at TEXT DEFAULT (datetime('now')));
```

**Reglas de la API** `[V]`:

| Función | Cita | Regla |
|---|---|---|
| `guardar` | `backend/price_history.py:31-51` | idempotente y **NO PISA** (`ON CONFLICT DO NOTHING`): el primer precio registrado para una fecha es el que vale |
| `precio_en` | `backend/price_history.py:54-62` | busca hacia atrás con **techo de 7 días** (`MAX_DIAS_ATRAS`, `backend/price_history.py:23`); `None` = **no se puede valuar**, nunca 0 |
| `precios_en` | `backend/price_history.py:65-70` | los que no resuelven **no aparecen** en el dict — nada de 0 silencioso |
| `cobertura` | `backend/price_history.py:73-85` | `{total, con_precio, faltan, pct}` para decidir **antes** de publicar un valor |
| `backfill` | `backend/price_history.py:104-151` | resumible (se salta lo ya cubierto vía `price_backfill_log`), lote de 25 (`LOTE_DEFAULT`), un símbolo que falla no frena la tanda |
| `_fetch_yfinance` | `backend/price_history.py:88-101` | descarta cierres NaN o ≤ 0 — el bug de las ruedas `.BA` con volumen y OHLC en NaN |
| `simbolos_de` | `backend/price_history.py:154-167` | reusa `build_price_symbols` del snapshot, con la advertencia de que reinventar esa resolución fue lo que infló un CEDEAR 15-100× |

⚠️⚠️ `[V]` **En producción nada llena esta tabla y nada la lee.** Verificado por grep sobre todo
`backend/` excluyendo tests:

- El único consumidor de `price_history` es `backend/ledger_replay.py:213` (`import price_history as ph`).
- `ledger_replay` **no tiene ningún caller**: las únicas menciones fuera de tests son un
  comentario en `backend/twr.py:1232` y otro en `backend/importing/proyeccion.py:12`.
- `guardar` solo se llama desde `backfill`; `backfill` solo se llama desde
  `backend/tests/test_advisor_plan.py`.
- No hay ningún job de scheduler para el backfill (`backend/main.py:32524-32583` registra
  `daily_snapshot`, `iol_lab_refresh`, `subscription_lifecycle`, `backup_db` y `fci_refresh` —
  nada de precios históricos).

`[I]` La capa está escrita, testeada y con el esquema deployado, pero **desconectada**. El
histórico de precios que la app efectivamente usa es otro: `snapshots.holdings_json` (foto por
activo, `backend/snapshots_job.py:764`) y `asset_last_price` (una sola fila por símbolo).

⚠️ `[V]` **Camino roto adyacente**: `backend/ai/builders/position_chart.py:26` llama a
`_m._fetch_price_history(symbol, period="1m")`. **Esa función no existe en `main.py`**
(`grep -n "_fetch_price_history" backend/main.py` → sin resultados). El `try/except Exception`
de `backend/ai/builders/position_chart.py:37-38` se come el `AttributeError` y `series` queda
**siempre vacío**: el packet `position.chart` de la IA nunca tiene serie de precios. Lo que sí
existe es el endpoint `GET /api/prices/history` (`backend/main.py:8051`), que devuelve
`{symbol, period, points}` y no un dict `{fecha: close}` como el caller espera.

**Nota aparte sobre `/api/prices/history`** `[V]`: usa `auto_adjust=False`
(`backend/main.py:8097`) mientras `/api/prices` usa `auto_adjust=True`
(`backend/main.py:7746`). `[I]` El mini-chart y el precio de la fila pueden no cerrar en un
ticker con dividendos/splits recientes.

---

### 14.13 Hallazgos, rarezas y contradicciones

Ordenados por lo que me parece más caro, con la evidencia al lado.

1. ⚠️ **FCI en broker ARS con lote en pesos: valuado al costo en el snapshot, y contado como
   "con precio" en el guard de cobertura.** `[V]` `backend/snapshots_job.py:276` busca
   `FCI:X.BA`; `backend/snapshots_job.py:727` valida con `position_price_key`, que devuelve
   `FCI:X`. El asesor ya parchea esto con un alias (`backend/main.py:36893-36897`) y el frontend
   nunca lo tuvo. El snapshot no.

2. ⚠️ **`_fill_last_known_prices` no tiene TTL.** `[V]` `backend/main.py:7538` +
   `backend/snapshots_job.py:589` (sin filtro por `updated_at`). Un ticker que dejó de cotizar
   sigue "teniendo precio" para siempre. El propio repo lo llama bug en
   `backend/price_history.py:18-22`. Único lugar con guard de edad: 48 h en el registro por chat
   (`backend/main.py:23451`).

3. ⚠️ **Cap de 60 símbolos con truncado silencioso y sin chunking en el cliente.** `[V]`
   `backend/main.py:7139`, `:7637`, `:7881`; frontend sin chunk en
   `frontend/src/pages/Positions.jsx:577-580`. El propio código reconoce el riesgo para el
   asesor (`backend/main.py:37265-37266`) pero la ruta retail sigue expuesta: una cartera con
   más de 60 tickers distintos deja la cola al costo. `[I]`

4. ⚠️ **El cron nocturno no escribe `mep_venta`, y el relleno solo corre al boot.** `[V]`
   `backend/snapshots_job.py:980-982` (solo blue) vs `backend/main.py:32098-32110` (backfill en
   `@app.on_event("startup")`). Ya causó al menos un bug medido según
   `backend/main.py:36838-36842`.

5. ⚠️ **Fecha futura no está bloqueada en la capa de FX.** `[V]` `backend/fx.py:60-64` y
   `frontend/src/hooks/useFxHistory.js:157-161` devuelven el dólar de hoy. El único guard vive
   en `POST /api/bonds/cashflow` (`backend/main.py:10384-10387`); `cash_flow`
   (`backend/main.py:10196`) no lo tiene.

6. ⚠️ **Asimetría alta/revert de un flujo de caja con fecha.** `[V]` alta con `fx_for_date`
   (`backend/main.py:10196`), revert con el `tc_blue` del cliente (`backend/main.py:10240`).

7. ⚠️ **`GD46` amortiza hoy y no tiene cronograma → queda sobrevaluado.** `[V]` lo declara el
   propio módulo, `backend/pricing/bond_amortization.py:97-98`.

8. ⚠️ **`price_history.py` + `asset_price_history` + `ledger_replay.py` son código muerto en
   producción.** `[V]` ver 14.12. Es infraestructura completa (tabla, índice, log de backfill,
   guard de cobertura, tests) que **ningún camino vivo toca**.

9. ⚠️ **`ai/builders/position_chart.py` llama a una función inexistente**, y el `except` lo tapa.
   `[V]` `backend/ai/builders/position_chart.py:26` vs `grep _fetch_price_history backend/main.py`
   (vacío).

10. **Dos motores de quotes que no comparten fuente.** `[V]` `/api/prices` va a data912 primero
    (`backend/main.py:7679-7690`); `backend/home/market.py:267` (`_fetch_batch_quotes`) es
    yfinance puro, y es el que alimenta Análisis/behavioral/goals vía
    `backend/analysis_prep.py:53-77`. `[I]` Dos pantallas pueden mostrar precios `.BA` distintos
    para el mismo activo.

11. **`_display_blue` toma `venta` y su docstring dice que es "el MISMO que usa el frontend".**
    `[V]` `backend/main.py:4894-4897` vs `frontend/src/contexts/CurrencyContext.jsx:50-53`
    (medio, y MEP primero). Docstring desactualizado.

12. **`_user_tc_blue` y `_config_tc_blue` son la misma función duplicada.** `[V]`
    `backend/main.py:33040-33048` y `backend/main.py:13957-13966`: mismo SQL, mismo default
    1415, mismo `if v > 0`.

13. **`is_exchange_broker` matchea por nombre EXACTO.** `[V]`
    `backend/main.py:2842-2852`: el set tiene `'binance'`, `'ripio'`, etc. `[I]` Un broker que el
    usuario llamó "Binance Spot", "Binance Futuros" o el sibling `"Binance · USD"` **no
    matchea** → su cripto recibe el premium cripto/MEP como si fuera un broker AR. Me agarro de
    que `_ensure_usd_sibling` crea nombres con sufijo `· USD` (documentado en
    `frontend/src/utils/valuation.js:156-158`).

14. **`CEDEAR_USD_RATIOS` tiene un solo ticker (`BAC`, ratio 4).** `[V]`
    `backend/main.py:7125-7127`. Es una lista manual, encontrada por reporte de usuario; el
    comentario dice "extensible si aparecen otros". `[I]` Cualquier otro CEDEAR que las fuentes
    empiecen a cotizar en USD queda con el precio en USD tratado como si fuera pesos (~×1500 de
    error) hasta que alguien lo agregue.

15. **Si falta el CCL, el CEDEAR USD-cotizado queda con el precio EN USD.** `[V]` En
    `/api/prices` la conversión está dentro de un `if cedear_usd and _ccl_ars and _ccl_ars > 0`
    (`backend/main.py:7830`): sin CCL no se convierte **ni se anula** — el número en USD se
    devuelve como si fuera ARS. En cambio `backend/snapshots_job.py:504` sí lo pone en `None`, y
    `GET /api/prices/history` vacía la serie (`backend/main.py:8129`). Tres comportamientos
    distintos para la misma falla.

16. **`_data912_peso_per_usd` cae a `1450.0` hardcodeado.** `[V]` `backend/main.py:7256`.
    `[I]` Ese número decide la clasificación per-100/per-1 de bonos en pesos; con una
    devaluación fuerte y data912 sin par soberano usable, la clasificación puede invertirse
    (error ×100 en el valor de un bono).

17. **`AR_BONDS_DATA912` ya no es una allowlist de pricing.** `[V]` el pricing usa el universo
    completo de data912 (`backend/main.py:7347-7351`); la constante sobrevive solo para excluir
    bonos de noticias (`backend/main.py:6080`, `:35321`). Nombre engañoso.

18. **El precio `None` se cachea 60 s.** `[V]` `backend/main.py:7443-7444`. Es deliberado
    (evita retry storm si Yahoo está caído) pero significa que un símbolo recién agregado puede
    mostrar `—` durante un minuto aunque la fuente ya lo tenga.

19. **`/api/prices` y `/api/prices/prev-close` son dos requests separados sobre el mismo
    `yf.download`.** `[V]` `backend/main.py:7746` y `backend/main.py:7964`, con caches distintos
    (60 s vs 600 s). `[I]` Los dos pueden quedar desfasados: el TTL de 600 s del prev-close
    sobrevive a 10 refrescos del precio actual.

20. **El `pct_change` de data912 se usa para *derivar* el cierre anterior.** `[V]`
    `backend/main.py:7917`: `previo = c / (1 + pct/100)`, y si `pct == 0` (mercado cerrado)
    `previo = actual` → variación 0. Es una decisión explícita para que el precio actual y el
    previo salgan de la **misma** fuente (`backend/main.py:7891-7898`).

21. **Rarezas de nomenclatura que ya causaron confusión, y que el código admite.** `[V]`
    `CurrencyContext` documenta que la variable «se llamaba `tcBlue` sin contener el blue»
    (`frontend/src/contexts/CurrencyContext.jsx:6-10`), y `_advisor_pf_usd` tuvo que escribir un
    párrafo entero para explicar que `pfUsd(totals, tcBlue)` recibe el MEP
    (`backend/main.py:37346-37353`). El renombre a `tcValuacion` ya se hizo en el context, pero
    los call sites viejos (`Positions.jsx:1037`, `PositionsMobile.jsx:389`) siguen mandando el
    campo `tc_blue` al backend con el valor del MEP.

22. **`seed.py` escribe `config` con 2 valores para 3 columnas.** `[V]`
    `backend/seed.py:29-30`, con el comentario que reconoce que revienta
    (`backend/seed.py:25-28`). Es un script pre-multi-tenancy, no un camino vivo.

---

### 14.14 Lo que NO encontré / preguntas abiertas

- **No encontrado**: interpolación de FX entre días faltantes. En ninguna capa. Siempre arrastre
  del último hábil anterior.
- **No encontrado**: dólar oficial, tarjeta, mayorista, turista o solidario. Solo blue, bolsa
  (MEP), contadoconliqui (CCL) y cripto.
- **No encontrado**: una UI para fijar `tc_blue`/`tc_mep`. El `PUT /api/config` los acepta pero
  ningún componente lo llama.
- **No encontrado**: cualquier caller de producción de `price_history.backfill`,
  `price_history.guardar`, `price_history.simbolos_de`, `price_history.cobertura` o de
  `ledger_replay.valor_en`. Solo tests.
- **No encontrado**: escritura de `source='manual'` en `fx_rates_daily`, pese a que el comentario
  del esquema lo lista como valor posible (`backend/main.py:1481`).
- **No encontrado**: `_fetch_price_history` en `main.py` (la llama
  `backend/ai/builders/position_chart.py:26`).
- **No encontrado**: variables de entorno en la capa de precios/FX. `grep os.getenv|os.environ`
  sobre `backend/fx.py`, `backend/price_history.py`, `backend/pricing/*.py`,
  `backend/home/market.py` y `backend/snapshots_job.py` no devuelve nada: todos los endpoints
  externos (dolarapi, argentinadatos, data912) están **hardcodeados**, sin API key y sin
  configuración.
- **Pregunta**: ¿el `mep_venta` faltante de la fila de hoy tiene efecto medible? Depende de la
  frecuencia real de reinicio de Railway y del tráfico al Dashboard — no lo puedo determinar
  leyendo código.
- **Pregunta**: ¿cuántas cuentas siguen en `fx_version = v1`? El migrador y sus endpoints de
  diagnóstico existen (`backend/main.py:16889`, `:16996`, `:17239`) pero el estado es dato de
  producción.
- **Pregunta**: ¿qué se hace con un símbolo cuya última barra de data912 es vieja? El `stale` de
  `__meta` no lo marca (14.4), y data912 no devuelve fecha en el payload que se consume
  (`backend/main.py:7232-7236` solo lee `symbol` y `c`).
