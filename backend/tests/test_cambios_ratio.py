"""Cambios de ratio de CEDEAR: la lista única y quién la usa, con precios REALES.

El problema (auditoría del 22/10/2026): el aviso «Ajustar» de Posiciones le
preguntaba a Yahoo por los splits de la especie en pesos (`XLE.BA`) y Yahoo la
devuelve VACÍA en 33 cambios reales de los últimos 3 años. Medido: un lote de XLE
cargado a mano en octubre de 2025 mostraba -11% cuando ganaba +77%, y el aviso no
aparecía. La foto de tenencia arreglaba la cantidad pero inventaba un aporte de
$558.000 (-6% en vez de +77%).

Por qué estas pruebas usan precios reales y no `patch(_fetch_ba_splits)`: las
pruebas viejas reemplazaban la consulta a Yahoo por una respuesta inventada, así
que daban verde con la lista de verdad vacía. Acá las velas reales (tramos de
Yahoo guardados en `fixtures/cambios_ratio_series.json`, bajados el 22/10/2026)
entran por `velas_diarias.actualizar` —el mismo camino que la corrida nocturna—,
la lista se arma con `cambios_ratio.recalcular`, y la prueba pasa por el aviso,
el botón «Ajustar» y el import de la foto. Lo único inyectado es lo que Yahoo
anota como splits (también copiado tal cual de Yahoo ese día).

Corre con: cd backend && python3 -m pytest tests/test_cambios_ratio.py
"""
import io
import json
import os
import unittest
import uuid

import pandas as pd

import cambios_ratio
import main
import velas_diarias
from fastapi.testclient import TestClient

_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "cambios_ratio_series.json")
SERIES = json.load(open(_FIX))

# Lo que Yahoo anotaba como splits el 22/10/2026 (pesos, dólares y Nueva York).
SPLITS_YAHOO = {
    "XLE": [("2025-12-05", 2.0)],
    "TQQQ": [("2025-11-20", 2.0)],
    "NFLX": [("2025-11-17", 10.0)],
    "NFLX.BA": [("2025-11-17", 10.0)],
    "NFLXD.BA": [("2024-01-24", 3.0), ("2025-11-17", 10.0)],
    "AAPLD.BA": [("2024-01-24", 2.0)],
    # DuPont: la escisión de Qnity anotada como «split» de 2,39 y la agrupación
    # 1 a 3 real del 24/06/2026 (8-K ante la SEC).
    "DD": [("2025-11-03", 2.39), ("2026-06-24", 0.3333)],
    "DD.BA": [("2026-06-24", 0.3333)],
    # 3D Systems no hizo nada; Yahoo le copió la de DuPont al CEDEAR.
    "DDD.BA": [("2026-06-24", 0.3333)],
    # SPY: cambio de ratio del CEDEAR (Nueva York no hizo nada). Yahoo lo anota
    # en pesos y corrige la serie hacia atrás: en las velas no queda escalón.
    "SPY.BA": [("2026-05-29", 3.0)],
}
CEDEARS = ["XLE", "AAPL", "NFLX", "TQQQ", "DD", "DDD", "FNMA", "AZN", "SPY"]


def _byma(cedear):
    """Los cierres de BYMA como fueron ese día (data912, bajados el 22/10/2026).
    DDD no tiene historia en data912."""
    return SERIES.get(f"BYMA:{cedear}", {})
HOY = "2026-10-22"


def _bajar_de_la_fixture(ticker, periodo):
    s = SERIES.get(ticker) or {}
    idx = pd.to_datetime(sorted(s))
    c = [s[d] for d in sorted(s)]
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": [1000] * len(c)},
                        index=idx)


