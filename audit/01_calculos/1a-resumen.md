# 1A — Resumen: veredicto sobre implementaciones divergentes

**Tanda 1A · 8 conceptos · 94 de las 166 divergencias.**
Commit auditado: `b74f450f2badf1a2b84e657551115a0595110e45` (copia limpia de solo lectura en `/tmp/rendi-main`).
Deriva: `origin/main` = `82fad6a0` (+1 commit, FCI Ualá). **Ningún hallazgo de esta tanda cae en los 3 archivos de esa deriva.**

## El número

| severidad | divergencias |
|---|---:|
| 🔴 alta | 29 |
| 🟠 media-alta | 34 |
| 🟡 media | 22 |
| ⚪ cosmética | 9 |
| **total** | **94** |

**85 de 94 divergencias dan números distintos de verdad. 9 son cosméticas.**

## Por concepto

| concepto | divs | 🔴 | 🟠 | 🟡 | ⚪ | citas verificadas | informe |
|---|---:|---:|---:|---:|---:|---|---|
| Valuación de cartera / valor de mercado | 15 | 2 | 5 | 4 | 4 | 22 de 22 abiertas y leídas · **13 corregidas** (ninguna cita del mapa era literalmente exacta en línea; ninguna era falsa en sustancia salvo DIV-146, ver abajo) | [`1a-valuacion.md`](1a-valuacion.md) |
| Tenencia / posición / holding | 13 | 2 | 3 | 6 | 2 | 26 de 31 correctas · 5 corregidas | [`1a-tenencia.md`](1a-tenencia.md) |
| Costo de adquisición, costo promedio y lotes FIFO | 13 | 3 | 7 | 3 | 0 | 26 de 32 correctas · 6 corregidas (detalle al final) | [`1a-costo-fifo.md`](1a-costo-fifo.md) |
| Capital aportado, flujos, depósitos y retiros | 13 | 4 | 4 | 3 | 2 | 41 de 53 exactas · 10 corregidas (desvío de 1–16 líneas) · 2 **sustantivamente incorrectas** (DIV-038 sobre `_ytd_delta`, DIV-040 sobre `twr.py:1047`) | [`1a-capital-aportado.md`](1a-capital-aportado.md) |
| Tipo de cambio (blue, MEP, CCL, cripto) | 11 | 5 | 4 | 1 | 1 | 38 de 42 correctas · 4 corregidas · 1 afirmación del mapa refutada por el código | [`1a-fx.md`](1a-fx.md) |
| P&L realizado | 11 | 5 | 4 | 2 | 0 | 36 de 41 correctas · 5 corregidas | [`1a-pnl-realizado.md`](1a-pnl-realizado.md) |
| P&L no realizado / ganancia latente | 9 | 3 | 4 | 2 | 0 | 28 de 36 correctas · 8 corregidas | [`1a-pnl-no-realizado.md`](1a-pnl-no-realizado.md) |
| Rendimiento / retorno (simple, TWR, anualizado, CAGR) | 9 | 5 | 3 | 1 | 0 | 31 de 33 correctas · 2 corregidas (+ 1 typo de path) | [`1a-rendimiento.md`](1a-rendimiento.md) |

## Tabla completa — una fila por divergencia

