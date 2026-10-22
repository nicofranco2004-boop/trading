"""Un depósito adentro del mes NO es ganancia del mes en Reportes.

EL BUG (encontrado leyendo el código el 2026-10-15, sesión sharp-kilby; acá se
MIDE). Para un mes cerrado sin los dos bordes estrictos (`bordes_mercado_periodo`
exige una foto medida el día anterior al mes, y en producción la consigue 1 de
cada 50 usuarios), Reportes mide el mes con `twr.curva_indexada`. El % sale bien
—el motor descuenta los flujos adentro de cada leg—, pero el MONTO se armaba
aparte en `reporting/builder.py`:

    valor final − valor inicial − (aportado final − aportado inicial)

leyendo el aportado de los puntos de `curva`. Esos puntos no traían
`net_deposited` (sólo lo traían los de `tramos`, de `serie_medible`), así que el
flujo daba 0 y los US$5.000 depositados el 15 se publicaban como "+US$5.000" de
resultado al lado de un 0,0 %.

Todo entra por las puertas de la app: el depósito por POST /api/cash/flow (el
botón de efectivo), las fotos de cada noche por `snapshots_job.
take_snapshot_for_user` (el MISMO código del cron, corrido día por día en orden:
las fotos de antes del 15 se sacan antes de cargar el depósito, como en la vida
real) y lo que se mira es GET /api/reports/period/month/2026-07, lo que pide la
pantalla. Cuenta sólo con efectivo en dólares: el mercado está QUIETO, así que
el resultado verdadero del mes es exactamente cero.

Corre con: cd backend && python3 -m pytest tests/test_deposito_en_el_mes_no_es_ganancia.py
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from fastapi.testclient import TestClient

import main
import snapshots_job
import twr


def _dias(y, m, d0, d1):
    return [f"{y:04d}-{m:02d}-{d:02d}" for d in range(d0, d1 + 1)]


class DepositoEnElMes(unittest.TestCase):
    BROKER = "IBKR"
    INICIAL = 10000.0
    DEPOSITO = 5000.0
    DIA_DEPOSITO = "2026-07-15"

    def setUp(self):
        self.conn = main.get_db()
        for t in ("operations", "positions", "monthly_entries", "snapshots",
                  "fx_rates_daily", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,'plus')",
            ("deposito_en_el_mes@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, self.BROKER, "USDT"))
        # El dólar de cada día de junio y julio, subiendo: sin esto la vista en
        # pesos no tiene con qué convertir y cae a la contabilidad, o sea que el
        # test en pesos pasaría por otra rama y no probaría nada.
        for i, d in enumerate(_dias(2026, 6, 1, 30) + _dias(2026, 7, 1, 31)):
            tc = 1200.0 + 2 * i
            self.conn.execute(
                "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
                "VALUES (?,?,?,'manual')", (d, tc, tc))
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        self.conn.close()

    # ── caminos reales ──────────────────────────────────────────────────────
    def _depositar(self, monto, fecha):
        r = self.client.post("/api/cash/flow", json={
            "broker_name": self.BROKER, "direction": "deposit", "amount": monto,
            "date": fecha})
        self.assertEqual(r.status_code, 200, r.text)

    def _foto_del_cron(self, fecha):
        with mock.patch.object(snapshots_job, "fetch_prices_for_symbols",
                               side_effect=lambda syms, cy: {s: 1.0 for s in syms}):
            with self.conn:
                res = snapshots_job.take_snapshot_for_user(
                    self.conn, self.uid, 1200, {}, fecha)
        self.assertTrue(res.get("ok"), f"el cron no escribió el {fecha}: {res}")

    def _cargar_julio(self):
        """US$10.000 desde junio, US$5.000 más el 15 de julio, nada más.

        La primera foto es del 3 de julio a propósito: sin foto el 30/06 no hay
        borde estricto, y el mes se mide con `curva_indexada` — la rama del bug."""
        self._depositar(self.INICIAL, "2026-06-10")
        for d in _dias(2026, 7, 3, 14):
            self._foto_del_cron(d)
        self._depositar(self.DEPOSITO, self.DIA_DEPOSITO)
        for d in _dias(2026, 7, 15, 31):
            self._foto_del_cron(d)

    def _reporte(self, moneda="usd"):
        r = self.client.get("/api/reports/period/month/2026-07",
                            params={"moneda": moneda})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ── lo que se mide ───────────────────────────────────────────────────────
    def test_el_escenario_es_el_de_la_rama_del_motor(self):
        """Sin esto los demás tests podrían pasar por otra rama y no probar nada:
        el mes tiene que medirse con `curva_indexada` (ventana del 3 al 31), con
        las fotos del cron anotando el aportado de cada noche."""
        self._cargar_julio()
        nd = dict(self.conn.execute(
            "SELECT date, net_deposited FROM snapshots WHERE user_id=? ORDER BY date",
            (self.uid,)).fetchall())
        self.assertAlmostEqual(nd["2026-07-14"], self.INICIAL, places=2)
        self.assertAlmostEqual(nd["2026-07-15"], self.INICIAL + self.DEPOSITO, places=2)
        m = self._reporte()["metrics"]
        self.assertEqual((m["medido_desde"], m["medido_hasta"]),
                         ("2026-07-03", "2026-07-31"))

    def test_el_porcentaje_del_mes_es_cero(self):
        """El % ya salía bien: el motor descuenta el flujo adentro del leg."""
        self._cargar_julio()
        self.assertAlmostEqual(self._reporte()["metrics"]["delta_pct"], 0.0, places=2)

    def test_el_monto_del_mes_no_cuenta_el_deposito_como_ganancia(self):
        """EL BUG. Medido antes del arreglo: delta_usd = +5000,0 al lado de un
        delta_pct = 0,0 — el depósito entero publicado como resultado."""
        self._cargar_julio()
        m = self._reporte()["metrics"]
        self.assertAlmostEqual(m["delta_usd"], 0.0, places=2)

    def test_tambien_con_el_selector_en_pesos(self):
        """En pesos el monto sigue en dólares (lo convierte la pantalla), así que
        tiene que ser el mismo cero. Y tiene que pasar por la MISMA rama: medido
        por el motor, con la ventana del 3 al 31."""
        self._cargar_julio()
        m = self._reporte("ars")["metrics"]
        self.assertEqual((m["basis"], m["medido_desde"], m["medido_hasta"]),
                         ("mercado", "2026-07-03", "2026-07-31"))
        self.assertAlmostEqual(m["delta_usd"], 0.0, places=2)

    def test_los_puntos_de_la_curva_traen_lo_aportado(self):
        """Donde nace: el punto de la curva trae el aportado de su fecha, el mismo
        que el punto de la serie medible de la que sale."""
        self._cargar_julio()
        c = twr.curva_indexada(self.conn, self.uid, "2026-07-01", "2026-07-31")
        serie = {p["date"]: p for t in c["tramos"] for p in t}
        self.assertTrue(c["curva"])
        for p in c["curva"]:
            self.assertIn("net_deposited", p, p)
            self.assertEqual(p["net_deposited"], serie[p["date"]]["net_deposited"])


if __name__ == "__main__":
    unittest.main()
