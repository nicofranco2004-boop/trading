"""El efectivo de un broker: la ÚNICA puerta por la que se mueve.

El saldo vive en `positions` (la fila con `is_cash=1`, columna `invested`, en la
moneda del broker). Hasta 2026-10-07 había CINCO copias de "sumarle algo al
saldo", cada una con su regla:

  · `_adjust_broker_cash` (main): dejaba quedar negativo; creaba la caja 'USD'
    para un broker en dólares.
  · `_adjust_cash` (main, conversiones y cobros de bonos): no dejaba quedar
    negativo, promediaba el TC… y rechazaba también un COBRO si el saldo ya
    estaba en rojo ("Saldo insuficiente" al acreditar un cupón).
  · `/api/cash/flow`: su propia cuenta, escribiendo el saldo como un número.
  · `/api/brokers/reconcile-cash`: escribía el saldo objetivo.
  · el importador (`_apply_cash_flow`, `_adjust_cash_permissive`): escribía el
    saldo como un número y creaba la caja 'USDT' para TODO lo que no fuera
    pesos — un Schwab importado mostraba su efectivo como Tether. En la base de
    producción del 2026-08-16: 35 de las 81 cajas de brokers en dólares eran
    'USDT', y las 35 las había creado el importador.

Ahora todas pasan por `mover`, y lo que antes distinguía a cada copia es un
parámetro explícito: ¿puede quedar negativo? ¿promedia el TC?
"""
from typing import Optional

from fastapi import HTTPException

from money_fmt import fmt_num


def asset_de_caja(moneda_broker: Optional[str]) -> str:
    """Cómo se llama la caja de un broker según su moneda.

    Pesos → 'ARS'. Dólares → 'USD'. Lo demás → 'USDT': los exchanges cripto y
    los sub-brokers '<Padre> · USD' (que se crean con moneda 'USDT'; la pantalla
    ya los muestra como USD). El nombre no cambia el valor —la valuación mira la
    moneda del broker—, pero es lo que se ve: con 'USDT' sale el logo de Tether.
    """
    if moneda_broker == 'ARS':
        return 'ARS'
    if moneda_broker == 'USD':
        return 'USD'
    return 'USDT'


def tomar_saldo(conn, uid: int, broker: str) -> None:
    """Toma el saldo de efectivo del broker PARA ESCRIBIR, antes de leerlo.

    sqlite3 abre la transacción recién en la primera escritura, así que un SELECT
    anterior lee sin bloqueo y otro pedido puede cambiar el saldo antes de que
    éste escriba. Esta escritura no cambia nada, pero desde acá hasta el commit
    nadie más puede tocar el saldo (en SQLite, la base entera —también cuando
    todavía no hay caja: un UPDATE de 0 filas igual la toma—; en Postgres, la
    fila), y lo que se lea después es lo vigente."""
    conn.execute(
        "UPDATE positions SET invested=invested WHERE user_id=? AND broker=? AND is_cash=1",
        (uid, broker),
    )


def caja(conn, uid: int, broker: str):
    """La fila de efectivo del broker (o None). Si hubiera dos, siempre la misma:
    la más vieja. Para leer el saldo VIGENTE, llamar antes a `tomar_saldo`."""
    return conn.execute(
        "SELECT id, invested, tc_compra FROM positions "
        "WHERE user_id=? AND broker=? AND is_cash=1 ORDER BY id LIMIT 1",
        (uid, broker),
    ).fetchone()


def _moneda(conn, uid: int, broker: str) -> Optional[str]:
    row = conn.execute(
        "SELECT currency FROM brokers WHERE user_id=? AND name=? LIMIT 1", (uid, broker),
    ).fetchone()
    return row["currency"] if row else None


def _moneda_para_mostrar(conn, uid: int, broker: str) -> str:
    """'USDT' de un sub-broker '<Padre> · USD' son dólares, no Tether."""
    row = conn.execute(
        "SELECT currency, parent_broker_id FROM brokers WHERE user_id=? AND name=? LIMIT 1",
        (uid, broker)).fetchone()
    if not row:
        return ''
    if row["currency"] == 'USDT' and row["parent_broker_id"]:
        return 'USD'
    return row["currency"] or ''


