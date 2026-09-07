## Servicios externos y APIs de terceros

Inventario completo de todo lo que Rendi le pide a un tercero. Commit auditado: `b74f450f` (origin/main, 2026-09-05).

**Cómo leerlo**: `[V]` = verificado leyendo el código (con archivo:línea); `[I]` = inferencia mía (digo de qué me agarré).

Dos aclaraciones de método:

- La base `backend/trading.db` que viene en el repo es de una rama vieja: **no tiene** la tabla `user_broker_credentials` (verificado con `sqlite3 .tables`), aunque el código la crea en `backend/main.py:733`. Toda la evidencia de este informe sale del código, no de la base.
- No leí ningún `.env`. Cuando nombro una variable, la saqué de un `os.getenv` / `os.environ` / `import.meta.env` del código.

---

### Mapa rápido: los 4 clientes HTTP que conviven

`[V]` No hay UN cliente HTTP, hay cuatro, y la elección parece histórica más que de diseño:

| Cliente | Quién lo usa | Ejemplo |
|---|---|---|
| `requests` | dolarapi, argentinadatos (dólar/inflación/UVA/CER), data912, Google News RSS, Investing RSS | `backend/main.py:36` (`import requests`), `backend/main.py:4608` |
| `httpx` | Resend, MercadoPago, Rebill, Wallbit, IOL | `backend/wallbit.py:20`, `backend/iol_api.py:30`, `backend/billing/rebill.py:27` |
| `urllib.request` (stdlib) | FCI/CAFCI (`pricing/fci.py`), tasas de plazo fijo, probes admin | `backend/pricing/fci.py:28`, `backend/main.py:9346` |
| SDKs | `yfinance` (Yahoo), `anthropic`, `pywebpush`, `boto3` | `backend/main.py:35`, `backend/ai/llm.py:114`, `backend/main.py:34122`, `backend/scripts/backup_db.py:153` |

`[V]` `httpx` está declarado en `backend/requirements.txt` con un comentario de 12 líneas que cuenta que **no estaba declarado** y funcionaba de rebote porque lo arrastraba `anthropic`. Hoy está: `httpx>=0.27,<1.0`.

---

## Datos de mercado

### yfinance (Yahoo Finance) — no oficial

- **Para qué se usa** (negocio): es **la** fuente de precios de la app. Precios live de acciones US, CEDEARs `.BA`, cripto (`BTC-USD`), ETFs y benchmarks (SPY/`^MERV`/GLD/SHV); series históricas para las curvas; fundamentales (P/E, EPS, market cap, beta, sector), earnings, ratings de analistas y perfil de empresa para "Calidad de cartera" y para las tools del Coach IA; y el buscador de tickers por nombre.
- **Endpoints concretos**: no hay URL propia — es la librería. Los puntos de salida:
  - `backend/main.py:35` — `import yfinance as yf`
  - `backend/main.py:7746` — `yf.download(tickers_str, period="1mo", ...)` dentro de `GET /api/prices` (`backend/main.py:7606`)
  - `backend/main.py:7964` — `yf.download(...)` en `GET /api/prices/prev-close` (`backend/main.py:7866`)
  - `backend/main.py:8096` — `yf.Ticker(yf_sym)` en `GET /api/prices/history` (`backend/main.py:8050`)
  - `backend/main.py:5316` y `backend/main.py:5330` — `_yf_history()` para benchmarks
  - `backend/main.py:21346`, `:21493`, `:21541`, `:21801`, `:21876`, `:21946` — fetchers de fundamentals / scorecard / earnings / analysts / profile / financials
  - `backend/main.py:8671` — `yf.Ticker(ba_symbol).splits` (detección de splits)
  - `search_tickers` usa `_yf.Search(query, max_results=12)` (`backend/main.py`, dentro de `GET /api/tickers/search`)
  - `backend/snapshots_job.py:476` — `yf.download(...)` del cron diario de snapshots
  - `backend/home/market.py:294` y `:334` — heatmaps / índices / watchlist (batch + retry uno-a-uno)
  - `backend/price_history.py:92` — `yf.Ticker(symbol).history(start=..., interval="1d")` para el backfill de series
- **Autenticación**: ninguna. Es scraping legal-gris de la API pública de Yahoo. No hay env var de credencial.
- **Manejo de fallas**:
  - Timeout: `yf.download` **no lleva timeout explícito** en ninguno de sus call sites `[V]`. El único timeout es el del wrapper de fundamentales: `YF_FETCH_TIMEOUT_SECONDS = 10` (`backend/main.py:21017`).
  - Retry: en el cron de snapshots hay una segunda pasada sobre los símbolos que quedaron en `None` (`backend/snapshots_job.py:688-693`). En `home/market.py:325-334` hay retry uno-a-uno con `yf.Ticker.history` cuando el batch falla parcialmente.
  - Fallback en cascada, y es sofisticado:
    1. Para `.BA` (CEDEARs y acciones AR): **data912 pisa a yfinance** (`backend/snapshots_job.py:520-526`). El motivo está documentado: yfinance devuelve ruedas `.BA` con volumen pero OHLC en `NaN` (`backend/main.py:7257` y siguientes, comentario de `_fetch_data912_equities`).
    2. Para bonos AR: `_resolve_ar_bond_price` (data912, per-1) pisa a yfinance (`backend/snapshots_job.py:506-510`).
    3. Si sigue sin precio: **último precio conocido** desde la tabla `asset_last_price` (`apply_last_known_prices`, `backend/snapshots_job.py:605`). Explícitamente reemplaza el viejo fallback a cost basis, "sin precio hoy → la posición queda al último valor real visto (no a lo que se pagó)".
    4. Para fundamentales: cache stale de hasta 7 días (`YF_CACHE_STALE_FALLBACK_SECONDS`, `backend/main.py:21035`); si no hay nada, `{available: False, reason: 'fetch_failed'}`.
  - Hay un remedio específico para el TzCache corrupto de yfinance: `_setup_yfinance_cache()` (`backend/main.py:41-73`) lo apunta a `/tmp/yf-cache` (override con `YF_TZ_CACHE_LOCATION`) y `_yf_history` reapunta el caché y reintenta una vez cuando la respuesta viene vacía (`backend/main.py:5301-5335`). El comentario dice que el backend local sirvió `sp500: {}` durante días por un `disk I/O error` de ese SQLite.
- **Qué ve el usuario si se cae**: en el corto plazo, **casi nada**, y ahí está el riesgo. Las posiciones quedan al último precio conocido, así que la cartera muestra un número plausible y silencioso. La señal existe solo en los logs: `backend/snapshots_job.py:546-552` loguea "N/M símbolos sin dato de yfinance — BYMA rescató K", y `backend/main.py:5269-5270` loguea en ERROR cuando el S&P vuelve vacío. En el cron diario sí hay una defensa dura: si la cobertura ponderada por costo cae mucho, **no se persiste el snapshot** antes que escribir un total subvaluado (`backend/snapshots_job.py:700-710`).
- **Cache**:
  | Capa | Dónde | TTL |
  |---|---|---|
  | Precios per-símbolo (in-memory, con lock) | `backend/main.py:7399-7400` (`_PRICE_CACHE`) | 60 s |
  | Quotes del watchlist/home | `backend/home/market.py:263-264` (`_QUOTE_CACHE`) | 60 s |
  | Índices strip | `backend/home/market.py:375` | 15 min |
  | Heatmaps SP500/Merval | `backend/home/market.py:448,451` | 30 min |
  | Heatmap/movers cripto | `backend/home/market.py:454,464` | 15 min |
  | Benchmarks (mensuales + diarias) | `backend/main.py:5202-5204` (`BENCH_TTL`) | 1 h, con stale-while-revalidate |
  | Fundamentales (tabla `yfinance_cache`, persistente) | `backend/main.py:21020-21033` | profile/analysts 24 h · fundamentals/scorecard 12 h · earnings 6 h · financials 24 h · default 6 h |
  | Búsqueda de símbolos | `backend/main.py` (`_SYMSEARCH_TTL`) | 24 h |
  | Últimos precios (persistente) | tabla `asset_last_price` + buffer in-memory que baja 1×/min (`backend/main.py:7503-7507`) | sin vencimiento |
- **Criticidad**: **la más alta de todas**. Es la única fuente de precios de todo lo que no sea bono AR / CEDEAR BYMA / FCI. Sin ella: se congela la valuación (queda en último precio), mueren fundamentales frescos, benchmarks, heatmaps y la mitad de las tools del Coach IA.
- **Estado**: **viva, en el camino crítico, y sin contrato**. `requirements.txt` la pide con `yfinance>=1.2.0` (sin techo).
- ⚠️ **Observación**: `MAX_SYMBOLS = 60` (`backend/main.py:7139`) es el techo por request de `/api/prices`. Una cartera de más de 60 símbolos se trunca en silencio en ese endpoint `[V]` (la lista se corta con `sym_list[:MAX_SYMBOLS]`).

