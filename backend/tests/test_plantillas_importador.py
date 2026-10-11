"""Las plantillas de columnas del importador ("Guardar mapeo actual") se vuelven a ver.

EL BUG (reproducido por HTTP el 2026-10-10). Guardar una plantilla andaba (200) y
pedir las guardadas contestaba 404 "Batch no encontrado": la ruta del detalle de un
import (`GET /api/imports/{batch_id}`) estaba declarada antes que la de las
plantillas (`GET /api/imports/mappings`) y se quedaba con el pedido. El asistente
se tragaba el error y mostraba una lista vacía: la plantilla se veía mientras el
asistente seguía abierto y no volvía a aparecer nunca — ni para usarla ni para
borrarla. Así desde el día en que se agregaron (2026-05-08).

Todo por las mismas puertas que usa el asistente (`ImportWizard.jsx`): guardar,
pedir, borrar, importar con la plantilla. El control general de rutas tapadas está
en `test_rutas_tapadas.py`; el del renombre de brokers, en
`test_renombre_broker_recetas.py` (escenarios `plantilla_…`).

Corre con: cd backend && python3 -m pytest tests/test_plantillas_importador.py
"""
import io
import json
import unittest
import uuid
from unittest import mock

from fastapi.testclient import TestClient

import main
import renombre_broker

try:
    from tests.test_renombre_broker_recetas import COLUMNAS_DEL_BANCO, archivo_del_banco
except ImportError:                                  # corrido suelto desde tests/
    from test_renombre_broker_recetas import COLUMNAS_DEL_BANCO, archivo_del_banco

# Un archivo con los títulos de columna de un banco cualquiera, sin columna de broker
# (el mismo de los escenarios `plantilla_…` del renombre).
_ARCHIVO = archivo_del_banco(activo="AAPL")
_COLUMNAS = COLUMNAS_DEL_BANCO


class _Cuenta:
    def __init__(self):
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, is_admin) VALUES (?, 'x', 1, 0)",
            (f"plant-{uuid.uuid4().hex[:12]}@rendi.test",)).lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.c = TestClient(main.app)

    def pedir(self, metodo, url, **kw):
        return getattr(self.c, metodo)(url, headers=self.h, **kw)

    def ok(self, metodo, url, **kw):
        r = self.pedir(metodo, url, **kw)
        assert r.status_code == 200, f"{metodo.upper()} {url} → {r.status_code} {r.text[:300]}"
        return r.json()

    def guardar(self, nombre, mapping):
        return self.ok("post", "/api/imports/mappings", json={"name": nombre, "mapping": mapping})

    def plantillas(self):
        return self.ok("get", "/api/imports/mappings")


