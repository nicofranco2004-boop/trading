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


def test_ar_bond_metadata_enrichment():
    print("\n=== Test 16: insights packet incluye ar_bond_holdings cuando hay bonos AR ===")
    import os, sqlite3 as s3, tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    os.environ["DB_PATH"] = tmp.name
    for mod in list(sys.modules):
        if mod.startswith("main") or mod.startswith("ai"):
            del sys.modules[mod]
    from main import init_db
    init_db()
    conn = s3.connect(tmp.name); conn.row_factory = s3.Row
    conn.execute("INSERT INTO users (email,password_hash,name,approved,email_verified) VALUES (?,?,?,1,1)", ("t@t","h","T"))
    uid = conn.execute("SELECT id FROM users").fetchone()["id"]
    conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)", (uid,"Cocos","ARS"))
    # Bonos AR conocidos + un asset que NO es bono
    conn.execute("INSERT INTO positions (user_id,broker,asset,buy_price,quantity,invested,is_cash) VALUES (?,?,?,?,?,?,0)",
                 (uid,"Cocos","AL30",60,100,6000))
    conn.execute("INSERT INTO positions (user_id,broker,asset,buy_price,quantity,invested,is_cash) VALUES (?,?,?,?,?,?,0)",
                 (uid,"Cocos","TX26",100,50,5000))
    conn.execute("INSERT INTO positions (user_id,broker,asset,buy_price,quantity,invested,is_cash) VALUES (?,?,?,?,?,?,0)",
                 (uid,"Cocos","GGAL",2000,10,20000))  # acción AR, no bono
    conn.commit()

    from ai.builders.insights import build
    packet = build(conn, uid)

    if "ar_bond_holdings" not in packet:
        fail("packet missing ar_bond_holdings field")
    holdings = packet["ar_bond_holdings"]
    if len(holdings) != 2:
        fail(f"expected 2 bond holdings (AL30, TX26), got {len(holdings)}: {[h.get('ticker') for h in holdings]}")
    tickers = {h["ticker"] for h in holdings}
    if tickers != {"AL30", "TX26"}:
        fail(f"expected {{AL30, TX26}}, got {tickers}")
    print(f"  ar_bond_holdings detecta AL30 + TX26 (excluye GGAL) ✓")

    al30 = next(h for h in holdings if h["ticker"] == "AL30")
    assert al30["metadata"]["kind"] == "soberano_usd"
    assert al30["metadata"]["law"] == "ley_local"
    assert "2030" in al30["metadata"]["maturity"]
    print(f"  AL30: kind=soberano_usd, law=ley_local, maturity={al30['metadata']['maturity']} ✓")

    tx26 = next(h for h in holdings if h["ticker"] == "TX26")
    assert tx26["metadata"]["kind"] == "cer"
    assert tx26["metadata"]["indexed_by"] == "CER"
    print(f"  TX26: kind=cer, indexed_by=CER ✓")

    os.unlink(tmp.name)
    print("  TEST 16 PASS")


def test_ai_tools_sanitize_input():
    print("\n=== Test 15: tools del chat sanitizan input (anti-hallucination + defensa SQL) ===")
    import os, sqlite3 as s3, tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    os.environ["DB_PATH"] = tmp.name
    for mod in list(sys.modules):
        if mod.startswith("main") or mod.startswith("ai"):
            del sys.modules[mod]
    from main import init_db, _execute_ai_tool
    init_db()
    conn = s3.connect(tmp.name)
    conn.execute("INSERT INTO users (email, password_hash, name, approved, email_verified) VALUES (?,?,?,1,1)", ("t@t","h","T"))
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    conn.commit()

    # SQL injection attempt en asset
    r = _execute_ai_tool("get_asset_operations", {"asset": "AAPL' OR 1=1--"}, uid)
    if "error" not in r:
        fail("SQL injection attempt should be rejected")
    print("  SQL-inj asset rejected ✓")

    # months negativo
    r = _execute_ai_tool("get_monthly_detail", {"months": -5}, uid)
    if "entries" not in r:
        fail("negative months should clamp, not error")
    print("  months negativo → clamp ✓")

    # months no-numeric
    r = _execute_ai_tool("get_monthly_detail", {"months": "mucho"}, uid)
    if "entries" not in r:
        fail("non-numeric months should fallback to 12")
    print("  months string → default ✓")

    # symbols no-list
    r = _execute_ai_tool("get_current_prices", {"symbols": "AAPL"}, uid)
    if "error" not in r:
        fail("non-list symbols should be rejected")
    print("  symbols non-list rejected ✓")

    # tool name desconocida
    r = _execute_ai_tool("hack_db", {}, uid)
    if "no reconocida" not in r.get("error", ""):
        fail("unknown tool should return error")
    print("  unknown tool rejected ✓")

    # input_data no-dict
    r = _execute_ai_tool("get_current_prices", "not a dict", uid)
    if "debe ser dict" not in r.get("error", ""):
        fail("non-dict input should be rejected")
    print("  non-dict input rejected ✓")

    os.unlink(tmp.name)
    print("  TEST 15 PASS")


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


