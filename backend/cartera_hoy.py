"""¿Qué pasó hoy con mi cartera? — el movimiento del día, con la FECHA de la rueda.

Es la pregunta que más se le hace al chat, y hasta ahora el chat no tenía con
qué contestarla: el snapshot traía el valor de HOY y el retorno de 30 días, pero
ningún cierre anterior. El modelo improvisaba con lo que tuviera a mano.

⭐ LA REGLA QUE SOSTIENE TODO ESTE ARCHIVO: un número que dice "hoy" tiene que
viajar con la fecha de la rueda que midió. Medido el 2026-10-08 a las 09:32
(la bolsa porteña abre a las 11:00): el feed de BYMA ya mostraba "AAPL +1,04 %"
y ese 1,04 % era el del día ANTERIOR. Un chat que lo leyera pelado diría "hoy
subiste" con el movimiento de ayer. Por eso cada grupo de este resumen dice de
qué día es, y lo que no sabemos de qué día es NO se cuenta como de hoy.

Acá vive sólo la parte pura (agrupar, sumar, rotular), sin red ni base, para
poder probarla entera. Quién trae los precios y los cierres está en
`main._cartera_hoy_para_chat`.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from money_fmt import fmt_money, fmt_num

_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

# Lo que se le dice al modelo de por qué una posición no tiene movimiento.
MOTIVOS = {
    "efectivo": "es efectivo: no se mueve con el mercado",
    "precio_manual": "tiene un precio cargado a mano, no hay cotización contra qué comparar",
    "sin_cierre": "no conseguimos el cierre anterior de este activo",
    "sin_precio": "no conseguimos su precio de hoy",
    "fci": "es un fondo común: su valor se publica una vez por día, no tiene variación en la rueda",
}


def dia_txt(rueda: Optional[str], hoy: str) -> str:
    """Cómo nombrar el día de una rueda en una frase: 'hoy', 'ayer' o 'el
    viernes 3/10'. Sin fecha → 'sin fecha confirmada' (nunca 'hoy')."""
    if not rueda:
        return "sin fecha confirmada"
    if rueda == hoy:
        return "hoy"
    try:
        r = date.fromisoformat(rueda)
        h = date.fromisoformat(hoy)
    except ValueError:
        return "sin fecha confirmada"
    if r == h - timedelta(days=1):
        return "ayer"
    return f"el {_DIAS[r.weekday()]} {r.day}/{r.month}"


def _usd_txt(v: float) -> str:
    s = fmt_money(v, "USD")
    return s if v < 0 else "+" + s


def _pct_txt(v: Optional[float]) -> Optional[str]:
    return None if v is None else f"{fmt_num(v, 2, signed=True)}%"