def mover(conn, uid: int, broker: str, delta: float, *,
          permite_negativo: bool = True,
          tc_compra: Optional[float] = None) -> Optional[int]:
    """Suma `delta` (en la moneda del broker; negativo = sale plata) al efectivo
    del broker. Devuelve el id de la fila de efectivo, o None si `delta` es 0.

    `permite_negativo`:
      · True (el motor: compras, ventas, borrados, deshacer, el importador): el
        saldo puede quedar en rojo — es la señal visible de que falta cargar
        plata, y frenar ahí dejaría la operación a medias.
      · False (lo que el usuario pide a mano: retirar, convertir): si un DÉBITO
        deja el saldo bajo cero, no se toca nada y se contesta 400 "Saldo
        insuficiente". Un CRÉDITO pasa siempre, aunque el saldo siga negativo
        (antes un cupón no se podía cobrar en una cuenta en rojo).

    `tc_compra`: dólares comprados con pesos a ese TC. Se promedia con el TC de
    los dólares que ya había (sólo los que había de verdad: un saldo en rojo no
    tiene TC que pesar), para medir después la ganancia cambiaria al venderlos.
    Sólo aplica a créditos.

    El saldo se toma para escribir ANTES de leerlo (`tomar_saldo`) y la suma la
    hace la base (`invested = invested + ?`): con dos pedidos a la vez, el
    segundo espera y ve el saldo que dejó el primero. Lo mismo vale para la
    creación: dos primeros depósitos a la vez no crean dos cajas."""
    if not delta:
        return None
    tomar_saldo(conn, uid, broker)
    fila = caja(conn, uid, broker)
    actual = float(fila["invested"] or 0) if fila else 0.0

    if delta < 0 and not permite_negativo:
        if actual + delta < -1e-6:
            moneda = _moneda_para_mostrar(conn, uid, broker)
            raise HTTPException(
                400, f"Saldo insuficiente en {broker}. Disponible: {fmt_num(actual, 2)} {moneda}".rstrip())
        if actual + delta < 0:
            delta = -actual          # el redondeo no deja un -0,0000001 de saldo

    tc_nuevo = None
    if tc_compra is not None and delta > 0:
        base = max(actual, 0.0)
        tc_previo = (fila["tc_compra"] if fila else None) or tc_compra
        tc_nuevo = (base * tc_previo + delta * tc_compra) / (base + delta)

    if not fila:
        cur = conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested, tc_compra)
               VALUES (?,?,?,1,?,?)""",
            (uid, broker, asset_de_caja(_moneda(conn, uid, broker)), delta, tc_nuevo),
        )
        return cur.lastrowid
    if tc_nuevo is not None:
        conn.execute(
            "UPDATE positions SET invested=COALESCE(invested, 0) + ?, tc_compra=? "
            "WHERE id=? AND user_id=?",
            (delta, tc_nuevo, fila["id"], uid),
        )
    else:
        conn.execute(
            "UPDATE positions SET invested=COALESCE(invested, 0) + ? WHERE id=? AND user_id=?",
            (delta, fila["id"], uid),
        )
    return fila["id"]


def tc_de_la_caja(conn, uid: int, broker: str) -> Optional[float]:
    """El TC promedio vigente de los dólares de la caja (None si no hay caja o
    todavía no tiene). Toma el saldo antes de leerlo, como `mover`."""
    tomar_saldo(conn, uid, broker)
    fila = caja(conn, uid, broker)
    return fila["tc_compra"] if fila else None


_SIN_EXPECTATIVA = object()


def _mismo_tc(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(b)))


def revertir(conn, uid: int, broker: str, delta: float, *,
             tc_compra: Optional[float] = None,
             tc_esperado=_SIN_EXPECTATIVA,
             tc_a_dejar: Optional[float] = None) -> dict:
    """Mueve `delta` como REVERSO de un movimiento anterior (borrar o deshacer una
    compra o venta de dólares) y deja el TC promedio de la caja como si ese
    movimiento no hubiera pasado.

    El saldo es exacto siempre: es una suma. El TC promedio no se puede "restar"
    sin saber qué pasó después, así que:

      · Si la caja sigue con el TC que dejó el movimiento (`tc_esperado`), nadie
        compró dólares desde entonces y se vuelve al de antes (`tc_a_dejar`):
        EXACTO. Débitos, ventas y depósitos sin TC no cambian el promedio, así
        que no estorban. Salvo que "el de antes" sea NINGUNO y queden dólares: el
        promedio también queda igual si después se compró AL MISMO TC (dos compras
        a 1.300 en una caja vacía; medido en el navegador, 2026-10-09: borrar la
        primera dejaba los 10 dólares de la segunda sin precio). Dólares sin precio
        rompen la ganancia de la próxima venta, así que conservan el que tenían.
      · Si cambió (otra compra de dólares en el medio):
          - entran dólares con `tc_compra` → se promedian a ese TC, como una
            compra (devolver los dólares de una venta borrada a su costo es
            exacto aun con compras en el medio);
          - salen dólares con `tc_compra` → se sacan del promedio (borrar una
            compra): exacto si después sólo hubo compras, aproximado si además
            hubo ventas. Sólo si quedan al menos tantos dólares como los que
            salen: la cuenta inversa divide por lo que queda, y con poco saldo
            se dispara (100 comprados a 1.000, 100 a 1.800 y 99 vendidos daban
            un dólar a 41.400). Con poco saldo el promedio no se toca;
          - salen sin `tc_compra` (rehacer una venta) → el promedio no se toca,
            como en cualquier venta.

    Devuelve el TC que tenía la caja y el que quedó, para que el reverso de este
    reverso pueda volver exacto."""
    tomar_saldo(conn, uid, broker)
    fila = caja(conn, uid, broker)
    actual = float(fila["invested"] or 0) if fila else 0.0
    tc_ahora = fila["tc_compra"] if fila else None
    if not delta:
        return {"tc_antes": tc_ahora, "tc_despues": tc_ahora}

    fijar = False
    tc_nuevo = tc_ahora
    if tc_esperado is not _SIN_EXPECTATIVA and _mismo_tc(tc_ahora, tc_esperado):
        fijar, tc_nuevo = True, tc_a_dejar
        if tc_nuevo is None and actual + delta > 1e-9:
            tc_nuevo = tc_ahora
        id_caja = mover(conn, uid, broker, delta)
    elif tc_compra is not None and delta > 0:
        id_caja = mover(conn, uid, broker, delta, tc_compra=tc_compra)
    elif tc_compra is not None and delta < 0:
        queda = actual + delta
        if tc_ahora and actual > 0 and queda >= -delta - 1e-9:
            calculado = (actual * float(tc_ahora) + delta * float(tc_compra)) / queda
            if calculado > 0:
                fijar, tc_nuevo = True, calculado
        id_caja = mover(conn, uid, broker, delta)
    else:
        id_caja = mover(conn, uid, broker, delta)

    if fijar and id_caja:
        conn.execute("UPDATE positions SET tc_compra=? WHERE id=? AND user_id=?",
                     (tc_nuevo, id_caja, uid))
    fila = caja(conn, uid, broker)
    return {"tc_antes": tc_ahora, "tc_despues": fila["tc_compra"] if fila else None}
