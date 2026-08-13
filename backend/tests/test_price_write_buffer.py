"""Mirar la cartera no puede generar una escritura por visita.

EL PROBLEMA (log de prod, 13/08). `/api/prices` es el endpoint más caliente del
stack —Dashboard, Cartera, Insights, Home, Goals y Events lo pegan en cada
montaje de página— y ESCRIBÍA en `asset_last_price` en cada llamada. O sea que el
volumen de escritura de Rendi escalaba con las VISITAS, no con las operaciones de
la gente: diez personas mirando su cartera generaban más escrituras que diez
cargando movimientos.

Sobre SQLite, que tiene UN SOLO escritor para toda la base, eso es una cola que
no drena. En el log se veía exactamente así:

    WARNING: persist_last_prices falló (migration pendiente?): database is locked
    ERROR:   500 en POST /api/positions — Error al crear posición: database is locked

El precio y la posición del usuario peleando por la misma cerradura.

Ahora los precios se acumulan en memoria y bajan a disco como mucho 1×/minuto, en
UNA transacción con todos los símbolos juntos.

Corre con: cd backend && python3 -m pytest tests/test_price_write_buffer.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _buffer_limpio():
    with main._last_price_buf_lock:
        main._last_price_buf.clear()
    main._last_price_flushed_at = 0.0
    yield
    with main._last_price_buf_lock:
        main._last_price_buf.clear()


def _guardados():
    conn = main.get_db()
    try:
        return {r[0]: r[1] for r in conn.execute(
            "SELECT symbol, price FROM asset_last_price").fetchall()}
    finally:
        conn.close()


def test_cien_visitas_hacen_una_sola_escritura(monkeypatch):
    """EL test. Antes: 100 requests = 100 transacciones de escritura."""
    escrituras = []
    real = main.persist_last_prices
    monkeypatch.setattr(main, "persist_last_prices",
                        lambda conn, filas: (escrituras.append(len(filas)), real(conn, filas))[1])

    for i in range(100):
        main._fill_last_known_prices({"AAPL": 100.0 + i, "GGAL.BA": 5000.0 + i})

    assert len(escrituras) == 1, (
        f"{len(escrituras)} escrituras para 100 visitas — el buffer no está "
        "conteniendo nada. Antes del fix esto daba 100.")
    # y la única que hubo bajó los dos símbolos juntos
    assert escrituras[0] == 2


def test_el_precio_no_se_pierde_ni_envejece_mientras_espera_en_el_buffer():
    """El buffer no puede ser un agujero: lo encolado tiene que seguir
    respondiendo a quien pregunte, y con el valor MÁS NUEVO."""
    # Estado de RÉGIMEN: acaba de bajar, así que lo próximo se queda encolado.
    # (Con flushed_at=0 la primera llamada baja enseguida y no probaríamos nada.)
    main._last_price_flushed_at = time.time()
    main._fill_last_known_prices({"NVDA": 900.0})

    # todavía no bajó a disco...
    assert "NVDA" not in _guardados()

    # ...pero un símbolo sin precio se completa igual, desde el buffer
    res = {"NVDA": None}
    main._fill_last_known_prices(res)
    assert res["NVDA"] == 900.0, "el buffer tiene que responder como si fuera la tabla"

    # y si llega uno más nuevo, gana el más nuevo
    main._fill_last_known_prices({"NVDA": 950.0})
    res2 = {"NVDA": None}
    main._fill_last_known_prices(res2)
    assert res2["NVDA"] == 950.0


def test_al_bajar_a_disco_queda_el_ultimo_valor():
    main._fill_last_known_prices({"MSFT": 400.0})
    main._fill_last_known_prices({"MSFT": 410.0})
    main._flush_last_prices_si_toca(forzar=True)

    assert _guardados().get("MSFT") == 410.0
    with main._last_price_buf_lock:
        assert not main._last_price_buf, "el buffer tiene que quedar vacío tras bajar"


def test_si_la_bajada_falla_los_precios_vuelven_al_buffer(monkeypatch):
    """Perder estos precios no es cosmético: son el fallback de valuación cuando
    el mercado no cotiza. Sin ellos la cartera cae a cost basis, o sea muestra lo
    que pagaste como si fuera el precio de hoy."""
    main._last_price_flushed_at = time.time()   # que se quede en el buffer
    main._fill_last_known_prices({"TSLA": 250.0})

    def explota(conn, filas):
        raise RuntimeError("disco lleno")
    monkeypatch.setattr(main, "persist_last_prices", explota)

    assert main._flush_last_prices_si_toca(forzar=True) == 0
    with main._last_price_buf_lock:
        assert main._last_price_buf.get("TSLA") == 250.0, (
            "tras una bajada fallida el precio tiene que volver al buffer")


def test_lo_ya_guardado_en_disco_se_sigue_leyendo():
    """El buffer no reemplaza a la tabla: la completa. Un símbolo que se guardó
    en otra corrida (o en otro proceso) tiene que seguir apareciendo."""
    conn = main.get_db()
    with conn:
        main.persist_last_prices(conn, {"AMZN": 180.0})
    conn.close()

    res = {"AMZN": None}
    main._fill_last_known_prices(res)
    assert res["AMZN"] == 180.0