### data912.com — no oficial, sin auth

- **Para qué se usa**: precios live de BYMA. Dos usos distintos: (a) bonos y ONs argentinos (soberanos, BOPREAL, CER, corporativos), que son la única fuente confiable de per-100 vs per-1; (b) **CEDEARs y acciones AR** — acá pisa a yfinance porque yfinance da barras `.BA` en `NaN`.
- **Endpoints concretos**:
  - `https://data912.com/live/arg_bonds` y `https://data912.com/live/arg_corp` — `backend/main.py:7229` (dentro de `_fetch_data912_bonds`)
  - `https://data912.com/live/arg_cedears` y `https://data912.com/live/arg_stocks` — `backend/main.py:7284` (dentro de `_fetch_data912_equities`)
- **Autenticación**: ninguna. Sin env var.
- **Manejo de fallas**: `timeout=8`. Sin retry. Fallback: devuelve el **cache anterior** (aunque esté stale) o `{}` (`backend/main.py:7241-7242` y `:7296-7297`, `except Exception: return cached or {}`). El cache solo se pisa si hubo data nueva (`if result:`), así que una respuesta vacía no borra lo bueno.
- **Qué ve el usuario si se cae**: los bonos AR y los CEDEARs caen a yfinance. Para bonos eso significa **precios per-100 sin dividir**, o sea posiciones infladas ~100× — el comentario en `backend/main.py:7204-7208` lo dice explícito para los tickers que se agregaron a `AR_BONDS_DATA912` justo porque "aparecían INFLADOS". Para CEDEARs significa volver a la barra en NaN → precio de dos ruedas atrás sin marcarlo.
- **Cache**: `_data912_cache` / `_data912_eq_cache`, TTL `DATA912_TTL = 300` (5 min) — `backend/main.py:7211-7212`, `:7258`.
- **Criticidad**: **alta y subestimada**. El universo cubierto es una **lista hardcodeada** de 30 tickers (`AR_BONDS_DATA912`, `backend/main.py:7194-7209`). Un bono que el usuario tenga y no esté en esa lista no entra por acá.
- **Estado**: viva y en el camino crítico.

### ArgentinaDatos (api.argentinadatos.com) — comunitaria, sin auth

Es el proveedor que más funciones distintas cubre. Lo separo por serie porque las criticidades son muy diferentes.

- **Para qué se usa**:
  1. **Backfill histórico del blue** (~5 años) — `backend/main.py:4722`, `/v1/cotizaciones/dolares/blue`
  2. **Backfill histórico del MEP** (~7 años) — `backend/main.py:4811`, `/v1/cotizaciones/dolares/bolsa`
  3. **Inflación mensual INDEC** — `backend/main.py:5279`, `/v1/finanzas/indices/inflacion`
  4. **UVA mensual** (proxy del PF UVA en el simulador de benchmarks) — `backend/main.py:5491`, `/v1/finanzas/indices/uva`
  5. **CER diario** (ajusta capital de TX26/TX28/TZX*) — `backend/main.py:5580`, `/v1/finanzas/indices/cer`
  6. **Tasas de plazo fijo por banco** — `backend/main.py:9353`, `/v1/finanzas/tasas/plazoFijo` (endpoint `GET /api/pf/banks`, `backend/main.py:9341`)
  7. **Valor de cuotaparte de FCI** (5 categorías) — `backend/pricing/fci.py:35`, `/v1/finanzas/fci/{categoria}/ultimo`
  8. Blue mensual para el benchmark — `_fetch_dolar_blue_monthly` (`backend/main.py:5378`)
- **Autenticación**: ninguna en ningún endpoint. Los únicos headers son User-Agent (`"Mozilla/5.0 (Rendi FCI pricing)"` en `backend/pricing/fci.py:37`, `"Mozilla/5.0 (Rendi)"` en `backend/main.py:9352`).
- **Manejo de fallas**:
  - Timeouts: 8 s (inflación, UVA), 10 s (blue, bolsa, CER), 12 s (plazo fijo y FCI vía `_http_json(timeout=20)` por default pero llamado sin override → 20 s en `backend/pricing/fci.py:96`).
  - Retry: ninguno en ninguno.
  - Fallback: los de índices devuelven `{}` en cualquier excepción (`backend/main.py:5288-5289`, `:5504-5505`, `:5589-5590`). El de plazo fijo devuelve el cache viejo o **HTTP 503 "No se pudieron obtener las tasas de plazo fijo"** si nunca hubo cache (`backend/main.py:9375-9378`) — es el único que el usuario ve como error explícito.
  - FCI: `refresh_prices` **no borra los precios viejos** si el fetch falla (`backend/pricing/fci.py:266-268`), y `_fetch_all_funds` solo levanta si **ninguna** de las 5 categorías respondió (`backend/pricing/fci.py:116-117`).
  - Los dos backfills FX corren en un thread daemon al startup y no rompen el boot (`backend/main.py:32097-32116`).
- **Qué ve el usuario si se cae**:
  - **Índices (inflación/CER/UVA)**: la app sigue andando; los cálculos ajustados por inflación y las curvas CER caen a lo cacheado en `bond_indices_daily` con flag `stale: true` para que el frontend avise (`backend/main.py:5565-5566`, comentario del diseño de cache).
  - **FCI**: sigue mostrando el último VCP, **con la fecha**. Está resuelto a conciencia: `get_prices_detail_for` devuelve `{price, as_of}` porque la fuente dejó de publicar tres semanas (21/07 → 13/08) y el precio viejo se mostraba como si fuera de hoy (`backend/pricing/fci.py:321-328`). Ese `as_of` viaja en `__meta` de `/api/prices` (`backend/main.py:7626-7627`).
  - **Plazo fijo**: 503 y el comparador/prefill de tasas no carga.
  - **Backfills FX**: si la tabla `fx_rates_daily` ya está poblada, no pasa nada (el backfill es one-shot: `if cnt > 0: return`).
- **Cache**:
  - FX diario e histórico → tabla persistente `fx_rates_daily` (backfill one-shot + upsert diario del cron)
  - Benchmarks (inflación, UVA, blue mensual) → `_bench_cache`, TTL 1 h (`backend/main.py:5204`)
  - CER → tabla `bond_indices_daily` + `_indices_fetched` con `INDICES_TTL = 4 * 3600` (`backend/main.py:5568-5569`)
  - Tasas PF → `_PF_BANKS_CACHE`, TTL 6 h (`backend/main.py:9337-9338`)
  - FCI → tabla `fci_prices`, refrescada 1×/día por cron a las 12:10 UTC (`backend/main.py:32566-32572`) + bootstrap al boot en thread (`_fci_bootstrap_async`, `backend/main.py:32506`)
- **Criticidad**: **alta pero degradable**. Es la única fuente de inflación, CER, UVA y FCI. La app no se cae; los números se congelan (y en FCI, con la fecha a la vista, que es lo correcto).
- **Estado**: **viva y en producción** para todo salvo el probe admin.
- ⚠️ El propio módulo lo dice: *"Las fuentes son comunitarias/no oficiales (sin SLA)"* (`backend/pricing/fci.py:19`).

### dolarapi.com — comunitaria, sin auth

- **Para qué se usa**: **las 4 cotizaciones live** que atraviesan toda la valuación: blue, MEP (`bolsa`), CCL (`contadoconliqui`) y cripto. De acá salen `_display_blue`, `_display_ccl`, `_current_ccl`, `_current_cedear_rate`, `_current_cripto_rate` — o sea, el dólar con el que se valúa la cartera entera.
- **Endpoints concretos**: `https://dolarapi.com/v1/dolares/{casa}` — `backend/main.py:4608`, con `casa ∈ {blue, bolsa, contadoconliqui, cripto}` (`backend/main.py:4852-4855`). Servido por `GET /api/dolar` (`backend/main.py:4978`) y `GET /api/public/dolar` (`backend/main.py:4983`), que comparten el mismo caché a propósito.
- **Autenticación**: ninguna.
- **Manejo de fallas**: `timeout=5` (el más corto de todo el backend). Sin retry. **Resiliencia per-casa**: si una casa puntual falla, se conserva el último valor conocido de *esa* casa en vez de devolverla en `null` (`backend/main.py:4860-4864`). El comentario explica por qué: un `/dolar` con `ccl=null` hacía que `pickFinancialRate('ccl')` del frontend cayera **silenciosamente** al MEP, y dos pantallas que fetchean en momentos distintos quedaban valuando a rates diferentes — reportado por un usuario. El caché solo se refresca si al menos una casa respondió (`if blue or mep or ccl or cripto:`).
- **Qué ve el usuario si se cae**: con caché caliente, nada (5 min de gracia). Con caché frío (post-restart de Railway + dolarapi caída) los consumidores caen a `_user_tc_blue(conn, uid)` — el `tc_blue` guardado en la config del usuario, que puede estar viejo. Ese es el modo de falla feo: **la cartera se valúa a un dólar stale sin que nada lo diga**.
- **Cache**: `_dolar_cache`, `DOLAR_TTL = 300` (5 min) — `backend/main.py:4602-4603`. In-memory, se pierde en cada deploy.
- **Criticidad**: **crítica**. Toda la valuación en USD de posiciones y cash ARS pasa por acá.
- **Estado**: viva, camino crítico.
- `[V]` Detalle de negocio que vale la pena registrar: desde el fix documentado en `backend/main.py:4614-4624`, la valuación usa el **punto medio** `(compra+venta)/2` y no la punta de venta, para coincidir con lo que muestran Cocos/IOL/Balanz. La excepción es el dólar cripto, que sigue en `venta` crudo porque el frontend lo lee así en ~8 lugares (`backend/main.py:4955-4960`).

