"""Ninguna ruta del servidor puede quedar TAPADA por otra declarada antes.

EL BUG (visto el 2026-10-10, reproducido por HTTP). El servidor atiende cada pedido
con la PRIMERA ruta que coincide, en el orden en que están escritas en main.py. La
ruta del detalle de un import (`GET /api/imports/{batch_id}`) estaba escrita antes
que la de las plantillas guardadas (`GET /api/imports/mappings`), y `{batch_id}`
coincide con cualquier palabra: pedir las plantillas buscaba un import llamado
"mappings" y contestaba 404 "Batch no encontrado". La pantalla se tragaba el error y
mostraba una lista vacía. Las plantillas de columnas del importador no volvieron a
aparecer nunca, desde el día en que se agregaron (2026-05-08).

CÓMO SE REVISA. No se lee el texto de main.py: se recorre la tabla REAL de rutas de
la app (la misma que usa para atender, con todo lo que se le haya sumado por otro
lado). Para cada ruta se arma un pedido que esa ruta tendría que atender —cada
`{parámetro}` con un valor de su tipo— y se pregunta cuál es la primera ruta de la
tabla que lo agarra. Si no es ella misma, está tapada. Eso encuentra la ruta fija
escrita después de una con parámetro, la ruta con parámetro escrita después de otra
más ancha, y la misma ruta escrita dos veces.

EL INSTRUMENTO SE REVISA con casos plantados (apps chicas armadas en el test):
  · el orden mal tiene que aparecer, y el orden bien no;
  · en ese caso, un pedido de verdad tiene que caer en la ruta equivocada (si un día
    el servidor deja de atender con "la primera que coincide", el detector estaría
    midiendo otra cosa: este control lo avisa);
  · cada rama del detector tiene su caso: la ruta con parámetro tapada por otra, la
    que se tapa sólo en UNO de sus métodos, el parámetro con tipo (`{id:int}`), el
    tramo que mezcla texto y parámetro, y la ruta de un tipo que no se sabe revisar
    (un WebSocket, una carpeta montada), que hace fallar el test en vez de pasar sin
    que nadie la mire.

Y EL CRUCE (auditoría 2026-10-11): dos rutas donde cada una tiene un `{parámetro}`
justo donde la otra tiene una palabra fija — `POST /cosas/{cosa_id}/revertir` y
`POST /cosas/plantillas/{nombre}`. Ninguna tapa entera a la otra, pero hay UN pedido
(`POST /cosas/plantillas/revertir`) que las dos podrían atender y se lo queda la
primera. `rutas_que_se_cruzan` arma ese pedido para cada par y lo prueba. (En la app
hay dos pares con esa forma, `/imports/{batch_id}/revert` y `/imports/{batch_id}/redo`
contra `/imports/mappings/{mid}`, pero aquéllas son POST y ésta DELETE: no comparten
ningún pedido.)

LÍMITE. Con un parámetro de tipo acotado en la ruta misma (`{id:int}`), una ruta
puede tapar a otra sólo para ALGUNOS valores; acá se prueba un valor por parámetro.
Hoy ninguna ruta de la app usa parámetros acotados así, y si aparece una el test
falla y pide ampliar el control antes de sumarla. Y el cruce se arma tramo por
tramo con UN texto de muestra: entre dos tramos que mezclan texto y parámetro de
maneras distintas (`{a}.mp3` contra `voz-{b}`) no encuentra el pedido que comparten
(hoy la app tiene un solo tramo así, `/api/ai/voz/{key}.mp3`).

Corre con: cd backend && python3 -m pytest tests/test_rutas_tapadas.py
"""
import re
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Match, Route

import main

# Un valor de cada tipo de parámetro que una ruta puede declarar.
_VALOR_DE_MUESTRA = {
    "str": "zz",
    "int": "7",
    "float": "1.5",
    "path": "zz/yy",
    "uuid": "00000000-0000-0000-0000-000000000000",
}
_PARAMETRO = re.compile(r"\{(\w+)(?::(\w+))?\}")


