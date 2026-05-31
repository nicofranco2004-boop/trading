"""Tests para los fixes de seguridad del 2026-05-31.

Cubre:
  1. Rebill webhook signature verification:
     - is_likely_production() detecta prod via múltiples señales
     - verify_webhook_signature fail-closed en prod sin secret
     - verify_webhook_signature OK en dev local sin secret
     - validate_config escala WARN → ERROR en prod sin secret

  2. yfinance TzCache setup:
     - _setup_yfinance_cache limpia entrada corrupta (file en lugar de folder)
     - _setup_yfinance_cache crea dir si no existe
     - YF_TZ_CACHE_LOCATION env var override funciona

Estos tests son ADVERSARIALES — escenarios que rompían la seguridad antes
del fix. Si alguien revierte el fix por accidente, estos tests fallan.
"""
import hashlib
import hmac
import importlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


# ─── Helper para aislar env vars en cada test ──────────────────────────────

class EnvIsolation(unittest.TestCase):
    """Base class que limpia env vars relacionadas antes de cada test
    para que un test no contamine al siguiente.
    """
    _RELEVANT_ENV_VARS = [
        "RENDI_ENV",
        "RAILWAY_ENVIRONMENT",
        "REBILL_API_KEY",
        "REBILL_WEBHOOK_SECRET",
        "MP_WEBHOOK_SECRET",
        "YF_TZ_CACHE_LOCATION",
    ]

    def setUp(self):
        self._saved = {}
        for k in self._RELEVANT_ENV_VARS:
            if k in os.environ:
                self._saved[k] = os.environ.pop(k)

    def tearDown(self):
        for k in self._RELEVANT_ENV_VARS:
            os.environ.pop(k, None)
        for k, v in self._saved.items():
            os.environ[k] = v


# ─── 1. is_likely_production() ─────────────────────────────────────────────

class TestIsLikelyProduction(EnvIsolation):
    """Audit fix 2026-05-31: la detección de prod no puede depender solo de
    RENDI_ENV=prod. Si Nicolas no setea esa env var en Railway, su deploy
    estaba aceptando webhooks fake. Ahora múltiples señales se chequean."""

    def test_no_env_vars_returns_false(self):
        """Sin ninguna señal → dev local → False."""
        from billing import rebill
        self.assertFalse(rebill.is_likely_production())

    def test_rendi_env_prod_returns_true(self):
        os.environ["RENDI_ENV"] = "prod"
        from billing import rebill
        self.assertTrue(rebill.is_likely_production())

    def test_rendi_env_PROD_case_insensitive(self):
        os.environ["RENDI_ENV"] = "PROD"
        from billing import rebill
        self.assertTrue(rebill.is_likely_production())

    def test_railway_environment_production_returns_true(self):
        """Railway setea esta env var automáticamente — la detectamos."""
        os.environ["RAILWAY_ENVIRONMENT"] = "production"
        from billing import rebill
        self.assertTrue(rebill.is_likely_production())

    def test_railway_environment_staging_returns_false(self):
        """Staging != production. No detect."""
        os.environ["RAILWAY_ENVIRONMENT"] = "staging"
        from billing import rebill
        self.assertFalse(rebill.is_likely_production())

    def test_sk_live_api_key_returns_true(self):
        """sk_live_* es el prefijo claro de prod en Rebill."""
        os.environ["REBILL_API_KEY"] = "sk_live_abc123def456"
        from billing import rebill
        self.assertTrue(rebill.is_likely_production())

    def test_sk_test_api_key_returns_false(self):
        """sk_test_* es sandbox — NO debe detectar prod."""
        os.environ["REBILL_API_KEY"] = "sk_test_abc123def456"
        from billing import rebill
        self.assertFalse(rebill.is_likely_production())

    def test_unknown_prefix_api_key_returns_true(self):
        """Caso real de Nicolas: key tipo `sk_4d7a9_...` que no matchea
        sk_test_ ni sk_live_. Defensiva: asumir prod."""
        os.environ["REBILL_API_KEY"] = "sk_4d7a9_xxxxxxxxxxxxx"
        from billing import rebill
        self.assertTrue(rebill.is_likely_production())

    def test_empty_api_key_returns_false(self):
        """API key vacía o ausente → no detect prod (esperá tests/dev)."""
        os.environ["REBILL_API_KEY"] = ""
        from billing import rebill
        self.assertFalse(rebill.is_likely_production())


# ─── 2. verify_webhook_signature() fail-closed en prod ──────────────────────

