"""Tests para backend/ai/quota.py — cap semanal + tiers + reset logic."""
from __future__ import annotations
import sqlite3
import pytest
from datetime import date, timedelta
from unittest.mock import patch

from ai import quota


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_db():
    """In-memory SQLite con las tablas mínimas que quota necesita."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT,
            is_admin INTEGER DEFAULT 0
        );
        CREATE TABLE ai_usage_daily (
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            analyses_count INTEGER DEFAULT 0,
            hub_queries_count INTEGER DEFAULT 0,
            cost_usd_cents INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date)
        );
    """)
    # Tres users: 1=admin, 2=free, 3=free (sin uso aún)
    conn.executescript("""
        INSERT INTO users (id, email, is_admin) VALUES
            (1, 'admin@rendi.app', 1),
            (2, 'free@rendi.app', 0),
            (3, 'newuser@rendi.app', 0);
    """)
    return conn


# ── get_tier ─────────────────────────────────────────────────────────────────

def test_get_tier_admin():
    conn = _make_db()
    assert quota.get_tier(conn, 1) == "admin"


def test_get_tier_free():
    conn = _make_db()
    assert quota.get_tier(conn, 2) == "free"


def test_get_tier_unknown_user_falls_back_to_free():
    conn = _make_db()
    # User no existe en la tabla — defaults a free, no crash
    assert quota.get_tier(conn, 999) == "free"


