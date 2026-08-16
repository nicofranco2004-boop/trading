"""Copia la base de Rendi de SQLite a Postgres. Se corre UNA vez, con la app abajo.

SE ESCRIBE DESPUÉS DE LA VERIFICACIÓN, y el orden no es negociable: escrito el
copiador primero, uno mira lo que produjo y lo acepta, porque no tiene contra qué
compararlo. La vara es `verificar_copia.py` y **la única forma de aceptar esto es
que sus cuatro niveles den CERO hallazgos**.

CUATRO SUBCOMANDOS, y están separados porque hacen cosas distintas de reversibles:

    aplicar-esquema   crea las 60 tablas en el destino (idempotente)
    preflight         SÓLO LEE. Busca en el origen lo que rompería la copia a mitad
                      de camino. Es la precondición dura de `copiar`.
    preparar-destino  ESCRIBE: vacía el destino. Para reintentar.
    copiar            ESCRIBE: la copia + los setval + la verificación final

⚠️ **EL VACIADO DE `raw_json` NO ES PARTE DE ESTO.** Se decidió migrar todo
(sesión 9): vaciarlo apagaba CUATRO lectores y no uno. Queda como tarea aparte,
cualquier martes, ya sobre Postgres. **La consecuencia importa más que la decisión:
el día del pasaje se queda SIN ningún paso irreversible antes de los chequeos.** Si
algo sale mal, se saca `DATABASE_URL` y no hay nada que deshacer sobre el origen.

LAS DECISIONES QUE SOSTIENEN ESTO, y por qué (salieron de atacar el diseño ANTES de
escribirlo: 66 hallazgos, 40 ataques, 5 bloqueantes):

1. **`psycopg` crudo, nunca `pgshim`.** El shim traduce SQL de SQLite y emula
   `lastrowid` cacheando la PK de cada tabla. Acá se insertan filas CON su id
   original y se habla en SQL de Postgres: no hay nada que traducir, y sí un caché
   que podría estorbar.

2. **NUNCA `with destino.transaction()`.** Se hace el trabajo y se llama
   `destino.commit()` explícito. El `with` sólo commitea si es la transacción MÁS
   EXTERNA, y cualquier consulta previa sobre la misma conexión ya abrió una: ahí
   el bloque se degrada a `SAVEPOINT`, sale con `RELEASE`, y al cerrar la conexión
   **el servidor rollbackea todo**. La herramienta habría reportado éxito, con el
   cronómetro completo y los cuatro niveles en verde, sobre una base vacía.

3. **La verificación final corre en una conexión NUEVA, abierta DESPUÉS del
   commit.** Sobre la misma conexión uno ve sus propias escrituras: eso prueba que
   la transacción existe, no que los datos quedaron. Es la diferencia entre "veo lo
   que escribí" y "la base tiene los datos".

4. **Qué copiar sale del ORIGEN y no hay parámetro para pedir otra cosa.** Misma
   regla que `verificar_copia.comparar()`. Preguntarle al destino qué copiar es
   preguntarle al sospechoso: una tabla que no está en el destino no entraría al
   bucle y nadie se enteraría.

5. **El origen se abre SÓLO LECTURA.** Es la base de la que dependen 1.084
   personas: si algo acá tiene un bug, que no pueda escribir.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verificar_copia as vc  # noqa: E402

# Cada cuántas filas se avisa. Sin esto, `import_raw_rows` (3,1M) es una caja negra:
# desde otra sesión un `SELECT count(*)` da CERO porque la transacción no commiteó,
# y el operador tiene que decidir a ciegas si esperar o cortar.
_AVISAR_CADA = 250_000


class NoSePuedeCopiar(Exception):
    """Una precondición no se cumple. Aborta ANTES de tocar el destino."""


# ── Abrir las dos puntas ─────────────────────────────────────────────────────

def abrir_origen(ruta: str) -> sqlite3.Connection:
    """La SQLite de producción, SÓLO LECTURA.

    ⚠️ **El chequeo del `-wal` es el que evita el peor error posible del día.** Esta
    base corre en WAL (`main.py:351`). Si alguien se baja `trading.db` sin su
    archivo `-wal`, `mode=ro` falla con `unable to open database file` — un mensaje
    que no dice nada. El reflejo del operador es sacarle el `mode=ro` "para ver si
    es eso": ahí abre bien y lee **sólo lo checkpointeado**, perdiendo en silencio
    las últimas transacciones de todos los usuarios. Y ninguno de los cuatro
    niveles lo podría ver, porque el destino se compara contra esa misma lectura
    mal hecha. Es "verificar contra la fuente equivocada" en su forma más cara.

    Por eso el mensaje ES el arreglo: la apertura ya falla; lo que faltaba era que
    el operador entendiera por qué.
    """
    if not os.path.exists(ruta):
        raise NoSePuedeCopiar(f"no existe el origen: {ruta}")
    wal = ruta + "-wal"
    if os.path.exists(wal) and os.path.getsize(wal) > 0:
        raise NoSePuedeCopiar(
            f"el origen tiene un WAL con datos sin checkpointear ({wal}, "
            f"{os.path.getsize(wal):,} bytes).\n"
            f"Copiar así lee sólo lo checkpointeado y PIERDE en silencio las "
            f"últimas transacciones de todos los usuarios.\n"
            f"Con el backend YA FRENADO, corré sobre la base:\n"
            f"    sqlite3 {ruta} 'PRAGMA wal_checkpoint(TRUNCATE);'\n"
            f"y recién ahí copiá el archivo. NUNCA saques el mode=ro para "
            f"'ver si es eso': eso hace que abra y lea de menos.")
    return sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)


def abrir_destino(dsn: str, autocommit: bool = False):
    """El Postgres. `prepare_threshold=None` porque el pooler transaccional de
    Supabase (puerto 6543) rompe las sentencias preparadas."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import pgsesion
    # Por `pgsesion` aunque este script NO use el shim: lo que se importa es el
    # ajuste de sesión, no la traducción de SQL. Sin `extra_float_digits=3` la
    # verificación denuncia diferencias que no existen en los datos — medido: 73
    # de 350 filas leídas distinto, con los bits en disco IDÉNTICOS.
    return pgsesion.conectar(dsn, autocommit=autocommit, prepare_threshold=None)


