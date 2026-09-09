# Plan de remediación — cálculo

**222 hallazgos** consolidados: 94 veredictos sobre implementaciones divergentes (tanda 1A) + 128 hallazgos transversales (tanda 1B).
Commit auditado: `b74f450f` · copia limpia de solo lectura · 14 informes de detalle en `01_calculos/`.

> **Cómo leer los números de este plan.** La agrupación por causa raíz se hizo clasificando la columna "causa raíz" de los 222 hallazgos con búsqueda por patrón, en modo multi-etiqueta (un hallazgo puede tener dos causas). **Los conteos son cota inferior**: 105 filas tienen texto libre que no mapea limpio a ninguna categoría. Lo que sostiene el plan es **el orden relativo de las causas**, que es robusto, no el dígito exacto.

---

## 1. Las causas raíz

| # | causa | hallazgos (≥) | pantallas que toca | esfuerzo |
|---|---|---:|---|---|
| **C1** | **El fix existe pero no se propagó a todos los call sites** | 28 | transversal: Dashboard, Cartera, Reportes, Métricas, mobile, packets de IA, libro del asesor | **medio** — cada caso es de 1 a 3 líneas, pero son ~28 casos y hay que encontrar los call sites hermanos |
| **C2** | **Copiar y pegar sin un origen designado** | 21 | Cartera desktop/mobile, ficha de activo, Dashboard, Insights | **grande** — no se arregla editando: hay que elegir el origen y borrar las copias |
| **C3** | **Falta una capa compartida: no hay dónde poner el cálculo** | 17 | valuación, FIFO, capital aportado, plazos fijos | **grande** — es trabajo de arquitectura |
| **C7** | **Guard o cota ausente en un lector** | 17 | rendimiento (desborde hacia arriba), valuación, ventas | **chico** — el guard ya existe escrito; es llevarlo a los lectores que no lo tienen |
| **C5** | **Migración empezada y nunca terminada** | 14 | `valuePositionLot`, `twr.py`, `performance.py`, columna `cost_basis_consumed` | **grande** — terminar migraciones abiertas |
| **C8** | **Cada capa decide su propia política de faltantes y defaults** | 10 | precios ausentes, TC ausente, índice no publicado, mes sin dato | **medio** — requiere una decisión de producto antes que código |
| **C4** | **Port a mano que quedó atrás del original** | 9 | snapshots, brief del asesor, motores de cronograma | **medio** |
| **C10** | **Modelo de datos incompleto (tipo, moneda, FK)** | 8 | brokers linkeados por nombre, `pnl_usd` polimórfico, `positions.currency` | **grande** |
| **C6** | **El frontend hace lo que el backend no sabe hacer** | 7 | toggle de costo, benchmark del gráfico, totales de Cartera | **medio** |
| **C11** | **Decisión deliberada o parche documentado** | 6 | — | **ninguno** — no son bugs; se documentan y se cierran |
| **C9** | **Zona horaria y calendario** | 3+ | todo lo que tenga fecha | **medio** — pocos hallazgos, muchísimo alcance |
| **C12** | **Documentación que afirma algo que el código no hace** | 2+ | — | **chico** — pero es lo que hace fallar a los auditores siguientes |

### Las dos que explican el resto

**C1 es la causa dominante y no es descuido: es la forma que toma un fix correcto en este código.** El patrón se repite idéntico: alguien diagnostica bien, arregla bien, deja el comentario que explica por qué — y el arreglo llega a un call site de varios. Ejemplos verificados:

- `AdvisorDashboard.jsx:745` corrige `toISOString` a hora local **con el comentario que lo explica**; los otros **27** lugares que calculan "hoy" siguen en UTC.
- El fix del TC histórico se aplicó a **2 de 3** motores de venta.
- Las series diarias de benchmark se bajaron para los 3 del selector **en dólares**; los 2 del selector **en pesos** quedaron con ancla mensual.
- `register_trade` rechaza un precio de más de 48 h; `read_last_prices` —que alimenta el snapshot nocturno, el Dashboard y el libro del asesor— no mira la edad.
- `POST /api/monthly` valida que el broker exista; `POST /api/positions` y `POST /api/operations` no.

