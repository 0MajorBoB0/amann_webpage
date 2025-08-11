import os, sqlite3, uuid, random, string, datetime, io
from datetime import timedelta
from flask import (
    Flask, request, redirect, render_template, session as flask_session,
    url_for, send_file, jsonify, g
)
from flask_socketio import SocketIO, join_room, emit

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "game.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ManarHolgerErwin!")

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, "templates"),
    static_folder=os.path.join(APP_DIR, "static"),
)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
app.config["TEMPLATES_AUTO_RELOAD"] = True
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")


# -------------------- DB helpers --------------------
def db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def ensure_column(con, table, column, definition):
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        con.commit()

def ensure_archive_schema(con, table):
    """Stellt sicher, dass archived_<table> dieselben Spalten hat wie <table>."""
    base_cols = con.execute(f"PRAGMA table_info({table})").fetchall()
    arch_cols = {r[1] for r in con.execute(f"PRAGMA table_info(archived_{table})").fetchall()}
    for r in base_cols:
        name = r[1]; coltype = r[2] or "TEXT"; dflt = r[4]
        if name not in arch_cols:
            if dflt is None:
                con.execute(f"ALTER TABLE archived_{table} ADD COLUMN {name} {coltype}")
            else:
                con.execute(f"ALTER TABLE archived_{table} ADD COLUMN {name} {coltype} DEFAULT {dflt}")
            con.commit()

# ---- UTC helper (für stabile Countdowns) ----
def utc_now():
    return datetime.datetime.utcnow().replace(microsecond=0)

def iso_utc(dt: datetime.datetime) -> str:
    return dt.replace(microsecond=0).isoformat() + "Z"

def parse_iso_utc(s: str) -> datetime.datetime:
    s = (s or "").rstrip("Z")
    return datetime.datetime.fromisoformat(s)


def init_db():
    con = db()
    # Haupt-Tabellen
    con.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY, name TEXT, group_size INTEGER, rounds INTEGER,
        cvac REAL, alpha REAL, cinf REAL, subsidy INTEGER DEFAULT 0, subsidy_amount REAL DEFAULT 0,
        regime TEXT, starting_balance REAL DEFAULT 500, created_at TEXT,
        archived INTEGER DEFAULT 0,
        reveal_window INTEGER DEFAULT 5,   -- Entscheidungsphase (Sek.)
        watch_time INTEGER DEFAULT 15      -- Watchtime (Sek.)
    )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS participants (
        id TEXT PRIMARY KEY, session_id TEXT, code TEXT UNIQUE, theta REAL, lambda REAL, alias TEXT,
        joined INTEGER DEFAULT 0, current_round INTEGER DEFAULT 1, balance REAL DEFAULT 0,
        completed INTEGER DEFAULT 0, created_at TEXT)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, participant_id TEXT,
        round_number INTEGER, choice TEXT, a_cost REAL, b_cost REAL, total_cost REAL, created_at TEXT,
        reveal INTEGER)"""  # 1=zeigen, 0=geheim, NULL=keine Angabe
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, participant_id TEXT, alias TEXT, text TEXT, created_at TEXT)"""
    )
    con.commit()

    # Idempotente Migrationen
    ensure_column(con, "participants", "alias", "TEXT")
    ensure_column(con, "participants", "completed", "INTEGER DEFAULT 0")
    ensure_column(con, "sessions", "archived", "INTEGER DEFAULT 0")
    ensure_column(con, "sessions", "reveal_window", "INTEGER DEFAULT 5")
    ensure_column(con, "sessions", "watch_time", "INTEGER DEFAULT 15")
    ensure_column(con, "decisions", "reveal", "INTEGER")

    # Reveal-Phasen je Runde
    con.execute("""
        CREATE TABLE IF NOT EXISTS round_phases (
            session_id TEXT,
            round_number INTEGER,
            decision_ends_at TEXT,
            watch_ends_at TEXT,
            created_at TEXT,
            PRIMARY KEY (session_id, round_number)
        )
    """)
    con.commit()

    # Archiv-Tabellen anlegen (starten leer) und Schema synchronisieren
    con.execute("""CREATE TABLE IF NOT EXISTS archived_sessions AS SELECT * FROM sessions WHERE 0""")
    con.execute("""CREATE TABLE IF NOT EXISTS archived_participants AS SELECT * FROM participants WHERE 0""")
    con.execute("""CREATE TABLE IF NOT EXISTS archived_decisions AS SELECT * FROM decisions WHERE 0""")
    con.execute("""CREATE TABLE IF NOT EXISTS archived_chat_messages AS SELECT * FROM chat_messages WHERE 0""")
    con.commit()
    ensure_archive_schema(con, "sessions")
    ensure_archive_schema(con, "participants")
    ensure_archive_schema(con, "decisions")
    ensure_archive_schema(con, "chat_messages")


