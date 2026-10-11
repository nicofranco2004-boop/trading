"""Renombrar un broker: el nombre vive también ADENTRO de lo guardado.

Las tablas linkean al broker por NOMBRE (ver `NAME_KEYED_TABLES` en main.py) y el
renombre reescribe esa columna. Pero el nombre también está guardado adentro de
textos JSON, y ahí no lo cambiaba nadie (reproducido el 2026-10-09):
  · la RECETA de borrado de cada cosa cargada a mano (`undo_meta_json`): a qué caja
    devolver la plata (`cash_broker`), en qué broker re-crear el lote (`lot.broker`),
    de qué broker salió (`broker`) — y la receta del lote vendido, guardada como
    texto ADENTRO de la de la venta (`lot.undo_meta`);
  · las secciones de bonos ARCHIVADAS (filas enteras de positions, con su receta);
  · el registro de BORRADOS (`deleted_ops_journal`): la fila borrada, la caja, los
    eventos que corrigen las fotos, los pares de brokers;
  · el precio de cada fondo que fijó una foto de tenencia;
  · la plantilla de columnas del importador (`import_mappings`): el broker fijo al
    que va todo el archivo. Con el viejo, importar con la plantilla volvía a crear un
    broker con ese nombre.
Con el nombre viejo ahí, borrar después de renombrar mandaba la plata a una caja
nueva a nombre de un broker que ya no existe (invisible), re-creaba el lote bajo ese
nombre, o frenaba con 409 para siempre.

Por qué no alcanza un `REPLACE` sobre el texto: `json.dumps` guarda "·" y "ñ" como
`\\u00b7` / `\\u00f1`, y lo anidado va escapado OTRA vez. Hay que abrir el JSON.

La regla: se cambia todo valor guardado bajo una clave de broker (la clave dice
"broker", o es un par de brokers) que sea EXACTAMENTE un nombre viejo — como texto,
como elemento de una lista o como clave de un diccionario (`cash_by_broker`). Nunca
se toca un texto libre que sólo lo CONTENGA. Una excepción, la plantilla del
importador, que la escribe el cliente: ahí el nombre viejo también vale con otras
mayúsculas o espacios al borde, y sólo se mira su parte `defaults` (ver
COMO_EL_IMPORTADOR y SOLO_BAJO). `test_renombre_broker_recetas.py`
revisa toda la cuenta después de renombrar: si una receta nueva guarda el nombre
bajo otra clave, falla y dice dónde.
"""
import json
from typing import Dict, Optional, Tuple

# Claves que guardan nombres de broker aunque no digan "broker": el par padre↔"· USD"
# del registro de una edición de posición y del borrado del historial de un activo, y
# la cuenta en pesos donde un dividendo de la bandeja cobró su comisión.
_CLAVES_DE_BROKER_SIN_LA_PALABRA = frozenset({"pair", "pairs", "cuenta_pesos"})

# Columnas de texto JSON con nombres de broker adentro: (tabla, columna). Las que no
# tienen user_id se acotan por el import del usuario (`batch_id`).
COLUMNAS_JSON = (
    ("operations", "undo_meta_json"),
    ("positions", "undo_meta_json"),
    ("archived_positions", "payload"),
    ("deleted_ops_journal", "payload_json"),
    # El precio por cuotaparte que fijó una foto de tenencia (Balanz) para cada fondo,
    # con su broker: con el nombre viejo, revertir esa foto no limpiaba el precio y
    # re-aplicar las fotos no lo encontraba (visto en la copia de prod 16/08).
    ("import_batches", "fund_price_overrides"),
    # Lo que decidió una foto de tenencia (qué redujo o sacó, por broker). Hoy sólo se
    # usa para medir; va igual, para que no quede un nombre viejo esperando un lector.
    ("import_batches", "override_info"),
    # El dividendo confirmado en la bandeja que un import reemplazó (la fila entera,
    # con su receta): vuelve si ese import se revierte — a la cuenta que diga acá.
    ("dividendos_reemplazados", "op_json"),
    # La plantilla de columnas del importador ("Guardar mapeo actual"): el broker fijo
    # al que van todas las filas del archivo. Con el nombre viejo, importar con la
    # plantilla después de renombrar volvía a crear un broker con ese nombre y metía
    # todo el archivo ahí (medido el 2026-10-10: dos brokers donde había uno). Sólo lo
    # de `defaults`: ver SOLO_BAJO.
    ("import_mappings", "mapping_json"),
)

