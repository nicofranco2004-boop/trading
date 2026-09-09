# Handoff — auditoría de cálculo de Rendi y las tandas de fix que quedan

**F2 está hecha** y **el CER de F5 también** (rama `fix/f2-que-no-mientan`, sin deployar).
Ver §4 y §4-bis. Todo lo demás está para que entiendas por qué, sin tener que reconstruirlo.

**Base:** `origin/main` actual. Trabajá siempre sobre eso, **no** sobre el commit del mapeo — el
código se movió y la auditoría original se hizo sobre `b74f450f`, que ya no es producción.

---

## 1. Qué es Rendi

App argentina de seguimiento y análisis de carteras de inversión **multi-broker**: tenencias,
operaciones, P&L realizado y no realizado, rendimientos (incluido ajustado por inflación),
objetivos y comparaciones contra benchmarks. Tiene planes de suscripción, período de prueba y un
**plan para asesores** (B2B2C: un asesor ve el libro de sus clientes).

Dos cosas del dominio que explican la mitad de los bugs:

- **Argentina tiene varios dólares** (blue, MEP, CCL, cripto, oficial) con brechas materiales.
  Elegir mal la cotización, o usar la de hoy para una operación de 2021, desvía plata de verdad.
- **Un mismo activo se puede tener en pesos y en dólares** en el mismo broker, y hay
  sub-brokers (`Cocos · USD`) que son la pata dólar de un broker argentino. La moneda del
  **lote** y la moneda de la **cuenta** no son lo mismo, y confundirlas es la causa raíz de
  varios de los errores más grandes que encontramos.

---

## 2. Qué se auditó, y cómo

Antes de esto ya existía un **mapa del sistema** (`audit/00-mapa-sistema.md`, 28.586 líneas) que
documentaba *qué hay*. Lo que se hizo después responde *qué está mal*.

Se auditó en dos tandas, con agentes en paralelo, cada uno sobre una copia limpia de solo lectura
del commit de producción:

| tanda | qué cubrió | resultado |
|---|---|---|
| **1A** | 94 de las 166 "implementaciones divergentes" — casos donde el mismo concepto se calcula de más de una forma. Se eligió la **cadena del número que el usuario ve**: tenencia → costo/FIFO → valuación → P&L, capital aportado → rendimiento, con FX multiplicando todo | **85 de 94 dan números realmente distintos.** Sólo 9 eran cosméticas |
| **1B** | 6 temas transversales: decimales y precisión, monedas y cotizaciones, fechas y zonas horarias, inflación/UVA/CER, benchmarks y objetivos, casos borde | **128 hallazgos.** Los últimos tres conceptos no estaban mapeados: se mapearon y auditaron a la vez |

**Total: 222 hallazgos con veredicto.** De esos, **50 están MEDIDOS ejecutando código** (con la
traza pegada en el informe); el resto es lectura verificada con grep. La distinción está hallazgo
por hallazgo en `audit/01_calculos/1a-evidencia.md`, y **importa**: ninguna magnitud dice cuántos
usuarios reales están afectados — eso todavía no se midió.

### El veredicto general, sin suavizar

**Los motores centrales están bien.** `backend/twr.py`, `backend/performance.py` y
`frontend/src/utils/valuation.js::valuePositionLot` son correctos y están documentados con las
mediciones que los justifican.

**El problema es que el producto no los usa.** Cinco superficies publican rendimiento sin pasar
por el motor de rendimiento; seis comparan contra benchmark sin pasar por el de benchmark; el
valuador canónico admite en su propio docstring que todavía no lo consume nadie.

No es un sistema mal pensado. Es **un sistema bien pensado cuyas correcciones nunca terminaron
de propagarse** — por eso se ordena en tandas y no es una reescritura.

### La causa raíz dominante

De las 12 causas raíz identificadas, la más frecuente (**≥28 hallazgos**) es:
**un fix correcto que se aplicó en un solo call site y no se propagó al resto.**

El patrón se repite idéntico: alguien diagnostica bien, arregla bien, deja el comentario que lo
explica — y el arreglo llega a un lugar de varios. Ejemplos verificados: el fix de `toISOString`
está en 1 de 28 lugares; el del TC histórico en 2 de 3 motores de venta; las series diarias de
benchmark se bajaron para los 3 del selector en dólares y no para los 2 en pesos.

