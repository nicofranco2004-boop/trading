"""Tests para backend/ai/cache.py — separación de pools por tier."""
from __future__ import annotations
import sqlite3
import pytest

from ai import cache


def _make_db():
    """In-memory SQLite con la tabla ai_analyses_cache."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE ai_analyses_cache (
            cache_key TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            screen TEXT NOT NULL,
            result_json TEXT,
            expires_at TEXT,
            packet_hash TEXT,
            model TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_read_tokens INTEGER,
            cache_create_tokens INTEGER,
            cost_usd_cents INTEGER,
            created_at TEXT
        );
    """)
    return conn


SAMPLE_PACKET = {"screen": "dashboard", "twr_pct": 14.3, "exposure": {"us_pct": 47}}
SAMPLE_RESULT_PRO = {"tldr": "Pro response", "sections": [], "follow_ups": []}
SAMPLE_RESULT_FREE = {"tldr": "Free response", "sections": [], "follow_ups": []}


# ── _compute_keys: el tier afecta la key ─────────────────────────────────────

def test_compute_keys_returns_two_hashes():
    packet_hash, cache_key = cache._compute_keys(1, "dashboard", SAMPLE_PACKET, "pro")
    assert len(packet_hash) == 64  # sha256 hex
    assert len(cache_key) == 64


def test_compute_keys_packet_hash_independent_of_tier():
    """El packet_hash debe ser igual sin importar tier — sirve para detectar
    cambios de packet, no de tier."""
    h_pro, _ = cache._compute_keys(1, "dashboard", SAMPLE_PACKET, "pro")
    h_free, _ = cache._compute_keys(1, "dashboard", SAMPLE_PACKET, "free")
    assert h_pro == h_free


def test_compute_keys_cache_key_differs_by_tier():
    """La cache_key tiene que diferir entre tiers (separar pools)."""
    _, key_pro = cache._compute_keys(1, "dashboard", SAMPLE_PACKET, "pro")
    _, key_free = cache._compute_keys(1, "dashboard", SAMPLE_PACKET, "free")
    assert key_pro != key_free


def test_compute_keys_cache_key_differs_by_user():
    """Aislamiento entre cuentas — mismo packet de user diferente = key diferente."""
    _, key_u1 = cache._compute_keys(1, "dashboard", SAMPLE_PACKET, "pro")
    _, key_u2 = cache._compute_keys(2, "dashboard", SAMPLE_PACKET, "pro")
    assert key_u1 != key_u2


def test_compute_keys_cache_key_differs_by_screen():
    _, key_dash = cache._compute_keys(1, "dashboard", SAMPLE_PACKET, "pro")
    _, key_ins = cache._compute_keys(1, "insights", SAMPLE_PACKET, "pro")
    assert key_dash != key_ins


def test_compute_keys_deterministic():
    """Mismos inputs → misma key (clave para el lookup)."""
    a = cache._compute_keys(1, "dashboard", SAMPLE_PACKET, "pro")
    b = cache._compute_keys(1, "dashboard", SAMPLE_PACKET, "pro")
    assert a == b


# ── get_cached / set_cached: full flow con tier ──────────────────────────────

def test_set_then_get_pro():
    conn = _make_db()
    cache.set_cached(
        conn, user_id=1, screen="dashboard", packet=SAMPLE_PACKET,
        result=SAMPLE_RESULT_PRO,
        model="claude-haiku-4-5", input_tokens=1000, output_tokens=500,
        tier="pro",
    )
    got = cache.get_cached(conn, 1, "dashboard", SAMPLE_PACKET, tier="pro")
    assert got == SAMPLE_RESULT_PRO


def test_get_returns_none_on_miss():
    conn = _make_db()
    got = cache.get_cached(conn, 1, "dashboard", SAMPLE_PACKET, tier="pro")
    assert got is None


def test_pro_and_free_cache_isolated():
    """Si guardo una respuesta Pro y pido la Free del mismo packet → miss."""
    conn = _make_db()
    cache.set_cached(
        conn, user_id=1, screen="dashboard", packet=SAMPLE_PACKET,
        result=SAMPLE_RESULT_PRO,
        model="claude-haiku-4-5", input_tokens=1000, output_tokens=500,
        tier="pro",
    )
    # Pedimos Free del mismo packet → debería ser cache miss
    got_free = cache.get_cached(conn, 1, "dashboard", SAMPLE_PACKET, tier="free")
    assert got_free is None
    # Pero el Pro sigue ahí
    got_pro = cache.get_cached(conn, 1, "dashboard", SAMPLE_PACKET, tier="pro")
    assert got_pro == SAMPLE_RESULT_PRO


def test_pro_and_free_can_coexist():
    """Dos respuestas distintas (Pro y Free) para mismo packet deben convivir."""
    conn = _make_db()
    cache.set_cached(
        conn, user_id=1, screen="dashboard", packet=SAMPLE_PACKET,
        result=SAMPLE_RESULT_PRO,
        model="claude-haiku-4-5", input_tokens=1000, output_tokens=500,
        tier="pro",
    )
    cache.set_cached(
        conn, user_id=1, screen="dashboard", packet=SAMPLE_PACKET,
        result=SAMPLE_RESULT_FREE,
        model="claude-haiku-4-5", input_tokens=500, output_tokens=200,
        tier="free",
    )
    assert cache.get_cached(conn, 1, "dashboard", SAMPLE_PACKET, tier="pro") == SAMPLE_RESULT_PRO
    assert cache.get_cached(conn, 1, "dashboard", SAMPLE_PACKET, tier="free") == SAMPLE_RESULT_FREE


