# Barrido de los 24 usos de `_tomar_turno` — 28/10/2026

Ocho agentes mapearon los 24 sitios con el mismo molde de preguntas; los marcados
en riesgo los refutaban tres escépticos con lentes distintas (¿hay una protección
que no viste? ¿es alcanzable? ¿la consecuencia es real?).

🔴 **EL BARRIDO ESTÁ INCOMPLETO Y ESO NO SE PUEDE REDONDEAR.** De 71 agentes, **44
murieron por el límite de uso de la cuenta**. El mapeo de los 24 se completó; la
refutación llegó a 7 sitios de 21. Entonces:

| | |
|---|---|
| sitios mapeados | 24 |
| marcados en riesgo | 21 |
| **confirmados por los escépticos** | **6** |
| refutados | 1 |
| **sin verificar** (los escépticos murieron) | **14** |
| protegidos también en Postgres | 3 |

⚠️ **«Sin verificar» NO quiere decir «probablemente cierto».** En la tanda anterior,
de 3 hallazgos que alguien verificó: 1 era cierto, 1 estaba corroborado por un test
rojo, y **1 tenía el mecanismo bien y la gravedad inflada al doble**. Las lentes
aciertan el *dónde* y exageran el *cuánto*. Un sitio sin verificar es una hipótesis.

---

## EL MECANISMO, una vez para los 24

`main._tomar_turno(conn, uid)` hace `UPDATE users SET tier=tier WHERE id=?`.

· En **SQLite** ese UPDATE toma **la base entera** hasta el commit: cualquier otro
  pedido que quiera escribir espera. Protección total y gratis.
· En **Postgres** toma **sólo la fila de ese usuario en `users`**: espera únicamente
  quien también escriba ESA fila — o sea, en la práctica, sólo otras operaciones
  destructivas que llamen a `_tomar_turno`. Todo lo demás pasa por al lado.

El propio repo ya lo tenía escrito en el docstring de `_foto_contable`: «En Postgres
sólo traba la fila del usuario … hace falta un turno por usuario que tomen todos los
que escriben las cuentas». **Lo que faltaba era la lista de quiénes no lo toman.**

---

## ✅ CONFIRMADOS por los escépticos

### 🔴 `_delete_asset_history_cascade (DELETE /api/assets/history — el tacho «borrar todo el historial de este activo»)` — gravedad plata · 3 de 3 confirman

**Qué protege:** Hay cuatro lecturas que DECIDEN, y la escritura que depende de ellas llega mucho después.

LEE PARA DECIDIR:
· 22582-22588: las compras y ventas importadas vivas del activo (`rows`). Con eso decide si va al camino de lo cargado a mano (22588), bloquea si hay un cierre de foto (22598) o un lote semilla sintético (22606), arma los pares de cuentas (22592-22596), elige qué filas tapar y cuánta plata devolver.
· 22611: `_is_safe_to_rebuild` — mira los lotes y las ventas que HAY HOY del activo y los compara con lo que quedó vinculado a un import. Si aparece algo cargado a mano, contesta 409 y no toca nada.
· 22623-22637: los cobros de renta fija (cupones, amortizaciones, dividendos) del activo, para bloquear si alguno se anotó a mano (22646) y para guardar la copia que después permite deshacer.
· 22690: `_foto_contable`, que el propio código mide en 0,8 a 1,65 segundos en una cuenta con miles de movimientos importados.

ESCRIBE:
· 22694-22698: tapa las filas importadas de una sola vez y, si matchea menos de las que esperaba, contesta 409 (eso evita el doble-crédito de plata).
· 22712-22734: devuelve la plata a cada cuenta, borra los vínculos del import y borra las filas de renta fija de `operations`.
· 22741: `rebuild_pair_asset`, que por dentro (importing/rebuild.py:708 y :712) hace `DELETE FROM positions … AND asset=? AND is_cash=0` y `DELETE FROM operations … AND op_type='Venta'` A CIEGAS — borra TODOS los lotes y TODAS las ventas del activo en esas cuentas, estén vinculados a un import o no. Su propia docstring (importing/rebuild.py:999-1000) lo dice: «El caller DEBE haber chequeado `_is_safe_to_rebuild` antes (no tocamos data manual)». No lo vuelve a chequear.

El par concreto es entonces: LEE en 22611 «no hay nada cargado a mano» → BORRA A CIEGAS en 22741 (vía rebuild.py:708). Entre las dos hay 130 líneas y, sobre todo, los 0,8 a 1,65 segundos de `_foto_contable`.

**Tablas:** Lee-para-decidir: import_normalized_tx junto con import_batches (sólo las filas de un import confirmado y sin tapar), positions, operations, import_op_links, y —por dentro de `_foto_contable`— lo que usa el capital aportado (monthly_entries, cash_flow, snapshots).

Escribe: import_normalized_tx (la tapa), import_op_links, operations, positions (los lotes, vía el rebuild; y la caja de efectivo), deleted_ops_journal, monthly_entries y snapshots (la cascada final).

**Quién se mete sin pedir el turno:** Revisé 24 funciones que escriben estas tablas sin pedir turno. Las cinco que tocan las MISMAS filas del MISMO activo:

1. `create_position` → `_insert_manual_position` (main.py:11858 y 11728; POST /api/positions): inserta el lote en `positions` (11770) y descuenta la plata (11803). Es el competidor más directo: crea exactamente lo que `_is_safe_to_rebuild` existe para detectar.
2. `sell_position_fifo` (main.py:16015; POST /api/positions/sell): inserta la venta en `operations` (16246) y borra/cambia lotes en `positions` (16307, 16317).
3. `create_operation` (main.py:20956; POST /api/operations): inserta en `operations` (20998) — una venta a mano del activo, sin vínculo de import.
4. `import_confirm` (main.py:43811; POST /api/imports/confirm): escribe `positions` (44086) y, por `importing/persister.py`, vuelve vivas las filas importadas (pone `status='confirmed'` en persister.py:564) e inserta positions (682, 799) y operations (933, 996, 1127, 1282).
5. `edit_position_group` → `_edit_position_group` (main.py:12080 y 11935; PATCH /api/positions/group): cambia `positions` (12012, 12027, 12039, 12054), `import_normalized_tx` (12017, 12043, 12058) y `operations` (12065) — puede incluso renombrar el ticker del activo mientras el borrado está corriendo.

Ninguna de las cinco escribe la fila del usuario en `users`, así que en Postgres ninguna espera al borrado ni el borrado las espera a ellas.

**Por qué no está protegido:** El turno de 22578 sólo traba la fila de ese usuario en `users`. De los cinco competidores, ninguno escribe esa fila: todos pasan por al lado.

Lo que sí protege algo, y es importante no confundirlo, son dos candados reales que ya están puestos:
· La tapa de 22694-22698 es una escritura con control de cuántas filas tocó. Eso cubre que dos borrados del mismo activo se crucen (el segundo matchea menos filas y corta con 409). Pero cubre SOLAMENTE `import_normalized_tx`: no cubre `positions` ni `operations`, y los cinco competidores no tocan esa tabla con esas filas (los que la tocan, la tocan con filas nuevas o distintas, que no bajan el conteo).
· La caja de efectivo sí tiene candado de verdad (`TURNO_CAJA_DEL_BROKER`, efectivo.py:103). Pero no salva este caso, por el ORDEN: el borrado toca la caja recién en 22712, DESPUÉS de haber decidido en 22611 y después de la foto contable. Un pedido que alta un lote a mano agarra la caja, descuenta, y TERMINA ENTERO antes de que el borrado llegue a pedirla. Cuando el borrado la pide, está libre. El candado ordena la suma de la plata; no hace que la decisión de 22611 siga siendo cierta.

Y la ventana no es un microsegundo teórico: son los 0,8 a 1,65 segundos de `_foto_contable` (22690), medidos por el propio código, metidos justo entre la decisión y el borrado a ciegas. Es el MISMO molde que el bug ya resuelto de `_delete_one_movement`, con el mismo reloj en el medio.

**Consecuencia:** Plata que se va y no vuelve, más un activo que desaparece sin dejar rastro.

El caso concreto: la persona manda a borrar todo el historial importado de GGAL. El borrado mira en 22611, no encuentra nada cargado a mano, y arranca la foto contable. En ese segundo y medio, desde otra pestaña, desde el celular, o porque la primera petición pareció colgarse y reintentó, entra un alta de un lote de GGAL por US$ 5.000 (POST /api/positions): el lote se inserta y los US$ 5.000 salen de la caja. Ese pedido termina y confirma.

