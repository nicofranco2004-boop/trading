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

# ⚠️ DOS PREGUNTAS DISTINTAS, DOS LISTAS DISTINTAS.
#
# Confundirlas costó caro: al filtrar TODA serie con la lista de bordes, un
# usuario 100% sano —600 fotos del cron, cero imports— se quedaba con 51 puntos.
# Las columnas `holdings_json` y `source` se agregaron el 2026-07-04 y el
# 2026-08-06; TODO lo que el cron escribió antes tiene fx pero no composición, y
# la heurística lo llama INTRADIA (twr.py:100-102). Su CAGR pasaba de +13,7%
# sobre 19 meses a −56,9% sobre "1 mes".
#
# Aflojar la lista fue lo correcto; aflojar UNA SOLA lista no. `BASE_MERCADO`
# respondía a la vez "¿qué punto entra a la serie?" y "¿qué punto puede ser PICO o
# DENOMINADOR?", y meter INTRADIA ahí adentro hizo que una foto del browser fijara
# máximos: una cartera plana en 10.000 todos los cierres publicaba
# "Drawdown −33,3%" con el pico en la foto de media rueda, y el drawdown EMPEORABA
# cuantas más veces el usuario abría la app. El sesgo va en una sola dirección
# —los picos sólo suben—, así que cada foto que sobrevive lo empeora para siempre.
#
#   BASE_MERCADO — el punto es un cierre afirmable: puede ser BORDE de período,
#     PICO y DENOMINADOR. Es la exigencia máxima y es UNA sola pregunta: cerrar un
#     período contra el valor de hoy y fijar un máximo histórico piden lo mismo.
#
#   ACEPTA_LINEA — lo que entra a la serie DIBUJADA. Una foto intradía es un valor
#     de mercado (posiciones × precio, no contabilidad), así que sostiene la línea;
#     entra con `apto=False` y `curva_indexada` se encarga de que nunca sea pico ni
#     denominador. Es el mismo contrato que ya estaba escrito para INDETERMINADO.
#
# Lo que NUNCA entra en ninguna es SINTETICO_COSTO: no es una medición de nada,
# es la cadena contable copiada. Ése era el defecto original.
BASE_MERCADO = (MEDICION, RECONSTRUIDO)
ACEPTA_LINEA = BASE_MERCADO + (INTRADIA,)
# Alias explícito para los callers que preguntan por un BORDE de período. Es la
# misma tupla a propósito: son la misma exigencia.
BORDE_PERIODO = BASE_MERCADO

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


# Cuántas ruedas seguidas —día calendario a día calendario, sin saltar ninguno—
# hacen falta para afirmar que a esa tanda la escribió el cron y no una persona.
# El cron corre TODOS los días, incluidos sábados, domingos y feriados; el browser
# escribe salteado y sólo cuando el usuario entra. Siete días corridos sin un solo
# hueco ya es una cadencia que una persona no produce.
RACHA_CRON_MINIMA = 7


def clasificar_serie(filas, primera_pos, orden_desc: bool = False) -> list:
    """Clasifica una SERIE de snapshots. Devuelve una clase por fila, en el mismo
    orden en que vinieron.

    Hace todo lo que hace `clasificar_fila` MÁS una cosa que una fila sola no
    puede saber: la CADENCIA.

    ⚠️ POR QUÉ HACE FALTA. `clasificar_fila` mira una fila aislada y, sin
    `source` ni `holdings_json`, cae en `if tiene_fx: return INTRADIA  # el
    browser` (twr.py, más abajo). Pero las columnas `holdings_json` y `source` se
    agregaron el 2026-07-04 y el 2026-08-06: TODAS las fotos que el cron escribió
    antes tienen esa firma y quedaban etiquetadas como si las hubiera sacado una
    persona a media rueda. Con eso, o se les negaba la serie a los usuarios viejos,
    o —aflojando la lista— una foto de browser pasaba a fijar picos.

    La información para desambiguarlas SÍ existe, pero está en el vecindario, no
    en la fila: una tanda de días calendario consecutivos SIN UN SOLO HUECO la
    escribió el cron. Sólo se aplica a filas LEGACY (sin `source`): una fila que
    dice `source='browser'` se respeta siempre — lo que dice `source` manda.
    """
    filas = list(filas)
    if orden_desc:
        filas = filas[::-1]
    clases = [clasificar_fila(r, _tenia_posiciones_en(primera_pos, r["date"]))
              for r in filas]

    def _legacy(r):
        try:
            return ("source" not in r.keys()) or (r["source"] is None)
        except AttributeError:
            return r.get("source") is None

    # Rachas de días calendario consecutivos.
    ini = 0
    for i in range(1, len(filas) + 1):
        corta = (i == len(filas)) or (_dias(filas[i - 1]["date"], filas[i]["date"]) != 1)
        if not corta:
            continue
        if (i - ini) >= RACHA_CRON_MINIMA:
            for j in range(ini, i):
                if clases[j] == INTRADIA and _legacy(filas[j]):
                    clases[j] = MEDICION
        ini = i

    return clases[::-1] if orden_desc else clases


