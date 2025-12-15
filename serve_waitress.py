import os
import sys

# Stelle sicher dass app.py gefunden wird (für embedded Python)
APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

from app import app, init_db
from waitress import serve

init_db()

port = int(os.environ.get("PORT", "8000"))
threads = int(os.environ.get("THREADS", "48"))

serve(app, host="127.0.0.1", port=port, threads=threads)
