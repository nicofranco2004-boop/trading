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
from .excel import to_csv_text, is_xlsx, xlsx_to_csv, is_html_table, html_table_to_csv
from . import seed as _seed


PREVIEW_TTL_HOURS = 1
MAX_FILE_BYTES = 5_000_000      # 5 MB por archivo individual (input al pipeline)
MAX_TOTAL_BYTES = 5_000_000     # 5 MB sumado al cargar multi-file (cap del endpoint)
MAX_ROWS = 10_000


def _read_user_tc_blue(conn, uid: int) -> float:
    """Blue con el que se estampa `gross_amount_usd` de los flujos ARS al importar.

    Preferimos el blue LIVE (el MISMO dolarapi que ve el usuario en pantalla) y
    solo caemos al `tc_blue` guardado en config si el caché live está frío.

    ⚠️ Antes usábamos SOLO el config, que en cuentas viejas quedaba stale (ej.
    ~143 de 2021, nunca actualizado tras el rail live). Resultado: depósitos en
    pesos estampados a un dólar ~10× chico → "capital aportado" inflado y pérdida
    fantasma, aunque el dólar de display fuera correcto (dos fuentes distintas).
    `_display_blue` ya trae el blue del caché de dolarapi con fallback al config,
    así que el import queda alineado con el resto de la app. Late-import de main
    para no romper el circular pipeline ↔ main al nivel de módulo."""
    try:
        import main as _main
        live = _main._display_blue(conn, uid)
        if live and float(live) > 0:
            return float(live)
    except Exception:
        pass
    # Fallback (import de main falló / caché frío): tc_blue del config, default 1415.
    row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key='tc_blue'", (uid,),
    ).fetchone()
    try:
        v = float(row["value"]) if row else 1415.0
        return v if v > 0 else 1415.0
    except (TypeError, ValueError):
        return 1415.0


def _stamp_gross_amount_usd(currency, gross_amount, tc_blue):
    """Fase 4 (2026-05-30): convierte gross_amount a USD usando el tc_blue
    del momento del import. Stampado en `import_normalized_tx.gross_amount_usd`.
    Readers downstream (recalc, /api/movements) usan este valor stamped en
    vez de re-calcularlo con tc_blue actual — estable contra cambios de TC.
    Devuelve None si gross_amount es None.
    """
    if gross_amount is None:
        return None
    cur = (currency or "").upper()
    if cur == "ARS" and tc_blue and tc_blue > 0:
        return float(gross_amount) / float(tc_blue)
    return float(gross_amount)


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


def already_imported_row_indices(conn, uid: int, session_id: str, txs,
                                 already_skipped=()) -> set:
    """row_index de las filas cuyo fingerprint YA existe en OTRO batch confirmado
    del usuario → se omiten en el confirm para no duplicar al re-importar.

    Es cross-batch (no intra-batch): dos ops idénticas en el MISMO archivo se
    respetan; solo se saltea lo que ya entró en una importación anterior. Así una
    actualización mensual agrega SOLO lo nuevo y conserva el historial previo."""
    existing = {
        r["fingerprint"] for r in conn.execute(
            """SELECT DISTINCT n.fingerprint
                 FROM import_normalized_tx n
                 JOIN import_batches b ON n.batch_id = b.id
                WHERE b.user_id=? AND b.status='confirmed' AND b.id != ?
                  AND n.fingerprint IS NOT NULL""",
            (uid, session_id),
        ).fetchall()
    }
    if not existing:
        return set()
    skip = set(already_skipped)
    return {t.row_index for t in txs
            if t.row_index not in skip and _row_fingerprint(t) in existing}


def inspect(file_bytes: bytes) -> Dict[str, Any]:
    """Lee headers + primeras filas del CSV. Sin auth contra DB. Devuelve
    metadata para que el frontend muestre el wizard de mapeo de columnas."""
    if len(file_bytes) > MAX_FILE_BYTES:
        return {"error": f"El archivo excede el límite de {MAX_FILE_BYTES // 1_000_000} MB."}
    try:
        content = to_csv_text(file_bytes)  # maneja .xlsx (convierte) y CSV (decodifica)
    except ValueError as ex:
        return {"error": str(ex)}
    return mapper_inspect(content)


