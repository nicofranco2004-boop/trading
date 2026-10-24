"""El resultado de una venta en las DOS monedas — la cuenta vive acá y en ningún otro lado.

POR QUÉ EXISTE
──────────────
`operations.pnl_pct` es el % en la MONEDA DE LA VENTA. En una venta en pesos es el %
en pesos: GGAL comprada a $4.500 y vendida a $6.900 da +53,3 % aunque el dólar haya
pasado de 1.000 a 1.500 en el medio y en dólares se haya ganado +2,2 %. Y `pnl_usd`
de esa venta es la ganancia en pesos dividida por el dólar DEL DÍA DE LA VENTA (la
regla "FX-phantom" de los motores de venta): tampoco es la ganancia en dólares.

Esas dos columnas NO se tocan — alimentan el P&L realizado, el win rate y la curva.
Al lado se guarda el resultado en las dos monedas, cada punta a SU dólar:

    costo_ars / costo_usd      lo que costó el lote, al dólar del DÍA DE COMPRA
    cobrado_ars / cobrado_usd  lo que entró por la venta, al dólar del DÍA DE VENTA
    pnl_pct_ars / pnl_pct_usd  (cobrado − costo) / costo, en cada moneda
    pnl_sin_dato               por qué falta alguno de los dos (nunca se inventa)

La moneda en que se pagó cada punta no necesita dólar: el costo de un lote comprado
en pesos ES el costo en pesos. El dólar sólo hace falta para la OTRA moneda.

EL DÓLAR
────────
El de la cuenta (`fx.fx_version`): MEP de la fecha en v2, blue de la fecha en v1,
con la red histórica de `fx.fx_for_date` (MEP → blue). SIN el dólar de hoy como
respaldo: si no hay dato para esa fecha, el % de esa moneda queda vacío con su
motivo. Así recalcular da siempre lo mismo.

QUIÉN LA USA
────────────
· Los tres motores de venta FIFO (`main.sell_position_fifo`,
  `persister._persist_sell_fifo`, `rebuild._replay_asset`) llaman a
  `resultado_en_dos_monedas` con el lote que están consumiendo.
· El histórico y la edición de una venta llaman a `resultado_de_la_fila`, que
  despeja los mismos datos de la fila guardada y llama a la MISMA función.
"""
import json
from typing import Any, Dict, Optional

import fx as _fx

COLUMNAS = ("costo_ars", "costo_usd", "cobrado_ars", "cobrado_usd",
            "pnl_pct_ars", "pnl_pct_usd", "pnl_sin_dato")

# Los motivos de `pnl_sin_dato`. Uno solo por fila: el primero que impide un %.
SIN_FECHA_COMPRA = "sin_fecha_compra"   # el lote no tiene fecha de compra
SIN_DOLAR_COMPRA = "sin_dolar_compra"   # no hay dólar guardado para el día de compra
SIN_DOLAR_VENTA = "sin_dolar_venta"     # no hay dólar guardado para el día de venta
SIN_COSTO = "sin_costo"                 # el lote no tiene costo (0 o vacío)
MONEDA_DEL_LOTE = "moneda_del_lote"     # no se puede saber en qué moneda se compró
RETIRO = "retiro"                       # salida del activo a costo, no una venta


def _moneda(c) -> Optional[str]:
    """'ARS' o 'USD' (USDT y cualquier dólar → 'USD'). None si no hay moneda."""
    if c is None or str(c).strip() == "":
        return None
    return "ARS" if str(c).strip().upper() == "ARS" else "USD"


def _pos(x) -> Optional[float]:
    try:
        return float(x) if x is not None and float(x) > 0 else None
    except (TypeError, ValueError):
        return None


def riel_de_la_cuenta(conn, uid: int) -> str:
    """El dólar con que la cuenta valúa por fecha: MEP (v2) o blue (v1)."""
    return _fx.RIEL_MEP if _fx.fx_version(conn, uid) == _fx.FX_V2 else _fx.RIEL_BLUE


def _dolar(conn, fecha, riel) -> Optional[float]:
    if not fecha:
        return None
    return _pos(_fx.fx_for_date(conn, fecha, fallback=None, riel=riel))


