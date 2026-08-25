"""La foto redondea, y ese redondeo NO es un veredicto.

🔴 BUG VIVO EN PRODUCCIÓN cuando se escribió este test. `compute_reconcile`
comparaba la foto contra Rendi con un epsilon ABSOLUTO de 1e-6. Los brokers
reportan cuotapartes de FCI / money market con 2 decimales, así que una tenencia
de 90,1037 contra una foto de 90,10 daba un gap de 0,0037 — y eso se convertía
en una fila sintética.

Medido sobre la copia de prod del 2026-08-16 (152 fotos confirmadas):

  · 39 de los 60 `over` eran esto → una VENTA sintética de 0,004 cuotapartes.
  · 40 de los 580 `to_seed` eran el espejo → una COMPRA sintética. Y `to_seed`
    es el único balde que SE AUTO-APLICA SIN PREGUNTAR.
  · 79 filas sintéticas en total, todas en FCI / money market.

No le pasaba a asesores (no hay ninguno todavía): le pasaba a la gente que sube
su propia foto.

Los números de los tests son los REALES de esos usuarios, no inventados.

Corre con: cd backend && python3 -m pytest tests/test_tenencia_redondeo.py
"""
import io
import unittest
import uuid
from unittest import mock

import main
from fastapi.testclient import TestClient
from importing import tenencia as tn


def _h(ticker, qty, tipo="FUND", ccy="ARS"):
    return tn.Holding(ticker=ticker, asset_type=tipo, quantity=qty,
                      value=qty, currency=ccy, price_per1=1.0)


def _snap(*holdings, fecha="2026-07-05"):
    return tn.TenenciaSnapshot(holdings=list(holdings), date=fecha)


class ToleranciaTest(unittest.TestCase):
    """`tolerancia_qty` sola: de dónde sale la constante."""

    def test_el_piso_absoluto_sigue_siendo_ruido_de_float(self):
        # Con tenencias en 0 no hay relativo del que agarrarse: queda el piso.
        self.assertEqual(tn.tolerancia_qty(0.0, 0.0), tn.EPS_QTY_ABS)

    def test_es_proporcional_a_la_tenencia(self):
        self.assertAlmostEqual(tn.tolerancia_qty(90.10, 90.1037), 90.10 * 1e-4)
        self.assertAlmostEqual(tn.tolerancia_qty(460993.92, 460993.95),
                               460993.92 * 1e-4)

    def test_usa_el_MINIMO_de_las_dos_puntas(self):
        # Nunca el más permisivo de los dos. (Da igual en la práctica — ver el
        # docstring de `tolerancia_qty` —, pero que no se vuelva permisivo por
        # accidente en un refactor.)
        self.assertLessEqual(tn.tolerancia_qty(1e9, 100.0),
                             tn.tolerancia_qty(100.0, 100.0))


