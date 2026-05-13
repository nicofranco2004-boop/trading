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
from .cash_sim import simulate as simulate_cash
from . import seed as _seed


PREVIEW_TTL_HOURS = 1
MAX_FILE_BYTES = 5_000_000      # 5 MB por archivo individual (input al pipeline)
MAX_TOTAL_BYTES = 5_000_000     # 5 MB sumado al cargar multi-file (cap del endpoint)
MAX_ROWS = 10_000


def sanitize_filename(name: Optional[str]) -> str:
    """Sanitiza un nombre de archivo que llega del cliente. Reduce a chars
    seguros (alfanuméricos + ._- + espacio) y trunca a 80 chars.

    Defensa contra:
    - Path traversal (../) — descartamos slashes
    - Newlines / control chars que rompen logs y la UI de batches
    - Filenames vacíos / None — devolvemos "archivo.csv" como default
    """
    import re
    raw = (name or "").strip()
    if not raw:
        return "archivo.csv"
    # Saca el path en caso de que el navegador haya mandado uno completo
    raw = raw.replace("\\", "/").split("/")[-1]
    # Whitelist conservadora: letras (incluyendo acentos básicos), dígitos,
    # ._- y espacio. Cualquier otra cosa → underscore.
    cleaned = re.sub(r"[^\w\.\- ]", "_", raw, flags=re.UNICODE)
    # Colapsa underscores múltiples y trim
    cleaned = re.sub(r"_+", "_", cleaned).strip(" ._-") or "archivo.csv"
    return cleaned[:80]


def _file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _row_fingerprint(tx: NormalizedTx) -> str:
    """Hash que identifica unívocamente una transacción a efectos de dedup.
    Misma fecha + broker + tipo + activo + cantidad + precio → misma fila lógica.
    No incluye fees ni notes (que pueden diferir entre imports del mismo evento)."""
    parts = [
        tx.date or "",
        (tx.broker or "").strip().lower(),
        tx.operation_type or "",
        (tx.asset_symbol or "").strip().upper(),
        f"{tx.quantity:.8f}" if tx.quantity is not None else "",
        f"{tx.unit_price:.8f}" if tx.unit_price is not None else "",
        f"{tx.gross_amount:.4f}" if tx.gross_amount is not None else "",
    ]
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return h[:16]  # 16 chars son suficientes para colision-free a nivel usuario


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
        return {"error": f"El archivo excede el límite de {MAX_FILE_BYTES // 1_000_000} MB."}
    try:
        content = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            content = file_bytes.decode("latin-1")
        except UnicodeDecodeError:
            return {"error": "No pudimos decodificar el archivo. Probá guardarlo como UTF-8."}
    return mapper_inspect(content)


def _decode_csv(file_bytes: bytes) -> Optional[str]:
    """Decodifica bytes a string. None si falla.

    Probamos en orden: utf-8 (con BOM), cp1252 (Excel Windows), latin-1 (catch-all).
    cp1252 cubre exports de Excel Windows que latin-1 muta mal (chars 0x80-0x9F).
    """
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return file_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def _normalize_header_for_match(line: str) -> str:
    """Normaliza la primera línea de un CSV para comparar headers entre files:
    saca BOM residual, lowercase, strip. Tolera diferencias menores de encoding."""
    return line.lstrip("﻿").strip().lower()


