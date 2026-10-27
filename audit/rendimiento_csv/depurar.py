"""Corre UN escenario y muestra el detalle del motor (cortes, tramos) normal y contrafáctico."""
import json, sys
import arnes, correr_escenarios as ce
from mercado import Mercado
import generadores as g
br, esc = sys.argv[1], sys.argv[2]
m = Mercado(); a = arnes.Arnes(m)
h, omitir, ajustar, hasta = ce.escenarios(m)[esc]; h.simular()
gen, broker, fmt, nombre = ce.MOV[br]
a.usuario("dbg@rendi.test"); a.subir([(nombre, gen(h, omitir=omitir, hasta=hasta))], broker=broker, fmt=fmt)
if br in ce.FOTOS:
    fg, ff, fn = ce.FOTOS[br]; a.subir_foto(fn, fg(h, ce.FOTO, ajustar), broker, ff)
from datetime import date, timedelta
a.cron(date(2026, 8, 4), date.today()); a.reconstruir()
def det(c):
    return {k: c.get(k) for k in ("twr", "motivo", "ventana_desde", "ventana_hasta", "serie_partida",
                                  "cortes_dudosos", "cortes_capital_chico", "tramos_vetados", "contable_superado",
                                  "reconstruido_superado", "contable_realineado", "tramos_detalle")}
conn = arnes.main.get_db()
print("NORMAL estimado:", json.dumps(det(arnes.twr.curva_indexada(conn, a.uid, modo="estimado")), default=str)[:1500])
conn.close()
cf = arnes.contrafactico_sin_cobros(a)
print("CF estimado:", json.dumps(det(cf["curva"]["estimado"]), default=str)[:1500])
print("CF certero:", json.dumps(det(cf["curva"]["certero"]), default=str)[:800])
