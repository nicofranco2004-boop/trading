"""El mes sin movimientos también tiene foto: la curva del que compra y mantiene.

La contabilidad mensual (`monthly_entries`) sólo tiene fila para los meses con
depósitos, retiros o ventas. Un mes en el que la persona sólo compró, o no hizo
nada, no la tiene. La reconstrucción a mercado que corre después de cada import
(`scripts/backfill_historical_mtm.py`) armaba una foto por FILA, así que esos meses
quedaban sin foto. Dos fotos separadas por un mes faltante quedan a ~60 días, más
que `twr.MAX_HUECO_DIAS` (45): la serie se parte y el rendimiento desaparece.

Medido con la cuenta de laboratorio de abajo (2026-10-03): depositando 100 todos
los meses daba +16,95 % desde el 31/01/2025; sacando SÓLO el depósito de junio, la
sección de rendimiento quedaba sin número (`serie_partida`). Y después del último
depósito tampoco había fotos: el que deja de depositar y mantiene la cartera
quedaba con la última foto a meses de la primera medición del cron.

Todo entra por las puertas reales: `POST /api/imports/preview` + `/confirm` (que
lanza la reconstrucción en su hilo, como en producción) y lo que lee la pantalla
(`GET /api/snapshots` y `GET /api/insights/performance`). Lo único reemplazado es
lo que sale a internet: Yahoo (AAPL cierra cada mes a 200 + 5×n, n=1 en enero de
2025) y la lista de bonos de data912.
"""
import io
import os
import sys
import time
import unittest
import uuid
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import twr  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


def _ym(n):
    """Mes n contando enero de 2025 como 1."""
    y, m = divmod(n - 1, 12)
    return f"{2025 + y}-{m + 1:02d}"


PRECIOS = {_ym(n): 200.0 + 5 * n for n in range(1, 40)}
ACEPTA_LINEA = ("medicion", "reconstruido", "intradia")


