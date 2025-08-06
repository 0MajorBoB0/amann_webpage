from flask import Flask, request, render_template_string, session, redirect, url_for
import random, datetime, os
from openpyxl import Workbook, load_workbook

app = Flask(__name__)
app.secret_key = 'dein_geheimer_schluessel'
LOG = "matrix_log.xlsx"

# Excel initialisieren
if not os.path.exists(LOG):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Matrix'
    ws.append([
        'timestamp',
        'CC', 'CD', 'DC', 'DD',  # Payoffs: R, S, T, P
        'entered_S', 'correct'
    ])
    wb.save(LOG)

# Template: show R, T, P read-only, input for S
TEMPLATE = '''
<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><title>Payoff-Lückentest</title></head>
<body style="font-family:Arial;text-align:center;margin-top:50px">
  <h1>Gefangenendilemma – Lückentest</h1>
  <p>Erklärung: Wir generieren drei Auszahlungen automatisch (<em>R</em>, <em>T</em>, <em>P</em>),
     du trägst das letzte <strong>S</strong> (Sucker-Payoff) ein. Es muss gelten: T > R > P > S.</p>
  {% if message %}
    <p style="color:{{ 'green' if correct else 'red' }};font-size:1.1em;">{{ message }}</p>
  {% endif %}
  <form method="post">
    <table style="margin:0 auto;font-size:1.2em;">
      <tr><td>R (Reward)</td><td><input name="R" value="{{ R }}" readonly size="1"></td></tr>
      <tr><td>T (Temptation)</td><td><input name="T" value="{{ T }}" readonly size="1"></td></tr>
      <tr><td>P (Punishment)</td><td><input name="P" value="{{ P }}" readonly size="1"></td></tr>
      <tr><td>S (Sucker-Payoff)</td><td><input name="S" value="" size="1" required></td></tr>
    </table>
    <p><button type="submit">Prüfen &amp; Speichern</button></p>
  </form>
</body>
</html>
'''

@app.route("/", methods=["GET", "POST"])
def test_s():
    # Excel
    wb = load_workbook(LOG)
    ws = wb['Matrix']
    message = None
    correct = False

    if request.method == 'GET':
        # Werte generieren T>R>P>S, alle 1-9
        R = random.randint(3,7)
        P = random.randint(2, R-1)
        S = random.randint(1, P-1)
        T = random.randint(R+1,9)
        # In Session speichern
        session['vals'] = {'R': R, 'P': P, 'S': S, 'T': T}
    else:
        # Eingabe aus Formular
        R,P,T = session['vals']['R'], session['vals']['P'], session['vals']['T']
        S = session['vals']['S']
        try:
            entered = int(request.form['S'])
        except ValueError:
            entered = None
        # Prüfung
        if entered == S:
            correct = True
            message = f"Richtig! S = {S}. Deine Eingabe wurde gespeichert."
        else:
            message = f"Falsch. Versuche es erneut!"
        # Immer speichern
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append([timestamp, R, entered, T, P, entered, correct])
        wb.save(LOG)
        # Wenn korrekt: Redirect auf GET für neuen Test
        if correct:
            return redirect(url_for('test_s'))
    # Beim GET oder falscher Versuch
    vals = session.get('vals', {'R':'?','T':'?','P':'?'})
    return render_template_string(TEMPLATE,
                                  R=vals['R'], T=vals['T'], P=vals['P'],
                                  message=message, correct=correct)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