def _pedido_de_muestra(camino: str) -> str:
    """Un camino concreto que la ruta `camino` tiene que atender."""
    return _PARAMETRO.sub(lambda m: _VALOR_DE_MUESTRA[m.group(2) or "str"], camino)


def _quien_atiende(rutas, camino: str, metodo: str):
    """La primera ruta de la tabla que agarra ese pedido entero (camino Y método):
    la que el servidor usa."""
    pedido = {"type": "http", "path": camino, "method": metodo, "root_path": ""}
    for r in rutas:
        if r.matches(pedido)[0] == Match.FULL:
            return r
    return None


def rutas_sin_revisar(app) -> list:
    """Las rutas de un tipo que este test no sabe revisar."""
    return [f"{type(r).__name__} {getattr(r, 'path', '?')}" for r in app.routes
            if not (isinstance(r, Route) and r.methods)]


def rutas_con_parametro_acotado(app) -> list:
    """Las rutas con un parámetro de tipo acotado en la ruta misma (`{id:int}`)."""
    return sorted({r.path for r in app.routes
                   for m in _PARAMETRO.finditer(getattr(r, "path", "")) if m.group(2)})


def rutas_tapadas(app) -> list:
    """["MÉTODO /ruta/tapada  ← la atiende /ruta/anterior (función)"] de la app."""
    rutas = list(app.routes)
    out = []
    for r in rutas:
        if not (isinstance(r, Route) and r.methods):
            continue
        camino = _pedido_de_muestra(r.path)
        for metodo in sorted(r.methods):
            atiende = _quien_atiende(rutas, camino, metodo)
            if atiende is not r:
                out.append(f"{metodo} {r.path}  ← la atiende "
                           + (f"{atiende.path} ({atiende.name})" if atiende is not None
                              else "NADIE (¿cambió cómo se arma el pedido de muestra?)"))
    return out


# Qué tan ANCHO es un tramo del camino: una palabra fija atiende un solo texto; un
# tramo que mezcla texto y parámetro (`{key}.mp3`), algunos; un parámetro, cualquiera.
_FIJO, _MEZCLA, _PARAMETRO_SOLO = 0, 1, 2


def _tramos(camino: str) -> list:
    """[(texto, ancho)] de cada tramo del camino."""
    return [(t, _PARAMETRO_SOLO if _PARAMETRO.fullmatch(t) else _MEZCLA if "{" in t else _FIJO)
            for t in camino.split("/")]


def rutas_que_se_cruzan(app) -> list:
    """["MÉTODO /pedido  → lo atiende /ruta/anterior (función), no /ruta/posterior"]:
    los pedidos que dos rutas podrían atender y que se queda la declarada antes,
    cuando NINGUNA de las dos es simplemente más específica que la otra. No repite
    las de `rutas_tapadas` (ésas pierden todos sus pedidos) ni marca el orden
    correcto (la fija antes que la del parámetro se queda con su pedido a propósito)."""
    rutas = [r for r in app.routes if isinstance(r, Route) and r.methods]
    todas = list(app.routes)
    out = []
    for j, b in enumerate(rutas):
        tb = _tramos(b.path)
        for a in rutas[:j]:
            ta = _tramos(a.path)
            metodos = a.methods & b.methods
            if len(ta) != len(tb) or not metodos:
                continue
            # Sólo interesa si A (la de antes) es más ancha que B en algún tramo: si
            # no, A es la más específica de las dos y que gane es lo que se quiere.
            if not any(ancho_a > ancho_b for (_, ancho_a), (_, ancho_b) in zip(ta, tb)):
                continue
            # El pedido del cruce: en cada tramo, el texto de la más angosta de las dos.
            camino = "/".join(
                txt_b if ancho_b == _FIJO else txt_a if ancho_a == _FIJO
                else _pedido_de_muestra(txt_a if ancho_a < ancho_b else txt_b)
                for (txt_b, ancho_b), (txt_a, ancho_a) in zip(tb, ta))
            if camino == _pedido_de_muestra(b.path):
                continue                        # no es un cruce: es el pedido común de B
            for metodo in sorted(metodos):
                pedido = {"type": "http", "path": camino, "method": metodo, "root_path": ""}
                # `is a`: si una tercera ruta declarada antes (una fija que resuelve
                # justo ese pedido) es la que atiende, no hay nada que avisar.
                if (b.matches(pedido)[0] == Match.FULL
                        and _quien_atiende(todas, camino, metodo) is a):
                    out.append(f"{metodo} {camino}  → lo atiende {a.path} ({a.name}), "
                               f"no {b.path} ({b.name})")
    return out


