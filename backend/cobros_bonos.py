"""Cobros de bonos: cuándo un pago del cronograma ya está anotado.

Gemelo de `dividendos.py` para la renta fija. La bandeja de Cartera
(`frontend/src/utils/pendingCashflows.js`) propone los pagos del cronograma que
ya pasaron y no están anotados; el usuario los confirma por
`POST /api/bonds/cashflow/pago`. Este módulo tiene la regla de "ya está anotado"
del lado del servidor, la MISMA que usa la bandeja (`cobroRegistrado`):

  · un cobro de renta del activo —'Cupón' o 'Amortización' cargados a mano,
    'Dividendo' / 'Interés' / 'Renta' importados (el importador guarda así los
    cupones: `persister._persist_dividend_or_interest`)—
  · en cualquier cuenta del broker (la de pesos o la de dólares: el cupón en
    dólares de un bono comprado en pesos entra a «Cocos · USD»),
  · a ±14 días de la fecha del cronograma (el broker acredita T+1, T+2 o tarde).

La usan dos puertas:
  · la bandeja, para no anotar dos veces un pago que ya está (409);
  · el importador, cuando trae el cobro de un pago que el usuario ya había
    cargado a mano: la fila del archivo se saltea con un aviso
    (`cubierto_por_lo_anotado`, `main._cobro_bono_confirmado_a_mano`).
"""
from __future__ import annotations

import unicodedata
from datetime import date, timedelta

# Días de tolerancia alrededor de la fecha del cronograma. ESPEJO de
# DATE_TOLERANCE_DAYS en frontend/src/utils/pendingCashflows.js.
VENTANA_DIAS = 14

# Los op_type que son cobro de renta de un bono, sin tildes ni mayúsculas. ESPEJO
# de TIPOS_DE_COBRO en pendingCashflows.js ('Interés PF' —plazo fijo— no entra).
TIPOS_DE_COBRO = ("CUPON", "AMORTIZACION", "DIVIDENDO", "INTERES", "RENTA")


def _norm(t) -> str:
    t = unicodedata.normalize("NFD", str(t or "").strip().upper())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def es_cobro_de_renta(op_type) -> bool:
    return _norm(op_type) in TIPOS_DE_COBRO


def _ventana(fecha: str) -> tuple:
    d = date.fromisoformat(fecha[:10])
    return ((d - timedelta(days=VENTANA_DIAS)).isoformat(),
            (d + timedelta(days=VENTANA_DIAS)).isoformat())


def ventas_que_son_amortizacion(conn, uid: int) -> set:
    """ids de las operaciones IMPORTADAS como venta que en realidad son el pago de
    una amortización. Balanz trae "Renta y Amortización" con cantidad, y su lector
    la convierte en una VENTA de esos nominales por lo cobrado
    (`parsers/balanz_movimientos.py`); la marca es la de siempre: la nota del
    renglón dice "amortiz" (`maturity._bond_genuine_net`).

    Son un COBRO del bono aunque se llamen "Venta": sin contarlas, la bandeja
    ofrecía como pendiente un pago que ya había entrado y el importador lo sumaba
    encima del confirmado (auditoría 2026-10-10; en la copia de producción del
    16/08: 403 operaciones de 46 usuarios)."""
    from importing.schema import TX_VIVAS, OP_SELL
    return {r["operation_id"] for r in conn.execute(
        f"""SELECT DISTINCT l.operation_id
              FROM {TX_VIVAS}
              JOIN import_op_links l
                ON l.batch_id = n.batch_id AND l.raw_row_id = n.raw_row_id
             WHERE b.user_id=? AND n.operation_type=? AND l.operation_id IS NOT NULL
               AND lower(COALESCE(n.notes,'')) LIKE '%amortiz%'""",
        (uid, OP_SELL)).fetchall()}


def _cerca(conn, uid: int, broker: str, asset: str, fecha: str):
    from importing.persister import broker_pair
    par = broker_pair(conn, uid, broker)
    ph = ",".join("?" * len(par))
    desde, hasta = _ventana(fecha)
    filas = conn.execute(
        f"""SELECT * FROM operations
             WHERE user_id=? AND broker IN ({ph}) AND UPPER(TRIM(asset))=?
               AND date >= ? AND date <= ?""",
        (uid, *par, (asset or "").strip().upper(), desde, hasta + "~")).fetchall()
    ventas_amort = ventas_que_son_amortizacion(conn, uid) if filas else set()
    return [f for f in filas if es_cobro_de_renta(f["op_type"]) or f["id"] in ventas_amort]


