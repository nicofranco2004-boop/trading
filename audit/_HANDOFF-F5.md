# Handoff — la auditoría de cálculo de Rendi, y por qué la próxima es F5

> **Si sos la sesión que arranca: leé esto entero antes de tocar código.** Es autocontenido.
> No hace falta abrir el mapa de 3,4 MB ni los 14 informes de detalle salvo que el trabajo
> te lleve ahí, y en ese caso este documento te dice a cuál.

---

## 0 · Lo primero, en treinta segundos

Rendi tiene una auditoría de cálculo con **222 hallazgos**, que se ejecuta en **siete tandas**
(F1 a F7). **F1, F2, F3 y F4 están hechas y deployadas.**

➡️ **La que sigue es F5, «una sola cotización, una sola política de faltantes».**

F5 tiene la misma particularidad que tuvo F4, y conviene saberla antes de empezar: **su punto
más grande no es programar, es decidir.** "Una sola política de faltantes" —qué hace la app
cuando no hay precio, no hay tipo de cambio o no se publicó el índice— es una decisión de
producto, y hasta que esté tomada cualquier código que escribas es una apuesta. La §6 te dice
qué preguntar y con qué datos.

⭐ **Y lo más importante que dejó F4, que no está en ningún informe: auditar la tanda contra sí
misma encontró 12 defectos propios que la suite en verde no mostraba.** Dos estaban en commits
ya ofrecidos para deploy; uno aplastaba un 50 % a 0,03 % en la curva del Dashboard. **Reservá
tiempo para auditarte al final. No es opcional y no lo cubre la suite.** La §9 explica cómo.

**Antes de tocar nada:**

```bash
cd /Users/nicolaspussetto/Documents/trading
git fetch && git log --oneline HEAD..origin/main      # ¿entró algo de otra sesión?
git status --short                                     # ¿hay trabajo ajeno sin commitear?
cd backend && python3 -m pytest tests/ -q | tail -1    # tu baseline, medido por vos
cd ../frontend && npm test -- --run 2>&1 | grep "Tests"
```

⚠️ **Si `git status` muestra archivos modificados que vos no tocaste, hay otra sesión viva en
esta carpeta.** Leé la §10 antes de seguir: no es un detalle, ya rompió cosas dos veces.

---

## 1 · Qué es Rendi

App argentina de seguimiento y análisis de carteras de inversión multi-broker: tenencias,
operaciones, ganancia realizada y no realizada, rendimientos (incluido ajustado por inflación),
objetivos y comparaciones contra índices. Tiene planes de suscripción, período de prueba y un
plan para asesores financieros (un asesor ve el libro de todos sus clientes).

**Dos cosas del dominio explican la mitad de los bugs. Si no las tenés presentes, vas a
diagnosticar mal:**

1. **Argentina tiene varios dólares** (blue, MEP, CCL, cripto, oficial) con diferencias
   materiales entre ellos. Elegir mal la cotización, o usar la de hoy para una operación de
   2021, desvía plata de verdad.
2. **Un mismo activo se puede tener en pesos y en dólares en el mismo broker**, y hay
   sub-brokers (`Cocos · USD`) que son la pata dólar de un broker argentino. **La moneda del
   lote y la moneda de la cuenta no son lo mismo**, y confundirlas es la causa raíz de varios
   de los errores más grandes que se encontraron.

---

## 2 · Qué es la auditoría, y cuál fue el veredicto

Antes existía un **mapa del sistema** (`audit/00-mapa-sistema.md`, 28.586 líneas) que
documentaba *qué hay*. La auditoría responde *qué está mal*.

Se hizo en dos tandas, con agentes en paralelo, cada uno sobre una copia limpia de solo lectura
del commit que estaba en producción (`b74f450f`):

| tanda | qué cubrió | resultado |
|---|---|---|
| **1A** | 94 de las 166 "implementaciones divergentes" — casos donde el mismo concepto se calcula de más de una forma. Se eligió la cadena del número que el usuario ve | **85 de 94 dan números realmente distintos.** Sólo 9 eran cosméticas |
| **1B** | 6 temas transversales: decimales, monedas y cotizaciones, fechas y zonas horarias, inflación, benchmarks, casos borde | **128 hallazgos** |

**Total: 222 hallazgos con veredicto.** De esos, **50 están MEDIDOS ejecutando código** (con la
traza pegada en el informe); el resto es lectura verificada con `grep`. La distinción está
hallazgo por hallazgo en `audit/01_calculos/1a-evidencia.md`, e importa.

### El veredicto general, sin suavizar

**Los motores centrales están bien.** `backend/twr.py`, `backend/performance.py` y
`frontend/src/utils/valuation.js::valuePositionLot` son correctos y están documentados con las
mediciones que los justifican.

**El problema es que el producto no los usa.** Cinco superficies publican rendimiento sin pasar
por el motor de rendimiento; seis comparan contra un índice sin pasar por el de índices; el
valuador canónico admite en su propio docstring que todavía no lo consume nadie.

No es un sistema mal pensado. Es **un sistema bien pensado cuyas correcciones nunca terminaron
de propagarse** — por eso se ordena en tandas y no es una reescritura.