def _ultimo_mes_cerrado():
    """La reconstrucción no toca el mes en curso (lo maneja el flujo live). Se le
    pregunta a la app qué día es hoy, con el mismo reloj que usa el hilo."""
    from datetime import datetime
    hoy = datetime.utcnow().date()
    y, m = (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    return f"{y}-{m:02d}"


def _filas_laboratorio(sin_deposito_de=()):
    """Depósito de 10.000 y compra de 40 AAPL a 200 en enero de 2025; después 100
    por mes de febrero a octubre, salvo los meses que se pidan sacar."""
    filas = ["2025-01-02,DEPOSITO,IBKR,,,,10000,,,0,USD,",
             "2025-01-03,COMPRA,IBKR,AAPL,40,200,8000,,,0,USD,"]
    for mes in range(2, 11):
        if mes not in sin_deposito_de:
            filas.append(f"2025-{mes:02d}-10,DEPOSITO,IBKR,,,,100,,,0,USD,")
    return filas


class _Cuenta(unittest.TestCase):

    def setUp(self):
        self._crear_cuenta()
        self.http = TestClient(main.app)
        _data912 = mock.patch.object(main, "_fetch_data912_bonds", return_value={})
        _data912.start()
        self.addCleanup(_data912.stop)
        self._fetch_orig = bf._fetch_monthly_close
        bf._HIST_CACHE.clear()
        bf._fetch_monthly_close = lambda price_key, start_iso: dict(PRECIOS)

    def tearDown(self):
        bf._fetch_monthly_close = self._fetch_orig
        bf._HIST_CACHE.clear()

    def _crear_cuenta(self):
        """Una cuenta en IBKR (dólares). Deja `self.uid` y `self.h` apuntando a ella."""
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"sin-fila-{uuid.uuid4().hex[:10]}@rendi.test", "x")).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "IBKR", "USDT"))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def _importar(self, filas):
        csv = (HDR + "".join(f + "\n" for f in filas)).encode()
        p = self.http.post("/api/imports/preview",
                           files=[("files", ("mov.csv", io.BytesIO(csv), "text/csv"))],
                           data={"format": "rendi_generic", "broker": "IBKR"}, headers=self.h)
        self.assertEqual(p.status_code, 200, p.text)
        c = self.http.post("/api/imports/confirm",
                           json={"session_id": p.json()["session_id"],
                                 "skip_row_indices": [], "aprobar_tickers": []},
                           headers=self.h)
        self.assertEqual(c.status_code, 200, c.text)
        self.assertEqual((c.json().get("mtm_reconstruccion") or {}).get("reconstruida"),
                         "en_curso", c.text)
        limite = time.time() + 60
        while time.time() < limite:
            with main._MTM_RUNNING_LOCK:
                if self.uid not in main._MTM_RUNNING:
                    return
            time.sleep(0.02)
        self.fail("la reconstrucción no terminó en 60 s")

    def _fotos(self):
        r = self.http.get("/api/snapshots", params={"days": 3650}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return [f for f in r.json() if f.get("clase") in ACEPTA_LINEA]

    def _rendimiento(self):
        r = self.http.get("/api/insights/performance", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _meses_con_fila(self):
        conn = main.get_db()
        try:
            return {f"{r['year']}-{r['month']:02d}" for r in conn.execute(
                "SELECT year, month FROM monthly_entries WHERE user_id=? AND broker='global'",
                (self.uid,))}
        finally:
            conn.close()


class ElMesSinFilaTieneFoto(_Cuenta):

    def test_un_mes_sin_deposito_ya_no_le_borra_el_rendimiento(self):
        self._importar(_filas_laboratorio(sin_deposito_de=(6,)))
        # La premisa: junio no tiene fila en la contabilidad.
        self.assertNotIn("2025-06", self._meses_con_fila())
        self.assertIn("2025-07", self._meses_con_fila())

        p = self._rendimiento()
        # Antes: twr None, motivo 'serie_partida'.
        self.assertIsNotNone(p["twr"], p.get("motivo"))
        self.assertFalse(p["serie_partida"])
        self.assertEqual(p["ventana_desde"], "2025-01-31")

        # La foto de junio, escrita a mano. Hasta mayo entraron 10.000 + 4×100;
        # en junio la contabilidad no se movió y AAPL cerró a 230:
        #   efectivo 2.400 + 40 × 230 = 11.600, aportado 10.400 (arrastrado, no 0).
        junio = {f["date"]: f for f in self._fotos()}["2025-06-30"]
        self.assertEqual(junio["clase"], "reconstruido")
        self.assertEqual((junio["total_value"], junio["net_deposited"]), (11600.0, 10400.0))

    def _rendimiento_hasta_octubre(self):
        r = self.http.get("/api/insights/performance", params={"hasta": "2025-10-31"},
                          headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_casi_el_mismo_numero_que_depositando_todos_los_meses(self):
        """Lo que gana la cartera es lo que hacen las 40 AAPL, haya depósito en
        junio o no. La cuenta completa reproduce el +16,95 % medido el 03/10 (de
        enero a octubre de 2025, lo que antes alcanzaba a cubrir la curva); la
        del hueco, que antes no tenía número, da casi lo mismo."""
        self._importar(_filas_laboratorio())
        completo = self._rendimiento_hasta_octubre()
        self._crear_cuenta()
        self._importar(_filas_laboratorio(sin_deposito_de=(6,)))
        con_hueco = self._rendimiento_hasta_octubre()
        self.assertEqual(round(completo["twr"], 4), 0.1695)
        self.assertIsNotNone(con_hueco["twr"], con_hueco.get("motivo"))
        for p in (completo, con_hueco):
            self.assertEqual((p["ventana_desde"], p["ventana_hasta"]),
                             ("2025-01-31", "2025-10-31"))
        # La única diferencia son 100 dólares de efectivo quieto que la cuenta
        # del hueco no tiene (~0,8 % de la cartera): diluyen un poco la ganancia
        # de la completa, así que la del hueco da apenas MÁS, nunca otra cosa.
        self.assertGreater(con_hueco["twr"], completo["twr"])
        self.assertLess(con_hueco["twr"] - completo["twr"], 0.008 * completo["twr"])

    def test_cada_mes_cerrado_tiene_su_foto_y_su_aportado_canonico(self):
        self._importar(_filas_laboratorio(sin_deposito_de=(6,)))
        fotos = self._fotos()
        conn = main.get_db()
        try:
            canon = twr.netdep_canonico(conn, self.uid)
        finally:
            conn.close()
        # Un mes detrás de otro, del primero al último cerrado: ninguno falta.
        meses = [f["date"][:7] for f in fotos]
        hasta = _ultimo_mes_cerrado()
        n, esperado = 1, []
        while _ym(n) <= hasta:
            esperado.append(_ym(n))
            n += 1
        self.assertEqual(meses, esperado)
        # El aportado es el canónico (el del cron y la curva) en TODAS, y nunca 0.
        for f in fotos:
            self.assertEqual(f["net_deposited"], canon(f["date"]), f["date"])
            self.assertGreater(f["net_deposited"], 0, f["date"])
        # Después del último depósito (octubre: 10.000 + 8×100) la persona sigue
        # con sus 40 AAPL: noviembre vale efectivo 2.800 + 40 × 255.
        nov = {f["date"]: f for f in fotos}["2025-11-30"]
        self.assertEqual((nov["total_value"], nov["net_deposited"]), (13000.0, 10800.0))

    def test_el_mes_con_solo_una_compra_valua_lo_que_compro(self):
        """Una compra no es un flujo: no crea fila. La foto del mes igual tiene que
        ver las acciones nuevas, con el efectivo que salió para pagarlas."""
        filas = _filas_laboratorio(sin_deposito_de=(6,))
        filas.append("2025-06-12,COMPRA,IBKR,AAPL,5,228,1140,,,0,USD,")
        self._importar(filas)
        self.assertNotIn("2025-06", self._meses_con_fila())
        junio = {f["date"]: f for f in self._fotos()}["2025-06-30"]
        # Efectivo 2.400 − 1.140 = 1.260; 45 AAPL × 230 = 10.350.
        self.assertEqual((junio["total_value"], junio["net_deposited"]), (11610.0, 10400.0))
        self.assertIsNotNone(self._rendimiento()["twr"])

    def test_no_pisa_la_medicion_del_cron_de_un_mes_sin_fila(self):
        """El cron midió el 30/06 (por ejemplo, la cuenta ya estaba en Rendi). La
        reconstrucción de un mes sin fila no puede reemplazar una medición."""
        conn = main.get_db()
        conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, fx_to_usd_blue, holdings_json, source) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (self.uid, "2025-06-30", 11655.0, 9000.0, 10400.0, 1200.0,
             '[{"asset":"AAPL","value_usd":9255}]', "cron"))
        conn.commit()
        conn.close()
        self._importar(_filas_laboratorio(sin_deposito_de=(6,)))
        junio = {f["date"]: f for f in self._fotos()}["2025-06-30"]
        self.assertEqual(junio["clase"], "medicion")
        self.assertEqual(junio["total_value"], 11655.0)


class ElEstimadoLeeLaContabilidadDelMesSinFila(_Cuenta):
    """En modo estimado la foto "contable" no se usa tal cual: se reemplaza por el
    saldo de la contabilidad de su mes (`twr.serie_medible`, la foto es una copia
    que se desactualiza). Ese saldo se buscaba por mes EXACTO, así que la foto de
    un mes sin fila se quedaba con su valor crudo entre dos meses realineados.

    Cómo se llega a una foto así por el camino real: una tenencia recibida gratis
    (10 LIBRE a costo 0, cargada a mano) que se vende en diciembre. Mientras está
    abierta, la reconstrucción no puede afirmar qué parte de la cartera valuó (no
    hay costo con qué compararla) y la foto queda sin cobertura: contable.
    Medido con esta cuenta: el estimado publicaba +20,4 % hasta noviembre —junio
    saltaba a su valor a mercado y julio volvía— en una contabilidad que hasta ahí
    sólo tuvo depósitos. En la copia de producción del 16/08 el mismo defecto ya
    movía el estimado de 40 cuentas con fotos viejas en meses sin fila (uid 89:
    US$ 177 entre meses de US$ 394, −20,9 % en vez de +52,3 %)."""

    def test_el_mes_sin_fila_toma_el_saldo_arrastrado_y_no_inventa_resultado(self):
        r = self.http.post("/api/positions", headers=self.h, json={
            "broker": "IBKR", "asset": "LIBRE", "quantity": 10, "buy_price": 0,
            "invested": 0, "entry_date": "2025-01-05", "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.http.post("/api/positions/sell", headers=self.h, json={
            "broker": "IBKR", "asset": "LIBRE", "quantity": 10, "exit_price": 5,
            "date": "2025-12-10", "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)
        self._importar(_filas_laboratorio(sin_deposito_de=(6,)))
        self.assertNotIn("2025-06", self._meses_con_fila())

        r = self.http.get("/api/insights/performance", headers=self.h,
                          params={"modo": "estimado", "hasta": "2025-11-30"})
        self.assertEqual(r.status_code, 200, r.text)
        p = r.json()
        puntos = {c["date"]: c for c in p["curva"]}
        # La premisa: la foto de junio es contable.
        self.assertEqual(puntos["2025-06-30"]["clase"], "sintetico_costo")
        # Junio vale lo que dice la contabilidad: el saldo de mayo, arrastrado
        # (10.000 + 4 × 100), igual que el aportado. Antes: 11.600, su valor crudo,
        # que queda registrado aparte.
        self.assertEqual(puntos["2025-06-30"]["value_no_medible"], 10400.0)
        self.assertEqual(puntos["2025-06-30"]["valor_foto"], 11600.0)
        # Hasta noviembre la contabilidad sólo tuvo depósitos: el estimado (que
        # por diseño no cuenta lo no realizado) da exactamente cero.
        self.assertEqual(p["twr"], 0.0)


class LaListaDeMeses(unittest.TestCase):
    """`_meses_a_reconstruir` por dentro: qué fila rige cada mes."""

    def test_el_mes_sin_fila_hereda_la_del_ultimo_que_tuvo(self):
        f_ene = (2025, 1, 0.0, 10000.0, 0.0, 0.0)
        f_abr = (2025, 4, 10000.0, 500.0, 0.0, 0.0)
        meses = bf._meses_a_reconstruir([f_ene, f_abr], date(2025, 7, 3))
        self.assertEqual([(y, m, f, p) for y, m, f, p in meses], [
            (2025, 1, f_ene, True), (2025, 2, f_ene, False), (2025, 3, f_ene, False),
            (2025, 4, f_abr, True), (2025, 5, f_abr, False), (2025, 6, f_abr, False)])

    def test_no_toca_el_mes_en_curso_ni_filas_futuras(self):
        f = (2025, 12, 0.0, 100.0, 0.0, 0.0)
        futura = (2099, 7, 0.0, 1.0, 0.0, 0.0)
        meses = bf._meses_a_reconstruir([f, futura], date(2026, 2, 10))
        self.assertEqual([(y, m) for y, m, _, _ in meses], [(2025, 12), (2026, 1)])
        self.assertEqual(bf._meses_a_reconstruir([], date(2026, 2, 10)), [])


if __name__ == "__main__":
    unittest.main()