| concepto | DIV | versiones | ¿difieren de verdad? | cuál es la correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---|---:|---|---|---|---|---|
| Valuación de cartera / valor de mercado | DIV-145 | 2 | SÍ — ×1.360 (pesos contados 1:1 como USD + guard cruzando monedas) | `valuation.js:573-604` (`valuePositionLot` rama 2) | gráfico y Var. día del Dashboard, Reportes, TWR, libro/brief del asesor, chat IA | 🔴 alta | port incompleto al backend (se portó `costInUsd` y no `costInPesos`) |
| Valuación de cartera / valor de mercado | DIV-146 | 2 | SÍ — cae a costo en silencio (−72 % medido) | `snapshots_job._broker_name_sets` (parent-aware) | ídem DIV-145 | 🔴 alta | fix aplicado en un solo lugar del mismo archivo (`build_price_symbols` sí, valuación no) |
| Valuación de cartera / valor de mercado | DIV-147 | 4 | SÍ — ×100 en renta fija con `price_override` | `valuation.js:448` `trustMktValue` | Comportamiento, los 8 builders de IA, Reportes timeline | 🟠 media-alta | re-port perdiendo el parámetro `has_override` + return antes del guard |
| Valuación de cartera / valor de mercado | DIV-148 | 8 (6 bien, 3 mal) | SÍ — 0,5–1 % sistemático, siempre optimista | `invested + commissions` | Comportamiento, chat IA, Análisis, ficha del activo mobile | 🟡 media | falta de una capa compartida (`realCost(p)` no existe) |
| Valuación de cartera / valor de mercado | DIV-149 | 3 (+3 ausencias) | SÍ — el valor íntegro del plazo fijo | ninguna: falta un valuador de patrimonio | Cartera mobile, Análisis, gráfico/Reportes, todo el backend | 🟠 media-alta | activos fuera de `positions` sin dueño en la capa de valuación |
| Valuación de cartera / valor de mercado | DIV-150 | 1 (aislada) | SÍ — el no realizado de futuros no está en ningún patrimonio | ninguna | todas las superficies de patrimonio; salto discreto al cerrar el futuro | 🟡 media | ídem DIV-149 |
| Valuación de cartera / valor de mercado | DIV-151 | 2 | SÍ — ×10 a ×100 entre la fila y el total | el total (`computeBrokerValue`) | Cartera desktop: fila y P&L% del activo | 🟠 media-alta | guard omitido a propósito en una rama de UI |
| Valuación de cartera / valor de mercado | DIV-152 | 2 | SÍ — +45 % (factor `MEP_hoy/tc_compra`) | `valuePositionLot` (fallback a `guardCost`) | `/activo/:ticker` — "Valor actual" sin cotización, en el modo por defecto | 🟠 media-alta | fix aplicado en un solo lugar (copia previa de la matriz) |
| Valuación de cartera / valor de mercado | DIV-153 | 3 | NO — delta 0 verificado caso por caso | `valuePositionLot` | ninguna hoy (deuda estructural) | ⚪ cosmética | copiar y pegar; ninguna designada como origen |
| Valuación de cartera / valor de mercado | DIV-154 | 7 | NO — hoy `tcValuacion === tcCedear` en las 6 páginas | `cedearRate` para todo el path ARS | ninguna hoy; precedente medido de −11,8 % (56.582 vs 64.147) | ⚪ cosmética | copiar y pegar de una versión previa del motor |
| Valuación de cartera / valor de mercado | DIV-155 | 2 | SÍ — −0,69 % diario (punta de venta vs medio) | el MEP MEDIO (`_current_cedear_rate`) | libro, informes y contexto IA del asesor; no coincide con su propio brief diario | 🟡 media | fix aplicado en un solo lugar (`_advisor_book_fx` lee la tabla, no el caché) |
| Valuación de cartera / valor de mercado | DIV-156 | 2 | SÍ — por DIV-145/146 en el valor, y `total_invested` con dos definiciones (modo `purchase` vs MEP de hoy) | el motor del browser (`computeBrokerValue`) | serie histórica completa: gráfico Dashboard, Reportes, TWR | 🟠 media-alta | migración a medio hacer (el cron se sumó al escritor viejo en vez de reemplazarlo) |
| Valuación de cartera / valor de mercado | DIV-157 | 1 | SÍ — ×918 en el ejemplo (pesos + USD sumados 1:1) | ninguna (debería ser `Σ invested/fx(_native_ccy)`) | ninguna hoy — clave muerta del payload de `/api/reports/period/…` | ⚪ cosmética | PARCHE documentado y dejado a propósito |
| Valuación de cartera / valor de mercado | DIV-158 | 1 | SÍ — puede nombrar el activo equivocado | ordenar por valor de mercado (`value_usd` del valuador) | KPI "Top holding" de Reportes | 🟡 media | PARCHE parcial: se arregló la moneda con un `CASE` de SQL, no la valuación |
| Valuación de cartera / valor de mercado | DIV-159 | 1 | SÍ — sin guard, sin `costInPesos/costInUsd`, sin factor cripto, sin rama CEDEAR, broker hardcodeado | `computeBrokerValue` (importable, función pura) | modo demo (`/login` → "Ver demo"), incluido su gráfico de evolución | ⚪ cosmética | fixture escrito a mano con un comentario que afirma una equivalencia que no existe |
| Tenencia / posición / holding | DIV-121 | 9 (+2 backend) | sí — habilita a todas las demás | `valuation.js:543` `valuePositionLot` | ninguna por sí sola; es el vector | ⚪ | migración a medio hacer (SSoT escrita, lectores sin migrar) |
| Tenencia / posición / holding | DIV-122 | 10 | sí — el costo difiere en `commissions` (0,55 pp sobre 10.000/50) | la versión con comisiones (`valuePositionLot`) | Comportamiento, Rendi AI, Reportes, Objetivos, brief del asesor, detalle de posición mobile | 🟡 | fix aplicado en un solo lado (frontend; `behavioral.py` nunca lo recibió) |
| Tenencia / posición / holding | DIV-123 | 4 | sí — hasta ×75 entre fila y pie | la versión con `trustMktValue` | Cartera desktop `/posiciones`: la suma de las filas no da el total | 🟠 | omisión deliberada + copiar y pegar |
| Tenencia / posición / holding | DIV-124 | 2 | sí — ×MEP (US$ 707.000 vs US$ 517) | `valuePositionLot` (6 ramas) | curva del Dashboard, `/reportes`, libro del asesor, variación diaria | 🔴 | port Python incompleto (5 de 6 ramas) |
| Tenencia / posición / holding | DIV-125 | 3 | sí — cotiza otro instrumento (ADR vs `.BA`), P&L fantasma de −US$ 695.500 | `valuationPriceKey` (parent-aware + `positions.currency`) | snapshot/curva/Reportes/libro; Comportamiento y Rendi AI sin `_byma` | 🔴 | falta de capa compartida + port incompleto |
| Tenencia / posición / holding | DIV-126 | 2 | sí — costo vs valor, y por lote (3 lotes de AAPL copan el top 3) | ninguna: valor de mercado agregado por activo | `/reportes` "Top holdings" vs respuesta de Rendi AI | 🟡 | copiar y pegar + falta de SSoT |
| Tenencia / posición / holding | DIV-127 | 2 | sí — 60 lotes vs 5 activos | la de la Cartera (`asset`,`moneda`) | `/reportes` KPI "# posiciones" | 🟡 | falta de SSoT (`COUNT(*)` suelto) |
| Tenencia / posición / holding | DIV-128 | 4 | sí — `H₃` suma CEDEARs y acciones US como la misma unidad | `(broker, asset, currency)` para tenencia; `cedearEspecieBase` valuado para exposición | Home (tarjetas de briefing), chat de Rendi AI, Cartera vs Calidad de cartera | 🟡 | copiar y pegar; no existe un tipo "Holding" |
| Tenencia / posición / holding | DIV-129 | 8 (el mapa decía 7) | sí — rango ×1.450 entre pantallas | descartar y reportar (chat IA / libro del asesor) | `/reportes` top holdings (×MEP), grupos del asesor (÷MEP), Dashboard/Cartera/curva (ausente) | 🟠 | falta de SSoT + brokers linkeados por NOMBRE sin FK |
| Tenencia / posición / holding | DIV-130 | 2 | sí, y está documentado y medido | ambas (miden cosas distintas) | ninguna hoy: el replay no llega a pantalla | ⚪ | por diseño, con `verificar_contra_hoy` como testigo |
| Tenencia / posición / holding | DIV-131 | 2 (3 con el snapshot) | sí — 8,5 % con caché frío (blue 1.400 vs cripto 1.530) | la del frontend: mep→ccl→blue, al medio | curva/snapshot/Reportes vs hero y Cartera, los días que MEP y CCL fallan | 🟠 | fix aplicado en un solo lado (el paso "al medio" no cruzó al backend) |
| Tenencia / posición / holding | DIV-132 | 4 | sí — pesos de la IA inflados 1/(1−%cash) = 1,67× con 40 % en efectivo | ninguna: excluir sólo por falta de precio, y siempre reportarlo | Rendi AI (`weight_pct`), libro del asesor (AUM menor al del cliente), curva con días faltantes | 🟡 | cada capa eligió su política de faltantes |
| Tenencia / posición / holding | DIV-133 | 2 | sí — por el monto del PF (hero US$ 20.000 vs Cartera US$ 10.000) | ninguna: el PF debe entrar al snapshot | hero Dashboard/Home ≠ `/posiciones` ≠ gráfico ≠ `/reportes` ≠ AUM del asesor | 🟡 | migración a medio hacer (PF en tabla aparte, nunca portado al motor) |
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
| Tipo de cambio y conversión de moneda | DIV-134 | 3 | Sí (3,7 % con brecha actual; hasta 15 % histórica) | Ninguna: convertir con el mismo riel con que se dolarizó (MEP de la fecha) | `/dashboard` curva Evolución en Pesos vs. hero; `/` home mobile; `/operaciones` | 🔴 | Migración a medio hacer (`fx_to_usd_blue` es de cuando se valuaba al blue) |
| Tipo de cambio y conversión de moneda | DIV-135 | 6 | Sí (4,1 pp entre `/analisis` y Reportes sobre la misma cartera quieta) | `twr.serie_fx` / `fx.fx_for_date` (MEP diario con red al blue) | `/analisis` gráfico Evolución y cards Comparativa; `/mensual` tabs ARS | 🔴 | Falta de capa compartida; `fx.py` existe y ninguna de las otras 5 series lo importa |
| Tipo de cambio y conversión de moneda | DIV-136 | 5 lectores + 1 escritor | Sí (0,74 % entre el libro del asesor y su propio brief diario) | `fx.py._lookup` para histórico + `_val_rate` medio vivo para hoy | `/clientes` (libro del asesor) vs. brief diario por email | 🟠 | Fix aplicado en un lugar y copiado a mano 3 veces; `mep_venta` NULLABLE con un escritor que no la escribe |
| Tipo de cambio y conversión de moneda | DIV-137 | 5 | Sí (0,74 % medio-vs-punta; 11,3 % en el importador con caché frío) | `_val_rate` (medio con fallback a venta) | Importador (Capital Aportado); `/analisis?tab=reportes` con caché frío; snapshot nocturno frío | 🟠 | Copy-paste + fix parcial: la SSoT se aplicó a 3 funciones y quedaron 3 leyendo `venta` |
| Tipo de cambio y conversión de moneda | DIV-138 | 2 (mismo archivo) | Sí (mismo import, dos dólares; hasta 10× con config stale) | Ninguna: `fx.fx_for_date` por fila, no un TC por batch | `/dashboard` "Capital Aportado" tras importar; `/operaciones` P&L de ventas ARS v1 | 🔴 | Fix aplicado en un solo lugar: `_read_tc_blue` existe 950 líneas abajo y `persist_batch` no lo llama |
| Tipo de cambio y conversión de moneda | DIV-139 | 3 | Sí (`reconcile-cash` divide por 1415 literal: +7,3 % de aportado) | `fx_for_date(conn, fecha_del_asiento)` (la de `/cash/flow`) | Asistente de import → "Reconciliar caja"; deshacer transferencia | 🔴 | Migración a medio hacer + default de Pydantic que oculta un caller incompleto |
| Tipo de cambio y conversión de moneda | DIV-140 | 2 (+1 asimetría interna) | Sí (import crea +US$236 por conversión de 10 M ARS; manual escribe 0) | Ninguna: ambas patas al TC de la conversión (`tx.unit_price`), Δcapital = 0, simétrico en ambas direcciones | `/dashboard` y `/analisis` "Capital Aportado" y rendimiento total | 🔴 | Falta de capa compartida: dos implementaciones completas del mismo hecho, cero código en común |
| Tipo de cambio y conversión de moneda | DIV-141 | 3 | Sí (`or 1` = 1.518× en v1; mobile pierde 68 % del P&L en ventas retroactivas) | La rama v2 con la mejora del chat (nunca caer a 1; MEP vivo para hoy) | `/posiciones` mobile (venta ARS con fecha pasada); `/operaciones`; `/analisis` P&L realizado | 🟠 | Parche que funciona por accidente + prop opcional que degrada en silencio en el 2º caller |
| Tipo de cambio y conversión de moneda | DIV-142 | 2 significados / 1 columna | No hoy (todos los lectores guardan `is_cash`), sí estructuralmente | Partir la columna: `tc_compra` (lote) vs. `tc_cash_avg` (cash USD) | Ninguna hoy | 🟡 | Sobrecarga de esquema: se reusó una columna para un concepto nuevo |
| Tipo de cambio y conversión de moneda | DIV-143 | 2 | Sí con preferencia CCL (2,7 %: Cartera vs. snapshot de esa noche) | Ninguna: la preferencia debe viajar al backend, o anclar toda comparación al MEP | `/posiciones`, `/dashboard` (P&L Día fantasma), `/analisis`; parcheado SOLO en `/` home mobile | 🟠 | Parche puntual: el fix existe, está comentado, y se aplicó a 1 de 5 pantallas |
| Tipo de cambio y conversión de moneda | DIV-144 | — | No (convergencias reales, 5/5 verificadas) | (n/a) | (ninguna) | ⚪ | (n/a) |
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
| P&L no realizado / ganancia latente | DIV-072 | 2 | SÍ — hasta invertir el signo (Δ = Σ C_i·(1/tc_compra − 1/MEP)) | ninguna sola: el persistido debe ser `today`; el display debe rotular el modo | `/dashboard` KPI "P&L no realizado" y hero de `/cartera` (modo `purchase`) vs `/mensual` col. "No realizado" y `/reportes` KPI (modo `today`) | 🔴 | preferencia de display (`costBasis`, default `purchase`) filtrándose a la mitad de los cálculos; fix aplicado en un solo lado |
| P&L no realizado / ganancia latente | DIV-073 | 2 | SÍ — no por la fórmula (son equivalentes) sino por gates y lista de precios | ninguna: fórmula de MonthlySummary + gates de ambos + `buildPriceSymbols` | `/mensual` y `/reportes`: el valor guardado depende de qué pantalla abriste último | 🔴 | dos escritores del mismo campo sin capa común; `buildPriceSymbols` existe y /mensual no lo usa |
| P&L no realizado / ganancia latente | DIV-074 | 2 | SÍ, sólo por el interés devengado de plazos fijos (el cash aporta 0 en ambas) | el KPI del Dashboard (incluir PF es lo correcto) | `/dashboard` KPI vs `/mensual` col. "No realizado" y `/reportes` | 🟡 | el rollup de PF se agregó al display y nunca al writer |
| P&L no realizado / ganancia latente | DIV-075 | 4 (2 en Dashboard, 2 en Insights) | SÍ — mismo delta que DIV-072, dentro de la misma pantalla | las versiones `today` (tortas y `aiPositions`) | `/dashboard` hero vs sus tortas tipo/sector y Top Holdings; `/analisis` card de P&L abierto vs `pnl_usd` por activo del snapshot IA | 🟠 | `costBasis` se pasó a `computeBrokerValue` y no a las memos hechas a mano al lado |
| P&L no realizado / ganancia latente | DIV-076 | 6 (4 en builder + /mensual + /wrapped) | SÍ — el número publicado es un stock acumulado de años, no del período (33× en el ejemplo) | ninguna salvo día/semana global; lo correcto es `U(fin) − U(inicio)` con bordes MtM, o `None` | `/reportes` card de mes y de año ("No realizado", sub "mark-to-market"); `/mensual` fila del mes en curso y fila TOTAL; `/wrapped` mejor/peor mes | 🔴 | un stock guardado en una columna con nombre de flujo; `builder.py:1545-1548` lo documenta y lo publica igual |
| P&L no realizado / ganancia latente | DIV-077 | 3 motores backend | SÍ — comisiones (Δ = K por lote), `asset_type` ausente (guard RF desactivado), None vs 0 | `compute_broker_value_usd` (`snapshots_job.py:158`) | snapshot del chat IA (`/ai`, `/analisis`), atribución por ticker, `/goals`, Comportamiento | 🟠 | tres ports independientes del mismo `computeBrokerValue`; el SELECT de `insights.py` no trae las columnas que su propio guard consulta |
| P&L no realizado / ganancia latente | DIV-078 | 2 | Parcial: el P&L coincide (0 vs "—"); el VALOR no (la fila muestra "—", el total cuenta el costo) | el total (`computeBrokerValue`); la fila debe mostrar el costo con marca, no "—" | `/cartera` desktop: la suma de la columna "Valor" no da el TOTAL del pie (ONs/bonos/FCIs sin cotización) | 🟡 | las filas no usan el motor canónico; sólo tres totales lo usan |
| P&L no realizado / ganancia latente | DIV-079 | 3 criterios | SÍ — con una fila futura, el latente entero desaparece de la tabla y del total | el calendario del backend (`main.py:9702`), idealmente en hora argentina y no UTC | `/mensual`: columnas "No realizado" y "Retorno", badge de mes vivo, % oculto de meses cerrados, fila TOTAL | 🟠 | criterio de "mes abierto" re-decidido en cada capa; fix idéntico ya hecho en el backend (2026-05-30) y nunca replicado al frontend |
| P&L no realizado / ganancia latente | DIV-080 | 9 | Hoy casi alineadas por parcheo repetido; 3 divergen de verdad (son DIV-073 y DIV-075) y 6 usan `tcValuacion` donde la canónica usa `cedearRate` | `valuePositionLot` (`valuation.js:543`), consumida sólo por `computeBrokerValue` | todas las superficies de valuación; el riesgo mayor es futuro (el día que MEP ≠ el rate de valuación, divergen las seis a la vez) | 🟠 | falta de capa compartida; migración a `valuePositionLot` empezada y abandonada — el bloqueo declarado (comisiones, modo `purchase`) ya está resuelto |
| Rendimiento / retorno | DIV-092 | 5 | SÍ — +10,0 % vs +6,67 % en un mes; +213,8 % vs +115,7 % en doce | `twr.dietz` / `twr.curva_indexada` | `/wrapped` (slide «Tu rendimiento TWR», exportable como PNG); chat IA de `/analisis?tab=diagnostico`, de la curva de evolución y de `?tab=reportes` | 🔴 alta | migración a medio hacer — `insights_benchmarks.py` se migró y los otros cuatro quedaron |
| Rendimiento / retorno | DIV-093 | 2 | SÍ — un depósito del 30 % del capital se publica como "TWR +30 %" | `twr.curva_indexada` sobre la ventana pedida | packet del chat IA de `/dashboard`; email diario del asesor (`advisor_brief`) | 🟠 media-alta | falta de capa compartida + rótulo heredado ("TWR" a `(V₁−V₀)/V₀`) |
| Rendimiento / retorno | DIV-094 | 3 | SÍ — +74,9 % anual en una tab vs "no se anualiza" en otra, mismo día y misma cuenta | B1 `twr.py:2164-2172` (geométrica sobre días, piso de medio año) | `/analisis?tab=diagnostico`, card `metric_cagr` (gratuita) | 🔴 alta | fix aplicado sólo en el backend; `insightsMetrics.computeCAGR` conservó su motor |
| Rendimiento / retorno | DIV-095 | 2 | Los números difieren (+20,0 % vs +44,3 %) pero responden preguntas distintas; el bug real es el denominador sin guard peak (+400 % vs −95 %) | ambas con etiqueta explícita; el denominador peak debe agregarse a "Total" | `/dashboard`, strip "Total" / "Anual" | 🟡 media | frontend recalculando lo que el backend ya calcula, sin nomenclatura común |
| Rendimiento / retorno | DIV-096 | 2 | SÍ — +18,2 % vs +200 % con FX 500→1.500 y cartera quieta | `twr._leg_en_moneda` (stock a su TC, flujo al TC medio geométrico) | `/analisis?tab=diagnostico`, curva de evolución diaria en pesos | 🔴 alta | copiar y pegar la rama USD con una premisa falsa escrita como justificación (`evolution.js:560-562`) |
| Rendimiento / retorno | DIV-097 | 2 con guards / 11 sin | SÍ — sin `DENOM_MIN_FRACCION` vuelve el +4.439 % en un leg; sin `SALTO_MAX_VECES` el +25.757 % | los guards de `twr.py:610-647` + el piso de medio año | todas las anteriores + chips Δ1d/Δ7d/Δ30d (`_snapshot_delta`) + email del asesor | 🔴 alta | los guards nacieron dentro del motor; nada impide calcular retorno afuera |
| Rendimiento / retorno | DIV-098 | 2 | SÍ — veredicto OPUESTO en la misma pantalla (+18,75 % real vs −15,63 % real) | `perf.twr` del motor (cartera completa, con guards) | `/analisis?tab=diagnostico`: card "Expectativa de retorno" vs celda "Inflación" del comparativo, + el packet de IA | 🟠 media-alta | un fix aplicado en un solo call site de la misma pantalla |
| Rendimiento / retorno | DIV-099 | 4 | SÍ — el sellado no se muestra; el del chat no filtra base de mercado y el del dashboard sí (+39,6 % vs "—") | `advisor_twr.twr_por_cliente` (sellado, con cobertura) | chat de la IA del libro (`main.py:35516`, sin filtro) 🔴; Mejor/Peor del dashboard del asesor; informe firmado; email diario | 🔴 alta | fix aplicado en un solo lugar (`_es_base_de_mercado`) + motor correcto sin consumidor (`/api/advisor/twr` no lo llama nadie) |
| Rendimiento / retorno | DIV-100 | 5 | SÍ — "big withdraw" +20,0 % vs +30,8 %; "import inicial" −9,8 % vs −19,5 % | `twr.dietz` como primitivo único (V2 defendible con `clamp=False`) | curvas de `/analisis?tab=diagnostico` (V3, V4); `/mensual` y el teaser del Dashboard (V5) | 🟠 media-alta | copiar y pegar + parches locales que nunca volvieron a la capa común (`evolution.js:506`: «dos copias de la misma regla es el defecto de fondo de este proyecto») |