---

## 3 · Las 12 causas raíz — y la que domina todo

| # | causa | hallazgos (≥) | esfuerzo |
|---|---|---:|---|
| **C1** | **El fix existe pero no se propagó a todos los call sites** | **28** | medio |
| C2 | Copiar y pegar sin un origen designado | 21 | grande |
| C3 | Falta una capa compartida: no hay dónde poner el cálculo | 17 | grande |
| **C7** | **Guard o cota ausente en un lector** ← **esto es F4** | **17** | **chico** |
| C5 | Migración empezada y nunca terminada | 14 | grande |
| C8 | Cada capa decide su propia política de faltantes | 10 | medio |
| C4 | Port a mano que quedó atrás del original | 9 | medio |
| C10 | Modelo de datos incompleto (tipo, moneda, FK) | 8 | grande |
| C6 | El frontend hace lo que el backend no sabe hacer | 7 | medio |
| C11 | Decisión deliberada o parche documentado (no son bugs) | 6 | ninguno |
| C9 | Zona horaria y calendario | 3+ | medio |
| C12 | Documentación que afirma algo que el código no hace | 2+ | chico |

> Los conteos son **cota inferior** (105 filas tienen texto libre que no mapea limpio). Lo que
> sostiene el plan es **el orden relativo**, que es robusto, no el dígito exacto.

### C1 es la causa dominante, y no es descuido

**Es la forma que toma un fix correcto en este código.** El patrón se repite idéntico: alguien
diagnostica bien, arregla bien, deja el comentario que lo explica — y el arreglo llega a **un**
call site de varios. Ejemplos verificados:

- El fix de `toISOString` estaba en **1 de 28** lugares, con el comentario de auditoría al lado.
- El fix del tipo de cambio histórico llegó a **2 de 3** motores de venta.
- Las series diarias de índices se bajaron para los 3 del selector **en dólares**; los 2 **en
  pesos** quedaron con ancla mensual.
- `register_trade` rechaza un precio de más de 48 h; `read_last_prices` —que alimenta el
  snapshot nocturno, el Dashboard y el libro del asesor— **no mira la edad**. ← *esto es F4*
- `POST /api/monthly` valida que el broker exista; `POST /api/positions` y `POST /api/operations`
  no. ← *esto también es F4*

**Las dos reglas permanentes de `CLAUDE.md` salieron de acá. Respetalas o vas a generar el
hallazgo 223.**

### C12 es chica en conteo y grande en consecuencia

Hay comentarios que **afirman premisas falsas** y sobre los que después se construyó lógica.
Tres archivos del producto asesor decían textualmente *"los snapshots se estampan con fecha
ART"* mientras el cron los estampaba en UTC. Otro decía *"mismo número a propósito: si se
separan, uno de los dos está mal"* — y se habían separado. **Mientras esos comentarios sigan
ahí, el próximo que lea el código repite el error.** (F3 cerró estos dos casos.)

---

## 4 · Las 7 tandas de un vistazo

**No están ordenadas por gravedad**, sino por lo que cada una habilita: primero se frena lo que
corrompe datos nuevos, después lo que se publica mal, y al final se unifican los motores para
que la causa raíz deje de reproducirse.

| tanda | qué resuelve, en una línea | estado |
|---|---|---|
| **F1** | Que la app **deje de escribir mal**. Un número mal mostrado se arregla el día que se toca el código; uno mal **escrito** queda para siempre | ✅ **hecha y deployada** |
| **F2** | Que **la IA y las pantallas no mientan**: cuatro números que se publicaban mal hacia afuera | ✅ **hecha, deployada y cerrada** |
| **F3** | **Un solo calendario.** Convivían tres relojes dentro del mismo endpoint | ✅ **hecha y deployada** (2026-09-09) |
| **F4** | Los guards que **ya están escritos** pero no llegaron a todos los lectores | ✅ **hecha y deployada** (2026-09-10), 6 de 6 |
| **F5** | **Una sola cotización y una sola política de faltantes** | ➡️ **LA QUE SIGUE** — el CER ✅ ya deployado; el resto, 4 a 6 días, y **arranca con una decisión** |
| **F6** | **Terminar las migraciones abiertas.** Un solo motor por concepto | ⬜ pendiente, 1 a 2 semanas |
| **F7** | **El modelo de datos.** Es diseño, no arreglos | ⬜ proyecto aparte |

---

## 5 · Las cuatro que ya están hechas

### F1 ✅ — «que deje de escribir mal»

**Criterio:** sólo lo que corrompe datos nuevos. 13 commits, cada uno con un test que falla
contra el código viejo.