def backfill_source_legacy(conn, uids: list) -> dict:
    """Estampa `source='cron'` en las filas LEGACY que la cadencia identifica como
    del cron. Idempotente: sólo toca filas con `source IS NULL`.

    ⚠️ POR QUÉ MATERIALIZAR Y NO RESOLVERLO A READ-TIME.
    Resolverlo al leer parece equivalente y es más barato, pero es ESTRICTAMENTE
    MÁS DÉBIL, y ya lo pagamos: cada lector tiene que ACORDARSE de llamar a
    `clasificar_serie`, y uno no se acordó. Llegaron a convivir dos criterios sobre
    la MISMA fila del MISMO usuario en la misma sesión — `serie_medible` la veía
    MEDICION y `/api/snapshots` INTRADIA, con lo cual a un usuario sano se le
    degradaban 549 de 600 fotos en la lista y ninguna en la curva.
    Materializado, eso es imposible: no hay dos lectores que puedan discrepar, una
    fila nueva no puede reescribir la clase del pasado, y la clase deja de depender
    de qué ventana se leyó.

    Va por TANDAS y sin crear ningún índice: en este repo una migración que tocó el
    orden columna/índice se llevó producción puesta 20 minutos.
    """
    tocados = filas = 0
    for uid in uids:
        rows = conn.execute(
            """SELECT id, date, total_value, fx_to_usd_blue, holdings_json, source,
                      mtm_coverage
                 FROM snapshots WHERE user_id=? ORDER BY date""", (uid,)).fetchall()
        if not rows:
            continue
        if all(r["source"] is not None for r in rows):
            continue                       # ya estampado: nada que hacer
        primera = primera_fecha_con_posiciones(conn, uid)
        clases = clasificar_serie(rows, primera)
        # SÓLO lo que aporta la cadencia: filas que solas se leerían INTRADIA y que
        # la tanda diaria identifica como del cron. Una fila que ya se clasifica
        # bien mirada sola (p. ej. la de una cartera 100% cash) no necesita
        # estamparse — y estamparla sería afirmar 'cron' sobre algo que también
        # pudo escribir el browser.
        solas = [clasificar_fila(r, _tenia_posiciones_en(primera, r["date"]))
                 for r in rows]
        ids = [r["id"] for r, c, sola in zip(rows, clases, solas)
               if r["source"] is None and c == MEDICION and sola == INTRADIA]
        if not ids:
            continue
        for i in range(0, len(ids), 500):
            lote = ids[i:i + 500]
            ph = ",".join("?" * len(lote))
            conn.execute(
                f"UPDATE snapshots SET source='cron' WHERE source IS NULL AND id IN ({ph})",
                lote)
        tocados += 1
        filas += len(ids)
    return {"usuarios": tocados, "filas": filas}


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
    return [r for r, c in zip(filas, clasificar_serie(filas, primera)) if c == MEDICION]


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


