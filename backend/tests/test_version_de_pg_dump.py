"""Una sola lectura de la versión de `pg_dump`, para el backup y para el registro.

QUÉ PROTEGE. La versión de `pg_dump` se leía en dos lugares, cada uno a su manera:
`backup_db._version_mayor` (para negarse a volcar un servidor más nuevo) y
`main._imagen_del_proceso` (el renglón «imagen: Python … · pg_dump …» del arranque, con el
que se comprueba que la imagen de Railway salió bien). El segundo cortaba por el último
espacio y mostraba `17.11-1.pgdg12+2)` en vez de `17.11`: si Debian cambia el formato de la
salida, cada uno se habría roto distinto. Ahora el registro llama a la función del backup.

Sin base ni red: ejecutables de mentira que imprimen lo que imprime `pg_dump` de verdad.
Corre con: cd backend && python3 -m pytest tests/test_version_de_pg_dump.py
"""
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import main  # noqa: E402
from scripts import backup_db  # noqa: E402


def _falso(salida):
    d = tempfile.mkdtemp(prefix="pgdump-falso-")
    ruta = os.path.join(d, "pg_dump")
    with open(ruta, "w") as f:
        f.write(f"#!/bin/sh\necho '{salida}'\n")
    os.chmod(ruta, os.stat(ruta).st_mode | stat.S_IXUSR)
    return ruta


class UnaSolaLectura(unittest.TestCase):

    SALIDAS = [
        ("pg_dump (PostgreSQL) 17.11 (Debian 17.11-1.pgdg12+2)", "17.11", 17),
        ("pg_dump (PostgreSQL) 17.2", "17.2", 17),
        ("pg_dump (PostgreSQL) 16.4 (Ubuntu 16.4-1.pgdg22.04+1)", "16.4", 16),
        ("pg_dump (PostgreSQL) 18beta1", "18", 18),
    ]

    def test_el_backup_y_el_registro_leen_lo_mismo(self):
        for salida, completa, mayor in self.SALIDAS:
            with self.subTest(salida=salida):
                exe = _falso(salida)
                self.assertEqual(backup_db.version_de_pg_dump(exe), completa)
                self.assertEqual(backup_db._version_mayor(exe), mayor)
                with mock.patch("shutil.which", return_value=exe):
                    self.assertTrue(main._imagen_del_proceso().endswith(f"pg_dump {completa}"),
                                    main._imagen_del_proceso())

    def test_el_registro_no_muestra_restos_de_la_salida(self):
        """El defecto que había: `17.11-1.pgdg12+2)`."""
        exe = _falso("pg_dump (PostgreSQL) 17.11 (Debian 17.11-1.pgdg12+2)")
        with mock.patch("shutil.which", return_value=exe):
            linea = main._imagen_del_proceso()
        self.assertNotIn("pgdg", linea)
        self.assertNotIn(")", linea)

    def test_una_salida_que_no_entiende_falla_fuerte_en_el_backup_y_se_ve_en_el_registro(self):
        exe = _falso("algo que no es la versión")
        with self.assertRaises(backup_db.BackupFallido):
            backup_db._version_mayor(exe)
        with mock.patch("shutil.which", return_value=exe):
            self.assertTrue(main._imagen_del_proceso().endswith("pg_dump ? (BackupFallido)"))

    def test_sin_pg_dump_sigue_diciendo_FALTA(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertTrue(main._imagen_del_proceso().endswith("pg_dump FALTA"))

    def test_con_el_pg_dump_de_esta_maquina_si_hay(self):
        import shutil
        exe = shutil.which("pg_dump")
        if not exe:
            self.skipTest("esta máquina no tiene pg_dump")
        self.assertRegex(backup_db.version_de_pg_dump(exe), r"^\d+(\.\d+)*$")

    def test_la_otra_lectura_ya_no_existe(self):
        """Propagación: nadie más en `backend/` parsea `pg_dump --version` a su manera."""
        raiz = os.path.dirname(HERE)
        quedan = []
        for dirpath, dirs, files in os.walk(raiz):
            dirs[:] = [d for d in dirs if d not in ("tests", "node_modules", "__pycache__", ".venv", "venv")]
            for f in files:
                if f.endswith(".py"):
                    ruta = os.path.join(dirpath, f)
                    if "--version" in open(ruta, encoding="utf-8", errors="ignore").read() and \
                            os.path.basename(ruta) not in ("backup_db.py",):
                        quedan.append(os.path.relpath(ruta, raiz))
        # Los que lean `--version` de otra cosa se revisan a mano: hoy no hay ninguno.
        self.assertEqual(quedan, [], "otra lectura de `--version` fuera de backup_db")


if __name__ == "__main__":
    unittest.main()
