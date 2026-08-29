"""Verifica que una copia SQLite→Postgres no haya cambiado la plata de nadie.

SE ESCRIBE ANTES QUE EL COPIADOR, y el orden no es negociable: escrito el copiador
primero, uno mira lo que produjo y lo acepta, porque no tiene contra qué compararlo.

**Contar filas NO alcanza.** Un número mal convertido —un costo en pesos leído como
dólares, un `numeric` redondeado— deja exactamente la misma cantidad de filas. Lo
que hay que comparar es la PLATA, por usuario.

Cuatro niveles, y hacen falta los cuatro:

  NIVEL 0  vaciar `raw_json` no tocó nada más. El 92% de las filas es andamio de
           import y se vacía ANTES de copiar, con UPDATE y **nunca DELETE** (borrar
           la fila cascadea y se lleva su movimiento real del ledger). Ese UPDATE
           corre sobre la base REAL: es la primera oportunidad de perder plata.
  NIVEL 1  fila por fila, exacto. Atrapa una columna que ningún total suma.
  NIVEL 2  la plata por usuario. Es el nivel que un humano puede leer y creer.
  NIVEL 3  las secuencias. Sin `setval()` el próximo alta choca contra un id que ya
           existe.

DOS DECISIONES QUE SOSTIENEN TODO LO DEMÁS:

1. **Los totales se suman en Python y como `Decimal`, no con `SUM()` en SQL.** La
   suma de floats no es asociativa: dos motores que sumen las MISMAS filas en
   distinto orden pueden dar resultados distintos en el último bit. Eso obligaría a
   inventar una tolerancia, y una tolerancia es exactamente donde se esconde un
   error de conversión. Sumando en `Decimal` el resultado es exacto y no depende
   del orden, así que se puede comparar **sin tolerancia** — que es lo correcto:
   estamos copiando las MISMAS filas, no recalculando nada.

2. **El digest de cada tabla es INDEPENDIENTE DEL ORDEN**: se hashea cada fila y se
   SUMAN los hashes. Así no hace falta un `ORDER BY` que se comporte igual en los
   dos motores — y no se comportan igual: con NULLs, SQLite los ordena primero y
   Postgres al final. Un `ORDER BY` mal elegido habría hecho fallar tablas sanas.
   Se suman (y no se hace XOR) para que dos filas idénticas no se cancelen.

⚠️ **LA TRAMPA, y es donde un bug haría que todo parezca bien:** los dos motores
devuelven TIPOS distintos para la misma columna. `sqlite3` tiene tipado dinámico y
te devuelve el `int` 1500 de una columna declarada REAL; psycopg te devuelve el
`float` 1500.0. Si no se normaliza, TODO da distinto, la verificación se llena de
ruido y uno aprende a ignorarla — que es peor que no tenerla. Por eso la
normalización (`canon`) está aislada, tiene sus propios tests, y **falla fuerte**
cuando encuentra algo que no sabe normalizar en vez de adivinar.
"""
from __future__ import annotations

import hashlib
import sqlite3
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

NULO = "\x00NULO"          # sentinela: distingue el NULL del texto "None"
_MOD = 1 << 128            # los hashes se suman módulo esto


class ValorRaro(Exception):
    """Un valor que la normalización no sabe convertir al tipo declarado.

    Se levanta en vez de coercionar: un texto adentro de una columna numérica es
    un hallazgo, no algo para redondear en silencio.
    """


class FotoIlegible(Exception):
    """El NIVEL 0 no pudo fotografiar una tabla.

    Levanta en vez de anotar el error como si fuera un valor. Guardarlo como dato
    lo vuelve comparable, y dos errores iguales comparan iguales: así el único
    nivel que vigila el paso irreversible del día devolvía "sin hallazgos" sin
    haber leído nada.
    """


class OrigenIlegible(Exception):
    """No se pudo leer del ORIGEN la lista de qué hay que comparar.

    Levanta en vez de seguir con lo que haya: sin esa lista la verificación sólo
    puede mirar lo que el destino ya tiene, que es exactamente la ceguera que
    todo este módulo existe para evitar. Una verificación que no sabe qué tiene
    que comparar no puede decir "ok".
    """


# ── La normalización ─────────────────────────────────────────────────────────

