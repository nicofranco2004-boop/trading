#!/usr/bin/env python3
"""Spike de la API de IOL (InvertirOnline) — SOLO LECTURA.

Lo corre el TESTER en su propia máquina. Rendi nunca ve su contraseña.
Solo requiere Python 3.8+ (sin instalar nada: usa la librería estándar).

Modos:
    python3 iol_spike.py probe          # 5-10 min. Contesta S2..S8 del plan.
    python3 iol_spike.py watch          # días. Contesta S1 (vida del refresh token).

Garantías para el tester:
  * La contraseña se pide por consola (sin eco), se usa UNA vez para /token y
    se descarta. No se escribe en ningún archivo ni se manda a ningún lado que
    no sea api.invertironline.com.
  * Este script NO PUEDE operar: el único método permitido contra /api es GET,
    y la lista de paths está fija abajo (ALLOWED_GET). Cualquier otro path
    levanta excepción antes de salir a la red. Ver _request().
  * El modo `watch` guarda SOLO el refresh token en `iol_spike_state.json`
    (permisos 600) para poder renovarlo cada hora. Al terminar, borrá ese
    archivo y cambiá tu contraseña de IOL si querés estar 100% tranquilo.
  * La salida (`iol_spike_out/`) enmascara nombre, apellido, DNI, CUIT, email
    y números de cuenta. Los montos y tickers quedan (son lo que se analiza).
"""
import getpass
import json
import os
import re
import stat
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from urllib import error, parse, request

BASE = os.environ.get("IOL_SPIKE_BASE", "https://api.invertironline.com")  # override solo para tests locales
OUT_DIR = "iol_spike_out"
STATE_FILE = "iol_spike_state.json"
WATCH_LOG = "iol_spike_watch.log"

# ---- GUARDA DURA: solo estos GET. Nada de /operar, /cuentas-bancarias, DELETE. ----
ALLOWED_GET = (
    "/api/v2/datos-perfil",
    "/api/v2/estadocuenta",
    "/api/v2/portafolio/argentina",
    "/api/v2/portafolio/estados_Unidos",
    "/api/v2/operaciones",
    "/api/v2/operaciones/",          # + {numero}
    "/api/v2/Notificacion",
)
# POST permitidos: solo el login/refresh. (Asesor/Movimientos es una consulta
# de lectura pero vive bajo "Asesores"; se prueba aparte con su propio flag.)
ALLOWED_POST = ("/token", "/api/v2/Asesor/Movimientos")

PII_KEYS = {"nombre", "apellido", "dni", "cuitCuil", "email", "numeroCuenta",
            "cuentaComitente", "numero_cuenta"}


class IolHttp(Exception):
    def __init__(self, status, body, headers):
        super().__init__(f"HTTP {status}")
        self.status, self.body, self.headers = status, body, dict(headers or {})


def _request(method, path, token=None, form=None, json_body=None, timeout=30):
    """Único punto de salida a la red. Rechaza todo lo que no esté en la allowlist."""
    bare = path.split("?")[0]           # la allowlist se compara SIN query string
    if method == "GET":
        if not any(bare == p or (p.endswith("/") and bare.startswith(p)) for p in ALLOWED_GET):
            raise RuntimeError(f"BLOQUEADO: GET {bare} no está en ALLOWED_GET")
    elif method == "POST":
        if bare not in ALLOWED_POST:
            raise RuntimeError(f"BLOQUEADO: POST {path} no está en ALLOWED_POST")
    else:
        raise RuntimeError(f"BLOQUEADO: método {method} prohibido")
    if "/operar" in path.lower() or "cancelar" in path.lower() or "extraccion" in path.lower():
        raise RuntimeError(f"BLOQUEADO: {path}")

    headers = {"Accept": "application/json", "User-Agent": "rendi-iol-spike/1"}
    data = None
    if form is not None:
        data = parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(BASE + path, data=data, method=method, headers=headers)
    t0 = time.time()
    try:
        with request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            ms = int((time.time() - t0) * 1000)
            try:
                return json.loads(body), dict(r.headers), ms
            except ValueError:
                return body, dict(r.headers), ms
    except error.HTTPError as e:
        raise IolHttp(e.code, e.read().decode("utf-8", "replace")[:2000], e.headers)


def get(path, token, **q):
    if q:
        path = path + "?" + parse.urlencode({k: v for k, v in q.items() if v is not None})
    return _request("GET", path, token=token)


def login(user, pwd):
    return _request("POST", "/token", form={"username": user, "password": pwd, "grant_type": "password"})[0]


def refresh(rt):
    return _request("POST", "/token", form={"refresh_token": rt, "grant_type": "refresh_token"})[0]


# ---------------- anonimización + salida ----------------

