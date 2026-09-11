# Handoff — la auditoría de cálculo de Rendi, y por qué la próxima es F6

Si sos la sesión que arranca: **leé esto entero antes de tocar código.** Es autocontenido. No
hace falta abrir el mapa de 3,4 MB ni los 14 informes de detalle salvo que el trabajo te lleve
ahí, y en ese caso este documento te dice a cuál.

---

## 0 · Lo primero, en treinta segundos

Rendi tiene una auditoría de cálculo con **222 hallazgos**, que se ejecuta en siete tandas
(F1 a F7). **F1, F2, F3, F4 y F5 están hechas y deployadas.**

➡️ **La que sigue es F6, «terminar las migraciones abiertas — un solo motor por concepto».**

F6 es distinta de todas las anteriores en un punto que conviene saber antes de empezar: **no
arranca con una decisión tuya ni con un bug que duele.** Arranca con una mudanza. Las cinco
tandas previas fueron "esto publica un número falso, arreglalo"; F6 es "hay cuatro motores que
calculan lo mismo, dejá uno". Es la más cara (1–2 semanas) y la que no se ve en pantalla — y es
**la única que hace que la causa raíz del proyecto deje de reproducirse**. Si la saltás, la
tanda siguiente vuelve a encontrar los mismos 28 hallazgos con otros nombres.

⭐ **Lo más importante que dejaron F4 y F5, y que no está en ningún informe: auditar la tanda
contra sí misma encuentra defectos que la suite en verde no muestra.** En F4 fueron 12. En F5
fueron **5, y uno estuvo mal en producción veinte horas**. Y cada ronda correctiva encontró
defectos en el código escrito por la ronda anterior. Reservá tiempo para auditarte al final —
no es opcional, y **cada tanda correctiva necesita su propia ronda**. La §9 explica cómo.

**Antes de tocar nada:**

```bash
cd /Users/nicolaspussetto/Documents/trading
git fetch && git log --oneline HEAD..origin/main      # ¿entró algo de otra sesión?
git status --short                                     # ¿hay trabajo ajeno sin commitear?
cd backend && python3 -m pytest tests/ -q | tail -1    # tu baseline, medido por vos
cd ../frontend && npm test -- --run 2>&1 | grep "Tests"
```

⚠️ Si `git status` muestra archivos modificados que vos no tocaste, hay **otra sesión viva** en
esa carpeta. Leé la §10 antes de seguir: no es un detalle, ya rompió cosas dos veces.

---

## 1 · Qué es Rendi

App argentina de seguimiento y análisis de carteras de inversión multi-broker: tenencias,
operaciones, ganancia realizada y no realizada, rendimientos (incluido ajustado por inflación),
objetivos y comparaciones contra índices. Tiene planes de suscripción, período de prueba y un
plan para asesores financieros (un asesor ve el libro de todos sus clientes).

**Dos cosas del dominio explican la mitad de los bugs.** Si no las tenés presentes, vas a
diagnosticar mal:

1. **Argentina tiene varios dólares** (blue, MEP, CCL, cripto, oficial) con diferencias
   materiales entre ellos. Elegir mal la cotización, o usar la de hoy para una operación de
   2021, desvía plata de verdad. Y cada dólar tiene **dos puntas** (compra y venta): la app
   valúa al **punto medio**, que es el que usan los brokers — ver §5-F5.
2. **Un mismo activo se puede tener en pesos y en dólares en el mismo broker**, y hay
   sub-brokers (`Cocos · USD`) que son la pata dólar de un broker argentino. La moneda del lote
   y la moneda de la cuenta no son lo mismo, y confundirlas es la causa raíz de varios de los
   errores más grandes que se encontraron.

---

## 2 · Qué es la auditoría, y cuál fue el veredicto

Antes existía un **mapa del sistema** (`audit/00-mapa-sistema.md`, 28.586 líneas) que
documentaba *qué hay*. La auditoría responde *qué está mal*.

Se hizo en dos tandas, con agentes en paralelo, cada uno sobre una copia limpia de solo lectura
del commit que estaba en producción (`b74f450f`):

| tanda | qué cubrió | resultado |
|---|---|---|
| **1A** | 94 de las 166 "implementaciones divergentes" — casos donde el mismo concepto se calcula de más de una forma | **85 de 94** dan números realmente distintos. Sólo 9 eran cosméticas |
| **1B** | 6 temas transversales: decimales, monedas y cotizaciones, fechas y zonas horarias, inflación, benchmarks, casos borde | **128 hallazgos** |

**Total: 222 hallazgos con veredicto.** De esos, **50 están MEDIDOS** ejecutando código (con la
traza pegada en el informe); el resto es lectura verificada con grep. La distinción está
hallazgo por hallazgo en `audit/01_calculos/1a-evidencia.md`, e importa.

### El veredicto general, sin suavizar

**Los motores centrales están bien.** `backend/twr.py`, `backend/performance.py` y
`frontend/src/utils/valuation.js::valuePositionLot` son correctos y están documentados con las
mediciones que los justifican.

**El problema es que el producto no los usa.** Cinco superficies publican rendimiento sin pasar
por el motor de rendimiento; seis comparan contra un índice sin pasar por el de índices; el
valuador canónico admite en su propio docstring que **todavía no lo consume nadie**
(`valuation.js:601`, verificado el 2026-09-11).

