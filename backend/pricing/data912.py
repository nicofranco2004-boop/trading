"""Historia diaria de data912: la bajada, en UN solo lugar.

data912 tiene, además del precio en vivo (`/live/...`, ver `_fetch_data912_bonds`
en main.py), una vela por rueda desde 2021 para bonos, acciones y CEDEARs:

    GET https://data912.com/historical/{tipo}/{papel}
    tipo ∈ {"bonds", "stocks", "cedears"}
    → [{"date": "2026-10-30", "o", "h", "l", "c", "v", "dr", "sa"}, ...]

Si no tiene el papel contesta CON 200 un objeto de error en vez de la lista
(medido 2026-11-03: `{"Error": "Nahh no tengo ese ticker loko"}` para ONs como
PNDCO, para letras como S30N6 y para un ticker inventado — la historia de bonos
cubre soberanos, CER y BOPREAL, no `arg_corp` ni `arg_notes`). Un código que no
es 200 es otra cosa: una ruta que no existe o el servidor que no contesta.

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
    no tiene ese papel. Una falla NO se traga: sube como excepción, así quien
    llama distingue "no hay historia" (definitivo, se puede recordar) de "no
    contestó" (se vuelve a preguntar).

    ⚠️ Un código que no es 200 es una FALLA, no "no hay historia". data912
    avisa que no tiene un papel con 200; un 500, un 503 o un 429 es el servidor
    caído o limitando. Tomarlo como "no hay" dejaba al bono al costo todo el
    mes en la reconstrucción, que recuerda el "no hay" hasta que cambia el mes."""
    r = requests.get(URL.format(tipo=tipo, papel=papel), timeout=timeout)
    if r.status_code != 200:
        raise requests.HTTPError(f"data912 {tipo}/{papel}: {r.status_code}")
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
