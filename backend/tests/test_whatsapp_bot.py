"""El bot de WhatsApp (whatsapp.py + «WhatsApp: el bot» en main.py).

Lo que se prueba, de afuera hacia adentro:
  · lo puro: la firma de Meta, la lectura del aviso, el código, el formato;
  · el timbre (/api/whatsapp/webhook): el alta, la firma, que descarta rápido;
  · la vinculación por código desde la app hasta el WhatsApp;
  · atender un mensaje: duplicados, número desconocido, plan, tipos que no se
    leen, y la vuelta completa con un modelo de mentira — por el MISMO camino que
    la app (`_ai_chat_core`), con la foto armada por el servidor y la respuesta
    sin el bloque técnico.

Nada sale a la red: bajo pytest `whatsapp._post` anota en `whatsapp.ENVIADOS`.

Corre con: cd backend && python3 -m pytest tests/test_whatsapp_bot.py
"""
import hashlib
import hmac
import json
import os
import sys
import time
import unittest
import uuid
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main  # noqa: E402
import whatsapp as wa  # noqa: E402
import foto_cartera  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

SECRETO = "secreto-de-prueba"
TEL = "5492914000001"


def _aviso(texto=None, wa_id=None, tel=TEL, tipo="text", boton=None, nombre="Nico"):
    msg = {"from": tel, "id": wa_id or f"wamid.{uuid.uuid4().hex}", "timestamp": "1700000000",
           "type": tipo}
    if tipo == "text":
        msg["text"] = {"body": texto}
    elif tipo == "interactive":
        msg["interactive"] = {"type": "button_reply", "button_reply": {"id": boton, "title": "x"}}
    elif tipo == "audio":
        msg["audio"] = {"id": "media-1", "mime_type": "audio/ogg; codecs=opus"}
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{
        "field": "messages", "value": {
            "messaging_product": "whatsapp",
            "contacts": [{"profile": {"name": nombre}, "wa_id": tel}],
            "messages": [msg]}}]}]}


def _firmar(cuerpo: bytes, secreto=SECRETO) -> str:
    return "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


class _Txt:
    type = "text"
    def __init__(self, t): self.text = t
    def model_dump(self): return {"type": "text", "text": self.text}


class _Resp:
    def __init__(self, content, stop="end_turn"):
        self.content, self.stop_reason, self.usage = content, stop, None


# ── Lo puro ──────────────────────────────────────────────────────────────────

