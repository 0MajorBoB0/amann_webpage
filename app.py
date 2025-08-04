from flask import Flask, request, render_template_string, send_file
import csv, io, datetime, os

app = Flask(__name__)
LOG = "game_log.csv"

if not os.path.exists(LOG):
    with open(LOG, "w", newline="") as f:
        csv.writer(f).writerow(["timestamp", "decision"])

TEMPLATE = """
<!DOCTYPE html><html lang="de">
<head><meta charset="UTF-8"><title>Gefangenendilemma</title></head>
<body style="font-family:Arial;text-align:center;margin-top:50px">
  <h1>Gefangenendilemma – Testversion</h1>
  <p>Wähle deine Strategie:</p>
  <form method="post">
    <button name="d" value="kooperieren">Kooperieren</button>
    <button name="d" value="verraten">Verraten</button>
  </form>
  {% if choice %}
    <p style="margin-top:30px;font-size:1.2em">
      Du hast <strong>{{ choice }}</strong> gewählt. Danke fürs Mitmachen!
    </p>
  {% endif %}
  <p style="margin-top:60px;font-size:0.8em">
    <a href="/download">Ergebnisse herunterladen (CSV)</a>
  </p>
</body></html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    choice = None
    if request.method == "POST":
        choice = request.form["d"]
        with open(LOG, "a", newline="") as f:
            csv.writer(f).writerow([datetime.datetime.utcnow().isoformat(), choice])
    return render_template_string(TEMPLATE, choice=choice)

@app.route("/download")
def download():
    # CSV als Download streamen
    return send_file(LOG, mimetype="text/csv",
                     as_attachment=True, download_name="dilemma_daten.csv")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)