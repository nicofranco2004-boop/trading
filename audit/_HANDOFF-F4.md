# Handoff — la auditoría de cálculo de Rendi, y por qué la próxima es F4

> **Si sos la sesión que arranca: leé esto entero antes de tocar código.** Es autocontenido.
> No hace falta abrir el mapa de 3,4 MB ni los 14 informes de detalle salvo que el trabajo
> te lleve ahí, y en ese caso este documento te dice a cuál.

---

## 0 · Lo primero, en treinta segundos

Rendi tiene una auditoría de cálculo con **222 hallazgos**, que se ejecuta en **siete tandas**
(F1 a F7). **F1, F2 y F3 están hechas y deployadas.**

➡️ **La que sigue es F4, «los guards que ya existen, en todos los lectores».**

Y F4 tiene una particularidad que hay que entender antes de empezar: **le quedan tres puntos y
los tres están frenados a propósito**, esperando una decisión del dueño. No son difíciles de
programar — son difíciles de *decidir*, y la decisión no es técnica. **Tu primer trabajo en F4
no es escribir código: es hacerle tres preguntas al dueño de una forma que pueda contestar.**
La §6 te dice cuáles y cómo.

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
| **F4** | Los guards que **ya están escritos** pero no llegaron a todos los lectores | ➡️ **LA QUE SIGUE** — 3 de 6; los 3 que faltan **esperan una decisión del dueño** |
| **F5** | **Una sola cotización y una sola política de faltantes** | 🟡 lo más grave ✅ deployado (el CER); el resto pendiente, 4 a 6 días |
| **F6** | **Terminar las migraciones abiertas.** Un solo motor por concepto | ⬜ pendiente, 1 a 2 semanas |
| **F7** | **El modelo de datos.** Es diseño, no arreglos | ⬜ proyecto aparte |

---

## 5 · Las tres que ya están hechas

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

---

## 6 · ➡️ F4 — «los guards que ya existen, en todos los lectores»

**Es toda la causa C7.** Y es la tanda de mejor relación entre resultado y esfuerzo, porque
**el código de los guards ya está escrito**: sólo no llegó a todos los lectores.

### Qué es un "guard" acá

Una cota de cordura. El código de Rendi tiene varias, escritas cada una cuando algo explotó:
"un valor de mercado que se va más de ×50 del costo no se publica", "un monto no finito no
entra", "un porcentaje sobre una base ≤ 0 no es 0, es indefinido". El problema no es que falten:
es que **cada una vive en uno o dos lectores y no en los demás**.

### Los 3 que ya están hechos y deployados

| guard | qué frena |
|---|---|
| `trustMktValue` con 0 y negativos | una posición valiendo **menos que nada**, o NaN |
| `_FINITE_BOUND` en `PositionIn` | `invested = 1e308` entrando y llegando a `capital_final` |
| Validación de broker existente en `positions` | fila huérfana → pérdida fantasma de −US$ 9.999 |

### ⛔ Los 3 que quedan — **NO los "arregles" sin decidirlos**

En los tres, o el código contradecía al plan, o la decisión es de producto. **Verificados contra
el código el 2026-09-09**, o sea que estas citas están vivas:

---

**1 · Edad máxima del precio en `read_last_prices`**

`backend/snapshots_job.py:705` devuelve el último precio guardado **sin mirar cuándo se guardó**.
Alimenta el snapshot nocturno, el Dashboard y el libro del asesor.

El arreglo ya existe **en otro lado**: `backend/main.py:24069-24085` (`register_trade`) rechaza
un precio de más de **48 horas**, con este comentario textual:

> *"Frescura: get_prices rellena huecos con el last-known SIN límite de edad (para valuar la
> cartera está bien; para escribir el costo de un lote 'de HOY' no)."*

⚠️ **Leelo dos veces: el comentario dice que para valuar la cartera está bien.** O sea que el
código *contradice al plan de la auditoría*, a propósito y por escrito. La regla de 48 h existe
deliberadamente **sólo para escribir costos**. La tabla `asset_last_price` tiene columna
`updated_at`, así que el dato para decidir está disponible.

**Lo que hay que decidir:** a qué edad un precio viejo deja de ser mejor que no mostrar nada.

---

**2 · Guard de denominador en el número titular del Dashboard**

`frontend/src/utils/evolution.js` tiene un guard que usa el **pico histórico** de la cartera como
denominador estable: si la cartera llegó a US$ 100k y después retirás US$ 70k, el capital
aportado puede quedar chico o negativo y el porcentaje **explota a 90 %+ artificialmente**.