class PuroTest(unittest.TestCase):

    def test_firma(self):
        cuerpo = b'{"hola": 1}'
        self.assertTrue(wa.firma_valida(cuerpo, _firmar(cuerpo), SECRETO))
        self.assertTrue(wa.firma_valida(cuerpo, _firmar(cuerpo)[7:], SECRETO))   # sin prefijo
        self.assertFalse(wa.firma_valida(cuerpo + b" ", _firmar(cuerpo), SECRETO))
        self.assertFalse(wa.firma_valida(cuerpo, None, SECRETO))
        self.assertFalse(wa.firma_valida(cuerpo, _firmar(cuerpo), ""))           # sin secreto: nunca válida

    def test_lee_texto_boton_y_audio(self):
        m = wa.mensajes_del_aviso(_aviso("  cómo vengo "))
        self.assertEqual(len(m), 1)
        self.assertEqual((m[0].tipo, m[0].texto, m[0].telefono, m[0].nombre), ("texto", "cómo vengo", TEL, "Nico"))
        b = wa.mensajes_del_aviso(_aviso(tipo="interactive", boton=wa.BOTON_SI))[0]
        self.assertEqual((b.tipo, b.texto), ("boton", "sí"))
        a = wa.mensajes_del_aviso(_aviso(tipo="audio"))[0]
        self.assertEqual((a.tipo, a.media_id), ("audio", "media-1"))

    def test_los_avisos_de_estado_no_son_mensajes(self):
        estado = {"entry": [{"changes": [{"value": {"statuses": [{"id": "x", "status": "read"}]}}]}]}
        self.assertEqual(wa.mensajes_del_aviso(estado), [])
        self.assertEqual(wa.mensajes_del_aviso({}), [])
        self.assertEqual(wa.mensajes_del_aviso("basura"), [])

    def test_codigo(self):
        c = wa.codigo_nuevo()
        self.assertEqual(len(c), 6)
        self.assertNotIn("0", c); self.assertNotIn("O", c); self.assertNotIn("1", c)
        self.assertEqual(wa.codigo_del_texto(f"RENDI {c}"), c)
        self.assertEqual(wa.codigo_del_texto(f"hola, rendi {c.lower()}!"), c)
        self.assertEqual(wa.codigo_del_texto(f"  {c.lower()} "), c)          # el código a secas
        self.assertIsNone(wa.codigo_del_texto("hola"))
        self.assertIsNone(wa.codigo_del_texto(""))
        # Una palabra de 6 letras adentro de una frase NO es un código.
        self.assertIsNone(wa.codigo_del_texto("cuánto tengo en VENTAS este mes"))
        self.assertIsNone(wa.codigo_del_texto("mi código es ABC234"))
        self.assertIn(f"text=RENDI%20{c}", wa.link_para_vincular(c, "5491100000000"))
        self.assertEqual(wa.link_para_vincular(c, ""), "")

    def test_formato_para_whatsapp(self):
        t = wa.texto_para_whatsapp('Tu cartera vale **US$ 10**.\n\n\n\nSubió.\n---RENDI---{"voz":"x"}')
        self.assertEqual(t, "Tu cartera vale *US$ 10*.\n\nSubió.")
        self.assertEqual(wa.texto_para_whatsapp("Hola --- RENDI --- {}"), "Hola")
        partes = wa.partir("a" * 10 + "\n" + "b" * 10, maximo=12)
        self.assertEqual(partes, ["a" * 10, "b" * 10])
        self.assertEqual(wa.partir("", 10), [])

    def test_celular_argentino_sin_el_9(self):
        self.assertEqual(wa.otra_forma_argentina("5493584011063"), "543584011063")
        self.assertIsNone(wa.otra_forma_argentina("543584011063"))     # ya sin el 9
        self.assertIsNone(wa.otra_forma_argentina("15551887611"))      # no es de Argentina

    def test_no_autorizado_reintenta_sin_el_9(self):
        """Meta rechaza 549… con «no autorizado» (131030): se reintenta una vez
        sin el 9. Cualquier otro error, o un número de otro país, no reintenta."""
        wa.ENVIADOS.clear()
        wa._FALLAR_EN_PRUEBAS.clear()
        self.addCleanup(wa._FALLAR_EN_PRUEBAS.clear)
        wa._FALLAR_EN_PRUEBAS["5493584011063"] = wa.ERROR_NO_AUTORIZADO
        ids = wa.enviar_texto("5493584011063", "hola")
        self.assertEqual([p["to"] for p in wa.ENVIADOS], ["5493584011063", "543584011063"])
        self.assertEqual(len(ids), 1)
        # Otro error: no se reintenta.
        wa.ENVIADOS.clear()
        wa._FALLAR_EN_PRUEBAS["5493584011063"] = 131047
        self.assertEqual(wa.enviar_texto("5493584011063", "hola"), [])
        self.assertEqual(len(wa.ENVIADOS), 1)
        # Otro país: tampoco.
        wa.ENVIADOS.clear()
        wa._FALLAR_EN_PRUEBAS["16315551181"] = wa.ERROR_NO_AUTORIZADO
        self.assertEqual(wa.enviar_texto("16315551181", "hola"), [])
        self.assertEqual(len(wa.ENVIADOS), 1)

    def test_el_resumen_de_la_foto_es_el_del_navegador(self):
        """Los casos de frontend/src/utils/aiSummary.test.js, en Python."""
        positions = [{"invested": 100.5, "is_cash": 0}, {"invested": 50, "is_cash": 1}, None,
                     {"invested": None, "is_cash": 0}]
        monthly = [{"broker": "global", "pnl_realized": 10, "deposits": 1000, "withdrawals": 200},
                   {"broker": "Cocos", "pnl_realized": 10, "deposits": 1000, "withdrawals": 200},
                   {"broker": "global", "pnl_realized": -2.5}]
        r = foto_cartera.resumen(positions, monthly)
        self.assertEqual(r, {"total_invested_usd": 100.5, "open_positions_count": 2,
                             "cash_lines_count": 1, "months_count": 2, "sum_pnl_realized": 7.5,
                             "sum_deposits": 1000.0, "sum_withdrawals": 200.0})
        self.assertEqual(foto_cartera.resumen(None, None)["months_count"], 0)
        # Y las llaves son las que el servidor deja pasar.
        src = open(os.path.join(os.path.dirname(__file__), "..", "main.py"), encoding="utf-8").read()
        for k in r:
            self.assertIn(f'"{k}"', src.split("_SUMMARY_NUMERIC_KEYS = {", 1)[1][:400], k)

    def test_el_plan_lo_declara(self):
        from ai import plan
        self.assertIn(wa.FEATURE, plan.FEATURE_IDS)
        self.assertTrue(plan.PLAN_LIMITS["pro"]["can_access"][wa.FEATURE])
        self.assertFalse(plan.PLAN_LIMITS["plus"]["can_access"][wa.FEATURE])
        self.assertFalse(plan.PLAN_LIMITS["free"]["can_access"][wa.FEATURE])


