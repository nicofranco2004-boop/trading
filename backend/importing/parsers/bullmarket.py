"""Parser de Bull Market Brokers — tres layouts del mismo broker.

Bull Market expone los movimientos en TRES formatos distintos:

  1. "Cuenta Corriente" (Excel): columna `Comprobante` con descripciones
     ("COMPRA NORMAL", "RECIBO DE COBRO", …) y columnas Cantidad/Precio/Saldo
     separadas. El pipeline convierte el .xlsx a CSV antes de llegar acá.

  2. "Movimientos" (CSV compacto): columna `Cpbt.` con CÓDIGOS (COBA, CPRA,
     VTAS, VTU$, PAGA, DIV, RTA, SFCI, LRFD), cantidad y precio PEGADOS en un
     solo campo `Referencia/Cantidad/Precio`, y signo de `Importe` INVERTIDO
     (negativo = ingreso de plata). Es un único archivo con el historial completo.

  3. "Histórico compacto" (CSV que Bull Market MANDA POR MAIL, partido en varios
     archivos por período — reporte de un usuario, 2026-09-09). Header:
     `F.Liquid;Cpbt;N.Cpbt;Importe;Dolares;Mda;Ref./Cantidad`. No trae ni
     `Especie` ni `Saldo` ni `Operado`: el TICKER viaja pegado a la cantidad
     dentro de `Ref./Cantidad` ("833.0000  GD30"; las ventas marcan el signo con
     un guión pegado atrás, "247.0000- TXAR") y NO trae precio: se deriva como
     importe ÷ cantidad, que ya sale per-1 (no hace falta el ajuste per-100).

     Lo que lo hace distinto de verdad son las columnas `Dolares` + `Mda`: el
     archivo lista LAS DOS sub-cuentas (pesos y dólares) en una sola tabla.
     Cuando `Mda` viene lleno (U$S / DOLAR) la plata REAL de esa fila es la de
     `Dolares`; el `Importe` de esas filas es sólo el equivalente en pesos al
     dólar OFICIAL, para que cierre el total del pie. Tomarlo como pesos sería
     cargar un dividendo de US$2,57 como $460 — y al TC oficial, encima.
     Verificado contra los dos archivos reales del usuario: la suma del `Importe`
     de las filas SIN `Mda` del archivo 2021-2022 da -630,92, que es exactamente
     el `S.ANTERIOR` (-630,93) con el que abre el archivo 2023-2024; y la suma de
     `Dolares` de un archivo (+555,78) cancela con la del otro (-555,78).

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
# `operado` NO va acá: el export "Histórico" (el que Bull Market manda por mail
# a las cuentas con historia larga) trae SOLO `Liquida` — el gate lo rechazaba
# con "no parece un export de Bull Market" (reporte de un usuario, 2026-07-29).
_REQUIRED_HEADERS = {"liquida", "especie", "importe"}

# El TERCER layout ("Histórico compacto", el que Bull Market manda por mail en
# archivos partidos por período — ver docstring del módulo) no trae ni `Especie`
# ni `Operado` ni `Saldo`: el ticker viaja PEGADO a la cantidad y la fecha se
# llama `F.Liquid`. Tiene su propio juego mínimo de headers.
_REQUIRED_HEADERS_HIST = {"f.liquid", "importe", "dolares", "mda"}

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
    # Licitación primaria/privada de letras y bonos: es una COMPRA (trae especie,
    # cantidad y precio) — solo que el comprobante no empieza con "compra".
    if comp_lc.startswith("licitacion"):
        return "COMPRA"
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

# Layout 3 (Histórico compacto): código `Cpbt` → tipo Rendi. Se consulta ANTES
# que la leyenda del pie, porque acá hay códigos de la sub-cuenta en DÓLARES
# (CDOA/PU$A: cobro y pago EN dólares) que en este layout sí se pueden importar
# bien —la columna `Dolares` trae el monto real— y en los otros dos layouts NO
# (ahí sólo está la columna en pesos, así que siguen dando error visible en vez
# de importarse en la moneda equivocada). Los tipos "_SIGNED" los resuelve el
# signo del Importe más abajo (en este layout negativo = ENTRA plata).
_HIST_CODE_MAP = {
    "coba": "DEPOSITO",     # recibo de cobro (pesos)
    "cdoa": "DEPOSITO",     # rec. cobro dólares
    "paga": "RETIRO",       # orden de pago (pesos)
    "pu$a": "RETIRO",       # ord. pago dólares
    "cpra": "COMPRA",
    "vtas": "VENTA",
    "cpu$": "COMPRA",       # compra paridad — puede ser pata de un MEP (ver abajo)
    "vtu$": "VENTA",        # venta paridad  — ídem
    "sfci": "RETIRO",       # suscripción FCI
    "lrfd": "VENTA",        # liquidación rescate FCI
    "div":  "DIV_SIGNED",   # dividendos
    "cdiv": "DIV_SIGNED",   # pago de dividendos / fracciones
    "ddiv": "DIV_SIGNED",
    "rta":  "DIV_SIGNED",   # renta y amortización de bonos
    "drep": "FEE_SIGNED",   # retención
    "drec": "FEE_SIGNED",   # retención dólares
    "nocr": "FEE_SIGNED",   # devolución de retención (entra plata → ingreso)
    "dtrt": "FEE_SIGNED",   # gastos de transferencia de títulos
    "canj": "FEE_SIGNED",   # canje: sólo queda el residuo de caja
    # Notas de crédito/débito en dólares: cuando vienen EMPAREJADAS son una
    # conversión cable↔MEP y se omiten (ver _HIST_NOTA_USD). Una nota suelta —el
    # export real trae una, "RET BS PS/GCIA"— es una retención de verdad y se
    # cobra por signo. Sin esta entrada quedaba como código no soportado y la
    # caja en dólares cerraba 0,04 corrida.
    "du$v": "FEE_SIGNED",
    "cu$v": "FEE_SIGNED",
}

# Layout 3: notas de crédito/débito en dólares. Son las conversiones internas
# cable↔MEP: mueven LOS MISMOS dólares entre sub-cuentas y vienen SIEMPRE de a
# pares que se cancelan (mismo día, mismo monto, signo opuesto). Emparejadas se
# omiten —igual que en la Cuenta Corriente—; suelta, una nota de débito es una
# retención real y se cobra por signo.
_HIST_NOTA_USD = ("du$v", "cu$v")

# Palabras que aparecen como PRIMER token de `Ref./Cantidad` y NO son un ticker
# (el campo mezcla referencias de dividendo, plazas y textos libres).
_HIST_NO_TICKER = {
    "BYMA", "MAE", "RET", "DEV", "PAGO", "FRACC", "CONV", "CABLE", "TENENCIA",
    "CREDITO", "DEBITO", "TRANSFERENCIA", "GTOS", "GTO", "RETENCION",
    "RETENCIONES", "CTA", "S", "ANT", "TOTAL", "DOLAR", "DOLARES", "MEP",
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


def _num_us(s: str) -> Optional[float]:
    """Número del campo `Ref./Cantidad` del layout Histórico compacto. OJO: acá
    el formato es AL REVÉS que el de `Importe` — la cantidad viene a la yanqui
    ('1,400.0000' = mil cuatrocientos) mientras que el importe de la MISMA fila
    viene a la argentina ('79.992,31'). Y las ventas marcan el signo con un
    guión PEGADO ATRÁS ('247.0000-'), no adelante."""
    s = (s or "").strip()
    if not s:
        return None
    neg = s.endswith("-")
    if neg:
        s = s[:-1]
    s = s.replace(",", "")
    if not re.match(r"^\d+(\.\d+)?$", s):
        return None
    v = float(s)
    return -v if neg else v


def _split_ref_hist(s: str):
    """Campo `Ref./Cantidad` → (cantidad_con_signo, ticker, texto_crudo).

    Tres formas reales en el archivo:
      · "833.0000  GD30"      → operación: cantidad + TICKER (no hay precio)
      · "8044 BYMA" / "322"   → referencia del dividendo (número de plaza/cupón)
      · "CREDITO CTA. CTE."   → texto libre
    Devolvemos el ticker sólo cuando el token parece uno de verdad; quién puede
    usarlo (operación vs dividendo) lo decide el llamador, que sabe el código."""
    s = (s or "").strip()
    toks = s.split()
    if not toks:
        return (None, None, "")
    qty = _num_us(toks[0])
    tk = None
    cand = toks[1] if (qty is not None and len(toks) > 1) else (toks[0] if qty is None else None)
    if cand:
        c = cand.strip().upper()
        if c not in _HIST_NO_TICKER and re.match(r"^[A-Z][A-Z0-9]{0,9}$", c):
            tk = c
    return (qty, tk, s)


def _add_days(iso: str, n: int) -> str:
    """ISO ± n días. Sin dependencias: sólo se usa para fechar el saldo inicial
    un día antes del primer movimiento, así no compite por el desempate de orden
    con una operación del mismo día."""
    try:
        import datetime as _dt
        y, m, d = (int(x) for x in iso.split("-"))
        return (_dt.date(y, m, d) + _dt.timedelta(days=n)).isoformat()
    except Exception:
        return iso


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
    tenencia_format = "bullmarket_tenencia"

    def can_handle(self, headers: List[str]) -> bool:
        norm = {_norm_header(h) for h in headers}
        # Layout 3 (Histórico compacto por mail): no trae `Especie`, así que no
        # pasa el gate de los otros dos. Se reconoce por su propio juego de
        # headers + la columna de código `Cpbt` (sin punto).
        if (len(_REQUIRED_HEADERS_HIST & norm) == len(_REQUIRED_HEADERS_HIST)
                and any(h.startswith("cpbt") for h in norm)):
            return True
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
        # Layout 3 (Histórico compacto por mail): sin `Especie`, con `Dolares`+`Mda`.
        if (has_cpbt
                and len(_REQUIRED_HEADERS_HIST & norm_set) == len(_REQUIRED_HEADERS_HIST)):
            return self._parse_historico_compacto(list(reader), norm_to_orig)
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
        indice_net = {}         # ídem para futuros de dólar en A3/Matba-Rofex
        indice_last_date = {}
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

            # Futuros de dólar en A3/Matba-Rofex (CPRA/VTA INDICE A3 MTR, CREDITO
            # POR GANANCIA / DEBITO POR PERDIDA INDICE): el contrato no es una
            # tenencia (especie "DLR072023") → igual que las cauciones, solo su
            # NETO cuenta, como resultado. Antes caían en "tipo no soportado" y
            # se perdían: 58 filas en el export de un usuario real.
            if "indice" in comp_lc or "a3 mtr" in comp_lc:
                v = _num(G(row, "importe"))
                if v is not None:
                    indice_net[moneda] = indice_net.get(moneda, 0.0) + v
                    d = G(row, "operado") or G(row, "liquida")
                    if d > indice_last_date.get(moneda, ""):
                        indice_last_date[moneda] = d
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

        # Resultado de los futuros de dólar (A3): acá el neto SÍ puede ser
        # negativo (una posición perdedora es una pérdida real, no un contrato
        # abierto) → INTERÉS si ganó, FEE si perdió.
        for moneda, net in indice_net.items():
            if abs(net) < 0.01:
                continue
            last_idx += 1
            result.raw_rows.append(RawRow(row_index=last_idx, data={
                "fecha":      indice_last_date.get(moneda, "") or "",
                "tipo":       "INTERES" if net > 0 else "FEE",
                "broker":     "Bull Market",
                "activo":     "",
                "cantidad":   "",
                "precio":     "",
                "monto":      f"{abs(net):.2f}",
                "monto_usd":  "",
                "tc":         "",
                "comisiones": "0",
                "moneda":     moneda,
                "notas":      "Resultado de futuros de dólar (A3)",
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

        # Pass 1a: LEYENDA del pie. El export trae, después de los movimientos,
        # una fila por código con su descripción larga — LAS MISMAS que usa la
        # Cuenta Corriente ("CPRA = COMPRA", "COBA = RECIBO DE COBRO", …). La
        # leemos y clasificamos con _classify_comprobante: así un código nuevo
        # que Bull Market agregue mañana se entiende solo, sin tocar el mapa.
        # (Las filas de leyenda no tienen fecha; van en Especie=código,
        # Referencia=descripción.)
        legend = {}
        for row in rows:
            if gv(row, op_col) or gv(row, liq_col):
                continue
            code_l, desc_l = gv(row, esp_col), gv(row, ref_col)
            if code_l and desc_l:
                # Doble espacio real en el archivo ("ORDEN  DE PAGO") — normalizar
                # o el startswith del clasificador no matchea.
                legend[code_l.upper()] = re.sub(r"\s+", " ", desc_l).strip()

        def _tipo_de(code: str) -> Optional[str]:
            """Código → tipo Rendi: primero la leyenda del propio archivo, si no
            el mapa fijo (exports viejos que no la traen)."""
            desc = legend.get(code.upper())
            if desc:
                t = _classify_comprobante(desc.lower())
                if t:
                    return t
            return _MOV_CODE_MAP.get(code[:4].lower())

        def _es_caucion(code: str) -> bool:
            # CCDO/VTCT/VTCC/CPCT — y cualquier código nuevo cuya leyenda diga
            # "caución". Mismo criterio que la Cuenta Corriente: manejo de caja,
            # no inversión → solo su NETO cuenta, como interés.
            if code[:4].lower() in ("ccdo", "vtct", "vtcc", "cpct"):
                return True
            return "caucion" in (legend.get(code.upper(), "").lower())

        def _es_indice(code: str) -> bool:
            # Futuros de dólar en A3/Matba-Rofex (CIRM/VIRM compra-venta del
            # contrato, CRGI/DBPI resultado diario, DECU retención). El contrato
            # NO es una tenencia (especie tipo "DLR072023") → se netea como
            # resultado, igual que las cauciones. Sin esto entraba un activo
            # fantasma por cada vencimiento.
            if code[:4].lower() in ("crgi", "dbpi", "virm", "cirm", "decu"):
                return True
            d = legend.get(code.upper(), "").lower()
            return "indice" in d or "a3 mtr" in d

        # Pass 1b: PATAS del dólar bolsa. Hay dos sentidos y ANTES se trataban
        # mal (se descartaba TODA fila de una especie que alguna vez hizo MEP —
        # en el histórico de un usuario eso se comió 4 ventas reales por
        # $3.581.048):
        #   · comprar dólares → CPRA (bono en pesos, sale plata) + VTU$ (venta
        #     paridad, sin importe en pesos)  → la CPRA es un RETIRO de pesos.
        #   · vender dólares  → CPU$ (compra paridad, sin importe) + VTAS (venta
        #     del bono en pesos, entra plata) → la VTAS es un DEPOSITO de pesos.
        # El bono NETEA a 0 en ambos casos (no es tenencia). Emparejamos cada
        # pata dólar con su pata pesos por (especie, cantidad); lo que no
        # empareja es una compra/venta común y se importa como tal.
        def _key_ref(row):
            q, _p, _t = _split_ref(gv(row, ref_col))
            esp = _norm_ticker(gv(row, esp_col))
            return (esp, round(abs(q), 6)) if (esp and q) else None

        mep_buy_legs, mep_sell_legs = {}, {}   # (especie, |qty|) → cuántas patas
        for row in rows:
            c = gv(row, cpbt_col).upper()
            k = _key_ref(row)
            if not k:
                continue
            if c.startswith("VTU"):            # venta paridad → compró dólares
                mep_buy_legs[k] = mep_buy_legs.get(k, 0) + 1
            elif c.startswith("CPU"):          # compra paridad → vendió dólares
                mep_sell_legs[k] = mep_sell_legs.get(k, 0) + 1

        # Netos que se emiten como UNA fila sintética al final (ver arriba).
        caucion_net = 0.0
        indice_net = 0.0
        last_fecha = ""

        for idx, row in enumerate(rows, start=1):
            operado = gv(row, op_col)
            liquida = gv(row, liq_col)
            if not operado and not liquida:
                continue  # filas de leyenda / totales al pie (sin fecha)
            code = gv(row, cpbt_col).upper()
            if not code:
                continue

            fecha = _iso_date(operado or liquida)
            if fecha:
                last_fecha = fecha
            numero = gv(row, num_col)
            notas = f"Op. {numero}" if numero else ""
            importe = _num(gv(row, imp_col))
            especie = _norm_ticker(gv(row, esp_col))
            qty, price, _txt = _split_ref(gv(row, ref_col))

            # Cauciones y futuros de índice: solo su NETO cuenta (ver helpers).
            # OJO con el signo: en ESTE layout el Importe viene invertido
            # (negativo = entra plata) → el neto se niega para que un interés
            # ganado quede positivo.
            if _es_caucion(code):
                if importe is not None:
                    caucion_net -= importe
                continue
            if _es_indice(code):
                if importe is not None:
                    indice_net -= importe
                continue

            # "S.ANTERIOR": no es un movimiento, es el saldo con el que arranca
            # el archivo. Se emite como cash inicial para que la caja reconcilie
            # (sin esto el saldo del broker arranca corrido).
            if code.upper().startswith("ANT"):
                if importe:
                    result.raw_rows.append(_mk_row(
                        idx, fecha, "DEPOSITO" if importe < 0 else "RETIRO",
                        "", "", "", abs(importe), "ARS", "Saldo anterior"))
                continue

            # Patas DÓLAR del MEP (VTU$ / CPU$): el Importe en pesos viene vacío
            # → no hay cash que registrar acá. Su efecto (netear el bono) se
            # aplica en la pata PESOS, abajo.
            if code.startswith(("VTU", "CPU")):
                continue

            # Pata PESOS de un MEP: se convierte en movimiento de caja puro y el
            # bono NO entra como tenencia (netea contra la pata dólar). Solo si
            # esta fila tiene una pata dólar que la reclame — si no, es una
            # compra/venta común del bono y sigue de largo.
            _k = (especie, round(abs(qty), 6)) if (especie and qty) else None
            if _k and importe is not None:
                if code.startswith("CPRA") and mep_buy_legs.get(_k, 0) > 0:
                    mep_buy_legs[_k] -= 1
                    nt = f"Dólar MEP vía {especie}" + (f" · {notas}" if notas else "")
                    result.raw_rows.append(
                        _mk_row(idx, fecha, "RETIRO", "", "", "", abs(importe), "ARS", nt))
                    continue
                if code.startswith("VTAS") and mep_sell_legs.get(_k, 0) > 0:
                    mep_sell_legs[_k] -= 1
                    nt = f"Venta de dólar MEP vía {especie}" + (f" · {notas}" if notas else "")
                    result.raw_rows.append(
                        _mk_row(idx, fecha, "DEPOSITO", "", "", "", abs(importe), "ARS", nt))
                    continue

            # Dividendos / renta-amortización: SIN monto no hay nada que
            # registrar (el export los lista igual) → se omiten. CON monto sí
            # se cuentan: la columna Saldo los acumula, así que ignorarlos
            # descuadraba la caja — en el histórico de un usuario real eran
            # $70M de renta de bonos que quedaban afuera.
            if code.startswith(("DIV", "CDIV", "DDIV", "RTA")):
                if importe:
                    result.raw_rows.append(_mk_row(
                        idx, fecha, "DIVIDENDO" if importe < 0 else "FEE",
                        especie or "", "", "", abs(importe), "ARS", notas))
                continue

            tipo = _tipo_de(code)
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
            elif tipo == "FEE_SIGNED":
                # Retenciones, aranceles y notas de crédito/débito: gasto si sale
                # plata, ingreso si entra (signo invertido en este layout).
                tipo = "FEE" if (importe or 0) > 0 else "DIVIDENDO"
            elif tipo == "DIVIDENDO" and (importe or 0) > 0:
                tipo = "FEE"    # fila de ingreso con signo de egreso = retención

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

        # Netos de cauciones y futuros: una fila sintética cada uno. Positivo =
        # ganancia (INTERÉS), negativo = costo (FEE). Mismo criterio que la
        # Cuenta Corriente: no se crea el activo fantasma ("VARIAS", "DLR072023")
        # pero el resultado real no se pierde ni descuadra la caja.
        n_idx = len(rows) + 1
        for neto, etiqueta in ((caucion_net, "Neto de cauciones"),
                               (indice_net, "Neto de futuros de dólar (A3)")):
            if abs(neto) >= 0.01:
                result.raw_rows.append(_mk_row(
                    n_idx, last_fecha, "INTERES" if neto > 0 else "FEE",
                    "", "", "", abs(neto), "ARS", etiqueta))
                n_idx += 1

        return result

    # ── Layout 3: Histórico compacto (CSV por mail, con Dolares + Mda) ───────
    def _parse_historico_compacto(self, rows: list, norm_to_orig: dict) -> ParseResult:
        """El export que Bull Market MANDA POR MAIL cuando el portal no deja bajar
        toda la historia. Ver el docstring del módulo para la forma del archivo.

        Las tres cosas que lo hacen distinto de los otros dos layouts:
          1. La moneda de cada fila la manda `Mda`: si viene lleno, la plata REAL
             es la de `Dolares` y el `Importe` de esa fila es sólo un equivalente
             en pesos al dólar oficial (informativo, para el total del pie).
          2. No hay columna de precio: se deriva importe ÷ cantidad (ya per-1).
          3. El ticker viene pegado a la cantidad dentro de `Ref./Cantidad`.
        """
        result = ParseResult()
        f_col = _col(norm_to_orig, "f.liquid", "liquida")
        cpbt_col = _col(norm_to_orig, "cpbt")
        num_col = _col(norm_to_orig, "n.cpbt", "numero")
        imp_col = norm_to_orig.get("importe")
        dol_col = norm_to_orig.get("dolares")
        mda_col = norm_to_orig.get("mda")
        ref_col = _col(norm_to_orig, "ref.", "referencia")

        def gv(row, col) -> str:
            return _strip(row.get(col, "")) if col else ""

        def es_fecha(s: str) -> bool:
            return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", s or ""))

        def dias(a: str, b: str) -> int:
            import datetime as _dt
            try:
                pa = _dt.date(*(int(x) for x in a.split("-")))
                pb = _dt.date(*(int(x) for x in b.split("-")))
                return abs((pa - pb).days)
            except Exception:
                return 9999

        # Pass 1 — LEYENDA del pie. Acá no hay columna `Especie` donde poner el
        # código, así que la leyenda viene TODA junta en `Ref./Cantidad`, con el
        # código y la descripción separados por 2+ espacios ("CDIV   PAGO DIV").
        # La leemos para que un código que Bull Market agregue mañana se entienda
        # solo, vía _classify_comprobante, sin tocar el mapa fijo.
        legend = {}
        for row in rows:
            if es_fecha(_iso_date(gv(row, f_col))):
                continue
            m = re.match(r"^([A-Z0-9$]{2,6})\s{2,}(\S.*)$", gv(row, ref_col))
            if m:
                legend[m.group(1).upper()] = re.sub(r"\s+", " ", m.group(2)).strip()

        def _desc(code: str) -> str:
            return legend.get(code.upper(), "")

        def _es_caucion(code: str) -> bool:
            return (code[:4].lower() in ("ccdo", "vtct", "vtcc", "cpct")
                    or "caucion" in _desc(code).lower())

        def _es_indice(code: str) -> bool:
            if code[:4].lower() in ("crgi", "dbpi", "virm", "cirm", "decu"):
                return True
            d = _desc(code).lower()
            return "indice" in d or "a3 mtr" in d

        # Pass 2 — una pasada leyendo las filas que SÍ son movimientos. La fila
        # rota que trae el export (la leyenda de DTRT sale en ancho fijo, sin
        # `;`) no tiene fecha parseable → cae acá afuera sola.
        recs = []
        for idx, row in enumerate(rows, start=1):
            fecha = _iso_date(gv(row, f_col))
            if not es_fecha(fecha):
                continue
            code = gv(row, cpbt_col).upper()
            if not code:
                continue
            qty, tk, txt = _split_ref_hist(gv(row, ref_col))
            mda = gv(row, mda_col)
            recs.append({
                "idx": idx, "fecha": fecha, "code": code, "c4": code[:4].lower(),
                "numero": gv(row, num_col), "imp": _num(gv(row, imp_col)),
                "dol": _num(gv(row, dol_col)), "mda": mda, "usd": bool(mda),
                "qty": qty, "tk": tk, "txt": txt,
            })

        # Pass 3 — DÓLAR MEP. Acá, a diferencia de los otros dos layouts, las DOS
        # patas traen monto: la de pesos y la de dólares. Así que en vez de
        # perder los dólares en un RETIRO (que además infla el capital aportado),
        # las colapsamos en UNA conversión, que es lo que realmente pasó.
        #   · CPRA (bono en pesos, sale plata) + VTU$ (venta paridad) → ARS→USD
        #   · CPU$ (compra paridad, salen dólares) + VTAS (entra plata) → USD→ARS
        # Guardas para no fusionar de más: la contraparte tiene que ser de la OTRA
        # moneda (un CPU$+VTU$ del mismo papel es un round-trip en dólares, NO una
        # conversión), mismo ticker, misma cantidad, a menos de una semana, y con
        # un TC plausible. Lo que no empareja es una compra/venta común.
        mep, drop, usados = {}, set(), set()
        for u in recs:
            if u["c4"] not in ("vtu$", "cpu$") or not u["usd"] or not u["dol"]:
                continue
            if u["idx"] in usados or u["qty"] is None or not u["tk"]:
                continue
            want = "cpra" if u["c4"] == "vtu$" else "vtas"
            for p in recs:
                if p["idx"] in usados or p["idx"] == u["idx"] or p["usd"]:
                    continue
                if p["c4"] != want or not p["imp"] or p["qty"] is None:
                    continue
                if p["tk"] != u["tk"] or abs(abs(p["qty"]) - abs(u["qty"])) > 1e-6:
                    continue
                if dias(p["fecha"], u["fecha"]) > 7:
                    continue
                ars, usd = abs(p["imp"]), abs(u["dol"])
                if not (usd > 0 and 10.0 <= ars / usd <= 100000.0):
                    continue
                mep[p["idx"]] = ("FX_ARS_USD" if u["c4"] == "vtu$" else "FX_USD_ARS",
                                 ars, usd, u["tk"])
                drop.add(u["idx"])
                usados.add(p["idx"]); usados.add(u["idx"])
                break

        # Pass 4 — notas de crédito/débito en dólares emparejadas (conversiones
        # cable↔MEP): mismos dólares moviéndose entre sub-cuentas, mismo día,
        # monto igual y signo opuesto → se omiten las dos. Una nota SUELTA no se
        # toca acá: es una retención real y se cobra por signo más abajo.
        for a in recs:
            if a["c4"] not in _HIST_NOTA_USD or a["idx"] in drop or not a["dol"]:
                continue
            for b in recs:
                if (b["idx"] == a["idx"] or b["idx"] in drop
                        or b["c4"] not in _HIST_NOTA_USD or not b["dol"]):
                    continue
                if b["fecha"] == a["fecha"] and abs(a["dol"] + b["dol"]) < 0.005:
                    drop.add(a["idx"]); drop.add(b["idx"])
                    break

        # Pass 5 — SALDO ANTERIOR. Viene SIN fecha y con el texto partido entre
        # dos columnas ("S.ANT" | "ERIOR"). Sólo se emite si este archivo es el
        # PRIMERO del lote: cuando el usuario sube los dos períodos juntos (que es
        # lo que Bull Market manda), el saldo inicial del segundo ya está contado
        # como movimientos en el primero → emitirlo sería contarlo dos veces.
        min_fecha = min((r["fecha"] for r in recs), default="")
        pos_fecha = {}   # posición en `rows` → fecha del primer movimiento posterior
        ult = ""
        for i in range(len(rows) - 1, -1, -1):
            f = _iso_date(gv(rows[i], f_col))
            if es_fecha(f):
                ult = f
            pos_fecha[i] = ult
        for i, row in enumerate(rows):
            if es_fecha(_iso_date(gv(row, f_col))):
                continue
            marca = (gv(row, cpbt_col) + gv(row, num_col)).upper().replace(".", "")
            if not marca.startswith("SANT") and not marca.startswith("ANT"):
                continue
            arranca = pos_fecha.get(i, "")
            if not arranca or arranca != min_fecha:
                continue    # bloque posterior del lote → ya viene contado
            mda = gv(row, mda_col)
            v = _num(gv(row, dol_col)) if mda else _num(gv(row, imp_col))
            if not v:
                continue
            result.raw_rows.append(_mk_row(
                0, _add_days(arranca, -1), "DEPOSITO" if v < 0 else "RETIRO",
                "", "", "", abs(v), "USD" if mda else "ARS", "Saldo anterior"))

        # Pass 6 — emisión.
        caucion_net, indice_net, last_fecha = {}, {}, ""
        for r in recs:
            idx, fecha, code = r["idx"], r["fecha"], r["code"]
            last_fecha = fecha
            if idx in drop:
                continue
            notas = f"Op. {r['numero']}" if r["numero"] else ""
            moneda = "USD" if r["usd"] else "ARS"
            # La plata REAL de la fila: `Dolares` si la fila es de la sub-cuenta
            # en dólares, `Importe` si es de la de pesos. Signo INVERTIDO en las
            # dos (negativo = entra plata).
            v = r["dol"] if r["usd"] else r["imp"]

            fx = mep.get(idx)
            if fx:
                fx_op, ars, usd, tk = fx
                result.raw_rows.append(RawRow(row_index=idx, data={
                    "fecha": fecha, "tipo": fx_op, "broker": "Bull Market",
                    "activo": "", "cantidad": "", "precio": "",
                    "monto": f"{ars}", "monto_usd": f"{usd}", "tc": "",
                    "comisiones": "0", "moneda": "",
                    "notas": (f"Dólar MEP vía {tk}" if tk else "Dólar MEP")
                             + (f" · {notas}" if notas else ""),
                }))
                continue

            # Cauciones y futuros de dólar: manejo de caja / contrato, no tenencia.
            # Sólo su NETO cuenta, y por moneda (este archivo trae las dos juntas).
            if _es_caucion(code):
                if v is not None:
                    caucion_net[moneda] = caucion_net.get(moneda, 0.0) - v
                continue
            if _es_indice(code):
                if v is not None:
                    indice_net[moneda] = indice_net.get(moneda, 0.0) - v
                continue

            tipo = _HIST_CODE_MAP.get(r["c4"])
            if tipo is None:
                d = _desc(code) or r["txt"]
                tipo = _classify_comprobante(re.sub(r"\s+", " ", d).strip().lower()) if d else None
            if tipo is None:
                tipo = _MOV_CODE_MAP.get(r["c4"])
            if tipo is None:
                result.parse_errors.append(RowError(
                    idx, "Cpbt", "BULLMARKET_OP_UNKNOWN",
                    f"Código de comprobante no soportado: '{code}'.",
                ))
                continue

            # Dirección por SIGNO — reconcilia por construcción con el archivo.
            if tipo == "DIV_SIGNED":
                if not v:
                    continue        # dividendo listado sin monto: nada que registrar
                tipo = "DIVIDENDO" if v < 0 else "FEE"
            elif tipo == "FEE_SIGNED":
                if not v:
                    continue
                tipo = "FEE" if v > 0 else "DIVIDENDO"
            elif tipo in ("DEPOSITO", "RETIRO") and v is not None:
                tipo = "DEPOSITO" if v < 0 else "RETIRO"

            monto = abs(v) if v else None
            if tipo in ("COMPRA", "VENTA"):
                tk = _norm_ticker(r["tk"] or "")
                if not tk or not r["qty"] or not monto:
                    result.parse_errors.append(RowError(
                        idx, "Ref./Cantidad", "BULLMARKET_HIST_REF_ILEGIBLE",
                        f"No pudimos leer especie y cantidad de '{r['txt']}' ({code}).",
                    ))
                    continue
                q = abs(r["qty"])
                # No hay columna de precio: se deriva. Como el importe es el TOTAL
                # de la operación, el precio sale ya per-1 (los bonos de este
                # export NO necesitan el ajuste per-100 de los otros layouts).
                result.raw_rows.append(
                    _mk_row(idx, fecha, tipo, tk, q, round(monto / q, 8), monto,
                            moneda, notas))
                continue

            if not monto:
                continue
            activo = _norm_ticker(r["tk"] or "") if tipo == "DIVIDENDO" else ""
            # En los movimientos de CAJA la última columna es la leyenda del
            # comprobante ("GTOS. TRANS. TITULOS", "TRANSFERENCIA VIA MEP",
            # "CREDITO CTA. CTE."), no una especie: la guardamos. Sin esto el
            # historial mostraba sólo "Op. 257047" y se perdía el dato de que ese
            # día hubo un TRASPASO DE TÍTULOS a otro broker — la única señal de
            # que las posiciones que quedan abiertas ya no están en la cuenta
            # (el export de Bull Market es el libro de caja: no trae la salida de
            # los títulos, sólo lo que costó el trámite). No afecta el dedup: el
            # fingerprint no mira las notas.
            # Sólo la leyenda de verdad: en los dividendos esa columna trae el
            # número de especie ("8006 BYMA", "30043"), que no dice nada. Las
            # leyendas empiezan con letra ("GTOS. TRANS. TITULOS", "CREDITO CTA.
            # CTE.", "TRANSFERENCIA VIA MEP"); los números de especie, con dígito.
            _leyenda = re.sub(r"\s+", " ", (r["txt"] or "")).strip()
            if _leyenda[:1].isdigit():
                _leyenda = ""
            _notas = f"{notas} · {_leyenda}" if (notas and _leyenda) else (notas or _leyenda)
            result.raw_rows.append(
                _mk_row(idx, fecha, tipo, activo or "", "", "", monto, moneda, _notas))

        # Netos sintéticos de cauciones y futuros, uno por moneda.
        n_idx = len(rows) + 1
        for tabla, etiqueta in ((caucion_net, "Neto de cauciones"),
                                (indice_net, "Neto de futuros de dólar (A3)")):
            for moneda, neto in tabla.items():
                if abs(neto) < 0.01:
                    continue
                result.raw_rows.append(_mk_row(
                    n_idx, last_fecha, "INTERES" if neto > 0 else "FEE",
                    "", "", "", abs(neto), moneda, etiqueta))
                n_idx += 1

        return result
