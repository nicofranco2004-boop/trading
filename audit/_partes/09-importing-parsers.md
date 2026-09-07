## 9. Importación — parsers por broker (`backend/importing/parsers/`)

Alcance: los 17 archivos de `backend/importing/parsers/`. Todo lo documentado acá está verificado leyendo el código de `origin/main` (commit `b74f450f`). Las rutas son relativas a la raíz del repo.

### 9.0 Resumen de una línea

Hay **15 parsers registrados** (14 soportados + 1 apagado), todos con la misma forma: **traducen el export del broker a filas con los headers del template genérico de Rendi** (`fecha, tipo, broker, activo, cantidad, precio, monto, monto_usd, tc, comisiones, moneda, notas` + extras `asset_type`, `asset_name` y flags `_`-prefijados). Ningún parser habla con la base ni valida semántica: eso vive en `normalizer.py` / `validator.py` / `persister.py`.

| Métrica | Valor |
|---|---|
| Parsers registrados | 15 [V] `backend/importing/parsers/registry.py:22-54` |
| Soportados (`is_supported=True`) | 14 [V] |
| Apagados | 1 — `binance_futures_trade_history` [V] `backend/importing/parsers/binance_futures.py:79` |
| Registrados pero que SIEMPRE fallan a propósito | 1 — `balanz_resultados` [V] `backend/importing/parsers/balanz_resultados.py:202-209` |
| Líneas totales | 6.226 (el más grande: `iol.py`, 787) [V] |
| Parsers que emiten operaciones FX | 2 (`balanz_movimientos`, `iol`) [V] |
| Parsers que llenan la columna `tc` | **0** [V] (ver hallazgo H-1) |

---

### 9.1 El registry — cómo se elige el parser para un archivo

**Archivo**: `backend/importing/parsers/registry.py` (74 líneas).

Es una **lista Python ordenada a mano** (`_PARSERS`, `backend/importing/parsers/registry.py:22-54`) con una instancia de cada parser. Tres funciones públicas:

| Función | Línea | Qué hace |
|---|---|---|
| `list_parsers()` | `backend/importing/parsers/registry.py:57-58` | Devuelve la lista completa (la consume el wizard vía `parser_options_grouped`) |
| `get_parser(format_id)` | `backend/importing/parsers/registry.py:61-65` | Lookup lineal por `format_id`; `None` si no existe |
| `autodetect(headers)` | `backend/importing/parsers/registry.py:68-74` | **Primer** parser con `is_supported and can_handle(headers)`; `None` si ninguno |

#### La detección es por SNIFFING DE ENCABEZADOS, no por nombre de archivo [V]

`autodetect` recibe únicamente la lista de headers y consulta `can_handle(headers)` de cada parser. El `file_name` llega al parser (`parse(content, file_name=...)`) pero **ningún parser lo usa para decidir nada** — sólo lo aceptan en la firma [V] (revisado en los 15 `parse()`).

Cada `can_handle` es una heurística distinta sobre headers normalizados:

| Parser | Criterio de `can_handle` | Cita |
|---|---|---|
| `rendi_generic` | Todos de `{fecha, tipo, broker}` | `backend/importing/parsers/generic.py:48-50` |
| `binance` | Fecha (`date(utc)`\|`time`) **+ todos** de `{pair, side, price, executed, amount, fee}` | `backend/importing/parsers/binance.py:110-113` |
| `binance_futures_trade_history` | Fecha + todos de `{symbol, side, price, quantity, amount, fee, realized_profit}` | `backend/importing/parsers/binance_futures.py:84-87` |
| `binance_transaction_history` | Todos de `{user_id, time, account, operation, coin, change}` | `backend/importing/parsers/binance_transaction.py:121-123` |
| `cocos` | **≥3** de `{nroticket, fechaejecucion, tipooperacion, instrumento}` | `backend/importing/parsers/cocos.py:364-366` |
| `ppi` | Todos de `{descripcion, moneda, importe, saldo}` | `backend/importing/parsers/ppi.py:189-191` |
| `balanz_movimientos` | Todos de `{descripcion, importe, moneda}` | `backend/importing/parsers/balanz_movimientos.py:204-206` |
| `balanz_internacional` | **`return False` — nunca autodetecta** | `backend/importing/parsers/balanz_internacional.py:129-130` |
| `balanz` (Órdenes) | `{operacion, estado, activo, fecha}` **+** ≥1 discriminador (`id orden`\|`precio operado`\|`cantidad operada`) | `backend/importing/parsers/balanz.py:186-190` |
| `balanz_resultados` | `{tipo_mov, activo}` + ≥1 de `{precio_compra, cupones, _dolar}` | `backend/importing/parsers/balanz_resultados.py:153-155` |
| `iol` | **≥3** de `{tipomov, canttitulos, concert, monto, nrodeboleto}` | `backend/importing/parsers/iol.py:516-518` |
| `schwab` | **≥3** de `{date, action, symbol, amount}` | `backend/importing/parsers/schwab.py:189-191` |
| `bullmarket` | Todos de `{liquida, especie, importe}` **+** (`comprobante` \| header que empiece con `cpbt`) | `backend/importing/parsers/bullmarket.py:264-269` |
| `ieb` | **≥4** de `{referencia, operacion, nrodeoperacion, importears, importedivisas, divisa}` | `backend/importing/parsers/ieb.py:277-279` |
| `inviu` | Todos de `{tipo de operacion, import bruto, importe neto, saldo}` | `backend/importing/parsers/inviu.py:147-149` |

#### ¿Qué pasa si dos parsers matchean? Gana el PRIMERO de la lista [V]

`autodetect` hace `for p in _PARSERS: if p.is_supported and p.can_handle(headers): return p` (`backend/importing/parsers/registry.py:71-74`). No hay scoring, ni desempate, ni aviso de ambigüedad. **El orden de la lista ES la política de desempate**, y está documentado con comentarios que cuentan bugs reales:

- **PPI antes que Balanz** (`backend/importing/parsers/registry.py:28-32`): un export de PPI tiene `Descripción` + `Moneda` + `Importe` (lo que pide `balanz_movimientos`), pero sólo PPI trae `Saldo`. Como PPI exige `saldo`, no roba archivos de Balanz; y al ir primero, agarra los suyos.
- **`balanz_movimientos` antes que `balanz` (Órdenes)** (`backend/importing/parsers/registry.py:33-38`): el wizard arranca en el primer export soportado del grupo, así que el default de Balanz pasó a ser Movimientos.
- **`balanz_internacional` después de Movimientos y con `can_handle=False`** (`backend/importing/parsers/registry.py:40-44` + `backend/importing/parsers/balanz_internacional.py:126-130`): el export internacional tiene **exactamente las mismas columnas** que el local → indistinguible por headers. Se elige explícito en el wizard.

**Riesgo estructural** [I]: tres parsers usan umbrales laxos (`cocos` ≥3/4, `iol` ≥3/5, `schwab` ≥3/4, `ieb` ≥4/6). Un export nuevo con headers parecidos puede ser capturado silenciosamente por el primero que pase el umbral, sin ningún aviso al usuario. La única protección es el orden de la lista, que es conocimiento tácito escrito en comentarios.

#### Cómo se conecta con el pipeline

`backend/importing/pipeline.py:469-506` es donde se decide de verdad:

1. Default: `parser = get_parser("rendi_generic")` (`backend/importing/pipeline.py:469`).
2. Si vino un **`mapping`** explícito de columnas → se traduce el CSV a headers de Rendi y se parsea con el genérico (`backend/importing/pipeline.py:470-475`).
3. Si vino **`parser_format`** ≠ genérico → `get_parser(...)`; error si no existe o si `is_supported=False` (`backend/importing/pipeline.py:476-483`).
4. **Fallback robusto** (`backend/importing/pipeline.py:487-505`): si el parser elegido devolvió errores y **cero filas**, se re-lee la primera línea del CSV, se corre `autodetect(headers)` y, si da otro parser que sí produce filas, se reemplaza el parser en caliente. Cubre "elegí Balanz pero subí el de Resultados".
5. Después del parseo, `FORMAT_BASE_CURRENCY[parser.format_id]` (`backend/importing/pipeline.py:412-437`) ancla la **moneda del broker** (Cocos/IOL/Balanz/BM/IEB/PPI/inviu→ARS, Schwab/Balanz Internacional→USD, Binance×3→USDT) y hasta **auto-corrige** (`backend/importing/pipeline.py:544-562`) un broker vacío que quedó con la moneda equivocada. `rendi_generic` es el único deliberadamente sin ancla (test en `backend/tests/test_format_base_currency.py:36`).
6. **El nombre del broker sale del parser, no del wizard** [V]: `broker_hint` sólo etiqueta el batch (`backend/importing/pipeline.py:678-685`); las `tx.broker` conservan el string hardcodeado por el parser (`"Cocos"`, `"IOL"`, `"Balanz"`, `"Bull Market"`, `"Binance"`, `"Schwab"`, `"IEB"`, `"PPI"`, `"inviu"`, `"Balanz Internacional"`), sólo canonicalizado case-insensitive contra brokers existentes (`backend/importing/pipeline.py:518-529`).
7. Ruteo por moneda: si un broker ARS trae filas USD/USDT o FX, se activa solo `route_by_currency` y esas filas van al sub-broker `"<Padre> · USD"` (`backend/importing/pipeline.py:647-655`).

---

### 9.2 `base.py` — el contrato

**Archivo**: `backend/importing/parsers/base.py` (54 líneas). `class Parser(ABC)`.

| Miembro | Tipo | Default | Para qué |
|---|---|---|---|
| `format_id` | `str` | `""` | Identificador estable, persistido en `import_batches.parser_format` |
| `display_name` | `str` | `""` | Nombre legible (fallback de UI) |
| `is_supported` | `bool` | `True` | Si es `False`: no autodetecta, el pipeline lo rechaza y el wizard ni lo lista |
| `platform` / `platform_label` / `export_label` | `str` | `"generic"` / `"Genérico"` / `""` | Agrupación a 2 niveles del wizard (plataforma → export) |
| `tenencia_format` | `Optional[str]` | `None` | `parser_format` de la FOTO de tenencia de ese broker, si existe |
| `parse(content, file_name=None)` | **abstracto** | — | Único método obligatorio. Devuelve `ParseResult(raw_rows, parse_errors)` |
| `can_handle(headers)` | método | `False` | Heurística de autodetección |
| `template_csv()` | método | `""` | CSV de ejemplo descargable |

Dos cosas notables del contrato:

- **`parse` NO valida semántica** — sólo estructura. El docstring lo dice explícito (`backend/importing/parsers/base.py:44-49`): "errores típicos acá: encoding, columnas faltantes, headers ilegibles".
- **`tenencia_format` es SSoT del backend y nació de un bug del frontend** (`backend/importing/parsers/base.py:24-38`): el mapeo movimientos→foto vivía en un dict a mano en `frontend/src/components/import/ImportWizard.jsx:158` (`TENENCIA_BROKER_BY_FORMAT`) que ya se había desincronizado — tenía una entrada para `balanz_internacional`, cuya foto **no existe**, y le pedía al usuario un archivo que ningún parser sabe leer. El comentario incluye la métrica: sólo el 57,8% de la gente elegible sube la foto (160 de 277). Hoy hay tests que lo blindan (`backend/tests/test_tenencia_capability.py:50-56`, `:82-85`).

