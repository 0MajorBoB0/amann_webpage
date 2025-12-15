import os, sqlite3, datetime, sys

root = os.path.dirname(os.path.abspath(__file__))
src  = os.path.join(root, "game.db")
dst_dir = os.path.join(root, "backups")
os.makedirs(dst_dir, exist_ok=True)

if not os.path.exists(src):
    print("NO_DB")
    sys.exit(0)

ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
dst = os.path.join(dst_dir, f"game_{ts}.db")

con = sqlite3.connect(src)
try:
    con.execute("PRAGMA wal_checkpoint(FULL);")
except Exception:
    pass

bck = sqlite3.connect(dst)
con.backup(bck)
bck.close()
con.close()

print(dst)

