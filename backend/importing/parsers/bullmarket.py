"""Parser de Bull Market Brokers — dos layouts del mismo broker.

Bull Market expone los movimientos en DOS formatos distintos:

  1. "Cuenta Corriente" (Excel): columna `Comprobante` con descripciones
     ("COMPRA NORMAL", "RECIBO DE COBRO", …) y columnas Cantidad/Precio/Saldo
     separadas. El pipeline convierte el .xlsx a CSV antes de llegar acá.

  2. "Movimientos" (CSV compacto): columna `Cpbt.` con CÓDIGOS (COBA, CPRA,
     VTAS, VTU$, PAGA, DIV, RTA, SFCI, LRFD), cantidad y precio PEGADOS en un
     solo campo `Referencia/Cantidad/Precio`, y signo de `Importe` INVERTIDO
     (negativo = ingreso de plata). Es un único archivo con el historial completo.

`parse()` detecta el layout por el header y despacha al sub-parser correspondiente.

Cómo bajarlos (referencia para el wizard):
    Cuenta Corriente: MI CUENTA → CUENTA CORRIENTE → pestaña Pesos → Exportar (Excel)

Mapeo al modelo Rendi (Cuenta Corriente):

    Bull Market                  → Rendi      Notas
    ─────────────────────────────────────────────────────────────────────
    COMPRA NORMAL                → COMPRA     Acción / CEDEAR
    VENTA                        → VENTA
    RECIBO DE COBRO              → DEPOSITO   Ingreso de plata (CREDITO CTA CTE)
    ORDEN DE PAGO                → RETIRO     Egreso (TRANSFERENCIA VIA MEP)

Cauciones (COMPRA CAUCION CONTADO / VENTA CAUCION TERMINO, especie "VARIAS"):
    NO se cargan como activo (manejo de caja, no inversión). Pero su NETO (lo
    que volvió por encima de lo colocado) es interés real ganado → lo sumamos
    como UNA fila de INTERÉS (cuenta como ganancia realizada, no como depósito).
    Así no se pierde esa ganancia ni se crea el activo fantasma "VARIAS".

FCI (SUSCRIPCION FCI / LIQUIDACION RESCATE FCI):
    El CASH reconcilia (suscripción sin cantidad → RETIRO; rescate con cantidad
    → VENTA del fondo). La tenencia del FCI sigue siendo follow-up (la suscripción
    no trae unidades). Si el usuario tiene un FCI abierto hoy, lo carga manual.

Mapeo del layout Movimientos (códigos `Cpbt.`):

    Código   → Rendi                Notas
    ─────────────────────────────────────────────────────────────────────
    CPRA     → COMPRA               Importe POSITIVO (egreso)
    VTAS     → VENTA                Importe NEGATIVO (ingreso)
    COBA     → DEPOSITO             Recibo de cobro (Importe negativo)
    PAGA     → RETIRO               Orden de pago / transferencia MEP (positivo)
    SFCI     → RETIRO               Suscripción FCI (egreso)
    LRFD     → VENTA                Liquidación rescate FCI (ingreso, con cantidad)
    VTU$     → (MEP, ver abajo)     Venta paridad = pata dólar; Importe vacío
    DIV/CDIV/RTA → (omitidos)       El export casi nunca trae el monto del dividendo

    Dólar MEP (VTU$): el usuario compra un bono en pesos (CPRA) y lo vende contra
    dólar (VTU$, mismo especie, cantidad opuesta, Importe en pesos vacío). El bono
    NETEA a 0 (no es tenencia). La plata que salió en pesos (la CPRA) la cargamos
    como RETIRO ("Dólar MEP vía X"): los dólares quedan en la cuenta USD, fuera de
    este export. Cualquier especie que aparezca en una fila VTU$ se trata así.

Particularidades:
- Fecha = `Operado`. En el Excel ya viene ISO; en el CSV de Movimientos viene
  dd/mm/aaaa (el normalizer la pasa a ISO después).
- Importe = cantidad × precio (sin comisiones desglosadas) → comisiones = 0.
- Tickers: Bull Market usa el símbolo BYMA salvo algún caso (YPF → YPFD).
- Bonos: pueden venir per-100 (lo detectamos por cantidad×precio ≈ 100×importe).
- Moneda: el Excel la saca del nombre de la hoja; el CSV de Movimientos es ARS.
"""
from __future__ import annotations
import csv
import io
import re
from typing import List, Optional
from .base import Parser
from ..schema import ParseResult, RawRow, RowError


