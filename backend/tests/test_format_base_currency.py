"""La moneda BASE de cada formato de import.

`FORMAT_BASE_CURRENCY` (importing/pipeline.py) ancla la moneda del broker que el
import auto-crea. Cuando un format_id NO está en esa tabla, `fmt_base` queda en
None y la moneda se INFIERE de las filas — y un export argentino trae muchas filas
en dólares (las compras MEP), así que el broker se auto-crea en USD y las
posiciones y el efectivo EN PESOS terminan adentro de una cuenta marcada en
dólares.

Eso ya pasó en producción: `balanz_movimientos` —el export que el wizard
RECOMIENDA— no estaba en la tabla porque su format_id no es 'balanz'. Medido en la
base: 231 posiciones en pesos de 23 usuarios con el broker "Balanz" marcado USD.
Lo mismo inviu y las dos variantes de Binance.

Este test no fija los valores de hoy: fija la REGLA. Si mañana alguien suma un
parser nuevo y se olvida de anclarlo, el test se lo dice acá y no un usuario tres
meses después.

Corre con: cd backend && python3 -m pytest tests/test_format_base_currency.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.pipeline import FORMAT_BASE_CURRENCY          # noqa: E402
from importing.parsers.registry import list_parsers          # noqa: E402

# El CSV canónico de Rendi es el ÚNICO que no se ancla, y es a propósito: puede
# traer operaciones de cualquier broker en cualquier moneda, así que la moneda
# tiene que salir de las filas. Anclarlo sería el bug opuesto.
SIN_ANCLA_A_PROPOSITO = {"rendi_generic"}


def test_todo_parser_registrado_tiene_moneda_base():
    faltan = sorted(
        p.format_id for p in list_parsers()
        if p.format_id not in FORMAT_BASE_CURRENCY
        and p.format_id not in SIN_ANCLA_A_PROPOSITO
    )
    assert not faltan, (
        "Estos parsers no anclan la moneda del broker, así que el broker que el "
        "import auto-cree puede quedar marcado en la moneda equivocada y las "
        "posiciones en pesos van a vivir en una cuenta en dólares: "
        f"{faltan}. Agregalos a FORMAT_BASE_CURRENCY en importing/pipeline.py "
        "(o a SIN_ANCLA_A_PROPOSITO si de verdad son multi-moneda)."
    )


def test_los_brokers_argentinos_estan_anclados_en_pesos():
    """El caso que rompió: un export AR anclado en USD (o sin anclar) mete los
    pesos del usuario en una cuenta dólar."""
    for fid in ("cocos", "iol", "balanz", "balanz_movimientos", "balanz_resultados",
                "bullmarket", "ieb", "ppi", "inviu"):
        assert FORMAT_BASE_CURRENCY.get(fid) == "ARS", (
            f"{fid} es un broker argentino y tiene que anclar en ARS, "
            f"está en {FORMAT_BASE_CURRENCY.get(fid)!r}")


def test_las_cuentas_en_dolares_no_se_anclaron_en_pesos_por_error():
    """El espejo: Balanz INTERNACIONAL contiene 'balanz' en el nombre pero es la
    cuenta del exterior, en dólares. Anclarla en ARS le dividiría todo por el MEP."""
    assert FORMAT_BASE_CURRENCY["balanz_internacional"] == "USD"
    assert FORMAT_BASE_CURRENCY["schwab"] == "USD"
    for fid in ("binance", "binance_transaction_history", "binance_futures_trade_history"):
        assert FORMAT_BASE_CURRENCY[fid] == "USDT", fid


def test_toda_moneda_de_la_tabla_es_valida():
    """`brokers.currency` sólo acepta ARS/USD/USDT (BrokerIn.valid_currency)."""
    malas = {k: v for k, v in FORMAT_BASE_CURRENCY.items()
             if v not in ("ARS", "USD", "USDT")}
    assert not malas, malas
