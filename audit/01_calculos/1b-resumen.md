# 1B — Resumen: auditoría transversal de cálculo

**6 temas · 128 hallazgos.** Commit auditado `b74f450f`, copia limpia de solo lectura.

> ⚠️ **Cuatro de los seis agentes murieron con un 429 de límite de sesión antes de responder en el chat.**
> Los seis archivos estaban completos en disco igual: la regla "escribí a disco ANTES de responder" rescató
> `benchmarks`, `decimales`, `fechas` y `borde` (2.968 líneas y 88 hallazgos que se habrían perdido).
> Los seis tienen su bloque `## Método` y su `BLOQUE-RESUMEN` verificados.

## El número

| severidad | hallazgos |
|---|---:|
| 🔴 alta | 20 |
| 🟠 media-alta | 39 |
| 🟡 media | 37 |
| ⚪ menor | 32 |
| **total** | **128** |

## Calidad de la evidencia

Esta tanda impuso la etiqueta obligatoria. El saldo:

| etiqueta | hallazgos | qué significa |
|---|---:|---|
| **MEDIDO** | 50 | se ejecutó código real y la traza está pegada en el informe |
| **DEDUCIDO** | 12 | aritmética a mano, con los supuestos declarados |
| **ESTRUCTURAL** | 66 | no hay magnitud: falta una rama, un guard, un parámetro |

**50 de 128 hallazgos están medidos ejecutando código.** En la tanda 1A, 1 de 8 agentes ejecutó algo.
La diferencia es la etiqueta obligatoria: al no poder escribir "medido" sin traza, los agentes midieron.

## Por tema

| tema | hallazgos | 🔴 | 🟠 | 🟡 | ⚪ | medidos | informe |
|---|---:|---:|---:|---:|---:|---:|---|
| Decimales y precisión | 20 | 0 | 4 | 6 | 10 | 10 | [`1b-decimales.md`](1b-decimales.md) |
| Monedas y cotizaciones | 19 | 3 | 6 | 5 | 5 | 6 | [`1b-monedas.md`](1b-monedas.md) |
| Fechas, períodos y zonas horarias | 17 | 3 | 7 | 5 | 2 | 8 | [`1b-fechas.md`](1b-fechas.md) |
| Inflación, UVA y CER | 21 | 4 | 5 | 5 | 7 | 6 | [`1b-inflacion.md`](1b-inflacion.md) |
| Benchmarks y objetivos | 30 | 5 | 11 | 9 | 5 | 7 | [`1b-benchmarks.md`](1b-benchmarks.md) |
| Casos borde | 21 | 5 | 6 | 7 | 3 | 13 | [`1b-borde.md`](1b-borde.md) |