def test_get_tier_no_users_table():
    """Si la tabla users no existe (entorno legacy), no rompe — fallback free."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Solo creamos ai_usage_daily, no users
    conn.execute("""
        CREATE TABLE ai_usage_daily (
            user_id INTEGER, date TEXT, analyses_count INTEGER DEFAULT 0,
            hub_queries_count INTEGER DEFAULT 0, cost_usd_cents INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date)
        );
    """)
    assert quota.get_tier(conn, 1) == "free"


# ── _week_start: semana ISO ──────────────────────────────────────────────────

def test_week_start_returns_monday():
    # Miércoles 13 may 2026 → lunes 11 may
    assert quota._week_start(date(2026, 5, 13)) == date(2026, 5, 11)


def test_week_start_when_today_is_monday():
    assert quota._week_start(date(2026, 5, 11)) == date(2026, 5, 11)


def test_week_start_when_today_is_sunday():
    # Domingo 17 may → lunes 11 may de esa misma semana ISO
    assert quota._week_start(date(2026, 5, 17)) == date(2026, 5, 11)


# ── LIMITS por tier ──────────────────────────────────────────────────────────

def test_limits_free_is_6_per_week():
    # Free: 6 análisis/sem (tasting menu, paywall agresivo a 3k+ users).
    assert quota.LIMITS["free"]["analyses_per_week"] == 6


def test_limits_free_has_no_hub_access():
    # Hub es Pro-only — el contador queda en 0 como gate explícito.
    assert quota.LIMITS["free"]["hub_queries_per_week"] == 0


def test_limits_pro_is_10x_free():
    # Cap Pro: 60/sem = exactamente 10× Free, claim de marketing literal.
    pro = quota.LIMITS["pro"]["analyses_per_week"]
    free = quota.LIMITS["free"]["analyses_per_week"]
    assert pro == free * 10, f"Pro ({pro}) debe ser exactamente 10× Free ({free})"


def test_limits_admin_unlimited():
    assert quota.LIMITS["admin"]["analyses_per_week"] >= 500


# ── get_current_usage: shape + sum semanal ───────────────────────────────────

def test_usage_empty_user_zero_count():
    conn = _make_db()
    u = quota.get_current_usage(conn, 3)
    assert u["tier"] == "free"
    assert u["period"] == "week"
    assert u["analyses_count"] == 0
    assert u["analyses_limit"] == 6
    assert u["analyses_remaining"] == 6
    # Hub Pro-only — Free user ve 0/0
    assert u["hub_queries_limit"] == 0
    assert u["hub_queries_remaining"] == 0


def test_usage_sums_only_current_week():
    """Análisis de la semana pasada NO cuentan para el cap actual."""
    conn = _make_db()
    today = date(2026, 5, 13)  # miércoles
    last_week = today - timedelta(days=8)  # martes de la semana anterior

    with patch("ai.quota.date") as mock_date:
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        # 3 análisis la semana pasada
        conn.execute(
            "INSERT INTO ai_usage_daily (user_id, date, analyses_count) VALUES (?, ?, ?)",
            (2, last_week.isoformat(), 3),
        )
        # 2 análisis esta semana
        conn.execute(
            "INSERT INTO ai_usage_daily (user_id, date, analyses_count) VALUES (?, ?, ?)",
            (2, today.isoformat(), 2),
        )

        u = quota.get_current_usage(conn, 2)
        # Solo los 2 de esta semana cuentan
        assert u["analyses_count"] == 2
        assert u["analyses_remaining"] == 4


def test_usage_sums_multiple_days_within_week():
    conn = _make_db()
    today = date(2026, 5, 13)  # miércoles
    monday = today - timedelta(days=2)
    tuesday = today - timedelta(days=1)

    with patch("ai.quota.date") as mock_date:
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        for d, n in [(monday, 2), (tuesday, 2), (today, 1)]:
            conn.execute(
                "INSERT INTO ai_usage_daily (user_id, date, analyses_count) VALUES (?, ?, ?)",
                (2, d.isoformat(), n),
            )

        u = quota.get_current_usage(conn, 2)
        assert u["analyses_count"] == 5
        assert u["analyses_remaining"] == 1


def test_usage_admin_tier_uses_admin_limits():
    conn = _make_db()
    u = quota.get_current_usage(conn, 1)  # admin
    assert u["tier"] == "admin"
    assert u["analyses_limit"] == 1000


def test_usage_resets_on_next_monday():
    """resets_on debe ser SIEMPRE un lunes — el inicio de la próxima semana."""
    conn = _make_db()
    # Probamos en distintos días de la semana
    test_days = [
        (date(2026, 5, 11), date(2026, 5, 18)),  # lunes → próximo lunes
        (date(2026, 5, 13), date(2026, 5, 18)),  # miércoles → mismo próximo lunes
        (date(2026, 5, 17), date(2026, 5, 18)),  # domingo → lunes siguiente
        (date(2026, 5, 18), date(2026, 5, 25)),  # próximo lunes → el otro
    ]
    for today, expected_reset in test_days:
        with patch("ai.quota.date") as mock_date:
            mock_date.today.return_value = today
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            u = quota.get_current_usage(conn, 2)
            assert u["resets_on"] == expected_reset.isoformat(), (
                f"Para today={today}, esperaba reset={expected_reset}, obtuve {u['resets_on']}"
            )


# ── can_analyze: enforcement del cap ─────────────────────────────────────────

def test_can_analyze_free_under_cap():
    conn = _make_db()
    allowed, usage = quota.can_analyze(conn, 2)
    assert allowed is True
    assert usage["analyses_remaining"] == 6


def test_can_analyze_free_at_cap_blocks():
    """Cuando un Free user alcanza 6/6, can_analyze debe devolver False."""
    conn = _make_db()
    today = date(2026, 5, 13)

    with patch("ai.quota.date") as mock_date:
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        # 6 análisis ya consumidos esta semana
        conn.execute(
            "INSERT INTO ai_usage_daily (user_id, date, analyses_count) VALUES (?, ?, ?)",
            (2, today.isoformat(), 6),
        )
        allowed, usage = quota.can_analyze(conn, 2)
        assert allowed is False
        assert usage["analyses_remaining"] == 0
        assert usage["tier"] == "free"


def test_can_hub_query_free_always_blocked():
    """Free tier no tiene acceso al Hub — siempre False, sin importar count."""
    conn = _make_db()
    allowed, usage = quota.can_hub_query(conn, 2)
    assert allowed is False
    assert usage["hub_queries_limit"] == 0
    assert usage["hub_queries_remaining"] == 0


def test_can_analyze_admin_at_high_count_still_allowed():
    """Admin con 50 análisis sigue allowed (cap 1000)."""
    conn = _make_db()
    today = date.today()
    conn.execute(
        "INSERT INTO ai_usage_daily (user_id, date, analyses_count) VALUES (?, ?, ?)",
        (1, today.isoformat(), 50),
    )
    allowed, _ = quota.can_analyze(conn, 1)
    assert allowed is True


# ── record_analysis ──────────────────────────────────────────────────────────

def test_record_analysis_increments_counter():
    conn = _make_db()
    quota.record_analysis(conn, 2, cost_usd_cents=15)
    quota.record_analysis(conn, 2, cost_usd_cents=20)
    row = conn.execute(
        "SELECT analyses_count, cost_usd_cents FROM ai_usage_daily WHERE user_id=?",
        (2,),
    ).fetchone()
    assert row["analyses_count"] == 2
    assert row["cost_usd_cents"] == 35


def test_record_analysis_isolates_users():
    """Records de un user no afectan el counter de otro."""
    conn = _make_db()
    quota.record_analysis(conn, 2)
    quota.record_analysis(conn, 2)
    quota.record_analysis(conn, 3)
    u2 = quota.get_current_usage(conn, 2)
    u3 = quota.get_current_usage(conn, 3)
    assert u2["analyses_count"] == 2
    assert u3["analyses_count"] == 1


# ── Legacy alias ─────────────────────────────────────────────────────────────

def test_get_today_usage_aliases_current_usage():
    """get_today_usage debe seguir funcionando — back-compat."""
    conn = _make_db()
    a = quota.get_today_usage(conn, 2)
    b = quota.get_current_usage(conn, 2)
    assert a == b
