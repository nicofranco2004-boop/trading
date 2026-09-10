"""Parser de Balanz — export de "Movimientos" (Actividad → Movimientos).

Es el LIBRO DE CAJA real: a diferencia del export de Resultados (informe de
ganancias/tenencias, SIN efectivo) y del de Órdenes (solo trades, sin depósitos),
Movimientos trae TODOS los movimientos de plata — incluidos los depósitos ("Recibo
de Cobro") — así que el cash RECONCILIA. Una hoja, columnas:
  Descripcion, Ticker, Tipo de Instrumento, Concertacion, Cantidad, Precio,
  Liquidacion, Moneda, Importe   (+ `_hoja` que agrega excel.xlsx_to_csv).

Reglas clave (verificadas contra archivo real):
  • Cada fila = un movimiento independiente (cada Boleto es 1 fila; los legs NO se
    parean por número de boleto).
  • `Importe` = el efecto en CASH (− sale, + entra). Es la fuente de verdad del
    cash → `monto = abs(Importe)` SIEMPRE, y el tipo de operación se elige para que
    el signo del cash MATCHEE el de Importe (así reconcilia por construcción).
  • `precio = -1` = sentinela "sin precio unitario" → fila de cash/renta/fee (no
    crea posición). Con precio real → trade/FCI (crea posición).
  • Compra/Venta de un Boleto está en el TEXTO ("Boleto / NNN / COMPRA|VENTA"),
    pero el signo de Importe es el que manda para el cash.
  • Comisiones/impuestos vienen como filas Pesos aparte (precio=-1, importe chico)
    → se emiten como FEE propias (cash correcto; el costo-base del trade no las
    incluye — follow-up menor).

Limitación conocida (follow-up): los fondos money-market "Suscripción/Rescate
desde/a Balanz" (sweeps de cash ocioso) traen el signo de Importe INVERTIDO
respecto del efecto en la cuenta principal (contabilidad del lado del fondo). Se
mapean por signo de Importe → el CASH reconcilia, pero la dirección de la POSICIÓN
del fondo-sweep puede quedar invertida. Los fondos "Liquidación de Suscripción/
Rescate" (los reales) quedan bien.
"""
from __future__ import annotations
import csv
import io
import re
from typing import Dict, List, Optional
from .base import Parser
from ..schema import ParseResult, RawRow, RowError, omitted_row_error


def _norm_header(h: str) -> str:
    if not h:
        return ""
    s = (h.strip().lower()
           .replace("ó", "o").replace("í", "i").replace("á", "a")
           .replace("é", "e").replace("ú", "u").replace("ñ", "n"))
    return " ".join(s.split())


_FIELD_ALIASES: Dict[str, List[str]] = {
    "descripcion": ["descripcion"],
    "activo":      ["ticker", "especie"],
    "clase":       ["tipo de instrumento", "tipo instrumento", "tipoinstrumento"],
    "fecha":       ["concertacion", "fecha concertacion", "fecha"],
    "cantidad":    ["cantidad"],
    "precio":      ["precio"],
    "moneda":      ["moneda"],
    "importe":     ["importe"],
    "_hoja":       ["_hoja"],
}

# Movimientos se distingue de los otros dos exports de Balanz por traer JUNTAS las
# columnas `Descripcion` + `Importe` (Órdenes no tiene Descripcion; Resultados no
# tiene Importe ni Descripcion como columna de evento).
_REQUIRED = ("descripcion", "importe", "moneda")


def _norm_ccy(s: str) -> str:
    if not s:
        return ""
    v = " ".join(s.strip().lower().replace("ó", "o").split())
    if v.startswith("peso") or v in ("ars", "$"):
        return "ARS"
    if v.startswith("dolar") or "dollar" in v or v in ("usd", "u$s", "us$"):
        return "USD"
    return s.strip().upper()


def _asset_type(clase: str) -> Optional[str]:
    c = (clase or "").strip().lower().replace("ó", "o")
    if not c:
        return None
    if "cedear" in c:
        return "CEDEAR"
    if "fondo" in c:
        return "FUND"
    if "accion" in c:
        return "STOCK"
    if "bono" in c or "letra" in c or "corporativ" in c or "obligacion" in c:
        return "BOND"
    return None


def _num(s) -> Optional[float]:
    if s is None:
        return None
    txt = str(s).strip()
    if not txt or txt.lower() == "none":
        return None
    if "," in txt and "." in txt:
        txt = txt.replace(".", "").replace(",", ".")
    elif "," in txt:
        txt = txt.replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return None


def _resolve_columns(headers: List[str]) -> Dict[str, Optional[str]]:
    norm_to_orig: Dict[str, str] = {}
    for h in headers:
        norm_to_orig.setdefault(_norm_header(h), h)
    resolved: Dict[str, Optional[str]] = {}
    used: set = set()
    for field_name, aliases in _FIELD_ALIASES.items():
        match = None
        for alias in aliases:
            key = _norm_header(alias)
            if key in norm_to_orig and key not in used:
                match = norm_to_orig[key]
                used.add(key)
                break
        resolved[field_name] = match
    return resolved