# ── El timbre y la vuelta entera ─────────────────────────────────────────────

class BotTest(unittest.TestCase):

    def setUp(self):
        self.env = patch.dict(os.environ, {"WHATSAPP_APP_SECRET": SECRETO, "WHATSAPP_VERIFY_TOKEN": "palabra",
                                           "WHATSAPP_NUMERO": "5491100000000", "WHATSAPP_TOKEN": "t",
                                           "WHATSAPP_PHONE_NUMBER_ID": "123"})
        self.env.start()
        self.addCleanup(self.env.stop)
        wa.ENVIADOS.clear()
        main._TRADE_DRAFT.clear()
        main._rate_store.clear()
        conn = main.get_db()
        self.addCleanup(conn.close)
        for t in ("whatsapp_mensajes", "whatsapp_vinculos", "positions", "brokers", "ai_usage_daily"):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM users WHERE email LIKE 'wa-%@rendi.test'")
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, tier, name) VALUES (?,?,1,?,?)",
            (f"wa-{uuid.uuid4().hex[:6]}@rendi.test", "x", "pro", "Nico Pussetto")).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)", (self.uid, "Cocos", "ARS"))
        conn.commit()
        self.conn = conn
        self.http = TestClient(main.app)
        self.headers = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self._interruptor(True)

    def _interruptor(self, on):
        main._poner_interruptor(self.conn, wa.INTERRUPTOR, on, self.uid)

    def _post_aviso(self, payload, firma=None):
        cuerpo = json.dumps(payload).encode()
        h = {"X-Hub-Signature-256": _firmar(cuerpo) if firma is None else firma}
        return self.http.post("/api/whatsapp/webhook", content=cuerpo, headers=h)

    def _texto_enviado(self, i=-1):
        p = wa.ENVIADOS[i]
        return p["text"]["body"] if p.get("type") == "text" else p["interactive"]["body"]["text"]

    # El alta y la firma
    def test_alta_del_webhook(self):
        r = self.http.get("/api/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "palabra",
                                                           "hub.challenge": "12345"})
        self.assertEqual((r.status_code, r.text), (200, "12345"))
        r = self.http.get("/api/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "otra",
                                                           "hub.challenge": "12345"})
        self.assertEqual(r.status_code, 403)

    def test_sin_firma_valida_se_rechaza(self):
        with patch.object(main, "_wa_atender") as atender:
            r = self._post_aviso(_aviso("hola"), firma="sha256=deadbeef")
            self.assertEqual(r.status_code, 403)
            r = self._post_aviso(_aviso("hola"), firma="")
            self.assertEqual(r.status_code, 403)
            atender.assert_not_called()

    def test_con_firma_contesta_rapido_y_atiende_aparte(self):
        with patch.object(main, "_wa_atender") as atender:
            r = self._post_aviso(_aviso("hola"))
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["mensajes"], 1)
            for _ in range(50):
                if atender.called:
                    break
                time.sleep(0.02)
            self.assertTrue(atender.called)
            self.assertEqual(atender.call_args[0][0].texto, "hola")
        # Un aviso de estado no dispara nada.
        with patch.object(main, "_wa_atender") as atender:
            r = self._post_aviso({"entry": [{"changes": [{"value": {"statuses": [{"status": "read"}]}}]}]})
            self.assertEqual((r.status_code, r.json()["mensajes"]), (200, 0))
            atender.assert_not_called()

    # La vinculación
    def test_vincular_por_codigo(self):
        e = self.http.get("/api/whatsapp/estado", headers=self.headers).json()
        self.assertEqual((e["encendido"], e["permitido"], e["vinculado"], e["codigo"]), (True, True, False, None))
        r = self.http.post("/api/whatsapp/codigo", headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        codigo = r.json()["codigo"]
        self.assertEqual(r.json()["texto_codigo"], f"RENDI {codigo}")
        self.assertIn("wa.me/5491100000000", r.json()["link"])

        # Llega desde un WhatsApp, con otras palabras alrededor.
        main._wa_atender(wa.mensajes_del_aviso(_aviso(f"hola, RENDI {codigo}"))[0])
        self.assertIn("quedó conectado", self._texto_enviado())
        self.assertIn("Nico", self._texto_enviado())
        e = self.http.get("/api/whatsapp/estado", headers=self.headers).json()
        self.assertEqual((e["vinculado"], e["telefono"], e["codigo"]), (True, "•••• 0001", None))

        # El mismo código no sirve dos veces.
        wa.ENVIADOS.clear()
        main._wa_atender(wa.mensajes_del_aviso(_aviso(f"RENDI {codigo}", tel="5492914000002"))[0])
        self.assertIn("no me sirve", self._texto_enviado())

        # Ya vinculado: no se genera otro código sin desconectar.
        self.assertEqual(self.http.post("/api/whatsapp/codigo", headers=self.headers).status_code, 400)
        # Desconectar borra el vínculo y la conversación.
        r = self.http.delete("/api/whatsapp/vinculo", headers=self.headers)
        self.assertEqual((r.status_code, r.json()["vinculado"]), (200, False))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS n FROM whatsapp_mensajes WHERE user_id=?",
                                           (self.uid,)).fetchone()["n"], 0)

    def test_codigo_vencido_no_vincula(self):
        codigo = self.http.post("/api/whatsapp/codigo", headers=self.headers).json()["codigo"]
        self.conn.execute("UPDATE whatsapp_vinculos SET codigo_vence_at='2000-01-01 00:00:00' WHERE user_id=?",
                          (self.uid,))
        self.conn.commit()
        main._wa_atender(wa.mensajes_del_aviso(_aviso(f"RENDI {codigo}"))[0])
        self.assertIn("vencido", self._texto_enviado())
        self.assertFalse(self.http.get("/api/whatsapp/estado", headers=self.headers).json()["vinculado"])

    def test_un_telefono_una_cuenta(self):
        self._vincular()
        otro = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,'pro')",
            (f"wa-{uuid.uuid4().hex[:6]}@rendi.test", "x")).lastrowid
        self.conn.commit()
        codigo = self.http.post("/api/whatsapp/codigo",
                                headers={"Authorization": f"Bearer {main.create_token(otro)}"}).json()["codigo"]
        wa.ENVIADOS.clear()
        main._wa_atender(wa.mensajes_del_aviso(_aviso(f"RENDI {codigo}"))[0])
        self.assertIn("otra cuenta", self._texto_enviado())

    def test_sin_plan_pro_no_hay_codigo(self):
        self.conn.execute("UPDATE users SET tier='plus' WHERE id=?", (self.uid,))
        self.conn.commit()
        r = self.http.post("/api/whatsapp/codigo", headers=self.headers)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["detail"]["error"], "solo_pro")
        self.assertFalse(self.http.get("/api/whatsapp/estado", headers=self.headers).json()["permitido"])

    def test_apagado_no_da_codigo(self):
        self._interruptor(False)
        r = self.http.post("/api/whatsapp/codigo", headers=self.headers)
        self.assertEqual((r.status_code, r.json()["detail"]["error"]), (403, "apagado"))

    # Atender
    def _vincular(self):
        codigo = self.http.post("/api/whatsapp/codigo", headers=self.headers).json()["codigo"]
        main._wa_atender(wa.mensajes_del_aviso(_aviso(f"RENDI {codigo}"))[0])
        wa.ENVIADOS.clear()

    def test_numero_desconocido(self):
        main._wa_atender(wa.mensajes_del_aviso(_aviso("cómo vengo", tel="5492914009999"))[0])
        self.assertIn("no está conectado", self._texto_enviado())
        self.assertIn("rendi.finance", self._texto_enviado())

    def test_el_mismo_aviso_dos_veces_se_atiende_una(self):
        self._vincular()
        m = wa.mensajes_del_aviso(_aviso("hola", wa_id="wamid.repetido"))[0]
        with patch.object(main, "_ai_chat_core", return_value={"reply": "Hola."}) as core:
            main._wa_atender(m)
            main._wa_atender(m)
            self.assertEqual(core.call_count, 1)
        self.assertEqual([p for p in wa.ENVIADOS if p.get("type") == "text"],
                         [{"messaging_product": "whatsapp", "to": TEL, "type": "text",
                           "text": {"preview_url": False, "body": "Hola."}}])

    def test_plan_que_no_alcanza(self):
        self._vincular()
        self.conn.execute("UPDATE users SET tier='free' WHERE id=?", (self.uid,))
        self.conn.commit()
        with patch.object(main, "_ai_chat_core") as core:
            main._wa_atender(wa.mensajes_del_aviso(_aviso("cómo vengo"))[0])
            core.assert_not_called()
        self.assertIn("plan Pro", self._texto_enviado())

    def test_cuenta_en_pausa_oye_que_elija_plan(self):
        """Prueba terminada sin elegir plan: no es «sólo Pro» (tenía Pro), es
        «elegí un plan». Desde la app tampoco se le da código."""
        self._vincular()
        self.conn.execute("UPDATE users SET tier='free', requires_plan=1 WHERE id=?", (self.uid,))
        self.conn.commit()
        with patch.object(main, "_ai_chat_core") as core:
            main._wa_atender(wa.mensajes_del_aviso(_aviso("cómo vengo"))[0])
            core.assert_not_called()
        self.assertIn("en pausa", self._texto_enviado())
        self.http.delete("/api/whatsapp/vinculo", headers=self.headers)
        r = self.http.post("/api/whatsapp/codigo", headers=self.headers)
        self.assertEqual((r.status_code, r.json()["detail"]["error"]), (403, "en_pausa"))

    def test_apagado_le_avisa_a_todos(self):
        self._vincular()
        self._interruptor(False)
        with patch.object(main, "_ai_chat_core") as core:
            main._wa_atender(wa.mensajes_del_aviso(_aviso("cómo vengo"))[0])
            core.assert_not_called()
        self.assertIn("mantenimiento", self._texto_enviado())
        # También a un número que no conocemos: no le mandamos a buscar un código
        # a una pantalla que dice «todavía no está disponible».
        wa.ENVIADOS.clear()
        main._wa_atender(wa.mensajes_del_aviso(_aviso("hola", tel="5492914009999"))[0])
        self.assertIn("mantenimiento", self._texto_enviado())

    def test_los_carteles_del_bot_no_son_charla(self):
        """«Por ahora leo texto» se guarda, pero no viaja al modelo como si lo
        hubiera dicho Mervall-E en la conversación."""
        self._vincular()
        main._wa_atender(wa.mensajes_del_aviso(_aviso(tipo="audio"))[0])
        with patch.object(main, "_ai_chat_core", return_value={"reply": "Hola."}) as core:
            main._wa_atender(wa.mensajes_del_aviso(_aviso("hola"))[0])
        mensajes = core.call_args[0][0].messages
        self.assertEqual([(x.role, x.content) for x in mensajes], [("user", "hola")])

    def test_lo_viejo_se_borra_solo(self):
        self._vincular()
        self.conn.execute("INSERT INTO whatsapp_mensajes (wa_id, telefono, user_id, direccion, tipo, texto, creado_at) "
                          "VALUES ('viejo', ?, ?, 'in', 'texto', 'hola de hace meses', '2020-01-01 00:00:00.000000')",
                          (TEL, self.uid))
        self.conn.commit()
        with patch.object(main, "_ai_chat_core", return_value={"reply": "Hola."}):
            main._wa_atender(wa.mensajes_del_aviso(_aviso("hola"))[0])
        self.assertIsNone(self.conn.execute("SELECT 1 FROM whatsapp_mensajes WHERE wa_id='viejo'").fetchone())

    def test_dos_mensajes_del_mismo_telefono_van_en_orden(self):
        """Dos preguntas casi juntas: la segunda se atiende cuando terminó la
        primera, y la ve en su historial."""
        import threading
        self._vincular()
        vistos = []

        def chat(data, uid, request=None, canal="app"):
            vistos.append([(x.role, x.content) for x in data.messages])
            time.sleep(0.15)
            return {"reply": f"R{len(vistos)}"}

        with patch.object(main, "_ai_chat_core", side_effect=chat):
            a = threading.Thread(target=main._wa_atender, args=(wa.mensajes_del_aviso(_aviso("uno"))[0],))
            b = threading.Thread(target=main._wa_atender, args=(wa.mensajes_del_aviso(_aviso("dos"))[0],))
            a.start(); time.sleep(0.03); b.start(); a.join(); b.join()
        self.assertEqual(vistos[0], [("user", "uno")])
        self.assertEqual(vistos[1], [("user", "uno"), ("assistant", "R1"), ("user", "dos")])

    def test_audio_e_imagen_todavia_no(self):
        self._vincular()
        with patch.object(main, "_ai_chat_core") as core:
            main._wa_atender(wa.mensajes_del_aviso(_aviso(tipo="audio"))[0])
            core.assert_not_called()
        self.assertIn("no audios", self._texto_enviado())

    def test_la_vuelta_entera_por_el_mismo_chat(self):
        """Pregunta → el chat de la app (`_ai_chat_core`, canal whatsapp, foto del
        servidor, mismo cupo) → respuesta sin el bloque técnico → guardada."""
        self._vincular()
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested, buy_price, currency, asset_type) "
            "VALUES (?,?,?,?,?,?,?,?)", (self.uid, "Cocos", "GGAL", 10, 85000, 8500, "ARS", "STOCK"))
        self.conn.commit()
        visto = {}

        def respuesta(**kw):
            visto["kw"] = kw
            return _Resp([_Txt('Tu cartera vale **US$ 60**, +1,8 % en el mes.\n---RENDI---{"voz":"x"}')])

        mc = MagicMock()
        mc.messages.create.side_effect = respuesta
        with patch.object(main, "_get_anthropic_client", return_value=mc), \
             patch.object(main, "_kick_bench_refresh", lambda: None):
            main._wa_atender(wa.mensajes_del_aviso(_aviso("cómo vengo", wa_id="wamid.pregunta"))[0])

        # Lo que viajó al modelo: el canal y la foto ARMADA POR EL SERVIDOR.
        kw = visto["kw"]
        sistema = "".join(b["text"] for b in kw["system"])
        self.assertIn("CANAL: esta conversación es por WhatsApp", sistema)
        primer_bloque = kw["messages"][0]["content"][0]["text"]
        self.assertIn('"asset":"GGAL"', primer_bloque.replace(" ", ""))
        self.assertIn('"months_count"', primer_bloque)
        # Un solo mensaje: lo de la vinculación no cuenta como charla.
        self.assertEqual(len(kw["messages"]), 1)
        self.assertEqual(kw["messages"][0]["content"][-1]["text"], "cómo vengo")
        # Lo que le llegó a la persona: sin el bloque técnico ni marcas de markdown
        # (el chat las quita para todos los canales, `_strip_markdown`).
        self.assertEqual(len(wa.ENVIADOS), 2)                    # leído + respuesta
        self.assertEqual(wa.ENVIADOS[0].get("status"), "read")
        self.assertEqual(self._texto_enviado(), "Tu cartera vale US$ 60, +1,8 % en el mes.")
        # Quedó guardada la ida y la vuelta.
        filas = self.conn.execute("SELECT direccion, texto FROM whatsapp_mensajes WHERE user_id=? "
                                  "ORDER BY creado_at", (self.uid,)).fetchall()
        self.assertEqual([r["direccion"] for r in filas][-2:], ["in", "out"])
        self.assertEqual(filas[-1]["texto"], "Tu cartera vale US$ 60, +1,8 % en el mes.")
        # Y descontó del MISMO cupo que la app.
        from ai import quota
        self.assertEqual(quota.can_chat(self.conn, self.uid)[1]["chat_count"], 1)

        # Segundo turno: la conversación anterior viaja como historial.
        wa.ENVIADOS.clear()
        with patch.object(main, "_get_anthropic_client", return_value=mc), \
             patch.object(main, "_kick_bench_refresh", lambda: None):
            main._wa_atender(wa.mensajes_del_aviso(_aviso("¿y en pesos?", wa_id="wamid.segunda"))[0])
        roles = [m["role"] for m in visto["kw"]["messages"]]
        self.assertEqual(roles, ["user", "assistant", "user"])
        self.assertEqual(visto["kw"]["messages"][1]["content"], "Tu cartera vale US$ 60, +1,8 % en el mes.")

    def test_si_queda_una_operacion_por_confirmar_van_botones(self):
        self._vincular()
        main._TRADE_DRAFT[self.uid] = {"status": "confirming", "ts": time.time(), "payload": {"price": 8500},
                                       "summary": "Compra de 10 GGAL a $ 8.500 en Cocos", "fields": {},
                                       "request_id": "x", "free_turns": 0}
        with patch.object(main, "_ai_chat_core",
                          return_value={"reply": "Anoto una compra de 10 GGAL a $ 8.500 en Cocos. ¿Confirmás?"}):
            main._wa_atender(wa.mensajes_del_aviso(_aviso("compré 10 GGAL a 8500"))[0])
        p = wa.ENVIADOS[-1]
        self.assertEqual(p["type"], "interactive")
        ids = [b["reply"]["id"] for b in p["interactive"]["action"]["buttons"]]
        self.assertEqual(ids, [wa.BOTON_SI, wa.BOTON_NO])
        # El botón vuelve como la palabra que el chat ya entiende.
        m = wa.mensajes_del_aviso(_aviso(tipo="interactive", boton=wa.BOTON_SI))[0]
        self.assertEqual(m.texto, "sí")

    def test_el_cupo_agotado_se_traduce_a_texto(self):
        self._vincular()
        from fastapi import HTTPException
        ex = HTTPException(429, {"error": "chat_quota_exceeded", "message": "Llegaste al máximo de consultas."})
        with patch.object(main, "_ai_chat_core", side_effect=ex):
            main._wa_atender(wa.mensajes_del_aviso(_aviso("cómo vengo"))[0])
        self.assertEqual(self._texto_enviado(), "Llegaste al máximo de consultas.")

    def test_si_todo_falla_igual_contesta(self):
        self._vincular()
        with patch.object(main, "_ai_chat_core", side_effect=RuntimeError("boom")):
            main._wa_atender(wa.mensajes_del_aviso(_aviso("cómo vengo"))[0])
        self.assertIn("No pude contestarte", self._texto_enviado())

    def test_admin_ve_el_interruptor(self):
        self.conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (self.uid,))
        self.conn.commit()
        r = self.http.get("/api/admin/whatsapp", headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["interruptor"]["encendido"])
        # Dice SI están las variables, nunca cuáles son.
        self.assertEqual((r.json()["configurado"], r.json()["firma"], r.json()["palabra"]), (True, True, True))
        self.assertIs(r.json()["palabra"], True)                    # un sí/no, no el valor
        with patch.dict(os.environ, {"WHATSAPP_VERIFY_TOKEN": ""}):
            self.assertFalse(self.http.get("/api/admin/whatsapp", headers=self.headers).json()["palabra"])
        r = self.http.post("/api/admin/whatsapp/interruptor", headers=self.headers, json={"encendido": False})
        self.assertEqual((r.status_code, r.json()["encendido"]), (200, False))


if __name__ == "__main__":
    unittest.main()
