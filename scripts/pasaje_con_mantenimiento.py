"""Herramienta del día del pasaje: habla con la app CERRADA (modo mantenimiento).

Con el mantenimiento prendido, la app le contesta 503 a todo el que no traiga la llave
en la cabecera `x-rendi-bypass`. Este script trae la llave desde un archivo de esta
Mac (nunca por el chat ni por la línea de comandos) y pide la contraseña de la cuenta
SIN mostrarla. La llave y la contraseña no se imprimen, no se pasan como argumento (no
quedan en el historial de la Terminal) y no se escriben en ningún archivo, salvo la
llave en su propio archivo con permiso 600.

La dirección de la app NO está escrita acá: va con `--url` o con la variable `RENDI_URL`.
Tiene que ser https (salvo `localhost`, para las pruebas): la llave viaja en el pedido.

Uso (lo corre Nico en su Terminal, o la central en la pestaña Terminal con Nico
tipeando la contraseña):

  python3 scripts/pasaje_con_mantenimiento.py llave           guarda la llave que ya está en Railway
  python3 scripts/pasaje_con_mantenimiento.py llave --nueva   inventa una llave y la copia al portapapeles
  python3 scripts/pasaje_con_mantenimiento.py respaldo --url https://…       dispara el respaldo (cuenta de ADMIN)
  python3 scripts/pasaje_con_mantenimiento.py pantallas antes --url https://…    guarda lo que muestra la app hoy
  python3 scripts/pasaje_con_mantenimiento.py pantallas despues --url https://…  lo mismo, ya sobre Postgres
  python3 scripts/pasaje_con_mantenimiento.py comparar        compara «antes» con «despues», cuenta por cuenta

Sólo usa la biblioteca estándar de Python. No imprime nunca la llave, la contraseña, el
token de sesión ni montos de nadie: sólo estados y DÓNDE difieren las cosas.
"""
import getpass
import glob
import json
import os
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

PANTALLAS = ["/api/operations", "/api/monthly", "/api/snapshots?days=3650"]

# Cómo se pide lo que se escribe. Son nombres del módulo (y no llamadas sueltas) para que
# las pruebas puedan reemplazar SÓLO el teclado, y todo lo demás corra de verdad.
pedir_mail = input
pedir_secreto = getpass.getpass


def ruta_llave():
    return os.path.join(os.path.expanduser("~"), ".rendi-mantenimiento-llave")


def carpeta_pantallas():
    """Fuera del repo; guarda datos de personas."""
    return os.path.join(os.path.expanduser("~"), "rendi-pasaje")


def escribir_privado(ruta, texto):
    os.makedirs(os.path.dirname(ruta), mode=0o700, exist_ok=True)
    fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(texto)      # sin salto de línea: la llave se compara tal cual
    os.chmod(ruta, 0o600)


def leer_llave():
    ruta = ruta_llave()
    try:
        modo = os.stat(ruta).st_mode & 0o777
        llave = open(ruta).read().strip()
    except OSError:
        sys.exit(f"✋ No encuentro la llave en {ruta}. Corré primero:  python3 {sys.argv[0]} llave")
    if modo & 0o077:
        sys.exit(f"✋ El archivo {ruta} lo puede leer otra gente de esta Mac (permiso {modo:o}). "
                 f"Corré `chmod 600 {ruta}` y repetí. No se hizo nada.")
    if not llave:
        sys.exit(f"✋ El archivo {ruta} está vacío. Corré de nuevo:  python3 {sys.argv[0]} llave")
    return llave


def base_url(url):
    """La dirección de la app, validada. La llave viaja en cada pedido: sólo por https."""
    url = (url or os.environ.get("RENDI_URL") or "").strip().rstrip("/")
    if not url:
        sys.exit("✋ Falta la dirección de la app: usá --url https://… (o la variable RENDI_URL). "
                 "La confirma Nico mirando Railway → trading → Settings → Domains. No se hizo nada.")
    p = urlparse(url)
    local = p.hostname in ("localhost", "127.0.0.1", "::1")
    if p.scheme != "https" and not (p.scheme == "http" and local):
        sys.exit("✋ La dirección tiene que empezar con https:// (la llave viaja en cada pedido). "
                 "No se hizo nada.")
    return url


