"""BalanzMovimientosParser — el export de Movimientos de Balanz (el libro de caja
que RECONCILIA). Lo importante: la suma del cash emitido = la suma de Importe por
moneda (el parser no inventa ni pierde plata). Cubre los casos finos: caución
(APCOLCON contado / APCOLFUT futuro), la pata fee precio=-1 de un trade, depósito/
retiro, dividendo con retención, FCI y lote gratis."""
import unittest

from importing.parsers.balanz_movimientos import BalanzMovimientosParser
from importing.parsers.registry import get_parser, autodetect

HDR = "Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,Liquidacion,Moneda,Importe"
ROWS = [
    "Recibo de Cobro / 8801586,,,2025-10-22,0,-1,2025-10-22,Pesos,1000000",          # +1.000.000 ARS depósito
    "Boleto / 111 / COMPRA / 0 / GD46 / $,AL30,Bonos,2025-10-23,500,1000,2025-10-23,Pesos,-500000",  # -500.000 ARS compra
    "Boleto / 112 / COMPRA / 0 / GD46 / $,AL30,Bonos,2025-10-23,500,-1,2025-10-23,Pesos,-50",        # -50 ARS comisión (precio=-1)
    "Boleto / 113 / VENTA / 0 / GD46 / U$S,AL35,Bonos,2025-11-02,800,0.75,2025-11-02,Dólares,600",   # +600 USD venta
    "Boleto / 200 / APCOLCON / 0 / $,,,2025-11-05,0,-1,2025-11-05,Pesos,-200000",     # -200.000 ARS caución contado
    "Boleto / 201 / APCOLFUT / 1 / $,,,2025-11-12,0,-1,2025-11-12,Pesos,205000",      # +205.000 ARS caución término
    "Dividendo en efectivo / XLE,XLE,Cedears,2025-12-15,0,-1,2025-12-15,Dólares,10",  # +10 USD dividendo
    "Dividendo en efectivo / XLE,XLE,Cedears,2025-12-15,0,-1,2025-12-15,Pesos,-3",    # -3 ARS retención
    "Comprobante de Pago / 999,,,2026-01-10,0,-1,2026-01-10,Pesos,-100000",           # -100.000 ARS retiro
    "Cargo por Descubierto del 30/09/2025,,,2026-01-11,0,-1,2026-01-11,Pesos,-50",    # -50 ARS fee
    "Liquidación de Suscripción / 7 / FONDO,BAHUSD,Fondos,2026-02-01,740,1.35,2026-02-01,Dólares,-1000",  # -1000 USD FCI
    "Dividendo en acciones / IJH,IJH,Cedears,2026-03-01,5,-1,2026-03-01,Pesos,0",     # lote gratis qty 5
]


def _csv():
    return (HDR + "\n" + "\n".join(ROWS) + "\n")


OUT = {"COMPRA", "RETIRO", "FEE", "IMPUESTO"}   # IMPUESTO = retención (debita cash, como FEE)
IN = {"VENTA", "DEPOSITO", "DIVIDENDO", "INTERES"}


