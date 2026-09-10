# Handoff — auditoría de cálculo de Rendi y las tandas de fix que quedan

**Base:** `origin/main` actual. Trabajá siempre sobre eso, **no** sobre el commit del mapeo — el
código se movió y la auditoría original se hizo sobre `b74f450f`, que ya no es producción.

---

## 0. Las 7 tandas de un vistazo — y la que sigue

Los 222 hallazgos de la auditoría se ejecutan en siete tandas. **No están ordenadas por
gravedad**, sino por lo que cada una habilita: primero se frena lo que corrompe datos nuevos,
después lo que se publica mal, y al final se unifican los motores para que la causa raíz deje
de reproducirse.

> ### ➡️ La próxima es **F4**, y arranca con **tres decisiones tuyas** (§7).
>
> F3 quedó **hecha y ya deployada** (ver la nota en §5-F3). Si querés entender qué cambió, antes de
> pushear, leé «Lo que se ve el día del deploy» en §5-F3: hay **un efecto medido** que
> conviene saber de antemano, y **una decisión tuya** sobre la serie histórica.

| tanda | qué resuelve, en una línea | estado |
|---|---|---|
| **F1** | Que la app **deje de escribir mal**. Un número mal mostrado se arregla el día que se toca el código; uno mal **escrito** queda para siempre. | ✅ deployada |
| **F2** | Que **la inteligencia artificial y las pantallas no mientan**: cuatro números que se publicaban mal hacia afuera. | ✅ deployada y **cerrada** (§4) |
| **F3** | **Un solo calendario.** Convivían tres relojes distintos dentro del mismo endpoint. | ✅ **DEPLOYADA** (llegó a `main` el 2026-09-09 con los pushes de la limpieza; ver §5-F3) |
| **F4** | Los guards que **ya están escritos** pero no llegaron a todos los lectores. | ➡️ **LA QUE SIGUE.** 3 de 6; los 3 que faltan **te esperan a vos**, no al código |
| **F5** | **Una sola cotización y una sola política de faltantes.** | 🟡 lo más grave ✅ deployado (el CER); el resto pendiente, 4 a 6 días |
| **F6** | **Terminar las migraciones abiertas.** Un solo motor por concepto. | ⬜ pendiente, 1 a 2 semanas |
| **F7** | **El modelo de datos.** Es diseño, no arreglos. | ⬜ proyecto aparte |

### Por qué F4 ahora, y por qué te toca a vos

F4 es la de mejor relación entre resultado y esfuerzo, porque el código ya está escrito y sólo
falta llevarlo a los demás lectores. Pero **los tres puntos que le quedan están frenados a
propósito**: en los tres la decisión es de producto, no técnica. A qué edad un precio viejo deja
de servir, qué guard usar sobre el número titular del Dashboard, y desde qué porcentaje un
resultado deja de ser plausible. Nadie debería elegir eso por vos. Hasta que las decidas, F4 no
avanza.

F3 se hizo primero justamente porque no dependía de ninguna decisión tuya, y porque desbloquea
a las que siguen: casi todo lo que mide rendimiento arranca preguntando qué día es hoy.

### Lo que corrió en paralelo y NO es una tanda

El 2026-09-09 se trabajó una línea aparte sobre **cripto**, nacida de un reporte de usuario y no
de la auditoría. Tiene su propio plan y sus propias mediciones en producción:
`audit/08_cripto/PLAN.md`. Tres arreglos ya están deployados; lo que queda está priorizado ahí.

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

## 3. F1 — ✅ HECHA Y DEPLOYADA

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

## 4. F2 — ✅ HECHA, DEPLOYADA Y CERRADA (2026-09-09)

**Estado final:** deployada en `529ee423` junto con el CER de F5. La rama
`fix/f2-que-no-mientan` está a cero commits de diferencia con `origin/main` en
las dos direcciones: no queda nada sin mergear.

**Y lo que quedaba abierto ya se cerró**, en este orden:

1. **Q7 se midió.** Era lo único de F2 que dependía de producción y no se podía
   contestar desde el repo. El botón de alcance del panel de admin lo contestó:
   **1 usuario, 2 filas, $121.095** en pesos que las pantallas publicaban como
   US$121.095.
