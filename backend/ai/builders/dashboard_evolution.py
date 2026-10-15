"""builders.dashboard_evolution — packet de la evolución / curva del portfolio.
═══════════════════════════════════════════════════════════════════════════
Topic: dashboard.evolution — el ✦ de la tarjeta "Evolución" del Dashboard.

── DOS COSAS DISTINTAS EN LA MISMA TARJETA ────────────────────────────────
  · EL RENDIMIENTO DEL RANGO: el chip "±USD X · ±Y % en <rango>". Lo calcula la
    pantalla (`rendimientoDelRango` en frontend/src/utils/evolution.js) y llega
    en `params["rendimiento"]`. Este builder NO lo recalcula — ver la cabecera
    de `rendimiento_pantalla.py`.
  · LA CURVA: el VALOR de la cartera en el tiempo. Incluye lo que el usuario
    depositó y retiró, así que que suba o baje NO es ganancia ni pérdida.

Antes el paquete las mezclaba: `delta_pct = (value_end − value_start) /
value_start`, sobre la curva. Un depósito en el medio del rango contaba como
ganancia (la IA podía decir "subiste 18 %" al lado de un chip que decía
"+1 %"), la ventana se cortaba con el reloj UTC y terminaba en la última foto
guardada en vez de la cartera de ahora. Y el "drawdown" era el mismo error al
revés: un retiro del 30 % se leía como una caída del 30 %.

Params (los manda AskAIAbout desde Dashboard.jsx):
    period_days  — días del rango (1, 7, 30, 180, 365; MAX llega como 1825)
    rango        — '1D' | '1W' | '1M' | '6M' | '1Y' | 'MAX'
    rendimiento  — el chip, con la forma de `rendimiento_pantalla` | null
                   (null = la pantalla dice "Sin rendimiento medible")

Shape (~700 bytes):
{
  "screen": "dashboard.evolution",
  "period_days": int, "rango": str | null,
  "rendimiento_del_rango": {resultado_usd, resultado_pct, desde, dias,
                            valor_al_inicio_usd, aportes_netos_usd} | null,
  "rendimiento_motivo": str,                     # sólo si es null
  "curva": {
    "que_es": str,
    "ventana": {"desde", "hasta", "ampliada"},
    "puntos": [[date, value_usd], ...],          # hasta 12 cierres medidos
    "valor_maximo": {"date", "value"}, "valor_minimo": {"date", "value"},
  } | null,
  "insufficient_data": true, "reason": str,      # sólo si curva es null
  "caida_desde_el_mejor_momento_pct": float | null,
  "caida_al_cierre": str | null,
  "best_month": {"month", "pct"} | null,         # del motor: `twr.rendimientos_mensuales`
  "worst_month": {"month", "pct"} | null,
  "meses_base": "mercado" | "contable" | null,   # con qué regla se rankearon
  "meses_sin_medir_a_mercado": int,
}
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import twr as _twr

from . import rendimiento_pantalla

_RANGOS = ("1D", "1W", "1M", "6M", "1Y", "MAX")

_QUE_ES_LA_CURVA = (
    "El VALOR de la cartera en cada cierre medido a precio de mercado. Incluye lo "
    "que el usuario depositó y retiró: que la curva suba o baje NO es ganancia ni "
    "pérdida. El rendimiento es `rendimiento_del_rango`. Termina en el último "
    "cierre guardado, no en el valor de este momento."
)


def _dias(v, default: Optional[int]) -> Optional[int]:
    """`period_days` saneado. None / 0 / basura → default."""
    try:
        d = int(v)
    except (TypeError, ValueError):
        return default
    return d if 0 < d <= 36_600 else default


def _ventana(snapshots: List[Dict[str, Any]], period_days: Optional[int]
             ) -> Tuple[List[Dict[str, Any]], bool]:
    """Los cierres que describen el rango, y si hubo que ampliarlo.

    Arranca donde arranca el chip: `inicioDeVentana(dias)` del frontend, el primer
    día ADENTRO del rango contado en días ARGENTINOS (antes era `utcnow`, y desde
    las 21:00 la ventana perdía un día). Como la curva de la pantalla, incluye el
    último cierre ANTERIOR a ese día: es el que abre el rango.
    """
    if period_days:
        inicio = (date.fromisoformat(_twr._hoy_art())
                  - timedelta(days=period_days - 1)).isoformat()
        antes = [s for s in snapshots if s["date"] < inicio]
        adentro = [s for s in snapshots if s["date"] >= inicio]
        in_window = antes[-1:] + adentro
    else:
        in_window = list(snapshots)
    # ⚠️ El fallback amplía la ventana; el rótulo tiene que decirlo. Sin esto el
    # paquete salía con `period_days: 365` y un valor de hace tres años, y el LLM
    # leía "así evolucionó tu último año". Ningún campo declaraba la ventana real.
    if len(in_window) < 2:
        return snapshots[-12:], True
    return in_window, False


def _caida_desde_el_mejor_momento(conn, user_id: int, desde: str):
    """Cuánto está la cartera abajo de su mejor momento en el rango, MEDIDO COMO
    RENDIMIENTO: `twr.curva_indexada` encadena `dietz`, que descuenta aportes y
    retiros. Es el mismo motor del drawdown de Métricas.

    Con los valores crudos de la curva (lo que había acá), sacar la mitad de la
    plata era "estás 50 % abajo de tu máximo". `None` cuando el motor no puede
    afirmarlo (la serie tiene un hueco en el rango, o no hay dos cierres)."""
    try:
        c = _twr.curva_indexada(conn, user_id, desde=desde)
    except Exception:
        return None, None
    dd = c.get("drawdown_actual")
    if dd is None:
        return None, None
    return round(float(dd) * 100, 2), c.get("ventana_hasta")


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    period_days = _dias(kwargs.get("period_days"), 365)
    rango = kwargs.get("rango") if kwargs.get("rango") in _RANGOS else None

    out: Dict[str, Any] = {
        "screen": "dashboard.evolution",
        "period_days": period_days,
        "rango": rango,
    }

    # ── El número del chip ────────────────────────────────────────────────
    # `None` explícito = la pantalla dice "Sin rendimiento medible" en ese rango.
    # Clave ausente = el pedido no la trajo (un navegador con la versión
    # anterior de la página). En ninguno de los dos casos se calcula acá.
    rendimiento = rendimiento_pantalla.leer(kwargs.get("rendimiento"))
    out["rendimiento_del_rango"] = rendimiento
    if rendimiento is not None:
        out["nota_rendimiento"] = rendimiento_pantalla.NOTA_PERIODO
    _moneda = rendimiento_pantalla.nota_moneda(kwargs)
    if _moneda:
        out["nota_moneda"] = _moneda
    if rendimiento is None:
        out["rendimiento_motivo"] = (
            rendimiento_pantalla.SIN_NUMERO_EN_PANTALLA if "rendimiento" in kwargs
            else rendimiento_pantalla.NO_LLEGO_DE_LA_PANTALLA)

    # ── La curva (valor, no rendimiento) ──────────────────────────────────
    # ⚠️ NO se leen los snapshots crudos. La tabla mezcla mediciones reales del
    # cron con fotos que el import FABRICA copiando la cadena contable
    # (persister.py:1289-1292): esas no bajan con el mercado, asi que fijan
    # picos que nunca existieron. `twr.serie_medible` deja solo lo que esta en
    # base de mercado (medido por el cron o reconstruido a precio real).
    _serie = _twr.serie_medible(conn, user_id)
    snapshots = [{"date": p["date"], "total_value": p["value"]}
                 for p in _serie["medibles"] if p.get("value")]

    in_window, ampliada = _ventana(snapshots, period_days)
    if len(in_window) < 2:
        # `insufficient_data` + `reason` describen la CURVA, como en el resto de
        # los builders. El chip puede tener número igual —la pantalla mide contra
        # el valor de ahora con un solo cierre— y por eso no se corta arriba.
        out["curva"] = None
        out["insufficient_data"] = True
        # El motivo sale de `twr.MOTIVO_TEXTO`: el asesor y el usuario final
        # tienen que leer exactamente lo mismo.
        out["reason"] = (
            _serie.get("motivo_texto")
            or "Necesitamos al menos 2 cierres medidos para describir la curva.")
        out["caida_desde_el_mejor_momento_pct"] = None
        out["caida_al_cierre"] = None
        out.update(_mejor_y_peor_mes(conn, user_id))
        return out

    values = [(s["date"], float(s["total_value"])) for s in in_window]
    maximo = max(values, key=lambda v: v[1])
    minimo = min(values, key=lambda v: v[1])

    # Reducir a 12 puntos representativos (downsampling uniforme)
    n = len(values)
    if n <= 12:
        points = values
    else:
        step = n / 12
        points = [values[min(int(i * step), n - 1)] for i in range(12)]
        if points[-1][0] != values[-1][0]:
            points[-1] = values[-1]  # asegurar el último punto

    out["curva"] = {
        "que_es": _QUE_ES_LA_CURVA,
        # La ventana que estos números describen DE VERDAD (puede no ser
        # `period_days` si hubo que ampliarla por falta de mediciones).
        "ventana": {"desde": values[0][0], "hasta": values[-1][0],
                    "ampliada": ampliada},
        "puntos": [[d, int(round(v))] for d, v in points],
        "valor_maximo": {"date": maximo[0], "value": int(round(maximo[1]))},
        "valor_minimo": {"date": minimo[0], "value": int(round(minimo[1]))},
    }
    caida, al_cierre = _caida_desde_el_mejor_momento(conn, user_id, values[0][0])
    out["caida_desde_el_mejor_momento_pct"] = caida
    out["caida_al_cierre"] = al_cierre
    out.update(_mejor_y_peor_mes(conn, user_id))
    return out


def _mejor_y_peor_mes(conn, user_id: int) -> Dict[str, Any]:
    """Mejor / peor mes, del MOTOR (`twr.rendimientos_mensuales`).

    ⚠️ ANTES SALÍA DEL DIETZ DE `monthly_entries`, y para un mes cerrado esa fila
    está al costo: el mes de una cartera que no vendió daba ~0 % aunque se hubiera
    movido 20 %. El "peor mes" era el plano y el que se derrumbó ni aparecía.
    `meses_base` dice con qué regla se rankeó ('mercado' o, si ningún mes se pudo
    medir a mercado, 'contable').
    """
    r = _twr.mejor_y_peor_mes(_twr.rendimientos_mensuales(conn, user_id))
    best_month = worst_month = None
    if r["mejor"] is not None:
        # `pct` en fracción (0,05 = 5 %), como siempre publicó este paquete.
        best_month = {"month": r["mejor"]["mes"], "pct": round(r["mejor"]["pct"] / 100, 4)}
        worst_month = {"month": r["peor"]["mes"], "pct": round(r["peor"]["pct"] / 100, 4)}
    return {"best_month": best_month, "worst_month": worst_month,
            "meses_base": r["base"],
            "meses_sin_medir_a_mercado": r["sin_medir_a_mercado"]}