class BalanzMovimientosTest(unittest.TestCase):
    def setUp(self):
        self.res = BalanzMovimientosParser().parse(_csv())
        self.by = {}  # row_index → data
        for rr in self.res.raw_rows:
            self.by.setdefault(rr.data["tipo"], []).append(rr.data)

    def test_no_parse_errors(self):
        self.assertEqual(self.res.parse_errors, [])

    def test_reconciles_cash_per_currency(self):
        # Σ cash firmado (por op) = Σ Importe del archivo, por moneda.
        emit = {"ARS": 0.0, "USD": 0.0}
        for rr in self.res.raw_rows:
            d = rr.data
            m = float(d.get("monto") or 0)
            c = d["moneda"]
            emit[c] += (-m if d["tipo"] in OUT else (m if d["tipo"] in IN else 0))
        # Esperado, a mano:
        #   ARS: +1.000.000 -500.000 -50 -200.000 +205.000 -3 -100.000 -50 = 404.897
        #   USD: +600 +10 -1000 = -390
        self.assertAlmostEqual(emit["ARS"], 404897.0, places=2)
        self.assertAlmostEqual(emit["USD"], -390.0, places=2)

    def test_caucion_signs(self):
        # APCOLCON (sale) → RETIRO ; APCOLFUT (entra) → DEPOSITO
        retiros = [d["notas"] for d in self.by.get("RETIRO", [])]
        depos = [d["notas"] for d in self.by.get("DEPOSITO", [])]
        self.assertTrue(any("APCOLCON" in n for n in retiros))
        self.assertTrue(any("APCOLFUT" in n for n in depos))

    def test_trade_fee_is_fee_not_position(self):
        # la pata precio=-1 de un Boleto COMPRA es FEE (no crea posición)
        fees = self.by.get("FEE", [])
        self.assertTrue(any("Boleto / 112" in d["notas"] for d in fees))
        # la COMPRA real sí lleva cantidad+precio
        compra = [d for d in self.by.get("COMPRA", []) if "Boleto / 111" in d["notas"]][0]
        self.assertEqual(compra["activo"], "AL30")
        self.assertEqual(float(compra["cantidad"]), 500.0)

    def test_free_lot(self):
        compras = self.by.get("COMPRA", [])
        free = [d for d in compras if d.get("activo") == "IJH"][0]
        self.assertEqual(float(free["precio"]), 0.0)
        self.assertEqual(float(free["cantidad"]), 5.0)

    def test_transferencia_externa(self):
        # Título transferido desde otro broker: ticker+precio (costo), Importe=0.
        # → COMPRA (posición con costo) + DEPOSITO (valor que entra) → cash neto 0.
        csv = HDR + "\n" + "Transferencia Externa (Crédito) / AGRO,AGRO,Acciones,2025-10-01,100,36,2025-10-01,,0\n"
        res = BalanzMovimientosParser().parse(csv)
        self.assertEqual(res.parse_errors, [])
        tipos = [rr.data["tipo"] for rr in res.raw_rows]
        self.assertIn("COMPRA", tipos)
        self.assertIn("DEPOSITO", tipos)
        compra = [rr.data for rr in res.raw_rows if rr.data["tipo"] == "COMPRA"][0]
        self.assertEqual(compra["activo"], "AGRO")
        self.assertEqual(float(compra["monto"]), 3600.0)  # 100 × 36
        cash = sum((-float(rr.data["monto"]) if rr.data["tipo"] == "COMPRA" else float(rr.data["monto"]))
                   for rr in res.raw_rows if rr.data["tipo"] in ("COMPRA", "DEPOSITO"))
        self.assertAlmostEqual(cash, 0.0, places=2)

    def test_unknown_desc_is_flagged_not_swallowed(self):
        # Una descripción que no conocemos NO se traga en silencio → RowError
        # (aparece vía el Import Guardian) en vez de mis-importarse como cash.
        csv = HDR + "\n" + "Algo Totalmente Nuevo / 123,,,2025-10-01,0,-1,2025-10-01,Pesos,-500\n"
        res = BalanzMovimientosParser().parse(csv)
        self.assertEqual(len(res.raw_rows), 0)
        self.assertTrue(any(e.code == "BALANZ_MOV_DESC_DESCONOCIDA" for e in res.parse_errors))

    def test_detection(self):
        p = BalanzMovimientosParser()
        self.assertTrue(p.can_handle(HDR.split(",")))
        # NO debe matchear headers de Órdenes ni de Resultados de Balanz
        ordenes = ["Operacion", "Estado", "id Orden", "Ticker", "Moneda", "Fecha", "Cantidad", "Precio", "Monto"]
        resultados = ["Cantidad", "Descripcion", "Fecha", "Gastos", "Ticker", "Tipo", "Tipo Movimiento", "Precio Compra"]
        self.assertFalse(p.can_handle(ordenes))
        self.assertFalse(p.can_handle(resultados))
        # y el registry lo encuentra
        self.assertIsNotNone(get_parser("balanz_movimientos"))