**Las dos reglas permanentes de `CLAUDE.md` salieron de acá.** Respetalas.

### Dónde está todo

| archivo | qué es |
|---|---|
| **`audit/01-calculos.md`** | **el plan.** 222 hallazgos por causa raíz, 7 dependencias entre fixes, las 7 tandas, el veredicto. **Leé este primero, es corto** |
| `audit/01_calculos/1a-resumen.md` | tabla de las 94 divergencias con veredicto |
| `audit/01_calculos/1b-resumen.md` | tabla de los 128 hallazgos transversales |
| `audit/01_calculos/1a-*.md` (8) | los informes de detalle de 1A, uno por concepto |
| `audit/01_calculos/1b-*.md` (6) | los informes de detalle de 1B, uno por tema |
| `audit/01_calculos/1a-evidencia.md` | MEDIDO vs DEDUCIDO vs ESTRUCTURAL, hallazgo por hallazgo |
| `audit/_fixes/F1-datos-a-limpiar.md` | los datos que quedaron mal, si son recalculables y el riesgo |
| `audit/01_calculos/_grupos/*.md` | las 72 divergencias **sin** veredicto, partidas por concepto |
| `audit/00-mapa-sistema.md` | el mapa, 3,4 MB — **no lo leas entero**, grepealo |

⚠️ **El mapa es hipótesis, no verdad.** Se verificaron 290 de sus citas: **~53 tenían el número
de línea corrido y 5 afirmaciones eran sustantivamente falsas.** Confirmá cada cita con grep
antes de apoyarte en ella. Si el código contradice al mapa, **gana el código**.

---

## 3. F1 — hecha y deployada

**«Que deje de escribir mal».** Criterio: sólo lo que **corrompe datos nuevos**. Un número mal
mostrado se arregla el día que se corrige el código; un número mal **escrito** queda.

13 commits, cada uno con un test que falla contra el código viejo:

| qué estaba mal | efecto medido |
|---|---|
| El cron de snapshots contaba un costo en pesos como dólares en cuentas USD | **×1.450.** Y el guard de integridad reportaba cobertura 100 % porque medía con la función correcta y valuaba con la incorrecta |
| El guard de cobertura del 95 % ponderaba por la moneda del **broker**, no del **lote** | dejaba ciego al guard: tapaba faltantes de precio reales |
| Una conversión de moneda creaba capital de la nada | US$444.342 salieron y US$217.932 volvieron sin que ningún broker los acreditara. 41 usuarios, 12 con capital aportado **negativo** |
| `reconcile-cash` dividía por un dólar **hardcodeado (1415)** | su único caller nunca manda el campo → +7,3 % de capital fantasma, permanente |
| El recalc **borraba** el `capital_inicio` que el usuario tipeó | irrecuperable. Se disparaba con el primer import, revert, borrado de broker o cierre de futuro |
| La venta sellaba un TC distinto del que usó para dividir el P&L | fila con `fx_to_usd = 1.0` y P&L dividido por ~1.400; el mensual del broker recibía pesos como dólares |
| `SellModal` no recibía las cotizaciones históricas **en mobile** | una venta retroactiva desde el celular quedaba escrita al dólar de hoy |
| Una operación con fecha futura **congelaba el calendario mensual** | el usuario se quedaba sin fila del mes en curso hasta 2030 |
| El guard antidistorsión aceptaba valor **negativo y NaN** | la posición se publicaba valiendo menos que nada |
| `PositionIn` no acotaba sus montos | `invested = 1e308` entraba y llegaba a `capital_final` |
| Se podía cargar una posición contra un broker **inexistente** | fila huérfana → pérdida fantasma de −US$9.999 |

**Efecto visible esperado, que NO es un bug:** al dejar de borrarse la baseline, "Capital
aportado" muestra **dos números distintos** entre Dashboard y Reportes para quienes la habían
cargado. Esa divergencia ya existía; estaba tapada porque el dato se borraba. Unificar esos dos
lectores es **F6**.

**Lo que F1 NO hace:** no repara los datos que ya están mal. Eso es la limpieza, y sigue
pendiente de medir.

---

## 4. F2 — ✅ HECHA, sin deployar

