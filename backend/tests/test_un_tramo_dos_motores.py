"""#37 — Un tramo de venta, dos motores: lo que HOY calcula cada uno, congelado.

QUÉ ES UN TRAMO. Una venta FIFO consume lotes de a uno: cada pedazo (un lote
entero o parte de uno) es un tramo, y por cada tramo se calcula cuánto costó en
dólares (`invested_usd`), cuánto se ganó (`pnl_usd`), cuánta plata entró
(`proceeds_native`) y el resultado en pesos y en dólares (`resultado_dual`).

POR QUÉ ESTE TEST. Esa cuenta vive copiada en dos lugares: el que guarda la venta
cuando se confirma un archivo (`persister._persist_sell_fifo`) y el que rearma
toda la historia (`rebuild._replay_asset`). «Mover a otro broker» la necesita una
tercera vez (el costo C del pase, sección C.5 de la especificación), y la etapa
E2b la va a mudar a una función única, `importing/tramo.py`. Mudar código sin
cambiar un solo número exige saber ANTES cuáles son los números: este archivo los
mide con el código de hoy y los deja escritos como literales.

CÓMO SE MIDIÓ. Cada escenario corre por el mismo camino que el confirm de un
import: `store_preview_txs` → `load_session_for_confirm` → `persist_batch` con los
ayudantes reales de main (primero las compras, después la venta, en dos lotes), y
después `rebuild_fifo_after_import` + `_recalc_pnl_realized_from_ops`, que es lo
que el confirm corre a continuación. No va por HTTP a propósito: el confirm por
HTTP dispara `_auto_migrar_fx_post_import`, que pasa la cuenta de v1 a v2 y borra
justo el escenario v1 que se quiere medir. El dólar está sembrado en
`fx_rates_daily` con valores distintos por fecha y por riel (blue ≠ MEP), así una
fecha o un riel cruzado cambia el número.

Los literales salen de una corrida real con el código de 6f28f2fc: las fotos, de la
base; los TRAMOS, de un rastreo (sys.settrace) que leyó las variables de cada motor
en el punto donde pnl_usd e invested_usd ya son los definitivos. NO se recalculan a
mano ni se regeneran: después de E2b ese código ya no existe, y estos números son
justamente lo que la mudanza tiene que respetar. Si uno cambia, el código cambió.

LOS ESCENARIOS (los cinco que pide la especificación, más tres):
  · ars_v1                   lote en pesos, venta en pesos, cuenta v1 (dólar de la config)
  · ars_v2                   lo mismo en una cuenta v2 (dólar de cada fecha + resultado_dual)
  · usd                      lote y venta en dólares
  · transfer_out             la SELL a precio 0 con `transfer_out` (la que usa el pase)
  · comision_en_otra_moneda  lote en dólares con comisión en dólares, vendido en pesos
                             con comisión en pesos (la comisión del lote se convierte)
  · pesos_vendido_en_dolares el otro sentido de la conversión (dólar-MEP): lote en
                             pesos vendido en dólares, costo al dólar del día de compra
  · los dos últimos, también en una cuenta v1 (*_v1): ver el comentario de ESCENARIOS

LO QUE ESTA PARTE NO VE. El `invested_usd` de una SELL `transfer_out` no queda
guardado en ningún lado (la fila dice pnl 0 y pnl_pct 0 con cualquier costo): lo
cubren los TRAMOS de abajo, que se activan con la función única.

Corre con: cd backend && python3 -m pytest tests/test_un_tramo_dos_motores.py
"""
import importlib.util
import math
import os
import sys
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import main  # noqa: E402
import fx  # noqa: E402
from importing import pipeline as pl  # noqa: E402
from importing import persister as ps  # noqa: E402
from importing import rebuild as rb  # noqa: E402
from importing.schema import NormalizedTx, OP_BUY, OP_SELL  # noqa: E402
from _limpieza import vaciar  # noqa: E402

# El dólar de la config (v1 vende a este) y el que se le pasa al rebuild. Distinto
# de todos los de la serie, así se ve cuál usó cada cuenta.
TC_BLUE = 1400.0

D_COMPRA_1 = "2024-01-10"
D_COMPRA_2 = "2024-02-15"
D_VENTA = "2024-06-10"

# fx_rates_daily: fecha → (blue_venta, mep_venta). Sin punta compradora: el dólar
# de valuación es la punta de venta (fx._sql_medio).
DOLARES = {
    D_COMPRA_1: (1100.0, 1000.0),
    D_COMPRA_2: (1150.0, 1050.0),
    D_VENTA: (1300.0, 1250.0),
}

TABLAS = ("import_op_links", "import_normalized_tx", "import_raw_rows",
          "import_batches", "operations", "positions", "monthly_entries",
          "snapshots", "config", "brokers", "users")

COLUMNAS_OPERACION = ("broker", "entry_date", "quantity", "entry_price", "exit_price",
                      "pnl_usd", "pnl_pct", "commissions", "currency", "fx_to_usd")
# Las ocho de resultado_dual que existían cuando se midió (resultado_dual.COLUMNAS).
# Escritas acá y no importadas: si mañana se suma una columna, este test tiene que
# avisar que su foto quedó corta, no ensancharse solo.
COLUMNAS_RESULTADO = ("costo_ars", "costo_usd", "cobrado_ars", "cobrado_usd",
                      "pnl_pct_ars", "pnl_pct_usd", "pnl_sin_dato", "costo_moneda")
COLUMNAS_VENTA = COLUMNAS_OPERACION + COLUMNAS_RESULTADO

COLUMNAS_LOTE = ("broker", "quantity", "invested", "commissions", "entry_date",
                 "currency", "tc_compra", "buy_price")


def _fila(i, fecha, broker, op, activo, tipo, qty, precio, monto, comision, moneda, **extra):
    return NormalizedTx(row_index=i, date=fecha, broker=broker, operation_type=op,
                        asset_symbol=activo, asset_type=tipo, quantity=qty,
                        unit_price=precio, gross_amount=monto, fees=comision,
                        currency=moneda, **extra)


