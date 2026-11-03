"""`scripts/pasaje_con_mantenimiento.py`: lo que se usa el día del pasaje con la app CERRADA.

QUÉ PROTEGE. El día del pasaje la app está en modo mantenimiento: todo pedido sin la
llave da 503. El respaldo (paso 3) y la comparación de pantallas (paso 8) tienen que
poder hacerse igual, **sin que la llave ni la contraseña pasen por el chat ni queden
en el historial de la Terminal**. Si el script se equivoca el día del pasaje, no hay
segunda oportunidad con la base vieja.

POR QUÉ NO ES UN SERVIDOR FALSO. Una versión anterior se probó contra un servidor de
juguete que contestaba lo que el script esperaba: eso certifica que el script entiende a
su propio juguete, no a la app. Acá se levanta la app DE VERDAD (uvicorn, el mismo
`main.app` con el middleware de mantenimiento, el login real, el disparador real del
respaldo) en un puerto local, y el script le habla por HTTP como el día real. Lo único
que se reemplaza es el TECLADO (mail y contraseña, que el día real se tipean) y la
subida a Cloudflare R2 (no hay red). Corre con SQLite o con Postgres
(`DATABASE_URL`): el motor lo dice la app misma.

Corre con: cd backend && python3 -m pytest tests/test_pasaje_con_mantenimiento.py
"""
import contextlib
import gzip
import io
import json
import os
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
RAIZ = os.path.dirname(BACKEND)
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import main  # noqa: E402
import pasaje_con_mantenimiento as P  # noqa: E402

LLAVE = "llave-de-prueba-" + uuid.uuid4().hex
CLAVE = "Contrasena-de-prueba-1$" + uuid.uuid4().hex[:6]
_VARS = ("RENDI_MANTENIMIENTO", "RENDI_MANTENIMIENTO_TOKEN", "RENDI_PASAJE_COMPLETO", "HOME",
         "BACKUP_LOCAL_DIR", "BACKUP_S3_BUCKET", "BACKUP_S3_ENDPOINT", "BACKUP_S3_ACCESS_KEY",
         "BACKUP_S3_SECRET_KEY", "RENDI_URL")


