"""Una columna nueva en una tabla que YA EXISTE tiene que llegar a las bases viejas.

Qué pasó (auditoría C, re-test del 29/10): el arreglo B3 le agregó
`hasta_vela` al `CREATE TABLE IF NOT EXISTS tendencia_semanal` de `init_db` y a
`schema_pg.sql` (que sí tiene su `ALTER … IF NOT EXISTS`), pero no el `ALTER
TABLE … ADD COLUMN` del lado de SQLite. Una base donde la tabla ya existía
(creada con 31c00ff6) nunca recibía la columna, y el resumen del sábado fallaba
para CADA persona: «no such column: hasta_vela».

Por qué ninguna prueba lo vio: todas arrancan de una base NUEVA, donde el
CREATE trae la tabla completa. Es exactamente la trampa que ya documenta
`test_advisor_schema_migration.py` (el alta grupal del asesor fallaba siempre
en producción por lo mismo). Pasó dos veces: el arreglo de aquella vez fue para
SU tabla; esta prueba es para todas.

Dos candados:
  · ESTRUCTURAL (todas las tablas): se leen los `CREATE TABLE IF NOT EXISTS` y
    los `ALTER TABLE … ADD COLUMN` del código, y se comparan contra el censo
    `fixtures/columnas_de_las_tablas.json` (las columnas de cada tabla en
    31c00ff6). Una columna que no está en el censo tiene que tener su ALTER. Una
    tabla que no está en el censo es nueva: hay que sumarla (con sus columnas)
    — así, la próxima columna que se le agregue también va a pedir su ALTER.
  · DE COMPORTAMIENTO (la que importa): se FABRICA la tabla como la dejaba
    31c00ff6, se corre `init_db()` y el resumen del sábado escribe su fila.

Sólo SQLite: en Postgres no hay migraciones incrementales (ver
test_advisor_schema_migration.py); allá manda `schema_pg.sql`, que vigilan
test_schema_pg_al_dia y test_esquema_pg_reaplicable.
"""
import json
import os
import re
import sys
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main  # noqa: E402

# Los archivos que crean tablas en el arranque.
ARCHIVOS = ("main.py", "advisor_tandas.py", "dividendos.py", os.path.join("pricing", "fci.py"))
CENSO = os.path.join(HERE, "fixtures", "columnas_de_las_tablas.json")


def columnas_y_alters(fuentes: list) -> tuple:
    """({tabla: {columnas del CREATE}}, {(tabla, columna) con ALTER ADD COLUMN})."""
    tablas, alters = {}, set()
    for src in fuentes:
        for m in re.finditer(r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*?)\n\s*\);?", src, re.S):
            for ln in m.group(2).split("\n"):
                linea = ln.split("--")[0].strip()
                if not linea:
                    continue
                w = linea.split()[0].strip('"(,')
                if w.upper() in ("PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT") or not re.match(r"^\w+$", w):
                    continue
                tablas.setdefault(m.group(1), set()).add(w)
        alters |= set(re.findall(r"ALTER TABLE\s+(\w+)\s+ADD COLUMN\s+(\w+)", src))
    return tablas, alters


def faltantes(tablas: dict, alters: set, censo: dict) -> list:
    out = []
    for t, cols in sorted(tablas.items()):
        if t not in censo:
            out.append(f"tabla nueva {t}: sumala a {os.path.basename(CENSO)} con sus columnas")
            continue
        for c in sorted(cols - set(censo[t])):
            if (t, c) not in alters:
                out.append(f"{t}.{c}: está en el CREATE pero no tiene ALTER TABLE {t} ADD COLUMN {c}")
    return out


def _fuentes() -> list:
    out = []
    for a in ARCHIVOS:
        with open(os.path.join(BACKEND, a), encoding="utf-8") as f:
            out.append(f.read())
    return out


class ColumnaNuevaTest(unittest.TestCase):

    def test_toda_columna_nueva_de_una_tabla_vieja_tiene_su_alter(self):
        with open(CENSO, encoding="utf-8") as f:
            censo = json.load(f)
        tablas, alters = columnas_y_alters(_fuentes())
        self.assertEqual(faltantes(tablas, alters, censo), [],
                         "una base donde la tabla ya existía no recibe la columna (ver el docstring)")

    def test_el_guardian_ve_la_forma(self):
        """Que no esté ciego: el código de 873d2124 (sin el ALTER) lo marca."""
        censo = {"tendencia_semanal": ["user_id", "semana", "mail_ok"]}
        sin = ['''CREATE TABLE IF NOT EXISTS tendencia_semanal (
                user_id INTEGER NOT NULL,
                semana TEXT NOT NULL,
                mail_ok INTEGER,
                hasta_vela TEXT,                     -- la última vela
                PRIMARY KEY (user_id, semana)
            );''']
        self.assertEqual(faltantes(*columnas_y_alters(sin), censo),
                         ["tendencia_semanal.hasta_vela: está en el CREATE pero no tiene "
                          "ALTER TABLE tendencia_semanal ADD COLUMN hasta_vela"])
        con = sin + ["ALTER TABLE tendencia_semanal ADD COLUMN hasta_vela TEXT;"]
        self.assertEqual(faltantes(*columnas_y_alters(con), censo), [])


@unittest.skipIf(main.USANDO_PG, "Sólo SQLite: en Postgres manda schema_pg.sql (ver el docstring)")
class BaseVieja31c00ff6Test(unittest.TestCase):

    def setUp(self):
        conn = main.get_db()
        conn.execute("DROP TABLE IF EXISTS tendencia_semanal")
        # Tal cual la creaba 31c00ff6 (sin `hasta_vela`).
        conn.executescript("""
            CREATE TABLE tendencia_semanal (
                user_id INTEGER NOT NULL,
                semana TEXT NOT NULL,
                pct_alcista REAL,
                cambios INTEGER NOT NULL DEFAULT 0,
                canal TEXT,
                push_ok INTEGER,
                mail_ok INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, semana)
            );
        """)
        conn.commit()
        conn.close()

    def test_init_db_le_agrega_la_columna_y_el_resumen_escribe_su_fila(self):
        conn = main.get_db()
        try:
            antes = [r[1] for r in conn.execute("PRAGMA table_info(tendencia_semanal)")]
        finally:
            conn.close()
        self.assertNotIn("hasta_vela", antes, "el setUp tiene que reproducir la base vieja")
        main.init_db()
        import senales_semana
        with main.db_abierta() as conn:
            despues = [r[1] for r in conn.execute("PRAGMA table_info(tendencia_semanal)")]
            self.assertIn("hasta_vela", despues)
            # Lo que hace el resumen del sábado con cada persona.
            hoy = date(2026, 10, 31)
            senales_semana.desde_del_mail(conn, 1, hoy)
            conn.execute("INSERT INTO tendencia_semanal (user_id, semana, pct_alcista, cambios, canal, hasta_vela) "
                         "VALUES (1, ?, NULL, 0, NULL, ?)",
                         (hoy.isoformat(), senales_semana.marcas_json({"BTC|0": "2026-10-29"})))
            conn.commit()
            self.assertEqual(senales_semana.desde_del_mail(conn, 1, date(2026, 11, 7)),
                             ("2026-10-30", {("BTC", False): "2026-10-29"}))


if __name__ == "__main__":
    unittest.main()
