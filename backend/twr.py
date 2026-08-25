"""Retorno time-weighted — el núcleo, POR USUARIO.

Este módulo no sabe qué es un asesor. Recibe una lista de user_ids y trabaja.
`advisor_twr.py` lo usa para agregar el libro; la app retail lo va a usar para
la cartera propia. Un cliente de un asesor ES un usuario: si la lógica del TWR
se escribe dos veces, terminamos con dos motores que dan distinto — que es
exactamente el problema que este trabajo viene a cerrar.

FASE 0 (lo que hay acá hoy): el semáforo de datos. Read-only. Clasifica cada
fila de `snapshots` según cómo se escribió, para poder responder una pregunta
antes de calcular nada: ¿desde cuándo la historia de esta persona es una
MEDICIÓN A MERCADO, y no contabilidad congelada ni una foto de media rueda?
"""
import json
import logging
from collections import defaultdict

log = logging.getLogger(__name__)

# ─── Cómo se distingue quién escribió cada snapshot ──────────────────────────
#
# Tres emisores, y hasta que exista la columna `source` había que deducirlo:
#
#   cron nocturno  (snapshots_job.take_snapshot_for_user)
#       → fx_to_usd_blue NOT NULL  +  holdings_json con la composición
#       ⚠️ PERO holdings excluye el cash (`if p.get('is_cash'): continue`), así
#          que un usuario TODO EN CASH deja holdings_json en NULL aunque el cron
#          haya corrido perfecto. Por eso NO alcanza con exigir la columna:
#          hay que cruzar contra si esa persona tenía posiciones que valuar.
#
#   browser        (POST /api/snapshots, lo dispara el Dashboard al cargar)
#       → nunca escribe holdings_json; fx_to_usd_blue sale del caché de dólar,
#         que con caché frío queda en NULL. Es un valor calculado en JS a media
#         rueda: sirve para que la curva del usuario no tenga huecos, NO para
#         medir un período.
#
#   importador     (persister._backfill_snapshots_from_monthly)
#       → ambas columnas en NULL, siempre a fin de mes, y total_value es
#         `capital_final` — que para meses cerrados tiene pnl_unrealized
#         forzado a 0, o sea EL COSTO. Encadenar eso no mide el mercado:
#         mide la cadena contable.
#
# La firma "ambas NULL" la comparten el importador y el browser-con-caché-frío.
# Es la misma heurística que ya usa /api/insights/mtm-audit, y acá se mantiene
# idéntica a propósito: si las dos difieren, una de las dos está mal.
#
# La regla que hace que esto sea seguro: sólo `medicion` habilita un borde de
# período. No hace falta separar perfectamente al browser del sintético, porque
# NINGUNO de los dos sirve como borde.

MEDICION = "medicion"                # cierre real a mercado — sirve de borde
RECONSTRUIDO = "reconstruido"        # tenencia histórica valuada a precio real de mercado
INTRADIA = "intradia"                # foto de media rueda escrita por un browser
SINTETICO_COSTO = "sintetico_costo"  # fabricado por el import: contabilidad, no mercado
INDETERMINADO = "indeterminado"      # no se puede afirmar cuál es — no se usa de borde

CLASES = (MEDICION, RECONSTRUIDO, INTRADIA, SINTETICO_COSTO, INDETERMINADO)

# Las dos clases que están EN BASE DE MERCADO. Es la única lista que puede
# sostener un pico o un denominador: mezclar una de éstas con base contable en
# las dos puntas de un mismo tramo es exactamente lo que fabrica el fantasma.
BASE_MERCADO = (MEDICION, RECONSTRUIDO)

# Piso de cobertura para que una foto reconstruida cuente como base de mercado.
# `mtm_coverage` dice qué fracción del valor NO-CASH se pudo valuar a precio real;
# por debajo del piso la foto es mayormente costo, y presentarla como medida sería
# cambiar una mentira etiquetada (`source='import'`) por una sin etiquetar.
COBERTURA_MINIMA = 0.70

# Una serie PLANA es peor que un hueco: el hueco se ve, la serie plana pasa
# todos los guards. Pasa cuando `apply_last_known_prices` completa un símbolo
# delisted desde una tabla global sin TTL — el activo "tiene precio" para
# siempre y el valor no se mueve más. Con este umbral de ruedas seguidas
# idénticas se marca el tramo como degradado.
PLANO_RUEDAS = 3
PLANO_TOL = 0.0001   # 0,01% — dos cierres que difieren menos que esto son "el mismo"


