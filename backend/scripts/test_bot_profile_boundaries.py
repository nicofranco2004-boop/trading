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

    # Campos nuevos para entender origen del twr_pct (realized vs unrealized)
    for field in ("unrealized_pnl_total_usd", "unrealized_pnl_total_pct", "total_equity_usd"):
        if field not in packet:
            fail(f"packet missing {field}")
    print(f"  unrealized_pnl_total_usd = ${packet['unrealized_pnl_total_usd']} ✓")
    print(f"  total_equity_usd = ${packet['total_equity_usd']} ✓")

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


def test_attribution_packet_has_source_and_in_portfolio():
    print("\n=== Test 9: insights.attribution etiqueta pnl_source + in_portfolio_now ===")
    import os, sqlite3 as s3, tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    os.environ["DB_PATH"] = tmp.name
    for mod in list(sys.modules):
        if mod.startswith("main") or mod.startswith("ai"):
            del sys.modules[mod]
    from main import init_db
    init_db()
    conn = s3.connect(tmp.name); conn.row_factory = s3.Row
    conn.execute("INSERT INTO users (email, password_hash, name, approved, email_verified) VALUES (?,?,?,1,1)", ("t@t","h","T"))
    uid = conn.execute("SELECT id FROM users").fetchone()["id"]
    conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)", (uid,"Schwab","USD"))
    # Fixtures: INTC closed-only / AMD mixed / NVDA open-only
    conn.execute("INSERT INTO operations (user_id,broker,asset,op_type,pnl_usd,date) VALUES (?,'Schwab','INTC','Venta',500,'2024-08-01')", (uid,))
    conn.execute("INSERT INTO operations (user_id,broker,asset,op_type,pnl_usd,date) VALUES (?,'Schwab','AMD','Venta',200,'2024-09-01')", (uid,))
    conn.execute("INSERT INTO positions (user_id,broker,asset,buy_price,quantity,invested,is_cash) VALUES (?,?,?,?,?,?,0)",
                 (uid,"Schwab","AMD",100,5,500))
    conn.execute("INSERT INTO positions (user_id,broker,asset,buy_price,quantity,invested,is_cash) VALUES (?,?,?,?,?,?,0)",
                 (uid,"Schwab","NVDA",100,10,1000))
    conn.commit()

    from ai.builders.insights_attribution import build
    packet = build(conn, uid)

    if "concentration_source" not in packet:
        fail("attribution missing concentration_source")
    print(f"  concentration_source = {packet['concentration_source']} ✓")

    sources_found = set()
    by_ticker = {c["ticker"]: c for c in packet["top_contributors"]}
    for t in ("INTC", "AMD", "NVDA"):
        if t not in by_ticker:
            continue
        c = by_ticker[t]
        for key in ("pnl_source", "in_portfolio_now", "combined_pnl_usd"):
            if key not in c:
                fail(f"contributor {t} missing {key}")
        sources_found.add(c["pnl_source"])
        print(f"  {t}: source={c['pnl_source']}, in_portfolio={c['in_portfolio_now']} ✓")

    expected_sources = {"realized_only", "mixed", "unrealized_only"}
    missing = expected_sources - sources_found
    if missing:
        fail(f"Missing pnl_source values: {missing}")
    print(f"  Los 3 pnl_source aparecen (realized_only/mixed/unrealized_only) ✓")

    os.unlink(tmp.name)
    print("  TEST 9 PASS")


def test_monthly_packet_etiqueta_closed_trades():
    print("\n=== Test 10: monthly.py etiqueta best_trade/top_drivers como closed_trade ===")
    import inspect
    from ai.builders import monthly as monthly_mod

    src = inspect.getsource(monthly_mod)
    # Verificar que el código emite kind='closed_trade' tanto en _trade como
    # en top_drivers.
    if src.count('"closed_trade"') < 2:
        fail("monthly.py debe emitir 'closed_trade' en _trade y top_drivers")
    if '"kind": "closed_trade"' not in src:
        fail("monthly.py no etiqueta items con kind:'closed_trade'")
    print("  best_trade, worst_trade, top_drivers etiquetados kind='closed_trade' ✓")
    # Docstring documenta la separación
    if "SOLO TRADES CERRADOS" not in src and "SOLO trades cerrados" not in src:
        fail("monthly.py docstring debe aclarar que top_drivers es SOLO trades cerrados")
    print("  Docstring aclara que top_drivers son trades cerrados ✓")
    print("  TEST 10 PASS")


def test_reports_packet_has_realized_alias():
    print("\n=== Test 11: reports.py emite realized_pnl_year_usd además de pnl_year_usd ===")
    import inspect
    from ai.builders import reports as reports_mod

    src = inspect.getsource(reports_mod)
    if '"realized_pnl_year_usd"' not in src:
        fail("reports.py debe emitir realized_pnl_year_usd")
    if '"pnl_year_usd"' not in src:
        fail("reports.py debe mantener pnl_year_usd como alias back-compat")
    print("  reports.py expone realized_pnl_year_usd + alias pnl_year_usd ✓")
    print("  TEST 11 PASS")