def resultado_en_dos_monedas(conn, *, costo, moneda_costo, fecha_compra,
                             cobrado, moneda_venta, fecha_venta, riel,
                             tc_venta=None, retiro: bool = False) -> Dict[str, Any]:
    """El resultado de UN pedazo de venta (un lote) en pesos y en dólares.

    `costo` va en la moneda en que se COMPRÓ el lote (`moneda_costo`), con las
    comisiones de compra; `cobrado` en la moneda de la VENTA, ya sin la comisión
    de venta. `tc_venta` es el dólar que el usuario escribió en la venta, si lo
    escribió: es lo que de verdad le dieron y le gana a la serie.

    Devuelve un dict con las `COLUMNAS`, listo para el INSERT/UPDATE.
    """
    out: Dict[str, Any] = dict.fromkeys(COLUMNAS)
    mc, mv = _moneda(moneda_costo), _moneda(moneda_venta)
    if retiro:
        out["pnl_sin_dato"] = RETIRO
        return out
    if mc is None or mv is None:
        out["pnl_sin_dato"] = MONEDA_DEL_LOTE
        return out

    tc_c = _dolar(conn, fecha_compra, riel)
    tc_v = _pos(tc_venta) or _dolar(conn, fecha_venta, riel)

    def _en_las_dos(monto, moneda, tc):
        if monto is None:
            return None, None
        monto = float(monto)
        if moneda == "ARS":
            return monto, (monto / tc if tc else None)
        return (monto * tc if tc else None), monto

    costo = float(costo) if costo is not None else None
    if costo is not None and costo > 0:
        out["costo_ars"], out["costo_usd"] = _en_las_dos(costo, mc, tc_c)
    out["cobrado_ars"], out["cobrado_usd"] = _en_las_dos(cobrado, mv, tc_v)

    for m in ("ars", "usd"):
        c, v = out[f"costo_{m}"], out[f"cobrado_{m}"]
        if c and v is not None:
            out[f"pnl_pct_{m}"] = round((v - c) / c * 100, 4)
        for k in (f"costo_{m}", f"cobrado_{m}"):
            if out[k] is not None:
                out[k] = round(out[k], 6)

    if out["pnl_pct_ars"] is None or out["pnl_pct_usd"] is None:
        if costo is None or costo <= 0:
            out["pnl_sin_dato"] = SIN_COSTO
        elif not fecha_compra and (out["costo_ars"] is None or out["costo_usd"] is None):
            out["pnl_sin_dato"] = SIN_FECHA_COMPRA
        elif out["costo_ars"] is None or out["costo_usd"] is None:
            out["pnl_sin_dato"] = SIN_DOLAR_COMPRA
        else:
            out["pnl_sin_dato"] = SIN_DOLAR_VENTA
    return out


# ─── Desde una fila ya guardada (histórico y edición) ─────────────────────────

def _moneda_del_lote(conn, uid: int, op: Dict[str, Any], moneda_venta: str) -> Optional[str]:
    """En qué moneda se compró el lote que consumió esta venta.

    · Venta hecha con el botón "Vender": la foto del lote (`undo_meta_json.lot`).
    · Venta importada: la moneda de las COMPRAS importadas de ese activo en la
      fecha de compra del lote. Si ese día hubo compras en las dos monedas no se
      sabe cuál pagó → None (sin dato, no se adivina).
    · Sin rastro (o un lote semilla, que nace en la moneda de la venta): la de la venta.
    """
    try:
        meta = json.loads(op.get("undo_meta_json") or "{}") or {}
    except (TypeError, ValueError):
        meta = {}
    lote = meta.get("lot") if isinstance(meta, dict) else None
    if isinstance(lote, dict) and _moneda(lote.get("currency")):
        return _moneda(lote.get("currency"))

    importada = conn.execute(
        "SELECT 1 FROM import_op_links WHERE operation_id=? LIMIT 1", (op["id"],)).fetchone()
    if importada and op.get("entry_date"):
        try:
            from importing.persister import broker_pair
            from importing.schema import TX_VIVAS, OP_BUY
        except ImportError:  # pragma: no cover
            return moneda_venta
        par = broker_pair(conn, uid, op["broker"])
        ph = ",".join("?" * len(par))
        monedas = {_moneda(r[0]) or moneda_venta for r in conn.execute(
            f"""SELECT DISTINCT n.currency FROM {TX_VIVAS}
                 WHERE b.user_id=? AND n.broker IN ({ph}) AND n.asset_symbol=?
                   AND n.operation_type=? AND n.date=?""",
            (uid, *par, op["asset"], OP_BUY, str(op["entry_date"])[:10])).fetchall()}
        if len(monedas) > 1:
            return None
        if monedas:
            return monedas.pop()
    return moneda_venta


