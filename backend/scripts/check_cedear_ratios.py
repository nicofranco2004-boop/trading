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

Sale con código 1 si encuentra diferencias o una excepción que ya no cuadra
(sirve para CI o para un cron).

FUENTE
──────
Banco Comafi, emisor de los programas de CEDEARs — "LISTA TOTAL DE CEDEARS",
columna "Ratio Cedear/Acción ó ADR". Cubre acciones; NO trae ETFs (SPY, QQQ,
GLD…) ni los CEDEARs de otros emisores: ésos quedan fuera del chequeo y en la
tabla están marcados como medidos del precio.

EXCEPCIONES
───────────
Esa columna cuenta CEDEARs por el papel sobre el que se armó el programa. Si ese
papel desaparece, la lista puede quedarse con el número viejo, y copiarlo rompe
la tabla: AstraZeneca canjeó su ADR (media acción) por la acción el 02/02/2026,
Comafi sigue anotando 2 CEDEARs por ADR y contra la acción que cotiza hoy son 4.
Esas decisiones, verificadas a mano, viven en `NO_SEGUIR_A_COMAFI`: el chequeo
las muestra aparte y `--write` no las toca. Si Comafi cambia el número que
anotaba, o la tabla deja de decir lo decidido, lo marca para que lo mire una
persona.
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

# Donde la tabla NO copia a Comafi, a propósito (ver EXCEPCIONES arriba):
# {símbolo: (ratio de la tabla, ratio que anota Comafi, por qué)}. Se guarda lo
# que anota Comafi porque la decisión se tomó contra ESE número: si lo cambia, ya
# no vale sola. El mismo motivo, más largo, en la tabla (cedearRatio.js).
NO_SEGUIR_A_COMAFI = {
    "AZN": (4, 2, "Comafi cuenta 2 por ADR; el 02/02/2026 cada ADR se canjeó por media "
                  "acción y AZN en Nueva York (y en Yahoo) es la acción entera. Verificado "
                  "el 06/11/2026: precio 4,00 en 230 ruedas, un cobro real 4,7."),
}


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


# Una entrada de la tabla: la clave (sin comillas o con simples o dobles) y el
# ratio (entero, con decimales, o una fracción «1/3» con o sin espacios).
_ENTRADA = re.compile(r"""\s*(?:'([^']*)'|"([^"]*)"|([A-Za-z0-9_$\-.]+))\s*:\s*"""
                      r"""([0-9]+(?:\.[0-9]+)?)(?:\s*/\s*([0-9]+(?:\.[0-9]+)?))?\s*""")


def leer_tabla_js(path: str = TABLA_JS) -> tuple[dict[str, float], str, tuple[int, int]]:
    """Lee CEDEAR_RATIOS del módulo. Devuelve (tabla, fuente completa, (ini, fin)).

    Entrada por entrada (lo que hay entre comas): si una no se entiende, o trae
    una clave en minúscula (la pantalla busca en mayúscula: no la encontraría
    nunca), FALLA en vez de saltearla. La lee también la prueba de paridad con la
    copia del servidor (`backend/ratios_cedear.py`): antes, una clave nueva con
    comillas dobles, un ratio con decimales (2.5 se leía 2) o una clave en
    minúscula separaban las dos copias sin que la prueba se pusiera roja
    (auditoría 06/11, pruebas: hallazgo 5)."""
    src = open(path, encoding="utf-8").read()
    ini = src.index("export const CEDEAR_RATIOS = {") + len("export const CEDEAR_RATIOS = {")
    fin = src.index("\n}", ini)
    cuerpo = re.sub(r"//.*", "", src[ini:fin])
    tabla = {}
    for item in (x for x in cuerpo.split(",") if x.strip()):
        m = _ENTRADA.fullmatch(item)
        if not m:
            raise ValueError(f"no entiendo esta entrada de CEDEAR_RATIOS: {item.strip()!r}")
        k = next(g for g in m.groups()[:3] if g is not None)
        if k != k.upper():
            raise ValueError(f"CEDEAR_RATIOS tiene una clave en minúscula: {k!r}")
        num, den = float(m.group(4)), float(m.group(5)) if m.group(5) else 1.0
        tabla[k] = num / den
    return tabla, src, (ini, fin)


def aplicar_correcciones(src: str, ini: int, fin: int,
                         diferentes: list[tuple[str, float, float, str]]) -> str:
    """Devuelve el módulo con los ratios corregidos. Sin I/O, para poder testearla.

    Toca SOLO el bloque [ini:fin] de CEDEAR_RATIOS a propósito: el módulo tiene
    números en los comentarios (el ejemplo `GOOGL: 347.45` de deriveCedearRatio)
    que no son ratios y no se deben pisar.
    """
    bloque = src[ini:fin]
    for k, _mio, ofi, _nombre in diferentes:
        clave = k if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", k) else f"'{k}'"
        # Entero; menor a 1, como fracción (1/3); mayor a 1 y no entero, con
        # decimales (escribía 1,5 como «1/1» y 2,5 como «1/0»).
        val = (str(int(round(ofi))) if abs(ofi - round(ofi)) < 1e-9
               else f"1/{round(1 / ofi)}" if ofi < 1 else f"{ofi:g}")
        # El lookbehind evita que al corregir 'BA' se pise el ratio de 'BABA'.
        patron = rf"(?<![A-Z0-9]){re.escape(clave)}:\s*[0-9]+(?:\.[0-9]+)?(?:\s*/\s*[0-9]+(?:\.[0-9]+)?)?"
        bloque, n = re.subn(patron, f"{clave}: {val}", bloque, count=1)
        if n != 1:
            raise RuntimeError(
                f"no pude ubicar {clave} en la tabla para corregirlo — "
                f"revisá el formato a mano antes de confiar en --write")
    return src[:ini] + bloque + src[fin:]