class BalanzMovimientosNuevosTiposTest(unittest.TestCase):
    """Tipos que aparecieron en un export real más amplio (Actividad → Movimientos
    de una cuenta de años): acciones societarias (split, cambio de ratio CEDEAR,
    rescate parcial de bono), operación a plazo/diferida, cheque, intereses
    devengados, prima/rescate de bono, y clases de FCI con espacio en el ticker."""

    def _parse(self, *rows):
        return BalanzMovimientosParser().parse(HDR + "\n" + "\n".join(rows) + "\n")

    def _by_tipo(self, res):
        by = {}
        for rr in res.raw_rows:
            by.setdefault(rr.data["tipo"], []).append(rr.data)
        return by

    def test_corporate_split_y_cambio_ratio_dan_lote_gratis(self):
        # Split (+201) y cambio de ratio CEDEAR (+27): suman nominales SIN cash
        # (importe 0) → COMPRA precio 0. No deben quedar flagged ni mover caja.
        res = self._parse(
            "Split / GGAL,GGALX,Acciones,2025-10-01,201,-1,2025-10-01,,0",
            "Acreditación cambio de ratio / NVDA,NVDA,Cedears,2025-10-02,27,-1,2025-10-02,,0",
        )
        self.assertEqual(res.parse_errors, [])
        by = self._by_tipo(res)
        compras = {d["activo"]: d for d in by.get("COMPRA", [])}
        self.assertEqual(float(compras["GGALX"]["precio"]), 0.0)
        self.assertEqual(float(compras["GGALX"]["cantidad"]), 201.0)
        self.assertEqual(float(compras["NVDA"]["cantidad"]), 27.0)
        # cero cash emitido (todas precio 0, monto 0)
        self.assertEqual(sum(float(rr.data.get("monto") or 0) for rr in res.raw_rows), 0.0)

    def test_rescate_parcial_baja_nominal_sin_cash(self):
        # Rescate parcial de bono: cantidad negativa, importe 0 → VENTA precio 0
        # (baja el nominal). El cash del rescate viene en una fila "Rescate" aparte.
        res = self._parse(
            "Rescate parcial / TLC1O,TLC1O,Corporativos,2025-10-03,-427,-1,2025-10-03,,0")
        self.assertEqual(res.parse_errors, [])
        venta = self._by_tipo(res)["VENTA"][0]
        self.assertEqual(venta["activo"], "TLC1O")
        self.assertEqual(float(venta["precio"]), 0.0)
        self.assertEqual(float(venta["cantidad"]), 427.0)

    def test_amortizacion_total_baja_nominal_a_cero(self):
        # Caso real (Fede/SXC2O): ON transferida (+4000) que se amortiza TOTAL. La
        # "Renta y Amortización" viene en 2 patas con cantidad=-4000: el cobro del
        # principal (USD, entra) y la retención (ARS, sale). Antes el parser ignoraba
        # la cantidad → quedaban 4000 unidades fantasma (a precio ×100 = +US$385k).
        # Ahora: el cobro cierra el nominal como VENTA a su valor de rescate (proceeds),
        # la retención va como FEE, y se cierra UNA sola vez (no oversell).
        res = self._parse(
            "Transferencia Externa (Crédito) / ON,SXC2O,Corporativos,2025-11-27,4000,1495.1,2025-11-27,,0",
            "Renta y Amortización / SXC2O,SXC2O,Corporativos,2026-06-01,-4000,-1,2026-06-01,Pesos,-650.05",
            "Renta y Amortización / SXC2O,SXC2O,Corporativos,2026-06-01,-4000,-1,2026-06-01,Dólares,4129.43")
        self.assertEqual(res.parse_errors, [])
        by = self._by_tipo(res)
        ventas = [d for d in by.get("VENTA", []) if d["activo"] == "SXC2O"]
        compras = [d for d in by.get("COMPRA", []) if d["activo"] == "SXC2O"]
        # 1 sola VENTA (las 2 patas comparten cantidad → dedup), a proceeds USD (no precio 0).
        self.assertEqual(len(ventas), 1)
        self.assertEqual(ventas[0]["moneda"], "USD")
        self.assertEqual(float(ventas[0]["monto"]), 4129.43)
        self.assertNotIn("precio", ventas[0])  # sin precio → el normalizer deriva monto/cant (no precio 0)
        # nominal neto = +4000 -4000 = 0 → la posición desaparece (sin fantasma).
        net = sum(float(d["cantidad"]) for d in compras) - sum(float(d["cantidad"]) for d in ventas)
        self.assertEqual(net, 0.0)
        # la retención ARS quedó como IMPUESTO (no comisión, no segunda VENTA).
        self.assertTrue(any(float(d["monto"]) == 650.05 for d in by.get("IMPUESTO", [])))

    def test_cupon_puro_no_baja_nominal(self):
        # "Renta" con cantidad=0 (cupón puro, sin amortización) NO debe vender nominal.
        res = self._parse(
            "Transferencia Externa (Crédito) / ON,CS48O,Corporativos,2025-11-27,4000,1560,2025-11-27,,0",
            "Renta / CS48O,CS48O,Corporativos,2026-01-12,0,-1,2026-01-12,Dólares,160.75")
        self.assertEqual(res.parse_errors, [])
        by = self._by_tipo(res)
        self.assertEqual(len([d for d in by.get("VENTA", []) if d["activo"] == "CS48O"]), 0)
        self.assertTrue(any(float(d["monto"]) == 160.75 for d in by.get("DIVIDENDO", [])))

    def test_operacion_diferida_netea_a_cero(self):
        # El par "Operación Diferida" + "Liquidación de Operación Diferida" trae
        # legs opuestos (cantidad y cash) → netea a 0 en posición y caja. Sin
        # precio unitario: el tipo lo decide el SIGNO de Importe.
        res = self._parse(
            "Operación Diferida / Boleto : 6123382,VIST,Cedears,2025-10-04,-35,-1,2025-10-04,Pesos,693000",
            "Liquidación de Operación Diferida / Boleto : 6123382,VIST,Cedears,2025-10-05,35,-1,2025-10-05,Pesos,-693000",
        )
        self.assertEqual(res.parse_errors, [])
        net_qty = sum((float(rr.data["cantidad"]) if rr.data["tipo"] == "VENTA"
                       else -float(rr.data["cantidad"]))
                      for rr in res.raw_rows)  # VENTA suma, COMPRA resta (signo de tenencia)
        net_cash = sum((float(rr.data["monto"]) if rr.data["tipo"] == "VENTA"
                        else -float(rr.data["monto"])) for rr in res.raw_rows)
        self.assertAlmostEqual(net_qty, 0.0, places=6)
        self.assertAlmostEqual(net_cash, 0.0, places=6)

    def test_cheque_intereses_y_rescate_son_cash_in(self):
        # Acreditación de Cheque → depósito ; Intereses devengados / Rescate (cash
        # de bono) / Prima por rescate → ingreso. Todos cash IN, reconcilian.
        res = self._parse(
            "Acreditación de Cheque #150 / BANCO,,,2025-10-06,0,-1,2025-10-06,Pesos,1580563.6",
            "Intereses devengados / TLC1O,TLC1O,Corporativos,2025-10-07,0,-1,2025-10-07,Dólares,14.38",
            "Rescate / TLC1O,TLC1O,Corporativos,2025-10-08,0,-1,2025-10-08,Dólares,432.89",
            "Prima por rescate / TLC1O,TLC1O,Corporativos,2025-10-09,0,-1,2025-10-09,Dólares,2.32",
        )
        self.assertEqual(res.parse_errors, [])
        by = self._by_tipo(res)
        self.assertTrue(any("Cheque" in d["notas"] for d in by.get("DEPOSITO", [])))
        ingresos = by.get("DIVIDENDO", [])
        self.assertAlmostEqual(sum(float(d["monto"]) for d in ingresos), 14.38 + 432.89 + 2.32, places=2)

    def test_ticker_con_espacio_se_normaliza(self):
        # Clases de FCI vienen como "INSTITU A" y fragmentaban contra "INSTITUA".
        res = self._parse(
            "Liquidación de Suscripción / 7 / FCI,INSTITU A,Fondos,2025-10-10,100,1.35,2025-10-10,Pesos,-135")
        self.assertEqual(res.parse_errors, [])
        self.assertEqual(res.raw_rows[0].data["activo"], "INSTITUA")