def es_venta_de_un_lote(op: Dict[str, Any]) -> bool:
    """Las filas que escriben los motores de venta FIFO: 'Venta' con precio y cantidad."""
    return ((op.get("op_type") or "").strip() == "Venta"
            and op.get("exit_price") is not None
            and (op.get("quantity") or 0) > 0)


def resultado_de_la_fila(conn, uid: int, op: Dict[str, Any], *, riel: str) -> Optional[Dict[str, Any]]:
    """El resultado en las dos monedas de una venta YA GUARDADA. None si la fila no
    es la venta de un lote (dividendos, cupones, futuros, conversiones, plazos fijos:
    no tienen un costo del que medir un %).

    No hay otra cuenta: despeja de la fila lo que el motor tenía en la mano —costo
    del lote, moneda, fechas, lo cobrado— y llama a `resultado_en_dos_monedas`.

    El costo sale del par que el motor dejó: `pnl_pct` = ganancia / costo, los dos
    en la moneda de la venta, así que costo = cobrado / (1 + pnl_pct/100). El dólar
    de la venta se cancela en ese cociente, por eso sirve incluso en las filas
    viejas que quedaron estampadas con un dólar equivocado.
    """
    if not es_venta_de_un_lote(op):
        return None
    moneda_venta = _moneda(op.get("currency"))
    if moneda_venta is None:
        # Filas anteriores a que se guardara la moneda: los motores de entonces
        # vendían en la moneda del broker.
        br = conn.execute("SELECT currency FROM brokers WHERE user_id=? AND name=?",
                          (uid, op["broker"])).fetchone()
        moneda_venta = _moneda(br[0]) if br else None
    if moneda_venta is None:
        out = dict.fromkeys(COLUMNAS)
        out["pnl_sin_dato"] = MONEDA_DEL_LOTE
        return out

    cobrado = float(op["exit_price"]) * float(op["quantity"]) - float(op.get("commissions") or 0)
    fx_fila = _pos(op.get("fx_to_usd"))

    # Una salida a costo (retiro de un exchange, transferencia): sin cobro y sin resultado.
    if not op["exit_price"] and not op.get("pnl_usd"):
        return resultado_en_dos_monedas(conn, costo=None, moneda_costo=moneda_venta,
                                        fecha_compra=None, cobrado=0,
                                        moneda_venta=moneda_venta, fecha_venta=op["date"],
                                        riel=riel, retiro=True)

    pct = op.get("pnl_pct")
    costo_venta = None   # el costo del lote, en la moneda de la VENTA
    if pct is not None and abs(float(pct) + 100) > 1e-9:
        costo_venta = cobrado / (1 + float(pct) / 100)
    elif pct is not None and op.get("pnl_usd") is not None:
        # −100 %: la fórmula de arriba divide por cero; el costo es lo cobrado − el
        # resultado, con el resultado llevado de vuelta a la moneda de la venta.
        if moneda_venta == "USD":
            costo_venta = cobrado - float(op["pnl_usd"])
        elif fx_fila:
            costo_venta = cobrado - float(op["pnl_usd"]) * fx_fila

    moneda_lote = _moneda_del_lote(conn, uid, op, moneda_venta)
    if moneda_lote is None:
        out = dict.fromkeys(COLUMNAS)
        out["pnl_sin_dato"] = MONEDA_DEL_LOTE
        return out

    # El motor llevó el costo del lote a la moneda de la venta (`fx.costo_en_moneda_de_venta`).
    # Se deshace esa conversión con el mismo dólar que usó para volver a la moneda del lote.
    entry_date = op.get("entry_date")
    costo = costo_venta
    if costo is not None and moneda_lote != moneda_venta:
        if moneda_lote == "USD":      # lote en dólares vendido en pesos: al dólar de la venta
            costo = costo / fx_fila if fx_fila else None
            if costo is None:
                out = dict.fromkeys(COLUMNAS)
                out["pnl_sin_dato"] = SIN_DOLAR_VENTA
                return out
        else:                         # lote en pesos vendido en dólares: al dólar de la compra
            tc_c = _dolar(conn, entry_date, riel)
            if not tc_c:
                out = dict.fromkeys(COLUMNAS)
                out["pnl_sin_dato"] = SIN_FECHA_COMPRA if not entry_date else SIN_DOLAR_COMPRA
                return out
            costo = costo * tc_c

    # El dólar de la venta: en una cuenta v2 el que quedó estampado en la fila es el
    # de la fecha (o el que escribió el usuario). En v1 el estampado puede ser el
    # dólar del día del import, así que se busca el de la fecha.
    tc_venta = fx_fila if (moneda_venta == "ARS" and riel == _fx.RIEL_MEP) else None
    return resultado_en_dos_monedas(conn, costo=costo, moneda_costo=moneda_lote,
                                    fecha_compra=entry_date, cobrado=cobrado,
                                    moneda_venta=moneda_venta, fecha_venta=op["date"],
                                    riel=riel, tc_venta=tc_venta)


