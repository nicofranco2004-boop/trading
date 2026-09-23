"""El panel de seguimiento: ¿se nota el progreso de cada prueba?

El embudo (`test_billing_trial.py`) cuenta cabezas al final del camino. Esto
mira a cada persona MIENTRAS prueba, que es el único momento en que todavía se
puede hacer algo, y por eso lo que hay que blindar es distinto: no es "¿el
total da bien?" sino "¿la actividad cae en la ventana de días correcta?".

Los tres riesgos que este archivo cubre, y que ya se rompieron antes en este
repo con esta misma forma:

  1. ⭐ LA VENTANA. Una importación de hace 5 días NO puede aparecer en "los
     últimos 3 días". Si el corte se corre un día, el panel dice que alguien
     está avanzando cuando hace una semana que no entra — y esa es justo la
     persona a la que hay que escribirle.
  2. ⭐ LOS DOS DIBUJOS DEL MISMO DATO. La tabla de ventanas y la tira de días
     de la pantalla salen del mismo array a propósito. El test suma la tira a
     mano y la compara contra la ventana: si algún día alguien calcula las
     ventanas por separado, acá se pone en rojo.
  3. ⭐ LO QUE NO SE PUEDE FECHAR. `positions` y `operations` no guardan cuándo
     se creó cada fila, así que lo cargado A MANO se cuenta como total y JAMÁS
     se reparte por día. Si alguien lo mete en una ventana, el panel empieza a
     mostrar actividad inventada en el día de hoy.

Y el que protege el refactor que vino con esto: `activos()` y `progreso()`
tienen que decir los MISMOS días restantes de la misma persona. Los dos usan
ahora `prueba_viva` + `dias_restantes`; antes cada uno tenía su copia de la
cuenta.

Corre con: cd backend && python3 -m pytest tests/test_progreso_de_la_prueba.py
"""
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main                                      # noqa: E402
from billing import trial as tr                   # noqa: E402


def _iso(dt):
    return dt.isoformat()


class Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        cls.client = TestClient(main.app)

    def setUp(self):
        self.conn = main.get_db()
        try:
            self.conn.rollback()
        except Exception:
            pass
        for t in ("import_op_links", "import_batches", "login_history",
                  "ai_usage_daily", "positions", "operations", "credit_ledger",
                  "subscriptions", "trial_consumed", "trial_email_log",
                  "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        for var in ("TRIALS_ENABLED", "TRIALS_MONTHLY_CAP", "PAYWALL_NUEVOS"):
            os.environ.pop(var, None)
        from billing import emails as _em
        self._orig = {}
        for fn in ("send_trial_started", "send_trial_pro_ending",
                   "send_trial_ending_soon", "send_trial_ended",
                   "send_welcome_free"):
            if hasattr(_em, fn):
                self._orig[fn] = getattr(_em, fn)
                setattr(_em, fn, lambda **kw: True)
        self.ahora = datetime.utcnow()

    def tearDown(self):
        from billing import emails as _em
        for fn, orig in getattr(self, "_orig", {}).items():
            setattr(_em, fn, orig)
        try:
            self.conn.rollback()
        except Exception:
            pass
        self.conn.close()

    # ── el mundo ────────────────────────────────────────────────────────────

    def _persona(self, email=None, *, admin=0):
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, "
            "                   requires_plan, is_admin) VALUES (?,?,1,1,1,?)",
            (email or f"{uuid.uuid4().hex[:8]}@rendi.test", "x", admin))
        self.conn.commit()
        return cur.lastrowid

    def _con_prueba(self, uid, *, arrancó_hace=0):
        """Le arranca la prueba y después corre el reloj hacia atrás.

        Mover las tres fechas juntas es la única forma de viajar en el tiempo
        acá, y son las tres a propósito: `trial_ends_at` sin
        `credit_active_until` deja a la persona 'terminada' aunque la prueba
        esté viva, que es el bug que hace que el panel muestre a nadie."""
        self.assertTrue(tr.start(self.conn, uid).get("ok"))
        if not arrancó_hace:
            return
        atras = timedelta(days=arrancó_hace)
        r = self.conn.execute(
            "SELECT trial_started_at, credit_active_until, trial_ends_at "
            "FROM users WHERE id=?", (uid,)).fetchone()
        self.conn.execute(
            "UPDATE users SET trial_started_at=?, credit_active_until=?, "
            "                 trial_ends_at=? WHERE id=?",
            (_iso(datetime.fromisoformat(r["trial_started_at"]) - atras),
             _iso(datetime.fromisoformat(r["credit_active_until"]) - atras),
             _iso(datetime.fromisoformat(r["trial_ends_at"]) - atras), uid))
        self.conn.commit()

    def _importó(self, uid, *, hace_dias=0, filas=1, broker="Cocos",
                 status="confirmed"):
        """Un archivo confirmado hace N días, con `filas` posiciones creadas.

        Va por las DOS tablas que usa el panel de verdad —el lote y los
        vínculos— y no por un contador aparte: el número que se mira en
        producción sale de contar vínculos, así que el test tiene que crearlos."""
        bid = uuid.uuid4().hex[:12]
        cuando = (self.ahora - timedelta(days=hace_dias)).strftime(
            "%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "INSERT INTO import_batches (id, user_id, broker, parser_format, "
            "  file_hash, status, created_at, confirmed_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (bid, uid, broker, "test", bid, status, cuando, cuando))
        for i in range(filas):
            cur = self.conn.execute(
                "INSERT INTO positions (user_id, broker, asset, quantity, is_cash) "
                "VALUES (?,?,?,?,0)", (uid, broker, f"ACT{i}", 1))
            self.conn.execute(
                "INSERT INTO import_op_links (batch_id, position_id) VALUES (?,?)",
                (bid, cur.lastrowid))
        self.conn.commit()
        return bid

    def _cargó_a_mano(self, uid, n=1, broker="Cocos"):
        """Posiciones SIN vínculo a ningún lote: nadie sabe de qué día son."""
        for i in range(n):
            self.conn.execute(
                "INSERT INTO positions (user_id, broker, asset, quantity, is_cash) "
                "VALUES (?,?,?,?,0)", (uid, broker, f"MANO{i}", 1))
        self.conn.commit()

    def _entró(self, uid, hace_dias=0, veces=1):
        cuando = (self.ahora - timedelta(days=hace_dias)).strftime(
            "%Y-%m-%d %H:%M:%S")
        for _ in range(veces):
            self.conn.execute(
                "INSERT INTO login_history (user_id, created_at) VALUES (?,?)",
                (uid, cuando))
        self.conn.commit()

    def _usó_ia(self, uid, hace_dias=0, analisis=1, chat=0):
        dia = (self.ahora - timedelta(days=hace_dias)).date().isoformat()
        self.conn.execute(
            "INSERT INTO ai_usage_daily (user_id, date, analyses_count, chat_count) "
            "VALUES (?,?,?,?)", (uid, dia, analisis, chat))
        self.conn.commit()

    def _pagó(self, uid):
        """La misma alta que usa test_billing_trial: una suscripción cobrada de
        verdad es fila en `subscriptions` Y plata en el ledger."""
        ts = self.ahora.strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "INSERT INTO subscriptions (user_id, status, external_reference, "
            "                           period, amount_ars, created_at) "
            "VALUES (?, 'authorized', ?, 'monthly', 10000, ?)",
            (uid, f"ref-{uid}", ts))
        self.conn.execute(
            "INSERT INTO credit_ledger (user_id, kind, amount_usd, days_delta, "
            "                           created_at) "
            "VALUES (?, 'payment', 9.0, 30, ?)", (uid, ts))
        self.conn.commit()

    def _fila(self, uid):
        for p in tr.progreso(self.conn)["personas"]:
            if p["id"] == uid:
                return p
        self.fail(f"uid={uid} no aparece en el panel")


class LoQueYaMostrabaElPanelViejo(Base):
    """Fecha de arranque, día en el que va y cuánto le queda."""

    def test_arranca_hoy_y_va_por_el_dia_1(self):
        uid = self._persona()
        self._con_prueba(uid)
        p = self._fila(uid)
        self.assertEqual(p["estado"], "activa")
        self.assertEqual(p["dia"], 1)
        self.assertEqual(p["inicio"], self.ahora.date().isoformat())
        self.assertEqual(p["days_left"], tr.TRIAL_TOTAL_DAYS)
        self.assertEqual(p["stage"], "pro")

    def test_a_mitad_de_camino(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=tr.TRIAL_PRO_DAYS + 1)
        p = self._fila(uid)
        self.assertEqual(p["dia"], tr.TRIAL_PRO_DAYS + 2)
        self.assertEqual(p["days_left"], tr.TRIAL_PLUS_DAYS - 1)
        self.assertEqual(p["stage"], "plus",
                         "pasado el corte de Pro la etapa tiene que ser Plus")

    def test_el_dia_nunca_pasa_del_total(self):
        """Terminada hace rato, `dia` muestra el total y no un número que sigue
        creciendo para siempre (día 47 de 20 no significa nada)."""
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=tr.TRIAL_TOTAL_DAYS + 25)
        p = self._fila(uid)
        self.assertEqual(p["dia"], tr.TRIAL_TOTAL_DAYS)
        self.assertEqual(p["estado"], "terminada")
        self.assertEqual(p["days_left"], 0)

    def test_los_dos_paneles_dicen_los_mismos_dias(self):
        """⭐ El refactor: `activos()` y `progreso()` responden lo mismo sobre la
        misma persona. Antes cada uno tenía su copia de la cuenta de días."""
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=4)
        desde_activos = [u for u in tr.activos(self.conn)["usuarios"]
                         if u["id"] == uid][0]
        self.assertEqual(self._fila(uid)["days_left"], desde_activos["days_left"])
        self.assertEqual(self._fila(uid)["stage"], desde_activos["stage"])