## URGENTE — consolidado

Los ocho agentes marcaron **15 puntos urgentes**. Ninguno fue tocado: la regla de la auditoría es documentar, no arreglar. Están ordenados por lo que los hace urgentes, que no es la magnitud sino la **irreversibilidad**.

### A. Escriben datos falsos que quedan (necesitan fix **y** backfill)

| # | qué | dónde | magnitud medida |
|---|---|---|---|
| A-1 | **El job nocturno de snapshots valúa con un motor al que le falta 1 de 6 ramas.** Cuenta un costo en pesos como dólares; el guard anti-distorsión entonces rechaza el precio bueno y persiste el costo inflado | `snapshots_job.compute_broker_value_usd` | **×1.360 – ×1.500**. US$ 517 en pantalla → US$ 707.000 en la tabla |
| A-2 | En broker USD genuino, la clave de precio tampoco mira `currency`: cotiza el **ADR de NYSE** en vez del `.BA`, y el múltiplo cae dentro de la banda del guard | `snapshots_job.position_price_key` | P&L de **−US$ 695.500** sobre un lote de US$ 500 |
| A-3 | El cron **pisa incondicionalmente** el snapshot correcto que escribió el browser; el browser **no** pisa al cron | `snapshots_job.py:786-790` vs `main.py:5060-5064` | el motor roto tiene prioridad de escritura sobre el bueno |
| A-4 | **El recalc borra el `capital_inicio` que el usuario tipeó** en `/mensual`, en el primer mes de todos los brokers, `'global'` incluido. Sin deshacer | `main.py:9639-9652` | se dispara con importar un CSV, revertirlo, borrar un broker o cerrar un futuro |
| A-5 | La amortización manual guarda el **cash bruto** como `pnl_usd`; la ganancia correcta se calcula 24 líneas después y **se descarta** | `main.py:10484` vs `:10508` | se hereda mes a mes vía `capital_final`; infla el TWR de toda cuenta con AL30/GD30 |
| A-6 | `reconcile-cash` divide por un **TC hardcodeado (1415)**: su único caller no manda el campo, así que en producción siempre usa el default | `main.py:10020` + `:10100` | **+7,3 % de capital fantasma** por reconciliación, con MEP ~1.518 |
| A-7 | Si el usuario **borra** el campo opcional "TC de venta", la fila se estampa con `fx_to_usd = 1.0` aunque el P&L ya se dividió por el TC de la fecha | `main.py:11310` y `:11389` | **~1.400×** en todo lector que reconstruya el nominal en pesos |
| A-8 | `SellModal` se renderiza **sin la prop `fxHist`** en mobile: el TC por fecha degrada al MEP de hoy. El desktop sí la pasa | `PositionsMobile.jsx:1642-1650` | una venta retroactiva desde el celular queda con **68 % menos** de P&L realizado |
| A-9 | La conversión ARS→USD **importada** escribe `withdraw + deposit` cuyo neto no es cero (la manual no escribe nada, y es la que tiene razón) | importador FX | **+US$ 293 por cada US$ 1.000** convertidos |

