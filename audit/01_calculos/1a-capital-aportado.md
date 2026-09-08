# 1A — Veredicto: Capital aportado, flujos, depósitos y retiros

**Grupo:** Capital aportado, flujos de fondos, depósitos y retiros · 13 divergencias (DIV-029–DIV-041)
**Commit auditado:** `b74f450f2badf1a2b84e657551115a0595110e45` (`/tmp/rendi-main`, `backend/main.py` = 38.029 líneas ✅)
**Citas verificadas:** 41 de 53 exactas · 10 corregidas (desvío de 1–16 líneas) · 2 **sustantivamente incorrectas** (DIV-038 sobre `_ytd_delta`, DIV-040 sobre `twr.py:1047`)
**Hallazgo nuevo, no mapeado:** `main.py:9639-9652` — el recalc BORRA el baseline. Ver URGENTE.

---

## Resumen ejecutivo

El capital aportado tiene **dos convenciones** (`baseline + flujos` vs `sólo flujos`) y **siete implementaciones vivas** de la primera. La app publica los dos números con el MISMO label —"Capital aportado"— en dos pantallas distintas: `/dashboard` (con baseline) y `/analisis?tab=reportes` (sin baseline). Con un baseline de US$50.000 y flujos de US$20.000, el Dashboard dice US$70.000 y Reportes dice US$20.000, y el sub-label de Reportes divide por el chico: **+320 % donde el Dashboard dice +20 %**. Mismo día, misma cuenta, mismo usuario.

Pero el problema de fondo es peor que la divergencia: **el baseline no sobrevive**. `_recalc_pnl_realized_from_ops` (`main.py:9639-9652`) fuerza `capital_inicio = 0` en el PRIMER mes de todos los brokers tocados —`'global'` incluido— cada vez que corre (import, revert, borrar broker, cerrar un futuro, backfill admin). O sea: el usuario carga en `/mensual` lo que ya tenía, y el primer import se lo borra sin aviso. Su "Capital aportado" cae por el baseline entero y su rendimiento salta en la proporción inversa, de una vez, sin que nada haya pasado en su cartera. Eso es una escritura destructiva sobre un dato que el usuario tipeó, y es la causa por la que DIV-029 parece cosmética en la mayoría de las cuentas: en las que ya importaron, las dos convenciones coinciden porque el baseline vale 0.

Lo demás, por severidad:

- **DIV-030 (🔴):** los plazos fijos. El Dashboard suma `pf.investedUsd` al aportado SIEMPRE; HomeMobile y el backend NUNCA. Cuando el PF salió del cash de un broker que ya estaba en Rendi, el Dashboard lo **duplica**; cuando vino de afuera, HomeMobile y el backend lo **omiten**. Ninguna de las dos versiones es correcta, y en un caso medible el signo del retorno se invierte (−6,9 % vs +26,0 %).
- **DIV-032 (🔴):** la conversión ARS→USD importada inventa capital. Escribe `withdraw(ars/tc_blue) + deposit(usd)`, cuyo neto NO es cero (US$1.000.000 al MEP 1.000 con `tc_blue`=1.415 deja **+US$293,29** de aportado fantasma). Y el ajuste **se borra solo** en el primer recalc, porque las filas FX no son `DEPOSIT/WITHDRAW` ni `manual_*`. La conversión manual (`POST /api/conversions`) no toca nada — y es la que tiene razón.
- **DIV-035 (🔴):** `GET /api/export/transactions.csv` — el CSV "para el contador" — **doble-cuenta todo flujo importado**: lo vuelca una vez desde `import_normalized_tx` y otra vez desde `monthly_entries.deposits` completo.
- **DIV-036 (🟠):** el snapshot que va al modelo de IA suma `global` + el desglose por broker → `deposits_lifetime` y `withdrawals_lifetime` son **exactamente 2×** lo real. Hay DOS copias (el mapa detectó una).
- **DIV-037 (🟠):** siete denominadores Modified Dietz distintos. El mismo mes rinde +7,7 %, +4,0 % o "—" según la pantalla.
- **DIV-033 (🟠):** cuatro escritores de `snapshots.net_deposited` con tres convenciones, y cuatro lectores que siguen restando estampas escritas en momentos distintos. El propio `twr.py:937` documenta el caso medido: −37,04 % en un mes plano.

---

## Tabla de veredictos

| DIV | versiones | ¿difieren de verdad? | cuál es la correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---:|---|---|---|---|---|
| **DIV-029** | 2 | **SÍ** — difieren exactamente en el baseline | `include_baseline=True` (Dashboard) | `/analisis?tab=reportes` KPI "Capital aportado" y "Retorno sobre aportes" (+320 % vs +20 %) | 🔴 alta | fix aplicado en un solo lugar + "semántica histórica" preservada a propósito |
| **DIV-030** | 3 | **SÍ** — ±el capital del PF | **ninguna**: falta registrar el flujo en el backend | `/dashboard` (duplica) y `/` HomeMobile + `/analisis?tab=reportes` (omite) | 🔴 alta | falta de capa compartida: el PF nunca escribe `monthly_entries` |
| **DIV-031** | 7 | Mayormente **NO** (misma fórmula) · SÍ en el fallback MtM y en el clamp de demo | `insightsModel.netCapitalContributed` | latente (`/dashboard` el día que se conecte el MtM); demo `/` con clamp | 🟡 media | copiar y pegar; no existe helper compartido front↔back |
| **DIV-032** | 2 | **SÍ** — el import mueve el aportado, lo manual no | la **manual** (neta cero) | `/dashboard`, `/`, `/analisis` — aportado inflado tras importar Balanz/Cocos con conversiones | 🔴 alta | PARCHE ("FIX bug #1") sobre el síntoma, sin pasar por el recalc autoritativo |
| **DIV-033** | 4 escritores / 4 lectores | **SÍ** — restar estampas de momentos distintos no es un flujo | `twr.netdep_canonico` + `_aportado_por_punto` | `/analisis?tab=reportes` (Dietz del período), `/clientes` asesor (captación e "efecto mercado"), gráfico de evolución | 🟠 media-alta | migración a medio hacer: el canónico existe y sólo 2 de 6 call sites lo usan |
| **DIV-034** | 2 | **SÍ** cuando hay filas no-import no-manual (las FX de DIV-032) | la columna `manual_deposits` (DELETE) | `/operaciones` — movimiento visible que devuelve 404 al borrar | 🟡 media | heurística vieja (`total − imports`) que sobrevivió a la migración a `manual_*` |
| **DIV-035** | 2 pasos del mismo endpoint | **SÍ** — 2× cada flujo importado | ninguna de las dos: hay que restar los imports como en `/api/movements` | `GET /api/export/transactions.csv` (botón Exportar en `/operaciones`) | 🔴 alta | el fix de `/api/movements` no se replicó en el export |
| **DIV-036** | 2 copias idénticas | **SÍ** — exactamente 2× | sumar sólo `broker === 'global'` | Coach IA (`/ai` y el drawer): el modelo afirma depósitos del doble | 🟠 media-alta | frontend recalculando sobre un payload que mezcla agregado y desglose |
| **DIV-037** | 7 | **SÍ** — hasta 2× entre variantes | `builder._modified_dietz_pct` (Dietz puro, sin heurísticas) | `/analisis?tab=reportes`, `/analisis?tab=diagnostico`, `/mensual`, informe del asesor | 🟠 media-alta | copiar y pegar + heurísticas anti-spike agregadas de a una |
| **DIV-038** | 3 | **NO** — las 3 vías del par ya coinciden; `_ytd_delta` está muerto para no-global | `brokers_del_filtro` + `include_baseline=False` por pata | ninguna hoy (trampa latente documentada) | ⚪ cosmética | — (cita del mapa incorrecta) |
| **DIV-039** | 2 | **SÍ** — mes y TC equivocados | desktop (`Positions.jsx`) | cualquier depósito/retiro cargado desde el celular | 🟠 media-alta | paridad mobile/desktop incompleta |
| **DIV-040** | 3 (no 4) | **NO** — `\|\|` y el helper son equivalentes | `netDepositedOf` / `main.py:32932` | ninguna | ⚪ cosmética | copiar y pegar (riesgo de drift, no de número) |
| **DIV-041** | 1 import muerto | **NO hoy** — trampa armada | `insightsModel.js:49` (con fallback `capital_inicio_costo`) | latente: `/dashboard` el día que se llame `applyMtmToMonthly` | 🟡 media | copiar y pegar sin el fix posterior |

---

## Detalle por divergencia

### DIV-029 · DIV-031 · DIV-041 — La fórmula del aportado y su baseline
*(Se analizan juntas: misma raíz. DIV-029 es la divergencia de convención, DIV-031 la proliferación de copias, DIV-041 una de esas copias con un fix faltante.)*

**Estado de las citas:** ✅ verificadas, con 1 corrección menor
- `backend/reporting/builder.py:735` → la función `fetch_cum_deposits_until` arranca en **:716**; :735 es el `import` interno. Correcto en sustancia.
- `backend/main.py:32700` → ✅ exacto (`cum_deposited = sum(`).
- `frontend/src/pages/Reports.jsx:593-594` (label) y `:602` (el cociente) → ✅.
- `frontend/src/pages/Dashboard.jsx:872` (label), `:222-232` (cálculo), `:43` (import muerto) → ✅.
- `frontend/src/pages/HomeMobile.jsx:135-141` → ✅.
- `frontend/src/utils/insightsModel.js:41-52` → ✅.
- `frontend/src/utils/demo.js:588-595` → ✅.
- ⚠️ `backend/importing/fx_migrate.py:88-92` → **corregida: :91-92**.

#### a. Implementaciones

**1. SSoT backend — `backend/snapshots_job.py:328-386`**
```python
def compute_net_deposited_db(conn, uid, *, as_of_date=None,
                             broker_filter="global", include_baseline=True) -> float:
    ...
    flows = SUM(deposits) - SUM(withdrawals)  # WHERE user_id, broker[, fecha]
    if not include_baseline:
        return flows
    baseline = SELECT capital_inicio ... ORDER BY year, month LIMIT 1
    return baseline + flows
```
Variante in-memory: `compute_net_deposited(monthly_entries)` (`snapshots_job.py:388-403`), equivalente a `include_baseline=True, broker='global'`.

**2. `include_baseline=False` — los dos call sites que lo apagan**
- `backend/reporting/builder.py:716-742` (`fetch_cum_deposits_until`), consumido en `builder.py:1533` para `delta_pct_over_contrib`.
- `backend/main.py:32699-32703` (`_portfolio_snapshot_summary`), publicado como `cum_deposited` en `main.py:32860`.

Los dos con el mismo comentario: *"Mantenemos `include_baseline=False` para preservar la semántica histórica del endpoint".*