Pero ese guard es para el **% realizado**, no para el retorno total, y **el Dashboard no tiene el
pico a mano**. O sea: no es propagar un guard, es **diseño nuevo sobre el número más visible de
la app**.

**Lo que hay que decidir:** si el hero del Dashboard debe cambiar de denominador, y a cuál.

---

**3 · Cota de plausibilidad en la ganancia realizada**

Hoy **no hay ninguna**. Medido: **+188.566,67 %** en una sola fila de `operations`, sobre un
lote cuyo costo entero es US$ 106 (venta declarada en una moneda distinta a la del lote → cae a
todos los lotes y no convierte el precio de salida).

La asimetría es el hallazgo: **el valor NO realizado está protegido por una banda de ×50; el
realizado no tiene absolutamente nada.** Y existe `MAX_PNL_TO_COST = 10` en
`frontend/src/utils/assetPnl.js:45` con su espejo en `backend/main.py:38339` — pero sólo lo
aplican la ficha de activo y el libro del asesor, **no el motor de la venta**.

⚠️ Hay un test que verifica que las dos copias del espejo no diverjan
(`test_advisor_composition.py`). Si tocás una, tocá la otra.

**Lo que hay que decidir:** desde qué porcentaje un resultado deja de ser creíble, y qué se hace
cuando lo supera (no publicarlo, o rechazar la venta al escribirla).

---

### 🔑 Tu primer trabajo en F4: hacer estas tres preguntas

**El dueño no programa.** Decide sobre el producto, la plata y los usuarios. Las preguntas
tienen que poder contestarse **sin leer código**, y cada una tiene que venir con lo que pasa en
cada opción. Leé `~/.claude/CLAUDE.md` y `memory/feedback_como_explicarle` antes de escribirlas.

Un ejemplo de cómo NO preguntarlo y cómo sí:

> ❌ *"¿Le pongo un `max_lag_days` a `read_last_prices` o dejo el fallback?"*
>
> ✅ *"Si el precio de un activo no se actualiza hace días, ¿preferís que la cartera lo siga
> mostrando al último precio conocido (aunque sea viejo), o que diga 'sin precio'? Mostrarlo
> viejo mantiene el total completo pero puede estar desactualizado; decir 'sin precio' es
> honesto pero deja huecos en el total. ¿A partir de cuántos días te parece que ya no sirve:
> 2, 5, o 15?"*

**Sugerencia de orden:** la (1) es la más acotada y la más fácil de contestar. La (3) cambia
números publicados. La (2) es diseño y conviene dejarla para el final.

### Y una asimetría que está bien y NO hay que "arreglar"

`/api/positions` rechaza un broker inexistente; `/api/operations` **no**. Ahí el contrato lo
tolera deliberadamente y hay un test que lo fija
(`test_currency_fallback_to_usd_if_broker_unknown`). **Hay un test que congela esa asimetría a
propósito**, para que quien la toque tenga que decidirla en vez de romperla de refilón.

---

## 7 · Las tandas que vienen después

### F5 — «una sola cotización, una sola política de faltantes» *(4–6 días)*

Lo más grave ya está deployado: **la serie CER estaba caída** (la fuente devuelve 404 mientras
`/inflacion` y `/uva` del mismo host devuelven 200) y **todos los bonos CER ajustaban por 1,00
cuando el factor real es 7,7× a 37,6×**. Se sirve con UVA, que da el mismo ratio porque el BCRA
la actualiza *por* CER — verificado a 0,25 % contra los factores medidos. Ver
`memory/project_cer_via_uva`.

Lo que queda:

- **El tope de `/api/fx-rates` Y el fallback mudo** (van juntos). El endpoint limita por
  **filas**, no por días: el frontend pide 3.650 días, el backend responde
  `ORDER BY date DESC LIMIT 3650`, y la serie tiene ~5.685 filas desde 2011 → la ventana arranca
  en 2016 y **toda fecha anterior cae al dólar de hoy sin avisar**. Medido: una venta de 2013 se
  dibuja **160× mal**. Poner un `WHERE date >= ?` arregla el síntoma; el fallback mudo es la
  causa y sigue vivo para cualquier otro hueco.
- Unificar **punta venta vs. punta media** entre `fx_rates_daily` y la valuación viva (explica un
  escalón sistemático de **0,74 %**).
- Decidir y aplicar **una** política de faltantes: precio ausente, TC ausente, índice no
  publicado. **Es decisión de producto antes que código.**