def setUpModule():
    global _rl, _srv, URL
    _rl = patch("main._check_rate_limit")
    _rl.start()
    import uvicorn
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    # lifespan="off": no corre los `startup` de la app (el programador de fotos y mails).
    _srv = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port,
                                         log_level="error", lifespan="off"))
    threading.Thread(target=_srv.run, daemon=True).start()
    URL = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(URL + "/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise unittest.SkipTest("no levantó la app de prueba")


def tearDownModule():
    _srv.should_exit = True
    _rl.stop()


class _ConAppCerrada(unittest.TestCase):
    """La app real en mantenimiento, una Mac de mentira (HOME temporal) y un teclado
    que tipea lo que cada test le diga."""

    def setUp(self):
        self._previo = {k: os.environ.get(k) for k in _VARS}
        self.casa = tempfile.mkdtemp(prefix="pasaje-casa-")
        self.respaldos = tempfile.mkdtemp(prefix="pasaje-resp-")
        for k in _VARS:
            os.environ.pop(k, None)
        os.environ.update({"RENDI_MANTENIMIENTO": "1", "RENDI_MANTENIMIENTO_TOKEN": LLAVE,
                           "HOME": self.casa, "BACKUP_LOCAL_DIR": self.respaldos})
        self._mails = patch("billing.emails._send", return_value=True)
        self._mails.start()
        tag = uuid.uuid4().hex[:8]
        self.admin_mail = f"adm{tag}@rendi.test"
        self.user_mail = f"usr{tag}@rendi.test"
        conn = main.get_db()
        h = main.pwd_ctx.hash(CLAVE)
        self.admin_id = conn.execute(
            "INSERT INTO users (email, password_hash, approved, is_admin, email_verified) "
            "VALUES (?, ?, 1, 1, 1)", (self.admin_mail, h)).lastrowid
        self.user_id = conn.execute(
            "INSERT INTO users (email, password_hash, approved, is_admin, email_verified) "
            "VALUES (?, ?, 1, 0, 1)", (self.user_mail, h)).lastrowid
        conn.commit()
        conn.close()
        P.escribir_privado(P.ruta_llave(), LLAVE)

    def tearDown(self):
        self._mails.stop()
        for k, v in self._previo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def correr(self, *args, mail=None, clave=CLAVE, url=None):
        """Corre el script como lo corre Nico. Devuelve (código, todo lo que imprimió)."""
        argv = list(args)
        if url is not False and "llave" not in argv and "comparar" not in argv:
            argv += ["--url", url or URL]
        teclado_mail = mail if mail is not None else self.admin_mail
        salida = io.StringIO()
        codigo = 0
        with patch.object(P, "pedir_mail", lambda *_: teclado_mail), \
                patch.object(P, "pedir_secreto", lambda *_: clave), \
                contextlib.redirect_stdout(salida):
            try:
                P.main(argv)
            except SystemExit as e:
                if isinstance(e.code, str):
                    salida.write("\n" + e.code)
                    codigo = 1
                else:
                    codigo = e.code or 0
        texto = salida.getvalue()
        # Lo que no puede pasar nunca, en NINGUNA corrida: ni la llave, ni la contraseña,
        # ni el token de sesión aparecen en lo que se imprime.
        self.assertNotIn(LLAVE, texto)
        self.assertNotIn(CLAVE, texto)
        self.assertNotIn("eyJ", texto, "se imprimió un token de sesión")
        self.assertNotIn(LLAVE, " ".join(argv))
        self.assertNotIn(CLAVE, " ".join(argv))
        return codigo, texto

    def con_header(self, token=None):
        h = {"x-rendi-bypass": LLAVE}
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h


class LaPuertaYLaLlave(_ConAppCerrada):

    def test_sin_la_llave_la_app_da_503_y_con_ella_el_script_entra(self):
        """Las dos mitades: la app SÍ está cerrada (si no, esto no probaría nada)
        y el script, con la llave del archivo, pasa."""
        self.assertEqual(httpx.get(URL + "/api/operations").status_code, 503)
        codigo, texto = self.correr("pantallas", "antes")
        self.assertEqual(codigo, 0, texto)
        self.assertIn("estado 200", texto)
        self.assertNotIn("estado 503", texto)

    def test_con_una_llave_que_no_es_la_de_la_app_el_script_se_frena_con_un_motivo(self):
        P.escribir_privado(P.ruta_llave(), "otra-llave")
        codigo, texto = self.correr("pantallas", "antes")
        self.assertEqual(codigo, 1)
        self.assertIn("503", texto)
        self.assertIn("RENDI_MANTENIMIENTO_TOKEN", texto)
        self.assertFalse(os.path.exists(P.carpeta_pantallas()), "no debió guardar nada")

    def test_sin_llave_guardada_dice_cual_comando_correr(self):
        os.unlink(P.ruta_llave())
        codigo, texto = self.correr("respaldo")
        self.assertEqual(codigo, 1)
        self.assertIn("llave", texto)

    def test_un_archivo_de_llave_que_lee_otra_gente_se_rechaza(self):
        os.chmod(P.ruta_llave(), 0o644)
        codigo, texto = self.correr("respaldo")
        self.assertEqual(codigo, 1)
        self.assertIn("chmod 600", texto)

    def test_contrasena_mala_no_hace_nada(self):
        codigo, texto = self.correr("respaldo", clave="no-es")
        self.assertEqual(codigo, 1)
        self.assertIn("401", texto)
        self.assertEqual(os.listdir(self.respaldos), [], "no debió disparar el respaldo")


class LaDireccionNoEstaEscritaEnElCodigo(_ConAppCerrada):

    def test_sin_direccion_no_hace_nada_y_dice_donde_mirarla(self):
        codigo, texto = self.correr("respaldo", url=False)
        self.assertEqual(codigo, 1)
        self.assertIn("--url", texto)
        self.assertIn("Settings → Domains", texto)

    def test_la_variable_de_entorno_alcanza(self):
        os.environ["RENDI_URL"] = URL
        codigo, texto = self.correr("pantallas", "antes", url=False)
        self.assertEqual(codigo, 0, texto)

    def test_http_a_un_servidor_que_no_es_local_se_rechaza(self):
        """La llave viaja en cada pedido: nunca en claro por internet."""
        codigo, texto = self.correr("respaldo", url="http://rendi.example.com")
        self.assertEqual(codigo, 1)
        self.assertIn("https", texto)

    def test_el_codigo_no_trae_ninguna_direccion_de_produccion(self):
        fuente = open(os.path.join(RAIZ, "scripts", "pasaje_con_mantenimiento.py")).read()
        for prohibida in ("railway.app", "rendi.finance", "vercel.app"):
            self.assertNotIn(prohibida, fuente)


class ElRespaldo(_ConAppCerrada):

    def _s3_de_mentira(self):
        # Sólo la subida a Cloudflare (no hay red): todo lo demás corre de verdad.
        return patch("scripts.backup_db.upload_to_s3", return_value=(True, None))

    @unittest.skipIf(main.USANDO_PG, "el día del pasaje la app todavía está en SQLite")
    def test_respaldo_de_sqlite_con_la_app_cerrada(self):
        with self._s3_de_mentira():
            codigo, texto = self.correr("respaldo")
        self.assertEqual(codigo, 0, texto)
        self.assertIn("motor:           sqlite", texto)
        self.assertIn("✅ Respaldo hecho y subido", texto)
        # El archivo existe, es un gzip entero y trae lo que el cuadro dice.
        archivos = [f for f in os.listdir(self.respaldos) if f.startswith("trading-")]
        self.assertEqual(len(archivos), 1, archivos)
        ruta = os.path.join(self.respaldos, archivos[0])
        crudo = os.path.join(self.casa, "bajado.db")
        with gzip.open(ruta) as g, open(crudo, "wb") as out:
            out.write(g.read())
        db = sqlite3.connect(crudo)
        usuarios = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        db.close()
        self.assertIn(f"usuarios:        {usuarios}", texto)
        self.assertIn(f"tamaño (bytes):  {os.path.getsize(ruta)}", texto)

    @unittest.skipIf(main.USANDO_PG, "el día del pasaje la app todavía está en SQLite")
    def test_si_no_subio_a_r2_no_dice_que_esta_bien(self):
        """Nico baja el archivo de R2: un respaldo que sólo quedó en el disco de Railway
        no le sirve, y el script no puede decirle «hecho»."""
        codigo, texto = self.correr("respaldo")        # sin S3 configurado: sube nada
        self.assertEqual(codigo, 1)
        self.assertIn("subido afuera:   NO", texto)
        self.assertIn("NO está bien", texto)

    @unittest.skipUnless(main.USANDO_PG, "se prueba con DATABASE_URL puesta")
    def test_si_la_app_ya_esta_en_postgres_el_script_frena(self):
        with self._s3_de_mentira():
            codigo, texto = self.correr("respaldo")
        self.assertEqual(codigo, 1)
        self.assertIn("motor:           postgres", texto)
        self.assertIn("El respaldo dice que es de Postgres", texto)

    def test_una_cuenta_que_no_es_admin_no_dispara_nada(self):
        with self._s3_de_mentira():
            codigo, texto = self.correr("respaldo", mail=self.user_mail)
        self.assertEqual(codigo, 1)
        self.assertIn("no es de administrador", texto)
        self.assertEqual(os.listdir(self.respaldos), [])


class ComparoLoQueMuestraLaApp(_ConAppCerrada):
    """Contra la app real: «antes» y «despues» de una misma cuenta."""

    def _depositar(self, monto):
        tok = main.create_token(self.user_id)
        h = self.con_header(tok)
        if not getattr(self, "_con_broker", False):      # el plan Free admite un solo broker
            r = httpx.post(URL + "/api/brokers", headers=h, json={"name": "Cocos", "currency": "ARS"})
            self.assertEqual(r.status_code, 200, r.text)
            self._con_broker = True
            # Un movimiento real, para que Movimientos tenga una fila que comparar.
            r = httpx.post(URL + "/api/operations", headers=h, json={
                "date": "2026-01-05", "broker": "Cocos", "asset": "AL30", "op_type": "venta",
                "entry_price": 50.0, "exit_price": 55.0, "quantity": 10, "pnl_usd": 50.0,
                "currency": "ARS"}, timeout=30)
            self.assertEqual(r.status_code, 200, r.text)
        r = httpx.post(URL + "/api/cash/flow", headers=h, json={
            "broker_name": "Cocos", "direction": "deposit", "amount": monto}, timeout=30)
        self.assertEqual(r.status_code, 200, r.text)

    def test_sin_cambios_entre_antes_y_despues_da_cero_diferencias(self):
        self._depositar(1000)
        self.assertEqual(self.correr("pantallas", "antes", mail=self.user_mail)[0], 0)
        self.assertEqual(self.correr("pantallas", "despues", mail=self.user_mail)[0], 0)
        codigo, texto = self.correr("comparar")
        self.assertEqual(codigo, 0, texto)
        self.assertIn("SIN DIFERENCIAS", texto)
        self.assertIn("/api/operations", texto)
        # tiene que haber algo que comparar (si no, el «sin diferencias» no dice nada)
        antes = json.load(open(os.path.join(P.carpeta_pantallas(),
                                            f"pantallas-antes-{self.user_mail.split('@')[0]}.json")))
        self.assertGreaterEqual(len(antes["pantallas"]["/api/operations"]["json"]), 1)
        self.assertGreaterEqual(len(antes["pantallas"]["/api/monthly"]["json"]), 1)

    def test_si_entre_antes_y_despues_cambia_algo_lo_marca_y_no_deja_seguir(self):
        self._depositar(1000)
        self.correr("pantallas", "antes", mail=self.user_mail)
        self._depositar(500)                          # «alguien escribió en el medio»
        self.correr("pantallas", "despues", mail=self.user_mail)
        codigo, texto = self.correr("comparar")
        self.assertEqual(codigo, 1, texto)
        self.assertIn("❌ /api/monthly", texto)
        self.assertIn("deposits", texto)
        self.assertIn("NO abras", texto)

    def test_los_archivos_de_pantallas_son_privados(self):
        self.correr("pantallas", "antes", mail=self.user_mail)
        self.assertEqual(os.stat(P.carpeta_pantallas()).st_mode & 0o777, 0o700)
        for f in os.listdir(P.carpeta_pantallas()):
            self.assertEqual(os.stat(os.path.join(P.carpeta_pantallas(), f)).st_mode & 0o777, 0o600)

    def test_comparar_sin_nada_guardado_lo_dice(self):
        codigo, texto = self.correr("comparar")
        self.assertEqual(codigo, 1)
        self.assertIn("pantallas antes", texto)


class LaComparacionEnSi(_ConAppCerrada):
    """Archivos armados a mano: lo que Postgres hace distinto y NO es un error, y lo que sí."""

    def _guardar(self, cuando, operaciones, mensual, fotos):
        os.makedirs(P.carpeta_pantallas(), exist_ok=True)
        P.escribir_privado(
            os.path.join(P.carpeta_pantallas(), f"pantallas-{cuando}-cuenta.json"),
            json.dumps({"cuenta": "x", "pantallas": {
                "/api/operations": {"estado": 200, "json": operaciones},
                "/api/monthly": {"estado": 200, "json": mensual},
                "/api/snapshots?days=3650": {"estado": 200, "json": fotos}}}))

    OPS = [{"id": 1, "date": "2026-01-01", "monto": 10.0}, {"id": 2, "date": "2026-01-01", "monto": 20.0}]
    MES = [{"id": 5, "year": 2026, "month": 1, "broker": "b", "pnl": 1.0}]
    FOTOS = [{"date": "2026-01-02", "total_value": 100.0}]

    def test_el_orden_de_los_movimientos_y_el_id_del_mensual_no_cuentan(self):
        self._guardar("antes", self.OPS, self.MES, self.FOTOS)
        self._guardar("despues", self.OPS[::-1], [dict(self.MES[0], id=99)], self.FOTOS)
        codigo, texto = self.correr("comparar")
        self.assertEqual(codigo, 0, texto)

    def test_un_numero_distinto_en_una_foto_se_marca_por_nombre_de_campo(self):
        self._guardar("antes", self.OPS, self.MES, self.FOTOS)
        self._guardar("despues", self.OPS, self.MES, [dict(self.FOTOS[0], total_value=101.0)])
        codigo, texto = self.correr("comparar")
        self.assertEqual(codigo, 1)
        self.assertIn("total_value", texto)
        self.assertNotIn("101", texto, "no se imprimen montos")

    def test_una_fila_que_falta_en_postgres_se_marca(self):
        self._guardar("antes", self.OPS, self.MES, self.FOTOS)
        self._guardar("despues", self.OPS[:1], self.MES, self.FOTOS)
        codigo, texto = self.correr("comparar")
        self.assertEqual(codigo, 1)
        self.assertIn("2 vs 1 filas", texto)

    def test_falta_el_despues_de_una_cuenta(self):
        self._guardar("antes", self.OPS, self.MES, self.FOTOS)
        codigo, texto = self.correr("comparar")
        self.assertEqual(codigo, 1)
        self.assertIn("falta el «despues»", texto)


class GuardarLaLlave(_ConAppCerrada):

    def test_guardar_la_que_esta_en_railway_queda_en_un_archivo_600_y_no_se_imprime(self):
        os.unlink(P.ruta_llave())
        codigo, texto = self.correr("llave", clave="  " + LLAVE + "  ")
        self.assertEqual(codigo, 0, texto)
        self.assertEqual(open(P.ruta_llave()).read(), LLAVE)
        self.assertEqual(os.stat(P.ruta_llave()).st_mode & 0o777, 0o600)

    def test_guardar_una_vacia_no_pisa_la_buena(self):
        codigo, texto = self.correr("llave", clave="   ")
        self.assertEqual(codigo, 1)
        self.assertEqual(open(P.ruta_llave()).read(), LLAVE)

    def test_nueva_inventa_una_la_copia_y_no_la_muestra(self):
        os.unlink(P.ruta_llave())
        copiado = {}

        def pbcopy(cmd, input=None, check=False):
            copiado["cmd"], copiado["texto"] = cmd, input.decode()

        with patch("pasaje_con_mantenimiento.subprocess.run", pbcopy):
            codigo, texto = self.correr("llave", "--nueva")
        self.assertEqual(codigo, 0, texto)
        guardada = open(P.ruta_llave()).read()
        self.assertGreaterEqual(len(guardada), 32)
        self.assertEqual(copiado["texto"], guardada)
        self.assertEqual(copiado["cmd"], ["pbcopy"])
        self.assertNotIn(guardada, texto)
        self.assertEqual(os.stat(P.ruta_llave()).st_mode & 0o777, 0o600)

    def test_la_llave_guardada_es_la_que_la_app_acepta(self):
        """El cierre del círculo: `llave` + el login real."""
        os.unlink(P.ruta_llave())
        self.assertEqual(self.correr("llave", clave=LLAVE)[0], 0)
        self.assertEqual(self.correr("pantallas", "antes")[0], 0)


if __name__ == "__main__":
    unittest.main()