#### Contrato de salida real (no está en `base.py`, es convención)

Los `RawRow.data` que producen los parsers usan las claves del template genérico (`backend/importing/parsers/generic.py:17-30`) más tres extensiones **no documentadas en `base.py`** [V]:

- `asset_type` — hint de clase (`CEDEAR`/`BOND`/`FUND`/`STOCK`/`ETF`), lo consume el normalizer.
- `asset_name` — nombre largo del instrumento.
- Flags con guion bajo, que el normalizer traduce a campos de `NormalizedTx`:
  - `_corporate_close` → `tx.corporate_close` (`backend/importing/normalizer.py:481`)
  - `_transfer_out` → `tx.transfer_out` (`backend/importing/normalizer.py:486`)
  - `_cost_basis_pending` → `tx.cost_basis_pending` (`backend/importing/normalizer.py:476`)
  - `_hoja` → columna sintética que agrega `xlsx_to_csv` con el título de la hoja (`backend/importing/excel.py:88-94`)

Ese namespace `_` es **privilegiado**: el parser genérico descarta a propósito toda columna de usuario que empiece con `_` para que nadie inyecte `_corporate_close` desde un CSV y saltee el guard `MISSING_PRICE` (`backend/importing/parsers/generic.py:104-117`).

---

### 9.3 Tabla maestra

| Broker | Archivo | Export / hojas que acepta | Cómo se detecta | Tipos que reconoce | ¿Precios? | ¿Comisiones? | ¿FX? | Limitaciones conocidas |
|---|---|---|---|---|---|---|---|---|
| **Template Rendi** | `generic.py` | CSV libre (`,`/`;`/tab, sniffer) | `fecha+tipo+broker` | Todos los aliases de `schema.OP_TYPE_ALIASES` | Sí (col. `precio`) | Sí (`comisiones`) | Sí (`CONVERSION_ARS_USD`) | Es el único multi-broker/multi-moneda; sin ancla de moneda |
| **Binance Spot** | `binance.py` | `Spot → Trade History` (CSV) | 6 columnas exactas | BUY / SELL | Sí (col. `Price`) | Sí, si el fee está en quote o base | No | Ventanas de 3 meses/archivo; **fee en BNB no se convierte NI baja tenencia** (sólo nota) |
| **Binance Futures** | `binance_futures.py` | `Futures → Trade History` | 7 columnas + fecha | `FUTURES_PNL` (1 por Order ID) | No (deriva avg) | Netea en el PnL | No | **`is_supported=False` → inalcanzable en prod** |
| **Binance completo** | `binance_transaction.py` | `Asset History → Transaction History` | 6 columnas exactas | COMPRA/VENTA (spot), FUTURES_PNL, INTERES, COMISION, DEPOSITO, RETIRO, `_transfer_out` | Derivado (`sold/rev`) | Sí (fees stable); fees cripto → venta `_transfer_out` | No | Cripto-cripto sin stable se resuelve por heurística de "quote-like"; USDT→USDC cae a VENTA |
| **Cocos Capital** | `cocos.py` | `Actividad → Movimientos` (CSV `;`, decimal AR) | ≥3 de 4 headers | COMPRA/VENTA, DEPOSITO/RETIRO, DIVIDENDO, FEE + conductos MEP | **Derivado** `montoBruto/cantidad` (ignora `precio` a propósito) | Sí (`comision+ddmm+iva+otros`) | Indirecto (conductos → RETIRO/DEPOSITO) | Moneda `EXT` se descarta en silencio; `canje` se descarta |
| **Balanz Órdenes** | `balanz.py` | `Operaciones → Órdenes → Exportar` | 4 campos + discriminador | **Sólo COMPRA/VENTA** | Sí (`Precio Operado`) | **No trae** | No | Se saltea transferencias, dólar bolsa, suscripción/rescate, canje, caución |
| **Balanz Movimientos** | `balanz_movimientos.py` | `Actividad → Movimientos` (xlsx) | `descripcion+importe+moneda` | ~12 (trade, corporate, diferida, transfer, FCI, boleto, renta, manual, fee, depósito, retiro, **FX**) | Sí (col. `Precio`, `-1`=sentinela) | Sí (**derivada** del gap bruto-neto, sólo ARS, cap 3%) | **Sí** (`Operación de Cambio` → FX_ARS_USD/USD_ARS) | Sweeps money-market con signo invertido → dirección de la posición del fondo puede quedar al revés |
| **Balanz Internacional** | `balanz_internacional.py` | `Actividad → Movimientos` de la cuenta exterior | **No autodetecta** (elección manual) | Igual que el local + `tax` (inglés) + reverse split | Sí | **No las separa** (embebidas en `|Importe|`) | No | Sin foto de tenencia; **sin pre-pass de `Operación de Cambio`** |
| **Balanz Resultados** | `balanz_resultados.py` | `Actividad → Resultados` (xlsx multi-hoja) | `tipo_mov+activo`+discriminador | — | — | — | — | **BLOQUEADO**: siempre devuelve error y redirige a Movimientos |
| **IOL** | `iol.py` | `Mi Cuenta → Movimientos → Movimientos Históricos` (.xls = tabla HTML) | ≥3 de 5 headers | COMPRA/VENTA, DIVIDENDO, INTERES, DEPOSITO, RETIRO, FEE, **FX**, caución sintética | **Derivado** `|Monto|/cantidad` | Suma `Comis.+Iva Com.+Otros Imp.` pero **las pone en 0** cuando usa `Monto` | **Sí** (2 detectores: bono-conducto y `Compra/Venta de Dólares`) | `Tipo Cuenta` nunca se validó contra datos reales (venía anonimizado) |
| **Charles Schwab** | `schwab.py` | `Accounts → History → Export CSV` | ≥3 de 4 headers | 11 acciones mapeadas + MoneyLink por signo + split + transfer | Sí (col. `Price`) | Sí (`Fees & Comm`) | No (todo USD) | Sin soporte multi-moneda; `_KNOWN_ETF_TICKERS` es una lista a mano |
| **Bull Market** | `bullmarket.py` | **2 layouts**: `Cuenta Corriente` (xlsx multi-hoja) y `Movimientos` (CSV con códigos) | 3 headers + (`comprobante`\|`cpbt*`) | COMPRA/VENTA, DEPOSITO/RETIRO, DIVIDENDO, FEE, INTERES (cauciones + futuros A3), saldo anterior | Sí (+ **fix per-100** heurístico) | **No** (siempre `"0"`) | Indirecto (patas MEP → RETIRO/DEPOSITO) | El layout Movimientos **hardcodea `moneda="ARS"`** en todas las filas |
| **IEB** | `ieb.py` | `Actividad → Movimientos totales` (xlsx) | ≥4 de 6 headers | ~15 códigos + wash PAGW↔COBW + DETR/RETR | Sí (col. `Precio`) | **No** (siempre `"0"`; los fees llegan como filas `ND`) | No | `asset_type` siempre vacío; FCI sólo como caja, no como tenencia |
| **PPI** | `ppi.py` | `Movimientos` (xlsx, **1 hoja por sub-cuenta de moneda** + hoja `Instrumentos`) | 4 headers exactos | trade, FCI, corporate, income, fee, signed, caución, `_transfer_out` | Sí (col. `Precio`) | **No** (no emite `comisiones`) | No | `COMPRA/VENTA SPOT` (conducto MEP) se **flaggea y descarta** |
| **inviu** | `inviu.py` | `Reporte de cuenta corriente` (xlsx con preámbulo y secciones por moneda) | 4 headers exactos | CPRA/VENTA, cobro/pago, dividendo/renta/amortización, genéricos por descripción | Sí (col. `Precio`) | Sí (**derivada** `\|Neto\|−\|Bruto\|`, **sin cap**) | No | Corta el parseo al llegar a `Disponible - Instrumentos`; catch-all sin flag |

---

### 9.4 Ficha por parser

#### 9.4.1 `generic.py` — Template Rendi (`rendi_generic`)

- **Export que consume**: el CSV que Rendi le da al usuario para descargar (`template_csv()`, `backend/importing/parsers/generic.py:52-66`), o cualquier CSV traducido por `mapper.apply_mapping`.
- **Dirección**: 100% por la columna `tipo`, resuelta contra `OP_TYPE_ALIASES` (~200 aliases castellano/inglés) en `backend/importing/schema.py:36-151`.
- **Ticker**: pass-through de la columna `activo`.
- **Moneda**: columna `moneda` por fila. **Único parser sin ancla de moneda de plataforma** — a propósito (`backend/tests/test_format_base_currency.py:33-36`).
- **Detalles**: auto-detecta separador con `csv.Sniffer` sobre los primeros 2 KB (`backend/importing/parsers/generic.py:75-79`); si el sniffer falla cae a `csv.excel`. Maneja BOM. Salta filas 100% vacías.
- **Guard de seguridad**: descarta columnas de usuario cuyo header normalizado empiece con `_` (`backend/importing/parsers/generic.py:104-117`) — el namespace de flags internos. Es la mitigación de una inyección real: `_corporate_close` saltearía el guard `MISSING_PRICE` de una venta a precio 0.

#### 9.4.2 `binance.py` — Binance Spot Trade History (`binance`)

- **Export**: `Date(UTC),Pair,Side,Price,Executed,Amount,Fee` (acepta `Time` en lugar de `Date(UTC)`, `backend/importing/parsers/binance.py:52-55`).
- **Dirección**: columna `Side` (`BUY`/`SELL`) tal cual — ya son aliases válidos (`backend/importing/parsers/binance.py:211`).
- **Ticker**: `_split_pair` (`backend/importing/parsers/binance.py:73-79`) parte el par sin separador probando 31 quote assets **ordenados por longitud descendente** (`backend/importing/parsers/binance.py:38-49`) para que `FDUSD` gane a `USD` y `USDT` a `USD`. Si no matchea ninguno, usa el par entero como activo y asume `USDT` (`backend/importing/parsers/binance.py:163-169`).
- **Números**: `_split_num_unit` (`backend/importing/parsers/binance.py:82-99`) separa `"0.02351000BTC"` en `(0.02351, "BTC")`.
- **Moneda**: `currency_map` mapea 8 stablecoins → `USD` y `ARS` → `ARS`; **cualquier otro quote (BTC/ETH/BNB) cae a `USD`** con una nota "valuado como USD" (`backend/importing/parsers/binance.py:196-207`).
- **Comisiones**: si el fee está en la quote → directo; si está en la base → `fee_qty × price`; **si está en BNB u otra cripto → `fee=0` y sólo se anota en `notas`** (`backend/importing/parsers/binance.py:179-190`). Ese fee **no baja la tenencia del coin**, a diferencia de lo que sí hace `backend/importing/parsers/binance_transaction.py:272-280`.
- **Limitaciones del docstring** (`backend/importing/parsers/binance.py:16-25`): exports limitados a ventanas de 3 meses; el "Transaction History" se declara NO soportado — **eso ya es obsoleto**, existe `binance_transaction.py` desde entonces. Comentario desactualizado.