# Cada escenario arma filas NUEVAS en cada corrida (el persister las muta).
ESCENARIOS = {
    "ars_v1": dict(
        version="v1", brokers=(("IOL", "ARS", None),), activo="GGAL",
        compras=lambda: [
            _fila(0, D_COMPRA_1, "IOL", OP_BUY, "GGAL", "STOCK", 10.0, 1000.0, 10000.0, 50.0, "ARS"),
            _fila(1, D_COMPRA_2, "IOL", OP_BUY, "GGAL", "STOCK", 5.0, 1200.0, 6000.0, 30.0, "ARS",
                  tc_compra=1080.0),
        ],
        venta=lambda: [
            _fila(0, D_VENTA, "IOL", OP_SELL, "GGAL", "STOCK", 12.0, 1500.0, 18000.0, 90.0, "ARS"),
        ]),
    "ars_v2": dict(
        version="v2", brokers=(("IOL", "ARS", None),), activo="GGAL",
        compras=lambda: [
            _fila(0, D_COMPRA_1, "IOL", OP_BUY, "GGAL", "STOCK", 10.0, 1000.0, 10000.0, 50.0, "ARS"),
            _fila(1, D_COMPRA_2, "IOL", OP_BUY, "GGAL", "STOCK", 5.0, 1200.0, 6000.0, 30.0, "ARS",
                  tc_compra=1080.0),
        ],
        venta=lambda: [
            _fila(0, D_VENTA, "IOL", OP_SELL, "GGAL", "STOCK", 12.0, 1500.0, 18000.0, 90.0, "ARS"),
        ]),
    "usd": dict(
        version="v2", brokers=(("IBKR", "USD", None),), activo="AAPL",
        compras=lambda: [
            _fila(0, D_COMPRA_1, "IBKR", OP_BUY, "AAPL", "STOCK", 10.0, 150.0, 1500.0, 1.5, "USD"),
            _fila(1, D_COMPRA_2, "IBKR", OP_BUY, "AAPL", "STOCK", 5.0, 160.0, 800.0, 0.5, "USD"),
        ],
        venta=lambda: [
            _fila(0, D_VENTA, "IBKR", OP_SELL, "AAPL", "STOCK", 12.0, 200.0, 2400.0, 1.2, "USD"),
        ]),
    "transfer_out": dict(
        version="v2", brokers=(("Cocos", "ARS", None),), activo="NVDA",
        compras=lambda: [
            _fila(0, D_COMPRA_1, "Cocos", OP_BUY, "NVDA", "CEDEAR", 10.0, 30000.0, 300000.0, 1500.0, "ARS"),
        ],
        venta=lambda: [
            _fila(0, D_VENTA, "Cocos", OP_SELL, "NVDA", "CEDEAR", 4.0, 0.0, 0.0, 0.0, "ARS",
                  transfer_out=True),
        ]),
    "comision_en_otra_moneda": dict(
        version="v2", brokers=(("Cocos", "ARS", None), ("Cocos · USD", "USD", "Cocos")),
        activo="SPY",
        compras=lambda: [
            _fila(0, D_COMPRA_1, "Cocos · USD", OP_BUY, "SPY", "CEDEAR", 20.0, 25.0, 500.0, 2.5, "USD"),
        ],
        venta=lambda: [
            _fila(0, D_VENTA, "Cocos", OP_SELL, "SPY", "CEDEAR", 8.0, 40000.0, 320000.0, 1600.0, "ARS"),
        ]),
    "pesos_vendido_en_dolares": dict(
        version="v2", brokers=(("Cocos", "ARS", None), ("Cocos · USD", "USD", "Cocos")),
        activo="KO",
        compras=lambda: [
            _fila(0, D_COMPRA_1, "Cocos", OP_BUY, "KO", "CEDEAR", 10.0, 20000.0, 200000.0, 1000.0, "ARS"),
        ],
        venta=lambda: [
            _fila(0, D_VENTA, "Cocos · USD", OP_SELL, "KO", "CEDEAR", 4.0, 25.0, 100.0, 0.5, "USD"),
        ]),
}
# Las dos ventas que cruzan de moneda, también en una cuenta v1. En v2 el resultado
# en dólares lo pone resultado_dual con el costo SIN convertir, así que la
# conversión del costo a la moneda de la venta no se ve en ningún número: medido,
# un sabotaje que la llevaba al dólar equivocado quedaba en verde con sólo los
# escenarios v2. En v1 esa conversión ES el resultado.
ESCENARIOS["comision_en_otra_moneda_v1"] = dict(ESCENARIOS["comision_en_otra_moneda"], version="v1")
ESCENARIOS["pesos_vendido_en_dolares_v1"] = dict(ESCENARIOS["pesos_vendido_en_dolares"], version="v1")


# ─── Correr un escenario por el camino del confirm ───────────────────────────

def sembrar_dolares(conn):
    conn.execute("DELETE FROM fx_rates_daily")
    for fecha, (blue, mep) in DOLARES.items():
        conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
                     "VALUES (?,?,?, 'test')", (fecha, blue, mep))


def _confirmar(conn, uid, broker, txs):
    """Lo que hace el confirm con un lote: guardarlo, releerlo de la base y aplicarlo."""
    with conn:
        sid = pl.store_preview_txs(conn, uid, broker=broker, parser_format="rendi_generic",
                                   file_name="tramo.csv", txs=txs)
    with conn:
        txs_db, raw = pl.load_session_for_confirm(conn, uid=uid, session_id=sid)
        r = ps.persist_batch(conn, uid=uid, batch_id=sid, txs=txs_db,
                             raw_row_ids_by_index=raw, helpers=main._import_helpers)
    if r.get("skipped_rows"):
        raise AssertionError(f"el persister salteó filas: {r['skipped_rows']}")
    return sid


def _cajas(conn, uid):
    return {r["broker"]: float(r["c"] or 0) for r in conn.execute(
        "SELECT broker, COALESCE(SUM(invested),0) c FROM positions "
        "WHERE user_id=? AND is_cash=1 GROUP BY broker", (uid,)).fetchall()}


