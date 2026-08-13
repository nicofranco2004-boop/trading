"""¿Qué datos de la base actual RECHAZARÍA Postgres?

Por qué existe. SQLite tiene tipificación LAXA: una columna declarada REAL acepta
un texto, un '' o un None sin chistar. Postgres es estricto. Después de meses de
imports de una decena de brokers, la pregunta que decide si migrar es de dos
semanas o de seis no es "cuánto SQL hay que reescribir" —eso ya está contado—
sino "cuántas filas de datos REALES no van a entrar".

Y el peor caso no es que la carga falle: es que convierta mal en silencio y le
cambie el número a alguien. En una app donde la gente mira su plata, eso no se
descubre con tests, se descubre con un reclamo.

Este audit lee `typeof()` de cada valor y lo compara contra el tipo que Postgres
va a exigir según el DECLARADO en el schema. Es SÓLO LECTURA.

Cuidado deliberado con el lock: la base es de ~1 GB y un scan largo mantiene una
transacción de lectura abierta, lo que impide que el WAL haga checkpoint (ver el
incidente del 12-13/08). Por eso cada columna va en su propia consulta corta y
las tablas gigantes se MUESTREAN, diciéndolo en el resultado.
"""

# Umbral a partir del cual muestreamos en vez de escanear entero. Las tablas de
# import tienen ~1M de filas cada una; escanear las 3 enteras, columna por
# columna, son minutos de lectura sostenida.
FILAS_SCAN_COMPLETO = 200_000
MUESTRA = 200_000

# Cómo mapea un tipo declarado de SQLite al de Postgres, y qué `typeof()` acepta.
# SQLite devuelve: 'null' | 'integer' | 'real' | 'text' | 'blob'.
_MAPA = {
    "INTEGER": ("bigint", {"null", "integer"}),
    "REAL":    ("double precision", {"null", "integer", "real"}),
    "NUMERIC": ("numeric", {"null", "integer", "real"}),
    "TEXT":    ("text", {"null", "text", "integer", "real"}),   # todo se castea a texto
    "BLOB":    ("bytea", {"null", "blob"}),
    "":        ("text", {"null", "text", "integer", "real", "blob"}),  # sin tipo: Postgres necesita uno
}


def _pg_de(decl: str):
    d = (decl or "").upper().strip()
    for k, v in _MAPA.items():
        if k and d.startswith(k):
            return v
    if "CHAR" in d or "CLOB" in d:
        return _MAPA["TEXT"]
    if "INT" in d:
        return _MAPA["INTEGER"]
    if "FLOA" in d or "DOUB" in d:
        return _MAPA["REAL"]
    return _MAPA[""]


def auditar(conn, incluir_ok: bool = False) -> dict:
    """Devuelve, por columna, qué tipos hay realmente y cuáles rompen en Postgres."""
    tablas = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]

    problemas, revisados, saltados = [], 0, []
    resumen_tablas = []

    for t in tablas:
        try:
            n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        except Exception as ex:
            saltados.append({"tabla": t, "error": f"{type(ex).__name__}: {ex}"})
            continue
        if n == 0:
            resumen_tablas.append({"tabla": t, "filas": 0, "muestreada": False})
            continue

        muestreada = n > FILAS_SCAN_COMPLETO
        origen = (f'(SELECT * FROM "{t}" LIMIT {MUESTRA})' if muestreada else f'"{t}"')
        resumen_tablas.append({"tabla": t, "filas": n, "muestreada": muestreada})

        cols = conn.execute(f'PRAGMA table_info("{t}")').fetchall()
        for c in cols:
            nombre, decl, notnull = c[1], c[2], c[3]
            pg, aceptados = _pg_de(decl)
            revisados += 1
            try:
                filas = conn.execute(
                    f'SELECT typeof("{nombre}") AS t, COUNT(*) AS n FROM {origen} GROUP BY 1'
                ).fetchall()
            except Exception as ex:
                saltados.append({"tabla": t, "columna": nombre,
                                 "error": f"{type(ex).__name__}: {ex}"})
                continue

            vistos = {r[0]: r[1] for r in filas}
            malos = {k: v for k, v in vistos.items() if k not in aceptados}

            # '' en una columna numérica es EL caso clásico de los parsers: SQLite
            # lo guarda como texto vacío y Postgres lo rechaza (o peor, si alguien
            # "arregla" con un cast, lo convierte en 0 y eso es un número inventado).
            vacios = 0
            if pg in ("bigint", "double precision", "numeric") and vistos.get("text"):
                try:
                    vacios = conn.execute(
                        f'SELECT COUNT(*) FROM {origen} WHERE typeof("{nombre}")=\'text\' '
                        f'AND TRIM("{nombre}")=\'\''
                    ).fetchone()[0]
                except Exception:
                    pass

            nulls_en_notnull = 0
            if notnull and vistos.get("null"):
                nulls_en_notnull = vistos["null"]

            if malos or nulls_en_notnull:
                problemas.append({
                    "tabla": t, "columna": nombre,
                    "declarado": decl or "(sin tipo)", "postgres": pg,
                    "filas_tabla": n, "muestreada": muestreada,
                    "tipos_encontrados": vistos,
                    "rompen": malos,
                    "n_rompen": sum(malos.values()),
                    "de_esos_string_vacio": vacios,
                    "nulls_en_columna_not_null": nulls_en_notnull,
                })
            elif incluir_ok:
                problemas.append({"tabla": t, "columna": nombre, "ok": True,
                                  "tipos_encontrados": vistos})

    # Lo que más duele primero.
    problemas.sort(key=lambda p: -(p.get("n_rompen", 0) + p.get("nulls_en_columna_not_null", 0)))

    total_malas = sum(p.get("n_rompen", 0) for p in problemas)
    return {
        "veredicto": (
            "LIMPIO — ninguna columna tiene valores que Postgres rechace"
            if not total_malas else
            f"{len(problemas)} columnas con datos incompatibles ({total_malas:,} filas)"
        ),
        "columnas_revisadas": revisados,
        "tablas": len(tablas),
        "problemas": problemas,
        "saltados": saltados,
        "detalle_tablas": resumen_tablas,
        "nota": (
            f"Las tablas de más de {FILAS_SCAN_COMPLETO:,} filas se MUESTREARON "
            f"(primeras {MUESTRA:,}); en ésas los conteos son un piso, no un total. "
            "Todo esto es sólo lectura."
        ),
    }
