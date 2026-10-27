"""El rendimiento CERTERO desde el CSV, contra la VERDAD (auditoría 2026-10-27, fase A).

Un inversor inventado (2024-01 → 2026-08: aportes en pesos y en dólares, CEDEARs,
acciones, un bono con cupones, dólar MEP con bono puente, ventas, un retiro) escrito en
el formato de Balanz y de IEB, con su foto de tenencia, en un mercado inventado donde el
rendimiento VERDADERO se conoce exacto (`tests/rendimiento_csv/`, copia de
`audit/rendimiento_csv/`). Todo entra por las puertas reales: subida HTTP, confirm con
su reconstrucción en su hilo, foto de tenencia, el cron real día por día y el motor.

Lo que la auditoría midió con el código de antes (escenario completo, Balanz): el
Certero medía sólo los últimos tres meses (desde que arrancó el cron), porque
  · H1 — cada dividendo en dólares de un CEDEAR que vive en la cuenta en pesos dejaba
    sin cobertura todos los meses anteriores;
  · H3 — el bono iba siempre al costo ("data912 es live-only") y ningún mes llegaba al
    90 % de cobertura;
y, una vez destrabado eso, la historia no servía igual:
  · H14 — valía "contabilidad + no realizado": la caja y el costo en pesos no se
    devalúan ahí, y 2025 daba +49,9 % contra +40,2 % real (el total cerraba por
    casualidad: la unión con el cron devolvía −9,7 % en cuatro días);
  · H13 — cada aporte pesaba como si hubiera entrado a mitad de mes.
Con un export que arranca en 2025 (H5): Certero +70,6 % contra +25,5 % real.
"""
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import twr  # noqa: E402
from tests.rendimiento_csv.camino import Camino  # noqa: E402
from mercado import Mercado  # noqa: E402
from historia import historia_base  # noqa: E402
import generadores as g  # noqa: E402

FOTO = "2026-08-03"
HOY = date.today().isoformat()
FORMATOS = {"balanz": (g.balanz_mov, "Balanz", "balanz_movimientos", "mov.xlsx",
                       g.balanz_foto, "balanz_tenencia", "ResumenDeCuenta.pdf"),
            "ieb": (g.ieb_mov, "IEB", "ieb", "actividad.xlsx",
                    g.ieb_foto, "ieb_tenencia", "portafolio.xlsx")}


class _Inversor(unittest.TestCase):

    def cuenta(self, broker="balanz", omitir=None):
        """La historia base subida en el formato de `broker`, con su foto de tenencia
        y el cron real desde el día siguiente a lo último hasta hoy. Devuelve
        (camino, historia)."""
        m = Mercado()
        h = historia_base(m)
        h.simular()
        c = Camino(self, m)
        c.usuario(f"csv-{broker}-{id(self)}@rendi.test")
        gen, nombre_b, fmt, archivo, foto, ffmt, farchivo = FORMATOS[broker]
        c.subir(archivo, gen(h, omitir=omitir), nombre_b, fmt)
        c.subir_foto(farchivo, foto(h, FOTO), nombre_b, ffmt)
        ult = c.q("SELECT MAX(n.date) d FROM import_normalized_tx n JOIN import_batches b "
                  "ON b.id=n.batch_id WHERE b.user_id=? AND b.status='confirmed'", c.uid)[0]["d"]
        c.cron(max(date.fromisoformat(ult[:10]), date.fromisoformat(FOTO)) + timedelta(days=1),
               date.today())
        c.reconstruir()
        return c, h

    def error_pp(self, c, h, modo="certero"):
        cv = c.curva(modo)
        self.assertIsNotNone(cv["twr"], cv.get("motivo"))
        verdad = h.twr_verdad(cv["ventana_desde"], HOY)
        return cv, cv["twr"] * 100 - verdad


