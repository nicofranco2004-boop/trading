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
INTRADIA = "intradia"                # foto de media rueda escrita por un browser
SINTETICO_COSTO = "sintetico_costo"  # fabricado por el import: contabilidad, no mercado
INDETERMINADO = "indeterminado"      # no se puede afirmar cuál es — no se usa de borde

CLASES = (MEDICION, INTRADIA, SINTETICO_COSTO, INDETERMINADO)

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
_POR_SOURCE = {"cron": MEDICION, "browser": INTRADIA, "import": SINTETICO_COSTO}


def clasificar_fila(row, tenia_posiciones: bool) -> str:
    """Clasifica UN snapshot. `tenia_posiciones` responde si esa persona tenía
    algo no-cash para valuar: sin eso, un holdings_json vacío es lo correcto y
    no una señal de que la fila sea mala."""
    src = row["source"] if "source" in row.keys() else None
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
    con_pos = _usuarios_con_posiciones(conn, ids)

    por_user = defaultdict(list)
    for r in conn.execute(
            f"""SELECT user_id, date, total_value, fx_to_usd_blue, holdings_json, source
                FROM snapshots WHERE user_id IN ({ph}) AND total_value > 0
                ORDER BY user_id, date""", ids).fetchall():
        por_user[r["user_id"]].append(r)

    out = {}
    for uid in ids:
        filas = por_user.get(uid, [])
        conteo = {c: 0 for c in CLASES}
        mediciones = []
        for r in filas:
            c = clasificar_fila(r, uid in con_pos)
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
    con_pos = uid in _usuarios_con_posiciones(conn, [uid])
    filas = conn.execute(
        """SELECT id, date, total_value, fx_to_usd_blue, holdings_json, source
           FROM snapshots WHERE user_id=? AND total_value > 0 ORDER BY date""",
        (uid,)).fetchall()
    return [r for r in filas if clasificar_fila(r, con_pos) == MEDICION]


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
