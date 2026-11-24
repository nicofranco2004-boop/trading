"""«Mover a otro broker»: el contrato entre la PANTALLA y el servidor.

QUÉ FIJA. La pantalla (frontend/, commit af736748 y la integración) se escribió
contra la especificación antes de que existiera el servidor. Estas pruebas arman un
pase de verdad, lo listan, lo deshacen e importan archivos después, todo por HTTP
con el arnés de `test_mover_entre_brokers.py` (token real, imports por las puertas,
recálculo y reconstrucción de verdad), y afirman que cada respuesta trae las claves
que la pantalla LEE. Las listas de abajo son literales, sacadas del código del
frontend, con un comentario de dónde se lee cada una: si el servidor cambia un
nombre, esto se pone rojo antes de que la pantalla muestre un hueco.

Dos niveles:
  · `LEE_*`: lo que la pantalla lee. Tiene que estar (subconjunto).
  · `CONTRATO_*`: la forma ENTERA de las respuestas nuevas de esta función (la
    vista previa, el confirmar, el deshacer, GET /traspasos, las filas del pase en
    Movimientos, el `traspaso` de Importaciones, `ya_traspasados`,
    `cambian_un_pase`). Igualdad exacta: una clave nueva o perdida se revisa acá.
    Las respuestas que ya existían (una fila de /api/monthly, un lote de la lista de
    imports, una posición) sólo se miran por lo que la pantalla lee.

Y los TEXTOS: los que llevan montos tienen la moneda adelante, así el «ojito»
(`taparMontos`, frontend/src/utils/ocultarSaldos.js) los tapa. La expresión se lee
del archivo del frontend, no se copia: si la pantalla la cambia, esto la sigue.

Corre con: cd backend && python3 -m pytest tests/test_mover_entre_brokers_contrato.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import main  # noqa: E402
import test_mover_entre_brokers as base  # noqa: E402  (el módulo: así no se recolectan sus pruebas acá)
from importing import traspaso_a_mano  # noqa: E402

FRONT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "frontend", "src")

# ── La vista previa: POST /api/positions/traspaso/vista-previa (B.2) ──────────────
LEE_VISTA = {
    "origen",               # VistaPreviaDelPase.jsx `plan?.origen?.cuenta`; useMoverDeBroker.jsx `hecho`
    "destino",              # VistaPreviaDelPase.jsx `plan?.destino?.cuenta`; useMoverDeBroker.jsx `hecho`
    "asset",                # VistaPreviaDelPase.jsx `lineaDeLote(l, plan.asset)`; useMoverDeBroker.jsx `hecho`
    "fecha",                # moverDeBroker.js `lineaDelValor` (`plan.fecha`)
    "cantidad",             # MoverDeBrokerModal.jsx `cantidadBoton`; useMoverDeBroker.jsx `hecho`
    "cantidad_disponible",  # MoverDeBrokerModal.jsx `setDisponible` («Tenés N que ya estaban…»)
    "lotes",                # VistaPreviaDelPase.jsx `plan.lotes`
    "valuacion",            # moverDeBroker.js `lineaDelValor`; MoverDeBrokerModal.jsx la devuelve al confirmar
    "valor_nativo",         # moverDeBroker.js `lineaDelValor`
    "valor_usd",            # moverDeBroker.js `lineaDelValor`, `lineaDelPuente`
    "costo_usd",            # moverDeBroker.js `lineaDelPuente`
    "puente_usd",           # moverDeBroker.js `lineaDelPuente` (ganancia o pérdida por el signo)
    "gasto",                # moverDeBroker.js `lineaDelGasto`
    "avisos",               # VistaPreviaDelPase.jsx `plan.avisos`
    "firma",                # MoverDeBrokerModal.jsx `confirmarPase` (la devuelve tal cual)
}
LEE_VISTA_ORIGEN = {"cuenta"}
LEE_VISTA_DESTINO = {"cuenta"}
LEE_VISTA_LOTE = {
    "lote_id",              # VistaPreviaDelPase.jsx `key={l.lote_id}`
    "a_mano",               # moverDeBroker.js `lineaDeLote` («cargado a mano»)
    "fecha_compra",         # moverDeBroker.js `lineaDeLote` («comprados el …»)
    "cantidad",             # moverDeBroker.js `lineaDeLote`
    "de_un_lote_de",        # moverDeBroker.js `lineaDeLote` («parte de un lote de …»)
    "costo",                # moverDeBroker.js `lineaDeLote` («costo …»)
    "moneda",               # moverDeBroker.js `lineaDeLote` (la moneda del costo)
}
LEE_VISTA_VALUACION = {
    "fuente",               # moverDeBroker.js `textoDeFuente`
    "fecha_precio",         # moverDeBroker.js `textoDeFuente` («cierre del viernes 20/11»)
    "moneda_precio",        # moverDeBroker.js `lineaDelValor`; MoverDeBrokerModal.jsx `monedaPrecio`
}
LEE_VISTA_GASTO = {"monto", "moneda", "broker"}   # moverDeBroker.js `lineaDelGasto`
# El 409 «sin precio» (B.6 #26): `detail` es un objeto.
LEE_SIN_PRECIO = {
    "codigo",               # moverDeBroker.js `faltaPrecio` (`d.codigo === 'sin_precio'`)
    "mensaje",              # MoverDeBrokerModal.jsx `faltaElPrecio.mensaje`
    "moneda_precio",        # MoverDeBrokerModal.jsx `monedaPrecio` («en pesos|dólares»)
}
CONTRATO_VISTA = {"ok", "origen", "destino", "asset", "moneda", "fecha", "cantidad",
                  "cantidad_disponible", "lotes", "valuacion", "valor_nativo", "valor_ars",
                  "valor_usd", "costo_usd", "puente_usd", "gasto", "avisos", "firma"}
CONTRATO_VISTA_ORIGEN = {"cuenta", "etiqueta"}
CONTRATO_VISTA_DESTINO = {"cuenta", "brokers_a_crear"}
CONTRATO_VISTA_LOTE = {"lote_id", "a_mano", "fecha_compra", "cantidad", "de_un_lote_de", "costo",
                       "comisiones", "moneda", "broker_origen", "broker_destino"}
CONTRATO_VISTA_VALUACION = {"precio_unitario", "moneda_precio", "fuente", "fecha_precio", "dolar"}
CONTRATO_VISTA_GASTO = {"monto", "moneda", "broker", "caja_queda_negativa"}
CONTRATO_SIN_PRECIO = {"codigo", "mensaje", "moneda_precio"}

# ── Confirmar y deshacer ─────────────────────────────────────────────────────────
LEE_CONFIRMAR = {
    "mensaje",              # useMoverDeBroker.jsx `hecho` (el toast «Listo: pasaste …»)
    "traspaso_id",          # useMoverDeBroker.jsx `hecho` (el «Deshacer» del toast)
}
CONTRATO_CONFIRMAR = {"ok", "traspaso_id", "mensaje"}
LEE_DESHACER = {"mensaje"}  # useMoverDeBroker.jsx `deshacer`; Operations.jsx `deshacerElPase`
CONTRATO_DESHACER = {"ok", "mensaje"}

# ── GET /api/positions/traspasos (B.5) ────────────────────────────────────────────
LEE_TRASPASOS = {
    "habilitado",           # useMoverDeBroker.jsx (`r?.habilitado === true`: el ítem del menú)
    "traspasos",            # Operations.jsx `deshacerElPase`
}
LEE_TRASPASO = {
    "id",                   # Operations.jsx `find(t => t.id === m.traspaso_id)`
    "puede_deshacer",       # Operations.jsx `deshacerElPase`
    "motivo",               # Operations.jsx `deshacerElPase` (el porqué, tapado con el ojito)
    "cantidad",             # moverDeBroker.js `preguntaDeDeshacer`
    "asset",                # moverDeBroker.js `preguntaDeDeshacer`
    "broker_origen",        # moverDeBroker.js `preguntaDeDeshacer`
    "broker_destino",       # moverDeBroker.js `preguntaDeDeshacer`
    "estado",               # moverDeBroker.js `preguntaDeDeshacer` (el texto del incompleto)
}
CONTRATO_TRASPASO = {"id", "fecha", "asset", "cantidad", "moneda", "broker_origen",
                     "broker_destino", "valor_usd", "costo_usd", "estado", "puede_deshacer",
                     "motivo", "aviso"}
ESTADOS = {"vivo", "incompleto", "desfasado"}   # los que compara moverDeBroker.js

# ── GET /api/movements: las filas del pase (D.9) ──────────────────────────────────
LEE_PATA = {
    "id",                   # MovementsTable.jsx / MovementsFeed.jsx `key={m.id}`
    "type",                 # moverDeBroker.js `esFilaDePase`; shared.js `TYPE_META`, `esDeUnPase`
    "date",                 # Operations.jsx (filtro de año), MovementsTable.jsx
    "broker",               # Operations.jsx (filtro de broker); moverDeBroker.js `avisoDeFilaDePase`
    "asset",                # moverDeBroker.js `lineaDeFilaDePase`
    "quantity",             # moverDeBroker.js `lineaDeFilaDePase`
    "amount_usd",           # MovementsTable.jsx / MovementsFeed.jsx (el monto)
    "fx_to_usd",            # MovementsTable.jsx (la vista en pesos de la pata)
    "currency",             # MovementsTable.jsx / MovementsFeed.jsx
    "notes",                # MovementsTable.jsx `title={m.notes}`
    "traspaso_id",          # MovementsTable.jsx / MovementsFeed.jsx (botón «Deshacer pase»); shared.js
    "borrable",             # shared.js `puedeBorrarMovimiento`
    "contraparte",          # moverDeBroker.js `lineaDeFilaDePase`, `avisoDeFilaDePase`
    "estado",               # moverDeBroker.js `avisoDeFilaDePase`
    "aviso",                # moverDeBroker.js `avisoDeFilaDePase` (el texto del desfasado)
}
CONTRATO_PATA = {"id", "kind", "date", "type", "broker", "asset", "quantity", "unit_price",
                 "amount_usd", "currency", "fx_to_usd", "fees_usd", "notes", "source", "ref_id",
                 "transfer_out", "traspaso_id", "borrable", "contraparte", "estado", "aviso",
                 "cobro"}
LEE_GASTO = {"type", "traspaso_id", "borrable", "amount_usd"}   # shared.js `esDeUnPase`, `puedeBorrarMovimiento`
LEE_COMPRA_PASADA = {
    "id", "type", "date", "broker", "asset", "quantity", "amount_usd", "fees_usd",
    "borrable",             # shared.js `puedeBorrarMovimiento` (sin tacho)
    "traspaso_id",          # shared.js `esDeUnPase` (NO cuenta en «Pases»: es una COMPRA)
    "notes",                # MovementsTable.jsx («La pasaste a {B} el …»)
}
CONTRATO_COMPRA_PASADA = {"id", "kind", "date", "type", "broker", "asset", "quantity",
                          "unit_price", "amount_usd", "currency", "fees_usd", "notes", "source",
                          "ref_id", "traspaso_id", "borrable", "cobro"}

# ── GET /api/monthly (D.8): lo que leen resultadoDelMes.js y capitalAportado.js ──
LEE_MENSUAL_A = {
    "pnl_realized",         # resultadoDelMes.js `resultadoSinPuente`
    "puente_salida_usd",    # resultadoDelMes.js `puenteDelMes`, `lineasDelPuente`
    "gasto_pase_usd",       # resultadoDelMes.js `lineasDelPuente` («Incluye … del costo del pase.»)
    "traspaso_pesos_ret",   # capitalAportado.js (la tabla de UN broker)
    "traspaso_pesos_ret_usd",  # capitalAportado.js
}
LEE_MENSUAL_B = {
    "pnl_realized",
    "puente_entrada_usd",   # resultadoDelMes.js `puenteDelMes`, `lineasDelPuente`
    "traspaso_pesos_dep",   # capitalAportado.js
    "traspaso_pesos_dep_usd",  # capitalAportado.js
}
# La fila global con las DOS patas vivas: el puente se anula y no viene (nota 5 de
# notas_tanda2.md: si viniera crudo, /mensual dibujaba dos renglones que se anulan).
NO_EN_GLOBAL_VIVO = {"puente_salida_usd", "puente_entrada_usd", "traspaso_neto_usd",
                     "traspaso_neto_pesos", "traspaso_pesos_dep", "traspaso_pesos_ret",
                     "traspaso_usd_con_dia"}
# Con una pata huérfana (se borró un broker): el neto, con signo (capitalAportado.js
# `g.traspaso_neto_usd` / `Math.abs(g.traspaso_neto_pesos)`).
LEE_GLOBAL_HUERFANA = {"traspaso_neto_usd", "traspaso_neto_pesos", "puente_salida_usd"}
LEE_USD_CON_DIA = {"dep", "ret"}   # capitalAportado.js `b.traspaso_usd_con_dia?.dep|ret`

# ── Importaciones: GET /api/imports y POST /api/imports/preview (E8) ──────────────
CONTRATO_LOTE_PASE = {"id", "asset", "cantidad", "lado", "contraparte", "estado"}
LEE_LOTE_PASE = {"asset", "cantidad", "lado", "contraparte"}   # moverDeBroker.js `tituloDeLotePase`
LADOS_DEL_LOTE = {"salida", "entrada"}                         # `tituloDeLotePase` («a» / «desde»)
LEE_PREVIEW = {
    "ya_traspasados",       # ImportWizard.jsx (el bloque «Ya las cargaste con «Mover a otro broker»»)
    "cambian_un_pase",      # ImportWizard.jsx (bloque rojo y confirmar apagado)
    "avisos_de_pases",      # ImportWizard.jsx («Revisá esto antes de confirmar»); tandaImport.js
    "duplicate_row_indices",  # moverDeBroker.js `repetidasPorHuella`
    "filas_de_pases",       # moverDeBroker.js `repetidasPorHuella`
}
CONTRATO_YA_TRASPASADO = {"fecha", "activo", "cantidad", "broker", "lado"}   # todas las lee ImportWizard.jsx
CONTRATO_CAMBIA_UN_PASE = {"traspaso_id", "lado", "fecha", "fecha_fila", "asset", "broker",
                           "contraparte", "op", "mensaje"}   # `mensaje`: moverDeBroker.js `textoDeImportCambiaUnPase`
LEE_CONFIRM_IMPORT = {"omitidas_por_pases", "auto_skipped_duplicates"}   # tandaImport.js `estadoFinal`

# ── Otros lectores ────────────────────────────────────────────────────────────────
LEE_BORRAR_BROKER = {"counts", "sibling"}   # BrokerManager.jsx / avisoBorrarBroker.js
LEE_COUNTS = {"positions", "operations", "monthly_entries", "import_batches", "futures",
              "archived", "traspasos"}       # avisoBorrarBroker.js `partesDelBorrado`
# GET /api/positions: `en_broker_desde` (utils/dividendosPendientes.js). GET /api/brokers:
# `is_exchange` (moverDeBroker.js `familiaDeCuenta`).


def _monto_en_texto():
    """La expresión con que la pantalla tapa los montos de un texto del servidor
    (`MONTO_EN_TEXTO`, frontend/src/utils/ocultarSaldos.js), leída del archivo."""
    with open(os.path.join(FRONT, "utils", "ocultarSaldos.js"), encoding="utf-8") as f:
        m = re.search(r"const MONTO_EN_TEXTO = /(.+)/g\s*$", f.read(), re.M)
    assert m, "no encontré MONTO_EN_TEXTO en ocultarSaldos.js"
    return re.compile(m.group(1))


OCULTO = "••••••"


class _Contrato(base._Archivos):
    maxDiff = None

    def _trae(self, obj, lee, contrato=None, donde=""):
        """`obj` trae todo lo que la pantalla lee (`lee`) y, si se pasa `contrato`,
        exactamente esas claves."""
        self.assertIsInstance(obj, dict, f"{donde}: {obj!r}")
        self.assertEqual(set(lee) - set(obj), set(), f"{donde}: le falta lo que lee la pantalla")
        if contrato is not None:
            self.assertEqual(set(obj), set(contrato), f"{donde}: cambió la forma de la respuesta")

    def _tapado(self, texto, *montos):
        """Con el ojito prendido, `taparMontos(texto)` no deja ninguno de `montos` a la
        vista: todos llevan la moneda adelante."""
        tapado = _monto_en_texto().sub(OCULTO, texto)
        for monto in montos:
            self.assertIn(monto, texto, f"control: «{monto}» no está en «{texto}»")
            self.assertNotIn(monto, tapado, f"el ojito no tapa «{monto}» en «{texto}»")
        self.assertIn(OCULTO, tapado)
        return tapado


class PaseListadoYDeshecho(_Contrato):

    def test_pase_listado_y_deshecho_con_las_claves_que_lee_la_pantalla(self):
        """El flujo entero de la pantalla, por HTTP: la vista previa (sin precio, y con
        precio a mano y un gasto), el confirmar con la firma y la valuación que devolvió,
        el doble click, GET /traspasos, Movimientos, /mensual, Importaciones, Cartera,
        Brokers, el aviso de borrar el broker de destino y el deshacer. Cada respuesta,
        con las claves que lee la pantalla; los textos, con la moneda adelante."""
        self._historia()
        self._lote_a_mano("Cocos", "NVDA", 2, 28000, "2025-01-02", commissions=280)

        # La vista previa sin precio: 409 con `detail` objeto (B.6 #26).
        r = self._vista(self._pedido("NVDA", "Cocos", "Balanz", base.FECHA_PASE))
        self.assertEqual(r.status_code, 409, r.text)
        self._trae(r.json()["detail"], LEE_SIN_PRECIO, CONTRATO_SIN_PRECIO, "409 sin precio")
        self.assertEqual(r.json()["detail"]["codigo"], "sin_precio")

        # Un gasto que deja la caja en negativo: el aviso lleva el monto con «−$» adelante.
        r = self._vista(self._pedido("NVDA", "Cocos", "Balanz", base.FECHA_PASE,
                                     precio_manual=base.PRECIO_PASE,
                                     gasto={"monto": 5000000, "moneda": "ARS"}))
        self.assertEqual(r.status_code, 200, r.text)
        caja = [a for a in r.json()["avisos"] if a.startswith("Con el gasto, la caja de Cocos queda en ")]
        self.assertEqual(len(caja), 1, r.json()["avisos"])
        self.assertTrue(r.json()["gasto"]["caja_queda_negativa"])
        monto = caja[0][len("Con el gasto, la caja de Cocos queda en "):-1]
        self.assertRegex(monto, r"^−\$\d{1,3}(\.\d{3})*$")
        self._tapado(caja[0], monto)

        # La vista previa de verdad: 5 de 12 (el lote a mano entero y 3 del importado).
        body = self._pedido("NVDA", "Cocos", "Balanz", base.FECHA_PASE,
                            precio_manual=base.PRECIO_PASE, cantidad=5,
                            gasto={"monto": 5000, "moneda": "ARS"})
        r = self._vista(body)
        self.assertEqual(r.status_code, 200, r.text)
        vista = r.json()
        self._trae(vista, LEE_VISTA, CONTRATO_VISTA, "vista previa")
        self._trae(vista["origen"], LEE_VISTA_ORIGEN, CONTRATO_VISTA_ORIGEN, "vista.origen")
        self._trae(vista["destino"], LEE_VISTA_DESTINO, CONTRATO_VISTA_DESTINO, "vista.destino")
        self.assertEqual(len(vista["lotes"]), 2)
        for l in vista["lotes"]:
            self._trae(l, LEE_VISTA_LOTE, CONTRATO_VISTA_LOTE, "vista.lotes[]")
        self.assertEqual([(l["a_mano"], l["cantidad"], l["de_un_lote_de"]) for l in vista["lotes"]],
                         [(True, 2.0, 2.0), (False, 3.0, 10.0)])
        self._trae(vista["valuacion"], LEE_VISTA_VALUACION, CONTRATO_VISTA_VALUACION, "vista.valuacion")
        # La pantalla devuelve la valuación TAL CUAL: tiene que entrar en `ValuacionIn`.
        main.ValuacionIn(**vista["valuacion"])
        self._trae(vista["gasto"], LEE_VISTA_GASTO, CONTRATO_VISTA_GASTO, "vista.gasto")
        self.assertEqual((vista["origen"]["cuenta"], vista["destino"]["cuenta"], vista["asset"],
                          vista["cantidad"], vista["cantidad_disponible"]),
                         ("Cocos", "Balanz", "NVDA", 5.0, 12.0))
        self.assertAlmostEqual(vista["puente_usd"], vista["valor_usd"] - vista["costo_usd"], delta=0.011)
        self.assertIsInstance(vista["firma"], str)

        # Confirmar como MoverDeBrokerModal: el mismo cuerpo + firma + valuación.
        c = self._confirmar(body, vista=vista)
        self.assertEqual(c.status_code, 200, c.text)
        self._esperar_reconstruccion()
        self._trae(c.json(), LEE_CONFIRMAR, CONTRATO_CONFIRMAR, "confirmar")
        self.assertEqual(c.json()["mensaje"], "Listo: pasaste 5 NVDA de Cocos a Balanz.")
        tid = c.json()["traspaso_id"]
        # El doble click: 409 con `detail` TEXTO (la pantalla lo muestra con errorMessage
        # y vuelve a pedir la vista previa en todo 409).
        c2 = self._confirmar(body, vista=vista)
        self.assertEqual((c2.status_code, c2.json()["detail"]), (409, traspaso_a_mano.MSG_CARTERA_CAMBIO))
        # Otro dólar: 409 con los dos dólares con «$» adelante.
        c3 = self._confirmar(body, valuacion={**vista["valuacion"],
                                              "dolar": vista["valuacion"]["dolar"] * 1.05})
        self.assertEqual(c3.status_code, 409, c3.text)
        self.assertIsInstance(c3.json()["detail"], str)
        dolares = re.findall(r"\$[\d.]+,\d{2}", c3.json()["detail"])
        self.assertEqual(len(dolares), 2, c3.json()["detail"])
        self._tapado(c3.json()["detail"], *dolares)

        # GET /traspasos.
        t = self._traspasos()
        self._trae(t, LEE_TRASPASOS, {"habilitado", "traspasos"}, "GET /traspasos")
        self.assertIs(t["habilitado"], True)
        [uno] = t["traspasos"]
        self._trae(uno, LEE_TRASPASO, CONTRATO_TRASPASO, "GET /traspasos[]")
        self.assertEqual((uno["id"], uno["estado"], uno["puede_deshacer"], uno["motivo"], uno["aviso"]),
                         (tid, "vivo", True, None, None))

        # Movimientos: las dos patas, el gasto y la compra pasada.
        movs = self._get("/api/movements").json()
        patas = [m for m in movs if m["type"] in ("TRASPASO_SALIDA", "TRASPASO_ENTRADA")]
        self.assertEqual(len(patas), 2)
        for m in patas:
            self._trae(m, LEE_PATA, CONTRATO_PATA, f"movimiento {m['type']}")
            self.assertEqual((m["traspaso_id"], m["borrable"], m["estado"], m["aviso"]),
                             (tid, False, "vivo", None))
        self.assertEqual(sorted((m["type"], m["broker"], m["contraparte"]) for m in patas),
                         [("TRASPASO_ENTRADA", "Balanz", "Cocos"), ("TRASPASO_SALIDA", "Cocos", "Balanz")])
        [gasto] = [m for m in movs if m["type"] == "FEE" and m.get("traspaso_id")]
        self._trae(gasto, LEE_GASTO, None, "movimiento gasto del pase")
        self.assertEqual((gasto["traspaso_id"], gasto["borrable"]), (tid, False))
        [pasada] = [m for m in movs if str(m["id"]).startswith("trp-")]
        self._trae(pasada, LEE_COMPRA_PASADA, CONTRATO_COMPRA_PASADA, "movimiento trp-")
        self.assertEqual((pasada["type"], pasada["traspaso_id"], pasada["borrable"], pasada["notes"]),
                         ("BUY", tid, False, "La pasaste a Balanz el 16/06/2025"))

        # /mensual del mes del pase: A y B por broker; global sin el puente que se anula.
        mens = self._mensual()
        a, b, g = (mens[(x, 2025, 6)] for x in ("Cocos", "Balanz", "global"))
        self._trae(a, LEE_MENSUAL_A, None, "/api/monthly Cocos")
        self._trae(b, LEE_MENSUAL_B, None, "/api/monthly Balanz")
        self.assertEqual(NO_EN_GLOBAL_VIVO & set(g), set(), "global con las dos patas vivas")
        self.assertIn("gasto_pase_usd", g, "el gasto es una pérdida también en la cuenta entera")
        self.assertGreater(a["puente_salida_usd"], 0)
        self.assertAlmostEqual(a["puente_salida_usd"], b["puente_entrada_usd"], places=6)

        # Importaciones: los dos lotes del pase con su `traspaso`.
        lotes = [x for x in self._get("/api/imports").json() if x.get("traspaso")]
        self.assertEqual(len(lotes), 2)
        for x in lotes:
            self._trae(x["traspaso"], LEE_LOTE_PASE, CONTRATO_LOTE_PASE, "imports[].traspaso")
        self.assertEqual(sorted((x["broker"], x["traspaso"]["lado"], x["traspaso"]["contraparte"])
                                for x in lotes),
                         [("Balanz", "entrada", "Cocos"), ("Cocos", "salida", "Balanz")])
        self.assertTrue({x["traspaso"]["lado"] for x in lotes} <= LADOS_DEL_LOTE)

        # Cartera: cada lote trae `en_broker_desde` (la bandeja de dividendos);
        # Brokers: `is_exchange` (la familia de la cuenta, para los destinos posibles).
        pos = self._get("/api/positions").json()
        llegados = [p for p in pos if p.get("broker") == "Balanz" and p.get("asset") == "NVDA"]
        self.assertTrue(llegados and all(p["en_broker_desde"] == base.FECHA_PASE for p in llegados))
        self.assertTrue(all("en_broker_desde" in p for p in pos))
        self.assertTrue(all("is_exchange" in x for x in self._get("/api/brokers").json()))

        # Borrar el broker de destino: el 409 trae `counts.traspasos` (avisoBorrarBroker.js).
        r = self.http.delete(f"/api/brokers/{self._id_broker('Balanz')}", headers=self.h)
        self.assertEqual(r.status_code, 409, r.text)
        self._trae(r.json()["detail"], LEE_BORRAR_BROKER, None, "409 de DELETE /api/brokers")
        self._trae(r.json()["detail"]["counts"], LEE_COUNTS, None, "counts")
        self.assertEqual(r.json()["detail"]["counts"]["traspasos"], 1)

        # El porqué de «no se puede deshacer» (C.8 #4), con los costos con «$» adelante.
        llegados = sorted(llegados, key=lambda p: p["entry_date"])
        lote = self._lote(broker="Balanz", entry_date=llegados[0]["entry_date"][:10])
        self._editar(lote, quantity=1)
        motivo = self._uno(tid)["motivo"]
        self.assertEqual(motivo, "Los NVDA que llegaron a Balanz ya no están como llegaron: los "
                                 "editaste. Volvé a dejarlos como llegaron (2 a $28.000 y 3 a "
                                 "$30.000) para poder deshacer el pase.")
        tapado = self._tapado(motivo, "$28.000", "$30.000")
        self.assertIn(f"(2 a {OCULTO} y 3 a {OCULTO})", tapado)
        self.assertIs(self._uno(tid)["puede_deshacer"], False)
        r = self._deshacer(tid)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, motivo))
        self._editar(self._lote(broker="Balanz", entry_date=llegados[0]["entry_date"][:10]),
                     quantity=2)

        # Deshacer: `{ok, mensaje}`; el segundo, 409 con `detail` texto; uno ajeno, 404.
        r = self._deshacer(tid)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self._trae(r.json(), LEE_DESHACER, CONTRATO_DESHACER, "deshacer")
        self.assertEqual(r.json()["mensaje"], "Listo: los 5 NVDA volvieron a Cocos.")
        r = self._deshacer(tid)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, traspaso_a_mano.MSG_YA_DESHECHO))
        r = self._deshacer("no-existe")
        self.assertEqual((r.status_code, r.json()["detail"]), (404, traspaso_a_mano.MSG_NO_ENCONTRADO))
        self.assertEqual(self._traspasos()["traspasos"], [])
        # Deshecho, Importaciones lo sigue mostrando como pase (sin «Revertir»).
        estados = {x["traspaso"]["estado"] for x in self._get("/api/imports").json() if x.get("traspaso")}
        self.assertEqual(estados, {"deshecho"})

        # Con el interruptor apagado: GET dice `habilitado: false` y la vista previa, 403 texto.
        self._interruptor(False)
        self.assertIs(self._traspasos()["habilitado"], False)
        r = self._vista(body)
        self.assertEqual((r.status_code, r.json()["detail"]), (403, traspaso_a_mano.MSG_APAGADO))


class PaseIncompletoYDesfasado(_Contrato):

    def test_incompleto_y_desfasado_con_las_claves_que_lee_la_pantalla(self):
        """Los dos estados que cambian lo que dibuja la pantalla. DESFASADO por el lado
        de destino: GET /traspasos y las patas de Movimientos traen el MISMO `aviso`, que
        nombra la cuenta cuya historia cambió (Balanz) —antes la pantalla lo armaba y
        nombraba siempre al origen—. INCOMPLETO (se borró Balanz): `estado` en GET y en la
        pata que queda, /mensual global con el neto de la pata huérfana con signo
        (`traspaso_neto_usd` negativo: salió), y el deshacer con su texto."""
        self._historia()
        p = self._fabricar_pase("NVDA", "Cocos", "Balanz", base.FECHA_PASE, base.PRECIO_PASE,
                                cantidad=3)
        tid = p["traspaso_id"]

        conn = main.get_db()
        try:
            conn.execute("UPDATE traspasos_a_mano SET desfasado_at=datetime('now'), "
                         "desfasado_motivo='destino' WHERE id=? AND user_id=?", (tid, self.uid))
            conn.commit()
        finally:
            conn.close()
        aviso = ("Cambió la historia de Balanz y este pase quedó desactualizado: deshacelo y "
                 "hacelo de nuevo.")
        uno = self._uno(tid)
        self.assertEqual((uno["estado"], uno["aviso"]), ("desfasado", aviso))
        patas = [m for m in self._get("/api/movements").json()
                 if m["type"] in ("TRASPASO_SALIDA", "TRASPASO_ENTRADA")]
        self.assertEqual(len(patas), 2)
        for m in patas:
            self._trae(m, LEE_PATA, CONTRATO_PATA, f"movimiento {m['type']} desfasado")
            self.assertEqual((m["estado"], m["aviso"]), ("desfasado", aviso))
        conn = main.get_db()
        try:
            conn.execute("UPDATE traspasos_a_mano SET desfasado_at=NULL, desfasado_motivo=NULL "
                         "WHERE id=? AND user_id=?", (tid, self.uid))
            conn.commit()
        finally:
            conn.close()

        r = self.http.delete(f"/api/brokers/{self._id_broker('Balanz')}?force=true", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        uno = self._uno(tid)
        self._trae(uno, LEE_TRASPASO, CONTRATO_TRASPASO, "GET /traspasos[] incompleto")
        self.assertEqual((uno["estado"], uno["puede_deshacer"]), ("incompleto", True))
        self.assertTrue({uno["estado"]} <= ESTADOS)
        [pata] = [m for m in self._get("/api/movements").json()
                  if m["type"] in ("TRASPASO_SALIDA", "TRASPASO_ENTRADA")]
        self._trae(pata, LEE_PATA, CONTRATO_PATA, "pata que queda")
        self.assertEqual((pata["type"], pata["estado"], pata["contraparte"], pata["aviso"]),
                         ("TRASPASO_SALIDA", "incompleto", "Balanz", None))
        g = self._mensual()[("global", 2025, 6)]
        self._trae(g, LEE_GLOBAL_HUERFANA, None, "/api/monthly global con la pata huérfana")
        self.assertAlmostEqual(g["traspaso_neto_usd"], -p["V"], places=4)
        self.assertAlmostEqual(abs(g["traspaso_neto_pesos"]), p["V_ars"], places=2)

        r = self._deshacer(tid)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self._trae(r.json(), LEE_DESHACER, CONTRATO_DESHACER, "deshacer incompleto")
        self.assertEqual(r.json()["mensaje"],
                         "Listo: Balanz ya no existe, así que los 3 NVDA volvieron a Cocos.")


class PaseEnDolares(_Contrato):

    def test_lotes_en_dolares_traen_su_pata_con_el_dia(self):
        """Un pase de lotes en dólares: cada fila de broker de /mensual trae
        `traspaso_usd_con_dia` {dep, ret} (capitalAportado.js lo suma al dólar de ese día)
        y la global no. La vista previa y la pata de Movimientos dicen la moneda de los
        lotes."""
        self._broker("IBKR", "USD")
        self._broker("Schwab", "USD")
        self._importar("IBKR", ["2025-01-05,DEPOSITO,IBKR,,,,1000,,,,USD,dep",
                                "2025-01-10,COMPRA,IBKR,MSFT,2,300,600,,,1,USD,compra"])
        p = self._aplicar(self._pedido("MSFT", "IBKR", "Schwab", base.FECHA_PASE, moneda="USD",
                                       precio_manual=420))
        self.assertEqual(p["vista"]["valuacion"]["moneda_precio"], "USD")
        self.assertEqual({l["moneda"] for l in p["vista"]["lotes"]}, {"USD"})
        m = self._mensual()
        for broker, lado in (("IBKR", "ret"), ("Schwab", "dep")):
            con_dia = m[(broker, 2025, 6)].get("traspaso_usd_con_dia")
            self._trae(con_dia, LEE_USD_CON_DIA, LEE_USD_CON_DIA, f"traspaso_usd_con_dia {broker}")
            self.assertEqual(con_dia[lado], [[base.FECHA_PASE, 840.0]])
        self.assertNotIn("traspaso_usd_con_dia", m[("global", 2025, 6)])
        patas = [x for x in self._get("/api/movements").json()
                 if x["type"] in ("TRASPASO_SALIDA", "TRASPASO_ENTRADA")]
        self.assertEqual({x["currency"] for x in patas}, {"USD"})


class ImportarDespuesDelPase(_Contrato):

    def test_el_asistente_recibe_lo_que_dibuja(self):
        """POST /api/imports/preview después de un pase (los archivos reales de Bull
        Market y Balanz de E8): `ya_traspasados`, `filas_de_pases` (dentro de
        `duplicate_row_indices`, que el asistente resta del cartel de la huella),
        `cambian_un_pase` (UN objeto con `mensaje`, o null: la pantalla lo trata como
        objeto) y `avisos_de_pases`; el confirm frenado, 409 con `detail` texto; el que
        entra, con `omitidas_por_pases` (lo lee la tanda del asesor)."""
        self._bull_market_y_pase(cantidad=4)
        prev = self._subir("Balanz", base._balanz(base.RECIBO, base._credito("2025-06-18", 4)),
                           "balanz_movimientos")
        self._trae(prev, LEE_PREVIEW, None, "preview")
        [ya] = prev["ya_traspasados"]
        self._trae(ya, CONTRATO_YA_TRASPASADO, CONTRATO_YA_TRASPASADO, "ya_traspasados[]")
        self.assertEqual(ya["lado"], "entrada")
        self.assertIsNone(prev["cambian_un_pase"])
        self.assertEqual(prev["avisos_de_pases"], [])
        # La llegada y su depósito compensatorio: omitidas por el pase, también entre las
        # repetidas (D.2.3); por huella, ninguna.
        self.assertEqual(len(prev["filas_de_pases"]), 2)
        self.assertEqual(sorted(prev["filas_de_pases"]), sorted(prev["duplicate_row_indices"]))

        frena = self._subir("Balanz", base._balanz(base._credito("2025-07-06", 4)),
                            "balanz_movimientos")
        c = frena["cambian_un_pase"]
        self._trae(c, CONTRATO_CAMBIA_UN_PASE | {"row_index"}, CONTRATO_CAMBIA_UN_PASE | {"row_index"},
                   "cambian_un_pase (freno de 4 a 60 días)")
        self.assertIn(c["lado"], {"origen", "destino"})
        r = self._confirmar_archivo(frena)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, c["mensaje"]))

        lejos = self._subir("Balanz", base._balanz(base._credito("2025-09-14", 4)),
                            "balanz_movimientos")
        self.assertIsNone(lejos["cambian_un_pase"])
        self.assertEqual(len(lejos["avisos_de_pases"]), 1)
        self.assertTrue(all(isinstance(a, str) for a in lejos["avisos_de_pases"]))
        self.assertEqual(lejos["filas_de_pases"], [])

        r = self._confirmar_archivo(prev)
        self.assertEqual(r.status_code, 200, r.text)
        self._trae(r.json(), LEE_CONFIRM_IMPORT, None, "confirm del import")
        self.assertEqual(r.json()["omitidas_por_pases"], 2)

    def test_archivo_que_cambia_la_historia_anterior(self):
        """La regla general de C.11 en el asistente: `cambian_un_pase` con todas sus
        claves y el `mensaje` exacto de la spec; el confirm, 409 con el mismo texto."""
        self._balanz_y_pase_de_glob()
        prev = self._subir("Balanz", base._balanz(base._boleto("2025-01-05", 3, 9000)),
                           "balanz_movimientos")
        c = prev["cambian_un_pase"]
        self._trae(c, CONTRATO_CAMBIA_UN_PASE, CONTRATO_CAMBIA_UN_PASE, "cambian_un_pase (C.11)")
        self.assertEqual(c["mensaje"],
                         "Este archivo trae compras de GLOB en Balanz del 05/01/2025, anteriores a "
                         "tu pase del 16/06/2025 a Cocos. Si lo confirmamos, el pase quedaría con "
                         "otros lotes. Deshacé el pase (Movimientos → la fila «Pase» → Deshacer), "
                         "importá el archivo y volvé a moverlos.")
        r = self._confirmar_archivo(prev)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, c["mensaje"]))
