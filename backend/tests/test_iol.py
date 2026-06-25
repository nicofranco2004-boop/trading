"""Tests del parser de IOL (InvertirOnline) + lectura de tablas HTML (.xls).

El export de "Movimientos Históricos" de IOL es un .xls que en realidad es una
tabla HTML. Estos tests usan HTML SINTÉTICO construido en memoria (no datos
reales de nadie) que cubre cada tipo de movimiento, los dos formatos de fecha
(DD/MM/YYYY y DD/MM/YY), los sufijos dólar/cable D/C, la keep-list de tickers
que terminan en C/D legítimamente (AMD/GOLD/INTC), el sufijo US$, la resolución
de moneda por Tipo Cuenta, montos en formato es-AR y en-US, y los skips.

Corre con: cd backend && python3 -m pytest tests/test_iol.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.excel import is_html_table, html_table_to_csv, to_csv_text, is_xlsx
from importing.parsers.registry import autodetect, get_parser
from importing.parsers.iol import IolParser
from importing.normalizer import normalize_rows
from importing import pipeline as pl
from importing import persister as ps
import main  # init_db() crea las tablas


IOL_HEADERS = [
    "Nro. de Mov.", "Nro. de Boleto", "Tipo Mov.", "Concert.", "Liquid.", "Est",
    "Cant. titulos", "Precio", "Comis.", "Iva Com.", "Otros Imp.", "Monto",
    "Observaciones", "Tipo Cuenta",
]


def _cell(v):
    return f"      <td>{v}</td>"


def _html(rows, headers=IOL_HEADERS):
    """Construye una tabla HTML estilo IOL a partir de listas de celdas."""
    th = "\n".join(f"      <th>{h}</th>" for h in headers)
    body = []
    for r in rows:
        tds = "\n".join(_cell(c) for c in r)
        body.append(f"    <tr>\n{tds}\n    </tr>")
    body_html = "\n".join(body)
    return (
        '<table border="1" class="dataframe">\n'
        f"  <thead>\n    <tr>\n{th}\n    </tr>\n  </thead>\n"
        f"  <tbody>\n{body_html}\n  </tbody>\n</table>\n"
    ).encode("utf-8")


def _row(tipo_mov, concert="05/01/2025", cant="", precio="", comis="0",
         iva="0", otros="0", monto="", cuenta="Inversion Argentina Pesos",
         mov="1", boleto="1", liquid="07/01/2025", est="Terminada"):
    return [mov, boleto, tipo_mov, concert, liquid, est, cant, precio,
            comis, iva, otros, monto, "", cuenta]


def _parse(rows):
    content = to_csv_text(_html(rows))
    return IolParser().parse(content)


def _by_index(result):
    return {r.row_index: r.data for r in result.raw_rows}


class TestHtmlReader(unittest.TestCase):
    def test_detects_html_table(self):
        self.assertTrue(is_html_table(_html([_row("Compra(GGAL)", cant="1", precio="10")])))

    def test_rejects_plain_csv(self):
        self.assertFalse(is_html_table(b"fecha,tipo,broker\n2024-01-01,COMPRA,Cocos\n"))

    def test_rejects_xlsx_bytes(self):
        # Un .xlsx (zip) no debe confundirse con HTML.
        self.assertFalse(is_html_table(b"PK\x03\x04rest-of-zip"))
        self.assertTrue(is_xlsx(b"PK\x03\x04rest-of-zip"))

    def test_html_to_csv_roundtrip(self):
        csv_text = html_table_to_csv(_html([
            _row("Compra(GGAL)", cant="100", precio="1500"),
            _row("Venta(GGAL)", cant="50", precio="1900"),
        ]))
        lines = csv_text.splitlines()
        self.assertEqual(len(lines), 3)  # header + 2 filas
        self.assertIn("Tipo Mov.", lines[0])
        self.assertIn("Compra(GGAL)", lines[1])

    def test_to_csv_text_routes_html(self):
        csv_text = to_csv_text(_html([_row("Compra(GGAL)", cant="1", precio="10")]))
        self.assertIn("Tipo Mov.", csv_text.splitlines()[0])

    def test_utf8_accents_preserved(self):
        # 'Depósito' / 'Crédito' deben decodificar bien (el export es UTF-8).
        csv_text = to_csv_text(_html([
            _row("Depósito de Fondos - Transferencia electrónica - BANCO X", monto="500000"),
            _row("Crédito", monto="12.50", cuenta="Inversion Argentina Dolares"),
        ]))
        self.assertIn("Depósito", csv_text)
        self.assertIn("Crédito", csv_text)

    def test_rejects_csv_with_embedded_table_markup(self):
        # Un CSV legítimo con '<table>' dentro de una celda NO debe enrutarse al
        # path HTML (no arranca con '<').
        csv = b'fecha,notas\r\n2024-01-01,"<table><tr><td>ver adjunto</td></tr></table>"\r\n'
        self.assertFalse(is_html_table(csv))
        # to_csv_text lo trata como CSV (devuelve el texto tal cual).
        self.assertIn("ver adjunto", to_csv_text(csv))

    def test_leading_whitespace_and_bom_ok(self):
        # HTML real con whitespace/BOM antes del <table> sí se detecta.
        b = b"\xef\xbb\xbf\n  " + _html([_row("Compra(GGAL)", cant="1", precio="10")])
        self.assertTrue(is_html_table(b))

    def test_nested_table_does_not_corrupt_outer_row(self):
        # Una tabla anidada en una celda no debe pisar ni desalinear la fila exterior.
        html = (
            '<table class="dataframe"><thead><tr><th>A</th><th>B</th></tr></thead>'
            '<tbody><tr><td>1</td><td><table><tr><td>x</td></tr></table>2</td></tr></tbody>'
            '</table>'
        ).encode("utf-8")
        lines = html_table_to_csv(html).splitlines()
        self.assertEqual(lines[0], "A,B")
        self.assertEqual(lines[1], "1,2")  # 'x' (anidada) descartada, '2' preservado

    def test_truncated_html_raises(self):
        # Archivo cortado a la mitad (sin cerrar </tr></table>) → error claro.
        truncated = (
            '<table><thead><tr><th>A</th></tr></thead><tbody>'
            '<tr><td>1</td></tr><tr><td>2'   # fila 2 sin cerrar
        ).encode("utf-8")
        with self.assertRaises(ValueError):
            html_table_to_csv(truncated)


class TestAutodetect(unittest.TestCase):
    def test_autodetect_picks_iol(self):
        content = to_csv_text(_html([_row("Compra(GGAL)", cant="1", precio="10")]))
        headers = content.splitlines()[0].split(",")
        p = autodetect(headers)
        self.assertIsNotNone(p)
        self.assertEqual(p.format_id, "iol")

    def test_get_parser_iol(self):
        self.assertIsInstance(get_parser("iol"), IolParser)


class TestOpMapping(unittest.TestCase):
    def test_op_types(self):
        res = _parse([
            _row("Compra(GGAL)", cant="100", precio="1500"),
            _row("Venta(GGAL)", cant="50", precio="1900"),
            _row("Pago de Dividendos(EDN)", monto="5230"),
            _row("Pago de Renta(AL30)", monto="1000"),
            _row("Pago de Amortización(AL30)", monto="2000"),
            _row("Crédito", monto="12.50", cuenta="Inversion Argentina Dolares"),
            _row("Depósito de Fondos - Transferencia electrónica - BANCO X", monto="500000"),
            _row("Extracción de Fondos - Transferencia Electrónica - BANCO Y", monto="300000"),
            _row("Suscripción FCI(PRREMIB)", cant="100", precio="888.63"),
            _row("Rescate FCI(PRREMIB)", cant="100", precio="900.00"),
        ])
        tipos = [r.data["tipo"] for r in res.raw_rows]
        self.assertEqual(tipos, [
            "COMPRA", "VENTA", "DIVIDENDO", "DIVIDENDO", "DIVIDENDO",
            "INTERES", "DEPOSITO", "RETIRO", "COMPRA", "VENTA",
        ])
        self.assertEqual(len(res.parse_errors), 0)

    def test_title_transfer_skipped(self):
        res = _parse([_row("Transferencia de Titulos IN - (SUPV)", cant="10")])
        self.assertEqual(len(res.raw_rows), 0)
        self.assertEqual(res.parse_errors[0].code, "IOL_TITLE_TRANSFER")

    def test_unknown_op_reported(self):
        res = _parse([_row("Movimiento Raro(XYZ)", monto="100")])
        self.assertEqual(len(res.raw_rows), 0)
        self.assertEqual(res.parse_errors[0].code, "IOL_OP_UNKNOWN")

    def test_empty_tipo_skipped_silently(self):
        res = _parse([_row("", monto="100")])
        self.assertEqual(len(res.raw_rows), 0)
        self.assertEqual(len(res.parse_errors), 0)


class TestTicker(unittest.TestCase):
    def _ticker(self, tipo_mov, **kw):
        res = _parse([_row(tipo_mov, cant="1", precio="10", **kw)])
        return res.raw_rows[0].data["activo"]

    def test_strips_dolar_cable_suffix(self):
        self.assertEqual(self._ticker("Compra(GGALD)"), "GGAL")
        self.assertEqual(self._ticker("Compra(GGALC)"), "GGAL")
        self.assertEqual(self._ticker("Venta(AL30D)"), "AL30")
        self.assertEqual(self._ticker("Venta(AL30C)"), "AL30")
        self.assertEqual(self._ticker("Compra(NUD)"), "NU")

    def test_keeps_known_cd_tickers(self):
        # CEDEARs/cripto que terminan en C/D de forma legítima — NO se tocan.
        self.assertEqual(self._ticker("Compra(AMD)"), "AMD")
        self.assertEqual(self._ticker("Compra(GOLD)"), "GOLD")
        self.assertEqual(self._ticker("Compra(INTC)"), "INTC")
        self.assertEqual(self._ticker("Compra(YPFD)"), "YPFD")

    def test_strips_usd_suffix(self):
        res = _parse([_row("Pago de Dividendos(EDN US$)", monto="100",
                            cuenta="Inversion Argentina Dolares")])
        self.assertEqual(res.raw_rows[0].data["activo"], "EDN")

    def test_fci_underscore_suffix(self):
        # FCI_C / FCI_D → FCI_ ; FCI_A / FCI_B se mantienen.
        self.assertEqual(self._ticker("Rescate FCI(FCI_C)"), "FCI_")
        self.assertEqual(self._ticker("Rescate FCI(FCI_D)"), "FCI_")
        self.assertEqual(self._ticker("Rescate FCI(FCI_A)"), "FCI_A")
        self.assertEqual(self._ticker("Rescate FCI(FCI_B)"), "FCI_B")

    def test_cash_ops_have_no_ticker(self):
        res = _parse([
            _row("Depósito de Fondos - BANCO X", monto="500000"),
            _row("Crédito", monto="12"),
        ])
        self.assertEqual(res.raw_rows[0].data["activo"], "")
        self.assertEqual(res.raw_rows[1].data["activo"], "")


class TestCurrency(unittest.TestCase):
    def _cur(self, **kw):
        return _parse([_row("Compra(GGAL)", cant="1", precio="10", **kw)]).raw_rows[0].data["moneda"]

    def test_pesos_account_is_ars(self):
        self.assertEqual(self._cur(cuenta="Inversion Argentina Pesos"), "ARS")

    def test_dolares_account_is_usd(self):
        self.assertEqual(self._cur(cuenta="Inversion Argentina Dolares"), "USD")

    def test_usd_suffix_forces_usd(self):
        res = _parse([_row("Pago de Dividendos(EDN US$)", monto="100",
                            cuenta="Inversion Argentina Pesos")])  # cuenta dice pesos…
        self.assertEqual(res.raw_rows[0].data["moneda"], "USD")    # …pero el US$ gana

    def test_unknown_account_defaults_ars(self):
        self.assertEqual(self._cur(cuenta="Cuenta Anonimizada"), "ARS")


class TestDates(unittest.TestCase):
    def test_four_digit_year(self):
        res = _parse([_row("Compra(GGAL)", concert="05/01/2025", cant="1", precio="10")])
        self.assertEqual(res.raw_rows[0].data["fecha"], "2025-01-05")

    def test_two_digit_year(self):
        res = _parse([_row("Compra(GGAL)", concert="12/06/26", cant="1", precio="10")])
        self.assertEqual(res.raw_rows[0].data["fecha"], "2026-06-12")


class TestAmountRouting(unittest.TestCase):
    def test_trade_uses_monto_as_cash_not_qty_price(self):
        # El cash real del trade es Monto, NO cantidad × Precio. Para un bono que
        # cotiza "por 100 nominales", cantidad × Precio se infla ~100×; el parser
        # debe usar |Monto| y derivar precio = |Monto|/qty.
        rows = _parse([_row("Venta(AL30)", cant="231", precio="91370", monto="-209.988,27")])
        d = rows.raw_rows[0].data
        self.assertAlmostEqual(float(d["monto"]), 209988.27, places=2)        # NO 231×91370=21M
        self.assertAlmostEqual(float(d["precio"]), 209988.27 / 231, places=4)
        self.assertEqual(d["comisiones"], "0")                                # Monto ya es neto
        norm, errs = normalize_rows(rows.raw_rows)
        self.assertEqual(len(errs), 0)
        self.assertAlmostEqual(norm[0].gross_amount, 209988.27, places=2)

    def test_dolar_mep_leg_uses_monto(self):
        # Pata dólar-MEP: Precio en otra escala (cantidad × Precio se va a millones),
        # pero el cash real es Monto. Caso real: Venta(NOW) q=57 p=8747193 Monto=49.527,18.
        rows = _parse([_row("Venta(NOW)", cant="57", precio="8747193",
                            monto="49.527,18", cuenta="Inversion Argentina Dolares")])
        norm, _ = normalize_rows(rows.raw_rows)
        self.assertAlmostEqual(norm[0].gross_amount, 49527.18, places=2)      # NO 498 millones
        self.assertEqual(norm[0].currency, "USD")

    def test_trade_falls_back_to_qty_price_without_monto(self):
        # Si no hay Monto usable, cae a cantidad × Precio (comportamiento viejo).
        rows = _parse([_row("Compra(GGAL)", cant="100", precio="1500", monto="")])
        norm, _ = normalize_rows(rows.raw_rows)
        self.assertAlmostEqual(norm[0].gross_amount, 150000.0, places=2)

    def test_cash_uses_monto(self):
        d = _parse([_row("Depósito de Fondos - BANCO X", monto="500000")]).raw_rows[0].data
        self.assertAlmostEqual(float(d["monto"]), 500000.0)
        self.assertEqual(d["cantidad"], "")
        self.assertEqual(d["precio"], "")
        self.assertEqual(d["comisiones"], "0")

    def test_withdrawal_negative_monto_abs(self):
        # Extracción: IOL pone Monto negativo; la dirección la da el tipo RETIRO.
        rows = _parse([_row("Extracción de Fondos - BANCO Y", monto="-21.476,30")])
        norm, errs = normalize_rows(rows.raw_rows)
        self.assertEqual(len(errs), 0)
        self.assertEqual(norm[0].operation_type, "WITHDRAW")
        self.assertAlmostEqual(norm[0].gross_amount, 21476.30, places=2)

    def test_fees_summed(self):
        d = _parse([_row("Compra(GGAL)", cant="100", precio="1500",
                          comis="150.05", iva="31.51", otros="5.00")]).raw_rows[0].data
        self.assertEqual(d["comisiones"], "186.56")

    def test_bond_nominal_row_skipped(self):
        # Evento de bono: fila de cash (Monto>0) + fila nominal (Cant>0, Monto vacío).
        # La nominal se saltea sin error; la de cash entra.
        res = _parse([
            _row("Pago de Amortización(AL30)", monto="68096.69"),       # cash
            _row("Pago de Amortización(AL30)", cant="2.82", monto=""),  # nominal → skip
        ])
        self.assertEqual(len(res.raw_rows), 1)
        self.assertEqual(len(res.parse_errors), 0)
        self.assertEqual(res.raw_rows[0].data["monto"], "68096.69")

    def test_zero_and_empty_monto_dividend_skipped(self):
        res = _parse([
            _row("Pago de Dividendos(EDN)", monto="0"),   # cero cash → skip
            _row("Pago de Renta(LEDE)", monto=""),         # vacío → skip
            _row("Crédito", monto=""),                     # interés sin monto → skip
        ])
        self.assertEqual(len(res.raw_rows), 0)
        self.assertEqual(len(res.parse_errors), 0)


class TestNumberFormats(unittest.TestCase):
    def test_ar_comma_decimal_normalizes(self):
        # Formato es-AR ('1.234,56'): el normalizer debe armar el bruto bien.
        res = _parse([_row("Compra(GGAL)", cant="100", precio="1.500,50",
                            comis="150,05", iva="31,51", otros="5,00")])
        self.assertEqual(res.raw_rows[0].data["comisiones"], "186.56")
        norm, errs = normalize_rows(res.raw_rows)
        self.assertEqual(len(errs), 0)
        self.assertAlmostEqual(norm[0].gross_amount, 100 * 1500.50, places=2)

    def test_us_point_decimal_normalizes(self):
        res = _parse([_row("Compra(GGAL)", cant="100", precio="1500.50")])
        norm, errs = normalize_rows(res.raw_rows)
        self.assertEqual(len(errs), 0)
        self.assertAlmostEqual(norm[0].gross_amount, 100 * 1500.50, places=2)


class TestEndToEnd(unittest.TestCase):
    def test_full_mix_normalizes_clean(self):
        rows = [
            _row("Compra(NVDA)", cant="433", precio="2077.43", comis="5764.10",
                 iva="1210.46", otros="104.08"),
            _row("Venta(GGALD)", cant="100", precio="8.20",
                 cuenta="Inversion Argentina Dolares"),
            _row("Pago de Dividendos(EDN)", monto="5230"),
            _row("Pago de Dividendos(EDN US$)", monto="208.32",
                 cuenta="Inversion Argentina Dolares"),
            _row("Crédito", monto="12.50", cuenta="Inversion Argentina Dolares"),
            _row("Depósito de Fondos - BANCO X", monto="500000"),
            _row("Extracción de Fondos - BANCO Y", monto="300000"),
        ]
        res = _parse(rows)
        self.assertEqual(len(res.parse_errors), 0)
        self.assertEqual(len(res.raw_rows), 7)
        norm, errs = normalize_rows(res.raw_rows)
        self.assertEqual(len(errs), 0)
        self.assertEqual(len(norm), 7)
        # Broker hardcodeado a IOL en todas.
        self.assertTrue(all(t.broker == "IOL" for t in norm))

    def test_negative_dividend_handled(self):
        # Dividendo con Monto negativo (retención): el normalizer no debe romper.
        res = _parse([_row("Pago de Dividendos(YPFD)", monto="-259",
                            cuenta="Inversion Argentina Pesos")])
        norm, errs = normalize_rows(res.raw_rows)
        self.assertEqual(len(errs), 0)
        self.assertEqual(len(norm), 1)


def _helpers():
    h = main._ImportHelpers()
    h._adjust_broker_cash = main._adjust_broker_cash
    h._adjust_cash = main._adjust_cash
    h._update_monthly_pnl_realized = main._update_monthly_pnl_realized
    h._update_monthly_flow = main._update_monthly_flow
    h._repair_monthly_chain = main._repair_monthly_chain
    h._ensure_usd_sibling = main._ensure_usd_sibling
    return h


class TestIolImportE2E(unittest.TestCase):
    """End-to-end por la DB real: HTML (.xls) → preview → persist → revert.
    Valida que el reader HTML está cableado en run_preview y que el batch de
    IOL se persiste y se revierte sin dejar datos colgados."""

    def setUp(self):
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("iol_e2e@rendi.test", "x"),
        )
        self.uid = cur.lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "IOL", "ARS"))
        conn.commit()
        conn.close()

    def _xls(self):
        # Secuencia coherente en pesos: depósito → compra → venta parcial → dividendo.
        return _html([
            _row("Depósito de Fondos - Transferencia electrónica - BANCO X",
                 concert="02/01/2024", monto="1000000"),
            _row("Compra(GGAL)", concert="03/01/2024", cant="100", precio="5000",
                 comis="500", iva="105"),
            _row("Venta(GGAL)", concert="04/01/2024", cant="40", precio="6000",
                 comis="300", iva="63"),
            _row("Pago de Dividendos(GGAL)", concert="05/01/2024", monto="2500"),
        ])

    def test_preview_persist_revert(self):
        conn = main.get_db()
        try:
            with conn:
                payload = pl.run_preview(
                    conn, uid=self.uid, file_bytes=self._xls(),
                    file_name="MovimientosHistoricos.xls",
                    broker_hint="IOL", parser_format="iol",
                )
            self.assertNotIn("error", payload, payload.get("error"))
            session_id = payload["session_id"]
            self.assertEqual(payload["summary"]["valid_rows"], 4)

            with conn:
                txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=session_id)
                ps.persist_batch(conn, uid=self.uid, batch_id=session_id, txs=txs,
                                 raw_row_ids_by_index=raw, helpers=_helpers())

            # Quedó una posición GGAL con 60 títulos (100 comprados − 40 vendidos).
            pos = conn.execute(
                "SELECT quantity FROM positions WHERE user_id=? AND broker='IOL' "
                "AND asset='GGAL' AND is_cash=0", (self.uid,),
            ).fetchone()
            self.assertIsNotNone(pos)
            self.assertAlmostEqual(pos["quantity"], 60.0, places=2)
            # Se registró al menos una operación (la venta).
            n_ops = conn.execute(
                "SELECT COUNT(*) c FROM operations WHERE user_id=?", (self.uid,),
            ).fetchone()["c"]
            self.assertGreaterEqual(n_ops, 1)

            # Revert nuclear (el batch tiene una VENTA) → no debe quedar nada.
            with conn:
                ps.revert_batch(conn, uid=self.uid, batch_id=session_id,
                                helpers=_helpers(), nuclear=True)
            remaining_pos = conn.execute(
                "SELECT COUNT(*) c FROM positions WHERE user_id=? AND is_cash=0",
                (self.uid,),
            ).fetchone()["c"]
            remaining_ops = conn.execute(
                "SELECT COUNT(*) c FROM operations WHERE user_id=?", (self.uid,),
            ).fetchone()["c"]
            self.assertEqual(remaining_pos, 0, "quedaron posiciones tras el revert")
            self.assertEqual(remaining_ops, 0, "quedaron operaciones tras el revert")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