No es un sistema mal pensado. Es un sistema bien pensado **cuyas correcciones nunca terminaron
de propagarse** — por eso se ordena en tandas y no es una reescritura. **Y es exactamente lo que
F6 viene a cerrar.**

---

## 3 · Las 12 causas raíz — y la que domina todo

| # | causa | hallazgos (≥) | esfuerzo |
|---|---|---|---|
| **C1** | **El fix existe pero no se propagó a todos los call sites** | **28** | medio |
| C2 | Copiar y pegar sin un origen designado | 21 | grande |
| C3 | Falta una capa compartida: no hay dónde poner el cálculo | 17 | grande |
| C7 | Guard o cota ausente en un lector — *fue F4* | 17 | chico |
| **C5** | **Migración empezada y nunca terminada — ES F6** | **14** | grande |
| C8 | Cada capa decide su propia política de faltantes — *fue F5* | 10 | medio |
| C4 | Port a mano que quedó atrás del original | 9 | medio |
| C10 | Modelo de datos incompleto (tipo, moneda, FK) | 8 | grande |
| C6 | El frontend hace lo que el backend no sabe hacer | 7 | medio |
| C11 | Decisión deliberada o parche documentado (no son bugs) | 6 | ninguno |
| C9 | Zona horaria y calendario — *fue F3* | 3+ | medio |
| C12 | Documentación que afirma algo que el código no hace | 2+ | chico |

Los conteos son **cota inferior** (105 filas tienen texto libre que no mapea limpio). Lo que
sostiene el plan es el **orden relativo**, que es robusto, no el dígito exacto.

### C1 es la causa dominante, y no es descuido

Es la forma que toma un fix correcto en este código. El patrón se repite idéntico: alguien
diagnostica bien, arregla bien, deja el comentario que lo explica — y **el arreglo llega a un
call site de varios**. Ejemplos verificados, incluidos los de hoy:

- El fix de `toISOString` estaba en **1 de 28** lugares, con el comentario de auditoría al lado.
- El fix del tipo de cambio histórico llegó a **2 de 3** motores de venta *(F5 cerró el tercero)*.
- La conversión del costo cross-currency vivía copiada en **3 motores**, y el del formulario
  manual no miraba la versión de FX de la cuenta *(F5)*.
- En el MISMO endpoint de venta, la pata del TC de venta era version-aware y la del costo no —
  **a treinta líneas de distancia** *(F5)*.
- `monthlyReturnArs` arreglaba el veredicto contra inflación en el frontend y **no había llegado
  a los drivers de Reportes** *(F5)*.
- La regla del punto medio del dólar llegó a cinco lectores y **no a la rama fría del cron
  nocturno**, que es la que más corre *(F5)*.

Las **dos reglas permanentes de `CLAUDE.md`** salieron de acá. Respetalas o vas a generar el
hallazgo 223.

### C12 es chica en conteo y grande en consecuencia

Hay comentarios que afirman premisas falsas **y sobre los que después se construyó lógica**. En
F5 pasó dos veces en un solo día, con comentarios que había escrito yo mismo esa mañana.
Mientras esos comentarios sigan ahí, el próximo que lea el código repite el error.

---

## 4 · Las 7 tandas de un vistazo

No están ordenadas por gravedad, sino **por lo que cada una habilita**: primero se frena lo que
corrompe datos nuevos, después lo que se publica mal, y al final se unifican los motores para
que la causa raíz deje de reproducirse.

| tanda | qué resuelve, en una línea | estado |
|---|---|---|
| **F1** | Que la app deje de **escribir** mal. Un número mal mostrado se arregla el día que se toca el código; uno mal escrito queda para siempre | ✅ hecha y deployada |
| **F2** | Que la IA y las pantallas no mientan: cuatro números que se publicaban mal hacia afuera | ✅ hecha, deployada y cerrada |
| **F3** | **Un solo calendario.** Convivían tres relojes dentro del mismo endpoint | ✅ hecha y deployada |
| **F4** | Los guards que ya están escritos pero no llegaron a todos los lectores | ✅ hecha y deployada, 6 de 6 |
| **F5** | Una sola cotización y una sola política de faltantes | ✅ hecha y deployada (2026-09-11) |
| **F6** | **Terminar las migraciones abiertas. Un solo motor por concepto** | ➡️ **LA QUE SIGUE** — 1 a 2 semanas |
| **F7** | El modelo de datos. Es diseño, no arreglos | ⬜ proyecto aparte |

---

## 5 · Las cinco que ya están hechas

### F1 ✅ — «que deje de escribir mal»

Criterio: **sólo lo que corrompe datos nuevos.** 13 commits, cada uno con un test que falla
contra el código viejo.

