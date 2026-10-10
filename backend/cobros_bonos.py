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
    return [f for f in filas if es_cobro_de_renta(f["op_type"])]


def ya_registrado(conn, uid: int, broker: str, asset: str, fecha: str):
    """La primera fila que ya cuenta como el pago del cronograma `fecha`, o None."""
    filas = _cerca(conn, uid, broker, asset, fecha)
    return filas[0] if filas else None


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


def _usd(c) -> bool:
    return (c or "").upper() in ("USD", "USDT")


def _cobrado(f) -> float:
    """Lo que entró por esa fila: `quantity` en los cobros nuevos; en los viejos,
    `pnl_usd` era el cobro."""
    q = f["quantity"]
    return float(q if q is not None else (f["pnl_usd"] or 0))


def cubierto_por_lo_anotado(conn, uid: int, broker: str, asset: str, fecha: str, *,
                            monto=None, moneda=None, es_amortizacion: bool = False):
    """La fila del archivo (un cobro de `monto` en `moneda`) ¿es un cobro que el
    usuario YA anotó a mano? Devuelve esa operación, o None.

    Con montos comparables (misma moneda): tiene que parecerse al cupón anotado,
    a la amortización anotada, o a la suma de los dos (el archivo suele traer
    "renta y amortización" en un solo renglón). Una amortización del archivo sólo
    se compara con una amortización anotada. Sin montos comparables (el archivo
    en pesos y lo anotado en dólares), alcanza con que sea del mismo tipo."""
    manuales = cobros_a_mano_cerca(conn, uid, broker, asset, fecha)
    if not manuales:
        return None
    cupones = [f for f in manuales if _norm(f["op_type"]) == "CUPON"]
    amorts = [f for f in manuales if _norm(f["op_type"]) == "AMORTIZACION"]
    grupos = [amorts] if es_amortizacion else [cupones, amorts, cupones + amorts]
    grupos = [g for g in grupos if g]
    if not grupos:
        return None
    comparables = monto and moneda and all(
        _usd(f["currency"]) == _usd(moneda) for f in manuales)
    if not comparables:
        return grupos[0][0]
    for g in grupos:
        total = sum(_cobrado(f) for f in g)
        if total > 0 and abs(float(monto) - total) <= TOLERANCIA_MONTO * max(total, float(monto)):
            return g[0]
    return None


def absorbidos_por_el_archivo(conn, uid: int, broker: str, asset: str, fecha: str, *,
                              monto=None, moneda=None) -> list:
    """Los cobros a mano que la fila del archivo trae ADENTRO y hay que reemplazar.

    El caso: a mano sólo se anotó el cupón (20) y el archivo trae "renta y
    amortización" junto (247). No es el mismo cobro —no se saltea, perdería la
    amortización—, pero importarlo tal cual contaría el cupón dos veces. Entonces
    lo anotado a mano se borra y entra el renglón del archivo. Sólo cuando lo
    anotado NO le bajó nominales a ningún lote (un cupón): deshacer una
    amortización confirmada volvería a inflar la tenencia."""
    import json
    manuales = cobros_a_mano_cerca(conn, uid, broker, asset, fecha)
    if not manuales or not monto or not moneda:
        return []
    if not all(_usd(f["currency"]) == _usd(moneda) for f in manuales):
        return []
    total = sum(_cobrado(f) for f in manuales)
    if not (float(monto) > total * (1 + TOLERANCIA_MONTO)):
        return []
    for f in manuales:
        try:
            meta = json.loads(f["undo_meta_json"] or "{}")
        except (TypeError, ValueError):
            return []
        if float(meta.get("qty_decremented") or 0) > 0:
            return []
        # Su propio renglón ya vino en un archivo (se salteó por estar anotado):
        # este otro renglón es otra cosa (la amortización aparte), no lo contiene.
        if meta.get("respaldado_por_import"):
            return []
    return manuales
