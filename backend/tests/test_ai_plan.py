"""Tests para backend/ai/plan.py — feature gates + grandfather logic."""
from __future__ import annotations
import sqlite3
import pytest

from ai import plan


def _make_db(*, n_brokers_user2: int = 0, n_brokers_user1: int = 0):
    """In-memory SQLite con tablas users + brokers para feature gate tests.

    Setup:
      • user_id=1 → admin (is_admin=1)
      • user_id=2 → free (is_admin=0)
      • Opcionalmente: pre-cargamos N brokers para cada user (para
        testear quotas + grandfather).
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT,
            is_admin INTEGER DEFAULT 0,
            tier TEXT
        );
        INSERT INTO users (id, email, is_admin) VALUES (1, 'admin@x.com', 1);
        INSERT INTO users (id, email, is_admin) VALUES (2, 'free@x.com', 0);

        CREATE TABLE brokers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            currency TEXT,
            parent_broker_id INTEGER REFERENCES brokers(id)
        );
    """)
    for i in range(n_brokers_user1):
        conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?, ?, 'USD')",
            (1, f"AdminBroker{i}"),
        )
    for i in range(n_brokers_user2):
        conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?, ?, 'USD')",
            (2, f"FreeBroker{i}"),
        )
    conn.commit()
    return conn


# ── FEATURE_IDS coverage ─────────────────────────────────────────────────────

def test_all_features_declared_in_all_tiers():
    """Cada feature_id de FEATURE_IDS debe tener entrada en los 3 tiers.

    Esto previene bugs donde agregás una feature y olvidás declararla en
    algún tier (fallaría silenciosamente devolviendo False)."""
    for tier in ("free", "pro", "admin"):
        for fid in plan.FEATURE_IDS:
            assert fid in plan.PLAN_LIMITS[tier]["can_access"], (
                f"Feature '{fid}' falta en tier '{tier}'"
            )


# ── can_access ───────────────────────────────────────────────────────────────

def test_free_cannot_access_paywalled_features():
    conn = _make_db()
    for fid in plan.FEATURE_IDS:
        # Free no debe tener acceso a NINGUNA feature paywallable
        assert plan.can_access(conn, 2, fid) is False, f"Free no debería acceder a {fid}"


def test_pro_accesses_most_features_except_coming_soon():
    """Pro accede a las features liberadas. AI Hub + Tax Helper son
    próximamente y solo admin los tiene en pre-launch."""
    pro = plan.PLAN_LIMITS["pro"]["can_access"]
    # Features liberadas
    assert pro["ai.followup"] is True
    assert pro["comportamiento.full"] is True
    assert pro["insights.distribucion_activo"] is True
    assert pro["reportes.historicos"] is True
    assert pro["export.csv"] is True
    # Features próximamente — NO disponibles aún para Pro
    assert pro["ai.hub"] is False
    assert pro["tax.helper"] is False


def test_admin_accesses_everything_including_hub():
    """Admin tiene acceso TOTAL — incluso a features en desarrollo (Hub)."""
    conn = _make_db()
    for fid in plan.FEATURE_IDS:
        assert plan.can_access(conn, 1, fid) is True, f"Admin debería acceder a {fid}"


def test_unknown_feature_id_denied():
    """Feature no declarada en FEATURE_IDS → False (fail-safe defensivo)."""
    conn = _make_db()
    assert plan.can_access(conn, 1, "nonexistent.feature") is False
    assert plan.can_access(conn, 2, "nonexistent.feature") is False


# ── check_broker_quota ───────────────────────────────────────────────────────

def test_broker_quota_free_zero_brokers_can_create():
    """Free sin brokers puede crear el primero."""
    conn = _make_db(n_brokers_user2=0)
    allowed, info = plan.check_broker_quota(conn, 2)
    assert allowed is True
    assert info["current_count"] == 0
    assert info["limit"] == 1
    assert info["grandfather"] is False


def test_broker_quota_free_one_broker_at_limit():
    """Free con 1 broker está en el cap — NO puede crear más."""
    conn = _make_db(n_brokers_user2=1)
    allowed, info = plan.check_broker_quota(conn, 2)
    assert allowed is False
    assert info["current_count"] == 1
    assert info["limit"] == 1
    assert info["grandfather"] is False


def test_broker_quota_free_grandfather_existing_keeps_brokers():
    """Free preexistente con 3 brokers (legacy, antes del paywall):
    los 3 brokers se preservan pero NO puede agregar más."""
    conn = _make_db(n_brokers_user2=3)
    allowed, info = plan.check_broker_quota(conn, 2)
    assert allowed is False, "Grandfather: ya superó cap, no puede agregar más"
    assert info["current_count"] == 3
    assert info["limit"] == 1
    assert info["grandfather"] is True, "Debería marcar grandfather=True"


def test_broker_quota_admin_unlimited():
    """Admin no tiene límite — puede crear muchos."""
    conn = _make_db(n_brokers_user1=50)
    allowed, info = plan.check_broker_quota(conn, 1)
    assert allowed is True
    assert info["limit"] is None
    assert info["grandfather"] is False  # sin límite, no aplica


# ── get_plan_features ────────────────────────────────────────────────────────

def test_get_plan_features_free_shape():
    conn = _make_db(n_brokers_user2=1)
    out = plan.get_plan_features(conn, 2)
    assert out["tier"] == "free"
    assert out["limits"]["brokers_max"] == 1
    assert out["limits"]["brokers_current"] == 1
    assert out["limits"]["brokers_can_create"] is False
    assert out["limits"]["brokers_grandfather"] is False
    assert out["limits"]["insights_diagnostic_visible"] == 3
    assert out["limits"]["behavioral_tags_visible"] == 3
    # Free no tiene acceso a ninguna feature paywallable
    assert all(v is False for v in out["access"].values())


