# Veredicto: `_foto_contable` — NO refutado (sólo en Postgres)

**En una frase:** si alguien carga un depósito o un retiro justo mientras borra otro movimiento, en Postgres el borrado le suma (o le resta) a las fotos diarias viejas también la plata del depósito ajeno. El capital aportado de la Evolución queda torcido hacia atrás y no se arregla solo. En SQLite (producción hoy) no pasa: ahí el turno frena a la base entera.

## Lente 1, protección no vista: NO la tumba
- `_foto_contable` (main.py:18741) toma el turno (`_tomar_turno`, main.py:18784 → `UPDATE users SET tier=tier`). Después recompone las cuentas dentro de un punto de guardado y lee el «antes» (`canon`, main.py:18795). Ese punto de guardado se deshace (main.py:18797).
- Intruso: `POST /api/cash/flow` (`cash_flow`, main.py:14601). **No pide el turno.** Lo que sí hace:
  - toma sólo el candado de la caja de SU broker (`_adjust_broker_cash` → `efectivo.tomar_saldo`, main.py:14640);
  - anota el flujo (`_registrar_flujo_a_mano`, main.py:14674);
  - repara la cadena del broker y la de `global` (main.py:14680-14681).

  Si el borrado y el depósito son de brokers distintos, los candados de caja no se cruzan.
- Ningún índice único ni CHECK impide el cruce: las dos escrituras son legítimas.
- El propio docstring de `_foto_contable` lo admite: «en Postgres… un import o un depósito pasan igual».
- Postgres trabaja por defecto en READ COMMITTED: cada consulta ve lo último que otros ya confirmaron. No encontré en el código nada que suba ese nivel de aislamiento.

## Lente 2, alcanzable: SÍ
Puerta del sitio: `DELETE /api/movements/mf-{id}` (main.py:20072) → `_borrar_una_carga_a_mano` (lee el antes en main.py:19832) → `_cascade_after_movement_delete` (main.py:20068). Esa cascada recalcula todo y vuelve a leer lo aportado con `c1 = _twr.netdep_canonico` (main.py:19118).

Lo dispara cualquier usuario por HTTP: dos pestañas, el chat (que carga flujos) o un asesor que opera la cuenta de un cliente (`get_effective_user`).

**La ventana es larga y encima la fabrica el mismo código.** Paso a paso:
1. Mientras el borrado recompone el «antes» (0,8 a 1,65 s en una cuenta con miles de imports), traba las filas `global` de `monthly_entries`.
2. El depósito, que llegó en ese momento, queda esperando en esas filas.
3. Esas trabas se sueltan en el ROLLBACK TO SAVEPOINT, que corre justo DESPUÉS de leer el «antes».
4. El depósito sigue y confirma, mientras el borrado se queda esperando sus filas o sigue con lo suyo.
5. El recálculo de la cascada ya ve el depósito confirmado.

El orden peligroso no es mala suerte: es el que sale naturalmente.

## Lente 3, consecuencia: queda escrito, igual de grave que lo dicho por el mapeo (con un matiz)
- `delta[mes] = c1 − c0` (main.py:19154) queda como −lo_borrado + lo_ajeno en los meses de lo ajeno en adelante.
- Por el camino M (cargas con hora), las cargas ya no explican el cambio y el cálculo pasa al camino B.
- B busca un salto igual al delta y no lo encuentra. Entonces pasa una de dos cosas:
  - **Caso (a), el del mapeo:** cae al paso B.3 y aplica el delta desde la fecha de lo borrado. Las fotos diarias ya escritas reciben +lo_ajeno, que no tenían, sin importar si quedan antes o después de cuando entró el depósito.
  - **Caso (b), un error distinto:** B.1 no encuentra ningún cierre que «lo tuviera» y no toca nada. Las fotos quedan CON lo borrado adentro.

  Las dos cosas se escriben en `UPDATE snapshots SET net_deposited=?` (main.py:19671).
- El plan se anota en el diario del borrado, así que un deshacer devuelve exactamente lo mismo: no corrige nada.
- **No lo tapa ningún recálculo.** `_recalc_pnl_realized_from_ops` y `_repair_monthly_chain` reparan `monthly_entries`, no `snapshots.net_deposited` de días pasados. Sólo lo re-estampan el botón del admin o la reparación de historial, que corren a mano.
- En pantalla: en la Evolución, el capital aportado salta o se hunde en días donde no hubo movimiento. El rendimiento diario y la peor caída que salen del par (valor, aportado) muestran ganancias o pérdidas inventadas del tamaño del depósito ajeno.

## Par intruso
- Sitio: `DELETE /api/movements/mf-{id}`. Lee el antes en main.py:18795 (dentro de `_foto_contable`, llamada desde main.py:19832), lee el después en main.py:19118 y escribe en main.py:19671.
- Intruso: `POST /api/cash/flow` (main.py:14601). Escribe en main.py:14674 y 14680-14681. Nunca pide `_tomar_turno`.

## Cómo medirlo (contra Postgres)
1. Usuario con dos brokers (Schwab, IBKR).
2. Depósito a mano de 1.000 en Schwab, fechado el 5 del mes pasado. Dejar que el cron saque fotos diarias de ese mes y del actual.
3. Con `_Cruce` / `y_despues` de `tests/test_dos_pedidos_a_la_vez.py`, frenar el `DELETE /api/movements/mf-{id}` justo después de su lectura `SELECT year, month, capital_inicio, deposits, withdrawals FROM monthly_entries … broker='global'`. Hay que saltear la primera lectura (la de `tal_cual`) y frenar en la segunda (la `canon`).
4. En otro hilo, `POST /api/cash/flow` de 5.000 en IBKR (sin fecha → hoy). Esperar a que confirme y recién ahí soltar el borrado.
5. **Resultado esperado si el problema existe:** las fotos del mes en curso anteriores a hoy terminan con `net_deposited` = viejo − 1.000 + 5.000 (o sin el −1.000, si cae en el caso (b)). Lo correcto es viejo − 1.000.
6. Control: en SQLite el mismo test deja viejo − 1.000, porque el depósito espera al turno.