def combine_csv_files(files: List[Tuple[bytes, str]]) -> Tuple[bytes, str, Optional[str]]:
    """Combina N CSVs en un único stream, manteniendo el header del primero y
    saltando el de los siguientes. Útil para multi-file upload del wizard.

    `files`: lista de (bytes, name).

    Devuelve `(combined_bytes, combined_name, error)`. Si `error` es no-None,
    el combinado no se debe usar — el caller debe surface al user.

    Validaciones:
    - Todos los archivos deben ser decodificables (UTF-8 o Latin-1).
    - Todos deben tener el MISMO header en la primera línea — sino no podemos
      garantizar que los row_index sean coherentes ni que el parser funcione.
    - Excluye archivos vacíos.

    Output:
    - combined_name: "2024.csv + 2025.csv + 2026.csv" (max ~200 chars)
    - file_hash se calcula sobre el combined_bytes en run_preview, así dos
      uploads idénticos quedan dedup-eados aunque el orden sea distinto si los
      archivos individuales son iguales (cuestión menor — el orden importa).
    """
    if not files:
        return (b"", "", "No se subió ningún archivo.")
    if len(files) == 1:
        return (files[0][0], files[0][1] or "import.csv", None)

    decoded: List[Tuple[List[str], str]] = []  # [(lines, name), ...]
    for data, name in files:
        if not data:
            continue
        text = _decode_csv(data)
        if text is None:
            return (b"", "", f"No pudimos decodificar '{name}'. Probá guardarlo como UTF-8.")
        lines = text.splitlines()
        if not lines:
            continue
        decoded.append((lines, name or "archivo.csv"))

    if not decoded:
        return (b"", "", "Todos los archivos estaban vacíos.")
    if len(decoded) == 1:
        return ("\n".join(decoded[0][0]).encode("utf-8"), decoded[0][1], None)

    # El header del primero define el formato — los demás deben matchear.
    # Normalizamos para tolerar BOM residual / casing al comparar entre files.
    first_header_norm = _normalize_header_for_match(decoded[0][0][0])
    parts: List[str] = [decoded[0][0][0]]  # header original del primero
    for lines, name in decoded:
        if _normalize_header_for_match(lines[0]) != first_header_norm:
            return (
                b"", "",
                f"Los archivos no coinciden en formato. "
                f"'{name}' tiene un header distinto al primero. "
                f"Subí archivos del mismo broker/export.",
            )
        parts.extend(lines[1:])  # skip header de archivos 2..N

    combined_text = "\n".join(parts)
    names_joined = " + ".join(n for _, n in decoded)
    # Cap el nombre combinado para que entre en la columna file_name
    combined_name = names_joined if len(names_joined) <= 200 else names_joined[:197] + "..."
    return (combined_text.encode("utf-8"), combined_name, None)


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
        return {"error": f"El archivo excede el límite de {MAX_FILE_BYTES // 1_000_000} MB."}

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

    # Normalizar nombres de broker: case-insensitive + trim. Evita que
    # "Cocos capital" y "Cocos Capital" (o "  cocos capital  ") se traten
    # como brokers distintos.
    user_brokers = fetch_user_brokers(conn, uid)
    canonical_by_norm = {name.strip().lower(): name for name in user_brokers}
    # Re-asignar tx.broker al nombre canónico existente si hay match
    for tx in normalized:
        if not tx.broker:
            continue
        key = tx.broker.strip().lower()
        if key in canonical_by_norm:
            tx.broker = canonical_by_norm[key]

    # Auto-crear brokers que aparecen en el CSV pero no existen para este
    # usuario. Inferimos la moneda por mayoría de filas: USD/USDT → USDT,
    # ARS (o empate) → ARS. Si dos filas tienen el mismo broker con casing
    # distinto (ej.: "Bull Market" + "bull market"), las agrupamos bajo el
    # primer casing visto.
    new_brokers_created: List[Dict[str, Any]] = []
    pending: Dict[str, Dict[str, Any]] = {}  # norm_key → {first_name, rows}
    for tx in normalized:
        if not tx.broker:
            continue
        key = tx.broker.strip().lower()
        if key in canonical_by_norm:
            continue  # ya existe
        if key not in pending:
            pending[key] = {"first_name": tx.broker.strip(), "rows": []}
        pending[key]["rows"].append(tx)

    for key, info in pending.items():
        rows_for_broker = info["rows"]
        broker_name = info["first_name"]
        usd_count = sum(1 for t in rows_for_broker
                        if (t.currency or "").upper() in ("USD", "USDT"))
        ars_count = sum(1 for t in rows_for_broker
                        if (t.currency or "").upper() == "ARS")
        inferred = "USDT" if usd_count > ars_count else "ARS"
        cur = conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (uid, broker_name, inferred),
        )
        new_brokers_created.append({
            "name": broker_name,
            "currency": inferred,
            "rows": len(rows_for_broker),
        })
        user_brokers[broker_name] = {
            "id": cur.lastrowid,
            "name": broker_name,
            "currency": inferred,
            "parent_broker_id": None,
        }
        canonical_by_norm[key] = broker_name
        # Re-asignar las txs de este grupo al nombre canónico (por si la fila
        # vino con otro casing del mismo nombre)
        for t in rows_for_broker:
            t.broker = broker_name

    # Validar (necesita estado del usuario, ya con los brokers nuevos)
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

    # En modo "varios brokers" (broker_hint=None y >1 broker distinto en las txs),
    # encendemos route_by_currency automáticamente si hay algún broker ARS con
    # filas USD. El usuario no necesita un toggle — la moneda por fila es
    # inequívoca en este modo.
    is_multi_broker = (broker_hint is None) and (
        len({t.broker for t in valid_txs}) > 1
    )
    if is_multi_broker and not route_by_currency:
        # Buscar si algún broker ARS tiene filas USD
        broker_currencies = dict(
            (r["name"], r["currency"])
            for r in conn.execute("SELECT name, currency FROM brokers WHERE user_id=?", (uid,))
        )
        for tx in valid_txs:
            if (broker_currencies.get(tx.broker) == "ARS"
                    and (tx.currency or "").upper() in ("USD", "USDT")):
                route_by_currency = True
                break
            if tx.operation_type in ("FX_ARS_TO_USD", "FX_USD_TO_ARS") \
                    and broker_currencies.get(tx.broker) == "ARS":
                route_by_currency = True
                break

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

    # Fingerprints existentes en batches confirmados — para detectar dupes
    existing_fingerprints = set(
        r[0] for r in conn.execute(
            """SELECT DISTINCT n.fingerprint
                 FROM import_normalized_tx n
                 JOIN import_batches b ON b.id = n.batch_id
                WHERE b.user_id=? AND b.status='confirmed' AND n.fingerprint IS NOT NULL""",
            (uid,),
        ).fetchall()
    )
    duplicate_row_indices: List[int] = []

    for tx in valid_txs:
        fp = _row_fingerprint(tx)
        if fp in existing_fingerprints:
            duplicate_row_indices.append(tx.row_index)
        conn.execute(
            """INSERT INTO import_normalized_tx
               (batch_id, raw_row_id, date, broker, operation_type, asset_symbol, asset_name, asset_type,
                quantity, unit_price, gross_amount, fees, taxes, currency, settlement_currency, notes,
                fingerprint)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (batch_id, raw_id_by_index[tx.row_index], tx.date, tx.broker, tx.operation_type,
             tx.asset_symbol, tx.asset_name, tx.asset_type,
             tx.quantity, tx.unit_price, tx.gross_amount,
             tx.fees, tx.taxes, tx.currency, tx.settlement_currency, tx.notes,
             fp),
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
    preview_payload["is_multi_broker"] = is_multi_broker
    preview_payload["new_brokers_created"] = new_brokers_created
    preview_payload["duplicate_row_indices"] = duplicate_row_indices

    # Cash simulation pre-confirm: detecta filas que pondrían el cash en
    # negativo y reporta como warnings (no errores — el persister permite
    # overdraft, esto es informativo).
    if valid_txs:
        starting_cash: Dict[Tuple[str, str], float] = {}
        for r in conn.execute(
            """SELECT p.broker, br.currency, p.invested
                 FROM positions p
                 JOIN brokers br ON br.name = p.broker AND br.user_id = p.user_id
                WHERE p.user_id=? AND p.is_cash=1""",
            (uid,),
        ).fetchall():
            starting_cash[(r["broker"], r["currency"])] = float(r["invested"] or 0)

        sim = simulate_cash(
            valid_txs,
            user_brokers=user_brokers,
            starting_cash=starting_cash,
            route_by_currency=route_by_currency,
        )
        preview_payload["cash_warnings"] = [
            {
                "row_index": w.row_index,
                "broker": w.broker,
                "currency": w.currency,
                "new_balance": round(w.new_balance, 2),
                "op_type": w.op_type,
                "message": w.message,
            }
            for w in sim.warnings
        ]
        preview_payload["projected_cash"] = [
            {
                "broker": broker,
                "currency": currency,
                "balance": round(balance, 2),
            }
            for (broker, currency), balance in sorted(sim.final_balances.items())
        ]

    # Seed suggestions: si el CSV referencia activos sin posición previa
    # (errores INSUFFICIENT_STOCK) o tiene overdrafts sobre cash que no fue
    # depositado antes en el archivo, ofrecemos al usuario cargar un "estado
    # inicial". El seed se aplica al confirmar y resuelve esos casos.
    err_insufficient_indices = {e.row_index for e in val_errors
                                  if e.code == "INSUFFICIENT_STOCK"}
    cash_warnings_obj = sim.warnings if valid_txs else []
    seed_suggestions = _seed.build_suggestions(
        valid_txs=valid_txs,
        val_errors=val_errors,
        cash_warnings=cash_warnings_obj,
        user_brokers=user_brokers,
        existing_positions=existing_pos,
        all_normalized=normalized,
    )
    if seed_suggestions:
        # Enriquecer con broker+asset+qty desde las normalized originales
        # (las INSUFFICIENT_STOCK están filtradas de valid_txs)
        seed_suggestions = _seed.enrich_with_sell_assets(
            seed_suggestions,
            all_normalized=normalized,
            err_row_indices=err_insufficient_indices,
        )
        preview_payload["seed_suggestions"] = seed_suggestions

    # Routing summary: por cada broker ARS con filas USD, cuántas van al padre
    # y cuántas al sibling. Sirve para que el frontend muestre chips claros.
    if route_by_currency and valid_txs:
        broker_currencies = dict(
            (r["name"], r["currency"])
            for r in conn.execute("SELECT name, currency FROM brokers WHERE user_id=?", (uid,))
        )
        per_broker: Dict[str, Dict[str, int]] = {}
        for tx in valid_txs:
            entry = per_broker.setdefault(tx.broker, {"ars": 0, "usd": 0})
            cur = (tx.currency or "").upper()
            if cur in ("USD", "USDT"):
                entry["usd"] += 1
            else:
                entry["ars"] += 1
        routing_breakdown = []
        for broker_name in sorted(per_broker.keys()):
            stats = per_broker[broker_name]
            broker_currency = broker_currencies.get(broker_name)
            entry = {
                "broker": broker_name,
                "broker_currency": broker_currency,
                "ars_rows": stats["ars"],
                "usd_rows": stats["usd"],
                "creates_sibling": (broker_currency == "ARS" and stats["usd"] > 0),
                "sibling_name": f"{broker_name} · USD" if broker_currency == "ARS" else None,
            }
            routing_breakdown.append(entry)
        preview_payload["routing_breakdown"] = routing_breakdown
        # Compat: campos planos para el modo single-broker que ya consume el frontend
        total_usd = sum(b["usd_rows"] for b in routing_breakdown)
        total_ars = sum(b["ars_rows"] for b in routing_breakdown)
        preview_payload["routing_summary"] = {
            "ars_rows_to_parent": total_ars,
            "usd_rows_to_sibling": total_usd,
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


def load_session_with_seed_revalidate(
    conn, *, uid: int, session_id: str, seed_state: Optional[Dict[str, Any]],
) -> Tuple[List[NormalizedTx], Dict[int, int]]:
    """Variante de load_session_for_confirm que re-normaliza y re-valida
    TODAS las filas crudas (incluso las que fallaron la primera validación).

    Sirve para cuando el usuario aporta un seed_state: re-corremos el validator
    con las posiciones del seed sumadas, así los SELLs que antes fallaron por
    INSUFFICIENT_STOCK ahora pasan. También re-insertamos las nuevas
    NormalizedTx en la DB para que queden auditables y revertibles.

    Si seed_state es None, comportamiento idéntico a load_session_for_confirm.
    """
    if not seed_state:
        return load_session_for_confirm(conn, uid=uid, session_id=session_id)

    batch = conn.execute(
        "SELECT * FROM import_batches WHERE id=? AND user_id=?", (session_id, uid),
    ).fetchone()
    if not batch:
        raise ValueError("Sesión de import no encontrada o expirada.")
    if batch["status"] != "preview":
        raise ValueError(f"Esta sesión ya está en estado '{batch['status']}'.")

    raw_rows_db = conn.execute(
        """SELECT id, row_index, raw_json FROM import_raw_rows
            WHERE batch_id=? ORDER BY row_index ASC""",
        (session_id,),
    ).fetchall()

    raw_rows: List[RawRow] = []
    raw_id_by_index: Dict[int, int] = {}
    for r in raw_rows_db:
        try:
            data = json.loads(r["raw_json"]) if r["raw_json"] else {}
        except json.JSONDecodeError:
            data = {}
        raw_rows.append(RawRow(row_index=r["row_index"], data=data))
        raw_id_by_index[r["row_index"]] = r["id"]

    # Re-normalizar
    normalized, _ = normalize_rows(raw_rows)

    # Aplicar el mismo broker-canonicalization que run_preview.
    user_brokers = fetch_user_brokers(conn, uid)
    canonical_by_norm = {name.strip().lower(): name for name in user_brokers}
    for tx in normalized:
        if not tx.broker:
            continue
        key = tx.broker.strip().lower()
        if key in canonical_by_norm:
            tx.broker = canonical_by_norm[key]

    # Existing positions + seed posiciones sintéticas → con esto los SELLs
    # antes inválidos pasan validación.
    existing_pos = fetch_existing_positions(conn, uid)
    seed_pos = _seed.seed_state_to_existing_positions(seed_state)
    existing_with_seed: Dict[Tuple[str, str], float] = dict(existing_pos)
    for k, v in seed_pos.items():
        existing_with_seed[k] = existing_with_seed.get(k, 0.0) + v

    route_currency = bool(batch["route_by_currency"] or 0)
    valid_txs, _ = validate(
        normalized,
        user_brokers=user_brokers,
        existing_positions=existing_with_seed,
        route_by_currency=route_currency,
    )

    # Reemplazar el contenido de import_normalized_tx con la nueva validación.
    # Las filas previamente válidas + las promovidas por el seed quedan ahí;
    # las que siguen inválidas se descartan (no van a persister).
    conn.execute("DELETE FROM import_normalized_tx WHERE batch_id=?", (session_id,))
    for tx in valid_txs:
        fp = _row_fingerprint(tx)
        conn.execute(
            """INSERT INTO import_normalized_tx
               (batch_id, raw_row_id, date, broker, operation_type, asset_symbol, asset_name, asset_type,
                quantity, unit_price, gross_amount, fees, taxes, currency, settlement_currency, notes,
                fingerprint)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (session_id, raw_id_by_index[tx.row_index], tx.date, tx.broker, tx.operation_type,
             tx.asset_symbol, tx.asset_name, tx.asset_type,
             tx.quantity, tx.unit_price, tx.gross_amount,
             tx.fees, tx.taxes, tx.currency, tx.settlement_currency, tx.notes,
             fp),
        )

    return valid_txs, raw_id_by_index


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