# Cuánto disco necesita el destino, por cada byte del archivo de origen.
#
# 🔴 **Este número existe porque no contarlo tumbó un destino.** Copiando 1 GB a un
# Supabase Free, la instancia se cayó con el disco al 100%, y el desglose del panel
# fue el hallazgo: `DATABASE 553 MB · WAL 660 MB · SYSTEM 759 MB`. El cuaderno de
# borrador pesaba MÁS que los datos.
#
# Es consecuencia directa de que la copia va en UNA transacción (para que un corte
# no deje nada a medias): el WAL no se recicla hasta el commit, y los 62 índices lo
# multiplican porque cada índice también escribe WAL.
#
# Medido con `scripts/vigilar_espacio.py` sobre la base de forma real:
#     datos 1.211 MB + WAL 1.606 MB = pico simultáneo 2.817 MB, sobre un .db de
#     1.071 MB → **2,63×**
# ⚠️ Con `wal_compression=off`. Si el destino lo tuviera prendido, sería menos: el
# 2,63 es un TECHO, no un piso.
_DISCO_POR_BYTE_DE_ORIGEN = 2.63


def espacio_que_va_a_necesitar(ruta_origen: str) -> Dict[str, float]:
    """Cuánto disco tiene que tener libre el destino, A LA VEZ.

    No es cuánto va a ocupar al final: es el pico, que es casi el doble. Se
    imprime SIEMPRE, antes de copiar, porque es exactamente el dato que no se miró
    la vez que se cayó el destino — y era mirable.
    """
    gb = os.path.getsize(ruta_origen) / 1e9
    return {"origen_gb": round(gb, 2),
            "pico_gb": round(gb * _DISCO_POR_BYTE_DE_ORIGEN, 2),
            "factor": _DISCO_POR_BYTE_DE_ORIGEN}


def _avisar_espacio(ruta_origen: str) -> None:
    e = espacio_que_va_a_necesitar(ruta_origen)
    print(f"espacio que el destino tiene que tener LIBRE: ~{e['pico_gb']:.1f} GB "
          f"({e['factor']}× el origen, que son {e['origen_gb']:.1f} GB)")
    print(f"   es el PICO simultáneo —datos + WAL—, no lo que queda al final.")
    print(f"   ⚠️ si el destino no lo tiene, se cae a mitad de la copia: ya pasó.")