class LaVentanaDeDias(Base):
    """⭐ El corazón del panel: que lo de hace 5 días no figure como de hoy."""

    def test_lo_de_hoy_entra_en_todas_las_ventanas(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=10)
        self._importó(uid, hace_dias=0, filas=7)
        v = self._fila(uid)["ventanas"]
        for n in ("1", "3", "7", "15"):
            self.assertEqual(v[n]["filas"], 7, f"la ventana de {n} días no lo vio")

    def test_lo_de_hace_cinco_dias_NO_entra_en_la_de_tres(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=10)
        self._importó(uid, hace_dias=5, filas=4)
        v = self._fila(uid)["ventanas"]
        self.assertEqual(v["1"]["filas"], 0, "una carga de hace 5 días figura como de hoy")
        self.assertEqual(v["3"]["filas"], 0, "una carga de hace 5 días entra en «3 días»")
        self.assertEqual(v["7"]["filas"], 4)
        self.assertEqual(v["15"]["filas"], 4)

    def test_las_ventanas_se_acumulan_en_el_orden_correcto(self):
        """Tres cargas en tres momentos: cada ventana ve exactamente lo suyo."""
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=14)
        self._importó(uid, hace_dias=0, filas=1)
        self._importó(uid, hace_dias=2, filas=10)
        self._importó(uid, hace_dias=9, filas=100)
        v = self._fila(uid)["ventanas"]
        self.assertEqual(v["1"]["filas"], 1)
        self.assertEqual(v["3"]["filas"], 11)
        self.assertEqual(v["7"]["filas"], 11)
        self.assertEqual(v["15"]["filas"], 111)

    def test_la_ventana_es_la_suma_de_la_tira(self):
        """⭐ La tabla y el dibujo de la pantalla salen del mismo array. Si
        alguien calcula las ventanas por separado, acá se rompe."""
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=12)
        self._importó(uid, hace_dias=1, filas=3)
        self._importó(uid, hace_dias=6, filas=5)
        self._usó_ia(uid, hace_dias=2, analisis=4)
        self._entró(uid, hace_dias=0, veces=2)
        p = self._fila(uid)
        for n in (1, 3, 7, 15):
            a_mano = {"filas": 0, "archivos": 0, "ia": 0, "entradas": 0}
            for d in p["dias"][-n:]:
                for k in a_mano:
                    a_mano[k] += d[k]
            # La frecuencia son días DISTINTOS, no entradas: se cuenta aparte.
            a_mano["dias_entro"] = sum(1 for d in p["dias"][-n:] if d["entradas"])
            self.assertEqual(p["ventanas"][str(n)], a_mano,
                             f"la ventana de {n} días no coincide con la tira")

    def test_la_tira_tiene_un_lugar_por_dia_desde_el_arranque(self):
        """Los días sin nada tienen que existir igual: el hueco ES el dato."""
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=6)
        p = self._fila(uid)
        self.assertEqual(len(p["dias"]), 7, "faltan días en la tira")
        self.assertEqual(p["dias"][0]["d"], p["inicio"])
        self.assertEqual(p["dias"][-1]["d"], self.ahora.date().isoformat())
        self.assertTrue(all(d["filas"] == 0 for d in p["dias"]))