| qué estaba mal | efecto medido |
|---|---|
| El cron de snapshots contaba un costo en pesos como dólares en cuentas USD | **×1.450** |
| El guard de cobertura del 95 % ponderaba por la moneda del broker, no del lote | dejaba ciego al guard: tapaba faltantes de precio reales |
| Una conversión de moneda **creaba capital de la nada** | US$ 444.342 salieron y US$ 217.932 volvieron sin que ningún broker los acreditara. 41 usuarios, 12 con capital aportado negativo |
| `reconcile-cash` dividía por un dólar fijo (1415) | +7,3 % de capital fantasma, permanente |
| El recalc borraba el `capital_inicio` que el usuario tipeó | **irrecuperable** |
| La venta sellaba un tipo de cambio distinto del que usó para dividir la ganancia | fila con `fx_to_usd = 1.0` y P&L dividido por ~1.400 |
| `SellModal` no recibía las cotizaciones históricas en mobile | una venta retroactiva desde el celular quedaba al dólar de hoy |
| Una operación con fecha futura congelaba el calendario mensual | el usuario se quedaba sin fila del mes en curso hasta 2030 |
| El guard antidistorsión aceptaba valor negativo y NaN | la posición se publicaba valiendo **menos que nada** |
| `PositionIn` no acotaba sus montos | `invested = 1e308` entraba y llegaba a `capital_final` |
| Se podía cargar una posición contra un broker inexistente | fila huérfana → pérdida fantasma de −US$ 9.999 |

**Lo que F1 NO hace:** no repara los datos que ya estaban mal. Eso es "la limpieza", y está
parcialmente hecha (ver `audit/_HANDOFF-TANDAS.md` §4-ter).

### F2 ✅ — «que la IA y lo que sale de la app no mientan»

Lo que se publica **hacia afuera** o **hacia el modelo**:

- **B-3** — la IA recibía la ganancia de por vida **duplicada ×2 exacto** (sumaba la fila
  sintética `global` más las por-broker). Viajaba en el contexto de cada mensaje del chat.
- **B-2** — el prompt que **rankea clientes** del asesor recibía un retorno sin el filtro que el
  propio código documenta.
- **B-1** — el Wrapped decía literalmente *"Tu rendimiento TWR"* sobre una fórmula que no lo es.
  **+10,0 %** donde el motor mide **+6,67 %**; compuesto a doce meses, **+213,8 % contra +115,7 %**.
  Y `shareCard.js` lo exporta como PNG: ese número **salía de la app**.
- **B-4** — `Interés PF` sin conversión de moneda. Medido en producción: 1 usuario, 2 filas,
  **$121.095 en pesos publicados como US$ 121.095**. Reparado hacia atrás y hacia adelante.

**La trampa que costó, y que te puede pasar a vos:** al migrar cinco lectores a un primitivo
compartido es natural dar por cubierto el guard que traían. **No lo está.** El primitivo cortaba
por una condición distinta, y soltar el guard viejo publicaba el mes de alta inflado (23,71 %
contra 20,10 % real). **Los dos guards tienen que convivir.** Ver
`memory/feedback_dietz_no_cubre_el_guard`.

### F3 ✅ — «un solo calendario» (2026-09-09, `41fa6a37`)

Convivían **tres calendarios**: hora argentina, UTC y hora local del proceso, más UTC y hora
local del navegador en el frontend. La hora argentina estaba escrita **a mano nueve veces** en
el backend y **veintisiete** en el frontend.

- El cron **archivaba el cierre del viernes como sábado**. La conversión existía desde
  2026-05-31 y **nunca corrió**: el runner pasaba fecha no-nula y la rama era inalcanzable.
- El **% del año** restaba dos veces el aporte del 1 de enero: sobre una cartera que ganó
  US$ 1.000 publicaba **−US$ 4.000 / −22,86 %**, con el signo invertido.
- **"Este mes" del Dashboard medía desde 79 días antes**: +35,24 % donde el mes real fue +2,90 %.
- **Cargar una operación a las 22:00 la fechaba mañana** — y el guard de fecha futura miraba el
  mismo reloj equivocado, así que aceptaba justo lo que existe para frenar.

**Lo que dejó vivo, a propósito y medido:** el **% del año queda con una rueda de más** hasta
enero de 2027, porque el arreglo del cron sólo alcanza a las fotos nuevas y las de diciembre de
2025 siguen con la etiqueta corrida. **El dueño decidió NO re-etiquetar la historia** y esperar
a enero. **No se lo vuelvas a preguntar.** Y ojo: **el botón para re-etiquetar no existe** —
habría que construirlo.

Detalle completo: `audit/_HANDOFF-TANDAS.md` §5-F3.

⚠️ **F3 no terminó, y su guard no lo ve.** Unificó la *definición* del día argentino y dejó un
test que impide re-copiarla — eso funciona. Pero ese test busca la fórmula (`hours = 3`), **no
el uso del reloj equivocado**, que es otra cosa. Quedan **~40 sitios de producción** pidiéndole
la fecha a `date.today()` / `utcnow()` (en Railway los dos son UTC). La mayoría no decide un
borde. **Uno sí**: `importing/persister.py:1264` borra las fotos con fecha futura con el reloj
malo, así que entre las 21:00 y las 00:00 **no borra justo la de mañana, que es la única que
existe para borrar** — y el limpiador de `main.py` sí usa el reloj bueno. Además, 33 archivos de
test siembran fechas con UTC; dos de ellos ponían la suite en rojo sola de noche (arreglados en
`a1bceb12`). Ver `memory/project_f3_relojes_pendientes`.

### F4 ✅ — «los guards que ya existen, en todos los lectores» (2026-09-10, `9ecb35f1` + `48b934f9`)