Rama `fix/f2-que-no-mientan`, 7 commits sobre `origin/main` (`04a5736e`). Cada uno con un test
que **falla contra el código viejo** — verificado revirtiendo sólo el archivo de código y
dejando el test. Suite: los mismos 33 fallos preexistentes que el baseline, cero nuevos;
frontend 1.470 en verde. `git merge-tree` contra `origin/main` da limpio (mientras tanto entraron
dos commits de seguridad de otra sesión, que tocan `main.py` en otra zona).

| # | qué era | dónde quedó |
|---|---------|-------------|
| B-3 | el ×2 en el contexto del chat | `frontend/src/utils/aiSummary.js` — las dos copias de `buildSummary` unificadas en una, con el filtro `global` |
| B-2 | el `ret_pct` sin filtrar del prompt que rankea clientes | `_advisor_book_chat_context`, con `_es_base_de_mercado` |
| B-1 | el «TWR» del Wrapped | rótulo + **el denominador de los 5 lectores** al primitivo `twr.dietz` |
| B-4 | `Interés PF` sin conversión | TC sellado al escribir + `_NATIVE_CCY_OPS` (Python **y** el espejo JS) |

**Lo que quedó abierto a propósito, y es del dueño:**

- **Q7 no se pudo contestar desde acá** (¿cuántas filas `Interés PF` hay en producción?): las
  copias locales están vacías. El fix de B-4 es seguro con 0 filas **y** con filas —no toca
  ninguna fila vieja— pero la MAGNITUD del hallazgo sigue sin medir.
- **`Interés PF` sigue contando como "operación ganada"** en los 6 win rates. Es `_NOT_A_TRADE`,
  o sea F7: sacarlo le cambia el significado a la métrica. Hay un test que congela la asimetría.
- **El Wrapped sigue midiendo sobre la cadena contable.** El rótulo ya no dice TWR y el
  denominador ya es el del motor, pero la base son `monthly_entries` (con `pnl_unrealized`
  forzado a 0 en los meses cerrados). Migrarlo a `twr.curva_indexada` es **F6**.

**La trampa que costó, para que no se repita:** al pasar los 5 lectores a `twr.dietz` es natural
dar por cubierto el guard `ci > 0` que traían. **No lo está**: `dietz` sólo corta cuando el
denominador es `<= 0`, y con `capital_inicio = 0` más un depósito el denominador queda en
`0,5·flujo`, que da positivo — o sea que el mes de alta empezaba a publicarse, inflado
(23,71 % contra 20,10 % real, medido en `twr.tramos`). Los dos guards tienen que convivir.

**Y un guard del repo cazó un fix a medias mío:** `assetPnl.js` mantiene a mano el espejo en JS
de `_NATIVE_CCY_OPS`, y `test_advisor_composition.py` falla si las dos listas divergen. Agregué
`Interés PF` del lado de Python y el test se puso en rojo. Es exactamente la causa raíz que la
auditoría persigue, agarrada por un guard que ya existía.

### Lo que salió de auditar la propia tanda

Tres cosas eran **parches, no soluciones integradas** por el estándar del `CLAUDE.md`. Las tres
quedaron arregladas (commits `d89785ef`, `b26ab9dd`, `ed12d949`):

1. **El guard estaba copiado 5 veces.** El fix unificó el primitivo (`twr.dietz`) pero dejó el
   `ci > 0` en cada lector — justo el que se pierde. Ahora es `twr.retorno_mensual`, que responde
   la pregunta completa; ningún lector ve `dietz` pelado.
2. **B-2 hizo coincidir dos copias en vez de unificarlas.** La regla 2 dice textual que la
   respuesta por defecto no es arreglar las dos. Estaba duplicado hasta la query
   `MAX(net_deposited)` palabra por palabra. Ahora hay `_retorno_vs_aportado` y nada más.
3. **B-3 unificó, pero nada impedía que las copias vuelvan.** Ahora hay un test que lee el código
   de las dos pantallas del chat.

Los tres guards nuevos leen CÓDIGO, no números, y los tres se verificaron poniendo el bug de
vuelta a mano.

**⚠️ Lo que QUEDA ABIERTO de mi propio fix, y es un hallazgo del audit ya catalogado (DIV-087):**
al convertir `Interés PF`, el número queda bien en todo lo que pasa por `realized_pnl.py`
—`monthly_entries` (el recalc usa `realized_usd_sql`), el Dashboard, Reportes, los packets de IA,
`assetPnl.js`— y **sigue crudo en los lectores que leen `pnl_usd` a pelo**: `AssetDetail.jsx:174`,
`diagnostics.js` y el detalle mobile de posición. Antes estaba mal en TODOS (uniformemente); ahora
está bien en la mayoría y mal en esos tres. Es la misma situación que ya tienen Cupón y
Amortización, y el arreglo de verdad es DIV-087 ("convertir en el endpoint, no en cada lector"),
que hay que hacer para los tres op_types juntos porque cambia números en pantalla.

