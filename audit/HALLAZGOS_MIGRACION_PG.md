# Auditoría de los arreglos de migración a Postgres — 23/10/2026

**Rama auditada:** `claude/migracion-pg-oct`. El análisis se hizo sobre
`1aed8a45` (los 10 commits del informe) y las corridas finales sobre `4fe75445`,
que el autor agregó mientras yo auditaba: **sólo marca tres tests como «sólo
SQLite», no toca una línea de lo auditado**, así que ningún hallazgo cambia.
**Consigna:** intentar romperlos, no confirmarlos. **Nada publicado.**

> ✅ **ESTADO (23/10/2026):** los hallazgos **1, 2, 3, 6 y 7** los arregló la
> sesión de la migración **en esta misma rama** (verificado en el código, no
> por lo que dice el commit), y el 2 y su gemelo —el tope de alertas— quedaron
> los dos cubiertos poniendo la regla adentro del `INSERT`. El **4** no era un
> bug sino la respuesta a una pregunta del informe, y el **5** sigue como estaba
> porque está verificado que no es alcanzable.
>
> Hubo un segundo arreglo en paralelo (`arreglo/topes-pg`, de esta sesión de
> auditoría) que **se descartó por decisión de Nico**: hacía lo mismo dejando las
> cuatro copias de la reserva sin unificar, que es justo lo que la regla de
> propagación de este repo pide no hacer. Lo único que sobrevive de esa rama es
> esta corrección del informe y dos cosas anotadas: la nota de diseño del tope de
> alertas (abajo, en el hallazgo 2) y la regla de orden de candados del hallazgo 8.
>
> 🔴 **Y la auditoría de ESOS arreglos encontró un bug nuevo: el hallazgo 8.**
>
> 🔴 **Y UNA CORRECCIÓN MÍA, importante:** el hallazgo 2 decía que el tope de
> brokers era «una regresión de la migración, no una deuda vieja». **Eso está
> mal.** Con la máquina tranquila **también se escapa en SQLite** (5 de 5 con
> tope 1, seis corridas), o sea que **es un bug vivo en producción hoy**, no
> algo que aparezca al pasar a Postgres. Mis dos mediciones de SQLite dieron
> «1 y 1» porque las corrí con la suite grande ocupando la máquina, y eso
> escalonaba los hilos lo suficiente para tapar la carrera. El detalle está en
> la sección del hallazgo 2.
**Informe auditado:** `audit/AUDITAR_MIGRACION_PG.md`

**Instrumento:** un Postgres 16.2 propio (`pgserver`, sin docker), independiente
del de la sesión que hizo los arreglos, para que una medición no dependa de un
proceso ajeno. Toda afirmación de abajo que diga «medido» tiene su número y su
forma de repetirla al final.

---

## Veredicto en una línea por commit

| commit | qué arregla | veredicto |
|---|---|---|
| `c4f552d2` | el día de la cuota en 6 `UPDATE` de cobros | ✅ **los seis bien** — verificado por máquina, no a ojo. Faltaba quien lo vigilara; ahora hay guard. |
| `76816f3c` | los topes bajo carga | 🔴 **el tope de la cuota de IA NO aguanta** (el informe decía que sí) y **apareció un cuarto tope roto** que el grep no podía ver: el de brokers del plan. |
| `d4742484` | la caja de efectivo y la fila del mes | ✅ **los dos aguantan** — y el arreglo de la caja agrega un bloqueo mutuo nuevo (🟠), con mitigación probada. |

Los 5 primeros commits (conversiones mecánicas) no se auditaron en detalle: los
cubre la suite, que quedó igual que al cerrar.

---

## 🔴 HALLAZGO 1 — El tope de la cuota de IA no aguanta, y no es un tope: son cuatro

**Lo que decía el informe:** «cuota de IA · aguanta SÍ · se salva por chocar en
la fila del usuario». **Es falso.** La medición con dos pedidos dio un falso
negativo, y el motivo de por qué justo con dos sale bien está abajo.

### Medido contra Postgres real (errores: ninguno, resultados variados)

| escenario | tope | pedidos a la vez | **entraron** | consumido |
|---|---|---|---|---|
| chat, cuota vacía (Free) | 1 | 10 | **8** | 8 |
| chat, cuota en tope−1 (Pro) | 40 | 8 | **2** | 41 |
| análisis, cuota vacía (Free) | 1 | 8 | **5** | 5 |
| chat, 3 usuarios a la vez | 1 c/u | 12 | **4, 3 y 1** | 4, 3 y 1 |

Los mismos cuatro tests **pasan contra SQLite** (1 y 1, como corresponde). O sea:
no es el instrumento, es la migración.

**Y la medición es el camino de producción, no una maqueta.** La sonda llama a la
MISMA función que llama el endpoint (`quota.reserve_chat`, `main.py:40486` y
`41204`), desde conexiones distintas sacadas de `get_db()` — que devuelve una
conexión NUEVA por llamada (`main.py:655`). O sea que N hilos así son exactamente
lo que produce N pedidos HTTP simultáneos del mismo usuario. Y los números son VARIADOS (8, 2, 5,
{4,3,1}) con `errores=[]` en los cuatro, que es la señal de que se está midiendo
el código y no una conexión mal armada.

### El mecanismo, y por qué con dos pedidos parecía aguantar

`reserve_chat` cuenta y escribe en una sentencia:

```sql
INSERT INTO ai_usage_daily (...) SELECT ...
 WHERE (SELECT SUM(chat_count) ... ) < tope
 ON CONFLICT(user_id, date) DO UPDATE SET chat_count = chat_count + 1
 WHERE (SELECT SUM(chat_count) ... ) < tope
```

La idea de «chocan en la fila del usuario y Postgres los hace esperar» es cierta
a medias: **esperan, pero cuando siguen vuelven a contar con la foto vieja.** En
`READ COMMITTED` cada sentencia saca su foto al EMPEZAR; el que se quedó
esperando la fila la relee actualizada, pero la **subconsulta que suma** se
evalúa con la foto de antes. Entonces re-chequea el tope contra un número que ya
no existe y pasa igual.

Y es peor cuando **todavía no hay fila del día**, que es el caso de la primera
consulta de la semana: los diez cuentan 0, los diez intentan insertar, uno gana
el índice único y los otros nueve caen al `DO UPDATE` con la foto vieja. De ahí
los 8 de 10.

Con la fila ya existente y sólo dos pedidos, el segundo suele alcanzar a sacar
foto después del commit del primero y lo rechaza bien. **Por eso dos pedidos
dicen «aguanta» y ocho dicen «no».** La medición no estaba mal hecha: estaba
hecha justo en el punto donde el bug no se ve.

### No es un tope, son cuatro (y ninguno está protegido)

Misma sentencia, palabra por palabra, en `backend/ai/quota.py`:

| función | columna | qué deja pasar de más |
|---|---|---|
| `reserve_chat` | `chat_count` | consultas a Mervall-E |
| `reserve_analysis` | `analyses_count` | análisis de cartera |
| `reserve_listen` | `listen_count` | audio generado (la voz de Rendi) |
| `reserve_diag_dismiss` | `diag_dismiss_count` | sin costo: es de producto |

Los tres primeros **gastan plata de proveedor en cada pasada**. Una cuenta Free
con 1 consulta por semana sacó 8 llamadas al modelo en una ráfaga. No hace falta
mala intención: un cliente que reintenta, un doble clic o una pestaña duplicada
alcanzan.

`puede_dictar` NO está en la lista: su propio docstring dice que es un chequeo y
no una reserva, a propósito, y acota el peor caso por el tope de bytes. Eso está
decidido y documentado; no es este hallazgo.

### La respuesta a «¿hay otros topes que no encontré?»: no hay familias nuevas, pero son SEIS sentencias, no tres

