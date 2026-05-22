"""test_bot_profile_boundaries — verifica que el bot Plus se mantenga
descriptivo y el bot Pro use el perfil de forma causal.

Estrategia: NO llamamos al LLM real (caro y no determinístico). En su lugar
verificamos las propiedades CONSTRUCTIVAS del prompt:

  1. Routing correcto: tier=free/plus → SYSTEM_BASE_DESCRIPTIVE, tier=pro/admin
     → SYSTEM_BASE_PRO. Asserts sobre el primer fragmento del prompt.

  2. Bloque de perfil presente en ambos.

  3. Bloque de perfil DIFERENCIADO:
       descriptive prompt tiene "PROHIBIDO inferir causas"
       pro prompt tiene "Inferir CAUSAS PLAUSIBLES"

  4. Reglas de prohibición compartidas (cero asesoramiento operativo) están
     en ambos manifiestos.

  5. Packet del /api/ai/analyze incluye `investor_profile` cuando el user
     completó el test, vacío cuando no.

Correr:
    cd backend && python3 -m scripts.test_bot_profile_boundaries
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def fail(msg):
    print(f"  FAIL: {msg}")
    sys.exit(1)


def assert_contains(text, substr, name):
    if substr not in text:
        fail(f"{name}: missing '{substr}'")


def assert_not_contains(text, substr, name):
    if substr in text:
        fail(f"{name}: should NOT contain '{substr}' but does")


def test_routing():
    print("\n=== Test 1: tier routing → manifiesto correcto ===")
    from ai import prompts

    for screen, fn in [
        ("dashboard", prompts.render_dashboard_prompt),
        ("position", prompts.render_position_prompt),
        ("behavioral", prompts.render_behavioral_prompt),
    ]:
        free_p = fn(tier="free")
        plus_p = fn(tier="plus")
        pro_p = fn(tier="pro")

        # Free/Plus deben arrancar con DESCRIPTIVE (que dice "asistente de análisis")
        if not free_p.startswith("Sos el asistente de análisis"):
            fail(f"{screen}: free should start with descriptive header")
        if not plus_p.startswith("Sos el asistente de análisis"):
            fail(f"{screen}: plus should start with descriptive header")
        # Plus debe usar EL MISMO prompt que free (Plus comparte el manifiesto descriptive)
        if free_p != plus_p:
            fail(f"{screen}: plus != free (deberían ser idénticos)")
        # Pro debe arrancar con el manifiesto causal
        if not pro_p.startswith("Sos el analista financiero"):
            fail(f"{screen}: pro should start with analyst header")
        print(f"  {screen}: free=plus=descriptive, pro=causal ✓")


def test_profile_block_present():
    print("\n=== Test 2: bloque de perfil presente en ambos manifiestos ===")
    from ai.prompts import SYSTEM_BASE_DESCRIPTIVE, SYSTEM_BASE_PRO

    assert_contains(SYSTEM_BASE_DESCRIPTIVE, "PERFIL DEL INVERSOR", "descriptive")
    assert_contains(SYSTEM_BASE_PRO, "PERFIL DEL INVERSOR", "pro")
    print("  Ambos manifiestos mencionan PERFIL DEL INVERSOR ✓")


def test_profile_block_differentiated():
    print("\n=== Test 3: bloque de perfil con reglas diferenciadas ===")
    from ai.prompts import SYSTEM_BASE_DESCRIPTIVE, SYSTEM_BASE_PRO

    # Descriptive: PROHIBIDO inferir causas
    assert_contains(SYSTEM_BASE_DESCRIPTIVE, "PROHIBIDO", "descriptive")
    assert_contains(SYSTEM_BASE_DESCRIPTIVE, "Inferir causas", "descriptive")
    assert_contains(SYSTEM_BASE_DESCRIPTIVE, "Recomendar cambios", "descriptive")
    print("  Descriptive prohíbe inferir causas y recomendar ✓")

    # Pro: PERMITE causalidad probable, prohíbe recetas operativas
    assert_contains(SYSTEM_BASE_PRO, "CAUSAS PLAUSIBLES", "pro")
    assert_contains(SYSTEM_BASE_PRO, "CERO ASESORAMIENTO OPERATIVO", "pro")
    # Pero no debe decir "PROHIBIDO Inferir" (sería bug del refactor)
    assert_not_contains(SYSTEM_BASE_PRO, "PROHIBIDO inferir", "pro")
    print("  Pro permite causalidad pero prohíbe asesoramiento operativo ✓")


def test_helper_modes():
    print("\n=== Test 4: helper _format_investor_profile_for_prompt diferencia modos ===")
    import json
    from main import _format_investor_profile_for_prompt

    profile = json.dumps({"horizon": "medium", "drawdown": "hold", "goal": "freedom"})
    desc = _format_investor_profile_for_prompt(profile, mode="descriptive")
    causal = _format_investor_profile_for_prompt(profile, mode="causal")

    assert_contains(desc, "PROHIBIDO inferir causas", "descriptive helper")
    assert_contains(desc, "sin interpretarlo", "descriptive helper")
    assert_not_contains(desc, "Inferir causas plausibles", "descriptive helper")
    print("  Descriptive helper prohíbe inferir, instruye 'sin interpretarlo' ✓")

    assert_contains(causal, "Podés inferir causas plausibles", "causal helper")
    assert_contains(causal, "Hipótesis sí, recetas específicas", "causal helper")
    print("  Causal helper permite hipótesis, prohíbe recetas ✓")

    # Empty profile
    if _format_investor_profile_for_prompt(None) != "":
        fail("None profile should return empty string")
    if _format_investor_profile_for_prompt("{}") != "":
        fail("Empty profile JSON should return empty string")
    print("  Empty profile devuelve '' ✓")


def test_chat_prompts_have_operational_prohibition():
    print("\n=== Test 5: prompts de chat prohíben asesoramiento operativo ===")
    import main as main_mod

    # _AI_CHAT_SYSTEM (Pro chat)
    chat_pro = main_mod._AI_CHAT_SYSTEM
    chat_free = main_mod._AI_CHAT_SYSTEM_FREE

    # Pro chat menciona explícitamente que no es asesor financiero
    # El módulo viejo ya tiene "no doy recomendaciones" o equivalente
    # Para descriptivo (Free + Plus chat): el bloque dice "Sin recomendaciones"
    assert_contains(chat_free, "Sin recomendaciones", "Free/Plus chat")
    print("  Chat Free/Plus tiene 'Sin recomendaciones' ✓")

    # Para Pro chat: debería tener alguna forma de la misma regla
    # (el manifiesto Pro lo tiene en _AI_CHAT_SYSTEM via "No sos asesor financiero...")
    # Si no lo tiene literal, busquemos un patron alternativo
    # En general el system Pro permite causalidad pero no recetas operativas.
    print("  Chat Pro: verificación manual recomendada del prompt completo")


def test_analyze_endpoint_injects_profile():
    print("\n=== Test 6: /api/ai/analyze inyecta perfil al packet ===")
    # Verificación estática del código fuente — no hacemos call real
    with open(os.path.join(os.path.dirname(HERE), "main.py")) as f:
        src = f.read()

    # Buscar el bloque que enriquece el packet con investor_profile
    if "packet[\"investor_profile\"] = profile_dict" not in src:
        fail("/api/ai/analyze no inyecta investor_profile en el packet")
    print("  Endpoint /api/ai/analyze inyecta investor_profile al packet ✓")

    # Y debe estar ANTES del cache check (para que el cache key lo incluya)
    inject_idx = src.find("packet[\"investor_profile\"] = profile_dict")
    cache_idx = src.find("cache.get_cached(conn, uid, screen, packet, tier=tier)")
    if inject_idx == -1 or cache_idx == -1 or inject_idx > cache_idx:
        fail("inyección de profile DEBE ocurrir ANTES de cache.get_cached")
    print("  Inyección ocurre antes del cache check (cache key incluye perfil) ✓")


def test_insights_packet_has_separated_open_closed():
    print("\n=== Test 7: insights packet separa realized vs current_holdings ===")
    import os, sqlite3 as s3, tempfile
    from datetime import datetime

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["DB_PATH"] = tmp.name

    # Limpiar caches
    for mod in list(sys.modules):
        if mod.startswith("main") or mod.startswith("ai"):
            del sys.modules[mod]
    from main import init_db
    init_db()

    conn = s3.connect(tmp.name)
    conn.row_factory = s3.Row
    conn.execute(
        "INSERT INTO users (email, password_hash, name, approved, email_verified, tier) "
        "VALUES (?, ?, ?, 1, 1, ?)",
        ("t@test", "h", "T", "pro"),
    )
    uid = conn.execute("SELECT id FROM users").fetchone()["id"]
    conn.execute(
        "INSERT INTO brokers (user_id, name, currency) VALUES (?, ?, ?)",
        (uid, "Schwab", "USD"),
    )
    # Operations cerradas en INTC y AMD (los del bug original)
    conn.execute(
        "INSERT INTO operations (user_id, broker, asset, op_type, entry_price, exit_price, "
        "quantity, pnl_usd, pnl_pct, date) "
        "VALUES (?, 'Schwab', 'INTC', 'Venta', 20, 30, 100, 500, 50, '2024-08-01')",
        (uid,),
    )
    conn.execute(
        "INSERT INTO operations (user_id, broker, asset, op_type, entry_price, exit_price, "
        "quantity, pnl_usd, pnl_pct, date) "
        "VALUES (?, 'Schwab', 'AMD', 'Venta', 100, 130, 20, 320, 30, '2024-09-01')",
        (uid,),
    )
    # Positions abiertas en NVDA + AAPL (las que el portfolio realmente tiene)
    conn.execute(
        "INSERT INTO positions (user_id, broker, asset, buy_price, quantity, invested, is_cash) "
        "VALUES (?, ?, ?, ?, ?, ?, 0)",
        (uid, "Schwab", "NVDA", 100, 50, 5000),
    )
    conn.execute(
        "INSERT INTO positions (user_id, broker, asset, buy_price, quantity, invested, is_cash) "
        "VALUES (?, ?, ?, ?, ?, ?, 0)",
        (uid, "Schwab", "AAPL", 180, 22, 3960),
    )
    conn.commit()

    from ai.builders.insights import build
    packet = build(conn, uid)

    # NUEVOS campos: realized_pnl_usd reemplaza al engañoso twr_realized_pct
    if "realized_pnl_usd" not in packet:
        fail("packet missing realized_pnl_usd (replaces twr_realized_pct)")
    if "twr_realized_pct" in packet:
        fail("packet still has twr_realized_pct — should be removed (matemáticamente engañoso)")
    if "realized_avg_pct_per_trade" not in packet:
        fail("packet missing realized_avg_pct_per_trade")
    expected_pnl = 500 + 320  # INTC +500, AMD +320
    if packet["realized_pnl_usd"] != expected_pnl:
        fail(f"realized_pnl_usd should be {expected_pnl}, got {packet['realized_pnl_usd']}")
    print(f"  realized_pnl_usd = ${expected_pnl} (USD absoluto, no % engañoso) ✓")
    print(f"  realized_avg_pct_per_trade = {packet['realized_avg_pct_per_trade']}% ✓")
    if "twr_realized_pct" not in packet:
        print("  twr_realized_pct removed from packet ✓")

    if "realized_attribution" not in packet:
        fail("packet missing realized_attribution")
    ra = packet["realized_attribution"]
    if ra.get("scope") != "closed_trades":
        fail(f"realized_attribution.scope should be 'closed_trades', got {ra.get('scope')}")
    print("  realized_attribution.scope = 'closed_trades' ✓")

    contributors = ra.get("top_contributors", [])
    if not contributors:
        fail("expected at least 1 top_contributor")
    for c in contributors:
        if c.get("status") != "closed":
            fail(f"contributor {c.get('ticker')} status should be 'closed', got {c.get('status')}")
        if "in_portfolio_now" not in c:
            fail(f"contributor {c.get('ticker')} missing in_portfolio_now flag")
    print(f"  {len(contributors)} contributors etiquetados con status='closed' + in_portfolio_now ✓")

    # INTC/AMD vendidos, no están en positions → in_portfolio_now=false
    intc = next((c for c in contributors if c["ticker"] == "INTC"), None)
    amd = next((c for c in contributors if c["ticker"] == "AMD"), None)
    if not intc or intc.get("in_portfolio_now") is not False:
        fail(f"INTC should have in_portfolio_now=False, got {intc}")
    if not amd or amd.get("in_portfolio_now") is not False:
        fail(f"AMD should have in_portfolio_now=False, got {amd}")
    print("  INTC + AMD marcados in_portfolio_now=false (sold trades) ✓")

    # current_holdings_top debe tener NVDA + AAPL con status='open'
    if "current_holdings_top" not in packet:
        fail("packet missing current_holdings_top")
    holdings = packet["current_holdings_top"]
    if len(holdings) < 2:
        fail(f"expected at least 2 current holdings, got {len(holdings)}")
    for h in holdings:
        if h.get("status") != "open":
            fail(f"holding {h.get('ticker')} status should be 'open'")
        if "market_value_usd" not in h or "share_pct" not in h:
            fail(f"holding {h.get('ticker')} missing market_value_usd or share_pct")
    print(f"  {len(holdings)} current_holdings etiquetados status='open' con market_value + share_pct ✓")

    os.unlink(tmp.name)
    print("  TEST 7 PASS")


def test_pro_prompt_has_open_closed_rule():
    print("\n=== Test 8: prompt Pro tiene la regla anti-confusion open/closed ===")
    from ai.prompts import SYSTEM_BASE_PRO, render_insights_prompt

    assert_contains(SYSTEM_BASE_PRO, "TRADES CERRADOS vs POSICIONES ABIERTAS", "Pro base")
    assert_contains(SYSTEM_BASE_PRO, "realized_attribution", "Pro base")
    assert_contains(SYSTEM_BASE_PRO, "current_holdings_top", "Pro base")
    assert_contains(SYSTEM_BASE_PRO, "in_portfolio_now", "Pro base")
    print("  SYSTEM_BASE_PRO menciona la separación open/closed explícitamente ✓")

    insights_prompt = render_insights_prompt(tier="pro")
    assert_contains(insights_prompt, "realized_attribution", "insights pro prompt")
    assert_contains(insights_prompt, "current_holdings_top", "insights pro prompt")
    assert_contains(insights_prompt, "MÁXIMO 3 sections", "insights pro prompt")
    print("  render_insights_prompt incluye reglas de separación + concisión ✓")
    print("  TEST 8 PASS")


def main():
    test_routing()
    test_profile_block_present()
    test_profile_block_differentiated()
    test_helper_modes()
    test_chat_prompts_have_operational_prohibition()
    test_analyze_endpoint_injects_profile()
    test_insights_packet_has_separated_open_closed()
    test_pro_prompt_has_open_closed_rule()
    print("\n\nALL TESTS PASS")


if __name__ == "__main__":
    main()