def _app_plantada(orden_bien: bool) -> FastAPI:
    """El bug en chico: una ruta con parámetro y una fija que cabe en ella."""
    app = FastAPI()

    def con_parametro(cosa_id: str):
        return {"atendio": "la del parámetro", "cosa_id": cosa_id}

    def fija():
        return {"atendio": "la fija"}

    declarar = [("/cosas/{cosa_id}", con_parametro), ("/cosas/plantillas", fija)]
    for camino, funcion in (reversed(declarar) if orden_bien else declarar):
        app.get(camino)(funcion)
    return app


class ElDetectorVeElCasoPlantado(unittest.TestCase):
    def test_con_el_orden_mal_la_ruta_fija_aparece_como_tapada(self):
        tapadas = rutas_tapadas(_app_plantada(orden_bien=False))
        self.assertEqual(len(tapadas), 1, tapadas)
        self.assertIn("GET /cosas/plantillas", tapadas[0])
        self.assertIn("/cosas/{cosa_id}", tapadas[0])

    def test_con_el_orden_bien_no_aparece_nada(self):
        self.assertEqual(rutas_tapadas(_app_plantada(orden_bien=True)), [])

    def test_el_servidor_atiende_con_la_primera_que_coincide(self):
        """La premisa del detector, medida con un pedido de verdad."""
        mal = TestClient(_app_plantada(orden_bien=False)).get("/cosas/plantillas").json()
        bien = TestClient(_app_plantada(orden_bien=True)).get("/cosas/plantillas").json()
        self.assertEqual(mal["atendio"], "la del parámetro")
        self.assertEqual(bien["atendio"], "la fija")

    def test_la_misma_ruta_escrita_dos_veces_tambien_aparece(self):
        app = FastAPI()
        app.get("/cosas")(lambda: {"n": 1})
        app.get("/cosas")(lambda: {"n": 2})
        self.assertEqual(len(rutas_tapadas(app)), 1)

    def test_el_mismo_camino_con_otro_metodo_no_es_tapar(self):
        """`GET /cosas/{id}` antes de `POST /cosas/plantillas` no molesta: el servidor
        sigue buscando hasta la que coincide también en el método."""
        app = FastAPI()
        app.get("/cosas/{cosa_id}")(lambda cosa_id: {})
        app.post("/cosas/plantillas")(lambda: {})
        self.assertEqual(rutas_tapadas(app), [])