def _armar_lista():
    """Velas reales por el camino nocturno + la lista de cambios."""
    conn = main.get_db()
    try:
        conn.execute("DELETE FROM velas_diarias")
        conn.execute("DELETE FROM velas_estado")
        conn.execute("DELETE FROM cambios_ratio")
        conn.commit()
        tickers = [t for c in CEDEARS for t in (c, f"{c}.BA")]
        velas_diarias.actualizar(conn, tickers, bajar=_bajar_de_la_fixture, hoy=HOY)
        return cambios_ratio.recalcular(conn, cambios_ratio.cedears_guardados(conn),
                                        splits=lambda t: SPLITS_YAHOO.get(t, []), byma=_byma)
    finally:
        conn.close()


def _filas(cedear):
    conn = main.get_db()
    try:
        return cambios_ratio.todos(conn, cedear)
    finally:
        conn.close()


class ListaDeCambiosTest(unittest.TestCase):
    """La regla sobre precios reales: lo que entra y lo que no."""

    @classmethod
    def setUpClass(cls):
        cls.res = _armar_lista()

    def _confirmados(self, c):
        conn = main.get_db()
        try:
            return cambios_ratio.confirmados(conn, c)
        finally:
            conn.close()

    def test_cambios_que_yahoo_no_anota_en_pesos(self):
        # Ninguno de estos está en la lista de Yahoo para la especie en pesos.
        self.assertEqual(self._confirmados("XLE"), [("2025-12-05", 2.0)])
        self.assertEqual(self._confirmados("AAPL"), [("2024-01-24", 2.0)])
        self.assertEqual(self._confirmados("TQQQ"), [("2025-11-20", 2.0)])

    def test_nflx_no_se_pierde_por_el_balance_del_dia(self):
        # Ese día NFLX subió 10,7% en Nueva York: un filtro «Nueva York se movió
        # menos de 10%» lo tiraba. El cociente ya descuenta a Nueva York.
        self.assertIn(("2024-01-24", 3.0), self._confirmados("NFLX"))

    def test_escision_de_dupont_no_es_un_cambio_de_cantidad(self):
        filas = {f["fecha"]: f for f in _filas("DD")}
        self.assertEqual(filas["2025-11-03"]["estado"], cambios_ratio.DESCARTADO)
        self.assertIn("escisión", filas["2025-11-03"]["motivo"])
        # La agrupación 1 a 3 sí es real y el CEDEAR la trasladó.
        self.assertEqual(len(self._confirmados("DD")), 1)
        d, f = self._confirmados("DD")[0]
        self.assertEqual(d, "2026-06-24")
        self.assertAlmostEqual(f, 1 / 3)

    def test_lo_que_yahoo_copia_sin_respaldo_queda_dudoso(self):
        self.assertEqual(self._confirmados("DDD"), [])
        self.assertEqual({f["estado"] for f in _filas("DDD") if f["fecha"] == "2026-06-24"},
                         {cambios_ratio.DUDOSO})

    def test_spy_anotado_y_corregido_por_yahoo_lo_confirma_byma(self):
        # El aviso viejo lo ofrecía (era real: hubo un reclamo de un usuario); la
        # regla nueva no puede perderlo por no ver el escalón en la serie corregida.
        self.assertEqual(self._confirmados("SPY"), [("2026-05-29", 3.0)])
        self.assertEqual([f["origen"] for f in _filas("SPY")], ["yahoo+byma"])

    def test_precio_quieto_y_precio_roto_no_entran(self):
        self.assertEqual(self._confirmados("FNMA"), [])   # $240 quieto meses
        self.assertEqual(self._confirmados("AZN"), [])    # $214 → $47.328

    def test_la_corrida_no_pisa_lo_puesto_a_mano(self):
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM cambios_ratio WHERE cedear='DDD' AND fecha='2026-06-24'")
            conn.execute(
                "INSERT INTO cambios_ratio (cedear, fecha, factor, estado, origen, motivo) "
                "VALUES ('DDD', '2026-06-24', NULL, 'descartado', 'manual', 'revisado')")
            conn.commit()
            cambios_ratio.recalcular(conn, ["DDD"], splits=lambda t: SPLITS_YAHOO.get(t, []), byma=_byma)
            filas = [f for f in cambios_ratio.todos(conn, "DDD") if f["fecha"] == "2026-06-24"]
        finally:
            conn.close()
        self.assertEqual([(f["origen"], f["estado"]) for f in filas], [("manual", "descartado")])
        _armar_lista()

    def test_lo_viejo_que_salio_de_la_ventana_de_velas_no_se_borra(self):
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM velas_diarias WHERE symbol IN ('AAPL','AAPL.BA') AND date < '2024-02-01'")
            conn.commit()
            cambios_ratio.recalcular(conn, ["AAPL"], splits=lambda t: SPLITS_YAHOO.get(t, []), byma=_byma)
            self.assertEqual(cambios_ratio.confirmados(conn, "AAPL"), [("2024-01-24", 2.0)])
        finally:
            conn.close()
        _armar_lista()


