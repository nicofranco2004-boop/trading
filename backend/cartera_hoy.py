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
    "precio_dudoso": "su precio de hoy y el cierre anterior no cuadran entre sí; preferimos no inventar el movimiento",
    "comprado_hoy_sin_rueda": "lo compraste hoy y su mercado todavía no operó hoy",
}


# Por qué un activo no tiene «Contra tu promedio» (lo que dice el mapa en gris).
MOTIVOS_PROMEDIO = {
    "sin_precio": "no conseguimos su precio de hoy",
    "precio_dudoso": "su precio de hoy no cuadra; preferimos no inventar cuánto vale",
    "sin_costo": "no tiene cargado lo que pagaste",
}

# Una compra de HOY se hizo a un precio de hoy: su costo tiene que caer entre el
# cierre anterior y el precio de ahora, con este margen para lo que el precio
# anduvo dentro de la rueda, la comisión y el dólar del día de la compra.
# Es el mismo control que «precio_dudoso» (un precio que en un día se movió más de
# 50 % es una unidad equivocada), pero contra el rango del día: equivocarse para
# este lado cuesta poco (el lote se mide desde el cierre de ayer, como la «Var.
# día» de la Cartera), equivocarse para el otro publicaba +398 %.
MARGEN_COMPRA_DEL_DIA = 0.15


def compra_cuadra_con_el_dia(costo: Optional[float], valor: Optional[float],
                             valor_previo: Optional[float]) -> bool:
    """¿El costo de un lote «comprado hoy» es el de una compra de hoy? `costo`,
    `valor` (ahora) y `valor_previo` (al cierre anterior): misma cantidad, en USD.
    Con el promedio de hace años (MSFT 120,5 contra 590/600) no: ese lote ya lo
    tenías, y medido desde la compra decía «Hoy tu cartera +116 %»."""
    try:
        c, v, vp = float(costo or 0), float(valor or 0), float(valor_previo or 0)
    except (TypeError, ValueError):
        return False
    if c <= 0 or v <= 0 or vp <= 0:
        return False
    piso = min(v, vp) / (1 + MARGEN_COMPRA_DEL_DIA)
    techo = max(v, vp) * (1 + MARGEN_COMPRA_DEL_DIA)
    return piso <= c <= techo


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


def _no_hoy(txt: str) -> str:
    """Invariante: "hoy" se escribe SÓLO si es_hoy. Un número cuya rueda tiene
    la fecha de hoy pero que su mercado no confirma como de hoy no se llama
    "hoy"."""
    return "sin fecha confirmada" if txt == "hoy" else txt


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
                                   "es_hoy": es_hoy, "valor": 0.0, "valor_previo": 0.0,
                                   "comprado_hoy": False})
        e["comprado_hoy"] = e["comprado_hoy"] or bool(l.get("comprado_hoy"))
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
            "dia_txt": "hoy" if g["es_hoy"] else _no_hoy(dia_txt(g["rueda"], hoy)),
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
            "dia_txt": "hoy" if e["es_hoy"] else _no_hoy(dia_txt(e["rueda"], hoy)),
            "es_hoy": e["es_hoy"],
            "usd": round(usd, 2),
            "usd_txt": _usd_txt(round(usd, 2)),
            "pct": None if pct is None else round(pct, 2),
            "pct_txt": _pct_txt(None if pct is None else round(pct, 2)),
            "peso_en_la_cartera_pct": round(e["valor"] / total * 100, 1) if total > 0 else None,
            # Lo compró HOY (todo o una parte): su movimiento se mide desde el
            # precio de compra, no desde el cierre de ayer.
            "comprado_hoy": e["comprado_hoy"],
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


