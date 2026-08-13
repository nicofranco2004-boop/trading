"""El backfill del blue NO puede borrar el MEP histórico.

POR QUÉ EXISTE ESTE ARCHIVO. Migrando a Postgres hubo que convertir un
`INSERT OR REPLACE` de `_backfill_fx_rates_if_empty` (main.py) a un `ON CONFLICT`
explícito, y esa conversión CAMBIA el comportamiento a propósito. Vale la pena
tenerlo escrito porque es la clase de cosa que se revierte sin querer:

`INSERT OR REPLACE` en SQLite no es un upsert: BORRA la fila y la reinserta. Como
la query nombra sólo (date, blue_venta, source), cada vez que corría sobre una
fecha existente dejaba `mep_venta` en NULL.

Que el borrado era un bug y no una intención se ve en que los otros DOS escritores
de la misma tabla ya protegen la columna:
  · `_persist_blue_for_date` (main.py) → COALESCE(excluded.mep_venta, fx_rates_daily.mep_venta)
  · el cron de snapshots_job.py        → ni la nombra

QUÉ TAN GRAVE ES, sin exagerar. Una versión anterior de este archivo decía que un
mep borrado "no se auto-cura nunca" y que sin mep fx.py "cae al blue". Las dos
cosas se verificaron FALSAS: `_backfill_mep_rates_if_missing` re-rellena por
`WHERE mep_venta IS NULL` (un borrado queda NULL y entra igual), y `fx.py:_lookup`
pone el `IS NOT NULL` adentro del WHERE, así que agarra el MEP del día anterior.
Encima el backfill sólo corre con la tabla vacía. El arreglo vale igual —deja a
este escritor igual que sus dos hermanos, y saca una forma de romper— pero es
defensa en profundidad, no un incendio.

Los tests corren la CONSTANTE de main (`SQL_BACKFILL_FX_BLUE`), no una copia
pegada acá: si alguien edita la consulta en main.py, estos tests se enteran.
Y corren igual contra SQLite y contra Postgres, que es el punto de la migración.
"""
import unittest

import main


class BackfillBlueNoPisaElMepTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.conn.execute("DELETE FROM fx_rates_daily WHERE date LIKE '19%'")
        self.conn.commit()

    def tearDown(self):
        try:
            self.conn.execute("DELETE FROM fx_rates_daily WHERE date LIKE '19%'")
            self.conn.commit()
        finally:
            self.conn.close()

    def _fila(self, fecha):
        r = self.conn.execute(
            "SELECT blue_venta, mep_venta, source, fetched_at FROM fx_rates_daily "
            "WHERE date = ?", (fecha,)).fetchone()
        return None if r is None else {
            "blue": r[0], "mep": r[1], "source": r[2], "fetched_at": r[3]}

    # Fechas de 1900: no chocan con datos reales ni con el backfill de verdad.
    FECHA = "1900-03-04"

    def test_el_mep_sobrevive_al_backfill_del_blue(self):
        """EL TEST QUE IMPORTA. Antes de la conversión, esto dejaba mep en None."""
        self.conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
            "VALUES (?, 100, 950, 'bolsa')", (self.FECHA,))
        self.conn.commit()

        self.conn.executemany(main.SQL_BACKFILL_FX_BLUE,
                              [(self.FECHA, 120.0, "argentinadatos")])
        self.conn.commit()

        f = self._fila(self.FECHA)
        self.assertEqual(f["mep"], 950,
                         "el backfill del blue borró el MEP: fx.py se cae al blue en silencio")
        # …y lo que SÍ tiene que pisar, lo pisa:
        self.assertEqual(f["blue"], 120)
        self.assertEqual(f["source"], "argentinadatos")

    def test_refresca_fetched_at(self):
        """El REPLACE reseteaba fetched_at por su DEFAULT y eso estaba BIEN (la fila
        se reescribe con dato recién traído). El DO UPDATE se quedaría con el viejo
        si no se lo pusiera explícito en el SET, así que hay que fijarlo."""
        self.conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, source, fetched_at) "
            "VALUES (?, 100, 'viejo', '2001-01-01 00:00:00')", (self.FECHA,))
        self.conn.commit()

        self.conn.executemany(main.SQL_BACKFILL_FX_BLUE,
                              [(self.FECHA, 120.0, "argentinadatos")])
        self.conn.commit()

        self.assertNotEqual(self._fila(self.FECHA)["fetched_at"], "2001-01-01 00:00:00",
                            "fetched_at quedó pegado en el valor viejo")

    def test_inserta_cuando_la_fecha_no_estaba(self):
        """El camino normal del backfill: tabla vacía, no hay conflicto."""
        self.assertIsNone(self._fila(self.FECHA))
        self.conn.executemany(main.SQL_BACKFILL_FX_BLUE,
                              [(self.FECHA, 120.0, "argentinadatos")])
        self.conn.commit()
        f = self._fila(self.FECHA)
        self.assertEqual(f["blue"], 120)
        self.assertIsNone(f["mep"], "una fila nueva no tiene MEP: lo llena el otro backfill")

    def test_la_consulta_no_toca_mep_venta(self):
        """Guardarraíl de lectura: que nadie agregue mep_venta al SET sin querer.

        Los tres de arriba lo prueban ejecutando; éste lo dice sobre el texto, que es
        lo que se lee en una revisión de código."""
        sql = " ".join(main.SQL_BACKFILL_FX_BLUE.split()).lower()
        set_ = sql.split("do update set", 1)[1]
        self.assertNotIn("mep_venta", set_,
                         "mep_venta volvió al SET del backfill: pisa el MEP histórico")
        self.assertIn("fetched_at", set_)


if __name__ == "__main__":
    unittest.main()