class LasPlantillasGuardadasSeVuelvenAVer(unittest.TestCase):
    def setUp(self):
        for nombre in ("_reconstruir_mtm_post_import", "_reconstruir_en_fila"):
            p = mock.patch.object(main, nombre, side_effect=lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)

    def test_lo_guardado_vuelve_al_pedir_la_lista(self):
        """El bug: esto contestaba 404."""
        cta = _Cuenta()
        mapping = {"columns": dict(_COLUMNAS), "defaults": {"broker": "Banco Ñandú"}}
        guardada = cta.guardar("mi banco", mapping)
        r = cta.pedir("get", "/api/imports/mappings")
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertEqual(r.json(), [{"id": guardada["id"], "name": "mi banco",
                                     "mapping": mapping, "created_at": guardada["created_at"]}])

    def test_una_cuenta_nueva_recibe_una_lista_vacia_y_no_un_error(self):
        self.assertEqual(_Cuenta().plantillas(), [])

    def test_guardar_con_el_mismo_nombre_la_reemplaza(self):
        cta = _Cuenta()
        cta.guardar("mi banco", {"columns": {"fecha": "Dia"}, "defaults": {}})
        cta.guardar("mi banco", {"columns": {"fecha": "Fecha"}, "defaults": {}})
        cta.guardar("otro", {"columns": {"fecha": "Date"}, "defaults": {}})
        self.assertEqual([(p["name"], p["mapping"]["columns"]["fecha"]) for p in cta.plantillas()],
                         [("mi banco", "Fecha"), ("otro", "Date")])

    def test_borrar_la_saca_de_la_lista(self):
        cta = _Cuenta()
        a = cta.guardar("a", {"columns": {"fecha": "Dia"}, "defaults": {}})
        cta.guardar("b", {"columns": {"fecha": "Dia"}, "defaults": {}})
        cta.ok("delete", f"/api/imports/mappings/{a['id']}")
        self.assertEqual([p["name"] for p in cta.plantillas()], ["b"])

    def test_cada_cuenta_ve_y_borra_solo_las_suyas(self):
        una, otra = _Cuenta(), _Cuenta()
        suya = una.guardar("de una", {"columns": {"fecha": "Dia"}, "defaults": {}})
        self.assertEqual(otra.plantillas(), [])
        otra.pedir("delete", f"/api/imports/mappings/{suya['id']}")
        self.assertEqual([p["name"] for p in una.plantillas()], ["de una"])

    def test_sin_sesion_no_se_ven(self):
        r = TestClient(main.app).get("/api/imports/mappings")
        self.assertIn(r.status_code, (401, 403), r.text[:200])

    def test_la_plantilla_que_vuelve_sirve_para_importar(self):
        """El camino entero del asistente: guardar, cerrar, volver, cargarla, importar."""
        cta = _Cuenta()
        cta.ok("post", "/api/brokers", json={"name": "Banco Ñandú", "currency": "USD"})
        cta.guardar("mi banco", {"columns": dict(_COLUMNAS), "defaults": {"broker": "Banco Ñandú"}})
        plantilla = cta.plantillas()[0]["mapping"]
        previa = cta.ok("post", "/api/imports/preview",
                        files=[("files", ("banco.csv", io.BytesIO(_ARCHIVO), "text/csv"))],
                        data={"format": "rendi_generic", "mapping": json.dumps(plantilla)})
        cta.ok("post", "/api/imports/confirm", json={"session_id": previa["session_id"]})
        conn = main.get_db()
        try:
            tenencias = [(r["broker"], r["asset"], r["quantity"]) for r in conn.execute(
                "SELECT broker, asset, quantity FROM positions WHERE user_id=? AND is_cash=0",
                (cta.uid,))]
        finally:
            conn.close()
        self.assertEqual(tenencias, [("Banco Ñandú", "AAPL", 10.0)])


