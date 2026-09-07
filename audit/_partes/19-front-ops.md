## Frontend — Operaciones, Importación, Novedades, Alertas

Alcance: las pantallas **operativas** (donde el usuario carga, importa, borra y se entera de cosas), más el chat de IA. Todo verificado contra `origin/main` (`b74f450f`).

Convención: `[V]` = verificado leyendo el código (con cita), `[I]` = inferencia (digo de qué me agarré).

---

### Mapa de rutas (qué monta cada URL)

`[V]` `frontend/src/App.jsx:186-267` (bloque autenticado):

| URL | Monta | Nota |
|---|---|---|
| `/operaciones` | `Operations` | `App.jsx:214` |
| `/imports` | `Imports` | `App.jsx:225` |
| `/novedades` | `Novedades` | `App.jsx:210` |
| `/eventos` | `<Navigate to="/novedades?tab=eventos" replace />` | `App.jsx:212` |
| `/noticias` | `<Navigate to="/novedades?tab=noticias" replace />` | `App.jsx:213` |
| `/alertas` | `Alertas` | `App.jsx:227` |
| `/config/notificaciones` | `<Navigate to="/alertas" replace />` | `App.jsx:230` |
| `/ai` | `RendiAI` | `App.jsx:228` |
| `/mas` | `More` | `App.jsx:264` |

`[V]` Ninguna de estas rutas está en la tab-bar mobile: los tabs retail son `/`, `/posiciones`, `/insights`, `/mas` (`frontend/src/components/mobile/MobileTabBar.jsx:31-35`). O sea, en el celular `/operaciones`, `/imports`, `/alertas`, `/novedades` y `/ai` se alcanzan **sólo** desde "Más" (o por deep-link).

---

## `/operaciones` → `frontend/src/pages/Operations.jsx` (1409 líneas)

### Qué muestra

Una pantalla, **dos tabs** y **dos ramas de render** (ancha/angosta) sobre el mismo dueño de datos.

