"""Tandas de importación del asesor (Plan Asesor, Fase 2).

Una TANDA es la unidad "el asesor apretó Guardar con N filas". Cada fila termina
en un lote propio del importador (`import_batches`, uno por cliente), y este
módulo guarda el paraguas que los agrupa:

  advisor_import_tandas  — id, advisor_uid, created_at, finished_at, rows_json
  import_batches.tanda_id — el lote sabe a qué tanda pertenece (NULL = suelto)

Con eso existen tres cosas que la Fase 1 no tenía:
  1. "Tandas anteriores": qué se cargó, cuándo y cómo terminó cada fila.
  2. Si el asesor cerró la pestaña a mitad, al volver ve qué quedó hecho.
  3. "Deshacer toda la tanda": revierte lote por lote, cada uno en la cuenta
     de SU cliente y con el write-gate de ese vínculo. En modo SEGURO siempre:
     si un lote tiene ventas posteriores o algo que el revert seguro rechaza,
     ESE falla y se informa; nunca se fuerza el modo nuclear desde acá.

⚠️ `rows_json` lo escribe el FRONT (PATCH) y es lo que el asesor VIO. La verdad
sobre qué lotes existen y en qué estado están vive en `import_batches`
(`tanda_id`, `status`, `user_id`): `detalle`, `listar` y sobre todo `revertir`
la leen de ahí. Un rows_json viejo (un PATCH que llegó tarde) no puede hacer
que un lote se saltee.

Todo lo que escribe pasa por `conn` del caller (main.py) para compartir la
transacción y el patrón `with conn:` del resto del código.
"""
from __future__ import annotations

import json
import secrets
from typing import Any, Dict, List, Optional

# Tope de filas por tanda. El front tiene el mismo número (MAX_FILAS): si se
# cambia uno se cambia el otro — acá está la verdad, allá la copia.
MAX_FILAS = 50
# Tope del JSON de filas que guarda el front. 50 filas × (detalle 500 + 20
# archivos × 120 + notas) entra holgado; 64 KB no entraba con nombres largos.
MAX_ROWS_JSON = 256 * 1024

ESTADOS_FILA = {"pendiente", "cargando", "completo", "revisar", "error",
                "revertido", "revert_fallo", "foto_pendiente"}
# Estados en los que un lote confirmado puede seguir vivo (y por tanto revertirse).
_CON_LOTE = {"completo", "revisar", "foto_pendiente"}
_INT_MAX = 2 ** 63 - 1


def ensure_schema(conn) -> None:
    """Crea la tabla y agrega la columna al lote. Idempotente.

    ⚠️ La columna se chequea con PRAGMA directo, NO con `_table_cols()` de
    main.py: esa función tiene una allowlist silenciosa que devuelve set()
    para tablas que no conoce y la migración nunca corre (rompió dos veces:
    `87ab966c` y `twr_periods`). `import_batches` SÍ está en la allowlist,
    pero el patrón directo no depende de eso.
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS advisor_import_tandas (
            id TEXT PRIMARY KEY,
            advisor_uid INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            finished_at TEXT,
            rows_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS idx_advisor_import_tandas
            ON advisor_import_tandas(advisor_uid, created_at);
    """)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(import_batches)").fetchall()]
    if cols and "tanda_id" not in cols:
        conn.execute("ALTER TABLE import_batches ADD COLUMN tanda_id TEXT")
    # El índice va FUERA del branch del ALTER: si el CREATE INDEX fallara una
    # vez, al siguiente arranque la columna ya existiría y no se reintentaría.
    if cols:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_import_batches_tanda ON import_batches(tanda_id)")


# ─── Filas ───────────────────────────────────────────────────────────────────

def _entero(v, campo: str, *, opcional: bool = False, minimo: int = 0) -> Optional[int]:
    """Entero de verdad (no bool, no float, no dict), acotado a 63 bits: SQLite
    no puede bindear más y el 500 saltaba recién en el revert."""
    if v is None:
        if opcional:
            return None
        return 0
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"{campo} debe ser entero")
    if v < minimo or v > _INT_MAX:
        raise ValueError(f"{campo} fuera de rango")
    return v


def _texto(v, largo: int) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        raise ValueError("texto inválido")
    return str(v)[:largo]


