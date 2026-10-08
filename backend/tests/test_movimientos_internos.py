"""Plata que cambia de sub-cuenta dentro del mismo broker: no es ganancia ni retiro.

PPI y Balanz muestran el pase de una sub-cuenta a otra (dólar local → dólar cable,
"Compensación de monedas", "Renta CV 7.000 a Cable") como DOS filas: una que sale y
otra que entra por el mismo monto. Los parsers las leían por signo: la que entraba,
INTERÉS; la que salía, COMISIÓN. Y el recálculo de la contabilidad arma los retiros
sólo con las filas RETIRO, así que la comisión desaparecía y el interés quedaba:
ganancia realizada que nadie cobró. Medido en la copia de producción del 16/08:
52 cuentas, US$ 324.000 (uid 1078: US$ 58.600 sobre US$ 7.500 aportados).

Todo entra por las puertas reales: `POST /api/imports/preview` + `/confirm`, y lo
que leen las pantallas (`/api/operations`, `/api/movements`, `/api/monthly`,
`/api/positions`). Reemplazado sólo lo que sale a internet (Yahoo y data912).
"""
import io
import os
import sys
import time
import unittest
import uuid
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PPI = "Fecha,Descripción,Cantidad,Precio,Importe,Saldo,Moneda,Especie,_hoja\n"
BALANZ = "Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,Liquidacion,Moneda,Importe\n"
GENERICO = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


