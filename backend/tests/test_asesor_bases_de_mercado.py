"""Lado asesor: qué foto se DIBUJA, qué foto puede ser BASE, y de cuándo es.

Tres defectos del libro del asesor, todos de la misma familia que el resto de
la app ya había cerrado (el caso 452: 196.631 al costo contra 67.214 a mercado):

  1. "Evolución del capital administrado" (GET /api/advisor/book/history) leía
     TODAS las fotos sin clasificar, y la pantalla restaba punta contra punta.
     Una foto del import —la cadena contable copiada al costo— entraba a la
     curva, y el salto costo→mercado se publicaba como "el mercado restó $X".
     Y una base de cualquier antigüedad (un hueco de fotos) metía mercado de
     antes del período adentro del período.
  2. El modal "Últimos 7 días" no tenía el piso de antigüedad del hero y cortaba
     el día con el reloj de UTC: a las 22 h de Buenos Aires ya era mañana.
  3. El mail de cierre llamaba "hoy" a una variación medida contra un cierre de
     hace varios días, sin decir de cuándo era.

Y los lectores que tenían el mismo defecto (barrido "¿quién más lee esto?" y
dos auditorías independientes):
  · la alerta de movimiento de cartera decía "hoy" / "desde el cierre de ayer"
    con bases de hasta 4 días;
  · el grupo "están perdiendo", la tarjeta Mejor/Peor y la cola "Su ganancia
    cayó X%" juzgaban con la ÚLTIMA foto: la del import (al costo) publicaba
    números falsos, y la de media rueda que escribe la app al abrirla hacía
    desaparecer al cliente ese día;
  · el mail de cierre no descontaba los depósitos, y un cliente frenado le
    cambiaba el rótulo al total de todo el libro;
  · el informe del período publicaba sin nota una base de 6 a 10 días.

Todos los tests pasan por el ENDPOINT (o por el armado real del mail / de la
alerta), con fotos estampadas igual que en producción (`twr.estampar_base`).
"""
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import fechas
import main
import twr
from fastapi.testclient import TestClient


def _user(conn, email, tier=None, approved=1):
    return conn.execute(
        "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,?,?)",
        (email, "x", approved, tier)).lastrowid


class _LibroBase(unittest.TestCase):
    """Un asesor, y clientes que se agregan con su historia de fotos."""

    def setUp(self):
        self.hoy = fechas.hoy_art_date()
        self.http = TestClient(main.app)
        self.clientes = []
        conn = main.get_db()
        try:
            self.tag = uuid.uuid4().hex[:10]
            self.asesor = _user(conn, f"asesor-{self.tag}@rendi.test", tier="advisor")
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM advisor_alert_events WHERE advisor_uid=?", (self.asesor,))
            conn.execute("DELETE FROM advisor_alert_state WHERE advisor_uid=?", (self.asesor,))
            conn.execute("DELETE FROM advisor_alerts WHERE advisor_uid=?", (self.asesor,))
            conn.execute("DELETE FROM advisor_clients WHERE advisor_uid=?", (self.asesor,))
            conn.execute("DELETE FROM advisor_reports WHERE advisor_uid=?", (self.asesor,))
            for c in self.clientes:
                conn.execute("DELETE FROM snapshots WHERE user_id=?", (c,))
                conn.execute("DELETE FROM positions WHERE user_id=?", (c,))
                conn.execute("DELETE FROM monthly_entries WHERE user_id=?", (c,))
            conn.commit()
        finally:
            conn.close()

    def _hdr(self):
        return {"Authorization": f"Bearer {main.create_token(self.asesor)}"}

    def _dia(self, dias_atras: int) -> str:
        return (self.hoy - timedelta(days=dias_atras)).isoformat()

    def _cliente(self, label: str) -> int:
        conn = main.get_db()
        try:
            cid = _user(conn, f"{label.lower().replace(' ', '')}-{uuid.uuid4().hex[:8]}@rendi.test",
                        approved=0)
            conn.execute("UPDATE users SET managed_by=? WHERE id=?", (self.asesor, cid))
            conn.execute(
                """INSERT INTO advisor_clients
                       (advisor_uid, client_uid, link_type, permission, status, label)
                   VALUES (?,?,'managed','read_write','active',?)""",
                (self.asesor, cid, label))
            # Tuvo cartera no-cash desde hace años: sin esto el clasificador lee
            # una foto sin composición como "cartera 100% cash".
            conn.execute(
                "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
                "invested, entry_date) VALUES (?,'IBKR','AAPL',0,1,100,'2020-01-01')",
                (cid,))
            conn.commit()
        finally:
            conn.close()
        self.clientes.append(cid)
        return cid

    def _fotos(self, cid: int, filas):
        """filas = [(dias_atras, total_value, net_deposited, source)]. Se estampan
        `base`/`apto` con el MISMO escritor que producción, no a mano."""
        conn = main.get_db()
        try:
            for dias, tv, nd, src in filas:
                conn.execute(
                    "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
                    "net_deposited, source, fx_to_usd_blue, holdings_json) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (cid, self._dia(dias), tv, tv, nd, src,
                     None if src == "import" else 1400.0,
                     '[{"asset":"AAPL"}]' if src == "cron" else None))
            twr.estampar_base(conn, [cid])
            conn.commit()
        finally:
            conn.close()

    def _historia(self, extra=""):
        r = self.http.get(f"/api/advisor/book/history?days=730{extra}", headers=self._hdr())
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


