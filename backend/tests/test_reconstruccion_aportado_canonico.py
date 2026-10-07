"""Cada foto reconstruida describe UNA contabilidad: su aportado es el canónico de
su mes y su valor sale de la misma contabilidad.

Después de cada import, `_reconstruir_mtm` arma una foto por mes a precio de
mercado (`scripts/backfill_historical_mtm.py`). Cada foto lleva dos números que
el Dashboard resta para sacar el resultado: lo que valía la cartera y lo que la
persona había aportado. El aportado lo calculaba con SU PROPIA copia de
"arranque + depósitos − retiros", leída al FINAL de la corrida, mientras que el
valor de cada mes se lee al valuarlo, minutos antes (sale a buscar precios a
Yahoo con 8 s de tope por activo).

Medido con esta misma cuenta de laboratorio:
  · Recorrido normal: la copia y `twr.netdep_canonico` dan lo mismo en los 3
    meses con foto. Los meses sin depósitos ni retiros (abril, mayo, junio y
    agosto) no tienen fila en la contabilidad y el reconstructor tampoco les
    armaba foto, así que el `get(mes, 0.0)` de la copia no se alcanzaba nunca.
    (Desde 2026-10-07 esos meses SÍ tienen foto —sin ella la curva se partía,
    ver test_reconstruccion_meses_sin_fila.py— y su aportado es el canónico,
    que arrastra el último valor: es la razón por la que la copia no podía
    volver.)
  · Si la persona borra el depósito de julio MIENTRAS la reconstrucción corre,
    la fila de julio desaparece de la contabilidad entre las dos lecturas y la
    copia estampaba aportado **0** en la foto de julio: el servidor quedaba con
    +US$ 15.800 de "resultado" en un mes que ganó US$ 800.
  · Si el borrado llega ANTES de valuar ese mes, la foto se escribía con valor
    **0** (la consulta del mes ya no encontraba fila y el costo daba 0).
  · Si el mes sobrevive al borrado (tenía otro depósito), la copia estampaba el
    aportado de DESPUÉS sobre el valor de ANTES: +US$ 5.800 y −US$ 4.600 en el
    Dashboard para meses que ganaron 800 y 400.
  · Leer el aportado junto con el valor arregla el resultado de la foto, pero
    no alcanza: la foto queda describiendo la contabilidad VIEJA, y la base del
    libro del asesor (el mayor aportado de la historia) toma el depósito borrado
    (12 % → 8 %). Por eso, si la contabilidad cambió durante la corrida, la
    reconstrucción vuelve a empezar antes de escribir.

Lo que se fija acá entra por las puertas reales: `POST /api/imports/preview` +
`/confirm` (que dispara la reconstrucción en su hilo, como en producción) y
`DELETE /api/movements/…`. Lo único reemplazado es lo que sale a internet:
Yahoo (precios fijos y sabidos, así el resultado correcto de cada mes se puede
escribir a mano) y la lista de bonos de data912 (vacía: AAPL no es un bono, y
sin red el confirm tarda 17 s en desistir).
"""
import inspect
import io
import os
import sys
import time
import unittest
import uuid
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import twr  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"
# AAPL a fin de cada mes: marzo de 2025 200, julio 240, septiembre 260, y sigue
# subiendo 10 por mes (así todo mes cerrado, también los de 2026, tiene precio).
PRECIOS = {f"{2025 + (n - 1) // 12}-{(n - 1) % 12 + 1:02d}": 200.0 + 10 * (n - 3)
           for n in range(1, 49)}
# Lo que el Dashboard dibuja (frontend/src/utils/evolution.js, ACEPTA_LINEA).
ACEPTA_LINEA = ("medicion", "reconstruido", "intradia")


