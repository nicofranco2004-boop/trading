"""La foto reconstruida valúa los bonos al cierre de su mes, no al costo.

Encontrado al filmar el video de portada (03/11/2026): la cuenta compró AL35 y
GD35 en julio (1.220 y 1.258,9 pesos por nominal) y a fin de octubre cotizaban
1.059 y 1.126. La reconstrucción los dejaba al costo («data912 es live-only»),
así que la foto del 31/10 quedaba US$ 706 arriba de la cartera real y la caída
aparecía de golpe entre esa foto y la primera medición del cron. Además, al
costo bajaban la cobertura de julio a 89,93 % (el umbral es 90 %), y eso cortaba
la serie: «Este año: no se puede medir», CAGR sin número.

data912 sí guarda historia (una vela por rueda desde 2021). La reconstrucción
pide el mismo papel que el precio en vivo (AL35 en pesos para una cuenta en
pesos, AL35D para una en dólares) y lo escala con la MISMA regla
(`main._escala_bono`): los soberanos vienen por cada 100 nominales, los CER por
cada 1.

Todo entra por las puertas reales (`/api/imports/preview` + `/confirm`, que
lanza la reconstrucción en su hilo) y la referencia de hoy es el cron de verdad
con el precio en vivo de verdad (`_resolve_ar_bond_price`). Sólo se reemplaza lo
que sale a internet: la historia y el feed en vivo de data912.
"""
import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import snapshots_job as sj  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from fechas import hoy_art_date  # noqa: E402
from tests.test_caja_medida_en_la_reconstruccion import (  # noqa: E402
    MESES, _CajaMedida, _dia, _dolar, _mes)


def _al35(k):
    """Dólares por 1 nominal de AL35 a fin del mes k: baja un centavo por mes."""
    return 0.80 - 0.01 * min(k, MESES)


def _tx26(k):
    """Dólares por 1 nominal del CER TX26: sube un centavo por mes."""
    return 0.50 + 0.01 * min(k, MESES)


def _velas(papel):
    """La historia de data912 de `papel`, como la contesta: soberanos por cada 100
    nominales, el CER por cada 1, en pesos (o en dólares con la 'D').

    Cada mes tiene tres ruedas, y sólo la ÚLTIMA vale: la del día 15 viene al
    doble (si se tomara una rueda que no es el cierre del mes, se nota)."""
    precio = {
        "AL35": lambda k: _al35(k) * 100 * _dolar(k),
        "AL35D": lambda k: _al35(k) * 100,
        "TX26": lambda k: _tx26(k) * _dolar(k),
        "AL30": lambda k: 60.0 * _dolar(k),
        "AL30D": lambda k: 60.0,
    }.get(papel)
    if precio is None:
        return {"Error": "Nahh no tengo ese ticker loko"}   # medido: así contesta
    filas = []
    for k in range(MESES + 1):
        for d, factor in ((2, 1.0), (15, 2.0), (27, 1.0)):
            filas.append({"date": _dia(k, d), "c": precio(k) * factor, "v": 1000.0})
    return filas


class _Resp:
    # data912 contesta 200 también cuando no tiene el papel (con un objeto de
    # error en vez de la lista): medido 2026-11-03.
    def __init__(self, datos, status=200):
        self.status_code = status
        self._datos = datos

    def json(self):
        return self._datos


def _get_historia(url, timeout=None, **kw):
    assert "data912.com/historical/bonds/" in url, url
    return _Resp(_velas(url.rsplit("/", 1)[1]))


def _feed_vivo():
    """`/live/arg_bonds` + `/live/arg_corp` de hoy: los cierres del último mes."""
    k = MESES
    return {"AL35": _al35(k) * 100 * _dolar(k), "AL35D": _al35(k) * 100,
            "TX26": _tx26(k) * _dolar(k), "TX26D": _tx26(k),
            "AL30": 60.0 * _dolar(k), "AL30D": 60.0,
            "PNDCO": 1.02 * 100 * _dolar(k), "PNDCOD": 102.0}


class _Bonos(_CajaMedida):

    def setUp(self):
        super().setUp()
        # El camino de verdad: nada de cierres armados a mano.
        bf._fetch_monthly_close = self._fetch_orig
        for p in (mock.patch.object(main, "_fetch_data912_bonds", side_effect=_feed_vivo),
                  mock.patch.object(main, "_fetch_argentinadatos_letras", return_value={}),
                  mock.patch("pricing.data912.requests.get", side_effect=_get_historia),
                  # El cron de hoy valúa los bonos con el precio en vivo de la app.
                  mock.patch.object(sj, "fetch_prices_for_symbols",
                                    lambda syms, *a, **k: {
                                        s: main._resolve_ar_bond_price(s) for s in syms})):
            p.start()
            self.addCleanup(p.stop)

    def _cobertura(self, k):
        y, m = _mes(k)
        conn = main.get_db()
        try:
            return conn.execute("SELECT mtm_coverage FROM snapshots WHERE user_id=? AND date=?",
                                (self.uid, bf._month_end(y, m))).fetchone()[0]
        finally:
            conn.close()