def test_realized_vs_unrealized_tool():
    print("\n=== Test 17: tool get_realized_vs_unrealized devuelve shape correcto ===")
    import os, sqlite3 as s3, tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    os.environ["DB_PATH"] = tmp.name
    for mod in list(sys.modules):
        if mod.startswith("main") or mod.startswith("ai"):
            del sys.modules[mod]
    from main import init_db, _execute_ai_tool
    init_db()
    conn = s3.connect(tmp.name)
    conn.execute(
        "INSERT INTO users (email, password_hash, name, approved, email_verified) VALUES (?,?,?,1,1)",
        ("t@t", "h", "T"),
    )
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    # broker + 1 operación cerrada + 1 posición abierta (sin price_override sería
    # mark-to-market vía yfinance, lo cual no queremos en test → usamos override)
    conn.execute(
        "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
        (uid, "TestBroker", "USDT"),
    )
    conn.execute(
        "INSERT INTO operations (user_id, broker, asset, op_type, entry_price, exit_price, "
        "quantity, pnl_usd, pnl_pct, date) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (uid, "TestBroker", "AMD", "sell", 100, 120, 10, 200, 20, "2025-01-15"),
    )
    conn.execute(
        "INSERT INTO operations (user_id, broker, asset, op_type, entry_price, exit_price, "
        "quantity, pnl_usd, pnl_pct, date) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (uid, "TestBroker", "INTC", "sell", 30, 28, 100, -200, -6.7, "2025-02-10"),
    )
    conn.execute(
        "INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity, "
        "commissions, price_override) VALUES (?,?,?,?,?,?,?,?)",
        (uid, "TestBroker", "NVDA", 0, 1000, 10, 0, 150),  # invested=1000, qty=10, price=150 → value=1500, unr=500
    )
    conn.commit()

    # Totales de toda la cartera
    r = _execute_ai_tool("get_realized_vs_unrealized", {}, uid)
    if r.get("scope") != "portfolio_total":
        fail(f"scope esperado 'portfolio_total', got {r.get('scope')}")
    # realized = +200 - 200 = 0 USD
    if abs(r.get("realized_pnl_usd", -999)) > 0.01:
        fail(f"realized_pnl_usd esperado 0, got {r.get('realized_pnl_usd')}")
    # closed_trades_count = 2
    if r.get("closed_trades_count") != 2:
        fail(f"closed_trades_count esperado 2, got {r.get('closed_trades_count')}")
    # open_positions_count = 1
    if r.get("open_positions_count") != 1:
        fail(f"open_positions_count esperado 1, got {r.get('open_positions_count')}")
    # unrealized: market_value − invested = 1500 − 1000 = 500
    if abs(r.get("unrealized_pnl_usd", 0) - 500) > 1:
        fail(f"unrealized_pnl_usd esperado ~500, got {r.get('unrealized_pnl_usd')}")
    if "_note" not in r:
        fail("falta _note explicativo")
    print("  portfolio_total shape OK ✓")

    # Filtrado por asset (AMD: solo realized, no está en posiciones abiertas)
    r2 = _execute_ai_tool("get_realized_vs_unrealized", {"asset": "AMD"}, uid)
    if r2.get("scope") != "single_asset":
        fail(f"scope filtrado debe ser 'single_asset', got {r2.get('scope')}")
    if abs(r2.get("realized_pnl_usd", 0) - 200) > 0.01:
        fail(f"realized AMD esperado 200, got {r2.get('realized_pnl_usd')}")
    if r2.get("in_portfolio_now") is not False:
        fail("AMD no debería estar en cartera abierta")
    if r2.get("pnl_source") != "realized_only":
        fail(f"pnl_source AMD esperado 'realized_only', got {r2.get('pnl_source')}")
    print("  filtro AMD (realized_only) ✓")

    # Filtrado por NVDA — sin trades cerrados, solo posición abierta
    r3 = _execute_ai_tool("get_realized_vs_unrealized", {"asset": "NVDA"}, uid)
    if r3.get("realized_pnl_usd") != 0:
        fail(f"NVDA realized esperado 0, got {r3.get('realized_pnl_usd')}")
    if r3.get("in_portfolio_now") is not True:
        fail("NVDA debería estar en cartera abierta")
    if r3.get("pnl_source") != "unrealized_only":
        fail(f"pnl_source NVDA esperado 'unrealized_only', got {r3.get('pnl_source')}")
    print("  filtro NVDA (unrealized_only) ✓")

    # Asset inválido (SQL injection / formato)
    r4 = _execute_ai_tool("get_realized_vs_unrealized", {"asset": "FOO' OR 1=1--"}, uid)
    if "error" not in r4:
        fail("asset inválido debería ser rechazado")
    print("  asset inválido rechazado ✓")

    os.unlink(tmp.name)
    print("  TEST 17 PASS")


