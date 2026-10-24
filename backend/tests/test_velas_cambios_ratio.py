"""El gráfico en pesos lee la lista única de cambios de ratio.

Cuando BYMA cambia el ratio de un CEDEAR, Yahoo deja en la serie '.BA' un
escalón de −50 % que no existió (XLE el 05/12/2025) y no lo anota. La lista
única (`cambios_ratio.py`, la misma que usa el aviso «Ajustar» de los lotes) lo
detecta de noche, y `velas_diarias.serie` —la puerta por la que lee todo el que
usa las velas— lo empalma al leer. Lo guardado queda como lo dio Yahoo.

Entra por el camino de producción: la cartera por HTTP, la corrida nocturna real
(`main._run_velas_diarias_job` → `velas_diarias.correr` → `cambios_ratio.correr`)
con Yahoo reemplazado en su punto más bajo por cierres REALES grabados, y la
ficha y /admin por HTTP.

Los casos que importan:
  · los que hoy se arreglan (XLE, XLU, TQQQ, AAPL, MELI, NFLX): en pesos, sin el
    escalón falso; en la ficha, ningún día salta 25 %;
  · FNMA: el precio en pesos quieto meses NO es un cambio de ratio (no se
    empalma, no se le ofrece a nadie);
  · el par «pesos ↔ afuera» lo da la cartera (es un CEDEAR), no el nombre:
    Agrometal (AGRO.BA) y Adecoagro (AGRO en Nueva York) no se comparan, y
    Berkshire (BRKB.BA) se compara con BRK-B;
  · un salto de los últimos días, todavía sin decidir, se esconde y no reescala.

Corre con: cd backend && python3 -m pytest tests/test_velas_cambios_ratio.py
"""
import json
import os
import sys
import unittest
import uuid
from datetime import timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import pandas as pd
from fastapi.testclient import TestClient

import cambios_ratio
import main
import velas_diarias
from fechas import hoy_art_date

# Cierres reales de Yahoo alrededor de cada cambio: los de la lista única
# (XLE, AAPL, NFLX, TQQQ, FNMA…) y XLU/MELI, bajados el 22/10/2026.
SERIES = {}
for _f in ("cambios_ratio_series.json", "grafico_ratio_series.json"):
    with open(os.path.join(HERE, "fixtures", _f)) as fh:
        SERIES.update(json.load(fh))

# Lo que hoy se arregla: (CEDEAR, primer día a escala nueva, por cuánto se
# multiplicó la cantidad).
ARREGLADOS = [("XLE", "2025-12-05", 2.0), ("XLU", "2025-12-05", 2.0), ("TQQQ", "2025-11-20", 2.0),
              ("AAPL", "2024-01-24", 2.0), ("MELI", "2024-01-24", 2.0), ("NFLX", "2024-01-24", 3.0)]


def _df(cierres: dict):
    fechas = sorted(cierres)
    c = [cierres[d] for d in fechas]
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": [1000.0] * len(c)},
                        index=pd.to_datetime(fechas))


def _ruedas(hasta, n):
    out, d = [], hasta - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


class GraficoTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions", "brokers"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'free')", (f"graf-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier, is_admin) "
                "VALUES (?, 'x', 1, 1, 'pro', 1)", (f"graf-adm-{tag}@rendi.test",))
            self.admin = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.h_admin = {"Authorization": f"Bearer {main.create_token(self.admin)}"}
        self.series = dict(SERIES)
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia",
                              lambda t, *a, **k: _df(self.series[t]) if t in self.series else pd.DataFrame()),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   # Las listas de splits de Yahoo y la historia de BYMA: nada.
                   # Todo lo de abajo sale del cociente, como XLE en la vida real.
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {})]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _broker(self, name, currency, h=None):
        r = self.client.post("/api/brokers", json={"name": name, "currency": currency}, headers=h or self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def _posicion(self, broker, asset, asset_type, h=None):
        r = self.client.post("/api/positions", json={"broker": broker, "asset": asset, "quantity": 10,
                                                     "buy_price": 100, "asset_type": asset_type},
                             headers=h or self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _admin(self):
        r = self.client.get("/api/admin/velas", headers=self.h_admin)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _mayor_salto(self, cierres):
        return max(abs(b / a - 1) for a, b in zip(cierres, cierres[1:]))

    def test_los_cedears_que_hoy_se_arreglan(self):
        self._broker("IOL", "ARS")
        for c, _, _ in ARREGLADOS:
            self._posicion("IOL", c, "CEDEAR")
        main._run_velas_diarias_job()

        conn = main.get_db()
        try:
            for c, fecha, factor in ARREGLADOS:
                with self.subTest(c):
                    self.assertEqual(cambios_ratio.para_el_grafico(conn, c)["escalones"], [(fecha, factor)])
                    crudas = [v["close"] for v in velas_diarias._crudas(conn, f"{c}.BA")]
                    empalmadas = [v["close"] for v in velas_diarias.serie(conn, f"{c}.BA")]
                    self.assertGreater(self._mayor_salto(crudas), 0.4, "lo guardado es lo de Yahoo, con el escalón")
                    self.assertLess(self._mayor_salto(empalmadas), 0.25, "la puerta de lectura lo empalma")
                    # Y la ficha en pesos, por HTTP.
                    r = self.client.get(f"/api/tecnico/{c}?moneda=ars", headers=self.h)
                    self.assertEqual(r.status_code, 200, r.text)
                    puntos = [p["c"] for p in r.json()["puntos"]]
                    self.assertLess(self._mayor_salto(puntos), 0.25)
        finally:
            conn.close()
        adm = self._admin()
        self.assertEqual(sorted((x["symbol"], x["date"], x["estado"]) for x in adm["cambios_de_ratio"]),
                         sorted((f"{c}.BA", f, "confirmado") for c, f, _ in ARREGLADOS))

    def test_fnma_precio_quieto_no_es_un_cambio_de_ratio(self):
        # FNMA: el CEDEAR en pesos quedó en $240 meses sin operarse mientras
        # Nueva York se movía. El cociente salta, pero no es un cambio de ratio.
        self._broker("IOL", "ARS")
        self._posicion("IOL", "FNMA", "CEDEAR")
        main._run_velas_diarias_job()
        conn = main.get_db()
        try:
            self.assertEqual(cambios_ratio.para_el_grafico(conn, "FNMA")["escalones"], [])
            self.assertEqual(cambios_ratio.para_lotes(conn, "FNMA"), [])
            self.assertEqual([v["close"] for v in velas_diarias.serie(conn, "FNMA.BA")],
                             [v["close"] for v in velas_diarias._crudas(conn, "FNMA.BA")],
                             "no se toca nada")
            self.assertIn("precio_quieto", {f["tipo"] for f in cambios_ratio.todos(conn, "FNMA")})
        finally:
            conn.close()
        self.assertEqual(self._admin()["cambios_de_ratio"], [])

    def test_agrometal_no_se_compara_con_adecoagro(self):
        # Vos tenés Agrometal (AGRO.BA); otro usuario, Adecoagro (AGRO, Nueva
        # York). Agrometal cae 88 % un día. Comparadas, daban un «cambio de ratio
        # confirmado ×8» que el aviso le ofrecía a quien tiene Agrometal.
        dias = [d.isoformat() for d in _ruedas(hoy_art_date(), 120)]
        self.series["AGRO.BA"] = {d: (1000.0 if i < 60 else 120.0) for i, d in enumerate(dias)}
        self.series["AGRO"] = {d: 10.0 for d in dias}
        self._broker("IOL", "ARS")
        self._posicion("IOL", "AGRO", "ACCION")
        self._broker("Schwab", "USD", h=self.h_admin)
        self._posicion("Schwab", "AGRO", "STOCK", h=self.h_admin)
        main._run_velas_diarias_job()
        conn = main.get_db()
        try:
            self.assertEqual(cambios_ratio.para_lotes(conn, "AGRO"), [], "nada que ofrecerle a nadie")
            self.assertEqual(cambios_ratio.para_el_grafico(conn, "AGRO")["escalones"], [])
            self.assertIn(1000.0, {v["close"] for v in velas_diarias.serie(conn, "AGRO.BA")})
        finally:
            conn.close()
        adm = self._admin()
        self.assertEqual(adm["cambios_de_ratio"], [])
        self.assertEqual([(x["symbol"], x["date"]) for x in adm["sin_explicar"]], [("AGRO.BA", dias[60])])

    def test_el_par_de_berkshire_es_brk_guion_b(self):
        # El par sale de la cartera: BRK.B es un CEDEAR, su acción de afuera en
        # Yahoo es BRK-B. Por el nombre ("BRKB") no se encontraba.
        dias = [d.isoformat() for d in _ruedas(hoy_art_date(), 120)]
        self.series["BRKB.BA"] = {d: (40000.0 if i < 60 else 20000.0) for i, d in enumerate(dias)}
        self.series["BRK-B"] = {d: 500.0 for d in dias}
        self._broker("IOL", "ARS")
        self._posicion("IOL", "BRK.B", "CEDEAR")
        main._run_velas_diarias_job()
        conn = main.get_db()
        try:
            self.assertEqual(cambios_ratio.para_el_grafico(conn, "BRKB")["escalones"], [(dias[60], 2.0)])
            self.assertEqual({v["close"] for v in velas_diarias.serie(conn, "BRKB.BA")}, {20000.0})
        finally:
            conn.close()

    def test_admin_lo_ve_y_el_usuario_no(self):
        r = self.client.get("/api/admin/velas", headers=self.h)
        self.assertEqual(r.status_code, 403)


class EmpalmarTest(unittest.TestCase):
    """Cómo la puerta de lectura aplica lo que dice la lista."""

    def _velas(self, cierres):
        return [{"date": f"d{i:02d}", "open": c, "high": c, "low": c, "close": c, "volume": 100.0}
                for i, c in enumerate(cierres)]

    def test_escalon_lleva_lo_anterior_a_la_escala_nueva(self):
        v = velas_diarias._empalmar(self._velas([90, 90, 45, 45]), {"escalones": [("d02", 2.0)]})
        self.assertEqual([x["close"] for x in v], [45, 45, 45, 45])
        self.assertEqual(v[0]["volume"], 200.0, "el doble de CEDEARs")

    def test_dia_roto_se_saca(self):
        v = velas_diarias._empalmar(self._velas([90, 30, 90]), {"rotos": ["d01"]})
        self.assertEqual([x["date"] for x in v], ["d00", "d02"])

    def test_salto_pendiente_esconde_desde_ese_dia_y_no_reescala(self):
        v = velas_diarias._empalmar(self._velas([90, 90, 90, 45, 45]), {"pendientes": ["d03"]})
        self.assertEqual([x["close"] for x in v], [90, 90, 90])


if __name__ == "__main__":
    unittest.main()
