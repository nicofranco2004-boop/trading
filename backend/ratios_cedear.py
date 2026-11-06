"""Cuántos CEDEARs hacen una acción de afuera (el «ratio» del CEDEAR).

QUÉ ES. Un CEDEAR no es una acción: es una fracción. Hacen falta 20 CEDEARs de
AAPL para una acción de Apple; con ABEV es al revés (1/3: un CEDEAR son tres
acciones). Todo precio «por acción» de Nueva York está en la escala de la acción,
no del CEDEAR.

COPIA de `CEDEAR_RATIOS` de frontend/src/utils/cedearRatio.js (la lista oficial
de Comafi y, para los ETFs y los CEDEARs de otros emisores, el ratio medido del
precio: ver el comentario de allá). La pantalla la usa para los dividendos; acá:
  · `tecnico.serie`: el gráfico en pesos de un CEDEAR que no tiene su serie en
    pesos al día es la acción de afuera × el MEP de cada día ÷ esto. Sin dividir
    era la acción ENTERA en pesos (Apple ×20, Mercado Libre ×120: auditoría del
    06/11/2026);
  · `main.CEDEAR_USD_RATIOS`: el precio en pesos de los CEDEARs que las fuentes
    cotizan en dólares (BAC).
tests/test_ratios_cedear.py compara las dos copias: si cambiás una sin la otra,
falla. Para revalidarla contra Comafi: scripts/check_cedear_ratios.py (corrige la
de la pantalla; después se copia acá).

Lo que la tabla no tiene no se adivina: `ratio_de` da None y quien la usa no
publica un precio en la escala del CEDEAR. Un número ausente es honesto; uno
inflado veinte veces, no.
"""
from __future__ import annotations

CEDEAR_RATIOS = {
    # ── Ratio OFICIAL de Comafi (lista del 17.9.2026) ─────────────────────
    "AAL": 2, "AAPL": 20, "ABBV": 10, "ABEV": 1 / 3, "ACWI": 26, "ADBE": 44, "ALAB": 44, "AMD": 10, "AMGN": 30,
    "AMZN": 144, "ANET": 29, "ASML": 146, "ASTS": 15, "AVGO": 39, "AXP": 15, "BA": 24, "BABA": 9,
    "BAC": 4, "BAK": 2, "BB": 3, "BBD": 1, "BIDU": 11, "BIOX": 1, "BMNR": 8, "BMY": 3, "BRK-B": 22, "BRKB": 22,
    "C": 3, "CAT": 20, "CEG": 45, "COIN": 27, "COP": 25, "COPX": 14, "COST": 48, "CRM": 18, "CRWD": 79,
    "CRWV": 27, "CSCO": 5, "CVX": 16, "DE": 40, "DISN": 12, "DOCU": 22, "DOW": 6, "FXI": 5, "GE": 8, "GILD": 4,
    "GLOB": 18, "GM": 6, "GOOGL": 58, "GPRK": 1, "GS": 13, "HD": 32, "HIMS": 4, "HMY": 1, "HON": 8, "HOOD": 29,
    "IBIT": 10, "IBM": 15, "INTC": 5, "IREN": 12, "ITUB": 1, "JD": 4, "JNJ": 15, "JPM": 15, "KO": 5, "LAC": 1,
    "LAR": 1, "LLY": 56, "LMT": 20, "MA": 33, "MCD": 24, "MELI": 120, "META": 24, "MMM": 10, "MP": 10,
    "MRK": 5, "MRNA": 19, "MS": 41, "MSFT": 30, "MUX": 2, "NBIS": 27, "NFLX": 48, "NIO": 4, "NKE": 12,
    "NOKA": 1, "NOW": 172, "NU": 2, "NVDA": 24, "NVO": 7, "NVS": 4, "O": 13, "OKLO": 28, "ONDS": 2, "ORCL": 3,
    "PAGS": 3, "PATH": 2, "PBR": 1, "PDD": 25, "PEP": 18, "PFE": 4, "PINS": 7, "PLTR": 3, "PYPL": 8,
    "QCOM": 11, "RGTI": 2, "RIO": 8, "RIOT": 3, "RKLB": 12, "ROKU": 13, "RTX": 5, "SBUX": 12, "SE": 32,
    "SHOP": 107, "SID": 1 / 8, "SNAP": 1, "SNDK": 170, "SNOW": 30, "SPCE": 1 / 2, "SPCX": 50, "SPOT": 28,
    "STNE": 3, "T": 3, "TGT": 24, "TRIP": 2, "TSLA": 15, "TSM": 9, "TWLO": 36, "UNH": 33, "V": 18, "VALE": 2,
    "VIG": 39, "VIST": 3, "VST": 26, "WFC": 5, "WMT": 18, "XLV": 29, "XOM": 10, "XYZ": 20, "ZM": 47,

    # ── Distinto de Comafi a propósito: su lista cuenta contra un papel que ya no
    #    existe (AstraZeneca canjeó su ADR por la acción el 02/02/2026; ver «CUANDO
    #    COMAFI CUENTA OTRA COSA» en la tabla de la pantalla). Verificado a mano.
    "AZN": 4,

    # ── Sin fila en la lista de Comafi (ETFs, y acciones de otros emisores):
    #    ratio MEDIDO del precio (puede haber alguno corrido en 1).
    "ABNB": 15, "ARKK": 10, "EA": 14, "EEM": 5, "ETHA": 5, "EWY": 50, "EWZ": 2, "F": 1, "GLD": 50, "HUT": 5,
    "JMIA": 1, "KEEL": 1 / 5, "MSTR": 20, "MU": 5, "PANW": 50, "QQQ": 20, "SATL": 1, "SPY": 60, "UBER": 2,
    "URA": 5, "XLE": 2, "XLF": 2,
}


def ratio_de(asset) -> float | None:
    """El ratio de la tabla para el CEDEAR `asset` (con o sin '.BA'), o None.

    Se busca con el código con que BYMA cotiza el CEDEAR (`simbolo_byma`: «BRK.B»
    es BRKB). El alias de especie (SI = SID) NO: «SI» en Nueva York es otra
    empresa (Shoulder Innovations) y su precio ÷ el ratio de CSN no es nada."""
    from snapshots_job import simbolo_byma
    a = (asset or "").strip().upper()
    if a.endswith(".BA"):
        a = a[:-3]
    if not a:
        return None
    r = CEDEAR_RATIOS.get(simbolo_byma(a)[:-3], CEDEAR_RATIOS.get(a))
    return float(r) if r and r > 0 else None