Toda la causa C7, 6 de 6. Las tres decisiones que estaban frenadas las tomó el dueño:

| punto | qué se hizo |
|---|---|
| `trustMktValue` con 0/negativos, `_FINITE_BOUND`, broker en `positions` | ya estaban de antes |
| **Edad máxima del precio** | **mostrar ≠ anotar**: la pantalla sigue usando el último precio conocido tenga la edad que tenga; la foto que queda en la historia sólo acepta precios frescos (48 h, el mismo número que ya usaba `register_trade`) |
| **Cota del % realizado** | el techo (1000 %) pasó de **2 superficies a 7**: Wrapped, Reportes, la exportación CSV y 5 paquetes de IA lo ignoraban |
| **Denominador del hero** | **el máximo aportado histórico** en vez del actual, con piso de US$100 |

**La raíz del primero es la más instructiva:** el relleno de precios **le tapaba los ojos al
guard de cobertura del 95 %**, que decía textual *"preferimos NO escribir ese día antes que
escribir un dato corrupto"* y nunca se enteraba de que faltaba nada. Misma forma que el hallazgo
de F1.

**El segundo es un cinturón, no un arreglo** — y está dicho en el código: las dos causas del
+188.566 % siguen abiertas (`project_sell_scale_per100` y `project_entry_price_cruzada`).

**El tercero no era propagar un guard, era corregirlo.** El plan proponía copiar el de
`realized%`, que usa el pico de la **CARTERA**; copiarlo le rompía el número al que nunca
retiró. Al mirarlo de cerca el equivocado era ése: metía la ganancia **no realizada** en el
denominador de un porcentaje sobre capital **aportado**. Medido: 10k aportados, 30k de cartera,
5k realizados → publicaba **20,8 % donde son 50 %**. Terminó unificando **siete copias con tres
criterios** en `twr.denominador_aportado` + su espejo `evolution.js`.

⛔ **El sub-punto "y `operations`" del plan NO se hace, y es una decisión.**
`test_currency_fallback_to_usd_if_broker_unknown` **exige** que `POST /api/operations` acepte un
broker desconocido con 200. El contrato lo tolera a propósito.

Detalle: `memory/project_f4_guards`.

---

## 6 · ➡️ F5 — «una sola cotización, una sola política de faltantes»

Toda la causa C8 más la parte de C1 que toca el tipo de cambio. **Citas verificadas contra el
árbol el 2026-09-11** — si no coinciden, buscá por nombre de función, no por número de línea.

### Lo que ya está deployado

**La serie CER estaba caída** y **todos los bonos CER ajustaban por 1,00 cuando el factor real
es 7,7× a 37,6×**. La fuente devuelve 404 mientras `/inflacion` y `/uva` del mismo host
devuelven 200. Se sirve con UVA, que da el mismo ratio porque el BCRA la actualiza *por* CER —
verificado a 0,25 % contra los factores medidos. Ver `memory/project_cer_via_uva`.

### 1 · El tope de `/api/fx-rates` **y** el fallback mudo (van juntos)

`main.py:5400`, `get_fx_rates`. El endpoint limita por **filas**, no por días:

```python
days = max(1, min(int(days or 3650), 3650))
...
"SELECT date, blue_venta, mep_venta FROM fx_rates_daily ORDER BY date DESC LIMIT ?", (days,)
```

El frontend pide 3.650 "días" y el backend devuelve las **últimas 3.650 filas**. Como la serie
tiene ruedas y no días corridos, la ventana es mucho más corta de lo que el nombre sugiere.

**Medido en la base local (5.634 filas desde 2011-01-03): la ventana arranca el 2016-06-09 y
quedan 1.984 días invisibles.** Toda fecha anterior cae al dólar de hoy **sin avisar**. Una
venta de 2013 se dibuja 160× mal.

Poner un `WHERE date >= ?` arregla el síntoma. **El fallback mudo es la causa** y sigue vivo
para cualquier otro hueco: hoy no hay forma de distinguir "convertí con el TC de esa fecha" de
"no lo tenía y usé el de hoy".

### 2 · Punta venta vs. punta media

`fx_rates_daily` guarda `blue_venta` / `mep_venta`, y hay al menos un lugar que calcula el medio
(`main.py:4853`: `medio = round((compra + venta) / 2, 2) if compra else venta`). Explica un
escalón sistemático de **0,74 %** entre la valuación viva y la histórica. Ver
`memory/project_dolar_medio`.

### 3 · ⛔ La política de faltantes — **acá arranca F5, y no es código**

Qué hace la app cuando **no hay precio**, **no hay tipo de cambio** o **el índice no se
publicó**. Hoy cada capa decide por su cuenta: unas caen al costo, otras al dólar de hoy, otras
publican 0, otras no publican nada.

**Es una decisión de producto y el dueño ya tomó una parecida en F4**, que conviene usar de
ancla porque quedó bien y está deployada:

> **Mostrar y anotar no son lo mismo.** En pantalla, un dato viejo es mejor que un agujero. En
> la historia que queda guardada, **prefiero no medir a medir mal**.