def ya_registrado(conn, uid: int, broker: str, asset: str, fecha: str):
    """La primera fila que ya cuenta como el pago del cronograma `fecha`, o None."""
    filas = _cerca(conn, uid, broker, asset, fecha)
    return filas[0] if filas else None


def choca_con_lo_anotado(conn, uid: int, broker: str, asset: str, fecha: str, op_type: str):
    """Para anotar UNA parte de un pago (el cupón, o la amortización): la fila ya
    anotada que lo impide, o None. Choca con cualquier cobro IMPORTADO de la
    ventana (el archivo trae el pago entero) y con uno a mano del mismo tipo.

    La usan el formulario de la ficha del bono —que carga las dos partes por
    separado— y el "Deshacer" del borrado de un cobro (que lo vuelve a poner)."""
    for f in _cerca(conn, uid, broker, asset, fecha):
        importado = conn.execute(
            "SELECT 1 FROM import_op_links WHERE operation_id=? LIMIT 1", (f["id"],)).fetchone()
        if importado or _norm(f["op_type"]) == _norm(op_type):
            return f
    return None


def cobros_a_mano_cerca(conn, uid: int, broker: str, asset: str, fecha: str) -> list:
    """Los cobros de ese bono cargados A MANO (sin vínculo con una importación) a
    ±14 días: los que el importador reemplaza cuando trae el mismo pago."""
    out = []
    for f in _cerca(conn, uid, broker, asset, fecha):
        if _norm(f["op_type"]) not in ("CUPON", "AMORTIZACION"):
            continue
        if conn.execute("SELECT 1 FROM import_op_links WHERE operation_id=? LIMIT 1",
                        (f["id"],)).fetchone():
            continue
        meta = f["undo_meta_json"] or ""
        if '"bond_cashflow"' not in meta:
            continue          # sin la foto del cobro no hay cómo devolverlo exacto
        out.append(f)
    return out


# Cuánto pueden diferir el monto anotado a mano (el del cronograma, o el que tipeó
# el usuario) y el del archivo del broker para seguir siendo EL MISMO cobro.
TOLERANCIA_MONTO = 0.25

SALTEAR, REEMPLAZAR, IMPORTAR = "saltear", "reemplazar", "importar"


def _usd(c) -> bool:
    return (c or "").upper() in ("USD", "USDT")


def _cobrado(f) -> float:
    """Lo que entró por esa fila: `quantity` en los cobros nuevos; en los viejos,
    `pnl_usd` era el cobro."""
    q = f["quantity"]
    return float(q if q is not None else (f["pnl_usd"] or 0))


def _en_dolares(monto, moneda, tc):
    """`monto` en dólares, o None si está en pesos y no hay con qué pasarlo."""
    if monto is None:
        return None
    if _usd(moneda):
        return float(monto)
    try:
        tc = float(tc or 0)
    except (TypeError, ValueError):
        tc = 0
    return float(monto) / tc if tc > 0 else None


def _intocable(f) -> bool:
    """Un cobro a mano que el archivo NO puede reemplazar: le bajó nominales a un
    lote (deshacerlo volvería a inflar la tenencia), o su propio renglón ya vino
    en un archivo (este otro renglón es otra cosa)."""
    import json
    try:
        meta = json.loads(f["undo_meta_json"] or "{}")
    except (TypeError, ValueError):
        return True
    return float(meta.get("qty_decremented") or 0) > 0 or bool(meta.get("respaldado_por_import"))


