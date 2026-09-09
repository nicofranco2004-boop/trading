import re, sys
SRC="/tmp/rendi-main/backend/main.py"
INV="/Users/nicolaspussetto/Documents/trading/audit/05_seguridad/_inventario_endpoints.txt"
lines=open(SRC,encoding="utf-8").read().split("\n")
eps=[]
for l in open(INV,encoding="utf-8"):
    l=l.strip()
    if not l: continue
    ln,m,r=l.split("|",2)
    ln=int(ln)
    if 3094<=ln<=9102: eps.append((ln,m,r))
for ln,m,r in eps:
    # find signature: from decorator line, collect until the line that closes def(...)
    i=ln-1
    # advance to 'def '
    while i<len(lines) and not lines[i].lstrip().startswith("def "): i+=1
    sig=[]
    depth=0; started=False
    j=i
    while j<len(lines):
        sig.append(lines[j])
        depth+=lines[j].count("(")-lines[j].count(")")
        started=True
        if started and depth<=0: break
        j+=1
    s=" ".join(x.strip() for x in sig)
    deps=re.findall(r"Depends\(([A-Za-z_0-9.]+)\)", s)
    print(f"{ln}|{m.upper()}|{r}|{','.join(deps) or 'NINGUNA'}")
