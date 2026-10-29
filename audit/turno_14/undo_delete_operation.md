# Veredicto — `undo_delete_operation` (POST /api/operations/undo/{token})

**Refutado: NO.** Lente que decide: ninguna lo tumba (pasa las tres). Gravedad: **datos** (y plata si la venta manual se cargó con «mueve efectivo»). Sólo en **Postgres**; en SQLite no ocurre.

## El mecanismo, en criollo
Deshacer el borrado de una operación importada hace tres cosas en orden:
1. Pide el turno (main.py:22594) y **mira** si el activo tiene algo cargado a mano (`_is_safe_to_rebuild`, main.py:22630 → importing/rebuild.py:556-589: lista lotes y filas `Venta` del activo y verifica que todas vengan de un import).
2. Saca la «foto contable» (main.py:22634, 0,8–1,65 s), marca el journal, devuelve la caja.
3. **Borra y rearma** el activo entero desde lo importado (`rebuild_pair_asset`, main.py:22654 → `_clear_old_state`, importing/rebuild.py:707-714: `DELETE FROM positions … asset=?` y `DELETE FROM operations … asset=? AND op_type='Venta'`).

El comentario de 22622-22626 dice que el chequeo existe justamente para no borrar en silencio data manual. El chequeo vale sólo si nadie puede meter una fila manual entre el paso 1 y el paso 3.
Es como revisar que el depósito esté vacío, ir a buscar la topadora (un segundo y medio) y demoler: si alguien guardó una caja mientras ibas, la demolés con la caja adentro.

## Lente 1 — Protección no vista: no hay
- **Intruso = `create_operation` (POST /api/operations, main.py:21061).** Verificado: no llama a `_tomar_turno` ni a ningún wrapper que lo haga (no usa `_exigir_broker_existente`, no valida broker). Inserta en main.py:21105 con `op_type` libre (puede ser `'Venta'`) y commitea en main.py:21133.
- `create_position` (POST /api/positions) **sí** está protegido: `_exigir_broker_existente` toma el turno (main.py:11915). Ese no es intruso.
- No hay índice único ni CHECK que impida una segunda `Venta` del mismo activo. La caja (`efectivo.mover`) tiene su candado propio, pero eso protege el saldo, no la fila de la operación.
- El «reclamo» con rowcount (main.py:22638-22643) sólo frena un doble Deshacer, no a otro escritor.
- No hay nivel de aislamiento distinto del default (READ COMMITTED) en el código: cada sentencia de Postgres ve lo commiteado por otros hasta ese instante, así que el `DELETE` del paso 3 **sí ve** la venta que el otro pedido commiteó después del chequeo.
- En **SQLite** el turno toma la base entera: el INSERT de `create_operation` espera al commit del Deshacer, entra después del rearmado y queda intacto. Por eso el problema es exclusivo de Postgres.

## Lente 2 — Alcanzable: sí, por HTTP, con ventana de ~1-2 s
Los dos pedidos los dispara el usuario logueado (o un asesor con `get_effective_user`). La ventana entre el chequeo (22630) y el DELETE (rebuild) contiene `_foto_contable` (0,8–1,65 s), `_config_tc_blue`, `_full_events` y `_replay_asset` (que puede buscar cotizaciones históricas). No son microsegundos.
Escenario realista pero poco frecuente: el usuario borra una venta importada, en otra pestaña empieza a cargarla a mano, y aprieta «Deshacer» en el toast de la primera justo cuando guarda la segunda. Requiere dos pestañas o dos dispositivos; no es un doble click.

## Lente 3 — Consecuencia: la venta manual desaparece, confirmado
Supuesto el cruce (`create_operation` commitea entre 22630 y 22654):
1. `rebuild_pair_asset` borra **la venta manual recién guardada** (rebuild.py:711-714) y rearma sólo lo importado. El usuario recibió 200 de su carga y la vio aparecer; desaparece sin aviso.
2. `_cascade_after_movement_delete` (main.py:22658 → 19620-19622) corre `_repair_monthly_chain` y `_recalc_pnl_realized_from_ops`: el P&L realizado del mes se **recalcula sin esa venta**. El recálculo no la tapa: la confirma (la fila ya no existe en `operations`).
3. Si la venta se cargó con «mueve efectivo» (`mueve_efectivo=true`, main.py:21082-21087), el movimiento de caja de `create_operation` (`_adjust_broker_cash`, main.py:21114) **queda aplicado** y la operación que lo justificaba no existe más: saldo del broker con el resultado de una venta fantasma, y no hay fila que borrar para devolverlo (el borrado manual devolvía la caja leyendo `undo_meta_json` de esa fila).

Comparado con el mapeo: **igual** a lo que afirmaba (data manual que desaparece en silencio), con un agravante no mencionado: caja huérfana si se pidió mover efectivo. No es exagerado ni peor en escala: afecta una operación de un usuario por cruce.

## Par intruso
- Sitio: `undo_delete_operation` — lectura main.py:22630 (`_is_safe_to_rebuild`, rebuild.py:567-570 lee `operations … op_type='Venta'`), escritura main.py:22654 → rebuild.py:711-714 (DELETE).
- Intruso: `create_operation` — escritura main.py:21105 (INSERT `op_type='Venta'`), commit main.py:21133, caja main.py:21114.

## Cómo medirlo (test, sólo en Postgres)
Siguiendo `tests/test_dos_pedidos_a_la_vez.py` (hilos + `threading.Event`, como en `test_una_escritura_AJENA_en_el_medio_no_hace_perder_filas`, línea 590):
1. Sembrar un usuario con un activo importado AAPL en broker X con una venta importada; borrarla con DELETE /api/operations/{oid} y guardar el `undo_token`.
2. Envolver `_foto_contable` (o `_import_rebuild._full_events`) para que el hilo del Deshacer, después del chequeo, espere un `Event`.
3. Hilo B: POST /api/operations con `{broker: X, asset: AAPL, op_type: 'Venta', pnl_usd: 100, mueve_efectivo: true}`; al responder 200, prender el `Event`.
4. Dejar terminar el Deshacer (responde 200).
5. Lo que sale mal: `SELECT count(*) FROM operations WHERE user_id=? AND asset='AAPL' AND op_type='Venta' AND undo_meta_json LIKE '%manual%'` da **0** (debería 1); el P&L realizado del mes en `monthly_entries` no incluye los US$100; la caja de X quedó +100 (en moneda del broker) sin operación que la explique.
6. Control: en SQLite el mismo test da 1 (el INSERT espera el turno). Y con `_tomar_turno` agregado a `create_operation` también debería dar 409 al Deshacer o 1 fila.

## Arreglo sugerido (no aplicado)
Que `create_operation` (y `update_operation`, mismo patrón) tomen el turno al entrar, igual que `create_position` vía `_exigir_broker_existente`. Arreglarlo en un solo lugar compartido protege a todos los que hacen «chequeo `_is_safe_to_rebuild` → rebuild» (delete de venta/compra, borrado de historial, imports).