def huella_origen(conn: sqlite3.Connection, ruta: str) -> Dict[str, Any]:
    """Con qué base se está trabajando, para que quede en la bitácora.

    Existe porque un preflight limpio sobre la base SINTÉTICA es una tautología:
    esa base se construye con `init_db()`, la misma fuente que `schema_pg.sql`, así
    que **no puede** devolver un hallazgo de esquema. La huella lo hace visible: si
    no es la de la copia restaurada de producción, el preflight midió otra cosa.
    """
    filas = conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
    h = hashlib.md5()
    for nombre, sql in filas:
        h.update((nombre or "").encode())
        h.update(b"\x1f")
        h.update((sql or "").encode())
    st = os.stat(ruta)
    return {"esquema_md5": h.hexdigest(), "bytes": st.st_size,
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(st.st_mtime))}


# ── El orden de copiado ──────────────────────────────────────────────────────

def _fks_del_destino(cur) -> List[Tuple[str, str, str]]:
    """[(tabla_hija, columna, tabla_padre)] leído del catálogo real de Postgres."""
    return [(r[0], r[1], r[2]) for r in cur.execute("""
        SELECT c.relname, a.attname, f.relname
          FROM pg_constraint con
          JOIN pg_class c ON c.oid = con.conrelid
          JOIN pg_class f ON f.oid = con.confrelid
          JOIN pg_namespace n ON n.oid = con.connamespace
          JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = con.conkey[1]
         WHERE con.contype = 'f' AND n.nspname = current_schema()
         ORDER BY c.relname, a.attname
    """).fetchall()]


def orden_de_copia(tablas: set, fks: List[Tuple[str, str, str]]
                   ) -> Tuple[List[str], List[Tuple[str, str]]]:
    """(orden de tablas, auto-referencias) para no violar una FK al insertar.

    Devuelve TAMBIÉN las auto-referencias que tuvo que romper —hoy es
    `brokers.parent_broker_id`— y no las deja escritas a mano en ningún lado. Es a
    propósito: si mañana aparece una segunda, el copiador la maneja solo. Un nombre
    de tabla hardcodeado en dos lugares es la forma en que una defensa queda a
    medias sin que nadie lo note.

    Con una tabla que se referencia a sí misma, ningún orden ENTRE tablas alcanza:
    el orden también existe DENTRO de la tabla (un broker hijo no puede entrar
    antes que su padre). Se resuelve copiando esa columna en NULL y llenándola en
    una segunda pasada, que es más simple y más robusto que ordenar las filas.
    """
    deps: Dict[str, set] = {t: set() for t in tablas}
    self_loops: List[Tuple[str, str]] = []
    for hija, col, padre in fks:
        if hija not in deps or padre not in deps:
            continue
        if hija == padre:
            self_loops.append((hija, col))
        else:
            deps[hija].add(padre)

    orden: List[str] = []
    pendientes = dict(deps)
    while pendientes:
        libres = sorted(t for t, d in pendientes.items()
                        if not (d & set(pendientes)))
        if not libres:
            # No puede pasar con las 12 FKs de hoy, pero si alguien agrega un ciclo
            # entre DOS tablas, el copiador tiene que decirlo y no elegir un orden
            # cualquiera: insertaría filas que violan la FK y fallaría a mitad.
            raise NoSePuedeCopiar(
                f"hay un ciclo de claves foráneas entre tablas y no hay orden "
                f"posible: {sorted(pendientes)}. Con un ciclo entre dos tablas "
                f"distintas hace falta decidir cuál se copia en NULL primero, y "
                f"eso es una decisión, no algo para adivinar acá.")
        for t in libres:
            orden.append(t)
            del pendientes[t]
    return orden, self_loops


# ── PREFLIGHT: lo que rompería la copia a mitad de la ventana ────────────────

