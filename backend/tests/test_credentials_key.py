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
import logging
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
CLAVE_NUEVA = "credentials-key-rotada-tras-railway-" + "n" * 30


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
        os.environ.pop("CREDENTIALS_KEY_ANTERIOR", None)

    def tearDown(self):
        main.SECRET_KEY = self._secret_original
        os.environ.pop("CREDENTIALS_KEY", None)
        os.environ.pop("CREDENTIALS_KEY_ANTERIOR", None)
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

    def _gate(self):
        """Corre la migración y devuelve el LogRecord del gate.

        `assertLogs` fuerza el nivel del logger, así que por sí solo NO prueba que
        el mensaje se vea en producción: hay que mirar el levelno del record."""
        with self.assertLogs("main", level="DEBUG") as cap:
            main._migrar_credenciales_a_credentials_key()
        gate = [r for r in cap.records if "credenciales:" in r.getMessage()]
        self.assertTrue(gate, f"el gate no salió por logging: {cap.output}")
        return gate[0]

    def test_el_gate_sale_por_el_logger_de_la_app(self):
        self._guardar_cifrada_a_la_vieja("visible")
        os.environ["CREDENTIALS_KEY"] = CLAVE_PROPIA
        self.assertIn("credenciales:", self._gate().getMessage())

    def test_el_gate_va_en_warning_en_las_tres_ramas(self):
        """EL TEST QUE FALTABA. Esta función corre a nivel de módulo, ANTES del
        `logging.basicConfig(level=INFO)` que está ~1000 líneas más abajo en
        main.py. Con el root logger todavía en WARNING, un INFO se descarta en
        silencio. Pasó en producción: la rama 'SEGURO rotar' era la única en INFO
        y era justo la que había que leer para poder avanzar."""
        # rama 1: sin la variable
        os.environ.pop("CREDENTIALS_KEY", None)
        self.assertGreaterEqual(self._gate().levelno, logging.WARNING,
                                "la rama 'no está seteada' quedó por debajo de WARNING")
        # rama 2: hay algo para migrar
        self._guardar_cifrada_a_la_vieja("tres-ramas")
        os.environ["CREDENTIALS_KEY"] = CLAVE_PROPIA
        self.assertGreaterEqual(self._gate().levelno, logging.WARNING,
                                "la rama 'NO rotes todavía' quedó por debajo de WARNING")
        # rama 3: ya está todo migrado — la que se perdió
        r = self._gate()
        self.assertIn("SEGURO rotar SECRET_KEY", r.getMessage())
        self.assertGreaterEqual(r.levelno, logging.WARNING,
                                "la rama 'SEGURO rotar' quedó por debajo de WARNING: "
                                "no se va a ver en los logs y el gate no sirve")

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


    # ── rotar CREDENTIALS_KEY (incidente de Railway, 2026-10-21) ─────────────
    # La clave propia también puede filtrarse. Rotarla a secas pierde todo: la
    # nueva no abre lo de la vieja y SECRET_KEY tampoco. CREDENTIALS_KEY_ANTERIOR
    # es la vieja en modo sólo-lectura mientras la migración re-cifra.

    def _guardar_bajo_credentials_key(self, plano: str, broker: str = "wallbit") -> None:
        """Estado de producción desde 2026-09-08: todo cifrado bajo la clave propia."""
        os.environ["CREDENTIALS_KEY"] = CLAVE_PROPIA
        self.conn.execute(
            "INSERT INTO user_broker_credentials (user_id,broker,api_key_enc) VALUES (?,?,?)",
            (self.UID, broker, main._wallbit_encrypt(plano)))
        self.conn.commit()

    def test_control_negativo_rotar_credentials_key_a_secas_la_pierde(self):
        """Por qué hace falta CREDENTIALS_KEY_ANTERIOR."""
        self._guardar_bajo_credentials_key("se-pierde-sin-anterior")
        os.environ["CREDENTIALS_KEY"] = CLAVE_NUEVA
        with self.assertRaises(InvalidToken):
            main._wallbit_decrypt(self._enc_guardado())

    def test_rotar_credentials_key_con_anterior_no_pierde_nada(self):
        """EL TEST QUE IMPORTA de la rotación: vieja → (anterior + nueva) →
        migración → se borra la anterior → la credencial se sigue leyendo, y
        quedó cifrada con la nueva y SÓLO con la nueva."""
        self._guardar_bajo_credentials_key("api-key-que-sobrevive")
        os.environ["CREDENTIALS_KEY_ANTERIOR"] = CLAVE_PROPIA
        os.environ["CREDENTIALS_KEY"] = CLAVE_NUEVA
        self.assertEqual(main._wallbit_decrypt(self._enc_guardado()), "api-key-que-sobrevive")

        main._migrar_credenciales_a_credentials_key()
        enc = self._enc_guardado()
        self.assertEqual(main._fernet_de(CLAVE_NUEVA).decrypt(enc.encode()).decode(),
                         "api-key-que-sobrevive")
        with self.assertRaises(InvalidToken):
            main._fernet_de(CLAVE_PROPIA).decrypt(enc.encode())

        os.environ.pop("CREDENTIALS_KEY_ANTERIOR")
        self.assertEqual(main._wallbit_decrypt(enc), "api-key-que-sobrevive")

    def test_rotar_las_dos_a_la_vez_tambien_sobrevive(self):
        """Tras el incidente se rotan SECRET_KEY y CREDENTIALS_KEY. Como desde el
        08/09 nada depende de SECRET_KEY, cambiarla en el mismo deploy no afecta."""
        self._guardar_bajo_credentials_key("dos-rotaciones")
        main.SECRET_KEY = SECRET_ROTADA
        os.environ["CREDENTIALS_KEY_ANTERIOR"] = CLAVE_PROPIA
        os.environ["CREDENTIALS_KEY"] = CLAVE_NUEVA
        main._migrar_credenciales_a_credentials_key()
        os.environ.pop("CREDENTIALS_KEY_ANTERIOR")
        self.assertEqual(main._wallbit_decrypt(self._enc_guardado()), "dos-rotaciones")

    def test_anterior_sin_clave_propia_se_ignora(self):
        """Sin CREDENTIALS_KEY el sistema es el de antes: la anterior no puede
        pasar a ser la que cifra por quedar primera en la lista."""
        os.environ["CREDENTIALS_KEY_ANTERIOR"] = CLAVE_PROPIA
        enc = main._wallbit_encrypt("sin-propia")
        self.assertEqual(main._fernet_de(main.SECRET_KEY).decrypt(enc.encode()).decode(),
                         "sin-propia")

    def test_gate_confirma_que_la_copia_de_la_anterior_esta_bien(self):
        """Paso 2 del runbook: antes de cambiar CREDENTIALS_KEY, la anterior es
        una copia. El log tiene que decir que coinciden SIN mostrar ninguna."""
        self._guardar_bajo_credentials_key("copia")
        os.environ["CREDENTIALS_KEY_ANTERIOR"] = CLAVE_PROPIA
        r = self._gate()
        self.assertIn("CREDENTIALS_KEY_ANTERIOR es IGUAL", r.getMessage())
        self.assertNotIn(CLAVE_PROPIA, r.getMessage())
        self.assertGreaterEqual(r.levelno, logging.WARNING)

    def test_gate_de_la_anterior_en_las_dos_pasadas(self):
        """Primera pasada tras rotar: re-cifra y dice que NO se borre la anterior.
        Segunda: 0 migradas y SEGURO borrarla. Las dos en WARNING."""
        self._guardar_bajo_credentials_key("dos-pasadas-anterior")
        os.environ["CREDENTIALS_KEY_ANTERIOR"] = CLAVE_PROPIA
        os.environ["CREDENTIALS_KEY"] = CLAVE_NUEVA
        primera = self._gate()
        self.assertIn("NO borres CREDENTIALS_KEY_ANTERIOR todavía", primera.getMessage())
        self.assertGreaterEqual(primera.levelno, logging.WARNING)
        segunda = self._gate()
        self.assertIn("0 migradas ahora", segunda.getMessage())
        self.assertIn("SEGURO borrar CREDENTIALS_KEY_ANTERIOR", segunda.getMessage())
        self.assertGreaterEqual(segunda.levelno, logging.WARNING)

    def test_gate_no_autoriza_borrar_la_anterior_con_ilegibles(self):
        """Si la anterior estaba mal copiada, la fila no abre con ninguna: no se
        toca (sigue recuperable) y el log NO dice que se pueda borrar."""
        self._guardar_bajo_credentials_key("mal-copiada")
        antes = self._enc_guardado()
        os.environ["CREDENTIALS_KEY_ANTERIOR"] = "una-copia-equivocada-" + "q" * 30
        os.environ["CREDENTIALS_KEY"] = CLAVE_NUEVA
        r = self._gate()
        self.assertNotIn("SEGURO borrar", r.getMessage())
        self.assertIn("NO borres CREDENTIALS_KEY_ANTERIOR", r.getMessage())
        self.assertEqual(self._enc_guardado(), antes, "una fila ilegible no se reescribe")


if __name__ == "__main__":
    unittest.main()
