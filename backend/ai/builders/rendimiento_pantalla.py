"""rendimiento_pantalla — el rendimiento que la PANTALLA ya calculó, listo para la IA.
═══════════════════════════════════════════════════════════════════════════
── Por qué los builders NO calculan "Hoy", "Este mes" ni el chip del rango ──
Esos números los calcula el navegador (`frontend/src/utils/evolution.js`:
`computeDailyPnl`, `computeReturnDelta`, `rendimientoDelRango`) con el valor
VIVO de la cartera, que también se calcula en el navegador. Una segunda
implementación acá da otro número apenas difiera cualquiera de sus entradas
—el valor vivo, lo aportado, el día de arranque, qué foto sirve de base— y la
IA termina contradiciendo a la pantalla desde la que la llamaron.

Fue exactamente lo que pasó (2026-09-25): el "Analizar" de la curva restaba
valores a secas (`value_end − value_start`). Un depósito en el medio del rango
salía como ganancia: la IA podía decir "subiste 18 %" al lado de un chip que
decía "+1 %". Y terminaba en la última foto guardada, no en la cartera de ahora.

Es el mismo criterio que `distribution.py` (las tortas): la pantalla manda lo
que muestra y el builder sólo lo sanea. Lo que acá NO se hace es "completar"
un número que la pantalla no mandó con una cuenta propia: si la pantalla dice
"Sin rendimiento medible", la IA tiene que decir lo mismo.

── El contrato ────────────────────────────────────────────────────────────
Lo arma `frontend/src/utils/rendimientoAi.js` y lo fija
`tests/fixtures/rendimiento_pantalla.json`, que leen los tests de LOS DOS
lados (si el navegador cambia la forma, se pone rojo el test de acá):

    { usd, pct, desde, dias, rotulo_con_fecha, valor_inicio, aportes }

      usd          resultado en dólares, el que muestra la pantalla
      pct          FRACCIÓN (0.0123 = +1,23 %): Dietz en un período (sobre
                   valor_inicio + ½·aportes), sobre valor_inicio en "Hoy"
      desde        YYYY-MM-DD del cierre con el que abre la medición
      dias         cuántos días mide de verdad
      rotulo_con_fecha  true cuando la pantalla rotula "desde el DD/MM" en vez
                   del nombre del rango (no había un cierre pegado al arranque)
      valor_inicio valor de la cartera en ese cierre (la base del %)
      aportes      aportes − retiros del tramo. NO son ganancia. Puede faltar:
                   sin `net_deposited` en la foto de arranque no hay cómo saberlo.

Son NÚMEROS y una fecha — nada de texto libre del navegador entra al paquete.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Dict, Optional

_RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Topes de cordura. No juzgan si el número es "razonable" —eso es trabajo del
# motor que lo calculó—: sólo impiden que un valor absurdo o fabricado a mano
# entre al contexto del modelo.
_MAX_USD = 1e12
_MAX_PCT = 1e4          # como fracción: 1.000.000 %
_MAX_DIAS = 36_600      # 100 años


def _num(v) -> Optional[float]:
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _fecha(v) -> Optional[str]:
    if not isinstance(v, str) or not _RE_FECHA.match(v):
        return None
    try:
        date.fromisoformat(v)
    except ValueError:
        return None
    return v


def leer(raw: Any) -> Optional[Dict[str, Any]]:
    """El rendimiento que mandó la pantalla, saneado y con nombres que se
    explican solos. `None` si no vino o no se puede leer.

    `resultado_pct` sale en PORCENTAJE (1.23 = +1,23 %), que es como lo lee el
    modelo en el resto del contexto (`usd_30d_pct`, `ytd_pct`).
    """
    if not isinstance(raw, dict):
        return None
    usd = _num(raw.get("usd"))
    pct = _num(raw.get("pct"))
    if usd is None or pct is None or abs(usd) > _MAX_USD or abs(pct) > _MAX_PCT:
        return None
    out: Dict[str, Any] = {
        "resultado_usd": round(usd, 2),
        "resultado_pct": round(pct * 100, 2),
    }
    desde = _fecha(raw.get("desde"))
    if desde:
        out["desde"] = desde
    dias = _num(raw.get("dias"))
    if dias is not None and 1 <= dias <= _MAX_DIAS:
        out["dias"] = int(round(dias))
    base = _num(raw.get("valor_inicio"))
    if base is not None and 0 < base <= _MAX_USD:
        out["valor_al_inicio_usd"] = round(base, 2)
    aportes = _num(raw.get("aportes"))
    if aportes is not None and abs(aportes) <= _MAX_USD:
        out["aportes_netos_usd"] = round(aportes, 2)
    if raw.get("rotulo_con_fecha") is True:
        out["rotulo_con_fecha"] = True
    return out


# Cómo leer los números de arriba. Va ADENTRO del paquete porque es lo único que
# llega al modelo en el ✦: el chat no usa los prompts de `ai/prompts.py`.
NOTA_PERIODO = (
    "Son los números que el usuario está viendo, ya descontados los aportes y "
    "retiros: citá ésos. `desde` y `dias` dicen qué tramo mide cada uno; si "
    "`rotulo_con_fecha` es true o `dias` no coincide con el período del rótulo "
    "(por ejemplo un 'hoy' de 3 días después de un fin de semana), decí desde qué "
    "fecha mide, como hace la pantalla."
)


def nota_moneda(params: Dict[str, Any]) -> Optional[str]:
    """Si el usuario mira la pantalla en pesos, la pantalla muestra estos mismos
    resultados convertidos y el modelo los tiene en dólares: que lo diga."""
    if isinstance(params, dict) and params.get("moneda") == "ARS":
        return ("El usuario está viendo la pantalla en PESOS; estos resultados "
                "están en dólares (MEP). Si los citás, decí que son en dólares y "
                "no los conviertas.")
    return None


# Lo que va al paquete cuando no hay número, con las palabras de la pantalla.
SIN_NUMERO_EN_PANTALLA = (
    "La pantalla no muestra un rendimiento para este período: no tiene "
    "mediciones a precio de mercado con qué calcularlo. Decí eso mismo; no lo "
    "calcules con los valores de la curva, porque incluyen lo que el usuario "
    "depositó y retiró."
)
NO_LLEGO_DE_LA_PANTALLA = (
    "Este análisis no recibió el número que muestra la pantalla. No lo calcules "
    "con los valores de la curva: incluyen lo que el usuario depositó y retiró, y "
    "darías un número distinto al que está viendo."
)
