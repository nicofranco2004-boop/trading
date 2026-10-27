"""Tabla parser × tipo de movimiento, por la vista previa HTTP real (/api/imports/preview).

Cada broker recibe el MISMO movimiento económico escrito en su formato (tomado de su
`template_csv()` y de su docstring; los marcados SUPUESTO no tienen ejemplo real en el
repo). Se lee lo que el pipeline produjo: tipo, moneda, broker (padre o '· USD'), monto.
"""
import json, sys
import arnes
from mercado import Mercado

# (tipo económico, fila) por broker. Montos: DEP 100.000 ARS / 500 USD; compra 10 AAPL a 20.000 ARS.
COCOS_H = "nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;instrumento;moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total"
COCOS = [
    ("DEP_ARS", "1;1;05-01-2026;05-01-2026;Recibo De Cobro;;ARS;;;;100.000;0;0;0;0;100.000"),
    ("DEP_USD", "2;2;05-01-2026;05-01-2026;Recibo De Cobro Dolares;;USD;;;;500;0;0;0;0;500"),
    ("WD_ARS", "3;3;06-01-2026;06-01-2026;Orden De Pago;;ARS;;;;-50.000;0;0;0;0;-50.000"),
    ("BUY_CEDEAR_ARS", "4;4;07-01-2026;08-01-2026;Compra;CEDEAR APPLE INC. (AAPL);ARS;BYMA;10;20.000;-200.000;-900;-100;-210;0;-201.210"),
    ("BUY_CEDEAR_USD", "5;5;07-01-2026;08-01-2026;Compra;CEDEAR APPLE INC. (AAPL);USD;BYMA;10;13,5;-135;-0,6;0;0;0;-135,6"),
    ("SELL_ARS", "6;6;09-02-2026;10-02-2026;Venta;CEDEAR APPLE INC. (AAPL);ARS;BYMA;5;22.000;110.000;-500;-50;-105;0;109.345"),
    ("DIV_ARS", "7;7;10-03-2026;10-03-2026;Dividendos;Peso argentino;ARS;;;;2.548,26;0;0;0;0;2.548,26"),
    ("DIV_USD", "8;8;11-03-2026;11-03-2026;Dividendos;Dolar MEP;USD;;;;1,25;0;0;0;0;1,25"),
    ("CUPON_USD", "9;9;09-01-2026;09-01-2026;Renta y Amortizacion;BONO GD38;USD;;;;42,5;0;0;0;0;42,5"),   # SUPUESTO
    ("MEP_COMPRA", "10;10;12-01-2026;12-01-2026;Compra Dolar Mep;BONOS REP. ARG. U$S STEP UP 2030 (AL30);ARS;BYMA;1000;750;-750.000;0;0;0;0;-750.000"),
    ("MEP_VENTA", "11;11;12-01-2026;12-01-2026;Venta Dolar Mep;BONOS REP. ARG. U$S STEP UP 2030 (AL30);USD;BYMA;1000;0,5;500;0;0;0;0;500"),
]
IOL_H = "Nro. de Mov.,Nro. de Boleto,Tipo Mov.,Concert.,Liquid.,Est,Cant. titulos,Precio,Comis.,Iva Com.,Otros Imp.,Monto,Observaciones,Tipo Cuenta"
IOL = [
    ("DEP_ARS", "1,1,Depósito de Fondos - Transferencia electrónica - BANCO X,05/01/2026,05/01/2026,,,,0,0,0,100000.00,,Cuenta Pesos"),
    ("DEP_USD", "2,2,Depósito de Fondos - Transferencia electrónica - BANCO X,05/01/2026,05/01/2026,,,,0,0,0,500.00,,Cuenta Dólares"),
    ("WD_ARS", "3,3,Extracción de Fondos - Transferencia electrónica - BANCO X,06/01/2026,06/01/2026,,,,0,0,0,50000.00,,Cuenta Pesos"),  # SUPUESTO
    ("BUY_CEDEAR_ARS", "4,4,Compra(AAPL),07/01/2026,08/01/2026,,10,20000,180,37.8,5,200222.80,,Cuenta Pesos"),
    ("BUY_CEDEAR_USD", "5,5,Compra(AAPLD),07/01/2026,08/01/2026,,10,13.5,0.12,0.02,0,135.14,,Cuenta Dólares"),
    ("SELL_ARS", "6,6,Venta(AAPL),09/02/2026,10/02/2026,,5,22000,99,20.8,2,109878.20,,Cuenta Pesos"),
    ("DIV_ARS", "7,7,Pago de Dividendos(GGAL),10/03/2026,10/03/2026,,,,0,0,0,2548.26,,Cuenta Pesos"),
    ("DIV_USD", "8,8,Pago de Dividendos(AAPL US$),11/03/2026,11/03/2026,,,,0,0,0,1.25,,Cuenta Dólares"),
    ("CUPON_USD", "9,9,Pago de Renta(GD38),09/01/2026,09/01/2026,,,,0,0,0,42.50,,Cuenta Dólares"),
    ("AMORT_USD", "10,10,Pago de Amortización(GD38),09/01/2026,09/01/2026,,,,0,0,0,80.00,,Cuenta Dólares"),
    ("MEP_COMPRA", "11,11,Compra(AL30),12/01/2026,12/01/2026,,1000,750,0,0,0,750000.00,,Cuenta Pesos"),
    ("MEP_VENTA", "12,12,Venta(AL30D),12/01/2026,12/01/2026,,1000,0.5,0,0,0,500.00,,Cuenta Dólares"),
]
PPI_H = "Fecha,Descripción,Cantidad,Precio,Importe,Saldo,Moneda,Especie,_hoja"
PPI = [
    ("DEP_ARS", "05/01/2026,Ingreso de Fondos ,0,0,100000,100000,Pesos,,Pesos"),
    ("DEP_USD", "05/01/2026,Ingreso de Fondos ,0,0,500,500,Dolar MEP,,Dolar MEP"),
    ("WD_ARS", "06/01/2026,Egreso de Fondos ,0,0,-50000,50000,Pesos,,Pesos"),    # SUPUESTO
    ("BUY_CEDEAR_ARS", "07/01/2026,COMPRA AAPL,10,20000,-201210,-151210,Pesos,,Pesos"),
    ("BUY_CEDEAR_USD", "07/01/2026,COMPRA AAPL,10,13.5,-135.6,364.4,Dolar MEP,,Dolar MEP"),
    ("SELL_ARS", "09/02/2026,VENTA AAPL,5,22000,109345,-41865,Pesos,,Pesos"),
    ("DIV_ARS", "10/03/2026,Dividendo en efectivo / GGAL,0,0,2548.26,-39316.74,Pesos,,Pesos"),
    ("DIV_USD", "11/03/2026,Dividendo en efectivo / MSFT,0,0,1.25,365.65,DolarCV7000 Ext.,,DolarCV7000 Ext."),
    ("CUPON_USD", "09/01/2026,Renta / GD38,0,0,42.5,406.9,Dolar MEP,,Dolar MEP"),   # SUPUESTO
    ("MEP_COMPRA", "12/01/2026,COMPRA AL30,1000,750,-750000,-789316.74,Pesos,,Pesos"),
    ("MEP_VENTA", "12/01/2026,VENTA AL30,1000,0.5,500,906.9,Dolar MEP,,Dolar MEP"),
]
INVIU_H = "Fecha de Concertación,Fecha de Liquidación,Descripción,Tipo de Operación,Ticker,Cantidad VN,Precio,Import Bruto,Importe Neto,Saldo"
INVIU = [("SECCION", "PESOS - $,,,,,,,,,"),
    ("DEP_ARS", "5/1/2026,5/1/2026,Recibo de Cobro / 1,Recibo de Cobro,-,-,0,100000,100000,100000"),
    ("WD_ARS", "6/1/2026,6/1/2026,Comprobante de Pago / 2,Comprobante de Pago,-,-,0,-50000,-50000,50000"),   # SUPUESTO
    ("BUY_CEDEAR_ARS", "7/1/2026,8/1/2026,Boleto / 3 / CPRA / 2 / AAPL / $,CPRA,AAPL,10,20000,-200000,-201210,-151210"),
    ("SELL_ARS", "9/2/2026,10/2/2026,Boleto / 4 / VENTA / 1 / AAPL / $,VENTA,AAPL,-5,22000,110000,109345,-41865"),
    ("DIV_ARS", "10/3/2026,10/3/2026,Dividendo en efectivo / GGAL,Dividendo en efectivo,GGAL,-,0,2548.26,2548.26,-39316.74"),
    ("SECCION", "Dólar MEP - U$S,,,,,,,,,"),
    ("DEP_USD", "5/1/2026,5/1/2026,Recibo de Cobro / 5,Recibo de Cobro,-,-,0,500,500,500"),
    ("BUY_CEDEAR_USD", "7/1/2026,8/1/2026,Boleto / 6 / CPRA / 2 / AAPL / U$S,CPRA,AAPL,10,13.5,-135,-135.6,364.4"),
    ("DIV_USD", "11/3/2026,11/3/2026,Dividendo en efectivo / AAPL,Dividendo en efectivo,AAPL,-,0,1.25,1.25,365.65"),
    ("AMORT_USD", "9/1/2026,9/1/2026,Amortización / GD38,Amortización,GD38,-,0,80,80,445.65"),
    ("CUPON_USD", "9/1/2026,9/1/2026,Renta / GD38,Renta,GD38,-,0,42.5,42.5,488.15"),   # SUPUESTO
]
SCHWAB_H = '"Date","Action","Symbol","Description","Quantity","Price","Fees & Comm","Amount"'
SCHWAB = [
    ("DEP_USD", '"01/05/2026","MoneyLink Transfer","","Tfr CITIBANK NA","","","","$500.00"'),
    ("WD_USD", '"01/06/2026","MoneyLink Transfer","","Tfr CITIBANK NA","","","","-$200.00"'),
    ("BUY_USD", '"01/07/2026","Buy","AAPL","APPLE INC","1","$250.00","","-$250.00"'),
    ("SELL_USD", '"02/09/2026","Sell","AAPL","APPLE INC","1","$260.00","$0.50","$259.50"'),
    ("DIV_USD", '"03/11/2026","Cash Dividend","AAPL","APPLE INC","","","","$1.25"'),
    ("DIV_QUAL_USD", '"03/12/2026","Qualified Dividend","KO","COCA COLA","","","","$2.00"'),
    ("INTERES_USD", '"03/31/2026","Bank Interest","","BANK INT","","","","$0.40"'),
    ("TIN_TITULOS", '"01/04/2026","Journaled Shares","MSFT","MICROSOFT","3","","",""'),   # SUPUESTO
]
CASOS = {"cocos": (COCOS_H, COCOS, ";", "Cocos", "cocos", "cocos.csv"),
         "iol": (IOL_H, IOL, ",", "IOL", "iol", "iol.csv"),
         "ppi": (PPI_H, PPI, ",", "PPI", "ppi", "ppi.csv"),
         "inviu": (INVIU_H, INVIU, ",", "inviu", "inviu", "inviu.csv"),
         "schwab": (SCHWAB_H, SCHWAB, ",", "Schwab", "schwab", "schwab.csv")}