def canon(valor: Any, tipo: str) -> str:
    """Un valor → su forma canónica en texto, según el tipo DECLARADO en Postgres.

    El tipo declarado manda, y no el tipo que devolvió el driver: es lo único que
    los dos motores tienen en común. `positions.invested` es `double precision`
    aunque SQLite haya guardado ahí un entero.
    """
    if valor is None:
        return NULO
    if tipo in ("bigint", "integer", "smallint"):
        if isinstance(valor, bool):                 # bool ANTES que int: bool es int
            return "1" if valor else "0"
        if isinstance(valor, int):
            return str(valor)
        if isinstance(valor, (float, Decimal)):
            d = _a_decimal(valor)
            if d != d.to_integral_value():
                raise ValorRaro(f"{valor!r} tiene decimales en una columna {tipo}")
            return str(int(d))
        raise ValorRaro(f"{type(valor).__name__} {valor!r} en una columna {tipo}")
    if tipo in ("double precision", "real", "numeric"):
        return _num(valor)
    if tipo in ("text", "character varying", "date", "timestamp without time zone"):
        if isinstance(valor, bytes):
            return valor.decode("utf-8", "replace")
        return str(valor)
    raise ValorRaro(f"tipo declarado desconocido: {tipo!r}")


def _a_decimal(valor: Any) -> Decimal:
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, float):
        # repr() de un float es la representación decimal MÁS CORTA que vuelve al
        # mismo float. Pasar por str(float) directo a Decimal es equivalente en
        # Python 3, pero repr deja explícito que se busca ida y vuelta exacta.
        return Decimal(repr(valor))
    if isinstance(valor, int):
        return Decimal(valor)
    raise ValorRaro(f"{type(valor).__name__} {valor!r} donde iba un número")


def _num(valor: Any) -> str:
    """Número → texto canónico. Mismo valor ⇒ mismo texto, venga como venga.

    `1500` (int de SQLite), `1500.0` (float de psycopg) y `Decimal('1500.00')` dan
    los tres `'1500'`. Un `Decimal('1500.01')` da `'1500.01'` y NO coincide — que
    es justo lo que tiene que pasar: los tipos distintos no pueden tapar valores
    distintos.
    """
    if isinstance(valor, str):
        raise ValorRaro(f"texto {valor!r} en una columna numérica")
    d = _a_decimal(valor)
    if d.is_nan():
        return "NaN"
    if d.is_infinite():
        return "Inf" if d > 0 else "-Inf"
    if d == 0:
        return "0"                                   # unifica 0, 0.0 y -0.0
    try:
        return format(d.normalize(), "f")            # sin exponente, sin ceros de cola
    except (InvalidOperation, ValueError):
        return str(d)


def hash_fila(valores: List[Any], tipos: List[str]) -> int:
    """Una fila → un entero. El separador va adentro del hash de cada campo para
    que `('ab','c')` y `('a','bc')` no colisionen."""
    h = hashlib.md5()
    for v, t in zip(valores, tipos):
        s = canon(v, t)
        h.update(str(len(s)).encode())
        h.update(b"\x1f")
        h.update(s.encode("utf-8"))
    return int(h.hexdigest(), 16)


# ── Leer el esquema: de Postgres, que es el que tiene tipos de verdad ─────────

def esquema_pg(cur) -> Dict[str, List[Tuple[str, str]]]:
    """{tabla: [(columna, tipo_declarado)]} del esquema activo, en orden.

    ⚠️ SÓLO TABLAS BASE, y es la simetría exacta del `type='table'` que ya hace
    `tablas_sqlite()`. `information_schema.columns` lista TAMBIÉN las vistas, y desde
    que existe `snapshots_medibles` —la primera vista del repo— este lado devolvía 61
    relaciones contra las 60 del origen. El preflight compara los dos conjuntos y
    aborta la copia con `NoSePuedeCopiar` ante UN solo hallazgo: la vista sola
    bloqueaba el pasaje entero.

    Medido contra un Postgres real (PG 16) con el esquema de la rama aplicado:
    sin el filtro `esquema_pg()` devuelve 61 y `tablas_sqlite()` 60; con el filtro,
    60 y 60. Una vista no se copia —se recrea desde el esquema— así que no tiene
    nada que hacer en una comparación origen-vs-destino de DATOS.
    """
    filas = cur.execute("""
        SELECT c.table_name, c.column_name, c.data_type
          FROM information_schema.columns c
          JOIN information_schema.tables t
            ON t.table_schema = c.table_schema
           AND t.table_name = c.table_name
         WHERE c.table_schema = current_schema()
           AND t.table_type = 'BASE TABLE'
         ORDER BY c.table_name, c.ordinal_position
    """).fetchall()
    out: Dict[str, List[Tuple[str, str]]] = {}
    for t, c, d in filas:
        out.setdefault(t, []).append((c, d))
    return out