class BalanzFCITest(unittest.TestCase):
    """FCI (fondos): Balanz INVIERTE el signo del Importe (Suscripción=compra,
    Rescate=venta) y el sweep money-market duplica con una pata espejo
    'desde/a Balanz'. Verifica dirección por nombre + dedup del par."""
    HDR = "Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,Liquidacion,Moneda,Importe"
    ROWS = [
        # Suscripción plana, Importe POSITIVO → COMPRA (antes la tomaba VENTA)
        "Suscripción / 1,BCRFA,Fondos,2025-10-16,13553.17,213.97,2025-10-16,Pesos,2900000",
        # Sweep apareado (Liquidación + desde Balanz, mismo ticker/fecha/qty) → 1 COMPRA
        "Liquidación de Suscripción / 2,BCACCA,Fondos,2023-06-16,6777.92,22.13,2023-06-16,Pesos,-150000",
        "Suscripción desde Balanz / 3,BCACCA,Fondos,2023-06-16,6777.92,22.13,2023-06-16,Pesos,150000",
        # Sweep SIN par (suscripción directa) → SÍ cuenta como COMPRA
        "Suscripción desde Balanz / 4,LECAPSA,Fondos,2024-05-30,1484344.71,1.01,2024-05-30,Pesos,1499998.61",
        # Rescate, Importe NEGATIVO → VENTA
        "Rescate / 5,LECAPSA,Fondos,2025-10-16,1764974.75,1.64,2025-10-16,Pesos,-2900000",
    ]

    def setUp(self):
        res = BalanzMovimientosParser().parse(self.HDR + "\n" + "\n".join(self.ROWS) + "\n")
        self.assertEqual(res.parse_errors, [])
        self.ops = [rr.data for rr in res.raw_rows]

    def _for(self, asset):
        return [d for d in self.ops if d.get("activo") == asset]

    def test_suscripcion_positiva_es_compra(self):
        # Importe + en una Suscripción de fondo → COMPRA (no VENTA por el signo)
        bcrfa = self._for("BCRFA")
        self.assertEqual([d["tipo"] for d in bcrfa], ["COMPRA"])
        self.assertEqual(float(bcrfa[0]["cantidad"]), 13553.17)

    def test_sweep_apareado_no_duplica(self):
        # Liquidación + 'desde Balanz' (mismo ticker/fecha/cantidad) → 1 sola COMPRA
        bcacca = self._for("BCACCA")
        self.assertEqual([d["tipo"] for d in bcacca], ["COMPRA"])
        self.assertEqual(float(bcacca[0]["cantidad"]), 6777.92)

    def test_sweep_sin_par_si_cuenta(self):
        # 'Suscripción desde Balanz' sin Liquidación → COMPRA ; Rescate → VENTA
        lecapsa = self._for("LECAPSA")
        self.assertEqual(sorted(d["tipo"] for d in lecapsa), ["COMPRA", "VENTA"])
        compra = [d for d in lecapsa if d["tipo"] == "COMPRA"][0]
        self.assertEqual(float(compra["cantidad"]), 1484344.71)


