"""El dólar con el que `reconcile-cash` dolariza el ajuste de caja en pesos.

CONTEXTO. `POST /api/brokers/reconcile-cash` bookea la diferencia entre el cash
computado y el real en el mes MÁS VIEJO del broker (representa historia pre-CSV),
y esa diferencia va a `deposits`/`manual_deposits`: o sea, al CAPITAL APORTADO,
que es el denominador del rendimiento. Como el recalc trata `manual_*` como
autoritativo y no lo recomputa, un dólar torcido acá queda torcido para siempre.

EL BUG (auditoría 1A, hallazgo A-6). `BrokerReconcileCashIn.tc_blue` estaba
declarado `Field(1415, ...)` y el endpoint hacía `magnitude / data.tc_blue`. Su
único caller —el paso de reconciliación del ImportWizard— no manda ese campo, así
que en producción TODA reconciliación en pesos se dividía por 1415: un dólar
congelado en el código, no una cotización. Y como el ajuste se bookea en un mes
viejo, ni siquiera el dólar de hoy sería el correcto.

Estos tests fallan con el código viejo: el primero da el monto dividido por 1415
en vez de por el TC del mes bookeado, y el tercero ni siquiera llega a correr
porque el modelo rechazaba `tc_blue: None`.

Corre con: cd backend && python3 -m pytest tests/test_reconcile_cash_rate.py
"""
import unittest
from datetime import datetime

import main
from fastapi.testclient import TestClient


class ReconcileCashRateTest(unittest.TestCase):
    BROKER = "TestRecon"
    # El mes al que se bookea el ajuste, y el TC de esa fecha. Elegido lejos de
    # 1415 para que el test distinga "resolvió por fecha" de "cayó al default".
    ANIO, MES = 2022, 3
    TC_DE_ESE_MES = 200.0

    def setUp(self):
        conn = main.get_db()
        for t in ("operations", "positions", "monthly_entries", "snapshots",
                  "brokers", "fx_rates_daily", "config", "users"):
            try:
                conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = conn.execute(
            "INSERT INTO users (email,password_hash,approved,email_verified) "
            "VALUES ('recon@rendi.test','x',1,1)").lastrowid
        conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,'ARS')",
                     (self.uid, self.BROKER))
        # Historia previa: el mes más viejo del broker es el que recibe el ajuste.
        conn.execute(
            """INSERT INTO monthly_entries
               (user_id,year,month,broker,deposits,withdrawals,pnl_realized,
                pnl_unrealized,capital_inicio,capital_final)
               VALUES (?,?,?,?,0,0,0,0,0,0)""",
            (self.uid, self.ANIO, self.MES, self.BROKER))
        # Serie de TC: el MEP de la fecha bookeada. `fx_for_date` lo prefiere.
        conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
            (f"{self.ANIO:04d}-{self.MES:02d}-01", 190.0, self.TC_DE_ESE_MES))
        conn.commit()
        conn.close()
        self.client = TestClient(main.app)
        self.hdr = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def _reconciliar(self, target_cash, **extra):
        r = self.client.post("/api/brokers/reconcile-cash", headers=self.hdr,
                             json={"broker_name": self.BROKER,
                                   "target_cash": target_cash, **extra})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _fila(self):
        conn = main.get_db()
        row = conn.execute(
            """SELECT deposits, manual_deposits, manual_deposits_native
                 FROM monthly_entries
                WHERE user_id=? AND broker=? AND year=? AND month=?""",
            (self.uid, self.BROKER, self.ANIO, self.MES)).fetchone()
        conn.close()
        return row

    def test_usa_el_tc_del_mes_bookeado_y_no_el_1415_hardcodeado(self):
        """REGRESIÓN A-6: el caller real no manda `tc_blue`.

        1.000.000 ARS al TC de marzo 2022 (200) son US$5.000. Con el default duro
        de 1415 daban US$706,71 — un 86 % menos de capital aportado, permanente."""
        self._reconciliar(1_000_000.0)          # sin tc_blue, como el ImportWizard
        row = self._fila()
        self.assertAlmostEqual(float(row["deposits"]), 5000.0, places=2)
        # Y explícitamente: NO es el número que daba el default congelado.
        self.assertNotAlmostEqual(float(row["deposits"]), 1_000_000 / 1415, places=2)

    def test_el_nativo_queda_en_pesos(self):
        """`manual_deposits_native` guarda el monto en la moneda del broker: es lo
        que permite auditar después con qué TC se dolarizó."""
        self._reconciliar(1_000_000.0)
        row = self._fila()
        self.assertAlmostEqual(float(row["manual_deposits_native"]), 1_000_000.0, places=2)
        self.assertAlmostEqual(float(row["manual_deposits"]), 5000.0, places=2)

    def test_el_tc_del_cliente_es_ultimo_recurso_no_default(self):
        """Si el navegador manda un TC, sólo se usa cuando NO hay serie para esa
        fecha. Con serie, gana la serie: el cliente manda el dólar de HOY y el
        ajuste pertenece a un mes viejo."""
        self._reconciliar(1_000_000.0, tc_blue=1500.0)
        row = self._fila()
        self.assertAlmostEqual(float(row["deposits"]), 5000.0, places=2)

    def test_sin_serie_para_esa_fecha_cae_al_tc_del_cliente(self):
        conn = main.get_db()
        conn.execute("DELETE FROM fx_rates_daily")
        conn.commit()
        conn.close()
        self._reconciliar(1_000_000.0, tc_blue=1500.0)
        row = self._fila()
        self.assertAlmostEqual(float(row["deposits"]), 1_000_000 / 1500.0, places=2)

    def test_broker_en_dolares_no_convierte(self):
        conn = main.get_db()
        conn.execute("UPDATE brokers SET currency='USDT' WHERE user_id=? AND name=?",
                     (self.uid, self.BROKER))
        conn.commit()
        conn.close()
        self._reconciliar(5000.0)
        self.assertAlmostEqual(float(self._fila()["deposits"]), 5000.0, places=2)