def guardar(conn, uid: int, op_id: int, resultado: Optional[Dict[str, Any]]) -> None:
    """Escribe las columnas del resultado en la fila (o las vacía si es None)."""
    r = resultado or dict.fromkeys(COLUMNAS)
    conn.execute(
        f"UPDATE operations SET {', '.join(c + '=?' for c in COLUMNAS)} "
        "WHERE id=? AND user_id=?",
        (*[r.get(c) for c in COLUMNAS], op_id, uid))


def recalcular_fila(conn, uid: int, op_id: int) -> None:
    """Re-deriva el resultado de una fila desde lo que tiene guardado."""
    row = conn.execute("SELECT * FROM operations WHERE id=? AND user_id=?",
                       (op_id, uid)).fetchone()
    if row:
        guardar(conn, uid, op_id, resultado_de_la_fila(conn, uid, dict(row),
                                                       riel=riel_de_la_cuenta(conn, uid)))


def recalcular_historico(conn, *, uid: Optional[int] = None, apply: bool = False,
                         muestra: int = 20) -> Dict[str, Any]:
    """Completa el resultado en dos monedas de las ventas guardadas que no lo tienen.

    Idempotente: sólo mira filas con las 7 columnas vacías, así que apretarlo dos
    veces no hace nada la segunda, y nunca pisa lo que escribió un motor de venta.
    `apply=False` sólo cuenta y muestra.
    """
    where = ("op_type='Venta' AND pnl_pct_ars IS NULL AND pnl_pct_usd IS NULL "
             "AND pnl_sin_dato IS NULL")
    params: list = []
    if uid is not None:
        where += " AND user_id=?"
        params.append(uid)
    filas = conn.execute(f"SELECT * FROM operations WHERE {where} ORDER BY user_id, id",
                         params).fetchall()
    rieles: Dict[int, str] = {}
    conteo = {"filas": 0, "con_los_dos": 0, "sin_dato": {}, "no_es_venta": 0}
    ejemplos = []
    usuarios = set()
    for f in filas:
        op = dict(f)
        u = op["user_id"]
        if u not in rieles:
            rieles[u] = riel_de_la_cuenta(conn, u)
        res = resultado_de_la_fila(conn, u, op, riel=rieles[u])
        if res is None:
            conteo["no_es_venta"] += 1
            continue
        conteo["filas"] += 1
        usuarios.add(u)
        if res["pnl_sin_dato"]:
            conteo["sin_dato"][res["pnl_sin_dato"]] = conteo["sin_dato"].get(res["pnl_sin_dato"], 0) + 1
        else:
            conteo["con_los_dos"] += 1
        if len(ejemplos) < muestra:
            ejemplos.append({"id": op["id"], "fecha": op["date"], "activo": op["asset"],
                             "moneda": op.get("currency"), "pnl_pct_guardado": op.get("pnl_pct"),
                             "pnl_pct_ars": res["pnl_pct_ars"], "pnl_pct_usd": res["pnl_pct_usd"],
                             "sin_dato": res["pnl_sin_dato"]})
        if apply:
            guardar(conn, u, op["id"], res)
    if apply:
        conn.commit()
    return {"applied": bool(apply), "usuarios": len(usuarios), **conteo, "ejemplos": ejemplos}