class _Cuenta(unittest.TestCase):

    BROKERS = ()

    def setUp(self):
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"internos-{uuid.uuid4().hex[:10]}@rendi.test", "x")).lastrowid
        for nombre, moneda in self.BROKERS:
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                         (self.uid, nombre, moneda))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.http = TestClient(main.app)
        _data912 = mock.patch.object(main, "_fetch_data912_bonds", return_value={})
        _data912.start()
        self.addCleanup(_data912.stop)
        self._fetch_orig = bf._fetch_monthly_close
        bf._HIST_CACHE.clear()
        bf._fetch_monthly_close = lambda price_key, start_iso: {}

    def tearDown(self):
        bf._fetch_monthly_close = self._fetch_orig
        bf._HIST_CACHE.clear()

    def _importar(self, contenido, formato, broker):
        p = self.http.post("/api/imports/preview",
                           files=[("files", ("mov.csv", io.BytesIO(contenido.encode()), "text/csv"))],
                           data={"format": formato, "broker": broker}, headers=self.h)
        self.assertEqual(p.status_code, 200, p.text)
        c = self.http.post("/api/imports/confirm",
                           json={"session_id": p.json()["session_id"],
                                 "skip_row_indices": [], "aprobar_tickers": []},
                           headers=self.h)
        self.assertEqual(c.status_code, 200, c.text)
        limite = time.time() + 60
        while time.time() < limite:
            with main._MTM_RUNNING_LOCK:
                if self.uid not in main._MTM_RUNNING:
                    return
            time.sleep(0.02)
        self.fail("la reconstrucción no terminó en 60 s")

    def _get(self, ruta):
        r = self.http.get(ruta, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _intereses(self):
        return [o for o in self._get("/api/operations") if o["op_type"] in ("Interés", "Interes")]

    def _contabilidad(self):
        """(ganancia realizada, depósitos, retiros) sumados en la fila 'global'."""
        filas = [f for f in self._get("/api/monthly") if f["broker"] == "global"]
        return (round(sum(f["pnl_realized"] or 0 for f in filas), 2),
                round(sum(f["deposits"] or 0 for f in filas), 2),
                round(sum(f["withdrawals"] or 0 for f in filas), 2))

    def _efectivo(self):
        return round(sum(p["invested"] or 0 for p in self._get("/api/positions")
                         if p.get("is_cash")), 2)

    def _tipos_movimientos(self):
        return sorted({m.get("type") or m.get("operation_type") for m in self._get("/api/movements")})


class PpiCompensacionDeMonedas(_Cuenta):
    """Deposita US$ 1.000 en la sub-cuenta dólar local y pasa 500 a dólar cable."""

    BROKERS = (("PPI", "ARS"),)
    FILAS = (PPI
             + "02/06/2026,Ingreso de Fondos,0,0,1000,1000,DolarCV7000 Ext.,,DolarCV7000 Ext.\n"
             + "25/06/2026,Movimiento Manual / Débito/Crédito - Compensación de monedas,"
               "0,0,-500,500,DolarCV7000 Ext.,,DolarCV7000 Ext.\n"
             + "25/06/2026,Movimiento Manual / Débito/Crédito - Compensación de monedas,"
               "0,0,500,500,Dolar Cable,,Dolar Cable\n")

    def test_el_pase_no_es_ganancia_ni_retiro(self):
        self._importar(self.FILAS, "ppi", "PPI")
        # Antes: un "Interés" de US$ 500 y la ganancia realizada en 500.
        self.assertEqual(self._intereses(), [])
        self.assertEqual(self._contabilidad(), (0.0, 1000.0, 0.0))
        # La plata es la que entró: el pase no la cambia.
        self.assertEqual(self._efectivo(), 1000.0)


class PpiPataSuelta(_Cuenta):
    """Si el archivo trae una sola mitad del pase, la plata SÍ entró a lo que Rendi
    ve: es un depósito, no un interés cobrado."""

    BROKERS = (("PPI", "ARS"),)
    FILAS = (PPI
             + "27/01/2026,Movimiento Manual / Canje de monedas USD7000/USD,0,0,158.34,0,Dolar MEP,,Dolar MEP\n")

    def test_la_mitad_que_entra_es_deposito(self):
        self._importar(self.FILAS, "ppi", "PPI")
        self.assertEqual(self._intereses(), [])
        self.assertEqual(self._contabilidad(), (0.0, 158.34, 0.0))
        self.assertEqual(self._efectivo(), 158.34)


class BalanzRentaCvACable(_Cuenta):
    """Cobra un cupón de US$ 40 en dólar local, lo pasa a cable y cobra US$ 7 de
    intereses corridos. El cupón y los intereses son ganancia; el pase, no."""

    BROKERS = (("Balanz", "ARS"),)
    FILAS = (BALANZ
             + "Recibo de Cobro / 1,,,2026-01-05,0,-1,2026-01-05,Dólares,2000\n"
             + "Renta / GD30,GD30,Bonos,2026-01-08,0,-1,2026-01-08,Dólares C.V. 7000,40\n"
             + "Movimiento Manual / Renta CV 7.000 a Cable,,,2026-01-08,0,-1,2026-01-08,Dólares C.V. 7000,-40\n"
             + "Movimiento Manual / Renta CV 7.000 a Cable,,,2026-01-08,0,-1,2026-01-08,Dólares,40\n"
             + "Movimiento Manual / Intereses corridos - MRCUO,MRCUO,Corporativos,2026-01-09,0,-1,2026-01-09,Dólares,7\n")

    def test_cuenta_el_cupon_una_vez_y_no_el_pase(self):
        self._importar(self.FILAS, "balanz_movimientos", "Balanz")
        # Antes: 40 (cupón) + 40 (pase) + 7 = 87.
        realizado, depositos, retiros = self._contabilidad()
        self.assertEqual((realizado, depositos, retiros), (47.0, 2000.0, 0.0))
        # Los intereses corridos SÍ son un interés cobrado; el pase no aparece.
        self.assertEqual([round(o["pnl_usd"], 2) for o in self._intereses()], [7.0])
        self.assertEqual(self._efectivo(), 2047.0)


class GenericoArmadoPorLaIA(_Cuenta):
    """El CSV genérico (el que arma la IA desde un export de Balanz) ya viene con
    INTERES/FEE puestos: la regla mira la descripción, no quién la escribió."""

    BROKERS = (("IBKR", "USDT"),)
    FILAS = (GENERICO
             + "2025-03-01,DEPOSITO,IBKR,,,,5000,,,0,USD,Recibo de Cobro / 9\n"
             + "2025-03-10,INTERES,IBKR,,,,300,,,0,USD,Movimiento Manual / Renta CV 7.000 a Cable\n"
             + "2025-03-10,FEE,IBKR,,,,300,,,0,USD,Movimiento Manual / Renta CV 7.000 a Cable\n")

    def test_el_pase_no_es_ganancia(self):
        self._importar(self.FILAS, "rendi_generic", "IBKR")
        self.assertEqual(self._intereses(), [])
        self.assertEqual(self._contabilidad(), (0.0, 5000.0, 0.0))
        self.assertEqual(self._efectivo(), 5000.0)


class LaRegla(unittest.TestCase):
    """`movimientos_internos.neutralizar` por dentro: qué se aparea y qué no."""

    def _filas(self, *datos):
        from importing.schema import RawRow
        return [RawRow(row_index=i + 1, data=d) for i, d in enumerate(datos)]

    def _f(self, fecha, tipo, monto, notas, broker="PPI", moneda="USD"):
        return {"fecha": fecha, "tipo": tipo, "monto": monto, "notas": notas,
                "broker": broker, "moneda": moneda}

    def test_aparea_por_dia_broker_moneda_y_monto(self):
        from importing.movimientos_internos import neutralizar
        comp = "Movimiento Manual / Débito/Crédito - Compensación de monedas"
        filas = self._filas(
            self._f("2026-06-25", "INTERES", "500", comp),
            self._f("2026-06-25", "FEE", "500", comp),
            self._f("2026-06-25", "INTERES", "500", comp, broker="Balanz"),   # otro broker
            self._f("2026-06-26", "FEE", "500", comp),                       # otro día
            self._f("2026-06-25", "INTERES", "70", comp, moneda="ARS"),      # otra moneda
        )
        out = neutralizar(filas)
        self.assertEqual([(r.row_index, r.data["tipo"]) for r in out],
                         [(3, "DEPOSITO"), (4, "RETIRO"), (5, "DEPOSITO")])

    def test_lo_que_no_es_un_pase_no_se_toca(self):
        from importing.movimientos_internos import neutralizar
        filas = self._filas(
            self._f("2026-01-09", "INTERES", "7", "Movimiento Manual / Intereses corridos - MRCUO"),
            self._f("2026-01-09", "FEE", "7", "Movimiento Manual / Gastos por operación de Fondos"),
            self._f("2026-01-09", "DIVIDENDO", "40", "Renta / GD30"),
        )
        self.assertEqual([r.data for r in neutralizar(filas)], [r.data for r in filas])


if __name__ == "__main__":
    unittest.main()
