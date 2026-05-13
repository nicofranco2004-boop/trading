"""Módulo `home/` — backend para la página /home.

Compone las distintas secciones de la pantalla Home:
- indices: valores actuales de S&P, Nasdaq, Merval, BTC, dólar blue, oro
- market: heatmap del S&P 500 top 50 (snapshot diario)
- movers: top gainers / top losers del día
- personal: capa "lo que te afecta" (holdings que se mueven, earnings próximos)

Diseño: pure functions sobre la DB + caches en memoria con TTL.
Cada función es independiente y devuelve un dict serializable.
"""
