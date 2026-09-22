"""Letras/LECAPs del Tesoro AR: cuánta plata devuelven el día que vencen.

POR QUÉ HACE FALTA ESTE ARCHIVO
───────────────────────────────
Una letra no paga cupones: devuelve todo junto el día que vence. Pero las
LECAP/BONCAP CAPITALIZAN, así que 100 nominales NO devuelven 100: devuelven 100
más el interés que se fue acumulando desde la emisión. Medido el 2026-09-22,
S30O6 cotizaba 132,45 por cada 100 nominales y devuelve ~135,33 al vencer. Un
calendario que mostrara "100" estaría 35 % abajo, y en la pantalla del asesor
eso es plata que el cliente creería que no va a cobrar.

DE DÓNDE SALE EL NÚMERO
───────────────────────
De la misma fuente que ya sirve el PRECIO de la letra (ArgentinaDatos, ver
`_fetch_argentinadatos_letras` en main.py), que publica al lado la TEM — la tasa
mensual que el mercado le pide al papel. La TEM es, por definición, la tasa que
lleva el precio de HOY al pago del vencimiento:

    pago_por_100 = precio_por_100 × (1 + TEM) ^ (días_al_vencimiento / 30)

Verificado contra la otra vía que trae el mismo feed: para S30S6 (8 días al
vencimiento) el `paridadPorcentaje` implica un valor técnico de 116,75 que
capitalizado da 117,29, y esta fórmula da 117,54 — 0,2 % de diferencia. Para
papeles más largos `paridadPorcentaje` no es usable (el feed lo calcula con dos
convenciones distintas según el ticker), así que la TEM es la única vía uniforme.

Es una estimación DE MERCADO, no el prospecto: se mueve con el precio del día.
Quien la muestre tiene que marcarla como estimada, y NO se usa para pre-llenar
un cobro a registrar (eso escribe operaciones, y una estimación no puede
escribir plata).

CUÁNDO NO ESTIMAMOS — y por qué el feed solo no alcanza
───────────────────────────────────────────────────────
El feed llama "letras" a papeles que NO son letras cero-cupón, y aplicarles la
fórmula inventaría plata:
  • TY30P (vence 2030) es un bono que PAGA CUPONES: capitalizarlo como bullet
    agregaría un pago final gigante ADEMÁS de sus cupones.
  • TTD26 cotiza con TEM NEGATIVA (−2,10 % el 2026-09-22): proyectar con ella
    daría un pago MENOR que el precio de hoy — plata que se achica sola.
Por eso el ticker y el feed tienen que estar DE ACUERDO: sólo se estima si el
símbolo decodifica como letra estándar argentina (S30O6 → 30/oct/2026, la regla
de `importing.maturity.letra_maturity`) Y esa fecha es la misma que publica el
feed. TO26, TTD26 y TY30P no decodifican con esa regla → quedan afuera solos,
sin lista negra que mantener. Los 10 tickers restantes del feed (2026-09-22)
decodifican y coinciden al día.

Un papel que queda afuera no desaparece: sigue cayendo en "sin cronograma
conocido", que es exactamente lo que mostraba antes de esto.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

# El feed publica un universo chico (13 papeles vivos al 2026-09-22) y sólo en
# pesos. Un papel que pague en otra moneda tendría su TEM en ESA moneda, y
# proyectar un pago en pesos con una tasa en dólares mezclaría dos cosas
# distintas (ver [[feedback_el_tc_tiene_que_cancelarse]]): se excluye.
PAYOUT_CURRENCY = "ARS"


def parse_letras_feed(payload: Any) -> Dict[str, Dict[str, Any]]:
    """{ticker: {price_per_100, tem_pct, maturity, currency}} desde el JSON crudo
    de ArgentinaDatos. Ignora en silencio las filas sin precio usable."""
    items = (payload or {}).get("letras") if isinstance(payload, dict) else payload
    out: Dict[str, Dict[str, Any]] = {}
    for item in (items or []):
        if not isinstance(item, dict):
            continue
        ticker = (item.get("ticker") or "").strip().upper()
        price = item.get("precioArs")
        if not ticker or not isinstance(price, (int, float)) or price <= 0:
            continue
        tem = item.get("temPorcentaje")
        out[ticker] = {
            "ticker": ticker,
            "price_per_100": float(price),
            "tem_pct": float(tem) if isinstance(tem, (int, float)) else None,
            "maturity": (item.get("fechaVencimiento") or "")[:10] or None,
            "currency": (item.get("monedaCupon") or PAYOUT_CURRENCY).strip().upper(),
        }
    return out


def days_to_maturity(maturity: Optional[str], today: str) -> Optional[int]:
    """Días entre hoy y el vencimiento. None si alguna fecha no es una fecha."""
    try:
        return (date.fromisoformat(maturity) - date.fromisoformat(today)).days
    except (TypeError, ValueError):
        return None


def payout_per_100(price_per_100: Optional[float], tem_pct: Optional[float],
                   days: Optional[int]) -> Optional[float]:
    """Lo que devuelve la letra al vencer, por cada 100 nominales. None si falta
    algún dato o la tasa no es positiva (ver la cabecera: una TEM ≤ 0 no describe
    una letra que capitaliza)."""
    if not price_per_100 or price_per_100 <= 0:
        return None
    if tem_pct is None or tem_pct <= 0:
        return None
    if days is None or days < 0:
        return None
    return round(price_per_100 * (1.0 + tem_pct / 100.0) ** (days / 30.0), 4)


def letra_cashflow(rec: Optional[Dict[str, Any]], ticker_maturity: Optional[str],
                   today: str) -> Optional[Dict[str, Any]]:
    """El único pago de una letra, listo para el calendario — o None si este
    papel no califica (ver "CUÁNDO NO ESTIMAMOS" arriba).

    `ticker_maturity` es el vencimiento DECODIFICADO DEL SÍMBOLO por la regla del
    importador; tiene que coincidir con el que publica el feed. `today` es el día
    argentino de Rendi (el caller lo pasa; acá no se lee ningún reloj).
    """
    if not rec:
        return None
    maturity = rec.get("maturity")
    if not maturity or not ticker_maturity or maturity != ticker_maturity:
        return None                      # el símbolo y el feed no dicen lo mismo
    if (rec.get("currency") or PAYOUT_CURRENCY) != PAYOUT_CURRENCY:
        return None                      # el precio es en pesos; la tasa, no
    days = days_to_maturity(maturity, today)
    if days is None or days <= 0:
        return None                      # ya venció: el pago no es un pago futuro
    payout = payout_per_100(rec.get("price_per_100"), rec.get("tem_pct"), days)
    if payout is None:
        return None
    return {
        "maturity": maturity,
        "payout_per_100": payout,
        "currency": PAYOUT_CURRENCY,
        "price_per_100": round(float(rec["price_per_100"]), 4),
        "tem_pct": rec.get("tem_pct"),
        "source": "ArgentinaDatos",
    }


def letras_catalog(records: Dict[str, Dict[str, Any]], tickers: List[str],
                   today: str, ticker_maturity) -> Dict[str, Dict[str, Any]]:
    """Sub-catálogo para los tickers pedidos: {ticker: cashflow}. Los que no
    califican simplemente no están (el frontend ya sabe qué hacer con eso:
    'sin cronograma conocido')."""
    out: Dict[str, Dict[str, Any]] = {}
    for t in tickers or []:
        key = (t or "").strip().upper()
        if not key or key in out:
            continue
        cf = letra_cashflow(records.get(key), ticker_maturity(key), today)
        if cf:
            out[key] = cf
    return out
