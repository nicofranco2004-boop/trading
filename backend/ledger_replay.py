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
    """Cuánto valía la cartera de esta persona en esa fecha, en USD.

    Devuelve `valor` sólo si la cobertura de precios alcanza. Con un símbolo sin
    precio el total NO es el total, y publicar un borde corto es fabricar una
    caída — por eso ante la duda devuelve None con el motivo.
    """
    import price_history as ph

    ten = tenencia_en(conn, uid, fecha)
    if not ten:
        return {"valor": None, "motivo": "sin_tenencia", "fecha": fecha}

    fx = _fx_en(conn, fecha)
    total, faltan, necesita_fx = 0.0, [], False

    for (broker, asset), qty in ten.items():
        sym = _simbolo_de(conn, uid, broker, asset)
        precio = ph.precio_en(conn, sym, fecha)
        if precio is None:
            faltan.append(sym)
            continue
        if sym.endswith(".BA"):          # cotiza en pesos → hay que pasarlo a USD
            necesita_fx = True
            if fx is None:
                faltan.append(f"{sym} (sin FX)")
                continue
            total += qty * precio / fx
        else:
            total += qty * precio

    n = len(ten)
    cubiertos = n - len(faltan)
    pct = cubiertos / n if n else 1.0
    ok = pct >= COBERTURA_MINIMA and not (necesita_fx and fx is None)

    return {
        "valor": round(total, 2) if ok else None,
        "fecha": str(fecha)[:10],
        "activos": n,
        "con_precio": cubiertos,
        "cobertura_pct": round(pct * 100, 1),
        "faltan": sorted(set(faltan))[:20],
        "fx_basis": FX_BASIS if necesita_fx else "usd",
        "motivo": None if ok else "cobertura_insuficiente",
    }