# Descripciones que NO crean posición y se mapean por significado (el resto cae
# al default por signo de Importe). Match por substring sobre la desc normalizada.
def _classify_desc(desc_norm: str) -> str:
    d = desc_norm
    if d.startswith("transferencia"):
        return "transfer"
    # Acciones societarias que cambian CANTIDAD sin cash (o casi): dividendo en
    # acciones / en especie (lote gratis de acciones o nominales), split, cambio
    # de ratio de CEDEAR, rescate parcial de bono (baja nominal). "rescate parcial"
    # va acá (antes que "rescate" abajo). "dividendo en especie" va acá (antes que
    # "dividendo" suelto abajo, que sería renta en efectivo) — trae nominales, no
    # cash; ruteado a renta caía como FEE monto 0 ("comisión aislada necesita monto").
    # ⭐ "canje s/aviso de suscripción" = CANJE de bono: el viejo SALE (cantidad −) y
    # el nuevo ENTRA (cantidad +), normalmente con importe 0. Va a `corporate` (no a
    # renta): la rama corporate maneja la cantidad (VENTA viejo / COMPRA nuevo) Y el
    # cash cuando lo hay (canje liquidado en efectivo → DIVIDENDO/FEE). Ruteado a
    # renta perdía la cantidad → dejaba el bono nuevo/viejo como posición fantasma.
    # "reducción de capital" (devolución de capital de un bono/ON: baja el nominal,
    # cantidad −, importe normalmente 0) y "conversión especie" (canje de un título
    # por otro: el viejo SALE con cantidad −) también cambian la CANTIDAD sin cash →
    # corporate (VENTA precio 0 que baja la posición). Ruteadas a renta/otro caían
    # como FEE monto 0 o se descartaban, dejando el bono como posición fantasma.
    if (d.startswith("dividendo en acciones") or d.startswith("dividendo en especie")
            or d.startswith("split") or d.startswith("acreditacion cambio de ratio")
            or d.startswith("rescate parcial") or d.startswith("canje s/aviso")
            or d.startswith("reduccion de capital") or d.startswith("conversion especie")):
        return "corporate"
    # Operación a plazo / diferida: trade con cantidad + cash pero sin precio
    # unitario (precio=-1). Se resuelve por el signo de Importe.
    if d.startswith("operacion diferida") or d.startswith("liquidacion de operacion diferida"):
        return "diferida"
    if d.startswith("recibo de cobro") or d.startswith("acreditacion de cheque"):
        return "deposito"
    if d.startswith("comprobante de pago"):
        return "retiro"
    # Comisiones / aranceles que salen como fila propia (cash que SALE). "Débito de
    # Aranceles por Acreencias" (arancel por cobrar cupones/dividendos) entra acá.
    if d.startswith("cargo por descubierto") or d.startswith("debito de aranceles"):
        return "fee"
    # Ingresos por título (entra) o retención (sale): cupón, dividendo en efectivo,
    # amortización, intereses devengados, prima por rescate, rescate (cash de un
    # bono que se rescata; el "rescate parcial" que baja nominal ya salió arriba) y
    # baja de derecho de suscripción (cash por los derechos; la cantidad son
    # DERECHOS, no acciones → la renta los ignora y solo cuenta el cash). El "canje
    # s/aviso" ya salió arriba en `corporate` (puede traer cantidad).
    if (d.startswith("renta") or d.startswith("dividendo") or d.startswith("amortizacion")
            or d.startswith("pago complementario") or d.startswith("prima por rescate")
            # "Intereses corridos" es la MISMA cosa que "intereses devengados"
            # con otras dos palabras: los intereses que el bono acumuló hasta la
            # fecha del canje. Llega en dos patas —el cobro en dólares y su
            # retención en pesos—, igual que "Intereses devengados canje …", que
            # ya entraba bien por esta misma rama.
            # "Contraprestación período temprano" es el premio por entrar temprano
            # a un canje de ON: cash que ENTRA, sin nominales.
            or d.startswith("intereses corridos") or d.startswith("contraprestacion")
            or d.startswith("intereses devengados") or d.startswith("rescate")
            or d.startswith("baja derecho")):
        return "renta"
    if d.startswith("movimiento manual"):
        return "manual"
    if d.startswith("boleto"):
        return "boleto"
    return "otro"


