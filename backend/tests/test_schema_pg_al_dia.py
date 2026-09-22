"""Toda columna que SQLite agrega por migración tiene que estar en schema_pg.sql.

En Postgres `init_db()` **no replica las migraciones incrementales**: mira
`USANDO_PG`, aplica `schema_pg.sql` y vuelve (main.py:859). Es una decisión
deliberada y está bien argumentada —46 migraciones traducidas son 46
oportunidades de equivocarse para llegar al mismo lugar— pero tiene una
consecuencia que no perdona: **una columna agregada con `ALTER TABLE` en el
camino de SQLite y olvidada en `schema_pg.sql` simplemente no existe en
Postgres**, y la consulta que la lea falla.

Cuánto duele depende de dónde se lea. `requires_plan` se agregó al SELECT que
valida el token, o sea el que corre en TODOS los requests autenticados: en
Postgres eso no es un bug, es la app entera caída. Y no lo avisa ningún test,
porque la suite corre sobre SQLite, donde la migración sí corre.

Esta familia ya tiró producción una vez en este repo (2026-08-02, el índice
creado antes que su columna). Este test es el guard de la familia entera, no
de una columna: cualquier `ALTER TABLE ... ADD COLUMN` nuevo que no se refleje
en `schema_pg.sql` sale en rojo acá.

Corre con: cd backend && python3 -m pytest tests/test_schema_pg_al_dia.py
"""
import io
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

MAIN = os.path.join(BACKEND, "main.py")
SCHEMA_PG = os.path.join(BACKEND, "schema_pg.sql")


def _columnas_del_schema_pg(tabla: str) -> set:
    """Las columnas declaradas para `tabla` en schema_pg.sql."""
    pg = io.open(SCHEMA_PG, encoding="utf-8").read()
    bloque = re.search(
        r"CREATE TABLE IF NOT EXISTS %s \((.*?)\n\);" % re.escape(tabla), pg, re.S)
    assert bloque, f"no encontré la tabla {tabla} en schema_pg.sql"
    # Cada línea de columna arranca con exactamente dos espacios y su nombre.
    return set(re.findall(r"^\s{2}(\w+)\s", bloque.group(1), re.M))


def _columnas_agregadas_por_migracion() -> dict:
    """{tabla: [columnas]} de todos los ALTER TABLE ... ADD COLUMN de main.py."""
    main = io.open(MAIN, encoding="utf-8").read()
    fuera = {}
    for tabla, col in re.findall(
            r"ALTER TABLE (\w+) ADD COLUMN (\w+)", main):
        fuera.setdefault(tabla, []).append(col)
    return fuera


class SchemaPgAlDia(unittest.TestCase):

    def test_los_dos_archivos_existen(self):
        """Si alguien los mueve, este test avisa — no pasa en verde por no
        encontrar nada que comparar."""
        self.assertTrue(os.path.exists(MAIN), MAIN)
        self.assertTrue(os.path.exists(SCHEMA_PG), SCHEMA_PG)

    def test_hay_migraciones_para_comparar(self):
        """Contra el falso verde: si el regex deja de matchear (porque cambió la
        forma de escribir los ALTER), el test de abajo pasaría sin comparar
        nada."""
        agregadas = _columnas_agregadas_por_migracion()
        self.assertIn("users", agregadas)
        self.assertGreater(len(agregadas["users"]), 10,
                           "el regex de los ALTER dejó de encontrar migraciones")

    def test_toda_columna_migrada_esta_en_el_schema_de_postgres(self):
        agregadas = _columnas_agregadas_por_migracion()
        faltantes = {}
        for tabla, cols in agregadas.items():
            try:
                en_pg = _columnas_del_schema_pg(tabla)
            except AssertionError:
                # La tabla no existe en schema_pg.sql: es otro problema y lo
                # reporta el test de abajo, no este.
                continue
            faltan = [c for c in cols if c not in en_pg]
            if faltan:
                faltantes[tabla] = faltan
        self.assertEqual(
            faltantes, {},
            "estas columnas se agregan por migración en SQLite y NO están en "
            "schema_pg.sql, así que en Postgres no existen y cualquier consulta "
            f"que las lea falla: {faltantes}")

    def test_toda_tabla_migrada_existe_en_el_schema_de_postgres(self):
        pg = io.open(SCHEMA_PG, encoding="utf-8").read()
        for tabla in _columnas_agregadas_por_migracion():
            self.assertIn(
                f"CREATE TABLE IF NOT EXISTS {tabla} ", pg,
                f"la tabla {tabla} recibe ALTERs en SQLite y no existe en "
                "schema_pg.sql")

    def test_requires_plan_es_el_caso_que_motivó_este_archivo(self):
        """Regresión explícita: se lee en el SELECT que valida el token, o sea
        en cada request autenticado."""
        self.assertIn("requires_plan", _columnas_del_schema_pg("users"))


if __name__ == "__main__":
    unittest.main()
