"""Prueba el resumen de Mervall-E de la ficha con el modelo REAL sobre activos reales.

Arma los hechos con las velas guardadas en una COPIA de la base (nunca
backend/trading.db), llama a ai/resumen_tecnico.generar —el mismo camino que el
botón— e imprime el texto, los hechos, los tokens, el costo y la demora.

Uso (desde backend/):
    DB_PATH=<scratch>/x.db python3 scripts/probar_resumen_tecnico.py <copia.db> <.env> [salida.json]

La clave de Anthropic se lee del .env sin imprimirla.
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# activo, moneda, ¿acción argentina?, qué es
ACTIVOS = [
    ("AAPL", "usd", False, "acción de EE.UU."),
    ("NVDA", "usd", False, "acción de EE.UU."),
    ("TSLA", "usd", False, "acción de EE.UU."),
    ("MSFT", "usd", False, "acción de EE.UU."),
    ("MELI", "usd", False, "acción de EE.UU."),
    ("AAPL", "ars", False, "CEDEAR en pesos"),
    ("KO", "ars", False, "CEDEAR en pesos"),
    ("GGAL", "ars", True, "acción argentina en pesos"),
    ("YPFD", "ars", True, "acción argentina en pesos"),
    ("PAMP", "usd", True, "acción argentina en dólares (BYMA ÷ MEP)"),
    ("BTC", "usd", False, "cripto"),
]


def main():
    base, env = sys.argv[1], sys.argv[2]
    salida = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    if Path(base).resolve() == (BACKEND / "trading.db").resolve():
        sys.exit("Usá una COPIA de la base, no backend/trading.db")
    for linea in Path(env).read_text().splitlines():
        if linea.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = linea.split("=", 1)[1].strip().strip('"').strip("'")
    import logging
    logging.basicConfig(level=logging.WARNING, format="   [%(name)s] %(message)s")
    logging.getLogger("ai.resumen_tecnico").setLevel(logging.INFO)
    import tecnico
    from ai import resumen_tecnico
    from ai.asset_names import asset_name

    conn = sqlite3.connect(base)
    conn.row_factory = sqlite3.Row
    filas, total = [], 0.0
    for sim, mon, local, que in ACTIVOS:
        ficha = tecnico.para_la_ficha(conn, sim, mon, local)
        hechos = tecnico.hechos_para_el_resumen(ficha, asset_name(sim) or sim)
        if not hechos:
            print(f"{sim} {mon}: sin datos")
            continue
        t0 = time.time()
        try:
            r = resumen_tecnico.generar(hechos)
            error = None
        except resumen_tecnico.NoSePudo as ex:
            r, error = ex.gasto, str(ex)
        seg = time.time() - t0
        costo = (r or {}).get("cost_usd_cents", 0) / 10000
        total += costo
        fila = {"activo": sim, "moneda": mon, "que": que, "texto": (r or {}).get("texto"),
                "error": error, "palabras": (r or {}).get("palabras"), "llamadas": (r or {}).get("llamadas"),
                "entrada": (r or {}).get("input_tokens"), "salida": (r or {}).get("output_tokens"),
                "costo_usd": round(costo, 5), "segundos": round(seg, 1), "hechos": hechos}
        filas.append(fila)
        print(f"\n── {sim} {mon} ({que}) · {fila['palabras']} palabras · {fila['llamadas']} llamada(s) · "
              f"{fila['entrada']}+{fila['salida']} tokens · US$ {costo:.5f} · {seg:.1f} s")
        print(fila["texto"] or f"NO SE PUDO: {error}")
    print(f"\nTotal: US$ {total:.4f} en {len(filas)} resúmenes")
    if salida:
        salida.write_text(json.dumps(filas, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
