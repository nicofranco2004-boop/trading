"""accion_local — ¿es una acción ARGENTINA (se lee en BYMA ÷ el MEP) o no (su
acción de afuera)? Espejo de frontend/src/utils/accionLocal.js y de
`lecturaDeSeguido` (utils/listaTecnica.js). Las dos copias leen la MISMA tabla
de casos (frontend/src/utils/fixtures/accionLocal.json) en sus pruebas
(tests/test_accion_local.py y utils/accionLocal.test.js): si una cambia sin la
otra, se pone roja.

Dos preguntas, porque se sabe distinto de lo que tenés y de lo que seguís:
  · `es_lote_local`: un LOTE tuyo (tiene broker y moneda). Acción argentina si
    se valúa por su precio de BYMA (`position_price_key` termina en .BA) y no
    es efectivo, ni cripto, ni CEDEAR (por tipo o por la lista de la app).
  · `seguido`: un símbolo de la WATCHLIST (sólo el texto que guardó el botón:
    «GGAL» el buscador del inicio, «GGAL.BA» la estrella de la ficha).
    Acción argentina si es del panel argentino (`AR_STOCK_TICKERS`), con o sin
    «.BA»; otro «.BA» es un CEDEAR.

Ninguna mira la lista de CEDEARs de BYMA (data912): si data912 no contesta,
la respuesta tiene que ser la misma (auditoría A 29/10, P2). Pasó (A1): la
watchlist decidía por el sufijo «.BA» y «GGAL» del buscador se leía con el ADR
de Nueva York en Señales y en el mail, y con la acción de BYMA en Tu lista y en
la ficha que abre «Ver gráfico».
"""
from __future__ import annotations


def es_cedear(asset: str) -> bool:
    """¿Es un CEDEAR de la lista de la app? Con el código de especie (SI = SID).
    Espejo de `esCedear` (utils/accionLocal.js)."""
    from ai.trade_tickers import CEDEAR_TICKERS
    from fuera_de_horario import CEDEAR_ESPECIE_ALIAS
    a = (asset or "").strip().upper()
    if a.endswith(".BA"):
        a = a[:-3]
    return CEDEAR_ESPECIE_ALIAS.get(a, a) in CEDEAR_TICKERS


def es_lote_local(p: dict, ars: set, ar_usd: set) -> bool:
    """¿Este lote es una acción argentina? Espejo de `esLoteLocal`. `ars` y
    `ar_usd` son los de `snapshots_job._broker_name_sets`."""
    from snapshots_job import _crypto_symbol_set, position_price_key
    if p.get("is_cash"):
        return False
    a = (p.get("asset") or "").upper()
    if (p.get("asset_type") or "").upper() == "CEDEAR" or es_cedear(a) or a in _crypto_symbol_set():
        return False
    return str(position_price_key(p, ars, ar_usd)).upper().endswith(".BA")


def seguido(simbolo: str) -> tuple:
    """(asset, local) de un símbolo de la watchlist. Espejo de
    `lecturaDeSeguido`: `asset` sin «.BA» ni «-USD» (la clave con que se nombra
    lo que tenés), `local` = es una acción del panel argentino. Una cripto
    pelada (BTC) no es acción aunque comparta código con una (`inferType` mira
    la cripto antes)."""
    from ai.trade_tickers import AR_STOCK_TICKERS
    from cripto import es_cripto
    s = (simbolo or "").strip().upper()
    base = s[:-3] if s.endswith(".BA") else s
    local = base in AR_STOCK_TICKERS and (s.endswith(".BA") or not es_cripto(s))
    if base.endswith("-USD") and es_cripto(base[:-4]):
        base = base[:-4]
    return base, local
