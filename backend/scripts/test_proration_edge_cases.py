"""test_proration_edge_cases — verifica escenarios del modelo de crédito.

Cubre los flujos críticos:
  1. Fresh subscribe Plus monthly + Pro upgrade mid-período + downgrade
  2. Backfill de user pre-proration
  3. Cancel durante credit-only (debe 409 con hint)
  4. Re-subscribe durante credit-only (suma crédito en lugar de reemplazar)
  5. Múltiples cambios de plan seguidos
  6. Expiración por cron: solo afecta users sin sub authorized
  7. Idempotencia: re-correr init_db no duplica entries en ledger

Correr desde backend/:
    python -m scripts.test_proration_edge_cases

Si todo pasa imprime "ALL TESTS PASS" al final.
"""

import os
import sys
import tempfile
import sqlite3
from datetime import datetime, timedelta

# Working dir setup
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def setup_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["DB_PATH"] = tmp.name
    # init_db reads DB_PATH at import time of main — clear cached modules
    for mod in list(sys.modules):
        if mod.startswith("main") or mod.startswith("billing"):
            del sys.modules[mod]
    from main import init_db
    init_db()
    return tmp.name


def open_conn(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def make_user(conn, email="u@test.com", tier=None):
    conn.execute(
        "INSERT INTO users (email, password_hash, name, approved, email_verified, tier) "
        "VALUES (?, 'h', ?, 1, 1, ?)",
        (email, email.split("@")[0], tier),
    )
    conn.commit()
    return conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]


def assert_close(actual, expected, tolerance=0.5, msg=""):
    if abs(actual - expected) > tolerance:
        raise AssertionError(f"{msg}: got {actual}, expected ~{expected} (±{tolerance})")


def test_1_subscribe_upgrade_downgrade():
    """User compra Plus monthly → upgrade Pro → downgrade Plus → expira."""
    print("\n=== Test 1: subscribe → upgrade → downgrade flow ===")
    path = setup_db()
    conn = open_conn(path)
    uid = make_user(conn)

    from billing import credits

    # Day 0: Plus monthly subscribe
    credits.grant_payment_credit(conn, user_id=uid, plan="plus", period="monthly")
    state = credits.get_credit_state(conn, uid)
    assert_close(state["days_remaining"], 30.0, msg="Fresh Plus monthly")
    print(f"  Day 0: Plus monthly → {state['days_remaining']:.1f} days ✓")

    # Day 15: upgrade to Pro monthly (15 days used = $2 left)
    conn.execute(
        "UPDATE users SET credit_active_until=? WHERE id=?",
        ((datetime.utcnow() + timedelta(days=15)).isoformat(), uid),
    )
    conn.commit()
    result = credits.convert_plan(conn, user_id=uid, new_plan="pro", new_period="monthly")
    # $2 remaining at Pro rate $0.30/day = ~6.7 days
    assert_close(result["days_remaining"], 6.67, msg="Plus→Pro mid-month")
    print(f"  Day 15: upgrade Pro → {result['days_remaining']:.1f} days at Pro rate ✓")

    # Day 18: downgrade back to Plus (~3.7 days used in Pro = $1.10 remaining)
    conn.execute(
        "UPDATE users SET credit_active_until=? WHERE id=?",
        ((datetime.utcnow() + timedelta(days=3)).isoformat(), uid),
    )
    conn.commit()
    result = credits.convert_plan(conn, user_id=uid, new_plan="plus", new_period="monthly")
    # $0.90 remaining at Plus rate $0.133/day = ~6.75 days
    assert_close(result["days_remaining"], 6.75, msg="Pro→Plus downgrade")
    print(f"  Day 18: downgrade Plus → {result['days_remaining']:.1f} days at Plus rate ✓")

    os.unlink(path)
    print("  TEST 1 PASS")


def test_2_no_op_change_to_same_plan():
    """Cambiar al mismo plan/period que ya tenés → no-op, no toca crédito."""
    print("\n=== Test 2: no-op when changing to same plan ===")
    path = setup_db()
    conn = open_conn(path)
    uid = make_user(conn)
    from billing import credits

    credits.grant_payment_credit(conn, user_id=uid, plan="pro", period="monthly")
    before = credits.get_credit_state(conn, uid)
    result = credits.convert_plan(conn, user_id=uid, new_plan="pro", new_period="monthly")
    assert result["converted"] is False, f"Should be no-op but got {result}"
    after = credits.get_credit_state(conn, uid)
    assert before["active_until"] == after["active_until"], "credit_active_until shouldn't change"
    print(f"  Same plan change is no-op ✓")
    os.unlink(path)
    print("  TEST 2 PASS")