class BalanzMovimientosCanjeArancelesTest(unittest.TestCase):
    """Tipos de un export real más amplio que antes caían como 'no reconocido' o
    como FEE con monto 0 ('comisión aislada'): canje de bono por aviso de
    suscripción, débito de aranceles (fee), baja de derecho de suscripción,
    dividendo en especie (nominales gratis) y acción societaria que BAJA nominales
    (qty<0 → cierre a precio 0 con _corporate_close, que el validador acepta)."""

    def _parse(self, *rows):
        return BalanzMovimientosParser().parse(HDR + "\n" + "\n".join(rows) + "\n")

    def _by_tipo(self, res):
        by = {}
        for rr in res.raw_rows:
            by.setdefault(rr.data["tipo"], []).append(rr.data)
        return by

    def test_canje_s_aviso_es_ingreso_y_default_ars(self):
        # Canje s/Aviso de Suscripción de un bono: solo cash (sin cantidad/precio),
        # moneda vacía → ingreso (DIVIDENDO) en ARS por default.
        res = self._parse(
            "Canje s/Aviso de Suscripción 12/16/4 / GN34O,GN34O,Corporativos,2025-10-01,0,0,2025-10-01,,190737.7")
        self.assertEqual(res.parse_errors, [])
        div = self._by_tipo(res)["DIVIDENDO"][0]
        self.assertEqual(div["activo"], "GN34O")
        self.assertEqual(div["moneda"], "ARS")
        self.assertAlmostEqual(float(div["monto"]), 190737.7, places=2)

    def test_debito_aranceles_es_fee(self):
        res = self._parse(
            "Débito de Aranceles por Acreencias,,,2025-10-02,0,0,2025-10-02,Pesos,-4579.81")
        self.assertEqual(res.parse_errors, [])
        fee = self._by_tipo(res)["FEE"][0]
        self.assertAlmostEqual(float(fee["monto"]), 4579.81, places=2)
        self.assertNotIn("activo", fee)  # sin ticker

    def test_baja_derecho_es_cash_sin_tocar_posicion(self):
        # Baja de derecho de suscripción: cash + cantidad (los DERECHOS, no acciones)
        # → la renta ignora la cantidad y solo cuenta el cash (no vende BBAR).
        res = self._parse(
            "Baja Derecho de Suscripción / BBAR,BBAR,Acciones,2025-10-03,360,0,2025-10-03,,849.55")
        self.assertEqual(res.parse_errors, [])
        self.assertEqual(len(res.raw_rows), 1)       # una sola fila (cash)
        div = res.raw_rows[0].data
        self.assertEqual(div["tipo"], "DIVIDENDO")
        self.assertNotIn("cantidad", div)            # NO se emite cantidad (no es venta)
        self.assertAlmostEqual(float(div["monto"]), 849.55, places=2)

    def test_canje_con_cantidad_es_intercambio_de_bono(self):
        # Canje de bono (debt exchange): el viejo SALE (cantidad −) y el nuevo ENTRA
        # (cantidad +), con importe 0. Antes caía en renta (cash-only) → la cantidad
        # se IGNORABA y el bono quedaba como posición fantasma. Ahora → corporate:
        # VENTA del viejo (_corporate_close) + COMPRA del nuevo.
        res = self._parse(
            "Canje s/Aviso Suscripcion 23/10/20 / IRC1O,IRC1O,Corporativos,2020-10-28,-9,0,2020-10-28,,0",
            "Canje s/Aviso de Suscripción 22/10/20 / 23231,IRC9O,Corporativos,2020-11-12,9,0,2020-11-12,,0",
        )
        self.assertEqual(res.parse_errors, [])
        by = self._by_tipo(res)
        venta = next(d for d in by["VENTA"] if d["activo"] == "IRC1O")
        self.assertEqual(float(venta["cantidad"]), 9.0)
        self.assertTrue(venta.get("_corporate_close"))      # cierra el bono viejo
        compra = next(d for d in by["COMPRA"] if d["activo"] == "IRC9O")
        self.assertEqual(float(compra["cantidad"]), 9.0)    # entra el bono nuevo

    def test_dividendo_en_especie_positivo_suma_nominales(self):
        # Antes caía como FEE monto 0 ('comisión aislada'). Ahora: nominales gratis.
        res = self._parse(
            "Dividendo en especie / AE38,AE38,Bonos,2025-10-04,75,0,2025-10-04,Pesos,0")
        self.assertEqual(res.parse_errors, [])
        compra = self._by_tipo(res)["COMPRA"][0]
        self.assertEqual(compra["activo"], "AE38")
        self.assertEqual(float(compra["cantidad"]), 75.0)
        self.assertEqual(float(compra["precio"]), 0.0)
        # no se emite ninguna fila de cash (importe 0)
        self.assertNotIn("FEE", self._by_tipo(res))

    def test_societaria_qty_negativa_cierra_a_precio_0(self):
        # "Dividendo en acciones" / "en especie" con cantidad NEGATIVA (típicamente
        # cambio de ratio a la baja): VENTA precio 0 marcada _corporate_close → el
        # validador la acepta (sin esto: MISSING_PRICE) y baja la posición.
        res = self._parse(
            "Dividendo en acciones / VIST,VIST,Cedears,2025-10-05,-200,0,2025-10-05,Pesos,0",
            "Dividendo en especie / AE38,AE38,Bonos,2025-10-06,-25,0,2025-10-06,Pesos,0",
        )
        self.assertEqual(res.parse_errors, [])
        ventas = self._by_tipo(res)["VENTA"]
        self.assertEqual({v["activo"] for v in ventas}, {"VIST", "AE38"})
        for v in ventas:
            self.assertEqual(float(v["precio"]), 0.0)
            self.assertTrue(v.get("_corporate_close"))

    def test_renta_sin_cash_no_emite_fee_monto_0(self):
        # Una fila de renta/cobro/fee con importe 0 PERO con cantidad (que dejó
        # pasar el guard de arriba) NO debe emitir un FEE monto 0 → el validador lo
        # rechazaba ("comisión aislada necesita monto > 0"). Se omite limpio.
        res = self._parse(
            "Pago Complementario / TLC1O,TLC1O,Corporativos,2025-10-01,150,0,2025-10-01,Pesos,0",
            "Intereses devengados / GD30,GD30,Bonos,2025-10-02,200,0,2025-10-02,Pesos,0",
            "Renta / AL30,AL30,Bonos,2025-10-03,100,0,2025-10-03,Pesos,0",
        )
        self.assertEqual(res.parse_errors, [])
        self.assertEqual(len(res.raw_rows), 0)       # nada que importar (sin cash)
        # y NO hay ningún FEE/DIVIDENDO con monto 0
        self.assertFalse(any(rr.data.get("tipo") in ("FEE", "DIVIDENDO")
                             and float(rr.data.get("monto") or 0) == 0
                             for rr in res.raw_rows))

    def test_descripcion_desconocida_sin_cash_sigue_flaggeada(self):
        # El guard de "cash-only sin cash" NO debe tragarse una descripción
        # DESCONOCIDA (esa sigue yendo al RowError para el Import Guardian).
        res = self._parse(
            "Algo Totalmente Nuevo / 9,XYZ,Acciones,2025-10-01,5,0,2025-10-01,Pesos,0")
        self.assertEqual(len(res.raw_rows), 0)
        self.assertTrue(any(e.code == "BALANZ_MOV_DESC_DESCONOCIDA" for e in res.parse_errors))