# -------------------- Session/Participant context --------------------
@app.before_request
def load_participant():
    pid = flask_session.get("participant_id")
    g.participant = None
    if pid:
        con = db()
        g.participant = con.execute("SELECT * FROM participants WHERE id=?", (pid,)).fetchone()

def create_code(n=6):
    alphabet = (string.ascii_uppercase + string.digits).replace("O", "").replace("0", "").replace("I", "").replace("1", "")
    return "".join(random.choice(alphabet) for _ in range(n))


# -------------------- Public routes --------------------
@app.route("/")
def index():
    if g.participant:
        return redirect(determine_next_url(g.participant))
    return redirect(url_for("join"))

@app.route("/logout")
def logout():
    flask_session.pop("participant_id", None)
    return redirect(url_for("join"))

@app.route("/me")
def me():
    if not g.participant:
        return ("", 401)
    con = db()
    s = con.execute("SELECT id,name FROM sessions WHERE id=?", (g.participant["session_id"],)).fetchone()
    return jsonify({"code": g.participant["code"], "alias": g.participant["alias"], "session_id": s["id"], "session_name": s["name"]})

@app.route("/join", methods=["GET", "POST"])
def join():
    con = db()
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        alias = request.form.get("alias", "").strip()
        p = con.execute("SELECT * FROM participants WHERE code=?", (code,)).fetchone()
        if not p:
            return render_template("join.html", error="Code unbekannt.")
        if p["completed"]:
            return render_template("join.html", error="Dieser Code wurde bereits abgeschlossen. Bitte neuen Code verwenden.")
        flask_session["participant_id"] = p["id"]
        con.execute("UPDATE participants SET joined=1 WHERE id=?", (p["id"],))
        if alias:
            con.execute("UPDATE participants SET alias=? WHERE id=?", (alias, p["id"]))
        con.commit()
        return redirect(determine_next_url(p))
    return render_template("join.html", error=None)

@app.route("/alias", methods=["POST"])
def alias():
    if not g.participant:
        return redirect(url_for("join"))
    a = request.form.get("alias", "").strip()
    if a:
        con = db()
        con.execute("UPDATE participants SET alias=? WHERE id=?", (a, g.participant["id"]))
        con.commit()
    return redirect(url_for("lobby"))

def determine_next_url(p_row):
    con = db()
    p = con.execute("SELECT * FROM participants WHERE id=?", (p_row["id"],)).fetchone()
    s = con.execute("SELECT * FROM sessions WHERE id=?", (p["session_id"],)).fetchone()
    if s["archived"]:
        return url_for("done")
    joined = con.execute(
        "SELECT COUNT(*) c FROM participants WHERE session_id=? AND joined=1", (s["id"],)
    ).fetchone()["c"]
    if joined < s["group_size"]:
        return url_for("lobby")
    if p["current_round"] > s["rounds"]:
        return url_for("done")
    decided = con.execute(
        "SELECT 1 FROM decisions WHERE participant_id=? AND round_number=?", (p["id"], p["current_round"])
    ).fetchone()
    return url_for("wait_view") if decided else url_for("round_view")

@app.route("/lobby")
def lobby():
    if not g.participant:
        return redirect(url_for("join"))
    con = db()
    s = con.execute("SELECT * FROM sessions WHERE id=?", (g.participant["session_id"],)).fetchone()
    joined = con.execute(
        "SELECT COUNT(*) c FROM participants WHERE session_id=? AND joined=1", (s["id"],)
    ).fetchone()["c"]
    return render_template("lobby.html", session=s, participant=g.participant, joined=joined)