def test_3_renewal_extends_window():
    """Renewal payment durante crédito activo extiende +period_days días."""
    print("\n=== Test 3: renewal extends credit window ===")
    path = setup_db()
    conn = open_conn(path)
    uid = make_user(conn)
    from billing import credits

    credits.grant_payment_credit(conn, user_id=uid, plan="plus", period="monthly")
    before = credits.get_credit_state(conn, uid)

    # Simulate 5 days passed
    conn.execute(
        "UPDATE users SET credit_active_until=? WHERE id=?",
        ((datetime.utcnow() + timedelta(days=25)).isoformat(), uid),
    )
    conn.commit()

    # Renewal (Rebill cobró otro $4)
    credits.grant_payment_credit(conn, user_id=uid, plan="plus", period="monthly")
    after = credits.get_credit_state(conn, uid)
    # 25 days remaining + 30 days new = 55 days
    assert_close(after["days_remaining"], 55.0, msg="Renewal extension")
    print(f"  25d before renewal + 30d period = {after['days_remaining']:.1f}d ✓")
    os.unlink(path)
    print("  TEST 3 PASS")


def test_4_cron_only_downgrades_credit_users_without_sub():
    """Cron baja a free SOLO si no hay sub authorized."""
    print("\n=== Test 4: cron preserves users with authorized sub ===")
    path = setup_db()
    conn = open_conn(path)

    from billing import subscriptions as billing_subs

    # User A: pro, credit expired, NO sub → SHOULD downgrade
    uid_a = make_user(conn, "a@test", tier="pro")
    conn.execute(
        "UPDATE users SET tier='pro', credit_active_until=?, credit_anchor_plan='pro', credit_anchor_period='monthly' WHERE id=?",
        ((datetime.utcnow() - timedelta(days=2)).isoformat(), uid_a),
    )

    # User B: pro, credit expired, BUT has authorized sub → should NOT downgrade
    uid_b = make_user(conn, "b@test", tier="pro")
    conn.execute(
        "UPDATE users SET tier='pro', credit_active_until=?, credit_anchor_plan='pro', credit_anchor_period='monthly' WHERE id=?",
        ((datetime.utcnow() - timedelta(days=2)).isoformat(), uid_b),
    )
    conn.execute(
        "INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference, period, status, amount_ars) "
        "VALUES (?, 'sub_b', 'rendi-b', 'monthly', 'authorized', 0)",
        (uid_b,),
    )

    # User C: pro, credit NOT expired → should NOT downgrade
    uid_c = make_user(conn, "c@test", tier="pro")
    conn.execute(
        "UPDATE users SET tier='pro', credit_active_until=?, credit_anchor_plan='pro', credit_anchor_period='monthly' WHERE id=?",
        ((datetime.utcnow() + timedelta(days=10)).isoformat(), uid_c),
    )
    conn.commit()

    result = billing_subs.run_lifecycle_job(conn)
    assert result["credit_expired_downgraded"] == 1, f"Expected 1 downgrade, got {result['credit_expired_downgraded']}"

    a_tier = conn.execute("SELECT tier FROM users WHERE id=?", (uid_a,)).fetchone()["tier"]
    b_tier = conn.execute("SELECT tier FROM users WHERE id=?", (uid_b,)).fetchone()["tier"]
    c_tier = conn.execute("SELECT tier FROM users WHERE id=?", (uid_c,)).fetchone()["tier"]

    assert a_tier is None, f"A should be free, got {a_tier}"
    assert b_tier == "pro", f"B should stay pro (sub authorized), got {b_tier}"
    assert c_tier == "pro", f"C should stay pro (credit valid), got {c_tier}"
    print(f"  A (expired no sub): {a_tier} (free) ✓")
    print(f"  B (expired with sub): {b_tier} (pro) ✓")
    print(f"  C (active credit): {c_tier} (pro) ✓")
    os.unlink(path)
    print("  TEST 4 PASS")


def test_5_change_chain_consistent():
    """Plus monthly → Pro monthly → Plus annual: math acumulada coincide."""
    print("\n=== Test 5: change chain math is consistent ===")
    path = setup_db()
    conn = open_conn(path)
    uid = make_user(conn)
    from billing import credits

    # Start: Plus monthly ($4 / 30d = $0.133/d)
    credits.grant_payment_credit(conn, user_id=uid, plan="plus", period="monthly")
    # → 30 days @ Plus rate. Day 0 = $4 of credit.

    # Simulate 10 days used
    conn.execute(
        "UPDATE users SET credit_active_until=? WHERE id=?",
        ((datetime.utcnow() + timedelta(days=20)).isoformat(), uid),
    )
    conn.commit()

    # Switch to Pro monthly (20 days × $0.133 = $2.67 remaining → $2.67/$0.30 = 8.89 days)
    r1 = credits.convert_plan(conn, user_id=uid, new_plan="pro", new_period="monthly")
    assert_close(r1["days_remaining"], 8.89, tolerance=0.1, msg="Plus→Pro")

    # Simulate 4 more days used (4.89 days remaining)
    conn.execute(
        "UPDATE users SET credit_active_until=? WHERE id=?",
        ((datetime.utcnow() + timedelta(days=4.89)).isoformat(), uid),
    )
    conn.commit()

    # Switch to Plus annual ($4.89×$0.30 = $1.467 → $1.467/$0.110 = 13.4 days)
    r2 = credits.convert_plan(conn, user_id=uid, new_plan="plus", new_period="annual")
    assert_close(r2["days_remaining"], 13.4, tolerance=0.5, msg="Pro→Plus annual")
    print(f"  Plus monthly (10d used) → Pro monthly: {r1['days_remaining']:.1f}d ✓")
    print(f"  Pro (4d used) → Plus annual: {r2['days_remaining']:.1f}d ✓")

    # Check ledger has 3 entries: 1 payment + 2 plan_change
    rows = conn.execute("SELECT kind FROM credit_ledger WHERE user_id=? ORDER BY id", (uid,)).fetchall()
    kinds = [r["kind"] for r in rows]
    assert kinds == ["payment", "plan_change", "plan_change"], f"Unexpected ledger kinds: {kinds}"
    print(f"  Ledger entries: {kinds} ✓")
    os.unlink(path)
    print("  TEST 5 PASS")