**3. `include_baseline=True` — el resto**
`snapshots_job.py:767` (cron), `main.py:32753` (`_latest_netdep` de los Δ chips), `builder.py:964`, `builder.py:1446`, `twr.py:736-737`, `twr.py:2049`, `advisor_alerts.py:105`, `main.py:15554` (fallback).

**4. Cinco copias inline en el front + 1 en el back**
| # | ubicación | fórmula |
|---|---|---|
| a | `insightsModel.js:41-52` | `(capital_inicio_costo ?? capital_inicio ?? 0) + Σ(dep−wd)` |
| b | `Dashboard.jsx:222-232` | `(capital_inicio \|\| 0) + Σ(dep−wd)` **+ `pf.investedUsd`** |
| c | `HomeMobile.jsx:135-142` | `(capital_inicio \|\| 0) + Σ(dep−wd)` |
| d | `demo.js:588-595` | `min(baseline + Σ(dep−wd), 0,85 × valor)` ← **clamp** |
| e | `fx_migrate.py:91-92` | `baseline + dep − ret` (panel admin del migrador) |
| f | `snapshots_job.py:388` | `baseline + Σ(dep−wd)` (in-memory) |

#### b. Fórmulas

Sea, para el broker `g = 'global'` y sus filas mensuales ordenadas $m_1 \dots m_n$:

$$B = \texttt{capital\_inicio}(m_1) \qquad F = \sum_{i=1}^{n}\big(\texttt{deposits}(m_i) - \texttt{withdrawals}(m_i)\big)$$

- **CON baseline:** $A_{\text{con}} = B + F$
- **SIN baseline:** $A_{\text{sin}} = F$
- **Dashboard:** $A_{\text{dash}} = B + F + P$ , con $P$ = capital de los plazos fijos en USD (ver DIV-030)
- **Demo:** $A_{\text{demo}} = \min(B+F,\; 0{,}85\,V)$ , $V$ = última valuación

Y el número que ve el usuario en cada caso: $r = (V - A)/A$.

#### c. ¿Real o cosmética? — **REAL**

Ejemplo con $B = 50.000$, $F = 20.000$, $V = 84.000$:

| pantalla | $A$ | "Capital aportado" | retorno publicado |
|---|---:|---|---|
| `/dashboard` (KPI + chip del hero) | 70.000 | **US$70.000** | **+20,0 %** |
| `/analisis?tab=reportes` (tab Año) | 20.000 | **US$20.000** | **+320,0 %** |

Diferencia en el % del hero: **16×**. Y no es un caso de laboratorio: el propio `Reports.jsx:596-601` documenta haber visto "**+1565.9 %**" en esa tarjeta, al lado de un "P&L del año: —".

Además `builder.py:1533-1536` usa el mismo denominador chico para `delta_pct_over_contrib` ("% sobre aportado" del período), así que la inflación aparece dos veces en la misma pantalla.

**Matiz decisivo:** en cuentas que ya pasaron por un recalc, $B = 0$ (ver URGENTE), y ahí las dos convenciones coinciden. La divergencia se materializa en el subconjunto de usuarios que cargaron `capital_inicio` a mano en `/mensual` y todavía no importaron nada — y desaparece de golpe, con un salto visible, el día que importan.

**DIV-031 propiamente dicha es mayormente COSMÉTICA:** las 6 copias calculan lo mismo. Las dos excepciones reales:
- `insightsModel.js:49` tiene el fallback `capital_inicio_costo ?? capital_inicio`; `Dashboard.jsx:227` y `HomeMobile.jsx:139` no.
- `demo.js:594` clampea a 85 % del valor — un ajuste manual para que la demo dé positivo.

**DIV-041 es un NO-OP hoy, con la trampa armada:** verifiqué que `applyMtmToMonthly` se importa en `Dashboard.jsx:43` y **no se llama en ningún lado del archivo** (grep sobre todo `Dashboard.jsx`: una sola aparición). Mientras `monthly` no pase por MtM, `capital_inicio` no tiene sustituto y la copia b es idéntica a la a. El día que alguien conecte el MtM al Dashboard —y el import ya está puesto—, `capital_inicio` pasa a ser el snapshot a mercado y el "Capital aportado" del hero se infla en silencio con la ganancia latente. `insightsModel.js:45-48` explica ese riesgo textualmente; `Dashboard.jsx` no lo tiene.

#### d. Dictamen
**Correcta: `include_baseline=True`.** El baseline es un stock: la plata que el usuario ya tenía cuando arrancó la contabilidad. Sacarlo del denominador no cambia el numerador (el valor de hoy SÍ incluye esas posiciones), así que el cociente mide el retorno de toda la cartera contra una fracción del capital. `Reports.jsx:596-601` ya reconoce el síntoma y lo tapa con un guard (`noBasis`) en vez de arreglar el denominador — **PARCHE**.

"Preservar la semántica histórica del endpoint" no es una justificación: no es un endpoint público con contrato, es una tarjeta que dice lo mismo que otra tarjeta y muestra otro número.

Para DIV-031: la correcta es `netCapitalContributed` (con el fallback MtM). Para DIV-041: nada que arreglar hoy, pero el import muerto hay que sacarlo o el fallback hay que agregarlo — no dejar las dos mitades.

#### e. Qué ve mal el usuario y dónde
- **`/analisis?tab=reportes`, tab "Año"**, tarjeta "Capital aportado" (`Reports.jsx:593`) → monto **subvaluado en $B$** y sub-label "Retorno sobre aportes" (`Reports.jsx:602`) **inflado en $V/A_{\text{sin}} - V/A_{\text{con}}$**. En el ejemplo: +320 % en vez de +20 %.
- **`/analisis?tab=reportes`**, "% sobre aportado" del período (`builder.py:1535`) → mismo denominador chico, mismo factor de inflación.
- **`/dashboard`**, chip "Aportado" del hero (`Dashboard.jsx:835`) y KPI "Capital aportado" (`Dashboard.jsx:872`) → el número correcto en cuanto al baseline, pero contaminado por el PF (DIV-030).
- Endpoints: `GET /api/reportes` (a través de `_portfolio_snapshot_summary`, `main.py:33211`) y el packet del chat (`main.py:23108`).

#### f. Causa raíz
**Fix aplicado en un solo lugar + una migración a SSoT que se detuvo a mitad.** La Fase 3 (2026-05-30) unificó las 3 implementaciones backend en `compute_net_deposited_db`, pero le dio a la función un `include_baseline` opcional en vez de decidir la convención — y los dos call sites que ya estaban mal se quedaron mal, ahora con un flag que los legitima. El frontend nunca entró en esa unificación: sigue con 4 copias inline porque no hay un endpoint que devuelva el aportado ya calculado.

#### g. Fuente única de verdad propuesta
- Backend: `snapshots_job.compute_net_deposited_db` **sin el parámetro `include_baseline`** — siempre con baseline. Eliminar `include_baseline=False` de `builder.py:737` y `main.py:32701`.
- Frontend: exponer `net_deposited` en el payload que ya consumen `/dashboard` y `/` y **borrar las 3 copias inline** (`Dashboard.jsx:222`, `HomeMobile.jsx:135`, y la de `demo.js` reemplazarla por el valor fijo del fixture). Si se quiere seguir calculándolo en el cliente, que sea `netCapitalContributed` importada, no reescrita.
- Sacar el `import { applyMtmToMonthly }` muerto de `Dashboard.jsx:43`.

---

### DIV-030 — Plazos fijos: tres valores para el mismo KPI

**Estado de las citas:** ✅ verificadas
- `backend/main.py:9143-9144` → ✅ exacto (`_autodeposit_if_overdraw` + `_adjust_broker_cash(-capital)` dentro de `create_plazo_fijo`, def en `:9119`).
- `Dashboard.jsx:232` → ✅ (`const netDeposited = netDepositedBase + pf.investedUsd`).
- `HomeMobile.jsx:135-142` → ✅ (no suma PF).

#### a. Implementaciones

**Backend — `main.py:9119-9161` (`POST /api/plazos-fijos`)**
```python
if p.source_broker:
    ...
    _autodeposit_if_overdraw(conn, uid, p.source_broker, float(p.capital), p.fecha_inicio)
    _adjust_broker_cash(conn, uid, p.source_broker, -float(p.capital))
cur = conn.execute("""INSERT INTO plazos_fijos ...""")
```
Debita el cash **sin escribir `monthly_entries`**. Y si `source_broker` no viene (plata de afuera de Rendi), no hace absolutamente nada contable.

**Dashboard — `Dashboard.jsx:209, 232`**
```js
const pf = pfUsd(usePfRollup(), tcValuacion)
...
const netDeposited = netDepositedBase + pf.investedUsd
```
donde `pfUsd` (`hooks/usePfRollup.js:34-39`) devuelve `investedUsd = Σ capital` de TODOS los PF abiertos, sin mirar si tuvieron `source_broker`.

**HomeMobile — `HomeMobile.jsx:102, 135-142`**: calcula `pf` y lo suma al VALOR (`totals`), pero `aportado` no lo incluye.

#### b. Fórmulas
Con $A_0 = B + F$ y $P = \sum_j \texttt{capital}_j$ (en USD al `tcValuacion`):

- Backend / Reportes: $A_{\text{back}} = A_0$
- HomeMobile: $A_{\text{home}} = A_0$
- Dashboard: $A_{\text{dash}} = A_0 + P$

Y el correcto depende del origen del PF:

$$A^{*} = A_0 + \sum_{j\,:\,\text{sin source\_broker}} \texttt{capital}_j$$

porque un PF fondeado desde el cash de un broker de Rendi **ya está** dentro de $A_0$ (esa plata entró como depósito y sigue en la cuenta, sólo cambió de instrumento), mientras que uno fondeado de afuera es capital nuevo que nadie registró.

#### c. ¿Real o cosmética? — **REAL, y puede invertir el signo del retorno**

Caso: usuario con $A_0 = 20.000$, posiciones valuadas en 18.000, y un PF de $10.000.000 ARS al MEP 1.415 (= US$7.067) **hecho desde el cash de Cocos**, hoy devengando US$7.200.

| pantalla | aportado | valor total | retorno publicado |
|---|---:|---:|---|
| `/dashboard` | 20.000 + 7.067 = **27.067** | 25.200 | **−6,9 %** |
| `/` (HomeMobile) | **20.000** | 25.200 | **+26,0 %** |
| `/analisis?tab=reportes` | **20.000** | (sin PF) | — |

**Correcto en este caso:** 20.000 → +26,0 %. El Dashboard está mal por US$7.067 y publica una pérdida donde hay ganancia.

Caso simétrico (PF sin `source_broker`, plata de afuera): el correcto es 27.067 y quien se equivoca es HomeMobile y el backend, que publican +26,0 % donde el retorno real es −6,9 %.