def transferencia_externa(qty: float, precio: Optional[float]):
    """Qué emite una fila "Transferencia Externa" de TÍTULOS. Compartido por el
    parser local y el internacional — el formato es el mismo.

    Manda el SIGNO DE LA CANTIDAD, no el Importe: mover un título entre brokers
    no mueve efectivo, así que el Importe de estas filas viene 0 y no distingue
    nada. Antes esta rama tomaba `abs(qty)` y emitía siempre COMPRA porque solo
    se había visto la transferencia que ENTRA; con un export real que traía seis
    "Transferencia Externa (Débito)" (títulos que SALIERON a otro broker) cada
    una sumaba en vez de restar y la tenencia quedaba al DOBLE, más un depósito
    de capital que nunca existió.

      • qty > 0 — Crédito: el título ENTRA desde otro broker. COMPRA a su valor
        + DEPOSITO por ese mismo valor: el cash NETEA a 0 (no se gastó plata en
        Balanz) y el capital aportado refleja lo que entró. Sin precio no hay
        valor que asignar → COMPRA a 0.
      • qty < 0 — Débito: el título SALE hacia otro broker. NO es una venta: no
        entró plata y no hay resultado que realizar. VENTA precio 0 marcada
        `_transfer_out` → cierra el lote A COSTO, P&L 0, sin generar cash. Es el
        MISMO criterio que ya usan IEB (código RETR), PPI ("Retiro de Títulos")
        y Binance (retiro a wallet): el papel se fue de la cuenta pero sigue
        siendo del usuario, así que no se le bookea ni ganancia ni pérdida.

    Devuelve (tipo, extra, cash): `extra` son los campos propios de la fila de
    posición y `cash` es (tipo, monto) o None. Los campos comunes
    (fecha/broker/moneda/notas) los pone el `base()` de cada parser.
    """
    if not qty:
        # Sin cantidad no hay título que mover. La guarda vive acá y no solo en el
        # caller: esta función la usan los dos parsers de Balanz.
        return (None, {}, None)
    if qty > 0:
        # Se redondea ANTES de decidir: con una cantidad microscópica (una
        # cuotaparte de FCI de 0,00001) el valor redondea a 0 y el DEPOSITO de
        # monto 0 lo RECHAZA el validador. Si no queda monto, no hay depósito.
        valor = round(abs(qty) * precio, 4) if (precio or 0) > 0 else 0.0
        if valor > 0:
            return ("COMPRA",
                    {"cantidad": str(abs(qty)), "precio": str(precio),
                     "monto": str(valor)},
                    ("DEPOSITO", str(valor)))
        return ("COMPRA", {"cantidad": str(abs(qty)), "precio": "0", "monto": "0"}, None)
    return ("VENTA",
            {"cantidad": str(abs(qty)), "precio": "0", "monto": "0", "_transfer_out": "1"},
            None)


def _is_tax(desc_norm: str) -> bool:
    """¿Esta salida de cash es una RETENCIÓN DE IMPUESTO (Ganancias/IIGG/IIBB/
    Bienes Personales) y NO una comisión? Balanz las descuenta de dividendos,
    cupones y ventas ("N/D Ret IIGG - IRSA"). Van a op_type IMPUESTO (métrica
    aparte), no a FEE — así "comisiones" queda limpio de impuestos."""
    d = desc_norm
    return (("ret" in d and ("iigg" in d or "ganancia" in d or "gcia" in d))
            or "retencion" in d or "impuesto" in d or "iibb" in d
            or "ingresos brutos" in d or "bienes personales" in d)