class BalanzFeeTaxClassificationTest(unittest.TestCase):
    """Comisiones vs impuestos vs ajuste de cambio (fix del metric inflado)."""

    HDR2 = HDR
    ROWS2 = [
        "Movimiento Manual / N/D Ret IIGG - IRSA,,,2026-01-01,0,-1,2026-01-01,Pesos,-1000",           # retención impuesto → IMPUESTO
        "Movimiento Manual / Ret IIGG y BBPP - BYMA,,,2026-01-01,0,-1,2026-01-01,Pesos,-500",          # retención impuesto → IMPUESTO
        "Movimiento Manual / Gastos por operación de Fondos,,,2026-01-01,0,-1,2026-01-01,Dólares,-5",   # gasto real → FEE
        "Movimiento Manual / Conversión CV 7.000 a CV 10.000,,,2026-01-01,0,-1,2026-01-01,Dólares C.V. 7000,-9.88",  # transferencia → SKIP
        "Movimiento Manual / Conversión CV 7.000 a CV 10.000,,,2026-01-01,0,-1,2026-01-01,Dólares,9.88",             # transferencia → SKIP
        "Boleto / 500 / COMPRA / 0 / GGAL / $,GGAL,Cedears,2026-01-01,10,-1,2026-01-01,Pesos,-30",      # comisión de boleto → FEE
        "Dividendo en efectivo / SPY,SPY,Cedears,2026-01-01,0,-1,2026-01-01,Dólares,-2",                # retención dividendo → IMPUESTO
    ]

    def setUp(self):
        csv = self.HDR2 + "\n" + "\n".join(self.ROWS2) + "\n"
        self.res = BalanzMovimientosParser().parse(csv)
        self.tipos = [rr.data["tipo"] for rr in self.res.raw_rows]

    def test_no_parse_errors(self):
        self.assertEqual(self.res.parse_errors, [])

    def test_taxes_are_impuesto_not_fee(self):
        # Ret IIGG (x2) + retención de dividendo = 3 IMPUESTO; NINGUNO como FEE.
        self.assertEqual(self.tipos.count("IMPUESTO"), 3)

    def test_real_fees_are_fee(self):
        # "Gastos por operación" + comisión de boleto = 2 FEE (sin impuestos ni conversión).
        self.assertEqual(self.tipos.count("FEE"), 2)

    def test_conversion_cv_is_skipped(self):
        # La conversión entre buckets de dólar netea a 0 → NO emite fee ni interés.
        self.assertNotIn("INTERES", self.tipos)
        # las 2 filas de conversión no generan ninguna operación
        self.assertEqual(len(self.res.raw_rows), 5)  # 7 filas − 2 conversiones