def reconstruct_csv_from_batch(conn, *, uid: int, batch_id: str) -> Optional[bytes]:
    """Reconstruye un CSV en formato Rendi-canónico desde las raw_rows de un
    batch. Sirve para "Editar y rehacer": revertir un import y re-procesar
    los mismos datos sin pedirle al usuario el archivo otra vez.

    Las raw_rows se almacenaron como `data` (dict) que es la salida del parser
    correspondiente — siempre en el formato canónico de Rendi (fecha/tipo/
    broker/activo/...). Por eso el reuso pasa por el parser genérico.
    """
    batch = conn.execute(
        "SELECT id FROM import_batches WHERE id=? AND user_id=?", (batch_id, uid),
    ).fetchone()
    if not batch:
        return None

    rows = conn.execute(
        """SELECT raw_json FROM import_raw_rows
            WHERE batch_id=? ORDER BY row_index ASC""",
        (batch_id,),
    ).fetchall()
    if not rows:
        return None

    parsed: List[Dict[str, Any]] = []
    for r in rows:
        try:
            d = json.loads(r["raw_json"]) if r["raw_json"] else {}
        except json.JSONDecodeError:
            continue
        # Excluir filas sintéticas del seed — las nuevas se generan en el redo
        if d.get("_synthetic_seed"):
            continue
        parsed.append(d)

    if not parsed:
        return None

    # Headers canónicos del template Rendi (mismo orden que el template).
    headers = ["fecha", "tipo", "broker", "activo", "cantidad", "precio",
                "monto", "monto_usd", "tc", "comisiones", "moneda", "notas"]
    # Si alguna fila trae una clave no estándar, la agregamos al final.
    extra_keys = set()
    for d in parsed:
        for k in d.keys():
            if k not in headers and not k.startswith("_"):
                extra_keys.add(k)
    headers = headers + sorted(extra_keys)

    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    writer = _csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for d in parsed:
        row = {h: d.get(h, "") if d.get(h) is not None else "" for h in headers}
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def parser_options() -> List[Dict[str, Any]]:
    """Lista plana — back-compat para clientes viejos."""
    return [
        {"id": p.format_id, "label": p.display_name, "supported": p.is_supported}
        for p in list_parsers()
    ]