#### d. Dictamen
**Ninguna de las tres es correcta.** El bug no está en las pantallas: está en que `POST /api/plazos-fijos` no registra el flujo. La solución es contable, no de presentación:
- PF **sin** `source_broker` → `_update_monthly_flow(direction='deposit', amount_usd, is_manual=True)` sobre un broker que represente el banco + `'global'`.
- PF **con** `source_broker` → nada (transferencia interna, el cash ya estaba contado). Que es exactamente lo que hoy hace.
- Y entonces las tres pantallas leen el mismo `net_deposited` y ninguna suma `pf.investedUsd` a mano.

El `_autodeposit_if_overdraw` de `main.py:9143` es un **PARCHE parcial**: cubre el caso "PF mayor al cash disponible" registrando el faltante como aporte, pero deja sin registrar el PF entero cuando no hay `source_broker`. Tapa medio síntoma.

#### e. Qué ve mal el usuario y dónde
- **`/dashboard`**: chip "Aportado" del hero (`:835`), KPI "Capital aportado" (`:872`), "Resultado total" (`:265-266`) y el % del hero (`:668`). Todos corridos en $P_{\text{interno}}$.
- **`/`** (HomeMobile, la home mobile): KPI "Capital aportado" (`HomeMobile.jsx:417-421`). Corrido en $P_{\text{externo}}$.
- **`/analisis?tab=reportes`**: `cum_deposited` (`GET /api/reportes`) — corrido en $P_{\text{externo}}$, y encima sin baseline (DIV-029).
- El cron (`snapshots_job.py:767`) tampoco ve los PF → la curva de evolución tiene un "escalón de rendimiento" el día que se abre un PF externo.

#### f. Causa raíz
**Falta de una capa compartida.** Los plazos fijos se agregaron como una tabla y un rollup de frontend (`usePfRollup`), sin conectarlos al libro contable (`monthly_entries`). Cada pantalla decidió por su cuenta si sumarlos o no, y las tres decidieron distinto.

#### g. Fuente única de verdad propuesta
`POST /api/plazos-fijos` debe escribir `monthly_entries` cuando el capital viene de afuera, y las tres superficies deben leer `net_deposited` del backend. Eliminar `netDepositedBase + pf.investedUsd` de `Dashboard.jsx:232`.

---

### DIV-032 — Conversión ARS→USD: la importada inventa capital, la manual no (y el ajuste se autodestruye)

**Estado de las citas:** ⚠️ 1 corregida
- ⚠️ `backend/importing/persister.py:1139-1143` → **corregida: `:1138-1141`** (los 4 `_update_monthly_flow`). El bloque completo con su comentario va de `:1126` a `:1141`.
- `backend/main.py:10870-11010` → ✅ (`create_conversion` en `:10871`, cierra en `:11000`).

#### a. Implementaciones

**Import — `persister.py:1126-1141` (`_persist_fx`, `direction == "ars_to_usd"`)**
```python
_ars_as_usd = (ars_amount / tc_blue) if tc_blue else 0.0
helpers._update_monthly_flow(conn, uid, ars_broker["name"], _y, _m, "withdraw", _ars_as_usd)
helpers._update_monthly_flow(conn, uid, "global",           _y, _m, "withdraw", _ars_as_usd)
helpers._update_monthly_flow(conn, uid, usd_broker["name"], _y, _m, "deposit",  usd_amount)
helpers._update_monthly_flow(conn, uid, "global",           _y, _m, "deposit",  usd_amount)
```
Los cuatro con `is_manual=False` (default de `main.py:9918-9919`).

**Manual — `main.py:10871-11000` (`POST /api/conversions`)**
Ajusta cash en las dos patas (`_adjust_cash`), inserta una `operation` tipo `CONVERSION`, y en `usd_to_ars` computa P&L cambiario. **No toca `deposits`/`withdrawals` en ningún caso** (verificado línea por línea: los únicos `_update_monthly_*` del endpoint son `_update_monthly_pnl_realized`, `main.py:10979-10982`).

**El destructor — `main.py:9414-9601` (`_recalc_pnl_realized_from_ops`)**
```python
imp_deposits, imp_withdrawals = _import_flows_for_period(conn, uid, broker, year_str, month_str, tc_blue)
...
new_deposits    = round(imp_deposits + manual_dep, 4)
new_withdrawals = round(imp_withdrawals + manual_wit, 4)
UPDATE monthly_entries SET deposits=?, withdrawals=? ...
```
Y `_import_flows_for_period` (`main.py:589-626`) filtra `AND n.operation_type IN ('DEPOSIT', 'WITHDRAW')`. Las filas FX tienen `operation_type` `FX_ARS_TO_USD` / `FX_USD_TO_ARS` → **no entran**. Tampoco están en `manual_*` (se escribieron con `is_manual=False`). Resultado: el recalc las pisa con cero.

Dispara el recalc: revert de un batch (`persister.py:1677`), borrar broker (`main.py:4495`), cerrar un futuro (`main.py:12370`), `rebuild.py`, `recompute_backfill.py`.

#### b. Fórmulas
Sea $a$ = pesos convertidos, $u$ = dólares obtenidos, $t = a/u$ el TC real de la conversión, $t_b$ = `config.tc_blue` del usuario (default duro 1.415).

- Import, efecto sobre el aportado global: $\Delta A_{\text{imp}} = u - \dfrac{a}{t_b} = u\left(1 - \dfrac{t}{t_b}\right)$
- Manual: $\Delta A_{\text{man}} = 0$
- Import **después del primer recalc**: $\Delta A = 0$

#### c. ¿Real o cosmética? — **REAL, y transitoria (lo cual es peor)**

$a = 1.000.000$ ARS convertidos al MEP $t = 1.000$ → $u = 1.000$ USD. Con `tc_blue` en su default 1.415:

$$\Delta A_{\text{imp}} = 1.000 - \frac{1.000.000}{1.415} = 1.000 - 706{,}71 = \boxed{+293{,}29\ \text{USD}}$$

de capital aportado que nadie aportó — **+29,3 % del monto convertido**. Y con una cuenta de 20.000 de aportado, eso solo mueve el retorno publicado en ~1,5 puntos porcentuales; con diez conversiones (un usuario de Balanz típico tiene decenas), en ~15.

Después, la primera vez que el usuario revierta un import, borre un broker o cierre un futuro, los 293,29 desaparecen y el aportado **baja de golpe** sin que haya pasado nada. El retorno salta hacia arriba en la misma proporción. El usuario ve su rendimiento cambiar solo.

Si $t > t_b$ (conversión a un dólar más alto que el blue guardado) el signo se invierte y el import **borra** capital aportado.

#### d. Dictamen
**Correcta: la manual.** Una conversión de moneda es una transferencia interna de valor neto cero: no entra ni sale plata de la cuenta, sólo cambia de denominación. Registrarla como `withdraw + deposit` sólo puede dar cero si las dos patas se valúan al MISMO tipo de cambio — y acá se valúan a dos (`tc_blue` para la salida, face para la entrada). El comentario de `persister.py:1126-1136` es explícito sobre la intención ("valuar el capital a la MISMA tasa que las tenencias"), pero la tasa que usa para la pata ARS (`tc_blue` de config, un número estático) no es la que usa la valuación del resto de la app (MEP del día).

Este bloque es un **PARCHE de manual**: se llama "FIX bug #1" y corrige un síntoma (aportado subvaluado tras importar conversiones) tocando `monthly_entries` fuera del circuito autoritativo. La causa real del síntoma original está aguas arriba —el `DEPOSIT` en pesos se dolarizó a un TC distinto del de la conversión— y hay que arreglarla ahí (`gross_amount_usd` sellado al MEP de la fecha), no compensando después.

#### e. Qué ve mal el usuario y dónde
Cualquier usuario que importó movimientos de un broker con compra/venta de dólares (Balanz, Cocos, IEB, PPI, inviu) ve, hasta el primer recalc:
- **`/dashboard`** — chip "Aportado" y KPI "Capital aportado" inflados en $\sum \Delta A_{\text{imp}}$; retorno total **subvaluado**.
- **`/`** (HomeMobile) — mismo KPI.
- **`/analisis?tab=reportes`** — `cum_deposited` y "% sobre aportado".
- **`/operaciones`** — un movimiento fantasma "Depósitos manuales YYYY-MM" que no se puede borrar (ver DIV-034: es exactamente esta fila).
- Snapshot del cron → toda la curva de evolución arrastra el escalón.

Y después del recalc, un salto de rendimiento sin causa.

#### f. Causa raíz
**PARCHE que no pasa por el escritor autoritativo.** Es literalmente el patrón que la regla `feedback_el_test_que_no_atraviesa_el_recalc.md` describe: se escribió `monthly_entries` directo, y el escritor POSTERIOR (`_recalc_pnl_realized_from_ops`) lo deshace. Un test que llame a `_persist_fx` y lea `monthly_entries` pasa en verde y certifica lo contrario de producción.

#### g. Fuente única de verdad propuesta
- `_persist_fx` **no debe escribir `monthly_entries`** (igual que `create_conversion`). Borrar `persister.py:1126-1141`.
- El aportado de una conversión sale de que el `DEPOSIT` original esté bien dolarizado: sellar `gross_amount_usd` con `fx.fx_for_date(fecha)` en el normalizer, que es lo que ya hace `cash_flow` (`main.py:10196`).
- Si alguna vez hiciera falta un ajuste FX en el libro, tiene que entrar por `manual_*` o por una fuente que `_import_flows_for_period` reconozca — si no, no existe.

---

### DIV-033 — Cuatro escritores de `snapshots.net_deposited`, tres convenciones, cuatro lectores que los restan

**Estado de las citas:** ⚠️ 4 corregidas
- ⚠️ `snapshots_job.py:766` → **corregida: `:767`** (`net_deposited = compute_net_deposited(monthly)`).
- `main.py:5075` → ✅ en sustancia: `POST /api/snapshots` es `main.py:5004-5089`; el write de `net_deposited` está en `:5062` (rama cron) y `:5077-5083` (rama browser).
- ⚠️ `persister.py:1250` → **corregida: `:1266`** (`net_dep = cum_dep - cum_wd`; `_backfill_snapshots_from_monthly` empieza en `:1230`).
- ⚠️ `main.py:15546` → **corregida:** la función es `_recompute_snapshots_netdep_for_user` (`main.py:15508`); `:15546` cae dentro del comentario, el uso de `twr._aportado_por_punto` está en `:15550`.
- `twr.py:938-948` → ✅ (`netdep_canonico` en `:937`).
- `builder.py:1451` → ✅ exacto (`deposits = max(0.0, end_netdep - start_netdep)`).
- ⚠️ `main.py:37040` → **corregida: `:37043-37047`**.
- `main.py:38004` → ✅ exacto.
- `evolution.js:508` → ✅ exacto.

#### a. Implementaciones — los cuatro escritores

