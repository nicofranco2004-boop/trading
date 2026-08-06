"""KNOWN_CD_TICKERS tiene que seguir siendo espejo de la allowlist del frontend.

POR QUÉ EXISTE ESTE TEST
────────────────────────
`tickers_cd.KNOWN_CD_TICKERS` es la lista de tickers que terminan en C o D de
forma LEGÍTIMA — no son la pata dólar de nada. Su docstring ya pedía "si
tickers.js suma uno nuevo terminado en C/D, agregalo acá", pero eso dependía de
que alguien se acordara, y no pasó: SID (Companhia Siderúrgica Nacional) y SCHD
(Schwab US Dividend Equity) se agregaron al frontend y nunca acá.

Lo que se rompe cuando se desincronizan, medido con el export real del usuario
que lo reportó (IOL, 2026-08-06):
  · el motor lee SID como "la pata dólar de SI" y lo trunca a SI
  · SI no cotiza en ningún lado → la cartera muestra "—" en precio, valor y P&L
  · y como SIDD (la pata dólar de verdad) sí trunca bien a SID, el usuario
    termina con DOS activos separados para la misma tenencia: 7.704 nominales
    bajo "SI" y 1.374 bajo "SID"

Este test vuelve a correr el barrido completo en cada run, así que la próxima
vez que alguien agregue un ticker terminado en C/D al frontend, se entera acá y
no por el reporte de un usuario tres meses después.

CÓMO AGREGAR UNA EXCEPCIÓN
──────────────────────────
Si el símbolo nuevo ES una especie en dólares (o sea que truncarlo es CORRECTO,
como BA37D → BA37), sumalo a ESPECIES_EN_DOLARES de abajo con su porqué. Si es
un ticker real que termina en C/D, va a KNOWN_CD_TICKERS.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.tickers_cd import KNOWN_CD_TICKERS, strip_cd_suffix  # noqa: E402

TICKERS_JS = os.path.join(os.path.dirname(BACKEND), "frontend", "src", "utils", "tickers.js")

# Símbolos que terminan en C/D y que SÍ son una pata en dólares: truncarlos es el
# comportamiento correcto (es lo que une las dos patas bajo un solo ledger FIFO).
ESPECIES_EN_DOLARES = {
    "BA37D",   # Buenos Aires 2037 (Prov., USD ley NY) — la pata pesos es BA37
}


def _simbolos_de_la_allowlist():
    """Los `{ s: 'XXX', n: 'Nombre' }` de tickers.js."""
    with open(TICKERS_JS, encoding="utf-8") as f:
        js = f.read()
    return re.findall(r"\{\s*s:\s*'([^']+)'\s*,\s*n:\s*'([^']*)'", js)


class AllowlistSincronizadaTest(unittest.TestCase):

    def test_ningun_ticker_real_se_trunca(self):
        pares = _simbolos_de_la_allowlist()
        self.assertGreater(len(pares), 300,
                           "no pude parsear la allowlist — ¿cambió el formato de tickers.js?")

        rotos = []
        for simbolo, nombre in pares:
            if not simbolo or "." in simbolo or len(simbolo) < 3:
                continue
            if simbolo[-1] not in ("C", "D"):
                continue
            if simbolo in KNOWN_CD_TICKERS or simbolo in ESPECIES_EN_DOLARES:
                continue
            rotos.append((simbolo, strip_cd_suffix(simbolo), nombre))

        if rotos:
            detalle = "\n".join(
                f"    {s} se trunca a {d}  ({n})" for s, d, n in sorted(rotos))
            self.fail(
                f"\n{len(rotos)} ticker(s) de la allowlist terminan en C/D y NO están "
                f"protegidos, así que el importador les corta la última letra y el "
                f"activo deja de cotizar:\n{detalle}\n\n"
                f"Si es un ticker real → agregalo a KNOWN_CD_TICKERS en "
                f"backend/importing/tickers_cd.py.\n"
                f"Si es una especie en dólares (truncarlo es correcto) → agregalo a "
                f"ESPECIES_EN_DOLARES en este archivo, con el porqué.")

    def test_los_reportados_quedan_intactos(self):
        # Los dos que motivaron el test.
        self.assertEqual(strip_cd_suffix("SID"), "SID",
                         "SID es el ticker NYSE de Companhia Siderúrgica, no una pata dólar")
        self.assertEqual(strip_cd_suffix("SCHD"), "SCHD",
                         "SCHD es el ETF de Schwab, no una pata dólar")

    def test_la_pata_dolar_sigue_consolidando(self):
        # Y el otro lado: la pata dólar de verdad tiene que seguir uniéndose.
        self.assertEqual(strip_cd_suffix("SIDD"), "SID",
                         "SIDD ES la pata dólar de SID y tiene que consolidar")
        self.assertEqual(strip_cd_suffix("BA37D"), "BA37",
                         "BA37D ES la especie en dólares de BA37")


if __name__ == "__main__":
    unittest.main()
