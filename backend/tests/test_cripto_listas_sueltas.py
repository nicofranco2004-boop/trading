"""«¿Esto es cripto?» tiene UNA respuesta: la lista de la app (`cripto.py`).

Hasta 2026-10-08 la lista de cripto (`main.CRYPTO_SYMBOLS`, 124 códigos) decidía
cómo se VALÚA una tenencia, pero cinco lugares que deciden qué ES tenían su
propia lista de 13 a 36 códigos:

  · el importador (`normalizer._CRYPTO_HINTS`, 19): una compra de PEPE, KAS o
    FET sin tipo en el archivo (Binance, Schwab, IEB, PPI, Bull Market y el CSV
    genérico no lo mandan) se guardaba OTHER;
  · Mervall-E AI por país (`insights._CRYPTO_HINT`, 13 + «broker = binance»):
    esa misma tenencia en Ripio o en una billetera era «exposición a EE.UU.»;
    y el armador ni siquiera leía `asset_type`, así que lo que el importador
    marcó CRYPTO (ROSE comprada en un exchange) tampoco contaba;
  · la tarjeta de perfil de la IA (`profile_card.crypto_set`, 14) y su gemela
    en pantalla (`profileAllocations.classifyAssetBucket`, 36): «equity»
    mientras la torta de al lado decía Cripto;
  · los grupos del asesor (la lista del chat: le faltan WBTC, stETH, EOS…);
  · el sector del diagnóstico (`behavioral._SECTOR_MAP`, 16): «Otros».

Todo entra por las puertas reales: el CSV por `POST /api/imports/preview` +
`/confirm`, lo que leen las pantallas (`/api/positions`,
`/api/behavioral/insights`), los armadores de la IA tal como los llama el
endpoint (`ai.registry.REGISTRY`) y los grupos del asesor
(`advisor_groups.client_profiles`). Reemplazado sólo lo que sale a internet.

Corre con: cd backend && python3 -m pytest tests/test_cripto_listas_sueltas.py
"""
import ast
import io
import json
import os
import re
import sys
import time
import unittest
import uuid
from unittest import mock

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import analysis_prep  # noqa: E402
import cripto  # noqa: E402
import home.market as market  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from ai.registry import REGISTRY  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

REPO = os.path.dirname(BACKEND)
GENERICO = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"

# Una billetera en dólares: ni exchange (no la salva «broker = binance») ni
# broker argentino. PEPE, KAS y FET no estaban en ninguna de las listas sueltas;
# WBTC sí estaba en la lista de la app pero no en la del chat (los grupos del
# asesor). AAPL y DASH (DoorDash: la cripto Dash queda afuera a propósito) son
# acciones.
COMPRAS = {"PEPE": (1_000_000, 0.001), "KAS": (10_000, 0.05), "FET": (1_000, 0.3),
           "WBTC": (0.01, 60_000), "AAPL": (10, 200), "DASH": (5, 200)}
CRIPTO = {"PEPE", "KAS", "FET", "WBTC"}
DEPOSITO = 10_000


def _buscar(d, clave):
    """El primer valor de `clave` en un dict anidado (el packet de la IA)."""
    if isinstance(d, dict):
        if clave in d:
            return d[clave]
        for v in d.values():
            r = _buscar(v, clave)
            if r is not None:
                return r
    elif isinstance(d, list):
        for v in d:
            r = _buscar(v, clave)
            if r is not None:
                return r
    return None


