"""Errores plantados en cada borde de cada regla del CEDEAR con el contado con
liqui: ¿alguna prueba lo ve? Cada uno sobre una COPIA del backend.

Uso: python3 mutantes_ccl.py <backend del repo> <carpeta de trabajo>
"""
import os
import shutil
import subprocess
import sys

BACKEND, TRABAJO = sys.argv[1], sys.argv[2]

PRUEBAS = [
    "tests/test_tecnico.py", "-k",
    "contado_con_liqui or no_es_cedear_sigue or serie_vieja_no_corre or bac_el_grafico or noche_guarda",
]
OTRAS = [
    ["tests/test_vela_de_hoy.py", "-k", "contado_con_liqui"],
    ["tests/test_velas_horarias.py", "-k", "contado_con_liqui"],
    ["tests/test_alertas_tecnicas.py", "-k", "estimado or contado_con_liqui"],
    ["tests/test_resumen_tecnico.py", "-k", "estimado or contado_con_liqui"],
]

# (nombre, archivo, texto, reemplazo)
MUTANTES = [
    ("serie: un CEDEAR siempre con el MEP", "tecnico.py",
     'dolar = _dolar_de_los_cedears(conn, afuera[0]["date"])', 'dolar = "mep"'),
    ("sin red: siempre el CCL aunque no haya historia", "tecnico.py",
     'return "ccl" if primero and primero <= desde else "mep"', 'return "ccl"'),
    ("historia a medias alcanza (mitad y mitad)", "tecnico.py",
     'return "ccl" if primero and primero <= desde else "mep"', 'return "ccl" if primero else "mep"'),
    ("vela de hoy: lo guardado de hoy con el MEP", "tecnico.py",
     '"dolares": serie_diaria(conn, cruda["date"], s["convertida"]) if s["convertida"] else [],',
     '"dolares": serie_diaria(conn, cruda["date"]) if s["convertida"] else [],'),
    ("vela de hoy: el dólar de ahora, el MEP", "tecnico.py",
     'dolar_hoy = _dolar_de_hoy(prep["convertida"])', 'dolar_hoy = _dolar_de_hoy("mep")'),
    ("1 y 4 horas: la clave sin el dólar", "velas_horarias.py",
     "clave = (ticker, cada, por, escala, dolar)", "clave = (ticker, cada, por, escala)"),
    ("1 y 4 horas: con el MEP", "velas_horarias.py",
     "velas = tecnico._convertir(conn, velas, por, escala, dolar)",
     "velas = tecnico._convertir(conn, velas, por, escala)"),
    ("BAC: siempre el CCL de ahora (lo guardado no se mira)", "main.py",
     "out = _fx.ccl_de_las_fechas(conn, [f for f in claves if f and f < hoy], tecnico.MAX_DIAS_SIN_DOLAR)",
     "out = {}"),
    ("BAC: el cierre anterior con el CCL del último", "main.py",
     "_cuando[_csym] = (f_prev or _dia_antes(f_ult), f_ult)", "_cuando[_csym] = (f_ult, f_ult)"),
    ("BAC: el mini-gráfico con el CCL de ahora", "main.py",
     "_ccls = _ccl_de_las_fechas(_cdb, [_cierra(pt) for pt in points], uid)",
     "_ccls = {_cierra(pt): _ccl_del_dia(_cdb, None, uid) for pt in points}"),
    ("la noche no reescribe los últimos días", "fx.py",
     "if f not in ya or f >= revisar]", "if f not in ya]"),
    ("la noche reescribe toda la historia", "fx.py",
     "if f not in ya or f >= revisar]", "]"),
    ("la noche no baja el CCL", "main.py",
     "        try:\n            _actualizar_ccl()\n        except Exception as e:\n            _velas_log.warning",
     "        try:\n            pass\n        except Exception as e:\n            _velas_log.warning"),
    ("la nota no sigue al dólar", "tecnico.py",
     'return NOTAS_MEP.get(nota, nota) if convertida == "mep" else nota', "return nota"),
    ("el mail no sabe el dólar", "alerts_engine.py",
     'velas.dolar = s.get("convertida")', "velas.dolar = None"),
    ("Mervall-E: la clave sin «·ccl»", "ai/resumen_tecnico.py",
     '        serie += "·ccl"', "        pass"),
    ("Mervall-E: los hechos dicen CCL siempre", "ai/resumen_tecnico_hechos.py",
     'lejos de su precio en la Bolsa" if r.get("convertida") == "mep" else',
     'lejos de su precio en la Bolsa" if False else'),
    ("el CCL se lee de otro índice", "fx.py",
     '(INDICE_CCL, INDICE_CCL, desde, desde)', '("CER", "CER", desde, desde)'),
    ("el CCL guardado es la punta de venta", "fx.py",
     "        v = punta_media(compra, venta)\n        if v:\n            valores[fecha] = v",
     "        v = punta_media(None, venta)\n        if v:\n            valores[fecha] = v"),
]


def correr(back):
    fallas = []
    for args in [PRUEBAS] + OTRAS:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider", *args],
                           cwd=back, capture_output=True, text=True)
        if r.returncode != 0:
            fallas += [l.split("::")[-1][:70] for l in r.stdout.splitlines() if l.startswith("FAILED")] or [
                args[0] + ": " + r.stdout.strip().splitlines()[-1][:80]]
    return fallas


def main():
    vistos = 0
    copia = os.path.join(TRABAJO, "backend")
    for nombre, archivo, viejo, nuevo in MUTANTES:
        if os.path.exists(copia):
            shutil.rmtree(copia)
        shutil.copytree(BACKEND, copia, ignore=shutil.ignore_patterns("__pycache__", "*.db", "*.db-*"))
        ruta = os.path.join(copia, archivo)
        s = open(ruta).read()
        assert s.count(viejo) == 1, (nombre, s.count(viejo))
        open(ruta, "w").write(s.replace(viejo, nuevo))
        fallas = correr(copia)
        vistos += bool(fallas)
        print(f"{'VISTO ' if fallas else 'NO VISTO'}  {nombre}: {', '.join(fallas[:3]) if fallas else '—'}", flush=True)
    print(f"\n{vistos} de {len(MUTANTES)} errores plantados los ve alguna prueba")


if __name__ == "__main__":
    main()
