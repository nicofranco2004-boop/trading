"""builders.caida_medida — la caída de la cartera, MEDIDA COMO RENDIMIENTO.
═══════════════════════════════════════════════════════════════════════════
No es un topic: es la cuenta que comparten los paquetes que le hablan al modelo
de caídas ("drawdown"). Hoy la usan `insights_drawdown` (el ✦ de la tarjeta
"Curva de drawdown") e `insights` (el bloque `drawdown` del ✦ de Métricas).

── POR QUÉ EXISTE ─────────────────────────────────────────────────────────
Los dos armadores medían la caída sobre el VALOR de la cartera:

    caída = (valor − valor_máximo) / valor_máximo

y el valor incluye lo que el usuario deposita y retira. Sacar 10.000 de una
cartera de 20.000, con el mercado quieto, era "una caída del 50 %"; y un
depósito subía el "máximo" que después cualquier baja de mercado medía como
derrumbe. La tarjeta de la pantalla, al lado, decía 0,0 %.

Acá se mide con `twr.curva_indexada`: encadena `dietz`, que descuenta aportes y
retiros, así que un movimiento de plata no es ni una subida ni una caída. Es el
MISMO motor y la MISMA llamada que `/api/insights/performance` (performance.py),
que es de donde la tarjeta saca "Actual" y "Máx histórico". Para que el número
sea idéntico, recibe lo mismo que recibe la pantalla:

    moneda      — 'usd' | 'ars'. En pesos el rendimiento incluye la devaluación:
                  es otro número, y la tarjeta muestra el de la moneda elegida.
    valor_live  — la cartera de AHORA en dólares (el `valor_live` que manda
                  Insights.jsx). Cierra la curva en "hoy"; sin él, a media rueda
                  el número es el del último cierre.

Si no llegan (un navegador con la versión anterior de la página), se mide en
dólares hasta el último cierre, y el resultado lo DICE (`moneda`, `incluye_hoy`).

── LO QUE NO SE PUBLICA ───────────────────────────────────────────────────
El valor de la cartera en el pico y en el fondo. Restados son exactamente la
cuenta vieja: con un retiro en el medio, "de US$ 20.000 a US$ 9.000" es el −55 %
que este módulo vino a sacar.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, List, Optional

import twr as _twr
from fechas import hoy_art

# Eventos de caída reportables: más de 5 % abajo del máximo.
UMBRAL_EVENTO_PCT = -5.0

QUE_ES = (
    "Caídas medidas como RENDIMIENTO, no como valor: un depósito o un retiro NO es "
    "una subida ni una caída de la cartera. Son los mismos números que muestra la "
    "tarjeta 'Curva de drawdown' de la pantalla (Actual y Máx histórico), sobre toda "
    "la historia medida a precio de mercado (desde `medido_desde`)."
)

_SIN_MEDICIONES = "No hay mediciones a mercado suficientes para medir la caída."


def leer_moneda(v) -> str:
    """La moneda que pidió la pantalla. Cualquier otra cosa → dólares."""
    return _twr.MONEDA_ARS if str(v or "").strip().lower() == "ars" else _twr.MONEDA_USD


def leer_valor_live(v) -> Optional[float]:
    """El valor de AHORA que mandó la pantalla: un número positivo y finito, o
    nada. Lo mismo que acepta `/api/insights/performance`."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if (math.isfinite(f) and f > 0) else None


def _fecha(d: str) -> str:
    """El punto del valor vivo se llama "hoy"; acá se escribe con la fecha."""
    return hoy_art() if d == "hoy" else str(d)[:10]


