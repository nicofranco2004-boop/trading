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
