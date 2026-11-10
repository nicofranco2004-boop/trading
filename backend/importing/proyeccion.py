"""Qué tenía esta persona a la FECHA DE LA FOTO, para poder reconciliar antes de confirmar.

`compute_reconcile` compara la foto contra el estado de HOY. Eso vale sólo si la
foto ES de hoy. Si los movimientos del import llegan más allá de su fecha, toda
compra posterior aparece como "Rendi tiene de más" y toda venta posterior como un
falso "coincide". Este módulo produce el otro lado de la comparación: la tenencia
a la fecha D, contando además lo que el preview agregaría.

🔴 ANCLA EN `positions`, NO EN UN REPLAY DEL LEDGER — Y ESA ES LA DECISIÓN
   IMPORTANTE DEL MÓDULO.

   Existe `ledger_replay.tenencia_en(uid, fecha)`, que replaya `import_normalized_tx`
   hacia adelante. Usarla acá tendría un costo que este repo ya pagó: sería un
   SEGUNDO MOTOR DE TENENCIA. Cuando el resultado y la foto no coincidieran, no
   habría forma de saber si el import está mal o si el segundo motor está mal. Es
   exactamente lo que pasó con `valor_en`, que terminó siendo un segundo motor de
   valuación y hubo que enderezarlo para que delegara en el canónico —su propio
   docstring lo cuenta: "tener un segundo motor de valuación es como se vuelve a
   los ~15 motores de retorno que este trabajo viene a cerrar".

   Anclando en `positions` se compara LO QUE EL USUARIO EFECTIVAMENTE VE, rodado
   hacia atrás, contra lo que el broker dijo. Una sola cadena, un solo motor.

   Efecto secundario que importa: la reproducibilidad del replay contra
   `positions` (37,4% base-wide, 41,2% en cuentas de un solo import) deja de ser
   relevante. Ese número mide la distancia entre una suma ingenua de BUY−SELL y
   un FIFO completo —con cancelación de conductos, spill cross-currency, sweeps,
   splits y lotes semilla—, no corrupción de datos. Con el ancla correcta esa
   distancia no se mide y no bloquea a nadie.

LO QUE NO SE PUEDE RODAR HACIA ATRÁS
────────────────────────────────────
No todo movimiento deja rastro reversible. Lo que no se puede deshacer con
confianza NO se adivina: sale en `no_reconciliable` con su motivo, y el override
no lo toca. Los motivos están medidos contra la copia de prod del 2026-08-16:

  · `datos_manuales`        — alta/venta/edición desde la UI: no hay fila en el
                              ledger que restar. 1.082 de 31.433 lotes vivos.
  · `vencimiento_en_ventana`— `sweep_matured_letras` BORRÓ la posición entre D y
                              hoy; `positions` ya no tiene el nominal que había.
  · `split_en_ventana`      — el ajuste multiplicó la cantidad sin dejar
                              movimiento, y el watermark es un piso, no el total.

Lo que SÍ se corrige, porque la función que lo produjo acepta fecha:

  · amortización de bonos — `positions.quantity` de hoy es
    `nominal × residual_factor(HOY)`; a la fecha D era `nominal ×
    residual_factor(D)`. Se re-escala por el cociente.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple

from .schema import TX_VIVAS

log = logging.getLogger(__name__)

# Motivos por los que un activo NO se puede proyectar con confianza. Enum cerrado:
# un motivo nuevo se agrega acá y no como string suelto en el sitio de uso.
MOTIVO_MANUAL = "datos_manuales"
MOTIVO_VENCIMIENTO = "vencimiento_en_ventana"
MOTIVO_SPLIT = "split_en_ventana"
# Lo archivado (`/api/sections/archive`): las posiciones salieron de la cartera
# sin venta ni plata, así que Rendi no las ve y la foto las leía como «no las
# tenías» → las volvía a comprar con un aporte sintético (y restaurarlas después
# las duplicaba). No depende de la fecha: archivado antes o después de la foto,
# la cartera no dice cuánto había.
MOTIVO_ARCHIVADO = "posiciones_archivadas"
# Los motivos de esta lista: lo que la cartera no puede decir a la fecha de la foto.
MOTIVOS_PROYECCION = (MOTIVO_MANUAL, MOTIVO_VENCIMIENTO, MOTIVO_SPLIT, MOTIVO_ARCHIVADO)


def _norm(s) -> str:
    return (s or "").strip().upper()


def _comparable(asset, asset_type=None) -> str:
    """El nombre con el que la cartera se compara contra la foto: la MISMA
    traducción que pasa la foto (`tenencia.ticker_comparable`). Ver ahí por qué."""
    from .tenencia import ticker_comparable
    return ticker_comparable(asset, asset_type)


def posiciones_por_ticker(conn, uid: int, brokers: List[str]) -> Dict[str, dict]:
    """Lo que la cartera tiene HOY en esos brokers, con el nombre de la comparación:
    `{ticker: {"q": cantidad, "inv": invertido, "nombres": {como está guardado},
    "tipo": asset_type}}`.

    Es el único lugar que lee `positions` para comparar contra la foto: la
    proyección, la foto sin fecha, el reparto por cuenta y las guardas del modo
    que pisa leen todos de acá, así que la traducción no puede faltar en uno.
    `nombres` sirve para lo contrario: un ajuste se escribe con el nombre de la
    comparación, así que si la cartera lo guarda con OTRO (GOLD, AL30D), la venta
    no encontraría esos lotes — el modo que pisa no lo toca solo."""
    out: Dict[str, dict] = {}
    if not brokers:
        return out
    ph = ",".join("?" * len(brokers))
    for r in conn.execute(
            f"SELECT asset, asset_type, SUM(quantity) q, SUM(invested) inv FROM positions "
            f"WHERE user_id=? AND COALESCE(is_cash,0)=0 AND broker IN ({ph}) "
            f"GROUP BY asset, asset_type", (uid, *brokers)):
        k = _comparable(r["asset"], r["asset_type"])
        if not k:
            continue
        d = out.setdefault(k, {"q": 0.0, "inv": 0.0, "nombres": set(), "tipo": r["asset_type"]})
        d["q"] += float(r["q"] or 0)
        d["inv"] += float(r["inv"] or 0)
        d["nombres"].add(_norm(r["asset"]))
    return out


def archivados(conn, uid: int, brokers: List[str]) -> set:
    """Los activos de esos brokers que están en una sección archivada (con el
    nombre de la comparación). Ver `MOTIVO_ARCHIVADO`."""
    import json as _json
    par = set(brokers or ())
    out = set()
    for r in conn.execute("SELECT payload FROM archived_positions WHERE user_id=?", (uid,)):
        try:
            filas = _json.loads(r["payload"] or "[]") or []
        except (TypeError, ValueError):
            continue
        for f in filas:
            if isinstance(f, dict) and f.get("broker") in par and not f.get("is_cash"):
                k = _comparable(f.get("asset"), f.get("asset_type"))
                if k:
                    out.add(k)
    return out


def tenencia_sin_rodar(conn, uid: int, *, pair: List[str]) -> Tuple[Dict[str, float], List[dict]]:
    """Lo mismo que `proyectar` cuando la foto no tiene fecha: la cartera de hoy,
    sin rodar nada hacia atrás (no hay a qué fecha), con la misma traducción de
    tickers y dejando afuera lo archivado."""
    pos = posiciones_por_ticker(conn, uid, pair)
    fuera = archivados(conn, uid, pair)
    no_rec = [{"ticker": a, "motivo": MOTIVO_ARCHIVADO,
               "rendi_qty_hoy": round(pos.get(a, {}).get("q", 0.0), 6)} for a in sorted(fuera)]
    return ({a: round(d["q"], 6) for a, d in pos.items() if d["q"] > 1e-9 and a not in fuera},
            no_rec)


def proyectar(conn, uid: int, *, pair: List[str], fecha: str,
              session_id: str = None, hoy: str = None,
              tickers_foto=None) -> Tuple[Dict[str, float], List[dict]]:
    """`({activo: cantidad}, [no_reconciliable])` a la fecha `fecha`.

    `pair` son los brokers del par padre↔'· USD' (ver `persister.broker_pair`):
    el mismo activo comprado en una moneda y vendido en la otra queda partido
    entre los dos, así que la tenencia se mide sobre el par y no sobre un broker.

    `session_id` suma además las filas de un batch en preview — es la parte de
    "qué quedaría si confirmo esto".
    """
    from datetime import datetime, timedelta
    from pricing.bond_amortization import residual_factor
    from .maturity import letra_maturity

    D = str(fecha)[:10]
    from fechas import hoy_art
    HOY = hoy or hoy_art()
    ph = ",".join("?" * len(pair))

    # ── 1. El ancla: lo que el usuario ve HOY, por el par de brokers ─────────
    # Con el nombre de la comparación (`posiciones_por_ticker`): la foto ya pasó
    # por la misma traducción. `tipos` sirve para traducir lo que no guarda el
    # tipo de activo (las operaciones a mano).
    pos = posiciones_por_ticker(conn, uid, pair)
    qty: Dict[str, float] = {a: d["q"] for a, d in pos.items()}
    tipos: Dict[str, str] = {n: d["tipo"] for d in pos.values() for n in d["nombres"]}

    dudosos: Dict[str, str] = {}
    for a in archivados(conn, uid, pair):
        dudosos[a] = MOTIVO_ARCHIVADO

    # ── 2. Deshacer los movimientos POSTERIORES a D ──────────────────────────
    # Una compra posterior a la foto no estaba ahí: se resta. Una venta
    # posterior sí estaba: se suma. Es la única forma de que una operación hecha
    # después del corte no aparezca como discrepancia contra el broker.
    for r in conn.execute(
            f"""SELECT n.asset_symbol a, n.asset_type t, n.operation_type op, n.quantity q
                  FROM {TX_VIVAS}
                 WHERE b.user_id=? AND n.broker IN ({ph})
                   AND n.date > ? AND n.asset_symbol IS NOT NULL
                   AND n.operation_type IN ('BUY','SELL')""", (uid, *pair, D)):
        v = float(r["q"] or 0)
        if v <= 0:
            continue
        a = _comparable(r["a"], r["t"] or tipos.get(_norm(r["a"])))
        qty[a] = qty.get(a, 0.0) - (v if r["op"] == "BUY" else -v)

    # ── 3. Sumar lo que el PREVIEW agregaría hasta D ─────────────────────────
    if session_id:
        for r in conn.execute(
                """SELECT n.asset_symbol a, n.asset_type t, n.operation_type op, n.quantity q
                     FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id
                    WHERE b.user_id=? AND b.id=? AND n.excluded_at IS NULL
                      AND n.date <= ? AND n.asset_symbol IS NOT NULL
                      AND n.operation_type IN ('BUY','SELL')""", (uid, session_id, D)):
            v = float(r["q"] or 0)
            if v <= 0:
                continue
            a = _comparable(r["a"], r["t"] or tipos.get(_norm(r["a"])))
            qty[a] = qty.get(a, 0.0) + (v if r["op"] == "BUY" else -v)

    # ── 4. Los que NO se pueden rodar hacia atrás ────────────────────────────
    # Lo cargado a mano después de D (operaciones Y compras): no hay fila en el
    # ledger que restar, así que el paso 2 no lo deshizo y el número queda mal
    # sin avisar. Hasta el 2026-11-07 sólo se miraban las operaciones: una compra
    # a mano posterior salía como «ausente en la foto», con pedido de cerrarla.
    for m in _a_mano_posterior(conn, uid, pair, D):
        a = _comparable(m["activo"], m.get("tipo_activo") or tipos.get(_norm(m["activo"])))
        if a and _cambia_cantidad(m):
            dudosos.setdefault(a, MOTIVO_MANUAL)

    # Splits ajustados dentro de la ventana: la cantidad de hoy está multiplicada
    # por un factor que no dejó movimiento.
    for r in conn.execute(
            f"""SELECT asset a, asset_type t, split_adjusted_through s FROM positions
                 WHERE user_id=? AND COALESCE(is_cash,0)=0 AND broker IN ({ph})
                   AND split_adjusted_through IS NOT NULL""", (uid, *pair)):
        if str(r["s"] or "")[:10] > D:
            dudosos.setdefault(_comparable(r["a"], r["t"]), MOTIVO_SPLIT)

    # ── 5. Correctores FECHADOS ──────────────────────────────────────────────
    # Una letra que la FOTO lista y que venció entre D y hoy: el sweep ya la
    # borró de `positions`, así que no está en `qty` y el bucle de abajo no la
    # veía. Sin esto la foto la "completaba" (compra + aporte sintético) y el
    # sweep la volvía a borrar: quedaba un aporte que nunca existió (revisión
    # del 2026-11-08: $100.000 sobre una cuenta de $102.000).
    for t in (tickers_foto or ()):
        v = letra_maturity(_norm(t))
        if v and D < v[:10] <= HOY:
            dudosos.setdefault(_norm(t), MOTIVO_VENCIMIENTO)
    for a in list(qty):
        # Letra que venció ENTRE D y hoy: el sweep borró la posición, así que
        # `positions` ya no tiene el nominal que la persona sí tenía en D.
        # Recuperarlo del ledger sería reintroducir el segundo motor.
        v = letra_maturity(a)
        if v and D < v[:10] <= HOY:
            dudosos.setdefault(a, MOTIVO_VENCIMIENTO)
            continue
        # Bono amortizante: hoy vale nominal × rf(hoy); en D valía nominal × rf(D).
        rf_hoy, rf_d = residual_factor(a, HOY), residual_factor(a, D)
        if rf_hoy > 0 and abs(rf_d - rf_hoy) > 1e-9:
            qty[a] = qty[a] * (rf_d / rf_hoy)

    no_rec = [{"ticker": a, "motivo": m,
               "rendi_qty_hoy": round(qty.get(a, 0.0), 6)}
              for a, m in sorted(dudosos.items())]
    limpio = {a: round(v, 6) for a, v in qty.items()
              if v > 1e-9 and a not in dudosos}
    return limpio, no_rec


def _a_mano_posterior(conn, uid: int, pair: List[str], D: str) -> List[dict]:
    """Lo cargado DESDE LA PANTALLA en el par con fecha posterior a D: las
    operaciones (ventas, conversiones, cierres de futuros, cobros) y las compras
    (`positions` sin vínculo a un import, el mismo criterio que
    `rebuild._is_safe_to_rebuild`). Es UNA definición para las dos preguntas:
    qué activos no se pueden comparar (`proyectar`) y si la caja se puede
    comparar (`plata_posterior`). Con dos listas, una vio la compra y la otra no."""
    ph = ",".join("?" * len(pair))
    out: List[dict] = []
    for r in conn.execute(
            f"""SELECT o.date d, o.broker b, o.asset a, o.op_type t FROM operations o
                 WHERE o.user_id=? AND o.date > ? AND o.broker IN ({ph})
                   AND NOT EXISTS (SELECT 1 FROM import_op_links l
                                    WHERE l.operation_id = o.id)""",
            (uid, D, *pair)):
        out.append({"origen": "operacion_a_mano", "fecha": str(r["d"])[:10],
                    "broker": r["b"], "activo": r["a"], "tipo": r["t"]})
    vinculadas = {r["position_id"] for r in conn.execute(
        """SELECT DISTINCT l.position_id FROM import_op_links l
             JOIN import_batches b ON b.id = l.batch_id
            WHERE b.user_id=? AND l.position_id IS NOT NULL""", (uid,))}
    for r in conn.execute(
            f"""SELECT id, entry_date d, broker b, asset a, asset_type t FROM positions
                 WHERE user_id=? AND COALESCE(is_cash,0)=0 AND broker IN ({ph})
                   AND entry_date IS NOT NULL""", (uid, *pair)):
        if r["id"] not in vinculadas and str(r["d"])[:10] > D:
            out.append({"origen": "compra_a_mano", "fecha": str(r["d"])[:10],
                        "broker": r["b"], "activo": r["a"], "tipo": "compra",
                        "tipo_activo": r["t"]})
    return out


# Lo cargado a mano que CAMBIA LA CANTIDAD de un activo: una venta (desde
# «Vender» o registrada como operación) y una compra (alta de posición). Un
# dividendo, un cupón, un interés, una conversión o el cierre de un futuro dejan
# su renglón en `operations` pero no tocan la tenencia: para la PLATA cuentan,
# para la CANTIDAD no (revisión del 2026-11-08: un dividendo a mano de KO, que
# Rendi no tenía, hacía que la foto dejara de completar KO).
def _cambia_cantidad(m: dict) -> bool:
    return (m.get("origen") == "compra_a_mano"
            or str(m.get("tipo") or "").strip().lower() in ("venta", "sell"))


def plata_posterior(conn, uid: int, *, pair: List[str], fecha: str) -> List[dict]:
    """Movimientos de PLATA del par posteriores a la fecha de la foto.

    Es el otro lado de `proyectar` para la caja. El ajuste de efectivo de la foto
    comparaba la caja de HOY contra la de la foto: con una foto del 05/09 y un
    cobro del 20/10, el ajuste retiraba el cobro (medido el 07/11: $1.000.000 →
    $500). Para las tenencias eso no pasa porque `proyectar` deshace lo posterior;
    para la plata NO se deshace —haría falta repetir las reglas de caja del
    persister, un segundo motor de caja—, así que la decisión es la del paso 4 de
    `proyectar`: lo que no se puede rodar hacia atrás no se adivina. Si esto
    devuelve algo, el ajuste de efectivo no corre.

    «Posterior» es lo mismo que en `proyectar`: fecha estrictamente mayor que la
    de la foto. Se buscó en los 37 lugares de `main.py` que llaman a
    `_adjust_broker_cash` (más el persister) cuáles dejan un renglón con fecha:
      · lo importado (cualquier tipo: una compra también saca plata);
      · los depósitos, retiros, autodepósitos y conciliaciones a mano
        (`flujos_a_mano`); los que no tienen día cuentan por el día ARGENTINO en
        que se cargaron (`cargado_at` es UTC);
      · lo cargado desde la pantalla: operaciones (ventas, conversiones, cierres
        de futuros, cobros de bonos) y compras (`_a_mano_posterior`);
      · los plazos fijos armados después con plata de este par. Desde el
        2026-11-10 el plazo fijo guarda de qué broker salió (`origen_plazo_fijo`);
        el armado con plata de afuera no tocó ninguna cuenta y no cuenta. Los de
        antes no lo guardan: cuentan siempre (la duda frena el ajuste: lo que se
        pierde es una corrección, no plata). Los COBRADOS después cuentan todos:
        la fila no dice a qué cuenta entró la plata.
    Los borrados y los «deshacer» de movimientos sacan el renglón y su plata
    juntos: la caja queda coherente con lo que queda y no hace falta mirarlos.
    Borrar un plazo fijo también, desde el 2026-11-10: le devuelve la plata al
    broker de donde salió (antes la dejaba debitada, sin rastro, y el ajuste de
    una foto posterior la «reponía» como un aporte). Archivar una sección no
    mueve plata (oculta las posiciones): lo archivado queda fuera de la
    comparación de tenencias (`MOTIVO_ARCHIVADO`), y la caja no cambia.
    """
    from fechas import dia_art_de_texto
    D = str(fecha)[:10]
    ph = ",".join("?" * len(pair))
    out: List[dict] = []
    for r in conn.execute(
            f"""SELECT n.date d, n.broker b, n.operation_type op FROM {TX_VIVAS}
                 WHERE b.user_id=? AND n.broker IN ({ph}) AND n.date > ?""",
            (uid, *pair, D)):
        out.append({"origen": "importado", "fecha": str(r["d"])[:10], "broker": r["b"],
                    "tipo": r["op"]})
    for r in conn.execute(
            f"""SELECT fecha, cargado_at, broker, direction FROM flujos_a_mano
                 WHERE user_id=? AND broker IN ({ph}) AND anulado_at IS NULL""",
            (uid, *pair)):
        dia = str(r["fecha"])[:10] if r["fecha"] else dia_art_de_texto(r["cargado_at"])
        if dia and dia > D:
            out.append({"origen": "a_mano", "fecha": dia, "broker": r["broker"],
                        "tipo": r["direction"]})
    for m in _a_mano_posterior(conn, uid, pair, D):
        out.append({"origen": m["origen"], "fecha": m["fecha"], "broker": m["broker"],
                    "tipo": "operacion"})
    for r in conn.execute(
            "SELECT fecha_inicio, closed_at, undo_meta_json FROM plazos_fijos WHERE user_id=?",
            (uid,)):
        ini = str(r["fecha_inicio"] or "")[:10]
        conocido, de_broker = origen_plazo_fijo(r["undo_meta_json"])
        if ini > D and (not conocido or de_broker in pair):
            out.append({"origen": "plazo_fijo", "fecha": ini, "broker": de_broker,
                        "tipo": "armado"})
        cobro = dia_art_de_texto(r["closed_at"])
        if cobro and cobro > D:
            out.append({"origen": "plazo_fijo", "fecha": cobro, "broker": None, "tipo": "cobrado"})
    return out


def origen_plazo_fijo(receta: Optional[str]) -> Tuple[bool, Optional[str]]:
    """De qué broker salió la plata de un plazo fijo: `(se sabe, broker)`.

    `(True, None)` = plata de afuera de Rendi (no tocó ninguna cuenta);
    `(False, None)` = no se sabe (armado antes de que se guardara, 2026-11-10)."""
    import json as _json
    if not receta:
        return False, None
    try:
        meta = _json.loads(receta) or {}
    except (TypeError, ValueError):
        return False, None
    if not isinstance(meta, dict) or meta.get("src") != "pf_alta":
        return False, None
    return True, (meta.get("broker") or None)


MOTIVO_NO_VERIFICA = "proyeccion_no_verifica"

# 🔴 TRES ESTADOS, Y NINGUNO PUEDE COLAPSAR CON OTRO.
#
# Esto devolvía `None` para DOS cosas opuestas —"coincide" y "no había con qué
# comparar"— y el endpoint las publicaba juntas como `verifica: true`. O sea que
# el campo afirmaba una verificación que en la mitad de los casos no se hizo, y
# justo en la dimensión donde alguien se apoyaría para confiar en un retroceso
# largo.
#
# Se cazó corriendo una foto REAL de tres meses atrás contra una DB temporal:
# el flag dio `true` con CERO snapshots del cron en la base. No es un caso de
# laboratorio — una cuenta nueva, o cualquier fecha anterior al primer snapshot
# del cron, cae ahí.
#
# `sin_referencia` NO es una buena noticia y no se puede presentar como tal:
# significa que la comparación contra la foto no tiene respaldo independiente,
# que es lo MISMO que dice `no_coincide` sobre la confianza a tenerle — cambia
# el motivo, no la conclusión.
ESTADO_OK = "verificado_ok"
ESTADO_NO_COINCIDE = "no_coincide"
ESTADO_SIN_REFERENCIA = "sin_referencia"


def verificar_contra_snapshot(conn, uid: int, fecha: str,
                              proyectado: Dict[str, float]) -> dict:
    """¿La proyección reproduce la composición que el cron estampó ese día?

    Es la prueba más dura disponible y sale gratis: `snapshots.holdings_json` con
    `source='cron'` es una referencia INDEPENDIENTE — no sale del replay del
    ledger ni de la foto del broker, la escribió el cron nocturno. Si el
    retroceso está bien, coincide.

    Devuelve SIEMPRE un dict con `estado` — ver los tres estados arriba.

    Validado contra la copia de prod del 2026-08-16 sobre 3.855 pares
    (usuario, fecha): **98,6% de composición exacta**, y 13 de 440 usuarios
    (3,0%) no coinciden. De esos 13, 3 se explican porque confirmaron un import
    DESPUÉS del snapshot —o sea que el cron no podía saber— y 10 quedan sin
    explicar. Dos hipótesis probadas y DESCARTADAS: que el snapshot omitiera
    activos sin precio (15 de 16 sí aparecen en snapshots de otros usuarios), y
    que fuera un desfase de fechas de import (sólo 3 de 13).

    ⚠️ LÍMITE DE LA REFERENCIA: el snapshot registra lo que Rendi SABÍA ese día,
    no lo que la persona tenía. Un import cargado después lo deja corto — y en
    ese caso la proyección está MÁS en lo cierto que la referencia. Por eso el
    desacuerdo no invalida el número: marca que no se pudo verificar, que es
    distinto.

    ⚠️ Y compara COMPOSICIÓN, no cantidades: `holdings_json` guarda `value_usd`.
    Alcanza para lo que importa, porque los dos veredictos peligrosos del
    reconcile —"sobra un activo", que el override cierra con una venta
    sintética, y "falta un activo", que crea un lote— son de composición.
    """
    import json as _json
    _sin = lambda por: {  # noqa: E731
        "estado": ESTADO_SIN_REFERENCIA, "motivo_sin_referencia": por,
        "detalle": ("no hay un snapshot del cron con el que contrastar la "
                    "proyección a esa fecha, así que la comparación contra la "
                    "foto no tiene respaldo independiente. No quiere decir que "
                    "esté bien: quiere decir que no se pudo comprobar."),
    }
    fila = conn.execute(
        """SELECT date, holdings_json FROM snapshots
            WHERE user_id=? AND source='cron' AND date <= ?
              AND holdings_json IS NOT NULL AND holdings_json <> ''
            ORDER BY date DESC LIMIT 1""", (uid, str(fecha)[:10])).fetchone()
    if not fila:
        return _sin("no_hay_snapshot_del_cron_hasta_esa_fecha")
    # El registro diario guarda el activo como está en la cartera (GOLD, AL30D) y la
    # proyección viene con el nombre de la comparación (B, AL30): se traduce con la
    # misma función. El registro no guarda el tipo de activo: sale de la cartera.
    tipos = {_norm(r["asset"]): r["asset_type"] for r in conn.execute(
        "SELECT DISTINCT asset, asset_type FROM positions WHERE user_id=? "
        "AND COALESCE(is_cash,0)=0", (uid,))}
    try:
        esperado = {_comparable(h.get("asset"), tipos.get(_norm(h.get("asset"))))
                    for h in _json.loads(fila["holdings_json"]) if h.get("asset")}
    except (ValueError, TypeError):
        return _sin("holdings_json_ilegible")
    if not esperado:
        return _sin("el_snapshot_no_lista_activos")
    obtenido = set(proyectado)
    falta, sobra = sorted(esperado - obtenido), sorted(obtenido - esperado)
    if not falta and not sobra:
        return {"estado": ESTADO_OK, "snapshot_fecha": fila["date"]}
    return {
        "estado": ESTADO_NO_COINCIDE,
        "motivo": MOTIVO_NO_VERIFICA,
        "snapshot_fecha": fila["date"],
        "falta": falta[:20],   # el cron lo tenía y la proyección no
        "sobra": sobra[:20],   # la proyección lo tiene y el cron no
        "detalle": ("la proyección a esa fecha no reproduce la composición que "
                    "el cron habia estampado. Puede ser que la proyección esté "
                    "mal, o que el cron no supiera todavía (un import cargado "
                    "después lo deja corto). En cualquiera de los dos casos no "
                    "se puede afirmar que la comparación contra la foto sea "
                    "válida."),
    }