def _decode_csv(file_bytes: bytes) -> Optional[str]:
    """Decodifica bytes a string CSV. None si falla.

    Si es un .xlsx (multi-file con Excel), lo convierte a CSV primero. Para CSV
    en texto probamos: utf-8 (con BOM), cp1252 (Excel Windows), latin-1 (catch-all).
    cp1252 cubre exports de Excel Windows que latin-1 muta mal (chars 0x80-0x9F).
    """
    if is_xlsx(file_bytes):
        try:
            return xlsx_to_csv(file_bytes)
        except ValueError:
            return None
    if is_html_table(file_bytes):
        try:
            return html_table_to_csv(file_bytes)
        except ValueError:
            return None
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
            # Hint dirigido: si el que no matchea (o el primero) es una FOTO de
            # tenencia (Estado de Cuenta de Cocos), no va en este wizard de
            # Movimientos — va por su propio botón.
            hint = ""
            try:
                from .tenencia import looks_like_cocos_tenencia
                if looks_like_cocos_tenencia(lines[0]) or looks_like_cocos_tenencia(decoded[0][0][0]):
                    hint = (' Si subiste el Estado de Cuenta (Portfolio) de Cocos, ese no va acá: '
                            'subílo aparte con el botón "Estado de Cuenta Cocos".')
            except Exception:
                pass
            return (
                b"", "",
                f"Los archivos no coinciden en formato. "
                f"'{name}' tiene un header distinto al primero. "
                f"Subí archivos del mismo broker/export.{hint}",
            )
        parts.extend(lines[1:])  # skip header de archivos 2..N

    combined_text = "\n".join(parts)
    names_joined = " + ".join(n for _, n in decoded)
    # Cap el nombre combinado para que entre en la columna file_name
    combined_name = names_joined if len(names_joined) <= 200 else names_joined[:197] + "..."
    return (combined_text.encode("utf-8"), combined_name, None)


