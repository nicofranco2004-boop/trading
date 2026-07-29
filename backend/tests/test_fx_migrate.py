"""Migración FX v1→v2 por cuenta: el deploy no cambia números, el migrador sí — las
dos patas juntas.

Reproduce el escenario que la review midió y que frenó el deploy anterior:
usuario 2021, depósito 1.000.000 ARS (MEP 155), venta con +20.000 ARS (MEP 190),
todo importado "hoy" con el dólar vivo en 1450.

  · estado v1:               pnl 13,79 / depósito 689,66  → 2,00% (error 1,23×)
  · una pata sola (el bug):  pnl 105,26 / depósito 689,66 → 15,3% (error 9,4×)
  · migrado (las dos patas): pnl 105,26 / depósito 6.451,61 → 1,63% ✅

Lo que fijan estos tests:
  1. una cuenta v1 que pasa por el rebuild NO cambia de números (el deploy es inocuo)
  2. el migrador mueve las dos patas y el ratio queda el real
  3. el dry-run no toca la base real
  4. cuentas nuevas nacen v2; cuentas con historia quedan v1
  5. el migrador es idempotente (segunda corrida = no-op)
"""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False); TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main
import fx as fxmod
from importing import pipeline as pl
from importing import persister as ps
from importing import rebuild as rb
from importing import fx_migrate as fxm

TC_VIVO = 1450.0
MEP_DEP = 155.0     # el MEP del día del depósito
MEP_VTA = 190.0     # el MEP del día de la venta

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


def _helpers():
    h = main._ImportHelpers()
    for a in ("_adjust_broker_cash", "_adjust_cash", "_update_monthly_pnl_realized",
              "_update_monthly_flow", "_repair_monthly_chain", "_ensure_usd_sibling",
              "_recalc_pnl_realized_from_ops"):
        setattr(h, a, getattr(main, a))
    return h


class FxMigrateTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "config", "brokers", "users", "fx_rates_daily"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES (?,?,1)",
            ("fxmig@test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)",
                          (self.uid, "IOL", "ARS"))
        self.conn.execute(
            "INSERT OR REPLACE INTO config (user_id,key,value) VALUES (?,?,?)",
            (self.uid, "tc_blue", str(TC_VIVO)))
        for d, m in [("2021-01-15", MEP_DEP), ("2021-06-15", MEP_VTA)]:
            self.conn.execute(
                "INSERT OR REPLACE INTO fx_rates_daily (date,blue_venta,mep_venta,source) "
                "VALUES (?,?,?,?)", (d, m - 10, m, "test"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _importar_historia_v1(self):
        """Simula la cuenta vieja: importada cuando el motor usaba el dólar vivo.
        La marcamos v1 EXPLÍCITO antes de importar (en prod, todas las cuentas con
        historia quedan v1 por el default del grandfathering)."""
        fxmod.set_fx_version(self.conn, self.uid, fxmod.FX_V1)
        self.conn.commit()
        csv = (HDR +
               "2021-01-15,DEPOSITO,IOL,,,,1000000,,,0,ARS,\n" +
               "2021-01-15,COMPRA,IOL,GGAL,100,1000,100000,,,0,ARS,\n" +
               "2021-06-15,VENTA,IOL,GGAL,100,1200,120000,,,0,ARS,\n").encode()
        with self.conn:
            payload = pl.run_preview(self.conn, uid=self.uid, file_bytes=csv,
                                     file_name="h.csv", broker_hint="IOL",
                                     parser_format="rendi_generic")
            sid = payload["session_id"]
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            self.conn.execute("UPDATE import_batches SET status='confirmed', "
                              "confirmed_at=datetime('now') WHERE id=?", (sid,))
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=TC_VIVO)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        return sid

    def _estado(self):
        pnl = self.conn.execute(
            "SELECT ROUND(COALESCE(SUM(pnl_usd),0),2) s FROM operations "
            "WHERE user_id=? AND op_type='Venta'", (self.uid,)).fetchone()["s"]
        dep = self.conn.execute(
            "SELECT ROUND(COALESCE(SUM(deposits),0),2) d FROM monthly_entries "
            "WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()["d"]
        return pnl, dep

    # ── 1. El deploy es inocuo para una cuenta v1 ─────────────────────────
    def test_v1_rebuild_no_cambia_numeros(self):
        """El escenario que FRENÓ el deploy anterior: un rebuild posterior (import
        nuevo, foto, backfill) NO debe re-derivar las ventas de una cuenta v1."""
        sid = self._importar_historia_v1()
        pnl0, dep0 = self._estado()
        self.assertAlmostEqual(pnl0, round(20000 / TC_VIVO, 2), places=2)   # 13,79
        self.assertAlmostEqual(dep0, round(1000000 / TC_VIVO, 2), places=2) # 689,66

        # Se dispara el rebuild de nuevo (como haría cualquier import posterior)…
        with self.conn:
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=TC_VIVO)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        pnl1, dep1 = self._estado()
        # …y NADA se movió. Sin el gate, pnl saltaba a 105,26 con dep en 689,66:
        # una pata sola, error 9×.
        self.assertEqual((pnl0, dep0), (pnl1, dep1))

    # ── 2. El migrador mueve las dos patas juntas ─────────────────────────
    def test_migracion_mueve_las_dos_patas(self):
        self._importar_historia_v1()
        with self.conn:
            out = fxm.migrate_user_fx(
                self.conn, self.uid, helpers=None,
                recalc=main._recalc_pnl_realized_from_ops,
                backfill_snapshots=ps._backfill_snapshots_from_monthly,
                recompute_netdep=main._recompute_snapshots_netdep_for_user)
        self.assertTrue(out["ok"], out)

        pnl, dep = self._estado()
        self.assertAlmostEqual(pnl, round(20000 / MEP_VTA, 2), places=1)     # 105,26
        self.assertAlmostEqual(dep, round(1000000 / MEP_DEP, 2), places=1)   # 6.451,61
        # El ratio queda el REAL (1,63%), no el 15,3% de la pata suelta.
        self.assertAlmostEqual(pnl / dep * 100, 1.63, delta=0.05)
        self.assertEqual(fxmod.fx_version(self.conn, self.uid), fxmod.FX_V2)
        # El stamp de la venta ahora es el MEP de su fecha.
        fx = self.conn.execute(
            "SELECT fx_to_usd FROM operations WHERE user_id=? AND op_type='Venta'",
            (self.uid,)).fetchone()["fx_to_usd"]
        self.assertAlmostEqual(fx, MEP_VTA, places=2)

    def test_migracion_es_idempotente(self):
        self._importar_historia_v1()
        with self.conn:
            fxm.migrate_user_fx(self.conn, self.uid, helpers=None,
                                recalc=main._recalc_pnl_realized_from_ops,
                                backfill_snapshots=ps._backfill_snapshots_from_monthly,
                                recompute_netdep=main._recompute_snapshots_netdep_for_user)
        e1 = self._estado()
        with self.conn:
            out2 = fxm.migrate_user_fx(self.conn, self.uid, helpers=None,
                                       recalc=main._recalc_pnl_realized_from_ops,
                                       backfill_snapshots=ps._backfill_snapshots_from_monthly,
                                       recompute_netdep=main._recompute_snapshots_netdep_for_user)
        self.assertFalse(out2["ok"])           # "ya está en v2"
        self.assertEqual(self._estado(), e1)   # y nada se movió

    # ── 3. El dry-run del endpoint no toca la base real ───────────────────
    def test_dry_run_no_toca_la_base(self):
        self._importar_historia_v1()
        antes = self._estado()
        out = main.admin_fx_migrate_user(user_id=self.uid, apply=False, uid=self.uid)
        self.assertFalse(out["applied"])
        self.assertTrue(out["ok"], out)
        # El dry-run REPORTA el después correcto…
        self.assertAlmostEqual(out["despues"]["pnl_ventas_usd"],
                               round(20000 / MEP_VTA, 2), places=1)
        # …pero la base real sigue intacta y la cuenta sigue v1.
        self.assertEqual(self._estado(), antes)
        self.assertEqual(fxmod.fx_version(self.conn, self.uid), fxmod.FX_V1)

    def test_apply_por_endpoint(self):
        self._importar_historia_v1()
        out = main.admin_fx_migrate_user(user_id=self.uid, apply=True, uid=self.uid)
        self.assertTrue(out["applied"])
        pnl, dep = self._estado()
        self.assertAlmostEqual(pnl / dep * 100, 1.63, delta=0.05)

    # ── 4. Defaults del versionado ────────────────────────────────────────
    def test_cuenta_con_historia_queda_v1(self):
        self.conn.execute(
            "INSERT INTO operations (user_id,date,broker,asset,op_type,pnl_usd) "
            "VALUES (?,?,?,?,?,?)", (self.uid, "2024-01-01", "IOL", "GGAL", "Venta", 10))
        self.conn.commit()
        self.assertEqual(fxmod.fx_version(self.conn, self.uid), fxmod.FX_V1)

    def test_cuenta_virgen_nace_v2_y_queda_persistida(self):
        u2 = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES (?,?,1)",
            ("nuevo@test", "x")).lastrowid
        self.assertEqual(fxmod.fx_version(self.conn, u2), fxmod.FX_V2)
        # Persistió: aunque después confirme su primer batch, sigue v2.
        self.conn.execute(
            "INSERT INTO import_batches (id,user_id,broker,parser_format,file_hash,status) "
            "VALUES (?,?,?,?,?,?)", ("b-x", u2, "IOL", "generic", "h", "confirmed"))
        self.conn.commit()
        self.assertEqual(fxmod.fx_version(self.conn, u2), fxmod.FX_V2)

    # ── 5. Los pares con data manual quedan reportados, no adivinados ─────
    def test_par_manual_queda_salteado_y_reportado(self):
        self._importar_historia_v1()
        # Venta manual sin link sobre el mismo activo → el par queda congelado.
        self.conn.execute(
            "INSERT INTO operations (user_id,date,broker,asset,op_type,quantity,"
            "exit_price,pnl_usd,pnl_pct) VALUES (?,?,?,?,'Venta',?,?,?,?)",
            (self.uid, "2021-07-01", "IOL", "GGAL", 1, 1200, 1.0, 1.0))
        self.conn.commit()
        pnl_antes = self.conn.execute(
            "SELECT pnl_usd FROM operations WHERE user_id=? AND op_type='Venta' "
            "AND quantity=100", (self.uid,)).fetchone()["pnl_usd"]
        with self.conn:
            out = fxm.migrate_user_fx(self.conn, self.uid, helpers=None,
                                      recalc=main._recalc_pnl_realized_from_ops,
                                      backfill_snapshots=ps._backfill_snapshots_from_monthly,
                                      recompute_netdep=main._recompute_snapshots_netdep_for_user)
        self.assertTrue(any(s.get("asset") == "GGAL"
                            for s in out["rebuild"]["pares_salteados"]), out["rebuild"])
        # La venta importada del par congelado conserva su TC viejo (no se adivina)…
        pnl_desp = self.conn.execute(
            "SELECT pnl_usd FROM operations WHERE user_id=? AND op_type='Venta' "
            "AND quantity=100", (self.uid,)).fetchone()["pnl_usd"]
        self.assertEqual(pnl_antes, pnl_desp)
        # …pero los FLUJOS sí se migraron (la pata 1 no depende del rebuild).
        self.assertGreater(out["flujos"]["re_estampados"], 0)