**⚠️ Y una corrección de método:** dije "cero fallos nuevos, mismo set exacto que el baseline"
sobre el conteo de la suite completa, y ese número **no sirve como métrica**. Probado en un
worktree limpio de `origin/main`: agregar UN test que crea UN usuario cambia el conteo de 31 a 30,
sin tocar una línea de código. La comparación válida es **archivo por archivo, aislado, con base
fresca y el mismo `backend/.env`** (su ausencia sola cambia 6 resultados de `test_advisor_plan`).
Hecho así sobre los 247 archivos, en las dos ramas: **la única diferencia es el archivo de test
nuevo, que pasa.**

**Y una corrección a la corrección, que la hizo otra sesión.** Atribuí a dependencia del orden
tres rojos (`test_reports_variaciones_f4`, `test_quota_window_corte`, `test_trial_funnel_smoke`).
La dependencia del orden existe —el experimento del usuario de más lo prueba— pero **esos tres no
eran eso: era el reloj**. De 21:00 a 00:00 ART, `datetime.utcnow().date()` ya pasó al día
siguiente y `date.today()` no: los tests sembraban con un reloj y asertaban con el otro. Está
arreglado en `main` (`4ad6eed7`) y esta rama lo mergeó. **Corolario para la próxima tanda: antes
de explicar un rojo, mirá la hora.**

**Estado tras mergear `origin/main` (2026-09-08 22:40):** backend **6 rojos**, los seis en
`test_advisor_plan` (`ClaimFlow`/`LinkRequest`) y **los mismos seis en un worktree pristino de
`origin/main` con el mismo `.env`** — son de entorno, no del código. Frontend **1.481 en verde**.

---

### El hallazgo original (lo que decía este documento antes)

**«Que la IA y lo que sale de la app no mientan».** Cuatro hallazgos, todos publicados hacia
afuera o hacia el modelo. **Dos son casi de una línea.**

**1 · La IA recibe el P&L de por vida duplicado ×2 exacto.**
`RendiAI.jsx:170` y `AICoachDrawer.jsx:177` suman `pnl_realized` de todas las filas de
`GET /api/monthly`, que incluye la fila sintética `broker='global'` **más** las por-broker.
`Dashboard.jsx:243` tiene el `.filter(m => m.broker === 'global')` que falta, 70 líneas más
arriba. Afecta también a `deposits_lifetime` y `withdrawals_lifetime`, así que **cualquier ratio
que el modelo derive sale mal por partida doble**. Viaja en el contexto de **cada** mensaje del chat.

**2 · El prompt que rankea clientes recibe un retorno sin filtrar.**
`main.py:35516` hace la misma lectura que `main.py:37073` pero **sin `_es_base_de_mercado`**. El
propio código documenta el síntoma que ese filtro vino a matar («+39,6 % mientras su propia
pantalla decía "—"»). **Fix de una línea, con el arreglo ya escrito en el mismo archivo.**

**3 · El Wrapped dice literalmente «Tu rendimiento TWR» sobre una fórmula que no es TWR.**
Le falta el `0,5·F` del denominador y va sobre base al costo. +10,0 % donde el motor mide
+6,67 %; compuesto a doce meses, **+213,8 % contra +115,7 %**. `shareCard.js` lo exporta como
**PNG**, o sea que ese número **sale de la app**. Si migrar el cálculo lleva tiempo, **el rótulo
se puede cambiar hoy** sin tocar nada más. Los tres packets de IA arrastran la misma fórmula;
`insights_benchmarks.py` ya fue migrado por este motivo **y lo documenta** — los otros quedaron.

**4 · `Interés PF` se escapa de todos los filtros y de toda conversión.**
No está en `_NATIVE_CCY_OPS` (`realized_pnl.py:78`) y nace con `fx_to_usd = NULL`
(`main.py:9315`). Un plazo fijo de $10M a 30 días inyecta **US$328.767 falsos** en cinco
pantallas y suma "una operación ganada" a los seis win rates.
⚠️ **Verificá primero si hay filas.** El código lo documenta como "hoy no muerde (0 filas)". Si
sigue en 0, esto baja de urgente a deuda estructural.

