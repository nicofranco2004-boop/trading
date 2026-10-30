"""Prueba el resumen de Mervall-E de la ficha con el modelo REAL sobre activos reales.

Arma los hechos con las velas guardadas en una COPIA de la base (nunca
backend/trading.db) con ai/resumen_tecnico_hechos, llama a
ai/resumen_tecnico.generar —el mismo camino que el botón, con el pedido de
ai/resumen_tecnico_pedido.txt— e imprime el texto, los tokens, el costo y la demora.

Uso (desde backend/), con DB_PATH apuntando a la COPIA (entra por get_db, como la app):
    DB_PATH=<copia.db> python3 scripts/probar_resumen_tecnico.py <.env> [salida.json]

La clave de Anthropic se lee del .env sin imprimirla.
"""
import json
import os
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
    env = sys.argv[1]
    salida = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    base = os.environ.get("DB_PATH")
    if not base or Path(base).resolve() == (BACKEND / "trading.db").resolve():
        sys.exit("Poné DB_PATH=<una COPIA de la base>; nunca backend/trading.db")
    for linea in Path(env).read_text().splitlines():
        if linea.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = linea.split("=", 1)[1].strip().strip('"').strip("'")
    import logging
    logging.basicConfig(level=logging.WARNING, format="   [%(name)s] %(message)s")
    logging.getLogger("ai.resumen_tecnico").setLevel(logging.INFO)
    import main
    import tecnico
    from ai import resumen_tecnico
    from ai.asset_names import asset_name
    from ai.resumen_tecnico_hechos import para_el_resumen

    filas, total = [], 0.0
    for sim, mon, local, que in ACTIVOS:
        with main.db_abierta() as conn:
            ficha = tecnico.para_la_ficha(conn, sim, mon, local)
        hechos = para_el_resumen(ficha, asset_name(sim) or sim)
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
