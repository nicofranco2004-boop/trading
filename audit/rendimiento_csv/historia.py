"""Una historia económica de inversor con su VERDAD calculada a mano.

La misma historia se escribe después en el formato de cada broker (generadores.py):
lo que cambia entre brokers es sólo la traducción, así cualquier diferencia en el
número que publica Rendi es del parser/pipeline, no de la historia.

Verdad (en USD, ARS valuado al MEP del día — lo que el inversor obtendría al
dolarizarse por la vía legal):
  · `twr_verdad(desde, hasta)`: TWR diario exacto (flujo al inicio del día).
  · `contable_verdad`: la cadena contable que el Estimado dice reproducir —
    capital = aportes netos + realizado (FIFO en USD + cobros − comisiones) —,
    con Dietz mensual, sin lo no realizado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional

from mercado import Mercado, BONOS, US, AR, dias, fin_de_mes

COMISION = 0.006  # 0,6 % de cada operación, dentro del importe neto


@dataclass
class Ev:
    fecha: str
    tipo: str                 # DEP | WD | BUY | SELL | DIV | CUPON | MEP
    moneda: str = "ARS"       # moneda de la plata
    monto: float = 0.0        # DEP/WD/DIV/CUPON/MEP(ARS que salen)
    tk: Optional[str] = None
    qty: float = 0.0
    px: float = 0.0           # precio unitario en `moneda`
    clase: str = ""           # CEDEAR | ACCION | BONO
    neto: float = 0.0         # importe neto (con comisión) en `moneda`
    usd_recibidos: float = 0.0  # MEP
    nota: str = ""


def _clase(tk):
    return "BONO" if tk in BONOS else ("CEDEAR" if tk in US else "ACCION")


@dataclass
class Historia:
    m: Mercado
    eventos: List[Ev] = field(default_factory=list)

    def _px(self, tk, f, moneda):
        """Precio unitario en la moneda en que se opera. Un CEDEAR/acción comprado
        con dólares MEP cotiza a precio-en-pesos ÷ MEP (la especie D)."""
        if moneda == "ARS":
            px = self.m.ars(tk, f)
        elif tk in BONOS:
            px = self.m.usd(tk, f)
        else:
            px = self.m.ars(tk, f) / self.m.mep(f)
        return round(px, 4 if px < 10 else 2)

    # ── constructores de eventos (precios del mercado de ese día) ──
    def dep(self, f, monto, moneda="ARS"):
        self.eventos.append(Ev(f, "DEP", moneda, monto))

    def wd(self, f, monto, moneda="ARS"):
        self.eventos.append(Ev(f, "WD", moneda, monto))

    def buy(self, f, tk, qty, moneda="ARS"):
        px = self._px(tk, f, moneda)
        neto = round(qty * px * (1 + COMISION), 2)
        self.eventos.append(Ev(f, "BUY", moneda, tk=tk, qty=qty, px=px, clase=_clase(tk), neto=neto))

    def sell(self, f, tk, qty, moneda="ARS"):
        px = self._px(tk, f, moneda)
        neto = round(qty * px * (1 - COMISION), 2)
        self.eventos.append(Ev(f, "SELL", moneda, tk=tk, qty=qty, px=px, clase=_clase(tk), neto=neto))

    def div(self, f, tk, monto, moneda):
        self.eventos.append(Ev(f, "DIV", moneda, round(monto, 2), tk=tk, clase=_clase(tk)))

    def cupon(self, f, tk, qty_vn):
        c = self.m.cupon_usd_por_vn(tk, f)
        assert c > 0, (tk, f)
        self.eventos.append(Ev(f, "CUPON", "USD", round(qty_vn * c, 2), tk=tk, clase="BONO"))

    def tin(self, f, tk, qty):
        """Transferencia de títulos DESDE otro broker: aporte en especie, a valor de mercado."""
        px = self._px(tk, f, "ARS")
        self.eventos.append(Ev(f, "TIN", "ARS", tk=tk, qty=qty, px=px, clase=_clase(tk)))

    def mep(self, f, ars):
        """Compra de dólar MEP: salen `ars` pesos, entran ars/MEP dólares."""
        usd = round(ars / self.m.mep(f), 2)
        self.eventos.append(Ev(f, "MEP", "ARS", ars, usd_recibidos=usd))

    # ── estado día por día ──
    def estado(self, hasta=None):
        """Recorre los eventos y devuelve {fecha: (cash_ars, cash_usd, holdings)}
        al cierre de cada día con evento, más la función de valor."""
        evs = sorted(self.eventos, key=lambda e: (e.fecha, e.tipo not in ("DEP",)))
        return evs

    def simular(self):
        """Valor diario (USD al MEP), flujos diarios (USD) y caja/holdings."""
        evs = self.estado()
        d0 = date.fromisoformat(evs[0].fecha)
        hoy = date.today()
        cash = {"ARS": 0.0, "USD": 0.0}
        hold = {}
        lotes = {}      # tk -> [(qty, costo_usd_unit)]
        realizado = {}  # fecha -> realizado USD del día (FIFO + cobros − comisiones)
        valor, flujo = {}, {}
        i = 0
        for d in dias(d0, hoy):
            ds = d.isoformat()
            f_usd = 0.0
            while i < len(evs) and evs[i].fecha == ds:
                e = evs[i]
                mep = self.m.mep(d)
                a_usd = (lambda x, c: x if c == "USD" else x / mep)
                if e.tipo == "DEP":
                    cash[e.moneda] += e.monto
                    f_usd += a_usd(e.monto, e.moneda)
                elif e.tipo == "WD":
                    cash[e.moneda] -= e.monto
                    f_usd -= a_usd(e.monto, e.moneda)
                elif e.tipo == "BUY":
                    cash[e.moneda] -= e.neto
                    hold[e.tk] = hold.get(e.tk, 0) + e.qty
                    lotes.setdefault(e.tk, []).append([e.qty, a_usd(e.qty * e.px, e.moneda) / e.qty])
                    realizado[ds] = realizado.get(ds, 0) - a_usd(e.neto - e.qty * e.px, e.moneda)
                elif e.tipo == "SELL":
                    cash[e.moneda] += e.neto
                    hold[e.tk] -= e.qty
                    q, costo = e.qty, 0.0
                    while q > 1e-9:
                        lq, lc = lotes[e.tk][0]
                        t = min(q, lq)
                        costo += t * lc
                        q -= t
                        lotes[e.tk][0][0] -= t
                        if lotes[e.tk][0][0] <= 1e-9:
                            lotes[e.tk].pop(0)
                    realizado[ds] = realizado.get(ds, 0) + a_usd(e.neto, e.moneda) - costo
                elif e.tipo in ("DIV", "CUPON"):
                    cash[e.moneda] += e.monto
                    realizado[ds] = realizado.get(ds, 0) + a_usd(e.monto, e.moneda)
                elif e.tipo == "TIN":
                    hold[e.tk] = hold.get(e.tk, 0) + e.qty
                    vu = e.qty * self.m.usd_de_unidad_local(e.tk, d)
                    lotes.setdefault(e.tk, []).append([e.qty, vu / e.qty])
                    f_usd += vu
                elif e.tipo == "MEP":
                    cash["ARS"] -= e.monto
                    cash["USD"] += e.usd_recibidos
                    realizado[ds] = realizado.get(ds, 0) + e.usd_recibidos - e.monto / mep
                assert cash["ARS"] > -1 and cash["USD"] > -0.01, (ds, e, cash)
                i += 1
            v = cash["ARS"] / self.m.mep(d) + cash["USD"]
            for tk, q in hold.items():
                if q > 1e-9:
                    v += q * self.m.usd(tk, d) if tk in BONOS else q * self.m.usd_de_unidad_local(tk, d)
            valor[ds], flujo[ds] = v, f_usd
        self._sim = dict(valor=valor, flujo=flujo, realizado=realizado, cash=cash, hold=hold, lotes=lotes)
        return self._sim

    def twr_verdad(self, desde, hasta):
        """TWR exacto entre el cierre de `desde` y el cierre de `hasta` (fechas ISO)."""
        s = self._sim if hasattr(self, "_sim") else self.simular()
        v, f = s["valor"], s["flujo"]
        ks = sorted(k for k in v if desde < k <= hasta)
        prev = v.get(desde)
        if prev is None:
            return None
        idx = 1.0
        for k in ks:
            base = prev + f[k]
            if base > 1e-9:
                idx *= v[k] / base
            prev = v[k]
        return (idx - 1) * 100

    def contable_verdad(self, desde_mes=None, hasta_mes=None):
        """Dietz mensual de la contabilidad realizada (lo que el Estimado promete)."""
        s = self._sim if hasattr(self, "_sim") else self.simular()
        meses = {}
        for k, x in s["flujo"].items():
            meses.setdefault(k[:7], [0.0, 0.0])[0] += x
        for k, x in s["realizado"].items():
            meses.setdefault(k[:7], [0.0, 0.0])[1] += x
        cap, idx, out = 0.0, 1.0, {}
        for ym in sorted(meses):
            fl, re_ = meses[ym]
            if (desde_mes and ym <= desde_mes) or (hasta_mes and ym > hasta_mes):
                cap += fl + re_
                continue
            if cap > 0:
                idx *= 1 + re_ / (cap + 0.5 * fl)
            cap += fl + re_
            out[ym] = (idx - 1) * 100
        return out

    def foto(self, fecha):
        """Tenencia y caja verdaderas al cierre de `fecha` (para fabricar la foto)."""
        cash = {"ARS": 0.0, "USD": 0.0}
        hold = {}
        for e in self.estado():
            if e.fecha > fecha:
                break
            if e.tipo == "DEP":
                cash[e.moneda] += e.monto
            elif e.tipo == "WD":
                cash[e.moneda] -= e.monto
            elif e.tipo == "BUY":
                cash[e.moneda] -= e.neto
                hold[(e.tk, e.moneda)] = hold.get((e.tk, e.moneda), 0) + e.qty
            elif e.tipo == "SELL":
                cash[e.moneda] += e.neto
                k = (e.tk, e.moneda) if (e.tk, e.moneda) in hold else next(k for k in hold if k[0] == e.tk)
                hold[k] -= e.qty
            elif e.tipo in ("DIV", "CUPON"):
                cash[e.moneda] += e.monto
            elif e.tipo == "TIN":
                hold[(e.tk, "ARS")] = hold.get((e.tk, "ARS"), 0) + e.qty
            elif e.tipo == "MEP":
                cash["ARS"] -= e.monto
                cash["USD"] += e.usd_recibidos
        return {"cash": cash, "hold": {k: q for k, q in hold.items() if q > 1e-9}}


def historia_base(m: Mercado, post_foto=False) -> Historia:
    """La historia estándar: 2024-01 → 2026-08, broker en pesos con lado dólar."""
    h = Historia(m)
    h.dep("2024-01-08", 6_000_000)
    h.buy("2024-01-10", "GGAL", 1000)
    h.buy("2024-01-10", "AAPL", 300)
    h.dep("2024-02-14", 4_000, "USD")
    h.buy("2024-02-16", "GD38", 8000, "USD")
    h.div("2024-04-15", "GGAL", 30 * 1000, "ARS")
    h.div("2024-05-16", "AAPL", 300 / 20 * 0.25, "USD")
    h.cupon("2024-07-09", "GD38", 8000)
    h.sell("2024-09-03", "GGAL", 400)
    h.mep("2024-11-12", 1_000_000)
    h.cupon("2025-01-09", "GD38", 8000)
    h.buy("2025-03-05", "MELI", 20)
    h.wd("2025-06-02", 300_000)
    h.cupon("2025-07-09", "GD38", 8000)
    h.dep("2025-10-06", 3_000_000)
    h.buy("2025-10-08", "SPY", 70)
    h.cupon("2026-01-09", "GD38", 8000)
    h.sell("2026-03-10", "AAPL", 300)
    h.buy("2026-05-15", "KO", 100, "USD")
    h.cupon("2026-07-09", "GD38", 8000)
    if post_foto:
        h.buy("2026-08-20", "YPFD", 20)
    return h