def _foto(conn, uid, activo, cajas_antes):
    ventas = [{c: r[c] for c in COLUMNAS_VENTA} for r in conn.execute(
        f"SELECT {', '.join(COLUMNAS_VENTA)} FROM operations "
        "WHERE user_id=? AND asset=? AND op_type='Venta' "
        "ORDER BY date, entry_date, quantity, id", (uid, activo)).fetchall()]
    lotes = [{c: r[c] for c in COLUMNAS_LOTE} for r in conn.execute(
        f"SELECT {', '.join(COLUMNAS_LOTE)} FROM positions "
        "WHERE user_id=? AND asset=? AND is_cash=0 "
        "ORDER BY entry_date, broker, quantity", (uid, activo)).fetchall()]
    cajas = _cajas(conn, uid)
    caja = {b: round(cajas.get(b, 0.0) - cajas_antes.get(b, 0.0), 6)
            for b in sorted(set(cajas) | set(cajas_antes))}
    mes = {r["broker"]: r["pnl_realized"] for r in conn.execute(
        "SELECT broker, pnl_realized FROM monthly_entries "
        "WHERE user_id=? AND year=? AND month=? ORDER BY broker",
        (uid, int(D_VENTA[:4]), int(D_VENTA[5:7]))).fetchall()}
    return {"ventas": ventas, "lotes": lotes, "caja": caja, "mes": mes}


def correr(conn, uid, nombre):
    """Corre el escenario: compras, venta (persister), rebuild real. Devuelve
    (foto después del persister, foto después del rebuild, resultado del rebuild)."""
    esc = ESCENARIOS[nombre]
    ids = {}
    for b, moneda, padre in esc["brokers"]:
        cur = conn.execute(
            "INSERT INTO brokers (user_id, name, currency, parent_broker_id) VALUES (?,?,?,?)",
            (uid, b, moneda, ids.get(padre)))
        ids[b] = cur.lastrowid
    fx.set_fx_version(conn, uid, esc["version"])
    conn.execute("INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
                 "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
                 (uid, "tc_blue", str(TC_BLUE)))
    conn.commit()
    raiz = esc["brokers"][0][0]

    _confirmar(conn, uid, raiz, esc["compras"]())
    cajas_antes = _cajas(conn, uid)
    sid = _confirmar(conn, uid, raiz, esc["venta"]())
    ids_persister = {r["id"] for r in conn.execute(
        "SELECT id FROM operations WHERE user_id=? AND op_type='Venta'", (uid,)).fetchall()}
    persister = _foto(conn, uid, esc["activo"], cajas_antes)

    with conn:
        res = rb.rebuild_fifo_after_import(conn, uid, sid, tc_blue=TC_BLUE)
        main._recalc_pnl_realized_from_ops(conn, uid)
    ids_rebuild = {r["id"] for r in conn.execute(
        "SELECT id FROM operations WHERE user_id=? AND op_type='Venta'", (uid,)).fetchall()}
    rebuild = _foto(conn, uid, esc["activo"], cajas_antes)
    res = dict(res, ventas_reescritas=not (ids_persister & ids_rebuild) and bool(ids_rebuild))
    return persister, rebuild, res


def _parecidos(a, b, ruta=""):
    """Igualdad recursiva; los números con 1e-9 de holgura relativa (la mudanza de
    E2b es código movido: si cambia más que el último bit, cambió la cuenta)."""
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return f"{ruta}: claves {sorted(a)} ≠ {sorted(b)}"
        for k in a:
            d = _parecidos(a[k], b[k], f"{ruta}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{ruta}: {len(a)} elementos ≠ {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _parecidos(x, y, f"{ruta}[{i}]")
            if d:
                return d
        return None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
            and not isinstance(a, bool) and not isinstance(b, bool):
        if math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9):
            return None
        return f"{ruta}: {a!r} ≠ {b!r}"
    return None if a == b else f"{ruta}: {a!r} ≠ {b!r}"


# ─── Lo que midió la corrida real (6f28f2fc) ─────────────────────────────────

def _res(t):
    """Las columnas de resultado_dual, en el orden de COLUMNAS_RESULTADO. None = el
    motor no calculó resultado (cuenta v1)."""
    if t is None:
        return None
    assert len(t) == len(COLUMNAS_RESULTADO), t
    return dict(zip(COLUMNAS_RESULTADO, t))


def _venta(*valores):
    """Una fila de `operations` por tramo: COLUMNAS_OPERACION en orden y, si la
    venta guardó resultado_dual, un último argumento con sus ocho columnas (si no
    va, quedan vacías)."""
    n = len(COLUMNAS_OPERACION)
    assert len(valores) in (n, n + 1), valores
    fila = dict(zip(COLUMNAS_OPERACION, valores[:n]))
    fila.update(_res(valores[n] if len(valores) > n else None)
                or dict.fromkeys(COLUMNAS_RESULTADO))
    return fila


def _lote(*valores):
    assert len(valores) == len(COLUMNAS_LOTE)
    return dict(zip(COLUMNAS_LOTE, valores))


def _tramo(escenario, motor, i, *, lote, salida, **entrada):
    # El rebuild llama `qty` a la cantidad del lote y positions la llama `quantity`:
    # van las dos, la función única elige (y E2b puede sacar la que sobre).
    lote = dict(lote, qty=lote["quantity"])
    salida = dict(salida, resultado=_res(salida["resultado"]))
    return {"escenario": escenario, "motor": motor, "i": i,
            "entrada": dict(entrada, lote=lote), "salida": salida}


