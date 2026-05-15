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
    """Un bloque dentro del análisis. Frontend lo renderiza con eyebrow mono
    caps + body, con color según tone."""

    title: str = Field(
        ...,
        description="Título corto en español (3-6 palabras). Sin punto final.",
        max_length=80,
    )
    body: str = Field(
        ...,
        description=(
            "Cuerpo del análisis en español rioplatense. 2-4 frases. "
            "Solo afirmá cosas que están en el packet — no inventes números."
        ),
        max_length=600,
    )
    tone: Tone = Field(
        "neutral",
        description=(
            "neutral (default), positive (logro o patrón sano), "
            "negative (pérdida o sesgo problemático), "
            "warning (cuidado, foco accionable)."
        ),
    )


class AnalysisResult(BaseModel):
    """Output forzado del LLM para cualquier 'Analizar' contextual."""

    tldr: str = Field(
        ...,
        description=(
            "1-2 frases con la conclusión más importante. "
            "Lo primero que el user lee — sin preámbulo, sin '¡Hola!'."
        ),
        max_length=300,
    )
    sections: List[AnalysisSection] = Field(
        ...,
        description=(
            "2-4 secciones que profundizan la conclusión. "
            "Orden: qué pasó → qué lo explica → qué hacer / qué mirar."
        ),
        min_length=1,
        max_length=4,
    )
    follow_ups: List[str] = Field(
        default_factory=list,
        description=(
            "0-3 preguntas cortas que el user podría querer profundizar. "
            "Cada una es un chip clickeable. Ejemplos: "
            "'¿Por qué META cayó?', '¿Cómo voy vs S&P 500?'."
        ),
        max_length=3,
    )

    model_config = {"json_schema_extra": {"additionalProperties": False}}