class CriptoFueraDeLasListasViejas(unittest.TestCase):

    def setUp(self):
        conn = main.get_db()
        sufijo = uuid.uuid4().hex[:10]
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, investor_profile) VALUES (?,?,1,?)",
            (f"cripto-{sufijo}@rendi.test", "x",
             json.dumps({"horizon": "long", "drawdown": "medium", "goal": "growth",
                         "style": "buy_hold", "experience": "intermediate"}))).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "Wallet", "USD"))
        self.asesor = conn.execute(
            "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,'advisor')",
            (f"asesor-{sufijo}@rendi.test", "x")).lastrowid
        conn.execute("INSERT INTO advisor_clients (advisor_uid, client_uid, link_type, "
                     "permission, status, label) VALUES (?,?,'managed','read_write','active','C')",
                     (self.asesor, self.uid))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.http = TestClient(main.app)
        for p in (mock.patch.object(main, "_fetch_data912_bonds", return_value={}),
                  mock.patch.object(market, "_fetch_batch_quotes", return_value={}),
                  mock.patch.object(analysis_prep, "fetch_ba_aware_prices", return_value={})):
            p.start()
            self.addCleanup(p.stop)
        self._fetch_orig = bf._fetch_monthly_close
        bf._HIST_CACHE.clear()
        bf._fetch_monthly_close = lambda price_key, start_iso: {}
        self._importar()

    def tearDown(self):
        bf._fetch_monthly_close = self._fetch_orig
        bf._HIST_CACHE.clear()

    def _importar(self):
        filas = GENERICO + f"2025-03-01,DEPOSITO,Wallet,,,,{DEPOSITO},,,0,USD,\n"
        for activo, (qty, precio) in COMPRAS.items():
            filas += f"2025-03-02,COMPRA,Wallet,{activo},{qty},{precio},{qty * precio},,,0,USD,\n"
        p = self.http.post("/api/imports/preview",
                           files=[("files", ("w.csv", io.BytesIO(filas.encode()), "text/csv"))],
                           data={"format": "rendi_generic", "broker": "Wallet"}, headers=self.h)
        self.assertEqual(p.status_code, 200, p.text)
        c = self.http.post("/api/imports/confirm",
                           json={"session_id": p.json()["session_id"],
                                 "skip_row_indices": [], "aprobar_tickers": []},
                           headers=self.h)
        self.assertEqual(c.status_code, 200, c.text)
        limite = time.time() + 60
        while time.time() < limite:
            with main._MTM_RUNNING_LOCK:
                if self.uid not in main._MTM_RUNNING:
                    return
            time.sleep(0.02)
        self.fail("la reconstrucción no terminó en 60 s")

    def _get(self, ruta):
        r = self.http.get(ruta, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _costo(self, activos):
        return sum(COMPRAS[a][0] * COMPRAS[a][1] for a in activos)

    # ── 1. El importador ─────────────────────────────────────────────────────
    def test_el_importador_anota_cripto_lo_que_la_app_valua_como_cripto(self):
        tipos = {p["asset"]: p.get("asset_type") for p in self._get("/api/positions")
                 if not p.get("is_cash")}
        self.assertEqual(set(tipos), set(COMPRAS))
        for a in CRIPTO:
            self.assertEqual(tipos[a], "CRYPTO", a)          # antes: OTHER
        self.assertEqual(tipos["AAPL"], "OTHER")
        self.assertEqual(tipos["DASH"], "OTHER")             # DoorDash, no la cripto

    # ── 2. Mervall-E AI por país ─────────────────────────────────────────────
    def _exposicion(self):
        conn = main.get_db()
        try:
            packet = REGISTRY["insights"][0](conn, self.uid)
        finally:
            conn.close()
        exp = _buscar(packet, "exposure")
        self.assertIsNotNone(exp, "el packet no trae exposure")
        return exp

    def test_la_ia_cuenta_la_cripto_como_cripto(self):
        exp = self._exposicion()
        # Sin precio de mercado (Yahoo apagado) cada tenencia vale su costo.
        self.assertAlmostEqual(exp["crypto_pct"], round(self._costo(CRIPTO) / DEPOSITO * 100, 1))
        self.assertAlmostEqual(exp["us_pct"], round(self._costo({"AAPL", "DASH"}) / DEPOSITO * 100, 1))

    def test_la_ia_lee_el_tipo_que_anoto_el_importador(self):
        """ROSE marcada CRYPTO (comprada en un exchange en pesos) es la cripto
        Oasis, no Rosenbusch. El armador no leía la columna asset_type: llamar a
        `_classify_geography` con un dict armado a mano daba verde igual."""
        conn = main.get_db()
        try:
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                         (self.uid, "Santander", "ARS"))
            conn.execute("INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, "
                         "invested, quantity, commissions, currency) "
                         "VALUES (?,?,?,?,0,?,?,0,?)",
                         (self.uid, "Santander", "ROSE", "CRYPTO", 2_000_000, 100, "ARS"))
            conn.commit()
        finally:
            conn.close()
        exp = self._exposicion()
        self.assertEqual(exp["ar_pct"], 0.0)                 # antes: la ROSE era argentina
        self.assertGreater(exp["crypto_pct"], round(self._costo(CRIPTO) / DEPOSITO * 100, 1))

    # ── 3. La tarjeta de perfil de la IA ─────────────────────────────────────
    def test_la_tarjeta_de_perfil_dice_alternativo(self):
        conn = main.get_db()
        try:
            packet = REGISTRY["profile.card"][0](conn, self.uid, code="allocation")
        finally:
            conn.close()
        b = packet["card"]["actual"]["buckets_pct"]
        self.assertEqual(b["alternative"], round(self._costo(CRIPTO) / DEPOSITO * 100))  # antes: 0
        self.assertEqual(b["equity"], round(self._costo({"AAPL", "DASH"}) / DEPOSITO * 100))

    # ── 4. Los grupos del asesor ─────────────────────────────────────────────
    def test_los_grupos_del_asesor_ven_la_cripto(self):
        import advisor_groups as ag
        conn = main.get_db()
        try:
            prof = ag.client_profiles(conn, self.asesor)[self.uid]
        finally:
            conn.close()
        self.assertAlmostEqual(prof["by_class"]["crypto"], self._costo(CRIPTO), places=2)
        self.assertAlmostEqual(prof["by_class"]["us_stock"], self._costo({"AAPL", "DASH"}), places=2)

    def test_wbtc_es_cripto_para_los_grupos(self):
        """WBTC/stETH/EOS: la app las valúa como cripto pero no están en la
        lista del chat, que era la que usaban los grupos."""
        import advisor_groups as ag
        for s in ("WBTC", "STETH", "EOS", "ICX", "PEPE", "KAS"):
            self.assertEqual(ag.classify(s, None, False), "crypto", s)
        self.assertNotEqual(ag.classify("DASH", None, False), "crypto")

    # ── 5. El sector del diagnóstico ─────────────────────────────────────────
    def test_el_diagnostico_de_sectores_la_llama_cripto(self):
        cards = self._get("/api/behavioral/insights")
        cards = cards.get("cards", cards) if isinstance(cards, dict) else cards
        sector = next(c for c in cards if c.get("code") == "sector_concentration")
        por_sector = {f["sector"]: f["value_usd"] for f in sector["evidence"]["breakdown"]}
        self.assertAlmostEqual(por_sector.get("Crypto", 0), self._costo(CRIPTO), places=2)