#### 9.4.3 `binance_futures.py` — Binance Futures Trade History (`binance_futures_trade_history`)

- **Estado: APAGADO.** `is_supported = False` con el comentario "TEMP: oculto en la UI hasta estabilizar futures" (`backend/importing/parsers/binance_futures.py:77-79`). Consecuencia verificada: `autodetect` lo saltea (`backend/importing/parsers/registry.py:72`), `parser_options_grouped` lo filtra (`backend/importing/pipeline.py:1324-1327`) y el pipeline lo rechaza si se pide explícito (`backend/importing/pipeline.py:481-482`). **Es código inalcanzable en producción.**
- **Export**: `Time, Symbol, Side, Price, Quantity, Amount, Fee, Realized Profit, Buyer, Maker, Trade ID, Order ID`.
- **Dirección**: no hay compra/venta — agrupa por `Order ID` y emite **una fila `FUTURES_PNL`** por orden con `monto = Σ Realized Profit − Σ Fee` (`backend/importing/parsers/binance_futures.py:136-181`).
- **Ticker**: usa el símbolo del par completo (`"BTCUSDT"`) como activo, con la nota "el usuario puede editar después" (`backend/importing/parsers/binance_futures.py:174`).
- **Rareza**: si `|net| < 1e-8` la orden entera se descarta con el comentario `# apertura sin fee neta? skip` (`backend/importing/parsers/binance_futures.py:157-158`), pero el docstring del módulo (`backend/importing/parsers/binance_futures.py:19-20`) promete que las aperturas puras emiten una fila con `monto = −Σfees`. **El docstring y el código se contradicen.**
- **Agrupación sin Order ID**: la clave de fila suelta es `f"_solo_{id(raw)}"` — `id()` de un dict, o sea la **dirección de memoria** (`backend/importing/parsers/binance_futures.py:132`). Funciona porque los dicts están vivos, pero es frágil.

#### 9.4.4 `binance_transaction.py` — Binance Transaction History (`binance_transaction_history`)

El export más completo (Spot + Futures + Funding + P2P + Deposits + Withdraws en un archivo).

- **Export**: `User_ID, Time, Account, Operation, Coin, Change, Remark`.
- **Estructura**: cada trade spot ocupa varias filas con el mismo timestamp. El parser hace tres buckets (`backend/importing/parsers/binance_transaction.py:170-183`): spot agrupado **por `Time`**, futuros agrupados **por `TradeID` del Remark** (regex `backend/importing/parsers/binance_transaction.py:64`), y el resto fila por fila.
- **Dirección (spot)**: cascada de 5 reglas (`backend/importing/parsers/binance_transaction.py:228-256`):
  1. revenue stable + sold no-stable → **VENTA**
  2. sold stable + revenue no-stable → **COMPRA**
  3. revenue es `BTC/ETH/BNB/...` y sold no → **VENTA**
  4. sold es cripto-quote y revenue no → **COMPRA**
  5. **default: VENTA** — cubre stable→stable (USDT→USDC) y cripto-cripto ambiguo. Es un fallback silencioso.
- **Dirección (single rows)**: por **tipo de coin y signo** (`backend/importing/parsers/binance_transaction.py:336-376`). Stable/fiat → DEPOSITO/RETIRO; cripto que entra → COMPRA a precio 0; cripto que sale → VENTA con `_transfer_out` (cierra el lote a costo, P&L 0). Las `Transfer*` internas se ignoran (`backend/importing/parsers/binance_transaction.py:343`).
- **Fees**: las stable van a `comisiones`; **las cripto se emiten como una VENTA `_transfer_out` aparte** para que el saldo del coin reconcilie (`backend/importing/parsers/binance_transaction.py:213-219`, `:272-280`) — el comentario cita el caso real de "la fee de 32 HBAR no se descontaba".
- **Regla de negocio rara pero explicada**: micro-trades de futuros con `|net| < $0.5` se emiten como `COMISION` en vez de `FUTURES_PNL`, para no ensuciar win rate / profit factor (`backend/importing/parsers/binance_transaction.py:283-309`).
- **Moneda**: `_currency_for` (`backend/importing/parsers/binance_transaction.py:105-110`) — 8 stables → `USD`, `ARS` → `ARS`, **todo lo demás → `USD`**.

#### 9.4.5 `cocos.py` — Cocos Capital (`cocos`)

- **Export**: `app.cocos.capital → Actividad → Movimientos`, CSV **semicolon-separated con decimal coma y miles punto** (`backend/importing/parsers/cocos.py:1-13`).
- **Dirección**: `_resolve_op` (`backend/importing/parsers/cocos.py:87-144`) — primero match exacto contra `_OP_MAP` (12 entradas, `backend/importing/parsers/cocos.py:64-77`), después **12 reglas por patrón**, en orden deliberado:
  - `nota` + `debito` → **FEE** (va primero para que `"Nota Debito Dividendos ARS"` no lo capture la regla de dividendos por subcadena)
  - `dividendo` → DIVIDENDO; `amortizacion`/`renta*` → DIVIDENDO ("sin esto se perdían millones de pesos de maduraciones")
  - `registracion`/`esp app` → **conducto MEP**: `venta*`→DEPOSITO, resto→RETIRO
  - `caucion` → `termino|cierre`→DEPOSITO, resto→RETIRO
  - `compra*`→COMPRA, `venta*`→VENTA (último)
- **Ticker**: `_extract_ticker` toma el último paréntesis del `instrumento` con la regex `backend/importing/parsers/cocos.py:150` (permite espacios: `(SBSACAR AR)` → `SBSACAR`). Si no hay paréntesis y el nombre parece bono (`is_bond_like_name`, `backend/importing/maturity.py:127`), sintetiza un ticker desde el vencimiento (`synth_letra_ticker`) — si no, todas las letras caerían en un activo vacío (`backend/importing/parsers/cocos.py:511-521`).
- **Moneda**: la columna `moneda` es **autoritativa** cuando dice ARS/USD; sólo se fuerza USD por "dolar mep" si la columna no distingue (`backend/importing/parsers/cocos.py:492-501`). El comentario nombra la causa raíz que arregló: forzar USD contaba pesos como dólares (×tc_blue) y el FIFO calculaba `pnl = proceeds_USD − costo_PESOS` → capital negativo gigante.
- **Precio: NO usa la columna `precio`.** Deriva `precio = montoBruto / cantidad` (`backend/importing/parsers/cocos.py:544-552`) porque el formato AR de Cocos es ambiguo (`'10.094,497'` → 10094.497 cuando el real es 10.094) y un precio inflado ×1000 generaba P&L falso millonario.
- **Comisiones**: `|comision| + |ddmm| + |iva| + |otros|` (`backend/importing/parsers/cocos.py:227-239`, `backend/importing/parsers/cocos.py:553-558`).
- **asset_type**: `CEDEAR` si el instrumento empieza con "CEDEAR"; `FUND` si dice FCI y el ticker no tiene dígitos; `BOND` si dice FCI **y** el ticker tiene dígitos (ONs suscritas vía el tipo FCI) (`backend/importing/parsers/cocos.py:522-542`).
- **Conductos MEP con bono** (`_detect_mep_conduits`, `backend/importing/parsers/cocos.py:303-353`): aparea "Compra ARS" + "Venta Dolar Mep USD" del mismo bono, misma cantidad, ≤5 días, y reclasifica la compra a RETIRO y la venta a DEPOSITO. Acotado a bonos por `_is_bond_instrument` (`backend/importing/parsers/cocos.py:274-291`), que tiene un guard explícito: **un CEDEAR nunca es bono** — sin él, `"CEDEAR NVIDIA CORPORATION (NVDA)"` disparaba la pista `"on "` y 6 de 12 CEDEARs entraban al detector, que borra las dos patas.
- **Skips silenciosos**: moneda distinta de ARS/USD/vacío (`backend/importing/parsers/cocos.py:426-429`), `canje` (`backend/importing/parsers/cocos.py:430-433`), dividendo en especie USD/acciones (`backend/importing/parsers/cocos.py:447-467`).
- **Código muerto**: `_OP_SKIP: set = set()` (`backend/importing/parsers/cocos.py:84`) **no se usa en ningún lado** [V].

#### 9.4.6 `balanz.py` — Balanz Órdenes (`balanz`)

- **Export**: `Operaciones → Órdenes → Exportar`.
- **Filtro de estado**: sólo `ejecutada` y `parcialmente cancelada` (`backend/importing/parsers/balanz.py:74`, `:235-237`).
- **Dirección**: `_map_operacion` (`backend/importing/parsers/balanz.py:89-105`) — `startswith("compra")`/`startswith("venta")`, con exclusión previa de `"dolar bolsa"`. **Todo lo demás se saltea** (transferencia, suscripción/rescate, canje, caución, cambio de fondo, depósito).
- **Cantidad/precio**: prefiere `Cantidad Operada` / `Precio Operado`, con fallback a los ordenados; `_val` (`backend/importing/parsers/balanz.py:171-174`) rechaza el centinela `-1`.
- **Moneda**: `_norm_currency` (`backend/importing/parsers/balanz.py:77-86`) — `peso*`→ARS, `dolar*`/`dollar`→USD.
- **asset_type**: `_classify_asset` por **patrón de ticker** (`backend/importing/parsers/balanz.py:112-132`): `FCI*`→FUND; `^[STX]\d`→BOND (letras/lecaps/boncer); prefijo en `_AR_BOND_PREFIXES` + dígito→BOND; ≥5 chars terminado en "O"→BOND (ONs). Es explícitamente conservador.
- **Limitación admitida**: `"el export de órdenes no trae comisiones"` (`backend/importing/parsers/balanz.py:266`), y el docstring avisa que fue construido sobre un export real de 2026-01 (`backend/importing/parsers/balanz.py:28-29`).
- **Consecuencia** [I]: este export **no trae depósitos ni retiros**, o sea sufre el mismo problema de capital aportado que hizo bloquear `balanz_resultados`, pero acá no está bloqueado.

#### 9.4.7 `balanz_movimientos.py` — Balanz Movimientos (`balanz_movimientos`) — el recomendado

Es el parser más elaborado del repo junto con `iol.py`. Regla de oro: **`Importe` es el efecto en cash y manda el signo; `monto = abs(Importe)` siempre** (`backend/importing/parsers/balanz_movimientos.py:12-16`).