## Tabla completa — 128 hallazgos

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
| Monedas | M-01 | `/api/fx-rates` capa por FILAS (3.650): fechas anteriores a ~2016-09 se convierten al dólar de HOY, en silencio (160×) | MEDIDO | 🔴 | `/operaciones` en Pesos, curva del Dashboard, `/mensual` | `LIMIT` sobre filas con un parámetro llamado `days`; el fallback del hook es el TC vivo |
| Monedas | M-02 | "Invertido en dólares": `'purchase'` en el frontend vs `'today'` en todo el backend. Mismo lote: −13,6 % vs +25,0 % | MEDIDO | 🔴 ⚠️ zona activa | Cartera vs snapshot/Reportes/IA/asesor/CSV | el toggle `costBasis` se implementó sólo en el frontend; ningún backend lee `tc_compra` |
| Monedas | M-03 | `snapshots.total_invested` tiene dos escritores con convención opuesta (cron `'today'` / navegador `'purchase'`) | ESTRUCTURAL | 🔴 ⚠️ zona activa | serie de costo, `Δtotal_invested` de gap-month y mtm-audit | consecuencia de M-02: una columna, dos motores sin definición común |
| Monedas | M-04 | Reportes en Pesos: % al TC de cada punta, monto al TC de hoy → hero "+10,0 % · +US$0" | MEDIDO | 🟠 | `/reportes` y `/analisis?tab=reportes` | división de tareas declarada que el frontend cumple con el TC equivocado |
| Monedas | M-05 | `vs_sp500_pct` / `vs_inflation_pct` sin gate de moneda: el veredicto vs S&P cambia de signo con el toggle | DEDUCIDO | 🟠 | tarjeta de Reportes + narrativa/IA | `vs_x = delta_pct − bench_ret` y los benchmarks no tienen versión en la otra moneda |
| Monedas | M-06 | `config.tc_blue` = 1415 congelado (sin UI, sin escritor) y es el dólar del cash del motor de Comportamiento | MEDIDO + ESTRUCTURAL | 🟠 | `/analisis?tab=comportamiento`, wrapped, cards de IA | override manual retirado sin retirar a sus lectores |
| Monedas | M-07 | `_position_size_usd` ignora la fecha de la op: notional en pesos siempre `/1415` (8,6× en 2021) | MEDIDO | 🟠 | turnover, overtrading, loss-aversion | `behavioral.py` nunca se migró a `fx.fx_for_date` |
| Monedas | M-08 | `ai/builders/insights.py` lee `config.tc_mep` (1415) en vez de `user_fx` live → la IA ve la cartera +7,3 % | ESTRUCTURAL | 🟠 | packet de Rendi AI de Análisis | único builder que resuelve el FX a mano |
| Monedas | M-09 | Depósito desde mobile sin `date` → mes en curso + dólar de hoy; desktop usa `fx_for_date` | ESTRUCTURAL | 🟠 | capital aportado (denominador del rendimiento) | paridad mobile/desktop cerrada en el TC y no en la fecha |
| Monedas | M-10 | `lookupHistoricalDolar`: mes en curso al MEP medio vivo, mes cerrado al blue venta mensual → +3,73 % de salto | MEDIDO | 🟡 | `/mensual` (tabs ARS), `evolution.js` | el parámetro `liveTc` recibe MEP mientras el mapa es blue |
| Monedas | M-11 | Alertas: el `currency` del umbral no se usa para comparar, sólo para el mensaje | ESTRUCTURAL | 🟡 | alerta sobre `.BA` con default USD: dispara al instante o nunca | el campo se agregó para el copy; el comparador quedó igual |
| Monedas | M-12 | `positions.csv` (al contador) exporta `invested` sin columna de moneda; `monthly.csv` no declara unidad | ESTRUCTURAL | 🟡 | declaración impositiva de un tercero | el fix de `operations.csv` no se propagó a sus hermanos |
| Monedas | M-13 | Factor cripto = `cripto.venta / mep.medio`: punta sobre medio | ESTRUCTURAL | 🟡 | valor de la cripto en broker AR (FE, BE, snapshot, asesor) | decisión comentada de paridad FE/BE que deja el ratio no homogéneo |
| Monedas | M-14 | `serie_fx("hoy")` = última fila de `fx_rates_daily`: el punto "hoy" en pesos usa el TC del último cron | ESTRUCTURAL | 🟡 | último punto de `curva_indexada` en `moneda=ars` | valor vivo con TC de serie: dos relojes en el mismo punto |
| Monedas | M-15 | El packet del Coach manda `tc_blue_ars: tcValuacion` (el MEP, o el CCL) | ESTRUCTURAL | ⚪ | lo que la IA cree que es el blue | renombre `tcBlue`→`tcValuacion` que no llegó al payload |
| Monedas | M-16 | `config.display_currency` se lee y nadie lo escribe → la IA siempre cree que la pantalla está en USD | ESTRUCTURAL | ⚪ | Rendi AI hablando en dólares a un usuario en pesos | preferencia per-device que un lector de servidor asumió persistida |
| Monedas | M-17 | `Goals.jsx` ignora el selector de moneda y llama `computeBrokerValue` sin `costBasis` | ESTRUCTURAL | ⚪ | `/objetivos` | pantalla fuera del rollout del toggle |
| Monedas | M-18 | Vender dólares importados: `tc_compra` NULL → `tc_avg = data.tc` → P&L cambiario exactamente 0, sin aviso | ESTRUCTURAL | ⚪ | P&L realizado de conversiones en cuentas importadas | el cost-basis del cash USD sólo lo llena la conversión manual |
| Monedas | M-19 | PF en pesos: `capital / TC de hoy` — el "invertido" del PF se mueve con el dólar y se suma a lotes en `tc_compra` | ESTRUCTURAL | ⚪ | totales de Dashboard/Home/Métricas con PF | el PF no tiene dónde guardar su TC de constitución |
| Fechas/períodos/TZ | H-1 | El cron sella el snapshot con el día UTC (= un día ART adelante); la rama que convierte a ART es código muerto. El desfasaje llega al borde de todos los períodos: septiembre arranca en el cierre del 30/08 y el año 2026 cierra con la rueda del 30/12 | **MEDIDO**: `target_date='2026-09-05'` corriendo 02:59 UTC del 5 (= viernes 4, 23:59 ART); borde de septiembre medido con `fetch_snapshot_at_or_before` real | 🔴 | serie de snapshots entera, Reportes, Δ1d/7d/30d, curva, TWR, libro y brief del asesor, packets de IA | horario del cron movido a 02:59 UTC sin mover la etiqueta; `run_daily_snapshot` pasa `target` no-None (`snapshots_job.py:937` vs `:648-657`) |
| Fechas/períodos/TZ | H-2 | El YTD de Métricas usa borde INCLUSIVO del 1/1 y resta los flujos del año entero → el aporte del 1/1 se descuenta dos veces. Hoy lo tapa H-1 | **MEDIDO**: `main._ytd_delta` verbatim publica −22,86 % / −US$ 4.000 donde la verdad es +US$ 1.000 | 🔴 | KPI YTD de Métricas → `_bench_cache` → prompt del chat de IA | fix `_dia_anterior` aplicado en `builder.py:1155` y no en `main.py:33006` |
| Fechas/períodos/TZ | H-3 | "Este mes" tiene 4 definiciones; 2 no aplican el piso de 5 días del borde de apertura | **MEDIDO**: +35,24 % (Dashboard) vs "sin base" (backend, `/mensual`) vs +2,90 % real | 🔴 | Dashboard y home mobile KPI "Este mes"; banner de `/mensual` | `computeReturnDelta` no recibió el `_border_is_fresh` que `useMonthlyData.js:585-593` documenta como obligatorio |
| Fechas/períodos/TZ | H-4 | `/reportes`: la clave del tab "Hoy" es UTC y las de Semana/Mes/Año son hora local | **MEDIDO**: 31/08 22:00 ART → Hoy=`2026-09-01`, Mes=`2026-08`; 31/12 22:00 ART → Hoy=`2027-01-01`, Año=`2026` | 🟠 | `/reportes` de 21:00 a 23:59 ART | cuatro helpers escritos por separado en `Reports.jsx:31-51` |
| Fechas/períodos/TZ | H-5 | Dos relojes dentro de `/api/reports/period/{type}/{key}`: ART para `day`, local/UTC para el resto, UTC adentro de `is_period_current` | ESTRUCTURAL + MEDIDO | 🟠 | la rama "período en curso" se apaga 3 h/día: el reporte del día cierra sin valor live | `main.py:33165` vs `:33166`; `build_period_report` llamado sin `today` |
| Fechas/períodos/TZ | H-6 | `is_period_current` usa UTC con un comentario que afirma consistencia con `_iso_today()`, que es ART | ESTRUCTURAL + MEDIDO (agosto cerrado a las 23:30 ART del 31/08; 2026 cerrado a las 22:00 ART del 31/12) | 🟠 | Reportes: cambia la rama que mide el período (live vs cadena contable) | comentario sobre una premisa falsa (`builder.py:91-94`) |
| Fechas/períodos/TZ | H-7 | Rollover mensual en UTC en el backend, en hora local en el frontend | ESTRUCTURAL | 🟠 | último día de cada mes 21:00-23:59 ART: `/mensual` muestra el mes local como en curso con latente 0, y el latente vivo va a la fila del mes siguiente | `main.py:11452` / `:11054` vs `MonthlySummary.jsx:118-120` |
| Fechas/períodos/TZ | H-8 | Brief y alertas del asesor excluyen "hoy ART" y por H-1 se llevan puesta la fila del cierre de anoche → miden contra el cierre de anteayer | ESTRUCTURAL (H-1 MEDIDO) | 🟠 | "Δ del día" de los dos briefs por mail y el disparo de las alertas de drawdown; y `advisor_book_detail` (UTC) no cierra con el hero (ART) | tres comentarios afirmando "los snapshots se estampan con fecha ART" |
| Fechas/períodos/TZ | H-9 | Las semanas anidadas bajo un mes no cubren el mes | **MEDIDO**: sep-2026 sin los días 1-6; dic-2026 sin 1-6 y con desborde al 3/1 | 🟠 | `/reportes` tab Semana; `detect_consistency` concluye sobre una partición incompleta | "la semana pertenece al mes de su lunes" sin regla que cierre el hueco (`timeline.py:52-56`) |
| Fechas/períodos/TZ | H-10 | 27 sitios del frontend calculan "hoy" en UTC; el bug está diagnosticado y arreglado en 1 solo | ESTRUCTURAL (conteo verificado; `AdvisorDashboard.jsx:745-747` lleva el comentario del audit) | 🟠 | fecha por defecto de compra/venta/cash/cupón/PF/futuro = mañana después de las 21:00 ART, y el backend la acepta | fix aplicado en un solo lugar |
| Fechas/períodos/TZ | H-11 | La foto intradía del browser no se escribe: el cron ya ocupó esa fecha con `source='cron'` y el guard la protege | ESTRUCTURAL (consecuencia de H-1) | 🟡 | punto de "hoy" en la curva del Dashboard | H-1 + `main.py:5058-5067` |
| Fechas/períodos/TZ | H-12 | La IA recibe `HOY es {utcnow()}` y puede persistir operaciones por chat | ESTRUCTURAL | 🟡 | `register_trade` fecha mal entre las 21:00 y las 23:59 ART | `main.py:28512` |
| Fechas/períodos/TZ | H-13 | Seis tolerancias distintas de arrastre hacia atrás (4, 5, 7, 14 días y dos sin tope) | ESTRUCTURAL | 🟡 | findes largos y feriados: un KPI se apaga y el de al lado no; `fx._lookup` además arrastra hacia adelante sin tope | cada superficie eligió su número |
| Fechas/períodos/TZ | H-14 | `_market_open_now` es un rango UTC fijo, sin feriados y sin DST de EE.UU. | ESTRUCTURAL | 🟡 | alertas de precio: ~1,5 h de pre-market diario en EST y feriados evaluando contra el cierre congelado | `alerts_engine.py:113-120` |
| Fechas/períodos/TZ | H-15 | `date.today()` (77 call sites) es la hora local del proceso: UTC en prod, ART en dev | DEDUCIDO (no pude leer `TZ` de Railway) | 🟡 | tests y dev local miden un día distinto que producción 3 h/día | no hay helper único de "hoy" |
| Fechas/períodos/TZ | H-16 | Fechas validadas sólo por `max_length=10`, sin formato: un `'2026-9-4'` rompería el orden lexicográfico de todos los filtros | ESTRUCTURAL | ⚪ | ningún cliente actual lo produce; puerta abierta para chat de IA / scripts / clientes viejos | validación por longitud |
| Fechas/períodos/TZ | H-17 | El docstring de `/api/ai/usage` dice "ISO week, lunes-domingo"; el código es una ventana móvil de 7 días (deliberada y bien razonada) | ESTRUCTURAL | ⚪ | copy "X/6 esta semana" sugiere un reset de lunes que no existe | docstring atrasado (`main.py:27789` vs `ai/quota.py:226-238`) |
| 4. Inflación/UVA/CER | 1 | La fuente de CER (`api.argentinadatos.com/v1/finanzas/indices/cer`) devuelve **404**: los bonos CER calculan con factor 1,00 en vez de 7,72×–37,44× | MEDIDO | 🔴 | cronograma, próximo pago, TIR y pre-llenado de cupón de TX26/TX28/T2X5/TZX26/27/28 | dependencia de un tercero sin canario; el único camino de error es `return {}` silencioso |
| 4. Inflación/UVA/CER | 2 | La TIR se rotula "TIR real (sobre CER) — lo que ganás POR ENCIMA de la inflación" aunque el ajuste no se haya aplicado | ESTRUCTURAL | 🔴 | detalle del bono (`BondDetail.jsx:274`) | el rótulo mira `meta.type`, el cálculo mira `cerOpts`: dos condiciones para el mismo hecho |
| 4. Inflación/UVA/CER | 3 | El "próximo pago" y el monto pre-llenado del cupón nunca llevan ajuste CER (6 de 8 call sites sin `cerSeries`; `nextPaymentForPosition` ni acepta el parámetro) | ESTRUCTURAL | 🔴 | inbox de cobranzas, Novedades, filas de Renta Fija, modal de registro → `operations` → P&L | el ajuste se agregó como `options` opcional en vez de resolverse dentro del motor |
| 4. Inflación/UVA/CER | 4 | Los 6 `vs_inflación` del backend restan **inflación en pesos a un retorno en dólares** | ESTRUCTURAL | 🔴 | Reportes, Wrapped y los 4 packets que alimentan a la IA | la moneda no viaja con el número; nadie valida unidad antes de restar |
| 4. Inflación/UVA/CER | 5 | Los mismos 6 usan `r − π` en vez de `(1+r)/(1+π)−1`; error medido 3–17 pp hoy, 75–143 pp con la inflación de 2023 | MEDIDO | 🟠 | idem #4 | la fórmula correcta existe y vive en una sola pantalla (`diagnostics.js:207`) |
| 4. Inflación/UVA/CER | 6 | Los ~2 meses que el INDEC no publicó se arrastran planos (~4,2 pp hoy, ~13,8 pp con inflación 2024), sesgo pro-usuario, declarado sólo en el packet del chat | MEDIDO | 🟠 | gráfico de Insights, celda de Reportes, verdicts de la IA | política de arrastre correcta, comunicación inexistente |
| 4. Inflación/UVA/CER | 7 | `detect_inflation_loss` cae a **60 % anual hardcodeado**; el real medido es 33,82 % (1,77×) e infla la pérdida reportada un 48 % | MEDIDO | 🟠 | card "Pérdida por inflación" en Comportamiento, Objetivos, Wrapped y packet IA | número mágico en vez de `_not_enough_data()` |
| 4. Inflación/UVA/CER | 8 | `detect_inflation_loss` aplica 12 meses de inflación al saldo en pesos **de hoy**, sin mirar una sola fecha | ESTRUCTURAL | 🟠 | misma card | la métrica se diseñó como "por tener este saldo un año" y se comunica como "perdiste" |
| 4. Inflación/UVA/CER | 9 | En mobile los bonos CER van sin ajuste y con un "Cargando coeficiente CER…" que nunca termina | ESTRUCTURAL | 🟠 | `PositionsMobile.jsx:1355` | 3 props (`cerSeries`/`cerStale`/`tcMep`) no se pasan; los defaults degradan en silencio |
| 4. Inflación/UVA/CER | 10 | La opción "Plazo fijo UVA" del gráfico queda habilitada y no dibuja nada (el front pide `plazo_fijo`, el back produce `uva`) | MEDIDO | 🟡 | gráfico de Insights en Pesos | dos diccionarios de claves de benchmark que nadie cruza |
| 4. Inflación/UVA/CER | 11 | `_fetch_uva_monthly` toma el último día disponible del mes en curso como cierre (medido: 2026-09 = +0,47 % con 7 días) | MEDIDO | 🟡 | benchmark "Plazo fijo UVA" | el dict-overwrite no distingue mes cerrado de mes vivo |
| 4. Inflación/UVA/CER | 12 | `floorReal` (0/3/10/18) compara varas anuales contra un retorno real acumulado sin anualizar: el veredicto depende de cuánto tiempo lleva el usuario en la app | DEDUCIDO | 🟡 | card "Expectativa de retorno" | falta normalización temporal |
| 4. Inflación/UVA/CER | 13 | `vs_inflation` de Reportes no se gatea por exposición ARS; el gate correcto existe en JS pero en código muerto | ESTRUCTURAL | 🟡 | reportes de carteras 100 % USA | la regla se escribió del lado que se apagó |
| 4. Inflación/UVA/CER | 14 | Sólo el reporte mensual tiene `vs_inflación`; el **anual** cae por el mismo `return None` que día y semana | ESTRUCTURAL | 🟡 | reporte anual | el corte se pensó por resolución del dato y se aplica por tipo de período |
| 4. Inflación/UVA/CER | 15 | Tres cálculos de inflación no llegan a ninguna pantalla, y un comentario afirma un consumidor inexistente (`Insights.jsx:2315`) | ESTRUCTURAL | ⚪ | — | restos de iteraciones; el comentario impide que se limpien |
| 4. Inflación/UVA/CER | 16 | `UVA` y `A3500` pasan la allowlist de `/api/bond-indices` sin fetcher → serie vacía y `stale:true` permanente (P-051) | ESTRUCTURAL | ⚪ | — | validación y capacidad declaradas en lugares distintos |
| 4. Inflación/UVA/CER | 17 | `benchmark_recortado` excluye el IPC del mes base: correcto para curva anclada a fin de mes, sesgo pro-usuario de hasta ~1,2 pp si el usuario arranca a mitad de mes | DEDUCIDO | ⚪ | gráfico de Insights | IPC mensual contra curva diaria |
| 4. Inflación/UVA/CER | 18 | La suite mockea `_fetch_cer_series` y hasta testea el caso "fuente vacía": el 404 de #1 pasa en verde | ESTRUCTURAL | ⚪ | CI | no hay canario contra las URLs reales |
| 4. Inflación/UVA/CER | 19 | `/api/reports/*` llama `_fetch_inflation_ar()` en cada request ignorando `_bench_cache` (confirma el mapa) | ESTRUCTURAL | ⚪ | latencia de Reportes; dos fotos distintas del IPC entre pantallas | dos caminos a la misma fuente, uno cacheado y otro no |
| 4. Inflación/UVA/CER | 20 | `detect_inflation_loss` convierte con blue y el resto del módulo con MEP (confirma el mapa; **no** es bug de unidad) | ESTRUCTURAL | ⚪ | monto USD de la card | riel de FX elegido por función, no por concepto |
| 4. Inflación/UVA/CER | 21 | `MonthCard` rotula con `%` un valor que está en puntos porcentuales, invitando a la resta que la pantalla hermana prohíbe | ESTRUCTURAL | ⚪ | celda "vs Inflación AR" | — |
| Benchmarks | B-01 | "Plazo fijo UVA" pide una serie (`plazo_fijo`) que el backend nunca produjo → benchmark vacío con la opción marcada disponible | MEDIDO | 🔴 | `/analisis` en Pesos | el frontend mapeó al nombre de producto, no al de la fuente (`uva`) |
| Benchmarks | B-02 | "Pesos cash (blue)" no está en `BENCH_API_KEY` → `if(!k) return` cancela el refetch: la línea anterior queda con la leyenda nueva | ESTRUCTURAL | 🔴 | `/analisis` en Pesos | dos listas de claves que nadie obliga a coincidir |
| Benchmarks | B-03 | Merval y UVA se resuelven por MES sobre una curva DIARIA — el fix del ancla diaria sólo se aplicó a los tres benchmarks en dólares | MEDIDO | 🟠 | `/analisis` en Pesos | el fix se hizo por serie en vez de por regla |
| Benchmarks | B-04 | Reportes resta retorno en PESOS menos S&P en DÓLARES (y viceversa contra inflación): `benchmark_return_for_period` nunca recibe `moneda` | DEDUCIDO | 🔴 | `/reportes` — frase, chip e insight | el modo pesos se agregó al retorno y no al benchmark |
| Benchmarks | B-05 | Reportes fetchea inflación y S&P en **cada request**, salteando `_bench_cache`/SWR; si fallan, la comparación desaparece sin log | ESTRUCTURAL | 🟠 | latencia + benchmark intermitente | dos call sites que no conocen la caché del módulo |
| Benchmarks | B-06 | `insights.benchmarks` publica `outperform.inflation` cruzando USD contra ARS, y el prompt instruye a afirmar "pérdida real" | ESTRUCTURAL | 🟠 | chat IA (topic sin UI, invocable) | la migración arregló el retorno y no la moneda |
| Benchmarks | B-07 | El `_note` del chat da la regla de pareo para S&P e inflación y no para el Merval, que se publica en pesos junto a un retorno en dólares | ESTRUCTURAL | 🟠 | chat IA | benchmark agregado después de escribir la regla |
| Benchmarks | B-08 | El "vs S&P" del Dashboard usa `monthly` crudo + total CON plazos fijos; el de Insights usa MtM + total SIN | ESTRUCTURAL | 🟠 | `/dashboard`, `/` mobile vs `/analisis` | `applyMtmToMonthly` importado y nunca llamado |
| Benchmarks | B-09 | Crear un plazo fijo saca la plata del patrimonio y no del flujo del simulador → el usuario pierde contra todo por el monto del PF | DEDUCIDO | 🟠 | veredicto AR, chips, diagnósticos | `create_plazo_fijo` debita cash sin registrar retiro |
| Benchmarks | B-10 | Wrapped compara un pseudo-TWR USD contra inflación ARS y contra un S&P de YTD calendario, en un slide compartible | ESTRUCTURAL | 🟡 | `/wrapped` | decisión documentada que contradice la regla escrita del chat |
| Benchmarks | B-11 | La serie diaria es 5y y la mensual `max`, y el diario gana con cobertura parcial; el docstring afirma que las dos son 5y | ESTRUCTURAL | 🟡 | `/analisis` con historia larga | el chequeo es "¿algún punto?" en vez de "¿cubre el rango?" |
| Benchmarks | B-12 | `bench` sin allowlist: cualquier clave da benchmark vacío en silencio; `?bench=dolar_blue&moneda=ars` contaría la devaluación dos veces | ESTRUCTURAL | ⚪ | endpoint | falta de validación en el borde |
| Benchmarks | B-13 | `BENCH_PORCENTUAL`/`BENCH_EN_ARS` declaran `plazo_fijo` (rama muerta) y el docstring del fetcher dice "TNA Minorista BCRA" cuando baja `uva` | MEDIDO | ⚪ | mantenimiento | el nombre de producto quedó tras cambiar la fuente |
| Benchmarks | B-14 | `vsShv`, `vsGold`, `vsMerval` e `inflationCum` se computan en cada render y no los consume nadie; el comentario de `:2315` afirma lo contrario | ESTRUCTURAL | ⚪ | mantenimiento | cards retiradas sin limpiar |
| Benchmarks | B-15 | Los simuladores ejecutan el flujo del mes al cierre de fin de mes, y `compareToMine` contrasta el patrimonio de HOY contra el benchmark al último cierre mensual | ESTRUCTURAL | 🟡 | veredicto AR, chips del Dashboard | granularidad "MVP" que sobrevivió al MVP |
| Benchmarks | B-16 | `vs_sp500_pp` es el **promedio aritmético** de los excesos mensuales, rotulado como pp del período | ESTRUCTURAL | 🟡 | packet IA de Reportes | promediar en vez de componer |
| Benchmarks | B-17 | **PARCHE**: `BenchmarksLine` esconde el chip si `\|pct\|>500` o el benchmark vale ≤US$1, sin decir por qué | ESTRUCTURAL | ⚪ | `/dashboard` | denominador del simulador sin guard; `compareToMine` no tiene ni el parche |
| Benchmarks | B-18 | `/api/insights/performance` no chequea `BENCH_TTL`: sólo si el dict está vacío. Benchmark arbitrariamente viejo, sin campo que lo declare | ESTRUCTURAL | 🟡 | `/analisis` | dos lecturas de la misma caché con criterios distintos |
| Objetivos | O-01 | `cagr: None` (ventana < medio año) se vuelve **0 %** por un `or 0`: "Atrasado · no llegás a la meta" para quien rinde +54 % | MEDIDO | 🔴 | `/objetivos`, packet IA `goal` | un `None` que significa "no se puede anualizar" tratado como "cero" |
| Objetivos | O-02 | El objetivo no tiene aportes: ni columna, ni campo, ni parámetro. El packet IA publica `monthly_contribution: 0.0` de una columna inexistente y el prompt razona sobre ella | ESTRUCTURAL | 🔴 | `/objetivos`, chat IA | el modelo de datos nunca incorporó el aporte que la pantalla promete calcular |
| Objetivos | O-03 | Tres "capital actual" distintos (frontend live / backend live con otro valuador / último snapshot medible), ninguno con plazos fijos | ESTRUCTURAL | 🟠 | `/objetivos` | tres consumidores, tres valuadores |
| Objetivos | O-04 | `delta_pct_required` anualiza ×12 lineal y `required_annual_pct` compone, en el mismo `return` | MEDIDO (28,6 y 41,1 pp) | 🟠 | packet IA `goal` | dos convenciones a tres líneas de distancia |
| Objetivos | O-05 | El objetivo es siempre `target_usd`, sin pesos ni ajuste por inflación; el selector global no lo toca | ESTRUCTURAL | 🟠 | `/objetivos` | la única superficie que quedó fuera del trabajo de monedas |
| Objetivos | O-06 | El diagnóstico llama `_historical_cagr_global` sin `modo` ni `moneda`: el toggle Certero/Estimado mueve la card de arriba y no la de abajo | ESTRUCTURAL | 🟠 | `/objetivos` | el toggle se cableó a un endpoint y no al otro |
| Objetivos | O-07 | `_months_between` ignora el día: hoy 07/09 con objetivo al 30/09 → 0 meses → "la fecha ya llegó". Y el frontend cuenta con otra fórmula (dice "1 mes") | MEDIDO | 🟡 | `/objetivos` | aritmética de calendario por (año, mes) |
| Objetivos | O-08 | `_project_value` compone sin cota y `twr` no capa el CAGR por arriba (sólo se niega bajo medio año): 6,0e11 USD proyectados en el caso medido | MEDIDO | 🟡 | `/objetivos`, packet IA | el guard del motor es sobre la ventana, no sobre la magnitud |
| Objetivos | O-09 | "Tu CAGR (X %)" prellena `expected_return_pct` sin clamp; el backend valida `le=200` → 422 traducido a "Ocurrió un error" | ESTRUCTURAL | 🟡 | `/objetivos` (alta) | validación en el servidor sin espejo en el cliente |
| Objetivos | O-10 | "Expectativa de retorno" compara un retorno real **acumulado** contra un piso **anual**; `monthsCounted` llega a la card y el gauge no lo usa ni lo muestra | ESTRUCTURAL | 🟠 | `/analisis?tab=perfil` | una constante %/año usada como umbral de un acumulado |
| Objetivos | O-11 | Dos "tasa requerida" a 15 px, sobre capitales distintos y con dos formas de contar meses | ESTRUCTURAL | 🟡 | `/objetivos` | la card del diagnóstico se agregó sin retirar el escenario que ya lo decía |
| Objetivos | O-12 | `_cagr_from_monthly_rows` es código muerto (0 call sites fuera de tests); refuta la premisa de P-230 | ESTRUCTURAL | ⚪ | mantenimiento | fallback que sobrevivió a la migración al motor canónico |
| borde | B-01 | `trustMktValue` / `_trust_mkt_value` devuelven `true` con `mktValue = 0` y con `mktValue < 0` → la posición vale 0 (P&L −100 %) o vale negativo. Un precio de 0,0001 sí se rechaza | **MEDIDO** — `valuation.js:449`, `snapshots_job.py:48` | 🔴 | Cartera, Dashboard, snapshot nocturno, torta de composición, packets de IA | El `or` pega "sin costo no hay con qué comparar" (correcto) con "sin valor tampoco" (falso): con valor 0 sí hay con qué comparar, y el múltiplo es absurdo |
| borde | B-02 | `pricing/fci.py:284` acepta `vcp = 0` (sólo chequea `isinstance`) y escribe `price = 0.0`. Las otras 3 fuentes de precio filtran `> 0` | **ESTRUCTURAL** — verificado también contra `origin/main` `82fad6a0`: no corregido | 🔴 | FCI en Cartera, Renta Fija, snapshot | Guard de "precio positivo" aplicado en 3 de 4 fuentes |
| borde | B-03 | La venta no tiene cota de plausibilidad: lote ARS vendido declarando USD → `pnl_usd = +19.989,40`, `pnl_pct = +188.566,67 %` sobre un lote de US$106. El comentario de `:11195` dice que se rechaza; el código de `:11202` cae a todos los lotes | **MEDIDO** | 🔴 | P&L realizado, `monthly_entries`, curva, Reportes, IA | El no-realizado tiene banda ×50 (`trustMktValue`); el realizado no tiene ninguna. El `exit_price` nunca se convierte de moneda |
| borde | B-04 | Fecha futura aceptada por 5 de 7 escrituras (`positions`, `operations`, `sell`, `futures`, `plazos-fijos`). El único guard vive en `/api/bonds/cashflow` | **MEDIDO** — `main.py:8156`, `:11137`, `:12099`, `:12159` vs `:10384` | 🔴 | Toda la cadena contable | Guard escrito para el endpoint donde apareció el incidente, no para la propiedad |
| borde | B-05 | Una fila mensual futura hace que `_rollover_to_current_month` devuelva 0 filas **para siempre** → el mes en curso deja de existir y `sync-unrealized` no-opea en silencio | **MEDIDO** — `main.py:11467-11468` | 🔴 | Cuadro mensual, evolución, P&L no realizado | `last` se elige con `ORDER BY year DESC` sin excluir el futuro |
| borde | B-06 | `POST /api/positions` y `POST /api/operations` aceptan un broker inexistente; `POST /api/monthly` lo rechaza. Medido: aportado 10.999 vs valuación 1.000 = **−US$9.999** de pérdida fantasma | **MEDIDO** | 🟠 | Dashboard (ganancia total, aportado), snapshot, Reportes | El guard existe en 3 lugares (monthly, asesor, chat) y falta en el alta, que es donde se crea la fila |
| borde | B-07 | `PositionIn` es el único modelo monetario sin `le=_FINITE_BOUND`: `invested = 1e308` y `quantity = 1e308` aceptados y propagados a `monthly_entries.capital_final` | **MEDIDO** — `main.py:8142-8147` vs `:11112`, `:12067`, `:11419` | 🟠 | Toda la cadena contable | Guard aplicado a 4 modelos de 5, y falta justo en el que siembra la cadena |
| borde | B-08 | `read_last_prices` no lee `updated_at` (que sí se escribe): un precio de 2019 se sirve como si fuera de hoy. `register_trade` sí lo chequea, con 48 h | **MEDIDO** — `snapshots_job.py:589` vs `main.py:23451` | 🟠 | Delistados, fuentes muertas, feriados largos | La edad del precio es un chequeo local de un caller, no parte del contrato del dato |
| borde | B-09 | `apply_last_known_prices` corre **antes** del guard de cobertura del 95 % → un precio congelado cuenta como "con precio" y habilita el snapshot | **ESTRUCTURAL** — `snapshots_job.py:697` vs `:734` | 🟠 | Snapshot nocturno, curva histórica | El guard mira si FALTA el precio, no si SIRVE |
| borde | B-10 | El hero del Dashboard publica `0,00 %` con aportado ≤ 0, junto a un monto real. El KPI del mismo archivo (`:668`) y `evolution.js` (`:356`, con la medición: 192 usuarios) devuelven `null` | **ESTRUCTURAL** — `Dashboard.jsx:266` + `:823` | 🟠 | Hero del Dashboard | Dos lecturas del mismo concepto en el mismo archivo, con criterios opuestos |
| borde | B-11 | `/api/prices` trunca a 60 símbolos en silencio y **ningún** call site del frontend chunkea. El workaround existe sólo del lado asesor, con el razonamiento escrito | **ESTRUCTURAL** — `main.py:7139`, `:7637`, `:37264` | 🟠 | Carteras grandes: parte al costo, sin cartel | El cap se puso en el endpoint y el chunking nunca se puso en el cliente |
| borde | B-12 | `sumRowUSDT` / `sumRowARS` devuelven `pnlPct = 0` cuando el costo es 0, con `pnl != null` | **MEDIDO** — `valuation.js:919`, `:941` | 🟡 | Filas de Cartera | Mismo "cero falso" que `evolution.js:356` documenta y evita |
| borde | B-13 | MEP `0`/`null` → frontend `Infinity`/`NaN`; backend `0`. Los dos son "port fiel" uno del otro | **MEDIDO** — `valuation.js` vs `snapshots_job.py:222` | 🟡 | Display del Dashboard con FX caído (el cron es fail-closed) | El guard `if rate > 0 else 0` existe sólo del lado Python |
| borde | B-14 | `min_length=1` corre antes del `.strip()`: `broker="   "` y `asset="   "` se guardan como `""` | **MEDIDO** — `main.py:8139-8140` + `:8177-8184` | 🟡 | Fila de `monthly_entries` con broker `''`; posición que nunca se valúa | Orden de validadores de Pydantic v2 |
| borde | B-15 | El cambio de ticker cascadea a `positions`, `import_normalized_tx` y `operations`, pero **no** a `snapshots.holdings_json` ni a `asset_last_price` | **ESTRUCTURAL** — `main.py:8431-8447` | 🟡 | Movers de Reportes, atribución MtM histórica | El mismo razonamiento que justificó cascadear a `operations` no se extendió a la foto histórica |
| borde | B-16 | Fuera de rueda `pct = 0` → `previo = actual` → todas las filas `.BA` muestran `+0,00 %`, que se lee como "no se movió" | **ESTRUCTURAL** — `main.py:7917` (P-153) | 🟡 | Variación diaria de Cartera | No se distingue "no hay dato" de "no se movió" |
| borde | B-17 | `StalePricesNotice` sólo se monta en `/cartera`; Dashboard, Insights, Reportes, Home y los packets de IA leen los mismos precios sin avisar | **ESTRUCTURAL** — `Positions.jsx:2002` | 🟡 | Todas las pantallas menos una | El aviso se hizo donde se reportó el síntoma |
| borde | B-18 | Split + precio congelado: la cantidad queda en escala nueva y el last-known en la vieja → valor ×F o ÷F | **DEDUCIDO** (composición de B-08 y `main.py:8879`) | 🟡 | Cualquier CEDEAR con split cuyo feed se cae | El ajuste de split no invalida el precio cacheado |
| borde | B-19 | `computeBrokerValue(undefined, …)` lanza `TypeError` sin capturar | **MEDIDO** | ⚪ | Pantalla en blanco si el fetch de posiciones falla raro | Falta un `|| []` |
| borde | B-20 | Un `asset = ''` nunca se valúa: `build_price_symbols` lo omite y el valor queda anclado al costo | **MEDIDO** | ⚪ | Posición invisible para el motor de precios | Consecuencia de B-14 |
| borde | B-21 | Venta con `exit_price = 0` aceptada (`pnl_pct = −100 %`) | **MEDIDO** | ⚪ | — | Probablemente correcto: es cómo se da de baja un delistado. Lo dejo anotado para que lo confirmes |

