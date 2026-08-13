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


def test_rowid_adentro_de_un_delete_pasa_a_ctid():
    """El borrado por tandas del reset: `DELETE … WHERE rowid IN (SELECT rowid …
    LIMIT n)`, que existe porque `DELETE … LIMIT` no está en todos los builds de
    SQLite.

    `ctid` es la posición FÍSICA de la fila en Postgres y CAMBIA cuando la fila se
    actualiza o pasa un VACUUM — por eso no es un reemplazo general del rowid.
    Pero adentro de UNA sentencia el valor no se escapa: se lee y se usa en el
    mismo statement, sin ventana para que la fila se mueva. Verificado contra
    Postgres: sobre 10 filas, dos tandas de LIMIT 4 borran 4 y 4.
    """
    out = traducir("DELETE FROM t WHERE rowid IN (SELECT rowid FROM t WHERE u=? LIMIT 5000)")
    assert "ctid" in out and "rowid" not in out
    assert "LIMIT 5000" in out


def test_rowid_fuera_de_un_delete_sigue_ruidoso():
    """LA GARANTÍA QUE NO SE NEGOCIA. Afuera del DELETE el valor SÍ sobrevive a la
    sentencia —alguien se lo guarda y lo usa después— y ahí el ctid ya puede
    apuntar a otra fila. Si eso pasara callado, un UPDATE o un DELETE posterior
    tocaría cualquier cosa. Se rechaza."""
    for sql in ("SELECT rowid FROM t WHERE u=?",
                "UPDATE t SET x=1 WHERE rowid=?",
                "INSERT INTO t (a) SELECT rowid FROM u"):
        with pytest.raises(NotImplementedError):
            traducir(sql)


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


# ── El catálogo: PRAGMA table_info y sqlite_master ───────────────────────────

def test_pragma_table_info_se_convierte_en_una_consulta_al_catalogo():
    """Los 9 sitios de main.py sólo leen el NOMBRE de la columna, así que la
    traducción tiene que devolver una columna llamada `name` — y en la misma
    posición que SQLite (la 1), porque el código lee de las dos formas."""
    q = traducir("PRAGMA table_info(positions)")
    assert "pg_attribute" in q, q
    assert "AS name" in q, q
    assert "'positions'" in q, q
    # el orden de las columnas es el de SQLite: cid, name, type, notnull, ...
    assert q.index("AS cid") < q.index("AS name") < q.index("AS type"), q


def test_pragma_table_info_acepta_el_nombre_entre_comillas():
    """scripts/pg_type_audit.py lo escribe así."""
    assert "'import_raw_rows'" in traducir('PRAGMA table_info("import_raw_rows")')


def test_los_otros_pragma_no_se_tocan():
    """Sólo `table_info` se traduce. Los demás PRAGMA son configuración de SQLite
    y tienen que seguir de largo: si el traductor se los comiera, `foreign_keys=ON`
    se apagaría en silencio y las cascadas de borrado dejarían de correr."""
    for p in ("PRAGMA journal_mode=WAL", "PRAGMA foreign_keys=ON",
              "PRAGMA busy_timeout=15000", "PRAGMA page_count"):
        assert traducir(p) == p, p