class LaTiraNoPuedeEmpezarHaceMeses(Base):
    """⭐ La tira tiene un tope de días. Si ese tope se aplica desde el ARRANQUE
    en vez de desde hoy, una prueba vieja devuelve los primeros 45 días y las
    ventanas —que son "los últimos N de la tira"— pasan a mirar un pedazo del
    pasado: el panel diría "cargó 90 filas hoy" con una importación de hace dos
    meses. Sale con la ventana de 90/180 días del selector."""

    def test_una_prueba_de_hace_dos_meses_no_muestra_actividad_vieja_como_de_hoy(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=60)
        self._importó(uid, hace_dias=55, filas=90)
        p = [x for x in tr.progreso(self.conn, days=90)["personas"]
             if x["id"] == uid][0]
        for n in ("1", "3", "7", "15"):
            self.assertEqual(
                p["ventanas"][n]["filas"], 0,
                f"la ventana de {n} días está mostrando una carga de hace 55 días")

    def test_la_tira_siempre_termina_hoy(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=60)
        p = [x for x in tr.progreso(self.conn, days=90)["personas"]
             if x["id"] == uid][0]
        self.assertEqual(p["dias"][-1]["d"], self.ahora.date().isoformat(),
                         "la tira no llega hasta hoy: las ventanas miran el pasado")

    def test_y_lo_de_ayer_sigue_entrando(self):
        """El contraveneno: que el arreglo no corte también lo reciente."""
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=60)
        self._importó(uid, hace_dias=1, filas=7)
        p = [x for x in tr.progreso(self.conn, days=90)["personas"]
             if x["id"] == uid][0]
        self.assertEqual(p["ventanas"]["3"]["filas"], 7)


class LoQueNoSePuedeFechar(Base):
    """⭐ Lo cargado a mano se cuenta, pero nunca se reparte por día."""

    def test_lo_cargado_a_mano_no_aparece_en_ninguna_ventana(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=3)
        self._cargó_a_mano(uid, 5)
        p = self._fila(uid)
        self.assertEqual(p["tiene"]["a_mano"], 5)
        self.assertEqual(p["tiene"]["posiciones"], 5)
        for n in ("1", "3", "7", "15"):
            self.assertEqual(
                p["ventanas"][n]["filas"], 0,
                "una fila sin fecha se está contando como si fuera de hoy")

    def test_una_operacion_registrada_a_mano_tambien_cuenta(self):
        """Una venta cargada por el chat del Coach no pasa por ningún lote.
        Contando sólo `positions`, esa persona se leía como que no hizo nada."""
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=3)
        self.conn.execute(
            "INSERT INTO operations (user_id, date, broker, asset, op_type) "
            "VALUES (?,?,?,?,'Venta')",
            (uid, self.ahora.date().isoformat(), "Cocos", "GGAL"))
        self.conn.commit()
        p = self._fila(uid)
        self.assertEqual(p["tiene"]["operaciones"], 1)
        self.assertEqual(p["tiene"]["a_mano"], 1,
                         "la operación cargada a mano no se está contando")

    def test_lo_importado_no_cuenta_como_cargado_a_mano(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=3)
        self._importó(uid, hace_dias=1, filas=6)
        self._cargó_a_mano(uid, 2)
        p = self._fila(uid)
        self.assertEqual(p["tiene"]["posiciones"], 8)
        self.assertEqual(p["tiene"]["a_mano"], 2,
                         "las importadas se están contando como cargadas a mano")


