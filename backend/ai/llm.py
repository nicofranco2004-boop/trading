"""llm — wrapper de Anthropic SDK con prompt caching + token tracking.
═══════════════════════════════════════════════════════════════════════════
Encapsula las llamadas al modelo. Convenciones:

  • Modelo por superficie (NO por tier):
      Chat (/api/ai/chat, todos los tiers) → MODEL_SONNET, lo elige main.ai_chat
      analyze() (análisis ✦ de pantalla, resumen de fundamentals) → Haiku
      analyze() del resumen del mercado por mail → MODEL_SONNET, effort
        "low" (lo elige market_brief.narrate; ahí está el porqué medido)
    Los precios de cada uno están en _PRICING_USD_PER_M, más abajo.

  • Prompt caching (TTL 1h, beta extended-cache-ttl-2025-04-11):
      System prompt va con cache_control={"type": "ephemeral", "ttl": "1h"}.
      Mismo system prompt (mismo tier + screen) en <1h → cache_read 90%
      más barato. El TTL 1h cuesta 2.0x el write pero, con >2 reads/hora,
      gana sobre el TTL default 5min (que cuesta 1.25x). Para Rendi a
      escala (107+ calls/hora a 3k Free users) el break-even es claro.
      CRÍTICO: el system prompt NUNCA debe tener timestamps / UUIDs /
      datos volátiles — eso invalida el cache silenciosamente. Para
      contexto dinámico, mandar en el user message.

  • Output forzado:
      Usamos client.messages.parse() con AnalysisResult (Pydantic).
      Si el modelo rompe el schema, levanta ValidationError → caller
      decide retry o fallback templated.

  • Token tracking:
      Devolvemos LLMResult con input/output tokens + cost_cents para
      auditar costos por user en ai_usage_daily.

"""

from __future__ import annotations
import os
import json
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("ai.llm")

# Modelo IDs canónicos del catálogo (no inventar — son los exactos)
MODEL_HAIKU = "claude-haiku-4-5"
# Sonnet 5.5: mismo precio que Sonnet 5 (US$2/$10) y cuenta el texto igual, así
# que la consulta cuesta lo mismo; es la versión nueva. Los anteriores quedan
# como referencia de precio para cualquier código viejo que todavía los nombre.
# OJO al cambiar de modelo: el que va acá TIENE que estar en la tabla de abajo.
# Un modelo que falta se cobra al más caro que conocemos (main._precio_por_millon)
# y el costo que se guarda en ai_usage_daily sale inflado sin que nada avise.
MODEL_SONNET = "claude-sonnet-5-5"
MODEL_SONNET_5 = "claude-sonnet-5"
MODEL_SONNET_46 = "claude-sonnet-4-6"

# Tarifas por modelo en USD por 1M tokens (catálogo al 2026-09-25).
# Cache reads ≈ 10% del input price. Cache writes ≈ 125% del input price.
_PRICING_USD_PER_M = {
    MODEL_HAIKU:     {"input": 1.00,  "output": 5.00},
    MODEL_SONNET:    {"input": 2.00,  "output": 10.00},
    MODEL_SONNET_5:  {"input": 2.00,  "output": 10.00},
    MODEL_SONNET_46: {"input": 3.00,  "output": 15.00},
}


@dataclass
class LLMResult:
    """Resultado de una llamada al modelo: output parseado + costos."""
    output: object               # AnalysisResult (Pydantic instance)
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd_cents: int          # entero (centavo de centavo redondeado)