---

## Los 20 rojos, agrupados por qué los causa

No están dispersos: caen en cinco patrones, y **cuatro de los cinco son el mismo que 1A ya había nombrado**.

### 1. Un fix aplicado en un solo call site de varios (el patrón dominante, otra vez)

| tema | el fix existe en… | …y falta en |
|---|---|---|
| Fechas | `AdvisorDashboard.jsx:745` corrige `toISOString` a hora local, **con el comentario que explica por qué** | los otros **27** lugares que calculan "hoy" en UTC |
| Fechas | `reporting/builder.py:1146` arregla el borde YTD con `_dia_anterior` y lo documenta | el KPI de Métricas (`_ytd_delta`) quedó sin migrar |
| Fechas | el backend y `/mensual` tienen el piso de antigüedad del borde | `computeReturnDelta` —el motor del Dashboard y del home mobile— no lo tiene |
| Borde | `POST /api/monthly` valida que el broker exista | `POST /api/positions` y `POST /api/operations` no |
| Borde | `SellIn`, `OperationIn`, `MonthlyIn` aplican `_FINITE_BOUND = 1e12` | `PositionIn` no |
| Borde | `register_trade` rechaza un precio de más de 48 h | `read_last_prices` —que alimenta el snapshot nocturno, el Dashboard y el libro del asesor— no mira la edad |
| Benchmarks | se bajaron series **diarias** para `sp500`, `shv`, `gld` | Merval y Plazo fijo UVA quedaron con ancla mensual |

