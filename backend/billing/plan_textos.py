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
módulo. El 2026-10-15 se revierte el commit «[15-10]» (Plus: 2 análisis, los 12
detectores, alertas sin tope) y los mails acompañan solos.

LO QUE ES DE TODOS NO SE VENDE. El diagnóstico completo y la distribución por
activo son de todos los planes (decisión de producto del 2026-09-26): estaban
declarados como topes (`insights_diagnostic_visible`,
`insights.distribucion_activo`) que ninguna pantalla aplicaba, y los mails
viejos los prometían como si fueran del plan pago. Se sacaron de la tabla (ver
`ai/plan.py`); lo que sí se limita del diagnóstico es el "No me interesa"
(`diag_dismiss_per_week`), y eso sí se dice.

Lo que no es un número (el chat libre, las respuestas con causalidad, el panel
del asesor) no está en esas tablas: el chat libre y el modo research-note se
deciden por tier en `main.py` (`is_premium`), y el panel del asesor en
`_require_advisor`. Va escrito a mano en `_SIN_NUMEROS` (y `_PREMIUM` dice
quién tiene chat libre), y ahí no hay cifras.

Formato: cada renglón es un string con el tramo a resaltar entre `**`. El HTML
lo vuelve <b> y el texto plano lo saca, así las dos versiones del mail dicen lo
mismo por construcción.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Optional

