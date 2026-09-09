"""El cron fecha en día argentino, y el YTD abre en el cierre del 31/12.

⚠️ LOS DOS ARREGLOS SON UNA SOLA COSA. Están en el mismo test y en el mismo
commit porque hasta ahora los dos errores se tapaban mutuamente, y arreglar uno
solo publica un número peor que el de antes.

EL PRIMERO — el cron fechaba en UTC.
El job corre a las 02:59 UTC *a propósito*: eso es 23:59 en Buenos Aires, o sea
el cierre del día que el usuario acaba de terminar de vivir. Pero la etiqueta
salía de `utcnow()`, que a esa hora ya dice el día siguiente. La serie entera
quedó corrida un día: el cierre del viernes archivado como sábado.

La conversión a hora argentina existía desde 2026-05-31, escrita adentro de
`take_snapshot_for_user`. Nunca corrió: el runner de al lado siempre pasa una
fecha no-nula, así que la rama `if target_date is None` es siempre falsa. Un fix
escrito y no propagado — la causa raíz más frecuente del repo.

No es cosmético. El desfasaje llega al borde de todos los períodos: el reporte de
septiembre arranca en el cierre del 30 de agosto (una rueda de más adentro del
mes) y el reporte anual de 2026 cierra con la rueda del 30 de diciembre, porque
el cierre real del 31 queda etiquetado `2027-01-01`, fuera del período.

EL SEGUNDO — el YTD de Métricas restaba dos veces el aporte del 1 de enero.
Tomaba como borde de apertura la foto del PROPIO 1 de enero, que ya tiene adentro
el aporte de ese día, y después restaba los flujos del año entero. Sobre una
cartera que ganó US$ 1.000 publicaba −US$ 4.000 / −22,86 %: el signo invertido.

POR QUÉ NO SE PODÍAN SEPARAR. Con el cron fechando en UTC, la fila etiquetada
`2026-01-01` era en realidad el cierre argentino del 31/12 — no contenía el aporte
del 1/1 — y el borde inclusivo caía bien por accidente. Arreglar sólo el cron hace
aparecer el segundo bug en el KPI anual, que además viaja al prompt del chat
marcado como "Retornos REALES precalculados — citalos, NO hagas aritmética nueva".

DÓNDE FUE EL ARREGLO DEL SEGUNDO. No en `_ytd_delta`: el mismo cálculo de borde
estaba escrito cuatro veces y el arreglo había llegado a tres. Se unificó en
`reporting.builder.snapshot_borde_apertura`, que ahora usan los cuatro.

Corre con: cd backend && python3 -m pytest tests/test_f3_cron_art_y_borde_anual.py
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

from snapshots_job import run_daily_snapshot


class ElCronFechaEnDiaArgentino(unittest.TestCase):
    """Reloj congelado en el minuto exacto que rompía: 02:59 UTC del sábado."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);
            CREATE TABLE brokers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, name TEXT NOT NULL,
                currency TEXT NOT NULL, parent_broker_id INTEGER
            );
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, broker TEXT NOT NULL,
                asset TEXT NOT NULL, is_cash INTEGER DEFAULT 0,
                invested REAL, quantity REAL, commissions REAL DEFAULT 0,
                price_override REAL, asset_type TEXT, currency TEXT
            );
            CREATE TABLE monthly_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, year INTEGER NOT NULL,
                month INTEGER NOT NULL, broker TEXT NOT NULL,
                capital_inicio REAL DEFAULT 0, capital_final REAL DEFAULT 0,
                deposits REAL DEFAULT 0, withdrawals REAL DEFAULT 0,
                pnl_realized REAL DEFAULT 0, pnl_unrealized REAL DEFAULT 0
            );
            CREATE TABLE snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, date TEXT NOT NULL,
                total_value REAL NOT NULL, total_invested REAL NOT NULL,
                net_deposited REAL NOT NULL DEFAULT 0,
                fx_to_usd_blue REAL, holdings_json TEXT,
                source TEXT, mtm_coverage REAL, base TEXT, apto INTEGER,
                UNIQUE(user_id, date)
            );
            CREATE TABLE fx_rates_daily (
                date TEXT PRIMARY KEY, blue_venta REAL NOT NULL,
                source TEXT DEFAULT 'unknown',
                fetched_at TEXT DEFAULT (datetime('now'))
            );
            INSERT INTO users (id, email) VALUES (1, 'test@example.com');
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_a_las_0259_utc_del_sabado_el_snapshot_se_llama_viernes(self):
        """El caso que corrió la serie histórica entera un día.

        02:59 UTC del sábado 5 = 23:59 ART del viernes 4. Lo que se está
        fotografiando es el cierre del VIERNES.
        """
        import fechas
        with patch("fechas.datetime") as reloj:
            reloj.utcnow.return_value = datetime(2026, 9, 5, 2, 59, 0)
            r = run_daily_snapshot(self.db_path, fetch_tc_blue=lambda: 1500,
                                   crypto_yf={})
        self.assertEqual(r["target_date"], "2026-09-04",
                         "El cron fechó el cierre del viernes como sábado.")

    def test_la_cotizacion_del_dia_se_guarda_con_la_misma_fecha(self):
        """`fx_rates_daily` y `snapshots` tienen que coincidir o el TC del día
        queda colgado de una fecha que no existe en la serie."""
        import fechas
        with patch("fechas.datetime") as reloj:
            reloj.utcnow.return_value = datetime(2026, 9, 5, 2, 59, 0)
            run_daily_snapshot(self.db_path, fetch_tc_blue=lambda: 1500, crypto_yf={})
        conn = sqlite3.connect(self.db_path)
        fechas_fx = [r[0] for r in conn.execute("SELECT date FROM fx_rates_daily")]
        conn.close()
        self.assertEqual(fechas_fx, ["2026-09-04"])

    def test_a_media_maniana_los_dos_relojes_coinciden(self):
        """Control: fuera de la franja 21:00-24:00 ART el fix no mueve nada."""
        import fechas
        with patch("fechas.datetime") as reloj:
            reloj.utcnow.return_value = datetime(2026, 9, 5, 13, 0, 0)  # 10:00 ART
            r = run_daily_snapshot(self.db_path, fetch_tc_blue=lambda: 1500,
                                   crypto_yf={})
        self.assertEqual(r["target_date"], "2026-09-05")

    def test_una_fecha_explicita_se_respeta(self):
        """Los backfills y los tests pasan la fecha a mano: eso no se toca."""
        r = run_daily_snapshot(self.db_path, lambda: 1500, {}, "2026-02-20")
        self.assertEqual(r["target_date"], "2026-02-20")


