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


class LoQuePERSISTEUsaElDiaArgentino(unittest.TestCase):
    """Los tres relojes que escribían o validaban filas de verdad.

    El "hoy" mal calculado duele distinto según dónde esté. En una pantalla se
    corrige el día que se toca el código; en una fila persistida queda. Estos
    tres escriben:

      · el guard de fecha futura del cobro — el que existe porque un usuario
        cargó 25 cupones de AL35 fechados en 2027 y metió US$ 3,9M fantasma;
      · el default de fecha y el guard de `register_trade`, o sea lo que el
        chat de la IA persiste cuando alguien dicta una operación;
      · el "HOY es …" del prompt, con el que el modelo resuelve "ayer".

    Y estaban escritos con DOS relojes distintos para la MISMA regla:
    `date.today()` en uno y `datetime.utcnow()` en el otro. De 21:00 a 23:59 ART
    los dos ya están en mañana, así que el guard aceptaba justamente las fechas
    futuras que existe para frenar — en la misma franja en la que el frontend las
    ofrecía por defecto.
    """

    def test_el_prompt_de_la_ia_recibe_el_dia_argentino(self):
        import re
        ruta = os.path.join(BACKEND, "main.py")
        with open(ruta, encoding="utf-8") as fh:
            txt = fh.read()
        m = re.search(r'_today_line = f"HOY es \{([^}]+)\}\."', txt)
        self.assertIsNotNone(m, "no encontré la línea `HOY es` del prompt")
        self.assertIn("_iso_today", m.group(1),
                      "el modelo resuelve 'ayer' con esto y después lo escribe")

    def test_los_guards_de_fecha_futura_usan_el_mismo_reloj(self):
        """Dos guards para la misma regla no pueden decidir con relojes distintos."""
        import re
        ruta = os.path.join(BACKEND, "main.py")
        with open(ruta, encoding="utf-8") as fh:
            lineas = fh.readlines()
        sospechosas = [
            f"main.py:{n}: {l.strip()}"
            for n, l in enumerate(lineas, 1)
            if re.search(r"(>|>=)\s*(date\.today\(\)\.isoformat\(\)"
                         r"|datetime\.utcnow\(\)\.strftime)", l)
        ]
        self.assertEqual(
            sospechosas, [],
            "Un guard de fecha futura decidiendo con un reloj que no es el "
            "argentino. Usá `_iso_today()`:\n  " + "\n  ".join(sospechosas))



# ─── "Hoy" sacado del reloj crudo: la lista sólo puede achicarse ─────────────
# `date.today()` es la hora del PROCESO (UTC en Railway, ART en una Mac) y
# `utcnow().date()` es el día UTC: de 21 a 24 h argentinas los dos ya dicen
# mañana. El relevamiento del 18/10/2026 los clasificó uno por uno; la tanda 1
# (los que ESCRIBEN datos: contabilidad mensual, reconstrucción, foto del import,
# tenencia sin fecha) ya pasó a `fechas`. Lo que queda está anotado acá con
# cuántos tiene cada archivo: los UTC a propósito (cripto, cuota de IA) y la
# deuda de las tandas 2 y 3 (IA, CSV, admin, barridos de bonos).
#
# Si este test se pone rojo porque SUBIÓ un número o apareció un archivo: usá
# `fechas.hoy_art()` / `hoy_art_date()`. Si BAJÓ: bajalo acá también, así la
# lista no esconde nada. Es un guard por TEXTO y tiene puntos ciegos: no ve
# `now = datetime.utcnow()` seguido de `now.month` (así se escondían los tres de
# la contabilidad mensual). Para esos está `test_mes_argentino_contabilidad.py`,
# que congela el reloj y mira el resultado.
DIA_DEL_RELOJ_CRUDO = re.compile(
    r"utcnow\(\)\.date\(\)"
    r"|(?<![\w.])_?date\.today\(\)"
    r"|\.now\(\)\.date\(\)"
    r"|\.now\(\)\.strftime\(\s*['\"]%Y-%m")

