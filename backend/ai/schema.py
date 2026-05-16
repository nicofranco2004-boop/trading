"""schema — Pydantic models del output de IA estructurado.
═══════════════════════════════════════════════════════════════════════════
Forzamos al LLM a devolver un shape fijo. Si el LLM rompe el schema, el
SDK levanta ValidationError y el caller decide retry o fallback templated.

Estructura del output:
  {
    "tldr": "1-2 frases con la conclusión más importante",
    "sections": [
      { "title": str, "body": str (2-4 frases), "tone": Tone }
    ],
    "follow_ups": [str]  // 0-3 chips
  }

Tone se mapea visualmente en el frontend:
  • neutral  → text-ink-0
  • positive → text-rendi-pos
  • negative → text-rendi-neg
  • warning  → text-rendi-warn
"""

from __future__ import annotations
from typing import List, Literal
from pydantic import BaseModel, Field


Tone = Literal["neutral", "positive", "negative", "warning"]


class AnalysisSection(BaseModel):
    """Bloque dentro del análisis. Frontend lo renderiza con eyebrow mono
    caps + body, color según tone. Una section es UNA idea con cuerpo
    interpretativo — no un bullet, no un resumen."""

    title: str = Field(
        ...,
        description=(
            "Frase noun-phrase corta (3-6 palabras) en español. Sin punto "
            "final, sin signos de pregunta. Ejemplos: 'Dinámica reciente', "
            "'Factores impulsores', 'Riesgo asimétrico', 'Insight clave'."
        ),
        max_length=80,
    )
    body: str = Field(
        ...,
        description=(
            "Cuerpo interpretativo en español rioplatense. 2-4 oraciones "
            "densas. INTERPRETAR (no describir) los datos del packet: "
            "conectar métricas, sugerir causalidad probabilística, "
            "comparar vs benchmark/histórico/composición. Solo afirmar "
            "cosas presentes en el packet."
        ),
        max_length=800,
    )
    tone: Tone = Field(
        "neutral",
        description=(
            "neutral (default — observación contextual), positive (patrón "
            "sano o outperform sustentado), negative (pérdida material o "
            "riesgo activado), warning (asimetría / sesgo / concentración)."
        ),
    )


class AnalysisResult(BaseModel):
    """Output forzado del LLM. Estructura tipo research note: tldr
    interpretativo, 3-5 sections estructuradas, follow_ups sustantivos."""

    tldr: str = Field(
        ...,
        description=(
            "1-2 frases con la observación interpretativa más importante. "
            "ARRANCA con la observación (no con 'tu portfolio' ni 'el "
            "análisis muestra'). Que sea afirmación contextual, no "
            "resumen descriptivo de métricas."
        ),
        max_length=360,
    )
    sections: List[AnalysisSection] = Field(
        ...,
        description=(
            "3-5 secciones tipo research note. Orden típico (adaptable): "
            "dinámica → factores probables → lectura comparativa → riesgo "
            "actual → insight clave / cambio de proceso. La última section "
            "idealmente lleva el insight memorable, no un cierre genérico."
        ),
        min_length=1,
        max_length=5,
    )
    follow_ups: List[str] = Field(
        default_factory=list,
        description=(
            "0-3 preguntas SUSTANTIVAS — cosas que el user no se "
            "preguntaría sin haber leído el análisis. Evitá obvias "
            "('¿qué hago?', '¿está bien?')."
        ),
        max_length=3,
    )

    model_config = {"json_schema_extra": {"additionalProperties": False}}
