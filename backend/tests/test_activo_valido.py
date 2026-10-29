"""Una sola definición de «activo válido» para tesis, dibujos y alertas técnicas
(auditoría E2, E3, E4, E7 y E8 del 29/10).

El «activo» de una tesis era texto libre, el de un dibujo o una alerta técnica
sólo tenía que PARECER un ticker. Cada texto distinto era una fila nueva: 300
tesis con recordatorio → 302 mails al día siguiente desde una cuenta gratis;
400 gráficos dibujados → 14 MB; 89 alertas con símbolos inventados → 89
pedidos a Yahoo esa noche, adelante de los de verdad.

La regla es UNA (`velas_diarias.se_puede_pedir`, la misma que decide qué se
baja a pedido para la ficha): un activo que la app conoce (sus listas, BYMA)
o que la persona tiene, operó o sigue. Y topes por persona: tesis nuevas por
día, recordatorios activos, gráficos con dibujos.

Todo por HTTP, con dos personas en plan Free (Ana y Beto); el recordatorio
llega por el cron de siempre (`main._evaluar_alertas_job`).

Corre con: cd backend && python3 -m pytest tests/test_activo_valido.py
"""
import os
import sys
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timedelta
from unittest import mock
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from fastapi.testclient import TestClient

import main
import tesis
from ai import trade_tickers
from fechas import hoy_art_date

CONOCIDOS = sorted(trade_tickers.US_TICKERS)
INVENTADOS = ["cualquier cosa / no es un activo ?#", 'X" onmouseover="alert(1)', "ZZZZ9", "QX0001"]
FONDO = "FCI:FONDO RENTA/A"


class Base(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("tesis", "alerts", "alert_events", "dibujos_grafico", "watchlist",
                      "positions", "brokers", "operations"):
                conn.execute(f"DELETE FROM {t}")
            self.uids = []
            for quien in ("ana", "beto"):
                cur = conn.execute(
                    "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                    "VALUES (?, 'x', 1, 1, 'free')", (f"valido-{quien}-{tag}@rendi.test",))
                self.uids.append(cur.lastrowid)
            conn.commit()
        self.ana = {"Authorization": f"Bearer {main.create_token(self.uids[0])}"}
        self.beto = {"Authorization": f"Bearer {main.create_token(self.uids[1])}"}
        self.hoy = hoy_art_date()
        self.yahoo = mock.MagicMock(return_value=None)
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("alerts_engine.price_for_alert", self.yahoo)]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _tesis(self, asset, h=None, texto="Porque sí", esperado=200):
        r = self.client.put("/api/tesis", json={"asset": asset, "texto": texto}, headers=h or self.ana)
        self.assertEqual(r.status_code, esperado, f"{asset}: {r.text}")
        return r.json().get("id")

    def _fondo_en_cartera(self):
        r = self.client.post("/api/brokers", json={"name": "IOL", "currency": "ARS"}, headers=self.ana)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/positions", json={"broker": "IOL", "asset": FONDO, "quantity": 10,
                                                     "buy_price": 100, "asset_type": "FCI"}, headers=self.ana)
        self.assertIn(r.status_code, (200, 201), r.text)


