"""IEB: la foto siembra al PPP (costo del broker). Títulos de otro broker (VIST) con PPP = 80 % del precio."""
import sys, json
from datetime import date
import arnes, correr_escenarios as ce, generadores as g
from mercado import Mercado
m = Mercado(); a = arnes.Arnes(m)
h, omitir, _, _ = ce.escenarios(m)["S3_titulos_de_otro_broker"]; h.simular()
out = {}
for factor in (1.0, 0.8):
    a.usuario(f"ppp_{factor}@rendi.test")
    a.subir([("actividad.xlsx", g.ieb_mov(h, omitir=omitir))], broker="IEB", fmt="ieb")
    pv, cf = a.subir_foto("portafolio.xlsx", g.ieb_foto(h, ce.FOTO, ppp_factor=factor), "IEB", "ieb_tenencia")
    a.cron(date(2026, 8, 4), date.today()); a.reconstruir()
    r = ce.medir_contra_verdad(h, a.motor())
    sint = a.q("SELECT n.operation_type t, n.asset_symbol a, ROUND(n.gross_amount,2) g, n.currency c FROM import_normalized_tx n "
               "JOIN import_batches b ON b.id=n.batch_id WHERE b.user_id=? AND b.parser_format LIKE '%tenencia%'", a.uid)
    out[factor] = r
    print("PPP factor", factor, "| CERT", r["certero"]["rendi"], "vs", r["certero"].get("verdad_twr"), r["certero"]["ventana"],
          "| EST", r["estimado"]["rendi"], "vs", r["estimado"].get("verdad_twr"), "| siembra", sint, flush=True)