- **6 sitios restan inflación en pesos a retornos en dólares** y ninguno mira la moneda. Y hay
  que pasar moneda a los índices: hoy `vs_sp500_pct` **cambia de signo** con sólo tocar el
  selector de moneda.

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
5. **Antes de explicar un test en rojo, mirá la hora.** De 21:00 a 00:00 hora argentina la suite
   se ponía roja sola (los tests sembraban con un reloj y verificaban con otro). Arreglado en
   F3, pero el reflejo sirve igual. Y **el conteo de la suite completa no es una métrica**:
   agregar un test que crea un usuario lo mueve sin tocar código.

---

## 10 · ⚠️ Coordinación — esto ya rompió cosas dos veces

**El usuario corre varias sesiones sobre el mismo repo al mismo tiempo.**

**2026-09-08:** otra sesión deployó a `main` mientras esta rama tenía los mismos fixes sin
mergear. Se detectó al chequear antes de mezclar; mergear a ciegas habría pisado su solución con
una peor.

**2026-09-09, durante F3:** otra sesión editaba `backend/main.py` en la misma carpeta. Un
`git add -A backend/` **se llevó su fix de seguridad adentro de un commit mío** que hablaba de
fechas — **y sin su test**, que vivía en otro archivo. Estuvo a un push de ir a producción.

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

**Verificar un deploy sin adivinar** — los dos exponen el SHA:

```bash
curl -s https://rendi.finance/version.json      # frontend (Vercel),  ~30 s
curl -s https://rendi.finance/api/health        # backend (Railway), ~100 s
```

**El baseline no es un número que puedas copiar de un documento.** Depende del entorno (con o sin
`backend/.env` cambian 6 resultados) y hasta de cuántos usuarios crea un test. **Medí el tuyo
antes de tocar nada.** Como referencia del 2026-09-09, en worktrees limpios: `origin/main`
**4.113 / 0** y con F3 **4.132 / 0**.

### Dónde está todo

| archivo | qué es |
|---|---|
| `audit/01-calculos.md` | **el plan.** 222 hallazgos por causa raíz, las 7 dependencias entre fixes, las 7 tandas. **Leé este primero, es corto** |
| `audit/_HANDOFF-TANDAS.md` | el histórico largo, tanda por tanda, con lo que costó cada una |
| `audit/01_calculos/1a-resumen.md` | tabla de las 94 divergencias con veredicto |
| `audit/01_calculos/1b-resumen.md` | tabla de los 128 hallazgos transversales |
| `audit/01_calculos/1a-*.md` (8) | detalle de 1A, uno por concepto |
| `audit/01_calculos/1b-*.md` (6) | detalle de 1B, uno por tema. **`1b-borde.md` es el de F4** |
| `audit/01_calculos/1a-evidencia.md` | MEDIDO vs DEDUCIDO vs ESTRUCTURAL, hallazgo por hallazgo |
| `audit/01_calculos/_grupos/*.md` | las 72 divergencias sin veredicto |
| `audit/00-mapa-sistema.md` | el mapa, 3,4 MB — **no lo leas entero, grepealo** |

> ⚠️ **El mapa es hipótesis, no verdad.** Se verificaron 290 de sus citas: ~53 tenían el número
> de línea corrido y **5 afirmaciones eran sustantivamente falsas**. Confirmá cada cita con
> `grep` antes de apoyarte en ella. **Si el código contradice al mapa, gana el código.**
>
> Y lo mismo vale para este documento: `main.py` se movió ~700 líneas desde que se escribieron
> los informes. Las citas de la §6 se verificaron el **2026-09-09**; si no coinciden, buscá por
> nombre de función, no por número de línea.

### Memoria del proyecto

Hay memoria persistente en
`~/.claude/projects/-Users-nicolaspussetto-Documents-trading/memory/`. Las que importan para F4:

- `project_tandas_calculo` — estado vivo de las 7 tandas
- `project_f3_un_solo_calendario` — lo último que se hizo y qué dejó abierto
- `feedback_como_explicarle` — ⭐ **cómo hablarle al dueño. Leelo antes de escribir las tres preguntas**
- `feedback_git_add_con_otra_sesion_viva` — la §10 de acá, resumida
- `feedback_quien_mas_pasa_por_aca` — antes de una validación que rechaza
- `feedback_buscar_el_guard` — antes de una reparación masiva
- `project_test_suite_state` — por qué el conteo de la suite no es una métrica