def _es_fin_de_mes(fecha: str) -> bool:
    """¿La fecha ISO es el último día de su mes? El backfill del import escribe
    SIEMPRE a fin de mes; el browser escribe el día que se abrió la app."""
    from datetime import date, timedelta
    try:
        y, m, d = (int(x) for x in fecha[:10].split("-"))
        return (date(y, m, d) + timedelta(days=1)).month != m
    except (ValueError, TypeError):
        return False


# Lo que dice `source` manda: es un hecho estampado al escribir, no una
# deducción. La heurística de abajo queda sólo para las filas anteriores a esa
# columna, que nunca la van a tener.
_POR_SOURCE = {"cron": MEDICION, "browser": INTRADIA, "import": SINTETICO_COSTO,
               "mtm_backfill": RECONSTRUIDO}


def clasificar_fila(row, tenia_posiciones: bool) -> str:
    """Clasifica UN snapshot. `tenia_posiciones` responde si esa persona tenía
    algo no-cash para valuar: sin eso, un holdings_json vacío es lo correcto y
    no una señal de que la fila sea mala."""
    src = row["source"] if "source" in row.keys() else None
    if src == "mtm_backfill":
        # La reconstrucción sólo vale como base de mercado si de verdad se valuó a
        # mercado. Sin cobertura estampada no se puede afirmar → contable.
        cob = row["mtm_coverage"] if "mtm_coverage" in row.keys() else None
        try:
            ok = cob is not None and float(cob) >= COBERTURA_MINIMA
        except (TypeError, ValueError):
            ok = False
        return RECONSTRUIDO if ok else SINTETICO_COSTO
    if src in _POR_SOURCE:
        return _POR_SOURCE[src]
    tiene_holdings = bool(row["holdings_json"])
    tiene_fx = row["fx_to_usd_blue"] is not None

    if tiene_holdings:
        return MEDICION                       # composición estampada: lo escribió el cron
    if tiene_fx and not tenia_posiciones:
        # Cartera 100% cash: el cron deja holdings_json en NULL con razón, y el
        # valor (todo cash) es exacto. Es una medición válida.
        return MEDICION
    if tiene_fx:
        # Tenía posiciones pero no quedó composición → el browser.
        return INTRADIA
    if _es_fin_de_mes(row["date"]):
        return SINTETICO_COSTO                # fin de mes sin nada estampado: el import
    return INDETERMINADO


def primera_fecha_con_posiciones(conn, uid: int):
    """La fecha más vieja en que esta persona tuvo algo NO-CASH. None si nunca.

    ⚠️ ESTO ARREGLA UN FALSO ASCENSO. `_usuarios_con_posiciones` mira las posiciones
    de HOY. Un usuario que vendió todo esta semana da `tenia_posiciones=False`, y con
    ese False sus filas VIEJAS de browser —escritas cuando sí tenía cartera— dejan de
    ser INTRADIA y ASCIENDEN a MEDICION: pasan a habilitar bordes de período que
    nunca fueron una medición. El flag tiene que evaluarse a la fecha de CADA fila.

    "Tuvo algo no-cash en o antes de D" es monótono: una vez verdadero, verdadero
    para siempre. Así que alcanza con la fecha más temprana, y comparar contra ella.
    Se mira la tenencia abierta (`positions.entry_date`) y también la ya cerrada
    (`operations`), porque el usuario que vendió todo es justamente el caso a cubrir.
    """
    fechas = []
    for q, args in (
        ("SELECT MIN(entry_date) AS d FROM positions "
         "WHERE user_id=? AND COALESCE(is_cash,0)=0 AND entry_date IS NOT NULL", (uid,)),
        ("SELECT MIN(COALESCE(entry_date, date)) AS d FROM operations "
         "WHERE user_id=? AND COALESCE(entry_date, date) IS NOT NULL", (uid,)),
    ):
        try:
            r = conn.execute(q, args).fetchone()
        except Exception:
            continue
        if r is not None and r["d"]:
            fechas.append(str(r["d"])[:10])
    if not fechas:
        # Sin fechas utilizables, pero puede haber posiciones no-cash sin entry_date:
        # ahí lo conservador es asumir que SÍ tenía (no ascender nada).
        try:
            hay = conn.execute(
                "SELECT 1 FROM positions WHERE user_id=? AND COALESCE(is_cash,0)=0 LIMIT 1",
                (uid,)).fetchone() is not None
        except Exception:
            hay = False
        return "0000-01-01" if hay else None
    return min(fechas)


def _tenia_posiciones_en(primera, fecha) -> bool:
    """El flag que `clasificar_fila` necesita, evaluado A LA FECHA DE LA FILA."""
    return bool(primera) and str(fecha)[:10] >= primera