La pregunta para el dueño no es "¿qué política querés?" sino, para cada faltante, **"¿esto se
muestra o se anota?"**. Y hay un tercer caso que F4 dejó abierto y que cae justo acá: las curvas
publican **0 %** cuando no hay denominador, y un 0 no es "no sé", es "no ganaste nada".

### 4 · Inflación restada a retornos en dólares, sin mirar la moneda

Verificados: `wrapped.py:404` (`twr_user - inflation_ytd`), `reporting/builder.py:1691`
(`delta_pct - inflation_ret`), `ai/builders/insights.py:643` (`twr_pct - inflation_pct`),
`main.py:14324` (`inflation_loss`). Ninguno mira la moneda del retorno: **restarle la inflación
en pesos a un rendimiento medido en dólares no significa nada.**

Y falta pasar **moneda a los índices**: hoy `vs_sp500_pct` **cambia de signo** con sólo tocar el
selector. Es la misma familia que el audit de benchmarks ya cerró para otras superficies
(`memory/project_benchmark_audit`) — mirá cómo se resolvió ahí antes de inventar nada.

### 🔑 Tu primer trabajo en F5

Igual que en F4: **preguntar antes de programar**, y preguntar de una forma que el dueño pueda
contestar **mirando**, no sabiendo. Leé `~/.claude/CLAUDE.md` y
`memory/feedback_como_explicarle` antes de escribir la pregunta.

Lo que hizo que las tres preguntas de F4 salieran bien:

1. **Medir primero.** "¿Cortamos a los 2, 5 o 15 días?" no se podía contestar hasta que medí la
   antigüedad real de los precios y resultó ser **bimodal**: 21 frescos y 68 de dos meses, nada
   en el medio. Eso cambió la pregunta.
2. **Decir qué pasa en cada opción**, incluido "no cambia nada para la mayoría".
3. **Una sola pregunta por vez.**

---

## 7 · Las tandas que vienen después

### F6 — «terminar las migraciones abiertas» *(1–2 semanas)*

**Acá es donde la causa raíz dominante deja de reproducirse.** Es la que más cuesta y la que más
cambia el futuro del código.

- Migrar los **5 lectores** que faltan a `valuePositionLot` y **borrar** las matrices duplicadas.
- Las **5 superficies** que publican retorno sin pasar por `twr.py`.
- Los **6 lugares** que comparan contra un índice sin pasar por `performance.py`.
- Persistir `cost_basis_consumed` en la venta.
- Unificar los dos lectores de "Capital aportado" (F1 destapó que divergen: la divergencia ya
  existía, estaba tapada porque el dato se borraba).

**Estado al cerrar: un solo motor por concepto.**

### F7 — «el modelo de datos» *(proyecto aparte, no es una tanda de fixes)*

Es diseño, no arreglos:

- **`operations.pnl_usd` es polimórfica**: guarda cuatro cosas distintas (resultado de venta,
  cash de dividendo, cash bruto de amortización, ganancia cambiaria) en dos monedas.
- **`_NOT_A_TRADE` es una lista de EXCLUSIÓN**, así que **todo tipo de operación nuevo entra como
  "trade cerrado ganado" por omisión**. Ya pasó con `Interés PF`; `Renta`, `Cupón` y
  `Amortización` están en la misma situación, esperando. **Es la única causa que garantiza bugs
  futuros sin que nadie escriba una línea nueva mal.**
- Brokers linkeados **por nombre** (no por clave foránea) en 6 tablas.
- Plazos fijos que no escriben `monthly_entries`.
- Objetivos sin aportes.

---

## 8 · Las 72 divergencias que todavía no tienen veredicto

Están partidas por concepto en `audit/01_calculos/_grupos/<slug>.md`.

**Auditables ya (29):** bonos (13), CEDEAR (8), comisiones (8) — son clases de activo o
conceptos independientes de las tandas.

**Conviene esperar (43):** snapshot (11), TIR (9), dividendos (9), caja (7), variación diaria (7).
Dependen de la cadena que las tandas modifican; auditarlas ahora produce veredictos para rehacer.
La variación diaria dependía de F3, **así que ya se puede**.

---

## 9 · Método — lo que funciona en este repo

1. **Un commit por causa raíz**, revertible solo. Nada de un commit por tanda.
2. **Cada fix trae un test que FALLA con el código viejo.** ⚠️ **Verificalo de verdad:** revertir
   el commit entero también revierte el test, y entonces no probaste nada. **Revertí sólo el
   archivo de código, dejando el test nuevo.**
3. **Baseline ANTES de tocar nada**, y comparación al final. El objetivo es **cero fallos
   NUEVOS**, no cero fallos.
4. **Antes de dar un fix por terminado**, `grep` de todos los call sites del mismo patrón, y
   decir explícitamente cuáles arreglaste y cuáles no.
5. **Un guard defensivo no es un parche.** Y si hay un comentario que justifica algo, **leelo
   antes de reportarlo como bug**: varias veces el código tenía razón y el plan no.
6. **Antes de una validación que RECHAZA:** censo de *callers* Y de *contratos*. No alcanza con
   los callers de Python — puede haber un test que fija una tolerancia deliberada.