# ─── 1. La evolución del capital administrado ────────────────────────────────

class EvolucionConFotosAlCostoTest(_LibroBase):
    """El caso 452 en el libro: historia importada al costo (196.631) y después el
    cron midiendo a mercado (67.214). La cartera no perdió 129.417 en el período:
    lo que cambió fue la REGLA con que se valuó."""

    COSTO = 196631.0
    MERCADO = 67214.0

    def setUp(self):
        super().setUp()
        self.c452 = self._cliente("Caso 452")
        filas = [(d, self.COSTO, 150000.0, "import") for d in (150, 120, 91)]
        filas += [(d, self.MERCADO + (20 - d) * 10, 150000.0, "cron") for d in range(20, 0, -1)]
        self._fotos(self.c452, filas)

    def test_la_foto_al_costo_no_se_dibuja(self):
        serie = self._historia()["series"]
        self.assertTrue(serie)
        self.assertNotIn(self.COSTO, [p["aum_usd"] for p in serie],
                         "la foto del import (al costo) entró a la curva a mercado")
        # La curva de este cliente arranca con su primera medición.
        self.assertEqual(serie[0]["date"], self._dia(20))

    def test_el_salto_costo_mercado_no_se_publica_como_mercado(self):
        """Hace 90 días este cliente sólo tenía la foto del import: se lo mide
        desde su PRIMERA medición a mercado (hace 20 días). El mercado de verdad
        movió +190; el escalón costo→mercado (−129.227) no entra."""
        p90 = self._historia()["periods"]["90"]
        self.assertEqual(p90["corte"], self._dia(90))
        self.assertEqual(p90["clientes_medidos"], 1)
        self.assertEqual(p90["clientes_entraron"], 1)
        self.assertEqual(p90["mercado_usd"], 190.0)
        self.assertEqual(p90["aportes_usd"], 0.0)

    def test_con_otro_cliente_desde_antes_tampoco_entra_el_salto(self):
        """Con otro cliente medido desde hace 100 días que sostiene la curva, el
        caso 452 sigue entrando desde su primera medición: el total del período es
        su +190 más el 0 del otro, nunca el escalón del import."""
        sano = self._cliente("Sano")
        self._fotos(sano, [(d, 1000.0, 1000.0, "cron") for d in range(100, 0, -1)])
        p90 = self._historia()["periods"]["90"]
        self.assertEqual(p90["clientes_medidos"], 2)
        self.assertEqual(p90["clientes_entraron"], 1)
        self.assertEqual(p90["mercado_usd"], 190.0)

    def test_la_serie_ya_no_trae_el_escalon_costo_mercado(self):
        """Un navegador con la versión anterior de la pantalla en caché resta
        punta contra punta de la serie. Con la serie nueva esa resta ya no cruza
        del costo al mercado para UN cliente solo.

        ⚠️ Lo que este test NO cubre, a propósito: con otro cliente que ya sostiene
        la curva, la pantalla vieja sigue leyendo como "mercado" la ganancia previa
        del cliente que ENTRA (el "+1 cliente"). Eso no se arregla desde la serie:
        lo arregla la pantalla nueva, que lee `periods`. Dura lo que tarde ese
        navegador en recargar la versión nueva."""
        serie = self._historia()["series"]
        corte = self._dia(90)
        i = next(k for k, p in enumerate(serie) if p["date"] >= corte)
        base = serie[i - 1] if i > 0 else serie[i]
        fin = serie[-1]
        mercado_viejo = ((fin["aum_usd"] - base["aum_usd"])
                         - (fin["net_deposited_usd"] - base["net_deposited_usd"]))
        self.assertGreater(mercado_viejo, -1000,
                           f"la pantalla publicaría 'el mercado restó {-mercado_viejo:,.0f}'")


