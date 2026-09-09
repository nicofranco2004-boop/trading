"""Hoy se calcula en UN solo lugar. Este guard lee CÓDIGO, no números.

CONTEXTO. La auditoría 1B (fechas y zonas horarias) encontró tres calendarios
corriendo a la vez dentro de la misma app: ART (`utcnow() - 3h`), UTC (`utcnow()`)
y hora local del proceso (`date.today()`, que en Railway es UTC y en una Mac
argentina es ART). Ninguno está mal en sí mismo; el problema es que convivían
dentro del mismo endpoint.

EL BUG DE FONDO, que es de propagación y no de aritmética. La conversión a ART
estaba escrita NUEVE veces, copiada a mano en nueve archivos distintos:

    main.py::_iso_today · advisor_brief::_today_art · advisor_alerts::_today_art
    advisor_alerts (el piso de 4 días) · twr::_hoy_art · ledger_replay
    importing/proyeccion · main (informe firmado, ×2) · snapshots_job

Cuando el mismo cálculo vive en nueve lugares, arreglar uno no arregla nada: es
exactamente la causa raíz que la auditoría midió como la más frecuente del repo.
Y de hecho pasó — `snapshots_job` tenía la conversión escrita y muerta mientras el
runner de al lado fechaba en UTC.

QUÉ VERIFICA ESTE ARCHIVO
  1. Que la definición de "hoy ART" no vuelva a copiarse: ningún módulo de
     producción resta 3 horas a mano. La única resta permitida vive en
     `backend/fechas.py`, que es el dueño del calendario.
  2. Que ese dueño realmente devuelva el día argentino, con el reloj congelado en
     el caso que motivó todo: 02:59 UTC del sábado = 23:59 ART del viernes.

POR QUÉ UN GUARD DE CÓDIGO Y NO UNO DE NÚMEROS. Un test de comportamiento sobre
`hoy_art()` pasa igual aunque mañana alguien escriba una décima copia en otro
archivo — y esa décima copia es el bug. Lo que hay que impedir es la copia.

Corre con: cd backend && python3 -m pytest tests/test_un_solo_calendario.py
"""
import ast
import os
import re
import unittest
from datetime import datetime
from unittest.mock import patch

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# El único archivo que tiene derecho a saber cuántas horas son.
DUENIO_DEL_CALENDARIO = "fechas.py"

# Carpetas que no son código de producción.
EXCLUIDAS = ("tests", "scripts", "backups", "__pycache__", "venv", ".venv")

# La resta a mano, en cualquiera de las formas en que estaba escrita:
#   timedelta(hours=3) · _td(hours=3) · timedelta(hours=ART_OFFSET...)
RESTA_A_MANO = re.compile(r"\bhours\s*=\s*3\b")


def _fuentes_de_produccion():
    for raiz, dirs, files in os.walk(BACKEND):
        dirs[:] = [d for d in dirs if d not in EXCLUIDAS]
        for f in files:
            if f.endswith(".py") and f != DUENIO_DEL_CALENDARIO:
                yield os.path.join(raiz, f)