| # | escritor | qué estampa | ¿baseline? | ¿corte por fecha? |
|---|---|---|---|---|
| 1 | cron, `snapshots_job.py:767` | `compute_net_deposited(monthly)` | **sí** | **no** — todo el historial |
| 2 | browser, `main.py:5077-5083` | `data.net_deposited` (lo que manda el front) | según el front | n/a |
| 3 | import, `persister.py:1266` | `cum_dep − cum_wd` acumulado al mes | **no** | sí, por mes |
| 4 | arranque, `main.py:15550` | `twr._aportado_por_punto(...)` | **sí**, anclado al canónico | sí, día a día |

El escritor 2, en la práctica, recibe `netDepositedPositions` del Dashboard (`Dashboard.jsx:478`) = `B + F + P − P = B + F` → convención 1. Coherente.

El escritor 1 estampa el aportado de **todo el historial** en cada foto diaria — no el aportado *hasta esa fecha*. Para la foto de hoy es lo mismo; para una foto de hace 6 meses re-estampada, no.

#### b. Fórmulas
Sea $N(d)$ la estampa de la foto del día $d$, y $\tau(d)$ el instante en que esa fila se escribió.

- Convención 1/2/4: $N(d) = B + \sum_{m \le d} (\text{dep}_m - \text{wd}_m)\big|_{\tau(d)}$
- Convención 3: $N(d) = \sum_{m \le d} (\text{dep}_m - \text{wd}_m)\big|_{\tau(d)}$ (sin $B$)

El lector calcula el flujo de una ventana como $\Phi = N(d_1) - N(d_0)$. Eso sólo es un flujo si $\tau(d_0) = \tau(d_1)$ **y** las dos filas usan la misma convención. Ninguna de las dos cosas está garantizada.

#### c. ¿Real o cosmética? — **REAL, con caso medido en el propio código**

`twr.py:945-951` documenta el caso de producción: *"julio plano en 110.000, cero aportes en julio, cron diario sano, y un import del historial 2025 el 16/7 → el mes cerrado publicaba **−US$50.000 / −37,04 %** y Diagnóstico el mismo −37,04 % de drawdown"*. El import reescribió `monthly_entries` hacia atrás, las fotos viejas conservaron su estampa vieja, y la resta midió el cambio de la contabilidad.

Y hay una **mezcla peor, todavía viva**, en `builder.py:1440-1451`:
```python
start_netdep = float(snap_start["net_deposited"] or 0)      # ESTAMPA (momento τ₀)
...
end_netdep = compute_net_deposited_db(conn, uid, broker_filter='global', include_baseline=True)  # LIVE (momento ahora)
deposits = max(0.0, end_netdep - start_netdep)
```
Un lado estampado y el otro calculado ahora. Si entre medio hubo un import retroactivo de US$30.000, el período publica US$30.000 de "aportes" que no ocurrieron en el período, y el `delta_usd` los resta del rendimiento: la pantalla dice que el usuario perdió 30.000 que en realidad depositó en 2024.

**Ejemplo numérico:** cartera plana en 110.000 todo julio, aportes de julio = 0. Foto del 1/7 estampada el 1/7 con $N = 60.000$. El 16/7 se importa el historial 2025 (US$50.000 de depósitos viejos) → el canónico pasa a 110.000. El 31/7:
- $\Phi = 110.000 - 60.000 = 50.000$ de "aportes de julio"
- $\text{pnl} = (110.000 - 110.000) - 50.000 = -50.000$
- Dietz: $-50.000 / (110.000 + 25.000) = \mathbf{-37{,}04\,\%}$

#### d. Dictamen
**Correcta: `twr.netdep_canonico` (`twr.py:937-987`) + `twr._aportado_por_punto` (`twr.py:1014-1070`).** Son las únicas dos que garantizan que las dos puntas de una resta salgan de la MISMA lectura de `monthly_entries`, y `_aportado_por_punto` además preserva la resolución diaria anclando los bordes de mes al canónico. El docstring de `_aportado_por_punto` explica los dos intentos fallidos previos (sólo-estampa: −37,04 %; sólo-canónico: +200,00 %) y por qué el híbrido con corredor es correcto.

Los 4 lectores que restan estampas crudas están mal, incluido `builder.py:1451` que además mezcla estampa con live.

#### e. Qué ve mal el usuario y dónde
- **`/analisis?tab=reportes`** — `delta_usd` y `delta_pct` de cualquier período sub-mensual (día/semana), vía `builder.py:1451`. El Dietz del período tiene el flujo mal → el % es directamente otro número. **Éste es el más grave: mezcla estampa con live.**
- **`/clientes`** (asesor, `GET` que arma el libro, `main.py:37043-37047`) — "Captación del mes" (`net_deposited_usd`) y "Efecto mercado" (`market_effect_usd`). El comentario del propio código admite que publicar "el mercado restó US$65.967" sobre un escalón de convenciones es ponerle *"el nombre del mercado"* a otra cosa.
- **`/clientes`**, tabla por cliente (`main.py:38004`) — `flows_7d_usd` y `market_7d_usd`.
- **`/analisis?tab=diagnostico`** — el gráfico de evolución, vía `evolution.js:508` + `:534` (`flows = netDep − prevNetDep`).

#### f. Causa raíz
**Migración a medio hacer.** `netdep_canonico` y `_aportado_por_punto` existen, están escritos, documentados con casos medidos... y sólo los usan 2 call sites (`twr.py:1343` y `main.py:15550`). Los otros cuatro siguieron restando estampas. El escritor 3 (`persister.py:1266`) además nunca se alineó a la convención con baseline.

#### g. Fuente única de verdad propuesta
- Lectura: **todo el que necesite "el flujo entre dos fechas" llama a `twr._aportado_por_punto`**, nunca a la columna. Reemplazar en `builder.py:1439-1451`, `main.py:37043-37047`, `main.py:38004` y `evolution.js:508` (exponiendo el aportado por punto en el payload de snapshots).
- Escritura: una sola convención (baseline + flujos hasta la fecha). `persister.py:1266` debe pasar a `compute_net_deposited_db(as_of_date=snap_date, include_baseline=True)`.
- La columna `snapshots.net_deposited` queda como caché de la lectura canónica, no como fuente.

---

### DIV-034 — "Lo manual" se define de dos maneras: la lista muestra lo que el borrado no encuentra

**Estado de las citas:** ✅ verificadas
- `main.py:12711` → ✅ exacto (`deposits_manual = max(0.0, deposits_total - imp_dep)`).
- `main.py:13042-13046` → ✅ (`manual_usd` en `:13044`, el 404 en `:13045-13046`).

#### a. Implementaciones

**LISTA — `GET /api/movements`, `main.py:12640-12724`**
```python
imp_dep = imp_dep_map.get(key, 0.0)
deposits_total = float(d["deposits"] or 0)
deposits_manual = max(0.0, deposits_total - imp_dep)     # :12711
if deposits_manual > 0.01:
    movements.append({"id": f"me-{d['id']}-dep", ..., "amount_usd": deposits_manual, ...})
```

**BORRADO — `DELETE /api/movements/{mid}`, `main.py:13027-13046`**
```python
col = "manual_deposits" if direction == "dep" else "manual_withdrawals"
manual_usd = float((row[col] if col in row.keys() else 0) or 0)
if manual_usd <= 0:
    raise HTTPException(404, "No hay un movimiento manual para borrar en ese mes")
```

#### b. Fórmulas
Para una fila $(broker, y, m)$ de `monthly_entries`:

- Lista: $D_{\text{lista}} = \max\big(0,\ \texttt{deposits} - I\big)$, con $I$ = Σ de los `DEPOSIT` importados confirmados del período.
- Borrado: $D_{\text{del}} = \texttt{manual\_deposits}$

Coinciden **si y sólo si** $\texttt{deposits} = I + \texttt{manual\_deposits}$, que es el invariante que `_recalc_pnl_realized_from_ops` restablece (`main.py:9584-9586`). Cualquier escritura a `deposits` con `is_manual=False` que no sea un `DEPOSIT`/`WITHDRAW` importado rompe el invariante y separa los dos números.

#### c. ¿Real o cosmética? — **REAL, y DIV-032 la dispara**

La escritura que rompe el invariante existe y la identifiqué: `_persist_fx` (`persister.py:1141`) hace `_update_monthly_flow(usd_broker, ..., "deposit", usd_amount)` con `is_manual=False`, y `FX_ARS_TO_USD` no está en `('DEPOSIT','WITHDRAW')`.

**Ejemplo:** import de Balanz con una conversión de US$1.000 hacia "Balanz · USD", mes 2026-08, sin ningún depósito importado en ese broker/mes.
- `monthly_entries("Balanz · USD", 2026, 8).deposits = 1.000`
- $I = 0$ → lista publica **"Depósitos manuales 2026-08 · US$1.000"** en `/operaciones`
- `manual_deposits = 0` → el botón Borrar devuelve **404 "No hay un movimiento manual para borrar en ese mes"**

El usuario ve un movimiento que él no cargó, que dice "manual", y que no puede borrar.

El caso simétrico (borra un monto distinto al mostrado) requiere `manual_deposits > deposits − I`, lo cual el clamp `max(0.0, ...)` del `_backfill_manual_flows` y el recalc hacen improbable — pero el 404 es reproducible hoy.

#### d. Dictamen
**Correcta: la columna `manual_deposits` (el borrado).** Desde que existen las columnas `manual_*` y el recalc las trata como fuente autoritativa (`main.py:9551-9586`), la heurística `total − imports` es un residuo. El propio comentario del recalc lo dice: *"Ya NO inferimos el residual con la heurística `existing − imports`"*. La lista se quedó con la versión vieja.

`main.py:12711` es un **PARCHE**: la heurística existía porque antes no había columna. La causa real que el parche tapaba (el doble-conteo import/manual) ya se arregló estructuralmente; el parche se quedó y ahora produce un tipo de error distinto.

#### e. Qué ve mal el usuario y dónde
**`/operaciones`** (`Operations.jsx`, `GET /api/movements`): filas fantasma "Depósitos manuales YYYY-MM" que no se pueden borrar. No distorsiona ningún % —el monto que muestra es el mismo que ya está en el aportado— pero es una fila inventada y un 404 sin salida.

#### f. Causa raíz
**Migración a medio hacer.** Las columnas `manual_*` reemplazaron a la heurística en el escritor (`_recalc`) y en el borrador, pero no en el lector.

#### g. Fuente única de verdad propuesta
`main.py:12703-12712` debe leer `manual_deposits` / `manual_withdrawals` directo, igual que el DELETE. Y el helper que decide "cuánto de este mes es manual" debería ser una función única (`_manual_flows_for_period`) usada por lista, borrado y export.

---

### DIV-035 — El CSV "para el contador" doble-cuenta todo flujo importado

**Estado de las citas:** ✅ verificadas
- `main.py:12640-12662` → ✅ (el bloque de la resta en `/api/movements`).
- `main.py:13445-13468` → ✅ (paso 1 del export; `tx_rows` en `:13446`).
- `main.py:13636` → ✅ (`"DEPOSIT": "DEPÓSITO"` dentro de `_humanize_tx_type`, def en `:13629`).
- `main.py:13560-13595` → ✅ (paso 4, `me_rows` en `:13560`).

