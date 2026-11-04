"""Confirmar un cobro desde la bandeja MIENTRAS se confirma un import que trae
ese mismo cobro: ¿entra dos veces?

Lo dejó ABIERTO la auditoría del turno (audit/BARRIDO_TOMAR_TURNO_24.md, «Lo que
queda ABIERTO»): la bandeja pide el turno y después mira si ya está anotado
(`dividendos.ya_registrado`, `cobros_bonos.ya_registrado` /
`choca_con_lo_anotado`), pero el intruso posible era el importador, que entonces
no pedía el turno. Si los dos miran «¿ya está?» antes de que el otro escriba,
entran dos filas en Movimientos y dos acreditaciones en la caja.

Cada prueba mete al otro en el PEOR momento: justo DESPUÉS de que el primero
miró lo ya anotado y ANTES de que escriba. Lo que tiene que pasar, en los dos
motores, es lo mismo que en secuencia:
  · dividendo: el importado reemplaza al confirmado (o la bandeja contesta 409);
  · cupón: lo anotado a mano manda y el renglón del archivo se saltea (o la
    bandeja contesta 409).
Y el segundo no termina mientras el primero no confirmó.

Todo por las puertas reales: `/api/imports/preview` + `/confirm` con un CSV, y
`/api/dividendos/cobro`, `/api/bonds/cashflow`, `/api/bonds/cashflow/pago`. Lo
único envuelto es la función que mira «¿ya está?», para elegir el momento.
"""
import io
import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi.testclient import TestClient  # noqa: E402

import cobros_bonos  # noqa: E402
import dividendos  # noqa: E402
import main  # noqa: E402
from tests._limpieza import vaciar  # noqa: E402

PG = bool(getattr(main, "USANDO_PG", False))
HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"
TC = 1450.0
KO = dict(broker="Balanz", asset="KO", ex_date="2026-09-15", fecha="2026-10-06",
          bruto=15.90, impuesto=4.77, otros=0.80, comision_pesos=62.0, cedears=150)
VENTANA_S = 1.5


def _csv(*rows):
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


class _Cruce(unittest.TestCase):

    def setUp(self):
        self.conn = main.get_db()
        vaciar(self.conn, "import_op_links", "import_normalized_tx", "import_raw_rows",
               "import_batches", "operations", "positions", "monthly_entries", "snapshots",
               "deleted_ops_journal", "dividendos_salteados", "dividendos_reemplazados",
               "bond_cashflow_skips", "brokers", "users")
        self.conn.execute("DELETE FROM fx_rates_daily")
        for d in ("2025-03-01", "2025-03-03", "2026-07-09", "2026-07-10", "2026-09-15",
                  "2026-10-01", "2026-10-06", "2026-10-07"):
            self.conn.execute(
                "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source, fetched_at) "
                "VALUES (?,?,?,?,datetime('now'))", (d, TC, TC, "test"))
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("cruce-cobro@rendi.test", "x")).lastrowid
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.addCleanup(main.app.dependency_overrides.pop, main.get_effective_user, None)
        self.client = TestClient(main.app)

    def tearDown(self):
        self.conn.close()

    # ── las puertas ───────────────────────────────────────────────────────────
    def _vista_previa(self, broker, *filas):
        r = self.client.post(
            "/api/imports/preview",
            files=[("files", ("x.csv", io.BytesIO(_csv(*filas)), "text/csv"))],
            data={"format": "rendi_generic", "broker": broker})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["session_id"]

    def _confirmar_import(self, sesion):
        return TestClient(main.app).post("/api/imports/confirm", json={
            "session_id": sesion, "skip_row_indices": [], "aprobar_tickers": []})

    def _importar(self, broker, *filas):
        r = self._confirmar_import(self._vista_previa(broker, *filas))
        self.assertEqual(r.status_code, 200, r.text)

    def _ops(self, op_types):
        ph = ",".join("?" * len(op_types))
        return [dict(r) for r in self.conn.execute(
            f"SELECT * FROM operations WHERE user_id=? AND op_type IN ({ph}) ORDER BY id",
            (self.uid, *op_types)).fetchall()]

    def _caja(self, broker):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(invested),0) FROM positions "
            "WHERE user_id=? AND broker=? AND is_cash=1", (self.uid, broker)).fetchone()
        return round(float(r[0]), 4)

    # ── el cruce ──────────────────────────────────────────────────────────────
    def _cruzar(self, modulo, nombre, primero, segundo):
        """Corre `primero()`; cuando `primero` termina de mirar «¿ya está?»
        (`modulo.nombre`), larga `segundo()` en otro hilo y le da `VENTANA_S` para
        que alcance a terminar. Devuelve (respuesta del primero, del segundo, si
        el segundo terminó adentro de la ventana)."""
        real = getattr(modulo, nombre)
        out, listo = {}, threading.Event()

        def correr_segundo():
            try:
                out["segundo"] = segundo()
            except Exception as ex:
                out["segundo"] = ex
            finally:
                listo.set()

        def envuelta(*a, **kw):
            res = real(*a, **kw)
            if "adentro" not in out:
                threading.Thread(target=correr_segundo, daemon=True).start()
                out["adentro"] = listo.wait(timeout=VENTANA_S)
            return res

        with mock.patch.object(modulo, nombre, envuelta):
            primera = primero()
        self.assertTrue(listo.wait(timeout=60), "el segundo no terminó nunca")
        self.assertIn("adentro", out, f"nunca se llamó a {nombre}: la prueba no cruzó nada")
        return primera, out["segundo"], out["adentro"]


