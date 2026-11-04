# Veredicto: `update_broker` (PUT /api/brokers/{bid}) — NO refutado

**Lente que decide: consecuencia (pasó protección y alcanzable).**

## Par intruso
- Sitio: `update_broker` (renombre), backend/main.py:6219. Pide el turno en main.py:6395, re-chequea el nombre en 6396-6403 y reescribe el nombre en todas las tablas en 6426-6441 (`NAME_KEYED_TABLES`, en este orden: positions, operations, monthly_entries, import_batches, import_normalized_tx…).
- Intruso: `import_confirm` (POST de confirmación de import), main.py:43930.
  - LEE el nombre del broker: `load_session_for_confirm` → importing/pipeline.py:1515 (`broker = r["broker"] or batch["broker"]`, de `import_normalized_tx`), llamado en main.py:~43960. Queda en memoria.
  - Entre esa lectura y la primera escritura corre la deduplicación (`already_imported_row_indices`, main.py:~43991).
  - PRIMERA ESCRITURA: el «reclamo» del lote, importing/persister.py:219-224 (`UPDATE import_batches SET status=status … AND status='preview'`). Sólo mira el estado, no el broker: un renombre en el medio no lo cambia, así que el reclamo pasa.
  - ESCRIBE con el nombre viejo, sin chequear que el broker exista: `INSERT INTO positions … broker=tx.broker` (persister.py:707) y `efectivo.mover` (efectivo.py, `INSERT` de una caja nueva cuando la del nombre viejo ya no está), más operations/monthly_entries.

## Protección (lente 1): no alcanza
- `import_confirm` no llama a `_tomar_turno`. Lo único que lo pide en el import es `_ensure_usd_sibling` (main.py:15704), y sólo si el lote trae dólares. Aun así, eso pasa DESPUÉS de la lectura, así que tampoco cubre la ventana de abajo.
- `efectivo.tomar_saldo` pide `turno_exclusivo(TURNO_CAJA_DEL_BROKER, uid)`, pero el renombre no lo pide: no se excluyen.
- El reclamo del lote es un UPDATE condicional por `status`, no por broker.
- No hay chequeo de que el broker exista ni en el persister (`_persist_buy`, `_persist_cash_in`) ni en `mover`. Sólo lo chequean dividendos, retiros y FX (`PersistError "no encontrado"`, persister.py:1099/1187/1241).
- El re-chequeo del renombre (6396-6403) mira la tabla `brokers`, que el import no toca.
- No hay ninguna FK por nombre ni índice único que rechace la fila con el nombre muerto.

## Alcanzable (lente 2): sí, pero raro
Las dos cosas las puede pedir el mismo usuario por HTTP: dos pestañas, o un asesor (`get_effective_user`) que renombra mientras el cliente confirma. Hay dos ventanas:
1. **En los dos motores (SQLite también):** entre la lectura de `load_session_for_confirm` y el reclamo. Ahí el import todavía no abrió la transacción (sqlite3 la abre recién en la primera escritura; en Postgres todavía no tomó ningún candado). Dura lo que tarden la carga y la deduplicación: milisegundos, hasta cientos en archivos grandes. No hay nada lento del orden de `_foto_contable`.
2. **Sólo en Postgres, más ancha:** mientras corre el persist (≈1 s cada 2.000 filas). El UPDATE de `positions` del renombre se traba en la caja que el import ya tomó y espera a que termine. Cuando sigue, sólo revisa las filas que ya veía al empezar esa instrucción, así que las `positions` NUEVAS del import quedan con el nombre viejo. operations y monthly_entries son instrucciones posteriores y sí se renombran. Si los dos se cruzan en un lote que el import vende, Postgres corta a uno con «deadlock detected» y ese se deshace entero, sin dejar datos mal.

## Consecuencia (lente 3): plata visible mal
- **Ventana 1:** todo el import queda bajo el nombre que ya no tiene ningún broker. Eso incluye las tenencias compradas, una caja nueva con el saldo del import, las operaciones y las filas mensuales del broker. En cambio, `import_normalized_tx` y `import_batches` sí quedaron con el nombre nuevo, porque el renombre las alcanzó antes.
  En pantalla, la Cartera agrupa por el nombre actual del broker (comentario de main.py:6003: «quedan con el nombre VIEJO → huérfanas → desaparecen del UI»), y las valuaciones descartan las posiciones huérfanas (main.py:33059, 33291, 33525). El usuario ve el import «OK», pero las tenencias y la plata no aparecen en el broker renombrado. Los aportes del lote sí entran en la fila 'global' de monthly_entries, que no lleva nombre de broker. Resultado: capital aportado sin tenencia que lo valúe, o sea una pérdida fantasma del tamaño del import. Es el mismo efecto que midió la auditoría en `_exigir_broker_existente` (−US$9.999).
- **Ventana 2 (Postgres):** las tenencias nuevas desaparecen, pero el débito de la caja sí quedó en el broker renombrado. Se ve efectivo bajado por compras que no aparecen.
- Ningún recálculo lo repara: `_recalc_pnl_realized_from_ops` y `_repair_monthly_chain` trabajan por el nombre que ya está escrito. Sale a mano, creando un broker con el nombre viejo o renombrando de vuelta, y el usuario no tiene forma de enterarse.
- Comparado con el mapeo: **igual en lo que queda mal, y algo peor en el alcance.** El mapeo lo pensaba como un problema de Postgres con imports de puros pesos. La ventana 1 existe también en SQLite y con imports que traen dólares, porque la lectura del nombre ocurre antes de cualquier turno. La probabilidad sigue siendo baja: hace falta renombrar en el mismo segundo en que se confirma.

## Cómo medirlo (estilo `tests/test_dos_pedidos_a_la_vez.py`)
1. Preparar el usuario: broker «Cocos» en ARS con caja y un lote previsualizado (`preview`) de un archivo en pesos con un depósito de $100.000 y una compra de GGAL por $60.000.
2. Abrir la ventana: `mock.patch.object(main._import_pipeline, "already_imported_row_indices", …)` con un envoltorio que primero avisa con `evento_leido.set()`, después espera `evento_renombrado.wait()` y recién ahí llama a la función original.
3. Correr dos pedidos a la vez:
   - Hilo A: confirmar el import.
   - Hilo B: espera `evento_leido`, hace `PUT /api/brokers/{bid}` con `{"name": "Cocos2", "currency": "ARS"}` y al final avisa con `evento_renombrado.set()`.
4. Qué debería dar y qué sale hoy:
   - `SELECT COUNT(*) FROM positions WHERE user_id=? AND broker='Cocos'` debería dar 0. Hoy da 2: GGAL y una caja nueva de +40.000.
   - La Cartera de «Cocos2» debería mostrar GGAL y una caja de +40.000. Hoy no muestra GGAL y la caja queda en el saldo anterior.
   - El capital aportado global sube $100.000 sin la tenencia que le corresponde.
5. Para la ventana 2, correrlo en Postgres: soltar el renombre después del reclamo, por ejemplo con un envoltorio sobre `helpers._adjust_broker_cash` en la primera compra. Lo que hay que contar es las `positions` nuevas que quedaron con broker='Cocos'.