### 2. El motor está bien y nadie lo usa

Tres veces el mismo hallazgo estructural, en tres conceptos distintos:

- `backend/twr.py` es correcto — **cinco superficies publican otro número con el mismo rótulo** (1A).
- `performance.py` recorta, indexa y convierte el benchmark bien — **otros seis lugares comparan sin pasar por ahí**.
- El motor de valuación canónico `valuePositionLot` existe y **su docstring admite que no lo consume nadie** (1A).

### 3. Un comentario afirma una premisa que es falsa

- Tres comentarios (`advisor_book`, `advisor_brief`, `advisor_alerts`) dicen textualmente *"los snapshots se estampan con fecha ART"* y construyen su lógica sobre eso. **El cron los estampa en UTC**, un día adelante (MEDIDO).
- `useMonthlyData.js:585` dice *"mismo número a propósito: si se separan, uno de los dos está mal"*. **Se separaron.**
- `BondDetail.jsx` dice "serie CER no disponible" arriba y rotula "TIR real sobre CER" 67 líneas abajo.

### 4. Un guard que confía en el peor valor posible

`trustMktValue` arranca con `if !(mktValue > 0) return True`: rechaza un precio de `0,0001` y **acepta un precio de exactamente 0** (posición a 0, P&L −100 %) **y uno negativo** (posición que vale menos que nada). Medido en los dos motores, y con vía de entrada real: `pricing/fci.py:284` acepta `vcp = 0` porque sólo chequea el tipo, y `0` es un `int`.