| qué estaba mal | efecto medido |
|---|---|
| El cron de snapshots contaba un costo en pesos como dólares en cuentas USD | **×1.450** |
| El guard de cobertura del 95 % ponderaba por la moneda del broker, no del lote | dejaba ciego al guard |
| Una conversión de moneda **creaba capital de la nada** | US$ 444.342 salieron y US$ 217.932 volvieron sin que ningún broker los acreditara. 41 usuarios, 12 con capital aportado negativo |
| `reconcile-cash` dividía por un dólar fijo (1415) | **+7,3 %** de capital fantasma, permanente |
| El recalc borraba el `capital_inicio` que el usuario tipeó | irrecuperable |
| La venta sellaba un TC distinto del que usó para dividir la ganancia | fila con `fx_to_usd = 1.0` y P&L dividido por ~1.400 |
| `SellModal` no recibía las cotizaciones históricas en mobile | una venta retroactiva desde el celular quedaba al dólar de hoy |
| Una operación con fecha futura congelaba el calendario mensual | el usuario se quedaba sin fila del mes en curso hasta 2030 |
| El guard antidistorsión aceptaba valor negativo y NaN | la posición se publicaba valiendo menos que nada |
| `PositionIn` no acotaba sus montos | `invested = 1e308` entraba y llegaba a `capital_final` |
| Se podía cargar una posición contra un broker inexistente | fila huérfana → pérdida fantasma de −US$ 9.999 |

**Lo que F1 NO hace:** no repara los datos que ya estaban mal. Eso es "la limpieza", y está
parcialmente hecha (ver `audit/_HANDOFF-TANDAS.md` §4-ter).

### F2 ✅ — «que la IA y lo que sale de la app no mientan»

- **B-3** — la IA recibía la ganancia de por vida **duplicada ×2 exacto**. Viajaba en el
  contexto de cada mensaje del chat.
- **B-2** — el prompt que rankea clientes del asesor recibía un retorno sin el filtro que el
  propio código documenta.
- **B-1** — el Wrapped decía literalmente "Tu rendimiento TWR" sobre una fórmula que no lo es.
  **+10,0 % donde el motor mide +6,67 %**; compuesto a doce meses, +213,8 % contra +115,7 %. Y
  `shareCard.js` lo exporta como PNG: ese número **salía de la app**.
- **B-4** — Interés PF sin conversión de moneda. Medido en producción: 1 usuario, 2 filas,
  $121.095 en pesos publicados como US$ 121.095. Reparado hacia atrás y hacia adelante.

⚠️ **La trampa que costó**: al migrar cinco lectores a un primitivo compartido es natural dar
por cubierto el guard que traían. **No lo está.** El primitivo cortaba por una condición
distinta, y soltar el guard viejo publicaba el mes de alta inflado (23,71 % contra 20,10 %
real). Los dos guards tienen que convivir. Ver `memory/feedback_dietz_no_cubre_el_guard`.

### F3 ✅ — «un solo calendario» (`41fa6a37`)

Convivían **tres calendarios**: hora argentina, UTC y hora local del proceso, más UTC y hora
local del navegador en el frontend. La hora argentina estaba escrita a mano **nueve veces en el
backend y veintisiete en el frontend**.

- El cron archivaba el cierre del viernes como sábado. La conversión existía desde 2026-05-31 y
  **nunca corrió**: el runner pasaba fecha no-nula y la rama era inalcanzable.
- El % del año restaba **dos veces** el aporte del 1 de enero: sobre una cartera que ganó
  US$ 1.000 publicaba **−US$ 4.000 / −22,86 %**, con el signo invertido.
- "Este mes" del Dashboard medía desde **79 días antes**: +35,24 % donde el mes real fue +2,90 %.
- Cargar una operación a las 22:00 la fechaba mañana — y el guard de fecha futura miraba el
  mismo reloj equivocado, así que **aceptaba justo lo que existe para frenar**.

**Lo que dejó vivo, a propósito y medido:** el % del año queda con una rueda de más **hasta
enero de 2027**. El dueño decidió **NO re-etiquetar la historia** y esperar a enero. **No se lo
vuelvas a preguntar.** Y ojo: el botón para re-etiquetar **no existe** — habría que construirlo.

⚠️ **F3 no terminó, y su guard no lo ve.** Su test busca la **fórmula** (`hours = 3`), no el
**uso del reloj equivocado**, que es otra cosa. Quedan **~40 sitios** de producción pidiéndole la
fecha a `date.today()` / `utcnow()` (en Railway los dos son UTC). Uno importa:
`importing/persister.py:1264` borra las fotos con fecha futura con el reloj malo, así que entre
las 21:00 y las 00:00 **no borra justo la de mañana**, que es la única que existe para borrar.
Además, **33 archivos de test** siembran fechas con UTC. Ver
`memory/project_f3_relojes_pendientes`.

### F4 ✅ — «los guards que ya existen, en todos los lectores» (`9ecb35f1` + `48b934f9`)

Toda la causa C7, **6 de 6**. Las tres decisiones frenadas las tomó el dueño:

| punto | qué se hizo |
|---|---|
| Edad máxima del precio | **mostrar ≠ anotar**: la pantalla sigue usando el último precio conocido tenga la edad que tenga; la foto que queda en la historia sólo acepta precios frescos (48 h) |
| Cota del % realizado | el techo (1000 %) pasó de **2 superficies a 7** |
| Denominador del hero | el **máximo aportado histórico** en vez del actual, con piso de US$ 100 |

