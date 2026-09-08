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

Verificado 2026-06-25 vs api.argentinadatos.com; IAMRDOA agregado 2026-07-28.
Fondos deliberadamente FUERA (sin match confiable → al costo): "Cocos Pesos Plus"
(COCOSPPA) — re-chequeado 2026-07-28: sigue SIN figurar en ArgentinaDatos (fondo
nuevo, inicio 15/05/2025; VCP Clase A 1,2945 no matchea ningún fondo de la fuente,
y "Adcap Pesos Plus" es otro fondo con VCP ~136). CAFCI directo devuelve 403 y
cocos.capital es SSR/Cloudflare sin API estable → no hay fuente backend confiable;
queda al costo hasta que ArgentinaDatos lo indexe. "ALRTAFA" (Allaria vs Alpha,
errar es catastrófico). Para sumar uno: confirmá su `fondo` exacto en la fuente,
agregá el ticker acá y su base-name en pricing.fci.BROKER_FCI_ALLOWLIST.
"""
from __future__ import annotations
from typing import Optional

import re
from pricing.fci import FCI_PREFIX, _slug, _strip_accents

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
    "ESTRA3A":   "Balanz Capital Estrategia III USD - Clase A",  # rentaFija USD (Balanz) — reportado user 2026-07-10, VCP 1069,96 vs AD
    "BCMMUSDA":  "Balanz Money Market USD - Clase A",           # mercadoDinero USD (Balanz) — VCP 1024,74 (÷1000=1,02 escala USD, no la ARS 'Capital Money Market' de 12k)
    # IOL — confirmado 2026-07-02 vs ArgentinaDatos: el ticker CONIOLA ("Adcap Acciones"
    # en IOL/BCBA) matchea "Adcap Acciones - Clase A" (rentaVariable ARS) por PRECIO
    # EXACTO (VCP 193.077,218 = los $193.077 de IOL) y magnitud sana. Clase B daría
    # 227.176 (×1.18 mal). Otras clases (D/E/F) sin VCP en la fuente → no candidatas.
    "CONIOLA":   "Adcap Acciones - Clase A",           # rentaVariable ARS (IOL)
    # Cohen / IAM — confirmado 2026-07-28 vs ArgentinaDatos: "IAM Renta Dólares - Clase A"
    # (rentaFija USD), VCP 1780,226 (÷1000 = 1,78 escala USD). El user linkeó el fondo 4815
    # de Cohen con ese nombre EXACTO. Clases B/C dan 1830/1801 (misma magnitud, sin riesgo 100x).
    "IAMRDOA":   "IAM Renta Dólares - Clase A",        # rentaFija USD (Cohen/IAM)
    # Galicia/FIMA — NO es un ticker de broker: es el nombre COMERCIAL que el usuario
    # escribe al cargar el fondo a mano ("FIMA-ACCIONES"), y que queda crudo → al costo.
    # Entra acá igual porque el remap (main._remap_fci_broker_tickers) es el único
    # camino que arregla las posiciones YA cargadas sin editar lote por lote.
    # Confirmado 2026-08-13 vs ArgentinaDatos: "Fima Acciones - Clase A" (rentaVariable
    # ARS), VCP 277.297,694 (÷1000 = 277,30 $/cp) contra un costo del usuario de ~210 $/cp
    # → misma magnitud. Los dos vecinos peligrosos quedan descartados por magnitud:
    # "Fima PB Acciones - Clase A" da 3.253 $/cp (12× arriba) y "Fima Acciones
    # Latinoamerica - Clase A" 1,60 $/cp. Clase B (314.394) es la misma escala que A,
    # así que el peor caso de errarle a la clase acá es ~13%, no 100×.
    "FIMA-ACCIONES": "Fima Acciones - Clase A",        # rentaVariable ARS (Galicia/FIMA)
}


def resolve_fci_symbol(ticker: Optional[str]) -> Optional[str]:
    """Ticker de fondo del broker → símbolo del catálogo (`FCI:<slug>`), o None
    si no está en el mapa curado (→ el llamador deja el ticker crudo = al costo).

    Usa el `_slug` de pricing.fci, así el símbolo SIEMPRE coincide con la entrada
    del catálogo (no hay drift posible aunque cambie el slugify).
    """
    ad_name = BROKER_FCI_AD_NAME.get((ticker or "").strip().upper())
    return (FCI_PREFIX + _slug(ad_name)) if ad_name else None


# ── Resolución por NOMBRE de fondo (plantilla manual de Rendi) ───────────────
# El mapa de arriba resuelve el TICKER que emite un parser de broker. Pero por la
# plantilla manual el usuario no tiene un ticker: escribe el NOMBRE del fondo tal
# como se lo muestra su app ("Ualintec Renta Dolares - Clase A"). Eso entraba como
# activo crudo y la posición quedaba al costo para siempre (reportado 2026-09-08).
#
# Peor: para cuando llega acá el nombre ya pasó por el `\s+`→`-` del normalizer,
# así que lo que vemos es "UALINTEC-RENTA-DOLARES---CLASE-A" (tres guiones donde
# iba " - "). `_name_key` colapsa las dos formas —la escrita y la mangleada— a la
# MISMA clave que produce `_slug` sobre el nombre oficial de la fuente.
_CLASE_SUFFIX_RE = re.compile(r"-CLASE-([A-Z0-9]+)$")


def _name_key(s: Optional[str]) -> Optional[str]:
    """Clave canónica de un nombre de fondo, tolerante a acentos, mayúsculas,
    separadores repetidos y al sufijo de clase escrito largo.

        'Ualintec Renta Dólares - Clase A'   → 'UALINTEC-RENTA-DOLARES-A'
        'UALINTEC-RENTA-DOLARES---CLASE-A'   → 'UALINTEC-RENTA-DOLARES-A'
        'ualintec renta dolares clase a'     → 'UALINTEC-RENTA-DOLARES-A'

    Devuelve la MISMA forma que `_slug`, así la comparación es contra el símbolo
    de catálogo sin necesidad de una tabla de alias.
    """
    if not s:
        return None
    base = re.sub(r"[^A-Z0-9]+", "-",
                  _strip_accents(str(s)).upper()).strip("-")
    if not base:
        return None
    return _CLASE_SUFFIX_RE.sub(r"-\1", base)


def resolve_fci_by_name(conn, raw: Optional[str]) -> Optional[str]:
    """Nombre de fondo escrito por el usuario → símbolo del catálogo, o None.

    Reglas de seguridad (mismas que el mapa curado — errar de clase valúa ~100x
    mal, ver el docstring de arriba):
      • el match es EXACTO sobre la clave canónica, no por prefijo ni fuzzy;
      • si la clave matchea más de un fondo activo, NO se resuelve (ambiguo);
      • un símbolo que ya es 'FCI:' no se toca;
      • sin catálogo (tabla vacía / DB sin seedear) devuelve None, nunca adivina.
    """
    if not raw or str(raw).strip().upper().startswith(FCI_PREFIX):
        return None
    key = _name_key(raw)
    if not key or "-" not in key:
        # Una sola palabra no es un nombre de fondo: sería un ticker suelto y
        # abrir eso a match invita colisiones ('DELTA' vs 'Delta Pesos').
        return None
    try:
        rows = conn.execute(
            "SELECT symbol FROM fci_catalog WHERE activo=1 AND symbol=?",
            (FCI_PREFIX + key,),
        ).fetchall()
    except Exception:
        return None  # sin tabla de catálogo → comportamiento previo (al costo)
    if len(rows) != 1:
        return None
    row = rows[0]
    return row["symbol"] if not isinstance(row, tuple) else row[0]
