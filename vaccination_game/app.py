
import os, sqlite3, uuid, random, string, datetime
from flask import Flask, request, redirect, render_template, session as flask_session, url_for, send_file, jsonify, g
from flask_socketio import SocketIO, join_room, emit

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "game.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ManarHolgerErwin!")

app = Flask(__name__, template_folder=os.path.join(APP_DIR, "templates"), static_folder=os.path.join(APP_DIR, "static"))
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

def db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False); c.row_factory = sqlite3.Row; return c

def ensure_column(con, table, column, definition):
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols: con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"); con.commit()

def init_db():
    con = db()
    con.execute("""CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY, name TEXT, group_size INTEGER, rounds INTEGER,
        cvac REAL, alpha REAL, cinf REAL, subsidy INTEGER DEFAULT 0, subsidy_amount REAL DEFAULT 0,
        regime TEXT, starting_balance REAL DEFAULT 500, created_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS participants (
        id TEXT PRIMARY KEY, session_id TEXT, code TEXT UNIQUE, theta REAL, lambda REAL, alias TEXT,
        joined INTEGER DEFAULT 0, current_round INTEGER DEFAULT 1, balance REAL DEFAULT 0, created_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, participant_id TEXT,
        round_number INTEGER, choice TEXT, a_cost REAL, b_cost REAL, total_cost REAL, created_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, participant_id TEXT, alias TEXT, text TEXT, created_at TEXT)""")
    con.commit()
    ensure_column(con, "participants", "alias", "TEXT")

@app.before_request
def load_participant():
    pid = flask_session.get("participant_id")
    g.participant = None
    if pid:
        con = db(); g.participant = con.execute("SELECT * FROM participants WHERE id=?", (pid,)).fetchone()

def create_code(n=6):
    alphabet = (string.ascii_uppercase + string.digits).replace("O","").replace("0","").replace("I","").replace("1","")
    return "".join(random.choice(alphabet) for _ in range(n))

@app.route("/")
def index():
    if g.participant: return redirect(determine_next_url(g.participant))
    return redirect(url_for("join"))

@app.route("/logout")
def logout():
    flask_session.pop("participant_id", None); return redirect(url_for("join"))

@app.route("/me")
def me():
    if not g.participant: return ("", 401)
    con = db(); s = con.execute("SELECT id,name FROM sessions WHERE id=?", (g.participant["session_id"],)).fetchone()
    return jsonify({"code": g.participant["code"], "alias": g.participant["alias"], "session_id": s["id"], "session_name": s["name"]})

@app.route("/join", methods=["GET","POST"])
def join():
    con = db()
    if request.method == "POST":
        code = request.form.get("code","").strip().upper(); alias = request.form.get("alias","").strip()
        p = con.execute("SELECT * FROM participants WHERE code=?", (code,)).fetchone()
        if not p: return render_template("join.html", error="Code unbekannt.")
        flask_session["participant_id"] = p["id"]; con.execute("UPDATE participants SET joined=1 WHERE id=?", (p["id"],))
        if alias: con.execute("UPDATE participants SET alias=? WHERE id=?", (alias, p["id"]))
        con.commit(); return redirect(determine_next_url(p))
    return render_template("join.html", error=None)

@app.route("/alias", methods=["POST"])
def alias():
    if not g.participant: return redirect(url_for("join"))
    a = request.form.get("alias","").strip()
    if a: con = db(); con.execute("UPDATE participants SET alias=? WHERE id=?", (a, g.participant["id"])); con.commit()
    return redirect(url_for("lobby"))

def determine_next_url(p_row):
    con = db(); p = con.execute("SELECT * FROM participants WHERE id=?", (p_row["id"],)).fetchone()
    s = con.execute("SELECT * FROM sessions WHERE id=?", (p["session_id"]),).fetchone()
    joined = con.execute("SELECT COUNT(*) c FROM participants WHERE session_id=? AND joined=1", (s["id"],)).fetchone()["c"]
    if joined < s["group_size"]: return url_for("lobby")
    if p["current_round"] > s["rounds"]: return url_for("quiz")
    decided = con.execute("SELECT 1 FROM decisions WHERE participant_id=? AND round_number=?", (p["id"], p["current_round"])).fetchone()
    return url_for("wait_view") if decided else url_for("round_view")

