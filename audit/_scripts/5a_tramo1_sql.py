import re
SRC="/tmp/rendi-main/backend/main.py"
txt=open(SRC,encoding="utf-8").read()
lines=txt.split("\n")
# tablas con columna user_id (scope por usuario)
USER_TABLES={"positions","operations","monthly_entries","snapshots","brokers","config",
 "goals","plazos_fijos","twr_periods","deleted_ops_journal","bond_cashflow_skips",
 "archived_positions","import_batches","subscriptions","users","alerts","watchlist",
 "ai_analyses_cache","ai_user_facts","email_verification_codes","password_reset_tokens",
 "advisor_clients","import_mappings","login_history","user_broker_credentials"}
# junta bloques conn.execute("...") dentro del rango
out=[]
i=3093
while i < 9102 and i < len(lines):
    l=lines[i]
    if ".execute(" in l:
        # juntar hasta balancear parentesis
        buf=[]; depth=0; j=i
        while j<len(lines) and j<i+40:
            buf.append(lines[j])
            depth+=lines[j].count("(")-lines[j].count(")")
            if depth<=0 and len(buf)>0: break
            j+=1
        blob=" ".join(x.strip() for x in buf)
        sql=" ".join(re.findall(r'"""(.*?)"""|"([^"]*)"|\'([^\']*)\'', blob, re.S)[0]) if False else blob
        low=blob.lower()
        m=re.search(r'\b(from|into|update|delete\s+from)\s+([a-z_]+)', low)
        if m:
            tbl=m.group(2)
            if tbl in USER_TABLES and "user_id" not in low:
                out.append((i+1, tbl, " ".join(blob.split())[:220]))
        i=j+1
    else:
        i+=1
for ln,t,b in out:
    print(f"{ln}|{t}|{b}")
