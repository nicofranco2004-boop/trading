"""builders.tecnico — cómo viene el precio de UN activo (la lectura técnica de su ficha).
═══════════════════════════════════════════════════════════════════════════
Topic: tecnico (el botón de Mervall-E en la ficha → el chat con ese activo cargado)

Params (los manda la ficha, con la misma marca que GET /api/tecnico):
  asset: str   — ticker ('GGAL', 'AAPL', 'BTC').
  moneda: str  — 'usd' (default) | 'ars'.
  local: str   — '1' si es una acción argentina (BYMA ÷ el MEP en dólares).

El paquete = lo mismo que recibe el chat con `get_technical_reading`
(ai/lectura_tecnica_chat.para_el_chat): los hechos de `resumen_tecnico_hechos`
sobre `tecnico.para_la_ficha`. No toca la cartera del usuario.
"""
from __future__ import annotations
from typing import Any, Dict


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    asset = (kwargs.get("asset") or "").strip().upper()
    if not asset:
        raise ValueError("Falta param 'asset' — ticker del activo.")
    moneda = "ars" if str(kwargs.get("moneda") or "").lower() == "ars" else "usd"
    local = str(kwargs.get("local") or "").lower() in ("1", "true")

    # Lazy: main ya está cargado cuando el registro llama al builder.
    import tecnico
    from main import _velas_a_pedido, _freno_tecnico
    from ai import lectura_tecnica_chat
    from ai.asset_names import asset_name
    base = asset[:-3] if asset.endswith(".BA") else asset
    # El freno de la ficha (tipo «uno»): lee la serie entera. Si está lleno, el
    # 429/503 corta el paquete y el chat contesta con lo que tiene (main.ai_chat).
    # Se le cuenta a quien pregunta (`paga`: la asesora adentro de un cliente),
    # que pone el servidor desde el token y nunca el navegador
    # (`main._params_de_boton`); a través del freno, también paga las descargas
    # (`main._freno_paga`). Sin `paga` (llamado a mano), la cuenta que se mira.
    paga = kwargs.get("paga") or user_id
    with _freno_tecnico(None, paga, "uno"):
        tickers, motivo = _velas_a_pedido(conn, [(base, local)], user_id)[base]
        ficha = tecnico.para_la_ficha(conn, base, moneda, local)
    if not ficha.get("disponible"):
        ficha["motivo"] = motivo or ("sin_serie" if not tickers else "sin_datos")
    return {"screen": "tecnico", **lectura_tecnica_chat.para_el_chat(ficha, asset_name(base) or base)}