@app.route("/lobby_status")
def lobby_status():
    sid = request.args.get("session_id")
    con = db()
    s = con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    joined = con.execute(
        "SELECT COUNT(*) c FROM participants WHERE session_id=? AND joined=1", (sid,)
    ).fetchone()["c"]
    return jsonify({"joined": joined, "group_size": s["group_size"], "ready": joined >= s["group_size"]})

@app.route("/round")
def round_view():
    if not g.participant:
        return redirect(url_for("join"))
    con = db()
    p = g.participant
    s = con.execute("SELECT * FROM sessions WHERE id=?", (p["session_id"],)).fetchone()
    if s["archived"]:
        return redirect(url_for("done"))
    joined = con.execute(
        "SELECT COUNT(*) c FROM participants WHERE session_id=? AND joined=1", (s["id"],)
    ).fetchone()["c"]
    if joined < s["group_size"]:
        return redirect(url_for("lobby"))
    r = p["current_round"]
    if r > s["rounds"]:
        return redirect(url_for("done"))
    a_cost_preview = max(p["theta"] * (s["cvac"] - (s["subsidy_amount"] if s["subsidy"] else 0)), 0)
    b_cost_max = p["lambda"] * s["alpha"] * 1.0 * s["cinf"]
    return render_template("round.html", session=s, round_number=r, a_cost_preview=round(a_cost_preview, 2), b_cost_max=b_cost_max)

@app.route("/choose", methods=["POST"])
def choose():
    if not g.participant:
        return ("No participant", 400)
    data = request.get_json() or {}
    choice = data.get("choice")
    if choice not in ("A", "B"):
        return ("Invalid choice", 400)
    con = db()
    p = g.participant
    s = con.execute("SELECT * FROM sessions WHERE id=?", (p["session_id"],)).fetchone()
    r = p["current_round"]
    already = con.execute(
        "SELECT 1 FROM decisions WHERE participant_id=? AND round_number=?", (p["id"], r)
    ).fetchone()
    if not already:
        con.execute(
            "INSERT INTO decisions (session_id, participant_id, round_number, choice, created_at) VALUES (?,?,?,?,?)",
            (s["id"], p["id"], r, choice, utc_now().isoformat()),
        )
        con.commit()
    return ("OK", 200)

@app.route("/wait")
def wait_view():
    if not g.participant:
        return redirect(url_for("join"))
    con = db()
    p = g.participant
    s = con.execute("SELECT * FROM sessions WHERE id=?", (p["session_id"],)).fetchone()
    if s["archived"]:
        return redirect(url_for("done"))
    r = p["current_round"]
    decided = con.execute(
        "SELECT COUNT(*) c FROM decisions WHERE session_id=? AND round_number=?", (s["id"], r)
    ).fetchone()["c"]
    return render_template("wait.html", session=s, round_number=r, decided=decided)

