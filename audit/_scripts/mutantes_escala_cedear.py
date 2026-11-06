"""Errores plantados (mutantes) en una copia de backend/: ¿alguna prueba se pone roja? (06/11/2026)

Cada error es un cambio chico y verosímil en el estimado del CEDEAR en pesos (tecnico.serie: la
acción de afuera × el MEP ÷ cuántas veces entra el CEDEAR en ella) o en sus dos copias de la cuenta
(la vela de hoy y las de 1 y 4 horas). Si las pruebas siguen verdes con él, nada cuida esa regla.

Corre con:  python3 audit/_scripts/mutantes_escala_cedear.py <raíz del repo> <carpeta nueva y vacía>
"""
import os, shutil, subprocess, sys
W, R = sys.argv[1], sys.argv[2]
MUT = {
    "la cuenta no divide": ("tecnico.py", "    return y / escala if escala else y\n", "    return y\n"),
    "la vela de hoy sin escala": ("tecnico.py", 'a_la_moneda(x, tc, prep["por"], prep.get("escala"))', 'a_la_moneda(x, tc, prep["por"])'),
    "la vela de hoy no la recibe": ("tecnico.py", '        "escala": s.get("escala"),\n        # La serie entera', '        # La serie entera'),
    "las horas sin escala": ("velas_horarias.py", "velas = tecnico._convertir(conn, velas, por, escala)", "velas = tecnico._convertir(conn, velas, por)"),
    "las horas no la piden": ("velas_horarias.py", '"convertida": s["convertida"], "escala": s.get("escala")}', '"convertida": s["convertida"]}'),
    "sin la tolerancia": ("tecnico.py", "    if tabla and abs(medida / tabla - 1) > TOLERANCIA_ESCALA:\n        return None\n", ""),
    "sólo la tabla": ("tecnico.py", "    if not comunes:\n        return tabla\n", "    if True:\n        return tabla\n"),
    "el último día, no la mediana": ("tecnico.py", "    medida = cocientes[k] if len(cocientes) % 2 else (cocientes[k - 1] + cocientes[k]) / 2\n",
                                     "    medida = v[\"close\"] / pesos[v[\"date\"]]\n"),
    "todo se divide (también lo que no es CEDEAR)": ("tecnico.py", "        if not (guardada or es_cedear(a) or ratio_de(a)):", "        if False:"),
    "CEDEAR sólo si está en la tabla": ("tecnico.py", "        if not (guardada or es_cedear(a) or ratio_de(a)):", "        if not (guardada or ratio_de(a)):"),
    "sin escala, la acción entera": ("tecnico.py", "        if not escala:\n            return {\"velas\": []}\n",
                                     "        if not escala:\n            escala = 1\n"),
    "la serie vieja no se guarda": ("tecnico.py", "            byma, guardada = [], byma\n", "            byma = []\n"),
    "BAC con su número aparte": ("main.py", 'CEDEAR_USD_RATIOS = {b: _RATIOS_CEDEAR[b] for b in ("BAC",)}', 'CEDEAR_USD_RATIOS = {"BAC": 5}'),
    "la tabla del servidor se separa": ("ratios_cedear.py", '"AAPL": 20,', '"AAPL": 21,'),
    "SI se lee como SID": ("ratios_cedear.py", '    r = CEDEAR_RATIOS.get(simbolo_byma(a)[:-3], CEDEAR_RATIOS.get(a))',
                           '    a = {"SI": "SID"}.get(a, a)\n    r = CEDEAR_RATIOS.get(simbolo_byma(a)[:-3], CEDEAR_RATIOS.get(a))'),
}
PRUEBAS = ["tests/test_tecnico.py", "tests/test_vela_de_hoy.py", "tests/test_velas_horarias.py", "tests/test_ratios_cedear.py"]
# La prueba de la tabla lee la de la pantalla en ../frontend: va al lado de la copia.
os.makedirs(os.path.join(R, "frontend", "src", "utils"), exist_ok=True)
shutil.copy(os.path.join(W, "frontend", "src", "utils", "cedearRatio.js"), os.path.join(R, "frontend", "src", "utils"))
for nombre, (archivo, viejo, nuevo) in MUT.items():
    copia = os.path.join(R, "backend")
    shutil.rmtree(copia, ignore_errors=True)
    shutil.copytree(os.path.join(W, "backend"), copia, ignore=shutil.ignore_patterns("__pycache__", "*.db"))
    p = os.path.join(copia, archivo)
    s = open(p, encoding="utf-8").read()
    if s.count(viejo) != 1:
        print(f"{nombre}: NO SE PUDO PLANTAR"); continue
    open(p, "w", encoding="utf-8").write(s.replace(viejo, nuevo))
    r = subprocess.run([sys.executable, "-m", "pytest", *PRUEBAS, "-q",
                        "-p", "no:warnings", "-p", "no:cacheprovider"], cwd=copia, capture_output=True, text=True)
    ult = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l or "error" in l.lower()][-1:]
    rojo = [l.split("::")[-1].split(" ")[0] for l in r.stdout.splitlines() if l.startswith("FAILED")]
    print(f"{nombre}: {'ROJO ' + str(rojo[:3]) if r.returncode else 'VERDE (nadie lo ve)'} {ult}")
