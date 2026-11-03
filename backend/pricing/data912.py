"""Historia diaria de data912: la bajada, en UN solo lugar.

data912 tiene, además del precio en vivo (`/live/...`, ver `_fetch_data912_bonds`
en main.py), una vela por rueda desde 2021 para bonos, acciones y CEDEARs:

    GET https://data912.com/historical/{tipo}/{papel}
    tipo ∈ {"bonds", "stocks", "cedears"}
    → [{"date": "2026-10-30", "o", "h", "l", "c", "v", "dr", "sa"}, ...]

Si no tiene el papel contesta un objeto de error en vez de la lista (medido
2026-11-03: `{"Error": "Nahh no tengo ese ticker loko"}` para ONs como PNDCO y
para letras como S30N6 — la historia de bonos cubre soberanos, CER y BOPREAL,
no `arg_corp` ni `arg_notes`).

UNIDAD: la misma que el feed en vivo. Los soberanos vienen por cada 100
nominales (AL35 = 105.900 pesos el 30/10/2026) y los CER por cada 1 (TX26 =
765,9). Quien lo use para valuar pasa el número por `main._escala_bono`, la
misma regla que el precio en vivo.

Antes había tres copias de esta bajada (el chat, la liquidez del papel y los
cambios de ratio), cada una con su forma de decidir "no hay datos".
"""
from __future__ import annotations

import requests

URL = "https://data912.com/historical/{tipo}/{papel}"


def filas(tipo: str, papel: str, timeout: float = 10) -> list:
    """Las velas diarias de `papel`, de la más vieja a la más nueva. [] si data912
    no tiene ese papel. Una falla de red NO se traga: sube como excepción, así
    quien llama distingue "no hay historia" (definitivo) de "no contestó"
    (se vuelve a preguntar)."""
    r = requests.get(URL.format(tipo=tipo, papel=papel), timeout=timeout)
    if r.status_code != 200:
        return []
    datos = r.json()
    return datos if isinstance(datos, list) else []


def cierres(tipo: str, papel: str, timeout: float = 10) -> dict:
    """{fecha ISO: cierre} de las ruedas con cierre positivo. {} si no hay."""
    out = {}
    for f in filas(tipo, papel, timeout):
        try:
            c = float(f.get("c") or 0)
        except (TypeError, ValueError):
            continue
        if c > 0 and f.get("date"):
            out[str(f["date"])[:10]] = c
    return out