class LoQueNoTieneQueContar(Base):

    def test_un_archivo_sin_confirmar_no_cuenta(self):
        """El preview de una importación que nunca se confirmó no es una carga:
        la persona abrió el archivo y se fue."""
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=2)
        self._importó(uid, hace_dias=0, filas=9, status="preview")
        p = self._fila(uid)
        self.assertEqual(p["ventanas"]["1"]["filas"], 0)
        self.assertEqual(p["ventanas"]["1"]["archivos"], 0)

    def test_el_efectivo_no_es_una_posicion_cargada(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=2)
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, is_cash) "
            "VALUES (?,?,?,?,1)", (uid, "Cocos", "USD", 100))
        self.conn.commit()
        self.assertEqual(self._fila(uid)["tiene"]["posiciones"], 0)

    def test_la_actividad_de_otro_no_se_le_cuenta(self):
        """Las consultas traen la tanda entera de una y reparten por uid: si el
        reparto se equivoca, todos muestran la actividad de todos."""
        uno, otro = self._persona(), self._persona()
        self._con_prueba(uno, arrancó_hace=3)
        self._con_prueba(otro, arrancó_hace=3)
        self._importó(uno, hace_dias=0, filas=11)
        self.assertEqual(self._fila(uno)["ventanas"]["1"]["filas"], 11)
        self.assertEqual(self._fila(otro)["ventanas"]["1"]["filas"], 0)


class ElResumenEnUnaPalabra(Base):
    """`estado_uso` es lo que se lee de un vistazo; equivocarlo manda a hablar
    con la persona equivocada."""

    def test_sin_datos_cuando_la_app_esta_vacia(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=5)
        self._entró(uid, hace_dias=0)
        self.assertEqual(self._fila(uid)["estado_uso"], "sin_datos",
                         "entrar sin cargar nada no es estar probando Rendi")

    def test_avanzando_con_algo_en_los_ultimos_tres_dias(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=8)
        self._importó(uid, hace_dias=1, filas=3)
        self.assertEqual(self._fila(uid)["estado_uso"], "avanzando")

    def test_tibio_cuando_lo_ultimo_fue_hace_cinco_dias(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=8)
        self._importó(uid, hace_dias=5, filas=3)
        self.assertEqual(self._fila(uid)["estado_uso"], "tibio")

    def test_frenado_cuando_carga_y_desaparece(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=14)
        self._importó(uid, hace_dias=12, filas=40)
        self.assertEqual(self._fila(uid)["estado_uso"], "frenado")

    def test_entrar_sin_cargar_igual_cuenta_como_señal_de_vida(self):
        """Con datos adentro, entrar YA es progreso: está mirando su cartera."""
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=14)
        self._importó(uid, hace_dias=12, filas=40)
        self._entró(uid, hace_dias=1)
        self.assertEqual(self._fila(uid)["estado_uso"], "avanzando")


class QuienEntraYQuienNo(Base):

    def test_el_que_pago_no_cuenta_como_probando(self):
        """Su `trial_ends_at` sigue en el futuro, pero ya decidió. Mezclarlo
        infla «los que están probando» con gente que ya es cliente."""
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=3)
        self._pagó(uid)
        p = self._fila(uid)
        self.assertEqual(p["estado"], "pago")
        self.assertEqual(tr.progreso(self.conn)["activas"], 0)

    def test_la_que_termino_hace_poco_sigue_a_la_vista(self):
        """Ver a quién se le venció sin pagar es media razón del panel."""
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=tr.TRIAL_TOTAL_DAYS + 2)
        self.assertEqual(self._fila(uid)["estado"], "terminada")

    def test_la_de_hace_mucho_ya_no_aparece(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=tr.TRIAL_TOTAL_DAYS + 200)
        self.assertTrue(all(p["id"] != uid
                            for p in tr.progreso(self.conn, days=30)["personas"]))

    def test_quien_nunca_activo_no_esta_en_el_panel(self):
        uid = self._persona()
        self.assertTrue(all(p["id"] != uid
                            for p in tr.progreso(self.conn)["personas"]))

    def test_primero_el_que_menos_tiempo_le_queda(self):
        """El orden es el orden en que hay que actuar."""
        apurado = self._persona()
        self._con_prueba(apurado, arrancó_hace=tr.TRIAL_TOTAL_DAYS - 2)
        recien = self._persona()
        self._con_prueba(recien, arrancó_hace=1)
        vivos = [p["id"] for p in tr.progreso(self.conn)["personas"]
                 if p["estado"] == "activa"]
        self.assertEqual(vivos[0], apurado)


