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

El PRECIO de los dólares (`tc_compra` de la caja: a cuántos pesos se compraron,
en promedio) también se escribe solamente acá, y es de los dólares que HAY: una
caja vacía o en rojo no tiene precio. Hasta 2026-10-11 la caja lo conservaba al
vaciarse, y los dólares que entraban después SIN precio (un dividendo, un
depósito, lo cobrado de una venta) lo heredaban: 100 dólares comprados a 400 y
vendidos, un dividendo de US$ 10 y su venta a 1.300 anotaban US$ 6,92 de
ganancia cambiaria que no existía (auditoría 2 del 2026-10-10). Y la cuenta de
esa ganancia (`venta_de_dolares`) estaba copiada en dos lugares —la conversión a
mano y la importada—, cada una leyendo el precio por su lado.
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


# Por debajo de medio centavo la caja está VACÍA: es lo que la pantalla muestra
# como 0,00. Vender "todo" suele dejar un resto así (76,923077 comprados, 76,92
# vendidos), y con el cero exacto ese resto conservaba el precio para los
# dólares que entraran después.
CAJA_VACIA = 0.005

# Las cajas que rompen la regla, en SQL: lo usan la limpieza del arranque
# (main.init_db) y el chequeo de invariantes, para que "vacía" sea una sola cosa.
SQL_CAJA_VACIA_CON_PRECIO = (
    f"is_cash=1 AND tc_compra IS NOT NULL AND COALESCE(invested, 0) < {CAJA_VACIA}")


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


def _precio_vigente(fila, saldo: float) -> Optional[float]:
    """El precio de compra de los dólares que la caja TIENE, o None: no hay caja,
    no tiene precio, o está vacía o en rojo (el que guarde no es de ningún dólar)."""
    if not fila or saldo < CAJA_VACIA:
        return None
    tc = fila["tc_compra"]
    return tc if (tc and tc > 0) else None


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


_NO_FIJAR = object()


def mover(conn, uid: int, broker: str, delta: float, *,
          permite_negativo: bool = True,
          tc_compra: Optional[float] = None,
          tc_fijo=_NO_FIJAR) -> Optional[int]:
    """Suma `delta` (en la moneda del broker; negativo = sale plata) al efectivo
    del broker. Devuelve el id de la fila de efectivo, o None si `delta` es 0.

    `permite_negativo`:
      · True (el motor: compras, ventas, borrados, deshacer, el importador): el
        saldo puede quedar en rojo — es la señal visible de que falta cargar
        plata, y frenar ahí dejaría la operación a medias.
        Dos excepciones que NO se resuelven acá sino antes, en main.py, porque
        necesitan su propio motivo (decisión de Nico, 2026-10-10): borrar un
        depósito cargado a mano (`_frenar_si_la_plata_del_deposito_no_esta`) y
        deshacer el borrado de algo cargado a mano
        (`_frenar_si_deja_efectivo_negativo`) frenan si dejarían el saldo en rojo.
      · False (lo que el usuario pide a mano: retirar, convertir): si un DÉBITO
        deja el saldo bajo cero, no se toca nada y se contesta 400 "Saldo
        insuficiente". Un CRÉDITO pasa siempre, aunque el saldo siga negativo
        (antes un cupón no se podía cobrar en una cuenta en rojo).

    `tc_compra`: dólares comprados con pesos a ese TC. Se promedia con el TC de
    los dólares que ya había (sólo los que había de verdad: un saldo en rojo no
    tiene TC que pesar), para medir después la ganancia cambiaria al venderlos.
    Sólo aplica a créditos.

    El precio es de los dólares que HAY, y esta función es la única que lo
    escribe. Si la caja estaba vacía o en rojo, el que traía no cuenta; si queda
    vacía o en rojo, queda sin precio. Lo que entra sin `tc_compra` a una caja
    con dólares y precio sigue como siempre: no mueve el promedio.

    `tc_fijo`: el precio que tiene que quedar, cuando lo decide quien llama. Sólo
    lo usa `revertir`, que repone el de antes de un movimiento; la regla de la
    caja vacía vale igual.

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

    tc_previo = _precio_vigente(fila, actual)
    if tc_fijo is not _NO_FIJAR:
        tc_nuevo = tc_fijo
    elif tc_compra is not None and delta > 0:
        base = max(actual, 0.0)
        tc_nuevo = (base * (tc_previo or tc_compra) + delta * tc_compra) / (base + delta)
    else:
        tc_nuevo = tc_previo
    if actual + delta < CAJA_VACIA:
        tc_nuevo = None

    if not fila:
        cur = conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested, tc_compra)
               VALUES (?,?,?,1,?,?)""",
            (uid, broker, asset_de_caja(_moneda(conn, uid, broker)), delta, tc_nuevo),
        )
        return cur.lastrowid
    conn.execute(
        "UPDATE positions SET invested=COALESCE(invested, 0) + ?, tc_compra=? "
        "WHERE id=? AND user_id=?",
        (delta, tc_nuevo, fila["id"], uid),
    )
    return fila["id"]