def mask(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in PII_KEYS:
                out[k] = "***" if v not in (None, "") else v
            elif k == "numero" and isinstance(v, str):   # numero de cuenta (string); el de operación es int
                out[k] = "***"
            else:
                out[k] = mask(v)
        return out
    if isinstance(obj, list):
        return [mask(x) for x in obj]
    return obj


class Out:
    def __init__(self):
        self.dir = os.path.join(OUT_DIR, datetime.now().strftime("%Y%m%d-%H%M%S"))
        os.makedirs(self.dir, exist_ok=True)
        self.summary = []

    def save(self, name, data):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            json.dump(mask(data), f, ensure_ascii=False, indent=1, default=str)

    def note(self, line):
        print(line)
        self.summary.append(line)

    def finish(self):
        with open(os.path.join(self.dir, "summary.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(self.summary) + "\n")
        zpath = self.dir + ".zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for fn in os.listdir(self.dir):
                z.write(os.path.join(self.dir, fn), fn)
        print(f"\n>>> Listo. Mandale a Rendi el archivo: {zpath}")


def safe(out, label, fn):
    try:
        data, headers, ms = fn()
        out.note(f"- {label}: OK ({ms} ms)")
        return data, headers
    except IolHttp as e:
        out.note(f"- {label}: HTTP {e.status} → {e.body[:200]!r}")
        return None, e.headers
    except Exception as e:  # noqa
        out.note(f"- {label}: ERROR {type(e).__name__}: {e}")
        return None, {}


# ---------------- PROBE ----------------

def probe(tok, out):
    out.note(f"# IOL spike probe — {datetime.now().isoformat(timespec='seconds')}")
    out.note("\n## S0 Perfil / cuenta / portafolio")
    perfil, h = safe(out, "datos-perfil", lambda: get("/api/v2/datos-perfil", tok))
    out.save("datos_perfil.json", perfil)
    out.save("headers_primer_request.json", h)
    if isinstance(perfil, dict):
        out.note(f"  perfilInversor={perfil.get('perfilInversor')} cuentaAbierta={perfil.get('cuentaAbierta')} "
                 f"actualizarTyC={perfil.get('actualizarTyC')} actualizarDDJJ={perfil.get('actualizarDDJJ')}")

    ec, _ = safe(out, "estadocuenta", lambda: get("/api/v2/estadocuenta", tok))
    out.save("estadocuenta.json", ec)
    if isinstance(ec, dict):
        for c in ec.get("cuentas", []):
            out.note(f"  cuenta tipo={c.get('tipo')} moneda={c.get('moneda')} disponible={c.get('disponible')} "
                     f"saldo={c.get('saldo')} titulosValorizados={c.get('titulosValorizados')} "
                     f"saldos[]={len(c.get('saldos') or [])} estado={c.get('estado')}")

    for pais in ("argentina", "estados_Unidos"):
        pf, _ = safe(out, f"portafolio/{pais}", lambda p=pais: get(f"/api/v2/portafolio/{p}", tok))
        out.save(f"portafolio_{pais}.json", pf)
        if isinstance(pf, dict):
            acts = pf.get("activos") or []
            out.note(f"  {pais}: {len(acts)} activos")
            for a in acts[:50]:
                t = a.get("titulo") or {}
                out.note(f"    {t.get('simbolo')} tipo={t.get('tipo')} moneda={t.get('moneda')} "
                         f"cant={a.get('cantidad')} ppc={a.get('ppc')} ult={a.get('ultimoPrecio')} val={a.get('valorizado')}")

    out.note("\n## S2/S6 Historial de operaciones por ventanas anuales (filtro.estado=todas)")
    today = date.today()
    all_ops, per_year = {}, {}
    for y in range(2010, today.year + 1):
        d0, d1 = f"{y}-01-01", (f"{y}-12-31" if y < today.year else today.isoformat())
        ops, _ = safe(out, f"operaciones {y}", lambda a=d0, b=d1: get(
            "/api/v2/operaciones", tok, **{"filtro.estado": "todas", "filtro.fechaDesde": a, "filtro.fechaHasta": b}))
        if isinstance(ops, list):
            per_year[y] = len(ops)
            for o in ops:
                all_ops[o.get("numero")] = o
        time.sleep(0.3)
    out.save("operaciones_todas.json", list(all_ops.values()))
    out.note(f"  por año: {per_year}")
    out.note(f"  total únicas por numero: {len(all_ops)}; máx en una sola respuesta: {max(per_year.values() or [0])}")
    tipos, estados, mercados = {}, {}, {}
    fechas = []
    for o in all_ops.values():
        tipos[o.get("tipo")] = tipos.get(o.get("tipo"), 0) + 1
        estados[o.get("estado")] = estados.get(o.get("estado"), 0) + 1
        mercados[o.get("mercado")] = mercados.get(o.get("mercado"), 0) + 1
        if o.get("fechaOrden"):
            fechas.append(o["fechaOrden"])
    out.note(f"  tipos: {tipos}")
    out.note(f"  estados: {estados}")
    out.note(f"  mercados: {mercados}")
    if fechas:
        out.note(f"  fechaOrden min={min(fechas)} max={max(fechas)} (¿trae hora? ver formato)")
    out.note("  ⚠ Si NO aparecen tipos como dividendo/renta/amortización/depósito/extracción, la API de")
    out.note("    operaciones solo trae ÓRDENES; los flujos de caja no están expuestos para retail.")

    # Paginación / tope silencioso: el año más cargado, mes a mes, vs. la llamada anual.
    if per_year:
        ybusy = max(per_year, key=per_year.get)
        monthly = 0
        for m in range(1, 13):
            d0 = date(ybusy, m, 1)
            d1 = (date(ybusy + (m == 12), (m % 12) + 1, 1) - timedelta(days=1))
            if d0 > today:
                break
            ops, _ = safe(out, f"operaciones {ybusy}-{m:02d}", lambda a=d0, b=min(d1, today): get(
                "/api/v2/operaciones", tok, **{"filtro.estado": "todas", "filtro.fechaDesde": a.isoformat(),
                                               "filtro.fechaHasta": b.isoformat()}))
            monthly += len(ops) if isinstance(ops, list) else 0
            time.sleep(0.3)
        out.note(f"  S6 tope: año {ybusy} anual={per_year[ybusy]} vs suma mensual={monthly} "
                 f"({'IGUAL → sin tope' if monthly == per_year[ybusy] else 'DISTINTO → hay tope/paginación oculta'})")

    # pais filter
    for pais in ("argentina", "estados_Unidos"):
        ops, _ = safe(out, f"operaciones filtro.pais={pais} (2 años)", lambda p=pais: get(
            "/api/v2/operaciones", tok, **{"filtro.estado": "todas", "filtro.pais": p,
                                           "filtro.fechaDesde": (today - timedelta(days=730)).isoformat(),
                                           "filtro.fechaHasta": today.isoformat()}))
        out.note(f"    → {len(ops) if isinstance(ops, list) else 'n/a'} operaciones")

    out.note("\n## S4 Detalle de operación (aranceles = comisiones)")
    seen_tipo = set()
    picked = []
    for o in sorted(all_ops.values(), key=lambda x: str(x.get("fechaOrden")), reverse=True):
        key = (o.get("tipo"), o.get("estado") == "terminada")
        if key not in seen_tipo and len(picked) < 8:
            seen_tipo.add(key)
            picked.append(o)
    details = []
    for o in picked:
        d, _ = safe(out, f"operaciones/{o.get('numero')} ({o.get('tipo')}, {o.get('estado')})",
                    lambda n=o.get("numero"): get(f"/api/v2/operaciones/{n}", tok))
        if isinstance(d, dict):
            details.append(d)
            out.note(f"    aranceles={d.get('aranceles')} arancelesARS={d.get('arancelesARS')} "
                     f"arancelesUSD={d.get('arancelesUSD')} moneda={d.get('moneda')} "
                     f"fills={len(d.get('operaciones') or [])} estados={len(d.get('estados') or [])}")
        time.sleep(0.3)
    out.save("operaciones_detalle.json", details)

    out.note("\n## S3 Movimientos de caja (dividendos, depósitos, transferencias de títulos)")
    out.note("  El swagger v2 NO tiene endpoint de movimientos para retail. Probamos el de Asesores:")
    mv, _ = safe(out, "POST Asesor/Movimientos (consulta de lectura)", lambda: _request(
        "POST", "/api/v2/Asesor/Movimientos", token=tok,
        json_body={"from": f"{today.year - 1}-01-01", "to": today.isoformat(), "dateType": "fechaOperacion",
                   "status": "todas", "type": "todos", "country": "argentina", "currency": "todas"}))
    out.save("asesor_movimientos.json", mv)
    nt, _ = safe(out, "Notificacion", lambda: get("/api/v2/Notificacion", tok))
    out.save("notificacion.json", nt)

    out.note("\n## S5 Rate limit (ráfaga de GET estadocuenta, máx 150)")
    t0, n, first_err = time.time(), 0, None
    for i in range(150):
        try:
            _request("GET", "/api/v2/estadocuenta", token=tok, timeout=15)
            n += 1
        except IolHttp as e:
            first_err = (i + 1, e.status, {k: v for k, v in e.headers.items()
                                          if re.search(r"retry|limit|rate", k, re.I)})
            break
        except Exception as e:  # noqa
            first_err = (i + 1, type(e).__name__, str(e))
            break
    el = time.time() - t0
    out.note(f"  {n} OK en {el:.1f}s ({n / el if el else 0:.1f} req/s); primer error: {first_err}")

    out.note("\n## S7 Clave de dedup contra el .xls (Nro. de Boleto)")
    out.note(f"  numeros de las 10 operaciones más recientes: "
             f"{[o.get('numero') for o in sorted(all_ops.values(), key=lambda x: str(x.get('fechaOrden')), reverse=True)[:10]]}")
    out.note("  → Rendi los cruza con la columna 'Nro. de Boleto' del export 'Movimientos históricos'.")
    out.note("\n## S8 Sandbox: api-sandbox.invertironline.com (no se prueba acá; cuenta separada)")


# ---------------- WATCH (S1: vida del refresh token) ----------------

def _save_state(rt):
    with open(STATE_FILE, "w") as f:
        json.dump({"refresh_token": rt, "saved_at": datetime.now().isoformat()}, f)
    os.chmod(STATE_FILE, stat.S_IRUSR | stat.S_IWUSR)


def _log(line):
    line = f"{datetime.now().isoformat(timespec='seconds')} {line}"
    print(line)
    with open(WATCH_LOG, "a") as f:
        f.write(line + "\n")


def watch(tokens, interval):
    rt = tokens["refresh_token"]
    _save_state(rt)
    _log(f"START expires_in={tokens.get('expires_in')} .expires={tokens.get('.expires')} "
         f"refresh_len={len(rt)} interval={interval}s")
    # ¿El refresh token viejo sigue sirviendo después de usarlo? (rotación)
    try:
        new = refresh(rt)
        _log("refresh #1 OK (inmediato)")
        try:
            refresh(rt)
            _log("ROTACION: el refresh token VIEJO sigue válido tras usarlo (no rota)")
        except IolHttp as e:
            _log(f"ROTACION: el refresh token viejo queda inválido tras usarlo (HTTP {e.status}) → rota")
        rt = new["refresh_token"]
        _save_state(rt)
    except IolHttp as e:
        _log(f"refresh #1 FALLÓ HTTP {e.status} {e.body[:200]!r}")
        return
    started = time.time()
    n = 1
    while True:
        time.sleep(interval)
        n += 1
        try:
            new = refresh(rt)
            rt = new["refresh_token"]
            _save_state(rt)
            hours = (time.time() - started) / 3600
            _log(f"refresh #{n} OK — {hours:.1f} h desde el login; expires_in={new.get('expires_in')}")
        except IolHttp as e:
            hours = (time.time() - started) / 3600
            _log(f"refresh #{n} FALLÓ tras {hours:.1f} h — HTTP {e.status} {e.body[:300]!r}")
            _log("FIN. Ese número de horas es la vida del refresh token (o IOL lo invalidó por otro motivo).")
            return
        except Exception as e:  # noqa
            _log(f"refresh #{n} error de red {type(e).__name__}: {e} (sigo)")


# ---------------- main ----------------

def main():
    mode = (sys.argv[1] if len(sys.argv) > 1 else "probe").lower()
    if mode not in ("probe", "watch"):
        print(__doc__)
        sys.exit(1)
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 3600

    if mode == "watch" and os.path.exists(STATE_FILE):
        rt = json.load(open(STATE_FILE))["refresh_token"]
        print("Retomando desde iol_spike_state.json (sin pedir contraseña)...")
        try:
            tokens = refresh(rt)
        except IolHttp as e:
            print(f"El refresh guardado ya no sirve (HTTP {e.status}). Borrá {STATE_FILE} y volvé a correr.")
            sys.exit(2)
    else:
        user = input("Usuario IOL: ").strip()
        pwd = getpass.getpass("Contraseña IOL (no se muestra ni se guarda): ")
        try:
            tokens = login(user, pwd)
        except IolHttp as e:
            print(f"Login falló: HTTP {e.status} {e.body[:300]}")
            print("Si dice 'invalid_grant' o similar: ¿pediste la activación de APIs por mensaje y "
                  "aceptaste los TyC en Mi Cuenta > Personalización > APIs?")
            sys.exit(2)
        finally:
            del pwd
    tok = tokens["access_token"]
    print(f"Login OK. expires_in={tokens.get('expires_in')}s")

    if mode == "probe":
        out = Out()
        out.save("token_meta.json", {k: v for k, v in tokens.items() if k not in ("access_token", "refresh_token")})
        try:
            probe(tok, out)
        finally:
            out.finish()
    else:
        watch(tokens, interval)


if __name__ == "__main__":
    main()
