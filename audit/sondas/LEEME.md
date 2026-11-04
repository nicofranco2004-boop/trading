# Sondas rescatadas de `/tmp` — 28/10/2026

Las escribió la sesión de auditoría («Auditar arreglos de migración a Postgres»)
y vivían en su scratchpad de `/private/tmp`, que macOS purga. Una tercera
(`test_cobro_doble_del_primer_pago.py`, la del Rebill) **ya se había perdido**
cuando se rescataron éstas.

Están acá y no en `backend/tests/` **a propósito**: no se revisaron a fondo y no
tienen que entrar a la suite sin que alguien las lea. Se leyó el encabezado de las
dos y se buscó que no tuvieran claves, tokens ni rutas a `/tmp`: no tienen.

## Para correrlas

Asumen vivir en `backend/tests/` (calculan `BACKEND` como el padre de su carpeta).
Desde acá no encuentran el código. Copiarlas allá:

    cp audit/sondas/test_*.py backend/tests/
    cd backend && DATABASE_URL='<el DSN>' python3 -m pytest tests/test_<nombre>.py -q

Las dos miden algo **sólo en Postgres**; contra SQLite se saltean o pasan siempre.

## Lo que mide cada una

### `test_deposito_borrado_con_retiro.py`

Borrar un depósito cargado a mano mientras entra un retiro. Fuerza la ventana con
un handshake (A pasa el freno y espera; B retira; A sigue) y mira en
`pg_stat_activity` **quién espera a quién**. Con el arreglo `a80b43b7` puesto, B
queda bloqueado en `Lock/advisory` —el candado que pide `caja()`— y después
rechaza bien con «Saldo insuficiente».

⚠️ **Fuerza una ventana de varios segundos**, y la suite mata las transacciones
ociosas a los 6 s (`idle_in_transaction_session_timeout` del `conftest`). La
auditoría la corrió con:

    RENDI_TEST_IDLE_TX_S=45 RENDI_TEST_LOCK_S=90 ... --timeout=180

manteniendo el orden idle < lock < pytest. Sin eso, Postgres mata al pedido A por
ocioso y la sonda parece decir que el borrado falla, cuando el roto es el
instrumento.

⚠️ Abre una conexión con `psycopg.connect` directo (línea ~111) para el vigía. Si
se mueve a `backend/`, puede chocar con el guardián
`test_conexiones_pg_ajustadas.py`, que exige que toda conexión pase por
`pgsesion.conectar`.

### `test_turno_depende_de_la_moneda.py`

Cuenta si `sell_position_fifo` llega a `_tomar_turno`. No necesita concurrencia.

🔴 **SU DOCSTRING SE CONTRADICE.** El primer bloque dice —bien— que la condición
es **la moneda**: vender en dólares dentro de un broker en pesos pide el turno,
vender en pesos no. El último párrafo conserva la hipótesis vieja —«la protección
existe la primera vez y desaparece después»— que la propia medición refutó.
**Vale el primer bloque**: verificado leyendo `_pata_de_la_moneda` el 28/10, que
sólo llega a `_ensure_usd_sibling` si el broker es ARS y la operación USD. Ver el
cierre del cruce en `audit/BARRIDO_TOMAR_TURNO_24.md`.
