"""PoC del mecanismo de main.py:28342 (conn.close) vs main.py:28412 (conn.execute).
No toca prod ni la DB de Rendi: sqlite in-memory."""
import sqlite3
conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE users(id INTEGER, tier TEXT)")
conn.close()
try:
    conn.execute("SELECT tier FROM users WHERE id=?", (1,)).fetchone()
    print("NO RAISE (inesperado)")
except Exception as ex:
    print(f"RAISE: {type(ex).__name__}: {ex}")