def columnas_sqlite(conn: sqlite3.Connection) -> Dict[str, List[str]]:
    """{tabla: [columnas]} del ORIGEN, leído de SQLite.

    Existe para que la verificación no tenga que preguntarle al destino qué
    columnas hay que comparar — que era el bug. Ver el NIVEL 1-b.
    """
    out: Dict[str, List[str]] = {}
    for t in tablas_sqlite(conn):
        out[t] = [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")').fetchall()]
    return out


def tablas_sqlite(conn: sqlite3.Connection) -> set:
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'").fetchall()}


def catalogo_origen(cur) -> Tuple[set, Dict[str, List[str]]]:
    """(tablas, {tabla: [columnas]}) del ORIGEN. LO LEE `comparar()` SOLA.

    🔴 **Por qué esto no es un parámetro, y es el punto entero de esta función.**
    Antes lo era —`tablas_origen=None`, `cols_origen=None`— con un docstring que
    decía "pasalos SIEMPRE". Eso es una ADVERTENCIA, no un mecanismo: el que no
    los pasaba se saltaba el chequeo **en silencio** y la verificación volvía a
    devolver "ok" con tablas sin copiar. La red existía y quedaba sin poner, que
    es la forma exacta de los últimos errores de este proyecto.

    Sacando el parámetro, olvidarlo no es posible: no hay nada que pasar. Y tapa
    de paso el error de un piso más arriba —**mirar desde la fuente equivocada**—
    porque la lista ya no puede venir del destino ni de una variable de hace diez
    líneas: sale del cursor del ORIGEN que la comparación está usando.

    Si el origen no se puede leer, LEVANTA. Nunca devuelve una lista a medias:
    una lista corta se ve igual que una completa, y comparar de menos es
    justamente el modo de falla que da verde con plata perdida.
    """
    try:
        tablas = tablas_sqlite(cur)
        cols = columnas_sqlite(cur)
    except Exception as ex:
        raise OrigenIlegible(
            f"no se pudo leer el catálogo del ORIGEN ({type(ex).__name__}: {ex}). "
            f"`comparar()` espera que el origen sea la base SQLite que se está "
            f"copiando; sin su lista de tablas y columnas la verificación sería "
            f"ciega a todo lo que no viajó.") from ex
    if not tablas:
        raise OrigenIlegible(
            "el ORIGEN no tiene ninguna tabla. Comparar contra una base vacía da "
            "'sin hallazgos' sin haber mirado nada: es el falso verde más caro "
            "posible.")
    return tablas, cols


# ── NIVEL 1: fila por fila ───────────────────────────────────────────────────

def digest_tabla(cur, tabla: str, cols: List[Tuple[str, str]],
                 excluir: Optional[set] = None) -> Tuple[int, int, List[str]]:
    """(cantidad de filas, suma de hashes, columnas usadas).

    `excluir` saca columnas del digest — lo usa el NIVEL 0 para comparar
    `import_raw_rows` sin `raw_json`, que es justo la columna que se vacía a
    propósito.
    """
    usar = [(c, t) for (c, t) in cols if not (excluir and c in excluir)]
    nombres = [c for c, _ in usar]
    tipos = [t for _, t in usar]
    lista = ", ".join(f'"{c}"' for c in nombres)
    total = 0
    n = 0
    for fila in cur.execute(f'SELECT {lista} FROM "{tabla}"'):
        total = (total + hash_fila(list(fila), tipos)) % _MOD
        n += 1
    return n, total, nombres


# ── NIVEL 2: la plata, por usuario ───────────────────────────────────────────

# Se leen los valores GUARDADOS, no valuados a mercado: la valuación depende de
# precios y de FX, cambia cada minuto, y no es lo que puede romper un copiador.
CONSULTAS_PLATA = {
    "invertido": ("SELECT user_id, invested FROM positions WHERE is_cash = 0", "invested"),
    "efectivo":  ("SELECT user_id, invested FROM positions WHERE is_cash = 1", "invested"),
    "ganancia":  ("SELECT user_id, pnl_usd  FROM operations", "pnl_usd"),
    "comisiones": ("SELECT user_id, commissions FROM positions", "commissions"),
}


def plata_por_usuario(cur) -> Dict[int, Dict[str, Decimal]]:
    """{uid: {concepto: total}} sumado en Decimal.

    POR USUARIO y no en total, que es el punto: un total global netea dos errores
    opuestos —un usuario ×1400 para arriba y otro para abajo— y da bien. A este
    proyecto ya le pasó con el FX.
    """
    out: Dict[int, Dict[str, Decimal]] = {}
    for concepto, (sql, _col) in CONSULTAS_PLATA.items():
        for uid, valor in cur.execute(sql):
            if uid is None:
                uid = -1                              # filas huérfanas: su propio cajón
            d = out.setdefault(int(uid), {})
            d[concepto] = d.get(concepto, Decimal(0)) + (
                Decimal(0) if valor is None else _a_decimal(valor))
    return out


def nominales_por_usuario(cur) -> Dict[Tuple[int, str, str], Decimal]:
    """{(uid, broker, activo): cantidad}. Atrapa un nominal mal convertido que la
    suma de plata no ve porque el costo quedó bien."""
    out: Dict[Tuple[int, str, str], Decimal] = {}
    for uid, broker, activo, qty in cur.execute(
            "SELECT user_id, broker, asset, quantity FROM positions WHERE is_cash = 0"):
        k = (int(uid or -1), str(broker), str(activo))
        out[k] = out.get(k, Decimal(0)) + (Decimal(0) if qty is None else _a_decimal(qty))
    return out


# ── NIVEL 3: las secuencias ──────────────────────────────────────────────────

def secuencias_atrasadas(cur) -> List[Dict[str, Any]]:
    """Tablas cuya secuencia quedaría dando un id que YA existe.

    Las PK son `GENERATED BY DEFAULT` justamente para poder insertar cada fila con
    su id original; el precio es que después hay que correr `setval()` en cada una.
    """
    malas = []
    filas = cur.execute("""
        SELECT c.relname AS tabla, a.attname AS col,
               pg_get_serial_sequence(quote_ident(c.relname), a.attname) AS sec
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
          JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0
         WHERE n.nspname = current_schema() AND c.relkind = 'r'
           AND a.attidentity IN ('a', 'd')
         ORDER BY c.relname
    """).fetchall()
    for tabla, col, sec in filas:
        if not sec:
            # Misma familia que el fail-open del NIVEL 0: saltear en silencio una
            # columna identity SIN secuencia es decir "todo bien" sobre algo que
            # ni se miró. Si esto aparece, el próximo alta de esa tabla no tiene
            # de dónde sacar el id.
            malas.append({"tabla": tabla, "columna": col, "secuencia": None,
                          "proximo_id": None, "max_id": None,
                          "sin_secuencia": True})
            continue
        maximo = cur.execute(f'SELECT MAX("{col}") FROM "{tabla}"').fetchone()[0]
        if maximo is None:
            continue
        ultimo = cur.execute(f"SELECT last_value, is_called FROM {sec}").fetchone()
        last_value, is_called = ultimo[0], ultimo[1]
        proximo = last_value + 1 if is_called else last_value
        if proximo <= maximo:
            malas.append({"tabla": tabla, "columna": col, "secuencia": sec,
                          "proximo_id": proximo, "max_id": maximo})
    return malas


# ── Los adaptadores: un cursor uniforme sobre los dos motores ────────────────

class CursorSqlite:
    def __init__(self, conn):
        self._c = conn

    def execute(self, sql, params=()):
        return self._c.execute(sql, params)


class CursorPg:
    """psycopg no deja re-ejecutar sobre el mismo cursor mientras se itera, así
    que cada execute() abre el suyo. Son consultas de lectura y de a una."""

    def __init__(self, conn):
        self._c = conn

    def execute(self, sql, params=()):
        cur = self._c.cursor()
        cur.execute(sql, params)
        return cur


# ── El informe ───────────────────────────────────────────────────────────────

def comparar(cur_origen, cur_destino, esquema: Dict[str, List[Tuple[str, str]]],
             *, saltear: Optional[set] = None,
             revisar_secuencias: bool = True) -> Dict[str, Any]:
    """Compara origen (SQLite) contra destino (Postgres). Devuelve los HALLAZGOS.

    Lista vacía = las dos bases dicen lo mismo. Nunca devuelve "está todo bien"
    sin haber mirado: si una tabla no se pudo leer, eso es un hallazgo.

    **QUÉ SE COMPARA LO DECIDE EL ORIGEN, y no hay forma de pedir otra cosa.**
    La lista de tablas y de columnas se lee acá adentro con `catalogo_origen()`,
    del mismo cursor del origen que se está comparando. No es un parámetro a
    propósito: cuando lo era, omitirlo apagaba el chequeo en silencio. Ver el
    docstring de `catalogo_origen`.

    `esquema` sigue viniendo del DESTINO (`esquema_pg`) porque es lo único que
    tiene los TIPOS declarados, que es lo que la normalización necesita. La
    división es la que importa: **el destino aporta los tipos, el origen aporta
    la lista de qué mirar.** Preguntarle al destino qué verificar es preguntarle
    al sospechoso.

    `revisar_secuencias=False` apaga el NIVEL 3, que es propio de Postgres. Los
    tests lo usan para poder correr las mismas comparaciones SQLite-contra-SQLite
    y así probar la lógica de detección sin depender de que haya un Postgres. Su
    default es `True`: apagarlo es un acto explícito, no un olvido.
    """
    hallazgos: List[Dict[str, Any]] = []
    saltear = saltear or set()
    tablas_origen, cols_origen = catalogo_origen(cur_origen)

    # ── NIVEL 1-a: ¿ESTÁN TODAS LAS TABLAS? ─────────────────────────────────
    # 🔴 Acá había un agujero estructural, y era grave: el `esquema` sale del
    # catálogo del DESTINO (`esquema_pg`), y todo el nivel 1 itera sobre él. O sea
    # que **una tabla que existe en el ORIGEN y no en el destino nunca se compara**:
    # no aparece en el bucle, no genera hallazgo, y la verificación devuelve
    # "ok: sin hallazgos" con dos tablas de datos que no viajaron.
    #
    # No es hipotético. Producción tiene **60 tablas** y `schema_pg.sql` tiene
    # **58**: faltan `fci_catalog` y `fci_prices`, que las crea `pricing/fci.py`
    # EN CALIENTE y por eso nunca entraron al esquema. Son los precios de los FCI:
    # sin ellas, esas posiciones se valúan mal.
    #
    # La lección es la de siempre en este proyecto: **preguntarle al destino qué
    # hay que verificar es preguntarle al sospechoso.** La lista de qué comparar
    # tiene que salir del ORIGEN.
    #
    # ⚠️ Y el arreglo tuvo DOS etapas, porque la primera se quedó a mitad de
    # camino: la lista salía del origen pero **por un parámetro opcional**, así
    # que el que no lo pasaba volvía a tener la ceguera entera, en silencio.
    # Ahora no hay parámetro: `catalogo_origen()` lo lee arriba, siempre.
    faltan = sorted(t for t in tablas_origen if t not in esquema and t not in saltear)
    for t in faltan:
        hallazgos.append({
            "nivel": 1, "tabla": t,
            "que": "la tabla existe en el ORIGEN y NO en el destino: no se copió "
                   "y el resto de la verificación es ciega a ella"})
    sobran = sorted(t for t in esquema if t not in tablas_origen and t not in saltear)
    for t in sobran:
        hallazgos.append({
            "nivel": 1, "tabla": t,
            "que": "la tabla existe en el destino y NO en el origen"})
    # Ya reportadas: sacarlas del bucle de abajo para no decir dos veces lo
    # mismo (la de más daría además "no se pudo leer el ORIGEN", que es la
    # misma noticia con otras palabras y ensucia el informe).
    saltear = set(saltear) | set(sobran)

    # ── NIVEL 1-b: ¿ESTÁN TODAS LAS COLUMNAS? ───────────────────────────────
    # 🔴 El MISMO agujero que el de arriba, un piso más abajo, y por poco se
    # queda sin tapar. La lista de columnas de cada tabla también sale del
    # catálogo del DESTINO, y `digest_tabla` usa esa lista para leer LAS DOS
    # bases. O sea que una columna que existe en producción y no en
    # `schema_pg.sql` **no se copia, no se lee, y no se reporta**: el informe
    # dice "sin hallazgos" con una columna entera de datos perdida.
    #
    # Tapar sólo el nivel de las tablas habría dejado exactamente el mismo bug
    # esperando un piso más abajo. La regla es la misma y vale en los dos
    # niveles: **la lista de qué comparar sale del ORIGEN.**
    for tabla in sorted(set(esquema) & set(cols_origen)):
        if tabla in saltear:
            continue
        en_destino = {c for c, _t in esquema[tabla]}
        en_origen = set(cols_origen[tabla])
        faltan_c = sorted(en_origen - en_destino)
        sobran_c = sorted(en_destino - en_origen)
        if faltan_c:
            hallazgos.append({
                "nivel": 1, "tabla": tabla,
                "que": f"columnas que están en el ORIGEN y no en el destino: "
                       f"{faltan_c}. No se copiaron y el digest es ciego a ellas"})
        if sobran_c:
            hallazgos.append({
                "nivel": 1, "tabla": tabla,
                "que": f"columnas que están en el destino y no en el origen: "
                       f"{sobran_c}"})

    # NIVEL 1
    comparadas = 0
    for tabla, cols in sorted(esquema.items()):
        if tabla in saltear:
            continue
        try:
            n_o, h_o, _ = digest_tabla(cur_origen, tabla, cols)
        except Exception as ex:
            hallazgos.append({"nivel": 1, "tabla": tabla,
                              "que": f"no se pudo leer el ORIGEN: {type(ex).__name__}: {ex}"})
            continue
        try:
            n_d, h_d, _ = digest_tabla(cur_destino, tabla, cols)
        except Exception as ex:
            hallazgos.append({"nivel": 1, "tabla": tabla,
                              "que": f"no se pudo leer el DESTINO: {type(ex).__name__}: {ex}"})
            continue
        comparadas += 1              # recién acá: las dos lecturas salieron bien
        if n_o != n_d:
            hallazgos.append({"nivel": 1, "tabla": tabla, "que": "cantidad de filas",
                              "origen": n_o, "destino": n_d})
        elif h_o != h_d:
            hallazgos.append({"nivel": 1, "tabla": tabla,
                              "que": "mismas filas pero contenido distinto",
                              "filas": n_o})

    # NIVEL 2
    p_o = plata_por_usuario(cur_origen)
    p_d = plata_por_usuario(cur_destino)
    for uid in sorted(set(p_o) | set(p_d)):
        a, b = p_o.get(uid, {}), p_d.get(uid, {})
        for concepto in sorted(set(a) | set(b)):
            va, vb = a.get(concepto, Decimal(0)), b.get(concepto, Decimal(0))
            if va != vb:
                # En forma canónica y no str(Decimal): la misma diferencia salía
                # como "-1000.00" para un usuario y "1000.0" para otro, según los
                # decimales que arrastrara cada suma. Ilegible al lado del otro.
                hallazgos.append({"nivel": 2, "uid": uid, "que": concepto,
                                  "origen": _num(va), "destino": _num(vb),
                                  "diferencia": _num(vb - va)})
    n_o, n_d = nominales_por_usuario(cur_origen), nominales_por_usuario(cur_destino)
    for k in sorted(set(n_o) | set(n_d)):
        va, vb = n_o.get(k, Decimal(0)), n_d.get(k, Decimal(0))
        if va != vb:
            hallazgos.append({"nivel": 2, "uid": k[0], "que": f"nominales {k[1]}/{k[2]}",
                              "origen": _num(va), "destino": _num(vb),
                              "diferencia": _num(vb - va)})

    # NIVEL 3
    for s in (secuencias_atrasadas(cur_destino) if revisar_secuencias else []):
        hallazgos.append({"nivel": 3, "tabla": s["tabla"],
                          "que": "la secuencia daría un id que ya existe "
                                 "(¿falta el setval?)",
                          "proximo_id": s["proximo_id"], "max_id": s["max_id"]})
    # `tablas_comparadas` cuenta las que de verdad se digestearon, no las que se
    # pensaba mirar. Misma familia que el fail-open: un número que dice "60" cuando
    # se leyeron 58 es la forma en que un informe verde tapa una tabla sin revisar.
    return {"hallazgos": hallazgos, "ok": not hallazgos,
            "tablas_comparadas": comparadas,
            "tablas_en_el_origen": len(tablas_origen)}


# ── NIVEL 0: el vaciado de raw_json ──────────────────────────────────────────

def foto_para_vaciado(cur) -> Dict[str, Any]:
    """Foto de la base ANTES/DESPUÉS de vaciar `raw_json`.

    Todo tiene que quedar idéntico salvo el contenido de esa única columna. Por eso
    `import_raw_rows` se digestea SIN ella: si el digest cambia, se tocó algo más.

    🔴 **ACÁ HABÍA DOS AGUJEROS Y LOS DOS ERAN LA MISMA FAMILIA QUE EL DE
    `comparar()` — un piso más abajo, en el nivel que vigila el ÚNICO paso
    irreversible del día.**

    1. **Era FAIL-OPEN.** Una tabla que no se podía leer se guardaba como
       `("ERROR", mensaje)` *adentro* del `try`, y `comparar_vaciado` sólo denuncia
       cuando los valores DIFIEREN. Dos ERROR idénticos comparan iguales, así que
       podía mirar 58 de 60 tablas —o ninguna— e imprimir "sin hallazgos". Medido:
       con las dos tablas ilegibles devolvía `[]`. Ahora **levanta**.
    2. **La lista de tablas salía del DESTINO** (el `esquema` que recibía por
       parámetro), igual que el bug de `comparar()`. Pero las dos fotos son del
       ORIGEN: preguntarle al destino qué fotografiar del origen es, otra vez,
       preguntarle al sospechoso. Ahora la lista sale de `catalogo_origen()` y el
       parámetro **no existe**, así que no se puede pasar la lista equivocada.

    **Y los tipos van todos como `text` a propósito.** Este nivel compara SQLite
    contra SQLite: no necesita que el tipo sea *correcto*, necesita que sea *el
    mismo en las dos fotos*. Con `text` eso está garantizado y desaparece la única
    forma en que este nivel podría levantar por un dato legítimo. Un cambio real
    igual se ve: `str()` distingue `1500` de `1500.0`.
    """
    tablas, cols_origen = catalogo_origen(cur)
    foto: Dict[str, Any] = {}
    for tabla in sorted(tablas):
        cols = [(c, "text") for c in cols_origen[tabla]]
        excluir = {"raw_json"} if tabla == "import_raw_rows" else None
        try:
            n, h, _ = digest_tabla(cur, tabla, cols, excluir=excluir)
        except Exception as ex:
            raise FotoIlegible(
                f"no se pudo fotografiar la tabla {tabla!r} "
                f"({type(ex).__name__}: {ex}). Este nivel vigila el paso "
                f"irreversible del pasaje: una tabla que no se puede leer NO puede "
                f"quedar como 'sin hallazgos'.") from ex
        foto[tabla] = (n, h)
    return foto


def comparar_vaciado(antes: Dict[str, Any], despues: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Hallazgos del NIVEL 0. Vacío = el UPDATE tocó sólo `raw_json`."""
    hallazgos = []
    for tabla in sorted(set(antes) | set(despues)):
        a, d = antes.get(tabla), despues.get(tabla)
        if a is None or d is None:
            hallazgos.append({"nivel": 0, "tabla": tabla,
                              "que": "la tabla apareció o desapareció"})
            continue
        if a[0] != d[0]:
            hallazgos.append({
                "nivel": 0, "tabla": tabla,
                "que": "cambió la cantidad de filas: el vaciado tiene que ser UPDATE, "
                       "NUNCA DELETE (borrar la fila cascadea y se lleva su "
                       "movimiento del ledger)",
                "antes": a[0], "despues": d[0]})
        elif a[1] != d[1]:
            hallazgos.append({"nivel": 0, "tabla": tabla,
                              "que": "el vaciado tocó columnas que no eran raw_json",
                              "filas": a[0]})
    return hallazgos
