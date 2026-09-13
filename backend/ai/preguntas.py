"""preguntas — qué le pregunta el botón ✦ Analizar cuando lo tocás.
═══════════════════════════════════════════════════════════════════════════
El botón ✦ dejó de abrir un panel lateral. Ahora escribe una pregunta en el
chat flotante de Rendi, Rendi la contesta corta, y el usuario sigue la
conversación por donde quiera. Este archivo es LA pregunta de cada botón.

POR QUÉ LA PREGUNTA LA ESCRIBE EL SERVIDOR Y NO EL NAVEGADOR

Free y Plus no pueden escribirle a Rendi lo que se les ocurra: el chat les
acepta solamente las preguntas de una lista cerrada (`_FREE_QUESTIONS_
WHITELIST` en main.py). Es el candado que evita que alguien use el chat de
Rendi como si fuera ChatGPT gratis, y también evita que le manden a la IA un
texto preparado para engañarla.

Si la pregunta del botón la armara el navegador, habría que abrirle ese
candado al navegador — o sea, al usuario. Armándola acá, el navegador manda
sólo QUÉ botón tocó (`{screen, params}`); el texto que llega a la IA sale de
esta tabla, que el usuario no puede tocar. El candado no se abre: se agrega
una segunda llave, y esta llave la tiene el servidor.

QUÉ SE INTERPOLA Y QUÉ NO

Los datos que manda el navegador (el título de una noticia, el texto de una
observación) siguen llegando a la IA por donde ya llegaban: el packet que
arma el builder de cada análisis. Pero NO entran en la pregunta. En la
pregunta se interpolan sólo tres cosas, y las tres pasan por un filtro:

  · el activo   → se traduce a nombre con asset_names ("Nvidia", no "NVDA")
  · la categoría→ una de cinco, tabla cerrada
  · el mes      → se arma con dos números, no con texto

Todo lo demás sale del texto fijo de esta tabla.

CÓMO SE LEEN LAS ENTRADAS

Una sola frase → esa pregunta, siempre.
Un par de frases → la primera si vino el dato, la segunda si no vino. Que el
botón funcione igual sin el dato importa: `asset_name` devuelve None para
cualquier activo fuera del catálogo, y ahí "¿Cómo viene mi posición en None?"
sería peor que la versión genérica.

SI AGREGÁS UN ANÁLISIS NUEVO: `tests/test_ai_preguntas.py` compara esta tabla
contra el registro de análisis (`registry.REGISTRY`) y se pone ROJO si alguno
quedó sin pregunta. Un botón sin pregunta acá no abre nada.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple, Union

from .asset_names import asset_name

# ─── La tabla ────────────────────────────────────────────────────────────────
# Están escritas como las diría el usuario en voz alta, no como las nombra el
# producto: "¿Cómo viene mi cartera?" y no "análisis del dashboard". El que
# lee la respuesta tiene que reconocer su propia pregunta arriba.

PREGUNTAS: Dict[str, Union[str, Tuple[str, str]]] = {
    # ── Inicio y cartera ─────────────────────────────────────────────────
    "home": "¿Cómo vengo hoy?",
    "dashboard": "¿Cómo viene mi cartera?",
    "dashboard.composition": "¿Cómo está repartida mi cartera? ¿Estoy muy concentrado en algo?",
    "dashboard.evolution": "¿Cómo vino evolucionando mi cartera?",
    "dashboard.top_holdings": "¿Cuáles son mis posiciones más grandes y cuánto pesan?",
    "dashboard.brokers": "¿Cómo está repartida mi plata entre los brokers?",
    "dashboard.upcoming_events": "¿Qué se viene en los próximos días para lo que tengo?",
    "portfolio.distribution_type": "¿Cómo está repartida mi cartera por tipo de activo?",
    "portfolio.distribution_sector": "¿Cómo está repartida mi cartera por sector?",

    # ── Rendimiento ──────────────────────────────────────────────────────
    "insights": "¿Cómo me está yendo de verdad?",
    "insights.summary": "¿Cómo me está yendo de verdad?",
    "insights.evolution": "¿Cómo se movió mi cartera en este período?",
    "insights.drawdown": "¿Cuál fue mi peor caída y cuánto tardé en recuperarla?",
    "insights.attribution": "¿Qué activos explican mi resultado?",
    "insights.benchmarks": "¿Le estoy ganando al mercado y a la inflación?",
    "insights.observation": "Contame más de esto que encontraste.",
    "reports": "¿Cómo me fue en los últimos meses?",

    # ── Un mes / un período ──────────────────────────────────────────────
    "monthly": ("¿Cómo me fue en {mes}?", "¿Cómo me fue en ese período?"),
    "monthly.insight": ("¿Por qué pasó esto en {mes}?", "¿Por qué pasó esto?"),

    # ── Una posición ─────────────────────────────────────────────────────
    "position": ("¿Cómo viene mi posición en {activo}?", "¿Cómo viene esta posición?"),
    "position.chart": ("¿Cómo se movió {activo} y qué hice yo mientras tanto?",
                       "¿Cómo se movió este activo y qué hice yo mientras tanto?"),
    "position.lots": ("¿Cómo fui armando mi posición en {activo}?",
                      "¿Cómo fui armando esta posición?"),

    # ── Calidad de la empresa ────────────────────────────────────────────
    "fundamentals.category": ("¿Cómo está {activo} en {categoria}?",
                              "¿Cómo está esta empresa en esa parte?"),

    # ── Operaciones ──────────────────────────────────────────────────────
    "operations": "¿Cómo vengo operando?",
    "operations.trade": "¿Qué tal me salió esta operación?",

    # ── Novedades ────────────────────────────────────────────────────────
    "news": "¿Qué noticias de hoy me tocan a mí?",
    "news.item": ("¿Esta noticia me afecta en {activo}?", "¿Esta noticia me afecta?"),
    "events": "¿Qué eventos se vienen para lo que tengo?",
    "events.item": ("¿Qué significa este evento para mi posición en {activo}?",
                    "¿Qué significa este evento para mí?"),

    # ── Cómo opero (sesgos) ──────────────────────────────────────────────
    "behavioral": "¿Detectás algún sesgo en mi forma de operar?",
    "behavioral.card": "¿Qué significa esto sobre mi forma de operar?",

    # ── Perfil de inversor ───────────────────────────────────────────────
    "profile.summary": "¿Mi cartera se parece al inversor que dije que soy?",
    "profile.card": "¿Qué dice esto de mí como inversor?",

    # ── Métricas Pro ─────────────────────────────────────────────────────
    "metrics_pro.card": "¿Qué me está diciendo este número?",

    # ── Objetivos ────────────────────────────────────────────────────────
    "goal": "¿Cómo vengo con este objetivo?",

    # ── Libro del asesor ─────────────────────────────────────────────────
    # Estas dos no miran una cuenta: miran todas las carteras que administra
    # el asesor. Por eso hablan de "el libro" y no de "mi cartera".
    "book.composition_type": "¿Cómo está repartido mi libro por tipo de activo?",
    "book.composition_sector": "¿Cómo está repartido mi libro por sector?",
}


# ─── Los tres filtros ────────────────────────────────────────────────────────

# Las cinco dimensiones de Calidad de cartera, dichas como se leen en pantalla.
# Tabla cerrada: si mañana aparece una sexta y no está acá, la pregunta cae a
# la versión genérica en vez de meter en el prompt lo que haya mandado el
# navegador.
_CATEGORIAS = {
    "valuation": "el precio al que cotiza",
    "growth": "crecimiento",
    "profitability": "rentabilidad",
    "health": "salud financiera",
    "dividends": "dividendos",
}

_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio",
          "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def _activo(params: dict) -> Optional[str]:
    """El nombre del activo para decirlo en la pregunta, o None.

    None cuando el activo no está en el catálogo. Se cae a la versión
    genérica de la pregunta a propósito: el código pelado ("¿Cómo viene mi
    posición en AL30D?") lee peor que no nombrarlo, y un nombre inventado
    lee peor todavía.
    """
    ticker = params.get("asset") or params.get("ticker")
    return asset_name(ticker)


def _categoria(params: dict) -> Optional[str]:
    return _CATEGORIAS.get(str(params.get("category") or "").strip().lower())


def _mes(params: dict) -> Optional[str]:
    """"septiembre de 2026", o "2026" cuando el período es un año entero."""
    try:
        anio = int(params.get("year"))
    except (TypeError, ValueError):
        return None
    if not (2000 <= anio <= 2100):
        return None
    try:
        mes = int(params.get("month"))
    except (TypeError, ValueError):
        return str(anio)
    if not (1 <= mes <= 12):
        return str(anio)
    return "%s de %d" % (_MESES[mes - 1], anio)


def pregunta_de(screen: str, params: Optional[dict] = None) -> Optional[str]:
    """La pregunta que el botón ✦ escribe en el chat, o None si no existe.

    None significa "este análisis no tiene pregunta": el endpoint responde
    400 y el botón no manda nada. Preferimos eso a inventar una pregunta
    genérica, que le haría gastar una consulta al usuario para recibir algo
    que no era lo que tocó.
    """
    entrada = PREGUNTAS.get(str(screen or "").strip().lower())
    if entrada is None:
        return None
    if isinstance(entrada, str):
        return entrada

    con_dato, sin_dato = entrada
    p = params or {}
    datos = {}
    if "{activo}" in con_dato:
        datos["activo"] = _activo(p)
    if "{categoria}" in con_dato:
        datos["categoria"] = _categoria(p)
    if "{mes}" in con_dato:
        datos["mes"] = _mes(p)
    if any(v is None for v in datos.values()):
        return sin_dato
    return con_dato.format(**datos)