**Por qué esta tanda primero:** son pocos, están acotados, y son **lo único que se publica fuera
de la app o alimenta al modelo**. Un número inflado en una pantalla lo ve un usuario; un número
inflado en el prompt le tuerce el consejo a todos.

---

## 4-bis. El CER de F5 — ✅ HECHO, adelantado a propósito

El plan lo pone en F5, después de F3. Lo adelanté porque la comparación no da:

| | qué estaba mal | cuánto |
|---|---|---|
| F3 | el cron sella el día en UTC en vez de ART | **un día** |
| CER | todos los bonos CER ajustaban con factor **1,00** | el real es **7,7×–37,6×** |

**Confirmado en vivo el 2026-09-08:** `api.argentinadatos.com/v1/finanzas/indices/cer`
devuelve 404 mientras `/inflacion` y `/uva` del MISMO host devuelven 200. No está en
ninguna variante de la ruta (`/cer/`, `/cer/2026`, `/indices`). No es la fuente caída: es
esa ruta, y no vuelve sola.

**Se sirve con UVA, y no es un parche.** Acá NO se usa el NIVEL del índice:
`bondSchedule.js` calcula un RATIO, `serie[pago]/serie[emisión]`, y el BCRA actualiza la
UVA POR CER. Lo dice el propio `_fetch_uva_monthly` del repo, que existe desde hace meses
("UVA ajusta por inflación INDEC (CER)").

**Verificado, no deducido.** Contra los factores que la auditoría midió con la serie CER
real: el ratio UVA da **37,34× vs 37,44×** y **7,70× vs 7,72×** — 0,25 % de desvío, en dos
bonos con fechas de emisión separadas por tres años. Probé además desfasar la serie de 1 a
12 días por si había un lag: **cualquier desfasaje lo empeora**, así que el residuo es el
redondeo del informe y no un lag que corregir. El endpoint real, extremo a extremo, hoy
devuelve 3.816 filas y factor **37,57×** para TX26 donde la app publicaba 1,00×.

**Lo que se arregló además del dato:**

- **La caída era muda.** `_ensure_index_cached` hacía `return` pelado. Ahora loguea — una
  vez cada 15 min por índice, porque un aviso que sale mil veces es invisible (que es más
  o menos cómo esto sobrevivió meses). Se limita el aviso, **no** el reintento.
- **La tarjeta se contradecía sola:** arriba "Serie CER no disponible — flujos en nominal
  sin ajuste", doce líneas abajo "TIR real (sobre CER)… es lo que ganás POR ENCIMA de la
  inflación". El rótulo ahora depende de que el factor exista. Eso sigue valiendo aunque
  la fuente se vuelva a caer.
- **Una sola bajada de la serie:** `_fetch_uva_monthly` y el fetcher diario pegaban al
  mismo endpoint por separado.
- **`basis` viaja al frontend** y la tarjeta dice "(vía UVA)". Servir UVA en silencio bajo
  el rótulo "CER" sería cambiar un número inventado por otro número inventado mejor.

**Lo que queda de esta pieza:**

- **Un test viejo certificaba la caída.** `test_empty_cache_returns_empty_series_no_500`
  mockeaba sólo el CER y pasaba en verde *porque* la fuente está muerta. Ya está arreglado,
  pero vale como recordatorio de qué buscar en los otros.
- **La pregunta que sólo se contesta contra prod:** si `bond_indices_daily` tiene CER
  histórico guardado, el síntoma no es "factor 1,00" sino "factor congelado el día que
  murió la fuente". En la base de dev **no hay una sola fila** de ningún índice, lo que
  apunta a que nunca funcionó. Con filas en prod, el fallback igual gana (sólo entra
  cuando no hay CER), pero conviene saberlo.
- **Límite declarado:** la UVA existe desde 2016-03-31. El bono más viejo del catálogo es
  de 2020-08-04, así que hoy están todos cubiertos; un bono anterior no tendría base.
- **Lo demás de F5 sigue pendiente:** el cap de `/api/fx-rates` + el fallback mudo (D-7),
  punta venta vs. punta media, la política única de faltantes, y los 6 sitios que restan
  inflación en pesos a retornos en dólares.