### CAFCI (api.cafci.org.ar / api.pub.cafci.org.ar)

- **Para qué se usa**: **nada en producción.** Solo aparece en un probe de diagnóstico admin.
- **Endpoints concretos** (los tres, en el mismo handler `GET /api/admin/fci/probe`, `backend/main.py:19985`):
  - `https://api.argentinadatos.com/v1/finanzas/fci/mercadoDinero/ultimo` — `backend/main.py:20047`
  - `https://api.pub.cafci.org.ar/pb_get` — `backend/main.py:20051` (solo status, `read_body=False`)
  - `https://api.cafci.org.ar/fondo/851/clase/2427/ficha` — `backend/main.py:20055`
- **Autenticación**: ninguna. El endpoint que lo llama sí exige admin (`Depends(get_admin_user)`).
- **Manejo de fallas**: cada probe atrapa su propia excepción y devuelve `{ok: false, error}` con latencia en ms. Nunca rompe.
- **Cache**: ninguno (es un probe).
- **Criticidad**: **cero**. El comentario dice que `api.cafci.org.ar` está geo-bloqueado (403 desde IPs no-AR) y el probe existe justo para confirmarlo desde la IP de Railway (`backend/main.py:19993-19997`).
- **Estado**: **spike de decisión, ya resuelto**. Ganó ArgentinaDatos (es lo que usa `pricing/fci.py`). El probe quedó vivo como herramienta de diagnóstico admin.
- `[I]` Lo mismo vale para `GET /api/admin/pf/probe` (`backend/main.py:20098`): es la Fase 0 del feature de plazos fijos, que ya está implementado en `/api/pf/banks`. Me agarro de que el docstring dice "Fase 0 (Plazos Fijos) — Probe READ-ONLY" y el feature real ya existe 9000 líneas más arriba.

---

## Noticias

### Google News RSS

- **Para qué se usa**: alimenta "Novedades" / `/api/news/*` con noticias de mercado, macro AR y **por ticker de la cartera del usuario**. También es una tool del Coach IA (`get_recent_news_for_assets`, `backend/main.py:24758`; `get_market_news`, `:24774`).
- **Endpoints concretos**: `https://news.google.com/rss/search?` + querystring — `backend/main.py:6552`. Parámetros por idioma: `hl=es-419&gl=AR&ceid=AR:es-419` para español, `hl=en-US&gl=US&ceid=US:en` para inglés (`backend/main.py:6547-6550`).
- **Autenticación**: ninguna. User-Agent propio: `"Mozilla/5.0 (compatible; RendiBot/1.0; +https://rendi.finance/bot)"` (`backend/main.py:6557`).
- **Manejo de fallas**: `timeout=6`. El comentario explica la baja de 10→6 s como mitigación de DoS por "tool storm" del chat IA: `5 tickers × 3 tool loops × 10s = 150s → ×6s = 90s` (`backend/main.py:6551-6556`). Sin retry. Devuelve `[]` ante cualquier fallo (`backend/main.py:6562-6563`).
- **Qué ve el usuario si se cae**: **nada roto**. La tabla `news` acumula histórico, así que los endpoints siguen sirviendo lo que ya bajó. Además hay stale-while-revalidate: si hay data en DB, se devuelve al toque y el refresh va a un daemon thread (`_refresh_news_in_background`, `backend/main.py:6743`). Con cache frío hay un tope de espera: `max_wait_seconds=4` y el resto sigue en background (`backend/main.py:6940`, `:7022`).
- **Cache**: `_news_fetched_at` in-memory + la tabla `news` persistente. TTL: `NEWS_TICKER_TTL = 30 min`, `NEWS_MARKET_TTL = 60 min` (`backend/main.py:6150-6151`). Pool dedicado `_news_fetch_executor` (16 workers) + semáforo global de 16 in-flight (`backend/main.py:6797`, `:6805`). Prewarm al startup en thread (`backend/main.py:32145`).
- **Criticidad**: **baja**. Es una feature, no la valuación.
- **Estado**: viva.

### Investing.com RSS

- **Para qué se usa**: complemento de Google News con cobertura más profunda de acciones y macro, en español.
- **Endpoints concretos** (`INVESTING_FEEDS`, `backend/main.py:6189-6193`):
  - `https://es.investing.com/rss/news_25.rss` → categoría `market`
  - `https://es.investing.com/rss/news_285.rss` → categoría `macro`
- **Autenticación**: ninguna. Mismo User-Agent `RendiBot/1.0` (`backend/main.py:6630`).
- **Manejo de fallas**: `timeout=10`, sin retry, `[]` ante cualquier fallo (`backend/main.py:6634-6635`).
- **Cache**: el mismo mecanismo que Google News (`NEWS_MARKET_TTL`, 60 min).
- **Criticidad**: baja. El comentario dice que los feeds en inglés se retiraron en el clean pass de 2026-07 y quedaron solo estos dos.
- **Estado**: viva.
- `[V]` Nota de seguridad que está bien resuelta: el parser RSS usa `defusedxml` cuando está disponible, con fallback a `xml.etree`, contra XML bombs (`backend/main.py:6647-6653`). `defusedxml==0.7.1` está pinneado en `requirements.txt`.

---

## IA

### Anthropic (Claude)

- **Para qué se usa**: es el producto, no un accesorio. Tres superficies:
  1. **`POST /api/ai/analyze`** (`backend/main.py:25890`) — el botón "Analizar" de Dashboard/Insights/Operaciones/Reportes. Manda un *packet* de números **pre-calculados** de la pantalla y pide un JSON estructurado validado contra un modelo Pydantic (`AnalysisResult`).
  2. **`POST /api/ai/chat`** (`backend/main.py:28264`) — el Coach IA, con tool-use (26 tools declaradas: precios, operaciones, noticias, fundamentales, FX, y **`register_trade` / `undo_last_trade` / `register_group_op`**, que escriben en la cartera del usuario).
  3. Brief del asesor / Wrapped, por los mismos wrappers.
- **Endpoints concretos**: vía SDK oficial (`api.anthropic.com`, no hardcodeado). Puntos de salida:
  - `backend/ai/llm.py:242` — `client.messages.parse(...)` con `output_format=output_model`
  - `backend/main.py:28768` y `:28815` — `client.messages.stream(...)` (chat SSE, loop de tools + fallback forzado sin tools)
  - `backend/main.py:28894` y `:28960` — `client.messages.create(...)` (chat en modo JSON, mismo loop)
- **Modelos**: `claude-haiku-4-5` (default, Free/Plus/Pro) y `claude-sonnet-4-6` (solo el chat en *book mode* del Plan Asesor) — `backend/ai/llm.py:45-46`, `backend/main.py:28363`.
- **Autenticación**: `ANTHROPIC_API_KEY`. Dos clientes distintos: `backend/ai/llm.py:114` (sin timeout explícito) y `backend/main.py:20363` con `timeout=25.0`.
- **Manejo de fallas**:
  - **Timeout 25 s en el cliente del chat**, y el porqué está muy bien documentado (`backend/main.py:20370-20385`): el rewrite de Vercel a Railway corta a ~30 s y devuelve HTML, no JSON, así que el frontend no podía parsear `detail`. Bajaron de 60→25 s para fallar **antes** que Vercel y poder devolver un 503 con mensaje útil.
  - Retry: `llm.analyze` reintenta 1 vez si el modelo rompe el schema (`max_retries=1`, `backend/ai/llm.py:139`); loguea el raw output truncado a 1500 chars para diagnosticar.
  - Sin API key: `is_configured()` devuelve `False` y los endpoints tiran **503 "AI no configurada (falta ANTHROPIC_API_KEY)"** (`backend/main.py:25916`, `:26196`, `:28288`). El warning de key faltante se loguea **una sola vez** (`_client_init_attempted`, `backend/ai/llm.py:104-110`).
  - Excepción del LLM → **502 "AI procesamiento fallo: {tipo}"** (`backend/main.py:26055-26057`). `llm_result is None` → 503 "AI no disponible momentáneamente".
  - Truncamiento por `max_tokens` → warning en logs (`_warn_if_truncated`, `backend/main.py:27941`).
