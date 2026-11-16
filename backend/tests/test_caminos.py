"""Los caminos del menú de cada broker: una sola fuente, y el servidor la sigue.

POR QUÉ EXISTE. Cómo bajar cada archivo lo dice la guía de la app (BROKER_GUIDES,
`frontend/src/components/import/BrokerInstructions.jsx`), que es la que se
corrige cuando un broker cambia su menú. El servidor tenía sus propias copias y
se habían separado sin que nada avisara: al 16/11/2026 el aviso de PPI mandaba a
«Mi cuenta → Movimientos» con la guía diciendo «Actividad → Todos los
movimientos», el de la foto de Cocos a «Inversiones → Estado de cuenta», y el
asistente le mostraba a Balanz «Mi cuenta → Resumen de cuenta» con la guía,
debajo y en la misma pantalla, diciendo «Actividad → Reportes → Posición
consolidada». Ahora el servidor los lee de `importing/caminos.py`.

Tres cosas, y por qué cada una:
  1. Cada camino de caminos.py está, letra por letra, en los pasos de su broker
     en la guía. Si alguien corrige la guía y no el servidor (o al revés), rojo.
  2. Ningún texto del servidor escribe un camino a mano. Es la que hubiera
     atrapado las copias viejas (probado contra el código de main del 16/11: se
     pone roja en los 12 lectores, los avisos de foto de PPI y Cocos, y la lista
     de fotos que mostraba el asistente).
  3. Los avisos llegan con el camino: se sube el archivo equivocado por la API,
     como lo sube la app, y se mira lo que vuelve.

Y el export de «Resultados» de Balanz: el servidor lo reconoce sólo para decir
«ese no, bajá Movimientos». Se ofrecía igual en la lista de exports (la tanda
del asesor lo mostraba como opción) y la persona elegía algo que se rechaza.
"""
import ast
import io
import os
import re
import tempfile
import unittest
import uuid

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ.setdefault("DB_PATH", _TMP.name)

import openpyxl                              # noqa: E402
from fastapi.testclient import TestClient    # noqa: E402

import main                                  # noqa: E402
from importing.caminos import EN_LA_GUIA, FUERA_DE_LA_GUIA, camino   # noqa: E402
from importing.parsers.registry import autodetect, get_parser        # noqa: E402
from tests import _guia_de_la_app as guia                            # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class CadaCaminoEstaEnLaGuia(unittest.TestCase):
    def test_la_guia_se_lee_donde_la_buscamos(self):
        # Contra el falso verde: sin pasos, el resto no compararía nada.
        pasos = guia.pasos()
        self.assertGreaterEqual(len(pasos), 10)
        self.assertTrue(all(len(v) >= 3 for v in pasos.values()), pasos)

    def test_letra_por_letra_en_los_pasos_de_su_broker(self):
        pasos = guia.pasos()
        for (gid, archivo), texto in EN_LA_GUIA.items():
            with self.subTest(guia=gid, archivo=archivo):
                self.assertIn(gid, pasos, f"no hay guía «{gid}» en BrokerInstructions.jsx")
                self.assertTrue(any(texto in p for p in pasos[gid]),
                                f"«{texto}» no está en los pasos de «{gid}» de la guía: "
                                f"¿se corrigió uno y no el otro?")

    def test_lo_de_la_foto_esta_en_el_paso_de_la_foto(self):
        # No alcanza con que esté en algún paso: el camino de la foto tiene que
        # estar en el paso que la guía marca como el de la foto.
        pasos, foto = guia.pasos(), guia.pasos_de_la_foto()
        for (gid, archivo), texto in EN_LA_GUIA.items():
            if archivo != "foto":
                continue
            with self.subTest(guia=gid):
                self.assertTrue(any(texto in pasos[gid][i] for i in foto[gid]), texto)

    def test_lo_de_afuera_de_la_guia_no_esta_en_la_guia(self):
        # FUERA_DE_LA_GUIA es para exports que la guía NO explica. Si un camino
        # de ahí aparece en la guía, va en EN_LA_GUIA (y entonces se vigila).
        todos = [p for v in guia.pasos().values() for p in v]
        for clave, texto in FUERA_DE_LA_GUIA.items():
            with self.subTest(clave=clave):
                self.assertFalse(any(texto in p for p in todos), texto)

    def test_un_nombre_mal_escrito_rompe_enseguida(self):
        with self.assertRaises(KeyError):
            camino("ppi", "movimeintos")


# ── 2. Ningún texto del servidor escribe un camino a mano ──────────────────────