class TesisTest(Base):

    def test_el_activo_tiene_que_ser_uno_que_la_app_conoce(self):
        for a in INVENTADOS:
            self._tesis(a, esperado=400)
        self._tesis("AAPL")                          # de las listas de la app
        self._fondo_en_cartera()
        self._tesis(FONDO)                           # un fondo de SU cartera (no tiene forma de ticker)
        self._tesis(FONDO, self.beto, esperado=400)  # …que no es de Beto
        r = self.client.post("/api/watchlist", json={"symbol": "RAROX"}, headers=self.ana)
        self.assertEqual(r.status_code, 200, r.text)
        self._tesis("RAROX")                         # lo que sigue
        self._tesis("RAROX", self.beto, esperado=400)
        with main.db_abierta() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tesis").fetchone()[0], 3)

    def test_tope_de_tesis_nuevas_por_dia(self):
        tope = tesis.TESIS_NUEVAS_POR_DIA
        for a in CONOCIDOS[:tope]:
            self._tesis(a)
        r = self.client.put("/api/tesis", json={"asset": CONOCIDOS[tope], "texto": "una más"}, headers=self.ana)
        self.assertEqual(r.status_code, 429, r.text)
        self._tesis(CONOCIDOS[0], texto="corregida")      # corregir la de hoy no es una nueva
        self._tesis(CONOCIDOS[tope], self.beto)            # Beto, normal
        manana = self.hoy + timedelta(days=1)
        with mock.patch("tesis.hoy_art_date", lambda: manana):
            self._tesis(CONOCIDOS[tope])                  # al otro día, sí

    def test_tope_de_recordatorios_activos(self):
        tope = tesis.RECORDATORIOS_MAX
        ids = []
        for k in range(tope + 1):
            dia = self.hoy + timedelta(days=k // tesis.TESIS_NUEVAS_POR_DIA)
            with mock.patch("tesis.hoy_art_date", lambda d=dia: d):
                ids.append(self._tesis(CONOCIDOS[k]))
        for tid in ids[:tope]:
            r = self.client.put(f"/api/tesis/{tid}/recordatorio", json={"tipo": "3m"}, headers=self.ana)
            self.assertEqual(r.status_code, 200, r.text)
        r = self.client.put(f"/api/tesis/{ids[tope]}/recordatorio", json={"tipo": "3m"}, headers=self.ana)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn(str(tope), r.json()["detail"])
        # Cambiar la fecha de uno que ya tenía no suma: sigue andando.
        r = self.client.put(f"/api/tesis/{ids[0]}/recordatorio", json={"tipo": "fecha",
                            "fecha": (self.hoy + timedelta(days=5)).isoformat()}, headers=self.ana)
        self.assertEqual(r.status_code, 200, r.text)
        # Sacar uno libera el lugar.
        self.assertEqual(self.client.delete(f"/api/tesis/{ids[1]}/recordatorio", headers=self.ana).status_code, 200)
        r = self.client.put(f"/api/tesis/{ids[tope]}/recordatorio", json={"tipo": "3m"}, headers=self.ana)
        self.assertEqual(r.status_code, 200, r.text)

    def test_diez_a_la_vez_no_pasan_el_tope_del_dia(self):
        tope = tesis.TESIS_NUEVAS_POR_DIA
        for a in CONOCIDOS[:tope - 2]:
            self._tesis(a)
        codigos = []
        barrera = threading.Barrier(10)

        def una(a):
            barrera.wait(10)
            codigos.append(self.client.put("/api/tesis", json={"asset": a, "texto": "x"},
                                           headers=self.ana).status_code)
        hilos = [threading.Thread(target=una, args=(a,)) for a in CONOCIDOS[tope:tope + 10]]
        for t in hilos:
            t.start()
        for t in hilos:
            t.join(30)
        with main.db_abierta() as conn:
            n = conn.execute("SELECT COUNT(*) FROM tesis WHERE user_id=?", (self.uids[0],)).fetchone()[0]
        self.assertEqual(n, tope, f"códigos {sorted(codigos)}")
        self.assertEqual(sorted(codigos), [200, 200] + [429] * 8)

    def test_el_link_del_mail_y_de_la_notificacion_va_codificado(self):
        self._fondo_en_cartera()
        tid = self._tesis(FONDO)
        r = self.client.put(f"/api/tesis/{tid}/recordatorio", json={"tipo": "3m"}, headers=self.ana)
        self.assertEqual(r.status_code, 200, r.text)
        with main.db_abierta() as conn:
            conn.execute("UPDATE tesis SET recordar_el=? WHERE id=?", (self.hoy.isoformat(), tid))
            conn.commit()
        mails, pushes = [], []
        with mock.patch("billing.emails.send_alert_email", lambda **kw: mails.append(kw) or True), \
             mock.patch("main._send_push_to_user", lambda uid, p: pushes.append((uid, p)) or 1), \
             mock.patch("alerts_engine.HORA_RECORDATORIO", 0):
            main._evaluar_alertas_job()
        esperado = "/activo/" + quote(FONDO, safe="")
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails[0]["cta_path"], esperado)
        self.assertEqual(pushes[0][1]["url"], esperado)

    def test_balance_de_un_inventado_no_le_pregunta_a_yahoo(self):
        with mock.patch("main._eventos_al_dia") as eventos:
            for a in INVENTADOS:
                tid = self._tesis(a, esperado=400)
                self.assertIsNone(tid)
        eventos.assert_not_called()


class DibujosTest(Base):

    DIBUJO = [{"id": "h1", "tipo": "horizontal", "precio": 100}]

    def _dibujar(self, asset, h=None, dibujos=None):
        return self.client.put(f"/api/tecnico/{asset}/dibujos",
                               json={"dibujos": self.DIBUJO if dibujos is None else dibujos},
                               headers=h or self.ana)

    def test_solo_activos_que_la_app_conoce(self):
        for a in ("ZZZZZZZZZZZZ.ZZZZ", "QX0001"):
            r = self._dibujar(a)
            self.assertEqual(r.status_code, 400, f"{a}: {r.text}")
        self.assertEqual(self._dibujar("AAPL").status_code, 200)
        with main.db_abierta() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM dibujos_grafico").fetchone()[0], 1)

    def test_tope_de_graficos_por_persona(self):
        with mock.patch("main.GRAFICOS_CON_DIBUJOS_MAX", 3, create=True):
            for a in CONOCIDOS[:3]:
                self.assertEqual(self._dibujar(a).status_code, 200)
            r = self._dibujar(CONOCIDOS[3])
            self.assertEqual(r.status_code, 400, r.text)
            self.assertIn("3", r.json()["detail"])
            self.assertEqual(self._dibujar(CONOCIDOS[0], dibujos=self.DIBUJO * 1 + [
                {"id": "h2", "tipo": "horizontal", "precio": 120}]).status_code, 200)   # cambiar uno, sí
            self.assertEqual(self._dibujar(CONOCIDOS[3], self.beto).status_code, 200)  # Beto, normal
            self.assertEqual(self._dibujar(CONOCIDOS[1], dibujos=[]).status_code, 200)  # borrar libera
            self.assertEqual(self._dibujar(CONOCIDOS[3]).status_code, 200)


class AlertaTecnicaTest(Base):

    def test_el_alta_no_acepta_inventados_ni_va_a_yahoo_por_ellos(self):
        for a in ("QX0001", "ZZZZ9"):
            r = self.client.post("/api/alerts", json={"kind": "tecnica", "symbol": a, "senal": "media200",
                                                      "direction": "either"}, headers=self.ana)
            self.assertEqual(r.status_code, 400, f"{a}: {r.text}")
        self.yahoo.assert_not_called()
        r = self.client.post("/api/alerts", json={"kind": "tecnica", "symbol": "AAPL", "senal": "media200",
                                                  "direction": "either"}, headers=self.ana)
        self.assertEqual(r.status_code, 200, r.text)


if __name__ == "__main__":
    unittest.main()