@app.route("/lobby")
def lobby():
    if not g.participant: return redirect(url_for("join"))
    con = db(); s = con.execute("SELECT * FROM sessions WHERE id=?", (g.participant["session_id"],)).fetchone()
    joined = con.execute("SELECT COUNT(*) c FROM participants WHERE session_id=? AND joined=1", (s["id"]),).fetchone()["c"]
    return render_template("lobby.html", session=s, participant=g.participant, joined=joined)

@app.route("/lobby_status")
def lobby_status():
    sid = request.args.get("session_id"); con = db(); s = con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    joined = con.execute("SELECT COUNT(*) c FROM participants WHERE session_id=? AND joined=1", (sid,)).fetchone()["c"]
    return jsonify({"joined": joined, "group_size": s["group_size"], "ready": joined >= s["group_size"]})

@app.route("/round")
def round_view():
    if not g.participant: return redirect(url_for("join"))
    con = db(); p = g.participant; s = con.execute("SELECT * FROM sessions WHERE id=?", (p["session_id"],)).fetchone()
    joined = con.execute("SELECT COUNT(*) c FROM participants WHERE session_id=? AND joined=1", (s["id"],)).fetchone()["c"]
    if joined < s["group_size"]: return redirect(url_for("lobby"))
    r = p["current_round"]; if r > s["rounds"]: return redirect(url_for("quiz"))
    a_cost_preview = max(p["theta"] * (s["cvac"] - (s["subsidy_amount"] if s["subsidy"] else 0)), 0)
    b_cost_max = p["lambda"] * s["alpha"] * 1.0 * s["cinf"]
    return render_template("round.html", session=s, round_number=r, a_cost_preview=round(a_cost_preview,2), b_cost_max=b_cost_max)

@app.route("/choose", methods=["POST"])
def choose():
    if not g.participant: return ("No participant", 400)
    data = request.get_json() or {}; choice = data.get("choice")
    if choice not in ("A","B"): return ("Invalid choice", 400)
    con = db(); p = g.participant; s = con.execute("SELECT * FROM sessions WHERE id=?", (p["session_id"],)).fetchone()
    r = p["current_round"]; already = con.execute("SELECT 1 FROM decisions WHERE participant_id=? AND round_number=?", (p["id"], r)).fetchone()
    if not already:
        con.execute("INSERT INTO decisions (session_id, participant_id, round_number, choice, created_at) VALUES (?,?,?,?,?)",
                    (s["id"], p["id"], r, choice, datetime.datetime.utcnow().isoformat())); con.commit()
    return ("OK", 200)

@app.route("/wait")
def wait_view():
    if not g.participant: return redirect(url_for("join"))
    con = db(); p = g.participant; s = con.execute("SELECT * FROM sessions WHERE id=?", (p["session_id"]),).fetchone()
    r = p["current_round"]
    decided = con.execute("SELECT COUNT(*) c FROM decisions WHERE session_id=? AND round_number=?", (s["id"], r)).fetchone()["c"]
    return render_template("wait.html", session=s, round_number=r, decided=decided)