class AlGuardarElBrokerFijoQuedaConElNombreDelBroker(unittest.TestCase):
    """El asistente manda el broker fijo como esté en pantalla; cuando la cuenta no
    tiene brokers es un texto libre. El importador compara sin mayúsculas ni espacios
    al borde, así que "balanz " importa a "Balanz" — pero el renombre de brokers busca
    el nombre, y con otra escritura la plantilla quedaba atrás (auditoría 2026-10-11:
    tras renombrar, el import volvía a crear el broker viejo). Se guarda con el nombre."""

    def _guardada(self, cta, escrito):
        return cta.guardar("p", {"columns": {"fecha": "Dia"},
                                 "defaults": {"broker": escrito, "moneda": "ARS"}})["mapping"]

    def _cuenta(self, *brokers):
        cta = _Cuenta()
        conn = main.get_db()
        try:                      # el plan gratis permite un solo broker
            conn.execute("UPDATE users SET tier='pro' WHERE id=?", (cta.uid,))
            conn.commit()
        finally:
            conn.close()
        for b in brokers:
            cta.ok("post", "/api/brokers", json={"name": b, "currency": "USD"})
        return cta

    def test_otras_mayusculas_o_espacios_quedan_con_el_nombre_del_broker(self):
        cta = self._cuenta("Zorzal Ñandú")
        for escrito in ("zorzal ñandú", "ZORZAL ÑANDÚ", "  Zorzal Ñandú ", "Zorzal Ñandú"):
            m = self._guardada(cta, escrito)
            self.assertEqual(m["defaults"], {"broker": "Zorzal Ñandú", "moneda": "ARS"}, escrito)
        self.assertEqual(cta.plantillas()[0]["mapping"]["defaults"]["broker"], "Zorzal Ñandú")

    def test_dos_brokers_que_solo_difieren_en_mayusculas_no_se_confunden(self):
        cta = self._cuenta("Balanz", "balanz")
        self.assertEqual(self._guardada(cta, "balanz")["defaults"]["broker"], "balanz")
        self.assertEqual(self._guardada(cta, "Balanz")["defaults"]["broker"], "Balanz")

    def test_un_broker_que_no_existe_queda_como_se_escribio_sin_los_espacios(self):
        cta = self._cuenta("Balanz")
        self.assertEqual(self._guardada(cta, "  Mi Banco Nuevo ")["defaults"]["broker"], "Mi Banco Nuevo")

    def test_un_broker_en_blanco_no_se_guarda(self):
        cta = self._cuenta("Balanz")
        self.assertEqual(self._guardada(cta, "   ")["defaults"], {"moneda": "ARS"})

    def test_el_titulo_de_la_columna_de_broker_no_se_toca(self):
        cta = self._cuenta("Balanz")
        m = cta.guardar("p", {"columns": {"broker": " balanz "}, "defaults": {"broker": " balanz "}})
        self.assertEqual(m["mapping"], {"columns": {"broker": " balanz "}, "defaults": {"broker": "Balanz"}})

    def test_un_nombre_que_el_broker_tuvo_antes_se_guarda_con_el_de_hoy(self):
        """Una pantalla que quedó abierta mientras el broker se renombraba en otra
        manda el nombre viejo: es ESE broker, con el nombre que tiene ahora."""
        cta = self._cuenta("Zorzal Ñandú")
        bid = cta.ok("get", "/api/brokers")[0]["id"]
        cta.ok("put", f"/api/brokers/{bid}", json={"name": "Zorzal Ávido", "currency": "USD"})
        self.assertEqual(self._guardada(cta, "Zorzal Ñandú")["defaults"]["broker"], "Zorzal Ávido")
        self.assertEqual(self._guardada(cta, " zorzal ñandú ")["defaults"]["broker"], "Zorzal Ávido")

    def test_si_otro_broker_tomo_ese_nombre_es_el_otro(self):
        cta = self._cuenta("Zorzal Ñandú", "Hornero")
        ids = {b["name"]: b["id"] for b in cta.ok("get", "/api/brokers")}
        cta.ok("put", f"/api/brokers/{ids['Zorzal Ñandú']}", json={"name": "Zorzal Ávido", "currency": "USD"})
        cta.ok("put", f"/api/brokers/{ids['Hornero']}", json={"name": "Zorzal Ñandú", "currency": "USD"})
        self.assertEqual(self._guardada(cta, "Zorzal Ñandú")["defaults"]["broker"], "Zorzal Ñandú")

    def test_si_el_renombre_entra_justo_antes_la_plantilla_queda_con_el_nombre_nuevo(self):
        """La carrera (auditoría 2026-10-11): el guardado leía los brokers ANTES de
        tomar el turno de la cuenta; si un renombre se confirmaba en ese hueco, la
        plantilla quedaba con el nombre que ya no existe y el import volvía a crear
        ese broker. Se simula ese orden exacto: lo que dejó el renombre aparece en
        el instante en que el guardado toma el turno."""
        cta = self._cuenta("Zorzal Ñandú")
        bid = cta.ok("get", "/api/brokers")[0]["id"]
        de_verdad = main._tomar_turno

        def el_renombre_llego_antes(conn, uid):
            de_verdad(conn, uid)
            conn.execute("UPDATE brokers SET name=?, nombres_anteriores=? WHERE id=?",
                         ("Zorzal Ávido", json.dumps(["Zorzal Ñandú"]), bid))

        with mock.patch.object(main, "_tomar_turno", side_effect=el_renombre_llego_antes) as turno:
            m = self._guardada(cta, "Zorzal Ñandú")
        self.assertEqual(turno.call_count, 1, "el guardado tiene que tomar el turno de la cuenta")
        self.assertEqual(m["defaults"]["broker"], "Zorzal Ávido")
        self.assertEqual(cta.plantillas()[0]["mapping"]["defaults"]["broker"], "Zorzal Ávido")

    def test_al_renombrar_un_broker_la_plantilla_que_apunta_a_su_gemelo_no_se_toca(self):
        """"Balanz" y "balanz" pueden ser dos brokers. El renombre busca el nombre
        viejo también sin mirar mayúsculas (por las plantillas guardadas antes), pero
        un texto que es EXACTAMENTE el nombre de otro broker vivo es de ese otro."""
        cta = self._cuenta("Zorzal Ñandú", "zorzal ñandú")
        ids = {b["name"]: b["id"] for b in cta.ok("get", "/api/brokers")}
        cta.guardar("del gemelo", {"columns": {}, "defaults": {"broker": "zorzal ñandú"}})
        cta.guardar("del renombrado", {"columns": {}, "defaults": {"broker": "Zorzal Ñandú"}})
        cta.ok("put", f"/api/brokers/{ids['Zorzal Ñandú']}", json={"name": "Zorzal Ávido", "currency": "USD"})
        self.assertEqual({p["name"]: p["mapping"]["defaults"]["broker"] for p in cta.plantillas()},
                         {"del gemelo": "zorzal ñandú", "del renombrado": "Zorzal Ávido"})

    def test_la_plantilla_se_guarda_siempre_con_sus_dos_partes(self):
        cta = self._cuenta("Balanz")
        for mandado in ({}, {"columns": {"fecha": "Dia"}}, {"defaults": {"moneda": "ARS"}}):
            self.assertEqual(cta.guardar("p", mandado)["mapping"],
                             {"columns": mandado.get("columns", {}), "defaults": mandado.get("defaults", {})})

    def test_una_plantilla_con_otra_forma_no_se_guarda(self):
        """Texto a texto y nada más: con un broker fijo que no es texto, o con una
        parte de más, ni el renombre ni el importador la leen como el asistente."""
        cta = self._cuenta("Balanz")
        for mandado in ({"defaults": {"broker": 7}}, {"defaults": {"broker": ["Balanz"]}},
                        {"defaults": {"broker": None}}, {"defaults": ["Balanz"]}, {"defaults": None},
                        {"columns": {"fecha": 3}}, {"columns": "Dia"},
                        {"columns": {}, "defaults": {}, "otra_parte": {"broker": "Balanz"}}):
            r = cta.pedir("post", "/api/imports/mappings", json={"name": "p", "mapping": mandado})
            self.assertEqual(r.status_code, 422, f"{mandado} → {r.status_code} {r.text[:120]}")
        self.assertEqual(cta.plantillas(), [])

    def test_guardar_y_despues_renombrar_el_broker(self):
        """Lo que la auditoría midió roto, por las mismas puertas: guardar con otra
        escritura, renombrar el broker, importar con la plantilla."""
        cta = self._cuenta("Zorzal Ñandú")
        bid = cta.ok("get", "/api/brokers")[0]["id"]
        cta.guardar("mi banco", {"columns": dict(_COLUMNAS), "defaults": {"broker": "zorzal ñandú "}})
        cta.ok("put", f"/api/brokers/{bid}", json={"name": "Zorzal Ávido", "currency": "USD"})
        plantilla = cta.plantillas()[0]["mapping"]
        self.assertEqual(plantilla["defaults"]["broker"], "Zorzal Ávido")
        for nombre in ("_reconstruir_mtm_post_import", "_reconstruir_en_fila"):
            p = mock.patch.object(main, nombre, side_effect=lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)
        previa = cta.ok("post", "/api/imports/preview",
                        files=[("files", ("banco.csv", io.BytesIO(_ARCHIVO), "text/csv"))],
                        data={"format": "rendi_generic", "mapping": json.dumps(plantilla)})
        cta.ok("post", "/api/imports/confirm", json={"session_id": previa["session_id"]})
        self.assertEqual([b["name"] for b in cta.ok("get", "/api/brokers")], ["Zorzal Ávido"])