La raíz del primero es la más instructiva: **el relleno de precios le tapaba los ojos al guard
de cobertura del 95 %**, que decía textual *"preferimos NO escribir ese día antes que escribir un
dato corrupto"* y nunca se enteraba de que faltaba nada.

El tercero **no era propagar un guard, era corregirlo**. El plan proponía copiar el de
`realized%`, que usa el pico de la CARTERA; copiarlo le rompía el número al que nunca retiró. Al
mirarlo de cerca el equivocado era ése. Medido: 10k aportados, 30k de cartera, 5k realizados →
publicaba **20,8 % donde son 50 %**.

⛔ El sub-punto "y `operations`" del plan **NO se hace, y es una decisión**:
`test_currency_fallback_to_usd_if_broker_unknown` exige que `POST /api/operations` acepte un
broker desconocido con 200. El contrato lo tolera a propósito.

Detalle: `memory/project_f4_guards`.

### F5 ✅ — «una sola cotización» (2026-09-11, `54e60f83` → `10ea031f`, once commits)

⭐ **El hallazgo estructural de F5, y la lección que más sirve para F6: la "política de
faltantes" que había que inventar YA ESTABA ESCRITA en cuatro lugares del repo, y decía lo mismo
en los cuatro.** Ninguno se había propagado, y al lado de cada uno vivía un hermano mudo que
hacía lo contrario. **Antes de diseñar algo en F6, buscá si ya está escrito.** Casi siempre lo
está.

**Lo que se arregló:**

| qué | efecto medido |
|---|---|
| `/api/fx-rates` cortaba por **filas** y no por fecha | ventana ciega de **1.984 días**; una operación del arranque de la serie se dibujaba **×389** |
| La misma venta daba costos distintos **tipeada que importada** | MEP y blue se separan >3 % en la mitad de los días, **25,1 %** el peor |
| La comparación contra inflación restaba **pesos a dólares** | el veredicto se daba vuelta con sólo tocar el selector en **65 de 186 meses (35 %)** |
| El costo se convertía con un dólar y la ganancia se dividía por otro | **−US$ 300 donde eran +US$ 200**: el signo invertido |
| El dólar **por fecha** era la punta de venta y el vivo el punto medio | cerraba la "pérdida fantasma" que `ledger_replay` documentaba y parcheaba |

**La decisión del dueño**: *"¿le ganaste a la inflación?" se contesta SIEMPRE en pesos*, y *"que
quede todo al medio, que es el que usan los brokers"*.

⭐⭐ **Y lo más importante para vos: de los once commits, TRES fueron para arreglar errores míos**,
y uno estuvo mal en producción veinte horas (la tarjeta de inflación publicando *"le ganaste"*
sobre un mes que perdió 40 %). Los encontró **auditarme, no la suite**. Detalle en
`memory/project_f5_cotizacion` y `memory/project_dolar_medio_historico`.

---

## 6 · ➡️ F6 — «terminar las migraciones abiertas»

**Toda la causa C5 (14 hallazgos) más lo que se pueda de C2 (21).** Estimado 1–2 semanas.

**Acá es donde C1 deja de reproducirse.** Las cinco tandas anteriores arreglaron síntomas de
"el fix no se propagó"; F6 saca los lugares a los que habría que propagarlo.

Citas verificadas contra el árbol el **2026-09-11** — si no coinciden, buscá por **nombre de
función**, no por número de línea.

### 6.1 · El valuador canónico que no consume nadie

`frontend/src/utils/valuation.js:637` define `valuePositionLot`, la valuación de UN lote. Su
propio docstring (línea 601) dice, textual:

> *"Esta es la que va a serlo. **Todavía NO la consume nadie más**"*

Verificado hoy: el único caller es `computeBrokerValue`, en el mismo archivo (línea 842).

**Qué hacer:** migrar los 5 lectores que faltan y **borrar las matrices duplicadas**. El plan
original los cuenta; **contalos vos de nuevo antes de empezar** (el informe puede haber
envejecido — ver el ⚠️ de la §11).

**Por qué importa:** mientras haya dos valuadores, cualquier arreglo de valuación tiene que
aplicarse dos veces, y la historia del repo dice que se aplica una.

### 6.2 · Las 5 superficies que publican retorno sin pasar por `twr.py`

El motor de rendimiento es correcto y está medido. El problema es quién no lo llama.

⚠️ **F5 ya cerró dos de esta familia** (el Wrapped y el paquete de la IA pasaron a
`twr.vs_inflacion_ar`), así que **el conteo de 5 puede estar desactualizado a la baja**.
Re-censalo.

⭐ **La trampa específica de este punto, medida en F5 y que te va a morder:** cuando migres un
lector al motor, **verificá de dónde sale el número que la pantalla muestra**, no de dónde
"debería" salir. En `reporting/builder.py`, `delta_pct` **se reasigna cinco veces** dentro de la
misma función: para un mes, el motor canónico lo pisa treinta líneas antes de donde vos lo vas a
leer. Calcular el derivado "bien" desde otra fuente publicó **+24,32 % sobre un mes que a mercado
hizo −40 %**. Ver `memory/feedback_la_funcion_exacta_no_es_la_correcta`.

### 6.3 · Los 6 lugares que comparan contra un índice sin pasar por `performance.py`