class EvolucionConHuecoDeFotosTest(_LibroBase):
    """Un cliente con un hueco de 50 días en sus fotos: su cartera subió 4.000
    en algún momento del hueco. Eso NO se le puede atribuir a "los últimos 30
    días": la base de ese cliente tiene 30 días de antigüedad."""

    def setUp(self):
        super().setUp()
        # Sano: el cron todos los días, un aporte de 1.000 hace 15 días.
        self.sano = self._cliente("Sano")
        filas = []
        for d in range(100, 0, -1):
            nd = 20000.0 if d > 15 else 21000.0
            tv = 20000.0 + (100 - d) * 10 + (0 if d > 15 else 1000)
            filas.append((d, tv, nd, "cron"))
        # Y una foto del browser HOY, a media rueda: se dibuja, no es base.
        filas.append((0, 99999.0, 21000.0, "browser"))
        self._fotos(self.sano, filas)
        # Con hueco: medido hasta hace 60 días, nada, y otra vez los últimos 10.
        self.hueco = self._cliente("Con hueco")
        self._fotos(self.hueco,
                    [(d, 10000.0, 10000.0, "cron") for d in range(100, 59, -1)]
                    + [(d, 14000.0, 10000.0, "cron") for d in range(10, 0, -1)])

    def _mercado_sano(self, corte_dias):
        # base = cierre del día de corte; fin = último CIERRE (ayer), no la foto de hoy
        tv0 = 20000.0 + (100 - corte_dias) * 10 + (0 if corte_dias > 15 else 1000)
        nd0 = 20000.0 if corte_dias > 15 else 21000.0
        tv1, nd1 = 20000.0 + 99 * 10 + 1000, 21000.0
        return round((tv1 - tv0) - (nd1 - nd0), 2), round(nd1 - nd0, 2)

    def test_30_dias_deja_afuera_al_cliente_con_base_vieja(self):
        p = self._historia()["periods"]["30"]
        mercado, aportes = self._mercado_sano(30)
        self.assertEqual(p["clientes_medidos"], 1)
        self.assertEqual(p["clientes_con_hueco"], 1)
        self.assertEqual(p["mercado_usd"], mercado)      # sólo el sano: +290
        self.assertEqual(p["aportes_usd"], aportes)      # el aporte de 1.000 no es mercado
        self.assertEqual(p["corte"], self._dia(30))

    def test_90_dias_si_mide_al_cliente_con_hueco(self):
        """El piso no le borra el número a nadie que SÍ tiene base: a 90 días
        los dos tienen un cierre en el corte, y la suba del hueco cae ADENTRO."""
        p = self._historia()["periods"]["90"]
        mercado, aportes = self._mercado_sano(90)
        self.assertEqual(p["clientes_medidos"], 2)
        self.assertEqual(p["mercado_usd"], round(mercado + 4000.0, 2))
        self.assertEqual(p["aportes_usd"], aportes)

    def test_ventana_mas_larga_que_la_historia_dice_lo_mismo_que_todo(self):
        """La historia medida empieza hace 100 días: "6M" y "1A" muestran la
        misma curva que "Todo", y tienen que decir lo mismo."""
        p = self._historia()["periods"]
        for k in ("180", "365"):
            for campo in ("mercado_usd", "aportes_usd", "clientes_medidos"):
                self.assertEqual(p[k][campo], p["todo"][campo], (k, campo))
        self.assertEqual(p["todo"]["corte"], self._dia(100))
        self.assertEqual(p["todo"]["clientes_medidos"], 2)

    def test_la_foto_de_media_rueda_se_dibuja_pero_no_cierra_el_periodo(self):
        d = self._historia()
        self.assertEqual(d["series"][-1]["date"], self._dia(0))
        self.assertIn(99999.0 + 14000.0, [p["aum_usd"] for p in d["series"]])
        # …y el período terminó en el último CIERRE: si la foto de hoy contara,
        # el mercado de 30 días sería decenas de miles.
        self.assertLess(d["periods"]["30"]["mercado_usd"], 1000)

    def test_la_pantalla_vieja_contaba_la_suba_del_hueco_en_30_dias(self):
        """Documenta el defecto con la serie: la resta punta contra punta de la
        pantalla le mete al período los 4.000 que subió el cliente del hueco."""
        serie = self._historia()["series"]
        corte = self._dia(30)
        i = next(k for k, p in enumerate(serie) if p["date"] >= corte)
        base, fin = serie[i - 1], serie[-2]          # fin = ayer (sin la foto de hoy)
        mercado_viejo = ((fin["aum_usd"] - base["aum_usd"])
                         - (fin["net_deposited_usd"] - base["net_deposited_usd"]))
        nuevo = self._historia()["periods"]["30"]["mercado_usd"]
        self.assertGreater(mercado_viejo - nuevo, 3900)