2. **Y se reparó** (`0f1978ba`, otra sesión): sella el MEP del día del cobro y
   **después** corre el recálculo que reescribe `monthly_entries`, porque sin ese
   segundo paso el sello queda y el Dashboard sigue mostrando el número viejo.
   Idempotente, en dos pasos en el panel, y sin MEP para la fecha la fila se
   lista y no se toca.
3. **Verificado**: la medición del 2026-09-09 devuelve `monto pesos leido como
   usd: 0` sobre las mismas 2 filas. El hallazgo está cerrado hacia atrás y hacia
   adelante.

Lo que sigue abierto **no es F2**: `Interés PF` en los win rates es F7, el
Wrapped sobre la cadena contable es F6, y DIV-087 (convertir en el endpoint y no
en cada lector) es un hallazgo aparte que hay que hacer para Cupón, Amortización
e Interés PF juntos porque cambia números en pantalla.

---

### Cómo se hizo (queda por el método)

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

## 4-ter. Reparaciones sobre lo ya escrito — estado, y un error de F1 que destapó

**Hechas (botones en el panel de admin, con "ver qué cambiaría" antes de "aplicar"):**

- **Interés PF leído como dólares** — ✅ aplicada en prod el 2026-09-09: 1 fila, 1 usuario,
  $121.095 → US$ 78,88. El medidor la da por cerrada (0 / Sin caso).
- **Caja reconciliada al 1.415 fijo** — ✅ aplicada en prod el 2026-09-09: 42 meses, 40 usuarios,
  capital aportado −US$ 62.115 (el 8 % de los US$ 779.200 medidos: 1.415 vs el dólar real de
  junio–septiembre 2026, 1.508–1.548). Queda 1 mes sin lote de importación con qué fecharlo, sin
  tocar. La segunda pasada del preview da 0: idempotente confirmado en prod.