def armar(lotes: list, hoy: str, mercados: Optional[dict] = None,
          top: int = 8) -> dict:
    """Arma el resumen del día a partir de lotes ya valuados.

    Cada lote es un dict con:
      asset, broker, valor (USD hoy),
      valor_previo (USD al cierre anterior, MISMA cantidad y mismo dólar;
                    None = no se pudo medir),
      motivo (clave de MOTIVOS, si no se midió),
      mercado ('byma' | 'eeuu' | 'cripto' | None),
      rueda (ISO de la rueda que midió el movimiento, o None),
      es_hoy (bool: esa rueda es la de hoy para ese mercado).

    El dólar NO se mueve entre `valor_previo` y `valor`: es el movimiento de los
    PRECIOS, igual que la columna "Var. día" de Posiciones. Un CEDEAR que subió
    1 % en pesos figura +1 % aunque el MEP también se haya movido.
    """
    total = sum(float(l.get("valor") or 0) for l in lotes)

    # ── Agrupar: por (activo, rueda) los medidos; por activo los que no. ──
    medidos: dict = {}
    sin_medir: dict = {}
    efectivo = 0.0
    for l in lotes:
        v = float(l.get("valor") or 0)
        if l.get("motivo") == "efectivo":
            efectivo += v
            continue
        vp = l.get("valor_previo")
        if vp is None or vp <= 0:
            k = l.get("asset")
            e = sin_medir.setdefault(k, {"asset": k, "valor": 0.0,
                                         "motivo": MOTIVOS.get(l.get("motivo"), MOTIVOS["sin_cierre"])})
            e["valor"] += v
            continue
        # La rueda 'de hoy' de la cripto es un día UTC (su vela diaria corta a
        # las 21:00 de Buenos Aires): entre las 21 y la medianoche esa fecha ya
        # es la de mañana. Para el usuario es "hoy" — se rotula con la fecha
        # argentina para que no aparezca un grupo fechado mañana.
        rueda = hoy if (l.get("es_hoy") and l.get("mercado") == "cripto") else l.get("rueda")
        es_hoy = bool(l.get("es_hoy")) and bool(rueda)
        k = (l.get("asset"), rueda, es_hoy)
        e = medidos.setdefault(k, {"asset": l.get("asset"), "brokers": [],
                                   "mercado": l.get("mercado"), "rueda": rueda,
                                   "es_hoy": es_hoy, "valor": 0.0, "valor_previo": 0.0})
        if l.get("broker") and l.get("broker") not in e["brokers"]:
            e["brokers"].append(l.get("broker"))
        e["valor"] += v
        e["valor_previo"] += float(vp)

    mov_total = sum(e["valor"] - e["valor_previo"] for e in medidos.values())
    # La cartera "al cierre anterior": lo de hoy menos todo lo que se movió.
    base = total - mov_total

    # ── Un grupo por rueda: "hoy", "ayer", "sin fecha confirmada"… ──
    grupos: dict = {}
    for e in medidos.values():
        g = grupos.setdefault((e["rueda"], e["es_hoy"]), {
            "rueda": e["rueda"], "es_hoy": e["es_hoy"], "mercados": [],
            "usd": 0.0, "valor": 0.0, "valor_previo": 0.0, "activos": 0})
        if e["mercado"] and e["mercado"] not in g["mercados"]:
            g["mercados"].append(e["mercado"])
        g["usd"] += e["valor"] - e["valor_previo"]
        g["valor"] += e["valor"]
        g["valor_previo"] += e["valor_previo"]
        g["activos"] += 1

    movimiento = []
    # Primero lo de hoy, después de lo más nuevo a lo más viejo; sin fecha al final.
    for g in sorted(grupos.values(),
                    key=lambda g: (g["es_hoy"], g["rueda"] is not None, g["rueda"] or ""),
                    reverse=True):
        usd = round(g["usd"], 2)
        pct_cartera = round(g["usd"] / base * 100, 2) if base > 0 else None
        pct_medido = round(g["usd"] / g["valor_previo"] * 100, 2) if g["valor_previo"] > 0 else None
        movimiento.append({
            "rueda": g["rueda"],
            "dia_txt": "hoy" if g["es_hoy"] else dia_txt(g["rueda"], hoy),
            "es_hoy": g["es_hoy"],
            "mercados": sorted(g["mercados"]),
            "usd": usd,
            "usd_txt": _usd_txt(usd),
            "pct_sobre_la_cartera": pct_cartera,
            "pct_sobre_la_cartera_txt": _pct_txt(pct_cartera),
            "pct_de_esos_activos": pct_medido,
            "pct_de_esos_activos_txt": _pct_txt(pct_medido),
            "porcion_de_la_cartera_pct": round(g["valor"] / total * 100, 1) if total > 0 else None,
            "activos": g["activos"],
        })

    # ── Los que más movieron la cartera, en plata (no en %): un +8 % en una
    # posición de US$ 20 no le cambia el día a nadie. ──
    filas = []
    for e in medidos.values():
        usd = e["valor"] - e["valor_previo"]
        pct = (usd / e["valor_previo"] * 100) if e["valor_previo"] > 0 else None
        filas.append({
            "asset": e["asset"],
            "brokers": e["brokers"],
            "mercado": e["mercado"],
            "dia_txt": "hoy" if e["es_hoy"] else dia_txt(e["rueda"], hoy),
            "es_hoy": e["es_hoy"],
            "usd": round(usd, 2),
            "usd_txt": _usd_txt(round(usd, 2)),
            "pct": None if pct is None else round(pct, 2),
            "pct_txt": _pct_txt(None if pct is None else round(pct, 2)),
            "peso_en_la_cartera_pct": round(e["valor"] / total * 100, 1) if total > 0 else None,
        })
    filas.sort(key=lambda f: abs(f["usd"]), reverse=True)

    sm = sorted(sin_medir.values(), key=lambda e: e["valor"], reverse=True)
    sm_valor = sum(e["valor"] for e in sm)

    return {
        "hoy": hoy,
        "valor_cartera_usd": round(total, 2),
        "valor_cartera_txt": fmt_money(total, "USD"),
        "movimiento": movimiento,
        "activos_que_mas_movieron": filas[:top],
        "sin_medir": [{"asset": e["asset"], "motivo": e["motivo"],
                       "peso_en_la_cartera_pct": round(e["valor"] / total * 100, 1) if total > 0 else None}
                      for e in sm[:10]],
        "sin_medir_porcion_de_la_cartera_pct": round(sm_valor / total * 100, 1) if total > 0 else None,
        "efectivo_porcion_de_la_cartera_pct": round(efectivo / total * 100, 1) if total > 0 else None,
        "mercados": mercados or {},
    }


def tickers_para_noticias(resumen: dict, cripto: set, maximo: int = 5) -> list:
    """De qué activos buscar noticias: los que más movieron la cartera y se
    movieron de verdad (≥ 1 %). Cripto queda afuera por el mismo motivo que en
    el mail del mercado: la búsqueda "BTC acciones" no trae nada útil."""
    out = []
    for f in resumen.get("activos_que_mas_movieron") or []:
        a = f.get("asset")
        if not a or a in cripto or a in out:
            continue
        if f.get("pct") is None or abs(f["pct"]) < 1:
            continue
        out.append(a)
        if len(out) >= maximo:
            break
    return out