class LasPlantillasTienenTecho(unittest.TestCase):
    """El renombre de brokers abre cada plantilla dentro de su transacción (que en
    SQLite frena las escrituras de todos): lo que recorre tiene que tener tope."""

    def test_una_plantilla_enorme_no_se_guarda(self):
        cta = _Cuenta()
        grande = {"columns": {"fecha": "x" * (renombre_broker.PLANTILLA_MAX_CARACTERES + 1)}, "defaults": {}}
        r = cta.pedir("post", "/api/imports/mappings", json={"name": "grande", "mapping": grande})
        self.assertEqual(r.status_code, 400, r.text[:200])
        self.assertIn("demasiado grande", r.json()["detail"])
        self.assertEqual(cta.plantillas(), [])

    def test_una_plantilla_normal_esta_muy_lejos_del_tope(self):
        """Una bien cargada: los 12 datos, cada uno con un título de 60 letras y un
        valor fijo. (Los títulos salen del archivo y no tienen tope propio: el techo
        real son 12 títulos de unas 1.600 letras cada uno.)"""
        import importing.mapper as mapper
        campos = [f["id"] for f in mapper.RENDI_FIELDS]
        normal = {"columns": {c: "T" * 60 for c in campos},
                  "defaults": {c: "V" * 60 for c in campos}}
        self.assertLess(len(json.dumps(normal)) * 5, renombre_broker.PLANTILLA_MAX_CARACTERES)
        _Cuenta().guardar("normal", normal)

    def test_pasado_el_tope_de_cantidad_no_entra_otra_pero_se_pueden_reemplazar(self):
        cta = _Cuenta()
        with mock.patch.object(renombre_broker, "PLANTILLAS_MAX_POR_CUENTA", 3):
            for n in ("a", "b", "c"):
                cta.guardar(n, {"columns": {"fecha": "Dia"}, "defaults": {}})
            r = cta.pedir("post", "/api/imports/mappings",
                          json={"name": "d", "mapping": {"columns": {}, "defaults": {}}})
            self.assertEqual(r.status_code, 400, r.text[:200])
            self.assertIn("Borrá alguna", r.json()["detail"])
            # Reemplazar una que ya está sí se puede, y borrar hace lugar.
            cta.guardar("b", {"columns": {"fecha": "Fecha"}, "defaults": {}})
            cta.ok("delete", f"/api/imports/mappings/{cta.plantillas()[0]['id']}")
            cta.guardar("d", {"columns": {"fecha": "Dia"}, "defaults": {}})
        self.assertEqual([p["name"] for p in cta.plantillas()], ["b", "c", "d"])

    def test_doce_titulos_de_1600_letras_entran_y_de_1700_no(self):
        """El número del comentario de arriba, medido."""
        import importing.mapper as mapper
        campos = [f["id"] for f in mapper.RENDI_FIELDS]
        cta = _Cuenta()
        cta.guardar("entra", {"columns": {c: "T" * 1600 for c in campos}, "defaults": {}})
        r = cta.pedir("post", "/api/imports/mappings",
                      json={"name": "no entra", "mapping": {"columns": {c: "T" * 1700 for c in campos}}})
        self.assertEqual(r.status_code, 400, r.text[:120])

    def test_lo_guardado_antes_de_que_hubiera_tope_no_se_lista_ni_frena_el_renombre(self):
        """Entre 2026-05-08 y 2026-10-11 se pudo guardar sin tope. Una fila enorme de
        entonces no puede pesar en la lista ni en el renombre de un broker (que la
        abriría con la base tomada): queda fuera de las dos cosas."""
        cta = _Cuenta()
        bid = cta.ok("post", "/api/brokers", json={"name": "Balanz", "currency": "USD"})["id"]
        cta.guardar("la normal", {"columns": {"fecha": "Dia"}, "defaults": {"broker": "Balanz"}})
        enorme = json.dumps({"columns": {"fecha": "x" * (renombre_broker.PLANTILLA_MAX_CARACTERES + 1)},
                             "defaults": {"broker": "Balanz"}})
        conn = main.get_db()
        try:
            conn.execute("INSERT INTO import_mappings (user_id, name, mapping_json) VALUES (?,?,?)",
                         (cta.uid, "la enorme", enorme))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual([p["name"] for p in cta.plantillas()], ["la normal"])
        abiertas = []
        de_verdad = renombre_broker.renombrar_en_json

        def anotar(texto, *a, **k):
            abiertas.append(len(texto or ""))
            return de_verdad(texto, *a, **k)

        with mock.patch.object(renombre_broker, "renombrar_en_json", side_effect=anotar):
            cta.ok("put", f"/api/brokers/{bid}", json={"name": "Balanz 2", "currency": "USD"})
        self.assertTrue(abiertas, "el renombre tiene que abrir la plantilla normal")
        self.assertLessEqual(max(abiertas), renombre_broker.PLANTILLA_MAX_CARACTERES)
        self.assertEqual(cta.plantillas()[0]["mapping"]["defaults"]["broker"], "Balanz 2")

    def test_de_mas_de_cien_guardadas_antes_se_usan_las_primeras_las_mismas_en_la_lista_y_en_el_renombre(self):
        cta = _Cuenta()
        bid = cta.ok("post", "/api/brokers", json={"name": "Balanz", "currency": "USD"})["id"]
        conn = main.get_db()
        try:
            for n in ("e", "d", "c", "b", "a"):          # guardadas en este orden
                conn.execute("INSERT INTO import_mappings (user_id, name, mapping_json) VALUES (?,?,?)",
                             (cta.uid, n, json.dumps({"columns": {}, "defaults": {"broker": "Balanz"}})))
            conn.commit()
        finally:
            conn.close()
        with mock.patch.object(renombre_broker, "PLANTILLAS_MAX_POR_CUENTA", 3):
            self.assertEqual([p["name"] for p in cta.plantillas()], ["c", "d", "e"])
            cta.ok("put", f"/api/brokers/{bid}", json={"name": "Balanz 2", "currency": "USD"})
            self.assertEqual({p["mapping"]["defaults"]["broker"] for p in cta.plantillas()}, {"Balanz 2"})
            # Con el tope lleno no entra otra: quedaría detrás de las que no se ven.
            r = cta.pedir("post", "/api/imports/mappings",
                          json={"name": "z", "mapping": {"columns": {}, "defaults": {}}})
            self.assertEqual(r.status_code, 400, r.text[:120])

    def test_si_la_base_esta_ocupada_el_guardado_espera_y_vuelve_a_intentar(self):
        """El guardado toma el turno de la cuenta: si en ese instante otro pedido
        tiene la base, reintenta en vez de mostrarle a la persona "database is locked"."""
        import sqlite3
        cta = _Cuenta()
        de_verdad, intentos = main._tomar_turno, []

        def ocupada_la_primera_vez(conn, uid):
            intentos.append(1)
            if len(intentos) == 1:
                raise sqlite3.OperationalError("database is locked")
            de_verdad(conn, uid)

        with mock.patch.object(main, "_tomar_turno", side_effect=ocupada_la_primera_vez), \
                mock.patch("time.sleep"):
            r = cta.pedir("post", "/api/imports/mappings",
                          json={"name": "p", "mapping": {"columns": {"fecha": "Dia"}, "defaults": {}}})
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertEqual(len(intentos), 2)
        self.assertEqual([p["name"] for p in cta.plantillas()], ["p"])

    def test_un_nombre_en_blanco_no_se_guarda(self):
        r = _Cuenta().pedir("post", "/api/imports/mappings",
                            json={"name": "   ", "mapping": {"columns": {}, "defaults": {}}})
        self.assertEqual(r.status_code, 400, r.text[:200])


