"""Builder de PeriodReports — funciones puras sobre la DB.

Punto de entrada: `build_period_report(conn, uid, period_type, period_key, broker_filter)`.

Reusa lógica existente del backend:
- monthly_entries (broker='global' o broker específico) → start/end value, flows, realized
- operations → drivers por activo, win rate, trades count
- snapshots → start/end value para semanas (cuando no hay monthly_entry)
- benchmarks (sp500, inflation) → vs S&P / vs inflación
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date as date_cls, datetime, timedelta
from typing import Optional, List, Tuple, Dict, Any

from realized_pnl import realized_usd_sql

log = logging.getLogger(__name__)

from .schema import (
    PeriodReport, PeriodMetrics, Insight, Highlight, AssetContribution,
    HoldingMover,
)


# ─── Período: parseo y bounds ────────────────────────────────────────────────

def parse_period_bounds(period_type: str, period_key: str) -> Tuple[str, str]:
    """Devuelve (start_date, end_date) ISO ('YYYY-MM-DD') inclusivos.

    Soporta:
    - 'day': period_key = 'YYYY-MM-DD'
    - 'week': period_key = 'YYYY-Wnn' (ISO week, lunes a domingo)
    - 'month': period_key = 'YYYY-MM'
    """
    if period_type == "day":
        y, m, d = (int(x) for x in period_key.split("-"))
        dt = date_cls(y, m, d)
        return dt.isoformat(), dt.isoformat()
    if period_type == "week":
        y_str, w_str = period_key.split("-W")
        y, w = int(y_str), int(w_str)
        # ISO week: lunes de la semana w del año y
        # date.fromisocalendar disponible desde Python 3.8
        monday = date_cls.fromisocalendar(y, w, 1)
        sunday = monday + timedelta(days=6)
        return monday.isoformat(), sunday.isoformat()
    if period_type == "month":
        y, m = (int(x) for x in period_key.split("-"))
        first = date_cls(y, m, 1)
        # Último día del mes
        if m == 12:
            next_m = date_cls(y + 1, 1, 1)
        else:
            next_m = date_cls(y, m + 1, 1)
        last = next_m - timedelta(days=1)
        return first.isoformat(), last.isoformat()
    if period_type == "year":
        y = int(period_key)
        return f"{y:04d}-01-01", f"{y:04d}-12-31"
    raise ValueError(f"period_type desconocido: {period_type}")


def period_label(period_type: str, period_key: str, period_start: str) -> str:
    """Label legible para el chip. Ej: 'Mayo 2026', 'Semana 19', 'Lun 13 may'."""
    MES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
           "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    DIA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    if period_type == "month":
        y, m = period_key.split("-")
        return f"{MES[int(m) - 1]} {y}"
    if period_type == "week":
        _, w = period_key.split("-W")
        return f"Semana {int(w)}"
    if period_type == "day":
        y, m, d = (int(x) for x in period_key.split("-"))
        dt = date_cls(y, m, d)
        return f"{DIA[dt.weekday()]} {dt.day} {MES[m - 1].lower()}"
    if period_type == "year":
        return f"Año {period_key}"
    return period_key


def is_period_current(period_type: str, period_start: str, period_end: str,
                     today: Optional[date_cls] = None) -> bool:
    # Usar UTC para consistencia con _iso_today() del endpoint principal.
    # Sin esto, servidores con TZ no-UTC pueden divergir del frontend cerca
    # de medianoche, marcando un período como "no current" cuando sí lo es.
    today = today or datetime.utcnow().date()
    start = date_cls.fromisoformat(period_start)
    end = date_cls.fromisoformat(period_end)
    return start <= today <= end


# ─── Queries primitives ──────────────────────────────────────────────────────

def _broker_clause(broker_filter: str) -> Tuple[str, tuple]:
    """SQL fragment para filtrar por broker. 'global' = sin filtro."""
    if broker_filter == "global":
        return "", ()
    return " AND broker = ?", (broker_filter,)


def _operations_clause(broker_filter: str) -> Tuple[str, tuple]:
    if broker_filter == "global":
        return "", ()
    return " AND broker = ?", (broker_filter,)


def fetch_operations_in_range(conn, uid: int, start: str, end: str,
                              broker_filter: str = "global") -> List[Dict[str, Any]]:
    """Operations cerradas (Venta, Dividendo, Interés, Futuros) en el rango."""
    br_sql, br_args = _operations_clause(broker_filter)
    # `pnl_usd` se convierte a USD real acá, en el SELECT: en Cupón/Amortización
    # la columna guarda el monto en moneda del broker. Como TODO el módulo lee
    # las ops por esta función, con normalizarlo en el origen quedan bien el
    # realized del período, el win/loss y el mejor/peor del reporte, sin repetir
    # la condición en cada uno. Ver backend/realized_pnl.py.
    rows = conn.execute(
        f"""SELECT id, date, broker, asset, op_type, quantity, entry_price,
                   exit_price, {realized_usd_sql()} AS pnl_usd, pnl_pct
              FROM operations
             WHERE user_id = ? AND date >= ? AND date <= ?{br_sql}
             ORDER BY date ASC, id ASC""",
        (uid, start, end, *br_args),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_snapshots_in_range(conn, uid: int, start: str, end: str) -> List[Dict[str, Any]]:
    """Snapshots del portfolio en el rango. Snapshot es global (no per-broker)."""
    rows = conn.execute(
        """SELECT date, total_value, total_invested, net_deposited
             FROM snapshots
            WHERE user_id = ? AND date >= ? AND date <= ?
            ORDER BY date ASC""",
        (uid, start, end),
    ).fetchall()
    return [dict(r) for r in rows]


def _tiene_columna(conn, tabla: str, col: str) -> bool:
    """¿La migración de esa columna ya corrió en esta base? Cacheado por conexión."""
    cache = getattr(conn, "_cols_cache", None)
    if cache is None:
        cache = {}
        try:
            conn._cols_cache = cache
        except AttributeError:
            pass
    if tabla not in cache:
        try:
            cache[tabla] = {r[1] for r in conn.execute(f"PRAGMA table_info({tabla})")}
        except Exception:
            return False
    return col in cache[tabla]


def _user_has_positions(conn, uid: int) -> bool:
    """¿Tiene (o tuvo) algo no-cash para valuar? `twr.clasificar_fila` lo necesita:
    en una cartera 100% cash el cron deja `holdings_json` NULL con razón, y esa
    fila SÍ es una medición válida."""
    return conn.execute(
        "SELECT 1 FROM positions WHERE user_id=? AND COALESCE(is_cash,0)=0 LIMIT 1",
        (uid,),
    ).fetchone() is not None


# Cuántas filas mirar hacia atrás buscando un borde medible. Un borde más viejo
# que `_BORDER_MAX_LAG_DAYS` ya no sirve, así que no hace falta escanear la serie
# entera: 90 ruedas cubren de sobra la ventana útil.
_BORDER_SCAN_LIMIT = 90
# Un cierre a más de 5 días del arranque del período mete movimiento de mercado
# ajeno al período adentro del delta. Mismo criterio que el guard de día/semana.
_BORDER_MAX_LAG_DAYS = 5


def fetch_snapshot_at_or_before(conn, uid: int, when: str,
                                mtm_only: bool = False,
                                accept: Optional[tuple] = None,
                                require_positive: bool = True) -> Optional[Dict[str, Any]]:
    """Último snapshot con date <= when. Útil para encontrar el "valor de
    arranque" de un período cuando no hay snapshot exacto en el primer día.

    Con `mtm_only=True` devuelve SOLO un cierre real a mercado (`twr.MEDICION`).
    Motivo: el período en curso cierra con `end` a mercado (live). Si el `start`
    sale de una foto intradía del browser o de una fila que el import fabricó al
    costo (`_backfill_snapshots_from_monthly` escribe `total_value = capital_final`,
    que es la cadena contable), la resta no mide el período — mide la brecha entre
    dos formas de medir, y la publica como si fuera la pérdida del mes.

    Es la misma regla que `twr.bordes_medibles`, y el criterio de clasificación es
    `twr.clasificar_fila` a propósito: si dos módulos deciden distinto qué fila es
    un cierre, uno de los dos está mal.

    `accept` afloja ese filtro para los callers que no definen el número principal
    de la pantalla. Un borde de PERÍODO se compara contra el valor de mercado de
    hoy y decide el "P&L del mes", así que exige `MEDICION`. Un chip de variación
    a 1/7/30 días sólo necesita descartar lo que se sabe FABRICADO
    (`SINTETICO_COSTO`) o de media rueda (`INTRADIA`): rechazar además las filas
    legacy `INDETERMINADO` (sin `source`, anteriores a la columna) le borraría el
    chip a usuarios cuyo snapshot es perfectamente válido.
    """
    if not mtm_only and accept is None:
        row = conn.execute(
            """SELECT date, total_value, total_invested, net_deposited
                 FROM snapshots
                WHERE user_id = ? AND date <= ?
                ORDER BY date DESC LIMIT 1""",
            (uid, when),
        ).fetchone()
        return dict(row) if row else None

    from twr import (clasificar_serie, primera_fecha_con_posiciones, MEDICION,
                     bases_de_serie, BASE_MERCADO, VALUADO_A_MERCADO)
    allowed = accept if accept is not None else (MEDICION,)
    # `mtm_coverage` es la columna más nueva. Pedirla a secas ata este lector a que
    # la migración de startup ya haya corrido — y un deploy donde el código llega
    # antes que su columna es exactamente cómo se cayó producción el 2026-08-02.
    # Sin la columna el clasificador degrada las fotos reconstruidas a contable,
    # que es el lado seguro del error.
    _cov = "mtm_coverage" if _tiene_columna(conn, "snapshots", "mtm_coverage") else "NULL AS mtm_coverage"
    # `base`/`apto` estampados (ronda 11). Misma defensa que `mtm_coverage`: si la
    # migración todavía no corrió, se piden como NULL y el clasificador deduce.
    _bse = "base" if _tiene_columna(conn, "snapshots", "base") else "NULL AS base"
    _apt = "apto" if _tiene_columna(conn, "snapshots", "apto") else "NULL AS apto"
    # ⚠️ `total_value > 0` TIENE SENTIDO EN LA APERTURA Y NO EN EL CIERRE.
    # Como borde de ARRANQUE, un 0 no sirve: es el denominador del período y
    # dividir por él no da un porcentaje. Pero como borde de CIERRE, una cartera
    # legítimamente vacía NO es "no hay medición": es una medición DE CERO.
    # El usuario que vendió todo tiene un cierre válido en 0 y se lo estábamos
    # salteando, y el guard seguía retrocediendo hasta encontrar una fila con
    # valor — hasta 57 días atrás.
    # Medido en la copia del 16/08: el uid 330 tiene sus últimas 6 filas
    # `source='cron'`, clase `medicion`, `total_value = 0,00` y
    # `net_deposited = 35.712,01` (vendió todo), y el lector saltaba a junio y
    # publicaba "+8,76%" entre el 25 y el 30 de junio como "variación del último
    # cierre". Son 160 usuarios cuya última fila medida quedaba descartada.
    _pos = " AND total_value > 0" if require_positive else ""
    rows = conn.execute(
        f"""SELECT date, total_value, total_invested, net_deposited,
                   fx_to_usd_blue, holdings_json, source, {_cov}, {_bse}, {_apt}
              FROM snapshots
             WHERE user_id = ? AND date <= ?{_pos}
             ORDER BY date DESC LIMIT ?""",
        (uid, when, _BORDER_SCAN_LIMIT),
    ).fetchall()
    # ⚠️ POR SERIE, igual que `twr.serie_medible`. Con `clasificar_fila` fila por
    # fila, los dos módulos decidían DISTINTO sobre la misma fila legacy: la
    # cadencia diaria —lo único que distingue una foto vieja del cron de una del
    # browser— no se ve mirando una fila sola. `serie_medible` la ascendía a
    # MEDICION y este lector la seguía viendo INTRADIA, con lo cual un usuario
    # anterior a julio-2026 no conseguía NINGÚN borde de período. Si dos módulos
    # deciden distinto qué fila es una medición, uno de los dos está mal.
    primera = primera_fecha_con_posiciones(conn, uid)
    clases = clasificar_serie(rows, primera, orden_desc=True)
    # ⚠️ LA CLASE NO ALCANZA — HACE FALTA LA BASE. Éste era EL bug original, vivo
    # en la pantalla del reclamo original después de nueve rondas: `c in allowed`
    # acepta cualquier fila de clase RECONSTRUIDO, incluida una cuya cobertura es
    # 0,05 — o sea una foto cuyo `total_value` ES EL COSTO. Con esa fila de borde de
    # apertura, Reportes publicaba (medido, jul-2026):
    #     HEADLINE "Mes difícil — -47.3%" · basis='mercado' · incomparable=False
    #     "En jul 2026 perdiste US$ 65.967 (-47.3%)..."
    # sobre una cartera cuya cadena contable se había movido +0,1%. El −47,3% era
    # la brecha entre las dos formas de medir, no el mes.
    #
    # ⚠️ EL GUARD ES ESTRECHO A PROPÓSITO, NO ES `es_apto`. Lo que se rechaza es la
    # fila cuya CLASE dice mercado y cuya BASE es costo — contabilidad con etiqueta
    # de mercado. Las clases que el caller aceptó EXPLÍCITAMENTE sabiendo que no son
    # mercado (INDETERMINADO en el chip de variación a 1/7/30 días, main.py:31707)
    # siguen bajo su criterio: para eso existe `accept`, y endurecerlas acá le
    # borraría el chip a los usuarios legacy — que es el error que este mismo
    # docstring advierte cuatro párrafos más arriba.
    bases = bases_de_serie(rows, clases)
    for r, c, b in zip(rows, clases, bases):
        if c in allowed and not (c in BASE_MERCADO and b != VALUADO_A_MERCADO):
            return dict(r)
    return None


def fetch_latest_measured_snapshot(conn, uid: int,
                                   accept: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
    """El último snapshot que puede servir de BORDE DE CIERRE.

    ⚠️ EL ESPEJO QUE FALTABA, Y ES EL HALLAZGO ESTRUCTURAL DE TODO ESTE TRABAJO.
    `fetch_snapshot_at_or_before` protege el borde de APERTURA, y once rondas lo
    fueron enchufando lector por lector con mucho cuidado. NINGUNA miró el borde de
    CIERRE — y la punta también puede ser una fila al costo: el día que el usuario
    importa, la foto que el import fabrica es la más nueva y gana cualquier
    `ORDER BY date DESC LIMIT 1`.

    Cuando eso pasa la resta sale INVERTIDA: en vez del −65% fantasma que todos
    fueron a buscar, publica un +96% fantasma. Mismo defecto, signo opuesto, y por
    eso sobrevivió — nadie va a auditar un número que da bien.

    Medido sobre la copia de producción del 16/08: 180 de 822 usuarios (22%) tienen
    la última fila al costo. De ésos, 178 no tienen NINGUNA medición, así que para
    ellos la respuesta correcta es None — no hay número — y el llamador tiene que
    saber mostrarlo como un vacío explicado y no como un 0.

    Delega en `fetch_snapshot_at_or_before` con una fecha tope que ninguna fila
    alcanza, a propósito: si el criterio de "esta fila es una medición" viviera
    escrito dos veces, sería exactamente el defecto que este trabajo vino a sacar.

    ⚠️ `require_positive=False` — y ésa es la ÚNICA diferencia legítima entre los
    dos bordes. Una cartera vacía no es "no hay medición": es una medición de cero.
    Ver el comentario en `fetch_snapshot_at_or_before` (el caso del uid 330, que
    vendió todo y publicaba la variación de dos días de junio como si fuera la del
    último cierre).
    """
    return fetch_snapshot_at_or_before(conn, uid, "9999-12-31",
                                       mtm_only=(accept is None), accept=accept,
                                       require_positive=False)


# Cuánto de la base del período puede venir de capital contable SIN medir antes
# de que el resultado deje de ser publicable. El error máximo que puede meter la
# cadena es `start_value` entero; si el período está dominado por dinero NUEVO
# (los flujos son hechos registrados, no estimaciones) el riesgo está acotado a
# esta fracción. Con 0 el guard se comería el onboarding: el primer mes de un
# usuario arranca en la cadena y su número es correcto igual.
_UNMEASURED_BASE_TOL = 0.10


def _basis_is_incomparable(start_is_mtm: bool, start_value: float,
                           deposits: float, withdrawals: float) -> bool:
    """¿La resta `end(mercado) − start` mide el período, o mide la brecha entre
    dos formas de medir?

    Incomparable cuando `start` NO salió de un cierre medido y además pesa lo
    suficiente como para torcer el resultado. En el caso que originó esto,
    start=201.119 contra 131 de aportes: el 99,9% de la base era contabilidad
    sin medir, y la resta publicó −63,37% con cero operaciones cerradas.
    """
    if start_is_mtm or start_value <= 0:
        return False
    base_total = start_value + max(0.0, deposits - withdrawals)
    if base_total <= 0:
        return True
    return (start_value / base_total) > _UNMEASURED_BASE_TOL


def _border_is_fresh(snap_date: Optional[str], period_start: str,
                     max_lag_days: int = _BORDER_MAX_LAG_DAYS) -> bool:
    """¿El cierre está lo bastante pegado al arranque del período para servirle
    de borde? Un cierre de hace 3 semanas mete 3 semanas de mercado ajeno."""
    if not snap_date:
        return False
    try:
        lag = (datetime.strptime(period_start[:10], "%Y-%m-%d")
               - datetime.strptime(snap_date[:10], "%Y-%m-%d")).days
    except (ValueError, TypeError):
        return False
    return 0 <= lag <= max_lag_days


def _ventana_cubre(medido_desde: Optional[str], medido_hasta: Optional[str],
                   period_start: str, period_end: str, es_actual: bool,
                   tol_dias: int = _BORDER_MAX_LAG_DAYS) -> bool:
    """¿La ventana efectivamente medida cubre el período que se va a publicar?

    Un % calculado sobre julio-a-hoy no puede presentarse como "el año": va al lado
    de un monto que sí es del año entero y el lector no tiene forma de saber que
    describen ventanas distintas.

    Para el período EN CURSO el cierre esperado es HOY, no el 31/12 — exigir el
    fin del año calendario apagaría el número para todo el mundo, todo el año.
    """
    if not medido_desde or not medido_hasta:
        return False
    try:
        _fmt = "%Y-%m-%d"
        d0 = datetime.strptime(str(medido_desde)[:10], _fmt)
        d1 = datetime.strptime(str(medido_hasta)[:10], _fmt)
        p0 = datetime.strptime(period_start[:10], _fmt)
        p1 = datetime.strptime(period_end[:10], _fmt)
    except (ValueError, TypeError):
        return False
    if es_actual:
        hoy = datetime.strptime(_hoy_iso(), _fmt)
        if hoy < p1:
            p1 = hoy
    # El arranque medido no puede empezar DESPUÉS del período (más allá de la
    # tolerancia), y el cierre medido no puede terminar ANTES.
    return ((d0 - p0).days <= tol_dias) and ((p1 - d1).days <= tol_dias)


def _fin_de_mes_iso(y: int, m: int) -> str:
    import calendar as _cal
    return f"{y:04d}-{m:02d}-{_cal.monthrange(y, m)[1]:02d}"


def _hoy_iso() -> str:
    return datetime.utcnow().date().isoformat()


def _dia_anterior(iso: str):
    """El día anterior a una fecha ISO. None si la fecha no parsea."""
    try:
        return (datetime.strptime(iso[:10], "%Y-%m-%d") - timedelta(days=1)).date().isoformat()
    except (ValueError, TypeError):
        return None


def bordes_mercado_periodo(conn, uid: int, period_start: str, period_end: str,
                           broker_filter: str):
    """Las dos puntas de un período CERRADO, medidas a mercado. None si no se puede.

    Por qué hace falta: para un mes cerrado, `start` y `end` salen de la MISMA fila
    de `monthly_entries` (builder.py:386-387), y `_repair_monthly_chain`
    (main.py:9316-9318) garantiza para todo mes cerrado
        capital_final = capital_inicio + deposits − withdrawals + pnl_realized
    con lo cual `end − start − flows` es, algebraicamente, `pnl_realized` y nada
    más. El número no sabe nada del mercado: una cuenta que vendió con ganancia y
    después se derrumbó a mercado igual publica un año positivo.

    Se exige que las DOS puntas sean base de mercado. Una sola no sirve: mezclar
    bases es exactamente lo que fabrica el fantasma. Y sólo aplica a 'global':
    los snapshots son por usuario, no por broker, así que con un filtro de broker
    activo esta pregunta no se puede responder y se sigue con la contabilidad.
    """
    if broker_filter != "global":
        return None
    # BORDE_PERIODO, no BASE_MERCADO: cerrar un período contra el valor de hoy es
    # la pregunta exigente. Una foto intradía sirve para sostener una serie, no
    # para ser la punta de una resta contra un live.
    from twr import BORDE_PERIODO as acepta

    # ⚠️ EL BORDE DE APERTURA VA ESTRICTAMENTE ANTES DEL PERÍODO.
    #
    # Con `<= period_start` y el cron sano, el borde elegido era la foto del
    # PROPIO día 1 — que ya tiene adentro el depósito de ese día. Y como
    # `deposits` seguía saliendo del MES CALENDARIO COMPLETO de monthly_entries,
    # el aporte se restaba dos veces. Medido en un mes plano con un depósito de
    # US$10.000 el 1 de mayo y cron diario completo:
    #     start 110.000 · end 110.000 · dep 10.000 → delta −US$10.000 / −8,7%
    # cuando lo real era 0. No hacía falta haber importado nada: le pegaba a todo
    # el padrón sano. El borde correcto es el CIERRE DEL PERÍODO ANTERIOR.
    _prev = _dia_anterior(period_start)
    if _prev is None:
        return None
    ini = fetch_snapshot_at_or_before(conn, uid, _prev, accept=acepta)
    if not ini or not (float(ini.get("total_value") or 0) > 0):
        return None
    # ⚠️ UN SOLO DÍA DE TOLERANCIA, no cinco.
    # Con 5, si al cron le faltaba UN día el borde retrocedía a antes de un
    # depósito que igual se cuenta entero como flujo del período. Medido: abril
    # plano en 100.000, depósito de 10.000 el 30/4, mayo plano en 110.000 con CERO
    # aportes → con el cron muriendo el 30/4 daba 0,00%, y muriendo el 29/4 daba
    # +10,00% inventado. El único parámetro que cambiaba era qué día se cortó el
    # cron, y los huecos del cron son el caso ESPERADO en Railway
    # (memoria del repo: `project_cron_infra`). Un mes cerrado no se autocura.
    # Sin borde se cae a la cadena contable, que en ese mismo caso da 0,00: caer a
    # contable es mejor que inventar.
    if not _border_is_fresh(ini.get("date"), period_start, 1):
        return None
    if str(ini.get("date"))[:10] >= period_start:
        return None                     # defensa: nunca dentro del período

    fin = fetch_snapshot_at_or_before(conn, uid, period_end, accept=acepta)
    if not fin or not (float(fin.get("total_value") or 0) > 0):
        return None
    # El cierre tiene que caer DENTRO del período y cerca del final: un cierre de
    # mitad de mes deja fuera media rueda de mercado.
    if not (period_start <= str(fin.get("date"))[:10] <= period_end):
        return None
    # Idem del lado del cierre, y por el mismo motivo: un cierre 5 días temprano
    # deja fuera el movimiento de mercado de esos días pero cuenta igual los
    # aportes del mes entero. Es la misma asimetría, con el signo dado vuelta.
    if not _border_is_fresh(fin.get("date"), period_end, 1):
        return None
    if str(fin.get("date"))[:10] <= str(ini.get("date"))[:10]:
        return None                     # sin dos bordes distintos no hay tramo

    # Los flujos tienen que ser los de la VENTANA ENTRE LOS DOS BORDES, no los del
    # mes calendario: si el cierre quedó rezagado (cron caído los últimos días),
    # los aportes posteriores al borde no ocurrieron dentro de lo medido. El
    # `net_deposited` estampado en cada foto es la fuente con granularidad diaria;
    # es el mismo criterio que ya usa la rama del mes en curso (builder.py:492-498).
    # ⚠️ ACÁ NO SE CALCULA NINGÚN FLUJO, Y ESO ES EL ARREGLO.
    #
    # Antes se restaban las dos estampas de `net_deposited`. Esa columna no es un
    # hecho del día: es una MEDICIÓN que el escritor hizo sobre `monthly_entries`
    # EN EL MOMENTO de escribir la fila. Un import reescribe `monthly_entries`
    # hacia atrás y NO re-estampa las fotos viejas, así que la resta medía cuánto
    # cambió la contabilidad entre dos momentos, no el flujo del período. Medido:
    # julio plano, cero aportes, un import el 16/7 → "−US$50.000 / −37,04%", y un
    # mes cerrado no se autocura nunca.
    #
    # El flujo correcto ya lo tiene el caller: los `deposits`/`withdrawals` del
    # propio período. Y son EXACTAMENTE la ventana, porque el borde de apertura es
    # el cierre del período ANTERIOR — de eso se encarga `_dia_anterior` arriba.
    # Alinear las puntas hace innecesario calcular el flujo, que es mejor que
    # calcularlo bien.
    return float(ini["total_value"]), float(fin["total_value"])


def fetch_monthly_entry(conn, uid: int, year: int, month: int,
                       broker_filter: str = "global") -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """SELECT capital_inicio, capital_final, deposits, withdrawals,
                  pnl_realized, pnl_unrealized
             FROM monthly_entries
            WHERE user_id = ? AND broker = ? AND year = ? AND month = ?""",
        (uid, broker_filter, year, month),
    ).fetchone()
    return dict(row) if row else None


def fetch_cum_deposits_until(conn, uid: int, end_date: str,
                            broker_filter: str = "global") -> float:
    """Σ(deposits − withdrawals) en monthly_entries hasta `end_date` (incl).

    Sirve como denominador para la métrica alternativa "% sobre aportado".

    Fase 3 (2026-05-30): delega en la SSoT `compute_net_deposited_db`.
    Mantenemos `include_baseline=False` para preservar la semántica
    histórica del endpoint /reportes (que nunca incluyó capital_inicio).
    """
    from snapshots_job import compute_net_deposited_db
    return compute_net_deposited_db(
        conn, uid,
        as_of_date=end_date,
        broker_filter=broker_filter,
        include_baseline=False,
    )


# ─── Benchmarks ──────────────────────────────────────────────────────────────

def benchmark_return_for_period(bench: Dict[str, Any], period_type: str,
                                period_start: str, period_end: str,
                                key: str) -> Optional[float]:
    """% del benchmark en el período. `key` ∈ {'sp500', 'inflation_ar'}.

    sp500 está keyed por YYYY-MM con cierre del mes. Para mes completo es directo.
    Para semana, devolvemos None (no podemos pro-ratear sin daily data).
    """
    if not bench or key not in bench:
        return None
    series = bench.get(key) or {}
    if period_type != "month":
        return None  # Phase 1: no soportamos benchmark sub-mensual
    start_mk = period_start[:7]
    end_mk = period_end[:7]
    if key == "sp500":
        # close del mes anterior vs close de este mes
        y, m = (int(x) for x in end_mk.split("-"))
        prev_y, prev_m = (y, m - 1) if m > 1 else (y - 1, 12)
        prev_mk = f"{prev_y:04d}-{prev_m:02d}"
        cur = series.get(end_mk)
        prev = series.get(prev_mk)
        if cur and prev and prev > 0:
            return ((cur / prev) - 1) * 100
        return None
    if key == "inflation_ar":
        # ya viene en % por mes
        v = series.get(end_mk)
        return float(v) if v is not None else None
    return None


# ─── Métricas core del período ───────────────────────────────────────────────

def _modified_dietz_pct(start_value: float, end_value: float, flows: float) -> Optional[float]:
    """Period return Modified Dietz.

    Devuelve None si el promedio invertido es <=0 (no se puede computar un %
    significativo — el frontend muestra "—"). NO clampa: si el portfolio cae
    -150%, devolvemos -150 (raro pero real para shorts/leverage).
    """
    avg = start_value + 0.5 * flows
    if avg <= 0:
        return None
    pnl = end_value - start_value - flows
    return (pnl / avg) * 100


def compute_metrics_for_period(
    conn, uid: int, period_type: str, period_start: str, period_end: str,
    broker_filter: str, bench: Optional[Dict[str, Any]],
    live_value: Optional[float] = None,
) -> Tuple[PeriodMetrics, List[Dict[str, Any]]]:
    """Computa métricas + devuelve operaciones del período (para drivers/highlights).

    Estrategia:
    - month: usa monthly_entries (canónico).
    - week/day: usa snapshots para start/end + operations para realized/trades.

    Para el período en curso, si hay liveValue, lo usamos como end_value.
    """
    ops = fetch_operations_in_range(conn, uid, period_start, period_end, broker_filter)
    realized = sum(float(o.get("pnl_usd") or 0) for o in ops)

    # Trades cerrados (Venta + Futuros), excluyendo dividendos/intereses/compras/conversiones
    def _is_trade(op):
        t = (op.get("op_type") or "").strip()
        if t in ("Compra", "Dividendo", "Interés"):
            return False
        if t.startswith("Conversión") or t.startswith("CONVERSION"):
            return False
        return True

    trade_ops = [o for o in ops if _is_trade(o) and o.get("pnl_usd") is not None]
    wins = [o for o in trade_ops if o["pnl_usd"] > 0]
    losses = [o for o in trade_ops if o["pnl_usd"] < 0]
    win_rate = (len(wins) / len(trade_ops) * 100) if trade_ops else None

    deposits = 0.0
    withdrawals = 0.0
    start_value = 0.0
    end_value = 0.0
    unrealized = 0.0
    year_twr_pct = None  # AUDIT B1: TWR anual por composición geométrica de meses
    dw_incomplete = False  # AUDIT B4/B10: día/semana sin base confiable → % None
    # AUDIT D-1: ¿las dos puntas de la resta miden lo mismo? El período en curso
    # cierra con `end` a MERCADO (live). Si `start` salió de la cadena contable
    # (costo) o de una fila que no es un cierre medido, `end − start` no es el
    # P&L del período: es la brecha entre dos reglas de medición, acumulada
    # durante toda la vida de la cuenta. Cuando eso pasa no publicamos NI el %
    # NI el monto — un número inventado con autoridad es peor que un "—".
    basis_incomparable = False
    _basis = "contable"     # en qué base quedaron las dos puntas
    _start_is_mtm = False   # start_value salió de un cierre real a mercado
    _live_month_unmeasured = False  # (año) el mes vivo no tiene borde medido

    if period_type == "month":
        y, m = (int(x) for x in period_start[:7].split("-"))
        me = fetch_monthly_entry(conn, uid, y, m, broker_filter)
        if me:
            start_value = float(me.get("capital_inicio") or 0)
            end_value = float(me.get("capital_final") or 0)
            deposits = float(me.get("deposits") or 0)
            withdrawals = float(me.get("withdrawals") or 0)
            unrealized = float(me.get("pnl_unrealized") or 0)
        # ⚠️ DOS PREGUNTAS DISTINTAS, Y ACÁ LAS DECIDÍA UN SOLO `and`.
        #
        #   ¿el período es el ACTUAL?   → un hecho del calendario. No depende de
        #                                 que tengamos con qué medirlo.
        #   ¿hay valor de CIERRE?       → un hecho de los datos.
        #
        # Mezcladas, un `live_value=None` hacía que el mes EN CURSO se tratara como
        # un mes CERRADO y se calculara con `capital_inicio`/`capital_final` de
        # `monthly_entries` — la cadena contable. Y eso no dejaba el número en
        # blanco: lo REEMPLAZABA por una afirmación falsa. Medido sobre la copia de
        # producción del 16/08, en los 196 usuarios con valor real y sin ningún
        # cierre medible:
        #     195 × "Mes sin grandes movimientos."   ← afirma que no pasó nada
        #       1 × "Mes mixto — +2,5%."             ← publica un %
        # cuando lo cierto es que no lo sabemos. El mes en curso sigue siendo el mes
        # en curso aunque no haya con qué medirlo, y ahí lo que corresponde es
        # decirlo (`basis_incomparable` → "Mes sin base para medir el rendimiento",
        # que el generador de headline evalúa PRIMERO, builder.py:1236).
        _period_is_current = is_period_current(period_type, period_start, period_end)
        month_is_current = _period_is_current and live_value is not None
        if month_is_current:
            end_value = float(live_value)
            # AUDIT C-3: sin fila del mes (el rollover lazy solo corre al visitar
            # /mensual) start quedaba 0 → "P&L del mes" = la cartera ENTERA sobre
            # "capital inicial de US$ 0". Heredamos el cierre del mes anterior.
            if not me:
                prev_row = conn.execute(
                    """SELECT capital_final FROM monthly_entries
                        WHERE user_id = ? AND broker = ?
                          AND (year < ? OR (year = ? AND month < ?))
                        ORDER BY year DESC, month DESC LIMIT 1""",
                    (uid, broker_filter, y, y, m),
                ).fetchone()
                if prev_row and float(prev_row["capital_final"] or 0) > 0:
                    start_value = float(prev_row["capital_final"])
            # AUDIT C-2 (patch pre-C1): el mes EN CURSO cierra con end MtM (live),
            # pero capital_inicio viene de la cadena monthly A COSTO → costo-vs-
            # mercado fabricaba TODO el unrealized histórico como "P&L del mes"
            # (el patrón del "-64,9% fantasma"). Start desde el snapshot MtM del
            # cierre anterior (solo global: los snapshots no se desagregan).
            # AUDIT D-1: el borde tiene que ser un cierre MEDIDO y estar pegado al
            # arranque del mes. Antes esta llamada aceptaba cualquier fila: la que
            # el import fabricó al costo entraba como si fuera mercado y el parche
            # C-2 quedaba sin efecto justo en las cuentas que más lo necesitaban.
            if broker_filter == "global":
                # ⚠️ `_dia_anterior`, igual que el período cerrado. Con
                # `<= period_start` el borde elegido era la foto del PROPIO día 1,
                # que ya tiene adentro el depósito de ese día, mientras `deposits`
                # seguía siendo el del mes calendario: el aporte se restaba dos
                # veces. Es el defecto que `bordes_mercado_periodo` documenta, y
                # había quedado vivo justo en la rama más mirada — la del mes en
                # curso. Medido: julio cierra 110.000, el 1/8 entra un aporte de
                # 10.000, la cartera queda plana en 120.000 → "Mes difícil −8,0%".
                _prev_d = _dia_anterior(period_start)
                _snap_prev = (fetch_snapshot_at_or_before(
                    conn, uid, _prev_d, mtm_only=True) if _prev_d else None)
                if (_snap_prev and float(_snap_prev.get("total_value") or 0) > 0
                        and _border_is_fresh(_snap_prev.get("date"), period_start)):
                    start_value = float(_snap_prev["total_value"])
                    _start_is_mtm = True
                    # Sin fila monthly, los flows del mes salen del net_deposited
                    # canónico (Δ vs el stamp del snapshot) — si no, un depósito
                    # intra-mes contaría como ganancia.
                    if not me:
                        from snapshots_job import compute_net_deposited_db
                        _end_nd = compute_net_deposited_db(
                            conn, uid, broker_filter='global', include_baseline=True)
                        _start_nd = float(_snap_prev.get("net_deposited") or 0)
                        deposits = max(0.0, _end_nd - _start_nd)
                        withdrawals = max(0.0, _start_nd - _end_nd)
            # AUDIT D-1: sin un cierre medido de borde, `start` quedó en la cadena
            # contable (capital_inicio / capital_final del mes anterior) y `end` es
            # mercado vivo. Ese par produjo "−63,37% / −US$127.486" con CERO
            # operaciones cerradas y un no-realizado de −US$2.233: la resta no era
            # la pérdida del mes, era la brecha costo-vs-mercado de toda la cuenta.
            # Con start_value <= 0 no hay mezcla posible (no hay capital previo al
            # costo) y el caso ya lo cubre el guard de abajo.
            if _basis_is_incomparable(_start_is_mtm, start_value, deposits, withdrawals):
                basis_incomparable = True
            # Sin NINGUNA base medible NI flows (usuario sin historia ni aportes
            # registrados): período incompleto (patrón B4/B10) — delta 0 honesto
            # en vez de "+toda la cartera (+0.0% sobre capital inicial US$ 0)".
            # ⚠️ SOLO sin flows: el primer mes de un usuario nuevo tiene
            # capital_inicio=0 CON deposits>0 — ahí start=0 es CORRECTO
            # (delta = end − deposits; Dietz maneja start=0 vía avg=0.5·flows).
            # Pisar start=end con flows vivos fabricaba delta = −deposits
            # (depositás 5.000, vale 5.200 → "−US$5.000, −100%") en pleno
            # onboarding. (Cazado por el review adversarial de F4.)
            if start_value <= 0 and end_value > 0 and (deposits - withdrawals) <= 0:
                dw_incomplete = True
                start_value = end_value
        elif _period_is_current:
            # MES EN CURSO SIN CIERRE MEDIDO. No es un mes cerrado y no se puede
            # tratar como tal: no hay con qué cerrarlo. Cae acá el usuario cuyas
            # únicas filas las fabricó el import — 178 de los 822 de producción no
            # tienen NINGUNA medición.
            #
            # Esto NO es una regresión de cobertura: el número que se deja de
            # publicar nunca midió nada. Lo que cambia es que ahora se dice, en vez
            # de dejar que la cadena contable conteste por su cuenta.
            #
            # ⚠️ SÓLO SI HAY ALGO QUE MEDIR. "No se puede medir" y "no hay nada"
            # son dos cosas distintas, y confundirlas le pone al usuario RECIÉN
            # REGISTRADO un "Mes sin base para medir el rendimiento" sobre una
            # cuenta vacía — le contesta una pregunta que no hizo. Además
            # `basis_incomparable` vuelve el mes RELEVANTE en la timeline
            # (`is_relevant`), así que sin este chequeo la cuenta vacía empezaba a
            # ocupar lugar en una pantalla donde antes, correctamente, no aparecía.
            # (Lo cazó `test_empty_user_returns_n_months_with_no_relevant`.)
            _hay_algo = bool(
                me or start_value or end_value or deposits or withdrawals or ops
                or conn.execute(
                    "SELECT 1 FROM snapshots WHERE user_id = ? LIMIT 1", (uid,)
                ).fetchone()
            )
            if _hay_algo:
                basis_incomparable = True
        else:
            # Mes CERRADO: si hay dos cierres medidos, el período se mide a
            # mercado. Si no, queda la contabilidad — igual que antes, sin
            # regresión, pero ahora ETIQUETADA como tal.
            _b = bordes_mercado_periodo(conn, uid, period_start, period_end, broker_filter)
            if _b:
                # Las dos puntas a mercado; los flujos siguen siendo los del
                # propio período (`deposits`/`withdrawals` de monthly_entries), que
                # es la MISMA ventana porque el borde de apertura es el cierre del
                # período anterior. Los brutos NO se tocan: son lo que la app
                # PUBLICA (MonthCard.jsx:223-224), cifras que el usuario contrasta
                # contra el resumen de su broker.
                start_value, end_value = _b
                _basis = "mercado"
                _start_is_mtm = True
    elif period_type == "year":
        # Sumamos los monthly_entries del año. start = capital_inicio del primer
        # mes con data; end = capital_final del último mes con data (o live
        # value si el año en curso). flows = suma de deposits/withdrawals.
        y = int(period_start[:4])
        rows = conn.execute(
            """SELECT month, capital_inicio, capital_final, deposits, withdrawals,
                       pnl_realized, pnl_unrealized
                 FROM monthly_entries
                WHERE user_id = ? AND broker = ? AND year = ?
                ORDER BY month ASC""",
            (uid, broker_filter, y),
        ).fetchall()
        if rows:
            start_value = float(rows[0]["capital_inicio"] or 0)
            end_value = float(rows[-1]["capital_final"] or 0)
            deposits = sum(float(r["deposits"] or 0) for r in rows)
            withdrawals = sum(float(r["withdrawals"] or 0) for r in rows)
            unrealized = float(rows[-1]["pnl_unrealized"] or 0)
        year_is_current = live_value is not None and is_period_current(period_type, period_start, period_end)
        if year_is_current:
            end_value = float(live_value)
            # AUDIT C-2 (patch pre-C1): end MtM (live) vs capital_inicio A COSTO
            # fabricaba el unrealized histórico como "P&L del año". Start desde el
            # snapshot MtM del cierre del año pasado (solo global).
            if broker_filter == "global":
                # `_dia_anterior`: el borde de apertura del año es el cierre del
                # 31/12 ANTERIOR. Con `<= period_start` agarraba la foto del propio
                # 1/1 —que ya tiene adentro el aporte de ese día— mientras
                # `deposits` seguía siendo el del año entero: el aporte se restaba
                # dos veces. Mismo defecto que ya se cerró en el período cerrado y
                # en el mes en curso; faltaba acá.
                _prev_y = _dia_anterior(period_start)
                _snap_y = (fetch_snapshot_at_or_before(conn, uid, _prev_y, mtm_only=True)
                           if _prev_y else None)
                if (_snap_y and float(_snap_y.get("total_value") or 0) > 0
                        and _border_is_fresh(_snap_y.get("date"), period_start)):
                    start_value = float(_snap_y["total_value"])
                    _start_is_mtm = True
            # AUDIT D-1: mismo cruce que el mes — sin cierre medido de borde, el
            # año resta cadena contra mercado.
            if _basis_is_incomparable(_start_is_mtm, start_value, deposits, withdrawals):
                basis_incomparable = True
        else:
            # Año CERRADO: mismas dos puntas medidas que pide el mes.
            _b = bordes_mercado_periodo(conn, uid, period_start, period_end, broker_filter)
            if _b:
                # Las dos puntas a mercado; los flujos siguen siendo los del
                # propio período (`deposits`/`withdrawals` de monthly_entries), que
                # es la MISMA ventana porque el borde de apertura es el cierre del
                # período anterior. Los brutos NO se tocan: son lo que la app
                # PUBLICA (MonthCard.jsx:223-224), cifras que el usuario contrasta
                # contra el resumen de su broker.
                start_value, end_value = _b
                _basis = "mercado"
                _start_is_mtm = True
        # El TWR del año, DESDE EL MISMO MOTOR que la sección Diagnóstico. Si los
        # dos números salieran de motores distintos volverían a contradecirse para
        # el mismo período — que es el defecto que este trabajo viene a cerrar.
        # `twr.curva_indexada` sólo encadena bordes en base de mercado; si no
        # alcanzan, devuelve None y abajo queda la composición contable de siempre.
        if broker_filter == "global":
            try:
                import twr as _twr
                # ⚠️ El borde de APERTURA del año cae ANTES de period_start (el
                # cierre del 31/12 anterior). Arrancar la ventana justo en
                # period_start lo dejaba afuera y el año se quedaba con un solo
                # punto → sin TWR, y volvía silenciosamente a la composición
                # contable. Se abre la ventana hacia atrás la misma tolerancia
                # que ya usa `_border_is_fresh` para aceptar un borde.
                # ⚠️ Abrir la ventana en `period_start − 5` no basta: `serie_medible`
                # toma TODOS los puntos que caen ahí y `curva_indexada` encadena
                # desde el más viejo, así que el % del año incorporaba los últimos
                # 4 días del año anterior. Con cron diario sano eso publicaba
                # −6,30% al lado de +US$20.315 de ganancia. El arranque tiene que
                # ser EXACTAMENTE el borde de cierre del período anterior — el
                # mismo que usa `bordes_mercado_periodo` para `delta_usd`, para
                # que el % y el monto describan la misma ventana.
                # ⚠️ Y EL BORDE TIENE QUE SER FRESCO. `fetch_snapshot_at_or_before`
                # camina hacia atrás hasta encontrar uno aceptable, así que cuando el
                # cierre del período anterior NO sirve —por ejemplo una foto
                # reconstruida mayormente al costo, que el guard de base rechaza— se
                # trae el anterior, que puede estar un mes antes. Medido: con el
                # cierre del 31/12 rechazado, el año 2026 arrancaba su TWR el 30/11
                # y publicaba "Año difícil — −26,4%" con delta_usd = US$0 y start ==
                # end: el porcentaje describía 13 meses y el monto 12. Es la misma
                # asimetría que `bordes_mercado_periodo` ya cierra con
                # `_border_is_fresh` 350 líneas más arriba; acá faltaba.
                _prev_dia = _dia_anterior(period_start)
                _snap_ini = (fetch_snapshot_at_or_before(
                    conn, uid, _prev_dia, accept=_twr.BORDE_PERIODO)
                    if _prev_dia else None)
                if _snap_ini is not None and not _border_is_fresh(
                        _snap_ini.get("date"), period_start, 1):
                    _snap_ini = None
                _desde = (str(_snap_ini["date"])[:10] if _snap_ini
                          else (datetime.strptime(period_start[:10], "%Y-%m-%d")
                                - timedelta(days=_BORDER_MAX_LAG_DAYS)).date().isoformat())
                _c = _twr.curva_indexada(
                    conn, uid, _desde, period_end,
                    valor_live=(float(live_value) if year_is_current and live_value else None))
                # ⚠️ EL TWR TIENE QUE CUBRIR EL PERÍODO QUE SE ESTÁ PUBLICANDO.
                #
                # Sin esta guarda, un usuario con mediciones sólo desde julio
                # recibía el +10,0% de julio-a-hoy junto al −US$7.000 del año
                # entero, los dos en el mismo hero (MonthCard.jsx:118 y :121), y
                # `basis_incomparable` no lo tapaba porque el año en curso ya
                # tenía su propio guard para otra cosa. El % y el monto tienen que
                # describir LA MISMA VENTANA o el % no se publica.
                # ⚠️ `ventana_desde/hasta`, NO `medido_desde/hasta`. Los segundos
                # son el primer y el último punto APTO de TODA la serie; el TWR
                # sólo cubre el tramo publicado. Con una foto medida suelta al
                # arranque del año —el último cierre del cron de diciembre antes
                # de que se cortara, forma común— el guard daba por cubierto el
                # año y publicaba el % de dos meses al lado del monto de doce.
                if (_c.get("twr") is not None
                        and _ventana_cubre(_c.get("ventana_desde"), _c.get("ventana_hasta"),
                                           period_start, period_end, year_is_current)):
                    year_twr_pct = round(_c["twr"] * 100, 2)
                    _basis = "mercado"
            except Exception:
                log.exception("year_twr desde twr.curva_indexada fallo uid=%s", uid)
        # AUDIT B1: el retorno del año = composición GEOMÉTRICA de los retornos
        # mensuales (TWR encadenado), no un Modified Dietz único anual. Así el
        # anual coincide con lo que sugieren los meses y no depende del timing
        # de los aportes. El último mes del año en curso usa live como cierre.
        #
        # ⚠️ CON AGUJEROS EN EL MEDIO LA COMPOSICIÓN NO SE PUBLICA. Si a
        # `monthly_entries` le faltan meses entre el primero y el último, la
        # composición los saltea — o sea los cuenta como +0% — y el % termina
        # describiendo una ventana MÁS CORTA que `delta_usd`, que sí va de punta
        # a punta. Los dos van juntos en el mismo hero (MonthCard.jsx:118 y :121).
        # Medido: un año con filas sólo en enero y en el mes en curso publicaba
        # "+8,11%" al lado de "−US$7.000". Sin composición confiable queda el
        # Modified Dietz único del año, que cubre exactamente la misma ventana que
        # el monto. (Este agujero es anterior a este trabajo: origin/main da el
        # mismo 8,11 en el mismo escenario.)
        # El fallback contable corre JUSTO cuando la serie medida está rota, así
        # que también tiene que probar cobertura: no alcanza con que los meses sean
        # contiguos, tienen que ALINEAR con el período. Si la primera fila es de
        # julio, la composición describe medio año y `delta_usd` el año entero.
        _meses_con_fila = sorted(int(r["month"]) for r in rows) if rows else []
        _hay_agujero = bool(_meses_con_fila) and (
            len(_meses_con_fila) != (_meses_con_fila[-1] - _meses_con_fila[0] + 1))
        _cubre_el_periodo = bool(_meses_con_fila) and _ventana_cubre(
            f"{y:04d}-{_meses_con_fila[0]:02d}-01",
            _fin_de_mes_iso(y, _meses_con_fila[-1]),
            period_start, period_end, year_is_current)
        if rows and not _hay_agujero and _cubre_el_periodo:
            comp = 1.0
            have_comp = False
            for i, r in enumerate(rows):
                ci = float(r["capital_inicio"] or 0)
                cf = float(r["capital_final"] or 0)
                if i == len(rows) - 1 and year_is_current:
                    cf = float(live_value)
                    # AUDIT C-2: el mes vivo componía ci A COSTO contra cf MtM →
                    # el Dietz de ese mes concentraba TODO el fantasma (×1.8 en el
                    # TWR anual). ci desde el snapshot MtM del cierre anterior.
                    # AUDIT D-1: y sólo si ese cierre es una MEDICIÓN pegada al
                    # arranque del mes. Si no lo es, el factor de ese mes es el
                    # fantasma entero — se saltea (factor 1) en vez de propagarlo
                    # al TWR del año, y el año queda marcado como incomparable.
                    _ci_is_mtm = False
                    if broker_filter == "global":
                        _ms = f"{y:04d}-{int(r['month']):02d}-01"
                        # Idem: el cierre del mes ANTERIOR, no la foto del día 1.
                        _msp = _dia_anterior(_ms)
                        _snap_m = (fetch_snapshot_at_or_before(conn, uid, _msp, mtm_only=True)
                                   if _msp else None)
                        if (_snap_m and float(_snap_m.get("total_value") or 0) > 0
                                and _border_is_fresh(_snap_m.get("date"), _ms)):
                            ci = float(_snap_m["total_value"])
                            _ci_is_mtm = True
                    # Variable LOCAL a propósito: el `continue` ya saca al mes
                    # vivo de la composición. Prender el flag del AÑO acá apagaba
                    # un año cuyo propio borde SÍ estaba medido — se perdía un
                    # delta_usd real punta a punta sólo porque el cron se cortó
                    # dentro del mes en curso.
                    if not _ci_is_mtm and ci > 0:
                        _live_month_unmeasured = True
                        continue
                mp = _modified_dietz_pct(ci, cf, float(r["deposits"] or 0) - float(r["withdrawals"] or 0))
                if mp is not None:
                    comp *= (1 + mp / 100.0)
                    have_comp = True
            # La composición mensual sale de monthly_entries: es CONTABLE. Si las
            # dos puntas del año ya quedaron en base de mercado, dejarla ganar
            # volvería a publicar lo realizado sobre costo (el "+3,6% anual" de
            # una cuenta derrumbada). Ahí manda el Dietz punta a punta de los
            # bordes medidos, que es `delta_pct_val`.
            if have_comp and year_twr_pct is None and _basis != "mercado":
                year_twr_pct = round((comp - 1) * 100, 2)
    elif broker_filter != "global":
        # AUDIT H-8 — day/week con filtro de broker: los snapshots son GLOBALES,
        # así que el delta por snapshots mostraba el movimiento de TODO el
        # portfolio como si fuera del broker (WeekCard "Binance +$1.500" cuando
        # Binance estuvo flat y subió Balanz), y unrealized = delta_global −
        # realized_broker mezclaba universos. Solo el realized es medible
        # per-broker sub-mensual → delta = realized, % = None (patrón B4/B10).
        dw_incomplete = True
    else:
        # week / day (global): snapshots para start/end
        # AUDIT D-1: el borde de arranque tiene que ser un cierre MEDIDO, igual
        # que en mes/año. Sin esto, día y semana agarraban la MISMA fila que el
        # guard del mes acababa de rechazar (la que el import fabricó al costo) y
        # republicaban el fantasma entero: con el caso real, el mes mostraba "—" y
        # un click más allá la semana decía "perdiste US$127.486 (−63,4%)".
        # Ojo: los dos escapes de más abajo NO lo cubren — start_value > 0, y el
        # gap entre bordes da 0 porque snap_start y snap_end son la misma fila.
        _dw_lag = 2 if period_type == "day" else 5
        snap_start = fetch_snapshot_at_or_before(conn, uid, period_start, mtm_only=True)
        if snap_start and not _border_is_fresh(snap_start.get("date"), period_start,
                                               max_lag_days=_dw_lag):
            snap_start = None
        if snap_start is None:
            # Sin borde medido: la fila cruda sirve para el net_deposited (es un
            # stamp de flujos, no una valuación), pero no para restarle el valor
            # de mercado de hoy.
            snap_start = fetch_snapshot_at_or_before(conn, uid, period_start)
            if snap_start and float(snap_start.get("total_value") or 0) > 0:
                basis_incomparable = True
        snap_end = fetch_snapshot_at_or_before(conn, uid, period_end)
        start_value = float(snap_start["total_value"]) if snap_start else 0.0
        _dw_current = live_value is not None and is_period_current(period_type, period_start, period_end)
        if _dw_current:
            end_value = float(live_value)
        else:
            end_value = float(snap_end["total_value"]) if snap_end else start_value
        # flows sub-mensuales vía net_deposited de los snapshots (descuenta
        # aportes/retiros para que no se cuenten como P&L del período).
        start_netdep = float(snap_start["net_deposited"] or 0) if snap_start else 0.0
        if _dw_current:
            # AUDIT B5/B7: net_deposited CANÓNICO con baseline, misma convención
            # que el snapshot de inicio (compute_net_deposited). Antes: SUM sin
            # baseline → flows desfasados por capital_inicio → delta_usd inflado.
            # Snapshots son globales → usamos 'global' para que start y end matcheen.
            from snapshots_job import compute_net_deposited_db
            end_netdep = compute_net_deposited_db(conn, uid, broker_filter='global', include_baseline=True)
        else:
            # AUDIT B12: net_deposited NULL → usar start_netdep (no 0, que daría
            # flows negativos falsos → ganancia fantasma).
            end_netdep = float(snap_end["net_deposited"]) if (snap_end and snap_end["net_deposited"] is not None) else start_netdep
        deposits = max(0.0, end_netdep - start_netdep)
        withdrawals = max(0.0, start_netdep - end_netdep)
        # AUDIT B4/B10: sin snapshot de inicio (start_value=0 con cartera real) el
        # retorno es inmedible → marcamos incompleto (delta_pct=None) en vez de un
        # % disparatado. Igual si la ventana entre bordes es demasiado grande.
        if start_value <= 0 and end_value > 0:
            dw_incomplete = True
        if snap_start and snap_end:
            try:
                _gap = (datetime.strptime(snap_end["date"], "%Y-%m-%d")
                        - datetime.strptime(snap_start["date"], "%Y-%m-%d")).days
                if (period_type == "day" and _gap > 4) or (period_type == "week" and _gap > 10):
                    dw_incomplete = True
            except (ValueError, TypeError, KeyError):
                pass

    flows = deposits - withdrawals
    delta_usd = end_value - start_value - flows
    delta_pct_val = _modified_dietz_pct(start_value, end_value, flows)
    delta_pct = round(delta_pct_val, 2) if delta_pct_val is not None else None
    # AUDIT B1: el año usa la composición geométrica de meses (si está disponible),
    # no el Modified Dietz único anual (que diverge cuando hay aportes).
    # AUDIT D-1: `year_twr_pct` compone los meses del año, pero si el mes vivo se
    # salteó por falta de borde medido, esa composición es de un año INCOMPLETO
    # presentada como la del año. Con el borde del año sí medido, el Dietz punta
    # a punta es el número honesto — caemos a él en vez de publicar el parcial.
    if period_type == "year" and year_twr_pct is not None and not _live_month_unmeasured:
        delta_pct = year_twr_pct
    # AUDIT B4/B10 + C-3/H-8: período sin base confiable (día/semana con huecos,
    # broker-filter sub-mensual, mes en curso sin historia) → % None, no un
    # número engañoso.
    if dw_incomplete:
        delta_pct = None

    # Para day/week, el unrealized del período = todo el delta que no es
    # realized (las posiciones abiertas se movieron en su mark-to-market).
    # monthly_entries trae unrealized directo; day/week lo derivamos.
    if period_type in ("day", "week"):
        if broker_filter != "global":
            # AUDIT H-8: solo el realized es del broker; sin snapshots per-broker
            # el MtM sub-mensual no es medible → delta = realized, unrealized 0.
            delta_usd = realized
            unrealized = 0.0
        else:
            unrealized = delta_usd - realized

    cum_aportado = fetch_cum_deposits_until(conn, uid, period_end, broker_filter)
    delta_pct_over_contrib = (
        (delta_usd / cum_aportado) * 100 if cum_aportado > 0 else None
    )

    # AUDIT D-1: base incomparable (start contable vs end a mercado). Va acá, al
    # FINAL, cuando ya no queda nada que derivar: tapar sólo el % dejaba el monto
    # ("P&L del mes −US$127.486" con 0 operaciones cerradas), y taparlo antes
    # dejaba a `delta_pct_over_contrib` publicando un "+0,0% sobre aportado"
    # calculado desde el 0 fabricado — un número inventado más creíble que el
    # anterior, no menos.
    #
    # Y NO lo reemplazamos por `realized + unrealized`: `unrealized` de
    # monthly_entries es el latente ACUMULADO desde que se compró cada activo
    # (lo postea el navegador en /api/monthly/sync-unrealized), no la variación
    # del período. Sin base comparable lo honesto es no publicar el número, no
    # publicar otro. El frontend muestra "—" y explica por qué.
    if basis_incomparable:
        delta_pct = None
        delta_usd = 0.0
        delta_pct_over_contrib = None
        if period_type in ("day", "week"):
            # Acá `unrealized` es derivado del delta (línea de arriba), o sea el
            # fantasma con otro nombre. En `month` viene de monthly_entries y es
            # un dato propio, así que ese se respeta.
            unrealized = 0.0

    # AUDIT D-2: `benchmark_return_for_period` devuelve el retorno PROPIO del
    # benchmark. Antes se guardaba tal cual en un campo llamado `vs_sp500_pct` y
    # nunca se le restaba el retorno de la cartera: la narrativa leía ese número
    # como si fuera la diferencia y publicaba "Quedaste 2.5 puntos por encima del
    # S&P 500" en un mes de −63,4% (el exceso real era −65,9pp). Ahora el retorno
    # del benchmark va a su propio campo y `vs_*_pct` es el EXCESO, que es lo que
    # el nombre promete y lo que ya asumían el frontend (`Reports.jsx`,
    # `MonthCard.jsx`, `demo.js`) y `ai/builders/reports.py`.
    sp500_ret = benchmark_return_for_period(bench or {}, period_type, period_start,
                                            period_end, "sp500")
    inflation_ret = benchmark_return_for_period(bench or {}, period_type, period_start,
                                                period_end, "inflation_ar")
    # Sin `delta_pct` no hay con qué comparar — y si lo tapamos por base
    # incomparable, publicar un "vs benchmark" sería reintroducir el mismo número
    # por la ventana.
    vs_sp500 = (delta_pct - sp500_ret) if (delta_pct is not None and sp500_ret is not None) else None
    vs_inflation = (delta_pct - inflation_ret) if (delta_pct is not None and inflation_ret is not None) else None

    metrics = PeriodMetrics(
        start_value=round(start_value, 2),
        end_value=round(end_value, 2),
        delta_usd=round(delta_usd, 2),
        delta_pct=delta_pct,
        delta_pct_over_contrib=round(delta_pct_over_contrib, 2) if delta_pct_over_contrib is not None else None,
        realized_pnl=round(realized, 2),
        unrealized_pnl=round(unrealized, 2),
        deposits=round(deposits, 2),
        withdrawals=round(withdrawals, 2),
        trades_count=len(trade_ops),
        win_count=len(wins),
        loss_count=len(losses),
        win_rate=round(win_rate, 1) if win_rate is not None else None,
        vs_sp500_pct=round(vs_sp500, 2) if vs_sp500 is not None else None,
        vs_inflation_pct=round(vs_inflation, 2) if vs_inflation is not None else None,
        sp500_return_pct=round(sp500_ret, 2) if sp500_ret is not None else None,
        inflation_pct=round(inflation_ret, 2) if inflation_ret is not None else None,
        basis_incomparable=basis_incomparable,
        basis=_basis,
    )
    return metrics, ops


# ─── Drivers (atribución por activo) ─────────────────────────────────────────

def compute_drivers(ops: List[Dict[str, Any]], top_n: int = 5) -> List[AssetContribution]:
    """Top activos por |pnl_usd|. Cada uno con su contribución %."""
    by_asset: Dict[str, float] = {}
    for o in ops:
        a = (o.get("asset") or "").upper().strip()
        if not a or a == "—":
            continue
        by_asset[a] = by_asset.get(a, 0.0) + float(o.get("pnl_usd") or 0)
    if not by_asset:
        return []
    total_abs = sum(abs(v) for v in by_asset.values()) or 1.0
    items = sorted(by_asset.items(), key=lambda kv: abs(kv[1]), reverse=True)[:top_n]
    return [
        AssetContribution(
            asset=a,
            pnl_usd=round(pnl, 2),
            contribution_pct=round(abs(pnl) / total_abs * 100, 1),
        )
        for a, pnl in items
    ]


# ─── Movers (mejor/peor holding por MtM, incluye no realizado) ────────────────

def fetch_holdings_snapshot_at_or_before(conn, uid: int, when: str) -> Optional[Dict[str, Any]]:
    """Último snapshot con foto por activo (holdings_json) y date <= when."""
    row = conn.execute(
        """SELECT date, holdings_json
             FROM snapshots
            WHERE user_id = ? AND date <= ? AND holdings_json IS NOT NULL
            ORDER BY date DESC LIMIT 1""",
        (uid, when),
    ).fetchone()
    return dict(row) if row else None


def compute_movers(conn, uid: int, start: str, end: str) -> Tuple[List[HoldingMover], bool]:
    """Mejor/peor holding por variación MtM en el período (incluye NO realizado).

    Diferencia la foto por activo (snapshots.holdings_json) entre los bordes.
    Devuelve (movers, available). available=False si falta la foto en algún
    borde (todavía no acumuló historia). Solo cuenta activos presentes en AMBOS
    bordes → una compra del período no cuenta como "ganancia" (ideal buy-and-hold).
    """
    try:
        open_prev = (datetime.strptime(start, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()
    except (ValueError, TypeError):
        return [], False
    snap_open = fetch_holdings_snapshot_at_or_before(conn, uid, open_prev)
    snap_close = fetch_holdings_snapshot_at_or_before(conn, uid, end)
    if not snap_open or not snap_close:
        return [], False
    if snap_open["date"] == snap_close["date"]:
        return [], False  # sin ventana (foto única) → sin movers
    try:
        open_map = {h["asset"]: float(h["value_usd"]) for h in json.loads(snap_open["holdings_json"] or "[]")}
        close_map = {h["asset"]: float(h["value_usd"]) for h in json.loads(snap_close["holdings_json"] or "[]")}
    except (ValueError, KeyError, TypeError):
        return [], False

    deltas: List[Tuple[str, float, Optional[float]]] = []
    for asset, v_end in close_map.items():
        v_start = open_map.get(asset)
        if v_start is None:
            continue  # posición nueva en el período — no es movimiento MtM
        d = v_end - v_start
        if abs(d) < 0.5:
            continue
        pct = (d / v_start) if v_start > 0 else None
        deltas.append((asset, d, pct))
    if not deltas:
        return [], True  # había foto en ambos bordes, pero nada se movió material

    deltas.sort(key=lambda x: x[1], reverse=True)
    best = deltas[0]
    movers = [HoldingMover(
        asset=best[0], delta_usd=round(best[1], 2),
        delta_pct=(round(best[2] * 100, 2) if best[2] is not None else None), kind="best",
    )]
    worst = deltas[-1]
    if worst[0] != best[0]:
        movers.append(HoldingMover(
            asset=worst[0], delta_usd=round(worst[1], 2),
            delta_pct=(round(worst[2] * 100, 2) if worst[2] is not None else None), kind="worst",
        ))
    return movers, True


# ─── Highlights (mejor op, peor op, etc.) ────────────────────────────────────

def compute_highlights(ops: List[Dict[str, Any]]) -> List[Highlight]:
    """Para Phase 1: best_op + worst_op. Best/worst day/week vienen en builder
    de mes-con-semanas (se computan desde los children)."""
    out: List[Highlight] = []
    if not ops:
        return out

    def _is_trade(op):
        t = (op.get("op_type") or "").strip()
        if t in ("Compra", "Dividendo", "Interés"):
            return False
        if t.startswith("Conversión") or t.startswith("CONVERSION"):
            return False
        return True

    trades = [o for o in ops if _is_trade(o) and o.get("pnl_usd") is not None]
    if trades:
        best = max(trades, key=lambda o: o["pnl_usd"])
        worst = min(trades, key=lambda o: o["pnl_usd"])
        if best["pnl_usd"] > 1:
            out.append(Highlight(
                kind="best_op",
                icon="🚀",
                label="Mejor operación",
                value_label=f"{best['asset']} +US${best['pnl_usd']:,.0f}",
                context=best["date"],
            ))
        if worst["pnl_usd"] < -1:
            out.append(Highlight(
                kind="worst_op",
                icon="💀",
                label="Peor operación",
                value_label=f"{worst['asset']} −US${abs(worst['pnl_usd']):,.0f}",
                context=worst["date"],
            ))
    return out


# ─── Headline auto-generada ─────────────────────────────────────────────────

# Tabla de sustantivo + género por tipo de período. Necesaria para que los
# adjetivos del headline concuerden correctamente en español (semana = fem,
# mes/día = masc). "difícil" es invariable y "período" es masc (fallback).
_PERIOD_WORD = {
    "year":  ("Año", "m"),
    "month": ("Mes", "m"),
    "week":  ("Semana", "f"),
    "day":   ("Día", "m"),
}

# Adjetivos: forma masculina → forma femenina. Si no aparece, se asume invariable.
_ADJ_FEMININE = {
    "sólido":  "sólida",
    "mixto":   "mixta",
    "tranquilo": "tranquila",
    # "difícil" es invariable → no entra acá
}


def _conjugate(adj_masc: str, gender: str) -> str:
    """Devuelve el adjetivo concordado al género del sustantivo."""
    if gender == "f":
        return _ADJ_FEMININE.get(adj_masc, adj_masc)
    return adj_masc


def generate_headline(metrics: PeriodMetrics, drivers: List[AssetContribution],
                     period_type: str) -> Tuple[str, Optional[str]]:
    """Genera headline + subheadline narrativos basados en la data.

    Reglas determinísticas (no LLM). Cada caso es un detector simple.
    Concuerda el género del adjetivo con el sustantivo del período.
    """
    # delta_pct puede ser None (avg<=0) — caemos a "sin grandes movimientos"
    delta = metrics.delta_pct if metrics.delta_pct is not None else 0.0
    abs_usd = abs(metrics.delta_usd or 0)
    realized = metrics.realized_pnl or 0
    period_word, gender = _PERIOD_WORD.get(period_type, ("Período", "m"))

    # AUDIT D-1: base incomparable. Va PRIMERO: con delta_pct=None y delta_usd=0
    # el flujo de abajo caía en "sin grandes movimientos", que afirma que no pasó
    # nada cuando lo cierto es que no lo sabemos.
    if getattr(metrics, "basis_incomparable", False):
        return (
            f"{period_word} sin base para medir el rendimiento.",
            "Falta el cierre a mercado del arranque del período.",
        )

    # Caso especial: cerraste operaciones ganadoras pero el portfolio total bajó
    # (mark-to-market negativo). El user "ganó plata" en lo que cerró, aunque
    # el delta total sea rojo. Lo hacemos explícito para evitar el headline
    # "perdiste X%" cuando en realidad cerraste con ganancia.
    if realized >= 50 and delta < -0.5 and metrics.trades_count > 0:
        return (
            f"Cerraste con ganancia (+US$ {realized:,.0f}), pero el portfolio bajó {abs(delta):.1f}%.".replace(",", "."),
            "Operaciones ganadoras compensadas por mark-to-market negativo de las posiciones abiertas.",
        )
    # Caso simétrico inverso: cerraste con pérdida pero el portfolio subió por mark-to-market positivo
    if realized <= -50 and delta > 0.5 and metrics.trades_count > 0:
        return (
            f"Operaciones con pérdida (US$ {realized:,.0f}), pero el portfolio subió {delta:.1f}%.".replace(",", "."),
            "Mark-to-market positivo compensó las pérdidas realizadas.",
        )

    # AUDIT B3 (F4): sin % medible (delta_pct None — día/semana per-broker, o
    # base incompleta) el headline sale del SIGNO de delta_usd, sin inventar
    # "+0.0%". Antes: None→0.0 → "mixto — +0.0%" aunque delta_usd fuera −300.
    if metrics.delta_pct is None:
        if abs_usd < 100:
            return (f"{period_word} sin grandes movimientos.", None)
        sign = "+" if (metrics.delta_usd or 0) >= 0 else "−"
        return (
            f"{period_word}: {sign}US$ {abs_usd:,.0f}.".replace(",", "."),
            "Sin base suficiente para calcular el % del período.",
        )

    # Caso 1: período flat — frase invariable
    if abs(delta) < 0.5 and abs_usd < 100:
        return (f"{period_word} sin grandes movimientos.", None)

    # Caso 2: período negativo significativo — "difícil" es invariable
    if delta < -3:
        sub = None
        if drivers:
            top_neg = next((d for d in drivers if d.pnl_usd < 0), None)
            if top_neg:
                sub = f"{top_neg.asset} fue el principal responsable de la caída."
        return (f"{period_word} difícil — {delta:.1f}%.", sub)

    # Caso 3: período positivo significativo — "sólido/sólida"
    if delta > 3:
        sub = None
        if drivers:
            top_pos = next((d for d in drivers if d.pnl_usd > 0), None)
            if top_pos and top_pos.contribution_pct >= 30:
                sub = f"{top_pos.asset} explicó el {top_pos.contribution_pct:.0f}% del rendimiento."
        return (f"{period_word} {_conjugate('sólido', gender)} — +{delta:.1f}%.", sub)

    # Default: período mixto — "mixto/mixta"
    sign = "+" if delta >= 0 else ""
    return (f"{period_word} {_conjugate('mixto', gender)} — {sign}{delta:.1f}%.", None)


# ─── Narrativa larga (qué pasó en el período) ────────────────────────────────

def generate_narrative(metrics: "PeriodMetrics", drivers: List["AssetContribution"],
                       highlights: List["Highlight"], period_type: str,
                       period_label_str: str) -> Optional[str]:
    """Genera un párrafo de 2-4 oraciones contando qué pasó en el período.

    Determinístico — combina métricas, drivers y benchmark. No usa LLM.
    Devuelve None si el período no tiene actividad relevante.
    """
    delta = metrics.delta_pct if metrics.delta_pct is not None else 0.0
    abs_usd = abs(metrics.delta_usd or 0)
    realized = metrics.realized_pnl or 0
    # AUDIT D-1: sin base comparable no se afirma un resultado del período. Era
    # esta función la que escribía "En ago 2026 perdiste US$127.486 (−63,4%)
    # sobre un capital inicial de US$201.119" — con 0 operaciones cerradas y sin
    # que nada hubiera medido esos US$201.119 a mercado. Contamos lo que SÍ es
    # medible (lo realizado y los flujos) y decimos por qué falta el resto.
    if getattr(metrics, "basis_incomparable", False):
        parts: List[str] = [
            f"No podemos calcular cuánto rindió {period_label_str.lower()}: falta el "
            f"cierre a mercado del arranque del período, así que compararlo contra el "
            f"valor de hoy daría una diferencia que no es tu resultado."
        ]
        if metrics.trades_count > 0:
            parts.append(
                f"Lo que sí está medido: cerraste {metrics.trades_count} "
                f"operación{'es' if metrics.trades_count != 1 else ''} por "
                f"US$ {realized:+,.0f} de P&L realizado.".replace(",", ".")
            )
        net_flow = (metrics.deposits or 0) - (metrics.withdrawals or 0)
        if abs(net_flow) >= 100:
            verbo = "Aportaste" if net_flow > 0 else "Retiraste"
            parts.append(f"{verbo} US$ {abs(net_flow):,.0f} en el período.".replace(",", "."))
        return " ".join(parts)
    if abs(delta) < 0.5 and abs_usd < 100 and metrics.trades_count == 0:
        return None

    parts: List[str] = []

    # Oración 1: balance general del período en USD y %.
    # Caso especial: realized positivo pero delta total negativo (o viceversa).
    # No usamos "ganaste/perdiste" sin contexto porque las dos cosas pueden ser
    # ciertas a la vez — separamos "valor del portfolio" de "P&L realizado".
    mismatch = (realized >= 50 and delta < -0.5) or (realized <= -50 and delta > 0.5)
    if mismatch:
        port_dir = "bajó" if delta < 0 else "subió"
        real_sign = "+" if realized >= 0 else "−"
        parts.append(
            f"En {period_label_str.lower()} tu portfolio {port_dir} US$ {abs(metrics.delta_usd):,.0f} ({delta:+.1f}%), "
            f"pero las operaciones cerradas dejaron {real_sign}US$ {abs(realized):,.0f} de P&L realizado. "
            f"La diferencia viene del mark-to-market de tus posiciones abiertas."
            .replace(",", ".")
        )
    else:
        # AUDIT B3 (F4): con delta_pct None (día/semana per-broker, base
        # incompleta) la dirección sale del SIGNO de delta_usd — antes None→0.0
        # → "ganaste US$ 300 (+0.0%)" con una pérdida de −300. El "(+X%)" se
        # omite sin dato, y el "capital inicial US$ 0" también (parecía cuenta
        # vaciada).
        _dir_sign = delta if metrics.delta_pct is not None else (metrics.delta_usd or 0)
        direction = "ganaste" if _dir_sign >= 0 else "perdiste"
        pct_txt = f" ({delta:+.1f}%)" if metrics.delta_pct is not None else ""
        base_txt = (f" sobre un capital inicial de US$ {metrics.start_value:,.0f}"
                    if (metrics.start_value or 0) > 0 else "")
        parts.append(
            f"En {period_label_str.lower()} {direction} "
            f"US$ {abs(metrics.delta_usd):,.0f}{pct_txt}{base_txt}."
            .replace(",", ".")
        )

    # Oración 2: drivers principales (top + bottom).
    top_pos = next((d for d in drivers if d.pnl_usd > 0), None)
    top_neg = next((d for d in reversed(drivers) if d.pnl_usd < 0), None)
    driver_bits: List[str] = []
    if top_pos and abs(top_pos.pnl_usd) >= 50:
        driver_bits.append(
            f"{top_pos.asset} aportó +US$ {top_pos.pnl_usd:,.0f}".replace(",", ".")
        )
    if top_neg and abs(top_neg.pnl_usd) >= 50:
        driver_bits.append(
            f"{top_neg.asset} restó US$ {abs(top_neg.pnl_usd):,.0f}".replace(",", ".")
        )
    if driver_bits:
        parts.append("Los movimientos más relevantes: " + " · ".join(driver_bits) + ".")

    # Oración 3: flujos de capital del período.
    net_flow = metrics.deposits - metrics.withdrawals
    if abs(net_flow) >= 100:
        if net_flow > 0:
            parts.append(f"Aportaste US$ {net_flow:,.0f} de capital nuevo.".replace(",", "."))
        else:
            parts.append(f"Retiraste US$ {abs(net_flow):,.0f} del portfolio.".replace(",", "."))

    # Oración 4: trades cerrados + win rate.
    if metrics.trades_count > 0:
        wr = metrics.win_rate
        wr_str = f" con {wr:.0f}% de win rate" if wr is not None else ""
        parts.append(
            f"Cerraste {metrics.trades_count} operación{'es' if metrics.trades_count != 1 else ''}"
            f"{wr_str}, sumando US$ {metrics.realized_pnl:+,.0f} de P&L realizado.".replace(",", ".")
        )

    # Oración 5: comparativa vs S&P 500 (solo si hay dato).
    #
    # ⚠️ FASE 2 · LA COMPARACIÓN SE PUBLICA, PERO CON EL SESGO DECLARADO.
    # Comparar dos RETORNOS no es el crimen de la Fase 1 —ahí se restaban dos
    # VALUACIONES medidas con reglas distintas—: acá cada retorno se calcula entero
    # bajo su propia regla y recién después se contrastan. Por eso la frase queda.
    #
    # Lo que NO puede quedar es callado: con `basis='contable'` el retorno del
    # usuario NO incluye lo no realizado (`pnl_unrealized = 0` en toda la cadena),
    # así que una cartera que se duplicó sin vender nada entra a la comparación
    # como ~0%. El sesgo es sistemático y va SIEMPRE para el mismo lado —en contra
    # del usuario—, y sin decirlo la frase es engañosa aunque cada mitad esté bien
    # calculada.
    if metrics.vs_sp500_pct is not None and abs(metrics.vs_sp500_pct) >= 0.5:
        sign = "encima" if metrics.vs_sp500_pct > 0 else "debajo"
        _frase = f"Quedaste {abs(metrics.vs_sp500_pct):.1f} puntos por {sign} del S&P 500."
        if getattr(metrics, "basis", None) == "contable":
            _frase += (" Ojo: tu número está reconstruido de tu contabilidad y no "
                       "cuenta las ganancias que todavía no vendiste, así que la "
                       "comparación te juega en contra.")
        parts.append(_frase)

    return " ".join(parts) if parts else None


# ─── Punto de entrada principal ──────────────────────────────────────────────

def build_period_report(
    conn, uid: int, period_type: str, period_key: str,
    broker_filter: str = "global",
    bench: Optional[Dict[str, Any]] = None,
    live_value: Optional[float] = None,
    today: Optional[date_cls] = None,
) -> PeriodReport:
    """Builder principal — recibe un período, devuelve el PeriodReport completo
    (sin children. Children se anidan en `timeline.py`)."""
    start, end = parse_period_bounds(period_type, period_key)
    label = period_label(period_type, period_key, start)
    is_current = is_period_current(period_type, start, end, today=today)

    metrics, ops = compute_metrics_for_period(
        conn, uid, period_type, start, end, broker_filter,
        bench=bench, live_value=live_value,
    )
    drivers = compute_drivers(ops)
    highlights = compute_highlights(ops)
    movers, movers_available = compute_movers(conn, uid, start, end)
    headline, subheadline = generate_headline(metrics, drivers, period_type)
    narrative = generate_narrative(metrics, drivers, highlights, period_type, label)

    # is_relevant: hay actividad económica o cambios significativos
    # AUDIT D-1: con base incomparable `delta_usd` es 0 por el guard, no porque
    # no haya pasado nada — sin esto un período impublicable se colapsaba a "sin
    # actividad" y viajaba así al packet de la IA y al calendario.
    is_relevant = (
        metrics.trades_count > 0
        or abs(metrics.delta_usd) >= 100
        or metrics.deposits > 0
        or metrics.withdrawals > 0
        or metrics.basis_incomparable
    )

    return PeriodReport(
        period_type=period_type,
        period_key=period_key,
        period_label=label,
        period_start=start,
        period_end=end,
        is_current=is_current,
        is_relevant=is_relevant,
        headline=headline,
        subheadline=subheadline,
        metrics=metrics,
        insights=[],  # se llena en otro pase (detectors.py)
        highlights=highlights,
        drivers=drivers,
        movers=movers,
        movers_available=movers_available,
        children=[],
        narrative=narrative,
    )