- **Clasificación**: `_classify_desc` (`backend/importing/parsers/balanz_movimientos.py:129-181`) devuelve uno de 9 `kind`: `transfer`, `corporate`, `diferida`, `deposito`, `retiro`, `fee`, `renta`, `manual`, `boleto`, `otro`.
- **Pre-pass FX** (`backend/importing/parsers/balanz_movimientos.py:266-311`): `"Operación de Cambio / <nro>"` llega en **dos filas del mismo número** (una en Pesos, otra en Dólares, signos opuestos). Se colapsan en UNA `FX_ARS_USD`/`FX_USD_ARS` con `monto`=ARS y `monto_usd`=USD. El comentario cita el caso real: 32 conversiones que quedaban afuera y ningún saldo cerraba.
- **Pre-pass FCI** (`backend/importing/parsers/balanz_movimientos.py:313-321`): indexa las `"Liquidación de Suscripción/Rescate"` por `(ticker, fecha, |cantidad|)` para saltear su fila espejo `"desde/a Balanz"` y no duplicar la tenencia.
- **Fix de moneda mal-etiquetada** (`backend/importing/parsers/balanz_movimientos.py:349-357`): Balanz manda algunos FCI money-market en pesos marcados como `Dólares`. La heurística: **si es FUND, dice USD y el VCP > 5 → es ARS**. El comentario lo señala como causa raíz de la mitad de los `capital_final` negativos de 78 cuentas.
- **Dirección por rama**:
  - `corporate` → `qty>0`: COMPRA precio 0; `qty<0`: VENTA precio 0 con `_corporate_close` (`:386-405`)
  - `diferida` → COMPRA/VENTA por signo de `Importe` (`:413-420`)
  - `transfer` → COMPRA a su costo + DEPOSITO compensatorio (cash netea 0) (`:430-446`)
  - FCI → **por NOMBRE, no por signo**, porque Balanz invierte el signo ahí (`:448-460`)
  - trade normal → **por signo de `Importe`** (`:461-497`)
  - `boleto` sin precio → el token `COMPRA/VENTA/LICOMPRA/LIVENTA` de la descripción define FEE vs DEPOSITO; el resto por signo (`:505-517`)
  - `renta` con `"amortizacion"` + cantidad → **VENTA al valor de rescate** (devolución de capital), con dedup por `(ticker, fecha, |cantidad|)` en `_amort_closed` para no cerrar el nominal dos veces (`:537-556`)
- **Comisión "embebida"** (`backend/importing/parsers/balanz_movimientos.py:469-497`): en trades **en pesos**, Balanz no trae columna de comisión; vive en `|Precio×Cantidad − |Importe||`. Se extrae, pero con dos guards: sólo ARS (en USD la comisión llega como fila ARS aparte y el gap es ruido FX) y **cap del 3%** (si el gap es absurdo — bono per-100 leído per-1 — no es comisión y cae al comportamiento viejo).
- **Impuestos vs comisiones**: `_is_tax` (`backend/importing/parsers/balanz_movimientos.py:184-192`) distingue retenciones (IIGG/IIBB/Bienes Personales) → `IMPUESTO`, de fees → `FEE`. **Sólo se usa en la rama `manual`** (`:568-573`) [V]; las demás ramas deciden por signo.
- **Descripción no reconocida → se marca, no se traga**: emite `BALANZ_MOV_DESC_DESCONOCIDA` (`backend/importing/parsers/balanz_movimientos.py:575-580`).
- **Limitación declarada en el docstring** (`backend/importing/parsers/balanz_movimientos.py:25-30`): los fondos money-market "Suscripción/Rescate desde/a Balanz" traen el signo invertido → el cash reconcilia pero **la dirección de la posición del fondo-sweep puede quedar invertida**.

#### 9.4.8 `balanz_internacional.py` — Balanz cuenta exterior (`balanz_internacional`)

- **Export**: `Actividad → Movimientos` de Balanz Capital International (Panamá). **Mismas columnas exactas que el local** → `can_handle` devuelve `False` a propósito (`backend/importing/parsers/balanz_internacional.py:126-130`) y se elige por tarjeta propia en el wizard.
- **Plataforma separada** (`backend/importing/parsers/balanz_internacional.py:117-122`): no cuelga de "balanz" porque el wizard auto-elige el primer export de la plataforma y el usuario nunca podría llegar al internacional.
- **Ticker**: `_clean_ticker` (`backend/importing/parsers/balanz_internacional.py:63-70`) saca el **punto final** (`"ADBE."` → `ADBE`) — símbolos US reales, se valúan por el ticker US, no por `.BA`.
- **Moneda**: todo USD (`_norm_ccy(...) or "USD"`, `backend/importing/parsers/balanz_internacional.py:185`); anclado en `FORMAT_BASE_CURRENCY['balanz_internacional'] = 'USD'` (`backend/importing/pipeline.py:435`).
- **Diferencias con el local** (todas en el docstring, `backend/importing/parsers/balanz_internacional.py:12-27`): op-tokens `COMPRAEXT/VENTAEXT/CSBNG/VSBNG`; `US Treasuries`→BOND; `Reverse Split`; `Tax Withholding` + su reversal (kind `tax`, `:285-288`); FCI con `Precio = -1` → **no exige precio** (el normalizer deriva `monto/cantidad`) (`:249-274`).
- **Comisiones**: **no se separan.** `monto = |Importe|` "incluye la comisión ~US$10 embebida en el cash → costo-base correcto" (`backend/importing/parsers/balanz_internacional.py:275-281`). Nunca emite `comisiones` [V] (0 ocurrencias del literal en el archivo).
- **Sin foto**: no declara `tenencia_format` [V], y hay un test que lo blinda (`backend/tests/test_tenencia_capability.py:50-56`).
- **Gap** [I]: **no tiene el pre-pass de `Operación de Cambio`** que sí tiene el local (`backend/importing/parsers/balanz_movimientos.py:266-311`). Si la cuenta exterior alguna vez trae una conversión, caería en `_classify_desc → "otro"` y se marcaría como descripción desconocida.

#### 9.4.9 `balanz_resultados.py` — Balanz Resultados (`balanz_resultados`) — **BLOQUEADO**

- **Estado real**: `can_handle` sigue detectando el formato, `parse()` **siempre** agrega `BALANZ_RESULTADOS_NO_SOPORTADO` y hace `return result` en `backend/importing/parsers/balanz_resultados.py:202-209`.
- **Motivo documentado** (`backend/importing/parsers/balanz_resultados.py:194-201`): el export no trae efectivo → capital aportado negativo, y matchea mal las cerradas cross-currency (**"visto ~78× en un caso real"**). Se redirige al usuario al export de Movimientos.
- **Consecuencia**: **las líneas 211 a 364 (~155 líneas) son código inalcanzable** [V] — todo el dispatch por `Tipo Movimiento`, el manejo de cupones/dividendos/cauciones, los lotes gratis por `Dividendo en acciones`/`Split`, y el cierre `_corporate_close` por "Reducción/Devolución de capital". Sigue mantenido en el árbol y comentado como si estuviera vivo.
- **Lo que ese código muerto haría** (para referencia si se rehabilita): sólo procesa la hoja `por_realizado` (`:229-237`); `No Realizado`→COMPRA, `Orden`→COMPRA+VENTA, `Cupón`→INTERES, `Dividendo`→DIVIDENDO, `Caución`→INTERES, resto→error explícito para no crear compras espurias.

#### 9.4.10 `iol.py` — IOL / InvertirOnline (`iol`) — 787 líneas, el más grande

- **Export**: `Mi Cuenta → Movimientos → Detalle → Descargar movimientos históricos`. Baja un `.xls` que **no es Excel: es una tabla HTML**, que `backend/importing/excel.py` (`is_html_table`/`html_table_to_csv`) aplana a CSV antes de llegar al parser (`backend/importing/parsers/iol.py:9-14`).
- **Dirección**: `_resolve_op` (`backend/importing/parsers/iol.py:202-224`) mira el **prefijo del `Tipo Mov.`** (lo de antes del primer paréntesis, deacentuado): `transferencia de titulos`→skip, `compra*`→COMPRA, `venta*`→VENTA, `suscripcion`→COMPRA, `rescate`→VENTA, `dividendo|renta|amortizacion`→DIVIDENDO, `credito`→INTERES, `deposito`→DEPOSITO, `extraccion`→RETIRO.
- **Ticker**: `_extract_raw_ticker` toma el **último** paréntesis (`backend/importing/parsers/iol.py:174-178`), y `_clean_ticker` **delega en `strip_cd_suffix`** de `backend/importing/tickers_cd.py:117-141` (`backend/importing/parsers/iol.py:185-197`). El docstring lo dice explícito: el algoritmo vivía duplicado en dos lugares con dos copias de la lista de excepciones, y **un fix aplicado a una sola se perdió en silencio** (el mapeo brasileño).
- **Sufijo D/C**: consolida `GGALD→GGAL`, `AL30D→AL30` salvo `KNOWN_CD_TICKERS` (AMD, GOLD, INTC, SID, SCHD, LAC…) y salvo FCI. Los CEDEARs brasileños tienen mapa explícito (`PETRD→PETR3`). **IOL es el único parser que llama `strip_cd_suffix` directo** [V]; el resto pasa por `consolidate_cd` en el normalizer (`backend/importing/normalizer.py:451`), que además gatea por `asset_type`.
- **Tres detectores de pares** (el corazón del parser):
  1. **`_detect_iol_conduits`** (`backend/importing/parsers/iol.py:266-382`): dólar-MEP con **bono puente**. Firma exacta: pata pesos (ticker base) + pata dólar (ticker con D/C) **partida en 2 filas del mismo Boleto** (monto USD + residual en pesos = impuesto), misma cantidad, dirección opuesta, **mismo día**, y guard de tasa `100 ≤ ARS/USD ≤ 100000`. Colapsa en **un FX** (no en DEPOSITO/RETIRO, para no inflar capital aportado), emite el residual como FEE y descarta la pata dólar. Sin esto: posición fantasma del bono (`AL30 neto −169`), P&L basura y caja fabricada.
  2. **`_detect_iol_dolar_directo`** (`backend/importing/parsers/iol.py:384-458`): `"Compra/Venta de Dólares"` sin ticker y cantidad 0, en dos filas. Empareja por `(dirección, fecha, campo Precio crudo)`. Trata el formato sucio de IOL probando **÷100 primero y literal después** (`backend/importing/parsers/iol.py:399-414`), con guard de tasa `10 ≤ ARS/USD ≤ 2000`; si ninguna interpretación da plausible, **no colapsa** y la fila cae al error visible.
  3. **`_detect_iol_fci_phantoms`** (`backend/importing/parsers/iol.py:461-505`): doble-booking de FCI en dólares — dos filas del mismo Boleto+activo+cantidad, una con Monto y otra en 0. Descarta la de Monto 0.
- **Cauciones** (`backend/importing/parsers/iol.py:605-621`, `:770-787`): acumula el **neto por moneda** (colocación + liquidación) y emite **una fila sintética de INTERES por moneda** al final, sólo si el neto > 0. La moneda sale **exclusivamente de `Tipo Cuenta`** — el comentario explica por qué: la colocación trae la moneda en el tipo pero la liquidación no, y mezclar señales partía las patas en buckets distintos y booqueaba el **principal entero como interés fantasma**.
- **Precio: derivado.** Para COMPRA/VENTA usa `|Monto|` como bruto y `precio = |Monto| / cantidad` (`backend/importing/parsers/iol.py:700-720`), **poniendo `comisiones = "0"`** porque el `Monto` ya viene neto. Motivo citado: para bonos (per-100) y patas MEP/cable, `cantidad × Precio` se infla **hasta 10.000×**. Sólo si no hay `Monto` usable cae al fallback `cantidad × Precio` con las comisiones sumadas.
- **Moneda**: `Tipo Cuenta` + sufijo `US$` del ticker, **default ARS** (`backend/importing/parsers/iol.py:672-681`). ⚠️ **Advertencia del propio docstring** (`backend/importing/parsers/iol.py:41-47`): los ejemplos que recibieron tenían `Tipo Cuenta` aplastado a "Cuenta Anonimizada", así que **las etiquetas de moneda nunca se validaron contra datos reales**. El matching es liberal (`_CUENTA_USD_HINTS` incluye `"cable"`, `"ccl"`, `"mep"`, `"exterior"`).
- **Filas sin caja se saltean** (`backend/importing/parsers/iol.py:733-738`): eventos de bono que IOL parte en una fila de cash + otra nominal.

