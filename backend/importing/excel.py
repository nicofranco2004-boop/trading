"""Lectura de archivos Excel (.xlsx) en el pipeline de import.

Algunos brokers (ej. Bull Market) solo exportan Excel, no CSV. En vez de
escribir parsers que entiendan binario, convertimos el .xlsx a texto CSV acá,
y los parsers existentes (text-based) lo procesan igual que un CSV.

Diseño:
  • is_xlsx(bytes): detección por magic bytes (xlsx = zip → 'PK\\x03\\x04').
    Robusto: no depende del filename.
  • xlsx_to_csv(bytes): primera hoja → CSV (coma-separated). Fechas a ISO
    (YYYY-MM-DD) para que los parsers no tengan que adivinar formato; números
    tal cual los da openpyxl (point-decimal). Filas 100% vacías se descartan.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, date


def is_xlsx(file_bytes: bytes) -> bool:
    """True si los bytes son un .xlsx (archivo zip con firma PK\\x03\\x04).
    Los .xls viejos (BIFF) NO matchean — solo soportamos xlsx."""
    return bool(file_bytes) and file_bytes[:4] == b"PK\x03\x04"


def _cell_to_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        # ISO date — los parsers la leen sin ambigüedad de formato.
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float):
        # Evita notación científica para números grandes; point-decimal.
        return repr(v)
    return str(v).strip()


def xlsx_to_csv(file_bytes: bytes) -> str:
    """Convierte la PRIMERA hoja de un .xlsx a texto CSV (coma-separated).

    Levanta ValueError con mensaje claro si el archivo no se puede abrir
    (el caller lo traduce a un error de import amigable)."""
    try:
        import openpyxl
    except ImportError as ex:  # pragma: no cover
        raise ValueError("Falta la librería openpyxl para leer Excel.") from ex

    try:
        wb = openpyxl.load_workbook(
            io.BytesIO(file_bytes), data_only=True, read_only=True
        )
    except Exception as ex:
        raise ValueError(
            "No pudimos abrir el Excel. Verificá que sea un .xlsx válido."
        ) from ex

    try:
        if not wb.worksheets:
            raise ValueError("El Excel no tiene hojas.")
        ws = wb.worksheets[0]
        buf = io.StringIO()
        writer = csv.writer(buf)
        wrote_any = False
        for row in ws.iter_rows(values_only=True):
            cells = [_cell_to_str(v) for v in row]
            # Descartar filas completamente vacías (separadores, footer en blanco).
            if any(c.strip() for c in cells):
                writer.writerow(cells)
                wrote_any = True
        if not wrote_any:
            raise ValueError("La primera hoja del Excel está vacía.")
        return buf.getvalue()
    finally:
        wb.close()


def to_csv_text(file_bytes: bytes) -> str:
    """Devuelve texto CSV a partir de bytes que pueden ser .xlsx o un CSV ya
    en texto. Único punto de entrada para el pipeline: 'dame esto como CSV'.

    - xlsx → convierte la primera hoja.
    - CSV  → decodifica (utf-8-sig, fallback latin-1).
    Levanta ValueError si no se puede interpretar.
    """
    if is_xlsx(file_bytes):
        return xlsx_to_csv(file_bytes)
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return file_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("No pudimos decodificar el archivo. Probá guardarlo como UTF-8 o .xlsx.")