**C12 es chica en conteo y grande en consecuencia.** Hay comentarios que afirman premisas falsas y sobre los que después se construyó lógica: tres archivos del producto asesor dicen textualmente *"los snapshots se estampan con fecha ART"* y el cron los estampa en UTC. Un comentario dice *"mismo número a propósito: si se separan, uno de los dos está mal"* — y se separaron. Mientras esos comentarios sigan ahí, **el próximo que lea el código va a repetir el error**.

---

## 2. Dependencias entre fixes

Los casos donde **arreglar uno solo deja el sistema peor o descubre un bug que hoy no se ve**. El de zona horaria era el ejemplo; hay seis más.

### D-1 · Zona horaria ⟶ destapa el YTD
El borde de apertura de `_ytd_delta` está mal: toma la foto del 1 de enero, que ya tiene adentro el aporte de ese día. **Hoy el error está tapado** porque el cron estampa en UTC: la fila etiquetada `2026-01-01` es en realidad el cierre ART del 31/12, así que el borde sale bien por accidente.
**Arreglar la zona horaria sin tocar `_ytd_delta` hace aparecer un bug que hoy nadie ve** (medido: publica −22,86 % sobre una cartera que ganó US$ 1.000). → **Van juntos, obligatorio.**

### D-2 · `capital_inicio` ⟶ destapa la divergencia de "Capital aportado"
1A dictaminó que DIV-029 (dos pantallas con el label "Capital aportado" y números distintos) **parece inofensiva sólo porque el recalc ya borró el baseline** en las cuentas que recalcularon: sin baseline, las dos convenciones coinciden.
**Arreglar el borrado de `capital_inicio` (A-4) hace reaparecer la divergencia** en todas esas cuentas. → **Van juntos.**

### D-3 · Conversiones FX ⟶ de "se cura sola" a "permanente"
La conversión ARS→USD importada crea capital de la nada (+US$293 por cada US$1.000), pero **se autodestruye**: como las filas no son `DEPOSIT/WITHDRAW` ni `manual_*`, el primer recalc las pisa con cero.
**Si se arregla el recalc antes que la conversión, el capital fantasma deja de borrarse y queda fijo.** → **La conversión primero, el recalc después.**

### D-4 · Valuación de snapshots ⟶ el guard de cobertura quedó afuera (verificado)
El fix `86402f00` arregla la valuación, pero **no tocó `_cost_usd`**, la closure que pondera el guard de cobertura del 95 % — y que sigue decidiendo por la moneda del **broker**, no del **lote**. Un lote en pesos dentro de una cuenta USD sigue pesando ~MEP× de más en esa ponderación, lo que **sesga la cobertura hacia 100 % y puede tapar faltantes de precio reales en otras posiciones**. Además la closure está **duplicada en dos lugares del mismo archivo** (líneas 769 y 924 de la versión con el fix), que es exactamente C2. → **Falta un fix hermano.**

### D-5 · Dos escritores de `snapshots.total_invested` con convención opuesta
El cron escribe con una convención de costo y el navegador con la otra: **la definición del costo histórico depende de si el usuario abrió la app antes de que corriera el cron.** Arreglar la valuación sin unificar la convención deja la serie mitad y mitad. → **Va con cualquier trabajo sobre snapshots.**

### D-6 · `trustMktValue` acepta el 0 ⟶ cambia valuaciones publicadas hoy
El guard arranca con `if !(mktValue > 0) return True`: rechaza un precio de `0,0001` y **acepta el 0 y los negativos**. Arreglarlo **cambia el valor publicado de las posiciones que hoy valen 0**, hacia arriba. Es el fix correcto, pero **es visible para el usuario** y conviene anunciarlo, no deployarlo callado.