@app.route("/round_status")
def round_status():
    sid = request.args.get("session_id")
    r = int(request.args.get("round"))
    con = db()
    s = con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    decided = con.execute(
        "SELECT COUNT(*) c FROM decisions WHERE session_id=? AND round_number=?", (sid, r)
    ).fetchone()["c"]
    ready = decided >= s["group_size"]
    if ready:
        missing = con.execute(
            "SELECT COUNT(*) c FROM decisions WHERE session_id=? AND round_number=? AND total_cost IS NULL",
            (sid, r),
        ).fetchone()["c"]
        if missing > 0:
            rows = con.execute(
                """SELECT d.id, d.participant_id, d.choice, p.theta, p.lambda
                   FROM decisions d JOIN participants p ON p.id=d.participant_id
                   WHERE d.session_id=? AND d.round_number=?""",
                (sid, r),
            ).fetchall()
            b_players = [row for row in rows if row["choice"] == "B"]
            b_count = len(b_players)
            N = s["group_size"]
            alpha = s["alpha"]
            cinf = s["cinf"]
            updates = []
            for row in rows:
                if row["choice"] == "A":
                    a_cost = max(row["theta"] * (s["cvac"] - (s["subsidy_amount"] if s["subsidy"] else 0)), 0)
                    b_cost_val = None
                    total = a_cost
                else:
                    share_others = (b_count - 1) / (N - 1) if N > 1 else 0.0
                    b_cost_val = row["lambda"] * alpha * share_others * cinf
                    a_cost = None
                    total = b_cost_val
                updates.append((a_cost, b_cost_val, total, row["id"]))
            for a_cost, b_cost_val, total, did in updates:
                con.execute("UPDATE decisions SET a_cost=?, b_cost=?, total_cost=? WHERE id=?", (a_cost, b_cost_val, total, did))
            con.commit()
            # Balance niemals < 0
            for c in con.execute(
                "SELECT participant_id, total_cost FROM decisions WHERE session_id=? AND round_number=?", (sid, r)
            ):
                con.execute(
                    """UPDATE participants
                       SET balance = MAX(COALESCE(balance,0) - ?, 0),
                           current_round = current_round
                       WHERE id=?""",
                    (c["total_cost"], c["participant_id"]),
                )
            con.commit()
            # nächste Runde „schalten“
            con.execute(
                "UPDATE participants SET current_round = current_round + 1 WHERE session_id=? AND current_round=?",
                (sid, r),
            )
            con.commit()
            # Reveal-Phasenfenster für die soeben abgeschlossene Runde anlegen
            phase_exist = con.execute(
                "SELECT 1 FROM round_phases WHERE session_id=? AND round_number=?",
                (sid, r)
            ).fetchone()
            if not phase_exist:
                dec_sec = int(s["reveal_window"] or 5)
                watch_sec = int(s["watch_time"] or 15)
                now = utc_now()
                decision_ends = now + timedelta(seconds=dec_sec)
                watch_ends = decision_ends + timedelta(seconds=watch_sec)
                con.execute(
                    "INSERT INTO round_phases (session_id,round_number,decision_ends_at,watch_ends_at,created_at) VALUES (?,?,?,?,?)",
                    (sid, r, iso_utc(decision_ends), iso_utc(watch_ends), iso_utc(now))
                )
                con.commit()
    decided_codes = [
        row["code"]
        for row in con.execute(
            """SELECT p.code FROM decisions d JOIN participants p ON p.id=d.participant_id
               WHERE d.session_id=? AND d.round_number=? ORDER BY p.code""",
            (sid, r),
        ).fetchall()
    ]
    return jsonify({"decided": decided, "ready": ready, "decided_codes": decided_codes})

@app.route("/reveal")
def reveal():
    if not g.participant:
        return redirect(url_for("join"))
    con = db()
    p = g.participant
    s = con.execute("SELECT * FROM sessions WHERE id=?", (p["session_id"],)).fetchone()
    r = p["current_round"] - 1
    if r < 1:
        return redirect(url_for("round_view"))
    return render_template("reveal.html", session=s, round_number=r)

@app.post("/reveal_choose")
def reveal_choose():
    if not g.participant:
        return ("No participant", 400)
    con = db()
    p = g.participant
    s = con.execute("SELECT * FROM sessions WHERE id=?", (p["session_id"],)).fetchone()
    r = p["current_round"] - 1
    if r < 1:
        return ("Too early", 400)
    ph = con.execute("SELECT decision_ends_at FROM round_phases WHERE session_id=? AND round_number=?", (s["id"], r)).fetchone()
    if not ph:
        return ("No phase", 400)
    if utc_now() > parse_iso_utc(ph["decision_ends_at"]):
        return ("Phase over", 409)
    data = request.get_json() or {}
    val = data.get("reveal")
    if val not in (0,1,True,False):
        return ("Bad", 400)
    val = 1 if val in (1,True) else 0
    con.execute(
        "UPDATE decisions SET reveal=? WHERE participant_id=? AND round_number=?",
        (val, p["id"], r)
    )
    con.commit()
    return ("OK", 200)

