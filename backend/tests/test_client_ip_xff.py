"""De qué entrada de X-Forwarded-For sale la IP del cliente.

El header se arma de izquierda a derecha y cada proxy agrega al FINAL. La primera
entrada es la que mandó el cliente: la elige quien llama. Leíamos ESA.

Consecuencia: mandando un X-Forwarded-For distinto en cada request, cada una
parecía venir de una IP nueva y los 27 rate limiters de la app dejaban de
existir — incluidos el de login y el de reseteo de contraseña (flooding de mails
a una casilla ajena). Y en el mail de "nuevo inicio de sesión", la IP que veía la
víctima la escribía el atacante.

Se lee por la DERECHA, que es lo que escribieron los proxies. Cuántos saltos mete
Railway no lo sabemos con certeza, así que el default no lo asume: la entrada más
a la derecha que sea PÚBLICA (los saltos internos son privados y se saltean
solos). Equivocarse para el otro lado también es caro: si se lee demasiado a la
derecha, todos los usuarios caen en el mismo balde y se rate-limitean entre
ellos. Por eso hay RENDI_TRUSTED_PROXY_HOPS para fijar la posición sin deployar,
y /api/admin/diag/client-ip para ver la cadena cruda en prod.

Corre con: cd backend && python3 -m pytest tests/test_client_ip_xff.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["DB_PATH"] = _TMP.name

import main   # noqa: E402


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    """Lo mínimo que miran _ip_del_cliente/_xff_parts: headers y client.host."""
    def __init__(self, xff=None, peer="10.0.0.9"):
        self.headers = {"x-forwarded-for": xff} if xff is not None else {}
        self.client = _FakeClient(peer)


class XffBase(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.get(k) for k in ("RENDI_ENV", "RENDI_TRUSTED_PROXY_HOPS")}
        os.environ["RENDI_ENV"] = "prod"
        os.environ.pop("RENDI_TRUSTED_PROXY_HOPS", None)
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class LecturaPorLaDerechaTest(XffBase):
    def test_el_cliente_no_puede_elegir_su_balde(self):
        """EL bug. El atacante manda una IP inventada; el borde agrega la real
        DETRÁS. Si leemos la primera, el atacante rota de balde a voluntad."""
        ip1 = main._ip_del_cliente(_FakeRequest("1.1.1.1, 200.5.5.5"))
        ip2 = main._ip_del_cliente(_FakeRequest("2.2.2.2, 200.5.5.5"))
        self.assertEqual(ip1, "200.5.5.5")
        self.assertEqual(ip1, ip2, "cambiando el header se consigue un balde nuevo")

    def test_tampoco_con_una_cadena_larga_inventada(self):
        """Inyectar varias entradas no ayuda: todo lo que manda el cliente queda
        a la IZQUIERDA de lo que agregó el borde."""
        self.assertEqual(
            main._ip_del_cliente(_FakeRequest("9.9.9.9, 8.8.8.8, 7.7.7.7, 200.5.5.5")),
            "200.5.5.5")

    def test_una_sola_entrada_es_la_del_borde(self):
        """Sin header inyectado, el proxy crea el header con la IP real sola."""
        self.assertEqual(main._ip_del_cliente(_FakeRequest("200.5.5.5")), "200.5.5.5")

    def test_los_saltos_internos_se_saltean(self):
        """Con dos saltos, el interno agrega una IP privada: la última pública
        sigue siendo el cliente. Esto es lo que hace que el default sirva sin
        saber cuántos saltos mete Railway."""
        self.assertEqual(
            main._ip_del_cliente(_FakeRequest("1.1.1.1, 200.5.5.5, 10.0.0.7")),
            "200.5.5.5")
        self.assertEqual(
            main._ip_del_cliente(_FakeRequest("200.5.5.5, 10.0.0.7, 172.16.3.4")),
            "200.5.5.5")

    def test_ipv6(self):
        self.assertEqual(
            main._ip_del_cliente(_FakeRequest("1.1.1.1, 2803:9800:a000::1, fd00::1")),
            "2803:9800:a000::1")

    def test_entradas_con_puerto(self):
        self.assertEqual(main._ip_del_cliente(_FakeRequest("1.1.1.1, 200.5.5.5:44321")),
                         "200.5.5.5")
        self.assertEqual(main._ip_del_cliente(_FakeRequest("[2803:9800:a000::1]:443")),
                         "2803:9800:a000::1")


class HopsFijosTest(XffBase):
    def test_hops_1_toma_la_ultima(self):
        os.environ["RENDI_TRUSTED_PROXY_HOPS"] = "1"
        self.assertEqual(main._ip_del_cliente(_FakeRequest("1.1.1.1, 200.5.5.5")),
                         "200.5.5.5")

    def test_hops_2_toma_la_anteultima(self):
        """La salida de emergencia si algún día un salto interno tuviera IP
        pública y el modo automático eligiera la del proxy."""
        os.environ["RENDI_TRUSTED_PROXY_HOPS"] = "2"
        self.assertEqual(main._ip_del_cliente(_FakeRequest("1.1.1.1, 200.5.5.5, 45.0.0.1")),
                         "200.5.5.5")

    def test_hops_basura_no_rompe(self):
        os.environ["RENDI_TRUSTED_PROXY_HOPS"] = "no-es-un-numero"
        self.assertEqual(main._ip_del_cliente(_FakeRequest("1.1.1.1, 200.5.5.5")),
                         "200.5.5.5")


class BordesTest(XffBase):
    def test_fuera_de_prod_el_header_se_ignora(self):
        """En local no hay proxy de confianza: el header lo escribe cualquiera y
        el socket no se falsea."""
        os.environ["RENDI_ENV"] = "dev"
        self.assertEqual(main._ip_del_cliente(_FakeRequest("1.1.1.1, 200.5.5.5")),
                         "10.0.0.9")

    def test_sin_header_cae_al_socket(self):
        self.assertEqual(main._ip_del_cliente(_FakeRequest(None, peer="200.5.5.5")),
                         "200.5.5.5")

    def test_header_vacio_o_basura(self):
        self.assertEqual(main._ip_del_cliente(_FakeRequest("", peer="200.5.5.5")),
                         "200.5.5.5")
        self.assertEqual(main._ip_del_cliente(_FakeRequest(" , , ", peer="200.5.5.5")),
                         "200.5.5.5")

    def test_cadena_toda_privada_toma_la_ultima(self):
        """Health checks / tráfico interno: no hay pública que elegir. La última
        es la que escribió el proxy más cercano — nunca la que mandó el cliente."""
        self.assertEqual(main._ip_del_cliente(_FakeRequest("10.0.0.3, 10.0.0.7")),
                         "10.0.0.7")

    def test_limite_conocido_cadena_interna_con_publica_inyectada(self):
        """LIMITACIÓN DOCUMENTADA, no un descuido.

        Si TODAS las entradas que escribieron los proxies fueran privadas —o
        sea, la request entró desde adentro de la red— la última pública de la
        cadena es la que inyectó el cliente, y el modo automático la elige.

        No se puede distinguir sin saber cuántos saltos hay: es exactamente el
        dato que falta. Para tráfico real de internet no pasa (el borde escribe
        la IP pública del cliente), y desde adentro de la red privada de Railway
        no hay atacante. Si algún día importara, RENDI_TRUSTED_PROXY_HOPS lo
        cierra sin deployar. Este test existe para que la limitación sea visible
        y falle ruidosamente si alguien cambia la regla creyendo otra cosa."""
        self.assertEqual(main._ip_del_cliente(_FakeRequest("1.1.1.1, 10.0.0.3, 10.0.0.7")),
                         "1.1.1.1")
        os.environ["RENDI_TRUSTED_PROXY_HOPS"] = "2"
        self.assertEqual(main._ip_del_cliente(_FakeRequest("1.1.1.1, 10.0.0.3, 10.0.0.7")),
                         "10.0.0.3")

    def test_nunca_devuelve_vacio(self):
        r = _FakeRequest(None)
        r.client = None
        self.assertEqual(main._ip_del_cliente(r), "unknown")
        self.assertEqual(main._rate_limit_ip(r), "unknown")


class MismaReglaEnLosDosLectoresTest(XffBase):
    def test_rate_limit_y_aviso_de_login_leen_igual(self):
        """Eran dos copias del mismo parseo. Si divergen, una de las dos vuelve
        a ser falseable."""
        req = _FakeRequest("1.1.1.1, 200.5.5.5, 10.0.0.7")
        self.assertEqual(main._rate_limit_ip(req), "200.5.5.5")
        self.assertEqual(main._client_ip(req), "200.5.5.5")

    def test_el_aviso_de_login_devuelve_vacio_si_no_hay_nada(self):
        """_client_ip alimenta un mail: 'unknown' se leería como una IP."""
        r = _FakeRequest(None)
        r.client = None
        self.assertEqual(main._client_ip(r), "")


if __name__ == "__main__":
    unittest.main()
