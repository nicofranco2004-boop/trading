"""El costo y el resultado de UN tramo de venta: una sola cuenta para los tres motores.

QUÉ ES UN TRAMO. Una venta FIFO consume lotes de a uno: cada pedazo (un lote entero
o parte de uno) es un tramo. Por cada tramo hay que saber cuánto costó en dólares
(`invested_usd`), cuánto se ganó (`pnl_usd`), cuánta plata entró en la moneda de la
venta (`proceeds_native`) y el resultado en pesos y en dólares (`resultado`, de
`resultado_dual`).

POR QUÉ VIVE ACÁ. Esa cuenta estaba copiada, renglón por renglón, en el que guarda
la venta cuando se confirma un archivo (`persister._persist_sell_fifo`) y en el que
rearma toda la historia (`rebuild._replay_asset`). «Mover a otro broker» la
necesita una tercera vez: el costo C de los títulos que se pasan (sección C.5 de la
especificación). Tres copias de la misma cuenta es como se generó la deuda que
estamos limpiando (`CLAUDE.md`, regla de propagación), así que se MUDÓ acá sin
reescribirla: cada renglón es el de los motores, con sus comentarios.

QUÉ QUEDA EN CADA MOTOR. Elegir los lotes, cuánto se toma de cada uno (`take`),
qué dólar de venta corresponde (`tc_venta`), si la fila es un retiro (`transfer_out`:
el persister mira la marca de la fila; el rebuild, además, el exchange) y qué se hace
con el resultado (la fila de `operations`, la caja, achicar el lote). Esta función
sólo calcula: no lee ni escribe ninguna tabla propia (resultado_dual lee el dólar de
cada fecha de `fx_rates_daily`).

LO QUE PROTEGE. `tests/test_un_tramo_dos_motores.py` congeló, antes de la mudanza,
lo que calculaba cada motor tramo por tramo (y la clase `LaFuncionUnicaDaLoMismo`
llama a esta función con esas mismas entradas).
"""
from __future__ import annotations

from typing import Any, Dict

try:
    from fx import costo_en_moneda_de_venta, costo_del_lote, RIEL_MEP
    import resultado_dual as _resultado_dual
except ImportError:  # pragma: no cover — import relativo según cómo se cargue el paquete
    from ..fx import costo_en_moneda_de_venta, costo_del_lote, RIEL_MEP
    from .. import resultado_dual as _resultado_dual


def _cantidad_del_lote(lote: Dict[str, Any]) -> float:
    """La cantidad del lote ANTES de este tramo. El rebuild la llama `qty` (sus lotes
    viven en memoria) y `positions` la llama `quantity` (el persister le pasa la fila):
    se acepta cualquiera de las dos."""
    q = lote["qty"] if "qty" in lote else lote.get("quantity")
    return q or 0