# ── Guards: no vuelve a aparecer una lista suelta ───────────────────────────

# Archivos que PUEDEN nombrar criptos en un set/lista: la lista misma, los
# catálogos que la guard de test_cripto_sin_lista ata a ella (chat y nombres),
# y los parsers de Binance (monedas de cotización de un par, otra pregunta).
_PERMITIDOS_BE = {
    "cripto.py", os.path.join("ai", "trade_tickers.py"), os.path.join("ai", "asset_names.py"),
    os.path.join("importing", "parsers", "binance.py"),
    os.path.join("importing", "parsers", "binance_transaction.py"),
}


def _literales_con_cripto(path):
    """Sets/listas/tuplas/dicts literales que nombran a la vez BTC y ETH."""
    arbol = ast.parse(open(path, encoding="utf-8").read())
    out = []
    for n in ast.walk(arbol):
        if isinstance(n, (ast.Set, ast.List, ast.Tuple)):
            elems = n.elts
        elif isinstance(n, ast.Dict):
            elems = [k for k in n.keys if k is not None]
        else:
            continue
        strs = {e.value for e in elems if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        if {"BTC", "ETH"} <= strs:
            out.append(n.lineno)
    return out


def test_no_hay_otra_lista_de_cripto_en_el_servidor():
    sueltas = []
    for raiz, dirs, files in os.walk(BACKEND):
        dirs[:] = [d for d in dirs if d not in ("tests", "scripts", "__pycache__", "venv", ".venv")]
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(raiz, f)
            rel = os.path.relpath(path, BACKEND)
            if rel in _PERMITIDOS_BE:
                continue
            sueltas += [f"{rel}:{ln}" for ln in _literales_con_cripto(path)]
    assert sueltas == [], ("lista de cripto suelta (usá cripto.es_cripto / "
                           f"es_tenencia_cripto): {sueltas}")


def test_las_listas_viejas_eran_subconjunto():
    """Unificar no le saca a nadie el «es cripto»: todo lo que las listas
    sueltas llamaban cripto, la lista de la app también (salvo HYPE, que la app
    no sabe valuar, y DAI, que la tarjeta trata como efectivo)."""
    viejas = {"BTC", "ETH", "USDT", "USDC", "SOL", "ADA", "BNB", "DOGE", "MATIC", "ARB",
              "AVAX", "DOT", "LINK", "LTC", "XRP", "ATOM", "NEAR", "OP", "TRX", "AAVE",
              "BCH"}
    assert all(cripto.es_cripto(s) for s in viejas)


def test_es_cripto():
    assert cripto.es_cripto("pepe") and cripto.es_cripto("PEPE-USD") and cripto.es_cripto("USDT")
    for s in ("AAPL", "DASH", "ROSE", "CVX", "AGIX", "", None, "BTC.BA"):
        assert not cripto.es_cripto(s), s
    assert cripto.es_tenencia_cripto({"asset": "ROSE", "asset_type": "CRYPTO"})
    assert not cripto.es_tenencia_cripto({"asset": "ROSE", "asset_type": "AR_STOCK"})


def test_main_reexporta_la_misma_lista():
    """Los que leen `main.CRYPTO_SYMBOLS` (la valuación, la foto diaria, las
    alertas) y los que leen `cripto` ven el MISMO objeto, no una copia."""
    assert main.CRYPTO_SYMBOLS is cripto.CRYPTO_SYMBOLS
    assert main.CRYPTO_YF is cripto.CRYPTO_YF
    assert main.CRYPTO_BROKER_NAMES is cripto.CRYPTO_BROKER_NAMES
    assert main.yahoo_de_cripto is cripto.yahoo_de_cripto


def test_las_estables_de_la_tarjeta_son_las_de_la_torta():
    """profile_card manda las stables a efectivo igual que la pantalla
    (assetClass.js STABLECOINS, que ahora usa también classifyAssetBucket)."""
    from ai.builders.profile_card import _STABLECOINS
    src = open(os.path.join(REPO, "frontend", "src", "utils", "assetClass.js"), encoding="utf-8").read()
    m = re.search(r"const STABLECOINS = new Set\(\[([^\]]*)\]\)", src)
    assert m
    assert set(re.findall(r"'([A-Z0-9]+)'", m.group(1))) == _STABLECOINS


def test_las_estables_del_front_son_las_del_servidor():
    src = open(os.path.join(REPO, "frontend", "src", "utils", "crypto.js"), encoding="utf-8").read()
    m = re.search(r"CRIPTO_ESTABLES = new Set\(\[([^\]]*)\]\)", src)
    assert m
    assert set(re.findall(r"'([A-Z0-9]+)'", m.group(1))) == cripto.CRIPTO_ESTABLES