---

## 5. Las tandas que siguen

### F3 — «Un solo calendario» *(3–5 días)*

Hay **tres calendarios corriendo a la vez**: ART (`utcnow() − 3h`), UTC (`utcnow()`) y hora local
del proceso (`date.today()`), más UTC y hora local del navegador en el frontend. Ninguno está mal
en sí; el problema es que **conviven dentro del mismo endpoint** y varios llevan comentarios que
afirman estar alineados con otro cuando no lo están.

- El cron sella cada snapshot con el día **UTC**, o sea un día ART adelante. Medido: el reporte
  anual de 2026 cierra con la rueda del 30 de diciembre. La rama que convierte a ART existe,
  está a 280 líneas y **nunca se ejecuta**.
- **`_ytd_delta` va en el MISMO commit** — es obligatorio, ver abajo.
- Los **27** `toISOString` restantes (hay 1 de 28 ya corregido, con el comentario que explica por qué).
- Los **tres comentarios** que afirman "los snapshots se estampan con fecha ART" y construyen
  lógica sobre esa premisa falsa. **Corregirlos es parte del fix.**
- Unificar "este mes": llevar el piso de antigüedad del borde a `computeReturnDelta`. Medido: el
  KPI del Dashboard publica **+35,24 %** donde el mes real fue **+2,90 %**.

> ⚠️ **Dependencia obligatoria (D-1).** El borde de apertura de `_ytd_delta` está mal, pero **hoy
> el error está tapado** por el bug de zona horaria: como la fila etiquetada `2026-01-01` es en
> realidad el cierre ART del 31/12, el borde sale bien por accidente. **Arreglar la zona horaria
> sin tocar `_ytd_delta` hace aparecer un bug que hoy nadie ve** (medido: publica −22,86 % sobre
> una cartera que ganó US$1.000).

### F4 — «Los guards que ya existen, en todos los lectores» — 🟡 3 de 6 hechos

Es la tanda de mejor relación resultado/esfuerzo: **el código de los guards ya está escrito**,
sólo no llegó a todos los lectores.

**Hechos y deployados:** el guard con 0/negativos, `_FINITE_BOUND` en `PositionIn`, validación de
broker existente en `positions`.

**Los tres que quedan, frenados A PROPÓSITO** — en los tres el código contradecía al plan o la
decisión es de producto. No los "arregles" sin decidirlos:

- **Edad máxima del precio en `read_last_prices`.** El código dice textual: *"get_prices rellena
  huecos con el last-known SIN límite de edad (para valuar la cartera está bien; para escribir el
  costo de un lote 'de HOY' no)"*. La regla de 48 h existe a propósito sólo para escribir costos.
  **A qué edad un precio viejo deja de ser mejor que el costo es decisión del founder.**
- **Guard de denominador peak en el hero del Dashboard.** El guard canónico de `evolution.js` es
  para *realized %*, no para retorno total, y el Dashboard no tiene el peak a mano. Es diseño
  nuevo sobre el número titular de la app.
- **Cota de plausibilidad en el P&L realizado.** Hoy no hay ninguna — medido **+188.566 %** en
  una sola fila. El umbral es decisión de producto y cambia números publicados.

**Y una validación que quedó asimétrica a propósito:** `/api/positions` rechaza un broker
inexistente, `/api/operations` **no**. Ahí el contrato lo tolera deliberadamente y hay un test
que lo fija (`test_currency_fallback_to_usd_if_broker_unknown`). Hay un test que congela la
asimetría para que quien la toque tenga que decidirla en vez de romperla de refilón.

### F5 — «Una sola cotización, una sola política de faltantes» *(4–6 días)*

- **El cap de `/api/fx-rates` Y el fallback mudo (los dos, dependencia D-7).** El endpoint limita
  por **filas, no por días**: el frontend pide 3.650 días, el backend responde
  `ORDER BY date DESC LIMIT 3650`, y la serie tiene ~5.685 filas desde 2011 → **la ventana
  arranca en 2016** y toda fecha anterior cae al **dólar de hoy sin avisar**. Medido: una venta
  de 2013 se dibuja **160× mal**. Poner `WHERE date >= ?` arregla el síntoma; **el fallback mudo
  es la causa** y sigue vivo para cualquier otro hueco.