def _calc_cost_cents(model: str, input_t: int, output_t: int,
                     cache_create_t: int, cache_read_t: int) -> int:
    """Costo de un call en centavos enteros. Refleja prompt caching:
        • input regular         → $X per 1M
        • cache_creation (1h)   → $X * 2.0 per 1M   (TTL extendido)
        • cache_read            → $X * 0.10 per 1M  (mismo para 5m/1h)
        • output                → $Y per 1M

    El multiplier 2.0 corresponde al TTL 1h. Si en algún punto usamos
    TTL default (5m), sería 1.25. Asumimos 1h porque es el único modo
    que activamos en analyze().
    """
    p = _PRICING_USD_PER_M.get(model)
    if not p:
        return 0
    in_price = p["input"] / 1_000_000
    out_price = p["output"] / 1_000_000
    total_usd = (
        input_t * in_price
        + cache_create_t * in_price * 2.0
        + cache_read_t * in_price * 0.10
        + output_t * out_price
    )
    return max(1, round(total_usd * 100 * 100))  # centavos de centavo (precision)


# Singleton state — inicializado al módulo, evita NameError + re-warnings.
_client = None
_client_init_attempted = False


def _get_anthropic_client():
    """Singleton del cliente Anthropic. Reuse para hit del prompt cache.

    Importante: si la API key no está, registramos warning UNA sola vez
    y retornamos None en las siguientes llamadas sin re-loguear ni
    re-importar el SDK."""
    global _client, _client_init_attempted
    if _client is not None:
        return _client
    if _client_init_attempted:
        # Ya intentamos antes y falló — no reintentar en cada call.
        return None
    _client_init_attempted = True
    try:
        from anthropic import Anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            log.warning("ANTHROPIC_API_KEY no configurada — AI deshabilitada")
            return None
        _client = Anthropic(api_key=api_key)
        return _client
    except ImportError:
        log.error("anthropic SDK no instalado — pip install anthropic")
        return None


def is_configured() -> bool:
    """True si tenemos cliente listo. El caller lo usa para devolver 503
    cuando AI no está habilitada (ej. dev sin .env)."""
    return _get_anthropic_client() is not None