# Por escenario, la foto después del persister y después del rebuild:
#   ventas  una fila de `operations` por tramo: _venta(broker, entry_date, quantity,
#           entry_price, exit_price, pnl_usd, pnl_pct, commissions, currency,
#           fx_to_usd, [(costo_ars, costo_usd, cobrado_ars, cobrado_usd,
#           pnl_pct_ars, pnl_pct_usd, pnl_sin_dato, costo_moneda)])
#   lotes   lo que queda abierto: _lote(broker, quantity, invested, commissions,
#           entry_date, currency, tc_compra, buy_price)
#   caja    cuánto cambió la caja de cada broker con la venta (lo cobrado)
#   mes     `monthly_entries.pnl_realized` del mes de la venta. El persister suma
#           los pnl_usd sin redondear; el recálculo, los guardados (a 2 decimales).
#
# ⚠️ DIFERENCIA ENTRE MOTORES QUE YA EXISTÍA (no es de este test): en una venta que
# cruza el par padre↔«· USD» (comision_en_otra_moneda y pesos_vendido_en_dolares),
# el persister anota la fila de `operations` en el broker del LOTE y el rebuild en el
# de la VENTA. El renglón del mes, el persister lo anota en el de la venta. Queda
# congelado tal cual: E2b mueve la cuenta del tramo, no esto.
ESPERADO = {
    'ars_v1': {
        'persister': dict(
            ventas=[
                _venta('IOL', '2024-01-10', 10.0, 1000.0, 1500.0, 3.48, 48.5075, 75.0, 'ARS', 1400.0),
                _venta('IOL', '2024-02-15', 2.0, 1200.0, 1500.0, 0.41, 23.7562, 15.0, 'ARS', 1400.0),
            ],
            lotes=[_lote('IOL', 3.0, 3600.0, 18.0, '2024-02-15', 'ARS', 1080.0, 1200.0)],
            caja={'IOL': 17910.0},
            mes={'IOL': 3.8914, 'global': 3.8914},
        ),
        'rebuild': dict(
            ventas=[
                _venta('IOL', '2024-01-10', 10.0, 1000.0, 1500.0, 3.48, 48.5075, 75.0, 'ARS', 1400.0),
                _venta('IOL', '2024-02-15', 2.0, 1200.0, 1500.0, 0.41, 23.7562, 15.0, 'ARS', 1400.0),
            ],
            lotes=[_lote('IOL', 3.0, 3600.0, 18.0, '2024-02-15', 'ARS', 1080.0, 1200.0)],
            caja={'IOL': 17910.0},
            mes={'IOL': 3.89, 'global': 3.89},
        ),
    },
    'ars_v2': {
        'persister': dict(
            ventas=[
                _venta('IOL', '2024-01-10', 10.0, 1000.0, 1500.0, 1.89, 18.806, 75.0, 'ARS', 1250.0,
                       (10050.0, 10.05, 14925.0, 11.94, 48.5075, 18.806, None, 'ARS')),
                _venta('IOL', '2024-02-15', 2.0, 1200.0, 1500.0, 0.15, 6.9254, 15.0, 'ARS', 1250.0,
                       (2412.0, 2.233333, 2985.0, 2.388, 23.7562, 6.9254, None, 'ARS')),
            ],
            lotes=[_lote('IOL', 3.0, 3600.0, 18.0, '2024-02-15', 'ARS', 1080.0, 1200.0)],
            caja={'IOL': 17910.0},
            mes={'IOL': 2.0447, 'global': 2.0447},
        ),
        'rebuild': dict(
            ventas=[
                _venta('IOL', '2024-01-10', 10.0, 1000.0, 1500.0, 1.89, 18.806, 75.0, 'ARS', 1250.0,
                       (10050.0, 10.05, 14925.0, 11.94, 48.5075, 18.806, None, 'ARS')),
                _venta('IOL', '2024-02-15', 2.0, 1200.0, 1500.0, 0.15, 6.9254, 15.0, 'ARS', 1250.0,
                       (2412.0, 2.233333, 2985.0, 2.388, 23.7562, 6.9254, None, 'ARS')),
            ],
            lotes=[_lote('IOL', 3.0, 3600.0, 18.0, '2024-02-15', 'ARS', 1080.0, 1200.0)],
            caja={'IOL': 17910.0},
            mes={'IOL': 2.04, 'global': 2.04},
        ),
    },
    'usd': {
        'persister': dict(
            ventas=[
                _venta('IBKR', '2024-01-10', 10.0, 150.0, 200.0, 497.5, 33.1335, 1.0, 'USD', None,
                       (1501500.0, 1501.5, 2498750.0, 1999.0, 66.4169, 33.1335, None, 'USD')),
                _venta('IBKR', '2024-02-15', 2.0, 160.0, 200.0, 79.6, 24.8595, 0.2, 'USD', None,
                       (336210.0, 320.2, 499750.0, 399.8, 48.6422, 24.8595, None, 'USD')),
            ],
            lotes=[_lote('IBKR', 3.0, 480.0, 0.3, '2024-02-15', 'USD', None, 160.0)],
            caja={'IBKR': 2398.8},
            mes={'IBKR': 577.1, 'global': 577.1},
        ),
        'rebuild': dict(
            ventas=[
                _venta('IBKR', '2024-01-10', 10.0, 150.0, 200.0, 497.5, 33.1335, 1.0, 'USD', None,
                       (1501500.0, 1501.5, 2498750.0, 1999.0, 66.4169, 33.1335, None, 'USD')),
                _venta('IBKR', '2024-02-15', 2.0, 160.0, 200.0, 79.6, 24.8595, 0.2, 'USD', None,
                       (336210.0, 320.2, 499750.0, 399.8, 48.6422, 24.8595, None, 'USD')),
            ],
            lotes=[_lote('IBKR', 3.0, 480.0, 0.3, '2024-02-15', 'USD', None, 160.0)],
            caja={'IBKR': 2398.8},
            mes={'IBKR': 577.1, 'global': 577.1},
        ),
    },
    'transfer_out': {
        'persister': dict(
            ventas=[
                _venta('Cocos', '2024-01-10', 4.0, 30000.0, 0.0, 0.0, 0.0, 0.0, 'ARS', 1250.0,
                       (None, None, None, None, None, None, 'retiro', None)),
            ],
            lotes=[_lote('Cocos', 6.0, 180000.0, 900.0, '2024-01-10', 'ARS', 1000.0, 30000.0)],
            caja={'Cocos': 0.0},
            mes={},
        ),
        'rebuild': dict(
            ventas=[
                _venta('Cocos', '2024-01-10', 4.0, 30000.0, 0.0, 0.0, 0.0, 0.0, 'ARS', 1250.0,
                       (None, None, None, None, None, None, 'retiro', None)),
            ],
            lotes=[_lote('Cocos', 6.0, 180000.0, 900.0, '2024-01-10', 'ARS', 1000.0, 30000.0)],
            caja={'Cocos': 0.0},
            mes={},
        ),
    },
    'comision_en_otra_moneda': {
        'persister': dict(
            ventas=[
                _venta('Cocos · USD', '2024-01-10', 8.0, 25.0, 40000.0, 53.72, 26.7264, 1600.0, 'ARS', 1250.0,
                       (201000.0, 201.0, 318400.0, 254.72, 58.408, 26.7264, None, 'USD')),
            ],
            lotes=[_lote('Cocos · USD', 12.0, 300.0, 1.5, '2024-01-10', 'USD', None, 25.0)],
            caja={'Cocos': 318400.0, 'Cocos · USD': 0.0},
            mes={'Cocos': 53.72, 'global': 53.72},
        ),
        'rebuild': dict(
            ventas=[
                _venta('Cocos', '2024-01-10', 8.0, 25.0, 40000.0, 53.72, 26.7264, 1600.0, 'ARS', 1250.0,
                       (201000.0, 201.0, 318400.0, 254.72, 58.408, 26.7264, None, 'USD')),
            ],
            lotes=[_lote('Cocos · USD', 12.0, 300.0, 1.5, '2024-01-10', 'USD', None, 25.0)],
            caja={'Cocos': 318400.0, 'Cocos · USD': 0.0},
            mes={'Cocos': 53.72, 'global': 53.72},
        ),
    },
    'pesos_vendido_en_dolares': {
        'persister': dict(
            ventas=[
                _venta('Cocos', '2024-01-10', 4.0, 20000.0, 25.0, 19.1, 23.7562, 0.5, 'USD', None,
                       (80400.0, 80.4, 124375.0, 99.5, 54.6953, 23.7562, None, 'ARS')),
            ],
            lotes=[_lote('Cocos', 6.0, 120000.0, 600.0, '2024-01-10', 'ARS', 1000.0, 20000.0)],
            caja={'Cocos': 0.0, 'Cocos · USD': 99.5},
            mes={'Cocos · USD': 19.1, 'global': 19.1},
        ),
        'rebuild': dict(
            ventas=[
                _venta('Cocos · USD', '2024-01-10', 4.0, 20000.0, 25.0, 19.1, 23.7562, 0.5, 'USD', None,
                       (80400.0, 80.4, 124375.0, 99.5, 54.6953, 23.7562, None, 'ARS')),
            ],
            lotes=[_lote('Cocos', 6.0, 120000.0, 600.0, '2024-01-10', 'ARS', 1000.0, 20000.0)],
            caja={'Cocos': 0.0, 'Cocos · USD': 99.5},
            mes={'Cocos · USD': 19.1, 'global': 19.1},
        ),
    },
    'comision_en_otra_moneda_v1': {
        'persister': dict(
            ventas=[
                _venta('Cocos · USD', '2024-01-10', 8.0, 25.0, 40000.0, 26.43, 13.1485, 1600.0, 'ARS', 1400.0),
            ],
            lotes=[_lote('Cocos · USD', 12.0, 300.0, 1.5, '2024-01-10', 'USD', None, 25.0)],
            caja={'Cocos': 318400.0, 'Cocos · USD': 0.0},
            mes={'Cocos': 26.4286, 'global': 26.4286},
        ),
        'rebuild': dict(
            ventas=[
                _venta('Cocos', '2024-01-10', 8.0, 25.0, 40000.0, 26.43, 13.1485, 1600.0, 'ARS', 1400.0),
            ],
            lotes=[_lote('Cocos · USD', 12.0, 300.0, 1.5, '2024-01-10', 'USD', None, 25.0)],
            caja={'Cocos': 318400.0, 'Cocos · USD': 0.0},
            mes={'Cocos': 26.43, 'global': 26.43},
        ),
    },
    'pesos_vendido_en_dolares_v1': {
        'persister': dict(
            ventas=[
                _venta('Cocos', '2024-01-10', 4.0, 20000.0, 25.0, 26.41, 36.1318, 0.5, 'USD', None),
            ],
            lotes=[_lote('Cocos', 6.0, 120000.0, 600.0, '2024-01-10', 'ARS', 1000.0, 20000.0)],
            caja={'Cocos': 0.0, 'Cocos · USD': 99.5},
            mes={'Cocos · USD': 26.4091, 'global': 26.4091},
        ),
        'rebuild': dict(
            ventas=[
                _venta('Cocos · USD', '2024-01-10', 4.0, 20000.0, 25.0, 26.41, 36.1318, 0.5, 'USD', None),
            ],
            lotes=[_lote('Cocos', 6.0, 120000.0, 600.0, '2024-01-10', 'ARS', 1000.0, 20000.0)],
            caja={'Cocos': 0.0, 'Cocos · USD': 99.5},
            mes={'Cocos · USD': 26.41, 'global': 26.41},
        ),
    },
}