class RedondeoDeLaFotoTest(unittest.TestCase):
    """Los dos lados del mismo bug, con datos reales de prod."""

    # ── lado `over`: la foto redondea PARA ABAJO ────────────────────────────
    def test_over_de_redondeo_no_existe(self):
        # u1005, foto Cocos del 2026-07-05: Rendi 90,1037 · foto 90,10.
        # Antes: `over` → VENTA sintética de 0,0037 cuotapartes.
        rec = tn.compute_reconcile({"FCI:COCOS-RENDIMIENTO-A": 90.1037},
                                   _snap(_h("FCI:COCOS-RENDIMIENTO-A", 90.10)))
        self.assertEqual(rec.over, [])
        self.assertEqual(rec.to_seed, [])
        self.assertEqual(rec.matched, ["FCI:COCOS-RENDIMIENTO-A"])

    def test_over_de_redondeo_en_una_tenencia_ENORME_tampoco(self):
        # u982: 460.993,95 vs 460.993,92. El gap ABSOLUTO es 0,03 — treinta
        # veces el de arriba — y sigue siendo el mismo redondeo de 2 decimales.
        # Este es el caso que un epsilon absoluto más grande NO puede resolver
        # sin volverse peligroso en las tenencias chicas.
        rec = tn.compute_reconcile({"FCI:COCOS-RENDIMIENTO-A": 460993.95},
                                   _snap(_h("FCI:COCOS-RENDIMIENTO-A", 460993.92)))
        self.assertEqual(rec.over, [])
        self.assertEqual(rec.matched, ["FCI:COCOS-RENDIMIENTO-A"])

    # ── lado `to_seed`: la foto redondea PARA ARRIBA ────────────────────────
    def test_seed_de_redondeo_no_existe(self):
        # u1088, BCMMA: Rendi 1.521.743,027008 · foto 1.521.743,03.
        # Antes: COMPRA sintética de 0,002992 — y se aplicaba SOLA.
        rec = tn.compute_reconcile({"BCMMA": 1521743.027008},
                                   _snap(_h("BCMMA", 1521743.03)))
        self.assertEqual(rec.to_seed, [])
        self.assertEqual(rec.over, [])
        self.assertEqual(rec.matched, ["BCMMA"])

    def test_las_dos_direcciones_van_en_el_mismo_arreglo(self):
        # 🔴 El medio arreglo es peor que ninguno: silenciar sólo `over` dejaría
        # las 40 compras sintéticas del otro lado, que son las que se aplican
        # sin preguntar. Las dos puntas, una sola tolerancia.
        arriba = tn.compute_reconcile({"COCOSPPA": 22245589.4508},
                                      _snap(_h("COCOSPPA", 22245589.4500)))
        abajo = tn.compute_reconcile({"COCOSPPA": 22245589.4500},
                                     _snap(_h("COCOSPPA", 22245589.4508)))
        self.assertEqual((arriba.over, arriba.to_seed), ([], []))
        self.assertEqual((abajo.over, abajo.to_seed), ([], []))


class LoQueNOSeSilenciaTest(unittest.TestCase):
    """El otro lado de la moneda: la tolerancia no puede tragarse una señal.

    Los tres casos son los más CHICOS de la muestra de prod en cada categoría —
    o sea, los que más cerca están del corte. Si el corte se mueve para arriba,
    estos son los primeros que se rompen.
    """

    def test_el_over_real_mas_chico_sobrevive(self):
        # u329, SAMI: Rendi 161 · foto 158. Gap relativo 1,86e-2 — 186× el corte.
        rec = tn.compute_reconcile({"SAMI": 161.0},
                                   _snap(_h("SAMI", 158.0, tipo="STOCK")))
        self.assertEqual(rec.over, [("SAMI", 161.0, 158.0)])

    def test_el_seed_real_mas_chico_sobrevive(self):
        # u549, ADBAICA: Rendi 30.061,00 · foto 30.066,5397. Gap 5,5397 sobre
        # 30.066 = 1,84e-4. Es el caso MÁS AJUSTADO de toda la muestra: 1,8×
        # arriba del corte. Si alguien sube `REL_QTY` a 2e-4, este test cae.
        rec = tn.compute_reconcile({"ADBAICA": 30061.0},
                                   _snap(_h("ADBAICA", 30066.5397)))
        self.assertEqual(len(rec.to_seed), 1)
        self.assertAlmostEqual(rec.to_seed[0][1], 5.5397, places=4)

    def test_una_tenencia_MINUSCULA_con_gap_grande_en_relativo_sobrevive(self):
        # u884, FCI:COCOS-AHORRO-DOLARES-A: Rendi 0,0446 · foto 0,0400. El gap
        # ABSOLUTO es 0,0046 —más chico que varios de los que sí se silencian—
        # pero es el 10% de la tenencia. Un umbral absoluto de 0,005 se lo
        # comería; el relativo no. Este es el test que decide entre las dos
        # formas de arreglar el bug.
        rec = tn.compute_reconcile({"FCI:COCOS-AHORRO-DOLARES-A": 0.0446},
                                   _snap(_h("FCI:COCOS-AHORRO-DOLARES-A", 0.0400)))
        self.assertEqual(len(rec.over), 1)
        self.assertEqual(rec.over[0][0], "FCI:COCOS-AHORRO-DOLARES-A")