- **Qué ve el usuario si se cae**: el botón "Analizar" y el chat devuelven error; **el resto de la app funciona intacta**. No hay fallback templated (el docstring de `llm.py:24` lo menciona como opción del caller, pero los callers de `main.py` levantan HTTPException).
- **Cache y control de costo** — es donde está el trabajo fino:
  - **Prompt caching de Anthropic** con TTL extendido 1 h vía header beta `extended-cache-ttl-2025-04-11` en `/analyze` (`backend/ai/llm.py:248-253`); el chat usa `cache_control: {"type": "ephemeral"}` sin TTL (default 5 min).
  - **Cache de resultados propio** (`ai/cache.py`) keyed por (user, screen, packet): un cache hit **no consume cuota** (`backend/main.py:25902-25905`).
  - **Cuota por tier** (`ai/quota.py`) con `record_analysis` / `record_chat_cost` en centésimos de centavo.
  - **Rate limit propio**: 10 calls/60 s por uid en `/analyze` (`backend/main.py:25912`).
  - **Contabilidad de costo duplicada y con tarifas distintas**: `backend/ai/llm.py:50-53` usa `{haiku: 1/5, sonnet: 3/15}` con multiplicador de cache-write **2.0** (TTL 1 h); `backend/main.py:27923-27937` usa `_HAIKU_PRICE`/`_SONNET_PRICE` con cache_write **1.25**/3.75 (TTL 5 min). Los dos son coherentes con su propio TTL, pero son dos tablas de precios que hay que actualizar a mano por separado `[V]`.
- **Criticidad**: **alta para el valor percibido, cero para la integridad de los datos**. Si Anthropic se cae, Rendi sigue siendo un tracker correcto sin coach.
- **Estado**: viva, es el diferencial del producto.
- ⚠️ **Privacidad**: los *packets* que salen a Anthropic llevan la cartera del usuario (posiciones, montos, P&L, brokers). Verifiqué que **no** llevan email ni identidad: `grep -rn "email" backend/ai/builders/*.py` no devuelve nada `[V]`.

---

## Pagos

### Rebill (api.rebill.com) — procesador VIVO

- **Para qué se usa**: cobra las suscripciones Plus/Pro. Es el procesador actual.
- **Endpoints concretos**:
  - `POST https://api.rebill.com/v3/payment-links` — `backend/billing/rebill.py:174` (crear checkout con metadata `rendi_user_id`)
  - `GET https://api.rebill.com/v3/organizations/me` — `backend/billing/rebill.py:206` (`verify_api_key`, diagnóstico)
  - `GET https://api.rebill.com/v3/subscriptions/{id}` — `backend/billing/rebill.py:311`
  - `PATCH https://api.rebill.com/v3/subscriptions/{id}` con `{"status":"cancelled"}` — `backend/billing/rebill.py:325`
  - Webhook entrante: `POST /api/billing/rebill-webhook` — `backend/main.py:26809`
- **Autenticación**:
  - Salida: header `x-api-key` con `REBILL_API_KEY` (prefijo `sk_test_` = sandbox, `sk_live_` = prod).
  - Plan IDs: `REBILL_PLAN_ID_{PLAN}_{PERIOD}` — 4 variables (`REBILL_PLAN_ID_PLUS_MONTHLY`, `..._PLUS_ANNUAL`, `..._PRO_MONTHLY`, `..._PRO_ANNUAL`), `backend/billing/rebill.py:72`.
  - Webhook entrante: `REBILL_WEBHOOK_SECRET` (HMAC SHA-256, preferido) **o** `REBILL_WEBHOOK_TOKEN` (token en el query string `?token=`, fallback porque Rebill v3 no firma) — `backend/billing/rebill.py:45-65`.
- **Manejo de fallas**:
  - `timeout=15.0` en create/get/cancel, `10.0` en `verify_api_key`.
  - Sin retry, pero **con idempotency key**: `x-idempotency-key: rendi-{uid}-{plan}-{period}-{uuid8}` (`backend/billing/rebill.py:167`).
  - `create_payment_link` levanta `RuntimeError(f"Rebill {status}: {body}")` para no perder el body, y el endpoint devuelve **502 con el mensaje real truncado a 300 chars** al frontend (`backend/main.py:26567-26580`) — a propósito, para que se vea "REBILL_PLAN_ID_X no configurada".
  - `cancel_subscription` es **idempotente a propósito**: si falla, consulta el estado real antes de dar la mala noticia, porque un reintento sobre una sub ya cancelada devolvía 4xx → 502 y la persona quedaba trabada viendo "No pudimos cancelar" sobre algo ya cancelado (`backend/main.py:27347-27365`).
  - **Validación de config al startup**: `validate_config()` (`backend/billing/rebill.py:219`) detecta key ausente, webhook auth ausente en prod, plan IDs faltantes y **mismatch de ambiente** (key `sk_live_` con plan ID `test_pln_` → error crítico). Se corre en `_validate_rebill_config` (`backend/main.py:32119`) y solo loguea.
- **Qué ve el usuario si se cae**: no puede suscribirse ni cancelar (502 con detalle). Los usuarios ya pagos **no pierden acceso** — el tier vive en la DB de Rendi.
- **Cache**: ninguno (correcto para pagos).
- **Criticidad**: **alta para el negocio, cero para el producto**.
- **Estado**: **vivo y es el único procesador que cobra.**
- ✅ **Defensa que vale la pena destacar**: la URL de checkout que devuelve Rebill se valida contra un allowlist de hosts antes de mandársela al frontend, por si la respuesta viniera tampereada y apuntara a un phishing (`backend/main.py:26594-26603`): `app.rebill.com`, `checkout.rebill.com`, `pay.rebill.com`, `app.rebill.dev`, `checkout.rebill.dev`. Si no matchea → 502 `payment_url_invalid`.
- ⚠️ La columna donde se guarda el ID de Rebill **se llama `mp_subscription_id`** — se reusó el campo de MercadoPago para no migrar el schema (`backend/main.py:26584-26586`, comentario explícito). Es deuda de nombres que confunde a cualquiera que lea el schema.

### MercadoPago (api.mercadopago.com) — procesador MUERTO, código vivo

- **Para qué se usaba**: era el procesador antes de la migración a Rebill. `backend/main.py:26521-26523` lo dice literal: *"migramos de Mercado Pago a Rebill. MP queda muerto pero el código está en mercadopago.py por si hay que revertir"*.
- **Endpoints concretos** (todos siguen implementados):
  - `POST https://api.mercadopago.com/preapproval` — `backend/billing/mercadopago.py:144`
  - `PUT https://api.mercadopago.com/preapproval/{id}` — `backend/billing/mercadopago.py:163`
  - `GET https://api.mercadopago.com/preapproval/{id}` — `backend/billing/mercadopago.py:180`
  - Webhook entrante: `POST /api/billing/webhook` — `backend/main.py:27501` (**sigue registrado y abierto**)
- **Autenticación**: `MP_ACCESS_TOKEN` (Bearer). Webhook: `MP_WEBHOOK_SECRET` (HMAC SHA-256 sobre `id:{data_id};request-id:{req_id};ts:{ts};`, `backend/billing/mercadopago.py:230-236`). Otras vars: `MP_FRONTEND_BASE_URL`, `MP_BACK_URL_BASE`, `MP_ENV`, `MP_TEST_PAYER_EMAIL`.
- **Manejo de fallas**: `timeout=15.0`, sin retry, `raise_for_status()`.
- **Estado — esto es lo importante**:
  - `create_preapproval` **no lo llama nadie en producción** `[V]`: `/api/billing/subscribe` (`backend/main.py:26504`) usa Rebill.
  - `POST /api/billing/webhook` **sigue vivo y registrado**. Si `MP_WEBHOOK_SECRET` no está configurada y `is_likely_production()` da `True`, rechaza (`backend/billing/mercadopago.py:213-221`). Pero además hay un segundo gate en `main.py:27553-27560`: si la firma es inválida, **solo rechaza si el secret está configurado**.
  - `POST /api/billing/sync` (`backend/main.py:27420`) **le pregunta a MercadoPago** por el estado de la sub, pasándole el `mp_subscription_id`… **que hoy guarda un ID de Rebill**. El frontend ya no lo llama — `frontend/src/pages/BillingReturn.jsx:18` dice *"Pre-migración usábamos /api/billing/sync que pegaba a MP — eso quedó"* `[V]`. Pero el endpoint sigue expuesto a cualquier usuario autenticado.
  - 🔴 **`_sync_authorized_with_mp` es código muerto**: `backend/billing/subscriptions.py:556` la define y **solo la llaman los tests** (`backend/tests/test_billing_lifecycle.py:213,225,237`). `run_lifecycle_job` (`backend/billing/subscriptions.py:31`) inicializa `"synced_from_mp": 0` (`:38`) y **nunca la invoca**. Sin embargo el docstring del cron dice *"sync con MP para detectar webhooks perdidos"* (`backend/main.py:32079`). O sea: **la red de seguridad de webhooks perdidos no existe**, y el log diario dice `synced_from_mp: 0` como si hubiera corrido y no hubiera encontrado nada. `[V]`