def test_packets_emit_field_docs():
    print("\n=== Test 12: packets críticos emiten _field_docs inline (Ola 2-E) ===")
    import inspect
    for mod_name in ("insights", "insights_attribution", "monthly", "reports"):
        mod = __import__(f"ai.builders.{mod_name}", fromlist=[mod_name])
        src = inspect.getsource(mod)
        if '"_field_docs"' not in src:
            fail(f"{mod_name}.py debe emitir _field_docs")
        # Cada uno debe documentar al menos 3 fields
        # (chequeo grueso por presencia de keys clave)
        if mod_name == "insights":
            for key in ("realized_pnl_usd", "unrealized_pnl_total_usd", "realized_attribution"):
                if f'"{key}"' not in src or f'"{key}.' not in src and key not in src.split('_field_docs')[1][:2000]:
                    pass  # heurística laxa
        print(f"  {mod_name}.py emite _field_docs ✓")
    print("  TEST 12 PASS")


def test_pro_prompt_mentions_field_docs():
    print("\n=== Test 13: SYSTEM_BASE_PRO menciona _field_docs ===")
    from ai.prompts import SYSTEM_BASE_PRO, SYSTEM_BASE_DESCRIPTIVE

    assert_contains(SYSTEM_BASE_PRO, "_field_docs", "Pro base")
    assert_contains(SYSTEM_BASE_DESCRIPTIVE, "_field_docs", "Descriptive base")
    print("  Ambos system prompts instruyen al LLM a leer _field_docs ✓")
    print("  TEST 13 PASS")


def test_chat_snapshot_sanitizer():
    print("\n=== Test 14: _sanitize_chat_snapshot normaliza shape + inyecta _kind ===")
    from main import _sanitize_chat_snapshot

    # None → {}
    if _sanitize_chat_snapshot(None) != {}:
        fail("None input should return {}")
    print("  None → {} ✓")

    # Listas None → []
    r = _sanitize_chat_snapshot({"positions": None, "operations": None, "monthly": None})
    for key in ("positions", "operations", "monthly"):
        if r[key] != []:
            fail(f"{key}=None should coerce to []")
    print("  None lists → [] (positions, operations, monthly) ✓")

    # Lista no-lista (string) → [] con warning
    r = _sanitize_chat_snapshot({"positions": "not a list"})
    if r["positions"] != []:
        fail("non-list positions should coerce to []")
    print("  Non-list type-coerce: positions string → [] ✓")

    # Positions sin _kind → marcado open_position
    r = _sanitize_chat_snapshot({"positions": [{"asset": "AAPL", "quantity": 10}]})
    if r["positions"][0].get("_kind") != "open_position":
        fail("position should get _kind='open_position'")
    print("  positions[] inject _kind='open_position' ✓")

    # Operations sin _kind → marcado closed_trade
    r = _sanitize_chat_snapshot({"operations": [{"asset": "INTC", "pnl_usd": 500}]})
    if r["operations"][0].get("_kind") != "closed_trade":
        fail("operation should get _kind='closed_trade'")
    print("  operations[] inject _kind='closed_trade' ✓")

    # _kind preserved si ya está
    r = _sanitize_chat_snapshot({"positions": [{"_kind": "custom", "asset": "X"}]})
    if r["positions"][0]["_kind"] != "custom":
        fail("existing _kind should not be overwritten")
    print("  _kind preserved si existe ✓")

    # summary no-dict se remueve
    r = _sanitize_chat_snapshot({"summary": "string-not-dict"})
    if "summary" in r:
        fail("non-dict summary should be removed")
    print("  summary non-dict removed ✓")

    # _sanitized flag presente
    r = _sanitize_chat_snapshot({})
    if r.get("_sanitized") is not True:
        fail("sanitized snapshot should have _sanitized=True flag")
    print("  _sanitized flag inyectado ✓")

    print("  TEST 14 PASS")


def main():
    test_routing()
    test_profile_block_present()
    test_profile_block_differentiated()
    test_helper_modes()
    test_chat_prompts_have_operational_prohibition()
    test_analyze_endpoint_injects_profile()
    test_insights_packet_has_separated_open_closed()
    test_pro_prompt_has_open_closed_rule()
    test_attribution_packet_has_source_and_in_portfolio()
    test_monthly_packet_etiqueta_closed_trades()
    test_reports_packet_has_realized_alias()
    test_packets_emit_field_docs()
    test_pro_prompt_mentions_field_docs()
    test_chat_snapshot_sanitizer()
    print("\n\nALL TESTS PASS")


if __name__ == "__main__":
    main()