def preflight(origen: sqlite3.Connection, cur_destino) -> List[Dict[str, Any]]:
    """SÓLO LEE. Devuelve los hallazgos; lista vacía = se puede copiar.

    El día del pasaje la app está abajo. Un error a mitad de la copia no es "se
    reintenta": es la ventana consumida. Todo lo que se pueda saber ANTES, se sabe
    antes — y este preflight se corre días antes sobre la copia restaurada, no ese
    domingo.

    ⚠️ **La lista de QUÉ mirar sale del ORIGEN; los TIPOS ESPERADOS del destino.**
    Es la misma división que en `verificar_copia.comparar()`: el destino es el
    único que tiene tipos declarados de verdad, pero preguntarle qué revisar sería
    preguntarle al sospechoso.
    """
    hallazgos: List[Dict[str, Any]] = []

    def anotar(chequeo, que, **extra):
        hallazgos.append(dict(chequeo=chequeo, que=que, **extra))

    tablas_o, cols_o = vc.catalogo_origen(vc.CursorSqlite(origen))
    esquema_d = vc.esquema_pg(cur_destino)

    # ── P1: las tablas ───────────────────────────────────────────────────────
    for t in sorted(tablas_o - set(esquema_d)):
        anotar("P1", f"la tabla {t!r} está en el ORIGEN y no en el destino: no se "
                     f"copiaría y nadie se enteraría", tabla=t)
    for t in sorted(set(esquema_d) - tablas_o):
        anotar("P1", f"la tabla {t!r} está en el destino y no en el origen", tabla=t)
    comunes = sorted(tablas_o & set(esquema_d))

    # ── P2: las columnas ─────────────────────────────────────────────────────
    for t in comunes:
        en_d = {c for c, _ in esquema_d[t]}
        en_o = set(cols_o[t])
        if en_o - en_d:
            anotar("P2", f"columnas en el ORIGEN que el destino no tiene: "
                         f"{sorted(en_o - en_d)}", tabla=t)
        if en_d - en_o:
            anotar("P2", f"columnas en el destino que el origen no tiene: "
                         f"{sorted(en_d - en_o)}", tabla=t)

    # ── P3: NOT NULL ─────────────────────────────────────────────────────────
    # ⚠️ Se miran TODAS las columnas NOT NULL, incluidas las que tienen DEFAULT.
    # Una versión anterior filtraba `AND column_default IS NULL` y eso restaba
    # cobertura justo donde importa: `NOT NULL DEFAULT x` es la forma canónica de
    # agregarle NOT NULL a una tabla que ya existe (SQLite no acepta ADD COLUMN
    # NOT NULL sin default), así que ahí caen `positions.user_id`,
    # `operations.user_id`, `snapshots.net_deposited` y `brokers.currency`. Y el
    # DEFAULT no salva: el COPY manda todas las columnas, y una columna presente
    # con NULL inserta NULL — el default sólo cubre columnas OMITIDAS.
    notnull = cur_destino.execute("""
        SELECT table_name, column_name FROM information_schema.columns
         WHERE table_schema = current_schema() AND is_nullable = 'NO'
         ORDER BY table_name, column_name""").fetchall()
    for t, c in notnull:
        if t not in comunes or c not in cols_o[t]:
            continue
        n = origen.execute(f'SELECT COUNT(*) FROM "{t}" WHERE "{c}" IS NULL').fetchone()[0]
        if n:
            anotar("P3", f"{n:,} filas con {c!r} en NULL, y el destino la declara "
                         f"NOT NULL", tabla=t, columna=c, filas=n)

    # ── P4: números que no son números ───────────────────────────────────────
    # SQLite acepta el texto '' o 'N/A' adentro de una columna declarada REAL.
    # Postgres no: la copia cortaría a mitad de la ventana. Se mira por `typeof`
    # de cada valor, que es lo único que dice qué hay ADENTRO y no qué se declaró.
    for t in comunes:
        tipos_d = dict(esquema_d[t])
        for c in cols_o[t]:
            td = tipos_d.get(c)
            if td == "bigint":
                malos = "('integer','null')"
            elif td == "double precision":
                malos = "('integer','real','null')"
            else:
                continue
            n = origen.execute(
                f'SELECT COUNT(*) FROM "{t}" WHERE typeof("{c}") NOT IN {malos}'
            ).fetchone()[0]
            if n:
                ejemplo = origen.execute(
                    f'SELECT "{c}", typeof("{c}") FROM "{t}" '
                    f'WHERE typeof("{c}") NOT IN {malos} LIMIT 1').fetchone()
                anotar("P4", f"{n:,} valores no numéricos en una columna {td} "
                             f"(ej: {ejemplo[0]!r}, typeof={ejemplo[1]})",
                       tabla=t, columna=c, filas=n)

    # ── P5: texto que Postgres no acepta como texto ──────────────────────────
    # Dos cosas en la misma pasada: el byte NUL —que Postgres rechaza adentro de
    # un `text`— y los BLOB, que sin `set_types` entrarían como el string
    # `\x616263` y sólo los agarraría el NIVEL 1, después del pasaje y sin decir
    # qué columna. Candidata real: `advisor_profile.logo_data`, un TEXT con un logo.
    for t in comunes:
        tipos_d = dict(esquema_d[t])
        for c in cols_o[t]:
            if tipos_d.get(c) != "text":
                continue
            n = origen.execute(
                f'SELECT COUNT(*) FROM "{t}" WHERE typeof("{c}")=\'blob\' '
                f'OR (typeof("{c}")=\'text\' AND instr("{c}", char(0)) > 0)'
            ).fetchone()[0]
            if n:
                anotar("P5", f"{n:,} valores BLOB o con byte NUL en una columna "
                             f"text", tabla=t, columna=c, filas=n)

    # ── P6: claves foráneas huérfanas en el ORIGEN ───────────────────────────
    # Si el origen tiene una fila cuyo padre no existe, SQLite la aguanta (las FKs
    # están apagadas por defecto) y Postgres la rechaza. Es una DECISIÓN —borrar la
    # huérfana o poner NULL— y hay que tomarla días antes, con luz de día, no a las
    # 10 de la mañana de un domingo.
    for hija, col, padre in _fks_del_destino(cur_destino):
        if hija not in comunes or padre not in comunes:
            continue
        pk = _pk_de(cur_destino, padre)
        if not pk:
            continue
        n = origen.execute(
            f'SELECT COUNT(*) FROM "{hija}" h WHERE h."{col}" IS NOT NULL '
            f'AND NOT EXISTS (SELECT 1 FROM "{padre}" p WHERE p."{pk}" = h."{col}")'
        ).fetchone()[0]
        if n:
            anotar("P6", f"{n:,} filas huérfanas: {hija}.{col} apunta a un "
                         f"{padre}.{pk} que no existe", tabla=hija, columna=col, filas=n)

    # ── P7: claves foráneas DUPLICADAS en el destino ─────────────────────────
    # ⚠️ Una versión anterior comparaba el total contra un **12 hardcodeado**, y
    # estaba midiendo lo equivocado por dos motivos: el número se desactualiza
    # solo con cualquier tabla nueva, y sobre todo **no es el número lo que
    # importa, es la repetición**. El modo de falla real es aplicar el esquema dos
    # veces cuando las FKs iban sin nombre: Postgres les inventaba un nombre libre
    # y creaba una segunda constraint IDÉNTICA. Cada duplicado valida la tabla
    # hija entera durante el COPY, y 5 de las 12 caen sobre tablas de ~1M.
    # Buscar el duplicado directamente no necesita saber cuántas tiene que haber.
    vistas: Dict[Tuple[str, str, str], int] = {}
    for hija, col, padre in _fks_del_destino(cur_destino):
        vistas[(hija, col, padre)] = vistas.get((hija, col, padre), 0) + 1
    for (hija, col, padre), n in sorted(vistas.items()):
        if n > 1:
            anotar("P7", f"la clave foránea {hija}.{col} → {padre} está {n} veces. "
                         f"El esquema se aplicó más de una vez y cada copia valida "
                         f"la tabla hija entera durante el COPY",
                   tabla=hija, columna=col, veces=n)

    # ── P8: las secuencias del destino existen para lo que el origen autoincrementa
    # Mira desde el ORIGEN a propósito: `sqlite_sequence` sabe qué tablas
    # autoincrementan de verdad. Enumerar sólo por `attidentity` del destino sería
    # que el chequeo y el arreglo salgan del mismo lado, y entonces no puede fallar.
    try:
        auto_o = {r[0] for r in origen.execute("SELECT name FROM sqlite_sequence")}
    except sqlite3.OperationalError:
        auto_o = set()          # la tabla no existe: ninguna tabla autoincrementó aún
        anotar("P8", "el origen no tiene `sqlite_sequence`: ninguna tabla "
                     "autoincrementó nunca. Raro en producción, se anota.")
    # ⚠️ `_identidades` devuelve (tabla, columna); acá se compara contra nombres
    # de tabla. Comparar los dos conjuntos sin achicar la tupla daba las 8 tablas
    # como hallazgo — un falso positivo del chequeo, no del esquema.
    ident_d = {t for t, _c in _identidades(cur_destino)}
    for t in sorted(auto_o - ident_d):
        if t in comunes:
            anotar("P8", f"{t!r} autoincrementa en el origen y en el destino no es "
                         f"IDENTITY: el próximo alta no tiene de dónde sacar el id",
                   tabla=t)
    return hallazgos


