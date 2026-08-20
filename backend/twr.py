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
# columna, que nunca la van a tener (source NULL).
#
# FALLA CERRADA: un `source` que NO esté acá es, por definición, un emisor que
# este módulo no conoce — y la heurística lo ascendería a MEDICION con sólo
# tener holdings_json. Ésa es exactamente la puerta por la que entraría un
# borde RECONSTRUIDO (source='reconstruido') a la cadena publicada, sin que
# nadie lo decida. Un emisor nuevo tiene que declararse acá a mano.
# Verificado (2026-08-20): los únicos tres writers de snapshots.source en
# producción escriben 'cron' (snapshots_job.py:769), 'browser' (main.py:4831)
# e 'import' (persister.py:1290) — las tres claves de abajo. Las filas viejas
# tienen NULL y siguen cayendo a la heurística.
_POR_SOURCE = {"cron": MEDICION, "browser": INTRADIA, "import": SINTETICO_COSTO}


def clasificar_fila(row, tenia_posiciones: bool) -> str:
    """Clasifica UN snapshot. `tenia_posiciones` responde si esa persona tenía
    algo no-cash para valuar: sin eso, un holdings_json vacío es lo correcto y
    no una señal de que la fila sea mala."""
    src = row["source"] if "source" in row.keys() else None
    if src is not None:
        return _POR_SOURCE.get(src, INDETERMINADO)
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


def _dietz_con_peso(v0: float, v1: float, flow: float, peso: float):
    """El mismo primitivo con el peso del flujo como parámetro. Existe SOLO para
    la guarda de sensibilidad (G8): si mover el peso entre 0,25 y 0,75 cambia el
    retorno más que un pelo, el número depende de CUÁNDO entró la plata — y eso
    es justo lo que el agente va a estar deduciendo. Nadie más debe usar esto:
    el retorno publicado sale siempre de `dietz`."""
    denom = v0 + peso * flow
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


def _flag(nombre: str) -> bool:
    """Lee un interruptor de seguridad. ALLOWLIST DE ENCENDIDO, no lista de
    apagado: cualquier valor que no sea explícitamente "prendido" queda
    APAGADO, typo incluido.

    La primera versión hacía `not in ("", "0", "false", "no")`, así que
    `RECONSTRUCTOR_APLICAR="False"` (con mayúscula) o `"off"` PRENDÍAN la vía de
    escritura. Y eso pega justo en el plan de rollback: el docstring de acá
    abajo dice que la vuelta atrás es "apagar una env var" — pero editar el
    valor a `False` en Railway, en vez de borrar la variable, la dejaba
    prendida mientras el operador creía que la había apagado.

    Es además el idioma del resto de la casa (mantenimiento.py compara
    == "1" / == "0"; ALLOW_REGISTRATION usa .lower() == "true"): éste era el
    outlier.
    """
    import os
    return (os.environ.get(nombre, "") or "").strip().lower() in (
        "1", "true", "yes", "si", "sí", "on")


def _aplicar_resoluciones() -> bool:
    """El interruptor de la vía de escritura. APAGADO por default, y no es
    redundante con la columna `aplicado`: sin él, la primera carga de la
    pantalla sella los meses con el flujo YA corregido y esas filas quedan
    como REVISIÓN 1 — la que el asesor va a leer como "el número original".
    Con el interruptor, "el agente resolvió" y "la resolución entró al número"
    son dos actos separados."""
    return _flag("RECONSTRUCTOR_APLICAR")


def _ajuste_resoluciones(conn, uid: int, desde: str, hasta: str,
                         aplicar: bool = None) -> float:
    """Cuánto de lo que la SSoT cuenta como flujo NO es flujo, según lo ya
    resuelto y aprobado. Un traslado interno movió el saldo pero no es plata
    nueva del cliente: se le resta al aporte neto del tramo.

    Ventana (desde, hasta] — misma convención que los bordes del tramo: el
    movimiento del día del borde inicial pertenece al tramo anterior.
    Best-effort: si la tabla todavía no existe, el TWR sigue andando igual.

    `aplicar` fuerza la decisión para ESTA llamada (None = leer la env). Existe
    para el contrafáctico del diagnóstico: la primera versión prendía la env
    var, calculaba y la volvía a apagar — y `os.environ` es estado GLOBAL del
    proceso, así que cualquier request concurrente (los endpoints sync corren en
    el threadpool) veía el interruptor prendido durante esa ventana y se llevaba
    el número corregido sin que nadie lo hubiera habilitado. Explícito por
    parámetro, no ambiente.
    """
    if not (_aplicar_resoluciones() if aplicar is None else aplicar):
        return 0.0
    try:
        r = conn.execute(
            """SELECT COALESCE(SUM(monto_usd), 0) a FROM flujo_resoluciones f
                WHERE f.user_id = ? AND f.aplicado = 1 AND f.revocado_at IS NULL
                  AND f.naturaleza = 'traslado_interno'
                  AND f.fecha > ? AND f.fecha <= ?
                  AND f.revision = (SELECT MAX(f2.revision) FROM flujo_resoluciones f2
                                     WHERE f2.user_id = f.user_id
                                       AND f2.scope_tipo = f.scope_tipo
                                       AND f2.scope_id = f.scope_id)""",
            (uid, desde, hasta)).fetchone()
        return float(r["a"] or 0)
    except Exception:
        log.exception("[twr] _ajuste_resoluciones falló (no fatal)")
        return 0.0