class BalanzEmbeddedCommissionTest(unittest.TestCase):
    """Comisión EMBEBIDA en el Importe del trade (Balanz no la trae como columna).
    comisión = |Precio×Cantidad − Importe|; monto = bruto (Precio×Cantidad).
    Cash-neutral: COMPRA paga bruto+comisión = |Importe|; VENTA cobra
    bruto−comisión = |Importe|."""

    ROWS_C = [
        # COMPRA NU: bruto 46×10270=472420, paga 475563.95 → comisión 3143.95
        "Boleto / 1 / COMPRA / 0 / NU / $,NU,Cedears,2026-01-01,46,10270,2026-01-01,Pesos,-475563.95",
        # VENTA BKNG: bruto 546×396=216216, cobra 214777.08 → comisión 1438.92
        "Boleto / 2 / VENTA / 0 / BKNG / $,BKNG,Cedears,2026-01-01,546,396,2026-01-01,Pesos,214777.08",
    ]

    def setUp(self):
        csv = HDR + "\n" + "\n".join(self.ROWS_C) + "\n"
        self.by = {}
        res = BalanzMovimientosParser().parse(csv)
        self.assertEqual(res.parse_errors, [])
        for rr in res.raw_rows:
            self.by[rr.data["activo"]] = rr.data

    def test_commission_extracted(self):
        self.assertAlmostEqual(float(self.by["NU"]["comisiones"]), 3143.95, places=2)
        self.assertAlmostEqual(float(self.by["BKNG"]["comisiones"]), 1438.92, places=2)

    def test_monto_is_gross(self):
        self.assertAlmostEqual(float(self.by["NU"]["monto"]), 472420.0, places=2)
        self.assertAlmostEqual(float(self.by["BKNG"]["monto"]), 216216.0, places=2)

    def test_cash_neutral(self):
        # COMPRA: monto + comisión = |Importe|
        nu = self.by["NU"]
        self.assertAlmostEqual(float(nu["monto"]) + float(nu["comisiones"]), 475563.95, places=2)
        # VENTA: monto − comisión = |Importe|
        bk = self.by["BKNG"]
        self.assertAlmostEqual(float(bk["monto"]) - float(bk["comisiones"]), 214777.08, places=2)