El informe buscó con `grep "WHERE (SELECT COUNT"`. Lo repetí con AST —recorriendo
todos los `conn.execute(SQL, …)` con SQL literal de todo el backend, que ve
también los que cuentan con `SUM` o `COALESCE` y los que parten la sentencia en
varias líneas— y el barrido completo da **seis** topes que cuentan y escriben en
una sentencia:

| sitio | tope | ¿pide turno? |
|---|---|---|
| `ai/quota.py:610` | chat | 🔴 **no** |
| `ai/quota.py:669` | análisis | 🔴 **no** |
| `ai/quota.py:738` | escuchas | 🔴 **no** |
| `ai/quota.py:810` | descartes del diagnóstico | 🔴 **no** |
| `billing/trial.py:448` | pruebas gratis del mes | ✅ sí |
| `main.py:41595` | datos que la IA recuerda | ✅ sí |

Y un séptimo que el patrón pesca pero NO es un tope: `scripts/backfill_historical_mtm.py:459`,
un upsert de fotos en un script de backfill que corre solo.

O sea: la fila «cuota de IA» de la tabla del informe son **cuatro sentencias**, y
las cuatro están sin protección. No apareció ninguna forma distinta de armar un
tope que al grep se le haya escapado.

### El remedio, probado

Es el mismo que el commit ya usa en los otros dos topes: pedir el turno por
usuario ANTES de contar.

```python
_ps.turno_exclusivo(conn, <clave nueva>, int(user_id))
```

Puesto dentro del `with conn:` de las cuatro reservas, **los cuatro tests pasan
contra Postgres** (probado y revertido: no queda ningún cambio de código en la
rama). Por usuario y no global: dos personas no tienen por qué esperarse.

⚠️ La clave nueva **no puede salir de sumarle el uid a otra** — ver el hallazgo 7.

---

## 🔴 HALLAZGO 2 — El tope de brokers del plan tampoco aguanta, y es el que el grep no podía ver

Éste no estaba en el informe, y es la respuesta concreta a «si se arma de otra
forma, no lo vi». **Se arma de otra forma.**

Los tres topes del informe cuentan y escriben DENTRO de una sentencia, así que un
`grep "WHERE (SELECT COUNT"` los encuentra. El tope de brokers del plan se hace
cumplir **en dos pasos y en Python**:

```python
allowed, info = plan.check_broker_quota(conn, uid)     # cuenta (ai/plan.py:218)
if not allowed: raise HTTPException(403, …)
conn.execute("INSERT INTO brokers …")                  # escribe (main.py:5877)
```

Es el mismo bug con otra cara: entre contar y escribir entra cualquiera.

### Medido, corriendo el endpoint de verdad (`main.create_broker`)

| base | tope (Free) | pedidos a la vez | brokers que quedaron |
|---|---|---|---|
| **Postgres** | 1 | 5 | **2** y **4** |
| **SQLite** | 1 | 5 | **5, 5, 5, 4, 5 y 5** (seis corridas) |