def _flujo(conn, uid: int, desde: str, hasta: str, aplicar: bool = None) -> float:
    """Aportes netos entre dos fechas. Sale de la SSoT canónica de la app
    (`compute_net_deposited_db`), no de una cuenta propia — si el TWR usara su
    propia definición de flujo, discutiría con el resto de las pantallas.

    ⭐ ESTE ES EL ÚNICO LUGAR de toda la app donde una resolución del agente
    toca un número. Si algún día hay un segundo, la vuelta atrás deja de ser
    apagar una env var.
    """
    from snapshots_job import compute_net_deposited_db
    base = (compute_net_deposited_db(conn, uid, as_of_date=hasta)
            - compute_net_deposited_db(conn, uid, as_of_date=desde))
    return base - _ajuste_resoluciones(conn, uid, desde, hasta, aplicar)


def tramos(conn, uid: int, hasta_mes: str = None, aplicar: bool = None) -> list:
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
        flow = _flujo(conn, uid, b0["date"], b1["date"], aplicar)
        r = dietz(v0, v1, flow)
        if r is None:
            # NO desaparecer en silencio. Antes acá había un `continue` pelado:
            # el mes se esfumaba del historial sin dejar rastro y la cadena se
            # cerraba SOBRE el agujero, o sea que `meses` contaba 3 sobre un
            # span de 4 y el número se publicaba igual. "Nunca saltear un mes en
            # silencio" es regla del diseño; el tramo sale marcado y `twr_de`
            # decide qué hacer con él.
            out.append({
                "month": mes, "period_start": b0["date"], "period_end": b1["date"],
                "v0_usd": v0, "v1_usd": v1, "flow_usd": flow, "ret": 0.0,
                "quality": "no_medible",
                "snap_id_start": b0["id"], "snap_id_end": b1["id"],
                "fx_basis": "mep_medio",
            })
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


# Los campos cuyo cambio obliga a una revisión nueva. `ret` HAY que incluirlo
# aunque hoy sea función pura de v0/v1/flow: deja de serlo el día que el método
# cambie con los mismos inputs (un flujo deducido por el agente), y ese cambio
# no generaría revisión — el asesor vería un número distinto sin que la fila
# diga que cambió.
_CAMPOS_SELLO = ("period_start", "period_end", "v0_usd", "v1_usd", "flow_usd",
                 "ret", "quality", "metodo", "flow_source")

# Cuánto puede moverse el retorno al correr el Dietz con el flujo pesado 0,25 /
# 0,5 / 0,75 antes de considerar que el número depende de CUÁNDO entró la plata.
# 2 puntos porcentuales de spread: por encima de eso, deducir mal la fecha (o la
# naturaleza) de un flujo mueve el resultado de forma visible.
SENSIBILIDAD_MAX = 0.02

# Interruptor. Arranca APAGADO a propósito: las guardas registran en
# `guardas_json` qué habrían rechazado, sin bloquear nada, y recién cuando se
# midió cuántos meses reales tumbarían se prenden. Prender una guarda a ciegas
# sobre 40.000 snapshots es cómo se rompe una pantalla que hoy anda.
def _guardas_activas() -> bool:
    return _flag("TWR_GUARDAS")


