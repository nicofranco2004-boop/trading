"""Re-importar tiene que dejar la cuenta en el tipo de cambio HISTÓRICO, sola.

EL PROBLEMA QUE RESUELVE
────────────────────────
Una cuenta en `fx_version=v1` valúa TODA venta en pesos con el dólar de HOY. Con
años de historia eso inventa resultados enormes: medido sobre un GD30 real de
enero 2022 (comprado a 0,343 USD la lámina, vendido a 68,6415 ARS), v1 daba
−886,79 USD (−85,9%) y v2 da −71,55 (−6,9%) — el número verdadero, porque el bono
bajó de 34,3 a 31,9 dólares en esas dos semanas.

Hasta 2026-08-06 la migración sólo se disparaba a mano desde el panel admin, así
que cualquiera que quedara afuera del lote seguía viendo números falsos sin forma
de arreglarlo por su cuenta. Ahora la dispara el propio import.

QUÉ FIJA ESTE ARCHIVO
─────────────────────
1. que un import sobre una cuenta v1 la deje en v2;
2. que las ventas cruzadas queden valuadas al TC de su fecha, no al de hoy;
3. que una cuenta que los frenos rechazan quede en v1 SIN romper el import;
4. que una cuenta que ya está en v2 no se toque.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
for _p in (BACKEND, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_rebuild_fifo import _Base, _csv  # noqa: E402


class _AutoFxBase(_Base):
    BROKER = "IOL"
    BROKER_CCY = "ARS"

    def setUp(self):
        super().setUp()
        self._set_tc_blue(1415.0)          # el dólar "de hoy"
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS fx_rates_daily "
            "(date TEXT PRIMARY KEY, mep_venta REAL, blue_venta REAL)")
        # Serie real (aprox) de las fechas del caso reportado.
        # ON CONFLICT en vez de INSERT OR REPLACE (mismo SQL en SQLite y Postgres).
        # OJO, acá SÍ hay un cambio de comportamiento, y es a propósito: `_Base.setUp`
        # NO vacía fx_rates_daily, así que estas 3 fechas se re-escriben en CADA test.
        # El REPLACE viejo borraba la fila entera y reponía `source`/`fetched_at` con
        # sus DEFAULT ('unknown' / now); con DO UPDATE esas dos columnas SOBREVIVEN.
        # Se deja que sobrevivan porque este fixture no tiene nada mejor que poner ahí
        # y nadie las lee (fx.py no mira source ni fetched_at, y ningún test los
        # asserta) — sólo se pisan los dos valores que el fixture sí define.
        # Tampoco se las nombra en el SET a propósito: si el CREATE TABLE de arriba
        # llegara a ganar, la tabla tendría 3 columnas y `source` ni existiría.
        for d, mep in (("2021-12-01", 195.0), ("2022-01-07", 205.0), ("2022-01-24", 215.0)):
            self.conn.execute(
                "INSERT INTO fx_rates_daily (date, mep_venta, blue_venta) "
                "VALUES (?,?,?) "
                "ON CONFLICT (date) DO UPDATE SET "
                "  mep_venta=EXCLUDED.mep_venta, blue_venta=EXCLUDED.blue_venta",
                (d, mep, mep))
        self.conn.commit()

    def _version(self):
        r = self.conn.execute(
            "SELECT value FROM config WHERE user_id=? AND key='fx_version'",
            (self.uid,)).fetchone()
        return r[0] if r else None

    def _set_version(self, v):
        # ON CONFLICT en vez de INSERT OR REPLACE (mismo SQL en SQLite y Postgres).
        # Conflicto por la PK entera (key, user_id): fx_version es POR CUENTA.
        # Nombra las 3 columnas de `config`, así que la conversión es equivalente.
        # DO UPDATE y no DO NOTHING: el punto del helper es FORZAR la versión —
        # la fila puede existir ya (la puso el propio motor al resolverla), y con
        # DO NOTHING el test creería que forzó v1 mientras la cuenta sigue en v2.
        self.conn.execute(
            "INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
            (self.uid, "fx_version", v))
        self.conn.commit()

    def _migrar(self):
        """Corre el mismo helper que llama import_confirm, contra esta conexión."""
        from importing import fx_migrate as _fxm
        from fx import fx_version, FX_V1
        import main
        if fx_version(self.conn, self.uid) != FX_V1:
            return {"migrada": False, "motivo": "ya estaba en v2"}
        out = _fxm.migrate_user_fx(
            self.conn, self.uid, helpers=None,
            recalc=main._recalc_pnl_realized_from_ops,
            backfill_snapshots=main._import_persister._backfill_snapshots_from_monthly,
            recompute_netdep=main._recompute_snapshots_netdep_for_user,
            force=False)
        if not out.get("ok"):
            return {"migrada": False, "motivo": out.get("motivo")}
        self.conn.commit()
        return {"migrada": True}


class LaCuentaQuedaEnV2Test(_AutoFxBase):

    def test_una_cuenta_v1_pasa_a_v2(self):
        self._import(_csv(
            "2022-01-07,COMPRA,IOL,GD30,3011,0.343,1032.85,,,0,USD,",
            "2022-01-24,VENTA,IOL,GD30,3011,68.6415,206680,,,0,ARS,",
        ), rebuild=True)
        self._set_version("v1")
        self.assertEqual(self._version(), "v1")

        self._migrar()
        self.assertEqual(self._version(), "v2",
                         "tras el import la cuenta tiene que quedar en el TC histórico")

    def test_la_venta_cruzada_deja_de_usar_el_dolar_de_hoy(self):
        self._import(_csv(
            "2022-01-07,COMPRA,IOL,GD30,3011,0.343,1032.85,,,0,USD,",
            "2022-01-24,VENTA,IOL,GD30,3011,68.6415,206680,,,0,ARS,",
        ), rebuild=True)
        self._set_version("v1")
        self._migrar()

        r = self.conn.execute(
            "SELECT pnl_usd, fx_to_usd FROM operations WHERE user_id=? AND asset='GD30' "
            "AND op_type='Venta' ORDER BY id DESC LIMIT 1", (self.uid,)).fetchone()
        self.assertIsNotNone(r)
        self.assertAlmostEqual(
            float(r["fx_to_usd"]), 215.0, delta=1.0,
            msg=f"la venta tiene que valuarse al dólar de su fecha (215), no al de hoy "
                f"(1415). Dio {r['fx_to_usd']}.")
        # 206.680 ARS / 215 = 961,3 USD de ingreso contra 1.032,85 de costo.
        self.assertAlmostEqual(
            float(r["pnl_usd"]), -71.5, delta=3.0,
            msg=f"con el TC de la fecha la pérdida real es ~−71 USD, no −886. "
                f"Dio {r['pnl_usd']}.")


class NoRompeNadaTest(_AutoFxBase):

    def test_una_cuenta_ya_migrada_no_se_toca(self):
        self._import(_csv(
            "2022-01-07,COMPRA,IOL,GD30,3011,0.343,1032.85,,,0,USD,",
            "2022-01-24,VENTA,IOL,GD30,3011,68.6415,206680,,,0,ARS,",
        ), rebuild=True)
        self._set_version("v2")
        out = self._migrar()
        self.assertFalse(out["migrada"], "una cuenta v2 no se vuelve a migrar")
        self.assertEqual(self._version(), "v2")

    def test_si_los_frenos_rechazan_la_cuenta_queda_en_v1_y_el_import_sobrevive(self):
        # El import ocurre y persiste ANTES de cualquier intento de migración.
        self._import(_csv(
            "2022-01-07,COMPRA,IOL,GD30,3011,0.343,1032.85,,,0,USD,",
        ), rebuild=True)
        self._set_version("v1")
        out = self._migrar()

        # Migre o no (depende de los frenos, que son los del panel), lo que NO
        # puede pasar es que el import se pierda.
        pos = self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q FROM positions "
            "WHERE user_id=? AND asset='GD30' AND is_cash=0", (self.uid,)).fetchone()
        self.assertAlmostEqual(float(pos["q"]), 3011.0, places=2,
                               msg="el import tiene que sobrevivir pase lo que pase con la migración")
        self.assertIn(self._version(), ("v1", "v2"))
        if not out["migrada"]:
            self.assertEqual(self._version(), "v1",
                             "si los frenos rechazan, la cuenta queda como estaba")


if __name__ == "__main__":
    unittest.main()