#### a. Implementaciones

**Paso 1 — `main.py:13446-13468`**: `SELECT ... FROM import_normalized_tx t JOIN import_batches b WHERE b.status='confirmed' AND t.excluded_at IS NULL` — **sin filtro de `operation_type`**. Vuelca una fila por transacción, con `"tipo": _humanize_tx_type(r["operation_type"])`, que mapea `DEPOSIT → "DEPÓSITO"` y `WITHDRAW → "RETIRO"`.

**Paso 4 — `main.py:13560-13595`**: `SELECT year, month, broker, deposits, withdrawals FROM monthly_entries WHERE broker != 'global' AND (deposits > 0 OR withdrawals > 0)` y vuelca `"monto": r["deposits"]` **entero**, con la nota "Total depósitos YYYY-MM (fecha aproximada al 15)".

Y `monthly_entries.deposits = imports_confirmados + manual` (invariante del recalc, `main.py:9584`). O sea: paso 4 incluye lo que paso 1 ya volcó.

**Contraste:** `/api/movements` (`main.py:12640-12712`) sí hace la resta, con un comentario de 20 líneas explicando exactamente por qué. Ese razonamiento no llegó al export.

#### b. Fórmulas
Para un mes/broker con $I$ de depósitos importados y $M$ de depósitos manuales:

- CSV: $\texttt{Σ DEPÓSITO} = \underbrace{I}_{\text{paso 1}} + \underbrace{(I + M)}_{\text{paso 4}} = 2I + M$
- Correcto: $I + M$

Error = $I$, o sea **el 100 % de lo importado**.

#### c. ¿Real o cosmética? — **REAL, error del 100 % sobre el componente importado**

Usuario que importó su historial de Cocos con US$5.000 de depósitos y cargó US$1.000 a mano:
- CSV: 5.000 (13 filas de import) + 6.000 (una fila "Total depósitos") = **US$11.000**
- Real: **US$6.000**

Y a `/api/export/monthly.csv` (`main.py:13644`) no le pasa lo mismo: ese exporta sólo `monthly_entries`. Así que los dos CSV que el mismo usuario le manda al contador no cierran entre sí.

#### d. Dictamen
**Ninguna de las dos como está.** El export tiene que hacer la misma resta que `/api/movements`: paso 4 debe volcar sólo el residual manual (`manual_deposits` / `manual_withdrawals`, ver DIV-034), o alternativamente paso 1 debe excluir `DEPOSIT`/`WITHDRAW`. La primera es mejor: preserva la fecha real de cada flujo importado en vez de aplastarla al día 15.

#### e. Qué ve mal el usuario y dónde
**`GET /api/export/transactions.csv`** — el botón "Exportar" de `/operaciones`. El CSV que el usuario le manda a su contador para liquidar impuestos declara el doble de aportes de capital. No afecta ningún % de la app, pero es el artefacto que sale de Rendi hacia afuera.

#### f. Causa raíz
**Fix aplicado en un solo lugar.** El doble-conteo import/manual se diagnosticó y se arregló en `/api/movements` (con documentación extensa), y el segundo consumidor del mismo par de tablas quedó sin tocar.

#### g. Fuente única de verdad propuesta
Extraer un `_flujos_manuales_por_periodo(conn, uid)` que devuelva el residual manual por `(broker, año, mes)`, y usarlo en `/api/movements` (paso 3), `DELETE /api/movements` y `transactions.csv` (paso 4). Tres consumidores, una definición.

---

### DIV-036 — El snapshot que va al modelo de IA suma el agregado con su propio desglose

**Estado de las citas:** ⚠️ 1 corregida + 1 sitio faltante
- `main.py:11971` → ✅ (`rows = conn.execute("SELECT * FROM monthly_entries ...")` en `get_monthly`, def en `:11960`).
- `main.py:25377` → ✅ (el `_note` del tool `get_monthly_entries`, `:25377-25382`).
- ⚠️ `AICoachDrawer.jsx:178` → **corregida la ruta: `frontend/src/components/ai/AICoachDrawer.jsx:178`** (no está en `components/` a secas).
- 🆕 **Sitio no mapeado: `frontend/src/pages/RendiAI.jsx:171-172`** — copia byte-idéntica de `buildSummary`.

#### a. Implementaciones

**`GET /api/monthly` — `main.py:11960-11976`**
```python
rows = conn.execute("SELECT * FROM monthly_entries WHERE user_id=? ORDER BY year, month, broker", (uid,))
return [dict(r) for r in rows]
```
Devuelve TODAS las filas: la de `broker='global'` (agregado cross-broker) **más** una por cada broker real. Sin `_note`, sin flag.

**`buildSummary` — `components/ai/AICoachDrawer.jsx:167-190` y `pages/RendiAI.jsx:162-185`** (idénticas)
```js
const sumDeposits    = (monthly || []).reduce((acc, m) => acc + (m.deposits    || 0), 0)
const sumWithdrawals = (monthly || []).reduce((acc, m) => acc + (m.withdrawals || 0), 0)
const sumPnlRealized = (monthly || []).reduce((acc, m) => acc + (m.pnl_realized|| 0), 0)
const monthsCount    = (monthly || []).length
```
Sin filtrar por broker. Alimentado directo desde `api.get('/monthly')` (`AICoachDrawer.jsx:45,60` y `RendiAI.jsx:63,71`).

**El backend lo sabe — `main.py:25377-25382`** (tool `get_monthly_entries` del chat):
> *"Las filas con broker='global' son el AGREGADO cross-broker del mes (en USD); las demás son el desglose por broker. NO sumes 'global' con las por-broker — duplicarías."*

#### b. Fórmulas
Con $K$ brokers y el invariante $\texttt{global}_m = \sum_{k} \texttt{broker}_{k,m}$ (que el recalc garantiza, `main.py:9566-9573`):

$$\texttt{deposits\_lifetime} = \sum_m \texttt{global}_m + \sum_m\sum_k \texttt{broker}_{k,m} = 2\sum_m \texttt{global}_m$$

**Exactamente 2×.** Lo mismo para `withdrawals_lifetime` y `realized_pnl_usd_lifetime`. Y `months_tracked` = número de FILAS = $M \times (K+1)$, no $M$.

#### c. ¿Real o cosmética? — **REAL, factor 2 exacto**

Usuario con 12 meses y 3 brokers, US$10.000 de depósitos totales:
- `deposits_lifetime` = **20.000** (debería ser 10.000)
- `withdrawals_lifetime` = **2×** lo real
- `realized_pnl_usd_lifetime` = **2×** lo real
- `months_tracked` = **48** (debería ser 12)

El modelo recibe esto como hecho y lo cita. Si además `_bench_cache` lo marca `_note: "Retornos REALES precalculados — citalos, NO hagas aritmética nueva"` (patrón que `main.py:32665-32671` documenta para otro campo), el modelo no tiene forma de detectar el error.

#### d. Dictamen
**Correcta: sumar sólo `m.broker === 'global'`** — que es lo que hacen `insightsModel.netCapitalContributed`, `Dashboard.jsx:223` y `HomeMobile.jsx:136`, todos con el filtro puesto. Las dos copias de `buildSummary` son las únicas del repo que se lo olvidaron.

`months_tracked` debería ser `new Set(monthly.map(m => \`${m.year}-${m.month}\`)).size`.

#### e. Qué ve mal el usuario y dónde
- **`/ai`** (página Rendi AI, `RendiAI.jsx:171`) y el **drawer del Coach IA** (`AICoachDrawer.jsx:187`, disponible desde toda la app).
- El modelo afirma en lenguaje natural que el usuario depositó el doble de lo que depositó, y cualquier retorno que derive de ahí (`valor / deposits_lifetime`) queda a la mitad.
- El % de retorno distorsionado: si el valor real es $V$ y el aportado real $A$, el modelo calcula $V/2A - 1$ en vez de $V/A - 1$. Con $V=84.000$, $A=70.000$: dice **−40 %** donde el real es **+20 %**.

#### f. Causa raíz
**Frontend recalculando lo que el backend ya sabe, sobre un payload ambiguo.** `GET /api/monthly` devuelve dos tipos de fila en la misma lista sin discriminador, y el backend ya escribió el warning… en OTRO endpoint (el tool del chat). La advertencia existe pero no está donde se necesita.

#### g. Fuente única de verdad propuesta
- Agregar el `_note` (o mejor: un campo `scope: 'global' | 'broker'`) a `GET /api/monthly`.
- Reemplazar las dos `buildSummary` por **una** función compartida en `utils/` que filtre `broker === 'global'` y reuse `netCapitalContributed`.
- Idealmente el summary lo arma el backend, que ya tiene `_portfolio_snapshot_summary`.

---

### DIV-037 — Siete denominadores Modified Dietz

**Estado de las citas:** ⚠️ 2 corregidas
- `builder.py:790` → ✅ exacto (`avg = start_value + 0.5 * flows`).
- `main.py:33026` → ✅ exacto (`avg = start + 0.5 * net_flows`).
- ⚠️ `main.py:35700` → **corregida: `:35701`** (`dietz_base = v0 + flows_usd / 2.0`; el guard `> 100` en `:35702`).
- `Insights.jsx:675` → ✅ exacto.
- `evolution.js:536` → ✅ exacto.
- ⚠️ `useMonthlyData.js:378` → **corregida: `:379`** (`const avgCapital = (startUsd || 0) + 0.5 * flows`).
- `insightsMetrics.js:63` → ✅ (comentario en `:63`, `const denom = start + netFlow * 0.5` en `:64`).

#### a-b. Implementaciones y fórmulas

Notación: $V_0$ = valor inicial, $V_1$ = valor final, $\Phi$ = flujos netos del período, $\rho = |\Phi| / V_0$.

| # | ubicación | denominador $D$ | guard | consumidor |
|---|---|---|---|---|
| 1 | `builder.py:789-793` | $V_0 + 0{,}5\Phi$ | $D \le 0 \Rightarrow$ `None` | `GET /api/reportes` → `/analisis?tab=reportes` |
| 2 | `main.py:33025-33027` | $V_0 + 0{,}5\Phi$ | $D \le 0 \Rightarrow$ `None` | KPI "YTD" de `/analisis?tab=reportes` |
| 3 | `main.py:35701-35703` | $V_0 + \Phi/2$ | $D \le 100 \Rightarrow$ **no publica** | informe firmado del asesor (`/clientes`) |
| 4 | `Insights.jsx:672-676` | $\begin{cases}\Phi & \text{si } i{=}0 \wedge V_0{=}0 \wedge \Phi{>}0\\ V_0 & \text{si } \Phi{<}0 \wedge \rho{>}0{,}3\\ V_0+0{,}5\Phi & \text{si no}\end{cases}$ | $r \ge -0{,}99$ | curva TWRR de `/analisis?tab=diagnostico` |
| 5 | `evolution.js:534-537` | $\begin{cases}V_0 & \text{si } \Phi{<}0 \wedge \rho{>}0{,}3\\ V_0+0{,}5\Phi & \text{si no}\end{cases}$ | $r \ge -0{,}99$ | gráfico diario de `/analisis?tab=diagnostico` |
| 6 | `useMonthlyData.js:379` | $V_0 + 0{,}5\Phi$ | $D \le 0 \Rightarrow 0\%$ | `/mensual` + `MonthlyTeaser` |
| 7 | `insightsMetrics.js:64-65` | $V_0 + 0{,}5\Phi$ | $D \le 100 \Rightarrow$ **saltea el mes**; $\|r\|>3 \Rightarrow$ saltea | volatilidad / Sharpe / beta de `/analisis` |

