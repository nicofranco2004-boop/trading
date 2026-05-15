"""builders — context packet builders por screen.
═══════════════════════════════════════════════════════════════════════════
Cada submódulo expone una función `build(conn, user_id, **kwargs)` que
devuelve un dict (~500 tokens) con los números pre-calculados de esa
pantalla. El LLM recibe ese dict y NARRA.

Dispatch:
  router.py recibe POST /api/ai/analyze { screen, params } y llama al
  builder correspondiente:
    'dashboard'   → builders.dashboard.build(conn, uid, period='30d')
    'position'    → builders.position.build(conn, uid, position_id=N)
    'behavioral'  → builders.behavioral.build(conn, uid)
    'monthly'     → builders.monthly.build(conn, uid, year, month)

Regla:
  • El packet es JSON serializable (números, strings, booleanos, listas).
  • Sin objetos Pydantic, sin datetimes — strings ISO.
  • Solo lo importante (~10-15 campos). Si crece más, parte en sub-packets.
  • Determinista: misma data → mismo packet → mismo cache hit.
"""