# Columnas donde el nombre de un broker vive SÓLO adentro de ciertas claves de primer
# nivel; el resto del JSON no se toca aunque la clave diga "broker". En la plantilla
# del importador hay dos "broker": `defaults.broker` es el broker fijo, y
# `columns.broker` es el TÍTULO de una columna del archivo de la persona ("Cuenta",
# "Agente"…), que no es un broker. Si ese título es igual al nombre del broker, la
# regla general lo cambiaba y la plantilla dejaba de servir ("La columna … no existe
# en el archivo"). Se dice qué SÍ se mira (y no qué se saltea): una parte nueva de la
# plantilla no se reescribe hasta que alguien la sume acá, y el test del renombre
# avisa si quedó un nombre viejo en ella.
SOLO_BAJO = {
    ("import_mappings", "mapping_json"): ("defaults",),
}

# Columnas cuyo JSON lo escribe el CLIENTE tal cual lo manda, y no el servidor con el
# nombre exacto del broker. Ahí el nombre viejo se busca también sin mirar mayúsculas
# ni espacios al borde (`_clave`), que es como lo toma el importador: una plantilla
# que dice "zorzal ñandú " importa al broker "Zorzal Ñandú", así que el renombre
# también la tiene que seguir (auditoría 2026-10-11: letra por letra, quedaba con el
# nombre viejo y el import volvía a crear ese broker). Desde ese día
# `plantilla_con_broker_de_hoy` lo deja bien escrito al guardar; esto cubre lo
# guardado antes. (Un límite: con DOS brokers que sólo difieren en mayúsculas,
# "Balanz" y "balanz", el importador manda todo a uno de los dos sin mirar cuál dice
# el archivo; acá el texto que es exactamente el nombre de un broker vivo no se toca.)
COMO_EL_IMPORTADOR = frozenset({("import_mappings", "mapping_json")})

# Techo de las plantillas del importador. Una real pesa unos cientos de caracteres
# (doce datos y sus títulos) y nadie junta más de un puñado. El techo existe porque
# el renombre las abre una por una DENTRO de su transacción, y en SQLite esa
# transacción frena las escrituras de todos: lo que se recorre ahí tiene que tener
# tope. Vale al guardar (main.py) y también al leer (`plantillas_al_alcance`): entre
# 2026-05-08 y 2026-10-11 se pudo guardar sin tope, y una fila enorme de entonces no
# puede trabar el renombre ni la lista (medido: 2.000 filas de 200.000 letras = 2,6 s
# con la base tomada). Una plantilla fuera de tope no se lista ni se renombra.
PLANTILLA_MAX_CARACTERES = 20_000
PLANTILLAS_MAX_POR_CUENTA = 100
# NO va `import_raw_rows.raw_json` (lo que decía el archivo): una cuenta de prod tiene
# 502.915 filas y reescribirlas trababa la base para TODOS durante decenas de
# segundos. "Editar y rehacer" lo traduce al leer (`reconstruct_csv_from_batch`).
#
# Y hay un lugar donde el nombre NO se puede reescribir: la HUELLA con que el
# importador reconoce una fila que ya importó (`import_normalized_tx.fingerprint`) es
# un hash de fecha + nombre del broker + tipo + activo + cantidad + precio. Con el
# nombre nuevo la huella de la misma fila da otra, y el próximo archivo que se
# superponga entraba ENTERO otra vez (auditoría 2026-10-10: depósitos 200.000 donde
# había 100.000). Por eso cada broker guarda sus nombres anteriores
# (`brokers.nombres_anteriores`) y el anti-duplicados prueba la huella con el nombre de
# hoy y con cada anterior (`importing.pipeline.duplicate_row_indices_by_count`).


def es_clave_de_broker(clave) -> bool:
    return isinstance(clave, str) and ("broker" in clave.lower()
                                       or clave in _CLAVES_DE_BROKER_SIN_LA_PALABRA)


