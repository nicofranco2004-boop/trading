"""Qué tenía una persona en una fecha pasada, replayeando su ledger.

Es la pieza que CONSTRUYE un borde faltante. Con el ledger sabemos qué tenía;
con `price_history` sabemos cuánto valía. Un borde que falta no se busca: se
calcula.

Compartido — no sabe qué es un asesor ni qué es un usuario.

⚠️ DOS LÍMITES QUE HAY QUE MIRAR ANTES DE CREERLE A UN VALOR RECONSTRUIDO:

1. EL LEDGER PUEDE ESTAR INCOMPLETO. Las transferencias de títulos las filtra
   el validator y NO crean posición (por eso un export de IOL con 10 traspasos
   deja la tenencia corta hasta que se sube la foto). Y las posiciones cargadas
   a mano no están en el ledger en absoluto. Un replay sobre un ledger incompleto
   devuelve una cartera MÁS CHICA que la real — y eso, encadenado, se lee como
   una pérdida que nunca existió. Por eso `verificar_contra_hoy()`: si el replay
   no puede reproducir la cartera de HOY, que conocemos, tampoco puede
   reproducir la de enero. Es la prueba más dura que hay y sale gratis.

2. LA BASE DE CAMBIO NO ES LA MISMA. El cron valúa al MEP MEDIO; lo único que
   hay guardado por fecha es `fx_rates_daily.mep_venta`, una sola punta. Un
   borde reconstruido a la venta y otro medido al medio difieren por el spread
   (~0,7%), y encadenarlos fabrica ese retorno de la nada — es exactamente el
   bug de la "pérdida fantasma" que ya mordió al brief. Por eso cada valor sale
   estampado con su `fx_basis` y un tramo con bases distintas se marca.
"""
import logging

log = logging.getLogger(__name__)

FX_BASIS = "mep_venta"      # lo único disponible por fecha (ver límite 2)
COBERTURA_MINIMA = 0.98     # sin casi todos los precios, el total no es el total


def tenencia_en(conn, uid: int, fecha: str) -> dict:
    """{(broker, asset): cantidad} a esa fecha, replayeando el ledger.

    Mismo orden canónico que el rebuild del importador (fecha, BUY antes que
    SELL el mismo día, id): sin eso el replay y el rebuild pueden diferir, que
    es la clase de bug donde el orden de las filas decide la P&L.
    """
    from importing.schema import OP_BUY, OP_SELL
    filas = conn.execute(
        """SELECT n.broker, n.asset_symbol, n.operation_type, n.quantity
           FROM import_normalized_tx n
           JOIN import_batches b ON b.id = n.batch_id
           WHERE b.user_id = ? AND n.excluded_at IS NULL
             AND n.date <= ? AND n.asset_symbol IS NOT NULL
             AND n.operation_type IN (?, ?)
           ORDER BY n.date ASC,
                    CASE n.operation_type WHEN ? THEN 0 ELSE 1 END ASC,
                    n.id ASC""",
        (uid, str(fecha)[:10], OP_BUY, OP_SELL, OP_BUY)).fetchall()

    pos = {}
    for r in filas:
        q = float(r["quantity"] or 0)
        if q <= 0:
            continue
        k = (r["broker"] or "", (r["asset_symbol"] or "").upper())
        pos[k] = pos.get(k, 0.0) + (q if r["operation_type"] == OP_BUY else -q)
    # Un nominal negativo no es una posición corta: es el ledger avisando que le
    # falta la compra (o el traspaso que lo trajo). Se deja fuera y se reporta.
    return {k: v for k, v in pos.items() if v > 1e-9}


# Operaciones que mueven EFECTIVO. El cron incluye el cash en total_value, asi
# que un borde reconstruido sin cash no es la misma magnitud que uno medido:
# encadenarlos fabrica un escalon del tamano de la liquidez. Un cliente con 30%
# en pesos veria una caida del 30% que nunca existio.
_CASH_MAS = ("DEPOSIT", "SELL", "DIVIDEND", "INTEREST", "FUTURES_PNL")
_CASH_MENOS = ("WITHDRAW", "BUY", "FEE", "IMPUESTO")


def cash_en(conn, uid: int, fecha: str) -> dict:
    """{(broker, moneda): saldo} a esa fecha, replayeando el ledger.

    Misma logica que el resto: lo que el ledger no explica, no se inventa. Un
    saldo negativo se deja como esta y `verificar_contra_hoy` lo va a marcar
    contra la realidad — es el ledger avisando que le falta un movimiento.
    """
    filas = conn.execute(
        """SELECT n.broker, n.operation_type, n.gross_amount, n.fees, n.taxes,
                  COALESCE(n.settlement_currency, n.currency) ccy
           FROM import_normalized_tx n
           JOIN import_batches b ON b.id = n.batch_id
           WHERE b.user_id = ? AND n.excluded_at IS NULL AND n.date <= ?
           ORDER BY n.date ASC, n.id ASC""",
        (uid, str(fecha)[:10])).fetchall()

    saldos = {}
    for r in filas:
        op = r["operation_type"]
        monto = float(r["gross_amount"] or 0)
        if monto <= 0:
            continue
        k = (r["broker"] or "", (r["ccy"] or "USD").upper())
        if op in _CASH_MAS:
            saldos[k] = saldos.get(k, 0.0) + monto
        elif op in _CASH_MENOS:
            saldos[k] = saldos.get(k, 0.0) - monto
        else:
            continue
        # Comisiones e impuestos salen del efectivo en cualquier operacion.
        saldos[k] -= float(r["fees"] or 0) + float(r["taxes"] or 0)
    return saldos