# ─── 2. El modal "Últimos 7 días" ────────────────────────────────────────────

class DetalleSieteDiasTest(_LibroBase):

    def setUp(self):
        super().setUp()
        self.sano = self._cliente("Sano")
        self._fotos(self.sano, [(7, 1000.0, 1000.0, "cron"), (0, 1100.0, 1000.0, "cron")])
        # Frenado: su última foto antes del corte es de hace 30 días.
        self.viejo = self._cliente("Viejo")
        self._fotos(self.viejo, [(30, 1000.0, 1000.0, "cron"), (0, 1500.0, 1000.0, "cron")])

    def _detalle(self):
        r = self.http.get("/api/advisor/book/detail", headers=self._hdr())
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_base_de_30_dias_no_entra_en_7_dias(self):
        d = self._detalle()
        viejo = next(c for c in d["clients"] if c["client_uid"] == self.viejo)
        self.assertNotEqual(viejo["state"], "ok",
                            "publicó 30 días de mercado bajo el rótulo 'Últimos 7 días'")
        self.assertIsNone(viejo["delta_7d_usd"])
        self.assertEqual(d["delta_7d_usd"], 100.0)       # sólo el sano

    def test_el_modal_cierra_exacto_con_el_hero(self):
        d = self._detalle()
        book = self.http.get("/api/advisor/book", headers=self._hdr()).json()
        self.assertEqual(book["aum"]["delta_7d_usd"], d["delta_7d_usd"])
        suma = sum(c["delta_7d_usd"] for c in d["clients"] if c["delta_7d_usd"] is not None)
        self.assertEqual(round(suma, 2), d["delta_7d_usd"])


class DetalleConElRelojDeLas22Test(_LibroBase):
    """A las 22:00 de Buenos Aires ya es el día siguiente en UTC. El modal
    cortaba "hace 7 días" con UTC y el hero con la fecha argentina: cada uno
    elegía una base distinta y el modal dejaba de sumar lo que dice el hero."""

    def setUp(self):
        _orig = fechas.ahora_art
        # addCleanup y no tearDown: si el setUp falla a la mitad, tearDown no corre
        # y el reloj falso quedaría puesto para el resto de la suite.
        self.addCleanup(setattr, fechas, "ahora_art", _orig)
        utc_hoy = datetime.utcnow().date()
        # Hoy en Argentina = un día ANTES que en UTC, como entre las 21 y las 24.
        fechas.ahora_art = lambda: datetime(utc_hoy.year, utc_hoy.month, utc_hoy.day, 22, 0) - timedelta(days=1)
        super().setUp()
        self.c = self._cliente("Juan P")
        self._fotos(self.c, [(7, 1000.0, 1000.0, "cron"),
                             (6, 1200.0, 1000.0, "cron"),
                             (0, 1300.0, 1000.0, "cron")])

    def test_el_corte_es_el_dia_argentino(self):
        d = self.http.get("/api/advisor/book/detail", headers=self._hdr()).json()
        juan = next(c for c in d["clients"] if c["client_uid"] == self.c)
        self.assertEqual(juan["delta_7d_usd"], 300.0)    # contra el cierre de hace 7 días ART
        book = self.http.get("/api/advisor/book", headers=self._hdr()).json()
        self.assertEqual(book["aum"]["delta_7d_usd"], d["delta_7d_usd"])


# ─── 3. El mail de cierre ────────────────────────────────────────────────────

