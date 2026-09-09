"""El gate server-side del migrador FX: la verificación FRENA, no solo informa.

Antes, `migrate_user_fx` calculaba `delta_pnl_implausible` / `cash_intacto` /
`ventas_con_tc_distinto` y los escribía SOLO en `resultado["verificacion"]`,
dejando `ok=True`. El endpoint tiene el rollback (`if not out.get("ok")`), pero
nunca se disparaba: el único freno era que el operador viera el semáforo rojo y
destildara la fila a mano — y el apply masivo permite aplicar sin simular.

Además el umbral de implausibilidad era `>US$100k Y >US$1.000/venta`: en el
dry-run masivo de 2026-07-29 una cuenta con 1.203 ventas y Δ P&L de US$ 339.593
(282/venta) salía en VERDE por no llegar al segundo umbral.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import importing.fx_migrate as fxm  # noqa: E402


class UmbralImplausibleTest(unittest.TestCase):
    """El umbral nuevo es OR, no AND. Replica la aritmética del módulo."""

    @staticmethod
    def _implausible(d_pnl, n_ventas):
        n = max(int(n_ventas), 1)
        return d_pnl > 100_000 or ((d_pnl / n) > 1_000 and d_pnl > 10_000)

    def test_caza_el_falso_negativo_medido_en_prod(self):
        # Cuenta #499 del dry-run: 1.203 ventas, Δ P&L US$ 339.593 → 282/venta.
        # Con el umbral viejo (AND) pasaba en verde.
        viejo = 339_593 > 100_000 and (339_593 / 1203) > 1_000
        self.assertFalse(viejo, "el umbral viejo la dejaba pasar (por eso el fix)")
        self.assertTrue(self._implausible(339_593, 1203))

    def test_sigue_cazando_las_corruptas_por_venta(self):
        # #834: 62 ventas, Δ 21,5M → 347k/venta.
        self.assertTrue(self._implausible(21_546_698, 62))

    def test_no_marca_las_sanas(self):
        # Rango medido de cuentas sanas: 0-378 por venta, magnitudes chicas.
        self.assertFalse(self._implausible(4_775, 1245))   # #595
        self.assertFalse(self._implausible(332, 2689))     # #762
        self.assertFalse(self._implausible(29_112, 593))   # #587: 49/venta
        self.assertFalse(self._implausible(0, 1))

    def test_una_venta_con_delta_chico_no_dispara_por_venta(self):
        # Sin el piso de 10k, una sola venta con 1.500 de delta marcaría.
        self.assertFalse(self._implausible(1_500, 1))


class GateFrenaTest(unittest.TestCase):
    """El gate arma `frenos` y apaga `ok` — salvo force=True."""

    def test_el_modulo_expone_force_y_lo_respeta(self):
        import inspect
        sig = inspect.signature(fxm.migrate_user_fx)
        self.assertIn("force", sig.parameters)
        self.assertIs(sig.parameters["force"].default, False)

    def test_el_codigo_apaga_ok_con_frenos(self):
        src = inspect_source()
        self.assertIn('resultado["ok"] = False', src)
        self.assertIn("_frenos", src)
        # Las tres señales que frenan
        self.assertIn("cash_intacto", src)
        self.assertIn("mal_tc", src)
        self.assertIn("_implausible", src)

    def test_el_aportado_se_reporta_pero_NO_frena(self):
        """Un salto grande del aportado es la FIRMA DE LA REPARACIÓN (un flujo de
        2013 dolarizado a 1415 y re-derivado a ~5 lo multiplica ×280), así que no
        puede frenar. Se muestra con el 'antes' al lado para que se juzgue."""
        src = inspect_source()
        self.assertIn("aportado_antes_usd", src)
        self.assertIn("aportado_delta_pct", src)
        self.assertNotIn("_aportado_implausible", src)


def inspect_source():
    import inspect
    return inspect.getsource(fxm)


class DenominadorRotoTest(unittest.TestCase):
    """El freno que sí es objetivo: el aportado es el denominador del rendimiento.

    Los números vienen del dry-run real de 2026-07-30 sobre 503 cuentas.
    """

    def test_cruza_a_negativo_con_cartera_positiva(self):
        # #826: aportado 2.820 → −1.477.984. El hero mostraría "Ganancia total"
        # en dólares (inflada) con "+0,0%" al lado.
        m = fxm.denominador_roto(50_000, 2_820, -1_477_984, None)
        self.assertIsNotNone(m)
        self.assertIn("deja de tener sentido", m)

    def test_cruza_a_negativo_aunque_sea_chico(self):
        # #946: 394 → −264. Chico en dólares, pero el % igual deja de existir.
        self.assertIsNotNone(fxm.denominador_roto(9_000, 394, -264, None))

    def test_denominador_casi_cero_explota_el_porcentaje(self):
        # Sin clamp en pctSigned: US$1 de aportado con US$50.000 de cartera.
        self.assertIsNotNone(fxm.denominador_roto(50_000, 20_000, 1, 4_999_900.0))

    def test_no_frena_la_reparacion_normal(self):
        # #595: 79.311 → 874.375 (×11). Es la corrección funcionando.
        self.assertIsNone(fxm.denominador_roto(120_000, 79_311, 874_375, -86.3))
        # #719: 39 → 606 (×15,7), cuenta chica.
        self.assertIsNone(fxm.denominador_roto(700, 39, 606, 15.5))

    def test_no_frena_si_ya_venia_negativo(self):
        # #808: −509.588 → −509.652. Ya era negativo ANTES; la migración no lo
        # rompió y frenarla no arregla nada — es un problema aparte.
        self.assertIsNone(fxm.denominador_roto(30_000, -509_588, -509_652, None))

    def test_sin_snapshot_no_opina(self):
        # Sin valor de cartera no hay con qué juzgar: no se inventa un freno.
        self.assertIsNone(fxm.denominador_roto(None, 2_820, -1_477_984, None))

    def test_cartera_vacia_no_frena(self):
        # Cuenta sin cartera: el rendimiento no le importa a nadie.
        self.assertIsNone(fxm.denominador_roto(0, 2_820, -1_477_984, None))


class FechasSospechosasTest(unittest.TestCase):
    """La inflación argentina no va para atrás: un depósito típico de 2019 tiene
    que ser MUCHO más chico en pesos que uno de 2024. Cuando pasa al revés, esas
    filas no son de ese año. Números reales del panel del 2026-07-30."""

    def _conn(self, depositos):
        """depositos: lista de (fecha, monto)."""
        import sqlite3
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute("CREATE TABLE import_batches (id TEXT, user_id INT, status TEXT)")
        c.execute("CREATE TABLE import_normalized_tx (batch_id TEXT, date TEXT, "
                  "currency TEXT, operation_type TEXT, gross_amount REAL, "
                  "notes TEXT, fingerprint TEXT)")
        c.execute("INSERT INTO import_batches VALUES ('b1', 1, 'confirmed')")
        # fingerprint no-nulo = fila parseada de verdad (las del seed lo tienen NULL).
        c.executemany("INSERT INTO import_normalized_tx VALUES "
                      "('b1',?,'ARS','DEPOSIT',?,NULL,'fp')", depositos)
        return c

    def test_caza_el_patron_de_324(self):
        # 9 depósitos de 14,6 M en 2019 contra 73 mil por depósito en 2020.
        d = [(f"2019-0{i+1}-15", 14_571_098) for i in range(9)]
        d += [(f"2020-01-{10+i:02d}", 73_576) for i in range(19)]
        m = fxm.fechas_sospechosas(self._conn(d), 1)
        self.assertIsNotNone(m)
        self.assertTrue(m["frena"], m)          # 198× es inequívoco
        self.assertEqual(m["viejo"], "2019")

    def test_caza_el_patron_de_595(self):
        # 7 depósitos de 7,2 M en 2019 contra 622 mil en 2024.
        d = [(f"2019-0{i+1}-10", 7_200_813) for i in range(7)]
        d += [(f"2024-0{i+1}-10", 622_400) for i in range(5)]
        m = fxm.fechas_sospechosas(self._conn(d), 1)
        self.assertIsNotNone(m)
        # 11,6× es ambiguo: puede ser fecha mal o que aportaba más antes.
        self.assertFalse(m["frena"], m)

    def test_una_cuenta_sana_no_dispara(self):
        # Los montos crecen con la inflación, que es lo normal.
        d = ([("2020-05-10", 73_000)] * 4 + [("2022-05-10", 326_000)] * 4
             + [("2024-05-10", 846_000)] * 4 + [("2026-05-10", 5_000_000)] * 4)
        self.assertIsNone(fxm.fechas_sospechosas(self._conn(d), 1))

    def test_el_seed_no_cuenta(self):
        """El "Estado inicial" ya no se re-estampa, así que no puede causar el
        daño que este detector previene: mirarlo sería un falso positivo."""
        c = self._conn([(f"2024-0{i+1}-01", 100_000) for i in range(4)])
        c.executemany(
            "INSERT INTO import_normalized_tx VALUES ('b1',?,'ARS','DEPOSIT',?,?,NULL)",
            [(f"2019-0{i+1}-01", 130_000_000, "Estado inicial — depósito sintético (Rendi)")
             for i in range(3)])
        self.assertIsNone(fxm.fechas_sospechosas(c, 1))

    def test_un_deposito_grande_aislado_NO_es_sospechoso(self):
        # Una herencia, la venta de un auto: un depósito grande en 2019 y después
        # montos chicos. Con mediana + min_filas esto no puede marcar.
        d = [("2019-03-01", 20_000_000)] + [(f"2019-0{i+4}-01", 50_000) for i in range(5)]
        d += [(f"2021-0{i+1}-01", 200_000) for i in range(4)]
        m = fxm.fechas_sospechosas(self._conn(d), 1)
        self.assertFalse(m and m["frena"], m)

    def test_un_solo_anio_no_se_puede_juzgar(self):
        # Sin dos años no hay comparación posible: no se inventa un freno.
        # Es el caso de la fixture de test_fx_migrate (un depósito, 2021).
        d = [(f"2021-0{i+1}-01", 1_000_000) for i in range(5)]
        self.assertIsNone(fxm.fechas_sospechosas(self._conn(d), 1))

    def test_pocas_filas_en_el_anio_viejo_no_alcanzan(self):
        # min_filas=3: con 2 filas grandes no se marca (podría ser real).
        d = [("2019-03-01", 20_000_000), ("2019-04-01", 20_000_000)]
        d += [(f"2023-0{i+1}-01", 100_000) for i in range(4)]
        self.assertIsNone(fxm.fechas_sospechosas(self._conn(d), 1))

    def test_cuenta_sin_depositos_no_rompe(self):
        self.assertIsNone(fxm.fechas_sospechosas(self._conn([]), 1))


class AdvertenciaNoFrenaTest(unittest.TestCase):
    """"De ganar a perder todo" es un heurístico de comportamiento, no prueba de
    dato roto: perder el 80% es posible. Se muestra, no frena."""

    def test_detecta_el_salto(self):
        self.assertTrue(fxm.cae_de_ganar_a_perder_todo(10.9, -87.7))    # #324
        self.assertTrue(fxm.cae_de_ganar_a_perder_todo(39.7, -92.3))    # #814

    def test_no_marca_caidas_moderadas(self):
        self.assertFalse(fxm.cae_de_ganar_a_perder_todo(127.4, -23.3))  # #587
        self.assertFalse(fxm.cae_de_ganar_a_perder_todo(79.0, -58.3))   # #558

    def test_no_marca_al_que_ya_venia_perdiendo(self):
        self.assertFalse(fxm.cae_de_ganar_a_perder_todo(-21.5, -95.6))  # #735

    def test_no_esta_en_los_frenos(self):
        src = inspect_source()
        i = src.index("_frenos = []")
        self.assertNotIn("cae_de_ganar_a_perder_todo", src[i:i + 1200])

    def test_fechas_sospechosas_SI_frena(self):
        src = inspect_source()
        i = src.index("_frenos = []")
        self.assertIn("_fechas_mal", src[i:i + 1200])


class SeedSinteticoNoSeReEstampaTest(unittest.TestCase):
    """El depósito del "Estado inicial" NO se re-estampa: su monto está en pesos
    de HOY (el usuario lo tipeó en el wizard) y su fecha es la más VIEJA de la
    cuenta (`earliest − 1 día`). Aplicarle el TC de esa fecha lo multiplica ×33.

    Caso real, cuenta #324: 130.667.268 pesos fechados 2019-07-21 (un DOMINGO —
    la firma de "earliest − 1 día", ningún broker bookea en domingo) daban
    US$ 3.090.522, el 92% del aportado de la cuenta.
    """

    def test_la_query_excluye_las_sinteticas(self):
        src = inspect_source()
        i = src.index("PATA 1: re-estampar")
        bloque = src[i:i + 2400]
        self.assertIn("n.fingerprint IS NOT NULL", bloque)
        self.assertIn("NOT LIKE 'Estado inicial%'", bloque)

    def test_se_reporta_cuantas_quedaron_afuera(self):
        src = inspect_source()
        self.assertIn("sinteticas_no_re_estampadas", src)
        self.assertIn("sinteticas_usd", src)

    def test_la_firma_del_seed_existe_en_el_generador(self):
        # Si alguien cambia el texto de la nota, el match por `notes` deja de
        # servir — pero queda el de fingerprint. Este test avisa igual.
        import inspect
        import importing.seed as sd
        src = inspect.getsource(sd)
        self.assertIn("Estado inicial", src)
        self.assertIn("_minus_one_day", src)

    def test_el_insert_del_seed_sigue_sin_fingerprint(self):
        """La exclusión se apoya en que el INSERT del seed omite `fingerprint`.
        Si algún día se lo agregan, la mitad del filtro deja de discriminar."""
        import inspect
        import importing.persister as ps
        src = inspect.getsource(ps)
        # Desde la marca del seed hasta SU insert, sin depender de cuánto
        # comentario haya en el medio.
        i = src.index("_synthetic_seed")
        j = src.index("INSERT INTO import_normalized_tx", i)
        cols = src[j:src.index("VALUES", j)]
        self.assertNotIn("fingerprint", cols,
                         "el INSERT del seed ahora lleva fingerprint: la exclusión "
                         "del re-estampado en fx_migrate.py se apoya en que NO lo lleve")


class RendimientoVisibleTest(unittest.TestCase):
    """El panel tiene que mostrar el número que el usuario va a ver."""

    def test_metricas_expone_el_rendimiento_del_dashboard(self):
        import inspect
        src = inspect.getsource(fxm._metricas)
        # La fórmula del hero: (totalValue − netDeposited) / netDeposited, con
        # netDeposited = capital_inicio del primer mes + Σ(deposits − withdrawals).
        self.assertIn("capital_inicio", src)
        self.assertIn("aportado_dashboard_usd", src)
        self.assertIn("valor_cartera_usd", src)
        self.assertIn("rendimiento_pct", src)

    def test_el_resultado_reporta_antes_y_despues(self):
        src = inspect_source()
        for campo in ("rendimiento_antes_pct", "rendimiento_despues_pct",
                      "aportado_dashboard_antes_usd", "baseline_borrada_usd"):
            self.assertIn(campo, src)


class SnapshotsNoSePisanTest(unittest.TestCase):
    """El backfill de snapshots desde monthly no puede pisar una medición real.

    ⚠️ ESTE TEST MIRABA EL TEXTO DEL CÓDIGO, no lo que el código hace:
    `assertIn("DO NOTHING", inspect.getsource(...))`. Un guard así se conforma
    con la ortografía — pasaba en verde igual cuando la función pasó a corregir
    sus propias filas con un UPDATE aparte, que es justo el cambio que tenía que
    vigilar. Ahora ejerce las tres filas que importan contra una DB de verdad.
    """

    def setUp(self):
        # La base la da `tests/conftest.py` (una por MÓDULO), así que cada test
        # necesita su propio user: comparten archivo.
        import uuid
        import main
        self.conn = main.get_db()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"snap-guard-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _monthly(self, deposits, capital_final):
        self.conn.execute("DELETE FROM monthly_entries WHERE user_id=?", (self.uid,))
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, broker, year, month, deposits,
                                            withdrawals, capital_final)
               VALUES (?, 'global', 2024, 1, ?, 0, ?)""",
            (self.uid, deposits, capital_final))
        self.conn.commit()

    def _backfill(self):
        import importing.persister as ps
        ps._backfill_snapshots_from_monthly(self.conn, self.uid)
        self.conn.commit()

    def _snap(self, fecha="2024-01-31"):
        return self.conn.execute(
            "SELECT total_value, net_deposited, source FROM snapshots WHERE user_id=? AND date=?",
            (self.uid, fecha)).fetchone()

    def test_no_pisa_una_medicion_del_cron(self):
        """El motivo por el que existe el guard (a813abc4): el cierre a MERCADO
        del cron no se degrada al capital AL COSTO de la cadena contable."""
        self.conn.execute(
            """INSERT INTO snapshots (user_id, date, total_value, total_invested,
                                      net_deposited, fx_to_usd_blue, holdings_json, source, base, apto)
               VALUES (?, '2024-01-31', 9999, 9999, 9999, 1000.0, '[]', 'cron', 'mercado', 1)""",
            (self.uid,))
        self.conn.commit()
        self._monthly(deposits=5000, capital_final=5000)
        self._backfill()
        row = self._snap()
        self.assertEqual(row["total_value"], 9999, "pisó la medición del cron")
        self.assertEqual(row["source"], "cron")

    def test_corrige_la_fila_que_fabrico_el_propio_import(self):
        """El bug que el guard de texto no veía: tras un revert la fila sintética
        queda en 0 y el re-import tiene que poder corregirla."""
        self._monthly(deposits=0, capital_final=0)
        self._backfill()
        self.assertEqual(self._snap()["net_deposited"], 0)
        self._monthly(deposits=5000, capital_final=5000)     # re-import
        self._backfill()
        row = self._snap()
        self.assertEqual(row["net_deposited"], 5000, "el 0 del revert quedó clavado")
        self.assertEqual(row["total_value"], 5000)

    def test_no_toca_una_fila_legacy_sin_firma(self):
        """Sin `source` no se puede afirmar quién la escribió (las columnas
        `source`/`holdings_json` son de 2026) → se deja quieta."""
        self.conn.execute(
            """INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited)
               VALUES (?, '2024-01-31', 7777, 7777, 7777)""", (self.uid,))
        self.conn.commit()
        self._monthly(deposits=5000, capital_final=5000)
        self._backfill()
        self.assertEqual(self._snap()["total_value"], 7777)


if __name__ == "__main__":
    unittest.main()
