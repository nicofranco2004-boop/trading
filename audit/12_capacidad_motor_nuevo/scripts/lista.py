"""La lista de tickers que seguiría la noche (código de esta copia) sobre una COPIA migrada de la
base de prod del 16/08. Uso: DB_PATH=<copia descartable> python3 lista.py salida.json"""
import sys, json, collections
import main  # init_db migra la copia (DB_PATH)
import velas_diarias
with main.db_abierta() as conn:
    tickers, pares = velas_diarias._seguimiento(conn)
tickers = set(tickers); tickers.discard("^GSPC")
print("tickers:", len(tickers), "· CEDEAR con par:", len(pares))
print(dict(collections.Counter("cripto" if t.endswith("-USD") else "BYMA" if t.endswith(".BA") else "afuera" for t in tickers)))
json.dump(sorted(tickers), open(sys.argv[1], "w"))