class MailDeCierreRotuloTest(_LibroBase):
    """El Δ del mail compara el valor EN VIVO contra el último cierre medido de
    cada cliente. Si ese cierre es de hace 3 días, no es "hoy"."""

    def setUp(self):
        super().setUp()
        self.frenado = self._cliente("Frenado")
        # ⚠️ net_deposited=0 A PROPÓSITO: el mail descuenta (aportado vivo −
        # aportado de la base), y un cliente sin operaciones tiene aportado vivo 0.
        # Una base con 10.000 se leería como un retiro de 10.000.
        self._fotos(self.frenado, [(5, 10000.0, 0.0, "cron"),
                                   (4, 10000.0, 0.0, "cron"),
                                   (3, 10000.0, 0.0, "cron")])

    def _brief(self, vivos):
        import advisor_brief
        _orig = advisor_brief.live_book_values
        advisor_brief.live_book_values = lambda c, i, p: vivos
        conn = main.get_db()
        try:
            return advisor_brief.build_brief(conn, self.asesor, "close")
        finally:
            advisor_brief.live_book_values = _orig
            conn.close()

    def _mail(self, brief):
        from billing import emails
        capt = {}
        _o = emails._send
        emails._send = lambda to, subj, html_, text, **k: (capt.update(s=subj, h=html_, t=text), True)[1]
        try:
            emails.send_advisor_brief(to="asesor@rendi.test", user_name="Nico", brief=brief)
        finally:
            emails._send = _o
        return capt

    def test_base_de_hace_3_dias_no_se_llama_hoy(self):
        b = self._brief({self.frenado: 10300.0})
        self.assertEqual(b["day"]["dias"], 3)
        self.assertEqual(b["day"]["as_of_base"], self._dia(3))
        self.assertEqual(b["day"]["rotulo"], "en los últimos 3 días")
        m = self._mail(b)
        for parte in ("s", "t"):
            self.assertIn("en los últimos 3 días +US$", m[parte], m[parte])
            self.assertNotIn("hoy +US$", m[parte], m[parte])
        # Y el ranking tampoco dice "del día" para un tramo de 3 días.
        sec = next(s for s in b["sections"] if s["title"] == "Cómo cerraron tus clientes")
        self.assertNotIn("del día", sec["items"][0]["detail"])
        self.assertIn("en los últimos 3 días", sec["items"][0]["detail"])

    def test_con_el_cierre_de_ayer_sigue_diciendo_hoy(self):
        sano = self._cliente("Sano")
        self._fotos(sano, [(2, 5000.0, 0.0, "cron"), (1, 5000.0, 0.0, "cron")])
        b = self._brief({sano: 5100.0})
        self.assertEqual(b["day"]["dias"], 1)
        self.assertEqual(b["day"]["rotulo"], "hoy")
        m = self._mail(b)
        self.assertIn("hoy +US$", m["t"])
        sec = next(s for s in b["sections"] if s["title"] == "Cómo cerraron tus clientes")
        self.assertIn("el mejor del día", sec["items"][0]["detail"])

    def test_un_cliente_frenado_no_le_cambia_el_rotulo_al_libro(self):
        """El total es de los clientes medidos contra el cierre de ayer, y dice
        "hoy". El frenado va APARTE, con su propio rótulo: no se esconde, pero
        tampoco convierte el día del libro en "los últimos 3 días"."""
        sano = self._cliente("Sano")
        self._fotos(sano, [(1, 5000.0, 0.0, "cron")])
        b = self._brief({self.frenado: 10300.0, sano: 5100.0})
        self.assertEqual(b["day"]["dias"], 1)
        self.assertEqual(b["day"]["rotulo"], "hoy")
        self.assertEqual(b["day"]["delta_usd"], 100.0)        # sólo el sano
        self.assertEqual(b["day"]["clients_n"], 1)
        self.assertEqual(b["day"]["clients_otro_tramo"], 1)
        cerraron = next(s for s in b["sections"] if s["title"] == "Cómo cerraron tus clientes")
        self.assertEqual([it["label"] for it in cerraron["items"]], ["Sano"])
        viejos = next(s for s in b["sections"] if s["title"] == "Comparados contra un cierre más viejo")
        self.assertEqual(viejos["items"][0]["label"], "Frenado")
        self.assertIn("en los últimos 3 días", viejos["items"][0]["detail"])
        m = self._mail(b)
        self.assertIn("hoy +US$ 100", m["t"])
        self.assertIn("Frenado", m["t"])

    def test_un_deposito_no_es_ganancia(self):
        """Depositó 10.000 hoy y el mercado le sumó 300. El mail decía "+103%"."""
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO monthly_entries (user_id, year, month, broker, deposits, "
                "capital_inicio) VALUES (?,?,?,'global',10000,0)",
                (self.frenado, self.hoy.year, self.hoy.month))
            conn.commit()
        finally:
            conn.close()
        b = self._brief({self.frenado: 20300.0})
        self.assertEqual(b["day"]["delta_usd"], 300.0)
        self.assertEqual(b["day"]["pct"], 3.0)