### D-7 · El cap de `/api/fx-rates` ⟶ dos fixes, no uno
Poner `WHERE date >= ?` arregla la ventana de 2016, pero **no arregla la causa**: que ante un TC ausente el sistema caiga silenciosamente al **dólar de hoy**. Con el cap arreglado, el fallback mudo sigue vivo para cualquier otro hueco de la serie. → **El cap es el síntoma; la política de faltantes (C8) es la causa.**

---

## 3. Las tandas de fix

Cada tanda deja el sistema **en un estado consistente**: se puede parar ahí sin dejar nada a medio camino.

### Tanda F1 — «Que deje de escribir mal» *(2–3 días)*
Lo único que corrompe datos nuevos todas las noches. **Nada más entra acá.**
- Valuación del cron ✅ **ya hecho** (`86402f00`) — falta el hermano **D-4** (guard de cobertura) y **D-5** (unificar la convención de `total_invested`).
- `capital_inicio` que el recalc borra **(A-4)** — junto con **D-2**.
- Amortización manual que guarda el cash bruto como P&L **(A-5)**.
- `fx_to_usd = 1.0` en ventas en pesos **(A-7)** y `SellModal` sin `fxHist` en mobile **(A-8)**.
- TC hardcodeado 1415 en `reconcile-cash` **(A-6)**.
- Conversión ARS→USD importada **(A-9)** — antes que el recalc, por **D-3**.
- Fecha futura que congela el calendario mensual.
**Estado al cerrar:** el sistema deja de escribir números falsos. Lo ya escrito sigue mal.

### Tanda F2 — «Que la IA y lo que sale de la app no mientan» — ✅ HECHA (`fix/f2-que-no-mientan`, sin deployar)
Lo que se publica hacia afuera o hacia el modelo. Detalle de lo hecho y de lo que quedó
abierto a propósito: `audit/_HANDOFF-TANDAS.md` §4.
- P&L de por vida duplicado ×2 en el contexto del chat **(B-3)**.
- El `ret_pct` sin filtrar que va al prompt que **rankea clientes** **(B-2)**.
- El slide del Wrapped rotulado «TWR» sobre una fórmula que no lo es **(B-1)** — el **rótulo** se puede cambiar hoy, sin tocar el cálculo.
- `Interés PF` sin conversión ni filtro **(B-4)** — verificar primero con la consulta Q7: **si da 0 filas, baja de urgente a estructural**.
**Estado al cerrar:** nada que salga de la app o llegue al modelo está inflado.

### Tanda F3 — «Un solo calendario» *(3–5 días)*
- El cron sella en ART, no en UTC.
- `_ytd_delta` **en el mismo commit** (**D-1**, obligatorio).
- Los 27 `toISOString` restantes.
- Los tres comentarios que afirman "fecha ART" — **corregirlos es parte del fix** (**C12**).
- Unificar "este mes": llevar el piso de antigüedad del borde a `computeReturnDelta`.
**Estado al cerrar:** una sola definición de hoy, de mes y de año en toda la app.

### Tanda F4 — «Los guards que ya existen, en todos los lectores» *(2–3 días)*
Todo C7. Es la tanda de mejor relación resultado/esfuerzo: **el código ya está escrito**, sólo no llegó.
- `trustMktValue` con el 0 y los negativos (**D-6** — anunciarlo).
- Cota de plausibilidad en el P&L realizado (hoy no tiene ninguna; medido +188.566 %).
- `_FINITE_BOUND` en `PositionIn`.
- Validación de broker existente en `positions` y `operations`.
- Edad máxima del precio en `read_last_prices`.
- El guard de denominador peak en el hero del Dashboard y en los lectores de retorno.