class TestVerifyWebhookSignatureFailClosed(EnvIsolation):
    """Antes del fix: si REBILL_WEBHOOK_SECRET no estaba seteado, la función
    devolvía True (permitía el webhook) salvo en RENDI_ENV=prod estricto.
    Después del fix: devuelve False en cualquier ambiente que parezca prod.
    """

    def test_dev_local_no_secret_returns_true(self):
        """Dev local sin secret: permite (skip validation)."""
        from billing import rebill
        result = rebill.verify_webhook_signature(b'{"event": "test"}', "")
        self.assertTrue(result)

    def test_prod_no_secret_returns_false(self):
        """Producción (sk_live_ API key) sin secret: REJECT."""
        os.environ["REBILL_API_KEY"] = "sk_live_abc"
        from billing import rebill
        result = rebill.verify_webhook_signature(b'{"event": "test"}', "")
        self.assertFalse(result)

    def test_unknown_prefix_no_secret_returns_false(self):
        """Defensiva: API key con prefijo raro (caso real de Nicolas) +
        sin secret → REJECT. Antes esto pasaba silenciosamente.
        """
        os.environ["REBILL_API_KEY"] = "sk_4d7a9_realkey_xxx"
        from billing import rebill
        result = rebill.verify_webhook_signature(b'{"event": "test"}', "")
        self.assertFalse(result)

    def test_railway_production_no_secret_returns_false(self):
        os.environ["RAILWAY_ENVIRONMENT"] = "production"
        from billing import rebill
        result = rebill.verify_webhook_signature(b'{"event": "test"}', "")
        self.assertFalse(result)

    def test_prod_with_correct_hex_signature_returns_true(self):
        """Producción con secret y firma HMAC correcta (formato hex puro) → OK."""
        os.environ["RENDI_ENV"] = "prod"
        os.environ["REBILL_WEBHOOK_SECRET"] = "my_secret_value_xyz"
        from billing import rebill
        body = b'{"event": "subscription.created"}'
        expected_sig = hmac.new(
            b"my_secret_value_xyz", body, hashlib.sha256,
        ).hexdigest()
        result = rebill.verify_webhook_signature(body, expected_sig)
        self.assertTrue(result)

    def test_prod_with_wrong_signature_returns_false(self):
        """Producción con secret pero firma incorrecta → REJECT."""
        os.environ["RENDI_ENV"] = "prod"
        os.environ["REBILL_WEBHOOK_SECRET"] = "my_secret_value_xyz"
        from billing import rebill
        body = b'{"event": "subscription.created"}'
        wrong_sig = "0" * 64  # hex inválido
        result = rebill.verify_webhook_signature(body, wrong_sig)
        self.assertFalse(result)

    def test_prod_with_sha256_prefix_format_works(self):
        """Formato GitHub-style 'sha256=<hex>' también es válido."""
        os.environ["RENDI_ENV"] = "prod"
        os.environ["REBILL_WEBHOOK_SECRET"] = "my_secret_value_xyz"
        from billing import rebill
        body = b'{"event": "payment"}'
        h = hmac.new(b"my_secret_value_xyz", body, hashlib.sha256).hexdigest()
        result = rebill.verify_webhook_signature(body, f"sha256={h}")
        self.assertTrue(result)

    def test_exact_nicolas_scenario_pre_fix_was_vulnerable(self):
        """Replica el escenario EXACTO de Nicolas pre-fix:
          - REBILL_API_KEY con prefijo raro (sk_4d7a9_...)
          - Sin RENDI_ENV
          - Sin REBILL_WEBHOOK_SECRET
        Antes del fix esto devolvía True (acepta webhook fake) — vulnerability.
        Después del fix devuelve False (REJECT).
        """
        os.environ["REBILL_API_KEY"] = "sk_4d7a9_real_key_in_production"
        # NO RENDI_ENV
        # NO REBILL_WEBHOOK_SECRET
        from billing import rebill
        result = rebill.verify_webhook_signature(
            b'{"event": "subscription.activated", "metadata": {"rendi_user_id": "999"}}',
            "fake_signature_that_attacker_could_send",
        )
        # Si esto es True, el fix está roto y la vuln vuelve.
        self.assertFalse(result,
            "REGRESIÓN: webhooks sin firma se aceptan en prod (escenario exacto del bug original)")

    def test_secret_with_leading_trailing_spaces_normalized(self):
        """Si el user setea el secret con espacios extra (typo en Railway),
        el strip() debe limpiarlo. Sino fail-closed lo trataría como ausente.
        """
        os.environ["RENDI_ENV"] = "prod"
        # Espacio adelante Y atrás
        os.environ["REBILL_WEBHOOK_SECRET"] = "  my_secret_xyz  "
        from billing import rebill
        body = b'{"event": "test"}'
        # El HMAC se calcula con el secret TRIMMED
        expected = hmac.new(b"my_secret_xyz", body, hashlib.sha256).hexdigest()
        result = rebill.verify_webhook_signature(body, expected)
        self.assertTrue(result,
            "Espacios en el secret deben trimmearse — sino el fail-closed agarra")


# ─── 3. validate_config: warning → error en prod ────────────────────────────

