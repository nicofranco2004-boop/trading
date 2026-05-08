"""Column mapper para CSVs con formato arbitrario.

Permite que el usuario importe un CSV con headers cualquiera (ej.: export de
IBKR, Cocos, un Excel propio) sin tener que reescribir el archivo. El usuario
decide qué columna del CSV corresponde a cada campo interno de Rendi (fecha,
tipo, broker, activo, etc.). Como apoyo, hacemos auto-detección heurística
por nombres habituales en castellano e inglés.

Flujo:
  1. `inspect_csv` lee headers + primeras filas + sugiere un mapping.
  2. El usuario revisa/ajusta el mapping en el wizard.
  3. `apply_mapping` recibe el mapping confirmado y traduce el CSV a las
     columnas internas de Rendi (las que espera RendiGenericParser).
  4. El pipeline normal (parse → normalize → validate → preview) corre
     contra esas columnas internas.

Diseño: la "traducción" produce un CSV intermedio con headers internos. Lo
generamos en memoria y se lo pasamos a RendiGenericParser sin tocarlo. Así
toda la lógica de parsing/normalización/validación se reusa.
"""
from __future__ import annotations
import csv
import io
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# Campos internos de Rendi y metadata para la UI del mapper.
# `allow_default` indica que si el CSV del usuario no tiene una columna que
# corresponda, puede definir un valor fijo para todas las filas (ej.: "todas
# las filas son del broker IBKR").
RENDI_FIELDS: List[Dict[str, Any]] = [
    {"id": "fecha",       "label": "Fecha",       "required": True,  "allow_default": False},
    {"id": "tipo",        "label": "Tipo",        "required": True,  "allow_default": True},
    {"id": "broker",      "label": "Broker",      "required": True,  "allow_default": True},
    {"id": "activo",      "label": "Activo",      "required": False, "allow_default": False},
    {"id": "cantidad",    "label": "Cantidad",    "required": False, "allow_default": False},
    {"id": "precio",      "label": "Precio",      "required": False, "allow_default": False},
    {"id": "monto",       "label": "Monto",       "required": False, "allow_default": False},
    {"id": "monto_usd",   "label": "Monto USD",   "required": False, "allow_default": False},
    {"id": "tc",          "label": "Tipo de cambio", "required": False, "allow_default": False},
    {"id": "comisiones",  "label": "Comisiones",  "required": False, "allow_default": False},
    {"id": "moneda",      "label": "Moneda",      "required": False, "allow_default": True},
    {"id": "notas",       "label": "Notas",       "required": False, "allow_default": False},
]


# Sinónimos por campo. Los headers se normalizan con `_norm` (lowercase + reemplaza
# `_` y `-` por espacios), así que estas listas usan espacios. Un header como
# "trade_date" o "trade-date" matchea contra "trade date".
_SYNONYMS: Dict[str, List[str]] = {
    "fecha":       ["fecha", "date", "trade date", "transaction date", "exec date",
                    "execution date", "settlement date", "exec time", "fecha op",
                    "fecha operacion", "día", "dia", "datetime", "timestamp"],
    "tipo":        ["tipo", "type", "action", "operation type", "transaction type",
                    "trade type", "side", "op type", "operation", "operación",
                    "operacion", "movement", "movimiento", "kind"],
    "broker":      ["broker", "account", "cuenta", "source", "exchange", "platform",
                    "agente", "alyc"],
    "activo":      ["activo", "symbol", "ticker", "asset", "asset symbol",
                    "asset ticker", "security", "security id", "instrument",
                    "instrumento", "especie", "code", "código", "codigo"],
    "cantidad":    ["cantidad", "quantity", "qty", "units", "shares", "size",
                    "volume", "volumen", "nominales"],
    "precio":      ["precio", "price", "unit price", "unit cost", "exec price",
                    "execution price", "fill price", "avg price", "average price",
                    "promedio", "precio unitario"],
    "monto":       ["monto", "amount", "gross amount", "net amount", "total amount",
                    "transaction amount", "transaction value", "total", "gross",
                    "value", "importe", "valor", "monto bruto", "monto total",
                    "monto ars", "amount ars", "ars amount", "valor ars",
                    "importe ars"],
    "monto_usd":   ["monto usd", "amount usd", "usd amount", "valor usd",
                    "gross amount usd", "amount in usd"],
    "tc":          ["tc", "tipo de cambio", "exchange rate", "fx rate",
                    "tipo cambio", "rate", "tasa", "fx"],
    "comisiones":  ["comisiones", "commission", "fee", "fees", "comm", "comisión",
                    "comision", "costos", "charges", "broker fee"],
    "moneda":      ["moneda", "currency", "ccy", "denomination", "settlement currency",
                    "moneda csv", "currency csv", "row currency"],
    "notas":       ["notas", "notes", "description", "descripción", "descripcion",
                    "memo", "comment", "comentario", "detalle"],
}


@dataclass
class Mapping:
    """Mapeo de campos Rendi → header del CSV del usuario.
    Si un campo está en `defaults`, se aplica ese valor a TODAS las filas
    (en vez de leer una columna)."""
    columns: Dict[str, str] = field(default_factory=dict)   # {rendi_field: user_header}
    defaults: Dict[str, str] = field(default_factory=dict)  # {rendi_field: fixed_value}

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "Mapping":
        if not data:
            return cls()
        return cls(
            columns={k: str(v) for k, v in (data.get("columns") or {}).items() if v},
            defaults={k: str(v) for k, v in (data.get("defaults") or {}).items() if v not in (None, "")},
        )