def _snap_cash(x, eps: float = 1.0) -> float:
    """Redondea a 2 decimales y aplasta a 0 el ruido sub-unitario. Un export
    puede netear el cash de un sub-broker a -0,11 (residuo de comisiones/
    redondeo): no es plata real ni un overdraft, así que lo mostramos como 0.
    Saldos reales (≥ 1 unidad, positivos o negativos) se mantienen."""
    r = round(float(x), 2)
    return 0.0 if abs(r) < eps else r


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

    # Decode / convertir a CSV. to_csv_text maneja .xlsx (convierte la primera
    # hoja a CSV) y CSV en texto (utf-8-sig / latin-1).
    try:
        content = to_csv_text(file_bytes)
    except ValueError as ex:
        return {"error": str(ex)}

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

    # Fallback robusto: si se eligió un parser ESPECÍFICO que no matchea el
    # archivo (headers mismatch → 0 filas), reintentamos con autodetect sobre
    # los headers reales. Cubre el caso del usuario que en el wizard elige
    # "Balanz" (que defaultea al export de Órdenes) pero subió el de Resultados
    # —o viceversa— y, en general, cualquier broker con >1 formato de export.
    if (parse_result.parse_errors and not parse_result.raw_rows
            and parser.format_id != "rendi_generic"):
        try:
            import csv as _csv, io as _io
            headers = next(_csv.reader(_io.StringIO(content)), [])
        except Exception:
            headers = []
        auto = autodetect(headers)
        if auto is not None and auto.format_id != parser.format_id:
            alt = auto.parse(content, file_name=file_name)
            if alt.raw_rows:
                parser, parse_result = auto, alt

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

    # Moneda base CONOCIDA por parser: la plataforma define la moneda del broker.
    # Cocos/IOL/Balanz/Bullmarket → ARS; Binance → USDT; Schwab/IBKR → USD. Gana
    # sobre cualquier inferencia por mayoría de filas (un export de Cocos trae más
    # filas USD por las compras dólar-MEP, pero el broker es ARS). Solo aplica a
    # parsers específicos; el genérico ('rendi_generic') no está y sigue por fila.
    FORMAT_BASE_CURRENCY = {
        'cocos': 'ARS', 'bullmarket': 'ARS', 'balanz': 'ARS', 'iol': 'ARS',
        # Variantes/otros parsers AR: el export de "Resultados" de Balanz y el de IEB
        # también son brokers ARS. Sin esto, fmt_base=None → no ancla la moneda del
        # padre → un broker auto-creado puede inferirse USD/USDT por mayoría de filas
        # dólar-MEP (un export AR trae muchas filas USD por las compras MEP).
        'balanz_resultados': 'ARS', 'ieb': 'ARS', 'ppi': 'ARS',
        # Balanz INTERNACIONAL: cuenta exterior en DÓLARES (acciones US reales, no
        # CEDEARs) → el broker 'Balanz Internacional' es USD. Explícito para que NO
        # se infiera ARS por el nombre (contiene 'balanz') ni quede ambiguo por filas.
        'balanz_internacional': 'USD',
        'binance': 'USDT', 'schwab': 'USD', 'ibkr': 'USD',
    }
    fmt_base = FORMAT_BASE_CURRENCY.get(parser.format_id)

    # Auto-heal: si el broker destino YA existe con una moneda distinta a la base
    # de la plataforma (típico: lo creó un preview viejo con el bug de inferencia,
    # ej. "Cocos" quedó en USD) y está VACÍO (sin posiciones), le corregimos la
    # moneda. Así un re-import no queda pegado a un broker mal etiquetado. Si ya
    # tuviera posiciones cargadas, NO lo tocamos — el usuario debe revertir ese
    # import primero (cambiar la moneda reinterpretaría su data).
    if fmt_base:
        healed_targets = set()
        for tx in normalized:
            name = tx.broker
            if not name or name in healed_targets:
                continue
            healed_targets.add(name)
            info = user_brokers.get(name)
            if not info or info.get("currency") == fmt_base:
                continue
            has_data = conn.execute(
                "SELECT 1 FROM positions WHERE user_id=? AND broker=? LIMIT 1",
                (uid, name),
            ).fetchone()
            if has_data:
                continue
            conn.execute("UPDATE brokers SET currency=? WHERE user_id=? AND name=?",
                         (fmt_base, uid, name))
            info["currency"] = fmt_base

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

    # Sets para distinguir brokers crypto-native (USDT) vs tradicionales (USD).
    # Cuando un broker se auto-crea, miramos el nombre + la moneda de las filas:
    #   • Brokers cripto típicos → USDT
    #   • Brokers tradicionales con filas USD → USD (no USDT)
    #   • Brokers AR → ARS
    CRYPTO_BROKERS = frozenset({
        'binance', 'coinbase', 'kraken', 'bybit', 'kucoin', 'bitget',
        'okx', 'huobi', 'gemini', 'crypto.com', 'lemon', 'ripio', 'buenbit',
        'satoshitango', 'fiwind',
    })
    for key, info in pending.items():
        rows_for_broker = info["rows"]
        broker_name = info["first_name"]
        broker_lower = broker_name.lower()
        usd_count = sum(1 for t in rows_for_broker
                        if (t.currency or "").upper() == "USD")
        usdt_count = sum(1 for t in rows_for_broker
                         if (t.currency or "").upper() == "USDT")
        ars_count = sum(1 for t in rows_for_broker
                        if (t.currency or "").upper() == "ARS")
        # Prioridad de inferencia:
        #   1. Nombre conocido cripto → USDT (aunque tenga filas USD: en
        #      Binance "USD" suele venir como USDT igual)
        #   2. Moneda base conocida del parser (Cocos→ARS, etc.) → gana sobre la
        #      mayoría de filas. Evita que un broker AR caiga en USD por tener
        #      muchas compras dólar-MEP.
        #   3. Mayoría USDT → USDT (datos explícitos)
        #   4. Mayoría ARS → ARS
        #   5. Cualquier otro caso (mayoría USD o mix) → USD
        if broker_lower in CRYPTO_BROKERS:
            inferred = "USDT"
        elif fmt_base:
            inferred = fmt_base
        elif usdt_count > usd_count and usdt_count > ars_count:
            inferred = "USDT"
        elif ars_count > usd_count and ars_count > usdt_count:
            inferred = "ARS"
        else:
            inferred = "USD"
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

    # Auto-ruteo por moneda (reemplaza el viejo toggle "¿este archivo tiene
    # operaciones en USD?"): si algún broker ARS trae filas en USD/USDT o
    # conversiones FX, esas filas se separan a un sub-broker "<Padre> · USD". La
    # moneda de cada fila es inequívoca (la trae el parser), así que el ruteo se
    # decide solo — vale tanto para single-broker (Cocos) como multi-broker. Se
    # decide ANTES de validar para que validate omita los chequeos de
    # broker-currency de las FX (el persister las rerutea al broker correcto).
    if not route_by_currency:
        for tx in normalized:
            bc = (user_brokers.get(tx.broker) or {}).get("currency")
            if bc != "ARS":
                continue
            if (tx.currency or "").upper() in ("USD", "USDT") or \
                    tx.operation_type in ("FX_ARS_TO_USD", "FX_USD_TO_ARS"):
                route_by_currency = True
                break

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

    # Flag informativo para el frontend (modo "varios brokers"). El auto-ruteo
    # por moneda ya se decidió arriba, antes de validar — vale para single y
    # multi-broker por igual.
    is_multi_broker = (broker_hint is None) and (
        len({t.broker for t in valid_txs}) > 1
    )

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

    # Fase 4: tc_blue stamp at write time
    tc_blue_at_import = _read_user_tc_blue(conn, uid)

    for tx in valid_txs:
        fp = _row_fingerprint(tx)
        if fp in existing_fingerprints:
            duplicate_row_indices.append(tx.row_index)
        gross_usd = _stamp_gross_amount_usd(tx.currency, tx.gross_amount, tc_blue_at_import)
        # Audit follow-up: ALSO populate the NormalizedTx in-memory para que el
        # persister (que consume estos NormalizedTx) tenga acceso al stamped USD
        # y lo use en `_apply_cash_flow`. Sin esto, persist re-convertía con
        # runtime tc_blue → drift potencial.
        tx.gross_amount_usd = gross_usd
        conn.execute(
            """INSERT INTO import_normalized_tx
               (batch_id, raw_row_id, date, broker, operation_type, asset_symbol, asset_name, asset_type,
                quantity, unit_price, gross_amount, fees, taxes, currency, settlement_currency, notes,
                fingerprint, gross_amount_usd, tc_compra)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (batch_id, raw_id_by_index[tx.row_index], tx.date, tx.broker, tx.operation_type,
             tx.asset_symbol, tx.asset_name, tx.asset_type,
             tx.quantity, tx.unit_price, tx.gross_amount,
             tx.fees, tx.taxes, tx.currency, tx.settlement_currency, tx.notes,
             fp, gross_usd, tx.tc_compra),
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

    # Aviso de re-import: si los brokers de este import YA tienen posiciones,
    # volver a importar puede DUPLICAR (ej. subir Órdenes y luego Resultados del
    # mismo broker, o reimportar el mismo archivo). El dedup por fila no atrapa el
    # caso de exports distintos del mismo portfolio (mismos trades, valores
    # distintos). El front muestra un aviso para que el user revierta el anterior
    # si está cargando lo mismo de nuevo.
    _import_brokers = {(tx.broker or "").strip() for tx in normalized if tx.broker}
    _existing_brokers = {b for (b, _a) in existing_pos.keys()}
    preview_payload["brokers_already_imported"] = sorted(
        b for b in _import_brokers if b and b in _existing_brokers
    )

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
                "balance": _snap_cash(balance),
            }
            for (broker, currency), balance in sorted(sim.final_balances.items())
        ]
        # Higiene de re-import (#3): el `projected_cash` de arriba está APILADO
        # sobre el cash que ya tenías en la DB (starting_cash). Si esto es un
        # re-import del mismo portfolio (no un alta incremental), ese apilado
        # distorsiona el resultado — arrancás de un saldo viejo en vez de cero.
        # Exponemos también el cash STANDALONE (este archivo SOLO, desde cero)
        # para que el front pueda mostrar "este archivo, por sí solo, deja tu
        # cash en X" y el usuario detecte que está re-importando sobre data vieja
        # (combinado con `brokers_already_imported`). No cambia la persistencia.
        preview_payload["projected_cash_standalone"] = [
            {
                "broker": broker,
                "currency": currency,
                "balance": _snap_cash(balance - starting_cash.get((broker, currency), 0.0)),
            }
            for (broker, currency), balance in sorted(sim.final_balances.items())
        ]

    # Seed suggestions: si el CSV referencia activos sin posición previa
    # (sells que consumen stock no presente en el archivo) o tiene overdrafts
    # sobre cash que no fue depositado antes, ofrecemos al usuario cargar un
    # "estado inicial". El seed se aplica al confirmar y precisa cost basis
    # real para esas posiciones (sin seed, el persister auto-sintetiza al
    # precio de venta → P&L = 0 sobre la porción faltante).
    #
    # Detección de stock shortfall: ya no viene del validator (que ahora
    # acepta todos los sells — history-as-truth). Re-simulamos acá usando
    # `valid_txs` + `existing_pos` y registramos filas que dejarían stock
    # negativo. Solo se usa para alimentar las sugerencias; no bloquea.
    err_insufficient_indices: set = set()
    if valid_txs:
        from .schema import OP_BUY as _OP_BUY, OP_SELL as _OP_SELL
        sim_qty: Dict[Tuple[str, str], float] = dict(existing_pos)
        sorted_for_sim = sorted(valid_txs, key=lambda t: (
            t.date, 0 if t.operation_type == _OP_BUY else 1, t.row_index,
        ))
        for tx in sorted_for_sim:
            if tx.operation_type == _OP_BUY:
                k = (tx.broker, tx.asset_symbol or "")
                sim_qty[k] = sim_qty.get(k, 0.0) + (tx.quantity or 0)
            elif tx.operation_type == _OP_SELL:
                k = (tx.broker, tx.asset_symbol or "")
                avail = sim_qty.get(k, 0.0)
                if (tx.quantity or 0) > avail + 1e-9:
                    err_insufficient_indices.add(tx.row_index)
                sim_qty[k] = sim_qty.get(k, 0.0) - (tx.quantity or 0)

    # build_suggestions detecta el caso vía `val_errors` con code INSUFFICIENT_STOCK,
    # pero ya no los emitimos. Fabricamos un RowError shim para no tocar la API
    # del seed module (que es estable y la usan otros tests).
    from .schema import RowError as _RowError
    shim_errors = list(val_errors) + [
        _RowError(ridx, "cantidad", "INSUFFICIENT_STOCK", "")
        for ridx in err_insufficient_indices
    ]
    cash_warnings_obj = sim.warnings if valid_txs else []
    # final_balance para el back-cálculo del seed (front: deposit = saldo_hoy − F).
    # Tiene que ser el saldo que el CSV produce ARRANCANDO DE CERO, NO el que
    # incluye el cash que el user ya tenía en la DB (starting_cash) — el depósito
    # sintético del seed es justamente lo que crea ese cash pre-CSV. Standalone =
    # sim.final − starting_cash = Σ(deltas del CSV). Sin esto, en re-imports /
    # "Editar y rehacer" (broker con cash previo) el back-cálculo daba mal.
    standalone_final = (
        {k: _snap_cash(float(v) - float(starting_cash.get(k, 0.0))) for k, v in sim.final_balances.items()}
        if valid_txs else {}
    )
    seed_suggestions = _seed.build_suggestions(
        valid_txs=valid_txs,
        val_errors=shim_errors,
        cash_warnings=cash_warnings_obj,
        user_brokers=user_brokers,
        existing_positions=existing_pos,
        all_normalized=normalized,
        final_balances=standalone_final,
    )
    if seed_suggestions:
        seed_suggestions = _seed.enrich_with_sell_assets(
            seed_suggestions,
            all_normalized=normalized,
            err_row_indices=err_insufficient_indices,
        )
        # Asegurar final_balance para TODO broker del seed — incluidos los
        # sell-only que enrich agrega SIN cash_overdraft. Sin esto el front
        # recibía F=undefined y back-calculaba deposit=saldo_hoy, ignorando los
        # deltas de cash del CSV de ese broker (p.ej. el proceeds de la venta).
        for b in seed_suggestions.get("brokers", []):
            fb = b.setdefault("final_balance", {})
            for (br, cur), val in standalone_final.items():
                if br == b.get("broker") and cur not in fb:
                    fb[cur] = round(float(val), 2)
        preview_payload["seed_suggestions"] = seed_suggestions

    # Posiciones que entraron por transferencia de securities SIN precio en el
    # CSV (caso típico: migración TD Ameritrade → Schwab, muy común en usuarios
    # AR). El parser las marcó cost_basis_pending y el validator las derivó acá.
    # Las ofrecemos como seed-assets con cantidad EXACTA para que el user cargue
    # el cost basis → de ahí sale la compra sintética. Sin esto, una posición
    # que llegó 100% por transferencia (sin un Buy posterior) se perdía.
    transfer_assets = [
        (tx.broker, tx.asset_symbol, float(tx.quantity or 0))
        for tx in normalized
        if getattr(tx, "cost_basis_pending", False)
        and tx.asset_symbol and (tx.quantity or 0) > 0
    ]
    if transfer_assets:
        if not seed_suggestions:
            _dates = [t.date for t in normalized if t.date]
            _earliest = min(_dates) if _dates else None
            seed_suggestions = {
                "needed": True,
                "earliest_csv_date": _earliest,
                "seed_date": _seed._minus_one_day(_earliest) if _earliest else None,
                "brokers": [],
                "totals": {"sell_errors": 0, "cash_warnings": 0},
            }
        _seed.enrich_with_transfer_assets(
            seed_suggestions, transfers=transfer_assets, user_brokers=user_brokers,
        )
        for b in seed_suggestions.get("brokers", []):
            fb = b.setdefault("final_balance", {})
            for (br, cur), val in standalone_final.items():
                if br == b.get("broker") and cur not in fb:
                    fb[cur] = round(float(val), 2)
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


def store_preview_txs(conn, uid: int, *, broker: str, parser_format: str,
                      file_name: str, txs: List[NormalizedTx]) -> str:
    """Guarda una lista de NormalizedTx YA construidas como un batch en estado
    'preview' (import_batches + import_raw_rows + import_normalized_tx) — igual que
    run_preview pero SIN parsear/normalizar/validar. Lo usa el flujo de Tenencia
    (las seed-txs ya vienen armadas por `tenencia.build_tenencia_seed_txs`). El
    `load_session_for_confirm` + el confirm EXISTENTE las aplican sin cambios.
    Devuelve el batch_id (== session_id). Idempotente por hash de fingerprints."""
    cleanup_stale_previews(conn)
    batch_id = _new_id()
    tc_blue = _read_user_tc_blue(conn, uid)
    fh = _file_hash(("tenencia|" + "|".join(_row_fingerprint(t) for t in txs)).encode("utf-8"))
    n = len(txs)
    conn.execute(
        """INSERT INTO import_batches
           (id, user_id, broker, parser_format, file_name, file_hash,
            total_rows, valid_rows, invalid_rows, status, route_by_currency)
           VALUES (?,?,?,?,?,?,?,?,?, 'preview', 0)""",
        (batch_id, uid, broker, parser_format, file_name, fh, n, n, 0))
    for tx in txs:
        cur = conn.execute(
            """INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status, errors_json)
               VALUES (?,?,?, 'valid', NULL)""",
            (batch_id, tx.row_index, json.dumps(
                {"asset": tx.asset_symbol, "op": tx.operation_type,
                 "qty": tx.quantity, "price": tx.unit_price, "notes": tx.notes},
                ensure_ascii=False)))
        raw_id = cur.lastrowid
        gross_usd = _stamp_gross_amount_usd(tx.currency, tx.gross_amount, tc_blue)
        tx.gross_amount_usd = gross_usd
        conn.execute(
            """INSERT INTO import_normalized_tx
               (batch_id, raw_row_id, date, broker, operation_type, asset_symbol, asset_name, asset_type,
                quantity, unit_price, gross_amount, fees, taxes, currency, settlement_currency, notes,
                fingerprint, gross_amount_usd, transfer_out, tc_compra)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (batch_id, raw_id, tx.date, tx.broker, tx.operation_type,
             tx.asset_symbol, tx.asset_name, tx.asset_type,
             tx.quantity, tx.unit_price, tx.gross_amount,
             tx.fees, tx.taxes, tx.currency, tx.settlement_currency, tx.notes,
             _row_fingerprint(tx), gross_usd,
             1 if getattr(tx, "transfer_out", False) else 0,
             getattr(tx, "tc_compra", None)))
    return batch_id


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
            # Fase 4: preservar el USD stamped en el round-trip a la DB. Sin esto
            # el persister lo veía None y reconvertía a tc_blue runtime (drift, y
            # con un tc_blue stale → "capital aportado" fantasma). El stamp manda.
            gross_amount_usd=(r["gross_amount_usd"] if "gross_amount_usd" in r.keys() else None),
            fees=r["fees"] or 0.0,
            taxes=r["taxes"] or 0.0,
            currency=r["currency"],
            settlement_currency=r["settlement_currency"],
            notes=r["notes"],
            # transfer_out debe sobrevivir el round-trip a la DB: el persister lo
            # honra (cierra el lote A COSTO, P&L 0, sin cash) en el confirm ANTES del
            # rebuild. Sin esto, una VENTA de ajuste de tenencia (precio 0) bookeaba
            # una pérdida fantasma en el persist, que sólo el rebuild posterior
            # corregía → si el rebuild fallaba, quedaba la pérdida. Es una columna
            # de import_normalized_tx (default 0 para filas viejas / no-tenencia).
            transfer_out=bool(r["transfer_out"]) if "transfer_out" in r.keys() else False,
            # tc_compra debe sobrevivir el round-trip a la DB igual que
            # transfer_out: el confirm rehidrata desde import_normalized_tx (no
            # de la lista en memoria) y NO hay re-derivación posible (a
            # diferencia de transfer_out) → si no se persiste+rehidrata, la
            # compra de CEDEAR pierde el dato antes de _persist_buy.
            tc_compra=r["tc_compra"] if "tc_compra" in r.keys() else None,
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
    # Fase 4: tc_blue stamp at write time
    tc_blue_at_confirm = _read_user_tc_blue(conn, uid)
    for tx in valid_txs:
        fp = _row_fingerprint(tx)
        gross_usd = _stamp_gross_amount_usd(tx.currency, tx.gross_amount, tc_blue_at_confirm)
        # Audit follow-up: stamp también en el NormalizedTx in-memory para que
        # el persister lo use en `_apply_cash_flow` (consistencia DB ↔ memory).
        tx.gross_amount_usd = gross_usd
        conn.execute(
            """INSERT INTO import_normalized_tx
               (batch_id, raw_row_id, date, broker, operation_type, asset_symbol, asset_name, asset_type,
                quantity, unit_price, gross_amount, fees, taxes, currency, settlement_currency, notes,
                fingerprint, gross_amount_usd, tc_compra)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (session_id, raw_id_by_index[tx.row_index], tx.date, tx.broker, tx.operation_type,
             tx.asset_symbol, tx.asset_name, tx.asset_type,
             tx.quantity, tx.unit_price, tx.gross_amount,
             tx.fees, tx.taxes, tx.currency, tx.settlement_currency, tx.notes,
             fp, gross_usd, getattr(tx, "tc_compra", None)),
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
        # Solo incluimos parsers soportados — los que están en desarrollo no
        # aparecen ni como "próximamente". Si volvemos a habilitar uno, flipear
        # is_supported a True en la clase del parser y aparece solo.
        if not p.is_supported:
            continue
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
    # Orden: generic primero, después binance, después el resto
    order = {"generic": 0, "binance": 1, "balanz": 2, "cocos": 3}
    return sorted(grouped.values(), key=lambda g: order.get(g["platform"], 99))
