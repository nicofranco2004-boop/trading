#!/usr/bin/env python3
"""Revalida la tabla de ratios de CEDEAR contra la lista oficial del emisor.

POR QUÉ EXISTE
──────────────
`frontend/src/utils/cedearRatio.js` guarda cuántos CEDEARs entran en una acción.
Ese número decide el dividendo que Rendi le anuncia al usuario: con el ratio mal,
el monto sale multiplicado (o dividido) por el error, sin ningún síntoma visible
— fue exactamente el bug del 2026-09-17, que un usuario detectó recién cuando
comparó contra el depósito real del broker (US$40 anunciados, US$0,70 cobrados).

Los ratios CAMBIAN: Comafi autoriza cambios de ratio cada tanto (GM pasó de 20 a
6, TWLO de 5 a 36). Una tabla hardcodeada sin forma de revalidarla es el mismo
bug esperando a volver. Esto lo convierte en un comando de un minuto.

USO
───
    python3 backend/scripts/check_cedear_ratios.py           # chequea y reporta
    python3 backend/scripts/check_cedear_ratios.py --write   # además corrige la tabla

Sale con código 1 si encuentra diferencias (sirve para CI o para un cron).

FUENTE
──────
Banco Comafi, emisor de los programas de CEDEARs — "LISTA TOTAL DE CEDEARS",
columna "Ratio Cedear/Acción ó ADR". Cubre acciones; NO trae ETFs (SPY, QQQ,
GLD…) ni los CEDEARs de otros emisores: ésos quedan fuera del chequeo y en la
tabla están marcados como medidos del precio.
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import urllib.request

COMAFI_XLSX = "https://www.comafi.com.ar/custodiaglobal/Multimedios/otros/14779.xlsx"
TABLA_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "..", "frontend", "src", "utils", "cedearRatio.js")

# El símbolo con el que Rendi guarda la posición no siempre es el que usa Comafi
# en su columna "Identificación Mercado".
ALIAS_A_COMAFI = {"BRK-B": "BRK/B", "BRKB": "BRK/B", "DISN": "DIS", "NOKA": "NOK"}


def parse_ratio(v) -> float | None:
    """'4:1' → 4 · '15 : 1' → 15 · '1 :4' → 0.25 · '3.1' → 3 (punto por dos puntos).

    El '.' como separador aparece en 6 filas de la lista real; tratarlo como
    decimal daría 3,1 en vez de 3:1.
    """
    m = re.match(r"^\s*([\d.,]+)\s*[:.]\s*([\d.,]+)\s*$", str(v).strip())
    if not m:
        return None
    a = float(m.group(1).replace(",", "."))
    b = float(m.group(2).replace(",", "."))
    return a / b if a > 0 and b > 0 else None


def _descargar(url: str) -> bytes:
    """Baja el archivo. Cae a curl si el stack SSL de Python no llega.

    El Python 3.9 que trae macOS está compilado contra LibreSSL 2.8.3 y el
    servidor de Comafi lo rechaza (TLSV1_ALERT_PROTOCOL_VERSION). curl usa el
    stack del sistema y sí negocia, así que el script corre igual en la máquina
    de desarrollo y en un Linux con OpenSSL moderno.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except Exception:
        import subprocess
        out = subprocess.run(["curl", "-sL", "--max-time", "60",
                              "-A", "Mozilla/5.0", url],
                             capture_output=True, check=True)
        if not out.stdout:
            raise RuntimeError("descarga vacía")
        return out.stdout


def bajar_oficial(url: str = COMAFI_XLSX) -> dict[str, tuple[float, str]]:
    """{ticker: (ratio, nombre del programa)} de la lista publicada por el emisor."""
    import openpyxl  # dependencia ya declarada en requirements.txt

    blob = _descargar(url)
    ws = openpyxl.load_workbook(io.BytesIO(blob), data_only=True).active
    out: dict[str, tuple[float, str]] = {}
    for row in ws.iter_rows(min_row=9, values_only=True):
        if not row or len(row) < 8 or not row[2] or row[7] is None:
            continue
        ratio = parse_ratio(row[7])
        if ratio is not None:
            out[str(row[2]).strip().upper()] = (ratio, str(row[1] or "").strip())
    return out