🔴 **ACÁ ME EQUIVOQUÉ Y ES LA CORRECCIÓN QUE MÁS IMPORTA DEL INFORME.** La
primera versión de esta sección decía «SQLite dejó 1 y 1 → es una regresión de
la migración, no una deuda vieja». Las dos mediciones que decían «1 y 1` se
hicieron **con la suite grande de SQLite corriendo en la misma máquina**, y esa
carga escalonaba los hilos lo bastante para que la carrera no se diera. Repetidas
con la máquina tranquila, SQLite deja entrar a los cinco.

**No es una regresión de la migración: es un bug vivo en producción hoy.** Y el
motivo es la distinción que dejó pasar todo esto:

| forma del tope | SQLite | Postgres |
|---|---|---|
| contar y escribir en **UNA sentencia** | ✅ lo hace cumplir gratis | 🔴 no |
| contar **en Python** y escribir después | 🔴 **tampoco** | 🔴 no |

Lo que SQLite serializa son las ESCRITURAS. Cuando el conteo está en Python, la
decisión ya se tomó antes de escribir: los cinco leen cero, los cinco deciden
que pueden, y los cinco escriben de a uno, ordenaditos y de más.

👉 Consecuencia práctica: **`turno_exclusivo` no sirve para esta familia**, porque
no hace nada en SQLite a propósito. Para ésta va `turno_de_la_persona`, que toma
para escribir el renglón de esa persona —la única fila que seguro existe— y por
eso funciona en los dos motores. Medido con el arreglo puesto: **1 broker exacto,
6 de 6 en SQLite y 4 de 4 en Postgres.**

**Qué se escapa:** la pared del plan. Un Free con tope 1 se queda con 4 brokers y
después «grandfather» se los conserva (`check_broker_quota` no deja agregar más,
pero no saca los que ya están). No gasta plata de proveedor como la cuota de IA
— es el paywall, que es de dónde sale la plata que entra.

**El remedio es el mismo turno**, pedido antes del `check_broker_quota`, con
clave por usuario.

### Y su hermano, que NO medí

`check_alert_quota` (`ai/plan.py:268`, usado en `main.py:47352` por
`POST /api/alerts`) tiene la **forma idéntica**: cuenta en Python, después
inserta. Tope de alertas: 3 en Free.

**No lo medí**, y digo por qué en vez de suponerlo: ese endpoint sondea el precio
del símbolo por red antes de insertar, y para probarlo habría que simular ese
sondeo — un test que fuerza la condición puede tapar justo lo que falla. Lo que
sí está medido es su gemelo (el de brokers), y la forma es la misma línea por
línea, en los DOS motores. **Tratarlo como roto hasta que alguien lo mida.**

⚠️ **Y NO SE ARREGLA COPIANDO LA LÍNEA DEL DE BROKERS — por eso quedó sin
arreglar acá y no por olvido.** En el de brokers el turno va arriba porque entre
el conteo y el INSERT sólo hay lecturas locales. En el de alertas, en el medio
está `_ae.price_for_alert()`, que **sale por red a buscar el precio**. Poner el
turno arriba dejaría a SQLite con la base tomada para escribir durante toda esa
llamada: nadie más podría escribir hasta que Yahoo contestara. Cambiaríamos un
tope que se escapa por un «database is locked» para todos — un bug peor.

El arreglo necesita MOVER el chequeo: dejar el gate de arriba para el cartel del
403, y **volver a contar, con el turno, recién después del sondeo y justo antes
del INSERT**. Es un cambio de estructura en un camino de paywall, con su test —
no una línea.

¿Hay más? Los topes cuantitativos del plan son exactamente esos dos
(`brokers_max` y `alerts_max` en `PLAN_LIMITS`); los demás son `can_access`
(booleanos de funcionalidad, sin conteo) y `behavioral_tags_visible` (de
presentación, no escribe nada).

## 🟠 HALLAZGO 3 — El turno de la caja agrega un bloqueo mutuo nuevo

`efectivo.tomar_saldo` pide el turno **sólo cuando la caja todavía no existe**.
Eso deja dos candados distintos según el broker:

* broker **con** caja → candado de FILA (el `UPDATE` que no cambia nada)
* broker **sin** caja → candado de TURNO (`pg_advisory_xact_lock`)

Una transacción que toca DOS brokers los toma en distinto orden según cuál de
las dos cajas exista. Dos pedidos del mismo usuario que recorren los dos brokers
en orden opuesto se esperan cruzados.

**Medido: `deadlock detected` 3 de 3**, y el detalle de Postgres nombra el
candado nuevo:

```
Process 11880 waits for ExclusiveLock on advisory lock [16388,823471003,1,2]
```

(`823471003` es `TURNO_CAJA_DEL_BROKER`; el `1` es el uid.)

**Qué tan alcanzable es.** Hace falta el mismo usuario, dos pedidos simultáneos,
los mismos dos brokers, en orden opuesto, y uno de los dos sin caja. El par
realista existe: un broker en pesos (su caja la crea `/api/brokers` al nacer) y
su sub-broker `'<Padre> · USD'`, que **nace sin caja** (`_ensure_usd_sibling`
sólo inserta en `brokers`). Un dividendo acredita primero los dólares y después
descuenta la comisión en pesos (`dividendos.py:398-400`); una conversión de pesos
a dólares va al revés. Si se cruzan con la pata en dólares todavía vacía, 500.

**Esto NO es una regresión a favor del bug viejo.** Sin el turno esos dos pedidos
dejaban DOS cajas y la plata de una desaparecía del saldo. Un 500 ruidoso es
mejor que plata invisible. Pero se pueden tener las dos cosas.

**Mitigación, probada:** pedir el turno **SIEMPRE y ANTES del `UPDATE`**, no sólo
cuando la caja falta. Así todos los pedidos toman el mismo candado primero y no
queda orden que invertir. Medido: 3 de 3 sin error, y el test de los cinco
primeros depósitos sigue pasando. Costo: las operaciones de efectivo de UNA
persona se serializan entre sí — que es lo que el `UPDATE`-candado ya hacía
broker por broker.

✅ **ARREGLADO**, y el test dejó de ser `expectedFailure`:
`backend/tests/test_caja_orden_de_candados.py` ahora pasa y queda de guardián —
si alguien vuelve a condicionar el turno al `rowcount`, se pone rojo con el
`deadlock detected` en el mensaje.

### 🎉 Y de costado se cerró el PENDIENTE 2 de la migración

`VenderDolaresMientrasSeCompran` (dos conversiones simultáneas dando
`deadlock detected`) estaba declarado como «diagnosticado, SIN arreglar, va
aparte» en el informe original. **Se cerró sin que nadie lo tocara.**

| | antes | después |
|---|---|---|
| `test_dos_pedidos_a_la_vez.py` completo, Postgres | `deadlock detected` 3 de 3 reproducible | **24 pasados, 4 corridas seguidas, cero deadlock** |

Y el motivo es exactamente la regla de arriba: ahora la lectura del saldo pide el
turno por usuario **SIEMPRE y PRIMERO**, así que la conversión toma UN candado
antes de cualquier candado de fila y **no queda orden que invertir**. Los dos
bloqueos mutuos de esta migración —el que el arreglo de la caja introdujo y este
que venía de antes— tenían la misma causa, y una sola regla cerró los dos.

👉 Lo que esto deja como método: cuando aparece un bloqueo mutuo, antes de
diseñarle un arreglo propio conviene preguntarse si no es la misma inversión de
orden que otro que ya está en la lista. Acá eran el mismo, y se trataron como dos
problemas distintos durante un día entero.

---

## 🟡 HALLAZGO 4 — Eran TRES caminos que crean la caja sin `tomar_saldo`, no dos, y el tercero sí podía duplicarla

🔴 **CORRECCIÓN DE ESTE HALLAZGO (24/10/2026).** La primera versión decía: «sí
hay dos, y los dos están tapados por el índice único de `brokers`». **Estaba
incompleto, y el que faltaba era el único peligroso.**

Barridos todos los `INSERT INTO positions` que escriben `is_cash`, fuera de
tests:

| sitio | crea caja | ¿podía duplicarla? |
|---|---|---|
| `efectivo.mover` | sí | no — es la puerta |
| `POST /api/brokers` | sí, con saldo 0 | **no**: va junto al `INSERT INTO brokers`, y hay `UNIQUE (user_id, name)` en los dos esquemas |
| `_wallbit_ensure_broker` | sí, con saldo 0 | **no**: igual, sale temprano si el broker ya existe |
| `_insert_manual_position` | **no** | lo frena un `if p.is_cash: raise HTTPException(400, …)` |
| **`importing/persister.py`** (el sibling '· USD' del import) | **sí** | 🔴 **SÍ** |

**El tercero, que se me había escapado.** Era un «¿existe? → la inserto»:

    cash_exists = conn.execute("SELECT 1 FROM positions WHERE … is_cash=1 LIMIT 1").fetchone()
    if not cash_exists:
        conn.execute("INSERT INTO positions (… is_cash, invested) VALUES (?,?,?,1,0)")

Y no lo tapaba nada:
· no pasa por `efectivo.tomar_saldo`;
· **el índice único de `brokers` no aplica**: en ese punto el sibling '· USD' ya
  existe (`_ensure_usd_sibling` lo devuelve), así que no hay nada que frene al
  segundo;
· **`positions` no tiene NINGÚN índice UNIQUE**, ni en Postgres ni en SQLite
  (verificado en los dos esquemas);
· y cae del lado malo de la regla de esta auditoría: **lo primero que hace es
  LEER** para decidir, así que no lo hace cumplir ninguno de los dos motores.

Confirmar un import mientras entra el primer depósito al sibling dejaba DOS
cajas, y como todo lee «la más vieja», la plata de la segunda no la movía nadie
más.

✅ **ARREGLADO**: ese sitio va por `efectivo.asegurar_caja`, con
`backend/tests/test_caja_una_sola_puerta.py` como guardián.

### Por qué se me escapó, que es lo que queda de este hallazgo

El barrido fue `grep "is_cash" | grep -i "insert\|values"`: las dos palabras **en
la misma línea**. En el persister el INSERT ocupa varias líneas y el `is_cash`
cae en la segunda. Es el punto ciego que este repo ya tiene anotado para los
guardianes por texto, y lo pisé igual — en el mismo informe donde para los topes
sí usé AST sobre los `conn.execute`, que es lo que lo habría encontrado.

👉 **Un barrido por texto no cierra una pregunta del tipo «¿quedó algún otro
camino?».** Para esa pregunta hay que mirar la estructura del código, no su
texto. Lo encontró una de las siete lentes del barrido, no yo.

---

## 🟡 HALLAZGO 5 — El `ON CONFLICT` suma igual, con una diferencia: `NULL` → `0`

Construí la MISMA fila del mes por los dos caminos (la rama de «ya existe» y la
del `ON CONFLICT`, forzando la carrera) y comparé las **diez** columnas, en los
cuatro combinados de `direction` × `is_manual` × `native_amount`:

* `deposits`, `withdrawals`, `manual_*`, `manual_*_native`, `capital_final`:
  **idénticos** en los cuatro casos. ✅
* `capital_inicio`: **no se pisa**. ✅ (en el `DO UPDATE` no está, y el valor del
  INSERT perdedor se descarta)
* `pnl_realized`, `pnl_unrealized`: **no se pisan**. ✅

La única diferencia aparece **si la fila que ya estaba tiene las cuatro columnas
manuales en `NULL`**: el `ON CONFLICT` las pasa por `COALESCE(col,0) + 0` y las
deja en **0**, mientras que la rama del `UPDATE` no las toca y las deja en
`NULL`. Pasa igual en las dos bases, o sea que es de la sentencia y no de
Postgres.

**No le pasa a nadie hoy**, y lo verifiqué en vez de suponerlo: las cuatro
columnas nacen con `DEFAULT 0` en los dos esquemas (en SQLite entraron por
`ALTER TABLE … ADD COLUMN … DEFAULT 0`, que rellena las filas viejas con 0) y
**ningún lector distingue `NULL` de 0** — todos leen con `COALESCE`. Queda fijado
en un test para que, si la diferencia crece, se vea.

Y la carrera en sí: cinco depósitos simultáneos sobre un mes sin fila dejan
**una** fila, sin ningún 500, con `deposits`, `manual_deposits` y
`manual_deposits_native` sumando exacto. ✅

---

## 🟡 HALLAZGO 6 — El séptimo escritor del día de la cuota quedó sin unificar

`dia_de_la_cuota()` existe «para que ese día se calcule en UN lugar». Barridos
todos los `UPDATE users … quota_window_from` con SQL literal, son **ocho**:

```
main.py:29444   main.py:29593   main.py:37518   main.py:38230
billing/credits.py:395          billing/trial.py:411
ai/quota.py:414  (note_tier_change)          → los 7 usan dia_de_la_cuota()
billing/trial.py:628                        → usa datetime.now().date().isoformat()
```

`billing/trial.py:628` es el paso de la prueba gratis de Pro a Plus. Ya recibía
el día como parámetro —no estaba roto— y por eso no entró en la tanda. Pero hoy
es la **copia que queda**: el día que se tome la decisión de producto de pasar la
cuota al día argentino, cambiar `dia_de_la_cuota()` **no alcanza**, y el síntoma
sería que a la prueba gratis se le corre el corte un día respecto de todos los
demás. Es exactamente la forma de error que este repo tiene medida 28+ veces: un
arreglo correcto aplicado en N−1 lugares.

---

## 🟡 HALLAZGO 7 — La clave del turno de los facts se arma sumando el uid

`pgsesion` dice, textual: «dos topes distintos NO pueden compartir clave (se
bloquearían sin motivo)», y para eso tiene las claves juntas en un lugar. Pero
el tope de los facts no usa una clave de la lista:

```python
_ps.turno_exclusivo(conn, _ps.TURNO_TOPE_FACTS_POR_USUARIO + int(uid))   # main.py:41594
```

`823471002 + uid`. Para el usuario 1 eso da **823471003**, que es exactamente
`TURNO_CAJA_DEL_BROKER`.

**Hoy no choca, y lo medí en vez de deducirlo.** La etiqueta del candado que
imprimió Postgres termina en `…,1,2]`: ese último campo distingue la forma de UNA
clave de la de DOS, así que son espacios separados y `(823471003)` y
`(823471003, 1)` no se ven entre sí. La caja usa la forma de dos claves.

Pero es una trampa puesta: el día que alguien pase la caja a la forma de una
clave, o agregue `TURNO_... = 823471004` con la forma de una, el usuario 1 (o el
2) empieza a esperar un candado que no tiene nada que ver con lo suyo, sin error
y sin que nada lo diga. Ya existe la forma de dos claves y es la que hace lo que
este sitio quiere: `turno_exclusivo(conn, TURNO_TOPE_FACTS_POR_USUARIO, uid)`.

---

## 🔴 HALLAZGO 8 — El tope «sin tope» rompía el endpoint en Postgres

Encontrado al auditar los arreglos de los hallazgos 1 y 2 (23/10/2026), medido
contra Postgres real.

`plan.condicion_de_tope()` arma el `WHERE` que hace cumplir el tope adentro del
`INSERT`, y para los planes SIN tope preguntaba `? IS NULL` pasando `None` como
parámetro:

```sql
(? IS NULL OR (SELECT COUNT(*) …) < ?)
```

Postgres contesta:

```
IndeterminateDatatype: could not determine data type of parameter $1
```

**El mecanismo:** el driver manda `None` con el tipo SIN ESPECIFICAR, y en
`$1 IS NULL` Postgres no tiene de dónde inferirlo — no hay comparación, no hay
columna, nada. Con un entero manda un tipo concreto y por eso el caso con tope
anda. En SQLite pasa perfecto (`NULL IS NULL` no necesita que nadie infiera
nada), así que **la suite de SQLite queda verde con el bug adentro**.

| `limit` | la condición sola | el endpoint |
|---|---|---|
| `1` (Free) | TRUE ✅ | crea su primer broker ✅ |
| `0` | FALSE ✅ | — |
| **`None`** | 🔴 **revienta** | 🔴 el endpoint tira la excepción |

**El alcance, de `PLAN_LIMITS`, y está al revés de lo que uno querría:**

| | `brokers_max=None` | `alerts_max=None` |
|---|---|---|
| free | — | — |
| **plus** | — | 🔴 |
| **pro** | 🔴 | 🔴 |
| advisor / admin | 🔴 | 🔴 |

**El único que seguía funcionando era el Free.** Todo el que paga perdía crear
alertas, y el Pro perdía además crear brokers.

**El arreglo: no preguntarle a SQL algo que Python ya sabe.**

```python
if limit is None:
    return ("1=1", ())        # sin tope: la condición no filtra nada
