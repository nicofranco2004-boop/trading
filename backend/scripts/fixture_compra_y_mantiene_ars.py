"""Arma, POR LA API, la cuenta del caso "¿Le ganás a la inflación?" y guarda lo
que la pantalla de Análisis recibe de ella.

El caso (medido el 2026-10-13 sobre producción): broker en pesos, un depósito y
siete compras con fecha de hace un año, cargados a mano. `/api/monthly` devuelve
el capital AL COSTO todos los meses (la reconstrucción a precio real sólo corre
sobre imports), y la celda "Inflación" decía "Le perdés −16,6 %" a una cartera
que le ganaba.

Lo que sale de acá lo lee `frontend/src/utils/vsInflacionCompraYMantiene.test.js`,
que corre la cuenta de la pantalla sobre las respuestas REALES del servidor, en
vez de sobre filas escritas a mano. Todo entra por las puertas de producción
(`POST /api/brokers`, `/api/cash/flow`, `/api/positions`) y se lee por las que lee
la pantalla (`/monthly`, `/positions`, `/brokers`, `/benchmarks`, `/dolar`,
`/prices`). Sale a internet por los precios, el dólar y los índices: por eso el
resultado se guarda y no se regenera en cada corrida de la suite.

Uso (SIEMPRE con una base descartable; sin DB_PATH el script no corre):

    DB_PATH=/tmp/x.db YF_TZ_CACHE_LOCATION=$(mktemp -d) \\
        python3 backend/scripts/fixture_compra_y_mantiene_ars.py
"""
import json
import os
import sys
import uuid

if not os.environ.get("DB_PATH"):
    sys.exit("Falta DB_PATH: este script crea una cuenta y no puede tocar backend/trading.db")

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)
os.environ.setdefault("SECRET_KEY", "fixture-secret")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

FECHA = "2025-10-13"
DEPOSITO = 10_000_000
# (ticker, cantidad, precio en pesos): el cierre REAL en BYMA del 13/10/2025
# (Yahoo, `<ticker>.BA`), unos $1,4 millones por papel.
COMPRAS = [("GGAL", 300, 4750), ("YPFD", 360, 3976), ("PAMP", 370, 3890),
           ("KO", 74, 19160), ("MSFT", 58, 24570), ("MELI", 54, 26040),
           ("GOOGL", 236, 6030)]
SALIDA = os.path.join(os.path.dirname(BACKEND), "frontend", "src", "utils",
                      "fixtures", "compraYMantieneArs.json")


def main_():
    http = TestClient(main.app)
    conn = main.get_db()
    uid = conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                       (f"fixture-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
    conn.commit()
    conn.close()
    h = {"Authorization": f"Bearer {main.create_token(uid)}"}

    def ok(r):
        assert r.status_code == 200, r.text
        return r.json()

    ok(http.post("/api/brokers", json={"name": "Balanz", "currency": "ARS"}, headers=h))
    ok(http.post("/api/cash/flow", json={"broker_name": "Balanz", "direction": "deposit",
                                         "amount": DEPOSITO, "date": FECHA}, headers=h))
    for asset, qty, precio in COMPRAS:
        ok(http.post("/api/positions", json={"broker": "Balanz", "asset": asset, "quantity": qty,
                                             "buy_price": precio, "invested": qty * precio,
                                             "entry_date": FECHA}, headers=h))

    bench = ok(http.get("/api/benchmarks", headers=h))
    simbolos = ",".join(f"{a}.BA" for a, _, _ in COMPRAS)
    datos = {
        "_como_se_armo": ("backend/scripts/fixture_compra_y_mantiene_ars.py — cuenta cargada "
                          f"por la API: depósito de ${DEPOSITO:,} y {len(COMPRAS)} compras el "
                          f"{FECHA}; respuestas tal cual las recibe la pantalla."),
        "monthly": ok(http.get("/api/monthly", headers=h)),
        "positions": ok(http.get("/api/positions", headers=h)),
        "brokers": ok(http.get("/api/brokers", headers=h)),
        "snapshots": ok(http.get("/api/snapshots?days=3650", headers=h)),
        # Sólo las tres series que usan las celdas: el resto pesa y no se lee.
        "benchmarks": {k: bench.get(k) for k in ("inflation_ar", "dolar_blue", "uva")},
        "dolar": ok(http.get("/api/dolar", headers=h)),
        "prices": ok(http.get(f"/api/prices?symbols={simbolos}", headers=h)),
    }
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    print("guardado:", SALIDA)


if __name__ == "__main__":
    main_()