**Lo que vuelve crítico al bloque A-1/A-2/A-3:** el guard de integridad del 95 % **no lo ve**, porque mide con la función correcta mientras la valuación usa la incorrecta. Reporta cobertura 100 % y escribe igual. Cero excepciones, cero logs. El usuario ve el hero bien (se calcula en el browser) y sólo el gráfico mal — la discrepancia que se atribuye a "el mercado" y no a un bug.

### B. Salen de la app o alimentan a la IA

| # | qué | dónde | magnitud |
|---|---|---|---|
| B-1 | El slide del Wrapped dice literalmente **«Tu rendimiento TWR»** sobre una fórmula que no es TWR (sin el `0,5·F` del denominador, base al costo) | `shareCard.js` lo exporta **como PNG** | +10,0 % donde el motor mide +6,67 %; a doce meses, **+213,8 % vs +115,7 %** |
| B-2 | El contexto del chat del libro hace la misma lectura que su hermano **sin el filtro `_es_base_de_mercado`**; ese `ret_pct` va al prompt que le ordena al modelo **rankear clientes** | `main.py:35516` vs `:37073` | el propio código documenta el síntoma que el filtro vino a matar |
| B-3 | La IA recibe el **P&L de por vida duplicado ×2 exacto**: se suman la fila sintética `global` **y** las por-broker. También `deposits_lifetime` y `withdrawals_lifetime` | `RendiAI.jsx:170`, `AICoachDrawer.jsx:177` | viaja en el contexto de **cada mensaje** del chat |
| B-4 | `Interés PF` se escapa de todos los filtros y de toda conversión: no está en `_NATIVE_CCY_OPS` y nace con `fx_to_usd = NULL` | `main.py:9315` | un PF de $10M a 30 días inyecta **US$ 328.767 falsos** en 5 pantallas |