@app.get("/reveal_status")
def reveal_status():
    sid = request.args.get("session_id")
    r = int(request.args.get("round") or 0)
    con = db()
    s = con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s or r < 1:
        return jsonify({"err":"bad"}), 400

    ph = con.execute(
        "SELECT decision_ends_at, watch_ends_at FROM round_phases WHERE session_id=? AND round_number=?",
        (sid, r)
    ).fetchone()
    now = utc_now()
    phase = "decision"
    ends_at = iso_utc(now)

    if ph:
        dec_end = parse_iso_utc(ph["decision_ends_at"])
        wat_end = parse_iso_utc(ph["watch_ends_at"])
        if now < dec_end:
            phase = "decision"; ends_at = ph["decision_ends_at"] if ph["decision_ends_at"].endswith("Z") else ph["decision_ends_at"] + "Z"
        elif now < wat_end:
            con.execute("UPDATE decisions SET reveal=0 WHERE session_id=? AND round_number=? AND reveal IS NULL", (sid, r))
            con.commit()
            phase = "watch"; ends_at = ph["watch_ends_at"] if ph["watch_ends_at"].endswith("Z") else ph["watch_ends_at"] + "Z"
        else:
            con.execute("UPDATE decisions SET reveal=0 WHERE session_id=? AND round_number=? AND reveal IS NULL", (sid, r))
            con.commit()
            phase = "done"; ends_at = iso_utc(now)
    else:
        phase = "done"; ends_at = iso_utc(now)

    rows = con.execute("""
        SELECT p.id as pid, p.code, p.alias,
               EXISTS(SELECT 1 FROM decisions d2 WHERE d2.participant_id=p.id AND d2.round_number=?) AS has_decided,
               d.choice, d.reveal
        FROM participants p
        LEFT JOIN decisions d ON d.participant_id=p.id AND d.round_number=?
        WHERE p.session_id=?
        ORDER BY p.code
    """, (r, r, sid)).fetchall()
    players = []
    decided_reveal = 0
    me = None
    for row in rows:
        if row["reveal"] is not None:
            decided_reveal += 1
        obj = {
            "code": row["code"],
            "alias": row["alias"],
            "has_decided": bool(row["has_decided"]),
            "choice": row["choice"],
            "reveal": row["reveal"] if row["reveal"] is not None else None
        }
        players.append(obj)
        if g.participant and row["pid"] == g.participant["id"]:
            me = obj

    return jsonify({
        "phase": phase,
        "ends_at": ends_at,
        "total": len(players),
        "decided_reveal": decided_reveal,
        "players": players,
        "me": me
    })

@app.route("/feedback")
def feedback():
    if not g.participant:
        return redirect(url_for("join"))
    con = db()
    p = g.participant
    s = con.execute("SELECT * FROM sessions WHERE id=?", (p["session_id"],)).fetchone()
    r = p["current_round"] - 1
    if r < 1:
        return redirect(url_for("round_view"))
    balance = p["balance"]
    next_round = (not s["archived"]) and (p["current_round"] <= s["rounds"])
    return render_template("feedback.html", session=s, round_number=r, balance=balance, next_round=next_round)

@app.route("/quiz", methods=["GET", "POST"])
def quiz():
    if not g.participant:
        return redirect(url_for("join"))
    if request.method == "POST":
        return redirect(url_for("done"))
    return render_template("quiz.html")

@app.route("/svo", methods=["GET", "POST"])
def svo():
    if not g.participant:
        return redirect(url_for("join"))
    if request.method == "POST":
        return redirect(url_for("done"))
    return render_template("svo.html")

@app.route("/done")
def done():
    con = db()
    pid = flask_session.get("participant_id")
    balance = None
    code = None
    if pid:
        row = con.execute("SELECT code, balance FROM participants WHERE id=?", (pid,)).fetchone()
        if row:
            balance = row["balance"]
            code = row["code"]
            con.execute("UPDATE participants SET completed=1 WHERE id=?", (pid,))
            con.commit()
    flask_session.pop("participant_id", None)
    return render_template("done.html", balance=balance, code=code)


# -------------------- Admin auth --------------------
@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            flask_session["admin_ok"] = True
            return redirect(url_for("admin"))
        return render_template("admin_login.html", error="Falsches Passwort.")
    return render_template("admin_login.html", error=None)

