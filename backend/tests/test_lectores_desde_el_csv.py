"""Los lectores dicen lo mismo que el motor (auditoría 2026-10-27, fase C — H7).

Por el camino de producción (subida HTTP de Balanz, foto, cron, endpoints) con el
mercado inventado de la auditoría, donde el rendimiento de cada año se conoce exacto.

Lo que estaba roto, medido con el código anterior:
  · el Wrapped 2025 y la IA de Reportes le pedían al motor el año "desde el 1 de
    enero": el motor arrancaba en el primer punto de enero (el 31) y se comía el
    mes. Wrapped 2025: 29,0 % con la verdad en 40,2 % (Reportes ya arrancaba en el
    cierre del 31/12; ahora los tres usan `reporting.builder.inicio_de_ventana`);
  · en modo Certero, sin medición del año, `rendimiento_publicable` caía a la
    contabilidad: el Wrapped publicaba +0,0 % (escenario S1) donde no hay número.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import twr  # noqa: E402
from tests.test_rendimiento_desde_el_csv import _Inversor  # noqa: E402


class LosLectoresDelAnio(_Inversor):

    def _modo(self, c, modo):
        conn = main.get_db()
        with conn:
            conn.execute("UPDATE users SET modo_rendimiento=? WHERE id=?", (modo, c.uid))
        conn.close()

    def _ia_reportes(self, c, year):
        from ai.builders.reports import build
        conn = main.get_db()
        try:
            return build(conn, c.uid, year=year)
        finally:
            conn.close()

    def test_el_anio_arranca_en_el_cierre_del_anterior(self):
        c, h = self.cuenta("balanz")
        verdad = h.twr_verdad("2024-12-31", "2025-12-31")
        for modo in ("certero", "estimado"):
            with self.subTest(modo=modo):
                self._modo(c, modo)
                r = c.http.get("/api/wrapped/2025", headers=c.h)
                self.assertEqual(r.status_code, 200, r.text)
                w = r.json()["summary"]["twr"]
                self.assertIsNotNone(w)
                self.assertLess(abs(w * 100 - verdad), 0.5, (w, verdad))
                # La IA de Reportes dice lo mismo, sobre la misma ventana.
                ia = self._ia_reportes(c, 2025)
                self.assertAlmostEqual(ia["twr_year_pct"], round(w * 100, 2), places=1)

    def test_la_ia_compara_contra_el_sp_en_la_ventana_del_numero(self):
        """`vs_sp500_pp` era el promedio de "mes del usuario − mes del S&P" con una
        fórmula propia, sobre meses que podían ser contables. Ahora es el número del
        año menos el S&P entre las MISMAS dos fechas (`performance.bench_pct_entre`)."""
        from unittest import mock
        import performance
        c, _ = self.cuenta("balanz")
        sp = {"2024-12": 100.0, **{f"2025-{m:02d}": 100.0 + 2 * m for m in range(1, 13)}}
        with mock.patch.dict(main._bench_cache, {"data": {"sp500": sp}}):
            ia = self._ia_reportes(c, 2025)
            esperado = round(ia["twr_year_pct"] - performance.bench_pct_entre(
                {"sp500": sp}, "sp500", "2024-12-31", "2025-12-31"), 2)
        self.assertEqual(ia["vs_sp500_pp"], esperado)

    def test_en_certero_ninguno_publica_la_contabilidad(self):
        """S1: el archivo arranca en 2025 y la foto lo desmiente; en Certero, 2025 no
        tiene ninguna medición. Antes: Wrapped +0,0 % (contable)."""
        c, _ = self.cuenta("balanz", omitir=lambda e: e.fecha < "2025-01-01")
        self._modo(c, "certero")
        r = c.http.get("/api/wrapped/2025", headers=c.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json()["summary"]["twr"])
        conn = main.get_db()
        try:
            for desde, hasta in (("2025-01-01", "2025-12-31"), (None, None)):
                rp = twr.rendimiento_publicable(conn, c.uid, desde=desde, hasta=hasta,
                                                periodo=bool(desde))
                self.assertNotEqual(rp["base"], "contable", (desde, rp))
        finally:
            conn.close()
        ia = self._ia_reportes(c, 2025)
        self.assertIsNone(ia["twr_year_pct"])
        self.assertIsNotNone(ia["twr_year_motivo_texto"])
        # Y el mejor y el peor mes tampoco salen de la contabilidad (antes: +8,0 %
        # y −0,99 % con `months_base: 'contable'` en modo Certero).
        self.assertNotEqual(ia["months_base"], "contable")
        self.assertIsNone(ia["best_month"])
        # Reportes del año: sin número y diciendo por qué.
        r = c.http.get("/api/reports/period/year/2025", headers=c.h)
        if r.status_code == 200:              # 2025 es de plan pago; 2026 es libre
            self.assertIsNone(r.json()["metrics"]["delta_pct"])
        m = c.http.get("/api/reports/period/year/2026", headers=c.h).json()["metrics"]
        self.assertTrue(m["delta_pct"] is None or m["basis"] == "mercado", m)
        if m["delta_pct"] is None:
            self.assertTrue(m["motor_motivo_texto"], m)


if __name__ == "__main__":
    unittest.main()
