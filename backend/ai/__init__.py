"""AI v2 — capa de inteligencia contextual integrada al producto.
═══════════════════════════════════════════════════════════════════════════
Arquitectura (Sprint AI v2, RND-AUDIT-004):

  Frontend → POST /api/ai/analyze { screen, params }
       │
       ▼
  ContextPacketBuilder (por screen)
       │ paquete JSON ~500 tokens estructurado
       ▼
  Cache (SQLite, TTL 24h, key = sha256(packet_json))
       │ HIT → return cached
       │ MISS ↓
       ▼
  LLMRouter (Anthropic prompt caching ON)
       │ system prompt cacheado (estable)
       │ output schema JSON forzado
       ▼
  result_json → set_cached → return

Principio central:
  • Rendi CALCULA (todo determinístico, en builder)
  • Claude NARRA (recibe números, devuelve texto estructurado)

Submódulos:
  • llm.py     — wrapper Anthropic + prompt caching + token tracking
  • cache.py   — capa de cache SQLite con TTL
  • quota.py   — Free vs Pro quotas
  • schema.py  — Pydantic models del output (validador)
  • prompts.py — system prompts cacheables
  • builders/  — context packet builder por screen
"""
