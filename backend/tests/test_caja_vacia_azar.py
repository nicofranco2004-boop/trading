"""Con el dólar quieto, ninguna venta de dólares gana ni pierde — con cuentas al azar.

La ganancia cambiaria de vender dólares sale de comparar el precio de la venta con
el precio promedio al que se compraron los que hay en la caja (`efectivo.py`). Las
pruebas armadas de `test_operaciones_con_receta.py` (`LaCajaVaciaNoTienePrecio`)
fijan cada caso por separado. Esto los mezcla, en dos etapas y todo por HTTP:

  1. Con el dólar a OTRO precio (300 a 500) se compran dólares, se vende una parte
     y al final se venden TODOS — a veces dejando el resto de centavos que deja
     vender "todo" (lo que la pantalla muestra como 0,00).
  2. Con el dólar QUIETO en 1.300, una secuencia al azar de depositar dólares,
     comprar, vender, retirar, borrar una compra o una venta de esta etapa y
     deshacer el borrado.

En la etapa 2 todo se compra y se vende al mismo precio, así que cualquier ganancia
o pérdida cambiaria es inventada: sólo puede salir de un precio de la etapa 1 que
revivió. Después de CADA paso:
  · una caja vacía o en rojo no tiene precio (el mismo chequeo que corre en
    producción: `invariantes.check_caja_vacia_con_precio`);
  · el precio de la caja, si tiene, es 1.300;
  · ninguna venta de la etapa 2 anotó resultado, y el resultado realizado de la
    cuenta es el que dejó la etapa 1.

Hasta 2026-10-11 fallaba en el primer depósito de la etapa 2: la caja vaciada
conservaba el precio viejo y los dólares depositados lo heredaban.

Por defecto corre pocas semillas (entra en la suite). Para una pasada larga:
    cd backend && SEMILLAS_CAJA=1-300 PASOS_CAJA=30 \\
        python3 -m pytest tests/test_caja_vacia_azar.py -q -p no:cacheprovider
"""
import os
import random

import main  # noqa: F401  (antes que la base: fija la base de datos de este archivo)
from importing import invariantes

try:
    from tests import test_operaciones_con_receta as base
except ImportError:                                  # corrido suelto desde tests/
    import test_operaciones_con_receta as base


def _semillas():
    crudo = os.environ.get("SEMILLAS_CAJA", "1-8")
    out = []
    for parte in crudo.split(","):
        if "-" in parte:
            a, b = parte.split("-")
            out.extend(range(int(a), int(b) + 1))
        elif parte.strip():
            out.append(int(parte))
    return out


SEMILLAS = _semillas()
PASOS = int(os.environ.get("PASOS_CAJA", "14"))

DOLAR_DE_ANTES = (300, 400, 500)
DOLAR_QUIETO = 1300
# El resto que deja vender "todo": nada, o centavos que se ven como 0,00.
RESTOS = (0.0, 0.0, 0.001, 0.004)
ACCIONES = ("depositar",) * 3 + ("comprar",) * 3 + ("vender",) * 4 + ("retirar",) * 1 \
    + ("borrar",) * 2 + ("deshacer",) * 1


