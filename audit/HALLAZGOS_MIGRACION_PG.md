# Auditoría de los arreglos de migración a Postgres — 23/10/2026

**Rama auditada:** `claude/migracion-pg-oct`. El análisis se hizo sobre
`1aed8a45` (los 10 commits del informe) y las corridas finales sobre `4fe75445`,
que el autor agregó mientras yo auditaba: **sólo marca tres tests como «sólo
SQLite», no toca una línea de lo auditado**, así que ningún hallazgo cambia.
**Consigna:** intentar romperlos, no confirmarlos. **Nada publicado.**
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
| **Postgres** | 1 | 5 | **2** y **4** (dos corridas) |
| SQLite | 1 | 5 | 1 y 1 |

Igual que el hallazgo 1: SQLite lo hacía cumplir gratis y Postgres no. **Es una
regresión de la migración, no una deuda vieja.**

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
línea. **Tratarlo como roto hasta que alguien lo mida.**

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

Queda anotado en `backend/tests/test_caja_orden_de_candados.py`, como
`expectedFailure` (sale `xfail` hoy; el día que se aplique la mitigación sale
`XPASS` y hay que sacarle el decorador).

---

## 🟡 HALLAZGO 4 — Sí quedan dos caminos que crean la caja sin pasar por `tomar_saldo` (pero no pueden duplicarla)

Era la pregunta explícita del informe. Barridos todos los `INSERT INTO positions`
con `is_cash`, fuera de tests, son cuatro:

| sitio | crea caja | ¿puede duplicar? |
|---|---|---|
| `efectivo.py:205` (`mover`) | sí | no — es el arreglo |
| `main.py:5887` `POST /api/brokers` | sí, con saldo 0 | **no**: va junto al `INSERT INTO brokers`, y el esquema de Postgres tiene `UNIQUE (user_id, name)` (verificado en `schema_pg.sql`), así que el segundo pedido se cae con error de integridad |
| `main.py:44042` `_wallbit_ensure_broker` | sí, con saldo 0 | **no**: igual, sale temprano si el broker ya existe |
| `main.py:11716` `_insert_manual_position` | **no** | lo frena un `if p.is_cash: raise HTTPException(400, …)` tres líneas antes |

**Conclusión: la respuesta a la pregunta del informe es «sí hay dos, y los dos
están tapados por el índice único de `brokers`, no por el turno».** Es una
dependencia que conviene saber: si alguien le saca el `UNIQUE (user_id, name)` a
`brokers`, se vuelven a abrir los dos caminos.

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
armado. Entre ellas está `VenderDolaresMientrasSeCompran`, el `deadlock` que el
informe deja diagnosticado y aparte: coherente con lo declarado.

Los **5 rojos nuevos** contra Postgres **son los hallazgos 1 y 2**: cuatro del
tope de la cuota de IA y uno del tope de brokers del plan. Son tests que marcan
bugs que no están arreglados, y se dejan rojos a propósito — se ponen verdes con
el turno. Los mismos 16 tests dan **16 verdes contra SQLite**, que es lo que
prueba que miden la migración y no el instrumento.

---

## Lo que NO toqué (respetado del informe)

* El horario de la cuota (día UTC vs día argentino): decisión de producto.
* La columna de orden en `import_batches`: cambio de esquema.
* El `deadlock detected` de dos conversiones simultáneas
  (`VenderDolaresMientrasSeCompran`): diagnosticado y aparte. **Ojo: el hallazgo
  2 es OTRO bloqueo mutuo, con otro mecanismo (el candado nuevo de la caja).**
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