def netdep_canonico(conn, uid: int):
    """date → net_deposited, calculado AHORA desde `monthly_entries`.

    ⚠️ POR QUÉ NO SE USA LA COLUMNA ESTAMPADA. `snapshots.net_deposited` no es un
    hecho del día: es una MEDICIÓN que el escritor hizo sobre `monthly_entries` EN
    EL MOMENTO de escribir la fila (snapshots_job.py:752). Un import reescribe
    `monthly_entries` hacia atrás y NO re-estampa las fotos viejas, así que en la
    misma serie conviven estampas de dos momentos distintos. Restarlas para sacar
    "el flujo de la ventana" no mide un flujo: mide cuánto cambió la contabilidad
    entre los dos momentos en que se escribió cada foto.

    Medido: julio plano en 110.000, cero aportes en julio, cron diario sano, y un
    import del historial 2025 el 16/7 → el mes cerrado publicaba −US$50.000 /
    −37,04% y Diagnóstico el mismo −37,04% de drawdown. Y un mes cerrado NO SE
    AUTOCURA NUNCA. El par mezclado está GARANTIZADO, no es mala suerte: el
    reconstructor estampa desde el `monthly_entries` actual y saltea las fotos del
    cron a propósito.

    Las dos puntas salen de la MISMA lectura, así que la resta vuelve a ser un
    flujo. Es la convención canónica —filas 'global' + baseline— la misma que
    estampan el cron (`compute_net_deposited`) y `_recompute_snapshots_netdep_for_user`.
    """
    filas = conn.execute(
        "SELECT year, month, capital_inicio, deposits, withdrawals FROM monthly_entries "
        "WHERE user_id=? AND broker='global' ORDER BY year, month", (uid,)).fetchall()
    if not filas:
        # Sin contabilidad no hay nada que afirmar: devolver 0 para todo convertiría
        # cualquier aporte en ganancia. El caller se queda con lo estampado.
        return None
    baseline = float(filas[0]["capital_inicio"] or 0)
    acum, cum = [], 0.0
    for r in filas:
        cum += float(r["deposits"] or 0) - float(r["withdrawals"] or 0)
        acum.append((f"{int(r['year']):04d}-{int(r['month']):02d}", baseline + cum))

    def _en(fecha):
        ym = str(fecha)[:7]
        # ⚠️ ANTES DE LA PRIMERA FILA VALE EL BASELINE, NO CERO — y acá se aparta a
        # propósito de lo que estampa `compute_net_deposited_db`.
        # El baseline (`capital_inicio` de la primera fila) es un STOCK: la plata
        # que ya estaba cuando arranca la contabilidad. La convención estampada lo
        # atribuye al primer mes, y eso está bien para "cuánto puso en total" pero
        # es veneno para una RESTA: el borde anterior daba 0 y el posterior daba el
        # baseline entero, así que un año entero publicaba −62,3% porque el primer
        # tramo leía el baseline como un aporte de enero. Un stock tiene que
        # aparecer a los DOS lados de la resta para cancelarse.
        v = baseline
        for k, val in acum:
            if k <= ym:
                v = val
            else:
                break
        return v
    return _en


# Cuánto puede alejarse la estampa del total contable del mes sin que se la
# considere desactualizada. Un dólar, o una millonésima del total.
_TOL_ESTAMPA = 1.0