@app.route("/round_status")
def round_status():
    sid = request.args.get("session_id"); r = int(request.args.get("round")); con = db()
    s = con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    decided = con.execute("SELECT COUNT(*) c FROM decisions WHERE session_id=? AND round_number=?", (sid, r)).fetchone()["c"]
    ready = decided >= s["group_size"]
    if ready:
        missing = con.execute("SELECT COUNT(*) c FROM decisions WHERE session_id=? AND round_number=? AND total_cost IS NULL", (sid, r)).fetchone()["c"]
        if missing > 0:
            rows = con.execute("""SELECT d.id, d.participant_id, d.choice, p.theta, p.lambda
                                  FROM decisions d JOIN participants p ON p.id=d.participant_id
                                  WHERE d.session_id=? AND d.round_number=?""", (sid, r)).fetchall()
            b_players = [row for row in rows if row["choice"]=="B"]; b_count = len(b_players)
            N = s["group_size"]; alpha = s["alpha"]; cinf = s["cinf"]
            updates = []
            for row in rows:
                if row["choice"] == "A":
                    a_cost = max(row["theta"] * (s["cvac"] - (s["subsidy_amount"] if s["subsidy"] else 0)), 0); b_cost_val = None; total = a_cost
                else:
                    share_others = (b_count - 1) / (N - 1) if N > 1 else 0.0
                    b_cost_val = row["lambda"] * alpha * share_others * cinf; a_cost = None; total = b_cost_val
                updates.append((a_cost, b_cost_val, total, row["id"]))
            for a_cost, b_cost_val, total, did in updates:
                con.execute("UPDATE decisions SET a_cost=?, b_cost=?, total_cost=? WHERE id=?", (a_cost, b_cost_val, total, did))
            con.commit()
            for c in con.execute("SELECT participant_id, total_cost FROM decisions WHERE session_id=? AND round_number=?", (sid, r)):
                con.execute("UPDATE participants SET balance = COALESCE(balance,0) - ?, current_round = current_round WHERE id=?", (c["total_cost"], c["participant_id"]))
            con.commit()
            con.execute("UPDATE participants SET current_round = current_round + 1 WHERE session_id=? AND current_round=?", (sid, r)); con.commit()
    decided_codes = [row["code"] for row in con.execute("""SELECT p.code FROM decisions d JOIN participants p ON p.id=d.participant_id WHERE d.session_id=? AND d.round_number=? ORDER BY p.code""", (sid, r)).fetchall()]
    return jsonify({"decided": decided, "ready": ready, "decided_codes": decided_codes})

@app.route("/feedback")
def feedback():
    if not g.participant: return redirect(url_for("join"))
    con = db(); p = g.participant; s = con.execute("SELECT * FROM sessions WHERE id=?", (p["session_id"],)).fetchone()
    r = p["current_round"] - 1
    if r < 1: return redirect(url_for("round_view"))
    balance = p["balance"]; next_round = (p["current_round"] <= s["rounds"])
    return render_template("feedback.html", session=s, round_number=r, balance=balance, next_round=next_round)

@app.route("/quiz", methods=["GET","POST"])
def quiz():
    if not g.participant: return redirect(url_for("join"))
    if request.method == "POST": return redirect(url_for("done"))
    return render_template("quiz.html")

@app.route("/svo", methods=["GET","POST"])
def svo():
    if not g.participant: return redirect(url_for("join"))
    if request.method == "POST": return redirect(url_for("done"))
    return render_template("svo.html")

@app.route("/done")
def done(): return render_template("done.html")

