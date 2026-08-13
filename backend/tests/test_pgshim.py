"""El traductor de SQLite→Postgres del shim.

Es la pieza de más riesgo de la migración: por acá pasan las ~1.400 consultas del
backend sin que nadie las revise una por una. Un error acá no tira la app — te
devuelve el número equivocado, que es peor.

Los casos no son inventados: casi todos salen de queries que están en main.py.

Corre con: cd backend && python3 -m pytest tests/test_pgshim.py
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from pgshim import traducir, _normalizar_params, Row  # noqa: E402


# ── Placeholders y el `%` ────────────────────────────────────────────────────

def test_los_placeholders_pasan_a_la_sintaxis_de_postgres():
    assert traducir("SELECT * FROM users WHERE id=? AND email=?") == \
        "SELECT * FROM users WHERE id=%s AND email=%s"


def test_el_porcentaje_de_un_LIKE_se_escapa():
    """EL caso que rompe en silencio. psycopg usa `%` para bindear parámetros, así
    que un `%` literal del patrón hay que duplicarlo. Sin esto, la query de stats
    públicas —que excluye las cuentas de test— o revienta o deja de excluirlas y
    el número de la landing se infla."""
    q = traducir("SELECT COUNT(*) FROM users WHERE email NOT LIKE '%@rendi.test'")
    assert "'%%@rendi.test'" in q, q


def test_un_signo_de_pregunta_adentro_de_un_texto_no_es_un_placeholder():
    q = traducir("SELECT * FROM t WHERE nota = '¿seguro?' AND id = ?")
    assert q.count("%s") == 1, q
    assert "'¿seguro?'" in q, q


def test_las_comillas_escapadas_no_confunden_al_parser():
    q = traducir("SELECT * FROM t WHERE nombre = 'O''Brien' AND id = ?")
    assert q.count("%s") == 1, q
    assert "'O''Brien'" in q, q


# ── Fechas ───────────────────────────────────────────────────────────────────

def test_strftime_se_convierte_en_cortar_el_texto():
    """Las fechas están guardadas como TEXTO 'YYYY-MM-DD'. Cortar el string es
    exactamente lo que hacía strftime sobre ese formato — y no depende de que
    Postgres pueda parsear una columna que es `text`, no `date`."""
    q = traducir("SELECT * FROM n WHERE strftime('%Y', n.date)=? AND strftime('%m', n.date)=?")
    assert "substr(n.date, 1, 4)" in q, q
    assert "substr(n.date, 6, 2)" in q, q
    assert "strftime" not in q


def test_datetime_now_devuelve_TEXTO_con_el_mismo_formato():
    """Si devolviera un timestamptz, las comparaciones de string del código
    dejarían de funcionar sin avisar."""
    q = traducir("UPDATE users SET password_changed_at=datetime('now') WHERE id=?")
    assert "to_char(" in q and "YYYY-MM-DD HH24:MI:SS" in q, q
    assert "datetime(" not in q


def test_ifnull_es_coalesce():
    assert "COALESCE(" in traducir("SELECT IFNULL(x, 0) FROM t")


# ── INSERT ───────────────────────────────────────────────────────────────────

def test_insert_or_ignore_no_pisa_lo_que_ya_esta():
    q = traducir("INSERT OR IGNORE INTO watchlist (user_id, symbol) VALUES (?,?)")
    assert q.upper().startswith("INSERT INTO")
    assert q.rstrip().upper().endswith("ON CONFLICT DO NOTHING"), q


def test_insert_or_replace_NO_se_adivina():
    """Traducirlo solo exigiría saber por qué columna hay conflicto, y adivinarlo
    puede pisar la fila equivocada. Mejor parar ruidoso que convertir mal."""
    with pytest.raises(NotImplementedError) as e:
        traducir("INSERT OR REPLACE INTO config VALUES ('tc_mep', ?, ?)")
    assert "ON CONFLICT" in str(e.value)


def test_rowid_para_ruidoso():
    """No existe en Postgres. Si pasara callado, el DELETE por tandas del reset
    borraría cualquier cosa."""
    with pytest.raises(NotImplementedError):
        traducir("DELETE FROM t WHERE rowid IN (SELECT rowid FROM t LIMIT 5000)")


# ── Parámetros ───────────────────────────────────────────────────────────────

def test_los_booleanos_de_python_viajan_como_0_y_1():
    """Las columnas 0/1 quedaron smallint a propósito (el código compara `=1`).
    psycopg mandaría un boolean y Postgres lo rechaza."""
    assert _normalizar_params((True, False, 5, "x", None)) == (1, 0, 5, "x", None)


# ── Row ──────────────────────────────────────────────────────────────────────

def test_la_fila_se_lee_por_nombre_y_por_posicion():
    """`sqlite3.Row` permite las dos, y el código usa ambas —a veces en el mismo
    archivo—. Devolver sólo un dict rompería la mitad de las lecturas."""
    r = Row(["id", "email"], (7, "a@b.c"))
    assert r["id"] == 7 and r[0] == 7
    assert r["email"] == "a@b.c" and r[1] == "a@b.c"
    assert dict(zip(r.keys(), list(r))) == {"id": 7, "email": "a@b.c"}
    assert "email" in r and len(r) == 2


def test_una_columna_que_no_existe_avisa():
    r = Row(["id"], (1,))
    with pytest.raises(IndexError):
        r["no_existe"]