PENDIENTES = {
    # (b) UTC a propósito — la cuota se mueve entera o no se mueve (main.py:~29990)
    "ai/quota.py": 11,
    "billing/trial.py": 2,          # paso a Plus (día UTC del alta) + piso de cuota
    "home/market.py": 1,            # cripto: velas diarias en días UTC
    # main.py: 1 cripto (`hoy_utc` de la cartera de hoy) + 4 nombres de CSV
    # + diagnóstico admin de Reportes + benchmarks y detalle mensual del chat
    "main.py": 8,
    # (a) deuda de las tandas 2 y 3
    "ai/builders/dashboard_top_holdings.py": 1,
    "ai/builders/goal.py": 1,
    "ai/builders/insights.py": 1,
    "ai/builders/insights_benchmarks.py": 1,
    "ai/builders/insights_evolution.py": 1,
    "ai/builders/news.py": 1,
    "ai/builders/news_item.py": 1,
    "ai/builders/position.py": 1,
    "ai/builders/reports.py": 1,
    "importing/maturity.py": 1,
    "importing/recompute_backfill.py": 1,
    "scripts/backfill_bond_amortizations.py": 1,
    # (c) no deciden nada del usuario
    "iol_api.py": 1,
    "scripts/iol_spike.py": 1,
    "scripts/seed_f1.py": 1,
    "scripts/backfill_historical_mtm.py": 1,   # clave de la caché mensual de precios
}


def _sin_comentarios_ni_textos(fuente):
    """`fuente` con los comentarios y los strings en blanco (los docstrings que
    explican arreglos viejos nombran `date.today()` y no son llamadas). Se
    blanquean en su lugar —no se borran— para que el resto quede como estaba."""
    import io
    import tokenize
    lineas = [list(l) for l in fuente.splitlines(True)]
    for tok in tokenize.generate_tokens(io.StringIO(fuente).readline):
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        (f0, c0), (f1, c1) = tok.start, tok.end
        for f in range(f0, f1 + 1):
            fila = lineas[f - 1]
            desde = c0 if f == f0 else 0
            hasta = c1 if f == f1 else len(fila)
            for c in range(desde, hasta):
                if fila[c] != "\n":
                    fila[c] = " "
    return "".join("".join(l) for l in lineas)


def _codigo_sin_comentarios_ni_textos(ruta):
    with open(ruta, encoding="utf-8") as fh:
        return _sin_comentarios_ni_textos(fh.read())


class ElDiaNoSaleDelRelojCrudo(unittest.TestCase):

    def test_nadie_nuevo_saca_el_dia_del_reloj_crudo(self):
        encontrados = {}
        for raiz, dirs, files in os.walk(BACKEND):
            dirs[:] = [d for d in dirs
                       if d not in ("tests", "backups", "__pycache__", "venv", ".venv")]
            for f in files:
                if not f.endswith(".py") or f == DUENIO_DEL_CALENDARIO:
                    continue
                ruta = os.path.join(raiz, f)
                if os.path.basename(ruta).startswith("zz_sonda"):
                    continue    # archivos temporales de otras pruebas guardianas
                n = len(DIA_DEL_RELOJ_CRUDO.findall(_codigo_sin_comentarios_ni_textos(ruta)))
                if n:
                    encontrados[os.path.relpath(ruta, BACKEND)] = n
        diferencias = {
            ruta: f"anotados {PENDIENTES.get(ruta, 0)}, hay {encontrados.get(ruta, 0)}"
            for ruta in set(encontrados) | set(PENDIENTES)
            if encontrados.get(ruta, 0) != PENDIENTES.get(ruta, 0)
        }
        self.assertEqual(
            diferencias, {},
            "Cambió cuántos lugares sacan el día del reloj crudo. Si subió: usá "
            "`fechas.hoy_art()` / `hoy_art_date()`. Si bajó: actualizá PENDIENTES.")

    def test_la_reconstruccion_y_su_huella_usan_el_mismo_dia(self):
        """`_reconstruir_mtm` escribe la huella con un día y `_cuentas_que_cambiaron`
        la compara con otro: si no son el MISMO, de 21 a 24 del último día del mes
        nunca coinciden y cada aviso del Dashboard pide una reconstrucción entera."""
        import inspect
        import main
        for fn in (main._reconstruir_mtm, main._cuentas_que_cambiaron):
            fuente = _sin_comentarios_ni_textos(inspect.getsource(fn))
            self.assertIn("hoy_art_date()", fuente, fn.__name__)
            self.assertNotIn("utcnow", fuente, fn.__name__)


if __name__ == "__main__":
    unittest.main()