### C. Muestran mal, no persisten

| # | qué | dónde | magnitud |
|---|---|---|---|
| C-1 | `/reportes` publica **un stock como si fuera un flujo**: el latente acumulado desde la compra, rotulado "P&L no realizado del mes" | `builder.py:894` y `:1130` | **33×** en una cuenta de 2023, y crece con la antigüedad |
| C-2 | `SELECT br.currency AS currency` **pisa la moneda del lote**: un bono en dólares dentro de un broker ARS colapsa a 1/MEP | `reporting/timeline.py:123-131` | mismo bug que `usdLotValue` ya arregló en el frontend |

**Lo más elocuente de C-1:** el mismo archivo **diagnostica el problema por escrito** 400 líneas más abajo (*"es el latente ACUMULADO…, no la variación del período"*), lo usa para no tocar `delta_usd`, y a renglón seguido publica ese mismo número.

---

## Corroboración cruzada

Tres agentes que trabajaron por separado, sin verse, llegaron al **mismo bug por rutas distintas**:

| bug | valuación | tenencia | costo/FIFO |
|---|---|---|---|
| a `snapshots_job` le falta la rama "pesos en cuenta USD" | vía el guard anti-distorsión | vía la moneda del lote | vía el cost basis |
| `behavioral._position_value_usd` nunca lee `commissions` | — | ✅ | (lo halló también P&L no realizado) |

