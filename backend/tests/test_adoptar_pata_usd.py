"""Adoptar un broker ya existente como la cuenta en dólares de otro.

Cuando un broker en pesos necesita su sub-cuenta en dólares ("Cocos · USD") y ya
hay un broker con ese nombre que nadie creó como sub-cuenta —la persona lo creó
a mano—, `_ensure_usd_sibling` lo adopta: le pone el padre y la moneda USDT.
Hasta 2026-10-28 cambiaba sólo `brokers.currency` y la caja seguía marcada en
la moneda vieja. Con pesos adentro, los dólares que entraban después se sumaban
a esos pesos: $100.000 + US$500 quedaban como "100.500" en una caja que decía
'ARS' en un broker en dólares.

Las cuentas se arman por las puertas reales —alta de broker, depósito,
vista previa y confirmación de la plantilla de Rendi— y el chequeo se pide por
`/api/admin/check-invariantes`.

Corre con: cd backend && python3 -m pytest tests/test_adoptar_pata_usd.py
"""
import io
import os
import sys
import uuid

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main                                                          # noqa: E402
from fastapi.testclient import TestClient                            # noqa: E402

HDR = ("fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,"
       "comisiones,moneda,notas\n")
DOLARES_A_COCOS = "2026-01-06,DEPOSITO,Cocos,,,,500,,,,USD,\n"
PATA = "Cocos · USD"