### Tanda F5 — «Una sola cotización, una sola política de faltantes» *(4–6 días)*
- El cap de `/api/fx-rates` **y** el fallback mudo al dólar de hoy (**D-7**, los dos).
- ~~Serie CER caída: reponerla **y** agregar detección — hoy devuelve 404 y nadie se entera.~~
  ✅ **HECHO** y adelantado a F2 (`fix/f2-que-no-mientan`, sin deployar). Se sirve con UVA
  —el ratio es el mismo porque el BCRA la actualiza POR CER, verificado a 0,25 % contra los
  factores medidos—, la caída ya loguea y la tarjeta dejó de contradecirse. Ver
  `audit/_HANDOFF-TANDAS.md` §4-bis.
- Unificar punta venta vs. punta media entre `fx_rates_daily` y la valuación viva.
- Decidir y aplicar **una** política de faltantes (C8): precio ausente, TC ausente, índice no publicado.
- Gatear por moneda lo que hoy resta inflación-en-pesos a retornos-en-dólares (6 sitios) y pasar `moneda` a los benchmarks.

### Tanda F6 — «Terminar las migraciones abiertas» *(1–2 semanas)*
Todo C5 + lo que se pueda de C2.
- Migrar los 5 lectores que faltan a `valuePositionLot` y **borrar** las matrices duplicadas.
- Las 5 superficies que publican retorno sin pasar por `twr.py`.
- Los 6 lugares que comparan contra benchmark sin pasar por `performance.py`.
- Persistir `cost_basis_consumed` en la venta.
**Estado al cerrar:** un solo motor por concepto. **Acá es donde C1 deja de reproducirse.**

### Tanda F7 — «El modelo de datos» *(proyecto aparte)*
C10 + C3. No es una tanda de fixes: es diseño.
- `operations.pnl_usd` polimórfica (guarda cuatro cosas en dos monedas).
- `_NOT_A_TRADE` como lista de **exclusión**: todo `op_type` nuevo entra como "trade ganado" **por omisión**. Ya pasó con `Interés PF`; `Renta`, `Cupón` y `Amortización` esperan.
- Brokers linkeados por nombre en 6 tablas.
- Plazos fijos que no escriben `monthly_entries`.
- Objetivos sin aportes.

---

## 4. Qué hay que re-verificar por el fix `86402f00`

El commit porta la rama 2 del canónico y unifica `_cost_in_pesos` entre la valuación y la clave de precio. **Verificación del propio commit:** 24 comparaciones sobre 9 escenarios contra el motor canónico JS — antes 11 coinciden / 13 divergen, después **24 / 0**. El caso del repro pasa de `1.500.000 / 1.500.000` a `1.034,48 / 1.103,45`.

| hallazgo | estado | qué hay que hacer |
|---|---|---|
| **A-1** (costo en pesos como dólares) | ✅ **resuelto en el código** | Re-verificar. **Los datos ya escritos NO se tocaron** (el commit lo dice) |
| **A-2** (ADR de NYSE en vez del `.BA`) | ✅ **resuelto** | Ídem |
| **A-3** (el cron pisa al browser) | ⬜ **queda sin efecto** | Ya lo había reclasificado: no era bug, era lo que impedía que A-1 se auto-corrigiera. Con A-1 arreglado, cerrar |
| **DIV-145, DIV-146** (valuación) | ✅ probablemente | Re-verificar contra el fix |
| **DIV-124, DIV-125, X-3** (tenencia) | ✅ probablemente | Ídem |
| **DIV-054** (costo/FIFO) | ✅ probablemente | Ídem |
| **guard de cobertura `_cost_usd`** | ❌ **NO resuelto — verificado por mí** | El diff no lo toca. Sigue decidiendo por moneda del broker, y está duplicado en 2 lugares. **Es D-4** |
| **M-02, M-03, M-13** (monedas) | ⚠️ parcial | Tocan `snapshots_job`; re-verificar cuáles sobreviven |
| **B-01, B-02, B-06, B-08, B-09, B-13, B-15** (borde) | ⚠️ revisar | Citan `snapshots_job`; varios son de `trustMktValue`, que **no** se tocó |
| **D-15** (decimales) | ⚠️ revisar | Marcado "zona de trabajo activa" |
| **filas ya escritas** | ❌ **abierto** | Hay una `PROPUESTA_limpieza_snapshots_A1_A2.md` **sin ejecutar**. El alcance sale de las consultas Q1a–Q1d |