class _ConUsuario(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _armar_lista()

    def setUp(self):
        self.http = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"ratio-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "IOL", "ARS"))
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "Cocos", "ARS"))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def _lote(self, asset, qty, precio, fecha, broker="IOL"):
        conn = main.get_db()
        try:
            pid = conn.execute(
                """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                       invested, entry_date, asset_type, currency)
                   VALUES (?,?,?,0,?,?,?,?,'CEDEAR','ARS')""",
                (self.uid, broker, asset, precio, qty, precio * qty, fecha)).lastrowid
            conn.commit()
            return pid
        finally:
            conn.close()

    def _avisos(self):
        r = self.http.get("/api/positions/split-check", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return {s["pid"]: s for s in r.json()["suggestions"]}

    def _ajustar(self, pid):
        r = self.http.post(f"/api/positions/{pid}/adjust-ratio", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _lotes(self, asset):
        conn = main.get_db()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT quantity, buy_price, invested FROM positions "
                "WHERE user_id=? AND asset=? AND is_cash=0 ORDER BY id", (self.uid, asset))]
        finally:
            conn.close()


class AvisoDePosicionesTest(_ConUsuario):
    """El aviso y el botón, con la lista armada de precios reales."""

    def test_lote_a_mano_de_xle_ahora_tiene_aviso(self):
        # 10 XLE el 15/10/2025 a $62.925 (el cierre real de ese día).
        pid = self._lote("XLE", 10, 62925.0, "2025-10-15")
        av = self._avisos()
        self.assertIn(pid, av)
        self.assertAlmostEqual(av[pid]["factor"], 2.0)
        self.assertEqual(av[pid]["ex_date"], "2025-12-05")
        self.assertEqual(av[pid]["evidence"], "fecha")
        out = self._ajustar(pid)
        self.assertFalse(out["already_applied"])
        lote = self._lotes("XLE")[0]
        self.assertAlmostEqual(lote["quantity"], 20.0)
        self.assertAlmostEqual(lote["invested"], 629250.0)   # la plata no cambia
        # Idempotente: el segundo clic no duplica.
        self.assertTrue(self._ajustar(pid)["already_applied"])
        self.assertAlmostEqual(self._lotes("XLE")[0]["quantity"], 20.0)
        self.assertNotIn(pid, self._avisos())

    def test_cargo_la_cantidad_de_hoy_con_la_fecha_original(self):
        # Cargó 20 a $31.462 (precio ya partido) con la fecha de octubre: el
        # lote YA está en la escala nueva. Ajustar lo llevaría a 40.
        pid = self._lote("XLE", 20, 31462.5, "2025-10-15")
        self.assertNotIn(pid, self._avisos())
        self.assertTrue(self._ajustar(pid)["already_applied"])
        self.assertAlmostEqual(self._lotes("XLE")[0]["quantity"], 20.0)

    def test_precio_que_no_coincide_con_ninguna_escala_pregunta(self):
        pid = self._lote("XLE", 10, 45000.0, "2025-10-15")
        self.assertEqual(self._avisos()[pid]["evidence"], "pregunta")

    def test_aapl_del_24_01_2024(self):
        pid = self._lote("AAPL", 20, SERIES["AAPL.BA"]["2024-01-10"], "2024-01-10")
        av = self._avisos()
        self.assertAlmostEqual(av[pid]["factor"], 2.0)
        self.assertEqual(av[pid]["evidence"], "fecha")

    def test_dupont_ofrece_solo_la_agrupacion_real(self):
        # La serie guardada viene corregida por Yahoo por la agrupación (×3 hacia
        # atrás): lo que la persona pagó el 20/10/2025 fue un tercio de eso.
        pid = self._lote("DD", 30, SERIES["DD.BA"]["2025-10-20"] / 3, "2025-10-20")
        av = self._avisos()[pid]
        self.assertEqual([r["ex_date"] for r in av["raw_splits"]], ["2026-06-24"])
        self.assertAlmostEqual(av["suggested_qty"], 10.0)

    def test_dupont_cargado_con_la_cantidad_de_hoy_no_se_ofrece(self):
        pid = self._lote("DD", 10, SERIES["DD.BA"]["2025-10-20"], "2025-10-20")
        self.assertNotIn(pid, self._avisos())

    def test_spy_sigue_ofreciendose(self):
        pid = self._lote("SPY", 10, SERIES["BYMA:SPY"]["2026-05-04"], "2026-05-04")
        av = self._avisos()[pid]
        self.assertAlmostEqual(av["factor"], 3.0)
        self.assertEqual(av["evidence"], "fecha")

    def test_ddd_ya_no_ofrece_dividir_por_tres(self):
        pid = self._lote("DDD", 30, 29.0, "2026-03-02")
        self.assertNotIn(pid, self._avisos())
        self._ajustar(pid)
        self.assertAlmostEqual(self._lotes("DDD")[0]["quantity"], 30.0)

    def test_comprado_despues_del_cambio_no_se_toca(self):
        pid = self._lote("XLE", 10, 34980.0, "2025-12-05")
        self.assertNotIn(pid, self._avisos())