class ElYtdAbreEnElCierreDelAnioAnterior(unittest.TestCase):
    """El escenario medido: entran US$ 5.000 el 1 de enero y la cartera gana 1.000."""

    def setUp(self):
        import main
        self.main = main
        self.conn = main.get_db()
        for t in ("snapshots", "positions", "operations", "monthly_entries", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("ytd@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,?,?,0,1,100,?)",
            (self.uid, "IBKR", "AAPL", "2024-01-01"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _snap(self, d, v):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,0,'cron',1200.0,'[]')", (self.uid, d, v, v))
        self.conn.commit()

    def _cartera_que_gano_mil_dolares(self):
        # 31/12: cierra en 10.000. El 1/1 entran 5.000 → la foto del 1/1 dice 15.000.
        # En septiembre vale 16.000. Ganancia real del año: 1.000.
        self._snap("2025-12-31", 10000.0)
        self._snap("2026-01-01", 15000.0)
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,'global',2026,1,10000,15000,5000,0,0,0)", (self.uid,))
        self.conn.commit()

    def test_el_aporte_del_primero_de_enero_se_resta_una_sola_vez(self):
        """Antes: −US$ 4.000 / −22,86 %. La cartera había GANADO 1.000."""
        self._cartera_que_gano_mil_dolares()
        r = self.main._ytd_delta(self.conn, self.uid, 16000.0, "2026-09-04", "global")
        self.assertIsNotNone(r, "el YTD no debería apagarse: hay cierre del 31/12")
        self.assertAlmostEqual(r["usd"], 1000.0, places=1)
        self.assertGreater(r["pct"], 0, "publicaba el signo invertido")

    def test_sin_cierre_del_anio_anterior_el_ytd_no_se_publica(self):
        """Sin borde no se inventa uno: el número no sale, igual que en /reportes.

        Cubre la trampa del fix: agarrar la foto del 1/1 "porque es la que hay"
        es exactamente lo que producía el −22,86 %.
        """
        self._snap("2026-01-01", 15000.0)
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,'global',2026,1,10000,15000,5000,0,0,0)", (self.uid,))
        self.conn.commit()
        r = self.main._ytd_delta(self.conn, self.uid, 16000.0, "2026-09-04", "global")
        self.assertIsNone(r)

    def test_un_cierre_viejo_no_sirve_de_borde(self):
        """El piso de antigüedad sigue vivo: un cierre de noviembre mete dos meses
        de mercado ajeno adentro del año."""
        self._snap("2025-11-15", 10000.0)
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,'global',2026,1,10000,15000,5000,0,0,0)", (self.uid,))
        self.conn.commit()
        r = self.main._ytd_delta(self.conn, self.uid, 16000.0, "2026-09-04", "global")
        self.assertIsNone(r)


class ElBordeDeAperturaEsUnoSolo(unittest.TestCase):
    """Guard de CÓDIGO: que el cálculo no se vuelva a copiar.

    Lo que se arregló acá no fue una resta: fue que el mismo borde estuviera
    escrito cuatro veces con el arreglo en tres. Un test de números no impide la
    quinta copia.
    """

    DUENIO = "snapshot_borde_apertura"

    def test_nadie_arma_el_borde_a_mano_con_dia_anterior_y_mtm_only(self):
        import ast
        import re
        rutas = [os.path.join(BACKEND, "main.py"),
                 os.path.join(BACKEND, "reporting", "builder.py")]
        # El patrón de la copia: `_dia_anterior(...)` alimentando un
        # `fetch_snapshot_at_or_before(..., mtm_only=True)`.
        culpables = []
        for ruta in rutas:
            with open(ruta, encoding="utf-8") as fh:
                txt = fh.read()
            # El dueño del cálculo tiene derecho a escribirlo: se saltea su cuerpo.
            permitido = set()
            for nodo in ast.walk(ast.parse(txt)):
                if isinstance(nodo, ast.FunctionDef) and nodo.name == self.DUENIO:
                    permitido = set(range(nodo.lineno, (nodo.end_lineno or nodo.lineno) + 1))
            for m in re.finditer(r"_dia_anterior\([^)]*\)", txt):
                ventana = txt[m.end():m.end() + 400]
                if "mtm_only=True" in ventana:
                    linea = txt[:m.start()].count("\n") + 1
                    if linea in permitido:
                        continue
                    culpables.append(f"{os.path.relpath(ruta, BACKEND)}:{linea}")
        self.assertEqual(
            culpables, [],
            "Alguien volvió a armar el borde de apertura a mano. Usá "
            "`reporting.builder.snapshot_borde_apertura`: " + ", ".join(culpables))


if __name__ == "__main__":
    unittest.main()
