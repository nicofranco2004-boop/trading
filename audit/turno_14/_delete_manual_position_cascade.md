# Veredicto: `_delete_manual_position_cascade` — NO refutado (en Postgres)

**Sitio:** `backend/main.py:21776` (`_delete_manual_position_cascade`), al que se llega por `DELETE /api/positions/{pid}` (`main.py:12307` → `_borrar_posicion` `main.py:22382` → `main.py:22412`).
**Intruso:** `POST /api/cash/flow` (`cash_flow`, `main.py:14601`): un depósito o retiro a mano. **No pide el turno** (no hay `_tomar_turno` en todo el endpoint).

## Cómo funciona el borrado (lo que importa)
1. `main.py:21783` toma el turno (fila del usuario en `users`).
2. `main.py:21864` `antes = _foto_contable(conn, uid)`: recompone las cuentas dentro de un punto de guardado (0,8–1,65 s en cuentas con miles de imports, ~25 ms en una común) y lee `canon` = lo aportado de cada mes (`twr.netdep_canonico`, `main.py:18795`). Es el «antes».
3. `main.py:21870` borra la posición (reclamo con rowcount: protege contra otro borrado, no contra un depósito).
4. `main.py:21879` `_adjust_broker_cash(credit)` → toma el candado de caja (`efectivo.tomar_saldo` → `pgsesion.turno_exclusivo(TURNO_CAJA_DEL_BROKER, uid)`, por usuario). Sólo si `credit != 0`.
5. `main.py:21911` cascada → recálculo → `_cambio_de_aportado` (`main.py:18964`) lee el «después» `c1 = netdep_canonico` (`main.py:19121`) y a cada foto ya escrita le suma `c1(mes) − c0(mes)` (`main.py:19153`) → `UPDATE snapshots SET net_deposited` (`main.py:19658`).

La resta «después − antes» se le adjudica entera al borrado. Cualquier cambio de lo aportado que entre entre los pasos 2 y 5 se cuela.

## Lente 1 — protección no vista: NO la tumba
- `cash_flow` no pide turno. En Postgres el turno sólo traba la fila `users` de ese usuario, y `cash_flow` no la toca.
- Sí comparten el candado de caja (por usuario). Pero el borrado lo toma **después** de leer el «antes» (paso 4), así que no ordena el depósito respecto del «antes». Peor: si el depósito ya tiene el candado de caja cuando el borrado llega al paso 4, el borrado **espera a que el depósito confirme** y su «después» lo ve sí o sí.
- No hay índice único ni CHECK que aplique: son sumas en `monthly_entries` y `flujos_a_mano`.
- El reclamo `DELETE … rowcount` (`main.py:21870`) sólo frena otro borrado de la misma posición.
- En SQLite (producción hoy) no pasa: el turno traba la base entera. El propio docstring de `_foto_contable` (`main.py:18758-18766`) lo reconoce: «en Postgres … un import o un depósito pasan igual».

## Lente 2 — alcanzable: SÍ
- Los dos se disparan por HTTP, con el mismo usuario (otra pestaña, el chat que hace depósitos/transferencias, o un asesor operando la cuenta del cliente vía `get_effective_user` mientras el cliente borra).
- La ventana no es de microsegundos: el depósito tiene que estar «en vuelo» en el instante en que el borrado lee el «antes». Además, durante el recálculo del paso 2 el borrado tiene trabadas las filas de `monthly_entries` del usuario (dentro del punto de guardado). Un depósito que llegue en esos 0,8–1,65 s toma el candado de caja, se queda esperando en `monthly_entries`, se destraba cuando el borrado deshace el punto de guardado (ya leído el «antes») y confirma mientras el borrado espera el candado de caja. Toda la duración de `_foto_contable` funciona como ventana.

## Lente 3 — consecuencia: real, pero más chica que lo que decía el mapeo en el caso típico
Lo que queda escrito:
- `monthly_entries`, `flujos_a_mano` y el efectivo quedan **bien** (el recálculo los recompone desde las fuentes). No se fabrica plata.
- Lo que queda mal es `snapshots.net_deposited` (el capital aportado que guarda cada foto diaria). Las fotos de los meses donde `c1 − c0` incluye el depósito reciben **el depósito sumado como si lo hubiera cambiado el borrado**. Si el borrado no tocaba lo aportado (una compra pagada con efectivo, sin autodepósito: el caso más común), las fotos igual reciben el depósito entero: `cambiados` deja de estar vacío (`main.py:19162`). Con autodepósito, las «capas» M no cuadran y cae en el camino B (`main.py:19170`).
- **Alcance según la fecha del depósito:**
  - Depósito de hoy (lo normal): sólo cambia el mes en curso. Las fotos de este mes anteriores a hoy quedan con el depósito adentro, aunque eso todavía no había pasado. La de hoy se borra y se rehace (`main.py:19663`). Son de 1 a 30 fotos, no «años».
  - Depósito con fecha vieja (`CashFlowIn.date`, `main.py:13423`, usado por el chat y el calendario): todas las fotos desde ese mes (y desde la fecha de la posición) reciben el depósito. Ahí sí son años de historia.
- **En pantalla:** en la curva del Dashboard, el rendimiento (TWR) y la peor caída, el aportado sube y el valor no, así que aparece como una **pérdida** del monto del depósito en esos días. También se ve en el chip de capital aportado en fechas pasadas.
- **Ningún proceso lo tapa:** `_repair_monthly_chain` y `_recalc_pnl_realized_from_ops` no tocan `snapshots`, y el cron sólo estampa fotos nuevas. Formas de deshacerlo: el «Deshacer» del borrado, que devuelve exactamente el plan anotado en el journal (incluido el depósito colado), o el botón del admin que vuelve a anclar los meses (tiene sus propios errores conocidos). «Sin vuelta atrás» es exagerado: hay un deshacer, pero nadie sabe que hay que usarlo.

**Comparado con el mapeo:** acierta en el DÓNDE. En el CUÁNTO, exagera en el caso típico (un mes, no años) y queda igual si el depósito tiene fecha vieja. Gravedad: **datos** (la historia de lo aportado y el rendimiento quedan mal; los saldos y la plata no).

## Cómo medirlo (sólo en Postgres; en SQLite el cruce no existe)
Usar el esquema de `tests/test_dos_pedidos_a_la_vez.py` (envoltorio de conexión con `threading.Barrier` que frena en un fragmento de SQL), pero contra una base Postgres real:
1. Usuario con broker Schwab (USD, efectivo 1.000), una posición cargada a mano el mes pasado (con `undo_meta_json`, pagada con efectivo, sin autodepósito) y fotos diarias desde el día 1 del mes en curso hasta ayer, con `net_deposited` = X.
2. Hilo A: `DELETE /api/positions/{pid}`. Frenarlo con la barrera justo después del `SELECT … FROM monthly_entries WHERE broker='global'` de `netdep_canonico` dentro de `_foto_contable` (el «antes»).
3. Hilo B: `POST /api/cash/flow` con depósito de 500 sin fecha, que confirma mientras A está frenado. Soltar A.
4. **Esperado:** las fotos de este mes anteriores a hoy siguen en X (el borrado de una compra pagada con efectivo no cambia lo aportado).
   **Saldría mal:** quedan en X + 500, y el journal anota `aportado.fotos` con +500 en cada una.
5. Variante «años»: B con `date` = hace 18 meses. Todas las fotos desde la fecha de la posición quedan +500.