def _aportado_por_punto(conn, uid: int, filas):
    """Devuelve fila → aportado acumulado, eligiendo la mejor fuente MES A MES.

    ⚠️ NINGUNA DE LAS DOS FUENTES SIRVE SOLA, y elegir mal rompe cosas distintas:

    · LA ESTAMPA (`snapshots.net_deposited`) es DIARIA de verdad: el cron corre
      todos los días y escribe el acumulado del momento, así que un depósito del
      20 aparece el 20. Pero un import reescribe `monthly_entries` hacia atrás y
      NO re-estampa las fotos viejas: quedan estampas de dos momentos en la misma
      serie y la resta mide cuánto cambió la contabilidad, no un flujo. Eso
      publicaba −37% en un mes donde no pasó nada.

    · EL CANÓNICO (`netdep_canonico`) es consistente —las dos puntas salen de la
      misma lectura— pero tiene resolución MENSUAL, porque los flujos manuales se
      guardan en `monthly_entries.manual_*` sin fecha. Enchufado punto a punto en
      una curva DIARIA, retro-atribuye el depósito del 20 al día 1: aparece un
      flujo enorme contra un valor que todavía no lo incluye. Medido con el
      mercado literalmente inmóvil: drawdown de −9,52% donde lo real es 0.

    La regla: se prefiere la ESTAMPA, que es la que tiene resolución, y se cae al
    canónico SÓLO en los meses donde la estampa dejó de coincidir con la
    contabilidad actual — que es exactamente la señal de "acá hubo un import".
    Un mes incompleto (el cron se cortó antes de fin de mes) no se juzga: ahí la
    estampa puede ser legítimamente menor que el total del mes.
    """
    canon = netdep_canonico(conn, uid)
    if canon is None:                      # sin contabilidad: sólo queda la estampa
        return lambda r: float(r["net_deposited"] or 0)

    from datetime import date as _date, timedelta as _td

    def _es_fin_de_mes(f):
        try:
            y, m, d = (int(x) for x in str(f)[:10].split("-"))
            return (_date(y, m, d) + _td(days=1)).month != m
        except (ValueError, TypeError):
            return False

    ultimo_del_mes, hay_estampa = {}, False
    for r in filas:
        ym = str(r["date"])[:7]
        prev = ultimo_del_mes.get(ym)
        if prev is None or str(r["date"]) > str(prev["date"]):
            ultimo_del_mes[ym] = r
        if (r["net_deposited"] or 0):
            hay_estampa = True
    if not hay_estampa:                    # filas legacy con la columna en 0
        return lambda r: canon(str(r["date"])[:10])

    desconfiar = set()
    for ym, r in ultimo_del_mes.items():
        if not _es_fin_de_mes(r["date"]):
            continue                       # mes incompleto: no se juzga
        esperado = canon(str(r["date"])[:10])
        if abs(float(r["net_deposited"] or 0) - esperado) > max(
                _TOL_ESTAMPA, abs(esperado) * 1e-6):
            desconfiar.add(ym)

    def _en(r):
        ym = str(r["date"])[:7]
        if ym in desconfiar:
            return canon(str(r["date"])[:10])
        return float(r["net_deposited"] or 0)
    return _en