def estado_de_la_caja(conn, uid: int, broker: str) -> dict:
    """Saldo y TC promedio vigentes de la caja (`tc` None si no hay caja o todavía
    no tiene precio). Toma el saldo antes de leerlo, como `mover`."""
    tomar_saldo(conn, uid, broker)
    fila = caja(conn, uid, broker)
    return {"saldo": float(fila["invested"] or 0) if fila else 0.0,
            "tc": fila["tc_compra"] if fila else None}


_SIN_EXPECTATIVA = object()


def _mismo_tc(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(b)))


def revertir(conn, uid: int, broker: str, delta: float, *,
             tc_compra: Optional[float] = None,
             tc_esperado=_SIN_EXPECTATIVA,
             tc_a_dejar: Optional[float] = None,
             saldo_previo: Optional[float] = None) -> dict:
    """Mueve `delta` como REVERSO de un movimiento anterior (borrar o deshacer una
    compra o venta de dólares) y repone el TC promedio de la caja.

    El SALDO es exacto siempre: es una suma. El TC PROMEDIO no siempre se puede
    reponer: es un promedio móvil, y sin el registro de cada compra no se puede
    "sacar" una compra vieja de él (auditoría 2026-10-09: la cuenta inversa daba
    exacto sin ventas en el medio, pero con ventas daba un dólar a 2.200 cuando
    ninguna compra había costado más de 1.800; lo cierto queda ENTRE el promedio
    actual y esa cuenta, y no hay cómo saber dónde). Por eso:

      · Si la caja sigue con el TC que dejó el movimiento (`tc_esperado`), nadie
        compró dólares a otro precio desde entonces: se vuelve al de antes
        (`tc_a_dejar`). EXACTO, aunque en el medio haya débitos, ventas o
        depósitos sin precio (ninguno mueve el promedio). Con dos salvedades,
        porque el promedio también queda igual si después se compró AL MISMO
        precio, y "el de antes" puede no ser de ningún dólar que quede
        (`saldo_previo` = lo que había en la caja antes del movimiento):
          - la caja estaba VACÍA antes: su precio de entonces (ninguno; o, en
            las recetas escritas hasta 2026-10-11, el de una compra vieja ya
            vendida, que la caja en cero conservaba) no era de nadie. Si quedan
            dólares, entraron después a este precio y lo conservan; si no queda
            ninguno, la caja queda sin precio (`mover`: una receta vieja no
            vuelve a pegarle el suyo a una caja vacía). Sin esto, dos compras a
            1.300 y borrar la primera dejaba
            los dólares de la segunda sin precio (prueba en el navegador) o al
            precio de una compra de hace años (auditoría 2: 200 dólares a 400 →
            ganancia cambiaria falsa de US$ 138 al venderlos);
          - había dólares SIN precio antes: vuelven a no tenerlo sólo si no queda
            más de lo que había; si queda más, lo de más se compró después y
            conserva su precio (auditoría 2: 300 comprados a 1.300 quedaban sin
            precio).
      · Si cambió (otra compra a otro precio en el medio):
          - entran dólares con `tc_compra` → se promedian a ese precio, como una
            compra (devolver los dólares de una venta borrada a su costo es
            exacto aun con compras en el medio);
          - salen dólares → el promedio queda como está. Es una aproximación
            acotada: nunca inventa un precio ni se va fuera de los que hubo.

    Devuelve el TC y el saldo que tenía la caja y el TC que quedó, para que el
    reverso de este reverso pueda volver exacto."""
    tomar_saldo(conn, uid, broker)
    fila = caja(conn, uid, broker)
    actual = float(fila["invested"] or 0) if fila else 0.0
    tc_ahora = fila["tc_compra"] if fila else None
    if not delta:
        return {"tc_antes": tc_ahora, "tc_despues": tc_ahora, "saldo_antes": actual}

    if tc_esperado is not _SIN_EXPECTATIVA and _mismo_tc(tc_ahora, tc_esperado):
        tc_nuevo = tc_a_dejar
        queda, habia = actual + delta, max(float(saldo_previo or 0), 0.0)
        if queda >= CAJA_VACIA and (habia < CAJA_VACIA
                                    or (tc_a_dejar is None and queda > habia + 1e-9)):
            tc_nuevo = tc_ahora
        mover(conn, uid, broker, delta, tc_fijo=tc_nuevo)
    elif tc_compra is not None and delta > 0:
        mover(conn, uid, broker, delta, tc_compra=tc_compra)
    else:
        mover(conn, uid, broker, delta)

    fila = caja(conn, uid, broker)
    return {"tc_antes": tc_ahora, "tc_despues": fila["tc_compra"] if fila else None,
            "saldo_antes": actual}