def parser_options_grouped() -> List[Dict[str, Any]]:
    """Devuelve los parsers agrupados por plataforma para el dropdown a 2 niveles.
    Filtra plataformas que no tienen ningún parser soportado (ej.: Cocos
    Capital, que no ofrece export oficial — los usuarios usan el genérico).
    Estructura:
      [
        {
          "platform": "binance",
          "platform_label": "Binance",
          "exports": [
            {"id": "binance", "label": "Spot → Trade History", "supported": true},
            {"id": "binance_futures_trade_history", "label": "Futures → Trade History", "supported": true},
            ...
          ]
        },
        ...
      ]
    """
    grouped: Dict[str, Dict[str, Any]] = {}
    for p in list_parsers():
        if p.platform not in grouped:
            grouped[p.platform] = {
                "platform": p.platform,
                "platform_label": p.platform_label,
                "exports": [],
            }
        grouped[p.platform]["exports"].append({
            "id": p.format_id,
            "label": p.export_label or p.display_name,
            "supported": p.is_supported,
        })
    # Filtrar plataformas sin ningún export soportado — sino el dropdown
    # muestra "Cocos Capital (sin export oficial)" como una opción que solo
    # confunde al usuario.
    grouped = {k: v for k, v in grouped.items()
                if any(e["supported"] for e in v["exports"])}
    # Orden: generic primero, después binance, después el resto
    order = {"generic": 0, "binance": 1, "balanz": 2, "cocos": 3}
    return sorted(grouped.values(), key=lambda g: order.get(g["platform"], 99))