#### 9.4.11 `schwab.py` — Charles Schwab (`schwab`)

- **Export**: `Accounts → History → Export CSV`, headers entre comillas.
- **Dirección**: `_OP_MAP` con 11 acciones (`backend/importing/parsers/schwab.py:72-85`); `MoneyLink Transfer/Deposit/Adj` **por signo del `Amount`** (`backend/importing/parsers/schwab.py:321-326`).
- **Fecha**: `_parse_date` (`backend/importing/parsers/schwab.py:143-158`) prefiere la parte **`as of`** cuando existe (`"02/09/2026 as of 02/06/2026"` → `2026-02-06`), porque esa es la fecha efectiva.
- **Números**: `_clean_money` saca `$` y comas (`backend/importing/parsers/schwab.py:161-165`); convención US estricta.
- **Transferencia de securities** (`backend/importing/parsers/schwab.py:97-110`, `:249-277`): el caso TD Ameritrade→Schwab. La pata **IN** (`qty > 0`) se importa como COMPRA con `_cost_basis_pending = "1"` para que el wizard pida el cost basis; la pata **OUT** (`qty ≤ 0`) se ignora; las filas sin símbolo (cash interno) se ignoran. Antes se descartaban ambas y las posiciones que entraron 100% por transferencia desaparecían.
- **Stock Split** (`backend/importing/parsers/schwab.py:288-315`): se modela como **COMPRA con precio 0** de las acciones extra. El comentario incluye la aritmética: 3 XLK a $289.28 + 3 a $0 = 6 a $144.64 promedio, y el FIFO da P&L correcto en agregado. **Es el único parser que importa splits** — el genérico los rechaza con un mensaje de `UNSUPPORTED_OP_HINTS` (`backend/importing/schema.py:159-161`).
- **Bruto**: `qty × price` (no el `Amount`, que viene neto) con fallback a `|Amount|` (`backend/importing/parsers/schwab.py:339-350`).
- **`_KNOWN_ETF_TICKERS`** (`backend/importing/parsers/schwab.py:111-127`): lista **a mano** de 10 tickers (ETH, ETHE, GBTC, BITO, XLK, SPY, QQQ, VOO, VTI, IVV) que se marcan `ETF` para que la heurística genérica no clasifique el Grayscale Ethereum Trust como cripto raw. [I] Es una allowlist que no escala: cualquier otro producto Grayscale nuevo cae mal.
- **Moneda**: `USD` hardcodeado en todas las filas [V].
- **Sin foto de tenencia** (`tenencia_format` no declarado) [V].

#### 9.4.12 `bullmarket.py` — Bull Market (`bullmarket`) — dos layouts en un parser

**Único parser con dispatch interno por layout** (`backend/importing/parsers/bullmarket.py:279-284`): si hay `Cpbt.` y no `Comprobante` → `_parse_movimientos`; si no → `_parse_cuenta_corriente`.

**Layout 1 — Cuenta Corriente (Excel, `_parse_cuenta_corriente`, `backend/importing/parsers/bullmarket.py:309-487`)**

- **Moneda por HOJA**: `_currency_from_sheet` mira la columna sintética `_hoja` que agrega `xlsx_to_csv` — `"DOLAR" in hoja` → USD, si no ARS (`backend/importing/parsers/bullmarket.py:184-190`).
- **Dirección**: `_classify_comprobante` por **prefijo** (`backend/importing/parsers/bullmarket.py:87-125`) + corrección **por signo del `Importe`** (`backend/importing/parsers/bullmarket.py:381-393`): `FEE_SIGNED`→FEE/DIVIDENDO, DIVIDENDO con importe negativo→FEE, DEPOSITO negativo→RETIRO, RETIRO positivo→DEPOSITO. "El cash emitido siempre matchea el Importe".
- **Cauciones** (`backend/importing/parsers/bullmarket.py:333-345`): especie `"VARIAS"`; se acumula el neto por moneda → una fila de INTERES al final, sólo si es > 0.
- **Futuros de dólar A3/Matba-Rofex** (`backend/importing/parsers/bullmarket.py:347-360`, `:465-486`): especie tipo `DLR072023`; el neto **sí puede ser negativo** → INTERES si ganó, FEE si perdió. El comentario dice que antes caían en "tipo no soportado" y se perdían **58 filas** de un usuario real.
- **Conversiones cable↔MEP** (`backend/importing/parsers/bullmarket.py:362-366`): `"nota de" + "u$s"` → se omiten (mueven los mismos dólares entre sub-cuentas).
- **FCI**: rescate→VENTA (trae cantidad+precio), suscripción→RETIRO (no trae unidades). **La tenencia del FCI no se reconstruye** — declarado como follow-up (`backend/importing/parsers/bullmarket.py:33-37`, `:88-96`).

**Layout 2 — Movimientos (CSV compacto, `_parse_movimientos`, `backend/importing/parsers/bullmarket.py:492-712`)**

- **Signo INVERTIDO**: en este export **negativo = ingreso de plata** (`backend/importing/parsers/bullmarket.py:11-13`, `:670-673`).
- **Cantidad y precio pegados** en un solo campo `Referencia/Cantidad/Precio` → `_split_ref` (`backend/importing/parsers/bullmarket.py:219-231`).
- **Leyenda del pie como fuente de verdad** (`backend/importing/parsers/bullmarket.py:601-624`): el export trae al final una fila por código con su descripción larga; el parser la lee y la clasifica con `_classify_comprobante`, así **un código nuevo se entiende solo**. Sólo si no hay leyenda cae al `_MOV_CODE_MAP` fijo (`backend/importing/parsers/bullmarket.py:127-135`).
- **Patas del dólar bolsa** (`backend/importing/parsers/bullmarket.py:558-599`, `:632-645`): dos sentidos. Comprar dólares = `CPRA` (bono en pesos) + `VTU$` (venta paridad sin importe) → la CPRA se emite como **RETIRO**. Vender dólares = `CPU$` + `VTAS` → la VTAS se emite como **DEPOSITO**. El emparejamiento es por `(especie, |cantidad|)` con **contador de patas** para no consumir de más — el comentario cuenta el bug previo: se descartaba toda fila de una especie que alguna vez hizo MEP, y eso **se comió 4 ventas reales por $3.581.048**.
- **`S.ANTERIOR`** (`backend/importing/parsers/bullmarket.py:617-625`): el saldo con el que arranca el archivo se emite como DEPOSITO/RETIRO para que la caja reconcilie.
- **Bono per-100** (`backend/importing/parsers/bullmarket.py:686-690`): heurística `if abs(q*p − 100*monto) < abs(q*p − monto): p = p/100`. **Es el único parser con corrección per-100 explícita** [V].
- **⚠️ Moneda hardcodeada `"ARS"`** en TODAS las filas de este layout (`backend/importing/parsers/bullmarket.py:670`, `:692`, `:696`, `:700-702`) — el docstring lo admite ("el CSV de Movimientos es ARS", `backend/importing/parsers/bullmarket.py:67`), pero significa que un movimiento en dólares de ese export se importa como pesos.
- **Comisiones**: siempre `"0"` en los dos layouts (`backend/importing/parsers/bullmarket.py:247`, `_mk_row`) [V].

#### 9.4.13 `ieb.py` — IEB / Invertir en Bolsa (`ieb`)

- **Export**: `hb.iebmas.com.ar → Actividad → Movimientos totales` (.xlsx). Los vacíos vienen como `"-"` (manejado en `_num`, `backend/importing/parsers/ieb.py:199-208`).
- **El bug fundacional, documentado** (`backend/importing/parsers/ieb.py:82-89`): el parser se escribió contra un export de **demo con códigos cortos** (CPRA/VTAS/DETR), pero el archivo real de la web trae **descripciones largas** ("COMPRA NORMAL", "DEPOSITO TITULOS TRANSF.") → **rechazaba 305 de 305 filas**. La solución fue `_LABEL_TO_CODE` (`backend/importing/parsers/ieb.py:91-120`) + `_label_to_code` con patrones (`backend/importing/parsers/ieb.py:137-178`), que normaliza las dos formas al mismo código antes de resolver el tipo.
  - Incluye erratas del propio broker: `"COMPRA TRAIDING PARIDAD"` y `"VENTA TRAINDIG PARIDAD"` (sic, `backend/importing/parsers/ieb.py:99`, `:102`).
  - **El orden importa y está comentado** (`backend/importing/parsers/ieb.py:145-147`): `"DEBITO RET DIVIDENDOS"` contiene "DIVIDENDO", así que los cargos se resuelven antes que la renta.
  - Si no reconoce nada, devuelve la etiqueta normalizada sin espacios **para que `_resolve_op` falle visiblemente** en lugar de que la fila desaparezca (`backend/importing/parsers/ieb.py:139-142`).
- **Dirección**: `_resolve_op(code, amount)` (`backend/importing/parsers/ieb.py:211-262`) usa código **+ signo del importe** para los ambiguos: `DIV`/`RTA` (positivo→DIVIDENDO, negativo→FEE), `COUW`/`PAUW`/`CU$V` (dólar, por signo), `LS*`/`LR*` (FCI, por signo). Fallbacks por familia: `ND*`→FEE, `COB*`→DEPOSITO.
- **Wash PAGW↔COBW** (`backend/importing/parsers/ieb.py:317-333`, `:352-355`): pago + cobro del mismo ticker/día/|monto|/moneda son un movimiento interno que netea a 0 → se saltean ambos.
- **DETR** (`backend/importing/parsers/ieb.py:362-390`): transferencia de títulos **entrante** → COMPRA con su costo + **DEPOSITO compensatorio** (mismo patrón que Balanz "Transferencia Externa"). ⚠️ **Emite dos `RawRow` con el MISMO `row_index=idx`** (`backend/importing/parsers/ieb.py:371` y `:379`).
- **RETR** (`backend/importing/parsers/ieb.py:392-409`): título **saliente** → VENTA precio 0 con `_transfer_out = "1"` (cierra el lote a costo, P&L 0, sin cash).
- **Moneda**: por columna (`Importe divisas` presente → USD, si no `Importe ARS` → ARS), con el sufijo del código pisando para trades USD (`backend/importing/parsers/ieb.py:334-345`).
- **Limitaciones declaradas en el docstring** (`backend/importing/parsers/ieb.py:29-44`): FCI sólo como flujo de caja (no como cuotaparte); `DIV`/`RTA` con doble pata (bruto ARS negativo + neto `OTHER` positivo) **queda ABIERTO**; no hay snapshot de tenencia; si el export es una ventana faltan las posiciones previas.
- **`asset_type` siempre vacío** (`backend/importing/parsers/ieb.py:445`) — "IEB no distingue CEDEAR/acción/bono en el export".
- **Comisiones**: siempre `"0"` (`backend/importing/parsers/ieb.py:443`); los cargos llegan como filas `ND` propias.