Es la evidencia más fuerte de la tanda: **no son lecturas forzadas de un mismo mapa**, son tres caminos independientes que convergen. El bug de `snapshots_job` se puede dar por sólido sin verificación adicional.

---

## Los patrones de causa raíz

De las 94 divergencias, la causa raíz casi nunca es descuido. Se repiten cuatro formas, y las cuatro son **parches**:

1. **Fix aplicado en un solo call site** (el más frecuente). El mismo modal con dos llamadas y sólo una corregida (A-8); el mismo filtro en dos lecturas y sólo una lo tiene (B-2); `costInUsd` portado al backend y su espejo `costInPesos` no (A-1).
2. **Port a mano de una función que después divergió.** `snapshots_job.compute_broker_value_usd` es una copia de `computeBrokerValue` a la que le falta una rama de seis.
3. **Diagnóstico correcto escrito al lado del bug.** C-1 y A-5 tienen, en el mismo archivo, el comentario que explica exactamente por qué el número está mal — y publican el número mal igual.
4. **Listas de exclusión en vez de inclusión.** `_NOT_A_TRADE` hace que **todo `op_type` nuevo entre como "trade cerrado ganado" por omisión**. Ya pasó con `Interés PF`; `Renta`, `Cupon` y `Amortizacion` están en la misma situación, esperando.

