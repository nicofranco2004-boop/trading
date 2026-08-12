"""Todo 5xx tiene que dejar su CAUSA en los logs.

Por qué existe este archivo: el patrón que se repite 27 veces en main.py es

    except Exception as ex:
        raise HTTPException(500, f"Error al registrar flujo de caja: {ex}")

y 25 de esas 27 no loguean nada. Un usuario reportó "no puedo registrar un
depósito" y del lado del servidor no había NI UNA línea: ni el tipo de
excepción, ni la query, ni el archivo. El mensaje lindo se lo llevaba el
browser y el traceback se tiraba.

La información igual nunca se perdió — `raise X` adentro de un `except Y`
encadena el original en `X.__context__` con su traceback. Estos tests fijan que
el handler la lea, y que la respuesta que ve el cliente NO cambie por eso.

Corre con: cd backend && python3 -m pytest tests/test_500_logging.py
"""
import logging
import os
import sys
import tempfile

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main  # noqa: E402


# Rutas de juguete: montarlas acá evita atarse a un endpoint real (que puede
# cambiar de firma o pedir auth) para probar algo que es del handler, no suyo.
@main.app.get("/api/_test/wrapped-500")
def _wrapped_500():
    try:
        raise sqlite_full()
    except Exception as ex:
        raise HTTPException(500, f"Error al registrar flujo de caja: {ex}")


@main.app.get("/api/_test/bare-503")
def _bare_503():
    # 5xx DELIBERADO, sin excepción original detrás (ej.: cron sin token).
    raise HTTPException(503, "Snapshot cron no configurado.")


@main.app.get("/api/_test/not-found")
def _not_found():
    raise HTTPException(404, "Not found")


def sqlite_full():
    import sqlite3
    return sqlite3.OperationalError("database or disk is full")


@pytest.fixture()
def client():
    return TestClient(main.app, raise_server_exceptions=False)


def test_el_500_deja_la_causa_real_y_el_traceback_en_los_logs(client, caplog):
    with caplog.at_level(logging.ERROR, logger="main"):
        r = client.get("/api/_test/wrapped-500")

    assert r.status_code == 500
    rec = [x for x in caplog.records if x.levelno >= logging.ERROR]
    assert rec, "el 500 no logueó nada — es exactamente el bug que esto previene"

    linea = rec[0].getMessage()
    assert "500" in linea and "/api/_test/wrapped-500" in linea, linea

    # Lo que importa: el TIPO de excepción y su traceback, no solo el texto que
    # alguien decidió meter en el mensaje del HTTPException.
    assert rec[0].exc_info is not None, "sin exc_info no hay traceback que mirar"
    assert rec[0].exc_info[0] is __import__("sqlite3").OperationalError
    assert "database or disk is full" in str(rec[0].exc_info[1])


def test_la_respuesta_que_ve_el_cliente_no_cambia(client):
    # El handler es SOLO observabilidad. Si además moviera el body, cualquier
    # pantalla que hoy parsea `detail` se rompería en silencio.
    r = client.get("/api/_test/wrapped-500")
    assert r.status_code == 500
    assert r.json() == {
        "detail": "Error al registrar flujo de caja: database or disk is full"
    }


def test_un_5xx_deliberado_loguea_una_linea_pero_sin_stack(client, caplog):
    # Un 503 de "esto no está configurado" es una decisión del código, no un
    # accidente: queremos la línea, no un traceback en cada ping del cron.
    with caplog.at_level(logging.ERROR, logger="main"):
        r = client.get("/api/_test/bare-503")

    assert r.status_code == 503
    rec = [x for x in caplog.records if x.levelno >= logging.ERROR]
    assert len(rec) == 1
    assert "Snapshot cron no configurado." in rec[0].getMessage()
    assert rec[0].exc_info is None


def test_los_4xx_no_ensucian_los_logs(client, caplog):
    # Un 404 es tráfico normal. Si loguearan como error, el ruido tapa justo lo
    # que este handler existe para hacer visible.
    with caplog.at_level(logging.ERROR, logger="main"):
        r = client.get("/api/_test/not-found")

    assert r.status_code == 404
    assert [x for x in caplog.records if x.levelno >= logging.ERROR] == []