def _usuarios_con_posiciones(conn, ids: list) -> set:
    """Quiénes tienen (o tuvieron) alguna posición no-cash. Se usa para no
    castigar al que está todo en pesos."""
    if not ids:
        return set()
    ph = ",".join("?" * len(ids))
    return {r["user_id"] for r in conn.execute(
        f"""SELECT DISTINCT user_id FROM positions
            WHERE user_id IN ({ph}) AND COALESCE(is_cash,0)=0""", ids).fetchall()}


def _tramos_planos(filas: list) -> list:
    """Rachas de ruedas con el valor congelado. Devuelve [(desde, hasta, n)]."""
    fuera, racha = [], []
    for f in filas:
        v = float(f["total_value"] or 0)
        if racha and v > 0 and abs(v - racha[-1][1]) <= abs(racha[-1][1]) * PLANO_TOL:
            racha.append((f["date"], v))
            continue
        if len(racha) >= PLANO_RUEDAS:
            fuera.append((racha[0][0], racha[-1][0], len(racha)))
        racha = [(f["date"], v)] if v > 0 else []
    if len(racha) >= PLANO_RUEDAS:
        fuera.append((racha[0][0], racha[-1][0], len(racha)))
    return fuera


def diagnosticar(conn, ids: list) -> dict:
    """{user_id: diagnóstico} — desde cuándo la historia es medible, y por qué
    no antes. NO ESCRIBE NADA."""
    if not ids:
        return {}
    ids = [int(x) for x in ids]
    ph = ",".join("?" * len(ids))
    por_user = defaultdict(list)
    for r in conn.execute(
            f"""SELECT user_id, date, total_value, fx_to_usd_blue, holdings_json, source,
                       mtm_coverage
                FROM snapshots WHERE user_id IN ({ph}) AND total_value > 0
                ORDER BY user_id, date""", ids).fetchall():
        por_user[r["user_id"]].append(r)
    primera_por_user = {uid: primera_fecha_con_posiciones(conn, uid) for uid in ids}

    out = {}
    for uid in ids:
        filas = por_user.get(uid, [])
        conteo = {c: 0 for c in CLASES}
        mediciones = []
        primera = primera_por_user.get(uid)
        for r in filas:
            c = clasificar_fila(r, _tenia_posiciones_en(primera, r["date"]))
            conteo[c] += 1
            if c == MEDICION:
                mediciones.append(r["date"])

        # El TWR sólo puede empezar donde hay DOS bordes medibles: con una sola
        # medición no hay tramo que medir.
        medible_desde = mediciones[0] if len(mediciones) >= 2 else None
        planos = _tramos_planos([r for r in filas if r["date"] in set(mediciones)])

        out[uid] = {
            "user_id": uid,
            "snapshots": len(filas),
            "por_clase": conteo,
            "medible_desde": medible_desde,
            "ultima_medicion": mediciones[-1] if mediciones else None,
            "motivo": _motivo(conteo, len(mediciones)),
            "tramos_planos": [{"desde": a, "hasta": b, "ruedas": n} for a, b, n in planos],
        }
    return out


def _motivo(conteo: dict, n_mediciones: int) -> str:
    """Por qué no se puede medir, en criollo. None cuando sí se puede."""
    if n_mediciones >= 2:
        return None
    total = sum(conteo.values())
    if total == 0:
        return "sin_historia"
    if conteo[SINTETICO_COSTO] and not n_mediciones:
        return "importado_sin_mediciones"
    if n_mediciones == 1:
        return "una_sola_medicion"
    return "sin_mediciones"


# Texto de cara al usuario. Vive acá y no en el frontend para que el asesor y
# el usuario final lean exactamente lo mismo.
MOTIVO_TEXTO = {
    "sin_historia": "Todavía no hay historia de esta cuenta.",
    "importado_sin_mediciones": "La historia se importó: son datos contables, "
                               "no mediciones a mercado.",
    "una_sola_medicion": "Hay una sola medición: hace falta al menos una "
                         "segunda para medir un período.",
    "sin_mediciones": "Todavía no hay mediciones a mercado de esta cuenta.",
    "sin_tramo_continuo": "Hay mediciones, pero están demasiado separadas entre sí "
                          "como para medir un tramo sin inventar el recorrido del medio.",
    "serie_partida": "La medición tiene un hueco en el medio. Los tramos de cada lado "
                     "se miden solos, pero no se pueden encadenar: no se sabe qué pasó "
                     "en el medio y suponerlo sería inventarlo.",
}