- **Criticidad**: cero como servicio. Como superficie, es un webhook público de billing que sigue montado.

---

## Email y notificaciones

### Resend (api.resend.com)

- **Para qué se usa**: **todos** los emails transaccionales — verificación OTP de 6 dígitos al registrarse, reset de password, alertas de login, bienvenida Pro, recibos, pago fallido, cancelación, recordatorio de vencimiento, emails de trial, brief del asesor, avisos internos al admin (nuevo signup, cambio de plan, reporte del IOL Lab).
- **Endpoints concretos**: `POST https://api.resend.com/emails` — `backend/billing/emails.py:148-149`.
- **Autenticación**: `RESEND_API_KEY` (header `Authorization: Bearer`). Remitentes configurables: `EMAIL_FROM`, `EMAIL_FROM_NOREPLY`, `EMAIL_FROM_SUPPORT` (defaults `no_reply@rendi.finance` y `soporte@rendi.finance`, `backend/billing/emails.py:43-65`). Destino de avisos internos: `ADMIN_NOTIFY_EMAIL` (default `soporte@rendi.finance`, `backend/main.py:2920`).
- **Manejo de fallas**: `timeout=10.0`. **Sin retry, sin cola, sin dead-letter.** Cualquier error → `log.error` y `return False` (`backend/billing/emails.py:160-164`). El caller *asume que el evento no se notificó pero no falla*.
- **Qué ve el usuario si se cae**: **este es el peor modo de falla de toda la lista.** El registro exige verificar el email con un OTP; si Resend está caído, **el código nunca llega y el usuario no puede crear la cuenta**, sin reintento ni mensaje que lo explique. Lo mismo con reset de password. El envío se hace fuera de la transacción de DB, así que la cuenta queda creada esperando un código que no existe (`backend/main.py:3077`, `backend/billing/trial.py:408`).
- **Cache**: N/A. La idempotencia es por DB (`welcome_email_sent_at`, `last_receipt_sent_at`), no por el proveedor.
- **Criticidad**: **crítica para el onboarding**, media para el resto.
- **Estado**: viva. Sin proveedor configurado, `_send` loguea el mail a consola y devuelve `False` (modo dev, `backend/billing/emails.py:127-136`).
- ✅ **Guarda anti-spam bien hecha**: nunca envía bajo pytest ni a dominios reservados `.test/.example/.invalid/.localhost/.local` (`backend/billing/emails.py:76-88`, `:113-116`). El comentario cuenta el bug que la motivó: los tests de auth mandaban alertas de "nuevo usuario" REALES al inbox del fundador porque `main.py` hace `load_dotenv` del `.env` con la key real.

### Web Push (VAPID / pywebpush)

- **Para qué se usa**: notificaciones de alertas de precio a Chrome/Firefox/Edge desktop + Android, y iOS Safari ≥16.4 solo en modo PWA instalada.
- **Endpoints concretos**: no hay host fijo — `webpush()` pega al `endpoint` que le dio el browser al suscribirse (FCM de Google para Chrome, Mozilla autopush para Firefox, Apple push para Safari). `backend/main.py:34144-34149`.
- **Autenticación**: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` (default `mailto:hola@rendi.finance`). La pública se sirve sin auth por `GET /api/push/vapid-public-key` (`backend/main.py:34052`) — correcto, no es secreta.
- **Manejo de fallas**: sin timeout explícito (el de `pywebpush`). Sin retry. Si el gateway devuelve **404/410 → borra la suscripción** de `push_subscriptions` (`backend/main.py:34152-34158`); cualquier otro status se loguea y sigue con el próximo device. Si `pywebpush` no está instalado o faltan las keys → `return 0` en silencio (`backend/main.py:34122-34129`).
- **Qué ve el usuario si se cae**: no recibe la notificación. Las alertas siguen disparándose y quedando en la app.
- **Cache**: N/A.
- **Criticidad**: baja.
- **Estado**: viva. Hay un `POST /api/push/test` para probar el circuito end-to-end (`backend/main.py:34167`).

---

## Integraciones de brokers ← lo más sensible

### Wallbit (api.wallbit.io) — VIVA en producción, con credencial guardada

- **Para qué se usa**: sync automático read-only de la cuenta del usuario en Wallbit (broker/neobanco que opera acciones y ETFs US en USD). Trae los TRADEs y los mete por **el mismo pipeline que un CSV** (`store_preview_txs → persist → rebuild FIFO → recalc → snapshots`), reconstruyendo posiciones y P&L reales. Después reconcilia contra la foto real de tenencias.
- **Endpoints concretos** (base `https://api.wallbit.io/api/public/v1`, `backend/wallbit.py:24`):
  - `GET /balance/stocks` — `backend/wallbit.py:62` (validación de key) y `:70` (foto de tenencias)
  - `GET /assets/{symbol}` — `backend/wallbit.py:79` (precio para valuar aperturas seedeadas)
  - `GET /transactions?type=TRADE&limit=50&page=N[&from_date=]` — `backend/wallbit.py:96-99` (paginado)
  - Superficie propia: `GET /api/wallbit/status` (`backend/main.py:31218`), `POST /api/wallbit/connect` (`:31238`), `POST /api/wallbit/sync` (`:31278`), `DELETE /api/wallbit/disconnect` (`:31310`)
- **Autenticación**: header `X-API-Key` con **la API key del usuario final** (`backend/wallbit.py:42`). **No hay env var** — la key la pega el usuario.
- **🔑 Guarda credenciales del usuario: SÍ.**
  - Tabla `user_broker_credentials` con `broker='wallbit'`, columna `api_key_enc` (`backend/main.py:733-743`).
  - Cifrado **Fernet**, con clave derivada de `SHA256(SECRET_KEY)` en base64-urlsafe (`_wallbit_cipher`, `backend/main.py:31013-31020`).
  - Se guarda en su propia transacción, **antes** del sync inicial, "así sobrevive si el sync falla" (`backend/main.py:31249-31258`).
  - `DELETE /api/wallbit/disconnect` la borra (las posiciones importadas quedan).
- **Permisos que pide: solo lectura — pero no se puede verificar.** 🔴 Este es el punto más delicado del informe:
  - El módulo declara que Rendi solo usa endpoints de lectura y que la key debe tener permiso `read` (`backend/wallbit.py:1-16`).
  - `scope` se guarda **hardcodeado en `'read'`** (`backend/main.py:31255-31257`, `VALUES (?, 'wallbit', ?, 'read')`), sin consultar nada: es una etiqueta, no una verificación.
  - El propio frontend lo admite: *"La API de Wallbit NO expone los permisos de una key, así que no podemos bloquear por código una key con permiso de operar; el mitigante es esta instrucción clara"* (`frontend/src/components/import/WallbitConnect.jsx:115-117`).
  - El mitigante es un disclaimer en la UI: *"Es tu responsabilidad generar la key con permiso de lectura; Rendi no se hace responsable por keys creadas con permisos de operar (trade)"* (`WallbitConnect.jsx:119`).
  - **Consecuencia real**: si un usuario pega una key con permiso `trade`, Rendi la guarda cifrada y la conserva indefinidamente. Rendi no va a operar (no hay ningún método de escritura en `wallbit.py`), pero **el blast radius de un compromiso de la DB + `SECRET_KEY` incluye keys que pueden operar la cuenta del usuario**.
  - `403` sí se traduce a un mensaje claro: *"La API key no tiene permiso de lectura. Generala en Wallbit con el permiso read"* (`backend/wallbit.py:48`) — pero eso detecta la key con **menos** permisos, no la que tiene de más.
- **Manejo de fallas**: `timeout=20.0` (`backend/wallbit.py:25`). Sin retry. Errores traducidos a castellano por status (401 key inválida, 403 sin permiso read, 429 rate limit, ≥400 genérico — `backend/wallbit.py:45-52`). Tope de paginación `_MAX_PAGES=200` × 50 = 10.000 movimientos; **si Wallbit reporta más páginas que el tope, falla con aviso claro en vez de dar una cartera incompleta** (`backend/wallbit.py:107-110`) — buena decisión.
  - El estado de la última sync se persiste en `last_sync_status` (`'ok'` o `'error: …'`) y se muestra en la UI (`WallbitConnect.jsx:132-135`).
  - En `connect`, si la key valida pero el sync inicial falla: la credencial **queda guardada** y devuelve **502 "Conectamos tu cuenta pero falló el sync inicial: … Probá 'Sincronizar' en un rato"** (`backend/main.py:31272`).