7. ⭐ **Cuando el mismo cálculo vive en N lugares, la respuesta por defecto no es arreglar los N:
   es unificarlos en uno solo.** F3 creó `backend/fechas.py`,
   `frontend/src/utils/fecha.js` y `reporting.builder.snapshot_borde_apertura` por esto.
8. ⭐ **Los guards contra la re-copia leen CÓDIGO, no números.** Un test de comportamiento pasa
   igual aunque mañana alguien escriba la copia número 10 en otro archivo — y esa copia *es* el
   bug. Mirá `backend/tests/test_un_solo_calendario.py` y
   `frontend/src/utils/bordeFresco.test.js` (este último **lee el archivo de Python** para
   verificar que los dos lados usen el mismo número).

9. ⭐⭐ **AUDITÁ TU PROPIA TANDA ANTES DE PEDIR EL DEPLOY.** Es lo que más valor dio en F4 y no
   lo cubre ninguna suite. Tres rondas encontraron **12 defectos propios con la suite en verde**,
   y dos estaban en commits ya ofrecidos para deployar. Qué mirar, en orden de rendimiento:
   **(a)** de dónde salen los argumentos de cada función que tocaste — no sólo la función;
   **(b)** el diff completo leído de nuevo, buscando lo que cambiaste sin entender;
   **(c)** los comentarios que quedaron describiendo el código de antes (C12);
   **(d)** tus propios tests: ¿miden, o sólo verifican que aparezca un string?
10. ⭐ **Cuando unifiques un cálculo, revisá también de dónde salen sus argumentos.** La regla
   puede quedar perfecta y seguir recibiendo basura. En F4 unifiqué el denominador en siete
   sitios y dejé uno alimentándose de un helper que cae a COSTO: el resultado correcto era 50 %
   y publicaba **0,03 %**. Ver `memory/feedback_el_fallback_del_helper`.
11. ⭐ **Un helper no es su nombre: leé qué devuelve cuando el dato falta.** `netDepositedOf`
   suena a "el aportado", y cae a `total_invested` (costo) cuando el dato no está. Correcto para
   dibujar una serie, veneno para un denominador. **Si tu cálculo es un denominador, una cota o
   un máximo, un fallback pensado para "que no quede un hueco" casi nunca sirve.**
12. ⭐ **Si el número puede verse en pesos y en dólares, probá las dos.** Un umbral en USD
   comparado contra montos en pesos no filtra nada: el mismo usuario con US$50 aportados no veía
   porcentaje en dólares y sí en pesos. **La forma que no puede divergir es calcular en una
   moneda y convertir, no calcular dos veces.**

### Cinco trampas concretas que ya costaron

1. **Ojo con dónde insertás una función en `main.py`.** Un helper metido entre el decorador
   `@app.post(...)` y su función hace que FastAPI **registre el helper como endpoint**.
   `/api/positions` habría quedado roto en producción. No lo cazó la suite.
2. **No testees contra tu propio criterio: testeá contra el motor real.** Una función de
   ponderación escrita comparándola con "lo que yo creía correcto" estaba mal en el caso de
   cripto — **1450×, en la dirección contraria al bug que venía a arreglar**.
3. **Un test viejo puede tener razón.** Un fix "obvio" a un guard rompió dos tests que fijaban
   que una posición con cantidad 0 vale 0. Tenían razón. Pasó **de nuevo** en F3, con el borde
   de quien empezó dentro del mes. **Leé el test antes de cambiarlo.**
4. **El primitivo no hereda tus guards.** Ver F2 arriba.
5. **Antes de explicar un test en rojo, mirá la hora.** De 21:00 a 00:00 hora argentina la
   suite se pone roja sola. ⚠️ **F3 NO cerró esto**: arregló el código, no los tests, y quedaron
   33 archivos sembrando fechas con UTC. Medido el 2026-09-10: `origin/main` daba **2 en rojo a
   las 23:20 y 0 a las 10:40** sin que nadie tocara nada (esos dos se arreglaron en `a1bceb12`;
   los otros 31 son latentes). Y **el conteo de la suite completa no es una métrica**: agregar
   un test que crea un usuario lo mueve sin tocar código.
6. ⭐ **Revertir con `git stash` no prueba nada si ya commiteaste el arreglo** — vuelve al
   último commit, que YA lo tiene. Me pasó verificando: todo verde y ese verde no significaba
   nada. Para probar que tu fix importa, `git checkout <commit-anterior> -- <archivos de
   código>`, dejando los tests nuevos puestos.
7. ⭐ **Un test que sólo existe porque la función es nueva no mide nada.** Al revertir el código,
   la mitad de los tests fallan con "X is not a function" — eso prueba que X es nueva, no que el
   bug existía. **Poné los imports DENTRO de cada test** (o marcá en la cabecera cuáles son los
   que miden de verdad) para que cada uno falle por SU motivo.
8. ⭐ **Cuidado con el estado global entre tests.** `compute_live_portfolio_value` cachea 60 s en
   un dict de módulo con clave `(uid, tc_blue)`, y nadie lo limpia: con `uid=1, tc_blue=1500`
   —los que usa medio archivo— un test puede pasar leyendo el valor de OTRA base, sin ejecutar
   una línea de lo que dice probar. Verificado sembrando el caché a mano.