El borrado sigue, llega a 22741, y el rebuild hace `DELETE FROM positions … AND asset='GGAL'` (rebuild.py:708). El lote recién creado se borra junto con los importados. Pero sus US$ 5.000 NO se devuelven: el papel para deshacer (22751-22758) sólo anota la plata de las filas importadas, así que ni el undo lo recupera.

Queda: la plata salió de la caja, el activo no existe, y no hay forma de deshacerlo. Es exactamente el estado que el 409 «operaciones cargadas a mano mezcladas con las importadas» (22612-22614) existe para impedir.

La variante con la venta (`sell_position_fifo`) es igual de mala y más probable, porque vender es más frecuente que cargar un lote a mano: la venta acredita la plata, inserta su fila en `operations`, y el rebuild de 22741 la borra con el `DELETE … op_type='Venta'` de rebuild.py:712. Queda la plata acreditada por una venta que ya no figura en ninguna parte.

---

### 🔴 `undo_delete_asset_history (POST /api/assets/undo/{token} — el «deshacer» del borrado del historial de un activo)` — gravedad plata · 1 de 1 confirman

**Qué protege:** Es el mismo molde que su hermano, con cuatro guards en vez de tres, y el mismo reloj metido entre la última decisión y la escritura.

LEE PARA DECIDIR:
· 22794-22800: el papel del borrado, exigiendo que no se haya deshecho ya.
· 22817-22822: que los brokers de ese activo sigan existiendo (si no, 409). ESTE GUARD SÍ ESTÁ CUBIERTO: el único que borra brokers, `delete_broker` (main.py:6426), llama a `_borrar_datos_de_brokers` (6111), que toma el turno.
· 22824: `_is_safe_to_rebuild` — si desde el borrado el activo ganó algo cargado a mano, 409, «se perdería al restaurar».
· 22831-22836: el guard de re-import — busca filas vivas del activo FUERA del set borrado; si aparecen, 409 «volviste a importar este activo desde que lo borraste», porque deshacer fusionaría lo viejo con lo nuevo y duplicaría.
· 22842: `_foto_contable`, otra vez los 0,8 a 1,65 segundos.

ESCRIBE:
· 22844-22847: marca el papel como deshecho controlando cuántas filas tocó (eso sí cubre el doble-deshacer: el segundo corta con 409).
· 22849-22851: destapa las filas importadas; 22852-22855: devuelve la plata.
· 22856: `rebuild_pair_asset`, que vuelve a borrar a ciegas TODOS los lotes y ventas del activo (rebuild.py:708 y :712) y los re-escribe desde las filas importadas que están vivas EN ESE MOMENTO.
· 22859-22899: el barrido de amortizaciones, y re-inserta en `operations` los cobros de renta fija, sus vínculos y el mes.

El par concreto: LEE en 22824 y 22831-22836 «no hay nada a mano y no se re-importó» → BORRA Y RE-ESCRIBE A CIEGAS en 22856. Entre las dos, la foto contable de 22842.

**Tablas:** Lee-para-decidir: deleted_ops_journal, brokers, positions, operations, import_op_links, import_normalized_tx junto con import_batches, y lo del capital aportado por dentro de `_foto_contable`.

Escribe: deleted_ops_journal, import_normalized_tx, positions (los lotes, vía el rebuild; y la caja), operations, import_op_links, monthly_entries y snapshots.

**Quién se mete sin pedir el turno:** Los mismos cinco que el otro sitio (verificados uno por uno, no asumidos): `create_position`/`_insert_manual_position` (main.py:11858, 11728), `sell_position_fifo` (main.py:16015), `create_operation` (main.py:20956), `import_confirm` (main.py:43811, con `importing/persister.py:564` como la línea que vuelve vivas las filas) y `edit_position_group`/`_edit_position_group` (main.py:12080, 11935).

Acá `import_confirm` pesa más que en el otro sitio, porque hay un guard escrito específicamente contra él (22831-22836) y ese guard es justamente el que la ventana deja pasar.

**Por qué no está protegido:** Igual que su hermano: el turno de 22793 traba la fila del usuario en `users`, y ninguno de los cinco competidores escribe esa fila.

El control de filas tocadas del papel (22844-22847) cubre bien una cosa y sólo una: que el mismo deshacer se ejecute dos veces. No dice nada sobre lo que pasó con los lotes, las ventas o las filas importadas del activo entre 22824 y 22856.

Lo que hace a este sitio peor que al otro es que acá los guards son MÁS explícitos sobre qué quieren impedir —«se perdería al restaurar», «fusionaría viejo+nuevo → duplicaría»— y la ventana los deja pasar igual. Un guard que se evalúa y después espera un segundo y medio antes de que importe su respuesta, en Postgres no es un guard: es una foto vieja.

**Consecuencia:** Dos daños distintos, los dos de plata.

Primero, el mismo que el otro sitio: si en la ventana entra un lote a mano o una venta del activo, el rebuild de 22856 lo borra a ciegas (rebuild.py:708/712) y la plata que ese movimiento movió queda del lado equivocado, sin forma de recuperarla.

Segundo, y es el que el código mismo describe: la persona borró el historial de GGAL, después vuelve a subir el CSV del broker, y justo cuando aprieta «Confirmar» aprieta también «Deshacer» (o el deshacer ya estaba en vuelo). El deshacer pasa el guard de re-import en 22831-22836 porque todavía no hay filas nuevas, arranca la foto contable, y en ese segundo y medio el import confirma: sus filas pasan a `status='confirmed'` (persister.py:564) y quedan vivas. El deshacer sigue, destapa las filas VIEJAS en 22849-22851, devuelve la plata de las viejas en 22852-22855, y el rebuild de 22856 re-escribe el activo desde TODAS las filas vivas — las viejas destapadas y las nuevas importadas.

Resultado: GGAL aparece con el doble de tenencia y con la plata descontada dos veces, una por cada import. Es textualmente lo que el guard dice que pasa si se fusionan («deshacer FUSIONARÍA viejo+nuevo → duplicaría»), con el agravante de que el papel ya quedó marcado como deshecho en 22844, así que no hay un segundo deshacer que arregle esto.

---

### 🔴 `_delete_manual_operation_cascade` — gravedad plata · 3 de 3 confirman

**Qué protege:** Hay DOS pares acá, y el grave es el primero.

PAR 1 — EL CAPITAL APORTADO (es el mismo molde del caso resuelto, con otra tabla):
lee en 21450 `antes = _foto_contable(conn, uid)` → de ahí sale `antes["canon"]`, que es el capital aportado de cada mes leído desde `monthly_entries` (twr.py:1800-1802). Ese mismo código mide que tarda **0,8 a 1,65 segundos** en una cuenta con miles de movimientos (docstring en 18687).
escribe en 19564 `UPDATE snapshots SET net_deposited=?` sobre **hasta ~1.100 fotos históricas** (el comentario de 19563 lo dice).
Lo que se escribe en cada foto es, literalmente, `viejo + (aportado_de_ahora − aportado_de_antes)` (main.py:19274-19278, con el delta calculado en 19010-19011 y 19043). O sea: TODO lo que el capital aportado cambió entre las dos lecturas se le adjudica al borrado.

PAR 2 — EL LOTE QUE SE RESTAURA (sólo en el camino `fifo_sell`):
lee en 21472 `SELECT id, quantity, invested, commissions FROM positions WHERE id=?` para decidir si el lote sobrevivió (venta parcial → sumarle lo consumido, 21478) o si se borró (venta total → re-crearlo, 21495).
escribe en 21478 `UPDATE positions SET quantity=...` — **sin mirar cuántas filas tocó**.

**Tablas:** Lee-para-decidir: `monthly_entries` (el capital aportado, vía `_foto_contable`→`twr.netdep_canonico`), `operations` (21430), `positions` (21472, 21493), `plazos_fijos` (21601), `brokers` (21565, 21610). Escribe: `snapshots.net_deposited` (19564), `operations` (DELETE 21454), `positions` (21478, 21495 y la caja vía `_adjust_broker_cash`), `plazos_fijos`, `futures_positions`, `deleted_ops_journal`, `monthly_entries` (la cadena del recálculo).