# Por tramo, las entradas y las salidas EXACTAS (sin redondear) de la cuenta, leídas
# de las variables de cada motor en la corrida real. Son el contrato de
# `importing.tramo.costo_y_resultado_del_tramo` (C.5): la etapa E2b la crea y el
# test `LaFuncionUnicaDaLoMismo` se activa solo. El lote del rebuild trae el
# `tc_compra` de la fila importada (vacío) y el del persister el que quedó en
# positions (el dólar de la fecha): el resultado es el mismo porque resultado_dual,
# sin dólar del lote, usa el de esa misma fecha.
TRAMOS = [
    _tramo('ars_v1', 'persister', 0,
           lote=dict(invested=10000.0, buy_price=1000.0, quantity=10.0, commissions=50.0, currency='ARS',
                     entry_date='2024-01-10', tc_compra=1000.0),
           take=10.0, currency='ARS', sell_currency='ARS', exit_price=1500.0, chunk_commission=75.0,
           tc_venta=1400.0, tc_blue=1400.0, hist=False, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=3.482142857142857, invested_usd=7.178571428571429, proceeds_native=14925.0,
                       costo_en_su_moneda=10050.0, resultado=None)),
    _tramo('ars_v1', 'persister', 1,
           lote=dict(invested=6000.0, buy_price=1200.0, quantity=5.0, commissions=30.0, currency='ARS',
                     entry_date='2024-02-15', tc_compra=1080.0),
           take=2.0, currency='ARS', sell_currency='ARS', exit_price=1500.0, chunk_commission=15.0,
           tc_venta=1400.0, tc_blue=1400.0, hist=False, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=0.4092857142857143, invested_usd=1.7228571428571429, proceeds_native=2985.0,
                       costo_en_su_moneda=2412.0, resultado=None)),
    _tramo('ars_v1', 'rebuild', 0,
           lote=dict(invested=10000.0, buy_price=1000.0, quantity=10.0, commissions=50.0, currency='ARS',
                     entry_date='2024-01-10', tc_compra=None),
           take=10.0, currency='ARS', sell_currency='ARS', exit_price=1500.0, chunk_commission=75.0,
           tc_venta=1400.0, tc_blue=1400.0, hist=False, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=3.482142857142857, invested_usd=7.178571428571429,
                       costo_en_su_moneda=10050.0, resultado=None)),
    _tramo('ars_v1', 'rebuild', 1,
           lote=dict(invested=6000.0, buy_price=1200.0, quantity=5.0, commissions=30.0, currency='ARS',
                     entry_date='2024-02-15', tc_compra=1080.0),
           take=2.0, currency='ARS', sell_currency='ARS', exit_price=1500.0, chunk_commission=15.0,
           tc_venta=1400.0, tc_blue=1400.0, hist=False, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=0.4092857142857143, invested_usd=1.7228571428571429,
                       costo_en_su_moneda=2412.0, resultado=None)),
    _tramo('ars_v2', 'persister', 0,
           lote=dict(invested=10000.0, buy_price=1000.0, quantity=10.0, commissions=50.0, currency='ARS',
                     entry_date='2024-01-10', tc_compra=1000.0),
           take=10.0, currency='ARS', sell_currency='ARS', exit_price=1500.0, chunk_commission=75.0,
           tc_venta=1250.0, tc_blue=1400.0, hist=True, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=1.8899999999999988, invested_usd=10.05, proceeds_native=14925.0,
                       costo_en_su_moneda=10050.0, resultado=(10050.0, 10.05, 14925.0, 11.94, 48.5075, 18.806, None,
                       'ARS'))),
    _tramo('ars_v2', 'persister', 1,
           lote=dict(invested=6000.0, buy_price=1200.0, quantity=5.0, commissions=30.0, currency='ARS',
                     entry_date='2024-02-15', tc_compra=1080.0),
           take=2.0, currency='ARS', sell_currency='ARS', exit_price=1500.0, chunk_commission=15.0,
           tc_venta=1250.0, tc_blue=1400.0, hist=True, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=0.1546669999999999, invested_usd=2.233333, proceeds_native=2985.0,
                       costo_en_su_moneda=2412.0, resultado=(2412.0, 2.233333, 2985.0, 2.388, 23.7562, 6.9254, None,
                       'ARS'))),
    _tramo('ars_v2', 'rebuild', 0,
           lote=dict(invested=10000.0, buy_price=1000.0, quantity=10.0, commissions=50.0, currency='ARS',
                     entry_date='2024-01-10', tc_compra=None),
           take=10.0, currency='ARS', sell_currency='ARS', exit_price=1500.0, chunk_commission=75.0,
           tc_venta=1250.0, tc_blue=1400.0, hist=True, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=1.8899999999999988, invested_usd=10.05, costo_en_su_moneda=10050.0,
                       resultado=(10050.0, 10.05, 14925.0, 11.94, 48.5075, 18.806, None, 'ARS'))),
    _tramo('ars_v2', 'rebuild', 1,
           lote=dict(invested=6000.0, buy_price=1200.0, quantity=5.0, commissions=30.0, currency='ARS',
                     entry_date='2024-02-15', tc_compra=1080.0),
           take=2.0, currency='ARS', sell_currency='ARS', exit_price=1500.0, chunk_commission=15.0,
           tc_venta=1250.0, tc_blue=1400.0, hist=True, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=0.1546669999999999, invested_usd=2.233333, costo_en_su_moneda=2412.0,
                       resultado=(2412.0, 2.233333, 2985.0, 2.388, 23.7562, 6.9254, None, 'ARS'))),
    _tramo('usd', 'persister', 0,
           lote=dict(invested=1500.0, buy_price=150.0, quantity=10.0, commissions=1.5, currency='USD',
                     entry_date='2024-01-10', tc_compra=None),
           take=10.0, currency='USD', sell_currency='USD', exit_price=200.0, chunk_commission=1.0,
           tc_venta=1.0, tc_blue=1400.0, hist=True, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=497.5, invested_usd=1501.5, proceeds_native=1999.0,
                       costo_en_su_moneda=1501.5, resultado=(1501500.0, 1501.5, 2498750.0, 1999.0, 66.4169, 33.1335,
                       None, 'USD'))),
    _tramo('usd', 'persister', 1,
           lote=dict(invested=800.0, buy_price=160.0, quantity=5.0, commissions=0.5, currency='USD',
                     entry_date='2024-02-15', tc_compra=None),
           take=2.0, currency='USD', sell_currency='USD', exit_price=200.0,
           chunk_commission=0.19999999999999998, tc_venta=1.0, tc_blue=1400.0, hist=True,
           op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=79.60000000000002, invested_usd=320.2, proceeds_native=399.8,
                       costo_en_su_moneda=320.20000000000005, resultado=(336210.0, 320.2, 499750.0, 399.8, 48.6422,
                       24.8595, None, 'USD'))),
    _tramo('usd', 'rebuild', 0,
           lote=dict(invested=1500.0, buy_price=150.0, quantity=10.0, commissions=1.5, currency='USD',
                     entry_date='2024-01-10', tc_compra=None),
           take=10.0, currency='USD', sell_currency='USD', exit_price=200.0, chunk_commission=1.0,
           tc_venta=1.0, tc_blue=1400.0, hist=True, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=497.5, invested_usd=1501.5, costo_en_su_moneda=1501.5, resultado=(1501500.0,
                       1501.5, 2498750.0, 1999.0, 66.4169, 33.1335, None, 'USD'))),
    _tramo('usd', 'rebuild', 1,
           lote=dict(invested=800.0, buy_price=160.0, quantity=5.0, commissions=0.5, currency='USD',
                     entry_date='2024-02-15', tc_compra=None),
           take=2.0, currency='USD', sell_currency='USD', exit_price=200.0,
           chunk_commission=0.19999999999999998, tc_venta=1.0, tc_blue=1400.0, hist=True,
           op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=79.60000000000002, invested_usd=320.2,
                       costo_en_su_moneda=320.20000000000005, resultado=(336210.0, 320.2, 499750.0, 399.8, 48.6422,
                       24.8595, None, 'USD'))),
    _tramo('transfer_out', 'persister', 0,
           lote=dict(invested=300000.0, buy_price=30000.0, quantity=10.0, commissions=1500.0,
                     currency='ARS', entry_date='2024-01-10', tc_compra=1000.0),
           take=4.0, currency='ARS', sell_currency='ARS', exit_price=0.0, chunk_commission=0.0,
           tc_venta=1250.0, tc_blue=1400.0, hist=True, op_date='2024-06-10', transfer_out=True,
           salida=dict(pnl_usd=0.0, invested_usd=96.48, proceeds_native=0.0, costo_en_su_moneda=120600.0,
                       resultado=(None, None, None, None, None, None, 'retiro', None))),
    _tramo('transfer_out', 'rebuild', 0,
           lote=dict(invested=300000.0, buy_price=30000.0, quantity=10.0, commissions=1500.0,
                     currency='ARS', entry_date='2024-01-10', tc_compra=None),
           take=4.0, currency='ARS', sell_currency='ARS', exit_price=0.0, chunk_commission=0.0,
           tc_venta=1250.0, tc_blue=1400.0, hist=True, op_date='2024-06-10', transfer_out=True,
           salida=dict(pnl_usd=0.0, invested_usd=96.48, costo_en_su_moneda=120600.0, resultado=(None, None,
                       None, None, None, None, 'retiro', None))),
    _tramo('comision_en_otra_moneda', 'persister', 0,
           lote=dict(invested=500.0, buy_price=25.0, quantity=20.0, commissions=2.5, currency='USD',
                     entry_date='2024-01-10', tc_compra=None),
           take=8.0, currency='ARS', sell_currency='ARS', exit_price=40000.0, chunk_commission=1600.0,
           tc_venta=1250.0, tc_blue=1400.0, hist=True, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=53.72, invested_usd=201.0, proceeds_native=318400.0,
                       costo_en_su_moneda=201.0, resultado=(201000.0, 201.0, 318400.0, 254.72, 58.408, 26.7264, None,
                       'USD'))),
    _tramo('comision_en_otra_moneda', 'rebuild', 0,
           lote=dict(invested=500.0, buy_price=25.0, quantity=20.0, commissions=2.5, currency='USD',
                     entry_date='2024-01-10', tc_compra=None),
           take=8.0, currency='ARS', sell_currency='ARS', exit_price=40000.0, chunk_commission=1600.0,
           tc_venta=1250.0, tc_blue=1400.0, hist=True, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=53.72, invested_usd=201.0, costo_en_su_moneda=201.0, resultado=(201000.0,
                       201.0, 318400.0, 254.72, 58.408, 26.7264, None, 'USD'))),
    _tramo('pesos_vendido_en_dolares', 'persister', 0,
           lote=dict(invested=200000.0, buy_price=20000.0, quantity=10.0, commissions=1000.0,
                     currency='ARS', entry_date='2024-01-10', tc_compra=1000.0),
           take=4.0, currency='USD', sell_currency='USD', exit_price=25.0, chunk_commission=0.5,
           tc_venta=1.0, tc_blue=1400.0, hist=True, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=19.099999999999994, invested_usd=80.4, proceeds_native=99.5,
                       costo_en_su_moneda=80400.0, resultado=(80400.0, 80.4, 124375.0, 99.5, 54.6953, 23.7562, None,
                       'ARS'))),
    _tramo('pesos_vendido_en_dolares', 'rebuild', 0,
           lote=dict(invested=200000.0, buy_price=20000.0, quantity=10.0, commissions=1000.0,
                     currency='ARS', entry_date='2024-01-10', tc_compra=None),
           take=4.0, currency='USD', sell_currency='USD', exit_price=25.0, chunk_commission=0.5,
           tc_venta=1.0, tc_blue=1400.0, hist=True, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=19.099999999999994, invested_usd=80.4, costo_en_su_moneda=80400.0,
                       resultado=(80400.0, 80.4, 124375.0, 99.5, 54.6953, 23.7562, None, 'ARS'))),
    _tramo('comision_en_otra_moneda_v1', 'persister', 0,
           lote=dict(invested=500.0, buy_price=25.0, quantity=20.0, commissions=2.5, currency='USD',
                     entry_date='2024-01-10', tc_compra=None),
           take=8.0, currency='ARS', sell_currency='ARS', exit_price=40000.0, chunk_commission=1600.0,
           tc_venta=1400.0, tc_blue=1400.0, hist=False, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=26.428571428571427, invested_usd=201.0, proceeds_native=318400.0,
                       costo_en_su_moneda=201.0, resultado=None)),
    _tramo('comision_en_otra_moneda_v1', 'rebuild', 0,
           lote=dict(invested=500.0, buy_price=25.0, quantity=20.0, commissions=2.5, currency='USD',
                     entry_date='2024-01-10', tc_compra=None),
           take=8.0, currency='ARS', sell_currency='ARS', exit_price=40000.0, chunk_commission=1600.0,
           tc_venta=1400.0, tc_blue=1400.0, hist=False, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=26.428571428571427, invested_usd=201.0, costo_en_su_moneda=201.0,
                       resultado=None)),
    _tramo('pesos_vendido_en_dolares_v1', 'persister', 0,
           lote=dict(invested=200000.0, buy_price=20000.0, quantity=10.0, commissions=1000.0,
                     currency='ARS', entry_date='2024-01-10', tc_compra=1000.0),
           take=4.0, currency='USD', sell_currency='USD', exit_price=25.0, chunk_commission=0.5,
           tc_venta=1.0, tc_blue=1400.0, hist=False, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=26.409090909090907, invested_usd=73.0909090909091, proceeds_native=99.5,
                       costo_en_su_moneda=80400.0, resultado=None)),
    _tramo('pesos_vendido_en_dolares_v1', 'rebuild', 0,
           lote=dict(invested=200000.0, buy_price=20000.0, quantity=10.0, commissions=1000.0,
                     currency='ARS', entry_date='2024-01-10', tc_compra=None),
           take=4.0, currency='USD', sell_currency='USD', exit_price=25.0, chunk_commission=0.5,
           tc_venta=1.0, tc_blue=1400.0, hist=False, op_date='2024-06-10', transfer_out=False,
           salida=dict(pnl_usd=26.409090909090907, invested_usd=73.0909090909091,
                       costo_en_su_moneda=80400.0, resultado=None)),
]