class ConElDolarQuietoNadaGanaNiPierde(base.ConRecetaBase):

    def setUp(self):
        super().setUp()
        self.USD = f"{self.PESOS} · USD"
        self._depositar(self.PESOS, 500_000_000)

    # ── lecturas ──
    def _caja_usd(self):
        self.conn.commit()
        f = self.conn.execute(
            "SELECT invested, tc_compra FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
            (self.uid, self.USD)).fetchone()
        return (float(f["invested"] or 0), f["tc_compra"]) if f else (0.0, None)

    def _realizado(self):
        return self.estado()["resultado_del_mes"]

    # ── acciones ──
    def _comprar(self, dolares, tc):
        self._convertir(self.PESOS, "ars_to_usd", dolares * tc, dolares, tc)

    def _vender(self, dolares, tc):
        return self._convertir(self.USD, "usd_to_ars", dolares * tc, dolares, tc)

    def _monto(self, rng):
        return round(rng.uniform(1, 400), rng.choice((0, 2, 6)))

    def _etapa_1(self, rng):
        for _ in range(rng.randint(1, 3)):
            self._comprar(self._monto(rng), rng.choice(DOLAR_DE_ANTES))
            saldo = self._caja_usd()[0]
            if rng.random() < 0.4 and saldo > 1:
                self._vender(round(saldo * rng.uniform(0.1, 0.9), 2), rng.choice(DOLAR_DE_ANTES))
        saldo = self._caja_usd()[0]
        self._vender(saldo - rng.choice(RESTOS), rng.choice(DOLAR_DE_ANTES))

    def _paso(self, rng, accion, desde_op, tokens):
        """Devuelve lo que hizo (para el mensaje de un fallo)."""
        saldo = self._caja_usd()[0]
        if accion == "depositar":
            monto = self._monto(rng)
            self._depositar(self.USD, monto)
            return f"depositar {monto}"
        if accion == "comprar":
            monto = self._monto(rng)
            self._comprar(monto, DOLAR_QUIETO)
            return f"comprar {monto}"
        if accion == "vender" and saldo >= 0.01:
            monto = saldo - rng.choice(RESTOS) if rng.random() < 0.4 \
                else max(0.01, round(saldo * rng.uniform(0.05, 0.95), 2))
            venta = self._vender(monto, DOLAR_QUIETO)
            self.assertEqual(venta["pnl_usd"], 0, f"vender {monto}: ganancia cambiaria inventada")
            return f"vender {monto}"
        if accion == "retirar" and saldo >= 0.01:
            monto = max(0.01, round(saldo * rng.uniform(0.05, 1.0), 2))
            if monto <= saldo:
                self._ok(self.http.post("/api/cash/flow", json={
                    "broker_name": self.USD, "direction": "withdraw", "amount": monto}))
                return f"retirar {monto}"
        if accion == "borrar":
            self.conn.commit()
            ops = [r["id"] for r in self.conn.execute(
                "SELECT id FROM operations WHERE user_id=? AND id>? AND op_type LIKE 'CONVERSION%'",
                (self.uid, desde_op))]
            if ops:
                op = rng.choice(ops)
                r = self.http.delete(f"/api/operations/{op}")
                self.assertIn(r.status_code, (200, 400, 409), r.text)
                if r.status_code == 200:
                    tokens.append(r.json()["undo_token"])
                return f"borrar la operación {op} ({r.status_code})"
        if accion == "deshacer" and tokens:
            r = self.http.post(f"/api/operations/undo/{tokens.pop(rng.randrange(len(tokens)))}")
            self.assertIn(r.status_code, (200, 400, 404, 409, 410), r.text)
            return f"deshacer ({r.status_code})"
        return "nada"

    def _revisar(self, donde, realizado_etapa_1=None):
        saldo, tc = self._caja_usd()
        self.assertEqual(invariantes.check_caja_vacia_con_precio(self.conn, self.uid), [],
                         f"{donde}: caja vacía con precio (saldo {saldo}, precio {tc})")
        if realizado_etapa_1 is None:
            return
        if tc is not None:
            self.assertAlmostEqual(tc, DOLAR_QUIETO, delta=1e-6,
                                   msg=f"{donde}: revivió un precio de antes (saldo {saldo})")
        self.assertAlmostEqual(self._realizado(), realizado_etapa_1, places=2,
                               msg=f"{donde}: cambió el resultado realizado")

    def _correr(self, semilla):
        rng = random.Random(semilla)
        self._etapa_1(rng)
        saldo, tc = self._caja_usd()
        self.assertLess(saldo, 0.005)
        self.assertIsNone(tc, "la caja vaciada conservó el precio")
        self._revisar("fin de la etapa 1")
        realizado = self._realizado()
        desde_op = self._ultima_op()["id"]
        tokens, hechos = [], []
        for paso in range(PASOS):
            hechos.append(self._paso(rng, rng.choice(ACCIONES), desde_op, tokens))
            self._revisar(f"semilla {semilla}, paso {paso} ({' → '.join(hechos)})", realizado)


for _s in SEMILLAS:
    setattr(ConElDolarQuietoNadaGanaNiPierde, f"test_semilla_{_s:03d}",
            lambda self, _s=_s: self._correr(_s))