def main():
    salida = sys.argv[1]
    a = arnes.Arnes(Mercado()); res = {}
    for br, (hdr, filas, sep, broker, fmt, nombre) in CASOS.items():
        a.usuario(f"tabla_{br}@rendi.test")
        if br == "inviu":
            body = "\n".join([hdr] + [f for _, f in filas])
        else:
            body = "\n".join([hdr] + [f for _, f in filas])
        prev, _ = a.subir([(nombre, body.encode("utf-8"))], broker=broker, fmt=fmt, confirmar=False)
        etiquetas = [t for t, _ in filas if t != "SECCION"]
        res[br] = {"status": prev.get("detail") or "ok", "etiquetas": etiquetas,
                   "errors": prev.get("errors"), "conduits": prev.get("traspasos"),
                   "rows": [{k: r.get(k) for k in ("row_index", "date", "operation_type", "asset_symbol", "quantity",
                                                   "unit_price", "gross_amount", "fees", "currency", "broker", "notes", "status",
                                                   "transfer_out", "transfer_in")}
                            for r in (prev.get("rows_preview") or [])]}
        print(br, res[br]["status"], len(res[br]["rows"]), "filas", "errores:", len(prev.get("errors") or []), flush=True)
    json.dump(res, open(salida, "w"), ensure_ascii=False, default=str, indent=1)


if __name__ == "__main__":
    main()
