# Veredicto: `update_monthly` (PUT /api/monthly/{eid})

**NO refutado.** Lente que decide: **consecuencia** (sobrevive protección y alcance; la consecuencia es real pero menor que lo que decía el mapeo: no es permanente).

## Qué hace el sitio (backend/main.py)
- 17127 `_tomar_turno` (en Postgres traba sólo la fila del usuario en `users`).
- 17134-17136 LEE lo manual que había: `SELECT broker, year, month, manual_deposits, manual_withdrawals FROM monthly_entries WHERE id=? AND user_id=?` → `_prev`.
- 17137 `_global_al_dia` (dos SELECT más).
- 17138-17143 ESCRIBE el renglón del broker con valores ABSOLUTOS (`deposits=?, manual_deposits=?, capital_final=?`).
- 17145-17148 `_anotar_ajuste_mensual` (14413) suma a Global la DIFERENCIA `man_dep − _prev.manual_deposits` vía `_registrar_flujo_a_mano(..., broker_ya_sumado=True)` (14259 → `_update_monthly_flow` relativo sobre Global, 14445).

## Intruso: `POST /api/cash/flow` (`cash_flow`, main.py:14601)
- Lente 1 (protección): NO pide `_tomar_turno` (ni directo ni por wrappers: `_adjust_broker_cash` = `efectivo.mover`, que toma `tomar_saldo` → `pgsesion.turno_exclusivo(TURNO_CAJA_DEL_BROKER)`, efectivo.py:103). Ese candado es de la CAJA; `update_monthly` no lo pide. Son dos candados distintos: no se excluyen. El propio comentario de efectivo.py:129-131 lo dice: «/api/cash/flow no la escribe nunca» (la fila de users). No hay índice/CHECK que lo frene (son UPDATE relativos sobre una fila existente). Postgres sin nivel de aislamiento configurado → READ COMMITTED (no hay error de serialización que obligue a reintentar).
- Escribe en el MISMO renglón: 14674 `_registrar_flujo_a_mano` → `_update_monthly_flow` (`manual_deposits = COALESCE(manual_deposits,0)+X`, `deposits+X`, `capital_final+X` en broker y en Global) + fila en `flujos_a_mano`, luego dos `_repair_monthly_chain`.
- Lente 2 (alcanzable): los dos son HTTP del usuario con `get_effective_user`. El par realista no es un doble click: es el **asesor editando /mensual del cliente** (Plan Asesor, mismo uid efectivo) mientras **el cliente carga un depósito**, o dos pestañas/dispositivos. Ventana: no hay nada lento como `_foto_contable`; son decenas de ms contra Supabase. Dos formas de cruzarse:
  - A: `cash_flow` commitea entre el SELECT de `_prev` (17134) y el UPDATE (17138): 2-3 consultas de red.
  - B: `cash_flow` ya actualizó el renglón del broker pero no commiteó (le quedan Global, el INSERT en flujos y dos `_repair_monthly_chain`); `update_monthly` lee `_prev` viejo (en PG leer no espera), su UPDATE espera a la fila, y al soltarse la PISA con valores absolutos. Esta ventana es todo el final de la transacción de `cash_flow`.
  En SQLite no pasa: el turno toma la base entera y `cash_flow` espera.

## Lente 3 (consecuencia): qué queda escrito
Ejemplo: renglón del broker y de Global del mes con manual 1.000 (al día). El asesor manda el form con 1.500; el cliente deposita 300 en ese mes.
- Orden en serie (cualquiera de los dos): Global = suma de brokers. (Si el form estaba viejo, el 300 lo pisa el form en los DOS renglones: eso es semántica del form absoluto, no de la carrera.)
- Con el cruce: broker = 1.500 (el +300 de la caja quedó pisado), Global = 1.000 + 300 + (1.500 − 1.000) = **1.800**. Global cuenta **300 de más** respecto de los brokers. Si el usuario había incluido el depósito en el form (1.800), Global queda en 2.100: el «contada dos veces» literal del mapeo.
- Hasta la pantalla: Global es lo que leen Dashboard/«capital aportado», el cron y las fotos → capital aportado inflado en X, rendimiento achicado en X. Además `_global_al_dia` de ese mes queda en falso (Global ≠ suma), así que las próximas ediciones de /mensual de ese mes no llegan a Global ('mensual_sin_global').
- **No es permanente: «tapado por recálculo».** `_recalc_pnl_realized_from_ops` (13458; 13612-13670) rearma Global (deposits Y manual_*) como suma de los brokers. Lo llaman, entre otros, `create_operation` (21129), `update_operation`, `import_confirm`, `cobrar_plazo_fijo`, `dividendos_cobro`, `bond_pago`, `delete_broker`. A la próxima operación cargada, Global vuelve a coincidir. Lo que puede quedar: fotos (snapshots) del cron escritas en el medio con el capital inflado — no verifiqué si la reconstrucción por huella (`_contabilidad_tocada`) las rehace; y una fila 'efectivo' de X en `flujos_a_mano` que ningún renglón contiene (eso ya pasa también en serie con un form viejo).

**Comparado con el mapeo: EXAGERADO.** El dónde es correcto (Global cuenta X de más), pero no es permanente (se tapa en el próximo recálculo, que es frecuente) y la ventana es de decenas de ms con dos actores simultáneos. «La persona ve un número distinto del que cargó»: el broker muestra exactamente lo que cargó el form; lo distinto es el total.

## Cómo medirlo (sólo en Postgres; en SQLite el turno lo tapa)
Test en el estilo de `tests/test_dos_pedidos_a_la_vez.py`, corriendo con la base Postgres:
1. Usuario con broker Schwab (USD), renglón del mes actual en Schwab y en Global con `manual_deposits=1000`, `deposits=1000` (Global al día).
2. `cruce = self.cruzar("SELECT broker, year, month, manual_deposits, manual_withdrawals FROM monthly_entries WHERE id=? AND user_id=?", partes=2, y_despues={<ese texto>: deposito})` — o barrera con el hilo del otro.
3. Hilo B: espera la barrera, hace `POST /api/cash/flow {"broker_name":"Schwab","direction":"deposit","amount":300,"date":<hoy>}`, y al volver hace `deposito.set()`.
4. Hilo A: `PUT /api/monthly/{eid}` con `deposits=1500` (resto igual).
5. Assert: `manual_deposits` de Global == suma de `manual_deposits` de los brokers del mes, y `deposits` de Global == suma de brokers. Sin arreglo sale Global 1.800 vs brokers 1.500 (300 de diferencia). Segundo assert opcional: `GET` del dashboard/capital aportado == 1.500.
6. Control de que el cruce se forzó: `cruce.se_juntaron`. Y un caso que muestre el tapado: llamar a `create_operation` después y ver que Global vuelve a 1.500.

Arreglo natural (no pedido): que `cash_flow` (y los demás escritores de `monthly_entries` vía `_registrar_flujo_a_mano`) tomen `_tomar_turno`, o que `_registrar_flujo_a_mano` lo tome adentro, siempre en el mismo orden respecto del candado de caja para no reintroducir el deadlock que describe efectivo.py:88-97.
