"""El import y la foto de tenencia (auditoría 2026-10-27, fase D).

Por el camino de producción (subida HTTP, confirm, foto) con el mercado inventado de
la auditoría (`tests/rendimiento_csv/`).

  · H8 — el ajuste de caja de la foto comparaba el efectivo de la foto con el de
    HOY. Escenario S5 (foto del 03/08, movimientos hasta el 01/09 con un depósito de
    $500.000): un "Ajuste de cash" de $1.153.898 (Balanz) / $1.108.538 (IEB) fechado
    el 03/08 que no existió.
  · H11 — las reglas de "cuánta plata había en tal fecha" vivían en dos lugares
    (`ledger_replay.cash_en`, que ignoraba las conversiones y restaba impuestos que el
    importador no resta, y la caja de la reconstrucción). Ahora hay una:
    `ledger_replay.movimientos_de_caja`, y tiene que dar la caja que dejó el importador.
  · IEB — la comisión de una venta viene adentro del importe y se perdía: la caja
    quedaba arriba por la comisión y la foto la "reponía" como un retiro.
"""
import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
from tests.rendimiento_csv.camino import Camino  # noqa: E402
from mercado import Mercado  # noqa: E402
from historia import historia_base  # noqa: E402
import generadores as g  # noqa: E402

FOTO = "2026-08-03"
FORMATOS = {"balanz": (g.balanz_mov, "Balanz", "balanz_movimientos", "mov.xlsx",
                       g.balanz_foto, "balanz_tenencia", "ResumenDeCuenta.pdf"),
            "ieb": (g.ieb_mov, "IEB", "ieb", "actividad.xlsx",
                    g.ieb_foto, "ieb_tenencia", "portafolio.xlsx")}


def _caja_por_moneda(c):
    """La caja que dejó el importador en `positions`, por moneda."""
    from ledger_replay import moneda_de_caja
    out = {}
    for r in c.q("SELECT b.currency, p.invested FROM positions p JOIN brokers b "
                 "ON b.user_id = p.user_id AND b.name = p.broker "
                 "WHERE p.user_id=? AND p.is_cash=1", c.uid):
        k = moneda_de_caja(r["currency"])
        out[k] = out.get(k, 0.0) + float(r["invested"] or 0)
    return out


class LaFotoComparaLaCajaASuFecha(unittest.TestCase):

    def test_movimientos_despues_de_la_foto(self):
        for broker in ("balanz", "ieb"):
            with self.subTest(broker=broker):
                m = Mercado()
                h = historia_base(m, post_foto=True)
                h.dep("2026-09-01", 500_000)
                h.simular()
                c = Camino(self, m)
                c.usuario(f"h8-{broker}@rendi.test")
                gen, nb, fmt, arch, foto, ffmt, farch = FORMATOS[broker]
                c.subir(arch, gen(h), nb, fmt)
                c.subir_foto(farch, foto(h, FOTO), nb, ffmt)
                ajustes = c.q(
                    "SELECT n.operation_type t, n.gross_amount g, n.currency c "
                    "FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id "
                    "WHERE b.user_id=? AND b.parser_format LIKE '%tenencia%' "
                    "AND n.notes LIKE 'Ajuste de cash%' AND n.currency = 'ARS'", c.uid)
                # Lo que queda es el redondeo de la foto (el mismo que en la cuenta
                # sin movimientos posteriores), no el depósito de septiembre.
                self.assertLess(sum(float(a["g"]) for a in ajustes), 1_000, ajustes)


class UnaSolaReglaDeCaja(unittest.TestCase):

    def test_el_replay_da_la_caja_que_dejo_el_importador(self):
        from fechas import hoy_art
        from ledger_replay import cash_en
        for broker in ("balanz", "ieb"):
            with self.subTest(broker=broker):
                m = Mercado()
                h = historia_base(m)
                h.simular()
                c = Camino(self, m)
                c.usuario(f"h11-{broker}@rendi.test")
                gen, nb, fmt, arch = FORMATOS[broker][:4]
                c.subir(arch, gen(h), nb, fmt)
                conn = main.get_db()
                try:
                    replay = {}
                    for (_b, mon), v in cash_en(conn, c.uid, hoy_art()).items():
                        replay[mon] = replay.get(mon, 0.0) + v
                finally:
                    conn.close()
                real = _caja_por_moneda(c)
                for mon in set(replay) | set(real):
                    self.assertAlmostEqual(replay.get(mon, 0.0), real.get(mon, 0.0), delta=0.05,
                                           msg=(mon, replay, real))


class LaComisionDeUnaVentaDeIEB(unittest.TestCase):

    def test_la_venta_cobra_el_importe_neto(self):
        m = Mercado()
        c = Camino(self, m)
        c.usuario("ieb-comision@rendi.test")
        d = [datetime(2026, 3, k, 3, 0) for k in (2, 3, 20)]
        hdr = ("Referencia", "Operación", "Fecha emisión", "Fecha liquidación",
               "Nro. de operación", "Cantidad", "Precio", "Importe ARS", "Importe divisas",
               "Divisa")
        filas = [("-", "RECIBO DE COBRO", d[0], d[0], 9001, "-", "-", 1_000_000, "-", "ARS"),
                 # comisión 600 adentro del importe de la compra
                 ("GGAL", "COMPRA NORMAL", d[1], d[1], 9002, 100, 5000, -500_600, "-", "ARS"),
                 # comisión 720 descontada del importe de la venta
                 ("GGAL", "VENTA", d[2], d[2], 9003, -100, 6000, 599_280, "-", "ARS")]
        c.subir("actividad.xlsx", g._xlsx([("Export", [hdr] + filas)]), "IEB", "ieb")
        self.assertAlmostEqual(_caja_por_moneda(c).get("ARS", 0.0),
                               1_000_000 - 500_600 + 599_280, delta=0.01)


if __name__ == "__main__":
    unittest.main()
