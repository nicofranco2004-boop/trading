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
            is_admin INTEGER DEFAULT 0,
            tier TEXT
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
    # Cuatro users: 1=admin, 2=free, 3=free (sin uso aún), 4=pro (admin con override)
    conn.executescript("""
        INSERT INTO users (id, email, is_admin, tier) VALUES
            (1, 'admin@rendi.finance', 1, NULL),
            (2, 'free@rendi.finance', 0, NULL),
            (3, 'newuser@rendi.finance', 0, NULL),
            (4, 'admin-pro@rendi.finance', 1, 'pro');
    """)
    return conn


# ── get_tier ─────────────────────────────────────────────────────────────────

def test_get_tier_admin():
    conn = _make_db()
    assert quota.get_tier(conn, 1) == "admin"


def test_get_tier_free():
    conn = _make_db()
    assert quota.get_tier(conn, 2) == "free"


def test_get_tier_override_pro_beats_admin():
    """users.tier='pro' override hace que un admin se vea como Pro
    (sin perder is_admin powers en otras checks)."""
    conn = _make_db()
    # user_id=4 es is_admin=1 + tier='pro' override
    assert quota.get_tier(conn, 4) == "pro"


def test_get_tier_override_free_on_free_user():
    """users.tier='free' explícito devuelve free incluso si el user no es admin."""
    conn = _make_db()
    conn.execute("UPDATE users SET tier='free' WHERE id=2")
    assert quota.get_tier(conn, 2) == "free"


def test_get_tier_override_null_falls_back_to_is_admin():
    """Sin override, get_tier respeta la lógica is_admin antigua."""
    conn = _make_db()
    # user_id=1 (is_admin=1, tier=NULL) → admin
    assert quota.get_tier(conn, 1) == "admin"
    # user_id=2 (is_admin=0, tier=NULL) → free
    assert quota.get_tier(conn, 2) == "free"


def test_get_tier_override_invalid_value_falls_back():
    """Valores raros en users.tier (ej. 'enterprise') ignoran el override."""
    conn = _make_db()
    conn.execute("UPDATE users SET tier='enterprise' WHERE id=1")  # admin user
    assert quota.get_tier(conn, 1) == "admin"  # fallback a is_admin


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


# ── _window_start: ventana móvil 7 días ──────────────────────────────────────

def test_window_start_is_today_minus_6():
    """Window de 7 días inclusive = hoy − 6."""
    assert quota._window_start(date(2026, 5, 18)) == date(2026, 5, 12)


def test_window_includes_previous_sunday_on_monday():
    """Caso del bug Pablo: análisis del domingo previo NO debe excluirse
    cuando hoy es lunes. Window rolling lo incluye."""
    monday = date(2026, 5, 18)
    sunday_prev = date(2026, 5, 17)
    start = quota._window_start(monday)
    assert sunday_prev >= start, (
        f"Domingo previo ({sunday_prev}) debería estar en el window que empieza en {start}"
    )


def test_week_start_alias_still_works():
    """_week_start es alias back-compat del _window_start nuevo."""
    today = date(2026, 5, 18)
    assert quota._week_start(today) == quota._window_start(today)


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
    assert u["period"] == "rolling_7d"
    assert u["analyses_count"] == 0
    assert u["analyses_limit"] == 6
    assert u["analyses_remaining"] == 6
    # Hub Pro-only — Free user ve 0/0
    assert u["hub_queries_limit"] == 0
    assert u["hub_queries_remaining"] == 0
    # Sin análisis en el window → resets_on null
    assert u["resets_on"] is None


def test_usage_excludes_analyses_older_than_7_days():
    """Análisis de hace más de 7 días NO cuentan (cayeron del window)."""
    conn = _make_db()
    today = date(2026, 5, 13)
    too_old = today - timedelta(days=8)   # 8 días atrás → fuera del window
    within = today - timedelta(days=3)    # 3 días atrás → dentro del window

    with patch("ai.quota.date") as mock_date:
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        conn.execute(
            "INSERT INTO ai_usage_daily (user_id, date, analyses_count) VALUES (?, ?, ?)",
            (2, too_old.isoformat(), 3),
        )
        conn.execute(
            "INSERT INTO ai_usage_daily (user_id, date, analyses_count) VALUES (?, ?, ?)",
            (2, within.isoformat(), 2),
        )

        u = quota.get_current_usage(conn, 2)
        # Solo los 2 dentro del window cuentan
        assert u["analyses_count"] == 2
        assert u["analyses_remaining"] == 4


def test_usage_pablo_bug_sunday_analysis_counts_on_monday():
    """Regression del bug Pablo: análisis del domingo SIGUEN contando el lunes.

    Antes (ISO week): lunes resetea, count cae a 0. Sorpresa para el user.
    Ahora (rolling 7d): el análisis del domingo está dentro del window."""
    conn = _make_db()
    monday = date(2026, 5, 18)
    sunday_prev = date(2026, 5, 17)

    with patch("ai.quota.date") as mock_date:
        mock_date.today.return_value = monday
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        conn.execute(
            "INSERT INTO ai_usage_daily (user_id, date, analyses_count) VALUES (?, ?, ?)",
            (2, sunday_prev.isoformat(), 1),
        )

        u = quota.get_current_usage(conn, 2)
        assert u["analyses_count"] == 1, (
            "El análisis del domingo previo DEBE contar el lunes (rolling window)"
        )
        assert u["analyses_remaining"] == 5


def test_usage_sums_multiple_days_within_window():
    conn = _make_db()
    today = date(2026, 5, 13)
    d1 = today - timedelta(days=2)
    d2 = today - timedelta(days=1)

    with patch("ai.quota.date") as mock_date:
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        for d, n in [(d1, 2), (d2, 2), (today, 1)]:
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


def test_resets_on_is_oldest_analysis_plus_7_days():
    """resets_on debe ser la fecha en que el análisis más antiguo se cae del window."""
    conn = _make_db()
    today = date(2026, 5, 18)
    oldest = date(2026, 5, 14)  # 4 días atrás, dentro del window

    with patch("ai.quota.date") as mock_date:
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        # Análisis en el día más antiguo + uno más reciente
        conn.execute(
            "INSERT INTO ai_usage_daily (user_id, date, analyses_count) VALUES (?, ?, ?)",
            (2, oldest.isoformat(), 1),
        )
        conn.execute(
            "INSERT INTO ai_usage_daily (user_id, date, analyses_count) VALUES (?, ?, ?)",
            (2, today.isoformat(), 1),
        )

        u = quota.get_current_usage(conn, 2)
        # resets_on = oldest + 7 días
        assert u["resets_on"] == (oldest + timedelta(days=7)).isoformat()


def test_resets_on_none_when_no_analyses():
    """Sin análisis en el window → resets_on null (no hay nada que resetear)."""
    conn = _make_db()
    u = quota.get_current_usage(conn, 2)
    assert u["resets_on"] is None


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