def _sanitize_rows(rows: Any) -> List[Dict[str, Any]]:
    """Lo que el front manda por fila, tipado y acotado. No se confía en nada:
    ids enteros, strings cortos, estado dentro del conjunto conocido."""
    if not isinstance(rows, list):
        raise ValueError("rows debe ser una lista")
    if len(rows) > MAX_FILAS:
        raise ValueError(f"Una tanda tiene como máximo {MAX_FILAS} filas")
    out = []
    for r in rows:
        if not isinstance(r, dict):
            raise ValueError("cada fila debe ser un objeto")
        estado = str(r.get("estado") or "pendiente")
        if estado not in ESTADOS_FILA:
            raise ValueError(f"estado desconocido: {estado}")
        archivos = r.get("archivos") or []
        if not isinstance(archivos, list):
            raise ValueError("archivos debe ser una lista")
        notas = r.get("notas") or []
        if not isinstance(notas, list):
            raise ValueError("notas debe ser una lista")
        out.append({
            "id": _entero(r.get("id"), "id"),
            "client_uid": _entero(r.get("client_uid"), "client_uid", opcional=True, minimo=1),
            "label": _texto(r.get("label"), 120) or "",
            # `platform` = id de la plataforma (cocos, balanz…); `platform_label`
            # = cómo se muestra. Los dos: uno para rearmar la fila, otro para leer.
            "platform": _texto(r.get("platform"), 40) or "",
            "platform_label": _texto(r.get("platform_label"), 60) or "",
            "archivos": [(_texto(a, 120) or "") for a in archivos][:20],
            "estado": estado,
            "batch_id": _texto(r.get("batch_id"), 64) or None,
            # La foto de tenencia (F3): su lote, el borrador pendiente y qué
            # estado tenían los movimientos antes de "Aprobar foto". Sin esto
            # una fila 'foto_pendiente' recargada no se podía terminar.
            "foto_batch_id": _texto(r.get("foto_batch_id"), 64) or None,
            "foto_session_id": _texto(r.get("foto_session_id"), 64) or None,
            "foto_nombre": _texto(r.get("foto_nombre"), 120) or None,
            "estado_movimientos": (_texto(r.get("estado_movimientos"), 20) or None)
                if (r.get("estado_movimientos") in ESTADOS_FILA) else None,
            "cargados": _entero(r.get("cargados"), "cargados"),
            "repetidos": _entero(r.get("repetidos"), "repetidos"),
            "errores": _entero(r.get("errores"), "errores"),
            "detalle": _texto(r.get("detalle"), 500) or None,
            "notas": [(_texto(n, 160) or "") for n in notas][:6],
            "creado": bool(r.get("creado")),
            # 5xx en el confirm: no sabemos si llegó a guardarse. Se conserva
            # para que la tanda reabierta no diga "no se cargó nada".
            "incierto": bool(r.get("incierto")),
        })
    blob = json.dumps(out, ensure_ascii=False)
    if len(blob) > MAX_ROWS_JSON:
        raise ValueError("La tanda es demasiado grande para guardarla")
    return out


def crear(conn, advisor_uid: int, rows: Any) -> Dict[str, Any]:
    filas = _sanitize_rows(rows)
    if not filas:
        raise ValueError("La tanda no tiene filas")
    tid = secrets.token_hex(16)
    conn.execute(
        "INSERT INTO advisor_import_tandas (id, advisor_uid, rows_json) VALUES (?,?,?)",
        (tid, advisor_uid, json.dumps(filas, ensure_ascii=False)))
    return {"id": tid, "rows": filas}


def _row(conn, advisor_uid: int, tanda_id: str):
    return conn.execute(
        "SELECT * FROM advisor_import_tandas WHERE id=? AND advisor_uid=?",
        (tanda_id, advisor_uid)).fetchone()


def actualizar(conn, advisor_uid: int, tanda_id: str, rows: Any = None,
               finished: Optional[bool] = None) -> Dict[str, Any]:
    """PATCH parcial: filas y/o cierre. Si rows viene, REEMPLAZA el JSON (el
    front manda siempre la lista completa — es chica y evita merges)."""
    r = _row(conn, advisor_uid, tanda_id)
    if not r:
        raise LookupError("tanda")
    if rows is not None:
        filas = _sanitize_rows(rows)
        conn.execute("UPDATE advisor_import_tandas SET rows_json=? WHERE id=?",
                     (json.dumps(filas, ensure_ascii=False), tanda_id))
    if finished:
        conn.execute(
            "UPDATE advisor_import_tandas SET finished_at=COALESCE(finished_at, datetime('now')) WHERE id=?",
            (tanda_id,))
    return detalle(conn, advisor_uid, tanda_id)


# ─── La verdad: los lotes de la tanda en import_batches ─────────────────────

def _lotes_de_tanda(conn, tanda_id: str) -> Dict[str, Dict[str, Any]]:
    """{batch_id: {user_id, status}} de TODOS los lotes estampados con esta
    tanda — no depende de lo que el front haya llegado a guardar."""
    return {r["id"]: {"user_id": r["user_id"], "status": r["status"], "rowid": r["rowid"]} for r in conn.execute(
        "SELECT rowid, id, user_id, status FROM import_batches WHERE tanda_id=?", (tanda_id,)).fetchall()}