class CadaRamaDelDetectorTieneSuCaso(unittest.TestCase):
    def test_una_ruta_con_parametro_tapada_por_otra_con_parametro(self):
        app = FastAPI()
        app.get("/cosas/{a}/{b}")(lambda a, b: {})
        app.get("/cosas/{cosa_id}/detalle")(lambda cosa_id: {})
        tapadas = rutas_tapadas(app)
        self.assertEqual(len(tapadas), 1, tapadas)
        self.assertIn("GET /cosas/{cosa_id}/detalle", tapadas[0])

    def test_una_ruta_tapada_en_uno_solo_de_sus_metodos(self):
        """`rutas_tapadas` prueba TODOS los métodos de cada ruta, no el primero."""
        for tapado in ("DELETE", "GET", "POST"):
            app = FastAPI()
            app.api_route("/cosas/{cosa_id}", methods=[tapado])(lambda cosa_id: {})
            app.api_route("/cosas/plantillas", methods=["DELETE", "GET", "POST"])(lambda: {})
            tapadas = rutas_tapadas(app)
            self.assertEqual(len(tapadas), 1, f"{tapado}: {tapadas}")
            self.assertTrue(tapadas[0].startswith(f"{tapado} /cosas/plantillas"), tapadas[0])

    def test_el_pedido_de_muestra_respeta_el_tipo_de_cada_parametro(self):
        self.assertEqual(_pedido_de_muestra("/a/{x}/b/{n:int}/{resto:path}"), "/a/zz/b/7/zz/yy")
        app = FastAPI()
        app.get("/cosas/{n:int}")(lambda n: {})
        app.get("/cosas/{nombre}")(lambda nombre: {})
        self.assertEqual(rutas_con_parametro_acotado(app), ["/cosas/{n:int}"])
        self.assertEqual(rutas_con_parametro_acotado(_app_plantada(orden_bien=True)), [])
        # Una ruta con tipo atiende su propio pedido de muestra (no sale como tapada
        # por armarle mal el pedido).
        solo = FastAPI()
        solo.get("/cosas/{n:int}")(lambda n: {})
        self.assertEqual(rutas_tapadas(solo), [])

    def test_una_ruta_de_un_tipo_que_no_se_sabe_revisar_aparece(self):
        from starlette.routing import Mount
        app = FastAPI()
        app.get("/cosas")(lambda: {})
        self.assertEqual(rutas_sin_revisar(app), [])
        app.websocket("/vivo")(lambda ws: None)
        app.router.routes.append(Mount("/archivos", app=FastAPI()))
        sin_revisar = rutas_sin_revisar(app)
        self.assertEqual(len(sin_revisar), 2, sin_revisar)
        self.assertTrue(any("/vivo" in r for r in sin_revisar))
        self.assertTrue(any("/archivos" in r for r in sin_revisar))


class ElDetectorVeElCruce(unittest.TestCase):
    def _app(self):
        app = FastAPI()
        app.post("/cosas/{cosa_id}/revertir")(lambda cosa_id: {"atendio": "revertir una cosa"})
        app.post("/cosas/plantillas/{nombre}")(lambda nombre: {"atendio": "una plantilla"})
        return app

    def test_el_pedido_que_las_dos_podrian_atender_aparece(self):
        app = self._app()
        self.assertEqual(rutas_tapadas(app), [], "ninguna tapa ENTERA a la otra")
        cruces = rutas_que_se_cruzan(app)
        self.assertEqual(len(cruces), 1, cruces)
        self.assertIn("POST /cosas/plantillas/revertir", cruces[0])
        self.assertIn("/cosas/{cosa_id}/revertir", cruces[0])

    def test_ese_pedido_de_verdad_cae_en_la_primera(self):
        r = TestClient(self._app()).post("/cosas/plantillas/revertir").json()
        self.assertEqual(r["atendio"], "revertir una cosa")

    def test_sin_metodo_en_comun_no_hay_cruce(self):
        app = FastAPI()
        app.post("/cosas/{cosa_id}/revertir")(lambda cosa_id: {})
        app.get("/cosas/plantillas/{nombre}")(lambda nombre: {})
        self.assertEqual(rutas_que_se_cruzan(app), [])

    def test_la_ruta_tapada_entera_no_se_cuenta_dos_veces(self):
        app = _app_plantada(orden_bien=False)
        self.assertEqual(len(rutas_tapadas(app)), 1)
        self.assertEqual(rutas_que_se_cruzan(app), [])

    def test_fija_antes_que_la_del_parametro_no_es_un_cruce(self):
        """El orden correcto: la fija se queda con SU pedido, que es lo que se quiere."""
        self.assertEqual(rutas_que_se_cruzan(_app_plantada(orden_bien=True)), [])

    def test_si_una_ruta_fija_ya_resuelve_ese_pedido_no_hay_cruce(self):
        """El arreglo de un cruce: declarar ANTES la ruta fija de ese pedido puntual."""
        app = FastAPI()
        app.post("/cosas/plantillas/revertir")(lambda: {"atendio": "la fija"})
        app.post("/cosas/{cosa_id}/revertir")(lambda cosa_id: {"atendio": "revertir una cosa"})
        app.post("/cosas/plantillas/{nombre}")(lambda nombre: {"atendio": "una plantilla"})
        self.assertEqual(TestClient(app).post("/cosas/plantillas/revertir").json()["atendio"], "la fija")
        self.assertEqual(rutas_que_se_cruzan(app), [])
        self.assertEqual(rutas_tapadas(app), [])

    def test_un_tramo_mezclado_es_mas_angosto_que_un_parametro(self):
        """Si `{clave}.mp3` se tomara por un parámetro entero, este cruce no se vería."""
        app = FastAPI()
        app.get("/x/{algo}/fin")(lambda algo: {})
        app.get("/x/{clave}.mp3/{y}")(lambda clave, y: {})
        self.assertEqual(rutas_tapadas(app), [])
        cruces = rutas_que_se_cruzan(app)
        self.assertEqual(len(cruces), 1, cruces)
        self.assertIn("GET /x/zz.mp3/fin", cruces[0])

    def test_un_tramo_que_mezcla_texto_y_parametro(self):
        """`{clave}.mp3` es más angosto que `{algo}` y más ancho que `lista.mp3`."""
        bien = FastAPI()                      # de la más angosta a la más ancha
        bien.get("/voz/lista.mp3")(lambda: {})
        bien.get("/voz/{clave}.mp3")(lambda clave: {})
        bien.get("/voz/{algo}")(lambda algo: {})
        self.assertEqual(rutas_tapadas(bien) + rutas_que_se_cruzan(bien), [])
        mal = FastAPI()                       # cruce: cada una más ancha en un tramo
        mal.get("/{seccion}/lista.mp3")(lambda seccion: {})
        mal.get("/voz/{clave}.mp3")(lambda clave: {})
        self.assertEqual(rutas_tapadas(mal), [])
        cruces = rutas_que_se_cruzan(mal)
        self.assertEqual(len(cruces), 1, cruces)
        self.assertIn("GET /voz/lista.mp3", cruces[0])