class ElCerteroMideLaHistoria(_Inversor):

    def test_desde_el_primer_mes_y_contra_la_verdad(self):
        for broker in ("balanz", "ieb"):
            with self.subTest(broker=broker):
                c, h = self.cuenta(broker)
                cv, err = self.error_pp(c, h)
                # Antes: desde 2026-08-04 (el cron).
                self.assertEqual(cv["ventana_desde"], "2024-01-31")
                self.assertLess(abs(err), 1.0, cv["twr"])

    def test_cada_anio_y_cada_mes_contra_la_verdad(self):
        """El total puede cerrar por casualidad (con la regla vieja cerraba). Lo que
        prueba que la historia mide es el camino: cada año, cada mes, y la unión con
        el cron."""
        c, h = self.cuenta("balanz")
        cv = c.curva("certero")
        idx = {p["date"]: p["index_publicado"] for p in cv["curva"]}
        for a, b in (("2024-01-31", "2024-12-31"), ("2024-12-31", "2025-12-31")):
            r = (idx[b] / idx[a] - 1) * 100
            self.assertLess(abs(r - h.twr_verdad(a, b)), 0.5, (a, b, r))
        meses = sorted(d for d in idx if d < "2026-08" and d[8:] in ("28", "29", "30", "31")
                       and (date.fromisoformat(d) + timedelta(days=1)).day == 1)
        for a, b in zip(meses, meses[1:]):
            r = (idx[b] / idx[a] - 1) * 100
            self.assertLess(abs(r - h.twr_verdad(a, b)), 0.1, (a, b, r))
        # La unión historia → cron: antes −9,7 % en cuatro días que no existieron.
        r = (idx["2026-08-04"] / idx["2026-07-31"] - 1) * 100
        self.assertLess(abs(r - h.twr_verdad("2026-07-31", "2026-08-04")), 0.1, r)

    def test_los_cobros_no_dejan_la_historia_sin_cobertura(self):
        """H1: el dividendo en dólares de AAPL (16/05/2024) cae en "Balanz · USD" y
        AAPL vive en "Balanz": antes dejaba sin cobertura todos los meses anteriores."""
        c, _ = self.cuenta("balanz")
        sin = c.q("SELECT date FROM snapshots WHERE user_id=? AND source='mtm_backfill' "
                  "AND mtm_coverage IS NULL", c.uid)
        self.assertEqual(sin, [])

    def test_el_bono_tiene_precio_en_la_historia(self):
        """H3: el GD38 se valúa con las velas de data912; ningún mes cae al costo."""
        c, _ = self.cuenta("balanz")
        cobs = {r["date"]: r["mtm_coverage"] for r in c.q(
            "SELECT date, mtm_coverage FROM snapshots WHERE user_id=? "
            "AND source='mtm_backfill'", c.uid)}
        self.assertTrue(cobs)
        self.assertEqual({d for d, v in cobs.items() if v < 0.999}, set())


class LoQueLaFotoDesmienteNoEsCertero(_Inversor):

    def test_un_export_que_arranca_en_2025(self):
        """H5: una venta de AAPL comprado en 2024 sin su compra en el archivo, y una
        foto que agrega lo que el archivo no traía. Antes: Certero +70,6 % contra
        +25,5 % real. El Certero puede no publicar, o publicar con error < 1 pp."""
        c, h = self.cuenta("balanz", omitir=lambda e: e.fecha < "2025-01-01")
        cv = c.curva("certero")
        if cv["twr"] is not None:
            err = cv["twr"] * 100 - h.twr_verdad(cv["ventana_desde"], HOY)
            self.assertLess(abs(err), 1.0, cv["ventana_desde"])
        # Lo anterior a la foto describe un archivo que la foto desmintió.
        antes = c.q("SELECT apto FROM snapshots WHERE user_id=? AND source='mtm_backfill' "
                    "AND date < ?", c.uid, FOTO)
        self.assertTrue(antes)
        self.assertEqual({r["apto"] for r in antes}, {0})

    def test_falta_una_venta(self):
        """S2: el archivo no trae la venta de 400 GGAL; la foto los cierra al costo.
        La historia anterior sigue teniendo esos títulos: no es certero."""
        c, h = self.cuenta("balanz", omitir=lambda e: e.tipo == "SELL" and e.tk == "GGAL")
        cv, err = self.error_pp(c, h)
        self.assertGreaterEqual(cv["ventana_desde"], FOTO)
        self.assertLess(abs(err), 1.0)


class ElAporteTieneFecha(unittest.TestCase):
    """H13, el ejemplo del dueño: US$ 1.000 en XYZ que sube 30 %, un aporte de
    US$ 39.000 el 2 de mayo y una baja de 10 %, por un archivo de Schwab. Con todo
    aporte pesando como si hubiera entrado a mitad de mes, mayo daba −14,90 % en vez
    de −7,69 % y el acumulado +1,2 % en vez de +9,78 %."""

    PX = [("2025-01-06", 100), ("2025-04-30", 130), ("2025-05-02", 130), ("2025-05-31", 120),
          ("2025-08-31", 117), (HOY, 117)]
    FLUJOS = [("2025-01-06", 1000, 10), ("2025-05-02", 39000, 300)]

    def _valor(self, m, d):
        return sum(q for f, _, q in self.FLUJOS if f <= d.isoformat()) * m.usd("XYZ", d)

    def _verdad(self, m, d0, d1):
        idx, d = 1.0, date.fromisoformat(d0)
        prev = self._valor(m, d)
        while d < date.fromisoformat(d1):
            d += timedelta(days=1)
            fl = sum(ap for f, ap, _ in self.FLUJOS if f == d.isoformat())
            idx *= self._valor(m, d) / (prev + fl)
            prev = self._valor(m, d)
        return (idx - 1) * 100

    def test_el_aporte_grande_del_2_de_mayo(self):
        m = Mercado(extra_usd={"XYZ": self.PX})
        c = Camino(self, m)
        c.usuario("pesos-relativos@rendi.test")
        filas = ['"Date","Action","Symbol","Description","Quantity","Price","Fees & Comm","Amount"']
        for f, ap, q in self.FLUJOS:
            d = date.fromisoformat(f).strftime("%m/%d/%Y")
            filas.append(f'"{d}","MoneyLink Transfer","","Tfr BANK","","","","${ap:.2f}"')
            filas.append(f'"{d}","Buy","XYZ","XYZ CORP","{q}","${ap / q:.2f}","","-${ap:.2f}"')
        c.subir("schwab.csv", "\n".join(filas).encode(), "Schwab", "schwab")
        c.cron(date(2026, 10, 1), date.today())
        c.reconstruir()
        for modo in ("certero", "estimado"):
            cv = c.curva(modo)
            self.assertEqual(cv["ventana_desde"], "2025-01-31", modo)
            err = cv["twr"] * 100 - self._verdad(m, cv["ventana_desde"], HOY)
            self.assertLess(abs(err), 0.5, (modo, cv["twr"]))


