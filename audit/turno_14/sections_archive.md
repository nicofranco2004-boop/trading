# Veredicto: `sections_archive` (POST /api/sections/archive)

**Refutado: NO.** Lente que decide: ninguna (las tres pasan). Gravedad: plata. Probabilidad: baja (hace falta un import, o una tanda del asesor sobre esa cuenta, en el mismo momento en que se archiva la sección).

## Qué hace el sitio
`backend/main.py:45352`. Dentro de una sola transacción:
1. `_tomar_turno(conn, uid)` (main.py:45369) → `UPDATE users SET tier=tier`.
2. Lee las posiciones de renta fija: `_positions_in_section` → `SELECT * FROM positions ...` (main.py:45321).
3. Guarda la foto de esas filas, en JSON, en `archived_positions` (main.py:45375).
4. Borra esas filas por id: `DELETE FROM positions WHERE user_id=? AND id IN (...)` (main.py:45383).
`sections_restore` (main.py:45395) vuelve a insertar el JSON tal cual, con los ids originales.

## Lente 1 — protección no vista: no alcanza
- El sitio pide turno, pero el intruso no. `import_confirm` (main.py:43930) no llama a `_tomar_turno` ni a `_foto_contable`, y en `importing/` no hay ningún `tier=tier` ni turno (lo verifiqué con grep). Escribe en `positions` desde dos lugares:
  - la venta del archivo: `_persist_sell_fifo` → `UPDATE positions SET quantity=?, invested=?, commissions=?` o `DELETE` (importing/persister.py:976–985), dentro de la transacción de main.py:43959 (load + dedup + persist_batch);
  - la reconstrucción FIFO: `_clear_old_state` → `DELETE FROM positions WHERE broker IN (...) AND asset=?` (importing/rebuild.py:708) seguido de un `INSERT` con ids NUEVOS (importing/rebuild.py:796), en su propia transacción (main.py:44062).
- El candado de la caja (`efectivo.tomar_saldo`) que usa el persister al mover efectivo es otro candado. El archivo no lo pide, así que los dos no se esperan.
- No hay índice único en `positions` más allá de la clave primaria (schema_pg.sql:2357 es un índice común): nada rechaza un restore duplicado.
- No hay «reclamo»: el `DELETE` del archivo no repite en su WHERE la cantidad leída y no cuenta las filas que borró.
- `adjust_position_ratio` no toma turno, pero excluye BOND/FUND y exige un split de yfinance: en la práctica no toca renta fija. `_edit_position_group` (PATCH /api/positions/group) no toma turno, pero no cambia la cantidad (sólo costo, TC, ticker y tipo); da una variante menor, con el costo viejo en el archivo.
- En **SQLite** el sitio está protegido: el turno toma la base entera y el import, en cuanto escribe, también. En **Postgres** el turno toma sólo la fila de `users`, que el import nunca escribe.

## Lente 2 — alcanzable: sí, y la ventana es ancha
Las dos cosas se piden por HTTP: el botón «archivar sección» de Renta Fija y la confirmación de un import (del usuario o de la tanda del asesor sobre su cliente, vía get_effective_user). En Postgres (READ COMMITTED) **leer no espera a nadie**, pero el `DELETE` sí espera a la fila que tiene tomada otro. Por eso la ventana no son los microsegundos entre el SELECT y el DELETE del archivo: dura **toda la transacción del import**, que procesa el archivo completo en `persist_batch` (segundos), o toda la reconstrucción FIFO.

## Lente 3 — consecuencia (supuesto el cruce)
Par concreto: **POST /api/sections/archive** (`BONO|USD`) contra **POST /api/imports/confirm** con un archivo que trae «Venta 600 AL30».

**Caso B, el que describía el mapeo:**
1. El import hace el UPDATE de AL30 de 1.000 a 400 nominales (persister.py:983) y todavía no hizo commit.
2. El archivo lee AL30 = 1.000 (lo último confirmado) y lo guarda así en el JSON (main.py:45375).
3. El DELETE del archivo espera, el import hace commit, el DELETE vuelve a evaluar `id IN (...)`, la fila sigue cumpliéndolo y se borra.

Queda: un archivo con 1.000 nominales y la operación «Venta 600» guardada. Al restaurar vuelven 1.000 nominales, y los 600 ya vendidos aparecen **dos veces**: como tenencia en Cartera y como venta en la ganancia realizada. Es la consecuencia que afirmaba el mapeo: **igual**.

**Caso A, peor de lo dicho:** si el cruce cae sobre la reconstrucción FIFO, que borra AL30 y lo vuelve a crear con ids nuevos:
1. El archivo guarda la fila vieja (1.000 nominales).
2. Su DELETE espera, y después no borra nada: esa fila ya no existe.
3. La fila nueva (400 nominales, id nuevo) **queda en Cartera**. El usuario recibe «archivé 1» y el bono sigue a la vista.
4. Si restaura, entra la fila vieja con su id original, que ya está libre, así que nada lo rechaza: **AL30 queda con 1.400 nominales** (400 + 1.000).

Nada lo tapa después:
- `_recalc_pnl_realized_from_ops` recalcula la ganancia mensual, no las tenencias.
- `_repair_monthly_chain` tampoco toca `positions`.
- Sólo un import posterior **del mismo activo** reconstruiría AL30 desde el historial. Eso es «tapado a veces», no siempre.

En pantalla: Cartera y el valor de la cuenta muestran nominales que no existen. Con AL30 a ~US$0,6 por nominal, 600 nominales son ~US$360 de más (caso B) y 1.000 son ~US$600 (caso A). El monto escala con la tenencia.

## Cómo medirlo
Tiene que correr **contra Postgres**: en SQLite el turno lo protege y el test daría verde aunque el bug exista.
1. Usuario con un broker y AL30 de 1.000 nominales (ya importado), más un import pendiente con «Venta 600 AL30».
2. Hilo 1: `POST /api/imports/confirm`. Se lo frena con un `_Cruce`-like (tests/test_dos_pedidos_a_la_vez.py) sobre el fragmento `UPDATE positions SET quantity=?, invested=?, commissions=?` usando `y_despues`: el import hace el UPDATE y espera un Event **sin hacer commit**.
3. Hilo 2: `POST /api/sections/archive {"section":"BONO|USD"}`. Se lo deja llegar a su SELECT (`FROM positions WHERE user_id IN`) y recién entonces se prende el Event.
4. Cuando terminan los dos: `POST /api/sections/restore`.
5. Esperado: AL30 = 400. Con el bug: **AL30 = 1.000** (caso B).
6. Variante del caso A: frenar en el `DELETE FROM positions WHERE user_id=? AND broker IN` de rebuild.py:708. Esperado: después del archivo no queda AL30 en `positions`. Con el bug quedan 400 recién archivados y, tras el restore, **1.400**.

Arreglo sugerido (no aplicado): que el import pida el turno (`_tomar_turno`) al abrir su transacción, en vez de agregar un reclamo sólo en este sitio. Ese mismo hueco es el de los otros 15 endpoints de la lista.
