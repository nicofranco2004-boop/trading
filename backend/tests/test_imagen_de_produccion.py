"""La imagen de producción sale del `Dockerfile` y conserva lo que hacía Nixpacks.

Railway deja de leer `railway.toml` el 2026-12-01 y Nixpacks ya no figura entre
sus constructores; Railpack —el de por defecto— no lee `nixpacks.toml` y, en el
servicio de prueba, detectó `start.sh` (el arranque local) y lo corrió en bucle.
El reemplazo es un `Dockerfile` en la raíz (audit/RAILWAY_SIN_CONFIG_AS_CODE.md).

Lo que se fija acá, contra lo que configuraban `railway.toml` + `nixpacks.toml`
hasta `3a36eb52` (copiado abajo: la imagen no lleva la historia de git):
  · la misma imagen: Python 3.11, gcc, venv en /opt/venv, `pip<26`,
    `backend/requirements.txt`, y `pg_dump` 17 para el backup con Postgres;
  · el mismo arranque: uvicorn `main:app` desde `backend/`, en 0.0.0.0:$PORT;
  · cada ajuste de `[deploy]` tiene su lugar en el panel o en las variables, en
    la guía de la transición: el 1/12 este archivo deja de leerse y manda el panel;
  · el arranque dice con qué imagen corre (Python y pg_dump), para comprobarlo
    mirando el registro.

⚠️ Lo que NO prueba: que la imagen se arme. Eso lo dice el primer deploy.
"""
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAIZ = os.path.dirname(BACKEND)

# Lo que hacía Nixpacks (nixpacks.toml hasta 3a36eb52), para comparar.
NIXPACKS_ANTES = {
    "python": "python311",
    "paquetes": ["gcc"],
    "pg_dump": "postgresql_17",
    "install": ["python -m venv --copies /opt/venv",
                "pip install --upgrade 'pip<26'",
                "pip install -r backend/requirements.txt"],
    "start": ". /opt/venv/bin/activate && cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT",
}


def _leer(nombre):
    with open(os.path.join(RAIZ, nombre), encoding="utf-8") as f:
        return f.read()


def _instrucciones(dockerfile):
    """[(INSTRUCCIÓN, argumentos)] sin comentarios y con las líneas continuadas juntas."""
    sin_comentarios = "\n".join(l for l in dockerfile.splitlines() if not l.lstrip().startswith("#"))
    juntas = re.sub(r"\\\n", " ", sin_comentarios)
    return [(l.split(None, 1)[0].upper(), l.split(None, 1)[1] if " " in l.strip() else "")
            for l in juntas.splitlines() if l.strip()]


class LaImagenConservaLoDeNixpacks(unittest.TestCase):

    def setUp(self):
        self.df = _instrucciones(_leer("Dockerfile"))
        self.run = " ".join(a for i, a in self.df if i == "RUN")

    def test_python_311(self):
        desde = [a for i, a in self.df if i == "FROM"]
        self.assertEqual(len(desde), 1, desde)
        self.assertRegex(desde[0], r"^python:3\.11[-.]", NIXPACKS_ANTES["python"])

    def test_gcc_y_pg_dump_17(self):
        self.assertIn("gcc", self.run)
        m = re.search(r"postgresql-client-(\d+)", self.run)
        self.assertIsNotNone(m, "sin pg_dump el backup nocturno con Postgres falla")
        self.assertGreaterEqual(int(m.group(1)), int(NIXPACKS_ANTES["pg_dump"].rsplit("_", 1)[1]))

    def test_venv_pip_y_requirements_como_antes(self):
        self.assertIn("python -m venv --copies /opt/venv", self.run)
        env = " ".join(a for i, a in self.df if i == "ENV")
        self.assertIn("/opt/venv/bin", env, "sin el venv en el PATH, pip instala afuera")
        self.assertIn("pip install --upgrade 'pip<26'", self.run)
        self.assertIn("-r backend/requirements.txt", self.run)

    def test_el_mismo_arranque(self):
        cmd = [a for i, a in self.df if i == "CMD"]
        self.assertEqual(len(cmd), 1, cmd)
        workdir = [a for i, a in self.df if i == "WORKDIR"][-1]
        self.assertTrue(workdir.rstrip("/").endswith("/backend"), "uvicorn tiene que correr desde backend/")
        self.assertIn("uvicorn main:app --host 0.0.0.0 --port ${PORT", cmd[0])
        self.assertIn("exec uvicorn", cmd[0], "sin exec, la señal de apagado no le llega a uvicorn")

    def test_copia_el_backend_y_no_el_arranque_local(self):
        copias = [a for i, a in self.df if i == "COPY"]
        self.assertTrue(any(a.split()[0].rstrip("/") == "backend" for a in copias), copias)
        self.assertFalse(any("start.sh" in a for a in copias + [self.run]))


class RailwayTomlApuntaAlDockerfileYSusAjustesTienenReemplazo(unittest.TestCase):

    def setUp(self):
        self.toml = _leer("railway.toml")

    def _valor(self, clave):
        m = re.search(rf"^{clave}\s*=\s*(.+)$", self.toml, re.M)
        return m.group(1).strip().strip('"') if m else None

    def test_construye_con_el_dockerfile(self):
        self.assertEqual(self._valor("builder"), "DOCKERFILE")
        self.assertTrue(os.path.isfile(os.path.join(RAIZ, self._valor("dockerfilePath"))))
        self.assertFalse(os.path.exists(os.path.join(RAIZ, "nixpacks.toml")),
                         "nixpacks.toml ya no se usa: dejarlo hace creer que configura algo")

    def test_cada_ajuste_de_deploy_tiene_su_lugar_despues_del_corte(self):
        """El 1/12 este archivo deja de leerse: cada ajuste tiene que estar en la
        guía con su reemplazo (panel o variable), o se pierde ese día."""
        deploy = self.toml.split("[deploy]", 1)[1]
        claves = re.findall(r"^(\w+)\s*=", deploy, re.M)
        guia = _leer(os.path.join("audit", "RAILWAY_SIN_CONFIG_AS_CODE.md"))
        faltan = [c for c in claves if f"`{c}`" not in guia]
        self.assertEqual(faltan, [], "ajustes de railway.toml sin reemplazo en la guía")
        self.assertIn("RAILWAY_DEPLOYMENT_DRAINING_SECONDS", guia)
        self.assertIn("RAILWAY_HEALTHCHECK_TIMEOUT_SEC", guia)


class ElArranqueDiceConQueImagenCorre(unittest.TestCase):

    def test_python_y_pg_dump(self):
        linea = main._imagen_del_proceso()
        self.assertRegex(linea, r"^Python 3\.\d+\.\d+ · pg_dump ")

    def test_sin_pg_dump_lo_dice(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertTrue(main._imagen_del_proceso().endswith("pg_dump FALTA"))


if __name__ == "__main__":
    unittest.main()
