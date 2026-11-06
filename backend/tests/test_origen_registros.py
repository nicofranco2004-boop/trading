"""De dónde viene cada registro, y el conteo de /admin.

El link de cada post lleva un código (`rendi.finance/?d=x-1019`); si no trae,
el navegador anota el sitio de donde venía o la marca que la red le agregó al
link (`sitio/t.co`, `clic/fbclid`). Lo anota al entrar
(frontend/src/utils/origen.js) y lo manda con el registro; acá se prueba la
otra mitad: que /api/auth/register lo guarde en la cuenta y que GET
/api/admin/origenes lo cuente por código y por canal (IA, X, Meta…, ver
canal_de_origen.py), con cuántos confirmaron el mail y cuántos cargaron su
cartera.

Todo por HTTP, como en producción: registro → código del mail → crear broker y
posición con la sesión del usuario → panel del admin. Lo único que se escribe a
mano es el RELOJ (se corre la fecha de alta hacia atrás para sacarla de la
ventana de 7 días).

Las visitas de punta a punta (qué ve el navegador → qué código viaja → qué
canal muestra el panel) están en frontend/src/utils/origen.escenarios.json:
origen.test.js prueba la primera mitad con esa misma lista y este archivo la
segunda.

Corre con: cd backend && python3 -m pytest tests/test_origen_registros.py
"""
import json
import os
import random
import re
import unittest
import uuid
from collections import Counter
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from canal_de_origen import CANALES, MARCAS, canal_del_origen, para_guardar

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UTILS = os.path.join(REPO, "frontend", "src", "utils")
with open(os.path.join(UTILS, "origen.escenarios.json"), encoding="utf-8") as _f:
    ESCENARIOS = json.load(_f)["escenarios"]
IDS = [c for c, _, _ in CANALES]


def setUpModule():
    global _rl
    _rl = patch("main._check_rate_limit")
    _rl.start()


def tearDownModule():
    _rl.stop()


PASS = "Password123$"


