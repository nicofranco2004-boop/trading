# Veredicto: `_delete_one_movement` (camino tx-, depósito importado)

**NO refutado.** Lente que decide: ninguna lo tumba (pasa protección, alcanzable y consecuencia).

## El par intruso
- Sitio: `DELETE /api/movements/tx-N` → `_route_tx_delete` (main.py:20067) → `_delete_one_movement` (main.py:19943).
- Intruso: `POST /api/imports/{batch_id}/revert` → `import_revert` (main.py:45479) → `_revert_batch_de` (main.py:45509) → `persister.revert_batch` (importing/persister.py:1515). Mismo cuerpo en `import_redo` y en el deshacer de tanda del asesor.

## Lente 1 — protección: no hay ninguna que cruce a los dos
- `revert_batch` / `import_revert` **no piden `_tomar_turno`** (grep: 0 apariciones en persister.py; el endpoint no lo llama).
- Su «reclamo» es `UPDATE import_batches SET status=status ... AND status='confirmed'` (persister.py:1548). El borrado **nunca escribe `import_batches`** (ni `_delete_one_movement`, ni `_entrada_de_movimiento_importado`, ni `_cascade_after_movement_delete`): en Postgres los dos reclamos son filas distintas y no se esperan.
- El reclamo del borrado es `UPDATE import_normalized_tx SET excluded_at=... WHERE excluded_at IS NULL` (main.py:19983). El revert **no escribe** `excluded_at`: solo lo LEE (persister.py:1650-1655, `WHERE batch_id=? AND excluded_at IS NULL`) en una lectura sin bloqueo. En Postgres (read committed) ve la fila viva mientras el borrado no haya hecho commit.
- El único candado común es el de la caja (`efectivo.tomar_saldo` → `pgsesion.turno_exclusivo(TURNO_CAJA_DEL_BROKER)`, efectivo.py ~103). Ese candado **serializa** las dos restas pero no evita ninguna: cada una ya decidió restar antes de pedirlo. La resta es un `mover(delta)` sobre el saldo vigente, así que se acumulan.
- En SQLite esto NO pasa: el `UPDATE users` del borrado toma la base entera; el revert espera en su `UPDATE import_batches` y al leer la lista de movimientos ya ve `excluded_at` puesto (o, al revés, el borrado ve el lote revertido y da 404). Es un bug sólo de Postgres.

## Lente 2 — alcanzable: sí, y con ventana ancha
- Los dos son pedidos HTTP del usuario (o del asesor sobre la cuenta del cliente).
- Ventana: toda la transacción del borrado. Entre `_tomar_turno` y el commit corren `_foto_contable` (0,8–1,65 s, main.py:19970, ANTES del reclamo) y la cascada completa (`_repair_monthly_chain`, `_recalc_pnl_realized_from_ops`, fotos). Más de un segundo, no microsegundos.
- Funciona en los dos órdenes: (a) el revert lee la lista mientras el borrado está en `_foto_contable` → ve el depósito vivo → resta; (b) el borrado leyó `TX_VIVAS` (lote 'confirmed') antes del commit del revert, y su reclamo sobre `excluded_at` no choca con nada que el revert escriba → también resta.

## Lente 3 — consecuencia: igual a lo que decía el mapeo (efectivo restado dos veces), y no se autocura
- `_delete_one_movement` resta `gross_amount` de la caja (main.py:19996) y `revert_batch` resta el mismo `gross_amount` de la misma caja (persister.py:1708). Resultado: el efectivo del broker queda **un depósito entero por debajo** de lo real (ej.: depósito de US$ 1.000, saldo que debería quedar en 0 queda en −1.000).
- El propio código dice que la caja es «la única cosa que _recalc no recompone» (main.py:19990): ningún recálculo posterior la arregla. Se ve en Cartera (efectivo del broker) y arrastra el valor total de la cartera.
- Secundario (no lo seguí hasta el final): el revert además baja `monthly_entries.deposits` del broker y de 'global' con `_update_monthly_flow(-amount_usd)` (persister.py:1714-1715) DESPUÉS de que la cascada del borrado ya rehízo esos meses; si la cadena mensual se rearma desde las filas vivas, un recálculo posterior podría corregir el capital aportado (salvo el mes en curso, que `_repair_monthly_chain` no repara). El efectivo no tiene ese rescate.

## Cómo medirlo (test, siguiendo tests/test_dos_pedidos_a_la_vez.py)
1. Usuario con un import confirmado que trae SOLO un DEPOSIT de 1.000 en broker B (caja 1.000).
2. Contra Postgres, dos hilos con conexiones propias:
   - Hilo A: `DELETE /api/movements/tx-<id del depósito>`, frenado adentro de `_foto_contable` (parchear para que espere un evento) — ya tiene `_tomar_turno` tomado y aún no escribió `excluded_at`.
   - Hilo B: `POST /api/imports/<batch>/revert` mientras A está frenado; B lee la lista y se queda esperando el candado de la caja.
   - Soltar A; los dos responden 200.
3. Esperado: caja de B = 0. Sale: **−1.000**. (Variante orden inverso: frenar B después del SELECT de txs y lanzar A.)
4. En SQLite el mismo test debe dar 0 (el segundo espera o recibe 404/400): sirve de control.