class ElBrokerFijoQueMandaElAsistenteAlImportar(unittest.TestCase):
    """El mismo cuidado que al guardar una plantilla, en la puerta que importa: la
    vista previa. Con la pantalla abierta mientras el broker se renombra en otra, el
    asistente manda el nombre de antes; el import va al broker (auditoría 2026-10-11:
    creaba de nuevo un broker con el nombre viejo)."""

    def setUp(self):
        for nombre in ("_reconstruir_mtm_post_import", "_reconstruir_en_fila"):
            p = mock.patch.object(main, nombre, side_effect=lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)

    def _importar(self, cta, broker_fijo):
        previa = cta.ok("post", "/api/imports/preview",
                        files=[("files", ("banco.csv", io.BytesIO(_ARCHIVO), "text/csv"))],
                        data={"format": "rendi_generic", "mapping": json.dumps(
                            {"columns": dict(_COLUMNAS), "defaults": {"broker": broker_fijo}})})
        cta.ok("post", "/api/imports/confirm", json={"session_id": previa["session_id"]})
        conn = main.get_db()
        try:
            return ([b["name"] for b in conn.execute(
                         "SELECT name FROM brokers WHERE user_id=? ORDER BY id", (cta.uid,))],
                    sorted({r["broker"] for r in conn.execute(
                        "SELECT broker FROM positions WHERE user_id=? AND is_cash=0", (cta.uid,))}))
        finally:
            conn.close()

    def test_con_el_nombre_de_antes_va_al_broker_de_hoy(self):
        cta = _Cuenta()
        bid = cta.ok("post", "/api/brokers", json={"name": "Zorzal Ñandú", "currency": "USD"})["id"]
        cta.ok("put", f"/api/brokers/{bid}", json={"name": "Zorzal Ávido", "currency": "USD"})
        self.assertEqual(self._importar(cta, "Zorzal Ñandú"), (["Zorzal Ávido"], ["Zorzal Ávido"]))

    def test_un_broker_nuevo_de_verdad_se_sigue_creando(self):
        """La cuenta que escribe su primer broker en el texto libre del asistente."""
        cta = _Cuenta()
        self.assertEqual(self._importar(cta, "Mi Banco"), (["Mi Banco"], ["Mi Banco"]))

    def test_un_mapeo_sin_broker_fijo_o_sin_mapeo_no_cambia_nada(self):
        cta = _Cuenta()
        cta.ok("post", "/api/brokers", json={"name": "Balanz", "currency": "USD"})
        r = cta.pedir("post", "/api/imports/preview",
                      files=[("files", ("banco.csv", io.BytesIO(_ARCHIVO), "text/csv"))],
                      data={"format": "rendi_generic", "mapping": json.dumps({"columns": dict(_COLUMNAS)})})
        self.assertEqual(r.status_code, 400)                 # falta el broker: como antes
        self.assertIn("Broker", r.json()["detail"])