class _Cuenta(unittest.TestCase):
    """Una cuenta en IBKR (dólares) que importa su historia por la app."""

    def setUp(self):
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"aportado-{uuid.uuid4().hex[:10]}@rendi.test", "x")).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "IBKR", "USDT"))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.http = TestClient(main.app)
        _data912 = mock.patch.object(main, "_fetch_data912_bonds", return_value={})
        _data912.start()
        self.addCleanup(_data912.stop)
        self._fetch_orig = bf._fetch_monthly_close
        bf._HIST_CACHE.clear()
        bf._fetch_monthly_close = self._precios
        self._consultas = 0
        self._borrar = None          # (n° de consulta de precios, tipo, fecha)
        self._errores = []

    def tearDown(self):
        bf._fetch_monthly_close = self._fetch_orig
        bf._HIST_CACHE.clear()

    def _precios(self, price_key, start_iso):
        """Yahoo de mentira. Si el test lo pide, en la consulta N la persona borra
        un movimiento desde Movimientos — o sea, mientras la reconstrucción corre."""
        self._consultas += 1
        if self._borrar and self._consultas == self._borrar[0]:
            try:
                r = self.http.delete(
                    f"/api/movements/tx-{self._tx(*self._borrar[1:])}", headers=self.h)
                if r.status_code != 200:
                    self._errores.append(f"DELETE → {r.status_code}: {r.text}")
            except Exception as ex:          # el hilo se traga las excepciones
                self._errores.append(repr(ex))
        return dict(PRECIOS)

    def _tx(self, op, fecha):
        conn = main.get_db()
        try:
            return conn.execute(
                "SELECT n.id FROM import_normalized_tx n JOIN import_batches b "
                "ON b.id=n.batch_id WHERE b.user_id=? AND n.operation_type=? AND n.date=? "
                "AND n.excluded_at IS NULL", (self.uid, op, fecha)).fetchone()["id"]
        finally:
            conn.close()

    def _importar(self, *filas):
        """Sube el CSV y confirma. El confirm lanza la reconstrucción en un hilo
        (`_reconstruir_mtm_post_import`); se espera a que termine."""
        csv = (HDR + "".join(f + "\n" for f in filas)).encode()
        p = self.http.post("/api/imports/preview",
                           files=[("files", ("mov.csv", io.BytesIO(csv), "text/csv"))],
                           data={"format": "rendi_generic", "broker": "IBKR"}, headers=self.h)
        self.assertEqual(p.status_code, 200, p.text)
        c = self.http.post("/api/imports/confirm",
                           json={"session_id": p.json()["session_id"],
                                 "skip_row_indices": [], "aprobar_tickers": []},
                           headers=self.h)
        self.assertEqual(c.status_code, 200, c.text)
        self.assertEqual((c.json().get("mtm_reconstruccion") or {}).get("reconstruida"),
                         "en_curso", c.text)
        limite = time.time() + 60
        while time.time() < limite:
            with main._MTM_RUNNING_LOCK:
                if self.uid not in main._MTM_RUNNING:
                    break
            time.sleep(0.02)
        else:
            self.fail("la reconstrucción no terminó en 60 s")
        self.assertEqual(self._errores, [])

    def _fotos(self):
        """Lo que recibe el Dashboard (`GET /api/snapshots`) y que dibuja."""
        r = self.http.get("/api/snapshots", params={"days": 3650}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return [f for f in r.json() if f.get("clase") in ACEPTA_LINEA]

    @staticmethod
    def _resultados(fotos):
        """El chip del Dashboard entre fotos seguidas: Δ(valor − aportado)."""
        return [(a["date"], b["date"],
                 round((b["total_value"] - b["net_deposited"])
                       - (a["total_value"] - a["net_deposited"]), 2))
                for a, b in zip(fotos, fotos[1:])]

    def _canon(self):
        conn = main.get_db()
        try:
            return twr.netdep_canonico(conn, self.uid)
        finally:
            conn.close()

    def _invariantes(self, fotos):
        """Lo que vale para TODA foto reconstruida, también las de 2026 que no se
        escriben a mano: (a) su aportado es el canónico de su fecha, el de la
        contabilidad que quedó, y nunca 0; (b) ninguna vale 0; y no falta ningún
        mes entre la primera y la última cerrada (sin eso la curva se parte)."""
        canon = self._canon()
        for f in fotos:
            self.assertEqual(f["net_deposited"], canon(f["date"]), f["date"])
            self.assertGreater(f["net_deposited"], 0, f["date"])
            self.assertGreater(f["total_value"], 0, f["date"])
        meses = [f["date"][:7] for f in fotos]
        y, m = int(meses[0][:4]), int(meses[0][5:])
        seguidos = []
        while f"{y}-{m:02d}" <= meses[-1]:
            seguidos.append(f"{y}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        self.assertEqual(meses, seguidos)

    @staticmethod
    def _de_2025(fotos):
        return [(f["date"], f["total_value"], f["net_deposited"])
                for f in fotos if f["date"] < "2026"]


class AportadoDeLaFotoReconstruida(_Cuenta):

    def test_cada_foto_lleva_el_aportado_canonico_de_su_mes(self):
        self._importar(
            "2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
            "2025-03-04,COMPRA,IBKR,AAPL,20,200,4000,,,0,USD,",
            # abril, mayo y junio: nada. Agosto: sólo una compra (no es un flujo).
            "2025-07-10,DEPOSITO,IBKR,,,,5000,,,0,USD,",
            "2025-08-05,COMPRA,IBKR,AAPL,5,250,1250,,,0,USD,",
            "2025-09-15,RETIRO,IBKR,,,,1000,,,0,USD,",
        )
        fotos = self._fotos()
        self.assertEqual({f["clase"] for f in fotos}, {"reconstruido"})
        # …y es exactamente la cuenta canónica, la del cron y la curva.
        self._invariantes(fotos)
        # Lo que la persona puso a cada fin de mes, escrito a mano. Abril, mayo,
        # junio y agosto no tienen fila en la contabilidad: su aportado es el que
        # se ARRASTRA del último mes, no cero (la copia vieja estampaba 0).
        # Efectivo 6.000 hasta junio, 11.000 en julio, 9.750 tras la compra de
        # agosto y 8.750 desde el retiro; 20 AAPL hasta julio y 25 desde agosto.
        self.assertEqual(self._de_2025(fotos), [
            ("2025-03-31", 10000.0, 10000.0), ("2025-04-30", 10200.0, 10000.0),
            ("2025-05-31", 10400.0, 10000.0), ("2025-06-30", 10600.0, 10000.0),
            ("2025-07-31", 15800.0, 15000.0), ("2025-08-31", 16000.0, 15000.0),
            ("2025-09-30", 15250.0, 14000.0), ("2025-10-31", 15500.0, 14000.0),
            ("2025-11-30", 15750.0, 14000.0), ("2025-12-31", 16000.0, 14000.0)])

    def test_borrar_un_deposito_mientras_reconstruye_deja_la_contabilidad_final(self):
        # Julio tiene DOS depósitos: borrar uno deja la fila de julio viva. Una
        # consulta de precios por mes desde marzo: julio es la 5. El borrado
        # llega en la 6, con julio ya valuado con los US$ 5.000 adentro.
        self._borrar = (6, "DEPOSIT", "2025-07-10")
        self._importar(
            "2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
            "2025-03-04,COMPRA,IBKR,AAPL,20,200,4000,,,0,USD,",
            "2025-07-10,DEPOSITO,IBKR,,,,5000,,,0,USD,",
            "2025-07-20,DEPOSITO,IBKR,,,,300,,,0,USD,",
            "2025-09-15,RETIRO,IBKR,,,,1000,,,0,USD,",
        )
        fotos = self._fotos()
        self._invariantes(fotos)
        # Cada foto describe la contabilidad DE DESPUÉS del borrado: cash + 20 AAPL.
        #   marzo:      6.000 + 20×200 = 10.000   aportado 10.000
        #   julio:      6.300 + 20×240 = 11.100   aportado 10.300
        #   septiembre: 5.300 + 20×260 = 10.500   aportado  9.300
        self.assertEqual(self._de_2025(fotos), [
            ("2025-03-31", 10000.0, 10000.0), ("2025-04-30", 10200.0, 10000.0),
            ("2025-05-31", 10400.0, 10000.0), ("2025-06-30", 10600.0, 10000.0),
            ("2025-07-31", 11100.0, 10300.0), ("2025-08-31", 11300.0, 10300.0),
            ("2025-09-30", 10500.0, 9300.0), ("2025-10-31", 10700.0, 9300.0),
            ("2025-11-30", 10900.0, 9300.0), ("2025-12-31", 11100.0, 9300.0)])
        # (c) Lo que ganó de verdad: 20 AAPL que suben 10 por mes, +200 cada mes
        # (de marzo a septiembre, +1.200). Antes se publicaba +5.800 y −4.600
        # (valor de antes del borrado, aportado de después).
        self.assertEqual({r[2] for r in self._resultados(fotos)}, {200.0})
        self.assertEqual(sum(r[2] for r in self._resultados(fotos)
                             if r[1] <= "2025-09-30"), 1200.0)
        # Y la base del libro del asesor (el mayor aportado de la historia) no
        # guarda el depósito borrado.
        conn = main.get_db()
        try:
            self.assertEqual(main._max_net_deposited(conn, [self.uid])[self.uid], 10300.0)
        finally:
            conn.close()

    def _borrar_el_unico_deposito_de_julio_en(self, consulta):
        """Julio tiene un solo flujo: borrarlo hace desaparecer la fila del mes."""
        self._borrar = (consulta, "DEPOSIT", "2025-07-10")
        self._importar(
            "2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
            "2025-03-04,COMPRA,IBKR,AAPL,20,200,4000,,,0,USD,",
            "2025-07-10,DEPOSITO,IBKR,,,,5000,,,0,USD,",
            "2025-09-15,RETIRO,IBKR,,,,1000,,,0,USD,",
        )
        fotos = self._fotos()
        self._invariantes(fotos)
        # Ni foto que vale 0, ni aportado 0, ni la foto de julio con el depósito
        # borrado adentro: julio queda como los meses que la cadena saltea, que
        # arrastran la contabilidad de marzo (efectivo 6.000, aportado 10.000).
        self.assertEqual(self._de_2025(fotos), [
            ("2025-03-31", 10000.0, 10000.0), ("2025-04-30", 10200.0, 10000.0),
            ("2025-05-31", 10400.0, 10000.0), ("2025-06-30", 10600.0, 10000.0),
            ("2025-07-31", 10800.0, 10000.0), ("2025-08-31", 11000.0, 10000.0),
            ("2025-09-30", 10200.0, 9000.0), ("2025-10-31", 10400.0, 9000.0),
            ("2025-11-30", 10600.0, 9000.0), ("2025-12-31", 10800.0, 9000.0)])
        # (c) +200 por mes; de marzo a septiembre, 20 × (260 − 200) = 1.200.
        self.assertEqual({r[2] for r in self._resultados(fotos)}, {200.0})
        self.assertEqual(sum(r[2] for r in self._resultados(fotos)
                             if r[1] <= "2025-09-30"), 1200.0)

    def test_el_mes_desaparece_antes_de_valuarlo(self):
        # Antes: foto de julio con valor 0 y aportado 0. (Una consulta de precios
        # por mes desde marzo: julio es la 5; la 2 es abril.)
        self._borrar_el_unico_deposito_de_julio_en(2)

    def test_el_mes_desaparece_despues_de_valuarlo(self):
        # Antes: foto de julio con el valor de antes del borrado y aportado 0.
        self._borrar_el_unico_deposito_de_julio_en(6)

    def test_si_la_contabilidad_no_para_de_cambiar_no_escribe_nada(self):
        """Si cambia en cada pasada, no hay una contabilidad que describir: la
        reconstrucción se abandona y las fotos quedan como estaban."""
        self._importar(
            "2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
            "2025-03-04,COMPRA,IBKR,AAPL,20,200,4000,,,0,USD,",
            "2025-07-10,DEPOSITO,IBKR,,,,5000,,,0,USD,",
        )
        antes = self._fotos()

        def _cambia_siempre(price_key, start_iso):
            c = main.get_db()
            try:
                c.execute("UPDATE monthly_entries SET deposits = deposits + 1 "
                          "WHERE user_id=? AND broker='global' AND year=2025 AND month=7",
                          (self.uid,))
                c.commit()
            finally:
                c.close()
            return dict(PRECIOS)
        bf._fetch_monthly_close = _cambia_siempre
        r = main._reconstruir_mtm(self.uid)        # lo que corre el hilo del import
        self.assertFalse(r["reconstruida"], r)
        self.assertIn("contabilidad", r.get("motivo") or "")
        self.assertEqual(self._fotos(), antes)


class UnaSolaCuentaDelAportado(unittest.TestCase):
    def test_el_reconstructor_no_tiene_su_propia_copia(self):
        """La tercera copia de "arranque + depósitos − retiros" vivía acá. La del
        persister ya se había unificado (`fix(borrar)`, 2026-10-02). Si vuelve a
        aparecer una consulta propia a la contabilidad para el aportado, vuelven a
        ser dos cuentas que tarde o temprano dicen cosas distintas."""
        persistir = inspect.getsource(bf._persist_mtm_snapshots)
        self.assertNotIn("FROM monthly_entries", persistir)
        self.assertIn("netdep_canonico", inspect.getsource(bf.backfill_user))


if __name__ == "__main__":
    unittest.main()
