# MySQL Setup für PythonAnywhere

## 🎯 Übersicht

Dieses Dokument beschreibt, wie du deine Flask-App von SQLite auf MySQL migrierst für PythonAnywhere.

## ✅ Vorteile MySQL vs. SQLite für 150 Spieler

- ✅ **Concurrent Writes**: Keine Write-Locks bei parallelen Entscheidungen
- ✅ **Performance**: Bessere Performance bei vielen gleichzeitigen Zugriffen
- ✅ **Stabilität**: Keine "database is locked" Fehler
- ✅ **Skalierbar**: Unterstützt 150+ parallele Spieler problemlos

---

## 📋 Setup-Schritte auf PythonAnywhere

### 1. MySQL-Datenbank erstellen

1. Gehe zu **Databases** Tab auf PythonAnywhere
2. Erstelle eine neue MySQL-Datenbank:
   - **Database name**: z.B. `username$gamedb`
   - **MySQL password**: Setze ein sicheres Passwort

3. Notiere dir:
   ```
   DB_HOST: username.mysql.pythonanywhere-services.com
   DB_USER: username
   DB_PASSWORD: [dein Passwort]
   DB_NAME: username$gamedb
   DB_PORT: 3306
   ```

### 2. Umgebungsvariablen setzen

Erstelle/editiere `.env` Datei auf PythonAnywhere:

```bash
# Im PythonAnywhere Bash Console:
cd /home/username/amann_webpage
nano .env
```

Füge hinzu:
```env
# Existing
ADMIN_PASSWORD=dein_admin_passwort
SECRET_KEY=dein_geheimer_key

# MySQL Config (NEU!)
DB_HOST=username.mysql.pythonanywhere-services.com
DB_USER=username
DB_PASSWORD=dein_mysql_passwort
DB_NAME=username$gamedb
DB_PORT=3306
```

**WICHTIG**: In PythonAnywhere Web App Config:
- Gehe zu **Web** Tab → deine App
- Scroll zu **Environment variables**
- Füge alle Variablen dort ein (nicht nur .env!)

### 3. Dependencies installieren

```bash
cd /home/username/amann_webpage
pip3 install --user PyMySQL cryptography
# oder
pip3 install --user -r requirements.txt
```

### 4. Datenbank initialisieren

```bash
python3
>>> from app import init_db
>>> init_db()
>>> exit()
```

Falls Fehler auftreten:
```python
# Teste MySQL-Verbindung:
import pymysql
conn = pymysql.connect(
    host='username.mysql.pythonanywhere-services.com',
    user='username',
    password='dein_passwort',
    database='username$gamedb'
)
print("✅ MySQL Connection OK!")
conn.close()
```

### 5. Web App neu laden

- Gehe zu **Web** Tab
- Klicke **Reload** Button

---

## 🔧 Code-Änderungen (WICHTIG!)

### Status der Konvertierung

✅ **Fertig**:
- MySQL Connection Logic
- Schema-Initialisierung
- requirements.txt

⚠️ **TODO** (manuell nötig):
- Alle `.execute()` Calls: `?` → `%s` ersetzen
- `sqlite3` imports entfernen
- `BEGIN IMMEDIATE` → `START TRANSACTION`
- `INSERT OR REPLACE` → `REPLACE`

### Automatische Konvertierung

Ich habe die kritischen Teile bereits angepasst:
- `init_db()` - MySQL-kompatible Tabellen
- `_finalize_round_atomic()` - MySQL Transaktionen
- Connection Handling

**Verbleibende Arbeit**:
Alle SQL-Queries im Rest der app.py müssen von `?` auf `%s` umgestellt werden.

---

## 🚀 Performance-Optimierungen

### 1. Polling-Intervall erhöhen

**Aktuell**: 2 Sekunden (zu viel Last!)

templates/lobby.html:
```javascript
// Zeile 9: Von 2000 auf 5000 ändern
setInterval(async ()=>{ ... }, 5000);  // war: 2000
```

templates/round.html:
```javascript
// Zeile 100
setInterval(poll, 5000);  // war: 2000
```

templates/wait.html:
```javascript
// Zeile 33
setInterval(poll, 5000);  // war: 2000
```

templates/reveal.html:
```javascript
// Zeile 141
setInterval(pollReady, 5000);  // war: 2000
```

**Effekt**:
- Reduziert Last von 75 req/s auf 30 req/s
- Spart CPU-Budget
- Immer noch responsive genug

### 2. MySQL Connection Pooling (Optional)

Für noch bessere Performance kannst du später Connection Pooling einbauen:

```python
from pymysql import connect
from DBUtils.PooledDB import PooledDB

pool = PooledDB(
    creator=pymysql,
    maxconnections=20,
    host=DB_HOST,
    user=DB_USER,
    password=DB_PASSWORD,
    database=DB_NAME,
    charset='utf8mb4'
)

def db():
    return pool.connection()
```

---

## 📊 Load-Testing

Vor der Studie unbedingt testen!

### Einfacher Test mit curl:
```bash
# 10 parallele Requests
for i in {1..10}; do
  curl -s https://username.pythonanywhere.com/healthz &
done
wait
```

### Professionell mit Locust:

```python
# locustfile.py
from locust import HttpUser, task, between

class GamePlayer(HttpUser):
    wait_time = between(2, 5)

    @task
    def lobby_status(self):
        self.client.get("/lobby_status?session_id=test&participant_id=test")

    @task
    def round_status(self):
        self.client.get("/round_status?session_id=test&round=1")

# Starten:
# locust -f locustfile.py --users 150 --spawn-rate 10
```

---

## ⚠️ Troubleshooting

### Fehler: "No module named 'pymysql'"
```bash
pip3 install --user PyMySQL
```

### Fehler: "Access denied for user"
- Überprüfe DB_USER und DB_PASSWORD in .env
- Überprüfe Environment Variables in Web App Config

### Fehler: "Can't connect to MySQL server"
- Überprüfe DB_HOST (muss `.pythonanywhere-services.com` sein)
- Firewall-Problem? → PythonAnywhere Support kontaktieren

### Fehler: "Column 'xyz' doesn't exist"
- `init_db()` neu ausführen
- Oder: `DROP TABLE xyz; python3 -c "from app import init_db; init_db()"`

### App lädt nicht / 500 Error
- Check Error Log: **Web** Tab → **Error log**
- Check Server Log: **Web** Tab → **Server log**

---

## 📈 Monitoring während der Studie

### CPU Usage checken:
```bash
# Im Bash Console
top -u username
```

### MySQL Connections checken:
```sql
SHOW PROCESSLIST;
SHOW STATUS LIKE 'Threads_connected';
```

### Logs in Echtzeit:
```bash
tail -f /var/log/username.pythonanywhere.com.error.log
```

---

## ✅ Checkliste vor dem Go-Live

- [ ] MySQL-Datenbank erstellt
- [ ] Umgebungsvariablen gesetzt (auch in Web App!)
- [ ] PyMySQL installiert
- [ ] init_db() ausgeführt
- [ ] App neu geladen (Reload)
- [ ] Healthcheck funktioniert: `/healthz`
- [ ] Admin-Login funktioniert
- [ ] Test-Session erstellt
- [ ] Polling auf 5s erhöht
- [ ] Load-Test durchgeführt
- [ ] Backup-Plan vorhanden

---

## 🆘 Support

- PythonAnywhere Help: https://help.pythonanywhere.com/
- MySQL Docs: https://dev.mysql.com/doc/
- PyMySQL Docs: https://pymysql.readthedocs.io/

Bei Fragen: PythonAnywhere Forum oder Discord!
