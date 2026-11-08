"""termometro — «¿Cómo está el mercado?» (pieza 7, recuadro 7 del tablero).

QUÉ ES. Un número de 0 a 100 que DESCRIBE cómo se viene moviendo el mercado
entero, armado con tres reglas que la pantalla explica tal cual:

  · La mitad: qué parte de las acciones está arriba de su promedio de 200 días
    (la «tendencia de fondo» de la ficha). 60 % arriba suma 30 puntos.
  · Un cuarto: el S&P 500 contra sus promedios de 50 y de 200 días. Arriba de
    los dos suma 25; de uno, la mitad; de ninguno, 0.
  · Un cuarto: cuántas acciones cerraron en su máximo del año contra cuántas en
    su mínimo. Sólo máximos suma 25; mitad y mitad (o ninguno), la mitad.

Cada parte se muestra en puntos enteros que suman exactamente el número
(`senales_semana.repartir_enteros`).

QUÉ NO ES. No anticipa nada: la medición de la ficha (audit/09_ficha_tecnica,
70 series, 2 años) encontró que estos indicadores describen bien lo que pasó y
no adivinan mejor que el azar lo que sigue. Por eso el número nunca se traduce
en «tené X % invertido» (eso es una recomendación y roza la CNV) ni señala
papeles: sólo dice cuántos están de cada lado.

EL UNIVERSO es fijo, no lo que tienen los usuarios:
  · las ~500 empresas del S&P 500 (`home/sp500_constituyentes.json`, que deja
    `scripts/actualizar_sp500.py` desde la lista de Wikipedia; se pone al día
    una vez por trimestre);
  · el panel de acciones argentinas del mapa de calor (`home.market.MERVAL_TOP_25`).
    El índice Merval no tiene fuente (Yahoo dejó ^MERV): se usa el panel.
Cada acción se lee con la MISMA lectura que su ficha (`tecnico.para_la_cartera`
→ `tecnico.lectura`, en dólares: una acción argentina es su precio de BYMA ÷ el
MEP de cada día) y la misma regla de «alcista» que la Cartera y Señales
(`senales_semana._alcista`, que además descarta una lectura sin precios de la
última semana: `tecnico.lectura_vieja`, LA regla de «precio viejo»). Ninguna
regla está copiada acá.

CUÁNDO CORRE. Una vez por día, un rato DESPUÉS de la corrida nocturna de velas
(`toca`), en su propio trabajo: baja sólo lo que la noche no bajó (lo que
nadie tiene ni sigue) y no se suma a los ~2.000 pedidos de la noche, que es
donde Yahoo corta (auditoría de capacidad del 24/10). Lo dispara el cron de las
alertas, cada 10 minutos.

LA SEMANA PASADA. Cada día se guarda una fila (`termometro_diario`, por la
fecha de la última vela del S&P). «Hace una semana» es la fila de 7 a 13 días
antes. Para atrás NO se reconstruye: hasta que pase una semana desde que se
lanza, no aparece.
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import date, datetime, timedelta

log = logging.getLogger("termometro")

# Los pesos de cada parte (suman 100). La pantalla los muestra tal cual.
PESO_AMPLITUD = 50
PESO_INDICE = 25
PESO_MAXIMOS = 25
# Sin una buena parte del universo medida (Yahoo falló esa noche), el número
# no se guarda: compararía peras con manzanas contra el de la semana pasada.
COBERTURA_MINIMA = 0.8
# «Hace una semana»: la fila de entre 7 y 13 días antes (la de `senales_semana`).
DIAS_SEMANA = 7
DIAS_SEMANA_PASADA = 13
# Cuánto se espera después de la corrida de la noche antes de pedirle a Yahoo
# lo que falta: dos tandas seguidas son las que lo hacen cortar.
MINUTOS_DESPUES_DE_LA_NOCHE = 60
# Si la corrida de la noche no corrió (Railway dormido), desde esta hora de
# Argentina corre igual.
HORA_SIN_NOCHE = 6
# La fila de `velas_estado` donde el termómetro anota que corrió hoy (como
# `velas_diarias.MARCA_CORRIDA_NOCHE`: `~` no es un ticker).
MARCA_CORRIDA = "~corrida_termometro"

LEYENDA = "Describe cómo se mueve el mercado. No dice cuánto tener invertido ni es una recomendación."

_ARCHIVO_SP500 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "home", "sp500_constituyentes.json")

# El sector de cada acción del panel argentino, con la clasificación del S&P
# (GICS) que trae la lista de Wikipedia para las de afuera: las mismas claves
# que `frontend/src/utils/assetSector.js`.
SECTOR_PANEL = {
    "GGAL": "financiero", "BMA": "financiero", "BBAR": "financiero", "SUPV": "financiero",
    "VALO": "financiero", "BYMA": "financiero",
    "YPFD": "energia", "TGSU2": "energia", "TGNO4": "energia",
    "PAMP": "utilities", "CEPU": "utilities", "EDN": "utilities", "TRAN": "utilities",
    "DGCU2": "utilities", "CGPA2": "utilities",
    "ALUA": "materiales", "TXAR": "materiales", "LOMA": "materiales", "HARG": "materiales",
    "CRES": "consumo_bas", "AGRO": "industria", "COME": "industria",
    "MIRG": "consumo_disc", "CVH": "comunicacion", "GCLA": "comunicacion",
}


# ─── El universo ─────────────────────────────────────────────────────────────

def _lista_sp500() -> dict:
    with open(_ARCHIVO_SP500, encoding="utf-8") as f:
        return json.load(f)


def universo() -> list:
    """[{asset, local, grupo: 'sp500'|'panel', sector}]. `asset` y `local` como
    los lee la ficha (`tecnico.serie`): 'BRK.B' (afuera), ('GGAL', True)."""
    from home.market import MERVAL_TOP_25
    out = [{"asset": e["symbol"], "local": False, "grupo": "sp500", "sector": e["sector"]}
           for e in _lista_sp500()["empresas"]]
    for s in MERVAL_TOP_25:
        a = s[:-3] if s.endswith(".BA") else s
        out.append({"asset": a, "local": True, "grupo": "panel", "sector": SECTOR_PANEL.get(a)})
    return out


def tickers_yahoo() -> list:
    """Los tickers de Yahoo que hacen falta: los que `tecnico.serie` lee para
    cada acción del universo (la de afuera, o la de BYMA de una argentina) y el
    índice S&P 500."""
    from snapshots_job import simbolo_byma
    from velas_diarias import SP500, ticker_de_afuera
    ts = {simbolo_byma(u["asset"]) if u["local"] else ticker_de_afuera(u["asset"]) for u in universo()}
    ts.add(SP500)
    return sorted(ts)


# ─── La cuenta ───────────────────────────────────────────────────────────────

def _de_un_activo(x: dict, hoy: date) -> dict:
    """{'tendencia': 'alcista'|'bajista'|None, 'maximo': bool, 'minimo': bool}
    con la lectura de la ficha. Máximo y mínimo del año con la regla de la ficha
    («En su máximo» = a menos de 0,1 % del cierre más alto de los 12 meses,
    `tecnico.TOLERANCIA_MAXIMO`) y sólo con el año entero de velas."""
    import senales_semana
    import tecnico
    t = senales_semana._alcista(x, hoy)
    l = (x or {}).get("lectura") or {}
    maximo = minimo = False
    if t is not None and l.get("anio_completo"):
        precio, alto, bajo = l.get("precio"), l.get("maximo_12m"), l.get("minimo_12m")
        if precio and alto:
            maximo = precio >= alto * (1 - tecnico.TOLERANCIA_MAXIMO)
        if precio and bajo:
            minimo = precio <= bajo * (1 + tecnico.TOLERANCIA_MAXIMO)
    return {"tendencia": t, "maximo": maximo, "minimo": minimo}


def _pct(a: int, b: int):
    return round(a / b * 100, 1) if b else None


def _indice(conn, hoy: date) -> dict:
    """El S&P 500 contra sus promedios de 50 y 200 días, con `tecnico.lectura`
    (la de la ficha) sobre la serie del índice que ya guarda la noche. Sin
    precios de la última semana (`tecnico.lectura_vieja`) no cuenta."""
    import tecnico
    velas = tecnico.sp500(conn)
    if not velas:
        return {"disponible": False}
    cierres = [v["close"] for v in velas]
    l = tecnico.lectura(velas, tecnico.media(cierres, 50), tecnico.media(cierres, 200))
    if tecnico.lectura_vieja(l, hoy) or l.get("dist_media200") is None or l.get("dist_media50") is None:
        return {"disponible": False, "fecha": l.get("fecha")}
    arriba200, arriba50 = l["dist_media200"] >= 0, l["dist_media50"] >= 0
    return {"disponible": True, "fecha": l["fecha"], "arriba200": arriba200, "arriba50": arriba50,
            "dist200": round(l["dist_media200"], 2), "dist50": round(l["dist_media50"], 2),
            "puntos": PESO_INDICE * (arriba200 + arriba50) / 2}


def calcular(conn, hoy: date) -> dict:
    """El termómetro con las velas guardadas. `hoy` es el día ARGENTINO (una
    lectura sin precios de la última semana no cuenta: `tecnico.lectura_vieja`,
    vía `senales_semana._alcista`). Nunca inventa: sin el índice o
    con menos de `COBERTURA_MINIMA` del universo medido, `disponible` False."""
    import senales_semana
    import tecnico
    uni = universo()
    lecturas = tecnico.para_la_cartera(conn, [(u["asset"], u["local"]) for u in uni], hoy=hoy)
    por_clave = {(x["asset"], x["local"]): x for x in lecturas}
    cuentas = {g: {"alcistas": 0, "medidas": 0} for g in ("sp500", "panel")}
    sectores: dict = {}
    maximos = minimos = 0
    for u in uni:
        d = _de_un_activo(por_clave.get((u["asset"].upper(), u["local"])), hoy)
        if d["tendencia"] is None:
            continue
        alc = d["tendencia"] == "alcista"
        cuentas[u["grupo"]]["medidas"] += 1
        cuentas[u["grupo"]]["alcistas"] += alc
        if u["sector"]:
            s = sectores.setdefault(u["sector"], {"alcistas": 0, "medidas": 0})
            s["medidas"] += 1
            s["alcistas"] += alc
        maximos += d["maximo"]
        minimos += d["minimo"]
    alcistas = sum(c["alcistas"] for c in cuentas.values())
    medidas = sum(c["medidas"] for c in cuentas.values())
    indice = _indice(conn, hoy)
    base = {"universo": len(uni), "medidas": medidas}
    if not indice.get("disponible"):
        return {**base, "disponible": False, "motivo": "sin_indice"}
    if medidas < COBERTURA_MINIMA * len(uni):
        return {**base, "disponible": False, "motivo": "pocas_medidas"}
    amplitud = alcistas / medidas * 100
    crudos = [PESO_AMPLITUD * amplitud / 100, indice["puntos"],
              PESO_MAXIMOS * (maximos / (maximos + minimos) if (maximos + minimos) else 0.5)]
    # El número y sus tres partes en enteros que SUMAN el número: la pantalla
    # muestra «suma 28 de 50» y quien sume las tres tiene que llegar al mismo.
    # Redondeadas cada una por su lado, 27,9 + 25 + 11,6 daba 64,5 con un 64.
    puntaje = int(math.floor(sum(crudos) + 0.5))
    p_amplitud, p_indice, p_maximos = senales_semana.repartir_enteros(crudos, puntaje)
    indice = {**indice, "puntos": p_indice}
    return {
        **base, "disponible": True,
        # La fecha del número: la última vela del S&P (un día de mercado).
        "fecha": indice["fecha"],
        "puntaje": puntaje,
        "amplitud": {"pct": round(amplitud, 1), "alcistas": alcistas, "medidas": medidas,
                     "puntos": p_amplitud,
                     "sp500": {**cuentas["sp500"], "pct": _pct(cuentas["sp500"]["alcistas"], cuentas["sp500"]["medidas"])},
                     "panel": {**cuentas["panel"], "pct": _pct(cuentas["panel"]["alcistas"], cuentas["panel"]["medidas"])}},
        "indice": indice,
        "maximos": {"maximos": maximos, "minimos": minimos, "puntos": p_maximos},
        "sectores": {k: {**v, "pct": _pct(v["alcistas"], v["medidas"])} for k, v in sorted(sectores.items())},
    }


# ─── Guardar y leer ──────────────────────────────────────────────────────────

def guardar(conn, t: dict) -> bool:
    """Una fila por día de mercado. Si ese día ya estaba (la corrida volvió a
    correr), se pisa con la cuenta nueva: es el mismo día, no otro."""
    if not t.get("disponible"):
        return False
    conn.execute(
        """INSERT INTO termometro_diario (fecha, puntaje, detalle, calculado_el)
           VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT(fecha) DO UPDATE SET puntaje=excluded.puntaje,
             detalle=excluded.detalle, calculado_el=excluded.calculado_el""",
        (t["fecha"], t["puntaje"], json.dumps(t, ensure_ascii=False)))
    conn.commit()
    return True


def _fila(row) -> dict:
    return {**json.loads(row["detalle"]), "fecha": row["fecha"], "puntaje": row["puntaje"]}


def ultimo(conn, hoy: date) -> dict:
    """Lo que ve la pantalla: el último número guardado, el de hace una semana
    (de 7 a 13 días antes de ESE número) y si quedó viejo (`viejo`: su fecha, la
    última vela del S&P, es de antes de la última semana contada desde `hoy`;
    `tecnico.es_vieja`, LA regla de «precio viejo». Hasta el 06/11 eran 5 días
    acá). Sin filas, {'disponible': False}."""
    import tecnico
    row = conn.execute(
        "SELECT fecha, puntaje, detalle FROM termometro_diario ORDER BY fecha DESC LIMIT 1").fetchone()
    if not row:
        return {"disponible": False}
    t = _fila(row)
    f = date.fromisoformat(t["fecha"])
    antes = conn.execute(
        "SELECT fecha, puntaje FROM termometro_diario WHERE fecha <= ? AND fecha >= ? "
        "ORDER BY fecha DESC LIMIT 1",
        ((f - timedelta(days=DIAS_SEMANA)).isoformat(),
         (f - timedelta(days=DIAS_SEMANA_PASADA)).isoformat())).fetchone()
    t["semana_pasada"] = {"fecha": antes["fecha"], "puntaje": antes["puntaje"]} if antes else None
    t["viejo"] = tecnico.es_vieja(t["fecha"], hoy)
    lista = _lista_sp500()
    t["fuente"] = {"sp500_bajada": lista.get("bajada"), "pesos": {
        "amplitud": PESO_AMPLITUD, "indice": PESO_INDICE, "maximos": PESO_MAXIMOS}}
    t["leyenda"] = LEYENDA
    return t


# ─── Tu plata por sector ─────────────────────────────────────────────────────
# Cuánto de tu plata está en sectores donde la mayoría de las acciones del
# universo sube de fondo y cuánto donde la mayoría baja. El sector de cada
# papel tuyo es el MISMO que usa el termómetro (la lista del S&P 500 y
# `SECTOR_PANEL`): un CEDEAR de una empresa del S&P toma el de la empresa. Lo
# que no está en el universo (ETFs, cripto, bonos, efectivo, acciones de afuera
# del S&P o del panel) va a «sin sector», nombrado: nadie tiene que adivinar por
# qué su papel no aparece. No es la torta de sectores de la Cartera
# (`frontend/src/utils/assetSector.js`): ver la nota de la pieza 7.

# «La mayoría sube de fondo»: la mitad o más de las acciones del sector.
MAYORIA = 50.0


def sector_de(asset: str, local: bool):
    """El sector de un papel tuyo con la clasificación del termómetro, o None."""
    a = (asset or "").strip().upper()
    if a.endswith(".BA"):
        a, local = a[:-3], True
    if local:
        return SECTOR_PANEL.get(a)
    sp = {e["symbol"]: e["sector"] for e in _lista_sp500()["empresas"]}
    return sp.get(a) or sp.get(a.replace("-", "."))


def tu_plata(conn, uid: int, t: dict):
    """{'suben': {pct, sectores}, 'bajan': {pct, sectores}, 'sin_sector': {pct,
    papeles}} con tu plata valuada por el servidor (`senales_semana.cartera`) y
    el peso de cada papel de `senales_semana.peso` (LA cuenta del peso). Cada
    sector: {sector, mercado_pct (% de sus acciones que suben de fondo), pct
    (de tu plata), papeles: [de más a menos plata]}. Los % son enteros que suman
    100 (`_repartir_cien`). None si no tenés nada valuado o el termómetro no
    tiene número."""
    import senales_semana
    if not t or not t.get("disponible"):
        return None
    car = senales_semana.cartera(conn, uid)
    if not car["total"] > 0:
        return None
    mercado = t.get("sectores") or {}
    por_sector, sin = {}, {}
    for (asset, local), valor in car["tenencias"].items():
        if (asset, local) in por_sector or valor <= 0:
            continue
        sec = sector_de(asset, local)
        peso = senales_semana.peso(car, asset, local) or 0.0
        if sec and sec in mercado and mercado[sec].get("pct") is not None:
            por_sector.setdefault(sec, {})[asset] = por_sector.get(sec, {}).get(asset, 0.0) + peso
        else:
            sin[asset] = sin.get(asset, 0.0) + peso
    for nombre, clave in (("efectivo", "efectivo"), ("plazos fijos", "plazos_fijos")):
        if car.get(clave, 0) > 0:
            sin[nombre] = sin.get(nombre, 0.0) + car[clave] / car["total"]
    secs = sorted(por_sector, key=lambda k: -sum(por_sector[k].values()))
    pcts = senales_semana._repartir_cien([sum(por_sector[k].values()) for k in secs] + [sum(sin.values())])

    def _papeles(d):
        return [n for n, _ in sorted(d.items(), key=lambda x: -x[1])]
    grupos = {"suben": {"pct": 0, "sectores": []}, "bajan": {"pct": 0, "sectores": []}}
    for k, pct in zip(secs, pcts):
        m = mercado[k]["pct"]
        g = grupos["suben" if m >= MAYORIA else "bajan"]
        g["pct"] += pct
        g["sectores"].append({"sector": k, "mercado_pct": m, "pct": pct, "papeles": _papeles(por_sector[k])})
    grupos["sin_sector"] = {"pct": pcts[-1], "papeles": _papeles(sin)}
    return grupos


# ─── La corrida de cada día ──────────────────────────────────────────────────

def toca(conn, now: datetime) -> bool:
    """¿Hay que correr ahora? `now` en UTC (naive), como el cron. Una vez por
    día ARGENTINO: de 21:00 a medianoche de acá en UTC ya es mañana, y eso no
    puede hacerlo correr dos veces el mismo día. Espera a que la corrida de
    velas de la noche haya terminado hace `MINUTOS_DESPUES_DE_LA_NOCHE`; si la
    noche no corrió, desde las `HORA_SIN_NOCHE` de acá corre igual."""
    from fechas import dia_art, en_art
    from velas_diarias import MARCA_CORRIDA_NOCHE, instante_de_la_marca
    hoy = dia_art(now)

    def _marca(simbolo):
        r = conn.execute("SELECT ultima_corrida FROM velas_estado WHERE symbol=?", (simbolo,)).fetchone()
        return instante_de_la_marca(r["ultima_corrida"]) if r else None

    ya = _marca(MARCA_CORRIDA)
    if ya and dia_art(ya) >= hoy:
        return False
    noche = _marca(MARCA_CORRIDA_NOCHE)
    if noche and dia_art(noche) >= hoy:
        return now - noche >= timedelta(minutes=MINUTOS_DESPUES_DE_LA_NOCHE)
    return en_art(now).hour >= HORA_SIN_NOCHE


def correr(conn, *, bajar=None, hoy: str = None) -> dict:
    """Baja lo que falte del universo (sólo lo que la noche no bajó: lo que
    nadie tiene ni sigue), calcula el número del día y lo guarda. Anota que
    corrió aunque no haya podido guardar: mañana lo intenta de nuevo, no cada
    10 minutos."""
    from fechas import hoy_art
    import velas_diarias
    hoy = hoy or hoy_art()
    velas = velas_diarias.poner_al_dia(conn, tickers_yahoo(), bajar=bajar, hoy=hoy)
    t = calcular(conn, date.fromisoformat(hoy))
    guardado = guardar(conn, t)
    velas_diarias.anotar_marca(conn, MARCA_CORRIDA, filas=velas.get("filas", 0))
    conn.commit()
    res = {"velas": {k: (len(v) if isinstance(v, list) else v) for k, v in velas.items()},
           "guardado": guardado, "fecha": t.get("fecha"), "puntaje": t.get("puntaje"),
           "medidas": t.get("medidas"), "universo": t.get("universo")}
    if not guardado:
        res["motivo"] = t.get("motivo")
        log.warning("termómetro: no se guardó (%s): %s", t.get("motivo"), res)
    return res