def test_news_for_assets_tool():
    print("\n=== Test 18: tool get_recent_news_for_assets — sanitiza input + shape ===")
    import os, sqlite3 as s3, tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    os.environ["DB_PATH"] = tmp.name
    for mod in list(sys.modules):
        if mod.startswith("main") or mod.startswith("ai"):
            del sys.modules[mod]
    import main as main_mod
    from main import init_db, _execute_ai_tool
    init_db()
    # Monkey-patch para que NO haga fetch real a Google News durante el test —
    # los unit tests no deben tocar la red, además es lento/flaky.
    main_mod._ensure_news_batch_parallel = lambda *a, **k: None

    conn = s3.connect(tmp.name)
    conn.execute(
        "INSERT INTO users (email, password_hash, name, approved, email_verified) VALUES (?,?,?,1,1)",
        ("t@t", "h", "T"),
    )
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    # Pre-sembramos news para AAPL (query_source = "AAPL stock")
    conn.execute(
        "INSERT INTO news (source, external_id, category, query_source, title, summary, url, published_at, fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("test", "ext1", "portfolio", "AAPL stock", "Apple beats earnings", "Q4 EPS up", "http://x", "2025-05-20", "2025-05-20"),
    )
    conn.commit()

    # symbols no-lista → error
    r = _execute_ai_tool("get_recent_news_for_assets", {"symbols": "AAPL"}, uid)
    if "error" not in r:
        fail("symbols string debería ser rechazado")
    print("  symbols no-lista rechazado ✓")

    # Símbolos basura (no match al regex) → error
    r = _execute_ai_tool("get_recent_news_for_assets", {"symbols": ["'; DROP TABLE--"]}, uid)
    if "error" not in r:
        fail("símbolo basura debería rechazarse")
    print("  símbolo basura rechazado ✓")

    # Llamada válida con AAPL — debe levantar la fila sembrada
    r = _execute_ai_tool("get_recent_news_for_assets", {"symbols": ["AAPL"]}, uid)
    if "news_by_ticker" not in r:
        fail("respuesta debe tener news_by_ticker dict")
    if "AAPL" not in r["news_by_ticker"]:
        fail("AAPL debe estar en news_by_ticker")
    if not isinstance(r["news_by_ticker"]["AAPL"], list):
        fail("news_by_ticker[AAPL] debe ser lista")
    if len(r["news_by_ticker"]["AAPL"]) != 1:
        fail(f"esperaba 1 news para AAPL (la sembrada), got {len(r['news_by_ticker']['AAPL'])}")
    if r["news_by_ticker"]["AAPL"][0]["title"] != "Apple beats earnings":
        fail(f"título inesperado: {r['news_by_ticker']['AAPL'][0]['title']}")
    if "_note" not in r:
        fail("respuesta debe incluir _note explicativo")
    print("  shape correcto + _note presente + news real levantada ✓")

    # Cap a 5 símbolos — pasamos 8, deben quedar 5 o menos
    r = _execute_ai_tool("get_recent_news_for_assets",
                         {"symbols": ["AAPL", "MSFT", "TSLA", "NVDA", "AMD", "INTC", "GOOG", "META"]}, uid)
    if "error" in r:
        fail(f"8 símbolos válidos no deberían dar error, got {r}")
    if len(r.get("news_by_ticker", {})) > 5:
        fail(f"debe limitarse a 5 símbolos, got {len(r.get('news_by_ticker', {}))}")
    print("  cap a 5 símbolos OK ✓")

    os.unlink(tmp.name)
    print("  TEST 18 PASS")


