"""La serie CER está muerta y los bonos CER ajustaban con factor 1,00.

`api.argentinadatos.com/v1/finanzas/indices/cer` devuelve **404** (medido el
2026-09-08, con `/inflacion` y `/uva` del MISMO host devolviendo 200). El fetcher
devolvía `{}` y `_ensure_index_cached` hacía `return` sin dejar rastro, así que
todo bono CER calculaba su cronograma, su próximo pago, su TIR y el monto
pre-llenado del cupón con **factor 1,00** — contra 7,72× (TZX26/27/28) y 37,44×
(TX26/TX28/T2X5) reales.

La serie UVA del mismo host SÍ responde y sirve de reemplazo porque acá no se usa
el NIVEL del índice: `bondSchedule.js` calcula el RATIO `serie[pago]/serie[emisión]`,
y el BCRA actualiza la UVA POR CER.

⚠️ Los tests NO re-implementan la cuenta ni inventan fixtures: usan las fechas de
emisión REALES del catálogo (`bondMeta.js`) y contrastan contra los factores que la
auditoría midió con la serie CER de verdad.

Corre con: cd backend && python3 -m pytest tests/test_cer_serie_caida.py
"""
from __future__ import annotations
import json
import logging
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main

# Fechas de emisión REALES del catálogo (frontend/src/utils/bondMeta.js) y el
# factor CER que la auditoría midió para cada grupo contra la serie verdadera.
EMISIONES = {
    "TX26/TX28/T2X5": ("2020-08-04", 37.44),
    "TZX26/27/28":    ("2023-06-30",  7.72),
}
MEDIDO_AL = "2026-09-01"     # la fecha en que la auditoría tomó esos factores

# Una UVA de juguete no serviría: el punto es que los ratios REALES coincidan.
# Se usa la serie que la app baja, recortada a las fechas que hacen falta.
UVA = {
    "2016-03-31": 14.05,
    "2020-08-04": 56.25,
    "2023-06-30": 272.76,
    "2026-09-01": 2100.02,
}


class _Resp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._p = payload or []

    def json(self):
        return self._p


def _fuente(cer_ok: bool, uva_ok: bool = True):
    """Simula el host: CER en 404, UVA en 200 — que es lo que pasa hoy."""
    def _get(url, **kw):
        if "/indices/cer" in url:
            return _Resp(200 if cer_ok else 404,
                         [{"fecha": d, "valor": v} for d, v in UVA.items()] if cer_ok else None)
        if "/indices/uva" in url:
            return _Resp(200 if uva_ok else 500,
                         [{"fecha": d, "valor": v} for d, v in UVA.items()])
        return _Resp(404)
    return _get


class TestElRatioUvaReproduceElCer(unittest.TestCase):
    """La equivalencia, contra la medición independiente de la auditoría."""

    def test_los_dos_grupos_de_bonos_dan_el_factor_medido(self):
        for etiqueta, (emision, factor_cer) in EMISIONES.items():
            ratio = UVA[MEDIDO_AL] / UVA[emision]
            desvio = abs(ratio - factor_cer) / factor_cer
            self.assertLess(
                desvio, 0.005,
                f"{etiqueta}: el ratio UVA ({ratio:.2f}×) no reproduce el CER "
                f"medido ({factor_cer}×) — desvío {desvio:.2%}")

    def test_sin_serie_el_factor_seria_1_que_es_el_bug(self):
        """Lo que publicaba la app: factor 1,00 donde el real es 37,44×."""
        for _etiqueta, (_emision, factor_cer) in EMISIONES.items():
            self.assertGreater(factor_cer, 7.0)   # el error no es marginal