class ElResumenDeLaTanda(Base):
    """Las tasas de abajo de la tabla. La regla que las gobierna: NINGUNA se
    vuelve a calcular con otro criterio — todas cuentan lo que la fila ya
    decidió. Un panel donde la tabla muestra 4 con la app vacía y el resumen
    dice 3 no se arregla: se deja de mirar."""

    def _res(self):
        return tr.progreso(self.conn)["resumen"]

    def test_la_tasa_de_uso_es_quienes_llegaron_a_cargar(self):
        cargo = self._persona()
        self._con_prueba(cargo, arrancó_hace=3)
        self._importó(cargo, hace_dias=1, filas=5)
        for _ in range(2):
            vacio = self._persona()
            self._con_prueba(vacio, arrancó_hace=3)
        r = self._res()
        self.assertEqual(r["total"], 3)
        self.assertEqual(r["con_datos"], 1)
        self.assertEqual(r["sin_datos"], 2)
        self.assertEqual(r["tasa_uso"], 33.3)

    def test_el_resumen_no_puede_contradecir_la_tabla(self):
        """⭐ El invariante: contar las filas a mano tiene que dar el resumen."""
        for hace, filas in ((2, 5), (12, 9), (4, 0), (14, 3)):
            uid = self._persona()
            self._con_prueba(uid, arrancó_hace=hace)
            if filas:
                self._importó(uid, hace_dias=hace, filas=filas)
        d = tr.progreso(self.conn)
        r, ps = d["resumen"], d["personas"]
        self.assertEqual(r["total"], len(ps))
        self.assertEqual(r["sin_datos"],
                         sum(1 for p in ps if p["estado_uso"] == "sin_datos"))
        self.assertEqual(r["frenados"],
                         sum(1 for p in ps if p["estado_uso"] == "frenado"))
        self.assertEqual(r["en_curso"],
                         sum(1 for p in ps if p["estado"] == "activa"))
        self.assertEqual(r["pagaron"],
                         sum(1 for p in ps if p["estado"] == "pago"))

    def test_el_abandono_se_mide_sobre_los_que_cargaron(self):
        """Quien nunca cargó nada no "abandonó": nunca arrancó. Meterlo en el
        denominador diluye el número que dice a quién escribirle."""
        frenado = self._persona()
        self._con_prueba(frenado, arrancó_hace=14)
        self._importó(frenado, hace_dias=12, filas=40)
        activo = self._persona()
        self._con_prueba(activo, arrancó_hace=5)
        self._importó(activo, hace_dias=1, filas=7)
        vacio = self._persona()
        self._con_prueba(vacio, arrancó_hace=5)

        r = self._res()
        self.assertEqual(r["con_datos"], 2)
        self.assertEqual(r["frenados"], 1)
        self.assertEqual(r["tasa_abandono"], 50.0,
                         "el abandono se está midiendo sobre los 3 y no sobre los 2")

    def test_la_conversion_va_sobre_las_que_ya_terminaron(self):
        vencida_paga = self._persona()
        self._con_prueba(vencida_paga, arrancó_hace=tr.TRIAL_TOTAL_DAYS + 2)
        self._pagó(vencida_paga)
        vencida_no = self._persona()
        self._con_prueba(vencida_no, arrancó_hace=tr.TRIAL_TOTAL_DAYS + 2)
        en_curso = self._persona()
        self._con_prueba(en_curso, arrancó_hace=2)

        r = self._res()
        self.assertEqual(r["terminadas"], 2, "el que sigue probando no terminó")
        self.assertEqual(r["convirtieron"], 1)
        self.assertEqual(r["tasa_conversion"], 50.0)

    def test_un_checkout_abandonado_no_es_una_conversion(self):
        """⭐ El bug documentado del embudo: hay fila en `subscriptions` desde
        que se GENERA el link de pago. Contarla daba 100% de conversión con
        gente que nunca pagó un peso."""
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=tr.TRIAL_TOTAL_DAYS + 2)
        self.conn.execute(
            "INSERT INTO subscriptions (user_id, status, external_reference, "
            "                           period, amount_ars, created_at) "
            "VALUES (?, 'cancelled', ?, 'monthly', 13990, ?)",
            (uid, f"ref-{uid}", self.ahora.strftime("%Y-%m-%d %H:%M:%S")))
        self.conn.commit()
        r = self._res()
        self.assertEqual(r["convirtieron"], 0)
        self.assertEqual(r["tasa_conversion"], 0.0)
        self.assertNotEqual(self._fila(uid)["estado"], "pago")

    def test_sin_nadie_las_tasas_son_None_y_no_cero(self):
        """"0%" y "todavía no hay nadie" son cosas distintas: si el panel
        muestra 0% de conversión sin una sola prueba terminada, se lee como que
        la prueba no funciona."""
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=2)
        r = self._res()
        self.assertEqual(r["terminadas"], 0)
        self.assertIsNone(r["tasa_conversion"])
        self.assertIsNone(r["tasa_abandono"], "nadie cargó datos todavía")

    def test_los_que_estan_por_vencer_usan_el_corte_del_mail(self):
        """El «se terminan pronto» del panel y el mail de aviso tienen que
        hablar de la misma gente."""
        justo = self._persona()
        self._con_prueba(justo, arrancó_hace=tr.TRIAL_TOTAL_DAYS - tr.MAIL_AVISO_DIAS_ANTES)
        lejos = self._persona()
        self._con_prueba(lejos, arrancó_hace=2)
        r = self._res()
        self.assertEqual(r["dias_aviso"], tr.MAIL_AVISO_DIAS_ANTES)
        self.assertEqual(r["por_terminar"], 1)
        self.assertEqual(self._fila(justo)["days_left"], tr.MAIL_AVISO_DIAS_ANTES)

    def test_los_cuatro_pedazos_suman_la_tanda_entera(self):
        """⭐ La barra de "dónde está cada una" se dibuja con cuatro tramos. Si
        no suman el total, la barra queda corta y nadie sabe quién falta."""
        for hace in (2, tr.TRIAL_PRO_DAYS + 2, tr.TRIAL_TOTAL_DAYS + 2):
            uid = self._persona()
            self._con_prueba(uid, arrancó_hace=hace)
        pago = self._persona()
        self._con_prueba(pago, arrancó_hace=5)
        self._pagó(pago)

        r = self._res()
        self.assertEqual(
            r["en_pro"] + r["en_plus"] + r["pagaron"] + r["terminadas_sin_pagar"],
            r["total"], "los cuatro tramos de la barra no suman la tanda")
        self.assertGreaterEqual(r["terminadas_sin_pagar"], 0)

    def test_pro_y_plus_parten_a_los_que_estan_probando(self):
        en_pro = self._persona()
        self._con_prueba(en_pro, arrancó_hace=2)
        en_plus = self._persona()
        self._con_prueba(en_plus, arrancó_hace=tr.TRIAL_PRO_DAYS + 2)
        r = self._res()
        self.assertEqual(r["en_pro"], 1)
        self.assertEqual(r["en_plus"], 1)
        self.assertEqual(r["en_pro"] + r["en_plus"], r["en_curso"])