def analyze(
    *,
    system_prompt: str,
    packet: dict,
    output_model,                # tipo Pydantic (ej. AnalysisResult)
    model: str = MODEL_HAIKU,
    # 2500 es el sweet spot: suficiente headroom para JSON estructurado
    # con 3 sections densas (~500 chars cada una) + tldr + follow_ups +
    # overhead del schema. Bajarlo más causa truncamiento del JSON y
    # ValidationError ("AI procesamiento fallo"). El prompt sigue
    # pidiendo concisión vía reglas explícitas, no vía max_tokens.
    max_tokens: int = 2500,
    max_retries: int = 1,
    followup_question: Optional[str] = None,
    descriptive: bool = False,
    instruction: Optional[str] = None,
    effort: Optional[str] = None,
) -> Optional[LLMResult]:
    """Manda el packet a Claude y devuelve output validado contra `output_model`.

    Args:
        system_prompt: prompt estable cacheado (sin timestamps/UUIDs).
        packet: dict con los números pre-calculados de la pantalla.
        output_model: subclass de pydantic.BaseModel (ej. AnalysisResult).
        model: MODEL_HAIKU por default (el chat NO pasa por acá: ver main.ai_chat).
        max_tokens: cap de output (narrativa breve, no necesita >2K).
        max_retries: si el LLM rompe el schema, reintentar N veces.
        followup_question: si viene, el LLM responde la pregunta puntual
            usando el mismo packet en lugar de generar el análisis general.
        descriptive: True para tiers Free/Plus (DESCRIBIR, no interpretar) —
            debe coincidir con el system prompt (ai.prompts.is_descriptive_tier).
        instruction: la orden del mensaje del usuario, para quien NO es el
            análisis ✦ de pantalla. Si no viene, el mensaje es el del análisis
            (interpretar, insight memorable, "sugiere") — ver abajo por qué
            eso no le sirve a nadie más.
        effort: cuánto razona el modelo antes de escribir ("low", "medium",
            "high"). Sólo para los modelos que lo aceptan (Sonnet 5.x); si no
            viene, el del modelo. En un resumen el razonamiento es casi todo el
            costo: Sonnet 5.5 en su nivel de fábrica gastaba ~2.500 tokens de
            salida por mail, de los que el texto eran ~500.

    Returns:
        LLMResult con .output validado, o None si AI no está configurada.

    Raises:
        pydantic.ValidationError: si tras retries el output sigue inválido.
    """
    client = _get_anthropic_client()
    if client is None:
        return None

    # Mensaje del user — si hay followup_question, el LLM responde la
    # pregunta puntual en lugar de generar análisis general.
    #
    # ⚠️ LOS DOS MENSAJES DE ABAJO (descriptivo e interpretativo) SON DEL
    # ANÁLISIS ✦ DE PANTALLA, no de "cualquier llamada". El resumen del mercado
    # por mail pasaba por acá sin `instruction` y recibía, debajo de su propio
    # prompt que dice "contás lo que pasó, nada de pronósticos", la orden
    # opuesta: "INTERPRETAR, no describir… un insight memorable… lenguaje
    # probabilístico ('sugiere')… densidad". El modelo obedecía a las dos y
    # salía jerga de analista: "apuestas de catalista más que de valuación",
    # "flujos de atención concentrados", "sugiriendo una tregua temporal".
    # Medido el 2026-09-30 sobre los titulares reales del día — ver
    # market_brief.narrate. Quien no sea el análisis de pantalla trae su orden.
    if instruction:
        user_msg = (
            f"{instruction}\n\n"
            f"```json\n{json.dumps(packet, sort_keys=True, ensure_ascii=False)}\n```"
        )
    elif followup_question:
        user_msg = (
            "El usuario ya leyó un análisis previo del mismo packet y ahora "
            "te pregunta puntualmente:\n\n"
            f"PREGUNTA: \"{followup_question}\"\n\n"
            "Tu trabajo: responder específicamente esa pregunta usando SOLO "
            "los datos del packet de abajo. Mantenete dentro del mismo schema "
            "(tldr + sections + follow_ups) pero adaptado a la pregunta:\n"
            "- tldr: respuesta directa en 1-2 frases.\n"
            "- sections: 2-3 bloques que profundicen la respuesta. NO repetir "
            "el análisis general — enfocate en la pregunta.\n"
            "- follow_ups: 0-1 preguntas relacionadas, NO la pregunta original.\n\n"
            "REGLAS:\n"
            "1. SOLO usar números/conceptos del packet. Cero invención.\n"
            "2. Si la pregunta NO se puede responder con el packet, decirlo "
            "claro (\"no tengo ese dato en este snapshot\") sin inventar.\n"
            "3. Lenguaje probabilístico, denso, sin frases vacías.\n\n"
            f"```json\n{json.dumps(packet, sort_keys=True, ensure_ascii=False)}\n```"
        )
    elif descriptive:
        # Tier Free/Plus — DESCRIBIR, no interpretar. ANTES este user_msg era
        # único y ordenaba "INTERPRETAR + insight memorable" a TODOS los tiers,
        # contradiciendo el system prompt descriptivo de Free/Plus ("DESCRIBIR,
        # no interpretar; nada de insights memorables, eso es Pro") → el modelo
        # recibía órdenes opuestas y se rompía la diferenciación del paywall.
        # sort_keys=True para que sea determinístico (cache).
        user_msg = (
            "Datos pre-calculados de la pantalla del usuario.\n\n"
            "Tu trabajo: DESCRIBIR en lenguaje claro y breve qué muestran los "
            "números del packet. Contá los hechos, no la lectura analítica: "
            "NO interpretar, NO causalidad, NO comparaciones extendidas, NO un "
            "insight memorable (eso es exclusivo del tier Pro).\n\n"
            "REGLAS:\n"
            "1. SOLO usar números/conceptos del packet. Cero invención.\n"
            "2. Lenguaje probabilístico donde aplique, sin afirmaciones "
            "absolutas.\n"
            "3. Sin frases vacías. Breve y directo.\n\n"
            f"```json\n{json.dumps(packet, sort_keys=True, ensure_ascii=False)}\n```"
        )
    else:
        # Tier Pro/Admin — packet serializado + instrucción interpretativa.
        # sort_keys=True para que sea determinístico (cache).
        user_msg = (
            "Datos pre-calculados de la pantalla del usuario.\n\n"
            "Tu trabajo: INTERPRETAR (no describir). Cada section debe agregar "
            "una capa de lectura — causalidad probable, comparación, lo que "
            "los números *significan* — no solo restatearlos. Una de las "
            "sections (idealmente la última) tiene que cargar un insight "
            "memorable, el tipo de observación que el user no podría sacar "
            "solo mirando el dashboard.\n\n"
            "REGLAS:\n"
            "1. SOLO usar números/conceptos del packet. Cero invención.\n"
            "2. Lenguaje probabilístico (\"sugiere\", \"es consistente con\"), "
            "no absoluto.\n"
            "3. Sin frases vacías ni juicios sin sustento.\n"
            "4. Densidad > verbosidad.\n\n"
            f"```json\n{json.dumps(packet, sort_keys=True, ensure_ascii=False)}\n```"
        )

    last_error = None
    last_raw_output = None
    for attempt in range(max_retries + 1):
        try:
            # client.messages.parse() valida automáticamente contra el
            # Pydantic model. Si el LLM no respeta el schema, levanta.
            # TTL extendido 1h: cache_control.ttl="1h" + beta header.
            # Trade-off: write paga 2.0x (vs 1.25x del default 5min) pero
            # reads en la siguiente hora pagan 0.10x. A 100+ users/hora
            # con mismo system prompt (mismo tier+screen) gana fácil.
            response = client.messages.parse(
                model=model,
                max_tokens=max_tokens,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral", "ttl": "1h"},
                }],
                messages=[{"role": "user", "content": user_msg}],
                output_format=output_model,
                extra_headers={"anthropic-beta": "extended-cache-ttl-2025-04-11"},
                **({"output_config": {"effort": effort}} if effort else {}),
            )
            # Capturar raw output ANTES de parsed_output — si parse falla, lo
            # necesitamos para diagnosticar.
            try:
                if response.content:
                    last_raw_output = "".join(
                        block.text for block in response.content
                        if hasattr(block, "text") and block.text
                    )[:2000]  # truncar a 2KB para no llenar logs
            except Exception:
                last_raw_output = "<failed to extract>"

            output = response.parsed_output
            if output is None:
                raise ValueError(
                    f"parsed_output is None — schema parse failed. "
                    f"stop_reason={getattr(response, 'stop_reason', '?')}, "
                    f"raw_first_500={last_raw_output[:500] if last_raw_output else 'empty'!r}"
                )

            u = response.usage
            return LLMResult(
                output=output,
                model=model,
                input_tokens=getattr(u, "input_tokens", 0) or 0,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
                cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                cost_usd_cents=_calc_cost_cents(
                    model,
                    getattr(u, "input_tokens", 0) or 0,
                    getattr(u, "output_tokens", 0) or 0,
                    getattr(u, "cache_creation_input_tokens", 0) or 0,
                    getattr(u, "cache_read_input_tokens", 0) or 0,
                ),
            )
        except Exception as ex:
            last_error = ex
            # Log con detalle del error — ValidationError genérico no nos dice
            # qué campo falló. ex.errors() de pydantic devuelve detalle por
            # field. Importante para diagnosticar truncamiento JSON vs schema
            # violations vs LLM hallucinating fields.
            error_detail = str(ex)
            try:
                if hasattr(ex, "errors") and callable(ex.errors):
                    error_detail = f"{type(ex).__name__}: {ex.errors()}"
            except Exception:
                pass
            log.warning(
                "AI parse fallo (intento %d/%d, model=%s): %s\nRAW OUTPUT (primeros 1500 chars): %s",
                attempt + 1, max_retries + 1, model, error_detail,
                last_raw_output[:1500] if last_raw_output else "<no raw output>",
            )
    # Tras retries, propaga el último error al caller
    raise last_error if last_error else RuntimeError("AI parse falló sin error")