# ═══════════════════════════════════════════════════════════════════════════
# FASE 1 — el primitivo, el sellado y el encadenado
# ═══════════════════════════════════════════════════════════════════════════

# Un aporte que supera esta fracción del capital inicial se marca para revisar
# antes de entrar en la cadena: normalmente es un import que reescribió la
# historia, no plata que entró de verdad.
FLUJO_SOSPECHOSO = 0.5


def dietz(v0: float, v1: float, flow: float):
    """Modified Dietz de UN tramo. Es EL primitivo: si alguna pantalla calcula
    el retorno de otra forma, vuelve a haber dos motores.

        r = (v1 − v0 − flujo) / (v0 + 0,5·flujo)

    El 0,5 pondera el aporte como si hubiera entrado a mitad del tramo. Devuelve
    None cuando el denominador no da para medir (sin capital no hay retorno).

    SIN TECHO. El clamp de +50% que arrastra el lado retail trunca meses reales
    (+80% en cripto o post-devaluación es perfectamente posible) y encima NO se
    le aplica al benchmark → el sesgo es sistemático en contra del usuario y se
    compone mes a mes. El piso de −100% sí: no se puede perder más que todo.
    """
    denom = v0 + 0.5 * flow
    if denom <= 0:
        return None
    return max((v1 - v0 - flow) / denom, -1.0)


def _fin_de_mes(mes: str) -> str:
    from datetime import date, timedelta
    y, m = (int(x) for x in mes.split("-"))
    return ((date(y + (m == 12), (m % 12) + 1, 1)) - timedelta(days=1)).isoformat()


def _hoy_art() -> str:
    from datetime import datetime, timedelta
    return (datetime.utcnow() - timedelta(hours=3)).date().isoformat()


def bordes_medibles(conn, uid: int) -> list:
    """Los cierres que sirven de borde, en orden. SOLO mediciones a mercado:
    una foto intradía del browser o una fila fabricada al costo por el import
    no son un cierre, y encadenarlas mide cualquier cosa menos el mercado."""
    primera = primera_fecha_con_posiciones(conn, uid)
    filas = conn.execute(
        """SELECT id, date, total_value, fx_to_usd_blue, holdings_json, source,
                  mtm_coverage
           FROM snapshots WHERE user_id=? AND total_value > 0 ORDER BY date""",
        (uid,)).fetchall()
    return [r for r in filas
            if clasificar_fila(r, _tenia_posiciones_en(primera, r["date"])) == MEDICION]


def _flujo(conn, uid: int, desde: str, hasta: str) -> float:
    """Aportes netos entre dos fechas. Sale de la SSoT canónica de la app
    (`compute_net_deposited_db`), no de una cuenta propia — si el TWR usara su
    propia definición de flujo, discutiría con el resto de las pantallas."""
    from snapshots_job import compute_net_deposited_db
    return (compute_net_deposited_db(conn, uid, as_of_date=hasta)
            - compute_net_deposited_db(conn, uid, as_of_date=desde))


def tramos(conn, uid: int, hasta_mes: str = None) -> list:
    """Los tramos MENSUALES medibles de un usuario, sin tocar la base.

    El cliente entra recién desde su primer mes CALENDARIO COMPLETO: el mes de
    alta no se mide. Con capital_inicio = 0 el 0,5 del Dietz infla ese mes
    (medido: 23,71% reportado contra 20,10% real), y en un libro de asesor
    TODOS los clientes nuevos tienen ese mes. Excluirlo elimina el sesgo de
    raíz en vez de estimarlo — es lo que hace GIPS.
    """
    bordes = bordes_medibles(conn, uid)
    if len(bordes) < 2:
        return []
    tope = hasta_mes or _hoy_art()[:7]

    # Último borde de cada mes: el cierre del mes.
    cierre = {}
    for b in bordes:
        cierre[b["date"][:7]] = b

    meses = sorted(cierre)
    out = []
    for i in range(1, len(meses)):
        mes = meses[i]
        if mes >= tope:            # el mes en curso no se sella: todavía no cerró
            continue
        b0, b1 = cierre[meses[i - 1]], cierre[mes]
        v0, v1 = float(b0["total_value"]), float(b1["total_value"])
        flow = _flujo(conn, uid, b0["date"], b1["date"])
        r = dietz(v0, v1, flow)
        if r is None:
            continue
        calidad = "ok"
        if v0 > 0 and abs(flow) > v0 * FLUJO_SOSPECHOSO:
            calidad = "flujo_sospechoso"
        elif abs(v1 - v0) <= abs(v0) * PLANO_TOL and abs(flow) <= abs(v0) * PLANO_TOL:
            calidad = "plano"
        out.append({
            "month": mes, "period_start": b0["date"], "period_end": b1["date"],
            "v0_usd": v0, "v1_usd": v1, "flow_usd": flow, "ret": r,
            "quality": calidad,
            "snap_id_start": b0["id"], "snap_id_end": b1["id"],
            "fx_basis": "mep_medio",
        })
    return out


