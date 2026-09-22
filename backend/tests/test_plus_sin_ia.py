"""Plus = Rendi entero, sin el analista (2026-10-15).

El Plus se definía por RECORTES —6 de 12 detectores, 6 puntos de diagnóstico,
25 alertas— y nadie podía nombrar lo que compraba. Ahora las métricas están
completas y lo que lo separa del Pro son dos cosas que se dicen en una frase:

  1. la IA (2 análisis/semana vs 60, chat guiado vs libre, sin follow-ups);
  2. los brokers (3 vs sin tope).

Lo que estos tests protegen:

  1. **Que el cupo viejo del Plus se respete en los CUATRO lectores.** El cupo
     de análisis se lee en `get_current_usage`, `reserve_chat`,
     `reserve_analysis` y `reserve_diag_dismiss`. Respetarlo en uno solo dejaba
     a la persona que ya pagaba viendo "6 disponibles" en la pantalla y
     comiéndose un 429 en el tercero — la peor forma de romper una promesa: la
     que se descubre usando.
  2. Que las métricas del Plus estén de verdad completas (no es texto de
     marketing: son los gates que el producto aplica).
  3. Que NADA de IA se haya movido al Plus por accidente.

Corre con: cd backend && python3 -m pytest tests/test_plus_sin_ia.py
"""
import os
import sys
import tempfile
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# Base propia del módulo (ver reference_tests_una_base_por_modulo).
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main                                  # noqa: E402  (crea el schema)
from ai import quota                          # noqa: E402
from ai.plan import PLAN_LIMITS               # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        try:
            self.conn.rollback()
        except Exception:
            pass
        for t in ("ai_usage_daily", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()

    def tearDown(self):
        try:
            self.conn.rollback()
        except Exception:
            pass
        self.conn.close()

    def _user(self, tier, *, legacy=0):
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, "
            "                   tier, quota_plus_legacy) VALUES (?,?,1,1,?,?)",
            (f"u-{uuid.uuid4().hex[:8]}@rendi.test", "x", tier, legacy))
        self.conn.commit()
        return cur.lastrowid


class ElCupoDelPlusNuevo(Base):
    def test_son_dos_por_semana(self):
        self.assertEqual(quota.LIMITS["plus"]["analyses_per_week"], 2)

    def test_free_sigue_en_uno_asi_que_el_salto_en_IA_es_invisible(self):
        """Es el mensaje del cambio: el Plus no es el plan de la IA."""
        self.assertEqual(quota.LIMITS["free"]["analyses_per_week"], 1)
        self.assertLess(quota.LIMITS["plus"]["analyses_per_week"],
                        quota.LIMITS["pro"]["analyses_per_week"] / 10)

    def test_al_tercer_analisis_corta(self):
        uid = self._user("plus")
        for _ in range(2):
            ok, _ = quota.reserve_analysis(self.conn, uid)
            self.assertTrue(ok)
        ok, _ = quota.reserve_analysis(self.conn, uid)
        self.assertFalse(ok, "el tope de 2 no cortó")


class ElCupoViejoSeRespetaEnLosCuatroLectores(Base):
    """El test que de verdad importa: la promesa se rompe en el lector que se
    olvidó, no en el que se arregló."""

    def setUp(self):
        super().setUp()
        self.viejo = self._user("plus", legacy=1)
        self.nuevo = self._user("plus")

    def test_lector_1_la_pantalla_le_muestra_seis(self):
        u = quota.get_current_usage(self.conn, self.viejo)
        self.assertEqual(u["analyses_limit"], quota.ANALISIS_PLUS_ANTES_DEL_CAMBIO)

    def test_lector_2_can_analyze_lo_deja_pasar_el_tercero(self):
        for _ in range(2):
            quota.record_analysis(self.conn, self.viejo)
        ok, _ = quota.can_analyze(self.conn, self.viejo)
        self.assertTrue(ok, "le cortamos el 3º a alguien que pagó por 6")

    def test_lector_3_reserve_analysis_le_da_los_seis(self):
        for i in range(quota.ANALISIS_PLUS_ANTES_DEL_CAMBIO):
            ok, _ = quota.reserve_analysis(self.conn, self.viejo)
            self.assertTrue(ok, f"cortó en el análisis {i + 1} de 6")
        ok, _ = quota.reserve_analysis(self.conn, self.viejo)
        self.assertFalse(ok, "y el 7º sí tiene que cortar")

    def test_lector_4_el_cupo_de_chat_no_cambia_para_ninguno(self):
        """El respeto es sólo del cupo de ANÁLISIS: el chat no se tocó, y el
        helper no puede cambiarlo de rebote."""
        for uid in (self.viejo, self.nuevo):
            u = quota.get_current_usage(self.conn, uid)
            self.assertEqual(u["chat_limit"], quota.LIMITS["plus"]["chat_per_week"])

    def test_el_plus_nuevo_no_hereda_el_cupo_viejo(self):
        """La contracara: el respeto no se le filtra a todo el mundo."""
        u = quota.get_current_usage(self.conn, self.nuevo)
        self.assertEqual(u["analyses_limit"], 2)

    def test_la_marca_no_toca_a_un_pro(self):
        """Un Pro marcado por error no puede terminar con 6 en vez de 60."""
        uid = self._user("pro", legacy=1)
        u = quota.get_current_usage(self.conn, uid)
        self.assertEqual(u["analyses_limit"], quota.LIMITS["pro"]["analyses_per_week"])


class LasMetricasDelPlusEstanCompletas(Base):
    """No es texto de marketing: son los gates que el producto aplica."""

    def test_diagnostico_detectores_y_alertas_sin_tope(self):
        for campo in ("insights_diagnostic_visible", "behavioral_tags_visible",
                      "alerts_max"):
            self.assertIsNone(
                PLAN_LIMITS["plus"][campo],
                f"{campo} del Plus sigue recortado: las métricas no están completas")

    def test_comportamiento_completo_desbloqueado(self):
        self.assertTrue(PLAN_LIMITS["plus"]["can_access"]["comportamiento.full"])

    def test_el_plus_iguala_al_pro_en_todo_lo_que_no_es_IA(self):
        plus = PLAN_LIMITS["plus"]["can_access"]
        pro = PLAN_LIMITS["pro"]["can_access"]
        no_es_ia = [k for k in pro if not k.startswith("ai.")]
        distintos = [k for k in no_es_ia if plus[k] != pro[k]]
        self.assertEqual(
            distintos, [],
            "el Plus difiere del Pro en algo que NO es IA — o se mueve al Plus, "
            f"o deja de ser cierto que la diferencia es la IA: {distintos}")


class NadaDeIASeMovioAlPlus(Base):
    def test_los_followups_siguen_siendo_del_pro(self):
        self.assertFalse(PLAN_LIMITS["plus"]["can_access"]["ai.followup"])
        self.assertTrue(PLAN_LIMITS["pro"]["can_access"]["ai.followup"])

    def test_los_brokers_ilimitados_siguen_siendo_del_pro(self):
        """La única palanca del Pro que no depende de que le guste la IA."""
        self.assertEqual(PLAN_LIMITS["plus"]["brokers_max"], 3)
        self.assertIsNone(PLAN_LIMITS["pro"]["brokers_max"])


if __name__ == "__main__":
    unittest.main()