Numerador, en todas: $\Pi = V_1 - V_0 - \Phi$. Retorno: $r = \Pi / D$.

#### c. ¿Real o cosmética? — **REAL en 4 de las 7; el resto difiere sólo en el guard**

Las variantes 1, 2, 6 y 7 son **la misma fórmula**; difieren únicamente en el umbral que decide publicar (0, 0, 0, 100). Las 3, 4 y 5 son fórmulas distintas.

**Caso A — primer mes con import inicial.** $V_0 = 0$, $\Phi = +50.000$, $V_1 = 52.000$. $\Pi = 2.000$.
| variante | $D$ | $r$ |
|---|---:|---|
| 1/2/6/7 (Dietz puro) | 25.000 | **+8,00 %** |
| 4 (`isImportInitial`) | 50.000 | **+4,00 %** |
| 5 | 25.000 | +8,00 % |

Factor **2×** entre `/mensual` y `/analisis?tab=diagnostico`, el mismo mes.

**Caso B — retiro grande.** $V_0 = 100.000$, $\Phi = -70.000$, $V_1 = 50.000$. $\Pi = +20.000$.
| variante | $D$ | $r$ |
|---|---:|---|
| 1/2/6/7 | 65.000 | **+30,77 %** |
| 4/5 (`isBigWithdraw`) | 100.000 | **+20,00 %** |

**Caso C — mes chico.** $V_0 = 80$, $\Phi = 0$, $V_1 = 95$. $\Pi = 15$.
| variante | $D$ | resultado |
|---|---:|---|
| 1/2/6 | 80 | **+18,75 %** |
| 3/7 | 80 | **"—"** (no publica) |

#### d. Dictamen
**Correcta: la variante 1 (`builder._modified_dietz_pct`) — Dietz puro sin heurísticas.** Razones:
1. Es la única con docstring que declara explícitamente su contrato (no clampa, devuelve `None` cuando el promedio es ≤0).
2. Las heurísticas de 4 y 5 (`isBigWithdraw`, `isImportInitial`) **no son Modified Dietz**: son suposiciones sobre CUÁNDO ocurrió el flujo, tomadas a partir de su tamaño. La forma correcta de resolver eso no es una heurística por umbral, es usar la fecha real del flujo (Dietz ponderado por días) — que es exactamente lo que `twr._aportado_por_punto:1043` señala como el ideal pendiente: *"reconstruir el aportado desde las FECHAS REALES de los movimientos"*.
3. El umbral de 0,3 y el peso 0,5 son números mágicos sin derivación. Un retiro del 29 % usa un denominador y uno del 31 % usa otro, con un salto discontinuo en el resultado.

Las heurísticas de 4 y 5 son **PARCHES**: tapan el spike que produce un flujo grande mal fechado, en dos de los siete sitios. La causa real —`monthly_entries.manual_*` no guarda la fecha del flujo, sólo el mes— sigue rompiendo en los otros cinco.

Sobre los guards: el de 3 y 7 (no publicar con $D \le 100$) es sano; el de 6 (devolver `0 %`) es peor que `None` — publica un cero que parece un dato.

#### e. Qué ve mal el usuario y dónde
El mismo mes rinde distinto según dónde lo mire:
- **`/analisis?tab=reportes`** — "P&L del período" %: variante 1. YTD: variante 2.
- **`/analisis?tab=diagnostico`** — curva TWRR mensual: variante 4. Gráfico diario: variante 5. Volatilidad / Sharpe / beta: variante 7 (con meses SALTEADOS, o sea sobre un universo distinto de retornos).
- **`/mensual`** y el teaser del Dashboard — variante 6.
- **`/clientes`** → el **informe que el asesor firma** — variante 3.

En el caso A eso es +8,00 % en `/mensual` y +4,00 % en `/analisis`, el mismo mes, el mismo usuario, en dos clics.

#### f. Causa raíz
**Copiar y pegar + heurísticas anti-spike agregadas de a una, en el sitio donde apareció el spike.** Ningún archivo importa el Dietz de otro; los siete lo escriben. Y cuando un caso feo apareció en Insights, se arregló en Insights.

#### g. Fuente única de verdad propuesta
- Backend: `builder._modified_dietz_pct` es la única. `main.py:33025-33027` y `main.py:35701-35703` deben llamarla.
- Frontend: **un** `utils/dietz.js` con la misma fórmula y el mismo guard, importado por `Insights.jsx`, `evolution.js`, `useMonthlyData.js` e `insightsMetrics.js`. Borrar las 4 copias.
- Y la deuda de fondo: guardar la FECHA de los flujos manuales (`manual_deposits_date` o una tabla de movimientos con fecha) para poder hacer Dietz ponderado por días y retirar las heurísticas.

---

### DIV-038 — El par padre ↔ "· USD" en el aportado

**Estado de las citas:** ⚠️ **1 sustantivamente incorrecta**
- `main.py:32700` → ✅ exacto.
- `builder.py:735` → ✅ (la función en `:716`).
- ⚠️ `main.py:33019` → **corregida: `:33021`**, y **la afirmación del mapa es incorrecta**. Ver abajo.
- `snapshots_job.py:348-362` → ✅ (el bloque del docstring que se niega a aceptar listas con baseline).

#### a. Implementaciones

**`_portfolio_snapshot_summary` — `main.py:32699-32703`** y **`fetch_cum_deposits_until` — `builder.py:735-742`**: idénticos.
```python
sum(compute_net_deposited_db(conn, uid, broker_filter=b, include_baseline=False)
    for b in brokers_del_filtro(conn, uid, broker_filter))
```
`brokers_del_filtro` (`builder.py:102-128`) resuelve el par por `parent_broker_id` vía `broker_pair` — la definición única del repo, no parsea el sufijo `" · USD"`.

**`_ytd_delta` — `main.py:32948-32999`**: el mapa dice que *"usa `broker = ?` a secas y no vería al sibling"*. **Falso.** La función corta en `main.py:32979`:
```python
if broker_filter != "global":
    return None
```
y el comentario de `:32961-32978` documenta que además es un no-op medido porque `_portfolio_snapshot_summary` fuerza `snap_value = None` para no-global. Las dos queries con `broker = ?` (`:32985` y `:32021`) **sólo se ejecutan con `broker_filter == 'global'`**, donde el par no existe.

El comentario incluso enumera las dos trampas latentes (el `ORDER BY month ASC LIMIT 1` que elegiría una fila arbitraria del par; y el arranque medido que se saltea para no-global). O sea: el hallazgo del mapa ya estaba escrito en el código, con más precisión.

#### b. Fórmulas
Para un par $\{p, p_{\text{USD}}\}$ y `include_baseline=False`, la función es una suma pura:

$$\sum_{b \in \{p,\, p_{\text{USD}}\}} \Big(\sum_m \text{dep}_{b,m} - \text{wd}_{b,m}\Big) = \sum_m \sum_b (\text{dep} - \text{wd})$$

que es **exactamente** la query con `broker IN (p, p_USD)`. Suma-de-sumas = suma. ✅

Con baseline **prendido** no lo sería: $\sum_b \big(B_b + F_b\big) = B_p + B_{p_{\text{USD}}} + F$, o sea **dos baselines**. El docstring de `snapshots_job.py:352-362` reporta el caso medido: *"600 vs 1270 sobre el mismo fixture, y los dos números están mal"*.

#### c. ¿Real o cosmética? — **COSMÉTICA**

Las dos vías activas (`_portfolio_snapshot_summary` y `fetch_cum_deposits_until`) dan **el mismo número**, verificado línea por línea: el mismo helper, el mismo flag, la misma iteración. La tercera (`_ytd_delta`) no corre nunca con un par.

#### d. Dictamen
**Correcta la que hay.** La decisión de sumar el par desde el caller con `include_baseline=False`, en vez de ampliarle la firma a la SSoT, está bien fundada y documentada. La única objeción real es que `include_baseline=False` es la convención equivocada (DIV-029) — pero eso es DIV-029, no DIV-038.

Nota: `main.py:32713-32720` (`positions_count`) sí usa `br_clause` con `broker IN (...)` del par, así que el reporte filtrado es consistente. Y `cash_value` está explícitamente excluido del par (`main.py:32654`).

#### e. Qué ve mal el usuario y dónde
**Nada hoy.** Es una trampa latente en `_ytd_delta` para el día que se agregue valuación por broker.

#### f. Causa raíz
No aplica: no hay divergencia. **Cita del mapa incorrecta** (ver sección al final).

#### g. Fuente única de verdad propuesta
Ninguna acción. Si algún día hace falta el baseline de un par, el docstring de `snapshots_job.py:357-362` ya dice qué escribir: agregar `capital_inicio` por mes ANTES de elegir el primero, no un `IN` en el `WHERE`.

---

### DIV-039 — Mobile carga los depósitos sin fecha

**Estado de las citas:** ✅ verificadas
- `Positions.jsx:1034` → ✅ exacto (`date: cashFlowForm.date` dentro de `confirmCashFlow`, def en `:1023`).
- `Positions.jsx:2872-2878` → ✅ (el `<DateInput>` con `max` = hoy).
- `PositionsMobile.jsx:370-390` → ✅ (`confirmCashFlow` sin `date`). Confirmado por grep: **`cashFlowForm.date` no aparece ni una vez** en `PositionsMobile.jsx`; el modal (`:1656-1706`) sólo tiene monto.

#### a. Implementaciones

**Desktop — `Positions.jsx:1032-1041`**
```js
await api.post('/cash/flow', {
  broker_name, direction, amount,
  date: cashFlowForm.date,
  tc_blue: tcValuacion,   // fallback
})
```

**Mobile — `PositionsMobile.jsx:377-390`**
```js
await api.post('/cash/flow', {
  broker_name, direction, amount,
  tc_blue: tcValuacion,   // ← el fix de tc_blue SÍ llegó a mobile
})
```
El comentario de `:381-388` documenta que `tc_blue` faltaba y se emparejó con desktop. **`date` quedó afuera del mismo fix.**