```

Así desaparece el parámetro sin tipo y la sentencia dice lo que hace. Un
`::bigint` lo arreglaría en Postgres pero rompe SQLite.

⚠️ **Y por qué no lo agarró ningún test:** los tests del tope usan plan Free,
que es el único que NO se rompe. El caso «sin tope» no tenía ninguno. Un usuario
Pro creando tres brokers alcanza, y tiene la forma que uno quiere: verde en
SQLite, rojo en Postgres.

### Lo que sí aguantó de esos arreglos

* **`lastrowid` con `INSERT … SELECT … WHERE`**: no se rompe. El shim le pega el
  `RETURNING` igual (su regex matchea `INSERT INTO <tabla>` sin importar si sigue
  `VALUES` o `SELECT`), y con 0 filas insertadas devuelve None — pero los dos
  endpoints miran `rowcount` ANTES de tocar `lastrowid`, así que nunca usan un id
  viejo. Sin ese chequeo, en SQLite `lastrowid` después de un INSERT que no
  insertó nada devuelve el ANTERIOR: el endpoint habría contestado el id de un
  broker ajeno.
* **El conteo del chequeo y el del INSERT cuentan LO MISMO** en los dos topes: en
  brokers por construcción (comparten `SQL_BROKERS_QUE_CUENTAN`), en alertas
  verificado a mano (los dos cuentan sin filtrar por `active`). Si hubieran
  diferido, un usuario con alertas apagadas tendría la pantalla diciendo «podés»
  y la base diciendo «no».
* **`_reservar_un_slot` nunca recibe `limit=None`**: chat y análisis tienen número
  en los cinco planes, y escuchas y descartes tienen salida temprana. Si llegara,
  `< NULL` daría falso y bloquearía al que NO tiene tope — el mismo error del
  hallazgo 8 con otra cara.

### 🔒 La regla de orden de candados que queda de los dos arreglos

Un alcance, UN mecanismo, pedido SIEMPRE primero. Si dos caminos serializan «lo
de una persona» con candados de clase distinta —uno tomando el renglón de la
persona y otro un candado de aviso— una transacción que use los dos en orden
opuesto se cruza, y sale como `deadlock detected`. Es la misma forma del
hallazgo 3, y es el motivo por el que la caja y los topes del plan usan los dos
el candado de aviso y no uno cada uno.

---

## 🟡 HALLAZGO 9 — El primer cobro de Rebill deja DOS renglones en el libro, pero NO regala días

Viene del barrido de siete lentes: **tres lentes ciegas entre sí** lo encontraron
por separado, y las tres dijeron «paga 30 días y recibe 60». **El mecanismo que
describen es cierto; la consecuencia que le ponen, no.**

### Lo que es cierto, verificado leyendo

· El primer cobro **llega dos veces** —como `subscription.created` y como
  `payment.created`—, y eso no es una hipótesis: lo dice el propio código en
  `main.py:37818`, «con segundos de diferencia y **en cualquier orden**».
· Los dos avisos tienen un guardián que pregunta «¿esto ya se acreditó?», y
  **los dos preguntan sin candado**: `_rebill_activate` abre su `with conn:` en
  `main.py:37530` y lo CIERRA antes de preguntar en `37588` (el comentario lo
  dice: «fuera del with por simplicidad»), y `_rebill_record_payment` hace lo
  mismo (`with conn:` en `37807`, guardián en `37826`).
· La regla de la base que debería frenarlo **no lo frena**:
  `idx_credit_ledger_payment_dedup` es **PARCIAL**, con
  `WHERE payment_id IS NOT NULL AND source_subscription_id IS NOT NULL`
  (`main.py:3210`, `schema_pg.sql:2236`). La fila del alta nace con
  `payment_id` NULO a propósito, así que queda FUERA del índice y el segundo
  INSERT no choca con nada.

### Lo que MEDÍ, con las funciones reales del webhook y dos conexiones

| base | corridas | días acreditados | renglones de «payment» en el libro |
|---|---|---|---|
| SQLite (lo que corre en producción hoy), proceso frío | 10 | **30** siempre | **2** en 9 de 10 |
| Postgres | 10 | **30** siempre | **2** en 10 de 10 |
| SQLite, desfasaje ±5/10/20/40/80 ms | 11 | 30 | 1 |

**31 intentos, dos motores, 11 desfasajes: los días NUNCA se duplicaron.**

### Por qué no se duplican, que es la parte que importa

Los dos llaman a `get_credit_state` ANTES de que ninguno commitee, así que los
dos ven «no hay crédito» y los dos caen en el `else` de `credits.py:250`:

    new_active_until = now + period_days

Es un valor **ABSOLUTO, no una suma**: el segundo PISA al primero y queda en 30.
La rama que suma (`credits.py:228-236`, `total_days = remaining + period_days`)
sólo se activa si el segundo VE la ventana que el primero ya commiteó — y en ese
caso los guardianes lo agarran antes.

👉 **Lo que salva la plata es que la escritura es absoluta, no que los guardianes
funcionen.** Es importante decirlo así: el día que alguien convierta ese `else`
en una suma, los 60 días pasan a ser seguros y nada más cambió.

⚠️ **El riesgo que queda y NO pude forzar:** si el cruce cae de modo que el
guardián del cobro corra ANTES del commit del alta pero su `get_credit_state`
DESPUÉS, se activa la rama que suma y entran los 60 días. La ventana son unas
pocas sentencias entre `37826` y la llamada a `grant_payment_credit`. Existe en
el código; no la alcancé en 31 intentos.

### Veredicto

**Gravedad DATOS, no PLATA.** El libro de créditos es el registro de qué se
cobró, y queda con dos renglones de «payment» por un solo pago: mirando el libro
no se puede reconstruir cuánto entró. Vale arreglarlo. **No es «estamos regalando
un mes»**, y conviene que quede escrito así para que nadie lo trate como un
incendio.

La forma del arreglo que cubre el caso que el índice parcial no puede cubrir (el
`payment_id` nulo) es la misma que se usó para los topes del plan: la regla
adentro de la sentencia, `INSERT … SELECT … WHERE NOT EXISTS (…)` por
(usuario, suscripción, kind). La sonda con el barrido de desfasaje es el
guardián que hace falta para que la prueba no dependa del scheduler.

---

## 🔴 HALLAZGO 10 — «Fallar cerrada» era perder el candado, y lo agarró un test de tres semanas antes

El arreglo del turno por conexión (`4d969e10`) —hacer que se decida por LA
CONEXIÓN y no por una bandera del proceso— dejó un agujero nuevo durante dos horas, y lo
interesante es por qué.

`habla_postgres()` miraba SÓLO `type(conn).__module__` y contestaba «no» para
todo lo que no reconociera, con el argumento de que **fallar cerrada es más
seguro**. Pero un envoltorio de conexión —de registro, de pool, de medición— no
es un `pgshim.Connection`, así que contestaba «no es Postgres», **no pedía el
candado**, y los dos primeros depósitos simultáneos volvían a crear DOS cajas:
medido, una con 200 y otra con 300. El bug de las dos cajas, de vuelta.

### 🔑 La lección, que es general y vale fuera de esto

**«Fallar cerrada» no es seguro por definición. Hay que preguntarse QUÉ SE PIERDE
al fallar.** Si lo que se pierde es un candado que protege plata, fallar cerrada
es el PEOR resultado, no el más prudente.

Es la misma forma que la regla que este repo ya tiene medida sobre las listas de
exclusión («se ofrece salvo a…» dejó pasar plata dos veces) — sólo que ahí el
default abierto costaba plata y acá el default cerrado costaba plata. **La regla
no es «cerrá» ni «abrí»: es mirá qué se pierde.**

### Quién lo agarró, y la atribución correcta

Lo agarró **`backend/tests/test_dos_pedidos_a_la_vez.py`**, que **no lo escribió
ninguna de las dos sesiones de esta tanda**: nació en `61282c09`, el **3 de
octubre de 2026** —tres semanas antes—, en «fix(efectivo): dos pedidos iguales a
la vez ya no mueven la plata dos veces». Su envoltorio `_Conexion` nació en ese
mismo commit, para otro motivo.

👉 **Un test viejo, escrito para otra cosa, agarró una regresión que ninguno de
los dos autores vio.** Es la regla de «el test viejo tenía razón», y de paso el
argumento concreto para no borrar un test porque «es viejo y molesta»: la próxima
vez no hay quien avise.

### El arreglo

Tres pasos, y cada uno lo pidió un bug distinto (`5e7fcd0a`):
1. ¿Es SQLite? `isinstance` para la conexión directa **y**
   `hasattr(conn, "total_changes")` para la envuelta — un envoltorio no es una
   `sqlite3.Connection` pero sí reenvía atributos, y `total_changes` lo tiene
   sqlite3 y no psycopg. Preguntar por algo que el objeto REENVÍA, y no por su
   tipo, es lo único que sobrevive a un envoltorio.
2. ¿Es Postgres directo? Por el módulo.
3. Ninguna de las dos: ahí sí vale la bandera del proceso, pero antes el objeto
   tiene que PARECER una conexión (`callable(conn.execute)`) — sin eso, un `None`
   contestaba «sí habla Postgres».

Medido con una sonda de las CINCO situaciones en los dos motores: **5/5 y 5/5**.

---

## 🔴 HALLAZGO 11 — Dos operaciones a la vez: en Postgres UNA SE PIERDE, y el usuario ve «guardada»

Del barrido de siete lentes (lo vieron dos lentes como «el arreglo de
`_update_monthly_flow` no se propagó a su hermana», y una tercera como «la
segunda contesta guardada y no guarda nada»). **Verificado y medido el
28/10/2026 contra Postgres real: las tres describían el mismo bug, y la
consecuencia real es peor que la que le pusieron.**

### El punto de partida: la hermana sin propagar

`_update_monthly_pnl_realized` (`main.py:13746`) y `_update_monthly_flow`
(`main.py:13793`) son hermanas: **47 líneas de distancia, misma tabla, misma
fila**. A la segunda se le aplicaron las dos mitades del arreglo de concurrencia
de `d4742484`; a la primera **ninguna**:

| | `_update_monthly_flow` | `_update_monthly_pnl_realized` |
|---|---|---|
| suma | **en la base** (`deposits = deposits + ?`) | 🔴 **en Python** y escribe el absoluto |
| `ON CONFLICT` | **2** | 🔴 **0** |
| candado | — | 🔴 ninguno |

Son **30 llamadores de producción**: 16 en `importing/persister.py` y 14 en
`main.py` (ventas, operaciones a mano, cupones, importador).

### Medido: SQLite 3/3 · Postgres 4/4, los dos consistentes

| caso | SQLite | Postgres |
|---|---|---|
| dos operaciones a la vez, la fila del mes YA existe | 180 ✅ | 180 ✅ |
| depósito + operación a la vez | dep 1000 · pnl 150 · cap 1150 ✅ | igual ✅ |
| venta + operación a la vez | 250 ✅ | 250 ✅ |
| **dos PRIMERAS operaciones del mes** | 100 ✅ | 🔴 **40 o 60** |

Y el cuarto caso, medido aparte porque el número no alcanzaba:

    SQLite    operaciones=[40.0, 60.0]   suma=100   global=100   ✅
    Postgres  operaciones=[40.0]         suma=40    global=40    🔴  err=[]

**Sólo queda UNA fila en `operations`.** No es que el total del mes quede corto:
**la operación no está en el historial**, y las dos llamadas volvieron normal —
el usuario vio «guardada» las dos veces.

### 🔑 El mecanismo, y es el que generaliza

`create_operation` (`main.py:20706`):

    INSERT INTO operations …                      ← la operación entra
    try:
        _update_monthly_pnl_realized(…)           ← acá revienta: UNIQUE del mes
        _recalc_pnl_realized_from_ops(conn, uid)
    except Exception as ex:
        log.error("Recalc tras create_operation falló: %s", ex)   ← SE TRAGA
    conn.commit()
    return dict(row)                              ← contesta ÉXITO

· En **SQLite** el error no inutiliza la transacción: el `commit()` confirma el
  INSERT de la operación. Se pierde sólo el total del mes, y el recálculo lo
  rearma.
· En **Postgres** la sentencia que falla **aborta la transacción**, el `commit()`
  se vuelve un ROLLBACK **y se descarta todo lo del pedido** — el INSERT de la
  operación incluido. Y el endpoint contesta igual.

👉 **El `ON CONFLICT` que falta no causa un 500: causa una pérdida silenciosa**,
porque hay un `except` que traga y un `commit()` después.

### Lo que la lente erraba, y conviene saberlo

Las dos lentes decían que se perdía **la suma del mes** y que el recálculo no la
salvaba. **Al revés:** el recálculo SÍ la salva —`_recalc_pnl_realized_from_ops`
rearma el total desde `SUM(operations)`, y en `READ COMMITTED` esa consulta ve lo
que la otra transacción commiteó—. Medido por dos puertas (operación a mano y
venta): la suma perdida **no se reproduce**. Lo que no se puede salvar es la fila
que nunca se creó.

⚠️ **No se midió la puerta del importador** (los 16 llamadores del persister).
Ahí no corre `_recalc_pnl_realized_from_ops` después, así que podría comportarse
distinto. Queda abierto.

### El barrido del patrón: 28 candidatas

`except` que traga + `commit()` después + respuesta de éxito. Barrido con AST
sobre todo el backend (no grep): **28 funciones tienen esa forma.** Las de
caminos de usuario o de plata:

    main.py:20706  create_operation()      ← MEDIDO roto
    main.py:20784  update_operation()      ← la hermana: editar una operación
    main.py:12139  update_position()
    main.py:7130   post_snapshot()
    main.py:4537   register()
    main.py:4404   _registrar_ingreso()
    main.py:26692  registrar_uso()
    alerts_engine.py:1091  evaluate_alerts()
    snapshots_job.py:1354  run_daily_snapshot()

**`register()` puede explicar una de las 12 fallas que quedan:**
`test_email_verification::test_register_email_already_registered_returns_409_with_code`
está rojo en Postgres, y una de las lentes decía «registrarse con un email que ya
existe da 500 en vez del mensaje». Misma forma, mismo archivo, mismo síntoma. **No
medido** — es la candidata más barata de confirmar.

🔴 **Las 28 son CANDIDATAS, no hallazgos.** La forma no prueba el bug: el `except`
puede no envolver nada que toque la base, el error puede no ser alcanzable, o el
`commit` puede ser de otra conexión. De las 28 se verificó UNA.

### El arreglo son DOS cosas, no una

1. `ON CONFLICT` en el `INSERT` de `_update_monthly_pnl_realized` y pasar la suma
   a la base, como su hermana. Eso tapa este caso.
2. **El `except` que traga tiene que dejar de contestar éxito.** Con sólo (1) las
   otras 27 candidatas siguen pudiendo descartar un pedido en silencio. Un
   `except` alrededor de SQL en Postgres necesita además decidir qué hace con la
   transacción: o `rollback()` explícito y un error al usuario, o no tragar.

### La sonda

Cuatro casos, las dos puertas, y el cuarto imprime las filas de `operations` para
distinguir «se perdió el total» de «se perdió la operación». Está en el
scratchpad de la auditoría como `test_pnl_del_mes_dos_pedidos.py`.

⚠️ **Y un aviso sobre cómo NO escribirla:** la primera versión hacía el depósito
llamando a `_update_monthly_flow` directo. Eso deja la suma sin su detalle en
`flujos_a_mano`, el recálculo posterior la borra, y el test daba **rojo por culpa
del andamio**. El depósito tiene que ir por `main.cash_flow`. Un test que fuerza
una condición puede tapar lo que falla — o inventar una falla que no existe.

---

## 🔴 HALLAZGO 12 — «Tomar el turno» es una protección que sólo existe en SQLite, y la usan 24 lugares

Barrido pedido por Nico el 28/10/2026, a partir del hallazgo del depósito borrado
(ver `efectivo.caja`). **No es un bug: es una causa con 24 sitios colgados de
ella.**

### El mecanismo, que el propio código ya dice

`_tomar_turno` (`main.py:18448`) es **una sola sentencia**:

    conn.execute("UPDATE users SET tier=tier WHERE id=?", (uid,))

· En **SQLite** eso toma la base ENTERA para escribir: cualquier otro pedido que
  escriba cualquier cosa espera. Es una serialización de verdad.
· En **Postgres** traba **sólo esa fila de `users`**, así que únicamente espera
  quien también la escriba.

Y esto no es una deducción de la auditoría: está escrito en el docstring de
`_foto_contable`, con todas las letras — «En Postgres sólo traba la fila del
usuario: pone en fila a las puertas de borrado entre sí (y al login de ese
usuario) … hace falta un turno por usuario que tomen todos los que escriben las
cuentas». **Lo que faltaba era la lista de quiénes no lo toman.** Es ésta.

### Los 24 usos, y no todos son iguales

| | cuántos |
|---|---|
| lo piden **SIEMPRE**, al entrar a la función | **11** |
| lo piden **sólo en una rama** (un `if`, un `for`, un `try`) | **13** |

Los 11 incondicionales son las puertas de borrado y la foto contable
(`_delete_one_movement`, `_delete_operation_cascade`,
`_delete_position_cascade`, `_delete_asset_history_cascade`,
`_delete_manual_*_cascade`, `_undo_manual_delete`, `_borrar_datos_de_brokers`,
`_exigir_broker_existente`, `_ensure_usd_sibling`, `_foto_contable`).

Los 13 condicionales lo piden sólo si pasa algo: `update_broker`,
`bond_cashflow`, `bond_pago`, `dividendos_cobro`, `create/update/delete_monthly`,
`close_futuro`, `undo_delete_operation`, `undo_delete_asset_history`,
`import_mappings_save`, `sections_archive`, `sections_restore`.

### 🔴 Los 16 que escriben las cuentas y NO toman el turno

De los **34 endpoints que escriben las cuentas** (`monthly_entries`,
`flujos_a_mano`, `snapshots`), **16 no llegan nunca al turno** — o sea que pueden
caer dentro de la ventana de cualquiera de las puertas de borrado:

    /api/operations                          create_operation      ← MEDIDO: pierde una operación (hallazgo 11)
    /api/operations/{oid}                    update_operation
    /api/monthly/sync-unrealized             sync_unrealized       ← una lente lo marcó: «se come un depósito»
    /api/imports/confirm                     import_confirm
    /api/imports/recalc-pnl                  import_recalc_pnl
    /api/snapshots                           post_snapshot
    /api/brokers/reconcile-cash              broker_reconcile_cash
    /api/plazos-fijos                        create_plazo_fijo
    /api/plazos-fijos/{pid}/cobrar           cobrar_plazo_fijo
    /api/advisor/group-op/{batch_id}/undo    advisor_group_op_undo
    /api/admin/delete-snapshot               admin_delete_snapshot
    /api/admin/cleanup-future-snapshots      admin_cleanup_future_snapshots
    /api/admin/recompute-snapshots-netdep    admin_recompute_snapshots_netdep
    /api/admin/repair-caja-1415              admin_repair_caja_1415
    /api/admin/repair-interes-pf             admin_repair_interes_pf
    /api/admin/repair-user-history           admin_repair_user_history

Dos de esos 16 ya tienen un hallazgo propio en este informe o en el barrido de
las siete lentes, y **uno está medido**: `create_operation` (hallazgo 11). Los
seis de `/api/admin/repair-*` son de reparación masiva, que es el peor momento
para que alguien escriba al mismo tiempo.

### ⚠️ Y el límite de este barrido, que es parte del resultado

El «18 que sí lo toman» es un **techo, no un número**. Mi barrido es de
alcanzabilidad (¿se puede llegar al turno desde este endpoint?), y eso **no es lo
mismo que tomarlo**. El falso positivo que lo prueba:

    /api/cash/flow  →  _pata_de_la_moneda  →  _ensure_usd_sibling  →  _tomar_turno

`cash_flow` aparece «con turno», pero sólo lo toma si hay que CREAR el sub-broker
'· USD'. Un depósito o retiro normal en pesos no pasa por ahí — y eso está
medido: en la sonda del depósito borrado, el retiro por `/api/cash/flow` quedó
bloqueado en `Lock/advisory`, o sea en el candado del efectivo que pide `caja()`,
**no** en la fila de `users`. Si el turno lo hubiera tomado, habría esperado ahí.

👉 **Un grafo de llamadas dice «puede», no «hace».** Para cada uno de los 18 hay
que mirar si la llamada es incondicional — y 13 de los 24 usos están dentro de un
`if`.

### Qué cambia esto para el pasaje

El único de los 24 que quedó con una protección de verdad es el del efectivo, y
no por el turno: porque `caja()` pide un `pg_advisory_xact_lock` por usuario
(`a80b43b7`). **Los otros 23 siguen confiando en el turno.** Mientras corra
SQLite no se nota; el día que se prenda Postgres, 16 endpoints que escriben las
cuentas pueden caer en medio de un borrado.

El arreglo que el propio código propone —«un turno por usuario que tomen todos
los que escriben las cuentas»— es uno, no 24: la misma forma que cerró las dos
cajas, el bloqueo mutuo de las conversiones y el del depósito borrado.

---

## ✅ Lo que ataqué y aguantó

* **Los seis `UPDATE` de cobros, verificados por máquina y no a ojo.** El guard
  nuevo lee el código, cuenta los `?` hasta el de `quota_window_from` y mira qué
  expresión le toca. Los seis: cantidad de parámetros = cantidad de `?`, y el día
  cae en la posición del día. Ninguno cruzado.
* **El cruce al revés** (que el día caiga en la posición del `tier`, dejando al
  usuario con el plan `'2026-10-23'`): tampoco.
* **`dia_de_la_cuota()` devuelve lo mismo que antes**: `date.today().isoformat()`,
  el día del reloj del proceso, igual que el `date('now','localtime')` que
  reemplazó. No se cambió a qué día apunta. ✅
* **El guard de relojes no se movió**: el commit agregó un `date.today()` (en la
  función nueva) y sacó otro (en `note_tier_change`), así que `ai/quota.py` sigue
  en 11 y la suite queda igual.
* **`note_tier_change` hace lo mismo**: misma sentencia, mismo `try/except`, el
  día sale de la función nueva.
* **La forma de dos claves del turno existe en Postgres.** Era una duda real:
  `pg_advisory_xact_lock(a, b)` sólo está definida para enteros de 32 bits, y si
  el driver mandaba los parámetros con otro tipo Postgres contesta «function does
  not exist» y el camino de la caja revienta. Probado contra Postgres real: corre.
* **La caja de efectivo aguanta**: cinco primeros depósitos simultáneos (300, 200,
  100, 50, 25) dejan **una** caja con **675**. Sin el arreglo quedaban dos filas.
* **La fila del mes aguanta**: cinco depósitos simultáneos, una fila, cero 500,
  las tres columnas de flujo sumando exacto.
* **El turno se pide antes de contar en todos los caminos que llegan a esos dos
  topes.** `_atomic_insert_fact` es el único escritor de `ai_user_facts` fuera de
  tests, y `_start_tx` el único camino al tope de pruebas gratis.
* **El tope de facts activos no se puede cruzar por la puerta de atrás**: no hay
  ningún camino que REACTIVE un fact (`is_active=1`); sólo se desactivan.
* **El turno de verdad cubre la transacción.** `pg_advisory_xact_lock` se suelta
  al cerrar la transacción, así que con una conexión en autocommit no protegería
  nada. El shim abre con `autocommit=False` (`pgshim.py:883`) y nadie cambia el
  nivel de aislamiento en todo el backend: `READ COMMITTED`, que es el que hace
  falta para que contar DESPUÉS de pedir el turno lea lo vigente.
* **Espera larga por el turno**: el de pruebas gratis usa una clave GLOBAL (sin
  uid), así que todas las altas de prueba del mundo se serializan. Adentro del
  turno hay dos INSERT y nada de red, así que no es un problema; queda anotado
  por si algún día entra una llamada lenta ahí.

---

## 🟡 Por qué un cruce de parámetros podría haberse escapado (y no es un bug: es un agujero de cobertura)

`admin_billing_grant_comp` (`main.py:29593`) es el `UPDATE` con **más columnas**
de los seis —y por lo tanto el de más riesgo de cruce— y **no tenía ningún
test**. De los seis sitios, ninguno tenía un test que AFIRMARA que el día cayó en
su columna: el único test del repo que compara `quota_window_from` contra hoy
(`test_quota_window_corte.py:206`) cubre el cron de vencimiento, que es un
séptimo camino.

Por eso el guard nuevo lee el código en vez de correr los seis caminos: dos son
webhooks y dos endpoints de admin, y un test que no existe no protege nada. El
guard tiene el punto ciego de siempre —no ve un orden armado en runtime, tipo el
`sets.append()` de `_update_monthly_flow`— y eso está dicho en su docstring.

---

## Estado de las dos bases

Las dos corridas completas son sobre `4fe75445` (la punta), con mis tres
archivos de test adentro.

| base | resultado |
|---|---|
| SQLite | **6.993 pasados · 0 fallas · 0 bloqueos** — igual que al cerrar el informe |
| Postgres | **18 fallas · 6.970 pasados · 133 salteados · 13 xfail** |

De esas **18 fallas, 5 son mías** (los hallazgos 1 y 2, rojos a propósito), así
que **quedan 13 preexistentes**. El informe cerró en 17, y el commit `4fe75445`
convirtió 3 de ellas en salteadas: 17 − 3 = 14 esperadas, medí 13.

**La que falta es flakeo por carga de la máquina, no un arreglo.** En una corrida
anterior con la máquina ocupada salieron 18 preexistentes en vez de 13, y las que
aparecían y desaparecían son las de los cupones
(`test_cupones_bandeja`, `test_cupones_bandeja_azar`). Es el mismo efecto que el
`conftest` ya tiene documentado: cuando la corrida tarda el doble, un test
legítimo pasa más de 6 s con la transacción abierta y Postgres lo mata. **El
número de fallas de Postgres todavía depende de la carga de la máquina**, y eso
conviene saberlo antes de usarlo como criterio de «verde».

Las 13 preexistentes están repartidas en **12 archivos distintos** —cobertura sin
precios, alertas que no toman la base, poda del arranque, cupones, verificación de
mail, la caja al arrancar— o sea que son fallas VARIADAS, no un instrumento mal
armado. Entre ellas estaba `VenderDolaresMientrasSeCompran`, el `deadlock` que el
informe dejaba diagnosticado y aparte — **ése ya no está**: se cerró de costado
con el turno pedido siempre y primero (ver el final del hallazgo 3).

Los **5 rojos nuevos** contra Postgres **son los hallazgos 1 y 2**: cuatro del
tope de la cuota de IA y uno del tope de brokers del plan. Son tests que marcan
bugs que no están arreglados, y se dejan rojos a propósito — se ponen verdes con
el turno. Los mismos 16 tests dan **16 verdes contra SQLite**, que es lo que
prueba que miden la migración y no el instrumento.

### ⚠️ «La suite de Postgres está en N» todavía no es un criterio

Las cuatro corridas completas de Postgres de esta tanda, con su commit, su
duración y lo que dieron:

| corrida | commit | duró | fallas | qué tan limpia |
|---|---|---|---|---|
| v1 | `c48c1b8f` | 476 s | 22 | con el barrido de 7 lentes al lado |
| v2 | `a80b43b7` | **899 s** | 14 | 🔴 **compartió 415 s con la v3** |
| v3 | `a80b43b7` | 569 s | 16 | 🔴 **compartió 415 s con la v2** |
| v4 | `b5ab559e` | 513 s | 12 | máquina quieta |

**La v2 y la v3 son el MISMO commit y dieron 14 y 16** — pero no son dos
muestras independientes: se solaparon **415 de los 569 segundos de la v3**
(v2: 11:07:35→11:22:34 · v3: 11:15:38→11:25:07, y entre `a80b43b7` 11:05:32 y
`5e7fcd0a` 11:32:20 no hubo ningún commit). Así que ese par NO prueba que el
número varíe solo: prueba que **dos suites corriendo a la vez se estorban**, que
es otra cosa.

👉 **Y la duración es el delator.** La v2 tardó **899 s contra los 513 s de la
v4**: 1,75× más, con el mismo motor y casi el mismo código. Un número de fallas
sin su duración al lado no se puede interpretar — si la corrida tardó el doble,
la máquina estaba ocupada y el número está inflado.

**La evidencia de que el número se mueve con la carga es otra, y está medida:**
la auditoría corrió DOS veces el **mismo commit** (`4fe75445`), una con la máquina
ocupada y otra quieta → **18 y 13 fallas**. Ésa sí es una comparación de dos
corridas independientes del mismo código.

**Las dos mediciones limpias que tenemos coinciden:** la v4 (12, máquina quieta)
y la de la auditoría (13 preexistentes, máquina quieta, commit anterior). La
diferencia es exactamente un test —`VenderDolaresMientrasSeCompran`, que se
cerró— y nada más se movió.

**Los tres tests que entran y salen según la máquina**, identificados por nombre:

    tests/test_cupones_bandeja.py::BonoImportadoTest::test_la_posicion_dice_que_su_nominal_ya_es_el_vivo
    tests/test_cupones_bandeja_azar.py::CobrosDeBonosAlAzarTest::test_al_azar
    tests/test_ritmo_de_envio.py::test_una_rafaga_de_mails_sueltos_no_congela_la_app_ni_se_saltea_la_fila

El de `ritmo_de_envio` mide con reloj de pared y pasa 3/3 aislado; los dos de
cupones aparecen y desaparecen sin que nada del código cambie.

#### La consecuencia operativa

**Mientras esos tres sigan así, «la suite de Postgres está en N» no sirve como
criterio para decidir el pasaje.** Dos caminos, y hay que tomar uno:

1. **Hacerlos deterministas** (el de `ritmo_de_envio` no puede medir con reloj de
   pared; los de cupones hay que ver qué les falta), o
2. **sacarlos de la cuenta y decirlo**: «N, más 3 que dependen de la máquina».

Y en los dos casos, **la medición tiene que llevar su duración al lado**: una
corrida que tardó 1,75× lo normal no es una medición, es una medición con la
máquina ocupada. El `conftest` ya tiene documentado este mismo problema para sus
tres relojes, y con los números al lado (`tests/conftest.py:114-121`):

    #1  46 fallas · 68 s     #2  49 fallas · 133 s     #3  46 fallas · 71 s
                                 ↑ las 3 extra: IdleInTransactionSessionTimeout

«Nada corría en paralelo: era la máquina. Cuando se pone lenta y la corrida tarda
el doble, un test LEGÍTIMO pasa más de 3 s con la transacción abierta y Postgres
lo mata.» Es el mismo efecto visto desde el otro lado, y ya estaba medido en este
repo: **la corrida que tardó el doble trajo 3 fallas de más.**

#### Y la forma del error, que es la que se repitió todo el día

El par «v2 dio 14 y v3 dio 16 con el mismo código» parecía la prueba perfecta y
no lo era, porque las dos corridas no eran independientes. Es la quinta cara del
mismo descuido de esta tanda:

| se midió | y se afirmó sobre |
|---|---|
| dos pedidos simultáneos | un tope bajo carga |
| un conteo de comillas par | el anidado de los bloques |
| un total de fallas que cierra | de dónde salía cada falla |
| una corrida | una trayectoria de cuatro |
| dos corridas que se solapan | la variabilidad del número |

**Las cinco son un agregado o una muestra puesta en lugar de la estructura.** Es
el error más barato de cometer y el más caro de no ver: en los cinco casos el
número cerraba perfecto.

---

## Lo que NO toqué (respetado del informe)

* El horario de la cuota (día UTC vs día argentino): decisión de producto.
* La columna de orden en `import_batches`: cambio de esquema.
* ~~El `deadlock detected` de dos conversiones simultáneas
  (`VenderDolaresMientrasSeCompran`)~~ — **ya no está**: resultó ser la MISMA
  inversión de orden que el bloqueo mutuo del hallazgo 3, y la misma regla cerró
  los dos. Ver el final del hallazgo 3.
* El patrón «borrar e ignorar el error» de los 118 archivos de test.
* No se tocó una línea de código de producción. Las dos pruebas de remedio
  (hallazgos 1 y 3) se aplicaron, se midieron y se revirtieron: `git status` sólo
  muestra los tres archivos de test nuevos.

---

## Qué quedó en el repo

| archivo | qué vigila |
|---|---|
| `backend/tests/test_auditoria_pg_carrera.py` | los arreglos bajo carga: el tope de IA (4 rojos = hallazgo 1), el tope de brokers (1 rojo = hallazgo 2), la caja, la fila del mes y la equivalencia de las diez columnas |
| `backend/tests/test_quota_window_orden_de_parametros.py` | que el día caiga en su columna en los 8 sitios, y que nadie vuelva a meter el reloj adentro del SQL |
| `backend/tests/test_caja_orden_de_candados.py` | el bloqueo mutuo del hallazgo 3 (`xfail` hasta que se arregle) |

## Cómo repetir cada medición

```bash
cd backend
# Postgres propio, sin docker. DEJAR EL PROCESO VIVO: si muere, se lo lleva.
python3 - <<'PY'
import pgserver, pathlib, time
srv = pgserver.get_server(str(pathlib.Path("/tmp/pgaudit/pgdata")))
print(srv.get_uri())        # el host viene como PARÁMETRO, no en la URL
while True: time.sleep(30)
PY
# con el host de arriba y una base propia:
DSN="user=postgres dbname=rendi_audit host=<el socket>"

DATABASE_URL="$DSN" python3 -m pytest tests/test_auditoria_pg_carrera.py \
    -p no:randomly --timeout=90 -q          # 5 rojos = hallazgos 1 y 2
python3 -m pytest tests/test_auditoria_pg_carrera.py -p no:randomly -q
                                            # los 16, en SQLite: VERDES
DATABASE_URL="$DSN" python3 -m pytest tests/test_caja_orden_de_candados.py \
    -p no:randomly --timeout=90 -q -rx      # xfail: deadlock detected
```

Si una corrida da muchas fallas que dicen todas lo mismo, es el instrumento.
Y si algo se queda colgado, mirar `pg_stat_activity` antes de culpar al código:
una conexión en `idle in transaction` retiene el turno y cuelga a todo lo que
venga después.
