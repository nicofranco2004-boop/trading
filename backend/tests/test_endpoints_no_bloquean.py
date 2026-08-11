"""Ningún endpoint puede correr trabajo bloqueante sobre el event loop.

REPORTE REAL (2026-08-10): un usuario subió su archivo, tocó "Generar vista
previa" y se le quedó tildado hasta que apareció el error de gateway.

La causa no era su archivo: el preview procesa 2000 filas en 0,05s y convierte
un Excel de 5000 filas en 0,48s. Era la FIRMA del endpoint. `import_preview`
estaba declarado `async def` y adentro llamaba a `run_preview`, que es
sincrónico y abre una transacción de escritura en SQLite.

En FastAPI un handler `async def` corre SOBRE el event loop; uno `def` va al
threadpool. Medido con un uvicorn real, con un handler que tarda 3s:

    def        → otro request tarda 0,01s   (la app sigue viva)
    async def  → otro request tarda 2,51s   (la app entera congelada)

Y como `busy_timeout` es 15s, si el lock de escritura lo tiene otra cosa, cada
INSERT del preview espera hasta 15 segundos ahí parado — congelando a TODOS los
usuarios, no solo al que importa. Encima el frontend reintenta el preview 4
veces, y el 502 lo devuelve el proxy mientras el request original sigue vivo:
un click podía terminar en 4 previews concurrentes apilados.

Este test es una guarda estructural: si alguien vuelve a poner `async def` en un
endpoint que toca la base, falla acá y no en producción.
"""
import inspect
import re
import threading
import time
import unittest

import main


def _endpoints_async_con_trabajo_bloqueante():
    """Recorre las rutas registradas y devuelve las que son corrutinas Y tocan
    la base o el pipeline de imports."""
    sospechosos = []
    for route in main.app.routes:
        fn = getattr(route, "endpoint", None)
        if fn is None or not inspect.iscoroutinefunction(fn):
            continue
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError):
            continue
        marcas = [m for m in ("get_db()", "conn.execute", "_import_pipeline",
                              "run_preview", "run_confirm") if m in src]
        if marcas:
            sospechosos.append((fn.__name__, marcas))
    return sospechosos


class SinTrabajoBloqueanteEnElEventLoop(unittest.TestCase):
    def test_ningun_endpoint_async_toca_la_base(self):
        malos = _endpoints_async_con_trabajo_bloqueante()
        self.assertEqual(
            malos, [],
            "Estos endpoints son `async def` y hacen trabajo bloqueante, así que "
            "congelan la app entera mientras corren. Sacales el `async` (FastAPI "
            "los manda al threadpool) o mové el trabajo con "
            f"run_in_threadpool:\n  " + "\n  ".join(f"{n}: {', '.join(m)}" for n, m in malos)
        )

    def test_los_endpoints_del_importador_son_sincronicos(self):
        """El caso concreto que se reportó. Explícito para que quede el nombre."""
        for nombre in ("import_preview", "import_inspect",
                       "import_classify_tenencia", "import_tenencia_preview"):
            fn = getattr(main, nombre)
            self.assertFalse(
                inspect.iscoroutinefunction(fn),
                f"{nombre} volvió a ser `async def` — congela la app mientras importa.",
            )

    def test_los_webhooks_de_cobro_son_sincronicos(self):
        # Un webhook lento no puede dejar sin app al resto: escribe en la misma
        # base y compite por el mismo lock.
        for nombre in ("rebill_webhook", "billing_webhook"):
            fn = getattr(main, nombre)
            self.assertFalse(inspect.iscoroutinefunction(fn), f"{nombre} es async def")


class ElLockNoSeTomaAntesDeParsear(unittest.TestCase):
    def test_cleanup_va_despues_del_parseo(self):
        """`cleanup_stale_previews` es un DELETE, o sea la primera escritura de la
        transacción — y en SQLite la primera escritura es la que toma el lock. Si
        vuelve al principio de run_preview, el lock queda tomado durante todo el
        parseo del archivo."""
        from importing import pipeline
        src = inspect.getsource(pipeline.run_preview)
        pos_cleanup = src.index("cleanup_stale_previews(conn)")
        pos_parse = src.index("parse_result = parser.parse(")
        self.assertGreater(
            pos_cleanup, pos_parse,
            "cleanup_stale_previews volvió a estar ANTES del parseo: eso toma el "
            "lock de escritura y lo retiene mientras se parsea el archivo.",
        )


class MedicionDelMecanismo(unittest.TestCase):
    """No mockea nada: levanta uvicorn de verdad y mide. Es la evidencia de por
    qué la regla de arriba existe — si algún día FastAPI cambiara el criterio,
    este test lo diría."""

    def test_async_def_bloqueante_congela_la_app_y_def_no(self):
        import socket
        from fastapi import FastAPI
        import uvicorn
        import httpx

        app = FastAPI()

        @app.get("/lento_async")
        async def lento_async():
            time.sleep(1.5)
            return {"ok": True}

        @app.get("/lento_sync")
        def lento_sync():
            time.sleep(1.5)
            return {"ok": True}

        @app.get("/ping")
        def ping():
            return {"ok": True}

        s = socket.socket(); s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]; s.close()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                               log_level="error"))
        threading.Thread(target=server.run, daemon=True).start()
        try:
            for _ in range(100):
                try:
                    httpx.get(f"http://127.0.0.1:{port}/ping", timeout=1)
                    break
                except Exception:
                    time.sleep(0.1)
            else:
                self.skipTest("no levantó el server de prueba")

            def espera_de_otro_usuario(ruta):
                t = threading.Thread(
                    target=lambda: httpx.get(f"http://127.0.0.1:{port}{ruta}", timeout=30))
                t.start()
                time.sleep(0.4)                      # el lento ya está adentro
                t0 = time.perf_counter()
                httpx.get(f"http://127.0.0.1:{port}/ping", timeout=30)
                dt = time.perf_counter() - t0
                t.join()
                return dt

            con_sync = espera_de_otro_usuario("/lento_sync")
            con_async = espera_de_otro_usuario("/lento_async")

            self.assertLess(con_sync, 0.5,
                            f"un handler `def` no debería frenar a nadie (tardó {con_sync:.2f}s)")
            self.assertGreater(con_async, 0.5,
                               f"un `async def` bloqueante SÍ frena a todos; medido {con_async:.2f}s")
        finally:
            server.should_exit = True


if __name__ == "__main__":
    unittest.main()
