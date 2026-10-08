"""Auditoría por azar del panel "Uso de Rendi" (GET /api/admin/uso).

Los tests armados a mano (test_admin_uso.py) prueban los casos que se nos
ocurrieron. Éste prueba los que no: arma cuentas, ingresos, clics, uso de IA,
importaciones y carteras AL AZAR —cargando a propósito la franja de 21:00 a
medianoche de Buenos Aires, que en UTC ya es el día siguiente— y compara cada
número del panel contra una cuenta escrita desde cero, de otra forma: en
Python, fila por fila, con fechas de verdad y no con comparaciones de texto.

Si el endpoint y esta cuenta no coinciden en un solo número, el test dice cuál,
en qué escenario y con qué período. La semilla es fija: un rojo se reproduce.

Corre con: cd backend && python3 -m pytest tests/test_admin_uso_azar.py
"""
import random
import statistics
import unittest
from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

import main
from fechas import hoy_art_date

ESCENARIOS = 40
PERIODOS_POR_ESCENARIO = 6
EVENTOS = ["moneda_cambiada", "buscador_abierto", "operation_added", "app_abierta",
           "pantalla:/", "pantalla:/posiciones", "pantalla:/ai",
           "ai_chat_sent", "ai_analyze_opened", "vista:ai_followup_loaded", "vista:paywall_muro_visto",
           "vista:fundamentals_ai_summary_loaded"]
EVENTOS_IA = {"ai_chat_sent", "ai_benchmark_question", "ai_analyze_opened", "ai_analyze_refresh",
              "vista:ai_followup_loaded"}
TABLAS = ["users", "login_history", "uso_diario", "ai_usage_daily", "import_batches",
          "positions", "operations", "brokers", "subscriptions", "monthly_entries"]


def es_real(u):
    e = u["email"]
    return (u["verified"] and not u["admin"] and not e.endswith("@rendi.test")
            and not e.endswith("@rendi.finance") and not e.startswith("test@") and "+test" not in e)


def cuenta(u, internos):
    return u["verified"] if internos else es_real(u)


def dia_art(ts):
    return (ts - timedelta(hours=3)).date()


def mediana(v):
    return statistics.median(v) if v else 0


