"""Forma de la narración del resumen diario de mercado.

Vive acá y no adentro de `market_brief.py` porque `llm.analyze` valida el
output contra este modelo y el resto de los schemas de IA del repo viven bajo
`ai/`. El prompt que lo llena está en `market_brief._SYSTEM`.

Los topes son del schema a propósito: un modelo que se pasa de largo rompe la
validación y el mail no sale, que es preferible a un mail de dos pantallas.
Ojo con el aprendizaje ya medido en este repo: **el tope de palabras no es la
palanca** que acorta de verdad (bajar 80→60 movió la mediana 94→87 y nada más).
Lo que acorta es no repetir números que ya están en otra parte del mail y pedir
un tope POR ORACIÓN — las dos cosas están en el prompt.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class MarketNarrative(BaseModel):
    """Lo que el modelo escribe. Nada de esto toca números de la cartera: los
    datos propios de la persona (qué cobra hoy, qué balance sale) los arma el
    código y viajan aparte."""

    # ⚠️ 110 y no 90: con Sonnet los titulares de 12 palabras llegaban a 83-95
    # letras, y uno que se pasa dos veces es un mail que NO sale (el reintento
    # de `llm.analyze` no le dice al modelo qué falló). El largo se pide en el
    # prompt; este tope es la red, no la regla.
    titular: str = Field(
        ...,
        max_length=110,
        description="Una oración con lo que mandó hoy. Máximo 10 palabras.",
    )
    # ⚠️ 4 y no 3, por lo mismo que el titular: con Sonnet y las reglas de
    # explicar cada término, 5 de 16 respuestas vinieron con 4 párrafos y una
    # se pasó en los dos intentos → ese mail no salía. El largo total era el de
    # siempre (~260 palabras): lo que cambiaba era dónde ponía el punto y aparte.
    mercado: List[str] = Field(
        ...,
        min_length=1,
        max_length=4,
        description="2-3 párrafos: qué pasó afuera y en Argentina.",
    )
    tu_cartera: List[str] = Field(
        default_factory=list,
        max_length=2,
        description=(
            "0-2 párrafos sobre los activos que tiene. Vacío si no hubo "
            "noticias de sus activos — no se rellena."
        ),
    )
