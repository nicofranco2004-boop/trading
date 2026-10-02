"""Los eventos guardados se leen en UN solo lugar: `eventos_guardados.py`.

CONTEXTO (2026-10-01). "Los eventos de estos tickers de hoy a N días" estaba
escrito siete veces. Una copia leía la tabla `events`, que no existe, y las
tarjetas "Earnings de X" / "Dividendo de X" del inicio no aparecieron nunca. Las
tres copias de Rendi AI contaban "hoy" con el reloj del servidor (UTC): de 21 a
24 h de Buenos Aires la IA ya estaba en mañana y no veía el evento de hoy que la
pantalla sí mostraba.

QUÉ VERIFICA
  1. Que la lectura cuente desde el hoy ARGENTINO, con el reloj congelado en el
     caso que lo motivó (22:00 ART = 01:00 UTC del día siguiente).
  2. Que nadie vuelva a escribir la consulta a mano: ningún módulo de producción,
     salvo el dueño, filtra `financial_events` por un RANGO de fechas
     (`event_date >=`). Los mails que preguntan por UN día (`event_date = ?`) no
     son una copia: preguntan otra cosa.
"""
import json
import os
import re
import sqlite3
import unittest
from datetime import date, datetime
from unittest.mock import patch

import eventos_guardados as eg

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUENIO = "eventos_guardados.py"
EXCLUIDAS = ("tests", "scripts", "backups", "__pycache__", "venv", ".venv")
# Una LECTURA (SELECT … FROM financial_events … event_date >=). El borrado de
# fechas que Yahoo movió (_buscar_y_guardar_eventos) no es una lectura.
LECTURA_POR_RANGO = re.compile(r"SELECT\b[^;]{0,300}?FROM financial_events[^;]{0,300}?event_date\s*>=", re.S)


def _base():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE financial_events (
        id INTEGER PRIMARY KEY, ticker TEXT, event_type TEXT, event_date TEXT,
        details TEXT, confirmed INTEGER DEFAULT 0, source TEXT, fetched_at TEXT)""")
    return conn


class LecturaTest(unittest.TestCase):

    def setUp(self):
        self.conn = _base()
        for t, tipo, fecha, det in (
            ("NVDA", "earnings", "2030-01-09", None),          # ayer
            ("NVDA", "earnings", "2030-01-10", '{"eps_estimate": 1.2}'),  # hoy
            ("KO", "ex_dividend", "2030-01-24", "no es json"), # hoy + 14
            ("KO", "ex_dividend", "2030-01-25", None),         # hoy + 15
            ("AAPL", "earnings", "2030-01-12", None),          # otro ticker
        ):
            self.conn.execute(
                "INSERT INTO financial_events (ticker, event_type, event_date, details, confirmed, source)"
                " VALUES (?,?,?,?,1,'yfinance')", (t, tipo, fecha, det))

    def test_a_las_22_de_argentina_hoy_sigue_siendo_hoy(self):
        # 2030-01-11 01:00 UTC = 2030-01-10 22:00 ART
        with patch("fechas.datetime") as dt:
            dt.utcnow.return_value = datetime(2030, 1, 11, 1, 0)
            evs = eg.eventos_guardados(self.conn, ["NVDA", "KO"], 14)
        self.assertEqual([(e["ticker"], e["event_date"]) for e in evs],
                         [("NVDA", "2030-01-10"), ("KO", "2030-01-24")])

    def test_forma_de_cada_evento(self):
        evs = eg.eventos_guardados(self.conn, ["NVDA", "KO"], 14, hoy=date(2030, 1, 10))
        self.assertEqual(evs[0], {"ticker": "NVDA", "event_type": "earnings",
                                  "event_date": "2030-01-10", "details": {"eps_estimate": 1.2},
                                  "confirmed": True, "source": "yfinance"})
        self.assertEqual(evs[1]["details"], {})   # JSON roto no rompe la lectura

    def test_limite_y_lista_vacia(self):
        self.assertEqual(len(eg.eventos_guardados(self.conn, ["NVDA", "KO"], 14,
                                                  hoy=date(2030, 1, 10), limite=1)), 1)
        self.assertEqual(eg.eventos_guardados(self.conn, [], 14), [])
        self.assertEqual(eg.eventos_guardados(self.conn, [None, ""], 14), [])


class BotonDeUnEventoTest(unittest.TestCase):
    """El ✦ de cada fila de Eventos (ai/builders/events_item): de 21 a 24 h
    de Argentina un evento de HOY daba days_ahead = -1 ("ya pasó"). Hallado
    por la revisión independiente — la copia del reloj que quedaba."""

    def test_a_las_22_un_evento_de_hoy_es_de_hoy(self):
        from ai.builders import events_item
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE positions (user_id, asset, broker, quantity, invested, is_cash)")
        with patch("fechas.datetime") as dt:
            dt.utcnow.return_value = datetime(2030, 1, 11, 1, 0)   # 22:00 ART del 10
            try:
                pkt = events_item.build(conn, 1, ticker="NVDA", event_type="earnings",
                                        event_date="2030-01-10")
            except Exception as e:   # el resto del packet puede pedir más tablas
                self.fail(f"el builder falló: {e!r}")
        self.assertEqual(pkt.get("days_ahead", pkt.get("event", {}).get("days_ahead")), 0)


class NadieCopiaLaConsultaTest(unittest.TestCase):

    def test_solo_el_duenio_lee_eventos_por_rango(self):
        copias = []
        for raiz, dirs, files in os.walk(BACKEND):
            dirs[:] = [d for d in dirs if d not in EXCLUIDAS]
            for f in files:
                if not f.endswith(".py") or f == DUENIO:
                    continue
                ruta = os.path.join(raiz, f)
                with open(ruta, encoding="utf-8") as fh:
                    if LECTURA_POR_RANGO.search(fh.read()):
                        copias.append(os.path.relpath(ruta, BACKEND))
        self.assertEqual(copias, [], "leé los eventos con eventos_guardados(), no a mano")


if __name__ == "__main__":
    unittest.main()