def verificar_tramo(conn, uid: int, t: dict, prev_mes: dict = None) -> dict:
    """Las ocho guardas de runtime, corridas ANTES de sellar.

    Las 12 invariantes de la suite son tests unitarios sobre datos sintéticos:
    prueban que el motor es correcto, no que ESTA fila lo sea. Estas guardas son
    su sombra sobre datos reales — es la diferencia entre "el motor está bien" y
    "este mes se puede publicar".

    Devuelve {ok: bool, fallas: [codigo], detalle: {...}}. No lanza.
    """
    f, det = [], {}
    v0, v1, flow, ret = (float(t["v0_usd"]), float(t["v1_usd"]),
                         float(t["flow_usd"]), float(t["ret"]))

    # G1 — IDENTIDAD. Sin flujo relevante, el Dietz TIENE que dar v1/v0 − 1.
    # Es la invariante más dura que existe y la más barata de chequear.
    if abs(flow) < 0.005 * abs(v0 or 1):
        esperado = (v1 / v0 - 1.0) if v0 else None
        if esperado is not None and abs(ret - esperado) > 1e-9:
            f.append("G1_identidad")
            det["G1"] = {"ret": ret, "esperado": esperado}

    # G2 — RE-DERIVAR. El `ret` guardado tiene que salir del primitivo, no de
    # otro lado. Atrapa que alguien haya escrito la fila a mano.
    re_ret = dietz(v0, v1, flow)
    if re_ret is None or abs(ret - re_ret) > 1e-9:
        if t.get("quality") != "no_medible":
            f.append("G2_no_rederivable")
            det["G2"] = {"ret": ret, "rederivado": re_ret}

    # G3 — DOMINIO. Piso de −100% y denominador positivo.
    # La excepción de `no_medible` NO es un caso especial: el denominador <= 0
    # es LA DEFINICIÓN de ese estado. Sin ella, G3 rechazaba el 100% de los
    # meses no medibles (verificado sobre 68 combinaciones) y, peor, arrastraba
    # por G5 a todos los meses SANOS que venían después. La exención ya estaba
    # pensada en G2 y no se había propagado acá.
    if t.get("quality") != "no_medible":
        if ret < -1.0 or (v0 + 0.5 * flow) <= 0:
            f.append("G3_dominio")
            det["G3"] = {"ret": ret, "denom": v0 + 0.5 * flow}

    # G4 — MES CERRADO. `tramos()` ya filtra, pero sellar confiaba ciegamente en
    # ese filtro: si alguien llama sellar() con otro hasta_mes, sella el mes en
    # curso y lo congela a media rueda.
    if t["month"] >= _hoy_art()[:7]:
        f.append("G4_mes_en_curso")
        det["G4"] = {"month": t["month"], "hoy": _hoy_art()}

    # G5 — CONTIGÜIDAD. El borde inicial de este mes tiene que ser el borde
    # final del mes sellado anterior. Si no, la cadena salta un hueco y el
    # producto multiplica tramos que no se tocan.
    if prev_mes is not None and prev_mes["period_end"] != t["period_start"]:
        f.append("G5_no_contiguo")
        det["G5"] = {"anterior_termina": prev_mes["period_end"],
                     "este_empieza": t["period_start"]}

    # G6 — LOS DOS BORDES SON MEDICIÓN. La fila se re-lee de `snapshots` por su
    # id: es la guarda que impide que un borde RECONSTRUIDO entre a la cadena
    # publicada. Es la contraparte de runtime del fail-closed de clasificar_fila.
    con_pos = uid in _usuarios_con_posiciones(conn, [uid])
    for lado, sid in (("v0", t.get("snap_id_start")), ("v1", t.get("snap_id_end"))):
        if not sid:
            continue
        row = conn.execute(
            "SELECT date, total_value, fx_to_usd_blue, holdings_json, source "
            "FROM snapshots WHERE id=?", (sid,)).fetchone()
        if row is None or clasificar_fila(row, con_pos) != MEDICION:
            f.append(f"G6_borde_{lado}_no_es_medicion")
            det[f"G6_{lado}"] = {"snap_id": sid,
                                 "clase": clasificar_fila(row, con_pos) if row else "no_existe"}

    # G7 — MISMA BASE DE FX EN LOS DOS BORDES. Encadenar un borde valuado al MEP
    # medio con otro a la punta de venta fabrica el spread (~0,7%) como retorno,
    # y no se cancela: queda como nivel permanente.
    b0, b1 = t.get("fx_basis_v0"), t.get("fx_basis_v1")
    if b0 and b1 and b0 != b1 and t.get("quality") == "ok":
        f.append("G7_fx_mixto")
        det["G7"] = {"v0": b0, "v1": b1}

    # G8 — SENSIBILIDAD AL FLUJO. No es una falla: es una ETIQUETA. Si mover el
    # peso del flujo cambia mucho el retorno, este mes depende de cuándo entró
    # la plata — o sea que es donde una deducción equivocada del agente más
    # duele. Después sirve para priorizar dónde gastar el modelo.
    rs = [x for x in (_dietz_con_peso(v0, v1, flow, p) for p in (0.25, 0.5, 0.75))
          if x is not None]
    if len(rs) == 3:
        spread = max(rs) - min(rs)
        det["G8"] = {"spread": spread}
        if spread > SENSIBILIDAD_MAX:
            det["G8"]["sensible"] = True

    return {"ok": not f, "fallas": f, "detalle": det}