def verificar_contra_hoy(conn, uid: int, tolerancia: float = 0.01) -> dict:
    """¿El replay reproduce la cartera que HOY conocemos?

    Es el chequeo que decide si a este usuario se le puede reconstruir el pasado.
    Si el ledger no puede recrear el presente —porque hubo traspasos que no
    crean posición, o porque cargó cosas a mano— tampoco va a poder recrear
    enero, y un valor reconstruido sobre eso queda corto y se lee como pérdida.
    """
    from datetime import datetime, timedelta
    hoy = (datetime.utcnow() - timedelta(hours=3)).date().isoformat()
    replay = tenencia_en(conn, uid, hoy)
    real = {}
    for r in conn.execute(
            """SELECT broker, asset, SUM(quantity) q FROM positions
               WHERE user_id=? AND COALESCE(is_cash,0)=0 GROUP BY broker, asset""",
            (uid,)).fetchall():
        real[((r["broker"] or ""), (r["asset"] or "").upper())] = float(r["q"] or 0)

    difs = []
    for k in set(replay) | set(real):
        a, b = replay.get(k, 0.0), real.get(k, 0.0)
        ref = max(abs(a), abs(b))
        if ref > 0 and abs(a - b) / ref > tolerancia:
            difs.append({"broker": k[0], "asset": k[1],
                         "replay": round(a, 6), "real": round(b, 6)})

    return {
        "reproducible": not difs,
        "activos_reales": len(real),
        "activos_replay": len(replay),
        "diferencias": sorted(difs, key=lambda d: d["asset"])[:20],
        "motivo": None if not difs else (
            "sin_ledger" if not replay and real else "ledger_incompleto"),
    }


def _simbolo_de(conn, uid: int, broker: str, asset: str) -> str:
    """El símbolo de precio, con la MISMA resolución que el snapshot."""
    from snapshots_job import position_price_key, _broker_name_sets
    brokers = [dict(r) for r in conn.execute(
        "SELECT id, user_id, name, currency, parent_broker_id FROM brokers WHERE user_id=?",
        (uid,)).fetchall()]
    ars, ar_usd = _broker_name_sets(brokers)
    tipo = conn.execute(
        "SELECT asset_type FROM positions WHERE user_id=? AND asset=? LIMIT 1",
        (uid, asset)).fetchone()
    return position_price_key(
        {"asset": asset, "broker": broker,
         "asset_type": tipo["asset_type"] if tipo else None}, ars, ar_usd)


def _fx_en(conn, fecha: str):
    """MEP de esa fecha (la punta que hay guardada). None si no hay — y sin FX
    no se valúa una pata en pesos, no se inventa una tasa."""
    r = conn.execute(
        """SELECT mep_venta FROM fx_rates_daily
           WHERE date <= ? AND mep_venta IS NOT NULL
           ORDER BY date DESC LIMIT 1""", (str(fecha)[:10],)).fetchone()
    return float(r["mep_venta"]) if r else None