class LaFrecuenciaDeUso(Base):
    """"6/7 días" son días DISTINTOS, no entradas."""

    def test_entrar_seis_veces_el_mismo_dia_es_un_solo_dia(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=8)
        self._entró(uid, hace_dias=1, veces=6)
        v = self._fila(uid)["ventanas"]["7"]
        self.assertEqual(v["entradas"], 6)
        self.assertEqual(v["dias_entro"], 1,
                         "seis entradas de un martes están contando como seis días")

    def test_tres_dias_distintos_son_tres(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=8)
        for d in (0, 2, 5):
            self._entró(uid, hace_dias=d)
        self.assertEqual(self._fila(uid)["ventanas"]["7"]["dias_entro"], 3)


class LosBordes(Base):
    """Lo que pasa cuando falta un dato o el reloj miente. Nada de esto tiene
    que reventar la pantalla entera: es un panel de admin, y el que lo abre a
    las 2 de la mañana porque algo pasa necesita ver el resto."""

    def test_sin_una_sola_prueba_devuelve_la_forma_completa(self):
        """La pantalla lee `resumen.dias_aviso` y `ventanas` antes de tener
        datos. Si faltan con la base vacía, se rompe en el primer render."""
        d = tr.progreso(self.conn)
        self.assertEqual(d["personas"], [])
        self.assertEqual(d["ventanas"], list(tr.VENTANAS_PROGRESO))
        self.assertEqual(d["total_dias"], tr.TRIAL_TOTAL_DAYS)
        self.assertFalse(d["truncado"])
        self.assertIn("hoy", d)

    def test_sin_pruebas_igual_viene_el_resumen(self):
        """⭐ La pantalla muestra "el backend no responde este panel" cuando NO
        viene resumen. Sin este campo, una base sin pruebas se vería como un
        deploy roto — y las dos cosas piden lo contrario: una es esperar, la
        otra es correr a mirar Railway."""
        r = tr.progreso(self.conn)["resumen"]
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["en_curso"], 0)
        self.assertIsNone(r["tasa_uso"])
        self.assertIsNone(r["tasa_conversion"])
        self.assertEqual(r["dias_aviso"], tr.MAIL_AVISO_DIAS_ANTES)

    def test_alguien_sin_nombre_no_rompe_nada(self):
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=2)
        p = self._fila(uid)
        self.assertIsNone(p["name"])
        self.assertTrue(p["email"])

    def test_una_prueba_que_arranca_en_el_futuro_no_explota(self):
        """Pasa con un reloj corrido o una fecha cargada a mano desde admin.
        La tira queda vacía y la fila sigue existiendo."""
        uid = self._persona()
        self._con_prueba(uid)
        from datetime import timedelta as _td
        self.conn.execute(
            "UPDATE users SET trial_started_at=? WHERE id=?",
            ((self.ahora + _td(days=3)).isoformat(), uid))
        self.conn.commit()
        p = self._fila(uid)
        self.assertEqual(p["dias"], [])
        self.assertEqual(p["ventanas"]["7"]["filas"], 0)
        self.assertEqual(p["dia"], 1, "el día de la prueba nunca puede ser negativo")

    def test_la_ventana_de_dias_se_recorta_a_lo_permitido(self):
        """`days` gigante no puede convertirse en una consulta sin techo."""
        self.assertEqual(tr.progreso(self.conn, days=99999)["days"], 365)
        self.assertEqual(tr.progreso(self.conn, days=0)["days"], 1)

    def test_el_tope_de_filas_se_declara(self):
        for _ in range(4):
            uid = self._persona()
            self._con_prueba(uid, arrancó_hace=2)
        d = tr.progreso(self.conn, limit=2)
        self.assertEqual(len(d["personas"]), 2)
        self.assertEqual(d["total_en_ventana"], 4)
        self.assertTrue(d["truncado"], "cortó la lista y no lo dijo")
        # Y el resumen habla de lo que entró, no de una mezcla.
        self.assertEqual(d["resumen"]["total"], 2)