class UnTramoDosMotores(unittest.TestCase):
    """Los dos motores, escenario por escenario, contra los números congelados."""

    def setUp(self):
        self.conn = main.get_db()
        vaciar(self.conn, *TABLAS)
        sembrar_dolares(self.conn)
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"tramo-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
        self.conn.commit()

    def tearDown(self):
        # La tabla global primero y en su propio try: si queda sucia, el test
        # siguiente choca por la clave de la fecha y no por lo que mide.
        try:
            self.conn.execute("DELETE FROM fx_rates_daily")
            self.conn.commit()
        except Exception:
            pass
        try:
            vaciar(self.conn, *TABLAS)
            self.conn.commit()
        finally:
            self.conn.close()

    def _verificar(self, nombre):
        persister, rebuild, res = correr(self.conn, self.uid, nombre)
        # El rebuild tiene que haber rearmado el activo de verdad: si lo salteara,
        # la foto "rebuild" sería la del persister y el test daría un verde falso.
        self.assertEqual(res["errors"], [], res)
        self.assertEqual(res["skipped_manual"], [], res)
        self.assertEqual(len(res["rebuilt"]), 1, res)
        self.assertTrue(res["ventas_reescritas"], "el rebuild no reescribió las ventas")
        esperado = ESPERADO[nombre]
        for motor, foto in (("persister", persister), ("rebuild", rebuild)):
            dif = _parecidos(foto, esperado[motor], f"{nombre}/{motor}")
            self.assertIsNone(dif, f"{dif}\nobtenido: {foto!r}")

    def test_ars_v1(self):
        self._verificar("ars_v1")

    def test_ars_v2(self):
        self._verificar("ars_v2")

    def test_usd(self):
        self._verificar("usd")

    def test_transfer_out(self):
        self._verificar("transfer_out")

    def test_comision_en_otra_moneda(self):
        self._verificar("comision_en_otra_moneda")

    def test_pesos_vendido_en_dolares(self):
        self._verificar("pesos_vendido_en_dolares")

    def test_comision_en_otra_moneda_v1(self):
        self._verificar("comision_en_otra_moneda_v1")

    def test_pesos_vendido_en_dolares_v1(self):
        self._verificar("pesos_vendido_en_dolares_v1")

    def test_cada_escenario_tiene_su_test(self):
        nombres = {n[len("test_"):] for n in dir(self) if n.startswith("test_")}
        self.assertEqual(set(ESCENARIOS) - nombres, set())
        self.assertEqual(set(ESCENARIOS), set(ESPERADO))