_FLECHA = re.compile(r"(\S+)\s*→\s*(?=(\S+))")
_BORDES = "“”«»\"'()[],.;:¿?¡!"
_BROKER = re.compile(r"\b(PPI|Cocos|Balanz|IOL|InvertirOnline|Bull ?Market|Schwab|"
                     r"Binance|IEB|inviu)\b", re.I)


def _vocabulario():
    """De todos los caminos (guía + caminos.py): los pares «A → B» tal cual, y
    las palabras de menú (las que empiezan en mayúscula al lado de una flecha)."""
    textos = ([p for v in guia.pasos().values() for p in v]
              + list(EN_LA_GUIA.values()) + list(FUERA_DE_LA_GUIA.values()))
    pares, palabras = set(), set()
    for t in textos:
        for m in _FLECHA.finditer(t):
            a, b = (x.strip(_BORDES) for x in m.groups())
            pares.add((a.lower(), b.lower()))
            palabras.update(x.lower() for x in (a, b) if x[:1].isupper())
    return pares, palabras


def _textos_del_servidor():
    """(archivo, renglón, texto) de cada texto del código del servidor: sin
    comentarios ni docstrings (citan los caminos viejos a propósito), sin las
    pruebas ni los scripts sueltos, y sin caminos.py, que es la fuente."""
    for raiz, dirs, archivos in os.walk(BACKEND):
        dirs[:] = [d for d in dirs if d not in ("tests", "scripts", "__pycache__", "backups")]
        for nombre in archivos:
            ruta = os.path.join(raiz, nombre)
            rel = os.path.relpath(ruta, BACKEND).replace(os.sep, "/")
            if not nombre.endswith(".py") or rel == "importing/caminos.py":
                continue
            arbol = ast.parse(open(ruta, encoding="utf-8").read())
            docs = {id(n.body[0].value) for n in ast.walk(arbol)
                    if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                      ast.AsyncFunctionDef))
                    and n.body and isinstance(n.body[0], ast.Expr)
                    and isinstance(n.body[0].value, ast.Constant)}
            for n in ast.walk(arbol):
                if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                        and "→" in n.value and id(n) not in docs):
                    yield rel, n.lineno, n.value


def copias_a_mano(textos):
    """Los «A → B» que son un camino de broker escrito a mano. Dos reglas:
      · un par que está tal cual en algún camino, en cualquier texto;
      · cualquier flecha pegada a una palabra de menú de broker, en un texto que
        habla de un broker (el importador entero, o un texto que nombra uno).
        Sin esa condición confundiría los menús de la propia Rendi
        («Configuración → Mi plan», «Operaciones → Movimientos»), que repiten
        palabras de los menús de los brokers."""
    pares, palabras = _vocabulario()
    out = []
    for rel, linea, texto in textos:
        de_broker = rel.startswith("importing/") or bool(_BROKER.search(texto))
        for m in _FLECHA.finditer(texto):
            a, b = (x.strip(_BORDES).lower() for x in m.groups())
            if (a, b) in pares or (de_broker and (a in palabras or b in palabras)):
                out.append(f"{rel}:{linea}: «{m.group(1)} → {m.group(2)}» en «{texto[:90]}»")
    return out


class NingunTextoEscribeUnCaminoAMano(unittest.TestCase):
    def test_el_vocabulario_no_esta_vacio(self):
        pares, palabras = _vocabulario()
        self.assertGreater(len(pares), 15)
        for w in ("actividad", "movimientos", "cuenta", "history"):
            self.assertIn(w, palabras)

    def test_la_regla_atrapa_las_copias_que_habia(self):
        # Las copias reales del 16/11, tal como estaban: si la regla no las ve,
        # el verde de abajo no significa nada.
        viejas = [
            ("importing/parsers/ppi.py", 231,
             "Bajalo desde la web de PPI (Mi cuenta → Movimientos) en Excel."),
            ("main.py", 46544, "Este CSV no parece el Estado de Cuenta de Cocos "
                               "(Inversiones → Estado de cuenta → Exportar)."),
            ("importing/pipeline.py", 2113, "Inversiones → Estado de cuenta → Exportar"),
            ("importing/pipeline.py", 2119, "Tenencias → Exportar (Excel)"),
            ("importing/parsers/binance_transaction.py", 119,
             "Asset History → Transaction History (completo)"),
        ]
        for v in viejas:
            with self.subTest(texto=v[2]):
                self.assertTrue(copias_a_mano([v]), v)

    def test_y_deja_pasar_los_menus_de_rendi(self):
        propios = [
            ("billing/emails.py", 1, "Podés cancelar cuando quieras desde Configuración → Mi plan."),
            ("main.py", 1, "o desde la app (Operaciones → Movimientos)."),
            ("importing/validator.py", 1, "Creálo en Configuración → Brokers."),
            ("importing/preview.py", 1, "Conversión ARS → USD"),
        ]
        self.assertEqual(copias_a_mano(propios), [])

    def test_ningun_texto_del_servidor_copia_un_camino(self):
        textos = list(_textos_del_servidor())
        self.assertGreater(len(textos), 50)   # contra el falso verde
        self.assertEqual(copias_a_mano(textos), [],
                         "camino escrito a mano: leelo de importing/caminos.py")