def por_activo(lotes: list, hoy: str) -> list:
    """Lo del «Mapa de tu cartera», activo por activo, de los MISMOS lotes que
    `armar` (`main._lotes_del_dia`). Un activo es (asset, local) —la clave de
    `senales_semana.cartera`, la de los cuadritos—: GGAL de BYMA y el ADR no se
    suman. → [{asset, local, valor, hoy: {pct, usd} | None, dia_txt,
    promedio_pct_usd, promedio_pct_ars, promedio_sin_dato}]

      · `hoy`: el movimiento del precio en la rueda de HOY (la regla del archivo:
        lo que no es de hoy no se llama hoy). Si su última rueda es otra, None y
        `dia_txt` dice cuál («ayer», «el viernes 3/10»); sin medir, `dia_txt` None.
      · «Contra tu promedio», lo que vale contra lo que pagaste, en %, en las DOS
        monedas (la pantalla elige con la regla de `noRealizadoEnVista`):
          `promedio_pct_usd` — en dólares, el costo al dólar de la compra (`costo`);
          `promedio_pct_ars` — en pesos: el costo de un lote en pesos son los
            pesos que se pagaron (`costo_hoy`, al dólar de hoy, el mismo dólar
            del valor); un lote en dólares, a ese dólar también. Es también el %
            en dólares de quien elige «costo al dólar de hoy».
        Sin precio (el valor sería el costo: «0 %» que no pasó) o sin costo, los
        dos None y `promedio_sin_dato` dice por qué. Mejor gris que inventado.
    El efectivo no va: no es un activo del mapa."""
    grupos: dict = {}
    for l in lotes:
        if l.get("motivo") == "efectivo" or not l.get("asset"):
            continue
        k = (str(l["asset"]).upper(), bool(l.get("local")))
        g = grupos.setdefault(k, {"valor": 0.0, "costo": 0.0, "costo_hoy": 0.0, "sin_dato": None,
                                  "hoy_v": 0.0, "hoy_vp": 0.0, "medido_hoy": False,
                                  "todos_hoy": True, "otra_rueda": None})
        v = float(l.get("valor") or 0)
        g["valor"] += v
        c, ch = l.get("costo"), l.get("costo_hoy")
        # El primer motivo que impide el % es el que se dice (sin precio antes que
        # sin costo: es lo que el usuario puede ver en la Cartera).
        if l.get("sin_precio") or l.get("motivo") == "sin_precio":
            g["sin_dato"] = g["sin_dato"] or "sin_precio"
        elif (l.get("motivo") == "precio_dudoso" and c is not None
              and abs(v - float(c)) <= 0.01):
            # El control de precios de la valuación lo llevó al costo.
            g["sin_dato"] = g["sin_dato"] or "precio_dudoso"
        if c is None or c <= 0 or ch is None or ch <= 0:
            g["sin_dato"] = g["sin_dato"] or "sin_costo"
        else:
            g["costo"] += float(c)
            g["costo_hoy"] += float(ch)
        vp = l.get("valor_previo")
        if vp is not None and vp > 0 and l.get("es_hoy"):
            g["medido_hoy"] = True
            g["hoy_v"] += v
            g["hoy_vp"] += float(vp)
        else:
            # Un lote del activo sin el movimiento de hoy: el % de hoy del activo
            # sería el de una parte. Mejor ninguno que uno a medias.
            g["todos_hoy"] = False
            if vp is not None and vp > 0 and l.get("rueda"):
                g["otra_rueda"] = max(g["otra_rueda"] or "", l["rueda"])
    out = []
    for (asset, local), g in sorted(grupos.items()):
        hoy_d = None
        if g["medido_hoy"] and g["todos_hoy"] and g["hoy_vp"] > 0:
            usd = g["hoy_v"] - g["hoy_vp"]
            hoy_d = {"pct": round(usd / g["hoy_vp"] * 100, 2), "usd": round(usd, 2)}
        dia = "hoy" if hoy_d else (_no_hoy(dia_txt(g["otra_rueda"], hoy)) if g["otra_rueda"] else None)
        sd = g["sin_dato"]
        p_usd = None if sd else round((g["valor"] - g["costo"]) / g["costo"] * 100, 2)
        p_ars = None if sd else round((g["valor"] - g["costo_hoy"]) / g["costo_hoy"] * 100, 2)
        out.append({"asset": asset, "local": local, "valor": round(g["valor"], 2),
                    "hoy": hoy_d, "dia_txt": dia,
                    "promedio_pct_usd": p_usd, "promedio_pct_ars": p_ars,
                    "promedio_sin_dato": MOTIVOS_PROMEDIO[sd] if sd else None})
    return out


def la_cartera_hoy(resumen: dict) -> Optional[dict]:
    """El renglón «Hoy tu cartera» del mapa, del resumen de `armar`: lo que se
    movieron tus activos en la rueda de HOY, sobre la cartera al cierre anterior
    (`pct_sobre_la_cartera`). None si hoy no se movió nada todavía (la rueda no
    abrió): no se muestra el de ayer como si fuera de hoy."""
    for m in resumen.get("movimiento") or []:
        if m.get("es_hoy") and m.get("pct_sobre_la_cartera") is not None:
            return {"pct": m["pct_sobre_la_cartera"], "usd": m["usd"], "mercados": m["mercados"]}
    return None


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