def require_admin():
    return bool(flask_session.get("admin_ok"))


# -------------------- Admin helpers --------------------
def broadcast(room_id: str, event: str, payload=None):
    socketio.emit(event, payload or {}, to=room_id)

def _session_done(con, sid):
    row = con.execute("SELECT group_size, rounds FROM sessions WHERE id=?", (sid,)).fetchone()
    if not row:
        return False
    grp = row["group_size"]
    rmax = row["rounds"]
    cnt = con.execute("SELECT COUNT(*) c FROM participants WHERE session_id=? AND current_round > ?", (sid, rmax)).fetchone()["c"]
    return cnt >= grp


# -------------------- Admin main --------------------
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not require_admin():
        return redirect(url_for("admin_login"))
    con = db()
    if request.method == "POST":
        name = request.form.get("name", f"Session {datetime.datetime.now():%Y%m%d-%H%M}")
        group_size = int(request.form.get("group_size", "6"))
        rounds = int(request.form.get("rounds", "20"))
        cvac = float(request.form.get("cvac", "40"))
        alpha = float(request.form.get("alpha", "0.3"))
        cinf = float(request.form.get("cinf", "100"))
        subsidy = int(request.form.get("subsidy", "0"))
        subsidy_amount = float(request.form.get("subsidy_amount", "5"))
        reveal_window = int(request.form.get("reveal_window", "5"))
        watch_time = int(request.form.get("watch_time", "15"))

        starting_balance = 500.0
        sid = str(uuid.uuid4())

        con.execute("""
            INSERT INTO sessions
            (id, name, group_size, rounds, cvac, alpha, cinf, subsidy, subsidy_amount,
             starting_balance, created_at, archived, reveal_window, watch_time)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            sid, name, group_size, rounds, cvac, alpha, cinf, subsidy, subsidy_amount,
            starting_balance, utc_now().isoformat(), 0, reveal_window, watch_time
        ))

        for _ in range(group_size):
            pid = str(uuid.uuid4())
            while True:
                codechars = (string.ascii_uppercase + string.digits).replace("O","").replace("0","").replace("I","").replace("1","")
                code = "".join(random.choice(codechars) for _ in range(6))
                if not con.execute("SELECT 1 FROM participants WHERE code=?", (code,)).fetchone():
                    break
            theta = 0.8; lambd = 0.8
            con.execute(
                """INSERT INTO participants (id,session_id,code,theta,lambda,alias,joined,current_round,balance,completed,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (pid, sid, code, theta, lambd, None, 0, 1, starting_balance, 0, utc_now().isoformat()),
            )
        con.commit()
        return redirect(url_for("admin"))

    rows = con.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
    sessions_active, sessions_done, sessions_arch = [], [], []
    for s in rows:
        ps = con.execute("SELECT code FROM participants WHERE session_id=? ORDER BY code", (s["id"],)).fetchall()
        sdict = {**dict(s), "participants": [dict(p) for p in ps]}
        if s["archived"]:
            sessions_arch.append(sdict)
        else:
            if _session_done(con, s["id"]):
                sessions_done.append(sdict)
            else:
                sessions_active.append(sdict)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return render_template("admin.html",
                           sessions_active=sessions_active,
                           sessions_done=sessions_done,
                           sessions_arch=sessions_arch,
                           now=now, admin_tab_guard=True)

@app.post("/admin/reset_session")
def admin_reset_session():
    if not require_admin():
        return redirect(url_for("admin_login"))
    sid = request.form.get("session_id")
    con = db()
    s = con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s: return redirect(url_for("admin"))
    con.execute("DELETE FROM decisions WHERE session_id=?", (sid,))
    con.execute("DELETE FROM chat_messages WHERE session_id=?", (sid,))
    con.execute("DELETE FROM round_phases WHERE session_id=?", (sid,))
    con.execute(
        "UPDATE participants SET current_round=1, balance=?, completed=0 WHERE session_id=?",
        (s["starting_balance"], sid),
    )
    con.commit()
    con.execute("UPDATE sessions SET archived=0 WHERE id=?", (sid,))
    con.commit()
    broadcast(sid, "session_reset", {"goto": "/lobby"})
    return redirect(url_for("admin"))

@app.post("/admin/archive_session")
def admin_archive_session():
    if not require_admin():
        return redirect(url_for("admin_login"))
    sid = request.form.get("session_id")
    con = db()
    s = con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s: return redirect(url_for("admin"))
    ensure_archive_schema(con, "sessions")
    ensure_archive_schema(con, "participants")
    ensure_archive_schema(con, "decisions")
    ensure_archive_schema(con, "chat_messages")
    if not s["archived"]:
        con.execute("INSERT INTO archived_sessions SELECT * FROM sessions WHERE id=?", (sid,))
        con.execute("INSERT INTO archived_participants SELECT * FROM participants WHERE session_id=?", (sid,))
        con.execute("INSERT INTO archived_decisions SELECT * FROM decisions WHERE session_id=?", (sid,))
        con.execute("INSERT INTO archived_chat_messages SELECT * FROM chat_messages WHERE session_id=?", (sid,))
        con.execute("UPDATE sessions SET archived=1 WHERE id=?", (sid,))
        con.execute("UPDATE participants SET completed=1 WHERE session_id=?", (sid,))
        con.commit()
    broadcast(sid, "session_archived", {"goto": "/done"})
    return redirect(url_for("admin"))

@app.post("/admin/delete_session")
def admin_delete_session():
    if not require_admin():
        return redirect(url_for("admin_login"))
    sid = request.form.get("session_id")
    con = db()
    exists = con.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone()
    if not exists: return redirect(url_for("admin"))
    broadcast(sid, "session_deleted", {"goto": "/join"})
    con.execute("DELETE FROM decisions WHERE session_id=?", (sid,))
    con.execute("DELETE FROM chat_messages WHERE session_id=?", (sid,))
    con.execute("DELETE FROM round_phases WHERE session_id=?", (sid,))
    con.execute("DELETE FROM participants WHERE session_id=?", (sid,))
    con.execute("DELETE FROM sessions WHERE id=?", (sid,))
    con.commit()
    return redirect(url_for("admin"))

@app.get("/admin/session/<session_id>")
def admin_session_view(session_id):
    if not require_admin(): return redirect(url_for("admin_login"))
    con = db()
    s = con.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not s: return redirect(url_for("admin"))
    r = con.execute("SELECT MIN(current_round) AS r FROM participants WHERE session_id=?", (session_id,)).fetchone()["r"] or 1
    return render_template("admin_session.html", session=s, round_number=r)

@app.get("/admin/session_status")
def admin_session_status():
    if not require_admin(): return ("Forbidden", 403)
    sid = request.args.get("session_id")
    con = db()
    srow = con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if not srow: return jsonify({"participants": [], "decided_count": 0, "session": None})
    r = con.execute("SELECT MIN(current_round) AS r FROM participants WHERE session_id=?", (sid,)).fetchone()["r"] or 1
    rows = con.execute(
        """SELECT p.id, p.code, p.alias, p.balance, p.current_round,
                  EXISTS(SELECT 1 FROM decisions d WHERE d.participant_id=p.id AND d.round_number=?) AS decided,
                  (SELECT d.choice FROM decisions d WHERE d.participant_id=p.id AND d.round_number=? LIMIT 1) AS choice
           FROM participants p WHERE p.session_id=? ORDER BY p.code""", (r, r, sid)
    ).fetchall()
    participants = [{
        "id": rr["id"], "code": rr["code"], "alias": rr["alias"],
        "balance": rr["balance"], "current_round": rr["current_round"],
        "decided": bool(rr["decided"]), "choice": rr["choice"]
    } for rr in rows]
    decided_count = sum(1 for x in participants if x["decided"])
    return jsonify({"participants": participants, "decided_count": decided_count,
                    "session": {"id": srow["id"], "current_round": r}})

@app.get("/admin/session_chat")
def admin_session_chat():
    if not require_admin(): return ("Forbidden", 403)
    sid = request.args.get("session_id")
    con = db()
    rows = con.execute("""SELECT alias, text, created_at FROM chat_messages
                          WHERE session_id=? ORDER BY id ASC""", (sid,)).fetchall()
    msgs = [{"alias": row["alias"], "text": row["text"], "ts": row["created_at"].replace("T"," ")[:19]} for row in rows]
    return jsonify(msgs)

@app.get("/admin/export_session_xlsx")
def export_session_xlsx():
    if not require_admin(): return redirect(url_for("admin_login"))
    sid = request.args.get("session_id")
    con = db()
    s = con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s: return redirect(url_for("admin"))
    params = dict(s)
    participants = [dict(r) for r in con.execute(
        "SELECT code, alias, joined, current_round, balance, completed, created_at FROM participants WHERE session_id=? ORDER BY code",
        (sid,)
    ).fetchall()]
    decisions = [dict(r) for r in con.execute(
        """SELECT p.code, p.alias, d.round_number, d.choice, d.a_cost, d.b_cost, d.total_cost, d.reveal, d.created_at
           FROM decisions d JOIN participants p ON p.id=d.participant_id
           WHERE d.session_id=? ORDER BY d.created_at ASC""",
        (sid,)
    ).fetchall()]
    chats = [dict(r) for r in con.execute(
        "SELECT alias, text, created_at FROM chat_messages WHERE session_id=? ORDER BY id ASC", (sid,)
    ).fetchall()]
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active; ws.title = "Parameters"
    for i, (k, v) in enumerate(params.items(), start=1):
        ws.cell(row=i, column=1, value=k)
        ws.cell(row=i, column=2, value=v)
    ws2 = wb.create_sheet("Participants")
    if participants:
        headers = list(participants[0].keys()); ws2.append(headers)
        for row in participants: ws2.append([row[h] for h in headers])
    ws3 = wb.create_sheet("Decisions")
    if decisions:
        headers = list(decisions[0].keys()); ws3.append(headers)
        for row in decisions: ws3.append([row[h] for h in headers])
    ws4 = wb.create_sheet("Chat")
    if chats:
        headers = list(chats[0].keys()); ws4.append(headers)
        for row in chats: ws4.append([row[h] for h in headers])
    bio = io.BytesIO(); wb.save(bio); bio.seek(0)
    safe_name = (s["name"] or "Session").replace(" ", "_")
    fname = f"{safe_name}__{s['id'][:8]}__export.xlsx"
    return send_file(bio, as_attachment=True, download_name=fname, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# -------------------- Sockets (Chat) --------------------
@socketio.on("join_room")
def on_join_room(data):
    pid = flask_session.get("participant_id")
    if not pid:
        return
    con = db()
    p = con.execute("SELECT * FROM participants WHERE id=?", (pid,)).fetchone()
    if not p:
        flask_session.pop("participant_id", None)
        return
    room = p["session_id"]
    join_room(room)
    rows = con.execute(
        """SELECT alias, text, created_at FROM chat_messages
           WHERE session_id=? ORDER BY id DESC LIMIT 50""",
        (room,),
    ).fetchall()
    arr = [
        {
            "alias": row["alias"] or (p["alias"] or p["code"]),
            "text": row["text"],
            "ts": row["created_at"].replace("T", " ")[:19],
        }
        for row in rows
    ][::-1]
    emit("history", arr)

@socketio.on("send_message")
def on_send_message(data):
    pid = flask_session.get("participant_id")
    if not pid:
        return
    text_msg = (data.get("text") or "").strip()
    if not text_msg:
        return
    con = db()
    p = con.execute("SELECT * FROM participants WHERE id=?", (pid,)).fetchone()
    if not p:
        flask_session.pop("participant_id", None)
        return
    room = p["session_id"]
    alias = p["alias"] or p["code"]
    ts = utc_now().isoformat()
    con.execute(
        "INSERT INTO chat_messages (session_id, participant_id, alias, text, created_at) VALUES (?,?,?,?,?)",
        (room, pid, alias, text_msg, ts),
    )
    con.commit()
    emit("message", {"alias": alias, "text": text_msg, "ts": ts.replace("T", " ")[:19]}, to=room)


# -------------------- Run --------------------
if __name__ == "__main__":
    init_db()
    socketio.run(app, host="127.0.0.1", port=5000, debug=True)
