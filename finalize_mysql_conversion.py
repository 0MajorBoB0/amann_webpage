#!/usr/bin/env python3
"""
Finalisiert die MySQL-Konvertierung von app.py.

Führt folgende Änderungen durch:
1. Ersetzt alle ? Platzhalter durch %s in SQL-Queries
2. Ersetzt sqlite3-spezifische Syntax
3. Erstellt Backup der Originaldatei

WICHTIG: Bitte prüfe die Änderungen manuell nach!
"""

import re
import shutil
from datetime import datetime

def convert_app_py():
    # Backup erstellen
    backup_name = f"app.py.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy('app.py', backup_name)
    print(f"✅ Backup erstellt: {backup_name}")

    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content

    # 1. Ersetze ? durch %s in .execute() Aufrufen
    # Regex findet .execute("...", (...)) und ersetzt ? durch %s
    def replace_in_execute(match):
        execute_call = match.group(0)
        # Ersetze ? durch %s, aber nur in diesem execute call
        return execute_call.replace('?', '%s')

    # Pattern für .execute() mit Parametern
    pattern = r'\.execute\s*\([^)]*\?[^)]*\)'
    content = re.sub(pattern, replace_in_execute, content)

    # 2. SQLite-spezifische Syntax ersetzen
    replacements = {
        'INSERT OR REPLACE': 'REPLACE',
        'BEGIN IMMEDIATE': 'START TRANSACTION',
        'sqlite3.IntegrityError': 'pymysql.IntegrityError',
        'sqlite3.OperationalError': 'pymysql.OperationalError',
    }

    for old, new in replacements.items():
        content = content.replace(old, new)

    # 3. Speichern
    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(content)

    # Statistik
    num_changes = content.count('%s') - original_content.count('%s')
    print(f"\n📊 Konvertierungs-Statistik:")
    print(f"   - {num_changes} Platzhalter konvertiert (? → %s)")
    print(f"   - {len(replacements)} SQLite-Syntaxe ersetzt")

    print(f"\n✅ Konvertierung abgeschlossen!")
    print(f"📄 app.py wurde aktualisiert")
    print(f"💾 Original gesichert als: {backup_name}")

    print(f"\n⚠️  NÄCHSTE SCHRITTE:")
    print(f"   1. Prüfe app.py manuell (diff {backup_name} app.py)")
    print(f"   2. Teste lokal: python3 app.py")
    print(f"   3. Auf PythonAnywhere hochladen")
    print(f"   4. MySQL-Datenbank einrichten (siehe MYSQL_SETUP.md)")

if __name__ == '__main__':
    print("🔧 MySQL-Konvertierungs-Script")
    print("=" * 50)

    response = input("\nMöchtest du app.py für MySQL konvertieren? (j/n): ")
    if response.lower() in ['j', 'ja', 'y', 'yes']:
        convert_app_py()
    else:
        print("Abgebrochen.")