def valor_en(conn, uid: int, fecha: str) -> dict:
    """Cuanto valia la cartera de esta persona en esa fecha, en USD.

    ⚠️ NO VALUA POR SU CUENTA. Arma la tenencia historica y se la pasa a
    `compute_broker_value_usd`, el MISMO motor que usa el snapshot del cron.

    Tener un segundo motor de valuacion es como se vuelve a los ~15 motores de
    retorno que este trabajo viene a cerrar — y en este repo cada divergencia
    ya costo un bug con nombre: el cash que el cron cuenta y el replay no
    (escalon falso del tamano de la liquidez), los bonos per-100, el ratio de
    CEDEAR, el factor de cripto en broker AR, el price_override. Delegando, un
    borde reconstruido y uno medido son la MISMA magnitud, que es la unica
    forma de poder encadenarlos.

    Devuelve `valor` solo si la cobertura de precios alcanza: con un simbolo
    sin precio el total NO es el total, y publicar un borde corto es fabricar
    una caida.
    """
    import price_history as ph
    from snapshots_job import (compute_broker_value_usd, position_price_key,
                               _broker_name_sets)

    ten = tenencia_en(conn, uid, fecha)
    cash = cash_en(conn, uid, fecha)
    if not ten and not cash:
        return {"valor": None, "motivo": "sin_tenencia", "fecha": str(fecha)[:10]}

    brokers = [dict(r) for r in conn.execute(
        "SELECT id, user_id, name, currency, parent_broker_id FROM brokers WHERE user_id=?",
        (uid,)).fetchall()]
    if not brokers:
        return {"valor": None, "motivo": "sin_brokers", "fecha": str(fecha)[:10]}
    ars_names, ar_usd_names = _broker_name_sets(brokers)
    ccy_de = {b["name"]: b["currency"] for b in brokers}

    # asset_type historico: si el activo ya se vendio no esta en `positions`.
    # Sacarlo de ahi hacia que un CEDEAR vendido pidiera su ticker US en vez
    # del .BA — el bug C1, 15-100x inflado. El ledger lo conserva.
    tipos = {}
    for r in conn.execute(
            """SELECT UPPER(n.asset_symbol) a, n.asset_type t
               FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id
               WHERE b.user_id=? AND n.asset_type IS NOT NULL""", (uid,)).fetchall():
        tipos.setdefault(r["a"], r["t"])
    for r in conn.execute(
            "SELECT UPPER(asset) a, asset_type t FROM positions "
            "WHERE user_id=? AND asset_type IS NOT NULL", (uid,)).fetchall():
        tipos.setdefault(r["a"], r["t"])

    # Posiciones historicas con la forma que espera el motor canonico.
    por_broker, syms = {}, set()
    for (broker, asset), qty in ten.items():
        p = {"asset": asset, "broker": broker, "asset_type": tipos.get(asset),
             "is_cash": 0, "quantity": qty, "invested": 0.0, "commissions": 0.0,
             "price_override": None, "currency": None}
        por_broker.setdefault(broker, []).append(p)
        syms.add(position_price_key(p, ars_names, ar_usd_names))
    for (broker, ccy), saldo in cash.items():
        if abs(saldo) < 0.005:
            continue
        por_broker.setdefault(broker, []).append(
            {"asset": ccy, "broker": broker, "asset_type": None, "is_cash": 1,
             "quantity": 0.0, "invested": saldo, "commissions": 0.0,
             "price_override": None, "currency": ccy})

    precios = {sm: ph.precio_en(conn, sm, fecha) for sm in syms}
    faltan = sorted(sm for sm, v in precios.items() if v is None)

    fx = _fx_en(conn, fecha)
    if fx is None and any(ccy_de.get(b) == "ARS" for b in por_broker):
        return {"valor": None, "motivo": "sin_fx", "fecha": str(fecha)[:10],
                "fx_basis": FX_BASIS}

    hay_ars = any(ccy_de.get(b) == "ARS" for b in por_broker) or any(
        sm.endswith(".BA") for sm in syms)

    total = 0.0
    for broker, pos in por_broker.items():
        r = compute_broker_value_usd(
            pos, precios, ccy_de.get(broker) or "ARS", fx or 0.0,
            broker_name=broker, cedear_rate=fx)
        total += float(r["value"])

    # La cobertura se mide por VALOR, no por conteo: un activo que pesa 40% de
    # la cartera pasaria el filtro si hay 50 activos mas.
    valor_faltante, peso_desconocido = 0.0, False
    for (broker, asset), qty in ten.items():
        sm = position_price_key({"asset": asset, "broker": broker,
                                 "asset_type": tipos.get(asset)}, ars_names, ar_usd_names)
        if precios.get(sm) is None:
            # Sin precio no se sabe cuanto pesa: se usa el costo como piso.
            c = conn.execute(
                "SELECT SUM(gross_amount) g FROM import_normalized_tx n "
                "JOIN import_batches b ON b.id=n.batch_id WHERE b.user_id=? "
                "AND UPPER(n.asset_symbol)=? AND n.operation_type='BUY'",
                (uid, asset)).fetchone()
            costo = float((c["g"] if c else 0) or 0)
            if costo <= 0:
                # Sin precio Y sin costo no se sabe cuanto pesa. Tratarlo como
                # peso CERO seria certificar una cobertura que no se midio:
                # peso desconocido = no se publica.
                peso_desconocido = True
            valor_faltante += costo

    base = abs(total) + valor_faltante
    pct = (abs(total) / base) if base > 0 else 1.0
    ok = (not faltan) or (pct >= COBERTURA_MINIMA and not peso_desconocido)

    return {
        "valor": round(total, 2) if ok else None,
        "fecha": str(fecha)[:10],
        "activos": len(ten),
        "con_precio": len(syms) - len(faltan),
        # None = no se pudo medir el peso de lo que falta. Reportar 100% y a la
        # vez negarse a publicar seria contradictorio.
        "cobertura_pct": None if peso_desconocido else round(pct * 100, 1),
        "faltan": faltan[:20],
        "fx_basis": FX_BASIS if hay_ars else "usd",
        "motivo": None if ok else "cobertura_insuficiente",
    }