def pedir(url, metodo, ruta, llave, cuerpo=None, token=None, timeout=60):
    """(estado, json|texto). No tira por un 4xx/5xx: devuelve el estado."""
    datos = None if cuerpo is None else json.dumps(cuerpo).encode()
    req = urllib.request.Request(url + ruta, data=datos, method=metodo)
    req.add_header("x-rendi-bypass", llave)
    req.add_header("User-Agent", "rendi-pasaje/1")   # sin esto Cloudflare suele rechazar a urllib
    if datos is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            estado, crudo = r.status, r.read()
    except urllib.error.HTTPError as e:
        estado, crudo = e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        sys.exit(f"❌ No pude hablar con la app ({type(e).__name__}). No se hizo nada.")
    try:
        return estado, json.loads(crudo)
    except ValueError:
        return estado, crudo[:200].decode("utf-8", "replace")


def entrar(url, llave):
    email = pedir_mail("Mail de la cuenta: ").strip()
    clave = pedir_secreto("Contraseña (no se ve mientras escribís): ")
    estado, cuerpo = pedir(url, "POST", "/api/auth/login", llave, {"email": email, "password": clave})
    if estado == 503:
        sys.exit("✋ 503: la app no te dejó pasar. O la llave de este archivo no es la de Railway, "
                 "o en Railway falta RENDI_MANTENIMIENTO_TOKEN. No se hizo nada.")
    if estado != 200 or not isinstance(cuerpo, dict) or not cuerpo.get("token"):
        sys.exit(f"✋ La app contestó {estado} al entrar (credenciales o mail sin confirmar). No se hizo nada.")
    return cuerpo["token"], bool(cuerpo.get("is_admin")), email


def cmd_llave(nueva):
    if nueva:
        llave = secrets.token_urlsafe(32)
        escribir_privado(ruta_llave(), llave)
        subprocess.run(["pbcopy"], input=llave.encode(), check=True)
        print("✅ Llave nueva inventada, guardada y COPIADA al portapapeles (no se muestra).")
        print("   Pegala en Railway → trading → Variables → RENDI_MANTENIMIENTO_TOKEN.")
        return
    llave = pedir_secreto("Pegá la llave que está en Railway (no se ve): ").strip()
    if not llave:
        sys.exit("✋ Vacía. No se guardó nada.")
    escribir_privado(ruta_llave(), llave)
    print(f"✅ Guardada en {ruta_llave()} (sólo este usuario de la Mac puede leerla).")


def cmd_respaldo(url):
    llave = leer_llave()
    token, es_admin, _ = entrar(url, llave)
    if not es_admin:
        sys.exit("✋ Esa cuenta no es de administrador: el respaldo no se puede disparar. No se hizo nada.")
    print("Disparando el respaldo… (puede tardar un par de minutos; no cierres esto)")
    estado, r = pedir(url, "POST", "/api/admin/backup-trigger", llave, token=token, timeout=900)
    if estado != 200 or not isinstance(r, dict):
        sys.exit(f"❌ La app contestó {estado} al respaldo: {str(r)[:200]}")
    s = r.get("stats") or {}
    filas = s.get("filas") or {}
    print()
    print(f"  motor:           {s.get('motor')}      (tiene que decir sqlite: la app todavía no pasó a Postgres)")
    print(f"  tablas:          {s.get('tablas')}")
    print(f"  usuarios:        {filas.get('users')}")
    print(f"  operaciones:     {filas.get('operations')}")
    print(f"  tamaño (bytes):  {s.get('size_bytes')}")
    print(f"  subido afuera:   {'SÍ' if s.get('remote_uploaded') else 'NO'}   {s.get('remote_key') or s.get('remote_skip_reason') or ''}")
    print(f"  errores:         {s.get('errors') or 'ninguno'}")
    print()
    if s.get("motor") != "sqlite":
        sys.exit("🛑 El respaldo dice que es de Postgres: la app ya tiene DATABASE_URL. PARÁ y avisá.")
    if r.get("ok") and s.get("remote_uploaded"):
        print("✅ Respaldo hecho y subido a Cloudflare R2. Anotá el tamaño y la clave de arriba.")
    else:
        sys.exit("🛑 El respaldo NO está bien (errores o no subió a R2). PARÁ y avisá; no sigas con el paso 4.")


