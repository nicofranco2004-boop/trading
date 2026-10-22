"""Cambios de ratio de CEDEAR: la lista única.

QUÉ ES. Cuando un CEDEAR cambia de ratio (Comafi pasa Apple de 10 a 20 CEDEARs
por acción) o la acción de afuera se divide (XLE 2 a 1), cada CEDEAR pasa a
valer la mitad y al tenedor le acreditan el doble. La tabla `cambios_ratio`
guarda cada uno de esos cambios: qué CEDEAR, el primer día que BYMA cotizó a la
escala nueva, por cuánto se multiplicó la cantidad, y si está CONFIRMADO o es
DUDOSO. Es la misma lista para el aviso «Ajustar» de Posiciones (main.py,
`_fetch_ba_splits`) y para cualquier gráfico en pesos que tenga que empalmar la
serie: dos reglas distintas cuentan dos historias distintas.

POR QUÉ NO ALCANZA CON YAHOO. Medido el 22/10/2026 sobre los CEDEARs de BYMA:
la lista de splits de Yahoo para la especie en pesos (`AAPL.BA`) viene VACÍA en
33 cambios reales de los últimos 3 años (los 27 del 24/01/2024, TQQQ en
noviembre de 2025, XLE/XLU/XLB/XLK/XLY en diciembre de 2025). A veces los anota
en la especie en dólares (`AAPLD.BA`), que Rendi no valúa. Y al revés, anota
cosas que no le cambian la cantidad a nadie: a 3D Systems (DDD.BA) le copió la
agrupación de DuPont.

CÓMO SE DETECTA. El cociente «precio del CEDEAR en pesos ÷ precio de la acción
en Nueva York» es más o menos «dólar ÷ ratio»: se mueve despacio. Si salta más
de 25% de un día al otro y se queda (las 5 ruedas de después contra las 5 de
antes), cambió el ratio. Ese salto entra como CONFIRMADO sólo si además:
  · el factor es redondo (2, 3… o 1/2, 1/3…, con 5% de margen);
  · el precio en pesos se movió de verdad ese día (FNMA tuvo el precio quieto
    en $240 durante meses y el cociente saltaba porque se movía Nueva York);
  · Nueva York no anotó ese día un «split» con factor raro: eso es una escisión
    (DuPont el 03/11/2025 separó Qnity: el CEDEAR cayó 57% y nadie recibió más
    CEDEARs de DD; ajustar multiplicaba la tenencia por 2,38);
  · si la cantidad BAJA (factor < 1), Nueva York también lo anotó. Los únicos
    casos medidos sin esa confirmación son los precios rotos del 28/05/2024.
NO se exige que Nueva York se haya movido poco: el cociente ya descuenta a Nueva
York, y ese filtro tiraba NFLX el 24/01/2024 (ese día subió 10,7% por su
balance).

Lo que Yahoo anota (en pesos o en dólares) entra como CONFIRMADO si el factor es
redondo y Nueva York anotó lo mismo esos días (un split de afuera que el CEDEAR
trasladó: NVDA, DD el 24/06/2026), si el precio en pesos muestra el escalón, o
si lo muestra la historia de BYMA (data912), que guarda el cierre como fue ese
día (SPY el 29/05/2026, YPFD el 03/08/2026).

Si no, DUDOSO: no dispara ningún aviso, queda para que lo mire una persona.

UN AJUSTE MAL HECHO MULTIPLICA TENENCIAS (ver `_SPLIT_PRICE_EVIDENCE_ENABLED` en
main.py). Por eso lo dudoso nunca llega al aviso, y el aviso sigue siendo un
botón que toca la persona, nunca un ajuste automático.

CUÁNDO CORRE. De noche, después de `velas_diarias.correr` (que ya guarda las dos
series de cada CEDEAR que alguien tiene): `correr(conn)`. Lo que no está en la
ventana de 3 años de las velas NO se borra: un cambio de 2024 tiene que seguir
existiendo en 2028 para el lote que se compró antes.

FILAS A MANO. `origen='manual'` no la pisa nunca la corrida: sirve para
confirmar o descartar un caso que la regla no puede decidir sola.
"""
import logging
import statistics
import time
from datetime import date

log = logging.getLogger(__name__)