class UnaFilaIlegibleNoEscondeALasDemas(unittest.TestCase):
    """El asistente muestra una lista vacía ante cualquier error al pedir las
    plantillas — el mismo síntoma del 404 que duró cinco meses. Una fila que no se
    puede leer (hoy guardar no deja escribirla; puede haber quedado de antes) se
    saltea, y las demás se sirven."""

    def test_las_demas_plantillas_se_siguen_viendo(self):
        cta = _Cuenta()
        cta.guardar("la buena", {"columns": {"fecha": "Dia"}, "defaults": {}})
        conn = main.get_db()
        try:
            for nombre, texto in (("cortada", '{"columns": {"fecha": "Di'), ("con NaN", '{"columns": {"x": NaN}}'),
                                  ("una lista", '["a"]'), ("un texto", '"hola"')):
                conn.execute("INSERT INTO import_mappings (user_id, name, mapping_json) VALUES (?,?,?)",
                             (cta.uid, nombre, texto))
            conn.commit()
        finally:
            conn.close()
        r = cta.pedir("get", "/api/imports/mappings")
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertEqual([p["name"] for p in r.json()], ["la buena"])

    def test_y_el_renombre_de_un_broker_tampoco_se_frena_por_ella(self):
        cta = _Cuenta()
        bid = cta.ok("post", "/api/brokers", json={"name": "Balanz", "currency": "USD"})["id"]
        conn = main.get_db()
        try:
            conn.execute("INSERT INTO import_mappings (user_id, name, mapping_json) VALUES (?,?,?)",
                         (cta.uid, "cortada", '{"defaults": {"broker": "Bal'))
            conn.commit()
        finally:
            conn.close()
        cta.ok("put", f"/api/brokers/{bid}", json={"name": "Balanz 2", "currency": "USD"})