def _dumps_como(original: str, valor) -> str:
    """Vuelve a escribir el JSON con el mismo estilo que tenía: los imports guardan
    con `ensure_ascii=False` (la ñ tal cual), las recetas con el default (\\u00f1)."""
    return json.dumps(valor, ensure_ascii=original.isascii())


def _en_clave_de_broker(valor, nombres: Dict[str, str]) -> Tuple[object, bool]:
    """Un valor guardado BAJO una clave de broker: el nombre mismo, una lista de
    nombres (o de pares), o un diccionario {nombre: monto}."""
    if isinstance(valor, str):
        return (nombres[valor], True) if valor in nombres else (valor, False)
    if isinstance(valor, list):
        cambio, out = False, []
        for v in valor:
            nv, c = _en_clave_de_broker(v, nombres)
            out.append(nv)
            cambio |= c
        return out, cambio
    if isinstance(valor, dict):
        cambio, out = False, {}
        for k, v in valor.items():
            nk = nombres.get(k, k) if isinstance(k, str) else k
            nv, c = _recorrer(v, nombres)
            if nk in out and _es_numero(out[nk]) and _es_numero(nv):
                # {"A": 10, "B": 5} con A→B (quedaba un "B" de un broker borrado):
                # pisar perdía los 10. Son montos por broker: se suman.
                nv = out[nk] + nv
            out[nk] = nv
            cambio |= c or nk != k
        return out, cambio
    return valor, False