class HoySeCalculaEnUnSoloLugar(unittest.TestCase):

    def test_ningun_modulo_de_produccion_resta_tres_horas_a_mano(self):
        """La décima copia de `utcnow() - 3h` no entra.

        Si este test se pone en rojo por un archivo nuevo: no le agregues una
        excepción. Importá `from fechas import hoy_art` y usalo. Ese es el
        punto entero de la tanda F3.
        """
        culpables = []
        for ruta in _fuentes_de_produccion():
            with open(ruta, encoding="utf-8") as fh:
                for nro, linea in enumerate(fh, 1):
                    if RESTA_A_MANO.search(linea):
                        rel = os.path.relpath(ruta, BACKEND)
                        culpables.append(f"{rel}:{nro}: {linea.strip()}")
        self.assertEqual(
            culpables, [],
            "Hay código de producción calculando la hora argentina por su cuenta.\n"
            "Usá `from fechas import hoy_art` (o `hoy_art_date`):\n  "
            + "\n  ".join(culpables))

    def test_fechas_py_no_importa_nada_del_repo(self):
        """El dueño del calendario tiene que poder importarse desde cualquier lado.

        Si `fechas.py` importara `main` o `twr`, la mitad de los módulos no podría
        usarlo sin un ciclo de imports, y volveríamos a las copias a mano.
        """
        ruta = os.path.join(BACKEND, DUENIO_DEL_CALENDARIO)
        with open(ruta, encoding="utf-8") as fh:
            arbol = ast.parse(fh.read())
        modulos = []
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                modulos += [a.name for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                modulos.append(nodo.module)
        externos = [m for m in modulos if m.split(".")[0] != "datetime"]
        self.assertEqual(externos, [],
                         f"fechas.py sólo puede importar `datetime`; importa {externos}")


class ElDueniyoDevuelveElDiaArgentino(unittest.TestCase):

    def test_a_las_2359_de_un_viernes_argentino_hoy_es_ese_viernes(self):
        """El caso exacto que corrió la serie de snapshots un día entero.

        El cron corre a las 02:59 UTC *a propósito*, porque eso es la medianoche
        argentina. A esa hora `utcnow()` ya dice sábado y el día que el usuario
        acaba de terminar de vivir es el viernes.
        """
        import fechas
        # sábado 2026-09-05, 02:59 UTC  =  viernes 2026-09-04, 23:59 ART
        with patch("fechas.datetime") as reloj:
            reloj.utcnow.return_value = datetime(2026, 9, 5, 2, 59, 0)
            self.assertEqual(fechas.hoy_art(), "2026-09-04")
            self.assertEqual(fechas.hoy_art_date().isoformat(), "2026-09-04")

    def test_a_media_maniana_argentina_hoy_es_hoy(self):
        """Control: fuera de la franja de las 21 a las 24, los dos relojes coinciden."""
        import fechas
        with patch("fechas.datetime") as reloj:
            reloj.utcnow.return_value = datetime(2026, 9, 5, 13, 0, 0)  # 10:00 ART
            self.assertEqual(fechas.hoy_art(), "2026-09-05")

    def test_los_alias_de_los_modulos_devuelven_lo_mismo_que_el_canonico(self):
        """`_iso_today`, `_today_art` y `_hoy_art` son nombres, no definiciones."""
        import fechas
        import twr
        import advisor_brief
        import advisor_alerts
        esperado = fechas.hoy_art()
        self.assertEqual(twr._hoy_art(), esperado)
        self.assertEqual(advisor_brief._today_art(), esperado)
        self.assertEqual(advisor_alerts._today_art(), esperado)


class ElPeriodoEnCursoTerminaCuandoTerminaEnArgentina(unittest.TestCase):
    """`is_period_current` decidía en UTC — con un comentario que afirmaba lo
    contrario.

    El comentario decía textual *"usar UTC para consistencia con `_iso_today()`"*,
    y `_iso_today()` es ART. La consecuencia era la opuesta a la buscada: de
    21:00 a 23:59 hora argentina `utcnow()` ya es el día siguiente, así que el
    mes y el año se marcaban como CERRADOS tres horas antes de terminar. Eso
    cambia de rama el guard `basis_incomparable` y apaga el valor live del
    período en curso justo en la franja de mayor uso de la app.
    """

    def test_a_las_2200_del_31_de_agosto_agosto_sigue_en_curso(self):
        import fechas
        from reporting.builder import is_period_current
        # 01:00 UTC del 1 de septiembre = 22:00 ART del 31 de agosto.
        with patch("fechas.datetime") as reloj:
            reloj.utcnow.return_value = datetime(2026, 9, 1, 1, 0, 0)
            self.assertTrue(is_period_current("month", "2026-08-01", "2026-08-31"))

    def test_a_las_2200_del_31_de_diciembre_el_anio_sigue_en_curso(self):
        """Un año PASADO a propósito: si el reloj no se respeta, el test no
        discrimina — con `utcnow()` real el año en curso da True igual y el
        rojo no aparece nunca."""
        import fechas
        from reporting.builder import is_period_current
        # 01:00 UTC del 1 de enero de 2026 = 22:00 ART del 31 de diciembre de 2025.
        with patch("fechas.datetime") as reloj:
            reloj.utcnow.return_value = datetime(2026, 1, 1, 1, 0, 0)
            self.assertTrue(is_period_current("year", "2025-01-01", "2025-12-31"))

    def test_y_a_la_maniana_siguiente_ya_esta_cerrado(self):
        """Control: el guard cierra el período, sólo que en el momento correcto."""
        import fechas
        from reporting.builder import is_period_current
        with patch("fechas.datetime") as reloj:
            reloj.utcnow.return_value = datetime(2026, 9, 1, 13, 0, 0)  # 10:00 ART
            self.assertFalse(is_period_current("month", "2026-08-01", "2026-08-31"))

    def test_un_today_explicito_sigue_mandando(self):
        """Los tests del repo fijan `today=` para no depender del reloj real."""
        from datetime import date
        from reporting.builder import is_period_current
        self.assertTrue(is_period_current(
            "month", "2026-08-01", "2026-08-31", today=date(2026, 8, 16)))


if __name__ == "__main__":
    unittest.main()
