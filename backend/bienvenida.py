"""¿Esta cuenta tiene que pasar por la bienvenida antes de ver Rendi? UNA sola regla.

Qué decidió el dueño (25/11/2026)
─────────────────────────────────
Quien se registra NO ve Rendi hasta haber subido y confirmado un archivo de su
broker (o la planilla propia de Rendi, que también es un archivo). Cargar a mano
no destraba. Mientras falte, la app lo manda a la bienvenida (/onboarding).

Esta función es la ÚNICA que decide eso. La lee `/api/auth/me`
(`falta_cargar_historial`) y la pantalla obedece; ninguna otra parte del código
vuelve a preguntarlo con su propia consulta.

Quiénes quedan afuera
─────────────────────
  · el admin;
  · el asesor (plan 'advisor') y los clientes que crea un asesor (la ficha
    administrada, `managed_by`, y la que el cliente después reclamó: el vínculo
    'managed' sigue en `advisor_clients` aunque `managed_by` vuelva a NULL);
  · las cuentas creadas ANTES del corte: a quien ya usaba Rendi no se le cambia
    la entrada de un día para el otro.

Qué cuenta como «cargó su historial»
────────────────────────────────────
Un lote de `import_batches` confirmado. Los revertidos y los que quedaron en
vista previa no cuentan (no hay nada cargado). Los dos lotes que escribe un pase
entre brokers tampoco: mueven lo que ya estaba, no traen nada de un archivo — la
condición la tiene un solo dueño, `traspaso_a_mano.no_es_un_pase`. Las fotos de
tenencia confirmadas y la conexión con Wallbit SÍ cuentan: son el archivo o la
conexión del broker. Si la persona borra todo («Empezar de cero» borra sus lotes)
o deshace su único import, vuelve a faltar, y la app la lleva de nuevo a la
bienvenida.

Falla abierta
─────────────
Ante cualquier error devuelve False y lo deja en el registro. Un error acá no
puede encerrar a todos afuera de su cuenta: la bienvenida es una guía, no una
cerradura — lo peor que pasa si falla es que alguien entra sin haberla hecho.
"""
import logging

from importing.traspaso_a_mano import no_es_un_pase

log = logging.getLogger(__name__)

# Corte: las cuentas creadas ANTES no quedan obligadas. users.created_at está en UTC
# (datetime('now')); 2026-11-25 03:00 UTC = 25/11 00:00 en Argentina.
BIENVENIDA_OBLIGATORIA_DESDE = "2026-11-25 03:00:00"


def _normalizar_fecha(valor) -> str:
    """'2026-11-25T03:00:00.123+00:00' y '2026-11-25 03:00:00' → '2026-11-25 03:00:00'.

    ⚠️ La trampa ya vivida cuatro veces: Python escribe la fecha con 'T' y SQLite
    (datetime('now')) con espacio. Comparadas como texto, 'T' es mayor que el
    espacio, así que una cuenta de ANTES del corte escrita con 'T' el mismo día
    pasaba por posterior. Se normalizan las dos puntas al mismo formato."""
    return str(valor).replace("T", " ")[:19]


_CORTE = _normalizar_fecha(BIENVENIDA_OBLIGATORIA_DESDE)


def falta_cargar_historial(conn, uid) -> bool:
    """True sólo si esta cuenta tiene que pasar por la bienvenida (ver arriba).

    `uid` es el de la persona que INICIÓ SESIÓN. `/api/auth/me` nunca contesta por
    el cliente que mira un asesor (ignora el encabezado X-Rendi-Client-Id: `/api/auth`
    es una ruta exenta), así que ahí el asesor recibe su propio valor."""
    try:
        row = conn.execute(
            "SELECT is_admin, managed_by, created_at FROM users WHERE id=?",
            (uid,)).fetchone()
        if not row:
            return False
        if row["is_admin"]:
            return False
        if row["managed_by"] is not None:
            return False
        # La fecha va antes que las dos consultas de abajo: sale de la misma fila,
        # y las cuentas de antes del corte —casi todas, por ahora— no necesitan
        # más. `/api/auth/me` corre en cada arranque de la app.
        if not row["created_at"]:
            return False
        if _normalizar_fecha(row["created_at"]) < _CORTE:
            return False

        from ai import quota as _q
        if _q.get_tier(conn, uid) == "advisor":
            return False

        # Cliente creado por un asesor que después reclamó su cuenta: `managed_by`
        # ya es NULL, pero el vínculo 'managed' queda (en cualquier estado).
        cliente = conn.execute(
            "SELECT 1 FROM advisor_clients WHERE client_uid=? AND link_type='managed' "
            "LIMIT 1", (uid,)).fetchone()
        if cliente:
            return False

        cargado = conn.execute(
            "SELECT 1 FROM import_batches WHERE user_id=? AND status='confirmed' "
            f"AND {no_es_un_pase()} LIMIT 1", (uid,)).fetchone()
        return cargado is None
    except Exception as ex:
        log.warning("falta_cargar_historial falló uid=%s: %s", uid, ex)
        return False
