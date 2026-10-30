"""senales_semana — «Qué cambió esta semana en lo tuyo» (pieza 15).

Dos lugares con LA MISMA cuenta (`armar_semana`):
  · la pestaña «Tus señales» de Mercado → Novedades (GET /api/tus-senales);
  · el resumen de los sábados a las 10:00 de Argentina, por mail y/o
    notificación (`correr_si_toca`, que lo pega el cron de alertas).

Qué junta, por persona:
  · lo que TIENE (posiciones abiertas) y lo que sigue en su WATCHLIST: la noche
    ya guarda velas de las dos (`velas_diarias._seguimiento`);
  · de cada activo, lo que cambió en los últimos 7 días CORRIDOS contados desde
    HOY (`tecnico.cambios_desde`, la misma cuenta que la radiografía de la
    Cartera, las alertas técnicas y la tabla de la watchlist);
  · cuánto pesa cada tenencia y el % de la plata en activos con tendencia de
    fondo alcista, con la regla de la radiografía (precio ≥ promedio de 200
    días, en dólares; una lectura de hace más de 10 días no cuenta).

El VALOR de cada tenencia sale del motor de valuación del servidor
(`snapshots_job.compute_broker_value_usd`, el port de `computeBrokerValue` que
ya valúa las fotos diarias) con el último precio guardado y el dólar de
valuación de la pantalla. La radiografía de la Cartera lo calcula en la
pantalla con precios en vivo: puede diferir en un punto según la hora.

Las palabras de cada cambio también se arman acá (`texto_del_cambio`): las usan
la pantalla y el mail, así no se escriben dos veces. Nunca dicen qué hacer: lo
que se movió, en palabras de la ficha. «La fuerza cayó muy rápido» es lo único
que la medición de Rendi encontró algo mejor que el azar, y aun así se dice como
posibilidad (`POSIBILIDAD_REBOTE`).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

log = logging.getLogger("senales_semana")

# Los 7 días corridos del período: los de la radiografía (`tecnico.DIAS_CAMBIOS`).
from tecnico import DIAS_CAMBIOS as DIAS_SEMANA  # noqa: E402
# La regla de las filas de la Cartera (DIAS_LECTURA_VIEJA de
# frontend/src/utils/radiografia.js): una lectura cuya última vela es más vieja
# que esto no describe el precio de hoy.
DIAS_LECTURA_VIEJA = 10
# El resumen sale los sábados desde esta hora de Argentina (las velas del
# viernes se guardan a la medianoche; a las 10 ya no despierta a nadie).
DIA_RESUMEN = 5          # sábado (date.weekday)
HORA_RESUMEN = 10
# «La semana pasada»: el último % guardado de hasta 13 días antes (si faltó
# un sábado, más viejo que eso ya no es «la semana pasada»).
DIAS_SEMANA_PASADA = 13
CANALES = ("mail", "push", "ambos", "no")

# Adonde llevan el botón del mail, el «Cambiar o apagar» y la notificación: la
# pestaña «Señales de la semana» de Análisis técnico (se mudó de Novedades el
# 28/10; /novedades?tab=senales redirige ahí para los mails viejos).
URL_SENALES = "/analisis-tecnico?tab=senales"

NO_ES_RECOMENDACION = ("Muestra cómo se movieron los precios: no es una "
                       "recomendación para comprar ni vender.")
# La frase del mockup (recuadro 15). Sale de la medición de la ficha
# (audit/09_ficha_tecnica, 70 series, 2 años): después de que el RSI bajó de
# 30, el precio rebotó 5,7 de cada 10 veces contra 5,0 al azar. Es lo único con
# algo de ventaja; todo lo demás describe, no anticipa.
POSIBILIDAD_REBOTE = ("En la medición de Rendi (70 activos, 2 años), después de caídas así "
                      "el precio rebotó algo más seguido que lo que siguió cayendo. "
                      "Es una posibilidad, no una certeza.")

ETIQUETA = {
    "media200": "Tendencia de fondo",
    "media50": "Corto plazo",
    "rsi_bajo_30": "Cayó muy rápido",
    "rsi_sobre_70": "Subió muy rápido",
    "maximo_12m": "Máximo del año",
    "adx23": "Fuerza de la tendencia",
}


# ─── Palabras ────────────────────────────────────────────────────────────────

def _rsi_txt(r, nivel=None) -> str:
    """Como la ficha y el mail de las alertas: sin decimales, salvo que el
    redondeo caiga justo en el nivel que cruzó («bajó de 30, quedó en 30»)."""
    from alerts_engine import _fmt_rsi
    return _fmt_rsi(r, nivel)


def _adx_txt(a) -> str:
    """Espejo de `fmtAdx` (utils/tecnico.js): cerca de 23, un decimal cortado
    para abajo; si no, redondeado."""
    from money_fmt import fmt_num
    import tecnico
    if round(a) == tecnico.ADX_CLAVE:
        return fmt_num(int(a * 10) / 10, 1)
    return str(round(a))


def texto_del_cambio(c: dict) -> dict:
    """{etiqueta, tono, texto, extra} de un cambio de `tecnico.cambios_desde`.
    `texto` va después del ticker («AAPL quedó abajo…»). `tono`: 'pos' | 'neg' |
    'rsi' | 'adx' (el color de la pastilla)."""
    t, arriba = c["tipo"], c.get("sentido") == "arriba"
    extra = None
    if t == "media200":
        texto = ("pasó arriba de su promedio de 200 días: la tendencia de fondo se volvió alcista."
                 if arriba else
                 "quedó abajo de su promedio de 200 días: la tendencia de fondo se volvió bajista.")
        tono = "pos" if arriba else "neg"
    elif t == "media50":
        texto = ("pasó arriba de su promedio de 50 días: el corto plazo se volvió alcista."
                 if arriba else
                 "quedó abajo de su promedio de 50 días: el corto plazo se volvió bajista.")
        tono = "pos" if arriba else "neg"
    elif t in ("rsi_bajo_30", "rsi_sobre_70"):
        nivel = 30 if t == "rsi_bajo_30" else 70
        texto = f"tiene la fuerza (RSI) en {_rsi_txt(c.get('rsi'), nivel)}"
        if c.get("rsi_antes") is not None:
            texto += f": una semana de mercado antes estaba en {round(c['rsi_antes'])}."
        else:
            texto += "."
        # Sólo la caída tiene la frase: subir muy rápido no anticipó nada
        # mejor que el azar, y decir «suele frenar» sería inventar.
        extra = POSIBILIDAD_REBOTE if t == "rsi_bajo_30" else None
        tono = "rsi"
    elif t == "maximo_12m":
        texto = "cerró en su precio más alto de los últimos 12 meses."
        tono = "pos"
    else:   # adx23
        lado = {1: ", para arriba", -1: ", para abajo"}.get(c.get("squeeze"), "")
        texto = (f"tiene el ADX en {_adx_txt(c.get('adx') or 0)}: pasó 23, deja de ir de costado "
                 f"y marca dirección{lado}.")
        tono = "adx"
    return {"etiqueta": ETIQUETA[t], "tono": tono, "texto": texto, "extra": extra}


# ─── Qué tiene y qué sigue cada persona ──────────────────────────────────────

def _cedears():
    import velas_diarias
    return velas_diarias._cedears_de_byma()


def _es_lote_local(p: dict, ars: set, ar_usd: set, cedears) -> bool:
    """¿Acción ARGENTINA (no CEDEAR)? Espejo de `esLoteLocal` (utils/accionLocal.js):
    no es efectivo, ni CEDEAR (por tipo o por la lista de BYMA), ni cripto, y se
    valúa por su precio de BYMA (`position_price_key` termina en .BA — broker en
    pesos, sub-broker «· USD» o costo en pesos)."""
    from snapshots_job import position_price_key, _crypto_symbol_set
    if p.get("is_cash"):
        return False
    a = (p.get("asset") or "").upper()
    if (p.get("asset_type") or "").upper() == "CEDEAR" or a in cedears or a in _crypto_symbol_set():
        return False
    return str(position_price_key(p, ars, ar_usd)).upper().endswith(".BA")


def _dolar(conn, uid: int):
    """(tc, tc_cedear): el dólar de valuación de la pantalla y el de los .BA,
    como `compute_live_portfolio_value` (Reportes, el ✦ del inicio)."""
    import main
    from snapshots_job import _user_tc_cedear
    tc = main._live_valuation_rate(conn, uid)
    return tc, _user_tc_cedear(conn, uid, tc)


def cartera(conn, uid: int, cedears=None, dolar=None) -> dict:
    """{'tenencias': {(asset, local): valor_usd}, 'tipos': {(asset, local):
    asset_type}, 'sin_medir': valor_usd, 'efectivo': valor_usd, 'plazos_fijos':
    valor_usd, 'total': valor_usd}. Efectivo, bonos y plazos fijos suman al
    total (son plata tuya) pero no tienen tendencia: van a `sin_medir` (que es
    efectivo + plazos fijos) o, los bonos, a su propia tenencia sin lectura.
    Valor de cada lote = el motor del servidor (`compute_broker_value_usd`) con
    el último precio guardado."""
    import main
    from snapshots_job import (_broker_name_sets, build_price_symbols, compute_broker_value_usd,
                               read_last_prices)
    cedears = _cedears() if cedears is None else cedears
    brokers = [dict(r) for r in conn.execute(
        "SELECT id, name, currency, parent_broker_id FROM brokers WHERE user_id=?", (uid,)).fetchall()]
    positions = [dict(r) for r in conn.execute(
        "SELECT id, broker, asset, asset_type, is_cash, invested, quantity, commissions, "
        "price_override, currency FROM positions WHERE user_id=? AND COALESCE(quantity, 0) > 0",
        (uid,)).fetchall()]
    pfs = [dict(r) for r in conn.execute(
        "SELECT * FROM plazos_fijos WHERE user_id=? AND closed_at IS NULL", (uid,)).fetchall()]
    out = {"tenencias": {}, "tipos": {}, "sin_medir": 0.0, "efectivo": 0.0, "plazos_fijos": 0.0, "total": 0.0}
    if not positions and not pfs:
        return out
    tc, tc_cedear = dolar or _dolar(conn, uid)
    precios = read_last_prices(conn, build_price_symbols(positions, brokers))
    ars, ar_usd = _broker_name_sets(brokers)
    moneda = {b["name"]: b["currency"] for b in brokers}
    for p in positions:
        try:
            v = compute_broker_value_usd([p], precios, moneda.get(p["broker"], "USD"), tc,
                                         broker_name=p["broker"], cedear_rate=tc_cedear)["value"]
        except Exception as ex:
            log.warning("semana: no pude valuar %s de uid=%s: %s", p.get("asset"), uid, ex)
            continue
        if not v or v <= 0:
            continue
        out["total"] += v
        if p.get("is_cash"):
            out["sin_medir"] += v
            out["efectivo"] += v
            continue
        k = ((p["asset"] or "").upper(), _es_lote_local(p, ars, ar_usd, cedears))
        out["tenencias"][k] = out["tenencias"].get(k, 0.0) + v
        out["tipos"].setdefault(k, (p.get("asset_type") or "").upper())
    for pf in pfs:
        v = main._pf_value(pf)["valor_hoy"]
        v = v / tc_cedear if (pf.get("moneda") or "ARS").upper() == "ARS" and tc_cedear else v
        if v and v > 0:
            out["total"] += v
            out["sin_medir"] += v
            out["plazos_fijos"] += v
    return out


def peso(car: dict, asset: str, local=None):
    """Qué parte de toda tu plata (`car['total']`, de `cartera`) es `asset`: LA
    cuenta del peso de un activo, la de Tu lista («Sí · 12%»), la de Señales
    («Lo tenés · 12% de tu plata») y la de la ficha («Es el 12% de tu
    cartera», en «Cuánto se mueve»). Con `local` (True/False), sólo esa lectura
    (GGAL de BYMA aparte del ADR de Schwab, como Tu lista y Señales); sin
    `local`, el activo entero (la ficha: todos tus lotes de ese papel). None si
    no lo tenés o no hay total."""
    a = (asset or "").strip().upper()
    v = sum(x for (k, l), x in car["tenencias"].items() if k == a and (local is None or l == bool(local)))
    return v / car["total"] if v > 0 and car["total"] > 0 else None


def watchlist(conn, uid: int, cedears=None) -> dict:
    """{(asset, local): símbolo tal como está en la watchlist}. «GGAL.BA» es la
    acción argentina (local); «AAPL.BA» es el CEDEAR, que se lee por AAPL."""
    cedears = _cedears() if cedears is None else cedears
    out = {}
    for r in conn.execute("SELECT symbol FROM watchlist WHERE user_id=?", (uid,)).fetchall():
        s = (r["symbol"] or "").strip().upper()
        if not s:
            continue
        base = s[:-3] if s.endswith(".BA") else s
        out[(base, s.endswith(".BA") and base not in cedears)] = s
    return out


def _tesis(conn, uid: int) -> dict:
    """{ACTIVO: texto} de la última tesis de cada activo (pieza 11, «Tu
    tesis», `tesis.ultimas`). Hasta el 29/10 devolvía {} con un «al juntar:
    SELECT…» en un comentario: se juntó la pieza 11 y nadie lo llenó (auditoría
    B4 = A8 = C2). Ahora lo vigila test_tus_senales."""
    import tesis as _t
    return _t.ultimas(conn, uid)


# ─── La cuenta ───────────────────────────────────────────────────────────────

def _repartir_cien(valores: list) -> list:
    """Porcentajes enteros que suman 100 por el método del resto mayor
    (redondear cada uno por su lado puede dar 99 o 101). Era el espejo de
    `repartirCien` de la pantalla, que se borró el 28/10: el % se cuenta sólo acá."""
    total = sum(valores)
    if not total > 0:
        return [0 for _ in valores]
    crudos = [v / total * 100 for v in valores]
    pisos = [int(c) for c in crudos]
    falta = 100 - sum(pisos)
    for _, i in sorted(((c - p, i) for i, (c, p) in enumerate(zip(crudos, pisos))), reverse=True):
        if falta <= 0:
            break
        pisos[i] += 1
        falta -= 1
    return pisos


def _lectura_vieja(lectura: dict, hoy: date) -> bool:
    f = (lectura or {}).get("fecha")
    return bool(f) and (hoy - date.fromisoformat(f)).days > DIAS_LECTURA_VIEJA


def _alcista(x: dict, hoy: date):
    """'alcista' | 'bajista' | None (sin lectura): la tarjeta «Largo plazo» de
    la ficha (precio ≥ promedio de 200 días), como `tendencia()` de la radiografía."""
    if not x or not x.get("disponible"):
        return None
    l = x.get("lectura") or {}
    if _lectura_vieja(l, hoy) or l.get("media200") is None or l.get("dist_media200") is None:
        return None
    return "alcista" if l["dist_media200"] >= 0 else "bajista"


# Por qué algo va «sin lectura» (las claves de MOTIVOS_SIN_LECTURA de
# utils/radiografia.js, que pone las palabras): un bono o un fondo no se mide
# así; una acción sin velas todavía, aparece en un día; con menos de 200 días
# de mercado no hay promedio de 200; una última vela de hace más de 10 días no
# describe el precio de hoy.
# Como `noSeMide` de la pantalla: renta fija (`_FIXED_INCOME_TYPES`) y fondos.
_FONDOS = ("FCI", "FUND")


def _porque(x: dict, tipo: str, asset: str, hoy: date) -> str:
    from snapshots_job import _FIXED_INCOME_TYPES
    if tipo in _FIXED_INCOME_TYPES or tipo in _FONDOS or asset.startswith("FCI:"):
        return "no_se_mide"
    if not x or not x.get("disponible"):
        return "sin_historia"
    if _lectura_vieja(x.get("lectura"), hoy):
        return "vieja"
    return "pocos_dias"


def reparto(conn, uid: int, hoy: date, *, series: dict = None, cedears=None, dolar=None, car=None) -> dict:
    """LA cuenta del «% de tu plata en tendencia de fondo alcista» (28/10: una
    sola para la Cartera, el Panorama y la pestaña Señales de Análisis técnico y
    el mail de los sábados). Tu plata valuada por el servidor (`cartera`) y la
    tendencia de fondo de cada tenencia con la regla de la ficha (`_alcista`):

    {'pct': % alcista entero | None si nada tiene lectura,
     'grupos': {'alcista'|'bajista'|'sin': {'pct', 'nombres': [de más a menos plata]}},
     'motivos': [{'porque', 'nombres'}] de los sin lectura (las palabras las pone
                la pantalla, MOTIVOS_SIN_LECTURA),
     'semana_pasada': {'semana', 'pct'} | None}

    Los tres % suman 100 (`_repartir_cien`). Efectivo y plazos fijos cuentan en
    el total, sin lectura. `series`: el caché de lecturas de `armar_semana`."""
    import tecnico
    series = {} if series is None else series
    cedears = _cedears() if cedears is None else cedears
    car = car if car is not None else cartera(conn, uid, cedears, dolar)
    grupos = {"alcista": {}, "bajista": {}, "sin": {}}
    motivos = {}
    for k, valor in car["tenencias"].items():
        if k not in series:
            series[k] = tecnico.para_la_cartera(conn, [k], hoy=hoy)[0]
        g = _alcista(series[k], hoy) or "sin"
        grupos[g][k[0]] = grupos[g].get(k[0], 0.0) + valor
        if g == "sin":
            motivos.setdefault(_porque(series[k], car["tipos"].get(k, ""), k[0], hoy), []).append((valor, k[0]))
    for nombre, clave in (("efectivo", "efectivo"), ("plazos fijos", "plazos_fijos")):
        if car.get(clave, 0) > 0:
            grupos["sin"][nombre] = grupos["sin"].get(nombre, 0.0) + car[clave]
            motivos.setdefault("no_se_mide", []).append((car[clave], nombre))
    ids = ("alcista", "bajista", "sin")
    valores = [sum(grupos[g].values()) for g in ids]
    pcts = _repartir_cien(valores)
    con_lectura = valores[0] + valores[1] > 0
    orden = ("no_se_mide", "sin_historia", "pocos_dias", "vieja")
    return {
        "pct": pcts[0] if con_lectura else None,
        "grupos": {g: {"pct": pcts[i], "fraccion": (valores[i] / sum(valores)) if sum(valores) > 0 else 0,
                       "nombres": [n for n, _ in sorted(grupos[g].items(), key=lambda x: -x[1])]}
                   for i, g in enumerate(ids)},
        "motivos": [{"porque": m, "nombres": [n for _, n in sorted(motivos[m], key=lambda x: -x[0])]}
                    for m in orden if m in motivos],
        "semana_pasada": semana_pasada(conn, uid, hoy) if con_lectura else None,
    }


def semana_pasada(conn, uid: int, hoy: date):
    """{'semana', 'pct'} del último % guardado ANTES de hoy (hasta 13 días), o
    None: para atrás no se reconstruye, mientras no haya dato no aparece."""
    row = conn.execute(
        "SELECT semana, pct_alcista FROM tendencia_semanal "
        "WHERE user_id=? AND semana < ? AND semana >= ? AND pct_alcista IS NOT NULL "
        "ORDER BY semana DESC LIMIT 1",
        (uid, hoy.isoformat(), (hoy - timedelta(days=DIAS_SEMANA_PASADA)).isoformat())).fetchone()
    return {"semana": row["semana"], "pct": row["pct_alcista"]} if row else None


def armar_semana(conn, uid: int, hoy: date, *, series: dict = None, cedears=None, dolar=None,
                 desde: str = None, desde_de: dict = None) -> dict:
    """Lo que ve la pestaña y lo que dice el mail del sábado.

    {
      'desde', 'hasta': el período (desde exclusive: las velas posteriores),
      'alcista': lo de `reparto` (pct, grupos, motivos, semana_pasada) | None,
      'tenes': {'activos': con lectura, 'con_cambios'},
      'watchlist': cuántos activos sigue,
      'senales': [{asset, ficha, local, tenes, watchlist, peso, tesis,
                   tipo, fecha, sentido, …números…, etiqueta, tono, texto, extra}],
    }
    `series` es un caché {(asset, local): lectura} para la corrida del sábado,
    que arma la de cada activo una sola vez para todas las personas.
    `desde` (exclusive): desde cuándo se cuentan los cambios. La pestaña usa los
    últimos 7 días corridos. El mail cuenta CADA ACTIVO desde lo que ya contó el
    resumen anterior: `desde_de` {(asset, local): fecha} (`desde_del_mail`); el
    activo que no está ahí, desde `desde`. Agrega 'hasta_vela': {"NVDA|0":
    la última vela que se miró de ese activo} (lo que guarda el sábado)."""
    import tecnico
    series = {} if series is None else series
    cedears = _cedears() if cedears is None else cedears
    desde = desde or (hoy - timedelta(days=DIAS_SEMANA)).isoformat()
    car = cartera(conn, uid, cedears, dolar)
    wl = watchlist(conn, uid, cedears)
    tesis = _tesis(conn, uid)

    def _leer(k):
        # La lectura no depende de `desde`, los cambios sí: el caché va por
        # (activo, desde), y `reparto` (que sólo lee la lectura) reusa la misma.
        d = (desde_de or {}).get(k) or desde
        if (k, d) not in series:
            series[(k, d)] = tecnico.para_la_cartera(conn, [k], hoy=hoy, desde=d)[0]
            series.setdefault(k, series[(k, d)])
        return series[(k, d)]

    senales, con_lectura, con_cambios, hasta_vela = [], 0, set(), {}
    for k in sorted(set(car["tenencias"]) | set(wl)):
        x = _leer(k)
        f = (x.get("lectura") or {}).get("fecha") if x.get("disponible") else None
        if f:
            hasta_vela[_clave_marca(k)] = f
        tiene = k in car["tenencias"]
        if tiene:
            con_lectura += _alcista(x, hoy) is not None
        # Una serie cortada no tiene «esta semana» (los cambios ya cuentan desde
        # hoy, pero una lectura vieja tampoco describe el precio).
        if not x.get("disponible") or _lectura_vieja(x.get("lectura"), hoy):
            continue
        for c in x.get("cambios") or []:
            if tiene:
                con_cambios.add(k)
            senales.append({
                "asset": k[0], "local": k[1], "ficha": k[0] if tiene else wl[k],
                "tenes": tiene, "watchlist": k in wl,
                "peso": peso(car, *k) if tiene else None,
                "tesis": tesis.get(k[0]),
                **c, **texto_del_cambio(c),
            })
    orden = {t: i for i, t in enumerate(tecnico.TIPOS_CAMBIO)}
    # El día más nuevo primero; adentro, lo tuyo por peso y después la watchlist.
    senales.sort(key=lambda s: (s["fecha"], s["tenes"], s["peso"] or 0, -orden[s["tipo"]]), reverse=True)

    # El % y su reparto: LA cuenta (`reparto`), la misma que la Cartera y el
    # Panorama. Sin nada con lectura, None (como siempre).
    r = reparto(conn, uid, hoy, series=series, cedears=cedears, car=car)
    alcista = r if r["pct"] is not None else None
    return {
        "desde": desde, "hasta": hoy.isoformat(),
        "alcista": alcista,
        "tenes": {"activos": con_lectura, "con_cambios": len(con_cambios)},
        "watchlist": len(wl),
        "senales": senales,
        "hasta_vela": hasta_vela,
    }


# ─── El resumen de los sábados ───────────────────────────────────────────────

def canal(conn, uid: int) -> str:
    """'mail' | 'push' | 'ambos' | 'no'. Sin fila: 'no'. Es opt-in, como el
    resumen del mercado (`market_brief.brief_enabled`): un mail semanal que
    nadie pidió es cómo se llega a la pestaña «Actualizaciones» de Gmail."""
    row = conn.execute("SELECT canal FROM resumen_semanal_prefs WHERE user_id=?", (uid,)).fetchone()
    return row["canal"] if row and row["canal"] in CANALES else "no"


def toca(now: datetime) -> bool:
    """¿Es sábado desde las 10:00 de ARGENTINA? (`now` en UTC, como el cron)."""
    from fechas import en_art
    art = en_art(now)
    return art.weekday() == DIA_RESUMEN and art.hour >= HORA_RESUMEN


def _personas(conn) -> list:
    """Quiénes tienen algo que mirar: posiciones abiertas, plazos fijos o watchlist."""
    rows = conn.execute(
        "SELECT DISTINCT user_id FROM positions WHERE COALESCE(quantity, 0) > 0 "
        "UNION SELECT DISTINCT user_id FROM watchlist "
        "UNION SELECT DISTINCT user_id FROM plazos_fijos WHERE closed_at IS NULL").fetchall()
    return sorted(r[0] for r in rows)


def _titular(senales: list) -> str:
    """«Tu semana: AAPL quedó abajo de su promedio de 200 días y 4 cambios más».
    Nombra el cambio más importante de lo que TENÉS (por tipo, después por peso);
    si no tenés nada que cambió, el de la watchlist."""
    top = _por_importancia(senales)[0]
    texto = top["texto"].split(":")[0].rstrip(".")
    resto = len(senales) - 1
    mas = f" y {resto} {'cambio' if resto == 1 else 'cambios'} más" if resto else ""
    return f"Tu semana: {top['asset']} {texto}{mas}"


def _por_importancia(senales: list) -> list:
    """Lo que tenés antes que la watchlist; adentro, por tipo (TIPOS_CAMBIO) y
    por peso."""
    import tecnico
    orden = {t: i for i, t in enumerate(tecnico.TIPOS_CAMBIO)}
    return sorted(senales, key=lambda x: (not x["tenes"], orden[x["tipo"]], -(x["peso"] or 0)))


def _y(nombres: list) -> str:
    return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]


# Cuántos activos se nombran en el mail, uno por renglón (con su cambio más
# importante); lo demás se cuenta al final, como el recuadro 15.
RENGLONES_MAIL = 3


def contenido_del_mail(semana: dict, cuenta: str = None) -> dict:
    """Los argumentos de `emails.send_alert_email` para el resumen. `cuenta`: el
    nombre del cliente cuando el mail es de una cuenta que administra un asesor
    (lo pasa `alerts_engine.entrega`): entonces no es «tu plata» ni «tu
    watchlist», es la de Juan."""
    tu = {"plata": "tu plata", "lo": "lo tuyo", "watchlist": "tu watchlist", "tesis": "Tu tesis"}
    if cuenta:
        tu = {"plata": "la plata", "lo": "sus activos", "watchlist": f"la watchlist de {cuenta}",
              "tesis": f"La tesis de {cuenta}"}
    lista = _por_importancia(semana["senales"])
    primeros, nombrados = [], []
    for x in lista:
        if x["asset"] not in nombrados and len(nombrados) < RENGLONES_MAIL:
            nombrados.append(x["asset"])
            primeros.append(x)
    lineas = []
    for x in primeros:
        # Lo que no tenés lo dice: «MSFT pasó arriba…» se leía como algo tuyo.
        quien = x["asset"] if x["tenes"] else f"{x['asset']} (en {tu['watchlist']})"
        linea = f"{quien} {x['texto']}"
        if x.get("tesis"):
            import tesis as _tesis
            linea += f" {tu['tesis']}: «{_tesis.para_una_linea(x['tesis'])}»."
        lineas.append(linea)
    resto = [x for x in lista if x not in primeros]
    if resto:
        quienes = list(dict.fromkeys(x["asset"] for x in resto))
        lineas.append(f"{len(resto)} {'cambio' if len(resto) == 1 else 'cambios'} más, en {_y(quienes)}.")
    a = semana.get("alcista")
    watch = "su watchlist" if cuenta else tu["watchlist"]
    if a:
        detail = f"el {a['pct']}% de {tu['plata']} está en activos con tendencia de fondo alcista"
        if a.get("semana_pasada"):
            detail += f" (la semana pasada, {round(a['semana_pasada']['pct'])}%)"
        detail += f". Esto se movió en {tu['lo']} y en {watch}:"
    else:
        detail = f"esto se movió esta semana en {tu['lo']} y en {watch}:"
    return {
        "heading": _titular(semana["senales"]), "detail": detail, "lines": lineas,
        "cta_path": URL_SENALES, "cta_label": "Ver los cambios",
        "pie": ("Te llega los sábados porque lo pediste.", "Cambiar o apagar",
                URL_SENALES),
        "aclaracion": NO_ES_RECOMENDACION,
    }


def _armar_envio(conn, uid: int, semana: dict) -> dict:
    """La entrega de `alerts_engine.entrega` (destino, cliente, mail y push),
    la MISMA que la de las alertas: una cuenta administrada le llega al asesor,
    con el nombre del cliente, sus links a /clientes y sin «tu plata». Todo lo
    que se puede romper al armar el mail pasa ACÁ, antes de marcar la semana
    como hecha: un error al armarlo no puede comerse el resumen de esa persona
    sin mandarlo."""
    from alerts_engine import entrega
    return entrega(conn, uid, lambda cuenta: contenido_del_mail(semana, cuenta))


def _entregar(conn, via: str, envio: dict) -> tuple:
    """(push_ok, mail_ok). Por el camino de las alertas: `send_alert_email` y
    `_send_push_to_user`, con lo que armó `entrega`."""
    import main
    from billing import emails
    destino = envio["destino"]
    push_ok = mail_ok = False
    if via in ("push", "ambos"):
        try:
            push_ok = main._send_push_to_user(destino, {
                "title": "Rendi · Tu semana",
                "body": f"{envio['push']['titulo']}. {NO_ES_RECOMENDACION}",
                "url": envio["push"]["url"],
                "tag": "resumen-semanal",
            }) > 0
        except Exception as ex:
            log.warning("semana: push uid=%s falló: %s: %s", destino, type(ex).__name__, ex, exc_info=True)
    if via in ("mail", "ambos"):
        try:
            row = conn.execute("SELECT email, name FROM users WHERE id=?", (destino,)).fetchone()
            if row and row["email"]:
                mail_ok = bool(emails.send_alert_email(to=row["email"], user_name=row["name"] or "",
                                                       **envio["mail"]))
        except Exception as ex:
            log.warning("semana: mail uid=%s falló: %s: %s", destino, type(ex).__name__, ex, exc_info=True)
    return push_ok, mail_ok


# Lo más atrás que mira el mail de los sábados, aunque el resumen anterior
# sea más viejo (el cron se cayó varios sábados, o la persona recién vuelve):
# más que esto ya no es «tu semana».
DIAS_MAX_MAIL = 28


def _clave_marca(k) -> str:
    return f"{k[0]}|{int(bool(k[1]))}"


def marcas_json(hasta_vela: dict) -> str:
    """Cómo se guardan las marcas en `tendencia_semanal.hasta_vela`:
    {"NVDA|0": "2026-10-23", "GGAL|1": "2026-10-23"} (activo|acción local)."""
    import json
    return json.dumps(dict(sorted(hasta_vela.items())))


def desde_del_mail(conn, uid: int, hoy: date) -> tuple:
    """(desde, {(asset, local): desde}): desde cuándo (exclusive) cuenta los
    cambios el mail de ESTE sábado, por activo. Cada activo, desde la última
    vela SUYA que ya contó un resumen anterior (la marca de `hasta_vela`); el
    que no tiene marca, desde el viernes anterior al último resumen (o los 7
    días de la pestaña si no hubo ninguno). Nunca después de los 7 días y nunca
    antes de `DIAS_MAX_MAIL`.

    🔴 POR QUÉ, en tres vueltas (auditoría B3 y su re-test, 29/10):
      · Los 7 días corridos desde HOY dejaban afuera una vela de SÁBADO: el
        sábado a las 10 todavía no existe, y el sábado siguiente «los 7 días»
        empiezan después. Una cripto que cruzaba un sábado no salía nunca.
      · La primera marca era UNA por persona (la vela más nueva de todos sus
        activos): si BTC se atrasaba una noche y MSFT llegaba, la marca quedaba
        en el viernes y el viernes de BTC no salía nunca. Cada activo tiene su
        última vela, como en las alertas técnicas ('<activo>#velas').
      · El resumen anterior se buscaba hasta 13 días atrás: si un sábado no
        corría el cron, el siguiente no lo encontraba y la semana del medio se
        perdía entera. Ahora se busca hasta `DIAS_MAX_MAIL`, y la marca de cada
        activo sale del resumen más nuevo que la tenga."""
    import json
    base = (hoy - timedelta(days=DIAS_SEMANA)).isoformat()
    piso = (hoy - timedelta(days=DIAS_MAX_MAIL)).isoformat()
    filas = conn.execute(
        "SELECT semana, hasta_vela FROM tendencia_semanal WHERE user_id=? AND semana < ? AND semana >= ? "
        "ORDER BY semana DESC",
        (uid, hoy.isoformat(), piso)).fetchall()
    if not filas:
        return base, {}
    por_defecto = min(base, (date.fromisoformat(filas[0]["semana"]) - timedelta(days=1)).isoformat())
    marcas: dict = {}
    for f in filas:
        try:
            m = json.loads(f["hasta_vela"] or "{}")
        except (TypeError, ValueError):
            m = None
        if not isinstance(m, dict):
            # Una fila de antes de las marcas por activo (una fecha suelta, de
            # 61c7be12): vale para todos los que todavía no tienen una.
            if f["hasta_vela"]:
                por_defecto = min(por_defecto, max(piso, str(f["hasta_vela"])))
            continue
        for clave, fecha in m.items():
            marcas.setdefault(clave, fecha)
    desde_de = {}
    for clave, fecha in marcas.items():
        asset, _, local = clave.rpartition("|")
        desde_de[(asset, local == "1")] = max(piso, min(base, fecha))
    return por_defecto, desde_de


def correr(conn, hoy: date, *, solo: int = None) -> dict:
    """El resumen de ESTA semana (`hoy` = el sábado) para todas las personas:
    guarda el % de cada una (la «semana pasada» de dentro de 7 días) y manda el
    resumen a quien lo pidió y tuvo cambios. Una vez por persona y semana: la
    fila de `tendencia_semanal` se escribe ANTES de mandar (como las alertas: un
    deploy a mitad no duplica, a lo sumo se pierde uno)."""
    series: dict = {}
    cedears = _cedears()
    semana_iso = hoy.isoformat()
    res = {"personas": 0, "guardadas": 0, "mandadas": 0, "sin_cambios": 0, "errores": 0}
    for uid in ([solo] if solo else _personas(conn)):
        res["personas"] += 1
        if conn.execute("SELECT 1 FROM tendencia_semanal WHERE user_id=? AND semana=?",
                        (uid, semana_iso)).fetchone():
            continue
        # Armar lo de cada persona va en su punto de guardado (auditoría C1,
        # 29/10): en Postgres, una consulta que falla aborta la transacción y la
        # persona SIGUIENTE reventaba en su primer SELECT: nadie después de ella
        # recibía el resumen ese sábado. Con esto se deshace sólo lo suyo.
        from pgsesion import si_falla_se_deshace_solo_esto
        try:
            with si_falla_se_deshace_solo_esto(conn, "semana_de_una_persona"):
                desde, desde_de = desde_del_mail(conn, uid, hoy)
                sem = armar_semana(conn, uid, hoy, series=series, cedears=cedears,
                                   desde=desde, desde_de=desde_de)
                via = canal(conn, uid)
                mandar = via != "no" and bool(sem["senales"])
                envio = _armar_envio(conn, uid, sem) if mandar else None
        except Exception as ex:
            log.error("semana: no pude armar el resumen de uid=%s: %s: %s", uid,
                      type(ex).__name__, ex, exc_info=True)
            res["errores"] += 1
            continue
        conn.execute(
            "INSERT INTO tendencia_semanal (user_id, semana, pct_alcista, cambios, canal, hasta_vela) "
            "VALUES (?,?,?,?,?,?)",
            (uid, semana_iso, sem["alcista"]["pct"] if sem["alcista"] else None,
             len(sem["senales"]), via if mandar else None, marcas_json(sem["hasta_vela"])))
        conn.commit()
        res["guardadas"] += 1
        if not mandar:
            res["sin_cambios"] += via != "no"
            continue
        push_ok, mail_ok = _entregar(conn, via, envio)
        conn.execute("UPDATE tendencia_semanal SET push_ok=?, mail_ok=? WHERE user_id=? AND semana=?",
                     (int(push_ok), int(mail_ok), uid, semana_iso))
        conn.commit()
        res["mandadas"] += 1
    return res


def correr_si_toca(conn, now: datetime = None) -> dict:
    """Lo pega el cron de alertas cada ~10 minutos: el sábado desde las 10:00
    de Argentina corre; las pasadas siguientes no hacen nada (cada persona ya
    tiene su fila de esta semana)."""
    from fechas import dia_art
    now = now or datetime.utcnow()
    if not toca(now):
        return {"esperando": "sábados desde las 10:00"}
    return correr(conn, dia_art(now))