class TestAdoptarLaPataUsd:

    @pytest.fixture(autouse=True)
    def _usuario(self):
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, is_admin) "
            "VALUES (?, 'x', 1, 1, 1)", (f"adoptar-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    # ── las puertas ──────────────────────────────────────────────────────────

    def crear_broker(self, nombre, moneda):
        r = self.client.post("/api/brokers", headers=self.h,
                             json={"name": nombre, "currency": moneda})
        assert r.status_code == 200, r.text
        return r.json()["id"]

    def depositar(self, broker, monto, moneda=None):
        return self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": broker, "direction": "deposit", "amount": monto,
            "currency": moneda})

    def vista_previa(self, filas):
        r = self.client.post(
            "/api/imports/preview", headers=self.h,
            files=[("files", ("plantilla.csv", io.BytesIO((HDR + filas).encode("utf-8")),
                              "text/csv"))],
            data={"format": "rendi_generic", "broker": "Cocos"})
        assert r.status_code == 200, r.text
        return r.json()

    def confirmar(self, sid):
        return self.client.post("/api/imports/confirm", headers=self.h, json={"session_id": sid})

    def importar(self, filas):
        """Vista previa sin errores + confirmación. Devuelve la confirmación."""
        prev = self.vista_previa(filas)
        assert prev["errors"] == []
        return self.confirmar(prev["session_id"])

    @staticmethod
    def codigos(prev):
        return sorted(e["code"] for e in prev["errors"])

    # ── lo que se mira ───────────────────────────────────────────────────────

    def sql(self, q, *a):
        conn = main.get_db()
        try:
            with conn:
                return [dict(r) for r in conn.execute(q, a).fetchall()]
        finally:
            conn.close()

    def broker(self, nombre):
        return self.sql("SELECT id, currency, parent_broker_id FROM brokers "
                        "WHERE user_id=? AND name=?", self.uid, nombre)[0]

    def caja(self, broker):
        filas = self.sql("SELECT asset, currency, invested FROM positions "
                         "WHERE user_id=? AND broker=? AND is_cash=1", self.uid, broker)
        assert len(filas) == 1, filas
        return filas[0]

    def cajas_cruzadas(self):
        r = self.client.get("/api/admin/check-invariantes", headers=self.h,
                            params={"user_id": self.uid})
        assert r.status_code == 200, r.text
        assert r.json()["chequeos_rotos"] == {}
        return [v for v in r.json()["violaciones"] if v["chequeo"] == "cash_moneda"]

    # ── los casos ────────────────────────────────────────────────────────────

    def no_se_toco(self, padre, saldo=100_000.0):
        assert self.broker(PATA)["currency"] == "ARS"
        assert self.broker(PATA)["parent_broker_id"] is None
        caja = self.caja(PATA)
        assert (caja["asset"], caja["invested"]) == ("ARS", saldo)
        assert not self.sql("SELECT 1 FROM brokers WHERE user_id=? AND parent_broker_id=?",
                            self.uid, padre)
        assert self.cajas_cruzadas() == []

    def test_con_pesos_adentro_la_vista_previa_lo_marca(self):
        """El caso del bug: "Cocos · USD" creado a mano en pesos, con $100.000.
        Adoptarlo convertía esos pesos en dólares. La vista previa marca la fila
        en dólares con el motivo y qué hacer; confirmar lo que queda no toca nada."""
        padre = self.crear_broker("Cocos", "ARS")
        self.crear_broker(PATA, "ARS")
        assert self.depositar(PATA, 100_000).status_code == 200

        prev = self.vista_previa(DOLARES_A_COCOS)

        assert self.codigos(prev) == ["SIN_CUENTA_EN_DOLARES"], prev["errors"]
        assert "Renombralo" in prev["errors"][0]["message"]
        assert self.confirmar(prev["session_id"]).status_code == 200
        self.no_se_toco(padre)

    def test_si_entran_pesos_entre_la_vista_previa_y_el_confirm_rechaza_entero(self):
        """La vista previa estaba limpia (la cuenta vacía), pero antes de confirmar
        le entraron pesos. El confirm no la adopta: 409 y el import entero se deshace."""
        padre = self.crear_broker("Cocos", "ARS")
        self.crear_broker(PATA, "ARS")
        prev = self.vista_previa(DOLARES_A_COCOS)
        assert prev["errors"] == []
        assert self.depositar(PATA, 100_000).status_code == 200

        r = self.confirmar(prev["session_id"])

        assert r.status_code == 409, r.text
        assert PATA in r.json()["detail"] and "Renombralo" in r.json()["detail"]
        self.no_se_toco(padre)

    def test_el_mismo_archivo_no_puede_mandarle_pesos_a_la_que_va_a_adoptar(self):
        """El hueco que dejaba mirar sólo la base: "Cocos · USD" vacía, y un archivo
        con pesos para ella y dólares para "Cocos". Se adoptaba vacía y los pesos
        entraban después a la caja en dólares, sin que nada avisara. Ahora la fila
        en pesos se marca en la vista previa, como en cualquier sub-cuenta."""
        padre = self.crear_broker("Cocos", "ARS")
        self.crear_broker(PATA, "ARS")

        prev = self.vista_previa(f"2026-01-05,DEPOSITO,{PATA},,,,100000,,,,ARS,\n"
                                 + DOLARES_A_COCOS)

        assert self.codigos(prev) == ["PESOS_EN_BROKER_EN_DOLARES"], prev["errors"]
        assert "Los pesos van a «Cocos»" in prev["errors"][0]["message"]
        assert self.confirmar(prev["session_id"]).status_code == 200
        assert self.broker(PATA)["parent_broker_id"] == padre
        assert self.caja(PATA) == {"asset": "USDT", "currency": "USD", "invested": 500.0}
        assert self.cajas_cruzadas() == []

    def test_usuario_nuevo_con_pesos_a_la_sub_cuenta_desde_el_archivo(self):
        """Lo mismo sin crear nada a mano: el import crea "Cocos" y "Cocos · USD"."""
        prev = self.vista_previa("2026-01-05,DEPOSITO,Cocos,,,,1000000,,,,ARS,\n"
                                 f"2026-01-05,DEPOSITO,{PATA},,,,100000,,,,ARS,\n"
                                 + DOLARES_A_COCOS)
        assert self.codigos(prev) == ["PESOS_EN_BROKER_EN_DOLARES"], prev["errors"]
        assert self.confirmar(prev["session_id"]).status_code == 200
        assert self.caja("Cocos")["invested"] == 1_000_000.0
        # La caja nace con la pata ya en dólares: `currency` vacía hasta que el
        # arranque la complete desde el rótulo (ver test_invariantes.py).
        caja = self.caja(PATA)
        assert (caja["asset"], caja["invested"]) == ("USDT", 500.0)
        assert self.cajas_cruzadas() == []

    def test_la_que_esta_en_dolares_no_se_pasa_a_pesos_por_un_archivo(self):
        """"Cocos · USD" en dólares y vacía: los pesos que le manda el archivo
        la pasaban a pesos en la vista previa (la "curación"), y el confirm la volvía
        a dólares con los pesos adentro."""
        self.crear_broker("Cocos", "ARS")
        self.crear_broker(PATA, "USD")
        prev = self.vista_previa(f"2026-01-05,DEPOSITO,{PATA},,,,100000,,,,ARS,\n"
                                 + DOLARES_A_COCOS)
        assert self.codigos(prev) == ["PESOS_EN_BROKER_EN_DOLARES"], prev["errors"]
        assert self.broker(PATA)["currency"] == "USD"
        assert self.confirmar(prev["session_id"]).status_code == 200
        assert self.caja(PATA)["invested"] == 500.0
        assert self.cajas_cruzadas() == []

    def test_la_otra_puerta_tambien_rechaza(self):
        """Dólares "en Cocos" cargados a mano (`/api/cash/flow` con moneda USD)
        entran por la misma adopción (`_pata_de_la_moneda`): mismo rechazo."""
        self.crear_broker("Cocos", "ARS")
        self.crear_broker(PATA, "ARS")
        assert self.depositar(PATA, 100_000).status_code == 200

        r = self.depositar("Cocos", 500, "USD")

        assert r.status_code == 409, r.text
        assert self.broker(PATA)["currency"] == "ARS"
        assert self.caja(PATA)["invested"] == 100_000.0
        assert self.cajas_cruzadas() == []

    def test_vacio_se_adopta_y_su_caja_pasa_a_dolares(self):
        """Creado en pesos pero sin nada adentro (la caja en cero que crea el alta):
        no hay qué reinterpretar. Se adopta y la caja cambia de moneda con él."""
        padre = self.crear_broker("Cocos", "ARS")
        self.crear_broker(PATA, "ARS")

        r = self.importar(DOLARES_A_COCOS)

        assert r.status_code == 200, r.text
        assert self.broker(PATA)["currency"] == "USDT"
        assert self.broker(PATA)["parent_broker_id"] == padre
        assert self.caja(PATA) == {"asset": "USDT", "currency": "USD", "invested": 500.0}
        assert self.cajas_cruzadas() == []
        main.init_db()
        assert self.cajas_cruzadas() == []

    def test_en_dolares_se_adopta_con_sus_dolares(self):
        """Creado a mano en dólares, con US$300: son dólares, adoptarlo no
        reinterpreta nada. Los US$500 se suman y la caja queda marcada como la de
        cualquier sub-cuenta '· USD'."""
        padre = self.crear_broker("Cocos", "ARS")
        self.crear_broker(PATA, "USD")
        assert self.depositar(PATA, 300).status_code == 200

        r = self.importar(DOLARES_A_COCOS)

        assert r.status_code == 200, r.text
        assert self.broker(PATA)["parent_broker_id"] == padre
        assert self.caja(PATA) == {"asset": "USDT", "currency": "USD", "invested": 800.0}
        assert self.cajas_cruzadas() == []

    def test_pesos_que_entraron_y_salieron_cuentan_como_movimientos(self):
        """Depositar y retirar $100.000 deja la caja en cero, pero la historia es en
        pesos (`flujos_a_mano`): adoptarla mostraba esos pesos como dólares en
        Movimientos."""
        padre = self.crear_broker("Cocos", "ARS")
        self.crear_broker(PATA, "ARS")
        assert self.depositar(PATA, 100_000).status_code == 200
        r = self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": PATA, "direction": "withdraw", "amount": 100_000})
        assert r.status_code == 200, r.text

        r = self.depositar("Cocos", 500, "USD")

        assert r.status_code == 409, r.text
        self.no_se_toco(padre, saldo=0.0)

    def test_la_sub_cuenta_no_se_pasa_a_pesos_a_mano(self):
        """El PUT dejaba pasar a pesos la propia "Cocos · USD": sus US$300 quedaban
        como $300, y después ningún dólar podía volver a entrar."""
        self.crear_broker("Cocos", "ARS")
        assert self.depositar("Cocos", 300, "USD").status_code == 200
        pata = self.broker(PATA)
        r = self.client.put(f"/api/brokers/{pata['id']}", headers=self.h,
                            json={"name": PATA, "currency": "ARS"})
        assert r.status_code == 400, r.text
        assert r.json()["detail"]["code"] == "sibling_currency_forbidden"
        assert self.broker(PATA)["currency"] == "USDT"
        assert self.caja(PATA)["invested"] == 300.0

    def test_no_se_crea_una_sub_cuenta_en_pesos(self):
        padre = self.crear_broker("Cocos", "ARS")
        r = self.client.post("/api/brokers", headers=self.h, json={
            "name": PATA, "currency": "ARS", "parent_broker_id": padre})
        assert r.status_code == 400, r.text
        assert not self.sql("SELECT 1 FROM brokers WHERE user_id=? AND name=?", self.uid, PATA)

    def test_la_sub_cuenta_vieja_en_pesos_dice_la_salida_que_existe(self):
        """Una sub-cuenta que quedó en pesos de antes (hoy el PUT ya no deja): no se
        puede renombrar, así que el mensaje no manda a renombrarla."""
        padre = self.crear_broker("Cocos", "ARS")
        assert self.depositar("Cocos", 300, "USD").status_code == 200
        # Lo que dejaba el PUT de antes: broker y caja en pesos, juntos.
        self.sql("UPDATE brokers SET currency='ARS' WHERE user_id=? AND name=?", self.uid, PATA)
        self.sql("UPDATE positions SET asset='ARS', currency='ARS' "
                 "WHERE user_id=? AND broker=? AND is_cash=1", self.uid, PATA)

        r = self.depositar("Cocos", 500, "USD")

        assert r.status_code == 409, r.text
        assert "volvé a ponerla en dólares" in r.json()["detail"]
        assert "Renombralo" not in r.json()["detail"]
        assert self.broker(PATA)["parent_broker_id"] == padre
        assert self.caja(PATA)["invested"] == 300.0

    # ── segunda ronda de auditoría ───────────────────────────────────────────

    def test_confirmar_con_estado_inicial_no_pierde_los_dolares_en_silencio(self):
        """Con "Estado inicial" el confirm re-valida y descarta lo inválido sin
        avisar. Si la sub-cuenta se volvió imposible entre la vista previa y el
        confirm, los US$500 desaparecían y el import decía "ok"."""
        padre = self.crear_broker("Cocos", "ARS")
        self.crear_broker(PATA, "ARS")
        prev = self.vista_previa("2026-01-05,DEPOSITO,Cocos,,,,1000,,,,ARS,\n" + DOLARES_A_COCOS)
        assert prev["errors"] == []
        assert self.depositar(PATA, 100_000).status_code == 200

        r = self.client.post("/api/imports/confirm", headers=self.h, json={
            "session_id": prev["session_id"],
            "seed_state": {"cash": [{"broker": "Cocos", "currency": "ARS", "amount": 10}]}})

        assert r.status_code == 400, r.text
        assert PATA in r.json()["detail"]
        self.no_se_toco(padre)
        assert self.caja("Cocos")["invested"] == 0.0

    def test_el_padre_que_crea_el_import_tambien_se_avisa_en_la_vista_previa(self):
        """"Cocos" no existe y lo crea este import; "Cocos · USD" sí, en pesos y con
        plata. La vista previa lo daba limpio y el confirm rebotaba con 409."""
        self.crear_broker(PATA, "ARS")
        assert self.depositar(PATA, 100_000).status_code == 200

        prev = self.vista_previa("2026-01-05,DEPOSITO,Cocos,,,,1000,,,,ARS,\n" + DOLARES_A_COCOS)

        assert self.codigos(prev) == ["SIN_CUENTA_EN_DOLARES"], prev["errors"]
        assert self.confirmar(prev["session_id"]).status_code == 200
        assert self.caja("Cocos")["invested"] == 1000.0
        assert self.broker(PATA)["currency"] == "ARS"
        assert self.caja(PATA)["invested"] == 100_000.0
        assert self.cajas_cruzadas() == []

    def test_la_sub_cuenta_huerfana_en_dolares_se_vuelve_a_adoptar(self):
        """Su padre ya no existe (datos viejos). Tiene dólares: adoptarla es lo que
        hacía antes, y lo correcto. No es "la cuenta de otro broker"."""
        self.crear_broker(PATA, "USD")
        assert self.depositar(PATA, 300).status_code == 200
        # Un padre que ya no existe: sólo se arma salteando la clave foránea.
        conn = main.get_db()
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("UPDATE brokers SET parent_broker_id=987654 WHERE user_id=? AND name=?",
                         (self.uid, PATA))
            conn.commit()
        finally:
            conn.close()
        padre = self.crear_broker("Cocos", "ARS")

        r = self.depositar("Cocos", 500, "USD")

        assert r.status_code == 200, r.text
        assert self.broker(PATA)["parent_broker_id"] == padre
        assert self.caja(PATA)["invested"] == 800.0
        assert self.cajas_cruzadas() == []

    def test_un_formato_de_broker_sigue_curando_la_cuenta_con_movimientos_a_mano(self):
        """La regresión que dejó la primera corrección: contar los depósitos a mano
        en `broker_tiene_datos` hacía que un "Cocos" en dólares con un depósito y un
        retiro de US$100 no se pasara a pesos, y un export de Cocos guardaba
        $1.000.000 como dólares sin un error."""
        self.crear_broker("Cocos", "USDT")
        assert self.depositar("Cocos", 100).status_code == 200
        r = self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": "Cocos", "direction": "withdraw", "amount": 100})
        assert r.status_code == 200, r.text
        mov = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;"
               "instrumento;moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;"
               "total\n1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;1.000.000;0;0;0;0;"
               "1.000.000\n")
        r = self.client.post("/api/imports/preview", headers=self.h,
                             files=[("files", ("mov.csv", io.BytesIO(mov.encode()), "text/csv"))],
                             data={"format": "cocos", "broker": "Cocos"})
        assert r.status_code == 200, r.text
        assert self.confirmar(r.json()["session_id"]).status_code == 200
        assert self.broker("Cocos")["currency"] == "ARS"
        caja = self.caja("Cocos")
        assert (caja["asset"], caja["invested"]) == ("ARS", 1_000_000.0)
        assert self.cajas_cruzadas() == []

    def test_la_foto_con_pesos_a_la_sub_cuenta_dice_adonde_subirla(self):
        """"Cocos · USD" creada a mano en dólares, vacía, y una foto con pesos para
        ella. No se cura a pesos (el primer dólar de "Cocos" la adopta), y el
        mensaje dice qué hacer en vez de "cambiale la moneda a pesos"."""
        self.crear_broker("Cocos", "ARS")
        self.crear_broker(PATA, "USD")
        foto = ("instrumento;cantidad;precio;moneda;total\n"
                "Energy Select Sector SPDR (XLE);20;55800,00;ARS;1116000,00\n"
                "ARS;0;0;ARS;0\n")
        r = self.client.post(
            "/api/imports/tenencia/preview", headers=self.h,
            files={"file": ("portfolio_report_20261021.csv", io.BytesIO(foto.encode()),
                            "text/csv")},
            data={"broker": PATA, "format": "cocos"})
        assert r.status_code == 400, r.text
        assert "subila al broker «Cocos»" in r.json()["detail"]
        assert self.broker(PATA)["currency"] == "USD"

    def test_la_foto_con_pesos_a_una_cuenta_en_pesos_con_ese_nombre_sigue_andando(self):
        """Antes de este cambio, una foto en pesos a un "Cocos · USD" que está en
        pesos pasaba. Sigue pasando: el que no puede recibir pesos es el que está en
        dólares."""
        self.crear_broker("Cocos", "ARS")
        self.crear_broker(PATA, "ARS")
        foto = ("instrumento;cantidad;precio;moneda;total\n"
                "Energy Select Sector SPDR (XLE);20;55800,00;ARS;1116000,00\n"
                "ARS;0;0;ARS;0\n")
        r = self.client.post(
            "/api/imports/tenencia/preview", headers=self.h,
            files={"file": ("portfolio_report_20261021.csv", io.BytesIO(foto.encode()),
                            "text/csv")},
            data={"broker": PATA, "format": "cocos"})
        assert r.status_code == 200, r.text


