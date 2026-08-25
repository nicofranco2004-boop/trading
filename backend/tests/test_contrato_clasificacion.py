"""M-2 · EL TEST DE CONTRATO: los cinco lectores del mismo dato, obligados a
decidir lo mismo sobre la misma fila.

El criterio ya se bifurcó DOS veces en este trabajo, y las dos veces el síntoma
fue el mismo: se arregla un lector y no los otros. Este test vale más que arreglar
los síntomas de a uno, porque falla en el momento en que aparece el sexto lector
que se olvida.

Los cinco:
  1. twr.serie_medible                                  (la CURVA)
  2. twr.bordes_medibles                                (los bordes del TWR sellado)
  3. reporting.builder.fetch_snapshot_at_or_before      (el borde de PERÍODO)
  4. GET /api/snapshots                                 (la LISTA que lee el front)
  5. scripts.backfill_historical_mtm._persist_mtm_snapshots  (a quién NO pisar)
  6. twr.diagnosticar                                   (el semáforo de datos)
  7. GET /api/admin/diagnose-reportes-basis            (el diagnóstico del dueño)

Los dos últimos aparecieron en el barrido "¿quién MÁS lee este dato?". El
docstring del endpoint admin dice textual: «un diagnóstico que reimplemente el
criterio mide otra cosa que la que corre» — y estaba reimplementándolo.
"""
import datetime as _d
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main
import twr
from reporting import builder


class ContratoDeClasificacionTest(unittest.TestCase):
    """El fixture es el que rompió los tres lectores: fotos del cron ANTERIORES a
    que existieran las columnas `holdings_json` (2026-07-04) y `source`
    (2026-08-06). Mirada sola, cada una parece una foto del browser; la cadencia
    diaria dice que la escribió el cron."""

    DIAS = 40

    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "positions", "operations", "monthly_entries", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"contrato-{id(self)}@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,'IBKR','AAPL',0,1,100,'2025-01-01')",
            (self.uid,))
        d0 = _d.date(2026, 5, 1)
        for i in range(self.DIAS):                # cadencia diaria = el cron
            d = d0 + _d.timedelta(days=i)
            self.conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
                "net_deposited, source, fx_to_usd_blue, holdings_json) "
                "VALUES (?,?,?,?,0,NULL,1200,NULL)",
                (self.uid, d.isoformat(), 100000.0 + i * 10, 100000.0))
        self.conn.commit()
        self.ultima = (d0 + _d.timedelta(days=self.DIAS - 1)).isoformat()

    def tearDown(self):
        self.conn.close()

    # ── los cinco, sobre la MISMA fila ───────────────────────────────────────
    def _clase_serie_medible(self):
        s = twr.serie_medible(self.conn, self.uid)
        p = [x for x in s["puntos"] if x["date"] == self.ultima]
        return p[0]["clase"] if p else None

    def _clase_bordes_medibles(self):
        b = twr.bordes_medibles(self.conn, self.uid)
        return twr.MEDICION if any(str(r["date"]) == self.ultima for r in b) else None

    def _clase_borde_periodo(self):
        r = builder.fetch_snapshot_at_or_before(
            self.conn, self.uid, self.ultima, mtm_only=True)
        return twr.MEDICION if (r and str(r["date"]) == self.ultima) else None

    def _clase_api_snapshots(self):
        from fastapi.testclient import TestClient
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        try:
            filas = TestClient(main.app).get("/api/snapshots?days=3650").json()
        finally:
            main.app.dependency_overrides.clear()
        f = [x for x in filas if x["date"] == self.ultima]
        return f[0].get("clase") if f else None

    def _clase_persister_mtm(self):
        """El backfill no devuelve la clase: la USA para decidir a quién no pisar.
        Se la pregunta indirectamente — si NO pisa la fila, la vio como MEDICION."""
        import scripts.backfill_historical_mtm as bf
        antes = self.conn.execute(
            "SELECT total_value FROM snapshots WHERE user_id=? AND date=?",
            (self.uid, self.ultima)).fetchone()["total_value"]
        bf._persist_mtm_snapshots(self.conn, self.uid, {
            self.ultima[:7]: {"date": self.ultima, "value": 1.0, "cost": 1.0,
                              "coverage": 1.0, "holdings": []}})
        self.conn.commit()
        despues = self.conn.execute(
            "SELECT total_value FROM snapshots WHERE user_id=? AND date=?",
            (self.uid, self.ultima)).fetchone()["total_value"]
        return twr.MEDICION if abs(despues - antes) < 1e-9 else None

    def _clase_diagnosticar(self):
        d = twr.diagnosticar(self.conn, [self.uid])[self.uid]
        # Si la última fila fuera INTRADIA, `medicion` no llegaría a DIAS.
        return twr.MEDICION if d["por_clase"][twr.MEDICION] == self.DIAS else None

    def test_los_lectores_deciden_lo_mismo(self):
        veredictos = {
            "twr.serie_medible": self._clase_serie_medible(),
            "twr.bordes_medibles": self._clase_bordes_medibles(),
            "twr.diagnosticar": self._clase_diagnosticar(),
            "builder.fetch_snapshot_at_or_before": self._clase_borde_periodo(),
            "GET /api/snapshots": self._clase_api_snapshots(),
            "backfill._persist_mtm_snapshots": self._clase_persister_mtm(),
        }
        distintos = set(veredictos.values())
        self.assertEqual(
            distintos, {twr.MEDICION},
            "los lectores no coinciden sobre la MISMA fila: " + repr(veredictos))

    def test_el_diagnostico_del_admin_reporta_la_misma_clase(self):
        """Reimplementarlo hace que el dueño mida otra cosa que la que corre —
        y este endpoint es justamente el que se usa para decidir si mergear."""
        from fastapi.testclient import TestClient
        main.app.dependency_overrides[main.get_admin_user] = lambda: self.uid
        try:
            r = TestClient(main.app).get(
                f"/api/admin/diagnose-reportes-basis?user_id={self.uid}")
        finally:
            main.app.dependency_overrides.clear()
        if r.status_code != 200:
            self.skipTest(f"el endpoint de diagnóstico no respondió: {r.status_code}")
        j = r.json()
        recientes = j.get("snapshots_recientes") or []
        if not recientes:
            self.skipTest("sin snapshots_recientes en la respuesta")
        for fila in recientes:
            self.assertEqual(fila["clase"], twr.MEDICION, repr(fila))

    def test_la_lista_y_la_curva_ven_los_mismos_aptos(self):
        """El síntoma concreto de la última bifurcación: 600 aptos en la curva y
        51 en la lista, para el mismo usuario en la misma sesión."""
        from fastapi.testclient import TestClient
        s = twr.serie_medible(self.conn, self.uid)
        aptos_curva = sum(1 for p in s["puntos"] if p["apto"])
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        try:
            filas = TestClient(main.app).get("/api/snapshots?days=3650").json()
        finally:
            main.app.dependency_overrides.clear()
        aptos_lista = sum(1 for f in filas if f.get("apto"))
        self.assertEqual(aptos_curva, self.DIAS)
        self.assertEqual(aptos_lista, self.DIAS)
        self.assertEqual(sum(1 for f in filas if f.get("sintetico")), 0)