def que_hacer_con_el_renglon(conn, uid: int, broker: str, asset: str, fecha: str, *,
                             monto=None, moneda=None, tc=None,
                             es_amortizacion: bool = False,
                             contiene_amortizacion: bool = False) -> tuple:
    """El archivo trae un cobro de este bono (`monto` en `moneda`; `tc` = pesos por
    dólar con el que el importador pasa ese renglón). ¿Qué se hace con él, dado lo
    que el usuario ya anotó A MANO a ±14 días? Devuelve (acción, dato):

      (SALTEAR, operación)     es un cobro ya anotado: el renglón no entra.
      (REEMPLAZAR, [ops])      lo anotado a mano se borra y entra el renglón.
      (IMPORTAR, None)         es otra cosa: entra además de lo anotado.

    La regla que evita contar un pago dos veces: dentro de la ventana, un renglón
    que es "la misma parte" del pago que algo ya anotado NUNCA entra además — o
    se saltea, o lo reemplaza.

      · Renglón de AMORTIZACIÓN (el archivo lo dice): es la amortización anotada,
        con el monto que sea. Si no hay ninguna anotada, entra (es la otra parte).
      · Cualquier otro renglón de cobro (renta, dividendo, o "renta y amortización"
        junto): si se parece al cupón anotado, a la amortización, o a la suma →
        se saltea. Si no se parece:
          – lo anotado son sólo cupones que nadie más respalda → manda el dato del
            broker: se reemplazan (sea más o menos plata; un cupón no le bajó
            nominales a nadie, y revertir el import los trae de vuelta);
          – están anotados el cupón Y la amortización → no puede ser "otra parte":
            se saltea aunque el monto difiera (no se puede reemplazar una
            amortización que ya bajó nominales);
          – el renglón TRAE la amortización adentro (`contiene_amortizacion`: la
            "venta" de nominales con la que Balanz anota el pago) y ya hay una
            amortización anotada → se saltea: entrar además contaba el capital
            dos veces y bajaba los nominales dos veces (lo encontró la prueba al
            azar, 2026-10-10). Si faltaba anotar el cupón, se carga a mano;
          – si no, entra.

    Los montos se comparan en DÓLARES (lo anotado, con su TC sellado; el renglón,
    con `tc`). Antes, con monedas distintas, alcanzaba con el tipo: un cupón a
    mano de US$ 20 hacía descartar un renglón de $ 900.000 (auditoría 2026-10-10).
    Sólo si alguno no se puede pasar a dólares vuelve a alcanzar con el tipo."""
    manuales = cobros_a_mano_cerca(conn, uid, broker, asset, fecha)
    if not manuales:
        return IMPORTAR, None
    cupones = [f for f in manuales if _norm(f["op_type"]) == "CUPON"]
    amorts = [f for f in manuales if _norm(f["op_type"]) == "AMORTIZACION"]
    if es_amortizacion:
        return (SALTEAR, amorts[0]) if amorts else (IMPORTAR, None)
    grupos = [g for g in (cupones, amorts, cupones + amorts) if g]
    del_archivo = _en_dolares(monto, moneda, tc) if monto else None
    anotado = {f["id"]: _en_dolares(_cobrado(f), f["currency"], f["fx_to_usd"]) for f in manuales}
    if del_archivo is None or any(v is None for v in anotado.values()):
        return SALTEAR, grupos[0][0]
    for g in grupos:
        total = sum(anotado[f["id"]] for f in g)
        if total > 0 and abs(del_archivo - total) <= TOLERANCIA_MONTO * max(total, del_archivo):
            return SALTEAR, g[0]
    if not any(_intocable(f) for f in manuales):
        return REEMPLAZAR, manuales
    if cupones and amorts:
        return SALTEAR, cupones[0]
    if contiene_amortizacion and amorts:
        return SALTEAR, amorts[0]
    return IMPORTAR, None


def quedo_cubierto_despues(conn, uid: int, f) -> bool:
    """Al revertir un import que había reemplazado el cobro a mano `f` (una fila
    guardada): ¿ese pago quedó anotado de otra forma mientras tanto? Entonces no
    vuelve. Cuenta cualquier cobro de la ventana menos una AMORTIZACIÓN suelta
    (es la otra parte del pago, no este cupón)."""
    ventas_amort = ventas_que_son_amortizacion(conn, uid)
    for otra in _cerca(conn, uid, f.get("broker") or "", f.get("asset") or "", str(f.get("date"))[:10]):
        if _norm(otra["op_type"]) == "AMORTIZACION" and otra["id"] not in ventas_amort:
            continue
        return True
    return False


# ── La amortización sobre los lotes: UNA sola cuenta ─────────────────────────
# La usan el cobro (`main._registrar_cobro_bono`), el rearmado de lotes
# importados (`importing/rebuild.py`) y la re-aplicación después de revertir un
# import (`reaplicar_pendientes`). Hasta 2026-10-10 el rearmado tenía su copia.