- **Qué ve el usuario si se cae**: no puede conectar ni sincronizar; lo ya importado queda intacto. No hay sync automático de fondo `[V]` — no encontré ningún cron que llame `_wallbit_do_sync`; el sync es siempre a pedido del usuario.
- **Cache**: sync incremental por fecha — última sync menos **3 días de colchón**, y el dedup por `fingerprint` absorbe el solapamiento (`_wallbit_last_from_date`, `backend/main.py:31063-31078`).
- **Concurrencia**: lock por usuario (`_wallbit_sync_locks`, `backend/main.py:31010`), tomado **después** de todo el HTTP para no bloquear durante la red (`backend/main.py:31191`). ⚠️ Es in-process: el comentario aclara que asume server single-process.
- **Rate limit propio**: connect 6/60 s, sync 10/60 s por usuario (`backend/main.py:31241`, `:31281`).
- **Criticidad**: baja (afecta a los usuarios de Wallbit). **Sensibilidad: la más alta.**
- **Estado**: **viva en producción**, expuesta en el `ImportWizard` (`frontend/src/components/import/ImportWizard.jsx:5,796`).

### IOL — InvertirOnline (api.invertironline.com) — "IOL Lab", experimento vivo

- **Para qué se usa**: **no es un sync todavía.** Es la Fase 0 del `PLAN_iol_sync.md`: un tester pone usuario y contraseña de IOL en una página escondida, el backend hace login, corre un probe **read-only** de ~1 minuto contra la API v2 y guarda el resultado. Sirve para contestar preguntas de diseño (¿hay tope de paginación? ¿la API expone movimientos de caja? ¿cuánto vive el refresh token? ¿cuál es el rate limit desde la IP de Railway?).
- **Endpoints concretos** (base `https://api.invertironline.com`, `backend/iol_api.py:32`):
  - `POST /token` (grant_type=password y refresh_token) — `backend/iol_api.py:110`, `:120`
  - `GET /api/v2/datos-perfil`, `/api/v2/estadocuenta`, `/api/v2/portafolio/argentina`, `/api/v2/portafolio/estados_Unidos`, `/api/v2/operaciones`, `/api/v2/operaciones/{numero}`, `/api/v2/Notificacion` — allowlist en `backend/iol_api.py:34-42`
  - `POST /api/v2/Asesor/Movimientos` — `backend/iol_api.py:43` (única consulta de lectura bajo rol asesor; se prueba porque es la única chance de tener flujos de caja por API)
  - Superficie propia: `GET /api/iol/lab/status` (`backend/main.py:31464`), `POST /api/iol/lab/probe` (`:31490`), `POST /api/iol/lab/refresh` (`:31531`), `DELETE /api/iol/lab/disconnect` (`:31544`), `GET|POST /api/iol/lab/run-cron` (`:31559`), `GET /api/admin/iol-lab/runs` (`:31608`)
  - Frontend: `frontend/src/pages/IolLab.jsx`, ruta **escondida** `/lab/iol` sin ítem de nav (`frontend/src/App.jsx:53,226`)
- **Autenticación**:
  - Hacia IOL: usuario + contraseña del tester (no hay env var con credenciales de IOL).
  - Gate de acceso: `IOL_LAB_EMAILS` (allowlist separada por comas) **o** `is_admin`. Sin la variable configurada → **503 "IOL Lab no está habilitado"**; con la variable pero email fuera → 403 (`_iol_lab_gate`, `backend/main.py:31336-31351`).
  - Cron: `IOL_LAB_CRON_TOKEN` (header `X-Cron-Token` o `?token=`), sin token → 503 (`backend/main.py:31563-31568`).
  - `IOL_SPIKE_BASE` es solo un override de tests del script standalone (`backend/scripts/iol_spike.py:35`).
- **¿Puede operar? NO, y está bien defendido** ✅:
  - `_guard(method, path)` (`backend/iol_api.py:71-83`) es el único portón: bloquea fragmentos prohibidos (`/operar`, `cancelar`, `extraccion`, `deposito`, `cuentas-bancarias`), exige que todo GET esté en `ALLOWED_GET` y que todo POST esté en `ALLOWED_POST`, y **rechaza cualquier otro método** (PUT/DELETE/PATCH). Levanta `IolGuardError` **antes de tocar la red**.
  - `_request()` es el único punto de salida a la red del módulo (`backend/iol_api.py:85-104`).
  - El docstring del módulo dice que los métodos de escritura *"no están apagados: no existen"* (`backend/iol_api.py:11-14`) — verificado, no hay ninguno.
- **Guarda credenciales**:
  - **La contraseña, NO.** Vive en el frame de `login()` y en el body del request; el endpoint hace `del data` en un `finally` (`backend/main.py:31508`) y el frontend limpia el campo (`IolLab.jsx:48`). No se loguea.
  - **El refresh token, SÍ, pero opt-in.** Checkbox `keep_token` (default `true` en el frontend, `IolLab.jsx:21`). Se guarda cifrado con **el mismo Fernet que Wallbit**, en la misma tabla, con `broker='iol_lab'` (`backend/main.py:31510-31517`).
  - Lo renueva un cron horario (`CronTrigger(minute=7)`, `backend/main.py:32541-32546`) + un cron externo + una **renovación oportunista** cuando el tester abre `/status` y hace >55 min de la última (`backend/main.py:31471-31479`).
  - Si IOL responde 4xx al refresh → borra la credencial y anota "dead" en la bitácora; error de red → lo trata como transitorio (`_iol_lab_refresh_one`, `backend/main.py:31435-31450`).
  - `DELETE /api/iol/lab/disconnect` la borra. La bitácora queda (no tiene secretos).
- **Anonimización**: `mask()` (`backend/iol_api.py:129-143`) reemplaza por `***` las claves `nombre, apellido, dni, cuitCuil, email, numeroCuenta, cuentaComitente, numero_cuenta`, más `numero` cuando es string (número de cuenta, no de operación).
- 🔴 **Hallazgo: el `summary` NO pasa por `mask()`.** `run_probe` devuelve `{"summary": "\n".join(self.lines), "result": mask(self.data), ...}` (`backend/iol_api.py:305`) — el mask se aplica solo a `result`. Y las `lines` que arma `note()` contienen datos financieros crudos del tester: saldos por cuenta (`saldo=`, `disponible=`, `titulosValorizados=`, `backend/iol_api.py:186-188`) y **cada posición con símbolo, cantidad, PPC y valorizado** (`backend/iol_api.py:196-198`). Ese `summary` se persiste en `iol_lab_runs.summary` (`backend/main.py:31406`) y se **manda por email** a `ADMIN_NOTIFY_EMAIL` vía Resend (`backend/main.py:31414-31416`). El docstring del mail afirma lo contrario: *"El summary viene ANONIMIZADO por iol_api.mask"* (`backend/billing/emails.py:1663`). No lo viene. `[V]`
- **Manejo de fallas**: `_TIMEOUT = 30.0` (`backend/iol_api.py:53`). Sin retry. `IolError(0, ...)` para red/timeout, status real para HTTP. El probe corre en un **thread daemon** porque un request sincrónico daría 502 del gateway (`backend/main.py:31518`), y `_iol_lab_run_bg` atrapa todo para no dejar la corrida colgada en `'running'`. El login rechazado da 400 con una pista útil sobre activar las APIs en IOL (`backend/main.py:31496-31501`).
- **Rate limit propio**: probe 5/600 s, refresh 10/600 s por usuario (`backend/main.py:31492`, `:31534`).
- **Criticidad**: **cero para producción**. Ningún usuario común lo ve.
- **Estado**: **experimento a medio hacer, pero VIVO y deployado.** El endpoint existe, el cron in-process corre cada hora, y el gate depende de que `IOL_LAB_EMAILS` esté (o no) en Railway. Sin esa var, solo un admin puede entrar.
- `[V]` `backend/scripts/iol_spike.py` es la versión **standalone** del mismo probe, pensada para que el tester la corra **en su propia máquina** ("Rendi nunca ve su contraseña"). Solo stdlib. Es un camino paralelo, más conservador, al del IOL Lab.

---

## Frontend: scripts de terceros

### Meta Pixel (Facebook / Instagram Ads)

- **Para qué se usa**: retargeting y medición de conversión de las campañas de Meta.
- **Qué carga**: `https://connect.facebook.net/en_US/fbevents.js`, inyectado por un snippet **inline en el HTML** (`frontend/index.html:194-207`), o sea antes de que monte React. `<noscript>` con pixel de imagen a `https://www.facebook.com/tr?id=1281911210681122&ev=PageView&noscript=1` (`frontend/index.html:213-215`).
- **Pixel ID**: `1281911210681122`, **hardcodeado** en `frontend/src/utils/metaPixel.js:22` y en el HTML. El comentario aclara que el ID es público por diseño y que Vercel no inyectaba bien las `VITE_`. Un comentario cuenta que antes apuntaba a un pixel inexistente y los eventos iban al vacío.
- **Qué datos manda**: `PageView` automático + eventos estándar (`CompleteRegistration`, `Lead`) vía `trackMetaEvent`. El JSDoc pide explícitamente **no mandar PII** (`metaPixel.js:88`).
- ✅ **Guarda de privacidad, en dos capas**: no se inicializa ni se trackea en rutas que llevan **secretos en la URL** — `/i/` (token de invitación), `/claim` (token de takeover de cuenta), `/acceso` (informe público del cliente). El guard está en el HTML para la carga inicial (`frontend/index.html:203`) **y** en `trackMetaPageView` para la navegación SPA (`metaPixel.js:111-116`), con el comentario que dice que el segundo se agregó porque el primero no cubría la navegación (audit de seguridad).
- **Estado**: **activo**.