class LaPuertaDelPanel(Base):
    """Por el endpoint real: es admin-only y contesta lo que la pantalla lee."""

    def _headers(self, uid):
        return {"Authorization": f"Bearer {main.create_token(uid)}"}

    def test_un_usuario_comun_no_puede_ver_el_panel(self):
        uid = self._persona()
        r = self.client.get("/api/admin/billing/trial-progress",
                            headers=self._headers(uid))
        self.assertEqual(r.status_code, 403, r.text)

    def test_el_admin_lo_ve_con_la_forma_que_la_pantalla_espera(self):
        jefe = self._persona(admin=1)
        uid = self._persona()
        self._con_prueba(uid, arrancó_hace=2)
        self._importó(uid, hace_dias=0, filas=3)
        r = self.client.get("/api/admin/billing/trial-progress",
                            headers=self._headers(jefe))
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["ventanas"], list(tr.VENTANAS_PROGRESO))
        self.assertEqual(d["total_dias"], tr.TRIAL_TOTAL_DAYS)
        yo = [p for p in d["personas"] if p["id"] == uid][0]
        self.assertEqual(yo["ventanas"]["1"]["filas"], 3)
        self.assertIn("estado_uso", yo)

    def test_days_fuera_de_rango_se_rechaza(self):
        jefe = self._persona(admin=1)
        r = self.client.get("/api/admin/billing/trial-progress?days=9999",
                            headers=self._headers(jefe))
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