class ReconcileSinHistoriaTest(unittest.TestCase):
    """Un broker SIN historia previa bookea el ajuste en el mes EN CURSO, así que
    el TC que corresponde es el de HOY — no el del día 1 de este mes.

    Lo encontré auditando mi propio fix: la primera versión usaba
    `f"{año}-{mes}-01"` en los dos casos. Con historia está bien (el ajuste
    pertenece a un mes viejo); sin historia daba una cotización de hasta 27 días
    atrás para un movimiento de hoy.
    """
    BROKER = "TestSinHist"

    def setUp(self):
        conn = main.get_db()
        for t in ("operations", "positions", "monthly_entries", "brokers",
                  "fx_rates_daily", "config", "users"):
            try:
                conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = conn.execute(
            "INSERT INTO users (email,password_hash,approved,email_verified) "
            "VALUES ('sinhist@rendi.test','x',1,1)").lastrowid
        conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,'ARS')",
                     (self.uid, self.BROKER))
        from fechas import ahora_art
        hoy = ahora_art()
        self.anio, self.mes = hoy.year, hoy.month
        # Dos cotizaciones: la del día 1 de este mes y la de hoy, bien separadas.
        primero = f"{self.anio:04d}-{self.mes:02d}-01"
        conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) "
                     "VALUES (?,?,?)", (primero, 500.0, 500.0))
        if hoy.strftime('%Y-%m-%d') != primero:
            conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) "
                         "VALUES (?,?,?)", (hoy.strftime('%Y-%m-%d'), 1000.0, 1000.0))
            self.tc_hoy, self.hay_dos = 1000.0, True
        else:
            self.tc_hoy, self.hay_dos = 500.0, False
        conn.commit()
        conn.close()
        self.client = TestClient(main.app)
        self.hdr = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def test_usa_el_tc_de_hoy_y_no_el_del_dia_1(self):
        r = self.client.post("/api/brokers/reconcile-cash", headers=self.hdr,
                             json={"broker_name": self.BROKER, "target_cash": 1_000_000.0})
        self.assertEqual(r.status_code, 200, r.text)
        conn = main.get_db()
        row = conn.execute(
            "SELECT deposits FROM monthly_entries WHERE user_id=? AND broker=? "
            "AND year=? AND month=?",
            (self.uid, self.BROKER, self.anio, self.mes)).fetchone()
        conn.close()
        self.assertAlmostEqual(float(row["deposits"]), 1_000_000 / self.tc_hoy, places=2)
        if self.hay_dos:   # el día 1 del mes el test no puede distinguir
            self.assertNotAlmostEqual(float(row["deposits"]), 1_000_000 / 500.0, places=2)

if __name__ == "__main__":
    unittest.main()