def costo_y_resultado_del_tramo(conn, *, lote: Dict[str, Any], take: float, currency: str,
                                sell_currency: str, exit_price: float, chunk_commission: float,
                                tc_venta: float, tc_blue: float, hist: bool, op_date: str,
                                transfer_out: bool) -> Dict[str, Any]:
    """Costo y resultado de tomar `take` unidades de `lote` en una venta.

    `lote`: dict con invested, buy_price, qty (o quantity), commissions, currency,
    entry_date y tc_compra (los que falten valen None). `currency` es la moneda con la
    que se ramifica la cuenta y `sell_currency` la que se le pasa al resultado en dos
    monedas: en los dos motores son la misma (alias), se mantienen las dos para que
    el código mudado diga lo mismo que decía.

    Devuelve {"pnl_usd", "invested_usd", "proceeds_native", "resultado",
    "costo_en_su_moneda"}. `proceeds_native` lo usa sólo el persister (la caja); el
    rebuild no mueve caja.
    """
    pos_qty = _cantidad_del_lote(lote)
    ratio = take / pos_qty if pos_qty > 0 else 0
    pos_buy_commissions = lote.get("commissions") or 0
    # El costo del lote sale de `fx.costo_del_lote`: si la fila no tiene
    # `invested` (lote cargado a mano sin ese campo) es precio × cantidad.
    # Acá decía `(p["invested"] or 0)`: costo CERO, y la rama de pesos de
    # abajo anotaba todo lo cobrado como ganancia.
    base_invested = ((costo_del_lote(lote.get("invested"), lote.get("buy_price"), pos_qty) or 0)
                     + pos_buy_commissions)
    # El costo de este pedazo en la moneda en que se COMPRÓ (antes de llevarlo a
    # la de la venta): lo usa el resultado en las dos monedas, más abajo.
    costo_en_su_moneda = base_invested * ratio

    # Moneda nativa del lote — la guardamos en positions.currency desde
    # el BUY. Si el lote es viejo (pre-migración) o no la trajo el parser,
    # asumimos la moneda del broker para back-compat.
    lot_currency = lote.get("currency") or currency

    # CROSS-CURRENCY: el SELL es en otra moneda que el BUY → convertimos el
    # cost basis del lote a la moneda del SELL. Sin esto, un lote comprado por
    # USD 573 vs SELL en ARS daba P&L de +160000%.
    # La cuenta vive en `fx.costo_en_moneda_de_venta` — LA misma que usan los
    # motores y la venta manual. Estaba copiada en los tres, y la del
    # formulario manual no miraba el `fx_version` de la cuenta.
    #
    # ⚠️ En la pata USD→ARS el TC TIENE que ser el MISMO que `tc_venta`, no
    # `tc_blue`: el costo USD se lleva a pesos acá y después `pnl_ars/tc_venta`
    # lo divide de vuelta, así que el TC se CANCELA y el costo USD se preserva.
    # Mientras los dos eran `tc_blue` daba igual cuál se usara; con `tc_venta`
    # siendo el TC histórico de la fecha, dejar `tc_blue` acá los hace divergir
    # ~5× y mete una pérdida fantasma en TODA operación dólar-MEP — y sólo por
    # el camino del rebuild (re-import, foto, backfill), o sea invisible en un
    # test normal. Ese acople es justamente lo que la función única protege.
    base_invested = costo_en_moneda_de_venta(
        base_invested, lot_currency, currency,
        conn=conn, entry_date=lote.get("entry_date"),
        tc_venta=tc_venta, tc_blue=tc_blue, historico=hist)

    entry_invested = base_invested * ratio if base_invested else None

    if transfer_out:
        # RETIRO/TRANSFERENCIA del activo fuera de la cuenta (ej. cripto que
        # sale de un exchange a una wallet, polvo→BNB, o el pase a otro broker
        # del usuario): NO es una venta → cerramos el lote A COSTO (P&L 0) y NO
        # generamos cash (no entró plata). Sin esto, un retiro bookeaba una
        # pérdida fantasma = costo del lote.
        if currency == "ARS":
            invested_usd = (entry_invested or 0) / tc_venta if entry_invested and tc_venta else 0
        else:
            invested_usd = entry_invested if entry_invested is not None else ((lote.get("buy_price") or 0) * take)
        pnl_usd = 0.0
        proceeds_native = 0.0
    elif currency == "ARS":
        # Mismo modelo que el flow manual con FX-phantom-fix:
        # cost basis y venta se valúan al MISMO TC (el de venta).
        pnl_ars_chunk = exit_price * take - (entry_invested or 0) - chunk_commission
        pnl_usd = pnl_ars_chunk / tc_venta if tc_venta else 0
        invested_usd = (entry_invested or 0) / tc_venta if entry_invested and tc_venta else 0
        proceeds_native = exit_price * take - chunk_commission
    else:
        cost = entry_invested if entry_invested is not None else ((lote.get("buy_price") or 0) * take)
        pnl_usd = (exit_price * take) - cost - chunk_commission
        invested_usd = cost
        proceeds_native = exit_price * take - chunk_commission

    # El resultado en pesos y en dólares, cada punta a su dólar: la MISMA cuenta
    # que la venta a mano (resultado_dual). Dólar de compra: el del lote (el que
    # usa Cartera; en el rebuild, el que queda en `positions.tc_compra`:
    # `_lot_tc_compra`, el del evento o, si no, el de la fecha); de venta: el de
    # la fecha, también en v1 (donde `tc_venta` es el dólar del import).
    # SÓLO EN CUENTAS v2: en las v1 no se escribe ni la regla ni las columnas (ver
    # main.sell_position_fifo y el docstring de resultado_dual).
    resultado = None
    if hist:
        resultado = _resultado_dual.resultado_en_dos_monedas(
            conn, costo=costo_en_su_moneda, moneda_costo=lot_currency,
            fecha_compra=lote.get("entry_date"),
            cobrado=proceeds_native, moneda_venta=sell_currency, fecha_venta=op_date,
            riel=RIEL_MEP,
            tc_compra=lote.get("tc_compra"),
            retiro=bool(transfer_out))
    # El resultado en dólares: cobrado en dólares − costo en dólares (ver
    # resultado_dual.resultado_en_dolares).
    _en_dolares = _resultado_dual.resultado_en_dolares(resultado)
    if _en_dolares:
        pnl_usd, invested_usd = _en_dolares

    return {
        "pnl_usd": pnl_usd,
        "invested_usd": invested_usd,
        "proceeds_native": proceeds_native,
        "resultado": resultado,
        "costo_en_su_moneda": costo_en_su_moneda,
    }
