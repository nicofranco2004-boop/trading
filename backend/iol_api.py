"""Cliente READ-ONLY de la API REST v2 de IOL (InvertirOnline).

Fase 0/1 del plan `PLAN_iol_sync.md`. Hoy lo usa el "IOL Lab" (endpoints
/api/iol/lab/*): el tester pone usuario y contraseña en Rendi, este módulo hace
el login, corre un probe de solo lectura contra la API y devuelve un resultado
ANONIMIZADO. Mañana es el cliente del sync de la Fase 1/2, sin cambiar la
superficie de seguridad.

Garantías (no negociables):
  * NO existe ningún método de escritura acá: ni comprar, ni vender, ni
    suscribir/rescatar FCI, ni extracciones, ni cancelar. No están "apagados":
    no existen.
  * Único punto de salida a la red = _request(). Solo GET contra la allowlist
    ALLOWED_GET, más POST a /token (login/refresh) y a Asesor/Movimientos (una
    consulta de lectura que vive bajo rol asesor; se prueba porque es la única
    chance de tener flujos de caja por API). Cualquier otro path levanta
    IolGuardError ANTES de tocar la red. tests/test_iol_lab.py lo verifica.
  * La contraseña entra a login() y no se guarda en ningún lado. Nunca se
    loguea. El bearer dura 15 min; el refresh token es lo único que el caller
    puede decidir persistir (cifrado, opt-in del usuario).

Spec real: backend/scripts/iol_swagger_v2.json (bajado de /v2/swagger).
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx

BASE = "https://api.invertironline.com"

# ─── Allowlist dura ──────────────────────────────────────────────────────────
ALLOWED_GET = (
    "/api/v2/datos-perfil",
    "/api/v2/estadocuenta",
    "/api/v2/portafolio/argentina",
    "/api/v2/portafolio/estados_Unidos",
    "/api/v2/operaciones",
    "/api/v2/operaciones/",          # + {numero}
    "/api/v2/Notificacion",
)
ALLOWED_POST = ("/token", "/api/v2/Asesor/Movimientos")
_FORBIDDEN_FRAGMENTS = ("/operar", "cancelar", "extraccion", "deposito", "cuentas-bancarias")

# Campos que salen enmascarados de cualquier respuesta que se persista/envíe.
PII_KEYS = {"nombre", "apellido", "dni", "cuitCuil", "email", "numeroCuenta",
            "cuentaComitente", "numero_cuenta"}

# Hook para tests: httpx.MockTransport. En prod queda None (transporte real).
_transport = None
_TIMEOUT = 30.0


class IolError(Exception):
    """Respuesta HTTP no-2xx o error de red. `status` 0 = red/timeout."""
    def __init__(self, status: int, message: str, headers: Optional[dict] = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.headers = dict(headers or {})


class IolGuardError(RuntimeError):
    """Se intentó salir a la red por un path/método fuera de la allowlist."""


def _guard(method: str, path: str) -> str:
    bare = path.split("?")[0]
    low = bare.lower()
    if any(f in low for f in _FORBIDDEN_FRAGMENTS):
        raise IolGuardError(f"BLOQUEADO: {method} {bare}")
    if method == "GET":
        if not any(bare == p or (p.endswith("/") and bare.startswith(p)) for p in ALLOWED_GET):
            raise IolGuardError(f"BLOQUEADO: GET {bare} no está en ALLOWED_GET")
    elif method == "POST":
        if bare not in ALLOWED_POST:
            raise IolGuardError(f"BLOQUEADO: POST {bare} no está en ALLOWED_POST")
    else:
        raise IolGuardError(f"BLOQUEADO: método {method} prohibido")
    return bare


def _request(method: str, path: str, token: Optional[str] = None, *,
             params: Optional[dict] = None, form: Optional[dict] = None,
             json_body: Optional[dict] = None, timeout: float = _TIMEOUT) -> Tuple[Any, dict, int]:
    """Único punto de salida a la red. Devuelve (body_json_o_texto, headers, ms)."""
    _guard(method, path)
    headers = {"Accept": "application/json", "User-Agent": "rendi-iol/1 (read-only)"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    t0 = time.time()
    try:
        with httpx.Client(base_url=BASE, transport=_transport, timeout=timeout) as c:
            r = c.request(method, path, headers=headers, params=params, data=form, json=json_body)
    except httpx.HTTPError as e:
        raise IolError(0, f"red: {type(e).__name__}")
    ms = int((time.time() - t0) * 1000)
    if r.status_code >= 400:
        raise IolError(r.status_code, r.text[:600], r.headers)
    try:
        return r.json(), dict(r.headers), ms
    except ValueError:
        return r.text, dict(r.headers), ms


def get(path: str, token: str, **params) -> Tuple[Any, dict, int]:
    return _request("GET", path, token, params={k: v for k, v in params.items() if v is not None})


def login(username: str, password: str) -> dict:
    """POST /token grant_type=password → {access_token, refresh_token, expires_in, ...}.
    La contraseña no se retiene: vive en este frame y en el body del request."""
    body, _, _ = _request("POST", "/token",
                          form={"username": username, "password": password, "grant_type": "password"})
    if not isinstance(body, dict) or not body.get("access_token"):
        raise IolError(0, "respuesta de /token sin access_token")
    return body


def refresh(refresh_token: str) -> dict:
    body, _, _ = _request("POST", "/token",
                          form={"refresh_token": refresh_token, "grant_type": "refresh_token"})
    if not isinstance(body, dict) or not body.get("access_token"):
        raise IolError(0, "respuesta de /token (refresh) sin access_token")
    return body


# ─── Anonimización ───────────────────────────────────────────────────────────

def mask(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in PII_KEYS:
                out[k] = "***" if v not in (None, "") else v
            elif k == "numero" and isinstance(v, str):   # número de CUENTA (string); el de operación es int
                out[k] = "***"
            else:
                out[k] = mask(v)
        return out
    if isinstance(obj, list):
        return [mask(x) for x in obj]
    return obj


# ─── Probe (Fase 0) ──────────────────────────────────────────────────────────

class _Probe:
    def __init__(self, token: str, *, pause: float, burst: int, year_from: int):  # burst 60: IP compartida de Railway
        self.tok, self.pause, self.burst, self.year_from = token, pause, burst, year_from
        self.lines: List[str] = []
        self.data: Dict[str, Any] = {}

    def note(self, s: str):
        self.lines.append(s)

    def call(self, label: str, fn):
        try:
            body, headers, ms = fn()
            self.note(f"- {label}: OK ({ms} ms)")
            return body, headers
        except IolError as e:
            self.note(f"- {label}: HTTP {e.status} → {e.message[:200]!r}")
            return None, e.headers
        except IolGuardError as e:
            self.note(f"- {label}: GUARD {e}")
            return None, {}

    def run(self) -> Dict[str, Any]:
        tok, today = self.tok, date.today()
        self.note(f"# IOL probe — {datetime.now().isoformat(timespec='seconds')} (desde el backend de Rendi)")
        self.note("\n## S0 Perfil / cuenta / portafolio")
        perfil, h = self.call("datos-perfil", lambda: get("/api/v2/datos-perfil", tok))
        self.data["datos_perfil"] = perfil
        self.data["headers_primer_request"] = {k: v for k, v in (h or {}).items()
                                              if k.lower() not in ("set-cookie",)}
        if isinstance(perfil, dict):
            self.note(f"  perfilInversor={perfil.get('perfilInversor')} cuentaAbierta={perfil.get('cuentaAbierta')} "
                      f"actualizarTyC={perfil.get('actualizarTyC')} actualizarDDJJ={perfil.get('actualizarDDJJ')}")
        ec, _ = self.call("estadocuenta", lambda: get("/api/v2/estadocuenta", tok))
        self.data["estadocuenta"] = ec
        if isinstance(ec, dict):
            for c in ec.get("cuentas") or []:
                self.note(f"  cuenta tipo={c.get('tipo')} moneda={c.get('moneda')} disponible={c.get('disponible')} "
                          f"saldo={c.get('saldo')} titulosValorizados={c.get('titulosValorizados')} "
                          f"saldos[]={len(c.get('saldos') or [])} estado={c.get('estado')}")
        for pais in ("argentina", "estados_Unidos"):
            pf, _ = self.call(f"portafolio/{pais}", lambda p=pais: get(f"/api/v2/portafolio/{p}", tok))
            self.data[f"portafolio_{pais}"] = pf
            if isinstance(pf, dict):
                acts = pf.get("activos") or []
                self.note(f"  {pais}: {len(acts)} activos")
                for a in acts[:60]:
                    t = a.get("titulo") or {}
                    self.note(f"    {t.get('simbolo')} tipo={t.get('tipo')} moneda={t.get('moneda')} "
                              f"cant={a.get('cantidad')} ppc={a.get('ppc')} ult={a.get('ultimoPrecio')} val={a.get('valorizado')}")

        self.note("\n## S2/S6 Historial de operaciones por ventanas anuales (filtro.estado=todas)")
        all_ops: Dict[Any, dict] = {}
        per_year: Dict[int, int] = {}
        for y in range(self.year_from, today.year + 1):
            d0 = f"{y}-01-01"
            d1 = f"{y}-12-31" if y < today.year else today.isoformat()
            ops, _ = self.call(f"operaciones {y}", lambda a=d0, b=d1: get(
                "/api/v2/operaciones", tok, **{"filtro.estado": "todas", "filtro.fechaDesde": a, "filtro.fechaHasta": b}))
            if isinstance(ops, list):
                per_year[y] = len(ops)
                for o in ops:
                    if isinstance(o, dict):
                        all_ops[o.get("numero")] = o
            time.sleep(self.pause)
        ops_list = list(all_ops.values())
        self.data["operaciones_todas"] = ops_list
        self.note(f"  por año: {per_year}")
        self.note(f"  total únicas por numero: {len(ops_list)}; máx en una sola respuesta: {max(per_year.values() or [0])}")
        tipos: Dict[Any, int] = {}
        estados: Dict[Any, int] = {}
        mercados: Dict[Any, int] = {}
        fechas: List[str] = []
        for o in ops_list:
            tipos[o.get("tipo")] = tipos.get(o.get("tipo"), 0) + 1
            estados[o.get("estado")] = estados.get(o.get("estado"), 0) + 1
            mercados[o.get("mercado")] = mercados.get(o.get("mercado"), 0) + 1
            if o.get("fechaOrden"):
                fechas.append(str(o["fechaOrden"]))
        self.note(f"  tipos: {tipos}")
        self.note(f"  estados: {estados}")
        self.note(f"  mercados: {mercados}")
        if fechas:
            self.note(f"  fechaOrden min={min(fechas)} max={max(fechas)}")
        self.note("  ⚠ Si NO aparecen dividendo/renta/amortización/depósito/extracción: 'operaciones' = solo ÓRDENES.")
        if per_year:
            ybusy = max(per_year, key=per_year.get)
            monthly = 0
            for m in range(1, 13):
                d0m = date(ybusy, m, 1)
                if d0m > today:
                    break
                d1m = (date(ybusy + (m == 12), (m % 12) + 1, 1) - timedelta(days=1))
                ops, _ = self.call(f"operaciones {ybusy}-{m:02d}", lambda a=d0m, b=min(d1m, today): get(
                    "/api/v2/operaciones", tok, **{"filtro.estado": "todas", "filtro.fechaDesde": a.isoformat(),
                                                   "filtro.fechaHasta": b.isoformat()}))
                monthly += len(ops) if isinstance(ops, list) else 0
                time.sleep(self.pause)
            verdict = "IGUAL → sin tope" if monthly == per_year[ybusy] else "DISTINTO → hay tope/paginación oculta"
            self.note(f"  S6 tope: año {ybusy} anual={per_year[ybusy]} vs suma mensual={monthly} ({verdict})")
            self.data["s6"] = {"year": ybusy, "anual": per_year[ybusy], "mensual": monthly}
        for pais in ("argentina", "estados_Unidos"):
            ops, _ = self.call(f"operaciones filtro.pais={pais} (2 años)", lambda p=pais: get(
                "/api/v2/operaciones", tok, **{"filtro.estado": "todas", "filtro.pais": p,
                                               "filtro.fechaDesde": (today - timedelta(days=730)).isoformat(),
                                               "filtro.fechaHasta": today.isoformat()}))
            self.note(f"    → {len(ops) if isinstance(ops, list) else 'n/a'} operaciones")

        self.note("\n## S4 Detalle de operación (aranceles = comisiones)")
        seen, picked = set(), []
        for o in sorted(ops_list, key=lambda x: str(x.get("fechaOrden")), reverse=True):
            key = (o.get("tipo"), o.get("estado"))
            if key not in seen and len(picked) < 8:
                seen.add(key)
                picked.append(o)
        details = []
        for o in picked:
            d, _ = self.call(f"operaciones/{o.get('numero')} ({o.get('tipo')}, {o.get('estado')})",
                             lambda n=o.get("numero"): get(f"/api/v2/operaciones/{n}", tok))
            if isinstance(d, dict):
                details.append(d)
                self.note(f"    aranceles={d.get('aranceles')} arancelesARS={d.get('arancelesARS')} "
                          f"arancelesUSD={d.get('arancelesUSD')} moneda={d.get('moneda')} "
                          f"fills={len(d.get('operaciones') or [])} estados={len(d.get('estados') or [])}")
            time.sleep(self.pause)
        self.data["operaciones_detalle"] = details

        self.note("\n## S3 Movimientos de caja (dividendos, depósitos, transferencias de títulos)")
        self.note("  El swagger v2 NO tiene endpoint de movimientos para retail. Probamos el de Asesores:")
        mv, _ = self.call("POST Asesor/Movimientos (consulta de lectura)", lambda: _request(
            "POST", "/api/v2/Asesor/Movimientos", tok,
            json_body={"from": f"{today.year - 1}-01-01", "to": today.isoformat(), "dateType": "fechaOperacion",
                       "status": "todas", "type": "todos", "country": "argentina", "currency": "todas"}))
        self.data["asesor_movimientos"] = mv
        nt, _ = self.call("Notificacion", lambda: get("/api/v2/Notificacion", tok))
        self.data["notificacion"] = nt

        self.note(f"\n## S5 Rate limit (ráfaga de GET estadocuenta desde la IP de Rendi, máx {self.burst})")
        t0, n, first_err = time.time(), 0, None
        for i in range(self.burst):
            try:
                _request("GET", "/api/v2/estadocuenta", tok, timeout=15)
                n += 1
            except IolError as e:
                first_err = {"n": i + 1, "status": e.status,
                             "headers": {k: v for k, v in e.headers.items()
                                         if any(s in k.lower() for s in ("retry", "limit", "rate"))}}
                break
        el = time.time() - t0
        self.note(f"  {n} OK en {el:.1f}s ({(n / el) if el else 0:.1f} req/s); primer error: {first_err}")
        self.data["s5"] = {"ok": n, "seconds": round(el, 2), "first_error": first_err}

        self.note("\n## S7 Clave de dedup contra el .xls (Nro. de Boleto)")
        recent = [o.get("numero") for o in sorted(ops_list, key=lambda x: str(x.get("fechaOrden")), reverse=True)[:10]]
        self.note(f"  numeros de las 10 operaciones más recientes: {recent}")
        self.data["s7_numeros_recientes"] = recent
        return {"summary": "\n".join(self.lines), "result": mask(self.data),
                "stats": {"ops": len(ops_list), "tipos": tipos, "estados": estados, "per_year": per_year}}


def run_probe(token: str, *, pause: float = 0.25, burst: int = 60, year_from: int = 2010) -> Dict[str, Any]:
    """Corre el probe de solo lectura. Devuelve {summary: str, result: dict ANONIMIZADO, stats}.
    Nunca levanta por un endpoint que falle (queda anotado en el summary); sí
    propaga IolGuardError, que sería un bug nuestro."""
    return _Probe(token, pause=pause, burst=burst, year_from=year_from).run()