class NingunaRutaDeLaAppQuedaTapada(unittest.TestCase):
    def test_todas_las_rutas_son_de_un_tipo_que_se_sabe_revisar(self):
        self.assertEqual(rutas_sin_revisar(main.app), [],
                         "Hay rutas de un tipo que test_rutas_tapadas.py no sabe revisar "
                         "(un WebSocket, una carpeta montada): enseñale a revisarlas antes "
                         "de sumarlas, o quedan fuera del control sin que nadie lo note.")
        self.assertEqual(rutas_con_parametro_acotado(main.app), [],
                         "Hay rutas con un parámetro de tipo acotado en la ruta misma "
                         "(`{id:int}`, `{resto:path}`). Una así puede tapar a otra sólo "
                         "para ALGUNOS valores, y este test prueba un valor por parámetro: "
                         "antes de sumarla, hacé que `rutas_tapadas` pruebe varios.")

    def test_cada_ruta_atiende_su_propio_pedido(self):
        tapadas = rutas_tapadas(main.app)
        self.assertEqual(
            tapadas, [],
            "Hay rutas a las que NUNCA llega un pedido, porque otra declarada antes en "
            "main.py coincide primero (el servidor atiende con la primera que coincide):"
            "\n  " + "\n  ".join(tapadas) +
            "\nArreglo: mové la ruta fija ARRIBA de la que tiene el {parámetro} (o la del "
            "parámetro abajo de todas las fijas de su grupo).")

    def test_ninguna_ruta_le_saca_un_pedido_a_otra(self):
        cruces = rutas_que_se_cruzan(main.app)
        self.assertEqual(
            cruces, [],
            "Hay pedidos que dos rutas podrían atender, y se los queda la declarada "
            "antes (cada una tiene un {parámetro} donde la otra tiene una palabra fija):"
            "\n  " + "\n  ".join(cruces) +
            "\nSi ese valor del parámetro puede darse de verdad, la segunda ruta nunca "
            "lo recibe: cambiá el camino de una de las dos.")

    def test_la_tabla_no_esta_vacia(self):
        """Si un día las rutas dejan de colgar de `main.app`, este test no puede
        quedar en verde por revisar una tabla vacía."""
        self.assertGreater(len([r for r in main.app.routes if isinstance(r, Route)]), 250)


if __name__ == "__main__":
    unittest.main()