# Headers mínimos para reconocer un export de Bull Market (cualquiera de los dos
# layouts). `comprobante`/`cpbt` se chequean aparte para elegir el sub-parser.
_REQUIRED_HEADERS = {"liquida", "operado", "especie", "importe"}

# Comprobante (lowercase) → categoría Rendi, por PREFIJO (Bull Market tiene muchas
# variantes: COMPRA NORMAL/PARIDAD/EXTERIOR, RENTA Y AMORTIZ, DIVIDENDOS DOLARES
# CABLE, etc.). `Importe` es el efecto en caja → el tipo se elige para que el signo
# matchee y reconcilie por construcción. Las cauciones, conversiones cable↔MEP y
# FCI NO pasan por acá (se manejan antes en _parse_cuenta_corriente()).
def _classify_comprobante(comp_lc: str) -> Optional[str]:
    # FCI (fondos): el RESCATE trae cantidad+precio+especie → VENTA del fondo (su
    # cash entra y la tenencia baja). La SUSCRIPCION NO trae cantidad → solo el
    # cash que sale → RETIRO (la tenencia del FCI no se puede reconstruir desde la
    # cuenta corriente; sigue siendo follow-up). Sin esto, el neto FCI no se
    # contaba y la caja no cerraba.
    if comp_lc.startswith("liquidacion rescate fci") or comp_lc.startswith("rescate fci"):
        return "VENTA"
    if comp_lc.startswith("suscripcion fci") or comp_lc.startswith("suscripcion fondo"):
        return "RETIRO"
    if comp_lc.startswith("compra"):            # normal / paridad / exterior
        return "COMPRA"
    if comp_lc.startswith("venta"):             # normal / paridad
        return "VENTA"
    if comp_lc.startswith("recibo de cobro") or comp_lc.startswith("rec cobro"):
        return "DEPOSITO"                       # CREDITO CTA CTE = ingreso de plata
    if comp_lc.startswith("orden de pago"):     # TRANSFERENCIA = egreso
        return "RETIRO"
    # Ingresos por título: cupón + amortización de bono, dividendos (todas las
    # variantes), pago de dividendos. (La amortización baja nominal → follow-up;
    # acá solo cuenta como ingreso de caja, que es lo que reconcilia.)
    if (comp_lc.startswith("renta") or comp_lc.startswith("dividendo")
            or comp_lc.startswith("pago div") or comp_lc.startswith("amortiz")):
        return "DIVIDENDO"
    # Retenciones, gastos y aranceles (notas de débito/crédito): efecto chico de
    # caja → FEE si sale, ingreso si entra (lo decide el signo en parse()).
    if (comp_lc.startswith("retencion") or comp_lc.startswith("nd ")
            or comp_lc.startswith("nc ") or "gasto" in comp_lc or "arancel" in comp_lc):
        return "FEE_SIGNED"
    return None


# Layout Movimientos: código `Cpbt.` (primeros 4 chars, lowercase) → tipo Rendi.
# La DIRECCIÓN final del cash (DEPOSITO vs RETIRO) se ajusta por el signo del
# Importe en _parse_movimientos (en este export negativo = ingreso). VTU$ y
# DIV/CDIV/RTA NO van acá (se manejan aparte).
_MOV_CODE_MAP = {
    "cpra": "COMPRA",
    "vtas": "VENTA",
    "coba": "DEPOSITO",   # recibo de cobro (importe negativo); dirección por signo
    "paga": "RETIRO",     # orden de pago (importe positivo); dirección por signo
    "sfci": "RETIRO",     # suscripción FCI (egreso de plata)
    "lrfd": "VENTA",      # liquidación rescate FCI (ingreso, con cantidad)
}

# Normalización de tickers Bull Market → símbolo BYMA/Rendi. Pass-through si no
# está en el mapa. Crecé este dict si aparecen precios que no resuelven.
_TICKER_MAP = {
    "YPF": "YPFD",   # en BYMA la acción local de YPF cotiza como YPFD
}


def _strip(s) -> str:
    return (s or "").strip()


def _norm_header(h: str) -> str:
    if not h:
        return ""
    s = (h.strip().lower()
            .replace("ó", "o").replace("í", "i").replace("á", "a")
            .replace("é", "e").replace("ú", "u").replace("ñ", "n"))
    return s.replace(" ", "")