# ─── Propagación: los otros lectores con el mismo defecto ────────────────────

class AlertaDeMovimientoRotuloTest(_LibroBase):
    """La alerta acepta una base de hasta 4 días (cubre un cron caído), pero
    decía "subió 6% hoy" y "desde el cierre de ayer"."""

    def _correr(self, vivos):
        import advisor_alerts as aa, advisor_brief
        from billing import emails as _emails
        mails = []
        conn = main.get_db()
        try:
            aa.set_config(conn, self.asesor, up_pct=5, down_pct=5, active=True)
            conn.commit()
            _l0, _p0, _e0 = (advisor_brief.live_book_values, main._send_push_to_user,
                             _emails.send_alert_email)
            advisor_brief.live_book_values = lambda c, i, p: vivos
            main._send_push_to_user = lambda uid, payload: 1
            _emails.send_alert_email = lambda **kw: (mails.append(kw), True)[1]
            try:
                aa.evaluate(conn, market_open=True, only_uid=self.asesor)
            finally:
                (advisor_brief.live_book_values, main._send_push_to_user,
                 _emails.send_alert_email) = _l0, _p0, _e0
        finally:
            conn.close()
        return mails

    def test_base_de_hace_3_dias(self):
        c = self._cliente("Juan P")
        self._fotos(c, [(3, 10000.0, 0.0, "cron")])
        mails = self._correr({c: 10600.0})
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails[0]["heading"],
                         "La cartera de Juan P subió 6,0% en los últimos 3 días")
        self.assertNotIn("ayer", mails[0]["detail"])
        self.assertIn("hace 3 días", mails[0]["detail"])

    def test_base_de_ayer_no_cambia(self):
        c = self._cliente("Juan P")
        self._fotos(c, [(1, 10000.0, 0.0, "cron")])
        mails = self._correr({c: 10600.0})
        self.assertEqual(mails[0]["heading"], "La cartera de Juan P subió 6,0% hoy")
        self.assertIn("desde el cierre de ayer", mails[0]["detail"])


class GrupoEstanPerdiendoTest(_LibroBase):
    """"Están perdiendo" = la cartera vale menos que lo aportado. Si la última
    foto es la del import, su valor ES el costo: no dice si pierde o gana."""

    def _perdiendo(self):
        import advisor_groups as ag
        conn = main.get_db()
        try:
            return {c["client_uid"] for c in ag.evaluate(conn, self.asesor, {"losing": True})}
        finally:
            conn.close()

    def test_la_foto_al_costo_no_decide_si_pierde(self):
        solo_costo = self._cliente("Sólo importado")
        self._fotos(solo_costo, [(40, 800.0, 1000.0, "import")])
        medido = self._cliente("Medido")
        self._fotos(medido, [(1, 800.0, 1000.0, "cron")])
        got = self._perdiendo()
        self.assertIn(medido, got)
        self.assertNotIn(solo_costo, got,
                         "entró a 'están perdiendo' por una foto valuada al costo")

    def test_abrir_la_app_hoy_no_lo_saca_del_grupo(self):
        """La app escribe una foto de media rueda cuando alguien abre la cuenta
        (el cliente, o el asesor entrando a su vista). No es un cierre: con "la
        última foto y que sea apta", el cliente salía del grupo —y de las alertas
        atadas a él— justo el día que el asesor lo miraba."""
        c = self._cliente("Abrió hoy")
        self._fotos(c, [(1, 800.0, 1000.0, "cron"), (0, 790.0, 1000.0, "browser")])
        self.assertIn(c, self._perdiendo())


# ─── Auditoría: los casos que encontraron los dos auditores ──────────────────