def _reconciliar(filas: List[Dict[str, Any]], lotes: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cruza rows_json (lo que el front vio) con import_batches (lo que pasó).
    - una fila con batch_id → hereda el status real; revertido gana.
    - un lote estampado que ninguna fila nombra (PATCH que llegó tarde) → se
      asigna a la fila de ese cliente que quedó 'cargando'/'pendiente'.
    Sólo se miran lotes de la tanda: nunca ids sueltos que el front pueda mandar."""
    conocidos = ({f["batch_id"] for f in filas if f.get("batch_id")}
                 | {f["foto_batch_id"] for f in filas if f.get("foto_batch_id")})
    for f in filas:
        bid = f.get("batch_id")
        info = lotes.get(bid) if bid else None
        f["batch_status"] = info["status"] if info else None
        if info and info["status"] == "reverted" and f["estado"] in _CON_LOTE:
            f["estado"] = "revertido"
    for bid, info in lotes.items():
        if bid in conocidos or info["status"] not in ("confirmed", "reverted"):
            continue
        huerfana = next((f for f in filas
                         if f.get("client_uid") == info["user_id"]
                         and not f.get("batch_id")
                         and f["estado"] in ("pendiente", "cargando")), None)
        if huerfana is not None:
            huerfana["batch_id"] = bid
            huerfana["batch_status"] = info["status"]
            huerfana["estado"] = "revertido" if info["status"] == "reverted" else "completo"
            huerfana["notas"] = list(huerfana.get("notas") or []) + ["el detalle de esta fila no llegó a guardarse; el lote sí"]
            conocidos.add(bid)
    return filas


def detalle(conn, advisor_uid: int, tanda_id: str) -> Dict[str, Any]:
    r = _row(conn, advisor_uid, tanda_id)
    if not r:
        raise LookupError("tanda")
    filas = _reconciliar(json.loads(r["rows_json"] or "[]"), _lotes_de_tanda(conn, tanda_id))
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "finished_at": r["finished_at"],
        "rows": filas,
        "resumen": _resumen(filas),
    }


def _resumen(filas: List[Dict[str, Any]]) -> Dict[str, int]:
    def n(e):
        return sum(1 for f in filas if f.get("estado") == e)
    return {
        "total": len(filas),
        "completos": n("completo"),
        "revisar": n("revisar") + n("foto_pendiente"),
        "errores": n("error"),
        "revertidos": n("revertido") + n("revert_fallo"),
        "movimientos": sum(int(f.get("cargados") or 0) for f in filas if f.get("estado") in _CON_LOTE),
        "en_curso": n("pendiente") + n("cargando"),
    }


def listar(conn, advisor_uid: int, limit: int = 20) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, created_at, finished_at, rows_json FROM advisor_import_tandas
           WHERE advisor_uid=? ORDER BY created_at DESC LIMIT ?""",
        (advisor_uid, int(limit))).fetchall()
    out = []
    for r in rows:
        filas = _reconciliar(json.loads(r["rows_json"] or "[]"), _lotes_de_tanda(conn, r["id"]))
        out.append({
            "id": r["id"], "created_at": r["created_at"], "finished_at": r["finished_at"],
            "resumen": _resumen(filas),
            # Para la lista alcanza con los nombres — el detalle trae todo.
            "clientes": [f.get("label") or (f"Cliente {f['client_uid']}" if f.get("client_uid") else "") for f in filas][:8],
        })
    return out


# ─── Deshacer toda la tanda ─────────────────────────────────────────────────

_MSG_SIN_VINCULO = "Ya no tenés permiso de escritura sobre este cliente: revertilo desde su cuenta si recuperás el acceso."
_MSG_CLIENTE_BORRADO = "La cuenta de este cliente ya no existe: no hay nada que revertir."
_MSG_TRANSITORIO = "Error momentáneo al revertir (la base estaba ocupada): volvé a intentar en un momento."