class LosBonosSeValuanAlCierreDeSuMes(_Bonos):

    def test_cuenta_en_pesos_soberano_y_cer(self):
        # 4.000 AL35 a 800 pesos (US$ 0,80 con el dólar a 1.000) y 2.000 TX26 a 500.
        self._imp("Cocos",
                  f"{_dia(0, 5)},DEPOSITO,Cocos,,,,10000000,,,0,ARS,Aporte",
                  f"{_dia(0, 6)},COMPRA,Cocos,AL35,4000,800,3200000,,,0,ARS,",
                  f"{_dia(0, 6)},COMPRA,Cocos,TX26,2000,500,1000000,,,0,ARS,")
        caja = 10_000_000 - 3_200_000 - 1_000_000
        hoy = self._cron_hoy()
        self.assertAlmostEqual(hoy, caja / _dolar(MESES) + 4000 * _al35(MESES)
                               + 2000 * _tx26(MESES), delta=0.05)
        # Antes: los dos bonos al costo — el último cierre US$ 2.000 arriba de hoy
        # y la cobertura en 0,65.
        self.assertAlmostEqual(self._foto(MESES), hoy, delta=0.05)
        for k in (0, 3, 7, 11):
            self.assertAlmostEqual(
                self._foto(k), caja / _dolar(k) + 4000 * _al35(k) + 2000 * _tx26(k),
                delta=0.05, msg=f"mes {k}")
            self.assertAlmostEqual(self._cobertura(k), 1.0, places=6, msg=f"mes {k}")

    def test_cuenta_en_dolares_pide_el_papel_en_dolares(self):
        # IBKR es una cuenta en dólares: AL35 se valúa con AL35D, no con AL35.
        self._imp("IBKR",
                  f"{_dia(0, 5)},DEPOSITO,IBKR,,,,10000,,,0,USD,",
                  f"{_dia(0, 6)},COMPRA,IBKR,AL35,1000,0.80,800,,,0,USD,")
        hoy = self._cron_hoy()
        self.assertAlmostEqual(hoy, 9200 + 1000 * _al35(MESES), delta=0.05)
        self.assertAlmostEqual(self._foto(MESES), hoy, delta=0.05)
        for k in (2, 9):
            self.assertAlmostEqual(self._foto(k), 9200 + 1000 * _al35(k), delta=0.05)

    def test_la_on_que_data912_no_guarda_queda_al_costo_y_lo_dice(self):
        # data912 no guarda historia de ONs: PNDCO queda al costo y la foto baja
        # su cobertura, en vez de inventar un precio.
        self._imp("Cocos",
                  f"{_dia(0, 5)},DEPOSITO,Cocos,,,,10000000,,,0,ARS,Aporte",
                  f"{_dia(0, 6)},COMPRA,Cocos,AL35,4000,800,3200000,,,0,ARS,",
                  f"{_dia(0, 6)},COMPRA,Cocos,PNDCO,1000,1000,1000000,,,0,ARS,")
        self.assertAlmostEqual(self._foto(5), 5_800_000 / _dolar(5) + 4000 * _al35(5)
                               + 1_000_000 / _dolar(5), delta=0.05)
        self.assertLess(self._cobertura(5), 1.0)


class SiData912NoContesta(_Bonos):

    def _corrida(self, falla):
        """Una reconstrucción con data912 fallando así; → (resumen, pedidos)."""
        bf._HIST_CACHE.clear()
        pedidos = []

        def _get(url, timeout=None, **kw):
            pedidos.append(url)
            if isinstance(falla, Exception):
                raise falla
            return _Resp({"detail": "error"}, status=falla)

        conn = main.get_db()
        try:
            with mock.patch("pricing.data912.requests.get", side_effect=_get):
                return bf.backfill_user(conn, self.uid, hoy_art_date()), pedidos
        finally:
            conn.rollback()
            conn.close()

    def _dos_bonos(self):
        self._imp("Cocos",
                  f"{_dia(0, 5)},DEPOSITO,Cocos,,,,10000000,,,0,ARS,Aporte",
                  f"{_dia(0, 6)},COMPRA,Cocos,AL35,4000,800,3200000,,,0,ARS,",
                  f"{_dia(0, 6)},COMPRA,Cocos,TX26,2000,500,1000000,,,0,ARS,")

    def test_queda_al_costo_y_pide_otra_corrida(self):
        self._dos_bonos()
        r, _ = self._corrida(requests.ConnectionError("caído"))
        self.assertTrue(r.get("reintentar"))
        self.assertIn("AL35.BA", r.get("yahoo_fallo") or [])
        # La falla no quedó guardada: la próxima corrida vuelve a preguntar.
        self.assertFalse(any(k[0] in ("AL35.BA", "TX26.BA") for k in bf._HIST_CACHE))

    def test_un_error_del_servidor_no_es_no_hay_historia(self):
        # Antes: un 503 se leía como "no tiene ese papel", se guardaba, y el
        # bono quedaba al costo hasta fin de mes sin pedir reintento.
        self._dos_bonos()
        r, _ = self._corrida(503)
        self.assertTrue(r.get("reintentar"))
        self.assertFalse(any(k[0] in ("AL35.BA", "TX26.BA") for k in bf._HIST_CACHE))

    def test_caido_no_se_espera_una_vez_por_bono(self):
        # Cada pedido puede esperar su tope de tiempo: con data912 caído, el
        # segundo bono no vuelve a preguntar en la misma corrida.
        self._dos_bonos()
        r, pedidos = self._corrida(requests.Timeout("10 s"))
        self.assertEqual(len(pedidos), 1, pedidos)
        self.assertTrue({"AL35.BA", "TX26.BA"} <= set(r.get("yahoo_fallo") or []))


if __name__ == "__main__":
    unittest.main()