- **La serie CER está caída.** El endpoint devuelve **404** hoy, mientras `/inflacion` y `/uva`
  del mismo host dan 200. Consecuencia: **todos los bonos CER ajustan con factor 1,00** cuando el
  real es 7,72× o 37,44× según el bono. Nadie loguea, nadie alerta. Hay que reponerla **y agregar
  detección**.
- Unificar **punta venta vs. punta media** entre `fx_rates_daily` y la valuación viva (explica un
  escalón sistemático de 0,74 %).
- Decidir y aplicar **una** política de faltantes: precio ausente, TC ausente, índice no publicado.
- **6 sitios restan inflación en pesos a retornos en dólares** — ninguno pasa la moneda. Y hay
  que pasar `moneda` a los benchmarks: hoy `vs_sp500_pct` **cambia de signo** con sólo tocar el
  selector de moneda.

### F6 — «Terminar las migraciones abiertas» *(1–2 semanas)*

**Acá es donde la causa raíz dominante deja de reproducirse.** Es la tanda que más cuesta y la
que más cambia el futuro del código.

- Migrar los **5 lectores** que faltan a `valuePositionLot` y **borrar** las matrices duplicadas.
- Las **5 superficies** que publican retorno sin pasar por `twr.py`.
- Los **6 lugares** que comparan contra benchmark sin pasar por `performance.py`.
- Persistir `cost_basis_consumed` en la venta.
- **Acá entra la divergencia de "Capital aportado"** que F1 destapó: unificar los dos lectores.

**Estado al cerrar: un solo motor por concepto.**

### F7 — «El modelo de datos» *(proyecto aparte, no es una tanda de fixes)*

Es diseño, no arreglos:

- **`operations.pnl_usd` es polimórfica**: guarda cuatro cosas distintas (resultado de venta,
  cash de dividendo, cash bruto de amortización, ganancia cambiaria) **en dos monedas**.
- **`_NOT_A_TRADE` es una lista de EXCLUSIÓN**, así que **todo `op_type` nuevo entra como "trade
  cerrado ganado" por omisión**. Ya pasó con `Interés PF`; `Renta`, `Cupón` y `Amortización`
  están en la misma situación, esperando. **Es la única causa que garantiza bugs futuros sin que
  nadie escriba una línea nueva mal.**
- Brokers linkeados por **nombre** (no por FK) en 6 tablas.
- Plazos fijos que no escriben `monthly_entries`.
- Objetivos sin aportes.

---

## 6. Las 72 divergencias sin veredicto

Los inputs están partidos por concepto en `audit/01_calculos/_grupos/<slug>.md`.

**Auditables ya (29):** bonos (13), CEDEAR (8), comisiones (8) — clases de activo o conceptos
independientes de las tandas.

**Conviene esperar (43):** snapshot (11), TIR (9), dividendos (9), caja (7), variación diaria (7).
Dependen de la cadena que las tandas modifican; auditarlas ahora produce veredictos para rehacer.

---

## 7. Lo que depende del founder, no del código

> **Actualización 2026-09-09:** medir el alcance ya no requiere `railway ssh` ni instalar nada.
> Hay un botón en el panel de admin — **"Alcance real de la auditoría" → "Medir alcance"** —
> que corre las 13 consultas y devuelve cada número como una pregunta en castellano con su
> veredicto (urgente / mirar / sin caso). Es `GET /api/admin/alcance-auditoria`, solo lectura y
> sólo agregados, con un guard que se niega a correr si el `.sql` deja de ser seguro. Railway no
> tiene consola web para un servicio (su dashboard sólo COPIA el comando SSH), así que el
> "hacerlo desde el navegador" es esto. El script `1a-medir-alcance.py` queda para copias locales
> y lee el MISMO `.sql` (antes tenía una copia embebida que ya había divergido).


1. **Medir el alcance en producción.** 13 consultas de SOLO LECTURA que devuelven únicamente
   agregados, y un script autocontenido que las corre: `audit/01_calculos/1a-medir-alcance.py`.
   Producción es **SQLite** → usá `1a-alcance-produccion-sqlite.sql`, **no** la versión Postgres
   (sus casts `::numeric` hacen fallar 8 de 13, incluida Q2).
   La más importante es **Q2**: cuenta las baselines de `capital_inicio` que **todavía
   sobreviven** — lo único que se seguía perdiendo sin recuperación posible.