- **Tab `all` — "Todos los movimientos"** (`Operations.jsx:456` → `<MovementsView>`): historial unificado (compras, ventas, depósitos, retiros, dividendos, intereses, comisiones, impuestos). KPI strip adaptativo + pills por tipo + filtros broker/año + agrupado + tabla paginada (desktop) o feed por día (mobile).
- **Tab `trades` — "Solo P/L"** (`Operations.jsx:458`): trades cerrados con KPIs de P&L (P&L realizado, win rate, # operaciones, mejor trade), strip de "patrones", filtros, y tabla agrupable (desktop) o feed por día (mobile).

El tab se persiste en `localStorage['rendi_operations_tab']`, con default por anchura: `trades` en mobile, `all` en desktop (`Operations.jsx:74-75`).

### De dónde saca los datos

| Endpoint | Línea | Para qué |
|---|---|---|
| `GET /api/operations` | `Operations.jsx:139` | dataset del tab "Solo P/L" |
| `GET /api/brokers` | `Operations.jsx:129` | opciones del filtro Broker + select del modal de alta |
| `POST /api/operations` | `Operations.jsx:185` | alta manual |
| `PUT /api/operations/{id}` | `Operations.jsx:183` | edición |
| `DELETE /api/operations/{id}` | `Operations.jsx:224` | borrado individual |
| `POST /api/operations/undo/{token}` | `Operations.jsx:207` (base `'/operations/undo'`, `226`) | deshacer |
| `DELETE /api/assets/history?asset=…` | `Operations.jsx:251` y `1020` | borrar TODO el historial de un activo |
| `POST /api/assets/undo/{token}` | `Operations.jsx:254` / `1030` | deshacer ese borrado |
| `GET /api/movements` | `Operations.jsx:1052` | dataset del tab "Todos" |
| `DELETE /api/movements/{id}` | `Operations.jsx:1100` | borrado de un movimiento |

`[V]` Todos los paths van con prefijo `/api` (`frontend/src/utils/api.js:228` para uploads; `req()` hace lo mismo). Verificados contra el backend: `backend/main.py:12380` (`GET /api/operations`), `12389` (`GET /api/movements`), `13130` (`DELETE /api/movements/{movement_id}`), `13821`/`13890`/`14721`/`14743` (operations POST/PUT/DELETE/undo), `15019`/`15040` (`/api/assets/history`, `/api/assets/undo`).

### ⚠️ Cálculos hechos en el cliente

Esta pantalla es casi toda cliente. Lo que el backend manda es una lista cruda; **todos los agregados los computa el navegador**.

1. **Normalización de `pnl_usd` al cargar** — `Operations.jsx:140`:
   ```js
   setOps((rows||[]).map(o => ({ ...o, pnl_usd_native: o.pnl_usd, pnl_usd: opPnlUsd(o) })))
   ```
   `opPnlUsd` (`frontend/src/utils/assetPnl.js:76-84`) divide por `fx_to_usd` cuando la op es un cupón/amortización en moneda ARS. O sea: el número que se ve en pantalla **no es** el que devolvió `/api/operations`, y el form de edición vuelve a escribir el nativo (`pnl_usd_native`, `Operations.jsx:156`).

2. **P&L Realizado (KPI)** — `Operations.jsx:268-271`: `histMoney.sumConvertedAt(ops, o => o.pnl_usd || 0)` = *convert-then-sum* (cada fila con SU FX histórico). El motor está en `frontend/src/hooks/useHistoricalMoney.js:101-112`, con la cadena de prioridad `stampedFx > lookup por fecha > tcValuacion de hoy` (`useHistoricalMoney.js:30-48`).

3. **Win rate / wins / losses / trades** — `Operations.jsx:276` → `computeTradeStats` (`frontend/src/utils/tradeStats.js:64-76`). Excluye `Compra`, `Dividendo`, `Interés` y las conversiones; los `pnl_usd === 0` cuentan en el denominador y no en el numerador.

4. **Mejor trade** — `Operations.jsx:284-294`: se elige el máximo **sobre el valor convertido a la moneda del toggle**, no sobre el USD. En pesos el ranking puede diferir del ranking en USD (está documentado en el propio comentario, `Operations.jsx:278-283`).

5. **Patrones** — `Operations.jsx:299-327`: activo más operado (`countByAsset`, líder claro con ≥3 ops) y racha ganadora más larga (`pnl_usd > 0` consecutivos por fecha). Puramente cliente.

6. **Filtrado y agrupación** — `Operations.jsx:330-340` (filtro) y `367-370` (`buildGroups`). `buildGroups` vive en `frontend/src/components/operations/shared.js:183-226`.

7. **Totales de grupo** — `TradesTable.jsx:210` y `MovementsTable.jsx:196`: `histMoney.sumConvertedAt(group.rows, movPnl)`. El invariante buscado es `total === Σ filas`.

8. **Comisiones totales** — `Operations.jsx:1165-1173`: `Σ amount_usd` de los `FEE` **más** `Σ fees_usd` embebidas en el resto de las filas (excepto `IMPUESTO`). Se computa acá y no se consume `/api/insights/commissions` porque este número respeta los filtros de broker/año.

9. **KPIs de movimientos** — `Operations.jsx:1358-1409` (`computeMovementKpis`): "Aportado neto" = `Σ DEPOSIT − Σ WITHDRAW`, "Cobrado" = `Σ DIVIDEND + Σ INTEREST`, "Comisiones" = `commTotalUsd`.

10. **`buildPeriodOptions`** (`shared.js:134-138`) deriva los años disponibles del propio dataset.

### 🔴 Divergencia de FX entre el KPI strip y la tabla (tab "Todos")

`[V]` En `MovementsView` conviven **dos formateadores**:

- `money = useMoneyFormat()` → convierte con `tcValuacion` de **HOY** (`frontend/src/contexts/CurrencyContext.jsx:304-315`).
- `histMoney = useHistoricalMoney()` → convierte con el FX **de la fecha de cada fila**.

`Operations.jsx:980` define `fmtUsd = v => money.fmtMoney(v, {signed:false})` y ese es el que se le pasa a `computeMovementKpis` (`Operations.jsx:1175`). Las **filas** de `MovementsTable` usan `histMoney.fmtMoneyAt` (`MovementsTable.jsx:120-126`). El propio comentario lo admite (`Operations.jsx:975-977`: *"Los KPIs de montos (totales / promedios) siguen con `money`"*).

**Consecuencia:** con el toggle en PESOS, "Aportado neto" del strip **no** es la suma de los depósitos/retiros que se ven abajo. En USD coinciden (no hay conversión).

### 🔴 "Operaciones · total cerradas" cuenta lo que no es un trade cerrado

`[V]` `Operations.jsx:481-485`:
```jsx
<KpiCell label="Operaciones" value={ops.length.toLocaleString('es-AR')} sub="total cerradas" />
```
`ops` es **todo** lo que devuelve `/api/operations` (compras, dividendos, conversiones incluidos), mientras que la celda de al lado dice `${trades} cerradas` con el criterio estricto de `computeTradeStats`. Las dos celdas están una junto a la otra y dicen números distintos con la misma etiqueta.

`[I]` Mismo tema con "P&L Realizado": suma `o.pnl_usd || 0` sobre **todas** las ops (`Operations.jsx:269`), mientras que el win rate excluye dividendos/intereses. Si un dividendo importado trae `pnl_usd`, entra al P&L realizado pero no al win rate. Me agarro de que el filtro de `esTradeCerrado` (`tradeStats.js:45-53`) descarta esos tipos y el sumador no.

### Estado / contexto que consume

- `useCurrency` / `useMoneyFormat` / `useHistoricalMoney` (toggle global ARS↔USD) — `Operations.jsx:23-24, 83-84, 978-979`.
- `useToast` — `Operations.jsx:94`, `1006`.
- `useIsMobile` — `Operations.jsx:64` (breakpoint 768px, `frontend/src/hooks/useIsMobile.js:12`).
- **No** consume `AuthContext`, `AdvisorContext`, `PrivacyContext` ni `CoachDrawerContext`. `[V]` no hay imports de esos módulos en el archivo.
- `localStorage`: `rendi_operations_tab` (74), `rendi_trades_group` (115), `rendi_movements_group` (991).

### Gating por plan

- Sólo el botón **Exportar CSV** (`Operations.jsx:396`, `ExportCsvButton resource="operations"`). El gate es `can('export.csv')` (`frontend/src/components/plan/ExportCsvButton.jsx:28`); Free abre `UpgradeModal` sin llamada de red (`ExportCsvButton.jsx:32-36`). En el backend, `export.csv` es `False` para free y `True` desde plus (`backend/ai/plan.py:57,77`).
- `AnalyzeButton screen="operations"` (`Operations.jsx:395`) no gatea en el cliente: el 429/403 viene del backend y se renderiza como `UpgradePromoCard` dentro del drawer.
- **No hay** límite de operaciones manuales ni gating del historial en esta pantalla.

### Variante mobile — en qué divergen (no es sólo estética)

No hay un archivo separado (el fork `OperationsMobile.jsx` se mató; el comentario de cabecera lo cuenta, `Operations.jsx:1-14`). Las diferencias reales:

| | Desktop (`!isMobile`) | Mobile (`isMobile`) |
|---|---|---|
| Header + acciones | `PageHeader` con **Analizar (IA)**, **Exportar CSV** y **Nueva operación** (`386-406`) | **no existe** ninguno de los tres |
| Alta/edición manual | `OpFormModal` (`725-734`) | **no se monta** — no se puede crear ni editar una operación |
| Agrupado | pill "Agrupar" (activo / mes / ninguno), persistido (`632`) | forzado a `'day'` (`362`) |
| Paginación | 50 filas en modo plano (`TradesTable.jsx:22,98`) | ninguna: el feed muestra todo |
| Patrones (InsightLine) | sí (`560-578`) | no |
| Filtros | panel colapsable con broker/resultado/período/agrupar (`581-637`) | `BottomSheet` con período/resultado/broker — **sin** el filtro de texto por activo (`689-722`) |
| Loading | ninguno (cae al EmptyState de la tabla) | gate `loadingOps` (`661-665`, ver comentario `88-92`) |
| KPIs | strip de 4 celdas (`462-497`) | 2 números en un header sticky `top-[88px]` (`502-557`) |
| Tab "Todos": pills de tipo, selects de broker/año, KPI strip | sí (`1219-1284`) | **no se renderizan** — un filtro puesto en desktop persiste en el mismo mount pero es invisible/irreversible desde el feed salvo por el botón "Limpiar filtros" que aparece cuando `filtered.length < movements.length` (`1317-1327`) |
| Acciones por fila (trades) | Analizar IA + Editar + Eliminar (`TradesTable.jsx:165-184`) | sólo Eliminar (`TradesFeed.jsx:121-130`) |

`[V]` El feed de movimientos (`MovementsFeed.jsx:60-66`) formatea con `signed:false`: depósitos y retiros salen ambos en positivo, diferenciados sólo por color. Igual en la tabla (`MovementsTable.jsx:120-126`).

### Rarezas

- `[V]` **Import muerto**: `fmtUsd as fmtUsdRaw` (`Operations.jsx:21`) no se usa en ninguna parte del archivo (sólo aparece en un comentario en la línea 1148).
- `[V]` **Local muerto**: `const fmtUsd = …` en el componente `Operations` (`Operations.jsx:85`) nunca se llama.
- `[V]` **`useMemo` que no memoiza**: `Operations.jsx:1175` lista `fmtUsd` en las deps, pero `fmtUsd` se re-crea en cada render (`Operations.jsx:980`) → los KPIs se recomputan siempre.
- `[V]` **Dos definiciones de cantidad**: `formatQty` (`shared.js:104-109`, locale `en-US`, piso de 4 decimales) para el feed, vs `toLocaleString('es-AR', {maximumFractionDigits:4})` inline en la tabla (`MovementsTable.jsx:146`). El propio comentario avisa que difieren (`shared.js:99-103`).
- `[V]` **`enPeriodo` trata distinto las filas sin fecha según la rama**: ventana relativa → pasan; año → no pasan (`shared.js:149-159`, documentado a propósito).
- `[V]` **Confirmaciones nativas**: `confirm()` de browser en `del` (`221`), `delGroup` (`242`) y `handleDelete` (`1093`), no un modal de la app.
- `[V]` **`tone` sin usar**: `MOVEMENT_TYPES[].tone` (`shared.js:57-63`) no lo lee ningún consumidor; las pills usan sólo `icon`/`label`/`id` (`Operations.jsx:1230-1250`).
- `[V]` El P&L de un grupo por **mes** también muestra un tacho, pero `onDeleteGroup` sólo se pasa cuando `groupBy === 'asset'` (`TradesTable.jsx:84`, `MovementsTable.jsx:67`). Correcto, pero `MovementsTable` agrega además el guard `group.rows.some(r => r.type==='BUY'||'SELL')` (`MovementsTable.jsx:193-194`) que `TradesTable` **no** tiene: en "Solo P/L" el tacho de grupo aparece siempre.

---

## `/imports` → `frontend/src/pages/Imports.jsx` (685 líneas)

### Qué muestra

- Header con el CTA **Nueva importación** + 5 botones "avanzados" (`Recalcular aggregates`, `Limpiar broker`, `Estado de Cuenta PPI`, `Estado de Cuenta Cocos`, `Portafolio IEB`, `Resumen IOL`) que sólo aparecen si ya hay historial (`isFirstUse === false`, `Imports.jsx:177`).
- Card de gestión de **Wallbit** (sólo si ya está conectado, `Imports.jsx:284`).
- Tabla de lotes: fecha, archivo, broker, filas válidas/con errores, estado (`confirmed` / `reverted` / otro), y acciones **Editar y rehacer** / **Revertir** (sólo en lotes `confirmed`, `Imports.jsx:334`).
- Modales: confirmar reversa (con **Forzar revert** nuclear), confirmar redo, limpiar broker.

### De dónde saca los datos

| Endpoint | Línea | Backend |
|---|---|---|
| `GET /api/imports` | `Imports.jsx:60` | `backend/main.py:31627` |
| `POST /api/imports/{id}/revert` (+`?nuclear=1`) | `Imports.jsx:74-77` | `backend/main.py:31890` |
| `POST /api/imports/{id}/redo` | `Imports.jsx:109` | `backend/main.py:31930` |
| `POST /api/imports/recalc-pnl` | `Imports.jsx:131` | `backend/main.py:31718` |
| `GET /api/brokers` | `Imports.jsx:151` | para el modal de "Limpiar broker" |
| `POST /api/imports/wipe-broker?broker=…` | `Imports.jsx:163` | `backend/main.py:31740` |

`[V]` Después de revert/redo/recalc/wipe dispara `window.dispatchEvent(new Event('rendi:portfolio-changed'))` (`78, 110, 132, 164`) — el bus interno que usan Cartera y el snapshot del chat para refrescarse.

### ⚠️ Cálculos hechos en el cliente

Prácticamente ninguno: la tabla imprime lo que devuelve `/api/imports`. Lo único derivado es `fmtDate` (`Imports.jsx:676-685`), que parchea el formato `"YYYY-MM-DD HH:MM:SS"` a ISO agregándole una `Z` (asume UTC).

### 🔴 El aviso del asesor está renderizado **adentro** del botón "Nueva importación"

`[V]` `Imports.jsx:189-202`:
```jsx
<button onClick={() => setShowWizard(true)} className="inline-flex items-center gap-1.5 …">
  <Upload size={12} strokeWidth={2} />

{advisorOwnLevel && (
  <div className="mb-4 text-[12.5px] … rounded-md px-3 py-2.5">
    Estás en tu cuenta de trabajo, que no tiene cartera propia. …
  </div>
)} Nueva importación
</button>
```
El bloque quedó **anidado dentro del `<button>` del `PageHeader`**, entre el ícono y el texto. Efectos: (a) `<div>` dentro de `<button>` es HTML inválido; (b) para un asesor en su propio nivel el aviso no aparece arriba del contenido sino incrustado en el CTA, reventando el layout de la fila de acciones; (c) para todos los demás, es simplemente indentación rara. La variable existe y está bien calculada (`Imports.jsx:29`) — el problema es dónde terminó el JSX.

### Estado / contexto

- `useAuth()` → `user.tier` (`Imports.jsx:24`).
- `useAdvisorContext()` → `clientCtx` (`Imports.jsx:25`); `advisorOwnLevel = tier==='advisor' && !clientCtx` (`29`).
- `useSearchParams()` → `?from=onboarding` abre el wizard solo (`31, 52-54`).
- `localStorage['rendi_first_import_done']` (`Imports.jsx:20, 421-424`): el primer import confirmado redirige a `/bienvenida` al cerrar el wizard.

### Gating por plan

`[V]` **Ninguno en esta pantalla.** No hay `usePlanFeatures`, ni límite de imports, ni bloqueo de las herramientas destructivas (`Limpiar broker`, `Forzar revert`) para tiers bajos. El único gate relacionado que aparece en el flujo es el de **brokers** (403 al crear el 2º broker en Free), y vive en `BrokerManager`/backend, no acá.

### Variante mobile

`[V]` **No existe.** `Imports.jsx` no importa `useIsMobile` y no tiene ramas por anchura. La fila de 6 botones del header scrollea horizontal (el comentario en `Imports.jsx:187-188` lo reconoce y por eso puso el CTA primero).

### Rarezas

- `[V]` El botón **"Forzar revert" aparece siempre** en el modal de reversa (`Imports.jsx:547-556`), incluso antes de que la reversa normal haya fallado — con copy que dice "modo nuclear" y advertencia de que las posiciones consumidas por ventas no se recrean (`Imports.jsx:80`).
- `[V]` `doRevert` decide si el error es terminal con un regex de mensaje: `/no encontrado|confirmad/i` (`Imports.jsx:87`). El comentario documenta que el regex anterior (`/ventas|conversiones|fifo/`) fallaba con la palabra "vendida" y dejaba al usuario sin salida (`Imports.jsx:92-96`). Sigue siendo *string matching* contra mensajes del backend.
- `[V]` `StatusPill` cae al fallback `<Pill tone="warn">{status}</Pill>` con el string crudo para cualquier estado que no sea `confirmed`/`reverted` (`Imports.jsx:668-672`) — un `pending` se muestra literalmente como "pending".
- `[V]` Los 4 botones de "foto de tenencia" (PPI / Cocos / IEB / IOL) son **hardcode por broker** en el header (`Imports.jsx:229-264`), con instrucciones también hardcodeadas (`438-514`), mientras la capacidad real de foto viaja en `/imports/parsers/grouped` como `tenencia_format` (ver `ImportWizard.jsx:147-153`). Dos fuentes de verdad para lo mismo.

---

### `frontend/src/components/import/ImportWizard.jsx` (2980 líneas)

#### Flujo completo, paso por paso

Los pasos son constantes de módulo (`ImportWizard.jsx:70-83`): `intro → upload → (map) → preview → (seed) → (reconcile) → done`. El `Stepper` (`1090-1125`) arma la lista visible según `skipMap` (parser específico), `hasSeed`, `hasSeedAssets` y `hasTenencia`.

**Paso 0 — `STEP_INTRO`** (`IntroStep`, `1137-1361`)
1. **¿CSV o integración?** (`1168-1184`) → `entryType`. Si elige `integration`, se monta `<WallbitConnect onSynced={onWallbitConnected}/>` inline (`1187-1192`) y **no** aparece el botón Continuar (`919`).
2. **¿Export de broker o plantilla propia?** (`1197-1209`) → `sourceType`.
   - **broker**: grid de plataformas soportadas leídas de `GET /api/imports/parsers/grouped` (`280`, backend `main.py:29458`), filtrando `generic` y las bloqueadas (`1143-1147`). Al elegir, `chooseBrokerPlatform` (`367-374`) setea `platform` + el primer `export.supported` como `format`, y deja `singleBroker` vacío (el backend auto-crea el broker). Debajo, link de WhatsApp "No encuentro mi broker" (`1236-1244`) y `<BrokerInstructions lockBrokerId={platform}/>` (`1247-1249`).
   - **personal**: moneda ARS/USD (`1257-1281`), broker destino (select de `GET /api/brokers`, `283`) o creación inline vía `POST /api/brokers` (`349-362`), y el toggle "mi archivo mezcla varios brokers" → `importMode='general'` (`1340-1355`).
3. **Continuar** habilitado sólo si `sourceType==='broker' && isSpecificParser`, o `sourceType==='personal' && personalCurrency && (importMode==='general' || singleBroker)` (`924-928`).

**Paso 1 — `STEP_UPLOAD`** (`UploadStep`, `1368-1579`)
- Resumen de lo elegido + "Cambiar" (`1433-1449`).
- Si el broker tiene foto y no la trajo: caja azul "Traé también el resumen de {broker}" (`1454-1474`), decidida por `resolverFaltaTenencia` (`147-153`, exportada y testeada en `frontend/src/components/import/faltaTenencia.test.js`).
- Dropzone multi-archivo con dedup por `(name,size)` (`1377-1422`). Extensiones aceptadas: `.csv .txt .xlsx .xls`, más `.pdf` sólo si `format==='bullmarket' || platform==='balanz' || platform==='iol'` (`1388`, `1522`).
- Para la rama propia, botón "Descargar template de ejemplo" → `GET /api/imports/template?format=…` vía `fetch` directo (no `api.getBlob`) (`409-428`).

**Paso 1.5 — separación de la foto de tenencia** (`uploadAndInspect`, `466-553`)
- Si el parser es específico: aparta los `.pdf` como foto (`489`); para Cocos, detecta el CSV de Estado de Cuenta **por contenido del header** (`looksLikeCocosTenenciaCsv`, `126-130`, match exacto de 5 tokens); para PPI/IEB/inviu (todos `.xlsx`, indistinguibles en el browser) pregunta al backend con `POST /api/imports/classify-tenencia` (`506`, backend `main.py:29496`).
- Si quedó foto y **no** quedaron movimientos, corta con un error explicativo (`519-523`).
- `POST /api/imports/preview` con los archivos restantes + `format` (+ `broker` si `single`) → `STEP_PREVIEW` (`524-534`).

**Paso 2 — `STEP_MAP`** (sólo parser genérico; `MapStep`, `1582-1819`)
- Llega ahí vía `POST /api/imports/inspect` con **sólo el primer archivo** (`538-540`; el resto debe tener el mismo header — aviso en `1563-1567`).
- Mapea `columna → campo Rendi` + valores fijos por campo; cada campo tiene un `(?)` con `FIELD_HELP` (`12-68`).
- Plantillas de mapeo guardadas: `GET /api/imports/mappings` (`287`), `POST` (`301`), `DELETE /api/imports/mappings/{id}` (`314`) — backend `main.py:31665/31684/31707`.
- Valida required client-side y muestra "Falta mapear: X, Y" (`556-566`).
- **Generar vista previa** → `POST /api/imports/preview` con `format='rendi_generic'` + `mapping` serializado (`570-577`).

**Paso 3 — `STEP_PREVIEW`** (`PreviewStep`, `2114-2446`) — cómo se muestra el preview
- Banners, en este orden: redo (`2127-2141`), "ya tenés posiciones de X importadas / las duplicadas se omiten solas" (`2142-2158`), "podés verificar este import con el resumen de X" (`2165-2191`), y "te faltan datos / falta confirmar tu cash" con CTA al paso seed (`2192-2218`).
- Destino: "Importando todo a: {broker}" + desglose `ars_rows_to_parent` / `usd_rows_to_sibling` (`2219-2232`), brokers nuevos auto-creados (`2234-2254`), distribución multi-broker (`2256-2279`).
- **Duplicado exacto del archivo**: banner ámbar "si confirmás vas a duplicar" (`2281-2286`), a partir de `preview.duplicate_of_batch_id`.
- 4 `SummaryBox`: filas totales / válidas / con errores / brokers (`2288-2293`).
- "Se va a crear": conteo por tipo de operación + impacto estimado (posiciones, operaciones, movimientos de cash, conversiones) (`2295-2310`).
- Rango de fechas (`2312-2316`), tabla "Por activo" con compras/ventas/neto (`2318-2340`).
- **Filas ya importadas** (dedup por fecha+broker+tipo+activo+cantidad+precio) listadas por índice, hasta 30 (`2342-2356`).
- **Cash en negativo**: sólo si NO hay seed pendiente, para no duplicar el aviso (`2358-2380`).
- **Errores**: lista `Fila N — mensaje`, con el aclarador de que las válidas entran igual (`2382-2396`).
- **Filas a importar**: tabla con checkbox por fila para **omitir** (`2398-2443`); el destildado alimenta `skippedRowIndices`.

**Confirmación** (`confirm`, `663-718`)
- `POST /api/imports/confirm` con `{session_id, skip_row_indices, seed_state}` (`669-673`).
- Si hay `tenenciaFile`, encadena `POST /api/imports/tenencia/preview` con `broker` resuelto por `TENENCIA_BROKER_BY_FORMAT[format] || singleBroker || 'Bull Market'` (`686`) y, si devuelve `session_id`, **frena en `STEP_RECONCILE`** (`693-700`).
- El botón principal se deshabilita si `toImport === 0` (`1016`) y su label dice cuántas filas entran y cuántas se omiten (`1010-1012`).
- Si hay `seed_suggestions.needed` **y no hay foto**, el botón de confirmar se reemplaza por "Completar mis datos →" (`995-1009`): no se puede confirmar sin resolver el cash.

**Paso 4 — `STEP_SEED`** (`SeedStep`, `2457-2690`)
- Estado sembrado desde `preview.seed_suggestions` con los cash en `''` (`587-618`).
- Por broker y moneda: chip "según tu CSV {final_balance}" (`2550-2560`), botón "Es el mismo que calculó Rendi" (sólo si `F >= 0`, `2567-2580`), input del saldo de HOY con borde ámbar mientras esté vacío (`2581-2602`).
- Por posición: precio de compra, con "No sé el precio" → 0 para las de `exact_qty` (`2621-2676`).
- **`buildSeedPayload`** (`620-660`) es donde está la matemática: el ajuste que se manda es `saldo_tipeado − final_balance`, y se manda **con signo** (positivo = depósito sintético, negativo = retiro), filtrando `|adj| > 0.005`.
- Gate del botón: `cashComplete` exige un valor en **todas** las monedas mostradas (`1033-1043`), `assetsComplete` exige precio en todas las `exact_qty` (`1048-1052`).

**Paso 5 — `STEP_RECONCILE`** (`ReconcileStep`, `1850-2018`) — contra el resumen del broker
- 4 "baldes": se completan (`to_seed`), el resumen no los tiene (`not_in_snapshot`), tienen más cantidad (`over`), y "necesitamos que decidas vos" (`no_reconciliable`).
- **Default = NO aplicar**: los ítems con `requiere_aprobacion` arrancan destildados y `aprobar_tickers` es opt-in (`720-730`, `1986-1988`).
- Lo pendiente de aprobación se **filtra** de las tres listas afirmativas para que no aparezca dos veces (`1856-1863`).
- `<Chip>` de confianza por balde: `verificada_composicion` vs "sin verificar la cantidad" para `over` (`1885-1890`, `1963`).
- `OverrideDetalle` (`2052-2103`) muestra lo que el backend decidió y antes se tiraba: `capped` (el cap de seguridad disparó y no se ajustó nada), `skipped_manual`, `removed`.
- **`capAnulaLaDecision`** (`1873`): cuando el cap disparó, el checkbox de los `ausente_en_la_foto` no se muestra porque no tendría efecto (`1982-1983`, `1996-2001`).
- Botonera: **"Omitir la foto"** como salida de primera clase + "Aplicar (con N aprobados)" / "Aplicar sin los dudosos" (`959-984`).
- `aplicarTenencia` (`722-736`) → `POST /api/imports/confirm` con `{session_id, skip_row_indices: [], aprobar_tickers}`.

**Paso 6 — `STEP_DONE`** (`DoneStep`, `2839-2947`)
- Hero con contadores (posiciones, operaciones, movs de cash, conversiones, duplicadas omitidas) (`2855-2871`).
- Resultado de la foto (error / `nothing_to_do` / `to_seed.length`) (`2872-2880`).
- **Oferta de trial** (`TrialImportOffer`, `86-102`): único punto de la importación que lee `usePlanFeatures` (`87`) y sólo si `trial.can_start`.
- **Reconciliación de cash** por broker (`CashReconcileCard`, `2701-2828`): input del cash real, diff en vivo, y `POST /api/brokers/reconcile-cash {broker_name, target_cash}` (`2721-2723`, backend `main.py:10028`).
- Filas salteadas al persistir (`2919-2936`).

#### Cómo se presentan errores e incidentes

| Incidente | Dónde | Tono |
|---|---|---|
| Error de red/servidor en cualquier paso | banner rojo arriba del cuerpo (`775-780`) | error |
| Archivo con extensión inválida | banner ámbar dentro del dropzone, con consejo por tipo (pdf/xlsx/otro) (`1409-1421`, `1498-1503`) | warn |
| Archivo duplicado en la selección | mismo banner ("ya estaba en la lista — lo ignoramos") (`1417-1418`) | warn |
| Filas inválidas | sección roja "Errores (N)" con `Fila N` + mensaje (`2382-2396`) | error, no bloquea |
| Filas ya importadas | caja azul, se omiten solas (`2342-2356`) | info |
| Archivo idéntico a un import previo | caja ámbar "vas a duplicar" (`2281-2286`) | warn, **no bloquea** |
| Cash negativo | caja ámbar con lista por fila, sólo si no hay seed (`2361-2380`) | warn |
| Cap de la foto disparado | caja ámbar dentro de "Lo que no tocamos" (`2061-2074`) | warn |
| Foto falló después de confirmar los movimientos | línea en el `DoneStep` (`2874`) | warn |
| Filas salteadas al persistir | caja ámbar en `DoneStep` (`2919-2936`) | warn |

#### Rarezas del wizard

- `[V]` **`reset()` es código muerto**: definido en `ImportWizard.jsx:329-345`, nunca invocado (grep sin resultados fuera de la definición).
- `[V]` **`BLOCKED_IMPORT_PLATFORMS = {}`** (`189`): la feature entera (dropdown de plataformas bloqueadas + card de WhatsApp + `isBlockedPlatform`) está viva pero desactivada por config vacía. `withBlockedPlatforms` (`195-206`) no inyecta nada e `isBlockedPlatform` (`464`) es siempre `false`.
- `[V]` **Props que no se usan**: `IntroStep` recibe `effectiveCurrency` (`794`) y no lo destructura; destructura `isArsContext` (`1140`) y no lo usa. `UploadStep` destructura `isArsContext` (`1370`) y tampoco lo usa.
- `[V]` **`brokerLabel` muerto** en `IntroStep` (`1148`): se calcula y no se renderiza.
- `[V]` **`useCurrencyRouting` sale del preview** (`441: !!preview?.route_by_currency`), pero se le pasa a `UploadStep` (`815`) y a `MapStep` (`828`), que sólo se ven **antes** de que exista el preview. `[I]` En el primer paso de un import nuevo el aviso "(+ sub-broker USD)" / "Filas en USD → al sub-broker" nunca se ve; sólo aparece si el usuario vuelve atrás desde el preview (`895`, que no limpia `preview`).
- `[V]` **`TENENCIA_BROKER_BY_FORMAT`** (`158-175`) mapea `balanz_internacional` a un broker cuya foto todavía no existe. El propio comentario del código (`154-159`, `454-459`) explica que por eso el aviso usa `parserGroups` y no ese dict — pero el dict se sigue usando para decidir sobre qué broker aplicar la foto (`686`).
- `[V]` **`omitirTenencia` no se comunica**: setea `tenencia: { omitida: true }` (`740-741`) y `DoneStep` sólo contempla `error`, `nothing_to_do` y `to_seed` (`2872-2880`) → el que salteó la foto no ve ninguna confirmación de que se salteó.
- `[V]` **"Cancelar" después de escribir**: en `STEP_RECONCILE` los movimientos **ya están confirmados** (`confirm()` volvió antes, `697-699`), pero el footer sigue mostrando "Cancelar" (`911-918`) y no hay botón "Volver" para ese paso (`877-908` no lo contempla).
- `[V]` **`track('import_completed')` se emite dos veces posibles**: en la rama con foto (`697`) y en la rama sin foto (`710`) — no en el mismo flujo, pero `onConfirmed?.(data)` también sale en las dos (`698`, `711`), y en la rama con foto sale **antes** de que el usuario decida sobre la reconciliación.
- `[V]` `downloadTemplate` usa `fetch` crudo con `credentials:'include'` (`412-414`) en vez del wrapper `api.getBlob` que usa el resto de la app.
- `[V]` `PLATFORM_BASE_CURRENCY` (`108-118`) sólo lista cocos/binance/schwab/ibkr/bullmarket/iol/balanz_internacional. PPI, IEB, inviu y Balanz local caen a `null` → `effectiveCurrency` null → el resumen del `UploadStep` no muestra moneda.

---

### `frontend/src/components/import/TenenciaUpload.jsx` (215 líneas)

**Flujo de la "foto":** modal propio, tres estados internos (`preview===null` → formulario; `preview` → revisión; `done` → éxito).

1. Al montar trae `GET /api/brokers` y **filtra los siblings `· USD`** (`TenenciaUpload.jsx:29`), preseleccionando el que matchea `brokerMatch` (regex por caller: `/ppi/i`, `/cocos/i`, `/ieb/i`, `/iol/i`) o el primero de la lista (`31-32`).
2. **Analizar** → `POST /api/imports/tenencia/preview` con `file`, `broker` y (opcional) `format` (`40-44`).
3. Revisión: "Ya tenés N posiciones cargadas (no las tocamos) y vamos a completar M que faltaban (≈ valor por moneda)" (`128-134`) + tabla activo/cantidad/valor (`135-150`).
4. **Confirmar** → `POST /api/imports/confirm {session_id, skip_row_indices: []}` (`53`).

**Qué le advierte al usuario sobre pisar datos:**
- El `introText` lo pone el caller y es explícito sobre el modo: PPI/IEB/IOL dicen *"la foto MANDA … ajustamos lo que quedó de más o de menos (cerrando a costo, sin inventar ganancias). Por seguridad, si tocaría más de la mitad de tu cartera lo frenamos"* (`Imports.jsx:443, 482, 502`), Cocos dice *"si algo figura de menos no lo sacamos solos"* (`Imports.jsx:463`).
- `preview.override.reduced/removed` → lista explícita "bajamos de X a Y" / "lo sacamos" (`153-165`).
- `preview.override.capped` → *"El ajuste tocaría más de la mitad de tu cartera → lo frenamos por seguridad"* (`166-170`).
- `preview.warnings` → *"Leímos {doc} pero puede estar incompleto … Por eso no sacamos posiciones por 'ausencia' esta vez"* (`171-179`).
- `preview.avisos_escala` → canal propio "Este monto no nos cuadra" (`186-193`), separado a propósito del anterior (comentario `180-185`).
- `preview.not_in_snapshot` → *"Tenés N activo(s) en Rendi que no están en {doc} (¿vendidos?)"* (`194-198`).

**⚠️ Cálculo en el cliente:** `seedByCcy` / `seedValueLabel` (`64-68`) agrupa el valor a sembrar **por moneda** (no suma ARS+USD).

**Rarezas:**
- `[V]` **El botón dice siempre "Completar N posiciones"** (`207`), incluso cuando el override va a **reducir o sacar** activos: el label sólo cuenta `to_seed.length`.
- `[V]` A diferencia del wizard, acá **no hay** paso de aprobación por ticker: `doConfirm` manda `skip_row_indices: []` y ningún `aprobar_tickers` (`53`) — se aplica todo lo que el preview propuso.
- `[V]` El modal cierra al clickear el backdrop (`onClick={onClose}` en el contenedor, `71`), incluso a mitad de la revisión.
- `[V]` Usa clases `bg-rendi-card` / `bg-rendi-bg` / `border-white/10` (`72, 96, 128`) que no aparecen en el resto de los componentes de import (que usan `bg-bg-1`/`border-line`). Sistema de diseño mezclado.

---

### `frontend/src/components/import/WallbitConnect.jsx` (153 líneas)

- `GET /api/wallbit/status` al montar (`20`), `POST /api/wallbit/connect {api_key}` (`30`), `POST /api/wallbit/sync` (`42`), `DELETE /api/wallbit/disconnect` (`53`, con `window.confirm`). Backend: `main.py:31218/31238/31278/31310`.
- `onlyWhenConnected` (`61`): en `/imports` es card de gestión; el alta vive en el wizard.
- `[V]` **Disclaimer de responsabilidad siempre visible** (`115-120`): *"Es tu responsabilidad generar la key con permiso de lectura; Rendi no se hace responsable por keys creadas con permisos de operar"*, con el motivo técnico documentado: la API de Wallbit no expone los permisos de una key, así que no se puede bloquear por código.
- El input es `type="password"` (`102`) y la key no se guarda en el estado tras conectar (`setApiKey('')`, `31`).

### `frontend/src/components/import/BrokerInstructions.jsx` (363 líneas)

Widget informativo, **sin estado de red**. Un objeto `BROKERS` con logos SVG inline, `summary`, `steps[]` y `parserNote` por broker. `lockBrokerId` (usado por el wizard, `ImportWizard.jsx:1248, 1477`) fija el broker y oculta los chips de selección (`BrokerInstructions.jsx:238-239, 274`). Al pie, dos "opciones de mantenimiento" (manual desde Posiciones vs CSV mensual) (`332-358`).

`[V]` Rareza: la lista de brokers y sus instrucciones son **hardcode** (`BrokerInstructions.jsx:114-234`), completamente desacopladas del registry que devuelve `/imports/parsers/grouped`. Un broker nuevo en el backend no aparece acá hasta que alguien edite el archivo (el comentario de cabecera lo dice: *"Cuando el user pase los ejemplos reales de import, actualizar BROKERS"*, línea 6).

---

## `/novedades` → `frontend/src/pages/Novedades.jsx` (121 líneas)

### Qué muestra

Hub con **un solo header** y dos tabs (`Eventos` / `Noticias`) que montan las páginas hijas en modo `embedded`.

`[V]` `Novedades.jsx:39-44` ramifica primero por identidad: si `user.tier === 'advisor' && !clientCtx`, devuelve `<AdvisorNovedades/>` (radar cross-cliente, que fetchea `GET /api/advisor/radar/events?days=90` y `GET /api/advisor/radar/news?limit=30`, `AdvisorNovedades.jsx:50-51`). El resto ve `PersonalNovedades`.

`[V]` **Sólo se monta el panel activo** (`Novedades.jsx:116-117`) — no se fetchean las dos APIs al entrar.

### `/eventos` y `/noticias`: qué se monta y qué quedó huérfano

`[V]` Las dos rutas son `<Navigate … replace/>` (`App.jsx:212-213`) hacia `/novedades?tab=…`. `Novedades` monta `<Events embedded/>` / `<News embedded/>`.

`[V]` **Huérfano confirmado**: `Events` y `News` sólo se importan desde `Novedades.jsx:17-18`, y siempre con `embedded`. Por lo tanto **nunca** se ejecutan sus ramas `!embedded`:
- `Events.jsx:225-231`: el `PageHeader` "Eventos financieros" con su `AnalyzeButton screen="events"` de header.
- `News.jsx:146-152`: el `PageHeader` "Noticias" con su `AnalyzeButton screen="news"`.
- `Events.jsx:222` / `News.jsx:143`: el `containerClass = 'page-shell-wide'` (embedded devuelve `''`; el shell lo pone `Novedades.jsx:68`).

`[V]` Los CTA de briefing IA, en cambio, son **exclusivos** del modo embebido (`Events.jsx:261-274`, `News.jsx:185-198`) — sólo existen dentro de `/novedades`.

`[V]` Otro huérfano: `UpcomingEventsCard.jsx:4` documenta *"Link a /eventos para ver todo"* pero el link real ya apunta a `/novedades?tab=eventos` (`UpcomingEventsCard.jsx:55`). Sólo el comentario quedó viejo.

### Estado / contexto

`useAuth` + `useAdvisorContext` (`Novedades.jsx:20-21, 40-41`), `useSearchParams` para `?tab=` y `?sub=`. Al cambiar de sección borra `?sub` (`Novedades.jsx:63`).

### Gating por plan

`[V]` Ninguno en `Novedades.jsx`. El único gate del hub es de **identidad** (advisor sin cliente → radar del libro).

### Variante mobile

`[V]` No hay. `Novedades`, `Events` y `News` no importan `useIsMobile`; el responsive es puro CSS (grids `md:` / `sm:`).

---

### `Events` (embedded en `?tab=eventos`) → `frontend/src/pages/Events.jsx` (1058 líneas)

#### Qué muestra
Sub-tabs **Para ti** / **Populares** (`Events.jsx:60-63`, persistidos en `?sub=`), CTA de briefing IA, `SpotlightHero` (el próximo evento con tu cobro estimado), KPI strip de 3 celdas, controles de ventana (30D/90D/6M/1Y) y de tipo (Todos/Macro/Earnings/Dividendos/Bonos), `TimelineStrip` (barras por día/semana) y `EventAgenda` (agenda por día con cards expandibles).

#### De dónde saca los datos

`[V]` `loadAll` (`Events.jsx:116-146`) dispara **6 requests en paralelo** y uno más después:

| Endpoint | Línea |
|---|---|
| `GET /api/positions` | `121` |
| `GET /api/brokers` | `122` |
| `GET /api/config` | `123` |
| `GET /api/dolar` | `124` |
| `GET /api/events/portfolio?days={windowDays}` | `125` |
| `GET /api/events/popular?days={windowDays}` | `126` |
| `GET /api/prices?symbols=…` | `137` |
| `GET /api/events/earnings-expectations?symbol=…` | `813` (on-demand al expandir un earnings) |

`[V]` **Se refetchea todo al cambiar la ventana**: el `useEffect` depende de `windowDays` (`111-114`). Clickear "1Y" vuelve a pedir positions, brokers, config, dólar **y** precios, no sólo los eventos.

#### ⚠️ Cálculos hechos en el cliente

1. **Los eventos de BONOS los genera el frontend entero**, desde un cronograma teórico estático: `upcomingBondEvents(positions, {windowDays})` (`Events.jsx:193`) → `frontend/src/utils/upcomingEvents.js:48-96`, que usa `generateSchedule` + `getBondMeta`. Monto: `pmt.coupon * p.quantity / 100` (`upcomingEvents.js:67-69`). El backend **no** los conoce.
2. **`portfolioTotalUsd`** (`Events.jsx:152-158`): `Σ computeBrokerValue(posiciones del broker, prices, broker, tcValuacion, tcCedear, tcCripto)`.
3. **`tickerValueUsd`** (`161-173`): valor USD por ticker, sumando brokers.
4. **`tickerShares`** (`176-183`): cantidad por ticker, **sumando todos los brokers**.
5. **Impact %** = `tickerValueUsd.get(ticker) / portfolioTotalUsd` (`281-283`, `731-733`).
6. **`eventCobro`** (`934-947`): bono → `details.total`; ex-dividendo → `dividend_per_share × shares`.
7. **`buildDayBuckets`** (`548-591`): resolución adaptativa (1/2/7 días según ventana) y altura de barra ponderada por impacto cuando hay portfolio (`483-485`).
8. **`daysUntil`** (`1009-1015`), `formatCompact` (`1038-1044`), `collectPriceSymbols` (`1046-1057`, rail-aware ARS/.BA vs USD).

#### 🔴 Un bono en dos brokers: los nominales y el cobro no son del mismo universo

`[V]` `mergeEvents` deduplica por `${ticker}:${eventType}:${eventDate}` (`upcomingEvents.js:117-129`) — se queda con **un solo** evento aunque `upcomingBondEvents` haya generado uno por broker (genera uno por posición: `upcomingEvents.js:54-93`). Ese evento sobreviviente lleva el `details.total` de **un** broker.

Mientras tanto, `tickerShares` suma la cantidad de **todos** los brokers (`Events.jsx:176-183`), y la línea "personal" de la agenda imprime los dos juntos (`Events.jsx:753`):
```js
`tenés ${formatCompact(cobro.shares || shares || 0)} nominales → ~+${…}${formatCompact(cobro.amount)}`
```
con `cobro.shares = sharesMap.get(ticker)` (`Events.jsx:937`).

**Consecuencia:** un bono con 10.000 VN en Cocos y 10.000 en IOL muestra *"tenés 20.000 nominales → ~+US$ X"* donde X se calculó con 10.000. El mismo problema llega a `/home` vía `UpcomingEventsCard` (usa el mismo `mergeEvents`, `UpcomingEventsCard.jsx:40`).

#### 🔴 `EmptyState` con la prop equivocada

`[V]` `Events.jsx:334-341` pasa `subtitle=`, pero `EmptyState` sólo acepta `description` (`frontend/src/components/EmptyState.jsx:21-29, 45-47`). El texto explicativo ("No hay pagos, earnings ni dividendos del portfolio en los próximos N días") **se descarta silenciosamente**: el usuario ve sólo el título "Sin eventos en este rango". Mismo bug en `News.jsx:282-288`.

#### Gating por plan
`[V]` Ninguno directo. `AnalyzeButton` (`229`, `272`) e `InlineAIButton` (`785-790`) delegan la cuota al backend (429 → `UpgradePromoCard`).

#### Rarezas
- `[V]` **`renderAmount` es código muerto**: definido en `Events.jsx:906-928`, sin un solo llamador (grep confirma una única aparición).
- `[V]` **`Eye` importado y no usado** (`Events.jsx:23`).
- `[V]` `EventTableSkeleton` (`627-655`) todavía pinta el esqueleto de la **tabla densa** que se retiró en el "clean pass 2026-07" a favor de la agenda (`658-661`). El loading no se parece a lo que después aparece.
- `[V]` KPI "Confirmados %" (`416-420`) mide `e.confirmed`, y **todos los eventos de bonos tienen `confirmed:false`** por diseño (`upcomingEvents.js:89`, "schedule teórico"). Una cartera de puros bonos siempre muestra 0%.
- `[I]` `portfolioTotalUsd` y `tickerValueUsd` no listan `tcCedear`/`tcCripto` en las deps del `useMemo` (`Events.jsx:158, 173`) aunque los usan. Normalmente da igual porque `tcValuacion` cambia junto con `dolar`; pero si `pickFinancialRate(dolar, …)` devuelve null y cae al fallback `config.tc_blue`, `tcValuacion` queda fijo mientras `tcCripto = dolar?.cripto?.venta` cambia → valores stale. Me agarro de las líneas `149-151`.
- `[V]` `KpiCell` está definido **dos veces con el mismo nombre y distinta forma** en el árbol de esta auditoría: `Events.jsx:426-439` y `Operations.jsx:768-780`. No colisionan (son locales), pero divergen en tono y markup.

---

### `News` (embedded en `?tab=noticias`) → `frontend/src/pages/News.jsx` (591 líneas)

#### Qué muestra
Sub-tabs **Para ti** / **Mercado**, CTA de briefing IA, chips de filtro por **ticker** (sólo "Para ti"), por **tag** y por **sentimiento** (Todos/Positivo/Negativo), y una grilla con una noticia "Destacada" + el resto agrupado por frescura (Hoy / Ayer / Esta semana / Antes).

#### De dónde saca los datos
`[V]` `loadAll` (`News.jsx:82-103`): `GET /api/news/portfolio?limit=25` y `GET /api/news/market?limit=25`, **ambos en paralelo al montar** (los dos tabs se traen aunque se vea uno). Backend: `main.py:6974` y `6913`.

#### ⚠️ Cálculos hechos en el cliente
- `visibleNews` (`106-118`): filtros de ticker/tag/sentimiento.
- `availableTags` (`121-128`) y `portfolioTickers` (`131-138`): conteos derivados del feed.
- `groupByFreshness` / `freshnessBucket` (`332-350`): buckets calculados con la hora local del navegador.
- `splitTitleSource` (`568-574`): parte el título de Google News en `titular` + `medio` buscando el último `" - "`.
- `weightLabel` (`44-47`): "afecta X% de tu cartera" a partir de `weight_pct` **que sí manda el backend**.
- `formatNewsDate` (`576-591`): "12m / 3h / 2d".

#### Rarezas
- `[V]` **`computeKpis` casi entero es cómputo muerto**: calcula `uniqueTickers`, `uniqueSources`, `todayCount`, `lastRelative`, `lastSource` (`520-546`) y de todo eso el render sólo usa `kpi.total` (`193`). El KPI strip se retiró (comentario `200-201`) y la función quedó.
- `[V]` Mismo bug de `EmptyState subtitle=` que Events (`282-288`).
- `[V]` Las URLs externas pasan por `safeExternalUrl` (`360`, `442`) — bien.
- `[V]` `NewsGrid` toma la **primera** noticia de `visibleNews` como "Destacada" (`308`), o sea que la destacada cambia al aplicar un filtro.
- `[V]` `key={n.url}` (`322`, `45` en `TopNewsCard`): si dos noticias comparten URL, React tira warning y una se pierde.

---

## `/alertas` → `frontend/src/pages/Alertas.jsx` (50 líneas) + `components/alerts/AlertsManager.jsx` (481)

### Qué muestra
`Alertas.jsx` es un wrapper: `PageHeader` + una de dos cosas.
- `[V]` Si `plan.isAdvisor && !clientCtx` → `<AdvisorAlerts/>` (alertas del **libro**, `Alertas.jsx:22, 47`).
- Si hay `clientCtx`, banner explicativo: *"Las alertas que crees en esta cuenta te llegan a vos … con el nombre de {cliente} adelante"* (`41-46`).
- El resto ve `<AlertsManager plan={plan} prefill={prefill}/>`.

`[V]` Al entrar llama `markSeen()` del `AlertsContext` (`Alertas.jsx:26`), que apaga el puntito del sidebar vía `POST /api/alerts/events/seen` + `POST /api/advisor/alerts/events/seen` (`frontend/src/contexts/AlertsContext.jsx:37-48`).

`[V]` **Prefill por query string**: `/alertas?new=MSFT.BA&ccy=ARS` abre el formulario ya cargado (`Alertas.jsx:28-31`). Lo dispara el menú de una posición (`frontend/src/pages/Positions.jsx:631-634`, que arma el `priceSymbol` rail-aware).

### Cómo se crea una alerta

`AlertsManager.submit` (`120-167`):
1. Parseo tolerante al formato argentino con `parseNum` (`38-47`): `'1.234,56' → 1234.56`, `'9.000' → 9000`.
2. Validaciones cliente: pct sin ningún umbral → error; pct con scope ticker sin símbolo → error; price_target sin `thr > 0` o sin símbolo → error (`127-133`).
3. Payload (`135-145`) → `create()` → `POST /api/alerts` (`frontend/src/hooks/useAlerts.js:32`, backend `main.py:33432`).
4. Si la respuesta trae `resolved === false`, banner "No encontramos el precio de X ahora" (`151`, `207-215`).
5. Si el canal incluye push y todavía no hay permiso, dispara `push.subscribe()` (`154-156`).
6. `403` con `payload.upgrade` → `UpgradePromoCard`-lite inline (`157-163`, `189-204`).

### Tipos de alerta

| Tipo | `kind` | Parámetros | Plan |
|---|---|---|---|
| Precio objetivo | `price_target` | `symbol`, `direction` (`above`/`below`), `threshold`, `currency` | todos |
| Variación % | `pct_move` | `scope` (`holdings` = toda la cartera / `ticker`), `up_pct` y/o `down_pct` (asimétricos), `baseline` (`set_price` = "desde ahora" / `prev_close` = "en el día") | **Plus+** |

`[V]` Además: `channel` ∈ `push` / `email` / `both`, y `repeat` ∈ `once` / `always` (`303-315`).

### Cómo se notifica
`[V]` Frontend: `AlertsContext` refresca al volver a la pestaña con throttle de 60s (`AlertsContext.jsx:53-65`) y suma alertas propias + del libro en un solo `unseenCount` (`68`). El feed "Últimos avisos" muestra los 6 últimos `events` (`AlertsManager.jsx:365-378`).
`[V]` Backend: `backend/alerts_engine.py:265-295` (`_deliver`) manda Web Push (`main._send_push_to_user`) y/o email (`billing.emails`) según `channel`.

### Gating por plan
`[V]` Dos gates, ambos espejados del backend:
- **Cantidad**: `alertsMax = plan.limit('alerts_max')`; `atLimit` (`AlertsManager.jsx:77-78`) hace que "Nueva alerta" abra el upsell en vez del form (`180`). Backend: free 3, plus 25, pro/advisor/admin sin tope (`backend/ai/plan.py:50, 70, 86, 106, 122`).
- **Capacidad**: `canPct = plan.can('alerts.pct_move')` (`76`); el botón "Variación %" muestra el badge `Plus` y abre el upsell al clickearlo (`115`, `223`, `451`). Backend: `False` en free, `True` desde plus (`plan.py:59, 79`).

### 🔴 El selector de moneda de "Precio objetivo" no hace nada

`[V]` El formulario ofrece `US$` / `$ ARS` (`AlertsManager.jsx:242-248`) y lo manda como `currency` (`144`). En el backend, `currency` se usa **solamente para formatear el mensaje** (`backend/alerts_engine.py:226-227` → `_fmt`); la condición compara el `threshold` contra el precio crudo que devuelve `_prices_for` (`condition_met`, `alerts_engine.py:125-137`), que para un símbolo `.BA` viene en pesos.

**Consecuencia:** una alerta "MSFT.BA ≥ US$ 500" dispara cuando el precio en **pesos** cruza 500, y el mail dice "US$ 500". El campo es una afordancia falsa. `[V]` El panel de contexto de arriba ya deriva la moneda por el sufijo (`priceCcy = priceSym.endsWith('.BA') ? 'ARS' : 'USD'`, `97`) — o sea, el componente ya sabe la respuesta correcta y aun así ofrece elegir.

### 🔴 "El email siempre llega" no es cierto si elegís Push

`[V]` `AlertsManager.jsx:308-311` dice literalmente *"El email siempre llega. El push es un extra…"*, pero el mismo formulario permite `channel='push'` (`305`) y `_deliver` sólo manda mail `if channel in ("email","both")` (`backend/alerts_engine.py:287`).

### Rarezas
- `[V]` `TickerCombobox` (`386-444`) busca sólo en `POPULAR_TICKERS` pero **acepta cualquier texto tipeado** (comentario `383-385`) — de ahí el warning de "no resolvió precio".
- `[V]` El upsell linkea a `/config?tab=planes` (`198`), pero `planes` está en `CTX_HIDDEN_TABS` (`frontend/src/pages/Config.jsx:275`). `[I]` Un asesor dentro del contexto de un cliente que toque ese link cae en un tab oculto.
- `[V]` `AlertsManager` no tiene rama mobile ni edición de alertas: sólo pausar/activar (`PATCH /api/alerts/{id}`, `useAlerts.js:38`) y borrar (`DELETE`, `43`), sin confirmación.
- `[V]` El feed de eventos corta en 6 sin paginar ni "ver más" (`370`).

---

## `/mas` → `frontend/src/pages/More.jsx` (328 líneas)

### Qué muestra
Menú mobile: sección **Asistente** (abre Rendi AI), grupos de navegación, **Notificaciones push**, y **Cuenta** (Configuración / Recomendaciones / Cerrar sesión).

- `[V]` Grupos: "Tu portfolio" (Dashboard, Cartera, Movimientos, Importar CSV, Alertas) y "Análisis" (Métricas, Calidad de cartera, Perfil de inversor, Novedades) (`More.jsx:25-45`), más "Plan Asesor" y "Admin" condicionales (`63-82`).
- `[V]` **Un asesor en su propio nivel pierde los dos grupos retail enteros** (`73`: `...(atOwnLevel ? [] : GROUPS.map(...))`) — o sea, en mobile no tiene forma de llegar a `/imports` desde el menú.

### De dónde saca los datos
`[V]` La página en sí **no hace fetch**. Lo único de red es `usePushNotifications()` (`204`), que gestiona la suscripción y el `sendTest`.

### Estado / contexto
`useAuth` (`48`), `useCoachDrawer` (`49`), `useAdvisorContext` (`50`), `useToast` (`200`), `usePushNotifications` (`201-204`).

### 🔴 Todos los toasts de esta pantalla son no-ops

`[V]` `More.jsx` llama `toast?.show?.({ kind, text })` en 6 lugares (`230, 233, 236, 245, 247, 250`). El contexto de Toast expone **`{ push, dismiss }`** y no tiene `show` (`frontend/src/components/Toast.jsx:48, 57-68`; grep de `show` en ese archivo: sin resultados). Como el llamado usa optional chaining (`?.`), **falla en silencio**.

**Consecuencia:** activar/desactivar notificaciones push y mandarse un push de prueba desde `/mas` **nunca muestran confirmación ni error**. El único feedback que queda es el label del botón y el bloque `error` del hook (`320-324`).

`[V]` El mismo antipatrón está en `frontend/src/pages/MobileSearch.jsx:134,136` y `frontend/src/pages/PositionsMobile.jsx:1785`.

### Gating por plan
`[V]` Ninguno. Los items se filtran por `item.adminOnly` (`75`) — pero **ningún item de `GROUPS` define `adminOnly`** (`More.jsx:25-45`), así que ese filtro es un no-op.

### Rarezas
- `[V]` **Imports sin usar**: `BarChart3`, `Target` (`More.jsx:10-11`) no aparecen en el JSX.
- `[V]` "Rendi AI" no está en ningún grupo: se llega por el botón de la sección Asistente, que llama `coachDrawer.open()` → navega a `/ai` (`101`, `CoachDrawerContext.jsx:29-33`).
- `[V]` El item "Movimientos" apunta a `/operaciones` (`31`) pero el nav desktop y el `PageHeader` de esa página la llaman "Operaciones" (`Operations.jsx:389`).

---

## `/ai` → `frontend/src/pages/RendiAI.jsx` (183) + `components/AICoach.jsx` (675) + `components/ai/` (11 archivos)

### Qué muestra
Chat a pantalla completa: topbar con la marca, chip de contexto ("Viendo tu cartera · N posiciones · M brokers") y "Nueva conversación"; el cuerpo es `<AICoach fullHeight/>`.

### Cómo se manda el contexto de la cartera

`[V]` `RendiAI` arma el snapshot **en el cliente** (`RendiAI.jsx:56-87`) con 4 requests en paralelo:
- `GET /api/positions`, `GET /api/monthly`, `GET /api/brokers`, `GET /api/operations` (esta última con `.catch(() => [])`, "no crítico si falla", `65`).
- Las operaciones se **cortan a 100** (`69`) y se agrega un `summary` calculado en el navegador (`buildSummary`, `162-183`: `total_invested_usd`, `open_positions_count`, `cash_lines_count`, `months_tracked`, `realized_pnl_usd_lifetime`, `deposits_lifetime`, `withdrawals_lifetime`).
- El snapshot completo viaja en el body de `POST /api/ai/chat` (`AICoach.jsx:245` → `api.chatStream({messages, snapshot})` → `frontend/src/utils/api.js:304-310`).

`[V]` **Book-mode** (asesor en su propio nivel): no se fetchea nada y se manda `BOOK_SNAPSHOT = {}` (`RendiAI.jsx:26, 37, 150`), porque el backend arma el contexto del libro server-side.

`[V]` El snapshot se refresca solo cuando llega el evento `rendi:portfolio-changed` (`RendiAI.jsx:90-94`), que dispara el propio chat al escribir (`AICoach.jsx:253-255`).

### ¿Hay streaming?

`[V]` Sí, SSE propio (no la lib de nadie): `api.chatStream` (`frontend/src/utils/api.js:288-383`) hace `fetch('/api/ai/chat', {stream:true})`, parsea frames separados por `\n\n` y despacha eventos `delta` / `reset` / `done` / `error`.
- `[V]` **Centinela de fin**: si el reader termina sin un frame terminal, tira un error con `truncated:true` (`api.js:377-381`) y el chat avisa *"La respuesta se cortó a mitad de camino"* (`AICoach.jsx:284-288`). Sin eso, un corte de Vercel a 30s se leía como respuesta completa.
- `[V]` **`reset`**: cuando el turno termina en `tool_use`, lo streameado era el preámbulo → se borra la burbuja y vuelve el loader (`api.js:353-357`, `AICoach.jsx:219-226`).
- `[V]` **Guard anti-doble-envío**: `sendingRef` síncrono + `sending` de estado (`AICoach.jsx:125-126, 181-183`), y `AbortController` que se cancela al desmontar o al tocar "Nuevo" (`130-131, 348`).
- `[V]` La conversación **persiste** en `sessionStorage` (`loadChatSession`/`saveChatSession`, `107, 135`) pero al modelo sólo viaja `sendWindow(newMessages)` (`245`).

### ¿El chat puede registrar operaciones? ¿Dónde está la confirmación humana?

`[V]` **Sí, escribe en la base.** El input está habilitado para **todos** los tiers: Pro = chat libre, Free/Plus = "registrá: compré 2000 USD de BTC" (`AICoach.jsx:613-635`, placeholder por tier en `629-631`). El propio comentario lo dice: *"El gate del CONTENIDO es server-side (whitelist + detector de intención de registro)"* (`336-338`).

**La confirmación es de dos capas:**

1. **UI — `ConfirmBlock`** (`frontend/src/components/ai/AIBlocks.jsx:383-411`): el modelo emite un bloque `confirm` con las filas del borrador; el botón "Confirmar" **no** llama a ningún endpoint de escritura: manda el texto `'sí, confirmá'` como si el usuario lo tipeara (`398`). "Corregir" dispara un evento global que enfoca el input (`404`, escuchado en `AICoach.jsx:139-143`).
   `[V]` Los bloques de turnos viejos se **congelan**: `interactive={isLastMsg && !loading && !sending}` (`AICoach.jsx:501`) y cada bloque además se auto-bloquea con `sent` (`AIBlocks.jsx:323-324, 384-385`).

2. **Servidor — enforcement real** (`backend/main.py:23205-23231`): el draft vive en `_TRADE_DRAFT[uid]` (server-side, no en un token que viaja al modelo) y *"el draft se estampa con el request_id que lo creó; confirmar SOLO se acepta desde un request DISTINTO … Así el modelo NO puede auto-confirmarse en el mismo turno"* (`23214-23219`). Además se ejecuta **el payload guardado, no lo que reenvía el modelo**, con claim atómico pop-first (`23220-23222`).

Es decir: la garantía de "hubo un humano" es del backend; el `ConfirmBlock` es la superficie cómoda para producir ese segundo turno. **No hay** un `window.confirm()` ni un modal bloqueante en el frontend.

`[V]` Cuando el turno escribió, el stream manda `portfolio_changed` y el frontend emite `rendi:portfolio-changed` (`api.js:361`, `AICoach.jsx:253-255`).

### Bloques visuales de la respuesta

`[V]` `AIBlocks.jsx:36-48` despacha 8 tipos: `compare`, `alloc` (donut SVG), `scenario`, `table`, `actions` (deep-links ya whitelisted por el parser), `form` (formulario de registro), `confirm`, `client_list` (ranking de clientes del asesor, con botón "Entrar" que setea el contexto de cliente y navega, `237-240`). El texto estructurado se parsea con `parseStructured` (`frontend/src/utils/aiStructured.js`) y se renderiza como veredicto + titular + prosa + stats + bloques + fuentes + repreguntas (`AICoach.jsx:456-528`).

### Gating por plan
- `[V]` `canChatFree = isPro || isAdmin || bookMode` (`AICoach.jsx:99`). Free/Plus ven chips pre-armados (`DEFAULT_SUGGESTED`, 12 preguntas que deben matchear la whitelist del backend, `36-49`) y el input queda para registrar operaciones.
- `[V]` Cuota: `GET /api/ai/usage` al montar y tras cada respuesta (`149, 257`), mostrada como "N consultas restantes" (`648-652`).
- `[V]` `429`/`403` con `detail.upgrade.available` → `UpgradePromoCard` en lugar del banner rojo (`298-300, 546-553`).
- `[V]` Banda inferior de upsell cuando `!canChatFree` (`658-671`), con `<a href="/planes">` — **navegación dura**, no `<Link>`: recarga la SPA entera.

### Variante mobile
`[V]` `RendiAI` no bifurca por anchura; usa `h-dvh` + `pb-16 sm:pb-0` para dejar lugar a la tab-bar (`RendiAI.jsx:100`). El chip de contexto es `hidden md:inline-flex` (`113, 118`) → en mobile **no se ve** qué cartera está mirando la IA.

### Rarezas del subsistema IA
- `[V]` **`frontend/src/components/ai/AICoachDrawer.jsx` (190 líneas) es huérfano**: no lo importa nadie (grep en `frontend/` sólo devuelve su propia definición, la mención en un comentario de `RendiAI.jsx:3` y una entrada en `frontend/src/__design__/design-baseline.json:134`). Además está **roto por API**: lee `isOpen` y `close` de `useCoachDrawer()` (`AICoachDrawer.jsx:17`), y el contexto actual ya no expone `isOpen` (`frontend/src/contexts/CoachDrawerContext.jsx:35-41`).
- `[V]` `AnalysisDrawer` recibe `autoload: open` (`AnalysisDrawer.jsx:37`) y el hook dispara `POST /api/ai/analyze` al montar (`frontend/src/hooks/useAIAnalysis.js:126-129`). Como los botones sólo montan el drawer al clickear (`AnalyzeButton.jsx:42, 65`; `InlineAIButton.jsx:73`), el análisis efectivamente es on-demand — pero **se consume cuota apenas se abre el drawer**, sin un segundo click.
- `[V]` `refresh()` hace `DELETE /api/ai/cache/{screen}` + reanalyze (`useAIAnalysis.js:69-78`) → cada "Refrescar" gasta una consulta más.
- `[V]` Follow-ups capeados a **1** por análisis (`MAX_FOLLOWUPS_PER_ANALYSIS`, `useAIAnalysis.js:23`), y cada uno cuesta cuota (`92-96`).
- `[V]` `FormBlock`/`ConfirmBlock` ponen `sent=true` al enviar y **nunca lo revierten** (`AIBlocks.jsx:327, 398`): si el turno falla, el bloque queda para siempre en "Enviando…" / "Registrando…".
- `[V]` `AICoach` importa `Sparkles, RotateCcw` etc. que sólo se usan en la rama `!fullHeight` (`367-411`), que en `/ai` nunca se renderiza — el header embebido sólo aparece si alguien monta `<AICoach>` sin `fullHeight`, cosa que hoy no hace nadie (grep: sólo `RendiAI.jsx:150,152` y el huérfano `AICoachDrawer.jsx:12`).
- `[V]` `AskAIAbout` escucha el evento `storage` para el flag de discovery (`AskAIAbout.jsx:53-57`), pero `markAIDiscovered` emite un evento custom `'ai-discovered'` (`AIDiscoveryBanner.jsx:29`) **que `AskAIAbout` no escucha** — sólo lo escucha `OnboardingChecklist`. Dentro de la misma pestaña, los `✦` que ya estaban montados siguen en modo "pre-discovery" (pulse permanente) hasta un remount.

---

## Componentes sueltos del alcance

### `frontend/src/components/AddPositionFlow.jsx` (944 líneas) — alta manual, paso 1

**Qué pide.** Es el **selector**, no el formulario: 2 o 3 pasos según venga `initialBroker` (`AddPositionFlow.jsx:70-72`).
1. **Broker** (`StepBrokerPicker`, `323-394`) — o "Plazo fijo", que sale de este flujo y abre `PfFormModal`.
2. **Tipo de activo** (`Step1AssetType`, `399-…`) — 10 categorías (`CATEGORIES`, `50-65`) + FCI dinámico (`124-134`), con buscador general sobre el universo aplanado (cap 40 resultados, `420-426`), "En tu cartera" y "Sugeridos" (`494-528`).
3. **Ticker** — 4 pickers distintos según categoría (`257-265`): `StepFciPicker`, `StepLetraPicker`, `StepOtroPicker`, `Step2TickerPicker`.

**Qué valida en el cliente.**
- `[V]` **Letras**: `isLetraTicker(upper)` (regex de `frontend/src/utils/sections.js`) y, si valida, decodifica el vencimiento con `decodeLetraDate` (`31-36`, `786-787`).
- `[V]` **"Otro"**: exige código no vacío **y** tipo elegido (`listo = codigo.length >= 1 && !!tipo`, `686`). Devuelve la categoría REAL elegida (`690`), así el resto del sistema lo trata como si viniera de una lista.
- `[V]` **Bonos**: si la búsqueda no encuentra nada, ofrece "Agregar {QUERY} como bono/ON" con ≥2 caracteres (`617-625`).
- `[V]` **FCI por moneda del broker**: un fondo USD no se ofrece en un broker ARS (`118-122`).
- `[V]` **Desambiguación de símbolo**: `resolvePick` (`155-162`) — AAPL en broker ARS → CEDEAR, en broker USD → acción.

**A qué endpoint postea.** `[V]` **A ninguno.** Sólo lee `GET /api/fci/catalog` (`85`) y `GET /api/positions` (`98`). Termina llamando `onAssetSelected({asset, name, category, broker})` (`209-211`). El POST real lo hace el padre: `frontend/src/pages/Positions.jsx:639-642` mapea `category → asset_type` y abre el form, y `save()` (`Positions.jsx:738-798`) hace `POST /api/positions` (`779`) o `PUT /api/positions/{id}` (`777`).

**Qué valida el padre antes de postear** `[V]` (`Positions.jsx:761-771`): activo no vacío, `quantity > 0`, y `buy_price` o `invested` presente. Con toast, sin cerrar el modal.

**Qué se recalcula después.** `[V]` `loadAll()` del padre (`Positions.jsx:784`) y el evento `track('position_add_completed')` (`781`). El recálculo de P&L / cartera es server-side.

**Rarezas.**
- `[V]` `AddPositionFlow` fetchea `GET /api/positions` completo sólo para armar la lista "En tu cartera" (`96-112`), aunque el padre ya tiene las posiciones cargadas.
- `[V]` El contrato `TIPOS_OTRO[].cat → CATEGORY_ASSET_TYPE[cat]` cruza dos archivos y está **testeado** justamente por eso (`frontend/src/components/AddPositionFlow.test.js`, que lee los mapas del fuente para no quedar viejo).
- `[V]` En `PositionsMobile` se carga con `lazy()` por peso (`PositionsMobile.jsx:31`); en `Positions.jsx` no (`Positions.jsx:11`).

### `frontend/src/components/PfFormModal.jsx` (409) — alta de plazo fijo
- `[V]` 2 pasos: `BankPicker` (buscable, con logo y TNA de hoy) → formulario. `GET /api/pf/banks` (`148`, backend `main.py:9341`).
- `[V]` Al elegir banco **siempre** prefillea la tasa (`156-162`, el comentario aclara que antes sólo lo hacía la primera vez).
- `[V]` Salida "Seguir sin banco de la lista" → banco y tasa a mano (`164-169`).
- `[V]` Preview en vivo con `computePf` (`171-184`, `frontend/src/utils/valuation.js`) — **cálculo cliente**.
- `[V]` Validaciones: banco no vacío (vuelve al paso 1), `capital > 0`, `tasa > 0`, `plazo > 0` (`192-195`). → `POST /api/plazos-fijos` (`198`, backend `main.py:9119`).
- `[V]` Rareza: `daysBetween` (`22-27`) y `plazoMode` (`139`) existen; el modo "por fecha" está en el estado pero conviene revisar si el render lo expone en las 140 líneas siguientes — la aritmética de fechas es local para evitar shift de timezone (`16-27`).

### `frontend/src/components/BondCashflowModal.jsx` (475) — registrar cupón/amortización
- `[V]` Pre-llenado desde el cronograma teórico (`nextPaymentForPosition`, `71`) o desde el pendiente concreto del inbox, que **tiene prioridad absoluta** porque el cronograma sólo devuelve futuros (`62-69`, comentario `56-61`).
- `[V]` **Fecha**: sólo se siembra la del cronograma si ya pasó; si no, hoy (`95-97`). El comentario documenta el incidente: sembrar 09/01/2027 hizo que un usuario confirmara 25 cupones con esa fecha (`91-94`).
- `[V]` **Cross-currency**: si el bono paga en otra moneda que el broker, el campo arranca **vacío** y se ofrece un chip con la conversión al dólar de la fecha del pago (`101-116`, `154-163`). El comentario cuenta el bug que evita: sembrar el número en USD bajo una etiqueta ARS registraba 79 pesos donde se cobraron 79 dólares (`110-113`).
- `[V]` **Sello del FX**: sólo se manda `fx_to_usd` si el monto salió del chip **y** no se editó ni cambió la fecha (`164-170`, `213`).
- `[V]` `POST /api/bonds/cashflow` con `{broker, asset, flow_type, amount, date, commissions, notes, decrement_quantity, face_amortized?, fx_to_usd?}` (`198-215`, backend `main.py:10346`).
- `[V]` `decrement_quantity` sólo aplica a amortizaciones de bonos amortizantes y por default off si hay cross-currency (`133-138`).

### `frontend/src/components/PendingCashflowsBanner.jsx` (162) — inbox de cobros
- `[V]` No hace fetch: recibe `pending` ya calculado por `Positions.jsx` (`Positions.jsx:1840`).
- `[V]` **Confirmar directo** sólo para cupones **same-currency** (`sameCurrency`, `19-22`; `directOk`, `99`); todo lo demás pasa por el modal ("Revisar y confirmar"), con `title` que explica por qué (`145-147`).
- `[V]` "Saltar" (`onSkip`) → `POST /api/bonds/cashflow/skip` (documentado en la cabecera, `10`; backend `main.py:10714`).
- `[V]` Muestra "venció hace N días" y "estimado por tus N nominales" (`107-120`).

### `frontend/src/components/SplitRatioBanner.jsx` (149)
- `[V]` **Self-contained**: `GET /api/positions/split-check` al montar (`25`, backend `main.py:8967`), silencioso si falla (`27`).
- `[V]` Ajuste de un click: `POST /api/positions/{pid}/adjust-ratio` **sin body** — "el server re-deriva el split (no confía en factor/ex_date del cliente)" (`37-38`, backend `main.py:8877`). Luego dispara `rendi:portfolio-changed` (`39`).
- `[V]` **Distingue evidencia**: cuando la detección se apoya en el precio (`evidence === 'precio'`) el copy PREGUNTA en vez de afirmar y advierte *"Confirmá solo si la cantidad que ves es la de antes del split … ajustar la multiplicaría de más"* (`68-74`, `114-121`).
- `[V]` `ratioLabel` maneja split inverso (`14`).

### `frontend/src/components/UpcomingEventsCard.jsx` (117) y `TopNewsCard.jsx` (101)
- `[V]` Las dos viven en `/dashboard` (`Dashboard.jsx:1342, 1344`), no en Novedades.
- `[V]` `UpcomingEventsCard`: `GET /api/events/portfolio?days=30` (`31`), merge con los bonos calculados en cliente (`38-41`), máximo 5, y **no se renderiza si no hay nada** (`44`). Link a `/novedades?tab=eventos` (`55`). Hereda el problema de dedup cross-broker descrito arriba.
- `[V]` `TopNewsCard`: `GET /api/news/portfolio?limit=6` y corta a 3 (`22-23`); tampoco se renderiza vacía (`28`). Link a `/novedades?tab=noticias` (`38`).
- `[V]` `formatNewsDate` está **duplicado** entre `TopNewsCard.jsx:86-101` y `News.jsx:576-591`, con textos distintos ("hace 3h" vs "3h").
- `[V]` `splitTitleSource` también está duplicado: inline en `TopNewsCard.jsx:53-55` vs la función de `News.jsx:568-574`.

### `frontend/src/components/BrokerManager.jsx` (366)
- `[V]` `POST /api/brokers` (`65`), `PUT /api/brokers/{id}` (`87`), `DELETE /api/brokers/{id}` (`97`) y `DELETE /api/brokers/{id}?force=true` (`122`).
- `[V]` **Borrado en dos pasos**: el primer DELETE sin `force` devuelve 409 con `counts`; ahí se arma un `confirm()` nativo que enumera posiciones/operaciones/entradas mensuales/imports y **advierte sobre el sibling USD** (`101-119`).
- `[V]` **Gate Free**: 403 con `payload.detail.upgrade` → `UpgradeModal` + `track('feature_blocked_clicked')` (`71-79`). Tras crear/borrar llama `refreshPlanFeatures()` (`69, 99`).
- `[V]` Agrupa por cuenta con `groupBrokersIntoAccounts` y respeta la preferencia `localStorage['rendi_cuentas_separadas']` para no contradecir a las tablas de Cartera (`46-55`).
- `[V]` **Rareza**: usa `alert()` nativo para los errores (`80`, `105`) en vez del sistema de Toast que usa el resto de la app.

### `frontend/src/components/TickerSearch.jsx` (290)
- `[V]` Combobox con categorías, catálogo FCI cacheado a nivel módulo y pedido **al abrir** (`fetchFciOnce`, `37-49`, `81`).
- `[V]` Ranking: `startsWith` del ticker > `includes` del ticker > `includes` del nombre, cap 300 (`99-108`).
- `[V]` Permite ticker manual fuera de la lista (`showManual`, `111-112`).
- `[V]` La prop `currency` **sólo** decide qué categorías se sugieren (`151`), no filtra resultados.
- `[V]` **Colisión de nombre**: hay dos componentes distintos llamados `TickerSearch` — `components/TickerSearch.jsx` (API `value`/`onChange`, usado por Operations y Positions) y `components/fundamentals/TickerSearch.jsx` (API `onSelect`/`autoFocus`, usado por las 3 vistas de Fundamentals). Confirmado con `ls` + cabecera del segundo.

---

## Tabla resumen — endpoints por pantalla

| Pantalla | Lecturas | Escrituras |
|---|---|---|
| `/operaciones` | `/operations`, `/brokers`, `/movements` | `POST`/`PUT`/`DELETE /operations`, `/operations/undo/{t}`, `DELETE /assets/history`, `/assets/undo/{t}`, `DELETE /movements/{id}` |
| `/imports` | `/imports`, `/brokers`, `/wallbit/status` | `/imports/{id}/revert(?nuclear=1)`, `/imports/{id}/redo`, `/imports/recalc-pnl`, `/imports/wipe-broker` |
| ImportWizard | `/imports/parsers/grouped`, `/brokers`, `/imports/mappings`, `/imports/template` | `/imports/inspect`, `/imports/classify-tenencia`, `/imports/preview`, `/imports/confirm`, `/imports/tenencia/preview`, `/imports/mappings` (POST/DELETE), `/brokers` (POST), `/brokers/reconcile-cash` |
| TenenciaUpload | `/brokers` | `/imports/tenencia/preview`, `/imports/confirm` |
| WallbitConnect | `/wallbit/status` | `/wallbit/connect`, `/wallbit/sync`, `DELETE /wallbit/disconnect` |
| `/novedades` → Eventos | `/positions`, `/brokers`, `/config`, `/dolar`, `/events/portfolio`, `/events/popular`, `/prices`, `/events/earnings-expectations` | — |
| `/novedades` → Noticias | `/news/portfolio`, `/news/market` | — |
| `/novedades` (asesor) | `/advisor/radar/events`, `/advisor/radar/news` | — |
| `/alertas` | `/alerts`, `/advisor/alerts`, `/prices` | `POST /alerts`, `PATCH /alerts/{id}`, `DELETE /alerts/{id}`, `/alerts/events/seen`, `/advisor/alerts/events/seen` |
| `/ai` | `/positions`, `/monthly`, `/brokers`, `/operations`, `/ai/usage` | `POST /ai/chat` (stream; puede escribir en la cartera) |
| Drawer IA (global) | — | `POST /ai/analyze`, `DELETE /ai/cache/{screen}` |
| `/mas` | (sólo push) | suscripción push + `sendTest` |

---

## Hallazgos consolidados (lo notable, ordenado por gravedad)

1. `[V]` **`Imports.jsx:189-202` — el aviso del asesor está renderizado adentro del `<button>` "Nueva importación"**. HTML inválido + banner incrustado en el CTA para asesores en su propio nivel.
2. `[V]` **`More.jsx` — 6 toasts no-op** (`230,233,236,245,247,250`): llaman `toast?.show?.()` y el contexto sólo expone `push`/`dismiss` (`Toast.jsx:48,57-68`). Activar push y "mandame un test" no dan ninguna confirmación. Mismo bug en `MobileSearch.jsx:134,136` y `PositionsMobile.jsx:1785`.
3. `[V]` **Alertas — el selector de moneda no convierte nada**: el `currency` de una `price_target` sólo formatea el mensaje (`backend/alerts_engine.py:226-227`); la condición compara contra el precio crudo del símbolo (`alerts_engine.py:125-137`). Un `.BA` con umbral "US$ 500" dispara a 500 **pesos**.
4. `[V]` **Alertas — el copy "El email siempre llega"** (`AlertsManager.jsx:309`) contradice al motor, que sólo manda mail si `channel in ("email","both")` (`alerts_engine.py:287`).
5. `[V]` **Eventos — un bono en dos brokers**: `mergeEvents` deduplica por `ticker:tipo:fecha` (`upcomingEvents.js:121`) y se queda con el `details.total` de **un** broker, mientras `tickerShares` suma los nominales de **todos** (`Events.jsx:176-183`). La línea "tenés N nominales → ~+X" mezcla los dos universos (`Events.jsx:753, 937`). Se propaga a `/home` vía `UpcomingEventsCard`.
6. `[V]` **Movimientos — el KPI strip y la tabla usan FX distinto**: strip con `tcValuacion` de hoy (`Operations.jsx:980, 1175`), filas con FX histórico (`MovementsTable.jsx:120-126`). En pesos, "Aportado neto" no cierra con lo que se ve abajo. Está documentado en el código (`Operations.jsx:975-977`) pero sigue siendo una divergencia visible.
7. `[V]` **`Operations.jsx:481-485` — la celda "Operaciones · total cerradas"** muestra `ops.length` (todo lo que devuelve `/operations`, incluyendo compras/dividendos/conversiones), al lado de otra celda que dice `${trades} cerradas` con el criterio estricto.
8. `[V]` **`EmptyState subtitle=` se descarta**: `Events.jsx:338` y `News.jsx:285` pasan una prop que el componente no acepta (`EmptyState.jsx:21-29`) → el empty state queda sin explicación.
9. `[V]` **`components/ai/AICoachDrawer.jsx` es huérfano y está roto**: nadie lo importa, y lee `isOpen` de un contexto que ya no lo expone (`CoachDrawerContext.jsx:35-41`).
10. `[V]` **`Events.jsx:906-928` (`renderAmount`) e `ImportWizard.jsx:329-345` (`reset`) son código muerto**; `News.jsx:520-546` (`computeKpis`) calcula 5 campos de los que sólo se usa 1.
11. `[V]` **El wizard "Cancela" después de haber escrito**: en `STEP_RECONCILE` los movimientos ya se confirmaron (`ImportWizard.jsx:697-699`) y el footer sigue mostrando "Cancelar" (`911-918`), sin botón "Volver".
12. `[V]` **Mobile no puede crear ni editar operaciones**: `OpFormModal` está detrás de `!isMobile` (`Operations.jsx:725`) y `TradesFeed` sólo ofrece borrar (`TradesFeed.jsx:121-130`). Tampoco hay Exportar CSV ni Analizar IA en mobile (`Operations.jsx:386-406`).
13. `[V]` **`ConfirmBlock`/`FormBlock` se quedan en "Registrando…" para siempre** si el turno falla: `sent` se pone en `true` y nunca se revierte (`AIBlocks.jsx:327, 398`).
14. `[V]` **Dos componentes distintos llamados `TickerSearch`** con APIs incompatibles (`components/TickerSearch.jsx` vs `components/fundamentals/TickerSearch.jsx`).
15. `[V]` **`BrokerManager` usa `alert()` nativo** para los errores (`80, 105`) mientras el resto de la app usa Toast.
16. `[V]` **Props/imports muertos**: `Operations.jsx:21` (`fmtUsdRaw`), `Operations.jsx:85` (`fmtUsd`), `Events.jsx:23` (`Eye`), `More.jsx:10-11` (`BarChart3`, `Target`), `ImportWizard.jsx:1140/1370` (`isArsContext`), `ImportWizard.jsx:1148` (`brokerLabel`), `More.jsx:75` (filtro `adminOnly` sin ningún item que lo declare).
17. `[V]` **`ImportWizard` — `useCurrencyRouting` sale de `preview`** (`441`) pero se consume en pasos previos al preview (`815`, `828`): el aviso de sub-broker USD no se ve en el primer paso de un import nuevo.
18. `[V]` **`BLOCKED_IMPORT_PLATFORMS = {}`** (`ImportWizard.jsx:189`): toda la maquinaria de plataformas bloqueadas (inyección en el dropdown, card de WhatsApp, `isBlockedPlatform`) está viva pero inerte.
19. `[V]` **`omitirTenencia` no se comunica**: el `DoneStep` no contempla el flag `omitida` (`ImportWizard.jsx:740-741` vs `2872-2880`).
20. `[V]` **`Events.jsx` refetchea 7 endpoints al cambiar la ventana temporal** (`111-114`), no sólo los eventos.
21. `[V]` **`TenenciaUpload` no tiene aprobación por ticker**: manda `skip_row_indices: []` sin `aprobar_tickers` (`53`), a diferencia del `ReconcileStep` del wizard, que es opt-in estricto (`720-730`). El mismo `POST /api/imports/confirm` aplica todo lo propuesto, y el botón sigue diciendo "Completar N posiciones" aunque el override vaya a reducir/sacar activos (`207`).
22. `[V]` **`Imports.jsx` no tiene ningún gating de plan**: "Limpiar broker" (borra todo un broker) y "Forzar revert" (modo nuclear) están disponibles para cualquier tier, sin confirmación escrita del nombre.
23. `[V]` **Las instrucciones de descarga por broker son hardcode** (`BrokerInstructions.jsx:114-234`) y conviven con la capacidad real del registry (`tenencia_format` de `/imports/parsers/grouped`) y con un tercer mapa (`TENENCIA_BROKER_BY_FORMAT`, `ImportWizard.jsx:158-175`) que el propio código admite desincronizado.
24. `[I]` **El draft del registro por chat vive en un dict de proceso** (`backend/main.py:23228: _TRADE_DRAFT: dict = {}`, TTL 15 min). Me agarro de que es un módulo-level en memoria: con más de un worker o tras un restart, un "sí, confirmá" puede caer en un proceso que no tiene el draft. La confirmación en sí sigue siendo segura (falla cerrada), pero la UX del `ConfirmBlock` no contempla ese caso.