`performance.py` ya sabe convertir un índice a la moneda de la cartera (`_en_pesos`,
`BENCH_EN_ARS`, `BENCH_PORCENTUAL`) y lo documenta bien.

**Uno de los seis está identificado, medido y anotado en el código**: el gráfico de Performance
dibuja una curva en dólares al lado de la línea de inflación **en pesos**. F5 lo dejó sin tocar
a propósito y explica por qué en `backend/performance.py` (buscá "PENDIENTE, MEDIDO Y NO
ARREGLADO"):

- la conversión correcta es medir la **curva** en pesos, y `twr.curva_indexada` ya sabe;
- pero el frontend **rotula el eje con el selector global** y no con el `moneda` que la respuesta
  ya declara — convertir sin tocar eso deja el gráfico mal etiquetado, que es peor;
- y esa pantalla tiene **su propio motor de benchmark duplicado** en `Insights.jsx:1582`, así que
  arreglarlo en el backend solo **no alcanza**.

Es el ejemplo más claro de por qué F6 es una mudanza y no un fix.

### 6.4 · Persistir `cost_basis_consumed` en la venta

Verificado hoy: la columna **existe** (`main.py:1350`) y **se escribe, pero sólo para
amortizaciones** (`main.py:11180-11188`). Para las ventas no.

Sin ese dato, "cuánto costó lo que vendiste" hay que re-derivarlo en cada lectura — y re-derivar
es exactamente de dónde salen los cuatro motores FIFO que el mapa encontró.

### 6.5 · Unificar los dos lectores de «Capital aportado»

F1 destapó que **divergen**. La divergencia ya existía: estaba tapada porque el dato se borraba.

### 6.6 · Lo que F5 dejó explícitamente para acá

- **El gráfico de Performance** (§6.3), con su motor duplicado en el frontend.
- **La divergencia de riel entre frontend y backend en los drivers de Reportes**: el frontend
  mide con **blue** (`bench.dolar_blue`) y el backend con **MEP** (`twr.serie_fx`) — los dos
  rieles que se separan hasta 25 %. **Hoy no lo renderiza ninguna pantalla**, y está escrito al
  lado del código (`useMonthlyData.js`, buscá "ESTE RIEL NO ES EL DEL BACKEND") con lo que hay
  que hacer si alguna vez se muestra.
- **La ventana del paquete de la IA**: el rendimiento y la inflación cubren meses distintos (el
  TWR saltea el mes de alta, el INDEC publica con ~14 días de atraso). Alinearlas cambia qué
  significa `inflation_ar_pct`, que es un campo publicado: **es una decisión de contrato, no un
  arreglo.** Si la vas a tomar, preguntá.

### 🔑 Cómo empezar F6

A diferencia de F4 y F5, **F6 no arranca con una pregunta al dueño**: arranca con un **censo**.

1. Para cada uno de los cinco puntos, **contá los call sites vos** con grep y anotá la lista.
   Los números del informe son de junio y F5 ya movió algunos.
2. Ordenalos por **cuántos números de pantalla tocan**, no por cuántas líneas son.
3. **Migrá de a uno, con su commit y su test.** Un commit que migra tres lectores a la vez no se
   puede revertir si uno sale mal.
4. Para cada migración, la pregunta que hay que contestar ANTES es: **¿qué guard traía el lector
   viejo que el motor no tiene?** (F2 §5) y **¿de dónde sale el argumento que le vas a pasar?**
   (§6.2). Las dos ya mordieron.

---

## 7 · La que viene después

### F7 — «el modelo de datos» *(proyecto aparte, no es una tanda de fixes)*

Es **diseño**, no arreglos:

- **`operations.pnl_usd` es polimórfica**: guarda cuatro cosas distintas (resultado de venta,
  cash de dividendo, cash bruto de amortización, ganancia cambiaria) en dos monedas.
- **`_NOT_A_TRADE` es una lista de EXCLUSIÓN**, así que **todo tipo de operación nuevo entra como
  "trade cerrado ganado" por omisión**. Ya pasó con `Interés PF`; `Renta`, `Cupón` y
  `Amortización` están en la misma situación, esperando. **Es la única causa que garantiza bugs
  futuros sin que nadie escriba una línea nueva mal.**
- Brokers linkeados por **nombre** (no por clave foránea) en 6 tablas.
- Plazos fijos que no escriben `monthly_entries`.
- Objetivos sin aportes.

---

## 8 · Las 72 divergencias que todavía no tienen veredicto

Están partidas por concepto en `audit/01_calculos/_grupos/<slug>.md`.

**Auditables ya (29):** bonos (13), CEDEAR (8), comisiones (8) — son clases de activo o
conceptos independientes de las tandas.

**Conviene esperar (43):** snapshot (11), TIR (9), dividendos (9), caja (7), variación diaria
(7). Dependen de la cadena que las tandas modifican. La variación diaria dependía de F3, así que
ya se puede.

---

## 9 · Método — lo que funciona en este repo

**Un commit por causa raíz, revertible solo.** Nada de un commit por tanda.

**Cada fix trae un test que FALLA con el código viejo.** ⚠️ Verificalo de verdad: revertir el
commit entero también revierte el test, y entonces no probaste nada. Revertí **sólo el archivo de
código**, dejando el test nuevo:
`git checkout <commit-anterior> -- <archivos de código>`.

**Baseline ANTES de tocar nada**, y comparación al final. El objetivo es **cero fallos NUEVOS**,
no cero fallos.

**Antes de dar un fix por terminado, grep de todos los call sites** del mismo patrón, y decir
explícitamente cuáles arreglaste y cuáles no.

⭐ **Cuando el mismo cálculo vive en N lugares, la respuesta por defecto no es arreglar los N: es
unificarlos en uno solo.** F3 creó `backend/fechas.py` y `frontend/src/utils/fecha.js`; F5 creó
`fx.costo_en_moneda_de_venta`, `twr.vs_inflacion_ar` y `fx._sql_medio`/`fx.punta_media`.

⭐ **Los guards contra la re-copia leen CÓDIGO, no números.** Un test de comportamiento pasa igual
aunque mañana alguien escriba la copia número 10 en otro archivo. Mirá
`backend/tests/test_un_solo_calendario.py`, `frontend/src/utils/bordeFresco.test.js` y
`backend/tests/test_dolar_medio_historico.py::UnaSolaCuentaGuardTest`.

⭐ **Si una regla tiene que vivir en dos medios** (SQL y Python, o backend y frontend), escribí
**un test que corra las dos sobre la misma tabla de casos**. F5 tiene dos ejemplos:
`test_la_version_de_SQL_y_la_de_PYTHON_dan_lo_mismo` y el guard de `monthlyReturnArs.test.js`
que lee `twr.py`.

### ⭐⭐ AUDITÁ TU PROPIA TANDA ANTES DE PEDIR EL DEPLOY

Es lo que más valor dio en F4 y F5 y **no lo cubre ninguna suite**. En F4 encontró 12 defectos
propios; en F5, **5 — y uno estuvo vivo en producción veinte horas**.

**Y cada ronda correctiva necesita su propia ronda.** En F5, la auditoría del código escrito para
corregir la primera auditoría encontró dos caídas más.

Qué mirar, en orden de rendimiento:

1. ⭐ **Cuestioná los SUPUESTOS, no releas el diff.** La auditoría que encontró el defecto grave
   de F5 no fue releer líneas: fue preguntarme *"¿de dónde sale de verdad este número?"*. La que
   releyó el diff encontró tres cosas menores y se le escapó la peor.
2. **De dónde salen los argumentos** de cada función que tocaste — no sólo la función.
3. **Los comentarios que quedaron describiendo el código de antes** (C12). En F5 dos de esos los
   había escrito yo mismo esa mañana.
4. **Tus propios tests**: ¿miden, o sólo verifican que aparezca un string? Marcá en la cabecera
   cuáles miden de verdad.
5. **Los bordes hostiles**: cero, negativo, nulo, texto donde va un número. En F5 eso encontró
   que una compra en `0` daba **la mitad del dólar**, y que un mes en `0` tiraba un endpoint
   entero.
6. **Mirá el dato de la fuente antes de confiar en él.** Ver la trampa 9 de abajo.

### Trampas concretas que ya costaron

1. **Ojo con dónde insertás una función en `main.py`.** Un helper metido entre el decorador
   `@app.post(...)` y su función hace que FastAPI **registre el helper como endpoint**.
   `/api/positions` habría quedado roto en producción. No lo cazó la suite.
2. **No testees contra tu propio criterio: testeá contra el motor real.**
3. ⭐ **Un test viejo puede tener razón.** Pasó cuatro veces. Leé el test antes de cambiarlo — y
   si su intención sigue siendo válida pero mira al lugar equivocado, **re-apuntalo, no lo
   borres**. En F5 pasó dos veces con guards estructurales cuya fórmula se había mudado.
4. **El primitivo no hereda tus guards** (F2 §5).
5. **Antes de explicar un test en rojo, mirá la hora.** De 21:00 a 00:00 ART la suite se pone
   roja sola. F3 arregló el código, no los tests: quedan **33 archivos** sembrando fechas con UTC.
6. ⭐ **Revertir con `git stash` no prueba nada** si ya commiteaste el arreglo.
7. ⭐ **Un test que sólo existe porque la función es nueva no mide nada.** Al revertir, falla con
   "X is not a function" — eso prueba que X es nueva, no que el bug existía.
8. ⭐ **Cuidado con el estado global entre tests.** Toda la suite comparte **UNA** base
   (`main.DB_PATH` lo fija el primer módulo que importe `main`). En F5, un
   `DELETE FROM fx_rates_daily` en un archivo nuevo **rompió a `test_advisor_plan`** — y sólo en
   la suite completa: aislado daba verde. Si tocás una tabla **global** (sin `user_id`), borrá
   **sólo tus propias filas**, y si dos tests comparten una fecha, **dale a cada uno la suya**.
9. ⭐ **REVISÁ EL INSTRUMENTO.** En F5, la fuente de cotizaciones tiene un día con **45 % de
   spread** (el MEP con compra 751,67 y venta 1.363,60) y **73 días con la compra por encima de
   la venta**. Usarlos habría movido el dólar de esas fechas **−22 %** — mucho peor que el
   problema que se venía a arreglar. **Antes de confiar en un dato externo, mirale la
   distribución y los extremos.** Y cuando dudes, **descartar y quedarte con el statu quo** es la
   opción segura.
10. ⭐ **Leé el área de preparación de git antes de commitear.** Restaurar un archivo para
    compararlo contra producción (`git checkout origin/main -- <archivo>`) **lo deja staged**: si
    commiteás a ciegas, subís una reversión de tu propio trabajo. Pasó en F5, lo cazó un
    `git status`.
11. ⭐ **`cat > archivo` sobrescribe.** En F5 destruí un archivo de tests con 13 casos creyendo
    que era nuevo. **`ls` antes de crear.**
12. ⭐ **`schema_pg.sql` es GENERADO**, no se edita a mano: `python3 scripts/mkschema.py`.

---

## 10 · ⚠️ Coordinación — esto ya rompió cosas dos veces

El usuario corre **varias sesiones sobre el mismo repo al mismo tiempo**.

**2026-09-08**: otra sesión deployó a `main` mientras esta rama tenía los mismos fixes sin
mergear. Mergear a ciegas habría pisado su solución con una peor.

**2026-09-09, durante F3**: otra sesión editaba `backend/main.py` en la misma carpeta. Un
`git add -A backend/` **se llevó su fix de seguridad adentro de un commit mío** que hablaba de
fechas — y sin su test. Estuvo a un push de ir a producción.

**2026-09-10/11, durante F4 y F5**: salió bien, y así fue. **(a)** worktree propio y limpio
creado desde `origin/main`, nunca la carpeta compartida; **(b)** `git fetch` antes de cada push y
comparación de las dos listas de archivos con `comm -12`; **(c)** commits **archivo por archivo**,
nunca `git add -A`. **Es el procedimiento, no la suerte: repetilo.**

Las cuatro reglas:

1. `git fetch && git log --oneline HEAD..origin/main` **antes** de mergear o pushear.
2. **Nunca `git add -A <dir>`** en una carpeta compartida.
3. **Leé tu propio diff buscando lo que NO escribiste.** El filtro que lo encontró: listar las
   líneas de código que no mencionan nada del tema de la tanda. Lo ajeno salta solo.
4. ⭐ **No midas la suite en un árbol con trabajo ajeno en curso.** La medición válida se hace en
   worktrees limpios, uno por rama:

```bash
git worktree add -b fix/f6-un-solo-motor /Users/nicolaspussetto/rendi-worktrees/f6 origin/main
cp backend/.env /Users/nicolaspussetto/rendi-worktrees/f6/backend/.env
```

Y borralos al terminar (`git worktree remove --force`), que se llevan la copia del `.env`.

**Si te llevaste algo ajeno: devolvelo, no lo deployés.**

---

## 11 · Estado del repo y cómo correr todo

**Deploy = push a `origin/main`.** No hay CI: Railway (backend) y Vercel (frontend) observan esa
rama. Pushear una rama cualquiera no deploya.

```bash
cd backend  && python3 -m pytest tests/ -q      # ~65 s. `tests/` NO está en la raíz del repo
cd frontend && npm test -- --run                 # ~2 s
cd frontend && npm run build                     # verificá que compile antes de pushear
```

⚠️ `npm test` necesita `node_modules`, y un worktree nuevo no lo tiene. No hace falta instalar:
`ln -s <repo-principal>/frontend/node_modules node_modules` alcanza (verificá que `package.json`
sea idéntico con `diff`). **Y borralo antes de commitear**: `.gitignore` ignora `node_modules/`
como directorio y un symlink NO matchea, así que aparece como archivo sin trackear.

**Verificar un deploy sin adivinar** — los dos exponen el SHA:

```bash
curl -s https://rendi.finance/version.json      # frontend (Vercel),  ~30 s
curl -s https://rendi.finance/api/health        # backend (Railway),  ~60-100 s
```

**El baseline no es un número que puedas copiar de un documento.** Depende del entorno (con o sin
`backend/.env` cambian resultados), de la hora (§9, trampa 5) y hasta de cuántos usuarios crea un
test. **Medí el tuyo antes de tocar nada.** Como referencia, en worktrees limpios al cerrar F5
(commit `10ea031f`): **backend 4.295 / 0**, **frontend 1.559 / 0**.

### Dónde está todo

| archivo | qué es |
|---|---|
| `audit/01-calculos.md` | **el plan.** 222 hallazgos por causa raíz, las 7 dependencias entre fixes, las 7 tandas. Leé este primero, es corto |
| `audit/_HANDOFF-TANDAS.md` | el histórico largo, tanda por tanda, con lo que costó cada una |
| `audit/_HANDOFF-F5.md` | el handoff anterior — F5 en detalle, por si necesitás el contexto de la cotización |
| `audit/01_calculos/1a-resumen.md` | tabla de las 94 divergencias con veredicto |
| `audit/01_calculos/1b-resumen.md` | tabla de los 128 hallazgos transversales |
| `audit/01_calculos/1a-*.md` (8) | detalle de 1A, uno por concepto. **Los de F6 son `1a-valuacion.md` (§6.1), `1a-rendimiento.md` (§6.2) y `1a-capital-aportado.md` (§6.5)** |
| `audit/01_calculos/1b-*.md` (6) | detalle de 1B, uno por tema. El de los índices es `1b-benchmarks.md` (§6.3); `1b-monedas.md` e `1b-inflacion.md` fueron F5 y `1b-borde.md` F4 |
| `audit/01_calculos/1a-evidencia.md` | MEDIDO vs DEDUCIDO vs ESTRUCTURAL, hallazgo por hallazgo |
| `audit/01_calculos/_grupos/*.md` | las 72 divergencias sin veredicto |
| `audit/00-mapa-sistema.md` | el mapa, 3,4 MB — **no lo leas entero, grepealo** |

⚠️ **Los informes tampoco son verdad: son hipótesis verificables.** F4 encontró un error
aritmético en `1a-rendimiento.md`: decía que la regla del asesor daría **−95 %** en su ejemplo y
el código da **+4 %**. Quien lo siguiera al pie de la letra publicaba una pérdida del 95 % sobre
alguien que ganó plata. **Recalculá los ejemplos del informe antes de implementarlos.**

⚠️ **El mapa es hipótesis, no verdad.** Se verificaron 290 de sus citas: ~53 tenían el número de
línea corrido y **5 afirmaciones eran sustantivamente falsas**. Si el código contradice al mapa,
**gana el código**.

⚠️ **Y lo mismo vale para este documento.** Las citas de la §6 se verificaron una por una el
2026-09-11; si no coinciden, buscá por **nombre de función**. **Incluidos los nombres de
archivo**: escribiendo la tabla de arriba, la versión anterior de este handoff inventó dos
informes que no existían y los cazó un `ls`. **Antes de mandar a alguien a un archivo, verificá
que esté.**

### Memoria del proyecto

Hay memoria persistente en
`~/.claude/projects/-Users-nicolaspussetto-Documents-trading/memory/`.

**Antes de escribir una sola línea:**

- `feedback_como_explicarle` — ⭐⭐ **cómo hablarle al dueño. No programa.** Sin jerga pero CON
  todo el detalle, nada de comandos sin explicar, separando "lo hago yo" de "lo hacés vos".
- `project_tandas_calculo` — estado vivo de las 7 tandas.
- `project_f5_cotizacion` y `project_dolar_medio_historico` — lo último que se hizo, con los
  5 defectos propios que encontró auditarlo.

**Trampas del método (todas mordieron):**

- `feedback_la_funcion_exacta_no_es_la_correcta` — ⭐ **la más importante para F6.**
- `feedback_el_fallback_del_helper` — leé qué devuelve un helper cuando el dato falta.
- `feedback_el_tc_tiene_que_cancelarse` — multiplicar por un TC y dividir por otro.
- `feedback_dietz_no_cubre_el_guard` — el primitivo no hereda tus guards.
- `feedback_el_test_viejo_tenia_razon` — pasó cuatro veces.
- `feedback_git_add_con_otra_sesion_viva` — la §10 de acá, resumida.
- `feedback_quien_mas_pasa_por_aca` — antes de una validación que rechaza.
- `feedback_revisar_el_instrumento` — antes de creerle a un dato externo.
- `feedback_antes_de_explicar_un_rojo_mira_la_hora`.
- `project_test_suite_state` — por qué el conteo de la suite no es una métrica.
- `project_f3_relojes_pendientes` — los ~40 relojes que F3 dejó.

---

## 12 · Lo que queda anotado y sin hacer (fuera de las tandas)

Todo esto está **medido y escrito al lado del código**, con el motivo de por qué no se tocó:

1. **El bug del reloj en el importador** (`importing/persister.py:1264`). Una línea. No se tocó
   porque abrir los ~40 relojes es decidir cuánto trabajo más meterle a F3.
2. **`POST /api/snapshots`** escribe la foto con el total calculado en el NAVEGADOR y `SnapshotIn`
   son tres números sueltos: no viaja cobertura, así que un precio viejo entra a la historia por
   esa puerta. Amortiguado (`apto=0`) pero su `total_value` se guarda. Cerrarlo **cambia el
   contrato con el frontend**.
3. **Las curvas publican `realized: 0` cuando no hay denominador** (`evolution.js:758`). Un 0 no
   es "no sé", es "no ganaste nada" — y el comentario de la línea 427 del MISMO archivo dice
   textual que eso es falso. Arreglarlo bien = que la serie lleve `null` y el gráfico dibuje un
   hueco: **es un cambio de forma de los datos.**
4. **`/api/snapshots` corta por filas y no por días**, igual que cortaba `/api/fx-rates`. Medido:
   **no hace daño** — su tope (3650) no es la restricción que manda (las fotos son ralas) y el
   frontend ya filtra por ventana de fechas real. Cambiarlo le sacaría puntos a tres callers.
5. **Dos formas viejas de tirar el Wrapped** con un mes fuera de rango (13, o guardado como
   texto). Preexistentes: revientan igual en el código de antes de F5.
6. **El `MEMORY.md` del proyecto está sobre el límite** (~28 KB contra 24,4) y **se carga
   incompleto**. Hay que acortar entradas del índice: el detalle vive en los archivos de tema.

---

*Handoff escrito al cerrar F5, el 2026-09-11, sobre el commit `10ea031f`.*
