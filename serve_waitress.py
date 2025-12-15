from app import app, init_db
from waitress import serve
import os

init_db()

port = int(os.environ.get("PORT", "8000"))
threads = int(os.environ.get("THREADS", "16"))

serve(app, host="127.0.0.1", port=port, threads=threads)