def _es_numero(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _recorrer(valor, nombres: Dict[str, str]) -> Tuple[object, bool]:
    if isinstance(valor, dict):
        cambio, out = False, {}
        for k, v in valor.items():
            nv, c = (_en_clave_de_broker if es_clave_de_broker(k) else _recorrer)(v, nombres)
            out[k] = nv
            cambio |= c
        return out, cambio
    if isinstance(valor, list):
        cambio, out = False, []
        for v in valor:
            nv, c = _recorrer(v, nombres)
            out.append(nv)
            cambio |= c
        return out, cambio
    if isinstance(valor, str) and valor[:1] in "{[":
        # Una receta guardada como TEXTO adentro de otra (la del lote en la venta, la
        # de la fila en el registro de borrados, la de cada fila archivada).
        nuevo = renombrar_en_json(valor, nombres)
        return (nuevo, True) if nuevo is not None else (valor, False)
    return valor, False


def renombrar_en_json(texto: Optional[str], nombres: Dict[str, str],
                      solo_bajo: Optional[Tuple[str, ...]] = None) -> Optional[str]:
    """El texto JSON con los nombres de broker viejos cambiados por los nuevos
    (`nombres` = {viejo: nuevo}), o None si no había nada que cambiar (o no es JSON).
    Sólo se reescribe lo que cambió: el resto de la fila queda byte a byte igual.
    Con `solo_bajo`, sólo se mira adentro de esas claves de primer nivel (SOLO_BAJO)."""
    if not texto:
        return None
    try:
        valor = json.loads(texto)
    except (TypeError, ValueError):
        return None
    if solo_bajo is None:
        nuevo, cambio = _recorrer(valor, nombres)
    elif isinstance(valor, dict):
        nuevo, cambio = dict(valor), False
        for clave in solo_bajo:
            if clave in valor:
                nuevo[clave], c = _recorrer(valor[clave], nombres)
                cambio |= c
    else:
        return None
    return _dumps_como(texto, nuevo) if cambio else None


class _Anotador(dict):
    """Un {viejo: nuevo} vacío que anota cada nombre por el que se le pregunta. Con él,
    el MISMO recorrido del renombre lista los nombres de broker de un JSON sin cambiar
    nada — no una copia de las reglas que se pueda desincronizar."""

    def __init__(self):
        super().__init__()
        self.vistos = set()

    def __bool__(self):
        return True

    def __contains__(self, clave):
        self.vistos.add(clave)
        return False

    def get(self, clave, defecto=None):
        self.vistos.add(clave)
        return defecto


def nombres_en_json(texto: Optional[str]) -> set:
    """Los nombres de broker guardados en el JSON: exactamente los que
    `renombrar_en_json` cambiaría si alguno fuera el viejo."""
    anotador = _Anotador()
    renombrar_en_json(texto, anotador)
    return {n for n in anotador.vistos if isinstance(n, str) and n}


class _ComoElImportador(dict):
    """El {viejo: nuevo} del renombre que también encuentra el nombre viejo escrito
    con otras mayúsculas o con espacios al borde (COMO_EL_IMPORTADOR). Primero
    exacto. Y nunca un texto que sea EXACTAMENTE el nombre de un broker que existe
    hoy (`vivos`): "balanz" y "Balanz" pueden ser dos brokers distintos."""

    def __init__(self, nombres: Dict[str, str], vivos: set):
        super().__init__(nombres)
        self._vivos = vivos
        self._por_clave = {}
        for viejo, nuevo in nombres.items():
            self._por_clave.setdefault(_clave(viejo), nuevo)

    def _por_otra_escritura(self, nombre) -> bool:
        return (isinstance(nombre, str) and nombre not in self._vivos
                and bool(nombre.strip()) and _clave(nombre) in self._por_clave)

    def __contains__(self, nombre):
        return dict.__contains__(self, nombre) or self._por_otra_escritura(nombre)

    def __getitem__(self, nombre):
        if dict.__contains__(self, nombre):
            return dict.__getitem__(self, nombre)
        if self._por_otra_escritura(nombre):
            return self._por_clave[_clave(nombre)]
        raise KeyError(nombre)

    def get(self, nombre, defecto=None):
        return self[nombre] if nombre in self else defecto


def renombrar_adentro(conn, uid: int, nombres: Dict[str, str]) -> Dict[str, int]:
    """Reescribe los nombres de broker adentro de cada columna JSON de la cuenta.
    Va DENTRO de la transacción del renombre, después de tomar el turno: si algo
    falla, no queda un renombre a medias. Devuelve cuántas filas cambió por tabla."""
    hechas = {}
    como_el_importador = None
    # Los nombres de tabla y columna salen de la tupla fija de arriba, nunca del pedido.
    for tabla, col in COLUMNAS_JSON:
        if (tabla, col) == ("import_mappings", "mapping_json"):
            filas = [{"id": f["id"], "t": f["mapping_json"]} for f in plantillas_al_alcance(conn, uid)]
        else:
            filas = conn.execute(
                f"SELECT id, {col} AS t FROM {tabla} WHERE user_id=? AND {col} IS NOT NULL",
                (uid,)).fetchall()
        buscar = nombres
        if (tabla, col) in COMO_EL_IMPORTADOR and filas:
            if como_el_importador is None:
                # A esta altura `brokers` ya tiene los nombres nuevos (ver update_broker).
                vivos = {r["name"] for r in conn.execute(
                    "SELECT name FROM brokers WHERE user_id=?", (uid,)).fetchall()}
                como_el_importador = _ComoElImportador(nombres, vivos)
            buscar = como_el_importador
        n = 0
        for f in filas:
            nuevo = renombrar_en_json(f["t"], buscar, SOLO_BAJO.get((tabla, col)))
            if nuevo is not None:
                conn.execute(f"UPDATE {tabla} SET {col}=? WHERE id=? AND user_id=?",
                             (nuevo, f["id"], uid))
                n += 1
        if n:
            hechas[tabla] = n
    return hechas


# ─── Las plantillas de columnas del importador ────────────────────────────────
def plantillas_al_alcance(conn, uid: int) -> list:
    """Las plantillas de la cuenta que la app usa: las primeras
    PLANTILLAS_MAX_POR_CUENTA (por orden de guardado) de hasta
    PLANTILLA_MAX_CARACTERES. Las mismas para la lista del asistente y para el
    renombre de brokers: lo que se ve es lo que se mantiene al día."""
    return conn.execute(
        "SELECT id, name, mapping_json, created_at FROM import_mappings "
        "WHERE user_id=? AND mapping_json IS NOT NULL AND LENGTH(mapping_json) <= ? "
        "ORDER BY id LIMIT ?",
        (uid, PLANTILLA_MAX_CARACTERES, PLANTILLAS_MAX_POR_CUENTA)).fetchall()



def plantilla_con_broker_de_hoy(conn, uid: int, mapping: dict) -> dict:
    """El mapeo que manda el asistente —al guardar una plantilla y al importar con
    él—, con su broker fijo (`defaults.broker`) escrito como se llama HOY el broker:
      · tipeado con otras mayúsculas o un espacio de más (el importador lo iba a
        tomar igual por ese broker) → su nombre;
      · con un nombre que el broker tuvo ANTES (una pantalla que quedó abierta
        mientras se lo renombraba en otra) → su nombre de hoy;
      · si no es ningún broker de la cuenta → lo tipeado, sin los espacios del borde
        (el importador lo va a crear así).
    Al guardar se llama con el turno de la cuenta ya tomado. No modifica lo recibido."""
    defaults = mapping.get("defaults") if isinstance(mapping, dict) else None
    escrito = defaults.get("broker") if isinstance(defaults, dict) else None
    if not isinstance(escrito, str):
        return mapping
    de_hoy = [r["name"] for r in conn.execute(
        "SELECT name FROM brokers WHERE user_id=?", (uid,)).fetchall()]
    if escrito in de_hoy:
        return mapping
    por_clave = {_clave(n): n for n in de_hoy}
    nombre = (por_clave.get(_clave(escrito))
              or broker_de_hoy_por_nombre_anterior(conn, uid).get(_clave(escrito))
              or escrito.strip())
    nuevos = {k: v for k, v in defaults.items() if k != "broker"}
    if nombre:
        nuevos["broker"] = nombre
    return {**mapping, "defaults": nuevos}


# ─── Los nombres anteriores de cada broker ───────────────────────────────────
def anotar_nombre_anterior(conn, uid: int, broker_id: int, viejo: str, nuevo: str) -> None:
    """El broker `broker_id` deja de llamarse `viejo` y pasa a `nuevo`: `viejo` queda
    anotado entre sus nombres anteriores. Si vuelve a un nombre que ya tuvo, ése sale
    de la lista (es el de hoy). Va en la transacción del renombre."""
    fila = conn.execute("SELECT nombres_anteriores FROM brokers WHERE id=? AND user_id=?",
                        (broker_id, uid)).fetchone()
    try:
        lista = json.loads((fila["nombres_anteriores"] if fila else None) or "[]")
    except (TypeError, ValueError):
        lista = []
    lista = [n for n in lista if isinstance(n, str) and n != nuevo and n != viejo]
    if viejo and viejo != nuevo:
        lista.append(viejo)
    conn.execute("UPDATE brokers SET nombres_anteriores=? WHERE id=? AND user_id=?",
                 (json.dumps(lista) if lista else None, broker_id, uid))


def _con_historia(conn, uid: int) -> list:
    """[(nombre de hoy, [nombres anteriores])] de los brokers que se renombraron."""
    out = []
    for f in conn.execute("SELECT name, nombres_anteriores FROM brokers "
                          "WHERE user_id=? AND nombres_anteriores IS NOT NULL", (uid,)).fetchall():
        try:
            lista = [n for n in json.loads(f["nombres_anteriores"] or "[]") if isinstance(n, str)]
        except (TypeError, ValueError):
            continue
        if lista and f["name"]:
            out.append((f["name"], lista))
    return out


def _clave(nombre) -> str:
    """Como se comparan los nombres de broker en el importador: sin espacios al borde y
    en minúsculas. SIEMPRE en Python: `LOWER()` de SQLite no baja la Ñ ni las tildes, y
    buscar así un broker llamado "Zorzal Ñandú" no lo encontraba (prueba al azar)."""
    return str(nombre or "").strip().lower()


def nombres_anteriores(conn, uid: int) -> Dict[str, list]:
    """{nombre de hoy (`_clave`): [nombres anteriores]} de los brokers del usuario que
    alguna vez se renombraron. Para el anti-duplicados del importador."""
    return {_clave(hoy): lista for hoy, lista in _con_historia(conn, uid)}


def broker_de_hoy_por_nombre_anterior(conn, uid: int) -> Dict[str, Optional[str]]:
    """{nombre anterior (`_clave`): cómo se llama hoy ese broker}. None si dos brokers
    distintos tuvieron ese nombre (no se sabe cuál). Para "Editar y rehacer" y para el
    broker fijo que manda el asistente (`plantilla_con_broker_de_hoy`)."""
    out: Dict[str, Optional[str]] = {}
    for hoy, lista in _con_historia(conn, uid):
        for viejo in lista:
            k = _clave(viejo)
            out[k] = hoy if k not in out else None
    return out