from ai.plan import PLAN_LIMITS, PLANES_EN_VENTA
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

    Existe por los que ya pagaban Plus: desde el 2026-10-15 (se revierte el
    commit «[15-10]») a ellos se les respeta el cupo viejo de análisis
    (`quota.limites_del_usuario`, que `get_current_usage` consulta). Un mail
    que leyera sólo `LIMITS[plan]` le diría a esa persona el número del plan,
    no el suyo — justo en el aviso de vencimiento, que es a quien le puede
    llegar si cancela con la suba de precio.

    None si no se puede leer: el mail sale igual, con los cupos del plan."""
    try:
        from ai import quota
        return cupos_de_uso(quota.get_current_usage(conn, user_id, tier_override=plan), plan)
    except Exception as ex:
        log.warning("cupos de uid=%s en %s: no se pudieron leer (%s); el mail "
                    "va con los del plan", user_id, plan, ex)
        return None


# El nombre de cada cupo en `quota.get_current_usage` → su nombre en LIMITS.
_CUPOS_DEL_USO = {"analyses_per_week": "analyses_limit",
                  "chat_per_week": "chat_limit",
                  "diag_dismiss_per_week": "diag_dismiss_limit",
                  "listens_per_week": "listens_limit"}


def cupos_de_uso(usage: Optional[dict], plan: str) -> Optional[dict]:
    """Los cupos de un `usage` (el de `quota.get_current_usage`) con las claves
    de LIMITS, para pasarle a `_valor`. UNA sola traducción: la usan los mails
    (`cupos_del_usuario`) y los carteles de upgrade, que ya reciben el `usage`
    del endpoint — el mismo número que el 429 le muestra a la persona.

    None si el `usage` es de OTRO plan (con la lente del asesor se mide con el
    tope de 'pro') o no vino: entonces valen los del plan."""
    if not usage or usage.get("tier") != plan:
        return None
    return {k: usage[v] for k, v in _CUPOS_DEL_USO.items() if v in usage}


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
    if clave == "voz":
        # OJO: acá None NO es "sin tope" sino "no tiene cupo propio: cada audio
        # le cuesta una consulta" (ver `quota.listen_limit`).
        return semana.get("listens_per_week")
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


def _frase(clave: str, v, plan: Optional[str] = None) -> Optional[str]:
    """El renglón que describe `v` (lo que `plan` da en `clave`), o None si
    con eso no hay nada que decir (un cupo en 0, un acceso que no está).
    Sin `plan` no se agrega la aclaración de las preguntas guiadas."""
    if clave == "analisis":
        return f"**{v} análisis IA** por semana" if v else None
    if clave == "chat":
        if not v:
            return None
        cuantas = f"**{_n(v, 'consulta', 'consultas')} por semana** a Mervall-E AI"
        # Sin chat libre, esas consultas son sólo las preguntas guiadas: sin
        # aclararlo, "9 consultas" se lee como "preguntale lo que quieras".
        if plan is None or plan in _PREMIUM:
            return cuantas
        return f"{cuantas} con preguntas guiadas"
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
        "**Chat libre** con Mervall-E AI: preguntás lo que quieras, sin preguntas fijas",
        "**Respuestas con causalidad** y comparaciones",
    ),
    "advisor": (
        "**Tus clientes**, cada uno con su cartera, y el total que administrás",
        "Entrás a la cuenta de cada cliente **con visión Pro** (aunque él esté en Free)",
        "**Grupos** que se arman solos (por activo o por tamaño de cartera)",
        "**Operación grupal**: una compra para todo un grupo, con deshacer",
        "**Informes del período con tu marca** + brief diario de tu libro",
        '**Mervall-E AI sobre todo tu libro**: "¿a quiénes les pega esta noticia?"',
    ),
}

# En el aviso de vencimiento la app entera del asesor va en UN renglón; los
# seis de arriba describen qué es, no qué se pierde.
_SIN_NUMEROS_AL_PERDER = {
    "pro": (
        "**Chat libre** con Mervall-E AI",
        "**Respuestas con causalidad** y comparaciones",
    ),
    "advisor": (
        "**El panel de asesor**: tus clientes, los grupos, la operación grupal "
        "y los informes con tu marca",
        "**Chat libre** con Mervall-E AI",
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

def incluye(plan: str, cupos: Optional[dict] = None) -> list[str]:
    """Todo lo que el plan da. Para los mails de bienvenida y de regalo.
    `cupos`: los de la persona (`cupos_del_usuario`), si difieren del plan."""
    renglones = list(_SIN_NUMEROS.get(plan, ()))
    if plan == "advisor":
        return renglones
    for clave in _orden(plan):
        frase = _frase(clave, _valor(clave, plan, cupos), plan)
        if frase:
            renglones.append(frase)
    return renglones


def se_pierde(plan: str, cupos: Optional[dict] = None) -> list[str]:
    """Lo que `plan` da y Free no, con lo que queda entre paréntesis. Para el
    aviso de vencimiento de quien vuelve a Free. `cupos`: los de la persona
    (`cupos_del_usuario`), si difieren del plan.

    No recibe "a qué plan cae": los paréntesis dicen "en Free" y aceptar otro
    destino era prometer una cuenta que el texto no hacía."""
    renglones = list(_SIN_NUMEROS_AL_PERDER.get(plan, ()))
    for clave in _orden(plan):
        tiene = _valor(clave, plan, cupos)
        queda = _valor(clave, PLAN_AL_VENCER)
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


# ═══ Los carteles de upgrade ════════════════════════════════════════════════
# Los 403/429 de `main.py` traen `upgrade.benefits`: la lista que el frontend
# muestra cuando alguien choca con un tope (UpgradePromoCard, UpgradeModal).
# Estaba escrita a mano en diez lugares y mentía igual que los mails:
#
#   · "10× más análisis IA (60/sem vs 6/sem)" también a un Free, que tiene 1
#     (son 60×) — y desde el 15/10, con el Plus en 2, tampoco contra Plus;
#   · "Diagnóstico completo + 4 detectores" para vender Plus: el Plus ve 6, y
#     el diagnóstico completo ya lo ve el Free;
#   · "Distribución por activo" y "AI Hub (próximamente)": la primera ya es de
#     todos y la segunda no existe;
#   · la voz le mostraba la lista del Plus aunque el cartel ofreciera Pro.
#
# LA REGLA: un cartel dice lo que el plan DESTINO da y el plan de ORIGEN no, con
# los números de las mismas dos tablas que los mails. Lo que el destino no
# mejora no se nombra: el 15/10 "comportamiento completo" deja de separar al
# Pro del Plus y ese día se cae solo de la lista. El guard es
# `tests/test_carteles_vs_limites.py`.

NOMBRE = {"free": "Free", "plus": "Plus", "pro": "Pro", "advisor": "Asesor",
          "admin": "Admin"}


def nombre(plan: str) -> str:
    """"plus" → "Plus". Estaba escrito dos veces en main.py, y sin el asesor:
    un Asesor que agotaba su cupo leía "Llegaste al límite del plan Free"."""
    return NOMBRE.get(plan, str(plan).capitalize())


# El cupo que la persona TIENE puede no ser el de la tabla: desde el 15/10 a los
# que ya pagaban Plus se les respeta el cupo de antes
# (`quota.limites_del_usuario`), y el 429 les muestra ESE número ("usaste 6 de
# 6"). El cartel compara contra lo que la persona ve arriba: el origen se lee
# con `cupos_de_uso(usage, origen)`, igual que en los mails.


def _veces(a, b) -> Optional[int]:
    """a/b cuando es EXACTO y mayor que 1. Con 40 contra 9 no hay múltiplo que
    decir: "4× más" sería redondear una promesa, así que se dicen los dos
    números y nada más."""
    if not a or not b or a % b:
        return None
    return a // b if a // b > 1 else None


def _mas_de(cosa: str, a, b) -> str:
    veces = _veces(a, b)
    if veces:
        return f"{veces}× más {cosa} ({a}/sem vs {b}/sem)"
    return f"Más {cosa} ({a}/sem vs {b}/sem)"


def _pasa_a_interpretar(origen: str, destino: str) -> bool:
    """¿El destino tiene chat libre y respuestas con causalidad y el origen no?
    No es un número de las tablas: es `_PREMIUM`, la misma regla que usan los
    mails para aclarar "con preguntas guiadas"."""
    return origen not in _PREMIUM and destino in _PREMIUM


# Lo que no es un número, y por eso va escrito: sólo se dice cuando
# `_pasa_a_interpretar` (el mismo criterio que `_SIN_NUMEROS` de los mails).
_SIN_NUMEROS_CARTEL = {
    "chat_libre": "Chat libre con Mervall-E AI: preguntá lo que quieras",
    "causalidad": "Respuestas con causalidad y comparaciones",
    "causalidad_memoria": "Respuestas con causalidad y memoria persistente",
}


def _mejora(clave: str, origen: str, destino: str, usage: Optional[dict] = None,
            guiadas: Optional[int] = None) -> Optional[str]:
    """El renglón de lo que `destino` da y `origen` no, o None si en `clave` el
    destino no da más — y entonces no se vende."""
    de = nombre(origen)
    cupos = cupos_de_uso(usage, origen)
    if clave in _SIN_NUMEROS_CARTEL:
        return _SIN_NUMEROS_CARTEL[clave] if _pasa_a_interpretar(origen, destino) else None
    if clave == "reportes_export":
        reportes = _mejora("reportes", origen, destino)
        export = _mejora("export", origen, destino)
        if reportes and export:
            return "Reportes históricos + Export CSV"
        return reportes or export
    if clave == "voz":
        return _mejora_voz(origen, destino, usage)
    if clave == "chat_cupo":
        a, b = _valor("chat", destino), _valor("chat", origen, cupos)
        if not (_pasa_a_interpretar(origen, destino) and _da_mas(a, b)):
            return None
        entre = f", eligiendo entre {guiadas} preguntas guiadas" if guiadas else ""
        return f"{a} consultas por semana sobre lo que quieras (en {de}: {b}{entre})"

    a, b = _valor(clave, destino), _valor(clave, origen, cupos)
    if not _da_mas(a, b):
        return None
    if clave == "analisis":
        return _mas_de("análisis IA", a, b)
    if clave == "chat":
        if _pasa_a_interpretar(origen, destino):
            return f"Chat libre con Mervall-E AI ({a} consultas/sem vs {_n(b, 'guiada', 'guiadas')})"
        return _mas_de("consultas a Mervall-E AI", a, b)
    if clave == "brokers":
        cuantos = "Brokers ilimitados" if a is None else f"Hasta {_n(a, 'broker', 'brokers')}"
        return f"{cuantos} (vs {b} en {de})"
    if clave == "detectores":
        cuantos = ("Todos los detectores de comportamiento" if a is None
                   else f"{_n(a, 'detector', 'detectores')} de comportamiento")
        return f"{cuantos} (vs {b} en {de})"
    if clave == "alertas":
        (a_tope, a_pct), (b_tope, b_pct) = a, b
        cuantas = ("Alertas sin tope" if a_tope is None
                   else f"Hasta {_n(a_tope, 'alerta', 'alertas')}")
        # Los tipos con el nombre de la pantalla de Alertas, igual que los
        # mails: "precio objetivo" y "variación %".
        tipo = ", también de variación %" if a_pct and not b_pct else ""
        if b_tope is None:
            return f"{cuantas}{tipo}"
        return (f"{cuantas}{tipo} "
                f"(vs {b_tope} en {de}{'' if b_pct else ', sólo de precio objetivo'})")
    if clave == "diagnostico":
        cuanto = "sin límite" if a is None else f"{_n(a, 'vez', 'veces')} por semana"
        return (f"Personalizá tu diagnóstico {cuanto} "
                f"(en {de}, {_n(b, 'vez', 'veces')} por semana)")
    if clave == "followups":
        return "Follow-ups: repreguntá sobre cualquier análisis"
    if clave == "reportes":
        return "Reportes históricos completos (todos los meses)"
    if clave == "export":
        return "Export CSV consolidado para tu contador"
    raise KeyError(clave)


def _mejora_voz(origen: str, destino: str, usage: Optional[dict] = None) -> Optional[str]:
    """La voz se cobra de dos maneras (ver `quota.reserve_listen`): con cupo
    PROPIO de audios (Free, que si no nunca podría escuchar su única consulta)
    o sin cupo propio, pagando cada audio con 1 consulta (los planes pagos).

    El cartel viejo decía "Hasta 4 respuestas habladas por semana": 4 = 9
    consultas / 2, escrito a mano. Y ni siquiera es el tope real — las
    respuestas del botón ✦ salen del cupo de análisis y también se escuchan.
    Se dice la regla, que es exacta, en vez de un tope que no lo es."""
    cupos = cupos_de_uso(usage, origen)
    propio_destino = _valor("voz", destino)
    propio_origen = _valor("voz", origen, cupos)
    consultas = _valor("chat", destino)
    if propio_destino is not None:
        if propio_origen is not None and propio_destino <= propio_origen:
            return None
        antes = (f" (en {nombre(origen)}, {propio_origen})"
                 if propio_origen is not None else "")
        return (f"Hasta {_n(propio_destino, 'respuesta hablada', 'respuestas habladas')} "
                f"por semana{antes}")
    if propio_origen is not None:
        if not consultas or consultas <= propio_origen:
            return None
        antes = f"en {nombre(origen)}, {_n(propio_origen, 'audio', 'audios')} por semana"
    else:
        consultas_origen = _valor("chat", origen, cupos)
        if not _da_mas(consultas, consultas_origen):
            return None
        antes = f"vs {consultas_origen} en {nombre(origen)}"
    return (f"Más respuestas habladas: cada audio usa 1 de las {consultas} "
            f"consultas por semana ({antes})")


# Qué vende cada cartel, en orden: la primera clave contesta el tope que se tocó
# y el resto es lo que el cartel viejo ofrecía, con reemplazos para cuando algo
# deja de separar a los dos planes. Se dicen las primeras TOPE_DEL_CARTEL que el
# destino da de verdad. (motivo, destino) → claves.
_CARTELES = {
    ("brokers", "pro"): ("brokers", "analisis", "detectores", "reportes", "chat",
                         "followups"),
    ("export", "plus"): ("export", "brokers", "reportes", "detectores", "alertas",
                         "diagnostico"),
    ("followups", "pro"): ("followups", "analisis", "causalidad", "chat", "brokers"),
    ("analisis", "pro"): ("analisis", "causalidad", "chat", "followups", "brokers"),
    # El botón ✦ del chat de un Free: su 429 ofrece Plus (ver _chat_quota_429).
    ("analisis", "plus"): ("analisis", "chat", "brokers", "reportes_export",
                           "detectores"),
    ("chat", "plus"): ("chat", "brokers", "reportes_export", "detectores",
                       "diagnostico", "alertas"),
    ("chat", "pro"): ("chat", "analisis", "causalidad_memoria", "brokers",
                      "detectores", "followups"),
    ("diagnostico", "plus"): ("diagnostico", "brokers", "reportes_export", "chat",
                              "detectores"),
    ("chat_libre", "pro"): ("chat_libre", "chat_cupo", "causalidad_memoria",
                            "analisis", "brokers"),
    ("voz", "plus"): ("voz", "brokers", "reportes_export", "detectores",
                      "diagnostico"),
    # "Probá Pro" para el que ya paga Plus (TrialCta): no lo dispara un tope,
    # así que arranca por lo que más separa a los dos planes. Tenía la lista
    # escrita en la pantalla: "60 análisis por semana en vez de 6" y "los 12
    # detectores", que el 15/10 dejan de ser ciertos contra el Plus.
    ("prueba_pro", "pro"): ("chat", "analisis", "brokers", "detectores",
                            "causalidad_memoria", "followups"),
}
# Para una combinación que hoy no existe (p. ej. la voz ofreciendo Pro): el
# motivo primero y después lo que haya.
_RESTO = ("analisis", "chat", "causalidad", "brokers", "detectores",
          "reportes_export", "alertas", "diagnostico", "followups")
TOPE_DEL_CARTEL = 4


def cartel(motivo: str, origen: str, destino: str, *, usage: Optional[dict] = None,
           guiadas: Optional[int] = None) -> list[str]:
    """Los beneficios de pasarse de `origen` a `destino`, para `upgrade.benefits`.

    `motivo`: el tope que se tocó ("brokers", "export", "followups",
    "analisis", "chat", "diagnostico", "chat_libre", "voz"), que va primero;
    o "prueba_pro", la oferta de probar Pro que se le hace al que paga Plus.
    `usage`: el de `quota.get_current_usage`, para comparar contra el cupo que
    la persona tiene y no contra el de la tabla (ver `cupos_de_uso`).
    `guiadas`: cuántas preguntas guiadas hay, para el cartel del chat libre.
    Vive en main.py (`_FREE_QUESTIONS_WHITELIST`) y este módulo no lo importa."""
    claves = _CARTELES.get((motivo, destino)) or ((motivo,) + _RESTO)
    renglones: list[str] = []
    for clave in claves:
        renglon = _mejora(clave, origen, destino, usage, guiadas)
        if renglon and renglon not in renglones:
            renglones.append(renglon)
        if len(renglones) == TOPE_DEL_CARTEL:
            break
    return renglones


def resuelve(motivo: str, origen: str, destino: str, usage: Optional[dict] = None) -> bool:
    """¿El destino da más en lo que se tocó? Si no, ofrecerlo es vender algo
    que no arregla el problema de la persona."""
    return _mejora(motivo, origen, destino, usage) is not None


# ─── Las frases de los carteles que llevan números ──────────────────────────

def aviso_brokers(origen: str, destino: str) -> str:
    """El `error` del 403 de brokers. Decía "El plan Free permite 1 broker"
    también al Plus que llegaba a 3 (y el frontend lo muestra de título)."""
    tope, hasta = _valor("brokers", origen), _valor("brokers", destino)
    para = ("conectar todos tus brokers" if hasta is None
            else f"conectar hasta {_n(hasta, 'broker', 'brokers')}")
    return (f"El plan {nombre(origen)} permite {_n(tope, 'broker', 'brokers')}. "
            f"Pasate a Rendi {nombre(destino)} para {para}.")


def aviso_export() -> str:
    """"Export CSV está disponible en los planes Plus y Pro." — los que lo dan."""
    planes = [nombre(p) for p in PLANES_EN_VENTA if _valor("export", p)]
    if len(planes) == 1:
        return f"Export CSV está disponible en el plan {planes[0]}."
    return f"Export CSV está disponible en los planes {', '.join(planes[:-1])} y {planes[-1]}."


def mas_analisis(origen: str, destino: str, usage: Optional[dict] = None) -> str:
    """El remate del 429 de análisis. Decía "Para 10× más análisis" a todos."""
    a, b = _valor("analisis", destino), _valor("analisis", origen, cupos_de_uso(usage, origen))
    veces = _veces(a, b)
    cuanto = f"{veces}× más análisis" if veces else f"más análisis ({a} por semana)"
    return f"Para {cuanto} con respuestas profundas, pasate a Rendi {nombre(destino)}."


def aviso_diagnostico(destino: str) -> str:
    """El remate del 429 del "No me interesa": "o pasate a Plus y descartá sin
    límite" era cierto por la tabla, no por construcción."""
    a = _valor("diagnostico", destino)
    cuanto = "sin límite" if a is None else f"hasta {_n(a, 'vez', 'veces')} por semana"
    return f"o pasate a {nombre(destino)} y descartá {cuanto}"