class ElEstimadoSeApagaEnLaPrimeraMedicion(unittest.TestCase):
    """H4: la contabilidad se apaga en la primera MEDICIÓN DEL CRON, como dice el
    comentario de `serie_medible` — no en la primera foto apta, que puede ser una
    reconstrucción. Con el primer mes 100 % valuado y meses contables después (acá,
    un lote recibido gratis que no tiene precio), esos meses quedaban afuera del
    Estimado aunque fueran anteriores a toda medición."""

    def test_los_meses_contables_anteriores_al_cron_cuentan(self):
        m = Mercado()
        c = Camino(self, m)
        c.usuario("h4@rendi.test")
        hdr = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"
        filas = ["2025-01-02,DEPOSITO,IBKR,,,,10000,,,0,USD,",
                 f"2025-01-03,COMPRA,IBKR,AAPL,20,{m.usd('AAPL', '2025-01-03'):.2f},"
                 f"{20 * m.usd('AAPL', '2025-01-03'):.2f},,,0,USD,"]
        import main
        conn = main.get_db()
        with conn:
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                         (c.uid, "IBKR", "USDT"))
        conn.close()
        c.subir("mov.csv", (hdr + "\n".join(filas) + "\n").encode(), "IBKR", "rendi_generic")
        # Un lote recibido gratis en marzo y vendido en junio: sin precio ni costo,
        # esos meses no se pueden valuar (cobertura sin afirmar → contables).
        r = c.http.post("/api/positions", headers=c.h, json={
            "broker": "IBKR", "asset": "LIBRE", "quantity": 10, "buy_price": 0,
            "invested": 0, "entry_date": "2025-03-01", "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)
        r = c.http.post("/api/positions/sell", headers=c.h, json={
            "broker": "IBKR", "asset": "LIBRE", "quantity": 10, "exit_price": 1,
            "date": "2025-06-15", "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)
        c._esperar()
        c.cron(date(2025, 9, 1), date(2025, 9, 30))
        c.reconstruir()
        cv = c.curva("estimado", hasta="2025-09-30")
        cobs = {r["date"]: r["mtm_coverage"] for r in c.q(
            "SELECT date, mtm_coverage FROM snapshots WHERE user_id=? "
            "AND source='mtm_backfill'", c.uid)}
        # Las premisas: enero apto, marzo a mayo sin cobertura.
        self.assertEqual(cobs["2025-01-31"], 1.0)
        self.assertIsNone(cobs["2025-04-30"])
        self.assertEqual(cv["contable_superado"], 0)
        self.assertLessEqual(cv["ventana_desde"], "2025-06-30")


class LaCosturaMideElRetornoDelLeg(unittest.TestCase):
    """H5-b: `costura_no_cierra` medía `v1 / (v0 + flujo)`, que supone el flujo
    entero al principio y con un aporte grande lo diluye."""

    def test_el_caso_medido_se_corta(self):
        # Reconstrucción del 31/07 (2.777), aportes de la foto (15.445), cron del 04/08.
        self.assertTrue(twr.costura_no_cierra(2777.0, 22030.0, 15445.0))

    def test_una_costura_sana_con_un_aporte_grande_pasa(self):
        # 10.000 a fin de mes, aporte de 20.000 invertido, +1 % en los días del medio.
        self.assertFalse(twr.costura_no_cierra(10000.0, 30300.0, 20000.0))
        # Sin aporte, +4 %: pasa; ×1,3: no.
        self.assertFalse(twr.costura_no_cierra(10000.0, 10400.0, 0.0))
        self.assertTrue(twr.costura_no_cierra(10000.0, 13000.0, 0.0))


if __name__ == "__main__":
    unittest.main()