---

## 10 · ⚠️ Coordinación — esto ya rompió cosas dos veces

**El usuario corre varias sesiones sobre el mismo repo al mismo tiempo.**

**2026-09-08:** otra sesión deployó a `main` mientras esta rama tenía los mismos fixes sin
mergear. Se detectó al chequear antes de mezclar; mergear a ciegas habría pisado su solución con
una peor.

**2026-09-09, durante F3:** otra sesión editaba `backend/main.py` en la misma carpeta. Un
`git add -A backend/` **se llevó su fix de seguridad adentro de un commit mío** que hablaba de
fechas — **y sin su test**, que vivía en otro archivo. Estuvo a un push de ir a producción.

**2026-09-10/11, durante F4: esta vez salió bien, y así fue.** La otra sesión trabajó en los
importadores toda la sesión y pusheó dos veces en el medio. No hubo un solo conflicto porque:
(a) trabajé en un **worktree propio y limpio** creado desde `origin/main`, nunca en la carpeta
compartida; (b) antes de cada push hice `git fetch` y **comparé las dos listas de archivos con
`comm -12`** — cero intersección las dos veces; (c) commiteé **archivo por archivo**, nunca
`git add -A`. **Es el procedimiento, no la suerte: repetilo.**

**Las cuatro reglas que salen de eso:**

1. **`git fetch && git log --oneline HEAD..origin/main`** antes de mergear o pushear cualquier
   cosa. Si hay solapamiento, **comparen las dos soluciones** — no asumas que la tuya es la buena.
2. **Nunca `git add -A <dir>`** en una carpeta compartida. Archivo por archivo, o revisá
   `git diff --cached` completo antes de commitear.
3. **Leé tu propio diff buscando lo que NO escribiste.** El filtro que lo encontró: listar las
   líneas de código del diff que no mencionan nada del tema de la tanda. Lo ajeno salta solo.
4. ⭐ **No midas la suite en un árbol con trabajo ajeno en curso.** Dos tests daban rojo y
   parecían regresiones propias; eran de un cambio a medio hacer de otra sesión. La medición
   válida se hace en **dos worktrees limpios, uno por rama**:
   ```bash
   git worktree add --detach /Users/nicolaspussetto/rendi-worktrees/_tmp-mio HEAD
   git worktree add --detach /Users/nicolaspussetto/rendi-worktrees/_tmp-base origin/main
   cp backend/.env <cada worktree>/backend/.env     # misma condición en los dos
   ```
   Y **borralos al terminar** (`git worktree remove --force`), que se llevan la copia del `.env`.

**Si te llevaste algo ajeno: devolvelo, no lo deployés.** Revertilo en un commit propio con el
motivo, y dejá su cambio en el árbol donde estaba.

---

## 11 · Estado del repo y cómo correr todo

**Deploy = push a `origin/main`.** No hay CI: Railway (backend) y Vercel (frontend) observan esa
rama. Pushear una rama cualquiera no deploya.

```bash
cd backend  && python3 -m pytest tests/ -q      # ~60 s. `tests/` NO está en la raíz del repo
cd frontend && npm test -- --run                 # ~2 s
cd frontend && npm run build                     # verificá que compile antes de pushear
```

⚠️ **`npm test` necesita `node_modules`, y un worktree nuevo no lo tiene.** No hace falta
instalar: `ln -s <repo-principal>/frontend/node_modules node_modules` alcanza (es sólo lectura y
no toca el árbol de la otra sesión) **siempre que `package.json` sea idéntico — verificalo con
`diff`**. Y **borralo antes de commitear**: `.gitignore` ignora `node_modules/` como directorio
y un symlink NO matchea, así que aparece como archivo sin trackear.

**Verificar un deploy sin adivinar** — los dos exponen el SHA:

```bash
curl -s https://rendi.finance/version.json      # frontend (Vercel),  ~30 s
curl -s https://rendi.finance/api/health        # backend (Railway), ~100 s
```

**El baseline no es un número que puedas copiar de un documento.** Depende del entorno (con o sin
`backend/.env` cambian 6 resultados), **de la hora** (ver §9, trampa 5) y hasta de cuántos
usuarios crea un test. **Medí el tuyo antes de tocar nada.** Como referencia, en worktrees
limpios: 2026-09-09 `origin/main` **4.113 / 0**; 2026-09-11 después de F4, **4.237 / 0** en
backend y **1.552 / 0** en frontend.

### Dónde está todo