def leer_tabla_js(path: str = TABLA_JS) -> tuple[dict[str, float], str, tuple[int, int]]:
    """Lee CEDEAR_RATIOS del módulo. Devuelve (tabla, fuente completa, (ini, fin))."""
    src = open(path, encoding="utf-8").read()
    ini = src.index("export const CEDEAR_RATIOS = {") + len("export const CEDEAR_RATIOS = {")
    fin = src.index("\n}", ini)
    cuerpo = re.sub(r"//.*", "", src[ini:fin])
    tabla = {}
    for k, v in re.findall(r"'?([A-Z0-9\-.]+)'?\s*:\s*([0-9]+(?:/[0-9]+)?)", cuerpo):
        num, _, den = v.partition("/")
        tabla[k] = float(num) / float(den) if den else float(num)
    return tabla, src, (ini, fin)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                    help="corrige en cedearRatio.js los ratios que difieren de la oficial")
    args = ap.parse_args()

    try:
        oficial = bajar_oficial()
    except Exception as ex:                                   # red caída, URL movida
        print(f"No se pudo bajar la lista de Comafi: {ex}")
        print("Si la URL cambió, buscala en comafi.com.ar/custodiaglobal/programas.aspx")
        return 2
    tabla, src, (ini, fin) = leer_tabla_js()
    print(f"oficial (Comafi): {len(oficial)} ratios · tabla de Rendi: {len(tabla)}")

    diferentes, sin_oficial = [], []
    for k, mio in sorted(tabla.items()):
        hit = oficial.get(ALIAS_A_COMAFI.get(k, k))
        if hit is None:
            sin_oficial.append(k)
        elif abs(mio - hit[0]) > 1e-6:
            diferentes.append((k, mio, hit[0], hit[1]))

    # Los que la oficial trae y nosotros ni tenemos: sin ratio no se publica monto,
    # así que no es un bug — pero es cobertura que estamos dejando sobre la mesa.
    faltantes = [k for k in oficial if k not in tabla and k not in ALIAS_A_COMAFI.values()]

    if diferentes:
        print(f"\n✗ {len(diferentes)} ratios DIFIEREN de la lista oficial:")
        for k, mio, ofi, nombre in diferentes:
            print(f"    {k:8s} tabla={mio:<8g} oficial={ofi:<8g}  ({nombre})")
    else:
        print("\n✓ ningún ratio difiere de la lista oficial")
    print(f"· {len(sin_oficial)} sin fila en Comafi (ETFs / otros emisores, medidos del precio)")
    print(f"· {len(faltantes)} en la lista oficial que la tabla no cubre")

    if diferentes and args.write:
        nuevo = src[ini:fin]
        for k, _mio, ofi, _n in diferentes:
            clave = k if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", k) else f"'{k}'"
            val = str(int(ofi)) if abs(ofi - round(ofi)) < 1e-9 else f"1/{round(1 / ofi)}"
            nuevo = re.sub(rf"(?<![A-Z0-9]){re.escape(clave)}:\s*[0-9]+(?:/[0-9]+)?",
                           f"{clave}: {val}", nuevo, count=1)
        open(TABLA_JS, "w", encoding="utf-8").write(src[:ini] + nuevo + src[fin:])
        print(f"\n→ {len(diferentes)} corregidos en cedearRatio.js. Corré los tests del frontend.")
        return 0

    if diferentes:
        print("\n(volvé a correr con --write para corregirlos)")
    return 1 if diferentes else 0


if __name__ == "__main__":
    sys.exit(main())