### 5. Una dependencia externa que se murió sin que nadie se entere

La serie CER devuelve **404** hoy (`/inflacion` y `/uva` del mismo host dan 200). Todos los bonos CER ajustan con factor **1,00** cuando el real es 7,72× o 37,44×. Nadie loguea, nadie alerta.

---

## Lo que está bien, y conviene no romper

Vale registrarlo, porque tres de los seis informes salieron a buscar un defecto clásico y **no lo encontraron**:

- **`double precision` NO es el problema.** Las 142 columnas de plata son float y no hay una sola `numeric` en el esquema. Medido sobre 200.000 pares al azar: el peor error relativo de ida y vuelta de moneda es **2,2e-16** — cero centavos por cada diez mil dólares. Lo que rompe es el **criterio de redondeo**, no el tipo.
- **Nadie suma inflaciones mensuales.** Se buscó el patrón —el error clásico y grave en Argentina— y no hay un solo sitio: los 9 lugares componen con `Π(1+ipc/100)`.
- **Cartera vacía está impecable.** 25 endpoints medidos con un usuario recién creado: ninguno rompe, ninguno divide por cero, y los motores devuelven `null` con un `motivo` legible. Las 6 funciones de composición tienen su guard. **Cero hallazgos**, el caso mejor cubierto de los nueve.
- **Cantidades y montos negativos en la entrada** los rechaza Pydantic con 422 (medido).
- **Primer día sin snapshot previo** está bien cerrado, y es el ejemplo de cómo debería verse todo lo demás.

