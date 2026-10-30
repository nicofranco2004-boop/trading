"""Los brokers como los ve la pantalla, con ids que no dependen del motor.

POR QUÉ. Los fixtures de la bandeja de cupones (`cupones_contrato.json`,
`cupon_importado_bandeja.json`) guardan `/api/brokers` porque la pantalla enlaza
la pata «Cocos · USD» con su madre por `parent_broker_id`. Lo que el contrato
tiene que fijar es esa RELACIÓN, no el número: el id lo pone el contador de la
base, y la pantalla funciona con cualquiera.

Antes se fijaba el número reiniciando el contador (`DELETE FROM sqlite_sequence`).
Eso existe sólo en SQLite: en Postgres la secuencia sigue de largo entre
escenarios y el fixture veía `id: 4` donde esperaba `id: 1` (medido el
30/10/2026, el único campo distinto entre los dos motores).

Acá los ids se renumeran 1, 2, … en el orden en que se crearon, y
`parent_broker_id` se traduce con el mismo mapa: la relación queda intacta y el
número deja de depender del motor.
"""


def brokers_con_ids_relativos(brokers):
    orden = sorted(brokers, key=lambda b: b["id"])
    nuevo = {b["id"]: i for i, b in enumerate(orden, start=1)}
    return [
        {"id": nuevo[b["id"]], "name": b["name"], "currency": b["currency"],
         # Una madre que no está en la lista tiene que romper, no pasar callada.
         "parent_broker_id": (nuevo[b["parent_broker_id"]]
                              if b.get("parent_broker_id") is not None else None)}
        for b in orden
    ]