def revertir(conn, advisor_uid: int, tanda_id: str, *, puede_escribir, revertir_lote) -> Dict[str, Any]:
    """Revierte cada lote de la tanda en la cuenta de SU cliente.

    `puede_escribir(client_uid) -> bool` es el write-gate del vínculo (la misma
    regla que `get_effective_user`: vínculo activo + permission read_write).
    `revertir_lote(client_uid, batch_id)` hace el revert SEGURO y levanta
    RuntimeError con el mensaje del persister si no puede (ventas posteriores…).

    Los lotes salen de `import_batches.tanda_id` (la verdad), no de rows_json, y
    se revierten del MÁS NUEVO al más viejo: la foto (que se aplica después de
    los movimientos) antes que los movimientos, porque el revert seguro de un
    lote rechaza deshacer posiciones que un lote posterior ya tocó.
    Idempotente: un lote ya revertido se saltea como 'ya estaba revertido'.
    Nunca aborta la tanda entera por un lote: informa fila por fila.
    """
    r = _row(conn, advisor_uid, tanda_id)
    if not r:
        raise LookupError("tanda")
    lotes = _lotes_de_tanda(conn, tanda_id)
    filas = _reconciliar(json.loads(r["rows_json"] or "[]"), lotes)

    def _fila_de(bid):
        return next((f for f in filas if f.get("batch_id") == bid or f.get("foto_batch_id") == bid), None)

    resultado = []
    # Del más nuevo al más viejo (rowid crece con la creación).
    for bid in sorted(lotes, key=lambda b: lotes[b]["rowid"], reverse=True):
        info = lotes[bid]
        f = _fila_de(bid) or {}
        es_foto = f.get("foto_batch_id") == bid
        etiqueta = (f.get("label") or "") + (" (foto)" if es_foto else "")
        cu = info["user_id"]   # el dueño real del lote manda sobre lo que diga la fila
        if info["status"] == "reverted":
            if f and not es_foto: f["estado"] = "revertido"
            resultado.append({"id": f.get("id"), "label": etiqueta, "ok": True, "motivo": "ya estaba revertido"})
            continue
        if info["status"] != "confirmed":
            continue   # un borrador (preview) no está aplicado: no hay nada que revertir
        if not puede_escribir(cu):
            if f: f["estado"] = "revert_fallo"; f["detalle"] = _MSG_SIN_VINCULO
            resultado.append({"id": f.get("id"), "label": etiqueta, "ok": False, "motivo": _MSG_SIN_VINCULO})
            continue
        try:
            revertir_lote(cu, bid)
            if f and not es_foto:
                f["estado"] = "revertido"; f["detalle"] = None
            resultado.append({"id": f.get("id"), "label": etiqueta, "ok": True, "motivo": None})
        except RuntimeError as ex:   # el persister dijo que no (ventas posteriores, etc.)
            if f: f["estado"] = "revert_fallo"; f["detalle"] = str(ex)
            resultado.append({"id": f.get("id"), "label": etiqueta, "ok": False, "motivo": str(ex)})
        except Exception:  # noqa: BLE001 — base ocupada u otro transitorio: NO se graba el texto crudo
            if f: f["estado"] = "revert_fallo"; f["detalle"] = _MSG_TRANSITORIO
            resultado.append({"id": f.get("id"), "label": etiqueta, "ok": False, "motivo": _MSG_TRANSITORIO})
    con_lote = {f.get("batch_id") for f in filas} | {f.get("foto_batch_id") for f in filas}
    for f in filas:
        if not f.get("batch_id") and not f.get("foto_batch_id"):
            resultado.append({"id": f.get("id"), "label": f.get("label"), "ok": None, "motivo": "no había nada cargado"})
    conn.execute("UPDATE advisor_import_tandas SET rows_json=? WHERE id=?",
                 (json.dumps(filas, ensure_ascii=False), tanda_id))
    ok = sum(1 for x in resultado if x["ok"] is True)
    fallo = sum(1 for x in resultado if x["ok"] is False)
    return {"tanda_id": tanda_id, "revertidos": ok, "fallidos": fallo, "filas": resultado}


# ─── Ciclo de vida ──────────────────────────────────────────────────────────

def borrar_de_asesor(conn, advisor_uid: int) -> int:
    """Cascada del borrado de cuenta: las tandas son del asesor, no del cliente.
    Los lotes (`import_batches`) son del cliente y siguen su propio ciclo."""
    return conn.execute("DELETE FROM advisor_import_tandas WHERE advisor_uid=?", (advisor_uid,)).rowcount


def olvidar_cliente(conn, client_uid: int) -> int:
    """Cuando se borra la cuenta de un CLIENTE, su nombre no puede sobrevivir
    en las tandas de su asesor (mismo hallazgo que advisor_reports). La fila
    queda como 'Cliente eliminado', sin uid, con el estado que corresponde."""
    n = 0
    rows = conn.execute(
        "SELECT id, rows_json FROM advisor_import_tandas WHERE rows_json LIKE ?",
        (f'%"client_uid": {int(client_uid)},%',)).fetchall()
    for r in rows:
        filas = json.loads(r["rows_json"] or "[]")
        tocada = False
        for f in filas:
            if f.get("client_uid") == client_uid:
                f["client_uid"] = None
                f["label"] = "Cliente eliminado"
                if f.get("estado") in _CON_LOTE:
                    f["estado"] = "revert_fallo"
                    f["detalle"] = _MSG_CLIENTE_BORRADO
                tocada = True
        if tocada:
            conn.execute("UPDATE advisor_import_tandas SET rows_json=? WHERE id=?",
                         (json.dumps(filas, ensure_ascii=False), r["id"]))
            n += 1
    return n