class ElDetalleDeUnImportSigueAndando(unittest.TestCase):
    """Mover la ruta del detalle abajo de las fijas no la puede romper."""

    def setUp(self):
        for nombre in ("_reconstruir_mtm_post_import", "_reconstruir_en_fila"):
            p = mock.patch.object(main, nombre, side_effect=lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)

    def _importar(self, cta):
        cta.ok("post", "/api/brokers", json={"name": "Banco Ñandú", "currency": "USD"})
        previa = cta.ok("post", "/api/imports/preview",
                        files=[("files", ("banco.csv", io.BytesIO(_ARCHIVO), "text/csv"))],
                        data={"format": "rendi_generic", "mapping": json.dumps(
                            {"columns": dict(_COLUMNAS), "defaults": {"broker": "Banco Ñandú"}})})
        cta.ok("post", "/api/imports/confirm", json={"session_id": previa["session_id"]})
        return cta.ok("get", "/api/imports")[0]["id"]

    def test_el_detalle_de_un_import_trae_el_import_y_sus_filas(self):
        cta = _Cuenta()
        batch = self._importar(cta)
        detalle = cta.ok("get", f"/api/imports/{batch}")
        self.assertEqual(detalle["batch"]["id"], batch)
        self.assertEqual(len(detalle["rows"]), 2)

    def test_un_import_que_no_existe_sigue_dando_404(self):
        r = _Cuenta().pedir("get", f"/api/imports/{uuid.uuid4().hex}")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["detail"], "Batch no encontrado.")

    def test_el_import_de_otra_cuenta_no_se_ve(self):
        una, otra = _Cuenta(), _Cuenta()
        batch = self._importar(una)
        self.assertEqual(otra.pedir("get", f"/api/imports/{batch}").status_code, 404)

    def test_las_rutas_fijas_del_importador_no_caen_en_el_detalle(self):
        """Cada ruta fija de lectura del grupo contesta lo suyo, no "Batch no encontrado"."""
        cta = _Cuenta()
        for camino in ("/api/imports", "/api/imports/mappings", "/api/imports/parsers",
                       "/api/imports/parsers/grouped", "/api/imports/template"):
            r = cta.pedir("get", camino)
            self.assertEqual(r.status_code, 200, f"{camino} → {r.status_code} {r.text[:120]}")


if __name__ == "__main__":
    unittest.main()