def _pk_de(cur, tabla: str) -> Optional[str]:
    r = cur.execute("""
        SELECT a.attname FROM pg_index i
          JOIN pg_class c ON c.oid = i.indrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
          JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
         WHERE i.indisprimary AND c.relname = %s AND n.nspname = current_schema()
         LIMIT 1""", (tabla,)).fetchone()
    return r[0] if r else None


def _identidades(cur) -> List[Tuple[str, str]]:
    """[(tabla, columna)] de las columnas GENERATED ... AS IDENTITY del destino."""
    return [(r[0], r[1]) for r in cur.execute("""
        SELECT c.relname, a.attname
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
          JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0
         WHERE n.nspname = current_schema() AND c.relkind = 'r'
           AND a.attidentity IN ('a', 'd')
         ORDER BY c.relname""").fetchall()]


# ── LA COPIA ─────────────────────────────────────────────────────────────────

def copiar_tabla(origen, destino, tabla: str, columnas: List[str],
                 en_null: Tuple[str, ...] = (), avisar=None) -> int:
    """Copia una tabla con COPY FROM STDIN. Devuelve las filas escritas.

    `en_null` son las columnas que van vacías en esta pasada — las
    auto-referencias, que se llenan después. Se pasan explícitas y no se adivinan.

    **Sin `set_types`.** Los tres tipos del destino (text, bigint, double
    precision) castean bien desde el literal de texto que manda psycopg, y un texto
    adentro de una columna bigint da ERROR — que es lo correcto, y que además el
    preflight ya agarró días antes (P4).
    """
    lista = ", ".join(f'"{c}"' for c in columnas)
    idx_null = {i for i, c in enumerate(columnas) if c in en_null}
    n = 0
    cur = origen.execute(f'SELECT {lista} FROM "{tabla}"')
    with destino.cursor().copy(f'COPY "{tabla}" ({lista}) FROM STDIN') as cp:
        for fila in cur:
            if idx_null:
                fila = tuple(None if i in idx_null else v for i, v in enumerate(fila))
            cp.write_row(fila)
            n += 1
            if avisar and n % _AVISAR_CADA == 0:
                avisar(tabla, n)
    return n