# Cuánto tiene que saltar el cociente de un día al otro.
UMBRAL_SALTO = 0.25
# Ruedas de antes y de después que se comparan para decir «se quedó».
RUEDAS = 5
# Margen para decir que un factor es redondo (2,03 es 2; 2,38 no).
MARGEN_REDONDO = 0.05
# El factor más grande que se considera: más allá es un precio roto (AZN pasó
# de $214 a $47.328 el 28/05/2024).
FACTOR_MAXIMO = 30
# Cuánto puede diferir el escalón del precio en pesos del factor del cociente
# (el cociente descuenta lo que se movió Nueva York ese día; el precio no).
MARGEN_ESCALON = 0.25
# Días entre dos anotaciones para tratarlas como el MISMO cambio.
VENTANA_DIAS = 7
# Tope de la corrida nocturna para preguntarle a Yahoo sus listas de splits.
TOPE_YAHOO_SEG = 180.0

CONFIRMADO, DUDOSO, DESCARTADO = "confirmado", "dudoso", "descartado"


# ─── La regla, sin base ni red (se prueba sola) ──────────────────────────────

def factor_redondo(f):
    """El factor redondo más cercano (2, 3… o 1/2, 1/3…) o None si no hay."""
    try:
        f = float(f)
    except (TypeError, ValueError):
        return None
    if not f or f <= 0:
        return None
    # El MÁS CERCANO, no el primero que entra en el margen: con 5% de margen,
    # 25 también «entra» como 24 (BKNG y HUT salían ×24).
    candidatos = [float(n) for n in range(2, FACTOR_MAXIMO + 1)] + \
                 [1.0 / n for n in range(2, FACTOR_MAXIMO + 1)]
    mejor = min(candidatos, key=lambda c: abs(f / c - 1))
    return mejor if abs(f / mejor - 1) < MARGEN_REDONDO else None