class OrigenDeLosRegistros(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:8]
        self.codigo = f"x-1019-{self.tag}"
        conn = main.get_db()
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, approved, is_admin, email_verified) "
            "VALUES (?, 'x', 1, 1, 1)", (f"adm-{self.tag}@rendi.test",))
        self.admin = cur.lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.admin)}"}
        self._mails = patch("billing.emails._send", return_value=True)
        self._mails.start()

    def tearDown(self):
        self._mails.stop()

    # ── el camino real ──────────────────────────────────────────────────────

    def _email(self, quien):
        # Dominio REAL a propósito: @rendi.test queda afuera del conteo.
        return f"{quien}-{self.tag}@ejemplo.com"

    def _q(self, sql, params=()):
        conn = main.get_db()
        try:
            return conn.execute(sql, params).fetchone()
        finally:
            conn.close()

    def _registrar(self, email, **extra):
        """Lo mismo que manda Login.jsx: email, clave, nombre y, si la visita
        trajo código, `origen` + `origen_visto`."""
        r = self.client.post("/api/auth/register",
                             json={"email": email, "password": PASS, "name": "x", **extra})
        self.assertEqual(r.status_code, 200, r.text)
        self.client.cookies.clear()
        return self._q("SELECT * FROM users WHERE email=?", (email,))

    def _confirmar(self, email):
        code = self._q(
            """SELECT code FROM email_verification_codes
               WHERE user_id = (SELECT id FROM users WHERE email=?)
               ORDER BY created_at DESC LIMIT 1""", (email,))["code"]
        r = self.client.post("/api/auth/verify-email", json={"email": email, "code": code})
        self.assertEqual(r.status_code, 200, r.text)
        # Queda con la cookie del usuario puesta: lo que sigue lo hace ÉL, y
        # como la app, diciendo de quién es (main.py, PERSONA_HEADER).
        self._quien = email

    def _cargar_cartera(self):
        persona = {main.PERSONA_HEADER: self._quien}
        r = self.client.post("/api/brokers", json={"name": "Cocos", "currency": "USD"}, headers=persona)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/positions", headers=persona, json={
            "broker": "Cocos", "asset": "KO", "buy_price": 50, "quantity": 2,
            "invested": 100, "entry_date": "2026-02-10"})
        self.assertEqual(r.status_code, 200, r.text)
        self.client.cookies.clear()

    def _panel(self):
        r = self.client.get("/api/admin/origenes", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    @staticmethod
    def _fila(ventana, codigo):
        return next((f for f in ventana["origenes"] if f["origen"] == codigo), None)

    # ── 1. el recorrido entero: link → registro → panel ─────────────────────

    def test_visita_con_codigo_registro_y_aparece_en_el_panel(self):
        visto = (datetime.utcnow() - timedelta(hours=2)).isoformat(timespec="milliseconds") + "Z"
        # Uno entra por el post, se registra, confirma y carga su cartera.
        u1 = self._registrar(self._email("activo"), origen=self.codigo, origen_visto=visto)
        self.assertEqual(u1["origen"], self.codigo)
        self.assertEqual(u1["origen_visto_at"][:13],
                         (datetime.utcnow() - timedelta(hours=2)).strftime("%Y-%m-%d %H"))
        self._confirmar(self._email("activo"))
        self._cargar_cartera()
        # Otro entra por el mismo post, se registra y no confirma el mail.
        self._registrar(self._email("tibio"), origen=self.codigo, origen_visto=visto)
        # Y uno sin código.
        sin = self._registrar(self._email("directo"))
        self.assertIsNone(sin["origen"])

        panel = self._panel()
        for clave in ("7d", "30d"):
            fila = self._fila(panel[clave], self.codigo)
            self.assertEqual(fila, {"origen": self.codigo, "registros": 2,
                                    "confirmaron": 1, "cargaron": 1,
                                    "canal": "x", "fuente": None}, clave)
            self.assertIsNotNone(self._fila(panel[clave], None),
                                 f"{clave}: falta la fila de los que vinieron sin dato")
            self.assertGreaterEqual(panel[clave]["registros"], 3)
            self.assertGreaterEqual(panel[clave]["con_dato"], 2)
            # Los canales suman lo mismo que las filas, columna por columna.
            for k in ("registros", "confirmaron", "cargaron"):
                self.assertEqual(sum(c[k] for c in panel[clave]["canales"]),
                                 sum(f[k] for f in panel[clave]["origenes"]), (clave, k))
        # "Sin dato" va al final, aunque sea la más grande.
        self.assertIsNone(panel["7d"]["origenes"][-1]["origen"])

    def test_lo_que_manda_el_panel(self):
        """Las claves de cada ventana, de cada canal y de cada origen. El
        panel (RegistrosPorOrigen.jsx) se prueba dibujado con estas mismas
        claves (RegistrosPorOrigen.render.test.jsx): si cambian acá, hay que
        cambiarlas allá."""
        self._registrar(self._email("forma"), origen="sitio/t.co")
        panel = self._panel()
        self.assertEqual(set(panel), {"7d", "30d"})
        for clave in ("7d", "30d"):
            v = panel[clave]
            self.assertEqual(set(v), {"desde", "hasta", "registros", "con_dato", "con_codigo", "canales", "origenes"})
            # `con_codigo` es el mismo número, con el nombre que lee el panel anterior.
            self.assertEqual(v["con_codigo"], v["con_dato"])
            for c in v["canales"]:
                self.assertEqual(set(c), {"canal", "nombre", "explica", "registros", "confirmaron", "cargaron"})
            for f in v["origenes"]:
                self.assertEqual(set(f), {"origen", "registros", "confirmaron", "cargaron", "canal", "fuente"})

    # ── 1b. cada visita de prueba termina en su canal ───────────────────────

    def test_cada_visita_llega_a_su_canal_en_el_panel(self):
        """El código que manda el navegador para cada visita de
        origen.escenarios.json → /api/auth/register → /api/admin/origenes: la
        fila de ese código está en su canal y el resumen por canal sube en lo
        que tiene que subir."""
        antes = self._panel()
        visto = (datetime.utcnow() - timedelta(minutes=5)).isoformat(timespec="milliseconds") + "Z"
        for i, e in enumerate(ESCENARIOS):
            extra = {"origen": e["codigo"], "origen_visto": visto} if e["codigo"] else {}
            u = self._registrar(self._email(f"visita{i}"), **extra)
            # El servidor guarda el código tal como lo mandó el navegador, salvo
            # el nombre de un sitio o una app que no conoce («otro»).
            self.assertEqual(u["origen"], e.get("guardado", e["codigo"]), e["caso"])
        despues = self._panel()
        esperado = Counter(e["canal"] for e in ESCENARIOS)
        for clave in ("7d", "30d"):
            subio = {c["canal"]: c["registros"] - a["registros"]
                     for c, a in zip(despues[clave]["canales"], antes[clave]["canales"])}
            self.assertEqual(subio, {c: esperado.get(c, 0) for c in IDS}, clave)
            self.assertEqual([c["canal"] for c in despues[clave]["canales"]], IDS)
            # «de N se sabe de dónde vinieron»: todos menos los que no traían nada.
            self.assertEqual(despues[clave]["con_dato"] - antes[clave]["con_dato"],
                             sum(1 for e in ESCENARIOS if e["codigo"]), clave)
        for e in ESCENARIOS:
            fila = self._fila(despues["7d"], e.get("guardado", e["codigo"]))
            self.assertEqual(fila["canal"], e["canal"], e["caso"])
            if "fuente" in e:
                self.assertEqual(fila["fuente"], e["fuente"], e["caso"])

    # ── 2. la ventana de días ───────────────────────────────────────────────

    def test_un_registro_de_hace_10_dias_cuenta_en_30_y_no_en_7(self):
        u = self._registrar(self._email("viejo"), origen=self.codigo)
        conn = main.get_db()
        try:
            hace_10 = (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE users SET created_at=? WHERE id=?", (hace_10, u["id"]))
            conn.commit()
        finally:
            conn.close()
        panel = self._panel()
        self.assertIsNone(self._fila(panel["7d"], self.codigo))
        self.assertEqual(self._fila(panel["30d"], self.codigo)["registros"], 1)

    # ── 3. el código nunca rechaza un registro ──────────────────────────────

    def test_un_codigo_raro_se_limpia_y_el_registro_entra(self):
        u = self._registrar(self._email("raro"), origen="  IG 20261019<script>!  ",
                            origen_visto="no es una fecha")
        self.assertEqual(u["origen"], "ig-20261019script")
        self.assertIsNone(u["origen_visto_at"])

    def test_una_fecha_que_no_entra_en_utc_no_tumba_el_registro(self):
        # Se entiende, pero pasada a UTC cae después del año 9999: daba 500.
        self.assertIsNone(main._normalizar_origen_visto("9999-12-31T23:59:59-23:59"))
        u = self._registrar(self._email("fecha"), origen=self.codigo,
                            origen_visto="9999-12-31T23:59:59-23:59")
        self.assertEqual(u["origen"], self.codigo)
        self.assertIsNone(u["origen_visto_at"])

    def test_de_un_sitio_o_una_app_que_no_conoce_no_se_guarda_el_nombre(self):
        """Por HTTP, aunque lo mande otro que no es el navegador: el nombre de
        un sitio o una app que no está en la tabla puede ser un dato de la
        persona (dónde trabaja, qué apps usa)."""
        for i, (manda, queda) in enumerate([
            ("sitio/intranet.banco-ejemplo.com.ar", "sitio/otro"),
            ("sitio/181.46.12.200/fbclid", "sitio/otro/fbclid"),
            ("app/com.desconocida.citas", "app/otro"),
            ("clic/inventada", "clic/otra"),
            ("sitio/l.instagram.com/fbclid", "sitio/l.instagram.com/fbclid"),
            ("x-20261019", "x-20261019"),
        ]):
            u = self._registrar(self._email(f"nombre{i}"), origen=manda)
            self.assertEqual(u["origen"], queda, manda)

    def test_basura_en_el_origen_no_da_422(self):
        for i, (origen, visto) in enumerate([
            (12345, 99), ({"a": 1}, ["x"]), ("x" * 5000, "2099-01-01T00:00:00Z"), ("¡¡¡", None),
        ]):
            u = self._registrar(self._email(f"basura{i}"), origen=origen, origen_visto=visto)
            self.assertIn(u["origen"], (None, "x" * 60), (origen, u["origen"]))
            # Una fecha del futuro no fecha el clic.
            self.assertIsNone(u["origen_visto_at"])

    # ── 4. quién entra en la cuenta ─────────────────────────────────────────

    def test_cuentas_internas_y_clientes_de_asesor_no_cuentan(self):
        r = self.client.post("/api/auth/register", json={
            "email": f"interno-{self.tag}@rendi.test", "password": PASS, "name": "x",
            "origen": self.codigo})
        self.assertEqual(r.status_code, 200, r.text)
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO users (email, password_hash, managed_by, origen) VALUES (?, 'x', ?, ?)",
                (self._email("cliente"), self.admin, self.codigo))
            conn.commit()
        finally:
            conn.close()
        self.assertIsNone(self._fila(self._panel()["7d"], self.codigo))

    def test_sin_ser_admin_no_se_ve(self):
        self._registrar(self._email("curioso"))
        self._confirmar(self._email("curioso"))
        r = self.client.get("/api/admin/origenes")
        self.assertIn(r.status_code, (401, 403), r.text)


class LaMismaReglaQueElNavegador(unittest.TestCase):
    """`_normalizar_origen` y `normalizarCodigo` (utils/origen.js) tienen que
    limpiar igual: los mismos casos están en origen.test.js."""

    def test_casos(self):
        casos = {
            "x-20261019": "x-20261019",
            "IG-20261019": "ig-20261019",
            "  x 1019 ": "x-1019",
            "x/campaña": "x/campaa",
            "<b>": "b",
            "": None,
            "!!!": None,
            "ana@x.com": None,
        }
        for entrada, esperado in casos.items():
            self.assertEqual(main._normalizar_origen(entrada), esperado, entrada)

    def test_lo_que_se_limpia_nunca_pasa_de_256_caracteres(self):
        """Un origen de 40 MB pasaba entero por las dos limpiezas (más de un
        segundo frenando al servidor para todos). Se mira el largo de lo que
        entra a cada limpieza, no el tiempo: un umbral de tiempo da rojo falso
        en una máquina cargada."""
        import re as _re
        largos = []
        original = _re.sub

        def anotar(patron, reemplazo, texto, *a, **k):
            largos.append(len(texto))
            return original(patron, reemplazo, texto, *a, **k)

        with patch("re.sub", anotar):
            self.assertEqual(main._normalizar_origen(" a" * 1_000_000), ("a-" * 30)[:60])
        self.assertTrue(largos)
        self.assertLessEqual(max(largos), 256)

    def test_las_marcas_que_anota_el_navegador_son_las_que_conoce_el_servidor(self):
        """MARCAS_DE_CLIC (origen.js) y MARCAS (canal_de_origen.py): la misma
        lista y en el mismo orden. Una marca que el navegador anota y el
        servidor no conoce caería en «Otro sitio o app»; una que el servidor
        conoce y el navegador no busca, nunca llegaría."""
        with open(os.path.join(UTILS, "origen.js"), encoding="utf-8") as f:
            js = f.read()
        m = re.search(r"export const MARCAS_DE_CLIC = \[([^\]]*)\]", js)
        self.assertIsNotNone(m, "origen.js ya no declara MARCAS_DE_CLIC como lista")
        self.assertEqual(re.findall(r"'([^']+)'", m.group(1)), list(MARCAS))


class ElCanalDeCadaOrigen(unittest.TestCase):
    """`canal_del_origen`, el único que decide qué canal es cada origen
    guardado: también los códigos que ya están en la base desde antes."""

    CASOS = {
        # Códigos que ya hay en producción.
        "chatgpt.com": "ia",
        "x-20261019": "x",
        "prueba": "otro_codigo",
        # El código de los anuncios de Meta, con lo que puede escribir una persona.
        "meta-anuncios/promo-noviembre": "meta_anuncios",
        "meta-anuncios": "meta_anuncios",
        "meta_anuncios/x": "meta_anuncios",
        "meta-ads": "meta_anuncios",
        "metaads": "meta_anuncios",                 # utm_source=MetaAds
        "metaanuncios/promo": "meta_anuncios",
        "meta-anunciosx": "meta_sin_saber",        # no es el código ni la forma de un post
        # Los posts de Nico con su código, y los utm de Meta de alguien más.
        "ig-20261022": "meta_posts",
        "fb_1020": "meta_posts",
        "ig-stories/1022": "meta_sin_saber",         # «tus posts» es sólo red-fecha
        "ig": "meta_sin_saber",
        "ig/campana": "meta_sin_saber",
        "fb/promo-noviembre": "meta_sin_saber",
        "instagram/bio": "meta_sin_saber",
        "facebook.com": "meta_sin_saber",
        # …y si el código dice que es un anuncio, es un anuncio.
        "ig-anuncio-1022": "meta_anuncios",
        "facebook-ads/noviembre": "meta_anuncios",
        "fb/anuncios-noviembre": "meta_anuncios",
        "ig/paid": "meta_anuncios",
        "x-anuncio": "x",
        # Otras redes en un código.
        "x/post-1019": "x",
        "twitter": "x",
        "t.co": "x",
        "google/cpc": "google",
        "perplexity": "ia",
        "perplexity.ai/respuesta": "ia",
        "mail-1020": "otro_codigo",
        "xmas-promo": "otro_codigo",
        "igualdad": "otro_codigo",
        # Sitios: cuentan sus subdominios, sólo enteros.
        "sitio/lm.facebook.com": "meta_sin_saber",
        "sitio/web.facebook.com": "meta_sin_saber",
        "sitio/instagram.com": "meta_sin_saber",
        "sitio/threads.net": "meta_sin_saber",
        "sitio/notfacebook.com": "otro_sitio",
        "sitio/facebook.com.otro-sitio.io": "otro_sitio",
        "sitio/mobile.twitter.com": "x",
        "sitio/google.com": "google",
        "sitio/google.co.uk": "google",
        "sitio/google.es": "google",
        "sitio/www.google.com.ar": "google",
        "sitio/gemini.google.com": "ia",
        "sitio/mail.google.com": "otro_sitio",
        "sitio/accounts.google.com": "otro_sitio",
        "sitio/googlear.com": "otro_sitio",
        "sitio/chat.openai.com": "ia",
        "sitio/www.perplexity.ai": "ia",
        "sitio/meta.ai": "ia",
        # La marca le gana al sitio, salvo que el sitio sea de OTRA red con
        # nombre propio: entonces alguien copió la dirección y la compartió ahí.
        "sitio/t.co/gclid": "x",
        "sitio/t.co/fbclid": "x",
        "sitio/chatgpt.com/fbclid": "ia",
        "sitio/google.com/fbclid": "google",
        "sitio/mail.google.com/gclid": "google",     # anuncio de Google en Gmail
        "sitio/linkedin.com/fbclid": "meta_sin_saber",
        "app/com.whatsapp/fbclid": "meta_sin_saber",
        "sitio/linktr.ee/fbclid": "meta_sin_saber",
        "sitio/l.facebook.com/raro": "meta_sin_saber",
        "clic/fbclid": "meta_sin_saber",
        "clic/twclid": "x",
        "clic/wbraid": "google",
        "clic/msclkid": "otro_sitio",
        "clic/inventada": "otro_sitio",
        "clic/": "otro_codigo",
        "app/com.instagram.barcelona": "meta_sin_saber",
        "app/ai.x.grok": "ia",
        "app/com.desconocida.app": "otro_sitio",
        "app/com.google.android.gm/fbclid": "meta_sin_saber",
        "sitio/": "otro_codigo",
        # Anuncios de Meta como los puede escribir una persona o la plantilla
        # del Administrador de anuncios…
        "meta-ad": "meta_anuncios",
        "fb-ad": "meta_anuncios",
        "ig-pauta": "meta_anuncios",
        "meta-publicidad": "meta_anuncios",
        "meta-pago": "meta_anuncios",
        "meta-cpc": "meta_anuncios",
        "fb_cpc": "meta_anuncios",
        "meta-retargeting": "meta_anuncios",
        "instagram-sponsored": "meta_anuncios",
        "meta-ads2026": "meta_anuncios",
        "meta-anuncios2026/promo": "meta_anuncios",
        "fb/paid2026/promo": "meta_anuncios",       # la palabra con números, en el medio
        "ig-20261022/pauta2": "meta_anuncios",
        "metaad": "meta_anuncios",                  # utm_source=MetaAd
        "fbads": "meta_anuncios",
        "fb/paid/promo": "meta_anuncios",
        "ig/paid_social/promo": "meta_anuncios",
        "fbadmin": "otro_codigo",
        # …y códigos de Meta que no son los posts de Nico ni dicen anuncio.
        "instagram_story": "meta_sin_saber",
        "ig_story": "meta_sin_saber",
        "facebook_group": "meta_sin_saber",
        "fb-share": "meta_sin_saber",
        "ig-influencer/juan": "meta_sin_saber",
        "instagram/social/bio": "meta_sin_saber",
        "msg/promo": "meta_sin_saber",
        "an/promo": "meta_sin_saber",
        "insta-20261022": "meta_posts",
        "face-1020": "meta_posts",
        "threads-20261022": "meta_posts",
        # Sitios y apps que faltaban.
        "sitio/m.me": "meta_sin_saber",
        "sitio/ig.me": "meta_sin_saber",
        "sitio/pplx.ai": "ia",
        "sitio/notebooklm.google.com": "ia",
        "sitio/aistudio.google.com": "ia",
        "sitio/m365.cloud.microsoft": "ia",
        "sitio/images.google.com": "google",
        "app/com.google.android.apps.magazines": "google",
        # Lo que guarda el servidor de un sitio, una app o una marca que no conoce.
        "sitio/otro": "otro_sitio",
        "sitio/otro/fbclid": "meta_sin_saber",
        "app/otro": "otro_sitio",
        "clic/otra": "otro_sitio",
        "sitio-chatgpt.com": "otro_codigo",          # ?d=sitio/chatgpt.com, neutralizado
        # Sin dato.
        "": "sin_dato",
        "   ": "sin_dato",
    }

    def test_casos(self):
        for codigo, esperado in self.CASOS.items():
            self.assertEqual(canal_del_origen(codigo)[0], esperado, codigo)
        self.assertEqual(canal_del_origen(None), ("sin_dato", None))

    def test_dice_de_donde_cuando_lo_sabe(self):
        self.assertEqual(canal_del_origen("sitio/l.instagram.com/fbclid"), ("meta_sin_saber", "Instagram"))
        self.assertEqual(canal_del_origen("sitio/linktr.ee/fbclid"), ("meta_sin_saber", "Facebook o Instagram"))
        self.assertEqual(canal_del_origen("app/com.google.android.gm"), ("otro_sitio", "Gmail"))
        self.assertEqual(canal_del_origen("chatgpt.com"), ("ia", "ChatGPT"))
        self.assertEqual(canal_del_origen("sitio/blog.ejemplo.com"), ("otro_sitio", None))
        self.assertEqual(canal_del_origen("x-20261019"), ("x", None))

    def test_si_dos_sitios_coinciden_gana_el_mas_largo(self):
        """Hoy ningún sitio de la tabla es subdominio de otro; el día que se
        sume uno (`google.com` entero, por ejemplo), Gemini tiene que seguir
        siendo IA y no Google."""
        import canal_de_origen
        # El sitio corto PRIMERO en la tabla: si ganara el primero que coincide, se vería.
        con_google = {"google.com": ("Google", "google"), **canal_de_origen._SITIOS}
        with patch.object(canal_de_origen, "_SITIOS", con_google):
            self.assertEqual(canal_del_origen("sitio/gemini.google.com")[0], "ia")
            self.assertEqual(canal_del_origen("sitio/accounts.google.com")[0], "google")

    def test_cada_canal_tiene_nombre_y_explicacion(self):
        self.assertEqual(len(IDS), len(set(IDS)))
        for c, nombre, explica in CANALES:
            self.assertTrue(nombre.strip() and explica.strip(), c)

    def test_todas_las_filas_de_las_tablas_apuntan_a_un_canal_que_existe(self):
        """Un canal mal escrito en una fila (`"meta"` en vez de
        `"meta_sin_saber"`) tumbaba /api/admin/origenes con un KeyError."""
        import canal_de_origen as c
        for tabla in (c.MARCAS, c._SITIOS, c._APPS):
            for nombre, (fuente, canal) in tabla.items():
                self.assertIn(canal, IDS, nombre)
                self.assertTrue(fuente.strip(), nombre)
        self.assertLessEqual(set(c._REDES_EN_CODIGOS.values()), set(IDS) | {"meta"})

    def test_una_fila_mal_escrita_no_tumba_el_panel(self):
        import canal_de_origen as c
        roto = {**c._SITIOS, "roto.com": ("Roto", "meta")}
        with patch.object(c, "_SITIOS", roto):
            self.assertEqual(canal_del_origen("sitio/roto.com"), ("otro_sitio", "Roto"))
            self.assertEqual(canal_del_origen("roto.com/x")[0], "otro_codigo")

    def test_lo_que_se_guarda(self):
        """`para_guardar`: el nombre de un sitio o una app sólo si está en la
        tabla; la marca sólo si es de la lista; los códigos del link, como
        vinieron."""
        casos = {
            "sitio/l.instagram.com/fbclid": "sitio/l.instagram.com/fbclid",
            "sitio/google.com.ar/gclid": "sitio/google.com.ar/gclid",
            "app/com.whatsapp": "app/com.whatsapp",
            "sitio/intranet.banco-ejemplo.com.ar": "sitio/otro",
            "sitio/juanperez.github.io/fbclid": "sitio/otro/fbclid",
            "sitio/notebook-de-juan": "sitio/otro",
            "sitio/181.46.12.200": "sitio/otro",
            "app/com.desconocida.citas": "app/otro",
            "sitio/t.co/raro": "sitio/t.co",
            "clic/fbclid": "clic/fbclid",
            "clic/inventada": "clic/otra",
            "x-20261019": "x-20261019",
            "meta-anuncios/promo": "meta-anuncios/promo",
            "juanperez.github.io": "juanperez.github.io",   # un utm que eligió quien armó el link
            None: None,
        }
        for entra, sale in casos.items():
            self.assertEqual(para_guardar(entra), sale, entra)

    def test_lo_que_se_guarda_al_azar_sigue_limpio_y_en_su_canal(self):
        rnd = random.Random(611)
        letras = "abcdefghijklmnopqrstuvwxyz0123456789._/-"
        prefijos = ("sitio/", "app/", "clic/", "sitio/l.facebook.com/", "x-", "")
        for _ in range(3000):
            codigo = main._normalizar_origen(rnd.choice(prefijos) + "".join(
                rnd.choice(letras) for _ in range(rnd.randint(0, 60))))
            guardado = para_guardar(codigo)
            # Lo que se guarda pasa la limpieza sin cambios y no cambia de canal
            # salvo para ir a «otro».
            self.assertEqual(main._normalizar_origen(guardado), guardado, codigo)
            if guardado != codigo:
                self.assertTrue(guardado.startswith(("sitio/otro", "app/otro", "clic/otra"))
                                or canal_del_origen(guardado)[0] == canal_del_origen(codigo)[0], codigo)

    def test_al_azar_nunca_rompe_y_siempre_da_un_canal(self):
        rnd = random.Random(20261106)
        letras = "abcdefghijklmnopqrstuvwxyz0123456789._/- ÁñÑ¿?<>%&=#\t\n‮😀"
        prefijos = ("", "sitio/", "app/", "clic/", "meta", "x-", "ig-", "www.", "sitio/www.")
        no_texto = (None, 0, 123, 1.5, True, [], {}, b"x-1", ("x",))
        for _ in range(5000):
            crudo = rnd.choice(prefijos) + "".join(rnd.choice(letras) for _ in range(rnd.randint(0, 80)))
            for codigo in (crudo, main._normalizar_origen(crudo)):
                canal, fuente = canal_del_origen(codigo)
                self.assertIn(canal, IDS, repr(codigo))
                self.assertTrue(fuente is None or isinstance(fuente, str), repr(codigo))
        for cosa in no_texto:
            self.assertEqual(canal_del_origen(cosa), ("sin_dato", None), repr(cosa))

    def test_un_codigo_raro_cae_en_otro(self):
        rnd = random.Random(7)
        for _ in range(2000):
            raro = "zz" + "".join(rnd.choice("abcdefghijklmnopqrstuvwxyz0123456789-_") for _ in range(rnd.randint(0, 40)))
            self.assertEqual(canal_del_origen(raro)[0], "otro_codigo", raro)
            self.assertEqual(canal_del_origen("sitio/" + raro + ".io")[0], "otro_sitio", raro)
            self.assertEqual(canal_del_origen("app/" + raro)[0], "otro_sitio", raro)


if __name__ == "__main__":
    unittest.main()
