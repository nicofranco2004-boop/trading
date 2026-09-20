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
# Tope del JSON de filas que guarda el front (nombres de archivo, estados).
MAX_ROWS_JSON = 64 * 1024

ESTADOS_FILA = {"pendiente", "cargando", "completo", "revisar", "error", "revertido", "revert_fallo"}


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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_import_batches_tanda ON import_batches(tanda_id)")


# ─── Filas ───────────────────────────────────────────────────────────────────

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
        cu = r.get("client_uid")
        if cu is not None and not isinstance(cu, int):
            raise ValueError("client_uid debe ser entero")
        archivos = r.get("archivos") or []
        if not isinstance(archivos, list):
            raise ValueError("archivos debe ser una lista")
        out.append({
            "id": int(r.get("id") or 0),
            "client_uid": cu,
            "label": str(r.get("label") or "")[:120],
            "platform": str(r.get("platform") or "")[:40],
            "archivos": [str(a)[:200] for a in archivos][:20],
            "estado": estado,
            "batch_id": (str(r.get("batch_id"))[:64] if r.get("batch_id") else None),
            "cargados": int(r.get("cargados") or 0),
            "repetidos": int(r.get("repetidos") or 0),
            "errores": int(r.get("errores") or 0),
            "detalle": (str(r.get("detalle"))[:500] if r.get("detalle") else None),
            "creado": bool(r.get("creado")),
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


def _estado_lotes(conn, filas: List[Dict[str, Any]]) -> Dict[str, str]:
    """status real de cada lote (`confirmed`/`reverted`/`preview`) — la verdad
    vive en import_batches, el JSON es lo que el front vio en su momento."""
    ids = [f["batch_id"] for f in filas if f.get("batch_id")]
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    return {r["id"]: r["status"] for r in conn.execute(
        f"SELECT id, status FROM import_batches WHERE id IN ({ph})", ids).fetchall()}


def detalle(conn, advisor_uid: int, tanda_id: str) -> Dict[str, Any]:
    r = _row(conn, advisor_uid, tanda_id)
    if not r:
        raise LookupError("tanda")
    filas = json.loads(r["rows_json"] or "[]")
    estados = _estado_lotes(conn, filas)
    for f in filas:
        f["batch_status"] = estados.get(f.get("batch_id"))
        # Un lote revertido desde la cuenta del cliente (botón individual) se
        # refleja acá aunque el JSON diga 'completo'.
        if f.get("batch_id") and f["batch_status"] == "reverted" and f["estado"] in ("completo", "revisar"):
            f["estado"] = "revertido"
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
        "revisar": n("revisar"),
        "errores": n("error"),
        "revertidos": n("revertido") + n("revert_fallo"),
        "movimientos": sum(int(f.get("cargados") or 0) for f in filas),
        "en_curso": n("pendiente") + n("cargando"),
    }


def listar(conn, advisor_uid: int, limit: int = 20) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, created_at, finished_at, rows_json FROM advisor_import_tandas
           WHERE advisor_uid=? ORDER BY created_at DESC LIMIT ?""",
        (advisor_uid, int(limit))).fetchall()
    out = []
    for r in rows:
        filas = json.loads(r["rows_json"] or "[]")
        estados = _estado_lotes(conn, filas)
        for f in filas:
            if f.get("batch_id") and estados.get(f["batch_id"]) == "reverted" and f["estado"] in ("completo", "revisar"):
                f["estado"] = "revertido"
        out.append({
            "id": r["id"], "created_at": r["created_at"], "finished_at": r["finished_at"],
            "resumen": _resumen(filas),
            # Para la lista alcanza con los nombres — el detalle trae todo.
            "clientes": [f.get("label") or (f"Cliente {f['client_uid']}" if f.get("client_uid") else "") for f in filas][:8],
        })
    return out


# ─── Deshacer toda la tanda ─────────────────────────────────────────────────

def revertir(conn, advisor_uid: int, tanda_id: str, *, puede_escribir, revertir_lote) -> Dict[str, Any]:
    """Revierte cada lote de la tanda en la cuenta de SU cliente.

    `puede_escribir(client_uid) -> bool` es el write-gate del vínculo (la misma
    regla que `get_effective_user`: vínculo activo + permission read_write).
    `revertir_lote(client_uid, batch_id)` hace el revert SEGURO y levanta
    Exception con mensaje si no puede (ventas posteriores, etc.).

    Idempotente: un lote ya revertido se saltea como 'ya estaba revertido'.
    Nunca aborta la tanda entera por un lote: informa fila por fila.
    """
    r = _row(conn, advisor_uid, tanda_id)
    if not r:
        raise LookupError("tanda")
    filas = json.loads(r["rows_json"] or "[]")
    estados = _estado_lotes(conn, filas)
    resultado = []
    for f in filas:
        bid, cu = f.get("batch_id"), f.get("client_uid")
        if not bid or f.get("estado") in ("error", "pendiente", "cargando"):
            resultado.append({"id": f.get("id"), "label": f.get("label"), "ok": None, "motivo": "no había nada cargado"})
            continue
        if estados.get(bid) == "reverted":
            f["estado"] = "revertido"
            resultado.append({"id": f.get("id"), "label": f.get("label"), "ok": True, "motivo": "ya estaba revertido"})
            continue
        if not cu or not puede_escribir(cu):
            f["estado"] = "revert_fallo"
            f["detalle"] = "El vínculo con este cliente ya no permite escribir: revertilo desde su cuenta si recuperás el acceso."
            resultado.append({"id": f.get("id"), "label": f.get("label"), "ok": False, "motivo": f["detalle"]})
            continue
        try:
            revertir_lote(cu, bid)
            f["estado"] = "revertido"
            f["detalle"] = None
            resultado.append({"id": f.get("id"), "label": f.get("label"), "ok": True, "motivo": None})
        except Exception as ex:  # noqa: BLE001 — el motivo viaja al asesor tal cual
            f["estado"] = "revert_fallo"
            f["detalle"] = str(getattr(ex, "message", None) or ex)
            resultado.append({"id": f.get("id"), "label": f.get("label"), "ok": False, "motivo": f["detalle"]})
    conn.execute("UPDATE advisor_import_tandas SET rows_json=? WHERE id=?",
                 (json.dumps(filas, ensure_ascii=False), tanda_id))
    ok = sum(1 for x in resultado if x["ok"] is True)
    fallo = sum(1 for x in resultado if x["ok"] is False)
    return {"tanda_id": tanda_id, "revertidos": ok, "fallidos": fallo, "filas": resultado}


def borrar_de_asesor(conn, advisor_uid: int) -> int:
    """Cascada del borrado de cuenta: las tandas son del asesor, no del cliente.
    Los lotes (`import_batches`) son del cliente y siguen su propio ciclo."""
    return conn.execute("DELETE FROM advisor_import_tandas WHERE advisor_uid=?", (advisor_uid,)).rowcount
