"""Errores plantados (mutantes) en una copia de backend/: ¿alguna prueba se pone roja? (06/11/2026)

Cada error es un cambio chico y verosímil en el arreglo del ".BA" clavado (velas_diarias.py) o del
atraso de la serie en pesos (tecnico.py). Si las pruebas siguen verdes con él, nada cuida esa regla.
La auditoría del 06/11 encontró 14 de 29 sin ver; con las pruebas nuevas, los 13 de acá se ven.

Corre con:  python3 audit/_scripts/mutantes_pesos_ba.py <raíz del repo> <carpeta nueva y vacía>
"""
import os, shutil, subprocess, sys
W, R = sys.argv[1], sys.argv[2]
MUT = {
    "corrige rachas viejas": ("velas_diarias.py", "        if not (hasta == dias_de[-1] or corregida):\n            continue\n", ""),
    "sin la cola": ("velas_diarias.py", "    if cola and misma_escala(", "    if False and misma_escala("),
    "data912 caído: no guarda": ("velas_diarias.py", "        n, _ = _guardar(conn, t, velas, completa=False)\n        _anotar(conn, t, completa=entera and t in otra_escala, ok=True, filas=n)\n        res[\"filas\"] += n\n        res[\"incrementales\"] += 1\n", "        return\n"),
    "sin proteger": ("velas_diarias.py", "            proteger = proteger or corregida\n", ""),
    "relleno con tope de 7 días": ("velas_diarias.py", "                c = de_byma(d, semana=False)[3]\n", "                if de_byma(d) is None:\n                    continue\n                c = de_byma(d)[3]\n"),
    "sin control de escala": ("velas_diarias.py", "        if not misma_escala(antes_de(desde, cierre)):", "        if False:"),
    "corregida por distinto": ("velas_diarias.py", "        return (len(guardados) > 1 and bool(ambos)", "        return (True and bool(ambos)"),
    "lo nuevo con otra escala de Yahoo": ("velas_diarias.py", "        elif (byma is not None or clavada or not misma_escala) and ultimo is not None:", "        elif clavada and ultimo is not None:"),
    "atraso con lo dibujado": ("tecnico.py", "_atrasada(velas_diarias.ultima_fecha(conn, simbolo_byma(a)) or byma[-1][\"date\"],", "_atrasada(byma[-1][\"date\"],"),
    "racha de 2": ("velas_diarias.py", "RACHA_CLAVADA = 5", "RACHA_CLAVADA = 2"),
    "escala al 45 %": ("velas_diarias.py", "TOLERANCIA_BYMA = 0.05", "TOLERANCIA_BYMA = 0.45"),
    "pide siempre a cedears": ("velas_diarias.py", "    tipos = (\"stocks\", \"cedears\") if papel in AR_STOCK_TICKERS else (\"cedears\", \"stocks\")", "    tipos = (\"cedears\",)"),
    "pisa el primer día operado": ("velas_diarias.py", "            if out[d][4] and out[d][3] == nueva[3]:\n                continue", "            if False:\n                continue"),
}
for nombre, (archivo, viejo, nuevo) in MUT.items():
    copia = os.path.join(R, "b")
    shutil.rmtree(copia, ignore_errors=True)
    shutil.copytree(os.path.join(W, "backend"), copia, ignore=shutil.ignore_patterns("__pycache__", "*.db"))
    p = os.path.join(copia, archivo)
    s = open(p, encoding="utf-8").read()
    if s.count(viejo) != 1:
        print(f"{nombre}: NO SE PUDO PLANTAR"); continue
    open(p, "w", encoding="utf-8").write(s.replace(viejo, nuevo))
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/test_velas_diarias.py", "tests/test_tecnico.py", "-q", "-x",
                        "-p", "no:warnings", "-p", "no:cacheprovider"], cwd=copia, capture_output=True, text=True)
    ult = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l or "error" in l.lower()][-1:]
    rojo = [l.split("::")[-1].split(" ")[0] for l in r.stdout.splitlines() if l.startswith("FAILED")]
    print(f"{nombre}: {'ROJO ' + str(rojo[:2]) if r.returncode else 'VERDE (nadie lo ve)'} {ult}")
