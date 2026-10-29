"""Cuánto se mueve un papel: su peor caída, un día normal y lo que se movió el
precio después de cada balance y de cada dividendo.

QUÉ ES. Los números de «Cuánto se mueve este papel» de la ficha del activo y
de los globos de los balances («B») y dividendos («D») del gráfico. Son DATOS
de lo que ya pasó, nunca pronósticos: la verificación del 23/10 (70 activos ×
2 años) mostró que los indicadores técnicos describen bien pero no anticipan
mejor que el azar. Por eso acá no hay ninguna cuenta que mire para adelante.

SOBRE QUÉ SERIE. La misma del gráfico (`tecnico.serie`), en la moneda del
gráfico: un CEDEAR en dólares es la acción de afuera; en pesos, el CEDEAR. Las
palabras las pone la pantalla (`frontend/src/utils/movimiento.js`).

LAS CUENTAS
  · Un día normal: NO se calcula acá con otra regla: es el de la lectura
    técnica (`tecnico.movimiento_diario`, desvío de la variación de cierre
    contra cierre anterior) sobre el ÚLTIMO AÑO, el mismo número que la tarjeta
    «Cuánto se mueve» (A5, 29/10). Un «día malo normal» es una baja de ese
    tamaño; se cuenta además cada cuántos días de mercado pasó una baja así o
    peor, para que el «normal» sea un dato.
  · El S&P 500 en el MISMO año y la misma moneda (en pesos, × el MEP de cada
    día), con la misma cuenta, para comparar.
  · La peor caída: la mayor baja de un máximo a un piso posterior dentro de los
    2 años (de cierre a cierre), y cuántos días tardó desde el piso en volver a
    cerrar a la altura de aquel máximo (o que todavía no volvió).
  · La caída desde el máximo del año NO se calcula acá: es la de la lectura
    técnica (`tecnico.lectura`, `dist_maximo_12m`), una sola cuenta.
"""
from __future__ import annotations

from datetime import date, timedelta

# El período de «Cuánto se mueve»: 2 años de calendario.
DIAS_VENTANA = 730
# Con menos días de mercado que esto no se publica nada (el desvío de 20 días
# no es «un día normal» de nadie).
MIN_DIAS = 60
# Un balance o un dividendo cuya reacción cae más lejos que esto del evento
# (un hueco en la serie) no se mide: sería otra cosa.
MAX_DIAS_HASTA_LA_REACCION = 7


def ventana(velas: list, dias: int = DIAS_VENTANA) -> list:
    """Las velas de los últimos `dias` días CORRIDOS hasta la última."""
    if not velas:
        return []
    piso = (date.fromisoformat(velas[-1]["date"]) - timedelta(days=dias)).isoformat()
    return [v for v in velas if v["date"] > piso]


def peor_caida(velas: list):
    """La mayor baja de un máximo a un piso posterior, de cierre a cierre.
    {pico: {fecha, precio}, piso: {fecha, precio}, pct, volvio: fecha|None,
    dias_para_volver: días de mercado desde el piso, dias_corridos_para_volver}.
    None si nunca bajó de un máximo anterior."""
    if not velas:
        return None
    i_pico, mejor = 0, None
    for i, v in enumerate(velas):
        if v["close"] > velas[i_pico]["close"]:
            i_pico = i
        caida = v["close"] / velas[i_pico]["close"] - 1.0
        if caida < 0 and (mejor is None or caida < mejor[2]):
            mejor = (i_pico, i, caida)
    if mejor is None:
        return None
    ip, iv, caida = mejor
    pico, piso = velas[ip], velas[iv]
    i_vuelta = next((k for k in range(iv + 1, len(velas)) if velas[k]["close"] >= pico["close"]), None)
    vuelta = velas[i_vuelta] if i_vuelta is not None else None
    return {
        "pico": {"fecha": pico["date"], "precio": pico["close"]},
        "piso": {"fecha": piso["date"], "precio": piso["close"]},
        "pct": caida * 100.0,
        "volvio": vuelta["date"] if vuelta else None,
        "dias_para_volver": (i_vuelta - iv) if vuelta else None,
        "dias_corridos_para_volver": ((date.fromisoformat(vuelta["date"]) - date.fromisoformat(piso["date"])).days
                                      if vuelta else None),
    }


def dia_normal(velas: list, sp: list = None):
    """Un día normal del papel y del S&P 500 en el ÚLTIMO AÑO, con LA cuenta de
    la lectura técnica (`tecnico.movimiento_diario` sobre `tecnico.velas_del_anio`):
    es el mismo número que «su día normal del último año» de la tarjeta «Cuánto
    se mueve». Antes era otra cuenta (desvío de muestra) sobre los 2 años del
    gráfico y la misma ficha decía «1,1 %» y «±2,3 %» (auditoría A 29/10, A5).
    `sp`: las velas del S&P en la misma moneda (se cortan a las fechas del
    papel). {desvio_pct, desde, dias, dias_malos, sp500_desvio_pct,
    veces_el_sp500} o None."""
    import tecnico
    anio = tecnico.velas_del_anio(velas)
    cierres = [v["close"] for v in anio]
    xs = tecnico.cambios_diarios(cierres)
    d = tecnico.movimiento_diario(cierres)
    if d is None or len(xs) < MIN_DIAS:
        return None
    malos = sum(1 for x in xs if x * 100.0 <= -d)
    desde, hasta = anio[0]["date"], anio[-1]["date"]
    sp_v = [v["close"] for v in (sp or []) if desde <= v["date"] <= hasta]
    d_sp = tecnico.movimiento_diario(sp_v) if len(sp_v) >= MIN_DIAS else None
    return {
        "desvio_pct": d,
        "desde": desde,
        "dias": len(xs),
        "dias_malos": malos,
        "sp500_desvio_pct": d_sp,
        "veces_el_sp500": (d / d_sp) if d_sp else None,
    }