#### 9.4.14 `ppi.py` — PPI / Portafolio Personal (`ppi`)

- **Export**: `Mi cuenta → Movimientos` (Excel) con **una hoja por sub-cuenta de moneda** (Pesos, Dolar MEP, Dolar Cable, DolarCV7000/CV10000, variantes "… - COM 7340") **+ una hoja `Instrumentos`** (movimientos de títulos sin cash). Ruteo por `_hoja` (`backend/importing/parsers/ppi.py:1-10`).
- **Regla de oro**: igual que Balanz — `Importe` = efecto en cash, `monto = abs(Importe)`. Pero con un matiz importante: **para trades y fondos la dirección sale del TEXTO, no del signo** (`backend/importing/parsers/ppi.py:14-21`), porque "un archivo anonimizado tenía las VENTAS con Importe negativo".
- **Clasificación**: `_classify` (`backend/importing/parsers/ppi.py:143-176`) devuelve `caucion`, `fund_sub`, `fund_red`, `hold`, `trade`, `deposito`, `retiro`, `corporate`, `income`, `fee`, `signed`, `unknown`. `caucion` va **primero** para no confundirse con los `liquidacion de…` de FCI.
- **Hoja `Instrumentos`** (`backend/importing/parsers/ppi.py:276-296`): `"Retiro de Títulos"` → VENTA precio 0 con `_transfer_out`; los COMPRA/VENTA se **saltean** (redundantes con la hoja de moneda, que trae el precio); todo lo demás (Ingreso de Títulos / Canje / Traspaso) se **flaggea** como `PPI_INSTRUMENTO_NO_SOPORTADO`.
- **Bloqueo/Desbloqueo Monetario** (`kind == "hold"`, `backend/importing/parsers/ppi.py:306-308`): holds contables que netean con la Liquidación → skip para no doble-contar.
- **SPOT** (`backend/importing/parsers/ppi.py:310-322`): `COMPRA SPOT`/`VENTA SPOT` es el conducto dólar-MEP; el ticker real vive en `Instrumentos` y la cantidad no matchea → **se flaggea y se descarta** (`PPI_SPOT_REVIEW`). Es el único conducto MEP que Rendi **no** resuelve (Cocos, IOL y Bull Market sí).
- **FCI** (`backend/importing/parsers/ppi.py:331-341`): el nombre del fondo es el **último segmento de la descripción** (`"… / Allaria Dolar Ahorro - Clase A"`), y se usa **el nombre completo en mayúsculas como `activo`** con `asset_type="FUND"`. [I] Eso hace que el símbolo del FCI sea una frase larga, no un ticker.
- **Cauciones** (`backend/importing/parsers/ppi.py:298-304`, `:379-385`): neto por moneda → una fila de INTERES al final, sólo si > 0.001.
- **Moneda**: `_ccy` (`backend/importing/parsers/ppi.py:113-118`) — `"DOLAR" in (moneda|hoja)` → USD, si no ARS. **Todas las sub-cuentas dólar colapsan a USD**; el detalle MEP/cable/CV se pierde a propósito.
- **Comisiones**: nunca emite `comisiones` [V] (0 ocurrencias del literal en el archivo).
- **Código muerto**: la rama `elif kind in ("signed", "manual")` (`backend/importing/parsers/ppi.py:370`) — `_classify` **nunca devuelve `"manual"`** [V].
- **Follow-ups del docstring** (`backend/importing/parsers/ppi.py:48-54`): SPOT; canjes internos USD↔USD que caen como INTERES/FEE que netean; la amortización no baja el nominal del bono; `asset_type` no viene en el export.

#### 9.4.15 `inviu.py` — inviu (`inviu`)

- **Export**: `Reporte de cuenta corriente` (Excel) con **preámbulo** (título + metadata antes del header real, que `xlsx_to_csv` detecta y saltea) y **secciones por moneda** dentro de la misma grilla (`backend/importing/parsers/inviu.py:1-10`).
- **Moneda por SECCIÓN, no por columna** (`backend/importing/parsers/inviu.py:112-119`, `:213-218`): una fila marcador (`"PESOS - $"`, `"Dólar MEP - U$S"`, `"Dólar Cable - U$C"`) cae en la primera columna y **cambia la moneda vigente** para todas las filas siguientes. Ambas variantes de dólar consolidan a USD. Es un parser **con estado de máquina**, único en el repo.
- **Corte duro por variante** (`backend/importing/parsers/inviu.py:205-211`): si aparece `"Disponible - Instrumentos"` (export "Consolidada") se hace `break`. El comentario explica el bug: sin el corte, **cada boleto se importaba dos veces** y la segunda con montos en pesos etiquetados como dólares → cartera inflada ×miles.
- **Dirección**: por la columna `Tipo de Operación` — `CPRA`→COMPRA, `VENTA`→VENTA (`backend/importing/parsers/inviu.py:250-258`); `Recibo de Cobro`/`Comprobante de Pago` con corrección por signo (`:264-270`); dividendo/renta/amortización → DIVIDENDO si entra, IMPUESTO si sale (`:272-277`).
- **Comisión derivada** (`backend/importing/parsers/inviu.py:252-257`): `comision = | |Importe Neto| − |Import Bruto| |`, y se emite `monto = |Bruto|`. **Sin cap ni guard** — a diferencia del 3% de Balanz Movimientos (`backend/importing/parsers/balanz_movimientos.py:485-488`). [I] Si `Bruto` viniera en otra escala (bono per-100), la "comisión" resultante sería gigante.
- **`Cantidad VN` viene negativa en las ventas** → se usa `abs` (`backend/importing/parsers/inviu.py:27`, `:254`).
- **Catch-all sin flag** (`backend/importing/parsers/inviu.py:279-290`): los genéricos con `Tipo = "-"` se clasifican por palabra en la descripción (`rendimiento`→INTERES, `retencion|impositiva|impuesto`→IMPUESTO, `fee|comision|arancel`→FEE, `acreencia`→INTERES) y **cualquier otra cosa cae a INTERES/FEE por signo**. Es el **único parser de movimientos que no emite un error de "descripción desconocida"** — Balanz, Balanz Internacional, PPI, Bull Market, IEB, Cocos e IOL sí lo hacen.
- **`asset_type` nunca se setea** [V] — declarado como follow-up (`backend/importing/parsers/inviu.py:44-45`).

---

### 9.5 Casos especiales, transversales

#### Bonos per-100 vs per-1

| Parser | Tratamiento |
|---|---|
| `bullmarket` (Movimientos) | **Único fix explícito**: `if abs(q*p − 100*monto) < abs(q*p − monto): p /= 100` (`backend/importing/parsers/bullmarket.py:686-690`) |
| `iol` | Lo esquiva: nunca usa la columna `Precio`, deriva `precio = |Monto| / cantidad`. El comentario cita que `cantidad × Precio` se inflaba **hasta 10.000×** (`backend/importing/parsers/iol.py:700-711`) |
| `cocos` | Lo esquiva igual: `precio = montoBruto / cantidad` (`backend/importing/parsers/cocos.py:544-552`) |
| `balanz_movimientos` | Usa el `Precio` del export; el **cap del 3%** de la comisión embebida existe justamente para no inventar una comisión gigante cuando "un bono per-100 se lee per-1" (`backend/importing/parsers/balanz_movimientos.py:484-492`) |
| `balanz`, `ieb`, `ppi`, `inviu`, `schwab` | **Sin tratamiento.** Toman el `Precio` del export tal cual |

[I] El repo tiene tres estrategias distintas para el mismo problema (derivar el precio, corregir por heurística, o no hacer nada) según el parser. Un bono per-100 en IEB/PPI/inviu/Balanz-Órdenes queda a merced de lo que mande el broker.

#### CEDEARs y su pata en dólares

- **Consolidación del sufijo D/C**: la SSoT es `backend/importing/tickers_cd.py`. IOL la llama directo en el parser (`backend/importing/parsers/iol.py:197`); para el resto la aplica el normalizer vía `consolidate_cd` (`backend/importing/normalizer.py:451`), gateada por `asset_type ∈ {BOND, STOCK, CEDEAR}` (`tickers_cd.py:CD_ASSET_TYPES`).
- **`KNOWN_CD_TICKERS`** protege ~50 símbolos que terminan legítimamente en C/D (AMD, GOLD, INTC, YPFD, SID, SCHD, LAC…). El módulo documenta que **SPYD NO va en la lista** a propósito: en el mercado AR es la pata dólar del CEDEAR de SPY, y protegerla partiría el ledger FIFO en dos.
- **`asset_type = CEDEAR`**: sólo lo emiten `cocos` (por el prefijo "CEDEAR" del instrumento, `backend/importing/parsers/cocos.py:524-526`), `balanz_movimientos` y `balanz_resultados` (por la columna `Tipo de Instrumento`) y `balanz_internacional`. `iol`, `ieb`, `ppi`, `inviu`, `bullmarket` no lo emiten nunca → el CEDEAR queda sin hint y la valuación decide sola.
- **CEDEAR comprado con dólares**: el modelo tiene `NormalizedTx.cash_broker` para "la plata salió de la cuenta en dólares pero el activo vive consolidado" (`backend/importing/schema.py:225-229`). **Ningún parser lo setea** [V] — el ruteo lo resuelve `route_by_currency` en el pipeline.

#### FCI (fondos comunes)

| Parser | Cómo lo trata |
|---|---|
| `cocos` | `asset_type=FUND` con guard: si el ticker tiene dígitos es una ON suscrita con el tipo "FCI" → `BOND` (`backend/importing/parsers/cocos.py:527-541`) |
| `balanz_movimientos` | Dirección **por nombre** (Balanz invierte el signo ahí); pre-pass que saltea la fila espejo del sweep; **fix de moneda por escala del VCP** (`backend/importing/parsers/balanz_movimientos.py:349-357`, `:448-460`) |
| `balanz_internacional` | Precio `-1` → no exige precio, lo deriva el normalizer (`backend/importing/parsers/balanz_internacional.py:249-274`) |
| `iol` | `asset_type=FUND` y **el ticker NO se trunca** (`IOLDOLD ≠ IOLDOL`) para que matchee la foto (`backend/importing/parsers/iol.py:684-691`); detector de fantasmas por doble-booking (`backend/importing/parsers/iol.py:461-505`) |
| `ppi` | Usa el **nombre largo del fondo** como `activo` (`backend/importing/parsers/ppi.py:331-341`) |
| `bullmarket` | Sólo el CASH reconcilia; **la tenencia del FCI no se reconstruye** (la suscripción no trae unidades) (`backend/importing/parsers/bullmarket.py:33-37`) |
| `ieb` | Sólo flujo de caja por signo (`LS*`/`LR*`); declarado fuera de MVP (`backend/importing/parsers/ieb.py:39-40`, `:246-249`) |
| `balanz` (Órdenes) | `FCI*` → `FUND` por prefijo de ticker, pero la operación en sí se saltea |

#### Cauciones

**Patrón compartido**: no se cargan como activo (es manejo de caja), se acumula el **neto por moneda** y se emite **una fila sintética de INTERES al final**. Lo implementan cuatro parsers, con código separado:

| Parser | Dónde | Detalle |
|---|---|---|
| `bullmarket` CC | `backend/importing/parsers/bullmarket.py:333-345`, `:449-465` | especie `"VARIAS"`; sólo neto > 0 |
| `bullmarket` Mov | `backend/importing/parsers/bullmarket.py:626-636`, `:698-710` | códigos CCDO/VTCT/VTCC/CPCT + leyenda; **signo invertido** |
| `iol` | `backend/importing/parsers/iol.py:605-621`, `:770-787` | moneda **sólo** por `Tipo Cuenta`; sólo neto > 0 |
| `ppi` | `backend/importing/parsers/ppi.py:298-304`, `:379-385` | sólo neto > 0.001 |
| `cocos` | `backend/importing/parsers/cocos.py:130-135` | **NO netea**: emite RETIRO (apertura) / DEPOSITO (término-cierre) por par |
| `ieb` | `backend/importing/parsers/ieb.py:181-182`, `:226-229` | **NO netea**: `CCCD`→RETIRO, `CCTE`→DEPOSITO |
| `balanz_resultados` | código muerto | `Caución - Pase - Cheque` → INTERES |

Además, `schema.UNSUPPORTED_OP_HINTS` (`backend/importing/schema.py:167-168`) rechaza `CAUCION` con un mensaje de "cargalo a mano" — o sea, **el template genérico no acepta lo que 4 parsers específicos sí resuelven**.

#### Transferencias de títulos (entre brokers)

| Parser | Entrante | Saliente |
|---|---|---|
| `balanz_movimientos` | COMPRA a su costo + DEPOSITO compensatorio (cash netea 0) (`:430-446`) | — |
| `balanz_internacional` | Ídem; sin precio → COMPRA precio 0 (`:232-253`) | VENTA precio 0 `_corporate_close` |
| `ieb` | `DETR`: COMPRA + DEPOSITO compensatorio (`:362-390`) | `RETR`: VENTA `_transfer_out` (`:392-409`) |
| `ppi` | flaggeada, no soportada (`:290-296`) | `"Retiro de Títulos"` → VENTA `_transfer_out` (`:277-283`) |
| `schwab` | pata IN → COMPRA con `_cost_basis_pending` (`:249-277`) | pata OUT ignorada |
| `iol` | **skip con mensaje**: `IOL_TITLE_TRANSFER`, "se completa sola si subís el Resumen de Cuenta" (`backend/importing/parsers/iol.py:228-238`) | ídem |
| `binance_transaction` | cripto que entra → COMPRA precio 0 | cripto que sale → VENTA `_transfer_out` (`:363-370`) |

[I] Cuatro tratamientos distintos para el mismo evento: costo + depósito compensatorio (Balanz/IEB), cost-basis pendiente (Schwab), skip con mensaje (IOL), o precio 0 (Binance). El impacto en capital aportado y P&L difiere entre ellos.

#### Dólar MEP comprado vía bonos (conductos)

El bug que persiguen todos: si las dos patas se toman como trades reales, el bono queda como **posición fantasma** y el FIFO cruza costo en pesos con proceeds en dólares.

| Parser | Detección | Salida |
|---|---|---|
| `iol` | `_detect_iol_conduits`: base+D/C, misma cantidad, dirección opuesta, **mismo día**, pata dólar **partida** (mismo Boleto), guard de tasa 100–100.000 (`backend/importing/parsers/iol.py:266-382`) | **FX_ARS_USD/FX_USD_ARS** + el residual como FEE |
| `iol` | `_detect_iol_dolar_directo`: `Compra/Venta de Dólares`, 2 filas, guard 10–2000 (`backend/importing/parsers/iol.py:384-458`) | **FX** |
| `cocos` | `_detect_mep_conduits`: sólo bonos, misma cantidad, **≤5 días** (`backend/importing/parsers/cocos.py:303-353`) | **RETIRO (ARS) + DEPOSITO (USD)** |
| `cocos` | `"registracion"` / `"esp app"` en el tipo (`backend/importing/parsers/cocos.py:120-129`) | RETIRO / DEPOSITO |
| `bullmarket` Mov | `VTU$`/`CPU$` apareadas con su pata pesos por `(especie, |qty|)` (`backend/importing/parsers/bullmarket.py:558-599`) | RETIRO / DEPOSITO |
| `balanz` (Órdenes) | `"dolar bolsa"` (`backend/importing/parsers/balanz.py:96-99`) | **skip completo** |
| `ppi` | `COMPRA/VENTA SPOT` (`backend/importing/parsers/ppi.py:310-322`) | **flaggeado y descartado** |
| `ieb`, `inviu`, `schwab`, `balanz_movimientos`, `balanz_internacional` | sin detector | — |

⚠️ **Inconsistencia de fondo** [V]: IOL emite **FX** (no infla capital aportado); Cocos y Bull Market emiten **RETIRO + DEPOSITO** (dos flujos de caja que **sí** entran al capital aportado si el motor los cuenta así). El comentario de IOL lo dice explícito — "sin inflar 'capital aportado' (un DEPOSITO/RETIRO sí lo inflaría)" (`backend/importing/parsers/iol.py:298-300`) — pero Cocos y Bull Market siguen usando el patrón que IOL descartó por esa razón.

#### Cripto

- Tres parsers de Binance, uno apagado.
- Ningún parser setea `asset_type = CRYPTO` [V]; lo infiere el normalizer por símbolo.
- `schwab._KNOWN_ETF_TICKERS` existe justamente para pisar esa inferencia (ETH de Grayscale ≠ ETH cripto).
- Cripto que entra sin costo conocido (regalo, airdrop, convert) → **COMPRA a precio 0** (`backend/importing/parsers/binance_transaction.py:357-362`); el comentario admite que "el P&L de esas patas es un follow-up".

---

### 9.6 Duplicación entre parsers

| # | Qué está duplicado | Dónde | Nota |
|---|---|---|---|
| D-1 | **`_norm_header`** (lowercase + deacentuar) | 8 implementaciones distintas: `backend/importing/parsers/cocos.py:157`, `backend/importing/parsers/balanz.py:40`, `backend/importing/parsers/balanz_movimientos.py:39`, `backend/importing/parsers/balanz_resultados.py:41`, `backend/importing/parsers/bullmarket.py:147`, `backend/importing/parsers/ieb.py:184`, `backend/importing/parsers/ppi.py:64`, `backend/importing/parsers/iol.py:112`, más `inviu._norm` (`backend/importing/parsers/inviu.py:56`), `schwab._norm_header` (`backend/importing/parsers/schwab.py:132`), `binance_futures._norm_header` (`backend/importing/parsers/binance_futures.py:37`), `binance_transaction._norm_header` (`backend/importing/parsers/binance_transaction.py:67`). Difieren en si sacan espacios, puntos o ambos | El caso más grave de copy-paste del módulo |
| D-2 | **`_num` / parseo de números** | `backend/importing/parsers/balanz.py:153`, `backend/importing/parsers/balanz_movimientos.py:90`, `backend/importing/parsers/balanz_resultados.py:104`, `backend/importing/parsers/ppi.py:92`, `backend/importing/parsers/inviu.py:84`, `backend/importing/parsers/iol.py:127`, `backend/importing/parsers/bullmarket.py:156`, `backend/importing/parsers/ieb.py:199`, `backend/importing/parsers/cocos.py:189` (AR estricto). **Todos con reglas ligeramente distintas** para la ambigüedad coma/punto | `iol._num` se autodescribe como "espejo simplificado de `normalizer.parse_number`" (`backend/importing/parsers/iol.py:129-130`) |
| D-3 | **`_resolve_columns`** (alias → header real) | Idéntico en `backend/importing/parsers/balanz.py:135-150`, `backend/importing/parsers/balanz_movimientos.py:106-121`, `backend/importing/parsers/balanz_resultados.py:122-137`; variante sin `used` en `backend/importing/parsers/ppi.py:127-137` e `backend/importing/parsers/inviu.py:122-135` | 5 copias |
| D-4 | **`_norm_ccy` / `_norm_currency`** (Pesos→ARS, Dólares→USD) | `backend/importing/parsers/balanz.py:77-86`, `backend/importing/parsers/balanz_movimientos.py:67-75`, `backend/importing/parsers/balanz_resultados.py:79-87` — **byte a byte iguales salvo el nombre** | `balanz_internacional` sí lo importa en vez de copiarlo (`backend/importing/parsers/balanz_internacional.py:38-41`) |
| D-5 | **`_asset_type` por `Tipo de Instrumento`** | `backend/importing/parsers/balanz_movimientos.py:78-88` y `balanz_resultados._asset_type_from_clase` (`:89-101`) idénticos; `balanz_internacional._asset_type_intl` (`:45-60`) es una copia **con dos ramas más** (`treasur`/`treasury`) | Un cambio en uno no llega a los otros dos |
| D-6 | **`_classify_desc`** de Balanz | `backend/importing/parsers/balanz_movimientos.py:129-181` vs `backend/importing/parsers/balanz_internacional.py:73-110` — misma estructura, **copiada y editada** (el internacional agrega `reverse split`, `tax withholding`, `liquidacion de transferencia`) | El internacional **importa** `_norm_header`, `_norm_ccy`, `_num`, `_resolve_columns`, `_REQUIRED`, `_is_tax` pero **copió** `_classify_desc` y `_asset_type` |
| D-7 | **Cuerpo del loop de Balanz** | `backend/importing/parsers/balanz_movimientos.py:378-580` vs `backend/importing/parsers/balanz_internacional.py:179-350`: las ramas `corporate`, `transfer`, `deposito`, `retiro`, `fee`, `renta` (incl. el dedup `_amort_closed`), `manual` son **prácticamente idénticas** | ~170 líneas duplicadas |
| D-8 | **`_fix_date` YY→YYYY** | `backend/importing/parsers/binance.py:58-70`, `backend/importing/parsers/binance_futures.py:61-71`, `backend/importing/parsers/binance_transaction.py:83-94` — las tres idénticas | |
| D-9 | **Lógica de cauciones (neto por moneda → INTERES)** | `bullmarket.py` ×2, `iol.py`, `ppi.py` — mismo algoritmo, cuatro implementaciones | Ver §9.5 |
| D-10 | **Quote assets de Binance** | `binance._QUOTE_ASSETS` (`:38-49`) vs `binance_transaction._STABLE_QUOTES` + `_CRYPTO_QUOTES` (`:43-54`) — mismas monedas, dos estructuras | |
| D-11 | **`_days_between`** | `backend/importing/parsers/cocos.py:294-300` e `backend/importing/parsers/iol.py:246-252` idénticos | |
| D-12 | **Detección de conductos MEP** | `cocos._detect_mep_conduits`, `iol._detect_iol_conduits`, `bullmarket` pass 1b — mismo problema, tres algoritmos y **dos salidas distintas** (FX vs RETIRO/DEPOSITO) | Ver §9.5 |

Contraejemplo positivo [V]: `tickers_cd.py` nació **de-duplicando** el algoritmo D/C que vivía en `iol.py`, y el propio docstring del módulo explica por qué (`backend/importing/tickers_cd.py:26-30`): "un fix aplicado a una sola se perdía en silencio". Ese mismo razonamiento aplica sin cambios a D-1..D-7.