def _dias(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _pct(x: float) -> float:
    # `+ 0.0` para que un −0,0 no viaje con signo.
    return round(float(x) * 100, 2) + 0.0


def _episodios(puntos: List[Dict[str, Any]]):
    """Cada vez que el índice quedó abajo de su máximo, desde el pico hasta que lo
    volvió a alcanzar. Devuelve (episodios, fecha del máximo vigente).

    Sobre `punto["drawdown"]`, que es el índice publicado dividido su máximo — el
    mismo número que dibuja la curva de la tarjeta.
    """
    episodios: List[Dict[str, Any]] = []
    pico = _fecha(puntos[0]["date"])
    abierto: Optional[Dict[str, Any]] = None
    for p in puntos:
        f, dd = _fecha(p["date"]), float(p["drawdown"])
        if dd >= 0:                      # en el máximo (el motor lo redondea a 6)
            if abierto:
                abierto["end_date"] = f
                episodios.append(abierto)
                abierto = None
            pico = f
        elif abierto is None:
            abierto = {"start_date": pico, "trough_date": f, "_dd": dd, "end_date": None}
        elif dd < abierto["_dd"]:
            abierto["_dd"], abierto["trough_date"] = dd, f
    if abierto:
        episodios.append(abierto)
    return episodios, pico


def _formatear(e: Dict[str, Any], hasta: str) -> Dict[str, Any]:
    fin = e["end_date"]
    return {
        "start_date": e["start_date"],     # el pico desde el que cayó
        "trough_date": e["trough_date"],   # el fondo
        "end_date": fin,                   # cuando volvió al pico; None = sigue abajo
        "depth_pct": _pct(e["_dd"]),
        # Del pico a la salida; si sigue abajo, del pico a la última medición.
        "duration_days": _dias(e["start_date"], fin or hasta),
        # Del fondo a la salida: "cuánto tardé en recuperarla".
        "recovery_days": _dias(e["trough_date"], fin) if fin else None,
    }


def medir(conn, user_id: int, *, moneda=None, valor_live=None) -> Dict[str, Any]:
    """La caída actual, la peor, y cada episodio, medidos como rendimiento.

    Con `insufficient_data: True` (y los números en None, NUNCA en 0) cuando el
    motor no puede afirmarla: la tarjeta en ese caso muestra "—". Un 0,0 % sin
    medir le diría al modelo "nunca caíste".
    """
    _moneda = leer_moneda(moneda)
    _live = leer_valor_live(valor_live)
    # La misma llamada que performance.py:291 con los defaults de la pantalla
    # (modo certero, sin `desde`/`hasta`, sin indeterminados). La tarjeta de
    # drawdown sólo existe en certero: el estimado no tiene camino de precios.
    c = _twr.curva_indexada(conn, user_id, valor_live=_live, moneda=_moneda)

    out: Dict[str, Any] = {"que_es": QUE_ES, "moneda": _moneda}
    actual, maximo = c.get("drawdown_actual"), c.get("drawdown_maximo")
    puntos = [p for p in (c.get("curva") or [])
              if p.get("apto") and p.get("drawdown") is not None]
    if actual is None or maximo is None or len(puntos) < 2:
        out.update({
            "medido_desde": None, "medido_hasta": None, "incluye_hoy": False,
            "current_pct": None, "max_pct": None, "max_date": None,
            "max_peak_date": None, "days_since_peak": None, "recovered": None,
            "worst_event": None, "episodios": [],
            "insufficient_data": True,
            "reason": c.get("motivo_texto") or _SIN_MEDICIONES,
        })
        return out

    hasta = _fecha(puntos[-1]["date"])
    episodios, pico_vigente = _episodios(puntos)
    eventos = [_formatear(e, hasta) for e in episodios]
    peor = min(eventos, key=lambda e: e["depth_pct"]) if eventos else None
    out.update({
        "medido_desde": _fecha(puntos[0]["date"]),
        "medido_hasta": hasta,
        "incluye_hoy": puntos[-1]["date"] == "hoy",
        # Los dos números de la tarjeta, tal cual los publica el motor.
        "current_pct": _pct(actual),
        "max_pct": _pct(maximo),
        "max_date": (_fecha(c["drawdown_maximo_fecha"])
                     if c.get("drawdown_maximo_fecha") else None),
        "max_peak_date": (_fecha(c["drawdown_maximo_pico"])
                          if c.get("drawdown_maximo_pico") else None),
        # Días desde el máximo vigente hasta la última medición (0 = está en él).
        "days_since_peak": _dias(pico_vigente, hasta),
        # ¿Volvió al pico después de la peor caída? Sin caídas, no hay nada que
        # recuperar.
        "recovered": (peor is None) or (peor["end_date"] is not None),
        "worst_event": peor,
        "episodios": eventos,
    })
    return out