**Quién se mete sin pedir el turno:** PARA EL PAR 1 (el capital aportado en `monthly_entries`) — tres endpoints comunes, ninguno destructivo, ninguno escribe la fila de `users`:
· **`POST /api/cash/flow` → `cash_flow`, main.py:14518-14612.** Es EL MISMO competidor del caso ya resuelto, por otra puerta. Mueve la caja (14556, candado de la caja) y después llama a `_registrar_flujo_a_mano` (14593) → `_update_monthly_flow(..., 'global', ...)` (14195) → `UPDATE/INSERT monthly_entries` (14081 y 14128). Esa es exactamente la fila que lee `netdep_canonico`.
· **`POST /api/positions` → `create_position` (11856) → `_insert_manual_position` (11728).** Si la compra no tiene saldo, `_autodeposit_if_overdraw` (13893) registra un aporte automático: misma cadena `_registrar_flujo_a_mano` → `monthly_entries`, más `_repair_monthly_chain` x2.
· **El import, `POST /api/imports/.../confirm` → `import_confirm` (main.py:43811) + `importing/persister.py` (0 turnos en todo el archivo).** El import reescribe `monthly_entries` HACIA ATRÁS — lo dice el propio docstring de `netdep_canonico` (twr.py:1783-1784). Es el competidor de monto más grande.