El patrón 4 es el único que **garantiza bugs futuros** sin que nadie escriba una línea nueva mal.

Dato que ordena la prioridad: **la fuente única de verdad, en varios casos, ya existe y está escrita.** `valuePositionLot` (`valuation.js:566-731`) es el valuador canónico de 6 ramas, y su propio docstring admite que todavía no la consume nadie. Los lectores que faltan migrar son exactamente donde viven varias de estas divergencias. Lo mismo con `backend/twr.py`, que está bien: el problema es que cinco superficies no lo usan y publican otro número con el mismo rótulo.

---

## Confiabilidad del mapa — resultado de la verificación

Se abrieron y verificaron **290 citas**. El saldo:

- **~53 corregidas** (mayoría: desvíos de 1 a 16 líneas, y un error sistemático — todos los archivos frontend citados como `.js` son `.jsx`).
- **5 afirmaciones sustantivamente falsas**, donde el código contradijo al mapa y ganó el código:

| divergencia | qué decía el mapa | qué dice el código |
|---|---|---|
| DIV-133 | los plazos fijos producen un salto en la variación diaria | el frontend los **excluye a propósito** del eje temporal. La divergencia real es otra |
| DIV-062 | las dos funciones de amortización difieren en las comisiones | **devuelven el mismo número**. El bug real es que las dos las ignoran |
| DIV-073 | los dos escritores de `pnl_unrealized` calculan distinto | son **algebraicamente equivalentes**; lo que diverge son los gates |
| DIV-038 | `_ytd_delta` no vería al sibling | corta antes con un `return None`. **Es cosmética** |
| DIV-040 | cuarta copia de la regla "ausente ≠ negativo" | no lo es; y la variante JS con `||` es **equivalente** |