---

### 9.7 Parsers incompletos, apagados o abandonados

| Parser | Estado | Evidencia |
|---|---|---|
| `binance_futures_trade_history` | **APAGADO e inalcanzable.** `is_supported=False` "TEMP hasta estabilizar futures" | `backend/importing/parsers/binance_futures.py:77-79`; excluido de autodetect (`backend/importing/parsers/registry.py:72`), del wizard (`backend/importing/pipeline.py:1324-1327`) y del pipeline explícito (`backend/importing/pipeline.py:481-482`) |
| `balanz_resultados` | **BLOQUEADO por decisión de producto.** `parse()` siempre falla; **~155 líneas muertas** (211-364) | `backend/importing/parsers/balanz_resultados.py:194-209` |
| `balanz` (Órdenes) | **Funcional pero degradado.** No trae comisiones ni cash (depósitos/retiros); se saltea todo menos compra/venta de títulos. Es el mismo defecto por el que se bloqueó Resultados, sin bloquear | `backend/importing/parsers/balanz.py:14-22`, `:266` |
| `ppi` — conducto SPOT | **Incompleto declarado.** `COMPRA/VENTA SPOT` se flaggea y descarta | `backend/importing/parsers/ppi.py:310-322`, docstring `:32-34` |
| `ieb` — DIV/RTA doble pata | **ABIERTO declarado** en el docstring ("necesita el export real + docs") | `backend/importing/parsers/ieb.py:40-43` |
| `ieb` — FCI | **Fuera de MVP declarado**: sólo caja, no cuotaparte | `backend/importing/parsers/ieb.py:38-40` |
| `bullmarket` — FCI | **Follow-up declarado**: la suscripción no trae unidades → la tenencia no se reconstruye | `backend/importing/parsers/bullmarket.py:33-37` |
| `inviu` / `ppi` / `ieb` / `bullmarket` | `asset_type` **nunca** se setea → la clase de activo depende de la inferencia downstream | `backend/importing/parsers/inviu.py:44-45`, `backend/importing/parsers/ppi.py:53`, `backend/importing/parsers/ieb.py:445` |
| `binance.py` docstring | **Desactualizado**: declara el "Transaction History" como NO soportado, cuando `binance_transaction.py` existe y está registrado | `backend/importing/parsers/binance.py:20-25` vs `backend/importing/parsers/registry.py:26` |
| `binance_futures.py` docstring | **Contradice al código**: promete que las aperturas puras emiten `monto=−Σfees`; el código las descarta | `backend/importing/parsers/binance_futures.py:19-20` vs `:157-158` |
| `cocos._OP_SKIP` | **Variable muerta** (`set()` vacío, sin referencias) | `backend/importing/parsers/cocos.py:84` |
| `ppi` rama `"manual"` | **Rama muerta**: `_classify` nunca devuelve `"manual"` | `backend/importing/parsers/ppi.py:370` vs `:143-176` |
| `FORMAT_BASE_CURRENCY['ibkr']` | **Entrada huérfana**: no existe ningún parser con `format_id='ibkr'` | `backend/importing/pipeline.py:436` vs `backend/importing/parsers/registry.py:22-54` |

---

### 9.8 Hallazgos

| ID | Sev. | Hallazgo | Evidencia |
|---|---|---|---|
| **H-1** | 🔴 | **Ningún parser llena `tc`**, y ninguno llena `monto_usd` en filas de COMPRA. `backend/importing/normalizer.py:564-568` sólo setea `tc_compra` si viene `tc` o si hay `monto_usd` en un BUY en pesos. Conclusión: **ninguna compra importada tiene `tc_compra`** → la vista "costo al dólar de la compra" no recibe dato de ningún import de broker | Verificado con `grep -n '"tc":'` sobre los 17 archivos: todas las ocurrencias son `"tc": ""`. `monto_usd` no vacío sólo en filas FX (`backend/importing/parsers/balanz_movimientos.py:331`, `backend/importing/parsers/iol.py:649`) |
| **H-2** | 🔴 | **Los conductos MEP producen resultados contables distintos según el broker**: IOL emite FX (neutral para capital aportado), Cocos y Bull Market emiten RETIRO+DEPOSITO. El propio comentario de IOL dice que RETIRO/DEPOSITO **inflaría** el capital aportado | `backend/importing/parsers/iol.py:298-300` vs `backend/importing/parsers/cocos.py:120-129` y `backend/importing/parsers/bullmarket.py:632-645` |
| **H-3** | 🟠 | **`bullmarket._parse_movimientos` hardcodea `moneda="ARS"`** en todas las filas. Un movimiento en dólares de ese layout entra como pesos | `backend/importing/parsers/bullmarket.py:670`, `:692`, `:696`, `:700-702` |
| **H-4** | 🟠 | **IEB emite dos `RawRow` con el mismo `row_index`** en la rama DETR. En `backend/importing/pipeline.py:721` (`raw_id_by_index[raw.row_index] = cur.lastrowid`) el segundo pisa al primero, así que **las dos tx normalizadas quedan linkeadas a la MISMA `raw_row_id`**, y los errores de `errors_by_row` se aplican a ambas | `backend/importing/parsers/ieb.py:371` y `:379`; `backend/importing/pipeline.py:711-721`, `:757` |
| **H-5** | 🟠 | **`inviu` deriva la comisión sin ningún cap** (`\|Neto\|−\|Bruto\|`), mientras Balanz Movimientos usa el mismo truco **con un guard del 3%** puesto justamente para el caso "bono per-100 leído per-1" | `backend/importing/parsers/inviu.py:252-257` vs `backend/importing/parsers/balanz_movimientos.py:484-492` |
| **H-6** | 🟠 | **`inviu` es el único parser de movimientos sin fallback de "descripción desconocida"**: los genéricos no reconocidos caen a INTERES/FEE por signo, en silencio. Todos los demás emiten un `*_DESC_DESCONOCIDA` / `*_OP_UNKNOWN` que el Import Guardian puede cazar | `backend/importing/parsers/inviu.py:288-290` vs `backend/importing/parsers/balanz_movimientos.py:575-580`, `backend/importing/parsers/ppi.py:374-378`, `backend/importing/parsers/ieb.py:409-413`, `backend/importing/parsers/cocos.py:468-474`, `backend/importing/parsers/iol.py:663-668`, `backend/importing/parsers/bullmarket.py:373-377` |
| **H-7** | 🟠 | **La moneda de IOL nunca se validó contra datos reales.** El docstring lo declara: los ejemplos tenían `Tipo Cuenta` aplastado a "Cuenta Anonimizada". El default es ARS, y `_CUENTA_USD_HINTS` incluye tokens amplios (`"cable"`, `"mep"`, `"ccl"`, `"exterior"`) que podrían matchear una etiqueta ARS | `backend/importing/parsers/iol.py:41-47`, `:97-98`, `:672-681` |
| **H-8** | 🟡 | **`binance.py` no descuenta de la tenencia el fee pagado en BNB** (sólo lo anota), mientras `binance_transaction.py` sí lo emite como una VENTA `_transfer_out` para que el saldo del coin reconcilie. Dos parsers del mismo broker con contabilidad distinta | `backend/importing/parsers/binance.py:186-190` vs `backend/importing/parsers/binance_transaction.py:213-219`, `:272-280` |
| **H-9** | 🟡 | **`balanz` (Órdenes) sigue habilitado con el defecto que hizo bloquear `balanz_resultados`**: no trae depósitos/retiros → capital aportado incompleto. Además no trae comisiones | `backend/importing/parsers/balanz.py:14-22`, `:266` vs `backend/importing/parsers/balanz_resultados.py:194-201` |
| **H-10** | 🟡 | **`balanz_internacional` no tiene el pre-pass de `Operación de Cambio`** que el local sí tiene. Una conversión en la cuenta exterior caería como descripción desconocida | `backend/importing/parsers/balanz_internacional.py:73-110` (sin rama) vs `backend/importing/parsers/balanz_movimientos.py:266-311` |
| **H-11** | 🟡 | **Umbrales de detección laxos sin desempate**: `cocos` ≥3/4, `iol` ≥3/5, `schwab` ≥3/4, `ieb` ≥4/6. El orden de `_PARSERS` es la única política de desempate y vive como comentario | `backend/importing/parsers/registry.py:22-54`, `:68-74` |
| **H-12** | 🟡 | **`binance_futures` agrupa filas sin Order ID por `id(raw)`** — la dirección de memoria del dict como clave | `backend/importing/parsers/binance_futures.py:132` |
| **H-13** | 🟡 | **`schema.UNSUPPORTED_OP_HINTS` rechaza `CAUCION`, `SPLIT`, `CONVERSION`** desde el template genérico, pero 4-5 parsers específicos sí los resuelven (cauciones en BM/IOL/PPI/Cocos/IEB; split en Schwab; conversiones en IOL/Balanz). La capacidad del sistema depende del archivo que subas | `backend/importing/schema.py:158-177` |
| **H-14** | 🟡 | **`FORMAT_BASE_CURRENCY` tiene una entrada `'ibkr'` sin parser** que la use | `backend/importing/pipeline.py:436` |
| **H-15** | 🟢 | **Docstrings desactualizados o contradictorios** con el código: `backend/importing/parsers/binance.py:20-25` (declara Transaction History no soportado), `backend/importing/parsers/binance_futures.py:19-20` (aperturas puras) | Ver §9.7 |
| **H-16** | 🟢 | **~155 líneas de código muerto** en `balanz_resultados.py` (211-364), más `cocos._OP_SKIP` y la rama `"manual"` de PPI | `backend/importing/parsers/balanz_resultados.py:209`, `backend/importing/parsers/cocos.py:84`, `backend/importing/parsers/ppi.py:370` |
| **H-17** | 🟢 | **El nombre del broker lo fija el parser, no el usuario.** `broker_hint` sólo etiqueta el batch; las filas conservan el string hardcodeado. Dos cuentas del mismo broker se mezclan en un solo broker | `backend/importing/pipeline.py:678-685`, `:518-529`; strings en cada parser |

---

### 9.9 Qué NO encontré

- **Ningún parser usa `file_name` para decidir formato** — se pasa por la firma pero no se lee. Confirmado en los 15 `parse()`.
- **Ningún parser setea `NormalizedTx.cash_broker`** (el campo del CEDEAR pagado con dólares del `backend/importing/schema.py:225-229`).
- **Ningún parser emite `asset_type = CRYPTO` ni `FIAT`**.
- **No hay parser de IBKR** pese a la entrada en `FORMAT_BASE_CURRENCY`.
- **No hay test de "dos parsers matchean el mismo archivo"** — busqué en `backend/tests/`; hay tests de que PPI no roba a Balanz/BM (`backend/tests/test_ppi.py:62-68`) y de que Balanz Internacional no autodetecta (`backend/tests/test_balanz_internacional.py:144-146`), pero no una property test general de exclusividad mutua entre los 14 `can_handle`.
- **No hay versionado de formato por parser** — nada registra "este archivo es la versión 2026-01 del export de Balanz". Los docstrings lo mencionan como limitación (`backend/importing/parsers/balanz.py:28-29`) pero no hay mecanismo.
