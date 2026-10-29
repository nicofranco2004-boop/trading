# Veredicto: `_borrar_datos_de_brokers` (main.py:6162) — NO refutado (solo en Postgres)

## El sitio
Lo usan `delete_broker` (DELETE /api/brokers/{bid}?force=true, main.py:6587) y "Limpiar broker" (`_wipe_broker_data`, main.py:30271). Pide el turno (`_tomar_turno`, main.py:6177) y después hace tres cosas:
1. `_dividendos.al_borrar_cuentas` (dividendos.py:543): lee los dividendos anotados desde la bandeja en las cuentas que se borran y, si la cuenta en pesos sobrevive, le devuelve la comisión (`efectivo.mover`, dividendos.py:564).
2. Una sentencia `DELETE ... WHERE broker IN (...)` por tabla, en el orden de `BROKER_POR_NOMBRE` (main.py:6033): primero **positions**, después operations, monthly_entries, etc.
3. El que llama borra la fila del broker.

## Lente 1 — protección: no lo tumba
- **El intruso no pide el turno.** `import_confirm` (main.py:43930) abre su transacción grande en main.py:43958 y llama a `persist_batch`. En las 400 líneas del endpoint no hay ningún `_tomar_turno`, y tampoco lo hay en `importing/*.py`. Tampoco escribe en `users`.
- **El único candado que comparten es el de la caja.** `persist_batch` mueve efectivo con `_adjust_broker_cash` = `efectivo.mover` (main.py:13915 y 42240). `mover` toma el turno de la caja (`pgsesion.turno_exclusivo(TURNO_CAJA_DEL_BROKER, uid)`, que es un `pg_advisory_xact_lock`, un candado que se suelta solo al terminar la transacción) y además traba la fila de efectivo del broker. Ese candado **no frena** el cruce: lo empeora, porque hace que el borrado espere en el medio, con decisiones ya tomadas sobre una foto vieja.
- No hay ningún índice único ni CHECK que ate `positions.broker` u `operations.broker` a la tabla `brokers`: van por nombre, sin clave foránea.
- En SQLite no pasa nada: el `_tomar_turno` del borrado toma la base entera y espera a que termine el import. **El riesgo es exclusivo de Postgres.**

## Lente 2 — alcanzable: sí
Los dos son pedidos HTTP del mismo usuario: confirmar un import del broker X y borrar o limpiar X, por ejemplo desde dos pestañas. La ventana no es de microsegundos: es **toda la transacción del import** (segundos, porque persiste fila por fila con recálculos), y el borrado termina esperando adentro de ella.

## Lente 3 — consecuencia (suponiendo el cruce)

### Par concreto A: filas huérfanas
El par es `import_confirm` sobre "Balanz" contra `delete_broker` de "Balanz" (o "Limpiar broker"). El archivo trae la compra de un ticker nuevo, NUEVO.

1. El import compra NUEVO. `mover(Balanz, -costo)` traba la fila de efectivo de Balanz y el turno de caja, y después hace `INSERT positions(NUEVO, Balanz)`. Todavía no confirmó nada.
2. El borrado toma el turno de `users` (el import no lo tiene) y pasa `al_borrar_cuentas`. Al llegar a `DELETE FROM positions WHERE broker IN ('Balanz')` (main.py:6188) choca con la fila de efectivo trabada y **espera**.
3. El import confirma.
4. El DELETE de positions sigue, pero sólo con las filas que veía cuando empezó, que es como funciona Postgres en su modo normal (READ COMMITTED: cada sentencia mira una foto tomada al arrancar). **La posición NUEVO no estaba en esa foto y queda.** Las sentencias siguientes (operations, monthly_entries) toman una foto nueva y sí se llevan lo del import. Se borra el broker.

**Qué queda escrito:** una fila en `positions` (NUEVO, con cantidad e invertido) bajo un broker que ya no existe, sin ninguna operación que la respalde. Ninguna pantalla suma posiciones de brokers que no existen (lo dice el comentario de main.py:5410). Por eso hoy queda invisible. **Pero "Limpiar broker" existe justamente para volver a importar después**, y re-importar re-crea "Balanz" con ese mismo nombre (main.py:30230). En ese momento la posición huérfana reaparece y se suma a la que trae el import nuevo: tenencia y valor de NUEVO duplicados en Cartera y en el Dashboard. `_recalc_pnl_realized_from_ops` no la tapa, porque sólo recompone meses a partir de operations. Tampoco `_repair_monthly_chain`.

Si el borrado gana la carrera sin esperar, porque el import todavía no tocó la caja, el import falla más adelante en el chequeo "Broker no encontrado" (persister.py:~1100) y se deshace entero, que es lo seguro. Pero si en ese momento el import ya pasó su último chequeo de broker, confirma todo debajo de un nombre muerto (posiciones, operaciones, caja nueva creada por `mover`).

### Variante B: la comisión devuelta dos veces (la forma que nombraba el mapeo)
Se borra **sólo** "Balanz · USD" con `delete_broker`; la cuenta en pesos "Balanz" sobrevive. Al mismo tiempo se importa un archivo de Balanz con un dividendo que ya estaba anotado desde la bandeja con una comisión de $1.000.

1. El import ya tiene el turno de caja, tomado por sus movimientos anteriores.
2. El borrado lee el dividendo (dividendos.py:552) y queda esperando en `mover(Balanz, +1000)`.
3. El import corre `reemplazar_por_importado` (persister.py:1138 → dividendos.py:439). Lee el mismo dividendo, que sigue visible. `deshacer_efectivo` devuelve los +$1.000 a Balanz y saca el neto de "Balanz · USD". Borra la operación y confirma.
4. El borrado sigue con lo que ya había decidido: **+$1.000 otra vez**.

Resultado: la caja en pesos queda $1.000 de más, y "Balanz · USD" puede quedar con una caja negativa huérfana si `mover` la re-crea.

**Comparado con el mapeo:** el DÓNDE es correcto. El CUÁNTO queda más acotado de lo que sugiere "plata en tres formas":
- Las filas huérfanas que sí se forman son **posiciones** (y caja). Operations y monthly_entries se salvan, porque sus DELETE corren con una foto nueva.
- La doble comisión necesita borrar la "· USD" sola mientras se importa justo ese dividendo.
- No encontré la tercera forma.

Gravedad: **plata**, latente. Queda escondida hasta que se re-crea el broker o se mira la caja en pesos.

## Cómo medirlo (contra Postgres, con el estilo de tests/test_dos_pedidos_a_la_vez.py)
- **A:** usuario con broker "Balanz" (ARS, con caja de 1.000.000). Hilo 1: `import_confirm` de una sesión con la compra de NUEVO. Con el envoltorio de cruce, se frena **después** del `INSERT INTO positions` del persister (fragmento "INSERT INTO positions") hasta que el hilo 2 mande su `DELETE FROM positions`. Hilo 2: `DELETE /api/brokers/{id}?force=true`. Al final, `SELECT COUNT(*) FROM positions WHERE user_id=? AND broker='Balanz'` tendría que dar **0** y va a dar **1** (NUEVO). Después: `POST /api/brokers` "Balanz", re-importar el mismo archivo y ver que NUEVO tiene el **doble** de cantidad.
- **B:** anotar desde la bandeja (`POST /api/dividendos/cobro`) un dividendo en Balanz con `comision_pesos=1000`. Hilo 1: `import_confirm` con ese dividendo, frenado justo después de su primer `mover`. Hilo 2: `DELETE /api/brokers/{id de "Balanz · USD"}?force=true`. Lo esperado es que la caja de Balanz suba **+1000**; lo que va a salir es **+2000**.
