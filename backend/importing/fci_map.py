"""Mapeo de tickers de fondos (FCI) de brokers AR → símbolo del catálogo Rendi.

Problema
────────
Los parsers emiten el ticker CRUDO que usa el broker para sus fondos comunes
(Cocos manda "COCOA", "COCOACCA"…; Balanz "BAHUSDA"…) con asset_type='FUND'.
Ese ticker NO existe en `fci_prices` (que indexa por símbolo `FCI:<slug>`), así
que la posición queda sin precio live → valuada AL COSTO para siempre.

Solución
────────
Una tabla curada `ticker_broker → nombre EXACTO en ArgentinaDatos`. El normalizer
(no los parsers) traduce el ticker a `FCI:<slug>` usando el MISMO `_slug` que
`pricing/fci.py`, de modo que el símbolo coincide exactamente con la entrada del
catálogo y cotiza igual que un FCI cargado a mano.

Seguridad / criterio
─────────────────────
Sólo entran fondos CONFIRMADOS contra ArgentinaDatos con alta confianza
(nombre + clase + moneda + magnitud de VCP sana). El riesgo a evitar es mapear a
la clase equivocada: dentro de un mismo fondo el VCP entre clases puede variar
~100x (ej. Cocos Rendimiento Clase A=11.24 vs D=0.07). Por eso el mapa apunta a
la CLASE exacta y, ante la duda, NO se mapea (la posición queda al costo, que es
el comportamiento previo — sin regresión, no inventamos precio).

Verificado 2026-06-25 vs api.argentinadatos.com. Fondos deliberadamente FUERA
(sin match confiable → al costo): "Cocos Pesos Plus" (COCOSPPA, no figura en la
fuente), "BAHUSDA" (Balanz — candidatos ambiguos), "ALRTAFA" (Allaria vs Alpha,
errar es catastrófico). Para sumar uno: confirmá su `fondo` exacto en la fuente,
agregá el ticker acá y su base-name en pricing.fci.BROKER_FCI_ALLOWLIST.
"""
from __future__ import annotations
from typing import Optional

from pricing.fci import FCI_PREFIX, _slug

# ticker del broker (UPPER) → nombre EXACTO del fondo en ArgentinaDatos.
# La clase va explícita: el ticker del broker es específico de la clase
# (COCOA = Cocos Ahorro Clase A), así que mapeamos 1:1 a esa clase.
BROKER_FCI_AD_NAME = {
    # Cocos Capital — el ticker (entre paréntesis en el instrumento) ya codifica la clase
    "COCOA":     "Cocos Ahorro - Clase A",            # mercadoDinero ARS
    "COCOAUSD":  "Cocos Ahorro Dólares - Clase A",    # rentaFija USD
    "COCOUSDPA": "Cocos Dólares Plus - Clase A",       # rentaFija USD
    "COCORMA":   "Cocos Rendimiento - Clase A",        # rentaMixta ARS
    "COCOACCA":  "Cocos Acciones - Clase A",           # rentaVariable ARS
    "SBSACAR":   "SBS Acciones Argentina - Clase A",   # rentaVariable ARS (vía Cocos)
    # Balanz — confirmado 2026-07-02 vs ArgentinaDatos: el ticker BCAHA (Balanz Capital
    # AHorro clase A, descripción "Ahorro corto plazo Clase A" en el Resumen) matchea
    # "Balanz Capital Ahorro - Clase A" por PRECIO (237,27/cp = el 237,04 del PDF + 1
    # día de devengamiento) y magnitud sana. ARS.
    "BCAHA":     "Balanz Capital Ahorro - Clase A",    # rentaFija ARS (ahorro/money-market)
    # Balanz USD — confirmado 2026-07-05 vs ArgentinaDatos por TICKER + VCP del Resumen
    # (÷1000 porque el vcp de la API es por 1000 cuotapartes). El nombre CNV de la fuente
    # difiere del rótulo comercial del Resumen, así que se ancla por PRECIO:
    #   BAHUSDA "Corporativo Clase A" (foto VCP 1,42) → "Balanz Ahorro en Dólares - Clase A"
    #     (VCP API 1417,66 → 1,4177; 92.200,52 cp × 1,4177 = u$s130.703 ≈ foto u$s130.504).
    #   ESTRA1A "Dolar Corto Plazo Clase A" (foto VCP 1,16) → "Balanz Capital Estrategia I
    #     USD - Clase A" (VCP API 1163,54 → 1,1635; 79.181,74 × 1,1635 = u$s92.133 ≈ 92.008).
    # Los offshore BBALANCED/BLATAM ("LSeries DAC") NO cotizan en la fuente → siguen al
    # costo/override (snapshot de la foto), sin riesgo de mapear a la clase equivocada.
    "BAHUSDA":   "Balanz Ahorro en Dólares - Clase A",        # rentaFija USD (Balanz)
    "ESTRA1A":   "Balanz Capital Estrategia I USD - Clase A",  # rentaFija USD (Balanz)
    # IOL — confirmado 2026-07-02 vs ArgentinaDatos: el ticker CONIOLA ("Adcap Acciones"
    # en IOL/BCBA) matchea "Adcap Acciones - Clase A" (rentaVariable ARS) por PRECIO
    # EXACTO (VCP 193.077,218 = los $193.077 de IOL) y magnitud sana. Clase B daría
    # 227.176 (×1.18 mal). Otras clases (D/E/F) sin VCP en la fuente → no candidatas.
    "CONIOLA":   "Adcap Acciones - Clase A",           # rentaVariable ARS (IOL)
}


def resolve_fci_symbol(ticker: Optional[str]) -> Optional[str]:
    """Ticker de fondo del broker → símbolo del catálogo (`FCI:<slug>`), o None
    si no está en el mapa curado (→ el llamador deja el ticker crudo = al costo).

    Usa el `_slug` de pricing.fci, así el símbolo SIEMPRE coincide con la entrada
    del catálogo (no hay drift posible aunque cambie el slugify).
    """
    ad_name = BROKER_FCI_AD_NAME.get((ticker or "").strip().upper())
    return (FCI_PREFIX + _slug(ad_name)) if ad_name else None