### Google Analytics 4

- **Qué carga**: `https://www.googletagmanager.com/gtag/js?id=G-DQ8LV6YJPP` — `frontend/src/utils/analytics.js:60`.
- **Measurement ID**: `G-DQ8LV6YJPP`, hardcodeado (`analytics.js:37`), mismo motivo declarado.
- **Qué datos manda**: `page_view` manual por route change + eventos de embudo (`sign_up`, `login`, `subscribe_*`, `plan_changed`, `ai_analyze_clicked`, `ai_chat_sent`, `report_exported`, `wrapped_viewed`, `first_position_added`…). `setUserId(uid)` manda el **user_id numérico de Rendi** como `String(uid)` (`analytics.js:134-144`) — el comentario de la cabecera dice "user_id se setea como uid hasheado", pero el código **no hashea nada** `[V]`. `setUserProperties` manda tier, has_broker, etc.
- ✅ **Config de privacidad**: `anonymize_ip: true`, `allow_google_signals: false`, `allow_ad_personalization_signals: false` (`analytics.js:72-75`).
- ✅ Mismo guard de rutas sensibles (`isSensitivePath`, `analytics.js:93`) **más** un borrado defensivo del query param `token` de `page_location` (`analytics.js:100-103`).
- **Estado**: activo.

### `track.js` — wrapper propio

- `[V]` **No es un tercero**: hoy es un no-op + `console.debug` con buffer en memoria de 100 eventos (`frontend/src/utils/track.js:45-73`). El comentario dice "Mañana: pega a PostHog / Plausible / Mixpanel cambiando solo este archivo" y hay un stub comentado para PostHog (`track.js:123-128`).
- Hace dos forwards reales: (a) 4 eventos de paywall al **backend propio** vía `POST /api/plan/track` (`track.js:55-60`, `:139-144`), y (b) ~18 eventos a **GA4** si `window.gtag` existe (`track.js:90-117`).
- En demo mode no reenvía nada al backend (`track.js:136`).

### Google Fonts

- `[V]` `@import url('https://fonts.googleapis.com/css2?family=Geist:...&family=JetBrains+Mono:...')` — `frontend/src/index.css:2`. Con `preconnect` a `fonts.googleapis.com` y `fonts.gstatic.com` (`frontend/index.html:83-84`).
- ⚠️ Es un `@import` en CSS, o sea **render-blocking**. El comentario de `index.html:78-82` cuenta que ya sacaron Instrument Serif + Manrope (~100-150KB) por LCP, pero el import que queda sigue siendo el mismo patrón. Si Google Fonts se cae, la tipografía cae al fallback del sistema (no rompe).

### Google Search Console

- `[V]` Solo un meta tag de verificación de propiedad: `frontend/index.html:21`. No carga script.

### WhatsApp (wa.me)

- `[V]` Deep links de soporte, no una API. `frontend/src/utils/support.js:11-13` arma `https://wa.me/{digits}?text=...`. El número `542914373695` está hardcodeado ahí y también en el backend (`backend/billing/emails.py:186-190`, footer de todos los mails) y en varias páginas (`Reembolso.jsx`, `Terminos.jsx`, `Planes.jsx`). El Plan Asesor lo reusa para que el asesor le escriba a sus clientes (`GroupWhatsAppModal.jsx`).

### CSP — qué permite el navegador

`[V]` `frontend/vercel.json:18` define la CSP. Lo que deja pasar:

- `script-src`: `'self'`, `'unsafe-inline'`, googletagmanager, google-analytics, connect.facebook.net
- `style-src`: `'self'`, `'unsafe-inline'`, fonts.googleapis.com
- `font-src`: `'self'`, `data:`, fonts.gstatic.com
- `img-src`: `'self'`, `data:`, `blob:`, **`https:`** (o sea, cualquier host HTTPS)
- `connect-src`: `'self'`, `https://trading-production-143b.up.railway.app`, google-analytics (+ wildcards), googletagmanager, connect.facebook.net, facebook.com
- `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`, `object-src 'none'`

⚠️ Dos cosas: `'unsafe-inline'` en `script-src` (necesario por el snippet inline del pixel y el del tema) y `img-src https:` abierto. Ninguna es sorpresa, pero valen anotarse.

`[V]` **El frontend no le pega a ninguna API de datos de terceros directamente.** Todo va por rutas relativas `/api/...` (`frontend/src/utils/api.js:106,228,265,304`), y Vercel rewritea a Railway server-side (`frontend/vercel.json:6`). Los únicos hosts externos que toca el browser son los de analytics/fonts/pixel. Es una decisión de arquitectura sana: las API keys nunca salen del backend.

---

## Infraestructura (terceros que no son APIs de datos)

### Railway — hosting del backend

- `[V]` `railway.toml` + `nixpacks.toml`. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`. `restartPolicyType = "on_failure"`.
- Env vars que setea Railway y el código lee: `RAILWAY_ENVIRONMENT` (usada por `is_likely_production`, `backend/billing/rebill.py:107`), `RAILWAY_GIT_COMMIT_SHA` (`backend/main.py:34293`).
- ⚠️ `nixpacks.toml` pinnea `pip<26` por un bug del resolver de pip 26.1.1, y agrega `stdenv.cc.cc.lib` a `LD_LIBRARY_PATH` porque numpy (que viene con yfinance) crashea sin `libstdc++.so.6`. Son dos dependencias frágiles del build sobre terceros.

### Vercel — hosting del frontend + proxy al backend

- `[V]` `frontend/vercel.json:6` rewritea `/api/(.*)` a `https://trading-production-143b.up.railway.app/api/$1`. Ese host está además en el `preconnect` de `index.html:88` y en el `connect-src` de la CSP.
- ⚠️ **El límite de ~30 s de ese rewrite es una restricción de diseño real**: el timeout del cliente Anthropic se bajó a 25 s justo por eso (`backend/main.py:20372-20382`), y `withGatewayRetry` reintenta 502/503/504 hasta 3 veces con jitter porque "pasa de verdad cada vez que deployamos" (`frontend/src/utils/gatewayRetry.js:11-22`).
- `VERCEL_GIT_COMMIT_SHA` / `COMMIT_REF` alimentan el `__BUILD_ID__` y el `version.json` del auto-update (`frontend/vite.config.js:14-15`).

### `autoUpdate.js` — no es un tercero

`[V]` Pollea **`/version.json` del propio origin** (`frontend/src/utils/autoUpdate.js:43`), con `cache: 'no-store'` y `credentials: 'omit'`. No manda nada a nadie. Compara contra `__BUILD_ID__` inyectado en build. Guard anti-loop por versión con máximo 2 intentos, fail-closed si no hay `sessionStorage` (iOS privado), y no recarga en `/login`, `/verify-email`, `/reset-password`, `/onboarding`, `/billing` (`autoUpdate.js:33`).

### Almacenamiento S3-compatible — backups

- **Para qué**: backup diario de la SQLite a las 03:45 UTC (`backend/main.py:32558-32564` → `_run_backup_db_job` → `scripts/backup_db.py:run_backup`).
- **Autenticación / config** (todas opcionales): `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY`, `BACKUP_S3_REGION`, `BACKUP_S3_PREFIX`, más `BACKUP_LOCAL_DIR` — `backend/scripts/backup_db.py:35-40`, `:143-166`.
- **Manejo de fallas**: `_s3_client()` devuelve `(None, motivo)` en vez de tirar — falta de env var, `boto3` no instalado, init fallido (`backup_db.py:139-166`). El backup local se hace igual.
- **Estado**: `[I]` **configurable, probablemente dormida**. El `endpoint_url` genérico sugiere Backblaze B2 / Cloudflare R2 / MinIO (lo dice el docstring, `:36`). Me agarro de que todo es opcional y degrada a `./backups/` local en el disco de Railway.
- ⚠️ Si las vars no están, el único backup vive en el mismo disco efímero que la base.

### Postgres gestionado (Supabase) — `DATABASE_URL`

- `[V]` Con `DATABASE_URL` seteada, toda la app habla Postgres por `pgshim` (`backend/main.py:423-430`). El comentario de `backend/main.py:495` nombra a **Supabase** ("da bastante menos margen de conexiones que las 100 del Postgres local"). Sin la var, sigue en SQLite. `PG_DSN_COPIA` es para el script de copia.

### Crons externos (cron-job.org / UptimeRobot)

`[V]` Cuatro endpoints pensados para que un cron de terceros los pinche, todos con auth por token y todos **cerrados con 503 si el token no está configurado**:

| Endpoint | Env var | Frecuencia declarada | Línea |
|---|---|---|---|
| `GET\|POST /api/alerts/evaluate` | `ALERTS_CRON_TOKEN` | ~10 min | `backend/main.py:33590` |
| `GET\|POST /api/snapshots/run-cron` | `SNAPSHOT_CRON_TOKEN` | 1×/día ~03:00 UTC | `backend/main.py:33647` |
| `GET\|POST /api/advisor/brief/run-cron` | `ADVISOR_BRIEF_TOKEN` (o el de snapshot) | 2×/día hábil | `backend/main.py:33936` |
| `GET\|POST /api/iol/lab/run-cron` | `IOL_LAB_CRON_TOKEN` | cada hora | `backend/main.py:31559` |
| `GET /api/health` | (público, sin auth) | despertar Railway | `backend/main.py:34270` |

`[V]` **Hay redundancia deliberada**: el `BackgroundScheduler` in-process (APScheduler) corre los mismos jobs (snapshot 02:59 UTC, IOL refresh cada hora al minuto 7, lifecycle 03:30, backup 03:45, FCI refresh 12:10 — `backend/main.py:32524-32573`), como red de respaldo del cron externo. El comentario del IOL lo dice explícito (`backend/main.py:31598-31600`). Vale recordar que APScheduler in-process no es confiable si Railway hiberna el contenedor, que es exactamente por qué existen los crons externos.

---

## Tabla resumen

| Servicio | Criticidad | Qué se rompe si se cae | ¿Fallback? |
|---|---|---|---|
| **yfinance (Yahoo)** | 🔴 Crítica | Precios de todo lo no-AR, benchmarks, fundamentales, heatmaps, tools del chat | Sí, en cascada: data912 → `asset_last_price` → cache stale 7d (fundamentales). Pero **congela en silencio**: el usuario ve un número plausible |
| **dolarapi.com** | 🔴 Crítica | El dólar de valuación (blue/MEP/CCL/cripto) de toda la cartera | Caché 5 min per-casa → `config.tc_blue` del usuario (posiblemente stale, sin avisar) |
| **data912.com** | 🟠 Alta | Precios de bonos AR y CEDEARs `.BA` | Cache stale (5 min TTL, sin expiración dura) → yfinance, que para bonos da **per-100 sin dividir** (~100× inflado) y para `.BA` da barras NaN |
| **ArgentinaDatos** | 🟠 Alta | Inflación, CER, UVA, tasas PF, precios FCI, backfills FX históricos | Sí y bien hecho: tablas persistentes, flag `stale`, y el FCI **muestra la fecha del VCP**. Tasas PF: 503 explícito |
| **Anthropic (Claude)** | 🟠 Alta (producto) | "Analizar", Coach IA, brief del asesor, Wrapped | No. 503/502 con mensaje. El resto de la app intacta |
| **Resend** | 🔴 Crítica (onboarding) | **OTP de verificación → nadie puede registrarse.** Reset de password, recibos, avisos admin | **No.** Sin retry, sin cola. Loguea el error y sigue |
| **Rebill** | 🟠 Alta (negocio) | Nadie puede suscribirse ni cancelar | No (correcto). Los ya pagos conservan el tier (vive en la DB de Rendi) |
| **MercadoPago** | ⚪ Nula | Nada — está muerto | N/A. ⚠️ Su webhook y `/api/billing/sync` siguen montados; `_sync_authorized_with_mp` es código muerto |
| **Wallbit** | 🟡 Baja / 🔴 Sensible | Sync de los usuarios de Wallbit | Import manual por CSV. Lo importado queda |
| **IOL (IOL Lab)** | ⚪ Nula | Un experimento gateado por allowlist | N/A |
| **Google News RSS** | 🟡 Baja | Noticias nuevas | Sí: tabla `news` histórica + SWR con tope de 4 s |
| **Investing.com RSS** | 🟡 Baja | Idem | Idem |
| **CAFCI** | ⚪ Nula | Un probe admin | N/A — ganó ArgentinaDatos |
| **Web Push (VAPID)** | 🟡 Baja | No llegan las notificaciones | Las alertas siguen en la app. Subs muertas (404/410) se auto-borran |
| **GA4 / Meta Pixel** | ⚪ Nula (usuario) | Se pierde medición de embudo y campañas | No. La app funciona igual |
| **Google Fonts** | ⚪ Nula | Tipografía cae al fallback del sistema | Sí (implícito). ⚠️ `@import` render-blocking |
| **S3 backups** | 🟠 Alta (recuperación) | El backup queda solo en el disco de Railway | Sí: `./backups/` local. `[I]` probablemente sin S3 configurado |
| **Railway** | 🔴 Crítica | Todo el backend | No |
| **Vercel** | 🔴 Crítica | Todo el frontend + el proxy `/api` | No. `withGatewayRetry` cubre reinicios cortos (502/503/504, ~8 s) |
| **Supabase / Postgres** | 🔴 Crítica (si `DATABASE_URL` está) | Toda la persistencia | Sin la var, SQLite local |
| **cron-job.org / UptimeRobot** | 🟡 Media | Alertas y snapshots dejan de correr a horario | Sí: APScheduler in-process duplica los jobs (pero no corre si Railway hiberna) |

---

## Lo que más me llamó la atención

1. 🔴 **El `summary` del IOL Lab sale sin anonimizar por email.** `run_probe` masquea `result` pero no `summary` (`backend/iol_api.py:305`), y ese texto trae saldos por cuenta y cada posición con cantidad/PPC/valorizado (`backend/iol_api.py:186-198`). Va a `iol_lab_runs.summary` y a `ADMIN_NOTIFY_EMAIL` por Resend (`backend/main.py:31406,31414`). El docstring del mail afirma exactamente lo contrario (`backend/billing/emails.py:1663`).

2. 🔴 **`_sync_authorized_with_mp` no la llama nadie.** El docstring del cron promete "sync con MP para detectar webhooks perdidos" (`backend/main.py:32079`), `run_lifecycle_job` inicializa `synced_from_mp: 0` (`backend/billing/subscriptions.py:38`) y nunca la invoca. La red de seguridad de webhooks perdidos no existe, y el log diario reporta `0` como si hubiera corrido.

3. 🔴 **El permiso de la key de Wallbit no se puede verificar** y `scope` se guarda hardcodeado en `'read'` (`backend/main.py:31255`). La API de Wallbit no expone permisos; el mitigante es un disclaimer en la UI (`WallbitConnect.jsx:115-119`). Una key con permiso `trade` queda guardada cifrada, indefinidamente, sin que Rendi lo sepa.

4. 🔴 **Un solo `SECRET_KEY` para dos cosas incompatibles.** Firma los JWT (`backend/main.py:2689`) **y** deriva el Fernet que cifra las credenciales de broker (`backend/main.py:31018-31020`). Rotar `SECRET_KEY` —la respuesta normal ante un incidente— **destruye irreversiblemente** las API keys de Wallbit y los refresh tokens de IOL guardados. El código del IOL Lab ya contempla ese caso y borra la credencial con el detalle `"dead: no se pudo descifrar el token (SECRET_KEY cambió)"` (`backend/main.py:31434`); el de Wallbit devuelve 400 "Reconectá tu cuenta" (`backend/main.py:31292`).

5. 🟠 **Resend no tiene retry ni cola, y el registro depende de él.** Un OTP que no llega es un usuario que no puede crear la cuenta, sin reintento ni mensaje que lo explique.

6. 🟠 **El grado de dependencia de fuentes comunitarias sin SLA es alto**: dolarapi, data912 y ArgentinaDatos sostienen la valuación completa de la cartera, y ninguna tiene contrato ni auth. El propio código lo reconoce (`backend/pricing/fci.py:19`). Los fallbacks son buenos; lo que falta es que el **usuario** vea cuándo está mirando un número congelado (hoy solo el FCI muestra `as_of`).

7. 🟠 **`yf.download` no lleva timeout** en ninguno de sus call sites. Con el rewrite de Vercel cortando a ~30 s, un Yahoo lento se traduce en un 502 con HTML que el frontend no puede parsear.

8. 🟡 **`/api/billing/sync` sigue expuesto** y le manda a MercadoPago un ID que hoy es de Rebill (`backend/main.py:27420-27452`). El frontend ya no lo llama.

9. 🟡 **El comentario de `analytics.js` dice "user_id se setea como uid hasheado"** pero `setUserId` manda `String(uid)` crudo (`frontend/src/utils/analytics.js:37,140-142`). No es PII directa, pero el comentario miente sobre lo que hace el código.

10. ✅ **Lo que está muy bien**: el guard de la allowlist de IOL (`iol_api.py:71-83`), el allowlist de hosts de la URL de checkout de Rebill (`main.py:26594-26603`), el guard de rutas con secretos en GA4 y Pixel (dos capas, HTML + SPA), `defusedxml` en el parser RSS, y la decisión del cron de snapshots de **no escribir** antes que escribir un total subvaluado (`snapshots_job.py:700-710`).
