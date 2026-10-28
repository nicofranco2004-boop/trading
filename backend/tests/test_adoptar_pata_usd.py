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

    def importar(self, filas):
        """Vista previa + confirmación. Devuelve la respuesta de la confirmación."""
        r = self.client.post(
            "/api/imports/preview", headers=self.h,
            files=[("files", ("plantilla.csv", io.BytesIO((HDR + filas).encode("utf-8")),
                              "text/csv"))],
            data={"format": "rendi_generic", "broker": "Cocos"})
        assert r.status_code == 200, r.text
        assert r.json()["errors"] == []
        return self.client.post("/api/imports/confirm", headers=self.h,
                                json={"session_id": r.json()["session_id"]})

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

    def test_con_pesos_adentro_no_se_adopta_y_no_se_toca_nada(self):
        """El caso del bug: "Cocos · USD" creado a mano en pesos, con $100.000.
        Adoptarlo convertía esos pesos en dólares. Se rechaza el import entero
        —es atómico— con un mensaje que dice qué hacer, y la cuenta queda como
        estaba."""
        padre = self.crear_broker("Cocos", "ARS")
        self.crear_broker(PATA, "ARS")
        assert self.depositar(PATA, 100_000).status_code == 200

        r = self.importar(DOLARES_A_COCOS)

        assert r.status_code == 409, r.text
        assert PATA in r.json()["detail"] and "renombr" in r.json()["detail"].lower()
        assert self.broker(PATA)["currency"] == "ARS"
        assert self.broker(PATA)["parent_broker_id"] is None
        caja = self.caja(PATA)
        assert (caja["asset"], caja["invested"]) == ("ARS", 100_000.0)
        assert not self.sql("SELECT 1 FROM brokers WHERE user_id=? AND parent_broker_id=?",
                            self.uid, padre)
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