2. **Decidir la limpieza de datos** (`audit/_fixes/F1-datos-a-limpiar.md`). Los snapshots se
   reconstruyen re-corriendo el job; **las baselines borradas no están en ninguna tabla y sólo
   salen de un backup.**
3. **Los tres ítems frenados de F4.**
4. **Las preguntas abiertas** que cada informe de 1B lista en su encabezado, sin contestar.

---

## 8. Método — lo que funcionó

- **Un commit por causa raíz**, revertible solo. Nada de un commit por tanda.
- **Cada fix trae un test que FALLA con el código viejo.** Verificalo de verdad: revertir el
  commit entero también revierte el test, y entonces no probaste nada. Revertí **sólo el archivo
  de código**, dejando el test nuevo.
- **Baseline de fallos ANTES de tocar nada** (`pytest tests/ -q | grep ^FAILED | sort`) y
  comparación al final. El objetivo es **cero fallos NUEVOS**, no cero fallos: hay 27
  preexistentes (news/events/importer/billing).
- **Antes de dar un fix por terminado, grep de todos los call sites del mismo patrón**, y decir
  cuáles arreglaste y cuáles no.
- **Un guard defensivo no es un parche.** Y si hay un comentario que justifica algo, **leelo
  antes de reportarlo como bug**: varias veces el código tenía razón y el plan no.
- **Antes de una validación que RECHAZA: censo de callers Y de contratos.** No alcanza con los
  callers de Python — puede haber un test que fija una tolerancia deliberada.

### Tres trampas concretas que costaron

- **Ojo con dónde insertás una función en `main.py`.** Un helper metido entre el decorador
  `@app.post(...)` y su función hace que FastAPI registre **el helper** como endpoint.
  `/api/positions` habría quedado roto en producción. **No lo cazó la suite**, lo cazó el test
  que se estaba escribiendo en ese momento.
- **No testees contra tu propio criterio: testeá contra el motor real.** Una función de
  ponderación escrita comparándola con "lo que yo creía correcto" estaba mal en el caso de
  cripto — 1450×, en la dirección contraria al bug que venía a arreglar. Apareció recién al
  ejecutar `compute_broker_value_usd` de verdad sobre una matriz de casos.
- **Un test viejo puede tener razón.** Un fix "obvio" al guard rompió dos tests que fijaban que
  una posición con cantidad 0 vale 0. Tenían razón: el guard recibe un **valor** (precio ×
  cantidad), no un precio, y no puede distinguir "precio absurdo" de "cantidad cero". El fix
  correcto iba en la **fuente del precio**, no en el guard.

---

## 9. Coordinación — importante

**El 2026-09-08 hubo dos sesiones tocando el mismo código.** La otra deployó a `main` los fixes
de snapshots mientras esta rama los tenía sin mergear. Se detectó al chequear antes de mezclar:
**mergear a ciegas habría pisado su solución con una peor.**

Antes de mergear cualquier cosa:

```bash
git fetch && git log --oneline <tu-base>..origin/main
```

Y si hay solapamiento, **comparen las dos soluciones antes de resolver el conflicto** — no
asumas que la tuya es la buena.

---

## 10. Estado del repo

- **`main`** — F1 completa + 3 de 6 de F4, deployado y verificado (27 fallos de test, los mismos
  que antes; frontend entero en verde). Ojo: el baseline de fallos **subió a 33** desde entonces
  (`advisor_plan`, `bond_conduit`, `cedear_usd_price` se sumaron a news/events/importer/billing).
  Medí el tuyo antes de tocar nada, no uses el número de este documento.
- **`fix/f2-que-no-mientan`** — F2 completa, **sin deployar**. 7 commits. Ver §4.
- `audit/mapa-sistema` — el mapa y los informes.
- `audit/trabajo-local-2026-09-07` — prompts e informes previos.
- `fix/f1-deje-de-escribir-mal` y `fix/f4-guards-en-todos-los-lectores` — **obsoletas**, ya
  mergeadas vía `fix/auditoria-calculo`. **No las uses de base.**
- `worktree-f1/` — worktree local con un fixture de prueba (`backend/scripts/seed_f1.py`,
  usuario `f1@rendi.test`). Sirve para probar F1 a mano.

**Deploy = push a `origin/main`.** No hay CI: Railway observa esa rama. Pushear una rama
cualquiera no deploya.