class BalanzMovimientosParser(Parser):
    format_id = "balanz_movimientos"
    display_name = "Balanz — Movimientos"
    is_supported = True
    platform = "balanz"
    platform_label = "Balanz"
    export_label = "Actividad → Movimientos (recomendado)"
    tenencia_format = "balanz_tenencia"

    def can_handle(self, headers: List[str]) -> bool:
        cols = _resolve_columns(headers)
        return all(cols.get(f) for f in _REQUIRED)

    def template_csv(self) -> str:
        return (
            "Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,Liquidacion,Moneda,Importe\n"
            "Recibo de Cobro / 8801586,,,2025-10-22,0,-1,2025-10-22,Pesos,3493747.27\n"
            "Boleto / 4863167 / COMPRA / 0 / GD46 / usd,AL35,Bonos,2025-10-23,1886,0.658687,2025-10-23,Dólares,-1218.15\n"
            "Boleto / 2452545 / VENTA / 0 / GD46 / usd,AL35,Bonos,2025-11-02,854,0.576364,2025-11-02,Dólares,531.01\n"
            "Dividendo en efectivo / XLE,XLE,Cedears,2025-12-15,0,-1,2025-12-15,Dólares,1.2\n"
            "Comprobante de Pago / 9971834,,,2026-01-10,0,-1,2026-01-10,Pesos,-421757.05\n"
        )

    def parse(self, content: str, file_name: Optional[str] = None) -> ParseResult:
        result = ParseResult()
        if content.startswith("﻿"):
            content = content[1:]
        try:
            sample = content[:4096]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(io.StringIO(content), dialect=dialect)
            headers = reader.fieldnames or []
        except Exception as ex:
            result.parse_errors.append(RowError(0, None, "FILE_UNREADABLE",
                                                f"No pudimos leer el archivo: {ex}"))
            return result

        cols = _resolve_columns(headers)
        if not all(cols.get(f) for f in _REQUIRED):
            result.parse_errors.append(RowError(
                0, None, "BALANZ_MOV_HEADERS_MISMATCH",
                "Este archivo no coincide con el export de Movimientos de Balanz "
                "(Actividad → Movimientos). Asegurate de subir ese Excel — no el de "
                "Resultados ni el de Órdenes."))
            return result

        def _g(row, field_name):
            col = cols.get(field_name)
            return (row.get(col) or "").strip() if col else ""

        ridx = 0
        # Amortizaciones ya cerradas (ticker, fecha, |cantidad|) → evita bajar el
        # nominal dos veces: "Renta y Amortización" viene en 2 patas (cobro USD +
        # retención ARS), ambas con la MISMA cantidad. Solo una cierra el nominal.
        _amort_closed = set()

        def _emit(d):
            nonlocal ridx
            ridx += 1
            result.raw_rows.append(RawRow(row_index=ridx, data=d))

        # Pre-pass FCI: una suscripción/rescate de fondo vía sweep money-market
        # llega en DOS filas espejo — "Liquidación de Suscripción/Rescate" (la real,
        # con cantidad + caja) y "Suscripción desde/Rescate a Balanz" (el espejo).
        # Indexamos las Liquidación (ticker, fecha, |cantidad|) para saltear su
        # espejo en el loop y no duplicar la tenencia.
        all_rows = list(reader)

        # Pre-pass CAMBIO DE MONEDA: "Operación de Cambio / <nro>" es la compra o
        # venta de dólares y llega en DOS filas del MISMO número — una en Pesos y
        # otra en Dólares, con signos opuestos. Antes ninguna se reconocía y las
        # 32 conversiones de un usuario real quedaban afuera: los pesos gastados
        # en comprar dólares seguían "en la cuenta" y los dólares nunca entraban,
        # así que ningún saldo cerraba. Las colapsamos en UNA conversión (el mismo
        # contrato que usa IOL: monto = ARS, monto_usd = USD).
        _fx_by_idx: dict = {}     # índice de la fila PESOS → (tipo, ars, usd)
        _fx_drop: set = set()     # índice de la pata dólar (ya representada)
        _cambio_groups: dict = {}
        for _i, _r in enumerate(all_rows):
            _d = _norm_header(_g(_r, "descripcion"))
            if not _d.startswith("operacion de cambio"):
                continue
            # Clave = el número del comprobante que Balanz pone en la descripción.
            _nro = _d.split("/")[-1].strip() if "/" in _d else ""
            _cambio_groups.setdefault((_nro, _g(_r, "fecha")), []).append((_i, _r))
        for _key, _items in _cambio_groups.items():
            if len(_items) != 2:
                continue          # no adivinamos si no son exactamente dos patas
            _pat = {}
            for _i, _r in _items:
                _cc = _norm_ccy(_g(_r, "moneda"))
                _im = _num(_g(_r, "importe"))
                if _im is None or _cc not in ("ARS", "USD"):
                    _pat = {}
                    break
                _pat[_cc] = (_i, _im)
            if set(_pat) != {"ARS", "USD"}:
                continue
            (_i_ars, _v_ars), (_i_usd, _v_usd) = _pat["ARS"], _pat["USD"]
            # Los signos tienen que ser opuestos (una pata paga, la otra cobra).
            if _v_ars == 0 or _v_usd == 0 or (_v_ars > 0) == (_v_usd > 0):
                continue
            # Pesos NEGATIVO = salieron pesos → compró dólares.
            _op = "FX_ARS_USD" if _v_ars < 0 else "FX_USD_ARS"
            _fx_by_idx[_i_ars] = (_op, abs(_v_ars), abs(_v_usd))
            _fx_drop.add(_i_usd)

        # ⭐ Índice de las patas del lado de la CUENTA ("Liquidación de …") para
        # reconocer a su espejo del lado del FONDO. La clave NO lleva el TICKER a
        # propósito: Balanz nombra al MISMO fondo con dos códigos distintos según
        # el lado —"BMM A" en la Liquidación y "BCMMA" en el espejo—, así que
        # apareando por ticker 7 de los 12 pares de un archivo real NO matcheaban
        # y el movimiento se contaba DOS VECES (caja en pesos 2.207.199 en vez de
        # los 713.772 del resumen del broker, y una posición de fondo duplicada).
        # Fecha + cantidad + importe sí coinciden exacto entre las dos patas.
        _fci_liq_keys = set()
        for _r in all_rows:
            if _asset_type(_g(_r, "clase")) == "FUND":
                _d = _norm_header(_g(_r, "descripcion"))
                if _d.startswith("liquidacion de suscrip") or _d.startswith("liquidacion de rescate"):
                    _q = _num(_g(_r, "cantidad"))
                    _im = _num(_g(_r, "importe"))
                    if _q is not None and _im is not None:
                        _fci_liq_keys.add((_g(_r, "fecha"), round(abs(_q), 2), round(abs(_im), 2)))

        for _row_i, row in enumerate(all_rows):
            desc_raw = _g(row, "descripcion")
            desc = _norm_header(desc_raw)
            if not desc:
                continue

            # Cambio de moneda detectado en el pre-pass: una sola fila lleva las
            # dos patas; la otra ya está representada y se descarta.
            if _row_i in _fx_drop:
                continue
            _fx = _fx_by_idx.get(_row_i)
            if _fx:
                _op, _ars, _usd = _fx
                _emit({
                    "fecha": _g(row, "fecha"), "tipo": _op, "broker": "Balanz",
                    "activo": "", "cantidad": "", "precio": "",
                    "monto": repr(_ars), "monto_usd": repr(_usd), "tc": "",
                    "comisiones": "0", "moneda": "",
                    "notas": desc_raw.strip(),
                })
                continue
            # Ticker sin espacios: las clases de FCI vienen como "INSTITU A" /
            # "BCACC A" y fragmentaban contra "INSTITUA"/"BCACCA". Ningún ticker
            # legítimo tiene espacios internos → normalizamos sacándolos.
            ticker = _g(row, "activo").upper().replace(" ", "") or None
            moneda = _norm_ccy(_g(row, "moneda"))
            fecha = _g(row, "fecha")
            importe = _num(_g(row, "importe"))
            precio = _num(_g(row, "precio"))
            qty = _num(_g(row, "cantidad"))
            clase = _asset_type(_g(row, "clase"))
            kind = _classify_desc(desc)

            # El export de Balanz MAL-ETIQUETA algunos FCI money-market en PESOS como
            # 'Dólares' (RFPESOS A, DOLINKA — cuotaparte/VCP ~30-200 = pesos), mientras
            # los FCI USD reales (BAHUSD — VCP ~1.3) vienen bien. Sin esto, los pesos del
            # fondo se cuentan como dólares (×~tc_blue) → P&L/cash peso-escala → el
            # capital_final negativo gigante (causa raíz, mitad Balanz de las 78 cuentas).
            # La ESCALA del VCP discrimina con gap limpio (USD money-market ≈ 1, peso ≥ 6):
            # un cuotaparte > 5 es en PESOS. Solo corregimos 'Dólares'→ARS (nunca al revés),
            # y solo FCI (clase FUND) con precio = VCP real (no las filas espejo sin precio).
            if clase == "FUND" and moneda == "USD" and precio is not None and precio > 5.0:
                moneda = "ARS"

            has_price = precio is not None and precio > 0
            has_qty = qty is not None and abs(qty) > 1e-9
            has_cash = importe is not None and abs(importe) > 0.001
            cash_in = (importe or 0) > 0
            notas = desc_raw[:120]

            if not has_cash and not has_qty:
                continue  # ni cash ni cantidad → nada que importar

            # ── ⭐ Con CANTIDAD y sin plata: mueve NOMINALES, no caja ────────
            # Estas filas se descartaban más abajo para no emitir un FEE de monto
            # 0 que el validador rechaza — pero de paso se tiraba la CANTIDAD, y
            # con ella la tenencia. Un export real lo dejó a la vista:
            #   • los CANJES de ON llegan como "Movimiento Manual / … canje …":
            #     el bono viejo sale (−) y el nuevo entra (+) el mismo día, con
            #     Importe 0 y a veces vía un certificado provisorio ("21030").
            #     El viejo nunca salía y el nuevo nunca llegaba.
            #   • una "Amortización / RCCJO" de −232 nominales con Importe 0 (el
            #     cobro había venido días antes, en su propia fila) dejaba el bono
            #     entero como posición fantasma.
            # Van a `corporate` SÓLO las dos formas que vimos en un export real
            # —"Movimiento Manual" y las amortizaciones—; esa rama ya sabe
            # hacerlo (es la misma que atiende "canje s/aviso", el canje que
            # Balanz sí nombra así) y sin ticker no emite nada. El resto se
            # REPORTA en vez de descartarse: con una renta, la cantidad podría
            # ser la tenencia de referencia y no un movimiento, y adivinar
            # crearía una posición fantasma. VA ACÁ, ANTES de la rama
            # `corporate` — más abajo no sirve, esa rama ya pasó.
            # `not has_price` es parte de la condición y no un detalle: una acción
            # societaria de Balanz SIEMPRE viene con precio = -1 (el sentinela de
            # "sin precio"). Si la fila trae un precio REAL es un trade y tiene
            # que seguir hasta su propia rama (FCI / trade con precio), que están
            # MÁS ABAJO que `corporate` — sin este guard, reclasificar acá arriba
            # se las robaba y las emitía a precio 0, borrándoles el costo.
            if (kind in ("deposito", "retiro", "fee", "renta", "manual")
                    and not has_cash and not has_price):
                if kind == "manual" or "amortizacion" in desc:
                    kind = "corporate"
                else:
                    # Acá la CANTIDAD es ambigua y no la inventamos: puede ser un
                    # movimiento de nominales o puede ser sólo la tenencia sobre
                    # la que se paga la renta. Tampoco la tragamos en silencio
                    # (así se perdieron los canjes durante meses): la reportamos
                    # con su número de fila para resolverla con un export real.
                    result.parse_errors.append(omitted_row_error(
                        _row_i + 1, ticker, "BALANZ_MOV_CANTIDAD_SIN_CASH",
                        f"'{desc_raw[:60]}' trae cantidad pero no plata y no "
                        f"sabemos si mueve tenencia. Se omitió esta fila — "
                        f"escribinos para resolverlo."))
                    continue

            def base(tipo, **extra):
                # Moneda vacía → ARS (base del broker). Algunos eventos de título
                # (canje, baja de derecho) vienen sin moneda y son ARS; los trades
                # traen Pesos/Dólares explícito, así que no se tocan.
                d = {"fecha": fecha, "tipo": tipo, "broker": "Balanz",
                     "moneda": moneda or "ARS", "notas": notas}
                if ticker:
                    d["activo"] = ticker
                if clase:
                    d["asset_type"] = clase
                d.update(extra)
                return d

            # ── Acción societaria: cambia CANTIDAD sin cash (split, cambio de
            # ratio de CEDEAR, rescate parcial de bono, dividendo en acciones).
            # qty>0 → entran nominales (COMPRA precio 0) ; qty<0 → salen (VENTA
            # precio 0). Algunas (dividendo en acciones) traen ADEMÁS una
            # retención (importe≠0) → ese efecto de cash va aparte para reconciliar.
            if kind == "corporate":
                if has_qty and ticker:
                    if qty > 0:
                        # Entran nominales gratis (dividendo en acciones/especie,
                        # split, ratio al alza): COMPRA a costo 0 → baja el promedio.
                        _emit(base("COMPRA", activo=ticker,
                                   cantidad=str(abs(qty)), precio="0", monto="0"))
                    else:
                        # Salen nominales sin precio (split inverso, ratio a la baja,
                        # rescate parcial, dividendo en acciones/especie negativo):
                        # VENTA a precio 0 marcada _corporate_close → el validator la
                        # acepta (si no, MISSING_PRICE) y cierra la posición. El costo
                        # se bookea contra la renta/amortización asociada cuando la
                        # hay (rescate parcial / reducción de capital).
                        _emit(base("VENTA", activo=ticker, cantidad=str(abs(qty)),
                                   precio="0", monto="0", _corporate_close=True))
                if has_cash:
                    # cash-out en una acción societaria = retención de impuesto → IMPUESTO
                    _emit(base("DIVIDENDO" if cash_in else "IMPUESTO", monto=str(abs(importe))))
                continue

            # ── Operación a plazo / diferida: trade con cantidad + cash pero SIN
            # precio unitario (precio=-1). COMPRA/VENTA por el SIGNO de Importe; el
            # normalizer deriva el precio (monto/cantidad). Si no trae cantidad es
            # sólo un movimiento de caja → DEPOSITO/RETIRO por signo. El par
            # "Operación Diferida" + "Liquidación de Operación Diferida" netea a 0
            # (cantidad y cash) cuando la operación se cierra contra sí misma.
            if kind == "diferida":
                if has_qty and has_cash and ticker:
                    tipo = "VENTA" if cash_in else "COMPRA"
                    _emit(base(tipo, activo=ticker, cantidad=str(abs(qty)),
                               monto=str(abs(importe))))
                elif has_cash:
                    _emit(base("DEPOSITO" if cash_in else "RETIRO", monto=str(abs(importe))))
                continue

            # ── Transferencia Externa: título que ENTRA de / SALE hacia otro
            # broker. Importe=0 (no movió plata acá) → la dirección la da el SIGNO
            # DE LA CANTIDAD. Ver `transferencia_externa` para el criterio y para
            # el bug que corrige. Moneda: la del row o ARS (base del broker) — los
            # bonos en dólares transferidos son un follow-up.
            if kind == "transfer":
                _tipo, _extra, _cash = (
                    transferencia_externa(qty, precio) if ticker and has_qty
                    else (None, {}, None))
                if _tipo:
                    # La salida cierra a costo y descarta el precio de mercado del
                    # día; lo dejamos en las notas para no perder el dato de a
                    # cuánto valía el título cuando se fue.
                    _nota = notas
                    if qty < 0 and (precio or 0) > 0:
                        _nota = f"{notas} · valuado a {precio}"
                    _emit(base(_tipo, activo=ticker, notas=_nota, **_extra))
                    if _cash:
                        # La moneda la decide `base()`; acá replicamos SOLO el
                        # default para la fila de cash, que no pasa por base().
                        _emit({"fecha": fecha, "tipo": _cash[0], "broker": "Balanz",
                               "moneda": moneda or "ARS", "monto": _cash[1],
                               "notas": "Transferencia Externa (entrada de título)"})
                # Una fila de transferencia que SÍ movió efectivo (no es el caso de
                # los títulos, que vienen con Importe 0) se emite por signo — antes
                # se descartaba en silencio y ese cash no reconciliaba.
                if has_cash:
                    _emit(base("DEPOSITO" if cash_in else "RETIRO",
                               monto=str(abs(importe))))
                continue

            # ── FCI (fondos): Suscripción/Rescate ────────────────────────────
            # Un movimiento de fondo llega en DOS filas espejo y la dirección se
            # decide por NOMBRE, no por signo (Balanz invierte el Importe acá):
            #   • lado CUENTA — "Liquidación de …" (trae nº de operación y nombre
            #     del fondo). Es la ÚNICA que mueve la caja de la cuenta.
            #   • lado FONDO  — "Rescate a Balanz", "Suscripción desde Balanz", o
            #     "Rescate"/"Suscripción" a secas. Es contabilidad del fondo.
            # Verificado AL CENTAVO contra el resumen del broker de un usuario
            # real, en las DOS monedas: contando sólo las "Liquidación de …" la
            # caja da 713.772,28 vs 713.772,28 y 314,44 vs 314,44.
            # La pata del fondo CON par se descarta entera (su par trae tenencia y
            # caja). SIN par sí aporta la TENENCIA —si no, las cuotapartes quedan
            # colgadas— pero su caja se neutraliza con una pata compensatoria,
            # igual que la transferencia de títulos: la plata nunca pasó por la
            # cuenta (se rescató contra otro fondo).
            # Sólo SUSCRIPCIÓN y RESCATE entran acá. La condición no puede ser
            # "cualquier fila de un fondo": un `Boleto / … / COMPRA` de un FCI es
            # una compra REAL, y tratarla como pata del lado del fondo le
            # neutralizaba la caja — $125.000 comprados gratis. Lo que no es
            # suscripción ni rescate sigue de largo hasta la rama de trade.
            _es_rescate = (desc.startswith("rescate")
                           or desc.startswith("liquidacion de rescate"))
            _es_susc = (desc.startswith("suscrip")
                        or desc.startswith("liquidacion de suscrip"))
            if clase == "FUND" and has_price and has_qty and ticker and (_es_rescate or _es_susc):
                if not desc.startswith("liquidacion de"):
                    # Pata del lado del FONDO. Con par, su "Liquidación" ya trae
                    # tenencia y caja → se descarta entera.
                    if (fecha, round(abs(qty), 2), round(abs(importe or 0), 2)) in _fci_liq_keys:
                        continue
                    # Sin par: la tenencia sí se movió (si no, las cuotapartes
                    # quedan colgadas), pero la plata no pasó por la cuenta → una
                    # pata compensatoria la deja NEUTRA, igual que la
                    # transferencia de títulos.
                    _val = round(abs(qty) * precio, 4)
                    _emit(base("VENTA" if _es_rescate else "COMPRA", activo=ticker,
                               cantidad=str(abs(qty)), precio=str(precio), monto=str(_val)))
                    if _val > 0:
                        _emit({"fecha": fecha, "tipo": "RETIRO" if _es_rescate else "DEPOSITO",
                               "broker": "Balanz", "moneda": moneda or "ARS",
                               "monto": str(_val),
                               "notas": f"{notas} (la plata no pasó por la cuenta)"})
                    continue
                # Pata del lado de la CUENTA: es la que mueve la caja.
                _emit(base("VENTA" if _es_rescate else "COMPRA", activo=ticker,
                           cantidad=str(abs(qty)), precio=str(precio),
                           monto=str(abs(importe))))
                continue

            # ── Trade / FCI con precio real → crea posición ───────────────────
            # El tipo (COMPRA/VENTA) se decide por el SIGNO de Importe (cash), así
            # reconcilia siempre. El texto COMPRA/VENTA del Boleto coincide con
            # esto salvo en los fondos-sweep "desde/a Balanz" (limitación conocida).
            if has_price and ticker:
                tipo = "VENTA" if cash_in else "COMPRA"
                # Comisión EMBEBIDA: en los trades en PESOS Balanz NO la trae como
                # columna; vive en la diferencia entre el bruto (Precio×Cantidad) y
                # el Importe neto (COMPRA |Importe|=bruto+comisión; VENTA |Importe|=
                # bruto−comisión; ~0,5-0,7%). La extraemos como `comisiones` y
                # emitimos monto=BRUTO → COMPRA cost=invested(bruto)+comisión,
                # VENTA proceeds=bruto−comisión (antes la venta no la descontaba).
                # Cash NEUTRAL (bruto±comisión=|Importe|); solo se separa la comisión.
                #
                # ⚠️ SOLO en PESOS. En trades en DÓLARES la comisión viene como una
                # fila ARS APARTE (mismo boleto) que YA se cuenta como FEE, y el
                # |bruto−|Importe|| del leg USD es RUIDO FX (redondeo) → extraerla
                # duplicaría (~11%) e inflaría con ruido. Guard de tasa (≤3%): si el
                # "gap" es absurdo (bono per-100 leído per-1, precio raro) NO es
                # comisión → caemos al comportamiento viejo (monto=|Importe|, sin
                # extraer), sin inventar una comisión gigante.
                q = abs(qty or 0)
                gross = precio * q
                comision = abs(gross - abs(importe))
                embebida_ok = (
                    (moneda or "ARS").upper() == "ARS"
                    and gross > 0 and 0 < comision <= 0.03 * gross
                )
                if embebida_ok:
                    _emit(base(tipo, activo=ticker, cantidad=str(q),
                               precio=str(precio), monto=str(round(gross, 4)),
                               comisiones=str(round(comision, 4))))
                else:
                    _emit(base(tipo, activo=ticker, cantidad=str(q),
                               precio=str(precio), monto=str(abs(importe))))
                continue

            # ── Boleto sin precio (precio=-1) ─────────────────────────────────
            # Dos sub-casos muy distintos: (a) la pata COMISIÓN de un trade
            # (COMPRA/VENTA, importe chico, sale) → FEE; (b) CAUCIÓN colocadora
            # (APCOLCON=contado sale / APCOLFUT=futuro entra, importes grandes) y
            # cualquier otra → flujo de caja por SIGNO (sale→RETIRO, entra→DEPOSITO).
            # Sin esto, la pata de caución que ENTRA se contaba como FEE (sale) →
            # cash mal por millones. El signo de Importe siempre manda para el cash.
            if kind == "boleto":
                op_tok = ""
                _parts = [p.strip() for p in desc_raw.split("/")]
                if len(_parts) >= 3:
                    op_tok = _parts[2].upper()
                if op_tok in ("COMPRA", "VENTA", "LICOMPRA", "LIVENTA"):
                    tipo = "FEE" if not cash_in else "DEPOSITO"
                else:
                    tipo = "DEPOSITO" if cash_in else "RETIRO"
                _emit(base(tipo, monto=str(abs(importe))))
                continue


            # ── Red de seguridad: sin plata, no hay movimiento de caja ──────
            # Las filas con cantidad que SÍ mueven nominales ya se desviaron
            # arriba a `corporate`, y las ambiguas ya se reportaron. Lo que llega
            # acá con `kind` de caja y sin plata es una fila que ninguna rama
            # quiso (ej. trae precio pero no ticker): descartarla evita emitir un
            # FEE de monto 0 —que el validador rechaza— o reventar con `importe`
            # en None. Este guard estaba desde antes; la reclasificación de
            # arriba NO lo reemplaza, lo complementa.
            if kind in ("deposito", "retiro", "fee", "renta", "manual") and not has_cash:
                continue

            # ── Movimientos de efectivo / renta (precio=-1) ──────────────────
            if kind == "deposito":
                _emit(base("DEPOSITO" if cash_in else "RETIRO", monto=str(abs(importe))))
                continue
            if kind == "retiro":
                _emit(base("RETIRO" if not cash_in else "DEPOSITO", monto=str(abs(importe))))
                continue
            if kind == "fee":
                _emit(base("FEE", monto=str(abs(importe))))
                continue
            if kind == "renta":
                # ── Amortización que DEVUELVE CAPITAL (baja nominal) ──────────────
                # "Renta y Amortización" con cantidad ≠ 0 = el bono devolvió principal
                # (parcial o total). La pata del COBRO (entra) cierra ese nominal como
                # una VENTA a su valor de rescate (proceeds = el cobro) → P&L correcto
                # (devolución de capital, no pérdida fantasma; un precio=0 bookearía el
                # costo entero como pérdida). La retención/impuesto (sale) NO toca
                # nominal → va como FEE. Dedup por (ticker, fecha, |cantidad|): las 2
                # patas traen la misma cantidad, una sola cierra (si no, oversell).
                # Sin cantidad (cupón puro) → ingreso/retención de siempre.
                if has_qty and ticker and "amortizacion" in desc:
                    sig = (ticker, fecha, round(abs(qty), 3))
                    if cash_in and sig not in _amort_closed:
                        _amort_closed.add(sig)
                        _emit(base("VENTA", activo=ticker, cantidad=str(abs(qty)),
                                   monto=str(abs(importe))))
                        continue
                # cupón puro / retención / pata ya contada → ingreso o RETENCIÓN de impuesto
                _emit(base("DIVIDENDO" if cash_in else "IMPUESTO", monto=str(abs(importe))))
                continue
            if kind == "manual":
                # "Conversión CV X a CV Y" = transferencia entre buckets de dólar
                # (netea a 0: sale de 'Dólares C.V.' y entra a 'Dólares') → NO es fee
                # ni ingreso; se omite (sin efecto en el USD total, evita $ fantasma
                # de comisión + interés).
                if "conversion" in desc:
                    continue
                if cash_in:
                    _emit(base("INTERES", monto=str(abs(importe))))
                elif _is_tax(desc):
                    # "N/D Ret IIGG - IRSA/BYMA" y similares = impuesto, no comisión.
                    _emit(base("IMPUESTO", monto=str(abs(importe))))
                else:
                    # "Gastos por operación de Fondos" y cargos varios → fee real.
                    _emit(base("FEE", monto=str(abs(importe))))
                continue

            # ── Descripción NO reconocida → la MARCAMOS (no la tragamos en
            # silencio). Aparece vía el Import Guardian para que la soportemos, en
            # vez de mis-importarla como un depósito/retiro genérico. ────────────
            result.parse_errors.append(omitted_row_error(
                _row_i + 1, ticker, "BALANZ_MOV_DESC_DESCONOCIDA",
                f"Movimiento de Balanz no reconocido: '{desc_raw[:60]}'. Se omitió "
                f"esta fila — escribinos para soportarlo."))

        return result