**Backend — `main.py:10180-10202`**
```python
now = datetime.utcnow()
_fy, _fm = now.year, now.month
if data.date:
    _fd = datetime.strptime(data.date, "%Y-%m-%d"); _fy, _fm = _fd.year, _fd.month
...
if currency == 'ARS':
    _rate = _fx.fx_for_date(conn, data.date, fallback=data.tc_blue) or data.tc_blue
    amount_usd = data.amount / _rate
```
Y `fx.fx_for_date` → `fx_for_date_detail` (`fx.py:82-83`):
```python
if conn is None or not date_str:
    return (fallback, "fallback" if fallback else None)
```
**Sin `date`, el MEP histórico ni se consulta: devuelve el `tc_blue` del cliente**, que es el `tcValuacion` de hoy.

#### b. Fórmulas
Para un movimiento real de fecha $d^{*}$ y monto $a$ ARS:

- Desktop: mes = $\text{mes}(d^{*})$, $\text{USD} = a / \text{MEP}(d^{*})$
- Mobile: mes = $\text{mes}(\text{hoy})$, $\text{USD} = a / \text{MEP}(\text{hoy})$

Error relativo del monto: $\dfrac{\text{MEP}(d^{*})}{\text{MEP}(\text{hoy})} - 1$. Error de imputación: el flujo entero cambia de mes.

#### c. ¿Real o cosmética? — **REAL, doble error**

Usuario que el 7/9/2026 carga desde el celular un depósito de $1.000.000 ARS que hizo el **15/3/2026**. MEP del 15/3 = 1.100; MEP de hoy = 1.415.

| | mes imputado | USD asentado |
|---|---|---:|
| Desktop | 2026-03 | **909,09** |
| Mobile | 2026-09 | **706,71** |

- **Monto:** −22,3 % de error sobre el aportado de ese flujo.
- **Mes:** marzo queda con un depósito de menos → su Dietz publica el aporte como rendimiento. Con $V_0 = 10.000$ y $V_1 = 10.900$ en marzo: desktop dice $\Pi = 10.900 - 10.000 - 909 = -9$ → ≈ **0 %** (correcto: el valor subió por el aporte). Mobile dice $\Pi = 900$, $D = 10.000$ → **+9,0 %** de ganancia que no existió. Y septiembre queda con un aporte de más → su mes publica **−6,3 %** de pérdida fantasma.

Y como el aportado es el denominador, el retorno total del usuario también queda corrido en el 22,3 % de ese flujo.

#### d. Dictamen
**Correcta: la desktop.** Y el backend hace lo correcto cuando recibe `date` (`fx_for_date` prefiere el MEP del día, cae al blue histórico, y sólo de último recurso al rate del cliente). El bug es puramente de paridad de formulario.

#### e. Qué ve mal el usuario y dónde
**Todo cash flow cargado desde el celular** (`/posiciones` en viewport mobile → botón Cash → modal "Depositar en / Retirar de", `PositionsMobile.jsx:1656`). Impacta:
- El aportado total (denominador de `/dashboard`, `/`, `/analisis?tab=reportes`).
- El % del mes en curso (inflado por el aporte mal imputado) y el % del mes real (deflactado).
- La curva de evolución: un escalón en el mes equivocado.

#### f. Causa raíz
**Paridad mobile/desktop incompleta.** El campo de fecha se agregó a desktop y el modal mobile no se actualizó. El fix de `tc_blue` pasó por el mismo lugar y arregló sólo la mitad.

#### g. Fuente única de verdad propuesta
Extraer el modal de cash flow a un componente compartido (`components/CashFlowModal.jsx`) usado por `Positions.jsx` y `PositionsMobile.jsx`. Mientras tanto, agregar el `<DateInput>` a `PositionsMobile.jsx:1670` y `date: cashFlowForm.date` a `:380`.

**Mitigación de servidor recomendada:** `CashFlowIn` debería exigir `date` (o el endpoint rechazar el request sin fecha) en vez de caer en silencio a hoy — un campo faltante no debería producir un dato plausible pero equivocado.

---

### DIV-040 — "Ausente ≠ negativo": tres copias, no cuatro, y las tres coinciden

**Estado de las citas:** ⚠️ **1 sustantivamente incorrecta**
- `evolution.js:254-268` (`netDepositedOf`) → ✅.
- `evolution.js:194` → ✅ (`netDeposited: +(s.net_deposited || s.total_invested || 0)`).
- `main.py:32932-32934` (`_snapshot_delta`) → ✅ exacto.
- ❌ `twr.py:1047` → **incorrecta.** La línea real es:
  ```python
  canon = netdep_canonico(conn, uid)          # :1045
  if canon is None:                            # :1046
      return lambda r: float(r["net_deposited"] or 0)   # :1047
  ```
  Eso **no es** la regla "ausente ≠ negativo": no cae a `total_invested` en ningún caso. Verifiqué con `grep -n "total_invested" backend/twr.py`: la única aparición en todo el archivo es `:1310`, dentro de un `SELECT`. `twr.py` **nunca** aplica ese fallback. Es una convención distinta (y más estricta), no una cuarta copia.

#### a. Implementaciones

| # | ubicación | expresión |
|---|---|---|
| 1 | `evolution.js:266-267` | `(nd != null && nd !== 0) ? nd : (s?.total_invested \|\| 0)` |
| 2 | `evolution.js:194` | `+(s.net_deposited \|\| s.total_invested \|\| 0)` |
| 3 | `main.py:32932-32934` | `nd = float(prev["net_deposited"] or 0); if nd == 0: nd = float(prev["total_invested"] or 0)` |

#### b. Fórmulas
$$N(s) = \begin{cases} s.\texttt{net\_deposited} & \text{si } \ne 0 \text{ y presente} \\ s.\texttt{total\_invested} & \text{si no}\end{cases}$$

#### c. ¿Real o cosmética? — **COSMÉTICA**

El mapa afirma que `evolution.js:194` *"usa `||` en vez del helper"* y sugiere que por eso difiere. **En JavaScript no difiere:** `||` cae al siguiente operando sólo con valores *falsy* (`0`, `NaN`, `null`, `undefined`, `''`). Un `net_deposited` **negativo es truthy**, así que `-1789 || total_invested` devuelve `-1789` — exactamente lo que hace `netDepositedOf`. Las dos expresiones son equivalentes para todo valor numérico salvo `NaN` (caso que no se da: la columna es `NOT NULL DEFAULT 0`).

Las 4.744 filas con `net_deposited < 0` que el comentario de `evolution.js:257-262` reporta **pasan bien por las dos**.

#### d. Dictamen
**Las tres son correctas y equivalentes.** El comentario de `evolution.js:505-511` que dice *"ahora hay UNA sola y es la de arriba"* es impreciso (queda la de `:194`), pero no miente sobre el resultado: la que quedó calcula lo mismo.

Riesgo real: **drift futuro**, no error presente. Si mañana alguien cambia `netDepositedOf` (por ejemplo, para distinguir `0` legítimo de `0` por defecto), `:194` no se entera.

#### e. Qué ve mal el usuario y dónde
**Nada.** Ningún número está mal por esto hoy.

#### f. Causa raíz
Copiar y pegar. La regla se arregló en `netDepositedOf` y en `_snapshot_delta` (con comentarios extensos y un caso medido: el chip Δ1d publicando **+122,77 %** sobre una cartera quieta), pero la línea de `:194` nunca se tocó porque su `||` ya daba el resultado correcto por accidente.

#### g. Fuente única de verdad propuesta
`evolution.js:194` → `netDeposited: netDepositedOf(s)`. Cambio de una línea, cero impacto numérico, elimina el riesgo de drift. Y en el backend, extraer `_snapshot_delta`'s `prev_netdep` a un helper si aparece un tercer call site.

---

## Parches detectados

| ubicación | qué síntoma tapa | causa real | dónde más sigue rompiendo |
|---|---|---|---|
| `persister.py:1126-1141` (`_persist_fx`, "FIX bug #1") | aportado subvaluado tras importar conversiones ARS→USD | el `DEPOSIT` en pesos se dolariza a `config.tc_blue` (estático, default 1415) y no al MEP de la fecha | **todo flujo ARS importado**: `_import_flows_for_period` (`main.py:606`) usa el mismo `tc_blue` como fallback cuando `gross_amount_usd` es NULL; `/api/movements` (`main.py:12665-12676`) idem; `_backfill_manual_flows` (`main.py:643-647`) idem |
| `Reports.jsx:596-607` (guard `noBasis`) | "+1565,9 %" en la tarjeta de retorno sobre aportes | el denominador está sin baseline (`include_baseline=False`) | `builder.py:1533-1536` (`delta_pct_over_contrib`) usa el mismo denominador chico sin ningún guard |
| `Insights.jsx:672-675` y `evolution.js:534-536` (`isBigWithdraw`, `isImportInitial`) | spikes de Dietz cuando un flujo grande cae a mitad de mes | `monthly_entries.manual_*` no guarda la FECHA del flujo, sólo el mes → no se puede ponderar por días | `builder.py:790`, `main.py:33026`, `main.py:35701`, `useMonthlyData.js:379`, `insightsMetrics.js:64` — los otros 5 Dietz siguen expuestos al mismo spike, sin heurística |
| `main.py:12711` (`max(0, deposits − imports)`) | doble-conteo import/manual en la lista de movimientos | las columnas `manual_*` ya son la fuente autoritativa desde el recalc | produce ahora un error nuevo: filas fantasma no borrables (DIV-034). Y `transactions.csv` (`main.py:13560`) ni siquiera tiene el parche → doble-cuenta de verdad |
| `main.py:9143` (`_autodeposit_if_overdraw` en plazos fijos) | cash negativo al abrir un PF mayor al saldo | los PF no escriben `monthly_entries` en ningún caso | el PF fondeado desde afuera (sin `source_broker`) no registra nada; y `_adjust_broker_cash(-capital)` en `:9144` saca cash sin contrapartida contable |
| `demo.js:594` (`min(rawCum, 0,85 × valor)`) | la demo mostraba retorno negativo | el fixture de `MONTHLY` no cierra con `MONTHLY_LAST_VALUATION` | sólo demo — pero significa que el número de la demo no es reproducible por la fórmula real |
| `main.py:35702` (`if dietz_base > 100`) | porcentajes absurdos en el informe firmado del asesor | denominador de Dietz sin piso en todas las demás vías | `builder.py:791` y `main.py:33027` usan `> 0`; `useMonthlyData.js:381` usa `> 0` y publica `0 %`; sólo `insightsMetrics.js:65` comparte el umbral 100 |

---

## Citas del mapa incorrectas

