# Veredicto: `delete_monthly` (DELETE /api/monthly/{eid})

**Refutado: NO.** Gravedad: **plata**. Ninguna de las tres lentes lo tumba.

## Qué hace el sitio
`delete_monthly` (main.py:17162) pide el turno (main.py:17168), lee el renglón y llama a
`_borrar_filas_de_la_cadena` (main.py:13838). Esa función lee las filas del broker
(main.py:13881) y, si se borra la PRIMERA fila, le pasa su arranque declarado a la que queda
primera (UPDATE en main.py:13897) y después borra (main.py:13904). Así el dinero del mes
borrado no se convierte en «capital que ya tenías».

## El intruso concreto
**POST /api/cash/flow** (`cash_flow`, main.py:14601), un depósito o retiro con fecha.
- **No pide el turno.** Toma solamente el candado de la caja (`efectivo.tomar_saldo` →
  `pgsesion.turno_exclusivo(TURNO_CAJA_DEL_BROKER)`, efectivo.py:67-103), que
  `delete_monthly` NO toma. En Postgres no se esperan entre ellos.
- Va por `_registrar_flujo_a_mano` (main.py:14674) → `_update_monthly_flow`. Si el mes no
  tiene renglón, lo crea con `_capital_inicio_de_fila_nueva` (lectura en main.py:14182, la
  función está en main.py:14029): **copia el `capital_final` del mes anterior que VE**.
- Con el mismo mecanismo entran `create_operation` (vía `_update_monthly_pnl_realized`,
  lectura en main.py:14100) y el import.

## El cruce (Postgres, READ COMMITTED)
Broker con un solo renglón: noviembre, depósito de 100.000 → `capital_final` = 100.000.
1. A: el usuario borra noviembre. `delete_monthly` abre la transacción, ve sólo [nov]: no hay
   ninguna fila siguiente a la que pasarle el arranque. Borra noviembre, pero todavía no confirma.
2. B: al mismo tiempo, un depósito de 500 fechado en diciembre. `_capital_inicio_de_fila_nueva`
   todavía VE noviembre, porque el borrado de A no está confirmado, y crea diciembre con
   `capital_inicio` = 100.000 y `capital_final` = 100.500.
3. Los dos confirman. Diciembre queda como **primera fila del broker, con 100.000 de arranque**:
   los mismos 100.000 que el borrado tenía que sacar.

La variante con más filas también rompe: [nov, ene] y B crea dic en el hueco. A ve
[nov, ene] y le pasa el arranque a enero. B crea dic con `capital_inicio` = el `capital_final`
viejo de nov. Su reparación de la cadena traba la fila de enero hasta que A confirma, y eso
fuerza justo el orden malo. Termina igual: diciembre primera, con la plata borrada adentro.
El resultado no coincide con ninguno de los dos órdenes en serie. Si va primero A, diciembre
arranca en 0. Si va primero B, el borrado ve diciembre enganchada y le pasa el arranque correcto.

En SQLite no pasa: el primer UPDATE de `tomar_saldo` toma la base entera y los dos pedidos van
de a uno.

## Lente 1: protección no vista
- El turno de `delete_monthly` traba sólo la fila de `users`, y `cash_flow` nunca la toca.
- El candado de caja es otro y `delete_monthly` no lo pide.
- No hay índice único que lo frene: el UNIQUE es (user_id, year, month, broker) y los meses son
  distintos.
- `_capital_inicio_de_fila_nueva` lee antes de escribir, sobre una fila que otro está borrando.
- No hay ningún UPDATE condicional del tipo «reclamo».

**No refuta.**

## Lente 2: alcanzable
- Se dispara por HTTP, con un usuario común.
- Ventana: los dos pedidos tienen que solaparse. B tiene que leer noviembre antes de que A
  confirme, y A tiene que leer sus filas antes de que B confirme. La transacción de A dura
  milisegundos: `_restar_flujo_a_mano`, el borrado y dos reparaciones de cadena. En B, antes
  de esa lectura, corren `fx_for_date` (dólar de la fecha) y el movimiento de caja.
- Es una ventana angosta, pero real. Lo hacen posible dos pestañas, o el chat cargando un
  movimiento mientras la persona borra un mes en /mensual.
- El caso más natural es borrar el último mes cargado mientras se deposita en el mes en curso.

**No refuta.**

## Lente 3: consecuencia
- La primera fila de cada broker se lee como capital declarado en todos lados:
  `compute_net_deposited` del cron, `compute_net_deposited_db`, `twr.netdep_canonico`,
  Reportes y el Dashboard. Queda +100.000 de aportado fantasma, que es el denominador del
  rendimiento.
- `_repair_monthly_chain` no toca la primera fila (main.py:13743 y siguientes).
- `_recalc_pnl_realized_from_ops` dice explícitamente que no la toca (main.py:~13705).
- Nadie la vuelve a calcular. **Permanente**, hasta que la persona la edite a mano en /mensual.
- Comparado con lo que afirmaba el mapeo: **igual**. El mapeo dice que el arranque de la
  primera fila «se pierde o se recalcula con datos viejos» y que nada lo vuelve a calcular. El
  mecanismo exacto es que el que escribe el dato viejo es el intruso (copia el `capital_final`
  del renglón que se está borrando), no `delete_monthly`.

## Cómo medirlo (test en Postgres, al estilo de `backend/tests/test_dos_pedidos_a_la_vez.py`)
1. Preparar el broker con un solo renglón: noviembre, depósito de 100.000.
2. Usar el `Cruce`/barrera del archivo para frenar `delete_monthly` justo después del
   `DELETE FROM monthly_entries` y antes de que confirme. Por ejemplo, envolver
   `_repair_monthly_chain` para que la primera llamada espere en la barrera.
3. Mientras está frenado, lanzar en otro hilo `POST /api/cash/flow` con un depósito de 500
   fechado en diciembre. Dejar que llegue a su INSERT y soltar la barrera.
4. Esperado: diciembre con `capital_inicio` = 0, y lo aportado del broker = 500.
5. Saldría: `capital_inicio` = 100.000, y lo aportado = 100.500.

Variante con dos filas: [nov, ene] y el depósito en diciembre. Ahí sólo hace falta que las dos
transacciones se solapen, porque la traba sobre enero ordena sola a los dos pedidos.