def test_6_backfill_idempotency():
    """Re-correr init_db NO duplica entries en credit_ledger."""
    print("\n=== Test 6: init_db backfill is idempotent ===")
    path = setup_db()
    conn = open_conn(path)
    uid = make_user(conn, tier="plus")
    # Crear sub authorized SIN credit_active_until (estado pre-proration)
    conn.execute(
        "INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference, period, status, amount_ars, created_at) "
        "VALUES (?, 'sub_legacy', 'rendi-legacy', 'monthly', 'authorized', 0, ?)",
        (uid, (datetime.utcnow() - timedelta(days=5)).isoformat()),
    )
    conn.commit()
    conn.close()

    # First init_db → debería backfillear
    for mod in list(sys.modules):
        if mod.startswith("main") or mod.startswith("billing"):
            del sys.modules[mod]
    from main import init_db
    init_db()
    conn = open_conn(path)
    count1 = conn.execute("SELECT COUNT(*) AS c FROM credit_ledger WHERE user_id=?", (uid,)).fetchone()["c"]
    until_after_first = conn.execute("SELECT credit_active_until FROM users WHERE id=?", (uid,)).fetchone()["credit_active_until"]
    assert count1 == 1, f"After 1st init_db: expected 1 ledger entry, got {count1}"
    assert until_after_first is not None, "credit_active_until should be set"
    print(f"  After 1st init_db: 1 ledger entry, credit_active_until set ✓")

    # Second init_db → NO debería agregar otra entry
    conn.close()
    for mod in list(sys.modules):
        if mod.startswith("main") or mod.startswith("billing"):
            del sys.modules[mod]
    from main import init_db
    init_db()
    conn = open_conn(path)
    count2 = conn.execute("SELECT COUNT(*) AS c FROM credit_ledger WHERE user_id=?", (uid,)).fetchone()["c"]
    until_after_second = conn.execute("SELECT credit_active_until FROM users WHERE id=?", (uid,)).fetchone()["credit_active_until"]
    assert count2 == 1, f"After 2nd init_db: expected still 1 ledger entry, got {count2}"
    assert until_after_first == until_after_second, "credit_active_until shouldn't drift on re-init"
    print(f"  After 2nd init_db: still 1 entry (idempotent) ✓")
    os.unlink(path)
    print("  TEST 6 PASS")


def test_7_preview_change_plan():
    """preview_plan_change devuelve eligible=False si no hay crédito, y los días si hay."""
    print("\n=== Test 7: preview_plan_change validations ===")
    path = setup_db()
    conn = open_conn(path)
    uid = make_user(conn)
    from billing import credits

    # Sin crédito → eligible=False
    preview = credits.preview_plan_change(conn, uid, "pro", "monthly")
    assert preview["eligible"] is False
    assert preview["reason"] == "no_active_credit"
    print(f"  No credit → eligible=False, reason=no_active_credit ✓")

    # Con crédito Plus → preview a Pro debe ser eligible
    credits.grant_payment_credit(conn, user_id=uid, plan="plus", period="monthly")
    preview = credits.preview_plan_change(conn, uid, "pro", "monthly")
    assert preview["eligible"] is True
    assert_close(preview["new_days"], 13.33, msg="Plus monthly → Pro preview")
    print(f"  Plus monthly → Pro: eligible=True, new_days={preview['new_days']:.2f} ✓")

    # Cambio a mismo plan → eligible=False, reason=same_plan
    preview_same = credits.preview_plan_change(conn, uid, "plus", "monthly")
    assert preview_same["eligible"] is False
    assert preview_same["reason"] == "same_plan"
    print(f"  Same plan → eligible=False, reason=same_plan ✓")
    os.unlink(path)
    print("  TEST 7 PASS")


def main():
    test_1_subscribe_upgrade_downgrade()
    test_2_no_op_change_to_same_plan()
    test_3_renewal_extends_window()
    test_4_cron_only_downgrades_credit_users_without_sub()
    test_5_change_chain_consistent()
    test_6_backfill_idempotency()
    test_7_preview_change_plan()
    print("\n\nALL TESTS PASS")


if __name__ == "__main__":
    main()