def test_packet_change_invalidates_cache():
    """Si el packet cambia, la cache_key cambia → miss automático."""
    conn = _make_db()
    cache.set_cached(
        conn, user_id=1, screen="dashboard", packet=SAMPLE_PACKET,
        result=SAMPLE_RESULT_PRO,
        model="claude-haiku-4-5", input_tokens=1000, output_tokens=500,
        tier="pro",
    )
    # Packet ligeramente distinto
    different_packet = {**SAMPLE_PACKET, "twr_pct": 15.0}
    got = cache.get_cached(conn, 1, "dashboard", different_packet, tier="pro")
    assert got is None


def test_default_tier_is_pro():
    """Si no se pasa tier, defaults a 'pro' (back-compat con callers viejos)."""
    conn = _make_db()
    cache.set_cached(
        conn, user_id=1, screen="dashboard", packet=SAMPLE_PACKET,
        result=SAMPLE_RESULT_PRO,
        model="claude-haiku-4-5", input_tokens=1000, output_tokens=500,
        # NOTAR: no pasamos tier explícito
    )
    # get_cached sin tier también defaults a pro → debería leer la fila
    got = cache.get_cached(conn, 1, "dashboard", SAMPLE_PACKET)
    assert got == SAMPLE_RESULT_PRO


# ── TTL tier-aware ───────────────────────────────────────────────────────────

def test_ttl_for_tier_free_is_72h():
    """Free tier tiene TTL extendido (72h) para reducir costos a escala."""
    assert cache._ttl_for_tier("free") == 72 * 3600


def test_ttl_for_tier_pro_is_24h():
    assert cache._ttl_for_tier("pro") == 24 * 3600


def test_ttl_for_tier_admin_is_24h():
    """Admin usa el mismo TTL que Pro — dogfood real."""
    assert cache._ttl_for_tier("admin") == 24 * 3600


def test_ttl_for_tier_unknown_defaults_to_pro():
    """Tier desconocido (typo o futuro) → fallback a Pro."""
    assert cache._ttl_for_tier("enterprise") == cache._ttl_for_tier("pro")


def test_set_cached_uses_tier_ttl_for_free():
    """Cuando guardo con tier=free, expires_at debe ser ~72h en el futuro."""
    from datetime import datetime, timedelta
    conn = _make_db()
    before = datetime.utcnow()
    cache.set_cached(
        conn, user_id=1, screen="dashboard", packet=SAMPLE_PACKET,
        result=SAMPLE_RESULT_FREE,
        model="claude-haiku-4-5", input_tokens=500, output_tokens=200,
        tier="free",
    )
    row = conn.execute("SELECT expires_at FROM ai_analyses_cache").fetchone()
    expires = datetime.fromisoformat(row["expires_at"])
    delta = expires - before
    # Tolerancia de 60s para el wallclock del test
    expected = timedelta(hours=72)
    assert abs((delta - expected).total_seconds()) < 60, (
        f"Esperaba ~72h, fue {delta.total_seconds()}s"
    )


def test_set_cached_uses_tier_ttl_for_pro():
    """Pro mantiene el TTL clásico de 24h."""
    from datetime import datetime, timedelta
    conn = _make_db()
    before = datetime.utcnow()
    cache.set_cached(
        conn, user_id=1, screen="dashboard", packet=SAMPLE_PACKET,
        result=SAMPLE_RESULT_PRO,
        model="claude-haiku-4-5", input_tokens=1000, output_tokens=500,
        tier="pro",
    )
    row = conn.execute("SELECT expires_at FROM ai_analyses_cache").fetchone()
    expires = datetime.fromisoformat(row["expires_at"])
    delta = expires - before
    expected = timedelta(hours=24)
    assert abs((delta - expected).total_seconds()) < 60, (
        f"Esperaba ~24h, fue {delta.total_seconds()}s"
    )


# ── invalidate_for_user ──────────────────────────────────────────────────────

def test_invalidate_for_user_clears_all_tiers():
    """invalidate_for_user borra todas las filas del user — Pro y Free."""
    conn = _make_db()
    for tier in ("pro", "free"):
        cache.set_cached(
            conn, user_id=1, screen="dashboard", packet=SAMPLE_PACKET,
            result={"tldr": f"{tier} resp", "sections": [], "follow_ups": []},
            model="claude-haiku-4-5", input_tokens=1000, output_tokens=500,
            tier=tier,
        )
    n = cache.invalidate_for_user(conn, 1, screens=["dashboard"])
    assert n == 2
    assert cache.get_cached(conn, 1, "dashboard", SAMPLE_PACKET, tier="pro") is None
    assert cache.get_cached(conn, 1, "dashboard", SAMPLE_PACKET, tier="free") is None