def segunda_pasada(origen, destino, self_loops: List[Tuple[str, str]]) -> int:
    """Llena las auto-referencias que la primera pasada dejó en NULL.

    Va por UPDATE fila por fila y no por COPY: son pocas (hoy, los brokers con
    padre) y un UPDATE dirigido no puede tocar nada más.
    """
    total = 0
    for tabla, col in self_loops:
        pk = _pk_de(destino.cursor(), tabla)
        if not pk:
            raise NoSePuedeCopiar(
                f"{tabla!r} se auto-referencia por {col!r} y no tiene clave "
                f"primaria en el destino: no hay por dónde llenar la segunda pasada")
        filas = origen.execute(
            f'SELECT "{pk}", "{col}" FROM "{tabla}" WHERE "{col}" IS NOT NULL'
        ).fetchall()
        with destino.cursor() as c:
            c.executemany(f'UPDATE "{tabla}" SET "{col}" = %s WHERE "{pk}" = %s',
                          [(v, k) for k, v in filas])
        total += len(filas)
    return total


def correr_setval(destino) -> List[Tuple[str, str, int]]:
    """`setval` en cada secuencia. Devuelve [(tabla, columna, hasta)].

    Las PK son `GENERATED BY DEFAULT` justamente para poder insertar cada fila con
    su id original; el precio es que la secuencia queda en 1 y hay que adelantarla.
    Sin esto, **el primer usuario que se registre después del pasaje choca contra un
    id que ya existe.**

    ⚠️ **Las secuencias NO son transaccionales**: un `setval` no vuelve atrás con el
    ROLLBACK. No cambia el plan —si la copia falla se vacía el destino y se
    reintenta, y el setval siguiente pisa al anterior— pero conviene saberlo antes
    de leer un rollback y creer que quedó todo como estaba.
    """
    hechos = []
    with destino.cursor() as c:
        for tabla, col in _identidades(c):
            maximo = c.execute(f'SELECT MAX("{col}") FROM "{tabla}"').fetchone()[0]
            if maximo is None:
                continue                      # tabla vacía: la secuencia sirve como está
            c.execute("SELECT setval(pg_get_serial_sequence(%s, %s), %s, true)",
                      (tabla, col, int(maximo)))
            hechos.append((tabla, col, int(maximo)))
    return hechos


def destino_esta_vacio(cur, tablas: List[str]) -> List[str]:
    """Las tablas del destino que YA tienen filas.

    Se mide, no se sella. Un "certificado" de que el destino estaba vacío es un
    papel que se puede copiar de otra corrida; contar las filas ahora mismo, no.
    """
    con_datos = []
    for t in tablas:
        if cur.execute(f'SELECT EXISTS (SELECT 1 FROM "{t}")').fetchone()[0]:
            con_datos.append(t)
    return con_datos


