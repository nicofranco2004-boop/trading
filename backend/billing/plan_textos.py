"""plan_textos — lo que incluye cada plan, dicho con los números que el
producto APLICA de verdad.
═══════════════════════════════════════════════════════════════════════════
Por qué existe. Los mails de bienvenida, de regalo y de vencimiento traían la
lista de features de cada plan escrita a mano, y se había quedado atrás de los
límites reales sin que nada avisara:

  · Pro: "60 análisis IA por semana (10× más que Free)" — contra Free, que
    tiene 1 por semana, son 60×;
  · Plus: "4 análisis de comportamiento" (son 6 detectores) y "diagnóstico
    completo (6 observaciones)", un tope que ninguna pantalla aplica;
  · lo que pierde un Pro al vencer: "vas a quedar en 6" análisis. Al caer a
    Free le queda 1; el 6 era el cupo de Plus.

Un mail así no falla: sale y miente. Es la misma deuda que tenía el muro de
pago, que se arregló con `frontend/src/data/planCatalog.js` y el guard
`tests/test_promesas_vs_producto.py`. El guard de este módulo es
`tests/test_mails_vs_limites.py`.

LA REGLA: todo número sale de los límites que el backend aplica —
`ai.quota.LIMITS` (cupos semanales) y `ai.plan.PLAN_LIMITS` (brokers,
detectores, alertas y accesos)— y se lee al armar el texto, no al importar el
módulo. El 2026-10-15 se revierte `78f43739` (Plus: 2 análisis, los 12
detectores, alertas sin tope) y los mails acompañan solos.

LO QUE NO SE PROMETE, A PROPÓSITO. Dos entradas de PLAN_LIMITS están declaradas
pero ninguna pantalla las aplica, y prometerlas es mentir igual que con un
número viejo:
  · `insights_diagnostic_visible`: todos ven el diagnóstico entero. Lo que se
    limita es el "No me interesa" (`diag_dismiss_per_week`), y eso sí se dice.
  · `insights.distribucion_activo`: la distribución de activos se abrió para
    todos (ver el comentario en `pages/Insights.jsx`: "era 'Por activo' en
    Distribución, gateada Pro"). Un Free no la pierde.
Si alguno de los dos vuelve a aplicarse, se suma acá.

Lo que no es un número (el chat libre, las respuestas con causalidad, el panel
del asesor) no está en esas tablas: el chat libre y el modo research-note se
deciden por tier en `main.py` (`is_premium`), y el panel del asesor en
`_require_advisor`. Va escrito a mano en `_SIN_NUMEROS`, y ahí no hay cifras.

Formato: cada renglón es un string con el tramo a resaltar entre `**`. El HTML
lo vuelve <b> y el texto plano lo saca, así las dos versiones del mail dicen lo
mismo por construcción.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Optional

from ai.plan import PLAN_LIMITS
from ai.quota import LIMITS

log = logging.getLogger("billing.plan_textos")

# Adónde cae una cuenta que TIENE Free cuando se le termina lo que tenía. Quien
# nació sin plan gratis no cae a ningún lado: queda en pausa, y a esa persona
# no se le manda esta lista (ver `emails._al_terminar`). Es el único destino:
# los paréntesis de `_lo_que_queda` dicen "en Free".
PLAN_AL_VENCER = "free"


def _n(n: int, uno: str, varios: str) -> str:
    return f"{n} {uno if n == 1 else varios}"


# ─── Los cupos de UNA persona ───────────────────────────────────────────────

def cupos_del_usuario(conn, user_id: int, plan: str) -> Optional[dict]:
    """Los cupos semanales que ESTA cuenta tiene en `plan`, leídos de
    `quota.get_current_usage` — la misma función que le muestra sus cupos en
    la app.

    Existe por los que ya pagaban Plus: desde el 2026-10-15 (`git revert
    78f43739`) a ellos se les respeta el cupo viejo de análisis
    (`quota.limites_del_usuario`, que `get_current_usage` consulta). Un mail
    que leyera sólo `LIMITS[plan]` le diría a esa persona el número del plan,
    no el suyo — justo en el aviso de vencimiento, que es a quien le puede
    llegar si cancela con la suba de precio.

    None si no se puede leer: el mail sale igual, con los cupos del plan."""
    try:
        from ai import quota
        uso = quota.get_current_usage(conn, user_id, tier_override=plan)
        return {"analyses_per_week": uso["analyses_limit"],
                "chat_per_week": uso["chat_limit"],
                "diag_dismiss_per_week": uso["diag_dismiss_limit"]}
    except Exception as ex:
        log.warning("cupos de uid=%s en %s: no se pudieron leer (%s); el mail "
                    "va con los del plan", user_id, plan, ex)
        return None


# ─── Lo que da cada plan, leído de los límites ──────────────────────────────
# `None` = sin tope, igual que en las dos tablas de origen.

def _valor(clave: str, plan: str, cupos: Optional[dict] = None):
    """Lo que `plan` da en `clave`. `cupos` pisa los cupos semanales del plan
    con los de una persona (ver `cupos_del_usuario`)."""
    semana = {**LIMITS[plan], **(cupos or {})}
    plan_limits = PLAN_LIMITS[plan]
    acceso = plan_limits["can_access"]
    if clave == "analisis":
        return semana["analyses_per_week"]
    if clave == "chat":
        return semana["chat_per_week"]
    if clave == "followups":
        return bool(acceso.get("ai.followup"))
    if clave == "brokers":
        return plan_limits["brokers_max"]
    if clave == "detectores":
        return plan_limits["behavioral_tags_visible"]
    if clave == "alertas":
        # El tope y el tipo van juntos: "hasta 3, sólo de precio objetivo" es
        # UNA cosa.
        return (plan_limits["alerts_max"], bool(acceso.get("alerts.pct_move")))
    if clave == "diagnostico":
        return semana["diag_dismiss_per_week"]
    if clave == "reportes":
        return bool(acceso.get("reportes.historicos"))
    if clave == "export":
        return bool(acceso.get("export.csv"))
    raise KeyError(clave)


def _da_mas(a, b) -> bool:
    """¿`a` da más que `b`? `None` es sin tope y le gana a cualquier número."""
    if isinstance(a, tuple):
        return any(_da_mas(x, y) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) and not bool(b)
    if a is None:
        return b is not None
    if b is None:
        return False
    return a > b


def _frase(clave: str, v, plan: str) -> Optional[str]:
    """El renglón que describe `v` (lo que `plan` da en `clave`), o None si
    con eso no hay nada que decir (un cupo en 0, un acceso que no está)."""
    if clave == "analisis":
        return f"**{v} análisis IA** por semana" if v else None
    if clave == "chat":
        if not v:
            return None
        cuantas = f"**{_n(v, 'consulta', 'consultas')} por semana** a Rendi AI"
        # Sin chat libre, esas consultas son sólo las preguntas guiadas: sin
        # aclararlo, "9 consultas" se lee como "preguntale lo que quieras".
        return cuantas if plan in _PREMIUM else f"{cuantas} con preguntas guiadas"
    if clave == "followups":
        return "**Follow-ups**: repreguntás sobre cualquier análisis" if v else None
    if clave == "brokers":
        if v is None:
            return "**Brokers ilimitados**"
        return f"Hasta **{_n(v, 'broker', 'brokers')}**" if v else None
    if clave == "detectores":
        if v is None:
            return "**Todos los detectores de comportamiento**"
        return f"**{_n(v, 'detector', 'detectores')} de comportamiento**" if v else None
    if clave == "alertas":
        tope, de_variacion = v
        if tope == 0:
            return None
        cuantas = ("**Alertas sin tope**" if tope is None
                   else f"Hasta **{_n(tope, 'alerta', 'alertas')}**")
        # Los dos tipos, con el nombre que tienen en la pantalla de Alertas:
        # "Precio objetivo" y "Variación %" (un activo que sube o baja X % —
        # `alerts_engine.py`). Decía "de % sobre tu cartera", que suena a la
        # cartera entera y no es lo que hace.
        return (f"{cuantas}: de precio objetivo y de variación %" if de_variacion
                else f"{cuantas} de precio objetivo")
    if clave == "diagnostico":
        if v is None:
            return "**Personalizar el diagnóstico sin límite**"
        return f"Personalizar el diagnóstico **{_n(v, 'vez', 'veces')} por semana**" if v else None
    if clave == "reportes":
        return "**Reportes históricos completos** (todos los meses)" if v else None
    if clave == "export":
        return "**Export CSV** consolidado para tu contador" if v else None
    raise KeyError(clave)


def _lo_que_queda(clave: str, v) -> Optional[str]:
    """Lo que le queda después, para el paréntesis del renglón que se pierde.

    Brokers y alertas se dicen distinto a propósito: son topes de CANTIDAD con
    "grandfather" (`plan.check_broker_quota`, `plan.check_alert_quota`) — lo que
    ya tiene no se borra, sólo no puede sumar más. "Vas a quedar con 1 broker"
    le hacía creer a quien tiene 3 que dos se iban a borrar."""
    if clave in ("analisis", "chat", "detectores"):
        return f"vas a quedar con {v}" if v else None
    if clave == "diagnostico":
        return f"vas a quedar con {_n(v, 'vez', 'veces')} por semana" if v else None
    if clave == "brokers":
        return f"en Free el tope es {v}; los que ya tenés no se borran" if v else None
    if clave == "alertas":
        tope, de_variacion = v
        if not tope:
            return None
        return (f"en Free el tope es {tope}"
                f"{'' if de_variacion else ', sólo de precio objetivo'}; "
                "las que ya tenés no se borran")
    return None      # accesos sí/no: se pierden enteros, no hay paréntesis


# ─── Lo que no es un número ─────────────────────────────────────────────────

# El Plan Asesor no es "un Pro más grande": es otra app (el libro, los clientes,
# la operación grupal). Sus cupos de IA son los de Pro, pero no son lo que
# compra, así que su lista es sólo esto.
_SIN_NUMEROS = {
    "pro": (
        "**Chat libre** con Rendi AI: preguntás lo que quieras, sin preguntas fijas",
        "**Respuestas con causalidad** y comparaciones",
    ),
    "advisor": (
        "**Tus clientes**, cada uno con su cartera, y el total que administrás",
        "Entrás a la cuenta de cada cliente **con visión Pro** (aunque él esté en Free)",
        "**Grupos** que se arman solos (por activo o por tamaño de cartera)",
        "**Operación grupal**: una compra para todo un grupo, con deshacer",
        "**Informes del período con tu marca** + brief diario de tu libro",
        '**Rendi AI sobre todo tu libro**: "¿a quiénes les pega esta noticia?"',
    ),
}

# En el aviso de vencimiento la app entera del asesor va en UN renglón; los
# seis de arriba describen qué es, no qué se pierde.
_SIN_NUMEROS_AL_PERDER = {
    "pro": (
        "**Chat libre** con Rendi AI",
        "**Respuestas con causalidad** y comparaciones",
    ),
    "advisor": (
        "**El panel de asesor**: tus clientes, los grupos, la operación grupal "
        "y los informes con tu marca",
        "**Chat libre** con Rendi AI",
        "**Respuestas con causalidad** y comparaciones",
    ),
}

# El orden de los renglones. Plus arranca por lo que lo define (los brokers y
# las métricas); el resto, por la IA.
# Los planes con chat libre y respuestas con causalidad: la misma regla que
# `is_premium` en main.py (admin no se vende).
_PREMIUM = ("pro", "advisor")

_ORDEN = ("analisis", "chat", "followups", "brokers", "detectores", "alertas",
          "diagnostico", "reportes", "export")
_ORDEN_PLUS = ("brokers", "detectores", "alertas", "diagnostico", "reportes",
               "export", "analisis", "chat", "followups")


def _orden(plan: str) -> tuple:
    return _ORDEN_PLUS if plan == "plus" else _ORDEN


# ─── Las dos listas ─────────────────────────────────────────────────────────

def incluye(plan: str) -> list[str]:
    """Todo lo que el plan da. Para los mails de bienvenida y de regalo."""
    renglones = list(_SIN_NUMEROS.get(plan, ()))
    if plan == "advisor":
        return renglones
    for clave in _orden(plan):
        frase = _frase(clave, _valor(clave, plan), plan)
        if frase:
            renglones.append(frase)
    return renglones


def se_pierde(plan: str, destino: str = PLAN_AL_VENCER) -> list[str]:
    """Lo que `plan` da y `destino` no, con lo que queda entre paréntesis.
    Para el aviso de vencimiento de quien vuelve a Free."""
    renglones = list(_SIN_NUMEROS_AL_PERDER.get(plan, ()))
    for clave in _orden(plan):
        tiene, queda = _valor(clave, plan), _valor(clave, destino)
        if not _da_mas(tiene, queda):
            continue
        frase = _frase(clave, tiene, plan)
        if not frase:
            continue
        resto = _lo_que_queda(clave, queda)
        renglones.append(f"{frase} ({resto})" if resto else frase)
    return renglones


# ─── Cómo se imprimen ───────────────────────────────────────────────────────

def a_html(renglones: list[str]) -> str:
    """Los renglones como <li>, con el tramo marcado en negrita."""
    return "".join(
        "\n        <li>"
        + re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(r, quote=False))
        + "</li>"
        for r in renglones
    ) + "\n    "


def a_texto(renglones: list[str]) -> str:
    """Los renglones como lista de texto plano, uno por línea."""
    return "\n".join(f"  · {r.replace('**', '')}" for r in renglones)