class DividendoDeLaBandejaYDelImport(_Cruce):
    """KO por CEDEARs en Balanz (pesos) con su par en dólares."""

    def setUp(self):
        super().setUp()
        padre = self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, "Balanz", "ARS")).lastrowid
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency, parent_broker_id) VALUES (?,?,?,?)",
            (self.uid, "Balanz · USD", "USDT", padre))
        self.conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                   invested, entry_date, asset_type, currency)
               VALUES (?,?,?,0,?,?,?,?,?,?)""",
            (self.uid, "Balanz", "KO", 14000, 150, 2100000, "2026-08-01", "CEDEAR", "ARS"))
        self.conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested) "
                          "VALUES (?,?,?,1,?)", (self.uid, "Balanz", "ARS", 100000.0))
        self.conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested) "
                          "VALUES (?,?,?,1,?)", (self.uid, "Balanz · USD", "USDT", 1240.50))
        self.conn.commit()
        self.fila = "2026-10-07,DIVIDENDO,Balanz,KO,,,10.40,,,0,USD,"

    def _bandeja(self):
        return TestClient(main.app).post("/api/dividendos/cobro", json=KO)

    def _sumado(self):
        """Lo que entró a la plata del broker, en dólares (los pesos al TC)."""
        return round(self._caja("Balanz · USD") + self._caja("Balanz") / TC
                     - (1240.50 + 100000 / TC), 2)

    def _queda_uno_solo(self, quien):
        divs = self._ops(("Dividendo",))
        print(f"\n>>> [{'PG' if PG else 'SQLite'}] dividendo, {quien}: {len(divs)} fila(s), "
              f"entró {self._sumado()} USD")
        self.assertEqual(len(divs), 1, f"el dividendo entró {len(divs)} veces: {divs}")
        self.assertNotIn(dividendos.SRC, divs[0]["undo_meta_json"] or "",
                         "quedó el confirmado en vez del importado")
        self.assertAlmostEqual(self._sumado(), 10.40, places=2)

    def test_la_bandeja_en_el_medio_del_import(self):
        sesion = self._vista_previa("Balanz", self.fila)
        imp, banda, adentro = self._cruzar(
            dividendos, "reemplazar_por_importado",
            lambda: self._confirmar_import(sesion), self._bandeja)
        self.assertEqual(imp.status_code, 200, imp.text)
        self.assertFalse(adentro, "la bandeja confirmó mientras el import estaba por escribir")
        self.assertEqual(banda.status_code, 409, banda.text)
        self._queda_uno_solo("bandeja en el medio del import")

    def test_el_import_en_el_medio_de_la_bandeja(self):
        sesion = self._vista_previa("Balanz", self.fila)
        banda, imp, adentro = self._cruzar(
            dividendos, "ya_registrado",
            self._bandeja, lambda: self._confirmar_import(sesion))
        self.assertEqual(banda.status_code, 200, banda.text)
        self.assertFalse(adentro, "el import confirmó mientras la bandeja estaba por escribir")
        self.assertEqual(imp.status_code, 200, imp.text)
        self._queda_uno_solo("import en el medio de la bandeja")


class CuponDeLaBandejaYDelImport(_Cruce):
    """GD30 importado en una cuenta en dólares, como test_cupones_bandeja."""

    FILA = "2026-07-10,RENTA Y AMORTIZACION,Balanz,GD30,,,827,,,0,USD,"
    PAGO = dict(broker="Balanz", asset="GD30", date="2026-07-09",
                coupon_amount=27, amort_amount=800)
    CUPON = dict(broker="Balanz", asset="GD30", date="2026-07-09", flow_type="coupon",
                 amount=27)

    def setUp(self):
        super().setUp()
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Balanz", "USDT"))
        self.conn.commit()
        self._importar("Balanz",
                       "2025-03-01,DEPOSITO,Balanz,,,,10000,,,0,USD,",
                       "2025-03-03,COMPRA,Balanz,GD30,10000,0.6,6000,,,0,USD,")
        self.caja_antes = self._caja("Balanz")

    def _cobros(self):
        return self._ops(("Cupón", "Amortización", "Dividendo", "Interés"))

    def _entra_una_vez(self, quien, esperado):
        cobros = self._cobros()
        sumado = round(self._caja("Balanz") - self.caja_antes, 2)
        print(f"\n>>> [{'PG' if PG else 'SQLite'}] GD30, {quien}: "
              f"{sorted(c['op_type'] for c in cobros)}, entró {sumado} USD")
        self.assertAlmostEqual(sumado, esperado, places=2,
                               msg=f"el cobro entró más de una vez: {cobros}")
        return cobros

    # bond_pago: la bandeja de Cartera (cupón + amortización juntos)
    def test_pago_la_bandeja_en_el_medio_del_import(self):
        sesion = self._vista_previa("Balanz", self.FILA)
        imp, banda, adentro = self._cruzar(
            main._import_helpers, "_cobro_bono_confirmado_a_mano",
            lambda: self._confirmar_import(sesion),
            lambda: TestClient(main.app).post("/api/bonds/cashflow/pago", json=self.PAGO))
        self.assertEqual(imp.status_code, 200, imp.text)
        self.assertFalse(adentro, "la bandeja anotó mientras el import estaba por escribir")
        self.assertEqual(banda.status_code, 409, banda.text)
        self._entra_una_vez("pago, bandeja en el medio del import", 827)

    def test_pago_el_import_en_el_medio_de_la_bandeja(self):
        sesion = self._vista_previa("Balanz", self.FILA)
        banda, imp, adentro = self._cruzar(
            cobros_bonos, "ya_registrado",
            lambda: self.client.post("/api/bonds/cashflow/pago", json=self.PAGO),
            lambda: self._confirmar_import(sesion))
        self.assertEqual(banda.status_code, 200, banda.text)
        self.assertFalse(adentro, "el import confirmó mientras la bandeja estaba por escribir")
        self.assertEqual(imp.status_code, 200, imp.text)
        cobros = self._entra_una_vez("pago, import en el medio de la bandeja", 827)
        self.assertEqual(sorted(c["op_type"] for c in cobros), ["Amortización", "Cupón"],
                         "el renglón del archivo entró al lado de lo anotado a mano")

    # bond_cashflow: el formulario de un cupón suelto
    def test_cupon_la_bandeja_en_el_medio_del_import(self):
        sesion = self._vista_previa("Balanz", self.FILA)
        imp, banda, adentro = self._cruzar(
            main._import_helpers, "_cobro_bono_confirmado_a_mano",
            lambda: self._confirmar_import(sesion),
            lambda: TestClient(main.app).post("/api/bonds/cashflow", json=self.CUPON))
        self.assertEqual(imp.status_code, 200, imp.text)
        self.assertFalse(adentro, "el cupón a mano entró mientras el import estaba por escribir")
        self.assertEqual(banda.status_code, 409, banda.text)
        self._entra_una_vez("cupón, formulario en el medio del import", 827)

    def test_cupon_el_import_en_el_medio_de_la_bandeja(self):
        sesion = self._vista_previa("Balanz", self.FILA)
        banda, imp, adentro = self._cruzar(
            cobros_bonos, "choca_con_lo_anotado",
            lambda: self.client.post("/api/bonds/cashflow", json=self.CUPON),
            lambda: self._confirmar_import(sesion))
        self.assertEqual(banda.status_code, 200, banda.text)
        self.assertFalse(adentro, "el import confirmó mientras el cupón a mano estaba por escribir")
        self.assertEqual(imp.status_code, 200, imp.text)
        # Sólo un cupón a mano y el archivo trae el pago entero (otro monto): el
        # importado reemplaza al cupón (`cobros_bonos.que_hacer_con_el_renglon`).
        self._entra_una_vez("cupón, import en el medio del formulario", 827)


if __name__ == "__main__":
    unittest.main()