def serie_medible(conn, uid: int, desde: str = None, hasta: str = None, *,
                  aceptar: tuple = ACEPTA_LINEA,
                  max_hueco_dias: int = MAX_HUECO_DIAS) -> dict:
    """Los puntos de la serie que SE PUEDEN usar, partidos donde hay huecos.

    `aceptar` es el nivel de exigencia:
      · ACEPTA_LINEA (default) — lo que ENTRA a la serie dibujada: base de mercado
        MÁS las fotos intradía. ⚠️ NO es lo mismo que base de mercado: los puntos
        intradía vienen con `apto=False` y no pueden ser pico ni denominador. Un
        consumidor que asuma "lo que me devolvieron ya es base de mercado" se
        equivoca — para eso está el flag por punto.
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
    # Por SERIE, no fila por fila: la cadencia diaria es lo único que distingue una
    # foto vieja del cron de una del browser, y eso no se ve en una fila sola.
    clases = clasificar_serie(filas, primera_pos)
    _nd = _aportado_por_punto(conn, uid, filas)
    puntos, contable, conteo = [], [], {c: 0 for c in CLASES}
    for r, c in zip(filas, clases):
        conteo[c] += 1
        d = str(r["date"])[:10]
        if c in aceptar:
            puntos.append({
                "date": d, "value": float(r["total_value"]),
                "net_deposited": _nd(r),
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
                   aceptar: tuple = ACEPTA_LINEA,
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
        # ⚠️ TODAS las claves, también las nuevas. Ya pasó una vez con
        # `drawdown_maximo_fecha`: un consumidor que gatea por `serie_partida` o
        # `tramos_medidos` recibía undefined y no gateaba nada. El estado vacío es
        # justamente el que más se lee mal, así que la forma no puede cambiar.
        return {**s, "curva": [], "twr": None, "cagr": None,
                "drawdown_actual": None, "drawdown_maximo": None,
                "drawdown_maximo_fecha": None, "drawdown_maximo_pico": None,
                "tramos_medidos": 0, "tramos_detalle": [], "serie_partida": False,
                "ventana_desde": None, "ventana_hasta": None}

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
    tramos_info = []       # {desde, hasta, twr, dd_max, dd_actual, legs} por tramo
    idx_ultimo_tramo = 1.0

    for tramo in s["tramos"]:
        idx = 1.0
        legs_t = 0
        dd_actual_t = None
        pico = None
        pico_fecha = None
        dd_max_t, dd_max_fecha_t, dd_max_pico_t = 0.0, None, None
        ancla = None       # último punto APTO: el único que puede ser denominador
        for i, p in enumerate(tramo):
            # ⚠️ UN PUNTO NO-APTO NO TOCA EL ÍNDICE, NI COMO v0 NI COMO v1.
            #
            # Antes sólo se le negaba ser DENOMINADOR (v0). Pero la pata que ENTRABA
            # a la foto intradía sí se encadenaba, y eso mueve el índice para
            # siempre: cuatro cierres planos en 10.000 con una foto del browser de
            # 15.000 en el medio devolvían twr=+50%. Y con flujos el encadenado
            # dejaba de telescopiar — el mismo mes plano daba +3,45% o −3,41% según
            # de qué lado de la foto cayera el depósito.
            #
            # La cadena avanza de punto APTO a punto APTO, salteando lo que no lo
            # es. El no-apto se dibuja (sostiene la línea, que es para lo que entró)
            # arrastrando el índice vigente, sin retorno propio.
            if not p["apto"]:
                ret = None
            elif ancla is None:
                ret = None                       # arranque medible del tramo
            else:
                flow = p["net_deposited"] - ancla["net_deposited"]
                ret = dietz(ancla["value"], p["value"], flow)
            if p["apto"]:
                ancla = p
            if ret is not None:
                idx *= (1.0 + ret)
                legs_t += 1
            punto = {"date": p["date"], "index": round(idx, 6),
                     "value": p["value"], "clase": p["clase"],
                     "apto": p["apto"], "ret": ret,
                     # A qué TRAMO pertenece. Sin esto el punto sale con el índice
                     # reiniciado a 1,0 y sin ninguna marca, y el chart lo dibuja
                     # como continuación: la línea "se recupera" a breakeven
                     # mientras la cartera iba de 8.000 a 6.000. El hueco lo
                     # rellenaba el reinicio del índice en vez de una interpolación,
                     # que es el mismo crimen con otra cara.
                     "tramo": len(tramos_info),
                     "arranque_tramo": i == 0,
                     # `estimado`: este punto se dibuja pero el índice no avanzó en
                     # él. Es lo que el consumidor necesita para no leerlo como un
                     # retorno.
                     "estimado": (ret is None and i > 0) or (not p["apto"])}
            if p["apto"]:
                if pico is None or idx > pico:
                    pico, pico_fecha = idx, p["date"]
                dd = (idx / pico) - 1.0 if pico and pico > 0 else 0.0
                dd_actual_t = dd
                if dd < dd_max_t:
                    dd_max_t, dd_max_fecha_t, dd_max_pico_t = dd, p["date"], pico_fecha
                punto["drawdown"] = round(dd, 6)
            curva.append(punto)
        tramos_info.append({
            "desde": tramo[0]["date"], "hasta": tramo[-1]["date"],
            "legs": legs_t, "twr": (idx - 1.0) if legs_t > 0 else None,
            "drawdown_maximo": round(dd_max_t, 6) if legs_t > 0 else None,
            # ⚠️ POR TRAMO, no "el último que vi". `dd_actual` era una sola
            # variable que se pisaba en cada punto apto de CUALQUIER tramo: con un
            # punto suelto al final (hueco > max_hueco_dias), el último valor
            # escrito era el de ese punto — cuyo índice arranca en 1,0 — y el
            # drawdown daba 0,0% con el usuario 36% abajo de su pico. Misma
            # familia que el bug que este trabajo vino a cerrar, introducida por
            # el fix de la serie partida.
            "drawdown_actual": round(dd_actual_t, 6) if (legs_t > 0 and dd_actual_t is not None) else None,
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
    # ⚠️ CUALQUIER hueco parte la serie, tenga o no legs el otro lado.
    # Contar sólo los tramos CON legs dejaba invisible al tramo huérfano de UN
    # punto: `partida` quedaba False, `motivo` None, y con eso el cierre live
    # componía por encima del hueco (devolvía +32% donde punta a punta era −34%)
    # y `medido_hasta` se estiraba hasta el otro lado, con lo cual el guard del
    # año daba por cubierto un período que sólo se midió dos meses.
    partida = len(s["tramos"]) > 1
    publicable = (len(con_legs) == 1 and not partida)
    # La ventana que el número REALMENTE cubre. `medido_desde`/`medido_hasta` de
    # `serie_medible` describen TODOS los puntos aptos; el TWR sólo cubre el tramo
    # publicado. Quien tenga que probar cobertura (reporting/builder.py) debe
    # mirar esto, no aquéllos.
    _tp = con_legs[0] if publicable else None
    ventana_desde = _tp["desde"] if _tp else None
    ventana_hasta = _tp["hasta"] if _tp else None

    if publicable:
        _t = con_legs[0]
        idx = 1.0 + _t["twr"]
        pico = max(1.0, idx)
        dd_max = _t["drawdown_maximo"]
        dd_max_fecha = _t["drawdown_maximo_fecha"]
        dd_max_pico_fecha = _t["drawdown_maximo_pico"]
        dd_actual = _t["drawdown_actual"]
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

    # El valor live cierra la curva SOLO si la serie es UN tramo continuo y su
    # último punto es base de mercado. Antes `ultimo_apto` se buscaba sobre
    # `s["puntos"]` ENTERO: con un punto huérfano del otro lado del hueco, la pata
    # live se componía encima del índice del tramo 1 y el hueco desaparecía.
    ultimo_apto = None
    if publicable:
        ultimo_apto = next((p for p in reversed(s["tramos"][0]) if p["apto"]), None)
    if (publicable and valor_live and valor_live > 0
            and ultimo_apto is not None and curva and s["puntos"][-1]["apto"]):
        # ⚠️ EL FLUJO NO ES CERO. Todo lo que entró o salió DESPUÉS del último
        # snapshot medido —el depósito de hoy, antes de que el cron nocturno
        # escriba la foto— se computaba entero como rendimiento: un usuario con el
        # mercado plano que depositaba US$20.000 leía "+20,00%" al lado de "US$0"
        # de P&L. Se pregunta a la SSoT canónica, la misma que usa `_flujo`.
        _flujo_live = 0.0
        try:
            from snapshots_job import compute_net_deposited_db
            _flujo_live = (compute_net_deposited_db(conn, uid)
                           - float(ultimo_apto["net_deposited"] or 0))
        except Exception:
            log.exception("flujo live uid=%s", uid)
            _flujo_live = 0.0
        r = dietz(ultimo_apto["value"], float(valor_live), _flujo_live)
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

    # El CAGR se anualiza sobre la ventana QUE EL ÍNDICE MIDIÓ, no sobre las
    # fechas extremas de la curva. Tomándolas de `curva[0]`/`curva[-1]` —que
    # pueden ser tramos huérfanos— se publicaba −16,32% anual para una medición
    # de 28 días, esquivando el propio piso de medio año de dos líneas más abajo.
    cagr = None
    if publicable and legs > 0 and idx > 0 and ventana_desde:
        _c1 = ventana_hasta
        if curva and curva[-1]["date"] == "hoy":
            _c1 = _hoy_art()
        años = _dias(ventana_desde, _c1) / 365.25
        if años >= 0.5:                # bajo medio año, anualizar es propaganda
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
        # La ventana que el TWR publicado cubre de verdad (None si no se publica).
        "ventana_desde": ventana_desde,
        "ventana_hasta": ventana_hasta,
        "motivo": _motivo,
        "motivo_texto": (MOTIVO_TEXTO.get(_motivo) if _motivo else None),
        "drawdown_actual": (round(dd_actual, 6) if dd_actual is not None else None),
        "drawdown_maximo": (round(dd_max, 6) if dd_max is not None else None),
        "drawdown_maximo_fecha": dd_max_fecha,
        "drawdown_maximo_pico": dd_max_pico_fecha,
        "cagr": cagr,
    }