def test_sqlite_master_se_convierte_en_el_catalogo_de_postgres():
    """La query real de main.py:3467, que después BORRA de cada tabla que liste.
    Si devolviera un índice o una vista, el DELETE reventaría."""
    q = traducir(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    assert "pg_tables" in q, q
    assert "AS sqlite_master" in q, q
    # el % del LIKE sigue escapado después de la sustitución
    assert "'sqlite_%%'" in q, q


def test_sqlite_master_conserva_el_filtro_por_tipo():
    """`type` tiene que existir como columna: las 5 queries filtran por él."""
    q = traducir("SELECT name FROM sqlite_master WHERE type='table'")
    assert "AS type" in q, q
    assert "'index'" in q and "'view'" in q, "faltan los otros tipos que tiene SQLite"


# ── El caché de columnas ─────────────────────────────────────────────────────

def test_un_DDL_invalida_el_cache_de_columnas():
    """LO QUE MÁS IMPORTA del caché. init_db() mira las columnas, hace ALTER TABLE
    y vuelve a mirar. Si el caché no se entera del ALTER, la migración cree que la
    columna ya está y se la saltea — y la app arranca con una tabla incompleta."""
    from pgshim import _RE_DDL
    for ddl in ("ALTER TABLE advisor_clients ADD COLUMN phone TEXT",
                "CREATE TABLE IF NOT EXISTS fci_catalog (symbol TEXT PRIMARY KEY)",
                "DROP TABLE viejo",
                "alter table x add column y text"):
        assert _RE_DDL.search(ddl), ddl


def test_una_query_normal_no_invalida_el_cache():
    """Si un SELECT cualquiera limpiara el caché, el caché no serviría de nada."""
    from pgshim import _RE_DDL
    for q in ("SELECT * FROM positions WHERE user_id=?",
              "UPDATE users SET name=? WHERE id=?",
              "INSERT INTO operations (asset) VALUES (?)",
              "DELETE FROM snapshots WHERE date < ?"):
        assert not _RE_DDL.search(q), q


def test_el_cursor_cacheado_se_lee_igual_que_el_de_verdad():
    """El código lee el resultado por posición (`r[1]`) Y por nombre (`c["name"]`)."""
    from pgshim import CursorCacheado, Row
    filas = [Row(["cid", "name", "type"], (0, "id", "bigint")),
             Row(["cid", "name", "type"], (1, "broker", "text"))]
    cur = CursorCacheado(filas)
    assert [r[1] for r in cur.fetchall()] == ["id", "broker"]
    assert [c["name"] for c in CursorCacheado(filas).fetchall()] == ["id", "broker"]
    assert CursorCacheado(filas).fetchone()[1] == "id"
    assert CursorCacheado([]).fetchall() == []      # tabla que no existe


# ── Fechas con modificadores ─────────────────────────────────────────────────
# Los valores esperados NO están escritos a mano: se comparan contra lo que
# devuelve SQLite de verdad, que es la definición de "no cambió nada".

def _sqlite_dice(expr, params=()):
    import sqlite3
    return sqlite3.connect(":memory:").execute("SELECT " + expr, params).fetchone()[0]


@pytest.mark.parametrize("expr", [
    "datetime('now', '+2 days')",          # advisor_brief.py:269
    "datetime('now','-7 days')",           # main.py:16397 y 16400
    "date('now', '-30 days')",             # main.py:16473/16483/16497
    "datetime('now', '-30 days')",         # main.py:16564
    "datetime('now', '-1 day')",           # main.py:31056
    "datetime('now', '-6 hours')",         # importing/pipeline.py:195
])
def test_las_fechas_con_modificador_dan_LO_MISMO_que_sqlite(expr):
    """Cada expresión es una que está HOY en producción. La traducción tiene que
    devolver el mismo texto que devolvía SQLite, con el mismo formato: las
    columnas de fecha son `text` y el código las compara como strings."""
    import psycopg
    import os
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        pytest.skip("sin DATABASE_URL no hay Postgres contra qué comparar")
    with psycopg.connect(dsn, autocommit=True) as p:
        pg = p.execute(traducir("SELECT " + expr)).fetchone()[0]
    assert pg == _sqlite_dice(expr)


def test_el_ultimo_dia_del_mes_incluido_febrero_bisiesto():
    """main.py:11782 borra las fotos que caen el último día del mes. Si esto se
    tradujera mal, borraría las fotos equivocadas."""
    for fecha, esperado in [("2026-02-05", "2026-02-28"),   # febrero normal
                            ("2024-02-10", "2024-02-29"),   # bisiesto
                            ("2025-12-20", "2025-12-31"),   # fin de año
                            ("2025-07-03", "2025-07-31")]:  # mes de 31
        expr = f"date('{fecha}','start of month','+1 month','-1 day')"
        assert _sqlite_dice(expr) == esperado, "cambió lo que hace SQLite"
        assert "date_trunc('month'" in traducir("SELECT " + expr)


def test_el_modificador_que_llega_como_dato_sigue_siendo_un_parametro():
    """main.py:23160 y billing/subscriptions.py:334 pasan el modificador como
    dato ('-7 days', '+30 days'). No se puede resolver al traducir: tiene que
    seguir siendo un placeholder y que Postgres lo lea como intervalo."""
    q = traducir("SELECT date('now', ?)")
    assert "%s" in q, q
    assert "::interval" in q, q


@pytest.mark.parametrize("mod", [
    "weekday 0", "localtime", "unixepoch", "start of week", "+1 fortnight",
])
def test_un_modificador_desconocido_avisa_en_vez_de_adivinar(mod):
    """LA REGLA DE ORO de esta capa. SQLite acepta muchas más formas de las que
    traducimos. Adivinar mal una fecha no rompe nada visible: mueve un corte de
    período y cambia un número. Preferimos que explote."""
    with pytest.raises(NotImplementedError):
        traducir(f"SELECT date('now', '{mod}')")


def test_no_toca_lo_que_apenas_se_parece():
    for q in ("SELECT * FROM t WHERE update(x, 'y')",
              "SELECT to_char(fecha, 'YYYY')",
              "UPDATE t SET last_date = ? WHERE id = ?"):
        assert "to_char((" not in traducir(q), q


def test_la_base_puede_ser_un_agregado():
    """ai/quota.py:250 — `date(MIN(date), '+7 days')`, el "cuándo se te resetea la
    cuota de IA". El paréntesis del MIN cortaba el match y la expresión llegaba
    cruda a Postgres, que no tiene una función `date` de dos argumentos."""
    q = traducir("SELECT date(MIN(date), '+7 days') FROM ai_usage_daily")
    assert "to_char(" in q, q
    assert "MIN(date)" in q, "se perdió el agregado"
    assert "interval '+7 day'" in q, q


@pytest.mark.parametrize("expr", [
    "date('2026-08-13 17:30:00')",     # billing/subscriptions.py:333
    "date('2026-03-09 08:00:00')",     # billing/trial.py:584
])
def test_date_de_un_argumento_sobre_columna_devuelve_TEXTO(expr):
    """Postgres acepta `date(columna)` y NO rompe — por eso es peligroso: devuelve
    un objeto fecha en vez del texto 'YYYY-MM-DD' que devolvía SQLite. En
    ai/quota.py ese valor sale derecho al usuario."""
    q = traducir("SELECT " + expr)
    assert "to_char(" in q, q
    assert "'YYYY-MM-DD'" in q, q
    assert _sqlite_dice(expr) == "2026-08-13" or _sqlite_dice(expr) == "2026-03-09"


def test_date_now_sin_modificador_sigue_como_estaba():
    """No romper lo que ya andaba: `date('now')` y `datetime('now')` los traducen
    las reglas viejas, que ya tenían test."""
    assert traducir("SELECT date('now')") == "SELECT " + \
        "to_char(now() at time zone 'utc', 'YYYY-MM-DD')"


# ── MIN/MAX de dos argumentos ────────────────────────────────────────────────

def test_min_max_de_dos_argumentos_pasan_a_least_greatest():
    """En Postgres MIN/MAX son agregados de UN argumento: `MAX(0, x-1)` no existe.
    Son los 2 sitios que rompen de entrada: el "nunca bajo cero" del contador de
    chat (ai/quota.py:401) y el backfill de precios (price_history.py:143)."""
    assert "GREATEST(0, chat_count - 1)" in traducir(
        "UPDATE ai_usage_daily SET chat_count = MAX(0, chat_count - 1)")
    assert "LEAST(price_backfill_log.desde, excluded.desde)" in traducir(
        "INSERT INTO t VALUES (?) ON CONFLICT(symbol) DO UPDATE SET "
        "desde=MIN(price_backfill_log.desde, excluded.desde)")


@pytest.mark.parametrize("sql", [
    "SELECT MIN(date) FROM ai_usage_daily",              # agregado de verdad
    "SELECT MAX(date) FROM ai_usage_daily",
    "SELECT MIN(COALESCE(a,0)) FROM t",                  # 1 arg con coma anidada
    "SELECT MAX(CASE WHEN x THEN a ELSE b END) FROM t",
    "SELECT MIN(a), MAX(b) FROM t",                      # dos agregados
    "SELECT nombre FROM t WHERE x='MIN(a, b)'",          # adentro de un texto
])
def test_los_agregados_de_verdad_no_se_tocan(sql):
    """Confundir un agregado con un LEAST cambiaría el resultado de la consulta
    sin que nadie se entere. Por eso se cuentan paréntesis y no se usa un regex."""
    assert traducir(sql) == traducir(sql).replace("LEAST", "MIN").replace("GREATEST", "MAX")
    assert "LEAST" not in traducir(sql) and "GREATEST" not in traducir(sql), sql