class EvolucionConAltasEscalonadasTest(_LibroBase):
    """Un libro joven: un cliente desde hace 120 días, otro entra hace 50 y otro
    hace 20. Dejar afuera a los que entraron hacía que "3M" midiera a UNO de tres
    al lado de una curva que muestra a los tres."""

    def setUp(self):
        super().setUp()
        self.a = self._cliente("A")
        self._fotos(self.a, [(d, 1000.0 + (120 - d), 1000.0, "cron") for d in range(120, 0, -1)])
        self.b = self._cliente("B")
        self._fotos(self.b, [(d, 5000.0 + (50 - d) * 2, 5000.0, "cron") for d in range(50, 0, -1)])
        self.c = self._cliente("C")
        self._fotos(self.c, [(d, 9000.0 + (20 - d) * 3, 9000.0, "cron") for d in range(20, 0, -1)])

    def test_los_que_entraron_se_miden_desde_su_primera_foto(self):
        p = self._historia()["periods"]["90"]
        self.assertEqual(p["clientes_medidos"], 3)
        self.assertEqual(p["clientes_entraron"], 2)
        # A: de 1030 (día 90) a 1119 · B: de 5000 a 5098 · C: de 9000 a 9057.
        self.assertEqual(p["mercado_usd"], 89.0 + 98.0 + 57.0)
        # Su capital de ENTRADA no es mercado ni aporte: es el "+2 clientes".
        self.assertEqual(p["aportes_usd"], 0.0)


class EvolucionClienteQueDejoDeMedirseTest(_LibroBase):
    """Medido desde hace 120 días hasta hace 60, y después nada. En "3M" ese
    cliente cubre 30 de los 90 días: no "mide los últimos 90"."""

    def test_el_cierre_tambien_tiene_que_cubrir_el_periodo(self):
        frenado = self._cliente("Frenado")
        self._fotos(frenado, [(d, 1000.0 + (120 - d) * 10, 1000.0, "cron")
                              for d in range(120, 59, -1)])
        sano = self._cliente("Sano")
        self._fotos(sano, [(d, 2000.0, 2000.0, "cron") for d in range(120, 0, -1)])
        p = self._historia()["periods"]["90"]
        self.assertEqual(p["clientes_medidos"], 1)
        self.assertEqual(p["clientes_con_hueco"], 1)
        self.assertEqual(p["mercado_usd"], 0.0)


class EvolucionPrimerPuntoDeMediaRuedaTest(_LibroBase):
    """El primer punto de la curva es una foto de la app abierta (ese día el
    cron no corrió) y los cierres empiezan al día siguiente. "Todo" no puede
    decir que no hay con qué medir."""

    def test_todo_mide_desde_el_primer_cierre(self):
        c = self._cliente("Juan P")
        self._fotos(c, [(101, 1000.0, 1000.0, "browser")]
                    + [(d, 1000.0 + (100 - d) * 5, 1000.0, "cron") for d in range(100, 0, -1)])
        p = self._historia()["periods"]["todo"]
        self.assertEqual(p["corte"], self._dia(101))
        self.assertEqual(p["clientes_medidos"], 1)
        self.assertEqual(p["mercado_usd"], 495.0)


class DetalleConFotoDeMediaRuedaTest(_LibroBase):
    """Alguien abrió la cuenta hoy: la última foto es de media rueda. El cliente
    no "recién empezó a medirse" — se mide hasta su último cierre."""

    def _detalle(self):
        r = self.http.get("/api/advisor/book/detail", headers=self._hdr())
        self.assertEqual(r.status_code, 200, r.text)
        return {c["client_uid"]: c for c in r.json()["clients"]}, r.json()

    def test_abrir_la_app_hoy_no_lo_saca_de_7_dias(self):
        c = self._cliente("Abrió hoy")
        self._fotos(c, [(d, 1000.0 + (10 - d) * 10, 1000.0, "cron") for d in range(10, 0, -1)]
                    + [(0, 5000.0, 1000.0, "browser")])
        por, d = self._detalle()
        self.assertEqual(por[c]["state"], "ok")
        self.assertEqual(por[c]["delta_7d_usd"], 60.0)    # cierre de hace 7 → cierre de ayer
        self.assertEqual(por[c]["value_usd"], 5000.0)     # el capital sí es la última foto
        book = self.http.get("/api/advisor/book", headers=self._hdr()).json()
        self.assertEqual(book["aum"]["delta_7d_usd"], d["delta_7d_usd"])

    def test_cron_caido_10_dias_es_hueco_no_cliente_nuevo(self):
        c = self._cliente("Sin cron")
        self._fotos(c, [(d, 1000.0, 1000.0, "cron") for d in range(60, 10, -1)])
        por, _ = self._detalle()
        self.assertEqual(por[c]["state"], "gap")