**Costo de re-verificar:** bajo. El repro `repro_a1_a2_a3.py` corre contra el código nuevo y da el veredicto en una corrida.

---

## 5. Las 72 divergencias pendientes: cuáles ahora y cuáles después

Ninguna conviene auditarla hoy contra el código viejo si la tanda que la determina está por cambiar.

| grupo | divs | cuándo | por qué |
|---|---:|---|---|
| **Snapshot / foto histórica** | 11 | **después de F1** | Es la víctima directa de A-1/A-2. Auditarla contra el código ya arreglado da el veredicto real en vez del histórico |
| **Variación diaria / evolución** | 7 | **después de F3** | Lee `snapshots` y depende de la fecha de sellado. Con dos calendarios activos, cualquier veredicto se rehace |
| **TIR / XIRR** | 9 | **después de F1** | Depende de capital aportado y flujos, que F1 modifica (A-4, A-6, A-9) |
| **Caja / cash** | 7 | **después de F1** | `reconcile-cash` y las conversiones se tocan en F1 |
| **Dividendos, cupones, amortizaciones** | 9 | **después de F1** | Se cruza con A-5 y con el patrón `_NOT_A_TRADE` |
| **Bonos (escala per-100, paridad)** | 13 | **ahora** | Clase de activo; independiente de las tandas. Y el hallazgo del CER caído pide mirar bonos ya |
| **CEDEAR (ratio, split, pata USD)** | 8 | **ahora** | Ídem |
| **Comisiones e impuestos** | 8 | **ahora** | Apareció de refilón en 3 informes de 1A sin veredicto propio |

**Auditables ya: 29 divergencias** (bonos, CEDEAR, comisiones). **Las otras 43 conviene esperarlas** — auditarlas hoy produce veredictos que hay que rehacer.

---

## 6. Veredicto

**No. Hoy los números que ve un usuario de Rendi no son confiables, y el problema no es de precisión sino de identidad: el mismo concepto tiene varios valores distintos según la pantalla.**

De 94 divergencias auditadas, **85 dan números realmente distintos** — sólo 9 eran cosméticas. Hay pantallas contiguas de la misma app que muestran el mismo P&L con tres valores, y un caso medido donde Dashboard y Cartera dan **signo opuesto** sobre la misma cartera el mismo día.

Lo grave no es la magnitud sino que **es silencioso**: no hay excepciones, ni logs, ni banner. El usuario ve una discrepancia y la atribuye al mercado. El guard de integridad que existe para impedirlo reportaba cobertura del 100 % mientras se escribía el dato corrupto, porque medía con la función correcta y valuaba con la incorrecta.

También hay que decir lo otro: **los motores centrales están bien construidos.** `twr.py`, `performance.py` y `valuePositionLot` son correctos y están documentados con las mediciones que los justifican. El problema es que el producto no los usa: cinco superficies publican retorno sin pasar por el motor de retorno, seis comparan contra benchmark sin pasar por el de benchmark. **Esto no es un sistema mal pensado; es un sistema bien pensado cuyas correcciones nunca terminaron de propagarse.** Por eso el trabajo se puede ordenar en tandas y no es una reescritura.

Y una advertencia sobre el estado de la evidencia: **de los 222 hallazgos, 50 están medidos ejecutando código; el resto es lectura verificada con grep.** Ninguna magnitud de este plan dice cuántos usuarios reales están afectados — eso todavía no se midió. Las 19 consultas de alcance están escritas y **sin ejecutar** (`01_calculos/1a-alcance-produccion.sql`). Hasta que corran, todo lo que hay acá es "el código hace esto", no "le pasa a N personas".
