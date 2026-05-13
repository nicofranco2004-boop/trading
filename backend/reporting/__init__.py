"""Módulo de reportes — timeline temporal de la performance del portfolio.

Subdivisiones:
- `schema`: dataclasses puras (Insight, Highlight, PeriodReport, etc.)
- `builder`: funciones puras que construyen un PeriodReport a partir de DB.
- `detectors`: motor de reglas que genera Insights.
- `timeline`: composición de PeriodReports en una vista cronológica.

Diseño: pure functions, no estado global. Cada función recibe `conn` y datos,
devuelve structs. Sin mutaciones. Hace que los tests sean triviales y permite
re-renderizar sin riesgo de side-effects.
"""
