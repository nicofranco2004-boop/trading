"""Formateo de plata en convención ARGENTINA, en UN solo lugar.

Por qué existe este módulo: el formato estaba copiado a mano en cada archivo
que muestra plata, con dos variantes que no coinciden. El caso que lo destapó
fue el mail de alerta, que mostraba los pesos bien (`$7.350`) y los dólares a
la inglesa (`US$2,145.30`) en el MISMO mail.

⚠️ Trampa del atajo copiado por todo el repo: `f"{x:,.0f}".replace(",", ".")`
funciona SOLO si no hay decimales. Con `:,.2f` el número trae también un punto
decimal y ese replace lo deja mal (`2,145.30` → `2.145.30`). Por eso acá el
cambio de separadores se hace con un swap de verdad y no con un replace suelto.
"""
from __future__ import annotations
from typing import Optional

_DEFAULT_DECIMALS = {"ARS": 0, "USD": 2}


def fmt_money(value: Optional[float], currency: Optional[str] = "USD",
              decimals: Optional[int] = None, dash: str = "—") -> str:
    """`fmt_money(2145.3, 'USD')` → 'US$ 2.145,30'.
       `fmt_money(7350, 'ARS')`   → '$7.350'.

    `value` None devuelve `dash` (los motores de alerta nunca disparan con
    precio None, pero el formateador no puede asumirlo)."""
    if value is None:
        return dash
    ccy = (currency or "USD").upper()
    d = _DEFAULT_DECIMALS.get(ccy, 2) if decimals is None else decimals
    s = f"{abs(float(value)):,.{d}f}"
    # 2,145.30 → 2.145,30 (swap real: coma y punto intercambian rol)
    s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    sign = "−" if float(value) < 0 else ""
    return f"{sign}$" + s if ccy == "ARS" else f"{sign}US$ " + s