def calcular(velas: list, sp: list = None, lectura: dict = None) -> dict:
    """Todo «Cuánto se mueve este papel» sobre la serie del gráfico. `lectura`:
    la de `tecnico.lectura` sobre la MISMA serie (de ahí sale la caída desde el
    máximo del año). {disponible: False} con menos de MIN_DIAS días."""
    v = ventana(velas)
    if len(v) < MIN_DIAS:
        return {"disponible": False, "dias": len(v)}
    lectura = lectura or {}
    return {
        "disponible": True,
        "desde": v[0]["date"],
        "hasta": v[-1]["date"],
        "peor_caida": peor_caida(v),
        "dia_normal": dia_normal(v, sp),
        "desde_el_maximo": ({"pct": lectura.get("dist_maximo_12m"), "maximo": lectura.get("maximo_12m"),
                             "anio_completo": lectura.get("anio_completo")}
                            if lectura.get("dist_maximo_12m") is not None else None),
    }


# ─── Lo que se movió el precio después de un evento ─────────────────────────

def reaccion(velas: list, fecha: str, momento: str = None):
    """Cuánto se movió el precio con un evento del día `fecha`:
      · 'antes_del_cierre' (un balance publicado antes del cierre, o el día de
        corte de un dividendo, que se nota desde la apertura): el cierre de ESE
        día de mercado contra el anterior;
      · 'despues_del_cierre' (un balance publicado con el mercado cerrado): el
        cierre del día de mercado SIGUIENTE contra el de ese día;
      · None (no se sabe la hora): de ese día al siguiente, los dos juntos.
    {desde, hasta, pct, cuando} o None si la serie no lo cubre."""
    if not velas or not fecha:
        return None
    fechas = [v["date"] for v in velas]
    i_desde = i_hasta = None
    if momento == "antes_del_cierre":
        i_hasta = next((i for i, d in enumerate(fechas) if d >= fecha), None)
        i_desde = i_hasta - 1 if i_hasta else None
        cuando = "ese_dia"
    elif momento == "despues_del_cierre":
        i_desde = max((i for i, d in enumerate(fechas) if d <= fecha), default=None)
        i_hasta = i_desde + 1 if i_desde is not None and i_desde + 1 < len(fechas) else None
        cuando = "al_otro_dia"
    else:
        i_desde = max((i for i, d in enumerate(fechas) if d < fecha), default=None)
        i_hasta = next((i for i, d in enumerate(fechas) if d > fecha), None)
        cuando = "dos_dias"
    if i_desde is None or i_hasta is None or i_hasta <= i_desde:
        return None
    d_ev = date.fromisoformat(fecha)
    if (abs((date.fromisoformat(fechas[i_hasta]) - d_ev).days) > MAX_DIAS_HASTA_LA_REACCION
            or abs((d_ev - date.fromisoformat(fechas[i_desde])).days) > MAX_DIAS_HASTA_LA_REACCION):
        return None
    a, b = velas[i_desde]["close"], velas[i_hasta]["close"]
    if not a or b is None:
        return None
    return {"desde": fechas[i_desde], "hasta": fechas[i_hasta], "pct": (b / a - 1.0) * 100.0, "cuando": cuando}


def eventos_del_grafico(velas: list, balances: list, dividendos: list, moneda_dividendo: str) -> list:
    """Los balances y dividendos que caen dentro de la serie del gráfico, cada
    uno con lo que se movió el precio (`reaccion`), ordenados por fecha.
      · balances: [{fecha, momento}] (momento puede ser None)
      · dividendos: [{ex_date, por_accion}] — el día de corte
    Cada uno: {tipo: 'balance'|'dividendo', fecha, momento, monto, moneda,
    reaccion}."""
    if not velas:
        return []
    desde, hasta = velas[0]["date"], velas[-1]["date"]
    out = []
    for b in balances or []:
        f = b.get("fecha")
        if f and desde <= f <= hasta:
            out.append({"tipo": "balance", "fecha": f, "momento": b.get("momento"),
                        "reaccion": reaccion(velas, f, b.get("momento"))})
    for d in dividendos or []:
        f = d.get("ex_date")
        if f and desde <= f <= hasta:
            out.append({"tipo": "dividendo", "fecha": f, "monto": d.get("por_accion"),
                        "moneda": moneda_dividendo,
                        "reaccion": reaccion(velas, f, "antes_del_cierre")})
    return sorted(out, key=lambda e: (e["fecha"], e["tipo"]))