def _norm(s: str) -> str:
    """Normaliza un header para matching contra sinónimos.
    Tolerante a underscores y guiones (los trata como espacios), así
    'unit_price' / 'unit-price' / 'unit price' matchean igual."""
    return (s or "").strip().lower().lstrip("﻿").replace("_", " ").replace("-", " ")


def autodetect_mapping(headers: List[str]) -> Mapping:
    """Sugerencia inicial: matchea cada campo Rendi contra los headers del usuario
    usando los sinónimos. Si hay match, lo asigna; si no, queda sin asignar.
    Garantiza que un mismo header del usuario no se asigne a dos campos Rendi."""
    norm_to_orig = {_norm(h): h for h in headers}
    used: set = set()
    columns: Dict[str, str] = {}
    for rendi_field, syns in _SYNONYMS.items():
        for syn in syns:
            key = _norm(syn)
            if key in norm_to_orig and key not in used:
                columns[rendi_field] = norm_to_orig[key]
                used.add(key)
                break
    return Mapping(columns=columns, defaults={})


def inspect_csv(content: str, *, sample_size: int = 5) -> Dict[str, Any]:
    """Lee headers + las primeras filas del CSV y devuelve metadata para la UI.
    Auto-detecta el separador. Tolerante a errores: si algo falla, devuelve
    el error en `error` y headers vacíos."""
    if content.startswith("﻿"):
        content = content[1:]
    try:
        sample = content[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(content), dialect=dialect)
        headers = list(reader.fieldnames or [])
        sample_rows: List[Dict[str, Any]] = []
        for i, row in enumerate(reader):
            if i >= sample_size:
                break
            sample_rows.append({k: (v if v is not None else "") for k, v in row.items()})
    except Exception as ex:
        return {"error": f"No pudimos leer el archivo: {ex}", "headers": [], "sample_rows": [], "rendi_fields": RENDI_FIELDS, "suggested_mapping": {"columns": {}, "defaults": {}}}

    suggestion = autodetect_mapping(headers)
    return {
        "headers": headers,
        "sample_rows": sample_rows,
        "rendi_fields": RENDI_FIELDS,
        "suggested_mapping": {"columns": suggestion.columns, "defaults": suggestion.defaults},
    }


def apply_mapping(content: str, mapping: Mapping) -> Tuple[str, Optional[str]]:
    """Genera un CSV intermedio con los headers internos de Rendi
    (`fecha`, `tipo`, `broker`, `activo`, ...). Acepta el CSV original más un
    Mapping. Devuelve (csv_text, error_msg). El CSV resultante se le pasa a
    RendiGenericParser sin modificaciones.

    Reglas:
    - Para cada campo Rendi configurado en `mapping.columns`, leemos esa
      columna del original.
    - Para cada campo en `mapping.defaults`, escribimos el valor fijo en
      todas las filas (sobrescribe `columns` si ambos están).
    - Validamos que los campos `required` con allow_default=False tengan una
      columna mapeada. Si falta, devolvemos error.
    - Validamos que los headers referenciados en columns existan en el CSV.
    """
    if content.startswith("﻿"):
        content = content[1:]

    # Validar que campos required estén cubiertos
    for f in RENDI_FIELDS:
        if not f["required"]:
            continue
        has_col = f["id"] in mapping.columns
        has_def = f["id"] in mapping.defaults
        if not has_col and not has_def:
            return "", f"Falta mapear el campo obligatorio '{f['label']}'."
        if has_col and not has_def and not f.get("allow_default", False):
            # required + only column allowed — must have column
            pass

    try:
        sample = content[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(content), dialect=dialect)
        original_headers = list(reader.fieldnames or [])

        # Validar que los headers referenciados existan
        for rendi_field, user_col in mapping.columns.items():
            if user_col not in original_headers:
                return "", f"La columna '{user_col}' (mapeada a {rendi_field}) no existe en el archivo."

        # Generar CSV interno
        out = io.StringIO()
        rendi_headers = [f["id"] for f in RENDI_FIELDS]
        writer = csv.DictWriter(out, fieldnames=rendi_headers)
        writer.writeheader()

        for row in reader:
            # Skip filas completamente vacías
            if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
                continue
            new_row: Dict[str, str] = {h: "" for h in rendi_headers}
            for rendi_field, user_col in mapping.columns.items():
                if rendi_field in rendi_headers:
                    val = row.get(user_col)
                    new_row[rendi_field] = (val or "").strip() if isinstance(val, str) else (str(val) if val is not None else "")
            for rendi_field, fixed in mapping.defaults.items():
                if rendi_field in rendi_headers and fixed:
                    # default sobrescribe solo si la columna mapeada vino vacía
                    if not new_row[rendi_field]:
                        new_row[rendi_field] = fixed
            writer.writerow(new_row)
        return out.getvalue(), None
    except Exception as ex:
        return "", f"Error al aplicar el mapeo: {ex}"