def _num(s: str) -> Optional[float]:
    """Parsea un número que puede venir point-decimal (xlsx → '3744.87') o en
    formato AR ('3.744,87'). Devuelve None si no parsea."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        if "," in s:
            # Formato AR: '.' miles, ',' decimal.
            s = s.replace(".", "").replace(",", ".")
        return float(s)
    except (ValueError, TypeError):
        return None


def _detect_delimiter(first_line: str) -> str:
    """xlsx→csv usa ','. CSV nativo podría usar ';'. Elegimos el más frecuente."""
    counts = {d: first_line.count(d) for d in (",", ";", "\t")}
    return max(counts, key=counts.get) if max(counts.values()) > 0 else ","


def _norm_ticker(especie: str) -> Optional[str]:
    t = (especie or "").strip().upper()
    if not t or t == "VARIAS":
        return None
    return _TICKER_MAP.get(t, t)


def _currency_from_sheet(hoja: str) -> str:
    """Moneda de la fila según el nombre de la hoja del Excel. Bull Market
    nombra las hojas 'Cuenta Corriente PESOS …' / 'DOLARES …' / 'DOLARES CABLE …'.
    El conversor de xlsx agrega ese nombre como columna sintética '_hoja' a cada
    fila, así la moneda sobrevive a la combinación de varios archivos."""
    return "USD" if "DOLAR" in (hoja or "").upper() else "ARS"


def _col(norm_to_orig: dict, *prefixes: str) -> Optional[str]:
    """Devuelve el nombre ORIGINAL de la primera columna cuyo header normalizado
    arranque con alguno de los prefijos dados (p.ej. 'cpbt' matchea 'cpbt.')."""
    for norm, orig in norm_to_orig.items():
        if any(norm.startswith(p) for p in prefixes):
            return orig
    return None


def _iso_date(s: str) -> str:
    """dd/mm/aa(aa) → yyyy-mm-dd. El export de Movimientos trae el año en 2
    dígitos (07/08/23), que el normalizer rechaza (exige \\d{4}). Lo pasamos a ISO
    acá. Si no matchea, devolvemos el string crudo (que el normalizer intente)."""
    s = (s or "").strip()
    m = re.match(r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{2}|\d{4})$", s)
    if not m:
        return s
    d, mo, y = m.groups()
    if len(y) == 2:
        y = f"20{y}" if int(y) < 70 else f"19{y}"
    try:
        di, moi, yi = int(d), int(mo), int(y)
        if 1 <= moi <= 12 and 1 <= di <= 31:
            return f"{yi:04d}-{moi:02d}-{di:02d}"
    except ValueError:
        pass
    return s


def _split_ref(s: str):
    """Campo `Referencia/Cantidad/Precio` del layout Movimientos: si arranca con
    un número → (cantidad, precio, ''); si no → (None, None, texto). El precio es
    el segundo token (puede no estar). Maneja formato AR y point-decimal."""
    s = (s or "").strip()
    if not s:
        return (None, None, "")
    toks = s.split()
    qty = _num(toks[0])
    if qty is None:
        return (None, None, s)          # referencia textual (CREDITO CTA. CTE., …)
    price = _num(toks[1]) if len(toks) > 1 else None
    return (qty, price, "")


def _mk_row(idx, fecha, tipo, activo, cantidad, precio, monto, moneda, notas) -> RawRow:
    def fmt(v):
        return "" if v is None or v == "" else f"{v}"
    return RawRow(row_index=idx, data={
        "fecha":      fecha or "",
        "tipo":       tipo,
        "broker":     "Bull Market",
        "activo":     activo or "",
        "cantidad":   fmt(cantidad),
        "precio":     fmt(precio),
        "monto":      fmt(monto),
        "monto_usd":  "",
        "tc":         "",
        "comisiones": "0",
        "moneda":     moneda,
        "notas":      notas or "",
    })


class BullMarketParser(Parser):
    format_id = "bullmarket"
    display_name = "Bull Market"
    is_supported = True
    platform = "bullmarket"
    platform_label = "Bull Market"
    export_label = "Cuenta Corriente (Excel) o Movimientos (CSV)"

    def can_handle(self, headers: List[str]) -> bool:
        norm = {_norm_header(h) for h in headers}
        if len(_REQUIRED_HEADERS & norm) < len(_REQUIRED_HEADERS):
            return False
        # Tiene que ser reconocible como uno de los dos layouts (Comprobante o Cpbt.).
        return "comprobante" in norm or any(h.startswith("cpbt") for h in norm)

    def parse(self, content: str, file_name: Optional[str] = None) -> ParseResult:
        result = ParseResult()
        if content.startswith("﻿"):
            content = content[1:]
        first_line = content.split("\n", 1)[0] if content else ""
        delim = _detect_delimiter(first_line)
        try:
            reader = csv.DictReader(io.StringIO(content), delimiter=delim)
            raw_headers = reader.fieldnames or []
        except Exception as ex:
            result.parse_errors.append(RowError(
                0, None, "FILE_UNREADABLE", f"No pudimos leer el archivo: {ex}",
            ))
            return result

        norm_to_orig = {_norm_header(h): h for h in raw_headers}
        norm_set = set(norm_to_orig.keys())
        has_comprobante = "comprobante" in norm_set
        has_cpbt = any(h.startswith("cpbt") for h in norm_set)
        if (not (has_comprobante or has_cpbt)
                or len(_REQUIRED_HEADERS & norm_set) < len(_REQUIRED_HEADERS)):
            result.parse_errors.append(RowError(
                0, None, "BULLMARKET_HEADERS_MISMATCH",
                "Este archivo no parece un export de Bull Market. Bajá la Cuenta "
                "Corriente (Mi Cuenta → Cuenta Corriente → Exportar) o el resumen "
                "de Movimientos.",
            ))
            return result

        # Materializamos para poder hacer dos pasadas en el layout Movimientos.
        rows = list(reader)
        # Dos layouts del mismo broker: 'Comprobante' (Cuenta Corriente, Excel) vs
        # 'Cpbt.' con códigos + cantidad/precio pegados (Movimientos, CSV compacto).
        if has_cpbt and not has_comprobante:
            return self._parse_movimientos(rows, norm_to_orig)
        return self._parse_cuenta_corriente(rows, norm_to_orig)

    # ── Layout 1: Cuenta Corriente (Excel) ──────────────────────────────────
    def _parse_cuenta_corriente(self, rows: list, norm_to_orig: dict) -> ParseResult:
        result = ParseResult()

        def G(row, norm_key: str) -> str:
            col = norm_to_orig.get(norm_key)
            return _strip(row.get(col, "")) if col else ""

        # Cauciones: acumulamos su neto (= interés) POR MONEDA → una fila de
        # INTERÉS por moneda al final. last_idx indexa esas filas sintéticas.
        caucion_net = {}        # moneda → neto
        caucion_last_date = {}  # moneda → última fecha
        last_idx = 0

        for idx, row in enumerate(rows, start=1):
            last_idx = idx
            comprobante = G(row, "comprobante")
            comp_lc = comprobante.lower()
            if not comp_lc:
                continue  # fila vacía

            # Moneda de la fila por el nombre de la hoja (PESOS→ARS, DOLARES→USD).
            moneda = _currency_from_sheet(G(row, "_hoja"))

            # Cauciones (especie VARIAS): manejo de caja, no inversión. Acumulamos
            # su neto = interés ganado (por moneda) → fila de INTERÉS al final.
            # No crea el activo fantasma "VARIAS" ni infla el capital aportado.
            if "caucion" in comp_lc:
                v = _num(G(row, "importe"))
                if v is not None:
                    caucion_net[moneda] = caucion_net.get(moneda, 0.0) + v
                    d = G(row, "operado") or G(row, "liquida")
                    if d > caucion_last_date.get(moneda, ""):
                        caucion_last_date[moneda] = d
                continue

            # Conversiones internas cable↔MEP (NOTA DE CRÉDITO/DÉBITO U$S): mueven
            # los mismos dólares entre sub-cuentas y se cancelan entre archivos →
            # no son ingreso/egreso ni ganancia. Se omiten.
            if "nota de" in comp_lc and "u$s" in comp_lc:
                continue

            # FCI: el cash SÍ se cuenta (RESCATE→VENTA con sus datos, SUSCRIPCION→
            # RETIRO sin cantidad) — ver _classify_comprobante. La SUSCRIPCION no
            # trae unidades → la TENENCIA del FCI no se reconstruye (sigue siendo
            # carga manual / export de tenencias); pero la CAJA ahora reconcilia.
            tipo_rendi = _classify_comprobante(comp_lc)
            if tipo_rendi is None:
                # Tipo no soportado → lo reportamos pero seguimos (lo caza el
                # Import Guardian, no se mis-importa en silencio).
                result.parse_errors.append(RowError(
                    idx, "Comprobante", "BULLMARKET_OP_UNKNOWN",
                    f"Tipo de comprobante no soportado: '{comprobante}'.",
                ))
                continue

            # Reconciliación por SIGNO: `Importe` manda la dirección del cash.
            #  • FEE_SIGNED (retención/gasto/arancel) → FEE si sale, ingreso si entra.
            #  • Un dividendo/depósito/retiro con signo invertido (ej. una fila
            #    "DIVIDENDOS" con Importe NEGATIVO = retención/reverso) va al tipo
            #    opuesto, así el cash emitido siempre matchea el Importe (sin esto,
            #    el abs() contaba esa retención como ingreso → no reconciliaba).
            imp_sign = _num(G(row, "importe")) or 0.0
            if tipo_rendi == "FEE_SIGNED":
                tipo_rendi = "FEE" if imp_sign < 0 else "DIVIDENDO"
            elif tipo_rendi == "DIVIDENDO" and imp_sign < 0:
                tipo_rendi = "FEE"
            elif tipo_rendi == "DEPOSITO" and imp_sign < 0:
                tipo_rendi = "RETIRO"
            elif tipo_rendi == "RETIRO" and imp_sign > 0:
                tipo_rendi = "DEPOSITO"

            fecha = G(row, "operado") or G(row, "liquida")
            numero = G(row, "numero")

            if tipo_rendi in ("COMPRA", "VENTA"):
                ticker = _norm_ticker(G(row, "especie"))
                if not ticker:
                    # Trade sin ticker válido (ej. "VARIAS" que se nos escapó) → skip.
                    continue
                qty_v = _num(G(row, "cantidad"))
                imp_v = _num(G(row, "importe"))
                price_v = _num(G(row, "precio"))
                qty = f"{abs(qty_v)}" if qty_v is not None else ""
                monto = f"{abs(imp_v)}" if imp_v is not None else ""
                precio = f"{abs(price_v)}" if price_v is not None else ""
                activo = ticker
            elif tipo_rendi == "DIVIDENDO":
                # Dividendo en USD: la especie es el activo (GOOGL, EWZ…), el
                # monto es el importe. El persister lo trata como ganancia.
                imp_v = _num(G(row, "importe"))
                monto = f"{abs(imp_v)}" if imp_v is not None else ""
                activo = _norm_ticker(G(row, "especie")) or ""
                qty = ""
                precio = ""
            else:
                # DEPOSITO / RETIRO: solo plata.
                imp_v = _num(G(row, "importe"))
                monto = f"{abs(imp_v)}" if imp_v is not None else ""
                qty = ""
                precio = ""
                activo = ""

            notas = f"Op. {numero}" if numero else ""

            data = {
                "fecha":      fecha or "",
                "tipo":       tipo_rendi,
                "broker":     "Bull Market",
                "activo":     activo,
                "cantidad":   qty,
                "precio":     precio,
                "monto":      monto,
                "monto_usd":  "",
                "tc":         "",
                "comisiones": "0",
                "moneda":     moneda,
                "notas":      notas,
            }
            result.raw_rows.append(RawRow(row_index=idx, data=data))

        # Interés de cauciones por moneda: el neto positivo (lo que volvió por
        # encima de lo colocado) es interés ganado → una fila de INTERÉS por
        # moneda. Solo si es > 0 (un neto ≤ 0 implicaría una caución abierta al
        # cierre → lo omitimos para no inventar una pérdida fantasma).
        for moneda, net in caucion_net.items():
            if net > 0:
                last_idx += 1
                result.raw_rows.append(RawRow(row_index=last_idx, data={
                    "fecha":      caucion_last_date.get(moneda, "") or "",
                    "tipo":       "INTERES",
                    "broker":     "Bull Market",
                    "activo":     "",
                    "cantidad":   "",
                    "precio":     "",
                    "monto":      f"{net:.2f}",
                    "monto_usd":  "",
                    "tc":         "",
                    "comisiones": "0",
                    "moneda":     moneda,
                    "notas":      "Interés de cauciones",
                }))

        return result

    # ── Layout 2: Movimientos (CSV compacto, códigos `Cpbt.`) ────────────────
    def _parse_movimientos(self, rows: list, norm_to_orig: dict) -> ParseResult:
        result = ParseResult()
        cpbt_col = _col(norm_to_orig, "cpbt")
        ref_col = _col(norm_to_orig, "referencia")
        op_col = norm_to_orig.get("operado")
        liq_col = norm_to_orig.get("liquida")
        imp_col = norm_to_orig.get("importe")
        esp_col = norm_to_orig.get("especie")
        num_col = norm_to_orig.get("numero")

        def gv(row, col) -> str:
            return _strip(row.get(col, "")) if col else ""

        # Pass 1: especies que aparecen en VTU$ (venta paridad = pata dólar del
        # MEP). Sus compras en pesos son "compra de dólares" (ver abajo).
        mep_especies = set()
        for row in rows:
            if gv(row, cpbt_col).upper().startswith("VTU"):
                esp = _norm_ticker(gv(row, esp_col))
                if esp:
                    mep_especies.add(esp)

        for idx, row in enumerate(rows, start=1):
            operado = gv(row, op_col)
            liquida = gv(row, liq_col)
            if not operado and not liquida:
                continue  # filas de leyenda / totales al pie (sin fecha)
            code = gv(row, cpbt_col).upper()
            if not code:
                continue

            fecha = _iso_date(operado or liquida)
            numero = gv(row, num_col)
            notas = f"Op. {numero}" if numero else ""
            importe = _num(gv(row, imp_col))
            especie = _norm_ticker(gv(row, esp_col))
            qty, price, _txt = _split_ref(gv(row, ref_col))

            # VTU$ (venta paridad): pata dólar del MEP. El Importe en pesos viene
            # vacío → no hay cash acá. Su único efecto es netear el bono comprado
            # (lo hacemos vía la especie MEP, abajo). Se omite.
            if code.startswith("VTU"):
                continue

            # Especie dolarizada vía MEP: la COMPRA en pesos del bono fue para
            # comprar dólares (que quedan en la cuenta USD, fuera de este export).
            # La registramos como RETIRO de pesos y NO creamos la posición del bono
            # (neto 0). Otras filas de esa especie sin monto (RTA, etc.) se omiten.
            if especie and especie in mep_especies:
                if code.startswith("CPRA") and importe is not None:
                    nt = f"Dólar MEP vía {especie}" + (f" · {notas}" if notas else "")
                    result.raw_rows.append(
                        _mk_row(idx, fecha, "RETIRO", "", "", "", abs(importe), "ARS", nt))
                continue

            # Dividendos / renta-amortización: este export casi nunca trae el monto
            # y los pocos que trae son ambiguos (bruto vs retención) → NO los
            # importamos como ingreso para no inventar números. El detalle de
            # dividendos está en el reporte de Resultados.
            if code.startswith(("DIV", "CDIV", "RTA")):
                continue

            tipo = _MOV_CODE_MAP.get(code[:4].lower())
            if tipo is None:
                result.parse_errors.append(RowError(
                    idx, "Cpbt.", "BULLMARKET_OP_UNKNOWN",
                    f"Código de comprobante no soportado: '{code}'.",
                ))
                continue

            # Cash (COBA/PAGA y SFCI): la DIRECCIÓN la manda el signo del Importe
            # (en este export negativo = ingreso, positivo = egreso) → reconcilia
            # por construcción.
            if tipo in ("DEPOSITO", "RETIRO") and importe is not None:
                tipo = "DEPOSITO" if importe < 0 else "RETIRO"

            if tipo in ("COMPRA", "VENTA"):
                if not especie:
                    continue
                monto = abs(importe) if importe is not None else None
                q = abs(qty) if qty is not None else None
                p = abs(price) if price is not None else None
                # Bono per-100: si cantidad×precio ≈ 100×importe → el precio viene
                # per-100 (lo pasamos a per-1). Para CEDEARs/acciones no dispara.
                if q and p and monto and abs(q * p - 100 * monto) < abs(q * p - monto):
                    p = p / 100.0
                result.raw_rows.append(
                    _mk_row(idx, fecha, tipo, especie, q, p, monto, "ARS", notas))
            else:
                # DEPOSITO / RETIRO / FCI: solo plata.
                monto = abs(importe) if importe is not None else None
                result.raw_rows.append(
                    _mk_row(idx, fecha, tipo, "", "", "", monto, "ARS", notas))

        return result
