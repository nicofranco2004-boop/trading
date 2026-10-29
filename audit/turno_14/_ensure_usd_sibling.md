# Veredicto: `_ensure_usd_sibling` — REFUTADO (lente 1, protección)

**Qué afirmaba el mapeo:** una vista previa de un archivo que nombra «Cocos · USD» y un depósito en dólares leen los dos «no existe» y crean/adoptan la sub-cuenta a la vez → datos rotos y queda trabado.

## Por qué no pasa

1. **El turno lo pide la función misma, antes de mirar** (`backend/main.py:15700`, `_tomar_turno(conn, uid)` y recién después el SELECT de la pata en `main.py:15705`). No depende de quién la llame: todas las puertas pasan por esta función.
   - Depósito/retiro: `cash_flow` (`main.py:14602`) → `_pata_de_la_moneda` (`main.py:15790`) → `_ensure_usd_sibling`.
   - Import/foto: `main.py:42938` y `main.py:43146`, y el persister vía `_import_helpers._ensure_usd_sibling = _ensure_usd_sibling` (`main.py:42244`).
   - Conversiones `main.py:15852`; `POST /api/brokers/{bid}/usd-sibling` `main.py:15998`.
   Dos pedidos que llegan acá por el mismo usuario quieren la MISMA fila de `users`: en SQLite toman la base y en Postgres la fila, así que en los dos motores el segundo espera hasta el commit del primero. En Postgres (READ COMMITTED) cada sentencia mira de nuevo lo confirmado, así que el SELECT que sigue después de la espera encuentra la pata que creó el primero y la devuelve. El escenario del mapeo (vista previa + depósito) es justo el par protegido: **los dos piden turno**.
2. **El único que escribe en `brokers` sin pedir turno es el alta manual `POST /api/brokers` (`create_broker`, `main.py:5909`, INSERT en `main.py:5971`).** Contra ese, la tabla tiene `UNIQUE (user_id, name)` (`schema_pg.sql:690-697`; SQLite `main.py:1365-1372`): no pueden quedar dos «Cocos · USD». El que pierde recibe un error de unicidad y su transacción entera se deshace (no queda nada a medias); reintentando, `_ensure_usd_sibling` entra por el camino de adopción (`main.py:15729-15740`) con el chequeo `por_que_no_hay_pata_usd`. Además la ventana es de microsegundos (no hay nada lento entre el SELECT por nombre y el INSERT) y exige que la persona escriba a mano el nombre exacto «Cocos · USD» en el mismo instante en que entra su primer dólar.
3. El renombre (`main.py:6396`) y el borrado de brokers también piden turno; `_wallbit_ensure_broker` (`main.py:44495`) crea «Wallbit», nunca un «· USD».

## Consecuencia si igual se cruzara (alta manual vs. pata)
Un pedido rebota con error (500 o 409 según la puerta) y se deshace; nada queda escrito mal. Es cosmético/molestia, no datos ni plata. El «queda trabado» del mapeo no aparece: no hay estado intermedio guardado.

## Cómo medirlo (si se quisiera confirmar)
Siguiendo `tests/test_dos_pedidos_a_la_vez.py`: dos hilos con el mismo uid; hilo A llama `POST /api/cash/flow` (USD, broker «Cocos» en ARS sin pata) con un gancho que se detiene justo después de `_tomar_turno`; hilo B llama a la vista previa/`POST /api/brokers/{id}/usd-sibling`. Esperado: B queda esperando hasta el commit de A y termina devolviendo la misma pata; al final `SELECT COUNT(*) FROM brokers WHERE user_id=? AND parent_broker_id=?` = 1 y ningún 500. Para el par sin turno: A detenido entre el SELECT por nombre y el INSERT, B = `POST /api/brokers` {name:"Cocos · USD", currency:"USD"}: esperado exactamente un broker con ese nombre y un pedido con error, sin saldos tocados.
