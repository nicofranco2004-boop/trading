"""El modo ESTIMADO no publica una cadena contable que no describe la plata que había.

El estimado encadena la contabilidad mes a mes (realizado / capital al costo) y
publica "la ventana continua más reciente". `leg_dudoso` mira un mes por vez, así
que una cadena puede multiplicarse por 13 con todos sus meses creíbles. Medido en
la copia de producción del 2026-08-16: el estimado publicaba ≥300 % en 31 cuentas
y ≥1.000 % en 8 (uid 826: +1.240 % con el certero en +7,1 %). Tres mecanismos, uno
por clase de abajo:

  · la ventana ARRANCA en un mes cuya cartera ya tenía ganancia sin vender (la
    contabilidad, al costo, muy por debajo de la reconstrucción a mercado), y esa
    ganancia se cobra adentro de la ventana — el uid 826;
  · el arranque sobre menos de US$100: dos meses de "+100 %" sobre centavos le
    ponían ×3 a toda la historia — el uid 1008;
  · una cadena que compone más de +1.000 % — el techo que la composición contable
    (`contable_de_filas`) ya aplicaba y la curva no — el uid 1078.

Todo entra por las puertas reales: `POST /api/imports/preview` + `/confirm` (que
lanza la reconstrucción en su hilo, como en producción) y lo que lee la pantalla:
`GET /api/insights/performance?modo=estimado`. Reemplazado sólo lo que sale a
internet: Yahoo (precios de mentira por ticker) y la lista de bonos de data912.

Para que las fotos queden CONTABLES (y no mediciones a mercado) cada cuenta tiene
una tenencia cargada a mano a costo 0: la reconstrucción no puede afirmar qué parte
de la cartera valuó y la foto queda sin cobertura — lo mismo que le pasaba a la 826,
con tenencia que la reconstrucción no veía.
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

HASTA = "2025-12-31"
HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


def _serie(primeros: dict, despues: float) -> dict:
    """Cierre mensual: los meses de `primeros` y, de ahí hasta 2028, `despues`."""
    out = {}
    for y in range(2025, 2029):
        for m in range(1, 13):
            k = f"{y}-{m:02d}"
            out[k] = primeros.get(k, despues)
    return out


# MSFT se sextuplica entre enero y junio de 2025; KO se derrumba en marzo.
PRECIOS = {
    "MSFT": _serie({"2025-01": 20.0, "2025-02": 60.0, "2025-03": 100.0,
                    "2025-04": 110.0, "2025-05": 115.0}, 120.0),
    "KO": _serie({"2025-01": 100.0, "2025-02": 100.0}, 15.0),
}


def _precio(price_key, start_iso):
    for tk, serie in PRECIOS.items():
        if tk in str(price_key).upper():
            return dict(serie)
    return {}


class _Cuenta(unittest.TestCase):

    def setUp(self):
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"estimado-{uuid.uuid4().hex[:10]}@rendi.test", "x")).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "IBKR", "USDT"))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.http = TestClient(main.app)
        _data912 = mock.patch.object(main, "_fetch_data912_bonds", return_value={})
        _data912.start()
        self.addCleanup(_data912.stop)
        self._fetch_orig = bf._fetch_monthly_close
        bf._HIST_CACHE.clear()
        bf._fetch_monthly_close = _precio
        # La tenencia que la reconstrucción no puede valuar (ver el docstring):
        # recibida gratis y vendida en enero de 2026. Mientras está abierta, sin
        # costo con qué compararla, la foto del mes queda sin cobertura — contable.
        # Por eso el rendimiento se pide HASTA diciembre de 2025.
        r = self.http.post("/api/positions", headers=self.h, json={
            "broker": "IBKR", "asset": "LIBRE", "quantity": 10, "buy_price": 0,
            "invested": 0, "entry_date": "2025-01-01", "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.http.post("/api/positions/sell", headers=self.h, json={
            "broker": "IBKR", "asset": "LIBRE", "quantity": 10, "exit_price": 1,
            "date": "2026-01-15", "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)

    def tearDown(self):
        bf._fetch_monthly_close = self._fetch_orig
        bf._HIST_CACHE.clear()

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
        limite = time.time() + 60
        while time.time() < limite:
            with main._MTM_RUNNING_LOCK:
                if self.uid not in main._MTM_RUNNING:
                    return
            time.sleep(0.02)
        self.fail("la reconstrucción no terminó en 60 s")

    def _estimado(self):
        r = self.http.get("/api/insights/performance",
                          params={"modo": "estimado", "hasta": HASTA}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _puntos(self, p):
        return {c["date"]: c for c in p["curva"]}


class LaVentanaNoArrancaConGananciaAdentro(_Cuenta):
    """El mecanismo del uid 826, en chico.

    Enero: deposita 10.000 y compra 100 MSFT a 20 y 80 KO a 100. Marzo: KO se
    derrumba y lo vende a 15 — la contabilidad cae de 10.000 a 3.200, un salto que
    `leg_dudoso` corta, así que la ventana más reciente ARRANCA el 31/03. Pero ese
    día la cartera valía 11.200 (MSFT ya estaba a 100). De abril a julio vende las
    MSFT a 110–120, y cada venta suma sobre aquel costo de 3.200.

    Sin el freno, el estimado publicaba +303 % (3.200 → 12.900). La cartera, de
    marzo a hoy, fue de 11.200 a 12.900 — y lo que el estimado puede afirmar sin
    inventar es desde julio, el primer mes en que contabilidad y mercado coinciden:
    de ahí en adelante no pasó nada.
    """

    FILAS = [
        "2025-01-02,DEPOSITO,IBKR,,,,10000,,,0,USD,",
        "2025-01-03,COMPRA,IBKR,MSFT,100,20,2000,,,0,USD,",
        "2025-01-03,COMPRA,IBKR,KO,80,100,8000,,,0,USD,",
        "2025-03-10,VENTA,IBKR,KO,80,15,1200,,,0,USD,",
        "2025-04-10,VENTA,IBKR,MSFT,20,110,2200,,,0,USD,",
        "2025-05-10,VENTA,IBKR,MSFT,20,115,2300,,,0,USD,",
        "2025-06-10,VENTA,IBKR,MSFT,20,120,2400,,,0,USD,",
        "2025-07-10,VENTA,IBKR,MSFT,40,120,4800,,,0,USD,",
    ]

    def test_el_estimado_arranca_donde_la_contabilidad_coincide_con_la_cartera(self):
        self._importar(self.FILAS)
        p = self._estimado()
        pts = self._puntos(p)
        # Las premisas, leídas de la misma respuesta: el 31/03 la contabilidad
        # dice 3.200 y la reconstrucción a precios de marzo 11.200.
        self.assertEqual(pts["2025-03-31"]["clase"], "sintetico_costo")
        self.assertEqual(pts["2025-03-31"]["value_no_medible"], 3200.0)
        self.assertEqual(pts["2025-03-31"]["valor_foto"], 11200.0)
        # Lo publicado: desde julio, cuando contabilidad (12.900) y cartera
        # (12.900) vuelven a coincidir, y de ahí en adelante nada se movió.
        self.assertEqual(p["ventana_desde"], "2025-07-31")
        self.assertAlmostEqual(p["twr"], 0.0, places=9)
        # El corte que lo explica: la cadena no pudo arrancar el 31/03. (El
        # `motivo` sigue siendo el de una cuenta sin mediciones a mercado, que es
        # lo que explica por qué el certero no tiene número.)
        cortes = [c for c in p["cortes_dudosos"] if c["cadena"] == "contable"]
        self.assertIn(("2025-03-31", "cadena_implausible"),
                      {(c["desde"], c["motivo"]) for c in cortes})

    def test_el_certero_no_cambia(self):
        """El freno es de la cadena contable: el modo certero no la usa."""
        self._importar(self.FILAS)
        r = self.http.get("/api/insights/performance", params={"hasta": HASTA},
                          headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["cortes_dudosos"], [])


class ElArranqueSobreCentavosNoMide(_Cuenta):
    """El mecanismo del uid 1008, en chico.

    Enero: deposita 20 y compra 1 MSFT a 20. Febrero: la vende a 55 (+35 sobre 20,
    +175 % — un ×2,75 que `leg_dudoso` deja pasar). Marzo: deposita 10.000, que se
    quedan quietos. Sin el freno el estimado publicaba +175 % para alguien que
    tiene 10.055 de 10.020 puestos. Con menos de US$100 de capital un porcentaje no
    describe nada — el mismo piso que `contable_de_filas` ya aplicaba.
    """

    FILAS = [
        "2025-01-02,DEPOSITO,IBKR,,,,20,,,0,USD,",
        "2025-01-03,COMPRA,IBKR,MSFT,1,20,20,,,0,USD,",
        "2025-02-10,VENTA,IBKR,MSFT,1,55,55,,,0,USD,",
        "2025-03-05,DEPOSITO,IBKR,,,,10000,,,0,USD,",
    ]

    def test_los_meses_de_menos_de_100_dolares_no_entran_al_numero(self):
        self._importar(self.FILAS)
        p = self._estimado()
        pts = self._puntos(p)
        self.assertEqual(pts["2025-01-31"]["value_no_medible"], 20.0)
        self.assertEqual(pts["2025-02-28"]["value_no_medible"], 55.0)
        self.assertEqual(p["ventana_desde"], "2025-03-31")
        self.assertAlmostEqual(p["twr"], 0.0, places=9)
        self.assertEqual([(c["desde"], c["hasta"]) for c in p["cortes_capital_chico"]],
                         [("2025-01-31", "2025-02-28"), ("2025-02-28", "2025-03-31")])
        # No es un dato roto: no va a la cola de revisión del admin.
        self.assertEqual([c for c in p["cortes_dudosos"] if c["cadena"] == "contable"], [])


class LaCadenaSobreElTechoNoSePublica(_Cuenta):
    """El mecanismo del uid 1078 (conversiones entre monedas de PPI importadas como
    "interés"), en chico: 1.000 depositados y once "dividendos" de 1.000, uno por
    mes. Ningún mes es increíble (el peor es ×2), la cadena compone ×12 = +1.100 %.
    El techo de +1.000 % es el que la composición contable ya aplicaba
    (`MAX_PNL_PCT`). La cuenta no tiene mediciones, así que se queda sin número —
    con el motivo — en vez de con uno inventado."""

    FILAS = (["2025-01-02,DEPOSITO,IBKR,,,,1000,,,0,USD,"]
             + [f"2025-{m:02d}-10,DIVIDENDO,IBKR,MSFT,,,1000,,,0,USD," for m in range(2, 13)])

    def test_sin_numero_y_con_el_motivo(self):
        self._importar(self.FILAS)
        p = self._estimado()
        pts = self._puntos(p)
        self.assertEqual(pts["2025-12-31"]["value_no_medible"], 12000.0)
        self.assertIsNone(p["twr"])
        self.assertEqual(p["motivo"], "cadena_implausible")
        techo = [c for c in p["cortes_dudosos"] if c["cadena"] == "contable_techo"]
        self.assertEqual(len(techo), 1)
        self.assertAlmostEqual(techo[0]["factor"], 12.0, places=3)


if __name__ == "__main__":
    unittest.main()