def _dias(a: str, b: str) -> int:
    return abs((date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days)


def saltos_del_cociente(ba: dict, ny: dict) -> list:
    """Escalones del cociente pesos ÷ Nueva York que se quedan.

    `ba`, `ny`: {fecha 'YYYY-MM-DD': cierre}. Sólo se comparan los días que
    tienen las dos (los feriados de una bolsa no son ruedas de la otra).
    Devuelve [{fecha, factor_medido, ba_antes, ba_despues}] donde `fecha` es el
    primer día a escala nueva y `factor_medido` es por cuánto se multiplicó la
    cantidad (precio de antes ÷ precio de después)."""
    dias = sorted(d for d in ba if d in ny and ba[d] and ny[d] and ba[d] > 0 and ny[d] > 0)
    if len(dias) < 2 * RUEDAS:
        return []
    q = [ba[d] / ny[d] for d in dias]
    out = []
    for i in range(RUEDAS, len(dias) - RUEDAS + 1):
        if abs(q[i] / q[i - 1] - 1) <= UMBRAL_SALTO:
            continue
        f = statistics.median(q[i - RUEDAS:i]) / statistics.median(q[i:i + RUEDAS])
        if abs(f - 1) <= UMBRAL_SALTO:
            continue                       # volvió al día siguiente: un precio roto suelto
        if out and _dias(dias[i], out[-1]["fecha"]) <= 2 * VENTANA_DIAS:
            continue                       # el mismo escalón visto dos veces
        out.append({"fecha": dias[i], "factor_medido": f,
                    "ba_antes": ba[dias[i - 1]], "ba_despues": ba[dias[i]]})
    return out


def _split_cerca(splits: list, fecha: str, dias: int = VENTANA_DIAS):
    """La anotación de `splits` [(fecha, factor)] más cercana a `fecha`."""
    cerca = [(d, f) for d, f in (splits or []) if _dias(d, fecha) <= dias]
    return min(cerca, key=lambda x: _dias(x[0], fecha)) if cerca else None


def _escalon_en_pesos(ba: dict, fecha: str):
    """Por cuánto bajó el precio en pesos en `fecha` (mediana de las ruedas de
    antes ÷ las de después), o None si no hay velas alrededor."""
    dias = sorted(d for d in ba if ba[d] and ba[d] > 0)
    antes = [ba[d] for d in dias if d < fecha][-RUEDAS:]
    despues = [ba[d] for d in dias if d >= fecha][:RUEDAS]
    if len(antes) < 2 or len(despues) < 2:
        return None
    return statistics.median(antes) / statistics.median(despues)


def clasificar(ba: dict, ny: dict, splits_ba: list, splits_d: list, splits_ny: list,
               byma: dict = None) -> list:
    """Todos los cambios de un CEDEAR, cada uno con su estado y su motivo.

    `ba`: la serie en pesos guardada; `ny`: la de Nueva York; `splits_*`: lo que
    Yahoo anota para la especie en pesos, la especie en dólares (`XD.BA`) y la
    acción de afuera, como [(fecha, factor)]. `byma`: los cierres de BYMA tal
    como fueron ese día (data912), o None si no se pidieron: sólo hacen falta para
    lo que Yahoo anota y corrigió en la serie, sin que Nueva York lo tenga (SPY el
    29/05/2026: la serie de Yahoo ya no muestra el escalón, la de BYMA sí)."""
    eventos = []
    for s in saltos_del_cociente(ba, ny):
        f_med = s["factor_medido"]
        f = factor_redondo(f_med)
        ny_sp = _split_cerca(splits_ny, s["fecha"], 3)
        ev = {"fecha": s["fecha"], "factor": f, "factor_medido": round(f_med, 4),
              "precio_antes": s["ba_antes"], "precio_despues": s["ba_despues"],
              "origen": "cociente"}
        escalon = s["ba_antes"] / s["ba_despues"] if s["ba_despues"] else None
        if f_med > FACTOR_MAXIMO or f_med < 1 / FACTOR_MAXIMO:
            ev.update(estado=DESCARTADO, motivo="precio roto u otra especie")
        elif not escalon or abs(escalon / f_med - 1) > MARGEN_ESCALON:
            ev.update(estado=DESCARTADO,
                      motivo="el precio en pesos no dio el escalón: se movió Nueva York")
        elif ny_sp and not factor_redondo(ny_sp[1]):
            ev.update(estado=DESCARTADO,
                      motivo=f"Nueva York anotó un split de {ny_sp[1]:g} ese día: es una escisión, no cambia la cantidad")
        elif f is None:
            ev.update(estado=DUDOSO, motivo="el factor no es un número redondo")
        elif ny_sp and abs(factor_redondo(ny_sp[1]) / f - 1) < MARGEN_REDONDO:
            ev.update(estado=CONFIRMADO, origen="cociente+nueva_york",
                      motivo="split de afuera que Yahoo no copió a la especie en pesos")
        elif f < 1:
            ev.update(estado=DUDOSO, motivo="la cantidad baja y Nueva York no lo anotó")
        else:
            ev.update(estado=CONFIRMADO, motivo="cambio de ratio del CEDEAR")
        eventos.append(ev)

    # Lo que Yahoo anota y el cociente no vio (la serie ya viene corregida, o
    # falta la de Nueva York).
    for origen, lista in (("yahoo", splits_ba), ("yahoo_dolares", splits_d)):
        for d, f_y in (lista or []):
            if any(_dias(e["fecha"], d) <= VENTANA_DIAS for e in eventos):
                continue
            f = factor_redondo(f_y)
            ev = {"fecha": d, "factor": f, "factor_medido": round(float(f_y), 4),
                  "precio_antes": None, "precio_despues": None, "origen": origen}
            ny_sp = _split_cerca(splits_ny, d, 3)
            escalon = _escalon_en_pesos(ba, d)
            if f is None:
                ev.update(estado=DUDOSO, motivo="el factor no es un número redondo (¿dividendo en acciones?)")
            elif ny_sp and factor_redondo(ny_sp[1]) and abs(factor_redondo(ny_sp[1]) / f - 1) < MARGEN_REDONDO:
                ev.update(estado=CONFIRMADO, origen=origen + "+nueva_york",
                          motivo="split de afuera que el CEDEAR trasladó")
            elif escalon and abs(escalon / f - 1) <= MARGEN_ESCALON and f > 1:
                ev.update(estado=CONFIRMADO, origen=origen + "+precio",
                          motivo="el precio en pesos muestra el escalón")
            elif byma and (_escalon_en_pesos(byma, d) or 0) and \
                    abs(_escalon_en_pesos(byma, d) / f - 1) <= MARGEN_ESCALON:
                ev.update(estado=CONFIRMADO, origen=origen + "+byma",
                          motivo="el precio de BYMA de esos días muestra el escalón")
            else:
                ev.update(estado=DUDOSO,
                          motivo="Yahoo lo anota pero ni Nueva York ni el precio en pesos lo confirman")
            eventos.append(ev)
    eventos.sort(key=lambda e: e["fecha"])
    return eventos


# ─── Yahoo ───────────────────────────────────────────────────────────────────

def _parsear_splits(s) -> list:
    """Serie de yfinance → [('YYYY-MM-DD', factor)]."""
    out = []
    for idx, factor in (s.items() if s is not None else []):
        try:
            d = idx.date().isoformat()
        except Exception:
            d = str(idx)[:10]
        try:
            f = float(factor)
        except (TypeError, ValueError):
            continue
        if f and f > 0:
            out.append((d, f))
    return out


def _splits_de_yahoo(ticker: str) -> list:
    import yfinance as yf
    return _parsear_splits(yf.Ticker(ticker).splits)


def _historia_byma(cedear: str) -> dict:
    """{fecha: cierre} de BYMA para un CEDEAR, de data912 (la misma fuente que
    ya da el precio en vivo). A diferencia de Yahoo, guarda el cierre como fue
    ese día: el escalón de un cambio de ratio queda a la vista (SPY 56.000 →
    18.760 el 29/05/2026). {} si no hay datos (DDD no tiene)."""
    import requests
    r = requests.get(f"https://data912.com/historical/cedears/{cedear}", timeout=10)
    if r.status_code != 200:
        return {}
    filas = r.json()
    out = {}
    for f in (filas if isinstance(filas, list) else []):
        try:
            c = float(f.get("c") or 0)
        except (TypeError, ValueError):
            continue
        if c > 0 and f.get("date"):
            out[str(f["date"])[:10]] = c
    return out


def _le_falta_byma(eventos: list) -> bool:
    """¿Hay algo que Yahoo anota con factor redondo y que sólo BYMA puede decidir?"""
    return any(e["estado"] == DUDOSO and e["factor"] and e["origen"].startswith("yahoo")
               for e in eventos)


# ─── La tabla ────────────────────────────────────────────────────────────────

def _serie(conn, ticker: str) -> dict:
    return {r["date"]: r["close"] for r in conn.execute(
        "SELECT date, close FROM velas_diarias WHERE symbol=? ORDER BY date", (ticker,)).fetchall()}


def guardar(conn, cedear: str, eventos: list, desde: str) -> int:
    """Reemplaza los cambios automáticos de `cedear` desde la fecha `desde` (la
    primera vela guardada). Lo anterior y lo puesto a mano no se tocan."""
    cedear = cedear.upper()
    manuales = [r["fecha"] for r in conn.execute(
        "SELECT fecha FROM cambios_ratio WHERE cedear=? AND origen='manual'", (cedear,)).fetchall()]
    conn.execute("DELETE FROM cambios_ratio WHERE cedear=? AND origen<>'manual' AND fecha>=?",
                 (cedear, desde))
    n = 0
    for e in eventos:
        if e["fecha"] < desde:
            continue        # fuera de las velas: no se puede juzgar, queda lo que había
        if any(_dias(m, e["fecha"]) <= VENTANA_DIAS for m in manuales):
            continue
        conn.execute(
            """INSERT INTO cambios_ratio (cedear, fecha, factor, factor_medido, estado, origen,
                                          motivo, precio_antes, precio_despues)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(cedear, fecha) DO UPDATE SET
                 factor=excluded.factor, factor_medido=excluded.factor_medido,
                 estado=excluded.estado, origen=excluded.origen, motivo=excluded.motivo,
                 precio_antes=excluded.precio_antes, precio_despues=excluded.precio_despues,
                 actualizado=datetime('now')""",
            (cedear, e["fecha"], e["factor"], e["factor_medido"], e["estado"], e["origen"],
             e["motivo"], e["precio_antes"], e["precio_despues"]))
        n += 1
    return n


def cedears_guardados(conn) -> list:
    """Los CEDEARs que tienen las dos series en `velas_diarias` ('XLE' y
    'XLE.BA'), o al menos la de pesos de un CEDEAR que Yahoo cotiza afuera."""
    simbolos = {r["symbol"] for r in conn.execute(
        "SELECT DISTINCT symbol FROM velas_diarias").fetchall()}
    return sorted(s[:-3] for s in simbolos if s.endswith(".BA") and s[:-3] in simbolos)


def recalcular(conn, cedears: list, *, splits=None, byma=None,
               tope_seg: float = TOPE_YAHOO_SEG) -> dict:
    """Recalcula la lista de estos CEDEARs con las velas guardadas y lo que
    Yahoo anota. `splits(ticker) -> [(fecha, factor)]` y `byma(cedear) ->
    {fecha: cierre}` se inyectan en las pruebas; por defecto, Yahoo con tope y
    data912 (sólo para los pocos casos que lo necesitan)."""
    from pricing import yahoo as _yahoo
    cedears = sorted({(c or "").upper() for c in cedears if c})
    pedir = [t for c in cedears for t in (f"{c}.BA", f"{c}D.BA", c)]
    if splits is None:
        hechos, sin = _yahoo.varios(_splits_de_yahoo, pedir, tope=tope_seg,
                                    que="splits para los cambios de ratio")
        # Sin respuesta de Yahoo ≠ «no tuvo splits»: ese CEDEAR se recalcula
        # igual (el cociente no depende de Yahoo), pero lo que Yahoo anotó antes
        # sólo se pierde si Yahoo contestó.
        sin = set(sin) | {t for t in pedir if t not in hechos}

        def consulta(t):
            return hechos.get(t, [])
    else:
        sin = set()
        consulta = splits
    res = {"cedears": len(cedears), "confirmados": 0, "dudosos": 0, "descartados": 0,
           "sin_yahoo": sorted(sin)}
    for c in cedears:
        ba, ny = _serie(conn, f"{c}.BA"), _serie(conn, c)
        if not ba:
            continue
        if any(t in sin for t in (f"{c}.BA", f"{c}D.BA", c)):
            # Yahoo no contestó: se conservan las filas que vinieron de Yahoo.
            eventos = [e for e in clasificar(ba, ny, [], [], []) if e["origen"].startswith("cociente")]
            viejos = [dict(r) for r in conn.execute(
                "SELECT * FROM cambios_ratio WHERE cedear=? AND origen LIKE 'yahoo%'", (c,)).fetchall()]
            eventos += [v for v in viejos if not any(_dias(v["fecha"], e["fecha"]) <= VENTANA_DIAS for e in eventos)]
        else:
            sp = (consulta(f"{c}.BA"), consulta(f"{c}D.BA"), consulta(c))
            eventos = clasificar(ba, ny, *sp)
            if _le_falta_byma(eventos):
                try:
                    historia = (byma or _historia_byma)(c)
                except Exception as ex:      # data912 caído: queda dudoso, mañana se reintenta
                    log.warning("cambios de ratio: historia de BYMA de %s falló: %r", c, ex)
                    historia = {}
                if historia:
                    eventos = clasificar(ba, ny, *sp, byma=historia)
        guardar(conn, c, eventos, desde=min(ba))
        for e in eventos:
            clave = {CONFIRMADO: "confirmados", DUDOSO: "dudosos"}.get(e["estado"], "descartados")
            res[clave] += 1
    conn.commit()
    return res


def correr(conn) -> dict:
    """La corrida nocturna: todos los CEDEARs con velas guardadas."""
    t0 = time.monotonic()
    res = recalcular(conn, cedears_guardados(conn))
    res["seg"] = round(time.monotonic() - t0, 1)
    return res


# ─── Leer ────────────────────────────────────────────────────────────────────

def confirmados(conn, cedear: str) -> list:
    """[(fecha, factor)] de los cambios CONFIRMADOS de un CEDEAR, por fecha.
    `fecha` = primer día a escala nueva; `factor` = por cuánto se multiplicó la
    cantidad (2 = el doble; 1/3 = un tercio)."""
    c = (cedear or "").upper()
    if c.endswith(".BA"):
        c = c[:-3]
    return [(r["fecha"], float(r["factor"])) for r in conn.execute(
        "SELECT fecha, factor FROM cambios_ratio WHERE cedear=? AND estado=? AND factor IS NOT NULL "
        "ORDER BY fecha", (c, CONFIRMADO)).fetchall()]


def todos(conn, cedear: str = None) -> list:
    """Todas las filas (para /admin y para revisar a mano)."""
    q, args = "SELECT * FROM cambios_ratio", []
    if cedear:
        q += " WHERE cedear=?"
        args.append(cedear.upper())
    return [dict(r) for r in conn.execute(q + " ORDER BY cedear, fecha", args).fetchall()]