def _manuales_que_bajaron_nominal(conn, uid: int, asset: str = None) -> list:
    """Las amortizaciones cargadas a mano (con su receta leída) de este usuario."""
    import json
    out = []
    q = ("SELECT id, date, broker, asset, undo_meta_json FROM operations "
         "WHERE user_id=? AND op_type IN ('Amortización','Amortizacion') "
         "AND undo_meta_json LIKE '%\"bond_cashflow\"%'")
    args = [uid]
    if asset:
        q += " AND asset=?"
        args.append(asset)
    for r in conn.execute(q + " ORDER BY date ASC, id ASC", args).fetchall():
        try:
            meta = json.loads(r["undo_meta_json"] or "{}")
        except (TypeError, ValueError):
            continue
        out.append((r, meta))
    return out


def nominal_pedido(meta: dict) -> float:
    """Los nominales que esta amortización le tiene que bajar a los lotes que no
    lleva el barrido. Se fija al anotarla (`nominal_pedido`); las anteriores a
    2026-10-10 no lo guardaban: vale lo que tenían aplicado."""
    v = meta.get("nominal_pedido")
    return float(v if v is not None else (meta.get("qty_decremented") or 0))


def reparto_de_amortizacion(conn, uid: int, brokers, asset: str, face: float, *,
                            excluir_ids: set = None, hasta: str = None) -> dict:
    """{id de lote: nominales que le toca bajar} — `face` repartido EN PROPORCIÓN a
    la cantidad de cada lote ya comprado a la fecha `hasta` (un lote comprado
    después del pago no lo cobró). Sin tocar nada."""
    nombres = [brokers] if isinstance(brokers, str) else list(brokers)
    ph = ",".join("?" * len(nombres))
    lots = [l for l in conn.execute(
        f"""SELECT id, quantity, entry_date FROM positions
           WHERE user_id=? AND broker IN ({ph}) AND asset=? AND is_cash=0 AND quantity > 0""",
        (uid, *nombres, asset)).fetchall()
        if not (excluir_ids and l["id"] in excluir_ids)
        and (not hasta or not l["entry_date"] or str(l["entry_date"])[:10] <= hasta[:10])]
    total = sum(float(l["quantity"] or 0) for l in lots)
    if total <= 1e-9 or not face or face <= 0:
        return {}
    a_bajar = min(face, total)
    return {l["id"]: a_bajar * float(l["quantity"] or 0) / total for l in lots}


def aplicar_amortizacion(conn, uid: int, tomas: dict) -> tuple:
    """Le baja a cada lote los nominales de `tomas` (y la misma proporción de su
    costo y comisiones). Devuelve (nominales bajados, costo bajado, detalle).

    El detalle dice qué se le sacó a CADA lote: con eso el borrado del cobro lo
    restaura lote por lote (`main._devolver_cobro_bono`), y `q_antes` permite saber
    con cuánto había nacido el lote (`main._nominal_al_cargar`)."""
    total_qty, total_inv, detail = 0.0, 0.0, []
    for lot_id, take in tomas.items():
        lot = conn.execute("SELECT * FROM positions WHERE id=? AND user_id=? AND is_cash=0",
                           (lot_id, uid)).fetchone()
        if not lot:
            continue
        q = float(lot["quantity"] or 0)
        take = min(float(take), q)
        if take <= 1e-9 or q <= 0:
            continue
        ratio = take / q
        inv = float(lot["invested"] or 0) * ratio
        com = float(lot["commissions"] or 0) * ratio
        queda = q - take
        if queda <= 1e-9:
            # Lote totalmente amortizado — se borra para que no quede zombie.
            conn.execute("DELETE FROM positions WHERE id=? AND user_id=?", (lot_id, uid))
        else:
            conn.execute(
                "UPDATE positions SET quantity=?, invested=?, commissions=? WHERE id=? AND user_id=?",
                (round(queda, 6), round(float(lot["invested"] or 0) - inv, 6),
                 round(float(lot["commissions"] or 0) - com, 6), lot_id, uid))
        detail.append({"id": lot_id, "take": round(take, 6), "q_antes": round(q, 6),
                       "inv": round(inv, 6), "com": round(com, 6), "survives": queda > 1e-9,
                       # El lote que se va ENTERO guarda su fila completa: al borrar
                       # el cobro vuelve con su precio manual, su nota y su receta
                       # para borrarlo (volvía con seis campos y lo demás vacío).
                       "fila": (None if queda > 1e-9 else
                                {k: lot[k] for k in lot.keys() if k not in ("id", "user_id")}),
                       # Si el lote se consume entero, borrar el cobro lo re-crea con
                       # estos datos (los cobros de antes no guardaban `fila`).
                       "broker": lot["broker"],
                       "entry_date": lot["entry_date"], "tc_compra": lot["tc_compra"],
                       "currency": lot["currency"], "buy_price": lot["buy_price"],
                       "asset_type": lot["asset_type"]})
        total_qty += take
        total_inv += inv
    return round(total_qty, 6), round(total_inv, 6), detail