# ── Los subcomandos ──────────────────────────────────────────────────────────

def _guarda_de_escritura(sub: str):
    """Los subcomandos que ESCRIBEN no corren con `DATABASE_URL` puesta.

    Si la app ya está migrada y corriendo, `DATABASE_URL` apunta a la base VIVA.
    Un `preparar-destino` ahí borra todo. Los que sólo leen (`preflight`,
    `verificar`) no tienen por qué abortar.
    """
    if os.environ.get("DATABASE_URL"):
        raise NoSePuedeCopiar(
            f"`{sub}` escribe, y hay una `DATABASE_URL` en el ambiente. Si la app "
            f"ya está migrada, ésa es la base VIVA de 1.084 personas.\n"
            f"Pasá el destino con --destino y corré esto sin `DATABASE_URL`.")


def cmd_aplicar_esquema(args) -> int:
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "schema_pg.sql")
    ddl = open(ruta, encoding="utf-8").read()
    import psycopg
    with abrir_destino(args.destino, autocommit=True) as d:
        ok = 0
        for s in [x.strip() for x in ddl.split(";\n") if x.strip()]:
            try:
                d.execute(s)
                ok += 1
            except psycopg.errors.DuplicateObject:
                ok += 1               # la FK ya estaba: el esquema es re-aplicable
        n = d.execute("SELECT count(*) FROM information_schema.tables "
                      "WHERE table_schema = current_schema()").fetchone()[0]
    print(f"esquema aplicado: {ok} sentencias, {n} tablas")
    return 0


def cmd_preflight(args) -> int:
    origen = abrir_origen(args.origen)
    try:
        print(f"origen: {args.origen}")
        for k, v in huella_origen(origen, args.origen).items():
            print(f"   {k}: {v}")
        _avisar_espacio(args.origen)
        with abrir_destino(args.destino, autocommit=True) as d:
            hallazgos = preflight(origen, vc.CursorPg(d))
    finally:
        origen.close()
    if not hallazgos:
        print("\n✅ preflight LIMPIO: no hay nada que rompa la copia a mitad de camino")
        return 0
    print(f"\n🔴 {len(hallazgos)} hallazgo(s). NO se copia hasta resolverlos:")
    for h in hallazgos:
        donde = f"{h.get('tabla','')}" + (f".{h['columna']}" if h.get("columna") else "")
        print(f"   [{h['chequeo']}] {donde}: {h['que']}")
    return 1


def cmd_preparar_destino(args) -> int:
    _guarda_de_escritura("preparar-destino")
    origen = abrir_origen(args.origen)
    try:
        tablas, _ = vc.catalogo_origen(vc.CursorSqlite(origen))
    finally:
        origen.close()
    lista = ", ".join(f'"{t}"' for t in sorted(tablas))
    with abrir_destino(args.destino, autocommit=True) as d:
        # Un solo TRUNCATE con todas: tabla por tabla no se puede con las FKs
        # prendidas. **Sin CASCADE**: CASCADE arrastra tablas que no están en la
        # lista, en silencio, y "en silencio" es justo lo que no se banca acá.
        d.execute(f"TRUNCATE {lista} RESTART IDENTITY")
    print(f"destino vaciado: {len(tablas)} tablas, secuencias reiniciadas")
    return 0