class MejorPeorYCaidaTest(_LibroBase):
    """La tarjeta Mejor/Peor (y el ranking de la IA del libro) y la cola "Su
    ganancia cayó X%" también tomaban la ÚLTIMA foto."""

    def _book(self):
        r = self.http.get("/api/advisor/book", headers=self._hdr())
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_abrir_la_app_hoy_no_lo_saca_de_mejor_peor(self):
        c = self._cliente("Abrió hoy")
        self._fotos(c, [(1, 1200.0, 1000.0, "cron"), (0, 1210.0, 1000.0, "browser")])
        dist = self._book()["distribution"]
        self.assertIsNotNone(dist)
        self.assertEqual(dist["best"]["client_uid"], c)
        self.assertEqual(dist["best"]["ret_pct"], 20.0)
        chat = main._advisor_book_chat_context(self.asesor)
        self.assertEqual(chat["clients"][0]["ret_pct"], 20.0)   # la IA ve lo mismo

    def test_la_foto_del_import_no_fabrica_una_caida(self):
        """Pico de resultado 2.000 medido; hoy, a mercado, 1.900 (−5%). La foto del
        import de hoy vale al COSTO 1.100: con ella el libro decía "Su ganancia
        cayó 95%" y el mail "Para llamar hoy" lo repetía."""
        c = self._cliente("Importó hoy")
        self._fotos(c, [(10, 3000.0, 1000.0, "cron"), (1, 2900.0, 1000.0, "cron"),
                        (0, 1100.0, 1000.0, "import")])
        colas = {q["client_uid"]: q for q in self._book()["queues"]}
        razones = [r["kind"] for r in (colas.get(c) or {}).get("reasons", [])]
        self.assertNotIn("drawdown", razones)


class InformeConBaseViejaTest(_LibroBase):
    """El informe que FIRMA el asesor: con la base 8 días antes del arranque, los
    números son reales pero la ventana no es la del título. Con el piso de 10
    días se publicaba sin ninguna nota."""

    def test_base_de_8_dias_lleva_la_nota(self):
        c = self._cliente("Juan P")
        self._fotos(c, [(38, 1000.0, 1000.0, "cron"), (1, 1100.0, 1000.0, "cron")])
        main._rate_store.pop(f"testclient|advreport:{self.asesor}", None)
        r = self.http.post("/api/advisor/reports/generate",
                           json={"period_start": self._dia(30), "period_end": self._dia(0)},
                           headers=self._hdr())
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()["reports"][0]["token"]
        main._rate_store.pop("testclient|report_pub_ip", None)
        p = self.http.get(f"/api/reports/public/{token}").json()["report"]
        self.assertEqual(p["base_date"], self._dia(38))
        self.assertEqual(p["base_note"], "stale")


class ClasificacionIgualQueLaListaTest(_LibroBase):
    """La evolución del libro pide `holdings_json` como bandera (1/NULL) y no el
    JSON entero. Tiene que clasificar EXACTAMENTE igual que `GET /api/snapshots`
    sobre la misma serie, incluidas las fotos viejas sin `source` — con y sin
    composición, sueltas y en racha diaria."""

    def test_misma_clase_y_mismo_apto_para_cada_foto(self):
        c = self._cliente("Mezcla")
        conn = main.get_db()
        try:
            filas = [(60 - i, 1000.0 + i, None, 1400.0, None) for i in range(8)]   # racha legacy
            filas += [(45, 1100.0, None, 1400.0, '[{"asset":"AAPL"}]'),        # legacy con composición
                      (40, 1100.0, None, 1400.0, None),                         # legacy suelta
                      (30, 900.0, "import", None, None),
                      (5, 1200.0, "cron", 1400.0, '[{"asset":"AAPL"}]'),
                      (0, 1210.0, "browser", 1400.0, None)]
            for dias, tv, src, fx, hold in filas:
                conn.execute(
                    "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
                    "net_deposited, source, fx_to_usd_blue, holdings_json) VALUES (?,?,?,?,?,?,?,?)",
                    (c, self._dia(dias), tv, tv, 1000.0, src, fx, hold))
            twr.estampar_base(conn, [c])
            conn.commit()
            libro = main._serie_clasificada_de_clientes(conn, [c])[c]
        finally:
            conn.close()
        main.app.dependency_overrides[main.get_effective_user] = lambda: c
        try:
            lista = self.http.get("/api/snapshots?days=3650").json()
        finally:
            main.app.dependency_overrides.clear()
        de_la_lista = {f["date"]: (f["clase"], f["apto"]) for f in lista}
        del_libro = {f["date"]: (f["clase"], f["apto"]) for f in libro}
        self.assertEqual(del_libro, de_la_lista)


if __name__ == "__main__":
    unittest.main()