def cmd_pantallas(url, cuando):
    llave = leer_llave()
    token, _, email = entrar(url, llave)
    salida = {"cuenta": email, "pantallas": {}}
    for ruta in PANTALLAS:
        estado, cuerpo = pedir(url, "GET", ruta, llave, token=token, timeout=120)
        salida["pantallas"][ruta] = {"estado": estado, "json": cuerpo}
        print(f"  {ruta}: estado {estado}")
    chico = "".join(c for c in email.split("@")[0].lower() if c.isalnum())
    destino = os.path.join(carpeta_pantallas(), f"pantallas-{cuando}-{chico}.json")
    escribir_privado(destino, json.dumps(salida, ensure_ascii=False))
    print(f"✅ Guardado en {destino} (con datos de la cuenta: no lo subas a ningún lado).")


def _igual(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return a == b or abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b


def _dif_campos(fa, fb):
    return sorted(k for k in set(fa) | set(fb) if not _igual(fa.get(k), fb.get(k)))


def _comparar_cuenta(a, b):
    """Imprime el resultado de una cuenta y devuelve cuántas pantallas difieren."""
    hallazgos = 0
    for ruta in PANTALLAS:
        pa, pb = a["pantallas"][ruta], b["pantallas"][ruta]
        if pa["estado"] != 200 or pb["estado"] != 200:
            print(f"  ❌ {ruta}: estados {pa['estado']} vs {pb['estado']}")
            hallazgos += 1
            continue
        ja, jb = pa["json"], pb["json"]
        if ruta.startswith("/api/operations"):
            # Mismas filas, en cualquier orden (los empates de fecha salen en otro orden en Postgres).
            ca = sorted(json.dumps(f, sort_keys=True) for f in ja)
            cb = sorted(json.dumps(f, sort_keys=True) for f in jb)
            mal = ca != cb
            print(f"  {'❌' if mal else '✅'} {ruta}: {len(ja)} vs {len(jb)} filas"
                  + (f", {len(set(ca) ^ set(cb))} filas distintas" if mal else ", todas iguales"))
            hallazgos += mal
            continue
        clave = (lambda f: (f.get("year"), f.get("month"), f.get("broker"))) if "monthly" in ruta \
            else (lambda f: f.get("date"))
        da, db = {clave(f): f for f in ja}, {clave(f): f for f in jb}
        faltan = len(set(da) ^ set(db))
        campos = {}
        for k in set(da) & set(db):
            fa, fb = dict(da[k]), dict(db[k])
            fa.pop("id", None), fb.pop("id", None)     # la pantalla mensual CREA filas nuevas: su id no cuenta
            for c in _dif_campos(fa, fb):
                campos[c] = campos.get(c, 0) + 1
        bien = not faltan and not campos
        print(f"  {'✅' if bien else '❌'} {ruta}: {len(da)} vs {len(db)} filas; "
              f"filas que sólo están de un lado: {faltan}; campos distintos: {campos or 'ninguno'}")
        hallazgos += not bien
    return hallazgos


def cmd_comparar():
    antes = sorted(glob.glob(os.path.join(carpeta_pantallas(), "pantallas-antes-*.json")))
    if not antes:
        sys.exit(f"✋ No hay nada guardado en {carpeta_pantallas()}: falta correr «pantallas antes».")
    hallazgos = 0
    for fa in antes:
        fb = fa.replace("pantallas-antes-", "pantallas-despues-")
        print(os.path.basename(fa).replace("pantallas-antes-", "cuenta ").replace(".json", ""))
        if not os.path.isfile(fb):
            print("  ❌ falta el «despues» de esta cuenta")
            hallazgos += 1
            continue
        hallazgos += _comparar_cuenta(json.load(open(fa)), json.load(open(fb)))
    print()
    print("✅ SIN DIFERENCIAS: seguí." if not hallazgos else
          f"🛑 {hallazgos} pantalla(s) con diferencias. NO abras: pasale a la central esta salida (no tiene montos).")
    sys.exit(1 if hallazgos else 0)


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    url = None
    if "--url" in a:
        i = a.index("--url")
        if i + 1 >= len(a):
            sys.exit("✋ --url necesita la dirección a continuación. No se hizo nada.")
        url = a[i + 1]
        del a[i:i + 2]
    if a[:1] == ["llave"]:
        cmd_llave("--nueva" in a)
    elif a[:1] == ["respaldo"]:
        cmd_respaldo(base_url(url))
    elif a[:1] == ["pantallas"] and a[1:2] in (["antes"], ["despues"]):
        cmd_pantallas(base_url(url), a[1])
    elif a[:1] == ["comparar"]:
        cmd_comparar()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
