"""Punta a punta: movimientos + una foto que NO coincide, y los cuatro baldes.

No es un test unitario de una función: entra por `/api/imports/preview` y
`/api/imports/confirm` como el wizard, y después por
`/api/imports/tenencia/preview` con la foto. Es el flujo real.

El escenario está armado para que salgan las cuatro categorías a la vez:

  · MELI   — Rendi y la foto coinciden                        → matched
             (a propósito NO es un bono amortizante: con AL30 la proyección
              aplica `residual_factor` y `positions` queda con el RESIDUAL
              mientras la foto reporta el NOMINAL — un desajuste real, pero
              de otro tema que el de este test)
  · GGAL   — la foto tiene MÁS que Rendi                       → to_seed
  · YPFD   — Rendi tiene MÁS que la foto                       → over
  · AAPL   — Rendi lo tiene y la foto NO                       → not_in_snapshot
  · TSLA   — comprado DESPUÉS de la fecha de la foto           → no aparece:
             la proyección lo saca, que es todo el punto de la ventana temporal
  · NVDA   — editado a mano después de la foto                 → no_reconciliable
"""
import io
import unittest
import uuid

import main
from fastapi.testclient import TestClient

FOTO = "2026-06-30"

# Movimientos de Cocos. TSLA se compra DESPUÉS de la fecha de la foto: si la
# proyección no funciona, aparece como `over` y el asesor decide sobre algo que
# no es una discrepancia.
MOVIMIENTOS = (
    "nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;"
    "instrumento;moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total\n"
    "1;1;02-01-2026;02-01-2026;Compra;Mercado Libre (MELI);ARS;BYMA;1000;60,00;60000,00;0;0;0;0;60000,00\n"
    "2;2;03-01-2026;03-01-2026;Compra;Galicia (GGAL);ARS;BYMA;50;7000,00;350000,00;0;0;0;0;350000,00\n"
    "3;3;04-01-2026;04-01-2026;Compra;YPF (YPFD);ARS;BYMA;100;45000,00;4500000,00;0;0;0;0;4500000,00\n"
    "4;4;05-01-2026;05-01-2026;Compra;Apple (AAPL);ARS;BYMA;10;250000,00;2500000,00;0;0;0;0;2500000,00\n"
    "5;5;15-07-2026;15-07-2026;Compra;Tesla (TSLA);ARS;BYMA;20;300000,00;6000000,00;0;0;0;0;6000000,00\n"
)

# La foto del broker al 30/06: AL30 igual, GGAL de más, YPFD de menos, sin AAPL,
# y sin TSLA (todavía no lo había comprado).
FOTO_CSV = (
    "instrumento;cantidad;precio;moneda;total\n"
    "Mercado Libre (MELI);1000;60,00;ARS;60000,00\n"
    "Galicia (GGAL);80;7000,00;ARS;560000,00\n"
    "YPF (YPFD);40;45000,00;ARS;1800000,00\n"
)