PARA EL PAR 2 (el lote en `positions`):
· **`POST /api/positions/sell` → `sell_position_fifo`, main.py:16015-16387.** Consume lotes FIFO: `DELETE FROM positions WHERE id=? AND user_id=? AND quantity=?` (16307) y `UPDATE positions SET quantity=...` (16317). No pide turno.
· **`importing/rebuild.py:708** (`_clear_old_state`): `DELETE FROM positions ... AND asset=? AND is_cash=0` — borra todos los lotes del activo. Lo dispara cualquier import del mismo activo.

REVISADOS Y DESCARTADOS (sí están protegidos): el borrado de un broker por sus dos puertas (`DELETE /api/brokers/{bid}` en 6540 y «Limpiar broker» → `_wipe_broker_data` en 30173) — las dos pasan por `_borrar_datos_de_brokers`, que pide el turno en 6126 dentro del MISMO `with conn:` que el `DELETE FROM brokers`. También `POST/PUT/DELETE /api/monthly` (16988, 17020, 17060): piden turno. Y todo lo que sólo mueve plata, por el candado de la caja.

**Por qué no está protegido:** El turno de la fila de `users` no sirve acá porque **ninguno de los tres competidores del par 1 escribe la fila de `users`**. `cash_flow` toca la caja y `monthly_entries`, nada más. El import toca todo menos `users`. El alta de posición, lo mismo.

Y el candado que SÍ existe de verdad no llega: `efectivo.tomar_saldo` toma `pg_advisory_xact_lock(TURNO_CAJA_DEL_BROKER, uid)` (efectivo.py:104), que protege **el saldo de la caja**, no `monthly_entries`. Son dos candados distintos y no se esperan entre ellos. Es como poner un candado en la caja fuerte y dejar abierto el cuaderno donde se anota cuánta plata se puso: el que escribe el cuaderno no necesita la caja.

La ventana es concreta y no hace falta imaginarla: `antes = _foto_contable` está en la línea 21450 y la primera vez que esta función toca la caja —y por lo tanto agarra el único candado real que tiene— es en 21515 (`_adjust_broker_cash`), después del borrado de la operación y de la restauración del lote. Todo lo que pase entre 21450 y 21515 entra. Y en el camino `manual_form` (una operación que sólo tiene su fila de P&L) **nunca se mueve plata**, así que esta función no agarra el candado de la caja NI UNA VEZ: la ventana se estira desde 21450 hasta el final, incluyendo los 0,8-1,65 segundos del `_foto_contable`.

En SQLite esto no podía pasar: el `UPDATE users` de 18698 traba la base entera, así que `cash_flow` esperaba a que el borrado terminara.

El par 2 es más angosto pero igual de real: entre el SELECT de 21472 y el UPDATE de 21478 no hay nada que trabe la fila del lote (es un SELECT común, sin `FOR UPDATE`), y el UPDATE no chequea `rowcount` — si el lote ya no está, no pasa nada y nadie se entera.

**Consecuencia:** PAR 1 — **plata mal, en el número que mide el rendimiento, y sin vuelta.** Si alguien deposita $1.000.000 mientras se borra una operación cargada a mano, el borrado cree que ESE millón es su propio efecto y se lo suma al capital aportado de hasta ~1.100 fotos históricas. El capital aportado es el denominador del rendimiento: la curva de Reportes, el rendimiento de cada mes, el mejor/peor mes y la peor caída quedan todos deformados hacia atrás. El propio código avisa que esto no se arregla solo: «una [foto] reescrita mal no tiene vuelta» (19534-19535). Y peor: el cambio queda anotado foto por foto en el journal (19284), así que si después se usa «Deshacer», el deshacer devuelve exactamente la misma corrección contaminada (19002-19007) — el error queda sellado en las dos direcciones.

PAR 2 — **una tenencia que desaparece con la plata ya devuelta.** Borrás una venta de 10 acciones; mientras corre, otro pedido vende ese mismo lote entero y lo borra. Tu `UPDATE` no encuentra la fila, no devuelve las 10 acciones y nadie avisa; pero el efectivo SÍ se debita (21515, la venta lo había acreditado). Queda menos plata y menos acciones: se perdieron las dos puntas.

---

### 🔴 `_delete_operation_cascade` — gravedad plata · 3 de 3 confirman

**Qué protege:** Dos pares, los dos reales.

PAR 1 — EL CAPITAL APORTADO: idéntico al del sitio anterior. Lee en 22202 `antes = _foto_contable(conn, uid)` (los 0,8-1,65 s) → escribe en 19564 `UPDATE snapshots SET net_deposited=?` con `viejo + (aportado_de_ahora − aportado_de_antes)`. La ventana acá es MÁS ANCHA que en el sitio anterior, porque entre medio corren dos cosas pesadas más: `rebuild_pair_asset` (22256) y `_recalcular_mediciones` (22260).

PAR 2 — EL PERMISO PARA RE-DERIVAR EL ACTIVO:
lee en 22177 `_import_rebuild._is_safe_to_rebuild(conn, uid, pair, asset)` — que a su vez lee `positions` (rebuild.py:563-566) y las ventas de `operations` (rebuild.py:567-570) del activo, y contesta «todas estas filas las creó un import, se puede re-derivar» o «hay algo cargado a mano, NO toques».
lee también en 22187 un `SELECT 1 FROM operations` buscando cupones y amortizaciones (el guard de renta fija sin catalogar).
escribe en 22256 `rebuild_pair_asset`, que **borra TODAS las posiciones y TODAS las ventas del activo** (`_clear_old_state`, rebuild.py:708 y 712) y las vuelve a crear desde lo importado que sobrevive.
El propio docstring del rebuild lo dice en voz alta: «El caller DEBE haber chequeado `_is_safe_to_rebuild` antes (no tocamos data manual)» (rebuild.py:999).

**Tablas:** Lee-para-decidir: `monthly_entries` (el aportado), `positions` y `operations` del activo (vía `_is_safe_to_rebuild` y el guard de renta fija), `operations` (22124), `import_op_links` (22131), `import_normalized_tx` (22141). Escribe: `snapshots.net_deposited` (19564), `import_normalized_tx` (22206), la caja (22231), `import_op_links` (DELETE 22236), `deleted_ops_journal` (22241), y vía el rebuild **borra y re-crea `positions` + `operations` del activo entero** (rebuild.py:708, 712, 724).

**Quién se mete sin pedir el turno:** PARA EL PAR 1: los mismos tres del sitio anterior, verificados de nuevo — `cash_flow` (main.py:14518, escribe `monthly_entries` en 14593→14195→14081/14128), `_insert_manual_position` vía el aporte automático (11728→13893→14176), e `import_confirm` (43811) + `importing/persister.py`. Ninguno escribe la fila de `users`.

PARA EL PAR 2 — dos endpoints que CREAN justo el tipo de fila que el chequeo busca:
· **`POST /api/operations` → `create_operation`, main.py:20956-21032.** `INSERT INTO operations` en 20998, sin ningún `import_op_links` (es carga a mano). Si el `op_type` es 'Venta' del mismo activo y broker, es exactamente la fila que `_is_safe_to_rebuild` busca en rebuild.py:567-570 para contestar «NO» — y exactamente la que `_clear_old_state` borra en rebuild.py:712. No pide turno.
· **`POST /api/positions` → `_insert_manual_position`, main.py:11728-11825.** `INSERT INTO positions` en 11770 (un lote sin vincular) → la fila que `_is_safe_to_rebuild` busca en rebuild.py:563-566 y que `_clear_old_state` borra en rebuild.py:708. No pide turno.

El claim atómico de 22206 (`UPDATE import_normalized_tx ... WHERE excluded_at IS NULL`) **no cubre nada de esto**: sólo impide que DOS borrados de la MISMA operación importada se pisen. No repite ni el aportado ni el resultado del `_is_safe_to_rebuild`.

**Por qué no está protegido:** El par 1 no está protegido por lo mismo que el sitio anterior: los competidores no escriben la fila de `users`, y el candado de la caja es otro candado. Acá la ventana es todavía más larga porque entre la lectura (22202) y la escritura (19564) corren el rebuild del activo y el recálculo de las mediciones.

El par 2 es el caso de libro de «pregunto, me contestan que sí, y para cuando actúo la respuesta ya no vale». `_is_safe_to_rebuild` hace dos SELECT comunes (rebuild.py:563 y 567) y contesta true/false. En SQLite, el `UPDATE users` de la línea 22123 trababa la base entera, así que entre esa respuesta y el rebuild **nadie podía insertar nada**: la respuesta seguía siendo verdad. En Postgres el turno sólo traba la fila de ese usuario en `users`, y `create_operation` jamás la toca: inserta su venta a mano y commitea. Cuando el rebuild llega a la línea 22256 ya hay data manual que el chequeo no vio, y el rebuild la borra — justo lo que el chequeo existe para evitar.

Un SELECT que pregunta «¿hay filas que no debería tocar?» nunca puede quedar protegido por un candado sobre otra tabla: no hay fila que trabar, porque la fila que importa **todavía no existe cuando preguntás**. Es como contar las sillas vacías antes de apagar la luz: el que entra después no aparece en tu cuenta.

(El guard de la línea 22514 en el sitio siguiente —«el broker tiene que seguir vivo»— sí está protegido, porque borrar un broker pasa por `_borrar_datos_de_brokers`, que pide turno en 6126. Lo chequeé y lo descarto a propósito.)

**Consecuencia:** PAR 1 — **plata mal en el histórico, igual que el sitio anterior y por la misma puerta**: el depósito o el import de otro pedido se le adjudica al borrado y se escribe en el capital aportado de hasta ~1.100 fotos pasadas, deformando toda la curva de rendimiento. Irreversible por el propio comentario del código (19534-19535), y anotado en el journal (22241 + 19284) así que el «Deshacer» lo repite.

PAR 2 — **una operación cargada a mano desaparece sin dejar rastro, y la plata que movió se queda.** Secuencia concreta: en una pestaña borrás una venta importada de AAPL; en la otra (o desde el chat) cargás a mano una venta de AAPL. El rebuild de la línea 22256 borra tu venta manual (rebuild.py:712) porque el chequeo de 22177 corrió antes de que existiera. El resultado: el efectivo que `create_operation` movió (línea 20998-21001) sigue aplicado, pero la operación que lo explica ya no está, así que el P&L realizado del mes la pierde cuando `_recalc_pnl_realized_from_ops` recompone desde `operations`. Queda un saldo que ningún movimiento justifica, y el usuario no ve ningún error: simplemente su operación no está. Con `_insert_manual_position` es peor: se va el lote (rebuild.py:708) y queda el aporte automático que lo financió, o sea capital aportado fantasma sin ninguna tenencia detrás.

---

### 🔴 `_delete_position_cascade` — gravedad plata · 3 de 3 confirman

**Qué protege:** Lee DOS cosas para decidir y después borra en bloque. (1) Línea 22380: compara la cantidad que tiene el lote vivo contra la cantidad de la compra importada; si no coinciden significa que una venta ya se comió parte, y frena («Esta compra ya se vendió en parte»). (2) Línea 22388: `_is_safe_to_rebuild` pregunta si TODOS los lotes y TODAS las ventas de ese activo vinieron de un archivo importado; si hay una sola fila cargada a mano, frena. Recién después, en la línea 22406, corre `_foto_contable`, que el propio código mide en 0,8 a 1,65 segundos en una cuenta con miles de movimientos. Y en la línea 22444 llama a `rebuild_pair_asset`, que adentro hace un borrado EN BLOQUE sin condiciones (importing/rebuild.py líneas 707-714): «borrá todos los lotes de este activo en estas cuentas» y «borrá todas las ventas de este activo en estas cuentas». La única cosa que impide que ese borrado en bloque se lleve puesto algo cargado a mano es la mirada de la línea 22388, tomada 0,8 a 1,65 segundos antes. `rebuild_pair_asset` NO la vuelve a hacer: su propio comentario lo dice textualmente, «El caller DEBE haber chequeado `_is_safe_to_rebuild` antes».

**Tablas:** Lee para decidir: positions (el lote, 22340), import_op_links (22346), import_normalized_tx + import_batches (la fila de la compra en el archivo, 22355), operations (¿hay cupones o dividendos de este activo?, 22394) y otra vez positions + operations adentro de `_is_safe_to_rebuild`. Escribe: import_normalized_tx (el sello de «borrada», 22409), positions (la caja del broker al devolver la plata, 22420; y TODOS los lotes del activo adentro del rebuild), operations (todas las ventas del activo, adentro del rebuild), import_op_links, deleted_ops_journal, monthly_entries y snapshots (por la cascada).

**Quién se mete sin pedir el turno:** `sell_position_fifo` (main.py:16017, el endpoint `POST /api/positions/sell`, el botón Vender): inserta una venta en `operations` con op_type='Venta' (main.py:16245) y achica o borra el lote en `positions` (main.py:16307 y 16317). No llama a `_tomar_turno` y no escribe la fila de `users` en ningún renglón de sus 350 líneas. · `create_operation` (main.py:20956, `POST /api/operations`): inserta una operación cargada a mano (main.py:20998), mismo caso. · `_edit_position_group` (main.py:11935, editar todos los lotes de un activo de una vez): escribe `positions` (12012, 12027, 12039, 12054) y `operations` (12065). · `adjust_position_ratio` (main.py:12737, `POST /api/positions/{pid}/adjust-ratio`): cambia cantidad y precio del lote (12797). · `cobrar_plazo_fijo` (main.py:13208) y `create_conversion` (main.py:15713): insertan en `operations` (13283 y 15822). · `cobros_bonos.aplicar_amortizacion` (cobros_bonos.py:327 y 330): baja el nominal del lote. · `import_confirm` (main.py:43889 y 44086) y el persister (importing/persister.py:682, 799, 933). Ninguna de las nueve escribe la fila de `users`: lo verifiqué buscando `UPDATE users` dentro del cuerpo de cada una.

**Por qué no está protegido:** El candado que esta función se toma a sí misma (línea 22409, «poné el sello de borrada en la fila del archivo, pero sólo si nadie lo puso todavía») es un buen candado para UNA sola cosa: que dos clicks en el mismo tacho no borren dos veces la misma compra. Pero es un candado sobre OTRA fila: la del archivo importado. No repite ni la cantidad del lote (la mirada de la 22380) ni el «este activo no tiene nada a mano» (la de la 22388). Entonces las dos miradas que deciden si el borrado en bloque es seguro quedan sin ningún candado detrás, con una ventana medida de 0,8 a 1,65 segundos en el medio. En SQLite eso no se notaba nunca: el `UPDATE users SET tier=tier` de la línea 22339 agarra la base entera, así que el botón Vender esperaba parado hasta que el borrado terminara. En Postgres ese UPDATE agarra únicamente la fila de ese usuario en la tabla `users`, y el botón Vender no la escribe jamás — pasa por al lado sin enterarse. Es como poner un candado en la puerta de la cocina para proteger la heladera del garage: el candado existe y cierra bien, pero no está en el camino de nadie. Lo único que sí serializa a los dos es el candado de verdad del efectivo (`TURNO_CAJA_DEL_BROKER`), pero esta función lo toma recién en la línea 22420, DESPUÉS de la foto contable: la venta tiene todo ese tiempo para entrar y confirmarse.

**Consecuencia:** PLATA MAL Y UN BORRADO SILENCIOSO. Si el usuario (u otra pestaña, o el celular) vende ese activo justo mientras corre el borrado, pasa esto: la venta se confirma, le acredita su plata a la cuenta y queda anotada en Movimientos. Un segundo después, el borrado en bloque del rebuild ejecuta «borrá todas las ventas de este activo» y la venta DESAPARECE — con su ganancia o pérdida, que era lo único que justificaba la plata acreditada. Y encima el borrado devuelve además la plata de la compra (línea 22420). Resultado: la misma compra pagó dos veces de vuelta (la venta y el borrado), el efectivo queda inflado por la diferencia, la ganancia realizada que la venta había anotado se evapora de Reportes, y el lote reaparece entero como si nunca se hubiera vendido. No hay aviso, no hay error, no hay 409: el usuario ve una venta que hizo y que ya no está. Es exactamente el escenario que el aviso de la línea 22381 («Esta compra ya se vendió en parte… costo fabricado») existe para impedir, y que en Postgres no impide.

---

### 🔴 `_undo_manual_delete` — gravedad plata · 3 de 3 confirman

**Qué protege:** Deshacer un borrado le RESTA al lote exactamente lo que el borrado le había devuelto. Para que eso sea un reverso y no una corrupción, el lote tiene que seguir existiendo y tiene que alcanzar. Esa mirada está en las líneas 21884-21892: lee cantidad, costo y comisiones del lote vivo y frena con un 409 («cambió algo desde que borraste») si la cantidad viva es menor que la que hay que restar. Después, en la línea 21907, corre `_foto_contable` — los 0,8 a 1,65 segundos. Y recién en las líneas 22052-22063 escribe: vuelve a leer el lote y le resta. 🔴 EL PROBLEMA: al escribir vuelve a leer, pero YA NO vuelve a comprobar que alcance. El único control que queda es `if live:` (línea 22055), que pregunta «¿existe la fila?» y nada más. Y el bloque idéntico que está 10 renglones más arriba —el que restaura varios lotes a la vez, líneas 22036-22042— SÍ hace las dos comprobaciones de nuevo (`if not _live: raise` y `if cantidad < la que hay que restar: raise`). O sea: el arreglo correcto está escrito en el repo, dos pantallas más arriba, y no se propagó al hermano de al lado. Es la forma exacta que el CLAUDE.md de este repo describe como la causa raíz más frecuente: un fix aplicado en 1 de N lugares.

**Tablas:** Lee para decidir: brokers (¿siguen existiendo las cuentas donde va a volver a moverse plata?, 21861), plazos_fijos (21868), positions (la cantidad y el costo del lote, 21884 y 21896), positions otra vez para el efectivo de cada cuenta (`_efectivo_por_cuenta`, 21910), deleted_ops_journal, y `operations` vía los controles de dividendo/cupón ya anotado. Escribe: deleted_ops_journal (el sello de «ya se deshizo», claim atómico), operations (re-inserta la fila borrada), positions (el lote y la caja de efectivo, 22033, 22043, 22056, 22066), plazos_fijos, futures_positions, flujos_a_mano y monthly_entries (`_revivir_flujo_a_mano`, 22089), más monthly_entries y snapshots por la cascada.

**Quién se mete sin pedir el turno:** El mismo que arriba y por el mismo camino: `sell_position_fifo` (main.py:16017, `POST /api/positions/sell`) achica el lote con un `UPDATE positions SET quantity=…` (main.py:16317) o lo borra entero (main.py:16307), no llama a `_tomar_turno` y no escribe la fila de `users`. Él tiene su propio candado —repite la cantidad leída en el WHERE de su escritura, comentario de las líneas 16303-16310— pero ese candado lo protege a ÉL de un doble click, no protege a este deshacer. · `cobros_bonos.aplicar_amortizacion` (cobros_bonos.py:327 y 330) baja el nominal del lote de un bono, sin turno. · `_edit_position_group` (main.py:11935) cambia costo y precio de todos los lotes del activo (12012, 12027, 12039). · `adjust_position_ratio` (main.py:12737) multiplica la cantidad por el factor del split (12797). · `advisor_group_op_undo` (main.py:51390) borra lotes del cliente (`DELETE FROM positions WHERE id=? AND user_id=?`) sin turno, aunque ése compite por la MISMA fila y por eso lo resuelve el motor. Descartados por tomar el turno igual: `create_position` y `update_position` (lo piden indirectamente dentro de `_exigir_broker_existente`, main.py:11851).

**Por qué no está protegido:** Lo que protege de verdad en esta función es el sello del diario (línea 21912: «marcá este borrado como deshecho, pero sólo si nadie lo marcó») — ése es un candado bueno y evita que un doble click en «Deshacer» devuelva la plata dos veces. Y el efectivo tiene su propio candado de verdad por otro lado. Pero el LOTE no tiene ninguno: se lee sin candado en la 21884, se decide con esa foto, y 0,8 a 1,65 segundos después se escribe con un valor fresco sin volver a decidir. En SQLite daba igual porque el `UPDATE users SET tier=tier` de la línea 21843 frena la base entera y el botón Vender queda esperando. En Postgres ese UPDATE sólo agarra la fila del usuario en `users`, que el botón Vender no toca. Dicho con una analogía: el deshacer mide la caja, se va 1,5 segundos a hacer otra cosa, vuelve y saca la cantidad que había medido — sin volver a mirar si en el medio alguien sacó de esa misma caja. El hermano de al lado sí vuelve a mirar. Y `_frenar_si_deja_efectivo_negativo` (línea 22097), que es el guardián de último momento, mira SOLAMENTE el efectivo: una tenencia en negativo le pasa por abajo sin que diga nada.

**Consecuencia:** DOS DAÑOS, Y LOS DOS DE PLATA. (1) Si en el medio se vendió PARTE del lote: el deshacer le resta igual la cantidad entera y el lote queda con cantidad y costo NEGATIVOS. Una tenencia negativa se valúa negativa, así que la cartera muestra menos plata de la que hay, el costo invertido queda negativo y toda la ganancia calculada sobre ese activo pasa a ser inventada. (2) Si en el medio se vendió TODO el lote (la fila desapareció): el `if live:` de la línea 22055 no encuentra nada, no frena, no avisa — y simplemente no hace nada. Pero la plata ya se re-debitó nueve renglones antes (línea 22014) y el diario ya quedó marcado como «deshecho», así que no hay segundo intento. Resultado: al usuario le sacaron el efectivo y no le devolvieron la tenencia, en silencio y sin vuelta atrás desde la app. El bloque hermano de la línea 22040 contesta los dos casos con un 409 claro («cambió algo desde que borraste, cargalo de nuevo a mano»), que es exactamente lo que acá tendría que pasar.

---

## ❌ REFUTADO

· **`create_monthly (POST /api/monthly)`** — los 3 escépticos lo tumbaron. Afirmaba gravedad
  plata. Motivos de la refutación:
  · El daño que describe (la misma plata contada dos veces en «capital aportado», para siempre) es REAL — pero NO lo causa Postgres, y el candado de `_tomar_turno` nunca lo tapó en SQLite. El resultado final idéntico se consigue SIN ningún cruce, con un solo usuario y una sola operación a la vez.

**La cadena, confirmada línea por línea:**
1. `_derive_manual_flows` (main.py:1221-1241) calcula `manual 
  · REFUTADO como regresión de Postgres, por tres cosas distintas, y la primera sola alcanza.