class PanelContraLaCuentaAMano(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)

    def _limpiar(self):
        conn = main.get_db()
        try:
            for t in TABLAS:
                conn.execute(f"DELETE FROM {t}")
            conn.commit()
        finally:
            conn.close()

    def _ts(self, rnd, hoy, desde=None):
        """Un instante UTC de los últimos ~70 días (y no antes de `desde`: nadie
        entra antes de tener cuenta), con la mitad de las veces en la franja
        00:00–03:59 UTC (= 21:00–00:59 ART) o justo en el borde."""
        tope = 70 if desde is None else max(0, min(70, (hoy - desde.date()).days - 1))
        d = hoy - timedelta(days=rnd.randint(0, tope))
        base = datetime(d.year, d.month, d.day)
        r = rnd.random()
        if r < 0.15:
            return base + timedelta(hours=3)                       # exacto en el borde
        if r < 0.20:
            return base + timedelta(hours=2, minutes=59, seconds=59)
        if r < 0.55:
            return base + timedelta(minutes=rnd.randint(0, 239))   # 21–00:59 ART
        return base + timedelta(minutes=rnd.randint(0, 1439))

    def _escenario(self, rnd):
        hoy = hoy_art_date()
        conn = main.get_db()
        usuarios = []
        try:
            admin_id = conn.execute(
                "INSERT INTO users (email, password_hash, approved, is_admin, email_verified, created_at) "
                "VALUES ('adm@rendi.test', 'x', 1, 1, 1, '2026-01-01 00:00:00')").lastrowid
            usuarios.append({"id": admin_id, "email": "adm@rendi.test", "admin": True, "verified": True,
                             "created": datetime(2026, 1, 1)})
            dominios = ["ejemplo.com"] * 8 + ["rendi.finance", "rendi.test"]
            for i in range(rnd.randint(5, 30)):
                email = (f"test@{i}.com" if rnd.random() < 0.05 else
                         f"u{i}+test@x.com" if rnd.random() < 0.05 else
                         f"u{i}@{rnd.choice(dominios)}")
                created = self._ts(rnd, hoy) - timedelta(days=rnd.randint(2, 30))
                u = {"email": email, "admin": rnd.random() < 0.08, "verified": rnd.random() < 0.85,
                     "created": created}
                u["id"] = conn.execute(
                    "INSERT INTO users (email, password_hash, approved, is_admin, email_verified, created_at) "
                    "VALUES (?, 'x', 1, ?, ?, ?)",
                    (email, int(u["admin"]), int(u["verified"]), created.strftime("%Y-%m-%d %H:%M:%S"))).lastrowid
                usuarios.append(u)
            logins, usos, ias, imps, pos, ops = [], {}, [], [], {}, {}
            for u in usuarios:
                for _ in range(rnd.choice([0, 0, 1, 2, 5, 12])):
                    ts = self._ts(rnd, hoy, u["created"])
                    logins.append((u["id"], ts))
                    conn.execute("INSERT INTO login_history (user_id, created_at) VALUES (?, ?)",
                                 (u["id"], ts.strftime("%Y-%m-%d %H:%M:%S")))
                for _ in range(rnd.choice([0, 0, 3, 10])):
                    d = (hoy - timedelta(days=rnd.randint(0, max(0, min(50, (hoy - u["created"].date()).days - 1))))).isoformat()
                    ev = rnd.choice(EVENTOS)
                    n = rnd.randint(1, 9)
                    usos[(u["id"], d, ev)] = usos.get((u["id"], d, ev), 0) + n
                for _ in range(rnd.choice([0, 0, 2])):
                    d = (hoy - timedelta(days=rnd.randint(0, 50))).isoformat()
                    c = [rnd.choice([0, 0, 1, 3]) for _ in range(4)]
                    if any(x for (uu, dd, _) in ias for x in () if uu == u["id"] and dd == d):
                        continue
                    if (u["id"], d) in {(a, b) for a, b, _ in ias}:
                        continue
                    ias.append((u["id"], d, c))
                    conn.execute("INSERT INTO ai_usage_daily (user_id, date, analyses_count, chat_count, "
                                 "hub_queries_count, listen_count) VALUES (?,?,?,?,?,?)", (u["id"], d, *c))
                for _ in range(rnd.choice([0, 0, 0, 1, 2])):
                    st = rnd.choice(["confirmed", "confirmed", "reverted", "pending"])
                    cr = self._ts(rnd, hoy, u["created"])
                    cf = cr + timedelta(minutes=rnd.randint(0, 600)) if rnd.random() < 0.8 else None
                    imps.append((u["id"], st, cr, cf))
                    conn.execute(
                        "INSERT INTO import_batches (id, user_id, broker, parser_format, file_hash, status, created_at, confirmed_at) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (f"b{rnd.random()}", u["id"], "IOL", "x", "h", st, cr.strftime("%Y-%m-%d %H:%M:%S"),
                         cf.strftime("%Y-%m-%d %H:%M:%S") if cf else None))
                # Filas de posiciones como en la realidad: lotes repetidos del mismo
                # activo, cajas de efectivo, filas en cero, varios brokers.
                filas_pos = []
                for _ in range(rnd.choice([0, 0, 1, 3, 7, 25, 150])):
                    filas_pos.append((rnd.choice(["IOL", "Balanz"]), rnd.choice(["GGAL", "AL30", "SPY", "YPF", "USD", f"T{rnd.randint(1, 120)}"]),
                                      int(rnd.random() < 0.15), rnd.choice([0, 0.5, 1, 10])))
                for b, a, c, q in filas_pos:
                    conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity) VALUES (?,?,?,?,?,?)",
                                 (u["id"], b, a, c, 1, q))
                pos[u["id"]] = len({(b, a) for b, a, c, q in filas_pos if not c and q > 0})
                ops[u["id"]] = rnd.choice([0, 2, 9, 40])
                for _ in range(ops[u["id"]]):
                    conn.execute("INSERT INTO operations (user_id, date, broker, asset, op_type) VALUES (?,?,?,?,?)",
                                 (u["id"], "2026-01-01", "IOL", "GGAL", "buy"))
            for (uid, d, ev), n in usos.items():
                conn.execute("INSERT INTO uso_diario (user_id, dia, evento, cantidad) VALUES (?,?,?,?)", (uid, d, ev, n))
            conn.commit()
        finally:
            conn.close()
        return usuarios, admin_id, logins, usos, ias, imps, pos, ops

    def _esperado(self, desde, hasta, internos, usuarios, logins, usos, ias, imps, pos, ops):
        """La cuenta a mano. Nada de SQL: filas y fechas."""
        hoy = hoy_art_date()
        hasta = min(hasta, hoy)
        largo = (hasta - desde).days + 1
        p_hasta = desde - timedelta(days=1)
        p_desde = p_hasta - timedelta(days=largo - 1)
        quien = {u["id"]: u for u in usuarios if cuenta(u, internos)}
        en = lambda d, a, b: a <= d <= b
        lg = [(u, dia_art(ts), ts) for u, ts in logins if u in quien]

        def ingresos(a, b):
            us = {u for u, d, _ in lg if en(d, a, b)}
            primero = {}
            for u, d, _ in lg:
                primero[u] = min(primero.get(u, d), d)
            pv = {u for u in us if en(primero[u], a, b)}
            fin = datetime(b.year, b.month, b.day) + timedelta(days=1, hours=3)
            base = sum(1 for u in quien.values() if u["created"] < fin)
            return us, pv, base, sum(1 for u, d, _ in lg if en(d, a, b)), primero

        us, pv, base, n_ing, primero = ingresos(desde, hasta)
        us_prev = ingresos(p_desde, p_hasta)[0]
        todos_login = [dia_art(ts) for _, ts in logins]
        datos_desde = min(todos_login) if todos_login else None
        uso_desde = min((date.fromisoformat(d) for (_, d, _) in usos), default=None)

        uso_p = {(u, date.fromisoformat(d), ev): n for (u, d, ev), n in usos.items()
                 if u in quien and en(date.fromisoformat(d), desde, hasta)}
        app = {u for (u, _, _) in uso_p}
        activos = us | app
        # IA = lo que se pidió (eventos), NO el cupo de ai_usage_daily.
        ia = {}
        for (u, _, ev), n in uso_p.items():
            if ev in EVENTOS_IA:
                ia[u] = ia.get(u, 0) + n
        lo = datetime(desde.year, desde.month, desde.day) + timedelta(hours=3)
        hi = datetime(hasta.year, hasta.month, hasta.day) + timedelta(days=1, hours=3)
        # Importaron: confirmada en el período, aunque después se haya deshecho.
        importaron = {u for u, st, cr, cf in imps if u in quien and (
            (st == "confirmed" and lo <= (cf or cr) < hi) or (st == "reverted" and cf and lo <= cf < hi))}
        # Primera vez = la cuenta se creó en el período.
        alta = {u["id"]: dia_art(u["created"]) for u in quien.values() if lo <= u["created"] < hi}
        medido = uso_desde is not None and uso_desde <= hasta

        filas = {}
        for u in activos:
            dias = {d for (uu, d, _) in uso_p if uu == u}
            ult_l = max((d for uu, d, _ in lg if uu == u and en(d, desde, hasta)), default=None)
            ult = max([x for x in [max(dias, default=None), ult_l] if x], default=None)
            toq = sum(n for (uu, _, ev), n in uso_p.items()
                      if uu == u and not ev.startswith(("pantalla:", "vista:")) and ev != "app_abierta")
            filas[u] = {
                "ingresos": sum(1 for uu, d, _ in lg if uu == u and en(d, desde, hasta)),
                "dias_con_uso": len(dias),
                "ultimo": ult.isoformat() if ult else None,
                "primera_vez": u in alta,
                "posiciones": pos.get(u, 0), "operaciones": ops.get(u, 0),
                "ia": ia.get(u, 0) if u in app else None,
                "toques": toq if u in app else None,
            }

        por_dia = []
        d = desde
        while d <= hasta:
            l_d = {u for u, dd, _ in lg if dd == d}
            a_d = {u for (u, dd, _) in uso_p if dd == d}
            por_dia.append({"dia": d.isoformat(), "activos": len(l_d | a_d), "ingresaron": len(l_d),
                            "primera_vez": sum(1 for u in l_d | a_d if alta.get(u) == d), "usaron_app": len(a_d)})
            d += timedelta(days=1)

        compara_uso = uso_desde is not None and uso_desde <= p_desde

        def ranking(a, b, grupo):
            r = {}
            for (u, d, ev), n in usos.items():
                dd = date.fromisoformat(d)
                g = "pantallas" if ev.startswith("pantalla:") else "avisos" if ev.startswith("vista:") else "botones"
                if u not in quien or not en(dd, a, b) or ev == "app_abierta" or g != grupo:
                    continue
                p, c = r.get(ev, (set(), 0))
                r[ev] = (p | {u}, c + n)
            return r

        def lista(grupo):
            r, rp = ranking(desde, hasta, grupo), ranking(p_desde, p_hasta, grupo)
            return {ev: {"personas": len(p), "cantidad": c,
                         "personas_antes": len(rp.get(ev, (set(), 0))[0]) if compara_uso else None}
                    for ev, (p, c) in r.items()}

        con_cuenta = [u for u in quien.values() if u["created"] < hi]
        act_l = [u["id"] for u in con_cuenta if u["id"] in activos]
        ina_l = [u["id"] for u in con_cuenta if u["id"] not in activos]
        tramos = [(0, 0), (1, 5), (6, 20), (21, 100), (101, None)]
        cnt = lambda g, mn, mx: sum(1 for u in g if pos.get(u, 0) >= mn and (mx is None or pos.get(u, 0) <= mx))

        return {
            "resumen": {
                "usuarios": len(us), "ingresos": n_ing,
                "primera_vez": len(activos & set(alta)), "volvieron": len(activos - set(alta)),
                "base": base,
                "usuarios_antes": len(us_prev) if datos_desde and datos_desde <= p_desde else None,
                "usaron_app": len(app) if uso_desde and uso_desde <= hasta else None,
                "activos": len(activos), "usaron_ia": len([1 for v in ia.values() if v > 0]) if medido else None,
                "importaron": len(importaron),
            },
            "filas": filas, "por_dia": por_dia,
            "botones": lista("botones"), "pantallas": lista("pantallas"), "avisos": lista("avisos"),
            "tramos": [[cnt(act_l, a, b), cnt(ina_l, a, b)] for a, b in tramos],
            "medianas": [mediana([pos.get(u, 0) for u in act_l]), mediana([ops.get(u, 0) for u in act_l]),
                         mediana([pos.get(u, 0) for u in ina_l]), mediana([ops.get(u, 0) for u in ina_l])],
        }

    def test_cada_numero_coincide_con_la_cuenta_a_mano(self):
        rnd = random.Random(20261008)
        hoy = hoy_art_date()
        comparados = 0
        for esc in range(ESCENARIOS):
            self._limpiar()
            usuarios, admin_id, logins, usos, ias, imps, pos, ops = self._escenario(rnd)
            h = {"Authorization": f"Bearer {main.create_token(admin_id)}"}
            for _ in range(PERIODOS_POR_ESCENARIO):
                hasta = hoy - timedelta(days=rnd.choice([0, 0, 0, 1, 5, 20]))
                desde = hasta - timedelta(days=rnd.choice([0, 0, 1, 6, 29, 89]))
                internos = rnd.random() < 0.3
                r = self.client.get("/api/admin/uso", headers=h, params={
                    "desde": desde.isoformat(), "hasta": hasta.isoformat(), "internos": str(internos).lower()})
                self.assertEqual(r.status_code, 200, r.text)
                got = r.json()
                exp = self._esperado(desde, hasta, internos, usuarios, logins, usos, ias, imps, pos, ops)
                ctx = f"escenario {esc}, {desde}..{hasta}, internos={internos}"
                for k, v in exp["resumen"].items():
                    self.assertEqual(got["resumen"][k], v, f"{k} — {ctx}")
                self.assertEqual(got["por_dia"], exp["por_dia"], f"por_dia — {ctx}")
                g_filas = {u["id"]: u for u in got["usuarios"]}
                self.assertEqual(set(g_filas), set(exp["filas"]), f"quiénes están en la lista — {ctx}")
                for uid, f in exp["filas"].items():
                    for k, v in f.items():
                        self.assertEqual(g_filas[uid][k], v, f"usuario {uid}: {k} — {ctx}")
                for tipo in ("botones", "pantallas", "avisos"):
                    g = {x["evento"]: {k: x[k] for k in ("personas", "cantidad", "personas_antes")}
                         for x in got["ranking"][tipo]}
                    self.assertEqual(g, exp[tipo], f"ranking {tipo} — {ctx}")
                c = got["cartera"]
                self.assertEqual([[t["activos"], t["inactivos"]] for t in c["tramos"]], exp["tramos"], f"tramos — {ctx}")
                self.assertEqual([c["activos"]["posiciones"], c["activos"]["operaciones"],
                                  c["inactivos"]["posiciones"], c["inactivos"]["operaciones"]],
                                 exp["medianas"], f"medianas — {ctx}")
                self.assertEqual(c["activos"]["cuantos"], len([1 for x in exp["filas"]]), f"activos en cartera — {ctx}")
                comparados += 1
        self.assertEqual(comparados, ESCENARIOS * PERIODOS_POR_ESCENARIO)


if __name__ == "__main__":
    unittest.main()
