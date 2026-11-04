"""Levanta un Postgres de PRUEBA en la Mac y lo SOSTIENE vivo. Sin docker.

USO (desde la raíz del repo):

    python3 scripts/pg_de_prueba.py                 # datos en ~/.cache/rendi-pg-pruebas
    python3 scripts/pg_de_prueba.py /otra/carpeta   # o donde digas

Imprime una línea `DSN=...` y se queda dormido. **No termina a propósito**: el
servidor de `pgserver` muere con el proceso que lo creó, así que si este script
terminara, el Postgres se apagaría con él. Para apagarlo, matá ESTE proceso por
su pid (no con `pkill -f` y un patrón corto: ver la regla del repo).

Con ese DSN se corre la suite:

    cd backend
    DATABASE_URL='<el DSN>' python3 -m pytest tests -q -p no:randomly --timeout=90

🔴 POR QUÉ ESTE ARCHIVO ESTÁ EN EL REPO. Vivía en `/private/tmp` y el fin de
semana del 24-28/10/2026 macOS lo purgó, junto con los resultados de las suites
del viernes. La regla de este repo es que la prueba vive en el repo.

🔴 POR QUÉ LOS DATOS NO VAN A `/tmp`. Por lo mismo: una base de prueba en `/tmp`
desaparece entre sesiones sin aviso. `~/.cache/rendi-pg-pruebas` sobrevive. El
socket sí lo pone `pgserver` donde quiere (`~/Library/Caches/TemporaryItems/...`)
y eso está bien: se recrea cada vez.

🔴 POR QUÉ EL DSN SE ARMA ASÍ Y NO A MANO. `pgserver` da el host como PARÁMETRO
(`host=/ruta/al/socket`), no como hostname. Rearmar ese URI con cirugía de
strings pierde el host: pasó una vez en este proyecto y produjo **283 fallas
falsas** que parecían un desastre de la migración. Las 283 decían lo mismo, que
es la señal de que el roto era el instrumento. Por eso va
`conninfo_to_dict` + `make_conninfo`.

Vive en `scripts/` de la raíz y NO en `backend/` a propósito: abre conexiones con
`psycopg.connect` directo (para crear la base hace falta autocommit), y
`backend/tests/test_conexiones_pg_ajustadas.py` barre `backend/` exigiendo que
toda conexión pase por `pgsesion.conectar`.
"""
import os
import sys
import time

import pgserver
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

BASE = "rendi_pruebas"


def main():
    carpeta = (sys.argv[1] if len(sys.argv) > 1
               else os.path.expanduser("~/.cache/rendi-pg-pruebas"))
    pgdata = os.path.join(carpeta, "pgdata")
    os.makedirs(pgdata, exist_ok=True)

    srv = pgserver.get_server(pgdata)
    uri_crudo = srv.get_uri()
    partes = conninfo_to_dict(uri_crudo)

    with psycopg.connect(uri_crudo, autocommit=True) as c:
        existe = c.execute(
            "SELECT 1 FROM pg_database WHERE datname=%s", (BASE,)).fetchone()
        if not existe:
            c.execute(f'CREATE DATABASE "{BASE}"')
            print(f"CREADA={BASE}", flush=True)
        version = c.execute("SELECT version()").fetchone()[0]

    partes["dbname"] = BASE
    print("VERSION=" + version.split(",")[0], flush=True)
    print("PID=" + str(os.getpid()), flush=True)
    print("DSN=" + make_conninfo(**partes), flush=True)
    print("LISTO. Sosteniendo el servidor; matar este proceso lo apaga.", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