class ReconcileE2ETest(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES (?,'x',1)",
            (f"e2e-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
        conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,'Cocos','ARS')",
                     (self.uid,))
        conn.commit(); conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def _importar_movimientos(self):
        r = self.http.post(
            "/api/imports/preview",
            files={"file": ("mov.csv", io.BytesIO(MOVIMIENTOS.encode()), "text/csv")},
            data={"broker": "Cocos", "format": "cocos"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        sid = r.json()["session_id"]
        r = self.http.post("/api/imports/confirm", json={"session_id": sid}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def _subir_foto(self, nombre=f"portfolio_report_{FOTO.replace('-','')}.csv"):
        r = self.http.post(
            "/api/imports/tenencia/preview",
            files={"file": (nombre, io.BytesIO(FOTO_CSV.encode()), "text/csv")},
            data={"broker": "Cocos", "format": "cocos"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ── el caso completo ────────────────────────────────────────────────────
    def test_las_cuatro_categorias_salen_juntas(self):
        self._importar_movimientos()
        j = self._subir_foto()

        # La fecha salió del NOMBRE del archivo (el CSV de Cocos no la trae).
        self.assertEqual(j["fecha_origen"], "nombre_archivo")
        self.assertEqual(j["fecha_usada"], FOTO)
        self.assertTrue(j["proyeccion"], "la proyección tiene que haber corrido")
        self.assertEqual(j["proyeccion"]["fecha"], FOTO)

        seed = {x["ticker"]: x["qty"] for x in j["to_seed"]}
        over = {x["ticker"]: (x["rendi"], x["tenencia"]) for x in j["over"]}
        ausentes = {x["ticker"] for x in j["not_in_snapshot"]}

        # la foto tiene 80 y Rendi 50 → se completa el hueco de 30
        self.assertEqual(seed.get("GGAL"), 30)
        # Rendi tiene 100 y la foto 40 → sobra
        self.assertEqual(over.get("YPFD"), (100, 40))
        # está en Rendi y no en la foto
        self.assertIn("AAPL", ausentes)
        # AL30 coincide: no aparece en ningún balde de problema
        self.assertNotIn("MELI", seed)
        self.assertNotIn("MELI", over)
        self.assertNotIn("MELI", ausentes)

    def test_lo_comprado_DESPUES_de_la_foto_no_es_una_discrepancia(self):
        # ⭐ El motivo de toda la ventana temporal. Sin proyección, TSLA
        # aparecería como `over` (Rendi lo tiene, la foto no) y el asesor
        # tendría que decidir si cierra una posición que está perfectamente
        # bien — comprada dos semanas DESPUÉS del corte de la foto.
        self._importar_movimientos()
        j = self._subir_foto()
        ausentes = {x["ticker"] for x in j["not_in_snapshot"]}
        over = {x["ticker"] for x in j["over"]}
        self.assertNotIn("TSLA", ausentes)
        self.assertNotIn("TSLA", over)

    def test_sin_proyeccion_TSLA_si_seria_una_discrepancia(self):
        # El control negativo: con la fecha inventada no se proyecta, y TSLA
        # vuelve a aparecer como problema. Sin esto, el test de arriba podría
        # estar pasando por casualidad.
        self._importar_movimientos()
        j = self._subir_foto(nombre="EstadoDeCuenta.csv")   # sin fecha en el nombre
        self.assertEqual(j["fecha_origen"], "fallback_hoy")
        self.assertIsNone(j["proyeccion"])
        self.assertIn("TSLA", {x["ticker"] for x in j["not_in_snapshot"]})

    def test_lo_editado_a_mano_sale_como_no_reconciliable(self):
        self._importar_movimientos()
        conn = main.get_db()
        conn.execute(
            "INSERT INTO operations (user_id,date,broker,asset,op_type,entry_price,"
            "exit_price,quantity,pnl_usd) VALUES (?,'2026-07-20','Cocos','NVDA','Venta',1,2,5,5)",
            (self.uid,))
        conn.execute("INSERT INTO positions (user_id,broker,asset,is_cash,quantity,"
                     "buy_price,invested) VALUES (?,'Cocos','NVDA',0,5,1,5)", (self.uid,))
        conn.commit(); conn.close()
        j = self._subir_foto()
        motivos = {x["ticker"]: x["motivo"] for x in j["no_reconciliable"] if x.get("ticker")}
        self.assertEqual(motivos.get("NVDA"), "datos_manuales")

    def test_los_baldes_NO_se_presentan_con_la_misma_confianza(self):
        # La verificación contra el snapshot del cron compara COMPOSICIÓN, no
        # cantidades. Respalda `to_seed` y `not_in_snapshot`; no respalda `over`,
        # que es justo el que puede reducir una tenencia.
        self._importar_movimientos()
        j = self._subir_foto()
        conf = j["confianza"]
        self.assertEqual(conf["not_in_snapshot"], "verificada_composicion")
        self.assertEqual(conf["to_seed"], "verificada_composicion")
        self.assertEqual(conf["over"], "sin_verificar_cantidad")


if __name__ == "__main__":
    unittest.main()