def soltar_lote(conn, uid: int, lote_id) -> None:
    """Se está por borrar este lote porque se REVIERTE el import que lo creó. Las
    amortizaciones a mano que le habían bajado nominal dejan de tenerlo aplicado:
    queda pendiente (`nominal_pedido` − `qty_decremented`) y se vuelve a aplicar si
    la compra se importa de nuevo (`reaplicar_pendientes`).

    Sin esto, revertir y volver a importar la compra de un bono con una
    amortización confirmada dejaba el lote otra vez entero (10.000 en vez de
    9.773, con los 227 ya cobrados) y el cobro imposible de borrar: su receta
    nombraba un lote que ya no existía (auditoría 2026-10-10)."""
    import json
    if lote_id is None:
        return
    for r, meta in _manuales_que_bajaron_nominal(conn, uid):
        lotes = meta.get("amort_lots") or []
        suyos = [d for d in lotes if d.get("id") == lote_id and d.get("survives")]
        if not suyos:
            continue
        meta["nominal_pedido"] = nominal_pedido(meta)
        meta["amort_lots"] = [d for d in lotes if d not in suyos] or None
        meta["qty_decremented"] = round(
            float(meta.get("qty_decremented") or 0) - sum(float(d.get("take") or 0) for d in suyos), 6)
        meta["invested_decremented"] = round(
            float(meta.get("invested_decremented") or 0) - sum(float(d.get("inv") or 0) for d in suyos), 6)
        conn.execute("UPDATE operations SET undo_meta_json=? WHERE id=? AND user_id=?",
                     (json.dumps(meta), r["id"], uid))


def reaplicar_pendientes(conn, uid: int, lotes_del_barrido=None) -> int:
    """Terminó un import: a las amortizaciones a mano que quedaron con nominal
    pendiente (`soltar_lote`) se les vuelve a aplicar sobre los lotes de ese bono
    que ya estaban comprados a la fecha del pago y que esa amortización todavía no
    tocó. Devuelve cuántas se completaron (del todo o en parte)."""
    import json
    from importing.persister import broker_pair
    hechas = 0
    for r, meta in _manuales_que_bajaron_nominal(conn, uid):
        falta = nominal_pedido(meta) - float(meta.get("qty_decremented") or 0)
        if falta <= 1e-6:
            continue
        par = sorted(broker_pair(conn, uid, meta.get("lot_broker") or r["broker"]))
        ya = {d.get("id") for d in (meta.get("amort_lots") or [])}
        # Los que lleva el barrido de amortizaciones no se tocan — pero sólo en un
        # bono que el barrido conoce (`lotes_que_baja_el_barrido` devuelve los
        # lotes importados de CUALQUIER activo; la regla completa es la de
        # `main._lotes_del_barrido` y la del rearmado).
        from pricing.bond_amortization import is_amortizing_bond
        del_barrido = (set(lotes_del_barrido(conn, uid))
                       if lotes_del_barrido and is_amortizing_bond(r["asset"]) else set())
        excluir = set(ya) | del_barrido
        tomas = reparto_de_amortizacion(conn, uid, par, r["asset"], falta,
                                        excluir_ids=excluir, hasta=(r["date"] or "")[:10] or None)
        if not tomas:
            continue
        qty, inv, detalle = aplicar_amortizacion(conn, uid, tomas)
        if qty <= 1e-9:
            continue
        meta["amort_lots"] = (meta.get("amort_lots") or []) + detalle
        meta["qty_decremented"] = round(float(meta.get("qty_decremented") or 0) + qty, 6)
        meta["invested_decremented"] = round(float(meta.get("invested_decremented") or 0) + inv, 6)
        conn.execute("UPDATE operations SET undo_meta_json=? WHERE id=? AND user_id=?",
                     (json.dumps(meta), r["id"], uid))
        hechas += 1
    return hechas
