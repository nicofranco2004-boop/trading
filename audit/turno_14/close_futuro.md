# Veredicto: `close_futuro` (POST /api/futures/{fid}/close, main.py:17468)

**Refutado: SÍ** (en lo que importa: la plata). Lente que decide: **protección** para la
doble acreditación; queda un cruce real pero **cosmético**.

## Lo que afirmaba el mapeo
«La posición desaparece de Futuros aunque su resultado quedó acreditado; o se acredita dos veces.»

## Lente 1 — protección no vista

1. **Acreditar dos veces: imposible.** El cierre no depende del turno para eso. Marca la
   posición como cerrada con un UPDATE condicional tipo «reclamo»
   (`UPDATE futures_positions SET closed_at=? WHERE id=? AND user_id=? AND closed_at IS NULL`,
   y exige `rowcount == 1`, main.py:17512-17516) **antes** de tocar plata. En Postgres ese
   UPDATE toma la fila de la posición: un segundo cierre espera, re-evalúa el `closed_at IS NULL`
   y matchea 0 filas → 400. Vale en los dos motores, pida o no turno el otro.
2. **Efectivo:** `_adjust_broker_cash` = `efectivo.mover` (main.py:13915), que llama
   `tomar_saldo` (efectivo.py:248) — su propio candado por caja, válido en Postgres.
3. **Mes (`monthly_entries`):** `_update_monthly_pnl_realized` (main.py:14056) ya suma en la
   base con UPDATE-primero + INSERT ON CONFLICT: dos sumas a la vez no se pisan. Y después el
   cierre corre `_recalc_pnl_realized_from_ops`, que reconstruye el P&L desde las operaciones.
4. **Otros que reabren/recierran la posición:** borrar la operación
   (`_delete_manual_operation_cascade`, turno en main.py:21539; reabre con
   `closed_at IS NOT NULL`, main.py:21650) y su deshacer (`_undo_manual_delete`, turno en
   main.py:21954) piden turno → se ordenan con el cierre.

## El único intruso que queda: `delete_futuro` (DELETE /api/futures/{fid}, main.py:17447)
No pide turno. Lee `closed_at` (main.py:17454) y borra sin condición sobre `closed_at`
(`DELETE ... WHERE id=? AND user_id=?`, main.py:17462).

**Cruce en Postgres:** el borrado lee «abierta» → el cierre reclama la fila (17513), crea la
operación, acredita y hace commit → el DELETE del borrado, que esperaba el candado de la fila,
re-evalúa su WHERE (sigue matcheando: no mira `closed_at`) y **borra la posición ya cerrada**.
En SQLite (WAL, transacción diferida que ya leyó) el borrado no puede subir a escritor sobre una
foto vieja → error/500 y no borra.

## Lente 2 — alcanzable
Sí, por HTTP, el mismo usuario (dos pestañas: «Cerrar» y «Borrar» la misma posición). Pero la
ventana es la del **borrado**: microsegundos entre su SELECT y su DELETE (no hay nada lento en el
medio). Rarísimo en la práctica.

## Lente 3 — consecuencia (si se cruza)
- Queda: operación de futuros creada con el resultado, efectivo acreditado **una vez**, mes
  correcto (y recalculado). Todo consistente entre sí.
- Lo único raro: la fila de `futures_positions` ya no existe, así que la posición no aparece
  en la lista de cerradas (`GET /api/futures?include_closed=true`). En la de abiertas tampoco
  aparecería de todos modos, porque está cerrada.
- Si después se borra la operación: el reabrir matchea 0 filas (no hay posición), devuelve la
  plata bien; sólo no «resucita» la posición. Equivale a «cerró y después borró el registro»,
  que el usuario pidió explícitamente.
- Comparado con el mapeo: la parte «se acredita dos veces» es **falsa**; la parte «desaparece
  aunque se acreditó» es **cierta pero exagerada**: no es plata, es el registro histórico de una
  posición cerrada que el usuario mismo mandó a borrar.

Gravedad: **cosmético**.

## Cómo medirlo (si se quisiera)
Con el patrón de `tests/test_dos_pedidos_a_la_vez.py`, en Postgres: frenar `delete_futuro`
entre su SELECT y su DELETE (monkeypatch de un hook/evento tras la lectura), lanzar en paralelo
`POST /api/futures/{id}/close` con `exit_price` que dé +500, soltar el borrado.
Esperado si se reproduce: cierre 200, borrado 200, `futures_positions` sin la fila, operación
`Futuros` con `pnl_usd=500`, efectivo +500 (no +1000). Lo que «sale mal» es sólo
`GET /api/futures?include_closed=true` sin la posición. Arreglo de una línea si importara:
`AND closed_at IS NULL` en el DELETE de main.py:17462 y 404/400 si `rowcount==0`.