if __name__ == "__main__":
    unittest.main()


class GuardEscalaTest(FxMigrateTest):
    """El migrador se NIEGA sobre una cuenta con el bug per-100: migrarla dejaría
    el cash inflado ×100 sin la firma pnl_pct que hoy lo delata."""

    def test_cuenta_con_escala_rota_no_se_migra(self):
        sid = self._importar_historia_v1()
        # Inyectar una venta linkeada cuyo precio contradice el monto ×100 (el
        # patrón per-100 real: GD30 1000 nominales, precio 70, monto 700).
        rr = self.conn.execute(
            "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
            "VALUES (?,99,'{}','valid')", (sid,)).lastrowid
        self.conn.execute(
            "INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,"
            "operation_type,asset_symbol,quantity,unit_price,gross_amount,currency) "
            "VALUES (?,?,?,?,'SELL','GD30',1000,70,700,'USD')", (sid, rr, "2021-06-15", "IOL"))
        oid = self.conn.execute(
            "INSERT INTO operations (user_id,date,broker,asset,op_type,exit_price,"
            "quantity,pnl_usd,pnl_pct) VALUES (?,?,?,?,'Venta',70,1000,69339.6,10499.6)",
            (self.uid, "2021-06-15", "IOL", "GD30")).lastrowid
        self.conn.execute(
            "INSERT INTO import_op_links (batch_id,raw_row_id,operation_id) VALUES (?,?,?)",
            (sid, rr, oid))
        self.conn.commit()

        with self.conn:
            out = fxm.migrate_user_fx(self.conn, self.uid, helpers=None,
                                      recalc=main._recalc_pnl_realized_from_ops,
                                      backfill_snapshots=ps._backfill_snapshots_from_monthly,
                                      recompute_netdep=main._recompute_snapshots_netdep_for_user)
        self.assertFalse(out["ok"])
        self.assertIn("ESCALA", out["motivo"])
        self.assertEqual(out["ventas_con_escala_rota"], 1)
        # Y nada se movió: sigue v1, pnl viejo intacto.
        self.assertEqual(fxmod.fx_version(self.conn, self.uid), fxmod.FX_V1)