# ── 3. Los avisos llegan con el camino, por el mismo camino que la app ─────────

class _Cuenta:
    def __init__(self):
        self.c = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?, 'x', 1, 1)", (f"caminos-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def movimientos(self, formato, contenido, nombre="x.csv", tipo="text/csv"):
        return self.c.post("/api/imports/preview", headers=self.h,
                           files=[("files", (nombre, contenido, tipo))],
                           data={"format": formato})

    def foto(self, formato, contenido, nombre, tipo):
        return self.c.post("/api/imports/tenencia/preview", headers=self.h,
                           data={"broker": "X", "format": formato},
                           files={"file": (nombre, contenido, tipo)})


def _xlsx_cualquiera():
    wb = openpyxl.Workbook()
    wb.active.append(["Fecha", "Concepto", "Importe"])
    wb.active.append(["2026-11-01", "algo", 10])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_CSV_CUALQUIERA = b"Fecha,Concepto,Importe\n2026-11-01,algo,10\n"


class LosAvisosNombranElCaminoDeLaGuia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cuenta = _Cuenta()

    def test_archivo_equivocado_de_movimientos(self):
        casos = [
            ("cocos", ("cocos", "movimientos")),
            ("iol", ("iol", "movimientos")),
            ("ppi", ("ppi", "movimientos")),
            ("balanz_movimientos", ("balanz", "movimientos")),
            ("balanz_internacional", ("balanz_internacional", "movimientos")),
            ("bullmarket", ("bullmarket", "movimientos")),
            ("schwab", ("schwab", "movimientos")),
        ]
        for formato, clave in casos:
            with self.subTest(formato=formato):
                r = self.cuenta.movimientos(formato, _CSV_CUALQUIERA)
                self.assertEqual(r.status_code, 400, r.text)
                self.assertIn(camino(*clave), r.json()["detail"])

    def test_foto_equivocada_de_cocos(self):
        r = self.cuenta.foto("cocos", _CSV_CUALQUIERA, "EstadoDeCuenta.csv", "text/csv")
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn(camino("cocos", "foto"), r.json()["detail"])

    def test_foto_equivocada_de_ppi(self):
        r = self.cuenta.foto("ppi", _xlsx_cualquiera(), "EstadoDeCuenta.xlsx", XLSX)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn(camino("ppi", "foto"), r.json()["detail"])


class ResultadosDeBalanzNoSeOfrece(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cuenta = _Cuenta()

    def test_no_esta_en_la_lista_de_exports(self):
        r = self.cuenta.c.get("/api/imports/parsers/grouped", headers=self.cuenta.h)
        self.assertEqual(r.status_code, 200, r.text)
        balanz = next(g for g in r.json() if g["platform"] == "balanz")
        ids = [e["id"] for e in balanz["exports"]]
        self.assertNotIn("balanz_resultados", ids)
        self.assertIn("balanz_movimientos", ids)   # y el bueno sigue

    def test_la_lista_ya_no_manda_donde_bajar_la_foto(self):
        # Eso lo dice la guía de la app; la copia del servidor se fue.
        r = self.cuenta.c.get("/api/imports/parsers/grouped", headers=self.cuenta.h)
        for g in r.json():
            self.assertNotIn("tenencia_label", g, g["platform"])

    def test_pero_se_sigue_reconociendo_para_redirigir(self):
        # Si alguien lo sube igual (un cliente viejo que todavía lo ofrece), el
        # aviso le dice qué bajar en su lugar, con el camino de la guía.
        plantilla = get_parser("balanz_resultados").template_csv()
        headers = plantilla.splitlines()[0].split(",")
        self.assertEqual(autodetect(headers).format_id, "balanz_resultados")
        r = self.cuenta.movimientos("balanz_resultados", plantilla.encode())
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("Resultados", r.json()["detail"])
        self.assertIn(camino("balanz", "movimientos"), r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