def sellar(conn, uid: int, hasta_mes: str = None) -> dict:
    """Sella los meses cerrados. Idempotente: recalcular no cambia nada si el
    input no cambió. Si SÍ cambió (un import reescribió la historia, un deploy
    corrió el hook que recalcula el aportado hacia atrás), se escribe
    revision+1 — nunca se pisa la revisión vieja. Que la historia haya cambiado
    es justamente lo que el asesor tiene que poder ver."""
    import json as _json
    nuevos = revisados = rechazados = 0
    motivos = {}
    activas = _guardas_activas()
    prev_mes = None
    for t in tramos(conn, uid, hasta_mes):
        t.setdefault("metodo", "medido")
        t.setdefault("flow_source", "ledger")

        # Las guardas corren SIEMPRE. Con TWR_GUARDAS=0 sólo registran qué
        # habrían rechazado (modo sombra): así se mide el costo real antes de
        # prenderlas, en vez de descubrirlo tumbando una pantalla que anda.
        v = verificar_tramo(conn, uid, t, prev_mes)
        for cod in v["fallas"]:
            motivos[cod] = motivos.get(cod, 0) + 1
        # El ancla de contigüidad avanza SIEMPRE, se haya sellado el mes o no.
        # Antes se actualizaba después del `continue`, así que un mes rechazado
        # dejaba a `prev_mes` en el mes anterior y G5 tumbaba al siguiente por
        # "no contiguo" — y al siguiente, y al siguiente. Un solo agujero
        # congelaba el sellado de esa cuenta PARA SIEMPRE (medido: 4 meses
        # sellados pasaban a 1, y un mes nuevo e impecable ya nunca entraba,
        # porque la cascada se re-corre entera en cada llamada).
        prev_mes = t
        if not v["ok"] and activas:
            rechazados += 1
            log.warning("[twr] uid=%s mes=%s RECHAZADO por %s", uid, t["month"], v["fallas"])
            continue

        prev = conn.execute(
            "SELECT * FROM twr_periods WHERE user_id=? AND month=? "
            "ORDER BY revision DESC LIMIT 1", (uid, t["month"])).fetchone()
        if prev is not None:
            claves = prev.keys()
            igual = all(
                c in claves and (
                    (abs(float(prev[c] or 0) - float(t[c] or 0)) < 0.005)
                    if isinstance(t.get(c), float) else prev[c] == t.get(c))
                for c in _CAMPOS_SELLO)
            # Si el input no cambió, no se toca NADA — y eso incluye a un mes
            # RETRACTADO: revivirlo en el próximo sellado haría que retractar no
            # sirviera para nada. Vuelve a publicarse sólo si los datos de
            # abajo cambiaron de verdad (ahí sí entra una revisión vigente).
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
                flow_usd, ret, quality, snap_id_start, snap_id_end, fx_basis,
                revision, estado, metodo, flow_source, fx_basis_v0, fx_basis_v1,
                guardas_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'vigente', ?,?,?,?,?)""",
            (uid, t["period_start"], t["period_end"], t["month"], t["v0_usd"],
             t["v1_usd"], t["flow_usd"], t["ret"], t["quality"],
             t["snap_id_start"], t["snap_id_end"], t["fx_basis"], rev,
             t["metodo"], t["flow_source"],
             t.get("fx_basis_v0"), t.get("fx_basis_v1"),
             _json.dumps(v, ensure_ascii=False)))
    return {"sellados": nuevos, "revisados": revisados,
            "rechazados": rechazados, "guardas_activas": activas,
            "motivos": motivos}


def retractar(conn, uid: int, mes: str, motivo: str, ref: str = None) -> bool:
    """Saca un mes de la cadena SIN pisar la fila que ya se publicó.

    Es un INSERT de `revision+1` con estado='retractado', nunca un UPDATE — la
    revisión vieja tiene que seguir siendo legible, porque alguien la vio y
    tomó una decisión con ella. Con `retract_ref` estampado, deshacer una
    corrida entera del agente es un loop de INSERTs.
    """
    prev = conn.execute(
        "SELECT * FROM twr_periods WHERE user_id=? AND month=? "
        "ORDER BY revision DESC LIMIT 1", (uid, mes)).fetchone()
    if prev is None:
        return False
    conn.execute(
        """INSERT INTO twr_periods
           (user_id, period_start, period_end, month, v0_usd, v1_usd, flow_usd,
            ret, quality, snap_id_start, snap_id_end, fx_basis, revision,
            estado, retract_reason, retract_ref, retracted_at, metodo, flow_source)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'retractado', ?,?, datetime('now'), ?,?)""",
        (uid, prev["period_start"], prev["period_end"], prev["month"],
         prev["v0_usd"], prev["v1_usd"], prev["flow_usd"], prev["ret"],
         prev["quality"], prev["snap_id_start"], prev["snap_id_end"],
         prev["fx_basis"], int(prev["revision"]) + 1, motivo, ref,
         (prev["metodo"] if "metodo" in prev.keys() else "medido"),
         (prev["flow_source"] if "flow_source" in prev.keys() else None)))
    return True


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

    def _campo(f, c, default=None):
        return f[c] if c in f.keys() else default

    # Al producto no entra lo que NO ES UNA MEDICIÓN.
    #
    # ⚠️ Acá me aparté del plan escrito, que decía "sólo quality='ok'". Con esa
    # regla, un cliente que DUPLICA su aporte (flujo > 50% de v0 → la marca
    # `flujo_sospechoso`) se quedaba sin número: el caso legítimo más común de
    # todos, y justo el que el Dietz resuelve bien. Blanquear el TWR ahí es peor
    # que publicarlo con su etiqueta — y lo cazó la invariante del depósito.
    #
    # La línea correcta no es "ok vs. no ok", es "¿esto es un retorno medido?":
    #   flujo_sospechoso → SÍ. El retorno es correcto; la marca dice "verificá
    #     que ese flujo sea plata de verdad y no un import que reescribió".
    #   plano            → SÍ, con su marca. Un mes quieto puede ser real.
    #   no_medible       → NO. No hubo denominador: su `ret` es un 0.0 que
    #     pusimos nosotros para no perder el mes. Multiplicarlo es inventar.
    aptos = [f for f in filas
             if _campo(f, "estado", "vigente") == "vigente"
             and f["quality"] != "no_medible"]
    # Por id: comparar filas de sqlite3.Row con `in` no hace lo que parece.
    ids_aptos = {f["id"] for f in aptos}
    excluidos = [f["month"] for f in filas if f["id"] not in ids_aptos]

    # Y tienen que ser CONTIGUOS: multiplicar salteando un agujero y presentarlo
    # como si cubriera todo el rango es la forma más silenciosa de mentir. Se
    # devuelve la racha contigua más larga, diciendo qué quedó afuera.
    mejor, actual = [], []
    for f in aptos:
        if actual and _campo(actual[-1], "period_end") != _campo(f, "period_start"):
            if len(actual) > len(mejor):
                mejor = actual
            actual = []
        actual.append(f)
    if len(actual) > len(mejor):
        mejor = actual

    if not mejor:
        return {"twr": None, "meses": 0, "motivo": "sin_meses_publicables",
                "meses_excluidos": excluidos}

    idx = 1.0
    for f in mejor:
        idx *= (1.0 + float(f["ret"]))

    interrumpida = len(mejor) < len(aptos)
    metodos = {}
    for f in mejor:
        k = _campo(f, "metodo", "medido") or "medido"
        metodos[k] = metodos.get(k, 0) + 1

    return {
        "twr": idx - 1.0,
        "meses": len(mejor),
        "desde": mejor[0]["month"],
        "hasta": mejor[-1]["month"],
        "meses_revisados": [f["month"] for f in mejor if int(f["revision"]) > 1],
        "meses_degradados": [f["month"] for f in filas if f["quality"] != "ok"],
        "meses_excluidos": excluidos,
        # Cuánto del número lo construyó una corrección es PARTE del número, no
        # una nota al pie: el día que el agente aporte tramos, esto lo dice.
        "metodo_mix": metodos,
        "motivo": "cadena_interrumpida" if interrumpida else None,
    }