# --- Admin (password gate) ---
@app.route("/admin_login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            flask_session["admin_ok"] = True; return redirect(url_for("admin"))
        return render_template("admin_login.html", error="Falsches Passwort.")
    return render_template("admin_login.html", error=None)

def require_admin(): return bool(flask_session.get("admin_ok"))

@app.route("/admin", methods=["GET","POST"])
def admin():
    if not require_admin(): return redirect(url_for("admin_login"))
    con = db()
    if request.method == "POST":
        name = request.form.get("name", f"Session {datetime.datetime.now():%Y%m%d-%H%M}")
        group_size = int(request.form.get("group_size", "6")); rounds = int(request.form.get("rounds", "20"))
        cvac = float(request.form.get("cvac", "40")); alpha = float(request.form.get("alpha", "0.3")); cinf = float(request.form.get("cinf", "100"))
        subsidy = int(request.form.get("subsidy", "0")); subsidy_amount = float(request.form.get("subsidy_amount", "5"))
        starting_balance = 500.0; sid = str(uuid.uuid4())
        con.execute("""INSERT INTO sessions (id,name,group_size,rounds,cvac,alpha,cinf,subsidy,subsidy_amount,starting_balance,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (sid, name, group_size, rounds, cvac, alpha, cinf, subsidy, subsidy_amount, starting_balance, datetime.datetime.utcnow().isoformat()))
        for _ in range(group_size):
            pid = str(uuid.uuid4())
            while True:
                code = (string.ascii_uppercase + string.digits).replace("O","").replace("0","").replace("I","").replace("1","")
                code = "".join(random.choice(code) for _ in range(6))
                if not con.execute("SELECT 1 FROM participants WHERE code=?", (code,)).fetchone(): break
            theta = 0.8; lambd = 0.8
            con.execute("""INSERT INTO participants (id,session_id,code,theta,lambda,alias,joined,current_round,balance,created_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (pid, sid, code, theta, lambd, None, 0, 1, starting_balance, datetime.datetime.utcnow().isoformat()))
        con.commit(); return redirect(url_for("admin"))
    rows = con.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
    sessions = []
    for s in rows:
        ps = con.execute("SELECT code FROM participants WHERE session_id=? ORDER BY code", (s["id"],)).fetchall()
        sessions.append({**dict(s), "participants":[dict(p) for p in ps]})
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return render_template("admin.html", sessions=sessions, now=now)

@app.route("/monitor")
def monitor():
    if not require_admin(): return redirect(url_for("admin_login"))
    sid = request.args.get("session_id"); 
    if not sid: return redirect(url_for("admin"))
    con = db(); s = con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    r = con.execute("SELECT MIN(current_round) AS r FROM participants WHERE session_id=?", (sid,)).fetchone()["r"] or 1
    return render_template("monitor.html", session=s, round_number=r)

@app.route("/monitor_status")
def monitor_status():
    if not require_admin(): return ("Forbidden", 403)
    sid = request.args.get("session_id"); r = int(request.args.get("round") or 1)
    con = db()
    rows = con.execute("""SELECT p.code, p.alias, p.joined, p.current_round,
               EXISTS(SELECT 1 FROM decisions d WHERE d.participant_id=p.id AND d.round_number=?) AS decided
               FROM participants p WHERE p.session_id=? ORDER BY p.code""", (r, sid)).fetchall()
    participants = [{
        "code": row["code"], "alias": row["alias"], "joined": bool(row["joined"]),
        "current_round": row["current_round"], "decided": bool(row["decided"]),
    } for row in rows]
    return jsonify({"participants": participants})

@app.route("/export_db")
def export_db():
    if not require_admin(): return redirect(url_for("admin_login"))
    return send_file(DB_PATH, as_attachment=True, download_name="game.db")

# --- Chat (robust) ---
@socketio.on('join_room')
def on_join_room(data):
    pid = flask_session.get("participant_id")
    if not pid: return
    con = db()
    p = con.execute("SELECT * FROM participants WHERE id=?", (pid,)).fetchone()
    if not p:
        flask_session.pop("participant_id", None); return
    room = p["session_id"]
    join_room(room)
    rows = con.execute("""SELECT alias, text, created_at FROM chat_messages
                         WHERE session_id=? ORDER BY id DESC LIMIT 50""", (room,)).fetchall()
    arr = [{
        "alias": row["alias"] or (p["alias"] or p["code"]),
        "text": row["text"],
        "ts": row["created_at"].replace("T"," ")[:19],
    } for row in rows][::-1]
    emit('history', arr)

@socketio.on('send_message')
def on_send_message(data):
    pid = flask_session.get("participant_id")
    if not pid: return
    text_msg = (data.get('text') or "").strip()
    if not text_msg: return
    con = db(); p = con.execute("SELECT * FROM participants WHERE id=?", (pid,)).fetchone()
    if not p:
        flask_session.pop("participant_id", None); return
    room = p["session_id"]; alias = p["alias"] or p["code"]
    ts = datetime.datetime.utcnow().isoformat()
    con.execute("INSERT INTO chat_messages (session_id, participant_id, alias, text, created_at) VALUES (?,?,?,?,?)", (room, pid, alias, text_msg, ts)); con.commit()
    emit('message', {"alias": alias, "text": text_msg, "ts": ts.replace("T"," ")[:19]}, to=room)

if __name__ == "__main__":
    init_db()
    socketio.run(app, host="127.0.0.1", port=5000, debug=True)