class TestValidateConfigEscalation(EnvIsolation):
    """En prod sin REBILL_WEBHOOK_SECRET, validate_config() ahora reporta
    ERROR (no warning) — para que aparezca como crítico en los logs de boot.
    """

    def test_no_secret_in_prod_is_error(self):
        """Producción + sin secret → errors[] tiene el item, warnings no."""
        os.environ["REBILL_API_KEY"] = "sk_live_abc"
        # Set required plan IDs to isolate the test
        for combo in ["PLUS_MONTHLY", "PLUS_ANNUAL", "PRO_MONTHLY", "PRO_ANNUAL"]:
            os.environ[f"REBILL_PLAN_ID_{combo}"] = "pln_xxx"
        from billing import rebill
        result = rebill.validate_config()
        # En prod sin secret, debe estar en errors
        webhook_errors = [e for e in result["errors"] if "WEBHOOK_SECRET" in e]
        webhook_warnings = [w for w in result["warnings"] if "WEBHOOK_SECRET" in w]
        self.assertEqual(len(webhook_errors), 1,
                         f"Esperaba 1 error de webhook secret, vi: {result}")
        self.assertEqual(len(webhook_warnings), 0)
        # Cleanup
        for combo in ["PLUS_MONTHLY", "PLUS_ANNUAL", "PRO_MONTHLY", "PRO_ANNUAL"]:
            os.environ.pop(f"REBILL_PLAN_ID_{combo}", None)

    def test_no_secret_in_dev_is_warning(self):
        """Dev local sin secret → warning (no error)."""
        os.environ["REBILL_API_KEY"] = "sk_test_abc"
        for combo in ["PLUS_MONTHLY", "PLUS_ANNUAL", "PRO_MONTHLY", "PRO_ANNUAL"]:
            os.environ[f"REBILL_PLAN_ID_{combo}"] = "test_pln_xxx"
        from billing import rebill
        result = rebill.validate_config()
        webhook_errors = [e for e in result["errors"] if "WEBHOOK_SECRET" in e]
        webhook_warnings = [w for w in result["warnings"] if "WEBHOOK_SECRET" in w]
        self.assertEqual(len(webhook_errors), 0)
        self.assertEqual(len(webhook_warnings), 1)
        for combo in ["PLUS_MONTHLY", "PLUS_ANNUAL", "PRO_MONTHLY", "PRO_ANNUAL"]:
            os.environ.pop(f"REBILL_PLAN_ID_{combo}", None)


# ─── 4. yfinance TzCache setup ──────────────────────────────────────────────

class TestYfinanceCacheSetup(EnvIsolation):
    """Audit fix 2026-05-31: yfinance defaulteaba a /root/.cache/py-yfinance
    que existía como FILE corrupto. Ahora apuntamos a un path controlado y
    limpiamos el FILE si está en el medio."""

    def test_setup_uses_default_tmp_path(self):
        """Sin override, usa /tmp/yf-cache (efímero, regenerable)."""
        # Importar tarde y solo testear que no crashea + no hace nada raro
        from main import _setup_yfinance_cache
        # No setear YF_TZ_CACHE_LOCATION → usa /tmp/yf-cache
        _setup_yfinance_cache()  # No assertions: solo verificar no-crash
        self.assertTrue(os.path.isdir("/tmp/yf-cache"))

    def test_setup_respects_env_override(self):
        """Si YF_TZ_CACHE_LOCATION está seteada, se usa ese path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "yf-custom-cache")
            os.environ["YF_TZ_CACHE_LOCATION"] = custom_path
            from main import _setup_yfinance_cache
            _setup_yfinance_cache()
            self.assertTrue(os.path.isdir(custom_path))

    def test_setup_removes_corrupt_file(self):
        """Si el path existe como FILE (caso real del bug), lo borra y
        recrea como directorio."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "corrupt-cache")
            # Crear un FILE (no folder) en ese path — simulando el bug
            with open(custom_path, "w") as f:
                f.write("garbage")
            self.assertTrue(os.path.isfile(custom_path))
            os.environ["YF_TZ_CACHE_LOCATION"] = custom_path
            from main import _setup_yfinance_cache
            _setup_yfinance_cache()
            # Después del fix, debe ser un directorio
            self.assertTrue(os.path.isdir(custom_path))
            self.assertFalse(os.path.isfile(custom_path))

    def test_setup_does_not_crash_on_unwritable_path(self):
        """Si el path no se puede crear (permissions, fs read-only, etc.)
        no debe romper el boot. yfinance sigue sin cache."""
        os.environ["YF_TZ_CACHE_LOCATION"] = "/root/this-path-cannot-be-created"
        from main import _setup_yfinance_cache
        # No debe levantar excepción
        try:
            _setup_yfinance_cache()
        except Exception as e:
            self.fail(f"_setup_yfinance_cache no debería crashear: {e}")


if __name__ == "__main__":
    unittest.main()