**⚠️ El error de F1 que destapó el preview.** La primera versión de la reparación dolarizaba al
dólar del **mes anotado**, igual que dejó F1 en `reconcile-cash` (`9b03ebec`). El preview mostró
`2021-05 · retiros US$ 84 → 781`: 9×. La causa: reconcile-cash anota la diferencia en el **mes más
viejo del broker** ("historia pre-CSV"), pero los pesos son de **hoy** — es la diferencia entre lo
que dice el broker hoy y lo que calculó la app hoy. En 2021 esa misma plata eran 9 veces menos
pesos. El razonamiento del comentario de F1 ("el ajuste es plata anterior al CSV, va al dólar de
ese mes") confundía unidades. **Corregido hacia adelante**: reconcile-cash dolariza al dólar de
hoy. El botón Cash no cambia: ahí el usuario fecha el movimiento.

Para las 43 filas viejas, la fecha de reconciliación no se guardó (ni `monthly_entries` tiene
timestamps ni reconcile-cash deja registro). Se reconstruye del **lote de importación confirmado**
de ese usuario+broker, nunca anterior al nacimiento de la función (`def52782`, 2026-05-13): la
reconciliación es el paso siguiente del importador, su único caller. Sin lote → se lista y no se
toca.

**Método que vale la pena copiar:** el paso "ver qué cambiaría" no es cortesía. Cazó un fix mal
diseñado antes de tocar un solo dato de producción.

**Siguen pendientes:** re-correr las fotos pegadas al costo (19 usuarios grandes / 411 en total),
y las 868 posiciones con costo en pesos en cuentas en dólares de verdad (20 usuarios, 9 brokers;
sin TC conocido — hay que mirar broker por broker). Y "conversiones fantasma" sigue sin un número
confiable: hay un desglose por broker en el medidor para entender qué guarda cada uno antes de
volver a intentar.

---

## 5. Las tandas que siguen, en detalle

### F3 — «Un solo calendario» — ✅ **HECHA Y DEPLOYADA** (2026-09-09)

> **Nota de coordinación (2026-09-10):** los commits de F3 se hicieron sobre `fix/f2-que-no-mientan`
> —la misma rama y el mismo árbol que usaba la sesión de la limpieza— y salieron a `main` con uno de
> los pushes de esa sesión el 2026-09-09, sin que ninguna de las dos lo supiera. `fb63ef1a` es
> ancestro de `origin/main`. El efecto medido de abajo (una rueda perdida, la historia corrida un
> día, el YTD con una rueda de más) **ya ocurrió**. Dos sesiones sobre un mismo árbol es lo que
> hizo posible esto; conviene no repetirlo.

7 commits sobre `origin/main` (`ab8ae9a5` … `f9bc43db`), rama `fix/f2-que-no-mientan`.
Suite al terminar: **backend 4.132 en verde / 0 rojos · frontend 1.528 en verde / 0 rojos**,
contra un baseline medido esa misma tarde de **0 y 0**. Build del frontend OK.

Convivían **tres calendarios**: ART (`utcnow() − 3h`), UTC (`utcnow()`) y hora local del proceso
(`date.today()`), más UTC y hora local del navegador en el frontend. Ninguno estaba mal en sí; el
problema era que convivían dentro del mismo endpoint, y que varios llevaban comentarios
afirmando estar alineados con otro cuando no lo estaban.

**El "hoy" de Rendi es el día calendario argentino.** Esa decisión ya estaba tomada de hecho en
el producto (el cron corre 02:59 UTC *porque* es medianoche de acá); lo que faltaba era que
existiera en un solo lugar. Ahora vive en `backend/fechas.py` y en `frontend/src/utils/fecha.js`.

| # | qué se arregló | evidencia |
|---|---|---|
| 1 | **La hora argentina estaba escrita nueve veces**, copiada a mano en nueve archivos. Ahora `backend/fechas.py` y nada más | refactor sin cambio de comportamiento |
| 2 | **El cron archivaba el cierre del viernes como sábado.** La conversión existía desde 2026-05-31 y **nunca corrió**: el runner pasa fecha no-nula, así que la rama era inalcanzable | MEDIDO |
| 3 | **El YTD restaba dos veces el aporte del 1 de enero.** Sobre una cartera que ganó US$ 1.000 publicaba **−US$ 4.000 / −22,86 %** | MEDIDO |
| 4 | **"Este mes" del Dashboard medía desde 79 días antes**: +35,24 % / US$ 3.700 donde el mes real fue +2,90 % / US$ 400 | MEDIDO |
| 5 | **Cargar una operación a las 22:00 la fechaba mañana** — 27 sitios del frontend | ESTRUCTURAL |
| 6 | **El mes cerraba tres horas antes de terminar** (`is_period_current` en UTC, con el comentario que afirmaba lo contrario) | MEDIDO |
| 7 | **El guard de fecha futura aceptaba el futuro** tres horas por día — el guard que existe por los 25 cupones de AL35 de 2027 | ESTRUCTURAL |

**Dos hallazgos que se cerraron solos**, sin trabajo propio:

- **H-11** (la foto intradía del browser no se escribía nunca). El cron ocupaba la fecha de hoy
  con `source='cron'` y el guard de `POST /api/snapshots` la protegía. Al fechar el cron un día
  atrás, la fecha de hoy queda libre: **vuelve el punto de "hoy" en la curva del Dashboard** para
  todos, y el cron de la noche lo pisa con el cierre real, como estaba diseñado.
- **H-4** (los tabs de `/reportes` con calendarios distintos). El tab "Hoy" era uno de los 27
  `toISOString`; al migrarlo quedó alineado con Semana, Mes y Año.

**Los tres comentarios falsos** (`advisor_brief`, `advisor_alerts`, el hero del libro) que
afirmaban "los snapshots se estampan con fecha ART" **no se corrigieron: se volvieron ciertos**.
Quedan anotados con desde cuándo, para que el próximo lector no crea que siempre lo fueron.

#### Lo que se ve el día del deploy — MEDIDO, no deducido

Simulado corriendo el cron real cinco noches seguidas, tres con el código viejo y dos con el
nuevo (`audit/_fixes/F3-sim-deploy.py` — se corre desde `backend/`):

```
  archivada en   valor    es en realidad el cierre de…
  ──────────────────────────────────────────────────────────
  2026-09-03      100    ⚠️  corrida un día (es el cierre del 2026-09-02)
  2026-09-04      110    ⚠️  corrida un día (es el cierre del 2026-09-03)
  2026-09-05      130    ✅ correcta          ← primera noche con el código nuevo
  2026-09-06      140    ✅ correcta

  Cierres que NO quedaron en la serie: 2026-09-04
```

Tres cosas, en orden de importancia:

1. **Se pierde exactamente UNA rueda: la del día anterior al deploy.** La primera corrida nueva
   escribe sobre la fecha que la corrida de la noche anterior ya había ocupado, y el UPSERT la
   pisa. Es un punto en la curva, una sola vez, y no se puede evitar sin re-etiquetar la serie.
2. **La historia vieja queda corrida un día.** F3 no repara datos ya escritos, igual que F1.
   La serie queda partida en dos convenciones en la fecha del deploy.
3. **De acá en adelante todo queda bien fechado**, y con eso se acomodan los bordes de todos los
   períodos: el reporte de septiembre deja de arrancar en el cierre del 30 de agosto y el anual
   deja de cerrar con la rueda del 30 de diciembre.

#### ⚠️ Y una consecuencia que sólo apareció al auditar el propio fix

**Mientras la historia siga corrida, el KPI «YTD» de Métricas queda con una rueda de más — y
hoy, sin deployar, está exacto.** Medido corriendo `main._ytd_delta` real sobre la misma
historia en las dos ramas:

| | qué publica el YTD 2026 |
|---|---|
| `origin/main` (hoy) | **US$ 1.000** — exacto |
| con F3 | **US$ 1.100** — el borde cae en el cierre del 30/12 en vez del 31/12 |

El informe 1B lo tenía escrito en la letra chica (*"arreglar H-2 con H-1 vivo: se pierde una
rueda más, pero el signo no se invierte"*) y aplica igual acá, porque el fix del cron sólo
alcanza a las filas NUEVAS: las de diciembre de 2025 siguen con la etiqueta corrida.

**Por qué se deploya igual, y no es un empate:**

- Hoy el YTD acierta **por accidente**, y ese accidente depende de que el cron siga roto. El
  1 de enero de 2027 la fila `2027-01-01` la escribe el cron nuevo —con el aporte del 1/1
  adentro— y sin este fix el KPI publica **−22,86 %, con el signo invertido**. No arreglarlo
  es dejar armada una bomba con fecha.
- El desvío es de **una rueda de mercado**, no de signo, y se apaga solo: en cuanto la fila
  `2026-12-31` la escriba el cron nuevo, el YTD 2027 arranca exacto.
- **El fix hace que Métricas y Reportes coincidan.** Hoy divergen: Reportes ya usaba el
  día-anterior y arrastraba esa rueda, Métricas no. Post-deploy los dos miden igual — que es
  el punto de la tanda.

Re-etiquetar la historia lo cierra de inmediato. Es el argumento más fuerte a favor de hacerlo.

#### La decisión: ✅ TOMADA — no se re-etiqueta (2026-09-09)

**El dueño decidió dejar la historia como está y esperar a enero.** No hace falta volver a
preguntárselo. Consecuencia aceptada, con los ojos abiertos: el KPI «YTD» de Métricas publica
una rueda de más hasta que la fila `2026-12-31` la escriba el cron nuevo, y ahí se acomoda solo.
Los reportes de meses y años ANTERIORES al deploy quedan con esa misma rueda para siempre.

⚠️ Y ojo, porque es la trampa de este punto: **el botón para re-etiquetar NO EXISTE.** No está
en el panel de admin ni en ningún lado — habría que construirlo. Si algún día se retoma, es
trabajo nuevo (con su "ver qué cambiaría" antes de "aplicar", como los otros), no apretar algo
que ya está.

<details>
<summary>El análisis que llevó a esa decisión, por si se retoma</summary>

**¿Se re-etiqueta la serie histórica de `snapshots`, restándole un día a todo lo anterior al
deploy?**

| | a favor | en contra |
|---|---|---|
| **Re-etiquetar** | la serie queda coherente de punta a punta; los reportes de meses y años pasados se corrigen solos | mueve **toda** la historia de **todos** los usuarios; es la operación más grande que se le haya hecho a esa tabla |
| **No tocar nada** | riesgo cero, y de acá en adelante todo está bien | los reportes de períodos pasados siguen con la rueda corrida, para siempre |

No hace falta decidirlo para deployar. Se puede deployar hoy y re-etiquetar después: la
reparación es la misma con un día o con un año de por medio.

</details>

#### Lo que F3 NO tocó, y por qué

- **El contador de cuota de IA** (`_record_tool_usage`) se dejó en UTC **a propósito**, con el
  motivo escrito en el código: no es un día calendario del usuario, es la ventana de una cuota, y
  su lector (`ai/quota.py`) cuenta con `date.today()`. Mover uno solo desalinea escritura y
  lectura y le da a alguien un día de más o de menos de cuota. **Los dos se mueven juntos y
  medido antes, o no se mueve ninguno.**
- **Los 38 `date.today()` restantes** (cuota de IA, builders de la IA, eventos). Ninguno persiste
  una fecha de negocio. Son H-15 y quedan para cuando se toque cada zona.
- **H-7** (el rollover mensual: UTC en el backend, hora local en el frontend), **H-9** (las
  semanas anidadas que no cubren el mes), **H-13** (las seis tolerancias distintas de arrastre),
  **H-14** (`_market_open_now` sin feriados ni DST de EE.UU.), **H-16** y **H-17**. Ninguno es
  "dos relojes en el mismo endpoint": son piezas propias, y cada una necesita su decisión.

#### Lo que encontró auditar la propia tanda

Antes de deployar se auditó F3 contra sí misma. Cuatro cosas, y **dos eran errores míos**:

1. **Dos relojes que quedaron divergiendo por mi propio arreglo.** Al pasar
   `is_period_current` al día argentino, sus dos gemelos de `reporting/timeline.py`
   (`_months_back` y `wrpt_is_current_check`) siguieron en `date.today()`. Es exactamente la
   causa raíz que la tanda persigue, cometida dentro de la tanda. ✅ `abfb1e31`.
2. **El desvío del YTD** de acá arriba, que no estaba medido cuando se reportó la tanda.
3. **Un helper que escribí y no usa nadie** (`hoyMasDias`). ✅ `309ed995`.
4. **Trabajo de otra sesión que se coló en un commit mío** — ver §9.

Y la comparación de suites se rehízo en **worktrees limpios**, porque el árbol principal tenía
trabajo en curso de otra sesión: `origin/main` da **4.113 / 0** y F3 **4.132 / 0**, o sea +19,
que son exactamente los tests nuevos. **Cero regresiones.**

#### Los guards que quedaron, y qué leen

Cinco guards nuevos, y **cuatro de los cinco leen CÓDIGO, no números** — porque lo que hay que
impedir es que las copias vuelvan, y un test de comportamiento no las ve:

| guard | impide que… |
|---|---|
| `test_un_solo_calendario.py` | algún módulo vuelva a restar las 3 horas a mano |
| ídem | `fechas.py` importe algo del repo y deje de poder usarse desde cualquier lado |
| ídem | un guard de fecha futura decida con un reloj que no es el argentino |
| `test_f3_cron_art_y_borde_anual.py` | aparezca una quinta copia del borde de apertura |
| `bordeFresco.test.js` | el frontend y el backend usen números distintos — **lee `builder.py`** |
| `fecha.test.js` | vuelva el patrón UTC, **y** que un barrido futuro se lleve puestas las marcas de tiempo, que en UTC están bien |

Los cinco se verificaron poniendo el bug de vuelta a mano.

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

### F5 — «Una sola cotización, una sola política de faltantes» — 🟡 el CER ✅ deployado (§4-bis), el resto pendiente *(4–6 días)*

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

### F6 — «Terminar las migraciones abiertas» — ⬜ pendiente *(1–2 semanas)*

**Acá es donde la causa raíz dominante deja de reproducirse.** Es la tanda que más cuesta y la
que más cambia el futuro del código.

- Migrar los **5 lectores** que faltan a `valuePositionLot` y **borrar** las matrices duplicadas.
- Las **5 superficies** que publican retorno sin pasar por `twr.py`.
- Los **6 lugares** que comparan contra benchmark sin pasar por `performance.py`.
- Persistir `cost_basis_consumed` en la venta.
- **Acá entra la divergencia de "Capital aportado"** que F1 destapó: unificar los dos lectores.

**Estado al cerrar: un solo motor por concepto.**

### F7 — «El modelo de datos» — ⬜ proyecto aparte, no es una tanda de fixes

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

El 2026-09-08 hubo dos sesiones tocando el mismo código. La otra deployó a `main` los fixes de
snapshots mientras esta rama los tenía sin mergear. Se detectó al chequear antes de mezclar:
mergear a ciegas habría pisado su solución con una peor.

**Antes de mergear cualquier cosa:**

```
git fetch && git log --oneline <tu-base>..origin/main
```

Y si hay solapamiento, comparen las dos soluciones antes de resolver el conflicto — no asumas
que la tuya es la buena.

### ⚠️ Y volvió a pasar el 2026-09-09, de otra forma: `git add -A` se lleva lo ajeno

Mientras corría F3, otra sesión editaba `backend/main.py` **en la misma carpeta**. Un
`git add -A backend/` se llevó su fix de autorización de las alertas adentro de un commit
cuyo mensaje hablaba de fechas — y **sin su test**, que estaba en otro archivo que no entró.
Se detectó auditando el diff propio línea por línea, se revirtió (`6eaa6980`) y su trabajo
volvió al árbol donde lo había dejado.

Tres reglas que salen de eso:

1. **`git add -A <dir>` no sirve cuando hay otra sesión viva en la carpeta.** Agregá archivo
   por archivo, o revisá `git diff --cached` antes de commitear.
2. **Leé tu propio diff buscando lo que NO escribiste.** El filtro que lo encontró fue mirar
   las líneas de código que no mencionaban nada del tema de la tanda.
3. **No midas la suite en un árbol con trabajo ajeno en curso.** Dos tests daban rojo y
   parecían regresiones mías; eran de un cambio a medio hacer de la otra sesión
   (`_borrar_en_chunks` con un parámetro nuevo y su test sin actualizar). La medición válida
   se hizo en dos worktrees limpios, uno por rama.

## 10. Estado del repo

- **`main`** — F1 completa, F2 completa, 3 de 6 de F4 y el CER de F5. Todo deployado.
- **`fix/f2-que-no-mientan`** — el nombre quedó viejo: hoy lleva **F3 entera, sin deployar**.
  7 commits sobre `origin/main` (`ab8ae9a5` … `f9bc43db`), y `origin/main` no se movió mientras
  tanto (verificado al empezar y al terminar). **Deployar F3 = pushear esta rama a `origin/main`**
  — pero antes leé «Lo que se ve el día del deploy» en §5-F3.
- **Baseline de la suite el 2026-09-09 a la tarde: 0 fallos** — backend 4.113 en verde, frontend
  1.510 en verde, medido en esta misma carpeta (con `backend/.env` presente) justo antes de tocar
  nada. Al cerrar F3: **backend 4.132 / 0 · frontend 1.528 / 0**, y las diferencias son
  exactamente los tests nuevos.
  ⚠️ Ojo con el handoff anterior, que anotaba **6 fallos de `test_advisor_plan`** como baseline
  "de entorno". Con el `.env` de esta carpeta **no aparecen**. O sea que ni el 6 ni el 0 son "el"
  número: **el conteo de la suite completa no sirve como métrica** — depende del entorno y hasta
  de cuántos usuarios crea un test. La comparación válida es archivo por archivo, aislado, y
  **medí el tuyo antes de tocar nada**.
- `audit/mapa-sistema` — el mapa y los informes.
- `audit/trabajo-local-2026-09-07` — prompts e informes previos.
- `fix/f1-deje-de-escribir-mal` y `fix/f4-guards-en-todos-los-lectores` — **obsoletas**, ya
  mergeadas vía `fix/auditoria-calculo`. **No las uses de base.**
- `worktree-f1/` — worktree local con un fixture de prueba (`backend/scripts/seed_f1.py`,
  usuario `f1@rendi.test`). Sirve para probar F1 a mano.

**Deploy = push a `origin/main`.** No hay CI: Railway observa esa rama. Pushear una rama
cualquiera no deploya.

### Si vas a deployar F3

En orden, y **el primer paso no se saltea**:

1. `git fetch && git log --oneline origin/main..HEAD` y al revés — que no haya entrado nada de
   otra sesión (§9). El 2026-09-08 hubo dos sesiones tocando el mismo código.
2. Correr las dos suites en esta carpeta. Tienen que dar **4.132 / 0** y **1.528 / 0**.
3. Leer «Lo que se ve el día del deploy» en §5-F3 — hay un efecto medido y visible.
4. Pushear.
5. **A la mañana siguiente**, mirar un usuario con snapshots: la fila del cierre de anoche tiene
   que estar fechada **ayer**, no hoy. Es la prueba de comportamiento de que el cron cambió.