def cmd_copiar(args) -> int:
    _guarda_de_escritura("copiar")
    t0 = time.time()
    origen = abrir_origen(args.origen)
    print(f"origen: {args.origen}")
    for k, v in huella_origen(origen, args.origen).items():
        print(f"   {k}: {v}")
    _avisar_espacio(args.origen)

    # 1. El preflight es PRECONDICIÓN y se re-corre acá, sobre esta base y en esta
    #    corrida. No se acepta la prueba de un preflight anterior: un papel se
    #    copia de otra corrida, una lectura de la base no.
    with abrir_destino(args.destino, autocommit=True) as d:
        cur = vc.CursorPg(d)
        hallazgos = preflight(origen, cur)
        if hallazgos:
            origen.close()
            raise NoSePuedeCopiar(
                f"el preflight encontró {len(hallazgos)} hallazgo(s); no se copia. "
                f"Corré `preflight` para verlos.")
        tablas_o, cols_o = vc.catalogo_origen(vc.CursorSqlite(origen))
        orden, self_loops = orden_de_copia(tablas_o, _fks_del_destino(cur))
        con_datos = destino_esta_vacio(cur, orden)
    if con_datos:
        origen.close()
        raise NoSePuedeCopiar(
            f"el destino NO está vacío: {con_datos[:5]}"
            f"{'…' if len(con_datos) > 5 else ''}. Copiar encima duplicaría filas. "
            f"Corré `preparar-destino` si querés reintentar.")
    print(f"orden de copia: {len(orden)} tablas"
          + (f" · auto-referencias en 2 pasadas: {self_loops}" if self_loops else ""))

    # 2. La copia. Conexión PROPIA, recién abierta, `autocommit=False`, y el commit
    #    va EXPLÍCITO. Nunca `with destino.transaction()`: si algo ya abrió una
    #    transacción en esta conexión, ese bloque se degrada a SAVEPOINT, sale con
    #    RELEASE y al cerrar la conexión el servidor rollbackea TODO — reportando
    #    éxito, con los cuatro niveles en verde, sobre una base vacía.
    destino = abrir_destino(args.destino, autocommit=False)
    tiempos: Dict[str, float] = {}
    total = 0
    try:
        for tabla in orden:
            en_null = tuple(c for t, c in self_loops if t == tabla)
            t1 = time.time()
            n = copiar_tabla(origen, destino, tabla, cols_o[tabla], en_null,
                             avisar=lambda t, k: print(f"   … {t}: {k:,} filas"))
            tiempos[tabla] = time.time() - t1
            total += n
            if n:
                print(f"   {tabla}: {n:,} filas en {tiempos[tabla]:.1f}s")
        n2 = segunda_pasada(origen, destino, self_loops)
        if n2:
            print(f"   segunda pasada (auto-referencias): {n2:,} filas")
        hechos = correr_setval(destino)
        print(f"   setval en {len(hechos)} secuencias")
        destino.commit()                      # ⬅️ EXPLÍCITO. Ver el punto 2 de arriba.
    except Exception:
        # 🔴 El rollback va en su propio `try`, y el motivo apareció corriendo esto
        # contra Supabase: si la copia se corta en medio de un COPY, el `ROLLBACK`
        # falla con "another command is already in progress" **y esa excepción pisa
        # a la original**. O sea que el operador ve el error de la limpieza y no la
        # CAUSA — que es exactamente el modo de falla que este proyecto persigue.
        # Cerrar la conexión ya hace que el servidor rollbackee todo igual.
        try:
            destino.rollback()
        except Exception as limpieza:
            print(f"   (y el rollback tampoco pudo: {type(limpieza).__name__}: "
                  f"{limpieza}. El servidor rollbackea igual al cerrar.)")
        raise
    finally:
        destino.close()
        origen.close()
    print(f"\ncopiado: {total:,} filas en {time.time() - t0:.1f}s")

    # 3. La verificación, en una conexión NUEVA abierta DESPUÉS del commit. Sobre
    #    la misma conexión uno ve sus propias escrituras: eso prueba que la
    #    transacción existe, no que los datos quedaron.
    origen2 = abrir_origen(args.origen)
    try:
        with abrir_destino(args.destino, autocommit=True) as d2:
            cur2 = vc.CursorPg(d2)
            r = vc.comparar(vc.CursorSqlite(origen2), cur2, vc.esquema_pg(cur2))
    finally:
        origen2.close()
    print(f"verificación: {r['tablas_comparadas']}/{r['tablas_en_el_origen']} tablas "
          f"comparadas, {len(r['hallazgos'])} hallazgos")
    if r["hallazgos"]:
        for h in r["hallazgos"][:20]:
            print(f"   🔴 nivel {h['nivel']}: {h}")
        return 1
    print("✅ los cuatro niveles en CERO hallazgos")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--origen", default=os.environ.get("DB_PATH", "trading.db"),
                    help="la SQLite a copiar (se abre SÓLO LECTURA)")
    ap.add_argument("--destino", default=os.environ.get("PG_DSN_COPIA"),
                    help="DSN del Postgres destino")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nombre, fn in (("aplicar-esquema", cmd_aplicar_esquema),
                       ("preflight", cmd_preflight),
                       ("preparar-destino", cmd_preparar_destino),
                       ("copiar", cmd_copiar)):
        sub.add_parser(nombre).set_defaults(fn=fn)
    args = ap.parse_args(argv)
    if not args.destino:
        print("falta --destino (o PG_DSN_COPIA)", file=sys.stderr)
        return 2
    try:
        return args.fn(args)
    except NoSePuedeCopiar as e:
        print(f"\n🔴 {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())