def test_get_plan_features_admin_shape():
    conn = _make_db(n_brokers_user1=5)
    out = plan.get_plan_features(conn, 1)
    assert out["tier"] == "admin"
    assert out["limits"]["brokers_max"] is None
    assert out["limits"]["brokers_current"] == 5
    assert out["limits"]["brokers_can_create"] is True
    assert out["limits"]["insights_diagnostic_visible"] is None
    # Admin ve TODO (incluso ai.hub)
    assert all(v is True for v in out["access"].values())


def test_get_plan_features_grandfather_flag():
    """get_plan_features expone grandfather=True para UI hints (ej. mostrar
    'Tenés N brokers — mantenelos, pero el plan Free permite 1')."""
    conn = _make_db(n_brokers_user2=4)
    out = plan.get_plan_features(conn, 2)
    assert out["tier"] == "free"
    assert out["limits"]["brokers_current"] == 4
    assert out["limits"]["brokers_max"] == 1
    assert out["limits"]["brokers_grandfather"] is True
    assert out["limits"]["brokers_can_create"] is False


# ── Integridad: límites Free son STRICTAMENTE menores que Pro/Admin ─────────

def test_free_limits_stricter_than_pro():
    """Cualquier límite numérico de Free debe ser menor (más restrictivo)
    que el equivalente Pro. Si esto falla, el paywall no diferencia."""
    free = plan.PLAN_LIMITS["free"]
    pro = plan.PLAN_LIMITS["pro"]
    # brokers_max
    assert free["brokers_max"] is not None
    assert pro["brokers_max"] is None or pro["brokers_max"] > free["brokers_max"]
    # diagnostic visibility
    assert free["insights_diagnostic_visible"] is not None
    assert (
        pro["insights_diagnostic_visible"] is None
        or pro["insights_diagnostic_visible"] > free["insights_diagnostic_visible"]
    )
    # behavioral tags
    assert free["behavioral_tags_visible"] is not None
    assert (
        pro["behavioral_tags_visible"] is None
        or pro["behavioral_tags_visible"] > free["behavioral_tags_visible"]
    )


# ── el sub-broker "· USD" no come cupo ───────────────────────────────────────
# Regresión: `_ensure_usd_sibling` inserta el sibling directo, SIN pasar por la
# cuota, y después el COUNT(*) pelado se lo cobraba al usuario. Un Plus con 2
# brokers reales contaba 4 y no podía crear el tercero que pagó.

def _add_sibling(conn, user_id: int, parent_name: str):
    """Replica lo que hace `_ensure_usd_sibling`: fila propia, currency USDT,
    parent_broker_id apuntando al padre."""
    parent = conn.execute(
        "SELECT id FROM brokers WHERE user_id=? AND name=?",
        (user_id, parent_name),
    ).fetchone()
    conn.execute(
        "INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
        "VALUES (?, ?, 'USDT', ?)",
        (user_id, f"{parent_name} · USD", parent["id"]),
    )
    conn.commit()


def test_sibling_usd_no_consume_cupo():
    """Free con 1 broker AR bimonetario sigue teniendo 1 cuenta, no 2."""
    conn = _make_db(n_brokers_user2=1)
    _add_sibling(conn, 2, "FreeBroker0")

    assert conn.execute(
        "SELECT COUNT(*) c FROM brokers WHERE user_id=2"
    ).fetchone()["c"] == 2, "precondición: hay 2 FILAS en brokers"

    allowed, info = plan.check_broker_quota(conn, 2)
    assert info["current_count"] == 1, "el sibling no es una cuenta aparte"
    assert allowed is False, "1 broker real ya es el cap de free"
    assert info["grandfather"] is False, (
        "grandfather=True acá sería falso: no superó el cap, sólo tiene un sibling"
    )


def test_sibling_usd_no_bloquea_el_broker_que_el_plus_pago():
    """El caso que rompía: 2 brokers reales + 2 siblings contra brokers_max=3.

    Sin el filtro cuenta 4 y le rebota el alta del tercero."""
    assert plan.PLAN_LIMITS["plus"]["brokers_max"] == 3, (
        "el test asume el tope de Plus; si cambió, actualizá el caso"
    )
    conn = _make_db()
    conn.execute("UPDATE users SET tier='plus' WHERE id=2")
    for n in ("IOL", "Balanz"):
        conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (2, ?, 'ARS')",
            (n,),
        )
    conn.commit()
    for n in ("IOL", "Balanz"):
        _add_sibling(conn, 2, n)

    allowed, info = plan.check_broker_quota(conn, 2)
    assert info["current_count"] == 2, f"2 cuentas reales, no {info['current_count']}"
    assert allowed is True, "tiene que poder crear el tercer broker"


def test_get_plan_features_no_cuenta_el_sibling():
    """El mismo número que ve el frontend en limits.brokers_current."""
    conn = _make_db(n_brokers_user2=1)
    _add_sibling(conn, 2, "FreeBroker0")
    out = plan.get_plan_features(conn, 2)
    assert out["limits"]["brokers_current"] == 1


def test_huerfano_cuenta_como_cuenta_propia():
    """Un sibling cuyo padre ya no existe se dibuja como tarjeta suelta en la
    Cartera (`sortBrokersForDisplay` lo re-emite como standalone), así que
    tiene que ocupar cupo: si no, se ve en pantalla y no se cobra."""
    conn = _make_db(n_brokers_user2=1)
    _add_sibling(conn, 2, "FreeBroker0")
    conn.execute("DELETE FROM brokers WHERE user_id=2 AND name='FreeBroker0'")
    conn.commit()

    assert plan.count_broker_accounts(conn, 2) == 1, (
        "el huérfano quedó solo: es 1 cuenta, no 0"
    )
