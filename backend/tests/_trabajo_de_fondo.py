"""Esperar a que terminen las reconstrucciones que la app lanza de fondo.

POR QUÉ. Importar un archivo, crear un broker o revertir lanzan la reconstrucción
del historial en un hilo aparte (`main._reconstruir_mtm_post_import`,
`main._reconstruir_en_fila`, hilos `mtm-backfill-*`) y el pedido contesta sin
esperarla. En una prueba, ese hilo sigue vivo cuando ya empezó la SIGUIENTE —
medido el 02/11/2026 en el Postgres de la Mac: `mtm-backfill-1` seguía vivo 15
pruebas después y cruzaba de un archivo de pruebas al otro.

En la Mac no se notaba porque la base contesta en 0,1 ms y el hilo casi no la
toca para cuando la prueba siguiente limpia. Contra Supabase (5 ms por consulta,
corrida de Railway del 02/11) se pisaron:
  · `test_reimport_dedup_crudo` y `test_tenencia_override_all`: la limpieza del
    `setUp` (borrar las tablas) chocó con el hilo de la prueba anterior, el error
    lo tragó un `except: pass`, la transacción quedó abortada y el INSERT del
    usuario falló;
  · `test_plantillas_importador`: el hilo de fondo tomó el turno de la cuenta
    mientras la prueba contaba cuántas veces lo tomaba el guardado (2 en vez de 1).
La app estaba bien: el que tomaba el turno era la reconstrucción, que lo tiene
que tomar.
"""
import sys
import threading
import time

PREFIJO = "mtm-"
ESPERA_MAXIMA_S = 120


def vivos():
    return [t for t in threading.enumerate() if t.name.startswith(PREFIJO)]


def esperar(espera_maxima_s: float = ESPERA_MAXIMA_S) -> None:
    """Vuelve cuando no queda ningún hilo de reconstrucción vivo. Si alguno sigue
    después de `espera_maxima_s`, corta con su nombre: un hilo colgado tiene que
    verse, no pasar a pisar la prueba siguiente."""
    tope = time.monotonic() + espera_maxima_s
    # En ronda: una reconstrucción que termina puede haber lanzado otra.
    while vivos() and time.monotonic() < tope:
        for t in vivos():
            t.join(max(0.0, tope - time.monotonic()))
    quedan = vivos()
    if quedan:
        raise RuntimeError(
            f"{len(quedan)} reconstrucción(es) de fondo siguen vivas después de "
            f"{espera_maxima_s:.0f} s: {[t.name for t in quedan]}")
    # La fila (`_reconstruir_en_fila`) baja su bandera bajo el lock justo antes de
    # que el hilo termine; si el hilo ya no está, la bandera tiene que estar abajo.
    m = sys.modules.get("main")
    if m is not None and getattr(m, "_MTM_FILA_ACTIVA", False):
        raise RuntimeError("la fila de reconstrucción quedó marcada activa sin hilo")