---

## Interacciones entre hallazgos — importante para el orden de los fixes

Dos casos donde **arreglar uno solo empeora las cosas**:

1. **YTD.** El borde de apertura de `_ytd_delta` está mal (toma la foto del 1 de enero, que ya tiene adentro el aporte de ese día). Hoy el error **está tapado** por el bug de zona horaria: como la fila etiquetada `2026-01-01` es en realidad el cierre ART del 31/12, el borde sale accidentalmente bien. **Arreglar la zona horaria sin tocar `_ytd_delta` hace aparecer un bug que hoy no se ve** (medido: publica −22,86 % sobre una cartera que ganó US$ 1.000).
2. **Snapshots.** Los bugs de valuación del cron (A-1/A-2 de 1A) conviven con dos escritores de `total_invested` que usan convenciones opuestas. Tocar uno sin el otro deja la serie mitad y mitad.

---

## Estado y pendientes

- **Tanda 1A:** 8/8 completa · 94 divergencias · 14 puntos urgentes esperando tu decisión · las 19 consultas de alcance en producción escritas y **sin ejecutar** (`1a-alcance-produccion.sql`).
- **Tanda 1B:** 6/6 completa · 128 hallazgos.
- **Divergencias sin veredicto:** 72 (los 8 grupos de la tanda que quedó pendiente: bonos, snapshot, TIR, dividendos, comisiones, CEDEAR, variación diaria, caja). Los inputs están partidos en `_grupos/`.
- **Preguntas para el founder:** cada informe de 1B lista sólo las bloqueantes, en su encabezado. Sin contestar.
- **Ubicación:** todo este material está en `~/rendi-rescate/untracked/audit/`, fuera del repo.