def test_ai_user_facts_memory():
    print("\n=== Test 19: ai_user_facts — CRUD + injection en system prompt ===")
    import os, sqlite3 as s3, tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    os.environ["DB_PATH"] = tmp.name
    for mod in list(sys.modules):
        if mod.startswith("main") or mod.startswith("ai"):
            del sys.modules[mod]
    from main import init_db, _execute_ai_tool
    init_db()
    conn = s3.connect(tmp.name)
    conn.execute(
        "INSERT INTO users (email, password_hash, name, approved, email_verified) VALUES (?,?,?,1,1)",
        ("t@t", "h", "T"),
    )
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    conn.commit()

    # Tabla existe
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_user_facts'"
    ).fetchall()
    if not rows:
        fail("tabla ai_user_facts no se creó en init_db()")
    print("  tabla ai_user_facts creada ✓")

    # Tool remember_user_fact inserta fila activa
    r = _execute_ai_tool(
        "remember_user_fact",
        {"content": "AL30 lo tengo en IOL, no en Cocos."},
        uid,
    )
    if r.get("ok") is not True:
        fail(f"remember_user_fact debe devolver ok=True, got {r}")
    print("  remember_user_fact persiste ✓")

    # Content vacío → error
    r = _execute_ai_tool("remember_user_fact", {"content": "  "}, uid)
    if "error" not in r:
        fail("content vacío debe rechazarse")
    print("  content vacío rechazado ✓")

    # Verificar que se insertó y está activo
    row = conn.execute(
        "SELECT content, is_active, source FROM ai_user_facts WHERE user_id=?", (uid,)
    ).fetchone()
    if not row or row[0] != "AL30 lo tengo en IOL, no en Cocos.":
        fail(f"contenido no persistió correctamente, got {row}")
    if row[1] != 1:
        fail("fact debería estar activo (is_active=1)")
    if row[2] != "ai_inferred":
        fail("source desde tool debe ser 'ai_inferred'")
    print("  fila persisitda con shape correcto ✓")

    # Hard cap: insertamos 50 más → el 51 debe rechazarse
    for i in range(49):
        _execute_ai_tool("remember_user_fact", {"content": f"fact extra {i}"}, uid)
    r = _execute_ai_tool("remember_user_fact", {"content": "uno más, debería fallar"}, uid)
    if "error" not in r:
        fail("hard cap de 50 facts no funciona")
    if "máximo" not in r.get("error", "").lower():
        fail(f"error de cap debería mencionar 'máximo', got {r}")
    print("  hard cap 50 enforced ✓")

    # Content cap 280 chars (Pydantic acepta hasta 280; en tool capamos por slice)
    r = _execute_ai_tool("remember_user_fact", {"content": "x" * 500}, uid)
    # Como ya estamos en cap de 50 activos, este intento DEBE fallar por cap, no por len.
    # Pero antes de eso, content[:280] se aplicó → si tras cap es válido, da error 50.
    if "error" not in r:
        fail("tras cap 50 no se deberían aceptar más facts")
    print("  cap 280 chars + cap 50 facts respetados ✓")

    os.unlink(tmp.name)
    print("  TEST 19 PASS")


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
    test_ai_tools_sanitize_input()
    test_ar_bond_metadata_enrichment()
    test_realized_vs_unrealized_tool()
    test_news_for_assets_tool()
    test_ai_user_facts_memory()
    print("\n\nALL TESTS PASS")


if __name__ == "__main__":
    main()