class TestCompraGrupalDelAsesor:
    """Un cliente con "Cocos · USD" en pesos no tumba la compra de los demás."""

    @pytest.fixture(autouse=True)
    def _asesor(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        conn = main.get_db()
        with conn:
            self.asesor = conn.execute(
                "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,'advisor')",
                (f"asesor-{tag}@rendi.test", "x")).lastrowid
            self.sano, self.trabado = (conn.execute(
                "INSERT INTO users (email, password_hash, approved, managed_by) VALUES (?,?,0,?)",
                (f"cliente{i}-{tag}@rendi.test", "x", self.asesor)).lastrowid for i in (1, 2))
            for cid in (self.sano, self.trabado):
                conn.execute("""INSERT INTO advisor_clients (advisor_uid, client_uid, link_type,
                                permission, status, label)
                                VALUES (?,?,'managed','read_write','active','x')""",
                             (self.asesor, cid))
                conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                             (cid, "Cocos", "ARS"))
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.asesor)}"}
        # El cliente trabado: "Cocos · USD" creado por él en pesos, con plata.
        h_trabado = {"Authorization": f"Bearer {main.create_token(self.trabado)}"}
        r = self.client.post("/api/brokers", headers=h_trabado,
                             json={"name": PATA, "currency": "ARS"})
        assert r.status_code == 200, r.text
        r = self.client.post("/api/cash/flow", headers=h_trabado, json={
            "broker_name": PATA, "direction": "deposit", "amount": 100_000})
        assert r.status_code == 200, r.text

    def test_saltea_solo_al_cliente_trabado(self):
        r = self.client.post("/api/advisor/group-op", headers=self.h, json={
            "asset": "GD30", "currency": "USD", "entry_date": "2026-03-06",
            "rows": [{"client_uid": c, "broker": "Cocos", "quantity": 10, "buy_price": 100}
                     for c in (self.sano, self.trabado)]})
        assert r.status_code == 200, r.text
        saltados = {s["client_uid"]: s["reason"] for s in r.json()["skipped"]}
        assert list(saltados) == [self.trabado] and PATA in saltados[self.trabado]
        conn = main.get_db()
        try:
            def gd30(cid):
                return conn.execute("SELECT broker FROM positions WHERE user_id=? AND asset='GD30'",
                                    (cid,)).fetchall()
            assert [x["broker"] for x in gd30(self.sano)] == [PATA]
            assert gd30(self.trabado) == []
        finally:
            conn.close()