# ── La SEGUNDA puerta: el re-neteo contra el par, dentro del endpoint ───────
FOTO = "2026-06-30"
MOV = (
    "nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;"
    "instrumento;moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total\n"
    "1;1;02-01-2026;02-01-2026;Compra;Mercado Libre (MELI);ARS;BYMA;10;60,00;600,00;0;0;0;0;600,00\n"
)
# La foto lista el FCI con la precisión del broker (90.000,0037); Rendi,
# sumando las dos particiones del par, tiene 90.000,00 exactos. El instrumento
# va con el ticker entre paréntesis porque es como Cocos lo exporta — sin eso el
# parser descarta la fila y el fixture no llega a probar nada (lo aprendimos
# rompiendo el control negativo).
FOTO_CSV = (
    "instrumento;cantidad;precio;moneda;total\n"
    "Mercado Libre (MELI);10;60,00;ARS;600,00\n"
    "FCI Cocos Ahorro Pesos (COCOSPPA);90000,0037;1,00;ARS;90000,00\n"
)


class ReNeteoContraElParTest(unittest.TestCase):
    """El endpoint tiene su PROPIA comparación, y también fabricaba redondeo.

    `compute_reconcile` mide contra el SUB-BROKER; después el endpoint re-netea
    contra el PAR entero (para no sembrar dos veces un activo cross-currency).
    Ese segundo `> 1e-6` puede parir un `to_seed` que la primera comparación ya
    había descartado — y ahí se aplica solo. Arreglar una sola de las dos
    puertas era el medio arreglo de siempre.

    Escenario: el FCI vive partido entre 'Cocos' (40.000) y 'Cocos · USD'
    (50.000). La partición en pesos ve 40.000 contra una foto de 90.000,0037 →
    `to_seed` de 50.000,0037 → re-neteo contra el par (90.000,00) → 0,0037.
    """

    def setUp(self):
        self.http = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES (?,'x',1)",
            (f"red-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
        pid = conn.execute(
            "INSERT INTO brokers (user_id,name,currency) VALUES (?,'Cocos','ARS')",
            (self.uid,)).lastrowid
        conn.execute("INSERT INTO brokers (user_id,name,currency,parent_broker_id) "
                     "VALUES (?,'Cocos · USD','USD',?)", (self.uid, pid))
        for broker, qty in (("Cocos", 40000.0), ("Cocos · USD", 50000.0)):
            conn.execute(
                "INSERT INTO positions (user_id,broker,asset,is_cash,quantity,buy_price,"
                "invested,asset_type,currency) VALUES (?,?,'COCOSPPA',0,?,1,?,'FUND','ARS')",
                (self.uid, broker, qty, qty))
        conn.commit(); conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        r = self.http.post(
            "/api/imports/preview",
            files={"file": ("mov.csv", io.BytesIO(MOV.encode()), "text/csv")},
            data={"broker": "Cocos", "format": "cocos"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.http.post("/api/imports/confirm",
                           json={"session_id": r.json()["session_id"]}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def _foto(self):
        r = self.http.post(
            "/api/imports/tenencia/preview",
            files={"file": (f"portfolio_report_{FOTO.replace('-','')}.csv",
                            io.BytesIO(FOTO_CSV.encode()), "text/csv")},
            data={"broker": "Cocos", "format": "cocos"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_el_reneteo_no_siembra_el_redondeo(self):
        j = self._foto()
        seed = {x["ticker"]: x["qty"] for x in (j.get("to_seed") or [])}
        self.assertNotIn("COCOSPPA", seed,
                         "el re-neteo contra el par volvió a fabricar el redondeo")

    def test_CONTROL_NEGATIVO_con_la_tolerancia_vieja_si_lo_siembra(self):
        # ⭐ Sin esto, el test de arriba podría estar pasando de casualidad
        # (porque el fixture no llega a la puerta, no porque la puerta esté
        # cerrada). Con la tolerancia de antes —absoluta, 1e-6— el MISMO
        # fixture tiene que producir la compra sintética de 0,0037.
        with mock.patch.object(tn, "tolerancia_qty", lambda a, b, **kw: 1e-6):
            j = self._foto()
        seed = {x["ticker"]: x["qty"] for x in (j.get("to_seed") or [])}
        self.assertIn("COCOSPPA", seed,
                      "el fixture no llega a la puerta: el test de arriba no prueba nada")
        self.assertAlmostEqual(seed["COCOSPPA"], 0.0037, places=4)


if __name__ == "__main__":
    unittest.main()