class TestElEndpointSirveYLoDeclara(unittest.TestCase):
    """El camino de producción entero: fetcher → tabla → endpoint."""

    def setUp(self):
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        self.conn.execute("DELETE FROM bond_indices_daily")
        self.conn.commit()
        main._indices_fetched.clear()
        self.addCleanup(main._indices_fetched.clear)
        self.addCleanup(self._limpiar)

    def _limpiar(self):
        c = main.get_db()
        c.execute("DELETE FROM bond_indices_daily")
        c.commit(); c.close()

    def test_con_el_cer_en_404_el_endpoint_sirve_uva_y_lo_dice(self):
        with patch.object(main.requests, "get", side_effect=_fuente(cer_ok=False)):
            r = main.get_bond_index_series("CER", uid=1)
        self.assertEqual(r["index_name"], "CER")
        self.assertEqual(r["basis"], "UVA", "no declaró con qué serie ajustó")
        self.assertGreater(r["count"], 0, "sin serie, el factor vuelve a ser 1,00")
        self.assertFalse(r["stale"], "la UVA se acaba de bajar, no está stale")

    def test_el_factor_que_sale_del_endpoint_es_el_medido(self):
        """No alcanza con que devuelva números: tienen que ser LOS números."""
        with patch.object(main.requests, "get", side_effect=_fuente(cer_ok=False)):
            r = main.get_bond_index_series("CER", uid=1)
        serie = r["series"]
        for etiqueta, (emision, factor_cer) in EMISIONES.items():
            ratio = serie[MEDIDO_AL] / serie[emision]
            self.assertAlmostEqual(ratio, factor_cer, delta=factor_cer * 0.005,
                                   msg=f"{etiqueta} sale mal del endpoint")

    def test_si_el_cer_revive_gana_el_cer(self):
        """El fallback no puede tapar a la fuente buena cuando vuelve."""
        with patch.object(main.requests, "get", side_effect=_fuente(cer_ok=True)):
            r = main.get_bond_index_series("CER", uid=1)
        self.assertEqual(r["basis"], "CER")

    def test_si_se_caen_las_dos_no_inventa_nada(self):
        with patch.object(main.requests, "get",
                          side_effect=_fuente(cer_ok=False, uva_ok=False)):
            r = main.get_bond_index_series("CER", uid=1)
        self.assertEqual(r["count"], 0)
        self.assertEqual(r["basis"], "CER")   # no miente diciendo que usó UVA
        self.assertTrue(r["stale"])


class TestLaCaidaDejaDeSerMuda(unittest.TestCase):
    """El defecto que hizo que esto durara meses: nadie se enteraba."""

    def setUp(self):
        main._indices_fetched.clear()
        main._indices_aviso.clear()
        self.addCleanup(main._indices_fetched.clear)
        self.addCleanup(main._indices_aviso.clear)

    def test_una_fuente_vacia_loguea(self):
        conn = main.get_db()
        self.addCleanup(conn.close)
        with patch.object(main.requests, "get", side_effect=_fuente(cer_ok=False)):
            with self.assertLogs(main.log, level=logging.WARNING) as cap:
                main._ensure_index_cached(conn, "CER")
        self.assertTrue(any("CER" in m for m in cap.output),
                        "la fuente se cayó y no quedó ni una línea de log")

    def test_pero_no_grita_en_cada_request(self):
        """Un aviso que sale mil veces es ruido — así sobrevivió la caída.

        Se limita el AVISO, no el reintento: la fuente se sigue consultando en
        cada pasada (un blip se recupera enseguida), pero la línea sale una vez
        por ventana.
        """
        conn = main.get_db()
        self.addCleanup(conn.close)
        llamadas = []

        def _contando(url, **kw):
            llamadas.append(url)
            return _fuente(cer_ok=False)(url, **kw)

        # `assertNoLogs` es 3.10+; acá se cuentan las llamadas, que además dice
        # CUÁNTAS veces avisó y no sólo si avisó.
        with patch.object(main.requests, "get", side_effect=_contando), \
             patch.object(main.log, "warning") as avisos:
            main._ensure_index_cached(conn, "CER")
            self.assertEqual(avisos.call_count, 1)
            n1 = len(llamadas)

            # Segunda pasada: SÍ reintenta, NO vuelve a avisar.
            main._ensure_index_cached(conn, "CER")
            self.assertEqual(avisos.call_count, 1, "avisó dos veces seguidas")
            self.assertGreater(len(llamadas), n1, "dejó de reintentar la fuente")

            # Pasada la ventana del aviso, vuelve a avisar.
            main._indices_aviso["CER"] = 0
            main._ensure_index_cached(conn, "CER")
            self.assertEqual(avisos.call_count, 2)


class TestUnSoloFetchDeLaSerie(unittest.TestCase):
    """`_fetch_uva_monthly` y el diario pegaban al MISMO endpoint por separado."""

    def test_el_mensual_deriva_del_diario(self):
        with patch.object(main, "_fetch_uva_series", return_value=UVA) as spy:
            mensual = main._fetch_uva_monthly()
        spy.assert_called_once()
        # Un valor por mes, y es el ÚLTIMO día de ese mes.
        self.assertEqual(mensual["2020-08"], UVA["2020-08-04"])
        self.assertEqual(mensual["2026-09"], UVA["2026-09-01"])

    def test_el_mensual_no_baja_la_serie_por_su_cuenta(self):
        import inspect
        src = inspect.getsource(main._fetch_uva_monthly)
        self.assertNotIn("requests.get", src,
                         "volvió a haber dos bajadas del mismo endpoint")


if __name__ == "__main__":
    unittest.main()