_CAMPOS_SELLO = ("period_start", "period_end", "v0_usd", "v1_usd", "flow_usd")


def sellar(conn, uid: int, hasta_mes: str = None) -> dict:
    """Sella los meses cerrados. Idempotente: recalcular no cambia nada si el
    input no cambió. Si SÍ cambió (un import reescribió la historia, un deploy
    corrió el hook que recalcula el aportado hacia atrás), se escribe
    revision+1 — nunca se pisa la revisión vieja. Que la historia haya cambiado
    es justamente lo que el asesor tiene que poder ver."""
    nuevos = revisados = 0
    for t in tramos(conn, uid, hasta_mes):
        prev = conn.execute(
            "SELECT * FROM twr_periods WHERE user_id=? AND month=? "
            "ORDER BY revision DESC LIMIT 1", (uid, t["month"])).fetchone()
        if prev is not None:
            igual = all(
                (abs(float(prev[c]) - float(t[c])) < 0.005) if isinstance(t[c], float)
                else prev[c] == t[c]
                for c in _CAMPOS_SELLO)
            if igual:
                continue
            rev = int(prev["revision"]) + 1
            revisados += 1
        else:
            rev = 1
            nuevos += 1
        conn.execute(
            """INSERT INTO twr_periods
               (user_id, period_start, period_end, month, v0_usd, v1_usd,
                flow_usd, ret, quality, snap_id_start, snap_id_end, fx_basis, revision)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uid, t["period_start"], t["period_end"], t["month"], t["v0_usd"],
             t["v1_usd"], t["flow_usd"], t["ret"], t["quality"],
             t["snap_id_start"], t["snap_id_end"], t["fx_basis"], rev))
    return {"sellados": nuevos, "revisados": revisados}


def sellados(conn, uid: int, desde_mes: str = None, hasta_mes: str = None) -> list:
    """La revisión VIGENTE de cada mes sellado, en orden."""
    q = ["SELECT * FROM twr_periods t WHERE t.user_id=?",
         "AND t.revision = (SELECT MAX(t2.revision) FROM twr_periods t2 "
         "WHERE t2.user_id=t.user_id AND t2.month=t.month)"]
    p = [uid]
    if desde_mes:
        q.append("AND t.month >= ?"); p.append(desde_mes)
    if hasta_mes:
        q.append("AND t.month <= ?"); p.append(hasta_mes)
    q.append("ORDER BY t.month")
    return conn.execute(" ".join(q), p).fetchall()


def twr_de(conn, uid: int, desde_mes: str = None, hasta_mes: str = None) -> dict:
    """El TWR encadenado de un usuario, sobre lo SELLADO.

        TWR = Π(1 + r_mes) − 1

    Devuelve siempre la cobertura pegada al número: un retorno sin decir sobre
    cuántos meses se midió es exactamente el dato que después hay que salir a
    explicar. Si la cobertura no alcanza, no se devuelve porcentaje: se
    devuelve el motivo.
    """
    filas = sellados(conn, uid, desde_mes, hasta_mes)
    if not filas:
        return {"twr": None, "meses": 0, "motivo": "sin_periodos_sellados"}

    idx = 1.0
    for f in filas:
        idx *= (1.0 + float(f["ret"]))

    revisados = [f["month"] for f in filas if int(f["revision"]) > 1]
    degradados = [f["month"] for f in filas if f["quality"] != "ok"]
    return {
        "twr": idx - 1.0,
        "meses": len(filas),
        "desde": filas[0]["month"],
        "hasta": filas[-1]["month"],
        "meses_revisados": revisados,     # a estos les cambió la historia
        "meses_degradados": degradados,
        "motivo": None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# FASE 2 — LA SERIE CANÓNICA
#
# Todo lo que dibuje una curva de performance o publique un drawdown tiene que
# salir de acá. Mientras cada pantalla arme su propia serie sobre la cadena
# contable, cualquier guard nuevo en Python se queda corto — que es literalmente
# lo que ya pasó: `applyMtmToMonthly` descarta sintéticos y se abstiene sin borde
# medido (insightsModel.js:621 y :653), y trece líneas después
# `buildCumulativeReturnSeries` (insightsModel.js:106) pisa el cierre con el
# valor live sin mirar `m.mtm` y desarma el guard entero.
# ═══════════════════════════════════════════════════════════════════════════

# Cuántos días de silencio parten la serie en dos tramos. Más que esto y unir los
# dos puntos con una recta es inventar el recorrido del medio.
MAX_HUECO_DIAS = 45


def _dias(a: str, b: str) -> int:
    from datetime import date
    ya, ma, da = (int(x) for x in str(a)[:10].split("-"))
    yb, mb, db = (int(x) for x in str(b)[:10].split("-"))
    return abs((date(yb, mb, db) - date(ya, ma, da)).days)


def serie_medible(conn, uid: int, desde: str = None, hasta: str = None, *,
                  aceptar: tuple = BASE_MERCADO,
                  max_hueco_dias: int = MAX_HUECO_DIAS) -> dict:
    """Los puntos de la serie que SE PUEDEN usar, partidos donde hay huecos.

    `aceptar` es el nivel de exigencia:
      · BASE_MERCADO (default) — MEDICION|RECONSTRUIDO. El único nivel que puede
        sostener un pico o un denominador.
      · BASE_MERCADO + (INDETERMINADO,) — afloja para no borrarle la línea a los
        usuarios cuyas filas son anteriores a la columna `source`. Esas filas
        entran marcadas con `apto=False`: pueden sostener UNA LÍNEA, nunca ser un
        pico ni un denominador. La regla se aplica en `curva_indexada`, no queda
        librada al criterio del que consuma esto.

    LOS HUECOS NO SE RELLENAN. Un hueco visible es información; uno interpolado es
    exactamente el mismo crimen que el snapshot sintético — un número que el
    sistema inventó y que el usuario lee como si lo hubiera vivido.

    Devuelve también `contable`: lo que quedó AFUERA. No se tira, porque el
    usuario importó esa historia y tiene derecho a verla — pero va por separado,
    para dibujarse como banda y nunca como continuación de la línea medida.
    """
    q = ["""SELECT date, total_value, total_invested, net_deposited,
                   fx_to_usd_blue, holdings_json, source, mtm_coverage
              FROM snapshots WHERE user_id=? AND total_value > 0"""]
    args = [uid]
    if desde:
        q.append("AND date >= ?"); args.append(desde)
    if hasta:
        q.append("AND date <= ?"); args.append(hasta)
    q.append("ORDER BY date")
    filas = conn.execute(" ".join(q), args).fetchall()

    primera_pos = primera_fecha_con_posiciones(conn, uid)
    puntos, contable, conteo = [], [], {c: 0 for c in CLASES}
    for r in filas:
        c = clasificar_fila(r, _tenia_posiciones_en(primera_pos, r["date"]))
        conteo[c] += 1
        d = str(r["date"])[:10]
        if c in aceptar:
            puntos.append({
                "date": d, "value": float(r["total_value"]),
                "net_deposited": float(r["net_deposited"] or 0),
                "clase": c, "apto": c in BASE_MERCADO,
                "cobertura": (float(r["mtm_coverage"])
                              if r["mtm_coverage"] is not None else None),
            })
        else:
            contable.append({"date": d, "value": float(r["total_value"]), "clase": c})

    # Partir donde el silencio es demasiado largo.
    tramos, actual = [], []
    for p in puntos:
        if actual and _dias(actual[-1]["date"], p["date"]) > max_hueco_dias:
            tramos.append(actual); actual = []
        actual.append(p)
    if actual:
        tramos.append(actual)

    aptos = [p for p in puntos if p["apto"]]
    total = len(filas)
    cobertura = (len(aptos) / total) if total else 0.0
    # Cobertura media de lo reconstruido: un tramo reconstruido al 71% pasa el
    # piso pero NO es lo mismo que una foto del cron, y el usuario tiene que
    # poder verlo en el tooltip.
    cobs = [p["cobertura"] for p in puntos
            if p["clase"] == RECONSTRUIDO and p["cobertura"] is not None]

    return {
        "puntos": puntos,
        "tramos": tramos,
        "contable": contable,
        "por_clase": conteo,
        "cobertura": round(cobertura, 4),
        "cobertura_reconstruccion": (round(sum(cobs) / len(cobs), 4) if cobs else None),
        "medido_desde": (aptos[0]["date"] if aptos else None),
        "medido_hasta": (aptos[-1]["date"] if aptos else None),
        "motivo": _motivo(conteo, len(aptos)),
        "motivo_texto": MOTIVO_TEXTO.get(_motivo(conteo, len(aptos))),
    }


def curva_indexada(conn, uid: int, desde: str = None, hasta: str = None, *,
                   aceptar: tuple = BASE_MERCADO,
                   max_hueco_dias: int = MAX_HUECO_DIAS,
                   valor_live: float = None) -> dict:
    """La curva indexada + drawdown + CAGR, encadenando `dietz` sobre `serie_medible`.

    SIN CLAMPS ASIMÉTRICOS. El techo de +50% por mes que aplica el lado retail
    (`Insights.jsx:683`, `evolution.js:317`) trunca meses reales y —el punto— NO se
    le aplica al benchmark, así que el sesgo va sistemáticamente en contra del
    usuario y se compone mes a mes. Sólo queda el piso de −100% de `dietz`: no se
    puede perder más que todo.

    LAS DOS REGLAS QUE NO SE NEGOCIAN:
      · un punto no-apto (INDETERMINADO) nunca es DENOMINADOR: si el arranque de
        un tramo no es base de mercado, ese tramo no produce retorno.
      · un punto no-apto nunca es PICO: el drawdown se mide contra máximos que de
        verdad se alcanzaron, no contra un valor que el sistema no puede afirmar.
        Es exactamente el defecto que reportó el usuario ("yo nunca llegué tan
        arriba"): el pico lo había puesto el sistema.
    """
    s = serie_medible(conn, uid, desde, hasta, aceptar=aceptar,
                      max_hueco_dias=max_hueco_dias)
    if not s["puntos"]:
        # La forma de la respuesta NO cambia cuando no hay datos: si faltaran
        # claves, cada consumidor tendría que adivinar — y el estado vacío es
        # justamente el que más se lee mal.
        return {**s, "curva": [], "twr": None, "cagr": None,
                "drawdown_actual": None, "drawdown_maximo": None,
                "drawdown_maximo_fecha": None, "drawdown_maximo_pico": None}

    # ⚠️ EL ÍNDICE Y EL PICO SE REINICIAN EN CADA TRAMO.
    #
    # `serie_medible` parte la serie donde hubo más de `max_hueco_dias` de
    # silencio, y ese corte existe porque NO SE SABE qué pasó adentro del hueco.
    # Si el índice se arrastrara de un tramo al siguiente, el derrumbe que ocurrió
    # dentro del hueco desaparece y el tramo 2 compone encima del tramo 1.
    # Medido: 10.000 → 12.000 · [hueco con caída a 6.000] · 6.000 → 6.600
    # devolvía +32% cuando punta a punta es −34%. Y no es un caso de laboratorio:
    # el backfill escribe un punto por mes, así que basta con que UN mes caiga
    # bajo el piso de cobertura para que el hueco pase de 30 a ~60 días y parta
    # la cadena — cruzar el umbral recableaba la curva entera en silencio.
    curva = []
    tramos_info = []       # {desde, hasta, twr, dd_max, legs} por tramo
    dd_actual = None
    idx_ultimo_tramo = 1.0

    for tramo in s["tramos"]:
        idx = 1.0
        legs_t = 0
        pico = None
        pico_fecha = None
        dd_max_t, dd_max_fecha_t, dd_max_pico_t = 0.0, None, None
        for i, p in enumerate(tramo):
            if i == 0:
                ret = None                       # arranque de tramo: no hay v0
            else:
                a = tramo[i - 1]
                if not a["apto"]:
                    ret = None                   # denominador no publicable
                else:
                    flow = p["net_deposited"] - a["net_deposited"]
                    ret = dietz(a["value"], p["value"], flow)
            if ret is not None:
                idx *= (1.0 + ret)
                legs_t += 1
            punto = {"date": p["date"], "index": round(idx, 6),
                     "value": p["value"], "clase": p["clase"],
                     "apto": p["apto"], "ret": ret,
                     "estimado": ret is None and i > 0}
            if p["apto"]:
                if pico is None or idx > pico:
                    pico, pico_fecha = idx, p["date"]
                dd = (idx / pico) - 1.0 if pico and pico > 0 else 0.0
                dd_actual = dd
                if dd < dd_max_t:
                    dd_max_t, dd_max_fecha_t, dd_max_pico_t = dd, p["date"], pico_fecha
                punto["drawdown"] = round(dd, 6)
            curva.append(punto)
        tramos_info.append({
            "desde": tramo[0]["date"], "hasta": tramo[-1]["date"],
            "legs": legs_t, "twr": (idx - 1.0) if legs_t > 0 else None,
            "drawdown_maximo": round(dd_max_t, 6) if legs_t > 0 else None,
            "drawdown_maximo_fecha": dd_max_fecha_t,
            "drawdown_maximo_pico": dd_max_pico_t,
        })
        idx_ultimo_tramo = idx

    # Sólo se puede publicar UN número punta a punta si toda la medición cabe en
    # UN tramo continuo. Con la serie partida, ni el TWR ni el drawdown máximo son
    # afirmables: el peor momento puede haber estado adentro del hueco, y publicar
    # el máximo de los tramos medidos sería dar una COTA INFERIOR con nombre de
    # máximo — subestimar el riesgo con autoridad.
    con_legs = [t for t in tramos_info if t["legs"] > 0]
    legs = sum(t["legs"] for t in tramos_info)
    partida = len(con_legs) > 1
    publicable = len(con_legs) == 1

    if publicable:
        _t = con_legs[0]
        idx = 1.0 + _t["twr"]
        pico = max(1.0, idx)
        dd_max = _t["drawdown_maximo"]
        dd_max_fecha = _t["drawdown_maximo_fecha"]
        dd_max_pico_fecha = _t["drawdown_maximo_pico"]
        # `pico` sólo se usa de acá en adelante para el cierre live. El HWM del
        # tramo es el índice más alto que alcanzó; se recalcula desde la curva
        # para no depender de en qué punto quedó `idx`.
        _idxs = [c["index"] for c in curva if c.get("apto")]
        pico = max(_idxs) if _idxs else 1.0
        pico_fecha = next((c["date"] for c in curva
                           if c.get("apto") and c["index"] == pico), None)
    else:
        # ⚠️ Sin ningún tramo medido (o con la serie partida) el índice se quedó
        # en 1.0 — y devolver eso como `twr: 0.0` / `drawdown: 0.0` es publicar
        # "el período fue plano" sin haber medido nada. `drawdown_maximo` es el
        # que faltaba: `twr` y `drawdown_actual` ya tenían su guard y éste no,
        # así que el 452 iba a leer "peak histórico 0,0%" en el mismo lugar donde
        # leía −45%, y con `drawdown_maximo_fecha` en None: se contradecía solo.
        idx, pico, pico_fecha = 1.0, None, None
        dd_actual = dd_max = dd_max_fecha = dd_max_pico_fecha = None

    # El valor live cierra la curva SOLO si el último borde es base de mercado Y
    # la serie no está partida (si lo está, no hay índice contra el cual componer).
    ultimo_apto = next((p for p in reversed(s["puntos"]) if p["apto"]), None)
    if (publicable and valor_live and valor_live > 0
            and ultimo_apto is not None and curva and s["puntos"][-1]["apto"]):
        r = dietz(ultimo_apto["value"], float(valor_live), 0.0)
        if r is not None:
            idx *= (1.0 + r)
            legs += 1
            if pico is None or idx > pico:
                pico, pico_fecha = idx, "hoy"
            dd_actual = (idx / pico) - 1.0 if pico and pico > 0 else 0.0
            if dd_max is None or dd_actual < dd_max:
                dd_max, dd_max_fecha, dd_max_pico_fecha = dd_actual, "hoy", pico_fecha
            curva.append({"date": "hoy", "index": round(idx, 6),
                          "value": float(valor_live), "clase": MEDICION,
                          "apto": True, "ret": r, "estimado": False,
                          "drawdown": round(dd_actual, 6)})

    cagr = None
    if publicable and legs > 0 and idx > 0:
        _c0 = next((c["date"] for c in curva if c.get("apto")), None)
        _c1 = curva[-1]["date"] if curva[-1]["date"] != "hoy" else _hoy_art()
        if _c0:
            años = _dias(_c0, _c1) / 365.25
            if años >= 0.5:            # bajo medio año, anualizar es propaganda
                cagr = idx ** (1.0 / años) - 1.0

    _motivo = s["motivo"]
    if not _motivo:
        if partida:
            _motivo = "serie_partida"
        elif legs == 0:
            _motivo = "sin_tramo_continuo"

    return {
        **s,
        "curva": curva,
        "twr": (idx - 1.0) if (publicable and legs > 0) else None,
        "tramos_medidos": legs,
        "tramos_detalle": tramos_info,
        "serie_partida": partida,
        "motivo": _motivo,
        "motivo_texto": (MOTIVO_TEXTO.get(_motivo) if _motivo else None),
        "drawdown_actual": (round(dd_actual, 6) if dd_actual is not None else None),
        "drawdown_maximo": (round(dd_max, 6) if dd_max is not None else None),
        "drawdown_maximo_fecha": dd_max_fecha,
        "drawdown_maximo_pico": dd_max_pico_fecha,
        "cagr": cagr,
    }
