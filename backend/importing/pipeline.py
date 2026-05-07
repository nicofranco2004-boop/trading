"""Pipeline orchestrator: ata las etapas (parse → normalize → validate → preview).

Las sesiones de preview se persisten en `import_batches` con status='preview'.
Esto sobrevive a reinicios y reusa el mismo storage que los batches confirmados.

Cleanup: batches en estado 'preview' más viejos que PREVIEW_TTL_HOURS se borran
al inicio de cada preview nuevo (cleanup oportunista, no necesita cron job).
"""
from __future__ import annotations
import hashlib
import json
import secrets
from typing import Any, Dict, List, Optional, Tuple

from .schema import NormalizedTx, RawRow, RowError
from .parsers.registry import get_parser, autodetect, list_parsers
from .normalizer import normalize_rows
from .validator import validate
from .preview import build_preview
from .mapper import Mapping, apply_mapping, inspect_csv as mapper_inspect


PREVIEW_TTL_HOURS = 1
MAX_FILE_BYTES = 1_000_000      # 1 MB
MAX_ROWS = 10_000


def _file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _new_id() -> str:
    return secrets.token_hex(16)


def cleanup_stale_previews(conn) -> None:
    """Borra batches con status='preview' más viejos que PREVIEW_TTL_HOURS."""
    conn.execute(
        f"""DELETE FROM import_batches
            WHERE status='preview'
              AND created_at < datetime('now', '-{PREVIEW_TTL_HOURS} hours')"""
    )


def fetch_user_brokers(conn, uid: int) -> Dict[str, dict]:
    rows = conn.execute(
        "SELECT id, name, currency, parent_broker_id FROM brokers WHERE user_id=?", (uid,),
    ).fetchall()
    return {r["name"]: dict(r) for r in rows}


def fetch_existing_positions(conn, uid: int) -> Dict[Tuple[str, str], float]:
    rows = conn.execute(
        """SELECT broker, asset, SUM(COALESCE(quantity,0)) AS qty
             FROM positions
            WHERE user_id=? AND is_cash=0
            GROUP BY broker, asset""",
        (uid,),
    ).fetchall()
    return {(r["broker"], r["asset"]): float(r["qty"] or 0) for r in rows}


def find_duplicate_batch(conn, uid: int, file_hash: str) -> Optional[str]:
    row = conn.execute(
        """SELECT id FROM import_batches
            WHERE user_id=? AND file_hash=? AND status='confirmed'
            ORDER BY created_at DESC LIMIT 1""",
        (uid, file_hash),
    ).fetchone()
    return row["id"] if row else None


def inspect(file_bytes: bytes) -> Dict[str, Any]:
    """Lee headers + primeras filas del CSV. Sin auth contra DB. Devuelve
    metadata para que el frontend muestre el wizard de mapeo de columnas."""
    if len(file_bytes) > MAX_FILE_BYTES:
        return {"error": "El archivo excede el límite de 1 MB."}
    try:
        content = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            content = file_bytes.decode("latin-1")
        except UnicodeDecodeError:
            return {"error": "No pudimos decodificar el archivo. Probá guardarlo como UTF-8."}
    return mapper_inspect(content)


