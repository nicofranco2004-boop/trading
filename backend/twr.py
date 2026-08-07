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
