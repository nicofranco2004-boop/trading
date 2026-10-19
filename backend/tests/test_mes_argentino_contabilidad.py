"""El mes en curso de la contabilidad es el ARGENTINO, también de 21 a 24 h.

EL BUG (relevamiento de relojes, 18/10/2026). `_rollover_to_current_month`,
`sync_unrealized` y `_repair_monthly_chain` decidían "el mes de hoy" con
`now = datetime.utcnow()` + `now.year, now.month`. El último día de cada mes, de
21 a 24 h argentinas, UTC ya es el mes siguiente:

  · el rollover creaba la fila del mes que viene,
  · el sync escribía la ganancia no realizada ahí y ponía en 0 la del mes en curso,
  · la cadena trataba al mes en curso como cerrado.

Mientras tanto Reportes (`is_period_current`, que ya era argentino desde F3)
seguía mostrando octubre como mes en curso: octubre sin su ganancia. Medido con
un reloj simulado el 31/10/2026 a las 22:30: fila de noviembre con los 250 de no
realizado y octubre en 0. A las 20:30, una sola fila de octubre con los 250.

POR QUÉ SE CONGELAN DOS RELOJES. `fechas.datetime` es el calendario de la app y
`main.datetime` es el que usaban estas tres funciones. Se congelan los dos en el
mismo instante, como pasa en producción: si alguien vuelve a escribir
`datetime.utcnow()` en `main`, el test ve noviembre y se pone rojo. Congelar sólo
`fechas` dejaría pasar justo esa regresión.

Corre con: cd backend && python3 -m pytest tests/test_mes_argentino_contabilidad.py
"""
import unittest
from datetime import datetime
from unittest.mock import patch

import main
import fechas


def _reloj_en(instante_utc):
    class _Reloj(datetime):
        @classmethod
        def utcnow(cls):
            return cls(instante_utc.year, instante_utc.month, instante_utc.day,
                       instante_utc.hour, instante_utc.minute)

        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return cls.utcnow().replace(tzinfo=tz)
            return cls.utcnow()     # el proceso de Railway corre en UTC
    return _Reloj


# 01:30 UTC del 1/11/2026 = 22:30 ART del 31/10/2026.
NOCHE_DEL_31_10 = datetime(2026, 11, 1, 1, 30)
# 23:30 UTC del 31/10/2026 = 20:30 ART: control, los dos relojes coinciden.
TARDE_DEL_31_10 = datetime(2026, 10, 31, 23, 30)


class ElMesEnCursoEsElArgentino(unittest.TestCase):
    BROKER = "MesART"

    def setUp(self):
        conn = main.get_db()
        for t in ("operations", "positions", "monthly_entries", "brokers", "users"):
            try:
                conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = conn.execute(
            "INSERT INTO users (email,password_hash,approved,email_verified) "
            "VALUES ('mes-art@rendi.test','x',1,1)").lastrowid
        conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,'USDT')",
                     (self.uid, self.BROKER))
        conn.execute(
            """INSERT INTO monthly_entries
               (user_id,year,month,broker,deposits,withdrawals,pnl_realized,
                pnl_unrealized,capital_inicio,capital_final)
               VALUES (?,2026,10,?,0,0,0,0,1000,1000)""",
            (self.uid, self.BROKER))
        conn.commit()
        conn.close()

    def _correr_a_las(self, instante_utc):
        reloj = _reloj_en(instante_utc)
        with patch.object(fechas, "datetime", reloj), patch.object(main, "datetime", reloj):
            conn = main.get_db()
            creadas = main._rollover_to_current_month(conn, self.uid, self.BROKER)
            conn.commit()
            conn.close()
            main.sync_unrealized(
                main.SyncUnrealizedIn(broker=self.BROKER, pnl_unrealized_usd=250.0),
                uid=self.uid)
            conn = main.get_db()
            main._repair_monthly_chain(conn, self.uid, self.BROKER)
            conn.commit()
            filas = [(r["year"], r["month"], r["pnl_unrealized"], r["capital_final"])
                     for r in conn.execute(
                         "SELECT year, month, pnl_unrealized, capital_final "
                         "FROM monthly_entries WHERE user_id=? ORDER BY year, month",
                         (self.uid,))]
            conn.close()
        return creadas, filas

    def test_a_las_2230_del_31_de_octubre_la_ganancia_sigue_en_octubre(self):
        creadas, filas = self._correr_a_las(NOCHE_DEL_31_10)
        self.assertEqual(creadas, 0, "no se crea la fila de noviembre antes de tiempo")
        self.assertEqual(filas, [(2026, 10, 250.0, 1250.0)])

    def test_control_a_las_2030_da_lo_mismo(self):
        creadas, filas = self._correr_a_las(TARDE_DEL_31_10)
        self.assertEqual(creadas, 0)
        self.assertEqual(filas, [(2026, 10, 250.0, 1250.0)])

    def test_reportes_y_la_contabilidad_coinciden_en_cual_es_el_mes_en_curso(self):
        """El que muestra y el que escribe no pueden discrepar: es el defecto entero."""
        from reporting.builder import is_period_current
        with patch.object(fechas, "datetime", _reloj_en(NOCHE_DEL_31_10)):
            self.assertTrue(is_period_current("month", "2026-10-01", "2026-10-31"))
        _, filas = self._correr_a_las(NOCHE_DEL_31_10)
        self.assertEqual([(a, m) for a, m, unr, _ in filas if unr], [(2026, 10)])


class LaFotoDelImportNoSeAdelanta(unittest.TestCase):
    """`_backfill_snapshots_from_monthly` fabrica la foto de fin de mes (al costo,
    sin ganancia no realizada) de los meses que ya terminaron. Con `utcnow()`, el
    penúltimo día de 21 a 24 h ya era el último y la escribía un día antes; por
    `MAX(date)` esa foto pasaba a ser "la última" de la cuenta."""

    def test_a_las_2230_del_30_de_octubre_no_hay_foto_del_31(self):
        from importing.persister import _backfill_snapshots_from_monthly
        conn = main.get_db()
        uid = conn.execute(
            "INSERT INTO users (email,password_hash,approved,email_verified) "
            "VALUES ('foto-art@rendi.test','x',1,1)").lastrowid
        conn.execute(
            """INSERT INTO monthly_entries
               (user_id,year,month,broker,deposits,withdrawals,pnl_realized,
                pnl_unrealized,capital_inicio,capital_final)
               VALUES (?,2026,10,'global',0,0,0,0,1000,1000)""", (uid,))
        conn.commit()
        # 01:30 UTC del 31/10 = 22:30 ART del 30/10.
        with patch.object(fechas, "datetime", _reloj_en(datetime(2026, 10, 31, 1, 30))):
            _backfill_snapshots_from_monthly(conn, uid)
        conn.commit()
        fechas_fotos = [r["date"] for r in conn.execute(
            "SELECT date FROM snapshots WHERE user_id=?", (uid,))]
        conn.close()
        self.assertEqual(fechas_fotos, [])


if __name__ == "__main__":
    unittest.main()