_HAY_TRAMO = importlib.util.find_spec("importing.tramo") is not None


@unittest.skipUnless(_HAY_TRAMO, "importing/tramo.py todavía no existe: lo crea la etapa E2b")
class LaFuncionUnicaDaLoMismo(unittest.TestCase):
    """E2b: `costo_y_resultado_del_tramo` con las entradas de cada tramo medido
    devuelve exactamente lo que calculaba el motor de donde salió.

    Se activa solo cuando existe el módulo. Si al activarse la firma real difiere de
    la de la especificación (C.5), se ajusta ESTA llamada, nunca los números."""

    def setUp(self):
        self.conn = main.get_db()
        sembrar_dolares(self.conn)
        self.conn.commit()

    def tearDown(self):
        try:
            self.conn.execute("DELETE FROM fx_rates_daily")
            self.conn.commit()
        finally:
            self.conn.close()

    def test_cada_tramo_medido(self):
        from importing import tramo
        self.assertTrue(TRAMOS, "no hay tramos medidos")
        for t in TRAMOS:
            with self.subTest(escenario=t["escenario"], motor=t["motor"], tramo=t["i"]):
                e = t["entrada"]
                obtenido = tramo.costo_y_resultado_del_tramo(
                    self.conn, lote=dict(e["lote"]), take=e["take"],
                    currency=e["currency"], sell_currency=e["sell_currency"],
                    exit_price=e["exit_price"], chunk_commission=e["chunk_commission"],
                    tc_venta=e["tc_venta"], tc_blue=e["tc_blue"], hist=e["hist"],
                    op_date=e["op_date"], transfer_out=e["transfer_out"])
                # Sólo las salidas que el motor de origen tenía (el rebuild no
                # calcula `proceeds_native`).
                salida = {k: obtenido[k] for k in t["salida"]}
                dif = _parecidos(salida, t["salida"], f"{t['escenario']}/{t['motor']}/{t['i']}")
                self.assertIsNone(dif, dif)


if __name__ == "__main__":
    unittest.main()
