"""Pone al día la lista de empresas del S&P 500 que mide el termómetro.

De dónde sale
─────────────
La tabla «S&P 500 component stocks» de Wikipedia
(https://en.wikipedia.org/wiki/List_of_S%26P_500_companies): el símbolo, el
nombre y el sector (GICS, la clasificación que usa el propio S&P). S&P Dow
Jones no publica la lista gratis; Wikipedia la mantiene al día con cada cambio
del índice y cita la fuente de cada uno.

Cada cuánto
───────────
El S&P rebalancea cada trimestre (tercer viernes de marzo, junio, septiembre y
diciembre) y cambia empresas sueltas cuando hay fusiones. Con correr esto una
vez por trimestre alcanza: una empresa que salió y sigue en la lista mueve el
termómetro en 1 de ~500 (0,2 %).

La app NUNCA lee Wikipedia: lee el archivo `home/sp500_constituyentes.json`
que deja este script, versionado en git. Si Wikipedia cambia el formato, falla
este script, no la app.

Uso
───
    python3 scripts/actualizar_sp500.py             # muestra qué entra y qué sale
    python3 scripts/actualizar_sp500.py --escribir  # además reescribe el archivo
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.request
from datetime import date

FUENTE = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
ARCHIVO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "home", "sp500_constituyentes.json")
# El sector GICS de Wikipedia → la clave de sector de Rendi (las de
# frontend/src/utils/assetSector.js, para que las palabras sean las mismas).
SECTORES = {
    "Information Technology": "tecnologia",
    "Communication Services": "comunicacion",
    "Consumer Discretionary": "consumo_disc",
    "Consumer Staples": "consumo_bas",
    "Health Care": "salud",
    "Financials": "financiero",
    "Energy": "energia",
    "Utilities": "utilities",
    "Industrials": "industria",
    "Materials": "materiales",
    "Real Estate": "inmobiliario",
}


def bajar() -> list:
    import pandas as pd
    pedido = urllib.request.Request(FUENTE, headers={"User-Agent": "Rendi/1.0 (lista del S&P 500)"})
    html = urllib.request.urlopen(pedido, timeout=30).read().decode("utf-8")
    tabla = pd.read_html(io.StringIO(html), attrs={"id": "constituents"})[0]
    out = []
    for _, r in tabla.iterrows():
        sector = SECTORES.get(str(r["GICS Sector"]).strip())
        if sector is None:
            raise SystemExit(f"Sector desconocido en Wikipedia: {r['GICS Sector']!r} ({r['Symbol']})")
        out.append({"symbol": str(r["Symbol"]).strip().upper(),
                    "nombre": str(r["Security"]).strip(), "sector": sector})
    if not 490 <= len(out) <= 510:
        raise SystemExit(f"La tabla trajo {len(out)} empresas: algo cambió en Wikipedia, no se escribe nada.")
    return sorted(out, key=lambda x: x["symbol"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--escribir", action="store_true", help="reescribe home/sp500_constituyentes.json")
    args = ap.parse_args(argv)
    nuevas = bajar()
    try:
        viejas = json.load(open(ARCHIVO, encoding="utf-8"))["empresas"]
    except FileNotFoundError:
        viejas = []
    antes = {e["symbol"]: e for e in viejas}
    ahora = {e["symbol"]: e for e in nuevas}
    entran = sorted(set(ahora) - set(antes))
    salen = sorted(set(antes) - set(ahora))
    cambian = sorted(s for s in set(ahora) & set(antes) if ahora[s]["sector"] != antes[s]["sector"])
    def _lista(xs):
        return "-" if not xs else (", ".join(xs[:30]) + (f" y {len(xs) - 30} más" if len(xs) > 30 else ""))
    print(f"{len(nuevas)} empresas. Entran: {_lista(entran)}. Salen: {_lista(salen)}. "
          f"Cambian de sector: {_lista(cambian)}")
    if args.escribir:
        # Una empresa por renglón: el diff de git del trimestre muestra justo
        # las que entraron y salieron.
        filas = ",\n".join("  " + json.dumps(e, ensure_ascii=False) for e in nuevas)
        with open(ARCHIVO, "w", encoding="utf-8") as f:
            f.write('{\n "fuente": %s,\n "bajada": "%s",\n "empresas": [\n%s\n ]\n}\n'
                    % (json.dumps(FUENTE), date.today().isoformat(), filas))
        print(f"Escrito {ARCHIVO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
