"""Mercado sintético para la auditoría del rendimiento desde el CSV.

Precios y dólar CONOCIDOS → el rendimiento verdadero de cualquier historia se puede
calcular exacto, y el error de Rendi se mide en puntos, no se opina.

Convenciones (las mismas que usa Rendi para cada clave de precio):
  · "AAPL"      → precio del subyacente en USD.
  · "AAPL.BA"   → CEDEAR en pesos   = USD / ratio × CCL.
  · "GGAL.BA"   → acción local en pesos (camino en USD × CCL).
  · "GD38.BA"   → bono, en pesos POR 1 nominal = USD-por-100 / 100 × MEP.
  · FX: blue, MEP y CCL distintos a propósito (como en la realidad): así se ve si
    Rendi mezcla tipos de cambio entre la reconstrucción y el cron.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

# ─── Tipo de cambio: anclas (fecha, blue_medio, mep, ccl) ─────────────────────
FX_ANCLAS = [
    ("2023-12-01", 1000, 950, 1000),
    ("2024-03-01", 1000, 1030, 1050),
    ("2024-06-01", 1300, 1350, 1370),
    ("2024-09-01", 1230, 1220, 1250),
    ("2024-12-01", 1220, 1160, 1190),
    ("2025-03-01", 1250, 1200, 1230),
    ("2025-04-15", 1300, 1200, 1210),
    ("2025-07-01", 1310, 1260, 1270),
    ("2025-10-01", 1450, 1480, 1500),
    ("2026-01-01", 1500, 1470, 1490),
    ("2026-04-01", 1520, 1480, 1500),
    ("2026-07-01", 1540, 1500, 1520),
    ("2026-10-31", 1560, 1510, 1530),
]

# ─── Instrumentos ─────────────────────────────────────────────────────────────
# us: (precio USD al 2024-01-01, deriva anual, amplitud de la onda, período en días)
US = {
    "AAPL": (185, 0.18, 0.10, 210), "MSFT": (375, 0.15, 0.08, 260),
    "NVDA": (48, 0.60, 0.18, 180), "MELI": (1570, 0.20, 0.12, 240),
    "SPY": (475, 0.14, 0.05, 300), "KO": (59, 0.06, 0.04, 200),
    "AMZN": (151, 0.22, 0.10, 230), "META": (353, 0.35, 0.12, 220),
    "GOOGL": (140, 0.20, 0.09, 250), "VIST": (35, 0.25, 0.15, 190),
    "NU": (8.3, 0.30, 0.15, 170), "TSLA": (248, 0.10, 0.25, 150),
    "GLOB": (235, -0.25, 0.10, 200), "DIA": (377, 0.10, 0.05, 280),
}
RATIO = {"AAPL": 20, "MSFT": 30, "NVDA": 24, "MELI": 120, "SPY": 20, "KO": 5,
         "AMZN": 144, "META": 24, "GOOGL": 58, "VIST": 3, "NU": 2, "TSLA": 15,
         "GLOB": 18, "DIA": 20}
# acciones locales: (USD-equivalente al 2024-01-01, deriva, amplitud, período)
AR = {"GGAL": (2.0, 0.70, 0.20, 200), "YPFD": (18.0, 0.45, 0.18, 210),
      "PAMP": (2.2, 0.40, 0.15, 230), "TGNO4": (1.5, 0.55, 0.20, 190),
      "BBAR": (3.0, 0.50, 0.20, 200), "SUPV": (1.4, 0.65, 0.25, 180),
      "ALUA": (0.9, 0.20, 0.12, 220), "AUSO": (2.4, 0.35, 0.15, 240),
      "DOLAR": (1.0, 0.0, 0.0, 365)}
# bonos: (USD por 100 VN al 2024-01-01, deriva, cupón anual % sobre VN, meses de pago)
BONOS = {"GD38": (40.0, 0.30, 4.25, (1, 7)), "GD30": (45.0, 0.28, 0.75, (1, 7)),
         "AL30": (44.0, 0.28, 0.75, (1, 7)), "AE38": (39.0, 0.30, 4.25, (1, 7))}

T0 = date(2024, 1, 1)


def _d(x) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def _camino(p0, mu, amp, per, d):
    t = (_d(d) - T0).days
    return p0 * math.exp(mu * t / 365.25 + amp * math.sin(2 * math.pi * t / per))


class Mercado:
    def __init__(self, extra_ars=None, extra_usd=None):
        """`extra_*`: {ticker: [(fecha, precio)]} — precios observados en un archivo
        real; se interpolan. Ganan sobre el camino sintético del mismo ticker."""
        self._fx = [(_d(a), b, m, c) for a, b, m, c in FX_ANCLAS]
        self.extra_ars = {k: sorted((_d(a), float(p)) for a, p in v)
                          for k, v in (extra_ars or {}).items()}
        self.extra_usd = {k: sorted((_d(a), float(p)) for a, p in v)
                          for k, v in (extra_usd or {}).items()}

    # ── FX ──
    def _interp_fx(self, d, i):
        d = _d(d)
        a = self._fx
        if d <= a[0][0]:
            return float(a[0][i])
        for (d0, *v0), (d1, *v1) in zip(a, a[1:]):
            if d0 <= d <= d1:
                w = (d - d0).days / max(1, (d1 - d0).days)
                return v0[i - 1] + w * (v1[i - 1] - v0[i - 1])
        return float(a[-1][i])

    def blue(self, d):  # punto medio
        return self._interp_fx(d, 1)

    def mep(self, d):
        return self._interp_fx(d, 2)

    def ccl(self, d):
        return self._interp_fx(d, 3)

    # ── precios ──
    @staticmethod
    def _interp(serie, d):
        d = _d(d)
        if d <= serie[0][0]:
            return serie[0][1]
        if d >= serie[-1][0]:
            return serie[-1][1]
        for (d0, p0), (d1, p1) in zip(serie, serie[1:]):
            if d0 <= d <= d1:
                w = (d - d0).days / max(1, (d1 - d0).days)
                return p0 + w * (p1 - p0)
        return serie[-1][1]

    def usd(self, tk, d):
        """Precio en USD de UNA unidad tal como se tiene en la cuenta USD."""
        if tk in self.extra_usd:
            return self._interp(self.extra_usd[tk], d)
        if tk in US:
            return _camino(*US[tk], d)
        if tk in BONOS:
            p0, mu, _, _ = BONOS[tk]
            return _camino(p0, mu, 0.05, 200, d) / 100.0          # por 1 VN
        if tk in AR:
            return _camino(*AR[tk], d)
        if tk in self.extra_ars:
            return self._interp(self.extra_ars[tk], d) / self.ccl(d)
        return None

    def ars(self, tk, d):
        """Precio en pesos de UNA unidad del instrumento local (CEDEAR, acción, bono per-1)."""
        if tk in self.extra_ars:
            return self._interp(self.extra_ars[tk], d)
        if tk in US:
            return _camino(*US[tk], d) / RATIO[tk] * self.ccl(d)
        if tk in AR:
            return _camino(*AR[tk], d) * self.ccl(d)
        if tk in BONOS:
            return self.usd(tk, d) * self.mep(d)
        if tk in self.extra_usd:
            return self._interp(self.extra_usd[tk], d) * self.ccl(d)
        return None

    def usd_de_unidad_local(self, tk, d):
        """Valor en USD de una unidad local (CEDEAR/acción/bono) — la verdad, al MEP."""
        p = self.ars(tk, d)
        return None if p is None else p / self.mep(d)

    def precio_clave(self, clave, d):
        """Lo que devolvería Yahoo/data912 para la clave de precio de Rendi."""
        if clave.endswith(".BA"):
            base = clave[:-3]
            if base.endswith("D") and base[:-1] in BONOS:      # especie D: USD por 1
                return self.usd(base[:-1], d)
            return self.ars(base, d)
        return self.usd(clave, d)

    def cupon_usd_por_vn(self, tk, d):
        """Cupón (USD por 1 VN) que paga el bono en la fecha `d`, o 0."""
        if tk not in BONOS:
            return 0.0
        _, _, c, meses = BONOS[tk]
        d = _d(d)
        return (c / 100.0) / len(meses) if (d.month in meses and d.day == 9) else 0.0


def dias(desde, hasta):
    d, h = _d(desde), _d(hasta)
    while d <= h:
        yield d
        d += timedelta(days=1)


def fin_de_mes(y, m):
    return (date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1))