Y una en sentido inverso: **DIV-136 estaba archivada como redundancia y es una divergencia real** — el libro del asesor en `/clientes` y su propio brief diario por email valúan la misma cartera con 0,74 % de diferencia.

Conclusión operativa: **las citas del mapa sirven para encontrar el lugar, no para sostener una afirmación.** La instrucción de "gana el código" cambió cinco veredictos.

---

## Pendiente para la tanda 1B

8 grupos, **72 divergencias**. Son clases de activo específicas o vistas derivadas que se apoyan en la cadena auditada en 1A — por eso van después: ahora existe el veredicto sobre cuál es la fórmula correcta aguas arriba.

| concepto | slug | divs | IDs | por qué quedó para después |
|---|---|---:|---|---|
| Bonos: escala per-100, paridad, vencimiento y flujos | `bonos` | 13 | DIV-001–013 | clase de activo; se apoya en costo y valuación |
| Snapshot / foto histórica de la cartera | `snapshot` | 11 | DIV-101–111 | **es la víctima de A-1/A-2/A-3**; auditarlo ahora es la continuación natural |
| TIR / IRR / XIRR | `tir` | 9 | DIV-112–120 | vista derivada; depende de capital aportado y flujos |
| Dividendos, cupones, rentas y amortizaciones | `dividendos` | 9 | DIV-063–071 | se cruza con A-5 y con el patrón `_NOT_A_TRADE` |
| Comisiones, impuestos y costos de transacción | `comisiones` | 8 | DIV-042–049 | apareció de refilón en 3 informes de 1A |
| CEDEAR: ratio, split, valuación y pata en dólares | `cedear` | 8 | DIV-014–021 | clase de activo |
| Variación diaria / periódica y evolución | `variacion` | 7 | DIV-160–166 | lee `snapshots`; hereda todo el bloque A |
| Caja / cash / saldo disponible | `caja` | 7 | DIV-022–028 | — |

Los archivos de input ya están partidos en `audit/01_calculos/_grupos/<slug>.md`.