def venta_de_dolares(conn, uid: int, broker: str, dolares: float, pesos: float,
                     tc_venta: float) -> dict:
    """A qué precio salen los dólares que se venden y cuánta ganancia cambiaria
    dejan. Llamar ANTES de debitarlos. Es la única cuenta: la usan la conversión
    a mano (`create_conversion`) y la importada (`_persist_fx`).

    Los dólares salen a su precio promedio de compra, y la ganancia es lo que se
    cobró en pesos menos lo que costaron, en dólares al TC de la venta. Sólo los
    dólares que la caja TIENE llevan ese precio:
      · sin precio (depositados, cobrados, o caja vacía): no ganan ni pierden,
        su costo es el TC de la venta;
      · lo que se vende de más (sólo un archivo puede: le faltan compras viejas
        y la caja queda en rojo): tampoco. Con 30 dólares a 400 en la caja, un
        archivo que vendía 100 a 1.300 anotaba US$ 69,23; lo que se sabe son
        los 30: US$ 20,77.

    El precio se lee con el saldo TOMADO (2026-10-07): leído sin tomar, una
    compra de dólares simultánea cambiaba el promedio entre esta lectura y el
    débito, y el costo de los dólares vendidos y el de los que quedaban no
    sumaban lo que se pagó.

    Devuelve el precio al que salen (`tc_costo`), la ganancia (`ganancia_usd`) y
    cómo estaba la caja (`saldo_antes`, `tc_antes`), para la receta del borrado."""
    tomar_saldo(conn, uid, broker)
    fila = caja(conn, uid, broker)
    saldo = float(fila["invested"] or 0) if fila else 0.0
    tc_caja = _precio_vigente(fila, saldo)
    tc_costo = tc_caja or tc_venta
    ganancia_pesos = pesos - dolares * tc_costo
    if tc_caja and dolares > saldo:
        ganancia_pesos *= saldo / dolares
    return {"tc_costo": tc_costo,
            "ganancia_usd": ganancia_pesos / tc_venta if tc_venta > 0 else 0.0,
            "saldo_antes": saldo,
            "tc_antes": fila["tc_compra"] if fila else None}