# Cocos: Movimientos con la compra de octubre y el Resumen (foto) de octubre de 2026.
MOV_XLE = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;"
           "instrumento;moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total\n"
           "1;1;15-10-2025;15-10-2025;Compra;Energy Select Sector SPDR (XLE);ARS;BYMA;10;62925,00;"
           "629250,00;0;0;0;0;629250,00\n")
FOTO_XLE = ("instrumento;cantidad;precio;moneda;total\n"
            "Energy Select Sector SPDR (XLE);20;55800,00;ARS;1116000,00\n"
            "ARS;0;0;ARS;0\n")


class ImportsTest(_ConUsuario):
    """Lo que trae cada importador no se vuelve a ofrecer, y la foto no inventa plata."""

    def _import(self, ruta, nombre, contenido):
        r = self.http.post(ruta, files={"file": (nombre, io.BytesIO(contenido.encode()), "text/csv")},
                           data={"broker": "Cocos", "format": "cocos"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.http.post("/api/imports/confirm", json={"session_id": r.json()["session_id"]},
                           headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def test_foto_acredita_los_cedears_del_cambio_a_cero(self):
        self._import("/api/imports/preview", "mov.csv", MOV_XLE)
        self.assertEqual(len(self._avisos()), 1)            # 10 viejos: aviso ×2
        self._import("/api/imports/tenencia/preview", "portfolio_report_20261021.csv", FOTO_XLE)
        lotes = self._lotes("XLE")
        self.assertAlmostEqual(sum(l["quantity"] for l in lotes), 20.0)
        # La plata puesta sigue siendo la de octubre: sin el arreglo eran
        # $1.187.250 (10 «comprados» a $55.800 con un aporte que nunca existió).
        self.assertAlmostEqual(sum(l["invested"] or 0 for l in lotes), 629250.0)
        self.assertEqual(self._avisos(), {})                # y no se ofrece ajustar de nuevo
        conn = main.get_db()
        try:
            aporte = conn.execute(
                "SELECT COALESCE(SUM(n.gross_amount),0) s FROM import_normalized_tx n "
                "JOIN import_batches b ON b.id=n.batch_id WHERE b.user_id=? "
                "AND n.operation_type='DEPOSIT' AND n.notes LIKE 'Tenencia — aporte%'",
                (self.uid,)).fetchone()["s"]
        finally:
            conn.close()
        self.assertAlmostEqual(aporte, 0.0)

    def test_split_a_cero_sin_descripcion_cuenta_como_ya_traido(self):
        # Balanz Resultados trae el split como un lote a $0 SIN descripción: la
        # marca vieja buscaba la palabra «split» y lo dejaba a un clic de duplicar.
        from importing import pipeline as pl, persister as ps, rebuild as rb
        from importing.schema import NormalizedTx, OP_BUY, OP_DEPOSIT
        h = main._ImportHelpers()
        for n in ("_adjust_broker_cash", "_update_monthly_pnl_realized", "_update_monthly_flow",
                  "_repair_monthly_chain", "_ensure_usd_sibling", "_recalc_pnl_realized_from_ops"):
            setattr(h, n, getattr(main, n))
        txs = [NormalizedTx(row_index=-1, date="2025-10-01", broker="IOL", operation_type=OP_DEPOSIT,
                            gross_amount=629250, currency="ARS"),
               NormalizedTx(row_index=-2, date="2025-10-15", broker="IOL", operation_type=OP_BUY,
                            asset_symbol="XLE", asset_type="CEDEAR", quantity=10, unit_price=62925,
                            gross_amount=629250, currency="ARS"),
               NormalizedTx(row_index=-3, date="2025-12-05", broker="IOL", operation_type=OP_BUY,
                            asset_symbol="XLE", asset_type="CEDEAR", quantity=10, unit_price=0,
                            gross_amount=0, currency="ARS")]
        conn = main.get_db()
        try:
            with conn:
                sid = pl.store_preview_txs(conn, self.uid, broker="IOL", parser_format="iol",
                                           file_name="res", txs=txs)
                t2, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=sid)
                ps.persist_batch(conn, uid=self.uid, batch_id=sid, txs=t2,
                                 raw_row_ids_by_index=raw, helpers=h)
                rb.rebuild_fifo_after_import(conn, self.uid, sid,
                                             tc_blue=ps._read_tc_blue(conn, uid=self.uid))
        finally:
            conn.close()
        self.assertAlmostEqual(sum(l["quantity"] for l in self._lotes("XLE")), 20.0)
        self.assertEqual(self._avisos(), {})


class ParsersTest(unittest.TestCase):
    def test_ppi_reconoce_cambio_de_ratio(self):
        from importing.parsers import ppi
        self.assertEqual(ppi._classify("acreditacion cambio de ratio / xle"), "corporate")


class ReglaTest(unittest.TestCase):
    def test_factor_redondo(self):
        self.assertEqual(cambios_ratio.factor_redondo(2.03), 2.0)
        self.assertEqual(cambios_ratio.factor_redondo(0.334), 1 / 3)
        self.assertEqual(cambios_ratio.factor_redondo(25.0), 25.0)    # no 24 (BKNG, HUT)
        self.assertEqual(cambios_ratio.factor_redondo(0.05), 1 / 20)  # no 1/19 (SPCE)
        self.assertIsNone(cambios_ratio.factor_redondo(2.38))      # escisión de DuPont
        self.assertIsNone(cambios_ratio.factor_redondo(1.0099))    # dividendo en acciones de SCCO


if __name__ == "__main__":
    unittest.main()