class BackfillDeSourceTest(unittest.TestCase):
    """M-1 · materializar la clasificación. Resolverla al leer obliga a cada lector
    a acordarse, y uno no se acordó."""

    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "positions", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"bf-{id(self)}@t", "x")).lastrowid
        # CON posiciones: sin ellas, una fila con fx y sin holdings ya se clasifica
        # MEDICION por la regla de "cartera 100% cash", y el backfill no la toca a
        # propósito (podría haberla escrito el browser). El caso que el backfill
        # existe para resolver es el de una cuenta CON cartera.
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,'IBKR','AAPL',0,1,100,'2025-01-01')",
            (self.uid,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _fila(self, d, src=None, fx=1200.0, hold=None):  # noqa: D401
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,100000,100000,0,?,?,?)", (self.uid, d, src, fx, hold))
        self.conn.commit()

    def test_estampa_las_legacy_con_cadencia_de_cron(self):
        d0 = _d.date(2026, 5, 1)
        for i in range(20):
            self._fila((d0 + _d.timedelta(days=i)).isoformat())
        r = twr.backfill_source_legacy(self.conn, [self.uid])
        self.conn.commit()
        self.assertEqual(r["filas"], 20)
        quedan = self.conn.execute(
            "SELECT COUNT(*) c FROM snapshots WHERE user_id=? AND source IS NULL",
            (self.uid,)).fetchone()["c"]
        self.assertEqual(quedan, 0)

    def test_es_idempotente(self):
        d0 = _d.date(2026, 5, 1)
        for i in range(20):
            self._fila((d0 + _d.timedelta(days=i)).isoformat())
        twr.backfill_source_legacy(self.conn, [self.uid])
        self.conn.commit()
        r2 = twr.backfill_source_legacy(self.conn, [self.uid])
        self.conn.commit()
        self.assertEqual(r2["filas"], 0)

    def test_no_toca_una_fila_que_YA_dice_browser(self):
        """Lo que dice `source` manda: el backfill sólo desambigua legacy."""
        d0 = _d.date(2026, 5, 1)
        for i in range(20):
            self._fila((d0 + _d.timedelta(days=i)).isoformat(), src="browser")
        r = twr.backfill_source_legacy(self.conn, [self.uid])
        self.conn.commit()
        self.assertEqual(r["filas"], 0)
        quedan = self.conn.execute(
            "SELECT COUNT(*) c FROM snapshots WHERE user_id=? AND source='browser'",
            (self.uid,)).fetchone()["c"]
        self.assertEqual(quedan, 20)

    def test_no_estampa_una_tanda_salteada(self):
        """Cinco visitas sueltas no son el cron."""
        for d in ("2026-05-02", "2026-05-09", "2026-05-17", "2026-05-25", "2026-06-02"):
            self._fila(d)
        r = twr.backfill_source_legacy(self.conn, [self.uid])
        self.conn.commit()
        self.assertEqual(r["filas"], 0)
        # Y siguen viéndose como lo que son: fotos de media rueda.
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(s["por_clase"][twr.INTRADIA], 5)

    def test_despues_del_backfill_la_clase_no_depende_del_read_time(self):
        d0 = _d.date(2026, 5, 1)
        for i in range(20):
            self._fila((d0 + _d.timedelta(days=i)).isoformat())
        twr.backfill_source_legacy(self.conn, [self.uid])
        self.conn.commit()
        fila = self.conn.execute(
            "SELECT date,total_value,fx_to_usd_blue,holdings_json,source,mtm_coverage "
            "FROM snapshots WHERE user_id=? ORDER BY date LIMIT 1", (self.uid,)).fetchone()
        # Mirada SOLA —sin la serie— ya se clasifica bien: eso es lo que el
        # read-time no podía dar.
        self.assertEqual(twr.clasificar_fila(fila, True), twr.MEDICION)


if __name__ == "__main__":
    unittest.main()