def run_preview(
    conn,
    *,
    uid: int,
    file_bytes: bytes,
    file_name: Optional[str],
    broker_hint: Optional[str],            # broker default si la fila no lo trae
    parser_format: Optional[str],
    mapping: Optional[Dict[str, Any]] = None,   # mapping de columnas (formato libre)
    route_by_currency: bool = False,            # si True y broker es ARS, rutear USD al sub-broker
) -> Dict[str, Any]:
    """Ejecuta el pipeline hasta preview. Persiste el batch (status='preview')
    y devuelve el preview + session_id (== batch_id)."""
    if len(file_bytes) > MAX_FILE_BYTES:
        return {"error": "El archivo excede el límite de 1 MB."}

    cleanup_stale_previews(conn)

    fh = _file_hash(file_bytes)
    duplicate_of = find_duplicate_batch(conn, uid, fh)

    # Decode (intenta utf-8, latin-1)
    try:
        content = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            content = file_bytes.decode("latin-1")
        except UnicodeDecodeError:
            return {"error": "No pudimos decodificar el archivo. Probá guardarlo como UTF-8."}

    # Si viene un mapping explícito, lo aplicamos para traducir el CSV a los
    # headers internos de Rendi. Después corremos el RendiGenericParser sobre
    # ese intermedio. Esto desacopla el formato del usuario del pipeline.
    parser = get_parser("rendi_generic")
    if mapping:
        m = Mapping.from_dict(mapping)
        translated, err = apply_mapping(content, m)
        if err:
            return {"error": err}
        content = translated
    elif parser_format and parser_format != "rendi_generic":
        # Otros parsers (binance/cocos/balanz) — placeholder por ahora
        candidate = get_parser(parser_format)
        if candidate is None:
            return {"error": f"Formato '{parser_format}' desconocido."}
        if not candidate.is_supported:
            return {"error": f"El parser '{candidate.display_name}' aún no está disponible."}
        parser = candidate

    # Parsear
    parse_result = parser.parse(content, file_name=file_name)
    if parse_result.parse_errors and not parse_result.raw_rows:
        # Error fatal a nivel archivo
        return {
            "error": parse_result.parse_errors[0].message,
            "errors": [e.to_dict() for e in parse_result.parse_errors],
        }
    if len(parse_result.raw_rows) > MAX_ROWS:
        return {"error": f"El archivo tiene más de {MAX_ROWS} filas. Dividilo en partes."}

    # Normalizar
    normalized, norm_errors = normalize_rows(parse_result.raw_rows)

    # Validar (necesita estado del usuario)
    user_brokers = fetch_user_brokers(conn, uid)
    existing_pos = fetch_existing_positions(conn, uid)
    valid_txs, val_errors = validate(
        normalized,
        user_brokers=user_brokers,
        existing_positions=existing_pos,
        route_by_currency=route_by_currency,
    )

    # Combinar errores por row_index (parse + norm + validation)
    errors_by_row: Dict[int, List[RowError]] = {}
    for e in parse_result.parse_errors + norm_errors + val_errors:
        errors_by_row.setdefault(e.row_index, []).append(e)

    total_rows = len(parse_result.raw_rows)
    invalid_rows = len(errors_by_row)
    valid_rows = len(valid_txs)

    # Persistir batch en estado preview + raw_rows + normalized_tx
    batch_id = _new_id()
    # Determinar broker para el batch: el más frecuente entre las txs (o broker_hint)
    main_broker = broker_hint
    if not main_broker:
        from collections import Counter
        if normalized:
            main_broker = Counter(t.broker for t in normalized).most_common(1)[0][0]
        else:
            main_broker = "?"

    conn.execute(
        """INSERT INTO import_batches
           (id, user_id, broker, parser_format, file_name, file_hash,
            total_rows, valid_rows, invalid_rows, status, route_by_currency)
           VALUES (?,?,?,?,?,?,?,?,?, 'preview', ?)""",
        (batch_id, uid, main_broker, parser.format_id, file_name, fh,
         total_rows, valid_rows, invalid_rows, 1 if route_by_currency else 0),
    )

    # Insertar raw_rows + normalized_tx (asignamos los row_id en el camino)
    raw_id_by_index: Dict[int, int] = {}
    for raw in parse_result.raw_rows:
        errs = errors_by_row.get(raw.row_index, [])
        status = "invalid" if errs else "valid"
        cur = conn.execute(
            """INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status, errors_json)
               VALUES (?,?,?,?,?)""",
            (batch_id, raw.row_index, json.dumps(raw.data, ensure_ascii=False),
             status, json.dumps([e.to_dict() for e in errs], ensure_ascii=False) if errs else None),
        )
        raw_id_by_index[raw.row_index] = cur.lastrowid

    for tx in valid_txs:
        conn.execute(
            """INSERT INTO import_normalized_tx
               (batch_id, raw_row_id, date, broker, operation_type, asset_symbol, asset_name, asset_type,
                quantity, unit_price, gross_amount, fees, taxes, currency, settlement_currency, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (batch_id, raw_id_by_index[tx.row_index], tx.date, tx.broker, tx.operation_type,
             tx.asset_symbol, tx.asset_name, tx.asset_type,
             tx.quantity, tx.unit_price, tx.gross_amount,
             tx.fees, tx.taxes, tx.currency, tx.settlement_currency, tx.notes),
        )

    preview_payload = build_preview(
        total_rows=total_rows,
        valid_txs=valid_txs,
        errors_by_row=errors_by_row,
        parser_format=parser.format_id,
        file_name=file_name,
        duplicate_of_batch_id=duplicate_of,
    )
    preview_payload["session_id"] = batch_id
    preview_payload["route_by_currency"] = route_by_currency

    # Si el ruteo está activo, contamos cuántas filas USD/USDT se irán al sub-broker
    # para mostrarlo en el preview (cuántas a ARS, cuántas a USD).
    if route_by_currency:
        usd_rows = sum(1 for t in valid_txs if (t.currency or "").upper() in ("USD", "USDT"))
        ars_rows = len(valid_txs) - usd_rows
        preview_payload["routing_summary"] = {
            "ars_rows_to_parent": ars_rows,
            "usd_rows_to_sibling": usd_rows,
        }
    return preview_payload


def load_session_for_confirm(conn, *, uid: int, session_id: str
                              ) -> Tuple[List[NormalizedTx], Dict[int, int]]:
    """Reconstruye la lista de NormalizedTx desde la DB para el confirm.
    También devuelve el mapping row_index → raw_row_id para que el persister
    pueda linkear los IDs creados."""
    batch = conn.execute(
        "SELECT * FROM import_batches WHERE id=? AND user_id=?", (session_id, uid),
    ).fetchone()
    if not batch:
        raise ValueError("Sesión de import no encontrada o expirada.")
    if batch["status"] != "preview":
        raise ValueError(f"Esta sesión ya está en estado '{batch['status']}'.")

    rows = conn.execute(
        """SELECT n.*, r.row_index AS r_idx
             FROM import_normalized_tx n
             JOIN import_raw_rows r ON r.id = n.raw_row_id
            WHERE n.batch_id=?
            ORDER BY n.id ASC""",
        (session_id,),
    ).fetchall()

    txs: List[NormalizedTx] = []
    raw_id_by_index: Dict[int, int] = {}
    for r in rows:
        tx = NormalizedTx(
            row_index=r["r_idx"],
            date=r["date"],
            broker=r["broker"] or batch["broker"],
            operation_type=r["operation_type"],
            asset_symbol=r["asset_symbol"],
            asset_name=r["asset_name"],
            asset_type=r["asset_type"],
            quantity=r["quantity"],
            unit_price=r["unit_price"],
            gross_amount=r["gross_amount"],
            fees=r["fees"] or 0.0,
            taxes=r["taxes"] or 0.0,
            currency=r["currency"],
            settlement_currency=r["settlement_currency"],
            notes=r["notes"],
        )
        txs.append(tx)
        raw_id_by_index[r["r_idx"]] = r["raw_row_id"]
    return txs, raw_id_by_index


def list_batches(conn, *, uid: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, broker, parser_format, file_name, file_hash,
                  total_rows, valid_rows, invalid_rows, status,
                  created_at, confirmed_at, reverted_at
             FROM import_batches
            WHERE user_id=? AND status IN ('confirmed','reverted')
            ORDER BY created_at DESC""",
        (uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def parser_options() -> List[Dict[str, Any]]:
    return [
        {"id": p.format_id, "label": p.display_name, "supported": p.is_supported}
        for p in list_parsers()
    ]