**1) El candado que el reporte le atribuye a SQLite no cambia el resultado: el mismo número doble se consigue HOY en SQLite sin que nada se cruce.** El reporte dice «en SQLite esto no puede pasar, porque `_tomar_turno` (main.py:16988, definido en main.py:18695) se queda con la base entera antes de la lectura
  · REFUTADO. El cruce que describe el hallazgo no puede terminar en el doble conteo: termina en un error 400 limpio. Y el doble conteo que describe SÍ existe, pero se consigue sin ninguna simultaneidad y pasa igual en SQLite, así que no es una regresión de Postgres ni tiene que ver con `_tomar_turno`.

── 1) El cruce exacto está tapado por una regla de la base ──

El hallazgo dice: la lectura de lo i

---

## ❓ SIN VERIFICAR — hipótesis, no hallazgos

Los escépticos de estos sitios murieron por el límite. Quedan con lo que dijo el
mapeo y **nada más**. Para cerrarlos hace falta volver a correr la refutación.

| sitio | gravedad que afirma | consecuencia que afirma |
|---|---|---|
| `sections_archive` | plata | Plata mal, y no se nota en el momento sino cuando el usuario restaura. El archivo guarda una tenencia que ya no existe: 1.000 nominales cuando quedaba… |
| `bond_cashflow (POST /api/bonds/cashflow) — el fo` | plata | El mismo cupón queda cobrado DOS VECES: dos filas en Movimientos y el efectivo del broker acreditado dos veces. Un cupón de AL30 de US$ 795 deja +US$ … |
| `bond_pago (POST /api/bonds/cashflow/pago) — la b` | plata | El pago del cronograma queda cobrado dos veces, y las dos copias no son iguales: la del usuario son dos filas bien separadas (cupón como ganancia + am… |
| `dividendos_cobro (POST /api/dividendos/cobro) — ` | plata | El mismo dividendo entra dos veces: dos filas en Movimientos, dos acreditaciones en la cuenta en dólares y dos descuentos de comisión en la cuenta en … |
| `_borrar_datos_de_brokers` | plata | Plata, en tres formas. (1) Un dividendo de la cuenta que se borra cobró su comisión en pesos en la cuenta que sobrevive: si el importador lo inserta o… |
| `update_broker` | plata | Plata, y el caso realista es un import de puros pesos, que es justo el que nunca pide prestado el turno. (1) Filas huérfanas: la vista previa leyó los… |
| `_delete_one_movement (camino tx-, el de un movim` | plata | Un depósito importado queda restado DOS VECES del efectivo de ese broker. El comentario del propio código (19882) dice por qué no se autocura: «el rev… |
| `update_monthly (PUT /api/monthly/{eid})` | plata | La más grave: plata contada dos veces en «capital aportado» del mes editado y en el total de Global, permanente (casos 1 y 2). La más visible: la pers… |
| `delete_monthly (DELETE /api/monthly/{eid})` | plata | Las dos son plata mal, y PERMANENTE, porque nada las vuelve a calcular: · El `capital_inicio` de la primera fila de un broker es el capital que la per… |
| `_ensure_usd_sibling` | datos | Datos, y además queda trabado. (1) Una vista previa cuyo archivo nombra «Cocos · USD» mientras entra un depósito en dólares: los dos leen «no existe»,… |
| `undo_delete_operation` | datos | PAR 1 — **data cargada a mano que desaparece en silencio, exactamente lo que el comentario de 22505 dice que el chequeo evita.** Apretás «Deshacer» en… |
| `_foto_contable` | datos | A cada foto diaria ya escrita del mes afectado se le suma o resta la plata del movimiento AJENO. Eso es el «capital aportado» de la Evolución, que ade… |
| `close_futuro` | datos | Dos cosas distintas. (1) La posición de futuros desaparece de la pantalla Futuros aunque su resultado quedó acreditado: la operación, la plata en el e… |
| `_delete_manual_position_cascade` | datos | EL CAPITAL APORTADO DE AÑOS DE HISTORIA REESCRITO, Y SIN VUELTA ATRÁS DESDE LA APP. Si el usuario carga un depósito de, digamos, US$ 10.000 desde otra… |

---

## ✅ PROTEGIDOS también en Postgres

· **`import_mappings_save`** — El competidor que motivó este turno es el renombre de brokers, y el renombre también pide turno. En Postgres los dos escriben la fila de `users` de ese usuario, así que se esperan entre ellos: el que llega segundo se queda clavado en el `UPDATE users SET tier=tier` hasta que el primero commitea. Y c
· **`sections_restore`** — Lo que este sitio lee para decidir son `archived_positions` y `brokers`, y TODOS los caminos que pueden invalidar esa decisión piden turno: renombrar un broker, borrarlo (que además recorta el payload del archivo), archivar y restaurar. En Postgres eso los pone en fila entre sí por la fila de `users
· **`_exigir_broker_existente`** — Acá se cumple la condición buena: TODOS los que podrían invalidar la respuesta son ellos mismos clientes de `_tomar_turno`, así que en Postgres se serializan contra este sitio en la misma fila de `users`, y el que espera arranca sus sentencias siguientes con una foto fresca. Dos salvedades que anoto

---

## Cómo volver a correr la refutación de los 14

⚠️ **CORREGIDO el 28/10:** una versión anterior de esta sección decía que el
workflow se podía *reanudar* con `resumeFromRunId`. **Eso sólo funciona dentro de
la misma sesión que lo lanzó.** Desde una sesión nueva no se puede.

Lo que sí sirve desde cualquier sesión:

1. El script quedó copiado en el repo como plantilla:
   `audit/workflows/barrido_tomar_turno_24.js`. Tiene el molde de preguntas y las
   tres lentes de los escépticos, que es la parte que costó armar.
2. Los 14 sitios a verificar están en la tabla «SIN VERIFICAR» de arriba, con la
   gravedad y la consecuencia que afirmaba el mapeo.
3. Hacer un workflow **sólo de refutación** sobre esos 14 —sin volver a mapear—,
   reusando el `CONTEXTO` y las `LENTES` del script. Correr el mapeo de nuevo
   costaría lo mismo que la primera vez y no agrega nada.

⚠️ El límite de uso de la cuenta mató 44 de 71 agentes la primera vez. Con 14
sitios × 3 escépticos son 42 agentes: conviene correrlos en tandas.

---

# 🔀 EL CRUCE DE LOS DOS BARRIDOS (auditoría, 28/10/2026)

Los dos barridos preguntaban cosas distintas: el de arriba, **qué se rompe** en
cada uno de los 24 sitios; el de la auditoría (hallazgo 12 del informe), **qué
endpoints no llegan al turno**. Cruzarlos era la idea de esta sesión, y dio
exactamente lo que se buscaba: **los dos estábamos parcialmente mal, y aparece
una tercera categoría que ninguna de las dos listas tenía.**

## Las tres discrepancias

| endpoint | el barrido de arriba decía | la auditoría decía | **lo medido** |
|---|---|---|---|
| `sell_position_fifo` | intruso (no pide turno) | cubierto | 🟡 **depende de la MONEDA** |
| `create_conversion` | intruso | cubierto | 🟡 depende de la rama |
| `create_position` | intruso en una sección, **cubierto en otra** | cubierto | 🟡 depende de la rama |
| `_insert_manual_position`, `update_position` | intruso / — | cubierto | 🟡 depende de la rama |
| `_edit_position_group`, `adjust_position_ratio`, `cobrar_plazo_fijo`, `create_operation`, `import_confirm`, `advisor_group_op_undo` | intrusos | sin turno | ✅ **coinciden: NUNCA llegan** |

Los seis de la última fila son intrusos reales y los dos barridos coinciden. Las
cinco de arriba **no son ni una cosa ni la otra**.

## 🟡 La tercera categoría: «lo toma a veces», y es la peor de las tres

Los caminos, con todos los saltos verificados (el buscador se validó antes
contra dos casos conocidos: `_delete_one_movement`, directo e incondicional, y
`cash_flow`, condicional por `_pata_de_la_moneda`):

    sell_position_fifo      → _pata_de_la_moneda → _ensure_usd_sibling → _tomar_turno
    create_conversion       → _ensure_usd_sibling → _tomar_turno
    _insert_manual_position → _pata_de_la_moneda → _ensure_usd_sibling → _tomar_turno
    create_position         → _exigir_broker_existente → _tomar_turno
    update_position         → _exigir_broker_existente → _tomar_turno

Es peor que «sin turno» por un motivo: **«sin turno» se arregla y se sabe que
estaba mal; «a veces» da verde cuando lo probás y falla en producción**, según
qué esté haciendo la persona.

## 🔴 Y la condición real, MEDIDA — mi hipótesis estaba equivocada

Supuse que la rama era «la primera vez», porque pasa por `_ensure_usd_sibling`,
que **crea** la pata '· USD'. **La medición lo refutó:**

    vender en DÓLARES dentro de un broker en pesos  →  el turno SE PIDE  (1ª venta y 2ª)
    vender en PESOS (la moneda del broker)          →  el turno NO se pide  (0 veces)

No es «la primera vez»: es **la moneda de la operación**. `_ensure_usd_sibling`
toma el turno arriba aunque la pata ya exista, así que toda venta en dólares está
protegida; y toda venta en la moneda del broker, no.

👉 **El caso que queda sin candado es el común de una cuenta argentina: vender en
pesos.** La protección aparece justo en el caso menos frecuente.

Medido contando si la llamada ocurre, sin concurrencia (sonda
`test_turno_depende_de_la_moneda.py`, en el scratchpad de la auditoría). En
SQLite se saltea a propósito: allá el motor serializa igual y el turno no cambia
nada.

## Lo que queda como método

**Un grafo de llamadas dice «puede», no «hace»** — y éste es el segundo caso que
lo prueba, después de `/api/cash/flow`. Pero hay una vuelta más: entre «puede» y
«hace» hay un «hace a veces», y **de qué depende ese "a veces" no se lee en el
grafo: hay que medirlo**. Yo tenía la condición equivocada y la habría escrito
mal si no la hubiera contado.

Tres instrumentos propios fallaron en este barrido y los tres se cazaron igual:
cruzando contra un segundo método.
  · el grafo de alcanzabilidad dio `/api/cash/flow` como cubierto → lo refutó la
    traza de candados de Postgres (`Lock/advisory`, no la fila de `users`);
  · un `awk` que buscaba desde la línea del `def` cruzó al cuerpo de otra función
    → lo refutó el árbol del código;
  · un armador de caminos mal escrito inventó rutas de dos pasos → lo refutó
    validarlo contra dos casos cuya respuesta ya se conocía.

---

## Cierre del cruce — 28/10/2026, medido sobre el código

Las dos listas tenían errores y el cruce los separó uno por uno. Lo que sigue
está verificado leyendo el código y con un recorrido del árbol, no deducido.

### `create_position` — **CUBIERTO**, y mi informe se contradecía

Mi barrido lo listaba como intruso en dos secciones (líneas 68 y 119 de este
documento) y como «descartado por tomar el turno igual» en otra (línea 237). **Dos
agentes míos dijeron lo opuesto y nada en mi workflow los reconcilió** — el cruce
contra una segunda lista fue lo que lo destapó.

El que tenía razón es el tercero: `_exigir_broker_existente` (main.py:11826) pide
el turno en su **primera línea** (11851), sin condición, y `create_position` la
llama en 11862 sin condicionarla. **Está cubierto.** También `create_futuro` y
`update_futuro`.

⚠️ Y acá mi propio instrumento me falló: mi detector de «¿la llamada está en un
bloque condicional?» marcaba `Try` como condicional. **Un `try:` no es una rama —
su cuerpo siempre corre.** Es, otra vez, un proxy estructural («está adentro de
algún bloque») puesto en lugar de la pregunta real («¿es condicional?»).

### `update_position` — **«A VECES», y el caso protegido es el raro**

Acá la otra lista tenía razón y la mía no. La llamada está condicionada
(main.py:12196):

    if _actual and p.broker != _actual["broker"]:
        _exigir_broker_existente(conn, uid, p.broker)

Y el comentario de arriba lo dice sin vueltas: «Sólo si CAMBIA: editar el precio
de un lote no depende de esto.»

👉 **Mover un lote a otro broker está protegido. Editarle el precio —el caso
común— no.**

### `sell_position_fifo` — **depende de la MONEDA**, no de «la primera vez»

Verificado en `_pata_de_la_moneda` (main.py, el cuerpo arranca con los retornos
tempranos): sólo se llega a `_ensure_usd_sibling` —y por lo tanto al turno— si el
broker es **en pesos** y la operación es **en dólares**. Si la operación va en la
moneda del broker, la función sale antes y el turno no se pide nunca.

👉 **Vender en dólares en un broker en pesos está protegido. Vender en pesos —el
caso común de una cuenta argentina— no.**

### El patrón, que es lo que hay que llevarse

En los tres casos **la protección aparece en el caso MENOS frecuente**:

| operación | protegida | sin protección |
|---|---|---|
| vender un lote | en dólares, en un broker en pesos | **en pesos** |
| editar un lote | moverlo a otro broker | **cambiarle el precio** |

Eso no es casualidad: el turno está adentro de ayudantes que existen para los
casos especiales (crear la pata '· USD', validar un broker nuevo). El camino
común no pasa por ningún caso especial, así que no pasa por ningún turno.

### Y el límite del método, en su forma final

Veníamos con «**un grafo de llamadas dice "puede", no "hace"**». El cruce agrega
el escalón que faltaba:

> Entre «puede» y «hace» está «**hace a veces**» — y **de qué depende ese "a veces"
> no se lee en el grafo**. Hay que ir a la rama y leer la condición.

Las dos hipótesis que tuvimos sobre ese «a veces» (una por lista) estaban mal:
«sólo la primera vez» y «siempre». La respuesta real era la moneda en un caso y
el cambio de broker en el otro, y las dos salieron de leer el `if`.


---

# 🔎 LOS 14 SIN VERIFICAR: qué se puede cerrar sin medirlos uno por uno (28/10)

Nico pidió verificar los 14. No se pueden confirmar sus consecuencias sin 14
mediciones, pero **sí se puede resolver mecánicamente la mitad estructural** —y
de paso corregir un número mío que estaba mal.

## 1 · 🔴 Mi número del hallazgo 12 estaba equivocado: era un `try`, no un `if`

Decía que 13 de los 24 piden el turno «sólo en una rama». **Falso.** Recontado
distinguiendo `try` de rama de verdad:

    se toma SIEMPRE, sin nada alrededor ......... 11
    se toma SIEMPRE, adentro de un `try` ........ 13   ← un try NO es una rama
    se toma sólo si se cumple un `if` ...........  0

**Los 24 son incondicionales.** Y la distinción cambia dónde está el arreglo: lo
condicional no es la llamada adentro de la función, es **si el pedido LLEGA a esa
función**. Una venta en pesos nunca llama a `_ensure_usd_sibling` — eso está
medido contando llamadas, y sigue en pie.

👉 Consecuencia para los 14: **todos piden el turno cuando se los alcanza.** Así
que su riesgo no depende de ellos: depende enteramente de **si existe un intruso**.

## 2 · El mapa de intrusos, mecánico

Qué tabla de las que importan escribe cada uno de los **16 endpoints que nunca
piden el turno** (más `_edit_position_group` y `adjust_position_ratio`, que
tampoco):

| tabla | cuántos escritores SIN turno la tocan |
|---|---|
| `monthly_entries` | **12** |
| `snapshots` | **12** |
| `operations` | **5** |
| `positions` | **4** |
| `flujos_a_mano` | **3** |

    create_operation, update_operation, cobrar_plazo_fijo, admin_repair_interes_pf  → monthly + snapshots + operations
    import_confirm                                                                  → monthly + snapshots + positions
    advisor_group_op_undo                                                           → monthly + flujos + positions
    broker_reconcile_cash, create_plazo_fijo                                        → monthly + flujos
    sync_unrealized, import_recalc_pnl, admin_repair_caja_1415,
      admin_repair_user_history                                                     → monthly (+ snapshots)
    post_snapshot, admin_delete_snapshot, admin_cleanup_future_snapshots,
      admin_recompute_snapshots_netdep                                              → snapshots
    _edit_position_group, adjust_position_ratio                                     → positions (+ operations)

## 3 · Qué queda verificado y qué no

**NINGUNA de las cinco tablas tiene cero escritores sin turno.** O sea que
**ninguno de los 14 se puede refutar por «no hay quien se meta»**: la precondición
estructural se cumple en los catorce.

Lo que queda sin verificar de cada uno es **sólo la consecuencia** — si el cruce
produce de verdad el error de plata que el hallazgo afirma. Y ahí vale la regla de
esta tanda, con los números de los que sí se midieron:

| hallazgo medido | el dónde | el cuánto |
|---|---|---|
| cobro doble de Rebill | ✅ cierto | 🟡 exagerado (el libro, no los días) |
| tercer creador de la caja | ✅ cierto | ✅ cierto (y ya arreglado) |
| depósito borrado → efectivo en rojo | ✅ cierto | ✅ cierto (ya arreglado) |
| la hermana del mes | ✅ cierto | 🔴 **peor** de lo afirmado (se pierde la operación) |

Tres de cuatro aciertan el dónde; el cuánto se movió en dos, una vez para abajo y
una para arriba. **Para los 14 hay que creerles el dónde y medir el cuánto** —
que es justo lo que ninguno de los dos barridos puede hacer solo.

## 4 · Por dónde empezaría

Por los que escriben `monthly_entries`, que son 12 y es la tabla de la que cuelga
toda la pantalla Mensual y Reportes. Y de ésos, por `sync_unrealized`: es el único
de los 12 que **ya tiene un hallazgo propio de una lente** («se come un
depósito»), así que tiene las dos mitades —intruso mecánico y consecuencia
afirmada— y es el más barato de cerrar.


---

# ✅ VERIFICADO: `sync_unrealized` SÍ se come el depósito (28/10)

Primero de los 14 medido. Lo elegí porque era el único con las dos mitades:
intruso mecánico (es uno de los 12 que escriben `monthly_entries` sin pedir
turno) y consecuencia afirmada por una lente («recalcula el capital del mes con
números viejos y se come un depósito»).

**El hallazgo es CIERTO, y el cuánto también.** Es el primero de los cuatro
medidos esta tanda en el que la lente no exageró ni se quedó corta.

## La forma (`main.py:15947`)

    current = SELECT capital_inicio, deposits, withdrawals, pnl_realized …   ← lee
    UPDATE monthly_entries SET pnl_unrealized=0 WHERE … id != ?              ← escribe (otras filas)
    new_cap_final = current['capital_inicio'] + current['deposits'] − … + pnl ← calcula con la FOTO
    UPDATE monthly_entries SET pnl_unrealized=?, capital_final=? WHERE id=?   ← escribe el ABSOLUTO
    _repair_monthly_chain(…)
    conn.commit()

Lee `deposits`, calcula en Python y escribe el absoluto. Un depósito que entre en
el medio suma **en la base** (`deposits = deposits + ?`), así que el
`capital_final` que esta función escribe **no lo incluye**.

Y no lo repara nadie: los invariantes de `_repair_monthly_chain` dicen
«Meses cerrados (**NO el current calendar month**): capital_final = …». Al mes en
curso no se le recalcula.

## Medido, con la ventana forzada, 6 de 6

| base | corridas | `deposits` | `pnl_unrealized` | `capital_final` | debería ser |
|---|---|---|---|---|---|
| SQLite | 3 | 500 | 200 | **1.200** | 1.700 |
| Postgres | 3 | 500 | 200 | **1.200** | 1.700 |

**Se pierden los 500 del depósito**, idéntico en los dos motores. Lo que ve la
persona es exactamente lo que decía la lente: cargó 500, «Capital aportado» lo
muestra, y «Capital final» del mes no se movió. Y como el `capital_final` del mes
es el `capital_inicio` del siguiente, el error se arrastra.

🔴 **NO es una regresión de la migración: está vivo en producción hoy.** Cae del
lado malo del discriminador — **lo primero que hace el camino es LEER**, así que
SQLite no lo cubre.

## ⚠️ Pero la EXPOSICIÓN no es la misma en los dos motores, y esto es lo que NO medí

La ventana se forzó con el envoltorio de conexión del repo
(`tests/test_dos_pedidos_a_la_vez.py`). **No medí cada cuánto se da sola**, y por
la estructura del código no es igual en cada motor:

· En **SQLite**, la sentencia siguiente al SELECT es un `UPDATE` que toma la base
  entera. O sea que la ventana natural es **entre el SELECT y ese UPDATE:
  microsegundos de aritmética en Python**. Real, pero angosta.
· En **Postgres**, ese `UPDATE` traba sólo las OTRAS filas (`id != ?`) y no toca
  ni `positions` ni `flujos_a_mano`, así que el depósito pasa igual. La ventana
  se estira **hasta el commit**, e incluye `_repair_monthly_chain`.

👉 **Mismo bug en los dos; la ventana se agranda muchísimo al pasar a Postgres.**
Eso lo digo por la estructura del código, no medido: para medirlo haría falta una
corrida sin forzar, con muchos intentos.

## El arreglo

El mismo de la hermana del mes (hallazgo 11, punto 3): **no recalcular
`capital_final` desde una foto propia.** O se suma en la base, o se relee la fila
después de escribir `pnl_unrealized`. Son los dos el mismo arreglo, en dos
funciones distintas que escriben la misma columna de la misma fila — así que
conviene unificarlo y no hacerlo dos veces.

Sonda: `test_sync_unrealized_come_el_deposito.py` (en el scratchpad de la
auditoría). Rojo en los dos motores a propósito: ese rojo ES el bug.


---

# ❌ REFUTADO (en parte): el dividendo NO se cobra dos veces con dos clicks (28/10)

Segundo de los 14 medido. La lente afirmaba: «El mismo dividendo entra dos
veces: dos filas en Movimientos, dos acreditaciones en la cuenta en dólares y
dos descuentos de comisión».

## Medido: 8 de 8, en los dos motores, UN solo dividendo

    SQLite    4 corridas:  dividendos=1  saldo_caja=100.0  resultados=[409, ok]
    Postgres  4 corridas:  dividendos=1  saldo_caja=100.0  resultados=[409, ok]

Dos clicks simultáneos sobre el mismo dividendo: entra uno, el otro recibe un
409 limpio, la caja queda con los 100 que corresponden. **El escenario que
describe la lente no se reproduce.**

## 🔑 Y por qué NO se reproduce, que es el resultado que más importa

Porque **el turno se pide ANTES del chequeo**, y el propio código dice para qué
(`main.py:15601`): «El turno ANTES de mirar si ya está anotado: dos clicks a la
vez no pueden pasar los dos el chequeo y anotarlo dos veces».

Y acá el turno **sí alcanza en Postgres**, por un motivo que vale para todo el
hallazgo 12: `_tomar_turno` es `UPDATE users SET tier=tier WHERE id=?`, y **los
dos pedidos son del MISMO usuario**, así que escriben LA MISMA fila y el segundo
espera. El turno no protege contra cualquiera — **protege contra los otros 23**,
y «dos clicks en el mismo botón» cae justo adentro de eso.

👉 **Esto refina el hallazgo 12 y conviene leerlo junto:** «24 sitios colgados de
una protección que sólo sirve en SQLite» es demasiado fuerte. Lo correcto es:
**el turno protege a los 24 entre sí en los dos motores, y no protege contra los
16 que no lo piden.** El accidente más común —el doble click— está cubierto.

## ⚠️ Lo que queda ABIERTO, y no lo medí

El intruso real de este sitio no es el otro click: es **el importador**.
`importing/persister.py:1149` inserta filas `op_type='Dividendo'`, y
`import_confirm` **no pide el turno** (está en los 16). Así que confirmar un
import que trae el dividendo, al mismo tiempo que la persona lo confirma desde
la bandeja, es el cruce que el turno NO cubre.

No lo medí: hace falta armar un lote de import de verdad. Lo que sí verifiqué es
que **el guardián mira también los dividendos importados** —tiene una segunda
consulta sin filtrar por origen, que empareja por activo dentro de la ventana
(`dividendos.py`)—, así que el agujero, si existe, es sólo de tiempo y no de
alcance. Eso descarta la sospecha peor, que era que el guardián ni los viera.

## Los dos hermanos, por forma

`bond_cashflow` (`main.py:14802`) y `bond_pago` (`main.py:14901`) tienen la forma
IDÉNTICA: turno, después `cobros_bonos.ya_registrado`, después la escritura — el
comentario de `14803` dice «El mismo freno que la bandeja». **Por forma les cabe
la misma refutación para el doble click y la misma pregunta abierta con el
importador.** Medido uno de los tres; los otros dos por forma, y lo digo así.

Sonda: `test_dividendo_dos_clicks.py` (scratchpad de la auditoría). Verde en los
dos motores: acá el verde es el resultado.


---

# 🧾 LOS 14, CERRADOS POR LECTURA (29/10) — `audit/turno_14/`

Dos tandas, un escéptico por sitio con las tres lentes (protección / alcanzable /
consecuencia), sobre una copia congelada de `22d6bb4e`, sólo lectura, sin correr
nada. **Son veredictos de lectura, no mediciones**: cada archivo trae cómo medirlo.

| sitio | veredicto | gravedad | intruso sin turno | vs. el mapeo |
|---|---|---|---|---|
| `_delete_one_movement` (tx-) | 🔴 sobrevive | plata | revert de import | igual: la caja queda restada dos veces, nada la cura |
| `delete_monthly` | 🔴 sobrevive | plata | `/api/cash/flow` | igual: capital_inicio inflado, permanente |
| `update_broker` | 🔴 sobrevive | plata | `import_confirm` | **peor**: una ventana existe también en SQLite (prod hoy) |
| `_borrar_datos_de_brokers` | 🔴 sobrevive | plata | `import_confirm` | más acotado: tenencia huérfana que se duplica al re-importar |
| `sections_archive` | 🔴 sobrevive | plata | `import_confirm` | igual/peor, baja probabilidad |
| `update_monthly` | 🟡 sobrevive | plata | `/api/cash/flow` | **exagerado**: no permanente, lo rearma `_recalc` |
| `undo_delete_operation` | 🔴 sobrevive | datos (plata con «mueve efectivo») | `create_operation` | igual + la caja queda con una venta que no existe |
| `_foto_contable` | 🔴 sobrevive | datos | `/api/cash/flow` | igual: fotos viejas torcidas, el «Deshacer» no lo corrige |
| `_delete_manual_position_cascade` | 🟡 sobrevive | datos | `/api/cash/flow` | **exagerado**: con depósito de hoy, sólo fotos del mes en curso |
| `_ensure_usd_sibling` | ✅ refutado | cosmético | — | pide el turno antes de mirar; el alta manual choca con UNIQUE |
| `close_futuro` | ✅ refutado | cosmético | `delete_futuro` | no acredita dos veces; sólo se pierde la fila histórica |
| `dividendos_cobro` | ✅ doble click refutado (medido 28/10) | — | `import_confirm` | ABIERTO: el cruce con el import no se midió |
| `bond_cashflow`, `bond_pago` | por forma = `dividendos_cobro` | — | `import_confirm` | ABIERTO, igual |

**Lo que decide el arreglo:** en los 9 que sobreviven el intruso es uno de tres
—`import_confirm`, `/api/cash/flow`, `create_operation`—, los tres en la lista de
los 16 que nunca piden el turno. Confirma la hipótesis de la sección 5.C del
handoff: **el arreglo es UNO** (que esas puertas hagan la fila con un candado que
valga en Postgres), no 9 parches. Con el cuidado del orden de candados que pide el
handoff (la caja ya tiene el suyo).
