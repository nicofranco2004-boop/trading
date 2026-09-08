"""CREDENTIALS_KEY — la clave que cifra las credenciales de broker deja de ser
la que firma los JWT.

Contexto: hasta 2026-09, `user_broker_credentials.api_key_enc` (API key de
Wallbit, refresh token de IOL) se cifraba con Fernet(sha256(SECRET_KEY)). O sea
que rotar la firma de sesiones dejaba todas las credenciales indescifrables, y
por eso no se rotaba nunca — con el agravante de que en producción SECRET_KEY
era una API key de Anthropic.

Lo que estos tests fijan, y es el punto entero:
  • con CREDENTIALS_KEY seteada, lo cifrado ANTES se sigue leyendo (MultiFernet);
  • después de correr la migración, **rotar SECRET_KEY no rompe nada**;
  • SIN migrar, rotar SECRET_KEY sí las pierde → por eso el orden es obligatorio
    y está escrito en el comentario de _wallbit_cipher (test de control negativo);
  • sin CREDENTIALS_KEY, el comportamiento es idéntico al de antes (sin regresión).

Los tests pasan por las MISMAS funciones que producción (`main._wallbit_encrypt`,
`main._wallbit_decrypt`, `main._migrar_credenciales_a_credentials_key`), no por
una reimplementación del cifrado: un test que cifre por su cuenta certificaría
en verde algo que la app no hace.

Corre con: cd backend && python3 -m pytest tests/test_credentials_key.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
os.environ.setdefault("SECRET_KEY", "test-secret-key-para-credentials-" + "x" * 20)
os.environ.pop("CREDENTIALS_KEY", None)   # el import no debe migrar nada

import main

from cryptography.fernet import InvalidToken

CLAVE_PROPIA = "credentials-key-de-test-" + "k" * 40
SECRET_ROTADA = "secret-key-despues-de-rotar-" + "z" * 40


class CredentialsKeyTest(unittest.TestCase):
    _seq = 9100

    def setUp(self):
        CredentialsKeyTest._seq += 1
        self.UID = CredentialsKeyTest._seq
        self.conn = main.get_db()
        self.conn.execute(
            "INSERT INTO users (id,email,password_hash,approved) VALUES (?,?,?,1)",
            (self.UID, f"creds{self.UID}@t.com", "HASH"))
        self.conn.commit()
        self._secret_original = main.SECRET_KEY
        os.environ.pop("CREDENTIALS_KEY", None)

    def tearDown(self):
        main.SECRET_KEY = self._secret_original
        os.environ.pop("CREDENTIALS_KEY", None)
        self.conn.close()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _guardar_cifrada_a_la_vieja(self, plano: str, broker: str = "wallbit") -> None:
        """Deja una fila en el estado PRE-migración: cifrada con la clave derivada
        de SECRET_KEY, que es como estaban todas hasta 2026-09."""
        enc = main._fernet_de(main.SECRET_KEY).encrypt(plano.encode()).decode()
        self.conn.execute(
            "INSERT INTO user_broker_credentials (user_id,broker,api_key_enc) VALUES (?,?,?)",
            (self.UID, broker, enc))
        self.conn.commit()

    def _enc_guardado(self, broker: str = "wallbit") -> str:
        return self.conn.execute(
            "SELECT api_key_enc FROM user_broker_credentials WHERE user_id=? AND broker=?",
            (self.UID, broker)).fetchone()["api_key_enc"]

    # ── tests ────────────────────────────────────────────────────────────────

    def test_sin_credentials_key_no_hay_regresion(self):
        """Sin la env var, todo se comporta como antes: una sola clave, la de
        SECRET_KEY, y la migración no toca nada."""
        enc = main._wallbit_encrypt("api-key-wallbit")
        self.assertEqual(main._wallbit_decrypt(enc), "api-key-wallbit")
        # lo cifrado se abre con la clave derivada de SECRET_KEY, como siempre
        self.assertEqual(
            main._fernet_de(main.SECRET_KEY).decrypt(enc.encode()).decode(),
            "api-key-wallbit")
        self._guardar_cifrada_a_la_vieja("no-me-toques")
        antes = self._enc_guardado()
        main._migrar_credenciales_a_credentials_key()          # no-op
        self.assertEqual(self._enc_guardado(), antes)

    def test_lo_cifrado_antes_se_sigue_leyendo(self):
        """Al setear CREDENTIALS_KEY, las credenciales viejas NO se rompen:
        MultiFernet las descifra con la clave legacy."""
        enc_viejo = main._fernet_de(main.SECRET_KEY).encrypt(b"refresh-token-iol").decode()
        os.environ["CREDENTIALS_KEY"] = CLAVE_PROPIA
        self.assertEqual(main._wallbit_decrypt(enc_viejo), "refresh-token-iol")

    def test_lo_nuevo_se_cifra_con_la_clave_propia(self):
        """Con CREDENTIALS_KEY, lo que se guarda YA NO depende de SECRET_KEY."""
        os.environ["CREDENTIALS_KEY"] = CLAVE_PROPIA
        enc = main._wallbit_encrypt("api-key-nueva")
        # la clave propia la abre...
        self.assertEqual(
            main._fernet_de(CLAVE_PROPIA).decrypt(enc.encode()).decode(), "api-key-nueva")
        # ...y la de SECRET_KEY ya no
        with self.assertRaises(InvalidToken):
            main._fernet_de(main.SECRET_KEY).decrypt(enc.encode())

    def test_migrada_la_fila_rotar_secret_key_no_la_rompe(self):
        """EL TEST QUE IMPORTA. Fila vieja → migración → rotación de SECRET_KEY →
        la credencial se sigue leyendo. Es la garantía que hace que rotar la
        clave de firma deje de costar las conexiones de los usuarios."""
        self._guardar_cifrada_a_la_vieja("api-key-que-debe-sobrevivir")
        enc_pre = self._enc_guardado()

        os.environ["CREDENTIALS_KEY"] = CLAVE_PROPIA
        main._migrar_credenciales_a_credentials_key()

        enc_post = self._enc_guardado()
        self.assertNotEqual(enc_post, enc_pre, "la migración tenía que re-cifrar la fila")
        self.assertEqual(
            main._fernet_de(CLAVE_PROPIA).decrypt(enc_post.encode()).decode(),
            "api-key-que-debe-sobrevivir")

        # rotación: nuevo proceso con otra SECRET_KEY
        main.SECRET_KEY = SECRET_ROTADA
        self.assertEqual(main._wallbit_decrypt(enc_post), "api-key-que-debe-sobrevivir")

    def test_control_negativo_sin_migrar_rotar_la_pierde(self):
        """Por qué el orden es obligatorio: si se rota SECRET_KEY antes de que la
        migración corra, la fila no la abre nadie. Sin DB a propósito, para no
        depender del orden en que corran los tests."""
        os.environ["CREDENTIALS_KEY"] = CLAVE_PROPIA
        enc_sin_migrar = main._fernet_de(main.SECRET_KEY).encrypt(b"se-va-a-perder").decode()
        self.assertEqual(main._wallbit_decrypt(enc_sin_migrar), "se-va-a-perder")

        main.SECRET_KEY = SECRET_ROTADA
        with self.assertRaises(InvalidToken):
            main._wallbit_decrypt(enc_sin_migrar)

    def test_la_migracion_es_idempotente(self):
        """Corre en cada arranque: la segunda pasada no debe re-cifrar nada."""
        self._guardar_cifrada_a_la_vieja("idempotente")
        os.environ["CREDENTIALS_KEY"] = CLAVE_PROPIA
        main._migrar_credenciales_a_credentials_key()
        primera = self._enc_guardado()
        main._migrar_credenciales_a_credentials_key()
        self.assertEqual(self._enc_guardado(), primera)
        self.assertEqual(main._wallbit_decrypt(primera), "idempotente")

    def test_una_fila_ilegible_no_frena_a_las_demas(self):
        """Una credencial cifrada con una clave efímera de dev (no la abre nadie)
        no puede impedir que se migren las otras."""
        self.conn.execute(
            "INSERT INTO user_broker_credentials (user_id,broker,api_key_enc) VALUES (?,?,?)",
            (self.UID, "iol_lab", main._fernet_de("clave-efimera-perdida").encrypt(b"x").decode()))
        self.conn.commit()
        self._guardar_cifrada_a_la_vieja("esta-si-migra", broker="wallbit")

        os.environ["CREDENTIALS_KEY"] = CLAVE_PROPIA
        main._migrar_credenciales_a_credentials_key()

        self.assertEqual(
            main._fernet_de(CLAVE_PROPIA).decrypt(self._enc_guardado("wallbit").encode()).decode(),
            "esta-si-migra")


    # ── el gate de la rotación tiene que VERSE ────────────────────────────────
    # Estos dos existen porque la primera versión usaba print(): el start de
    # nixpacks no fuerza salida sin buffer, así que la línea nunca apareció en
    # los logs de Railway y el procedimiento de rotación quedó sin su semáforo.
    # Un gate que no se ve no es un gate.

    def test_el_gate_sale_por_el_logger_de_la_app(self):
        self._guardar_cifrada_a_la_vieja("visible")
        os.environ["CREDENTIALS_KEY"] = CLAVE_PROPIA
        with self.assertLogs("main", level="INFO") as cap:
            main._migrar_credenciales_a_credentials_key()
        self.assertTrue(any("credenciales:" in m for m in cap.output),
                        f"el gate no salió por logging: {cap.output}")

    def test_sin_credentials_key_tambien_avisa(self):
        """El silencio no puede ser ambiguo: sin este aviso, 'falta la variable' y
        'la migración no hizo nada' se ven igual desde los logs."""
        os.environ.pop("CREDENTIALS_KEY", None)
        with self.assertLogs("main", level="INFO") as cap:
            main._migrar_credenciales_a_credentials_key()
        self.assertTrue(any("CREDENTIALS_KEY no está seteada" in m for m in cap.output),
                        f"no avisó que falta la variable: {cap.output}")

    def test_el_veredicto_cambia_cuando_ya_esta_todo_migrado(self):
        """Primera pasada dice que NO rotes; la segunda, que es SEGURO."""
        self._guardar_cifrada_a_la_vieja("dos-pasadas")
        os.environ["CREDENTIALS_KEY"] = CLAVE_PROPIA
        with self.assertLogs("main", level="INFO") as primera:
            main._migrar_credenciales_a_credentials_key()
        self.assertTrue(any("NO rotes SECRET_KEY todavía" in m for m in primera.output),
                        primera.output)
        with self.assertLogs("main", level="INFO") as segunda:
            main._migrar_credenciales_a_credentials_key()
        self.assertTrue(any("SEGURO rotar SECRET_KEY" in m for m in segunda.output),
                        segunda.output)


if __name__ == "__main__":
    unittest.main()