| archivo | qué es |
|---|---|
| `audit/01-calculos.md` | **el plan.** 222 hallazgos por causa raíz, las 7 dependencias entre fixes, las 7 tandas. **Leé este primero, es corto** |
| `audit/_HANDOFF-TANDAS.md` | el histórico largo, tanda por tanda, con lo que costó cada una |
| `audit/01_calculos/1a-resumen.md` | tabla de las 94 divergencias con veredicto |
| `audit/01_calculos/1b-resumen.md` | tabla de los 128 hallazgos transversales |
| `audit/01_calculos/1a-*.md` (8) | detalle de 1A, uno por concepto |
| `audit/01_calculos/1b-*.md` (6) | detalle de 1B, uno por tema. **Los de F5 son `1b-monedas.md` (cotizaciones y faltantes de TC), `1b-inflacion.md` (el punto 4) y `1b-benchmarks.md` (moneda en los índices)**; `1b-borde.md` fue el de F4 |
| `audit/01_calculos/1a-evidencia.md` | MEDIDO vs DEDUCIDO vs ESTRUCTURAL, hallazgo por hallazgo |
| `audit/01_calculos/_grupos/*.md` | las 72 divergencias sin veredicto |
| `audit/00-mapa-sistema.md` | el mapa, 3,4 MB — **no lo leas entero, grepealo** |

> ⚠️ **Los informes tampoco son verdad: son hipótesis verificables.** Además del mapa, F4
> encontró un **error aritmético en `1a-rendimiento.md`**: decía que la regla del asesor daría
> −95 % en su ejemplo y el código da **+4 %** (el informe aplicó el máximo también al
> numerador). Quien lo siguiera al pie de la letra publicaba una pérdida del 95 % sobre alguien
> que ganó plata. **Recalculá los ejemplos del informe antes de implementarlos.**
>
> ⚠️ **El mapa es hipótesis, no verdad.** Se verificaron 290 de sus citas: ~53 tenían el número
> de línea corrido y **5 afirmaciones eran sustantivamente falsas**. Confirmá cada cita con
> `grep` antes de apoyarte en ella. **Si el código contradice al mapa, gana el código.**
>
> Y lo mismo vale para este documento. Las citas de la §6 se verificaron una por una el
> **2026-09-11**; si no coinciden, buscá por nombre de función, no por número de línea.
>
> ⚠️ **Incluidos los nombres de archivo.** Escribiendo esta misma tabla puse dos informes que no
> existen (`1b-fx.md`, `1b-faltantes`) y los cazó un `ls`. **Antes de mandar a alguien a un
> archivo, verificá que esté.**

### Memoria del proyecto

Hay memoria persistente en
`~/.claude/projects/-Users-nicolaspussetto-Documents-trading/memory/`. Las que importan para F5:

**Antes de escribir una sola línea**
- `feedback_como_explicarle` — ⭐⭐ **cómo hablarle al dueño.** No programa. Sin jerga pero CON
  todo el detalle, y separando "lo hago yo" de "lo hacés vos"
- `project_tandas_calculo` — estado vivo de las 7 tandas
- `project_f4_guards` — lo último que se hizo, con las 3 decisiones que tomó el dueño y las 12
  cosas que encontró auditarlas

**Sobre el tema de F5**
- `project_cer_via_uva` — el CER, lo único de F5 ya deployado
- `project_fx_rate_audit` — la regla "todo MEP excepto cripto-exchange" y las 67 desviaciones
- `project_dolar_medio` — la punta media vs la punta venta
- `project_benchmark_audit` — ⭐ cómo se resolvió el modo pesos en los índices. **Mirá esto
  antes de inventar nada para el punto 4**

**Trampas del método**
- `feedback_el_fallback_del_helper` — ⭐ leé qué devuelve un helper cuando el dato falta
- `feedback_el_test_viejo_tenia_razon` — ⭐ pasó tres veces
- `feedback_git_add_con_otra_sesion_viva` — la §10 de acá, resumida
- `feedback_quien_mas_pasa_por_aca` — antes de una validación que rechaza
- `feedback_buscar_el_guard` — antes de una reparación masiva
- `feedback_antes_de_explicar_un_rojo_mira_la_hora` — la suite se pone roja sola de noche
- `project_test_suite_state` — por qué el conteo de la suite no es una métrica
- `project_f3_relojes_pendientes` — los ~40 relojes que F3 dejó y el bug del importador

---

## 12 · Lo que queda anotado y sin hacer (fuera de las tandas)

Cuatro cosas que F4 encontró, midió y **no** tocó, con el motivo:

1. **El bug del reloj en el importador** (`importing/persister.py:1264`). Una línea. No se tocó
   porque abrir los ~40 relojes es decidir cuánto trabajo más meterle a F3.
2. **`POST /api/snapshots` escribe la foto con el total calculado en el NAVEGADOR** y
   `SnapshotIn` son tres números sueltos: no viaja cobertura, así que un precio viejo entra a la
   historia por esa puerta. Amortiguado (`apto=0`) pero su `total_value` se guarda. Cerrarlo
   cambia el contrato con el frontend.
3. **Las curvas publican `realized: 0` cuando no hay denominador.** Un 0 no es "no sé", es "no
   ganaste nada". Arreglarlo bien = que la serie lleve `null` y el gráfico dibuje un hueco: es
   un cambio de forma de los datos. **Cae dentro de la política de faltantes de F5** (§6.3).
4. **El `MEMORY.md` del proyecto está sobre el límite** (~28 KB contra 24,4) y se carga
   incompleto: 37 entradas del índice pasan los 200 caracteres, una llega a 1.290. El detalle
   está en los archivos de tema; hay que acortar el índice.
