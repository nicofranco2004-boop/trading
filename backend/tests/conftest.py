"""Aislamiento de la DB para TODA la suite de tests.

Causa raíz que esto resuelve: main.py lee DB_PATH a import-time (main.py:95) y
default-ea a la DB de desarrollo real (backend/trading.db). Los tests que NO
seteaban os.environ['DB_PATH'] antes de importar main (24 de 41 archivos)
escribían sus usuarios/posiciones en la DB real → contaminación medida de
cuentas @rendi.test que inflaba métricas y casi manda un número falso a la
landing.

pytest importa este conftest ANTES de colectar/importar cualquier test module,
así que al setear DB_PATH acá garantizamos que ningún `import main` posterior
caiga en la DB real. init_db() corre solo al importar main (main.py:1477) sobre
este temp, creando el schema. El temp se borra al terminar la sesión.

Los archivos que ya seteaban su propio temp siguen funcionando (usan el suyo);
lo importante es que el DEFAULT dejó de ser la DB real.
"""
import os
import tempfile
import atexit

# Solo si nadie lo seteó ya (respetamos un DB_PATH explícito del entorno).
if not os.environ.get("DB_PATH"):
    _tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _tmp.close()
    os.environ["DB_PATH"] = _tmp.name

    @atexit.register
    def _cleanup_test_db(path=_tmp.name):
        for p in (path, path + "-wal", path + "-shm"):
            try:
                os.unlink(p)
            except OSError:
                pass
