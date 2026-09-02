"""TWR del LIBRO — la capa del asesor, encima de `twr.py`.

Todo lo que sea cálculo por persona vive en `twr.py` y NO acá: un cliente de un
asesor es un usuario, y si el retorno se calcula distinto según por qué pantalla
se entra, volvemos a tener dos motores que se contradicen.

FASE 0: salud de los datos del libro. Read-only.
"""
import logging

import twr

log = logging.getLogger(__name__)


def _clientes_vigentes(conn, advisor_uid: int) -> dict:
    """{client_uid: etiqueta} de los clientes ACTIVOS hoy.

    ⚠️ Para el TWR de un período histórico esto NO alcanza: hay que usar el
    roster VIGENTE en cada mes (`created_at` / `revoked_at`), o el que se da de
    baja hoy desaparece de toda la historia y el retorno del año pasado mejora
    solo — el sesgo de supervivencia clásico. Acá se usa el roster de hoy a
    propósito: el semáforo responde "de quién puedo hablar AHORA".
    """
    return {r["client_uid"]: (r["label"] or r["name"] or f"Cliente {r['client_uid']}")
            for r in conn.execute(
                """SELECT ac.client_uid, ac.label, u.name
                   FROM advisor_clients ac JOIN users u ON u.id = ac.client_uid
                   WHERE ac.advisor_uid=? AND ac.status='active'""", (advisor_uid,)).fetchall()}


def salud_del_libro(conn, advisor_uid: int) -> dict:
    """Por cliente: desde cuándo su historia es medible a mercado, y si no lo
    es, por qué. Es el prerrequisito honesto del TWR — y el mapa que le dice al
    agente reconstructor por dónde empezar a hurgar."""
    labels = _clientes_vigentes(conn, advisor_uid)
    if not labels:
        return {"clientes": [], "resumen": {"total": 0, "medibles": 0, "cobertura_pct": 0.0}}

    diag = twr.diagnosticar(conn, list(labels))

    clientes = []
    for cid, label in sorted(labels.items(), key=lambda kv: kv[1].lower()):
        d = diag.get(cid) or {}
        motivo = d.get("motivo")
        clientes.append({
            "client_uid": cid,
            "label": label,
            "medible_desde": d.get("medible_desde"),
            "ultima_medicion": d.get("ultima_medicion"),
            "motivo": motivo,
            "motivo_texto": twr.MOTIVO_TEXTO.get(motivo) if motivo else None,
            "snapshots": d.get("snapshots", 0),
            "por_clase": d.get("por_clase", {}),
            "tramos_planos": d.get("tramos_planos", []),
        })

    medibles = sum(1 for c in clientes if c["medible_desde"])
    return {
        "clientes": clientes,
        "resumen": {
            "total": len(clientes),
            "medibles": medibles,
            # La cobertura va SIEMPRE pegada al número. Un TWR sin decir sobre
            # cuántos clientes se midió es exactamente el tipo de dato que
            # después hay que salir a explicar.
            "cobertura_pct": round(medibles / len(clientes) * 100, 1) if clientes else 0.0,
            "con_tramos_planos": sum(1 for c in clientes if c["tramos_planos"]),
        },
    }


# Debajo de este piso no se muestra porcentaje: se muestra el motivo. Un TWR de
# dos meses presentado a secas es exactamente el número que después hay que
# salir a explicar.
MESES_MINIMOS = 3


def twr_por_cliente(conn, advisor_uid: int, sellar_primero: bool = True) -> dict:
    """TWR de cada cliente del libro, con la cobertura pegada al número.

    Sella los meses cerrados antes de leer (idempotente: si nada cambió, no
    escribe nada). El TWR del LIBRO — el composite ponderado por capital — es
    la Fase 2: NO se puede sacar promediando estos números, porque el peso de
    cada cliente cambia mes a mes.
    """
    labels = _clientes_vigentes(conn, advisor_uid)
    if not labels:
        return {"clientes": [], "resumen": {"total": 0, "con_twr": 0}}

    out = []
    for cid, label in sorted(labels.items(), key=lambda kv: kv[1].lower()):
        if sellar_primero:
            try:
                twr.sellar(conn, cid)
            except Exception as ex:            # un cliente roto no tumba el libro
                log.warning("twr sellar uid=%s: %s", cid, ex)
        r = twr.twr_de(conn, cid)
        meses = r.get("meses", 0)
        publicable = r["twr"] is not None and meses >= MESES_MINIMOS
        # ⚠️ EL MOTIVO DEL MOTOR MANDA. Con `"pocos_meses" if meses else motivo`, un
        # cliente con 6 meses sellados y uno dudoso (twr None, motivo
        # 'medicion_dudosa') salía como "pocos_meses": el aviso equivocado.
        out.append({
            "client_uid": cid, "label": label,
            "twr": r["twr"] if publicable else None,
            "meses": meses,
            "desde": r.get("desde"), "hasta": r.get("hasta"),
            "motivo": None if publicable else (r.get("motivo") or "pocos_meses"),
            "motivo_texto": (None if publicable else
                             twr.MOTIVO_TEXTO.get(r.get("motivo") or "")),
            "meses_revisados": r.get("meses_revisados", []),
            "meses_degradados": r.get("meses_degradados", []),
            "meses_dudosos": r.get("meses_dudosos", []),
        })

    return {
        "clientes": out,
        "resumen": {
            "total": len(out),
            "con_twr": sum(1 for c in out if c["twr"] is not None),
            "meses_minimos": MESES_MINIMOS,
        },
    }