def comparar(tabla: dict[str, float], oficial: dict[str, tuple[float, str]],
             excepciones: dict | None = None):
    """Cruza la tabla con la lista oficial. Sin I/O, para poder testearla.

    Devuelve (diferentes, a_proposito, revisar, sin_oficial):
      · diferentes: [(k, tabla, oficial, nombre)], lo que `--write` corrige;
      · a_proposito: [(k, tabla, oficial, por qué)], las excepciones que siguen
        valiendo (Comafi anota lo mismo que cuando se decidió no copiarlo);
      · revisar: [(k, tabla, oficial, qué cambió)], excepciones que ya no
        describen lo que hay. No se corrigen solas: las mira una persona;
      · sin_oficial: [k], sin fila en Comafi.
    """
    excepciones = NO_SEGUIR_A_COMAFI if excepciones is None else excepciones
    diferentes, a_proposito, revisar, sin_oficial = [], [], [], []
    for k, mio in sorted(tabla.items()):
        hit = oficial.get(ALIAS_A_COMAFI.get(k, k))
        if hit is None:
            sin_oficial.append(k)
            continue
        ofi, nombre = hit
        if k in excepciones:
            nuestro, de_comafi, motivo = excepciones[k]
            if abs(mio - nuestro) > 1e-6:
                revisar.append((k, mio, ofi, f"la excepción dice que la tabla tiene {nuestro:g}"))
            elif abs(ofi - de_comafi) > 1e-6:
                revisar.append((k, mio, ofi, f"Comafi anotaba {de_comafi:g} y ahora {ofi:g}"))
            else:
                a_proposito.append((k, mio, ofi, motivo))
        elif abs(mio - ofi) > 1e-6:
            diferentes.append((k, mio, ofi, nombre))
    return diferentes, a_proposito, revisar, sin_oficial


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                    help="corrige en cedearRatio.js los ratios que difieren de la oficial")
    ap.add_argument("--tabla", default=TABLA_JS,
                    help="ruta del módulo cedearRatio.js (por defecto, el del repo)")
    args = ap.parse_args()

    try:
        oficial = bajar_oficial()
    except Exception as ex:                                   # red caída, URL movida
        print(f"No se pudo bajar la lista de Comafi: {ex}")
        print("Si la URL cambió, buscala en comafi.com.ar/custodiaglobal/programas.aspx")
        return 2
    tabla, src, (ini, fin) = leer_tabla_js(args.tabla)
    print(f"oficial (Comafi): {len(oficial)} ratios · tabla de Rendi: {len(tabla)}")

    diferentes, a_proposito, revisar, sin_oficial = comparar(tabla, oficial)

    # Los que la oficial trae y nosotros ni tenemos: sin ratio no se publica monto,
    # así que no es un bug — pero es cobertura que estamos dejando sobre la mesa.
    faltantes = [k for k in oficial if k not in tabla and k not in ALIAS_A_COMAFI.values()]

    if diferentes:
        print(f"\n✗ {len(diferentes)} ratios DIFIEREN de la lista oficial:")
        for k, mio, ofi, nombre in diferentes:
            print(f"    {k:8s} tabla={mio:<8g} oficial={ofi:<8g}  ({nombre})")
    else:
        print("\n✓ ningún ratio difiere de la lista oficial"
              + (" (fuera de las excepciones de abajo)" if a_proposito or revisar else ""))
    if revisar:
        print(f"\n✗ {len(revisar)} excepciones de NO_SEGUIR_A_COMAFI ya no cuadran "
              f"(miralas a mano; --write no las toca):")
        for k, mio, ofi, que in revisar:
            print(f"    {k:8s} tabla={mio:<8g} oficial={ofi:<8g}  {que}")
    for k, mio, ofi, motivo in a_proposito:
        print(f"· {k} distinto de Comafi A PROPÓSITO (tabla={mio:g}, oficial={ofi:g}): {motivo}")
    print(f"· {len(sin_oficial)} sin fila en Comafi (ETFs / otros emisores, medidos del precio)")
    print(f"· {len(faltantes)} en la lista oficial que la tabla no cubre")

    if diferentes and args.write:
        # Lee y escribe la MISMA ruta: antes leía del default del parámetro y
        # escribía en la constante global, así que apuntar a otro archivo habría
        # pisado el destino con el contenido del otro.
        try:
            nuevo = aplicar_correcciones(src, ini, fin, diferentes)
        except RuntimeError as ex:
            print(f"\n{ex}")
            return 2
        open(args.tabla, "w", encoding="utf-8").write(nuevo)
        print(f"\n→ {len(diferentes)} corregidos en {os.path.basename(args.tabla)}."
              f" Corré los tests del frontend.")
        return 1 if revisar else 0

    if diferentes:
        print("\n(volvé a correr con --write para corregirlos)")
    return 1 if diferentes or revisar else 0


if __name__ == "__main__":
    sys.exit(main())
