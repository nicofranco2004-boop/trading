"""Lo que entra a la descarga de la noche tiene tope por persona, por todas las
puertas (auditoría E4, 29/10).

La noche le pide a Yahoo lo que alguien tiene, sigue, vigila con una alerta
técnica u operó (`velas_diarias._seguimiento`). El 22/10 se le puso tope de 100
a la watchlist; las alertas técnicas fueron una puerta NUEVA a la misma lista,
sin tope en Plus/Pro y con cualquier símbolo con forma de ticker: una cuenta
Pro metió 89 inventados, y lo que nunca se intentó va primero en la fila.

Lo que se prueba, con `velas_diarias.simbolos_a_seguir` (la lista que usa la
corrida real) y lo cargado por HTTP:
  · lo de las listas de la app o BYMA entra siempre, sea de quien sea; de lo
    RARO (lo demás, se baje bien o no), cada persona —con los clientes que
    creó, si es asesor— aporta hasta `RAROS_POR_PERSONA`: primero lo que se
    baja bien, después lo nunca intentado, y lo que falla rotando; a otra
    persona no le cambia nada (re-test E4, rondas 2 y 3);
  · una alerta técnica de un activo que no es válido (una vieja, de antes de
    que el alta lo pidiera) no entra.

Corre con: cd backend && python3 -m pytest tests/test_noche_tope.py
"""
import os
import sys
import tempfile
import unittest
import uuid
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
import velas_diarias


class NocheTopeTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("alerts", "watchlist", "positions", "brokers", "operations"):
                conn.execute(f"DELETE FROM {t}")
            self.uids = []
            for quien in ("ana", "beto"):
                cur = conn.execute(
                    "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                    "VALUES (?, 'x', 1, 1, 'pro')", (f"noche-{quien}-{tag}@rendi.test",))
                self.uids.append(cur.lastrowid)
            conn.commit()
        self.ana = {"Authorization": f"Bearer {main.create_token(self.uids[0])}"}
        self.beto = {"Authorization": f"Bearer {main.create_token(self.uids[1])}"}
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   mock.patch("velas_diarias._cedears_de_byma", lambda: frozenset()),
                   mock.patch("alerts_engine.price_for_alert", lambda *a, **k: 100.0),
                   mock.patch("pricing.yahoo._historia", lambda *a, **k: None)]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _ok(self, ruta, cuerpo, h):
        r = self.client.post(ruta, json=cuerpo, headers=h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _noche(self):
        with main.db_abierta() as conn:
            return set(velas_diarias.simbolos_a_seguir(conn))

    def test_lo_desconocido_tiene_tope_y_lo_conocido_entra_siempre(self):
        self._ok("/api/brokers", {"name": "Schwab", "currency": "USD"}, self.ana)
        self._ok("/api/positions", {"broker": "Schwab", "asset": "AAPL", "quantity": 1,
                                    "buy_price": 100, "asset_type": "STOCK"}, self.ana)
        for s in ("QX0001", "QX0002", "QX0003", "MSFT"):
            self._ok("/api/watchlist", {"symbol": s}, self.ana)
        self._ok("/api/alerts", {"kind": "tecnica", "symbol": "KO", "senal": "media200",
                                 "direction": "either"}, self.ana)
        self._ok("/api/watchlist", {"symbol": "QX0009"}, self.beto)
        with mock.patch("velas_diarias.RAROS_POR_PERSONA", 2):
            noche = self._noche()
        self.assertTrue({"QX0001", "QX0002"} <= noche, noche)
        self.assertNotIn("QX0003", noche, "el tercer desconocido de Ana queda afuera")
        self.assertTrue({"AAPL", "MSFT", "KO"} <= noche, "lo conocido entra aunque el tope esté lleno")
        self.assertIn("QX0009", noche, "a Beto no le cambia nada")
        # Sin el tope chico, entra todo.
        self.assertIn("QX0003", self._noche())

    def test_una_alerta_tecnica_de_un_activo_invalido_no_entra(self):
        with main.db_abierta() as conn:   # una vieja, de antes de que el alta lo pidiera
            conn.execute("INSERT INTO alerts (user_id, kind, symbol, scope, direction, currency, "
                         "channel, repeat, cooldown_min, armed, active, senal, accion_local) "
                         "VALUES (?, 'tecnica', 'QX0001', 'ticker', 'either', 'USD', 'both', "
                         "'once', 0, 1, 1, 'media200', 0)", (self.uids[1],))
            conn.commit()
        self._ok("/api/alerts", {"kind": "tecnica", "symbol": "KO", "senal": "media200",
                                 "direction": "either"}, self.beto)
        noche = self._noche()
        self.assertNotIn("QX0001", noche)
        self.assertIn("KO", noche)

    def test_lo_que_vendio_entra_y_la_consulta_corre_en_postgres(self):
        """La consulta de las operaciones tenía `DISTINCT … ORDER BY entry_date`,
        que Postgres rechaza: la noche entera se caía (re-test E4). Esta prueba
        corre igual en los dos motores (con DATABASE_URL, en Postgres) y pasa
        por esa consulta con filas de verdad: dos ventas del mismo activo."""
        from fechas import hoy_art_date
        hoy = hoy_art_date().isoformat()
        with main.db_abierta() as conn:
            for dia in (hoy, "2026-01-02"):
                conn.execute("INSERT INTO operations (user_id, date, broker, asset, currency, entry_date, "
                             "op_type, quantity, entry_price, exit_price) "
                             "VALUES (?, ?, 'Schwab', 'NFLX', 'USD', ?, 'Venta', 1, 10, 12)",
                             (self.uids[1], hoy, dia))
            conn.commit()
        self.assertIn("NFLX", self._noche())

    def test_la_noche_va_por_turnos_y_lo_real_no_queda_al_final(self):
        """Re-test E4: 1.300 inventados nunca intentados iban primero y los 7
        reales en la última tanda; si la noche se cortaba por tiempo, lo de
        verdad no se actualizaba. Por turnos, cada persona avanza al mismo ritmo."""
        with main.db_abierta() as conn:
            for i in range(120):        # Ana sigue 120 inventados que nadie intentó nunca
                conn.execute("INSERT INTO watchlist (user_id, symbol) VALUES (?, ?)",
                             (self.uids[0], f"QX{i:04d}"))
            for s in ("KO", "PEP"):     # Beto sigue dos de verdad, que ya tienen historia
                conn.execute("INSERT INTO watchlist (user_id, symbol) VALUES (?, ?)", (self.uids[1], s))
                conn.execute("INSERT INTO velas_estado (symbol, ultima_corrida, ultima_completa, ok, filas) "
                             "VALUES (?, datetime('now'), datetime('now'), 1, 700)", (s,))
            conn.commit()
        pedidos = []

        def bajar(t, periodo):
            pedidos.append(t)
            return None
        # La corrida de la noche entera, de a un ticker por tanda para ver el orden.
        # El tope de desconocidos, más alto que los 120: acá se mira el orden.
        with main.db_abierta() as conn, mock.patch("velas_diarias._bajar", bajar), \
                mock.patch("velas_diarias.TANDA", 1), mock.patch("velas_diarias.RAROS_POR_PERSONA", 200):
            velas_diarias.correr(conn)
        self.assertLess(max(pedidos.index("KO"), pedidos.index("PEP")), 6, pedidos[:8])
        self.assertEqual(len(set(pedidos)), 123)   # todo se pide igual: sólo cambia el orden

    def _asesor_con_clientes(self, n, inventados_por_cliente, reales=()):
        """Un asesor y `n` clientes creados por él (`managed_by`), cada uno con
        símbolos inventados (y `reales`) en su lista de seguimiento."""
        with main.db_abierta() as conn:
            ase = conn.execute("INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                               "VALUES (?, 'x', 1, 1, 'advisor')",
                               (f"noche-ase-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
            for c in range(n):
                cli = conn.execute("INSERT INTO users (email, password_hash, approved, email_verified, tier, "
                                   "managed_by) VALUES (?, 'x', 0, 0, 'free', ?)",
                                   (f"noche-cli-{uuid.uuid4().hex[:8]}@rendi.test", ase)).lastrowid
                for i in range(inventados_por_cliente):
                    conn.execute("INSERT INTO watchlist (user_id, symbol) VALUES (?, ?)",
                                 (cli, f"QZ{c:03d}{i:03d}"))
                for r in reales[c::n]:       # los reales, repartidos entre los clientes
                    conn.execute("INSERT INTO watchlist (user_id, symbol) VALUES (?, ?)", (cli, r))
            conn.commit()
        return ase

    def test_los_clientes_que_creo_un_asesor_suman_a_su_tope_sin_dejar_afuera_lo_real(self):
        """Re-test E4, ronda 2: cada cliente creado era otra persona con su
        propio tope. Ahora lo desconocido de todos sus clientes suma al tope
        del asesor; lo real de sus clientes entra entero."""
        from ai import trade_tickers
        reales = sorted(trade_tickers.US_TICKERS)[:40]
        self._asesor_con_clientes(5, 3, reales)               # 15 inventados y 40 reales entre 5 clientes
        with mock.patch("velas_diarias.RAROS_POR_PERSONA", 4):
            noche = self._noche()
        self.assertEqual(len([t for t in noche if t.startswith("QZ")]), 4, sorted(noche))
        self.assertTrue(set(reales) <= noche, "ningún activo real de un cliente queda afuera")

    def test_lo_conocido_va_antes_que_lo_desconocido(self):
        """Re-test E4, ronda 2: un asesor con 100 clientes dejó 36 de 189 reales
        sin actualizar, porque lo nunca intentado iba primero. Ahora lo de las
        listas de la app (aunque nunca se haya bajado) y lo que ya tiene velas
        va antes que cualquier desconocido."""
        self._asesor_con_clientes(30, 4)                      # 120 inventados nunca intentados
        with main.db_abierta() as conn:
            for s in ("KO", "PEP", "AAPL"):                    # de las listas de la app, nunca bajados
                conn.execute("INSERT INTO watchlist (user_id, symbol) VALUES (?, ?)", (self.uids[1], s))
            conn.commit()
        pedidos = []

        def bajar(t, periodo):
            pedidos.append(t)
            return None
        with main.db_abierta() as conn, mock.patch("velas_diarias._bajar", bajar), \
                mock.patch("velas_diarias.TANDA", 1):
            velas_diarias.correr(conn)
        reales = [pedidos.index(s) for s in ("KO", "PEP", "AAPL")]
        primer_inventado = min(i for i, t in enumerate(pedidos) if t.startswith("QZ"))
        self.assertLess(max(reales), primer_inventado, pedidos[:8])

    def _estado(self, simbolo, ok, ultima_corrida, uid=None, en_watchlist=True):
        with main.db_abierta() as conn:
            if en_watchlist:
                conn.execute("INSERT INTO watchlist (user_id, symbol) VALUES (?, ?)",
                             (uid or self.uids[0], simbolo))
            conn.execute("INSERT INTO velas_estado (symbol, ultima_corrida, ultima_completa, ok, filas) "
                         "VALUES (?, ?, ?, ?, ?)",
                         (simbolo, ultima_corrida, ultima_corrida if ok else None, 1 if ok else 0, 700 if ok else 0))
            conn.commit()

    def test_los_codigos_que_fallan_no_tapan_a_los_raros_de_verdad(self):
        """Re-test E4, ronda 3: con más códigos que fallan que lugares, el cupo
        se llenaba todas las noches con los mismos, y los raros reales nunca
        se bajaban (0 de 30 en 3 noches). Ahora lo nunca intentado va antes
        que lo que falla, y lo que falla rota: entra el que hace más que no se
        prueba."""
        for i in range(5):                                  # 5 códigos que fallan, probados a distintas horas
            self._estado(f"QF{i:04d}", ok=False, ultima_corrida=f"2026-10-2{i} 03:00:00")
        for s in ("QR0001", "QR0002", "QR0003"):             # 3 raros reales recién sumados
            self._ok("/api/watchlist", {"symbol": s}, self.ana)
        with mock.patch("velas_diarias.RAROS_POR_PERSONA", 4):
            noche = self._noche()
        self.assertTrue({"QR0001", "QR0002", "QR0003"} <= noche, sorted(noche))
        fallados = sorted(t for t in noche if t.startswith("QF"))
        self.assertEqual(fallados, ["QF0000"], "de los que fallan entra el que hace más que no se prueba")

    def test_lo_raro_que_ya_se_baja_tambien_cuenta_y_no_tapa_lo_nuevo_de_otros(self):
        """Re-test E4, ronda 3: lo raro que se bajaba bien pasaba a «conocido»
        sin tope y se acumulaba (7.400 de una cuenta: 0 de 40 nuevos de los
        demás). Ahora cuenta en el cupo, y en la fila lo raro va por turnos."""
        for i in range(6):                                  # Ana: 6 raros que ya se bajan bien
            self._estado(f"QK{i:04d}", ok=True, ultima_corrida="2026-10-01 03:00:00")
        self._ok("/api/watchlist", {"symbol": "QN0001"}, self.beto)   # Beto: un raro nuevo
        with mock.patch("velas_diarias.RAROS_POR_PERSONA", 3):
            noche = self._noche()
        self.assertEqual(len([t for t in noche if t.startswith("QK")]), 3, sorted(noche))
        pedidos = []

        def bajar(t, periodo):
            pedidos.append(t)
            return None
        with main.db_abierta() as conn, mock.patch("velas_diarias._bajar", bajar), \
                mock.patch("velas_diarias.TANDA", 1), mock.patch("velas_diarias.RAROS_POR_PERSONA", 100):
            velas_diarias.correr(conn)
        self.assertLess(pedidos.index("QN0001"), 4, pedidos[:8])


if __name__ == "__main__":
    unittest.main()
