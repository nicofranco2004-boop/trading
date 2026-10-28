"""Cambios de ratio de CEDEAR: la lista única.

QUÉ ES. Cuando un CEDEAR cambia de ratio (Comafi pasa Apple de 10 a 20 CEDEARs
por acción) o la acción de afuera se divide (XLE 2 a 1), cada CEDEAR pasa a
valer la mitad y al tenedor le acreditan el doble. La tabla `cambios_ratio`
guarda cada uno de esos cambios: qué papel, el primer día que BYMA cotizó a la
escala nueva, por cuánto se multiplicó la cantidad, y qué tan seguro es. Es la
misma lista para el aviso «Ajustar» de Posiciones (`para_lotes`, que lee
main.py) y para el gráfico en pesos de la ficha (`para_el_grafico`): dos reglas
distintas cuentan dos historias distintas.

POR QUÉ NO ALCANZA CON YAHOO. Medido el 22/10/2026 sobre los CEDEARs de BYMA:
la lista de splits de Yahoo para la especie en pesos (`AAPL.BA`) viene VACÍA en
33 cambios reales de los últimos 3 años (los 27 del 24/01/2024, TQQQ en
noviembre de 2025, XLE/XLU/XLB/XLK/XLY en diciembre de 2025). A veces los anota
en la especie en dólares (`AAPLD.BA`), que Rendi no valúa. Y al revés, anota
cosas que nadie pudo confirmar: a 3D Systems (DDD.BA) le anotó la agrupación de
DuPont.

CÓMO SE DETECTA. El cociente «precio del CEDEAR en pesos ÷ precio de la acción
en Nueva York» es más o menos «dólar ÷ ratio»: se mueve despacio. Si salta más
de 25% de un día al otro y se queda, algo cambió. El factor sale de la mediana
de hasta 5 ruedas de cada lado, cortando en el salto siguiente. Qué fue:
  · `ratio`: cambió la cantidad. CONFIRMADO si el factor es redondo (2, 3… o
    1/2, 1/3…, con 5% de margen) y, si la cantidad BAJA, Nueva York también lo
    anotó (sin esa confirmación sólo se vieron los precios rotos del 28/05/2024).
    Con factor no redondo, DUDOSO.
  · `escision`: Nueva York anotó ese día un «split» con factor raro. DuPont el
    03/11/2025 separó Qnity: el CEDEAR cayó 57% y nadie recibió más CEDEARs de
    DD. No cambia la cantidad (ajustar multiplicaba la tenencia por 2,38), pero
    el gráfico en pesos sí tiene que empalmarlo, como Yahoo empalmó Nueva York.
  · `precio_quieto`: el precio en pesos no se movió y el cociente saltó porque se
    movió Nueva York (FNMA, $240 meses sin operaciones). Nada que corregir.
  · `precio_roto`: el nivel cambió por más de 30 veces (AZN $214 → $47.328). No es
    una cantidad; el gráfico lo empalma.
  · `roto`: un día (o dos) que salta y vuelve (ETHA el 06/10/2026 cotizó a la
    escala vieja entre dos días a la nueva). El gráfico lo saca.
  · `pendiente`: el salto es de los últimos días y todavía no hay 5 ruedas para
    saber si se queda. Se decide la noche que las haya.
  · `sin_explicar`: una acción argentina (sin par afuera) saltó más de 40% en un
    día y Yahoo no anotó nada. Puede ser real o un cambio de escala: se muestra
    en /admin para mirarlo a mano; no lo usan ni el gráfico ni el aviso.
NO se exige que Nueva York se haya movido poco: el cociente ya descuenta a Nueva
York, y ese filtro tiraba NFLX el 24/01/2024 (ese día subió 10,7% por su
balance).

Lo que Yahoo anota (en pesos o en dólares) entra como CONFIRMADO si el factor es
redondo y Nueva York anotó lo mismo esos días (un split de afuera que el CEDEAR
trasladó: NVDA, DD el 24/06/2026), si el precio en pesos guardado muestra el
escalón (MIRG el 03/08/2026), o si lo muestra la historia de BYMA (data912), que
guarda el cierre como fue ese día (SPY el 29/05/2026, YPFD el 03/08/2026).

SIN_CONFIRMAR: lo que Yahoo anota en la especie EN PESOS y nada confirma ni
desmiente (BYMA el 10/05/2024: Yahoo y data912 ya tienen la serie corregida;
DDD). Es lo que el aviso viejo ofrecía afirmándolo; ahora se ofrece como
PREGUNTA. Sacarlo perdía casos reales; afirmarlo, como antes, le decía a quien
tiene DDD «dividí por 3» sin que nadie lo haya confirmado.

UN AJUSTE MAL HECHO MULTIPLICA TENENCIAS (ver `_escala_del_lote` en main.py). Por
eso lo dudoso nunca llega al aviso, lo sin confirmar llega como pregunta, y el
aviso sigue siendo un botón que toca la persona, nunca un ajuste automático.

`en_la_serie`: 1 si la serie en pesos GUARDADA muestra el escalón ese día (lo
detectó el cociente, o se ve en el precio). 0 si Yahoo ya la corrigió hacia
atrás (NVDA). El gráfico empalma sólo los primeros: empalmar uno ya corregido lo
rompería. La evidencia de cada lote (main.py) lee la serie CRUDA, no la empalmada.

CUÁNDO CORRE. De noche, al final de `velas_diarias.correr` (que ya guardó la serie
en pesos de cada papel que alguien tiene y, de los CEDEARs, también la de Nueva
York): `correr(conn, pares)`. Los `pares` (qué papel es un CEDEAR y cuál es su
acción de afuera) los da `velas_diarias`, nunca el nombre (ver `recalcular`). Lo que quedó fuera de la ventana de 3 años de las velas
NO se borra: un cambio de 2024 tiene que seguir existiendo en 2028 para el lote
que se compró antes.

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
# El factor más grande que se considera una cantidad: más allá es un precio roto
# (AZN pasó de $214 a $47.328 el 28/05/2024).
FACTOR_MAXIMO = 30
# Cuánto puede diferir el escalón del precio en pesos del factor del cociente
# (el cociente descuenta lo que se movió Nueva York ese día; el precio no).
MARGEN_ESCALON = 0.25
# Días entre dos anotaciones para tratarlas como el MISMO cambio.
VENTANA_DIAS = 7
# Cuántos días seguidos puede durar un «día roto» que vuelve.
DIAS_ROTOS_MAX = 2
# Tope de la corrida nocturna para preguntarle a Yahoo sus listas de splits.
TOPE_YAHOO_SEG = 180.0

CONFIRMADO, SIN_CONFIRMAR, DUDOSO, DESCARTADO = "confirmado", "sin_confirmar", "dudoso", "descartado"
RATIO, ESCISION, PRECIO_QUIETO, PRECIO_ROTO, ROTO, PENDIENTE, SIN_EXPLICAR = (
    "ratio", "escision", "precio_quieto", "precio_roto", "roto", "pendiente", "sin_explicar")
# Una acción argentina no tiene par afuera: un salto de más que esto en un día,
# que Yahoo no anota, se guarda como `sin_explicar` para mirarlo a mano en /admin
# (Agrometal −88 % el 03/11/2023). Ni el gráfico ni el aviso lo usan.
SALTO_SIN_EXPLICAR = 0.40


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


def _salta(a, b) -> bool:
    return abs(b / a - 1) > UMBRAL_SALTO


def saltos_del_cociente(ba: dict, ny: dict) -> dict:
    """Lo que hizo saltar el cociente pesos ÷ Nueva York.

    `ba`, `ny`: {fecha 'YYYY-MM-DD': cierre}. Sólo se comparan los días que
    tienen las dos (los feriados de una bolsa no son ruedas de la otra).
    Devuelve {'escalones', 'rotos', 'pendientes'}:
      · escalones: [{fecha, factor_medido, ba_antes, ba_despues}] — `fecha` es el
        primer día a escala nueva; `factor_medido` = mediana del cociente de hasta
        `RUEDAS` días antes ÷ la de hasta `RUEDAS` días después, cortando en el
        salto vecino (con un solo día, AAPL daba 0,5076; con la mediana, 0,5).
      · rotos: [fecha] — días que saltan y vuelven en ≤ `DIAS_ROTOS_MAX` ruedas.
      · pendientes: [fecha] — saltos con menos de `RUEDAS` ruedas después y sin
        otro salto que los acote: todavía no se sabe si se quedan."""
    dias = sorted(d for d in ba if d in ny and ba[d] and ny[d] and ba[d] > 0 and ny[d] > 0)
    out = {"escalones": [], "rotos": [], "pendientes": []}
    if len(dias) < 2:
        return out
    q = [ba[d] / ny[d] for d in dias]
    n = len(q)
    saltos = [i for i in range(1, n) if _salta(q[i - 1], q[i])]
    rotos, vueltas = set(), set()
    for i in saltos:
        if i in rotos or i in vueltas:
            continue
        # ¿Vuelve al nivel de antes en 1 o 2 ruedas? Entonces son días rotos, y
        # el salto de vuelta no es un cambio.
        for k in range(1, DIAS_ROTOS_MAX + 1):
            if i + k < n and not _salta(q[i - 1], q[i + k]):
                rotos.update(range(i, i + k))
                vueltas.add(i + k)
                break
    reales = [i for i in saltos if i not in rotos and i not in vueltas]
    limpios = [i for i in range(n) if i not in rotos]
    for j, i in enumerate(reales):
        prev = reales[j - 1] if j > 0 else 0
        nxt = reales[j + 1] if j + 1 < len(reales) else n
        antes = [q[x] for x in limpios if prev <= x < i][-RUEDAS:]
        despues = [q[x] for x in limpios if i <= x < nxt][:RUEDAS]
        if len(despues) < RUEDAS and nxt == n:
            out["pendientes"].append(dias[i])
            continue
        if not antes or not despues:
            continue
        f = statistics.median(antes) / statistics.median(despues)
        if abs(f - 1) <= UMBRAL_SALTO:
            continue
        out["escalones"].append({"fecha": dias[i], "factor_medido": f,
                                 "ba_antes": ba[dias[i - 1]], "ba_despues": ba[dias[i]]})
    out["rotos"] = [dias[i] for i in sorted(rotos)]
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


def _fila(fecha, tipo, estado, motivo, origen, factor=None, medido=None,
          antes=None, despues=None, en_la_serie=0) -> dict:
    return {"fecha": fecha, "tipo": tipo, "estado": estado, "motivo": motivo,
            "origen": origen, "factor": factor,
            "factor_medido": round(medido, 4) if medido else None,
            "precio_antes": antes, "precio_despues": despues, "en_la_serie": en_la_serie}


def clasificar(ba: dict, ny: dict, splits_ba: list, splits_d: list, splits_ny: list,
               byma: dict = None) -> list:
    """Todas las filas de un papel, cada una con su tipo, su estado y su motivo.

    `ba`: la serie en pesos guardada; `ny`: la de Nueva York ({} para una acción
    argentina); `splits_*`: lo que Yahoo anota para la especie en pesos, la
    especie en dólares (`XD.BA`) y la acción de afuera, como [(fecha, factor)].
    `byma`: los cierres de BYMA tal como fueron ese día (data912), o None si no se
    pidieron: sólo hacen falta para lo que Yahoo anota y corrigió en la serie, sin
    que Nueva York lo tenga (SPY el 29/05/2026: la serie de Yahoo ya no muestra el
    escalón, la de BYMA sí)."""
    filas = []
    s = saltos_del_cociente(ba, ny)
    for e in s["escalones"]:
        f_med = e["factor_medido"]
        f = factor_redondo(f_med)
        ny_sp = _split_cerca(splits_ny, e["fecha"], 3)
        escalon = e["ba_antes"] / e["ba_despues"] if e["ba_despues"] else None
        base = dict(medido=f_med, antes=e["ba_antes"], despues=e["ba_despues"],
                    origen="cociente", en_la_serie=1)
        if f_med > FACTOR_MAXIMO or f_med < 1 / FACTOR_MAXIMO:
            filas.append(_fila(e["fecha"], PRECIO_ROTO, DESCARTADO,
                               "precio roto u otra especie", **base))
        elif not escalon or abs(escalon / f_med - 1) > MARGEN_ESCALON:
            base["en_la_serie"] = 0
            filas.append(_fila(e["fecha"], PRECIO_QUIETO, DESCARTADO,
                               "el precio en pesos no dio el escalón: se movió Nueva York", **base))
        elif ny_sp and not factor_redondo(ny_sp[1]):
            filas.append(_fila(e["fecha"], ESCISION, DESCARTADO,
                               f"Nueva York anotó un split de {ny_sp[1]:g} ese día: es una "
                               "escisión, no cambia la cantidad", **base))
        elif f is None:
            filas.append(_fila(e["fecha"], RATIO, DUDOSO, "el factor no es un número redondo", **base))
        elif ny_sp and abs(factor_redondo(ny_sp[1]) / f - 1) < MARGEN_REDONDO:
            base["origen"] = "cociente+nueva_york"
            filas.append(_fila(e["fecha"], RATIO, CONFIRMADO,
                               "split de afuera que Yahoo no copió a la especie en pesos", factor=f, **base))
        elif f < 1:
            filas.append(_fila(e["fecha"], RATIO, DUDOSO,
                               "la cantidad baja y Nueva York no lo anotó", factor=f, **base))
        else:
            filas.append(_fila(e["fecha"], RATIO, CONFIRMADO, "cambio de ratio del CEDEAR",
                               factor=f, **base))
    filas += [_fila(d, ROTO, DESCARTADO, "un día que salta y vuelve", "cociente") for d in s["rotos"]]
    filas += [_fila(d, PENDIENTE, DUDOSO, "todavía no hay 5 ruedas para saber si se queda",
                    "cociente") for d in s["pendientes"]]

    # Lo que Yahoo anota y el cociente no vio (la serie ya viene corregida, o
    # no hay serie de Nueva York: una acción argentina).
    vistos = [x["fecha"] for x in filas if x["tipo"] not in (ROTO, PENDIENTE)]
    for origen, lista in (("yahoo", splits_ba), ("yahoo_dolares", splits_d)):
        for d, f_y in (lista or []):
            if any(_dias(v, d) <= VENTANA_DIAS for v in vistos):
                continue
            vistos.append(d)
            f = factor_redondo(f_y)
            ny_sp = _split_cerca(splits_ny, d, 3)
            escalon = _escalon_en_pesos(ba, d)
            # «Se ve en la serie» sólo si el escalón se distingue de un día común:
            # un dividendo en acciones de 1% (SCCO) entra en cualquier margen.
            en_pesos = 1 if (escalon and _salta(1.0, escalon)
                             and abs(escalon / float(f_y) - 1) <= MARGEN_ESCALON) else 0
            base = dict(medido=float(f_y), origen=origen, en_la_serie=en_pesos)
            esc_byma = _escalon_en_pesos(byma, d) if byma else None
            if f and ny_sp and factor_redondo(ny_sp[1]) and abs(factor_redondo(ny_sp[1]) / f - 1) < MARGEN_REDONDO:
                base["origen"] = origen + "+nueva_york"
                filas.append(_fila(d, RATIO, CONFIRMADO, "split de afuera que el CEDEAR trasladó",
                                   factor=f, **base))
            elif f and en_pesos and f > 1:
                base["origen"] = origen + "+precio"
                filas.append(_fila(d, RATIO, CONFIRMADO, "el precio en pesos muestra el escalón",
                                   factor=f, **base))
            elif f and esc_byma and abs(esc_byma / f - 1) <= MARGEN_ESCALON:
                base["origen"] = origen + "+byma"
                filas.append(_fila(d, RATIO, CONFIRMADO,
                                   "el precio de BYMA de esos días muestra el escalón", factor=f, **base))
            elif origen == "yahoo":
                filas.append(_fila(d, RATIO, SIN_CONFIRMAR,
                                   "Yahoo lo anota en pesos y nada lo confirma ni lo desmiente: "
                                   "se pregunta, no se afirma", factor=f, **base))
            else:
                filas.append(_fila(d, RATIO, DUDOSO,
                                   "Yahoo lo anota en la especie en dólares y nada lo confirma",
                                   factor=f, **base))
    if not ny:
        dias = sorted(d for d in ba if ba[d] and ba[d] > 0)
        for a, b in zip(dias, dias[1:]):
            if abs(ba[b] / ba[a] - 1) > SALTO_SIN_EXPLICAR and \
                    not any(_dias(v, b) <= VENTANA_DIAS for v in vistos):
                filas.append(_fila(b, SIN_EXPLICAR, DESCARTADO,
                                   "sin par afuera y Yahoo no lo anota: mirar a mano", "precio",
                                   medido=ba[a] / ba[b], antes=ba[a], despues=ba[b]))
    filas.sort(key=lambda e: (e["fecha"], e["tipo"]))
    return filas


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


def _historia_byma(papel: str) -> dict:
    """{fecha: cierre} de BYMA de un CEDEAR o una acción argentina, de data912 (la
    misma fuente que ya da el precio en vivo). A diferencia de Yahoo, para los
    cambios recientes guarda el cierre como fue ese día: el escalón queda a la
    vista (SPY 56.000 → 18.760 el 29/05/2026; YPFD 83.000 → 8.105 el 03/08/2026).
    Los viejos los corrige (AAPL en 2024). {} si no hay datos (DDD no tiene)."""
    import requests
    for tipo in ("cedears", "stocks"):
        r = requests.get(f"https://data912.com/historical/{tipo}/{papel}", timeout=10)
        if r.status_code != 200:
            continue
        filas = r.json()
        out = {}
        for f in (filas if isinstance(filas, list) else []):
            try:
                c = float(f.get("c") or 0)
            except (TypeError, ValueError):
                continue
            if c > 0 and f.get("date"):
                out[str(f["date"])[:10]] = c
        if out:
            return out
    return {}


def _le_falta_byma(filas: list) -> bool:
    """¿Hay algo que Yahoo anota con factor redondo y que sólo BYMA puede decidir?"""
    return any(e["estado"] in (SIN_CONFIRMAR, DUDOSO) and e["factor"]
               and e["origen"].startswith("yahoo") for e in filas)


# ─── La tabla ────────────────────────────────────────────────────────────────

def _serie(conn, ticker: str) -> dict:
    """La serie GUARDADA, cruda: lo que trajo Yahoo, sin empalmar nada."""
    return {r["date"]: r["close"] for r in conn.execute(
        "SELECT date, close FROM velas_diarias WHERE symbol=? ORDER BY date", (ticker,)).fetchall()}


def guardar(conn, papel: str, filas: list, desde: str) -> list:
    """Reemplaza las filas automáticas de `papel` desde la fecha `desde` (la
    primera vela guardada). Lo puesto a mano no se toca nunca.

    Lo ANTERIOR a las velas no se juzga ni se borra: lo que ya estaba se queda
    (un cambio de 2024 tiene que seguir valiendo en 2028 para el lote que se
    compró antes), y lo que Yahoo anota de esa época y no estaba entra como
    `sin_confirmar` (AAPL 2014 y 2020: el aviso viejo lo ofrecía, y sin velas no
    hay con qué confirmarlo). Devuelve las filas que guardó."""
    papel = papel.upper()
    previas = [r["fecha"] for r in conn.execute(
        "SELECT fecha FROM cambios_ratio WHERE cedear=? AND (origen='manual' OR fecha<?)",
        (papel, desde)).fetchall()]
    conn.execute("DELETE FROM cambios_ratio WHERE cedear=? AND origen<>'manual' AND fecha>=?",
                 (papel, desde))
    guardadas = []
    for e in filas:
        if e["fecha"] < desde and not (e["origen"].split("+")[0] == "yahoo" and e["tipo"] == RATIO
                                       and e["estado"] in (CONFIRMADO, SIN_CONFIRMAR)):
            continue
        if any(_dias(m, e["fecha"]) <= VENTANA_DIAS for m in previas):
            continue
        conn.execute(
            """INSERT INTO cambios_ratio (cedear, fecha, tipo, factor, factor_medido, estado, origen,
                                          motivo, precio_antes, precio_despues, en_la_serie)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(cedear, fecha, tipo) DO UPDATE SET
                 factor=excluded.factor, factor_medido=excluded.factor_medido,
                 estado=excluded.estado, origen=excluded.origen, motivo=excluded.motivo,
                 precio_antes=excluded.precio_antes, precio_despues=excluded.precio_despues,
                 en_la_serie=excluded.en_la_serie, actualizado=datetime('now')""",
            (papel, e["fecha"], e["tipo"], e["factor"], e["factor_medido"], e["estado"],
             e["origen"], e["motivo"], e["precio_antes"], e["precio_despues"],
             int(e.get("en_la_serie") or 0)))
        guardadas.append(e)
    return guardadas


def papeles_guardados(conn) -> list:
    """Todo lo que tiene serie en pesos en `velas_diarias` ('XLE.BA', 'YPFD.BA'):
    CEDEARs (que además tienen la de Nueva York, 'XLE') y acciones argentinas,
    que también pueden cambiar de cantidad (YPFD 10 a 1 el 03/08/2026, los
    dividendos en acciones de BYMA) y también pasan por el aviso «Ajustar»."""
    return sorted({r["symbol"][:-3] for r in conn.execute(
        "SELECT DISTINCT symbol FROM velas_diarias WHERE symbol LIKE '%.BA'").fetchall()
        if r["symbol"][:-3]})


def recalcular(conn, papeles: list, *, pares: dict = None, splits=None, byma=None,
               tope_seg: float = TOPE_YAHOO_SEG) -> dict:
    """Recalcula la lista de estos papeles con las velas guardadas y lo que
    Yahoo anota. `splits(ticker) -> [(fecha, factor)]` y `byma(papel) ->
    {fecha: cierre}` se inyectan en las pruebas; por defecto, Yahoo con tope y
    data912 (sólo para los pocos casos que lo necesitan).

    `pares`: {papel: ticker de afuera} de los papeles que SON un CEDEAR ('XLE':
    'XLE', 'BRKB': 'BRK-B'). Lo sabe `velas_diarias` (por la cartera, la lista
    de seguimiento y la lista de CEDEARs de BYMA). Sin par, el papel se lee como
    una acción argentina: sin cociente, sólo con lo que Yahoo anota. NUNCA se
    arma el par por el nombre: AGRO.BA es Agrometal y AGRO en Nueva York es
    Adecoagro, y compararlos daba un «cambio de ratio confirmado ×8» el
    03/11/2023 que el aviso le ofrecía a quien tiene Agrometal (medido el
    22/10/2026). Tampoco con un ADR del mismo nombre (GGAL): un cambio de la
    equivalencia del ADR no cambia la cantidad de acciones locales de nadie."""
    from pricing import yahoo as _yahoo
    papeles = sorted({(c or "").upper() for c in papeles if c})
    afuera = {(k or "").upper(): (v or "").upper() for k, v in (pares or {}).items() if k and v}
    series = {c: (_serie(conn, f"{c}.BA"), _serie(conn, afuera[c]) if c in afuera else {})
              for c in papeles}
    # La especie en dólares ('XD.BA') sólo existe para los CEDEARs: pedirla para
    # una acción argentina es un 404 por papel, todas las noches.
    def _tickers(c):
        return (f"{c}.BA", f"{c}D.BA", afuera[c]) if series[c][1] else (f"{c}.BA",)
    pedir = [t for c in papeles for t in _tickers(c)]
    if splits is None:
        hechos, sin = _yahoo.varios(_splits_de_yahoo, pedir, tope=tope_seg,
                                    que="splits para los cambios de ratio")
        # Sin respuesta de Yahoo ≠ «no tuvo splits»: el papel se recalcula igual
        # (el cociente no depende de Yahoo), pero lo que Yahoo anotó antes sólo se
        # pierde si Yahoo contestó.
        sin = set(sin) | {t for t in pedir if t not in hechos}

        def consulta(t):
            return hechos.get(t, [])
    else:
        sin = set()
        consulta = splits
    res = {"papeles": len(papeles), CONFIRMADO: 0, SIN_CONFIRMAR: 0, DUDOSO: 0, DESCARTADO: 0,
           "sin_yahoo": sorted(sin)}
    for c in papeles:
        ba, ny = series[c]
        if not ba:
            continue
        if any(t in sin for t in _tickers(c)):
            # Yahoo no contestó: se conservan las filas que vinieron de Yahoo.
            filas = [e for e in clasificar(ba, ny, [], [], []) if e["origen"].startswith(("cociente", "precio"))]
            viejas = [dict(r) for r in conn.execute(
                "SELECT * FROM cambios_ratio WHERE cedear=? AND origen LIKE 'yahoo%'", (c,)).fetchall()]
            filas += [v for v in viejas
                      if not any(_dias(v["fecha"], e["fecha"]) <= VENTANA_DIAS for e in filas)]
        else:
            sp = (consulta(f"{c}.BA"), consulta(f"{c}D.BA") if ny else [], consulta(afuera[c]) if ny else [])
            filas = clasificar(ba, ny, *sp)
            if _le_falta_byma(filas):
                try:
                    historia = (byma or _historia_byma)(c)
                except Exception as ex:      # data912 caído: queda como estaba, mañana se reintenta
                    log.warning("cambios de ratio: historia de BYMA de %s falló: %r", c, ex)
                    historia = {}
                if historia:
                    filas = clasificar(ba, ny, *sp, byma=historia)
        for e in guardar(conn, c, filas, desde=min(ba)):
            res[e["estado"]] = res.get(e["estado"], 0) + 1
    conn.commit()
    return res


def correr(conn, pares: dict = None) -> dict:
    """La corrida nocturna: todo lo que tiene velas en pesos guardadas. La
    llama `velas_diarias.correr`, que le pasa los `pares` de cada CEDEAR."""
    t0 = time.monotonic()
    res = recalcular(conn, papeles_guardados(conn), pares=pares)
    res["seg"] = round(time.monotonic() - t0, 1)
    return res


# ─── Leer ────────────────────────────────────────────────────────────────────

def _base(papel: str) -> str:
    c = (papel or "").upper()
    return c[:-3] if c.endswith(".BA") else c


def para_lotes(conn, papel: str) -> list:
    """[(fecha, factor, confirmado)] de los cambios de CANTIDAD que el aviso
    «Ajustar» puede ofrecer, por fecha. `factor` = por cuánto se multiplica la
    cantidad (2 = el doble; 1/3 = un tercio). `confirmado=False` es lo que Yahoo
    anota en pesos y nada confirma: se ofrece como pregunta."""
    out = []
    for r in conn.execute(
            "SELECT fecha, factor, factor_medido, estado FROM cambios_ratio "
            "WHERE cedear=? AND tipo=? AND estado IN (?,?) ORDER BY fecha",
            (_base(papel), RATIO, CONFIRMADO, SIN_CONFIRMAR)).fetchall():
        f = r["factor"] if r["factor"] else r["factor_medido"]
        if f and f > 0:
            out.append((r["fecha"], float(f), r["estado"] == CONFIRMADO))
    return out


def confirmados(conn, papel: str) -> list:
    """[(fecha, factor)] de los cambios de cantidad CONFIRMADOS."""
    return [(d, f) for d, f, ok in para_lotes(conn, papel) if ok]


def para_el_grafico(conn, papel: str) -> dict:
    """Lo que el gráfico en pesos necesita para empalmar la serie guardada:
      · escalones: [(fecha, factor)] — dividí los cierres ANTERIORES a `fecha`
        por `factor`. Sólo los que la serie guardada muestra (`en_la_serie`): un
        cambio que Yahoo ya corrigió hacia atrás no se vuelve a corregir. Incluye
        las escisiones (DD 03/11/2025, como Yahoo empalmó Nueva York) y los
        precios rotos de nivel, que NO van a los lotes.
      · rotos: [fecha] — días a sacar del gráfico.
      · pendientes: [fecha] — saltos de los últimos días que todavía no se
        decidieron: esconder esos días, no reescalar."""
    c = _base(papel)
    filas = conn.execute(
        "SELECT fecha, tipo, factor, factor_medido FROM cambios_ratio WHERE cedear=? ORDER BY fecha",
        (c,)).fetchall()
    escalones = [(r["fecha"], float(r["factor"] or r["factor_medido"])) for r in conn.execute(
        "SELECT fecha, factor, factor_medido FROM cambios_ratio WHERE cedear=? AND en_la_serie=1 "
        "AND tipo IN (?,?,?) AND COALESCE(factor, factor_medido) > 0 ORDER BY fecha",
        (c, RATIO, ESCISION, PRECIO_ROTO)).fetchall()]
    return {"escalones": escalones,
            "rotos": [r["fecha"] for r in filas if r["tipo"] == ROTO],
            "pendientes": [r["fecha"] for r in filas if r["tipo"] == PENDIENTE]}


def todos(conn, papel: str = None) -> list:
    """Todas las filas (para /admin y para revisar a mano)."""
    q, args = "SELECT * FROM cambios_ratio", []
    if papel:
        q += " WHERE cedear=?"
        args.append(_base(papel))
    return [dict(r) for r in conn.execute(q + " ORDER BY cedear, fecha, tipo", args).fetchall()]