| DIV | cita del mapa | ubicación real | qué decía mal |
|---|---|---|---|
| DIV-031 | `backend/importing/fx_migrate.py:88-92` | `fx_migrate.py:91-92` | desvío de 3 líneas; el bloque de comentario empieza en `:73` |
| DIV-032 | `backend/importing/persister.py:1139-1143` | `persister.py:1138-1141` | desvío de 1-2 líneas |
| DIV-033 | `snapshots_job.py:766` | `snapshots_job.py:767` | desvío de 1 línea |
| DIV-033 | `persister.py:1250` | `persister.py:1266` (función en `:1230`) | desvío de 16 líneas |
| DIV-033 | `main.py:15546` | función `_recompute_snapshots_netdep_for_user` en `main.py:15508`; el uso de `_aportado_por_punto` en `:15550` | `:15546` cae dentro de un comentario |
| DIV-033 | `main.py:37040` | `main.py:37043-37047` | desvío de 3 líneas |
| DIV-036 | `AICoachDrawer.jsx:178` | `frontend/src/components/**ai/**AICoachDrawer.jsx:178` | ruta incompleta; falta el subdirectorio `ai/` |
| DIV-036 | (no citado) | 🆕 `frontend/src/pages/RendiAI.jsx:162-185` | **sitio faltante**: segunda copia byte-idéntica de `buildSummary` |
| DIV-037 | `main.py:35700` | `main.py:35701` | desvío de 1 línea |
| DIV-037 | `useMonthlyData.js:378` | `useMonthlyData.js:379` | desvío de 1 línea |
| **DIV-038** | *"`_ytd_delta` usa `broker = ?` a secas (main.py:33019) y no vería al sibling"* | `main.py:33021`; y `main.py:32979` corta con `if broker_filter != "global": return None` | **incorrecta en sustancia**: la función nunca corre con un broker. El código ya documenta la trampa latente en `:32961-32978`, con más detalle que el mapa |
| **DIV-040** | *"y el fallback de `twr.py:1047`"* como cuarta copia de "ausente ≠ negativo" | `twr.py:1045-1047` es `if canon is None: return lambda r: float(r["net_deposited"] or 0)` | **incorrecta en sustancia**: no aplica el fallback a `total_invested`. `grep total_invested backend/twr.py` → una sola línea, un `SELECT`. Son 3 copias, no 4 |
| DIV-040 | *"evolution.js:194, con `\|\|` en vez del helper"* implicando divergencia | `evolution.js:194` | la cita es correcta pero **la conclusión no**: `\|\|` es equivalente a `netDepositedOf` para todo número (un negativo es truthy). Cosmética, no real |
| DIV-029/031 | (no citado) | 🆕 `main.py:9639-9652` | **sitio faltante y el más importante del grupo**: el recalc pone `capital_inicio = 0` en el primer mes de todos los brokers, `'global'` incluido |

---

## URGENTE

### El recalc borra el baseline que el usuario cargó a mano — `backend/main.py:9639-9652`

```python
    # Para brokers que SÍ tienen actividad, resetear capital_inicio del primer
    # mes a 0 (es la "baseline" y debería empezar en 0 si nada precede al
    # primer movimiento; _repair_monthly_chain propaga forward desde ahí).
    for b in brokers_touched:
        first = conn.execute(
            """SELECT id FROM monthly_entries
               WHERE user_id=? AND broker=?
               ORDER BY year ASC, month ASC LIMIT 1""",
            (uid, b),
        ).fetchone()
        if first:
            conn.execute(
                "UPDATE monthly_entries SET capital_inicio=0 WHERE id=?",
                (first["id"],),
            )
```

**Verificado:**
- `brokers_touched.add(broker)` (`main.py:9607`) corre **incondicionalmente** para cada fila de `monthly_entries`, y esas filas incluyen `broker='global'`. Así que `'global'` siempre está en `brokers_touched`.
- `_repair_monthly_chain` (`main.py:9660-9746`) **no** hace esto: en la primera fila `prev_cap_final is None`, así que `new_cap_inicio = cur_cap_inicio` y el baseline se preserva. El único que lo pone en cero es el recalc.
- La premisa del comentario —*"debería empezar en 0 si nada precede al primer movimiento"*— es exactamente la que NO se cumple para el caso de uso del campo: `capital_inicio` del primer mes es lo que el usuario carga en `/mensual` (`POST /api/monthly`, `main.py:11997-12000`) para declarar lo que ya tenía cuando empezó a trackear. Algo SÍ precede.

**Quién lo dispara:** `main.py:4495` (borrar un broker), `main.py:12370` (cerrar un futuro), `persister.py:1677` (revertir un import), `importing/rebuild.py`, `importing/recompute_backfill.py` (botón admin), `sim_import.py`.

**Consecuencia:** un usuario que declara US$50.000 de capital preexistente y después importa un CSV (o revierte uno, o borra un broker) pierde ese dato **en silencio y sin deshacer**. Su "Capital aportado" en `/dashboard` cae de US$70.000 a US$20.000 de un día para el otro, y su retorno publicado salta de +20 % a +320 % sin que la cartera se haya movido. Los siete consumidores de `include_baseline=True` (cron, Dashboard, HomeMobile, Insights, `_snapshot_delta`, `advisor_alerts`, `builder.py:1446`) leen el 0 y lo dan por bueno.

Es además la razón por la que DIV-029 pasa desapercibida: en cualquier cuenta que ya recalculó, las dos convenciones coinciden porque no queda baseline que las separe.

**Qué hay que decidir (no lo arreglo, es una decisión de producto):** o `capital_inicio` es un dato del usuario y el recalc no puede tocarlo, o no es un dato del usuario y hay que sacar el campo de `/mensual` y de las siete lecturas con baseline. Lo que no puede seguir es que un formulario lo pida y un job lo borre.

**Verificación sugerida antes de tocar nada:** contar en la copia de producción cuántos usuarios tienen `capital_inicio > 0` en su primera fila de `broker='global'` (los que todavía no perdieron el dato) y cuántos tienen exactamente 0 con `deposits` en esa misma fila (candidatos a haberlo perdido).

---

## BLOQUE-RESUMEN

| concepto | DIV | versiones | difieren | correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---|---:|---|---|---|---|---|
| Capital aportado, flujos, depósitos y retiros | DIV-029 | 2 | SÍ (exactamente el baseline) | `compute_net_deposited_db(include_baseline=True)` | `/analisis?tab=reportes` KPI "Capital aportado" y "Retorno sobre aportes" (+320 % vs +20 % del Dashboard) | 🔴 alta | fix en un solo lugar; `include_baseline=False` legitimado como "semántica histórica" |
| Capital aportado, flujos, depósitos y retiros | DIV-030 | 3 | SÍ (±capital del PF; invierte el signo del retorno) | ninguna: falta escribir el flujo en `POST /api/plazos-fijos` | `/dashboard` (duplica el PF interno) y `/` HomeMobile + `/analisis?tab=reportes` (omiten el PF externo) | 🔴 alta | falta de capa compartida: los PF no escriben `monthly_entries` |
| Capital aportado, flujos, depósitos y retiros | DIV-031 | 7 | Mayormente NO; SÍ el fallback MtM y el clamp de demo | `insightsModel.netCapitalContributed` | latente en `/dashboard`; demo con clamp al 85 % | 🟡 media | copiar y pegar; sin helper compartido front↔back |
| Capital aportado, flujos, depósitos y retiros | DIV-032 | 2 | SÍ (+US$293 por cada US$1.000 convertidos, y se autodestruye en el primer recalc) | la manual (`POST /api/conversions`, neta cero) | `/dashboard`, `/`, `/analisis` tras importar Balanz/Cocos/IEB/PPI/inviu con conversiones | 🔴 alta | PARCHE fuera del escritor autoritativo (`_recalc` lo pisa) |
| Capital aportado, flujos, depósitos y retiros | DIV-033 | 4 escritores / 4 lectores | SÍ (caso medido: −37,04 % en un mes plano) | `twr.netdep_canonico` + `twr._aportado_por_punto` | `/analisis?tab=reportes` (Dietz del período), `/clientes` (captación y "efecto mercado"), gráfico de evolución | 🟠 media-alta | migración a medio hacer: el canónico existe y sólo 2 de 6 lo usan |
| Capital aportado, flujos, depósitos y retiros | DIV-034 | 2 | SÍ cuando hay filas no-import no-manual (las FX de DIV-032) | la columna `manual_deposits` | `/operaciones`: movimiento "Depósitos manuales" visible que devuelve 404 al borrar | 🟡 media | heurística vieja sobrevivió a la migración a `manual_*` |
| Capital aportado, flujos, depósitos y retiros | DIV-035 | 2 pasos del mismo endpoint | SÍ (2× cada flujo importado; US$11.000 donde hay US$6.000) | ninguna: hay que restar los imports como en `/api/movements` | `GET /api/export/transactions.csv` (botón Exportar de `/operaciones`) | 🔴 alta | el fix de `/api/movements` no se replicó en el export |
| Capital aportado, flujos, depósitos y retiros | DIV-036 | 2 copias idénticas | SÍ (exactamente 2×; `months_tracked` = filas, no meses) | sumar sólo `broker === 'global'` | Coach IA en `/ai` y en el drawer: el modelo cita el doble de depósitos | 🟠 media-alta | frontend recalculando sobre un payload que mezcla agregado y desglose |
| Capital aportado, flujos, depósitos y retiros | DIV-037 | 7 | SÍ (hasta 2×: +8,00 % en `/mensual` vs +4,00 % en `/analisis`, mismo mes) | `builder._modified_dietz_pct` (Dietz puro, sin heurísticas) | `/analisis?tab=reportes`, `/analisis?tab=diagnostico`, `/mensual`, informe firmado del asesor | 🟠 media-alta | copiar y pegar + heurísticas anti-spike agregadas de a una |
| Capital aportado, flujos, depósitos y retiros | DIV-038 | 3 | NO (las 2 vías activas coinciden; `_ytd_delta` no corre con brokers) | `brokers_del_filtro` + `include_baseline=False` por pata | ninguna hoy (trampa latente ya documentada en el código) | ⚪ cosmética | cita del mapa incorrecta |
| Capital aportado, flujos, depósitos y retiros | DIV-039 | 2 | SÍ (mes equivocado + TC de hoy: −22,3 % sobre el flujo, +9,0 % de ganancia fantasma en el mes real) | desktop (`Positions.jsx`) | todo depósito/retiro cargado desde el celular (`/posiciones` mobile → botón Cash) | 🟠 media-alta | paridad mobile/desktop incompleta (el fix de `tc_blue` arregló la mitad) |
| Capital aportado, flujos, depósitos y retiros | DIV-040 | 3 (no 4) | NO (`\|\|` es equivalente al helper: un negativo es truthy) | `netDepositedOf` / `main.py:32932` | ninguna | ⚪ cosmética | copiar y pegar; riesgo de drift, no de número |
| Capital aportado, flujos, depósitos y retiros | DIV-041 | 1 import muerto | NO hoy (trampa armada) | `insightsModel.js:49` (con fallback `capital_inicio_costo`) | latente: `/dashboard` el día que se llame `applyMtmToMonthly` | 🟡 media | copiar y pegar sin el fix posterior |