class BalanzEmbeddedGateTest(unittest.TestCase):
    """La comisión embebida se extrae SOLO en pesos y con tasa sana (≤3%).
    En dólares la comisión viene como fila ARS aparte → extraerla duplicaría."""

    def _parse(self, row):
        res = BalanzMovimientosParser().parse(HDR + "\n" + row + "\n")
        self.assertEqual(res.parse_errors, [])
        return res.raw_rows[0].data

    def test_usd_trade_no_extrae_embebida(self):
        # Trade en dólares con gap (ruido FX) → NO extrae, monto=|Importe|.
        d = self._parse("Boleto / 9 / COMPRA / 0 / AAPL / U$S,AAPL,Cedears,2026-01-01,10,18.5,2026-01-01,Dólares,-185.30")
        self.assertEqual(float(d.get("comisiones") or 0), 0.0)
        self.assertAlmostEqual(float(d["monto"]), 185.30, places=2)

    def test_peso_trade_si_extrae(self):
        d = self._parse("Boleto / 10 / COMPRA / 0 / NU / $,NU,Cedears,2026-01-01,46,10270,2026-01-01,Pesos,-475563.95")
        self.assertAlmostEqual(float(d["comisiones"]), 3143.95, places=2)

    def test_clamp_gap_absurdo_no_es_comision(self):
        # Bono per-100 leído per-1: gross 100× el Importe → gap absurdo (>3%) →
        # NO se inventa comisión gigante; cae a monto=|Importe|, comisiones=0.
        d = self._parse("Boleto / 11 / COMPRA / 1 / AL30 / $,AL30,Bonos,2026-01-01,1000,100,2026-01-01,Pesos,-1000")
        self.assertEqual(float(d.get("comisiones") or 0), 0.0)
        self.assertAlmostEqual(float(d["monto"]), 1000.0, places=2)


if __name__ == "__main__":
    unittest.main()
